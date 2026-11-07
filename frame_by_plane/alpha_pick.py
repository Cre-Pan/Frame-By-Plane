"""Click selection that sees through the transparent pixels of image planes.

Frame By Plane image planes are not selectable themselves; a layer is picked
through its control rig. This operator runs before Blender's click select in
Object Mode: it walks the view ray through the scene, skips planes whose
pixel under the cursor is transparent and selects the layer of the first
visible pixel. Viewport handles (Crop, Gradient, Shape Mask...) are drawn on
top of everything, so a click on one selects that handle before anything
else. Layers that show their rig wire are skipped (picked from the
wire) unless the "Rig Layers: Click Image Too" preference is on. Anything else
(no plane hit, a click on a rig wire, a regular object in front, a locked
layer) is passed through to Blender's own selection untouched.
"""

from bpy.props import BoolProperty
from bpy.types import Operator
from mathutils import Vector, geometry

from .runtime import FBP_DATA_ERRORS
from .common import ui_scale as _ui_scale, view_ray as fbp_view_ray


_MAX_STEPS = 64


def _fbp_rig_of_plane(obj):
    """Return the control rig that owns ``obj`` when it is an FBP image plane."""
    parent = getattr(obj, "parent", None)
    while parent is not None:
        if bool(getattr(parent, "is_fbp_control", False)) and getattr(parent, "fbp_plane_target", None) == obj:
            return parent
        parent = getattr(parent, "parent", None)
    return None


def _uv_on_polygon(mesh, polygon_index, local_point):
    """UV at a point (mesh space) inside polygon ``polygon_index``, or ``None``."""
    uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.active
    if uv_layer is None or not (0 <= polygon_index < len(mesh.polygons)):
        return None
    polygon = mesh.polygons[polygon_index]
    loops = list(polygon.loop_indices)
    corners = [mesh.vertices[mesh.loops[loop].vertex_index].co for loop in loops]
    uvs = [uv_layer.data[loop].uv for loop in loops]
    best = None
    for tri in range(1, len(loops) - 1):
        a, b, c = corners[0], corners[tri], corners[tri + 1]
        mapped = geometry.barycentric_transform(
            local_point, a, b, c,
            uvs[0].to_3d(), uvs[tri].to_3d(), uvs[tri + 1].to_3d(),
        )
        # Project into the triangle plane; keep the triangle that contains it.
        closest = geometry.closest_point_on_tri(local_point, a, b, c)
        distance = (closest - local_point).length
        if best is None or distance < best[0]:
            best = (distance, float(mapped.x), float(mapped.y))
    return None if best is None else (best[1], best[2])


def _uv_at_hit(obj_eval, matrix, world_location, polygon_index):
    """UV of the evaluated plane surface at a world hit, or ``None``.

    Uses the face and matrix reported by the scene ray cast, so the result does
    not depend on the plane's scale, distance or viewing angle.
    """
    try:
        mesh = obj_eval.data
        if mesh is None:
            return None
        local = matrix.inverted_safe() @ world_location
        return _uv_on_polygon(mesh, int(polygon_index), local)
    except (*FBP_DATA_ERRORS, IndexError, ValueError):
        return None


def _select_by_image_allowed(rig, by_image_with_rig):
    """Layers that show their rig are picked from the wire unless allowed."""
    from .builder import fbp_rig_wire_visible

    return bool(by_image_with_rig) or not fbp_rig_wire_visible(rig)


def _rig_wire_near_cursor(context, coord, radius):
    """True when a visible rig wire passes within ``radius`` pixels of ``coord``.

    Runs on every click, over every visible rig, so the wire edges are
    projected and measured in bulk with NumPy.
    """
    import numpy as np
    from .builder import fbp_rig_wire_visible

    region = context.region
    region_data = context.region_data
    width = float(region.width)
    height = float(region.height)
    perspective = np.array(region_data.perspective_matrix, dtype=np.float64)
    cx, cy = float(coord[0]), float(coord[1])
    limit = float(radius) * float(radius)
    for obj in tuple(getattr(context, "visible_objects", ()) or ()):
        try:
            if not bool(getattr(obj, "is_fbp_control", False)) or not fbp_rig_wire_visible(obj):
                continue
            if bool(getattr(obj, "hide_select", False)):
                continue
            mesh = obj.data
            vertex_count = len(mesh.vertices)
            edge_count = len(mesh.edges)
            if not vertex_count or not edge_count:
                continue
            positions = np.empty(vertex_count * 3, dtype=np.float64)
            mesh.vertices.foreach_get("co", positions)
            edges = np.empty(edge_count * 2, dtype=np.int64)
            mesh.edges.foreach_get("vertices", edges)
            matrix = perspective @ np.array(obj.matrix_world, dtype=np.float64)
            clip = np.c_[positions.reshape(-1, 3), np.ones(vertex_count)] @ matrix.T
            w = clip[:, 3]
            ahead = w > 1e-6
            safe = np.where(ahead, w, 1.0)
            x = (clip[:, 0] / safe + 1.0) * 0.5 * width
            y = (clip[:, 1] / safe + 1.0) * 0.5 * height
            edges = edges.reshape(-1, 2)
            edges = edges[ahead[edges[:, 0]] & ahead[edges[:, 1]]]
            if not len(edges):
                continue
            ax, ay = x[edges[:, 0]], y[edges[:, 0]]
            dx, dy = x[edges[:, 1]] - ax, y[edges[:, 1]] - ay
            length = dx * dx + dy * dy
            with np.errstate(divide="ignore", invalid="ignore"):
                t = np.where(length > 1e-9, ((cx - ax) * dx + (cy - ay) * dy) / length, 0.0)
            t = np.clip(t, 0.0, 1.0)
            px = ax + dx * t - cx
            py = ay + dy * t - cy
            if bool(np.any(px * px + py * py <= limit)):
                return True
        except (*FBP_DATA_ERRORS, IndexError):
            continue
    return False


