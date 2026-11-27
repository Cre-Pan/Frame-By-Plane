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

_MOVE_EVENTS = frozenset({"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"})
_SHIFT_KEYS = frozenset({"LEFT_SHIFT", "RIGHT_SHIFT", "LEFT_ALT", "RIGHT_ALT"})
_CTRL_KEYS = frozenset({"LEFT_CTRL", "RIGHT_CTRL", "OSKEY"})
_BRUSH_STROKE_ID = "GREASE_PENCIL_OT_brush_stroke"

_ADDON_KEYMAPS = []


def quick_shape_precision_key(context=None):
    """Modifier that slows the shape down: 'ALT' or 'SHIFT'."""
    preferences = fbp_get_addon_preferences(context)
    key = str(getattr(preferences, "gp_quick_shape_precision_key", "SHIFT") or "SHIFT")
    return key if key in {"ALT", "SHIFT"} else "SHIFT"


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
ARC_FIT_RATIO = 0.05
ELLIPSE_ARC_FIT_RATIO = 0.06
ARC_MAX_SWEEP = math.radians(300.0)

LINE, ARC, ELLIPSE, RECT = "LINE", "ARC", "ELLIPSE", "RECT"
POLYLINE, POLYGON = "POLYLINE", "POLYGON"
# Handle types stored in ``handle_type_left/right`` (Blender's HD_FREE, HD_ALIGN).
_HANDLE_FREE = 0
_HANDLE_AUTO = 1
_HANDLE_VECTOR = 2
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


# Points the drawn path is resampled to before fitting, evenly along its
# length, so slow (dense) parts of the stroke do not weigh more.
FIT_SAMPLES = 96


def resample_path(points, count=FIT_SAMPLES):
    """``count`` points evenly spaced along a path, keeping both ends."""
    if len(points) < 2:
        return list(points)
    steps = [_dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = sum(steps)
    if total <= 0.0:
        return [points[0]] * 2
    result = [points[0]]
    index, walked = 0, 0.0
    for i in range(1, count - 1):
        target = total * i / (count - 1)
        while index < len(steps) - 1 and walked + steps[index] < target:
            walked += steps[index]
            index += 1
        step = steps[index]
        t = 0.0 if step <= 0.0 else min(max((target - walked) / step, 0.0), 1.0)
        a, b = points[index], points[index + 1]
        result.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    result.append(points[-1])
    return result


def _median_of(values):
    values = sorted(values)
    count = len(values)
    if count == 0:
        return 0.0
    middle = count // 2
    return values[middle] if count % 2 else (values[middle - 1] + values[middle]) / 2.0


def _conic_ellipse(points):
    """Least squares ellipse (Fitzgibbon, Halir-Flusser): center, rx, ry, angle."""
    try:
        import numpy as np
    except ImportError:
        return None
    try:
        pts = np.asarray(points, dtype=float)
        mean = pts.mean(axis=0)
        scale = float(pts.std())
        if scale < 1.0e-9:
            return None
        q = (pts - mean) / scale
        x, y = q[:, 0], q[:, 1]
        d1 = np.column_stack((x * x, x * y, y * y))
        d2 = np.column_stack((x, y, np.ones_like(x)))
        s1, s2, s3 = d1.T @ d1, d1.T @ d2, d2.T @ d2
        t = -np.linalg.solve(s3, s2.T)
        m = s1 + s2 @ t
        m = np.array([m[2] / 2.0, -m[1], m[0] / 2.0])
        _values, vectors = np.linalg.eig(m)
        vectors = np.real(vectors)
        condition = 4.0 * vectors[0] * vectors[2] - vectors[1] ** 2
        found = np.where(condition > 0.0)[0]
        if len(found) == 0:
            return None
        a1 = vectors[:, found[0]]
        a, b, c = a1
        d, e, f = t @ a1
        den = b * b - 4.0 * a * c
        if den >= 0.0:
            return None
        x0 = (2.0 * c * d - b * e) / den
        y0 = (2.0 * a * e - b * d) / den
        value = a * x0 * x0 + b * x0 * y0 + c * y0 * y0 + d * x0 + e * y0 + f
        lams, axes = np.linalg.eigh(np.array([[a, b / 2.0], [b / 2.0, c]]))
        squares = -value / lams
        if np.any(squares <= 0.0):
            return None
        radii = np.sqrt(squares) * scale
        major = int(np.argmax(radii))
        angle = math.atan2(float(axes[1, major]), float(axes[0, major]))
        center = (float(x0 * scale + mean[0]), float(y0 * scale + mean[1]))
        return center, float(radii[major]), float(radii[1 - major]), angle
    except (ValueError, ArithmeticError, np.linalg.LinAlgError):
        return None


def _ellipse_error(points, center, rx, ry, angle):
    u = (math.cos(angle), math.sin(angle))
    v = (-u[1], u[0])
    total = 0.0
    for p in points:
        dx, dy = p[0] - center[0], p[1] - center[1]
        x, y = dx * u[0] + dy * u[1], dx * v[0] + dy * v[1]
        total += abs(math.hypot(x / rx, y / ry) - 1.0)
    return total / float(len(points)) * (rx + ry) / 2.0


def fit_ellipse(points):
    """Best ellipse for a closed path: (shape, mean distance)."""
    pts = resample_path(points)
    n = float(len(pts))
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts) / n
    syy = sum((p[1] - my) ** 2 for p in pts) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts) / n
    pca_angle = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    center, ra, rb, _local = _local_frame(pts, pca_angle)
    fits = []
    if min(ra, rb) >= 1.0:
        fits.append((center, ra, rb, pca_angle))
    conic = _conic_ellipse(pts)
    diagonal = _bbox_diagonal(pts)
    if conic is not None and min(conic[1], conic[2]) >= 1.0 and max(conic[1], conic[2]) <= diagonal:
        fits.append(conic)
    if not fits:
        return None, float("inf")
    scored = [(_ellipse_error(pts, *fit), fit) for fit in fits]
    error, (center, rx, ry, angle) = min(scored, key=lambda item: item[0])
    # Where the stroke started, as the ellipse's own parameter: the shape
    # starts there instead of on its axis.
    u = (math.cos(angle), math.sin(angle))
    dx, dy = points[0][0] - center[0], points[0][1] - center[1]
    phase = math.atan2((dx * -u[1] + dy * u[0]) / ry, (dx * u[0] + dy * u[1]) / rx)
    shape = {
        "kind": ELLIPSE, "center": center, "rx": rx, "ry": ry, "angle": angle,
        "ccw": _signed_area(pts) >= 0.0, "phase": phase,
    }
    return shape, error


