"""Blender native image/video backend for Frame by Plane layers."""

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

import bpy

from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_warn as _runtime_warn, fbp_set_rna_property_silent,
    fbp_action_fcurves, fbp_remove_action_fcurves,
)
from .layers import set_collection_color_tag, apply_collection_color_to_rig
from .scene_sync import sync_layer_collection


FBP_NATIVE_HOLD_MARGIN = 500
FBP_NATIVE_RENDER_CONTRACT_REVISION = 8
FBP_NATIVE_MEDIA_CACHE_REVISION = 7
FBP_NATIVE_TIMING_REVISION = 6
FBP_NATIVE_VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm', '.mpeg', '.mpg', '.mxf', '.ogv'}
_FBP_NATIVE_MEDIA_IMAGE_CACHE = globals().get("_FBP_NATIVE_MEDIA_IMAGE_CACHE", {})
if not isinstance(_FBP_NATIVE_MEDIA_IMAGE_CACHE, dict):
    _FBP_NATIVE_MEDIA_IMAGE_CACHE = {}
_FBP_NATIVE_MEDIA_IMAGE_CACHE_INDEXED = bool(
    globals().get("_FBP_NATIVE_MEDIA_IMAGE_CACHE_INDEXED", False)
)
_FBP_NATIVE_MEDIA_IMAGE_COUNT = int(
    globals().get("_FBP_NATIVE_MEDIA_IMAGE_COUNT", -1) or -1
)
_FBP_NATIVE_SOURCE_HEALTH_CACHE = globals().get("_FBP_NATIVE_SOURCE_HEALTH_CACHE", {})
if not isinstance(_FBP_NATIVE_SOURCE_HEALTH_CACHE, dict):
    _FBP_NATIVE_SOURCE_HEALTH_CACHE = {}
_FBP_NATIVE_SOURCE_HEALTH_TTL = 2.0
_FBP_NATIVE_SOURCE_HEALTH_LIMIT = 256


def fbp_clear_native_runtime_cache():
    """Clear name-only native media lookup hints before replacing Blender Main."""
    global _FBP_NATIVE_MEDIA_IMAGE_CACHE_INDEXED, _FBP_NATIVE_MEDIA_IMAGE_COUNT
    _FBP_NATIVE_MEDIA_IMAGE_CACHE.clear()
    _FBP_NATIVE_MEDIA_IMAGE_CACHE_INDEXED = False
    _FBP_NATIVE_MEDIA_IMAGE_COUNT = -1
    _FBP_NATIVE_SOURCE_HEALTH_CACHE.clear()


def _remember_native_media_image(media_key, image):
    global _FBP_NATIVE_MEDIA_IMAGE_COUNT
    try:
        image_name = str(getattr(image, "name", "") or "")
    except FBP_DATA_ERRORS:
        image_name = ""
    if not media_key or not image_name:
        return
    # Keep a complete index. It stores only two short strings per FBP-owned
    # Image, which is negligible beside the Image datablocks themselves and
    # avoids duplicate native media IDs in projects with hundreds of sources.
    _FBP_NATIVE_MEDIA_IMAGE_CACHE[media_key] = image_name
    try:
        _FBP_NATIVE_MEDIA_IMAGE_COUNT = len(bpy.data.images)
    except FBP_DATA_ERRORS:
        pass


def _ensure_native_media_image_index():
    """Index current FBP-owned Image IDs once instead of once per imported file."""
    global _FBP_NATIVE_MEDIA_IMAGE_CACHE_INDEXED, _FBP_NATIVE_MEDIA_IMAGE_COUNT
    try:
        image_count = len(bpy.data.images)
    except FBP_DATA_ERRORS:
        return
    if _FBP_NATIVE_MEDIA_IMAGE_CACHE_INDEXED and image_count == _FBP_NATIVE_MEDIA_IMAGE_COUNT:
        return

    _FBP_NATIVE_MEDIA_IMAGE_CACHE.clear()
    for candidate in bpy.data.images:
        try:
            media_key = str(candidate.get("fbp_native_media_key", "") or "")
            if media_key and _is_current_fbp_media_image(candidate, media_key):
                _remember_native_media_image(media_key, candidate)
        except FBP_DATA_ERRORS:
            continue
    _FBP_NATIVE_MEDIA_IMAGE_COUNT = image_count
    _FBP_NATIVE_MEDIA_IMAGE_CACHE_INDEXED = True


def _native_source_health_key(row_paths, transparent_flags):
    payload = "\0".join(
        "" if bool(is_empty) else os.path.normcase(os.path.abspath(str(path or "")))
        for path, is_empty in zip(row_paths, transparent_flags, strict=True)
    )
    return hashlib.sha1(payload.encode("utf-8", errors="surrogatepass")).hexdigest()


def _native_rows_are_available(row_paths, transparent_flags, *, force=False):
    """Validate source paths with a short bounded cache for live UI edits."""
    if len(row_paths) != len(transparent_flags):
        return False
    key = _native_source_health_key(row_paths, transparent_flags)
    now = time.monotonic()
    cached = _FBP_NATIVE_SOURCE_HEALTH_CACHE.get(key)
    if (
        not force
        and cached
        and (now - float(cached[0])) < _FBP_NATIVE_SOURCE_HEALTH_TTL
    ):
        return bool(cached[1])

    available = all(
        bool(is_empty) or (bool(path) and os.path.isfile(os.path.abspath(str(path))))
        for path, is_empty in zip(row_paths, transparent_flags, strict=True)
    )
    if len(_FBP_NATIVE_SOURCE_HEALTH_CACHE) >= _FBP_NATIVE_SOURCE_HEALTH_LIMIT and key not in _FBP_NATIVE_SOURCE_HEALTH_CACHE:
        oldest = min(
            _FBP_NATIVE_SOURCE_HEALTH_CACHE,
            key=lambda cache_key: float(_FBP_NATIVE_SOURCE_HEALTH_CACHE[cache_key][0]),
        )
        _FBP_NATIVE_SOURCE_HEALTH_CACHE.pop(oldest, None)
    _FBP_NATIVE_SOURCE_HEALTH_CACHE[key] = (now, bool(available))
    return bool(available)


def _warn(message, exc=None):
    return _runtime_warn(message, exc)


def _safe_socket(node, contains, excludes=()):
    try:
        from .materials import safe_get_socket
        return safe_get_socket(node, contains, list(excludes))
    except FBP_DATA_IO_ERRORS:
        pass
    for inp in getattr(node, "inputs", []):
        n = inp.name.lower()
        i = inp.identifier.lower()
        if all(c in n or c in i for c in contains) and not any(e in n or e in i for e in excludes):
            return inp
    return None


def _configure_material_surface(mat, opacity=1.0, has_alpha=True):
    try:
        from .materials import configure_fbp_material_surface
        return configure_fbp_material_surface(mat, opacity, has_alpha)
    except FBP_DATA_IO_ERRORS:
        pass
    opacity = max(0.0, min(1.0, float(opacity)))
    try:
        mat.diffuse_color = (mat.diffuse_color[0], mat.diffuse_color[1], mat.diffuse_color[2], opacity)
    except FBP_DATA_IO_ERRORS:
        pass
    render_method = 'BLENDED' if has_alpha or opacity < 0.999 else 'OPAQUE'
    for attr, value in (
        ('surface_render_method', render_method),
        ('blend_method', 'HASHED' if render_method == 'DITHERED' else ('BLEND' if render_method == 'BLENDED' else 'OPAQUE')),
        ('show_transparent_back', True),
        ('use_screen_refraction', False),
    ):
        if hasattr(mat, attr):
            try:
                setattr(mat, attr, value)
            except FBP_DATA_IO_ERRORS:
                pass


def _abspath(path):
    try:
        return bpy.path.abspath(path)
    except FBP_DATA_IO_ERRORS:
        return os.path.abspath(path)


def _is_video_file(path):
    return os.path.splitext(str(path or ""))[1].lower() in FBP_NATIVE_VIDEO_EXT


def _media_path(directory, name):
    """Return an absolute-ish file path for a sequence item.

    Pending lists normally store filenames relative to their source directory, but
    file-browser/project scans can occasionally leave absolute paths or paths
    with extra whitespace. Keeping this tolerant prevents one bad row from
    crashing generation with an empty native payload.
    """
    raw = str(name or "").strip()
    if not raw:
        return Path(str(directory or ""))
    try:
        if os.path.isabs(raw):
            return Path(_abspath(raw))
    except FBP_DATA_IO_ERRORS:
        pass
    return Path(_abspath(str(directory or ""))) / raw


def _is_video_sequence_payload(directory, files):
    files = list(files or [])
    return len(files) == 1 and _is_video_file(_media_path(directory, files[0]))


def _validate_native_media_payload(directory, files, *, row_count=None):
    """Reject mixed or multi-video payloads before Blender allocates media IDs."""
    files = [str(name or "").strip() for name in (files or []) if str(name or "").strip()]
    if not files:
        raise FileNotFoundError("No valid media files supplied for native layer")
    video_flags = [_is_video_file(_media_path(directory, name)) for name in files]
    if any(video_flags):
        if len(files) != 1 or not all(video_flags):
            raise ValueError("Video planes support one source file. Import videos separately.")
        if row_count is not None and int(row_count) != 1:
            raise ValueError("Video planes contain one source row and cannot use sequence frame-list edits.")
        return True
    extensions = {os.path.splitext(name)[1].lower() for name in files}
    if len(files) > 1 and len(extensions) > 1:
        raise ValueError("One image sequence must use a single file format. Split mixed PNG/JPG files into separate planes.")
    return False


def _valid_files(directory, files_list):
    """Return existing media rows without repeating expensive path resolution.

    The import path may be called several times while preparing one native
    sequence. Resolve the base directory once and use ``is_file`` as the single
    filesystem probe for each candidate instead of ``exists`` + ``is_file``.
    """
    files = []
    base = Path(_abspath(str(directory or "")))
    try:
        # Comparing normalized absolute parent strings avoids filesystem walks
        # through every path component (Path.resolve/lstat) for each frame.
        base_key = os.path.normcase(os.path.abspath(os.fspath(base)))
    except (OSError, TypeError, ValueError):
        base_key = os.path.normcase(str(base))

    for name in files_list or []:
        raw = str(name or "").strip()
        if not raw:
            continue

        try:
            raw_is_absolute = os.path.isabs(raw)
        except (OSError, TypeError, ValueError):
            raw_is_absolute = False

        candidates = [Path(raw) if raw_is_absolute else base / raw]
        # Some Blender file-browser paths may already be relative to the current
        # blend/project rather than the provided sequence directory. Try them as
        # a fallback, but keep the original relative name when possible.
        if not raw_is_absolute:
            fallback = Path(_abspath(raw))
            if fallback != candidates[0]:
                candidates.append(fallback)

        found = None
        for path in candidates:
            try:
                if path.is_file():
                    found = path
                    break
            except (OSError, RuntimeError, ValueError):
                continue
        if found is None:
            continue

        try:
            parent_key = os.path.normcase(
                os.path.abspath(os.fspath(found.parent))
            )
            files.append(found.name if parent_key == base_key else str(found))
        except (OSError, TypeError, ValueError):
            files.append(raw)
    return files


def _native_frame_number_from_name(name):
    """Return the frame number Blender is likely to read from a filename.

    Blender's native Image Sequence lookup is filename-pattern based. Frame by
    Plane groups a wider set of names than Blender accepts, so we use the last
    numeric block as the source frame number for offset/caching decisions.
    """
    stem = os.path.splitext(os.path.basename(str(name or "")))[0]
    matches = list(re.finditer(r"\d+", stem))
    if not matches:
        return None, "", "", 0
    match = matches[-1]
    try:
        index = int(match.group(0))
    except Exception:
        return None, "", "", 0
    return index, stem[:match.start()], stem[match.end():], len(match.group(0))


def _native_sequence_frame_base(files):
    """Return the first numeric frame used by Blender's sequence resolver.

    Blender resolves an Image Sequence from the number embedded in the runtime
    filename.  A sequence beginning at ``0100`` therefore needs an initial
    ``frame_offset`` of ``99``; treating every sequence as if it began at frame 1
    makes Blender request non-existent files such as ``0001`` and displays the
    magenta missing-texture fallback. Canonical FBP proxies always begin at 1.
    """
    files = [str(value or "") for value in (files or ()) if str(value or "")]
    if not files:
        return 1
    index, _prefix, _suffix, _width = _native_frame_number_from_name(files[0])
    return int(index) if index is not None else 1


def _material_frame_number_base(mat, fallback=1):
    """Read the stored filename base without treating frame 0 as missing."""
    try:
        value = mat.get("fbp_native_frame_number_base", fallback) if mat else fallback
        return int(fallback if value is None else value)
    except FBP_DATA_ERRORS:
        return int(fallback)


def _native_frame_number_base_matches(mat, runtime_files, *, is_video=False, is_static=False):
    """Validate the filename frame base only when Blender resolves a sequence.

    A still image can legitimately end in any numeric block (clipboard images use
    timestamps and random numeric suffixes). Blender does not interpret that
    number as a frame while the Image datablock source is ``FILE``. Comparing it
    with the sequence base therefore rejects valid still materials immediately
    after creation. Movie playback also does not use this sequence-offset base.
    """
    if bool(is_video) or bool(is_static):
        return True
    return _material_frame_number_base(mat) == _native_sequence_frame_base(runtime_files)


def _native_sequence_needs_rename(files):
    """True when filenames may confuse Blender's native Image Sequence reader.

    Problematic source names can be represented through a hidden canonical
    proxy, while the original files remain untouched.
    """
    files = [str(f) for f in (files or []) if f]
    if len(files) <= 1:
        return False

    # Blender derives the sequence resolver from the numeric filename pattern.
    # A non-1 starting number is valid and is handled through frame_offset; only
    # gaps or incompatible filename patterns require a canonical proxy.
    first_ext = os.path.splitext(files[0])[1].lower()
    first_idx, first_prefix, first_suffix, first_width = _native_frame_number_from_name(files[0])
    if first_idx is None:
        return True

    expected = first_idx
    for name in files:
        ext = os.path.splitext(name)[1].lower()
        idx, prefix, suffix, width = _native_frame_number_from_name(name)
        if idx is None or ext != first_ext:
            return True
        # Blender derives the sequence pattern from the first filename. Mixed
        # padding such as frame_1.png / frame_02.png can therefore resolve to
        # missing frames even though the numeric values are consecutive.
        if prefix != first_prefix or suffix != first_suffix or width != first_width:
            return True
        if idx != expected:
            return True
        expected += 1
    return False



def _native_proxy_cache_root(source_directory):
    """Return a persistent writable cache root for native sequence proxies."""
    candidates = [Path(str(source_directory or "")) / ".frame_by_plane_cache"]
    try:
        user_root = bpy.utils.user_resource(
            'DATAFILES',
            path='frame_by_plane/sequence_cache',
            create=True,
        )
        if user_root:
            candidates.append(Path(user_root))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
        pass
    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / '.fbp_write_test'
            probe.write_text('ok', encoding='utf-8')
            probe.unlink(missing_ok=True)
            return root
        except Exception:
            continue
    return None


def _ensure_native_sequence_proxy(directory, files):
    """Create a canonical native sequence without modifying source files.

    Blender Image Sequences require one stable filename pattern. Frame by Plane
    accepts broader naming schemes, including names with multiple changing number
    groups. For those cases, use hard-links when possible and copy only as a
    fallback. The logical source order remains unchanged.
    """
    directory = str(directory or "")
    files = _valid_files(directory, files)
    if len(files) <= 1:
        return "", []
    extensions = {os.path.splitext(name)[1].lower() for name in files}
    if len(extensions) != 1:
        return "", []
    root = _native_proxy_cache_root(directory)
    if root is None:
        return "", []

    signature_data = os.path.normcase(os.path.abspath(directory)) + "\0" + "\0".join(files)
    digest = hashlib.sha1(signature_data.encode('utf-8', errors='surrogatepass')).hexdigest()[:16]
    cache_dir = root / digest
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return "", []

    extension = next(iter(extensions))
    width = max(4, len(str(len(files))))
    manifest_path = cache_dir / 'fbp_proxy.json'
    proxy_files = []
    for index, name in enumerate(files, start=1):
        source = _media_path(directory, name)
        proxy_name = f"FBP_{index:0{width}d}{extension}"
        target = cache_dir / proxy_name
        proxy_files.append(proxy_name)
        temp_target = cache_dir / f".{proxy_name}.tmp_{os.getpid()}"
        try:
            source_stat = source.stat()
            current_ok = False
            if target.exists():
                try:
                    target_stat = target.stat()
                    current_ok = (
                        target_stat.st_size == source_stat.st_size
                        and target_stat.st_mtime_ns == source_stat.st_mtime_ns
                    )
                except OSError:
                    current_ok = False
            if current_ok:
                continue
            temp_target.unlink(missing_ok=True)
            try:
                os.link(str(source), str(temp_target))
            except OSError:
                shutil.copy2(str(source), str(temp_target))
            # Replace only after the new link/copy is complete. A failed copy
            # therefore never destroys a previously valid cached frame.
            os.replace(str(temp_target), str(target))
        except Exception as exc:
            try:
                temp_target.unlink(missing_ok=True)
            except OSError:
                pass
            if not manifest_path.is_file():
                shutil.rmtree(cache_dir, ignore_errors=True)
            _warn("Could not create native sequence proxy", exc)
            return "", []

    try:
        manifest = {
            "source_directory": os.path.abspath(directory),
            "source_files": files,
            "proxy_files": proxy_files,
        }
        temp_manifest = cache_dir / f'.fbp_proxy_{os.getpid()}.tmp'
        temp_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        os.replace(str(temp_manifest), str(manifest_path))
    except Exception as exc:
        try:
            temp_manifest.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass
        if not manifest_path.is_file():
            shutil.rmtree(cache_dir, ignore_errors=True)
        _warn("Could not write native sequence proxy manifest", exc)
        return "", []
    return str(cache_dir), proxy_files




def _playback_signature(row_paths, transparent_flags, durations, loop_mode, frame_start, extension_mode='EDGE'):
    payload = {
        "paths": [os.path.normcase(os.path.abspath(_abspath(path))) if path else "" for path in row_paths],
        "transparent": [bool(value) for value in transparent_flags],
        "durations": [max(1, int(value)) for value in durations],
        "loop_mode": str(loop_mode or 'NONE'),
        "frame_start": int(frame_start),
        "extension_mode": str(extension_mode or 'EDGE'),
    }
    return hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8', errors='surrogatepass')
    ).hexdigest()


def _media_frame_duration(image, fallback=1):
    """Return Blender's decoded movie duration with a caller-provided fallback."""
    try:
        duration = int(getattr(image, "frame_duration", 0) or 0) if image else 0
    except FBP_DATA_ERRORS:
        duration = 0
    try:
        fallback = max(0, int(fallback or 0))
    except (TypeError, ValueError):
        fallback = 0
    return duration if duration > 0 else fallback


def _require_media_frame_duration(image):
    """Return a decoded movie duration or fail instead of creating a 1-frame movie.

    Some Blender builds populate ``Image.frame_duration`` only after a reload of
    a datablock whose source was changed from FILE to MOVIE. This runs only while
    creating media, never during playback or rendering.
    """
    duration = _media_frame_duration(image, fallback=0)
    if duration > 0:
        return duration
    try:
        image.reload()
    except FBP_DATA_ERRORS:
        pass
    duration = _media_frame_duration(image, fallback=0)
    if duration <= 0:
        raise RuntimeError("Blender could not decode the movie frame duration")
    return duration


