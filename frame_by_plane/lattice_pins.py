"""Puppet pins for the Lattice (Deform Plane) effect.

A pin is a small Empty parented to the layer rig. Each pin drives the cage
through a native Hook modifier on the Lattice object, restricted to a vertex
group whose weights say how much of the cage follows that pin. Moving,
rotating or scaling a pin therefore bends the layer like a puppet, the pins
keyframe like any other object, and nothing runs in Python at render time.

Weights are harmonic: every cage point blends the pins smoothly and the
weights of all pins sum to one, so a pin that is left alone anchors its area
while its neighbours move. With Follow Drawing the solve uses the layer's
alpha as conductance, so a pin on a hand does not drag a separate, nearby part
of the drawing across a transparent gap.

Pins live in a frame aligned with the plane (local Z is the plane normal) so G
moves them across the drawing and R rotates them in its plane. A pin stores
its rest location; the Hook's inverse matrix is rebuilt from it whenever the
cage moves or changes resolution, and the weights are rebuilt with it.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Vector

from .runtime import FBP_DATA_ERRORS


PIN_OWNER_KEY = "fbp_lattice_pin_owner"
PIN_ID_KEY = "fbp_lattice_pin_id"
PIN_REST_KEY = "fbp_lattice_pin_rest"
BIND_SIGNATURE_KEY = "fbp_lattice_pins_bind"
GROUP_PREFIX = "FBP Pin "
HOOK_PREFIX = "FBP Pin • "

# Conductance across fully transparent pixels. Small but non-zero keeps every
# cage point connected, so empty areas still get smooth, well-defined weights.
_TRANSPARENT_CONDUCTANCE = 1.0e-3
_EDGE_SAMPLES = 9
# Largest image read for Follow Drawing (pixels). Bigger images fall back to an
# even solve instead of copying hundreds of megabytes of pixels.
_MAX_ALPHA_PIXELS = 4096 * 4096


def is_pin(obj):
    try:
        return bool(obj is not None and str(obj.get(PIN_ID_KEY, "") or ""))
    except FBP_DATA_ERRORS:
        return False


def pin_owner(obj):
    """Return the layer rig of a pin, or None."""
    if not is_pin(obj):
        return None
    parent = getattr(obj, "parent", None)
    if parent is not None and bool(getattr(parent, "is_fbp_control", False)):
        return parent
    try:
        owner = bpy.data.objects.get(str(obj.get(PIN_OWNER_KEY, "") or ""))
    except FBP_DATA_ERRORS:
        return None
    return owner if owner is not None and bool(getattr(owner, "is_fbp_control", False)) else None


def rig_pins(rig):
    """Return the pins of a layer, in creation order."""
    if rig is None:
        return []
    found = []
    try:
        for obj in tuple(getattr(rig, "children", ()) or ()):
            if is_pin(obj):
                found.append(obj)
    except FBP_DATA_ERRORS:
        return []

    def order(pin):
        try:
            return int(str(pin.get(PIN_ID_KEY, "0")).split(".")[0])
        except (TypeError, ValueError):
            return 0
    return sorted(found, key=order)


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
        return Vector(tuple(pin.location))
    return Vector(values)


def plane_frame(plane, helper):
    """Return the pin frame: the cage centre with the plane's rotation, unit scale."""
    rotation = plane.matrix_world.to_quaternion().to_matrix().to_4x4()
    return Matrix.Translation(helper.matrix_world.translation) @ rotation


def _rest_world(rig, pin):
    """World matrix of a pin at rest, computed without a depsgraph update."""
    return rig.matrix_world @ pin.matrix_parent_inverse @ Matrix.Translation(_rest_location(pin))


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


def _pin_display_size(plane):
    try:
        size = max(float(plane.dimensions.x), float(plane.dimensions.y))
    except FBP_DATA_ERRORS:
        size = 1.0
    return max(0.005, size * 0.03)


def add_pin(rig, helper, plane, world_location):
    """Create a pin at a world location on the layer and bind it. Return the pin."""
    pin_id = _next_pin_id(rig)
    frame = plane_frame(plane, helper)
    pin = bpy.data.objects.new(f"Pin {pin_id} • {rig.name}", None)
    pin[PIN_OWNER_KEY] = str(rig.name)
    pin[PIN_ID_KEY] = pin_id
    collections = tuple(getattr(helper, "users_collection", ()) or ()) or (bpy.context.scene.collection,)
    for collection in collections:
        collection.objects.link(pin)
    pin.parent = rig
    pin.matrix_parent_inverse = rig.matrix_world.inverted_safe() @ frame
    local = frame.inverted_safe() @ Vector(world_location)
    local.z = 0.0
    pin.location = local
    pin.rotation_mode = 'XYZ'
    pin[PIN_REST_KEY] = tuple(local)
    pin.empty_display_type = 'SPHERE'
    pin.empty_display_size = _pin_display_size(plane)
    pin.show_in_front = True
    pin.show_name = False
    pin.hide_render = True
    # Pins move across the drawing and rotate in its plane.
    pin.lock_location = (False, False, True)
    pin.lock_rotation = (True, True, False)
    pin.lock_scale = (False, False, True)

    helper.vertex_groups.new(name=_group_name(pin_id))
    hook = helper.modifiers.new(_hook_name(pin_id), 'HOOK')
    hook.object = pin
    hook.vertex_group = _group_name(pin_id)
    hook.falloff_type = 'NONE'
    hook.strength = 1.0
    hook.show_in_editmode = True
    hook.show_on_cage = True
    bind(rig, helper, plane, force=True)
    return pin


