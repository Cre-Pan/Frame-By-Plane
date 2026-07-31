"""Shared flat viewport handle geometry used by bounds-based controls."""

from __future__ import annotations

import bpy


BOUNDS_HANDLE_ROLES = (
    "LEFT", "RIGHT", "TOP", "BOTTOM",
    "TOP_LEFT", "TOP_RIGHT", "BOTTOM_LEFT", "BOTTOM_RIGHT",
)


def rect_vertices(cx, cy, width, height):
    hw = max(float(width), 1.0e-6) * 0.5
    hh = max(float(height), 1.0e-6) * 0.5
    return [
        (cx - hw, cy - hh, 0.0),
        (cx + hw, cy - hh, 0.0),
        (cx + hw, cy + hh, 0.0),
        (cx - hw, cy + hh, 0.0),
    ]


def append_rect_geometry(verts, faces, cx, cy, width, height):
    start = len(verts)
    verts.extend(rect_vertices(cx, cy, width, height))
    faces.append((start, start + 1, start + 2, start + 3))


def bounds_handle_geometry(size, role):
    """Return the Crop/Extend-style bar or L-corner mesh.

    Every handle has a compact square grip at its mathematical anchor.  The
    extra grip keeps side centres and L-shaped corners readable when a crop
    collapses to only a few pixels and their bars would otherwise overlap.
    """
    role = str(role or "").upper()
    size = max(float(size), 1.0e-6)
    thickness = max(size * 0.28, 0.004)
    side_length = max(size * 2.85, thickness * 3.0)
    corner_length = max(size * 1.85, thickness * 3.0)
    verts = []
    faces = []

    if role in {"TOP", "BOTTOM"}:
        append_rect_geometry(verts, faces, 0.0, 0.0, side_length, thickness)
    elif role in {"LEFT", "RIGHT"}:
        append_rect_geometry(verts, faces, 0.0, 0.0, thickness, side_length)
    else:
        sx = -1.0 if "RIGHT" in role else 1.0
        sy = -1.0 if "TOP" in role else 1.0
        append_rect_geometry(verts, faces, sx * corner_length * 0.5, 0.0, corner_length, thickness)
        append_rect_geometry(verts, faces, 0.0, sy * corner_length * 0.5, thickness, corner_length)
    grip = max(size * 0.58, thickness * 1.45)
    append_rect_geometry(verts, faces, 0.0, 0.0, grip, grip)
    return verts, faces


def ensure_viewport_handle_material():
    """Return the shared handle material without invalidating shading when unchanged.

    Blender tags a Material for shading recalculation on every RNA assignment,
    including assigning the same diffuse color again. Shape Mask maintenance
    calls this helper periodically, so changed-only writes are mandatory for a
    stable Cycles progressive viewport.
    """
    material = bpy.data.materials.get("FBP Viewport Control Handle")
    if material is None:
        material = bpy.data.materials.new("FBP Viewport Control Handle")
    target = (1.0, 0.55, 0.05, 0.9)
    try:
        current = tuple(float(value) for value in material.diffuse_color)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        current = ()
    if len(current) != len(target) or any(
        abs(left - right) > 1.0e-7 for left, right in zip(current, target, strict=False)
    ):
        material.diffuse_color = target
    return material


__all__ = [
    "BOUNDS_HANDLE_ROLES",
    "rect_vertices",
    "append_rect_geometry",
    "bounds_handle_geometry",
    "ensure_viewport_handle_material",
]