def fit_rect(points):
    """Best rectangle for a closed path: (shape, mean distance)."""
    pts = resample_path(points)
    sx = sy = 0.0
    for i in range(len(pts) - 1):
        dx, dy = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
        length = math.hypot(dx, dy)
        if length > 0.0:
            # Four times the angle: edges at 90 degrees vote for the same axis.
            a = 4.0 * math.atan2(dy, dx)
            sx += math.cos(a) * length
            sy += math.sin(a) * length
    angle = math.atan2(sy, sx) / 4.0
    center, hw, hh, local = _local_frame(pts, angle)
    if min(hw, hh) < 1.0:
        return None, float("inf")
    u = (math.cos(angle), math.sin(angle))
    v = (-u[1], u[0])
    # Each side where most of its points are (the median), not at the
    # farthest point: overshoots at the corners and where the stroke closes
    # do not push the sides out.
    for _round in range(2):
        sides = ([], [], [], [])
        for x, y in local:
            gaps = (abs(x - hw), abs(x + hw), abs(y - hh), abs(y + hh))
            side = gaps.index(min(gaps))
            sides[side].append(x if side < 2 else y)
        if any(len(side) < 2 for side in sides):
            break
        right, left, top, bottom = (_median_of(side) for side in sides)
        if right - left < 2.0 or top - bottom < 2.0:
            break
        ox, oy = (right + left) / 2.0, (top + bottom) / 2.0
        hw, hh = (right - left) / 2.0, (top - bottom) / 2.0
        center = (center[0] + u[0] * ox + v[0] * oy, center[1] + u[1] * ox + v[1] * oy)
        local = [(x - ox, y - oy) for x, y in local]
    error = 0.0
    for x, y in local:
        dx, dy = abs(x) - hw, abs(y) - hh
        if dx > 0.0 or dy > 0.0:
            error += math.hypot(max(dx, 0.0), max(dy, 0.0))
        else:
            error += -max(dx, dy)
    error /= float(len(local))
    # The corner nearest to where the stroke started comes first.
    dx, dy = points[0][0] - center[0], points[0][1] - center[1]
    corner = (
        1.0 if dx * u[0] + dy * u[1] >= 0.0 else -1.0,
        1.0 if dx * v[0] + dy * v[1] >= 0.0 else -1.0,
    )
    shape = {
        "kind": RECT, "center": center, "rx": hw, "ry": hh, "angle": angle,
        "ccw": _signed_area(pts) >= 0.0, "corner": corner,
    }
    return shape, error


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


def _bulge_circle(start, end, bulge):
    """Center and radius of the circle through start and end whose arc
    between them bulges ``bulge`` pixels to the left of start->end."""
    half = _dist(start, end) / 2.0
    nx, ny = -(end[1] - start[1]) / (2.0 * half), (end[0] - start[0]) / (2.0 * half)
    signed_radius = (half * half + bulge * bulge) / (2.0 * bulge)
    offset = bulge - signed_radius
    middle = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    return (middle[0] + nx * offset, middle[1] + ny * offset), abs(signed_radius)


def _arc_error(points, start, end, bulge):
    center, radius = _bulge_circle(start, end, bulge)
    return sum(abs(_dist(center, p) - radius) for p in points) / float(len(points))


def _ellipse_param(shape, point):
    """Parameter of ``point`` on an ellipse or elliptical arc."""
    u = (math.cos(shape["angle"]), math.sin(shape["angle"]))
    dx, dy = point[0] - shape["center"][0], point[1] - shape["center"][1]
    return math.atan2((dx * -u[1] + dy * u[0]) / shape["ry"], (dx * u[0] + dy * u[1]) / shape["rx"])


def _arc_moves_forward(shape, points):
    """Every point moves forward along the arc (no back and forth), and the
    path stays within the arc's ends."""
    sweep = abs(shape["sweep"])
    turn = 1.0 if shape["sweep"] >= 0.0 else -1.0
    t0 = shape["t0"]
    previous = 0.0
    for p in points[1:]:
        current = ((_ellipse_param(shape, p) - t0) * turn + 0.6) % (2.0 * math.pi) - 0.6
        if current > sweep + 0.4 or current + 0.4 < previous:
            return False
        previous = max(previous, current)
    return True


def fit_circle_arc(points):
    """Circular arc from the start to the end of an open path.

    Returns (shape, mean distance, bulge in pixels) or (None, inf, 0). The
    arc goes exactly through both ends; its bulge is the one that best
    follows the whole stroke, in either drawing direction.
    """
    failed = (None, float("inf"), 0.0)
    if len(points) < 5:
        return failed
    start, end = points[0], points[-1]
    chord = _dist(start, end)
    if chord < MIN_SHAPE_PX:
        return failed
    pts = resample_path(points, 64)
    nx, ny = -(end[1] - start[1]) / chord, (end[0] - start[0]) / chord
    # The bulge where half the stroke's length is, then refined.
    middle = _point_at_length(pts, _path_length(pts) / 2.0)
    guess = (middle[0] - start[0]) * nx + (middle[1] - start[1]) * ny
    if abs(guess) < 0.5:
        return failed
    sign = 1.0 if guess > 0.0 else -1.0
    low, high = abs(guess) * 0.4, max(abs(guess) * 2.5, abs(guess) + 2.0)
    samples = [low * (high / low) ** (i / 24.0) for i in range(25)]
    errors = [_arc_error(pts, start, end, sign * h) for h in samples]
    best = errors.index(min(errors))
    a, b = samples[max(best - 1, 0)], samples[min(best + 1, len(samples) - 1)]
    for _step in range(24):
        m1, m2 = a + (b - a) * 0.382, a + (b - a) * 0.618
        if _arc_error(pts, start, end, sign * m1) <= _arc_error(pts, start, end, sign * m2):
            b = m2
        else:
            a = m1
    bulge = sign * (a + b) / 2.0
    center, radius = _bulge_circle(start, end, bulge)
    error = _arc_error(pts, start, end, bulge)
    if error > ARC_FIT_RATIO * min(radius, chord):
        return failed
    # Sagitta and half chord give the swept angle directly: no wrapping.
    sweep = 4.0 * math.atan(abs(bulge) / (chord / 2.0))
    if sweep > ARC_MAX_SWEEP:
        return failed
    # Bulging to the right of start->end means turning left (counterclockwise).
    turn = 1.0 if bulge < 0.0 else -1.0
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    shape = {
        "kind": ARC, "center": center, "rx": radius, "ry": radius, "angle": 0.0,
        "t0": a0, "sweep": sweep * turn,
    }
    if not _arc_moves_forward(shape, pts):
        return failed
    return shape, error, abs(bulge)


def fit_ellipse_arc(points):
    """Arc of an ellipse along an open path: (shape, mean distance) or (None, inf).

    For arcs a circle cannot follow: deep U shapes, flattened or stretched
    curves. The arc ends where the stroke's ends fall on the ellipse.
    """
    failed = (None, float("inf"))
    if len(points) < 8 or _dist(points[0], points[-1]) < MIN_SHAPE_PX:
        return failed
    pts = resample_path(points)
    conic = _conic_ellipse(pts)
    if conic is None:
        return failed
    center, rx, ry, angle = conic
    diagonal = _bbox_diagonal(pts)
    # Nearly straight strokes fit huge, thin ellipses: not an arc.
    if min(rx, ry) < MIN_SHAPE_PX / 2.0 or max(rx, ry) > 1.5 * diagonal or max(rx, ry) > 6.0 * min(rx, ry):
        return failed
    shape = {"kind": ARC, "center": center, "rx": rx, "ry": ry, "angle": angle, "t0": 0.0, "sweep": 0.0}
    params = [_ellipse_param(shape, p) for p in pts]
    unwrapped = [params[0]]
    for value in params[1:]:
        delta = (value - unwrapped[-1] + math.pi) % (2.0 * math.pi) - math.pi
        unwrapped.append(unwrapped[-1] + delta)
    sweep = unwrapped[-1] - unwrapped[0]
    if not math.radians(20.0) <= abs(sweep) <= ARC_MAX_SWEEP:
        return failed
    shape["t0"], shape["sweep"] = unwrapped[0], sweep
    if not _arc_moves_forward(shape, pts):
        return failed
    error = _ellipse_error(pts, center, rx, ry, angle)
    if error > ELLIPSE_ARC_FIT_RATIO * math.sqrt(rx * ry):
        return failed
    return shape, error


