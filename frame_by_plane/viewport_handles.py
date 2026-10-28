"""Shared viewport handle geometry and plane binding for spatial controls.

Handles are small flat meshes in the plane's local XY space. They follow the
plane through a collapsed Child Of constraint instead of a parent, because
Blender draws a dashed relationship line from every child to its parent but
none for a constraint whose panel is collapsed. When the plane is deformed by
the Lattice effect, every handle gets the same Lattice modifier, so it bends
with the drawing and stays on the plane's real (tilted) edges.

The handle meshes are the selectable part. ``handle_overlay`` draws the visible
part on top of everything, in every shading mode.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix


BOUNDS_HANDLE_ROLES = (
    "LEFT", "RIGHT", "TOP", "BOTTOM",
    "TOP_LEFT", "TOP_RIGHT", "BOTTOM_LEFT", "BOTTOM_RIGHT",
)

FOLLOW_CONSTRAINT = "FBP Follow Plane"
LATTICE_FOLLOW_MODIFIER = "FBP • Follow Lattice"
# Marks objects that the handle overlay draws.
KEY_OVERLAY_HANDLE = "fbp_overlay_handle"
# Plane name, stored so lookups survive a constraint whose target was cleared.
KEY_FOLLOW_PLANE = "fbp_follow_plane"

# One accent for every handle; selection is shown by a lighter fill.
HANDLE_COLOR = (1.0, 0.55, 0.05, 1.0)
HANDLE_SELECTED_COLOR = (1.0, 0.86, 0.6, 1.0)
HANDLE_OUTLINE_COLOR = (0.0, 0.0, 0.0, 0.45)

_DATA_ERRORS = (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError)
_RING_SEGMENTS = 24


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


def append_polygon_geometry(verts, faces, points):
    start = len(verts)
    verts.extend((float(x), float(y), 0.0) for x, y in points)
    faces.append(tuple(range(start, start + len(points))))


def append_ring_geometry(verts, faces, cx, cy, outer, inner, segments=_RING_SEGMENTS):
    """A flat annulus made of quads."""
    start = len(verts)
    for index in range(segments):
        angle = math.tau * index / segments
        c, s = math.cos(angle), math.sin(angle)
        verts.append((cx + c * outer, cy + s * outer, 0.0))
        verts.append((cx + c * inner, cy + s * inner, 0.0))
    for index in range(segments):
        a = start + index * 2
        b = start + ((index + 1) % segments) * 2
        faces.append((a, b, b + 1, a + 1))


def append_disc_geometry(verts, faces, cx, cy, radius, segments=16):
    append_polygon_geometry(verts, faces, [
        (cx + math.cos(math.tau * i / segments) * radius, cy + math.sin(math.tau * i / segments) * radius)
        for i in range(segments)
    ])


def append_arrow_geometry(verts, faces, start, end, thickness, head_length, head_width):
    """A straight arrow along +X from ``start`` to ``end`` (head included)."""
    shaft_end = max(float(start), float(end) - float(head_length))
    if shaft_end > start:
        append_rect_geometry(verts, faces, (start + shaft_end) * 0.5, 0.0, shaft_end - start, thickness)
    append_polygon_geometry(verts, faces, [
        (shaft_end, -head_width * 0.5), (end, 0.0), (shaft_end, head_width * 0.5),
    ])


def bounds_handle_geometry(size, role):
    """Return a thin side bar or an L corner for Crop/Extend-style bounds.

    Corners open towards the inside of the rectangle, so they read as the
    corners of the frame they edit.
    """
    role = str(role or "").upper()
    size = max(float(size), 1.0e-6)
    thickness = max(size * 0.24, 0.002)
    side_length = max(size * 2.2, thickness * 3.0)
    corner_length = max(size * 1.3, thickness * 3.0)
    verts = []
    faces = []

    if role in {"TOP", "BOTTOM"}:
        append_rect_geometry(verts, faces, 0.0, 0.0, side_length, thickness)
    elif role in {"LEFT", "RIGHT"}:
        append_rect_geometry(verts, faces, 0.0, 0.0, thickness, side_length)
    else:
        sx = -1.0 if "RIGHT" in role else 1.0
        sy = -1.0 if "TOP" in role else 1.0
        half = thickness * 0.5
        # Two arms sharing the corner square, without overlapping faces.
        append_polygon_geometry(verts, faces, [
            (-sx * half, -sy * half),
            (sx * corner_length, -sy * half),
            (sx * corner_length, sy * half),
            (sx * half, sy * half),
            (sx * half, sy * corner_length),
            (-sx * half, sy * corner_length),
        ] if sx * sy > 0 else [
            (-sx * half, -sy * half),
            (-sx * half, sy * corner_length),
            (sx * half, sy * corner_length),
            (sx * half, sy * half),
            (sx * corner_length, sy * half),
            (sx * corner_length, -sy * half),
        ])
    return verts, faces


def point_handle_geometry(size, *, with_angle=False):
    """Ring with a centre dot; a tick on +X shows the rotation when it matters."""
    size = max(float(size), 1.0e-6)
    outer = size * 0.5
    thickness = size * 0.18
    verts, faces = [], []
    append_ring_geometry(verts, faces, 0.0, 0.0, outer, outer - thickness)
    append_disc_geometry(verts, faces, 0.0, 0.0, size * 0.12)
    if with_angle:
        append_rect_geometry(verts, faces, outer + size * 0.25, 0.0, size * 0.5, thickness)
    return verts, faces


def offset_handle_geometry(size, *, with_angle=False):
    """A small cross: the offset of a grid or a shadow."""
    size = max(float(size), 1.0e-6)
    thickness = size * 0.18
    arm = size * 0.55
    verts, faces = [], []
    append_rect_geometry(verts, faces, 0.0, 0.0, arm * 2.0, thickness)
    append_rect_geometry(verts, faces, 0.0, (arm + thickness * 0.5) * 0.5, thickness, arm - thickness * 0.5)
    append_rect_geometry(verts, faces, 0.0, -(arm + thickness * 0.5) * 0.5, thickness, arm - thickness * 0.5)
    if with_angle:
        append_polygon_geometry(verts, faces, [
            (arm, -thickness * 1.6), (arm + thickness * 2.4, 0.0), (arm, thickness * 1.6),
        ])
    return verts, faces


def angle_handle_geometry(size):
    """A dot with an arrow on +X; rotating the handle sets the angle."""
    size = max(float(size), 1.0e-6)
    thickness = size * 0.18
    verts, faces = [], []
    append_disc_geometry(verts, faces, 0.0, 0.0, size * 0.2)
    append_arrow_geometry(verts, faces, size * 0.26, size * 1.8, thickness, size * 0.45, size * 0.5)
    return verts, faces


def direction_handle_geometry(size):
    """A unit-long arrow on +X: the object's X scale is the effect distance."""
    size = max(float(size), 1.0e-6)
    thickness = size * 0.18
    verts, faces = [], []
    append_disc_geometry(verts, faces, 0.0, 0.0, size * 0.2)
    append_arrow_geometry(verts, faces, 0.0, 1.0, thickness, 0.22, size * 0.5)
    return verts, faces


