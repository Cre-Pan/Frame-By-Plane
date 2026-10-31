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
# Plane name, stored so lookups survive a constraint whose target was cleared.
KEY_FOLLOW_PLANE = "fbp_follow_plane"

# Handles are white like Blender's own gizmos; a selected handle takes the
# theme's gizmo yellow (``handle_selected_color``), with this as the fallback.
HANDLE_COLOR = (0.96, 0.96, 0.96, 1.0)
HANDLE_SELECTED_COLOR = (0.96, 0.945, 0.3, 1.0)
# Diffuse colour of the shared handle material (Solid shading, Material colour).
HANDLE_MATERIAL_COLOR = (0.96, 0.96, 0.96, 0.9)
HANDLE_OUTLINE_COLOR = (0.0, 0.0, 0.0, 0.45)
STOP_RING_COLOR = (1.0, 1.0, 1.0, 1.0)
GUIDE_COLOR = (1.0, 1.0, 1.0, 0.9)
GUIDE_OUTLINE_COLOR = (0.0, 0.0, 0.0, 0.5)

_DATA_ERRORS = (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError)
_RING_SEGMENTS = 24
_ARROW_HALF_ANGLE = math.radians(40.0)

# Face parts of a handle mesh, stored in the ``PART_ATTRIBUTE`` face attribute.
PART_ATTRIBUTE = "fbp_handle_part"
PART_HANDLE = 0
PART_SWATCH = 1
PART_STOP_RING = 2


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


def open_arrow_points(start, end, stroke, head):
    """Outline of a line arrow along +X with an open V head, as one polygon.

    The shaft and the two arms of the V share one outline, so the handle has
    no inner edges and its rim reads as a single stroke.
    """
    start, end = float(start), float(end)
    half = max(float(stroke), 1.0e-6) * 0.5
    arm = max(float(head), half * 4.0)
    sin_a, cos_a = math.sin(_ARROW_HALF_ANGLE), math.cos(_ARROW_HALF_ANGLE)
    upper_normal = (sin_a, cos_a)
    upper_dir = (-cos_a, sin_a)

    def offset(normal_sign, along, mirror):
        x = end + normal_sign * half * upper_normal[0] + along * upper_dir[0]
        y = normal_sign * half * upper_normal[1] + along * upper_dir[1]
        return (x, -y if mirror else y)

    # Where the inner edge of each arm meets the shaft's edge.
    meet = half * (1.0 + cos_a) / sin_a
    shaft_end = end - half * sin_a - meet * cos_a
    shaft_start = min(start, shaft_end)
    return [
        (shaft_start, -half),
        (shaft_end, -half),
        offset(-1.0, arm, True),
        offset(1.0, arm, True),
        (end + half / sin_a, 0.0),
        offset(1.0, arm, False),
        offset(-1.0, arm, False),
        (shaft_end, half),
        (shaft_start, half),
    ]


def open_chevron_points(tip, stroke, head):
    """Just the open V of :func:`open_arrow_points`, pointing at +X."""
    outline = open_arrow_points(tip, tip, stroke, head)
    half = max(float(stroke), 1.0e-6) * 0.5
    return outline[2:7] + [(float(tip) - half / math.sin(_ARROW_HALF_ANGLE), 0.0)]


def append_arrow_geometry(verts, faces, start, end, thickness, head_length):
    """A line arrow along +X from ``start`` to ``end`` with an open V head."""
    append_polygon_geometry(verts, faces, open_arrow_points(start, end, thickness, head_length))


class HandleShape:
    """Faces tagged by part, plus loose edges that the overlay draws as guides.

    Parts: ``PART_HANDLE`` is the accent fill, ``PART_SWATCH`` is filled with
    the colour the control stands for (a gradient stop) and ``PART_STOP_RING``
    is the light ring around a swatch. Loose edges are thin guide lines (the
    line between gradient stops, dashed radius circles).
    """

    __slots__ = ("verts", "faces", "edges", "parts")

    def __init__(self):
        self.verts = []
        self.faces = []
        self.edges = []
        self.parts = []

    def _tag(self, start, part):
        self.parts.extend([int(part)] * (len(self.faces) - start))

    def polygon(self, points, part=None):
        start = len(self.faces)
        append_polygon_geometry(self.verts, self.faces, points)
        self._tag(start, PART_HANDLE if part is None else part)

    def rect(self, cx, cy, width, height, part=None):
        start = len(self.faces)
        append_rect_geometry(self.verts, self.faces, cx, cy, width, height)
        self._tag(start, PART_HANDLE if part is None else part)

    def ring(self, cx, cy, outer, inner, part=None, segments=_RING_SEGMENTS):
        start = len(self.faces)
        append_ring_geometry(self.verts, self.faces, cx, cy, outer, inner, segments)
        self._tag(start, PART_HANDLE if part is None else part)

    def disc(self, cx, cy, radius, part=None, segments=16):
        start = len(self.faces)
        append_disc_geometry(self.verts, self.faces, cx, cy, radius, segments)
        self._tag(start, PART_HANDLE if part is None else part)

    def polyline(self, points, *, closed=False):
        points = [(float(x), float(y)) for x, y in points]
        if len(points) < 2:
            return
        start = len(self.verts)
        self.verts.extend((x, y, 0.0) for x, y in points)
        count = len(points)
        self.edges.extend((start + i, start + i + 1) for i in range(count - 1))
        if closed and count > 2:
            self.edges.append((start + count - 1, start))

    def dashed(self, points, dash, gap, *, closed=False):
        """Dashes along a polyline, as loose edges."""
        for piece in dashed_pieces(points, dash, gap, closed=closed):
            self.polyline(piece)

    def map_xy(self, function):
        """Apply a 2D map to every vertex (used to cancel an object transform)."""
        self.verts = [(*function(x, y), z) for x, y, z in self.verts]
        return self