def remove_pin(rig, helper, pin):
    pin_id = _pin_id(pin)
    if helper is not None:
        try:
            hook = helper.modifiers.get(_hook_name(pin_id))
            if hook is not None:
                helper.modifiers.remove(hook)
            group = helper.vertex_groups.get(_group_name(pin_id))
            if group is not None:
                helper.vertex_groups.remove(group)
        except FBP_DATA_ERRORS:
            pass
    try:
        bpy.data.objects.remove(pin, do_unlink=True)
    except FBP_DATA_ERRORS:
        return False
    if helper is not None and rig is not None:
        plane = getattr(rig, "fbp_plane_target", None)
        if plane is not None:
            bind(rig, helper, plane, force=True)
    return True


def remove_all_pins(rig, helper=None):
    """Remove every pin of a layer and its Hook and vertex group."""
    changed = False
    pins = rig_pins(rig)
    if rig is not None:
        # Pins whose parenting was lost still carry the owner name.
        owner_name = str(getattr(rig, "name", "") or "")
        try:
            for obj in tuple(bpy.data.objects):
                if obj not in pins and is_pin(obj) and str(obj.get(PIN_OWNER_KEY, "") or "") == owner_name:
                    pins.append(obj)
        except FBP_DATA_ERRORS:
            pass
    for pin in pins:
        pin_id = _pin_id(pin)
        if helper is not None:
            try:
                hook = helper.modifiers.get(_hook_name(pin_id))
                if hook is not None:
                    helper.modifiers.remove(hook)
                group = helper.vertex_groups.get(_group_name(pin_id))
                if group is not None:
                    helper.vertex_groups.remove(group)
            except FBP_DATA_ERRORS:
                pass
        try:
            bpy.data.objects.remove(pin, do_unlink=True)
            changed = True
        except FBP_DATA_ERRORS:
            continue
    if helper is not None:
        try:
            helper.pop(BIND_SIGNATURE_KEY, None)
        except FBP_DATA_ERRORS:
            pass
    return changed


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


# --- Binding -----------------------------------------------------------------


def _signature(rig, helper, pins):
    data = helper.data
    parts = [
        str(int(data.points_u)), str(int(data.points_v)), str(int(data.points_w)),
        "1" if bool(getattr(rig, "fbp_lattice_pins_follow_drawing", True)) else "0",
    ]
    parts.extend(f"{value:.6f}" for row in helper.matrix_world for value in row)
    for pin in pins:
        parts.append(_pin_id(pin))
        parts.extend(f"{value:.6f}" for value in _rest_location(pin))
        parts.extend(f"{value:.6f}" for row in pin.matrix_parent_inverse for value in row)
        parts.append(str(getattr(pin_hook(helper, pin), "name", "")))
    return "|".join(parts)


def bind(rig, helper, plane, *, force=False):
    """Rebuild Hook inverse matrices and weights when anything they depend on changed.

    Return True when a rebind happened.
    """
    if rig is None or helper is None or plane is None:
        return False
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
    rest_points = []
    for pin in pins:
        hook = pin_hook(helper, pin)
        rest_world = _rest_world(rig, pin)
        # Blender evaluates the hook as cage⁻¹ · pin · matrix_inverse, which is
        # the identity while the pin sits at rest.
        hook.matrix_inverse = rest_world.inverted_safe() @ helper_world
        hook.center = (0.0, 0.0, 0.0)
        hook.vertex_group = _group_name(_pin_id(pin))
        rest_points.append(helper_inverse @ rest_world.translation)
    weights = compute_weights(rig, helper, plane, rest_points)
    count = len(helper.data.points)
    indices = list(range(count))
    for pin, column in zip(pins, weights):
        name = _group_name(_pin_id(pin))
        group = helper.vertex_groups.get(name) or helper.vertex_groups.new(name=name)
        group.remove(indices)
        by_value = {}
        for index, value in enumerate(column):
            if value > 1.0e-5:
                by_value.setdefault(round(float(value), 5), []).append(index)
        for value, members in by_value.items():
            group.add(members, min(1.0, value), 'REPLACE')
    helper[BIND_SIGNATURE_KEY] = signature
    helper.data.update_tag()
    helper.update_tag(refresh={'DATA'})
    return True


def sync_after_cage_change(rig, helper, plane):
    """Cheap entry point for the Lattice setup: rebind only if needed."""
    try:
        if rig_pins(rig):
            return bind(rig, helper, plane, force=False)
    except FBP_DATA_ERRORS:
        return False
    return False


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
    """Return one weight list per pin (cage point order) summing to one."""
    import numpy as np
    points_u, points_v, xs, ys = _grid_rest(helper)
    count = len(rest_points)
    total = len(helper.data.points)
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

    # Each pin holds the nearest free cage point and, where free, its four
    # neighbours: a B-spline cage averages a point with its neighbours, so a
    # single held point would let the drawing under the pin lag behind it.
    centres = []
    taken = {}
    for index, point in enumerate(rest_points):
        distance = (xs - float(point.x)) ** 2 + (ys - float(point.y)) ** 2
        for flat in np.argsort(distance, axis=None):
            flat = int(flat)
            if flat not in taken:
                taken[flat] = index
                centres.append(divmod(flat, points_u))
                break
    for index, (row, column) in enumerate(centres):
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
            hook = helper_inverse @ pin.matrix_world @ _rest_world(rig, pin).inverted_safe() @ helper_world
            result += weight * (helper_world @ (hook @ local))
            total += weight
        return result / total if total > 1.0e-9 else Vector(rest_world_point)
    except (ImportError, IndexError, ZeroDivisionError) + FBP_DATA_ERRORS:
        return Vector(rest_world_point)
