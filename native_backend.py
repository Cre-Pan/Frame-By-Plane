"""Blender native image/video backend for Frame by Plane layers."""

import json
import os
import re
from pathlib import Path

import bpy


FBP_NATIVE_BACKEND_VERSION = "1.1.0"
FBP_NATIVE_VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm', '.mpeg', '.mpg', '.mxf', '.ogv'}

try:
    from .migrations import remove_legacy_prestart_visibility
    from .runtime import fbp_warn as _runtime_warn
    from .layers import set_collection_color_tag, apply_collection_color_to_rig
    from .scene_sync import sync_layer_collection
except ImportError:
    from migrations import remove_legacy_prestart_visibility
    from runtime import fbp_warn as _runtime_warn
    from layers import set_collection_color_tag, apply_collection_color_to_rig
    from scene_sync import sync_layer_collection


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


def _is_static_image_payload(directory, files):
    files = list(files or [])
    return len(files) == 1 and not _is_video_sequence_payload(directory, files)


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

    Frame by Plane no longer creates cache copies. Problematic sequences are kept
    linked to their original files and can be renamed intentionally through the
    Rename for Blender tool.
    """
    files = [str(f) for f in (files or []) if f]
    if len(files) <= 1:
        return False

    first_index = _native_sequence_frame_base(files)
    if first_index not in {0, 1}:
        return True

    first_ext = os.path.splitext(files[0])[1].lower()
    first_idx, first_prefix, first_suffix, _first_width = _native_frame_number_from_name(files[0])
    if first_idx is None:
        return True

    expected = first_idx
    for name in files:
        ext = os.path.splitext(name)[1].lower()
        idx, prefix, suffix, _width = _native_frame_number_from_name(name)
        if idx is None or ext != first_ext:
            return True
        if prefix != first_prefix or suffix != first_suffix:
            return True
        if idx != expected:
            return True
        expected += 1
    return False


def fbp_native_sequence_needs_rename(directory, files):
    """Public helper used by UI/operators to expose the rename warning."""
    files = _valid_files(directory, files)
    if not files or len(files) <= 1 or _is_video_sequence_payload(directory, files):
        return False
    return _native_sequence_needs_rename(files)


def _prepare_native_sequence_payload(directory, files):
    """Return (directory, files, frame_base, needs_rename).

    This function intentionally never creates cache files or copies. If a
    sequence may be unsafe for Blender native playback, the material is marked so
    the UI can offer an explicit destructive rename operation.
    """
    files = _valid_files(directory, files)
    if not files:
        return str(directory or ""), [], 1, False
    if len(files) <= 1 or _is_video_sequence_payload(directory, files):
        return str(directory or ""), files, 1, False
    return str(directory or ""), files, _native_sequence_frame_base(files), _native_sequence_needs_rename(files)


def _sequence_json(directory, files):
    data = {
        "directory": str(directory or ""),
        "files": [str(f) for f in (files or [])],
    }
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return ""


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


def _recommended_image_user_duration(file_count, durations=None, loop_mode='NONE', frame_start=1):
    """Return a safe ImageUser.frame_duration.

    The native Image Sequence should never fall off the end and turn pink just
    because Frame by Plane holds frames longer than Blender's default 1 image per
    frame. The offset driver / keyframes decide *which* source frame is shown;
    this duration only keeps the ImageUser active across the full visible span.
    """
    frame_start = int(frame_start)
    visible_span = _playback_span_frames(file_count, durations, loop_mode)
    try:
        scene = bpy.context.scene
        scene_span = max(1, int(scene.frame_end) - min(int(scene.frame_start), frame_start) + 1)
    except Exception:
        scene_span = visible_span
    # Small extra buffer so holding before/after the sequence never exposes the
    # missing-texture pink plane in normal timeline use.
    return max(int(file_count), int(visible_span), int(scene_span)) + 8


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
            rig["fbp_native_aspect_baked"] = True
            rig["fbp_native_aspect_source"] = "static_file_size"
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        # Native backend bakes aspect into mesh vertices. Keep the rig scale
        # uniform so the visible image, frame and transform handles agree.
        rig.scale = (1.0, 1.0, 1.0)
        rig.fbp_base_scale = 1.0
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

    decoded = decode_sequence(mat.get("fbp_native_original_sequence_json", "") if mat else "")
    if decoded:
        return decoded

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
    for item in rows:
        try:
            if bool(getattr(item, 'is_empty', False)):
                return False
            path = str(getattr(item, 'filepath', '') or '')
            if not path:
                return False
            abs_path = _abspath(path)
            if not os.path.exists(abs_path):
                return False
            d = os.path.dirname(abs_path)
            if directory is None:
                directory = d
            elif d != directory:
                return False
        except Exception:
            return False
    return True


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


def _load_media_image(first_path, *, is_video=False, is_sequence=True):
    desired_source = 'MOVIE' if is_video else ('SEQUENCE' if is_sequence else 'FILE')
    img = bpy.data.images.load(first_path, check_existing=True)

    # A single Blender Image datablock cannot safely be shared by a static FILE
    # plane and a SEQUENCE/MOVIE plane. Changing Image.source on the shared block
    # can make the other material turn pink or stop playing, so duplicate it when
    # the existing datablock is already configured for another source type.
    current_source = str(getattr(img, 'source', 'FILE') or 'FILE')
    if current_source != desired_source:
        try:
            img = bpy.data.images.load(first_path, check_existing=False)
        except Exception:
            try:
                img = img.copy()
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
    try:
        img.source = desired_source
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
        data_path = tex_node.path_from_id("image_user.frame_offset")
        ad = getattr(tree, "animation_data", None) if tree else None
        action = getattr(ad, "action", None) if ad else None
        if action:
            for fc in list(action.fcurves):
                if fc.data_path == data_path:
                    action.fcurves.remove(fc)
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
    for src, dur in zip(order, seq_durations):
        acc += max(1, int(dur))
        if local < acc:
            return max(0, min(file_count - 1, int(src)))
    return max(0, min(file_count - 1, int(order[-1] if order else 0)))


def _install_frame_offset_keyframes(tex_node, *, file_count=1, frame_start=1, durations=None, loop_mode='NONE', frame_number_base=1):
    """Bake ImageUser.frame_offset to F-Curves for per-image durations.

    Native ImageUser has a single frame duration, while Frame by Plane lets each
    row in the image list have its own duration. For varied row durations we keep
    the native Image Texture node and bake a lightweight F-Curve on
    image_user.frame_offset. No frame-change handler is needed.
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
    except Exception:
        frame_number_base = 1
    native_base_offset = frame_number_base - 1

    order, seq_durations = _timing_order_for_mode(file_count, durations, loop_mode)
    cycle_total = max(1, sum(seq_durations))
    try:
        scene = bpy.context.scene
        scene_end = max(int(getattr(scene, 'frame_end', frame_start + cycle_total - 1)), frame_start)
    except Exception:
        scene_end = frame_start + cycle_total - 1
    if loop_mode in {'REPEAT', 'PINGPONG'}:
        end_frame = max(scene_end, frame_start + cycle_total - 1)
    else:
        end_frame = frame_start + cycle_total - 1

    # Safety cap: avoid accidentally creating enormous F-Curves from a huge scene.
    max_keys = 5000
    if end_frame - frame_start + 1 > max_keys:
        end_frame = frame_start + max_keys - 1

    data_path = None
    try:
        data_path = tex_node.path_from_id("image_user.frame_offset")
    except Exception:
        data_path = None

    try:
        try:
            scene = bpy.context.scene
            pre_frame = min(int(getattr(scene, 'frame_start', frame_start)), frame_start)
            post_frame = max(int(getattr(scene, 'frame_end', end_frame)), end_frame)
        except Exception:
            pre_frame = frame_start
            post_frame = end_frame

        first_src = _source_index_at_elapsed(0, file_count, durations, loop_mode)
        iu.frame_offset = int(native_base_offset + first_src - (pre_frame - frame_start))
        if data_path:
            tex_node.id_data.keyframe_insert(data_path=data_path, frame=pre_frame)
        else:
            iu.keyframe_insert(data_path="frame_offset", frame=pre_frame)

        for timeline_frame in range(frame_start, end_frame + 1):
            elapsed = timeline_frame - frame_start
            src_index = _source_index_at_elapsed(elapsed, file_count, durations, loop_mode)
            iu.frame_offset = int(native_base_offset + src_index - elapsed)
            if data_path:
                tex_node.id_data.keyframe_insert(data_path=data_path, frame=timeline_frame)
            else:
                iu.keyframe_insert(data_path="frame_offset", frame=timeline_frame)

        final_elapsed = max(0, end_frame - frame_start)
        final_src = _source_index_at_elapsed(final_elapsed, file_count, durations, loop_mode)
        iu.frame_offset = int(native_base_offset + final_src - (post_frame - frame_start))
        if data_path:
            tex_node.id_data.keyframe_insert(data_path=data_path, frame=post_frame)
        else:
            iu.keyframe_insert(data_path="frame_offset", frame=post_frame)
        try:
            tree = getattr(tex_node, "id_data", None)
            action = getattr(getattr(tree, "animation_data", None), "action", None)
            if action and data_path:
                for fc in action.fcurves:
                    if fc.data_path == data_path:
                        for kp in fc.keyframe_points:
                            kp.interpolation = 'CONSTANT'
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        try:
            iu.frame_offset = int(native_base_offset + _source_index_at_elapsed(max(0, bpy.context.scene.frame_current - frame_start), file_count, durations, loop_mode) - max(0, bpy.context.scene.frame_current - frame_start))
        except Exception:
            iu.frame_offset = 0
        return True
    except Exception as exc:
        _warn("Could not bake native ImageUser per-frame timing", exc)
        try:
            iu.frame_offset = native_base_offset
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        return False


