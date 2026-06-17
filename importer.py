"""Folder scanning, sequence detection and Fast Import helpers."""

import bpy
import os
import re

from .path_utils import (
    natural_sort_key,
    clean_layer_name_from_path,
    is_hidden_import_name,
    is_supported_video_file,
    is_supported_media_file,
    is_technical_map_file,
)
from .runtime import fbp_runtime_get, fbp_runtime_set, fbp_warn
from .materials import do_update_emission, do_update_opacity
from .builder import build_fbp_rig
from .layers import (
    get_or_create_child_collection,
    set_collection_color_tag,
    sync_collection_colors_to_rigs,
    sync_layer_collection,
)


def _update_animation(rig):
    # core imports importer, so keep this one dependency lazy and explicit.
    from .core import do_update_animation
    return do_update_animation(rig)


def fbp_scene_orientation_is_horizontal(scene):
    value = str(getattr(scene, 'fbp_pre_orientation', 'VERT') or 'VERT').upper()
    return value in {'HORIZ', 'HORIZONTAL'}


# SECTION 00B - Smart Sequence Detection #
# These helpers detect multiple animations inside the same folder.
# Supported examples:
#   A1.png, A2.png, A3.png                 -> layer animato "A"
#   B - 1.png, B - 2.png, B - 3.png       -> layer animato "B"
#   BG_0001.png, BG_0002.png              -> layer animato "BG"
#   0001.png, 0002.png                    -> animated layer named after the folder
#   01 - Walk.png, 02 - Walk.png          -> layer animato "Walk"
#   Walk frame 001.png, Walk frame 002.png-> layer animato "Walk"
#   A (1).png, A (2).png / A - (1).png -> layer animato "A"
# Files that do not form a sequence remain independent images.

_TRAILING_NUMBER_PATTERNS = (
    # Nome (0001) / Nome-(0001) / Nome - (0001) / A(1)
    re.compile(r"^(?P<prefix>.+?)(?:\s*[-_.]\s*)?\((?P<index>\d+)\)$"),
    # Nome - 0001 / Nome_0001 / Nome.0001 / Nome 0001
    re.compile(r"^(?P<prefix>.+?)(?:\s*[-_.]\s*|\s+)(?P<index>\d+)$"),
    # Nome frame 0001 / Nome fr001 / Nome f001
    re.compile(r"^(?P<prefix>.+?)(?:\s*[-_.]?\s*(?:frame|frm|fr|f)\s*[-_.]?\s*)(?P<index>\d+)$", re.IGNORECASE),
    # Nome0001, A1, BG12
    re.compile(r"^(?P<prefix>.*\D)(?P<index>\d+)$"),
)

_LEADING_NUMBER_PATTERNS = (
    # 0001 - Nome / 0001_Nome / 0001.Nome / 0001 Nome
    re.compile(r"^(?P<index>\d+)(?:\s*[-_.]\s*|\s+)(?P<prefix>.+)$"),
    # frame0001 Nome / f001 Nome
    re.compile(r"^(?:frame|frm|fr|f)\s*[-_.]?\s*(?P<index>\d+)(?:\s*[-_.]\s*|\s+)(?P<prefix>.+)$", re.IGNORECASE),
)

_PURE_NUMBER_PATTERN = re.compile(r"^(?P<index>\d+)$")

_SEQUENCE_NOISE_WORDS = {"frame", "frames", "frm", "fr", "f", "image", "img", "shot"}


def _clean_sequence_prefix(prefix, fallback=""):
    prefix = str(prefix or "").strip(" ._-\t")
    fallback = str(fallback or "").strip(" ._-\t")
    if not prefix:
        prefix = fallback or "Sequence"
    parts = [part for part in re.split(r"[\s_.-]+", prefix) if part]
    while parts and parts[-1].lower() in _SEQUENCE_NOISE_WORDS:
        parts.pop()
    while parts and parts[0].lower() in _SEQUENCE_NOISE_WORDS:
        parts.pop(0)
    # A filename made only of noise words (frame_0001, img-02, …) should
    # inherit its folder name instead of producing a layer literally named
    # "frame" or "img".
    return " ".join(parts) if parts else (fallback or "Sequence")


