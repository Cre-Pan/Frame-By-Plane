"""Folder scanning, sequence detection, Fast Import and scene-split helpers."""

import bpy
import os
import re

try:
    from . import profiling as fbp_profiling
except ImportError:
    import profiling as fbp_profiling

try:
    from .path_utils import (
        natural_sort_key,
        clean_layer_name_from_path,
        is_hidden_import_name,
        is_supported_video_file,
        is_supported_media_file,
        is_technical_map_file,
    )
except ImportError:
    from path_utils import (
        natural_sort_key,
        clean_layer_name_from_path,
        is_hidden_import_name,
        is_supported_video_file,
        is_supported_media_file,
        is_technical_map_file,
    )


def _core():
    try:
        from . import core
        return core
    except Exception:
        import core
        return core


def _core_attr(name, default=None):
    return getattr(_core(), name, default)


def _call_core(name, *args, **kwargs):
    func = _core_attr(name)
    if callable(func):
        return func(*args, **kwargs)
    return None


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
    if not prefix:
        prefix = str(fallback or "").strip(" ._-\t")
    if not prefix:
        prefix = "Sequence"
    parts = [p for p in re.split(r"[\s_.-]+", prefix) if p]
    while parts and parts[-1].lower() in _SEQUENCE_NOISE_WORDS:
        parts.pop()
    while parts and parts[0].lower() in _SEQUENCE_NOISE_WORDS:
        parts.pop(0)
    return " ".join(parts) if parts else prefix


def _sequence_group_key(prefix, ext):
    # Include extension so a rendered PNG sequence and EXR sequence with the same
    # prefix do not accidentally merge into one layer.
    return (str(prefix or "").casefold(), str(ext or "").lower())


def fbp_sequence_key_from_filename(name, folder_name=""):
    """Return (prefix, frame_index) when a filename looks like a sequence frame."""
    stem, ext = os.path.splitext(os.path.basename(str(name)))
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


# Compatibility name for existing call sites; also supports video.
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

    def direct_images(path):
        try:
            return sorted(
                [name for name in os.listdir(path)
                 if os.path.isfile(os.path.join(path, name))
                 and not is_hidden_import_name(name)
                 and is_supported_media_file(name)
                 and (is_supported_video_file(name) or not is_technical_map_file(name))],
                key=natural_sort_key)
        except Exception:
            return []

    def direct_dirs(path):
        try:
            return sorted(
                [name for name in os.listdir(path)
                 if os.path.isdir(os.path.join(path, name))
                 and not is_hidden_import_name(name)
                 and fbp_folder_has_images_recursive(os.path.join(path, name))],
                key=natural_sort_key)
        except Exception:
            return []

    def visit(path, collection_name=""):
        imgs = direct_images(path)
        dirs = direct_dirs(path)
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

_FBP_FAST_IMPORT_RUNTIME = {
    # Runtime-only data. Nothing here is stored as IDProperties, so undo/reload
    # never has to free transient Fast Import state from Blender datablocks.
    "view_shading": [],
    "profile": None,
    "depth": 0,
}


def fbp_fast_import_wm(context=None):
    # Fast Import depth is runtime-only.
    return getattr(context, "window_manager", None) if context else getattr(bpy.context, "window_manager", None)


def fbp_fast_import_depth(context=None):
    try:
        return int(_FBP_FAST_IMPORT_RUNTIME.get("depth", 0))
    except Exception:
        return 0


def fbp_set_fast_import_depth(value, context=None):
    try:
        _FBP_FAST_IMPORT_RUNTIME["depth"] = max(0, int(value))
    except Exception as exc:
        _call_core("fbp_warn", "Could not store Fast Import depth", exc)


def fbp_fast_import_is_active():
    return fbp_fast_import_depth() > 0


def fbp_fast_import_queued_names(context=None):
    value = str(_call_core("fbp_runtime_get", "fbp_fast_import_queued_rigs", "", context) or "")
    return [name for name in value.split("|") if name]


def fbp_set_fast_import_queued_names(names, context=None):
    unique = []
    seen = set()
    for name in names:
        if name and name not in seen:
            unique.append(name)
            seen.add(name)
    _call_core("fbp_runtime_set", "fbp_fast_import_queued_rigs", "|".join(unique), context)


def fbp_fast_import_queue_rig(rig):
    if not rig:
        return
    names = fbp_fast_import_queued_names()
    if rig.name not in names:
        names.append(rig.name)
        fbp_set_fast_import_queued_names(names)