def vector_handle_geometry(size):
    """Two crossed flat arrows on +Z, readable from any view, on a small ring."""
    size = max(float(size), 1.0e-6)
    length = size * 2.0
    thickness = size * 0.18
    head = size * 0.5
    verts, faces = [], []
    # The ring keeps the handle visible when the arrow points at the viewer.
    append_ring_geometry(verts, faces, 0.0, 0.0, size * 0.45, size * 0.45 - thickness)
    shaft = length - head * 0.9
    for axis in (0, 1):
        def point(across, along):
            return (across, 0.0, along) if axis == 0 else (0.0, across, along)
        start = len(verts)
        verts.extend(point(a, b) for a, b in (
            (-thickness * 0.5, 0.0), (thickness * 0.5, 0.0),
            (thickness * 0.5, shaft), (-thickness * 0.5, shaft),
        ))
        faces.append((start, start + 1, start + 2, start + 3))
        start = len(verts)
        verts.extend(point(a, b) for a, b in ((-head * 0.5, shaft), (head * 0.5, shaft), (0.0, length)))
        faces.append((start, start + 1, start + 2))
    return verts, faces


def range_bar_geometry(size):
    """IN/OUT boundary of a gradient or tilt-shift band: a bar across it."""
    size = max(float(size), 1.0e-6)
    thickness = max(size * 0.24, 0.002)
    verts, faces = [], []
    append_rect_geometry(verts, faces, 0.0, 0.0, thickness, max(size * 2.6, thickness * 3.0))
    return verts, faces


