"""Corner Pin for the Lattice (Deform Plane) effect, like After Effects.

Four handles sit on the layer's corners. Moving them maps the layer onto the
new quad with a true perspective (projective) transform, so the drawing
foreshortens towards the far side instead of only shearing. The transform is
written into the rest cage, like Camera Flatten: poses, pins and bones still
work on top. The cage is linear and dense enough that its piecewise-linear
surface follows the projective map closely.

The handles are bones of the layer's controls armature (see ``lattice_bones``)
and keyframe like any bone. The cage is rewritten when a handle moves and on
every frame change, so animated corners also render (the add-on must be
enabled).
"""

from __future__ import annotations

import math

from mathutils import Vector

from .lattice_bones import (
    HANDLE_KEY,
    add_handle_bones,
    bones_object,
    bones_owner,
    ensure_armature,
    handle_size,
    remove_bone_names,
    remove_unused_armature,
    style_bone,
)
from .runtime import FBP_DATA_ERRORS


CORNER_ROLE_KEY = "fbp_lattice_corner"
SIGNATURE_KEY = "fbp_lattice_corner_signature"
KIND_CORNER = "CORNER"
# Cage corner order: counter-clockwise from the bottom left. The last value
# turns the bracket shape so it opens towards the layer.
ROLES = (
    ("BL", "Bottom Left", (-0.5, -0.5), 0.0),
    ("BR", "Bottom Right", (0.5, -0.5), 90.0),
    ("TR", "Top Right", (0.5, 0.5), 180.0),
    ("TL", "Top Left", (-0.5, 0.5), 270.0),
)
# Minimum cage points per axis for a smooth perspective.
MIN_POINTS = 12


def is_corner_handle(pose_bone):
    try:
        return bool(pose_bone is not None and str(pose_bone.get(CORNER_ROLE_KEY, "") or ""))
    except FBP_DATA_ERRORS:
        return False


def corner_owner(pose_bone):
    if not is_corner_handle(pose_bone):
        return None
    return bones_owner(pose_bone.id_data)


def corner_handles(rig):
    """Return {role: handle pose bone} for a layer."""
    result = {}
    armature = bones_object(rig)
    if armature is None:
        return result
    try:
        for bone in armature.pose.bones:
            if is_corner_handle(bone):
                result[str(bone.get(CORNER_ROLE_KEY))] = bone
    except FBP_DATA_ERRORS:
        return {}
    return result


def _cage_to_armature(helper, armature):
    """Matrix from cage coordinates to armature (plane frame) space.

    Both are children of the layer rig, so the rig's own world matrix cancels:
    this stays exact while the rig animates, even before a depsgraph update.
    """
    cage_in_rig = helper.matrix_parent_inverse @ helper.matrix_basis
    frame_in_rig = armature.matrix_parent_inverse @ armature.matrix_basis
    return frame_in_rig.inverted_safe() @ cage_in_rig


def ensure_handles(rig, helper, plane):
    """Create missing corner handles on the cage corners. Return {role: handle}."""
    handles = corner_handles(rig)
    missing = [role for role in ROLES if role[0] not in handles]
    if not missing:
        return handles
    armature = ensure_armature(rig, helper, plane)
    to_armature = _cage_to_armature(helper, armature)
    specs = [
        (f"Corner {label}", to_armature @ Vector((x, y, 0.0)))
        for _role, label, (x, y), _turn in missing
    ]
    names = add_handle_bones(armature, specs)
    size = handle_size(plane) * 0.7
    for (role, _label, _rest, turn), name in zip(missing, names):
        handle = armature.pose.bones[name]
        handle[HANDLE_KEY] = KIND_CORNER
        handle[CORNER_ROLE_KEY] = role
        handle.rotation_mode = 'XYZ'
        # Corners only move; perspective comes from where they are.
        handle.lock_location = (False, False, True)
        handle.lock_rotation = (True, True, True)
        handle.lock_scale = (True, True, True)
        style_bone(handle, KIND_CORNER, size, rotation=math.radians(turn))
        handles[role] = handle
    return handles


def reset_handles(rig, helper):
    handles = corner_handles(rig)
    for role, _label, (x, y), _turn in ROLES:
        handle = handles.get(role)
        if handle is None:
            continue
        point = _cage_to_armature(helper, handle.id_data) @ Vector((x, y, 0.0))
        offset = point - handle.bone.head_local
        handle.location = (offset.x, offset.y, 0.0)


def remove_handles(rig, helper=None):
    handles = list(corner_handles(rig).values())
    if not handles:
        return False
    armature = handles[0].id_data
    remove_bone_names(armature, [handle.name for handle in handles])
    if helper is not None:
        helper.pop(SIGNATURE_KEY, None)
    remove_unused_armature(rig, helper)
    return True


def corner_targets(rig, helper):
    """Return the four handle positions in cage coordinates, in ROLES order."""
    handles = corner_handles(rig)
    result = []
    for role, _label, _rest, _turn in ROLES:
        handle = handles.get(role)
        if handle is None:
            return None
        to_cage = _cage_to_armature(helper, handle.id_data).inverted_safe()
        point = to_cage @ (handle.bone.head_local + Vector(tuple(handle.location)))
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
    matrix = homography([rest for _role, _label, rest, _turn in ROLES], targets)
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
