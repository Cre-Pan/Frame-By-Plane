"""Focused Frame By Plane operator module."""

import bpy
import time
from bpy.props import (
    BoolProperty,
    IntProperty,
    StringProperty,
    EnumProperty,
)
from bpy.types import Operator

from .constants import (
    FBP_LAYER_BLEND_MENU_ITEMS,
    fbp_icon, fbp_layer_blend_label, fbp_layer_blend_mode_columns,
)
from .effects_registry import (
    FBP_EFFECT_CLIPPING_MASK, FBP_EFFECT_LAYER_BLEND, fbp_effect_definition,
)
from .path_utils import natural_sort_key
from .builder import apply_fit_to_camera
from .ui_style import configure_layout, hint_row, section_header
from .layers import (
    _collection_gp_canvases_for_ui,
    _collection_rigs_for_ui,
    _safe_layer_obj,
    ensure_object_in_active_collection,
    fbp_build_canonical_collection_tree,
    fbp_active_layer_index,
    fbp_clipping_source_map,
    fbp_layer_has_sampleable_image,
    fbp_active_work_collection,
    fbp_layer_depth_value_from_cache,
    fbp_make_depth_context_cache,
    get_primary_fbp_collection,
    get_selected_fbp_roots,
    get_selected_rigs,
    is_fbp_layer_object,
    iter_fbp_rigs_in_collection,
    iter_scene_fbp_rigs,
    move_layer_to_depth_preserve_projection,
    move_object_to_collection,
    set_collection_color_tag,
    object_in_view_layer,
    swap_layer_depth_only,
    update_global_visibility,
    visible_layer_indices,
    get_collection_holdout, set_collection_holdout,
    get_collection_locked, set_collection_locked,
    get_collection_plane_locked, set_collection_plane_locked,
    get_collection_selected, set_collection_selected,
    get_collection_solo, set_collection_solo,
    get_collection_visible, set_collection_visible,
)
from .scene_sync import delete_fbp_rigs, fbp_rename_layer_rig, sync_layer_collection
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_set_rna_property_silent,
    fbp_runtime_get,
    fbp_runtime_set,
    fbp_registration_busy,
    fbp_warn,
    fbp_tag_redraw,
)
from .core import (
    do_update_animation,
    fbp_load_active_procedural_frame_to_rig,
    pending_collection_is_open,
    set_pending_collection_open,
)
from .transactions import FBPTransaction
from .ui_context import restore_modal_cursor
from .ui_list_state import transient_get, transient_pop, transient_set
from .shortcut_runtime import primary_modifier_pressed
from .operator_common import (
    FBP_VerticalDragModalMixin,
    fbp_begin_ui_modal_mutation,
    fbp_touch_ui_modal_mutation,
    fbp_end_ui_modal_mutation,
    _fbp_refresh_layer_tree,
    _fbp_refresh_pending_tree,
    fbp_jump_timeline_to_sequence_row,
)


_FBP_LAST_UI_NAME_CLICK = {"key": None, "time": 0.0}


_FBP_COLLECTION_ROW_SELECTION_GUARD_KEY = "fbp.collection_row_selection_guard"
_FBP_COLLECTION_ROW_SELECTION_GUARD_SECONDS = 0.85


def _fbp_clear_collection_row_selection_guard():
    try:
        fbp_runtime_set(_FBP_COLLECTION_ROW_SELECTION_GUARD_KEY, None)
    except FBP_DATA_IO_ERRORS:
        pass


def _fbp_arm_collection_row_selection_guard(scene, collection_name, tree_index):
    if scene is None or not collection_name:
        return
    try:
        scene_pointer = int(scene.as_pointer())
    except FBP_DATA_ERRORS:
        scene_pointer = 0
    try:
        fbp_runtime_set(
            _FBP_COLLECTION_ROW_SELECTION_GUARD_KEY,
            {
                "scene_pointer": scene_pointer,
                "collection_name": str(collection_name or ""),
                "tree_index": int(tree_index),
                "expires": time.monotonic() + _FBP_COLLECTION_ROW_SELECTION_GUARD_SECONDS,
            },
        )
    except FBP_DATA_IO_ERRORS:
        pass


def _fbp_ui_name_click_key(operator):
    return (
        str(getattr(operator, "target_type", "") or ""),
        str(getattr(operator, "rig_name", "") or ""),
        str(getattr(operator, "collection_name", "") or ""),
        int(getattr(operator, "index", -1) or -1),
        int(getattr(operator, "tree_index", -1) or -1),
        str(getattr(operator, "list_mode", "ALL") or "ALL").upper(),
    )


def _fbp_normalize_layer_list_mode(mode):
    normalized = str(mode or "ALL").upper()
    return normalized if normalized in {"ALL", "PLANES", "GP"} else "ALL"


def _fbp_layer_selection_anchor_key(mode):
    """Keep Shift-selection anchors independent for each filtered UIList."""
    return f"_fbp_layer_selection_anchor_{_fbp_normalize_layer_list_mode(mode).lower()}"


def _fbp_layer_selection_anchor_token_key(mode):
    return f"{_fbp_layer_selection_anchor_key(mode)}_token"


def _fbp_tree_row_anchor_token(row):
    if row is None:
        return ""
    try:
        return "\x1f".join((
            str(getattr(row, "row_type", "") or ""),
            str(getattr(row, "collection_name", "") or ""),
            str(getattr(row, "rig_name", "") or ""),
            str(getattr(row, "canvas_name", "") or ""),
            str(getattr(row, "gp_layer_name", "") or ""),
        ))
    except FBP_DATA_ERRORS:
        return ""


def _fbp_resolve_layer_selection_anchor(scene, fallback_index, mode):
    """Resolve a Shift anchor after tree rebuild, collapse or depth reorder."""
    if scene is None:
        return int(fallback_index)
    list_mode = _fbp_normalize_layer_list_mode(mode)
    index_key = _fbp_layer_selection_anchor_key(list_mode)
    token_key = _fbp_layer_selection_anchor_token_key(list_mode)
    try:
        stored_index = int(transient_get(scene, index_key, fallback_index))
        token = str(transient_get(scene, token_key, "") or "")
        rows = tuple(getattr(scene, "fbp_layer_tree_rows", ()) or ())
        if token:
            for index, row in enumerate(rows):
                if (
                    _fbp_tree_row_visible_for_mode(row, list_mode)
                    and _fbp_tree_row_anchor_token(row) == token
                ):
                    return index
        if rows:
            return max(0, min(stored_index, len(rows) - 1))
        return int(fallback_index)
    except FBP_DATA_ERRORS:
        return int(fallback_index)


def _fbp_store_layer_selection_anchor(scene, row_index, mode):
    if scene is None:
        return
    list_mode = _fbp_normalize_layer_list_mode(mode)
    index = int(row_index)
    try:
        transient_set(scene, _fbp_layer_selection_anchor_key(list_mode), index)
        rows = tuple(getattr(scene, "fbp_layer_tree_rows", ()) or ())
        token = _fbp_tree_row_anchor_token(rows[index]) if 0 <= index < len(rows) else ""
        transient_set(scene, _fbp_layer_selection_anchor_token_key(list_mode), token)
    except FBP_DATA_ERRORS:
        pass


def _fbp_tree_selection_targets(scene, anchor, current, list_mode="ALL"):
    """Resolve visible layer-like objects in one flattened tree range.

    Plane and Grease Pencil lists share the same backing row collection.  A raw
    index range therefore contains hidden rows from the other list.  Filtering
    here prevents Shift-click in one split list from selecting objects that the
    user cannot see, while the combined list still spans both object families.
    """
    if scene is None:
        return []
    mode = _fbp_normalize_layer_list_mode(list_mode)
    try:
        rows = tuple(getattr(scene, "fbp_layer_tree_rows", ()) or ())
        if not rows:
            return []
        lo, hi = sorted((
            max(0, min(int(anchor), len(rows) - 1)),
            max(0, min(int(current), len(rows) - 1)),
        ))
    except FBP_DATA_ERRORS:
        return []

    result = []
    seen = set()
    for row in rows[lo:hi + 1]:
        if not _fbp_tree_row_visible_for_mode(row, mode):
            continue
        row_type = str(getattr(row, "row_type", "") or "")
        if row_type not in {"LAYER", "GP_CANVAS"}:
            continue
        object_name = str(
            getattr(row, "rig_name", "")
            or getattr(row, "canvas_name", "")
            or ""
        )
        candidate = bpy.data.objects.get(object_name)
        if candidate is None:
            continue
        if row_type == "LAYER" and not is_fbp_layer_object(candidate):
            continue
        if row_type == "GP_CANVAS" and not _fbp_is_gp_drawing_canvas_object(candidate):
            continue
        try:
            key = int(candidate.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(candidate)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _fbp_ensure_object_mode(context):
    """Leave GP Draw/Edit/Paint modes before selecting from the Layer List."""
    try:
        if str(getattr(context, "mode", "OBJECT") or "OBJECT") == "OBJECT":
            return True
        active_objects = getattr(getattr(context, "view_layer", None), "objects", None)
        active_obj = getattr(active_objects, "active", None) if active_objects is not None else None
        if active_obj is not None:
            try:
                active_obj.select_set(True)
            except FBP_DATA_IO_ERRORS:
                pass
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode='OBJECT')
            return True
    except FBP_DATA_IO_ERRORS:
        pass
    return str(getattr(context, "mode", "OBJECT") or "OBJECT") == "OBJECT"


def _fbp_deselect_layer_objects(context):
    """Safe deselect that also works when a click starts from GP Draw Mode."""
    _fbp_ensure_object_mode(context)
    try:
        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action='DESELECT')
            return True
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        for obj in tuple(getattr(context.view_layer, "objects", ()) or ()):  # fallback for narrow UI contexts
            try:
                obj.select_set(False)
            except FBP_DATA_IO_ERRORS:
                pass
        return True
    except FBP_DATA_IO_ERRORS:
        return False


_FBP_LAYER_BLEND_ENABLED_KEY = str(
    fbp_effect_definition(FBP_EFFECT_LAYER_BLEND).get(
        "enabled_key", "fbp_effect_layer_blend"
    ) or "fbp_effect_layer_blend"
)


def _fbp_layer_blend_target_rigs(context, rig_name=""):
    """Resolve one UIList layer or the current viewport FBP selection."""
    name = str(rig_name or "")
    if name:
        rig = bpy.data.objects.get(name)
        return [rig] if rig and is_fbp_layer_object(rig) else []
    return [rig for rig in get_selected_fbp_roots(context) if is_fbp_layer_object(rig)]


def _fbp_layer_blend_mode_for_rig(rig):
    if not rig or not is_fbp_layer_object(rig):
        return "NORMAL"
    try:
        if not bool(rig.get(_FBP_LAYER_BLEND_ENABLED_KEY, False)):
            return "NORMAL"
        return str(getattr(rig, "fbp_layer_blend_mode", "MULTIPLY") or "MULTIPLY").upper()
    except FBP_DATA_ERRORS:
        return "NORMAL"


def _fbp_apply_layer_blend_mode(context, rigs, mode):
    """Apply one blend mode without invoking another Blender operator.

    This shared path keeps every Layer Blend entry point identical, including
    relation refresh, Undo data and multi-layer editing.
    """
    mode = str(mode or "NORMAL").upper()
    changed = 0
    unchanged = 0
    skipped = 0
    try:
        from .geometry_nodes import (
            fbp_add_effect, fbp_effect_is_active, fbp_remove_effect,
            fbp_schedule_clipping_mask_sync, fbp_sync_effect_items,
            fbp_update_shader_effect,
        )
    except (ImportError, AttributeError) as exc:
        fbp_warn("Could not load Layer Blend operators", exc)
        return changed, unchanged, max(1, len(tuple(rigs or ())))

    rigs = tuple(rigs or ())
    for rig in rigs:
        try:
            active = bool(fbp_effect_is_active(rig, FBP_EFFECT_LAYER_BLEND))
            current_mode = _fbp_layer_blend_mode_for_rig(rig)
            if mode == "NORMAL":
                if not active and not bool(rig.get(_FBP_LAYER_BLEND_ENABLED_KEY, False)):
                    unchanged += 1
                    continue
                if fbp_remove_effect(rig, FBP_EFFECT_LAYER_BLEND, sync_items=False):
                    fbp_sync_effect_items(rig)
                    changed += 1
                else:
                    skipped += 1
                continue

            if active and current_mode == mode:
                unchanged += 1
                continue

            fbp_set_rna_property_silent(rig, "fbp_layer_blend_mode", mode)
            if not active:
                if not fbp_add_effect(
                    rig, FBP_EFFECT_LAYER_BLEND,
                    inherit_active_group=False, sync_items=False,
                ):
                    skipped += 1
                    continue
            fbp_update_shader_effect(
                rig, FBP_EFFECT_LAYER_BLEND,
                property_names={"fbp_layer_blend_mode"},
            )
            fbp_sync_effect_items(rig)
            changed += 1
        except FBP_DATA_ERRORS as exc:
            skipped += 1
            fbp_warn(f"Could not set Layer Blend on {getattr(rig, 'name', 'layer')}", exc)

    if changed:
        relation_collections = []
        seen_collections = set()
        for rig in rigs:
            collection = get_primary_fbp_collection(rig)
            if collection is None:
                continue
            try:
                key = int(collection.as_pointer())
            except FBP_DATA_ERRORS:
                key = id(collection)
            if key in seen_collections:
                continue
            seen_collections.add(key)
            relation_collections.append(collection)
        fbp_schedule_clipping_mask_sync(
            getattr(context, "scene", None),
            collections=tuple(relation_collections) if relation_collections else None,
        )
    return changed, unchanged, skipped


class FBP_OT_SetLayerBlendMode(Operator):
    bl_idname = "fbp.set_layer_blend_mode"
    bl_label = "Set Layer Blend Mode"
    bl_description = "Apply this blend mode to the chosen Frame By Plane layer, or to all selected Frame By Plane layers"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(description='Operation mode for this Layer List action. Example: choose whether the command adds, removes, previews, repairs or applies settings.',
        name="Blend Mode",
        items=FBP_LAYER_BLEND_MENU_ITEMS,
        default="NORMAL",
        options={'SKIP_SAVE'},
    )
    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', name="Layer", default="", options={'SKIP_SAVE'})

    def execute(self, context):
        rigs = _fbp_layer_blend_target_rigs(context, self.rig_name)
        if not rigs:
            self.report({'WARNING'}, "Select a Frame By Plane layer")
            return {'CANCELLED'}
        mode = str(self.mode or "NORMAL").upper()
        changed, unchanged, skipped = _fbp_apply_layer_blend_mode(context, rigs, mode)
        if changed:
            self.report({'INFO'}, f"{fbp_layer_blend_label(mode)}: {changed} layer(s)")
            return {'FINISHED'}
        if unchanged and not skipped:
            self.report({'INFO'}, f"Selected layer(s) already use {fbp_layer_blend_label(mode)}")
            return {'FINISHED'}
        self.report({'WARNING'}, "Layer Blend is unavailable for the selected layer type")
        return {'CANCELLED'}


