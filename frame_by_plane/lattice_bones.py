"""The controls armature of the Lattice (Deform Plane) effect.

Every layer gets at most one native Armature, parented to its rig in the plane
frame (local Z is the plane normal). It holds all the handles of the cage, so
the viewport shows one object and no relationship lines per handle:

* **Bones** (in the spirit of Moho): deforming bones drawn as sticks. Chains
  are drawn with clicks (shoulder, elbow, hand) and get an IK handle at their
  end. An Armature modifier deforms the cage; each bone owns a vertex group
  with harmonic weights (the same solve as the puppet pins, so Follow Drawing
  applies and joints bend smoothly).
* **Handles**: puppet pins, bend pins, Grid point handles and Corner Pin
  corners are non-deforming bones with their own shapes. Pins and point
  handles drive the cage through Hook modifiers that target their bone.

Everything is native Blender: Pose Mode, keyframes, constraints and rendering
need no Python at playback.
"""

from __future__ import annotations

import math
from contextlib import contextmanager

import bpy
from mathutils import Vector

from .runtime import FBP_DATA_ERRORS


BONES_OWNER_KEY = "fbp_lattice_bones_owner"
BIND_KEY = "fbp_lattice_bones_bind"
GROUPS_KEY = "fbp_lattice_bones_groups"
MODIFIER_NAME = "FBP • Bones"
IK_PREFIX = "IK "
IK_CONSTRAINT = "FBP IK"
# Pose bone tag of handles: "PIN", "BEND", "POINT" or "CORNER".
HANDLE_KEY = "fbp_lattice_handle"
SHAPE_KEY = "fbp_lattice_handle_shape"

# Handle shapes: meshes drawn flat on the drawing, in bone space (X, Y). Faces
# draw filled, so a handle reads as a solid dot with a thin outline.
_SHAPES = {
    "PIN": "FBP Handle • Pin",
    "BEND": "FBP Handle • Bend",
    "POINT": "FBP Handle • Point",
    "CORNER": "FBP Handle • Corner",
    "IK": "FBP Handle • IK",
}
# Bump when a shape changes: shapes saved in older files are rebuilt in place.
SHAPE_VERSION = 2
SHAPE_VERSION_KEY = "fbp_lattice_handle_shape_version"
# One accent for every handle, shared with the effect controls (Crop, Extend
# and the others); the shape tells the kinds apart. (normal, selected, active)
HANDLE_COLORS = (
    (1.0, 0.55, 0.05),
    (1.0, 0.86, 0.6),
    (1.0, 1.0, 1.0),
)
HANDLE_WIRE_WIDTH = 2.0
# Size of each kind relative to the layer's base handle size (half a point).
_KIND_SCALE = {
    "PIN": 1.6,
    "BEND": 2.0,
    "POINT": 1.0,
    "CORNER": 1.0,
    "IK": 1.6,
}


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


def handle_kind(pose_bone):
    try:
        return str(pose_bone.get(HANDLE_KEY, "") or "")
    except FBP_DATA_ERRORS:
        return ""


def is_handle_bone(pose_bone):
    return bool(handle_kind(pose_bone))


def deform_bones(armature):
    """Rest bones that bend the drawing (IK targets and handles are excluded)."""
    try:
        return [bone for bone in armature.data.bones if bone.use_deform]
    except FBP_DATA_ERRORS:
        return []


def rig_bones(armature):
    """Pose bones of the Bones type: deforming bones and their IK targets."""
    if armature is None:
        return []
    try:
        return [bone for bone in armature.pose.bones if not is_handle_bone(bone)]
    except FBP_DATA_ERRORS:
        return []


# --- Armature ----------------------------------------------------------------


