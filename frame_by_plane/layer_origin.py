"""Set Origin for Frame By Plane layers.

A layer is a rig (the selectable controller, which holds the transform and
its keys) with the image plane parented to it. Blender's own Set Origin acts
on the rig's wire mesh: with the wire hidden it has no vertices and nothing
happens, and Origin to 3D Cursor hides the shift in the plane's parent
inverse matrix, which the transform box and Reset do not expect.

Set Layer Origin moves the rig's origin to a point and puts everything that
hangs on the rig back where it was, so the drawing does not move:

* the rig location (and its location keys) move by the shift;
* the plane and the rig's other children move back by the same shift inside
  the rig (their location, or their parent inverse when they use one);
* the transform box anchor keeps its place;
* the rig wire is rebuilt around the plane (a Custom wire is shifted).

Origin to Geometry puts the origin in the middle of the plane as Crop and
Extend leave it, so after Crop Alpha it lands in the middle of the drawing.
"""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator
from mathutils import Matrix, Vector

from .runtime import FBP_DATA_ERRORS, fbp_action_fcurves


FBP_LAYER_ORIGIN_ITEMS = (
    ('GEOMETRY', "Origin to Geometry",
     "Move the layer origin to the middle of the plane as Crop and Extend leave it "
     "(after Crop Alpha: the middle of the drawing). The drawing does not move"),
    ('CURSOR', "Origin to 3D Cursor",
     "Move the layer origin to the 3D cursor. The drawing does not move"),
    ('GEOMETRY_TO_ORIGIN', "Geometry to Origin",
     "Move the plane inside the layer so its middle sits on the layer origin"),
)

_ANCHOR_KEY = "fbp_box_anchor"


def _is_identity(matrix, tolerance=1.0e-6):
    identity = Matrix.Identity(4)
    return all(
        abs(matrix[row][col] - identity[row][col]) <= tolerance
        for row in range(4) for col in range(4)
    )


