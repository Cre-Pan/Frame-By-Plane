import bpy
import os


try:
    from .constants import (
        STRIP_COLORS_DICT,
        COLOR_ENUM_ITEMS,
        preview_collections,
        FBP_SUPPORTED_IMAGE_EXT,
        FBP_SUPPORTED_VIDEO_EXT,
        FBP_SUPPORTED_MEDIA_EXT,
        FBP_TECHNICAL_MAP_SUFFIXES,
        FBP_PROJECT_COLLECTION_PREFIX,
    )
    from .path_utils import (
        natural_sort_key,
        is_supported_video_file,
        is_supported_media_file,
        is_hidden_import_name,
        is_technical_map_file,
        clean_layer_name_from_path,
    )
except ImportError:
    from constants import (
        STRIP_COLORS_DICT,
        COLOR_ENUM_ITEMS,
        preview_collections,
        FBP_SUPPORTED_IMAGE_EXT,
        FBP_SUPPORTED_VIDEO_EXT,
        FBP_SUPPORTED_MEDIA_EXT,
        FBP_TECHNICAL_MAP_SUFFIXES,
        FBP_PROJECT_COLLECTION_PREFIX,
    )
    from path_utils import (
        natural_sort_key,
        is_supported_video_file,
        is_supported_media_file,
        is_hidden_import_name,
        is_technical_map_file,
        clean_layer_name_from_path,
    )


# MATERIALS / NODES IMPORT #
############################
# Material and shader helpers live in materials.py. These imports keep the shared core API stable.
try:
    from .materials import (
        safe_get_socket,
        iter_material_image_nodes,
        fbp_images_from_material,
        fbp_remove_unused_images,
        fbp_remove_unused_materials_and_images,
        fbp_copy_material_slots_unique,
        rebuild_fbp_image_material,
        do_update_emission,
        set_fbp_material_transparency,
        is_fbp_empty_material,
        do_update_opacity,
        configure_fbp_material_surface,
        create_fbp_color_material,
        create_fbp_gradient_material,
        fbp_rebuild_color_plane_material,
        fbp_holdout_material,
        fbp_alpha_holdout_material_from_source,
        fbp_material_is_holdout,
        fbp_plane_uses_holdout_materials,
        fbp_is_native_holdout_plane,
        fbp_rebuild_original_materials_for_holdout_restore,
        fbp_apply_holdout_materials_to_rig,
        store_original_materials_for_holdout,
        restore_original_materials_from_holdout,
        fbp_find_node_by_type,
        fbp_relink_node_input,
        update_fbp_procedural_material_opacity,
        fbp_rebuild_procedural_material_for_emission,
        rig_holdout_is_active,
        get_fbp_gradient_material_from_rig,
        find_fbp_gradient_ramp_node,
        get_fbp_gradient_mapping_node,
        get_fbp_gradient_center_node,
        update_fbp_gradient_viewport_color,
        apply_fbp_gradient_mapping_to_material,
        get_fbp_gradient_preview_material,
        get_or_create_fbp_gradient_preview_material,
        fbp_update_scene_gradient_preview_material,
        fbp_capture_color_ramp_data,
        fbp_restore_color_ramp_data,
        fbp_apply_gradient_kind_to_ramp_node,
        copy_color_ramp,
        copy_scene_preview_ramp_to_rig,
        fbp_get_active_frame_material,
        fbp_material_color_value,
        fbp_duplicate_procedural_material_for_frame,
        fbp_create_procedural_frame_material_for_rig,
    )
except ImportError:
    from materials import (
        safe_get_socket, iter_material_image_nodes, fbp_images_from_material,
        fbp_remove_unused_images, fbp_remove_unused_materials_and_images,
        fbp_copy_material_slots_unique, rebuild_fbp_image_material, do_update_emission,
        set_fbp_material_transparency, is_fbp_empty_material,
        do_update_opacity, configure_fbp_material_surface,
        create_fbp_color_material, create_fbp_gradient_material,
        fbp_rebuild_color_plane_material, fbp_holdout_material,
        fbp_alpha_holdout_material_from_source, fbp_material_is_holdout,
        fbp_plane_uses_holdout_materials, fbp_is_native_holdout_plane,
        fbp_rebuild_original_materials_for_holdout_restore,
        fbp_apply_holdout_materials_to_rig, store_original_materials_for_holdout,
        restore_original_materials_from_holdout, fbp_find_node_by_type,
        fbp_relink_node_input, update_fbp_procedural_material_opacity,
        fbp_rebuild_procedural_material_for_emission, rig_holdout_is_active,
        get_fbp_gradient_material_from_rig, find_fbp_gradient_ramp_node,
        get_fbp_gradient_mapping_node, get_fbp_gradient_center_node,
        update_fbp_gradient_viewport_color,
        apply_fbp_gradient_mapping_to_material, get_fbp_gradient_preview_material,
        get_or_create_fbp_gradient_preview_material, fbp_update_scene_gradient_preview_material,
        fbp_capture_color_ramp_data, fbp_restore_color_ramp_data,
        fbp_apply_gradient_kind_to_ramp_node, copy_color_ramp, copy_scene_preview_ramp_to_rig,
        fbp_get_active_frame_material, fbp_material_color_value,
        fbp_duplicate_procedural_material_for_frame,
        fbp_create_procedural_frame_material_for_rig,
    )


# BUILDER / SCENE GEOMETRY IMPORT #
##################################
# Rig creation, mesh construction and fit-to-camera helpers live in builder.py.
try:
    from .builder import (
        camera_ratio_scale,
        fbp_link_object,
        fbp_create_rect_mesh,
        fbp_update_rig_frame_mesh_to_bounds,
        fbp_create_mesh_object,
        fbp_scene_orientation_is_horizontal,
        fbp_apply_creation_orientation,
        build_fbp_color_rig,
        set_plane_mesh_extension,
        fbp_rig_base_image_size,
        apply_fit_to_camera,
        build_fbp_rig,
    )
except ImportError:
    from builder import (
        camera_ratio_scale, fbp_link_object, fbp_create_rect_mesh,
        fbp_update_rig_frame_mesh_to_bounds, fbp_create_mesh_object,
        fbp_scene_orientation_is_horizontal, fbp_apply_creation_orientation,
        build_fbp_color_rig, set_plane_mesh_extension, fbp_rig_base_image_size,
        build_fbp_rig,
    )

# ICON REGISTRY IMPORT FALLBACK #
#################################
# Keep icon access safe even when testing core.py against an older constants.py.
# In the full add-on package, these functions are provided by constants.py.
try:
    from . import constants as _fbp_constants
except ImportError:
    try:
        import constants as _fbp_constants
    except ImportError:
        _fbp_constants = None

FBP_ICONS = getattr(_fbp_constants, "FBP_ICONS", {}) if _fbp_constants else {}


def fbp_icon(name, fallback="BLANK1"):
    """Return a Blender icon string from the centralized registry.

    Edit constants.py > FBP_ICONS to change icons globally. This local fallback
    prevents NameError when only core.py is replaced during live testing.
    """
    icon_func = getattr(_fbp_constants, "fbp_icon", None) if _fbp_constants else None
    if callable(icon_func):
        try:
            return icon_func(name, fallback)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    return FBP_ICONS.get(name, FBP_ICONS.get(fallback, name if name else fallback))


def fbp_strip_icon(color_tag, fallback="STRIP_COLOR_09"):
    """Return the strip icon for a Frame by Plane color tag."""
    strip_func = getattr(_fbp_constants, "fbp_strip_icon", None) if _fbp_constants else None
    if callable(strip_func):
        try:
            return strip_func(color_tag, fallback)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    tag = str(color_tag or "COLOR_09")
    return f"STRIP_{tag}" if tag.startswith("COLOR_") else fallback


def fbp_collection_color_icon(color_tag, fallback="OUTLINER_COLLECTION"):
    """Return the colored collection icon for a Blender collection color tag."""
    collection_func = getattr(_fbp_constants, "fbp_collection_color_icon", None) if _fbp_constants else None
    if callable(collection_func):
        try:
            return collection_func(color_tag, fallback)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    tag = str(color_tag or "")
    if tag.startswith("COLOR_"):
        suffix = tag.split("_")[-1]
        if suffix in {"01", "02", "03", "04", "05", "06", "07", "08"}:
            return f"COLLECTION_COLOR_{suffix}"
    return fallback

try:
    from .runtime import (
        fbp_log, fbp_warn, fbp_runtime_get, fbp_runtime_set,
        fbp_obj_runtime_key, fbp_is_silent_property_update,
        fbp_set_rna_property_silent,
    )
