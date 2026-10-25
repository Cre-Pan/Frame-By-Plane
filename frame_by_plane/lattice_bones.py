"""Bones for the Lattice (Deform Plane) effect, in the spirit of Moho.

A layer gets one native Armature, parented to its rig in the plane frame (local
Z is the plane normal, so bones lie on the drawing and rotate in its plane).
Chains are drawn with clicks: shoulder, elbow, hand. The cage is deformed by an
Armature modifier; each deforming bone owns a vertex group on the cage with
harmonic weights (the same solve as the puppet pins, so Follow Drawing applies
and joints bend smoothly). Chains of two or more bones get an IK target bone at
their end: drag the hand and the arm follows. Everything is native Blender:
Pose Mode, keyframes, constraints and rendering need no Python at playback.
"""

from __future__ import annotations

import bpy
from mathutils import Vector

from .lattice_pins import (
    plane_frame,
    solve_partition,
    write_groups,
)
from .runtime import FBP_DATA_ERRORS


BONES_OWNER_KEY = "fbp_lattice_bones_owner"
BIND_KEY = "fbp_lattice_bones_bind"
GROUPS_KEY = "fbp_lattice_bones_groups"
MODIFIER_NAME = "FBP • Bones"
IK_PREFIX = "IK "
IK_CONSTRAINT = "FBP IK"


def is_bones_object(obj):
    try:
        return bool(obj is not None and str(obj.get(BONES_OWNER_KEY, "") or "") and obj.type == 'ARMATURE')
    except FBP_DATA_ERRORS:
        return False


def bones_owner(obj):
    if not is_bones_object(obj):
        return None
    parent = getattr(obj, "parent", None)
    if parent is not None and bool(getattr(parent, "is_fbp_control", False)):
        return parent
    owner = bpy.data.objects.get(str(obj.get(BONES_OWNER_KEY, "") or ""))
    return owner if owner is not None and bool(getattr(owner, "is_fbp_control", False)) else None


def bones_object(rig):
    if rig is None:
        return None
    try:
        for obj in tuple(getattr(rig, "children", ()) or ()):
            if is_bones_object(obj):
                return obj
    except FBP_DATA_ERRORS:
        return None
    return None


def bones_modifier(helper):
    if helper is None:
        return None
    try:
        return helper.modifiers.get(MODIFIER_NAME)
    except FBP_DATA_ERRORS:
        return None


def deform_bones(armature):
    """Rest bones that bend the drawing (IK targets are excluded)."""
    try:
        return [bone for bone in armature.data.bones if bone.use_deform]
    except FBP_DATA_ERRORS:
        return []


def ensure_armature(rig, helper, plane):
    """Return the layer armature, creating it and its cage modifier if needed."""
    armature = bones_object(rig)
    if armature is None:
        data = bpy.data.armatures.new(f"Bones • {rig.name}")
        data.display_type = 'OCTAHEDRAL'
        armature = bpy.data.objects.new(f"Bones • {rig.name}", data)
        armature[BONES_OWNER_KEY] = str(rig.name)
        collections = tuple(getattr(helper, "users_collection", ()) or ()) or (bpy.context.scene.collection,)
        for collection in collections:
            collection.objects.link(armature)
        armature.parent = rig
        armature.matrix_parent_inverse = rig.matrix_world.inverted_safe() @ plane_frame(plane, helper)
        armature.show_in_front = True
        armature.hide_render = True
        armature.lock_location = (True, True, True)
        armature.lock_rotation = (True, True, True)
        armature.lock_scale = (True, True, True)
    modifier = bones_modifier(helper)
    if modifier is None:
        modifier = helper.modifiers.new(MODIFIER_NAME, 'ARMATURE')
        # Bones first, then pins and point handles on top.
        try:
            helper.modifiers.move(len(helper.modifiers) - 1, 0)
        except FBP_DATA_ERRORS:
            pass
    modifier.object = armature
    modifier.use_vertex_groups = True
    modifier.use_bone_envelopes = False
    modifier.use_deform_preserve_volume = False
    modifier.show_in_editmode = True
    modifier.show_on_cage = True
    return armature