def _sequence_group_key(prefix, ext):
    # Include extension so a rendered PNG sequence and EXR sequence with the same
    # prefix do not accidentally merge into one layer.
    return (str(prefix or "").casefold(), str(ext or "").lower())


def fbp_sequence_key_from_filename(name, folder_name=""):
    """Return (prefix, frame_index) when a filename looks like a sequence frame."""
    stem, _ext = os.path.splitext(os.path.basename(str(name)))
    stem = stem.strip()
    if not stem:
        return None

    pure = _PURE_NUMBER_PATTERN.match(stem)
    if pure:
        return _clean_sequence_prefix(folder_name, "Sequence"), int(pure.group("index"))

    for pattern in _TRAILING_NUMBER_PATTERNS:
        match = pattern.match(stem)
        if match:
            prefix = _clean_sequence_prefix(match.group("prefix"), folder_name)
            try:
                frame_index = int(match.group("index"))
            except Exception:
                frame_index = 0
            return prefix, frame_index

    for pattern in _LEADING_NUMBER_PATTERNS:
        match = pattern.match(stem)
        if match:
            prefix = _clean_sequence_prefix(match.group("prefix"), folder_name)
            try:
                frame_index = int(match.group("index"))
            except Exception:
                frame_index = 0
            return prefix, frame_index

    return None


def fbp_group_direct_media_into_layers(files, folder_name=""):
    """Group direct media filenames into logical image/video layers.

    Returns tuples:
        (layer_name, [file1, file2, ...], is_sequence)

    Videos are intentionally kept as one-file animated layers. Image files are
    grouped into separate sequences when at least two files share a smart prefix.
    """
    ordered = sorted([f for f in files if f], key=natural_sort_key)
    buckets = {}
    order_keys = []

    for filename in ordered:
        if is_supported_video_file(filename):
            key = ("__video__", filename)
            buckets[key] = [(filename, None)]
            order_keys.append(key)
            continue

        parsed = fbp_sequence_key_from_filename(filename, folder_name)
        if not parsed:
            key = ("__single__", filename)
            buckets[key] = [(filename, None)]
            order_keys.append(key)
            continue

        prefix, frame_index = parsed
        ext = os.path.splitext(filename)[1].lower()
        key = ("sequence",) + _sequence_group_key(prefix, ext)
        if key not in buckets:
            buckets[key] = []
            order_keys.append(key)
        buckets[key].append((filename, frame_index))

    result = []
    for key in order_keys:
        values = buckets.get(key, [])
        if not values:
            continue
        if key[0] == "sequence" and len(values) >= 2:
            values.sort(key=lambda item: ((item[1] if item[1] is not None else 0), natural_sort_key(item[0])))
            parsed_first = fbp_sequence_key_from_filename(values[0][0], folder_name)
            layer_name = parsed_first[0] if parsed_first else clean_layer_name_from_path(values[0][0])
            result.append((layer_name, [item[0] for item in values], True))
        else:
            for filename, _frame_index in values:
                result.append((clean_layer_name_from_path(filename), [filename], False))

    return result


# Shared import name for image sequences and video.
def fbp_group_direct_images_into_layers(files, folder_name=""):
    return fbp_group_direct_media_into_layers(files, folder_name)


def fbp_should_flatten_leaf_folder(grouped_layers, child_dirs):
    """Return True when a leaf folder adds no useful Blender collection.

    Flatten exactly one image sequence or exactly one static image into the
    parent collection. A single video keeps its folder collection because it is
    a distinct media container rather than a still-image layer. Folder and layer
    names are deliberately ignored.
    """
    if child_dirs or len(grouped_layers) != 1:
        return False

    _layer_name, files, is_sequence = grouped_layers[0]
    if is_sequence:
        return True
    if len(files) != 1:
        return False
    return not is_supported_video_file(files[0])