def _point_segment_distance_sq(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length <= 1e-12 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    ex, ey = ax + dx * t - px, ay + dy * t - py
    return ex * ex + ey * ey


def _screen_distance_to_triangle_sq(point, a, b, c):
    """0 inside the 2D triangle ``abc``, else the squared distance to its edges."""
    px, py = point
    d1 = (px - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (py - b[1])
    d2 = (px - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (py - c[1])
    d3 = (px - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (py - a[1])
    negative = d1 < 0.0 or d2 < 0.0 or d3 < 0.0
    positive = d1 > 0.0 or d2 > 0.0 or d3 > 0.0
    if not (negative and positive):
        return 0.0
    return min(
        _point_segment_distance_sq(px, py, a[0], a[1], b[0], b[1]),
        _point_segment_distance_sq(px, py, b[0], b[1], c[0], c[1]),
        _point_segment_distance_sq(px, py, c[0], c[1], a[0], a[1]),
    )


_LINE_PICK_PENALTY_SQ = 4.0


def _is_gradient_line(handle):
    try:
        from .effect_controls import KEY_MODE
        return str(handle.get(KEY_MODE, "") or "").upper() == "RANGE_CENTER"
    except (ImportError, *FBP_DATA_ERRORS):
        return False


def fbp_handle_under_cursor(context, coord, radius):
    """The viewport handle (Crop, Gradient, Shape Mask...) under ``coord``.

    Handles are drawn on top of everything, so they win over any plane or
    rig, wherever they sit in depth: what the user sees under the cursor is
    what the click picks. Returns the closest handle within ``radius`` pixels
    (inside its filled shape counts as 0), or ``None``.
    """
    from .handle_overlay import _visible_handles, handle_screen_scale

    region = context.region
    region_data = context.region_data
    try:
        if not bool(context.space_data.overlay.show_overlays):
            # Handles are an overlay: hidden with the overlays, never picked.
            return None
    except FBP_DATA_ERRORS:
        return None
    handles = [
        handle for handle in _visible_handles(context)
        if not bool(getattr(handle, "hide_select", False))
    ]
    if not handles:
        return None
    depsgraph = context.evaluated_depsgraph_get()
    try:
        ui_scale = float(context.preferences.system.ui_scale) or 1.0
    except (AttributeError, TypeError, ValueError):
        ui_scale = 1.0
    limit = float(radius) * float(radius)
    point = (float(coord[0]), float(coord[1]))
    best = None
    from .handle_overlay import handle_mesh

    import numpy as np

    width_half = region.width / 2.0
    height_half = region.height / 2.0
    perspective = np.array(region_data.perspective_matrix, dtype=np.float64)
    reach = float(radius) + 1.0

    def project(world):
        """``location_3d_to_region_2d`` for an (N, 3) array: (xy, valid)."""
        clip = world @ perspective[:, :3].T + perspective[:, 3]
        w = clip[:, 3]
        valid = w > 0.0
        safe = np.where(valid, w, 1.0)
        xy = np.empty((len(world), 2), dtype=np.float64)
        xy[:, 0] = width_half + width_half * (clip[:, 0] / safe)
        xy[:, 1] = height_half + height_half * (clip[:, 1] / safe)
        return xy, valid

    for handle in handles:
        try:
            matrix, topology = handle_mesh(handle, depsgraph)
        except (*FBP_DATA_ERRORS, IndexError):
            continue
        try:
            local = topology.get("vertices_array")
            if local is None:
                local = np.array([tuple(vertex) for vertex in topology["vertices"]], dtype=np.float64).reshape(-1, 3)
                topology["vertices_array"] = local
            if not len(local):
                continue
            world_matrix = np.array(matrix, dtype=np.float64)
            world = local @ world_matrix[:3, :3].T + world_matrix[:3, 3]
            if _is_gradient_line(handle):
                # A gradient's base line drags the whole gradient. It is a
                # loose edge along local X, drawn at its real size; the dots
                # on it win when both are in reach.
                line_xy, line_valid = project(world)
                for a, b in topology["loose_x"]:
                    if not (line_valid[a] and line_valid[b]):
                        continue
                    distance = _point_segment_distance_sq(
                        point[0], point[1], line_xy[a, 0], line_xy[a, 1], line_xy[b, 0], line_xy[b, 1],
                    ) + _LINE_PICK_PENALTY_SQ
                    if distance <= limit + _LINE_PICK_PENALTY_SQ and (best is None or distance < best[0]):
                        best = (distance, handle)
            triangles = topology["triangles"]
            if not triangles:
                continue
            # Picked where it is drawn: knobs keep one size on screen.
            fixed = handle_screen_scale(handle, region, region_data, ui_scale)
            if fixed is not None:
                anchor, factor = fixed
                anchor = np.array(tuple(anchor), dtype=np.float64)
                world = anchor + (world - anchor) * float(factor)
            screen, valid = project(world)
            # Only the filled faces are picked, so only their corners count;
            # a cursor away from all of them skips the triangle tests.
            used = topology.get("triangle_vertices")
            if used is None:
                used = sorted({index for _part, indices in triangles for index in indices})
            used = np.asarray(used, dtype=np.intp)
            corners_ok = used[valid[used]]
            if not len(corners_ok):
                continue
            box = screen[corners_ok]
            if (
                point[0] < box[:, 0].min() - reach or point[0] > box[:, 0].max() + reach
                or point[1] < box[:, 1].min() - reach or point[1] > box[:, 1].max() + reach
            ):
                continue
            screen, valid = screen.tolist(), valid.tolist()
            for _part, indices in triangles:
                if not all(valid[index] for index in indices):
                    continue
                corners = [screen[index] for index in indices]
                distance = _screen_distance_to_triangle_sq(point, *corners)
                if distance <= limit and (best is None or distance < best[0]):
                    best = (distance, handle)
                    if distance == 0.0:
                        break
        except (*FBP_DATA_ERRORS, IndexError, ValueError):
            pass
    return None if best is None else best[1]


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
    last_hit = None
    for _step in range(_MAX_STEPS):
        hit, location, _normal, index, obj, matrix = scene.ray_cast(depsgraph, origin, direction)
        if not hit or obj is None:
            return None, crossed_plane
        original = getattr(obj, "original", obj)
        key = (original.name_full if hasattr(original, "name_full") else id(original), int(index))
        nudge = max(1.0e-4, location.length * 1.0e-6)
        if key == last_hit:
            # Same face again (float precision far from the origin): step on.
            origin = location + direction * (nudge * 100.0)
            last_hit = None
            continue
        last_hit = key
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
            obj_eval = original.evaluated_get(depsgraph)
            uv = _uv_at_hit(obj_eval, matrix, location, index)
            visible = True
            if uv is not None:
                state = fbp_rig_alpha_visible_at_uv(rig, uv[0], uv[1], scene)
                visible = True if state is None else bool(state)
            if visible:
                return rig, True
        origin = location + direction * nudge
    return None, crossed_plane


def _by_image_with_rig():
    try:
        from .interface_preferences import fbp_get_addon_preferences
        preferences = fbp_get_addon_preferences()
        return bool(getattr(preferences, "rig_select_by_image", False)) if preferences else False
    except (ImportError, AttributeError, ReferenceError, RuntimeError):
        return False


def _layer_box_part_at(context, coord):
    try:
        from .layer_cage import layer_box_part_at
        return layer_box_part_at(context, coord)
    except (ImportError, *FBP_DATA_ERRORS):
        return None


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
        region = context.region
        region_data = context.region_data
        coord = (event.mouse_region_x, event.mouse_region_y)
        try:
            # Handles are drawn on top of everything, so they come first: a
            # click on a Crop or Gradient handle never picks the plane behind.
            handle = fbp_handle_under_cursor(context, coord, 4.0 * _ui_scale(context))
            if handle is not None:
                return self._select(context, handle)
            # A click on the transform box's knob, dots or edges stays on
            # the box (the knob shows the anchor); only the inside lets a
            # click through to the layers behind.
            box = _layer_box_part_at(context, coord)
            if box is not None and box[1] != "MOVE":
                if box[1] == "ROTATE":
                    from .layer_cage import toggle_anchor_mode
                    toggle_anchor_mode(box[0])
                    context.area.tag_redraw()
                # Nothing in the file changed: no empty Undo step. Cancelled
                # still ends the click here, so Blender does not deselect.
                return {'CANCELLED'}
            # A click on (or right next to) a visible rig wire stays Blender's.
            if _rig_wire_near_cursor(context, coord, 8.0 * _ui_scale(context)):
                return {'PASS_THROUGH'}
            origin, direction = fbp_view_ray(region, region_data, coord)
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
        return self._select(context, rig)

    def _select(self, context, rig):
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