def _shape_object(kind):
    """Return the shared mesh used to draw a kind of handle."""
    name = _SHAPES[kind]
    obj = bpy.data.objects.get(name)
    if (
        obj is not None and getattr(obj, "type", "") == 'MESH'
        and int(obj.get(SHAPE_VERSION_KEY, 0) or 0) == SHAPE_VERSION
    ):
        return obj
    vertices, edges, faces = [], [], []

    def loop(radius, segments=32, start=0.0, sweep=math.tau, closed=True, centre=(0.0, 0.0)):
        first = len(vertices)
        count = segments if closed else segments + 1
        for index in range(count):
            angle = start + sweep * index / float(segments)
            vertices.append((centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle), 0.0))
        for index in range(count - 1):
            edges.append((first + index, first + index + 1))
        if closed:
            edges.append((first + count - 1, first))
        return list(range(first, first + count))

    def disc(radius, segments=24, centre=(0.0, 0.0)):
        faces.append(tuple(loop(radius, segments, centre=centre)))

    def line(*points):
        first = len(vertices)
        vertices.extend((x, y, 0.0) for x, y in points)
        edges.extend((first + index, first + index + 1) for index in range(len(points) - 1))
        return list(range(first, first + len(points)))

    def square(half):
        corners = line((half, half), (-half, half), (-half, -half), (half, -half))
        edges.append((corners[-1], corners[0]))
        faces.append(tuple(corners))

    if kind == "PIN":
        loop(1.0)
        disc(0.32, segments=16)
    elif kind == "BEND":
        # An open ring with an arrow: this handle turns, it does not move.
        loop(1.0, segments=28, start=math.radians(20.0), sweep=math.radians(300.0), closed=False)
        tip = (math.cos(math.radians(320.0)), math.sin(math.radians(320.0)))
        line((tip[0] - 0.32, tip[1] - 0.05), tip, (tip[0] - 0.05, tip[1] + 0.32))
        disc(0.26, segments=16)
    elif kind == "POINT":
        square(1.0)
    elif kind == "CORNER":
        # A square with an L bracket opening towards +X/+Y (rotated per corner).
        square(1.0)
        line((3.0, 0.0), (1.6, 0.0))
        line((0.0, 1.6), (0.0, 3.0))
    else:  # IK
        loop(1.0)
        line((-1.4, 0.0), (-0.6, 0.0))
        line((0.6, 0.0), (1.4, 0.0))
        line((0.0, -1.4), (0.0, -0.6))
        line((0.0, 0.6), (0.0, 1.4))
    mesh = bpy.data.meshes.get(name) or bpy.data.meshes.new(name)
    mesh.clear_geometry()
    mesh.from_pydata(vertices, edges, faces)
    mesh.update()
    if obj is None or getattr(obj, "type", "") != 'MESH':
        obj = bpy.data.objects.new(name, mesh)
    else:
        obj.data = mesh
    # Shapes are not in any scene: keep them with the file.
    obj.use_fake_user = True
    obj[SHAPE_KEY] = kind
    obj[SHAPE_VERSION_KEY] = SHAPE_VERSION
    return obj


def _cage_cell(plane, rig):
    """Smallest cage cell of the layer in world units, or 0 when unknown."""
    try:
        points_u = max(2, int(getattr(rig, "fbp_lattice_points_u", 4) or 4))
        points_v = max(2, int(getattr(rig, "fbp_lattice_points_v", 4) or 4))
        return min(
            float(plane.dimensions.x) / (points_u - 1),
            float(plane.dimensions.y) / (points_v - 1),
        )
    except (TypeError, ValueError) + FBP_DATA_ERRORS:
        return 0.0


def handle_size(plane, kind="", rig=None):
    """World half-size of a handle, scaled by the layer's Handle Size.

    A point handle is 6% of the plane's short side (0.02 to 0.3 units), like
    the effect controls.
    """
    try:
        size = min(float(plane.dimensions.x), float(plane.dimensions.y))
    except FBP_DATA_ERRORS:
        size = 1.0
    size = 0.5 * max(0.02, min(0.3, size * 0.06))
    if not kind:
        return size
    size *= _KIND_SCALE.get(kind, 1.0)
    if kind == "POINT" and rig is not None:
        # Dense grids: a point never covers its neighbours.
        cell = _cage_cell(plane, rig)
        if cell > 0.0:
            size = min(size, cell * 0.18)
    if rig is not None:
        try:
            size *= max(0.1, float(getattr(rig, "fbp_lattice_handle_size", 1.0) or 1.0))
        except (TypeError, ValueError) + FBP_DATA_ERRORS:
            pass
    return max(0.002, size)


def _apply_color(color):
    color.palette = 'CUSTOM'
    color.custom.normal, color.custom.select, color.custom.active = HANDLE_COLORS
    color.custom.show_colored_constraints = False


def style_bone(pose_bone, kind, size, *, rotation=0.0):
    """Give a pose bone the shape and colour of a handle kind."""
    pose_bone.custom_shape = _shape_object(kind)
    pose_bone.use_custom_shape_bone_size = False
    pose_bone.custom_shape_scale_xyz = (size, size, size)
    pose_bone.custom_shape_rotation_euler = (0.0, 0.0, rotation)
    pose_bone.custom_shape_wire_width = HANDLE_WIRE_WIDTH
    try:
        _apply_color(pose_bone.color)
        _apply_color(pose_bone.bone.color)
    except FBP_DATA_ERRORS:
        pass