def _install_frame_offset_driver(tex_node, *, rig=None, file_count=1, frame_start=1, duration=1, loop_mode='NONE', frame_number_base=1):
    """Drive ImageUser.frame_offset without a playback handler.

    Blender image sequences normally advance one source image per timeline frame.
    Frame by Plane's UI uses `Duration` as hold-time per imported image. To keep
    the native Image Texture node but respect that UI, the driver compensates
    Blender's built-in timeline advance:

        desired_source_index = floor((scene_frame - start) / duration)
        frame_offset = desired_source_index - (scene_frame - start)

    Without this compensation, a layer set to duration 2 still appears to play
    at one image per frame.
    """
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

    try:
        iu.frame_offset = native_base_offset
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    if file_count <= 1:
        return True

    step_expr = f"floor(max(0, frame - {frame_start}) / {duration})"
    if loop_mode == 'REPEAT':
        target_expr = f"(({step_expr}) % {file_count})"
    elif loop_mode == 'PINGPONG' and file_count > 1:
        period = max(1, (file_count * 2) - 2)
        target_expr = f"abs((((({step_expr}) + {file_count - 1}) % {period}) - {file_count - 1}))"
    else:
        target_expr = f"min({file_count - 1}, ({step_expr}))"

    # ImageUser applies `frame - frame_start` internally. The offset must cancel
    # that internal advance and replace it with the held FBP index.
    expr = f"({native_base_offset}) + ({target_expr}) - (frame - {frame_start})"

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


