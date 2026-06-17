"""Core sequence, procedural material and shared UI operations."""

import bpy

from .constants import STRIP_COLORS_DICT, fbp_icon
from .path_utils import natural_sort_key
from .materials import (
    safe_get_socket,
    fbp_remove_unused_materials_and_images,
    do_update_emission,
    do_update_opacity,
    configure_fbp_material_surface,
    fbp_rebuild_color_plane_material,
    get_fbp_gradient_material_from_rig,
    find_fbp_gradient_ramp_node,
    update_fbp_gradient_viewport_color,
    apply_fbp_gradient_mapping_to_material,
    get_fbp_gradient_preview_material,
    get_or_create_fbp_gradient_preview_material,
    fbp_update_scene_gradient_preview_material,
    fbp_get_active_frame_material,
    fbp_material_color_value,
    fbp_duplicate_procedural_material_for_frame,
    ensure_fbp_plane_material_integrity,
)
from .builder import set_plane_mesh_extension
from .runtime import (
    fbp_warn,
    fbp_warn_once,
    fbp_runtime_get,
    fbp_runtime_set,
    fbp_obj_runtime_key,
    fbp_is_silent_property_update,
    fbp_set_rna_property_silent,
)
from .layers import (
    _FBP_SYNCING_PROCEDURAL_PREVIEW_ITEMS,
    apply_collection_color_to_layer,
    fbp_cache_procedural_preview_on_item,
    fbp_procedural_kind_for_item,
    fbp_procedural_kind_from_material,
    fbp_resolve_rig_from_any_object,
    fbp_set_procedural_metadata,
    get_primary_fbp_collection,
    is_fbp_layer_object,
    iter_fbp_rigs_in_collection,
    iter_scene_fbp_rigs,
    update_global_visibility,
)

_FBP_SYNCING_FRAME_MATERIAL_POINTERS = set()
_FBP_SUPPRESS_IMAGE_DURATION_CB = False


# ── CORE OPERATIONS ───────────────────────────────────────────────────────────


def fbp_rig_uses_procedural_color(rig):
    """Return whether the rig uses the current procedural color-plane workflow."""
    try:
        return bool(rig and getattr(rig, 'fbp_is_color_plane', False))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def fbp_sequence_index_at_frame(rig, frame=None):
    """Evaluate the visible procedural row without per-frame list rebuilding.

    Image layers use Blender ImageUser timing. Color, Gradient and Holdout rows
    are evaluated here; keep the hot frame-change path compact because it runs
    once per procedural layer on every evaluated frame.
    """
    if frame is None:
        scene = getattr(bpy.context, "scene", None)
        frame = getattr(scene, "frame_current", 1)
    try:
        start = int(getattr(rig, "fbp_start_frame", 1))
        rel = int(frame) - start
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        rel = 0
    if rel < 0:
        return -1

    items = getattr(rig, "fbp_images", ()) or ()
    count = len(items)
    if count <= 0:
        return -1

    default_duration = max(1, int(getattr(rig, "fbp_global_duration", 1) or 1))
    durations = tuple(
        max(1, int(getattr(item, "duration", default_duration) or default_duration))
        for item in items
    )
    mode = str(getattr(rig, "fbp_loop_mode", "NONE") or "NONE")

    if mode == "PINGPONG" and count > 1:
        # Ping-pong does not duplicate the first/last row at the turnarounds:
        # 0, 1, 2, 1 for a three-row sequence.
        total = max(1, sum(durations) + sum(durations[1:-1]))
        local = rel % total
        accumulator = 0
        for index, duration in enumerate(durations):
            accumulator += duration
            if local < accumulator:
                return index
        for index in range(count - 2, 0, -1):
            accumulator += durations[index]
            if local < accumulator:
                return index
        return 0

    total = max(1, sum(durations))
    local = rel % total if mode == "REPEAT" else min(rel, total - 1)
    accumulator = 0
    for index, duration in enumerate(durations):
        accumulator += duration
        if local < accumulator:
            return index
    return count - 1


