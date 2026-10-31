"""Click selection that sees through the transparent pixels of image planes.

Frame By Plane image planes are not selectable themselves; a layer is picked
through its control rig. This operator runs before Blender's click select in
Object Mode: it walks the view ray through the scene, skips planes whose
pixel under the cursor is transparent and selects the layer of the first
visible pixel. Layers that show their rig wire are skipped (picked from the
wire) unless the "Rig Layers: Click Image Too" preference is on. Anything else
(no plane hit, a click on a rig wire, a regular object in front, a locked
layer) is passed through to Blender's own selection untouched.
"""

from bpy.props import BoolProperty
from bpy.types import Operator
from mathutils import Vector, geometry

from .runtime import FBP_DATA_ERRORS


_MAX_STEPS = 64


def _fbp_rig_of_plane(obj):
    """Return the control rig that owns ``obj`` when it is an FBP image plane."""
    parent = getattr(obj, "parent", None)
    while parent is not None:
        if bool(getattr(parent, "is_fbp_control", False)) and getattr(parent, "fbp_plane_target", None) == obj:
            return parent
        parent = getattr(parent, "parent", None)
    return None


def _uv_at_hit(obj_eval, depsgraph, world_location, world_direction):
    """UV of the evaluated plane surface at a world hit, or ``None``."""
    try:
        inverse = obj_eval.matrix_world.inverted_safe()
        local_origin = inverse @ (world_location - world_direction * 1.0e-3)
        local_direction = (inverse.to_3x3() @ world_direction).normalized()
        hit, location, _normal, index = obj_eval.ray_cast(
            local_origin, local_direction, distance=1.0, depsgraph=depsgraph,
        )
        mesh = obj_eval.data
        if not hit or index < 0 or mesh is None:
            return None
        uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.active
        if uv_layer is None:
            return None
        polygon = mesh.polygons[index]
        loops = list(polygon.loop_indices)
        corners = [mesh.vertices[mesh.loops[loop].vertex_index].co for loop in loops]
        uvs = [uv_layer.data[loop].uv for loop in loops]
        for tri in range(1, len(loops) - 1):
            a, b, c = corners[0], corners[tri], corners[tri + 1]
            if geometry.intersect_point_tri(location, a, b, c) is None:
                continue
            mapped = geometry.barycentric_transform(
                location, a, b, c,
                uvs[0].to_3d(), uvs[tri].to_3d(), uvs[tri + 1].to_3d(),
            )
            return float(mapped.x), float(mapped.y)
    except (*FBP_DATA_ERRORS, IndexError, ValueError):
        return None
    return None


def _select_by_image_allowed(rig, by_image_with_rig):
    """Layers that show their rig are picked from the wire unless allowed."""
    from .builder import fbp_rig_wire_visible

    return bool(by_image_with_rig) or not fbp_rig_wire_visible(rig)


def _rig_wire_near_cursor(context, coord, radius):
    """True when a visible rig wire passes within ``radius`` pixels of ``coord``."""
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    from .builder import fbp_rig_wire_visible

    region = context.region
    region_data = context.region_data
    cx, cy = float(coord[0]), float(coord[1])
    limit = float(radius) * float(radius)
    for obj in tuple(getattr(context, "visible_objects", ()) or ()):
        try:
            if not bool(getattr(obj, "is_fbp_control", False)) or not fbp_rig_wire_visible(obj):
                continue
            if bool(getattr(obj, "hide_select", False)):
                continue
            mesh = obj.data
            matrix = obj.matrix_world
            points = [location_3d_to_region_2d(region, region_data, matrix @ vert.co) for vert in mesh.vertices]
            for edge in mesh.edges:
                a = points[edge.vertices[0]]
                b = points[edge.vertices[1]]
                if a is None or b is None:
                    continue
                dx, dy = b.x - a.x, b.y - a.y
                length = dx * dx + dy * dy
                t = 0.0 if length <= 1e-9 else max(0.0, min(1.0, ((cx - a.x) * dx + (cy - a.y) * dy) / length))
                px, py = a.x + dx * t - cx, a.y + dy * t - cy
                if px * px + py * py <= limit:
                    return True
        except (*FBP_DATA_ERRORS, IndexError):
            continue
    return False