def restyle_handles(rig, plane):
    """Re-apply shapes, colours and sizes to every handle of a layer.

    Rotation stays as it is (corner brackets face their own corner). Return
    the number of handles restyled.
    """
    armature = bones_object(rig)
    if armature is None or plane is None:
        return 0
    count = 0
    try:
        pose_bones = tuple(armature.pose.bones)
    except FBP_DATA_ERRORS:
        return 0
    for pose_bone in pose_bones:
        shape = getattr(pose_bone, "custom_shape", None)
        try:
            kind = str(shape.get(SHAPE_KEY, "") or "") if shape is not None else ""
        except FBP_DATA_ERRORS:
            kind = ""
        if kind not in _SHAPES:
            continue
        try:
            rotation = float(pose_bone.custom_shape_rotation_euler[2])
            style_bone(pose_bone, kind, handle_size(plane, kind, rig), rotation=rotation)
            count += 1
        except FBP_DATA_ERRORS:
            continue
    try:
        armature[SHAPE_VERSION_KEY] = SHAPE_VERSION
    except FBP_DATA_ERRORS:
        pass
    return count


def ensure_armature(rig, helper, plane):
    """Return the layer's controls armature, creating it and its cage modifier."""
    from .lattice_pins import plane_frame
    armature = bones_object(rig)
    if armature is None:
        data = bpy.data.armatures.new(f"Controls • {rig.name}")
        armature = bpy.data.objects.new(f"Controls • {rig.name}", data)
        armature[BONES_OWNER_KEY] = str(rig.name)
        collections = tuple(getattr(helper, "users_collection", ()) or ()) or (bpy.context.scene.collection,)
        for collection in collections:
            collection.objects.link(armature)
        armature.parent = rig
        armature.matrix_parent_inverse = rig.matrix_world.inverted_safe() @ plane_frame(plane, helper)
        armature.show_in_front = True
        armature[SHAPE_VERSION_KEY] = SHAPE_VERSION
        armature.hide_render = True
        armature.lock_location = (True, True, True)
        armature.lock_rotation = (True, True, True)
        armature.lock_scale = (True, True, True)
    data = armature.data
    # Bones read as sticks, like a 2D puppet; handles draw their own shapes.
    data.display_type = 'STICK'
    data.show_bone_custom_shapes = True
    data.relation_line_position = 'HEAD'
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


@contextmanager
def editing(armature):
    """Edit the armature's rest bones, then return to the mode it was in."""
    context = bpy.context
    view_layer = context.view_layer
    previous_active = view_layer.objects.active
    previous_mode = str(getattr(armature, "mode", "OBJECT"))
    hidden = bool(armature.hide_get())
    if hidden:
        armature.hide_set(False)
    override = dict(active_object=armature, object=armature, selected_objects=[armature], selected_editable_objects=[armature])
    if previous_active is not None and previous_active is not armature and str(getattr(previous_active, "mode", "OBJECT")) != 'OBJECT':
        with context.temp_override(active_object=previous_active, object=previous_active):
            bpy.ops.object.mode_set(mode='OBJECT')
    view_layer.objects.active = armature
    try:
        with context.temp_override(**override):
            if previous_mode != 'EDIT':
                bpy.ops.object.mode_set(mode='EDIT')
            yield armature.data.edit_bones
    finally:
        with context.temp_override(**override):
            if previous_mode != 'EDIT' and str(armature.mode) == 'EDIT':
                bpy.ops.object.mode_set(mode=previous_mode if previous_mode in {'POSE', 'OBJECT'} else 'OBJECT')
        if previous_active is not None and previous_active is not armature:
            try:
                view_layer.objects.active = previous_active
            except FBP_DATA_ERRORS:
                pass
        if hidden:
            armature.hide_set(True)


def unique_bone_name(edit_bones, base):
    if edit_bones.get(base) is None:
        return base
    index = 2
    while edit_bones.get(f"{base} {index}") is not None:
        index += 1
    return f"{base} {index}"


def add_handle_bones(armature, specs):
    """Add handle bones in one Edit Mode pass.

    ``specs`` is a list of (name, local head) in armature (plane frame) space;
    each handle points along +Y with roll 0, so its pose location moves it
    across the drawing and its Z rotation turns it in the drawing's plane.
    Return the bone names in order.
    """
    names = []
    with editing(armature) as edit_bones:
        for name, head in specs:
            bone = edit_bones.new(unique_bone_name(edit_bones, name))
            head = Vector((float(head[0]), float(head[1]), 0.0))
            bone.head = head
            bone.tail = head + Vector((0.0, 0.01, 0.0))
            bone.roll = 0.0
            bone.use_deform = False
            names.append(bone.name)
    return names


def remove_bone_names(armature, names):
    names = [name for name in names if armature.data.bones.get(name) is not None]
    if not names:
        return
    with editing(armature) as edit_bones:
        for name in names:
            bone = edit_bones.get(name)
            if bone is not None:
                edit_bones.remove(bone)


