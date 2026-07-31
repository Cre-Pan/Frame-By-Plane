"""Focused Frame By Plane operator module."""

import json

import bpy
from bpy.props import (
    StringProperty,
)
from bpy.types import Operator

from .constants import fbp_icon
from .builder import build_fbp_color_rig, set_plane_mesh_extension
from .materials import (
    copy_scene_preview_ramp_to_rig,
    fbp_apply_holdout_materials_to_rig,
    fbp_is_native_holdout_plane,
    restore_original_materials_from_holdout,
    rig_holdout_is_active,
)
from .layers import (
    _collection_rigs_for_ui,
    fbp_active_work_collection,
    get_selected_rigs,
    is_fbp_layer_object,
    iter_scene_fbp_rigs,
    object_in_view_layer,
)
from .scene_sync import sync_layer_collection
from .runtime import fbp_set_rna_property_silent, FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS
from .core import update_object_padding_cb
from .ui_style import configure_layout, hint_row, section_gap, section_header
from .operator_common import (
    _fbp_refresh_layer_tree,
    fbp_default_color_plane_name,
)


def _focus_crop_extend_controls(context, effect_id):
    """Select Crop/Extend in the real effect stack and reveal its handles."""
    rigs = list(get_selected_rigs(context) or ())
    if not rigs:
        return False
    effect_id = str(effect_id or "").upper()
    if effect_id not in {"CROP", "EXTEND"}:
        return False
    try:
        context.scene.fbp_effects_view = "2D"
        from .geometry_nodes import (
            _fbp_select_effect_row,
            fbp_add_effect,
            fbp_effect_is_active,
        )
        from .effect_controls import sync_active_effect_controls
        selected = False
        for rig in rigs:
            if not fbp_effect_is_active(rig, effect_id):
                fbp_add_effect(rig, effect_id)
            selected = _fbp_select_effect_row(rig, effect_id, rigs) or selected
        if not selected:
            return False
        # This explicit UNDO operator owns helper creation, unlike passive Panel
        # redraw callbacks. The same current-generation handles are therefore
        # available whether Crop/Extend was opened from Effects or the Z Pie.
        sync_active_effect_controls(
            context,
            select_active=True,
            create_missing=True,
        )
        return True
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _crop_extend_popup_rigs(operator, context, *, capture=False):
    """Resolve the dialog targets without silently following later selection changes."""
    if capture:
        rigs = tuple(get_selected_rigs(context) or ())
        try:
            operator.target_names = json.dumps(
                [str(getattr(rig, "name", "") or "") for rig in rigs if rig is not None]
            )
        except (AttributeError, TypeError, ValueError):
            pass
        return rigs

    names = ()
    try:
        decoded = json.loads(str(getattr(operator, "target_names", "") or "[]"))
        if isinstance(decoded, list):
            names = tuple(str(name or "") for name in decoded if str(name or ""))
    except (TypeError, ValueError):
        names = ()
    if names:
        objects = getattr(getattr(bpy, "data", None), "objects", None)
        get_object = getattr(objects, "get", None)
        if callable(get_object):
            return tuple(
                rig for rig in (get_object(name) for name in names)
                if rig is not None and is_fbp_layer_object(rig)
            )
    return tuple(get_selected_rigs(context) or ())


def _invoke_crop_extend_popup(operator, context, event, mode):
    rigs = _crop_extend_popup_rigs(operator, context, capture=True)
    if not rigs:
        operator.report({'WARNING'}, "Select a Frame By Plane layer first")
        return {'CANCELLED'}
    try:
        from .live_tutorial import fbp_notify_tutorial_action
        fbp_notify_tutorial_action(context, "image_open_crop")
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    if not _focus_crop_extend_controls(context, mode):
        operator.report({'WARNING'}, f"Could not activate {str(mode).title()} controls")
        return {'CANCELLED'}
    return context.window_manager.invoke_props_dialog(operator, width=400)


