"""Programmatically generated shader groups for Frame by Plane effects.

These groups are kept in Python rather than the bundled .blend library so their
interfaces can evolve together with the add-on and remain available when an
older asset library is present in an existing Blender file.
"""

from pathlib import Path

import bpy

from .matrix_presets import (
    ASCII_ATLAS_CELL_HEIGHT,
    ASCII_ATLAS_CELL_WIDTH,
    ASCII_ATLAS_COLUMNS,
    ASCII_ATLAS_REVISION,
    ASCII_ATLAS_VERSION,
    ASCII_PRESETS,
)


BUILTIN_EFFECT_IDS = {
    "PIXELATE",
    "DIGITAL_NOISE",
    "CHROMA_KEY",
    "HALFTONE",
    "DOT_MATRIX",
    "ASCII_MATRIX",
    "TEXT_MATRIX",
    "WIND_BENDER",
}


def _socket(group, name, in_out, socket_type, *, default=None, minimum=None, maximum=None):
    socket = group.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    if default is not None:
        try:
            socket.default_value = default
        except (AttributeError, TypeError, ValueError):
            pass
    if minimum is not None:
        try:
            socket.min_value = minimum
        except (AttributeError, TypeError, ValueError):
            pass
    if maximum is not None:
        try:
            socket.max_value = maximum
        except (AttributeError, TypeError, ValueError):
            pass
    return socket


def _node(group, node_type, name, x, y):
    node = group.nodes.new(node_type)
    node.name = name
    node.label = name
    node.location = (x, y)
    return node


def _input(node, name, fallback=None):
    try:
        socket = node.inputs.get(name)
        if socket is not None:
            return socket
    except (AttributeError, TypeError, ValueError):
        pass
    if fallback is not None:
        try:
            return node.inputs[fallback]
        except (AttributeError, IndexError, TypeError, ValueError):
            pass
    return None


def _output(node, name, fallback=None):
    try:
        socket = node.outputs.get(name)
        if socket is not None:
            return socket
    except (AttributeError, TypeError, ValueError):
        pass
    if fallback is not None:
        try:
            return node.outputs[fallback]
        except (AttributeError, IndexError, TypeError, ValueError):
            pass
    return None


def _math(group, operation, name, x, y, value_1=None, value_2=None):
    node = _node(group, "ShaderNodeMath", name, x, y)
    node.operation = operation
    if value_1 is not None:
        node.inputs[0].default_value = value_1
    if value_2 is not None:
        node.inputs[1].default_value = value_2
    return node


def _vector_math(group, operation, name, x, y):
    node = _node(group, "ShaderNodeVectorMath", name, x, y)
    node.operation = operation
    return node


def _mix_rgb(group, blend_type, name, x, y, fac=1.0):
    node = _node(group, "ShaderNodeMixRGB", name, x, y)
    node.blend_type = blend_type
    node.inputs[0].default_value = fac
    try:
        node.use_clamp = True
    except AttributeError:
        pass
    return node


def _group_io(group):
    inp = _node(group, "NodeGroupInput", "Group Input", -900, 0)
    out = _node(group, "NodeGroupOutput", "Group Output", 900, 0)
    return inp, out


def _tag(group, effect_id, definition):
    group.use_fake_user = True
    group["fbp_effect_id"] = effect_id
    group["fbp_effect_asset_id"] = str(definition.get("asset_id", "") or "")
    if str(definition.get("kind", "")) == "GEOMETRY":
        group["fbp_geometry_effect_id"] = str(definition.get("asset_id", "") or "")
    else:
        group["fbp_shader_effect_id"] = str(definition.get("asset_id", "") or "")
    group["fbp_builtin_effect"] = True
    group["fbp_builtin_effect_version"] = 5
    return group


