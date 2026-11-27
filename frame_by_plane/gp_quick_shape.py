"""Quick Shape for the Grease Pencil Draw brush.

Draw a line, an arc, an ellipse or a rectangle and keep the pen still at its
end: the stroke turns into a clean shape. While the button is still held the
shape follows the cursor (lines and arcs from their start, closed shapes
around their center); the mouse wheel sets its number of points, the
precision key (Alt, or Shift) slows it down and Ctrl snaps it. Releasing the
button gives a stroke with only the shape's own points, which the Adjust
Last Operation panel can still change (points, curve type).

Blender's own ``grease_pencil.brush_stroke`` keeps drawing the stroke. This
operator starts it, then sits in front of it in the window's modal handlers:
it watches the events and passes them through while the stroke is free, and
once Quick Shape starts it keeps the events for itself and spreads the
stroke's points along the shape as a preview. On release the brush finishes
the hand-drawn stroke (its Undo step gives it back), then
``fbp.gp_quick_shape_apply`` replaces it with the shape's own points.
"""

from __future__ import annotations

import json
import math
import time

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras import view3d_utils
from mathutils import Vector

from .interface_preferences import fbp_get_addon_preferences
from .registration import register_classes, unregister_classes
from .runtime import FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS, fbp_warn_once


# Quick Shape can start only in the first seconds of a stroke; later the
# stroke stays free hand however long the pen rests.
DETECTION_WINDOW_SECONDS = 10.0
# Pixels the cursor may drift while it counts as still.
HOLD_TOLERANCE_PX = 6.0
# Shortest stroke, in pixels, that can become a line.
MIN_LENGTH_PX = 20.0
# Largest distance of the drawn path from the start-to-end chord, as a share
# of the chord length, with a floor in pixels for short strokes.
STRAIGHT_DEVIATION_RATIO = 0.1
STRAIGHT_DEVIATION_MIN_PX = 8.0
# The drawn path may be at most this much longer than the chord (rules out
# strokes that go back and forth on the same line).
STRAIGHT_PATH_RATIO = 1.25
TIMER_STEP_SECONDS = 0.02
_APPLY_DELAY = 0.0
_PASS_TIMERS = False

_MOVE_EVENTS = frozenset({"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"})
_SHIFT_KEYS = frozenset({"LEFT_SHIFT", "RIGHT_SHIFT", "LEFT_ALT", "RIGHT_ALT"})
_CTRL_KEYS = frozenset({"LEFT_CTRL", "RIGHT_CTRL", "OSKEY"})
_BRUSH_STROKE_ID = "GREASE_PENCIL_OT_brush_stroke"

_ADDON_KEYMAPS = []


def quick_shape_precision_key(context=None):
    """Modifier that slows the shape down: 'ALT' or 'SHIFT'."""
    preferences = fbp_get_addon_preferences(context)
    key = str(getattr(preferences, "gp_quick_shape_precision_key", "ALT") or "ALT")
    return key if key in {"ALT", "SHIFT"} else "ALT"


def quick_shape_settings(context=None):
    """Validated Quick Shape preferences: (enabled, hold, snap, precision)."""
    preferences = fbp_get_addon_preferences(context)
    enabled = bool(getattr(preferences, "gp_quick_shape_enabled", True))
    try:
        hold = float(getattr(preferences, "gp_quick_shape_hold_time", 0.4))
    except (TypeError, ValueError):
        hold = 0.4
    try:
        snap = float(str(getattr(preferences, "gp_quick_shape_snap_angle", "15") or "15"))
    except (TypeError, ValueError):
        snap = 15.0
    try:
        precision = float(getattr(preferences, "gp_quick_shape_precision", 0.25))
    except (TypeError, ValueError):
        precision = 0.25
    return (
        enabled,
        min(max(hold, 0.1), 3.0),
        min(max(snap, 1.0), 90.0),
        min(max(precision, 0.02), 1.0),
    )


def is_straight_path(points, tolerance_ratio=STRAIGHT_DEVIATION_RATIO):
    """Whether a screen path (sequence of (x, y)) is close to a straight line."""
    if len(points) < 2:
        return False
    sx, sy = points[0]
    ex, ey = points[-1]
    dx, dy = ex - sx, ey - sy
    chord = math.hypot(dx, dy)
    if chord < MIN_LENGTH_PX:
        return False
    limit = max(STRAIGHT_DEVIATION_MIN_PX, chord * tolerance_ratio)
    path_length = 0.0
    previous = points[0]
    for x, y in points:
        # Distance from the chord line; the chord is long enough to divide.
        if abs((x - sx) * dy - (y - sy) * dx) / chord > limit:
            return False
        path_length += math.hypot(x - previous[0], y - previous[1])
        previous = (x, y)
    # Points past either end of the chord make the stroke a hook, not a line.
    for x, y in points:
        along = ((x - sx) * dx + (y - sy) * dy) / chord
        if along < -limit or along > chord + limit:
            return False
    return path_length <= chord * STRAIGHT_PATH_RATIO + STRAIGHT_DEVIATION_MIN_PX


def snap_screen_angle(start, end, step_degrees):
    """End point with the start-to-end angle rounded to ``step_degrees``."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1.0e-6 or step_degrees <= 0.0:
        return end
    step = math.radians(step_degrees)
    angle = round(math.atan2(dy, dx) / step) * step
    return (start[0] + math.cos(angle) * length, start[1] + math.sin(angle) * length)


def _layer_to_world(obj, layer):
    """Matrix from the layer's point space to world space."""
    local = layer.matrix_local.copy()
    parent = getattr(layer, "parent", None)
    if parent is None:
        return obj.matrix_world @ local
    parent_matrix = parent.matrix_world.copy()
    bone_name = str(getattr(layer, "parent_bone", "") or "")
    if bone_name and getattr(parent, "type", "") == "ARMATURE":
        pose_bone = parent.pose.bones.get(bone_name) if parent.pose else None
        if pose_bone is not None:
            parent_matrix = parent_matrix @ pose_bone.matrix
    return parent_matrix @ layer.matrix_parent_inverse @ local