def _draw_crop_extend_popup(operator, context, mode):
    layout = configure_layout(operator.layout)
    selected = _crop_extend_popup_rigs(operator, context)
    if not selected:
        hint_row(
            layout,
            "Target layer no longer available",
            icon="ERROR",
            disabled=False,
        )
        return False

    rig = selected[0]
    is_crop = str(mode or "CROP").upper() == "CROP"
    section_header(
        layout,
        "Crop" if is_crop else "Extend",
        icon=fbp_icon("MOD_BOOLEAN" if is_crop else "FULLSCREEN_ENTER"),
    )
    hint_row(
        layout,
        f"{len(selected)} selected layers" if len(selected) > 1 else rig.name,
        icon="RESTRICT_SELECT_OFF",
        disabled=False,
    )
    box = layout.box()
    configure_layout(box)
    section_header(
        box,
        "Image Bounds" if is_crop else "Canvas Bounds",
        icon="FULLSCREEN_EXIT" if is_crop else "FULLSCREEN_ENTER",
    )
    prefix = "fbp_crop" if is_crop else "fbp_extend"
    if not is_crop:
        box.prop(rig, "fbp_extend_mode", text="Mode")
    box.prop(rig, f"{prefix}_top", text="Top", slider=True)
    row = box.row(align=True)
    row.prop(rig, f"{prefix}_left", text="Left", slider=True)
    row.prop(rig, f"{prefix}_right", text="Right", slider=True)
    box.prop(rig, f"{prefix}_bottom", text="Bottom", slider=True)
    section_gap(layout)
    layout.operator(
        "fbp.reset_crop" if is_crop else "fbp.reset_extend",
        text="Reset Crop" if is_crop else "Reset Extend",
        icon=fbp_icon("FILE_REFRESH"),
    )
    return True


def _apply_crop_extend_popup(operator, context):
    selected = _crop_extend_popup_rigs(operator, context)
    if not selected:
        operator.report({'WARNING'}, "No Frame By Plane layer remains selected")
        return {'CANCELLED'}
    for rig in selected:
        update_object_padding_cb(rig, context)
    return {'FINISHED'}