def _native_frame_offset_driver_exists(tex_node):
    """Return whether frame_offset still uses a scripted dependency-graph driver."""
    try:
        image_user = getattr(tex_node, "image_user", None)
        node_tree = getattr(tex_node, "id_data", None)
        if not image_user or not node_tree:
            return False
        data_path = image_user.path_from_id("frame_offset")
        animation_data = getattr(node_tree, "animation_data", None)
        return any(
            str(getattr(curve, "data_path", "") or "") == data_path
            for curve in (getattr(animation_data, "drivers", ()) or ())
        )
    except FBP_DATA_ERRORS:
        return False


def _native_frame_offset_animation_exists(tex_node):
    """Return whether the ImageUser frame offset still has a driver or F-Curve."""
    try:
        image_user = getattr(tex_node, "image_user", None)
        node_tree = getattr(tex_node, "id_data", None)
        if not image_user or not node_tree:
            return False
        data_path = image_user.path_from_id("frame_offset")
        animation_data = getattr(node_tree, "animation_data", None)
        for curve in getattr(animation_data, "drivers", ()) or ():
            if str(getattr(curve, "data_path", "") or "") == data_path:
                return True
        return any(
            str(getattr(curve, "data_path", "") or "") == data_path
            for curve in (fbp_action_fcurves(node_tree) or ())
        )
    except FBP_DATA_ERRORS:
        return False


def _single_action_curve_for_path(id_data, data_path):
    try:
        matches = [
            curve for curve in (fbp_action_fcurves(id_data) or ())
            if str(getattr(curve, "data_path", "") or "") == data_path
        ]
        return matches[0] if len(matches) == 1 else None
    except FBP_DATA_ERRORS:
        return None


def _curve_points_match(curve, expected, interpolation):
    """Validate exact integer-frame keys, values and interpolation."""
    if curve is None:
        return False
    try:
        if getattr(curve, "modifiers", None) and len(curve.modifiers) > 0:
            return False
        actual = {}
        for point in curve.keyframe_points:
            frame = float(point.co.x)
            rounded = int(round(frame))
            if abs(frame - rounded) > 1e-4 or rounded in actual:
                return False
            if str(getattr(point, "interpolation", "") or "") != interpolation:
                return False
            actual[rounded] = float(point.co.y)
        if set(actual) != set(expected):
            return False
        return all(abs(actual[frame] - float(value)) <= 1e-4 for frame, value in expected.items())
    except FBP_DATA_ERRORS:
        return False


def _native_frame_offset_curve_is_intact(
    mat, tex_node, *, row_count, durations, loop_mode, frame_start, scene=None
):
    try:
        image_user = tex_node.image_user
        tree = tex_node.id_data
        data_path = image_user.path_from_id("frame_offset")
        curve = _single_action_curve_for_path(tree, data_path)
        source_indices = _source_indices_from_material(mat, row_count)
        source_directory, source_files = _source_sequence_from_material(mat)
        if (
            curve is None
            or len(source_indices) != row_count
            or not source_directory
            or not source_files
            or any(index < 0 or index >= len(source_files) for index in source_indices)
        ):
            return False
        frame_number_base = _material_frame_number_base(mat)
    except FBP_DATA_ERRORS:
        return False

    hold_in, hold_out, _animation_out = _native_hold_bounds(
        row_count, durations, loop_mode, frame_start, scene=scene
    )
    native_base_offset = frame_number_base - 1

    def mapped_source_index(elapsed):
        row_index = _source_index_at_elapsed(
            elapsed, row_count, durations, loop_mode
        )
        return source_indices[max(0, min(row_count - 1, row_index))]

    def offset_at(timeline_frame):
        return int(
            native_base_offset
            + mapped_source_index(int(timeline_frame) - frame_start)
            - (int(timeline_frame) - int(hold_in))
        )

    key_frames = {hold_in, hold_out}
    elapsed_min = hold_in - frame_start + 1
    elapsed_max = hold_out - frame_start
    for elapsed in _timing_transition_elapsed_values(
        row_count, durations, loop_mode, elapsed_min, elapsed_max
    ):
        if mapped_source_index(elapsed - 1) != mapped_source_index(elapsed):
            timeline_frame = frame_start + elapsed
            key_frames.add(timeline_frame - 1)
            key_frames.add(timeline_frame)
    expected = _simplified_linear_key_values(key_frames, offset_at)
    return _curve_points_match(curve, expected, 'LINEAR')


def _native_visibility_curve_is_intact(
    mat, *, row_count, durations, loop_mode, frame_start, transparent_flags, scene=None
):
    try:
        node = mat.node_tree.nodes.get("FBP_Native_Frame_Visibility")
        if node is None:
            return False
        output = node.outputs[0]
        data_path = output.path_from_id("default_value")
        curve = _single_action_curve_for_path(mat.node_tree, data_path)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        return False

    flags = [bool(value) for value in transparent_flags[:row_count]]
    while len(flags) < row_count:
        flags.append(False)
    hold_in, hold_out, _animation_out = _native_hold_bounds(
        row_count, durations, loop_mode, frame_start, scene=scene
    )

    def visibility_at(timeline_frame):
        elapsed = int(timeline_frame) - frame_start
        row_index = _source_index_at_elapsed(
            elapsed, row_count, durations, loop_mode
        )
        return 0.0 if flags[max(0, min(row_count - 1, row_index))] else 1.0

    key_frames = {hold_in, hold_out, frame_start}
    elapsed_min = hold_in - frame_start + 1
    elapsed_max = hold_out - frame_start
    for elapsed in _timing_transition_elapsed_values(
        row_count, durations, loop_mode, elapsed_min, elapsed_max
    ):
        timeline_frame = frame_start + elapsed
        if visibility_at(timeline_frame - 1) != visibility_at(timeline_frame):
            key_frames.add(timeline_frame)
    expected = {frame: visibility_at(frame) for frame in key_frames}
    return _curve_points_match(curve, expected, 'CONSTANT')


def _socket_has_source(target_socket, source_socket):
    """Return whether one input socket is linked from the exact expected output."""
    if target_socket is None or source_socket is None:
        return False
    try:
        links = list(getattr(target_socket, "links", ()) or ())
        return len(links) == 1 and getattr(links[0], "from_socket", None) == source_socket
    except FBP_DATA_ERRORS:
        return False


def _native_alpha_output(mat, texture_node):
    """Resolve and validate the native alpha chain before surface nodes."""
    try:
        nodes = mat.node_tree.nodes
        texture_alpha = texture_node.outputs.get("Alpha")
        if texture_alpha is None:
            return None
        base_output = texture_alpha
        visibility = nodes.get("FBP_Native_Frame_Visibility")
        mask = nodes.get("FBP_Native_Frame_Alpha")
        if (visibility is None) != (mask is None):
            return None
        if mask is not None:
            if getattr(visibility, "type", "") != "VALUE":
                return None
            if getattr(mask, "type", "") != "MATH" or str(getattr(mask, "operation", "") or "") != "MULTIPLY":
                return None
            if not _socket_has_source(mask.inputs[0], texture_alpha):
                return None
            if not _socket_has_source(mask.inputs[1], visibility.outputs[0]):
                return None
            base_output = mask.outputs.get("Value") or mask.outputs[0]

        opacity = max(0.0, min(1.0, float(mat.get("fbp_opacity", 1.0))))
        opacity_node = nodes.get("FBP_Opacity")
        if opacity < 0.999:
            if opacity_node is None or getattr(opacity_node, "type", "") != "MATH":
                return None
            if str(getattr(opacity_node, "operation", "") or "") != "MULTIPLY":
                return None
            if not _socket_has_source(opacity_node.inputs[0], base_output):
                return None
            if abs(float(opacity_node.inputs[1].default_value) - opacity) > 1e-5:
                return None
            return opacity_node.outputs.get("Value") or opacity_node.outputs[0]
        if opacity_node is not None:
            return None
        return base_output
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        return None


def _native_shader_effect_nodes(mat):
    """Return tagged shader-effect nodes without importing the effect subsystem."""
    try:
        return tuple(
            node
            for node in mat.node_tree.nodes
            if getattr(node, "type", "") == "GROUP"
            and str(node.get("fbp_shader_effect_id", "") or "")
        )
    except FBP_DATA_ERRORS:
        return ()


def _socket_has_effect_or_source(target_socket, source_socket, effect_nodes):
    """Validate one surface input after the optional shader-effect stack."""
    if _socket_has_source(target_socket, source_socket):
        return True
    try:
        links = list(getattr(target_socket, "links", ()) or ())
        if len(links) != 1:
            return False
        return getattr(links[0], "from_node", None) in set(effect_nodes)
    except FBP_DATA_ERRORS:
        return False


def _native_surface_nodes_are_intact(mat, texture_node):
    """Validate the native shader core and tolerate a tagged effect stack.

    A material with no shader effects must keep exact native links. When tagged
    effects are present, only the color/alpha inputs may be fed by the final
    effect node; the base shader, transparency mixer and media alpha core remain
    strict. This prevents valid effect graphs from triggering needless rebuilds
    while preserving a deterministic pass-through contract.
    """
    try:
        nodes = mat.node_tree.nodes
        color_output = texture_node.outputs.get("Color")
        alpha_output = _native_alpha_output(mat, texture_node)
        effect_nodes = _native_shader_effect_nodes(mat)
        if color_output is None or alpha_output is None:
            return False
        use_emission = bool(mat.get("fbp_use_emission", True))
        if use_emission:
            shader = nodes.get("FBP_Native_Emission")
            transparent = nodes.get("FBP_Native_Transparent")
            mix = nodes.get("FBP_Native_Alpha_Mix")
            if not shader or getattr(shader, "type", "") != "EMISSION":
                return False
            if not transparent or getattr(transparent, "type", "") != "BSDF_TRANSPARENT":
                return False
            if not mix or getattr(mix, "type", "") != "MIX_SHADER":
                return False
            color_socket = _safe_socket(shader, ["color"]) or shader.inputs[0]
            if not _socket_has_effect_or_source(color_socket, color_output, effect_nodes):
                return False
            if not _socket_has_effect_or_source(mix.inputs[0], alpha_output, effect_nodes):
                return False
            if not _socket_has_source(mix.inputs[1], transparent.outputs[0]):
                return False
            if not _socket_has_source(mix.inputs[2], shader.outputs[0]):
                return False
        else:
            shader = nodes.get("FBP_Native_Principled")
            if not shader or getattr(shader, "type", "") != "BSDF_PRINCIPLED":
                return False
            color_socket = _safe_socket(shader, ["base", "color"]) or shader.inputs[0]
            alpha_socket = _safe_socket(shader, ["alpha"])
            if not _socket_has_effect_or_source(color_socket, color_output, effect_nodes):
                return False
            if alpha_socket is None or not _socket_has_effect_or_source(
                alpha_socket, alpha_output, effect_nodes
            ):
                return False
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        return False


def _native_playback_nodes_are_intact(
    mat,
    native_nodes,
    transparent_flags,
    *,
    durations=None,
    loop_mode='NONE',
    frame_start=1,
    check_files=True,
    scene=None,
):
    """Validate all native media and ImageUser state before accepting a no-op."""
    try:
        is_video = bool(mat.get("fbp_native_video", False))
        is_static = bool(mat.get("fbp_native_static_image", False)) and not is_video
        if int(mat.get("fbp_native_render_contract", 0) or 0) != FBP_NATIVE_RENDER_CONTRACT_REVISION:
            return False
        runtime_directory, runtime_files = _runtime_sequence_from_material(mat)
    except FBP_DATA_ERRORS:
        return False

    if not runtime_directory or not runtime_files or len(native_nodes) != 1:
        return False
    first_path = os.path.abspath(str(_media_path(runtime_directory, runtime_files[0])))
    if check_files and not os.path.isfile(first_path):
        return False

    expected_source = 'MOVIE' if is_video else ('FILE' if is_static else 'SEQUENCE')
    expected_path = os.path.normcase(first_path)
    expected_media_key = _native_media_key(first_path, expected_source)
    expected_interpolation = str(mat.get("fbp_interpolation", "Closest") or "Closest")
    extension_mode = str(mat.get("fbp_native_extension_mode", "EDGE") or "EDGE")
    expected_extension = 'REPEAT' if extension_mode.upper() == 'REPEAT' else 'EXTEND'
    row_count = max(1, len(transparent_flags))
    normalized_durations = [max(1, int(value)) for value in (durations or [1] * row_count)][:row_count]
    while len(normalized_durations) < row_count:
        normalized_durations.append(normalized_durations[-1] if normalized_durations else 1)
    _hold_in, _hold_out, _animation_out = _native_hold_bounds(
        row_count, normalized_durations, loop_mode, frame_start, scene=scene
    )
    expected_coverage = max(1, int(_hold_out) - int(_hold_in) + 1)

    for node in native_nodes:
        try:
            image = getattr(node, "image", None)
            image_user = getattr(node, "image_user", None)
            if not image or not image_user:
                return False
            actual_path = os.path.normcase(os.path.abspath(_abspath(getattr(image, "filepath", "") or "")))
            if actual_path != expected_path:
                return False
            if str(getattr(image, "source", "") or "") != expected_source:
                return False
            if not _is_current_fbp_media_image(image, expected_media_key):
                return False
            if str(getattr(node, "interpolation", "") or "") != expected_interpolation:
                return False
            if str(getattr(node, "extension", "") or "") != expected_extension:
                return False

            actual_duration = int(getattr(image_user, "frame_duration", 0) or 0)
            actual_start = int(getattr(image_user, "frame_start", 0) or 0)
            actual_offset = int(getattr(image_user, "frame_offset", 0) or 0)
            actual_cyclic = bool(getattr(image_user, "use_cyclic", False))
            if not _native_frame_number_base_matches(
                mat,
                runtime_files,
                is_video=is_video,
                is_static=is_static,
            ):
                return False
            if not bool(getattr(image_user, "use_auto_refresh", False)):
                return False
            if is_video:
                expected_movie_duration = _media_frame_duration(
                    image,
                    fallback=max(1, int(mat.get("fbp_native_media_frame_duration", 1) or 1)),
                )
                if (
                    actual_duration != expected_movie_duration
                    or actual_start != int(frame_start)
                    or actual_offset != 0
                    or actual_cyclic != (str(loop_mode) == 'REPEAT')
                ):
                    return False
                if _native_frame_offset_animation_exists(node):
                    return False
            elif is_static:
                if actual_duration != 1 or actual_start != 1 or actual_offset != 0 or actual_cyclic:
                    return False
                if _native_frame_offset_animation_exists(node):
                    return False
            else:
                if (
                    actual_duration != expected_coverage
                    or actual_start != int(_hold_in)
                    or actual_cyclic
                ):
                    return False
                if _native_frame_offset_driver_exists(node):
                    return False
                if not _native_frame_offset_curve_is_intact(
                    mat, node, row_count=row_count, durations=normalized_durations,
                    loop_mode=loop_mode, frame_start=int(frame_start), scene=scene,
                ):
                    return False
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
            return False

    if not _native_surface_nodes_are_intact(mat, native_nodes[0]):
        return False

    if any(bool(value) for value in transparent_flags):
        try:
            nodes = mat.node_tree.nodes
            visibility = nodes.get("FBP_Native_Frame_Visibility")
            multiply = nodes.get("FBP_Native_Frame_Alpha")
            if visibility is None or multiply is None:
                return False
            if not _native_visibility_curve_is_intact(
                mat, row_count=row_count, durations=normalized_durations,
                loop_mode=loop_mode, frame_start=int(frame_start),
                transparent_flags=transparent_flags, scene=scene,
            ):
                return False
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
            return False
    return True




def _runtime_sequence_from_material(mat):
    if not mat:
        return "", []
    return _decode_sequence_json(mat.get("fbp_native_runtime_sequence_json", ""))


def _runtime_sequence_is_available(mat):
    directory, files = _runtime_sequence_from_material(mat)
    if not directory or not files:
        return False
    return len(_valid_files(directory, files)) == len(files)

def fbp_native_source_sequence_from_rig(rig):
    """Return the immutable disk sequence stored by the current native backend."""
    mat = _native_material_from_rig(rig)
    if not mat:
        return "", []
    directory, files = _decode_sequence_json(mat.get("fbp_native_source_sequence_json", ""))
    if directory and files:
        return directory, files
    return "", []



def fbp_rig_native_sequence_needs_rename(rig):
    """Report unsafe names only when no working internal proxy is available."""
    mat = _native_material_from_rig(rig)
    if mat and bool(mat.get("fbp_native_uses_proxy", False)) and _runtime_sequence_is_available(mat):
        return False
    directory, files = fbp_native_source_sequence_from_rig(rig)
    if len(files) <= 1 or _is_video_sequence_payload(directory, files):
        return False
    return _native_sequence_needs_rename(files)


def _prepare_native_sequence_payload(directory, files):
    """Return a Blender-safe runtime sequence without touching source files.

    Source rows may come from different folders after using Import Frame. Blender
    can read an Image Sequence only from one stable filename pattern, so mixed
    folders and incompatible names are always mirrored into the canonical proxy.
    """
    files = _valid_files(directory, files)
    if not files:
        return str(directory or ""), [], 1, False, False
    if len(files) <= 1 or _is_video_sequence_payload(directory, files):
        return str(directory or ""), files, 1, False, False

    resolved_paths = []
    for name in files:
        try:
            resolved_paths.append(os.path.abspath(str(_media_path(directory, name))))
        except Exception:
            resolved_paths.append(str(_media_path(directory, name)))
    parent_dirs = {
        os.path.normcase(os.path.dirname(path))
        for path in resolved_paths
        if path
    }
    mixed_directories = len(parent_dirs) > 1
    needs_proxy = mixed_directories or _native_sequence_needs_rename(files)
    if needs_proxy:
        proxy_directory, proxy_files = _ensure_native_sequence_proxy(directory, files)
        if proxy_directory and proxy_files:
            return proxy_directory, proxy_files, 1, False, True
        # Never hand Blender an incompatible filename pattern after proxy
        # generation failed. That path produces missing/pink frames and can
        # leave a half-valid material that only breaks during animation render.
        return "", [], 1, True, False

    return (
        str(directory or ""),
        files,
        _native_sequence_frame_base(files),
        False,
        False,
    )



def _sequence_json(directory, files):
    data = {
        "directory": str(directory or ""),
        "files": [str(f) for f in (files or [])],
    }
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return ""


def _decode_sequence_json(raw):
    try:
        data = json.loads(str(raw or ""))
        directory = str(data.get("directory", "") or "")
        files = [str(value) for value in data.get("files", []) if str(value or "")]
        if directory and files:
            return directory, files
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
        pass
    return "", []


def fbp_proxy_cache_roots_from_materials(materials):
    """Return generated proxy-cache roots associated with FBP materials.

    Only Frame by Plane cache folders are returned. Source media folders and
    original image files are never candidates for deletion.
    """
    roots = set()
    for mat in list(materials or []):
        if not mat:
            continue
        try:
            if not bool(mat.get('fbp_native_sequence', False)):
                continue
        except FBP_DATA_ERRORS:
            continue
        for key in (
            'fbp_native_runtime_sequence_json',
            'fbp_native_source_sequence_json',
            'fbp_native_sequence_json',
        ):
            try:
                directory, _files = _decode_sequence_json(mat.get(key, ''))
            except FBP_DATA_ERRORS:
                directory = ''
            if not directory:
                continue
            try:
                directory_path = Path(os.path.abspath(bpy.path.abspath(directory)))
            except Exception:
                directory_path = Path(os.path.abspath(directory))
            # Runtime proxy directories are children of a cache root. Source
            # directories can own a sibling .frame_by_plane_cache folder.
            if (directory_path / 'fbp_proxy.json').is_file():
                roots.add(str(directory_path.parent))
            source_cache = directory_path / '.frame_by_plane_cache'
            if source_cache.is_dir():
                roots.add(str(source_cache))
    try:
        user_root = bpy.utils.user_resource(
            'DATAFILES', path='frame_by_plane/sequence_cache', create=False,
        )
        if user_root and os.path.isdir(user_root):
            roots.add(os.path.abspath(user_root))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
        pass
    return sorted(roots)