def range_center_geometry(size, reference):
    """Thin connector between IN and OUT with a small grip in the middle.

    The object's X scale stretches the connector to the IN/OUT distance, so the
    grip is drawn narrower along X to stay readable at the usual scales.
    """
    size = max(float(size), 1.0e-6)
    reference = max(float(reference), 1.0e-6)
    verts, faces = [], []
    append_rect_geometry(verts, faces, 0.0, 0.0, reference, max(size * 0.1, 0.001))
    grip = size * 0.45
    append_polygon_geometry(verts, faces, [
        (-grip * 0.5, 0.0), (0.0, -grip), (grip * 0.5, 0.0), (0.0, grip),
    ])
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


# --- Plane binding ---------------------------------------------------------

def follow_constraint(obj):
    try:
        constraint = obj.constraints.get(FOLLOW_CONSTRAINT)
    except _DATA_ERRORS:
        return None
    return constraint if getattr(constraint, "type", "") == "CHILD_OF" else None


def attached_plane(obj):
    """Return the plane a handle follows (constraint target, or legacy parent)."""
    if obj is None:
        return None
    constraint = follow_constraint(obj)
    target = getattr(constraint, "target", None) if constraint is not None else None
    if target is not None:
        return target
    parent = getattr(obj, "parent", None)
    if parent is not None:
        return parent
    try:
        name = str(obj.get(KEY_FOLLOW_PLANE, "") or "")
    except _DATA_ERRORS:
        return None
    return bpy.data.objects.get(name) if name else None


def attach_to_plane(obj, plane):
    """Make ``obj`` follow ``plane`` in its local space, without a parent.

    The local transform keeps its meaning: with an identity inverse, Child Of
    applies the plane's world matrix exactly like a parent with an identity
    parent inverse. Only changed values are written.
    """
    if obj is None or plane is None:
        return False
    changed = False
    try:
        parent = getattr(obj, "parent", None)
        if parent is not None:
            # Keep the world placement, expressed in the plane's local space.
            # For the usual identity parent inverse this is the same basis.
            world = parent.matrix_world @ obj.matrix_parent_inverse @ obj.matrix_basis
            obj.parent = None
            obj.matrix_basis = plane.matrix_world.inverted_safe() @ world
            changed = True
        constraint = follow_constraint(obj)
        if constraint is None:
            stale = obj.constraints.get(FOLLOW_CONSTRAINT)
            if stale is not None:
                obj.constraints.remove(stale)
            constraint = obj.constraints.new(type="CHILD_OF")
            constraint.name = FOLLOW_CONSTRAINT
            changed = True
        if constraint.target is not plane:
            constraint.target = plane
            changed = True
        if not constraint.inverse_matrix.is_identity:
            constraint.inverse_matrix = Matrix.Identity(4)
            changed = True
        if bool(getattr(constraint, "set_inverse_pending", False)):
            constraint.set_inverse_pending = False
            changed = True
        # A collapsed constraint draws no relationship line.
        if bool(constraint.show_expanded):
            constraint.show_expanded = False
            changed = True
        # Follow last, after any limit constraint that works in plane space.
        constraints = obj.constraints
        index = constraints.find(FOLLOW_CONSTRAINT)
        if index != len(constraints) - 1:
            constraints.move(index, len(constraints) - 1)
            changed = True
        if str(obj.get(KEY_FOLLOW_PLANE, "") or "") != plane.name:
            obj[KEY_FOLLOW_PLANE] = plane.name
            _FOLLOWER_CACHE.pop(plane.name, None)
            changed = True
    except _DATA_ERRORS:
        return changed
    return changed


_FOLLOWER_CACHE = {}


