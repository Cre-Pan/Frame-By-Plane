"""Raster SDF backend for Grease Pencil Mask v2.

Input remains vector/polyline geometry; output is a Blender image-compatible
RGBA float stream.  Supports fill, line, both, per-point radius, expand/contract
and soft blur from the same signed distance field.
"""

from __future__ import annotations

import math
from array import array
from collections import OrderedDict

from .math_utils import point_inside_polygon_unchecked as _point_inside_polygon
from .math_utils import safe_float as _safe_float


_EXC = (AttributeError, IndexError, ReferenceError, RuntimeError, TypeError, ValueError)

DEFAULT_GP_MASK_STROKE_WIDTH = 0.002
_RGBA_CACHE = OrderedDict()
_RGBA_CACHE_BYTES = 0
_RGBA_CACHE_MAX_ENTRIES = 6
_RGBA_CACHE_MAX_BYTES = 32 * 1024 * 1024
_GRID_CACHE = OrderedDict()
_GRID_CACHE_BYTES = 0
_GRID_CACHE_MAX_ENTRIES = 8
_GRID_CACHE_MAX_BYTES = 16 * 1024 * 1024
_NUMPY_UNSET = object()
_NUMPY_MODULE = _NUMPY_UNSET


def clear_runtime_caches():
    """Release reusable mask buffers after file reload, add-on reload or repair."""
    global _RGBA_CACHE_BYTES, _GRID_CACHE_BYTES
    _RGBA_CACHE.clear()
    _GRID_CACHE.clear()
    _RGBA_CACHE_BYTES = 0
    _GRID_CACHE_BYTES = 0


def numpy_module():
    """Return NumPy once; Blender 5.2 bundles it for the fast mask path."""
    global _NUMPY_MODULE
    if _NUMPY_MODULE is not _NUMPY_UNSET:
        return _NUMPY_MODULE
    try:
        import numpy as np  # type: ignore
        _NUMPY_MODULE = np
    except Exception:
        _NUMPY_MODULE = None
    return _NUMPY_MODULE


def _grid_numpy(bounds, resolution, np):
    """Return bounded reusable X/Y grids for one mask plane and resolution."""
    global _GRID_CACHE_BYTES
    min_x, max_x, min_y, max_y = (float(value) for value in bounds)
    key = (int(resolution), min_x, max_x, min_y, max_y)
    cached = _GRID_CACHE.get(key)
    if cached is not None:
        _GRID_CACHE.move_to_end(key)
        return cached[0], cached[1]
    grid_x = np.linspace(min_x, max_x, int(resolution), dtype=np.float32)[None, :]
    grid_y = np.linspace(min_y, max_y, int(resolution), dtype=np.float32)[:, None]
    byte_count = int(grid_x.nbytes + grid_y.nbytes)
    _GRID_CACHE[key] = (grid_x, grid_y, byte_count)
    _GRID_CACHE_BYTES += byte_count
    while len(_GRID_CACHE) > _GRID_CACHE_MAX_ENTRIES or _GRID_CACHE_BYTES > _GRID_CACHE_MAX_BYTES:
        _old_key, (_old_x, _old_y, old_bytes) = _GRID_CACHE.popitem(last=False)
        _GRID_CACHE_BYTES = max(0, _GRID_CACHE_BYTES - int(old_bytes or 0))
    return grid_x, grid_y


def _polyline_is_degenerate(points) -> bool:
    try:
        if len(points) <= 1:
            return True
        first = points[0]
        for point in points[1:]:
            if (float(point[0]) - float(first[0])) ** 2 + (float(point[1]) - float(first[1])) ** 2 > 1.0e-12:
                return False
    except (IndexError, TypeError, ValueError):
        return True
    return True


def _closed_contour(points):
    try:
        values = tuple((float(p[0]), float(p[1])) for p in tuple(points or ()))
    except (TypeError, ValueError, IndexError):
        return ()
    if len(values) < 3:
        return values
    first = values[0]
    last = values[-1]
    if (first[0] - last[0]) ** 2 + (first[1] - last[1]) ** 2 <= 1.0e-18:
        return values
    return values + (first,)


