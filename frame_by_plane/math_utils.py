"""Small numeric helpers shared by mask and geometry backends.

Keep this module Blender-free so hot-path geometry code can reuse the same
finite-number and polygon rules without importing RNA or duplicating edge-case
handling.
"""

from __future__ import annotations

import math
from bisect import bisect_left


_NUMERIC_ERRORS = (
    AttributeError,
    IndexError,
    OverflowError,
    ReferenceError,
    RuntimeError,
    TypeError,
    ValueError,
)



def clamp(value, minimum, maximum):
    """Clamp a comparable value to the inclusive ``minimum``/``maximum`` range."""
    return max(minimum, min(maximum, value))

def safe_float(value, fallback=0.0) -> float:
    """Convert *value* to a finite float and sanitize the fallback as well."""
    try:
        fallback_value = float(fallback)
    except _NUMERIC_ERRORS:
        fallback_value = 0.0
    if not math.isfinite(fallback_value):
        fallback_value = 0.0
    try:
        result = float(value)
    except _NUMERIC_ERRORS:
        return fallback_value
    return result if math.isfinite(result) else fallback_value


def sorted_finite_values(values) -> tuple[float, ...]:
    """Return sorted unique finite floats, ignoring invalid editable values."""
    normalized = set()
    for value in tuple(values or ()):
        try:
            number = float(value)
        except _NUMERIC_ERRORS:
            continue
        if math.isfinite(number):
            normalized.add(number)
    return tuple(sorted(normalized))


def value_near_sorted(value, sorted_values, tolerance=1.0e-6) -> bool:
    """Test proximity in O(log n) against an ascending numeric sequence."""
    try:
        number = float(value)
        epsilon = abs(float(tolerance))
    except _NUMERIC_ERRORS:
        return False
    if not math.isfinite(number) or not math.isfinite(epsilon):
        return False
    try:
        count = len(sorted_values)
        if count <= 0:
            return False
        index = bisect_left(sorted_values, number)
        if index < count and abs(float(sorted_values[index]) - number) <= epsilon:
            return True
        return index > 0 and abs(float(sorted_values[index - 1]) - number) <= epsilon
    except _NUMERIC_ERRORS:
        return False


def point_inside_polygon_unchecked(x, y, points) -> bool:
    """Fast even/odd polygon test for already-normalized contours."""
    inside = False
    previous = points[-1]
    for current in points:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / ((y2 - y1) or 1.0e-12) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside


def point_inside_polygon(x, y, points) -> bool:
    """Safely test a point against a possibly incomplete editable contour."""
    try:
        if len(points) < 3:
            return False
        test_x = float(x)
        test_y = float(y)
        if not math.isfinite(test_x) or not math.isfinite(test_y):
            return False
        return point_inside_polygon_unchecked(test_x, test_y, points)
    except _NUMERIC_ERRORS:
        return False


__all__ = (
    "clamp",
    "point_inside_polygon",
    "point_inside_polygon_unchecked",
    "safe_float",
    "sorted_finite_values",
    "value_near_sorted",
)