def fbp_apply_procedural_color_frame(rig, frame=None):
    """Apply a procedural Color/Gradient frame material safely.

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
    except ReferenceError:
        return False
    except (AttributeError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError) as exc:
        fbp_warn_once(
            f"procedural_uv_setup:{getattr(rig, 'name', '<unknown>')}",
            "Could not create the procedural plane UV map",
            exc,
        )

    try:
        if len(mesh.materials) == 0 or mesh.materials[0] is None:
            fbp_rebuild_color_plane_material(rig)
    except ReferenceError:
        return False
    except (AttributeError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError) as exc:
        fbp_warn_once(
            f"procedural_material_rebuild:{getattr(rig, 'name', '<unknown>')}",
            "Could not rebuild the procedural plane material",
            exc,
        )

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
                # Frame by Plane panels and current-frame indicators live in
                # the 3D View. Redrawing Timeline/Dopesheet areas every frame
                # adds work without updating any FBP-owned interface.
                if getattr(area, 'type', '') != 'VIEW_3D':
                    continue
                # Updating only the Sidebar avoids forcing a full 3D viewport
                # redraw on every frame while keeping FBP frame indicators live.
                ui_regions = [
                    region for region in (getattr(area, 'regions', ()) or ())
                    if getattr(region, 'type', '') == 'UI'
                ]
                if ui_regions:
                    for region in ui_regions:
                        region.tag_redraw()
                else:
                    # Defensive fallback for unusual/headless area layouts.
                    area.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def fbp_update_sequence_scene(scene=None, frame=None):
    """Refresh procedural rows and report whether any require frame UI redraw."""
    scene = scene or getattr(bpy.context, 'scene', None)
    if not scene:
        return 0, False
    if frame is None:
        frame = getattr(scene, 'frame_current', 1)
    updated = 0
    has_procedural_rigs = False
    for obj in iter_scene_fbp_rigs(scene):
        try:
            if not getattr(obj, 'is_fbp_control', False):
                continue
            if fbp_rig_uses_procedural_color(obj) and len(getattr(obj, 'fbp_images', [])) > 0:
                has_procedural_rigs = True
                if fbp_apply_procedural_color_frame(obj, frame):
                    updated += 1
        except ReferenceError:
            continue
        except Exception as exc:
            fbp_warn_once(
                f"procedural_sequence_frame:{getattr(obj, 'name', 'unknown')}",
                "Sequence scene update skipped",
                exc,
            )
    return updated, has_procedural_rigs


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
    """Return the immutable source sequence used by a native image rig."""
    if not rig or getattr(rig, "fbp_is_color_plane", False):
        return "", []
    try:
        from . import native_backend
        directory, files = native_backend.fbp_native_source_sequence_from_rig(rig)
        return (directory, list(files)) if directory and files else ("", [])
    except Exception as exc:
        fbp_warn("Could not read native source sequence metadata", exc)
        return "", []



def fbp_rig_native_sequence_needs_rename(rig):
    """True if the selected rig uses filenames that may fail as a native Image Sequence."""
    directory, files = fbp_native_sequence_files_from_rig(rig)
    if not directory or len(files) <= 1:
        return False
    try:
        from . import native_backend
        return bool(native_backend.fbp_rig_native_sequence_needs_rename(rig))
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




def fbp_collection_item_owner_rig(item, procedural_only=False):
    """Return the Object ID that owns an Object.fbp_images row.

    CollectionProperty items inherit bpy_struct.id_data, so normal UI callbacks
    can resolve their parent rig directly instead of scanning every scene object.
    """
    if not item:
        return None
    try:
        rig = getattr(item, 'id_data', None)
    except ReferenceError:
        return None
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    if not rig or not getattr(rig, 'is_fbp_control', False):
        return None
    if procedural_only and not getattr(rig, 'fbp_is_color_plane', False):
        return None
    return rig


def fbp_collection_item_index(rig, item):
    """Return an item's index inside its owning rig without global searches."""
    if not rig or not item:
        return -1
    try:
        target_ptr = item.as_pointer()
        for index, row in enumerate(getattr(rig, 'fbp_images', [])):
            if row.as_pointer() == target_ptr:
                return index
    except ReferenceError:
        return -1
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return -1
    return -1


def fbp_find_rig_for_procedural_frame_item(item, context=None):
    """Return ``(rig, index)`` for a procedural frame UIList item."""
    if not item:
        return None, -1
    owner = fbp_collection_item_owner_rig(item, procedural_only=True)
    owner_index = fbp_collection_item_index(owner, item)
    return (owner, owner_index) if owner and owner_index >= 0 else (None, -1)



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


def update_loop_mode_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_edit_targets(context, self)
    value = str(getattr(self, "fbp_loop_mode", 'NONE'))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_loop_mode", value)
    for rig in targets:
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
        do_update_animation(rig)

def update_emission_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_edit_targets(context, self)
    value = bool(getattr(self, "fbp_use_emission", False))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_use_emission", value)
    for rig in targets:
        do_update_emission(rig)