def _official_proxy_user_root():
    try:
        value = bpy.utils.user_resource(
            'DATAFILES', path='frame_by_plane/sequence_cache', create=False,
        )
        return os.path.normcase(os.path.abspath(value)) if value else ""
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
        return ""


def _allowed_proxy_root(root):
    """Accept only FBP cache-root shapes, never arbitrary material paths."""
    try:
        if root.is_symlink() or not root.is_dir():
            return False
        normalized = os.path.normcase(os.path.abspath(str(root)))
        return root.name == '.frame_by_plane_cache' or normalized == _official_proxy_user_root()
    except (OSError, RuntimeError, ValueError):
        return False


def _owned_proxy_directory(cache_dir):
    """Validate a generated proxy directory before recursive deletion.

    A .blend can contain user-edited custom properties. Requiring the original
    digest, manifest schema and exact generated file set prevents a forged
    marker from turning cleanup into arbitrary directory deletion.
    """
    try:
        if cache_dir.is_symlink() or not cache_dir.is_dir():
            return False
        if not re.fullmatch(r'[0-9a-f]{16}', cache_dir.name):
            return False
        manifest_path = cache_dir / 'fbp_proxy.json'
        if manifest_path.is_symlink() or not manifest_path.is_file():
            return False
        if manifest_path.stat().st_size > 4 * 1024 * 1024:
            return False
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return False
        source_directory = str(data.get('source_directory', '') or '')
        source_files = data.get('source_files', [])
        proxy_files = data.get('proxy_files', [])
        if not source_directory or not isinstance(source_files, list) or not isinstance(proxy_files, list):
            return False
        if not source_files or len(source_files) != len(proxy_files) or len(source_files) > 100000:
            return False
        clean_sources = []
        clean_proxies = []
        for source_name, proxy_name in zip(source_files, proxy_files):
            source_name = str(source_name or '')
            proxy_name = str(proxy_name or '')
            if not source_name or os.path.basename(source_name) != source_name:
                return False
            if not re.fullmatch(r'FBP_\d{4,}\.[A-Za-z0-9]{1,10}', proxy_name):
                return False
            clean_sources.append(source_name)
            clean_proxies.append(proxy_name)
        signature_data = os.path.normcase(os.path.abspath(source_directory)) + "\0" + "\0".join(clean_sources)
        expected_digest = hashlib.sha1(
            signature_data.encode('utf-8', errors='surrogatepass')
        ).hexdigest()[:16]
        if expected_digest != cache_dir.name:
            return False
        allowed_names = {'fbp_proxy.json', *clean_proxies}
        for entry in cache_dir.iterdir():
            if entry.is_symlink() or entry.name not in allowed_names or not entry.is_file():
                return False
        return all((cache_dir / name).is_file() for name in clean_proxies)
    except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError):
        return False


def fbp_cleanup_unused_proxy_caches(candidate_roots=None):
    """Delete only unused Frame by Plane-generated proxy directories.

    A directory is removed only when it contains an FBP proxy manifest and no
    loaded Blender Image or native FBP material references it. Original media
    files are never deleted.
    """
    roots = {os.path.normcase(os.path.abspath(str(root))) for root in (candidate_roots or []) if root}
    active_dirs = set()

    try:
        materials = list(bpy.data.materials)
    except Exception:
        materials = []
    for mat in materials:
        try:
            if not mat or not bool(mat.get('fbp_native_sequence', False)):
                continue
            roots.update(
                os.path.normcase(os.path.abspath(root))
                for root in fbp_proxy_cache_roots_from_materials([mat])
            )
            for key in ('fbp_native_runtime_sequence_json',):
                directory, _files = _decode_sequence_json(mat.get(key, ''))
                if directory:
                    active_dirs.add(os.path.normcase(os.path.abspath(bpy.path.abspath(directory))))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
            continue

    try:
        images = list(bpy.data.images)
    except Exception:
        images = []
    for image in images:
        try:
            raw = str(getattr(image, 'filepath', '') or '')
            if raw:
                active_dirs.add(os.path.normcase(os.path.dirname(os.path.abspath(bpy.path.abspath(raw)))))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
            continue

    removed = 0
    for root_name in sorted(roots):
        root = Path(root_name)
        try:
            if not _allowed_proxy_root(root):
                continue
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                if not _owned_proxy_directory(child):
                    continue
                normalized = os.path.normcase(os.path.abspath(str(child)))
                if normalized in active_dirs:
                    continue
                shutil.rmtree(child)
                removed += 1
            except (OSError, RuntimeError, ValueError) as exc:
                _warn('Could not remove unused native proxy cache', exc)
        try:
            # Do not leave hidden cache folders behind after their generated
            # children have been removed. Never remove a non-empty directory.
            if _allowed_proxy_root(root) and not any(root.iterdir()):
                root.rmdir()
        except (OSError, RuntimeError, ValueError):
            pass
    return removed


def _decode_json_values(raw, count, default, cast):
    try:
        values = list(json.loads(str(raw or "")))
    except Exception:
        values = []
    result = []
    for value in values[:max(0, int(count or 0))]:
        try:
            result.append(cast(value))
        except Exception:
            result.append(default)
    while len(result) < max(0, int(count or 0)):
        result.append(default)
    return result


def _native_material_from_rig(rig):
    """Return only the current native contract owned by this rig."""
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    if not plane or not getattr(plane, "data", None):
        return None
    try:
        for mat in plane.data.materials:
            if (
                mat
                and bool(mat.get("fbp_native_sequence", False))
                and int(mat.get("fbp_native_render_contract", 0) or 0)
                == FBP_NATIVE_RENDER_CONTRACT_REVISION
            ):
                return mat
    except FBP_DATA_ERRORS:
        pass
    return None


def _source_sequence_from_material(mat):
    """Return the complete immutable disk sequence or fail as one unit."""
    if not mat:
        return "", []
    directory, files = _decode_sequence_json(
        mat.get("fbp_native_source_sequence_json", "")
    )
    if directory and files:
        valid = _valid_files(directory, files)
        if len(valid) == len(files):
            return directory, valid
    return "", []


def _row_paths_from_material(mat):
    try:
        values = list(json.loads(str(mat.get("fbp_native_row_paths_json", "") or "")))
        return [str(value or "") for value in values]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return []


def _source_indices_from_material(mat, count):
    raw = mat.get("fbp_native_source_indices_json", "") if mat else ""
    if not str(raw or "").strip():
        return []
    return _decode_json_values(raw, count, -1, int)


def _transparent_flags_from_material(mat, count):
    raw = mat.get("fbp_native_transparent_flags_json", "") if mat else ""
    if not str(raw or "").strip():
        return []
    return _decode_json_values(raw, count, False, bool)


def _discover_native_source_sequence(directory, row_paths):
    """Find the real filename sequence independently from UI row order.

    Duplicated/reordered rows are logical playback entries. The Image datablock
    must keep reading the original numeric sequence on disk.
    """
    directory = str(directory or "")
    row_names = [os.path.basename(str(path)) for path in row_paths if path]
    if not directory or not row_names:
        return []

    first = row_names[0]
    first_ext = os.path.splitext(first)[1].lower()
    first_index, first_prefix, first_suffix, _width = _native_frame_number_from_name(first)
    candidates = []
    if first_index is not None:
        try:
            for name in os.listdir(directory):
                path = os.path.join(directory, name)
                if not os.path.isfile(path) or os.path.splitext(name)[1].lower() != first_ext:
                    continue
                index, prefix, suffix, _candidate_width = _native_frame_number_from_name(name)
                if index is None or prefix != first_prefix or suffix != first_suffix:
                    continue
                candidates.append((int(index), str(name)))
        except OSError:
            candidates = []
    candidates.sort(key=lambda pair: (pair[0], pair[1].lower()))
    discovered = [name for _index, name in candidates]
    discovered_set = {os.path.normcase(name) for name in discovered}
    if discovered and all(os.path.normcase(name) in discovered_set for name in row_names):
        return discovered

    # If disk discovery fails, preserve a deterministic order from the current rows.
    unique = {}
    for name in row_names:
        unique.setdefault(os.path.normcase(name), name)
    return sorted(
        unique.values(),
        key=lambda name: (
            _native_frame_number_from_name(name)[0]
            if _native_frame_number_from_name(name)[0] is not None else 10**12,
            name.lower(),
        ),
    )


def _native_playback_plan_from_rig(rig):
    """Build immutable source metadata plus the logical UI playback mapping.

    Logical rows may be duplicated, reordered, transparent, or imported from a
    different folder. The source list is therefore a stable set of real absolute
    files, while the UI rows only store indices into that source list.
    """
    rows = list(getattr(rig, "fbp_images", [])) if rig else []
    if not rows:
        return None

    row_paths = []
    transparent_flags = []
    real_paths = []
    for item in rows:
        is_empty = bool(getattr(item, "is_empty", False))
        transparent_flags.append(is_empty)
        if is_empty:
            row_paths.append("")
            continue
        path = _abspath(str(getattr(item, "filepath", "") or ""))
        if not path or not os.path.isfile(path):
            return None
        path = os.path.abspath(path)
        row_paths.append(path)
        real_paths.append(path)

    if not real_paths:
        return None

    def unique_paths(values):
        result = []
        seen = set()
        for value in values:
            try:
                absolute = os.path.abspath(_abspath(str(value or "")))
            except Exception:
                absolute = os.path.abspath(str(value or ""))
            key = os.path.normcase(absolute)
            if absolute and os.path.isfile(absolute) and key not in seen:
                seen.add(key)
                result.append(absolute)
        return result

    row_keys = {os.path.normcase(path) for path in real_paths}
    video_paths = [path for path in real_paths if _is_video_file(path)]
    if video_paths:
        # A native Movie layer owns exactly one logical row and one media file.
        # Numeric video filenames must never trigger image-sequence discovery.
        if len(rows) != 1 or len(real_paths) != 1:
            return None
        source_paths = [real_paths[0]]
    else:
        existing_mat = _native_material_from_rig(rig)
        existing_directory, existing_files = _source_sequence_from_material(existing_mat)
        existing_paths = unique_paths(
            str(_media_path(existing_directory, name))
            for name in existing_files
        ) if existing_directory and existing_files else []
        source_paths = list(existing_paths)

        # On the first build, discover the complete numeric image sequence when
        # all rows belong to one folder. This preserves unused source frames for
        # later edits without ever expanding a movie file into a fake sequence.
        row_directories = {os.path.normcase(os.path.dirname(path)) for path in real_paths}
        if not source_paths and len(row_directories) == 1:
            row_directory = os.path.dirname(real_paths[0])
            discovered = _discover_native_source_sequence(row_directory, real_paths)
            discovered_paths = unique_paths(
                str(_media_path(row_directory, name))
                for name in discovered
            )
            discovered_keys = {os.path.normcase(path) for path in discovered_paths}
            if discovered_paths and row_keys.issubset(discovered_keys):
                source_paths = discovered_paths

    # Imported/relinked PNGs are appended to the immutable source set. They may
    # live in another directory; the runtime proxy will canonicalize them.
    source_keys = {os.path.normcase(path) for path in source_paths}
    for path in real_paths:
        key = os.path.normcase(path)
        if key not in source_keys:
            source_keys.add(key)
            source_paths.append(path)

    if not source_paths:
        source_paths = unique_paths(real_paths)
    source_lookup = {
        os.path.normcase(path): index
        for index, path in enumerate(source_paths)
    }
    if any(os.path.normcase(path) not in source_lookup for path in real_paths):
        return None

    source_parent_dirs = {os.path.normcase(os.path.dirname(path)) for path in source_paths}
    source_directory = os.path.dirname(source_paths[0])
    if len(source_parent_dirs) == 1:
        source_files = [os.path.basename(path) for path in source_paths]
    else:
        # Absolute entries are supported by _media_path/_valid_files and allow a
        # single proxy to combine images imported from multiple folders.
        source_files = list(source_paths)

    source_indices = []
    for path, is_empty in zip(row_paths, transparent_flags, strict=True):
        source_indices.append(
            0 if is_empty else int(source_lookup[os.path.normcase(path)])
        )

    row_directory = os.path.dirname(real_paths[0])
    return {
        "directory": row_directory,
        # Absolute row files keep validation correct even when rows come from
        # different folders or share the same basename.
        "row_files": list(real_paths),
        "row_paths": row_paths,
        "source_directory": source_directory,
        "source_files": source_files,
        "source_indices": source_indices,
        "transparent_flags": transparent_flags,
        "row_count": len(rows),
    }




def _source_indices_for_rows(mat, row_paths, transparent_flags, *, check_files=True):
    """Map UI rows to the immutable source sequence without silent fallbacks.

    Missing or unknown source paths are a hard failure. Reusing a previous index
    can display the wrong frame and makes the material appear healthy even though
    its source contract is broken.
    """
    count = max(len(row_paths), len(transparent_flags))
    source_directory, source_files = _source_sequence_from_material(mat)
    if not source_directory or not source_files:
        return None, 0

    lookup = {
        os.path.normcase(os.path.abspath(str(_media_path(source_directory, name)))): index
        for index, name in enumerate(source_files)
    }
    values = []
    for index in range(count):
        is_empty = bool(transparent_flags[index]) if index < len(transparent_flags) else False
        path = str(row_paths[index] or "") if index < len(row_paths) else ""
        if is_empty:
            values.append(0)
            continue
        if not path:
            return None, len(source_files)
        absolute_path = os.path.abspath(_abspath(path))
        if check_files and not os.path.isfile(absolute_path):
            return None, len(source_files)
        key = os.path.normcase(absolute_path)
        if key not in lookup:
            return None, len(source_files)
        values.append(int(lookup[key]))
    return values, len(source_files)


def _playback_span_frames(file_count, durations=None, loop_mode='NONE'):
    file_count = max(1, int(file_count or 1))
    durations = [max(1, int(d)) for d in (durations or [1] * file_count)][:file_count]
    if len(durations) < file_count:
        durations.extend([durations[-1] if durations else 1] * (file_count - len(durations)))
    order, seq_durations = _timing_order_for_mode(file_count, durations, loop_mode)
    return max(1, sum(max(1, int(d)) for d in seq_durations))




def _scene_for_rig(rig=None, preferred=None):
    """Resolve the Scene that owns a rig without relying on bpy.context.

    Context can point at another Scene during project import, background render,
    undo/load handlers or multi-scene editing. Timing coverage must follow the
    Scene that actually contains the animated plane.
    """
    if preferred is not None:
        try:
            if rig is None or preferred.objects.get(str(getattr(rig, 'name', '') or '')) is rig:
                return preferred
        except FBP_DATA_ERRORS:
            pass
    if rig is not None:
        try:
            scenes = tuple(getattr(rig, "users_scene", ()) or ())
        except FBP_DATA_ERRORS:
            scenes = ()
        if scenes:
            try:
                active = getattr(bpy.context, "scene", None)
                if active is not None and any(scene == active for scene in scenes):
                    return active
            except FBP_DATA_ERRORS:
                pass
            return scenes[0]
    try:
        return getattr(bpy.context, "scene", None)
    except FBP_DATA_ERRORS:
        return None


def _native_hold_bounds(file_count, durations=None, loop_mode='NONE', frame_start=1, margin=FBP_NATIVE_HOLD_MARGIN, scene=None):
    """Return ImageUser coverage and one-cycle animation Out frame."""
    frame_start = int(frame_start)
    animation_out = frame_start + _playback_span_frames(file_count, durations, loop_mode) - 1
    try:
        owner_scene = scene or _scene_for_rig()
        scene_in = int(getattr(owner_scene, 'frame_start', frame_start))
        scene_out = int(getattr(owner_scene, 'frame_end', animation_out))
    except Exception:
        scene_in = frame_start
        scene_out = animation_out
    margin = max(0, int(margin or 0))
    # Keep explicit coverage before and after the scene for every playback mode.
    # ImageUser clamps its base frame outside this range before applying the
    # animated offset, which can request a missing file and display magenta.
    # The 500-frame guard also preserves the established FBP hold contract while
    # the scene range is being edited interactively.
    hold_in = min(scene_in, frame_start) - margin
    hold_out = max(scene_out, animation_out) + margin
    return hold_in, hold_out, animation_out





def _normalized_image_aspect(width, height):
    try:
        width = float(width)
        height = float(height)
    except Exception:
        return 1.0, 1.0
    if width <= 0.0 or height <= 0.0:
        return 1.0, 1.0
    if width >= height:
        return 1.0, max(height / width, 0.0001)
    return max(width / height, 0.0001), 1.0


def _store_native_aspect_on_rig(rig, width, height, preview_path=""):
    ax, ay = _normalized_image_aspect(width, height)
    try:
        width_i = int(width)
        height_i = int(height)
    except Exception:
        width_i = height_i = 0
    try:
        if width_i > 0 and height_i > 0:
            rig["fbp_source_width"] = width_i
            rig["fbp_source_height"] = height_i
            rig["fbp_native_aspect_x"] = float(ax)
            rig["fbp_native_aspect_y"] = float(ay)
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        # Native backend bakes aspect into mesh vertices. Keep the rig scale
        # uniform so the visible image, frame and transform handles agree.
        rig.scale = (1.0, 1.0, 1.0)
        rig.fbp_base_scale_vec = (1.0, 1.0, 1.0)
    except FBP_DATA_IO_ERRORS:
        pass
    if preview_path:
        try:
            rig.fbp_preview_path = preview_path
        except FBP_DATA_IO_ERRORS:
            pass
    return ax, ay


def _sync_rig_frame_from_plane_bounds(rig, margin=0.05):
    """Make the controller frame read the actual child plane mesh bounds."""
    plane = getattr(rig, 'fbp_plane_target', None) if rig else None
    if not plane or not getattr(plane, 'data', None):
        return False
    try:
        verts = list(getattr(plane.data, 'vertices', []))
        if not verts:
            return False
        xs = [v.co.x for v in verts]
        ys = [v.co.y for v in verts]
        from .builder import fbp_update_rig_frame_mesh_to_bounds
        return fbp_update_rig_frame_mesh_to_bounds(rig, min(xs), max(xs), min(ys), max(ys), margin=margin)
    except Exception as exc:
        _warn("Could not sync native rig frame from plane bounds", exc)
        return False


def _refresh_native_geometry(rig):
    try:
        from .builder import set_plane_mesh_extension
        ok = set_plane_mesh_extension(
            rig,
            getattr(rig, 'fbp_extend_left', 0.0), getattr(rig, 'fbp_extend_right', 0.0),
            getattr(rig, 'fbp_extend_bottom', 0.0), getattr(rig, 'fbp_extend_top', 0.0),
            getattr(rig, 'fbp_extend_mode', 'EDGE'),
            getattr(rig, 'fbp_crop_left', 0.0), getattr(rig, 'fbp_crop_right', 0.0),
            getattr(rig, 'fbp_crop_bottom', 0.0), getattr(rig, 'fbp_crop_top', 0.0),
        )
        _sync_rig_frame_from_plane_bounds(rig)
        return ok
    except Exception as exc:
        _warn("Could not refresh native aspect/crop/extend geometry", exc)
        return False

def _sequence_from_material(mat):
    """Return only the explicit current-contract logical sequence payload."""
    if not mat:
        return "", []
    try:
        directory, files = _decode_sequence_json(
            mat.get("fbp_native_sequence_json", "")
        )
        if not directory or not files:
            return "", []
        if len(_valid_files(directory, files)) != len(files):
            return "", []
        return directory, files
    except FBP_DATA_ERRORS:
        return "", []