def _width_samples(width, point_count, fallback):
    fallback = max(1.0e-6, _safe_float(fallback, 1.0e-6))
    try:
        if isinstance(width, (str, bytes)):
            raise TypeError
        values = tuple(width)
    except (TypeError, ValueError):
        scalar = max(1.0e-6, _safe_float(width, fallback))
        return tuple(scalar for _ in range(max(1, int(point_count or 1))))
    if not values:
        return tuple(fallback for _ in range(max(1, int(point_count or 1))))
    result = [
        max(1.0e-6, _safe_float(value, fallback))
        for value in values[:max(1, int(point_count or 1))]
    ]
    while len(result) < max(1, int(point_count or 1)):
        result.append(result[-1] if result else fallback)
    return tuple(result)


def _axis_step(bounds, resolution):
    try:
        min_x, max_x, min_y, max_y = bounds
        sx = abs(float(max_x) - float(min_x)) / max(1, int(resolution) - 1)
        sy = abs(float(max_y) - float(min_y)) / max(1, int(resolution) - 1)
        return max(1.0e-9, max(sx, sy))
    except (TypeError, ValueError):
        return 1.0e-4


def _coord_window(min_value, max_value, bounds_min, bounds_max, resolution, margin):
    try:
        span = float(bounds_max) - float(bounds_min)
        if abs(span) <= 1.0e-12:
            return 0, int(resolution)
        a = (float(min_value) - float(margin) - float(bounds_min)) / span
        b = (float(max_value) + float(margin) - float(bounds_min)) / span
        lo = int(math.floor(min(a, b) * (int(resolution) - 1))) - 1
        hi = int(math.ceil(max(a, b) * (int(resolution) - 1))) + 2
        return max(0, lo), min(int(resolution), hi)
    except (TypeError, ValueError, OverflowError):
        return 0, int(resolution)


def _segment_chunk_size(resolution):
    try:
        res = int(resolution or 0)
    except (TypeError, ValueError):
        res = 128
    if res >= 1024:
        return 3
    if res >= 512:
        return 6
    if res >= 256:
        return 12
    return 24


def _distance_to_points_numpy(points, grid_x, grid_y, resolution, np):
    try:
        coords = np.asarray(points, dtype=np.float32)
    except (TypeError, ValueError):
        coords = np.empty((0, 2), dtype=np.float32)
    if coords.ndim != 2 or coords.shape[0] < 1 or coords.shape[1] < 2:
        return np.full((resolution, resolution), np.inf, dtype=np.float32)
    distance_sq = np.full((resolution, resolution), np.inf, dtype=np.float32)
    chunk_size = max(1, _segment_chunk_size(resolution) * 2)
    for start_index in range(0, coords.shape[0], chunk_size):
        chunk = coords[start_index:start_index + chunk_size]
        px = chunk[:, 0][:, None, None]
        py = chunk[:, 1][:, None, None]
        local = (grid_x[None, :, :] - px) ** 2 + (grid_y[None, :, :] - py) ** 2
        distance_sq = np.minimum(distance_sq, local.min(axis=0))
    return np.sqrt(distance_sq)


def _segment_arrays(points, cyclic, np):
    try:
        coords = np.asarray(points, dtype=np.float32)
    except (TypeError, ValueError):
        return None
    if coords.ndim != 2 or coords.shape[0] < 2 or coords.shape[1] < 2:
        return None
    start = coords if cyclic else coords[:-1]
    end = np.roll(coords, -1, axis=0) if cyclic else coords[1:]
    dx = end[:, 0] - start[:, 0]
    dy = end[:, 1] - start[:, 1]
    length_sq = dx * dx + dy * dy
    mask = length_sq > np.float32(1.0e-12)
    if not bool(mask.any()):
        return None
    return start[mask, 0], start[mask, 1], dx[mask], dy[mask], length_sq[mask], mask