def armature_world(rig, armature):
    """World matrix of the armature without waiting for a depsgraph update."""
    return rig.matrix_world @ armature.matrix_parent_inverse @ armature.matrix_basis


def local_point(rig, armature, world_point):
    local = armature_world(rig, armature).inverted_safe() @ Vector(world_point)
    local.z = 0.0
    return local


def add_bone(armature, head, tail, parent_name=""):
    """Add a planar bone in Edit Mode (the armature must be in Edit Mode)."""
    edit_bones = armature.data.edit_bones
    index = 1
    while edit_bones.get(f"Bone {index}") is not None or edit_bones.get(f"{IK_PREFIX}Bone {index}") is not None:
        index += 1
    bone = edit_bones.new(f"Bone {index}")
    bone.head = Vector(head)
    bone.tail = Vector(tail)
    # Bone Z is the plane normal: rotating around it bends in the drawing plane.
    bone.align_roll(Vector((0.0, 0.0, 1.0)))
    parent = edit_bones.get(parent_name) if parent_name else None
    if parent is not None:
        bone.parent = parent
        bone.use_connect = (parent.tail - bone.head).length < 1.0e-6
    return bone.name


def remove_bone(armature, name):
    edit_bones = armature.data.edit_bones
    bone = edit_bones.get(name)
    if bone is not None:
        edit_bones.remove(bone)


def nearest_joint(armature, world_matrix, world_to_region, coord, limit):
    """Return (local point, parent bone name) of the joint nearest a screen point."""
    best = None
    for bone in armature.data.edit_bones:
        if bone.name.startswith(IK_PREFIX):
            continue
        for point, parent in ((bone.tail, bone.name), (bone.head, bone.parent.name if bone.parent else "")):
            screen = world_to_region(world_matrix @ point)
            if screen is None:
                continue
            distance = (Vector(screen) - Vector(coord)).length
            if distance <= limit and (best is None or distance < best[0]):
                best = (distance, point.copy(), parent)
    return (best[1], best[2]) if best is not None else (None, "")


def add_ik_target(armature, chain):
    """Add a non-deforming IK target bone at the end of a chain (Edit Mode)."""
    edit_bones = armature.data.edit_bones
    last = edit_bones.get(chain[-1])
    first = edit_bones.get(chain[0])
    if last is None or first is None:
        return ""
    direction = (last.tail - last.head)
    length = max(direction.length * 0.3, 1.0e-3)
    target = edit_bones.new(f"{IK_PREFIX}{last.name}")
    target.head = last.tail.copy()
    target.tail = last.tail + direction.normalized() * length
    target.align_roll(Vector((0.0, 0.0, 1.0)))
    target.use_deform = False
    # The hand follows the body: parent the target to whatever holds the chain.
    target.parent = first.parent
    return target.name


def setup_pose_constraints(armature, chains):
    """Planar pose locks and IK constraints (Pose Mode or Object Mode)."""
    pose_bones = armature.pose.bones
    for bone in pose_bones:
        bone.rotation_mode = 'XYZ'
        bone.lock_rotation = (True, True, False)
        bone.lock_location = (bone.bone.use_connect, bone.bone.use_connect, True)
        bone.lock_scale = (False, False, True)
        bone.lock_ik_x = True
        bone.lock_ik_y = True
    for chain, target in chains:
        if not target:
            continue
        last = pose_bones.get(chain[-1])
        if last is None:
            continue
        constraint = last.constraints.get(IK_CONSTRAINT) or last.constraints.new('IK')
        constraint.name = IK_CONSTRAINT
        constraint.target = armature
        constraint.subtarget = target
        constraint.chain_count = len(chain)
        constraint.use_tail = True
        constraint.use_stretch = False


def _signature(rig, helper, armature):
    data = helper.data
    parts = [
        str(int(data.points_u)), str(int(data.points_v)),
        "1" if bool(getattr(rig, "fbp_lattice_pins_follow_drawing", True)) else "0",
    ]
    parts.extend(f"{value:.6f}" for row in helper.matrix_world for value in row)
    parts.extend(f"{value:.6f}" for row in armature.matrix_parent_inverse for value in row)
    for bone in deform_bones(armature):
        parts.append(bone.name)
        parts.extend(f"{value:.6f}" for value in (*bone.head_local, *bone.tail_local))
    return "|".join(parts)


