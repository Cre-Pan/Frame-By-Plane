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
* click the knob to show the anchor, then drag it: it snaps to the centre,
  the corners and the middle of the edges. The anchor is stored on the layer
  and only the box uses it: the rig origin does not move.

A plain click inside the box goes on to Select Through Transparency, so
clicking a layer behind still works; a click on a dot, an edge or the knob
stays on the box. A layer that shows effect handles (Crop, Gradient, Shape
Mask...) shows those instead of the box, so they receive the drag.

As in Grease Pencil's box, the edge and corner dots appear only when the
cursor comes near; the knob on top and the anchor cross stay visible.

Dots, the knob and the anchor face the view and keep one size on screen,
whatever the angle. A layer seen edge-on (Top or Side view of a layer that
faces the camera) draws as a line: only its outline and the two end dots
that stretch it stay, the line moves the layer in the view's plane (so in
Top view it also changes the depth), and rotation steps aside.
"""

from __future__ import annotations

import collections
import math
import bpy
from mathutils import Matrix, Vector

from .runtime import fbp_guarded
from .runtime import FBP_DATA_ERRORS
from .viewport_handles import handle_selected_color
from .common import (
    edge_on as _edge_on,
    view_axes as _view_axes,
    view_plane_point as _view_plane_point,
    world_per_pixel as _world_per_pixel,
    view_plane_hit as _plane_hit,
    ui_scale as _ui_scale,
    undo_push as _undo_push,
)


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


def _whole_groups(context):
    try:
        from .plane_groups import whole_group_selected_rigs
        return whole_group_selected_rigs(context)
    except (ImportError, *FBP_DATA_ERRORS):
        return set()


def _cage_layers(context):
    """Selected, visible, selectable layers (rigs with an image plane).

    Only Digital layers show the box: a Legacy layer keeps its coloured wire
    alone, selected or not. Layers selected as a whole plane group show the
    group's box instead.
    """
    from .rig_style import rig_style

    layers = []
    grouped = None
    for obj in tuple(getattr(context, "selected_objects", ()) or ()):
        try:
            if not bool(getattr(obj, "is_fbp_control", False)):
                continue
            if rig_style(obj) == "LEGACY":
                continue
            if grouped is None:
                grouped = _whole_groups(context)
            if obj.name in grouped:
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
    """``(center, size)`` of the layer's image plane in rig space (XY).

    The box hugs the plane as Crop and Extend leave it: a cropped layer gets
    a smaller box, an extended one a larger box. Effects that grow or move the
    evaluated mesh (Frame Stack slices, mesh effects) do not change it,
    whatever the layer's scale or its sign. Falls back to the evaluated plane
    bounds when the layer has no reference size.
    """
    plane = getattr(rig, "fbp_plane_target", None)
    if plane is None:
        return None
    try:
        relation = rig.matrix_world.inverted_safe() @ plane.matrix_world
    except FBP_DATA_ERRORS:
        return None
    corners = None
    try:
        from .builder import fbp_plane_reference_bounds
        # Index 2: the cropped bounds grown by Extend, as the plane mesh is.
        min_x, max_x, min_y, max_y = fbp_plane_reference_bounds(rig)[2]
        if max_x - min_x > 1.0e-9 and max_y - min_y > 1.0e-9:
            corners = [
                relation @ Vector((x, y, 0.0))
                for x in (min_x, max_x) for y in (min_y, max_y)
            ]
    except (ImportError, TypeError, ValueError, IndexError) + FBP_DATA_ERRORS:
        corners = None
    if corners is None:
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


_ALPHA_OUTLINES = collections.OrderedDict()
_ALPHA_OUTLINE_LIMIT = 512
_ALPHA_LAST_OUTLINE = {}


def _alpha_box_segments(rig, center):
    """Rig-local segment points of a Digital Alpha Outline box, or ``()``.

    Built from the same outline as the Legacy wire and kept until the
    drawing, the outline settings or the Expand change.
    """
    try:
        from . import builder
        from .rig_style import expand_margin, shrink_factor
        margin, shrink = expand_margin(rig), shrink_factor(rig)
        key = (
            builder.fbp_rig_alpha_frame_source(rig),
            str(getattr(rig, "fbp_rig_shape_alpha_style", "")),
            int(getattr(rig, "fbp_rig_shape_alpha_detail", 64) or 64),
            round(margin, 6), round(shrink, 6), tuple(round(value, 6) for value in center),
        )
        pointer = rig.as_pointer()
    except (ImportError, *FBP_DATA_ERRORS, TypeError, ValueError):
        return ()
    entry_key = (pointer, key)
    cached = _ALPHA_OUTLINES.get(entry_key)
    if cached is not None:
        _ALPHA_OUTLINES.move_to_end(entry_key)
        _ALPHA_LAST_OUTLINE[pointer] = cached
        return cached
    previous = _ALPHA_LAST_OUTLINE.get(pointer)
    if previous is not None:
        # During playback the outline waits, as the Legacy wire does, and
        # catches up on the first redraw after it stops.
        try:
            from .scene_sync import fbp_animation_playback_active
            if fbp_animation_playback_active():
                return previous
        except (ImportError, *FBP_DATA_ERRORS):
            pass
    segments = ()
    try:
        geometry = builder._fbp_alpha_rig_geometry(rig, margin)
    except (*FBP_DATA_ERRORS, TypeError, ValueError):
        geometry = None
    if geometry is not None:
        verts, edges = geometry
        cx, cy = center.x, center.y
        points = [
            (cx + (x - cx) * shrink, cy + (y - cy) * shrink, z)
            for x, y, z in verts
        ]
        segments = tuple(points[index] for edge in edges for index in edge)
    # One entry per layer and drawing, least recently drawn first out.
    # Clearing the whole cache at 64 entries, and keeping only the current
    # drawing of each layer, made every click in a bigger project and every
    # scrubbed frame of an Alpha Follow layer rebuild the outline (marching
    # squares and smoothing, 20-30 ms each).
    _ALPHA_OUTLINES[entry_key] = segments
    _ALPHA_OUTLINES.move_to_end(entry_key)
    while len(_ALPHA_OUTLINES) > _ALPHA_OUTLINE_LIMIT:
        _ALPHA_OUTLINES.popitem(last=False)
    if len(_ALPHA_LAST_OUTLINE) > _ALPHA_OUTLINE_LIMIT:
        _ALPHA_LAST_OUTLINE.clear()
    _ALPHA_LAST_OUTLINE[pointer] = segments
    return segments


def box_shape(rig, center, size):
    """The box a layer shows in its rig shape: ``(center, size, outline, alpha)``.

    ``outline`` is the closed rig-local XY curve of a Circle, Triangle or
    Polygon box (empty for a rectangle); ``alpha`` the segment points of an
    Alpha Outline. Expand grows or shrinks the box and Perfect Shape keeps it
    regular on screen whatever the layer's scale. A Custom rig keeps the
    plain box on the plane.
    """
    try:
        from .rig_style import is_outline_shape, outline_box, rig_outline, rig_shape
        shape = rig_shape(rig)
        if shape == "CUSTOM":
            return center, size, (), ()
        half = (size.x * 0.5, size.y * 0.5)
        outline = rig_outline(rig, (center.x, center.y), half)
    except (ImportError, *FBP_DATA_ERRORS, TypeError, ValueError):
        return center, size, (), ()
    (cx, cy), (hx, hy) = outline_box(outline)
    box_center = Vector((cx, cy, center.z))
    box_size = Vector((max(1.0e-6, hx * 2.0), max(1.0e-6, hy * 2.0)))
    if is_outline_shape(shape):
        return box_center, box_size, tuple(outline), ()
    alpha = _alpha_box_segments(rig, center) if shape == "ALPHA" else ()
    if alpha:
        # The handles sit on the box around the visible pixels, not on the
        # whole plane: a drawing in a corner of a large canvas gets a small
        # box around the drawing.
        xs = [point[0] for point in alpha]
        ys = [point[1] for point in alpha]
        if max(xs) - min(xs) > 1.0e-6 and max(ys) - min(ys) > 1.0e-6:
            box_center = Vector(((max(xs) + min(xs)) * 0.5, (max(ys) + min(ys)) * 0.5, center.z))
            box_size = Vector((max(xs) - min(xs), max(ys) - min(ys)))
    return box_center, box_size, (), alpha


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
        radius = 4.0 * _ui_scale(context)
        handle = fbp_handle_under_cursor(context, xy, radius)
        name = str(handle.name) if handle is not None else ""
        if not name:
            from .handle_overlay import lattice_handle_under_cursor
            name = lattice_handle_under_cursor(context, xy, radius)
        if not name and context.mode == "OBJECT":
            # Layer names in Top and Side views light up too: a click selects.
            from .handle_overlay import PLANE_LABEL_HOVER_PREFIX, plane_label_under_cursor
            label = plane_label_under_cursor(context, xy)
            name = PLANE_LABEL_HOVER_PREFIX + label if label else ""
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

    @fbp_guarded("viewport.layer_box")
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
        from .handle_overlay import _axis_view
        if _axis_view(context) and any(
            bool(getattr(obj, "is_fbp_control", False)) for obj in tuple(context.visible_objects or ())
        ):
            return True
    except (ImportError, *FBP_DATA_ERRORS):
        pass
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
# knob above the top edge) and ANCHOR (the point the knob turns the layer
# around: the rig origin until it is moved). A click on the knob shows the
# anchor, which can then be dragged; it snaps to the centre, the corners and
# the middle of the edges.

_ROTATE_OFFSET_PX = 18.0
_ROTATE_RADIUS_PX = 5.0
_ROTATE_DEADZONE_PX = 12.0
_MARK_RADIUS_PX = 3.8
_CROSS_HALF_PX = 5.0
_ANCHOR_RING_PX = 7.0
_PICK_DOT_PX = 8.0
_PICK_EDGE_PX = 5.0
_SNAP_PX = 14.0
_TARGET_RADIUS_PX = 2.2

# Corners and edges, counter-clockwise from bottom left, as (x, y) signs.
_CORNER_SIGNS = ((-1, -1), (1, -1), (1, 1), (-1, 1))
_EDGE_SIGNS = ((0, -1), (1, 0), (0, 1), (-1, 0))
# ORIENT: the square below the bottom edge turns the box (the rig) while
# the layer itself stays put, so later scaling follows the new direction.
PARTS = ("MOVE", "C0", "C1", "C2", "C3", "E0", "E1", "E2", "E3", "ROTATE", "ANCHOR", "ORIENT")
_ORIENT_HALF_PX = 4.5
# Side handle bars: share of the side, longest length and thickness (px).
_EDGE_BAR_FRACTION = 0.4
_EDGE_BAR_MAX_PX = 90.0
_EDGE_BAR_WIDTH_PX = 3.0

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


_FRAME_CACHE = {}


def _box_frame(rig, center, size, region, region_data, outline=(), alpha=()):
    """World and screen points of a layer's box, or None off screen.

    The box is drawn on every redraw and hit-tested on every mouse move with
    the same layer and view, so the last results are kept per layer, view
    and region size. The returned dict is shared: callers only read it.
    """
    world = rig.matrix_world
    anchor_local = layer_anchor_local(rig)
    key = (
        rig.as_pointer(), tuple(map(tuple, world)), tuple(center), tuple(size),
        None if anchor_local is None else tuple(anchor_local),
        tuple(map(tuple, region_data.perspective_matrix)), region.width, region.height,
        outline, len(alpha), alpha[:1],
    )
    try:
        return _FRAME_CACHE[key]
    except KeyError:
        pass
    frame = _build_box_frame(world, center, size, region, region_data, anchor_local, outline, alpha)
    if len(_FRAME_CACHE) >= 64:
        _FRAME_CACHE.clear()
    _FRAME_CACHE[key] = frame
    return frame


def local_handles(center, size, outline=()):
    """Rig-local corner and side handle points of a box, as ``Vector`` lists.

    A rectangle box has them on its corners and the middle of its sides; a
    shaped box (circle, triangle, polygon) on its outline, along the
    diagonals and the axes of its bounding box.
    """
    hx, hy = size.x * 0.5, size.y * 0.5
    if outline:
        from .rig_style import handle_points
        corners, edges = handle_points(outline, (center.x, center.y), (hx, hy))
        return (
            [Vector((x, y, center.z)) for x, y in corners],
            [Vector((x, y, center.z)) for x, y in edges],
        )
    return (
        [Vector((center.x + dx * hx, center.y + dy * hy, center.z)) for dx, dy in _CORNER_SIGNS],
        [Vector((center.x + dx * hx, center.y + dy * hy, center.z)) for dx, dy in _EDGE_SIGNS],
    )


def _build_box_frame(world, center, size, region, region_data, anchor_local, outline=(), alpha=()):
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

    def screen(value):
        return location_3d_to_region_2d(region, region_data, value)

    local_corners, local_edges = local_handles(center, size, outline)
    corners = [world @ value for value in local_corners]
    edges = [world @ value for value in local_edges]
    middle = point(0, 0)
    # The drawn outline: the shape's curve, the alpha outline segments, or
    # the four sides of the rectangle.
    if outline:
        shape_points = [world @ Vector((x, y, center.z)) for x, y in outline]
        segments = []
        for index in range(len(shape_points)):
            segments.extend((shape_points[index], shape_points[(index + 1) % len(shape_points)]))
    else:
        shape_points = None
        box_corners = [point(*signs) for signs in _CORNER_SIGNS]
        segments = []
        for index in range(4):
            segments.extend((box_corners[index], box_corners[(index + 1) % 4]))
    if alpha:
        segments = [world @ Vector(value) for value in alpha]
    normal = axis_x.cross(axis_y)
    if normal.length <= 1.0e-9:
        return None
    normal.normalize()
    view_right, view_up, _toward = _view_axes(region_data)
    edge_on = _edge_on(region_data, middle, normal)
    top = edges[2]
    bottom = edges[0]

    def beside(start, direction, pixels):
        """``start`` moved ``pixels`` on screen the way ``direction`` points."""
        a, b = screen(start), screen(start + direction)
        unit = _world_per_pixel(region, region_data, start)
        if a is None or b is None or unit is None:
            return None
        along = b - a
        if along.length <= 1.0e-6:
            return None
        along.normalize()
        return start + (view_right * along.x + view_up * along.y) * (pixels * unit)

    # The knob and the square sit a fixed distance off the box on screen,
    # whatever the angle; an edge-on layer has neither.
    knob = None if edge_on else beside(top, axis_y, _ROTATE_OFFSET_PX)
    orient = None if edge_on else beside(bottom, -axis_y, _ROTATE_OFFSET_PX)
    if not edge_on and (knob is None or orient is None):
        return None
    anchor = (world @ anchor_local) if anchor_local is not None else world.translation.copy()
    # The anchor sits on the layer: drop it on the box plane.
    anchor -= normal * (anchor - corners[0]).dot(normal)
    targets = [point(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    s_corners = [screen(value) for value in corners]
    s_edges = [screen(value) for value in edges]
    # Edge-on, the box is a line: its two ends are the sides that still
    # stretch the layer (left/right in Top view, top/bottom in Side view).
    ends = ()
    if edge_on:
        valid = [value for value in s_corners if value is not None]
        if len(valid) < 4:
            return None
        if shape_points is not None:
            # Seen edge-on, a shaped box is the line through its bounds.
            s_corners = [screen(point(*signs)) for signs in _CORNER_SIGNS]
            if any(value is None for value in s_corners):
                return None
        span_x = (s_edges[1] - s_edges[3]).length if s_edges[1] is not None and s_edges[3] is not None else 0.0
        span_y = (s_edges[2] - s_edges[0]).length if s_edges[2] is not None and s_edges[0] is not None else 0.0
        if max(span_x, span_y) <= 2.0:
            return None
        ends = (1, 3) if span_x >= span_y else (0, 2)

    return {
        "axis_x": axis_x, "axis_y": axis_y, "normal": normal,
        "view_x": view_right, "view_y": view_up, "edge_on": edge_on, "ends": ends,
        "corners": corners, "edges": edges, "top": top, "knob": knob,
        "bottom": bottom, "orient": orient, "s_orient": screen(orient) if orient is not None else None,
        "anchor": anchor, "targets": targets, "center": middle,
        "s_corners": s_corners, "s_edges": s_edges,
        "s_knob": screen(knob) if knob is not None else None,
        "s_top": screen(top), "s_anchor": screen(anchor),
        "s_targets": [screen(value) for value in targets],
        "segments": segments, "shaped": shape_points is not None,
        "s_outline": [screen(value) for value in shape_points] if shape_points is not None else None,
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

    if frame.get("edge_on"):
        # A line: its end dots stretch, the line itself moves.
        for index in frame["ends"]:
            if near(frame["s_edges"][index]):
                return f"E{index}"
        corners = frame["s_corners"]
        for index in range(4):
            a, b = corners[index], corners[(index + 1) % 4]
            if _segment_distance(mouse, a, b) <= _PICK_EDGE_PX * scale:
                return "MOVE"
        if _point_in_polygon(mouse, corners):
            return "MOVE"
        return None
    if anchor_mode(rig_name) and near(frame["s_anchor"], (_ANCHOR_RING_PX + 3.0) * scale):
        return "ANCHOR"
    if near(frame["s_knob"]):
        return "ROTATE"
    if near(frame.get("s_orient")):
        return "ORIENT"
    for index, screen_point in enumerate(frame["s_corners"]):
        if near(screen_point):
            return f"C{index}"
    for index, screen_point in enumerate(frame["s_edges"]):
        if near(screen_point):
            return f"E{index}"
    shape = frame.get("s_outline")
    if shape is not None:
        # A shaped box: the outline and the inside move the layer; its
        # dots (above) scale it.
        if any(value is None for value in shape):
            return None
        count = len(shape)
        for index in range(count):
            if _segment_distance(mouse, shape[index], shape[(index + 1) % count]) <= _PICK_EDGE_PX * scale:
                return "MOVE"
        return "MOVE" if _point_in_polygon(mouse, shape) else None
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
    if not _gizmos_shown(context):
        # The box is not drawn: it must not take the click either.
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
            frame = _box_frame(
                rig, state["center"], state["size"], region, region_data,
                state.get("outline", ()), state.get("alpha", ()),
            )
        except FBP_DATA_ERRORS:
            continue
        if frame is None:
            continue
        part = _hit_part(frame, location, scale, rig.name)
        if part is not None:
            return rig.name, part
    return None


def _gizmos_shown(context):
    try:
        space = context.space_data
        return bool(space.overlay.show_overlays and space.show_gizmo)
    except FBP_DATA_ERRORS:
        return False


ANCHOR_KEY = "fbp_box_anchor"


def layer_anchor_local(rig):
    """The box anchor in rig space, or None for the rig origin."""
    try:
        value = rig.get(ANCHOR_KEY)
        if value is None or len(value) < 2:
            return None
        return Vector((float(value[0]), float(value[1]), 0.0))
    except (TypeError, ValueError) + FBP_DATA_ERRORS:
        return None


def set_layer_anchor(rig, world_point):
    """Store the anchor the box rotates around, in rig space.

    Only the box uses it: the rig origin, the hierarchy and the effects stay
    as they are, so Blender draws no dashed parent line.
    """
    local = rig.matrix_world.inverted_safe() @ Vector(world_point)
    if local.xy.length <= 1.0e-7:
        if ANCHOR_KEY in rig:
            del rig[ANCHOR_KEY]
            return True
        return False
    current = layer_anchor_local(rig)
    if current is not None and (current.xy - local.xy).length <= 1.0e-7:
        return False
    rig[ANCHOR_KEY] = (float(local.x), float(local.y))
    return True


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


def _square(center, axis_x, axis_y, half):
    a = center + (-axis_x - axis_y) * half
    b = center + (axis_x - axis_y) * half
    c = center + (axis_x + axis_y) * half
    d = center + (-axis_x + axis_y) * half
    return [tuple(point) for point in (a, b, c, a, c, d)]


def _cross(center, axis_x, axis_y, half, width):
    triangles = []
    for direction in ((axis_x + axis_y).normalized(), (axis_x - axis_y).normalized()):
        side = direction.cross(axis_x.cross(axis_y)).normalized() * width
        a, b = center - direction * half, center + direction * half
        triangles.extend(tuple(point) for point in (a - side, b - side, b + side, a - side, b + side, a + side))
    return triangles


def _all_finite(points):
    """True when every coordinate of ``points`` is finite (one sum per point)."""
    try:
        return math.isfinite(sum(map(math.fsum, points)))
    except (OverflowError, TypeError, ValueError):
        return False


def _colored(parts):
    """Join ``(points, rgb, alpha)`` parts into one position and colour list."""
    positions, colors = [], []
    for points, rgb, alpha in parts:
        # A point at infinity or NaN (a degenerate rig scale, a point behind
        # the view) is never sent to the GPU: some drivers fault on it.
        if not _all_finite(points):
            continue
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
        "fbp_hover", "fbp_children", "fbp_turn", "fbp_free", "fbp_outline", "fbp_alpha",
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
        self.fbp_children = None
        self.fbp_turn = None
        self.fbp_free = False
        self.fbp_outline = ()
        self.fbp_alpha = ()
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
                self.fbp_outline, self.fbp_alpha,
            )
        except FBP_DATA_ERRORS:
            return None

    # --- Drawing ------------------------------------------------------------

    @fbp_guarded("viewport.layer_box")
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
            frame = _box_frame(
                rig, Vector(get(self, "fbp_center")), Vector(get(self, "fbp_size")), region, region_data,
                get(self, "fbp_outline"), get(self, "fbp_alpha"),
            )
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
        # Dots face the view and keep one size on screen at any angle.
        axis_x, axis_y = frame["view_x"], frame["view_y"]
        edge_on = frame.get("edge_on", False)

        def unit(point):
            return _world_per_pixel(region, region_data, point)

        fills = []      # (triangles, colour, alpha)
        lines = []      # (points as segment pairs, colour, alpha, width)
        corners = frame["corners"]
        shaped = frame.get("shaped", False)
        lines.append((frame["segments"], white, 0.9 if is_active else 0.6, 1.0))

        def dot(point, color, radius, alpha=1.0):
            u = unit(point)
            if u is None:
                return
            fills.append((_disc(point, axis_x, axis_y, (radius + 1.2) * u), (0.0, 0.0, 0.0), 0.5))
            fills.append((_disc(point, axis_x, axis_y, radius * u), color, alpha))

        # Corner and edge dots: near the cursor, or while one is dragged.
        screen_points = [*frame["s_corners"], *frame["s_edges"], frame["s_knob"]]
        near = proximity_near(("cage", rig_name), region, screen_points)
        if edge_on:
            # Seen edge-on the box is a line: the dots at its ends stretch
            # the layer; corners, knob and anchor would all pile up.
            if (near and not modal) or active_part[:1] == "E":
                for index in frame["ends"]:
                    part = f"E{index}"
                    if modal and part != active_part:
                        continue
                    dot(frame["edges"][index], accent if part == active_part else white, _MARK_RADIUS_PX + (0.8 if part == active_part else 0.0))
        elif (near and not modal) or active_part[:1] in {"C", "E"}:
            for index, point in enumerate(corners):
                part = f"C{index}"
                if not modal or part == active_part:
                    dot(point, accent if part == active_part else white, _MARK_RADIUS_PX)
            # Side handles: a short thick bar in the middle of each side, as
            # in the Grease Pencil deform box. Only the bar thickens on hover.
            for index, point in enumerate(frame["edges"]):
                part = f"E{index}"
                if modal and part != active_part:
                    continue
                if shaped:
                    # A curve has no straight side for a bar: a smaller dot.
                    dot(point, accent if part == active_part else white, _MARK_RADIUS_PX * 0.8 + (0.8 if part == active_part else 0.0))
                    continue
                along = corners[(index + 1) % 4] - corners[index]
                length = along.length
                if length <= 1.0e-9:
                    continue
                per = _pixels_per_unit(region, region_data, point, along / length)
                if per is None:
                    continue
                half = min(length * _EDGE_BAR_FRACTION, _EDGE_BAR_MAX_PX / per) * 0.5
                along = along / length
                bar = [point - along * half, point + along * half]
                width = _EDGE_BAR_WIDTH_PX + (1.5 if part == active_part else 0.0)
                lines.append((bar, (0.0, 0.0, 0.0), 0.5, width + 2.0))
                lines.append((bar, accent if part == active_part else white, 1.0, width))

        # The knob on its stem above the top edge.
        if frame["knob"] is not None and (not modal or active_part == "ROTATE"):
            lines.append(([frame["top"], frame["knob"]], white, 0.8, 1.0))
            knob_color = accent if active_part == "ROTATE" or showing else white
            dot(frame["knob"], knob_color, _ROTATE_RADIUS_PX)

        # The orientation square on its stem below the bottom edge.
        if frame["orient"] is not None and (not modal or active_part == "ORIENT"):
            lines.append(([frame["bottom"], frame["orient"]], white, 0.8, 1.0))
            u = unit(frame["orient"])
            if u is not None:
                square_color = accent if active_part == "ORIENT" else white
                fills.append((_square(frame["orient"], axis_x, axis_y, (_ORIENT_HALF_PX + 1.2) * u), (0.0, 0.0, 0.0), 0.5))
                fills.append((_square(frame["orient"], axis_x, axis_y, _ORIENT_HALF_PX * u), square_color, 1.0))

        # The anchor: a small cross, a ring around it once shown, and the
        # snap targets with guides while it is dragged.
        anchor = frame["anchor"]
        if active_part == "ANCHOR" and anchor_preview is not None:
            anchor = Vector(anchor_preview)
        u = None if edge_on else unit(anchor)
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
                context.region, context.region_data, get(self, "fbp_outline"), get(self, "fbp_alpha"),
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
        if part == "MOVE" and event.alt and _alt_orbits(context):
            # With Emulate 3 Button Mouse, Alt + drag orbits the view.
            return {"CANCELLED"}
        self.fbp_part = part
        self.fbp_initial = rig.matrix_world.copy()
        self.fbp_press = (event.mouse_region_x, event.mouse_region_y)
        self.fbp_anchor_preview = None
        self.fbp_snap = -1
        if part in {"ROTATE", "ORIENT"}:
            if part == "ORIENT":
                if transform_animated(rig):
                    _notify(context, ORIENT_ANIMATED_MESSAGE)
                    return {"CANCELLED"}
                self.fbp_children = _children_inverses(rig)
            self.fbp_start = self._screen_angle(context, event, frame)
            if self.fbp_start is None:
                return {"CANCELLED"}
            # Pivot (screen and world), last cursor angle and the turn so far.
            self.fbp_turn = [frame["s_anchor"].copy(), frame["anchor"].copy(), self.fbp_start, 0.0]
        else:
            # Edge-on, the line moves in the view's plane: in Top view that
            # slides the layer sideways and in depth.
            self.fbp_free = bool(frame.get("edge_on")) and part == "MOVE"
            if self.fbp_free:
                hit = _view_plane_point(context.region, context.region_data, self.fbp_press, frame["center"])
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
            if part in {"ROTATE", "ORIENT"}:
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
        if self.fbp_free:
            return _view_plane_point(
                context.region, context.region_data, (event.mouse_region_x, event.mouse_region_y),
                Vector(self.fbp_start),
            )
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
        local = self.fbp_initial.inverted_safe() @ hit
        # The dragged dot and the one opposite it, on the box or its shape.
        local_corners, local_edges = local_handles(centre, size, self.fbp_outline)
        points = local_corners if self.fbp_part[0] == "C" else local_edges
        handle = points[index].copy()
        handle.z = 0.0
        # Alt: symmetric, around the box centre. Otherwise the opposite side
        # (or corner) stays where it is.
        if event.alt:
            fixed = Vector((centre.x, centre.y, 0.0))
        else:
            fixed = points[(index + 2) % 4].copy()
            fixed.z = 0.0
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

        turn_state = self.fbp_turn
        if not turn_state:
            return
        pivot_screen, pivot, last, total = turn_state
        offset = Vector((event.mouse_region_x - pivot_screen.x, event.mouse_region_y - pivot_screen.y))
        # Near the pivot the angle swings wildly with each pixel: hold it.
        if offset.length < _ROTATE_DEADZONE_PX * _ui_scale(context):
            return
        angle = math.atan2(offset.y, offset.x)
        # Add up the change since the last move, so the turn never jumps by
        # a full circle and can go past 180 degrees.
        step_angle = angle - last
        total += math.atan2(math.sin(step_angle), math.cos(step_angle))
        turn_state[2], turn_state[3] = angle, total
        delta = total
        if "SNAP" in tweak or event.ctrl:
            step = math.radians(15.0)
            delta = round(delta / step) * step
        initial = self.fbp_initial
        normal = (initial.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
        view = context.region_data.view_matrix.inverted().to_3x3() @ Vector((0.0, 0.0, 1.0))
        # Counter-clockwise on screen, whichever side of the plane faces us.
        if normal.dot(view) < 0.0:
            delta = -delta
        turn = Matrix.Translation(pivot) @ Matrix.Rotation(delta, 4, normal) @ Matrix.Translation(-pivot)
        self._apply(rig, turn @ initial)
        if self.fbp_part == "ORIENT":
            _keep_children(rig, initial, self.fbp_children)
            context.area.header_text_set(f"Rotate Box: {math.degrees(delta):.1f}° (the layer stays)   Ctrl: 15° steps")
            return
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
                if part == "ORIENT":
                    _restore_children(self.fbp_children)
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
                _undo_push({"MOVE": "Move Layer", "ROTATE": "Rotate Layer", "ORIENT": "Rotate Layer Box"}.get(part, "Scale Layer"))
        self.fbp_part = ""
        self.fbp_children = None
        self.fbp_turn = None
        self.fbp_free = False
        self.fbp_anchor_preview = None
        self.fbp_snap = -1
        context.area.tag_redraw()


def _alt_orbits(context):
    try:
        return bool(context.preferences.inputs.use_mouse_emulate_3_button)
    except FBP_DATA_ERRORS:
        return False


def _basis_world(rig):
    """The rig's world matrix from its own channels, valid right after an edit."""
    parent = getattr(rig, "parent", None)
    if parent is None:
        return rig.matrix_basis.copy()
    return parent.matrix_world @ rig.matrix_parent_inverse @ rig.matrix_basis