except ImportError:
    from runtime import (
        fbp_log, fbp_warn, fbp_runtime_get, fbp_runtime_set,
        fbp_obj_runtime_key, fbp_is_silent_property_update,
        fbp_set_rna_property_silent,
    )

_FBP_SYNCING_FRAME_MATERIAL_POINTERS = set()
_FBP_SUPPRESS_IMAGE_DURATION_CB = False


# ICON REGISTRY NOTE #
######################
# All Frame by Plane UI icons are centralized in constants.py under # ICON REGISTRY #.
# Use fbp_icon("ICON_KEY") or fbp_strip_icon(color_tag) instead of hard-coded icon strings.


# ── HELPERS ──────────────────────────────────────────────────────────────────

try:
    from .layers import *
except ImportError:
    from layers import *

# ── PROPERTY GROUPS MOVED TO properties.py ─────────────────────────────────────

# ── LAYER / SYNC HELPERS ──────────────────────────────────────────────────────

# ── SCENE SYNC IMPORTS ───────────────────────────────────────────────────────
# Native delete/duplicate repair, orphan cleanup and layer syncing live in scene_sync.py.
# Imported here to keep the shared core API stable.
try:
    from .scene_sync import (
        sync_layer_collection,
        fbp_linked_planes_for_rig,
        fbp_remove_plane_datablock,
        fbp_snapshot_layer_plane_links,
        fbp_cleanup_planes_for_deleted_rigs,
        delete_fbp_rigs,
        fbp_repair_default_duplicate_rig,
        fbp_repair_default_duplicates,
        cleanup_orphan_fbp_planes,
        fbp_initial_sync_timer,
        fbp_known_links_have_deleted_rig,
        fbp_depsgraph_updated_fbp_rigs,
        fbp_scene_has_broken_native_duplicate,
        fbp_run_native_ops_sync,
        fbp_depsgraph_native_ops_handler,
        cleanup_orphan_fbp_planes_timer,
    )
except ImportError:
    from scene_sync import (
        sync_layer_collection, fbp_linked_planes_for_rig, fbp_remove_plane_datablock,
        fbp_snapshot_layer_plane_links, fbp_cleanup_planes_for_deleted_rigs,
        delete_fbp_rigs, fbp_repair_default_duplicate_rig, fbp_repair_default_duplicates,
        cleanup_orphan_fbp_planes, fbp_initial_sync_timer, fbp_known_links_have_deleted_rig,
        fbp_depsgraph_updated_fbp_rigs, fbp_scene_has_broken_native_duplicate,
        fbp_run_native_ops_sync, fbp_depsgraph_native_ops_handler, cleanup_orphan_fbp_planes_timer,
    )


def sync_fbp_property(self, context, prop_name):
    if getattr(context, "active_object", None) != self:
        return
    val = getattr(self, prop_name)
    for obj in context.selected_objects:
        if obj != self and getattr(obj, "is_fbp_control", False):
            if getattr(obj, prop_name) != val:
                setattr(obj, prop_name, val)


# ── CORE OPERATIONS ───────────────────────────────────────────────────────────


def fbp_sequence_backend_for_rig(rig):
    """Return the concrete backend used by this rig.

    Image layers are native-only. Color / Gradient / Holdout layers keep their
    procedural material workflow.
    """
    if not rig:
        return 'NATIVE_IMAGE_SEQUENCE'
    try:
        if bool(getattr(rig, 'fbp_is_color_plane', False)):
            return 'PROCEDURAL_COLOR'
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return 'NATIVE_IMAGE_SEQUENCE'


def fbp_rig_uses_procedural_color(rig):
    return fbp_sequence_backend_for_rig(rig) == 'PROCEDURAL_COLOR'


def fbp_sequence_index_at_frame(rig, frame=None):
    """Evaluate the visible row index for per-row timing.

    Used by procedural Color / Gradient / Holdout animation. Image sequences use
    Blender ImageUser timing instead of swapping material slots.
    """
    if frame is None:
        frame = getattr(bpy.context.scene, 'frame_current', 1)
    try:
        start = int(getattr(rig, 'fbp_start_frame', 1))
        rel = int(frame) - start
    except Exception:
        rel = 0
    if rel < 0:
        return -1

    items = list(getattr(rig, 'fbp_images', []))
    if not items:
        return -1
    durations = [max(1, int(getattr(item, 'duration', getattr(rig, 'fbp_global_duration', 1)) or 1)) for item in items]
    count = len(durations)
    mode = str(getattr(rig, 'fbp_loop_mode', 'NONE') or 'NONE')

    if mode == 'PINGPONG' and count > 1:
        order = list(range(count)) + list(range(count - 2, 0, -1))
    else:
        order = list(range(count))
    ordered_durations = [durations[i] for i in order]
    total = max(1, sum(ordered_durations))

    if mode in {'REPEAT', 'PINGPONG'}:
        local = rel % total
    else:
        local = min(rel, total - 1)

    acc = 0
    for src_index, dur in zip(order, ordered_durations):
        acc += dur
        if local < acc:
            return max(0, min(count - 1, int(src_index)))
    return count - 1


def fbp_apply_procedural_color_frame(rig, frame=None):
    """Apply legacy procedural Color/Gradient frame material safely.

    A color plane without frame rows is a static procedural plane and must stay
    visible with material slot 0. A color/gradient/holdout plane with rows uses
    per-frame procedural material slots. Image layers stay native-only.
    """
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return False
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane or not getattr(plane, 'data', None):
        return False
    mesh = plane.data

    try:
        if not mesh.uv_layers:
            mesh.uv_layers.new(name='UVMap')
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    try:
        if len(mesh.materials) == 0 or mesh.materials[0] is None:
            fbp_rebuild_color_plane_material(rig)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    try:
        if len(mesh.materials) == 0:
            return False
    except Exception:
        return False

    # Static Color / Gradient / Holdout plane: keep the single procedural material.
    if len(getattr(rig, 'fbp_images', [])) == 0:
        try:
            for poly in mesh.polygons:
                poly.material_index = 0
            mesh.update()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        visible = bool(getattr(rig, 'fbp_is_visible', True))
        try:
            if not fbp_is_rendering_now():
                plane.hide_viewport = not visible
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        try:
            plane.hide_render = not visible
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        return True

    idx = fbp_sequence_index_at_frame(rig, frame)
    visible = bool(getattr(rig, 'fbp_is_visible', True)) and idx >= 0
    try:
        if not fbp_is_rendering_now():
            plane.hide_viewport = not visible
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        plane.hide_render = not visible
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    if idx < 0:
        return True

    try:
        idx = max(0, min(int(idx), len(mesh.materials) - 1))
        changed = False
        for poly in mesh.polygons:
            if poly.material_index != idx:
                poly.material_index = idx
                changed = True
        if changed:
            mesh.update()
        return True
    except Exception as exc:
        fbp_warn('Procedural Color Plane frame update skipped', exc)
        return False


def fbp_tag_view3d_ui_redraw():
    """Refresh Frame by Plane UI indicators that depend on the current frame."""
    try:
        wm = bpy.context.window_manager
        for window in getattr(wm, 'windows', []) or []:
            screen = getattr(window, 'screen', None)
            for area in getattr(screen, 'areas', []) or []:
                if getattr(area, 'type', '') in {'VIEW_3D', 'TIMELINE', 'DOPESHEET_EDITOR'}:
                    area.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def fbp_update_sequence_scene(scene=None, frame=None):
    """Refresh procedural Color / Gradient / Holdout animated rows.

    Native image sequences do not need a frame-change material-slot update.
    """
    scene = scene or getattr(bpy.context, 'scene', None)
    if not scene:
        return 0
    if frame is None:
        frame = getattr(scene, 'frame_current', 1)
    updated = 0
    for obj in list(getattr(scene, 'objects', [])):
        try:
            if not getattr(obj, 'is_fbp_control', False):
                continue
            if fbp_rig_uses_procedural_color(obj) and len(getattr(obj, 'fbp_images', [])) > 0:
                if fbp_apply_procedural_color_frame(obj, frame):
                    updated += 1
        except ReferenceError:
            continue
        except Exception as exc:
            fbp_warn("Sequence scene update skipped", exc)
    return updated


def fbp_rebuild_sequence_backend_from_rig(rig):
    if fbp_rig_uses_procedural_color(rig):
        return fbp_apply_procedural_color_frame(rig, getattr(bpy.context.scene, 'frame_current', 1))
    try:
        from . import native_backend
        return bool(native_backend.rebuild_native_sequence_from_rig(rig))
    except Exception as exc:
        fbp_warn("Could not rebuild Native Image Sequence", exc)
        return False


