"""Grease Pencil Mask v2 core extraction for Frame By Plane.

This module is intentionally small and data-oriented: it reads the currently
exposed Grease Pencil drawing, converts it into the owner plane local 2D space
and returns plain Python geometry.  Raster/vector backends can consume this
without knowing about Blender RNA details.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Sequence

import bpy
from mathutils import Matrix, Vector

from .math_utils import safe_float as _safe_float


@dataclass(slots=True, frozen=True)
class FBPStrokeData:
    """One extracted GP stroke in target-plane local units."""

    points: tuple[tuple[float, float], ...]
    radii: tuple[float, ...]
    is_closed: bool
    use_fill: bool
    use_line: bool
    fill_group: object | None = None


@dataclass(slots=True, frozen=True)
class FBPMaskGeometry:
    """Backend-neutral GP mask geometry."""

    strokes: tuple[FBPStrokeData, ...]
    fill_groups: tuple[tuple[tuple[tuple[float, float], ...], ...], ...]
    polylines: tuple[tuple[tuple[tuple[float, float], ...], bool, tuple[float, ...]], ...]
    bounds: tuple[float, float, float, float]
    frame: int


_EXC = (AttributeError, IndexError, ReferenceError, RuntimeError, TypeError, ValueError)

DEFAULT_GP_MASK_STROKE_WIDTH = 0.002
_MAX_RADIUS_SCALE_SAMPLES = 64
_MAX_CLOSURE_SEGMENT_SAMPLES = 128


def _json_list_from_canvas(canvas, key: str) -> list:
    try:
        raw = canvas.get(key, "")
        if not raw:
            return []
        value = json.loads(str(raw))
        return list(value) if isinstance(value, list) else []
    except _EXC:
        return []


def _canvas_curve_authoring(canvas):
    """Return optional per-curve component modes.

    Thickness is intentionally absent: Blender's native radius attribute is the
    authoritative per-stroke value and avoids delayed curve-index bookkeeping.
    """
    modes = []
    for item in _json_list_from_canvas(canvas, "fbp_gp_mask_curve_modes_json"):
        mode = str(item or "AUTO").upper()
        if mode == "LINE":
            mode = "STROKE"
        modes.append(mode if mode in {"AUTO", "STROKE", "FILL", "BOTH"} else "AUTO")
    return modes

def _material_visibility(canvas, stroke, cache: dict[int, tuple[bool, bool, str]]) -> tuple[bool, bool, str]:
    """Return Blender 5.2 component visibility and stroke topology."""
    material_index = int(getattr(stroke, "material_index", 0) or 0)
    cached = cache.get(material_index)
    if cached is not None:
        return cached

    show_fill = True
    show_line = True
    stroke_mode = "LINE"
    try:
        materials = canvas.data.materials
        material = materials[material_index] if 0 <= material_index < len(materials) else None
        style = material.grease_pencil if material is not None else None
        if style is not None:
            show_fill = bool(style.is_fill_visible)
            show_line = bool(style.is_stroke_visible)
            stroke_mode = str(getattr(style, "mode", "LINE") or "LINE").upper()
    except _EXC:
        pass

    result = (show_fill, show_line, stroke_mode if stroke_mode in {"LINE", "DOTS", "BOX"} else "LINE")
    cache[material_index] = result
    return result


def _point_position(point):
    try:
        position = point.position
        return position if isinstance(position, Vector) else Vector(position)
    except _EXC:
        return None


def _point_radius(point, fallback: float) -> float:
    fallback = max(1.0e-6, _safe_float(fallback, DEFAULT_GP_MASK_STROKE_WIDTH))
    try:
        radius = _safe_float(point.radius, fallback)
    except _EXC:
        radius = fallback
    return radius if radius > 0.0 else fallback


def _point_opacity(point) -> float | None:
    try:
        return _safe_float(point.opacity, 1.0)
    except _EXC:
        return None


def _point_radius_values(points: Sequence[object], fallback: float) -> tuple[float, ...]:
    """Read the authoritative Blender 5.2 ``radius`` stored per GP point."""
    fallback = max(1.0e-6, _safe_float(fallback, DEFAULT_GP_MASK_STROKE_WIDTH))
    return tuple(_point_radius(point, fallback) for point in points)

def _plane_for_surface(surface):
    try:
        plane = getattr(surface, "fbp_plane_target", None)
        return plane if plane is not None else surface
    except _EXC:
        return surface


def plane_bounds(surface) -> tuple[float, float, float, float]:
    plane = _plane_for_surface(surface)
    mesh = getattr(plane, "data", None) if plane is not None else None
    coords = []
    try:
        coords = [
            (float(vertex.co.x), float(vertex.co.y))
            for vertex in getattr(mesh, "vertices", ()) or ()
        ]
    except _EXC:
        coords = []
    if not coords:
        return (-1.0, 1.0, -1.0, 1.0)
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return (min(xs), max(xs), min(ys), max(ys))


def _canvas_to_plane_matrix(canvas, surface):
    plane = _plane_for_surface(surface)
    if plane is None:
        return Matrix.Identity(4)
    try:
        return plane.matrix_world.inverted_safe() @ canvas.matrix_world
    except _EXC:
        return Matrix.Identity(4)


def _scene_for_canvas(canvas, scene=None):
    if scene is not None:
        return scene
    try:
        return bpy.context.scene
    except _EXC:
        return None


def _camera_project_to_plane(canvas, surface, local_position, scene=None):
    plane = _plane_for_surface(surface)
    target_scene = _scene_for_canvas(canvas, scene)
    camera = getattr(target_scene, "camera", None) if target_scene is not None else None
    if plane is None or camera is None:
        return None
    try:
        point_world = canvas.matrix_world @ Vector(local_position)
        plane_origin = plane.matrix_world.translation
        plane_normal = plane.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))
        if str(getattr(camera.data, "type", "PERSP") or "PERSP") == "ORTHO":
            ray_origin = point_world
            ray_direction = camera.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
        else:
            ray_origin = camera.matrix_world.translation
            ray_direction = point_world - ray_origin
        denominator = ray_direction.dot(plane_normal)
        if abs(float(denominator)) <= 1.0e-10:
            return None
        distance = (plane_origin - ray_origin).dot(plane_normal) / denominator
        hit = ray_origin + ray_direction * distance
        return plane.matrix_world.inverted_safe() @ hit
    except _EXC:
        return None


def _transform_points(points, canvas, surface, layer_matrix, scene=None):
    result = []
    try:
        mode = str(getattr(canvas, "fbp_gp_attachment_mode", "PLANE") or "PLANE")
    except _EXC:
        mode = "PLANE"
    transform = _canvas_to_plane_matrix(canvas, surface)
    layer_matrix = layer_matrix or Matrix.Identity(4)
    for point in points:
        source = _point_position(point)
        if source is None:
            continue
        try:
            local_position = layer_matrix @ source
            if mode == "CAMERA":
                co = _camera_project_to_plane(canvas, surface, local_position, scene=scene)
                if co is None:
                    co = transform @ local_position
            else:
                co = transform @ local_position
            result.append((float(co.x), float(co.y)))
        except _EXC:
            continue
    return tuple(result)


def _sampled_segment_indices(point_count: int, max_samples: int):
    """Return deterministic bounded segment indices for long GP strokes."""
    segment_count = max(0, int(point_count or 0) - 1)
    max_samples = max(1, int(max_samples or 1))
    if segment_count <= max_samples:
        return range(segment_count)
    step = max(1, int(math.ceil(segment_count / max_samples)))
    indices = list(range(0, segment_count, step))
    if indices and indices[-1] != segment_count - 1:
        indices.append(segment_count - 1)
    return tuple(indices)


def _radius_scale(canvas, surface, layer_matrix, native_points, transformed_points, scene=None) -> float:
    if not native_points or not transformed_points or len(native_points) != len(transformed_points):
        return 1.0
    layer_matrix = layer_matrix or Matrix.Identity(4)
    transform = _canvas_to_plane_matrix(canvas, surface)
    try:
        mode = str(getattr(canvas, "fbp_gp_attachment_mode", "PLANE") or "PLANE")
    except _EXC:
        mode = "PLANE"
    ratios = []
    try:
        for index in _sampled_segment_indices(
            len(native_points), _MAX_RADIUS_SCALE_SAMPLES
        ):
            a = _point_position(native_points[index])
            b = _point_position(native_points[index + 1])
            if a is None or b is None:
                continue
            source_a = layer_matrix @ a
            source_b = layer_matrix @ b
            tangent = Vector((source_b.x - source_a.x, source_b.y - source_a.y, 0.0))
            if tangent.length <= 1.0e-9:
                continue
            tangent.normalize()
            source_normal = Vector((-tangent.y, tangent.x, 0.0))
            if mode == "CAMERA":
                target_a = _camera_project_to_plane(canvas, surface, source_a, scene=scene)
                target_b = _camera_project_to_plane(canvas, surface, source_a + source_normal, scene=scene)
                if target_a is None or target_b is None:
                    target_a = transform @ source_a
                    target_b = transform @ (source_a + source_normal)
            else:
                target_a = transform @ source_a
                target_b = transform @ (source_a + source_normal)
            scale = math.hypot(float(target_b.x - target_a.x), float(target_b.y - target_a.y))
            if math.isfinite(scale) and scale > 1.0e-9:
                ratios.append(scale)
    except _EXC:
        ratios = []
    if not ratios:
        try:
            origin = transform @ (layer_matrix @ Vector((0.0, 0.0, 0.0)))
            axis_x = transform @ (layer_matrix @ Vector((1.0, 0.0, 0.0)))
            axis_y = transform @ (layer_matrix @ Vector((0.0, 1.0, 0.0)))
            sx = math.hypot(float(axis_x.x - origin.x), float(axis_x.y - origin.y))
            sy = math.hypot(float(axis_y.x - origin.x), float(axis_y.y - origin.y))
            if sx > 1.0e-9 and sy > 1.0e-9:
                return max(1.0e-4, min(1.0e4, math.sqrt(sx * sy)))
        except _EXC:
            pass
        return 1.0
    ratios.sort()
    middle = len(ratios) // 2
    scale = ratios[middle] if len(ratios) % 2 else (ratios[middle - 1] + ratios[middle]) * 0.5
    return max(1.0e-4, min(1.0e4, scale))


def _radius_to_plane_units(raw_value: float, scale: float, plane_extent: float, fallback_width: float) -> float:
    """Convert GPv3 authored radius to target-plane local units.

    In Blender 5.x the real Grease Pencil radius is already an object-space
    distance.  Do not reinterpret large values as UI pixels and do not divide
    by 1000: that heuristic was the main reason brush sizes 10/50 collapsed to
    near-identical masks.  We only multiply by the measured canvas→plane scale
    and clamp to a broad safety limit to avoid pathological full-scene masks.
    """
    raw = _safe_float(raw_value, fallback_width)
    if raw <= 0.0:
        raw = max(1.0e-6, _safe_float(fallback_width, DEFAULT_GP_MASK_STROKE_WIDTH))
    converted = raw * max(1.0e-8, _safe_float(scale, 1.0))
    limit = max(plane_extent * 0.50, 1.0e-5)
    return max(1.0e-5, min(limit, converted))


def _convert_radii(canvas, surface, layer_matrix, points, transformed_points, bounds, fallback_width, layer_radius_offset=0.0, scene=None):
    """Convert the native GP radius attached to this exact stroke.

    No parallel per-curve brush-size list is consulted here. This keeps stroke N
    bound to stroke N even when Blender publishes points/curves across different
    depsgraph ticks or the artist changes brush size immediately after drawing.
    """
    min_x, max_x, min_y, max_y = bounds
    plane_extent = max(1.0e-6, min(abs(max_x - min_x), abs(max_y - min_y)))
    scale = _radius_scale(canvas, surface, layer_matrix, points, transformed_points, scene=scene)
    raw_values = _point_radius_values(points, fallback_width)
    result = []
    for raw in raw_values:
        authored = max(1.0e-6, _safe_float(raw, fallback_width) + float(layer_radius_offset or 0.0))
        result.append(float(_radius_to_plane_units(authored, scale, plane_extent, fallback_width)))
    while len(result) < len(transformed_points):
        result.append(float(_radius_to_plane_units(fallback_width, scale, plane_extent, fallback_width)))
    return tuple(result[:len(transformed_points)])

def _stroke_closed(stroke, points, bounds, authored_fill=False) -> bool:
    """Return True for native cyclic curves or tightly closed hand-drawn loops."""
    try:
        if bool(stroke.cyclic):
            return True
    except _EXC:
        pass
    if len(points) < 3:
        return False
    min_x, max_x, min_y, max_y = bounds
    extent = max(1.0e-6, min(abs(max_x - min_x), abs(max_y - min_y)))
    gap = math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1])
    segments = sorted(
        math.hypot(
            points[index + 1][0] - points[index][0],
            points[index + 1][1] - points[index][1],
        )
        for index in _sampled_segment_indices(
            len(points), _MAX_CLOSURE_SEGMENT_SAMPLES
        )
    )
    segments = [value for value in segments if value > 1.0e-9]
    median = segments[len(segments) // 2] if segments else 0.0
    return gap <= max(extent * 0.006, median * 0.40)

def _component_visibility(stroke, material_fill: bool, material_line: bool, points) -> tuple[bool, bool]:
    """Resolve whether the stroke contributes fill and/or line.

    GPv3 can render a filled contour from material settings even when the
    Python stroke wrapper does not expose a useful ``fill_id`` or ``cyclic``
    value.  Therefore fill authoring follows the material; the caller decides
    whether there are enough points for a valid filled region.
    """
    hide_stroke = False
    try:
        hide_stroke = bool(getattr(stroke, "hide_stroke", False))
    except _EXC:
        pass

    has_opacity = False
    visible_opacity = False
    if len(points) > 1:
        for point in points:
            opacity = _point_opacity(point)
            if opacity is None:
                continue
            has_opacity = True
            if opacity > 1.0e-6:
                visible_opacity = True
                break
    opacity_signal = True if len(points) == 1 or not has_opacity else visible_opacity

    fill_visible = bool(material_fill and len(points) >= 3 and opacity_signal)
    line_visible = bool(material_line and (not hide_stroke) and len(points) > 0 and opacity_signal)
    return fill_visible, line_visible


def _stroke_fill_group(stroke, fallback_index: int):
    fill_id = int(getattr(stroke, "fill_id", 0) or 0)
    return ("NATIVE", fill_id) if fill_id else ("CURVE", fallback_index)


class _AttrPoint:
    __slots__ = ("position", "radius", "opacity")

    def __init__(self, position, radius=None, opacity=None):
        self.position = position if isinstance(position, Vector) else Vector(position)
        self.radius = radius
        self.opacity = opacity


class _AttrStroke:
    __slots__ = (
        "points",
        "material_index",
        "cyclic",
        "component_mode",
        "fill_id",
        "hide_stroke",
    )

    def __init__(
        self,
        points,
        material_index=0,
        cyclic=False,
        component_mode=None,
        fill_id=0,
        hide_stroke=False,
    ):
        self.points = tuple(points)
        self.material_index = int(material_index or 0)
        self.cyclic = bool(cyclic)
        self.component_mode = component_mode
        self.fill_id = int(fill_id or 0)
        self.hide_stroke = bool(hide_stroke)

def _attribute_data(drawing, name: str):
    """Return an exact Blender 5.x drawing attribute data collection."""
    try:
        attribute = drawing.attributes.get(name)
        return attribute.data if attribute is not None else None
    except _EXC:
        return None

def _attribute_scalar_values_exact(drawing, names: Sequence[str], expected_count: int) -> tuple[float | None, ...]:
    """Read a scalar attribute only when its domain length matches exactly.

    Blender 5.x Grease Pencil attributes may live on the POINT domain or on the
    CURVE domain.  The old reader padded shorter arrays to the requested length;
    that could accidentally treat one curve-level radius as the radius for the
    first point only, making brush sizes look unchanged.  This helper is strict
    so callers can decide whether an attribute is point-domain or curve-domain.
    """
    expected_count = int(expected_count or 0)
    if expected_count <= 0:
        return ()
    for name in names:
        data = _attribute_data(drawing, name)
        if data is None:
            continue
        try:
            available = len(data)
        except _EXC:
            available = 0
        if available != expected_count:
            continue
        values = [0.0] * expected_count
        got = False
        for prop in ("value", "factor"):
            try:
                data.foreach_get(prop, values)
                got = True
                break
            except _EXC:
                pass
        if not got:
            values = []
            valid = False
            for index in range(expected_count):
                try:
                    item = data[index]
                except _EXC:
                    values.append(None)
                    continue
                value = None
                for prop in ("value", "factor"):
                    try:
                        raw = getattr(item, prop)
                        if raw is not None:
                            value = _safe_float(raw, 0.0)
                            break
                    except _EXC:
                        continue
                if value is not None and math.isfinite(value):
                    valid = True
                    values.append(value)
                else:
                    values.append(None)
            if not valid:
                continue
        clean = []
        valid = False
        for value in values:
            if value is None:
                clean.append(None)
                continue
            number = _safe_float(value, 0.0)
            if math.isfinite(number):
                valid = True
                clean.append(number)
            else:
                clean.append(None)
        if valid:
            return tuple(clean)
    return ()


def _expand_curve_values_to_points(curve_values: Sequence[float | None], offsets: Sequence[int], point_count: int) -> tuple[float | None, ...]:
    if len(curve_values) != max(0, len(offsets) - 1):
        return ()
    result: list[float | None] = [None] * int(point_count or 0)
    for curve_index, value in enumerate(curve_values):
        try:
            start = max(0, int(offsets[curve_index]))
            stop = min(int(point_count), int(offsets[curve_index + 1]))
        except _EXC:
            continue
        if stop <= start:
            continue
        for point_index in range(start, stop):
            result[point_index] = value
    return tuple(result)

def _attribute_vector_values(drawing, names: Sequence[str], expected_count: int) -> tuple[Vector | None, ...]:
    expected_count = int(expected_count or 0)
    if expected_count <= 0:
        return ()
    for name in names:
        data = _attribute_data(drawing, name)
        if data is None:
            continue
        try:
            available = len(data)
        except _EXC:
            available = expected_count
        count = min(expected_count, int(available or 0))
        if count <= 0:
            continue
        flat = [0.0] * (count * 3)
        got = False
        try:
            data.foreach_get("vector", flat)
            got = True
        except _EXC:
            pass
        result = []
        valid = False
        if got:
            for index in range(count):
                vec = Vector((flat[index * 3], flat[index * 3 + 1], flat[index * 3 + 2]))
                result.append(vec)
                valid = True
        else:
            for index in range(count):
                try:
                    item = data[index]
                except _EXC:
                    result.append(None)
                    continue
                value = None
                for prop in ("vector", "value"):
                    try:
                        raw = getattr(item, prop)
                        if raw is not None:
                            value = Vector(raw)
                            break
                    except _EXC:
                        continue
                if value is None:
                    result.append(None)
                else:
                    result.append(value)
                    valid = True
        while len(result) < expected_count:
            result.append(None)
        if valid:
            return tuple(result[:expected_count])
    return ()


def _curve_offsets_from_drawing(drawing) -> tuple[int, ...]:
    try:
        offsets = drawing.curve_offsets
        count = len(offsets)
    except _EXC:
        return ()
    if count < 2:
        return ()
    try:
        values = [0] * count
        offsets.foreach_get("value", values)
    except _EXC:
        try:
            values = [int(offsets[index].value) for index in range(count)]
        except _EXC:
            return ()
    if values[0] != 0 or any(values[index] > values[index + 1] for index in range(count - 1)):
        return ()
    return tuple(int(value) for value in values)


def _curve_bool(value) -> bool:
    try:
        return bool(int(value))
    except _EXC:
        return bool(value)


def _native_component_mode(
    fill_id=0,
    hide_stroke=False,
    *,
    has_fill_id=False,
    has_hide_stroke=False,
) -> str | None:
    """Resolve Blender 5.2's curve-domain ``fill_id``/``hide_stroke`` state."""
    fill_value = int(fill_id or 0)
    hidden = bool(hide_stroke)
    if has_fill_id:
        if fill_value != 0:
            return "FILL" if hidden else "BOTH"
        return None if hidden else "STROKE"
    if has_hide_stroke:
        return None if hidden else "STROKE"
    return None