def fbp_rig_has_unsupported_native_contract(rig):
    """Return True when a rig still owns a material from an older backend contract."""
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    if not plane or not getattr(plane, "data", None):
        return False
    try:
        return any(
            mat
            and bool(mat.get("fbp_native_sequence", False))
            and int(mat.get("fbp_native_render_contract", 0) or 0) != FBP_NATIVE_RENDER_CONTRACT_REVISION
            for mat in plane.data.materials
        )
    except FBP_DATA_ERRORS:
        return True


def fbp_rig_uses_native_sequence(rig):
    if not rig:
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False
    found_native_material = False
    try:
        for mat in plane.data.materials:
            if not mat or not bool(mat.get("fbp_native_sequence", False)):
                continue
            found_native_material = True
            if int(mat.get("fbp_native_render_contract", 0) or 0) == FBP_NATIVE_RENDER_CONTRACT_REVISION:
                return True
        if found_native_material:
            return False
    except FBP_DATA_IO_ERRORS:
        return False
    return False


def fbp_rig_uses_native_movie(rig):
    """Return True only for a current-contract native Movie layer."""
    mat = _native_material_from_rig(rig)
    if not mat:
        return False
    try:
        return (
            int(mat.get("fbp_native_render_contract", 0) or 0)
            == FBP_NATIVE_RENDER_CONTRACT_REVISION
            and bool(mat.get("fbp_native_video", False))
        )
    except FBP_DATA_ERRORS:
        return False


def _normalize_rig_movie_loop_mode(rig, loop_mode):
    """Keep Movie layers on native one-shot/loop modes only."""
    normalized = str(loop_mode or 'NONE').upper()
    if normalized != 'PINGPONG' or not fbp_rig_uses_native_movie(rig):
        return normalized
    try:
        fbp_set_rna_property_silent(rig, "fbp_loop_mode", 'NONE')
    except FBP_DATA_ERRORS:
        pass
    _warn("Native Movie layers do not support Ping-Pong; playback was reset to One Shot")
    return 'NONE'


def fbp_native_sequence_nodes(mat):
    """Return image texture nodes owned by a native FBP sequence material."""
    nodes = []
    if not mat or not getattr(mat, "use_nodes", False) or not getattr(mat, "node_tree", None):
        return nodes
    try:
        for node in mat.node_tree.nodes:
            if getattr(node, "type", None) == 'TEX_IMAGE' and bool(node.get("fbp_native_sequence_node", False)):
                nodes.append(node)
    except FBP_DATA_IO_ERRORS:
        pass
    return nodes


def _native_backend_type_from_material(mat):
    """Return the explicit layer type represented by one native material."""
    if not mat:
        return 'NATIVE_SEQUENCE'
    try:
        if bool(mat.get('fbp_native_video', False)):
            return 'NATIVE_MOVIE'
        if bool(mat.get('fbp_native_static_image', False)):
            return 'NATIVE_IMAGE'
    except FBP_DATA_ERRORS:
        pass
    return 'NATIVE_SEQUENCE'


def _tag_native_backend(rig, plane=None, mat=None):
    """Persist a cheap backend discriminator on both owner objects."""
    if not rig:
        return
    plane = plane or getattr(rig, 'fbp_plane_target', None)
    backend_type = _native_backend_type_from_material(mat or _native_material_from_rig(rig))
    try:
        rig['fbp_native_backend'] = True
        rig['fbp_backend_type'] = backend_type
    except FBP_DATA_ERRORS:
        pass
    if plane:
        try:
            plane['fbp_native_backend'] = True
            plane['fbp_backend_type'] = backend_type
        except FBP_DATA_ERRORS:
            pass


def fbp_sync_native_texture_settings(rig):
    """Apply filtering/edge settings without rebuilding timing or media.

    Crop sliders share an update callback with the texture extension setting.
    A lightweight node update prevents geometry-only edits from touching source
    files, playback F-Curves, media caches or effects.
    """
    if not rig or not fbp_rig_uses_native_sequence(rig):
        return False
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane or not getattr(plane, 'data', None):
        return False

    interpolation = str(getattr(rig, 'fbp_interpolation', 'Closest') or 'Closest')
    extension_mode = str(getattr(rig, 'fbp_extend_mode', 'EDGE') or 'EDGE')
    expected_extension = 'REPEAT' if extension_mode.upper() == 'REPEAT' else 'EXTEND'
    rows = list(getattr(rig, 'fbp_images', ()) or ())
    default_duration = max(1, int(getattr(rig, 'fbp_global_duration', 1) or 1))
    durations = _durations_from_rig(rig, len(rows), default_duration) if rows else []
    transparent_flags = [bool(getattr(item, 'is_empty', False)) for item in rows]
    row_paths = [
        '' if bool(getattr(item, 'is_empty', False))
        else str(_abspath(getattr(item, 'filepath', '') or ''))
        for item in rows
    ]
    loop_mode = _normalize_rig_movie_loop_mode(rig, getattr(rig, 'fbp_loop_mode', 'NONE'))
    frame_start = int(getattr(rig, 'fbp_start_frame', 1) or 1)

    found = False
    try:
        for mat in plane.data.materials:
            if not mat or not bool(mat.get('fbp_native_sequence', False)):
                continue
            if int(mat.get('fbp_native_render_contract', 0) or 0) != FBP_NATIVE_RENDER_CONTRACT_REVISION:
                return False
            # Never mutate a material shared by two independent layer rigs.
            if int(getattr(mat, 'users', 0) or 0) > 1:
                return False
            nodes = fbp_native_sequence_nodes(mat)
            if not nodes:
                return False
            for node in nodes:
                node.interpolation = interpolation
                node.extension = expected_extension
            mat['fbp_interpolation'] = interpolation
            mat['fbp_native_extension_mode'] = extension_mode
            if rows:
                # This lightweight path must never hide a stale timing map. Only
                # advance the signature when the material already represents the
                # same logical rows and durations; otherwise the next timing
                # refresh must still detect and repair the structural change.
                stored_paths = _row_paths_from_material(mat)
                stored_flags = _transparent_flags_from_material(mat, len(rows))
                stored_durations = _decode_json_values(
                    str(mat.get('fbp_native_item_durations_json', '') or ''),
                    len(rows),
                    default_duration,
                    int,
                )
                if (
                    stored_paths == row_paths
                    and stored_flags == transparent_flags
                    and stored_durations == durations
                ):
                    mat['fbp_native_playback_signature'] = _playback_signature(
                        row_paths,
                        transparent_flags,
                        durations,
                        loop_mode,
                        frame_start,
                        extension_mode,
                    )
            _tag_native_backend(rig, plane, mat)
            found = True
    except FBP_DATA_ERRORS as exc:
        _warn('Could not synchronize native texture settings', exc)
        return False
    return found

def fbp_native_rig_contract_issues(rig, *, check_files=True):
    """Return render-blocking problems for one current native layer."""
    issues = []
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    if not plane or not getattr(plane, "data", None):
        return ["missing linked plane or mesh"]

    try:
        native_materials = [
            mat for mat in plane.data.materials
            if mat and bool(mat.get("fbp_native_sequence", False))
        ]
    except FBP_DATA_ERRORS:
        return ["native material slots are unreadable"]

    try:
        revisions = [
            (mat, int(mat.get("fbp_native_render_contract", 0) or 0))
            for mat in native_materials
        ]
    except FBP_DATA_ERRORS:
        return ["native material contract metadata is unreadable"]

    unsupported = [
        mat for mat, revision in revisions
        if revision != FBP_NATIVE_RENDER_CONTRACT_REVISION
    ]
    if unsupported:
        issues.append("contains an unsupported native material contract")
    current = [
        mat for mat, revision in revisions
        if revision == FBP_NATIVE_RENDER_CONTRACT_REVISION
    ]
    if len(current) != 1:
        issues.append(f"expected exactly one current native material, found {len(current)}")
        return issues
    mat = current[0]
    try:
        # Material.users also counts references from Geometry Nodes (for
        # example Felt Fuzz reuses the plane material for generated fibres).
        # Count actual object material-slot owners instead, otherwise valid
        # effects are falsely reported as cross-plane material sharing.
        material_owners = set()
        for obj in bpy.data.objects:
            data = getattr(obj, "data", None)
            slots = getattr(data, "materials", None) if data is not None else None
            if slots is None:
                continue
            if any(slot == mat for slot in slots):
                material_owners.add(obj.as_pointer())
        if len(material_owners) > 1:
            issues.append("native material is shared by multiple planes")
    except FBP_DATA_ERRORS:
        issues.append("native material ownership is unreadable")

    try:
        rows = list(getattr(rig, "fbp_images", ()) or ())
    except FBP_DATA_ERRORS:
        rows = []
    if not rows:
        issues.append("has no logical playback rows")
        return issues

    transparent_flags = [bool(getattr(item, "is_empty", False)) for item in rows]
    row_paths = [
        "" if is_empty else str(_abspath(getattr(item, "filepath", "") or ""))
        for item, is_empty in zip(rows, transparent_flags, strict=True)
    ]
    for path, is_empty in zip(row_paths, transparent_flags, strict=True):
        if not is_empty and (
            not path or (check_files and not os.path.isfile(os.path.abspath(path)))
        ):
            issues.append("references a missing logical media row")
            break

    try:
        duration_default = max(1, int(getattr(rig, "fbp_global_duration", 1) or 1))
        loop_mode = str(getattr(rig, "fbp_loop_mode", "NONE") or "NONE")
        frame_start = int(getattr(rig, "fbp_start_frame", 1) or 1)
        extension_mode = str(getattr(rig, "fbp_extend_mode", "EDGE") or "EDGE")
    except FBP_DATA_ERRORS:
        issues.append("native playback settings are unreadable")
        return issues
    durations = _durations_from_rig(rig, len(rows), duration_default)
    owner_scene = _scene_for_rig(rig)

    if check_files:
        runtime_available = _runtime_sequence_is_available(mat)
    else:
        runtime_directory, runtime_files = _runtime_sequence_from_material(mat)
        runtime_available = bool(runtime_directory and runtime_files)
    if not runtime_available:
        issues.append("native runtime media is missing")
    source_indices, source_count = _source_indices_for_rows(
        mat, row_paths, transparent_flags, check_files=check_files
    )
    if source_indices is None or source_count <= 0:
        issues.append("logical rows no longer map to the immutable source sequence")

    expected_signature = _playback_signature(
        row_paths, transparent_flags, durations, loop_mode, frame_start, extension_mode
    )
    if str(mat.get("fbp_native_playback_signature", "") or "") != expected_signature:
        issues.append("native playback metadata is stale")

    nodes = fbp_native_sequence_nodes(mat)
    if len(nodes) != 1:
        issues.append(f"expected exactly one native texture node, found {len(nodes)}")
    elif not _native_playback_nodes_are_intact(
        mat, nodes, transparent_flags, durations=durations,
        loop_mode=loop_mode, frame_start=frame_start,
        check_files=check_files, scene=owner_scene,
    ):
        issues.append("native Image/ImageUser/F-Curve contract is invalid")
    return issues


def fbp_native_rig_render_ready(rig, *, check_files=True):
    return not fbp_native_rig_contract_issues(rig, check_files=check_files)


def fbp_native_timing_self_test():
    """Run deterministic playback-math checks without creating Blender data.

    These cases protect the native ImageUser F-Curve contract against subtle
    regressions in One Shot, Loop, Ping-Pong, variable durations and the
    established 500-frame hold coverage. The function is intentionally free of
    datablock mutation so it can be called by the Deep Audit and headless tests.
    """
    issues = []
    checks = 0

    def expect(label, actual, expected):
        nonlocal checks
        checks += 1
        if actual != expected:
            issues.append(f"{label}: expected {expected!r}, got {actual!r}")

    durations = [2, 3, 1]
    expect(
        "One Shot source order",
        [_source_index_at_elapsed(value, 3, durations, 'NONE') for value in (-3, -1, 0, 1, 2, 4, 5, 6, 20)],
        [0, 0, 0, 0, 1, 1, 2, 2, 2],
    )
    expect(
        "Loop source order",
        [_source_index_at_elapsed(value, 3, durations, 'REPEAT') for value in range(0, 12)],
        [0, 0, 1, 1, 1, 2, 0, 0, 1, 1, 1, 2],
    )
    expect(
        "Ping-Pong source order",
        [_source_index_at_elapsed(value, 3, durations, 'PINGPONG') for value in range(0, 12)],
        [0, 0, 1, 1, 1, 2, 1, 1, 1, 0, 0, 1],
    )
    expect(
        "Single-frame playback",
        [_source_index_at_elapsed(value, 1, [7], 'PINGPONG') for value in (-50, 0, 50)],
        [0, 0, 0],
    )
    expect(
        "One Shot transitions",
        list(_timing_transition_elapsed_values(3, durations, 'NONE', -20, 20)),
        [2, 5],
    )
    expect(
        "Loop transitions",
        list(_timing_transition_elapsed_values(3, durations, 'REPEAT', 1, 12)),
        [2, 5, 6, 8, 11, 12],
    )
    expect(
        "Ping-Pong transitions",
        list(_timing_transition_elapsed_values(3, durations, 'PINGPONG', 1, 18)),
        [2, 5, 6, 9, 11, 14, 15, 18],
    )
    expect(
        "Linear key simplification",
        _simplified_linear_key_values({0, 1, 2, 4}, lambda frame: 10 - frame),
        {0: 10, 4: 6},
    )

    class _TimingScene:
        frame_start = -20
        frame_end = 120

    expect(
        "Hold coverage",
        _native_hold_bounds(3, durations, 'NONE', 10, margin=500, scene=_TimingScene()),
        (-520, 620, 15),
    )
    return {
        "issues": tuple(issues),
        "checks": checks,
        "passed": checks - len(issues),
    }


def fbp_native_media_cache_report(*, repair=False):
    """Inspect FBP-owned native Image IDs and lightweight runtime indexes.

    Duplicate used Image datablocks for the same media key are structural: they
    defeat source sharing and can multiply cache pressure. Unused duplicates and
    stale Python index entries are warnings and are never deleted automatically.
    Repair mode rebuilds only the name-based runtime index.
    """
    issues = []
    warnings = []
    repaired = 0
    by_key = {}
    unused = []

    try:
        images = tuple(getattr(bpy.data, "images", ()) or ())
    except FBP_DATA_ERRORS:
        images = ()
    for image in images:
        try:
            media_key = str(image.get("fbp_native_media_key", "") or "")
            if not media_key:
                continue
            by_key.setdefault(media_key, []).append(image)
            if int(getattr(image, "users", 0) or 0) == 0:
                unused.append(image)
        except FBP_DATA_ERRORS:
            continue

    duplicate_keys = 0
    duplicate_images = 0
    for media_key, candidates in sorted(by_key.items()):
        if len(candidates) <= 1:
            continue
        duplicate_keys += 1
        duplicate_images += len(candidates) - 1
        used = [image for image in candidates if int(getattr(image, "users", 0) or 0) > 0]
        names = ", ".join(str(getattr(image, "name", "<image>")) for image in candidates)
        if len(used) > 1:
            issues.append(
                f"Native media key is owned by multiple used Image datablocks: {media_key} ({names})"
            )
        else:
            warnings.append(
                f"Duplicate unused native Image wrapper: {media_key} ({names})"
            )

    stale_entries = []
    for media_key, image_name in tuple(_FBP_NATIVE_MEDIA_IMAGE_CACHE.items()):
        try:
            image = bpy.data.images.get(str(image_name or ""))
            if image is None or not _is_current_fbp_media_image(image, media_key):
                stale_entries.append((media_key, image_name))
        except FBP_DATA_ERRORS:
            stale_entries.append((media_key, image_name))
    if stale_entries:
        warnings.append(
            f"Native runtime media index contains {len(stale_entries)} stale entr{'y' if len(stale_entries) == 1 else 'ies'}"
        )

    if unused:
        warnings.append(
            f"Unused FBP native Image datablocks: {len(unused)} (kept for safe manual/orphan cleanup)"
        )

    if repair and stale_entries:
        fbp_clear_native_runtime_cache()
        _ensure_native_media_image_index()
        repaired += 1

    return {
        "issues": tuple(issues),
        "warnings": tuple(warnings),
        "repaired": repaired,
        "stats": {
            "native_cache_keys": len(by_key),
            "native_cache_duplicate_keys": duplicate_keys,
            "native_cache_duplicate_images": duplicate_images,
            "native_cache_unused_images": len(unused),
            "native_cache_stale_entries": len(stale_entries),
            "native_source_health_entries": len(_FBP_NATIVE_SOURCE_HEALTH_CACHE),
        },
    }


def fbp_probe_native_rig_timing(rig, *, scene=None, max_samples=64):
    """Evaluate representative timeline frames against the native F-Curves.

    The probe changes only ``Scene.frame_current`` and restores it before
    returning. It never rewrites rows, materials, images or animation data.
    """
    issues = list(fbp_native_rig_contract_issues(rig, check_files=True))
    result = {"issues": issues, "samples": 0, "kind": "UNKNOWN"}
    if issues:
        return result

    mat = _native_material_from_rig(rig)
    nodes = fbp_native_sequence_nodes(mat) if mat else []
    if not mat or len(nodes) != 1:
        result["issues"].append("native timing probe could not resolve one texture node")
        return result
    node = nodes[0]
    if bool(mat.get("fbp_native_video", False)):
        result["kind"] = "MOVIE"
        return result
    if bool(mat.get("fbp_native_static_image", False)):
        result["kind"] = "STATIC"
        return result
    result["kind"] = "SEQUENCE"

    try:
        rows = list(getattr(rig, "fbp_images", ()) or ())
        row_count = len(rows)
        durations = _durations_from_rig(
            rig, row_count, max(1, int(getattr(rig, "fbp_global_duration", 1) or 1))
        )
        loop_mode = str(getattr(rig, "fbp_loop_mode", "NONE") or "NONE")
        frame_start = int(getattr(rig, "fbp_start_frame", 1) or 1)
        transparent_flags = [bool(getattr(item, "is_empty", False)) for item in rows]
        source_indices = _source_indices_from_material(mat, row_count)
        runtime_directory, runtime_files = _runtime_sequence_from_material(mat)
        if row_count <= 0 or len(source_indices) != row_count or not runtime_directory or not runtime_files:
            result["issues"].append("native timing probe could not resolve logical rows to runtime sources")
            return result
        frame_number_base = _material_frame_number_base(mat)
        owner_scene = scene or _scene_for_rig(rig)
        if owner_scene is None:
            result["issues"].append("native timing probe could not resolve the owner scene")
            return result
        hold_in, hold_out, animation_out = _native_hold_bounds(
            row_count, durations, loop_mode, frame_start, scene=owner_scene
        )
        samples = {
            hold_in, frame_start - 1, frame_start, animation_out,
            animation_out + 1, hold_out,
            int(getattr(owner_scene, "frame_start", frame_start)),
            int(getattr(owner_scene, "frame_end", animation_out)),
        }
        cycle_span = _playback_span_frames(row_count, durations, loop_mode)
        probe_end = min(hold_out, frame_start + max(cycle_span * 2, cycle_span + 2))
        for elapsed in _timing_transition_elapsed_values(
            row_count, durations, loop_mode,
            max(1, hold_in - frame_start + 1),
            probe_end - frame_start,
        ):
            timeline_frame = frame_start + elapsed
            samples.add(timeline_frame - 1)
            samples.add(timeline_frame)
        samples = sorted(frame for frame in samples if hold_in <= frame <= hold_out)
        max_samples = max(1, int(max_samples or 1))
        if len(samples) > max_samples:
            step = max(1, len(samples) // max_samples)
            samples = samples[::step][:max_samples]

        original_frame = int(getattr(owner_scene, "frame_current", frame_start))
        image_user = node.image_user
        visibility = mat.node_tree.nodes.get("FBP_Native_Frame_Visibility")
        try:
            for timeline_frame in samples:
                owner_scene.frame_set(int(timeline_frame))
                elapsed = int(timeline_frame) - frame_start
                row_index = _source_index_at_elapsed(
                    elapsed, row_count, durations, loop_mode
                )
                expected_source = source_indices[max(0, min(row_count - 1, row_index))]
                actual_source = int(
                    (int(timeline_frame) - int(getattr(image_user, "frame_start", hold_in)))
                    + int(getattr(image_user, "frame_offset", 0) or 0)
                    - (int(frame_number_base) - 1)
                )
                if actual_source != expected_source:
                    result["issues"].append(
                        f"frame {timeline_frame}: source index {actual_source}, expected {expected_source}"
                    )
                if visibility is not None and any(transparent_flags):
                    expected_visibility = 0.0 if transparent_flags[row_index] else 1.0
                    actual_visibility = float(visibility.outputs[0].default_value)
                    if abs(actual_visibility - expected_visibility) > 1e-4:
                        result["issues"].append(
                            f"frame {timeline_frame}: visibility {actual_visibility:.3f}, expected {expected_visibility:.3f}"
                        )
                result["samples"] += 1
        finally:
            owner_scene.frame_set(original_frame)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError, IndexError) as exc:
        result["issues"].append(f"native timing probe failed: {exc}")
    return result