def _active_target(context):
    obj = getattr(context, "active_object", None)
    if obj is None or getattr(obj, "type", "") != "GREASEPENCIL":
        return None, None, None
    layer = obj.data.layers.active
    if layer is None:
        return obj, None, None
    frame = layer.current_frame()
    drawing = frame.drawing if frame is not None else None
    return obj, layer, drawing


def _curve_point_range(drawing, curve_index):
    offsets = drawing.curve_offsets
    return int(offsets[curve_index].value), int(offsets[curve_index + 1].value)


# -- shape recognition (screen space, pixels) -----------------------------

# A stroke whose end comes back within this share of its size (or this many
# pixels) of its start is a closed shape.
CLOSE_GAP_RATIO = 0.25
CLOSE_GAP_MIN_PX = 25.0
# Smallest closed shape or arc, in pixels.
MIN_SHAPE_PX = 24.0
# Mean distance of the drawn path from the recognized outline, as a share of
# the shape's size, above which the stroke stays free hand.
CLOSED_FIT_RATIO = 0.09
ARC_FIT_RATIO = 0.07
ARC_MAX_SWEEP = math.radians(300.0)

LINE, ARC, ELLIPSE, RECT = "LINE", "ARC", "ELLIPSE", "RECT"
# Handle types stored in ``handle_type_left/right`` (Blender's HD_FREE, HD_ALIGN).
_HANDLE_FREE = 0
_HANDLE_ALIGN = 3


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _rotate(vector, angle):
    c, s = math.cos(angle), math.sin(angle)
    return (vector[0] * c - vector[1] * s, vector[0] * s + vector[1] * c)


def _path_length(points):
    return sum(_dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def _signed_area(points):
    return 0.5 * sum(
        points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1]
        for i in range(len(points))
    )


def _bbox_diagonal(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def is_closed_path(points):
    if len(points) < 8:
        return False
    diagonal = _bbox_diagonal(points)
    if diagonal < MIN_SHAPE_PX:
        return False
    gap = _dist(points[0], points[-1])
    return gap <= max(CLOSE_GAP_MIN_PX, diagonal * CLOSE_GAP_RATIO) and _path_length(points) >= 1.8 * diagonal


def _local_frame(points, angle):
    """Center, half sizes and local coordinates of points in a rotated frame."""
    u = (math.cos(angle), math.sin(angle))
    v = (-u[1], u[0])
    a = [p[0] * u[0] + p[1] * u[1] for p in points]
    b = [p[0] * v[0] + p[1] * v[1] for p in points]
    ca, cb = (max(a) + min(a)) / 2.0, (max(b) + min(b)) / 2.0
    center = (ca * u[0] + cb * v[0], ca * u[1] + cb * v[1])
    local = [(x - ca, y - cb) for x, y in zip(a, b)]
    return center, (max(a) - min(a)) / 2.0, (max(b) - min(b)) / 2.0, local


def fit_ellipse(points):
    """Best ellipse for a closed path: (shape, mean distance)."""
    n = float(len(points))
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points) / n
    syy = sum((p[1] - my) ** 2 for p in points) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in points) / n
    angle = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    center, ra, rb, local = _local_frame(points, angle)
    if min(ra, rb) < 1.0:
        return None, float("inf")
    mean_radius = (ra + rb) / 2.0
    error = sum(abs(math.hypot(x / ra, y / rb) - 1.0) for x, y in local) / n * mean_radius
    shape = {
        "kind": ELLIPSE, "center": center, "rx": ra, "ry": rb, "angle": angle,
        "ccw": _signed_area(points) >= 0.0,
    }
    return shape, error


def fit_rect(points):
    """Best rectangle for a closed path: (shape, mean distance)."""
    sx = sy = 0.0
    for i in range(len(points) - 1):
        dx, dy = points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]
        length = math.hypot(dx, dy)
        if length > 0.0:
            # Four times the angle: edges at 90 degrees vote for the same axis.
            a = 4.0 * math.atan2(dy, dx)
            sx += math.cos(a) * length
            sy += math.sin(a) * length
    angle = math.atan2(sy, sx) / 4.0
    center, hw, hh, local = _local_frame(points, angle)
    if min(hw, hh) < 1.0:
        return None, float("inf")
    error = 0.0
    for x, y in local:
        dx, dy = abs(x) - hw, abs(y) - hh
        if dx > 0.0 or dy > 0.0:
            error += math.hypot(max(dx, 0.0), max(dy, 0.0))
        else:
            error += -max(dx, dy)
    error /= float(len(points))
    shape = {
        "kind": RECT, "center": center, "rx": hw, "ry": hh, "angle": angle,
        "ccw": _signed_area(points) >= 0.0,
    }
    return shape, error