def _configure_prestart_switch_driver(switch_node, frame_start):
    """Drive a 0/1 value: static first frame before Start, sequence from Start onward."""
    if not switch_node:
        return False
    try:
        output = switch_node.outputs[0]
        try:
            output.driver_remove('default_value')
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        fcurve = output.driver_add('default_value')
        fcurve.driver.type = 'SCRIPTED'
        fcurve.driver.expression = f"frame >= {int(frame_start)}"
        return True
    except Exception as exc:
        _warn('Could not configure pre-start first-frame switch', exc)
        try:
            switch_node.outputs[0].default_value = 1.0
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        return False


def _make_static_first_frame_image(sequence_image, first_path, material_name):
    """Create a separate FILE image datablock so changing its source cannot affect the sequence."""
    image = None
    try:
        if sequence_image:
            image = sequence_image.copy()
    except Exception:
        image = None
    if image is None:
        try:
            image = bpy.data.images.load(str(first_path), check_existing=False)
        except Exception as exc:
            _warn('Could not load static first-frame image', exc)
            return None
    try:
        image.name = f"FBP First Frame · {material_name}"
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        image.filepath = str(first_path)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        image.source = 'FILE'
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        image['fbp_prestart_first_frame'] = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return image


def _ensure_prestart_first_frame_nodes(mat, sequence_node, first_path, frame_start, interp='Closest', extension_mode='EDGE'):
    """Show a static copy of frame 1 before Start Frame, then switch to the native sequence.

    The sequence node is intentionally left native and keeps its normal ImageUser timing.
    Only its visibility is switched, which avoids reverse playback before Start Frame.
    """
    if not mat or not sequence_node or not getattr(mat, 'use_nodes', False):
        return sequence_node.outputs.get('Color'), sequence_node.outputs.get('Alpha')
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    static_tex = nodes.get('FBP_PreStart_FirstFrame')
    if static_tex is None:
        static_tex = nodes.new(type='ShaderNodeTexImage')
        static_tex.name = 'FBP_PreStart_FirstFrame'
        static_tex.label = 'Frame by Plane · First Frame Hold'
        static_tex.location = (-440, -170)
    try:
        static_tex.interpolation = interp
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        static_tex.extension = 'REPEAT' if str(extension_mode).upper() == 'REPEAT' else 'EXTEND'
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    needs_image = getattr(static_tex, 'image', None) is None
    if not needs_image:
        try:
            current = bpy.path.abspath(getattr(static_tex.image, 'filepath', '') or '')
            needs_image = bool(first_path) and os.path.normcase(os.path.abspath(current)) != os.path.normcase(os.path.abspath(str(first_path)))
        except Exception:
            needs_image = False
    if needs_image:
        static_tex.image = _make_static_first_frame_image(getattr(sequence_node, 'image', None), first_path, mat.name)
    if getattr(static_tex, 'image', None):
        try:
            static_tex.image.source = 'FILE'
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        _configure_image_user(static_tex, frame_start=1, frame_duration=1, frame_offset=0, cyclic=False)

    switch = nodes.get('FBP_PreStart_Switch')
    if switch is None:
        switch = nodes.new(type='ShaderNodeValue')
        switch.name = 'FBP_PreStart_Switch'
        switch.label = 'Use Sequence From Start Frame'
        switch.location = (-185, -270)
    _configure_prestart_switch_driver(switch, frame_start)

    color_mix = nodes.get('FBP_PreStart_ColorMix')
    if color_mix is None:
        color_mix = nodes.new(type='ShaderNodeMixRGB')
        color_mix.name = 'FBP_PreStart_ColorMix'
        color_mix.label = 'First Frame / Sequence'
        color_mix.blend_type = 'MIX'
        color_mix.location = (-120, 100)

    alpha_mix = nodes.get('FBP_PreStart_AlphaMix')
    if alpha_mix is None:
        alpha_mix = nodes.new(type='ShaderNodeMixRGB')
        alpha_mix.name = 'FBP_PreStart_AlphaMix'
        alpha_mix.label = 'First Alpha / Sequence Alpha'
        alpha_mix.blend_type = 'MIX'
        alpha_mix.location = (-120, -90)

    # Preserve any existing shader/opacity targets by inserting the two mix nodes
    # between the native sequence texture and its downstream sockets.
    color_targets = []
    alpha_targets = []
    try:
        for link in list(sequence_node.outputs['Color'].links):
            if link.to_node != color_mix:
                color_targets.append(link.to_socket)
                links.remove(link)
        for link in list(sequence_node.outputs['Alpha'].links):
            if link.to_node != alpha_mix:
                alpha_targets.append(link.to_socket)
                links.remove(link)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    _link_once(links, switch.outputs[0], color_mix.inputs[0])
    _link_once(links, static_tex.outputs['Color'], color_mix.inputs[1])
    _link_once(links, sequence_node.outputs['Color'], color_mix.inputs[2])
    _link_once(links, switch.outputs[0], alpha_mix.inputs[0])
    _link_once(links, static_tex.outputs['Alpha'], alpha_mix.inputs[1])
    _link_once(links, sequence_node.outputs['Alpha'], alpha_mix.inputs[2])

    for socket in color_targets:
        _link_once(links, color_mix.outputs['Color'], socket)
    for socket in alpha_targets:
        _link_once(links, alpha_mix.outputs['Color'], socket)

    return color_mix.outputs['Color'], alpha_mix.outputs['Color']