def fbp_refresh_sequence_backend_from_rig(rig):
    if fbp_rig_uses_procedural_color(rig):
        return fbp_apply_procedural_color_frame(rig, getattr(bpy.context.scene, 'frame_current', 1))
    try:
        from . import native_backend
        if native_backend.fbp_refresh_native_sequence_from_rig(rig):
            return True
        return bool(native_backend.rebuild_native_sequence_from_rig(rig))
    except Exception as exc:
        fbp_warn("Native sequence refresh skipped", exc)
        return False


def fbp_replace_sequence_backend(rig, directory, files):
    if not rig:
        return False
    files = [str(f) for f in (files or []) if f]
    if not files:
        return False
    try:
        from . import native_backend
        return bool(native_backend.replace_native_sequence(rig, directory, files))
    except Exception as exc:
        fbp_warn("Could not replace Native Image Sequence", exc)
        return False


def fbp_native_sequence_files_from_rig(rig):
    """Return (directory, filenames) for a native image rig, based on its frame rows."""
    if not rig or getattr(rig, 'fbp_is_color_plane', False):
        return "", []
    paths = []
    for item in getattr(rig, 'fbp_images', []):
        try:
            if getattr(item, 'is_empty', False):
                continue
            path = getattr(item, 'filepath', '') or ''
            if path:
                paths.append(bpy.path.abspath(path))
        except Exception:
            continue
    if not paths:
        return "", []
    directories = {os.path.normcase(os.path.abspath(os.path.dirname(path))) for path in paths}
    if len(directories) != 1:
        return "", []
    directory = os.path.dirname(paths[0])
    return directory, [os.path.basename(path) for path in paths]


def fbp_rig_native_sequence_needs_rename(rig):
    """True if the selected rig uses filenames that may fail as a native Image Sequence."""
    directory, files = fbp_native_sequence_files_from_rig(rig)
    if not directory or len(files) <= 1:
        return False
    try:
        from . import native_backend
        return bool(native_backend.fbp_native_sequence_needs_rename(directory, files))
    except Exception as exc:
        fbp_warn("Could not check native sequence filenames", exc)
        return False


def do_update_animation(rig):
    """Refresh whichever sequence backend this rig uses."""
    if not rig or not getattr(rig, "is_fbp_control", False):
        return False
    return bool(fbp_refresh_sequence_backend_from_rig(rig))


def do_update_track(rig, context):
    cam = context.scene.camera
    if rig.fbp_track_cam and cam:
        cons = rig.constraints.get("FBP_Track")
        if not cons:
            cons = rig.constraints.new(type='DAMPED_TRACK')
            cons.name = "FBP_Track"
        cons.target = cam
        cons.track_axis = 'TRACK_Z'
    else:
        cons = rig.constraints.get("FBP_Track")
        if cons:
            rig.constraints.remove(cons)


# ── CAMERA DEPTH GETTER/SETTER ────────────────────────────────────────────────

def fbp_edit_targets(context, source_rig, *, same_type=False):
    """Return active + selected FBP rigs for live multi-edit callbacks."""
    if not source_rig or not is_fbp_layer_object(source_rig):
        return []
    targets = []
    seen = set()

    def add(rig):
        if not rig or not is_fbp_layer_object(rig):
            return
        if same_type and bool(getattr(rig, 'fbp_is_color_plane', False)) != bool(getattr(source_rig, 'fbp_is_color_plane', False)):
            return
        key = fbp_obj_runtime_key(rig) or getattr(rig, 'name', '')
        if key in seen:
            return
        seen.add(key)
        targets.append(rig)

    add(source_rig)
    try:
        if context:
            active_rig = fbp_resolve_rig_from_any_object(getattr(context, 'active_object', None), context)
            active_key = fbp_obj_runtime_key(active_rig) or getattr(active_rig, 'name', '')
            source_key = fbp_obj_runtime_key(source_rig) or getattr(source_rig, 'name', '')
            if active_key == source_key:
                for obj in getattr(context, 'selected_objects', []) or []:
                    add(fbp_resolve_rig_from_any_object(obj, context))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return targets or [source_rig]


def fbp_copy_registered_props_silent(target, source, prop_names):
    for prop_name in prop_names:
        try:
            fbp_set_rna_property_silent(target, prop_name, getattr(source, prop_name))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass


def fbp_refresh_active_procedural_preview(rig):
    """Refresh per-frame procedural metadata after a Color/Gradient/Holdout edit."""
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return False
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane or not getattr(plane, 'data', None) or not getattr(plane.data, 'materials', None):
        return False
    try:
        idx = int(getattr(rig, 'fbp_images_index', 0)) if len(getattr(rig, 'fbp_images', [])) else 0
        idx = max(0, min(idx, len(plane.data.materials) - 1))
    except Exception:
        idx = 0
    try:
        mat = plane.data.materials[idx]
    except Exception:
        mat = None
    if not mat:
        return False
    kind = fbp_procedural_kind_from_material(mat, getattr(rig, 'fbp_color_plane_mode', 'SOLID'))
    try:
        fbp_set_procedural_metadata(mat, kind)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        if len(getattr(rig, 'fbp_images', [])) and 0 <= idx < len(rig.fbp_images):
            fbp_cache_procedural_preview_on_item(rig.fbp_images[idx], mat, kind)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        if kind == 'GRADIENT':
            update_fbp_gradient_viewport_color(rig, mat)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return True




def fbp_find_rig_for_procedural_frame_item(item, context=None):
    """Return (rig, index) for a procedural frame UIList item."""
    if not item:
        return None, -1
    try:
        target_ptr = item.as_pointer()
    except Exception:
        return None, -1
    scenes = []
    if context and getattr(context, 'scene', None):
        scenes.append(context.scene)
    try:
        scenes.extend(scene for scene in bpy.data.scenes if scene not in scenes)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    seen_objects = set()
    for scene in scenes:
        try:
            objects = list(scene.objects)
        except Exception:
            objects = []
        for obj in objects:
            try:
                if obj.name in seen_objects:
                    continue
                seen_objects.add(obj.name)
                if not getattr(obj, 'is_fbp_control', False) or not getattr(obj, 'fbp_is_color_plane', False):
                    continue
                for index, row in enumerate(getattr(obj, 'fbp_images', [])):
                    if row.as_pointer() == target_ptr:
                        return obj, index
            except ReferenceError:
                continue
            except Exception:
                continue
    return None, -1


def fbp_set_solid_material_color(mat, color):
    """Update a procedural solid material in-place from a UIList color edit."""
    if not mat:
        return False
    color = tuple(float(v) for v in color[:4])
    try:
        mat.diffuse_color = color
        mat['fbp_color_value'] = color
        mat['fbp_procedural_kind'] = 'SOLID'
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        if getattr(mat, 'use_nodes', False) and getattr(mat, 'node_tree', None):
            for node in mat.node_tree.nodes:
                if getattr(node, 'type', None) == 'EMISSION':
                    sock = safe_get_socket(node, ['color']) or node.inputs[0]
                    sock.default_value = color
                elif getattr(node, 'type', None) == 'BSDF_PRINCIPLED':
                    base = safe_get_socket(node, ['base', 'color']) or node.inputs[0]
                    base.default_value = color
                    alpha = safe_get_socket(node, ['alpha'])
                    if alpha:
                        alpha.default_value = color[3]
                elif getattr(node, 'type', None) == 'MIX_SHADER':
                    try:
                        node.inputs[0].default_value = color[3]
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                        pass
        configure_fbp_material_surface(mat, color[3], has_alpha=color[3] < 0.999)
    except Exception as exc:
        fbp_warn('Could not update procedural color material from UIList', exc)
    return True


