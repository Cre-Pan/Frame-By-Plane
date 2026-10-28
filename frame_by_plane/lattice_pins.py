"""Puppet pins for the Lattice (Deform Plane) effect.

A pin is a handle bone of the layer's controls armature (see
``lattice_bones``), so every handle of a layer lives in one object and the
viewport shows no relationship line per pin. Each pin drives the cage through
a native Hook modifier that targets its bone, restricted to a vertex group
whose weights say how much of the cage follows that pin. Moving, rotating or
scaling a pin in Pose Mode therefore bends the layer like a puppet, pins
keyframe like any bone, and nothing runs in Python at render time.

Weights are harmonic: every cage point blends the pins smoothly and the
weights of all pins sum to one, so a pin that is left alone anchors its area
while its neighbours move. With Follow Drawing the solve uses the layer's
alpha as conductance, so a pin on a hand does not drag a separate, nearby part
of the drawing across a transparent gap.

Handle bones point along the plane frame's +Y with roll 0, so their pose
location moves them across the drawing and their Z rotation turns them in its
plane. A pin stores its rest pose location; the Hook's inverse matrix is
rebuilt from it whenever the cage moves or changes resolution, and the
weights are rebuilt with it.

Kinds (After Effects style): a **Pin** moves, rotates and scales; a **Bend**
pin stays where it is and only rotates or scales its area; any pin can have a
**Stiff Area**, a disc that moves rigidly with it instead of bending. **Point
handles** are one Hook per cage point with the whole weight on that point, so
the Grid cage can be posed and keyframed without entering the cage's Edit Mode.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Vector

from .lattice_bones import (
    HANDLE_KEY,
    add_handle_bones,
    armature_world,
    bones_object,
    bones_owner,
    ensure_armature,
    handle_size,
    is_bones_object,
    pose_matrix,
    remove_bone_names,
    remove_unused_armature,
    style_bone,
)
from .runtime import FBP_DATA_ERRORS


PIN_ID_KEY = "fbp_lattice_pin_id"
PIN_REST_KEY = "fbp_lattice_pin_rest"
PIN_POINT_KEY = "fbp_lattice_pin_point"
PIN_GRID_KEY = "fbp_lattice_pin_grid"
BIND_SIGNATURE_KEY = "fbp_lattice_pins_bind"
KIND_PIN = "PIN"
KIND_BEND = "BEND"
KIND_POINT = "POINT"
PIN_KINDS = (KIND_PIN, KIND_BEND, KIND_POINT)
# Largest cage that gets one handle per point.
MAX_POINT_HANDLES = 100
GROUP_PREFIX = "FBP Pin "
HOOK_PREFIX = "FBP Pin • "

# Conductance across fully transparent pixels. Small but non-zero keeps every
# cage point connected, so empty areas still get smooth, well-defined weights.
_TRANSPARENT_CONDUCTANCE = 1.0e-3
_EDGE_SAMPLES = 9
# Largest image read for Follow Drawing (pixels). Bigger images fall back to an
# even solve instead of copying hundreds of megabytes of pixels.
_MAX_ALPHA_PIXELS = 4096 * 4096


def is_pin(item):
    """True for a pin pose bone (puppet pin, bend pin or point handle)."""
    try:
        return bool(
            isinstance(item, bpy.types.PoseBone)
            and str(item.get(HANDLE_KEY, "") or "") in PIN_KINDS
            and str(item.get(PIN_ID_KEY, "") or "")
        )
    except FBP_DATA_ERRORS:
        return False


def pin_owner(pin):
    """Return the layer rig of a pin, or None."""
    if not is_pin(pin):
        return None
    return bones_owner(pin.id_data)


def is_lattice_controller(obj):
    """True for the object that holds a Lattice cage's handles and bones."""
    return is_bones_object(obj)


def lattice_controller_owner(obj):
    """Return the layer rig of a Lattice controls armature, or None."""
    return bones_owner(obj) if is_bones_object(obj) else None


def pin_kind(pin):
    try:
        kind = str(pin.get(HANDLE_KEY, KIND_PIN) or KIND_PIN)
    except FBP_DATA_ERRORS:
        return KIND_PIN
    return kind if kind in PIN_KINDS else KIND_PIN


def rig_pins(rig, kinds=None):
    """Return the pin pose bones of a layer, in creation order.

    ``kinds`` filters by kind; None returns every pin, point handles included.
    """
    armature = bones_object(rig)
    if armature is None:
        return []
    try:
        found = [
            bone for bone in armature.pose.bones
            if is_pin(bone) and (kinds is None or pin_kind(bone) in kinds)
        ]
    except FBP_DATA_ERRORS:
        return []

    def order(pin):
        try:
            return int(str(pin.get(PIN_ID_KEY, "0")).split(".")[0])
        except (TypeError, ValueError):
            return 0
    return sorted(found, key=order)