def fit_arc(points):
    """Best arc (circular, or elliptical when a circle cannot follow).

    Returns (shape, mean distance, bulge in pixels) or (None, inf, 0).
    """
    circle, circle_error, bulge = fit_circle_arc(points)
    ellipse, ellipse_error = fit_ellipse_arc(points)
    if ellipse is not None and (
        circle is None
        or (ellipse_error < 0.6 * circle_error and max(ellipse["rx"], ellipse["ry"]) > 1.15 * min(ellipse["rx"], ellipse["ry"]))
    ):
        start, end = points[0], points[-1]
        chord = max(_dist(start, end), 1.0e-6)
        middle = _arc_point(ellipse, 0.5)
        bulge = abs((middle[0] - start[0]) * -(end[1] - start[1]) + (middle[1] - start[1]) * (end[0] - start[0])) / chord
        return ellipse, ellipse_error, bulge
    return circle, circle_error, bulge


def _line_error(points):
    start, end = points[0], points[-1]
    chord = _dist(start, end)
    if chord <= 0.0:
        return float("inf")
    dx, dy = (end[0] - start[0]) / chord, (end[1] - start[1]) / chord
    pts = resample_path(points, 64)
    return sum(abs((p[0] - start[0]) * dy - (p[1] - start[1]) * dx) for p in pts) / float(len(pts))


# -- polylines and polygons --------------------------------------------------

POLY_MIN_TURN = math.radians(35.0)
# Only clear polylines: every part of the stroke close to its segment
# (mean and worst distance, as a share of the stroke's size), segments of a
# fair length and not too many corners. Anything else stays free hand.
POLY_FIT_RATIO = 0.012
POLY_MAX_RATIO = 0.035
POLY_MIN_SEGMENT_RATIO = 0.08
POLY_MAX_CORNERS = 10


def _rdp(points, first, last, tolerance, keep):
    a, b = points[first], points[last]
    length = _dist(a, b)
    worst, index = 0.0, None
    for i in range(first + 1, last):
        p = points[i]
        if length > 0.0:
            d = abs((p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])) / length
        else:
            d = _dist(p, a)
        if d > worst:
            worst, index = d, i
    if index is not None and worst > tolerance:
        _rdp(points, first, index, tolerance, keep)
        keep.append(index)
        _rdp(points, index, last, tolerance, keep)


def _turn(a, b, c):
    """Change of direction at b, in radians (0 = straight on)."""
    d1 = math.atan2(b[1] - a[1], b[0] - a[0])
    d2 = math.atan2(c[1] - b[1], c[0] - b[0])
    return abs((d2 - d1 + math.pi) % (2.0 * math.pi) - math.pi)


def _fit_line(points):
    """(point, unit direction) of the best line through points."""
    n = float(len(points))
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    syy = sum((p[1] - my) ** 2 for p in points)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in points)
    angle = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    return (mx, my), (math.cos(angle), math.sin(angle))


def _intersect(line_a, line_b):
    (p, d), (q, e) = line_a, line_b
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 0.15:  # nearly parallel
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return (p[0] + d[0] * t, p[1] + d[1] * t)


def _project(line, point):
    (p, d) = line
    t = (point[0] - p[0]) * d[0] + (point[1] - p[1]) * d[1]
    return (p[0] + d[0] * t, p[1] + d[1] * t)


def _segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 <= 0.0 else min(max(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2, 0.0), 1.0)
    return math.hypot(p[0] - a[0] - dx * t, p[1] - a[1] - dy * t)


def _outline_error(points, vertices, cyclic):
    segments = list(zip(vertices, vertices[1:] + (vertices[:1] if cyclic else [])))
    return sum(min(_segment_distance(p, a, b) for a, b in segments) for p in points) / float(len(points))


def fit_polyline(points, cyclic=False):
    """Straight segments with a point only where the direction changes.

    Returns (shape, mean distance) or (None, inf). Corners are where the
    lines fitted to neighbouring segments cross, so they are sharp even
    when the drawn corner is rounded.
    """
    failed = (None, float("inf"))
    pts = resample_path(points, 160)
    if len(pts) < 8:
        return failed
    diagonal = _bbox_diagonal(pts)
    if diagonal < MIN_SHAPE_PX:
        return failed
    tolerance = max(4.0, diagonal * 0.035)
    if cyclic:
        pts = pts[:-1] if _dist(pts[0], pts[-1]) < 1.0e-6 else pts
        far = max(range(len(pts)), key=lambda i: _dist(pts[0], pts[i]))
        keep = [0]
        _rdp(pts, 0, far, tolerance, keep)
        keep.append(far)
        _rdp(pts + [pts[0]], far, len(pts), tolerance, keep)
        corners = sorted(set(i % len(pts) for i in keep))
    else:
        keep = [0]
        _rdp(pts, 0, len(pts) - 1, tolerance, keep)
        keep.append(len(pts) - 1)
        corners = sorted(set(keep))
    # Drop corners where the direction hardly changes.
    while True:
        count = len(corners)
        candidates = range(count) if cyclic else range(1, count - 1)
        turns = [
            (_turn(pts[corners[i - 1]], pts[corners[i]], pts[corners[(i + 1) % count]]), i)
            for i in candidates
        ]
        if not turns:
            break
        smallest, index = min(turns)
        if smallest >= POLY_MIN_TURN or count <= (3 if cyclic else 2):
            break
        corners.pop(index)
    if not 3 <= len(corners) <= POLY_MAX_CORNERS:
        return failed
    count = len(corners)
    spans = [(corners[i], corners[i + 1]) for i in range(count - 1)]
    if cyclic:
        spans.append((corners[-1], corners[0] + len(pts)))
    ring = pts + pts if cyclic else pts
    lines = []
    for a, b in spans:
        segment = ring[a:b + 1]
        if _path_length(segment) < max(15.0, diagonal * POLY_MIN_SEGMENT_RATIO):
            return failed
        # The middle of each segment: drawn corners are often rounded.
        trim = len(segment) // 6
        lines.append(_fit_line(segment[trim:len(segment) - trim] if len(segment) - 2 * trim >= 2 else segment))
    vertices = []
    if cyclic:
        for i in range(count):
            corner = _intersect(lines[i - 1], lines[i])
            vertices.append(corner if corner is not None else pts[corners[i]])
    else:
        vertices.append(_project(lines[0], pts[0]))
        for i in range(1, count - 1):
            corner = _intersect(lines[i - 1], lines[i])
            vertices.append(corner if corner is not None else pts[corners[i]])
        vertices.append(_project(lines[-1], pts[-1]))
    # Sharp corners only: the stroke must reach each corner. A rounded
    # bend (a U, an arc) leaves the crossing of its lines far away.
    reach = max(6.0, diagonal * 0.04)
    for corner in (vertices if cyclic else vertices[1:-1]):
        if min(_dist(corner, p) for p in pts) > reach:
            return failed
    segments = list(zip(vertices, vertices[1:] + (vertices[:1] if cyclic else [])))
    distances = [min(_segment_distance(p, a, b) for a, b in segments) for p in pts]
    error = sum(distances) / float(len(distances))
    if error > max(1.5, POLY_FIT_RATIO * diagonal) or max(distances) > max(5.0, POLY_MAX_RATIO * diagonal):
        return failed
    shape = {"kind": POLYGON if cyclic else POLYLINE, "vertices": vertices}
    return shape, error


