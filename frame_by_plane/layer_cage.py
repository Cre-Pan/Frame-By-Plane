"""Transform box around the selected layers, in the style of Blender's
Grease Pencil transform box.

Only selected layers show it, so a layer without a rig wire still shows how
much of the scene it covers, and unselected layers stay clean. It is one
Python gizmo per layer, laid on the image plane:

* drag inside the box to move the layer;
* drag an edge to stretch it, a corner to scale it, with the opposite side
  fixed. Alt scales symmetrically around the box centre, Shift keeps the
  proportions of a corner drag;
* drag the round knob above the box to rotate the layer around its anchor
  (Ctrl snaps to 15 degrees);
* click the knob to show the anchor (the rig origin), then drag it: it snaps
  to the centre, the corners and the middle of the edges, and the layer
  stays where it is.

A plain click inside the box goes on to Select Through Transparency, so
clicking a layer behind still works; a click on a dot, an edge or the knob
stays on the box. A layer that shows effect handles (Crop, Gradient, Shape
Mask...) shows those instead of the box, so they receive the drag.

As in Grease Pencil's box, the edge and corner dots appear only when the
cursor comes near; the knob on top and the anchor cross stay visible.
"""

from __future__ import annotations

import bpy
from mathutils import Matrix, Vector

from .runtime import FBP_DATA_ERRORS
from .viewport_handles import handle_selected_color


_MAX_CAGES = 32
_ACTIVE_COLOR = (1.0, 1.0, 1.0)
_SELECTED_COLOR = (0.72, 0.72, 0.72)


def cage_enabled(context=None):
    try:
        from .interface_preferences import fbp_get_addon_preferences
        preferences = fbp_get_addon_preferences()
        return bool(getattr(preferences, "show_layer_cage", True)) if preferences else True
    except (ImportError, *FBP_DATA_ERRORS):
        return True


def _cage_layers(context):
    """Selected, visible, selectable layers (rigs with an image plane)."""
    layers = []
    for obj in tuple(getattr(context, "selected_objects", ()) or ()):
        try:
            if not bool(getattr(obj, "is_fbp_control", False)):
                continue
            if getattr(obj, "fbp_plane_target", None) is None:
                continue
            if bool(getattr(obj, "hide_select", False)) or not obj.visible_get():
                continue
        except FBP_DATA_ERRORS:
            continue
        layers.append(obj)
        if len(layers) >= _MAX_CAGES:
            break
    return layers


def layer_cage_rect(rig, depsgraph=None):
    """``(center, size)`` of the layer's visible plane in rig space (XY).

    Uses the evaluated plane, so Crop, Extend and mesh effects are included.
    """
    plane = getattr(rig, "fbp_plane_target", None)
    if plane is None:
        return None
    try:
        source = plane.evaluated_get(depsgraph) if depsgraph is not None else plane
        relation = rig.matrix_world.inverted_safe() @ source.matrix_world
        corners = [relation @ Vector(corner) for corner in source.bound_box]
    except (*FBP_DATA_ERRORS, IndexError):
        return None
    xs = [corner.x for corner in corners]
    ys = [corner.y for corner in corners]
    size = Vector((max(xs) - min(xs), max(ys) - min(ys)))
    if size.x <= 1.0e-6 or size.y <= 1.0e-6:
        return None
    center = Vector(((max(xs) + min(xs)) * 0.5, (max(ys) + min(ys)) * 0.5, 0.0))
    return center, size


def _rigs_with_handles(context):
    """Pointers of the layers that currently show effect handles."""
    try:
        from .handle_overlay import _visible_handles
        from .viewport_handles import attached_plane
    except ImportError:
        return set()
    pointers = set()
    for handle in _visible_handles(context):
        try:
            plane = attached_plane(handle)
            if plane is not None:
                pointers.add(plane.as_pointer())
        except FBP_DATA_ERRORS:
            continue
    return pointers


def _shows_color_plane_gradient(context, rig):
    """True while a Gradient Color Plane shows its gradient line and dots,
    which sit on the box's side handles by default."""
    try:
        from .handle_overlay import color_plane_gradient_shown
        return color_plane_gradient_shown(context, rig)
    except ImportError:
        return False


def _shows_lattice_handles(rig):
    """True while the layer's Lattice shows Corner Pin or Grid point handles.

    Those draw their own Perspective quad or Grid lines on the layer's edges,
    so the transform box steps aside as it does for Crop.
    """
    try:
        from .lattice_bones import bones_object
        from .lattice_corner_pin import CORNER_ROLE_KEY
        from .lattice_pins import PIN_POINT_KEY
    except ImportError:
        return False
    try:
        armature = bones_object(rig)
        if armature is None or not armature.visible_get():
            return False
        return any(
            not bone.bone.hide and (bone.get(CORNER_ROLE_KEY) or bone.get(PIN_POINT_KEY) is not None)
            for bone in armature.pose.bones
        )
    except FBP_DATA_ERRORS:
        return False


def _rotation_copy(rig):
    mode = str(getattr(rig, "rotation_mode", "XYZ") or "XYZ")
    if mode == "QUATERNION":
        return rig.rotation_quaternion.copy()
    if mode == "AXIS_ANGLE":
        return tuple(rig.rotation_axis_angle)
    return rig.rotation_euler.copy()


