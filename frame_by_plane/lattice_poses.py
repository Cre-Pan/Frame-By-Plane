"""Animatable deformation poses for the Lattice (Deform Plane) effect.

A pose is a shape key on the Frame By Plane Lattice cage. Its slider blends the
pose in (and, from -1 to 0, its mirror), so poses mix and can be keyframed like
any other property. The "Basis" key holds the rest cage; tools that rewrite the
rest cage (Reset, Camera Flatten) move every pose by the same offset so each
pose keeps its own deformation on top of the new rest shape.

Coordinates are Blender Lattice ``co_deform`` values: -0.5..0.5 across the cage
in X and Y. The cage is very thin in Z, so depth offsets are authored in units
of the cage width and converted with :func:`_depth_ratio`.
"""

from __future__ import annotations

import math

from .runtime import FBP_DATA_ERRORS


BASIS_NAME = "Basis"


def _sway(x, y, z, depth):
    return x + 0.35 * (y + 0.5) ** 2, y, z


def _arch(x, y, z, depth):
    return x, y + 0.25 * (1.0 - 4.0 * x * x), z


def _squash(x, y, z, depth):
    # Anchored on the bottom edge: the layer stays on its ground line.
    return x * 1.25, (y + 0.5) * 0.75 - 0.5, z


def _taper(x, y, z, depth):
    return x * (1.0 + y), y, z


def _shear(x, y, z, depth):
    return x + 0.35 * (y + 0.5), y, z


def _bulge(x, y, z, depth):
    return x * (1.0 + 0.35 * (1.0 - 4.0 * y * y)), y * (1.0 + 0.35 * (1.0 - 4.0 * x * x)), z


def _wave(x, y, z, depth):
    return x, y + 0.1 * math.sin(2.0 * math.pi * (x + 0.5)), z


def _flag(x, y, z, depth):
    # Anchored on the left edge like a flag on its pole.
    return x, y, z + depth * 0.12 * math.sin(2.0 * math.pi * (x + 0.5)) * (x + 0.5)


def _curl(x, y, z, depth):
    return x, y, z + depth * 0.45 * (x + 0.5) ** 2


# id: (label, icon, description, function, minimum control points (u, v))
PRESETS = {
    "SWAY": ("Sway", "FORCE_WIND", "Bend sideways with the bottom edge fixed (plants, hair, cloth). Negative values sway the other way", _sway, (2, 3)),
    "ARCH": ("Arch", "SPHERECURVE", "Bend the whole layer into an arch. Negative values bend it downwards", _arch, (3, 2)),
    "SQUASH": ("Squash / Stretch", "FULLSCREEN_EXIT", "Squash on the bottom edge; negative values stretch upwards", _squash, (2, 2)),
    "TAPER": ("Taper", "MESH_CONE", "Widen the top and narrow the bottom; negative values do the opposite", _taper, (2, 2)),
    "SHEAR": ("Shear", "MOD_SIMPLEDEFORM", "Lean the layer with the bottom edge fixed", _shear, (2, 2)),
    "BULGE": ("Bulge / Pinch", "SPHERE", "Push the middle outwards; negative values pinch it inwards", _bulge, (3, 3)),
    "WAVE": ("Wave", "MOD_WAVE", "One wave across the layer in its own plane", _wave, (6, 2)),
    "FLAG": ("Flag", "MOD_CLOTH", "Wave in depth from the left edge, like a flag on its pole", _flag, (6, 2)),
    "CURL": ("Curl", "MOD_CURVE", "Curl the right side towards the camera; negative values curl it away", _curl, (4, 2)),
}

def _shape_keys(helper):
    data = getattr(helper, "data", None) if helper is not None else None
    return getattr(data, "shape_keys", None) if data is not None else None


def lattice_poses(helper):
    """Return the pose shape keys (every key except the Basis)."""
    keys = _shape_keys(helper)
    if keys is None:
        return ()
    try:
        blocks = tuple(keys.key_blocks)
    except FBP_DATA_ERRORS:
        return ()
    return blocks[1:]