# A line that is this much curved (share of its length, and pixels) also
# offers the arc, and the other way round.
ARC_CHOICE_RATIO = 0.02
ARC_CHOICE_MIN_PX = 3.0
# An arc comes first only when it bulges at least this share of its chord:
# hand-drawn lines are often slightly bowed.
ARC_FIRST_RATIO = 0.08
# Lines that pass this looser test still offer the line next to an arc.
LOOSE_STRAIGHT_RATIO = 0.2


def recognize_shapes(points):
    """Shapes a screen path could be, most likely first (empty: free hand).

    When the stroke is between two shapes (line or arc, arc or polyline,
    ellipse or rectangle...), both are returned and the Quick Shape panel
    offers them.
    """
    if len(points) < 2:
        return []
    straight = is_straight_path(points)
    diagonal = max(_bbox_diagonal(points), 1.0)
    if not straight and is_closed_path(points):
        fits = []
        for shape, error in (fit_ellipse(points), fit_rect(points)):
            if shape is not None and error <= CLOSED_FIT_RATIO * (shape["rx"] + shape["ry"]):
                fits.append((error / diagonal, shape))
        polygon, polygon_error = fit_polyline(points, cyclic=True)
        if polygon is not None:
            # More freedom than a rectangle: it must fit clearly better.
            fits.append((2.0 * polygon_error / diagonal + 0.004, polygon))
        fits.sort(key=lambda item: item[0])
        return [shape for _score, shape in fits]
    line = {"kind": LINE, "start": points[0], "end": points[-1]}
    chord = _dist(points[0], points[-1])
    arc, arc_error, bulge = fit_arc(points)
    if arc is not None and bulge < max(ARC_CHOICE_MIN_PX, chord * ARC_CHOICE_RATIO):
        arc = None
    if straight:
        if arc is None:
            return [line]
        # Clearly bowed and the arc follows it much better: the arc first.
        if bulge >= chord * ARC_FIRST_RATIO and arc_error < 0.35 * _line_error(points):
            return [arc, line]
        return [line, arc]
    polyline, polyline_error = fit_polyline(points)
    loose = is_straight_path(points, LOOSE_STRAIGHT_RATIO)
    result = []
    if arc is not None:
        if loose and bulge < chord * ARC_FIRST_RATIO:
            result = [line, arc]
        else:
            result = [arc, line] if loose else [arc]
    if polyline is not None:
        # Polylines can follow curves too, with many corners: an arc that
        # fits wins unless the polyline is far closer.
        if arc is None or 3.0 * polyline_error < arc_error:
            result.insert(0, polyline)
        else:
            result.append(polyline)
    return result


def recognize_shape(points):
    """Most likely shape for a screen path, or None."""
    shapes = recognize_shapes(points)
    return shapes[0] if shapes else None


def shape_anchor(shape):
    """Point the shape turns and scales around while the cursor moves."""
    kind = shape["kind"]
    if kind == LINE:
        return shape["start"]
    if kind == ARC:
        return _arc_point(shape, 0.0)
    if kind == POLYLINE:
        return shape["vertices"][0]
    if kind == POLYGON:
        vertices = shape["vertices"]
        return (sum(v[0] for v in vertices) / len(vertices), sum(v[1] for v in vertices) / len(vertices))
    return shape["center"]


def _ellipse_at(shape, t):
    c, rx, ry = shape["center"], shape["rx"], shape["ry"]
    u = (math.cos(shape["angle"]), math.sin(shape["angle"]))
    x, y = rx * math.cos(t), ry * math.sin(t)
    return (c[0] + u[0] * x - u[1] * y, c[1] + u[1] * x + u[0] * y)


def _arc_point(shape, fraction):
    return _ellipse_at(shape, shape["t0"] + shape["sweep"] * fraction)


def _circle_arc_through(start, middle, end):
    """Circular arc from start through middle to end, or None if straight."""
    d = 2.0 * (start[0] * (middle[1] - end[1]) + middle[0] * (end[1] - start[1]) + end[0] * (start[1] - middle[1]))
    if abs(d) < 1.0e-9:
        return None
    s2 = start[0] ** 2 + start[1] ** 2
    m2 = middle[0] ** 2 + middle[1] ** 2
    e2 = end[0] ** 2 + end[1] ** 2
    center = (
        (s2 * (middle[1] - end[1]) + m2 * (end[1] - start[1]) + e2 * (start[1] - middle[1])) / d,
        (s2 * (end[0] - middle[0]) + m2 * (start[0] - end[0]) + e2 * (middle[0] - start[0])) / d,
    )
    radius = _dist(center, start)
    cross = (middle[0] - start[0]) * (end[1] - middle[1]) - (middle[1] - start[1]) * (end[0] - middle[0])
    turn = 1.0 if cross > 0.0 else -1.0
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    sweep = ((a1 - a0) * turn) % (2.0 * math.pi)
    return {
        "kind": ARC, "center": center, "rx": radius, "ry": radius, "angle": 0.0,
        "t0": a0, "sweep": sweep * turn,
    }