def create_native_sequence_material(mat_name, directory, files, *, interp='Closest', opacity=1.0, use_emission=True, frame_start=1, frame_duration_per_image=1, loop_mode='NONE', extension_mode='EDGE'):
    """Create a unique material backed by a native Blender Image Sequence node."""
    original_directory = str(directory or "")
    original_files = _valid_files(original_directory, files)
    if not original_files:
        raise FileNotFoundError("No valid image files supplied for native sequence material")

    directory, files, native_frame_base, needs_rename = _prepare_native_sequence_payload(original_directory, original_files)
    if not files:
        raise FileNotFoundError("No valid image files supplied for native sequence material")

    first_path = str(_media_path(directory, files[0]))
    original_first_path = str(_media_path(original_directory, original_files[0]))
    is_static_image = _is_static_image_payload(directory, files)
    is_video = _is_video_sequence_payload(directory, files)
    source_width, source_height = _read_image_size_static(original_first_path)
    opacity = max(0.0, min(1.0, float(opacity)))
    use_emission = bool(use_emission)
    mat = bpy.data.materials.new(_unique_material_name(mat_name))
    mat.use_nodes = True
    _configure_material_surface(mat, opacity, has_alpha=True)

    mat["fbp_native_sequence"] = True
    mat["fbp_native_video"] = bool(is_video)
    mat["fbp_native_static_image"] = bool(is_static_image)
    mat["fbp_native_backend_version"] = FBP_NATIVE_BACKEND_VERSION
    mat["fbp_native_sequence_json"] = _sequence_json(directory, files)
    mat["fbp_native_original_sequence_json"] = _sequence_json(original_directory, original_files)
    mat["fbp_native_needs_rename"] = bool(needs_rename)
    mat["fbp_native_frame_number_base"] = int(native_frame_base)
    mat["fbp_image_path"] = original_first_path
    mat["fbp_native_runtime_image_path"] = first_path
    mat["fbp_interpolation"] = interp
    mat["fbp_use_emission"] = bool(use_emission)
    mat["fbp_opacity"] = opacity
    mat["fbp_native_frame_count"] = len(files)
    mat["fbp_native_duration_per_image"] = max(1, int(frame_duration_per_image))
    mat["fbp_native_frame_start"] = int(frame_start)
    mat["fbp_native_loop_mode"] = str(loop_mode or 'NONE')
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
        tex.image = _load_media_image(first_path, is_video=is_video, is_sequence=not is_static_image)
    except Exception as exc:
        _warn("Could not load native sequence image", exc)

    color_source = tex.outputs['Color']
    alpha_source = tex.outputs['Alpha']
    if not is_video and not is_static_image:
        color_source, alpha_source = _ensure_prestart_first_frame_nodes(
            mat, tex, first_path, int(frame_start), interp=interp, extension_mode=extension_mode
        )

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
        mat["fbp_native_timing_mode"] = 'STATIC_FILE'
        _clear_frame_offset_driver(tex)
        _configure_image_user(
            tex,
            frame_start=1,
            frame_duration=1,
            frame_offset=0,
            cyclic=False,
        )
    else:
        # Keep the ImageUser active for the whole visible playback span. The actual
        # per-frame image selection is still controlled by frame_offset below.
        native_duration = _recommended_image_user_duration(
            len(files),
            [max(1, int(frame_duration_per_image))] * max(1, len(files)),
            loop_mode=str(loop_mode or 'NONE'),
            frame_start=int(frame_start),
        )
        _configure_image_user(
            tex,
            frame_start=int(frame_start),
            frame_duration=native_duration,
            frame_offset=0,
            cyclic=str(loop_mode or 'NONE') in {'REPEAT', 'PINGPONG'},
        )
        _install_frame_offset_driver(
            tex,
            file_count=len(files),
            frame_start=int(frame_start),
            duration=max(1, int(frame_duration_per_image)),
            loop_mode=str(loop_mode or 'NONE'),
            frame_number_base=int(native_frame_base),
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
                links.new(tex.outputs['Alpha'], alpha)
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
        multiply.operation = 'MULTIPLY'
        multiply.location = (-130, -165)
        multiply.inputs[1].default_value = opacity
        links.new(alpha_source, multiply.inputs[0])
        alpha_source = multiply.outputs['Value']

    # Before Start Frame, native ImageUser timing holds the first sequence frame.

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
    )