def fbp_preserve_current_frame(context, func, *args, **kwargs):
    scene = context.scene if context else bpy.context.scene
    current_frame = None
    current_subframe = 0.0
    if scene:
        try:
            current_frame = int(scene.frame_current)
            current_subframe = float(getattr(scene, "frame_subframe", 0.0))
        except Exception:
            current_frame = None

    result = None
    error = None
    try:
        result = func(*args, **kwargs)
    except Exception as exc:
        error = exc
    finally:
        if scene and current_frame is not None:
            try:
                scene.frame_set(current_frame, subframe=current_subframe)
            except Exception:
                try:
                    scene.frame_current = current_frame
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
    if error:
        raise error
    return result


def fbp_current_profile():
    return _FBP_FAST_IMPORT_RUNTIME.get("profile")


def fbp_profiled_section(label):
    return fbp_profiling.section(fbp_current_profile(), label)


def fbp_capture_viewport_state():
    saved = []
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return saved
    try:
        for window in wm.windows:
            screen = window.screen
            if not screen:
                continue
            for area in screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                for space in area.spaces:
                    if getattr(space, "type", None) == 'VIEW_3D':
                        saved.append((space, getattr(space.shading, "type", 'SOLID')))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return saved


def fbp_set_viewports_wireframe(saved):
    """Temporarily use Wireframe during heavy import/build operations.

    Directly apply Wireframe during heavy operations.

    This function must never call itself.
    """
    for space, _old in saved:
        try:
            space.shading.type = 'WIREFRAME'
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass


def fbp_restore_viewport_state(saved):
    for space, old in saved:
        try:
            space.shading.type = old
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass


def fbp_begin_fast_import(context):
    depth = fbp_fast_import_depth(context) + 1
    fbp_set_fast_import_depth(depth, context)
    if depth != 1:
        return

    fbp_set_fast_import_queued_names([], context)
    _FBP_FAST_IMPORT_RUNTIME["profile"] = fbp_profiling.begin_profile("Fast Import")

    with fbp_profiled_section("Prepare fast import"):
        prefs_edit = getattr(getattr(bpy.context, "preferences", None), "edit", None)
        if prefs_edit:
            try:
                _call_core("fbp_runtime_set", "fbp_fast_import_undo_state", 1 if prefs_edit.use_global_undo else 0, context)
                prefs_edit.use_global_undo = False
            except Exception:
                _call_core("fbp_runtime_set", "fbp_fast_import_undo_state", -1, context)

        saved = fbp_capture_viewport_state()
        _FBP_FAST_IMPORT_RUNTIME["view_shading"] = saved
        fbp_set_viewports_wireframe(saved)

    try:
        bpy.context.window_manager.progress_begin(0, 100)
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

    scene = context.scene if context else bpy.context.scene
    current_frame = None
    current_subframe = 0.0
    if scene:
        try:
            current_frame = int(scene.frame_current)
            current_subframe = float(getattr(scene, "frame_subframe", 0.0))
        except Exception:
            current_frame = None

    with fbp_profiled_section("Finalize generated rigs"):
        seen = set()
        for rig_name in fbp_fast_import_queued_names(context):
            if rig_name in seen:
                continue
            seen.add(rig_name)
            rig = bpy.data.objects.get(rig_name)
            if not rig:
                continue
            try:
                _call_core("do_update_animation", rig)
                _call_core("do_update_emission", rig)
                _call_core("do_update_opacity", rig)
            except Exception as exc:
                _call_core("fbp_warn", "Could not finalize queued rig", exc)

    with fbp_profiled_section("Sync UI and collections"):
        try:
            _call_core("sync_layer_collection", context)
            _call_core("sync_collection_colors_to_rigs", context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

    with fbp_profiled_section("Final view layer update"):
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

    fbp_restore_viewport_state(_FBP_FAST_IMPORT_RUNTIME["view_shading"])
    _FBP_FAST_IMPORT_RUNTIME["view_shading"] = []

    prefs_edit = getattr(getattr(bpy.context, "preferences", None), "edit", None)
    undo_state = int(_call_core("fbp_runtime_get", "fbp_fast_import_undo_state", -1, context) or -1)
    if prefs_edit and undo_state >= 0:
        try:
            prefs_edit.use_global_undo = bool(undo_state)
        except Exception as exc:
            _call_core("fbp_warn", "Could not restore global undo", exc)
    _call_core("fbp_runtime_set", "fbp_fast_import_undo_state", -1, context)

    profile = _FBP_FAST_IMPORT_RUNTIME.get("profile")
    if profile:
        try:
            fbp_profiling.finish_profile(profile)
            fbp_profiling.write_profile_text(bpy, profile)
            print(fbp_profiling.format_profile(profile))
        except Exception as exc:
            print(f"[FBP] Profile report error: {exc}")
    _FBP_FAST_IMPORT_RUNTIME["profile"] = None
    fbp_set_fast_import_queued_names([], context)

    try:
        bpy.context.window_manager.progress_update(100)
        bpy.context.window_manager.progress_end()
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def fbp_folder_has_images_recursive(path):
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if not is_hidden_import_name(d)]
            for filename in filenames:
                if not is_hidden_import_name(filename) and is_supported_media_file(filename) and (is_supported_video_file(filename) or not is_technical_map_file(filename)):
                    return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return False


