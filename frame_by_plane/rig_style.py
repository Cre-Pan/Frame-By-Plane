"""Rig styles and controller shapes shared by the transform box and the wire.

Two styles:

* **Digital** (default): no wire; a selected layer shows the transform box,
  drawn in the rig shape (rectangle, circle, triangle, polygon, alpha
  outline) with its handles on the outline.
* **Legacy**: the coloured wire of the rig mesh, always visible, in the same
  shapes. Selected layers still show the box for dragging.

Both use the same outline, built here in rig-local XY:

* **Expand** above 0 adds a border around the plane; below 0 shrinks the
  shape towards its centre (down to 10% of the plane).
* **Perfect Shape** keeps a square, circle or regular polygon in world space:
  the rig's own scale (and its parents') is divided out, so stretching the
  layer never turns a circle into an ellipse.
"""

from __future__ import annotations

import math


EXPAND_STEP = 0.05
EXPAND_MIN = -18.0
EXPAND_MAX = 40.0
CIRCLE_SEGMENTS = 64

# Shapes whose outline is a regular polygon, with their fixed side count.
_FIXED_SIDES = {"TRIANGLE": 3}


def rig_style(rig):
    """``'LEGACY'`` when the layer shows its wire, ``'DIGITAL'`` otherwise."""
    try:
        return "LEGACY" if bool(getattr(rig, "fbp_rig_visible", False)) else "DIGITAL"
    except (AttributeError, ReferenceError, RuntimeError):
        return "DIGITAL"


def rig_shape(rig):
    try:
        return str(getattr(rig, "fbp_rig_shape", "DEFAULT") or "DEFAULT").upper()
    except (AttributeError, ReferenceError, RuntimeError):
        return "DEFAULT"


def rig_perfect(rig):
    try:
        return str(getattr(rig, "fbp_rig_shape_fit_mode", "FIT_PLANE") or "FIT_PLANE").upper() == "PERFECT"
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def rig_sides(rig, shape=None):
    shape = shape or rig_shape(rig)
    if shape in _FIXED_SIDES:
        return _FIXED_SIDES[shape]
    try:
        return max(3, min(50, int(getattr(rig, "fbp_rig_shape_sides", 6) or 6)))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 6


def expand_value(rig):
    try:
        value = float(getattr(rig, "fbp_rig_shape_expand", 1.0))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        value = 1.0
    if not math.isfinite(value):
        value = 1.0
    return max(EXPAND_MIN, min(EXPAND_MAX, value))


def expand_margin(rig):
    """Border added around the plane, in rig-local units (0 when shrinking)."""
    return EXPAND_STEP * max(0.0, expand_value(rig))


def shrink_factor(rig):
    """Scale towards the centre for a negative Expand (1.0 otherwise)."""
    return max(0.1, 1.0 + EXPAND_STEP * min(0.0, expand_value(rig)))


def axis_scales(matrix):
    """World length of the rig's local X and Y units."""
    try:
        sx = matrix.col[0].xyz.length
        sy = matrix.col[1].xyz.length
    except (AttributeError, IndexError, TypeError):
        return 1.0, 1.0
    return (sx if sx > 1.0e-9 else 1.0), (sy if sy > 1.0e-9 else 1.0)


def is_outline_shape(shape):
    """Shapes drawn as a closed curve other than the plane rectangle."""
    return shape in {"CIRCLE", "POLYGON", "TRIANGLE"}


def _regular_polygon(count):
    # Polygons rest on a flat bottom edge.
    offset = math.pi / count - math.pi * 0.5
    return [
        (math.cos(math.tau * index / count + offset), math.sin(math.tau * index / count + offset))
        for index in range(count)
    ]


def _bbox(points):
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    return min(xs), max(xs), min(ys), max(ys)