class FBP_OT_ShowLayerBlendMenu(Operator):
    bl_idname = "fbp.show_layer_blend_menu"
    bl_label = "Blend"
    bl_description = "Choose a Procreate-style blend mode for this layer or the selected Frame By Plane layers"
    bl_options = {'INTERNAL'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', name="Layer", default="", options={'SKIP_SAVE'})

    def invoke(self, context, _event):
        rigs = _fbp_layer_blend_target_rigs(context, self.rig_name)
        if not rigs:
            self.report({'WARNING'}, "Select a Frame By Plane layer")
            return {'CANCELLED'}

        exact_name = str(self.rig_name or "")
        target_names = tuple(str(getattr(rig, "name", "") or "") for rig in rigs)
        modes = {_fbp_layer_blend_mode_for_rig(rig) for rig in rigs}
        common_mode = next(iter(modes)) if len(modes) == 1 else ""
        target_text = target_names[0] if len(target_names) == 1 else f"{len(target_names)} selected layers"

        def draw_popup(menu, _popup_context):
            layout = menu.layout
            layout.label(text=target_text, icon='NODE_MATERIAL')
            if not common_mode:
                layout.label(text="Mixed blend modes", icon='BLANK1')

            grid = layout.row(align=False)
            for definitions in fbp_layer_blend_mode_columns():
                column = grid.column(align=False)
                for definition in definitions:
                    mode = str(definition.get("id", "NORMAL") or "NORMAL")
                    short = str(definition.get("short", "N") or "N")
                    label = str(definition.get("label", mode.title()) or mode.title())
                    icon = (
                        'CHECKMARK' if common_mode == mode
                        else str(definition.get("icon", "NODE_MATERIAL") or "NODE_MATERIAL")
                    )
                    op = column.operator(
                        'fbp.set_layer_blend_mode',
                        text=f"{short}   {label}",
                        icon=icon,
                    )
                    op.mode = mode
                    op.rig_name = exact_name

            if len(rigs) == 1 and common_mode != "NORMAL":
                rig = rigs[0]
                layout.separator()
                layout.prop(rig, "fbp_layer_blend_factor", text="Blend Opacity", slider=True)
                source = getattr(rig, "fbp_layer_blend_source", None)
                if source is not None:
                    select_source = layout.operator(
                        "fbp.select_layer_relation_source",
                        text=f"Select Source: {getattr(source, 'name', 'Layer')}",
                        icon='RESTRICT_SELECT_OFF',
                    )
                    select_source.rig_name = rig.name
                    select_source.relation = 'BLEND'
                else:
                    layout.label(text="No compatible image layer below", icon='ERROR')

        try:
            context.window_manager.popup_menu(draw_popup, title="Blend", icon='NODE_MATERIAL')
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not open Layer Blend menu", exc)
            return {'CANCELLED'}

    def execute(self, context):
        return self.invoke(context, None)



class FBP_OT_LinkCircleMaskNull(Operator):
    bl_idname = "fbp.link_circle_mask_null"
    bl_label = "Shape Mask External Null"
    bl_description = "Link this Shape Mask to an existing Empty by name, or create a new external Empty"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(name="Layer", options={'SKIP_SAVE'})
    shape: EnumProperty(
        name="Shape",
        items=(
            ('SQUARE', "Square", "Square Shape Mask"),
            ('CIRCLE', "Circle", "Circle Shape Mask"),
            ('TRIANGLE', "Triangle", "Triangle Shape Mask"),
        ),
        default='CIRCLE', options={'SKIP_SAVE'},
    )
    target_name: StringProperty(name="Null", description="Name of an existing Empty or the name for a new one")
    create_if_missing: BoolProperty(name="Create if Missing", default=True)
    unlink: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    def draw(self, context):
        layout = self.layout
        configure_layout(layout)
        layout.prop_search(self, "target_name", bpy.data, "objects", text="Null")
        layout.prop(self, "create_if_missing", toggle=True, icon="ADD")
        hint_row(layout, "The same Null can drive Shape Masks on multiple depth layers", icon="CON_LOCLIKE")

    def invoke(self, context, event):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if not rig or not is_fbp_layer_object(rig):
            return {'CANCELLED'}
        if self.unlink:
            return self.execute(context)
        shape = str(self.shape or "CIRCLE").upper()
        prefix = shape.lower()
        current = getattr(rig, f"fbp_{prefix}_mask_external_null", None)
        if current is not None:
            self.target_name = current.name
        elif not self.target_name:
            self.target_name = f"FBP {shape.title()} Controller • {rig.name}"
        return context.window_manager.invoke_props_dialog(self, width=390)

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if not rig or not is_fbp_layer_object(rig):
            return {'CANCELLED'}
        shape = str(self.shape or "CIRCLE").upper()
        prefix = shape.lower()
        pointer_prop = f"fbp_{prefix}_mask_external_null"
        if self.unlink:
            setattr(rig, pointer_prop, None)
            return {'FINISHED'}
        name = str(self.target_name or "").strip() or f"FBP {shape.title()} Controller • {rig.name}"
        target = bpy.data.objects.get(name)
        if target is not None and getattr(target, "type", "") != "EMPTY":
            self.report({'WARNING'}, "The selected object is not a Null/Empty")
            return {'CANCELLED'}
        try:
            from .object_masks import ensure_object_mask_helper, sync_shape_mask_external_null
            helper = ensure_object_mask_helper(rig, shape, context=context, select=False)
            if helper is None:
                return {'CANCELLED'}
            if target is None:
                if not self.create_if_missing:
                    self.report({'WARNING'}, "No Null with this name was found")
                    return {'CANCELLED'}
                target = bpy.data.objects.new(name, None)
                collection = getattr(context, "collection", None)
                try:
                    (collection or context.scene.collection).objects.link(target)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    context.scene.collection.objects.link(target)
                target.empty_display_type = 'PLAIN_AXES'
                target.empty_display_size = max(0.1, float(max(abs(helper.scale.x), abs(helper.scale.y))))
                target.matrix_world.translation = helper.matrix_world.translation
            setattr(rig, pointer_prop, target)
            fbp_set_rna_property_silent(rig, f"fbp_{prefix}_mask_follow_bounds", False)
            sync_shape_mask_external_null(rig, shape, helper=helper)
            self.report({'INFO'}, f"{shape.title()} Mask linked to {target.name}")
            return {'FINISHED'}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not link Circle Mask to external Null", exc)
            return {'CANCELLED'}


class FBP_OT_PerfectObjectMaskShape(Operator):
    bl_idname = "fbp.perfect_object_mask_shape"
    bl_label = "Perfect Shape"
    bl_description = "Restore a perfect square, circle or equilateral triangle while preserving position, rotation and overall size"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(name="Layer", options={'SKIP_SAVE'})
    shape: EnumProperty(
        name="Shape",
        items=(
            ('SQUARE', "Square", "Perfect square"),
            ('CIRCLE', "Circle", "Perfect circle"),
            ('TRIANGLE', "Triangle", "Equilateral triangle"),
        ),
        default='SQUARE', options={'SKIP_SAVE'},
    )

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if not rig or not is_fbp_layer_object(rig):
            return {'CANCELLED'}
        try:
            from .object_masks import make_object_mask_shape_perfect
            if not make_object_mask_shape_perfect(rig, self.shape):
                return {'CANCELLED'}
            self.report({'INFO'}, f"Perfect {str(self.shape).title()} Mask")
            return {'FINISHED'}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not restore perfect Shape Mask", exc)
            return {'CANCELLED'}


class FBP_OT_RecreateObjectMaskHelper(Operator):
    bl_idname = "fbp.recreate_object_mask_helper"
    bl_label = "Recreate Shape Mask"
    bl_description = "Recreate and select the editable Shape Mask helper aligned to this layer"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', name="Layer", options={'SKIP_SAVE'})
    shape: EnumProperty(description='Choose the Shape option for this Layer List action. Hover each entry for the specific mode when Blender exposes enum item help.',
        name="Shape",
        items=(
            ('SQUARE', "Square", "Editable square helper"),
            ('CIRCLE', "Circle", "Editable circular helper"),
            ('TRIANGLE', "Triangle", "Editable triangular helper"),
        ),
        default='SQUARE', options={'SKIP_SAVE'},
    )

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not is_fbp_layer_object(rig):
            return {'CANCELLED'}
        try:
            from .object_masks import remove_object_mask_helper, create_object_mask_helper
            remove_object_mask_helper(rig, self.shape)
            helper = create_object_mask_helper(rig, self.shape, context=context, select=True)
            if helper is None:
                return {'CANCELLED'}
            from .geometry_nodes import fbp_refresh_object_mask_binding
            effect_id = {
                'SQUARE': 'SQUARE_MASK',
                'CIRCLE': 'CIRCLE_MASK',
                'TRIANGLE': 'TRIANGLE_MASK',
            }[self.shape]
            fbp_refresh_object_mask_binding(rig, effect_id)
            return {'FINISHED'}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not recreate Shape Mask helper", exc)
            return {'CANCELLED'}


class FBP_OT_EditObjectMaskHelper(Operator):
    bl_idname = "fbp.edit_object_mask_helper"
    bl_label = "Edit Shape Mask"
    bl_description = "Select the Shape Mask helper and enter Edit Mode so its vertices define the mask silhouette"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', name="Layer", options={'SKIP_SAVE'})
    shape: EnumProperty(description='Choose the Shape option for this Layer List action. Hover each entry for the specific mode when Blender exposes enum item help.',
        name="Shape",
        items=(
            ('SQUARE', "Square", "Editable square helper"),
            ('CIRCLE', "Circle", "Editable circular helper"),
            ('TRIANGLE', "Triangle", "Editable triangular helper"),
        ),
        default='SQUARE', options={'SKIP_SAVE'},
    )

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not is_fbp_layer_object(rig):
            return {'CANCELLED'}
        try:
            from .object_masks import ensure_object_mask_helper
            helper = ensure_object_mask_helper(rig, self.shape, context=context, select=False)
            if helper is None or not object_in_view_layer(helper, context):
                self.report({'WARNING'}, "Shape Mask helper is not available in this View Layer")
                return {'CANCELLED'}
            if getattr(context, 'mode', 'OBJECT') != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            _fbp_deselect_layer_objects(context)
            helper.hide_viewport = False
            helper.hide_set(False)
            helper.hide_select = False
            helper.select_set(True)
            context.view_layer.objects.active = helper
            bpy.ops.object.mode_set(mode='EDIT')
            # Shape helpers are edge-only cages. Force vertex selection so a
            # workspace left in Face Select does not make the editable shape
            # appear empty because shape cages are edge-only.
            try:
                bpy.ops.mesh.select_mode(type='VERT')
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            bpy.ops.mesh.select_all(action='SELECT')
            return {'FINISHED'}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not enter Shape Mask Edit Mode", exc)
            return {'CANCELLED'}


class FBP_OT_SelectLayerRelationSource(Operator):
    bl_idname = "fbp.select_layer_relation_source"
    bl_label = "Select Source Layer"
    bl_description = "Select the layer currently used as the automatic Blend or Clipping source"
    bl_options = {'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', name="Layer", options={'SKIP_SAVE'})
    relation: EnumProperty(description='Choose the Relation option for this Layer List action. Hover each entry for the specific mode when Blender exposes enum item help.',
        name="Relation",
        items=(
            ('BLEND', "Layer Blend", "Select the image layer used as the Layer Blend base"),
            ('CLIPPING', "Clipping Mask", "Select the image layer supplying the clipping alpha"),
        ),
        default='BLEND',
        options={'SKIP_SAVE'},
    )

    @classmethod
    def description(cls, context, properties):
        relation = str(getattr(properties, "relation", "BLEND") or "BLEND")
        rig = bpy.data.objects.get(str(getattr(properties, "rig_name", "") or ""))
        prop_name = "fbp_clipping_mask_source" if relation == 'CLIPPING' else "fbp_layer_blend_source"
        source = getattr(rig, prop_name, None) if rig else None
        if source is not None:
            return f"Select source layer {getattr(source, 'name', 'Layer')}"
        return "No automatic source layer is currently available"

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if not rig or not is_fbp_layer_object(rig):
            return {'CANCELLED'}
        prop_name = (
            "fbp_clipping_mask_source"
            if str(self.relation or "BLEND") == 'CLIPPING'
            else "fbp_layer_blend_source"
        )
        source = getattr(rig, prop_name, None)
        if source is None or not is_fbp_layer_object(source):
            self.report({'WARNING'}, "No source layer is currently available")
            return {'CANCELLED'}
        if not object_in_view_layer(source, context):
            if not ensure_object_in_active_collection(source, context):
                sync_layer_collection(context)
                self.report({'WARNING'}, "Source layer is not in the active View Layer")
                return {'CANCELLED'}
        try:
            _fbp_deselect_layer_objects(context)
            source.select_set(True)
            context.view_layer.objects.active = source
            for index, item in enumerate(context.scene.fbp_layers):
                try:
                    if item.obj == source:
                        context.scene.fbp_layer_stack_index = index
                        break
                except ReferenceError:
                    continue
            self.report({'INFO'}, f"Selected source layer: {source.name}")
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not select relation source", exc)
            return {'CANCELLED'}


class FBP_OT_RepairLayerRelation(Operator):
    bl_idname = "fbp.repair_layer_relation"
    bl_label = "Repair Layer Relation"
    bl_description = (
        "Safely rebuild and rebind the selected Clipping Mask or Layer Blend "
        "after reordering, duplication, Undo/Redo or a partial node rebuild"
    )
    bl_options = {'REGISTER', 'INTERNAL'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', name="Layer", options={'SKIP_SAVE'})
    relation: EnumProperty(description='Choose the Relation option for this Layer List action. Hover each entry for the specific mode when Blender exposes enum item help.',
        name="Relation",
        items=(
            ('CLIPPING', "Clipping Mask", "Repair this layer's automatic clipping source"),
            ('BLEND', "Layer Blend", "Repair this layer's automatic blend source"),
        ),
        default='CLIPPING',
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None or not is_fbp_layer_object(rig):
            self.report({'WARNING'}, "Frame By Plane layer is no longer available")
            return {'CANCELLED'}

        effect_id = (
            FBP_EFFECT_CLIPPING_MASK
            if str(self.relation or 'CLIPPING') == 'CLIPPING'
            else FBP_EFFECT_LAYER_BLEND
        )
        try:
            from .geometry_nodes import (
                fbp_effect_is_active,
                fbp_schedule_clipping_mask_sync,
            )
            if not fbp_effect_is_active(rig, effect_id):
                self.report({'WARNING'}, "This layer relation is not active")
                return {'CANCELLED'}
            collection = get_primary_fbp_collection(rig)
            fbp_schedule_clipping_mask_sync(
                getattr(context, "scene", None),
                collections=(collection,) if collection is not None else None,
            )
            relation_label = "Clipping Mask" if effect_id == FBP_EFFECT_CLIPPING_MASK else "Layer Blend"
            self.report({'INFO'}, f"{relation_label} repair queued safely")
            return {'FINISHED'}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not repair layer relation", exc)
            self.report({'WARNING'}, "Could not queue the relation repair")
            return {'CANCELLED'}


class FBP_OT_RepairAllLayerRelations(Operator):
    bl_idname = "fbp.repair_all_layer_relations"
    bl_label = "Repair Layer Relations"
    bl_description = (
        "Safely rescan every active Clipping Mask and Layer Blend in the current scene, "
        "clear stale sources and rebuild incomplete relation nodes"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        available = bool(scene is not None and next(iter(iter_scene_fbp_rigs(scene)), None))
        if not available:
            cls.poll_message_set("The current scene contains no Frame By Plane layers to repair")
        return available

    def execute(self, context):
        try:
            from .geometry_nodes import fbp_schedule_clipping_mask_sync
            fbp_schedule_clipping_mask_sync(getattr(context, "scene", None), collections=None)
            self.report({'INFO'}, "Layer relation repair queued for the current scene")
            return {'FINISHED'}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not repair scene layer relations", exc)
            self.report({'WARNING'}, "Could not queue the scene relation repair")
            return {'CANCELLED'}


class FBP_OT_ToggleClippingMask(Operator):
    bl_idname = "fbp.toggle_clipping_mask"
    bl_label = "Toggle Clipping Mask"
    bl_description = 'Toggle clipping for the selected layer using the nearest compatible layer below it'
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', name="Layer", options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        rig = bpy.data.objects.get(str(getattr(properties, "rig_name", "") or ""))
        if not rig:
            return "Clip this layer to the alpha of the physically lower layer in the same collection"
        try:
            definition = fbp_effect_definition(FBP_EFFECT_CLIPPING_MASK)
            enabled_key = str(definition.get("enabled_key", "fbp_effect_clipping_mask") or "fbp_effect_clipping_mask")
            enabled = bool(rig.get(enabled_key, False))
            source = getattr(rig, "fbp_clipping_mask_source", None)
            if enabled:
                source_name = str(getattr(source, "name", "") or "")
                if source_name:
                    return f"Disable Clipping Mask currently using {source_name} as its alpha source"
                return "Disable this Clipping Mask; its previous source is no longer available"
        except FBP_DATA_IO_ERRORS:
            pass
        return "Clip this layer to the alpha of the physically lower layer in the same collection; alphabetical sorting does not change the source"

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not is_fbp_layer_object(rig):
            return {'CANCELLED'}
        try:
            from .geometry_nodes import (
                fbp_add_effect,
                fbp_effect_is_active,
                fbp_remove_effect,
            )
            definition = fbp_effect_definition(FBP_EFFECT_CLIPPING_MASK)
            enabled_key = str(
                definition.get('enabled_key', 'fbp_effect_clipping_mask')
                or 'fbp_effect_clipping_mask'
            )
            stored_enabled = bool(rig.get(enabled_key, False))
            clipping_active = stored_enabled or fbp_effect_is_active(
                rig, FBP_EFFECT_CLIPPING_MASK
            )
            if clipping_active:
                # fbp_remove_effect also clears stale enabled metadata when an
                # the shader node is missing but the feature flag remains.
                if not fbp_remove_effect(rig, FBP_EFFECT_CLIPPING_MASK):
                    return {'CANCELLED'}
                self.report({'INFO'}, "Clipping Mask disabled")
                return {'FINISHED'}

            collection = get_primary_fbp_collection(rig)
            scoped_rigs = tuple(
                iter_fbp_rigs_in_collection(collection, recursive=False)
            ) if collection else (rig,)
            source = fbp_clipping_source_map(
                context,
                rigs=scoped_rigs,
                collections=(collection,) if collection else None,
            ).get(rig)
            if source is None:
                self.report({'WARNING'}, "This layer has no compatible image layer directly below it in the same collection")
                return {'CANCELLED'}
            if not fbp_layer_has_sampleable_image(source):
                self.report({'WARNING'}, "The layer below has no image alpha available for clipping")
                return {'CANCELLED'}

            previous_source = getattr(rig, 'fbp_clipping_mask_source', None)
            previous_projection = bool(getattr(rig, 'fbp_clipping_mask_use_source_transform', True))
            previous_camera_projection = bool(getattr(rig, 'fbp_clipping_mask_use_camera_projection', True))
            # Manually created clipping masks operate in the spatial plane domain
            # by default. This makes opaque rectangular photos clip visibly to
            # the source plane bounds instead of sampling an all-white normalized UV.
            fbp_set_rna_property_silent(
                rig, 'fbp_clipping_mask_use_source_transform', True
            )
            fbp_set_rna_property_silent(
                rig, 'fbp_clipping_mask_use_camera_projection', True
            )
            try:
                rig['fbp_clipping_projection_version'] = 3
            except FBP_DATA_IO_ERRORS:
                pass
            # Bind the source before creating the shader node. This prevents a
            # transient unbound mask and lets initial socket synchronization use
            # the correct alpha source immediately.
            fbp_set_rna_property_silent(
                rig, 'fbp_clipping_mask_source', source
            )
            if not fbp_add_effect(rig, FBP_EFFECT_CLIPPING_MASK):
                fbp_set_rna_property_silent(
                    rig, 'fbp_clipping_mask_source', previous_source
                )
                fbp_set_rna_property_silent(
                    rig, 'fbp_clipping_mask_use_source_transform', previous_projection
                )
                fbp_set_rna_property_silent(
                    rig, 'fbp_clipping_mask_use_camera_projection', previous_camera_projection
                )
                self.report({'WARNING'}, "Could not add Clipping Mask")
                return {'CANCELLED'}
            # Defer relation binding until this UI operator has returned. The
            # effect group may have been removed/recreated in the same event;
            # traversing its ImageUser RNA immediately can dereference a stale
            # node wrapper in Blender 5.2.
            from .geometry_nodes import fbp_schedule_clipping_mask_sync
            fbp_schedule_clipping_mask_sync(
                getattr(context, "scene", None),
                collections=(collection,) if collection else None,
            )
            self.report({'INFO'}, f"Clipped to {source.name}")
            return {'FINISHED'}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not toggle Clipping Mask", exc)
            return {'CANCELLED'}


class FBP_OT_SaveFile(Operator):
    bl_idname      = "fbp.save_file"
    bl_label       = "Save File"
    bl_description = "Quickly save the current .blend file"

    def execute(self, context):
        if not bpy.data.is_saved:
            bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT')
        else:
            bpy.ops.wm.save_mainfile()
            self.report({'INFO'}, "Project saved!")
        return {'FINISHED'}

class FBP_OT_OpenCreateRig(Operator):
    bl_idname      = "fbp.open_create_rig"
    bl_label       = "Create New Frame By Plane Rig"
    bl_description = "Deselect layers and show the Create New Rig panel"
    bl_options     = {'UNDO'}

    def execute(self, context):
        _fbp_deselect_layer_objects(context)
        context.scene.fbp_show_create_tools = True
        return {'FINISHED'}

class FBP_OT_SelectLinkedPlane(Operator):
    bl_idname = "fbp.select_linked_plane"
    bl_label = "Select Linked Plane"
    bl_description = "Unlock and select all mesh planes belonging to this rig; click again to lock them"
    bl_options = {'UNDO'}

    rig_name: StringProperty(name="Rig", description="Frame By Plane rig whose child planes should be selected")

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig:
            return {'CANCELLED'}

        planes = []
        linked = getattr(rig, 'fbp_plane_target', None)
        if linked and getattr(linked, 'type', '') == 'MESH':
            planes.append(linked)
        try:
            descendants = list(rig.children_recursive)
        except (AttributeError, ReferenceError):
            descendants = list(getattr(rig, 'children', ()) or ())
        for child in descendants:
            if getattr(child, 'type', '') != 'MESH' or child in planes:
                continue
            if bool(getattr(child, 'is_fbp_plane', False)) or child.parent == rig:
                planes.append(child)
        planes = [plane for plane in planes if object_in_view_layer(plane, context)]

        if not planes:
            self.report({'WARNING'}, "This layer has no linked mesh plane")
            return {'CANCELLED'}

        # Locked is the default state. Clicking Select Plane unlocks and selects
        # every child mesh. Clicking again restores the lock and the rig selection.
        unlock_and_select = all(bool(getattr(plane, 'hide_select', True)) for plane in planes)
        try:
            if unlock_and_select:
                _fbp_deselect_layer_objects(context)
                for plane in planes:
                    plane.hide_select = False
                    plane.select_set(True)
                context.view_layer.objects.active = planes[0]
            else:
                for plane in planes:
                    plane.select_set(False)
                    plane.hide_select = True
                if object_in_view_layer(rig, context) and not bool(getattr(rig, 'hide_select', False)):
                    rig.select_set(True)
                    context.view_layer.objects.active = rig
        except ReferenceError:
            return {'CANCELLED'}
        except Exception as exc:
            fbp_warn("Could not select linked planes", exc)
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_SelectCollectionPlanes(Operator):
    bl_idname = "fbp.select_collection_planes"
    bl_label = "Toggle Collection Plane Selectability"
    bl_description = "Allow or prevent direct viewport selection of all linked image/color planes in this Frame By Plane collection"
    bl_options = {'UNDO'}

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        planes = []
        for rig in _collection_rigs_for_ui(coll):
            plane = getattr(rig, 'fbp_plane_target', None)
            if plane and object_in_view_layer(plane, context):
                planes.append(plane)
        if not planes:
            self.report({'WARNING'}, "No linked planes found in this collection")
            return {'CANCELLED'}
        # If all planes are locked, unlock them. Otherwise lock them all again.
        unlock = all(getattr(plane, 'hide_select', True) for plane in planes)
        for plane in planes:
            try:
                plane.hide_select = not unlock
                if plane.hide_select and plane.select_get():
                    plane.select_set(False)
            except ReferenceError:
                continue
            except Exception as exc:
                fbp_warn("Could not toggle linked plane selectability in collection", exc)
        return {'FINISHED'}

class FBP_OT_AddColorPlaneVariant(Operator):
    bl_idname = "fbp.add_color_plane_variant"
    bl_label = "Add Color/Gradient Plane"
    bl_description = "Duplicate the selected color, gradient or holdout plane as a new editable layer instead of importing image frames"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rigs = [rig for rig in get_selected_rigs(context) if getattr(rig, 'fbp_is_color_plane', False)]
        if not rigs:
            self.report({'WARNING'}, "Select a Frame By Plane color, gradient or holdout rig first")
            return {'CANCELLED'}
        _fbp_deselect_layer_objects(context)
        for rig in rigs:
            if object_in_view_layer(rig, context):
                rig.select_set(True)
                context.view_layer.objects.active = rig
        return bpy.ops.fbp.duplicate_selected_layers()

class FBP_OT_UIListNameAction(Operator):
    bl_idname = "fbp.ui_list_name_action"
    bl_label = "Select or Rename Item"
    bl_description = "Click to select, double-click to rename, or right-click for contextual actions"
    bl_options = {'REGISTER', 'UNDO'}

    target_type: StringProperty(description="Internal Frame By Plane value used for target type in operator_layers. It is managed by the add-on and normally should not be edited directly.", default="")
    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", default="")
    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")
    index: IntProperty(description="Zero-based index of the frame, drawing, layer or setup entry targeted by this action.", default=-1)
    tree_index: IntProperty(description="Index of the flattened UI tree row targeted by this action.", default=-1)
    list_mode: StringProperty(
        name="Layer List Mode",
        description="Visible Layer List used for range and collection selection",
        default="ALL",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    rename_mode: BoolProperty(description="Open inline rename behavior instead of performing the normal single-click selection action.", default=False, options={'HIDDEN', 'SKIP_SAVE'})
    use_shift: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    use_ctrl: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    new_name: StringProperty(description="New name that will replace the current visible name while preserving Frame By Plane internal links and identities.", name="Name", default="")

    def _current_name(self, context):
        if self.target_type == 'LAYER':
            rig = bpy.data.objects.get(self.rig_name)
            return getattr(rig, 'name', '') if rig else ''
        if self.target_type == 'GP_CANVAS':
            canvas = bpy.data.objects.get(self.rig_name)
            return getattr(canvas, 'name', '') if canvas else ''
        if self.target_type == 'FRAME':
            rig = bpy.data.objects.get(self.rig_name)
            if rig and 0 <= self.index < len(rig.fbp_images):
                return rig.fbp_images[self.index].name
            return ''
        if self.target_type == 'PENDING':
            if 0 <= self.index < len(context.scene.fbp_pending_planes):
                return context.scene.fbp_pending_planes[self.index].name
            return ''
        if self.target_type == 'COLLECTION':
            return self.collection_name
        if self.target_type == 'PENDING_GROUP':
            return self.collection_name.rsplit(' / ', 1)[-1]
        return ''

    def invoke(self, context, event):
        self.use_shift = bool(getattr(event, "shift", False))
        self.use_ctrl = primary_modifier_pressed(event)
        # Context-menu Rename sets rename_mode before invoking this operator.
        # Blender does not consistently forward DOUBLE_CLICK from every UIList
        # button, so keep a tiny timed fallback for fast second clicks on the
        # same row name. This restores reliable double-click rename in compact
        # Layer List rows.
        double_click = bool(getattr(self, 'rename_mode', False)) or getattr(event, 'value', '') == 'DOUBLE_CLICK'
        if not double_click:
            try:
                key = _fbp_ui_name_click_key(self)
                now = time.monotonic()
                if _FBP_LAST_UI_NAME_CLICK.get('key') == key and (now - float(_FBP_LAST_UI_NAME_CLICK.get('time', 0.0))) <= 0.45:
                    double_click = True
                    _FBP_LAST_UI_NAME_CLICK['key'] = None
                    _FBP_LAST_UI_NAME_CLICK['time'] = 0.0
                else:
                    _FBP_LAST_UI_NAME_CLICK['key'] = key
                    _FBP_LAST_UI_NAME_CLICK['time'] = now
            except Exception:
                double_click = False
        if double_click:
            # Keep the row/object selection in sync before opening the rename
            # field. This is especially important for layers: the user can
            # double-click an unselected row and immediately edit that layer.
            if self.target_type in {'LAYER', 'GP_CANVAS', 'FRAME', 'COLLECTION', 'PENDING', 'PENDING_GROUP'}:
                self._select(context)
            self.rename_mode = True
            self.new_name = self._current_name(context)
            return context.window_manager.invoke_props_dialog(self, width=360)
        self.rename_mode = False
        return self.execute(context)

    def draw(self, context):
        self.layout.prop(self, 'new_name', text='Name')

    def _rename(self, context):
        new_name = str(self.new_name or '').strip()
        if not new_name:
            self.report({'WARNING'}, "Name cannot be empty")
            return {'CANCELLED'}

        if self.target_type == 'LAYER':
            rig = bpy.data.objects.get(self.rig_name)
            if not rig or not is_fbp_layer_object(rig):
                return {'CANCELLED'}
            actual_name = fbp_rename_layer_rig(rig, new_name, context)
            if not actual_name:
                return {'CANCELLED'}
            if actual_name != new_name:
                self.report({'INFO'}, f"Layer renamed to {actual_name}")
            return {'FINISHED'}

        if self.target_type == 'GP_CANVAS':
            canvas = bpy.data.objects.get(self.rig_name)
            try:
                from .grease_pencil_bridge import is_gp_canvas
                if not is_gp_canvas(canvas):
                    return {'CANCELLED'}
                old_name = str(getattr(canvas, 'name', '') or '')
                canvas.name = new_name
                data = getattr(canvas, 'data', None)
                if data is not None and str(getattr(data, 'name', '') or '').startswith(old_name):
                    data.name = f"{canvas.name} Data"
                self.rig_name = canvas.name
                _fbp_refresh_layer_tree(context)
                return {'FINISHED'}
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                return {'CANCELLED'}

        if self.target_type == 'FRAME':
            rig = bpy.data.objects.get(self.rig_name)
            if not rig or not (0 <= self.index < len(rig.fbp_images)):
                return {'CANCELLED'}
            rig.fbp_images[self.index].name = new_name
            return {'FINISHED'}

        if self.target_type == 'PENDING':
            if not (0 <= self.index < len(context.scene.fbp_pending_planes)):
                return {'CANCELLED'}
            context.scene.fbp_pending_planes[self.index].name = new_name
            _fbp_refresh_pending_tree(context)
            return {'FINISHED'}

        if self.target_type == 'COLLECTION':
            coll = bpy.data.collections.get(self.collection_name)
            if not coll:
                return {'CANCELLED'}
            old_name = coll.name
            coll.name = new_name
            # Rigs, linked planes and independent GP Drawing Planes can all use
            # the visual collection name without being physically linked below
            # that Blender Collection. Keep every cached owner hint in sync.
            for obj in iter_scene_fbp_rigs(context.scene):
                try:
                    if getattr(obj, 'fbp_collection_name', '') == old_name:
                        obj.fbp_collection_name = coll.name
                    plane = getattr(obj, 'fbp_plane_target', None)
                    if plane and getattr(plane, 'fbp_collection_name', '') == old_name:
                        plane.fbp_collection_name = coll.name
                except FBP_DATA_IO_ERRORS:
                    pass
            try:
                from .fbp_index import iter_scene_gp_canvases
                from .grease_pencil_bridge import is_gp_drawing_canvas
                for canvas in iter_scene_gp_canvases(context.scene, kind='DRAWING', fallback=True):
                    if is_gp_drawing_canvas(canvas) and getattr(canvas, 'fbp_collection_name', '') == old_name:
                        canvas.fbp_collection_name = coll.name
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
                _fbp_refresh_layer_tree(context)
            return {'FINISHED'}

        if self.target_type == 'PENDING_GROUP':
            old_path = self.collection_name
            parent = old_path.rsplit(' / ', 1)[0] if ' / ' in old_path else ''
            new_path = f"{parent} / {new_name}" if parent else new_name
            for item in context.scene.fbp_pending_planes:
                path = str(getattr(item, 'collection_name', '') or '')
                if path == old_path or path.startswith(old_path + ' / '):
                    item.collection_name = new_path + path[len(old_path):]
            _fbp_refresh_pending_tree(context)
            return {'FINISHED'}

        return {'CANCELLED'}

    def _select(self, context):
        if self.target_type != 'COLLECTION':
            _fbp_clear_collection_row_selection_guard()
        if self.target_type == 'LAYER':
            rig = bpy.data.objects.get(self.rig_name)
            if not rig or not is_fbp_layer_object(rig):
                return {'CANCELLED'}
            if not object_in_view_layer(rig, context) and not ensure_object_in_active_collection(rig, context):
                return {'CANCELLED'}
            scene = context.scene
            current_index = self.tree_index if self.tree_index >= 0 else self.index
            list_mode = _fbp_normalize_layer_list_mode(self.list_mode)
            anchor_key = _fbp_layer_selection_anchor_key(list_mode)
            using_tree = self.tree_index >= 0
            anchor = (
                _fbp_resolve_layer_selection_anchor(scene, current_index, list_mode)
                if using_tree else int(transient_get(scene, anchor_key, current_index))
            )
            targets = [rig]
            if self.use_shift and current_index >= 0:
                if using_tree:
                    targets = _fbp_tree_selection_targets(
                        scene, anchor, current_index, list_mode
                    )
                else:
                    items = tuple(getattr(scene, "fbp_layers", ()) or ())
                    lo, hi = sorted((max(0, anchor), min(current_index, len(items) - 1)))
                    targets = [
                        candidate
                        for candidate in (_safe_layer_obj(item) for item in items[lo:hi + 1])
                        if candidate is not None and is_fbp_layer_object(candidate)
                    ]
            if not self.use_ctrl:
                _fbp_deselect_layer_objects(context)
            if self.use_ctrl and not self.use_shift:
                try:
                    rig.select_set(not rig.select_get())
                except FBP_DATA_IO_ERRORS:
                    return {'CANCELLED'}
            else:
                for candidate in targets:
                    try:
                        if object_in_view_layer(candidate, context):
                            candidate.select_set(True)
                    except FBP_DATA_IO_ERRORS:
                        pass
            selected = tuple(getattr(context, "selected_objects", ()) or ())
            if rig.select_get():
                context.view_layer.objects.active = rig
            elif selected:
                context.view_layer.objects.active = selected[-1]
            if not self.use_shift and current_index >= 0:
                if using_tree:
                    _fbp_store_layer_selection_anchor(scene, current_index, list_mode)
                else:
                    transient_set(scene, anchor_key, int(current_index))
            for i, item in enumerate(context.scene.fbp_layers):
                try:
                    if item.obj == rig:
                        context.scene.fbp_layer_stack_index = i
                        break
                except ReferenceError:
                    pass
            if self.tree_index >= 0:
                context.scene.fbp_layer_tree_rows_idx = self.tree_index
                return {'FINISHED'}

        if self.target_type == 'GP_CANVAS':
            canvas = bpy.data.objects.get(self.rig_name)
            try:
                from .grease_pencil_bridge import is_gp_canvas
                if not is_gp_canvas(canvas):
                    return {'CANCELLED'}
                if not object_in_view_layer(canvas, context) and not ensure_object_in_active_collection(canvas, context):
                    return {'CANCELLED'}
                scene = context.scene
                current_index = self.tree_index if self.tree_index >= 0 else self.index
                list_mode = _fbp_normalize_layer_list_mode(self.list_mode)
                anchor_key = _fbp_layer_selection_anchor_key(list_mode)
                using_tree = self.tree_index >= 0
                anchor = (
                    _fbp_resolve_layer_selection_anchor(scene, current_index, list_mode)
                    if using_tree else int(transient_get(scene, anchor_key, current_index))
                )
                targets = [canvas]
                if self.use_shift and using_tree:
                    targets = _fbp_tree_selection_targets(
                        scene, anchor, current_index, list_mode
                    )
                if not self.use_ctrl:
                    _fbp_deselect_layer_objects(context)
                previous_canvas_state = bool(canvas.select_get())
                for candidate in targets:
                    candidate.hide_set(False)
                    if hasattr(candidate, "fbp_gp_canvas_visible"):
                        candidate.fbp_gp_canvas_visible = True
                    candidate.select_set(True)
                if self.use_ctrl and not self.use_shift:
                    canvas.select_set(not previous_canvas_state)
                if canvas.select_get():
                    context.view_layer.objects.active = canvas
                if not self.use_shift and current_index >= 0:
                    if using_tree:
                        _fbp_store_layer_selection_anchor(scene, current_index, list_mode)
                    else:
                        transient_set(scene, anchor_key, current_index)
                if self.tree_index >= 0:
                    context.scene.fbp_layer_tree_rows_idx = self.tree_index
                return {'FINISHED'}
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                return {'CANCELLED'}

        if self.target_type == 'FRAME':
            rig = bpy.data.objects.get(self.rig_name)
            if not rig or not (0 <= self.index < len(rig.fbp_images)):
                return {'CANCELLED'}
            anchor_key = "_fbp_frame_selection_anchor"
            anchor = int(transient_get(rig, anchor_key, self.index))
            lo, hi = sorted((max(0, anchor), min(self.index, len(rig.fbp_images) - 1)))
            for i, item in enumerate(rig.fbp_images):
                if self.use_shift:
                    item.is_selected = bool(item.is_selected) if self.use_ctrl else (lo <= i <= hi)
                    if lo <= i <= hi:
                        item.is_selected = True
                elif self.use_ctrl:
                    if i == self.index:
                        item.is_selected = not bool(item.is_selected)
                else:
                    item.is_selected = (i == self.index)
            if not self.use_shift:
                transient_set(rig, anchor_key, int(self.index))
            rig.fbp_images_index = self.index
            fbp_jump_timeline_to_sequence_row(context, rig, self.index)
            if object_in_view_layer(rig, context):
                _fbp_deselect_layer_objects(context)
                rig.select_set(True)
                context.view_layer.objects.active = rig
            if getattr(rig, 'fbp_is_color_plane', False):
                fbp_load_active_procedural_frame_to_rig(rig)
            do_update_animation(rig)
            return {'FINISHED'}

        if self.target_type == 'PENDING':
            items = context.scene.fbp_pending_planes
            if not (0 <= self.index < len(items)):
                return {'CANCELLED'}
            using_tree = self.tree_index >= 0
            anchor_key = (
                "_fbp_pending_tree_selection_anchor"
                if using_tree else "_fbp_pending_selection_anchor"
            )
            current_index = self.tree_index if using_tree else self.index
            anchor = int(transient_get(context.scene, anchor_key, current_index))
            if self.use_shift and using_tree:
                rows = tuple(getattr(context.scene, "fbp_pending_tree_rows", ()) or ())
                lo, hi = sorted((max(0, anchor), min(current_index, len(rows) - 1)))
                selected_range = {
                    int(getattr(tree_row, "pending_index", -1))
                    for tree_row in rows[lo:hi + 1]
                    if str(getattr(tree_row, "row_type", "") or "") == 'LAYER'
                }
            else:
                lo, hi = sorted((max(0, anchor), min(self.index, len(items) - 1)))
                selected_range = set(range(lo, hi + 1))
            for i, item in enumerate(items):
                if self.use_shift:
                    item.is_selected = bool(item.is_selected) if self.use_ctrl else (i in selected_range)
                    if i in selected_range:
                        item.is_selected = True
                elif self.use_ctrl:
                    if i == self.index:
                        item.is_selected = not bool(item.is_selected)
                else:
                    item.is_selected = (i == self.index)
            context.scene.fbp_pending_planes_idx = self.index
            if not self.use_shift:
                transient_set(context.scene, anchor_key, int(current_index))
            if self.tree_index >= 0:
                context.scene.fbp_pending_tree_rows_idx = self.tree_index
            return {'FINISHED'}

        if self.target_type == 'COLLECTION':
            coll = bpy.data.collections.get(self.collection_name)
            if not coll:
                return {'CANCELLED'}
            try:
                scene = context.scene
                current_index = self.tree_index if self.tree_index >= 0 else self.index
                _fbp_arm_collection_row_selection_guard(scene, coll.name, current_index)
                list_mode = _fbp_normalize_layer_list_mode(self.list_mode)
                anchor_key = _fbp_layer_selection_anchor_key(list_mode)
                using_tree = self.tree_index >= 0
                anchor = (
                    _fbp_resolve_layer_selection_anchor(scene, current_index, list_mode)
                    if using_tree else int(transient_get(scene, anchor_key, current_index))
                )
                targets = []
                if list_mode != 'GP':
                    targets.extend(_collection_rigs_for_ui(coll))
                if list_mode != 'PLANES':
                    targets.extend(_collection_gp_canvases_for_ui(coll))
                if self.use_shift and using_tree:
                    targets = _fbp_tree_selection_targets(
                        scene, anchor, current_index, list_mode
                    )
                _fbp_ensure_object_mode(context)
                if not self.use_ctrl:
                    _fbp_deselect_layer_objects(context)
                live_targets = [
                    member for member in targets
                    if object_in_view_layer(member, context)
                    and not bool(getattr(member, "hide_select", False))
                ]
                toggle_to = (
                    not all(member.select_get() for member in live_targets)
                    if self.use_ctrl and not self.use_shift else True
                )
                selected = []
                for member in live_targets:
                    member.select_set(toggle_to)
                    if toggle_to:
                        selected.append(member)
                if selected:
                    context.view_layer.objects.active = selected[-1]
                    selected_keys = {int(rig.as_pointer()) for rig in selected}
                    for i, item in enumerate(context.scene.fbp_layers):
                        rig = _safe_layer_obj(item)
                        if rig and int(rig.as_pointer()) in selected_keys:
                            context.scene.fbp_layer_stack_index = i
                            break
                if not self.use_shift and current_index >= 0:
                    if using_tree:
                        _fbp_store_layer_selection_anchor(scene, current_index, list_mode)
                    else:
                        transient_set(scene, anchor_key, current_index)
            except FBP_DATA_IO_ERRORS:
                pass
            if self.tree_index >= 0:
                context.scene.fbp_layer_tree_rows_idx = self.tree_index
                return {'FINISHED'}

        if self.target_type == 'PENDING_GROUP':
            path = str(self.collection_name or "")
            members = [
                item for item in context.scene.fbp_pending_planes
                if str(getattr(item, "collection_name", "") or "") == path
                or str(getattr(item, "collection_name", "") or "").startswith(path + " / ")
            ]
            if members:
                target_state = not all(bool(item.is_selected) for item in members)
                if not self.use_ctrl:
                    for item in context.scene.fbp_pending_planes:
                        item.is_selected = False
                    target_state = True
                for item in members:
                    item.is_selected = target_state
            if self.tree_index >= 0:
                context.scene.fbp_pending_tree_rows_idx = self.tree_index
                if not self.use_shift:
                    transient_set(context.scene, "_fbp_pending_tree_selection_anchor", self.tree_index)
            return {'FINISHED'}

        return {'CANCELLED'}

    def execute(self, context):
        return self._rename(context) if self.rename_mode else self._select(context)

class FBP_OT_SelectLayerExclusive(Operator):
    bl_idname      = "fbp.select_layer_exclusive"
    bl_label       = "Select Layer"
    bl_description = "Select only this layer. Use the checkbox for additive multi-selection"
    bl_options     = {'UNDO'}

    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", default="")

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not is_fbp_layer_object(rig):
            return {'CANCELLED'}

        if not object_in_view_layer(rig, context):
            if not ensure_object_in_active_collection(rig, context):
                sync_layer_collection(context)
                self.report({'WARNING'}, "Layer is not in the active View Layer")
                return {'CANCELLED'}

        _fbp_deselect_layer_objects(context)
        rig.select_set(True)
        context.view_layer.objects.active = rig

        for i, item in enumerate(context.scene.fbp_layers):
            try:
                if item.obj == rig:
                    context.scene.fbp_layer_stack_index = i
                    break
            except ReferenceError:
                pass
        return {'FINISHED'}

class FBP_OT_DuplicateOrDefault(Operator):
    bl_idname      = "fbp.duplicate_or_default"
    bl_label       = "Duplicate"
    bl_description = "Shift+D: duplicate FBP rigs safely, otherwise use Blender's standard duplicate"
    bl_options     = {'UNDO'}

    def invoke(self, context, event):
        if get_selected_fbp_roots(context):
            result = bpy.ops.fbp.duplicate_selected_layers()
            if 'FINISHED' in result:
                return bpy.ops.transform.translate('INVOKE_DEFAULT')
            return result
        return bpy.ops.object.duplicate_move('INVOKE_DEFAULT')

def _fbp_groupable_shortcut_targets(context):
    """Return selected FBP rigs and Drawing Plane canvases for shortcut routing."""
    targets = []
    seen = set()
    for rig in get_selected_fbp_roots(context):
        if rig is None or not is_fbp_layer_object(rig):
            continue
        try:
            key = int(rig.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(rig)
        if key not in seen:
            seen.add(key)
            targets.append(rig)
    for obj in tuple(getattr(context, 'selected_objects', ()) or ()):
        if obj is None or not _fbp_is_gp_drawing_canvas_object(obj):
            continue
        try:
            key = int(obj.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(obj)
        if key not in seen:
            seen.add(key)
            targets.append(obj)
    return tuple(targets)


class FBP_OT_GroupOrPass(Operator):
    bl_idname = "fbp.group_or_pass"
    bl_label = "Move Layers to Collection"
    bl_description = "Create one Blender Collection for the selected Frame By Plane layers, or an empty collection at the active Layer List location"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return bpy.ops.fbp.create_layer_collection('EXEC_DEFAULT')

    def execute(self, context):
        return bpy.ops.fbp.create_layer_collection('EXEC_DEFAULT')


class FBP_OT_UngroupOrPass(Operator):
    bl_idname = "fbp.ungroup_or_pass"
    bl_label = "Move Layers Out of Collection"
    bl_description = "Move selected Frame By Plane layers to the parent Collection; pass through when no nested layer is selected"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        targets = _fbp_groupable_shortcut_targets(context)
        if not targets:
            return {'PASS_THROUGH'}
        if not any(str(getattr(target, 'fbp_collection_name', '') or '') for target in targets):
            return {'PASS_THROUGH'}
        return bpy.ops.fbp.ungroup_selected_layers('EXEC_DEFAULT')


class FBP_OT_SelectAllLayers(Operator):
    bl_idname      = "fbp.select_all_layers"
    bl_label       = "Select All Layers"
    bl_description = "Select all Frame By Plane rigs in the scene"

    def execute(self, context):
        _fbp_deselect_layer_objects(context)
        count = 0
        for idx in visible_layer_indices(context):
            item = context.scene.fbp_layers[idx]
            obj = _safe_layer_obj(item)
            if obj and is_fbp_layer_object(obj):
                obj.select_set(True)
                context.view_layer.objects.active = obj
                count += 1
        self.report({'INFO'}, f"{count} layers selected")
        return {'FINISHED'}

class FBP_OT_ToggleLock(Operator):
    bl_idname      = "fbp.toggle_lock"
    bl_label       = "Toggle Lock"
    bl_description = "Toggle object selectability in viewport. Shift+Click to apply to all selected"
    bl_options     = {'UNDO'}

    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", default="")
    target:   StringProperty(description="Target component affected by this operation, such as the Frame By Plane rig or its linked plane.", default="RIG")
    shift:    BoolProperty(description="Whether the action was invoked with Shift to apply it additively or to all currently selected Frame By Plane layers.", default=False)

    def invoke(self, context, event):
        self.shift = event.shift
        return self.execute(context)

    def execute(self, context):
        rigs = (get_selected_rigs(context) if self.shift
                else ([bpy.data.objects.get(self.rig_name)] if self.rig_name
                      else get_selected_rigs(context)))
        for rig in rigs:
            if not rig:
                continue
            if self.target == 'RIG':
                rig.hide_select = not rig.hide_select
            elif self.target == 'PLANE':
                plane = rig.fbp_plane_target
                if plane:
                    plane.hide_select = not plane.hide_select
        return {'FINISHED'}

class FBP_OT_ToggleSelectLayer(Operator):
    bl_idname      = "fbp.toggle_select_layer"
    bl_label       = "Toggle Layer Selection"
    bl_description = "Add or remove this layer from the selection"
    bl_options     = {'UNDO'}

    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.")

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if rig:
            new_state = not rig.select_get()
            rig.select_set(new_state)
            if new_state:
                context.view_layer.objects.active = rig
        return {'FINISHED'}

class FBP_OT_ToggleSolo(Operator):
    bl_idname      = "fbp.toggle_solo"
    bl_label       = "Solo Layer"
    bl_description = "Isolate this layer. Click others to add them to the view"
    bl_options     = {'UNDO'}

    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.")

    def execute(self, context):
        sc = context.scene
        target_item = next(
            (item for item in sc.fbp_layers if item.obj and item.obj.name == self.rig_name),
            None)
        if not target_item:
            return {'CANCELLED'}

        active_items = [item for item in sc.fbp_layers if item.solo]

        if not active_items:
            for item in sc.fbp_layers:
                item.solo = False
                if item.obj:
                    fbp_set_rna_property_silent(item.obj, 'fbp_is_visible', False)
            target_item.solo = True
            if target_item.obj:
                fbp_set_rna_property_silent(target_item.obj, 'fbp_is_visible', True)
        elif len(active_items) == 1 and target_item.solo:
            for item in sc.fbp_layers:
                item.solo = False
                if item.obj:
                    fbp_set_rna_property_silent(item.obj, 'fbp_is_visible', True)
        else:
            target_item.solo = not target_item.solo
            if target_item.obj:
                fbp_set_rna_property_silent(
                    target_item.obj,
                    'fbp_is_visible',
                    target_item.solo,
                )

        if not any(item.solo for item in sc.fbp_layers):
            for item in sc.fbp_layers:
                if item.obj:
                    fbp_set_rna_property_silent(item.obj, 'fbp_is_visible', True)

        update_global_visibility(context)
        _fbp_refresh_layer_tree(context)
        return {'FINISHED'}

def _fbp_active_tree_row(scene):
    try:
        rows = getattr(scene, "fbp_layer_tree_rows", ())
        index = int(getattr(scene, "fbp_layer_tree_rows_idx", -1))
        if 0 <= index < len(rows):
            return rows[index], index
    except FBP_DATA_ERRORS:
        pass
    return None, -1


def _fbp_resolve_tree_stack_object(row):
    if row is None:
        return None, ""
    row_type = str(getattr(row, "row_type", "") or "")
    if row_type == "GP_CANVAS":
        canvas = bpy.data.objects.get(str(getattr(row, "canvas_name", "") or getattr(row, "name", "") or ""))
        try:
            from .grease_pencil_bridge import is_gp_drawing_canvas
            if is_gp_drawing_canvas(canvas):
                return canvas, "GP_CANVAS"
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return None, ""
    if row_type == "LAYER":
        rig = bpy.data.objects.get(str(getattr(row, "rig_name", "") or getattr(row, "name", "") or ""))
        if rig and is_fbp_layer_object(rig):
            return rig, "LAYER"
    return None, ""


def _fbp_stack_object_collection(obj, scene=None):
    collection = get_primary_fbp_collection(obj)
    try:
        from .grease_pencil_bridge import gp_canvas_owner, is_gp_drawing_canvas
        if is_gp_drawing_canvas(obj) and str(getattr(collection, "name", "") or "") == "FBP Grease Pencil":
            owner_collection = get_primary_fbp_collection(gp_canvas_owner(obj))
            if owner_collection is not None:
                return owner_collection
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    if collection is not None:
        return collection
    try:
        user_collections = tuple(getattr(obj, "users_collection", ()) or ())
        return user_collections[0] if user_collections else getattr(scene, "collection", None)
    except FBP_DATA_ERRORS:
        return getattr(scene, "collection", None) if scene is not None else None


def _fbp_is_gp_drawing_canvas_object(obj):
    try:
        from .grease_pencil_bridge import is_gp_drawing_canvas
        return bool(is_gp_drawing_canvas(obj))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_prepare_stack_depth_object(obj):
    if _fbp_is_gp_drawing_canvas_object(obj):
        try:
            from .grease_pencil_bridge import make_drawing_canvas_stack_editable
            make_drawing_canvas_stack_editable(obj)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass


def _fbp_unique_collection_name(base_name):
    base = str(base_name or "FBP Collection").strip() or "FBP Collection"
    if bpy.data.collections.get(base) is None:
        return base
    index = 1
    while bpy.data.collections.get(f"{base}.{index:03d}") is not None:
        index += 1
    return f"{base}.{index:03d}"


def _fbp_canonical_collection_parent(scene, target):
    """Return the parent used by the canonical Layer List hierarchy."""
    if scene is None or target is None:
        return None
    try:
        tree = fbp_build_canonical_collection_tree(scene)
        try:
            target_key = int(target.as_pointer())
        except FBP_DATA_ERRORS:
            target_key = id(target)
        parent_key = (tree.get("parent_by_key", {}) or {}).get(target_key)
        return (tree.get("collections", {}) or {}).get(parent_key)
    except FBP_DATA_ERRORS:
        return None


def _fbp_collection_parents(root, target):
    """Return every scene-tree parent that directly links ``target``."""
    if root is None or target is None or root == target:
        return []
    result = []
    seen = set()
    stack = [root]
    while stack:
        parent = stack.pop()
        if parent is None:
            continue
        try:
            key = int(parent.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(parent)
        if key in seen:
            continue
        seen.add(key)
        try:
            children = tuple(getattr(parent, "children", ()) or ())
        except FBP_DATA_ERRORS:
            children = ()
        if target in children:
            result.append(parent)
        stack.extend(children)
    return result


def _fbp_collection_contains(root, target):
    """Return whether ``target`` is nested anywhere below ``root``."""
    if root is None or target is None:
        return False
    seen = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current is None:
            continue
        if current == target:
            return True
        try:
            key = int(current.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(current)
        if key in seen:
            continue
        seen.add(key)
        try:
            stack.extend(tuple(getattr(current, "children", ()) or ()))
        except FBP_DATA_ERRORS:
            pass
    return False


def _fbp_collection_tree_row(scene, collection_name=""):
    """Resolve one visible GROUP row and its index from name or active row."""
    try:
        rows = getattr(scene, "fbp_layer_tree_rows", ()) or ()
        requested = str(collection_name or "")
        if requested:
            for index, row in enumerate(rows):
                if (
                    str(getattr(row, "row_type", "") or "") == "GROUP"
                    and str(getattr(row, "collection_name", "") or "") == requested
                ):
                    return row, index
        index = int(getattr(scene, "fbp_layer_tree_rows_idx", -1))
        if 0 <= index < len(rows):
            row = rows[index]
            if str(getattr(row, "row_type", "") or "") == "GROUP":
                return row, index
    except FBP_DATA_ERRORS:
        pass
    return None, -1


def _fbp_tree_parent_collection(scene, row_index):
    """Resolve the displayed parent collection of a flattened tree row."""
    try:
        rows = getattr(scene, "fbp_layer_tree_rows", ()) or ()
        if not (0 <= int(row_index) < len(rows)):
            return None, -1
        depth = int(getattr(rows[int(row_index)], "depth", 0) or 0)
        if depth <= 0:
            return getattr(scene, "collection", None), -1
        for index in range(int(row_index) - 1, -1, -1):
            row = rows[index]
            row_depth = int(getattr(row, "depth", 0) or 0)
            if row_depth < depth - 1:
                break
            if (
                row_depth == depth - 1
                and str(getattr(row, "row_type", "") or "") == "GROUP"
            ):
                name = str(getattr(row, "collection_name", "") or "")
                return bpy.data.collections.get(name), index
    except FBP_DATA_ERRORS:
        pass
    return None, -1


_FBP_LAYER_REORDER_PREVIEW_KEY = "fbp.layer_reorder_preview"


def _fbp_tree_row_visible_for_mode(row, mode):
    row_type = str(getattr(row, "row_type", "") or "")
    mode = str(mode or "ALL").upper()
    if mode == "ALL":
        return True
    if row_type == "GROUP":
        domain = str(getattr(row, "list_domain", "PLANES") or "PLANES").upper()
        if domain != mode:
            return False
        count = (
            int(getattr(row, "layer_count", 0) or 0)
            if mode == "PLANES"
            else int(getattr(row, "gp_count", 0) or 0)
        )
        return count > 0 or bool(getattr(row, "empty_managed_path", False))
    if mode == "PLANES":
        return row_type == "LAYER"
    if mode == "GP":
        return row_type in {"GP_CANVAS", "GP_LAYER"}
    return False


def _fbp_row_source_type(row):
    row_type = str(getattr(row, "row_type", "") or "").upper()
    if row_type == "GROUP":
        return "COLLECTION"
    if row_type == "GP_CANVAS":
        return "GP_CANVAS"
    if row_type == "LAYER":
        return "LAYER"
    return ""


def _fbp_row_source_name(row):
    source_type = _fbp_row_source_type(row)
    if source_type == "COLLECTION":
        return str(getattr(row, "collection_name", "") or "")
    if source_type == "GP_CANVAS":
        return str(getattr(row, "canvas_name", "") or getattr(row, "name", "") or "")
    if source_type == "LAYER":
        return str(getattr(row, "rig_name", "") or getattr(row, "name", "") or "")
    return ""


def _fbp_row_token(row):
    source_type = _fbp_row_source_type(row)
    source_name = _fbp_row_source_name(row)
    return f"{source_type}:{source_name}" if source_type and source_name else ""


def _fbp_visible_tree_row_snapshots(scene, mode):
    """Return primitive visible-row snapshots without retaining RNA wrappers."""
    snapshots = []
    try:
        rows = tuple(getattr(scene, "fbp_layer_tree_rows", ()) or ())
    except FBP_DATA_ERRORS:
        rows = ()
    for tree_index, row in enumerate(rows):
        if not _fbp_tree_row_visible_for_mode(row, mode):
            continue
        source_type = _fbp_row_source_type(row)
        if not source_type:
            continue
        snapshots.append({
            "tree_index": int(tree_index),
            "source_type": source_type,
            "source_name": _fbp_row_source_name(row),
            "token": _fbp_row_token(row),
            "row_type": str(getattr(row, "row_type", "") or ""),
            "collection_name": str(getattr(row, "collection_name", "") or ""),
            "depth": int(getattr(row, "depth", 0) or 0),
        })
    return snapshots


def _fbp_collection_parent_name(scene, collection_name):
    collection = bpy.data.collections.get(str(collection_name or ""))
    parent = _fbp_canonical_collection_parent(scene, collection)
    root = getattr(scene, "collection", None)
    return "" if parent is None or parent == root else str(getattr(parent, "name", "") or "")


def _fbp_snapshot_parent_name(scene, snapshot):
    if not snapshot:
        return ""
    source_type = str(snapshot.get("source_type", "") or "")
    if source_type == "COLLECTION":
        return _fbp_collection_parent_name(scene, snapshot.get("source_name", ""))
    collection_name = str(snapshot.get("collection_name", "") or "")
    root = getattr(scene, "collection", None)
    collection = bpy.data.collections.get(collection_name) if collection_name else None
    return "" if collection is None or collection == root else collection_name


def _fbp_preview_destination_parent(scene, before_row, after_row):
    """Infer the parent at one flattened insertion boundary."""
    if after_row:
        if str(after_row.get("source_type", "")) == "COLLECTION":
            return _fbp_collection_parent_name(scene, after_row.get("source_name", ""))
        return _fbp_snapshot_parent_name(scene, after_row)
    if before_row:
        if str(before_row.get("source_type", "")) == "COLLECTION":
            return str(before_row.get("source_name", "") or "")
        return _fbp_snapshot_parent_name(scene, before_row)
    return ""


def _fbp_visible_tree_display_snapshots(scene, mode):
    """Return every visible row as primitives, including non-draggable GP children."""
    snapshots = []
    try:
        rows = tuple(getattr(scene, "fbp_layer_tree_rows", ()) or ())
    except FBP_DATA_ERRORS:
        rows = ()
    for tree_index, row in enumerate(rows):
        if not _fbp_tree_row_visible_for_mode(row, mode):
            continue
        row_type = str(getattr(row, "row_type", "") or "").upper()
        source_type = _fbp_row_source_type(row)
        source_name = _fbp_row_source_name(row)
        token = (
            f"{source_type}:{source_name}"
            if source_type and source_name
            else f"ROW:{int(tree_index)}"
        )
        snapshots.append({
            "tree_index": int(tree_index),
            "source_type": source_type or row_type,
            "source_name": source_name,
            "token": token,
            "row_type": row_type,
            "collection_name": str(getattr(row, "collection_name", "") or ""),
            "depth": max(0, int(getattr(row, "depth", 0) or 0)),
        })
    return snapshots


def _fbp_preview_row_overrides(scene, mode, preview):
    """Build a shadow flattened tree without mutating the UIList CollectionProperty."""
    rows = _fbp_visible_tree_display_snapshots(scene, mode)
    if not rows:
        return {}

    roots = []
    last_at_depth = {}
    all_nodes = []
    for snapshot in rows:
        depth = max(0, int(snapshot.get("depth", 0) or 0))
        node = {"snapshot": snapshot, "children": [], "parent_children": None}
        parent = last_at_depth.get(depth - 1) if depth > 0 else None
        parent_children = parent["children"] if parent is not None else roots
        parent_children.append(node)
        node["parent_children"] = parent_children
        all_nodes.append(node)
        last_at_depth[depth] = node
        for stale_depth in tuple(last_at_depth):
            if stale_depth > depth:
                last_at_depth.pop(stale_depth, None)

    source_type = str(preview.get("source_type", "") or "").upper()
    source_name = str(preview.get("source_name", "") or "")
    source_node = next((
        node for node in all_nodes
        if str(node["snapshot"].get("source_type", "") or "").upper() == source_type
        and str(node["snapshot"].get("source_name", "") or "") == source_name
    ), None)
    if source_node is None:
        return {}

    destination_name = str(preview.get("destination_parent", "") or "")
    destination_node = None
    if destination_name:
        destination_node = next((
            node for node in all_nodes
            if str(node["snapshot"].get("source_type", "") or "").upper() == "COLLECTION"
            and str(node["snapshot"].get("source_name", "") or "") == destination_name
        ), None)
        if destination_node is None:
            return {}

    def contains(root_node, candidate):
        if root_node is candidate:
            return True
        return any(contains(child, candidate) for child in root_node["children"])

    if destination_node is not None and contains(source_node, destination_node):
        return {}

    source_parent_children = source_node.get("parent_children")
    if source_parent_children is None or source_node not in source_parent_children:
        return {}
    source_parent_children.remove(source_node)

    destination_children = destination_node["children"] if destination_node is not None else roots
    before_token = str(preview.get("before_token", "") or "")
    after_token = str(preview.get("after_token", "") or "")
    insert_at = len(destination_children)
    if before_token:
        for index, node in enumerate(destination_children):
            if str(node["snapshot"].get("token", "") or "") == before_token:
                insert_at = index
                break
    elif after_token:
        for index, node in enumerate(destination_children):
            if str(node["snapshot"].get("token", "") or "") == after_token:
                insert_at = index + 1
                break
    destination_children.insert(max(0, min(insert_at, len(destination_children))), source_node)
    source_node["parent_children"] = destination_children

    flattened = []
    def flatten(nodes, depth=0):
        for node in nodes:
            flattened.append((node, depth))
            flatten(node["children"], depth + 1)
    flatten(roots)
    if len(flattened) != len(rows):
        return {}

    overrides = {}
    for slot, (node, depth) in zip(rows, flattened):
        overrides[str(int(slot["tree_index"]))] = {
            "source_tree_index": int(node["snapshot"]["tree_index"]),
            "depth": int(depth),
        }
    return overrides


def _fbp_set_layer_reorder_preview(
    context,
    *,
    mode,
    source_type,
    source_name,
    destination_parent,
    before_token="",
    after_token="",
):
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    preview = {
        "mode": str(mode or "PLANES").upper(),
        "source_type": str(source_type or "").upper(),
        "source_name": str(source_name or ""),
        "destination_parent": str(destination_parent or ""),
        "before_token": str(before_token or ""),
        "after_token": str(after_token or ""),
    }
    if not preview["source_type"] or not preview["source_name"]:
        return False
    preview["row_overrides"] = _fbp_preview_row_overrides(
        scene, preview["mode"], preview
    )
    if not preview["row_overrides"]:
        return False
    previous = transient_get(scene, _FBP_LAYER_REORDER_PREVIEW_KEY, None)
    if previous == preview:
        return True
    transient_set(scene, _FBP_LAYER_REORDER_PREVIEW_KEY, preview)
    return True


def _fbp_clear_layer_reorder_preview(context, *, refresh=False):
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    removed = transient_pop(scene, _FBP_LAYER_REORDER_PREVIEW_KEY)
    if refresh:
        try:
            scene.fbp_layer_tree_signature = ""
        except FBP_DATA_IO_ERRORS:
            pass
        _fbp_refresh_layer_tree(context, update_compositor=False)
    return bool(removed)


def _fbp_prepare_layer_reorder_preview(
    context,
    *,
    source_type,
    source_name,
    tree_index,
    mode,
    delta_x,
    delta_y,
    threshold,
):
    """Convert one completed drag gesture into a primitive visual proposal."""
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    mode = str(mode or "PLANES").upper()
    source_type = str(source_type or "").upper()
    source_name = str(source_name or "")
    snapshots = _fbp_visible_tree_row_snapshots(scene, mode)
    source_index = -1
    for index, snapshot in enumerate(snapshots):
        if (
            snapshot.get("source_type") == source_type
            and snapshot.get("source_name") == source_name
        ):
            source_index = index
            break
        if int(snapshot.get("tree_index", -1)) == int(tree_index):
            source_index = index
    if source_index < 0:
        return False

    source_snapshot = snapshots[source_index]
    remaining = snapshots[:source_index] + snapshots[source_index + 1:]
    try:
        steps = int(float(delta_y) / max(1, int(threshold)))
    except (TypeError, ValueError, OverflowError):
        steps = 0
    insertion_index = max(0, min(source_index - steps, len(remaining)))
    before_row = remaining[insertion_index - 1] if insertion_index > 0 else None
    after_row = remaining[insertion_index] if insertion_index < len(remaining) else None

    destination_parent = _fbp_preview_destination_parent(scene, before_row, after_row)
    # Stored names describe the operation, not the neighbour direction:
    # ``before_token`` means insert before the following row, while
    # ``after_token`` means insert after the preceding row.
    before_token = str((after_row or {}).get("token", "") or "")
    after_token = str((before_row or {}).get("token", "") or "")

    try:
        horizontal = abs(int(delta_x)) >= max(1, int(threshold))
    except (TypeError, ValueError, OverflowError):
        horizontal = False
    if steps == 0 and not horizontal:
        _fbp_clear_layer_reorder_preview(context)
        return False

    if horizontal and int(delta_x) < 0:
        current_parent_name = _fbp_snapshot_parent_name(scene, source_snapshot)
        if current_parent_name:
            destination_parent = _fbp_collection_parent_name(scene, current_parent_name)
            before_token = ""
            after_token = f"COLLECTION:{current_parent_name}"
    elif horizontal and int(delta_x) > 0:
        candidate = None
        for snapshot in (after_row, before_row):
            if snapshot and snapshot.get("source_type") == "COLLECTION":
                candidate = str(snapshot.get("source_name", "") or "")
                break
        if not candidate:
            for snapshot in reversed(remaining[:insertion_index]):
                if snapshot.get("source_type") == "COLLECTION":
                    candidate = str(snapshot.get("source_name", "") or "")
                    break
        if candidate:
            destination_parent = candidate
            before_token = ""
            after_token = ""

    # Anchors must be direct children/items of the proposed parent. Remove any
    # flattened descendant anchor that the cache could not resolve directly.
    if after_row and _fbp_snapshot_parent_name(scene, after_row) != destination_parent:
        before_token = ""
    if before_row and _fbp_snapshot_parent_name(scene, before_row) != destination_parent:
        after_token = ""

    if source_type == "COLLECTION":
        source_collection = bpy.data.collections.get(source_name)
        destination_collection = (
            bpy.data.collections.get(destination_parent)
            if destination_parent else getattr(scene, "collection", None)
        )
        if (
            source_collection is None
            or destination_collection is None
            or source_collection == destination_collection
            or _fbp_collection_contains(source_collection, destination_collection)
        ):
            _fbp_clear_layer_reorder_preview(context)
            return False

    return _fbp_set_layer_reorder_preview(
        context,
        mode=mode,
        source_type=source_type,
        source_name=source_name,
        destination_parent=destination_parent,
        before_token=before_token,
        after_token=after_token,
    )


def _fbp_previous_sibling_collection(scene, row_index, list_mode="ALL"):
    """Return the visible collection immediately above at the same tree level."""
    try:
        rows = getattr(scene, "fbp_layer_tree_rows", ()) or ()
        if not (0 <= int(row_index) < len(rows)):
            return None
        current_row = rows[int(row_index)]
        depth = int(getattr(current_row, "depth", 0) or 0)
        current_name = str(getattr(current_row, "collection_name", "") or "")
        current_collection = bpy.data.collections.get(current_name)
        current_parent = _fbp_canonical_collection_parent(scene, current_collection)
        for index in range(int(row_index) - 1, -1, -1):
            row = rows[index]
            row_depth = int(getattr(row, "depth", 0) or 0)
            if row_depth < depth:
                break
            if (
                row_depth == depth
                and str(getattr(row, "row_type", "") or "") == "GROUP"
                and _fbp_tree_row_visible_for_mode(row, list_mode)
            ):
                name = str(getattr(row, "collection_name", "") or "")
                candidate = bpy.data.collections.get(name)
                if candidate is None:
                    continue
                if _fbp_canonical_collection_parent(scene, candidate) == current_parent:
                    return candidate
    except FBP_DATA_ERRORS:
        pass
    return None
def _fbp_relink_collection(scene, collection, destination):
    """Relink one collection atomically to exactly one Scene-tree parent."""
    root = getattr(scene, "collection", None)
    if root is None or collection is None or destination is None:
        return False
    if collection == root or collection == destination:
        return False
    if destination != root and not _fbp_collection_contains(root, destination):
        return False
    if not _fbp_collection_contains(root, collection):
        return False
    if _fbp_collection_contains(collection, destination):
        return False

    parents = _fbp_collection_parents(root, collection)
    if len(parents) == 1 and parents[0] == destination:
        return False
    original_parent_tokens = tuple(
        "__SCENE_ROOT__" if parent == root else parent.name
        for parent in parents
    ) or ("__SCENE_ROOT__",)
    try:
        with FBPTransaction(
            f"Relink collection {collection.name}",
            kind="COLLECTION_RELINK",
            journal_owner=collection,
            context={
                "scene_name": str(getattr(scene, "name", "") or ""),
                "destination_name": str(getattr(destination, "name", "") or ""),
                "original_parent_tokens": original_parent_tokens,
            },
        ) as transaction:
            transaction.defer_rollback(
                _fbp_restore_collection_parents,
                scene, collection, original_parent_tokens,
                label="restore collection parents",
            )
            transaction.checkpoint("LINK_DESTINATION")
            if collection not in tuple(getattr(destination, "children", ()) or ()):
                destination.children.link(collection)
            transaction.checkpoint("UNLINK_OLD_PARENTS")
            for parent in parents:
                if parent == destination:
                    continue
                parent.children.unlink(collection)

            final_parents = _fbp_collection_parents(root, collection)
            if len(final_parents) != 1 or final_parents[0] != destination:
                raise RuntimeError(
                    "Collection relink did not produce one canonical parent"
                )
            try:
                collection.fbp_layer_order = -1
                if hasattr(collection, 'fbp_layer_order_mixed'):
                    collection.fbp_layer_order_mixed = False
            except FBP_DATA_IO_ERRORS:
                pass
            transaction.checkpoint("VALIDATED")
            transaction.commit()
            return True
    except FBP_DATA_IO_ERRORS as exc:
        fbp_warn(
            "Could not relink Layer List collection",
            exc,
            event="layers.collection_relink.transaction",
            context={
                "collection": getattr(collection, "name", ""),
                "destination": getattr(destination, "name", ""),
            },
        )
        return False


def _fbp_restore_collection_parents(scene, collection, parent_tokens):
    """Restore the exact pre-drag parent links for a cancelled modal move."""
    root = getattr(scene, "collection", None)
    if root is None or collection is None:
        return False
    desired = []
    for token in tuple(parent_tokens or ()):
        parent = root if token == "__SCENE_ROOT__" else bpy.data.collections.get(str(token or ""))
        if parent is None or parent == collection or _fbp_collection_contains(collection, parent):
            continue
        if parent not in desired:
            desired.append(parent)
    if not desired:
        desired = [root]

    try:
        current = list(_fbp_collection_parents(root, collection))
        for parent in desired:
            if collection not in tuple(getattr(parent, "children", ()) or ()):
                parent.children.link(collection)
        for parent in current:
            if parent in desired:
                continue
            try:
                parent.children.unlink(collection)
            except FBP_DATA_IO_ERRORS:
                pass
    except FBP_DATA_IO_ERRORS:
        return False
    try:
        final = list(_fbp_collection_parents(root, collection))
        final_keys = {int(parent.as_pointer()) for parent in final}
        desired_keys = {int(parent.as_pointer()) for parent in desired}
    except FBP_DATA_ERRORS:
        final = list(_fbp_collection_parents(root, collection))
        final_keys = {id(parent) for parent in final}
        desired_keys = {id(parent) for parent in desired}
    return final_keys == desired_keys


def _fbp_collection_collapse_snapshot(root):
    """Capture collection fold state so cancelling a drag is visually exact."""
    if root is None:
        return {}
    result = {}
    seen = set()
    stack = [root]
    while stack:
        collection = stack.pop()
        if collection is None:
            continue
        try:
            key = int(collection.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(collection)
        if key in seen:
            continue
        seen.add(key)
        try:
            name = "__SCENE_ROOT__" if collection == root else collection.name
            result[name] = bool(getattr(collection, "fbp_collapsed", False))
            stack.extend(tuple(getattr(collection, "children", ()) or ()))
        except FBP_DATA_ERRORS:
            continue
    return result


def _fbp_restore_collection_collapse_snapshot(root, snapshot):
    if root is None:
        return
    for token, collapsed in dict(snapshot or {}).items():
        collection = root if token == "__SCENE_ROOT__" else bpy.data.collections.get(str(token or ""))
        if collection is None:
            continue
        try:
            collection.fbp_collapsed = bool(collapsed)
        except FBP_DATA_IO_ERRORS:
            pass



def _fbp_layer_tree_row_identity(row):
    if row is None:
        return None
    try:
        return (
            str(getattr(row, "row_type", "") or ""),
            str(getattr(row, "collection_name", "") or ""),
            str(getattr(row, "rig_name", "") or ""),
            str(getattr(row, "canvas_name", "") or ""),
            str(getattr(row, "gp_layer_name", "") or ""),
        )
    except FBP_DATA_ERRORS:
        return None


def _fbp_capture_layer_tree_active_row(scene):
    try:
        rows = getattr(scene, "fbp_layer_tree_rows", ()) or ()
        index = int(getattr(scene, "fbp_layer_tree_rows_idx", -1))
        identity = (
            _fbp_layer_tree_row_identity(rows[index])
            if 0 <= index < len(rows) else None
        )
        return index, identity
    except FBP_DATA_ERRORS:
        return -1, None


def _fbp_restore_layer_tree_active_row(scene, index, identity):
    try:
        rows = getattr(scene, "fbp_layer_tree_rows", ()) or ()
        if not rows:
            scene.fbp_layer_tree_rows_idx = 0
            return 0
        if identity is not None:
            for candidate_index, row in enumerate(rows):
                if _fbp_layer_tree_row_identity(row) == identity:
                    scene.fbp_layer_tree_rows_idx = candidate_index
                    return candidate_index
        restored = min(max(0, int(index)), len(rows) - 1)
        scene.fbp_layer_tree_rows_idx = restored
        return restored
    except FBP_DATA_ERRORS:
        return -1


def _fbp_focus_collection_tree_row(context, collection):
    """Refresh the Layer List and keep one moved collection active."""
    scene = getattr(context, "scene", None)
    if scene is None or collection is None:
        return -1
    try:
        scene.fbp_layer_tree_signature = ""
    except FBP_DATA_ERRORS:
        pass
    _fbp_refresh_layer_tree(context)
    try:
        for index, candidate in enumerate(getattr(scene, "fbp_layer_tree_rows", ()) or ()):
            if (
                str(getattr(candidate, "row_type", "") or "") == "GROUP"
                and str(getattr(candidate, "collection_name", "") or "") == collection.name
            ):
                scene.fbp_layer_tree_rows_idx = index
                return index
    except FBP_DATA_ERRORS:
        pass
    return -1


def _fbp_finalize_collection_move(context, collection, destination):
    if collection is None or destination is None:
        return False
    try:
        destination.fbp_collapsed = False
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        context.view_layer.update()
    except FBP_DATA_IO_ERRORS:
        pass
    _fbp_focus_collection_tree_row(context, collection)
    fbp_tag_redraw(context, area_types={'VIEW_3D', 'PROPERTIES', 'OUTLINER'})
    return True


def _fbp_apply_collection_nesting_action(
    context, collection, action, list_mode="ALL", *, finalize=True
):
    """Apply one IN/OUT nesting step and return the destination collection."""
    scene = getattr(context, "scene", None)
    root = getattr(scene, "collection", None) if scene is not None else None
    if scene is None or root is None or collection is None or collection == root:
        return None
    _fbp_refresh_layer_tree(context)
    row, row_index = _fbp_collection_tree_row(scene, collection.name)
    if row is None:
        return None

    action = str(action or "").upper()
    if action == 'IN':
        destination = _fbp_previous_sibling_collection(scene, row_index, list_mode)
    elif action == 'OUT':
        parent, parent_row_index = _fbp_tree_parent_collection(scene, row_index)
        if parent is None or parent == root:
            return None
        destination, _grandparent_index = _fbp_tree_parent_collection(scene, parent_row_index)
        destination = destination or root
    else:
        return None

    if destination is None or not _fbp_relink_collection(scene, collection, destination):
        return None
    if bool(finalize):
        _fbp_finalize_collection_move(context, collection, destination)
    return destination


def _fbp_set_stack_object_visual_collection_name(obj, collection_name):
    if obj is None:
        return False
    name = str(
        getattr(collection_name, "name", "")
        or collection_name
        or ""
    )
    try:
        if getattr(obj, "fbp_collection_name", "") != name:
            obj.fbp_collection_name = name
        if is_fbp_layer_object(obj):
            plane = getattr(obj, "fbp_plane_target", None)
            if plane is not None and getattr(plane, "fbp_collection_name", "") != name:
                plane.fbp_collection_name = name
        return True
    except FBP_DATA_ERRORS:
        return False


class FBP_OT_MoveLayerCollection(Operator):
    bl_idname = "fbp.move_layer_collection"
    bl_label = "Move Collection"
    bl_description = "Move the active Layer List collection into the previous collection or out to its parent level"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(
        name="Action",
        description="Change the nesting level of the active Layer List collection",
        items=(
            ('IN', "Move Into Previous", "Nest this collection inside the previous sibling collection"),
            ('OUT', "Move Out", "Move this collection out to its parent's level"),
        ),
        default='IN',
        options={'SKIP_SAVE'},
    )
    collection_name: StringProperty(
        name="Collection",
        description="Optional exact collection row targeted by this action",
        default="",
        options={'SKIP_SAVE'},
    )
    list_mode: StringProperty(
        name="Layer List Mode",
        description="Visible list used to resolve the previous sibling",
        default="ALL",
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return getattr(context, "scene", None) is not None

    def execute(self, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return {'CANCELLED'}
        _fbp_refresh_layer_tree(context)
        row, _row_index = _fbp_collection_tree_row(scene, self.collection_name)
        if row is None:
            self.report({'INFO'}, "Select a collection row in the Layer List")
            return {'CANCELLED'}
        collection = bpy.data.collections.get(str(getattr(row, "collection_name", "") or ""))
        if collection is None:
            return {'CANCELLED'}
        action = str(self.action or 'IN').upper()
        destination = _fbp_apply_collection_nesting_action(
            context, collection, action, self.list_mode
        )
        if destination is None:
            message = (
                "No previous collection is available at this level"
                if action == 'IN'
                else "This collection is already at the top level"
            )
            self.report({'INFO'}, message)
            return {'CANCELLED'}
        verb = "inside" if action == 'IN' else "out to"
        self.report({'INFO'}, f"Moved {collection.name} {verb} {destination.name}")
        return {'FINISHED'}


class FBP_OT_MoveLayerCollectionTo(Operator):
    bl_idname = "fbp.move_layer_collection_to"
    bl_label = "Move Collection To"
    bl_description = "Move this Layer List collection directly below another collection"
    bl_options = {'REGISTER', 'UNDO'}

    collection_name: StringProperty(
        name="Collection",
        description="Collection to move",
        default="",
        options={'SKIP_SAVE'},
    )
    destination_name: StringProperty(
        name="Destination",
        description="Destination collection; empty means the Scene root",
        default="",
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return getattr(context, "scene", None) is not None

    def execute(self, context):
        scene = getattr(context, "scene", None)
        root = getattr(scene, "collection", None) if scene is not None else None
        collection = bpy.data.collections.get(str(self.collection_name or ""))
        destination = (
            bpy.data.collections.get(str(self.destination_name or ""))
            if str(self.destination_name or "")
            else root
        )
        if collection is None or destination is None or collection == root:
            return {'CANCELLED'}
        if destination != root and not _fbp_collection_contains(root, destination):
            self.report({'WARNING'}, "The destination collection is not part of the active Scene")
            return {'CANCELLED'}
        if collection == destination or _fbp_collection_contains(collection, destination):
            self.report({'WARNING'}, "A collection cannot be moved inside itself or one of its descendants")
            return {'CANCELLED'}
        if not _fbp_relink_collection(scene, collection, destination):
            self.report({'INFO'}, "The collection could not be moved to that location")
            return {'CANCELLED'}
        _fbp_finalize_collection_move(context, collection, destination)
        self.report({'INFO'}, f"Moved {collection.name} to {destination.name}")
        return {'FINISHED'}


class FBP_OT_DragLayerCollection(Operator):
    bl_idname = "fbp.drag_layer_collection"
    bl_label = "Drag Collection"
    bl_description = "Drag vertically to reorder; drag right to nest or left to move out. The UI previews the result and commits once on release"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL', 'BLOCKING'}

    tree_index: IntProperty(
        name="Tree Row",
        description="Visible Layer List collection row to drag",
        default=-1,
        options={'SKIP_SAVE'},
    )
    collection_name: StringProperty(
        name="Collection",
        description="Collection represented by this row",
        default="",
        options={'SKIP_SAVE'},
    )
    list_mode: StringProperty(
        name="Layer List Mode",
        description="Visible list used to resolve collection nesting during drag",
        default="ALL",
        options={'SKIP_SAVE'},
    )

    def _restore_cursor(self, context):
        restore_modal_cursor(context)

    def _redraw(self, context):
        fbp_tag_redraw(context, area_types={'VIEW_3D', 'PROPERTIES', 'OUTLINER'})

    def invoke(self, context, event):
        scene = getattr(context, "scene", None)
        if scene is None:
            return {'CANCELLED'}
        _fbp_refresh_layer_tree(context)
        row, _row_index = _fbp_collection_tree_row(scene, self.collection_name)
        if row is None and 0 <= int(self.tree_index) < len(getattr(scene, "fbp_layer_tree_rows", ()) or ()):
            candidate = scene.fbp_layer_tree_rows[int(self.tree_index)]
            if str(getattr(candidate, "row_type", "") or "") == "GROUP":
                row = candidate
        name = str(getattr(row, "collection_name", "") or "") if row is not None else ""
        collection = bpy.data.collections.get(name)
        root = getattr(scene, "collection", None)
        if collection is None or root is None or collection == root:
            return {'CANCELLED'}

        self._collection_name = collection.name
        original_parents = _fbp_collection_parents(root, collection)
        self._original_parent_tokens = tuple(
            "__SCENE_ROOT__" if parent == root else parent.name
            for parent in original_parents
        ) or ("__SCENE_ROOT__",)
        self._original_collapse_snapshot = _fbp_collection_collapse_snapshot(root)
        try:
            self._original_layer_order = float(getattr(collection, 'fbp_layer_order', -1.0))
            self._original_layer_order_mixed = bool(getattr(collection, 'fbp_layer_order_mixed', False))
            self._original_list_domain = str(getattr(collection, 'fbp_layer_list_domain', 'PLANES') or 'PLANES')
        except FBP_DATA_ERRORS:
            self._original_layer_order = -1.0
            self._original_layer_order_mixed = False
            self._original_list_domain = 'PLANES'
        (
            self._original_active_index,
            self._original_active_identity,
        ) = _fbp_capture_layer_tree_active_row(scene)
        self._anchor_x = int(getattr(event, 'mouse_x', 0) or 0)
        self._anchor_y = int(getattr(event, 'mouse_y', 0) or 0)
        self._delta_x = 0
        self._delta_y = 0
        self._moved = False
        try:
            ui_scale = float(context.preferences.system.ui_scale)
        except FBP_DATA_ERRORS:
            ui_scale = 1.0
        self._threshold = max(12, int(round(22.0 * ui_scale)))
        _fbp_focus_collection_tree_row(context, collection)
        try:
            if not fbp_begin_ui_modal_mutation(self):
                raise RuntimeError("Could not acquire the collection drag guard")
            context.window_manager.modal_handler_add(self)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            try:
                fbp_end_ui_modal_mutation(self)
            except Exception:
                pass
            fbp_warn("Could not start collection drag", exc)
            return {'CANCELLED'}
        try:
            context.window.cursor_modal_set('SCROLL_Y')
        except FBP_DATA_ERRORS:
            pass
        self._redraw(context)
        return {'RUNNING_MODAL'}

    def _cancel_drag(self, context, collection):
        _fbp_clear_layer_reorder_preview(context)
        scene = getattr(context, 'scene', None)
        root = getattr(scene, 'collection', None) if scene is not None else None
        if scene is not None and root is not None and collection is not None:
            _fbp_restore_collection_parents(
                scene,
                collection,
                getattr(self, '_original_parent_tokens', ()),
            )
            _fbp_restore_collection_collapse_snapshot(
                root,
                getattr(self, '_original_collapse_snapshot', {}),
            )
            try:
                collection.fbp_layer_order = float(getattr(self, '_original_layer_order', -1.0))
                collection.fbp_layer_order_mixed = bool(getattr(self, '_original_layer_order_mixed', False))
                collection.fbp_layer_list_domain = str(getattr(self, '_original_list_domain', 'PLANES') or 'PLANES')
                scene.fbp_layer_tree_signature = ""
            except FBP_DATA_IO_ERRORS:
                pass
            try:
                context.view_layer.update()
            except FBP_DATA_IO_ERRORS:
                pass
        self._restore_cursor(context)
        fbp_end_ui_modal_mutation(self)
        if scene is not None:
            _fbp_refresh_layer_tree(context)
            _fbp_restore_layer_tree_active_row(
                scene,
                getattr(self, '_original_active_index', -1),
                getattr(self, '_original_active_identity', None),
            )
        self._redraw(context)
        return {'CANCELLED'}

    def modal(self, context, event):
        collection = None
        try:
            fbp_touch_ui_modal_mutation(self)
            collection = bpy.data.collections.get(
                str(getattr(self, '_collection_name', '') or '')
            )
            if collection is None:
                _fbp_clear_layer_reorder_preview(context)
                self._restore_cursor(context)
                fbp_end_ui_modal_mutation(self)
                _fbp_refresh_layer_tree(context)
                self._redraw(context)
                return {'CANCELLED'}

            if event.type == 'MOUSEMOVE':
                self._delta_x = int(
                    getattr(event, 'mouse_x', self._anchor_x) or self._anchor_x
                ) - self._anchor_x
                self._delta_y = int(
                    getattr(event, 'mouse_y', self._anchor_y) or self._anchor_y
                ) - self._anchor_y
                _fbp_prepare_layer_reorder_preview(
                    context,
                    source_type="COLLECTION",
                    source_name=collection.name,
                    tree_index=int(getattr(self, "tree_index", -1)),
                    mode=self.list_mode,
                    delta_x=self._delta_x,
                    delta_y=self._delta_y,
                    threshold=self._threshold,
                )
                self._redraw(context)
                return {'RUNNING_MODAL'}

            if event.type in {'ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'}:
                return self._cancel_drag(context, collection)

            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                preview = transient_get(
                    getattr(context, "scene", None),
                    _FBP_LAYER_REORDER_PREVIEW_KEY,
                    None,
                )
                if not isinstance(preview, dict):
                    _fbp_prepare_layer_reorder_preview(
                        context,
                        source_type="COLLECTION",
                        source_name=collection.name,
                        tree_index=int(getattr(self, "tree_index", -1)),
                        mode=self.list_mode,
                        delta_x=int(getattr(self, "_delta_x", 0) or 0),
                        delta_y=int(getattr(self, "_delta_y", 0) or 0),
                        threshold=self._threshold,
                    )
                changed = bool(_fbp_commit_layer_reorder_preview(context))
                self._restore_cursor(context)
                fbp_end_ui_modal_mutation(self)
                _fbp_refresh_layer_tree(context)
                self._redraw(context)
                return {'FINISHED'} if changed else {'CANCELLED'}
            return {'RUNNING_MODAL'}
        except Exception as exc:
            fbp_warn("Collection drag aborted safely", exc)
            if collection is not None:
                return self._cancel_drag(context, collection)
            _fbp_clear_layer_reorder_preview(context)
            self._restore_cursor(context)
            fbp_end_ui_modal_mutation(self)
            _fbp_refresh_layer_tree(context)
            self._redraw(context)
            return {'CANCELLED'}


class FBP_OT_CreateLayerCollection(Operator):
    bl_idname = "fbp.create_layer_collection"
    bl_label = "Create Collection"
    bl_description = "Create a Frame By Plane collection, nesting it inside the selected layers' current collection when possible"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(
        name="Name",
        description="Name for the new Frame By Plane collection",
        default="FBP Collection",
        options={'SKIP_SAVE'},
    )
    mode: StringProperty(
        name="Mode",
        description="Limit grouping to plane layers or Grease Pencil canvases when called from a split list",
        default="AUTO",
        options={'SKIP_SAVE'},
    )

    @staticmethod
    def _ordered_selected_gp(context):
        try:
            from .grease_pencil_bridge import is_gp_drawing_canvas
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return []
        selected = tuple(getattr(context, "selected_objects", ()) or ())
        active = getattr(context, "object", None)
        ordered = ((active,) if active is not None else ()) + tuple(
            obj for obj in selected if obj is not active
        )
        result = []
        for obj in ordered:
            try:
                if is_gp_drawing_canvas(obj) and obj not in result:
                    result.append(obj)
            except FBP_DATA_ERRORS:
                continue
        return result

    @staticmethod
    def _active_tree_domain(scene):
        try:
            rows = getattr(scene, "fbp_layer_tree_rows", ()) or ()
            index = int(getattr(scene, "fbp_layer_tree_rows_idx", -1))
            if not (0 <= index < len(rows)):
                return "PLANES"
            row = rows[index]
            row_type = str(getattr(row, "row_type", "") or "")
            if row_type in {"GP_CANVAS", "GP_LAYER"}:
                return "GP"
            if row_type == "GROUP":
                domain = str(getattr(row, "list_domain", "PLANES") or "PLANES").upper()
                return domain if domain in {"PLANES", "GP"} else "PLANES"
        except FBP_DATA_ERRORS:
            pass
        return "PLANES"

    def execute(self, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return {'CANCELLED'}

        requested_mode = str(getattr(self, 'mode', 'AUTO') or 'AUTO').upper()
        if requested_mode not in {'AUTO', 'PLANES', 'GP'}:
            requested_mode = 'AUTO'

        selected_rigs = [
            rig for rig in get_selected_rigs(context)
            if rig is not None and is_fbp_layer_object(rig)
        ]
        selected_gp = self._ordered_selected_gp(context)

        if requested_mode == 'AUTO':
            active = getattr(context, "object", None)
            active_is_gp = bool(selected_gp and active is selected_gp[0])
            if active_is_gp:
                resolved_mode = 'GP'
            elif selected_rigs:
                resolved_mode = 'PLANES'
            elif selected_gp:
                resolved_mode = 'GP'
            else:
                resolved_mode = self._active_tree_domain(scene)
        else:
            resolved_mode = requested_mode

        # Plane and GP collections are deliberately separate. Mixed viewport
        # selections group only the active domain instead of leaking objects
        # into the other dedicated Layer List.
        selected_objects = list(selected_gp if resolved_mode == 'GP' else selected_rigs)

        visual_collections = []
        seen_collections = set()
        for obj in selected_objects:
            visual_name = str(getattr(obj, "fbp_collection_name", "") or "")
            collection = bpy.data.collections.get(visual_name) if visual_name else None
            collection = collection or _fbp_stack_object_collection(obj, scene)
            if collection is None:
                continue
            try:
                key = int(collection.as_pointer())
            except FBP_DATA_ERRORS:
                key = id(collection)
            if key not in seen_collections:
                seen_collections.add(key)
                visual_collections.append(collection)

        def ancestor_chain(collection):
            chain = []
            current = collection
            visited = set()
            while current is not None:
                try:
                    key = int(current.as_pointer())
                except FBP_DATA_ERRORS:
                    key = id(current)
                if key in visited:
                    break
                visited.add(key)
                chain.append(current)
                current = _fbp_canonical_collection_parent(scene, current)
            if scene.collection not in chain:
                chain.append(scene.collection)
            return chain

        parent = None
        if visual_collections:
            if len(visual_collections) == 1:
                # Selecting several planes already inside one collection creates
                # the new collection inside that collection.
                parent = visual_collections[0]
            else:
                chains = [ancestor_chain(collection) for collection in visual_collections]
                for candidate in chains[0]:
                    if all(candidate in chain for chain in chains[1:]):
                        parent = candidate
                        break
        parent = (
            parent
            or fbp_active_work_collection(context)
            or getattr(context, "collection", None)
            or scene.collection
        )

        base_name = self.name
        if not base_name or base_name == "FBP Collection":
            base_name = "FBP GP Collection" if resolved_mode == "GP" else "FBP Collection"
        name = _fbp_unique_collection_name(base_name)

        # Capture display placement and artist color before relinking members.
        # The active object is first in get_selected_rigs/_ordered_selected_gp,
        # which is Blender's only reliable definition of the first selected layer.
        closest_order = None
        if selected_objects:
            depth_context = fbp_make_depth_context_cache(context)
            depth_values = []
            for obj in selected_objects:
                try:
                    depth_values.append(float(fbp_layer_depth_value_from_cache(obj, depth_context)))
                except (TypeError, ValueError, OverflowError, ReferenceError, RuntimeError):
                    continue
            if depth_values:
                closest_order = min(depth_values)
        first_color_tag = str(
            getattr(selected_objects[0], "fbp_color_tag", "NONE")
            if selected_objects else "NONE"
        ) or "NONE"

        try:
            collection = bpy.data.collections.new(name)
            parent.children.link(collection)
            collection.is_fbp_collection = True
            if hasattr(collection, "fbp_layer_list_domain"):
                collection.fbp_layer_list_domain = resolved_mode
            collection.fbp_collapsed = False
            if closest_order is not None:
                collection.fbp_layer_order = max(0.0, float(closest_order))
                collection.fbp_layer_order_mixed = True
            set_collection_color_tag(collection, first_color_tag)
            if hasattr(collection, "fbp_color_tag_explicit"):
                collection.fbp_color_tag_explicit = bool(selected_objects)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not create Frame By Plane collection", exc)
            return {'CANCELLED'}

        moved = 0
        for obj in selected_objects:
            if _fbp_move_stack_object_to_collection(scene, obj, collection, resolved_mode):
                moved += 1

        _fbp_refresh_layer_tree(context)
        selected_tree_index = -1
        try:
            for index, row in enumerate(getattr(scene, "fbp_layer_tree_rows", ()) or ()):
                if (
                    str(getattr(row, "row_type", "") or "") == "GROUP"
                    and str(getattr(row, "collection_name", "") or "") == collection.name
                ):
                    selected_tree_index = index
                    scene.fbp_layer_tree_rows_idx = index
                    break
        except FBP_DATA_ERRORS:
            selected_tree_index = -1
        _fbp_arm_collection_row_selection_guard(scene, collection.name, selected_tree_index)

        if moved:
            self.report({'INFO'}, f"Moved {moved} layer(s) into: {collection.name}")
        else:
            self.report({'INFO'}, f"Created collection: {collection.name}")
        return {'FINISHED'}


def _fbp_find_tree_index_for_object(scene, object_name):
    target = str(object_name or "")
    if not target:
        return -1
    try:
        for index, row in enumerate(getattr(scene, "fbp_layer_tree_rows", ()) or ()):  # virtual rows
            if str(getattr(row, "rig_name", "") or "") == target:
                return index
            if str(getattr(row, "canvas_name", "") or "") == target:
                return index
            if str(getattr(row, "name", "") or "") == target:
                return index
    except FBP_DATA_ERRORS:
        pass
    return -1


class FBP_OT_UngroupSelectedLayers(Operator):
    bl_idname = "fbp.ungroup_selected_layers"
    bl_label = "Move Selected Out"
    bl_description = "Move selected Frame By Plane layers from their current Collection into its parent Collection"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(
        name="Layer",
        description="Optional layer used when the command is opened from a specific Layer List row",
        default="",
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return getattr(context, "scene", None) is not None

    def execute(self, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return {'CANCELLED'}

        selected = list(_fbp_groupable_shortcut_targets(context))
        specific = bpy.data.objects.get(str(getattr(self, "rig_name", "") or ""))
        if (
            specific is not None
            and (is_fbp_layer_object(specific) or _fbp_is_gp_drawing_canvas_object(specific))
            and specific not in selected
        ):
            targets = [specific]
        else:
            targets = selected

        moved = 0
        for target in targets:
            collection = get_primary_fbp_collection(target)
            if collection is None or collection == scene.collection:
                continue
            parent = _fbp_canonical_collection_parent(scene, collection)
            destination = parent or scene.collection
            mode = 'GP' if _fbp_is_gp_drawing_canvas_object(target) else 'PLANES'
            if _fbp_move_stack_object_to_collection(scene, target, destination, mode):
                moved += 1

        if not moved:
            self.report({'INFO'}, "Selected layers are not inside a nested collection")
            return {'CANCELLED'}

        _fbp_refresh_layer_tree(context)
        self.report({'INFO'}, f"Moved {moved} layer(s) to the parent collection")
        return {'FINISHED'}


class FBP_OT_DragLayerTree(FBP_VerticalDragModalMixin, Operator):
    bl_idname = "fbp.drag_layer_tree"
    bl_label = "Drag Layer"
    bl_description = "Drag to preview the new Layer List position; depth, scale and collection membership commit once on release"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL', 'BLOCKING'}

    tree_index: IntProperty(
        name="Tree Row",
        description="Visible Layer List row to drag",
        default=-1,
        options={'SKIP_SAVE'},
    )
    rig_name: StringProperty(
        name="Layer",
        description="Rig or Grease Pencil canvas represented by this row",
        default="",
        options={'SKIP_SAVE'},
    )
    list_mode: StringProperty(
        name="Layer List Mode",
        description="Dedicated Plane or Grease Pencil list that owns the dragged row",
        default="PLANES",
        options={'SKIP_SAVE'},
    )

    def _redraw(self, context):
        fbp_tag_redraw(context, area_types={'VIEW_3D', 'PROPERTIES'})

    def _capture_stack_state(self, context):
        scene = getattr(context, 'scene', None)
        snapshots = []
        if scene is None:
            return snapshots
        for obj in tuple(getattr(scene, 'objects', ()) or ()):
            if not (is_fbp_layer_object(obj) or _fbp_is_gp_drawing_canvas_object(obj)):
                continue
            try:
                primary_collection = _fbp_stack_object_collection(obj, scene)
                plane = getattr(obj, 'fbp_plane_target', None) if is_fbp_layer_object(obj) else None
                plane_collection = _fbp_stack_object_collection(plane, scene) if plane is not None else None
                snapshots.append({
                    'object_name': str(getattr(obj, 'name', '') or ''),
                    'matrix_world': obj.matrix_world.copy(),
                    'parent_name': str(getattr(getattr(obj, 'parent', None), 'name', '') or ''),
                    'matrix_parent_inverse': obj.matrix_parent_inverse.copy(),
                    'collection_name': str(getattr(primary_collection, 'name', '') or ''),
                    'visual_collection_name': str(getattr(obj, 'fbp_collection_name', '') or ''),
                    'layer_order': float(getattr(obj, 'fbp_layer_order', -1.0)),
                    'plane_name': str(getattr(plane, 'name', '') or ''),
                    'plane_collection_name': str(getattr(plane_collection, 'name', '') or ''),
                    'plane_visual_collection_name': str(getattr(plane, 'fbp_collection_name', '') or '') if plane is not None else '',
                    'attachment_mode': str(getattr(obj, 'fbp_gp_attachment_mode', '') or ''),
                    'lock_transform': bool(getattr(obj, 'fbp_gp_canvas_lock_transform', False)),
                    'show_in_front': bool(getattr(obj, 'show_in_front', False)),
                    'selected': bool(obj.select_get()),
                })
            except FBP_DATA_ERRORS:
                continue
        return snapshots

    def _cancel_drag(self, context):
        """Restore depth, parenting and GP attachment state in one transaction."""
        snapshots = tuple(getattr(self, '_original_stack_state', ()) or ())
        if not snapshots:
            return False
        scene = getattr(context, 'scene', None)
        try:
            for snapshot in snapshots:
                obj = bpy.data.objects.get(str(snapshot.get('object_name', '') or ''))
                if obj is None:
                    continue
                # Restore parenting before the world matrix. Drawing Plane
                # reorder can detach canvases and switch them to WORLD mode.
                parent_name = str(snapshot.get('parent_name', '') or '')
                obj.parent = bpy.data.objects.get(parent_name) if parent_name else None
                obj.matrix_parent_inverse = snapshot['matrix_parent_inverse'].copy()
                attachment_mode = snapshot.get('attachment_mode', '')
                if attachment_mode and hasattr(obj, 'fbp_gp_attachment_mode'):
                    obj.fbp_gp_attachment_mode = attachment_mode
                if hasattr(obj, 'fbp_gp_canvas_lock_transform'):
                    obj.fbp_gp_canvas_lock_transform = bool(snapshot.get('lock_transform', False))
                obj.show_in_front = bool(snapshot.get('show_in_front', False))
                obj.matrix_world = snapshot['matrix_world'].copy()
                original_collection = bpy.data.collections.get(
                    str(snapshot.get('collection_name', '') or '')
                )
                if original_collection is not None:
                    move_object_to_collection(obj, original_collection)
                if hasattr(obj, 'fbp_collection_name'):
                    obj.fbp_collection_name = str(snapshot.get('visual_collection_name', '') or '')
                if hasattr(obj, 'fbp_layer_order'):
                    obj.fbp_layer_order = float(snapshot.get('layer_order', -1.0))

                plane_name = str(snapshot.get('plane_name', '') or '')
                plane = bpy.data.objects.get(plane_name) if plane_name else None
                if plane is not None:
                    plane_collection = bpy.data.collections.get(
                        str(snapshot.get('plane_collection_name', '') or '')
                    )
                    if plane_collection is not None:
                        move_object_to_collection(plane, plane_collection)
                    if hasattr(plane, 'fbp_collection_name'):
                        plane.fbp_collection_name = str(
                            snapshot.get('plane_visual_collection_name', '') or ''
                        )

            if scene is not None:
                scene.fbp_layer_stack_index = int(
                    getattr(self, '_original_layer_stack_index', 0) or 0
                )
                scene.fbp_layer_tree_rows_idx = int(
                    getattr(self, '_original_tree_index', 0) or 0
                )
                scene.fbp_sort_layers_alpha = bool(
                    getattr(self, '_original_sort_alpha', False)
                )

            for snapshot in snapshots:
                obj = bpy.data.objects.get(str(snapshot.get('object_name', '') or ''))
                if obj is None or not object_in_view_layer(obj, context):
                    continue
                obj.select_set(bool(snapshot.get('selected', False)))
            active_name = str(getattr(self, '_original_active_name', '') or '')
            active = bpy.data.objects.get(active_name) if active_name else None
            if active is not None and object_in_view_layer(active, context):
                context.view_layer.objects.active = active

            _fbp_refresh_layer_tree(context)
            if scene is not None:
                restored_tree_index = _fbp_find_tree_index_for_object(
                    scene, active_name,
                )
                if restored_tree_index < 0:
                    restored_tree_index = max(0, min(
                        int(getattr(self, '_original_tree_index', 0) or 0),
                        max(0, len(getattr(scene, 'fbp_layer_tree_rows', ())) - 1),
                    ))
                scene.fbp_layer_tree_rows_idx = restored_tree_index
            return True
        except FBP_DATA_ERRORS as exc:
            fbp_warn('Could not restore cancelled layer drag', exc)
            return False

    def _set_active_index(self, context):
        index = _fbp_find_tree_index_for_object(context.scene, self._object_name)
        if index >= 0:
            context.scene.fbp_layer_tree_rows_idx = index
        return index

    def _move_once(self, context, direction):
        self._set_active_index(context)

        class _DragMoveProxy:
            def report(self, _level, _message):
                return None

        proxy = _DragMoveProxy()
        proxy.direction = direction
        proxy.rig_name = self._object_name
        proxy._fbp_defer_drag_refresh = True
        try:
            result = FBP_OT_MoveLayerStack.execute(proxy, context)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not drag-reorder layer", exc)
            return False
        if 'FINISHED' not in set(result):
            return False
        self._set_active_index(context)
        return True

    def _on_drag_finished(self, context, *, cancelled):
        # Rebuild once after the modal guard is released. During movement the
        # backing CollectionProperty remains stable, so Blender never redraws
        # rows through invalidated PropertyGroup wrappers.
        _fbp_refresh_layer_tree(context)
        self._set_active_index(context)
        if not cancelled:
            obj = bpy.data.objects.get(str(getattr(self, '_object_name', '') or ''))
            try:
                if obj is not None and object_in_view_layer(obj, context):
                    _fbp_deselect_layer_objects(context)
                    obj.select_set(True)
                    context.view_layer.objects.active = obj
            except FBP_DATA_ERRORS:
                pass

    def modal(self, context, event):
        """Preview a shadow row order, then commit one scene mutation on release."""
        try:
            self._touch_modal_mutation()
            obj = bpy.data.objects.get(
                str(getattr(self, '_object_name', '') or '')
            )
            if obj is None:
                _fbp_clear_layer_reorder_preview(context)
                self._restore_cursor(context)
                self._end_modal_mutation()
                self._notify_drag_finished(context, cancelled=True)
                self._redraw(context)
                return {'CANCELLED'}

            if event.type == 'MOUSEMOVE':
                self._saw_drag_motion = True
                mouse_y = int(
                    getattr(event, 'mouse_y', self._origin_y) or self._origin_y
                )
                mouse_x = int(
                    getattr(event, 'mouse_x', self._origin_x) or self._origin_x
                )
                self._delta_y = mouse_y - self._origin_y
                self._delta_x = mouse_x - self._origin_x
                self._pending_steps = (
                    int(self._delta_y / self._threshold)
                    if self._threshold else 0
                )
                source_type = (
                    "GP_CANVAS"
                    if _fbp_is_gp_drawing_canvas_object(obj)
                    else "LAYER"
                )
                _fbp_prepare_layer_reorder_preview(
                    context,
                    source_type=source_type,
                    source_name=self._object_name,
                    tree_index=int(getattr(self, "tree_index", -1)),
                    mode=self.list_mode,
                    delta_x=self._delta_x,
                    delta_y=self._delta_y,
                    threshold=self._threshold,
                )
                self._redraw(context)
                return {'RUNNING_MODAL'}

            if event.type in {'ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'}:
                _fbp_clear_layer_reorder_preview(context)
                self._cancel_drag_transaction(context)
                self._restore_cursor(context)
                self._end_modal_mutation()
                self._notify_drag_finished(context, cancelled=True)
                self._redraw(context)
                return {'CANCELLED'}

            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                preview = transient_get(
                    getattr(context, "scene", None),
                    _FBP_LAYER_REORDER_PREVIEW_KEY,
                    None,
                )
                if not isinstance(preview, dict):
                    source_type = (
                        "GP_CANVAS"
                        if _fbp_is_gp_drawing_canvas_object(obj)
                        else "LAYER"
                    )
                    _fbp_prepare_layer_reorder_preview(
                        context,
                        source_type=source_type,
                        source_name=self._object_name,
                        tree_index=int(getattr(self, "tree_index", -1)),
                        mode=self.list_mode,
                        delta_x=int(getattr(self, "_delta_x", 0) or 0),
                        delta_y=int(getattr(self, "_delta_y", 0) or 0),
                        threshold=self._threshold,
                    )
                changed = bool(_fbp_commit_layer_reorder_preview(context))
                self._did_change = changed
                self._restore_cursor(context)
                self._end_modal_mutation()
                self._notify_drag_finished(context, cancelled=not changed)
                self._redraw(context)
                return {'FINISHED'} if changed else {'CANCELLED'}

            return {'RUNNING_MODAL'}
        except Exception as exc:
            fbp_warn("Layer drag aborted safely", exc)
            _fbp_clear_layer_reorder_preview(context)
            try:
                self._cancel_drag(context)
            except Exception as rollback_exc:
                fbp_warn("Could not completely roll back layer drag", rollback_exc)
            self._restore_cursor(context)
            self._end_modal_mutation()
            self._notify_drag_finished(context, cancelled=True)
            self._redraw(context)
            return {'CANCELLED'}

    def invoke(self, context, event):
        scene = getattr(context, "scene", None)
        if scene is None:
            return {'CANCELLED'}
        object_name = str(getattr(self, "rig_name", "") or "")
        if not object_name:
            try:
                rows = getattr(scene, "fbp_layer_tree_rows", ())
                if 0 <= int(self.tree_index) < len(rows):
                    row = rows[int(self.tree_index)]
                    object_name = (
                        str(getattr(row, "rig_name", "") or "")
                        or str(getattr(row, "canvas_name", "") or "")
                        or str(getattr(row, "name", "") or "")
                    )
            except FBP_DATA_ERRORS:
                object_name = ""
        obj = bpy.data.objects.get(object_name)
        if obj is None or not (is_fbp_layer_object(obj) or _fbp_is_gp_drawing_canvas_object(obj)):
            return {'CANCELLED'}
        self._object_name = object_name
        self._original_stack_state = self._capture_stack_state(context)
        self._original_layer_stack_index = int(
            getattr(scene, 'fbp_layer_stack_index', 0) or 0
        )
        self._original_tree_index = int(
            getattr(scene, 'fbp_layer_tree_rows_idx', 0) or 0
        )
        self._original_sort_alpha = bool(
            getattr(scene, 'fbp_sort_layers_alpha', False)
        )
        active = getattr(getattr(context, 'view_layer', None), 'objects', None)
        active = getattr(active, 'active', None)
        self._original_active_name = str(getattr(active, 'name', '') or '')
        self._anchor_y = int(getattr(event, 'mouse_y', 0) or 0)
        self._origin_y = self._anchor_y
        self._origin_x = int(getattr(event, 'mouse_x', 0) or 0)
        self._delta_x = 0
        self._delta_y = 0
        self._pending_steps = 0
        self._history = []
        self._did_change = False
        self._finish_on_release = str(getattr(event, 'value', '') or '') in {'PRESS', 'CLICK_DRAG'}
        self._saw_drag_motion = False
        try:
            ui_scale = float(context.preferences.system.ui_scale)
        except FBP_DATA_ERRORS:
            ui_scale = 1.0
        self._threshold = max(10, int(round(18.0 * ui_scale)))
        self._set_active_index(context)
        try:
            if not self._begin_modal_mutation():
                raise RuntimeError("Could not acquire the UIList modal mutation guard")
            context.window_manager.modal_handler_add(self)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            try:
                self._end_modal_mutation()
            except Exception:
                pass
            fbp_warn("Could not start layer drag", exc)
            return {'CANCELLED'}
        try:
            context.window.cursor_modal_set('SCROLL_Y')
        except FBP_DATA_ERRORS:
            pass
        self._redraw(context)
        return {'RUNNING_MODAL'}


def _fbp_move_stack_object_to_collection(scene, obj, destination, mode):
    """Move the real Blender objects and their Layer List ownership together."""
    if scene is None or obj is None or destination is None:
        return False
    try:
        destination.fbp_layer_list_domain = 'GP' if str(mode).upper() == 'GP' else 'PLANES'
    except FBP_DATA_IO_ERRORS:
        pass
    moved = False
    try:
        move_object_to_collection(obj, destination)
        moved = True
    except FBP_DATA_ERRORS:
        moved = False
    if is_fbp_layer_object(obj):
        plane = getattr(obj, 'fbp_plane_target', None)
        if plane is not None:
            try:
                move_object_to_collection(plane, destination)
            except FBP_DATA_ERRORS:
                pass
    _fbp_set_stack_object_visual_collection_name(
        obj,
        "" if destination == getattr(scene, 'collection', None) else destination.name,
    )
    return moved
def _fbp_target_depth_between(context, source_obj, before_obj, after_obj):
    depth_context = fbp_make_depth_context_cache(context)
    before_depth = (
        fbp_layer_depth_value_from_cache(before_obj, depth_context)
        if before_obj is not None else None
    )
    after_depth = (
        fbp_layer_depth_value_from_cache(after_obj, depth_context)
        if after_obj is not None else None
    )
    current_depth = fbp_layer_depth_value_from_cache(source_obj, depth_context)
    epsilon = max(0.01, abs(float(current_depth)) * 1.0e-5)
    if before_depth is not None and after_depth is not None:
        if abs(float(after_depth) - float(before_depth)) <= epsilon:
            return float(before_depth) + epsilon, depth_context
        return (float(before_depth) + float(after_depth)) * 0.5, depth_context
    if before_depth is not None:
        step = max(epsilon, abs(float(before_depth)) * 0.01, 0.05)
        return float(before_depth) + step, depth_context
    if after_depth is not None:
        step = max(epsilon, abs(float(after_depth)) * 0.01, 0.05)
        return max(epsilon, float(after_depth) - step), depth_context
    return float(current_depth), depth_context


def _fbp_stack_value_for_preview_token(context, token):
    token = str(token or '')
    if ':' not in token:
        return None
    token_type, name = token.split(':', 1)
    token_type = token_type.upper()
    if token_type == 'COLLECTION':
        collection = bpy.data.collections.get(name)
        if collection is None:
            return None
        try:
            explicit = float(getattr(collection, 'fbp_layer_order', -1.0))
            if explicit >= 0.0 and bool(getattr(collection, 'fbp_layer_order_mixed', False)):
                return explicit
        except FBP_DATA_ERRORS:
            pass
        depths = []
        cache = fbp_make_depth_context_cache(context)
        for rig in iter_fbp_rigs_in_collection(collection, recursive=True):
            depths.append(fbp_layer_depth_value_from_cache(rig, cache))
        return (sum(depths) / len(depths)) if depths else None
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None
    try:
        explicit = float(getattr(obj, 'fbp_layer_order', -1.0))
        if explicit >= 0.0:
            return explicit
    except FBP_DATA_ERRORS:
        pass
    return fbp_layer_depth_value_from_cache(obj, fbp_make_depth_context_cache(context))


def _fbp_collection_preview_order_value(context, preview):
    before_value = _fbp_stack_value_for_preview_token(
        context, preview.get('after_token', '')
    )
    after_value = _fbp_stack_value_for_preview_token(
        context, preview.get('before_token', '')
    )
    # ``after_token`` is the item visually above the insertion; the Layer List
    # is closest-to-camera first, so its numeric value is the lower boundary.
    if before_value is not None and after_value is not None:
        return (float(before_value) + float(after_value)) * 0.5
    if before_value is not None:
        return float(before_value) + max(0.05, abs(float(before_value)) * 0.01)
    if after_value is not None:
        return max(0.0, float(after_value) - max(0.05, abs(float(after_value)) * 0.01))
    return 0.0


def _fbp_target_depth_for_preview(context, source_obj, preview):
    """Resolve an interpolated depth from the two visual insertion anchors."""
    depth_context = fbp_make_depth_context_cache(context)
    above_value = _fbp_stack_value_for_preview_token(
        context, preview.get("after_token", "")
    )
    below_value = _fbp_stack_value_for_preview_token(
        context, preview.get("before_token", "")
    )
    current_depth = fbp_layer_depth_value_from_cache(source_obj, depth_context)
    epsilon = max(0.01, abs(float(current_depth)) * 1.0e-5)
    if above_value is not None and below_value is not None:
        if abs(float(below_value) - float(above_value)) <= epsilon:
            return float(above_value) + epsilon, depth_context
        return (float(above_value) + float(below_value)) * 0.5, depth_context
    if above_value is not None:
        step = max(epsilon, abs(float(above_value)) * 0.01, 0.05)
        return float(above_value) + step, depth_context
    if below_value is not None:
        step = max(epsilon, abs(float(below_value)) * 0.01, 0.05)
        return max(epsilon, float(below_value) - step), depth_context
    return float(current_depth), depth_context


def _fbp_commit_layer_reorder_preview(context):
    """Commit the shadow UI proposal once, after the mouse is released."""
    scene = getattr(context, "scene", None)
    preview = transient_get(scene, _FBP_LAYER_REORDER_PREVIEW_KEY, None) if scene is not None else None
    if not isinstance(preview, dict):
        return False
    source_type = str(preview.get("source_type", "") or "").upper()
    source_name = str(preview.get("source_name", "") or "")
    mode = str(preview.get("mode", "PLANES") or "PLANES").upper()
    destination = (
        bpy.data.collections.get(str(preview.get("destination_parent", "") or ""))
        if str(preview.get("destination_parent", "") or "")
        else getattr(scene, "collection", None)
    )
    if destination is None:
        _fbp_clear_layer_reorder_preview(context)
        return False

    changed = False
    affected_collections = []
    try:
        if source_type == "COLLECTION":
            collection = bpy.data.collections.get(source_name)
            if collection is None or collection == getattr(scene, "collection", None):
                return False
            current_parent = _fbp_canonical_collection_parent(scene, collection)
            if current_parent != destination:
                changed = _fbp_relink_collection(scene, collection, destination) or changed
            try:
                collection.fbp_layer_list_domain = "GP" if mode == "GP" else "PLANES"
                collection.fbp_layer_order = _fbp_collection_preview_order_value(context, preview)
                collection.fbp_layer_order_mixed = True
                changed = True
            except FBP_DATA_IO_ERRORS:
                pass
            affected_collections.extend((collection, destination))
        else:
            obj = bpy.data.objects.get(source_name)
            if obj is None:
                return False
            old_collection = _fbp_stack_object_collection(obj, scene)
            changed = _fbp_move_stack_object_to_collection(scene, obj, destination, mode) or changed
            try:
                obj.fbp_layer_order = -1.0
            except FBP_DATA_IO_ERRORS:
                pass
            target_depth, depth_context = _fbp_target_depth_for_preview(
                context, obj, preview
            )
            _fbp_prepare_stack_depth_object(obj)
            changed = move_layer_to_depth_preserve_projection(
                context,
                obj,
                target_depth,
                depth_context=depth_context,
            ) or changed
            affected_collections.extend((old_collection, destination))
    finally:
        transient_pop(scene, _FBP_LAYER_REORDER_PREVIEW_KEY)

    try:
        scene.fbp_sort_layers_alpha = False
        scene.fbp_layer_tree_signature = ""
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        context.view_layer.update()
    except FBP_DATA_IO_ERRORS:
        pass
    _fbp_refresh_layer_tree(context)
    try:
        from .geometry_nodes import fbp_sync_clipping_masks
        collections = []
        seen_collection_keys = set()
        for collection in affected_collections:
            if collection is None:
                continue
            try:
                key = int(collection.as_pointer())
            except FBP_DATA_ERRORS:
                key = str(getattr(collection, "name", "") or "")
            if key in seen_collection_keys:
                continue
            seen_collection_keys.add(key)
            collections.append(collection)
        fbp_sync_clipping_masks(context, collections=tuple(collections) or None)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not refresh Clipping Masks after layer reorder", exc)
    return bool(changed)


class FBP_OT_MoveLayerStack(Operator):
    bl_idname      = "fbp.move_layer_stack"
    bl_label       = "Move Layer"
    bl_description = "Insert this layer one position higher or lower by changing only its camera depth and perspective scale"
    bl_options     = {'REGISTER', 'UNDO'}

    direction: StringProperty(description="Requested movement or step direction for this action, such as previous, next, up or down.")
    rig_name: StringProperty(
        name="Layer",
        description="Optional exact layer target used by context-menu actions",
        default="",
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        if self.direction not in {'UP', 'DOWN'}:
            self.report({'ERROR'}, 'Unknown layer movement direction')
            return {'CANCELLED'}

        sc = context.scene
        layers = sc.fbp_layers
        idx = fbp_active_layer_index(sc)
        current_obj = None
        current_kind = "LAYER"

        active_row, _active_tree_index = _fbp_active_tree_row(sc)
        tree_obj, tree_kind = _fbp_resolve_tree_stack_object(active_row)

        exact_target = bpy.data.objects.get(str(getattr(self, 'rig_name', '') or ''))
        if exact_target and (is_fbp_layer_object(exact_target) or _fbp_is_gp_drawing_canvas_object(exact_target)):
            current_obj = exact_target
            current_kind = "GP_CANVAS" if _fbp_is_gp_drawing_canvas_object(exact_target) else "LAYER"
            idx = -1
            for candidate, item in enumerate(layers):
                if _safe_layer_obj(item) == exact_target:
                    idx = candidate
                    break
        elif tree_obj is not None and tree_kind == "GP_CANVAS":
            current_obj = tree_obj
            current_kind = "GP_CANVAS"
            idx = -1
        else:
            selected_roots = get_selected_fbp_roots(context)
            if len(selected_roots) > 1:
                self.report({'WARNING'}, 'Select a single layer before moving it')
                return {'CANCELLED'}
            if selected_roots:
                current_obj = selected_roots[0]
                current_kind = "LAYER"
                for candidate, item in enumerate(layers):
                    if _safe_layer_obj(item) == current_obj:
                        idx = candidate
                        break
            elif tree_obj is not None and tree_kind == "LAYER":
                current_obj = tree_obj
                current_kind = "LAYER"
                for candidate, item in enumerate(layers):
                    if _safe_layer_obj(item) == current_obj:
                        idx = candidate
                        break
            elif 0 <= idx < len(layers):
                current_obj = _safe_layer_obj(layers[idx])
                current_kind = "LAYER"

        if not current_obj:
            return {'CANCELLED'}
        if current_kind == "LAYER" and not (0 <= idx < len(layers)):
            return {'CANCELLED'}

        depth_context = fbp_make_depth_context_cache(context)
        defer_drag_refresh = bool(getattr(self, '_fbp_defer_drag_refresh', False))

        # Plane and Grease Pencil lists are independent. Move only inside the
        # active family and never swap the neighbour: the active layer is
        # inserted at a newly interpolated camera depth while every other object
        # keeps its transform unchanged.
        display_order = []
        seen = set()
        try:
            for obj in tuple(getattr(sc, "objects", ()) or ()):
                valid = (
                    _fbp_is_gp_drawing_canvas_object(obj)
                    if current_kind == "GP_CANVAS"
                    else is_fbp_layer_object(obj)
                )
                if not valid:
                    continue
                key = int(obj.as_pointer())
                if key in seen:
                    continue
                seen.add(key)
                display_order.append(obj)
            stable_order = {}
            for stable_index, layer_item in enumerate(getattr(sc, "fbp_layers", ()) or ()):
                stable_obj = _safe_layer_obj(layer_item)
                if stable_obj is not None:
                    stable_order[stable_obj] = stable_index
            display_order.sort(
                key=lambda obj: (
                    fbp_layer_depth_value_from_cache(obj, depth_context),
                    stable_order.get(obj, 1 << 30),
                    str(getattr(obj, "name", "") or ""),
                )
            )
        except FBP_DATA_ERRORS:
            display_order = []

        if current_obj not in display_order or len(display_order) < 2:
            self.report({'WARNING'}, 'No visible neighbour in this Layer List')
            return {'CANCELLED'}

        pos = display_order.index(current_obj)
        remaining = display_order[:pos] + display_order[pos + 1:]
        insertion_index = pos - 1 if self.direction == 'UP' else pos + 1
        insertion_index = max(0, min(insertion_index, len(remaining)))
        if (
            (self.direction == 'UP' and pos <= 0)
            or (self.direction == 'DOWN' and pos >= len(display_order) - 1)
        ):
            return {'CANCELLED'}
        before_obj = remaining[insertion_index - 1] if insertion_index > 0 else None
        after_obj = remaining[insertion_index] if insertion_index < len(remaining) else None
        target_depth, depth_context = _fbp_target_depth_between(
            context, current_obj, before_obj, after_obj
        )
        affected_collections = [
            collection for collection in (_fbp_stack_object_collection(current_obj, sc),)
            if collection is not None
        ]
        _fbp_prepare_stack_depth_object(current_obj)
        if not move_layer_to_depth_preserve_projection(
            context,
            current_obj,
            target_depth,
            depth_context=depth_context,
        ):
            return {'CANCELLED'}
        try:
            current_obj.fbp_layer_order = -1.0
        except FBP_DATA_IO_ERRORS:
            pass
        if current_kind == "LAYER":
            sc.fbp_layer_stack_index = idx
        if not defer_drag_refresh:
            try:
                if object_in_view_layer(current_obj, context):
                    _fbp_deselect_layer_objects(context)
                    current_obj.select_set(True)
                    context.view_layer.objects.active = current_obj
            except FBP_DATA_ERRORS:
                pass
        try:
            sc.fbp_sort_layers_alpha = False
        except FBP_DATA_IO_ERRORS:
            pass
        if not defer_drag_refresh:
            _fbp_refresh_layer_tree(context)
        if int(fbp_runtime_get("fbp_ui_modal_mutation_depth", 0) or 0) <= 0:
            try:
                from .geometry_nodes import fbp_sync_clipping_masks
                fbp_sync_clipping_masks(context, collections=tuple(affected_collections) or None)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                fbp_warn('Could not refresh Clipping Masks after reordering', exc)
        return {'FINISHED'}


class FBP_OT_ReverseSelectedLayerOrder(Operator):
    bl_idname = 'fbp.reverse_selected_layer_order'
    bl_label = 'Reverse Selected Layer Order'
    bl_description = 'Reverse the depth order of selected layers inside each collection while leaving unselected layers in place'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = [
            rig for rig in get_selected_fbp_roots(context)
            if is_fbp_layer_object(rig)
        ]
        if len(selected) < 2:
            self.report({'WARNING'}, 'Select at least two Frame By Plane layers')
            return {'CANCELLED'}

        groups = {}
        for rig in selected:
            collection = get_primary_fbp_collection(rig)
            if collection is None:
                continue
            try:
                key = int(collection.as_pointer())
            except FBP_DATA_IO_ERRORS:
                continue
            groups.setdefault(key, (collection, []))[1].append(rig)

        depth_context = fbp_make_depth_context_cache(context)
        stable_order = {}
        for stable_index, layer_item in enumerate(context.scene.fbp_layers):
            stable_rig = _safe_layer_obj(layer_item)
            if stable_rig is not None:
                stable_order[stable_rig] = stable_index
        changed_groups = 0
        affected_collections = []
        for collection, rigs in groups.values():
            if len(rigs) < 2:
                continue
            ordered = sorted(
                rigs,
                key=lambda rig: (
                    fbp_layer_depth_value_from_cache(rig, depth_context),
                    stable_order.get(rig, 1 << 30),
                ),
            )
            for left, right in zip(
                ordered[:len(ordered) // 2],
                reversed(ordered[(len(ordered) + 1) // 2:]),
                strict=True,
            ):
                swap_layer_depth_only(
                    context,
                    left,
                    right,
                    depth_context=depth_context,
                )
            changed_groups += 1
            affected_collections.append(collection)

        if not changed_groups:
            self.report({'WARNING'}, 'Select at least two layers inside the same collection')
            return {'CANCELLED'}

        try:
            context.scene.fbp_sort_layers_alpha = False
        except FBP_DATA_IO_ERRORS:
            pass
        _fbp_refresh_layer_tree(context)
        try:
            from .geometry_nodes import fbp_sync_clipping_masks
            fbp_sync_clipping_masks(
                context,
                collections=tuple(affected_collections),
            )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn('Could not refresh Clipping Masks after reversing layer order', exc)
        self.report({'INFO'}, f"Reversed selected layer order in {changed_groups} collection(s)")
        return {'FINISHED'}


class FBP_OT_IsolateLayer(Operator):
    bl_idname      = "fbp.isolate_layer"
    bl_label       = "Isolate Layer"
    bl_description = "Hide all other layers. Click again to show all"
    bl_options     = {'UNDO'}

    def execute(self, context):
        selected_rigs = get_selected_rigs(context)
        if not selected_rigs:
            return {'CANCELLED'}
        all_rigs = list(iter_scene_fbp_rigs(context.scene))
        visible_rigs = [ob for ob in all_rigs if getattr(ob, "fbp_is_visible", False)]
        is_solo = set(visible_rigs) == set(selected_rigs)
        for rig in all_rigs:
            fbp_set_rna_property_silent(
                rig,
                'fbp_is_visible',
                True if is_solo else (rig in selected_rigs),
            )
        update_global_visibility(context)
        return {'FINISHED'}

class FBP_OT_PopupGenerateCamera(Operator):
    bl_idname = "fbp.popup_generate_camera"
    bl_label = "Create Camera"
    bl_description = "Create a camera and choose its projection, framing and output ratio"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        try:
            from .live_tutorial import fbp_notify_tutorial_action
            fbp_notify_tutorial_action(context, "multi_open_camera")
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        sc = context.scene
        sc.fbp_gen_camera = True
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        sc = context.scene
        layout = configure_layout(self.layout)
        box = layout.box()
        configure_layout(box)
        section_header(box, "Camera Settings", icon=fbp_icon("VIEW_CAMERA"))
        box.prop(sc, "fbp_gen_camera", text="Create Camera", toggle=True, icon='CAMERA_DATA')
        box.prop(sc, "fbp_camera_projection", text="Projection")
        if sc.fbp_camera_projection == 'ORTHO':
            box.prop(sc, "fbp_camera_ortho_scale", text="Orthographic Scale")
        else:
            box.prop(sc, "fbp_camera_lens", text="Lens (mm)")
        row = box.row(align=True)
        row.prop(sc, "fbp_camera_clip_start", text="Clip Start")
        row.prop(sc, "fbp_camera_clip_end", text="Clip End")
        from .camera_output import draw_camera_output
        draw_camera_output(box, sc, context, available_width=360)
        box.prop(sc, "fbp_camera_fit_source_aspect", text="Use Source Aspect on Import")
        row = box.row(align=True)
        row.prop(sc, "fbp_cam_pivot", text="Cursor Pivot", toggle=True, icon=fbp_icon("PIVOT_CURSOR"))
        row.prop(sc, "fbp_auto_scale", text="Fit Layers", toggle=True, icon=fbp_icon("FULLSCREEN_ENTER"))
        hint_row(layout, "Change generation defaults in Add-on Preferences.", icon='INFO')

    def execute(self, context):
        context.scene.fbp_gen_camera = True
        return {'FINISHED'}

class FBP_OT_FitToCamera(Operator):
    bl_idname      = "fbp.fit_camera"
    bl_label       = "Fit to Camera"
    bl_description = "Fit the real image rectangle inside the active camera"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cam = context.scene.camera
        if not cam:
            self.report({'WARNING'}, "No active camera!")
            return {'CANCELLED'}
        rigs = get_selected_rigs(context)
        if not rigs:
            return {'CANCELLED'}
        context.view_layer.update()
        context.evaluated_depsgraph_get().update()
        for rig in rigs:
            apply_fit_to_camera(context, rig, cam)
        return {'FINISHED'}

class FBP_OT_MultiFitCamera(Operator):
    bl_idname      = "fbp.multi_fit_camera"
    bl_label       = "Fit All to Camera"
    bl_description = "Fit all selected real image rectangles inside the active camera"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cam = context.scene.camera
        if not cam:
            self.report({'WARNING'}, "No active camera!")
            return {'CANCELLED'}
        rigs = get_selected_rigs(context)
        if not rigs:
            self.report({'WARNING'}, "No rig selected!")
            return {'CANCELLED'}
        context.view_layer.update()
        context.evaluated_depsgraph_get().update()
        for rig in rigs:
            apply_fit_to_camera(context, rig, cam)
        self.report({'INFO'}, f"{len(rigs)} layer(s) fitted to camera")
        return {'FINISHED'}

class FBP_OT_SetCurrentFrame(Operator):
    bl_idname      = "fbp.set_current_frame"
    bl_label       = "Set to Current Frame"
    bl_description = "Set the animation start to the current timeline frame"
    bl_options     = {'UNDO'}

    def execute(self, context):
        for rig in get_selected_rigs(context):
            rig.fbp_start_frame = context.scene.frame_current
        return {'FINISHED'}

class FBP_OT_ToggleCollectionCollapse(Operator):
    bl_idname      = "fbp.toggle_collection_collapse"
    bl_label       = "Collapse Collection"
    bl_description = "Open or collapse this collection in the Frame By Plane layer tree"
    bl_options     = {'INTERNAL'}

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        coll.fbp_collapsed = not bool(getattr(coll, "fbp_collapsed", False))
        _fbp_refresh_layer_tree(context, update_compositor=False)
        return {'FINISHED'}

class FBP_OT_TogglePendingCollectionCollapse(Operator):
    bl_idname = "fbp.toggle_pending_collection_collapse"
    bl_label = "Open Setup Collection"
    bl_description = "Open or collapse this collection in the Multiplane Setup preview"
    bl_options = {'INTERNAL'}

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")

    def execute(self, context):
        sc = context.scene
        name = self.collection_name or 'Unsorted'
        set_pending_collection_open(sc, name, not pending_collection_is_open(sc, name))
        _fbp_refresh_pending_tree(context)
        return {'FINISHED'}


class FBP_OT_SetPendingCollectionsOpen(Operator):
    bl_idname = "fbp.set_pending_collections_open"
    bl_label = "Expand or Collapse Setup Collections"
    bl_description = "Expand or collapse every collection in the Multiplane Setup tree"
    bl_options = {'INTERNAL'}

    open_all: BoolProperty(description="Expand every setup collection when enabled, or collapse every setup collection when disabled.", default=False)

    def execute(self, context):
        scene = context.scene
        if not self.open_all:
            scene.fbp_pending_open_collections = ""
            _fbp_refresh_pending_tree(context)
            return {'FINISHED'}

        paths = set()
        for item in getattr(scene, 'fbp_pending_planes', ()):
            raw = str(getattr(item, 'collection_name', '') or '').strip()
            if not raw:
                continue
            parts = [part.strip() for part in raw.split('/') if part.strip()]
            for depth in range(1, len(parts) + 1):
                paths.add(' / '.join(parts[:depth]))
        scene.fbp_pending_open_collections = '|'.join(sorted(paths, key=natural_sort_key))
        _fbp_refresh_pending_tree(context)
        return {'FINISHED'}

class FBP_OT_SelectCollectionLayers(Operator):
    bl_idname      = "fbp.select_collection_layers"
    bl_label       = "Toggle Collection Layer Selection"
    bl_description = "Select or deselect all Frame By Plane and Grease Pencil layers inside this collection. Shift-click adds/removes without clearing other selections"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")
    extend: BoolProperty(description="Add this collection to the current layer selection instead of replacing the existing selection.", default=False)

    def invoke(self, context, event):
        self.extend = bool(event.shift)
        return self.execute(context)

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        scene = getattr(context, "scene", None)
        tree_index = -1
        if scene is not None:
            try:
                tree_index = next((
                    index for index, row in enumerate(getattr(scene, "fbp_layer_tree_rows", ()) or ())
                    if str(getattr(row, "row_type", "") or "") == "GROUP"
                    and str(getattr(row, "collection_name", "") or "") == coll.name
                ), -1)
                if tree_index >= 0:
                    scene.fbp_layer_tree_rows_idx = tree_index
            except FBP_DATA_ERRORS:
                tree_index = -1
            _fbp_arm_collection_row_selection_guard(scene, coll.name, tree_index)
        members = list(_collection_rigs_for_ui(coll))
        members.extend(_collection_gp_canvases_for_ui(coll))
        members = [member for member in members if object_in_view_layer(member, context)]
        if not members:
            return {'CANCELLED'}
        selectable = [member for member in members if not bool(getattr(member, 'hide_select', False))]
        if not selectable:
            return {'CANCELLED'}
        all_selected = all(member.select_get() for member in selectable)
        target_state = not all_selected
        if not self.extend and target_state:
            _fbp_deselect_layer_objects(context)
        for member in selectable:
            try:
                member.select_set(target_state)
            except ReferenceError:
                continue
        if target_state:
            active = selectable[-1]
            context.view_layer.objects.active = active
            for i, item in enumerate(context.scene.fbp_layers):
                try:
                    if item.obj == active:
                        context.scene.fbp_layer_stack_index = i
                        break
                except ReferenceError:
                    pass
        return {'FINISHED'}


class FBP_OT_ToggleCollectionState(Operator):
    bl_idname = "fbp.toggle_collection_state"
    bl_label = "Toggle Collection State"
    bl_description = "Toggle one collection control after resolving the current Blender datablock"
    bl_options = {'UNDO', 'INTERNAL'}

    collection_name: StringProperty(
        description="Exact collection name resolved only when the operator executes",
        default="",
    )
    state: EnumProperty(
        name="State",
        items=(
            ('VISIBLE', "Visibility", "Show or hide collection layers"),
            ('SOLO', "Solo", "Solo or unsolo collection layers"),
            ('HOLDOUT', "Holdout", "Toggle holdout on collection layers"),
            ('PLANE_LOCK', "Plane Selectability", "Toggle linked plane selectability"),
            ('LOCK', "Lock", "Lock or unlock collection layers"),
            ('SELECT', "Selection", "Select or deselect collection layers"),
        ),
        default='VISIBLE',
    )

    def execute(self, context):
        if fbp_registration_busy():
            return {'CANCELLED'}
        collection = bpy.data.collections.get(str(self.collection_name or ""))
        if collection is None:
            return {'CANCELLED'}
        handlers = {
            'VISIBLE': (get_collection_visible, set_collection_visible),
            'SOLO': (get_collection_solo, set_collection_solo),
            'HOLDOUT': (get_collection_holdout, set_collection_holdout),
            'PLANE_LOCK': (get_collection_plane_locked, set_collection_plane_locked),
            'LOCK': (get_collection_locked, set_collection_locked),
            'SELECT': (get_collection_selected, set_collection_selected),
        }
        getter, setter = handlers.get(str(self.state or ""), (None, None))
        if getter is None or setter is None:
            return {'CANCELLED'}
        try:
            setter(collection, not bool(getter(collection)))
            scene = getattr(context, "scene", None)
            if scene is not None:
                scene.fbp_layer_tree_signature = ""
            _fbp_refresh_layer_tree(context, update_compositor=False)
            return {'FINISHED'}
        except FBP_DATA_IO_ERRORS as exc:
            fbp_warn("Could not toggle collection state", exc)
            return {'CANCELLED'}


class FBP_OT_ToggleCollectionVisibility(Operator):
    bl_idname      = "fbp.toggle_collection_visibility"
    bl_label       = "Toggle Collection Visibility"
    bl_description = "Hide/show this collection and all its Frame By Plane layers"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")

    def execute(self, context):
        if fbp_registration_busy():
            return {'CANCELLED'}
        coll = bpy.data.collections.get(str(self.collection_name or ""))
        if coll is None:
            return {'CANCELLED'}
        try:
            set_collection_visible(coll, not bool(get_collection_visible(coll)))
            _fbp_refresh_layer_tree(context, update_compositor=False)
        except FBP_DATA_IO_ERRORS:
            return {'CANCELLED'}
        return {'FINISHED'}

class FBP_OT_ToggleCollectionLock(Operator):
    bl_idname      = "fbp.toggle_collection_lock"
    bl_label       = "Toggle Collection Lock"
    bl_description = "Lock or unlock all Frame By Plane and Grease Pencil layers inside this collection"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")

    def execute(self, context):
        if fbp_registration_busy():
            return {'CANCELLED'}
        coll = bpy.data.collections.get(str(self.collection_name or ""))
        if coll is None:
            return {'CANCELLED'}
        try:
            new_state = not bool(get_collection_locked(coll))
            # Keep collection and plane locks synchronized: locking a collection also
            # locks its linked image/color planes.
            set_collection_locked(coll, new_state)
            set_collection_plane_locked(coll, new_state)
            _fbp_refresh_layer_tree(context, update_compositor=False)
        except FBP_DATA_IO_ERRORS:
            return {'CANCELLED'}
        return {'FINISHED'}

class FBP_OT_DeleteLayerCollection(Operator):
    bl_idname = "fbp.delete_layer_collection"
    bl_label = "Delete Collection"
    bl_description = "Remove this collection while preserving its layers and child collections in the parent collection"
    bl_options = {'UNDO'}

    collection_name: StringProperty(
        description="Exact Frame By Plane collection to remove",
        default="",
    )

    def execute(self, context):
        scene = getattr(context, "scene", None)
        collection = bpy.data.collections.get(str(self.collection_name or ""))
        root = getattr(scene, "collection", None) if scene is not None else None
        if scene is None or collection is None or collection == root:
            return {'CANCELLED'}

        parent = _fbp_canonical_collection_parent(scene, collection) or root
        if parent is None or parent == collection:
            return {'CANCELLED'}

        try:
            direct_objects = tuple(getattr(collection, "objects", ()) or ())
            child_collections = tuple(getattr(collection, "children", ()) or ())
        except FBP_DATA_ERRORS:
            return {'CANCELLED'}

        try:
            # Preserve the hierarchy contents. Deleting a folder in the Layer
            # List behaves like removing a grouping container, not deleting art.
            for child in child_collections:
                if child is None or child == parent:
                    continue
                if child not in tuple(getattr(parent, "children", ()) or ()):
                    parent.children.link(child)
            for obj in direct_objects:
                if obj is None:
                    continue
                if obj not in tuple(getattr(parent, "objects", ()) or ()):
                    parent.objects.link(obj)
                _fbp_set_stack_object_visual_collection_name(obj, parent.name)

            # Remove every scene-tree link before deleting the datablock. This
            # also repairs collections accidentally linked below multiple parents.
            for owner in tuple(_fbp_collection_parents(root, collection)):
                try:
                    owner.children.unlink(collection)
                except FBP_DATA_IO_ERRORS:
                    pass
            bpy.data.collections.remove(collection, do_unlink=True)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not delete Layer List collection", exc)
            return {'CANCELLED'}

        _fbp_clear_collection_row_selection_guard()
        try:
            scene.fbp_layer_tree_signature = ""
        except FBP_DATA_ERRORS:
            pass
        _fbp_refresh_layer_tree(context)
        try:
            rows = getattr(scene, "fbp_layer_tree_rows", ()) or ()
            parent_index = next((
                index for index, row in enumerate(rows)
                if str(getattr(row, "row_type", "") or "") == "GROUP"
                and str(getattr(row, "collection_name", "") or "") == parent.name
            ), -1)
            if parent_index >= 0:
                scene.fbp_layer_tree_rows_idx = parent_index
            elif rows:
                scene.fbp_layer_tree_rows_idx = min(
                    max(0, int(getattr(scene, "fbp_layer_tree_rows_idx", 0) or 0)),
                    len(rows) - 1,
                )
        except FBP_DATA_ERRORS:
            pass
        self.report({'INFO'}, f"Deleted collection: {self.collection_name}")
        return {'FINISHED'}


class FBP_OT_DeleteCollectionLayers(Operator):
    bl_idname      = "fbp.delete_collection_layers"
    bl_label       = "Delete Collection Layers"
    bl_description = "Delete all Frame By Plane and Grease Pencil layers inside this collection. The collection itself remains"
    bl_options     = {'UNDO'}

    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", default="")

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll:
            return {'CANCELLED'}
        rigs = list(_collection_rigs_for_ui(coll))
        gp_canvases = list(_collection_gp_canvases_for_ui(coll))
        deleted_gp = 0
        try:
            from .grease_pencil_bridge import delete_gp_canvas
            for canvas in gp_canvases:
                deleted, _users, _error = delete_gp_canvas(context, canvas)
                deleted_gp += int(bool(deleted))
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not delete Grease Pencil collection layers", exc)
        deleted_rigs = delete_fbp_rigs(context, rigs)
        deleted = int(deleted_rigs) + int(deleted_gp)
        self.report({'INFO'}, f"Deleted {deleted} layer(s) from {coll.name}")
        return {'FINISHED'} if deleted else {'CANCELLED'}