def _restore_locked(rig, before):
    location, rotation, scale = before
    for axis in range(3):
        if rig.lock_location[axis]:
            rig.location[axis] = location[axis]
        if rig.lock_scale[axis]:
            rig.scale[axis] = scale[axis]
    if any(rig.lock_rotation):
        mode = str(getattr(rig, "rotation_mode", "XYZ") or "XYZ")
        if mode == "QUATERNION":
            rig.rotation_quaternion = rotation
        elif mode == "AXIS_ANGLE":
            rig.rotation_axis_angle = rotation
        else:
            for axis in range(3):
                if rig.lock_rotation[axis]:
                    rig.rotation_euler[axis] = rotation[axis]


def _auto_key(rig):
    try:
        scene = bpy.context.scene
        if not bool(scene.tool_settings.use_keyframe_insert_auto):
            return
        frame = scene.frame_current
        for path in ("location", "rotation_euler", "scale"):
            if path == "rotation_euler" and rig.rotation_mode in {"QUATERNION", "AXIS_ANGLE"}:
                path = "rotation_quaternion" if rig.rotation_mode == "QUATERNION" else "rotation_axis_angle"
            rig.keyframe_insert(path, frame=frame, group="Object Transforms")
    except FBP_DATA_ERRORS:
        return


# --- Cursor proximity -------------------------------------------------------
#
# Like Grease Pencil's transform box, secondary handles (edge squares, the
# rotation knob, the side handles of Crop) appear only when the cursor comes
# near. Drawing code registers screen-space zones; an invisible probe gizmo
# sees every mouse move in the viewport and asks for a redraw only when the
# cursor enters or leaves a zone.

PROXIMITY_MARGIN_PX = 48.0
_CURSOR = {"region": 0, "xy": None}
_ZONES = {}


def _region_key(region):
    try:
        return int(region.as_pointer())
    except FBP_DATA_ERRORS:
        return 0


def _zone_near(rect, xy, margin):
    if xy is None or rect is None:
        return False
    min_x, min_y, max_x, max_y = rect
    x, y = xy
    return (min_x - margin) <= x <= (max_x + margin) and (min_y - margin) <= y <= (max_y + margin)


def proximity_near(key, region, points, margin=PROXIMITY_MARGIN_PX):
    """True when the cursor is within ``margin`` px of the screen ``points``.

    Also records the zone, so the probe redraws the view when the cursor
    crosses its border.
    """
    points = [point for point in points if point is not None]
    region_key = _region_key(region)
    if not points or not region_key:
        return False
    rect = (
        min(point[0] for point in points), min(point[1] for point in points),
        max(point[0] for point in points), max(point[1] for point in points),
    )
    xy = _CURSOR["xy"] if _CURSOR["region"] == region_key else None
    near = _zone_near(rect, xy, margin)
    _ZONES[(region_key, key)] = (rect, margin, near)
    return near


def _cursor_moved(region, xy):
    region_key = _region_key(region)
    _CURSOR["region"] = region_key
    _CURSOR["xy"] = (float(xy[0]), float(xy[1]))
    changed = False
    for (zone_region, _key), (rect, margin, near) in tuple(_ZONES.items()):
        if zone_region == region_key and _zone_near(rect, _CURSOR["xy"], margin) != near:
            changed = True
            break
    if changed:
        try:
            region.tag_redraw()
        except FBP_DATA_ERRORS:
            pass


_HOVER = {"region": 0, "name": ""}


def hovered_handle_name(region):
    """Name of the viewport handle under the cursor in ``region``, or ""."""
    return _HOVER["name"] if _HOVER["region"] == _region_key(region) else ""


def _update_hover(context, xy):
    """Track the handle under the cursor; redraw only when it changes."""
    name = ""
    try:
        from .alpha_pick import fbp_handle_under_cursor
        scale = float(context.preferences.system.ui_scale) or 1.0
        handle = fbp_handle_under_cursor(context, xy, 4.0 * scale)
        name = str(handle.name) if handle is not None else ""
        if not name:
            from .handle_overlay import lattice_handle_under_cursor
            name = lattice_handle_under_cursor(context, xy, 4.0 * scale)
    except (ImportError, *FBP_DATA_ERRORS):
        name = ""
    set_hovered_handle(context, name)


def set_hovered_handle(context, name):
    """Light up the handle called ``name`` (or none); redraw when it changes."""
    region_key = _region_key(context.region)
    if (_HOVER["region"], _HOVER["name"]) != (region_key, name):
        _HOVER["region"], _HOVER["name"] = region_key, name
        try:
            context.region.tag_redraw()
        except FBP_DATA_ERRORS:
            pass


class FBP_GT_cursor_probe(bpy.types.Gizmo):
    """Invisible gizmo that only watches the cursor; it never takes a click."""

    bl_idname = "FBP_GT_cursor_probe"

    def draw(self, context):
        del context

    def test_select(self, context, location):
        try:
            _cursor_moved(context.region, location)
        except FBP_DATA_ERRORS:
            pass
        # Handles light up under the cursor, as Blender's gizmos do.
        _update_hover(context, location)
        return -1


def _proximity_wanted(context):
    if _cage_layers(context):
        return True
    try:
        from .handle_overlay import _visible_lattice_handles
        if next(_visible_lattice_handles(context), None) is not None:
            return True
    except ImportError:
        pass
    try:
        from .handle_overlay import _visible_handles
        return bool(_visible_handles(context))
    except ImportError:
        return False