def layer_geometry_center(rig):
    """World position of the middle of the layer's plane, or None.

    Uses the plane bounds after Crop and Extend (as the mesh and the
    transform box use them); falls back to the plane's bounding box.
    """
    plane = getattr(rig, "fbp_plane_target", None)
    if plane is None:
        return None
    local = None
    try:
        from .builder import fbp_plane_reference_bounds
        min_x, max_x, min_y, max_y = fbp_plane_reference_bounds(rig)[2]
        if max_x - min_x > 1.0e-9 and max_y - min_y > 1.0e-9:
            local = Vector(((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, 0.0))
    except (ImportError, TypeError, ValueError, IndexError) + FBP_DATA_ERRORS:
        local = None
    if local is None:
        try:
            corners = [Vector(corner) for corner in plane.bound_box]
            local = sum(corners, Vector()) / 8.0
        except (*FBP_DATA_ERRORS, TypeError, ZeroDivisionError):
            return None
    try:
        return plane.matrix_world @ local
    except FBP_DATA_ERRORS:
        return None


def _rest_linear(rig):
    """Rotation and scale that turn rig space into the rig's parent space.

    Motion animates the delta transforms, so a rig with Motion uses its
    captured Motion base instead of the delta values of the current frame.
    """
    rotation_mode = str(getattr(rig, "rotation_mode", "XYZ"))
    if rotation_mode == 'QUATERNION':
        rotation = rig.rotation_quaternion.to_matrix()
    elif rotation_mode == 'AXIS_ANGLE':
        angle, *axis = tuple(rig.rotation_axis_angle)
        rotation = Matrix.Rotation(angle, 3, Vector(axis))
    else:
        rotation = rig.rotation_euler.to_matrix()
    scale = Vector(rig.scale)
    try:
        has_motion = bool(getattr(rig, "fbp_motion_base_captured", False)) and len(rig.fbp_motions) > 0
    except FBP_DATA_ERRORS:
        has_motion = False
    if has_motion:
        from mathutils import Euler
        delta_rotation = Euler(tuple(rig.fbp_motion_base_rotation), 'XYZ').to_matrix()
        delta_scale = Vector(tuple(rig.fbp_motion_base_scale))
    else:
        if rotation_mode == 'QUATERNION' or rotation_mode == 'AXIS_ANGLE':
            delta_rotation = rig.delta_rotation_quaternion.to_matrix()
        else:
            delta_rotation = rig.delta_rotation_euler.to_matrix()
        delta_scale = Vector(rig.delta_scale)
    scale_matrix = Matrix.Diagonal(Vector((
        scale.x * delta_scale.x, scale.y * delta_scale.y, scale.z * delta_scale.z,
    )))
    return rotation @ delta_rotation @ scale_matrix


def _offset_location_keys(obj, offset):
    """Shift every location key (and its handles) of *obj* by *offset*."""
    curves = fbp_action_fcurves(obj)
    if curves is None:
        return False
    keyed = False
    for curve in curves:
        if str(getattr(curve, "data_path", "")) != "location":
            continue
        index = int(getattr(curve, "array_index", 0))
        if index > 2:
            continue
        amount = float(offset[index])
        keyed = True
        for point in curve.keyframe_points:
            point.co.y += amount
            point.handle_left.y += amount
            point.handle_right.y += amount
        curve.update()
    return keyed


def _move_location(obj, offset):
    """Add *offset* to the location of *obj*, keyed or not."""
    keyed = _offset_location_keys(obj, offset)
    obj.location = Vector(obj.location) + Vector(offset)
    return keyed


def fbp_set_layer_origin(rig, world_point):
    """Move the rig origin to *world_point*; the drawing does not move.

    Returns True when something changed.
    """
    if rig is None or not bool(getattr(rig, "is_fbp_control", False)) or world_point is None:
        return False
    try:
        shift = rig.matrix_world.inverted_safe() @ Vector(world_point)
    except FBP_DATA_ERRORS:
        return False
    if shift.length <= 1.0e-7:
        return False
    try:
        _move_location(rig, _rest_linear(rig) @ shift)
        back = Matrix.Translation(-shift)
        for child in tuple(rig.children):
            if _is_identity(child.matrix_parent_inverse):
                _move_location(child, -shift)
            else:
                child.matrix_parent_inverse = back @ child.matrix_parent_inverse
        anchor = rig.get(_ANCHOR_KEY)
        if anchor is not None and len(anchor) >= 2:
            moved = (float(anchor[0]) - shift.x, float(anchor[1]) - shift.y)
            if abs(moved[0]) <= 1.0e-7 and abs(moved[1]) <= 1.0e-7:
                del rig[_ANCHOR_KEY]
            else:
                rig[_ANCHOR_KEY] = moved
    except FBP_DATA_ERRORS:
        return False
    _refresh_rig_wire(rig, shift)
    return True


def fbp_layer_geometry_to_origin(rig):
    """Move the plane inside the layer so its middle sits on the rig origin."""
    if rig is None or not bool(getattr(rig, "is_fbp_control", False)):
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    center = layer_geometry_center(rig)
    if plane is None or center is None:
        return False
    try:
        local = rig.matrix_world.inverted_safe() @ center
    except FBP_DATA_ERRORS:
        return False
    # Keep the plane's depth inside the rig: only slide it across the layer.
    offset = Vector((local.x, local.y, 0.0))
    if offset.length <= 1.0e-7:
        return False
    try:
        if _is_identity(plane.matrix_parent_inverse):
            _move_location(plane, -offset)
        else:
            plane.matrix_parent_inverse = Matrix.Translation(-offset) @ plane.matrix_parent_inverse
    except FBP_DATA_ERRORS:
        return False
    _refresh_rig_wire(rig, None)
    return True


def _refresh_rig_wire(rig, shift):
    try:
        shape = str(getattr(rig, "fbp_rig_shape", "DEFAULT") or "DEFAULT").upper()
        if shape == 'CUSTOM':
            if shift is not None and getattr(rig, "data", None) is not None:
                for vertex in rig.data.vertices:
                    vertex.co -= shift
                rig.data.update()
            return
        from .builder import fbp_apply_rig_shape
        fbp_apply_rig_shape(rig)
    except (ImportError, *FBP_DATA_ERRORS):
        pass


def _selected_layer_rigs(context):
    try:
        from .layers import get_selected_rigs
        return [
            rig for rig in (get_selected_rigs(context) or ())
            if bool(getattr(rig, "is_fbp_control", False))
        ]
    except (ImportError, *FBP_DATA_ERRORS):
        return []


class FBP_OT_LayerOriginSet(Operator):
    bl_idname = "fbp.layer_origin_set"
    bl_label = "Set Layer Origin"
    bl_description = "Move the origin of the selected Frame By Plane layers without moving the drawing"
    bl_options = {'REGISTER', 'UNDO'}

    type: EnumProperty(name="Type", items=FBP_LAYER_ORIGIN_ITEMS, default='GEOMETRY')

    @classmethod
    def description(cls, context, properties):
        for token, _label, text in FBP_LAYER_ORIGIN_ITEMS:
            if token == properties.type:
                return text
        return cls.bl_description

    @classmethod
    def poll(cls, context):
        return getattr(context, "mode", "OBJECT") == 'OBJECT' and bool(_selected_layer_rigs(context))

    def execute(self, context):
        rigs = _selected_layer_rigs(context)
        if not rigs:
            self.report({'WARNING'}, "Select a Frame By Plane layer first")
            return {'CANCELLED'}
        cursor = Vector(context.scene.cursor.location)
        changed = 0
        for rig in rigs:
            if self.type == 'CURSOR':
                done = fbp_set_layer_origin(rig, cursor)
            elif self.type == 'GEOMETRY_TO_ORIGIN':
                done = fbp_layer_geometry_to_origin(rig)
            else:
                done = fbp_set_layer_origin(rig, layer_geometry_center(rig))
            changed += int(bool(done))
        context.view_layer.update()
        for area in getattr(getattr(context, "screen", None), "areas", ()) or ():
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        if not changed:
            self.report({'INFO'}, "The origin is already there")
        return {'FINISHED'}


def draw_layer_origin_menu(layout):
    layout.operator_menu_enum(
        FBP_OT_LayerOriginSet.bl_idname, "type", text="Set Layer Origin", icon='OBJECT_ORIGIN',
    )


classes = (FBP_OT_LayerOriginSet,)


def register():
    from .registration import register_classes
    register_classes(classes)


def unregister():
    from .registration import unregister_classes
    unregister_classes(classes)