def _native_media_key(first_path, desired_source):
    normalized_path = os.path.normcase(os.path.abspath(_abspath(first_path)))
    return f"{str(desired_source or 'FILE').upper()}::{normalized_path}"


def _is_current_fbp_media_image(image, media_key):
    """Validate both the stored media key and Blender's live Image state.

    Custom properties can survive relinking, file moves or manual source edits.
    A matching stale key is not enough: the first runtime frame must still exist
    and the live Image must use the exact path/source contract. This prevents a
    missing Image ID from being reused as a permanently pink texture.
    """
    if image is None:
        return False
    try:
        expected_source, expected_path = str(media_key or "").split("::", 1)
        actual_source = str(getattr(image, "source", "FILE") or "FILE").upper()
        actual_path = os.path.normcase(os.path.abspath(_abspath(getattr(image, "filepath", "") or "")))
        return (
            int(image.get("fbp_native_media_revision", 0) or 0)
            == FBP_NATIVE_MEDIA_CACHE_REVISION
            and str(image.get("fbp_native_media_key", "") or "") == media_key
            and actual_source == expected_source.upper()
            and actual_path == expected_path
            and bool(actual_path)
            and os.path.isfile(actual_path)
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
        return False


def _tag_native_media_image(image, media_key):
    if image is None:
        return
    try:
        image["fbp_owned"] = True
        image["fbp_native_media_revision"] = FBP_NATIVE_MEDIA_CACHE_REVISION
        image["fbp_native_media_key"] = media_key
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        pass


def _cache_loaded_image_dimensions(image):
    """Store dimensions before changing a FILE image into SEQUENCE/MOVIE.

    Blender can report an empty size after the source mode changes. Keeping the
    dimensions on the Image ID avoids loading a second FILE datablock solely for
    aspect-ratio detection.
    """
    if not image:
        return 0, 0
    try:
        width, height = (int(value or 0) for value in image.size[:2])
    except FBP_DATA_ERRORS:
        width, height = 0, 0
    if width > 0 and height > 0:
        try:
            image["fbp_source_width"] = width
            image["fbp_source_height"] = height
        except FBP_DATA_ERRORS:
            pass
    return width, height


def _image_source_dimensions(image):
    if not image:
        return 0, 0
    try:
        width = int(image.get("fbp_source_width", 0) or 0)
        height = int(image.get("fbp_source_height", 0) or 0)
        if width > 0 and height > 0:
            return width, height
    except FBP_DATA_ERRORS:
        pass
    return _cache_loaded_image_dimensions(image)


def _load_media_image(first_path, *, is_video=False, is_sequence=True):
    """Load or reuse one canonical media datablock per path and source type.

    Blender Image datablocks are shallow wrappers around native image/movie
    buffers. Copying a FILE image and then changing the copy to SEQUENCE/MOVIE
    can therefore leave both wrappers tied to lifecycle-sensitive cache data.
    The current backend creates one independently loaded, FBP-owned datablock
    per path/source pair and shares it only across compatible current FBP planes.
    User-created images are never retagged, reloaded or mutated by this path.
    """
    desired_source = 'MOVIE' if is_video else ('SEQUENCE' if is_sequence else 'FILE')
    media_key = _native_media_key(first_path, desired_source)

    # Check the exact cache key before considering a global Image datablock scan.
    # This is the common path during rebuilds, duplication and multiplane import.
    # An unrelated Image added elsewhere in Blender must not turn every valid hit
    # into an O(n) reindex of bpy.data.images.
    cached_name = str(_FBP_NATIVE_MEDIA_IMAGE_CACHE.get(media_key, "") or "")
    cached_image = bpy.data.images.get(cached_name) if cached_name else None
    if _is_current_fbp_media_image(cached_image, media_key):
        return cached_image
    if cached_name:
        _FBP_NATIVE_MEDIA_IMAGE_CACHE.pop(media_key, None)

    # Build/rebuild the complete name index only after an exact-key miss. This
    # still finds compatible FBP-owned Image IDs loaded from an existing .blend.
    _ensure_native_media_image_index()
    cached_name = str(_FBP_NATIVE_MEDIA_IMAGE_CACHE.get(media_key, "") or "")
    cached_image = bpy.data.images.get(cached_name) if cached_name else None
    if _is_current_fbp_media_image(cached_image, media_key):
        return cached_image
    if cached_name:
        _FBP_NATIVE_MEDIA_IMAGE_CACHE.pop(media_key, None)

    # A datablock may have been renamed without changing bpy.data.images length,
    # so the count-based index can legitimately remain "current" while its name
    # hint is stale. Scan only on this cold miss before allocating a duplicate.
    for candidate in getattr(bpy.data, 'images', ()):
        try:
            if _is_current_fbp_media_image(candidate, media_key):
                _remember_native_media_image(media_key, candidate)
                return candidate
        except FBP_DATA_ERRORS:
            continue

    # Always allocate an independent Blender Image ID for the canonical FBP
    # binding. ``check_existing=True`` can return a user-owned FILE wrapper and
    # tagging or reloading that shared ID would couple unrelated materials to
    # Frame By Plane's lifecycle. The tagged lookup above still guarantees at
    # most one current FBP image per normalized path/source pair.
    image = bpy.data.images.load(first_path, check_existing=False)
    _cache_loaded_image_dimensions(image)
    try:
        if desired_source != 'FILE':
            image.source = desired_source
        if str(getattr(image, "source", "FILE") or "FILE").upper() != desired_source:
            raise RuntimeError(f"Blender kept image source as {getattr(image, 'source', 'FILE')}")
    except FBP_DATA_ERRORS as exc:
        # Never tag a partially initialized Image as a valid media binding. The
        # zero-user datablock is left for Blender's explicit orphan purge; doing
        # ID removal here is unsafe while native image caches may still settle.
        raise RuntimeError(
            f"Could not initialize native {desired_source} image from {first_path}"
        ) from exc
    _tag_native_media_image(image, media_key)
    _remember_native_media_image(media_key, image)
    return image



def _configure_image_user(tex_node, *, frame_start=1, frame_duration=1, frame_offset=0, cyclic=False):
    iu = getattr(tex_node, "image_user", None)
    if not iu:
        return False
    expected_start = int(frame_start)
    expected_duration = max(1, int(frame_duration))
    expected_offset = int(frame_offset)
    expected_cyclic = bool(cyclic)
    try:
        iu.frame_start = expected_start
        iu.frame_duration = expected_duration
        iu.frame_offset = expected_offset
        iu.use_auto_refresh = True
        iu.use_cyclic = expected_cyclic
        return (
            int(getattr(iu, "frame_start", 0) or 0) == expected_start
            and int(getattr(iu, "frame_duration", 0) or 0) == expected_duration
            and int(getattr(iu, "frame_offset", 0) or 0) == expected_offset
            and bool(getattr(iu, "use_auto_refresh", False))
            and bool(getattr(iu, "use_cyclic", False)) == expected_cyclic
        )
    except FBP_DATA_ERRORS:
        return False



def _clear_frame_offset_driver(tex_node):
    iu = getattr(tex_node, "image_user", None)
    if not iu:
        return
    try:
        iu.driver_remove("frame_offset")
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        tree = getattr(tex_node, "id_data", None)
        data_path = iu.path_from_id("frame_offset")
        fbp_remove_action_fcurves(tree, data_path)
    except FBP_DATA_IO_ERRORS:
        pass


def _durations_from_rig(rig, file_count=1, fallback=1):
    fallback = max(1, int(fallback or 1))
    file_count = max(1, int(file_count or 1))
    durations = []
    try:
        for item in getattr(rig, 'fbp_images', []):
            if len(durations) >= file_count:
                break
            # Transparent placeholders are logical timeline rows too. Their own
            # Duration must be respected exactly like an image row; falling back
            # to the global value shifts every subsequent frame.
            durations.append(
                max(1, int(getattr(item, 'duration', fallback) or fallback))
            )
    except Exception:
        durations = []
    if len(durations) < file_count:
        durations.extend([fallback] * (file_count - len(durations)))
    return durations[:file_count]


def _timing_order_for_mode(file_count, durations, loop_mode):
    file_count = max(1, int(file_count or 1))
    durations = list(durations or [1] * file_count)[:file_count]
    if len(durations) < file_count:
        durations.extend([1] * (file_count - len(durations)))
    loop_mode = str(loop_mode or 'NONE')
    if loop_mode == 'PINGPONG' and file_count > 1:
        order = list(range(file_count)) + list(range(file_count - 2, 0, -1))
    else:
        order = list(range(file_count))
    seq_durations = [max(1, int(durations[i])) for i in order]
    return order, seq_durations


def _simplified_linear_key_values(key_frames, value_at):
    """Return exact key values with redundant collinear points removed.

    The native offset curve is piecewise linear. Transition candidates are first
    generated conservatively, then this pure pass removes only a middle point
    whose two surrounding slopes are mathematically identical. Holds, hard
    jumps, reordered frames and cycle boundaries therefore remain untouched.
    """
    points = []
    for frame in sorted({int(value) for value in key_frames}):
        points.append((frame, int(value_at(frame))))
    simplified = []
    for point in points:
        simplified.append(point)
        while len(simplified) >= 3:
            frame_a, value_a = simplified[-3]
            frame_b, value_b = simplified[-2]
            frame_c, value_c = simplified[-1]
            left_span = frame_b - frame_a
            right_span = frame_c - frame_b
            if left_span <= 0 or right_span <= 0:
                break
            if (value_b - value_a) * right_span != (value_c - value_b) * left_span:
                break
            simplified.pop(-2)
    return {frame: value for frame, value in simplified}


def _source_index_at_elapsed(elapsed, file_count, durations, loop_mode):
    file_count = max(1, int(file_count or 1))
    if file_count <= 1:
        return 0
    order, seq_durations = _timing_order_for_mode(file_count, durations, loop_mode)
    cycle_total = max(1, sum(seq_durations))
    loop_mode = str(loop_mode or 'NONE')
    if loop_mode in {'REPEAT', 'PINGPONG'}:
        local = int(max(0, elapsed)) % cycle_total
    else:
        local = int(max(0, min(elapsed, cycle_total - 1)))
    acc = 0
    for src, dur in zip(order, seq_durations, strict=True):
        acc += max(1, int(dur))
        if local < acc:
            return max(0, min(file_count - 1, int(src)))
    return max(0, min(file_count - 1, int(order[-1] if order else 0)))


def _timing_transition_elapsed_values(file_count, durations, loop_mode, elapsed_min, elapsed_max):
    """Yield logical row boundaries inside an elapsed-frame range.

    Negative elapsed time is always the first frame hold. Repeating modes start
    cycling at elapsed zero, matching :func:`_source_index_at_elapsed`.
    """
    file_count = max(1, int(file_count or 1))
    if file_count <= 1:
        return
    elapsed_min = int(elapsed_min)
    elapsed_max = int(elapsed_max)
    if elapsed_max < elapsed_min:
        return

    _order, seq_durations = _timing_order_for_mode(file_count, durations, loop_mode)
    cycle_total = max(1, sum(seq_durations))
    boundaries = []
    cumulative = 0
    for duration in seq_durations:
        cumulative += max(1, int(duration))
        boundaries.append(cumulative)

    loop_mode = str(loop_mode or 'NONE')
    first_elapsed = max(1, elapsed_min)
    if loop_mode not in {'REPEAT', 'PINGPONG'}:
        for elapsed in boundaries[:-1]:
            if first_elapsed <= elapsed <= elapsed_max:
                yield elapsed
        return

    # Emit transitions in strict timeline order. Grouping by boundary first
    # produced 3, 14, 25... then 7, 18, 29..., forcing Blender to repeatedly
    # reorder F-Curve keys and making large looping ranges unnecessarily costly.
    cycle_index = max(0, (first_elapsed // cycle_total) - 1)
    cycle_start = cycle_index * cycle_total
    while cycle_start <= elapsed_max:
        for boundary in boundaries:
            elapsed = cycle_start + boundary
            if elapsed < first_elapsed:
                continue
            if elapsed > elapsed_max:
                break
            yield elapsed
        cycle_start += cycle_total


def _install_frame_offset_keyframes(tex_node, *, file_count=1, frame_start=1, durations=None, loop_mode='NONE', frame_number_base=1, source_indices=None, image_user_start=None, hold_start=None, hold_end=None, scene=None):
    """Keyframe logical frame order without creating one key per timeline frame.

    Within a held source frame, ``frame_offset`` must decrease by one on every
    timeline frame. Linear interpolation between the start/end of each hold does
    that exactly, while paired keys around source changes preserve hard jumps.
    The resulting F-Curve is proportional to logical frame changes rather than
    to the full scene range.
    """
    iu = getattr(tex_node, "image_user", None)
    if not iu:
        return False
    _clear_frame_offset_driver(tex_node)
    file_count = max(1, int(file_count or 1))
    frame_start = int(frame_start)
    durations = [max(1, int(d)) for d in (durations or [1] * file_count)][:file_count]
    if len(durations) < file_count:
        durations.extend([durations[-1] if durations else 1] * (file_count - len(durations)))
    loop_mode = str(loop_mode or 'NONE')
    # Blender resolves the number embedded in the runtime filename. Canonical
    # proxies begin at 1, while an untouched source can begin at 0, 100, etc.
    native_base_offset = int(frame_number_base) - 1
    if source_indices is None:
        source_indices = list(range(file_count))
    else:
        source_indices = [max(0, int(value)) for value in list(source_indices)[:file_count]]
        if len(source_indices) < file_count:
            source_indices.extend(range(len(source_indices), file_count))

    def mapped_source_index(elapsed):
        row_index = _source_index_at_elapsed(elapsed, file_count, durations, loop_mode)
        return source_indices[max(0, min(len(source_indices) - 1, row_index))]

    calculated_hold_in, calculated_hold_out, _animation_out = _native_hold_bounds(
        file_count, durations, loop_mode, frame_start, scene=scene
    )
    hold_start = int(calculated_hold_in if hold_start is None else hold_start)
    hold_start = min(hold_start, frame_start)
    # ImageUser must cover the complete hold range. Outside its duration Blender
    # clamps/cycles the base frame before applying frame_offset, which changes the
    # offset equation and can request missing files. Inside this explicit range
    # the resolver is stable and the curve always maps to a real source frame.
    image_user_start = int(hold_start if image_user_start is None else image_user_start)
    hold_end = max(frame_start, int(calculated_hold_out if hold_end is None else hold_end))

    try:
        data_path = iu.path_from_id("frame_offset")
    except FBP_DATA_ERRORS:
        data_path = None

    def offset_at(timeline_frame):
        return int(
            native_base_offset
            + mapped_source_index(int(timeline_frame) - frame_start)
            - (int(timeline_frame) - image_user_start)
        )

    def set_key(timeline_frame, value):
        iu.frame_offset = int(value)
        if data_path:
            tex_node.id_data.keyframe_insert(data_path=data_path, frame=timeline_frame)
        else:
            iu.keyframe_insert(data_path="frame_offset", frame=timeline_frame)

    try:
        key_frames = {hold_start, hold_end}
        elapsed_min = hold_start - frame_start + 1
        elapsed_max = hold_end - frame_start

        # Generate only real row boundaries instead of scanning every scene frame.
        # This keeps long holds and large scene ranges cheap while preserving the
        # exact hard jumps required by reordered/variable-duration sequences.
        for elapsed in _timing_transition_elapsed_values(
            file_count, durations, loop_mode, elapsed_min, elapsed_max
        ):
            before = mapped_source_index(elapsed - 1)
            after = mapped_source_index(elapsed)
            if before != after:
                timeline_frame = frame_start + elapsed
                key_frames.add(timeline_frame - 1)
                key_frames.add(timeline_frame)

        key_values = _simplified_linear_key_values(key_frames, offset_at)
        for timeline_frame, value in key_values.items():
            set_key(timeline_frame, value)

        tree = getattr(tex_node, "id_data", None)
        if data_path:
            for fcurve in fbp_action_fcurves(tree) or ():
                if fcurve.data_path == data_path:
                    for point in fcurve.keyframe_points:
                        point.interpolation = 'LINEAR'

        try:
            owner_scene = scene or _scene_for_rig()
            current = int(getattr(owner_scene, 'frame_current', frame_start))
            evaluated = max(hold_start, min(current, hold_end))
            iu.frame_offset = offset_at(evaluated)
        except FBP_DATA_ERRORS:
            iu.frame_offset = native_base_offset
        return True
    except Exception as exc:
        _warn("Could not keyframe native ImageUser timing", exc)
        try:
            iu.frame_offset = native_base_offset
        except FBP_DATA_ERRORS:
            pass
        return False



def _clear_value_output_animation(value_node):
    if not value_node:
        return
    try:
        output = value_node.outputs[0]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, IndexError):
        return
    try:
        output.driver_remove("default_value")
    except FBP_DATA_ERRORS:
        pass
    try:
        tree = getattr(value_node, "id_data", None)
        data_path = output.path_from_id("default_value")
        fbp_remove_action_fcurves(tree, data_path)
    except FBP_DATA_ERRORS:
        pass


def _install_visibility_mask_keyframes(value_node, *, row_count=1, frame_start=1, durations=None, loop_mode='NONE', transparent_flags=None, scene=None):
    """Animate logical transparent rows across the same 500-frame hold range."""
    if not value_node:
        return False
    row_count = max(1, int(row_count or 1))
    durations = [max(1, int(value)) for value in (durations or [1] * row_count)][:row_count]
    if len(durations) < row_count:
        durations.extend([durations[-1] if durations else 1] * (row_count - len(durations)))
    flags = [bool(value) for value in (transparent_flags or [False] * row_count)][:row_count]
    if len(flags) < row_count:
        flags.extend([False] * (row_count - len(flags)))
    frame_start = int(frame_start)
    loop_mode = str(loop_mode or 'NONE')
    _clear_value_output_animation(value_node)

    output = value_node.outputs[0]
    if not any(flags):
        try:
            output.default_value = 1.0
        except FBP_DATA_ERRORS:
            pass
        return True

    hold_in, hold_out, _animation_out = _native_hold_bounds(
        row_count, durations, loop_mode, frame_start, scene=scene
    )

    try:
        data_path = output.path_from_id("default_value")
    except Exception:
        data_path = None

    def visibility_at(timeline_frame):
        elapsed = int(timeline_frame) - frame_start
        row_index = _source_index_at_elapsed(elapsed, row_count, durations, loop_mode)
        return 0.0 if flags[max(0, min(row_count - 1, row_index))] else 1.0

    try:
        key_frames = {hold_in, hold_out, frame_start}
        elapsed_min = hold_in - frame_start + 1
        elapsed_max = hold_out - frame_start
        for elapsed in _timing_transition_elapsed_values(
            row_count, durations, loop_mode, elapsed_min, elapsed_max
        ):
            timeline_frame = frame_start + elapsed
            if visibility_at(timeline_frame - 1) != visibility_at(timeline_frame):
                key_frames.add(timeline_frame)

        for timeline_frame in sorted(key_frames):
            output.default_value = visibility_at(timeline_frame)
            if data_path:
                value_node.id_data.keyframe_insert(data_path=data_path, frame=timeline_frame)
            else:
                output.keyframe_insert(data_path="default_value", frame=timeline_frame)
        tree = getattr(value_node, "id_data", None)
        if data_path:
            for curve in fbp_action_fcurves(tree) or ():
                if curve.data_path == data_path:
                    for point in curve.keyframe_points:
                        point.interpolation = 'CONSTANT'
        owner_scene = scene or _scene_for_rig()
        output.default_value = visibility_at(getattr(owner_scene, 'frame_current', frame_start))
        return True
    except Exception as exc:
        _warn("Could not bake transparent-frame visibility", exc)
        try:
            output.default_value = 1.0
        except FBP_DATA_ERRORS:
            pass
        return False


def _ensure_visibility_mask_nodes(mat, alpha_source, *, row_count=1, frame_start=1, durations=None, loop_mode='NONE', transparent_flags=None, scene=None):
    if not mat or not getattr(mat, 'use_nodes', False):
        return None
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    value_node = nodes.get('FBP_Native_Frame_Visibility')
    if value_node is None:
        value_node = nodes.new(type='ShaderNodeValue')
        value_node.name = 'FBP_Native_Frame_Visibility'
        value_node.label = 'Frame Visibility'
        value_node.location = (-150, -300)
    multiply = nodes.get('FBP_Native_Frame_Alpha')
    if multiply is None:
        multiply = nodes.new(type='ShaderNodeMath')
        multiply.name = 'FBP_Native_Frame_Alpha'
        multiply.label = 'Transparent Frame Mask'
        multiply.operation = 'MULTIPLY'
        multiply.location = (20, -180)
    try:
        for link in list(multiply.inputs[0].links):
            links.remove(link)
        for link in list(multiply.inputs[1].links):
            links.remove(link)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, IndexError):
        return None
    if not _link_once(links, alpha_source, multiply.inputs[0]):
        return None
    if not _link_once(links, value_node.outputs[0], multiply.inputs[1]):
        return None
    if not _install_visibility_mask_keyframes(
        value_node,
        row_count=row_count,
        frame_start=frame_start,
        durations=durations,
        loop_mode=loop_mode,
        transparent_flags=transparent_flags, scene=scene,
    ):
        return None
    return multiply.outputs[0]



# Uniform and non-uniform sequence timing both use the compact F-Curve
# builder above. Native ImageUser playback must remain driver-free so native
# animation renders stay on Blender's ordinary F-Curve evaluation path.


def _unique_material_name(base_name):
    base = str(base_name or "FBP_NativeSeq").strip() or "FBP_NativeSeq"
    existing = set(bpy.data.materials.keys())
    if base not in existing:
        return base
    index = 1
    while True:
        candidate = f"{base}.{index:03d}"
        if candidate not in existing:
            return candidate
        index += 1


def _link_once(links, from_socket, to_socket):
    if not from_socket or not to_socket:
        return False
    try:
        for link in getattr(to_socket, 'links', []):
            if link.from_socket == from_socket:
                return True
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        links.new(from_socket, to_socket)
        return True
    except Exception:
        return False











def _reapply_fbp_effects(rig):
    """Restore the registered effect stack after native material changes."""
    if not rig:
        return
    try:
        from .geometry_nodes import fbp_reapply_all_effects
        fbp_reapply_all_effects(rig)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ImportError) as exc:
        _warn('Could not reapply Frame by Plane effects', exc)