class FBP_OT_CreateColorPlane(Operator):
    bl_idname = "fbp.create_color_plane"
    bl_label = "Create Color Plane"
    bl_description = "Create a rigged camera-ratio color, gradient or holdout plane"
    bl_options = {'REGISTER', 'UNDO'}

    plane_type: StringProperty(
        name="Plane Type",
        description="Optional explicit procedural plane type used by the creation menu",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        sc = context.scene
        requested = str(getattr(self, "plane_type", "") or "").upper()
        kind = requested if requested in {'CUSTOM', 'GRADIENT', 'HOLDOUT'} else getattr(sc, "fbp_color_plane_type", 'CUSTOM')
        gradient_settings = None
        if kind == 'HOLDOUT':
            color = (0.0, 0.0, 0.0, 1.0)
            name = fbp_default_color_plane_name('HOLDOUT', color)
            holdout = True
        elif kind == 'GRADIENT':
            color = tuple(sc.fbp_gradient_color_b)
            name = fbp_default_color_plane_name('GRADIENT', color)
            holdout = False
            gradient_settings = {
                'mode': sc.fbp_gradient_mode, 'kind': sc.fbp_gradient_kind,
                'color_a': tuple(sc.fbp_gradient_color_a), 'color_b': tuple(sc.fbp_gradient_color_b),
                'reverse': bool(sc.fbp_gradient_reverse),
                'offset_x': float(getattr(sc, 'fbp_gradient_offset_x', 0.0)),
                'offset_y': float(getattr(sc, 'fbp_gradient_offset_y', 0.0)),
                'scale_x': float(getattr(sc, 'fbp_gradient_scale_x', 1.0)),
                'scale_y': float(getattr(sc, 'fbp_gradient_scale_y', 1.0)),
                'rotation': float(getattr(sc, 'fbp_gradient_rotation', 0.0)),
            }
        else:
            color = tuple(sc.fbp_color_plane_color)
            name = fbp_default_color_plane_name('SOLID', color)
            holdout = False
        coll = fbp_active_work_collection(context) or getattr(context, 'collection', None) or sc.collection
        try:
            if coll is not None:
                coll.is_fbp_collection = True
        except FBP_DATA_ERRORS:
            pass
        rig = build_fbp_color_rig(context, name, color, sc.fbp_color_plane_emission, holdout, target_collection=coll, gradient_settings=gradient_settings)
        if gradient_settings:
            copy_scene_preview_ramp_to_rig(sc, rig)
        sync_layer_collection(context)
        bpy.ops.object.select_all(action='DESELECT')
        if object_in_view_layer(rig, context):
            rig.select_set(True)
            context.view_layer.objects.active = rig
        sc.fbp_show_create_tools = False
        self.report({'INFO'}, f"Created {rig.name}")
        return {'FINISHED'}

class FBP_OT_ResetCrop(Operator):
    bl_idname = "fbp.reset_crop"
    bl_label = "Reset Crop"
    bl_description = "Reset Crop values on all selected Frame By Plane layers"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rigs = get_selected_rigs(context)
        for rig in rigs:
            for prop in ('fbp_crop_top', 'fbp_crop_left', 'fbp_crop_right', 'fbp_crop_bottom'):
                fbp_set_rna_property_silent(rig, prop, 0.0)
            set_plane_mesh_extension(
                rig,
                getattr(rig, 'fbp_extend_left', 0.0), getattr(rig, 'fbp_extend_right', 0.0),
                getattr(rig, 'fbp_extend_bottom', 0.0), getattr(rig, 'fbp_extend_top', 0.0),
                getattr(rig, 'fbp_extend_mode', 'MIRROR'),
                0.0, 0.0, 0.0, 0.0,
            )
        self.report({'INFO'}, f"Reset Crop on {len(rigs)} layer(s)")
        return {'FINISHED'} if rigs else {'CANCELLED'}

class FBP_OT_ResetExtend(Operator):
    bl_idname = "fbp.reset_extend"
    bl_label = "Reset Extend"
    bl_description = "Reset Extend values on all selected Frame By Plane layers"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rigs = get_selected_rigs(context)
        for rig in rigs:
            for prop in ('fbp_extend_top', 'fbp_extend_left', 'fbp_extend_right', 'fbp_extend_bottom'):
                fbp_set_rna_property_silent(rig, prop, 0.0)
            try:
                from .effect_controls import update_extend_handle_limits
                update_extend_handle_limits(rig, reset=True)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            set_plane_mesh_extension(
                rig, 0.0, 0.0, 0.0, 0.0,
                getattr(rig, 'fbp_extend_mode', 'MIRROR'),
                getattr(rig, 'fbp_crop_left', 0.0), getattr(rig, 'fbp_crop_right', 0.0),
                getattr(rig, 'fbp_crop_bottom', 0.0), getattr(rig, 'fbp_crop_top', 0.0),
            )
        self.report({'INFO'}, f"Reset Extend on {len(rigs)} layer(s)")
        return {'FINISHED'} if rigs else {'CANCELLED'}


class FBP_OT_FocusCropExtend(Operator):
    """Reveal the existing spatial Crop/Extend handles without a popup."""

    bl_idname = "fbp.focus_crop_extend"
    bl_label = "Edit Crop / Expand"
    bl_description = "Select Crop or Expand and edit it directly with the viewport handles"
    bl_options = {'REGISTER', 'UNDO'}

    mode: StringProperty(
        name="Mode",
        description="Spatial bounds controller to reveal",
        default="CROP",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return bool(get_selected_rigs(context))

    def execute(self, context):
        mode = str(self.mode or "CROP").upper()
        if mode not in {"CROP", "EXTEND"}:
            return {'CANCELLED'}
        try:
            from .live_tutorial import fbp_notify_tutorial_action
            fbp_notify_tutorial_action(context, "image_open_crop")
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        if not _focus_crop_extend_controls(context, mode):
            self.report({'WARNING'}, "Select a Frame By Plane layer first")
            return {'CANCELLED'}
        label = "Crop" if mode == "CROP" else "Expand"
        self.report({'INFO'}, f"{label}: drag the viewport edge handles")
        return {'FINISHED'}

class FBP_OT_PopupCrop(Operator):
    bl_idname = "fbp.popup_crop"
    bl_label = "Crop"
    bl_description = "Crop the visible image borders without changing the plane transform"
    bl_options = {'REGISTER', 'UNDO'}

    target_names: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        return _invoke_crop_extend_popup(self, context, event, "CROP")

    def draw(self, context):
        _draw_crop_extend_popup(self, context, "CROP")

    def execute(self, context):
        return _apply_crop_extend_popup(self, context)

class FBP_OT_PopupExtend(Operator):
    bl_idname = "fbp.popup_extend"
    bl_label = "Extend"
    bl_description = "Extend plane borders while keeping the central image unchanged"
    bl_options = {'REGISTER', 'UNDO'}

    target_names: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        return _invoke_crop_extend_popup(self, context, event, "EXTEND")

    def draw(self, context):
        _draw_crop_extend_popup(self, context, "EXTEND")

    def execute(self, context):
        return _apply_crop_extend_popup(self, context)

class FBP_OT_SetSelectedHoldout(Operator):
    bl_idname = "fbp.set_selected_holdout"
    bl_label = "Set Selected Holdout"
    bl_description = "Turn selected Frame By Plane planes into holdout masks"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = 0
        for rig in get_selected_rigs(context):
            if fbp_apply_holdout_materials_to_rig(rig):
                count += 1
        self.report({'INFO'}, f"Holdout applied to {count} layer(s)")
        return {'FINISHED'} if count else {'CANCELLED'}

class FBP_OT_HoldoutAllExceptSelected(Operator):
    bl_idname = "fbp.holdout_all_except_selected"
    bl_label = "Holdout All Except Selected"
    bl_description = "Apply holdout to every Frame By Plane layer except the selected ones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = set(get_selected_rigs(context))
        if not selected:
            self.report({'WARNING'}, "Select the layer(s) that should stay rendered")
            return {'CANCELLED'}
        count = 0
        for rig in iter_scene_fbp_rigs(context.scene):
            if rig in selected:
                restore_original_materials_from_holdout(rig)
                continue
            if fbp_apply_holdout_materials_to_rig(rig):
                count += 1
        self.report({'INFO'}, f"Holdout applied to {count} other layer(s)")
        return {'FINISHED'}

class FBP_OT_RestoreHoldoutMaterials(Operator):
    bl_idname = "fbp.restore_holdout_materials"
    bl_label = "Restore Holdout Materials"
    bl_description = "Restore materials changed by Frame By Plane holdout tools"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = 0
        for rig in iter_scene_fbp_rigs(context.scene):
            if restore_original_materials_from_holdout(rig):
                count += 1
        self.report({'INFO'}, f"Restored {count} layer(s)")
        return {'FINISHED'}

class FBP_OT_ToggleCollectionHoldout(Operator):
    bl_idname = "fbp.toggle_collection_holdout"
    bl_label = "Toggle Collection Holdout"
    bl_description = "Toggle alpha-aware holdout on all Frame By Plane layers in this collection"
    bl_options = {'REGISTER', 'UNDO'}

    collection_name: StringProperty(name="Collection", description="Frame By Plane collection to toggle as holdout")

    def execute(self, context):
        collection = bpy.data.collections.get(self.collection_name)
        if not collection:
            self.report({'WARNING'}, "Frame By Plane collection not found")
            return {'CANCELLED'}

        rigs = [rig for rig in _collection_rigs_for_ui(collection) if not fbp_is_native_holdout_plane(rig)]
        if not rigs:
            self.report({'WARNING'}, "No editable Frame By Plane layers found in this collection")
            return {'CANCELLED'}

        # If any child is already holdout, one click clears the whole folder.
        should_restore = any(rig_holdout_is_active(rig) for rig in rigs)
        count = 0
        if should_restore:
            for rig in rigs:
                if restore_original_materials_from_holdout(rig):
                    count += 1
            self.report({'INFO'}, f"Holdout disabled for {count} layer(s)")
        else:
            for rig in rigs:
                if fbp_apply_holdout_materials_to_rig(rig):
                    count += 1
            self.report({'INFO'}, f"Holdout enabled for {count} layer(s)")

        try:
            sync_layer_collection(context)
        except FBP_DATA_IO_ERRORS:
            pass
        _fbp_refresh_layer_tree(context)
        return {'FINISHED'}

class FBP_OT_ToggleLayerHoldout(Operator):
    bl_idname = "fbp.toggle_layer_holdout"
    bl_label = "Toggle Layer Holdout"
    bl_description = "Toggle alpha-aware holdout on this layer. Transparent pixels stay transparent; visible pixels become holdout"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(name="Layer", description="Name of the Frame By Plane control rig whose holdout state will be toggled. The operator resolves and validates the rig before modifying materials.")

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or not is_fbp_layer_object(rig):
            self.report({'WARNING'}, "Frame By Plane layer not found")
            return {'CANCELLED'}
        if rig_holdout_is_active(rig):
            if restore_original_materials_from_holdout(rig):
                self.report({'INFO'}, f"Restored {rig.name}")
                return {'FINISHED'}
            return {'CANCELLED'}
        if fbp_apply_holdout_materials_to_rig(rig):
            self.report({'INFO'}, f"Holdout enabled for {rig.name}")
            return {'FINISHED'}
        return {'CANCELLED'}