def fbp_refresh_native_sequence_from_rig(rig):
    """Sync native ImageUser timing from existing FBP rig properties."""
    if not rig or not fbp_rig_uses_native_sequence(rig):
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False
    changed = False
    try:
        frame_start = int(getattr(rig, "fbp_start_frame", 1))
        duration = max(1, int(getattr(rig, "fbp_global_duration", 1)))
        loop_mode = str(getattr(rig, "fbp_loop_mode", 'NONE'))
        extension_mode = str(getattr(rig, "fbp_extend_mode", 'EDGE'))
        for mat in list(plane.data.materials):
            if not mat or not bool(mat.get("fbp_native_sequence", False)):
                continue
            remove_legacy_prestart_visibility(mat)
            mat["fbp_native_frame_start"] = frame_start
            mat["fbp_native_duration_per_image"] = duration
            mat["fbp_native_loop_mode"] = loop_mode
            mat["fbp_native_extension_mode"] = extension_mode
            count = max(1, int(mat.get("fbp_native_frame_count", max(1, len(getattr(rig, 'fbp_images', []))))))
            try:
                frame_number_base = int(mat.get("fbp_native_frame_number_base", 1))
            except Exception:
                frame_number_base = 1
            is_static_image = bool(mat.get("fbp_native_static_image", False)) or (count <= 1 and not bool(mat.get("fbp_native_video", False)))
            if is_static_image:
                mat["fbp_native_static_image"] = True
                mat["fbp_native_timing_mode"] = 'STATIC_FILE'
                for node in fbp_native_sequence_nodes(mat):
                    try:
                        node.extension = 'REPEAT' if extension_mode.upper() == 'REPEAT' else 'EXTEND'
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                        pass
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
                changed = True
                continue
            durations = _durations_from_rig(rig, count, duration)
            mat["fbp_native_item_durations_json"] = json.dumps(durations)
            uniform_duration = durations[0] if durations and all(d == durations[0] for d in durations) else None
            if uniform_duration is not None:
                mat["fbp_native_timing_mode"] = 'DRIVER_UNIFORM'
                mat["fbp_native_duration_per_image"] = int(uniform_duration)
            else:
                mat["fbp_native_timing_mode"] = 'KEYFRAMED_PER_ITEM'
            seq_directory, seq_files = _sequence_from_material(mat)
            seq_first_path = str(_media_path(seq_directory, seq_files[0])) if seq_directory and seq_files else str(mat.get('fbp_image_path', '') or '')
            for node in fbp_native_sequence_nodes(mat):
                try:
                    node.extension = 'REPEAT' if extension_mode.upper() == 'REPEAT' else 'EXTEND'
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
                if bool(mat.get("fbp_native_video", False)):
                    _clear_frame_offset_driver(node)
                    _configure_image_user(
                        node,
                        frame_start=frame_start,
                        frame_duration=_media_frame_duration(getattr(node, 'image', None), fallback=count),
                        frame_offset=0,
                        cyclic=loop_mode == 'REPEAT',
                    )
                else:
                    _configure_image_user(
                        node,
                        frame_start=frame_start,
                        frame_duration=_recommended_image_user_duration(count, durations, loop_mode, frame_start),
                        frame_offset=0,
                        cyclic=loop_mode in {'REPEAT', 'PINGPONG'},
                    )
                    if uniform_duration is not None:
                        _install_frame_offset_driver(
                            node,
                            file_count=count,
                            frame_start=frame_start,
                            duration=uniform_duration,
                            loop_mode=loop_mode,
                            frame_number_base=frame_number_base,
                        )
                    else:
                        _install_frame_offset_keyframes(
                            node,
                            file_count=count,
                            frame_start=frame_start,
                            durations=durations,
                            loop_mode=loop_mode,
                            frame_number_base=frame_number_base,
                        )
                    _ensure_prestart_first_frame_nodes(
                        mat, node, seq_first_path, frame_start,
                        interp=str(getattr(node, 'interpolation', mat.get('fbp_interpolation', 'Closest'))),
                        extension_mode=extension_mode,
                    )
                changed = True
    except Exception as exc:
        _warn("Could not refresh native sequence timing", exc)
    return changed