def shape_outline(shape, center, half, *, sides=6, perfect=False, scales=(1.0, 1.0), margin=0.0, shrink=1.0):
    """Closed outline (list of rig-local ``(x, y)``) around ``center``.

    ``half`` are the plane's half extents in rig space. ``margin`` is added
    to them; ``shrink`` scales the result towards ``center``. With
    ``perfect`` the shape is regular in world space: ``scales`` are the world
    lengths of the rig's X and Y units.
    """
    shape = str(shape or "DEFAULT").upper()
    cx, cy = float(center[0]), float(center[1])
    hx = max(1.0e-6, float(half[0]) + margin)
    hy = max(1.0e-6, float(half[1]) + margin)
    sx, sy = scales
    if perfect:
        # One world size for both axes, read back in rig units per axis.
        radius = max(hx * sx, hy * sy)
        hx, hy = radius / sx, radius / sy
    if shape == "CIRCLE":
        unit = [
            (math.cos(math.tau * index / CIRCLE_SEGMENTS), math.sin(math.tau * index / CIRCLE_SEGMENTS))
            for index in range(CIRCLE_SEGMENTS)
        ]
    elif shape in {"POLYGON", "TRIANGLE"}:
        unit = _regular_polygon(max(3, min(50, int(sides))))
        min_x, max_x, min_y, max_y = _bbox(unit)
        mid_x, mid_y = (min_x + max_x) * 0.5, (min_y + max_y) * 0.5
        if perfect:
            # Keep the polygon regular: one factor so its larger side fits.
            span = max(max_x - min_x, max_y - min_y) * 0.5
            unit = [((x - mid_x) / span, (y - mid_y) / span) for x, y in unit]
        else:
            # Fit to Plane: the polygon's bounding box spans the plane.
            span_x = max(1.0e-6, (max_x - min_x) * 0.5)
            span_y = max(1.0e-6, (max_y - min_y) * 0.5)
            unit = [((x - mid_x) / span_x, (y - mid_y) / span_y) for x, y in unit]
    else:
        unit = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
    shrink = max(0.0, float(shrink))
    return [(cx + x * hx * shrink, cy + y * hy * shrink) for x, y in unit]


def ray_to_outline(outline, center, direction):
    """Farthest point of ``outline`` along ``direction`` from ``center``."""
    cx, cy = center
    dx, dy = direction
    best = None
    count = len(outline)
    for index in range(count):
        ax, ay = outline[index]
        bx, by = outline[(index + 1) % count]
        ex, ey = bx - ax, by - ay
        denom = dx * ey - dy * ex
        if abs(denom) <= 1.0e-12:
            continue
        # center + t*d = a + u*e
        t = ((ax - cx) * ey - (ay - cy) * ex) / denom
        u = ((ax - cx) * dy - (ay - cy) * dx) / denom
        if t >= 0.0 and -1.0e-9 <= u <= 1.0 + 1.0e-9 and (best is None or t > best):
            best = t
    if best is None:
        return None
    return cx + dx * best, cy + dy * best


def handle_points(outline, center, half):
    """Corner and side handle points on the outline (rig-local XY).

    Corners lie on the diagonals of the outline's box, sides on its axes,
    in the transform box order: corners from bottom left counter-clockwise,
    sides bottom, right, top, left.
    """
    corner_signs = ((-1, -1), (1, -1), (1, 1), (-1, 1))
    edge_signs = ((0, -1), (1, 0), (0, 1), (-1, 0))
    hx, hy = max(1.0e-9, half[0]), max(1.0e-9, half[1])
    corners, edges = [], []
    for signs, out in ((corner_signs, corners), (edge_signs, edges)):
        for sx, sy in signs:
            point = ray_to_outline(outline, center, (sx * hx, sy * hy))
            if point is None:
                point = (center[0] + sx * hx, center[1] + sy * hy)
            out.append(point)
    return corners, edges


def outline_box(outline):
    """``(center, half)`` of the outline's bounding box."""
    min_x, max_x, min_y, max_y = _bbox(outline)
    return ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5), ((max_x - min_x) * 0.5, (max_y - min_y) * 0.5)


def rig_outline(rig, center, half, matrix=None):
    """Outline of ``rig``'s shape around a plane box (rig-local XY)."""
    shape = rig_shape(rig)
    # An Alpha Outline follows the pixels: its box is never squared up.
    perfect = rig_perfect(rig) and shape != "ALPHA"
    if shape in {"CUSTOM", "ALPHA"}:
        shape = "DEFAULT"
    if matrix is None:
        try:
            matrix = rig.matrix_world
        except (AttributeError, ReferenceError, RuntimeError):
            matrix = None
    scales = axis_scales(matrix) if (perfect and matrix is not None) else (1.0, 1.0)
    return shape_outline(
        shape, center, half, sides=rig_sides(rig, shape), perfect=perfect, scales=scales,
        margin=expand_margin(rig), shrink=shrink_factor(rig),
    )


def perfect_scale_key(rig):
    """What a Perfect Shape wire depends on beyond its settings: the rig's
    world X/Y scale ratio. ``None`` when the wire does not depend on it."""
    try:
        if rig_style(rig) != "LEGACY" or not rig_perfect(rig):
            return None
        if rig_shape(rig) in {"CUSTOM", "ALPHA"}:
            return None
        sx, sy = axis_scales(rig.matrix_world)
    except (AttributeError, ReferenceError, RuntimeError):
        return None
    return round(sx / sy, 5)