def _segment_distance_numpy(points, cyclic, grid_x, grid_y, resolution, np, widths=None, fallback_width=0.0, *, bounds=None, local_band=None):
    arrays = _segment_arrays(points, cyclic, np)
    if arrays is None:
        distance = _distance_to_points_numpy(points, grid_x, grid_y, resolution, np)
        if widths is None:
            return distance
        width = max(1.0e-6, _safe_float(max(widths) if widths else fallback_width, fallback_width))
        return np.float32(width) - distance
    x1, y1, dx, dy, length_sq, valid_mask = arrays
    use_local = bool(bounds is not None and local_band is not None and float(local_band or 0.0) > 0.0)
    if widths is None:
        distance_sq = np.full((resolution, resolution), np.inf, dtype=np.float32)
    else:
        signed = np.full((resolution, resolution), -1.0e6, dtype=np.float32)
        try:
            width_values = np.asarray(widths, dtype=np.float32)
        except (TypeError, ValueError):
            width_values = np.full(len(points), float(fallback_width or 1.0e-6), dtype=np.float32)
        w1_all = width_values if cyclic else width_values[:-1]
        w2_all = np.roll(width_values, -1) if cyclic else width_values[1:]
        w1_all = w1_all[valid_mask]
        w2_all = w2_all[valid_mask]

    if use_local:
        min_x, max_x, min_y, max_y = bounds
        margin = max(float(local_band or 0.0), _axis_step(bounds, resolution) * 2.0)
        for index in range(x1.shape[0]):
            sx = float(x1[index]); sy = float(y1[index])
            ex = sx + float(dx[index]); ey = sy + float(dy[index])
            x0, x2 = _coord_window(min(sx, ex), max(sx, ex), min_x, max_x, resolution, margin)
            y0, y2 = _coord_window(min(sy, ey), max(sy, ey), min_y, max_y, resolution, margin)
            if x2 <= x0 or y2 <= y0:
                continue
            gx = grid_x[:, x0:x2]
            gy = grid_y[y0:y2, :]
            sdx = np.float32(dx[index]); sdy = np.float32(dy[index]); slen = np.float32(length_sq[index])
            t = ((gx - np.float32(sx)) * sdx + (gy - np.float32(sy)) * sdy) / slen
            t = np.clip(t, 0.0, 1.0)
            cx = np.float32(sx) + t * sdx
            cy = np.float32(sy) + t * sdy
            dist = np.sqrt((gx - cx) ** 2 + (gy - cy) ** 2)
            if widths is None:
                distance_sq[y0:y2, x0:x2] = np.minimum(distance_sq[y0:y2, x0:x2], dist * dist)
            else:
                sw1 = np.float32(w1_all[index]); sw2 = np.float32(w2_all[index])
                local_width = sw1 + (sw2 - sw1) * t
                signed[y0:y2, x0:x2] = np.maximum(signed[y0:y2, x0:x2], local_width - dist)
        return np.sqrt(distance_sq) if widths is None else signed

    chunk_size = max(1, _segment_chunk_size(resolution))
    for start_index in range(0, x1.shape[0], chunk_size):
        stop = start_index + chunk_size
        sx = x1[start_index:stop][:, None, None]
        sy = y1[start_index:stop][:, None, None]
        sdx = dx[start_index:stop][:, None, None]
        sdy = dy[start_index:stop][:, None, None]
        slen = length_sq[start_index:stop][:, None, None]
        t = ((grid_x[None, :, :] - sx) * sdx + (grid_y[None, :, :] - sy) * sdy) / slen
        t = np.clip(t, 0.0, 1.0)
        cx = sx + t * sdx
        cy = sy + t * sdy
        dist = np.sqrt((grid_x[None, :, :] - cx) ** 2 + (grid_y[None, :, :] - cy) ** 2)
        if widths is None:
            distance_sq = np.minimum(distance_sq, (dist * dist).min(axis=0))
        else:
            sw1 = w1_all[start_index:stop][:, None, None]
            sw2 = w2_all[start_index:stop][:, None, None]
            local_width = sw1 + (sw2 - sw1) * t
            signed = np.maximum(signed, (local_width - dist).max(axis=0))
    return np.sqrt(distance_sq) if widths is None else signed


def _fill_mask_numpy(polygons, grid_x, grid_y, resolution, np):
    """Return even/odd fill parity without calculating an SDF boundary."""
    combined_inside = np.zeros((resolution, resolution), dtype=bool)
    for contours in tuple(polygons or ()):
        inside = np.zeros((resolution, resolution), dtype=bool)
        for contour in tuple(contours or ()):
            contour_closed = _closed_contour(contour)
            if len(contour_closed) < 4:
                continue
            contour_inside = np.zeros((resolution, resolution), dtype=bool)
            previous = contour_closed[-1]
            for current in contour_closed:
                x1, y1 = previous
                x2, y2 = current
                crossing = (y1 > grid_y) != (y2 > grid_y)
                denom = np.float32(y2 - y1)
                if abs(float(denom)) <= 1.0e-12:
                    denom = np.float32(1.0e-12)
                intersection = (x2 - x1) * (grid_y - y1) / denom + x1
                contour_inside ^= crossing & (grid_x < intersection)
                previous = current
            inside ^= contour_inside
        combined_inside |= inside
    return combined_inside