def _assign_layer_props(rig, scene, *, color_tag='COLOR_01', color_variant_index=0, target_collection=None, follow_collection_color=True):
    rig.is_fbp_control = True
    rig.hide_render = True
    rig.display_type = 'WIRE'
    rig["fbp_sequence_backend"] = 'NATIVE_IMAGE_SEQUENCE'
    rig["fbp_native_backend"] = True
    rig["fbp_native_backend_version"] = FBP_NATIVE_BACKEND_VERSION
    rig.fbp_global_duration = getattr(scene, 'fbp_pre_duration', 1)
    rig.fbp_use_emission = getattr(scene, 'fbp_pre_shadeless', True)
    rig.fbp_loop_mode = getattr(scene, 'fbp_pre_loop_mode', 'NONE')
    rig.fbp_interpolation = getattr(scene, 'fbp_pre_interpolation', 'Closest')
    rig.fbp_color_tag = color_tag
    rig.fbp_color_variant_index = int(color_variant_index)
    rig.fbp_follow_collection_color = bool(follow_collection_color)
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
    plane["fbp_sequence_backend"] = 'NATIVE_IMAGE_SEQUENCE'
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

    first_img = None

    for index, file_name in enumerate(files):
        path = str(Path(directory) / file_name)
        item = rig.fbp_images.add()
        item.name = str(file_name)
        item.duration = getattr(rig, 'fbp_global_duration', 1)
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