def _high_level_component_values(drawing, expected_count: int) -> tuple[tuple[int, bool], ...]:
    """Read Blender 5.2's native stroke visibility API in one bounded pass.

    ``fill_id`` and ``hide_stroke`` became public stroke properties in 5.2.
    Prefer them over two separate attribute-table reads; the exact attribute
    fallback below remains useful for malformed or transitional files where the
    high-level stroke slice cannot be constructed yet.
    """
    expected_count = int(expected_count or 0)
    if expected_count <= 0:
        return ()
    try:
        native_strokes = drawing.strokes
        if len(native_strokes) != expected_count:
            return ()
        result = []
        for stroke in native_strokes:
            if not hasattr(stroke, "fill_id") or not hasattr(stroke, "hide_stroke"):
                return ()
            result.append((int(stroke.fill_id or 0), bool(stroke.hide_stroke)))
        return tuple(result)
    except _EXC:
        return ()


def _attribute_strokes_from_drawing(drawing) -> tuple[_AttrStroke, ...]:
    """Extract current Blender 5.2 GP curves from exact drawing attributes."""
    offsets = _curve_offsets_from_drawing(drawing)
    if len(offsets) < 2:
        return ()
    point_count = int(offsets[-1])
    curve_count = len(offsets) - 1
    if point_count <= 0 or curve_count <= 0:
        return ()

    positions = _attribute_vector_values(drawing, ("position",), point_count)
    if len(positions) != point_count or not any(position is not None for position in positions):
        return ()

    radii = _attribute_scalar_values_exact(drawing, ("radius",), point_count)
    if not radii:
        curve_radii = _attribute_scalar_values_exact(drawing, ("radius",), curve_count)
        radii = _expand_curve_values_to_points(curve_radii, offsets, point_count) if curve_radii else ()

    opacities = _attribute_scalar_values_exact(drawing, ("opacity",), point_count)
    if not opacities:
        curve_opacities = _attribute_scalar_values_exact(drawing, ("opacity",), curve_count)
        opacities = _expand_curve_values_to_points(curve_opacities, offsets, point_count) if curve_opacities else ()

    material_indices = _attribute_scalar_values_exact(drawing, ("material_index",), curve_count)
    cyclic_values = _attribute_scalar_values_exact(drawing, ("cyclic",), curve_count)
    native_components = _high_level_component_values(drawing, curve_count)
    if native_components:
        fill_id_values = tuple(value[0] for value in native_components)
        hide_stroke_values = tuple(value[1] for value in native_components)
        has_fill_id = True
        has_hide_stroke = True
    else:
        fill_id_values = _attribute_scalar_values_exact(drawing, ("fill_id",), curve_count)
        hide_stroke_values = _attribute_scalar_values_exact(drawing, ("hide_stroke",), curve_count)
        has_fill_id = len(fill_id_values) == curve_count
        has_hide_stroke = len(hide_stroke_values) == curve_count

    strokes = []
    for curve_index in range(curve_count):
        start = int(offsets[curve_index])
        stop = int(offsets[curve_index + 1])
        if stop <= start or start < 0 or stop > point_count:
            continue

        points = []
        for point_index in range(start, stop):
            position = positions[point_index]
            if position is None:
                continue
            radius = radii[point_index] if point_index < len(radii) else None
            opacity = opacities[point_index] if point_index < len(opacities) else None
            points.append(_AttrPoint(position, radius=radius, opacity=opacity))
        if not points:
            continue

        material_index = int(_safe_float(material_indices[curve_index], 0.0)) if curve_index < len(material_indices) and material_indices[curve_index] is not None else 0
        cyclic = _curve_bool(cyclic_values[curve_index]) if curve_index < len(cyclic_values) and cyclic_values[curve_index] is not None else False
        fill_id = int(_safe_float(fill_id_values[curve_index], 0.0)) if has_fill_id and fill_id_values[curve_index] is not None else 0
        hide_stroke = _curve_bool(hide_stroke_values[curve_index]) if has_hide_stroke and hide_stroke_values[curve_index] is not None else False
        component_mode = _native_component_mode(
            fill_id,
            hide_stroke,
            has_fill_id=has_fill_id,
            has_hide_stroke=has_hide_stroke,
        )
        strokes.append(
            _AttrStroke(
                points,
                material_index=material_index,
                cyclic=cyclic,
                component_mode=component_mode,
                fill_id=fill_id,
                hide_stroke=hide_stroke,
            )
        )
    return tuple(strokes)