def update_opacity_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_edit_targets(context, self)
    value = float(getattr(self, "fbp_opacity", 1.0))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_opacity", value)
    for rig in targets:
        do_update_opacity(rig)


def update_track_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_edit_targets(context, self)
    value = bool(getattr(self, "fbp_track_cam", False))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_track_cam", value)
    for rig in targets:
        do_update_track(rig, context)

def update_global_duration_cb(self, context):
    if fbp_is_silent_property_update(self):
        return

    global _FBP_SUPPRESS_IMAGE_DURATION_CB
    previous_suppression = _FBP_SUPPRESS_IMAGE_DURATION_CB
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
        _FBP_SUPPRESS_IMAGE_DURATION_CB = previous_suppression

    for rig in changed_rigs or targets or [self]:
        do_update_animation(rig)


def fbp_find_rig_for_image_item(image_item, context=None):
    """Return the owning FBP rig for a current ``Object.fbp_images`` row."""
    if image_item is None:
        return None
    owner = fbp_collection_item_owner_rig(image_item)
    return owner if owner and fbp_collection_item_index(owner, image_item) >= 0 else None



def update_image_duration_cb(self, context):
    """Live-update sequence timing when a single image row duration changes."""
    if _FBP_SUPPRESS_IMAGE_DURATION_CB or fbp_is_silent_property_update(self):
        return
    try:
        rig = fbp_find_rig_for_image_item(self, context)
        if not rig:
            return
        do_update_animation(rig)
    except Exception as exc:
        fbp_warn("Image row duration update skipped", exc)


def update_visibility_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    targets = fbp_edit_targets(context, self)
    value = bool(getattr(self, "fbp_is_visible", True))
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_is_visible", value)
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
            add_rig(fbp_resolve_rig_from_any_object(obj, context))
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
    except Exception as exc:
        fbp_warn("Layer stack selection update skipped", exc)

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
        if len(mesh.materials) == 0:
            return False
        if not ensure_fbp_plane_material_integrity(rig):
            return False
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False

    try:
        if not mesh.uv_layers:
            mesh.uv_layers.new(name="UVMap")
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
    for obj in iter_scene_fbp_rigs(scene):
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
                    viewport_backup[plane.name] = {
                        "object_key": fbp_obj_runtime_key(plane),
                        "hide_viewport": bool(getattr(plane, 'hide_viewport', False)),
                    }
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
    # Some render paths can emit render_pre more than once before the matching
    # post/cancel callback. Preserve the first backup instead of overwriting it
    # with the already-hidden state from a nested notification.
    if bool(fbp_runtime_get("fbp_render_guard_active", False)):
        return
    fbp_runtime_set('fbp_render_viewport_hidden_planes', {})
    fbp_runtime_set("fbp_render_guard_active", True)
    try:
        from .geometry_nodes import fbp_effect_render_guard_pre
        fbp_runtime_set("fbp_effect_render_backup", fbp_effect_render_guard_pre())
    except Exception as exc:
        fbp_warn("Effect render visibility guard failed", exc)
    try:
        fbp_render_visibility_guard(scene)
    except Exception as e:
        fbp_warn("Render visibility guard failed", e)


@bpy.app.handlers.persistent
def fbp_render_guard_post(scene):
    try:
        backup = fbp_runtime_get('fbp_render_viewport_hidden_planes', {}) or {}
        for name, stored in list(backup.items()):
            obj = bpy.data.objects.get(name)
            if not obj:
                continue
            if isinstance(stored, dict):
                if fbp_obj_runtime_key(obj) != stored.get("object_key"):
                    continue
                was_hidden = bool(stored.get("hide_viewport", False))
            else:
                # Runtime compatibility with a guard started before module reload.
                was_hidden = bool(stored)
            obj.hide_viewport = was_hidden
        fbp_runtime_set('fbp_render_viewport_hidden_planes', {})
    except Exception as exc:
        fbp_warn('Could not restore viewport visibility after render', exc)
    try:
        from .geometry_nodes import fbp_effect_render_guard_post
        fbp_effect_render_guard_post(fbp_runtime_get("fbp_effect_render_backup", []) or [])
        fbp_runtime_set("fbp_effect_render_backup", [])
    except Exception as exc:
        fbp_warn("Could not restore effect viewport visibility after render", exc)
    fbp_runtime_set("fbp_render_guard_active", False)


# ── HANDLERS ─────────────────────────────────────────────────────────────────