def puppet_pins(rig):
    """Pins that take part in the smooth weight solve (not point handles)."""
    return rig_pins(rig, kinds=(KIND_PIN, KIND_BEND))


def _pin_id(pin):
    return str(pin.get(PIN_ID_KEY, "") or "")


def _group_name(pin_id):
    return f"{GROUP_PREFIX}{pin_id}"


def _hook_name(pin_id):
    return f"{HOOK_PREFIX}{pin_id}"


def pin_hook(helper, pin):
    if helper is None or pin is None:
        return None
    try:
        return helper.modifiers.get(_hook_name(_pin_id(pin)))
    except FBP_DATA_ERRORS:
        return None


def _rest_location(pin):
    try:
        values = tuple(float(value) for value in pin.get(PIN_REST_KEY, ()))
    except (TypeError,) + FBP_DATA_ERRORS:
        values = ()
    if len(values) != 3:
        return Vector((0.0, 0.0, 0.0))
    return Vector(values)


def plane_frame(plane, helper):
    """Return the handle frame: the cage centre with the plane's rotation, unit scale."""
    rotation = plane.matrix_world.to_quaternion().to_matrix().to_4x4()
    return Matrix.Translation(helper.matrix_world.translation) @ rotation


def _rest_world(rig, pin):
    """World matrix of a pin at rest, computed without a depsgraph update."""
    armature = pin.id_data
    return armature_world(rig, armature) @ pin.bone.matrix_local @ Matrix.Translation(_rest_location(pin))


def pin_world(rig, pin):
    """Current world matrix of a pin, computed without a depsgraph update."""
    return armature_world(rig, pin.id_data) @ pose_matrix(pin)


def _next_pin_id(rig):
    used = set()
    for pin in rig_pins(rig):
        try:
            used.add(int(_pin_id(pin)))
        except ValueError:
            continue
    index = 1
    while index in used:
        index += 1
    return str(index)


def _setup_handle(pin, kind, size, *, rotation=0.0, shape=None):
    """Planar transform locks and the handle look."""
    pin.rotation_mode = 'XYZ'
    pin.lock_location = (kind == KIND_BEND, kind == KIND_BEND, True)
    pin.lock_rotation = (True, True, kind == KIND_POINT)
    pin.lock_scale = (kind == KIND_POINT, kind == KIND_POINT, True)
    style_bone(pin, shape or kind, size, rotation=rotation)


def _grid_corner_turn(u_index, v_index, points_u, points_v):
    """Rotation of the L bracket on a cage corner, or None for other points."""
    last_u, last_v = points_u - 1, points_v - 1
    return {
        (0, 0): 0.0, (last_u, 0): 90.0, (last_u, last_v): 180.0, (0, last_v): 270.0,
    }.get((u_index, v_index))


def _attach_hook(helper, armature, pin, pin_id):
    helper.vertex_groups.new(name=_group_name(pin_id))
    hook = helper.modifiers.new(_hook_name(pin_id), 'HOOK')
    hook.object = armature
    hook.subtarget = pin.name
    hook.vertex_group = _group_name(pin_id)
    hook.falloff_type = 'NONE'
    hook.strength = 1.0
    hook.show_in_editmode = True
    hook.show_on_cage = True
    return hook


def add_pins(rig, helper, plane, world_locations, kind=KIND_PIN, *, bind_now=True):
    """Create pins at world locations on the layer and bind them. Return the pins."""
    armature = ensure_armature(rig, helper, plane)
    label = "Bend" if kind == KIND_BEND else "Pin"
    specs, ids = [], []
    used = {_pin_id(pin) for pin in rig_pins(rig)}
    index = 1
    for world in world_locations:
        while str(index) in used:
            index += 1
        used.add(str(index))
        ids.append(str(index))
        specs.append((f"{label} {index}", _local_head(rig, armature, world)))
    names = add_handle_bones(armature, specs)
    size = handle_size(plane, kind, rig)
    pins = []
    for name, pin_id in zip(names, ids):
        pin = armature.pose.bones[name]
        pin[HANDLE_KEY] = kind
        pin[PIN_ID_KEY] = pin_id
        pin[PIN_REST_KEY] = (0.0, 0.0, 0.0)
        _setup_handle(pin, kind, size)
        _attach_hook(helper, armature, pin, pin_id)
        pins.append(pin)
    if bind_now:
        bind(rig, helper, plane, force=True)
    return pins


def add_pin(rig, helper, plane, world_location, kind=KIND_PIN, *, bind_now=True):
    """Create one pin at a world location on the layer and bind it. Return the pin."""
    return add_pins(rig, helper, plane, [world_location], kind, bind_now=bind_now)[0]


def _local_head(rig, armature, world_location):
    local = armature_world(rig, armature).inverted_safe() @ Vector(world_location)
    local.z = 0.0
    return local