def bind(rig, helper, plane, *, force=False):
    """Rebuild the bone weights on the cage when the rest bones or cage changed."""
    armature = bones_object(rig)
    if armature is None or helper is None or plane is None:
        return False
    if str(getattr(armature, "mode", "OBJECT")) == 'EDIT':
        # Rest bones are only final once Edit Mode is left.
        return False
    try:
        signature = _signature(rig, helper, armature)
        if not force and str(helper.get(BIND_KEY, "") or "") == signature:
            return False
    except FBP_DATA_ERRORS:
        return False
    bones = deform_bones(armature)
    # Drop groups of bones that no longer exist.
    previous = [str(name) for name in (helper.get(GROUPS_KEY, ()) or ())]
    names = [bone.name for bone in bones]
    for name in previous:
        if name not in names:
            group = helper.vertex_groups.get(name)
            if group is not None:
                helper.vertex_groups.remove(group)
    if bones:
        to_cage = helper.matrix_world.inverted_safe() @ armature_world(rig, armature)
        controls = []
        for bone in bones:
            parent = bone.parent if bone.parent is not None and bone.parent.use_deform else None
            children = [child for child in bone.children if child.use_deform]
            controls.append({
                "points": [to_cage @ bone.head_local, to_cage @ bone.tail_local],
                "radius": 0.0,
                "start": 0.2 if parent is not None and (parent.tail_local - bone.head_local).length < 1.0e-5 else 0.0,
                "end": 0.8 if children else 1.0,
            })
        write_groups(helper, names, solve_partition(rig, helper, plane, controls))
    helper[GROUPS_KEY] = names
    helper[BIND_KEY] = signature
    ensure_armature(rig, helper, plane)
    helper.data.update_tag()
    helper.update_tag(refresh={'DATA'})
    return True


def reset_pose(armature):
    for bone in armature.pose.bones:
        bone.location = (0.0, 0.0, 0.0)
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def key_pose(armature, frame=None):
    count = 0
    for bone in armature.pose.bones:
        for path in ("location", "rotation_euler", "scale"):
            try:
                if frame is None:
                    bone.keyframe_insert(path)
                else:
                    bone.keyframe_insert(path, frame=frame)
                count += 1
            except FBP_DATA_ERRORS:
                continue
    return count


def remove_bones(rig, helper=None):
    """Remove the layer armature, its cage modifier and bone vertex groups."""
    changed = False
    armature = bones_object(rig)
    owner_name = str(getattr(rig, "name", "") or "")
    armatures = [armature] if armature is not None else []
    try:
        for obj in tuple(bpy.data.objects):
            if obj not in armatures and is_bones_object(obj) and str(obj.get(BONES_OWNER_KEY, "") or "") == owner_name:
                armatures.append(obj)
    except FBP_DATA_ERRORS:
        pass
    if helper is not None:
        try:
            modifier = bones_modifier(helper)
            if modifier is not None:
                helper.modifiers.remove(modifier)
                changed = True
            for name in [str(name) for name in (helper.get(GROUPS_KEY, ()) or ())]:
                group = helper.vertex_groups.get(name)
                if group is not None:
                    helper.vertex_groups.remove(group)
            helper.pop(GROUPS_KEY, None)
            helper.pop(BIND_KEY, None)
        except FBP_DATA_ERRORS:
            pass
    for obj in armatures:
        data = getattr(obj, "data", None)
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            changed = True
        except FBP_DATA_ERRORS:
            continue
        try:
            if data is not None and data.users == 0:
                bpy.data.armatures.remove(data)
        except FBP_DATA_ERRORS:
            pass
    return changed


__all__ = (
    "BONES_OWNER_KEY",
    "IK_PREFIX",
    "MODIFIER_NAME",
    "add_bone",
    "add_ik_target",
    "armature_world",
    "bind",
    "bones_object",
    "bones_owner",
    "deform_bones",
    "ensure_armature",
    "is_bones_object",
    "key_pose",
    "local_point",
    "nearest_joint",
    "remove_bone",
    "remove_bones",
    "reset_pose",
    "setup_pose_constraints",
)