def _create_pixelate(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Vector", "INPUT", "NodeSocketVector", default=(0.0, 0.0, 0.0))
    _socket(group, "Resolution", "INPUT", "NodeSocketFloat", default=64.0, minimum=1.0, maximum=4096.0)
    _socket(group, "Aspect Ratio", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.001, maximum=1000.0)
    _socket(group, "Vector Out", "OUTPUT", "NodeSocketVector")
    inp, out = _group_io(group)

    separate = _node(group, "ShaderNodeSeparateXYZ", "Separate UV", -700, 20)
    x_mul = _math(group, "MULTIPLY", "X Cells", -500, 150)
    x_floor = _math(group, "FLOOR", "X Floor", -320, 150)
    x_half = _math(group, "ADD", "X Center", -140, 150, value_2=0.5)
    x_div = _math(group, "DIVIDE", "X Normalize", 40, 150)

    y_res = _math(group, "DIVIDE", "Y Resolution", -500, -120)
    y_res.inputs[0].default_value = 64.0
    y_res.inputs[1].default_value = 1.0
    y_mul = _math(group, "MULTIPLY", "Y Cells", -320, -120)
    y_floor = _math(group, "FLOOR", "Y Floor", -140, -120)
    y_half = _math(group, "ADD", "Y Center", 40, -120, value_2=0.5)
    y_div = _math(group, "DIVIDE", "Y Normalize", 220, -120)
    combine = _node(group, "ShaderNodeCombineXYZ", "Pixelated UV", 470, 40)

    links = group.links
    links.new(inp.outputs["Vector"], separate.inputs[0])
    links.new(separate.outputs["X"], x_mul.inputs[0])
    links.new(inp.outputs["Resolution"], x_mul.inputs[1])
    links.new(x_mul.outputs[0], x_floor.inputs[0])
    links.new(x_floor.outputs[0], x_half.inputs[0])
    links.new(x_half.outputs[0], x_div.inputs[0])
    links.new(inp.outputs["Resolution"], x_div.inputs[1])

    links.new(inp.outputs["Resolution"], y_res.inputs[0])
    links.new(inp.outputs["Aspect Ratio"], y_res.inputs[1])
    links.new(separate.outputs["Y"], y_mul.inputs[0])
    links.new(y_res.outputs[0], y_mul.inputs[1])
    links.new(y_mul.outputs[0], y_floor.inputs[0])
    links.new(y_floor.outputs[0], y_half.inputs[0])
    links.new(y_half.outputs[0], y_div.inputs[0])
    links.new(y_res.outputs[0], y_div.inputs[1])

    links.new(x_div.outputs[0], combine.inputs["X"])
    links.new(y_div.outputs[0], combine.inputs["Y"])
    links.new(separate.outputs["Z"], combine.inputs["Z"])
    links.new(combine.outputs[0], out.inputs["Vector Out"])
    return group


def _create_digital_noise(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Luminance Noise", "INPUT", "NodeSocketFloat", default=0.12, minimum=0.0, maximum=1.0)
    _socket(group, "Chroma Noise", "INPUT", "NodeSocketFloat", default=0.08, minimum=0.0, maximum=1.0)
    _socket(group, "Noise Scale", "INPUT", "NodeSocketFloat", default=500.0, minimum=1.0, maximum=10000.0)
    _socket(group, "Shadow Bias", "INPUT", "NodeSocketFloat", default=0.65, minimum=0.0, maximum=2.0)
    _socket(group, "Animate (W)", "INPUT", "NodeSocketFloat", default=0.0, minimum=-10000.0, maximum=10000.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links

    luma = _node(group, "ShaderNodeRGBToBW", "Source Luminance", -680, 280)
    inverse_luma = _math(group, "SUBTRACT", "Shadow Amount", -500, 280, value_1=1.0)
    shadow_mul = _math(group, "MULTIPLY", "Shadow Bias", -320, 280)
    shadow_add = _math(group, "ADD", "Shadow Gain", -140, 280, value_2=1.0)

    noise_l = _node(group, "ShaderNodeTexNoise", "Luminance Noise", -620, 40)
    noise_l.noise_dimensions = "4D"
    noise_l.inputs["Detail"].default_value = 2.0
    noise_l.inputs["Roughness"].default_value = 0.65
    centered_l = _math(group, "SUBTRACT", "Center Luminance", -380, 40, value_2=0.5)
    amount_l = _math(group, "MULTIPLY", "Luminance Amount", -200, 40)
    shadowed_l = _math(group, "MULTIPLY", "Shadow Weighted Luminance", -20, 40)
    add_luma = _mix_rgb(group, "ADD", "Add Luminance Noise", 180, 100)

    noise_c = _node(group, "ShaderNodeTexNoise", "Chromatic Noise", -620, -260)
    noise_c.noise_dimensions = "4D"
    noise_c.inputs["Detail"].default_value = 1.0
    noise_c.inputs["Roughness"].default_value = 0.55
    noise_w_offset = _math(group, "ADD", "Chroma Seed Offset", -800, -360, value_2=19.37)
    center_color = _vector_math(group, "SUBTRACT", "Center Chroma", -360, -260)
    center_color.inputs[1].default_value = (0.5, 0.5, 0.5)
    scale_color = _vector_math(group, "SCALE", "Chroma Amount", -120, -260)
    add_chroma = _mix_rgb(group, "ADD", "Add Chroma Noise", 420, 20)

    links.new(inp.outputs["Color In"], luma.inputs[0])
    links.new(luma.outputs[0], inverse_luma.inputs[1])
    links.new(inverse_luma.outputs[0], shadow_mul.inputs[0])
    links.new(inp.outputs["Shadow Bias"], shadow_mul.inputs[1])
    links.new(shadow_mul.outputs[0], shadow_add.inputs[0])

    for noise in (noise_l, noise_c):
        links.new(inp.outputs["UV Vector"], noise.inputs["Vector"])
        links.new(inp.outputs["Noise Scale"], noise.inputs["Scale"])
    links.new(inp.outputs["Animate (W)"], noise_l.inputs["W"])
    links.new(inp.outputs["Animate (W)"], noise_w_offset.inputs[0])
    links.new(noise_w_offset.outputs[0], noise_c.inputs["W"])

    links.new(noise_l.outputs["Fac"], centered_l.inputs[0])
    links.new(centered_l.outputs[0], amount_l.inputs[0])
    links.new(inp.outputs["Luminance Noise"], amount_l.inputs[1])
    links.new(amount_l.outputs[0], shadowed_l.inputs[0])
    links.new(shadow_add.outputs[0], shadowed_l.inputs[1])
    links.new(inp.outputs["Color In"], add_luma.inputs[1])
    links.new(shadowed_l.outputs[0], add_luma.inputs[2])

    links.new(noise_c.outputs["Color"], center_color.inputs[0])
    links.new(center_color.outputs[0], scale_color.inputs[0])
    links.new(inp.outputs["Chroma Noise"], _input(scale_color, "Scale", 3))
    links.new(add_luma.outputs[0], add_chroma.inputs[1])
    links.new(scale_color.outputs[0], add_chroma.inputs[2])
    links.new(add_chroma.outputs[0], out.inputs["Color Out"])
    return group


def _create_chroma_key(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Key Color", "INPUT", "NodeSocketColor", default=(0.0, 1.0, 0.0, 1.0))
    _socket(group, "Tolerance", "INPUT", "NodeSocketFloat", default=0.20, minimum=0.0, maximum=1.732)
    _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=0.08, minimum=0.0, maximum=1.0)
    _socket(group, "Despill", "INPUT", "NodeSocketFloat", default=0.5, minimum=0.0, maximum=1.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    distance = _vector_math(group, "DISTANCE", "Color Distance", -620, 160)
    low = _math(group, "SUBTRACT", "Key Lower Bound", -620, -20)
    high = _math(group, "ADD", "Key Upper Bound", -620, -130)
    map_range = _node(group, "ShaderNodeMapRange", "Key Softness", -360, 100)
    map_range.interpolation_type = "SMOOTHERSTEP"
    map_range.inputs["To Min"].default_value = 0.0
    map_range.inputs["To Max"].default_value = 1.0
    inverse = _math(group, "SUBTRACT", "Inverse Key", -140, -80, value_1=1.0)
    normal_weight = _math(group, "SUBTRACT", "Normal Weight", -140, 80, value_1=1.0)
    normal_part = _math(group, "MULTIPLY", "Normal Mask", 40, 80)
    inverse_part = _math(group, "MULTIPLY", "Inverted Mask", 40, -80)
    mask = _math(group, "ADD", "Final Key Mask", 220, 20)
    alpha = _math(group, "MULTIPLY", "Keyed Alpha", 420, -80)

    bw = _node(group, "ShaderNodeRGBToBW", "Despill Grey", -340, 330)
    despill_zone = _math(group, "SUBTRACT", "Despill Zone", -140, 250, value_1=1.0)
    despill_fac = _math(group, "MULTIPLY", "Despill Strength", 40, 250)
    despill_mix = _mix_rgb(group, "MIX", "Despill", 260, 260)

    links.new(inp.outputs["Color In"], distance.inputs[0])
    links.new(inp.outputs["Key Color"], distance.inputs[1])
    links.new(inp.outputs["Tolerance"], low.inputs[0])
    links.new(inp.outputs["Softness"], low.inputs[1])
    links.new(inp.outputs["Tolerance"], high.inputs[0])
    links.new(inp.outputs["Softness"], high.inputs[1])
    links.new(_output(distance, "Value", 1), map_range.inputs["Value"])
    links.new(low.outputs[0], map_range.inputs["From Min"])
    links.new(high.outputs[0], map_range.inputs["From Max"])
    links.new(map_range.outputs["Result"], inverse.inputs[1])
    links.new(inp.outputs["Invert"], normal_weight.inputs[1])
    links.new(map_range.outputs["Result"], normal_part.inputs[0])
    links.new(normal_weight.outputs[0], normal_part.inputs[1])
    links.new(inverse.outputs[0], inverse_part.inputs[0])
    links.new(inp.outputs["Invert"], inverse_part.inputs[1])
    links.new(normal_part.outputs[0], mask.inputs[0])
    links.new(inverse_part.outputs[0], mask.inputs[1])
    links.new(inp.outputs["Alpha In"], alpha.inputs[0])
    links.new(mask.outputs[0], alpha.inputs[1])

    links.new(inp.outputs["Color In"], bw.inputs[0])
    links.new(mask.outputs[0], despill_zone.inputs[1])
    links.new(despill_zone.outputs[0], despill_fac.inputs[0])
    links.new(inp.outputs["Despill"], despill_fac.inputs[1])
    links.new(despill_fac.outputs[0], despill_mix.inputs[0])
    links.new(inp.outputs["Color In"], despill_mix.inputs[1])
    links.new(bw.outputs[0], despill_mix.inputs[2])
    distance_norm = _math(group, "MULTIPLY", "Normalized Key Distance", 420, 390, value_2=0.577350269)
    links.new(_output(distance, "Value", 1), distance_norm.inputs[0])
    debug_color = _debug_color(group, despill_mix.outputs[0], mask.outputs[0], distance_norm.outputs[0], inp.outputs["Debug Mode"], x=620, y=300, prefix="Chroma Key")
    debug_active = _math(group, "GREATER_THAN", "Chroma Debug Active", 650, -150, value_2=0.5)
    debug_alpha = _mix_rgb(group, "MIX", "Chroma Debug Alpha", 850, -100)
    links.new(inp.outputs["Debug Mode"], debug_active.inputs[0])
    links.new(debug_active.outputs[0], debug_alpha.inputs[0])
    links.new(alpha.outputs[0], debug_alpha.inputs[1])
    debug_alpha.inputs[2].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(debug_color, out.inputs["Color Out"])
    links.new(debug_alpha.outputs[0], out.inputs["Alpha Out"])
    return group


def _luminance_controls(group, inp, x, y, *, contrast_name="Contrast", invert_name="Invert"):
    links = group.links
    bw = _node(group, "ShaderNodeRGBToBW", "Luminance", x, y)
    subtract = _math(group, "SUBTRACT", "Luminance Center", x + 170, y, value_2=0.5)
    multiply = _math(group, "MULTIPLY", "Luminance Contrast", x + 340, y)
    add = _math(group, "ADD", "Luminance Restore", x + 510, y, value_2=0.5)
    clamp = _math(group, "MINIMUM", "Clamp High", x + 680, y, value_2=1.0)
    clamp_low = _math(group, "MAXIMUM", "Clamp Low", x + 850, y, value_2=0.0)
    inverse = _math(group, "SUBTRACT", "Inverted Luminance", x + 680, y - 140, value_1=1.0)
    normal_weight = _math(group, "SUBTRACT", "Luminance Normal Weight", x + 850, y - 140, value_1=1.0)
    normal_part = _math(group, "MULTIPLY", "Luminance Normal", x + 1020, y)
    inverse_part = _math(group, "MULTIPLY", "Luminance Inverted", x + 1020, y - 140)
    final = _math(group, "ADD", "Final Luminance", x + 1190, y - 40)

    links.new(inp.outputs["Color In"], bw.inputs[0])
    links.new(bw.outputs[0], subtract.inputs[0])
    links.new(subtract.outputs[0], multiply.inputs[0])
    links.new(inp.outputs[contrast_name], multiply.inputs[1])
    links.new(multiply.outputs[0], add.inputs[0])
    links.new(add.outputs[0], clamp.inputs[0])
    links.new(clamp.outputs[0], clamp_low.inputs[0])
    links.new(clamp_low.outputs[0], inverse.inputs[1])
    links.new(inp.outputs[invert_name], normal_weight.inputs[1])
    links.new(clamp_low.outputs[0], normal_part.inputs[0])
    links.new(normal_weight.outputs[0], normal_part.inputs[1])
    links.new(inverse.outputs[0], inverse_part.inputs[0])
    links.new(inp.outputs[invert_name], inverse_part.inputs[1])
    links.new(normal_part.outputs[0], final.inputs[0])
    links.new(inverse_part.outputs[0], final.inputs[1])
    return final.outputs[0]


def _cell_distance(group, inp, scale_socket, x=-720, y=-180, rotation_socket=None, aspect_socket="Aspect Ratio"):
    """Return circular cells in physical plane space, even after grid rotation.

    UV coordinates are first converted into width-relative plane coordinates.
    Rotation therefore happens before the grid is sampled and cannot stretch
    circles into ovals on non-square planes.
    """
    links = group.links
    separate = _node(group, "ShaderNodeSeparateXYZ", "Separate Grid UV", x, y)
    x_center = _math(group, "SUBTRACT", "Centered Grid X", x + 180, y + 100, value_2=0.5)
    y_center = _math(group, "SUBTRACT", "Centered Grid Y", x + 180, y - 80, value_2=0.5)
    y_physical = _math(group, "DIVIDE", "Aspect Correct Grid Y", x + 360, y - 80)
    physical = _node(group, "ShaderNodeCombineXYZ", "Physical Grid Coordinates", x + 540, y)

    links.new(inp.outputs["UV Vector"], separate.inputs[0])
    links.new(separate.outputs["X"], x_center.inputs[0])
    links.new(separate.outputs["Y"], y_center.inputs[0])
    links.new(y_center.outputs[0], y_physical.inputs[0])
    if aspect_socket and aspect_socket in inp.outputs:
        links.new(inp.outputs[aspect_socket], y_physical.inputs[1])
    else:
        y_physical.inputs[1].default_value = 1.0
    links.new(x_center.outputs[0], physical.inputs["X"])
    links.new(y_physical.outputs[0], physical.inputs["Y"])

    vector = physical.outputs[0]
    next_x = x + 720
    if rotation_socket:
        rotate = _node(group, "ShaderNodeVectorRotate", "Rotate Physical Grid", next_x, y)
        rotate.rotation_type = "Z_AXIS"
        rotate.invert = False
        rotate.inputs["Center"].default_value = (0.0, 0.0, 0.0)
        links.new(vector, rotate.inputs["Vector"])
        links.new(inp.outputs[rotation_socket], rotate.inputs["Angle"])
        vector = rotate.outputs["Vector"]
        next_x += 180

    rotated_separate = _node(group, "ShaderNodeSeparateXYZ", "Separate Rotated Grid", next_x, y)
    x_scaled = _math(group, "MULTIPLY", "Grid X Cells", next_x + 180, y + 80)
    y_scaled = _math(group, "MULTIPLY", "Grid Y Cells", next_x + 180, y - 80)
    scaled = _node(group, "ShaderNodeCombineXYZ", "Scaled Grid", next_x + 360, y)
    fraction = _vector_math(group, "FRACTION", "Cell Coordinates", next_x + 540, y)
    centered = _vector_math(group, "SUBTRACT", "Cell Center", next_x + 720, y)
    centered.inputs[1].default_value = (0.5, 0.5, 0.0)
    distance = _vector_math(group, "LENGTH", "Cell Distance", next_x + 900, y)

    links.new(vector, rotated_separate.inputs[0])
    links.new(rotated_separate.outputs["X"], x_scaled.inputs[0])
    links.new(inp.outputs[scale_socket], x_scaled.inputs[1])
    links.new(rotated_separate.outputs["Y"], y_scaled.inputs[0])
    links.new(inp.outputs[scale_socket], y_scaled.inputs[1])
    links.new(x_scaled.outputs[0], scaled.inputs["X"])
    links.new(y_scaled.outputs[0], scaled.inputs["Y"])
    links.new(scaled.outputs[0], fraction.inputs[0])
    links.new(fraction.outputs[0], centered.inputs[0])
    links.new(centered.outputs[0], distance.inputs[0])
    return _output(distance, "Value", 1), scaled.outputs[0], centered.outputs[0]


def _shape_distance(group, centered_socket, shape_socket, *, x, y, prefix="Cell"):
    """Select circle, square, diamond or line distance from centered cell coordinates."""
    links = group.links
    separate = _node(group, "ShaderNodeSeparateXYZ", f"{prefix} Shape Coordinates", x, y)
    abs_x = _math(group, "ABSOLUTE", f"{prefix} Abs X", x + 180, y + 90)
    abs_y = _math(group, "ABSOLUTE", f"{prefix} Abs Y", x + 180, y - 90)
    square = _math(group, "MAXIMUM", f"{prefix} Square Distance", x + 360, y + 90)
    diamond_sum = _math(group, "ADD", f"{prefix} Diamond Sum", x + 360, y - 70)
    diamond = _math(group, "MULTIPLY", f"{prefix} Diamond Distance", x + 540, y - 70, value_2=0.70710678)
    circle = _vector_math(group, "LENGTH", f"{prefix} Circle Distance", x + 360, y + 250)
    links.new(centered_socket, separate.inputs[0])
    links.new(centered_socket, circle.inputs[0])
    links.new(separate.outputs["X"], abs_x.inputs[0])
    links.new(separate.outputs["Y"], abs_y.inputs[0])
    links.new(abs_x.outputs[0], square.inputs[0])
    links.new(abs_y.outputs[0], square.inputs[1])
    links.new(abs_x.outputs[0], diamond_sum.inputs[0])
    links.new(abs_y.outputs[0], diamond_sum.inputs[1])
    links.new(diamond_sum.outputs[0], diamond.inputs[0])

    candidates = (_output(circle, "Value", 1), square.outputs[0], diamond.outputs[0], abs_y.outputs[0])
    weighted = []
    for index, candidate in enumerate(candidates):
        compare = _math(group, "COMPARE", f"{prefix} Shape {index}", x + 720, y + 260 - index * 120)
        compare.inputs[1].default_value = float(index)
        eps = _input(compare, "Epsilon", 2)
        if eps is not None:
            eps.default_value = 0.1
        amount = _math(group, "MULTIPLY", f"{prefix} Shape Distance {index}", x + 900, y + 260 - index * 120)
        links.new(shape_socket, compare.inputs[0])
        links.new(candidate, amount.inputs[0])
        links.new(compare.outputs[0], amount.inputs[1])
        weighted.append(amount.outputs[0])
    add_a = _math(group, "ADD", f"{prefix} Shape Pair A", x + 1080, y + 160)
    add_b = _math(group, "ADD", f"{prefix} Shape Pair B", x + 1080, y - 120)
    total = _math(group, "ADD", f"{prefix} Selected Shape", x + 1260, y + 20)
    links.new(weighted[0], add_a.inputs[0])
    links.new(weighted[1], add_a.inputs[1])
    links.new(weighted[2], add_b.inputs[0])
    links.new(weighted[3], add_b.inputs[1])
    links.new(add_a.outputs[0], total.inputs[0])
    links.new(add_b.outputs[0], total.inputs[1])
    return total.outputs[0]


def _debug_color(group, final_color, luminance, mask, debug_socket, *, x, y, prefix):
    """Return final/luminance/mask color selected by a numeric debug mode."""
    links = group.links
    is_luma = _math(group, "COMPARE", f"{prefix} Debug Luminance", x, y + 100)
    is_luma.inputs[1].default_value = 1.0
    is_mask = _math(group, "COMPARE", f"{prefix} Debug Mask", x, y - 80)
    is_mask.inputs[1].default_value = 2.0
    for compare in (is_luma, is_mask):
        eps = _input(compare, "Epsilon", 2)
        if eps is not None:
            eps.default_value = 0.1
        links.new(debug_socket, compare.inputs[0])
    luma_mix = _mix_rgb(group, "MIX", f"{prefix} Luminance Preview", x + 190, y + 80)
    mask_mix = _mix_rgb(group, "MIX", f"{prefix} Mask Preview", x + 390, y)
    links.new(is_luma.outputs[0], luma_mix.inputs[0])
    links.new(final_color, luma_mix.inputs[1])
    links.new(luminance, luma_mix.inputs[2])
    links.new(is_mask.outputs[0], mask_mix.inputs[0])
    links.new(luma_mix.outputs[0], mask_mix.inputs[1])
    links.new(mask, mask_mix.inputs[2])
    return mask_mix.outputs[0]


def _create_halftone(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Cell Scale", "INPUT", "NodeSocketFloat", default=80.0, minimum=1.0, maximum=2000.0)
    _socket(group, "Aspect Ratio", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.001, maximum=1000.0)
    _socket(group, "Dot Size", "INPUT", "NodeSocketFloat", default=0.9, minimum=0.0, maximum=1.5)
    _socket(group, "Rotation", "INPUT", "NodeSocketFloat", default=0.0, minimum=-6.283, maximum=6.283)
    _socket(group, "Contrast", "INPUT", "NodeSocketFloat", default=1.4, minimum=0.0, maximum=8.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Shape", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=3.0)
    _socket(group, "Use Source Color", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Foreground", "INPUT", "NodeSocketColor", default=(0.0, 0.0, 0.0, 1.0))
    _socket(group, "Background", "INPUT", "NodeSocketColor", default=(1.0, 1.0, 1.0, 1.0))
    _socket(group, "Transparent Background", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    luminance = _luminance_controls(group, inp, -1150, 480)
    _circle, _scaled, centered = _cell_distance(group, inp, "Cell Scale", x=-1120, y=-300, rotation_socket="Rotation")
    distance = _shape_distance(group, centered, inp.outputs["Shape"], x=140, y=-260, prefix="Halftone")
    inverse_luma = _math(group, "SUBTRACT", "Ink Amount", 200, 430, value_1=1.0)
    diameter = _math(group, "MULTIPLY", "Halftone Diameter", 380, 430)
    radius = _math(group, "MULTIPLY", "Halftone Radius", 560, 430, value_2=0.5)
    edge = _math(group, "ADD", "Halftone Soft Edge", 740, 350, value_2=0.018)
    mask = _node(group, "ShaderNodeMapRange", "Halftone Mask", 760, 120)
    mask.interpolation_type = "SMOOTHERSTEP"
    mask.clamp = True
    mask.inputs["To Min"].default_value = 1.0
    mask.inputs["To Max"].default_value = 0.0
    ink = _mix_rgb(group, "MIX", "Halftone Ink Color", 1010, 500)
    result = _mix_rgb(group, "MIX", "Halftone Output", 1240, 350)
    alpha_mask = _math(group, "MULTIPLY", "Halftone Ink Alpha", 1240, 60)
    opaque_weight = _math(group, "SUBTRACT", "Halftone Opaque Background", 1240, -80, value_1=1.0)
    bg_alpha = _math(group, "MULTIPLY", "Halftone Background Alpha", 1420, -80)
    fg_alpha = _math(group, "MULTIPLY", "Halftone Transparent Alpha", 1420, 60)
    final_alpha = _math(group, "ADD", "Halftone Alpha", 1600, 0)

    links.new(luminance, inverse_luma.inputs[1])
    links.new(inverse_luma.outputs[0], diameter.inputs[0])
    links.new(inp.outputs["Dot Size"], diameter.inputs[1])
    links.new(diameter.outputs[0], radius.inputs[0])
    links.new(radius.outputs[0], edge.inputs[0])
    links.new(distance, mask.inputs["Value"])
    links.new(radius.outputs[0], mask.inputs["From Min"])
    links.new(edge.outputs[0], mask.inputs["From Max"])
    links.new(inp.outputs["Use Source Color"], ink.inputs[0])
    links.new(inp.outputs["Foreground"], ink.inputs[1])
    links.new(inp.outputs["Color In"], ink.inputs[2])
    links.new(mask.outputs["Result"], result.inputs[0])
    links.new(inp.outputs["Background"], result.inputs[1])
    links.new(ink.outputs[0], result.inputs[2])
    debug_color = _debug_color(group, result.outputs[0], luminance, mask.outputs["Result"], inp.outputs["Debug Mode"], x=1450, y=420, prefix="Halftone")
    links.new(debug_color, out.inputs["Color Out"])

    links.new(mask.outputs["Result"], alpha_mask.inputs[0])
    links.new(inp.outputs["Alpha In"], alpha_mask.inputs[1])
    links.new(inp.outputs["Transparent Background"], opaque_weight.inputs[1])
    links.new(inp.outputs["Alpha In"], bg_alpha.inputs[0])
    links.new(opaque_weight.outputs[0], bg_alpha.inputs[1])
    links.new(alpha_mask.outputs[0], fg_alpha.inputs[0])
    links.new(inp.outputs["Transparent Background"], fg_alpha.inputs[1])
    links.new(bg_alpha.outputs[0], final_alpha.inputs[0])
    links.new(fg_alpha.outputs[0], final_alpha.inputs[1])
    debug_active = _math(group, "GREATER_THAN", "Halftone Debug Active", 1630, -150, value_2=0.5)
    debug_alpha = _mix_rgb(group, "MIX", "Halftone Debug Alpha", 1810, -40)
    links.new(inp.outputs["Debug Mode"], debug_active.inputs[0])
    links.new(debug_active.outputs[0], debug_alpha.inputs[0])
    links.new(final_alpha.outputs[0], debug_alpha.inputs[1])
    debug_alpha.inputs[2].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(debug_alpha.outputs[0], out.inputs["Alpha Out"])
    return group


def _matrix_cell_coordinates(group, inp, *, x=-980, y=-180):
    """Return cell-center UV, local cell UV, ID and radial distance.

    The grid is aspect-corrected in physical plane space.  Sampling the source
    at cell centers keeps luminance, alpha and character choice constant inside
    each dot/glyph instead of changing across the cell.
    """
    links = group.links
    separate = _node(group, "ShaderNodeSeparateXYZ", "Matrix UV", x, y)
    columns = _math(group, "MAXIMUM", "Matrix Columns", x + 180, y + 100, value_2=1.0)
    rows_div = _math(group, "DIVIDE", "Matrix Rows Ratio", x + 180, y - 90)
    rows = _math(group, "MAXIMUM", "Matrix Rows", x + 360, y - 90, value_2=1.0)
    scaled_x = _math(group, "MULTIPLY", "Matrix X Cells", x + 360, y + 100)
    scaled_y = _math(group, "MULTIPLY", "Matrix Y Cells", x + 540, y - 90)
    floor_x = _math(group, "FLOOR", "Matrix Cell X", x + 540, y + 100)
    floor_y = _math(group, "FLOOR", "Matrix Cell Y", x + 720, y - 90)
    local_x = _math(group, "FRACT", "Matrix Local X", x + 720, y + 100)
    local_y = _math(group, "FRACT", "Matrix Local Y", x + 900, y - 90)
    center_x_add = _math(group, "ADD", "Matrix Center X Cell", x + 900, y + 100, value_2=0.5)
    center_y_add = _math(group, "ADD", "Matrix Center Y Cell", x + 1080, y - 90, value_2=0.5)
    center_x = _math(group, "DIVIDE", "Matrix Center U", x + 1080, y + 100)
    center_y = _math(group, "DIVIDE", "Matrix Center V", x + 1260, y - 90)
    center_uv = _node(group, "ShaderNodeCombineXYZ", "Matrix Cell Center UV", x + 1440, y + 20)
    local_uv = _node(group, "ShaderNodeCombineXYZ", "Matrix Local UV", x + 1080, y - 250)
    cell_id = _node(group, "ShaderNodeCombineXYZ", "Matrix Cell ID", x + 900, y - 400)
    local_center = _vector_math(group, "SUBTRACT", "Matrix From Cell Center", x + 1260, y - 250)
    local_center.inputs[1].default_value = (0.5, 0.5, 0.0)
    distance = _vector_math(group, "LENGTH", "Matrix Cell Distance", x + 1440, y - 250)

    links.new(inp.outputs["UV Vector"], separate.inputs[0])
    links.new(inp.outputs["Cell Scale"], columns.inputs[0])
    links.new(inp.outputs["Cell Scale"], rows_div.inputs[0])
    links.new(inp.outputs["Aspect Ratio"], rows_div.inputs[1])
    links.new(rows_div.outputs[0], rows.inputs[0])
    links.new(separate.outputs["X"], scaled_x.inputs[0])
    links.new(columns.outputs[0], scaled_x.inputs[1])
    links.new(separate.outputs["Y"], scaled_y.inputs[0])
    links.new(rows.outputs[0], scaled_y.inputs[1])
    links.new(scaled_x.outputs[0], floor_x.inputs[0])
    links.new(scaled_y.outputs[0], floor_y.inputs[0])
    links.new(scaled_x.outputs[0], local_x.inputs[0])
    links.new(scaled_y.outputs[0], local_y.inputs[0])
    links.new(floor_x.outputs[0], center_x_add.inputs[0])
    links.new(floor_y.outputs[0], center_y_add.inputs[0])
    links.new(center_x_add.outputs[0], center_x.inputs[0])
    links.new(columns.outputs[0], center_x.inputs[1])
    links.new(center_y_add.outputs[0], center_y.inputs[0])
    links.new(rows.outputs[0], center_y.inputs[1])
    links.new(center_x.outputs[0], center_uv.inputs["X"])
    links.new(center_y.outputs[0], center_uv.inputs["Y"])
    links.new(local_x.outputs[0], local_uv.inputs["X"])
    links.new(local_y.outputs[0], local_uv.inputs["Y"])
    links.new(floor_x.outputs[0], cell_id.inputs["X"])
    links.new(floor_y.outputs[0], cell_id.inputs["Y"])
    links.new(local_uv.outputs[0], local_center.inputs[0])
    links.new(local_center.outputs[0], distance.inputs[0])
    return {
        "center_uv": center_uv.outputs[0],
        "local_uv": local_uv.outputs[0],
        "cell_id": cell_id.outputs[0],
        "distance": _output(distance, "Value", 1),
        "columns": columns.outputs[0],
        "rows": rows.outputs[0],
    }


def _controlled_luminance(group, color_socket, contrast_socket, invert_socket, *, x, y):
    """Return clamped luminance with contrast and optional inversion."""
    links = group.links
    bw = _node(group, "ShaderNodeRGBToBW", "Matrix Source Luminance", x, y)
    center = _math(group, "SUBTRACT", "Matrix Luminance Center", x + 180, y, value_2=0.5)
    contrast = _math(group, "MULTIPLY", "Matrix Luminance Contrast", x + 360, y)
    restore = _math(group, "ADD", "Matrix Luminance Restore", x + 540, y, value_2=0.5)
    low = _math(group, "MAXIMUM", "Matrix Luminance Low", x + 720, y, value_2=0.0)
    high = _math(group, "MINIMUM", "Matrix Luminance High", x + 900, y, value_2=1.0)
    inverse = _math(group, "SUBTRACT", "Matrix Inverted Luminance", x + 900, y - 140, value_1=1.0)
    normal_weight = _math(group, "SUBTRACT", "Matrix Normal Weight", x + 1080, y - 140, value_1=1.0)
    normal = _math(group, "MULTIPLY", "Matrix Normal Luminance", x + 1260, y)
    inverted = _math(group, "MULTIPLY", "Matrix Inverted Part", x + 1260, y - 140)
    result = _math(group, "ADD", "Matrix Final Luminance", x + 1440, y - 50)
    links.new(color_socket, bw.inputs[0])
    links.new(bw.outputs[0], center.inputs[0])
    links.new(center.outputs[0], contrast.inputs[0])
    links.new(contrast_socket, contrast.inputs[1])
    links.new(contrast.outputs[0], restore.inputs[0])
    links.new(restore.outputs[0], low.inputs[0])
    links.new(low.outputs[0], high.inputs[0])
    links.new(high.outputs[0], inverse.inputs[1])
    links.new(invert_socket, normal_weight.inputs[1])
    links.new(high.outputs[0], normal.inputs[0])
    links.new(normal_weight.outputs[0], normal.inputs[1])
    links.new(inverse.outputs[0], inverted.inputs[0])
    links.new(invert_socket, inverted.inputs[1])
    links.new(normal.outputs[0], result.inputs[0])
    links.new(inverted.outputs[0], result.inputs[1])
    return result.outputs[0]


def _matrix_source_sample(group, inp, center_uv, *, x, y, label):
    """Sample an owned source image at the cell center with procedural fallback."""
    links = group.links
    image = _node(group, "ShaderNodeTexImage", f"{label} Source Image", x, y)
    image["fbp_matrix_source_image_node"] = True
    try:
        image.interpolation = "Closest"
        image.extension = "EXTEND"
    except (AttributeError, TypeError, ValueError):
        pass
    color = _mix_rgb(group, "MIX", f"{label} Source Color", x + 240, y + 80)
    fallback_weight = _math(group, "SUBTRACT", f"{label} Fallback Weight", x + 220, y - 150, value_1=1.0)
    image_alpha = _math(group, "MULTIPLY", f"{label} Image Alpha", x + 420, y - 100)
    fallback_alpha = _math(group, "MULTIPLY", f"{label} Fallback Alpha", x + 420, y - 230)
    alpha = _math(group, "ADD", f"{label} Source Alpha", x + 600, y - 160)
    links.new(center_uv, image.inputs["Vector"])
    links.new(inp.outputs["Use Image Sample"], color.inputs[0])
    links.new(inp.outputs["Color In"], color.inputs[1])
    links.new(image.outputs["Color"], color.inputs[2])
    links.new(inp.outputs["Use Image Sample"], fallback_weight.inputs[1])
    links.new(image.outputs["Alpha"], image_alpha.inputs[0])
    links.new(inp.outputs["Use Image Sample"], image_alpha.inputs[1])
    links.new(inp.outputs["Alpha In"], fallback_alpha.inputs[0])
    links.new(fallback_weight.outputs[0], fallback_alpha.inputs[1])
    links.new(image_alpha.outputs[0], alpha.inputs[0])
    links.new(fallback_alpha.outputs[0], alpha.inputs[1])
    return image, color.outputs[0], alpha.outputs[0]


def _create_dot_matrix(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Image Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Cell Scale", "INPUT", "NodeSocketFloat", default=64.0, minimum=1.0, maximum=2000.0)
    _socket(group, "Aspect Ratio", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.001, maximum=1000.0)
    _socket(group, "Dot Size", "INPUT", "NodeSocketFloat", default=0.85, minimum=0.0, maximum=1.5)
    _socket(group, "Spacing", "INPUT", "NodeSocketFloat", default=0.10, minimum=0.0, maximum=0.95)
    _socket(group, "Contrast", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=8.0)
    _socket(group, "Brightness Response", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.1, maximum=8.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Random Size", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Random Brightness", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Seed", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100000.0, maximum=100000.0)
    _socket(group, "Glow", "INPUT", "NodeSocketFloat", default=0.035, minimum=0.0, maximum=0.5)
    _socket(group, "Use Source Color", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Foreground", "INPUT", "NodeSocketColor", default=(1.0, 0.35, 0.05, 1.0))
    _socket(group, "Background", "INPUT", "NodeSocketColor", default=(0.0, 0.0, 0.0, 1.0))
    _socket(group, "Transparent Background", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Shape", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=3.0)
    _socket(group, "Minimum Size", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.5)
    _socket(group, "Maximum Size", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.5)
    _socket(group, "Dead Pixels", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Flicker", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    grid = _matrix_cell_coordinates(group, inp, x=-2100, y=-260)
    _image, source_color, source_alpha = _matrix_source_sample(
        group, inp, grid["center_uv"], x=-500, y=-80, label="Dot Matrix"
    )
    luminance = _controlled_luminance(
        group, source_color, inp.outputs["Contrast"], inp.outputs["Invert"], x=-180, y=580
    )
    response_luminance = _math(group, "POWER", "Dot Brightness Response", 20, 580)
    links.new(luminance, response_luminance.inputs[0])
    links.new(inp.outputs["Brightness Response"], response_luminance.inputs[1])

    local_center = _vector_math(group, "SUBTRACT", "Dot Local Center", 0, -250)
    local_center.inputs[1].default_value = (0.5, 0.5, 0.0)
    links.new(grid["local_uv"], local_center.inputs[0])
    shape_distance = _shape_distance(
        group, local_center.outputs[0], inp.outputs["Shape"], x=180, y=-250, prefix="Dot Matrix"
    )

    size_noise = _node(group, "ShaderNodeTexWhiteNoise", "Dot Size Variation", 0, -650)
    size_noise.noise_dimensions = "4D"
    size_center = _math(group, "SUBTRACT", "Dot Size Center", 200, -650, value_2=0.5)
    size_full = _math(group, "MULTIPLY", "Dot Size Full Range", 380, -650, value_2=2.0)
    size_amount = _math(group, "MULTIPLY", "Dot Size Random Amount", 560, -650)
    size_factor = _math(group, "ADD", "Dot Size Random Factor", 740, -650, value_2=1.0)

    brightness_seed = _math(group, "ADD", "Dot Brightness Seed", 0, -830, value_2=37.0)
    brightness_noise = _node(group, "ShaderNodeTexWhiteNoise", "Dot Brightness Variation", 200, -830)
    brightness_noise.noise_dimensions = "4D"
    brightness_center = _math(group, "SUBTRACT", "Dot Brightness Center", 400, -830, value_2=0.5)
    brightness_full = _math(group, "MULTIPLY", "Dot Brightness Full Range", 580, -830, value_2=2.0)
    brightness_amount = _math(group, "MULTIPLY", "Dot Brightness Amount", 760, -830)

    flicker_seed = _math(group, "ADD", "Dot Flicker Seed", 0, -1010, value_2=211.0)
    flicker_noise = _node(group, "ShaderNodeTexWhiteNoise", "Dot Flicker Noise", 200, -1010)
    flicker_noise.noise_dimensions = "4D"
    flicker_center = _math(group, "SUBTRACT", "Dot Flicker Center", 400, -1010, value_2=0.5)
    flicker_full = _math(group, "MULTIPLY", "Dot Flicker Full Range", 580, -1010, value_2=2.0)
    flicker_amount = _math(group, "MULTIPLY", "Dot Flicker Amount", 760, -1010)
    brightness_combined = _math(group, "ADD", "Dot Brightness And Flicker", 940, -900)
    brightness_factor = _math(group, "ADD", "Dot Brightness Factor", 1120, -900, value_2=1.0)
    brightness_low = _math(group, "MAXIMUM", "Dot Brightness Minimum", 1300, -900, value_2=0.0)
    brightness_high = _math(group, "MINIMUM", "Dot Brightness Maximum", 1480, -900, value_2=2.0)

    dead_seed = _math(group, "ADD", "Dead Pixel Seed", 0, -1190, value_2=101.0)
    dead_noise = _node(group, "ShaderNodeTexWhiteNoise", "Dead Pixel Noise", 200, -1190)
    dead_noise.noise_dimensions = "4D"
    alive = _math(group, "GREATER_THAN", "Live Dot", 400, -1190)

    max_minus_min = _math(group, "SUBTRACT", "Dot Size Range", 680, 460)
    luma_range = _math(group, "MULTIPLY", "Image Dot Size Range", 860, 460)
    image_diameter = _math(group, "ADD", "Image Driven Dot Diameter", 1040, 460)
    spacing = _math(group, "SUBTRACT", "Dot Available Cell", 1040, 320, value_1=1.0)
    base_scale = _math(group, "MULTIPLY", "Dot Base Scale", 1220, 400)
    varied_size = _math(group, "MULTIPLY", "Dot Varied Diameter", 1400, 400)
    alive_size = _math(group, "MULTIPLY", "Dot Live Diameter", 1580, 400)
    radius = _math(group, "MULTIPLY", "Dot Radius", 1760, 400, value_2=0.5)
    safe_glow = _math(group, "MAXIMUM", "Safe Dot Glow", 1760, 250, value_2=0.0001)
    edge = _math(group, "ADD", "Dot Soft Edge", 1940, 330)
    mask = _node(group, "ShaderNodeMapRange", "Dot Matrix Mask", 1950, 80)
    mask.interpolation_type = "SMOOTHERSTEP"
    mask.clamp = True
    mask.inputs["To Min"].default_value = 1.0
    mask.inputs["To Max"].default_value = 0.0

    foreground_luma = _mix_rgb(group, "MULTIPLY", "Dot Luminance Color", 1540, 650)
    foreground_luma.inputs[0].default_value = 1.0
    source_mode = _mix_rgb(group, "MIX", "Dot Color Mode", 1780, 650)
    varied_color = _mix_rgb(group, "MULTIPLY", "Dot Animated Brightness", 2020, 650)
    varied_color.inputs[0].default_value = 1.0
    final = _mix_rgb(group, "MIX", "Dot Matrix Output", 2260, 500)

    glyph_alpha = _math(group, "MULTIPLY", "Dot Alpha", 2260, 0)
    opaque_weight = _math(group, "SUBTRACT", "Dot Opaque Background", 2260, -150, value_1=1.0)
    background_alpha = _math(group, "MULTIPLY", "Dot Background Alpha", 2440, -150)
    transparent_alpha = _math(group, "MULTIPLY", "Dot Transparent Alpha", 2440, 0)
    final_alpha = _math(group, "ADD", "Dot Matrix Alpha", 2620, -70)

    links.new(grid["cell_id"], size_noise.inputs["Vector"])
    links.new(inp.outputs["Seed"], size_noise.inputs["W"])
    links.new(size_noise.outputs["Value"], size_center.inputs[0])
    links.new(size_center.outputs[0], size_full.inputs[0])
    links.new(size_full.outputs[0], size_amount.inputs[0])
    links.new(inp.outputs["Random Size"], size_amount.inputs[1])
    links.new(size_amount.outputs[0], size_factor.inputs[0])

    links.new(inp.outputs["Seed"], brightness_seed.inputs[0])
    links.new(grid["cell_id"], brightness_noise.inputs["Vector"])
    links.new(brightness_seed.outputs[0], brightness_noise.inputs["W"])
    links.new(brightness_noise.outputs["Value"], brightness_center.inputs[0])
    links.new(brightness_center.outputs[0], brightness_full.inputs[0])
    links.new(brightness_full.outputs[0], brightness_amount.inputs[0])
    links.new(inp.outputs["Random Brightness"], brightness_amount.inputs[1])

    links.new(inp.outputs["Seed"], flicker_seed.inputs[0])
    links.new(grid["cell_id"], flicker_noise.inputs["Vector"])
    links.new(flicker_seed.outputs[0], flicker_noise.inputs["W"])
    links.new(flicker_noise.outputs["Value"], flicker_center.inputs[0])
    links.new(flicker_center.outputs[0], flicker_full.inputs[0])
    links.new(flicker_full.outputs[0], flicker_amount.inputs[0])
    links.new(inp.outputs["Flicker"], flicker_amount.inputs[1])
    links.new(brightness_amount.outputs[0], brightness_combined.inputs[0])
    links.new(flicker_amount.outputs[0], brightness_combined.inputs[1])
    links.new(brightness_combined.outputs[0], brightness_factor.inputs[0])
    links.new(brightness_factor.outputs[0], brightness_low.inputs[0])
    links.new(brightness_low.outputs[0], brightness_high.inputs[0])

    links.new(inp.outputs["Seed"], dead_seed.inputs[0])
    links.new(grid["cell_id"], dead_noise.inputs["Vector"])
    links.new(dead_seed.outputs[0], dead_noise.inputs["W"])
    links.new(dead_noise.outputs["Value"], alive.inputs[0])
    links.new(inp.outputs["Dead Pixels"], alive.inputs[1])

    links.new(inp.outputs["Maximum Size"], max_minus_min.inputs[0])
    links.new(inp.outputs["Minimum Size"], max_minus_min.inputs[1])
    links.new(response_luminance.outputs[0], luma_range.inputs[0])
    links.new(max_minus_min.outputs[0], luma_range.inputs[1])
    links.new(inp.outputs["Minimum Size"], image_diameter.inputs[0])
    links.new(luma_range.outputs[0], image_diameter.inputs[1])
    links.new(inp.outputs["Spacing"], spacing.inputs[1])
    links.new(inp.outputs["Dot Size"], base_scale.inputs[0])
    links.new(spacing.outputs[0], base_scale.inputs[1])
    links.new(image_diameter.outputs[0], varied_size.inputs[0])
    links.new(base_scale.outputs[0], varied_size.inputs[1])
    links.new(varied_size.outputs[0], alive_size.inputs[0])
    links.new(size_factor.outputs[0], alive_size.inputs[1])
    # Dead pixels are applied to radius so their mask is guaranteed to disappear.
    dead_size = _math(group, "MULTIPLY", "Dot Dead Pixel Mask", 1580, 260)
    links.new(alive_size.outputs[0], dead_size.inputs[0])
    links.new(alive.outputs[0], dead_size.inputs[1])
    links.new(dead_size.outputs[0], radius.inputs[0])
    links.new(inp.outputs["Glow"], safe_glow.inputs[0])
    links.new(radius.outputs[0], edge.inputs[0])
    links.new(safe_glow.outputs[0], edge.inputs[1])
    links.new(shape_distance, mask.inputs["Value"])
    links.new(radius.outputs[0], mask.inputs["From Min"])
    links.new(edge.outputs[0], mask.inputs["From Max"])

    links.new(inp.outputs["Foreground"], foreground_luma.inputs[1])
    links.new(response_luminance.outputs[0], foreground_luma.inputs[2])
    links.new(inp.outputs["Use Source Color"], source_mode.inputs[0])
    links.new(foreground_luma.outputs[0], source_mode.inputs[1])
    links.new(source_color, source_mode.inputs[2])
    links.new(source_mode.outputs[0], varied_color.inputs[1])
    links.new(brightness_high.outputs[0], varied_color.inputs[2])
    links.new(mask.outputs["Result"], final.inputs[0])
    links.new(inp.outputs["Background"], final.inputs[1])
    links.new(varied_color.outputs[0], final.inputs[2])
    debug_color = _debug_color(group, final.outputs[0], response_luminance.outputs[0], mask.outputs["Result"], inp.outputs["Debug Mode"], x=2470, y=520, prefix="Dot Matrix")
    links.new(debug_color, out.inputs["Color Out"])

    links.new(mask.outputs["Result"], glyph_alpha.inputs[0])
    links.new(source_alpha, glyph_alpha.inputs[1])
    links.new(inp.outputs["Transparent Background"], opaque_weight.inputs[1])
    links.new(source_alpha, background_alpha.inputs[0])
    links.new(opaque_weight.outputs[0], background_alpha.inputs[1])
    links.new(glyph_alpha.outputs[0], transparent_alpha.inputs[0])
    links.new(inp.outputs["Transparent Background"], transparent_alpha.inputs[1])
    links.new(background_alpha.outputs[0], final_alpha.inputs[0])
    links.new(transparent_alpha.outputs[0], final_alpha.inputs[1])
    debug_active = _math(group, "GREATER_THAN", "Dot Debug Active", 2800, -150, value_2=0.5)
    debug_alpha = _mix_rgb(group, "MIX", "Dot Debug Alpha", 2980, -60)
    links.new(inp.outputs["Debug Mode"], debug_active.inputs[0])
    links.new(debug_active.outputs[0], debug_alpha.inputs[0])
    links.new(final_alpha.outputs[0], debug_alpha.inputs[1])
    debug_alpha.inputs[2].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(debug_alpha.outputs[0], out.inputs["Alpha Out"])
    return group


def _load_ascii_atlas(asset_dir):
    """Load the current atlas without reusing packed atlases from old releases."""
    path = Path(asset_dir) / "ascii_matrix_atlas.png"
    if not path.is_file():
        return None
    expected_size = (
        ASCII_ATLAS_COLUMNS * ASCII_ATLAS_CELL_WIDTH,
        len(ASCII_PRESETS) * ASCII_ATLAS_CELL_HEIGHT,
    )
    atlas_version = ASCII_ATLAS_VERSION
    atlas_revision = ASCII_ATLAS_REVISION

    # ``check_existing=True`` can return a packed image embedded by an older
    # add-on version even though the extension file on disk has changed. Prefer
    # the explicitly versioned datablock, otherwise force a fresh disk load.
    try:
        for candidate in bpy.data.images:
            try:
                if (
                    int(candidate.get("fbp_ascii_atlas_version", 0) or 0) == atlas_version
                    and str(candidate.get("fbp_ascii_atlas_revision", "") or "") == atlas_revision
                    and tuple(int(value) for value in candidate.size[:2]) == expected_size
                ):
                    return candidate
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    try:
        image = bpy.data.images.load(str(path), check_existing=False)
        actual_size = tuple(int(value) for value in image.size[:2])
        if actual_size != expected_size:
            try:
                bpy.data.images.remove(image)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            raise RuntimeError(
                f"Invalid Textellation atlas size {actual_size}; expected {expected_size}"
            )
        image.name = "FBP Textellation Atlas 4.8.5"
        image["fbp_ascii_atlas_version"] = atlas_version
        image["fbp_ascii_atlas_revision"] = atlas_revision
        image["fbp_ascii_atlas_layout"] = f"{ASCII_ATLAS_COLUMNS}x{len(ASCII_PRESETS)}"
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "STRAIGHT"
        image.use_fake_user = True
        try:
            if not image.packed_file:
                image.pack()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        try:
            for candidate in bpy.data.images:
                if candidate == image:
                    continue
                filepath = str(getattr(candidate, "filepath", "") or "")
                if (
                    Path(filepath).name == path.name
                    and (
                        int(candidate.get("fbp_ascii_atlas_version", 0) or 0) != atlas_version
                        or str(candidate.get("fbp_ascii_atlas_revision", "") or "") != atlas_revision
                    )
                ):
                    candidate.use_fake_user = False
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return image
    except (RuntimeError, TypeError, ValueError):
        return None


def _create_ascii_matrix(name, asset_dir):
    """Create the raster Textellation shader.

    Preset rows are light-to-dense. Source luminance is therefore converted to
    glyph density before indexing the atlas: white selects the lightest glyph,
    black selects the densest one. Partial source alpha is composited over white
    for character selection, while output opacity remains binary except for the
    antialiased glyph edge itself.
    """
    atlas_image = _load_ascii_atlas(asset_dir)
    if atlas_image is None:
        raise RuntimeError("Textellation glyph atlas is missing or invalid")
    atlas_rows = max(1, len(ASCII_PRESETS))
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Image Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Cell Scale", "INPUT", "NodeSocketFloat", default=48.0, minimum=1.0, maximum=1000.0)
    _socket(group, "Aspect Ratio", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.001, maximum=1000.0)
    _socket(group, "Contrast", "INPUT", "NodeSocketFloat", default=1.3, minimum=0.0, maximum=8.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Use Source Color", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Foreground", "INPUT", "NodeSocketColor", default=(0.1, 1.0, 0.2, 1.0))
    _socket(group, "Background", "INPUT", "NodeSocketColor", default=(0.0, 0.0, 0.0, 1.0))
    _socket(group, "Transparent Background", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Variation", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Seed", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100000.0, maximum=100000.0)
    _socket(group, "Charset Row", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=float(atlas_rows - 1))
    _socket(group, "Character Count", "INPUT", "NodeSocketFloat", default=float(ASCII_ATLAS_COLUMNS), minimum=2.0, maximum=float(ASCII_ATLAS_COLUMNS))
    _socket(group, "Edge Boost", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Dither", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    grid = _matrix_cell_coordinates(group, inp, x=-2400, y=-260)
    _source_image, source_color, source_alpha = _matrix_source_sample(
        group, inp, grid["center_uv"], x=-760, y=-120, label="Textellation"
    )

    alpha_low = _math(group, "MAXIMUM", "Textellation Alpha Minimum", -520, 520, value_2=0.0)
    alpha_high = _math(group, "MINIMUM", "Textellation Alpha Maximum", -340, 520, value_2=1.0)
    alpha_aware_color = _mix_rgb(group, "MIX", "Textellation Alpha Over White", -120, 520)
    alpha_aware_color.inputs[1].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(source_alpha, alpha_low.inputs[0])
    links.new(alpha_low.outputs[0], alpha_high.inputs[0])
    links.new(alpha_high.outputs[0], alpha_aware_color.inputs[0])
    links.new(source_color, alpha_aware_color.inputs[2])

    base_luminance = _controlled_luminance(
        group, alpha_aware_color.outputs[0], inp.outputs["Contrast"], inp.outputs["Invert"], x=80, y=650
    )

    # Sample one neighbouring cell in each axis. Alpha is composited over white
    # here too, so edges against transparency are interpreted as light rather
    # than as black RGB hidden under a low alpha value.
    center_sep = _node(group, "ShaderNodeSeparateXYZ", "Textellation Center UV", -360, 120)
    inv_columns = _math(group, "DIVIDE", "Textellation U Step", -160, 200, value_1=1.0)
    inv_rows = _math(group, "DIVIDE", "Textellation V Step", -160, 40, value_1=1.0)
    right_u = _math(group, "ADD", "Textellation Right U", 40, 200)
    upper_v = _math(group, "ADD", "Textellation Upper V", 40, 40)
    right_uv = _node(group, "ShaderNodeCombineXYZ", "Textellation Right UV", 240, 170)
    upper_uv = _node(group, "ShaderNodeCombineXYZ", "Textellation Upper UV", 240, 10)
    links.new(grid["center_uv"], center_sep.inputs[0])
    links.new(grid["columns"], inv_columns.inputs[1])
    links.new(grid["rows"], inv_rows.inputs[1])
    links.new(center_sep.outputs["X"], right_u.inputs[0])
    links.new(inv_columns.outputs[0], right_u.inputs[1])
    links.new(center_sep.outputs["Y"], upper_v.inputs[0])
    links.new(inv_rows.outputs[0], upper_v.inputs[1])
    links.new(right_u.outputs[0], right_uv.inputs["X"])
    links.new(center_sep.outputs["Y"], right_uv.inputs["Y"])
    links.new(center_sep.outputs["X"], upper_uv.inputs["X"])
    links.new(upper_v.outputs[0], upper_uv.inputs["Y"])

    def neighbor_sample(label, uv_socket, x, y):
        image = _node(group, "ShaderNodeTexImage", f"Textellation {label} Image", x, y)
        image["fbp_matrix_source_image_node"] = True
        image.interpolation = "Closest"
        image.extension = "EXTEND"
        color = _mix_rgb(group, "MIX", f"Textellation {label} Source", x + 210, y + 50)
        fallback_weight = _math(group, "SUBTRACT", f"Textellation {label} Fallback Weight", x + 200, y - 100, value_1=1.0)
        image_alpha = _math(group, "MULTIPLY", f"Textellation {label} Image Alpha", x + 390, y - 80)
        fallback_alpha = _math(group, "MULTIPLY", f"Textellation {label} Fallback Alpha", x + 390, y - 190)
        alpha = _math(group, "ADD", f"Textellation {label} Alpha", x + 570, y - 130)
        alpha_min = _math(group, "MAXIMUM", f"Textellation {label} Alpha Minimum", x + 750, y - 130, value_2=0.0)
        alpha_max = _math(group, "MINIMUM", f"Textellation {label} Alpha Maximum", x + 930, y - 130, value_2=1.0)
        over_white = _mix_rgb(group, "MIX", f"Textellation {label} Alpha Over White", x + 750, y + 50)
        over_white.inputs[1].default_value = (1.0, 1.0, 1.0, 1.0)
        bw = _node(group, "ShaderNodeRGBToBW", f"Textellation {label} Luminance", x + 960, y + 50)
        links.new(uv_socket, image.inputs["Vector"])
        links.new(inp.outputs["Use Image Sample"], color.inputs[0])
        links.new(inp.outputs["Color In"], color.inputs[1])
        links.new(image.outputs["Color"], color.inputs[2])
        links.new(inp.outputs["Use Image Sample"], fallback_weight.inputs[1])
        links.new(image.outputs["Alpha"], image_alpha.inputs[0])
        links.new(inp.outputs["Use Image Sample"], image_alpha.inputs[1])
        links.new(inp.outputs["Alpha In"], fallback_alpha.inputs[0])
        links.new(fallback_weight.outputs[0], fallback_alpha.inputs[1])
        links.new(image_alpha.outputs[0], alpha.inputs[0])
        links.new(fallback_alpha.outputs[0], alpha.inputs[1])
        links.new(alpha.outputs[0], alpha_min.inputs[0])
        links.new(alpha_min.outputs[0], alpha_max.inputs[0])
        links.new(alpha_max.outputs[0], over_white.inputs[0])
        links.new(color.outputs[0], over_white.inputs[2])
        links.new(over_white.outputs[0], bw.inputs[0])
        return bw.outputs[0]

    right_luma = neighbor_sample("Right", right_uv.outputs[0], 420, 150)
    upper_luma = neighbor_sample("Upper", upper_uv.outputs[0], 420, -250)
    center_bw = _node(group, "ShaderNodeRGBToBW", "Textellation Center Raw Luminance", 1180, 430)
    diff_right = _math(group, "SUBTRACT", "Textellation Horizontal Difference", 1380, 230)
    abs_right = _math(group, "ABSOLUTE", "Textellation Horizontal Edge", 1560, 230)
    diff_upper = _math(group, "SUBTRACT", "Textellation Vertical Difference", 1380, 60)
    abs_upper = _math(group, "ABSOLUTE", "Textellation Vertical Edge", 1560, 60)
    edge_sum = _math(group, "ADD", "Textellation Edge Strength", 1740, 150)
    edge_amount = _math(group, "MULTIPLY", "Textellation Edge Boost", 1920, 150)
    source_density = _math(group, "SUBTRACT", "Textellation Source Density", 1920, 500, value_1=1.0)
    boosted_density = _math(group, "ADD", "Textellation Boosted Density", 2100, 430)
    density_low = _math(group, "MAXIMUM", "Textellation Density Minimum", 2280, 430, value_2=0.0)
    density_high = _math(group, "MINIMUM", "Textellation Density Maximum", 2460, 430, value_2=1.0)
    links.new(alpha_aware_color.outputs[0], center_bw.inputs[0])
    links.new(center_bw.outputs[0], diff_right.inputs[0])
    links.new(right_luma, diff_right.inputs[1])
    links.new(diff_right.outputs[0], abs_right.inputs[0])
    links.new(center_bw.outputs[0], diff_upper.inputs[0])
    links.new(upper_luma, diff_upper.inputs[1])
    links.new(diff_upper.outputs[0], abs_upper.inputs[0])
    links.new(abs_right.outputs[0], edge_sum.inputs[0])
    links.new(abs_upper.outputs[0], edge_sum.inputs[1])
    links.new(edge_sum.outputs[0], edge_amount.inputs[0])
    links.new(inp.outputs["Edge Boost"], edge_amount.inputs[1])
    links.new(base_luminance, source_density.inputs[1])
    links.new(source_density.outputs[0], boosted_density.inputs[0])
    links.new(edge_amount.outputs[0], boosted_density.inputs[1])
    links.new(boosted_density.outputs[0], density_low.inputs[0])
    links.new(density_low.outputs[0], density_high.inputs[0])

    random = _node(group, "ShaderNodeTexWhiteNoise", "Textellation Cell Variation", 1500, -610)
    random.noise_dimensions = "4D"
    random_center = _math(group, "SUBTRACT", "Textellation Center Variation", 1700, -610, value_2=0.5)
    random_full = _math(group, "MULTIPLY", "Textellation Full Variation", 1880, -610, value_2=2.0)
    variation_amount = _math(group, "MULTIPLY", "Textellation Variation Amount", 2060, -610)

    dither_seed = _math(group, "ADD", "Textellation Dither Seed", 1500, -780, value_2=509.0)
    dither_noise = _node(group, "ShaderNodeTexWhiteNoise", "Textellation Dither Pattern", 1700, -780)
    dither_noise.noise_dimensions = "4D"
    dither_center = _math(group, "SUBTRACT", "Textellation Center Dither", 1900, -780, value_2=0.5)
    dither_amount = _math(group, "MULTIPLY", "Textellation Dither Amount", 2080, -780)
    dither_scaled = _math(group, "DIVIDE", "Textellation Dither Per Level", 2260, -780)
    dithered_density = _math(group, "ADD", "Textellation Dithered Density", 2640, 360)
    dither_low = _math(group, "MAXIMUM", "Textellation Dither Minimum", 2820, 360, value_2=0.0)
    dither_high = _math(group, "MINIMUM", "Textellation Dither Maximum", 3000, 360, value_2=1.0)

    count_minus = _math(group, "SUBTRACT", "Character Levels", 2460, 180, value_2=1.0)
    safe_levels = _math(group, "MAXIMUM", "Safe Character Levels", 2640, 180, value_2=1.0)
    variation_half_count = _math(group, "MULTIPLY", "Textellation Half Active Range", 2240, -610, value_2=0.5)
    variation_cap = _math(group, "MINIMUM", "Textellation Variation Cap", 2420, -610, value_2=4.0)
    variation_levels = _math(group, "MULTIPLY", "Textellation Variation Levels", 2600, -610)
    scaled_density = _math(group, "MULTIPLY", "Character Level Scale", 3180, 360)
    rounded = _math(group, "ROUND", "Character Level", 3360, 360)
    normalize = _math(group, "DIVIDE", "Character Level Normalize", 3540, 360)
    atlas_scale = _math(group, "MULTIPLY", "Atlas Character Index", 3720, 360, value_2=float(ASCII_ATLAS_COLUMNS - 1))
    with_variation = _math(group, "ADD", "Varied Character Index", 3900, 310)
    clamp_low = _math(group, "MAXIMUM", "Character Clamp Low", 4080, 310, value_2=0.0)
    clamp_high = _math(group, "MINIMUM", "Character Clamp High", 4260, 310, value_2=float(ASCII_ATLAS_COLUMNS - 1))
    index_round = _math(group, "ROUND", "Final Character Index", 4440, 310)
    index_debug = _math(group, "DIVIDE", "Normalized Character Index", 4620, 250, value_2=float(max(1, ASCII_ATLAS_COLUMNS - 1)))

    links.new(grid["cell_id"], random.inputs["Vector"])
    links.new(inp.outputs["Seed"], random.inputs["W"])
    links.new(random.outputs["Value"], random_center.inputs[0])
    links.new(random_center.outputs[0], random_full.inputs[0])
    links.new(random_full.outputs[0], variation_amount.inputs[0])
    links.new(inp.outputs["Variation"], variation_amount.inputs[1])
    links.new(inp.outputs["Seed"], dither_seed.inputs[0])
    links.new(grid["cell_id"], dither_noise.inputs["Vector"])
    links.new(dither_seed.outputs[0], dither_noise.inputs["W"])
    links.new(dither_noise.outputs["Value"], dither_center.inputs[0])
    links.new(dither_center.outputs[0], dither_amount.inputs[0])
    links.new(inp.outputs["Dither"], dither_amount.inputs[1])
    links.new(inp.outputs["Character Count"], count_minus.inputs[0])
    links.new(count_minus.outputs[0], safe_levels.inputs[0])
    links.new(dither_amount.outputs[0], dither_scaled.inputs[0])
    links.new(safe_levels.outputs[0], dither_scaled.inputs[1])
    links.new(density_high.outputs[0], dithered_density.inputs[0])
    links.new(dither_scaled.outputs[0], dithered_density.inputs[1])
    links.new(dithered_density.outputs[0], dither_low.inputs[0])
    links.new(dither_low.outputs[0], dither_high.inputs[0])
    links.new(count_minus.outputs[0], variation_half_count.inputs[0])
    links.new(variation_half_count.outputs[0], variation_cap.inputs[0])
    links.new(variation_amount.outputs[0], variation_levels.inputs[0])
    links.new(variation_cap.outputs[0], variation_levels.inputs[1])
    links.new(dither_high.outputs[0], scaled_density.inputs[0])
    links.new(count_minus.outputs[0], scaled_density.inputs[1])
    links.new(scaled_density.outputs[0], rounded.inputs[0])
    links.new(rounded.outputs[0], normalize.inputs[0])
    links.new(safe_levels.outputs[0], normalize.inputs[1])
    links.new(normalize.outputs[0], atlas_scale.inputs[0])
    links.new(atlas_scale.outputs[0], with_variation.inputs[0])
    links.new(variation_levels.outputs[0], with_variation.inputs[1])
    links.new(with_variation.outputs[0], clamp_low.inputs[0])
    links.new(clamp_low.outputs[0], clamp_high.inputs[0])
    links.new(clamp_high.outputs[0], index_round.inputs[0])
    links.new(index_round.outputs[0], index_debug.inputs[0])

    local_sep = _node(group, "ShaderNodeSeparateXYZ", "Textellation Local Coordinates", 4480, 20)
    atlas_x_add = _math(group, "ADD", "Atlas X Cell", 4660, 150)
    atlas_x = _math(group, "DIVIDE", "Atlas X", 4840, 150, value_2=float(ASCII_ATLAS_COLUMNS))
    row_flip = _math(group, "SUBTRACT", "Atlas Row Flip", 4480, -70, value_1=float(atlas_rows - 1))
    atlas_y_add = _math(group, "ADD", "Atlas Y Cell", 4660, -70)
    atlas_y = _math(group, "DIVIDE", "Atlas Y", 4840, -70, value_2=float(atlas_rows))
    atlas_vector = _node(group, "ShaderNodeCombineXYZ", "Atlas UV", 5020, 70)
    atlas = _node(group, "ShaderNodeTexImage", "Textellation Glyph Atlas", 5200, 70)
    atlas["fbp_ascii_atlas_node"] = True
    atlas.interpolation = "Closest"
    atlas.extension = "CLIP"
    atlas.image = atlas_image
    links.new(grid["local_uv"], local_sep.inputs[0])
    links.new(index_round.outputs[0], atlas_x_add.inputs[0])
    links.new(local_sep.outputs["X"], atlas_x_add.inputs[1])
    links.new(atlas_x_add.outputs[0], atlas_x.inputs[0])
    links.new(inp.outputs["Charset Row"], row_flip.inputs[1])
    links.new(row_flip.outputs[0], atlas_y_add.inputs[0])
    links.new(local_sep.outputs["Y"], atlas_y_add.inputs[1])
    links.new(atlas_y_add.outputs[0], atlas_y.inputs[0])
    links.new(atlas_x.outputs[0], atlas_vector.inputs["X"])
    links.new(atlas_y.outputs[0], atlas_vector.inputs["Y"])
    links.new(atlas_vector.outputs[0], atlas.inputs["Vector"])

    foreground = _mix_rgb(group, "MIX", "Textellation Foreground", 5200, 430)
    final = _mix_rgb(group, "MIX", "Textellation Output", 5440, 330)
    source_visible = _math(group, "GREATER_THAN", "Textellation Visible Source", 5200, -140, value_2=0.0)
    glyph_visible = _math(group, "MULTIPLY", "Textellation Visible Glyph", 5440, 20)
    final_alpha = _mix_rgb(group, "MIX", "Textellation Final Alpha", 5620, -50)
    links.new(inp.outputs["Use Source Color"], foreground.inputs[0])
    links.new(inp.outputs["Foreground"], foreground.inputs[1])
    # Font color deliberately uses the original straight source RGB. Alpha only
    # affects luminance selection and visibility, never darkens the glyph color.
    links.new(source_color, foreground.inputs[2])
    links.new(atlas.outputs["Alpha"], final.inputs[0])
    links.new(inp.outputs["Background"], final.inputs[1])
    links.new(foreground.outputs[0], final.inputs[2])
    debug_color = _debug_color(
        group,
        final.outputs[0],
        base_luminance,
        index_debug.outputs[0],
        inp.outputs["Debug Mode"],
        x=5620,
        y=430,
        prefix="Textellation",
    )
    links.new(debug_color, out.inputs["Color Out"])
    links.new(source_alpha, source_visible.inputs[0])
    links.new(atlas.outputs["Alpha"], glyph_visible.inputs[0])
    links.new(source_visible.outputs[0], glyph_visible.inputs[1])
    # False = opaque cell background, True = only the glyph. Both branches use
    # a binary source-presence mask; partial alpha is not emitted as opacity.
    links.new(inp.outputs["Transparent Background"], final_alpha.inputs[0])
    links.new(source_visible.outputs[0], final_alpha.inputs[1])
    links.new(glyph_visible.outputs[0], final_alpha.inputs[2])
    debug_active = _math(group, "GREATER_THAN", "Textellation Debug Active", 5800, -180, value_2=0.5)
    debug_alpha = _mix_rgb(group, "MIX", "Textellation Debug Alpha", 5980, -50)
    links.new(inp.outputs["Debug Mode"], debug_active.inputs[0])
    links.new(debug_active.outputs[0], debug_alpha.inputs[0])
    links.new(final_alpha.outputs[0], debug_alpha.inputs[1])
    debug_alpha.inputs[2].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(debug_alpha.outputs[0], out.inputs["Alpha Out"])
    return group


def _create_text_matrix(name):
    """Create real vector text sampled from image-cell centers.

    Luminance mapping matches Textellation: white selects light/blank glyphs,
    black selects dense glyphs. Partial alpha is composited over white for
    character selection, but cells remain fully visible above Alpha Threshold.
    Source RGB can be stored as a named point attribute and read by the owned
    Text Matrix material, preserving per-cell image color.
    """
    glyph_count = 16
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Columns", "INPUT", "NodeSocketInt", default=48, minimum=2, maximum=512)
    _socket(group, "Rows", "INPUT", "NodeSocketInt", default=0, minimum=0, maximum=512)
    _socket(group, "Character Count", "INPUT", "NodeSocketInt", default=16, minimum=2, maximum=glyph_count)
    _socket(group, "Character Aspect", "INPUT", "NodeSocketFloat", default=0.60, minimum=0.1, maximum=2.0)
    _socket(group, "Glyph Scale", "INPUT", "NodeSocketFloat", default=0.88, minimum=0.05, maximum=2.0)
    _socket(group, "Contrast", "INPUT", "NodeSocketFloat", default=1.3, minimum=0.0, maximum=8.0)
    _socket(group, "Invert", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Variation", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Seed", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100000.0, maximum=100000.0)
    _socket(group, "Alpha Threshold", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Use Source Color", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Text Color", "INPUT", "NodeSocketColor", default=(0.1, 1.0, 0.2, 1.0))
    _socket(group, "Transparent Background", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Realize Text", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Depth Offset", "INPUT", "NodeSocketFloat", default=0.001, minimum=-1.0, maximum=1.0)
    _socket(group, "Font", "INPUT", "NodeSocketFont")
    _socket(group, "Text Material", "INPUT", "NodeSocketMaterial")
    _socket(group, "Background Material", "INPUT", "NodeSocketMaterial")
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    bbox = _node(group, "GeometryNodeBoundBox", "Source Bounds", -1700, 460)
    size = _vector_math(group, "SUBTRACT", "Plane Size", -1500, 460)
    center_add = _vector_math(group, "ADD", "Bounds Sum", -1500, 270)
    center = _vector_math(group, "SCALE", "Bounds Center", -1300, 270)
    center.inputs[3].default_value = 0.5
    separate_size = _node(group, "ShaderNodeSeparateXYZ", "Separate Plane Size", -1300, 460)
    width_safe = _math(group, "MAXIMUM", "Safe Width", -1100, 600, value_2=0.0001)
    height_safe = _math(group, "MAXIMUM", "Safe Height", -1100, 450, value_2=0.0001)
    height_ratio = _math(group, "DIVIDE", "Height Width Ratio", -920, 460)
    rows_base = _math(group, "MULTIPLY", "Rows From Columns", -740, 460)
    rows_aspect = _math(group, "MULTIPLY", "Rows Character Aspect", -560, 460)
    rows_round = _math(group, "ROUND", "Rounded Auto Rows", -380, 460)
    auto_rows = _math(group, "MAXIMUM", "Minimum Auto Rows", -200, 500, value_2=2.0)
    manual_rows = _math(group, "MAXIMUM", "Minimum Manual Rows", -200, 350, value_2=2.0)
    manual_rows_enabled = _math(group, "GREATER_THAN", "Use Manual Rows", -20, 350, value_2=0.5)
    rows = _node(group, "GeometryNodeSwitch", "Text Matrix Rows", 160, 420)
    rows.input_type = "FLOAT"
    cell_width = _math(group, "DIVIDE", "Cell Width", -920, 700)
    cell_height = _math(group, "DIVIDE", "Cell Height", 360, 500)
    grid_x = _math(group, "SUBTRACT", "Inset Grid Width", -740, 700)
    grid_y = _math(group, "SUBTRACT", "Inset Grid Height", 540, 500)

    grid = _node(group, "GeometryNodeMeshGrid", "Character Grid", 720, 500)
    transform_grid = _node(group, "GeometryNodeTransform", "Center Character Grid", 930, 500)
    mesh_points = _node(group, "GeometryNodeMeshToPoints", "Character Points", 1120, 470)
    offset = _node(group, "ShaderNodeCombineXYZ", "Text Depth Offset", 1130, 230)
    set_position = _node(group, "GeometryNodeSetPosition", "Offset Text Points", 1530, 470)

    # Derive UV coordinates from the actual point position rather than Grid point
    # indices. Mesh Grid does not promise the index traversal assumed by the old
    # implementation; on some Blender builds that transposed and scrambled the
    # sampled image. Position-normalized UVs remain stable for every grid order.
    position = _node(group, "GeometryNodeInputPosition", "Character Point Position", 1260, 80)
    separate_position = _node(group, "ShaderNodeSeparateXYZ", "Separate Point Position", 1440, 80)
    separate_min = _node(group, "ShaderNodeSeparateXYZ", "Separate Bounds Minimum", 1440, -120)
    u_offset = _math(group, "SUBTRACT", "Point U Offset", 1620, 120)
    v_offset = _math(group, "SUBTRACT", "Point V Offset", 1620, -20)
    normalized_u = _math(group, "DIVIDE", "Cell Center U", 1800, 120)
    normalized_v = _math(group, "DIVIDE", "Cell Center V", 1800, -20)
    u_low = _math(group, "MAXIMUM", "Clamp U Low", 1980, 120, value_2=0.0)
    v_low = _math(group, "MAXIMUM", "Clamp V Low", 1980, -20, value_2=0.0)
    u_high = _math(group, "MINIMUM", "Clamp U High", 2160, 120, value_2=1.0)
    v_high = _math(group, "MINIMUM", "Clamp V High", 2160, -20, value_2=1.0)
    center_uv = _node(group, "ShaderNodeCombineXYZ", "Cell Center UV", 2340, 60)

    image = _node(group, "GeometryNodeImageTexture", "Text Matrix Source Image", 1660, 90)
    image["fbp_alpha_image_node"] = True
    image["fbp_text_matrix_image_node"] = True
    try:
        image.extension = "EXTEND"
        image.interpolation = "Closest"
    except (AttributeError, TypeError, ValueError):
        pass

    raw_luma = _vector_math(group, "DOT_PRODUCT", "Image Luminance", 1880, 70)
    raw_luma.inputs[1].default_value = (0.2126, 0.7152, 0.0722)
    alpha_low = _math(group, "MAXIMUM", "Source Alpha Minimum", 1880, -100, value_2=0.0)
    alpha_high = _math(group, "MINIMUM", "Source Alpha Maximum", 2060, -100, value_2=1.0)
    luma_opaque = _math(group, "MULTIPLY", "Opaque Luminance", 2080, 70)
    transparent_weight = _math(group, "SUBTRACT", "Transparent Is White", 2240, -100, value_1=1.0)
    alpha_aware_luma = _math(group, "ADD", "Alpha Aware Luminance", 2260, 70)
    luma_center = _math(group, "SUBTRACT", "Luminance Center", 2440, 70, value_2=0.5)
    luma_contrast = _math(group, "MULTIPLY", "Luminance Contrast", 2620, 70)
    luma_restore = _math(group, "ADD", "Luminance Restore", 2800, 70, value_2=0.5)
    luma_floor = _math(group, "MAXIMUM", "Luminance Low", 2980, 70, value_2=0.0)
    luma_clamp = _math(group, "MINIMUM", "Luminance High", 3160, 70, value_2=1.0)
    luma_inverse = _math(group, "SUBTRACT", "Inverted Luminance", 3160, -80, value_1=1.0)
    luma_switch = _node(group, "GeometryNodeSwitch", "Invert Luminance", 3350, 50)
    luma_switch.input_type = "FLOAT"
    density = _math(group, "SUBTRACT", "Glyph Density", 3550, 50, value_1=1.0)

    white_noise = _node(group, "ShaderNodeTexWhiteNoise", "Character Variation", 2600, -260)
    white_noise.noise_dimensions = "4D"
    noise_center = _math(group, "SUBTRACT", "Centered Character Variation", 2800, -260, value_2=0.5)
    noise_amount = _math(group, "MULTIPLY", "Character Variation Amount", 2980, -260)
    varied_density = _math(group, "ADD", "Varied Glyph Density", 3730, -70)
    varied_low = _math(group, "MAXIMUM", "Varied Low", 3910, -70, value_2=0.0)
    varied_high = _math(group, "MINIMUM", "Varied High", 4090, -70, value_2=1.0)
    levels = _math(group, "SUBTRACT", "Glyph Levels", 3730, 130, value_2=1.0)
    glyph_float = _math(group, "MULTIPLY", "Glyph Level Float", 4270, 30)
    glyph_index = _math(group, "ROUND", "Glyph Index", 4450, 30)
    alpha_visible = _math(group, "GREATER_THAN", "Visible Source Alpha", 2240, -180)

    color_switch = _node(group, "GeometryNodeSwitch", "Text Matrix Source Color", 2450, -430)
    color_switch.input_type = "RGBA"
    store_color = _node(group, "GeometryNodeStoreNamedAttribute", "Store Text Matrix Color", 1740, 470)
    store_color.data_type = "FLOAT_COLOR"
    store_color.domain = "POINT"
    store_color.inputs["Name"].default_value = "fbp_text_matrix_color"

    text_scale = _math(group, "MULTIPLY", "Text Scale", 20, 650)
    scale_vector = _node(group, "ShaderNodeCombineXYZ", "Glyph Scale Vector", 220, 700)

    links.new(inp.outputs["Geometry"], bbox.inputs["Geometry"])
    links.new(bbox.outputs["Max"], size.inputs[0])
    links.new(bbox.outputs["Min"], size.inputs[1])
    links.new(bbox.outputs["Max"], center_add.inputs[0])
    links.new(bbox.outputs["Min"], center_add.inputs[1])
    links.new(center_add.outputs[0], center.inputs[0])
    links.new(size.outputs[0], separate_size.inputs[0])
    links.new(separate_size.outputs["X"], width_safe.inputs[0])
    links.new(separate_size.outputs["Y"], height_safe.inputs[0])
    links.new(height_safe.outputs[0], height_ratio.inputs[0])
    links.new(width_safe.outputs[0], height_ratio.inputs[1])
    links.new(height_ratio.outputs[0], rows_base.inputs[0])
    links.new(inp.outputs["Columns"], rows_base.inputs[1])
    links.new(rows_base.outputs[0], rows_aspect.inputs[0])
    links.new(inp.outputs["Character Aspect"], rows_aspect.inputs[1])
    links.new(rows_aspect.outputs[0], rows_round.inputs[0])
    links.new(rows_round.outputs[0], auto_rows.inputs[0])
    links.new(inp.outputs["Rows"], manual_rows.inputs[0])
    links.new(inp.outputs["Rows"], manual_rows_enabled.inputs[0])
    links.new(manual_rows_enabled.outputs[0], rows.inputs["Switch"])
    links.new(auto_rows.outputs[0], rows.inputs["False"])
    links.new(manual_rows.outputs[0], rows.inputs["True"])
    links.new(width_safe.outputs[0], cell_width.inputs[0])
    links.new(inp.outputs["Columns"], cell_width.inputs[1])
    links.new(height_safe.outputs[0], cell_height.inputs[0])
    links.new(rows.outputs["Output"], cell_height.inputs[1])
    links.new(width_safe.outputs[0], grid_x.inputs[0])
    links.new(cell_width.outputs[0], grid_x.inputs[1])
    links.new(height_safe.outputs[0], grid_y.inputs[0])
    links.new(cell_height.outputs[0], grid_y.inputs[1])
    links.new(grid_x.outputs[0], grid.inputs["Size X"])
    links.new(grid_y.outputs[0], grid.inputs["Size Y"])
    links.new(inp.outputs["Columns"], grid.inputs["Vertices X"])
    links.new(rows.outputs["Output"], grid.inputs["Vertices Y"])
    links.new(grid.outputs["Mesh"], transform_grid.inputs["Geometry"])
    links.new(center.outputs[0], transform_grid.inputs["Translation"])

    links.new(position.outputs["Position"], separate_position.inputs[0])
    links.new(bbox.outputs["Min"], separate_min.inputs[0])
    links.new(separate_position.outputs["X"], u_offset.inputs[0])
    links.new(separate_min.outputs["X"], u_offset.inputs[1])
    links.new(separate_position.outputs["Y"], v_offset.inputs[0])
    links.new(separate_min.outputs["Y"], v_offset.inputs[1])
    links.new(u_offset.outputs[0], normalized_u.inputs[0])
    links.new(width_safe.outputs[0], normalized_u.inputs[1])
    links.new(v_offset.outputs[0], normalized_v.inputs[0])
    links.new(height_safe.outputs[0], normalized_v.inputs[1])
    links.new(normalized_u.outputs[0], u_low.inputs[0])
    links.new(normalized_v.outputs[0], v_low.inputs[0])
    links.new(u_low.outputs[0], u_high.inputs[0])
    links.new(v_low.outputs[0], v_high.inputs[0])
    links.new(u_high.outputs[0], center_uv.inputs["X"])
    links.new(v_high.outputs[0], center_uv.inputs["Y"])

    links.new(center_uv.outputs[0], image.inputs["Vector"])
    links.new(transform_grid.outputs["Geometry"], mesh_points.inputs["Mesh"])
    links.new(image.outputs["Alpha"], alpha_visible.inputs[0])
    links.new(inp.outputs["Alpha Threshold"], alpha_visible.inputs[1])
    links.new(mesh_points.outputs["Points"], set_position.inputs["Geometry"])
    links.new(inp.outputs["Depth Offset"], offset.inputs["Z"])
    links.new(offset.outputs[0], set_position.inputs["Offset"])

    links.new(image.outputs["Color"], raw_luma.inputs[0])
    links.new(image.outputs["Alpha"], alpha_low.inputs[0])
    links.new(alpha_low.outputs[0], alpha_high.inputs[0])
    links.new(raw_luma.outputs["Value"], luma_opaque.inputs[0])
    links.new(alpha_high.outputs[0], luma_opaque.inputs[1])
    links.new(alpha_high.outputs[0], transparent_weight.inputs[1])
    links.new(luma_opaque.outputs[0], alpha_aware_luma.inputs[0])
    links.new(transparent_weight.outputs[0], alpha_aware_luma.inputs[1])
    links.new(alpha_aware_luma.outputs[0], luma_center.inputs[0])
    links.new(luma_center.outputs[0], luma_contrast.inputs[0])
    links.new(inp.outputs["Contrast"], luma_contrast.inputs[1])
    links.new(luma_contrast.outputs[0], luma_restore.inputs[0])
    links.new(luma_restore.outputs[0], luma_floor.inputs[0])
    links.new(luma_floor.outputs[0], luma_clamp.inputs[0])
    links.new(luma_clamp.outputs[0], luma_inverse.inputs[1])
    links.new(inp.outputs["Invert"], luma_switch.inputs["Switch"])
    links.new(luma_clamp.outputs[0], luma_switch.inputs["False"])
    links.new(luma_inverse.outputs[0], luma_switch.inputs["True"])
    links.new(luma_switch.outputs["Output"], density.inputs[1])
    links.new(center_uv.outputs[0], white_noise.inputs["Vector"])
    links.new(inp.outputs["Seed"], white_noise.inputs["W"])
    links.new(white_noise.outputs["Value"], noise_center.inputs[0])
    links.new(noise_center.outputs[0], noise_amount.inputs[0])
    links.new(inp.outputs["Variation"], noise_amount.inputs[1])
    links.new(density.outputs[0], varied_density.inputs[0])
    links.new(noise_amount.outputs[0], varied_density.inputs[1])
    links.new(varied_density.outputs[0], varied_low.inputs[0])
    links.new(varied_low.outputs[0], varied_high.inputs[0])
    links.new(inp.outputs["Character Count"], levels.inputs[0])
    links.new(varied_high.outputs[0], glyph_float.inputs[0])
    links.new(levels.outputs[0], glyph_float.inputs[1])
    links.new(glyph_float.outputs[0], glyph_index.inputs[0])

    links.new(inp.outputs["Use Source Color"], color_switch.inputs["Switch"])
    links.new(inp.outputs["Text Color"], color_switch.inputs["False"])
    links.new(image.outputs["Color"], color_switch.inputs["True"])
    links.new(set_position.outputs["Geometry"], store_color.inputs["Geometry"])
    links.new(color_switch.outputs["Output"], store_color.inputs["Value"])

    # Character Aspect controls the row count, so the physical cell width is
    # the stable scale reference. Scaling from cell height makes wide planes
    # produce glyphs several columns wide and causes heavy overlap.
    links.new(cell_width.outputs[0], text_scale.inputs[0])
    links.new(inp.outputs["Glyph Scale"], text_scale.inputs[1])
    for axis in ("X", "Y", "Z"):
        links.new(text_scale.outputs[0], scale_vector.inputs[axis])

    # Use one instance branch per glyph. This is slightly larger than an
    # indexed instance library, but it is robust across Blender field contexts:
    # each branch receives an explicit density comparison and blank glyphs
    # naturally produce no geometry without shifting later character slots.
    character_instances = _node(group, "GeometryNodeJoinGeometry", "Character Instances", 5880, 380)
    for index in range(glyph_count):
        y = 1080 - index * 190
        string = _node(group, "GeometryNodeStringToCurves", f"Glyph {index:02d}", 4540, y)
        string["fbp_text_matrix_glyph_index"] = index
        string.inputs["String"].default_value = "@" if index >= glyph_count // 2 else "."
        string.inputs["Size"].default_value = 1.0
        string.inputs["Align X"].default_value = "Center"
        string.inputs["Align Y"].default_value = "Middle"
        string.inputs["Pivot Point"].default_value = "Midpoint"
        links.new(inp.outputs["Font"], string.inputs["Font"])

        realize_glyph = _node(group, "GeometryNodeRealizeInstances", f"Realize Glyph {index:02d}", 4760, y)
        fill = _node(group, "GeometryNodeFillCurve", f"Fill Glyph {index:02d}", 4960, y)
        material = _node(group, "GeometryNodeSetMaterial", f"Text Material {index:02d}", 5140, y)
        compare = _math(group, "COMPARE", f"Select Glyph {index:02d}", 5340, y - 10)
        compare.inputs[1].default_value = float(index)
        epsilon = _input(compare, "Epsilon", 2)
        if epsilon is not None:
            epsilon.default_value = 0.1
        visible = _math(group, "MULTIPLY", f"Visible Glyph {index:02d}", 5520, y - 10)
        instance = _node(group, "GeometryNodeInstanceOnPoints", f"Instance Glyph {index:02d}", 5700, y)

        links.new(string.outputs["Curve Instances"], realize_glyph.inputs["Geometry"])
        links.new(realize_glyph.outputs["Geometry"], fill.inputs["Curve"])
        links.new(fill.outputs["Mesh"], material.inputs["Geometry"])
        links.new(inp.outputs["Text Material"], material.inputs["Material"])
        links.new(glyph_index.outputs[0], compare.inputs[0])
        links.new(compare.outputs[0], visible.inputs[0])
        links.new(alpha_visible.outputs[0], visible.inputs[1])
        links.new(store_color.outputs["Geometry"], instance.inputs["Points"])
        links.new(visible.outputs[0], instance.inputs["Selection"])
        links.new(material.outputs["Geometry"], instance.inputs["Instance"])
        links.new(scale_vector.outputs[0], instance.inputs["Scale"])
        links.new(instance.outputs["Instances"], character_instances.inputs["Geometry"])

    realize = _node(group, "GeometryNodeRealizeInstances", "Realize Text Matrix", 5980, 300)
    realize_switch = _node(group, "GeometryNodeSwitch", "Realize Text", 6200, 420)
    realize_switch.input_type = "GEOMETRY"
    links.new(character_instances.outputs["Geometry"], realize.inputs["Geometry"])
    links.new(inp.outputs["Realize Text"], realize_switch.inputs["Switch"])
    links.new(character_instances.outputs["Geometry"], realize_switch.inputs["False"])
    links.new(realize.outputs["Geometry"], realize_switch.inputs["True"])

    background_material = _node(group, "GeometryNodeSetMaterial", "Text Matrix Background", 5760, -980)
    background_switch = _node(group, "GeometryNodeSwitch", "Transparent Background", 6010, -980)
    background_switch.input_type = "GEOMETRY"
    join_output = _node(group, "GeometryNodeJoinGeometry", "Text Matrix Output", 6460, 260)
    links.new(inp.outputs["Geometry"], background_material.inputs["Geometry"])
    links.new(inp.outputs["Background Material"], background_material.inputs["Material"])
    links.new(inp.outputs["Transparent Background"], background_switch.inputs["Switch"])
    links.new(background_material.outputs["Geometry"], background_switch.inputs["False"])
    links.new(realize_switch.outputs["Output"], join_output.inputs["Geometry"])
    links.new(background_switch.outputs["Output"], join_output.inputs["Geometry"])
    links.new(join_output.outputs["Geometry"], out.inputs["Geometry"])
    group["fbp_text_matrix_uv_version"] = 2
    group["fbp_text_matrix_rows_version"] = 1
    return group


def _create_wind_bender(name):
    """Create a pin-aware flag/paper deformation Geometry Nodes group."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Subdivision", "INPUT", "NodeSocketInt", default=4, minimum=0, maximum=7)
    _socket(group, "Bend Amount", "INPUT", "NodeSocketFloat", default=0.5, minimum=-10.0, maximum=10.0)
    _socket(group, "Wind Speed", "INPUT", "NodeSocketFloat", default=2.0, minimum=-100.0, maximum=100.0)
    _socket(group, "Stepped", "INPUT", "NodeSocketInt", default=1, minimum=1, maximum=240)
    _socket(group, "Pin Edge", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=3.0)
    _socket(group, "Motion Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Wave Count", "INPUT", "NodeSocketFloat", default=2.0, minimum=0.0, maximum=40.0)
    _socket(group, "Wave Amplitude", "INPUT", "NodeSocketFloat", default=0.12, minimum=0.0, maximum=10.0)
    _socket(group, "Wave Speed", "INPUT", "NodeSocketFloat", default=2.0, minimum=-100.0, maximum=100.0)
    _socket(group, "Phase", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1000.0, maximum=1000.0)
    _socket(group, "Turbulence", "INPUT", "NodeSocketFloat", default=0.03, minimum=0.0, maximum=2.0)
    _socket(group, "Falloff", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.1, maximum=8.0)
    _socket(group, "Noise Scale", "INPUT", "NodeSocketFloat", default=3.0, minimum=0.01, maximum=100.0)
    _socket(group, "Gust Strength", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Direction Space", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Wind Direction", "INPUT", "NodeSocketVector", default=(0.0, 0.0, 1.0))
    _socket(group, "Preview Falloff", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Reverse Direction", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    subdivide = _node(group, "GeometryNodeSubdivideMesh", "Wind Subdivision", -1400, 320)
    bounds = _node(group, "GeometryNodeBoundBox", "Plane Bounds", -1200, 100)
    position = _node(group, "GeometryNodeInputPosition", "Position", -1200, -120)
    pos_xyz = _node(group, "ShaderNodeSeparateXYZ", "Position Axes", -1020, -120)
    min_xyz = _node(group, "ShaderNodeSeparateXYZ", "Minimum Axes", -1020, 80)
    max_xyz = _node(group, "ShaderNodeSeparateXYZ", "Maximum Axes", -1020, 250)
    links.new(inp.outputs["Geometry"], subdivide.inputs["Mesh"])
    links.new(inp.outputs["Subdivision"], subdivide.inputs["Level"])
    links.new(subdivide.outputs["Mesh"], bounds.inputs["Geometry"])
    links.new(position.outputs["Position"], pos_xyz.inputs[0])
    links.new(bounds.outputs["Min"], min_xyz.inputs[0])
    links.new(bounds.outputs["Max"], max_xyz.inputs[0])

    def normalized_axis(axis, y):
        size = _math(group, "SUBTRACT", f"{axis} Bounds Size", -820, y)
        safe_size = _math(group, "MAXIMUM", f"Safe {axis} Size", -650, y, value_2=0.000001)
        relative = _math(group, "SUBTRACT", f"{axis} From Minimum", -820, y - 90)
        normalized = _math(group, "DIVIDE", f"Normalized {axis}", -470, y - 40)
        links.new(max_xyz.outputs[axis], size.inputs[0])
        links.new(min_xyz.outputs[axis], size.inputs[1])
        links.new(size.outputs[0], safe_size.inputs[0])
        links.new(pos_xyz.outputs[axis], relative.inputs[0])
        links.new(min_xyz.outputs[axis], relative.inputs[1])
        links.new(relative.outputs[0], normalized.inputs[0])
        links.new(safe_size.outputs[0], normalized.inputs[1])
        return normalized.outputs[0]

    norm_x = normalized_axis("X", 220)
    norm_y = normalized_axis("Y", -20)
    normalized_vector = _node(group, "ShaderNodeCombineXYZ", "Normalized Coordinates", -250, -120)
    links.new(norm_x, normalized_vector.inputs["X"])
    links.new(norm_y, normalized_vector.inputs["Y"])

    right_distance = _math(group, "SUBTRACT", "Distance From Right", -260, 250, value_1=1.0)
    top_distance = _math(group, "SUBTRACT", "Distance From Top", -260, 40, value_1=1.0)
    links.new(norm_x, right_distance.inputs[1])
    links.new(norm_y, top_distance.inputs[1])
    distances = (norm_x, right_distance.outputs[0], norm_y, top_distance.outputs[0])

    weighted = []
    for index, distance in enumerate(distances):
        compare = _math(group, "COMPARE", f"Pin Edge {index}", -30, 330 - index * 105)
        compare.inputs[1].default_value = float(index)
        epsilon = _input(compare, "Epsilon", 2)
        if epsilon is not None:
            epsilon.default_value = 0.1
        multiply = _math(group, "MULTIPLY", f"Pinned Falloff {index}", 150, 330 - index * 105)
        links.new(inp.outputs["Pin Edge"], compare.inputs[0])
        links.new(distance, multiply.inputs[0])
        links.new(compare.outputs[0], multiply.inputs[1])
        weighted.append(multiply.outputs[0])
    add_a = _math(group, "ADD", "Pinned Horizontal", 340, 250)
    add_b = _math(group, "ADD", "Pinned Vertical", 340, 20)
    falloff = _math(group, "ADD", "Pinned Edge Falloff", 520, 135)
    links.new(weighted[0], add_a.inputs[0])
    links.new(weighted[1], add_a.inputs[1])
    links.new(weighted[2], add_b.inputs[0])
    links.new(weighted[3], add_b.inputs[1])
    links.new(add_a.outputs[0], falloff.inputs[0])
    links.new(add_b.outputs[0], falloff.inputs[1])
    shaped_falloff = _math(group, "POWER", "Pinned Falloff Shape", 700, 135)
    links.new(falloff.outputs[0], shaped_falloff.inputs[0])
    links.new(inp.outputs["Falloff"], shaped_falloff.inputs[1])

    scene_time = _node(group, "GeometryNodeInputSceneTime", "Scene Time", -850, -420)
    safe_step = _math(group, "MAXIMUM", "Safe Step", -850, -540, value_2=1.0)
    frame_div = _math(group, "DIVIDE", "Stepped Frame Divide", -650, -420)
    frame_floor = _math(group, "FLOOR", "Stepped Frame Floor", -470, -420)
    stepped_frame = _math(group, "MULTIPLY", "Stepped Frame", -290, -420)
    time_scale = _math(group, "MULTIPLY", "Animation Time Scale", -110, -420, value_2=0.1)
    links.new(inp.outputs["Stepped"], safe_step.inputs[0])
    links.new(scene_time.outputs["Frame"], frame_div.inputs[0])
    links.new(safe_step.outputs[0], frame_div.inputs[1])
    links.new(frame_div.outputs[0], frame_floor.inputs[0])
    links.new(frame_floor.outputs[0], stepped_frame.inputs[0])
    links.new(safe_step.outputs[0], stepped_frame.inputs[1])
    links.new(stepped_frame.outputs[0], time_scale.inputs[0])

    sway_time = _math(group, "MULTIPLY", "Sway Time", 80, -430)
    sway_phase = _math(group, "ADD", "Sway Phase", 260, -430)
    sway_sine = _math(group, "SINE", "Sway", 440, -430)
    sway_amount = _math(group, "MULTIPLY", "Sway Amount", 620, -430)
    sway_falloff = _math(group, "MULTIPLY", "Sway Falloff", 800, -430)
    links.new(time_scale.outputs[0], sway_time.inputs[0])
    links.new(inp.outputs["Wind Speed"], sway_time.inputs[1])
    links.new(sway_time.outputs[0], sway_phase.inputs[0])
    links.new(inp.outputs["Phase"], sway_phase.inputs[1])
    links.new(sway_phase.outputs[0], sway_sine.inputs[0])
    links.new(sway_sine.outputs[0], sway_amount.inputs[0])
    links.new(inp.outputs["Bend Amount"], sway_amount.inputs[1])
    links.new(sway_amount.outputs[0], sway_falloff.inputs[0])
    links.new(shaped_falloff.outputs[0], sway_falloff.inputs[1])

    wave_position = _math(group, "MULTIPLY", "Wave Position", 720, -160)
    wave_cycles = _math(group, "MULTIPLY", "Wave Cycles", 900, -160, value_2=6.283185307)
    wave_time = _math(group, "MULTIPLY", "Wave Time", 720, -280)
    wave_phase_a = _math(group, "ADD", "Wave Moving Phase", 1080, -220)
    wave_phase_b = _math(group, "ADD", "Wave User Phase", 1260, -220)
    wave_sine = _math(group, "SINE", "Flowing Wave", 1440, -220)
    wave_amount = _math(group, "MULTIPLY", "Wave Amount", 1620, -220)
    wave_falloff = _math(group, "MULTIPLY", "Wave Falloff", 1800, -220)
    links.new(shaped_falloff.outputs[0], wave_position.inputs[0])
    links.new(inp.outputs["Wave Count"], wave_position.inputs[1])
    links.new(wave_position.outputs[0], wave_cycles.inputs[0])
    links.new(time_scale.outputs[0], wave_time.inputs[0])
    links.new(inp.outputs["Wave Speed"], wave_time.inputs[1])
    links.new(wave_cycles.outputs[0], wave_phase_a.inputs[0])
    links.new(wave_time.outputs[0], wave_phase_a.inputs[1])
    links.new(wave_phase_a.outputs[0], wave_phase_b.inputs[0])
    links.new(inp.outputs["Phase"], wave_phase_b.inputs[1])
    links.new(wave_phase_b.outputs[0], wave_sine.inputs[0])
    links.new(wave_sine.outputs[0], wave_amount.inputs[0])
    links.new(inp.outputs["Wave Amplitude"], wave_amount.inputs[1])
    links.new(wave_amount.outputs[0], wave_falloff.inputs[0])
    links.new(shaped_falloff.outputs[0], wave_falloff.inputs[1])

    mode_normal = _math(group, "SUBTRACT", "Sway Mode Weight", 1040, -500, value_1=1.0)
    sway_mode = _math(group, "MULTIPLY", "Selected Sway", 1220, -480)
    wave_mode = _math(group, "MULTIPLY", "Selected Flow", 1980, -300)
    selected_motion = _math(group, "ADD", "Selected Wind Motion", 2160, -360)
    links.new(inp.outputs["Motion Mode"], mode_normal.inputs[1])
    links.new(sway_falloff.outputs[0], sway_mode.inputs[0])
    links.new(mode_normal.outputs[0], sway_mode.inputs[1])
    links.new(wave_falloff.outputs[0], wave_mode.inputs[0])
    links.new(inp.outputs["Motion Mode"], wave_mode.inputs[1])
    links.new(sway_mode.outputs[0], selected_motion.inputs[0])
    links.new(wave_mode.outputs[0], selected_motion.inputs[1])

    gust_noise = _node(group, "ShaderNodeTexNoise", "Wind Gusts", 1900, -760)
    gust_noise.noise_dimensions = "4D"
    gust_noise.inputs["Scale"].default_value = 0.65
    gust_noise.inputs["Detail"].default_value = 1.0
    gust_time = _math(group, "MULTIPLY", "Wind Gust Time", 1720, -820, value_2=0.37)
    gust_center = _math(group, "SUBTRACT", "Centered Wind Gust", 2100, -760, value_2=0.5)
    gust_full = _math(group, "MULTIPLY", "Full Wind Gust", 2280, -760, value_2=2.0)
    gust_amount = _math(group, "MULTIPLY", "Wind Gust Strength", 2460, -760)
    gust_factor = _math(group, "ADD", "Wind Gust Factor", 2640, -760, value_2=1.0)
    gust_motion = _math(group, "MULTIPLY", "Wind With Gusts", 2340, -360)
    links.new(normalized_vector.outputs[0], gust_noise.inputs["Vector"])
    links.new(time_scale.outputs[0], gust_time.inputs[0])
    links.new(gust_time.outputs[0], gust_noise.inputs["W"])
    links.new(gust_noise.outputs["Fac"], gust_center.inputs[0])
    links.new(gust_center.outputs[0], gust_full.inputs[0])
    links.new(gust_full.outputs[0], gust_amount.inputs[0])
    links.new(inp.outputs["Gust Strength"], gust_amount.inputs[1])
    links.new(gust_amount.outputs[0], gust_factor.inputs[0])
    links.new(selected_motion.outputs[0], gust_motion.inputs[0])
    links.new(gust_factor.outputs[0], gust_motion.inputs[1])

    noise = _node(group, "ShaderNodeTexNoise", "Wind Turbulence", 1400, -610)
    noise.noise_dimensions = "4D"
    noise.inputs["Detail"].default_value = 2.0
    noise_center = _math(group, "SUBTRACT", "Centered Turbulence", 1600, -610, value_2=0.5)
    noise_amount = _math(group, "MULTIPLY", "Turbulence Amount", 1780, -610)
    noise_falloff = _math(group, "MULTIPLY", "Turbulence Falloff", 1960, -610)
    total_motion = _math(group, "ADD", "Wind Plus Turbulence", 2340, -410)
    reverse_double = _math(group, "MULTIPLY", "Reverse Double", 2160, -650, value_2=2.0)
    reverse_sign = _math(group, "SUBTRACT", "Reverse Sign", 2340, -650, value_1=1.0)
    signed_motion = _math(group, "MULTIPLY", "Signed Wind", 2520, -420)
    preview_amount = _math(group, "MULTIPLY", "Falloff Preview Amount", 2520, -280, value_2=0.35)
    motion_switch = _node(group, "GeometryNodeSwitch", "Preview Pinned Falloff", 2700, -360)
    motion_switch.input_type = "FLOAT"
    normalize_direction = _vector_math(group, "NORMALIZE", "Normalized Wind Direction", 2700, -560)
    local_offset = _vector_math(group, "SCALE", "Local Wind Offset", 2900, -460)
    world_transform = _node(group, "ShaderNodeVectorTransform", "World Wind To Object", 2900, -650)
    world_transform.vector_type = "VECTOR"
    world_transform.convert_from = "WORLD"
    world_transform.convert_to = "OBJECT"
    world_offset = _vector_math(group, "SCALE", "World Wind Offset", 3100, -600)
    direction_switch = _node(group, "GeometryNodeSwitch", "Wind Direction Space", 3300, -470)
    direction_switch.input_type = "VECTOR"
    set_position = _node(group, "GeometryNodeSetPosition", "Wind Deformation", 3500, 220)
    links.new(normalized_vector.outputs[0], noise.inputs["Vector"])
    links.new(inp.outputs["Noise Scale"], noise.inputs["Scale"])
    links.new(time_scale.outputs[0], noise.inputs["W"])
    links.new(noise.outputs["Fac"], noise_center.inputs[0])
    links.new(noise_center.outputs[0], noise_amount.inputs[0])
    links.new(inp.outputs["Turbulence"], noise_amount.inputs[1])
    links.new(noise_amount.outputs[0], noise_falloff.inputs[0])
    links.new(shaped_falloff.outputs[0], noise_falloff.inputs[1])
    links.new(gust_motion.outputs[0], total_motion.inputs[0])
    links.new(noise_falloff.outputs[0], total_motion.inputs[1])
    links.new(inp.outputs["Reverse Direction"], reverse_double.inputs[0])
    links.new(reverse_double.outputs[0], reverse_sign.inputs[1])
    links.new(total_motion.outputs[0], signed_motion.inputs[0])
    links.new(reverse_sign.outputs[0], signed_motion.inputs[1])
    links.new(shaped_falloff.outputs[0], preview_amount.inputs[0])
    links.new(inp.outputs["Preview Falloff"], motion_switch.inputs["Switch"])
    links.new(signed_motion.outputs[0], motion_switch.inputs["False"])
    links.new(preview_amount.outputs[0], motion_switch.inputs["True"])
    links.new(inp.outputs["Wind Direction"], normalize_direction.inputs[0])
    links.new(normalize_direction.outputs[0], local_offset.inputs[0])
    links.new(motion_switch.outputs["Output"], local_offset.inputs[3])
    links.new(inp.outputs["Wind Direction"], world_transform.inputs[0])
    links.new(world_transform.outputs[0], world_offset.inputs[0])
    links.new(motion_switch.outputs["Output"], world_offset.inputs[3])
    links.new(inp.outputs["Direction Space"], direction_switch.inputs["Switch"])
    links.new(local_offset.outputs[0], direction_switch.inputs["False"])
    links.new(world_offset.outputs[0], direction_switch.inputs["True"])
    links.new(subdivide.outputs["Mesh"], set_position.inputs["Geometry"])
    links.new(direction_switch.outputs["Output"], set_position.inputs["Offset"])
    links.new(set_position.outputs["Geometry"], out.inputs["Geometry"])
    return group

def _interface_socket_names(group, in_out):
    """Return interface socket names without depending on one Blender API layout."""
    names = set()
    try:
        items = tuple(group.interface.items_tree)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        items = ()
    for item in items:
        try:
            if getattr(item, "item_type", "") != "SOCKET":
                continue
            if getattr(item, "in_out", "") == in_out:
                names.add(str(getattr(item, "name", "") or ""))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return names


def _builtin_group_is_complete(group, definition):
    """Reject interrupted or stale generated groups before they enter a material."""
    if group is None:
        return False
    required_inputs = {str(definition.get("input_socket", "") or "")}
    required_outputs = {str(definition.get("output_socket", "") or "")}
    required_inputs.update(
        str(socket_name or "")
        for socket_name in dict(definition.get("property_map", {})).values()
    )
    uv_input = str(definition.get("uv_input_socket", "") or "")
    alpha_input = str(definition.get("alpha_input_socket", "") or "")
    alpha_output = str(definition.get("alpha_output_socket", "") or "")
    debug_input = str(definition.get("debug_socket", "") or "")
    if debug_input:
        required_inputs.add(debug_input)
    if uv_input:
        required_inputs.add(uv_input)
    if alpha_input:
        required_inputs.add(alpha_input)
    if alpha_output:
        required_outputs.add(alpha_output)
    if str(definition.get("kind", "") or "") == "GEOMETRY":
        required_inputs.add("Geometry")
        required_outputs.add("Geometry")
    required_inputs.discard("")
    required_outputs.discard("")
    input_names = _interface_socket_names(group, "INPUT")
    output_names = _interface_socket_names(group, "OUTPUT")
    if not (required_inputs.issubset(input_names) and required_outputs.issubset(output_names)):
        return False
    try:
        output_node = next(
            node for node in group.nodes
            if getattr(node, "type", "") == "GROUP_OUTPUT" and bool(getattr(node, "is_active_output", True))
        )
    except (StopIteration, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    for socket_name in required_outputs:
        socket = _input(output_node, socket_name)
        if socket is None or not bool(getattr(socket, "is_linked", False)):
            return False
    if bool(definition.get("image_aware")):
        try:
            if str(definition.get("kind", "")) == "SHADER":
                if not any(bool(node.get("fbp_matrix_source_image_node", False)) for node in group.nodes):
                    return False
            elif not any(bool(node.get("fbp_alpha_image_node", False)) for node in group.nodes):
                return False
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False
    asset_id = str(definition.get("asset_id", "") or "")
    if asset_id.startswith("frame_by_plane.shader.textellation"):
        try:
            atlas_nodes = [node for node in group.nodes if bool(node.get("fbp_ascii_atlas_node", False))]
            if len(atlas_nodes) != 1:
                return False
            atlas_image = getattr(atlas_nodes[0], "image", None)
            if (
                atlas_image is None
                or int(atlas_image.get("fbp_ascii_atlas_version", 0) or 0) != ASCII_ATLAS_VERSION
                or str(atlas_image.get("fbp_ascii_atlas_revision", "") or "") != ASCII_ATLAS_REVISION
            ):
                return False
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False
    if asset_id.startswith("frame_by_plane.text_matrix"):
        try:
            glyph_nodes = [node for node in group.nodes if int(node.get("fbp_text_matrix_glyph_index", -1)) >= 0]
            color_store = group.nodes.get("Store Text Matrix Color")
            if (
                len(glyph_nodes) != 16
                or color_store is None
                or int(group.get("fbp_text_matrix_uv_version", 0) or 0) < 2
                or "Rows" not in input_names
            ):
                return False
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False
    return True


def create_builtin_effect_group(effect_id, definition, asset_dir):
    """Create or return a canonical built-in shader effect group."""
    if effect_id not in BUILTIN_EFFECT_IDS:
        return None
    canonical_name = str(definition.get("canonical_name", effect_id) or effect_id)
    existing = bpy.data.node_groups.get(canonical_name)
    if existing:
        try:
            same_asset = str(existing.get("fbp_effect_asset_id", "") or "") == str(definition.get("asset_id", "") or "")
        except (AttributeError, TypeError, ValueError):
            same_asset = False
        if same_asset and _builtin_group_is_complete(existing, definition):
            return existing
        try:
            if existing.users == 0:
                bpy.data.node_groups.remove(existing)
                existing = None
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        if existing is not None:
            canonical_name = canonical_name + " Rebuilt"

    builders = {
        "PIXELATE": lambda: _create_pixelate(canonical_name),
        "DIGITAL_NOISE": lambda: _create_digital_noise(canonical_name),
        "CHROMA_KEY": lambda: _create_chroma_key(canonical_name),
        "HALFTONE": lambda: _create_halftone(canonical_name),
        "DOT_MATRIX": lambda: _create_dot_matrix(canonical_name),
        "ASCII_MATRIX": lambda: _create_ascii_matrix(canonical_name, asset_dir),
        "TEXT_MATRIX": lambda: _create_text_matrix(canonical_name),
        "WIND_BENDER": lambda: _create_wind_bender(canonical_name),
    }
    builder = builders.get(effect_id)
    if builder is None:
        return None
    before = {group.as_pointer() for group in bpy.data.node_groups}
    try:
        group = builder()
        if not _builtin_group_is_complete(group, definition):
            raise RuntimeError(f"Generated {effect_id} group has an incomplete interface")
        return _tag(group, effect_id, definition)
    except Exception:
        # A failed builder can leave a half-created node group in the .blend.
        # Remove only groups created during this attempt and never touch user data.
        for candidate in tuple(bpy.data.node_groups):
            try:
                if candidate.as_pointer() not in before and candidate.users == 0:
                    bpy.data.node_groups.remove(candidate)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        raise