def fbp_pick_layer_through_alpha(context, origin, direction, *, by_image_with_rig=False):
    """Return ``(rig, hit_fbp_plane)`` for a world ray.

    ``rig`` is the layer whose visible pixel is hit first, or ``None``.
    ``hit_fbp_plane`` tells whether the ray crossed any image plane; when it
    is False the click is left entirely to Blender.
    """
    from .builder import fbp_rig_alpha_visible_at_uv

    scene = context.scene
    depsgraph = context.evaluated_depsgraph_get()
    direction = Vector(direction).normalized()
    origin = Vector(origin)
    crossed_plane = False
    for _step in range(_MAX_STEPS):
        hit, location, _normal, _index, obj, _matrix = scene.ray_cast(depsgraph, origin, direction)
        if not hit or obj is None:
            return None, crossed_plane
        original = getattr(obj, "original", obj)
        rig = _fbp_rig_of_plane(original)
        if rig is None:
            # A regular object (or anything else) in front: Blender decides.
            return None, crossed_plane
        crossed_plane = True
        selectable = (
            not bool(getattr(rig, "hide_select", False))
            and rig.visible_get()
            and _select_by_image_allowed(rig, by_image_with_rig)
        )
        if selectable:
            uv = _uv_at_hit(obj, depsgraph, location, direction)
            visible = True
            if uv is not None:
                state = fbp_rig_alpha_visible_at_uv(rig, uv[0], uv[1], scene)
                visible = True if state is None else bool(state)
            if visible:
                return rig, True
        origin = location + direction * 1.0e-4
    return None, crossed_plane


def _ui_scale(context):
    try:
        return float(context.preferences.system.ui_scale) or 1.0
    except FBP_DATA_ERRORS:
        return 1.0


def _by_image_with_rig():
    try:
        from .interface_preferences import fbp_get_addon_preferences
        preferences = fbp_get_addon_preferences()
        return bool(getattr(preferences, "rig_select_by_image", False)) if preferences else False
    except (ImportError, AttributeError, ReferenceError, RuntimeError):
        return False


class FBP_OT_SelectThroughAlpha(Operator):
    """Select a layer by its visible pixels, clicking through transparency."""

    bl_idname = "fbp.select_through_alpha"
    bl_label = "Select Through Transparency"
    bl_description = "Select the layer under the cursor, ignoring transparent pixels of the layers in front"
    bl_options = {'REGISTER', 'UNDO'}

    toggle: BoolProperty(name="Toggle", default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return (
            getattr(context, "mode", "") == 'OBJECT'
            and getattr(getattr(context, "area", None), "type", "") == 'VIEW_3D'
            and getattr(context, "region_data", None) is not None
        )

    def invoke(self, context, event):
        from bpy_extras import view3d_utils

        region = context.region
        region_data = context.region_data
        coord = (event.mouse_region_x, event.mouse_region_y)
        try:
            # A click on (or right next to) a visible rig wire stays Blender's.
            if _rig_wire_near_cursor(context, coord, 8.0 * _ui_scale(context)):
                return {'PASS_THROUGH'}
            origin = view3d_utils.region_2d_to_origin_3d(region, region_data, coord)
            direction = view3d_utils.region_2d_to_vector_3d(region, region_data, coord)
            rig, _crossed_plane = fbp_pick_layer_through_alpha(
                context, origin, direction, by_image_with_rig=_by_image_with_rig(),
            )
        except (*FBP_DATA_ERRORS, ValueError):
            return {'PASS_THROUGH'}
        if rig is None:
            # No visible pixel under the cursor. Image planes are never
            # selectable themselves, so Blender's own click select already
            # sees through them to rig wires and regular objects behind.
            return {'PASS_THROUGH'}
        view_layer = context.view_layer
        if self.toggle:
            if rig.select_get() and view_layer.objects.active == rig:
                rig.select_set(False)
            else:
                rig.select_set(True)
                view_layer.objects.active = rig
        else:
            for obj in tuple(context.selected_objects):
                if obj != rig:
                    obj.select_set(False)
            rig.select_set(True)
            view_layer.objects.active = rig
        return {'FINISHED'}
