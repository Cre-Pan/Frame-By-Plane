"""Small helpers shared by many Frame By Plane modules.

Each helper used to be copied into the modules that needed it (text
cleaning, unique names, Undo steps, the UI scale, view rays). They live here
once so a fix reaches every caller.
"""

from __future__ import annotations

import json

import bpy
from mathutils import Vector

from .runtime import FBP_DATA_ERRORS


# -- Text and names ---------------------------------------------------------

def safe_text(value) -> str:
    """``value`` as stripped text, or ``""`` when it cannot be read."""
    try:
        return str(value or "").strip()
    except FBP_DATA_ERRORS:
        return ""


def canonical_json(value) -> str:
    """Stable compact JSON: sorted keys, no spaces, Unicode kept."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def unique_name(existing, base, *, casefold=False) -> str:
    """``base``, or ``base 2``, ``base 3``... the first one not in ``existing``.

    ``casefold`` compares names without case, as the Scene libraries do.
    """
    fold = str.casefold if casefold else (lambda text: text)
    taken = {fold(str(name)) for name in existing}
    if fold(base) not in taken:
        return base
    number = 2
    while fold(f"{base} {number}") in taken:
        number += 1
    return f"{base} {number}"


def rna_pointer(value) -> int:
    """Memory address of an RNA struct, or 0 when it is gone."""
    try:
        return int(value.as_pointer()) if value is not None else 0
    except FBP_DATA_ERRORS:
        return 0


# -- Interface --------------------------------------------------------------

def ui_scale(context) -> float:
    """Preferences > Interface > Resolution Scale (1.0 when unreadable)."""
    try:
        return float(context.preferences.system.ui_scale) or 1.0
    except FBP_DATA_ERRORS:
        return 1.0


def undo_push(message: str) -> None:
    """One Undo step named ``message``; silently skipped where Undo is off."""
    try:
        bpy.ops.ed.undo_push(message=message)
    except RuntimeError:
        pass


_UNIFORM_COLOR_SHADER = None


def uniform_color_shader():
    """Blender's built-in flat colour shader, created once."""
    global _UNIFORM_COLOR_SHADER
    if _UNIFORM_COLOR_SHADER is None:
        import gpu
        _UNIFORM_COLOR_SHADER = gpu.shader.from_builtin("UNIFORM_COLOR")
    return _UNIFORM_COLOR_SHADER


# -- Viewport rays ----------------------------------------------------------

def view_ray(region, region_data, coord):
    """World ``(origin, direction)`` of the view ray under a region pixel.

    In orthographic views (including an orthographic camera) Blender's
    ``region_2d_to_origin_3d`` can place the origin beyond the scene, so the
    ray would start behind every plane. The origin is taken on the near clip
    plane instead, so the ray covers everything the view shows.
    """
    from bpy_extras import view3d_utils

    direction = view3d_utils.region_2d_to_vector_3d(region, region_data, coord)
    if bool(getattr(region_data, "is_perspective", True)):
        return view3d_utils.region_2d_to_origin_3d(region, region_data, coord), direction
    x = 2.0 * float(coord[0]) / max(1.0, float(region.width)) - 1.0
    y = 2.0 * float(coord[1]) / max(1.0, float(region.height)) - 1.0
    near = region_data.perspective_matrix.inverted_safe() @ Vector((x, y, -1.0, 1.0))
    if abs(near.w) > 1e-12:
        near = near / near.w
    return near.to_3d(), direction


def view_plane_hit(region, region_data, coord, point, normal):
    """Where the view ray under ``coord`` meets the plane through ``point``.

    ``None`` when the ray runs parallel to the plane or the view is gone.
    """
    try:
        origin, direction = view_ray(region, region_data, coord)
    except (ImportError,) + FBP_DATA_ERRORS:
        return None
    normal = Vector(normal)
    if normal.length <= 1.0e-12 or direction.length <= 1.0e-12:
        return None
    normal = normal.normalized()
    direction = direction.normalized()
    point = Vector(point)
    denominator = direction.dot(normal)
    if abs(denominator) >= GRAZING_COSINE:
        return origin + direction * ((point - origin).dot(normal) / denominator)
    # The plane is (nearly) edge-on, as a front-facing layer in Top or Side
    # view: the ray meets it far away or never. Take the cursor on the plane
    # facing the view through ``point`` instead and drop it onto the plane,
    # so a drag follows the line the plane draws on screen.
    facing = view_plane_point(region, region_data, coord, point)
    if facing is None:
        return None
    return facing - normal * (facing - point).dot(normal)


# Below this cosine between the view ray and a plane's normal (about 84
# degrees) the plane counts as seen edge-on.
GRAZING_COSINE = 0.1


def view_axes(region_data):
    """World ``(right, up, toward_viewer)`` unit axes of a 3D view."""
    rotation = region_data.view_matrix.inverted_safe().to_3x3()
    return (
        (rotation @ Vector((1.0, 0.0, 0.0))).normalized(),
        (rotation @ Vector((0.0, 1.0, 0.0))).normalized(),
        (rotation @ Vector((0.0, 0.0, 1.0))).normalized(),
    )


def view_direction_at(region_data, point):
    """Unit direction the view looks along at ``point`` (from the eye)."""
    _right, _up, toward = view_axes(region_data)
    if bool(getattr(region_data, "is_perspective", True)):
        eye = region_data.view_matrix.inverted_safe().translation
        direction = Vector(point) - eye
        if direction.length > 1.0e-9:
            return direction.normalized()
    return -toward


def view_plane_point(region, region_data, coord, point):
    """Where the ray under ``coord`` meets the plane facing the view at ``point``."""
    try:
        origin, direction = view_ray(region, region_data, coord)
        _right, _up, toward = view_axes(region_data)
    except (ImportError,) + FBP_DATA_ERRORS:
        return None
    denominator = direction.dot(toward)
    if abs(denominator) <= 1.0e-12:
        return None
    return origin + direction * ((Vector(point) - origin).dot(toward) / denominator)


def world_per_pixel(region, region_data, point):
    """World length of one screen pixel at ``point``, or None off screen."""
    from bpy_extras.view3d_utils import location_3d_to_region_2d

    right = view_axes(region_data)[0]
    point = Vector(point)
    start = location_3d_to_region_2d(region, region_data, point)
    end = location_3d_to_region_2d(region, region_data, point + right)
    if start is None or end is None:
        return None
    length = (end - start).length
    return 1.0 / length if length > 1.0e-9 else None


def edge_on(region_data, point, normal, limit=GRAZING_COSINE):
    """True when a plane through ``point`` with ``normal`` is seen edge-on."""
    normal = Vector(normal)
    if normal.length <= 1.0e-12:
        return True
    return abs(view_direction_at(region_data, point).dot(normal.normalized())) < limit


__all__ = (
    "canonical_json",
    "rna_pointer",
    "safe_text",
    "ui_scale",
    "undo_push",
    "uniform_color_shader",
    "unique_name",
    "view_plane_hit",
    "view_axes",
    "view_direction_at",
    "view_plane_point",
    "world_per_pixel",
    "edge_on",
    "GRAZING_COSINE",
    "view_ray",
)
