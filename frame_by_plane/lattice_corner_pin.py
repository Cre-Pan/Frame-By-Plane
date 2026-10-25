"""Corner Pin for the Lattice (Deform Plane) effect, like After Effects.

Four handles sit on the layer's corners. Moving them maps the layer onto the
new quad with a true perspective (projective) transform, so the drawing
foreshortens towards the far side instead of only shearing. The transform is
written into the rest cage, like Camera Flatten: poses, pins and bones still
work on top. The cage is linear and dense enough that its piecewise-linear
surface follows the projective map closely.

Handles live in the plane frame and keyframe like any object. The cage is
rewritten when a handle moves and on every frame change, so animated corners
also render (the add-on must be enabled).
"""

from __future__ import annotations

import bpy
from mathutils import Vector

from .lattice_pins import new_controller
from .runtime import FBP_DATA_ERRORS


CORNER_OWNER_KEY = "fbp_lattice_corner_owner"
CORNER_ROLE_KEY = "fbp_lattice_corner"
SIGNATURE_KEY = "fbp_lattice_corner_signature"
# Cage corner order: counter-clockwise from the bottom left.
ROLES = (
    ("BL", "Bottom Left", (-0.5, -0.5)),
    ("BR", "Bottom Right", (0.5, -0.5)),
    ("TR", "Top Right", (0.5, 0.5)),
    ("TL", "Top Left", (-0.5, 0.5)),
)
# Minimum cage points per axis for a smooth perspective.
MIN_POINTS = 12


def is_corner_handle(obj):
    try:
        return bool(obj is not None and str(obj.get(CORNER_ROLE_KEY, "") or ""))
    except FBP_DATA_ERRORS:
        return False


def corner_owner(obj):
    if not is_corner_handle(obj):
        return None
    parent = getattr(obj, "parent", None)
    if parent is not None and bool(getattr(parent, "is_fbp_control", False)):
        return parent
    owner = bpy.data.objects.get(str(obj.get(CORNER_OWNER_KEY, "") or ""))
    return owner if owner is not None and bool(getattr(owner, "is_fbp_control", False)) else None


def corner_handles(rig):
    """Return {role: handle} for a layer."""
    result = {}
    if rig is None:
        return result
    try:
        for obj in tuple(getattr(rig, "children", ()) or ()):
            if is_corner_handle(obj):
                result[str(obj.get(CORNER_ROLE_KEY))] = obj
    except FBP_DATA_ERRORS:
        return {}
    return result


def ensure_handles(rig, helper, plane):
    """Create missing corner handles on the cage corners. Return {role: handle}."""
    handles = corner_handles(rig)
    for role, label, (x, y) in ROLES:
        if role in handles:
            continue
        world = helper.matrix_world @ Vector((x, y, 0.0))
        handle, _local = new_controller(
            rig, helper, plane, f"Corner {label} • {rig.name}", world, display='CUBE', size=0.7,
        )
        handle[CORNER_OWNER_KEY] = str(rig.name)
        handle[CORNER_ROLE_KEY] = role
        # Corners only move; perspective comes from where they are.
        handle.lock_rotation = (True, True, True)
        handle.lock_scale = (True, True, True)
        handles[role] = handle
    return handles


def reset_handles(rig, helper):
    handles = corner_handles(rig)
    to_handle_space = {}
    for role, _label, (x, y) in ROLES:
        handle = handles.get(role)
        if handle is None:
            continue
        cage_to_frame = _cage_to_frame(helper, handle)
        point = cage_to_frame @ Vector((x, y, 0.0))
        handle.location = (point.x, point.y, 0.0)
        to_handle_space[role] = point
    return to_handle_space


def remove_handles(rig):
    changed = False
    owner_name = str(getattr(rig, "name", "") or "")
    targets = list(corner_handles(rig).values())
    try:
        for obj in tuple(bpy.data.objects):
            if obj not in targets and is_corner_handle(obj) and str(obj.get(CORNER_OWNER_KEY, "") or "") == owner_name:
                targets.append(obj)
    except FBP_DATA_ERRORS:
        pass
    for obj in targets:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            changed = True
        except FBP_DATA_ERRORS:
            continue
    return changed