def _depth_ratio(helper):
    """Return how many cage Z units correspond to one cage X unit."""
    try:
        matrix = helper.matrix_world
        width = float(matrix.col[0].to_3d().length)
        depth = float(matrix.col[2].to_3d().length)
        return width / depth if depth > 1.0e-9 else 1.0
    except FBP_DATA_ERRORS:
        return 1.0


def _grid_size(helper):
    data = helper.data
    return max(2, int(data.points_u)), max(2, int(data.points_v))


def _read_points(helper):
    data = helper.data
    values = [0.0] * (len(data.points) * 3)
    data.points.foreach_get("co_deform", values)
    return values


def _read_key(block):
    values = [0.0] * (len(block.data) * 3)
    block.data.foreach_get("co", values)
    return values


def write_rest_cage(helper, coordinates):
    """Write the rest cage, moving every pose by the same per-point offset.

    Without shape keys this is a plain ``co_deform`` write. With poses Blender
    evaluates the keys instead, so the Basis key is rewritten too and each pose
    keeps its offset from the Basis.
    """
    data = helper.data
    data.points.foreach_set("co_deform", coordinates)
    keys = _shape_keys(helper)
    if keys is not None and len(keys.key_blocks):
        basis = keys.key_blocks[0]
        old_basis = _read_key(basis)
        offsets = [new - old for new, old in zip(coordinates, old_basis)]
        for block in keys.key_blocks:
            values = coordinates if block == basis else [
                value + offset for value, offset in zip(_read_key(block), offsets)
            ]
            block.data.foreach_set("co", values)
    data.update_tag()
    helper.update_tag(refresh={'DATA'})


def _rest_grid(points_u, points_v):
    values = []
    for v_index in range(points_v):
        y = v_index / float(points_v - 1) - 0.5
        for u_index in range(points_u):
            values.extend((u_index / float(points_u - 1) - 0.5, y, 0.0))
    return values


def _bspline_axes(helper):
    data = helper.data
    return (
        str(getattr(data, "interpolation_type_u", "")) == "KEY_BSPLINE",
        str(getattr(data, "interpolation_type_v", "")) == "KEY_BSPLINE",
    )


def _filter_lines(values, points_u, points_v, axis, inverse):
    """Apply (or invert) Blender's B-spline node weights along one grid axis.

    At a control point the Lattice B-spline evaluates offsets as
    (d[i-1] + 4 d[i] + d[i+1]) / 6 with the end points repeated, so the cage
    surface misses its control points. Inverting this tridiagonal operator
    gives control points whose surface passes through the wanted shape.
    """
    count, lines = (points_u, points_v) if axis == 0 else (points_v, points_u)
    result = list(values)
    sixth = 1.0 / 6.0
    for line in range(lines):
        indices = [
            ((line * points_u + i) if axis == 0 else (i * points_u + line)) * 3
            for i in range(count)
        ]
        diagonal = [4.0 * sixth] * count
        diagonal[0] = diagonal[-1] = 5.0 * sixth
        for component in range(3):
            data = [values[index + component] for index in indices]
            if not inverse:
                output = [
                    sixth * data[max(i - 1, 0)] + 4.0 * sixth * data[i] + sixth * data[min(i + 1, count - 1)]
                    for i in range(count)
                ]
            else:
                # Thomas algorithm with the repeated-end diagonal.
                c_prime = [0.0] * count
                d_prime = [0.0] * count
                c_prime[0] = sixth / diagonal[0]
                d_prime[0] = data[0] / diagonal[0]
                for i in range(1, count):
                    denominator = diagonal[i] - sixth * c_prime[i - 1]
                    c_prime[i] = sixth / denominator
                    d_prime[i] = (data[i] - sixth * d_prime[i - 1]) / denominator
                output = [0.0] * count
                output[-1] = d_prime[-1]
                for i in range(count - 2, -1, -1):
                    output[i] = d_prime[i] - c_prime[i] * output[i + 1]
            for index, value in zip(indices, output):
                result[index + component] = value
    return result


