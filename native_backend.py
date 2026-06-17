"""Blender native image/video backend for Frame by Plane layers."""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import bpy

from .runtime import (
    fbp_warn as _runtime_warn, fbp_set_rna_property_silent,
    fbp_action_fcurves, fbp_remove_action_fcurves,
    fbp_obj_runtime_key,
)
from .layers import set_collection_color_tag, apply_collection_color_to_rig
from .scene_sync import sync_layer_collection


FBP_NATIVE_HOLD_MARGIN = 500
FBP_NATIVE_VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm', '.mpeg', '.mpg', '.mxf', '.ogv'}


def _warn(message, exc=None):
    return _runtime_warn(message, exc)


def _safe_socket(node, contains, excludes=()):
    try:
        from .materials import safe_get_socket
        return safe_get_socket(node, contains, list(excludes))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    opacity = max(0.0, min(1.0, float(opacity)))
    try:
        mat.diffuse_color = (mat.diffuse_color[0], mat.diffuse_color[1], mat.diffuse_color[2], opacity)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    render_method = 'BLENDED' if has_alpha or opacity < 0.999 else 'OPAQUE'
    for attr, value in (
        ('surface_render_method', render_method),
        ('blend_method', 'BLEND' if render_method == 'BLENDED' else 'OPAQUE'),
        ('show_transparent_back', True),
        ('use_screen_refraction', False),
    ):
        if hasattr(mat, attr):
            try:
                setattr(mat, attr, value)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass


def _abspath(path):
    try:
        return bpy.path.abspath(path)
    except Exception:
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return Path(_abspath(str(directory or ""))) / raw


def _is_video_sequence_payload(directory, files):
    files = list(files or [])
    return len(files) == 1 and _is_video_file(_media_path(directory, files[0]))


def _valid_files(directory, files_list):
    files = []
    base = Path(_abspath(str(directory or "")))
    for name in files_list or []:
        raw = str(name or "").strip()
        if not raw:
            continue

        candidates = [_media_path(base, raw)]
        # Some Blender file-browser paths may already be relative to the current
        # blend/project rather than the provided sequence directory. Try them as
        # a fallback, but keep the original relative name when possible.
        if not os.path.isabs(raw):
            candidates.append(Path(_abspath(raw)))

        found = None
        for path in candidates:
            try:
                if path.exists() and path.is_file():
                    found = path
                    break
            except Exception:
                continue
        if not found:
            continue

        try:
            if found.parent.resolve() == base.resolve():
                files.append(found.name)
            else:
                # Absolute fallback. Path joins on Blender/Windows keep this
                # absolute path intact, while still preserving the real file.
                files.append(str(found))
        except Exception:
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
    values = []
    for name in files or []:
        index, _prefix, _suffix, _width = _native_frame_number_from_name(name)
        if index is None:
            return 1
        values.append(index)
    if not values:
        return 1
    try:
        return int(min(values))
    except Exception:
        return 1


