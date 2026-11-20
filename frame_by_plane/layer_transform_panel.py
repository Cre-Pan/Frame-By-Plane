"""Layer transform where Blender shows the active object's transform.

A click on a layer selects its rig and makes the layer's image plane the
active object, so Properties > Modifiers shows the layer's effects. Blender's
own Transform fields (Properties > Object and the sidebar's Item tab) then
show the plane, which sits at zero inside the rig: typing or keying there
moves the plane away from its rig, and the keys land on an unselected object
the Graph Editor and Dope Sheet hide.

Properties > Object > Transform and a Layer Transform panel in the sidebar's
Item tab show the rig's Location, Rotation and Scale instead, the values
that place the layer, the box and the keys the Graph Editor lists. Every
field can be typed, keyed (I over a field, or the dot next to it) and copied
to all selected layers (Alt while editing, or right click > Copy All to
Selected), which lines layers up exactly.
"""

from __future__ import annotations

import bpy
from bpy.types import Panel

from .registration import register_classes, unregister_classes
from .runtime import FBP_DATA_ERRORS, fbp_action_fcurves


_PLANE_TRANSFORM_PATHS = (
    "location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
)


def layer_rig_for_plane(obj):
    """Return the rig when *obj* is a layer's image plane, else None.

    The rig itself, and any object that is not a layer plane, gives None:
    Blender's own Transform panel already shows the right object then.
    """
    if obj is None or bool(getattr(obj, "is_fbp_control", False)):
        return None
    try:
        rig = getattr(obj, "parent", None)
        if rig is None or not bool(getattr(rig, "is_fbp_control", False)):
            return None
        if getattr(rig, "fbp_plane_target", None) != obj:
            return None
        return rig
    except FBP_DATA_ERRORS:
        return None


def plane_has_transform_keys(plane):
    """True when the plane itself (not its rig) keys its transform."""
    try:
        curves = fbp_action_fcurves(plane)
        return curves is not None and any(
            str(getattr(curve, "data_path", "")) in _PLANE_TRANSFORM_PATHS
            for curve in curves
        )
    except FBP_DATA_ERRORS:
        return False


def draw_layer_transform(layout, rig):
    layout.use_property_split = True
    layout.use_property_decorate = True
    col = layout.column()
    row = col.row(align=True)
    row.prop(rig, "location")
    row.use_property_decorate = False
    row.prop(rig, "lock_location", text="", emboss=False, icon='DECORATE_UNLOCKED')

    mode = str(getattr(rig, "rotation_mode", "XYZ"))
    col = layout.column()
    row = col.row(align=True)
    if mode == 'QUATERNION':
        row.prop(rig, "rotation_quaternion", text="Rotation")
    elif mode == 'AXIS_ANGLE':
        row.prop(rig, "rotation_axis_angle", text="Rotation")
    else:
        row.prop(rig, "rotation_euler", text="Rotation")
    sub = row.column(align=True)
    sub.use_property_decorate = False
    sub.prop(rig, "lock_rotation", text="", emboss=False, icon='DECORATE_UNLOCKED')
    row = layout.row(align=True)
    row.prop(rig, "rotation_mode", text="Mode")
    row.label(text="", icon='BLANK1')

    col = layout.column()
    row = col.row(align=True)
    row.prop(rig, "scale")
    row.use_property_decorate = False
    row.prop(rig, "lock_scale", text="", emboss=False, icon='DECORATE_UNLOCKED')


def _draw_header_note(layout, rig, plane):
    col = layout.column(align=True)
    col.label(text=f"Layer: {rig.name}", icon='OBJECT_DATA')
    if plane is not None and plane_has_transform_keys(plane):
        warning = col.row()
        warning.alert = True
        warning.label(text="Plane has its own keys", icon='ERROR')


def draw_properties_transform_prepend(self, context):
    """Top of Properties > Object > Transform when the active object is a
    layer's plane: the layer (rig) transform first, then Blender's own
    fields, labelled as the plane's offset inside the layer."""
    plane = getattr(context, "object", None)
    rig = layer_rig_for_plane(plane)
    if rig is None:
        return
    layout = self.layout
    box = layout.box()
    _draw_header_note(box, rig, plane)
    draw_layer_transform(box, rig)
    layout.label(text="Plane offset inside the layer:")


class FBP_PT_LayerTransformSidebar(Panel):
    """The selected layer's transform, in the 3D View sidebar's Item tab."""

    bl_label = "Layer Transform"
    bl_idname = "FBP_PT_layer_transform_sidebar"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Item"

    @classmethod
    def poll(cls, context):
        if getattr(context, "mode", "") != 'OBJECT':
            return False
        active = getattr(context, "active_object", None)
        return layer_rig_for_plane(active) is not None or _plane_group_of(context) is not None

    def draw(self, context):
        plane = getattr(context, "active_object", None)
        rig = layer_rig_for_plane(plane)
        if rig is not None:
            _draw_header_note(self.layout, rig, plane)
            draw_layer_transform(self.layout, rig)
        group = _plane_group_of(context)
        if group is not None:
            from .group_controller import draw_group_controller

            box = self.layout.box()
            box.label(text=f"Group: {group.name}", icon='OUTLINER_COLLECTION')
            draw_group_controller(box, group)


def _plane_group_of(context):
    """The plane group of the active layer or controller, or ``None``."""
    try:
        from .group_controller import target_group
        return target_group(context)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


classes = (FBP_PT_LayerTransformSidebar,)


def _object_transform_panel():
    return getattr(bpy.types, "OBJECT_PT_transform", None)


def _remove_prepend(panel):
    # Drop this module's callback and stale copies left by an in-place reload.
    try:
        callbacks = panel._dyn_ui_initialize()
    except (AttributeError, TypeError):
        return
    for callback in tuple(callbacks):
        if (
            getattr(callback, "__name__", "") == draw_properties_transform_prepend.__name__
            and str(getattr(callback, "__module__", "")).endswith("layer_transform_panel")
        ):
            try:
                callbacks.remove(callback)
            except ValueError:
                pass


def register():
    if bool(getattr(bpy.app, "background", False)):
        return
    register_classes(classes)
    panel = _object_transform_panel()
    if panel is not None:
        _remove_prepend(panel)
        panel.prepend(draw_properties_transform_prepend)


def unregister():
    if bool(getattr(bpy.app, "background", False)):
        return
    panel = _object_transform_panel()
    if panel is not None:
        _remove_prepend(panel)
    unregister_classes(classes)