def transform_shape(shape, angle, scale, snap_degrees=0.0):
    """Shape turned by ``angle`` and scaled around its anchor.

    With ``snap_degrees`` (Ctrl) lines and arcs snap the start-to-end
    direction, polylines each segment, ellipses become circles and
    rectangles squares, and both snap their rotation.
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
    if kind in (POLYLINE, POLYGON):
        vertices = [move(v) for v in shape["vertices"]]
        if step and kind == POLYLINE:
            snapped = [vertices[0]]
            for a, b in zip(vertices, vertices[1:]):
                end = snap_screen_angle(a, b, snap_degrees)
                last = snapped[-1]
                snapped.append((last[0] + end[0] - a[0], last[1] + end[1] - a[1]))
            vertices = snapped
        elif step:
            a, b = vertices[0], vertices[1]
            edge = math.atan2(b[1] - a[1], b[0] - a[0])
            correction = round(edge / step) * step - edge
            vertices = [
                (anchor[0] + r[0], anchor[1] + r[1])
                for r in (_rotate((v[0] - anchor[0], v[1] - anchor[1]), correction) for v in vertices)
            ]
        return {"kind": kind, "vertices": vertices}
    result = dict(shape)
    result["center"] = move(shape["center"])
    result["rx"] = shape["rx"] * scale
    result["ry"] = shape["ry"] * scale
    result["angle"] = shape["angle"] + angle
    if kind == ARC:
        if step and abs(result["rx"] - result["ry"]) > 1.0e-6:
            # Ctrl: an elliptical arc becomes the circular arc through its
            # start, middle and end.
            circle = _circle_arc_through(
                _arc_point(result, 0.0), _arc_point(result, 0.5), _arc_point(result, 1.0),
            )
            if circle is not None:
                result = circle
        if step:
            end = _arc_point(result, 1.0)
            chord = math.atan2(end[1] - anchor[1], end[0] - anchor[0])
            correction = round(chord / step) * step - chord
            offset = _rotate((result["center"][0] - anchor[0], result["center"][1] - anchor[1]), correction)
            result["center"] = (anchor[0] + offset[0], anchor[1] + offset[1])
            result["angle"] += correction
        return result
    if step:
        size = (result["rx"] + result["ry"]) / 2.0
        result["rx"] = result["ry"] = size
        result["angle"] = round(result["angle"] / step) * step
    return result


DEFAULT_POINTS = {LINE: 2, ARC: 3, ELLIPSE: 24, RECT: 4}
_MIN_POINTS = {LINE: 2, ARC: 3, ELLIPSE: 3, RECT: 4}
MAX_POINTS = 256
DEFAULT_CURVE_TYPE = {
    LINE: "POLY", ARC: "BEZIER", ELLIPSE: "POLY", RECT: "POLY", POLYLINE: "POLY", POLYGON: "POLY",
}
SHAPE_LABELS = {
    LINE: "Line", ARC: "Arc", ELLIPSE: "Ellipse", RECT: "Rectangle", POLYLINE: "Polyline", POLYGON: "Polygon",
}


def _segment_count(shape):
    vertices = len(shape.get("vertices") or ())
    return vertices if shape["kind"] == POLYGON else max(vertices - 1, 1)


def default_points(shape):
    """Points of a shape before the wheel or the panel change them."""
    kind = shape["kind"]
    if kind in (POLYLINE, POLYGON):
        return len(shape["vertices"])
    if kind == ARC and abs(shape["sweep"]) > math.radians(200.0):
        # The ends have no handles: wide arcs need more points to stay round.
        return 5
    return DEFAULT_POINTS[kind]


def points_step(kind, shape=None):
    """Mouse wheel step for the number of points (one per side or segment)."""
    if kind in (POLYLINE, POLYGON) and shape is not None:
        return _segment_count(shape)
    return 4 if kind == RECT else 1


def clamp_points(kind, count, shape=None):
    if kind in (POLYLINE, POLYGON) and shape is not None:
        segments = _segment_count(shape)
        closing = 0 if kind == POLYGON else 1
        per_segment = max(1, min(MAX_POINTS // segments, int(round((int(count) - closing) / float(segments)))))
        return segments * per_segment + closing
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


def _ellipse_distance(shape, point):
    u = (math.cos(shape["angle"]), math.sin(shape["angle"]))
    dx, dy = point[0] - shape["center"][0], point[1] - shape["center"][1]
    x, y = dx * u[0] + dy * u[1], -dx * u[1] + dy * u[0]
    return abs(math.hypot(x / shape["rx"], y / shape["ry"]) - 1.0) * (shape["rx"] + shape["ry"]) / 2.0


def _fit_end_handle(shape, end, point, handle, from_end):
    """Handle of ``point`` facing an arc end that has no handle, with the
    length that keeps the Bezier segment closest to the arc."""
    direction = (handle[0] - point[0], handle[1] - point[1])
    length = math.hypot(*direction)
    if length <= 1.0e-9:
        return handle
    direction = (direction[0] / length, direction[1] / length)

    def worst(scale):
        h = (point[0] + direction[0] * length * scale, point[1] + direction[1] * length * scale)
        controls = (end, end, h, point) if from_end else (point, h, end, end)
        return max(_ellipse_distance(shape, _bezier(*controls, k / 16.0)) for k in range(1, 16))

    low, high = 0.3, 2.5
    for _step in range(30):
        m1, m2 = low + (high - low) * 0.382, low + (high - low) * 0.618
        if worst(m1) <= worst(m2):
            high = m2
        else:
            low = m1
    scale = (low + high) / 2.0
    return (point[0] + direction[0] * length * scale, point[1] + direction[1] * length * scale)


def shape_knots(shape, count=None):
    """Control points of a shape.

    Returns ([(left handle, point, right handle)], cyclic, handle types):
    handle types are (left, right) per point. Ellipses and arcs have aligned
    handles, except the two ends of an arc, which have none; lines and
    rectangles have sharp corners.
    """
    kind = shape["kind"]
    count = clamp_points(kind, default_points(shape) if count is None else count, shape)
    free = [(_HANDLE_FREE, _HANDLE_FREE)] * count
    if kind == LINE:
        s, e = shape["start"], shape["end"]
        points = [
            (s[0] + (e[0] - s[0]) * i / (count - 1), s[1] + (e[1] - s[1]) * i / (count - 1))
            for i in range(count)
        ]
        return _polyline_knots(points, False), False, free
    if kind in (POLYLINE, POLYGON):
        cyclic = kind == POLYGON
        vertices = [tuple(v) for v in shape["vertices"]]
        ends = vertices + vertices[:1] if cyclic else vertices
        per_segment = (count - (0 if cyclic else 1)) // _segment_count(shape)
        points = []
        for a, b in zip(ends, ends[1:]):
            for i in range(per_segment):
                t = i / per_segment
                points.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        if not cyclic:
            points.append(vertices[-1])
        return _polyline_knots(points, cyclic), cyclic, [(_HANDLE_FREE, _HANDLE_FREE)] * len(points)
    if kind == ARC:
        u = (math.cos(shape["angle"]), math.sin(shape["angle"]))
        step = shape["sweep"] / (count - 1)
        handle = 4.0 / 3.0 * math.tan(step / 4.0)
        knots = []
        for i in range(count):
            t = shape["t0"] + step * i
            p = _ellipse_at(shape, t)
            # Derivative of the ellipse at t, scaled for a Bezier segment.
            dx, dy = -shape["rx"] * math.sin(t) * handle, shape["ry"] * math.cos(t) * handle
            d = (u[0] * dx - u[1] * dy, u[1] * dx + u[0] * dy)
            knots.append(((p[0] - d[0], p[1] - d[1]), p, (p[0] + d[0], p[1] + d[1])))
        # The ends have no handles. The inner handle next to each end is
        # lengthened or shortened so the segment still follows the arc.
        for end, near, side in ((0, 1, 0), (count - 1, count - 2, 2)):
            p = knots[end][1]
            knots[end] = (p, p, p)
            left, point, right = knots[near]
            handle = left if side == 0 else right
            fitted = _fit_end_handle(shape, p, point, handle, from_end=(end == 0))
            knots[near] = (fitted, point, right) if side == 0 else (left, point, fitted)
        types = [(_HANDLE_ALIGN, _HANDLE_ALIGN)] * count
        types[0] = types[-1] = (_HANDLE_FREE, _HANDLE_FREE)
        return knots, False, types
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
        first = tuple(int(round(value)) for value in shape.get("corner", (-1, -1)))
        if first in corners:
            index = corners.index(first)
            corners = corners[index:] + corners[:index]
        corners = [at(sx * rx, sy * ry) for sx, sy in corners]
        per_side = count // 4
        points = []
        for j in range(4):
            a, b = corners[j], corners[(j + 1) % 4]
            for i in range(per_side):
                t = i / per_side
                points.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        return _polyline_knots(points, True), True, free
    step = 2.0 * math.pi / count
    handle = 4.0 / 3.0 * math.tan(step / 4.0)
    phase = float(shape.get("phase", 0.0))
    knots = []
    for i in range(count):
        t = phase + turn * i * step
        p = at(rx * math.cos(t), ry * math.sin(t))
        d = (-rx * math.sin(t) * turn * handle, ry * math.cos(t) * turn * handle)
        d = (u[0] * d[0] + v[0] * d[1], u[1] * d[0] + v[1] * d[1])
        knots.append(((p[0] - d[0], p[1] - d[1]), p, (p[0] + d[0], p[1] + d[1])))
    return knots, True, [(_HANDLE_ALIGN, _HANDLE_ALIGN)] * count


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


def write_shape_stroke(drawing, index, knots, cyclic, handle_types, curve_type, radius=None, opacity=None):
    """Replace stroke ``index`` by a new stroke with exactly ``knots``.

    ``knots`` are (left, point, right) in layer space, ``handle_types`` a
    (left, right) handle type per knot, or True for aligned handles
    everywhere and False for free ones. The new stroke keeps
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
        if isinstance(handle_types, bool):
            handle_type = _HANDLE_ALIGN if handle_types else _HANDLE_FREE
            handle_types = [(handle_type, handle_type)] * len(knots)
        lefts = attributes["handle_left"].data
        rights = attributes["handle_right"].data
        left_types = attributes["handle_type_left"].data
        right_types = attributes["handle_type_right"].data
        for offset, ((left, _point, right), (left_type, right_type)) in enumerate(zip(knots, handle_types)):
            lefts[first + offset].vector = left
            rights[first + offset].vector = right
            left_types[first + offset].value = left_type
            right_types[first + offset].value = right_type
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
    for key in ("start", "end", "center", "corner"):
        if key in shape:
            shape[key] = tuple(shape[key])
    if "vertices" in shape:
        shape["vertices"] = [tuple(v) for v in shape["vertices"]]
    return shape