def _surface_from_controls(helper, controls, points_u, points_v):
    """Return where the cage surface passes at each control point's grid spot."""
    rest = _rest_grid(points_u, points_v)
    offsets = [value - base for value, base in zip(controls, rest)]
    bspline_u, bspline_v = _bspline_axes(helper)
    if bspline_u:
        offsets = _filter_lines(offsets, points_u, points_v, 0, False)
    if bspline_v:
        offsets = _filter_lines(offsets, points_u, points_v, 1, False)
    return [base + offset for base, offset in zip(rest, offsets)]


def _controls_from_surface(helper, surface, points_u, points_v):
    """Inverse of :func:`_surface_from_controls`."""
    rest = _rest_grid(points_u, points_v)
    offsets = [value - base for value, base in zip(surface, rest)]
    bspline_u, bspline_v = _bspline_axes(helper)
    if bspline_u:
        offsets = _filter_lines(offsets, points_u, points_v, 0, True)
    if bspline_v:
        offsets = _filter_lines(offsets, points_u, points_v, 1, True)
    return [base + offset for base, offset in zip(rest, offsets)]


def _resample(values, old_u, old_v, new_u, new_v):
    """Bilinearly resample a one-layer cage (flat xyz list) onto a new grid."""
    def point(u, v):
        index = (v * old_u + u) * 3
        return values[index], values[index + 1], values[index + 2]

    result = []
    for v_index in range(new_v):
        t = v_index / float(new_v - 1) * (old_v - 1)
        v0 = min(int(math.floor(t)), old_v - 2)
        fv = t - v0
        for u_index in range(new_u):
            s = u_index / float(new_u - 1) * (old_u - 1)
            u0 = min(int(math.floor(s)), old_u - 2)
            fu = s - u0
            p00, p10 = point(u0, v0), point(u0 + 1, v0)
            p01, p11 = point(u0, v0 + 1), point(u0 + 1, v0 + 1)
            for axis in range(3):
                bottom = p00[axis] + (p10[axis] - p00[axis]) * fu
                top = p01[axis] + (p11[axis] - p01[axis]) * fu
                result.append(bottom + (top - bottom) * fv)
    return result


def resize_preserving_shape(helper, points_u, points_v):
    """Change the cage resolution while keeping its shape, poses and animation.

    Blender locks ``points_u``/``points_v`` while shape keys exist, so poses are
    captured, removed, resampled onto the new grid and recreated with their
    names, slider ranges, values and the Key's animation action.
    Return True when the resolution changed.
    """
    data = helper.data
    old_u, old_v = _grid_size(helper)
    if (old_u, old_v) == (int(points_u), int(points_v)) and int(data.points_w) == 1:
        return False
    one_layer = int(data.points_w) == 1
    rest = _read_points(helper) if one_layer else None

    def resampled(controls):
        # Resample what is visible (the surface), not the control points, so
        # B-spline cages keep the same look on the new grid.
        surface = _surface_from_controls(helper, controls, old_u, old_v)
        return _controls_from_surface(
            helper, _resample(surface, old_u, old_v, new_u, new_v), new_u, new_v
        )
    keys = _shape_keys(helper)
    saved = []
    action = None
    if keys is not None:
        try:
            action = keys.animation_data.action if keys.animation_data else None
        except FBP_DATA_ERRORS:
            action = None
        for block in keys.key_blocks:
            saved.append({
                "name": str(block.name),
                "values": _read_key(block) if one_layer else None,
                "value": float(block.value),
                "slider_min": float(block.slider_min),
                "slider_max": float(block.slider_max),
                "mute": bool(block.mute),
            })
        if saved and one_layer:
            # Pose offsets are measured from the Basis; keep its exact shape.
            rest = saved[0]["values"]
        helper.shape_key_clear()
    new_u, new_v = int(points_u), int(points_v)
    new_rest = resampled(rest) if rest is not None else None
    new_keys = [
        resampled(entry["values"]) if entry["values"] is not None else None
        for entry in saved
    ]
    data.points_u = new_u
    data.points_v = new_v
    data.points_w = 1
    if new_rest is not None:
        data.points.foreach_set("co_deform", new_rest)
    if saved:
        for index, entry in enumerate(saved):
            block = helper.shape_key_add(name=entry["name"], from_mix=False)
            if new_keys[index] is not None and index:
                block.data.foreach_set("co", new_keys[index])
            block.slider_min = entry["slider_min"]
            block.slider_max = entry["slider_max"]
            block.value = entry["value"]
            block.mute = entry["mute"]
        if action is not None:
            keys = _shape_keys(helper)
            if keys is not None:
                if keys.animation_data is None:
                    keys.animation_data_create()
                keys.animation_data.action = action
    data.update_tag()
    helper.update_tag(refresh={'DATA'})
    return True