# SECTION 01 - File system / Project scan #
def fbp_scan_project_layers_for_setup(root):
    """Return pending setup rows from a project folder.

    A leaf filesystem folder containing exactly one image sequence or one static
    image is flattened into its parent Blender collection. The resulting layer
    keeps an independent color. Folder and layer names are intentionally ignored.

    Rows are returned as:
        (layer_name, collection_name, directory, files, follow_collection_color)
    """
    rows = []
    root = bpy.path.abspath(root)
    if not root or not os.path.isdir(root):
        return rows

    def visit(path, collection_name=""):
        imgs = fbp_folder_direct_images(path)
        dirs = fbp_folder_direct_dirs(path)
        folder_name = clean_layer_name_from_path(path)
        grouped_layers = fbp_group_direct_images_into_layers(imgs, folder_name)

        flatten_single_layer = (
            path != root
            and fbp_should_flatten_leaf_folder(grouped_layers, dirs)
        )

        current_collection = collection_name
        if path != root and not flatten_single_layer:
            current_collection = f"{collection_name} / {folder_name}" if collection_name else folder_name

        # Collections that contain child folders remain neutral. A flattened
        # sequence/static-image folder produces an independently colored layer.
        follows_collection = bool(current_collection) and not dirs and not flatten_single_layer

        for layer_name, files, _is_sequence in grouped_layers:
            rows.append((layer_name, current_collection, path, files, follows_collection))

        for d in dirs:
            visit(os.path.join(path, d), current_collection)

    visit(root, "")
    return rows


# SECTION 02 - Fast Import runtime #

_FBP_FAST_IMPORT_RUNTIME = globals().get(
    "_FBP_FAST_IMPORT_RUNTIME",
    {
        # Runtime-only data. Nothing here is stored as IDProperties, so undo/reload
        # never has to free transient Fast Import state from Blender datablocks.
        "depth": 0,
    },
)


def fbp_fast_import_depth(context=None):
    try:
        return int(_FBP_FAST_IMPORT_RUNTIME.get("depth", 0))
    except Exception:
        return 0


def fbp_set_fast_import_depth(value, context=None):
    try:
        _FBP_FAST_IMPORT_RUNTIME["depth"] = max(0, int(value))
    except Exception as exc:
        fbp_warn("Could not store Fast Import depth", exc)


def fbp_fast_import_is_active():
    return fbp_fast_import_depth() > 0


def fbp_fast_import_queued_names(context=None):
    value = str(fbp_runtime_get("fbp_fast_import_queued_rigs", "", context) or "")
    return [name for name in value.split("|") if name]


def fbp_set_fast_import_queued_names(names, context=None):
    unique = []
    seen = set()
    for name in names:
        if name and name not in seen:
            unique.append(name)
            seen.add(name)
    fbp_runtime_set("fbp_fast_import_queued_rigs", "|".join(unique), context)