def _shapes_from_data(data):
    """All the shapes the stroke could be, most likely first."""
    shapes = [_shape_from_data({"shape": shape}) for shape in data.get("shapes") or ()]
    return shapes or [_shape_from_data(data)]


KIND_ITEMS = (
    (LINE, "Line", "Straight line"),
    (ARC, "Arc", "Circular arc"),
    (ELLIPSE, "Ellipse", "Ellipse or circle"),
    (RECT, "Rectangle", "Rectangle or square"),
    (POLYLINE, "Polyline", "Straight segments with a point at each change of direction"),
    (POLYGON, "Polygon", "Closed shape of straight sides"),
)

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
    kind: EnumProperty(
        name="Shape",
        description="Shape the stroke becomes, when it could be more than one",
        items=KIND_ITEMS,
        default=LINE,
    )
    # Shape the points and curve type were last set for: switching shape
    # starts from the new shape's own defaults.
    last_kind: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    data: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def draw(self, _context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        try:
            kinds = [shape["kind"] for shape in _shapes_from_data(json.loads(self.data))]
        except (ValueError, KeyError, TypeError):
            kinds = []
        kinds = [kind for kind in kinds if kind in SHAPE_LABELS]
        if len(kinds) > 1:
            split = layout.split(factor=0.4)
            label = split.row()
            label.alignment = "RIGHT"
            label.label(text="Shape")
            row = split.row(align=True)
            row.use_property_split = False
            for kind in kinds:
                row.prop_enum(self, "kind", kind)
        elif kinds:
            layout.label(text=SHAPE_LABELS[kinds[0]], icon="GREASEPENCIL")
        layout.prop(self, "points")
        layout.prop(self, "curve_type")

    def execute(self, _context):
        try:
            data = json.loads(self.data)
            shapes = {shape["kind"]: shape for shape in _shapes_from_data(data)}
            kind = self.kind if self.kind in shapes else _shapes_from_data(data)[0]["kind"]
            if self.kind != kind:
                self.kind = kind
            if self.last_kind != kind:
                if self.last_kind:
                    self.points = default_points(shapes[kind])
                    self.curve_type = DEFAULT_CURVE_TYPE[kind]
                self.last_kind = kind
            shape = shapes[kind]
            drawing = _find_drawing(data)
            index = int(data["index"])
            if drawing is None or len(drawing.strokes) != int(data["count"]) or index >= len(drawing.strokes):
                return {"CANCELLED"}
            points = clamp_points(shape["kind"], self.points, shape)
            if points != self.points:
                self.points = points
            knots, cyclic, handle_types = shape_knots(shape, points)
            mapping = data["mapping"]
            located = []
            for triple in knots:
                located.append(tuple(map_point(mapping, p) for p in triple))
                if any(p is None for p in located[-1]):
                    return {"CANCELLED"}
            write_shape_stroke(
                drawing, index, located, cyclic, handle_types, self.curve_type,
                data.get("radius"), data.get("opacity"),
            )
        except (ValueError, KeyError, TypeError, *FBP_DATA_IO_ERRORS) as exc:
            fbp_warn_once("gp_quick_shape.apply", "Quick Shape could not rebuild the stroke", exc)
            return {"CANCELLED"}
        return {"FINISHED"}


def _brush_running(window):
    try:
        return any(
            str(getattr(op, "bl_idname", "") or "") == _BRUSH_STROKE_ID
            for op in window.modal_operators
        )
    except FBP_DATA_ERRORS:
        return False


def _placement_normal(context, rv3d, world_points):
    """Normal of the plane the stroke was drawn on, in world space."""
    view_normal = (rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))).normalized()
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