def update_frame_preview_color_cb(self, context):
    """Write UIList color edits back to the owning procedural frame material."""
    try:
        ptr = self.as_pointer()
    except Exception:
        ptr = None
    if ptr is not None and ptr in _FBP_SYNCING_PROCEDURAL_PREVIEW_ITEMS:
        return
    try:
        rig, index = fbp_find_rig_for_procedural_frame_item(self, context)
        if not rig or index < 0:
            return
        plane = getattr(rig, 'fbp_plane_target', None)
        if not plane or not getattr(plane, 'data', None) or index >= len(plane.data.materials):
            return
        mat = plane.data.materials[index]
        if not mat:
            return
        kind = fbp_procedural_kind_for_item(rig, index, getattr(self, 'procedural_kind', 'SOLID'))
        if kind == 'GRADIENT':
            color_a = tuple(getattr(self, 'preview_color_a', (1.0, 1.0, 1.0, 1.0)))
            color_b = tuple(getattr(self, 'preview_color_b', (1.0, 1.0, 1.0, 1.0)))
            ramp = find_fbp_gradient_ramp_node(mat)
            elems = list(getattr(getattr(ramp, 'color_ramp', None), 'elements', [])) if ramp else []
            if elems:
                elems[0].color = color_a
                elems[-1].color = color_b
            try:
                mat.diffuse_color = color_b
                mat['fbp_procedural_kind'] = 'GRADIENT'
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            update_fbp_gradient_viewport_color(rig, mat)
            if int(getattr(rig, 'fbp_images_index', -1)) == index:
                fbp_set_rna_property_silent(rig, 'fbp_gradient_color_a', color_a)
                fbp_set_rna_property_silent(rig, 'fbp_gradient_color_b', color_b)
        elif kind == 'SOLID':
            color = tuple(getattr(self, 'preview_color_a', (1.0, 1.0, 1.0, 1.0)))
            fbp_set_solid_material_color(mat, color)
            if int(getattr(rig, 'fbp_images_index', -1)) == index:
                fbp_set_rna_property_silent(rig, 'fbp_color_plane_color', color)
        if int(getattr(rig, 'fbp_images_index', -1)) == index:
            fbp_apply_procedural_color_frame(rig, getattr(context.scene, 'frame_current', None) if context else None)
    except ReferenceError:
        return
    except Exception as exc:
        fbp_warn('Could not apply UIList color edit', exc)


# ── UPDATE CALLBACKS ──────────────────────────────────────────────────────────

def update_object_padding_cb(self, context):
    # Live-update Crop / Extend on the active rig, and copy to selected rigs.
    if not is_fbp_layer_object(self):
        return
    props = (
        'fbp_extend_left', 'fbp_extend_right', 'fbp_extend_bottom', 'fbp_extend_top',
        'fbp_extend_mode', 'fbp_crop_left', 'fbp_crop_right', 'fbp_crop_bottom', 'fbp_crop_top',
    )
    try:
        for rig in fbp_edit_targets(context, self):
            if rig != self:
                fbp_copy_registered_props_silent(rig, self, props)
            set_plane_mesh_extension(
                rig,
                getattr(rig, 'fbp_extend_left', 0.0), getattr(rig, 'fbp_extend_right', 0.0),
                getattr(rig, 'fbp_extend_bottom', 0.0), getattr(rig, 'fbp_extend_top', 0.0),
                getattr(rig, 'fbp_extend_mode', 'EDGE'),
                getattr(rig, 'fbp_crop_left', 0.0), getattr(rig, 'fbp_crop_right', 0.0),
                getattr(rig, 'fbp_crop_bottom', 0.0), getattr(rig, 'fbp_crop_top', 0.0),
            )
            if getattr(rig, 'fbp_is_color_plane', False):
                fbp_apply_procedural_color_frame(rig, getattr(context.scene, 'frame_current', None) if context else None)
            else:
                fbp_refresh_sequence_backend_from_rig(rig)
    except Exception as exc:
        fbp_warn("Plane Crop / Extend update skipped", exc)


def update_extend_plane_cb(self, context):
    # Legacy scene-level callback. New Crop/Extend values are stored per rig.
    rig = getattr(context, 'active_object', None) if context else None
    if rig and is_fbp_layer_object(rig):
        update_object_padding_cb(rig, context)


def update_loop_mode_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_edit_targets(context, self)
    value = str(getattr(self, "fbp_loop_mode", 'NONE'))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_loop_mode", value)
    for rig in targets:
        fbp_refresh_sequence_backend_from_rig(rig)
        do_update_animation(rig)


def update_start_frame_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_edit_targets(context, self)
    value = int(getattr(self, "fbp_start_frame", 1))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_start_frame", value)
    for rig in targets:
        fbp_refresh_sequence_backend_from_rig(rig)
        do_update_animation(rig)

def update_emission_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    sync_fbp_property(self, context, "fbp_use_emission")
    do_update_emission(self)

def update_opacity_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    sync_fbp_property(self, context, "fbp_opacity")
    do_update_opacity(self)

def update_track_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    sync_fbp_property(self, context, "fbp_track_cam")
    do_update_track(self, context)

def update_global_duration_cb(self, context):
    if fbp_is_silent_property_update(self):
        return

    global _FBP_SUPPRESS_IMAGE_DURATION_CB
    target_value = max(1, int(getattr(self, "fbp_global_duration", 1)))
    targets = fbp_edit_targets(context, self)
    multi_rig = len(targets) > 1
    changed_rigs = []

    try:
        _FBP_SUPPRESS_IMAGE_DURATION_CB = True
        for rig in targets:
            if rig != self:
                fbp_set_rna_property_silent(rig, "fbp_global_duration", target_value)

            items = list(getattr(rig, "fbp_images", []) or [])
            if multi_rig:
                edit_items = items
            else:
                checked = [item for item in items if bool(getattr(item, "is_selected", False))]
                edit_items = checked or items

            changed = False
            for item in edit_items:
                try:
                    if int(getattr(item, "duration", 1)) != target_value:
                        item.duration = target_value
                        changed = True
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
            if changed or rig == self or multi_rig:
                changed_rigs.append(rig)
    except Exception as exc:
        fbp_warn("Could not apply FPS/duration to selected layers", exc)
    finally:
        _FBP_SUPPRESS_IMAGE_DURATION_CB = False

    for rig in changed_rigs or targets or [self]:
        fbp_refresh_sequence_backend_from_rig(rig)
        do_update_animation(rig)


def fbp_find_rig_for_image_item(image_item, context=None):
    """Find the owning FBP rig for a row in Object.fbp_images.

    Blender update callbacks for items inside CollectionProperty do not receive
    the parent Object, so we resolve it by pointer. Active/selected objects are
    checked first to keep the common UI edit path fast.
    """
    if image_item is None:
        return None
    try:
        target_ptr = image_item.as_pointer()
    except Exception:
        return None

    candidates = []
    try:
        if context and getattr(context, 'object', None):
            candidates.append(context.object)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        if context:
            candidates.extend(list(getattr(context, 'selected_objects', []) or []))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        candidates.extend([obj for obj in bpy.data.objects if getattr(obj, 'is_fbp_control', False)])
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    seen = set()
    for rig in candidates:
        if not rig or not getattr(rig, 'is_fbp_control', False):
            continue
        try:
            key = rig.as_pointer()
            if key in seen:
                continue
            seen.add(key)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        try:
            for item in getattr(rig, 'fbp_images', []):
                if item.as_pointer() == target_ptr:
                    return rig
        except ReferenceError:
            continue
        except Exception:
            continue
    return None


def update_image_duration_cb(self, context):
    """Live-update native/legacy timing when a single image row duration changes."""
    if _FBP_SUPPRESS_IMAGE_DURATION_CB:
        return
    try:
        rig = fbp_find_rig_for_image_item(self, context)
        if not rig:
            return
        fbp_refresh_sequence_backend_from_rig(rig)
        do_update_animation(rig)
    except Exception as exc:
        fbp_warn("Image row duration update skipped", exc)


def update_visibility_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    sync_fbp_property(self, context, "fbp_is_visible")
    update_global_visibility(context)

def fbp_color_targets_for_update(context, source_rig):
    """Return rigs that should receive a layer color change from the N-Panel.

    Color changes respect the current Layer Stack selection.
    If a collection row was selected, its recursive layer selection is already
    represented by Scene.fbp_layers[*].selected, so this also colors all layers
    inside the selected collection instead of only the active/first rig.
    """
    if not context or not source_rig or not is_fbp_layer_object(source_rig):
        return []
    scene = getattr(context, 'scene', None)
    if not scene:
        return [source_rig]

    targets = []
    seen = set()

    def add_rig(rig):
        if not rig or not is_fbp_layer_object(rig):
            return
        name = getattr(rig, 'name', '')
        if not name or name in seen:
            return
        seen.add(name)
        targets.append(rig)

    # Main path: selected layer rows in the UIList / Layer Stack.
    try:
        for item in scene.fbp_layers:
            if bool(getattr(item, 'selected', False)):
                add_rig(getattr(item, 'obj', None))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    # If the active rig is part of a fully selected collection, force-recursive
    # targets. This covers the user workflow: select collection -> change color
    # from the selected layer/N-Panel.
    try:
        coll = get_primary_fbp_collection(source_rig)
        if coll and bool(getattr(coll, 'fbp_collection_selected', False)):
            for rig in iter_fbp_rigs_in_collection(coll, True):
                add_rig(rig)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    # Fallback: selected Blender objects, useful when the user selected layers in
    # the viewport/Outliner rather than the UIList.
    try:
        for obj in getattr(context, 'selected_objects', []):
            add_rig(obj)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    if not targets:
        add_rig(source_rig)
    elif source_rig not in targets:
        # Keep source first for predictable collection push behavior.
        targets.insert(0, source_rig)
    return targets