class FBP_GGT_cursor_probe(bpy.types.GizmoGroup):
    bl_idname = "FBP_GGT_cursor_probe"
    bl_label = "Frame By Plane Cursor Probe"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        try:
            # Pose Mode too: Lattice handles are edited there.
            if context.mode not in {"OBJECT", "POSE"} or not context.space_data.overlay.show_overlays:
                return False
        except FBP_DATA_ERRORS:
            return False
        if _proximity_wanted(context):
            return True
        _ZONES.clear()
        _HOVER["name"] = ""
        return False

    def setup(self, context):
        del context
        self.gizmos.new(FBP_GT_cursor_probe.bl_idname)


# --- Transform box ----------------------------------------------------------
#
# One Python gizmo per selected layer draws the box and takes its drags. Every
# point is recomputed from the rig's current matrix on each redraw, so the
# dots, the knob and the anchor follow the layer while it moves.
#
# Parts: MOVE (inside the box), C0..C3 (corners), E0..E3 (edges), ROTATE (the
# knob above the top edge) and ANCHOR (the rig origin, which the layer turns
# and scales around). A click on the knob shows the anchor, which can then be
# dragged; it snaps to the centre, the corners and the middle of the edges.

_ROTATE_OFFSET_PX = 18.0
_ROTATE_RADIUS_PX = 4.0
_MARK_RADIUS_PX = 3.0
_CROSS_HALF_PX = 5.0
_ANCHOR_RING_PX = 7.0
_PICK_DOT_PX = 8.0
_PICK_EDGE_PX = 5.0
_SNAP_PX = 14.0
_TARGET_RADIUS_PX = 2.2

# Corners and edges, counter-clockwise from bottom left, as (x, y) signs.
_CORNER_SIGNS = ((-1, -1), (1, -1), (1, 1), (-1, 1))
_EDGE_SIGNS = ((0, -1), (1, 0), (0, 1), (-1, 0))
PARTS = ("MOVE", "C0", "C1", "C2", "C3", "E0", "E1", "E2", "E3", "ROTATE", "ANCHOR")

# Layers showing their anchor (clicked on the knob), by rig name.
_ANCHOR_MODE = set()
# Last box of each layer: rig-space rect and whether effect handles hide it.
_BOX_STATE = {}


def anchor_mode(rig_name):
    return rig_name in _ANCHOR_MODE


def toggle_anchor_mode(rig_name):
    if rig_name in _ANCHOR_MODE:
        _ANCHOR_MODE.discard(rig_name)
    else:
        _ANCHOR_MODE.add(rig_name)


def _pixels_per_unit(region, region_data, origin, direction):
    """Screen pixels covered by one world unit along ``direction`` at ``origin``."""
    from bpy_extras.view3d_utils import location_3d_to_region_2d

    start = location_3d_to_region_2d(region, region_data, origin)
    end = location_3d_to_region_2d(region, region_data, origin + direction)
    if start is None or end is None:
        return None
    length = (end - start).length
    return length if length > 1.0e-6 else None


def _ui_scale(context):
    try:
        return float(context.preferences.system.ui_scale) or 1.0
    except FBP_DATA_ERRORS:
        return 1.0


_FRAME_CACHE = {}


def _box_frame(rig, center, size, region, region_data):
    """World and screen points of a layer's box, or None off screen.

    The box is drawn on every redraw and hit-tested on every mouse move with
    the same layer and view, so the last results are kept per layer, view
    and region size. The returned dict is shared: callers only read it.
    """
    world = rig.matrix_world
    key = (
        rig.as_pointer(), tuple(map(tuple, world)), tuple(center), tuple(size),
        tuple(map(tuple, region_data.perspective_matrix)), region.width, region.height,
    )
    try:
        return _FRAME_CACHE[key]
    except KeyError:
        pass
    frame = _build_box_frame(world, center, size, region, region_data)
    if len(_FRAME_CACHE) >= 64:
        _FRAME_CACHE.clear()
    _FRAME_CACHE[key] = frame
    return frame