def _cage_to_frame(helper, handle):
    """Matrix from cage coordinates to a handle's parent (frame) space.

    Both are children of the layer rig, so the rig's own world matrix cancels:
    this stays exact while the rig animates, even before a depsgraph update.
    """
    cage_in_rig = helper.matrix_parent_inverse @ helper.matrix_basis
    frame_in_rig = handle.matrix_parent_inverse
    return frame_in_rig.inverted_safe() @ cage_in_rig


def corner_targets(rig, helper):
    """Return the four handle positions in cage coordinates, in ROLES order."""
    handles = corner_handles(rig)
    result = []
    for role, _label, _rest in ROLES:
        handle = handles.get(role)
        if handle is None:
            return None
        frame_to_cage = _cage_to_frame(helper, handle).inverted_safe()
        point = frame_to_cage @ Vector(tuple(handle.location))
        result.append((float(point.x), float(point.y)))
    return result


def homography(source, target):
    """3×3 projective map sending four source points to four target points."""
    import numpy as np
    rows = []
    values = []
    for (x, y), (u, v) in zip(source, target):
        rows.append((x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y))
        rows.append((0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y))
        values.extend((u, v))
    solution = np.linalg.solve(np.array(rows, dtype=np.float64), np.array(values, dtype=np.float64))
    return np.append(solution, 1.0).reshape(3, 3)


def cage_coordinates(points_u, points_v, targets):
    """Rest cage coordinates (flat xyz) that map the regular cage onto ``targets``."""
    import numpy as np
    matrix = homography([rest for _role, _label, rest in ROLES], targets)
    xs, ys = np.meshgrid(
        np.linspace(-0.5, 0.5, points_u), np.linspace(-0.5, 0.5, points_v)
    )
    ones = np.ones_like(xs)
    mapped = np.einsum("ij,jkl->ikl", matrix, np.stack((xs, ys, ones)))
    w = mapped[2]
    w = np.where(np.abs(w) < 1.0e-9, 1.0e-9, w)
    result = np.zeros((points_v, points_u, 3))
    result[..., 0] = mapped[0] / w
    result[..., 1] = mapped[1] / w
    return result.reshape(-1).tolist()


def signature(rig, helper):
    targets = corner_targets(rig, helper)
    if targets is None:
        return None
    data = helper.data
    parts = [str(int(data.points_u)), str(int(data.points_v))]
    parts.extend(f"{value:.6f}" for point in targets for value in point)
    return "|".join(parts)


def apply(rig, helper, *, force=False):
    """Write the perspective cage. Return True when the cage changed."""
    if rig is None or helper is None:
        return False
    try:
        current = signature(rig, helper)
        if current is None:
            return False
        if not force and str(helper.get(SIGNATURE_KEY, "") or "") == current:
            return False
        data = helper.data
        if int(data.points_w) != 1:
            return False
        coordinates = cage_coordinates(int(data.points_u), int(data.points_v), corner_targets(rig, helper))
        from .lattice_poses import write_rest_cage
        write_rest_cage(helper, coordinates)
        helper[SIGNATURE_KEY] = current
        return True
    except (ImportError, ArithmeticError) + FBP_DATA_ERRORS:
        return False
    except Exception as exc:  # numpy.linalg.LinAlgError for a degenerate quad
        if type(exc).__name__ == "LinAlgError":
            return False
        raise


__all__ = (
    "CORNER_ROLE_KEY",
    "MIN_POINTS",
    "ROLES",
    "apply",
    "cage_coordinates",
    "corner_handles",
    "corner_owner",
    "corner_targets",
    "ensure_handles",
    "homography",
    "is_corner_handle",
    "remove_handles",
    "reset_handles",
)