def fbp_apply_color_tag_to_targets(context, source_rig, color_tag):
    """Apply a color tag to selected layer targets without recursive callbacks."""
    if color_tag not in STRIP_COLORS_DICT:
        return False
    targets = fbp_color_targets_for_update(context, source_rig)
    if not targets:
        return False

    # Count variants per collection so sibling layers remain visually readable.
    counters = {}
    for rig in targets:
        try:
            coll = get_primary_fbp_collection(rig)
            key = getattr(coll, 'name', '') if coll else '__scene__'
            idx = counters.get(key, 0)
            counters[key] = idx + 1
            fbp_set_rna_property_silent(rig, 'fbp_color_tag', color_tag)
            fbp_set_rna_property_silent(rig, 'fbp_color_variant_index', idx)
            apply_collection_color_to_layer(
                rig,
                color_tag,
                idx,
                push_collection=bool(coll and getattr(rig, 'fbp_follow_collection_color', True))
            )
        except ReferenceError:
            pass
        except Exception as exc:
            fbp_warn('Could not apply bulk layer color tag', exc)
    return True


def update_color_tag_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    sync_fbp_property(self, context, "fbp_color_tag")
    if is_fbp_layer_object(self):
        # Apply selected layer color changes to all selected layers or the selected collection.
        if fbp_apply_color_tag_to_targets(context, self, self.fbp_color_tag):
            return
        apply_collection_color_to_layer(
            self,
            self.fbp_color_tag,
            getattr(self, "fbp_color_variant_index", 0),
            push_collection=getattr(self, "fbp_follow_collection_color", True)
        )

def update_image_index_cb(self, context):
    # Do not move the timeline when selecting an image row.
    # The visible frame is evaluated from the current timeline position.
    if not getattr(self, "is_fbp_control", False):
        return
    do_update_animation(self)
    if getattr(self, "fbp_is_color_plane", False):
        fbp_load_active_procedural_frame_to_rig(self)

def update_layer_stack_index_cb(self, context):
    try:
        idx = self.fbp_layer_stack_index
        if 0 <= idx < len(self.fbp_layers):
            obj = self.fbp_layers[idx].obj
            if obj and is_fbp_layer_object(obj):
                if context.view_layer.objects.active != obj:
                    # Keep previous selections alive so the layer list can support multi-select painting.
                    obj.select_set(True)
                    context.view_layer.objects.active = obj
    except Exception as e:
        print(f"[FBP] Stack index error: {e}")

def apply_camera_ratio_settings(scene):
    # Apply selected output ratio before camera or camera-ratio plane creation.
    if not scene:
        return
    ratio = getattr(scene, 'fbp_cam_ratio', '4_3')
    presets = {
        'HD_16_9': (1920, 1080), 'UHD_4K': (3840, 2160), '16_9': (1920, 1080),
        'STORY_9_16': (1080, 1920), '9_16': (1080, 1920), '4_3': (1920, 1440),
        '3_4': (1440, 1920), '1_1': (2000, 2000), '5_4': (2000, 1600),
        '16_10': (1920, 1200), 'PHOTO_3_2': (3000, 2000), 'PHOTO_2_3': (2000, 3000),
        'CINEMA_185': (1850, 1000), 'CINEMA_239': (2390, 1000), 'TWO_1': (2000, 1000),
        'ULTRAWIDE_21_9': (2520, 1080), 'A4_LANDSCAPE': (2480, 1754), 'A4_PORTRAIT': (1754, 2480),
    }
    if ratio in presets:
        scene.render.resolution_x, scene.render.resolution_y = presets[ratio]


def update_cam_ratio_cb(self, context):
    # Store the chosen camera/output ratio only.
    # Do not change the current scene/camera frame just because the preset changes:
    # Frame by Plane applies this ratio only when it creates a new camera.
    return None


# ── RENDER STABILITY HELPERS ─────────────────────────────────────────────────

def fbp_is_rendering_now():
    """Best-effort render guard. Avoid UI side effects while Blender renders."""
    if bool(fbp_runtime_get("fbp_render_guard_active", False)):
        return True
    try:
        return bool(bpy.app.is_job_running('RENDER'))
    except Exception:
        return False


def fbp_ensure_plane_render_safe(rig, frame=None):
    """Validate render state for the selected sequence backend."""
    if not rig or not getattr(rig, "is_fbp_control", False):
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False
    mesh = plane.data

    if fbp_rig_uses_procedural_color(rig):
        return fbp_apply_procedural_color_frame(rig, frame)

    try:
        if len(mesh.materials) == 0 or mesh.materials[0] is None:
            return False
        while len(mesh.materials) > 1:
            mesh.materials.pop(index=len(mesh.materials) - 1)
    except Exception:
        return False

    try:
        if not mesh.uv_layers:
            mesh.uv_layers.new(name="UVMap")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    try:
        for poly in mesh.polygons:
            poly.material_index = 0
        mesh.update()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    try:
        plane.hide_render = not bool(getattr(rig, "fbp_is_visible", True))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    return True


def fbp_repair_all_render_state(scene=None, frame=None):
    scene = scene or bpy.context.scene
    fixed = 0
    for obj in list(scene.objects):
        try:
            if getattr(obj, "is_fbp_control", False):
                if fbp_ensure_plane_render_safe(obj, frame):
                    fixed += 1
                try:
                    obj.hide_render = True
                except (ReferenceError, RuntimeError):
                    pass
        except ReferenceError:
            pass
    return fixed


def fbp_render_visibility_guard(scene):
    """Render-pre safe pass: visibility only, no mesh/material datablock edits.

    Animated procedural Color/Gradient/Holdout planes can be expensive in the
    viewport while Blender renders. They remain renderable, but their viewport
    visibility is temporarily disabled and restored after render/cancel.
    """
    if not scene:
        return 0
    changed = 0
    viewport_backup = {}
    for obj in list(scene.objects):
        try:
            if not getattr(obj, "is_fbp_control", False):
                continue
            if not obj.hide_render:
                obj.hide_render = True
                changed += 1
            plane = getattr(obj, "fbp_plane_target", None)
            if plane and getattr(plane, "is_fbp_plane", False):
                target_hide = not bool(getattr(obj, "fbp_is_visible", True))
                if plane.hide_render != target_hide:
                    plane.hide_render = target_hide
                    changed += 1
                if getattr(obj, 'fbp_is_color_plane', False):
                    viewport_backup[plane.name] = bool(getattr(plane, 'hide_viewport', False))
                    if not plane.hide_viewport:
                        plane.hide_viewport = True
                        changed += 1
        except ReferenceError:
            continue
        except (AttributeError, TypeError, RuntimeError) as exc:
            fbp_warn("Render visibility guard skipped object", exc)
    if viewport_backup:
        fbp_runtime_set('fbp_render_viewport_hidden_planes', viewport_backup)
    return changed


@bpy.app.handlers.persistent
def fbp_render_guard_pre(scene):
    fbp_runtime_set("fbp_render_guard_active", True)
    try:
        fbp_render_visibility_guard(scene)
    except Exception as e:
        fbp_warn("Render visibility guard failed", e)


@bpy.app.handlers.persistent
def fbp_render_guard_post(scene):
    try:
        backup = fbp_runtime_get('fbp_render_viewport_hidden_planes', {}) or {}
        for name, was_hidden in list(backup.items()):
            obj = bpy.data.objects.get(name)
            if obj:
                obj.hide_viewport = bool(was_hidden)
        fbp_runtime_set('fbp_render_viewport_hidden_planes', {})
    except Exception as exc:
        fbp_warn('Could not restore viewport visibility after render', exc)
    fbp_runtime_set("fbp_render_guard_active", False)


# ── HANDLERS ─────────────────────────────────────────────────────────────────