def dashed_pieces(points, dash, gap, *, closed=False):
    """Split a polyline into dash polylines of length ``dash`` every ``dash + gap``."""
    points = [(float(x), float(y)) for x, y in points]
    if closed and points:
        points = points + [points[0]]
    dash = max(float(dash), 1.0e-6)
    period = dash + max(float(gap), 0.0)
    pieces, current = [], []
    travelled = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        length = math.hypot(x2 - x1, y2 - y1)
        if length <= 1.0e-12:
            continue
        cursor = 0.0
        while cursor < length - 1.0e-12:
            phase = travelled % period
            in_dash = phase < dash
            step = min(length - cursor, (dash - phase) if in_dash else (period - phase))
            if step <= 1.0e-12:
                step = min(length - cursor, 1.0e-9)
            t0, t1 = cursor / length, (cursor + step) / length
            if in_dash:
                a = (x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0)
                b = (x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1)
                if not current:
                    current.append(a)
                current.append(b)
            elif current:
                pieces.append(current)
                current = []
            cursor += step
            travelled += step
    if len(current) >= 2:
        pieces.append(current)
    return pieces


def ellipse_points(cx, cy, rx, ry, segments=72):
    return [
        (cx + math.cos(math.tau * i / segments) * rx, cy + math.sin(math.tau * i / segments) * ry)
        for i in range(segments)
    ]


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
        # A short open chevron past the +X arm shows the rotation.
        append_polygon_geometry(
            verts, faces, open_chevron_points(arm + thickness * 2.2, thickness * 0.9, thickness * 2.4)
        )
    return verts, faces


def angle_handle_geometry(size):
    """A dot with a line arrow on +X; rotating the handle sets the angle."""
    size = max(float(size), 1.0e-6)
    thickness = size * 0.16
    verts, faces = [], []
    append_disc_geometry(verts, faces, 0.0, 0.0, size * 0.2)
    append_arrow_geometry(verts, faces, size * 0.26, size * 1.8, thickness, size * 0.5)
    return verts, faces


def direction_handle_geometry(size, length=1.0):
    """A line arrow on +X whose X scale is the effect distance.

    ``length`` is the object's current X scale: the head and the dot are drawn
    narrower along X by that factor so that, once scaled, they keep their shape
    instead of stretching into a long spike.
    """
    size = max(float(size), 1.0e-6)
    length = max(float(length), 1.0e-6)
    thickness = size * 0.16
    shape = HandleShape()
    shape.disc(0.0, 0.0, size * 0.2)
    shape.polygon(open_arrow_points(0.0, max(length, size * 0.9), thickness, size * 0.5))
    return shape.map_xy(lambda x, y: (x / length, y))


def vector_handle_geometry(size):
    """Two crossed line arrows on +Z, readable from any view, on a small ring."""
    size = max(float(size), 1.0e-6)
    length = size * 2.0
    thickness = size * 0.16
    verts, faces = [], []
    # The ring keeps the handle visible when the arrow points at the viewer.
    append_ring_geometry(verts, faces, 0.0, 0.0, size * 0.45, size * 0.45 - size * 0.18)
    outline = open_arrow_points(0.0, length, thickness, size * 0.5)
    for axis in (0, 1):
        start = len(verts)
        verts.extend(
            (across, 0.0, along) if axis == 0 else (0.0, across, along)
            for along, across in outline
        )
        faces.append(tuple(range(start, start + len(outline))))
    return verts, faces


def gradient_stop_geometry(size):
    """A colour stop: a swatch disc inside a light ring (Figma-style)."""
    size = max(float(size), 1.0e-6)
    outer = size * 0.62
    ring = size * 0.16
    shape = HandleShape()
    shape.ring(0.0, 0.0, outer, outer - ring, part=PART_STOP_RING, segments=32)
    shape.disc(0.0, 0.0, outer - ring, part=PART_SWATCH, segments=32)
    return shape


def range_bar_geometry(size):
    """IN/OUT boundary of a band: a hollow stop on the guide line."""
    size = max(float(size), 1.0e-6)
    outer = size * 0.5
    shape = HandleShape()
    shape.ring(0.0, 0.0, outer, outer - size * 0.16, part=PART_STOP_RING, segments=32)
    return shape