def _children_inverses(rig):
    return [(child.name, child.matrix_parent_inverse.copy()) for child in rig.children]


def _keep_children(rig, initial, inverses):
    """Keep the rig's children where they were while the rig turns: the plane,
    its lattice and controls stay in place and only the box changes direction."""
    if not inverses:
        return
    keep = _basis_world(rig).inverted_safe() @ initial
    for name, inverse in inverses:
        child = bpy.data.objects.get(name)
        if child is not None:
            child.matrix_parent_inverse = keep @ inverse


def _restore_children(inverses):
    for name, inverse in inverses or ():
        child = bpy.data.objects.get(name)
        if child is not None:
            child.matrix_parent_inverse = inverse


ORIENT_ANIMATED_MESSAGE = (
    "The box of an animated layer cannot turn on its own: "
    "its keyframes would turn the drawing at the other frames"
)
_TRANSFORM_PATHS = {
    "location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
    "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale",
}


def transform_animated(rig):
    """True when keyframes, drivers or NLA strips set the rig's transform.

    Turning the box alone moves the rig and compensates in its children's
    parent inverse, which no keyframe holds: on another frame the keys put
    the rig back and the drawing would turn by the same angle. Only keys on
    the current frame, which Auto Keying rewrites, are safe.
    """
    animation = getattr(rig, "animation_data", None)
    if animation is None:
        return False
    try:
        for driver in animation.drivers:
            if driver.data_path in _TRANSFORM_PATHS:
                return True
        for track in animation.nla_tracks:
            if not track.mute and len(track.strips):
                return True
        from .runtime import fbp_action_fcurves

        curves = fbp_action_fcurves(rig)
        if not curves:
            return False
        scene = bpy.context.scene
        frame = float(scene.frame_current)
        auto_key = bool(scene.tool_settings.use_keyframe_insert_auto)
        for curve in curves:
            if curve.data_path not in _TRANSFORM_PATHS or curve.mute:
                continue
            if not auto_key or curve.data_path.startswith("delta_"):
                return True
            if any(abs(point.co.x - frame) > 1.0e-4 for point in curve.keyframe_points):
                return True
    except (ImportError, *FBP_DATA_ERRORS):
        return False
    return False