@bpy.app.handlers.persistent
def fbp_frame_change_handler(scene):
    # Native ImageUser playback does not require Python work on each frame.
    # Procedural Color / Gradient / Holdout rows still need material-slot timing.
    has_procedural_rigs = False
    try:
        _updated, has_procedural_rigs = fbp_update_sequence_scene(
            scene, getattr(scene, 'frame_current', None)
        )
    except Exception as exc:
        fbp_warn_once(
            "procedural_sequence_frame_handler",
            "Procedural sequence frame handler skipped",
            exc,
        )
    if has_procedural_rigs and not fbp_is_rendering_now():
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
    'YELLOW': ((1.0, 0.7019607843137254, 0.0, 1.0), 'Yellow'),
    'ORANGE': ((1.0, 0.4745098039215686, 0.0, 1.0), 'Orange'),
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


# ── PROCEDURAL SEQUENCE HELPERS ──────────────────────────────────────────────

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


def fbp_normalize_sequence_entry(entry, rig=None):
    """Validate and normalize one current dictionary-based sequence entry."""
    if not isinstance(entry, dict):
        raise TypeError("Sequence entries must use the current dictionary format")
    data = dict(entry)
    try:
        fallback_duration = getattr(rig, "fbp_global_duration", 1) if rig else 1
        data["duration"] = max(1, int(data.get("duration", fallback_duration) or 1))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        data["duration"] = 1
    data["name"] = str(data.get("name", "Frame") or "Frame")
    data["is_selected"] = bool(data.get("is_selected", True))
    data["is_empty"] = bool(data.get("is_empty", False))
    data["filepath"] = str(data.get("filepath", "") or "")
    data["procedural_kind"] = str(data.get("procedural_kind", "AUTO") or "AUTO")
    return data