def range_center_geometry(size, reference, *, scale_x=1.0, radii=(), radial_angle=0.0, dash=None):
    """Guide line between IN and OUT with a small grip in the middle.

    The object's X scale stretches the line to the IN/OUT distance. The grip,
    and the dashed radius circles of a radial gradient, are drawn narrower
    along X by that scale so they keep their shape on screen.
    """
    size = max(float(size), 1.0e-6)
    reference = max(float(reference), 1.0e-6)
    scale_x = max(float(scale_x), 1.0e-6)
    shape = HandleShape()
    if radii:
        # Radial: the line runs from the centre to the outer radius.
        shape.polyline([(0.0, 0.0), (reference * 0.5, 0.0)])
    else:
        shape.polyline([(-reference * 0.5, 0.0), (reference * 0.5, 0.0)])
    grip = size * 0.32
    shape.polygon([
        (-grip / scale_x, 0.0), (0.0, -grip), (grip / scale_x, 0.0), (0.0, grip),
    ])
    if radii:
        dash = float(dash or size * 0.45)
        cos_a, sin_a = math.cos(radial_angle), math.sin(radial_angle)
        for rx, ry in radii:
            if rx <= 1.0e-6 or ry <= 1.0e-6:
                continue
            # The circle lives in plane space; the control is rotated by
            # ``radial_angle`` and scaled along X, so undo both.
            points = [
                ((x * cos_a + y * sin_a) / scale_x, -x * sin_a + y * cos_a)
                for x, y in ellipse_points(0.0, 0.0, rx, ry, 96)
            ]
            shape.dashed(points, dash, dash * 0.6, closed=True)
    return shape


def radius_handle_geometry(size, radii, center=(0.0, 0.0), dash=None):
    """A knob on the effect radius plus the dashed circles it controls.

    ``radii`` are plane-space ``(rx, ry)`` pairs around ``center``, given
    relative to the knob.
    """
    size = max(float(size), 1.0e-6)
    shape = HandleShape()
    shape.ring(0.0, 0.0, size * 0.36, size * 0.36 - size * 0.14, part=PART_STOP_RING, segments=24)
    shape.disc(0.0, 0.0, size * 0.36 - size * 0.14, segments=24)
    dash = float(dash or size * 0.45)
    for rx, ry in radii or ():
        if rx <= 1.0e-6 or ry <= 1.0e-6:
            continue
        shape.dashed(
            ellipse_points(float(center[0]), float(center[1]), rx, ry, 120),
            dash, dash * 0.6, closed=True,
        )
    return shape


def handle_selected_color(context=None):
    """The theme's gizmo yellow, so selected handles match Blender's gizmos."""
    try:
        theme = (context or bpy.context).preferences.themes[0]
        return (*tuple(theme.user_interface.gizmo_primary)[:3], 1.0)
    except (AttributeError, IndexError) + _DATA_ERRORS:
        return HANDLE_SELECTED_COLOR


def write_handle_mesh(mesh, geometry):
    """Replace ``mesh`` with handle geometry: a ``(verts, faces)`` pair or a HandleShape."""
    if isinstance(geometry, HandleShape):
        verts, faces, edges, parts = geometry.verts, geometry.faces, geometry.edges, geometry.parts
    else:
        verts, faces = geometry
        edges, parts = [], [PART_HANDLE] * len(faces)
    mesh.clear_geometry()
    mesh.from_pydata(verts, edges, faces)
    if any(parts):
        attribute = mesh.attributes.get(PART_ATTRIBUTE)
        if attribute is None or attribute.domain != "FACE" or attribute.data_type != "INT":
            if attribute is not None:
                mesh.attributes.remove(attribute)
            attribute = mesh.attributes.new(PART_ATTRIBUTE, "INT", "FACE")
        attribute.data.foreach_set("value", [int(part) for part in parts])
    else:
        attribute = mesh.attributes.get(PART_ATTRIBUTE)
        if attribute is not None:
            mesh.attributes.remove(attribute)
    mesh.update()


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
    target = HANDLE_MATERIAL_COLOR
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


__all__ = [
    "BOUNDS_HANDLE_ROLES",
    "FOLLOW_CONSTRAINT",
    "LATTICE_FOLLOW_MODIFIER",
    "HANDLE_COLOR",
    "HANDLE_SELECTED_COLOR",
    "HANDLE_MATERIAL_COLOR",
    "handle_selected_color",
    "HANDLE_OUTLINE_COLOR",
    "STOP_RING_COLOR",
    "GUIDE_COLOR",
    "GUIDE_OUTLINE_COLOR",
    "PART_ATTRIBUTE",
    "PART_HANDLE",
    "PART_SWATCH",
    "PART_STOP_RING",
    "HandleShape",
    "dashed_pieces",
    "ellipse_points",
    "open_arrow_points",
    "open_chevron_points",
    "write_handle_mesh",
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
    "gradient_stop_geometry",
    "radius_handle_geometry",
    "ensure_viewport_handle_material",
    "follow_constraint",
    "attached_plane",
    "attach_to_plane",
    "is_attached_to",
    "plane_followers",
    "plane_lattice_modifier",
    "sync_lattice_follow",
]