def plane_followers(plane):
    """Objects that follow ``plane`` through the constraint (and its children).

    Replaces ``plane.children`` for handle lookups. The scan is cached per
    plane until the number of objects in the file changes or a cached object
    disappears.
    """
    if plane is None:
        return ()
    try:
        name = plane.name
        children = tuple(plane.children)
        count = len(bpy.data.objects)
    except _DATA_ERRORS:
        return ()
    def follows(obj):
        if obj is None or obj.parent is not None:
            return False
        if str(obj.get(KEY_FOLLOW_PLANE, "") or "") == name:
            return True
        constraint = follow_constraint(obj)
        return constraint is not None and constraint.target is plane

    cached = _FOLLOWER_CACHE.get(name)
    followers = None
    if cached is not None and cached[0] == count:
        followers = tuple(bpy.data.objects.get(item) for item in cached[1])
        if not all(follows(obj) for obj in followers):
            followers = None
    if followers is None:
        followers = tuple(obj for obj in bpy.data.objects if follows(obj))
        if len(_FOLLOWER_CACHE) > 256:
            _FOLLOWER_CACHE.clear()
        _FOLLOWER_CACHE[name] = (count, tuple(obj.name for obj in followers))
    return children + tuple(obj for obj in followers if obj not in children)


def forget_plane_followers():
    _FOLLOWER_CACHE.clear()


def is_attached_to(obj, plane):
    constraint = follow_constraint(obj)
    try:
        return bool(
            constraint is not None
            and constraint.target is plane
            and getattr(obj, "parent", None) is None
            and constraint.inverse_matrix.is_identity
            and not bool(constraint.show_expanded)
            and str(obj.get(KEY_FOLLOW_PLANE, "") or "") == plane.name
        )
    except _DATA_ERRORS:
        return False


def plane_lattice_modifier(plane):
    """The plane's own Lattice modifier, if the Lattice effect is on."""
    for modifier in tuple(getattr(plane, "modifiers", ()) or ()):
        try:
            if modifier.type == "LATTICE" and modifier.name.startswith("FBP • Lattice") and modifier.object is not None:
                return modifier
        except _DATA_ERRORS:
            continue
    return None


def sync_lattice_follow(obj, plane, *, enabled=True):
    """Give a handle mesh the plane's Lattice deformation, or remove it."""
    if obj is None or str(getattr(obj, "type", "") or "") != "MESH":
        return False
    source = plane_lattice_modifier(plane) if (plane is not None and enabled) else None
    changed = False
    try:
        modifier = obj.modifiers.get(LATTICE_FOLLOW_MODIFIER)
        if source is None:
            if modifier is not None:
                obj.modifiers.remove(modifier)
                changed = True
            return changed
        if modifier is None or modifier.type != "LATTICE":
            if modifier is not None:
                obj.modifiers.remove(modifier)
            modifier = obj.modifiers.new(LATTICE_FOLLOW_MODIFIER, "LATTICE")
            changed = True
        if modifier.object is not source.object:
            modifier.object = source.object
            changed = True
        if abs(float(modifier.strength) - float(source.strength)) > 1.0e-7:
            modifier.strength = float(source.strength)
            changed = True
        if bool(modifier.show_viewport) != bool(source.show_viewport):
            modifier.show_viewport = bool(source.show_viewport)
            changed = True
    except _DATA_ERRORS:
        return changed
    return changed


def mark_overlay_handle(obj):
    try:
        if not bool(obj.get(KEY_OVERLAY_HANDLE, False)):
            obj[KEY_OVERLAY_HANDLE] = True
            return True
    except _DATA_ERRORS:
        pass
    return False


__all__ = [
    "BOUNDS_HANDLE_ROLES",
    "FOLLOW_CONSTRAINT",
    "LATTICE_FOLLOW_MODIFIER",
    "KEY_OVERLAY_HANDLE",
    "HANDLE_COLOR",
    "HANDLE_SELECTED_COLOR",
    "HANDLE_OUTLINE_COLOR",
    "rect_vertices",
    "append_rect_geometry",
    "append_polygon_geometry",
    "append_ring_geometry",
    "append_disc_geometry",
    "append_arrow_geometry",
    "bounds_handle_geometry",
    "point_handle_geometry",
    "offset_handle_geometry",
    "angle_handle_geometry",
    "direction_handle_geometry",
    "vector_handle_geometry",
    "range_bar_geometry",
    "range_center_geometry",
    "ensure_viewport_handle_material",
    "follow_constraint",
    "attached_plane",
    "attach_to_plane",
    "is_attached_to",
    "plane_followers",
    "forget_plane_followers",
    "plane_lattice_modifier",
    "sync_lattice_follow",
    "mark_overlay_handle",
]