def _paths_from_rig_images(rig):
    paths = []
    for item in getattr(rig, 'fbp_images', []):
        try:
            if bool(getattr(item, 'is_empty', False)):
                return []
            path = str(getattr(item, 'filepath', '') or '')
            if not path:
                return []
            abs_path = _abspath(path)
            if not os.path.exists(abs_path):
                return []
            paths.append(abs_path)
        except Exception:
            return []
    return paths


def rebuild_native_sequence_from_rig(rig):
    """Rebuild the single native material after image-list edits.

    This preserves the existing UI list as the source of truth. In Beta 2.0.1
    every image layer is rebuilt as one native Image Sequence material. Existing
    older image layers are converted on rebuild when their rows point to real
    files in one directory.
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
    paths = _paths_from_rig_images(rig)
    if not paths:
        _warn('Native sequence rebuild skipped: image rows must be real files')
        return False
    directory = os.path.dirname(paths[0])
    if any(os.path.dirname(path) != directory for path in paths):
        _warn('Native sequence rebuild skipped: image rows must stay in one directory')
        return False
    files = [os.path.basename(path) for path in paths]
    try:
        mat = create_native_sequence_material(
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
        plane.data.materials.clear()
        plane.data.materials.append(mat)
        rig['fbp_sequence_backend'] = 'NATIVE_IMAGE_SEQUENCE'
        rig['fbp_native_backend'] = True
        plane['fbp_sequence_backend'] = 'NATIVE_IMAGE_SEQUENCE'
        plane['fbp_native_backend'] = True
        fbp_refresh_native_sequence_from_rig(rig)
        return True
    except Exception as exc:
        _warn('Could not rebuild native sequence from rig list', exc)
        return False


def replace_native_sequence(rig, directory, files):
    """Replace a native rig sequence while preserving transforms and UI."""
    if not rig or not getattr(rig, 'fbp_plane_target', None):
        return False
    files = _valid_files(directory, files)
    if not files:
        return False
    plane = rig.fbp_plane_target
    try:
        rig.fbp_images.clear()
        for f in files:
            item = rig.fbp_images.add()
            item.name = str(f)
            item.duration = max(1, int(getattr(rig, 'fbp_global_duration', 1)))
            item.is_selected = True
            item.is_empty = False
            item.filepath = str(Path(directory) / f)
        rig.fbp_images_index = 0
        mat = create_native_sequence_material(
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
        plane.data.materials.clear()
        plane.data.materials.append(mat)
        rig['fbp_sequence_backend'] = 'NATIVE_IMAGE_SEQUENCE'
        rig['fbp_native_backend'] = True
        plane['fbp_sequence_backend'] = 'NATIVE_IMAGE_SEQUENCE'
        plane['fbp_native_backend'] = True
        first_path = str(_media_path(directory, files[0]))
        try:
            width, height = _read_image_size_static(first_path)
            if width <= 0 or height <= 0:
                img = bpy.data.images.load(first_path, check_existing=True)
                width, height = img.size
            _store_native_aspect_on_rig(rig, width, height, first_path)
            _refresh_native_geometry(rig)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        fbp_refresh_native_sequence_from_rig(rig)
        return True
    except Exception as exc:
        _warn('Could not replace native sequence', exc)
        return False


def register():
    return None


def unregister():
    return None
