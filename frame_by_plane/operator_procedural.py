"""Focused Frame by Plane operator module."""

import bpy
from bpy.props import (
    StringProperty,
)
from bpy.types import Operator

from .constants import FBP_PROJECT_COLLECTION_PREFIX, fbp_icon
from .builder import build_fbp_color_rig, set_plane_mesh_extension
from .materials import (
    copy_scene_preview_ramp_to_rig,
    fbp_apply_holdout_materials_to_rig,
    fbp_is_native_holdout_plane,
    restore_original_materials_from_holdout,
    rig_holdout_is_active,
)
from .layers import (
    get_or_create_child_collection,
    get_selected_rigs,
    is_fbp_layer_object,
    iter_fbp_rigs_in_collection,
    object_in_view_layer,
)
from .scene_sync import sync_layer_collection
from .runtime import fbp_set_rna_property_silent, FBP_DATA_IO_ERRORS
from .core import update_object_padding_cb
from .operator_common import (
    _fbp_refresh_layer_tree,
    fbp_default_color_plane_name,
)


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
        coll = get_or_create_child_collection(sc.collection, FBP_PROJECT_COLLECTION_PREFIX + "Color Planes", 'COLOR_09')
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
    bl_description = "Reset Crop values on all selected Frame by Plane layers"
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
                getattr(rig, 'fbp_extend_mode', 'EDGE'),
                0.0, 0.0, 0.0, 0.0,
            )
        self.report({'INFO'}, f"Reset Crop on {len(rigs)} layer(s)")
        return {'FINISHED'} if rigs else {'CANCELLED'}

class FBP_OT_ResetExtend(Operator):
    bl_idname = "fbp.reset_extend"
    bl_label = "Reset Extend"
    bl_description = "Reset Extend values on all selected Frame by Plane layers"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rigs = get_selected_rigs(context)
        for rig in rigs:
            for prop in ('fbp_extend_top', 'fbp_extend_left', 'fbp_extend_right', 'fbp_extend_bottom'):
                fbp_set_rna_property_silent(rig, prop, 0.0)
            set_plane_mesh_extension(
                rig, 0.0, 0.0, 0.0, 0.0,
                getattr(rig, 'fbp_extend_mode', 'EDGE'),
                getattr(rig, 'fbp_crop_left', 0.0), getattr(rig, 'fbp_crop_right', 0.0),
                getattr(rig, 'fbp_crop_bottom', 0.0), getattr(rig, 'fbp_crop_top', 0.0),
            )
        self.report({'INFO'}, f"Reset Extend on {len(rigs)} layer(s)")
        return {'FINISHED'} if rigs else {'CANCELLED'}

class FBP_OT_PopupCrop(Operator):
    bl_idname = "fbp.popup_crop"
    bl_label = "Crop"
    bl_description = "Crop the visible image borders without changing the plane transform"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if not get_selected_rigs(context):
            self.report({'WARNING'}, "Select a Frame by Plane layer first")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        selected = get_selected_rigs(context)
        rig = selected[0]
        layout = self.layout
        if len(selected) > 1:
            layout.label(text=f"{len(selected)} selected layers", icon=fbp_icon("MOD_BOOLEAN"))
        else:
            layout.label(text=rig.name, icon=fbp_icon("MOD_BOOLEAN"))
        box = layout.box()
        box.prop(rig, "fbp_crop_top", text="Top", slider=True)
        row = box.row(align=True)
        row.prop(rig, "fbp_crop_left", text="Left", slider=True)
        row.prop(rig, "fbp_crop_right", text="Right", slider=True)
        box.prop(rig, "fbp_crop_bottom", text="Bottom", slider=True)
        layout.operator("fbp.reset_crop", text="Reset Crop", icon=fbp_icon("FILE_REFRESH"))

    def execute(self, context):
        for rig in get_selected_rigs(context):
            update_object_padding_cb(rig, context)
        return {'FINISHED'}

class FBP_OT_PopupExtend(Operator):
    bl_idname = "fbp.popup_extend"
    bl_label = "Extend"
    bl_description = "Extend plane borders while keeping the central image unchanged"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if not get_selected_rigs(context):
            self.report({'WARNING'}, "Select a Frame by Plane layer first")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        selected = get_selected_rigs(context)
        rig = selected[0]
        layout = self.layout
        if len(selected) > 1:
            layout.label(text=f"{len(selected)} selected layers", icon=fbp_icon("FULLSCREEN_ENTER"))
        else:
            layout.label(text=rig.name, icon=fbp_icon("FULLSCREEN_ENTER"))
        box = layout.box()
        box.prop(rig, "fbp_extend_mode", text="Mode")
        box.prop(rig, "fbp_extend_top", text="Top", slider=True)
        row = box.row(align=True)
        row.prop(rig, "fbp_extend_left", text="Left", slider=True)
        row.prop(rig, "fbp_extend_right", text="Right", slider=True)
        box.prop(rig, "fbp_extend_bottom", text="Bottom", slider=True)
        layout.operator("fbp.reset_extend", text="Reset Extend", icon=fbp_icon("FILE_REFRESH"))

    def execute(self, context):
        for rig in get_selected_rigs(context):
            update_object_padding_cb(rig, context)
        return {'FINISHED'}

class FBP_OT_SetSelectedHoldout(Operator):
    bl_idname = "fbp.set_selected_holdout"
    bl_label = "Set Selected Holdout"
    bl_description = "Turn selected Frame by Plane planes into holdout masks"
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
    bl_description = "Apply holdout to every Frame by Plane layer except the selected ones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = set(get_selected_rigs(context))
        if not selected:
            self.report({'WARNING'}, "Select the layer(s) that should stay rendered")
            return {'CANCELLED'}
        count = 0
        for rig in [obj for obj in context.scene.objects if is_fbp_layer_object(obj)]:
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
    bl_description = "Restore materials changed by Frame by Plane holdout tools"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = 0
        for rig in [obj for obj in context.scene.objects if is_fbp_layer_object(obj)]:
            if restore_original_materials_from_holdout(rig):
                count += 1
        self.report({'INFO'}, f"Restored {count} layer(s)")
        return {'FINISHED'}

class FBP_OT_ToggleCollectionHoldout(Operator):
    bl_idname = "fbp.toggle_collection_holdout"
    bl_label = "Toggle Collection Holdout"
    bl_description = "Toggle alpha-aware holdout on all Frame by Plane layers in this collection"
    bl_options = {'REGISTER', 'UNDO'}

    collection_name: StringProperty(name="Collection", description="Frame by Plane collection to toggle as holdout")

    def execute(self, context):
        collection = bpy.data.collections.get(self.collection_name)
        if not collection:
            self.report({'WARNING'}, "Frame by Plane collection not found")
            return {'CANCELLED'}

        rigs = [rig for rig in iter_fbp_rigs_in_collection(collection, True) if not fbp_is_native_holdout_plane(rig)]
        if not rigs:
            self.report({'WARNING'}, "No editable Frame by Plane layers found in this collection")
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
            self.report({'WARNING'}, "Frame by Plane layer not found")
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