def _line_signed_distance_numpy(polylines, bounds, resolution, stroke_width, np, band_margin, grid_x, grid_y):
    combined = np.full((resolution, resolution), -1.0e6, dtype=np.float32)
    for points, cyclic, line_width in tuple(polylines or ()):
        if len(points) < 1:
            continue
        widths = _width_samples(line_width, len(points), stroke_width)
        half_width = max(widths)
        local_band = max(
            float(half_width) + float(band_margin or 0.0),
            _axis_step(bounds, resolution) * 3.0,
        )
        signed = _segment_distance_numpy(
            points,
            cyclic,
            grid_x,
            grid_y,
            resolution,
            np,
            widths=widths,
            fallback_width=stroke_width,
            bounds=bounds,
            local_band=local_band,
        )
        combined = np.maximum(combined, signed)
    return combined


def _signed_distance_numpy(polygons, polylines, bounds, resolution, stroke_width, np, band_margin=0.0):
    grid_x, grid_y = _grid_numpy(bounds, resolution, np)
    combined = np.full((resolution, resolution), -1.0e6, dtype=np.float32)

    def boundary_distance(points, cyclic, *, local_band=None):
        if len(points) < 1:
            return np.full((resolution, resolution), np.inf, dtype=np.float32)
        if len(points) == 1 or _polyline_is_degenerate(points):
            return _distance_to_points_numpy(points, grid_x, grid_y, resolution, np)
        return _segment_distance_numpy(points, cyclic, grid_x, grid_y, resolution, np, bounds=bounds, local_band=local_band)

    for contours in tuple(polygons or ()):  # fill groups, even/odd parity within group
        inside = np.zeros((resolution, resolution), dtype=bool)
        boundary = np.full((resolution, resolution), np.inf, dtype=np.float32)
        for contour in tuple(contours or ()):
            contour_closed = _closed_contour(contour)
            if len(contour_closed) < 4:
                continue
            contour_inside = np.zeros((resolution, resolution), dtype=bool)
            previous = contour_closed[-1]
            for current in contour_closed:
                x1, y1 = previous; x2, y2 = current
                crossing = (y1 > grid_y) != (y2 > grid_y)
                denom = np.float32(y2 - y1)
                if abs(float(denom)) <= 1.0e-12:
                    denom = np.float32(1.0e-12)
                intersection = (x2 - x1) * (grid_y - y1) / denom + x1
                contour_inside ^= crossing & (grid_x < intersection)
                previous = current
            inside ^= contour_inside
            boundary = np.minimum(boundary, boundary_distance(contour_closed, True))
        signed = np.where(inside, boundary, -boundary)
        combined = np.maximum(combined, signed)

    if polylines:
        line_signed = _line_signed_distance_numpy(
            polylines,
            bounds,
            resolution,
            stroke_width,
            np,
            band_margin,
            grid_x,
            grid_y,
        )
        combined = np.maximum(combined, line_signed)
    return combined