def fbp_begin_fast_import(context):
    depth = fbp_fast_import_depth(context) + 1
    fbp_set_fast_import_depth(depth, context)
    if depth != 1:
        return

    fbp_set_fast_import_queued_names([], context)

    prefs_edit = getattr(getattr(bpy.context, "preferences", None), "edit", None)
    if prefs_edit:
        try:
            fbp_runtime_set("fbp_fast_import_undo_state", 1 if prefs_edit.use_global_undo else 0, context)
            prefs_edit.use_global_undo = False
        except Exception:
            fbp_runtime_set("fbp_fast_import_undo_state", -1, context)

    try:
        bpy.context.window_manager.progress_begin(0, 100)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def _fbp_restore_fast_import_runtime(context):
    """Always restore temporary Fast Import state, even after finalization errors."""
    try:
        prefs_edit = getattr(getattr(bpy.context, "preferences", None), "edit", None)
        stored_undo_state = fbp_runtime_get(
            "fbp_fast_import_undo_state", -1, context
        )
        undo_state = int(
            -1 if stored_undo_state is None else stored_undo_state
        )
        if prefs_edit and undo_state >= 0:
            try:
                prefs_edit.use_global_undo = bool(undo_state)
            except Exception as exc:
                fbp_warn("Could not restore global undo", exc)
    finally:
        fbp_runtime_set("fbp_fast_import_undo_state", -1, context)
        fbp_set_fast_import_queued_names([], context)

    try:
        bpy.context.window_manager.progress_update(100)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        bpy.context.window_manager.progress_end()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def fbp_end_fast_import(context):
    depth = fbp_fast_import_depth(context)
    if depth <= 0:
        return
    depth -= 1
    fbp_set_fast_import_depth(depth, context)
    if depth != 0:
        return

    try:
        try:
            scene = (
                getattr(context, "scene", None)
                if context
                else getattr(bpy.context, "scene", None)
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            scene = None

        current_frame = None
        current_subframe = 0.0
        if scene:
            try:
                current_frame = int(scene.frame_current)
                current_subframe = float(getattr(scene, "frame_subframe", 0.0))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                current_frame = None

        seen = set()
        for rig_name in fbp_fast_import_queued_names(context):
            if rig_name in seen:
                continue
            seen.add(rig_name)
            rig = bpy.data.objects.get(rig_name)
            if not rig:
                continue
            try:
                _update_animation(rig)
                do_update_emission(rig)
                do_update_opacity(rig)
            except Exception as exc:
                fbp_warn("Could not finalize queued rig", exc)

        try:
            sync_layer_collection(context)
            sync_collection_colors_to_rigs(context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

        try:
            if context and getattr(context, "view_layer", None):
                context.view_layer.update()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

        if scene and current_frame is not None:
            try:
                scene.frame_set(current_frame, subframe=current_subframe)
            except Exception:
                try:
                    scene.frame_current = current_frame
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
    finally:
        _fbp_restore_fast_import_runtime(context)


# Fast Import is invoked directly inside the operator execute methods.
# Avoid monkey-patching operator methods at module load: it makes debugging harder
# and is less suitable for Blender Extensions review.


def unregister():
    """Restore Global Undo if the extension is disabled during Fast Import."""
    try:
        stored_state = fbp_runtime_get("fbp_fast_import_undo_state", -1)
        has_saved_state = int(-1 if stored_state is None else stored_state) >= 0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        has_saved_state = False
    if fbp_fast_import_depth() > 0 or has_saved_state:
        try:
            _fbp_restore_fast_import_runtime(getattr(bpy, "context", None))
        except Exception as exc:
            fbp_warn("Could not restore Fast Import runtime during unregister", exc)
    fbp_set_fast_import_depth(0)


# SECTION 03 - Auto Build Project helpers #

def fbp_child_entries(path):
    entries = []
    try:
        names = os.listdir(path)
    except Exception:
        return entries

    image_names = []
    for name in names:
        if is_hidden_import_name(name):
            continue
        full = os.path.join(path, name)
        if os.path.isdir(full):
            if fbp_folder_has_importable_content(full):
                entries.append(('DIR', name, full))
        elif is_supported_media_file(name) and (is_supported_video_file(name) or not is_technical_map_file(name)):
            image_names.append(name)

    for layer_name, files, is_sequence in fbp_group_direct_images_into_layers(image_names):
        if is_sequence:
            entries.append(('IMAGE_GROUP', layer_name, (path, files)))
        elif files:
            entries.append(('IMAGE', clean_layer_name_from_path(files[0]), os.path.join(path, files[0])))

    entries.sort(key=lambda e: natural_sort_key(e[1]))
    return entries


def fbp_folder_has_importable_content(path):
    try:
        for name in os.listdir(path):
            if is_hidden_import_name(name):
                continue
            full = os.path.join(path, name)
            if os.path.isdir(full) and fbp_folder_has_importable_content(full):
                return True
            if not is_hidden_import_name(name) and is_supported_media_file(name) and (is_supported_video_file(name) or not is_technical_map_file(name)):
                return True
    except Exception:
        return False
    return False


def fbp_folder_direct_images(path):
    try:
        return sorted(
            [name for name in os.listdir(path)
             if os.path.isfile(os.path.join(path, name))
             and not is_hidden_import_name(name)
             and is_supported_media_file(name)
             and (is_supported_video_file(name) or not is_technical_map_file(name))],
            key=natural_sort_key
        )
    except Exception:
        return []


def fbp_folder_direct_dirs(path):
    try:
        return sorted(
            [name for name in os.listdir(path)
             if os.path.isdir(os.path.join(path, name))
             and not is_hidden_import_name(name)
             and fbp_folder_has_importable_content(os.path.join(path, name))],
            key=natural_sort_key
        )
    except Exception:
        return []


def fbp_collect_mixed_folder_entries(base):
    """Collect top-level folder/image entries for the Pending List."""
    entries = []
    try:
        names = os.listdir(base)
    except Exception:
        return entries
    direct_images = []
    for name in names:
        if is_hidden_import_name(name):
            continue
        path = os.path.join(base, name)
        if os.path.isdir(path):
            files = fbp_folder_direct_images(path)
            if files:
                folder_label = clean_layer_name_from_path(name)
                for layer_name, grouped_files, is_sequence in fbp_group_direct_images_into_layers(files, folder_label):
                    entries.append((layer_name, path, grouped_files, 'FOLDER_SEQUENCE' if is_sequence else 'FOLDER_IMAGE'))
        elif is_supported_media_file(name) and (is_supported_video_file(name) or not is_technical_map_file(name)):
            direct_images.append(name)
    for layer_name, grouped_files, is_sequence in fbp_group_direct_images_into_layers(direct_images):
        entries.append((layer_name, base, grouped_files, 'IMAGE_SEQUENCE' if is_sequence else 'IMAGE'))
    entries.sort(key=lambda e: natural_sort_key(e[0]))
    return entries


def fbp_build_project_folder(
    context, folder_path, parent_collection, cursor_loc, depth_counter,
    color_seed=0, depth=0, color_state=None,
):
    """Build one filesystem folder and its children as collection hierarchy.

    Leaf folders containing exactly one image sequence or one static image are
    flattened into their parent collection. Their layer remains independently
    color-tagged, so removing the redundant collection never removes variation.
    """
    folder_name = clean_layer_name_from_path(folder_path)
    if color_state is None:
        color_state = {'next': max(0, int(color_seed or 0))}

    direct_images = fbp_folder_direct_images(folder_path)
    direct_dirs = fbp_folder_direct_dirs(folder_path)
    grouped_layers = fbp_group_direct_images_into_layers(direct_images, folder_name)
    has_children = bool(direct_dirs)
    flatten_single_layer = fbp_should_flatten_leaf_folder(grouped_layers, direct_dirs)

    color_index = int(color_state.get('next', 0))
    if flatten_single_layer:
        coll = parent_collection
        collection_color = 'NONE'
        layer_color = f"COLOR_{(color_index % 8) + 1:02d}"
        color_state['next'] = color_index + 1
        follows_collection = False
        base_variant = color_index
    else:
        if has_children:
            collection_color = 'NONE'
        else:
            collection_color = f"COLOR_{(color_index % 8) + 1:02d}"
            color_state['next'] = color_index + 1
        coll = get_or_create_child_collection(parent_collection, folder_name)
        set_collection_color_tag(coll, collection_color)
        follows_collection = not has_children
        layer_color = collection_color if follows_collection else 'COLOR_09'
        base_variant = 0

    generated = []
    local_variant = 0

    for layer_name, grouped_files, _is_sequence in grouped_layers:
        rig_loc = cursor_loc.copy()
        offset = context.scene.fbp_layer_offset * depth_counter[0]
        if fbp_scene_orientation_is_horizontal(context.scene):
            rig_loc.z -= offset
        else:
            rig_loc.y += offset
        rig = build_fbp_rig(
            context,
            layer_name,
            folder_path,
            grouped_files,
            rig_loc,
            color_tag=layer_color,
            target_collection=coll,
            color_variant_index=base_variant + local_variant,
            follow_collection_color=follows_collection,
        )
        rig.fbp_depth_order = depth_counter[0]
        depth_counter[0] += 1
        local_variant += 1
        generated.append(rig)

    for child_name in direct_dirs:
        full = os.path.join(folder_path, child_name)
        generated.extend(
            fbp_build_project_folder(
                context, full, coll, cursor_loc, depth_counter,
                color_seed=color_seed, depth=depth + 1, color_state=color_state,
            )
        )

    return generated