def _notify(context, message):
    try:
        def draw(menu, _context):
            menu.layout.label(text=message, icon="INFO")
        context.window_manager.popup_menu(draw, title="Rotate Layer Box", icon="ORIENTATION_LOCAL")
    except FBP_DATA_ERRORS:
        pass


def box_orientation_offset(rig):
    """Angle (radians) between the box and the layer's plane, around the rig Z."""
    import math

    plane = getattr(rig, "fbp_plane_target", None)
    if plane is None:
        return 0.0
    relation = (plane.matrix_parent_inverse @ plane.matrix_basis).to_3x3()
    axis = relation @ Vector((1.0, 0.0, 0.0))
    if axis.xy.length <= 1.0e-9:
        return 0.0
    return math.atan2(axis.y, axis.x)


def reset_box_orientation(rig):
    """Turn the box back in line with the layer, which stays where it is."""
    angle = box_orientation_offset(rig)
    if abs(angle) <= 1.0e-7 or transform_animated(rig) or any(rig.lock_rotation):
        return False
    initial = _basis_world(rig)
    inverses = _children_inverses(rig)
    # Turn around the box anchor, so it stays on the same spot of the layer.
    anchor_local = layer_anchor_local(rig)
    pivot = (initial @ anchor_local) if anchor_local is not None else initial.translation.copy()
    normal = (initial.to_3x3() @ Vector((0.0, 0.0, 1.0)))
    if normal.length <= 1.0e-9:
        return False
    turn = Matrix.Translation(pivot) @ Matrix.Rotation(angle, 4, normal.normalized()) @ Matrix.Translation(-pivot)
    rig.matrix_world = turn @ initial
    _keep_children(rig, initial, inverses)
    return True


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
        except FBP_DATA_ERRORS:
            return False
        if not _gizmos_shown(context) or not cage_enabled(context):
            return False
        if _cage_layers(context):
            return True
        _BOX_STATE.clear()
        return False

    @classmethod
    def setup_keymap(cls, keyconfig):
        # Drag only: a plain click goes on to the selection operators. The
        # built-in drag keymaps leave Alt out, but the box uses Alt for
        # symmetric scaling, so this one takes a drag with any modifier.
        keymap = keyconfig.keymaps.new(
            name="FBP Layer Box Drag", space_type="EMPTY", region_type="WINDOW",
        )
        if not any(item.idname == "gizmogroup.gizmo_tweak" for item in keymap.keymap_items):
            keymap.keymap_items.new("gizmogroup.gizmo_tweak", "LEFTMOUSE", "CLICK_DRAG", any=True)
        return keymap

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
            center, size, outline, alpha = box_shape(rig, *rect)
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
            gizmo.fbp_outline = outline
            gizmo.fbp_alpha = alpha
            # Thin white lines as in Grease Pencil; other selected layers
            # are a dimmer grey so the active one stands out.
            gizmo.fbp_active = rig == active
            gizmo.matrix_basis = rig.matrix_world.normalized()
            _BOX_STATE[rig.name] = {
                "center": center.copy(), "size": size.copy(), "hidden": hidden,
                "outline": outline, "alpha": alpha,
            }


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