@bpy.app.handlers.persistent
def fbp_frame_change_handler(scene):
    # Native ImageUser playback does not require Python work on each frame.
    # Procedural Color / Gradient / Holdout rows still need material-slot timing.
    try:
        fbp_update_sequence_scene(scene, getattr(scene, 'frame_current', None))
    except Exception as exc:
        fbp_warn("Procedural sequence frame handler skipped", exc)
    if not fbp_is_rendering_now():
        fbp_tag_view3d_ui_redraw()
    return

FBP_COLOR_PLANE_PRESETS = {
    'CUSTOM': ((1.0, 1.0, 1.0, 1.0), 'Custom'),
    'BLACK': ((0.0, 0.0, 0.0, 1.0), 'Black'),
    'WHITE': ((1.0, 1.0, 1.0, 1.0), 'White'),
    'MIDDLE_GREY': ((0.5, 0.5, 0.5, 1.0), 'Middle Grey'),
    'GREENSCREEN': ((0.0, 1.0, 0.0, 1.0), 'Greenscreen'),
    'BLUE': ((0.4, 0.592156862745098, 1.0, 1.0), 'Blue'),
    'PURPLE': ((0.5803921568627451, 0.3137254901960784, 0.9529411764705882, 1.0), 'Purple'),
    'ROSE': ((1.0, 0.25, 0.55, 1.0), 'Rose'),
    'ORANGE': ((1.0, 0.7019607843137254, 0.0, 1.0), 'Yellow'),
    'RED': ((1.0, 0.0, 0.0, 1.0), 'Red'),
}


def update_color_plane_preset_cb(self, context):
    try:
        preset = getattr(self, 'fbp_color_plane_preset', 'CUSTOM')
        if preset == 'CUSTOM':
            return
        color = FBP_COLOR_PLANE_PRESETS.get(preset, FBP_COLOR_PLANE_PRESETS['CUSTOM'])[0]
        self['_fbp_applying_color_preset'] = True
        self.fbp_color_plane_color = color
    except Exception as exc:
        fbp_warn("Could not apply color plane preset", exc)
    finally:
        try:
            self['_fbp_applying_color_preset'] = False
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass


def update_color_plane_color_cb(self, context):
    try:
        if bool(self.get('_fbp_applying_color_preset', False)):
            return
        if getattr(self, 'fbp_color_plane_preset', 'CUSTOM') != 'CUSTOM':
            self.fbp_color_plane_preset = 'CUSTOM'
    except Exception as exc:
        fbp_warn("Could not switch color plane preset to Custom", exc)


def update_scene_gradient_preview_cb(self, context):
    """Keep the creation preview material synced with the N-Panel / popup gradient controls."""
    try:
        fbp_update_scene_gradient_preview_material(self)
    except ReferenceError:
        return
    except Exception as exc:
        fbp_warn("Could not update gradient preview material", exc)



# ── PROPERTY REGISTRATION MOVED TO properties.py ───────────────────────────────

# ── MATERIAL CREATION ─────────────────────────────────────────────────────────


# ── COLOR / MASK PLANE HELPERS ───────────────────────────────────────────────


def update_object_color_plane_cb(self, context):
    try:
        if fbp_is_silent_property_update(self) or (fbp_obj_runtime_key(self) in _FBP_SYNCING_FRAME_MATERIAL_POINTERS):
            return
        mode = getattr(self, 'fbp_color_plane_mode', 'SOLID')
        if mode != 'GRADIENT':
            # Close gradient foldouts when the active frame/layer is not a gradient.
            try:
                self.fbp_show_gradient_ramp = False
                self.fbp_show_gradient_transform = False
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
        elif mode == 'GRADIENT':
            try:
                self.fbp_show_gradient_ramp = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass

        props = (
            'fbp_color_plane_mode', 'fbp_color_plane_color', 'fbp_color_plane_emission',
            'fbp_gradient_mode', 'fbp_gradient_kind', 'fbp_gradient_color_a', 'fbp_gradient_color_b',
            'fbp_gradient_reverse', 'fbp_show_gradient_ramp', 'fbp_show_gradient_transform',
        )
        for rig in fbp_edit_targets(context, self, same_type=True):
            if rig != self:
                fbp_copy_registered_props_silent(rig, self, props)
            if fbp_rebuild_color_plane_material(rig):
                fbp_refresh_active_procedural_preview(rig)
                fbp_apply_procedural_color_frame(rig, getattr(context.scene, 'frame_current', None) if context else None)
    except ReferenceError:
        return
    except Exception as exc:
        fbp_warn("Could not update color/gradient plane material", exc)


# ── FIT TO CAMERA ─────────────────────────────────────────────────────────────


# ── BUILDER MOVED TO builder.py ───────────────────────────────────────────────
# Mesh creation, rig building, fit-to-camera and plane extension helpers
# are imported from builder.py.

# ── UI MOVED TO ui.py ──────────────────────────────────────────────────────────
# Panels, UILists, menu injection and UI draw helpers live in ui.py.


# ── UI HELPERS ────────────────────────────────────────────────────────────────


def update_gradient_mapping_cb(self, context):
    try:
        if fbp_obj_runtime_key(self) in _FBP_SYNCING_FRAME_MATERIAL_POINTERS:
            return
        props = ('fbp_gradient_offset_x', 'fbp_gradient_offset_y', 'fbp_gradient_scale_x', 'fbp_gradient_scale_y', 'fbp_gradient_rotation')
        for rig in fbp_edit_targets(context, self, same_type=True):
            if rig != self:
                fbp_copy_registered_props_silent(rig, self, props)
            apply_fbp_gradient_mapping_to_material(rig)
            fbp_refresh_active_procedural_preview(rig)
    except Exception as exc:
        fbp_warn("Could not update gradient transform", exc)


def draw_scene_fbp_color_ramp(layout, scene):
    """Draw the native ColorRamp in creation UI by editing a preview material node.

    This function is draw-safe: it never creates or mutates ID data-blocks.
    """
    box = layout.box()
    is_open = bool(getattr(scene, 'fbp_show_gradient_ramp', True))
    row = box.row(align=True)
    row.prop(scene, 'fbp_show_gradient_ramp', text='Color Ramp', icon=(fbp_icon('DOWNARROW_HLT') if is_open else fbp_icon('RIGHTARROW')), emboss=False)
    if not is_open:
        return
    try:
        mat = get_or_create_fbp_gradient_preview_material(scene)
    except Exception as exc:
        fbp_warn("Could not prepare gradient ColorRamp", exc)
        mat = get_fbp_gradient_preview_material(scene)
    ramp_node = find_fbp_gradient_ramp_node(mat) if mat else None
    if not ramp_node:
        box.label(text='No editable ColorRamp found.', icon=fbp_icon('ERROR'))
        return
    box.template_color_ramp(ramp_node, 'color_ramp', expand=True)


def draw_native_fbp_color_ramp(layout, rig):
    """Draw Blender's native ColorRamp widget for already-created gradient planes.

    This edits the actual shader node, so colors, stops, interpolation and keyframes
    remain stored directly in the material.
    """
    box = layout.box()
    is_open = bool(getattr(rig, 'fbp_show_gradient_ramp', True))
    row = box.row(align=True)
    row.prop(rig, 'fbp_show_gradient_ramp', text='Color Ramp', icon=(fbp_icon('DOWNARROW_HLT') if is_open else fbp_icon('RIGHTARROW')), emboss=False)
    if not is_open:
        return
    mat = get_fbp_gradient_material_from_rig(rig)
    ramp_node = find_fbp_gradient_ramp_node(mat) if mat else None
    if not ramp_node:
        box.label(text='No editable ColorRamp found on this gradient material.', icon=fbp_icon('ERROR'))
        return
    box.template_color_ramp(ramp_node, 'color_ramp', expand=True)


def fbp_draw_gradient_choice_rows(layout, owner):
    """Draw gradient choices as two compact dropdowns on one stable row."""
    row = layout.row(align=True)
    row.prop(owner, "fbp_gradient_mode", text="")
    row.prop(owner, "fbp_gradient_kind", text="")


def fbp_draw_color_plane_color_row(layout, scene):
    row = layout.row(align=False)
    split = row.split(factor=0.62, align=False)
    color_col = split.row(align=True)
    color_col.prop(scene, "fbp_color_plane_color", text="Color")
    preset_col = split.row(align=True)
    preset_col.prop(scene, "fbp_color_plane_preset", text="")


# SECTION 04B - Multiplane Setup helpers #
def _fbp_pending_open_collection_set(scene):
    try:
        raw = str(getattr(scene, "fbp_pending_open_collections", "") or "")
    except Exception:
        raw = ""
    return {name for name in raw.split("|") if name}