def add_point_handles(rig, helper, plane):
    """Give every cage point its own animatable handle. Return the handle count."""
    data = helper.data
    points_u, points_v = int(data.points_u), int(data.points_v)
    if points_u * points_v > MAX_POINT_HANDLES or int(data.points_w) != 1:
        return 0
    remove_all_pins(rig, helper, kinds=(KIND_POINT,))
    armature = ensure_armature(rig, helper, plane)
    keys = getattr(data, "shape_keys", None)
    if keys is not None and len(keys.key_blocks):
        source = keys.key_blocks[0].data
        coordinates = [Vector(item.co) for item in source]
    else:
        coordinates = [Vector(point.co_deform) for point in data.points]
    helper_world = helper.matrix_world
    used = {_pin_id(pin) for pin in rig_pins(rig)}
    specs, ids = [], []
    next_id = 1
    for index, local in enumerate(coordinates[: points_u * points_v]):
        while str(next_id) in used:
            next_id += 1
        used.add(str(next_id))
        ids.append(str(next_id))
        u_index, v_index = index % points_u, index // points_u
        specs.append((f"Point {u_index + 1}·{v_index + 1}", _local_head(rig, armature, helper_world @ local)))
    names = add_handle_bones(armature, specs)
    size = handle_size(plane, KIND_POINT, rig)
    corner_size = handle_size(plane, "GRID_CORNER", rig)
    for index, (name, pin_id) in enumerate(zip(names, ids)):
        handle = armature.pose.bones[name]
        handle[HANDLE_KEY] = KIND_POINT
        handle[PIN_ID_KEY] = pin_id
        handle[PIN_POINT_KEY] = index
        handle[PIN_GRID_KEY] = f"{points_u}x{points_v}"
        handle[PIN_REST_KEY] = (0.0, 0.0, 0.0)
        # Corners of the cage read as corners; every other point is a dot.
        turn = _grid_corner_turn(index % points_u, index // points_u, points_u, points_v)
        if turn is None:
            _setup_handle(handle, KIND_POINT, size)
        else:
            _setup_handle(handle, KIND_POINT, corner_size, rotation=math.radians(turn), shape="GRID_CORNER")
        _attach_hook(helper, armature, handle, pin_id)
    bind(rig, helper, plane, force=True)
    return points_u * points_v


def _drop_pin_data(helper, pin_id):
    if helper is None:
        return
    try:
        hook = helper.modifiers.get(_hook_name(pin_id))
        if hook is not None:
            helper.modifiers.remove(hook)
        group = helper.vertex_groups.get(_group_name(pin_id))
        if group is not None:
            helper.vertex_groups.remove(group)
    except FBP_DATA_ERRORS:
        pass


def _clear_pin_animation(armature, names):
    from .runtime import fbp_action_fcurves
    curves = fbp_action_fcurves(armature)
    if curves is None:
        return
    prefixes = tuple(f'pose.bones["{name}"]' for name in names)
    for curve in list(curves):
        try:
            if str(curve.data_path).startswith(prefixes):
                curves.remove(curve)
        except FBP_DATA_ERRORS:
            continue


def remove_pins(rig, helper, pins):
    """Remove pins with their Hooks, groups and animation, then rebind the rest."""
    if not pins:
        return False
    armature = pins[0].id_data
    names = [pin.name for pin in pins]
    for pin in pins:
        _drop_pin_data(helper, _pin_id(pin))
    _clear_pin_animation(armature, names)
    remove_bone_names(armature, names)
    if helper is not None:
        helper.pop(BIND_SIGNATURE_KEY, None)
        plane = getattr(rig, "fbp_plane_target", None)
        if rig_pins(rig) and plane is not None:
            bind(rig, helper, plane, force=True)
    remove_unused_armature(rig, helper)
    return True


def remove_pin(rig, helper, pin):
    return remove_pins(rig, helper, [pin])


def remove_all_pins(rig, helper=None, kinds=None):
    """Remove the pins of a layer (optionally only some kinds) with their Hooks."""
    pins = rig_pins(rig, kinds=kinds)
    if helper is not None:
        # Hooks whose bone is gone still carry the pin prefix.
        try:
            live = {_hook_name(_pin_id(pin)) for pin in rig_pins(rig)}
            for modifier in list(helper.modifiers):
                if kinds is None and modifier.type == 'HOOK' and modifier.name.startswith(HOOK_PREFIX) and modifier.name not in live:
                    pin_id = modifier.name[len(HOOK_PREFIX):]
                    _drop_pin_data(helper, pin_id)
        except FBP_DATA_ERRORS:
            pass
    if not pins:
        return False
    return remove_pins(rig, helper, pins)


def reset_pins(pins):
    """Return pins to their rest placement (the undeformed layer)."""
    for pin in pins:
        try:
            pin.location = _rest_location(pin)
            pin.rotation_euler = (0.0, 0.0, 0.0)
            pin.scale = (1.0, 1.0, 1.0)
        except FBP_DATA_ERRORS:
            continue


def key_pins(pins, frame=None):
    """Keyframe location, rotation and scale of each pin."""
    count = 0
    for pin in pins:
        for path in ("location", "rotation_euler", "scale"):
            try:
                if frame is None:
                    pin.keyframe_insert(path)
                else:
                    pin.keyframe_insert(path, frame=frame)
                count += 1
            except FBP_DATA_ERRORS:
                continue
    return count


def set_rest_from_current(rig, helper, plane, pins):
    """Use the current pin locations as their rest placement.

    The layer under each pin stops being deformed by it; this is how a pin is
    moved to a better spot without bending the drawing.
    """
    for pin in pins:
        try:
            pin[PIN_REST_KEY] = tuple(pin.location)
            pin.rotation_euler = (0.0, 0.0, 0.0)
            pin.scale = (1.0, 1.0, 1.0)
        except FBP_DATA_ERRORS:
            continue
    bind(rig, helper, plane, force=True)


def select_pins(context, rig, pins):
    """Show the controls in Pose Mode with exactly these pins selected."""
    armature = bones_object(rig)
    if armature is None:
        return False
    try:
        view_layer = context.view_layer
        current = view_layer.objects.active
        if current is not None and current is not armature and str(getattr(current, "mode", "OBJECT")) != 'OBJECT':
            with context.temp_override(active_object=current, object=current):
                bpy.ops.object.mode_set(mode='OBJECT')
        for item in tuple(view_layer.objects.selected):
            item.select_set(False)
        armature.hide_set(False)
        armature.select_set(True)
        view_layer.objects.active = armature
        if str(armature.mode) != 'POSE':
            with context.temp_override(active_object=armature, object=armature, selected_objects=[armature]):
                bpy.ops.object.mode_set(mode='POSE')
        wanted = {pin.name for pin in pins}
        for bone in armature.pose.bones:
            bone.select = bone.name in wanted
        if pins:
            armature.data.bones.active = pins[0].bone
        return True
    except FBP_DATA_ERRORS:
        return False


# --- Binding -----------------------------------------------------------------


def pin_stiffness(pin):
    try:
        return max(0.0, min(1.0, float(getattr(pin, "fbp_lattice_pin_stiffness", 0.0) or 0.0)))
    except FBP_DATA_ERRORS:
        return 0.0


def stiff_radius(plane, factor):
    """World radius of a Stiff Area: the full slider covers a quarter of the layer."""
    try:
        size = max(float(plane.dimensions.x), float(plane.dimensions.y))
    except FBP_DATA_ERRORS:
        size = 1.0
    return float(factor) * 0.25 * size


def _signature(rig, helper, pins):
    data = helper.data
    parts = [
        str(int(data.points_u)), str(int(data.points_v)), str(int(data.points_w)),
        "1" if bool(getattr(rig, "fbp_lattice_pins_follow_drawing", True)) else "0",
    ]
    parts.extend(f"{value:.6f}" for row in helper.matrix_world for value in row)
    if pins:
        parts.extend(f"{value:.6f}" for row in pins[0].id_data.matrix_parent_inverse for value in row)
    for pin in pins:
        parts.extend((_pin_id(pin), pin_kind(pin), f"{pin_stiffness(pin):.4f}", str(pin.get(PIN_POINT_KEY, "")), pin.name))
        parts.extend(f"{value:.6f}" for value in _rest_location(pin))
        parts.extend(f"{value:.6f}" for value in pin.bone.head_local)
        parts.append(str(getattr(pin_hook(helper, pin), "name", "")))
    return "|".join(parts)


def write_groups(helper, names, weights):
    """Write one weight column per vertex group name on the cage."""
    count = len(helper.data.points)
    indices = list(range(count))
    for name, column in zip(names, weights):
        group = helper.vertex_groups.get(name) or helper.vertex_groups.new(name=name)
        group.remove(indices)
        by_value = {}
        for index, value in enumerate(column):
            if value > 1.0e-5:
                by_value.setdefault(round(float(value), 5), []).append(index)
        for value, members in by_value.items():
            group.add(members, min(1.0, value), 'REPLACE')


def _point_handles_match_grid(helper, handles):
    data = helper.data
    grid = f"{int(data.points_u)}x{int(data.points_v)}"
    return all(str(handle.get(PIN_GRID_KEY, "")) == grid for handle in handles)


def bind(rig, helper, plane, *, force=False):
    """Rebuild Hook inverse matrices and weights when anything they depend on changed.

    Return True when a rebind happened.
    """
    if rig is None or helper is None or plane is None:
        return False
    armature = bones_object(rig)
    if armature is not None and str(getattr(armature, "mode", "OBJECT")) == 'EDIT':
        return False
    handles = [pin for pin in rig_pins(rig, kinds=(KIND_POINT,)) if pin_hook(helper, pin) is not None]
    if handles and not _point_handles_match_grid(helper, handles):
        # The cage changed resolution: rebuild the handles on the new points.
        add_point_handles(rig, helper, plane)
        return True
    pins = [pin for pin in rig_pins(rig) if pin_hook(helper, pin) is not None]
    try:
        signature = _signature(rig, helper, pins)
        if not force and str(helper.get(BIND_SIGNATURE_KEY, "") or "") == signature:
            return False
    except FBP_DATA_ERRORS:
        return False
    if not pins:
        helper.pop(BIND_SIGNATURE_KEY, None)
        return False
    helper_world = helper.matrix_world.copy()
    helper_inverse = helper_world.inverted_safe()
    controls = []
    smooth = []
    total = len(helper.data.points)
    for pin in pins:
        hook = pin_hook(helper, pin)
        rest_world = _rest_world(rig, pin)
        # Blender evaluates the hook as cage⁻¹ · bone · matrix_inverse, which is
        # the identity while the pin sits at rest.
        hook.object = pin.id_data
        hook.subtarget = pin.name
        hook.matrix_inverse = rest_world.inverted_safe() @ helper_world
        hook.center = (0.0, 0.0, 0.0)
        hook.vertex_group = _group_name(_pin_id(pin))
        if pin_kind(pin) == KIND_POINT:
            continue
        smooth.append(pin)
        controls.append({
            "points": [helper_inverse @ rest_world.translation],
            "radius": stiff_radius(plane, pin_stiffness(pin)),
        })
    if smooth:
        write_groups(helper, [_group_name(_pin_id(pin)) for pin in smooth], solve_partition(rig, helper, plane, controls))
    for handle in rig_pins(rig, kinds=(KIND_POINT,)):
        column = [0.0] * total
        try:
            index = int(handle.get(PIN_POINT_KEY, -1))
        except (TypeError, ValueError):
            index = -1
        if 0 <= index < total:
            column[index] = 1.0
        write_groups(helper, [_group_name(_pin_id(handle))], [column])
    helper[BIND_SIGNATURE_KEY] = signature
    helper.data.update_tag()
    helper.update_tag(refresh={'DATA'})
    return True


def sync_after_cage_change(rig, helper, plane):
    """Cheap entry point for the Lattice setup: rebind pins and bones if needed."""
    changed = False
    try:
        if rig_pins(rig):
            changed = bind(rig, helper, plane, force=False)
    except FBP_DATA_ERRORS:
        pass
    try:
        from .lattice_bones import bind as bind_bones, deform_bones
        armature = bones_object(rig)
        if armature is not None:
            ensure_armature(rig, helper, plane)
            if deform_bones(armature):
                changed = bind_bones(rig, helper, plane, force=False) or changed
    except (ImportError,) + FBP_DATA_ERRORS:
        pass
    return changed


# --- Weights -----------------------------------------------------------------


def _layer_image(plane):
    try:
        for slot in plane.material_slots:
            material = slot.material
            tree = getattr(material, "node_tree", None) if material is not None else None
            if tree is None:
                continue
            for node in tree.nodes:
                if node.type == 'TEX_IMAGE' and getattr(node, "image", None) is not None:
                    return node.image
    except FBP_DATA_ERRORS:
        return None
    return None


def _uv_mapping(plane):
    """Return (scale, offset) per axis mapping cage X/Y (-0.5..0.5) to image UV."""
    try:
        mesh = plane.data
        layer = mesh.uv_layers.active
        xs = [vertex.co.x for vertex in mesh.vertices]
        ys = [vertex.co.y for vertex in mesh.vertices]
        us = [loop.uv.x for loop in layer.data]
        vs = [loop.uv.y for loop in layer.data]
        # Planes are generated axis-aligned: the UV box spans the vertex box.
        if not xs or not us or max(xs) - min(xs) < 1.0e-9 or max(ys) - min(ys) < 1.0e-9:
            raise ValueError
        return (max(us) - min(us), min(us)), (max(vs) - min(vs), min(vs))
    except (AttributeError, ValueError) + FBP_DATA_ERRORS:
        return (1.0, 0.0), (1.0, 0.0)


def _alpha_sampler(plane):
    """Return alpha(u, v) for the layer image, or None when unavailable."""
    image = _layer_image(plane)
    if image is None:
        return None
    try:
        import numpy as np
        width, height = int(image.size[0]), int(image.size[1])
        channels = int(image.channels)
        if width < 1 or height < 1 or channels < 4 or width * height > _MAX_ALPHA_PIXELS:
            return None
        pixels = np.empty(width * height * channels, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        alpha = pixels[3::channels].reshape(height, width)
        if float(alpha.min()) > 0.999:
            return None
    except (ImportError, MemoryError) + FBP_DATA_ERRORS:
        return None

    def sample(u, v):
        inside = (u >= 0.0) & (u <= 1.0) & (v >= 0.0) & (v <= 1.0)
        columns = np.clip((u * width).astype(np.int64), 0, width - 1)
        rows = np.clip((v * height).astype(np.int64), 0, height - 1)
        return np.where(inside, alpha[rows, columns], 0.0)
    return sample


def _grid_rest(helper):
    import numpy as np
    data = helper.data
    points_u, points_v = int(data.points_u), int(data.points_v)
    rest = np.empty(len(data.points) * 3, dtype=np.float64)
    data.points.foreach_get("co", rest)
    # One-layer cage: U is the fastest axis, then V.
    rest = rest.reshape(-1, 3)[: points_u * points_v]
    return points_u, points_v, rest[:, 0].reshape(points_v, points_u), rest[:, 1].reshape(points_v, points_u)


def _conductance(plane, xs, ys, follow):
    """Edge conductances (horizontal, vertical) for the cage grid."""
    import numpy as np
    horizontal = np.ones((xs.shape[0], xs.shape[1] - 1))
    vertical = np.ones((xs.shape[0] - 1, xs.shape[1]))
    sampler = _alpha_sampler(plane) if follow else None
    if sampler is None:
        return horizontal, vertical
    (u_scale, u_offset), (v_scale, v_offset) = _uv_mapping(plane)

    def along(x0, y0, x1, y1):
        lowest = None
        for step in range(_EDGE_SAMPLES):
            t = step / float(_EDGE_SAMPLES - 1)
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            value = sampler((x + 0.5) * u_scale + u_offset, (y + 0.5) * v_scale + v_offset)
            lowest = value if lowest is None else np.minimum(lowest, value)
        # The weakest point decides: a thin transparent gap separates parts.
        return _TRANSPARENT_CONDUCTANCE + (1.0 - _TRANSPARENT_CONDUCTANCE) * lowest

    horizontal = along(xs[:, :-1], ys[:, :-1], xs[:, 1:], ys[:, 1:])
    vertical = along(xs[:-1, :], ys[:-1, :], xs[1:, :], ys[1:, :])
    return horizontal, vertical


def _apply_laplacian(values, horizontal, vertical):
    import numpy as np
    result = np.zeros_like(values)
    flux = horizontal * (values[:, :-1] - values[:, 1:])
    result[:, :-1] += flux
    result[:, 1:] -= flux
    flux = vertical * (values[:-1, :] - values[1:, :])
    result[:-1, :] += flux
    result[1:, :] -= flux
    return result


def _solve_dirichlet(fixed_mask, fixed_values, horizontal, vertical, diagonal):
    """Solve L·x = 0 on free nodes with fixed values (Jacobi-preconditioned CG)."""
    import numpy as np
    free = ~fixed_mask
    x = np.where(fixed_mask, fixed_values, 0.0)
    residual = -_apply_laplacian(x, horizontal, vertical)
    residual[fixed_mask] = 0.0
    preconditioned = np.where(free, residual / diagonal, 0.0)
    direction = preconditioned.copy()
    rho = float((residual * preconditioned).sum())
    tolerance = 1.0e-10 * max(1.0, float(np.abs(residual).sum()))
    for _iteration in range(max(200, 8 * x.size)):
        if abs(rho) <= tolerance:
            break
        product = _apply_laplacian(direction, horizontal, vertical)
        product[fixed_mask] = 0.0
        denominator = float((direction * product).sum())
        if abs(denominator) < 1.0e-300:
            break
        step = rho / denominator
        x += step * direction
        residual -= step * product
        preconditioned = np.where(free, residual / diagonal, 0.0)
        new_rho = float((residual * preconditioned).sum())
        direction = preconditioned + (new_rho / rho) * direction
        rho = new_rho
    return x


def compute_weights(rig, helper, plane, rest_points):
    """Return one weight list per rest point (cage point order) summing to one."""
    return solve_partition(rig, helper, plane, [{"points": [point], "radius": 0.0} for point in rest_points])


def _segment_distance(xs, ys, a, b, scale):
    """Distance (world units) from every cage point to segment a-b (cage coords)."""
    import numpy as np
    ax, ay = float(a.x) * scale[0], float(a.y) * scale[1]
    bx, by = float(b.x) * scale[0], float(b.y) * scale[1]
    px, py = xs * scale[0], ys * scale[1]
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if length < 1.0e-18:
        return np.sqrt((px - ax) ** 2 + (py - ay) ** 2)
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / length, 0.0, 1.0)
    return np.sqrt((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2)


def solve_partition(rig, helper, plane, controls):
    """Harmonic weights for a set of controls; one list per control, summing to one.

    Each control is ``{"points": [...], "radius": r}`` in cage coordinates:
    one point for a pin, a polyline (head, tail) for a bone. The cage points a
    control covers are held at weight one for it; the rest is solved.
    """
    import numpy as np
    points_u, points_v, xs, ys = _grid_rest(helper)
    count = len(controls)
    total = len(helper.data.points)
    if count == 0:
        return []
    if count == 1:
        return [[1.0] * total]
    follow = bool(getattr(rig, "fbp_lattice_pins_follow_drawing", True))
    horizontal, vertical = _conductance(plane, xs, ys, follow)
    diagonal = np.zeros((points_v, points_u))
    diagonal[:, :-1] += horizontal
    diagonal[:, 1:] += horizontal
    diagonal[:-1, :] += vertical
    diagonal[1:, :] += vertical
    diagonal = np.maximum(diagonal, 1.0e-12)
    try:
        matrix = helper.matrix_world
        scale = (float(matrix.col[0].to_3d().length), float(matrix.col[1].to_3d().length))
    except FBP_DATA_ERRORS:
        scale = (1.0, 1.0)
    cell = max(scale[0] / max(1, points_u - 1), scale[1] / max(1, points_v - 1))

    taken = {}
    centres = []
    # 1. Every control first claims the cage point nearest to each of its points.
    for index, control in enumerate(controls):
        points = list(control["points"])
        if len(points) == 2:
            # Bones: sample the inner part of the segment so joints between
            # bones stay free and bend smoothly.
            # A chain's free ends (root head, tip tail) are owned outright.
            a, b = points
            start = float(control.get("start", 0.2))
            end = float(control.get("end", 0.8))
            length = math.hypot((b.x - a.x) * scale[0], (b.y - a.y) * scale[1])
            steps = max(1, int(length / (0.5 * cell)))
            samples = [a.lerp(b, 0.5)] if length < 2.5 * cell else [
                a.lerp(b, start + (end - start) * step / float(steps)) for step in range(steps + 1)
            ]
        else:
            samples = points
        own = []
        for point in samples:
            distance = ((xs - float(point.x)) * scale[0]) ** 2 + ((ys - float(point.y)) * scale[1]) ** 2
            for flat in np.argsort(distance, axis=None)[:8]:
                flat = int(flat)
                if flat not in taken:
                    taken[flat] = index
                    own.append(divmod(flat, points_u))
                    break
        centres.append((own, len(points) == 2))
    # 2. Stiff areas and bone thickness.
    for index, control in enumerate(controls):
        radius = float(control.get("radius", 0.0) or 0.0)
        if radius <= 0.0:
            continue
        points = list(control["points"])
        if len(points) == 2:
            distance = _segment_distance(xs, ys, points[0], points[1], scale)
        else:
            distance = _segment_distance(xs, ys, points[0], points[0], scale)
        for flat in np.flatnonzero(distance.reshape(-1) <= radius):
            taken.setdefault(int(flat), index)
    # 3. Pins also hold their four neighbours: a B-spline cage averages a
    # point with its neighbours, so a single held point would let the drawing
    # under the pin lag behind it.
    for index, (own, is_segment) in enumerate(centres):
        if is_segment:
            continue
        for row, column in own:
            for d_row, d_column in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                r, c = row + d_row, column + d_column
                if 0 <= r < points_v and 0 <= c < points_u:
                    taken.setdefault(r * points_u + c, index)
    fixed_mask = np.zeros((points_v, points_u), dtype=bool)
    owner = np.full((points_v, points_u), -1)
    for flat, index in taken.items():
        row, column = divmod(flat, points_u)
        fixed_mask[row, column] = True
        owner[row, column] = index
    columns = []
    for index in range(count):
        fixed = np.where(owner == index, 1.0, 0.0)
        columns.append(np.clip(_solve_dirichlet(fixed_mask, fixed, horizontal, vertical, diagonal), 0.0, 1.0))
    stack = np.stack(columns)
    sums = stack.sum(axis=0)
    stack = stack / np.where(sums > 1.0e-12, sums, 1.0)
    result = []
    for index in range(count):
        flat = stack[index].reshape(-1).tolist()
        # Extra depth layers (never generated, but legal) follow the first layer.
        layers = max(1, total // max(1, len(flat)))
        result.append(flat * layers)
    return result


def needs_denser_cage(helper):
    data = getattr(helper, "data", None)
    if data is None:
        return False
    return max(int(data.points_u), int(data.points_v)) < 12


def puppet_grid_points(plane, long_side=24):
    """Return (points_u, points_v) for a pin-friendly cage with square cells."""
    try:
        width = max(float(plane.dimensions.x), 1.0e-6)
        height = max(float(plane.dimensions.y), 1.0e-6)
    except FBP_DATA_ERRORS:
        width = height = 1.0
    if width >= height:
        return long_side, max(4, min(long_side, int(round(long_side * height / width))))
    return max(4, min(long_side, int(round(long_side * width / height)))), long_side


def ray_plane_point(plane, origin, direction):
    """Intersect a world ray with the plane's rest surface (local Z = 0)."""
    inverse = plane.matrix_world.inverted_safe()
    local_origin = inverse @ Vector(origin)
    local_direction = inverse.to_3x3() @ Vector(direction)
    if abs(local_direction.z) < 1.0e-9:
        return None
    t = -local_origin.z / local_direction.z
    if t < 0.0:
        return None
    hit = local_origin + local_direction * t
    return plane.matrix_world @ hit


def deformed_hit(plane, depsgraph, origin, direction):
    """Ray cast the deformed layer; return (world hit, rest world point) or None.

    The rest point is recovered from the hit's UV, so a click on a bent layer
    places the pin where that part of the drawing sits on the flat layer.
    """
    evaluated = plane.evaluated_get(depsgraph)
    inverse = plane.matrix_world.inverted_safe()
    local_origin = inverse @ Vector(origin)
    local_direction = (inverse.to_3x3() @ Vector(direction)).normalized()
    try:
        success, location, _normal, face_index = evaluated.ray_cast(local_origin, local_direction)
    except FBP_DATA_ERRORS:
        return None
    if not success:
        return None
    mesh = evaluated.data
    try:
        layer = mesh.uv_layers.active
        polygon = mesh.polygons[face_index]
        corners = [mesh.vertices[mesh.loops[i].vertex_index].co for i in polygon.loop_indices]
        uvs = [layer.data[i].uv for i in polygon.loop_indices]
        weights = _polygon_weights(corners, location)
        uv = Vector((0.0, 0.0))
        for weight, value in zip(weights, uvs):
            uv += weight * value
    except (IndexError, ZeroDivisionError) + FBP_DATA_ERRORS:
        return plane.matrix_world @ location, None
    (u_scale, u_offset), (v_scale, v_offset) = _uv_mapping(plane)
    try:
        xs = [vertex.co.x for vertex in plane.data.vertices]
        ys = [vertex.co.y for vertex in plane.data.vertices]
        rest_x = min(xs) + (uv.x - u_offset) / u_scale * (max(xs) - min(xs))
        rest_y = min(ys) + (uv.y - v_offset) / v_scale * (max(ys) - min(ys))
    except (ValueError, ZeroDivisionError) + FBP_DATA_ERRORS:
        return plane.matrix_world @ location, None
    return plane.matrix_world @ location, plane.matrix_world @ Vector((rest_x, rest_y, 0.0))


def _polygon_weights(corners, point):
    """Barycentric weights of a point on a polygon, through its triangle fan."""
    for index in range(1, len(corners) - 1):
        a, b, c = corners[0], corners[index], corners[index + 1]
        v0, v1, v2 = b - a, c - a, point - a
        d00, d01, d11 = v0.dot(v0), v0.dot(v1), v1.dot(v1)
        d20, d21 = v2.dot(v0), v2.dot(v1)
        denominator = d00 * d11 - d01 * d01
        if abs(denominator) < 1.0e-18:
            continue
        v = (d11 * d20 - d01 * d21) / denominator
        w = (d00 * d21 - d01 * d20) / denominator
        u = 1.0 - v - w
        if u >= -1.0e-4 and v >= -1.0e-4 and w >= -1.0e-4:
            weights = [0.0] * len(corners)
            weights[0], weights[index], weights[index + 1] = u, v, w
            return weights
    return [1.0 / len(corners)] * len(corners)


def blended_location(rig, helper, pins, rest_world_point):
    """Where the current pins carry a rest point (used to place a new pin)."""
    pins = [pin for pin in pins if pin_kind(pin) != KIND_POINT]
    if not pins:
        return Vector(rest_world_point)
    try:
        import numpy as np
        helper_world = helper.matrix_world
        helper_inverse = helper_world.inverted_safe()
        local = helper_inverse @ Vector(rest_world_point)
        rest_points = [helper_inverse @ _rest_world(rig, pin).translation for pin in pins]
        weights = compute_weights(rig, helper, rig.fbp_plane_target, rest_points)
        _u, _v, xs, ys = _grid_rest(helper)
        nearest = int(np.argmin((xs - float(local.x)) ** 2 + (ys - float(local.y)) ** 2))
        result = Vector((0.0, 0.0, 0.0))
        total = 0.0
        for pin, column in zip(pins, weights):
            weight = float(column[nearest])
            hook = helper_inverse @ pin_world(rig, pin) @ _rest_world(rig, pin).inverted_safe() @ helper_world
            result += weight * (helper_world @ (hook @ local))
            total += weight
        return result / total if total > 1.0e-9 else Vector(rest_world_point)
    except (ImportError, IndexError, ZeroDivisionError) + FBP_DATA_ERRORS:
        return Vector(rest_world_point)