def _build_box_frame(world, center, size, region, region_data):
    from bpy_extras.view3d_utils import location_3d_to_region_2d

    world = world.copy()
    axis_x = (world.to_3x3() @ Vector((1.0, 0.0, 0.0)))
    axis_y = (world.to_3x3() @ Vector((0.0, 1.0, 0.0)))
    if axis_x.length <= 1.0e-9 or axis_y.length <= 1.0e-9:
        return None
    axis_x.normalize()
    axis_y.normalize()
    hx, hy = size.x * 0.5, size.y * 0.5

    def point(dx, dy):
        return world @ Vector((center.x + dx * hx, center.y + dy * hy, center.z))

    corners = [point(*signs) for signs in _CORNER_SIGNS]
    edges = [point(*signs) for signs in _EDGE_SIGNS]
    top = edges[2]
    per_unit = _pixels_per_unit(region, region_data, top, axis_y)
    if per_unit is None:
        return None
    knob = top + axis_y * (_ROTATE_OFFSET_PX / per_unit)
    anchor = world.translation.copy()
    # The anchor sits on the layer: drop the rig origin on the box plane.
    normal = axis_x.cross(axis_y)
    if normal.length > 1.0e-9:
        normal.normalize()
        anchor -= normal * (anchor - corners[0]).dot(normal)
    targets = [point(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]

    def screen(value):
        return location_3d_to_region_2d(region, region_data, value)

    return {
        "axis_x": axis_x, "axis_y": axis_y, "normal": normal,
        "corners": corners, "edges": edges, "top": top, "knob": knob,
        "anchor": anchor, "targets": targets, "center": point(0, 0),
        "s_corners": [screen(value) for value in corners],
        "s_edges": [screen(value) for value in edges],
        "s_knob": screen(knob), "s_top": screen(top), "s_anchor": screen(anchor),
        "s_targets": [screen(value) for value in targets],
    }


def _point_in_polygon(point, polygon):
    inside = False
    count = len(polygon)
    for index in range(count):
        a, b = polygon[index], polygon[(index + 1) % count]
        if (a.y > point.y) != (b.y > point.y):
            x = a.x + (point.y - a.y) * (b.x - a.x) / (b.y - a.y)
            if point.x < x:
                inside = not inside
    return inside


def _segment_distance(point, a, b):
    axis = b - a
    length_sq = axis.length_squared
    if length_sq <= 1.0e-9:
        return (point - a).length
    t = max(0.0, min(1.0, (point - a).dot(axis) / length_sq))
    return (point - (a + axis * t)).length


def _hit_part(frame, location, scale, rig_name):
    """The box part under ``location`` (region pixels), or None."""
    mouse = Vector(location[:2])
    dot = _PICK_DOT_PX * scale

    def near(screen_point, radius=dot):
        return screen_point is not None and (mouse - screen_point).length <= radius

    if anchor_mode(rig_name) and near(frame["s_anchor"], (_ANCHOR_RING_PX + 3.0) * scale):
        return "ANCHOR"
    if near(frame["s_knob"]):
        return "ROTATE"
    for index, screen_point in enumerate(frame["s_corners"]):
        if near(screen_point):
            return f"C{index}"
    for index, screen_point in enumerate(frame["s_edges"]):
        if near(screen_point):
            return f"E{index}"
    corners = frame["s_corners"]
    if any(corner is None for corner in corners):
        return None
    for index in range(4):
        a, b = corners[index], corners[(index + 1) % 4]
        # Edge index: E0 bottom (C0-C1), E1 right (C1-C2), E2 top, E3 left.
        if _segment_distance(mouse, a, b) <= _PICK_EDGE_PX * scale:
            return f"E{index}"
    if _point_in_polygon(mouse, corners):
        return "MOVE"
    return None


def layer_box_part_at(context, location):
    """``(rig_name, part)`` of the transform box under ``location``, or None."""
    region, region_data = getattr(context, "region", None), getattr(context, "region_data", None)
    if region is None or region_data is None or not cage_enabled(context):
        return None
    scale = _ui_scale(context)
    try:
        layers = _cage_layers(context)
    except FBP_DATA_ERRORS:
        return None
    # The active layer's box is on top.
    active = getattr(context, "active_object", None)
    layers.sort(key=lambda rig: rig != active)
    for rig in layers:
        state = _BOX_STATE.get(rig.name)
        if state is None or state["hidden"]:
            continue
        try:
            frame = _box_frame(rig, state["center"], state["size"], region, region_data)
        except FBP_DATA_ERRORS:
            continue
        if frame is None:
            continue
        part = _hit_part(frame, location, scale, rig.name)
        if part is not None:
            return rig.name, part
    return None


def _plane_hit(region, region_data, coord, point, normal):
    from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d

    origin = region_2d_to_origin_3d(region, region_data, coord)
    direction = region_2d_to_vector_3d(region, region_data, coord)
    denominator = direction.dot(normal)
    if abs(denominator) <= 1.0e-9:
        return None
    return origin + direction * ((point - origin).dot(normal) / denominator)


def set_layer_anchor(rig, world_point):
    """Move the layer's origin to ``world_point`` without moving anything.

    The plane and every other child keep their place, Child Of constraints
    that follow the rig are compensated, and location keys shift with the
    origin so an animated layer keeps its path.
    """
    world = rig.matrix_world.copy()
    local = world.inverted_safe() @ Vector(world_point)
    local.z = 0.0
    if local.length <= 1.0e-7:
        return False
    children = {child: child.matrix_world.copy() for child in rig.children}
    before = rig.location.copy()
    rig.matrix_world = world @ Matrix.Translation(local)
    delta = rig.location - before
    for child, matrix in children.items():
        child.matrix_world = matrix
    shift = Matrix.Translation(-local)
    for obj in bpy.data.objects:
        if obj == rig or obj.parent == rig:
            continue
        for constraint in getattr(obj, "constraints", ()):
            if constraint.type == "CHILD_OF" and getattr(constraint, "target", None) == rig:
                constraint.inverse_matrix = shift @ constraint.inverse_matrix
    action = getattr(getattr(rig, "animation_data", None), "action", None)
    fcurves = _action_fcurves(rig, action)
    for fcurve in fcurves:
        if fcurve.data_path != "location" or not 0 <= fcurve.array_index < 3:
            continue
        offset = float(delta[fcurve.array_index])
        for key in fcurve.keyframe_points:
            key.co.y += offset
            key.handle_left.y += offset
            key.handle_right.y += offset
        fcurve.update()
    return True


def _action_fcurves(rig, action):
    if action is None:
        return ()
    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None:
        return tuple(fcurves)
    # Layered actions (Blender 4.4+): the rig's slot channelbag.
    try:
        slot = rig.animation_data.action_slot
        for layer in action.layers:
            for strip in layer.strips:
                bag = strip.channelbag(slot)
                if bag is not None:
                    return tuple(bag.fcurves)
    except (AttributeError, TypeError) + FBP_DATA_ERRORS:
        pass
    return ()


_SHADERS = {}


def _shaders():
    """Per-vertex colour shaders: each draw sends one batch for its fills
    and one per line width, in drawing order, so blending is unchanged."""
    import gpu

    if not _SHADERS:
        _SHADERS["fill"] = gpu.shader.from_builtin("FLAT_COLOR")
        _SHADERS["line"] = gpu.shader.from_builtin("POLYLINE_FLAT_COLOR")
    return _SHADERS["fill"], _SHADERS["line"]


_UNIT_CIRCLES = {}


def _unit_circle(segments):
    table = _UNIT_CIRCLES.get(segments)
    if table is None:
        import math

        table = tuple(
            (math.cos(math.tau * index / segments), math.sin(math.tau * index / segments))
            for index in range(segments)
        )
        _UNIT_CIRCLES[segments] = table
    return table


def _circle(center, axis_x, axis_y, radius, segments=24):
    cx, cy, cz = center
    xx, xy, xz = axis_x
    yx, yy, yz = axis_y
    return [
        (cx + (xx * c + yx * s) * radius, cy + (xy * c + yy * s) * radius, cz + (xz * c + yz * s) * radius)
        for c, s in _unit_circle(segments)
    ]


def _disc(center, axis_x, axis_y, radius, segments=24):
    ring = _circle(center, axis_x, axis_y, radius, segments)
    middle = tuple(center)
    triangles = []
    for index in range(segments):
        triangles.extend((middle, ring[index], ring[(index + 1) % segments]))
    return triangles


def _ring(center, axis_x, axis_y, outer, inner, segments=24):
    a = _circle(center, axis_x, axis_y, outer, segments)
    b = _circle(center, axis_x, axis_y, inner, segments)
    triangles = []
    for index in range(segments):
        nxt = (index + 1) % segments
        triangles.extend((a[index], a[nxt], b[nxt], a[index], b[nxt], b[index]))
    return triangles


def _cross(center, axis_x, axis_y, half, width):
    triangles = []
    for direction in ((axis_x + axis_y).normalized(), (axis_x - axis_y).normalized()):
        side = direction.cross(axis_x.cross(axis_y)).normalized() * width
        a, b = center - direction * half, center + direction * half
        triangles.extend(tuple(point) for point in (a - side, b - side, b + side, a - side, b + side, a + side))
    return triangles


def _colored(parts):
    """Join ``(points, rgb, alpha)`` parts into one position and colour list."""
    positions, colors = [], []
    for points, rgb, alpha in parts:
        positions.extend(points)
        colors.extend(((*rgb, alpha),) * len(points))
    return positions, colors


_RNA_GET = bpy.types.bpy_struct.__getattribute__


class FBP_GT_layer_box(bpy.types.Gizmo):
    """A selected layer's transform box: move, scale, rotate, anchor."""

    bl_idname = "FBP_GT_layer_box"
    __slots__ = (
        "fbp_rig_name", "fbp_center", "fbp_size", "fbp_active", "fbp_part",
        "fbp_initial", "fbp_press", "fbp_start", "fbp_anchor_preview", "fbp_snap",
        "fbp_hover",
    )

    def setup(self):
        self.fbp_rig_name = ""
        self.fbp_center = (0.0, 0.0, 0.0)
        self.fbp_size = (1.0, 1.0)
        self.fbp_active = True
        self.fbp_part = ""
        self.fbp_initial = None
        self.fbp_press = None
        self.fbp_start = None
        self.fbp_anchor_preview = None
        self.fbp_snap = -1
        self.fbp_hover = ""
        self.use_draw_scale = False
        # Keep drawing while dragged, so the box follows the layer.
        self.use_draw_modal = True

    def _rig(self):
        return bpy.data.objects.get(self.fbp_rig_name or "")

    def _frame(self, context, rig=None):
        rig = rig or self._rig()
        if rig is None:
            return None
        try:
            return _box_frame(
                rig, Vector(self.fbp_center), Vector(self.fbp_size), context.region, context.region_data,
            )
        except FBP_DATA_ERRORS:
            return None

    # --- Drawing ------------------------------------------------------------

    def draw(self, context):
        import gpu
        from gpu_extras.batch import batch_for_shader

        # Python gizmos route each attribute through a slow lookup among
        # their operator-style properties: read everything once, directly.
        get = _RNA_GET
        rig_name = get(self, "fbp_rig_name")
        rig = bpy.data.objects.get(rig_name or "")
        if rig is None:
            return
        region, region_data = context.region, context.region_data
        try:
            frame = _box_frame(rig, Vector(get(self, "fbp_center")), Vector(get(self, "fbp_size")), region, region_data)
        except FBP_DATA_ERRORS:
            frame = None
        if frame is None:
            return
        scale = _ui_scale(context)
        accent = handle_selected_color(context)[:3]
        is_active = get(self, "fbp_active")
        white = _ACTIVE_COLOR if is_active else _SELECTED_COLOR
        modal = bool(get(self, "is_modal"))
        hovered = get(self, "fbp_hover") if get(self, "is_highlight") else ""
        active_part = get(self, "fbp_part") if modal else hovered
        anchor_preview = get(self, "fbp_anchor_preview")
        snap_index = get(self, "fbp_snap")
        showing = anchor_mode(rig_name)
        axis_x, axis_y = frame["axis_x"], frame["axis_y"]

        def unit(point):
            per = _pixels_per_unit(region, region_data, point, axis_y)
            return 1.0 / per if per else None

        fills = []      # (triangles, colour, alpha)
        lines = []      # (points as segment pairs, colour, alpha, width)
        corners = frame["corners"]
        outline = []
        for index in range(4):
            outline.extend((corners[index], corners[(index + 1) % 4]))
        lines.append((outline, white, 0.9 if is_active else 0.6, 1.0))
        if active_part.startswith("E"):
            index = int(active_part[1])
            lines.append(([corners[index], corners[(index + 1) % 4]], accent, 1.0, 2.0))

        def dot(point, color, radius, alpha=1.0):
            u = unit(point)
            if u is None:
                return
            fills.append((_disc(point, axis_x, axis_y, (radius + 1.2) * u), (0.0, 0.0, 0.0), 0.5))
            fills.append((_disc(point, axis_x, axis_y, radius * u), color, alpha))

        # Corner and edge dots: near the cursor, or while one is dragged.
        screen_points = [*frame["s_corners"], *frame["s_edges"], frame["s_knob"]]
        near = proximity_near(("cage", rig_name), region, screen_points)
        if (near and not modal) or active_part[:1] in {"C", "E"}:
            for index, point in enumerate(corners):
                part = f"C{index}"
                if not modal or part == active_part:
                    dot(point, accent if part == active_part else white, _MARK_RADIUS_PX)
            for index, point in enumerate(frame["edges"]):
                part = f"E{index}"
                if not modal or part == active_part:
                    dot(point, accent if part == active_part else white, _MARK_RADIUS_PX)

        # The knob on its stem above the top edge.
        if not modal or active_part == "ROTATE":
            lines.append(([frame["top"], frame["knob"]], white, 0.8, 1.0))
            knob_color = accent if active_part == "ROTATE" or showing else white
            dot(frame["knob"], knob_color, _ROTATE_RADIUS_PX)

        # The anchor: a small cross, a ring around it once shown, and the
        # snap targets with guides while it is dragged.
        anchor = frame["anchor"]
        if active_part == "ANCHOR" and anchor_preview is not None:
            anchor = Vector(anchor_preview)
        u = unit(anchor)
        if u is not None:
            cross_color = accent if (showing or active_part in {"ROTATE", "ANCHOR"}) else white
            if showing:
                ring_color = accent if active_part == "ANCHOR" or hovered == "ANCHOR" else white
                fills.append((_ring(anchor, axis_x, axis_y, (_ANCHOR_RING_PX + 1.2) * u, (_ANCHOR_RING_PX - 2.2) * u), (0.0, 0.0, 0.0), 0.45))
                fills.append((_ring(anchor, axis_x, axis_y, _ANCHOR_RING_PX * u, (_ANCHOR_RING_PX - 1.2) * u), ring_color, 1.0))
            fills.append((_cross(anchor, axis_x, axis_y, (_CROSS_HALF_PX + 0.8) * u, 1.4 * u), (0.0, 0.0, 0.0), 0.45))
            fills.append((_cross(anchor, axis_x, axis_y, _CROSS_HALF_PX * u, 0.6 * u), cross_color, 1.0))
        if showing and (active_part == "ANCHOR" or hovered == "ANCHOR"):
            targets = frame["targets"]
            if modal and active_part == "ANCHOR":
                # Guides: the box's middle lines and diagonals.
                guides = [
                    targets[3], targets[5], targets[1], targets[7],
                    targets[0], targets[8], targets[2], targets[6],
                ]
                lines.append((guides, accent, 0.45, 1.0))
            for index, point in enumerate(targets):
                snapped = modal and active_part == "ANCHOR" and index == snap_index
                dot(point, accent if snapped else white, _TARGET_RADIUS_PX * (1.6 if snapped else 1.0), 0.9)

        fill_shader, line_shader = _shaders()
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        try:
            line_shader.bind()
            line_shader.uniform_float("viewportSize", (region.width, region.height))
            # One batch per run of lines with the same width, in order.
            runs = []
            for segments, color, alpha, width in lines:
                if not segments:
                    continue
                if runs and runs[-1][0] == width:
                    runs[-1][1].append((segments, color, alpha))
                else:
                    runs.append((width, [(segments, color, alpha)]))
            for width, parts in runs:
                positions, colors = _colored([([tuple(point) for point in segments], color, alpha) for segments, color, alpha in parts])
                line_shader.uniform_float("lineWidth", width * scale)
                batch_for_shader(line_shader, "LINES", {"pos": positions, "color": colors}).draw(line_shader)
            if fills:
                positions, colors = _colored(fills)
                fill_shader.bind()
                batch_for_shader(fill_shader, "TRIS", {"pos": positions, "color": colors}).draw(fill_shader)
        finally:
            gpu.state.blend_set("NONE")

    def test_select(self, context, location):
        get = _RNA_GET
        rig_name = get(self, "fbp_rig_name")
        rig = bpy.data.objects.get(rig_name or "")
        if rig is None:
            return -1
        try:
            frame = _box_frame(
                rig, Vector(get(self, "fbp_center")), Vector(get(self, "fbp_size")),
                context.region, context.region_data,
            )
        except FBP_DATA_ERRORS:
            frame = None
        if frame is None:
            return -1
        part = _hit_part(frame, location, _ui_scale(context), rig_name)
        bpy.types.bpy_struct.__setattr__(self, "fbp_hover", part or "")
        return PARTS.index(part) if part is not None else -1

    # --- Interaction --------------------------------------------------------

    def invoke(self, context, event):
        rig = self._rig()
        frame = self._frame(context, rig)
        part = self.fbp_hover
        if rig is None or frame is None or not part:
            return {"CANCELLED"}
        self.fbp_part = part
        self.fbp_initial = rig.matrix_world.copy()
        self.fbp_press = (event.mouse_region_x, event.mouse_region_y)
        self.fbp_anchor_preview = None
        self.fbp_snap = -1
        if part == "ROTATE":
            self.fbp_start = self._screen_angle(context, event, frame)
            if self.fbp_start is None:
                return {"CANCELLED"}
        else:
            hit = _plane_hit(context.region, context.region_data, self.fbp_press, frame["corners"][0], frame["normal"])
            if hit is None:
                return {"CANCELLED"}
            self.fbp_start = tuple(hit)
        return {"RUNNING_MODAL"}

    @staticmethod
    def _screen_angle(context, event, frame):
        import math

        centre = frame["s_anchor"]
        if centre is None:
            return None
        return math.atan2(event.mouse_region_y - centre.y, event.mouse_region_x - centre.x)

    def modal(self, context, event, tweak):
        rig = self._rig()
        if rig is None or self.fbp_initial is None:
            return {"RUNNING_MODAL"}
        part = self.fbp_part
        try:
            if part == "ROTATE":
                self._rotate(context, event, tweak, rig)
            elif part == "ANCHOR":
                self._drag_anchor(context, event, rig)
            else:
                hit = self._hit(context, event)
                if hit is None:
                    return {"RUNNING_MODAL"}
                if part == "MOVE":
                    self._move(context, rig, hit)
                else:
                    self._scale(context, event, rig, hit)
        except FBP_DATA_ERRORS:
            return {"RUNNING_MODAL"}
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _hit(self, context, event):
        initial = self.fbp_initial
        normal = (initial.to_3x3() @ Vector((0.0, 0.0, 1.0)))
        if normal.length <= 1.0e-9:
            return None
        return _plane_hit(
            context.region, context.region_data, (event.mouse_region_x, event.mouse_region_y),
            Vector(self.fbp_start), normal.normalized(),
        )

    def _apply(self, rig, matrix):
        before = (rig.location.copy(), _rotation_copy(rig), rig.scale.copy())
        rig.matrix_world = matrix
        _restore_locked(rig, before)

    def _move(self, context, rig, hit):
        delta = hit - Vector(self.fbp_start)
        self._apply(rig, Matrix.Translation(delta) @ self.fbp_initial)
        context.area.header_text_set(f"Move Layer: {delta.length:.3f}")

    def _scale(self, context, event, rig, hit):
        index = int(self.fbp_part[1])
        signs = _CORNER_SIGNS[index] if self.fbp_part[0] == "C" else _EDGE_SIGNS[index]
        centre, size = Vector(self.fbp_center), Vector(self.fbp_size)
        half = Vector((size.x * 0.5, size.y * 0.5, 0.0))
        local = self.fbp_initial.inverted_safe() @ hit
        handle = Vector((centre.x + signs[0] * half.x, centre.y + signs[1] * half.y, 0.0))
        # Alt: symmetric, around the box centre. Otherwise the opposite side
        # (or corner) stays where it is.
        if event.alt:
            fixed = Vector((centre.x, centre.y, 0.0))
        else:
            fixed = Vector((centre.x - signs[0] * half.x, centre.y - signs[1] * half.y, 0.0))
        factors = [1.0, 1.0]
        for axis in (0, 1):
            if signs[axis] == 0:
                continue
            span = handle[axis] - fixed[axis]
            if abs(span) > 1.0e-9:
                factors[axis] = (local[axis] - fixed[axis]) / span
        if event.shift and self.fbp_part[0] == "C":
            # Shift keeps the proportions: follow the cursor along the diagonal.
            direction = handle - fixed
            length_sq = direction.x * direction.x + direction.y * direction.y
            if length_sq > 1.0e-12:
                along = ((local.x - fixed.x) * direction.x + (local.y - fixed.y) * direction.y) / length_sq
                factors = [along, along]
        factors = [max(0.01, factor) for factor in factors]
        stretch = (
            Matrix.Translation(fixed)
            @ Matrix.Diagonal((factors[0], factors[1], 1.0, 1.0))
            @ Matrix.Translation(-fixed)
        )
        self._apply(rig, self.fbp_initial @ stretch)
        context.area.header_text_set(
            f"Scale Layer: {factors[0] * 100.0:.1f}% × {factors[1] * 100.0:.1f}%"
            + ("   (Alt: symmetric)" if event.alt else "   Alt: symmetric")
            + ("" if self.fbp_part[0] == "E" else ("   (Shift: proportional)" if event.shift else "   Shift: proportional"))
        )

    def _rotate(self, context, event, tweak, rig):
        import math

        frame = self._frame(context, rig)
        if frame is None:
            return
        # The anchor does not move while rotating, so its screen point holds.
        angle = self._screen_angle(context, event, frame)
        if angle is None:
            return
        delta = angle - self.fbp_start
        delta = math.atan2(math.sin(delta), math.cos(delta))
        if "SNAP" in tweak or event.ctrl:
            step = math.radians(15.0)
            delta = round(delta / step) * step
        initial = self.fbp_initial
        normal = (initial.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
        view = context.region_data.view_matrix.inverted().to_3x3() @ Vector((0.0, 0.0, 1.0))
        # Counter-clockwise on screen, whichever side of the plane faces us.
        if normal.dot(view) < 0.0:
            delta = -delta
        pivot = frame["anchor"]
        turn = Matrix.Translation(pivot) @ Matrix.Rotation(delta, 4, normal) @ Matrix.Translation(-pivot)
        self._apply(rig, turn @ initial)
        context.area.header_text_set(f"Rotate Layer: {math.degrees(delta):.1f}°   Ctrl: 15° steps")

    def _drag_anchor(self, context, event, rig):
        frame = self._frame(context, rig)
        if frame is None:
            return
        hit = _plane_hit(
            context.region, context.region_data, (event.mouse_region_x, event.mouse_region_y),
            frame["corners"][0], frame["normal"],
        )
        if hit is None:
            return
        # Magnet: the centre, the corners and the middle of the edges pull
        # the anchor in when the cursor comes close. Ctrl drags it freely.
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.fbp_snap = -1
        if not event.ctrl:
            best = _SNAP_PX * _ui_scale(context)
            for index, screen_point in enumerate(frame["s_targets"]):
                if screen_point is None:
                    continue
                distance = (mouse - screen_point).length
                if distance <= best:
                    best, self.fbp_snap = distance, index
        point = frame["targets"][self.fbp_snap] if self.fbp_snap >= 0 else hit
        self.fbp_anchor_preview = tuple(point)
        context.area.header_text_set("Move Anchor: snaps to the centre, corners and edges   Ctrl: free")

    def exit(self, context, cancel):
        rig = self._rig()
        try:
            context.area.header_text_set(None)
        except FBP_DATA_ERRORS:
            pass
        part, initial = self.fbp_part, self.fbp_initial
        self.fbp_initial = None
        if rig is not None and initial is not None:
            if cancel:
                if part != "ANCHOR":
                    rig.matrix_world = initial
            elif part == "ANCHOR":
                preview = self.fbp_anchor_preview
                if preview is not None:
                    try:
                        changed = set_layer_anchor(rig, Vector(preview))
                    except FBP_DATA_ERRORS:
                        changed = False
                    if changed:
                        _undo_push("Move Layer Anchor")
            elif rig.matrix_world != initial:
                _auto_key(rig)
                _undo_push({"MOVE": "Move Layer", "ROTATE": "Rotate Layer"}.get(part, "Scale Layer"))
        self.fbp_part = ""
        self.fbp_anchor_preview = None
        self.fbp_snap = -1
        context.area.tag_redraw()


def _undo_push(message):
    try:
        bpy.ops.ed.undo_push(message=message)
    except RuntimeError:
        pass


class FBP_GGT_layer_cage(bpy.types.GizmoGroup):
    bl_idname = "FBP_GGT_layer_cage"
    bl_label = "Frame By Plane Layer Cage"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        try:
            if context.mode != "OBJECT":
                return False
            space = context.space_data
            if not space.overlay.show_overlays or not space.show_gizmo:
                return False
        except FBP_DATA_ERRORS:
            return False
        if not cage_enabled(context):
            return False
        if _cage_layers(context):
            return True
        _BOX_STATE.clear()
        return False

    @classmethod
    def setup_keymap(cls, keyconfig):
        # Drag only: a plain click goes on to the selection operators.
        return keyconfig.keymaps.new(
            name="Generic Gizmo Maybe Drag", space_type="EMPTY", region_type="WINDOW",
        )

    def setup(self, context):
        self.boxes = {}
        self.draw_prepare(context)

    def draw_prepare(self, context):
        boxes = getattr(self, "boxes", None)
        if boxes is None:
            boxes = self.boxes = {}
        layers = _cage_layers(context)
        try:
            depsgraph = context.evaluated_depsgraph_get()
        except FBP_DATA_ERRORS:
            depsgraph = None
        names = {rig.name for rig in layers}
        for name, gizmo in tuple(boxes.items()):
            if name not in names and not gizmo.is_modal:
                del boxes[name]
                _BOX_STATE.pop(name, None)
                try:
                    self.gizmos.remove(gizmo)
                except FBP_DATA_ERRORS:
                    pass
        # A layer that is no longer selected stops showing its anchor.
        _ANCHOR_MODE.intersection_update(names)
        active = getattr(context, "active_object", None)
        with_handles = _rigs_with_handles(context) if layers else set()
        for rig in layers:
            gizmo = boxes.get(rig.name)
            if gizmo is None:
                gizmo = boxes[rig.name] = self.gizmos.new(FBP_GT_layer_box.bl_idname)
                gizmo.fbp_rig_name = rig.name
            if gizmo.is_modal:
                continue
            rect = layer_cage_rect(rig, depsgraph)
            if rect is None:
                gizmo.hide = True
                _BOX_STATE.pop(rig.name, None)
                continue
            center, size = rect
            try:
                plane = rig.fbp_plane_target
                hidden = (
                    (plane is not None and plane.as_pointer() in with_handles)
                    or _shows_lattice_handles(rig)
                    or _shows_color_plane_gradient(context, rig)
                )
            except FBP_DATA_ERRORS:
                hidden = False
            # Effect handles (Crop, Gradient, Lattice Corner Pin and Grid...)
            # take over: they sit on the same edges and draw their own frame.
            gizmo.hide = hidden
            gizmo.fbp_center = tuple(center)
            gizmo.fbp_size = (size.x, size.y)
            # Thin white lines as in Grease Pencil; other selected layers
            # are a dimmer grey so the active one stands out.
            gizmo.fbp_active = rig == active
            gizmo.matrix_basis = rig.matrix_world.normalized()
            _BOX_STATE[rig.name] = {"center": center.copy(), "size": size.copy(), "hidden": hidden}


_CLASSES = (FBP_GT_cursor_probe, FBP_GGT_cursor_probe, FBP_GT_layer_box, FBP_GGT_layer_cage)


def register():
    if bpy.app.background:
        return
    for cls in _CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError):
            pass