class _StrokeWatcher:
    """Watches a stroke the native brush is drawing, from an app timer.

    The brush is started by Blender's own shortcut with the real input
    event (so the pen pressure of the first point is right); the watcher
    only reads the stroke. When its end rests, it starts the Quick Shape
    follow operator, which then takes the cursor over until release.
    """

    def __init__(self, context):
        _enabled, self.hold, self.snap, self.precision = quick_shape_settings(context)
        self.precision_key = quick_shape_precision_key(context)
        self.window = context.window
        self.area = context.area
        self.region = context.region
        self.rv3d = context.region_data
        self.started = time.monotonic()
        self.rest_point = None
        self.rest_since = self.started
        self.point_count = -1
        self.seen_brush = False
        self.missing_since = None
        self.active = True
        _obj, _layer, drawing = _active_target(context)
        try:
            self.baseline = (
                int(drawing.as_pointer()) if drawing is not None else 0,
                len(drawing.strokes) if drawing is not None else 0,
            )
        except FBP_DATA_ERRORS:
            self.baseline = (0, 0)

    def stop(self):
        self.active = False
        global _WATCHER
        if _WATCHER is self:
            _WATCHER = None
        return None

    def stroke(self, context):
        """(object, layer, drawing, curve index, first, last) of the stroke being drawn."""
        obj, layer, drawing = _active_target(context)
        if drawing is None:
            return None
        count = len(drawing.strokes)
        pointer = int(drawing.as_pointer())
        if count == 0 or (pointer == self.baseline[0] and count != self.baseline[1] + 1):
            return None
        try:
            on_back = bool(context.scene.tool_settings.use_gpencil_draw_onback)
        except FBP_DATA_ERRORS:
            on_back = False
        index = 0 if on_back else count - 1
        first, last = _curve_point_range(drawing, index)
        return obj, layer, drawing, index, first, last

    def tick(self):
        if not self.active:
            return self.stop()
        try:
            return self._tick()
        except FBP_DATA_IO_ERRORS as exc:
            fbp_warn_once("gp_quick_shape.watch", "Quick Shape stopped", exc)
            return self.stop()

    def _tick(self):
        running = _brush_running(self.window)
        now = time.monotonic()
        if not running:
            # The brush may not have started yet on the first ticks, and the
            # window can briefly list no modal operator while it redraws:
            # stop only once the brush has been gone for a moment.
            if self.missing_since is None:
                self.missing_since = now
            if now - self.missing_since > (0.15 if self.seen_brush else 0.5):
                if self.seen_brush:
                    _repair_after_automerge(self.window)
                return self.stop()
            return TIMER_STEP_SECONDS
        self.missing_since = None
        self.seen_brush = True
        if now - self.started > DETECTION_WINDOW_SECONDS:
            # Past the detection window the stroke stays free hand.
            return self.stop()
        with bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            context = bpy.context
            found = self.stroke(context)
            if found is None:
                return TIMER_STEP_SECONDS
            obj, layer, drawing, _index, first, last = found
            if last - first < 2:
                return TIMER_STEP_SECONDS
            positions = drawing.attributes["position"].data
            end = view3d_utils.location_3d_to_region_2d(
                self.region, self.rv3d, _layer_to_world(obj, layer) @ Vector(positions[last - 1].vector)
            )
            if end is None:
                return TIMER_STEP_SECONDS
            end = (float(end.x), float(end.y))
            if self.rest_point is None or _dist(end, self.rest_point) > HOLD_TOLERANCE_PX:
                self.rest_point = end
                self.rest_since = now
            elif now - self.rest_since >= self.hold:
                self.rest_since = now
                try:
                    result = bpy.ops.fbp.gp_quick_shape_follow("INVOKE_DEFAULT")
                except RuntimeError:
                    result = {"CANCELLED"}
                if "RUNNING_MODAL" in result:
                    # The follow operator owns the stroke until release.
                    return self.stop()
                # No shape: wait for the stroke to go on and rest again.
        return TIMER_STEP_SECONDS


_WATCHER = None


class FBP_OT_GPQuickShapeStroke(Operator):
    """Draw with the brush; rest the pen at the end of a line, arc, ellipse, rectangle or polyline to turn it into a clean shape (wheel: points, Shift or Alt: precise, Ctrl: snap)"""

    bl_idname = "fbp.gp_quick_shape_stroke"
    bl_label = "Draw with Quick Shape"
    bl_options = {"INTERNAL"}

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

    def invoke(self, context, _event):
        # Start watching, then let the click go on to Blender's own brush
        # shortcut (plain or Shift), which starts the stroke with the real
        # input event.
        global _WATCHER
        if _WATCHER is not None:
            _WATCHER.stop()
        watcher = _StrokeWatcher(context)
        _WATCHER = watcher
        bpy.app.timers.register(watcher.tick, first_interval=TIMER_STEP_SECONDS)
        return {"PASS_THROUGH"}


class FBP_OT_GPQuickShapeFollow(Operator):
    """Quick Shape: the shape follows the cursor until release"""

    bl_idname = "fbp.gp_quick_shape_follow"
    bl_label = "Quick Shape"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        watcher = _WATCHER
        if watcher is None or not watcher.active:
            return {"CANCELLED"}
        self._watcher = watcher
        self._precision, self._snap = watcher.precision, watcher.snap
        self._precision_key = watcher.precision_key
        self._window, self._area, self._region, self._rv3d = (
            watcher.window, watcher.area, watcher.region, watcher.rv3d,
        )
        self._header = False
        self._automerge = None
        self._alternatives = []
        if not self._begin_shape(context, event):
            return {"CANCELLED"}
        # Automerge would join the shape's stroke to the stroke it starts or
        # ends at when the brush finishes, and the shape could not be
        # applied: it stays off until the shape is done.
        self._automerge = _suspend_automerge(context.scene)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _finish(self, _context):
        if getattr(self, "_automerge", None):
            # After the brush has finished (timers run after the events).
            scene_name = self._automerge
            bpy.app.timers.register(lambda: _resume_automerge(scene_name), first_interval=0.0)
            self._automerge = None
        if self._header:
            try:
                self._area.header_text_set(None)
            except FBP_DATA_ERRORS:
                pass
            self._header = False

    # -- events ------------------------------------------------------------

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except FBP_DATA_IO_ERRORS as exc:
            fbp_warn_once("gp_quick_shape.modal", "Quick Shape stopped", exc)
            self._finish(context)
            return {"FINISHED", "PASS_THROUGH"}

    def _modal(self, context, event):
        # The shape follows the cursor until release. Apart from the release
        # the brush gets no more events, so it neither extends the stroke
        # nor reacts to Shift.
        if event.type in {"LEFTMOUSE", "PEN"} and event.value == "RELEASE":
            self._update_shape(event, final=True)
            self._finish(context)
            return {"FINISHED", "PASS_THROUGH"}
        if not _brush_running(self._window):
            self._finish(context)
            return {"FINISHED", "PASS_THROUGH"}
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
            step = points_step(kind, self._shape) * (1 if event.type == "WHEELUPMOUSE" else -1)
            self._points = clamp_points(kind, self._points + step, self._shape)
            self._update_shape(event)
        elif event.type in _SHIFT_KEYS or event.type in _CTRL_KEYS:
            self._update_shape(event)
        elif event.type in {"ESC", "RIGHTMOUSE"}:
            # Let the brush cancel the stroke as usual.
            self._finish(context)
            return {"FINISHED", "PASS_THROUGH"}
        return {"RUNNING_MODAL"}

    # -- geometry ----------------------------------------------------------

    def _begin_shape(self, context, event):
        found = self._watcher.stroke(context)
        if found is None:
            return False
        obj, layer, drawing, curve_index, first, last = found
        if last - first < 2:
            return False
        positions = drawing.attributes["position"].data
        to_world = _layer_to_world(obj, layer)
        self._original = [Vector(positions[i].vector) for i in range(first, last)]
        world_points = [to_world @ point for point in self._original]
        path = []
        for point in world_points:
            screen = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, point)
            if screen is None:
                return False
            screen = (float(screen.x), float(screen.y))
            if not path or _dist(screen, path[-1]) >= 1.0:
                path.append(screen)
        if len(path) < 2:
            return False
        shapes = recognize_shapes(path)
        if not shapes:
            return False

        shape = shapes[0]
        self._shape = shape
        self._alternatives = shapes[1:]
        self._points = default_points(shape)
        self._drawing_pointer = int(drawing.as_pointer())
        self._target_info = {
            "object": obj.name,
            "layer": layer.name,
            "frame": int(layer.current_frame().frame_number),
            "index": curve_index,
            "count": len(drawing.strokes),
        }
        self._obj_name = obj.name
        self._curve_index = curve_index
        self._point_count = last - first
        self._mapping = make_mapping(
            self._region, self._rv3d, world_points[0],
            _placement_normal(context, self._rv3d, world_points), to_world.inverted_safe(),
        )
        self._anchor = shape_anchor(shape)
        # The end of the stroke then moves with the cursor (by the same
        # amount, even when the stabilizer keeps it behind the cursor); the
        # shape turns and scales around its anchor to follow it.
        self._target = path[-1]
        self._last_mouse = (float(event.mouse_region_x), float(event.mouse_region_y))
        self._reference = (path[-1][0] - self._anchor[0], path[-1][1] - self._anchor[1])
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

    def _current_shape(self, event, shape=None):
        reference = self._reference
        current = (self._target[0] - self._anchor[0], self._target[1] - self._anchor[1])
        reference_length = math.hypot(*reference)
        if reference_length < 2.0 or math.hypot(*current) < 1.0:
            angle, scale = 0.0, 1.0
        else:
            angle = math.atan2(current[1], current[0]) - math.atan2(reference[1], reference[0])
            scale = math.hypot(*current) / reference_length
        snap = self._snap if (event.ctrl or event.oskey) else 0.0
        return transform_shape(self._shape if shape is None else shape, angle, scale, snap)

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
            shapes = [shape] + [self._current_shape(event, other) for other in self._alternatives]
            data.update(
                shape=shape, shapes=shapes, mapping=self._mapping,
                radius=self._radius, opacity=self._opacity,
            )
            _schedule_apply(
                self._window, self._area, self._region, data, self._points,
                DEFAULT_CURVE_TYPE[shape["kind"]], shape["kind"], self._automerge,
            )
            self._automerge = None
            return
        knots, cyclic, _handle_types = shape_knots(shape, self._points)
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