def pending_collection_is_open(scene, collection_name):
    """Return whether a Multiplane Setup collection is expanded in the UI."""
    name = collection_name or "Unsorted"
    return name in _fbp_pending_open_collection_set(scene)


def set_pending_collection_open(scene, collection_name, is_open=True):
    """Persist expanded/collapsed state for the Multiplane Setup collection UI."""
    name = collection_name or "Unsorted"
    values = _fbp_pending_open_collection_set(scene)
    if is_open:
        values.add(name)
    else:
        values.discard(name)
    try:
        scene.fbp_pending_open_collections = "|".join(sorted(values, key=natural_sort_key))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


# ── PANELS ────────────────────────────────────────────────────────────────────


# ── OPERATORS ─────────────────────────────────────────────────────────────────


# ── IMPORTER BRIDGE ─────────────────────────────────────────────────────────
# Import/scan/Fast Import functions now live in importer.py.
# These wrappers keep the shared core.py API stable.

def _fbp_importer():
    try:
        from . import importer
        return importer
    except Exception:
        import importer
        return importer


def fbp_scan_project_layers_for_setup(root):
    return _fbp_importer().fbp_scan_project_layers_for_setup(root)


def fbp_folder_has_importable_content(path):
    return _fbp_importer().fbp_folder_has_importable_content(path)


def fbp_folder_direct_images(path):
    return _fbp_importer().fbp_folder_direct_images(path)


def fbp_folder_direct_dirs(path):
    return _fbp_importer().fbp_folder_direct_dirs(path)


def fbp_child_entries(path):
    return _fbp_importer().fbp_child_entries(path)


def fbp_collect_mixed_folder_entries(base):
    return _fbp_importer().fbp_collect_mixed_folder_entries(base)


def fbp_build_project_folder(context, folder_path, parent_collection, cursor_loc, depth_counter, color_seed=0, depth=0, color_state=None):
    return _fbp_importer().fbp_build_project_folder(
        context, folder_path, parent_collection, cursor_loc, depth_counter,
        color_seed, depth, color_state,
    )


def fbp_color_plane_can_have_frames(rig):
    return bool(getattr(rig, "fbp_is_color_plane", False) and getattr(rig, "fbp_color_plane_mode", "SOLID") != 'HOLDOUT')


def fbp_load_active_procedural_frame_to_rig(rig):
    """Load the active color/gradient frame material into the rig UI controls.

    Each procedural frame owns its own material. Selecting a frame updates the
    editable color/gradient controls, while the update callbacks are suppressed
    so selecting does not accidentally overwrite that material.
    """
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return False
    mat = fbp_get_active_frame_material(rig)
    if not mat:
        return False
    key = fbp_obj_runtime_key(rig)
    try:
        if key is not None:
            _FBP_SYNCING_FRAME_MATERIAL_POINTERS.add(key)
        idx = max(0, min(int(getattr(rig, 'fbp_images_index', 0)), len(getattr(rig, 'fbp_images', [])) - 1)) if len(getattr(rig, 'fbp_images', [])) else 0
        kind = fbp_procedural_kind_for_item(rig, idx, fbp_procedural_kind_from_material(mat, getattr(rig, 'fbp_color_plane_mode', 'SOLID')))
        if kind == 'GRADIENT':
            rig.fbp_color_plane_mode = 'GRADIENT'
            rig.fbp_gradient_mode = str(mat.get('fbp_gradient_mode', getattr(rig, 'fbp_gradient_mode', 'LINEAR')))
            rig.fbp_gradient_kind = str(mat.get('fbp_gradient_kind', getattr(rig, 'fbp_gradient_kind', 'COLOR')))
            rig.fbp_gradient_reverse = bool(mat.get('fbp_gradient_reverse', getattr(rig, 'fbp_gradient_reverse', False)))
            ramp = find_fbp_gradient_ramp_node(mat)
            if ramp and len(ramp.color_ramp.elements) >= 2:
                elems = ramp.color_ramp.elements
                rig.fbp_gradient_color_a = tuple(elems[0].color)
                rig.fbp_gradient_color_b = tuple(elems[-1].color)
        elif kind == 'HOLDOUT':
            rig.fbp_color_plane_mode = 'HOLDOUT'
        else:
            rig.fbp_color_plane_mode = 'SOLID'
            rig.fbp_color_plane_color = fbp_material_color_value(mat, tuple(getattr(rig, 'fbp_color_plane_color', (1.0, 1.0, 1.0, 1.0))))
        return True
    except Exception as exc:
        fbp_warn('Could not load active procedural frame settings', exc)
        return False
    finally:
        try:
            if key is not None:
                _FBP_SYNCING_FRAME_MATERIAL_POINTERS.discard(key)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass


def fbp_sequence_snapshot(rig):
    """Return sequence row data.

    Native image planes use Object.fbp_images as the only source of truth.
    Procedural Color/Gradient planes may still carry one material per frame.
    """
    plane = getattr(rig, 'fbp_plane_target', None)
    image_data = [(item.name, item.duration, item.is_selected, getattr(item, 'is_empty', False), getattr(item, 'filepath', ''), getattr(item, 'procedural_kind', 'AUTO')) for item in rig.fbp_images]
    material_data = []

    if not getattr(rig, "fbp_is_color_plane", False):
        return image_data, material_data

    material_data = [
        plane.data.materials[i] if plane and i < len(plane.data.materials) else None
        for i in range(len(image_data))
    ]
    if not image_data and plane:
        if not fbp_color_plane_can_have_frames(rig):
            return [], []
        source_mat = plane.data.materials[0] if len(plane.data.materials) else None
        if not source_mat:
            fbp_rebuild_color_plane_material(rig)
            source_mat = plane.data.materials[0] if len(plane.data.materials) else None
        label = "Gradient" if getattr(rig, "fbp_color_plane_mode", "SOLID") == 'GRADIENT' else "Color"
        kind = fbp_procedural_kind_from_material(source_mat, getattr(rig, "fbp_color_plane_mode", "SOLID"))
        image_data = [(label, max(1, int(getattr(rig, 'fbp_global_duration', 1))), True, False, "", kind)]
        material_data = [source_mat]
    return image_data, material_data


def fbp_normalize_sequence_entry(entry, rig=None):
    """Return a dict representation for both new and legacy sequence entries.

    Beta 1.0.18 introduced procedural per-row metadata as dictionaries, but
    several older operators still pass tuples like:

        (name, duration, is_selected, is_empty, filepath, procedural_kind)

    Keeping the normalization in one place prevents tuple/dict mismatches and
    lets Color/Gradient rows stay mixed safely.
    """
    if isinstance(entry, dict):
        data = dict(entry)
    else:
        try:
            seq = list(entry)
        except Exception:
            seq = []
        fallback_duration = max(1, int(getattr(rig, 'fbp_global_duration', 1) or 1)) if rig else 1
        data = {
            "name": seq[0] if len(seq) > 0 else "Frame",
            "duration": seq[1] if len(seq) > 1 else fallback_duration,
            "is_selected": seq[2] if len(seq) > 2 else True,
            "is_empty": seq[3] if len(seq) > 3 else False,
            "filepath": seq[4] if len(seq) > 4 else "",
            "procedural_kind": seq[5] if len(seq) > 5 else 'AUTO',
        }
    try:
        data["duration"] = max(1, int(data.get("duration", getattr(rig, 'fbp_global_duration', 1) if rig else 1) or 1))
    except Exception:
        data["duration"] = 1
    data["name"] = str(data.get("name", "Frame") or "Frame")
    data["is_selected"] = bool(data.get("is_selected", True))
    data["is_empty"] = bool(data.get("is_empty", False))
    data["filepath"] = str(data.get("filepath", "") or "")
    data["procedural_kind"] = str(data.get("procedural_kind", 'AUTO') or 'AUTO')
    return data


def fbp_sequence_entry_to_tuple(entry, rig=None):
    data = fbp_normalize_sequence_entry(entry, rig)
    return (
        data["name"],
        data["duration"],
        data["is_selected"],
        data["is_empty"],
        data["filepath"],
        data["procedural_kind"],
    )