def armature_world(rig, armature):
    """World matrix of the armature without waiting for a depsgraph update."""
    return rig.matrix_world @ armature.matrix_parent_inverse @ armature.matrix_basis


def local_point(rig, armature, world_point):
    local = armature_world(rig, armature).inverted_safe() @ Vector(world_point)
    local.z = 0.0
    return local


def pose_matrix(pose_bone):
    """Armature-space pose matrix of an unparented, unconstrained handle bone."""
    return pose_bone.bone.matrix_local @ pose_bone.matrix_basis


# --- Bones (deforming chains) ------------------------------------------------


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
        if not bone.use_deform:
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


def setup_pose_constraints(armature, chains, size=None):
    """Planar pose locks and IK constraints for the given chains."""
    pose_bones = armature.pose.bones
    for chain, target in chains:
        for name in [*chain, target]:
            bone = pose_bones.get(name) if name else None
            if bone is None:
                continue
            bone.rotation_mode = 'XYZ'
            bone.lock_rotation = (True, True, False)
            bone.lock_location = (bone.bone.use_connect, bone.bone.use_connect, True)
            bone.lock_scale = (False, False, True)
            bone.lock_ik_x = True
            bone.lock_ik_y = True
        if not target:
            continue
        target_bone = pose_bones.get(target)
        if target_bone is not None and size:
            style_bone(target_bone, "IK", size)
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
    from .lattice_pins import solve_partition, write_groups
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
            # A chain's free ends (root head, tip tail) are owned outright.
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
    for bone in rig_bones(armature):
        bone.location = (0.0, 0.0, 0.0)
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def key_pose(armature, frame=None):
    count = 0
    for bone in rig_bones(armature):
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


def _clear_bone_groups(helper):
    if helper is None:
        return
    try:
        for name in [str(name) for name in (helper.get(GROUPS_KEY, ()) or ())]:
            group = helper.vertex_groups.get(name)
            if group is not None:
                helper.vertex_groups.remove(group)
        helper.pop(GROUPS_KEY, None)
        helper.pop(BIND_KEY, None)
    except FBP_DATA_ERRORS:
        pass


def remove_bones(rig, helper=None):
    """Remove the deforming bones and IK targets; handles stay."""
    armature = bones_object(rig)
    if armature is None:
        return False
    names = [bone.name for bone in rig_bones(armature)]
    _clear_bone_groups(helper)
    if not any(is_handle_bone(bone) for bone in armature.pose.bones):
        return remove_armature(rig, helper)
    remove_bone_names(armature, names)
    return bool(names)


def remove_armature(rig, helper=None):
    """Remove the controls armature, its cage modifier and bone vertex groups."""
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
        except FBP_DATA_ERRORS:
            pass
        _clear_bone_groups(helper)
    for obj in armatures:
        data = getattr(obj, "data", None)
        try:
            if str(getattr(obj, "mode", "OBJECT")) != 'OBJECT':
                with bpy.context.temp_override(active_object=obj, object=obj):
                    bpy.ops.object.mode_set(mode='OBJECT')
        except FBP_DATA_ERRORS:
            pass
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
    _remove_unused_shapes()
    return changed


def _remove_unused_shapes():
    """Drop the shared handle shapes once no controls armature is left."""
    try:
        if any(is_bones_object(obj) for obj in bpy.data.objects):
            return
        for name in _SHAPES.values():
            obj = bpy.data.objects.get(name)
            if obj is None or not str(obj.get(SHAPE_KEY, "") or ""):
                continue
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    except FBP_DATA_ERRORS:
        pass


def remove_unused_armature(rig, helper=None):
    """Drop the armature once it holds no bones at all."""
    armature = bones_object(rig)
    if armature is not None and not len(armature.data.bones):
        return remove_armature(rig, helper)
    return False


__all__ = (
    "BONES_OWNER_KEY",
    "HANDLE_KEY",
    "IK_PREFIX",
    "MODIFIER_NAME",
    "add_bone",
    "add_handle_bones",
    "add_ik_target",
    "armature_world",
    "bind",
    "bones_object",
    "bones_owner",
    "deform_bones",
    "editing",
    "ensure_armature",
    "handle_kind",
    "handle_size",
    "restyle_handles",
    "is_bones_object",
    "is_handle_bone",
    "key_pose",
    "local_point",
    "nearest_joint",
    "pose_matrix",
    "remove_armature",
    "remove_bone",
    "remove_bone_names",
    "remove_bones",
    "remove_unused_armature",
    "reset_pose",
    "rig_bones",
    "setup_pose_constraints",
    "style_bone",
)