def fbp_insert_sequence_entry(rig, entry, material, insert_at=None):
    """Insert one normalized sequence entry and rebuild through the shared path."""
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane:
        return -1

    is_color_plane = bool(getattr(rig, "fbp_is_color_plane", False))
    if is_color_plane and not fbp_color_plane_can_have_frames(rig):
        return -1

    entry_data = fbp_normalize_sequence_entry(entry, rig)
    # Native image planes keep transparent rows inside the same Image Sequence
    # material. The native backend drives an alpha visibility mask for those
    # logical frames, so no generated image file or extra material is required.
    entry_data["material"] = material if is_color_plane else None

    entries = fbp_sequence_entries_from_rig(rig)
    if is_color_plane and not entries:
        # Promote a static Color/Gradient plane to a one-frame procedural sequence
        # before inserting the requested row.
        source_mat = plane.data.materials[0] if len(plane.data.materials) else None
        if not source_mat:
            fbp_rebuild_color_plane_material(rig)
            source_mat = plane.data.materials[0] if len(plane.data.materials) else None
        label = "Gradient" if getattr(rig, "fbp_color_plane_mode", "SOLID") == 'GRADIENT' else "Color"
        kind = fbp_procedural_kind_from_material(
            source_mat,
            getattr(rig, "fbp_color_plane_mode", "SOLID"),
        )
        entries = [{
            "name": label,
            "duration": max(1, int(getattr(rig, 'fbp_global_duration', 1) or 1)),
            "is_selected": True,
            "is_empty": False,
            "filepath": "",
            "procedural_kind": kind,
            "material": source_mat,
        }]

    if insert_at is None:
        checked = [i for i, data in enumerate(entries) if bool(data.get("is_selected", False))]
        if checked:
            insert_at = checked[-1] + 1
        else:
            current = int(getattr(rig, 'fbp_images_index', 0) or 0)
            insert_at = min(max(current, 0), len(entries) - 1) + 1 if entries else 0
    insert_at = max(0, min(int(insert_at), len(entries)))
    entries.insert(insert_at, entry_data)

    try:
        if not fbp_apply_sequence_entries_to_rig(rig, entries):
            return -1
        rig.fbp_images_index = max(0, min(insert_at, len(rig.fbp_images) - 1)) if rig.fbp_images else 0
        if is_color_plane:
            fbp_load_active_procedural_frame_to_rig(rig)
        return insert_at
    except Exception as exc:
        fbp_warn("Could not update sequence after inserting row", exc)
        return -1


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
    """Apply logical sequence rows without leaving UI/backend state half-updated."""
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane:
        return False
    is_color_plane = getattr(rig, "fbp_is_color_plane", False)
    normalized_entries = []
    try:
        for raw_entry in entries:
            data = fbp_normalize_sequence_entry(raw_entry, rig)
            data["material"] = raw_entry.get("material")
            normalized_entries.append(data)
    except (TypeError, ValueError) as exc:
        fbp_warn("Rejected invalid sequence entry", exc)
        return False
    if is_color_plane and any(entry.get("material") is None for entry in normalized_entries):
        fbp_warn("Rejected procedural sequence with missing frame material")
        return False

    old_entries = fbp_sequence_entries_from_rig(rig)
    old_index = int(getattr(rig, 'fbp_images_index', 0) or 0)
    old_preview = str(getattr(rig, 'fbp_preview_path', '') or '')
    old_material_slots = list(getattr(plane.data, 'materials', [])) if is_color_plane else []
    candidate_materials = [
        entry.get("material") for entry in normalized_entries
        if entry.get("material") is not None
    ]

    def populate_state(values):
        rig.fbp_images.clear()
        if is_color_plane:
            plane.data.materials.clear()
        for entry in values:
            material = entry.get("material")
            if is_color_plane and material:
                fbp_set_procedural_metadata(
                    material,
                    entry.get(
                        "procedural_kind",
                        fbp_procedural_kind_from_material(
                            material,
                            getattr(rig, 'fbp_color_plane_mode', 'SOLID'),
                        ),
                    ),
                )
                plane.data.materials.append(material)

            item = rig.fbp_images.add()
            item.name = entry.get("name", "Image")
            fbp_set_rna_property_silent(
                item,
                "duration",
                max(
                    1,
                    int(entry.get("duration", getattr(rig, "fbp_global_duration", 1)) or 1),
                ),
            )
            item.is_selected = bool(entry.get("is_selected", True))
            item.is_empty = bool(entry.get("is_empty", False))
            item.filepath = str(entry.get("filepath", "") or "")
            try:
                item.procedural_kind = entry.get("procedural_kind", 'AUTO')
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            if is_color_plane:
                try:
                    fbp_cache_procedural_preview_on_item(
                        item,
                        material,
                        getattr(item, 'procedural_kind', 'SOLID'),
                    )
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass

    def restore_previous_state():
        populate_state(old_entries)
        rig.fbp_images_index = max(
            0,
            min(old_index, max(0, len(rig.fbp_images) - 1)),
        )
        try:
            rig.fbp_preview_path = old_preview
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        if is_color_plane:
            try:
                plane.data.materials.clear()
                for material in old_material_slots:
                    if material:
                        plane.data.materials.append(material)
            except Exception as exc:
                fbp_warn("Could not restore procedural material slots", exc)
            try:
                fbp_refresh_sequence_backend_from_rig(rig)
            except Exception as exc:
                fbp_warn("Could not refresh restored procedural sequence", exc)
            try:
                old_materials = [material for material in old_material_slots if material]
                fbp_remove_unused_materials_and_images([
                    mat for mat in candidate_materials
                    if mat
                    and not any(mat == old for old in old_materials)
                    and getattr(mat, 'users', 0) == 0
                ])
            except Exception as exc:
                fbp_warn("Could not clean rolled-back procedural materials", exc)

    populate_state(normalized_entries)
    rig.fbp_images_index = min(
        max(0, int(getattr(rig, 'fbp_images_index', 0) or 0)),
        max(0, len(rig.fbp_images) - 1),
    )
    if normalized_entries:
        first_path = next(
            (entry.get("filepath", "") for entry in normalized_entries if entry.get("filepath", "")),
            "",
        )
        if first_path:
            rig.fbp_preview_path = first_path
    try:
        if is_color_plane and not str(rig.get('fbp_procedural_layer_type', '') or ''):
            rig['fbp_procedural_layer_type'] = str(
                getattr(rig, 'fbp_color_plane_mode', 'SOLID') or 'SOLID'
            )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    try:
        if is_color_plane:
            rebuilt = fbp_refresh_sequence_backend_from_rig(rig)
        else:
            rebuilt = fbp_rebuild_sequence_backend_from_rig(rig)
        if not rebuilt:
            restore_previous_state()
            return False
    except Exception as exc:
        restore_previous_state()
        fbp_warn("Could not apply sequence entries", exc)
        return False

    do_update_animation(rig)
    do_update_emission(rig)
    do_update_opacity(rig)
    if is_color_plane:
        try:
            current_materials = [material for material in plane.data.materials if material]
            fbp_remove_unused_materials_and_images([
                material for material in old_material_slots
                if material
                and not any(material == current for current in current_materials)
                and getattr(material, 'users', 0) == 0
            ])
        except Exception as exc:
            fbp_warn("Could not clean replaced procedural materials", exc)
    return True



# Fast Import is invoked directly inside the operator execute methods.
# Avoid monkey-patching operator methods at module load.