def _discard_failed_native_material(mat):
    """Remove a newly-created, unused native material after transactional failure."""
    if not mat:
        return
    try:
        if int(getattr(mat, "users", 0) or 0) == 0:
            bpy.data.materials.remove(mat)
    except FBP_DATA_ERRORS:
        pass

def _discard_failed_native_layer(rig=None, plane=None, material=None, extra_meshes=()):
    """Rollback a partially-created native rig without leaving scene debris."""
    meshes = []
    for obj in (plane, rig):
        if not obj:
            continue
        try:
            mesh = getattr(obj, "data", None)
            if mesh is not None:
                meshes.append(mesh)
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except FBP_DATA_ERRORS:
            pass
    meshes.extend(mesh for mesh in (extra_meshes or ()) if mesh is not None)
    seen_meshes = set()
    for mesh in meshes:
        try:
            pointer = int(mesh.as_pointer())
            if pointer in seen_meshes:
                continue
            seen_meshes.add(pointer)
            if int(getattr(mesh, "users", 0) or 0) == 0:
                bpy.data.meshes.remove(mesh)
        except FBP_DATA_ERRORS:
            pass
    _discard_failed_native_material(material)


def create_native_sequence_material(
    mat_name,
    directory,
    files,
    *,
    interp='Closest',
    opacity=1.0,
    use_emission=True,
    frame_start=1,
    frame_duration_per_image=1,
    loop_mode='NONE',
    extension_mode='EDGE',
    source_directory=None,
    source_files=None,
    source_indices=None,
    transparent_flags=None,
    row_paths=None,
    item_durations=None,
    scene=None,
):
    """Create one native Image Sequence plus a logical playback-order map."""
    original_directory = str(directory or "")
    original_files = _valid_files(original_directory, files)
    if not original_files:
        raise FileNotFoundError("No valid image files supplied for native sequence material")

    source_directory = str(source_directory or original_directory)
    source_files = _valid_files(source_directory, source_files or original_files)
    if not source_files:
        raise FileNotFoundError("No valid source sequence supplied for native sequence material")

    original_is_video = _validate_native_media_payload(original_directory, original_files)
    source_is_video = _validate_native_media_payload(source_directory, source_files)
    if original_is_video != source_is_video:
        raise ValueError("Native layer payload cannot mix video and image sources.")

    source_indices = None if source_indices is None else list(source_indices)
    transparent_flags = None if transparent_flags is None else list(transparent_flags)
    item_durations = None if item_durations is None else list(item_durations)
    row_paths = None if row_paths is None else list(row_paths)
    logical_metadata_supplied = any(
        value is not None
        for value in (row_paths, source_indices, transparent_flags, item_durations)
    )
    if logical_metadata_supplied:
        if row_paths is None:
            raise ValueError("Logical native metadata requires explicit row paths")
        row_paths = [str(path or "") for path in list(row_paths)]
        row_count = len(row_paths)
        if row_count <= 0:
            raise ValueError("Native playback requires at least one logical row")
        for label, values in (
            ("source indices", source_indices),
            ("transparent flags", transparent_flags),
            ("item durations", item_durations),
        ):
            if values is not None and len(values) != row_count:
                raise ValueError(
                    f"Native {label} count does not match logical row count"
                )
    else:
        row_paths = [
            str(_media_path(original_directory, name)) for name in original_files
        ]
        row_count = len(row_paths)

    transparent_flags = [
        bool(value) for value in (transparent_flags or [False] * row_count)
    ]
    initial_durations = [
        max(1, int(value))
        for value in (item_durations or [frame_duration_per_image] * row_count)
    ]

    _validate_native_media_payload(source_directory, source_files, row_count=row_count)
    # Logical order, holds, duplicates and transparent rows are represented by
    # ImageUser animation and a lightweight alpha mask. A disk proxy is created
    # only when the source filenames themselves are not Blender-safe (or frames
    # come from multiple folders). A single logical image bypasses proxy creation.
    if not source_is_video and row_count == 1 and row_paths and row_paths[0]:
        single_path = os.path.abspath(_abspath(row_paths[0]))
        runtime_directory = os.path.dirname(single_path)
        runtime_files = [os.path.basename(single_path)]
        native_frame_base = 1
        uses_proxy = False
    else:
        runtime_directory, runtime_files, native_frame_base, _needs_rename, uses_proxy = _prepare_native_sequence_payload(
            source_directory,
            source_files,
        )
        if not runtime_files:
            raise FileNotFoundError("No valid source sequence supplied for native sequence material")

    if source_indices is None:
        source_indices = list(range(row_count))
    else:
        source_indices = [int(value) for value in source_indices]
    if len(source_indices) != row_count or any(
        value < 0 or value >= len(runtime_files) for value in source_indices
    ):
        raise ValueError("Native source indices do not map to runtime media")

    first_path = str(_media_path(runtime_directory, runtime_files[0]))
    first_display_path = next((path for path in row_paths if path), first_path)
    is_video = bool(source_is_video)
    loop_mode = str(loop_mode or 'NONE').upper()
    if is_video and loop_mode == 'PINGPONG':
        # Blender's native Movie ImageUser supports one-shot and cyclic playback,
        # but not reverse ping-pong without a Python/per-frame decoder path.
        # Keep movie layers on the crash-resistant native path and reject the
        # unsupported mode instead of silently rendering as one-shot.
        loop_mode = 'NONE'
    is_static_image = row_count == 1 and not is_video and not bool(transparent_flags[0] if transparent_flags else False)
    source_width, source_height = 0, 0
    opacity = max(0.0, min(1.0, float(opacity)))
    use_emission = bool(use_emission)
    expected_source = 'MOVIE' if is_video else ('FILE' if is_static_image else 'SEQUENCE')
    try:
        loaded_image = _load_media_image(
            first_path,
            is_video=is_video,
            is_sequence=not is_static_image,
        )
    except Exception as exc:
        raise RuntimeError(f"Could not load native media: {first_path}") from exc
    if loaded_image is None:
        raise RuntimeError(f"Blender returned no image datablock for: {first_path}")
    if str(getattr(loaded_image, "source", "FILE") or "FILE") != expected_source:
        raise RuntimeError(
            f"Native media source mismatch for {first_path}: "
            f"expected {expected_source}, got {getattr(loaded_image, 'source', 'FILE')}"
        )

    mat = None
    try:
        mat = bpy.data.materials.new(_unique_material_name(mat_name))
        mat["fbp_owned"] = True
        mat.use_nodes = True
        _configure_material_surface(mat, opacity, has_alpha=True)

        mat["fbp_native_sequence"] = True
        mat["fbp_native_render_contract"] = FBP_NATIVE_RENDER_CONTRACT_REVISION
        mat["fbp_native_video"] = bool(is_video)
        mat["fbp_native_static_image"] = bool(is_static_image)
        mat["fbp_native_sequence_json"] = _sequence_json(original_directory, original_files)
        mat["fbp_native_runtime_sequence_json"] = _sequence_json(runtime_directory, runtime_files)
        mat["fbp_native_source_sequence_json"] = _sequence_json(source_directory, source_files)
        mat["fbp_native_uses_proxy"] = bool(uses_proxy)
        mat["fbp_native_row_paths_json"] = json.dumps(row_paths, ensure_ascii=False)
        mat["fbp_native_source_indices_json"] = json.dumps(source_indices)
        mat["fbp_native_transparent_flags_json"] = json.dumps(transparent_flags)
        mat["fbp_native_frame_number_base"] = int(native_frame_base)
        mat["fbp_native_timing_revision"] = FBP_NATIVE_TIMING_REVISION
        mat["fbp_image_path"] = first_display_path
        mat["fbp_interpolation"] = interp
        mat["fbp_use_emission"] = bool(use_emission)
        mat["fbp_opacity"] = opacity
        mat["fbp_native_frame_count"] = row_count
        mat["fbp_native_duration_per_image"] = max(1, int(frame_duration_per_image))
        mat["fbp_native_item_durations_json"] = json.dumps(initial_durations)
        mat["fbp_native_playback_signature"] = _playback_signature(
            row_paths,
            transparent_flags,
            initial_durations,
            loop_mode,
            int(frame_start),
            str(extension_mode or 'EDGE'),
        )
        mat["fbp_native_frame_start"] = int(frame_start)
        mat["fbp_native_loop_mode"] = loop_mode
        mat["fbp_native_extension_mode"] = str(extension_mode or 'EDGE')
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out = nodes.new(type='ShaderNodeOutputMaterial')
        out.name = 'FBP_Native_Output'
        out.label = 'Frame by Plane Output'
        out.location = (560, 0)

        tex = nodes.new(type='ShaderNodeTexImage')
        tex.name = 'FBP_Native_Media_Texture'
        tex.label = 'Frame by Plane Native Video' if is_video else ('Frame by Plane Static Image' if is_static_image else 'Frame by Plane Native Image Sequence')
        tex.location = (-440, 80)
        tex["fbp_native_sequence_node"] = True
        try:
            tex.interpolation = interp
        except FBP_DATA_IO_ERRORS:
            pass
        try:
            tex.extension = 'REPEAT' if str(extension_mode).upper() == 'REPEAT' else 'EXTEND'
        except FBP_DATA_IO_ERRORS:
            pass
        tex.image = loaded_image
        if getattr(tex, "image", None) is not loaded_image:
            _discard_failed_native_material(mat)
            raise RuntimeError("Could not bind validated media to the native texture node")

        source_width, source_height = _image_source_dimensions(getattr(tex, "image", None))
        if source_width > 0 and source_height > 0:
            mat["fbp_source_width"] = int(source_width)
            mat["fbp_source_height"] = int(source_height)

        color_source = tex.outputs['Color']
        alpha_source = tex.outputs['Alpha']
        if is_video:
            movie_duration = _require_media_frame_duration(getattr(tex, 'image', None))
            mat["fbp_native_media_frame_duration"] = int(movie_duration)
            if not _configure_image_user(
                tex,
                frame_start=int(frame_start),
                frame_duration=movie_duration,
                frame_offset=0,
                cyclic=loop_mode == 'REPEAT',
            ):
                _discard_failed_native_material(mat)
                raise RuntimeError("Could not configure native movie ImageUser")
        elif is_static_image:
            _clear_frame_offset_driver(tex)
            if not _configure_image_user(
                tex,
                frame_start=1,
                frame_duration=1,
                frame_offset=0,
                cyclic=False,
            ):
                _discard_failed_native_material(mat)
                raise RuntimeError("Could not configure native still ImageUser")
        else:
            hold_in, hold_out, _animation_out = _native_hold_bounds(
                row_count, initial_durations, str(loop_mode or 'NONE'), int(frame_start), scene=scene
            )
            if not _configure_image_user(
                tex,
                frame_start=int(hold_in),
                # Keep Blender's base frame inside one explicit coverage range.
                # The F-Curve maps that base to the desired source filename.
                frame_duration=max(1, int(hold_out) - int(hold_in) + 1),
                frame_offset=int(native_frame_base) - 1,
                cyclic=False,
            ):
                _discard_failed_native_material(mat)
                raise RuntimeError("Could not configure native sequence ImageUser")
            # Use an ordinary F-Curve for every sequence timing mode. Earlier
            # versions used a scripted driver for uniform sequences; that driver was
            # evaluated inside every render-frame dependency-graph evaluation. A
            # compact linear F-Curve produces the same holds/loops while remaining
            # entirely in Blender's standard animation path.
            if not _install_frame_offset_keyframes(
                tex,
                file_count=row_count,
                frame_start=int(frame_start),
                durations=initial_durations,
                loop_mode=str(loop_mode or 'NONE'),
                frame_number_base=int(native_frame_base),
                source_indices=source_indices,
                image_user_start=int(hold_in),
                hold_start=hold_in,
                hold_end=hold_out, scene=scene,
            ):
                _discard_failed_native_material(mat)
                raise RuntimeError("Could not bake native sequence timing F-Curve")

        if any(transparent_flags):
            alpha_source = _ensure_visibility_mask_nodes(
                mat,
                alpha_source,
                row_count=row_count,
                frame_start=int(frame_start),
                durations=initial_durations,
                loop_mode=str(loop_mode or 'NONE'),
                transparent_flags=transparent_flags, scene=scene,
            )
            if alpha_source is None:
                _discard_failed_native_material(mat)
                raise RuntimeError("Could not bake transparent-frame visibility")

        if use_emission:
            shader = nodes.new(type='ShaderNodeEmission')
            shader.name = 'FBP_Native_Emission'
            shader.label = 'Frame by Plane Emission'
            shader.location = (120, 90)
            color_socket = _safe_socket(shader, ['color']) or shader.inputs[0]
            links.new(color_source, color_socket)
            strength = _safe_socket(shader, ['strength'])
            if strength:
                try:
                    strength.default_value = 1.0
                except FBP_DATA_IO_ERRORS:
                    pass
        else:
            shader = nodes.new(type='ShaderNodeBsdfPrincipled')
            shader.name = 'FBP_Native_Principled'
            shader.label = 'Frame by Plane Principled'
            shader.location = (120, 90)
            base = _safe_socket(shader, ['base', 'color']) or shader.inputs[0]
            links.new(color_source, base)
            alpha = _safe_socket(shader, ['alpha'])
            if alpha:
                try:
                    links.new(alpha_source, alpha)
                except FBP_DATA_IO_ERRORS:
                    pass
            for names, value in ((['specular'], 0.0), (['specular', 'ior', 'level'], 0.0), (['roughness'], 1.0)):
                sock = _safe_socket(shader, names)
                if sock:
                    try:
                        sock.default_value = value
                    except FBP_DATA_IO_ERRORS:
                        pass

        if opacity < 0.999:
            multiply = nodes.new(type='ShaderNodeMath')
            multiply.name = 'FBP_Opacity'
            multiply.label = 'Opacity'
            multiply['fbp_internal_opacity_node'] = True
            multiply.operation = 'MULTIPLY'
            multiply.location = (-130, -165)
            multiply.inputs[1].default_value = opacity
            links.new(alpha_source, multiply.inputs[0])
            alpha_source = multiply.outputs['Value']

        if not use_emission:
            alpha_socket = _safe_socket(shader, ['alpha'])
            if alpha_socket:
                try:
                    for link in list(getattr(alpha_socket, 'links', [])):
                        links.remove(link)
                    links.new(alpha_source, alpha_socket)
                except Exception as exc:
                    _warn('Could not connect native alpha to Principled shader', exc)

        if use_emission:
            transparent = nodes.new(type='ShaderNodeBsdfTransparent')
            transparent.name = 'FBP_Native_Transparent'
            transparent.label = 'Frame by Plane Transparent'
            transparent.location = (110, -160)
            mix = nodes.new(type='ShaderNodeMixShader')
            mix.name = 'FBP_Native_Alpha_Mix'
            mix.label = 'Frame by Plane Alpha Mix'
            mix.location = (340, 0)
            links.new(alpha_source, mix.inputs[0])
            links.new(transparent.outputs[0], mix.inputs[1])
            links.new(shader.outputs[0], mix.inputs[2])
            links.new(mix.outputs[0], out.inputs[0])
        else:
            links.new(shader.outputs[0], out.inputs[0])

        if not _native_playback_nodes_are_intact(
            mat,
            [tex],
            transparent_flags,
            durations=initial_durations,
            loop_mode=str(loop_mode or 'NONE'),
            frame_start=int(frame_start), scene=scene,
        ):
            _discard_failed_native_material(mat)
            raise RuntimeError("Native material failed its post-build render contract validation")
        return mat
    except Exception:
        _discard_failed_native_material(mat)
        raise