def _circumcircle(a, b, c):
    d = 2.0 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1.0e-9:
        return None
    a2 = a[0] ** 2 + a[1] ** 2
    b2 = b[0] ** 2 + b[1] ** 2
    c2 = c[0] ** 2 + c[1] ** 2
    ux = (a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d
    uy = (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d
    return (ux, uy)


def _point_at_length(points, target):
    walked = 0.0
    for i in range(len(points) - 1):
        step = _dist(points[i], points[i + 1])
        if walked + step >= target and step > 0.0:
            t = (target - walked) / step
            return (
                points[i][0] + (points[i + 1][0] - points[i][0]) * t,
                points[i][1] + (points[i + 1][1] - points[i][1]) * t,
            )
        walked += step
    return points[-1]


def fit_arc(points):
    """Circular arc from the start to the end of an open path, or None."""
    if len(points) < 5 or _dist(points[0], points[-1]) < MIN_SHAPE_PX:
        return None
    start, end = points[0], points[-1]
    middle = _point_at_length(points, _path_length(points) / 2.0)
    center = _circumcircle(start, middle, end)
    if center is None:
        return None
    radius = _dist(center, start)
    error = sum(abs(_dist(center, p) - radius) for p in points) / float(len(points))
    if error > radius * ARC_FIT_RATIO:
        return None
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    am = math.atan2(middle[1] - center[1], middle[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    ccw = ((middle[0] - start[0]) * (end[1] - middle[1]) - (middle[1] - start[1]) * (end[0] - middle[0])) > 0.0
    turn = 1.0 if ccw else -1.0

    def sweep_to(angle):
        delta = (angle - a0) * turn
        return delta % (2.0 * math.pi)

    sweep = sweep_to(a1)
    if sweep_to(am) > sweep or sweep > ARC_MAX_SWEEP:
        return None
    # Every point must move forward along the arc (no back and forth).
    previous = 0.0
    for p in points[1:]:
        current = sweep_to(math.atan2(p[1] - center[1], p[0] - center[0]))
        if current > sweep + 0.35 or current + 0.35 < previous:
            return None
        previous = max(previous, current)
    return {"kind": ARC, "center": center, "radius": radius, "start_angle": a0, "sweep": sweep * turn}


def recognize_shape(points):
    """Shape for a screen path the pen rested at the end of, or None."""
    if len(points) < 2:
        return None
    if is_straight_path(points):
        return {"kind": LINE, "start": points[0], "end": points[-1]}
    if is_closed_path(points):
        ellipse, ellipse_error = fit_ellipse(points)
        rect, rect_error = fit_rect(points)
        shape, error = (ellipse, ellipse_error) if ellipse_error <= rect_error else (rect, rect_error)
        if shape is not None and error <= CLOSED_FIT_RATIO * (shape["rx"] + shape["ry"]):
            return shape
        return None
    return fit_arc(points)


def shape_anchor(shape):
    """Point the shape turns and scales around while the cursor moves."""
    if shape["kind"] == LINE:
        return shape["start"]
    if shape["kind"] == ARC:
        return _arc_point(shape, 0.0)
    return shape["center"]


def _arc_point(shape, fraction):
    angle = shape["start_angle"] + shape["sweep"] * fraction
    c = shape["center"]
    return (c[0] + shape["radius"] * math.cos(angle), c[1] + shape["radius"] * math.sin(angle))


def transform_shape(shape, angle, scale, snap_degrees=0.0):
    """Shape turned by ``angle`` and scaled around its anchor.

    With ``snap_degrees`` (Ctrl) lines and arcs snap the start-to-end
    direction, ellipses become circles and rectangles squares, and both
    snap their rotation.
    """
    anchor = shape_anchor(shape)

    def move(point):
        offset = _rotate((point[0] - anchor[0], point[1] - anchor[1]), angle)
        return (anchor[0] + offset[0] * scale, anchor[1] + offset[1] * scale)

    kind = shape["kind"]
    step = math.radians(snap_degrees) if snap_degrees > 0.0 else 0.0
    if kind == LINE:
        end = move(shape["end"])
        if step:
            end = snap_screen_angle(anchor, end, snap_degrees)
        return {"kind": LINE, "start": anchor, "end": end}
    if kind == ARC:
        result = dict(shape)
        result["center"] = move(shape["center"])
        result["radius"] = shape["radius"] * scale
        result["start_angle"] = shape["start_angle"] + angle
        if step:
            end = _arc_point(result, 1.0)
            chord = math.atan2(end[1] - anchor[1], end[0] - anchor[0])
            correction = round(chord / step) * step - chord
            offset = _rotate((result["center"][0] - anchor[0], result["center"][1] - anchor[1]), correction)
            result["center"] = (anchor[0] + offset[0], anchor[1] + offset[1])
            result["start_angle"] += correction
        return result
    result = dict(shape)
    result["rx"] = shape["rx"] * scale
    result["ry"] = shape["ry"] * scale
    result["angle"] = shape["angle"] + angle
    if step:
        size = (result["rx"] + result["ry"]) / 2.0
        result["rx"] = result["ry"] = size
        result["angle"] = round(result["angle"] / step) * step
    return result


DEFAULT_POINTS = {LINE: 2, ARC: 3, ELLIPSE: 4, RECT: 4}
_MIN_POINTS = {LINE: 2, ARC: 2, ELLIPSE: 3, RECT: 4}
MAX_POINTS = 256
DEFAULT_CURVE_TYPE = {LINE: "POLY", ARC: "BEZIER", ELLIPSE: "BEZIER", RECT: "POLY"}
SHAPE_LABELS = {LINE: "Line", ARC: "Arc", ELLIPSE: "Ellipse", RECT: "Rectangle"}


def points_step(kind):
    """Mouse wheel step for the number of points (a side each for rectangles)."""
    return 4 if kind == RECT else 1


def clamp_points(kind, count):
    count = max(_MIN_POINTS.get(kind, 2), min(MAX_POINTS, int(count)))
    if kind == RECT:
        count = max(4, int(round(count / 4.0)) * 4)
    return count


def _polyline_knots(points, cyclic):
    """Knots of straight segments: each handle a third of the way to its neighbour."""
    knots = []
    count = len(points)
    for i, p in enumerate(points):
        if cyclic:
            previous, following = points[i - 1], points[(i + 1) % count]
        else:
            previous = points[i - 1] if i > 0 else (2.0 * p[0] - points[1][0], 2.0 * p[1] - points[1][1])
            following = points[i + 1] if i + 1 < count else (2.0 * p[0] - points[i - 1][0], 2.0 * p[1] - points[i - 1][1])
        left = (p[0] + (previous[0] - p[0]) / 3.0, p[1] + (previous[1] - p[1]) / 3.0)
        right = (p[0] + (following[0] - p[0]) / 3.0, p[1] + (following[1] - p[1]) / 3.0)
        knots.append((left, p, right))
    return knots


def shape_knots(shape, count=None):
    """Control points of a shape.

    Returns ([(left handle, point, right handle)], cyclic, smooth): smooth
    shapes (ellipse, arc) have aligned handles, the others sharp corners.
    """
    kind = shape["kind"]
    count = clamp_points(kind, DEFAULT_POINTS[kind] if count is None else count)
    if kind == LINE:
        s, e = shape["start"], shape["end"]
        points = [
            (s[0] + (e[0] - s[0]) * i / (count - 1), s[1] + (e[1] - s[1]) * i / (count - 1))
            for i in range(count)
        ]
        return _polyline_knots(points, False), False, False
    if kind == ARC:
        step = shape["sweep"] / (count - 1)
        handle = 4.0 / 3.0 * math.tan(abs(step) / 4.0) * shape["radius"]
        turn = 1.0 if shape["sweep"] >= 0.0 else -1.0
        knots = []
        for i in range(count):
            fraction = i / (count - 1)
            angle = shape["start_angle"] + shape["sweep"] * fraction
            p = _arc_point(shape, fraction)
            tangent = (-math.sin(angle) * turn * handle, math.cos(angle) * turn * handle)
            knots.append(((p[0] - tangent[0], p[1] - tangent[1]), p, (p[0] + tangent[0], p[1] + tangent[1])))
        return knots, False, True
    c, rx, ry = shape["center"], shape["rx"], shape["ry"]
    u = (math.cos(shape["angle"]), math.sin(shape["angle"]))
    v = (-u[1], u[0])
    turn = 1.0 if shape["ccw"] else -1.0

    def at(x, y):
        return (c[0] + u[0] * x + v[0] * y, c[1] + u[1] * x + v[1] * y)

    if kind == RECT:
        corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        if not shape["ccw"]:
            corners.reverse()
        corners = [at(sx * rx, sy * ry) for sx, sy in corners]
        per_side = count // 4
        points = []
        for j in range(4):
            a, b = corners[j], corners[(j + 1) % 4]
            for i in range(per_side):
                t = i / per_side
                points.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        return _polyline_knots(points, True), True, False
    step = 2.0 * math.pi / count
    handle = 4.0 / 3.0 * math.tan(step / 4.0)
    knots = []
    for i in range(count):
        t = turn * i * step
        p = at(rx * math.cos(t), ry * math.sin(t))
        d = (-rx * math.sin(t) * turn * handle, ry * math.cos(t) * turn * handle)
        d = (u[0] * d[0] + v[0] * d[1], u[1] * d[0] + v[1] * d[1])
        knots.append(((p[0] - d[0], p[1] - d[1]), p, (p[0] + d[0], p[1] + d[1])))
    return knots, True, True


def _bezier(p0, p1, p2, p3, t):
    s = 1.0 - t
    return tuple(
        s * s * s * p0[i] + 3.0 * s * s * t * p1[i] + 3.0 * s * t * t * p2[i] + t * t * t * p3[i]
        for i in range(2)
    )


def sample_knots(knots, cyclic, count):
    """``count`` points along the outline, closing back to the start."""
    segments = [(knots[i], knots[i + 1]) for i in range(len(knots) - 1)]
    if cyclic:
        segments.append((knots[-1], knots[0]))
    lengths = [max(_dist(a[1], a[2]) + _dist(a[2], b[0]) + _dist(b[0], b[1]), 1.0e-6) for a, b in segments]
    total = sum(lengths)
    count = max(2, int(count))
    result = []
    for i in range(count):
        target = total * i / (count - 1)
        for (a, b), length in zip(segments, lengths):
            if target <= length or (a, b) == segments[-1]:
                t = min(max(target / length, 0.0), 1.0)
                result.append(_bezier(a[1], a[2], b[0], b[1], t))
                break
            target -= length
    return result
def _median(values, fallback):
    values = sorted(values)
    return values[len(values) // 2] if values else fallback


# -- screen to drawing mapping ---------------------------------------------


def make_mapping(region, rv3d, plane_origin, plane_normal, to_layer):
    """Everything needed to place screen points on the drawing plane.

    Stored as plain lists so the Adjust Last Operation panel can rebuild the
    shape after the view has gone.
    """
    return {
        "persinv": [list(row) for row in rv3d.perspective_matrix.inverted_safe()],
        "size": [float(region.width), float(region.height)],
        "origin": list(plane_origin),
        "normal": list(plane_normal),
        "to_layer": [list(row) for row in to_layer],
    }


def map_point(mapping, screen):
    """Layer-space point of the drawing plane under a screen point, or None."""
    from mathutils import Matrix, Vector as V

    persinv = Matrix(mapping["persinv"])
    width, height = mapping["size"]
    x = 2.0 * screen[0] / width - 1.0
    y = 2.0 * screen[1] / height - 1.0
    near = persinv @ V((x, y, -1.0, 1.0))
    far = persinv @ V((x, y, 1.0, 1.0))
    if abs(near.w) < 1.0e-12 or abs(far.w) < 1.0e-12:
        return None
    near = near.xyz / near.w
    far = far.xyz / far.w
    direction = far - near
    normal = V(mapping["normal"])
    denominator = direction.dot(normal)
    if abs(denominator) < 1.0e-12:
        return None
    t = (V(mapping["origin"]) - near).dot(normal) / denominator
    return Matrix(mapping["to_layer"]) @ (near + direction * t)


# -- stroke rewriting --------------------------------------------------------

_SKIP_COPY = frozenset({
    "position", "curve_type", "cyclic", "handle_left", "handle_right",
    "handle_type_left", "handle_type_right", "radius", "opacity",
})


def _attribute_value(item):
    for field in ("value", "vector", "color"):
        if hasattr(item, field):
            value = getattr(item, field)
            return field, (tuple(value) if hasattr(value, "__len__") else value)
    return None, None


def write_shape_stroke(drawing, index, knots, cyclic, smooth, curve_type, radius=None, opacity=None):
    """Replace stroke ``index`` by a new stroke with exactly ``knots``.

    ``knots`` are (left, point, right) in layer space. The new stroke keeps
    the material, colors and other settings of the old one and its place in
    the drawing order. Returns the index of the new stroke.
    """
    attributes = drawing.attributes
    first, last = _curve_point_range(drawing, index)
    copied = []
    for attribute in attributes:
        name = attribute.name
        if name in _SKIP_COPY or name.startswith(".") or attribute.domain not in {"POINT", "CURVE"}:
            continue
        source = index if attribute.domain == "CURVE" else first
        field, value = _attribute_value(attribute.data[source])
        if field is not None:
            copied.append((name, attribute.domain, field, value))
    if radius is None:
        radius = _median([attributes["radius"].data[i].value for i in range(first, last)], None)
    if opacity is None and attributes.get("opacity") is not None:
        opacity = _median([attributes["opacity"].data[i].value for i in range(first, last)], None)

    count = len(drawing.strokes)
    drawing.remove_strokes(indices=[index])
    drawing.add_strokes([len(knots)])
    new_index = count - 1
    if curve_type != "POLY":
        drawing.set_types(type=curve_type, indices=[new_index])
    stroke = drawing.strokes[new_index]
    stroke.cyclic = bool(cyclic)
    attributes = drawing.attributes
    first, _last = _curve_point_range(drawing, new_index)
    for name, domain, field, value in copied:
        attribute = attributes.get(name)
        if attribute is None:
            continue
        targets = [new_index] if domain == "CURVE" else range(first, first + len(knots))
        for target in targets:
            try:
                setattr(attribute.data[target], field, value)
            except FBP_DATA_ERRORS:
                break
    positions = attributes["position"].data
    for offset, (_left, point, _right) in enumerate(knots):
        positions[first + offset].vector = point
    if curve_type == "BEZIER":
        for name, kind in (
            ("handle_left", "FLOAT_VECTOR"), ("handle_right", "FLOAT_VECTOR"),
            ("handle_type_left", "INT8"), ("handle_type_right", "INT8"),
        ):
            if attributes.get(name) is None:
                attributes.new(name, kind, "POINT")
        handle_type = _HANDLE_ALIGN if smooth else _HANDLE_FREE
        lefts = attributes["handle_left"].data
        rights = attributes["handle_right"].data
        left_types = attributes["handle_type_left"].data
        right_types = attributes["handle_type_right"].data
        for offset, (left, _point, right) in enumerate(knots):
            lefts[first + offset].vector = left
            rights[first + offset].vector = right
            left_types[first + offset].value = handle_type
            right_types[first + offset].value = handle_type
    for point in stroke.points:
        if radius is not None:
            point.radius = radius
        if opacity is not None:
            point.opacity = opacity
    if index != new_index:
        order = list(range(count))
        order.insert(index, order.pop())
        drawing.reorder_strokes(new_indices=order)
        new_index = index
    drawing.tag_positions_changed()
    return new_index


def _find_drawing(data):
    obj = bpy.data.objects.get(data["object"])
    if obj is None or getattr(obj, "type", "") != "GREASEPENCIL":
        return None
    layer = obj.data.layers.get(data["layer"])
    if layer is None:
        return None
    frame = layer.get_frame_at(int(data["frame"]))
    return frame.drawing if frame is not None else None


def _shape_from_data(data):
    shape = dict(data["shape"])
    for key in ("start", "end", "center"):
        if key in shape:
            shape[key] = tuple(shape[key])
    return shape


CURVE_TYPE_ITEMS = (
    ("POLY", "Poly", "Straight segments between the points"),
    ("BEZIER", "Bézier", "Bézier points with handles"),
    ("CATMULL_ROM", "Catmull Rom", "Smooth curve through the points"),
    ("NURBS", "NURBS", "Smooth curve guided by the points"),
)


class FBP_OT_GPQuickShapeApply(Operator):
    """Turn the stroke just drawn into a clean Quick Shape"""

    bl_idname = "fbp.gp_quick_shape_apply"
    bl_label = "Quick Shape"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    points: IntProperty(
        name="Points",
        description="Number of points of the shape. Rectangles keep the same number on each side",
        default=2,
        min=2,
        max=MAX_POINTS,
    )
    curve_type: EnumProperty(
        name="Curve Type",
        description="Curve type of the shape's stroke",
        items=CURVE_TYPE_ITEMS,
        default="POLY",
    )
    data: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def draw(self, _context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        try:
            kind = json.loads(self.data)["shape"]["kind"]
        except (ValueError, KeyError, TypeError):
            kind = None
        if kind in SHAPE_LABELS:
            layout.label(text=SHAPE_LABELS[kind], icon="GREASEPENCIL")
        layout.prop(self, "points")
        layout.prop(self, "curve_type")

    def execute(self, _context):
        try:
            data = json.loads(self.data)
            shape = _shape_from_data(data)
            drawing = _find_drawing(data)
            index = int(data["index"])
            if drawing is None or len(drawing.strokes) != int(data["count"]) or index >= len(drawing.strokes):
                return {"CANCELLED"}
            points = clamp_points(shape["kind"], self.points)
            if points != self.points:
                self.points = points
            knots, cyclic, smooth = shape_knots(shape, points)
            mapping = data["mapping"]
            located = []
            for triple in knots:
                located.append(tuple(map_point(mapping, p) for p in triple))
                if any(p is None for p in located[-1]):
                    return {"CANCELLED"}
            write_shape_stroke(
                drawing, index, located, cyclic, smooth, self.curve_type,
                data.get("radius"), data.get("opacity"),
            )
        except (ValueError, KeyError, TypeError, *FBP_DATA_IO_ERRORS) as exc:
            fbp_warn_once("gp_quick_shape.apply", "Quick Shape could not rebuild the stroke", exc)
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_GPQuickShapeStroke(Operator):
    """Draw with the brush; rest the pen at the end of a line, arc, ellipse or rectangle to turn it into a clean shape (wheel: points, Alt or Shift: precise, Ctrl: snap)"""

    bl_idname = "fbp.gp_quick_shape_stroke"
    bl_label = "Draw with Quick Shape"
    bl_options = {"INTERNAL"}

    brush_toggle: EnumProperty(
        name="Brush Toggle",
        items=(
            ("NORMAL", "Normal", "Draw with the brush as it is"),
            ("SMOOTH", "Smooth", "Draw with the stroke stabilizer, as Shift does"),
        ),
        default="NORMAL",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        if str(getattr(context, "mode", "") or "") != "PAINT_GREASE_PENCIL":
            return False
        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        if area is None or area.type != "VIEW_3D" or region is None or region.type != "WINDOW":
            return False
        if not quick_shape_settings(context)[0]:
            return False
        try:
            brush = context.tool_settings.gpencil_paint.brush
            return brush is not None and brush.gpencil_brush_type == "DRAW"
        except FBP_DATA_ERRORS:
            return False

    # -- lifecycle ---------------------------------------------------------

    def invoke(self, context, event):
        _enabled, self._hold, self._snap, self._precision = quick_shape_settings(context)
        self._precision_key = quick_shape_precision_key(context)
        self._area = context.area
        self._region = context.region
        self._rv3d = context.region_data
        self._window = context.window
        self._button = event.type
        self._started = time.monotonic()
        start = (float(event.mouse_region_x), float(event.mouse_region_y))
        self._path = [start]
        self._rest_anchor = start
        self._rest_since = self._started
        self._state = "WATCH"
        self._timer = None
        self._shape = None
        self._header = False

        _obj, _layer, drawing = _active_target(context)
        try:
            self._baseline = (
                int(drawing.as_pointer()) if drawing is not None else 0,
                len(drawing.strokes) if drawing is not None else 0,
            )
        except FBP_DATA_ERRORS:
            self._baseline = (0, 0)

        if self.brush_toggle == "NORMAL":
            result = bpy.ops.grease_pencil.brush_stroke("INVOKE_DEFAULT")
        else:
            result = bpy.ops.grease_pencil.brush_stroke("INVOKE_DEFAULT", brush_toggle=self.brush_toggle)
        if "RUNNING_MODAL" not in result:
            return {"FINISHED"} if "FINISHED" in result else {"CANCELLED"}
        try:
            self._timer = context.window_manager.event_timer_add(TIMER_STEP_SECONDS, window=context.window)
        except FBP_DATA_ERRORS:
            self._timer = None
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except FBP_DATA_ERRORS:
                pass
            self._timer = None
        if self._header:
            try:
                self._area.header_text_set(None)
            except FBP_DATA_ERRORS:
                pass
            self._header = False

    def _brush_running(self):
        try:
            return any(
                str(getattr(op, "bl_idname", "") or "") == _BRUSH_STROKE_ID
                for op in self._window.modal_operators
            )
        except FBP_DATA_ERRORS:
            return False

    # -- events ------------------------------------------------------------

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except FBP_DATA_IO_ERRORS as exc:
            fbp_warn_once("gp_quick_shape.modal", "Quick Shape stopped", exc)
            self._finish(context)
            return {"FINISHED", "PASS_THROUGH"}

    def _modal(self, context, event):
        released = event.type == self._button and event.value == "RELEASE"
        if self._state == "WATCH":
            if released:
                self._finish(context)
                return {"FINISHED", "PASS_THROUGH"}
            now = time.monotonic()
            if now - self._started > DETECTION_WINDOW_SECONDS or (
                event.type == "TIMER" and not self._brush_running()
            ):
                # Past the detection window the stroke stays free hand.
                self._finish(context)
                return {"FINISHED", "PASS_THROUGH"}
            if event.type in _MOVE_EVENTS:
                point = (float(event.mouse_region_x), float(event.mouse_region_y))
                if math.hypot(point[0] - self._path[-1][0], point[1] - self._path[-1][1]) >= 1.0:
                    self._path.append(point)
                if math.hypot(point[0] - self._rest_anchor[0], point[1] - self._rest_anchor[1]) > HOLD_TOLERANCE_PX:
                    self._rest_anchor = point
                    self._rest_since = now
            elif event.type == "TIMER" and now - self._rest_since >= self._hold:
                if self._begin_shape(context, event):
                    self._state = "SHAPE"
                    return {"RUNNING_MODAL"}
                # No shape: wait for the cursor to move and rest again.
                self._rest_since = now
            return {"PASS_THROUGH"}

        # SHAPE: the shape follows the cursor until release. Apart from the
        # release the brush gets no more events, so it neither extends the
        # stroke nor reacts to Shift.
        if released:
            self._update_shape(event, final=True)
            self._finish(context)
            return {"FINISHED", "PASS_THROUGH"}
        if event.type == "TIMER":
            if not self._brush_running():
                self._finish(context)
                return {"FINISHED", "PASS_THROUGH"}
            return {"PASS_THROUGH"} if _PASS_TIMERS else {"RUNNING_MODAL"}
        if event.type in _MOVE_EVENTS:
            mouse = (float(event.mouse_region_x), float(event.mouse_region_y))
            slow = event.alt if self._precision_key == "ALT" else event.shift
            factor = self._precision if slow else 1.0
            self._target = (
                self._target[0] + (mouse[0] - self._last_mouse[0]) * factor,
                self._target[1] + (mouse[1] - self._last_mouse[1]) * factor,
            )
            self._last_mouse = mouse
            self._update_shape(event)
        elif event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and event.value == "PRESS":
            kind = self._shape["kind"]
            step = points_step(kind) * (1 if event.type == "WHEELUPMOUSE" else -1)
            self._points = clamp_points(kind, self._points + step)
            self._update_shape(event)
        elif event.type in _SHIFT_KEYS or event.type in _CTRL_KEYS:
            self._update_shape(event)
        elif event.type in {"ESC", "RIGHTMOUSE"}:
            # Let the brush cancel the stroke as usual.
            self._finish(context)
            return {"FINISHED", "PASS_THROUGH"}
        return {"RUNNING_MODAL"}

    def _rested_path(self, start_screen):
        """Drawn path up to where the cursor came to rest, from the stroke start."""
        anchor = self._rest_anchor
        path = list(self._path)
        while len(path) > 2 and math.hypot(path[-1][0] - anchor[0], path[-1][1] - anchor[1]) <= HOLD_TOLERANCE_PX:
            path.pop()
        path.append(anchor)
        path[0] = start_screen
        return path

    # -- geometry ----------------------------------------------------------

    def _begin_shape(self, context, event):
        obj, layer, drawing = _active_target(context)
        if drawing is None:
            return False
        count = len(drawing.strokes)
        if count == 0:
            return False
        pointer = int(drawing.as_pointer())
        if pointer == self._baseline[0] and count != self._baseline[1] + 1:
            return False
        try:
            on_back = bool(context.scene.tool_settings.use_gpencil_draw_onback)
        except FBP_DATA_ERRORS:
            on_back = False
        curve_index = 0 if on_back else count - 1
        first, last = _curve_point_range(drawing, curve_index)
        if last - first < 2:
            return False

        positions = drawing.attributes["position"].data
        to_world = _layer_to_world(obj, layer)
        self._original = [Vector(positions[i].vector) for i in range(first, last)]
        world_points = [to_world @ point for point in self._original]
        start_world = world_points[0]
        start_screen = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, start_world)
        if start_screen is None:
            return False
        shape = recognize_shape(self._rested_path((float(start_screen.x), float(start_screen.y))))
        if shape is None:
            return False

        self._shape = shape
        self._points = DEFAULT_POINTS[shape["kind"]]
        self._drawing_pointer = pointer
        self._target_info = {
            "object": obj.name,
            "layer": layer.name,
            "frame": int(layer.current_frame().frame_number),
            "index": curve_index,
            "count": count,
        }
        self._obj_name = obj.name
        self._curve_index = curve_index
        self._point_count = last - first
        self._mapping = make_mapping(
            self._region, self._rv3d, start_world,
            self._placement_normal(context, world_points), to_world.inverted_safe(),
        )
        self._anchor = shape_anchor(shape)
        self._target = self._rest_anchor
        self._reference = (self._target[0] - self._anchor[0], self._target[1] - self._anchor[1])
        self._last_mouse = (float(event.mouse_region_x), float(event.mouse_region_y))
        try:
            radius = drawing.attributes["radius"].data
            self._radius = _median([radius[i].value for i in range(first, last)], None)
        except (KeyError, *FBP_DATA_ERRORS):
            self._radius = None
        try:
            opacity = drawing.attributes["opacity"].data
            self._opacity = _median([opacity[i].value for i in range(first, last)], None)
        except (KeyError, *FBP_DATA_ERRORS):
            self._opacity = None
        self._update_shape(event)
        return True

    def _placement_normal(self, context, world_points):
        """Normal of the plane the stroke was drawn on, in world space."""
        view_normal = (self._rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))).normalized()
        candidates = []
        try:
            lock = str(context.scene.tool_settings.gpencil_sculpt.lock_axis)
        except FBP_DATA_ERRORS:
            lock = "VIEW"
        preferred = {
            "AXIS_X": Vector((1.0, 0.0, 0.0)),
            "AXIS_Y": Vector((0.0, 1.0, 0.0)),
            "AXIS_Z": Vector((0.0, 0.0, 1.0)),
        }.get(lock)
        if lock == "CURSOR":
            try:
                preferred = (context.scene.cursor.matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
            except FBP_DATA_ERRORS:
                preferred = None
        if preferred is not None:
            candidates.append(preferred)
        candidates.append(view_normal)
        obj = context.active_object
        rotation = obj.matrix_world.to_3x3().normalized()
        for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
            candidates.append(Vector(axis))
            candidates.append((rotation @ Vector(axis)).normalized())

        origin = world_points[0]
        extent = max(((point - origin).length for point in world_points), default=0.0)
        tolerance = max(extent * 0.02, 1.0e-6)

        def residual(normal):
            return max(abs((point - origin).dot(normal)) for point in world_points)

        # The plane must also face the view, or the shape cannot be placed
        # under the cursor.
        usable = [n for n in candidates if abs(n.dot(view_normal)) > 0.05]
        for normal in usable:
            if residual(normal) <= tolerance:
                return normal
        if usable:
            best = min(usable, key=residual)
            if residual(best) <= extent * 0.15:
                return best
        return view_normal

    def _current_shape(self, event):
        reference = self._reference
        current = (self._target[0] - self._anchor[0], self._target[1] - self._anchor[1])
        reference_length = math.hypot(*reference)
        if reference_length < 2.0 or math.hypot(*current) < 1.0:
            angle, scale = 0.0, 1.0
        else:
            angle = math.atan2(current[1], current[0]) - math.atan2(reference[1], reference[0])
            scale = math.hypot(*current) / reference_length
        snap = self._snap if (event.ctrl or event.oskey) else 0.0
        return transform_shape(self._shape, angle, scale, snap)

    def _live_drawing(self):
        obj = bpy.data.objects.get(self._obj_name)
        if obj is None:
            return None
        layer = obj.data.layers.active
        frame = layer.current_frame() if layer is not None else None
        drawing = frame.drawing if frame is not None else None
        if drawing is None or int(drawing.as_pointer()) != self._drawing_pointer:
            return None
        if self._curve_index >= len(drawing.strokes):
            return None
        first, last = _curve_point_range(drawing, self._curve_index)
        if last - first != self._point_count:
            return None
        return drawing

    def _show_header(self):
        kind = self._shape["kind"]
        tip = bpy.app.translations.pgettext_iface
        text = "{}: {} · {} {} · {}".format(
            tip("Quick Shape"), tip(SHAPE_LABELS[kind]), self._points, tip("Points"),
            tip("Wheel: points, Alt: precise, Ctrl: snap" if self._precision_key == "ALT" else "Wheel: points, Shift: precise, Ctrl: snap"),
        )
        try:
            self._area.header_text_set(text)
            self._header = True
        except FBP_DATA_ERRORS:
            pass

    def _update_shape(self, event, final=False):
        drawing = self._live_drawing()
        if drawing is None:
            return
        shape = self._current_shape(event)
        if final:
            # The brush finishes the stroke as it was drawn, so its Undo step
            # holds the hand-drawn stroke (Ctrl+Z after a Quick Shape gives it
            # back); the Quick Shape operator then replaces it.
            first, _last = _curve_point_range(drawing, self._curve_index)
            positions = drawing.attributes["position"].data
            for offset, point in enumerate(self._original):
                positions[first + offset].vector = point
            drawing.tag_positions_changed()
            data = dict(self._target_info)
            data.update(shape=shape, mapping=self._mapping, radius=self._radius, opacity=self._opacity)
            _schedule_apply(self._window, self._area, self._region, data, self._points, DEFAULT_CURVE_TYPE[shape["kind"]])
            return
        knots, cyclic, _smooth = shape_knots(shape, self._points)
        # While the pen is down the stroke keeps its points, spread along the
        # outline: the brush still owns them and changing their number under
        # it is not safe. A closed outline stops just short of its start.
        first, _last = _curve_point_range(drawing, self._curve_index)
        positions = drawing.attributes["position"].data
        count = self._point_count
        samples = sample_knots(knots, cyclic, count + 1 if cyclic else count)[:count]
        for offset, point in enumerate(samples):
            location = map_point(self._mapping, point)
            if location is not None:
                positions[first + offset].vector = location
        drawing.tag_positions_changed()
        if self._area is not None:
            self._area.tag_redraw()
        self._show_header()


def _schedule_apply(window, area, region, data, points, curve_type):
    """Run the Quick Shape operator once the brush has finished the stroke.

    The brush finishes the hand-drawn stroke on release and pushes its own
    Undo step; the operator then replaces the stroke by the shape's own
    points, with its own Undo step and the Adjust Last Operation panel.
    """
    payload = json.dumps(data)

    def apply():
        try:
            override = {"window": window}
            if area is not None and any(a == area for a in window.screen.areas):
                override.update(area=area, region=region)
            with bpy.context.temp_override(**override):
                # ``True``: register the call like a user action, so it gets
                # its own Undo step and the Adjust Last Operation panel.
                bpy.ops.fbp.gp_quick_shape_apply(
                    "EXEC_DEFAULT", True, points=points, curve_type=curve_type, data=payload,
                )
        except FBP_DATA_IO_ERRORS as exc:
            fbp_warn_once("gp_quick_shape.final", "Quick Shape could not simplify the stroke", exc)
        return None

    bpy.app.timers.register(apply, first_interval=_APPLY_DELAY)


classes = (FBP_OT_GPQuickShapeApply, FBP_OT_GPQuickShapeStroke)


def _register_keymaps():
    _unregister_keymaps()
    window_manager = getattr(bpy.context, "window_manager", None)
    keyconfig = getattr(getattr(window_manager, "keyconfigs", None), "addon", None)
    if keyconfig is None:
        return False
    try:
        keymap = keyconfig.keymaps.new(name="Grease Pencil Brush Stroke", space_type="EMPTY", region_type="WINDOW")
        item = keymap.keymap_items.new(FBP_OT_GPQuickShapeStroke.bl_idname, "LEFTMOUSE", "PRESS", head=True)
        _ADDON_KEYMAPS.append((keymap, item))
        # Shift+click draws with the stroke stabilizer; Quick Shape works there too.
        item = keymap.keymap_items.new(FBP_OT_GPQuickShapeStroke.bl_idname, "LEFTMOUSE", "PRESS", shift=True, head=True)
        item.properties.brush_toggle = "SMOOTH"
        _ADDON_KEYMAPS.append((keymap, item))
        return True
    except FBP_DATA_ERRORS as exc:
        _unregister_keymaps()
        fbp_warn_once("gp_quick_shape.keymap", "Could not register the Grease Pencil Quick Shape shortcut", exc)
        return False


def _unregister_keymaps():
    while _ADDON_KEYMAPS:
        keymap, item = _ADDON_KEYMAPS.pop()
        try:
            keymap.keymap_items.remove(item)
        except FBP_DATA_ERRORS:
            pass


def register():
    register_classes(classes)
    _register_keymaps()


def unregister():
    _unregister_keymaps()
    unregister_classes(classes)