def fbp_insert_sequence_entry(rig, entry, material, insert_at=None):
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane:
        return -1
    entry_data = fbp_normalize_sequence_entry(entry, rig)
    entry_tuple = fbp_sequence_entry_to_tuple(entry_data, rig)
    image_data, material_data = fbp_sequence_snapshot(rig)
    is_color_plane = getattr(rig, "fbp_is_color_plane", False)
    if is_color_plane and not fbp_color_plane_can_have_frames(rig):
        return -1
    if not is_color_plane and bool(entry_data.get("is_empty", False)):
        # Native image planes are backed by one ShaderNodeTexImage Image Sequence.
        # Empty material rows are intentionally no longer supported here.
        return -1
    if insert_at is None:
        checked = [i for i, data in enumerate(image_data) if data[2]]
        if checked:
            insert_at = checked[-1] + 1
        else:
            insert_at = min(max(getattr(rig, 'fbp_images_index', 0), 0), len(image_data) - 1) + 1 if image_data else 0
    image_data.insert(insert_at, entry_tuple)
    if is_color_plane:
        material_data.insert(insert_at, material)

    rig.fbp_images.clear()
    for data in image_data:
        data = fbp_sequence_entry_to_tuple(data, rig)
        item = rig.fbp_images.add()
        item.name = data[0]
        item.duration = data[1]
        item.is_selected = data[2]
        item.is_empty = bool(data[3])
        item.filepath = data[4]
        try:
            item.procedural_kind = data[5] if len(data) > 5 else 'AUTO'
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        if is_color_plane:
            try:
                mat = material_data[len(rig.fbp_images) - 1] if len(rig.fbp_images) - 1 < len(material_data) else None
                fbp_cache_procedural_preview_on_item(item, mat, getattr(item, 'procedural_kind', 'SOLID'))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass

    if is_color_plane:
        plane.data.materials.clear()
        for index, mat in enumerate(material_data):
            if mat:
                kind = 'AUTO'
                try:
                    if index < len(image_data):
                        kind = fbp_sequence_entry_to_tuple(image_data[index], rig)[5]
                except Exception:
                    kind = entry_data.get("procedural_kind", 'AUTO')
                if kind == 'AUTO':
                    kind = fbp_procedural_kind_from_material(mat, getattr(rig, 'fbp_color_plane_mode', 'SOLID'))
                fbp_set_procedural_metadata(mat, kind)
                plane.data.materials.append(mat)

    rig.fbp_images_index = max(0, min(insert_at, len(rig.fbp_images) - 1)) if rig.fbp_images else 0
    try:
        if not is_color_plane:
            if not fbp_rebuild_sequence_backend_from_rig(rig):
                return -1
        else:
            fbp_refresh_sequence_backend_from_rig(rig)
    except Exception as exc:
        fbp_warn("Could not update sequence after inserting row", exc)
        if not is_color_plane:
            return -1
    do_update_animation(rig)
    do_update_emission(rig)
    do_update_opacity(rig)
    return insert_at


def fbp_sequence_entries_from_rig(rig):
    entries = []
    plane = getattr(rig, "fbp_plane_target", None)
    is_color_plane = getattr(rig, "fbp_is_color_plane", False)
    for i, item in enumerate(rig.fbp_images):
        mat = plane.data.materials[i] if is_color_plane and plane and i < len(plane.data.materials) else None
        entries.append({
            "name": item.name,
            "duration": item.duration,
            "is_selected": item.is_selected,
            "is_empty": getattr(item, "is_empty", False),
            "filepath": getattr(item, "filepath", ""),
            "procedural_kind": fbp_procedural_kind_for_item(rig, i, getattr(rig, 'fbp_color_plane_mode', 'SOLID')) if is_color_plane else getattr(item, 'procedural_kind', 'AUTO'),
            "material": mat,
        })
    return entries


def fbp_clone_sequence_entry_material(entry, rig=None, suffix="Copy"):
    """Clone a procedural Color/Gradient entry without sharing material data."""
    cloned = dict(entry)
    mat = entry.get("material")
    if mat:
        new_mat = fbp_duplicate_procedural_material_for_frame(mat, rig, suffix)
        if new_mat:
            cloned["material"] = new_mat
    # After duplication, only the newly-created rows should remain checked.
    cloned["is_selected"] = True
    return cloned


def fbp_apply_sequence_entries_to_rig(rig, entries):
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane:
        return False
    is_color_plane = getattr(rig, "fbp_is_color_plane", False)
    rig.fbp_images.clear()
    if is_color_plane:
        plane.data.materials.clear()
    for entry in entries:
        if is_color_plane:
            mat = entry.get("material")
            if mat:
                fbp_set_procedural_metadata(mat, entry.get("procedural_kind", fbp_procedural_kind_from_material(mat, getattr(rig, 'fbp_color_plane_mode', 'SOLID'))))
                plane.data.materials.append(mat)
        item = rig.fbp_images.add()
        item.name = entry.get("name", "Image")
        item.duration = int(entry.get("duration", getattr(rig, "fbp_global_duration", 1)) or 1)
        item.is_selected = bool(entry.get("is_selected", True))
        item.is_empty = bool(entry.get("is_empty", False))
        item.filepath = entry.get("filepath", "")
        try:
            item.procedural_kind = entry.get("procedural_kind", 'AUTO')
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        if is_color_plane:
            try:
                fbp_cache_procedural_preview_on_item(item, entry.get("material"), getattr(item, 'procedural_kind', 'SOLID'))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
    rig.fbp_images_index = min(max(0, rig.fbp_images_index), max(0, len(rig.fbp_images) - 1))
    if entries:
        first_path = entries[0].get("filepath", "")
        if first_path:
            rig.fbp_preview_path = first_path
    try:
        if is_color_plane and not str(rig.get('fbp_procedural_layer_type', '') or ''):
            rig['fbp_procedural_layer_type'] = str(getattr(rig, 'fbp_color_plane_mode', 'SOLID') or 'SOLID')
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        if not is_color_plane:
            fbp_rebuild_sequence_backend_from_rig(rig)
        else:
            fbp_refresh_sequence_backend_from_rig(rig)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    do_update_animation(rig)
    do_update_emission(rig)
    do_update_opacity(rig)
    return True


# ── FAST IMPORT / SCENE SPLIT BRIDGE ─────────────────────────────────────────

def fbp_fast_import_wm(context=None):
    return _fbp_importer().fbp_fast_import_wm(context)


def fbp_fast_import_depth(context=None):
    return _fbp_importer().fbp_fast_import_depth(context)


def fbp_set_fast_import_depth(value, context=None):
    return _fbp_importer().fbp_set_fast_import_depth(value, context)


def fbp_fast_import_is_active():
    return _fbp_importer().fbp_fast_import_is_active()


def fbp_fast_import_queued_names(context=None):
    return _fbp_importer().fbp_fast_import_queued_names(context)


def fbp_set_fast_import_queued_names(names, context=None):
    return _fbp_importer().fbp_set_fast_import_queued_names(names, context)


def fbp_fast_import_queue_rig(rig):
    return _fbp_importer().fbp_fast_import_queue_rig(rig)


def fbp_preserve_current_frame(context, func, *args, **kwargs):
    return _fbp_importer().fbp_preserve_current_frame(context, func, *args, **kwargs)


def fbp_current_profile():
    return _fbp_importer().fbp_current_profile()


def fbp_profiled_section(label):
    return _fbp_importer().fbp_profiled_section(label)


def fbp_capture_viewport_state():
    return _fbp_importer().fbp_capture_viewport_state()


def fbp_set_viewports_solid(saved):
    return _fbp_importer().fbp_set_viewports_solid(saved)


def fbp_restore_viewport_state(saved):
    return _fbp_importer().fbp_restore_viewport_state(saved)


def fbp_begin_fast_import(context):
    return _fbp_importer().fbp_begin_fast_import(context)


def fbp_end_fast_import(context):
    return _fbp_importer().fbp_end_fast_import(context)


def fbp_folder_has_images_recursive(path):
    return _fbp_importer().fbp_folder_has_images_recursive(path)


def fbp_unique_scene_name(base_name):
    return _fbp_importer().fbp_unique_scene_name(base_name)


def fbp_apply_scene_defaults(scene):
    return _fbp_importer().fbp_apply_scene_defaults(scene)


def fbp_auto_build_main_folders_as_scenes(operator, context):
    return _fbp_importer().fbp_auto_build_main_folders_as_scenes(operator, context)


# Fast Import is invoked directly inside the operator execute methods.
# Avoid monkey-patching operator methods at module load.


# UI compatibility proxy.
def draw_creation_ui(layout, context):
    """Compatibility proxy for the creation UI layout."""
    try:
        from .ui_layout import draw_creation_ui as _fbp_draw_creation_ui
    except ImportError:
        from ui_layout import draw_creation_ui as _fbp_draw_creation_ui
    return _fbp_draw_creation_ui(layout, context)