def repair_merged_handles(drawing):
    """Give handles to Bezier points that have none.

    With Automerge, a new stroke drawn from the end of a Bezier stroke (an
    arc or an ellipse made by Quick Shape) is joined to it: the joined
    stroke stays Bezier, but the new points keep the default handle
    position, the drawing's origin, and the stroke shoots there from every
    point. Such points get vector handles a third of the way to their
    neighbours, which keeps the drawn path exactly. Returns how many points
    were repaired.
    """
    attributes = drawing.attributes
    if attributes.get("handle_left") is None or attributes.get("handle_right") is None:
        return 0
    try:
        import numpy as np
    except ImportError:
        return 0
    strokes = drawing.strokes
    count = len(strokes)
    types = attributes.get("curve_type")
    if count == 0 or types is None:
        return 0
    curve_types = np.zeros(count, dtype=np.int8)
    types.data.foreach_get("value", curve_types)
    bezier = np.flatnonzero(curve_types == 2)
    if len(bezier) == 0:
        return 0
    total = len(attributes["position"].data)
    positions = np.zeros(total * 3, dtype=np.float32)
    lefts = np.zeros(total * 3, dtype=np.float32)
    rights = np.zeros(total * 3, dtype=np.float32)
    attributes["position"].data.foreach_get("vector", positions)
    attributes["handle_left"].data.foreach_get("vector", lefts)
    attributes["handle_right"].data.foreach_get("vector", rights)
    positions, lefts, rights = (a.reshape(-1, 3) for a in (positions, lefts, rights))
    offsets = [int(o.value) for o in drawing.curve_offsets]
    left_types = attributes.get("handle_type_left")
    right_types = attributes.get("handle_type_right")
    repaired = 0
    for curve in bezier:
        first, last = offsets[curve], offsets[curve + 1]
        cyclic = bool(strokes[int(curve)].cyclic)
        for i in range(first, last):
            p = positions[i]
            if lefts[i].any() or rights[i].any() or not p.any():
                continue
            if i > first:
                previous = positions[i - 1]
            else:
                previous = positions[last - 1] if cyclic else 2.0 * p - positions[min(i + 1, last - 1)]
            if i < last - 1:
                following = positions[i + 1]
            else:
                following = positions[first] if cyclic else 2.0 * p - positions[max(i - 1, first)]
            attributes["handle_left"].data[i].vector = tuple(p + (previous - p) / 3.0)
            attributes["handle_right"].data[i].vector = tuple(p + (following - p) / 3.0)
            if left_types is not None:
                left_types.data[i].value = _HANDLE_VECTOR
            if right_types is not None:
                right_types.data[i].value = _HANDLE_VECTOR
            repaired += 1
    if repaired:
        drawing.tag_positions_changed()
    return repaired


def _repair_after_automerge(window, drawing=None):
    try:
        if not bpy.context.scene.tool_settings.use_gpencil_automerge_strokes:
            return
        if drawing is None:
            with bpy.context.temp_override(window=window):
                _obj, _layer, drawing = _active_target(bpy.context)
        if drawing is not None and repair_merged_handles(drawing):
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except (KeyError, *FBP_DATA_IO_ERRORS) as exc:
        fbp_warn_once("gp_quick_shape.automerge", "Quick Shape could not repair an automerged stroke", exc)


def _suspend_automerge(scene):
    """Turn Automerge off; returns the scene's name if it was on."""
    try:
        settings = scene.tool_settings
        if settings.use_gpencil_automerge_strokes:
            settings.use_gpencil_automerge_strokes = False
            return scene.name
    except FBP_DATA_ERRORS:
        pass
    return None


def _resume_automerge(scene_name):
    scene = bpy.data.scenes.get(scene_name) if scene_name else None
    if scene is not None:
        try:
            scene.tool_settings.use_gpencil_automerge_strokes = True
        except FBP_DATA_ERRORS:
            pass
    return None


def _schedule_apply(window, area, region, data, points, curve_type, kind, automerge=None):
    """Run the Quick Shape operator once the brush has finished the stroke.

    The brush finishes the hand-drawn stroke on release and pushes its own
    Undo step; the operator then replaces the stroke by the shape's own
    points, with its own Undo step and the Adjust Last Operation panel.
    """
    payload = json.dumps(data)

    def apply():
        _repair_after_automerge(window, _find_drawing(data))
        try:
            override = {"window": window}
            if area is not None and any(a == area for a in window.screen.areas):
                override.update(area=area, region=region)
            with bpy.context.temp_override(**override):
                # ``True``: register the call like a user action, so it gets
                # its own Undo step and the Adjust Last Operation panel.
                bpy.ops.fbp.gp_quick_shape_apply(
                    "EXEC_DEFAULT", True, points=points, curve_type=curve_type,
                    kind=kind, last_kind=kind, data=payload,
                )
        except FBP_DATA_IO_ERRORS as exc:
            fbp_warn_once("gp_quick_shape.final", "Quick Shape could not simplify the stroke", exc)
        finally:
            _resume_automerge(automerge)
        return None

    bpy.app.timers.register(apply, first_interval=0.0)


classes = (FBP_OT_GPQuickShapeApply, FBP_OT_GPQuickShapeStroke, FBP_OT_GPQuickShapeFollow)


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
    if _WATCHER is not None:
        _WATCHER.stop()
    _unregister_keymaps()
    unregister_classes(classes)