def fbp_unique_scene_name(base_name):
    clean = clean_layer_name_from_path(base_name) or "Scene"
    clean = clean[:55]
    if clean not in bpy.data.scenes:
        return clean
    i = 2
    while f"{clean}.{i:03d}" in bpy.data.scenes:
        i += 1
    return f"{clean}.{i:03d}"


def fbp_apply_scene_defaults(scene):
    try:
        scene.fbp_pre_orientation = 'VERT'
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        scene.fbp_auto_scale = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        scene.fbp_cam_ratio = '4_3'
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        scene.render.resolution_x = 1920
        scene.render.resolution_y = 1440
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        scene.fbp_gen_camera = True
        scene.fbp_cam_pivot = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def fbp_auto_build_main_folders_as_scenes(operator, context):
    """Build each valid top-level project folder in its own Blender scene.

    Scene switching alone is not enough while an operator is running: object
    operators also need a context whose Scene and ViewLayer belong together.
    """
    original_scene = context.scene
    window = getattr(context, 'window', None)
    if window is None:
        operator.report({'ERROR'}, "Main Folders as Separate Scenes requires a Blender window")
        return {'CANCELLED'}

    original_window_scene = getattr(window, 'scene', original_scene)
    original_view_layer = getattr(window, 'view_layer', None)

    base = bpy.path.abspath(getattr(original_scene, "fbp_project_path", "") or "")
    if not base or not os.path.isdir(base):
        operator.report({'ERROR'}, "Set a valid Project Folder first")
        return {'CANCELLED'}

    top_folders = []
    for name in sorted(os.listdir(base), key=natural_sort_key):
        if is_hidden_import_name(name):
            continue
        full = os.path.join(base, name)
        if os.path.isdir(full) and fbp_folder_has_images_recursive(full):
            top_folders.append((name, full))

    if not top_folders:
        operator.report({'WARNING'}, "No valid main folders found")
        return {'CANCELLED'}

    made = 0
    errors = []
    try:
        for name, full in top_folders:
            scene = bpy.data.scenes.new(fbp_unique_scene_name(name))

            try:
                scene.render.fps = original_scene.render.fps
                scene.frame_start = original_scene.frame_start
                scene.frame_end = original_scene.frame_end
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass

            fbp_apply_scene_defaults(scene)

            try:
                scene.fbp_project_path = full
                scene.fbp_parent_import_path = full
                scene.fbp_import_main_folders_as_scenes = False
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass

            try:
                target_view_layer = scene.view_layers[0]
                window.scene = scene
                try:
                    window.view_layer = target_view_layer
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError):
                    pass

                # A temporary override refreshes context.scene, view_layer,
                # active_object and bpy.ops for the newly-created scene.
                with context.temp_override(
                    window=window,
                    scene=scene,
                    view_layer=target_view_layer,
                ):
                    result = operator._execute_impl(context)
                if 'CANCELLED' in result:
                    errors.append(f"{name}: build cancelled")
                else:
                    made += 1
            except Exception as exc:
                errors.append(f"{name}: {exc}")
    finally:
        try:
            window.scene = original_window_scene
            if original_view_layer and original_view_layer.name in original_window_scene.view_layers:
                window.view_layer = original_window_scene.view_layers[original_view_layer.name]
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

    if errors:
        print("Frame by Plane scene split issues:")
        for err in errors:
            print(" -", err)
        operator.report({'WARNING'}, f"Imported {made} scene(s), with {len(errors)} issue(s). Check console.")
    else:
        operator.report({'INFO'}, f"Imported {made} scene(s) from main folders")
    return {'FINISHED'} if made else {'CANCELLED'}


# Fast Import is invoked directly inside the operator execute methods.
# Avoid monkey-patching operator methods at module load: it makes debugging harder
# and is less suitable for Blender Extensions review.


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

    core = _core()
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
        coll = core.get_or_create_child_collection(parent_collection, folder_name)
        core.set_collection_color_tag(coll, collection_color)
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
        rig = core.build_fbp_rig(
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