def _ensure_basis(helper):
    keys = _shape_keys(helper)
    if keys is None or not len(keys.key_blocks):
        helper.shape_key_add(name=BASIS_NAME, from_mix=False)
    return _shape_keys(helper)


def _unique_name(helper, base):
    names = {block.name for block in lattice_poses(helper)}
    if base not in names:
        return base
    index = 2
    while f"{base} {index}" in names:
        index += 1
    return f"{base} {index}"


def preset_minimum_points(preset_id):
    return PRESETS.get(str(preset_id or "").upper(), (None, None, None, None, (2, 2)))[4]


def add_pose(helper, preset_id=""):
    """Add a pose slider; a preset fills it, an empty id starts from the Basis.

    Return the new shape key.
    """
    keys = _ensure_basis(helper)
    basis = keys.key_blocks[0]
    preset = PRESETS.get(str(preset_id or "").upper())
    label = preset[0] if preset else "Pose"
    block = helper.shape_key_add(name=_unique_name(helper, label), from_mix=False)
    block.slider_min = -1.0
    block.slider_max = 1.0
    if preset is not None:
        function = preset[3]
        depth = _depth_ratio(helper)
        points_u, points_v = _grid_size(helper)
        one_layer = int(helper.data.points_w) == 1
        source = _read_key(basis)
        if one_layer:
            # Deform the visible rest surface, then fit control points so a
            # B-spline cage passes through the preset shape at every grid spot.
            source = _surface_from_controls(helper, source, points_u, points_v)
        values = []
        for index in range(0, len(source), 3):
            values.extend(function(source[index], source[index + 1], source[index + 2], depth))
        if one_layer:
            values = _controls_from_surface(helper, values, points_u, points_v)
        block.data.foreach_set("co", values)
    block.value = 1.0
    helper.data.update_tag()
    helper.update_tag(refresh={'DATA'})
    return block


def remove_pose(helper, name):
    """Remove one pose; dropping the last pose also removes the Basis key."""
    keys = _shape_keys(helper)
    if keys is None:
        return False
    block = keys.key_blocks.get(str(name or ""))
    if block is None or block == keys.key_blocks[0]:
        return False
    helper.shape_key_remove(block)
    keys = _shape_keys(helper)
    if keys is not None and len(keys.key_blocks) == 1:
        # Keep the rest cage as plain lattice points before clearing the Basis.
        rest = _read_key(keys.key_blocks[0])
        helper.shape_key_clear()
        helper.data.points.foreach_set("co_deform", rest)
    helper.data.update_tag()
    helper.update_tag(refresh={'DATA'})
    return True


def set_active_pose(helper, name=""):
    """Make a pose the shape edited in the cage ("" returns to the Basis)."""
    keys = _shape_keys(helper)
    if keys is None:
        return False
    index = keys.key_blocks.find(str(name)) if name else 0
    if index < 0:
        return False
    helper.active_shape_key_index = index
    # Show the pose at full strength while it is being shaped.
    helper.show_only_shape_key = bool(name)
    return True