def extract_geometry(canvas, surface, *, bounds=None, frame_number=1, scene=None, exposure_state=None) -> FBPMaskGeometry:
    """Extract visible GP mask geometry as plane-local fills and polylines."""
    bounds = tuple(bounds if bounds is not None else plane_bounds(surface))
    try:
        source_mode = str(getattr(canvas, "fbp_gp_mask_source", "AUTO") or "AUTO")
    except _EXC:
        source_mode = "AUTO"
    if source_mode == "LINE":
        source_mode = "STROKE"
    try:
        fallback_width = max(1.0e-6, float(getattr(canvas, "fbp_gp_mask_stroke_width", DEFAULT_GP_MASK_STROKE_WIDTH) or DEFAULT_GP_MASK_STROKE_WIDTH))
    except _EXC:
        fallback_width = DEFAULT_GP_MASK_STROKE_WIDTH
    try:
        auto_radius = bool(getattr(canvas, "fbp_gp_mask_auto_radius", True))
    except _EXC:
        auto_radius = True
    authored_modes = _canvas_curve_authoring(canvas)
    curve_author_index = 0

    strokes_out: list[FBPStrokeData] = []
    polylines: list[tuple[tuple[tuple[float, float], ...], bool, tuple[float, ...]]] = []
    fill_groups_by_key: dict[object, list[tuple[tuple[float, float], ...]]] = {}
    material_cache: dict[int, tuple[bool, bool, str]] = {}

    if exposure_state is None:
        # Conservative fallback. The bridge normally passes exposure_state.
        entries = []
        data = getattr(canvas, "data", None)
        for layer in tuple(getattr(data, "layers", ()) or ()):
            try:
                frame = layer.current_frame()
                drawing = getattr(frame, "drawing", None) if frame else None
            except _EXC:
                drawing = None
            entries.append((layer, drawing, int(frame_number)))
        exposure_state = tuple(entries)

    fill_group_counter = 0
    for layer, drawing, _source_frame in tuple(exposure_state or ()):
        try:
            if bool(getattr(layer, "hide", False)):
                continue
        except _EXC:
            pass
        if drawing is None:
            continue
        try:
            layer_matrix = getattr(layer, "matrix_local", Matrix.Identity(4)).copy()
        except _EXC:
            layer_matrix = Matrix.Identity(4)
        try:
            layer_radius_offset = float(getattr(layer, "radius_offset", 0.0) or 0.0)
        except _EXC:
            layer_radius_offset = 0.0

        for stroke in _attribute_strokes_from_drawing(drawing):
            points_native = stroke.points
            if not points_native:
                continue
            material_fill, material_line, material_stroke_mode = _material_visibility(canvas, stroke, material_cache)
            authored_fill, authored_line = _component_visibility(stroke, material_fill, material_line, points_native)
            points = _transform_points(points_native, canvas, surface, layer_matrix, scene=scene)
            if not points:
                continue
            cyclic = _stroke_closed(stroke, points, bounds, authored_fill=authored_fill)
            stroke_mode = stroke.component_mode
            if stroke_mode not in {"STROKE", "FILL", "BOTH"} and curve_author_index < len(authored_modes):
                stroke_mode = authored_modes[curve_author_index]
            if stroke_mode not in {"STROKE", "FILL", "BOTH"}:
                stroke_mode = source_mode
            curve_author_index += 1
            radii = (
                _convert_radii(
                    canvas,
                    surface,
                    layer_matrix,
                    points_native,
                    points,
                    bounds,
                    fallback_width,
                    layer_radius_offset,
                    scene=scene,
                )
                if auto_radius else tuple(float(fallback_width) for _ in points)
            )
            # Per-curve authoring is recorded while drawing from the native brush
            # `gpencil_settings.stroke_type`. This lets one GP mask contain
            # independent line, fill and both strokes.  The UI source acts as the
            # default for newly authored curves, not as a destructive global
            # reinterpretation of old curves.
            fill_candidate = bool(len(points) >= 3)
            authored_fill_candidate = bool(authored_fill and len(points) >= 3)
            can_fill_auto = bool(authored_fill_candidate and (cyclic or authored_fill))
            can_line = bool(len(points) > 0)
            if stroke_mode == "FILL":
                use_fill = fill_candidate
                use_line = False
            elif stroke_mode == "STROKE":
                use_fill = False
                use_line = can_line
            elif stroke_mode == "BOTH":
                use_fill = fill_candidate
                use_line = can_line
            else:  # AUTO
                use_fill = can_fill_auto
                use_line = bool((authored_line and can_line) or (can_line and not use_fill))
            if not (use_fill or use_line):
                continue
            fill_key = None
            if use_fill:
                fill_group_counter += 1
                fill_key = _stroke_fill_group(stroke, fill_group_counter)
                # GPv3 Fill can visually close a non-cyclic stroke through the
                # material/fill tool.  Raster fill must receive an explicitly
                # closed contour; Line/Both still keep the original open stroke
                # for the variable-radius line component.
                if len(points) >= 3 and not cyclic:
                    fill_points = tuple(points) + (points[0],)
                else:
                    fill_points = tuple(points)
                fill_groups_by_key.setdefault(fill_key, []).append(fill_points)
            if use_line:
                if material_stroke_mode == "DOTS":
                    # Blender 5.2's dot materials stamp disconnected disks;
                    # joining the control points produced a completely
                    # different mask. A one-point polyline rasterizes as one
                    # native-radius disk in both mask backends.
                    polylines.extend(((point,), False, (radii[index],)) for index, point in enumerate(points))
                elif material_stroke_mode == "BOX":
                    # Square stroke stamps are filled contours rather than a
                    # continuous polyline. This follows the new material mode
                    # while keeping the backend-neutral geometry contract.
                    for index, point in enumerate(points):
                        radius = max(1.0e-6, float(radii[index]))
                        x, y = point
                        fill_group_counter += 1
                        square = (
                            (x - radius, y - radius), (x + radius, y - radius),
                            (x + radius, y + radius), (x - radius, y + radius),
                            (x - radius, y - radius),
                        )
                        fill_groups_by_key.setdefault(("BOX", fill_group_counter), []).append(square)
                else:
                    polylines.append((points, cyclic, radii))
            strokes_out.append(FBPStrokeData(points, radii, cyclic, use_fill, use_line, fill_key))

    fill_groups = tuple(tuple(contours) for contours in fill_groups_by_key.values() if contours)
    return FBPMaskGeometry(
        strokes=tuple(strokes_out),
        fill_groups=fill_groups,
        polylines=tuple(polylines),
        bounds=bounds,
        frame=int(frame_number or 1),
    )