def rebuild_native_sequence_material(mat, *, use_emission=None, opacity=None, interp=None, frame_start=None, frame_duration_per_image=None, loop_mode=None, extension_mode=None, scene=None):
    if not mat:
        return mat
    if int(mat.get("fbp_native_render_contract", 0) or 0) != FBP_NATIVE_RENDER_CONTRACT_REVISION:
        raise RuntimeError("Unsupported native material contract; rebuild the Frame by Plane layer")
    directory, files = _sequence_from_material(mat)
    if not directory or not files:
        raise RuntimeError("Current native material has no valid logical sequence payload")
    if use_emission is None:
        use_emission = bool(mat.get("fbp_use_emission", True))
    if opacity is None:
        opacity = float(mat.get("fbp_opacity", 1.0))
    if interp is None:
        interp = mat.get("fbp_interpolation", "Closest")
    if frame_start is None:
        frame_start = int(mat.get("fbp_native_frame_start", 1))
    if frame_duration_per_image is None:
        frame_duration_per_image = int(mat.get("fbp_native_duration_per_image", 1))
    if loop_mode is None:
        loop_mode = mat.get("fbp_native_loop_mode", 'NONE')
    if extension_mode is None:
        extension_mode = mat.get("fbp_native_extension_mode", 'EDGE')
    row_count = max(1, int(mat.get("fbp_native_frame_count", len(files)) or len(files) or 1))
    source_directory, source_files = _source_sequence_from_material(mat)
    source_indices = _source_indices_from_material(mat, row_count)
    transparent_flags = _transparent_flags_from_material(mat, row_count)
    row_paths = _row_paths_from_material(mat)
    if not source_directory or not source_files:
        raise RuntimeError("Current native material has no valid immutable source sequence")
    if len(source_indices) != row_count or any(
        index < 0 or index >= len(source_files) for index in source_indices
    ):
        raise RuntimeError("Current native material has invalid source-index metadata")
    if len(row_paths) != row_count:
        raise RuntimeError("Current native material has invalid logical row metadata")
    if len(transparent_flags) != row_count:
        raise RuntimeError("Current native material has invalid transparency metadata")
    raw_item_durations = str(mat.get("fbp_native_item_durations_json", "") or "")
    if not raw_item_durations.strip():
        raise RuntimeError("Current native material has no item-duration metadata")
    item_durations = _decode_json_values(
        raw_item_durations,
        row_count,
        max(1, int(frame_duration_per_image)),
        int,
    )
    return create_native_sequence_material(
        mat.name,
        directory,
        files,
        interp=interp,
        opacity=opacity,
        use_emission=use_emission,
        frame_start=frame_start,
        frame_duration_per_image=frame_duration_per_image,
        loop_mode=loop_mode,
        extension_mode=extension_mode,
        source_directory=source_directory,
        source_files=source_files,
        source_indices=source_indices,
        transparent_flags=transparent_flags,
        row_paths=row_paths,
        item_durations=item_durations, scene=scene,
    )


def fbp_refresh_native_sequence_from_rig(rig):
    """Synchronize native playback only after strict source and F-Curve checks."""
    if not rig or not fbp_rig_uses_native_sequence(rig):
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False

    refreshed = False
    effect_graph_changed = False
    owner_scene = _scene_for_rig(rig)
    try:
        frame_start = int(getattr(rig, "fbp_start_frame", 1))
        duration = max(1, int(getattr(rig, "fbp_global_duration", 1)))
        loop_mode = _normalize_rig_movie_loop_mode(
            rig, getattr(rig, "fbp_loop_mode", 'NONE')
        )
        extension_mode = str(getattr(rig, "fbp_extend_mode", 'EDGE'))
        rig_rows = list(getattr(rig, 'fbp_images', []))
        if not rig_rows:
            return False

        count = len(rig_rows)
        durations = _durations_from_rig(rig, count, duration)
        transparent_flags = [bool(getattr(item, 'is_empty', False)) for item in rig_rows]
        row_paths = [
            "" if bool(getattr(item, 'is_empty', False))
            else str(_abspath(getattr(item, 'filepath', '') or ''))
            for item in rig_rows
        ]
        current_signature = _playback_signature(
            row_paths,
            transparent_flags,
            durations,
            loop_mode,
            frame_start,
            extension_mode,
        )

        for mat in list(plane.data.materials):
            if not mat or not bool(mat.get("fbp_native_sequence", False)):
                continue
            if int(mat.get("fbp_native_render_contract", 0) or 0) != FBP_NATIVE_RENDER_CONTRACT_REVISION:
                continue
            # ImageUser animation belongs to the material node tree. A shared
            # native material would couple timing edits across multiple planes;
            # return False so the caller performs a transactional unique rebuild.
            if int(getattr(mat, "users", 0) or 0) > 1:
                return False
            if bool(mat.get("fbp_native_uses_proxy", False)) and not _runtime_sequence_is_available(mat):
                return False

            native_nodes = fbp_native_sequence_nodes(mat)
            if not native_nodes:
                continue

            previous_signature = str(mat.get("fbp_native_playback_signature", "") or "")
            stored_extension = str(mat.get("fbp_native_extension_mode", "") or "")
            stored_row_paths = _row_paths_from_material(mat)
            stored_transparent_flags = _transparent_flags_from_material(mat, count)
            real_row_paths = [path for path, is_empty in zip(row_paths, transparent_flags, strict=True) if not is_empty]
            video_flags = [_is_video_file(path) for path in real_row_paths]
            if any(video_flags) and (count != 1 or len(real_row_paths) != 1 or not all(video_flags)):
                return False
            expected_video = bool(video_flags and all(video_flags))
            expected_static = bool(count == 1 and not expected_video and not transparent_flags[0])
            if bool(mat.get("fbp_native_video", False)) != expected_video:
                return False
            if bool(mat.get("fbp_native_static_image", False)) != expected_static:
                return False
            structure_unchanged = (
                stored_row_paths == row_paths
                and stored_transparent_flags == transparent_flags
            )
            # Source health is forced after row/path changes and otherwise
            # reused briefly while timing sliders generate rapid callbacks.
            if not _native_rows_are_available(
                row_paths,
                transparent_flags,
                force=not structure_unchanged,
            ):
                return False
            expected_extension = 'REPEAT' if extension_mode.upper() == 'REPEAT' else 'EXTEND'
            nodes_match_extension = all(
                str(getattr(node, 'extension', '') or '') == expected_extension
                for node in native_nodes
            )
            if (
                previous_signature == current_signature
                and stored_extension == extension_mode
                and nodes_match_extension
                and _native_playback_nodes_are_intact(
                    mat,
                    native_nodes,
                    transparent_flags,
                    durations=durations,
                    loop_mode=loop_mode,
                    frame_start=frame_start,
                    check_files=not structure_unchanged,
                    scene=owner_scene,
                )
            ):
                mat["fbp_native_timing_revision"] = FBP_NATIVE_TIMING_REVISION
                refreshed = True
                continue

            source_indices, discovered_source_count = _source_indices_for_rows(
                mat,
                row_paths,
                transparent_flags,
                check_files=not structure_unchanged,
            )
            if source_indices is None or discovered_source_count <= 0:
                return False
            _runtime_directory, runtime_files = _runtime_sequence_from_material(mat)
            frame_number_base = _native_sequence_frame_base(runtime_files)
            is_video = bool(mat.get("fbp_native_video", False))
            is_static_image = bool(mat.get("fbp_native_static_image", False)) and not is_video
            uniform_duration = (
                durations[0]
                if durations and all(value == durations[0] for value in durations)
                else None
            )
            identity_order = source_indices == list(range(count))
            first_alpha_source = None

            for node in native_nodes:
                node.extension = expected_extension
                if is_video:
                    _clear_frame_offset_driver(node)
                    if not _configure_image_user(
                        node,
                        frame_start=frame_start,
                        frame_duration=_media_frame_duration(
                            getattr(node, 'image', None),
                            fallback=max(
                                1, int(mat.get("fbp_native_media_frame_duration", 1) or 1)
                            ),
                        ),
                        frame_offset=0,
                        cyclic=loop_mode == 'REPEAT',
                    ):
                        return False
                elif is_static_image:
                    _clear_frame_offset_driver(node)
                    image = getattr(node, 'image', None)
                    if not image:
                        return False
                    image.source = 'FILE'
                    if not _configure_image_user(
                        node,
                        frame_start=1,
                        frame_duration=1,
                        frame_offset=0,
                        cyclic=False,
                    ):
                        return False
                else:
                    hold_in, hold_out, _animation_out = _native_hold_bounds(
                        count, durations, loop_mode, frame_start, scene=owner_scene
                    )
                    # Remove the old F-Curve before assigning ImageUser defaults.
                    # Otherwise Blender returns the evaluated animated offset at
                    # the current frame and the refresh fails for Loop/Ping-Pong.
                    _clear_frame_offset_driver(node)
                    if not _configure_image_user(
                        node,
                        frame_start=int(hold_in),
                        frame_duration=max(1, int(hold_out) - int(hold_in) + 1),
                        frame_offset=int(frame_number_base) - 1,
                        cyclic=False,
                    ):
                        return False
                    if not _install_frame_offset_keyframes(
                        node,
                        file_count=count,
                        frame_start=frame_start,
                        durations=durations,
                        loop_mode=loop_mode,
                        frame_number_base=frame_number_base,
                        source_indices=source_indices,
                        image_user_start=int(hold_in),
                        hold_start=hold_in,
                        hold_end=hold_out, scene=owner_scene,
                    ):
                        return False
                if first_alpha_source is None:
                    first_alpha_source = node.outputs.get('Alpha')

            mask_node = mat.node_tree.nodes.get('FBP_Native_Frame_Visibility')
            if first_alpha_source and (any(transparent_flags) or mask_node is not None):
                if mask_node is None and any(transparent_flags):
                    effect_graph_changed = True
                if _ensure_visibility_mask_nodes(
                    mat,
                    first_alpha_source,
                    row_count=count,
                    frame_start=frame_start,
                    durations=durations,
                    loop_mode=loop_mode,
                    transparent_flags=transparent_flags, scene=owner_scene,
                ) is None:
                    return False

            if not _native_playback_nodes_are_intact(
                mat,
                native_nodes,
                transparent_flags,
                durations=durations,
                loop_mode=loop_mode,
                frame_start=frame_start,
                check_files=not structure_unchanged,
                scene=owner_scene,
            ):
                return False

            mat["fbp_native_render_contract"] = FBP_NATIVE_RENDER_CONTRACT_REVISION
            mat["fbp_native_frame_start"] = frame_start
            mat["fbp_native_duration_per_image"] = (
                int(uniform_duration)
                if uniform_duration is not None and identity_order
                else duration
            )
            mat["fbp_native_loop_mode"] = loop_mode
            mat["fbp_native_extension_mode"] = extension_mode
            mat["fbp_native_frame_count"] = count
            mat["fbp_native_item_durations_json"] = json.dumps(durations)
            mat["fbp_native_transparent_flags_json"] = json.dumps(transparent_flags)
            mat["fbp_native_row_paths_json"] = json.dumps(row_paths, ensure_ascii=False)
            mat["fbp_native_source_indices_json"] = json.dumps(source_indices)
            mat["fbp_native_frame_number_base"] = int(frame_number_base)
            mat["fbp_native_playback_signature"] = current_signature
            mat["fbp_native_timing_revision"] = FBP_NATIVE_TIMING_REVISION
            refreshed = True
    except Exception as exc:
        _warn("Could not refresh native sequence timing", exc)
        return False

    # ImageUser offsets, durations and row order do not change the shader or
    # Geometry Nodes effect graph. Reapply effects only when transparent-frame
    # support had to add new material nodes; this keeps large list edits cheap.
    if effect_graph_changed:
        _reapply_fbp_effects(rig)
    return refreshed



def fbp_native_sequence_order_matches_rig(rig):
    """Return True only when every native material matches the rig playback order.

    This catches the failure mode where the UI list reverses but an older
    material keeps evaluating its previous forward source-index curve. The
    check performs no filesystem scan and validates the actual ImageUser
    F-Curve, not only stored metadata.
    """
    if not rig or not fbp_rig_uses_native_sequence(rig):
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False
    rows = list(getattr(rig, "fbp_images", ()) or ())
    if not rows:
        return False
    row_paths = [
        "" if bool(getattr(item, "is_empty", False))
        else str(_abspath(getattr(item, "filepath", "") or ""))
        for item in rows
    ]
    transparent_flags = [bool(getattr(item, "is_empty", False)) for item in rows]
    durations = _durations_from_rig(
        rig,
        len(rows),
        max(1, int(getattr(rig, "fbp_global_duration", 1) or 1)),
    )
    found_native = False
    for mat in list(getattr(plane.data, "materials", ()) or ()):
        if not mat or not bool(mat.get("fbp_native_sequence", False)):
            continue
        found_native = True
        if _row_paths_from_material(mat) != row_paths:
            return False
        if _transparent_flags_from_material(mat, len(rows)) != transparent_flags:
            return False
        expected, source_count = _source_indices_for_rows(
            mat, row_paths, transparent_flags, check_files=False
        )
        if expected is None or source_count <= 0:
            return False
        stored = _source_indices_from_material(mat, len(rows))
        if stored != expected:
            return False
        native_nodes = fbp_native_sequence_nodes(mat)
        if not _native_playback_nodes_are_intact(
            mat,
            native_nodes,
            transparent_flags,
            durations=durations,
            loop_mode=str(getattr(rig, "fbp_loop_mode", "NONE") or "NONE"),
            frame_start=int(getattr(rig, "fbp_start_frame", 1) or 1),
            check_files=False,
            scene=_scene_for_rig(rig),
        ):
            return False
    return found_native

def fbp_repair_native_sequence_timing_scene(scene=None):
    """Repair obsolete ImageUser timing once per affected native image rig.

    Blender's resolver uses the numeric filename and applies animated offsets
    after clamping/cycling its base frame. Contracts that assumed zero-based
    logical positions or enabled Cyclic with an animated offset can therefore
    request missing files and display magenta. Only native image sequences with
    an obsolete timing contract are rebuilt; stills and movies are skipped.
    """
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return 0

    repaired = 0
    try:
        objects = tuple(getattr(scene, "objects", ()) or ())
    except FBP_DATA_ERRORS:
        return 0

    for rig in objects:
        try:
            if not bool(getattr(rig, "is_fbp_control", False)):
                continue
            plane = getattr(rig, "fbp_plane_target", None)
            if not plane or not getattr(plane, "data", None):
                continue
            native_materials = [
                candidate for candidate in plane.data.materials
                if candidate and bool(candidate.get("fbp_native_sequence", False))
            ]
            if len(native_materials) != 1:
                continue
            mat = native_materials[0]
            render_revision = int(mat.get("fbp_native_render_contract", 0) or 0)
            if render_revision != FBP_NATIVE_RENDER_CONTRACT_REVISION:
                # Contracts from the 5.1.x/early 5.2.x sequence backend are not
                # safe to patch in place: their Image source, numeric base and
                # F-Curve assumptions differ. Recreate the material transactionally
                # from the rig rows while preserving custom material slots/effects.
                if rebuild_native_sequence_from_rig(rig):
                    repaired += 1
                else:
                    _warn(
                        f"Could not migrate obsolete native sequence for {getattr(rig, 'name', 'layer')}"
                    )
                continue
            if bool(mat.get("fbp_native_video", False)):
                continue
            if bool(mat.get("fbp_native_static_image", False)):
                continue
            nodes = fbp_native_sequence_nodes(mat)
            if len(nodes) != 1:
                continue
            node = nodes[0]
            animation_start = int(getattr(rig, "fbp_start_frame", 1) or 1)
            actual_start = int(getattr(node.image_user, "frame_start", 0) or 0)
            stored_timing_revision = int(
                mat.get("fbp_native_timing_revision", 0) or 0
            )
            row_count = max(1, len(getattr(rig, "fbp_images", ()) or ()))
            durations = _durations_from_rig(
                rig, row_count, getattr(rig, "fbp_global_duration", 1)
            )
            loop_mode = str(getattr(rig, "fbp_loop_mode", "NONE") or "NONE")
            expected_start, expected_end, _animation_out = _native_hold_bounds(
                row_count, durations, loop_mode, animation_start, scene=scene
            )
            expected_duration = max(1, int(expected_end) - int(expected_start) + 1)
            runtime_directory, runtime_files = _runtime_sequence_from_material(mat)
            expected_base = _native_sequence_frame_base(runtime_files)
            if (
                stored_timing_revision >= FBP_NATIVE_TIMING_REVISION
                and actual_start == expected_start
                and int(getattr(node.image_user, "frame_duration", 0) or 0) == expected_duration
                and not bool(getattr(node.image_user, "use_cyclic", False))
                and _material_frame_number_base(mat) == expected_base
            ):
                continue
            timing_is_current = (
                actual_start == expected_start
                and int(getattr(node.image_user, "frame_duration", 0) or 0) == expected_duration
                and not bool(getattr(node.image_user, "use_cyclic", False))
                and _material_frame_number_base(mat) == expected_base
                and _native_frame_offset_curve_is_intact(
                    mat, node, row_count=row_count, durations=durations,
                    loop_mode=loop_mode, frame_start=animation_start, scene=scene,
                )
            )
            if timing_is_current:
                mat["fbp_native_timing_revision"] = FBP_NATIVE_TIMING_REVISION
                continue
            if fbp_refresh_native_sequence_from_rig(rig):
                repaired += 1
            else:
                _warn(
                    f"Could not repair native sequence timing for {getattr(rig, 'name', 'layer')}"
                )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError) as exc:
            _warn("Could not inspect native sequence timing", exc)
    return repaired


def _assign_layer_props(rig, scene, *, color_tag='COLOR_01', color_variant_index=0, target_collection=None, follow_collection_color=True):
    rig.is_fbp_control = True
    rig.hide_render = True
    rig.display_type = 'WIRE'
    rig["fbp_native_backend"] = True
    rig.fbp_global_duration = getattr(scene, 'fbp_pre_duration', 1)
    rig.fbp_use_emission = getattr(scene, 'fbp_pre_shadeless', True)
    rig.fbp_loop_mode = getattr(scene, 'fbp_pre_loop_mode', 'NONE')
    rig.fbp_interpolation = getattr(scene, 'fbp_pre_interpolation', 'Closest')
    rig.fbp_track_cam = bool(getattr(scene, 'fbp_pre_track_cam', False))
    # Creation-time color assignment must never trigger the interactive bulk
    # color callback. Set ownership/inheritance first, then store the requested
    # tag silently so previously generated selected rigs keep their own colors.
    rig.fbp_follow_collection_color = bool(follow_collection_color)
    fbp_set_rna_property_silent(rig, 'fbp_color_tag', color_tag)
    fbp_set_rna_property_silent(rig, 'fbp_color_variant_index', int(color_variant_index))
    if target_collection:
        rig.fbp_collection_name = target_collection.name
        if follow_collection_color:
            try:
                set_collection_color_tag(target_collection, color_tag)
            except FBP_DATA_ERRORS as exc:
                _warn('Could not apply collection color tag to native rig collection', exc)
    try:
        apply_collection_color_to_rig(rig, color_tag, color_variant_index, push_collection=False)
    except FBP_DATA_ERRORS as exc:
        _warn('Could not apply native rig viewport color', exc)