def _distance_to_polyline(x, y, points, cyclic):
    if len(points) == 1:
        x1, y1 = points[0]
        return math.hypot(x - x1, y - y1)
    best = float("inf")
    count = len(points) if cyclic else len(points) - 1
    for index in range(max(0, count)):
        x1, y1 = points[index]; x2, y2 = points[(index + 1) % len(points)]
        dx = x2 - x1; dy = y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq <= 1.0e-12:
            continue
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_sq))
        best = min(best, math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    if not math.isfinite(best):
        for x1, y1 in points:
            best = min(best, math.hypot(x - x1, y - y1))
    return best


def _signed_distance_fallback(polygons, polylines, bounds, resolution, stroke_width):
    min_x, max_x, min_y, max_y = bounds
    values = []
    for row in range(resolution):
        y = min_y + (max_y - min_y) * (row / max(1, resolution - 1))
        for col in range(resolution):
            x = min_x + (max_x - min_x) * (col / max(1, resolution - 1))
            signed = -1.0e6
            for contours in tuple(polygons or ()):
                inside = False
                distance = float("inf")
                for contour in tuple(contours or ()):
                    contour_closed = _closed_contour(contour)
                    if len(contour_closed) < 4:
                        continue
                    inside ^= _point_inside_polygon(x, y, contour_closed)
                    distance = min(distance, _distance_to_polyline(x, y, contour_closed, True))
                if math.isfinite(distance):
                    signed = max(signed, distance if inside else -distance)
            for points, cyclic, line_width in tuple(polylines or ()):
                widths = _width_samples(line_width, len(points), stroke_width)
                count = len(points) if cyclic else max(1, len(points) - 1)
                if len(points) <= 1 or _polyline_is_degenerate(points):
                    signed = max(signed, max(widths) - _distance_to_polyline(x, y, points, cyclic))
                    continue
                for index in range(max(0, count)):
                    x1, y1 = points[index]; x2, y2 = points[(index + 1) % len(points)]
                    dx = x2 - x1; dy = y2 - y1
                    length_sq = dx * dx + dy * dy
                    if length_sq <= 1.0e-12:
                        continue
                    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_sq))
                    local_width = widths[index] + (widths[(index + 1) % len(widths)] - widths[index]) * t
                    signed = max(signed, local_width - math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
            values.append(signed)
    return values


def _rgba_numpy(alpha, np):
    global _RGBA_CACHE_BYTES
    height, width = alpha.shape
    key = (int(height), int(width))
    cached = _RGBA_CACHE.get(key)
    if cached is None:
        rgba = np.empty((height, width, 4), dtype=np.float32)
        byte_count = int(getattr(rgba, "nbytes", 0) or 0)
        _RGBA_CACHE[key] = (rgba, byte_count)
        _RGBA_CACHE_BYTES += byte_count
        while len(_RGBA_CACHE) > _RGBA_CACHE_MAX_ENTRIES or _RGBA_CACHE_BYTES > _RGBA_CACHE_MAX_BYTES:
            old_key, (_old_buffer, old_bytes) = _RGBA_CACHE.popitem(last=False)
            _RGBA_CACHE_BYTES = max(0, _RGBA_CACHE_BYTES - int(old_bytes or 0))
            if old_key == key:
                break
        cached = _RGBA_CACHE.get(key, (rgba, byte_count))
    else:
        _RGBA_CACHE.move_to_end(key)
    rgba = cached[0]
    rgba[:, :, 0] = alpha
    rgba[:, :, 1] = alpha
    rgba[:, :, 2] = alpha
    rgba[:, :, 3] = alpha
    return rgba.reshape(-1)


def generate_base_alpha(mask_geometry, canvas, resolution):
    """Return the reusable pre-Reveal NumPy alpha field when available.

    Geometry, Expand, Blur and Threshold are frame-invariant during a normal
    Reveal animation.  Keeping this single-channel result lets the caller apply
    only the inexpensive directional Reveal gate on subsequent frames.
    """
    resolution = max(8, int(resolution or 128))
    polygons = tuple(getattr(mask_geometry, "fill_groups", ()) or ())
    polylines = tuple(getattr(mask_geometry, "polylines", ()) or ())
    bounds = tuple(getattr(mask_geometry, "bounds", (-1.0, 1.0, -1.0, 1.0)))
    stroke_width = max(1.0e-6, _safe_float(getattr(canvas, "fbp_gp_mask_stroke_width", DEFAULT_GP_MASK_STROKE_WIDTH), DEFAULT_GP_MASK_STROKE_WIDTH))
    np = numpy_module()
    if np is None:
        return None
    if not polygons and not polylines:
        return np.zeros((resolution, resolution), dtype=np.float32)

    expand = _safe_float(getattr(canvas, "fbp_gp_mask_expand", 0.0), 0.0)
    blur = max(0.0, _safe_float(getattr(canvas, "fbp_gp_mask_feather", 0.0), 0.0))
    threshold = _safe_float(getattr(canvas, "fbp_gp_mask_threshold", 0.5), 0.5)
    band_margin = max(abs(expand) + blur, _axis_step(bounds, resolution) * 4.0)
    if abs(expand) <= 1.0e-7 and blur <= 1.0e-7:
        # Fill/Both preview does not need a fill boundary SDF when there is
        # no expand or feather. Compute parity directly and calculate only
        # the variable-width line component when present.
        grid_x, grid_y = _grid_numpy(bounds, resolution, np)
        alpha_bool = _fill_mask_numpy(polygons, grid_x, grid_y, resolution, np)
        if polylines:
            line_signed = _line_signed_distance_numpy(
                polylines,
                bounds,
                resolution,
                stroke_width,
                np,
                band_margin,
                grid_x,
                grid_y,
            )
            alpha_bool |= line_signed >= 0.0
        alpha = alpha_bool.astype(np.float32, copy=False)
    else:
        signed = _signed_distance_numpy(
            polygons,
            polylines,
            bounds,
            resolution,
            stroke_width,
            np,
            band_margin=band_margin,
        )
        # Positive signed distance means inside the mask. Expand pushes the
        # edge out; negative values contract it. Blur controls softness.
        shifted = signed + np.float32(expand)
        if blur > 1.0e-7:
            alpha = np.clip(0.5 + shifted / np.float32(2.0 * blur), 0.0, 1.0)
            alpha = alpha * alpha * (np.float32(3.0) - np.float32(2.0) * alpha)
        else:
            alpha = np.where(shifted >= 0.0, 1.0, 0.0).astype(np.float32, copy=False)
    if abs(threshold - 0.5) > 1.0e-6:
        alpha = np.clip((alpha - threshold) / max(1.0e-6, 1.0 - threshold), 0.0, 1.0)
    return alpha.astype(np.float32, copy=False)


def generate_pixels(
    mask_geometry,
    canvas,
    resolution,
    *,
    reveal_callback=None,
    frame_number=1,
    base_alpha=None,
):
    """Return flat RGBA pixels for Blender Image.foreach_set."""
    resolution = max(8, int(resolution or 128))
    np = numpy_module()
    if np is not None:
        alpha = base_alpha
        if not (
            isinstance(alpha, np.ndarray)
            and alpha.dtype == np.float32
            and alpha.shape == (resolution, resolution)
        ):
            alpha = generate_base_alpha(mask_geometry, canvas, resolution)
        if reveal_callback is not None:
            alpha = reveal_callback(alpha, frame_number)
        return _rgba_numpy(alpha.astype(np.float32, copy=False), np)

    polygons = tuple(getattr(mask_geometry, "fill_groups", ()) or ())
    polylines = tuple(getattr(mask_geometry, "polylines", ()) or ())
    bounds = tuple(getattr(mask_geometry, "bounds", (-1.0, 1.0, -1.0, 1.0)))
    stroke_width = max(1.0e-6, _safe_float(getattr(canvas, "fbp_gp_mask_stroke_width", DEFAULT_GP_MASK_STROKE_WIDTH), DEFAULT_GP_MASK_STROKE_WIDTH))
    if not polygons and not polylines:
        pixels = array("f")
        pixels.extend((0.0, 0.0, 0.0, 0.0) * (resolution * resolution))
        return pixels

    expand = _safe_float(getattr(canvas, "fbp_gp_mask_expand", 0.0), 0.0)
    blur = max(0.0, _safe_float(getattr(canvas, "fbp_gp_mask_feather", 0.0), 0.0))
    threshold = _safe_float(getattr(canvas, "fbp_gp_mask_threshold", 0.5), 0.5)

    # Pure-Python safety path. The output length must exactly match the Blender
    # image datablock. Earlier builds silently capped this at 128, producing an
    # invalid pixel buffer whenever a higher-resolution mask was requested.
    values = _signed_distance_fallback(polygons, polylines, bounds, resolution, stroke_width)
    pixels = array("f")
    softness = max(1.0e-6, blur)
    for signed in values:
        shifted = float(signed) + float(expand)
        if blur > 1.0e-7:
            alpha = max(0.0, min(1.0, 0.5 + shifted / (2.0 * softness)))
            alpha = alpha * alpha * (3.0 - 2.0 * alpha)
        else:
            alpha = 1.0 if shifted >= 0.0 else 0.0
        if abs(threshold - 0.5) > 1.0e-6:
            alpha = max(0.0, min(1.0, (alpha - threshold) / max(1.0e-6, 1.0 - threshold)))
        pixels.extend((alpha, alpha, alpha, alpha))
    return pixels