def _native_sequence_needs_rename(files):
    """True when filenames may confuse Blender's native Image Sequence reader.

    Problematic source names can be represented through a hidden canonical
    proxy, while the original files remain untouched.
    """
    files = [str(f) for f in (files or []) if f]
    if len(files) <= 1:
        return False

    # Arbitrary numeric starts are supported through fbp_native_frame_number_base
    # and ImageUser.frame_offset. Only gaps or incompatible filename patterns
    # require renaming.
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _native_playback_nodes_are_intact(mat, native_nodes, transparent_flags):
    """Validate the lightweight pieces required before accepting a no-op refresh."""
    try:
        is_video = bool(mat.get("fbp_native_video", False))
        is_static = bool(mat.get("fbp_native_static_image", False)) and not is_video
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False

    expected_source = 'MOVIE' if is_video else ('FILE' if is_static else 'SEQUENCE')
    for node in native_nodes:
        try:
            image = getattr(node, "image", None)
            image_user = getattr(node, "image_user", None)
            if not image or not image_user:
                return False
            if str(getattr(image, "source", "") or "") != expected_source:
                return False
            if not (is_video or is_static) and not _native_frame_offset_animation_exists(node):
                return False
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False

    if any(bool(value) for value in transparent_flags):
        try:
            nodes = mat.node_tree.nodes
            visibility = nodes.get("FBP_Native_Frame_Visibility")
            multiply = nodes.get("FBP_Native_Frame_Alpha")
            if visibility is None or multiply is None:
                return False
            output = visibility.outputs[0]
            data_path = output.path_from_id("default_value")
            if not any(
                str(getattr(curve, "data_path", "") or "") == data_path
                for curve in (fbp_action_fcurves(mat.node_tree) or ())
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

    return (
        str(directory or ""),
        files,
        _native_sequence_frame_base(files),
        needs_proxy,
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
        for key in (
            'fbp_native_runtime_sequence_json',
            'fbp_native_source_sequence_json',
            'fbp_native_sequence_json',
        ):
            try:
                directory, _files = _decode_sequence_json(mat.get(key, ''))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
            if not root.is_dir():
                continue
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                if not child.is_dir():
                    continue
                if not (child / 'fbp_proxy.json').is_file():
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
            if root.is_dir() and not any(root.iterdir()):
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
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    if not plane or not getattr(plane, "data", None):
        return None
    try:
        for mat in plane.data.materials:
            if mat and bool(mat.get("fbp_native_sequence", False)):
                return mat
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _source_sequence_from_material(mat):
    """Return the immutable disk sequence used by the native Image datablock."""
    if not mat:
        return "", []
    directory, files = _decode_sequence_json(mat.get("fbp_native_source_sequence_json", ""))
    if directory and files:
        valid = _valid_files(directory, files)
        if valid:
            return directory, valid
    return "", []


def _row_paths_from_material(mat):
    try:
        values = list(json.loads(str(mat.get("fbp_native_row_paths_json", "") or "")))
        return [str(value or "") for value in values]
    except Exception:
        directory, files = _sequence_from_material(mat)
        return [str(_media_path(directory, name)) for name in files]


def _source_indices_from_material(mat, count):
    raw = mat.get("fbp_native_source_indices_json", "") if mat else ""
    if not str(raw or "").strip():
        return list(range(max(0, int(count or 0))))
    return _decode_json_values(raw, count, 0, int)


def _transparent_flags_from_material(mat, count):
    return _decode_json_values(
        mat.get("fbp_native_transparent_flags_json", "") if mat else "",
        count,
        False,
        bool,
    )


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

    existing_mat = _native_material_from_rig(rig)
    existing_directory, existing_files = _source_sequence_from_material(existing_mat)
    existing_paths = unique_paths(
        str(_media_path(existing_directory, name))
        for name in existing_files
    ) if existing_directory and existing_files else []

    row_keys = {os.path.normcase(path) for path in real_paths}
    source_paths = list(existing_paths)

    # On the first build, discover the complete numeric sequence when all rows
    # belong to one folder. This preserves unused source frames for later edits.
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




def _source_indices_for_rows(mat, row_paths, transparent_flags):
    """Map current UI rows to the immutable source sequence by absolute path."""
    count = max(len(row_paths), len(transparent_flags))
    old_values = _source_indices_from_material(mat, count)
    source_directory, source_files = _source_sequence_from_material(mat)
    lookup = {
        os.path.normcase(os.path.abspath(str(_media_path(source_directory, name)))): index
        for index, name in enumerate(source_files)
    } if source_directory and source_files else {}
    values = []
    for index in range(count):
        is_empty = bool(transparent_flags[index]) if index < len(transparent_flags) else False
        path = str(row_paths[index] or "") if index < len(row_paths) else ""
        if is_empty:
            values.append(0)
            continue
        key = os.path.normcase(os.path.abspath(_abspath(path))) if path else ""
        if key and key in lookup:
            values.append(int(lookup[key]))
        else:
            values.append(int(old_values[index]) if index < len(old_values) else 0)
    return values, len(source_files)

def _read_image_size_static(filepath):
    """Read image dimensions before turning the datablock into a SEQUENCE.

    This intentionally loads a temporary, non-reused image datablock. Reusing an
    existing Image Sequence datablock can return incomplete or misleading size
    information on some Blender builds, which made native planes stay square.
    """
    path = str(filepath or "")
    if not path:
        return 0, 0
    try:
        img = bpy.data.images.load(path, check_existing=False)
    except Exception as exc:
        _warn("Could not read static image size", exc)
        return 0, 0
    try:
        img["fbp_temporary"] = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        pass
    try:
        try:
            img.source = 'FILE'
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        try:
            img.reload()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        width, height = img.size
        return int(width or 0), int(height or 0)
    except Exception as exc:
        _warn("Could not inspect static image size", exc)
        return 0, 0
    finally:
        try:
            # Queue only our temporary reader datablock. The centralized cleanup
            # runs after Blender has finished any image-cache work for this event.
            from .materials import fbp_remove_unused_images
            fbp_remove_unused_images([img])
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError, ImportError):
            pass


def _playback_span_frames(file_count, durations=None, loop_mode='NONE'):
    file_count = max(1, int(file_count or 1))
    durations = [max(1, int(d)) for d in (durations or [1] * file_count)][:file_count]
    if len(durations) < file_count:
        durations.extend([durations[-1] if durations else 1] * (file_count - len(durations)))
    order, seq_durations = _timing_order_for_mode(file_count, durations, loop_mode)
    return max(1, sum(max(1, int(d)) for d in seq_durations))


def _native_hold_bounds(file_count, durations=None, loop_mode='NONE', frame_start=1, margin=FBP_NATIVE_HOLD_MARGIN):
    """Return ImageUser coverage and one-cycle animation Out frame."""
    frame_start = int(frame_start)
    animation_out = frame_start + _playback_span_frames(file_count, durations, loop_mode) - 1
    try:
        scene = bpy.context.scene
        scene_in = int(getattr(scene, 'frame_start', frame_start))
        scene_out = int(getattr(scene, 'frame_end', animation_out))
    except Exception:
        scene_in = frame_start
        scene_out = animation_out
    margin = max(0, int(margin or 0))
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        # Native backend bakes aspect into mesh vertices. Keep the rig scale
        # uniform so the visible image, frame and transform handles agree.
        rig.scale = (1.0, 1.0, 1.0)
        rig.fbp_base_scale_vec = (1.0, 1.0, 1.0)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    if preview_path:
        try:
            rig.fbp_preview_path = preview_path
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
    def decode_sequence(raw):
        try:
            if raw:
                data = json.loads(raw)
                directory = data.get("directory", "")
                files = list(data.get("files", []))
                if directory and files:
                    return directory, files
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        return None

    decoded = decode_sequence(mat.get("fbp_native_sequence_json", "") if mat else "")
    if decoded:
        directory, files = decoded
        try:
            if all(_media_path(directory, f).exists() for f in files):
                return directory, files
        except Exception:
            return directory, files

    try:
        first = mat.get("fbp_image_path", "")
    except Exception:
        first = ""
    if first:
        return os.path.dirname(first), [os.path.basename(first)]
    return "", []


def _rig_rows_are_native_compatible(rig):
    try:
        rows = list(getattr(rig, 'fbp_images', []))
    except Exception:
        return False
    if not rows:
        return False
    directory = None
    real_rows = 0
    for item in rows:
        try:
            if bool(getattr(item, 'is_empty', False)):
                continue
            path = str(getattr(item, 'filepath', '') or '')
            if not path:
                return False
            abs_path = _abspath(path)
            if not os.path.exists(abs_path):
                return False
            real_rows += 1
            d = os.path.dirname(abs_path)
            if directory is None:
                directory = d
            elif os.path.normcase(d) != os.path.normcase(directory):
                return False
        except Exception:
            return False
    return real_rows > 0


def fbp_rig_uses_native_sequence(rig):
    if not rig:
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False
    try:
        for mat in plane.data.materials:
            if mat and bool(mat.get("fbp_native_sequence", False)):
                return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        # A rig may be between list-edit rebuild steps: keep it native only when
        # the current rows can still be represented by one native Image Sequence.
        return bool(rig.get("fbp_native_backend", False)) and _rig_rows_are_native_compatible(rig)
    except Exception:
        return False


def fbp_native_sequence_nodes(mat):
    """Return image texture nodes owned by a native FBP sequence material."""
    nodes = []
    if not mat or not getattr(mat, "use_nodes", False) or not getattr(mat, "node_tree", None):
        return nodes
    try:
        for node in mat.node_tree.nodes:
            if getattr(node, "type", None) == 'TEX_IMAGE' and bool(node.get("fbp_native_sequence_node", False)):
                nodes.append(node)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return nodes


def _load_media_image(first_path, *, is_video=False, is_sequence=True, force_new=False):
    desired_source = 'MOVIE' if is_video else ('SEQUENCE' if is_sequence else 'FILE')
    existing_image_keys = {
        fbp_obj_runtime_key(image) for image in bpy.data.images
    }
    img = bpy.data.images.load(first_path, check_existing=not bool(force_new))
    image_is_new = fbp_obj_runtime_key(img) not in existing_image_keys

    # A single Blender Image datablock cannot safely be shared by a static FILE
    # plane and a SEQUENCE/MOVIE plane. Changing Image.source on the shared block
    # can make the other material turn pink or stop playing, so duplicate it when
    # the existing datablock is already configured for another source type.
    current_source = str(getattr(img, 'source', 'FILE') or 'FILE')
    if current_source != desired_source:
        try:
            img = bpy.data.images.load(first_path, check_existing=False)
            image_is_new = True
        except Exception:
            try:
                img = img.copy()
                image_is_new = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
    if image_is_new:
        try:
            img["fbp_owned"] = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    try:
        img.source = desired_source
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    if force_new:
        try:
            img.reload()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    # Do not force alpha_mode here. On some Blender 5.1/5.2 builds, changing
    # alpha_mode immediately after switching image.source can invalidate image
    # buffers and may crash during large imports. Blender's default PNG alpha
    # handling is enough for Frame by Plane materials.
    return img



def _media_frame_duration(img, fallback=250):
    try:
        value = int(getattr(img, 'frame_duration', 0) or 0)
        if value > 0:
            return value
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        scene = bpy.context.scene
        return max(1, int(scene.frame_end) - int(scene.frame_start) + 1)
    except Exception:
        return max(1, int(fallback or 250))


def _configure_image_user(tex_node, *, frame_start=1, frame_duration=1, frame_offset=0, cyclic=False):
    iu = getattr(tex_node, "image_user", None)
    if not iu:
        return False
    try:
        iu.frame_start = int(frame_start)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        iu.frame_duration = max(1, int(frame_duration))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        iu.frame_offset = int(frame_offset)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        iu.use_auto_refresh = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        iu.use_cyclic = bool(cyclic)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return True


def _clear_frame_offset_driver(tex_node):
    iu = getattr(tex_node, "image_user", None)
    if not iu:
        return
    try:
        iu.driver_remove("frame_offset")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        tree = getattr(tex_node, "id_data", None)
        data_path = iu.path_from_id("frame_offset")
        fbp_remove_action_fcurves(tree, data_path)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def _durations_from_rig(rig, file_count=1, fallback=1):
    fallback = max(1, int(fallback or 1))
    file_count = max(1, int(file_count or 1))
    durations = []
    try:
        for item in getattr(rig, 'fbp_images', []):
            if len(durations) >= file_count:
                break
            if bool(getattr(item, 'is_empty', False)):
                durations.append(fallback)
            else:
                durations.append(max(1, int(getattr(item, 'duration', fallback) or fallback)))
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

    for boundary in boundaries:
        if boundary > elapsed_max:
            continue
        cycle_index = max(0, (first_elapsed - boundary + cycle_total - 1) // cycle_total)
        elapsed = boundary + cycle_index * cycle_total
        while elapsed <= elapsed_max:
            if elapsed >= first_elapsed:
                yield elapsed
            elapsed += cycle_total


def _install_frame_offset_keyframes(tex_node, *, file_count=1, frame_start=1, durations=None, loop_mode='NONE', frame_number_base=1, source_indices=None, image_user_start=None, hold_start=None, hold_end=None):
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
    try:
        frame_number_base = int(frame_number_base)
    except (TypeError, ValueError):
        frame_number_base = 1
    native_base_offset = frame_number_base - 1
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
        file_count, durations, loop_mode, frame_start
    )
    hold_start = int(calculated_hold_in if hold_start is None else hold_start)
    hold_start = min(hold_start, frame_start)
    image_user_start = int(hold_start if image_user_start is None else image_user_start)
    hold_end = max(frame_start, int(calculated_hold_out if hold_end is None else hold_end))

    try:
        data_path = iu.path_from_id("frame_offset")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        data_path = None

    def offset_at(timeline_frame):
        return int(
            native_base_offset
            + mapped_source_index(int(timeline_frame) - frame_start)
            - (int(timeline_frame) - image_user_start)
        )

    def set_key(timeline_frame):
        iu.frame_offset = offset_at(timeline_frame)
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

        for timeline_frame in sorted(key_frames):
            set_key(timeline_frame)

        tree = getattr(tex_node, "id_data", None)
        if data_path:
            for fcurve in fbp_action_fcurves(tree) or ():
                if fcurve.data_path == data_path:
                    for point in fcurve.keyframe_points:
                        point.interpolation = 'LINEAR'

        try:
            current = int(bpy.context.scene.frame_current)
            evaluated = max(hold_start, min(current, hold_end))
            iu.frame_offset = offset_at(evaluated)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            iu.frame_offset = native_base_offset
        return True
    except Exception as exc:
        _warn("Could not keyframe native ImageUser timing", exc)
        try:
            iu.frame_offset = native_base_offset
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        tree = getattr(value_node, "id_data", None)
        data_path = output.path_from_id("default_value")
        fbp_remove_action_fcurves(tree, data_path)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def _install_visibility_mask_keyframes(value_node, *, row_count=1, frame_start=1, durations=None, loop_mode='NONE', transparent_flags=None):
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return True

    hold_in, hold_out, _animation_out = _native_hold_bounds(
        row_count, durations, loop_mode, frame_start
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
        output.default_value = visibility_at(getattr(bpy.context.scene, 'frame_current', frame_start))
        return True
    except Exception as exc:
        _warn("Could not bake transparent-frame visibility", exc)
        try:
            output.default_value = 1.0
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return False


def _ensure_visibility_mask_nodes(mat, alpha_source, *, row_count=1, frame_start=1, durations=None, loop_mode='NONE', transparent_flags=None):
    if not mat or not getattr(mat, 'use_nodes', False):
        return alpha_source
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
        pass
    _link_once(links, alpha_source, multiply.inputs[0])
    _link_once(links, value_node.outputs[0], multiply.inputs[1])
    _install_visibility_mask_keyframes(
        value_node,
        row_count=row_count,
        frame_start=frame_start,
        durations=durations,
        loop_mode=loop_mode,
        transparent_flags=transparent_flags,
    )
    return multiply.outputs[0]


def _install_frame_offset_driver(tex_node, *, rig=None, file_count=1, frame_start=1, duration=1, loop_mode='NONE', frame_number_base=1, image_user_start=None):
    """Drive a uniform native sequence from Animation In onward."""
    iu = getattr(tex_node, "image_user", None)
    if not iu:
        return False
    _clear_frame_offset_driver(tex_node)
    file_count = max(1, int(file_count))
    duration = max(1, int(duration))
    frame_start = int(frame_start)
    loop_mode = str(loop_mode or 'NONE')
    try:
        frame_number_base = int(frame_number_base)
    except Exception:
        frame_number_base = 1
    native_base_offset = frame_number_base - 1
    image_user_start = int(frame_start if image_user_start is None else image_user_start)

    def target_index_at(timeline_frame):
        step = max(0, (int(timeline_frame) - frame_start) // duration)
        if loop_mode == 'REPEAT':
            return step % file_count
        if loop_mode == 'PINGPONG' and file_count > 1:
            period = max(1, (file_count * 2) - 2)
            return abs(((step + file_count - 1) % period) - (file_count - 1))
        return min(file_count - 1, step)

    # Set a valid source frame immediately. Blender may draw the material before
    # the newly-created driver has completed its first depsgraph evaluation.
    try:
        current_frame = int(getattr(getattr(bpy, 'context', None), 'scene', None).frame_current)
    except Exception:
        current_frame = frame_start
    try:
        iu.frame_offset = int(
            native_base_offset
            + target_index_at(current_frame)
            - (current_frame - image_user_start)
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    step_expr = f"floor(max(0, frame - {frame_start}) / {duration})"
    if loop_mode == 'REPEAT':
        target_expr = f"(({step_expr}) % {file_count})"
    elif loop_mode == 'PINGPONG' and file_count > 1:
        period = max(1, (file_count * 2) - 2)
        target_expr = f"abs((((({step_expr}) + {file_count - 1}) % {period}) - {file_count - 1}))"
    else:
        target_expr = f"min({file_count - 1}, ({step_expr}))"

    expr = f"({native_base_offset}) + ({target_expr}) - (frame - {image_user_start})"

    try:
        fcu = iu.driver_add("frame_offset")
        drv = fcu.driver
        drv.type = 'SCRIPTED'
        drv.expression = expr
        return True
    except Exception as exc:
        _warn("Could not add native ImageUser frame driver; falling back to ImageUser settings", exc)
        try:
            iu.frame_offset = native_base_offset
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        return False




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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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

    if row_paths is None:
        row_paths = [str(_media_path(original_directory, name)) for name in original_files]
    else:
        row_paths = [str(path or "") for path in row_paths]
    inferred_count = max(len(row_paths), len(source_indices or []), len(transparent_flags or []), len(original_files), 1)
    row_count = int(inferred_count)

    transparent_flags = [bool(value) for value in list(transparent_flags or [])[:row_count]]
    while len(transparent_flags) < row_count:
        transparent_flags.append(False)
    while len(row_paths) < row_count:
        row_paths.append("")
    initial_durations = [max(1, int(value)) for value in list(item_durations or [])[:row_count]]
    while len(initial_durations) < row_count:
        initial_durations.append(max(1, int(frame_duration_per_image)))

    source_is_video = _is_video_sequence_payload(source_directory, source_files)
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
        source_indices = [max(0, int(value)) for value in list(source_indices)[:row_count]]
        while len(source_indices) < row_count:
            source_indices.append(min(len(source_indices), max(0, len(runtime_files) - 1)))

    first_path = str(_media_path(runtime_directory, runtime_files[0]))
    first_display_path = next((path for path in row_paths if path), first_path)
    is_video = bool(source_is_video)
    is_static_image = row_count == 1 and not is_video and not bool(transparent_flags[0] if transparent_flags else False)
    source_width, source_height = _read_image_size_static(first_display_path)
    opacity = max(0.0, min(1.0, float(opacity)))
    use_emission = bool(use_emission)
    mat = bpy.data.materials.new(_unique_material_name(mat_name))
    mat["fbp_owned"] = True
    mat.use_nodes = True
    _configure_material_surface(mat, opacity, has_alpha=True)

    mat["fbp_native_sequence"] = True
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
        str(loop_mode or 'NONE'),
        int(frame_start),
        str(extension_mode or 'EDGE'),
    )
    mat["fbp_native_frame_start"] = int(frame_start)
    mat["fbp_native_loop_mode"] = str(loop_mode or 'NONE')
    mat["fbp_native_extension_mode"] = str(extension_mode or 'EDGE')
    if source_width > 0 and source_height > 0:
        mat["fbp_source_width"] = int(source_width)
        mat["fbp_source_height"] = int(source_height)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (560, 0)

    tex = nodes.new(type='ShaderNodeTexImage')
    tex.name = 'FBP_Native_Media_Texture'
    tex.label = 'Frame by Plane Native Video' if is_video else ('Frame by Plane Static Image' if is_static_image else 'Frame by Plane Native Image Sequence')
    tex.location = (-440, 80)
    tex["fbp_native_sequence_node"] = True
    try:
        tex.interpolation = interp
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        tex.extension = 'REPEAT' if str(extension_mode).upper() == 'REPEAT' else 'EXTEND'
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        tex.image = _load_media_image(
            first_path,
            is_video=is_video,
            is_sequence=not is_static_image,
            force_new=bool(uses_proxy),
        )
    except Exception as exc:
        _warn("Could not load native sequence image", exc)

    color_source = tex.outputs['Color']
    alpha_source = tex.outputs['Alpha']
    if is_video:
        movie_duration = _media_frame_duration(getattr(tex, 'image', None), fallback=250)
        mat["fbp_native_frame_count"] = int(movie_duration)
        _configure_image_user(
            tex,
            frame_start=int(frame_start),
            frame_duration=movie_duration,
            frame_offset=0,
            cyclic=str(loop_mode or 'NONE') == 'REPEAT',
        )
    elif is_static_image:
        _clear_frame_offset_driver(tex)
        _configure_image_user(
            tex,
            frame_start=1,
            frame_duration=1,
            frame_offset=0,
            cyclic=False,
        )
    else:
        hold_in, hold_out, _animation_out = _native_hold_bounds(
            row_count, initial_durations, str(loop_mode or 'NONE'), int(frame_start)
        )
        _configure_image_user(
            tex,
            frame_start=hold_in,
            frame_duration=max(1, hold_out - hold_in + 1),
            frame_offset=0,
            cyclic=False,
        )
        identity_order = source_indices == list(range(row_count))
        uniform_duration = (
            initial_durations[0]
            if initial_durations and all(value == initial_durations[0] for value in initial_durations)
            else None
        )
        if identity_order and uniform_duration is not None:
            _install_frame_offset_driver(
                tex,
                file_count=row_count,
                frame_start=int(frame_start),
                duration=int(uniform_duration),
                loop_mode=str(loop_mode or 'NONE'),
                frame_number_base=int(native_frame_base),
                image_user_start=hold_in,
            )
        else:
            _install_frame_offset_keyframes(
                tex,
                file_count=row_count,
                frame_start=int(frame_start),
                durations=initial_durations,
                loop_mode=str(loop_mode or 'NONE'),
                frame_number_base=int(native_frame_base),
                source_indices=source_indices,
                image_user_start=hold_in,
                hold_start=hold_in,
                hold_end=hold_out,
            )

    if any(transparent_flags):
        alpha_source = _ensure_visibility_mask_nodes(
            mat,
            alpha_source,
            row_count=row_count,
            frame_start=int(frame_start),
            durations=initial_durations,
            loop_mode=str(loop_mode or 'NONE'),
            transparent_flags=transparent_flags,
        )

    if use_emission:
        shader = nodes.new(type='ShaderNodeEmission')
        shader.location = (120, 90)
        color_socket = _safe_socket(shader, ['color']) or shader.inputs[0]
        links.new(color_source, color_socket)
        strength = _safe_socket(shader, ['strength'])
        if strength:
            try:
                strength.default_value = 1.0
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
    else:
        shader = nodes.new(type='ShaderNodeBsdfPrincipled')
        shader.location = (120, 90)
        base = _safe_socket(shader, ['base', 'color']) or shader.inputs[0]
        links.new(color_source, base)
        alpha = _safe_socket(shader, ['alpha'])
        if alpha:
            try:
                links.new(alpha_source, alpha)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
        for names, value in ((['specular'], 0.0), (['specular', 'ior', 'level'], 0.0), (['roughness'], 1.0)):
            sock = _safe_socket(shader, names)
            if sock:
                try:
                    sock.default_value = value
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
        transparent.location = (110, -160)
        mix = nodes.new(type='ShaderNodeMixShader')
        mix.location = (340, 0)
        links.new(alpha_source, mix.inputs[0])
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(shader.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs[0])
    else:
        links.new(shader.outputs[0], out.inputs[0])

    return mat

def rebuild_native_sequence_material(mat, *, use_emission=None, opacity=None, interp=None, frame_start=None, frame_duration_per_image=None, loop_mode=None, extension_mode=None):
    if not mat:
        return mat
    directory, files = _sequence_from_material(mat)
    if not directory or not files:
        return mat
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
    item_durations = _decode_json_values(
        mat.get("fbp_native_item_durations_json", ""),
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
        item_durations=item_durations,
    )


def fbp_refresh_native_sequence_from_rig(rig):
    """Synchronize native playback only when its effective state changed."""
    if not rig or not fbp_rig_uses_native_sequence(rig):
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False

    changed = False
    refreshed = False
    try:
        frame_start = int(getattr(rig, "fbp_start_frame", 1))
        duration = max(1, int(getattr(rig, "fbp_global_duration", 1)))
        loop_mode = str(getattr(rig, "fbp_loop_mode", 'NONE'))
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
            if bool(mat.get("fbp_native_uses_proxy", False)) and not _runtime_sequence_is_available(mat):
                return False

            native_nodes = fbp_native_sequence_nodes(mat)
            if not native_nodes:
                continue

            try:
                previous_signature = str(mat.get("fbp_native_playback_signature", "") or "")
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                previous_signature = ""
            try:
                stored_extension = str(mat.get("fbp_native_extension_mode", "") or "")
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                stored_extension = ""
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
                    mat, native_nodes, transparent_flags
                )
            ):
                refreshed = True
                continue

            source_indices, _source_frame_count = _source_indices_for_rows(
                mat, row_paths, transparent_flags
            )
            try:
                frame_number_base = int(mat.get("fbp_native_frame_number_base", 1))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                frame_number_base = 1
            is_video = bool(mat.get("fbp_native_video", False))
            is_static_image = bool(mat.get("fbp_native_static_image", False)) and not is_video
            uniform_duration = (
                durations[0]
                if durations and all(value == durations[0] for value in durations)
                else None
            )
            identity_order = source_indices == list(range(count))

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

            for node in native_nodes:
                try:
                    node.extension = 'REPEAT' if extension_mode.upper() == 'REPEAT' else 'EXTEND'
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass

                if is_video:
                    _clear_frame_offset_driver(node)
                    _configure_image_user(
                        node,
                        frame_start=frame_start,
                        frame_duration=_media_frame_duration(getattr(node, 'image', None), fallback=count),
                        frame_offset=0,
                        cyclic=loop_mode == 'REPEAT',
                    )
                elif is_static_image:
                    _clear_frame_offset_driver(node)
                    try:
                        if getattr(node, 'image', None):
                            node.image.source = 'FILE'
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                        pass
                    _configure_image_user(
                        node,
                        frame_start=1,
                        frame_duration=1,
                        frame_offset=0,
                        cyclic=False,
                    )
                else:
                    hold_in, hold_out, _animation_out = _native_hold_bounds(
                        count, durations, loop_mode, frame_start
                    )
                    _configure_image_user(
                        node,
                        frame_start=hold_in,
                        frame_duration=max(1, hold_out - hold_in + 1),
                        frame_offset=0,
                        cyclic=False,
                    )
                    if uniform_duration is not None and identity_order:
                        _install_frame_offset_driver(
                            node,
                            file_count=count,
                            frame_start=frame_start,
                            duration=uniform_duration,
                            loop_mode=loop_mode,
                            frame_number_base=frame_number_base,
                            image_user_start=hold_in,
                        )
                    else:
                        _install_frame_offset_keyframes(
                            node,
                            file_count=count,
                            frame_start=frame_start,
                            durations=durations,
                            loop_mode=loop_mode,
                            frame_number_base=frame_number_base,
                            source_indices=source_indices,
                            image_user_start=hold_in,
                            hold_start=hold_in,
                            hold_end=hold_out,
                        )

                mask_node = (
                    mat.node_tree.nodes.get('FBP_Native_Frame_Visibility')
                    if getattr(mat, 'node_tree', None)
                    else None
                )
                alpha_source = node.outputs.get('Alpha') if getattr(mat, 'node_tree', None) else None
                if alpha_source and (any(transparent_flags) or mask_node is not None):
                    _ensure_visibility_mask_nodes(
                        mat,
                        alpha_source,
                        row_count=count,
                        frame_start=frame_start,
                        durations=durations,
                        loop_mode=loop_mode,
                        transparent_flags=transparent_flags,
                    )
                changed = True

            mat["fbp_native_playback_signature"] = current_signature
            refreshed = True
    except Exception as exc:
        _warn("Could not refresh native sequence timing", exc)

    if changed:
        _reapply_fbp_effects(rig)
    return refreshed

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
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                _warn('Could not apply collection color tag to native rig collection', exc)
    try:
        apply_collection_color_to_rig(rig, color_tag, color_variant_index, push_collection=False)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        _warn('Could not apply native rig viewport color', exc)


def build_native_fbp_rig(context, rig_name, directory, files_list, location, color_tag='COLOR_01', target_collection=None, color_variant_index=0, follow_collection_color=True):
    """Build a standard FBP layer using the native backend.

    The object names/properties intentionally match the existing add-on so the
    current UI, layer lists and operators keep working.
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

    rig_mesh = fbp_create_rect_mesh("Mesh_" + rig_name + "_Rig", size=2.1, with_face=False)
    rig = fbp_create_mesh_object(rig_name, rig_mesh, context, location=location, target_collection=target_collection)
    _assign_layer_props(rig, scene, color_tag=color_tag, color_variant_index=color_variant_index, target_collection=target_collection, follow_collection_color=follow_collection_color)
    try:
        rig.fbp_start_frame = int(scene.frame_current)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    fbp_apply_creation_orientation(rig, scene)

    plane_mesh = fbp_create_rect_mesh("Mesh_Plane_" + rig_name, size=2.0, with_face=True)
    plane = fbp_create_mesh_object("Plane_" + rig_name, plane_mesh, context, location=location, target_collection=target_collection)
    plane.is_fbp_plane = True
    plane["fbp_parent_rig_name"] = rig.name
    plane["fbp_native_backend"] = True
    plane.parent = rig
    try:
        plane.matrix_parent_inverse.identity()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    plane.location = (0.0, 0.0, 0.0)
    plane.rotation_euler = (0.0, 0.0, 0.0)
    plane.hide_select = True
    rig.fbp_plane_target = plane
    if target_collection:
        plane.fbp_collection_name = target_collection.name

    first_path = str(_media_path(directory, files[0]))
    source_width, source_height = _read_image_size_static(first_path)
    if source_width > 0 and source_height > 0:
        _store_native_aspect_on_rig(rig, source_width, source_height, first_path)
        _refresh_native_geometry(rig)

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
    )
    plane.data.materials.append(mat)
    _reapply_fbp_effects(rig)

    first_img = None

    for file_name in files:
        path = str(Path(directory) / file_name)
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

    if source_width <= 0 or source_height <= 0:
        try:
            first_img = bpy.data.images.load(first_path, check_existing=True)
            width, height = first_img.size
            _store_native_aspect_on_rig(rig, width, height, getattr(first_img, 'filepath', first_path))
            # Force the mesh away from the temporary square plane immediately.
            _refresh_native_geometry(rig)
        except Exception as exc:
            _warn("Could not set native rig image aspect", exc)

    # Keep timing, frame and generated plane in sync after the UI image rows exist.
    fbp_refresh_native_sequence_from_rig(rig)
    _refresh_native_geometry(rig)

    # Creation-time mesh rebuilds must not erase the requested orientation/depth.
    # Force the final transform state explicitly after native geometry refresh.
    try:
        rig.location = location
        fbp_apply_creation_orientation(rig, scene)
        plane.location = (0.0, 0.0, 0.0)
        plane.rotation_euler = (0.0, 0.0, 0.0)
        plane.scale = (1.0, 1.0, 1.0)
        plane.parent = rig
        plane.matrix_parent_inverse.identity()
    except Exception as exc:
        _warn("Could not enforce native rig creation transform", exc)

    try:
        plane.hide_render = not bool(getattr(rig, 'fbp_is_visible', True))
        for poly in plane.data.polygons:
            poly.material_index = 0
        apply_collection_color_to_rig(rig, color_tag, color_variant_index, push_collection=False)
        sync_layer_collection(context)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        _warn('Could not finalize native rig scene state', exc)

    try:
        context.view_layer.objects.active = rig
        rig.select_set(True)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    return rig



def _snapshot_id_property(owner, key):
    """Return whether an ID property existed and its previous value."""
    try:
        return key in owner, owner.get(key)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False, None


def _restore_id_property(owner, key, snapshot, context_label):
    existed, value = snapshot
    try:
        if existed:
            owner[key] = value
        elif key in owner:
            del owner[key]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        _warn(f"Could not restore {key} after {context_label}", exc)


def _fbp_snapshot_plane_material_state(plane):
    """Snapshot material slots and assignments for transactional rollback."""
    if not plane or not getattr(plane, "data", None):
        return {"slots": [], "polygon_indices": [], "active_index": 0}
    try:
        slots = list(getattr(plane.data, "materials", ()) or ())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        slots = []
    try:
        polygon_indices = [
            int(getattr(polygon, "material_index", 0) or 0)
            for polygon in plane.data.polygons
        ]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        polygon_indices = []
    try:
        active_index = int(getattr(plane, "active_material_index", 0) or 0)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return 0

    try:
        overrides = list(polygon_overrides or ())
        for index, polygon in enumerate(plane.data.polygons):
            custom = overrides[index] if index < len(overrides) else None
            polygon.material_index = index_for(custom)
        plane.active_material_index = index_for(active_override)
        plane.data.update()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return True


def rebuild_native_sequence_from_rig(rig):
    """Rebuild one native source sequence plus the UI playback-order map.

    Material assignment is transactional: the previous slots and backend flags
    stay available until the replacement has been created and assigned.
    """
    if not rig:
        return False
    try:
        if bool(getattr(rig, 'fbp_is_color_plane', False)):
            return False
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
        )
        if not mat:
            raise RuntimeError('native sequence material creation returned no material')

        rig['fbp_native_backend'] = True
        plane['fbp_native_backend'] = True
        _fbp_assign_native_material_with_custom_slots(
            plane,
            mat,
            custom_materials,
            polygon_overrides=polygon_overrides,
            active_override=active_override,
        )
        _reapply_fbp_effects(rig)
    except Exception as exc:
        _fbp_restore_plane_material_state(plane, old_material_state)
        _restore_id_property(rig, 'fbp_native_backend', old_rig_native, 'native rebuild failure')
        _restore_id_property(plane, 'fbp_native_backend', old_plane_native, 'native rebuild failure')
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
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
        _reapply_fbp_effects(rig)
        rig['fbp_native_backend'] = True
        plane['fbp_native_backend'] = True

        if not fbp_refresh_native_sequence_from_rig(rig):
            raise RuntimeError('native sequence timing refresh failed')
    except Exception as exc:
        failed_materials = []
        try:
            failed_materials.extend(
                material for material in list(plane.data.materials)
                if material and not any(material == old for old in old_materials)
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        _fbp_restore_plane_material_state(plane, old_material_state)
        _restore_id_property(rig, 'fbp_native_backend', old_rig_native, 'sequence replacement failure')
        _restore_id_property(plane, 'fbp_native_backend', old_plane_native, 'sequence replacement failure')
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        width, height = _read_image_size_static(first_path)
        if width <= 0 or height <= 0:
            image = bpy.data.images.load(first_path, check_existing=True)
            width, height = image.size
        _store_native_aspect_on_rig(rig, width, height, first_path)
        _refresh_native_geometry(rig)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError) as exc:
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