def build_native_fbp_rig(context, rig_name, directory, files_list, location, color_tag='COLOR_01', target_collection=None, color_variant_index=0, follow_collection_color=True):
    """Build one native layer transactionally.

    Any failure in media loading, material validation, timing F-Curves or final
    synchronization removes the partially-created objects, meshes and material.
    """
    from .builder import (
        fbp_create_rect_mesh,
        fbp_create_mesh_object,
        fbp_apply_creation_orientation,
    )

    scene = context.scene
    target_collection = target_collection or getattr(context, 'collection', None) or scene.collection
    files = _valid_files(directory, files_list)
    if not files:
        raise FileNotFoundError("No valid images found for native FBP rig")

    rig_mesh = None
    plane_mesh = None
    rig = None
    plane = None
    mat = None
    try:
        rig_mesh = fbp_create_rect_mesh("Mesh_" + rig_name + "_Rig", size=2.1, with_face=False)
        rig = fbp_create_mesh_object(
            rig_name, rig_mesh, context, location=location, target_collection=target_collection
        )
        _assign_layer_props(
            rig, scene, color_tag=color_tag, color_variant_index=color_variant_index,
            target_collection=target_collection, follow_collection_color=follow_collection_color,
        )
        rig.fbp_start_frame = int(scene.frame_current)
        fbp_apply_creation_orientation(rig, scene)

        plane_mesh = fbp_create_rect_mesh("Mesh_Plane_" + rig_name, size=2.0, with_face=True)
        plane = fbp_create_mesh_object(
            "Plane_" + rig_name, plane_mesh, context, location=location,
            target_collection=target_collection,
        )
        plane.is_fbp_plane = True
        plane["fbp_parent_rig_name"] = rig.name
        plane["fbp_native_backend"] = True
        plane.parent = rig
        plane.matrix_parent_inverse.identity()
        plane.location = (0.0, 0.0, 0.0)
        plane.rotation_euler = (0.0, 0.0, 0.0)
        plane.hide_select = True
        rig.fbp_plane_target = plane
        if target_collection:
            plane.fbp_collection_name = target_collection.name

        first_path = str(_media_path(directory, files[0]))
        mat = create_native_sequence_material(
            f"FBP_NativeSeq_{rig_name}",
            directory,
            files,
            interp=rig.fbp_interpolation,
            opacity=getattr(rig, 'fbp_opacity', 1.0),
            use_emission=rig.fbp_use_emission,
            frame_start=getattr(rig, 'fbp_start_frame', scene.frame_current),
            frame_duration_per_image=getattr(rig, 'fbp_global_duration', 1),
            loop_mode=getattr(rig, 'fbp_loop_mode', 'NONE'),
            extension_mode=getattr(rig, 'fbp_extend_mode', 'EDGE'),
            scene=context.scene,
        )
        if not mat:
            raise RuntimeError("Native material creation returned no material")
        plane.data.materials.append(mat)
        _tag_native_backend(rig, plane, mat)
        _normalize_rig_movie_loop_mode(rig, getattr(rig, "fbp_loop_mode", 'NONE'))

        source_width = int(mat.get("fbp_source_width", 0) or 0)
        source_height = int(mat.get("fbp_source_height", 0) or 0)
        if source_width > 0 and source_height > 0:
            _store_native_aspect_on_rig(rig, source_width, source_height, first_path)

        for file_name in files:
            path = str(_media_path(directory, file_name))
            item = rig.fbp_images.add()
            item.name = str(file_name)
            fbp_set_rna_property_silent(
                item,
                'duration',
                max(1, int(getattr(rig, 'fbp_global_duration', 1) or 1)),
            )
            item.is_selected = True
            item.is_empty = False
            item.filepath = path

        # Rows are part of the render contract. Do not return a rig whose timing
        # refresh failed after material creation.
        if not fbp_refresh_native_sequence_from_rig(rig):
            raise RuntimeError("Native timing validation failed after layer creation")
        if not _refresh_native_geometry(rig):
            raise RuntimeError("Native plane geometry could not be initialized")

        # Creation-time mesh rebuilds must not erase orientation/depth.
        rig.location = location
        fbp_apply_creation_orientation(rig, scene)
        plane.location = (0.0, 0.0, 0.0)
        plane.rotation_euler = (0.0, 0.0, 0.0)
        plane.scale = (1.0, 1.0, 1.0)
        plane.parent = rig
        plane.matrix_parent_inverse.identity()

        plane.hide_render = not bool(getattr(rig, 'fbp_is_visible', True))
        for poly in plane.data.polygons:
            poly.material_index = 0
        apply_collection_color_to_rig(
            rig, color_tag, color_variant_index, push_collection=False
        )
        _reapply_fbp_effects(rig)

        # Multiplane/Fast Import builds many layers in one transaction. Queue
        # this rig and let fbp_end_fast_import perform one scene/UI sync instead
        # of rescanning the entire scene after every generated plane.
        fast_import = False
        try:
            from .importer import (
                fbp_fast_import_is_active,
                fbp_queue_fast_import_rig_name,
            )
            fast_import = bool(fbp_fast_import_is_active())
            if fast_import:
                fbp_queue_fast_import_rig_name(rig.name)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            fast_import = False
        if not fast_import:
            sync_layer_collection(context)

        context.view_layer.objects.active = rig
        rig.select_set(True)
        return rig
    except Exception:
        _discard_failed_native_layer(
            rig=rig, plane=plane, material=mat, extra_meshes=(rig_mesh, plane_mesh)
        )
        raise



def _snapshot_id_property(owner, key):
    """Return whether an ID property existed and its previous value."""
    try:
        return key in owner, owner.get(key)
    except FBP_DATA_ERRORS:
        return False, None


def _restore_id_property(owner, key, snapshot, context_label):
    existed, value = snapshot
    try:
        if existed:
            owner[key] = value
        elif key in owner:
            del owner[key]
    except FBP_DATA_ERRORS as exc:
        _warn(f"Could not restore {key} after {context_label}", exc)


def _fbp_snapshot_plane_material_state(plane):
    """Snapshot material slots and assignments for transactional rollback."""
    if not plane or not getattr(plane, "data", None):
        return {"slots": [], "polygon_indices": [], "active_index": 0}
    try:
        slots = list(getattr(plane.data, "materials", ()) or ())
    except FBP_DATA_ERRORS:
        slots = []
    try:
        polygon_indices = [
            int(getattr(polygon, "material_index", 0) or 0)
            for polygon in plane.data.polygons
        ]
    except FBP_DATA_ERRORS:
        polygon_indices = []
    try:
        active_index = int(getattr(plane, "active_material_index", 0) or 0)
    except FBP_DATA_ERRORS:
        active_index = 0
    return {
        "slots": slots,
        "polygon_indices": polygon_indices,
        "active_index": active_index,
    }


def _fbp_restore_plane_material_state(plane, state):
    """Restore non-empty slots and remap their previous polygon assignments."""
    if not plane or not getattr(plane, "data", None):
        return False
    state = dict(state or {})
    slots = list(state.get("slots", ()) or ())
    old_to_new = {}
    try:
        plane.data.materials.clear()
        for old_index, material in enumerate(slots):
            if not material:
                continue
            old_to_new[old_index] = len(plane.data.materials)
            plane.data.materials.append(material)

        polygon_indices = list(state.get("polygon_indices", ()) or ())
        for index, polygon in enumerate(plane.data.polygons):
            old_index = polygon_indices[index] if index < len(polygon_indices) else 0
            polygon.material_index = old_to_new.get(int(old_index), 0)
        plane.active_material_index = old_to_new.get(
            int(state.get("active_index", 0) or 0), 0
        )
        plane.data.update()
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError) as exc:
        _warn("Could not restore previous material assignments", exc)
        return False


def _fbp_preserved_custom_materials(materials):
    """Return non-FBP material slots that must survive native sequence rebuilds."""
    try:
        from .materials import fbp_material_is_owned
    except ImportError:
        return []
    preserved = []
    for material in list(materials or ()):
        try:
            if material and not fbp_material_is_owned(material):
                preserved.append(material)
        except ReferenceError:
            continue
    return preserved


def _fbp_snapshot_custom_material_assignments(plane, materials):
    """Remember polygon/active custom overrides before rebuilding slot zero."""
    try:
        from .materials import fbp_material_is_owned
    except ImportError:
        return [], None
    polygon_materials = []
    try:
        for polygon in plane.data.polygons:
            index = int(getattr(polygon, "material_index", 0) or 0)
            material = materials[index] if 0 <= index < len(materials) else None
            polygon_materials.append(
                material if material and not fbp_material_is_owned(material) else None
            )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        polygon_materials = []

    active_material = None
    try:
        index = int(getattr(plane, "active_material_index", 0) or 0)
        material = materials[index] if 0 <= index < len(materials) else None
        if material and not fbp_material_is_owned(material):
            active_material = material
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        pass
    return polygon_materials, active_material


def _fbp_assign_native_material_with_custom_slots(
    plane,
    material,
    custom_materials,
    *,
    polygon_overrides=None,
    active_override=None,
):
    """Replace the FBP slot while preserving explicit custom assignments."""
    if not plane or not getattr(plane, "data", None) or not material:
        return False
    plane.data.materials.clear()
    plane.data.materials.append(material)
    for custom in list(custom_materials or ()):
        try:
            if custom and custom != material:
                plane.data.materials.append(custom)
        except ReferenceError:
            continue

    def index_for(custom):
        if not custom:
            return 0
        try:
            for index, slot in enumerate(plane.data.materials):
                if slot == custom:
                    return index
        except FBP_DATA_ERRORS:
            pass
        return 0

    try:
        overrides = list(polygon_overrides or ())
        for index, polygon in enumerate(plane.data.polygons):
            custom = overrides[index] if index < len(overrides) else None
            polygon.material_index = index_for(custom)
        plane.active_material_index = index_for(active_override)
        plane.data.update()
    except FBP_DATA_ERRORS:
        pass
    return True


def rebuild_native_sequence_from_rig(rig):
    """Rebuild one native source sequence plus the UI playback-order map.

    Material assignment is transactional: the previous slots and backend flags
    stay available until the replacement has been created and assigned.
    """
    if not rig:
        return False
    # Rebuilds are transactional and derive their immutable source list from the
    # rig rows. Allow them to replace older 5.1/5.2 native contracts: those
    # versions can contain the broken ImageUser mapping that displays magenta.
    # Unsupported foreign/non-FBP materials are still preserved as custom slots.
    try:
        if bool(getattr(rig, 'fbp_is_color_plane', False)):
            return False
    except FBP_DATA_IO_ERRORS:
        pass
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane or not getattr(plane, 'data', None):
        return False

    plan = _native_playback_plan_from_rig(rig)
    if not plan:
        _warn('Native sequence rebuild skipped: rows must reference one valid source sequence')
        return False

    old_material_state = _fbp_snapshot_plane_material_state(plane)
    old_slot_materials = list(old_material_state["slots"])
    old_materials = [mat for mat in old_slot_materials if mat]
    custom_materials = _fbp_preserved_custom_materials(old_slot_materials)
    polygon_overrides, active_override = _fbp_snapshot_custom_material_assignments(
        plane, old_slot_materials
    )
    old_rig_native = _snapshot_id_property(rig, 'fbp_native_backend')
    old_plane_native = _snapshot_id_property(plane, 'fbp_native_backend')
    old_loop_mode = str(getattr(rig, "fbp_loop_mode", 'NONE') or 'NONE')
    mat = None
    try:
        mat = create_native_sequence_material(
            f"FBP_NativeSeq_{rig.name}",
            plan["directory"],
            plan["row_files"],
            interp=getattr(rig, 'fbp_interpolation', 'Closest'),
            opacity=getattr(rig, 'fbp_opacity', 1.0),
            use_emission=getattr(rig, 'fbp_use_emission', True),
            frame_start=getattr(rig, 'fbp_start_frame', 1),
            frame_duration_per_image=getattr(rig, 'fbp_global_duration', 1),
            loop_mode=getattr(rig, 'fbp_loop_mode', 'NONE'),
            extension_mode=getattr(rig, 'fbp_extend_mode', 'EDGE'),
            source_directory=plan["source_directory"],
            source_files=plan["source_files"],
            source_indices=plan["source_indices"],
            transparent_flags=plan["transparent_flags"],
            row_paths=plan["row_paths"],
            item_durations=_durations_from_rig(
                rig,
                plan["row_count"],
                getattr(rig, 'fbp_global_duration', 1),
            ),
            scene=_scene_for_rig(rig),
        )
        if not mat:
            raise RuntimeError('native sequence material creation returned no material')

        _fbp_assign_native_material_with_custom_slots(
            plane,
            mat,
            custom_materials,
            polygon_overrides=polygon_overrides,
            active_override=active_override,
        )
        _normalize_rig_movie_loop_mode(rig, getattr(rig, "fbp_loop_mode", 'NONE'))
        _tag_native_backend(rig, plane, mat)
        _reapply_fbp_effects(rig)
    except Exception as exc:
        _fbp_restore_plane_material_state(plane, old_material_state)
        _restore_id_property(rig, 'fbp_native_backend', old_rig_native, 'native rebuild failure')
        _restore_id_property(plane, 'fbp_native_backend', old_plane_native, 'native rebuild failure')
        fbp_set_rna_property_silent(rig, "fbp_loop_mode", old_loop_mode)
        if mat and not any(mat == old for old in old_materials):
            try:
                from .materials import fbp_remove_unused_materials_and_images
                fbp_remove_unused_materials_and_images([mat])
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ImportError) as cleanup_exc:
                _warn('Could not clean failed native rebuild material', cleanup_exc)
        _warn('Could not rebuild native sequence from rig list', exc)
        return False

    try:
        from .materials import fbp_remove_unused_materials_and_images
        current_materials = [current for current in list(plane.data.materials) if current]
        fbp_remove_unused_materials_and_images([
            old for old in old_materials
            if not any(old == current for current in current_materials)
        ])
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ImportError) as exc:
        _warn('Could not clean replaced native sequence materials', exc)
    return True

def replace_native_sequence(rig, directory, files):
    """Replace a native sequence transactionally while preserving the old rig on failure."""
    if not rig or not getattr(rig, 'fbp_plane_target', None):
        return False
    files = _valid_files(directory, files)
    if not files:
        return False

    plane = rig.fbp_plane_target
    old_rows = [
        {
            "name": str(getattr(item, 'name', 'Image') or 'Image'),
            "duration": max(1, int(getattr(item, 'duration', 1) or 1)),
            "is_selected": bool(getattr(item, 'is_selected', False)),
            "is_empty": bool(getattr(item, 'is_empty', False)),
            "filepath": str(getattr(item, 'filepath', '') or ''),
            "procedural_kind": str(getattr(item, 'procedural_kind', 'AUTO') or 'AUTO'),
        }
        for item in getattr(rig, 'fbp_images', [])
    ]
    old_index = int(getattr(rig, 'fbp_images_index', 0) or 0)
    old_preview = str(getattr(rig, 'fbp_preview_path', '') or '')
    old_material_state = _fbp_snapshot_plane_material_state(plane)
    old_slot_materials = list(old_material_state["slots"])
    old_materials = [mat for mat in old_slot_materials if mat]
    custom_materials = _fbp_preserved_custom_materials(old_slot_materials)
    polygon_overrides, active_override = _fbp_snapshot_custom_material_assignments(
        plane, old_slot_materials
    )

    old_rig_native = _snapshot_id_property(rig, 'fbp_native_backend')
    old_plane_native = _snapshot_id_property(plane, 'fbp_native_backend')
    old_loop_mode = str(getattr(rig, "fbp_loop_mode", 'NONE') or 'NONE')

    def populate_rows(values):
        rig.fbp_images.clear()
        for data in values:
            item = rig.fbp_images.add()
            item.name = data.get('name', 'Image')
            fbp_set_rna_property_silent(
                item,
                'duration',
                max(1, int(data.get('duration', 1) or 1)),
            )
            item.is_selected = bool(data.get('is_selected', False))
            item.is_empty = bool(data.get('is_empty', False))
            item.filepath = str(data.get('filepath', '') or '')
            try:
                item.procedural_kind = data.get('procedural_kind', 'AUTO')
            except FBP_DATA_IO_ERRORS:
                pass

    new_material = None
    try:
        # Build and validate the replacement material before touching the rig.
        new_material = create_native_sequence_material(
            f"FBP_NativeSeq_{rig.name}",
            directory,
            files,
            interp=getattr(rig, 'fbp_interpolation', 'Closest'),
            opacity=getattr(rig, 'fbp_opacity', 1.0),
            use_emission=getattr(rig, 'fbp_use_emission', True),
            frame_start=getattr(rig, 'fbp_start_frame', 1),
            frame_duration_per_image=getattr(rig, 'fbp_global_duration', 1),
            loop_mode=getattr(rig, 'fbp_loop_mode', 'NONE'),
            extension_mode=getattr(rig, 'fbp_extend_mode', 'EDGE'),
            scene=_scene_for_rig(rig),
        )
        if not new_material:
            raise RuntimeError('native sequence material creation returned no material')

        replacement_rows = []
        for filename in files:
            replacement_rows.append({
                'name': str(filename),
                'duration': max(1, int(getattr(rig, 'fbp_global_duration', 1) or 1)),
                'is_selected': True,
                'is_empty': False,
                'filepath': str(Path(directory) / filename),
                'procedural_kind': 'AUTO',
            })
        populate_rows(replacement_rows)
        rig.fbp_images_index = 0

        _fbp_assign_native_material_with_custom_slots(
            plane,
            new_material,
            custom_materials,
            polygon_overrides=polygon_overrides,
            active_override=active_override,
        )
        _normalize_rig_movie_loop_mode(rig, getattr(rig, "fbp_loop_mode", 'NONE'))
        _tag_native_backend(rig, plane, new_material)
        _reapply_fbp_effects(rig)

        if not fbp_refresh_native_sequence_from_rig(rig):
            raise RuntimeError('native sequence timing refresh failed')
    except Exception as exc:
        failed_materials = []
        try:
            failed_materials.extend(
                material for material in list(plane.data.materials)
                if material and not any(material == old for old in old_materials)
            )
        except FBP_DATA_ERRORS:
            pass
        if new_material:
            try:
                if not any(new_material == material for material in failed_materials):
                    failed_materials.append(new_material)
            except ReferenceError:
                pass

        populate_rows(old_rows)
        rig.fbp_images_index = max(0, min(old_index, max(0, len(rig.fbp_images) - 1)))
        try:
            rig.fbp_preview_path = old_preview
        except FBP_DATA_IO_ERRORS:
            pass
        _fbp_restore_plane_material_state(plane, old_material_state)
        _restore_id_property(rig, 'fbp_native_backend', old_rig_native, 'sequence replacement failure')
        _restore_id_property(plane, 'fbp_native_backend', old_plane_native, 'sequence replacement failure')
        fbp_set_rna_property_silent(rig, "fbp_loop_mode", old_loop_mode)
        if failed_materials:
            try:
                from .materials import fbp_remove_unused_materials_and_images
                fbp_remove_unused_materials_and_images(failed_materials)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ImportError) as cleanup_exc:
                _warn('Could not clean failed replacement materials', cleanup_exc)
        _warn('Could not replace native sequence; previous sequence restored', exc)
        return False

    first_path = str(_media_path(directory, files[0]))
    try:
        rig.fbp_preview_path = first_path
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        width = int(new_material.get("fbp_source_width", 0) or 0) if new_material else 0
        height = int(new_material.get("fbp_source_height", 0) or 0) if new_material else 0
        if width > 0 and height > 0:
            _store_native_aspect_on_rig(rig, width, height, first_path)
            _refresh_native_geometry(rig)
    except FBP_DATA_IO_ERRORS as exc:
        _warn('Could not refresh replacement sequence geometry', exc)

    try:
        from .materials import fbp_remove_unused_materials_and_images
        committed_materials = [material for material in list(plane.data.materials) if material]
        fbp_remove_unused_materials_and_images([
            old for old in old_materials
            if not any(old == current for current in committed_materials)
        ])
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ImportError) as exc:
        _warn('Could not clean replaced native sequence materials', exc)
    return True
