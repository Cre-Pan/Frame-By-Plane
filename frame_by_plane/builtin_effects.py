"""Programmatically generated shader groups for Frame by Plane effects.

These groups are generated from the current Python contracts instead of being
reused from node groups embedded by previous add-on releases.
"""

from pathlib import Path

import bpy

from .runtime import FBP_DATA_ERRORS
from .effect_schema import FBP_EFFECT_SCHEMA_VERSION

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
    "RECOLOR",
    "GRADIENT_LIGHT",
    "RIM",
    "DEPTH_BLUR",
    "ALPHA_MATTE",
    "LUMA_MATTE",
    "SQUARE_MASK",
    "CIRCLE_MASK",
    "TRIANGLE_MASK",
    "CLIPPING_MASK",
    "COLOR_MASK",
    "GRADIENT_MASK",
    "NOISE_MASK",
    "DIGITAL_NOISE",
    "CHROMA_KEY",
    "HALFTONE",
    "DOT_MATRIX",
    "ASCII_MATRIX",
    "ASCII",
    "TEXT_MATRIX",
    "WIND_BENDER",
    "MESH_RIPPLE",
    "PAPER_CURL",
    "CUTOUT_OUTLINE",
    "THICKNESS",
    "CAMERA_SCALE_LOCK",
    "CAMERA_BILLBOARD",
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


def _alpha_geometry_mask(group, group_input, *, prefix="Alpha", x=-1500, y=240):
    """Build the shared image-alpha to temporary mesh contract.

    The returned mesh is a subdivided copy with transparent faces removed. The
    source geometry is never modified, so callers can join generated geometry
    back to the animated plane without replacing its material or topology.
    """
    links = group.links
    subdivide = _node(group, "GeometryNodeSubdivideMesh", f"{prefix} Detail", x, y)
    named_uv = _node(group, "GeometryNodeInputNamedAttribute", f"{prefix} UVMap", x, y - 360)
    try:
        named_uv.data_type = "FLOAT_VECTOR"
    except (AttributeError, TypeError, ValueError):
        pass
    name_socket = _input(named_uv, "Name")
    if name_socket is not None:
        name_socket.default_value = "UVMap"

    image_texture = _node(group, "GeometryNodeImageTexture", f"{prefix} Image", x + 240, y - 400)
    image_texture["fbp_alpha_image_node"] = True
    try:
        image_texture.extension = "EXTEND"
        image_texture.interpolation = "Linear"
    except (AttributeError, TypeError, ValueError):
        pass

    transparent = _math(group, "LESS_THAN", f"{prefix} Transparent", x + 490, y - 360)
    delete = _node(group, "GeometryNodeDeleteGeometry", f"{prefix} Delete Transparent", x + 740, y)
    try:
        delete.domain = "FACE"
    except (AttributeError, TypeError, ValueError):
        pass

    links.new(group_input.outputs["Geometry"], subdivide.inputs["Mesh"])
    links.new(group_input.outputs["Alpha Resolution"], subdivide.inputs["Level"])
    links.new(_output(named_uv, "Attribute", 0), _input(image_texture, "Vector"))
    links.new(_output(image_texture, "Alpha"), transparent.inputs[0])
    links.new(group_input.outputs["Alpha Threshold"], transparent.inputs[1])
    links.new(subdivide.outputs["Mesh"], delete.inputs["Geometry"])
    links.new(transparent.outputs[0], delete.inputs["Selection"])
    return delete.outputs["Geometry"], image_texture


def _tag(group, effect_id, definition):
    group.use_fake_user = True
    group["fbp_effect_id"] = effect_id
    group["fbp_effect_asset_id"] = str(definition.get("asset_id", "") or "")
    if str(definition.get("kind", "")) == "GEOMETRY":
        group["fbp_geometry_effect_id"] = str(definition.get("asset_id", "") or "")
    else:
        group["fbp_shader_effect_id"] = str(definition.get("asset_id", "") or "")
    group["fbp_builtin_effect"] = True
    group["fbp_builtin_effect_version"] = 8
    group["fbp_effect_schema_version"] = FBP_EFFECT_SCHEMA_VERSION
    return group


def _create_pixelate(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Vector", "INPUT", "NodeSocketVector", default=(0.0, 0.0, 0.0))
    _socket(group, "Pixels X", "INPUT", "NodeSocketFloat", default=64.0, minimum=1.0, maximum=8192.0)
    _socket(group, "Pixels Y", "INPUT", "NodeSocketFloat", default=36.0, minimum=1.0, maximum=8192.0)
    _socket(group, "Vector Out", "OUTPUT", "NodeSocketVector")
    inp, out = _group_io(group)

    separate = _node(group, "ShaderNodeSeparateXYZ", "Separate UV", -700, 20)

    x_mul = _math(group, "MULTIPLY", "X Cells", -500, 150)
    x_floor = _math(group, "FLOOR", "X Floor", -320, 150)
    x_half = _math(group, "ADD", "X Center", -140, 150, value_2=0.5)
    x_div = _math(group, "DIVIDE", "X Normalize", 40, 150)

    y_mul = _math(group, "MULTIPLY", "Y Cells", -500, -120)
    y_floor = _math(group, "FLOOR", "Y Floor", -320, -120)
    y_half = _math(group, "ADD", "Y Center", -140, -120, value_2=0.5)
    y_div = _math(group, "DIVIDE", "Y Normalize", 40, -120)

    combine = _node(group, "ShaderNodeCombineXYZ", "Pixelated UV", 290, 40)

    links = group.links
    links.new(inp.outputs["Vector"], separate.inputs[0])

    links.new(separate.outputs["X"], x_mul.inputs[0])
    links.new(inp.outputs["Pixels X"], x_mul.inputs[1])
    links.new(x_mul.outputs[0], x_floor.inputs[0])
    links.new(x_floor.outputs[0], x_half.inputs[0])
    links.new(x_half.outputs[0], x_div.inputs[0])
    links.new(inp.outputs["Pixels X"], x_div.inputs[1])

    links.new(separate.outputs["Y"], y_mul.inputs[0])
    links.new(inp.outputs["Pixels Y"], y_mul.inputs[1])
    links.new(y_mul.outputs[0], y_floor.inputs[0])
    links.new(y_floor.outputs[0], y_half.inputs[0])
    links.new(y_half.outputs[0], y_div.inputs[0])
    links.new(inp.outputs["Pixels Y"], y_div.inputs[1])

    links.new(x_div.outputs[0], combine.inputs["X"])
    links.new(y_div.outputs[0], combine.inputs["Y"])
    links.new(separate.outputs["Z"], combine.inputs["Z"])
    links.new(combine.outputs[0], out.inputs["Vector Out"])
    return group


def _create_depth_blur(name):
    """Nine-tap alpha-safe source blur with manual and camera-depth modes."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Image Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Manual Radius", "INPUT", "NodeSocketFloat", default=4.0, minimum=0.0, maximum=256.0)
    _socket(group, "Maximum Radius", "INPUT", "NodeSocketFloat", default=16.0, minimum=0.0, maximum=256.0)
    _socket(group, "Focus Distance", "INPUT", "NodeSocketFloat", default=10.0, minimum=0.0, maximum=1000000.0)
    _socket(group, "Focus Range", "INPUT", "NodeSocketFloat", default=0.25, minimum=0.0, maximum=1000000.0)
    _socket(group, "Falloff", "INPUT", "NodeSocketFloat", default=5.0, minimum=0.001, maximum=1000000.0)
    _socket(group, "Near Strength", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=2.0)
    _socket(group, "Far Strength", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=2.0)
    _socket(group, "Texel X", "INPUT", "NodeSocketFloat", default=0.001, minimum=0.0, maximum=1.0)
    _socket(group, "Texel Y", "INPUT", "NodeSocketFloat", default=0.001, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    camera = _node(group, "ShaderNodeCameraData", "Blur Camera Depth", -1500, 600)
    delta = _math(group, "SUBTRACT", "Depth Delta", -1300, 600)
    absolute = _math(group, "ABSOLUTE", "Absolute Depth Delta", -1120, 600)
    outside = _math(group, "SUBTRACT", "Outside Focus Range", -940, 600)
    outside_zero = _math(group, "MAXIMUM", "Clamp Focus Range", -760, 600, value_2=0.0)
    safe_falloff = _math(group, "MAXIMUM", "Safe Depth Falloff", -650, 690, value_2=0.001)
    normalized = _math(group, "DIVIDE", "Depth Falloff", -580, 600)
    normalized_clamp = _math(group, "MINIMUM", "Clamp Depth Blur", -400, 600, value_2=1.0)
    near_test = _math(group, "LESS_THAN", "Near Side", -940, 410)
    far_weight = _math(group, "SUBTRACT", "Far Side", -760, 410, value_1=1.0)
    near_amount = _math(group, "MULTIPLY", "Near Blur Strength", -580, 440)
    far_amount = _math(group, "MULTIPLY", "Far Blur Strength", -580, 330)
    side_strength = _math(group, "ADD", "Depth Side Strength", -400, 390)
    depth_radius = _math(group, "MULTIPLY", "Depth Blur Radius", -220, 560)
    depth_side = _math(group, "MULTIPLY", "Depth Radius Side", -40, 560)
    depth_limit = _math(group, "MINIMUM", "Limit Maximum Radius", 130, 500)
    manual_weight = _math(group, "SUBTRACT", "Manual Blur Weight", 130, 670, value_1=1.0)
    manual_part = _math(group, "MULTIPLY", "Manual Blur Radius", 310, 670)
    depth_part = _math(group, "MULTIPLY", "Depth Blur Selection", 310, 540)
    mode_mix = _math(group, "ADD", "Manual or Depth Radius", 500, 600)

    links.new(_output(camera, "View Z Depth", 1), delta.inputs[0])
    links.new(inp.outputs["Focus Distance"], delta.inputs[1])
    links.new(delta.outputs[0], absolute.inputs[0])
    links.new(absolute.outputs[0], outside.inputs[0])
    links.new(inp.outputs["Focus Range"], outside.inputs[1])
    links.new(outside.outputs[0], outside_zero.inputs[0])
    links.new(outside_zero.outputs[0], normalized.inputs[0])
    links.new(inp.outputs["Falloff"], safe_falloff.inputs[0])
    links.new(safe_falloff.outputs[0], normalized.inputs[1])
    links.new(normalized.outputs[0], normalized_clamp.inputs[0])
    links.new(_output(camera, "View Z Depth", 1), near_test.inputs[0])
    links.new(inp.outputs["Focus Distance"], near_test.inputs[1])
    links.new(near_test.outputs[0], far_weight.inputs[1])
    links.new(near_test.outputs[0], near_amount.inputs[0])
    links.new(inp.outputs["Near Strength"], near_amount.inputs[1])
    links.new(far_weight.outputs[0], far_amount.inputs[0])
    links.new(inp.outputs["Far Strength"], far_amount.inputs[1])
    links.new(near_amount.outputs[0], side_strength.inputs[0])
    links.new(far_amount.outputs[0], side_strength.inputs[1])
    links.new(normalized_clamp.outputs[0], depth_radius.inputs[0])
    links.new(inp.outputs["Maximum Radius"], depth_radius.inputs[1])
    links.new(depth_radius.outputs[0], depth_side.inputs[0])
    links.new(side_strength.outputs[0], depth_side.inputs[1])
    links.new(depth_side.outputs[0], depth_limit.inputs[0])
    links.new(inp.outputs["Maximum Radius"], depth_limit.inputs[1])
    links.new(inp.outputs["Mode"], manual_weight.inputs[1])
    links.new(inp.outputs["Manual Radius"], manual_part.inputs[0])
    links.new(manual_weight.outputs[0], manual_part.inputs[1])
    links.new(depth_limit.outputs[0], depth_part.inputs[0])
    links.new(inp.outputs["Mode"], depth_part.inputs[1])
    links.new(manual_part.outputs[0], mode_mix.inputs[0])
    links.new(depth_part.outputs[0], mode_mix.inputs[1])

    radius_x = _math(group, "MULTIPLY", "Blur Radius X", 680, 650)
    radius_y = _math(group, "MULTIPLY", "Blur Radius Y", 680, 500)
    links.new(mode_mix.outputs[0], radius_x.inputs[0])
    links.new(inp.outputs["Texel X"], radius_x.inputs[1])
    links.new(mode_mix.outputs[0], radius_y.inputs[0])
    links.new(inp.outputs["Texel Y"], radius_y.inputs[1])

    offsets = (
        (0.0, 0.0, 4.0, "Center"),
        (1.0, 0.0, 2.0, "Right"), (-1.0, 0.0, 2.0, "Left"),
        (0.0, 1.0, 2.0, "Top"), (0.0, -1.0, 2.0, "Bottom"),
        (0.70710678, 0.70710678, 1.0, "Top Right"),
        (-0.70710678, 0.70710678, 1.0, "Top Left"),
        (0.70710678, -0.70710678, 1.0, "Bottom Right"),
        (-0.70710678, -0.70710678, 1.0, "Bottom Left"),
    )
    color_terms = []
    alpha_terms = []
    base_x = 620
    for index, (ox, oy, weight, label) in enumerate(offsets):
        y = 520 - index * 170
        x_scale = _math(group, "MULTIPLY", f"{label} Offset X", base_x, y + 50, value_2=ox)
        y_scale = _math(group, "MULTIPLY", f"{label} Offset Y", base_x, y - 40, value_2=oy)
        offset = _node(group, "ShaderNodeCombineXYZ", f"{label} Offset", base_x + 180, y)
        uv = _vector_math(group, "ADD", f"{label} UV", base_x + 360, y)
        image = _node(group, "ShaderNodeTexImage", f"Depth Blur {label}", base_x + 560, y)
        image["fbp_matrix_source_image_node"] = True
        image["fbp_source_interpolation"] = "Linear"
        try:
            image.interpolation = "Linear"
            image.extension = "EXTEND"
        except (AttributeError, TypeError, ValueError):
            pass
        premultiply = _vector_math(group, "SCALE", f"{label} Premultiply", base_x + 800, y + 35)
        weighted_color = _vector_math(group, "SCALE", f"{label} Color Weight", base_x + 1000, y + 35)
        weighted_alpha = _math(group, "MULTIPLY", f"{label} Alpha Weight", base_x + 1000, y - 75, value_2=weight)
        links.new(radius_x.outputs[0], x_scale.inputs[0])
        links.new(radius_y.outputs[0], y_scale.inputs[0])
        links.new(x_scale.outputs[0], offset.inputs["X"])
        links.new(y_scale.outputs[0], offset.inputs["Y"])
        links.new(inp.outputs["UV Vector"], uv.inputs[0])
        links.new(offset.outputs[0], uv.inputs[1])
        links.new(uv.outputs[0], image.inputs["Vector"])
        links.new(image.outputs["Color"], premultiply.inputs[0])
        links.new(image.outputs["Alpha"], _input(premultiply, "Scale", 3))
        links.new(premultiply.outputs[0], weighted_color.inputs[0])
        _input(weighted_color, "Scale", 3).default_value = weight
        links.new(image.outputs["Alpha"], weighted_alpha.inputs[0])
        color_terms.append(weighted_color.outputs[0])
        alpha_terms.append(weighted_alpha.outputs[0])

    def add_chain(sockets, vector, prefix, x, y):
        current = sockets[0]
        for index, socket in enumerate(sockets[1:], 1):
            node = _vector_math(group, "ADD", f"{prefix} {index}", x + index * 150, y) if vector else _math(group, "ADD", f"{prefix} {index}", x + index * 150, y)
            links.new(current, node.inputs[0])
            links.new(socket, node.inputs[1])
            current = node.outputs[0]
        return current

    color_sum = add_chain(color_terms, True, "Blur Color Sum", 2250, 350)
    alpha_sum = add_chain(alpha_terms, False, "Blur Alpha Sum", 2250, -120)
    color_avg = _vector_math(group, "SCALE", "Blur Color Average", 3700, 350)
    _input(color_avg, "Scale", 3).default_value = 1.0 / 16.0
    alpha_avg = _math(group, "MULTIPLY", "Blur Alpha Average", 3700, -120, value_2=1.0 / 16.0)
    safe_alpha = _math(group, "MAXIMUM", "Safe Blur Alpha", 3890, -120, value_2=0.0001)
    reciprocal = _math(group, "DIVIDE", "Unpremultiply Factor", 4070, -120, value_1=1.0)
    unpremultiply = _vector_math(group, "SCALE", "Unpremultiplied Blur", 4250, 350)
    valid_alpha = _math(group, "GREATER_THAN", "Valid Blur Alpha", 4250, 180, value_2=0.0005)
    guarded_color = _mix_rgb(group, "MIX", "Guard Transparent Blur Color", 4430, 430)
    radius_enabled = _math(group, "GREATER_THAN", "Blur Radius Enabled", 4070, 40, value_2=0.0001)
    image_blur_weight = _math(group, "MULTIPLY", "Blur Image Weight", 4250, 40)
    fallback_weight = _math(group, "SUBTRACT", "Blur Fallback Weight", 4250, -120, value_1=1.0)
    color_mix = _mix_rgb(group, "MIX", "Blur Source Mix", 4680, 300)
    image_alpha = _math(group, "MULTIPLY", "Blur Image Alpha", 4680, -60)
    fallback_alpha = _math(group, "MULTIPLY", "Blur Fallback Alpha", 4680, -190)
    alpha_out = _math(group, "ADD", "Blur Final Alpha", 4870, -120)

    links.new(color_sum, color_avg.inputs[0])
    links.new(alpha_sum, alpha_avg.inputs[0])
    links.new(alpha_avg.outputs[0], safe_alpha.inputs[0])
    links.new(safe_alpha.outputs[0], reciprocal.inputs[1])
    links.new(color_avg.outputs[0], unpremultiply.inputs[0])
    links.new(reciprocal.outputs[0], _input(unpremultiply, "Scale", 3))
    links.new(alpha_avg.outputs[0], valid_alpha.inputs[0])
    links.new(valid_alpha.outputs[0], guarded_color.inputs[0])
    links.new(inp.outputs["Color In"], guarded_color.inputs[1])
    links.new(unpremultiply.outputs[0], guarded_color.inputs[2])
    links.new(mode_mix.outputs[0], radius_enabled.inputs[0])
    links.new(inp.outputs["Use Image Sample"], image_blur_weight.inputs[0])
    links.new(radius_enabled.outputs[0], image_blur_weight.inputs[1])
    links.new(image_blur_weight.outputs[0], fallback_weight.inputs[1])
    links.new(image_blur_weight.outputs[0], color_mix.inputs[0])
    links.new(inp.outputs["Color In"], color_mix.inputs[1])
    links.new(guarded_color.outputs[0], color_mix.inputs[2])
    links.new(alpha_avg.outputs[0], image_alpha.inputs[0])
    links.new(image_blur_weight.outputs[0], image_alpha.inputs[1])
    links.new(inp.outputs["Alpha In"], fallback_alpha.inputs[0])
    links.new(fallback_weight.outputs[0], fallback_alpha.inputs[1])
    links.new(image_alpha.outputs[0], alpha_out.inputs[0])
    links.new(fallback_alpha.outputs[0], alpha_out.inputs[1])
    links.new(color_mix.outputs[0], out.inputs["Color Out"])
    links.new(alpha_out.outputs[0], out.inputs["Alpha Out"])
    group["fbp_depth_blur_contract_version"] = 2
    return group



def _create_track_matte(name, *, luma=False):
    """Create an alpha-only track matte sampled from another FBP source image."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Mask Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Use Source Transform", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Source Min X", "INPUT", "NodeSocketFloat", default=-1.0)
    _socket(group, "Source Max X", "INPUT", "NodeSocketFloat", default=1.0)
    _socket(group, "Source Min Y", "INPUT", "NodeSocketFloat", default=-1.0)
    _socket(group, "Source Max Y", "INPUT", "NodeSocketFloat", default=1.0)
    _socket(group, "UV Offset X", "INPUT", "NodeSocketFloat", default=0.0)
    _socket(group, "UV Offset Y", "INPUT", "NodeSocketFloat", default=0.0)
    _socket(group, "UV Scale X", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.001, maximum=1000.0)
    _socket(group, "UV Scale Y", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.001, maximum=1000.0)
    _socket(group, "UV Rotation", "INPUT", "NodeSocketFloat", default=0.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Preview", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    if luma:
        _socket(group, "Threshold", "INPUT", "NodeSocketFloat", default=0.5, minimum=0.0, maximum=1.0)
        _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=0.15, minimum=0.0, maximum=1.0)
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    _socket(group, "Mask Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    source_coords = _node(group, "ShaderNodeTexCoord", "Matte Source Coordinates", -1500, 480)
    source_coords["fbp_mask_source_coord_node"] = True
    separate = _node(group, "ShaderNodeSeparateXYZ", "Separate Source Coordinates", -1280, 480)
    map_x = _node(group, "ShaderNodeMapRange", "Map Source X", -1040, 520)
    map_y = _node(group, "ShaderNodeMapRange", "Map Source Y", -1040, 280)
    for mapper in (map_x, map_y):
        mapper.interpolation_type = "LINEAR"
        mapper.clamp = False
        mapper.inputs["To Min"].default_value = 0.0
        mapper.inputs["To Max"].default_value = 1.0
    combine = _node(group, "ShaderNodeCombineXYZ", "Source Transform UV", -780, 430)
    uv_mix = _mix_rgb(group, "MIX", "Matte Coordinate Mode", -540, 300)
    try:
        uv_mix.use_clamp = False
    except AttributeError:
        pass

    image = _node(group, "ShaderNodeTexImage", "Matte Source Image", -300, 180)
    image["fbp_mask_source_image_node"] = True
    try:
        image.interpolation = "Linear"
        image.extension = "CLIP"
    except (AttributeError, TypeError, ValueError):
        pass

    links.new(source_coords.outputs["Object"], separate.inputs[0])
    links.new(separate.outputs["X"], map_x.inputs["Value"])
    links.new(inp.outputs["Source Min X"], map_x.inputs["From Min"])
    links.new(inp.outputs["Source Max X"], map_x.inputs["From Max"])
    links.new(separate.outputs["Y"], map_y.inputs["Value"])
    links.new(inp.outputs["Source Min Y"], map_y.inputs["From Min"])
    links.new(inp.outputs["Source Max Y"], map_y.inputs["From Max"])
    links.new(map_x.outputs["Result"], combine.inputs["X"])
    links.new(map_y.outputs["Result"], combine.inputs["Y"])
    links.new(inp.outputs["Use Source Transform"], uv_mix.inputs[0])
    links.new(inp.outputs["UV Vector"], uv_mix.inputs[1])
    links.new(combine.outputs[0], uv_mix.inputs[2])

    uv_sep = _node(group, "ShaderNodeSeparateXYZ", "Separate Matte UV", -340, 500)
    center_x = _math(group, "SUBTRACT", "Center Matte X", -140, 560, value_2=0.5)
    center_y = _math(group, "SUBTRACT", "Center Matte Y", -140, 440, value_2=0.5)
    safe_scale_x = _math(group, "MAXIMUM", "Safe Matte Scale X", -340, 700, value_2=0.001)
    safe_scale_y = _math(group, "MAXIMUM", "Safe Matte Scale Y", -340, 620, value_2=0.001)
    scaled_x = _math(group, "DIVIDE", "Scale Matte X", 40, 560)
    scaled_y = _math(group, "DIVIDE", "Scale Matte Y", 40, 440)
    cosine = _math(group, "COSINE", "Matte Rotation Cos", 40, 760)
    sine = _math(group, "SINE", "Matte Rotation Sin", 40, 680)
    x_cos = _math(group, "MULTIPLY", "Matte X Cos", 220, 600)
    y_sin = _math(group, "MULTIPLY", "Matte Y Sin", 220, 520)
    rot_x = _math(group, "SUBTRACT", "Rotated Matte X", 400, 570)
    x_sin = _math(group, "MULTIPLY", "Matte X Sin", 220, 420)
    y_cos = _math(group, "MULTIPLY", "Matte Y Cos", 220, 340)
    rot_y = _math(group, "ADD", "Rotated Matte Y", 400, 390)
    uncenter_x = _math(group, "ADD", "Uncenter Matte X", 580, 570, value_2=0.5)
    uncenter_y = _math(group, "ADD", "Uncenter Matte Y", 580, 390, value_2=0.5)
    offset_x = _math(group, "SUBTRACT", "Offset Matte X", 760, 570)
    offset_y = _math(group, "SUBTRACT", "Offset Matte Y", 760, 390)
    uv_final = _node(group, "ShaderNodeCombineXYZ", "Transformed Matte UV", 940, 500)

    links.new(uv_mix.outputs[0], uv_sep.inputs[0])
    links.new(uv_sep.outputs["X"], center_x.inputs[0])
    links.new(uv_sep.outputs["Y"], center_y.inputs[0])
    links.new(inp.outputs["UV Scale X"], safe_scale_x.inputs[0])
    links.new(inp.outputs["UV Scale Y"], safe_scale_y.inputs[0])
    links.new(center_x.outputs[0], scaled_x.inputs[0])
    links.new(safe_scale_x.outputs[0], scaled_x.inputs[1])
    links.new(center_y.outputs[0], scaled_y.inputs[0])
    links.new(safe_scale_y.outputs[0], scaled_y.inputs[1])
    links.new(inp.outputs["UV Rotation"], cosine.inputs[0])
    links.new(inp.outputs["UV Rotation"], sine.inputs[0])
    links.new(scaled_x.outputs[0], x_cos.inputs[0])
    links.new(cosine.outputs[0], x_cos.inputs[1])
    links.new(scaled_y.outputs[0], y_sin.inputs[0])
    links.new(sine.outputs[0], y_sin.inputs[1])
    links.new(x_cos.outputs[0], rot_x.inputs[0])
    links.new(y_sin.outputs[0], rot_x.inputs[1])
    links.new(scaled_x.outputs[0], x_sin.inputs[0])
    links.new(sine.outputs[0], x_sin.inputs[1])
    links.new(scaled_y.outputs[0], y_cos.inputs[0])
    links.new(cosine.outputs[0], y_cos.inputs[1])
    links.new(x_sin.outputs[0], rot_y.inputs[0])
    links.new(y_cos.outputs[0], rot_y.inputs[1])
    links.new(rot_x.outputs[0], uncenter_x.inputs[0])
    links.new(rot_y.outputs[0], uncenter_y.inputs[0])
    links.new(uncenter_x.outputs[0], offset_x.inputs[0])
    links.new(inp.outputs["UV Offset X"], offset_x.inputs[1])
    links.new(uncenter_y.outputs[0], offset_y.inputs[0])
    links.new(inp.outputs["UV Offset Y"], offset_y.inputs[1])
    links.new(offset_x.outputs[0], uv_final.inputs["X"])
    links.new(offset_y.outputs[0], uv_final.inputs["Y"])
    links.new(uv_final.outputs[0], image.inputs["Vector"])

    if luma:
        bw = _node(group, "ShaderNodeRGBToBW", "Matte Luminance", -760, 260)
        luma_alpha = _math(group, "MULTIPLY", "Luminance Alpha", -580, 210)
        low = _math(group, "SUBTRACT", "Luma Lower Bound", -580, 20)
        safe_softness = _math(group, "MAXIMUM", "Safe Luma Softness", -760, -100, value_2=0.0001)
        high = _math(group, "ADD", "Luma Upper Bound", -400, 20)
        ramp = _node(group, "ShaderNodeMapRange", "Luma Matte Transition", -190, 170)
        ramp.interpolation_type = "SMOOTHERSTEP"
        ramp.clamp = True
        ramp.inputs["To Min"].default_value = 0.0
        ramp.inputs["To Max"].default_value = 1.0
        links.new(image.outputs["Color"], bw.inputs[0])
        links.new(bw.outputs[0], luma_alpha.inputs[0])
        links.new(image.outputs["Alpha"], luma_alpha.inputs[1])
        links.new(inp.outputs["Softness"], safe_softness.inputs[0])
        links.new(inp.outputs["Threshold"], low.inputs[0])
        links.new(safe_softness.outputs[0], low.inputs[1])
        links.new(inp.outputs["Threshold"], high.inputs[0])
        links.new(safe_softness.outputs[0], high.inputs[1])
        links.new(luma_alpha.outputs[0], ramp.inputs["Value"])
        links.new(low.outputs[0], ramp.inputs["From Min"])
        links.new(high.outputs[0], ramp.inputs["From Max"])
        raw_source = luma_alpha.outputs[0]
        matte = ramp.outputs["Result"]
    else:
        raw_source = image.outputs["Alpha"]
        matte = raw_source

    inverse = _math(group, "SUBTRACT", "Inverted Matte", 30, 40, value_1=1.0)
    normal_weight = _math(group, "SUBTRACT", "Normal Matte Weight", 30, 190, value_1=1.0)
    normal_part = _math(group, "MULTIPLY", "Normal Matte", 210, 190)
    inverse_part = _math(group, "MULTIPLY", "Inverse Matte", 210, 40)
    selected = _math(group, "ADD", "Selected Matte", 390, 120)
    sampled = _math(group, "MULTIPLY", "Sampled Matte", 570, 120)
    missing = _math(group, "SUBTRACT", "Missing Source Pass Through", 570, -30, value_1=1.0)
    available = _math(group, "ADD", "Available Matte", 750, 70)
    factor_part = _math(group, "MULTIPLY", "Matte Factor", 930, 100)
    original_part = _math(group, "SUBTRACT", "Original Alpha Weight", 930, -50, value_1=1.0)
    effective = _math(group, "ADD", "Effective Matte", 1110, 40)
    result = _math(group, "MULTIPLY", "Track Matte Alpha", 1290, 40)

    links.new(matte, inverse.inputs[1])
    links.new(inp.outputs["Invert"], normal_weight.inputs[1])
    links.new(matte, normal_part.inputs[0])
    links.new(normal_weight.outputs[0], normal_part.inputs[1])
    links.new(inverse.outputs[0], inverse_part.inputs[0])
    links.new(inp.outputs["Invert"], inverse_part.inputs[1])
    links.new(normal_part.outputs[0], selected.inputs[0])
    links.new(inverse_part.outputs[0], selected.inputs[1])
    links.new(selected.outputs[0], sampled.inputs[0])
    links.new(inp.outputs["Use Mask Sample"], sampled.inputs[1])
    links.new(inp.outputs["Use Mask Sample"], missing.inputs[1])
    links.new(sampled.outputs[0], available.inputs[0])
    links.new(missing.outputs[0], available.inputs[1])
    links.new(available.outputs[0], factor_part.inputs[0])
    links.new(inp.outputs["Factor"], factor_part.inputs[1])
    links.new(inp.outputs["Factor"], original_part.inputs[1])
    links.new(factor_part.outputs[0], effective.inputs[0])
    links.new(original_part.outputs[0], effective.inputs[1])
    links.new(inp.outputs["Alpha In"], result.inputs[0])
    links.new(effective.outputs[0], result.inputs[1])

    # Diagnostic alpha previews. FINAL preserves the normal result, MATTE
    # exposes the effective post-invert/post-factor mask, and SOURCE shows the
    # unprocessed sampled alpha/luminance. Missing sources remain black in the
    # SOURCE preview instead of leaking the Image Texture fallback value.
    source_available = _math(group, "MULTIPLY", "Available Source Preview", 1110, -150)
    debug_matte = _math(group, "GREATER_THAN", "Preview Matte Mode", 1290, -160, value_2=0.5)
    debug_source = _math(group, "GREATER_THAN", "Preview Source Mode", 1290, -250, value_2=1.5)
    final_weight = _math(group, "SUBTRACT", "Final Preview Weight", 1470, 40, value_1=1.0)
    final_part = _math(group, "MULTIPLY", "Final Preview", 1650, 80)
    matte_part = _math(group, "MULTIPLY", "Matte Preview", 1650, -20)
    final_or_matte = _math(group, "ADD", "Final or Matte Preview", 1830, 30)
    source_weight = _math(group, "SUBTRACT", "Non Source Preview Weight", 1830, -120, value_1=1.0)
    normal_preview = _math(group, "MULTIPLY", "Normal Preview Output", 2010, 30)
    source_preview = _math(group, "MULTIPLY", "Source Preview Output", 2010, -100)
    preview_output = _math(group, "ADD", "Track Matte Preview Output", 2190, 0)

    links.new(raw_source, source_available.inputs[0])
    links.new(inp.outputs["Use Mask Sample"], source_available.inputs[1])
    links.new(inp.outputs["Debug Preview"], debug_matte.inputs[0])
    links.new(inp.outputs["Debug Preview"], debug_source.inputs[0])
    links.new(debug_matte.outputs[0], final_weight.inputs[1])
    links.new(result.outputs[0], final_part.inputs[0])
    links.new(final_weight.outputs[0], final_part.inputs[1])
    links.new(effective.outputs[0], matte_part.inputs[0])
    links.new(debug_matte.outputs[0], matte_part.inputs[1])
    links.new(final_part.outputs[0], final_or_matte.inputs[0])
    links.new(matte_part.outputs[0], final_or_matte.inputs[1])
    links.new(debug_source.outputs[0], source_weight.inputs[1])
    links.new(final_or_matte.outputs[0], normal_preview.inputs[0])
    links.new(source_weight.outputs[0], normal_preview.inputs[1])
    links.new(source_available.outputs[0], source_preview.inputs[0])
    links.new(debug_source.outputs[0], source_preview.inputs[1])
    links.new(normal_preview.outputs[0], preview_output.inputs[0])
    links.new(source_preview.outputs[0], preview_output.inputs[1])
    links.new(preview_output.outputs[0], out.inputs["Alpha Out"])
    links.new(effective.outputs[0], out.inputs["Mask Out"])
    group["fbp_track_matte_contract_version"] = 5
    return group


def _create_alpha_matte(name):
    return _create_track_matte(name, luma=False)


def _create_luma_matte(name):
    return _create_track_matte(name, luma=True)


def _create_object_shape_mask(name, *, shape="SQUARE"):
    """Create an editable mesh-driven Shape Mask sampled in helper local space."""
    shape = str(shape or "SQUARE").upper()
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Use Mask Object", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Shape Min X", "INPUT", "NodeSocketFloat", default=-1.1)
    _socket(group, "Shape Max X", "INPUT", "NodeSocketFloat", default=1.1)
    _socket(group, "Shape Min Y", "INPUT", "NodeSocketFloat", default=-1.1)
    _socket(group, "Shape Max Y", "INPUT", "NodeSocketFloat", default=1.1)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Feather", "INPUT", "NodeSocketFloat", default=0.05, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Preview", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    _socket(group, "Mask Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    coords = _node(group, "ShaderNodeTexCoord", "Shape Mask Coordinates", -1280, 260)
    coords["fbp_object_mask_coord_node"] = True
    separate = _node(group, "ShaderNodeSeparateXYZ", "Shape Mask XY", -1060, 260)
    map_x = _node(group, "ShaderNodeMapRange", "Shape Mask X to UV", -840, 360)
    map_y = _node(group, "ShaderNodeMapRange", "Shape Mask Y to UV", -840, 120)
    for mapper in (map_x, map_y):
        mapper.interpolation_type = "LINEAR"
        mapper.clamp = False
        mapper.inputs["To Min"].default_value = 0.0
        mapper.inputs["To Max"].default_value = 1.0
    combine = _node(group, "ShaderNodeCombineXYZ", "Shape Mask UV", -580, 260)
    image = _node(group, "ShaderNodeTexImage", "Editable Shape Mask SDF", -350, 260)
    image["fbp_object_mask_image_node"] = True
    try:
        image.interpolation = "Linear"
        image.extension = "CLIP"
    except (AttributeError, TypeError, ValueError):
        pass

    links.new(coords.outputs["Object"], separate.inputs[0])
    links.new(separate.outputs["X"], map_x.inputs["Value"])
    links.new(inp.outputs["Shape Min X"], map_x.inputs["From Min"])
    links.new(inp.outputs["Shape Max X"], map_x.inputs["From Max"])
    links.new(separate.outputs["Y"], map_y.inputs["Value"])
    links.new(inp.outputs["Shape Min Y"], map_y.inputs["From Min"])
    links.new(inp.outputs["Shape Max Y"], map_y.inputs["From Max"])
    links.new(map_x.outputs["Result"], combine.inputs["X"])
    links.new(map_y.outputs["Result"], combine.inputs["Y"])
    links.new(combine.outputs[0], image.inputs["Vector"])

    safe_feather = _math(group, "MAXIMUM", "Safe Shape Mask Feather", -100, 460, value_2=0.001)
    lower = _math(group, "SUBTRACT", "Shape Mask Inner SDF", 80, 420, value_1=0.5)
    upper = _math(group, "ADD", "Shape Mask Outer SDF", 80, 300, value_1=0.5)
    ramp = _node(group, "ShaderNodeMapRange", "Editable Shape Mask Feather", 300, 260)
    ramp.interpolation_type = "SMOOTHERSTEP"
    ramp.clamp = True
    ramp.inputs["To Min"].default_value = 0.0
    ramp.inputs["To Max"].default_value = 1.0
    links.new(inp.outputs["Feather"], safe_feather.inputs[0])
    links.new(safe_feather.outputs[0], lower.inputs[1])
    links.new(safe_feather.outputs[0], upper.inputs[1])
    links.new(image.outputs["Alpha"], ramp.inputs["Value"])
    links.new(lower.outputs[0], ramp.inputs["From Min"])
    links.new(upper.outputs[0], ramp.inputs["From Max"])

    inverse = _math(group, "SUBTRACT", "Inverted Shape Mask", 520, 40, value_1=1.0)
    normal_weight = _math(group, "SUBTRACT", "Normal Shape Mask Weight", 520, 250, value_1=1.0)
    normal = _math(group, "MULTIPLY", "Normal Shape Mask", 700, 250)
    inverted = _math(group, "MULTIPLY", "Inverse Shape Mask", 700, 40)
    selected = _math(group, "ADD", "Selected Shape Mask", 880, 150)
    sampled = _math(group, "MULTIPLY", "Sampled Shape Mask", 1060, 150)
    missing = _math(group, "SUBTRACT", "Missing Shape Mask Pass Through", 1060, 0, value_1=1.0)
    available = _math(group, "ADD", "Available Shape Mask", 1240, 100)
    factor_part = _math(group, "MULTIPLY", "Shape Mask Factor", 1420, 150)
    original_part = _math(group, "SUBTRACT", "Original Shape Mask Weight", 1420, 0, value_1=1.0)
    effective = _math(group, "ADD", "Effective Shape Mask", 1600, 80)
    result = _math(group, "MULTIPLY", "Shape Mask Alpha", 1780, 80)

    links.new(ramp.outputs["Result"], inverse.inputs[1])
    links.new(inp.outputs["Invert"], normal_weight.inputs[1])
    links.new(ramp.outputs["Result"], normal.inputs[0])
    links.new(normal_weight.outputs[0], normal.inputs[1])
    links.new(inverse.outputs[0], inverted.inputs[0])
    links.new(inp.outputs["Invert"], inverted.inputs[1])
    links.new(normal.outputs[0], selected.inputs[0])
    links.new(inverted.outputs[0], selected.inputs[1])
    links.new(selected.outputs[0], sampled.inputs[0])
    links.new(inp.outputs["Use Mask Object"], sampled.inputs[1])
    links.new(inp.outputs["Use Mask Object"], missing.inputs[1])
    links.new(sampled.outputs[0], available.inputs[0])
    links.new(missing.outputs[0], available.inputs[1])
    links.new(available.outputs[0], factor_part.inputs[0])
    links.new(inp.outputs["Factor"], factor_part.inputs[1])
    links.new(inp.outputs["Factor"], original_part.inputs[1])
    links.new(factor_part.outputs[0], effective.inputs[0])
    links.new(original_part.outputs[0], effective.inputs[1])
    links.new(inp.outputs["Alpha In"], result.inputs[0])
    links.new(effective.outputs[0], result.inputs[1])

    debug = _mix_rgb(group, "MIX", "Shape Mask Debug Preview", 1960, 80)
    links.new(inp.outputs["Debug Preview"], debug.inputs[0])
    links.new(result.outputs[0], debug.inputs[1])
    links.new(effective.outputs[0], debug.inputs[2])
    links.new(debug.outputs[0], out.inputs["Alpha Out"])
    links.new(effective.outputs[0], out.inputs["Mask Out"])
    group["fbp_object_mask_contract_version"] = 3
    group["fbp_object_mask_shape"] = shape
    return group


def _finish_generated_mask(group, inp, out, raw_mask, *, prefix, x=780, y=160, availability=None):
    """Finish a scalar 0..1 mask with invert, factor, alpha and debug output."""
    links = group.links
    inverse = _math(group, "SUBTRACT", f"{prefix} Inverted", x, y - 130, value_1=1.0)
    normal_weight = _math(group, "SUBTRACT", f"{prefix} Normal Weight", x, y + 110, value_1=1.0)
    normal = _math(group, "MULTIPLY", f"{prefix} Normal", x + 180, y + 110)
    inverted = _math(group, "MULTIPLY", f"{prefix} Inverse", x + 180, y - 130)
    selected = _math(group, "ADD", f"{prefix} Selected", x + 360, y)
    links.new(raw_mask, inverse.inputs[1])
    links.new(inp.outputs["Invert"], normal_weight.inputs[1])
    links.new(raw_mask, normal.inputs[0])
    links.new(normal_weight.outputs[0], normal.inputs[1])
    links.new(inverse.outputs[0], inverted.inputs[0])
    links.new(inp.outputs["Invert"], inverted.inputs[1])
    links.new(normal.outputs[0], selected.inputs[0])
    links.new(inverted.outputs[0], selected.inputs[1])

    available_mask = selected.outputs[0]
    if availability is not None:
        sampled = _math(group, "MULTIPLY", f"{prefix} Available Sample", x + 540, y + 70)
        missing = _math(group, "SUBTRACT", f"{prefix} Missing Pass Through", x + 540, y - 80, value_1=1.0)
        available = _math(group, "ADD", f"{prefix} Availability", x + 720, y)
        links.new(selected.outputs[0], sampled.inputs[0])
        links.new(availability, sampled.inputs[1])
        links.new(availability, missing.inputs[1])
        links.new(sampled.outputs[0], available.inputs[0])
        links.new(missing.outputs[0], available.inputs[1])
        available_mask = available.outputs[0]
        factor_x = x + 900
    else:
        factor_x = x + 540

    factor_part = _math(group, "MULTIPLY", f"{prefix} Factor", factor_x, y + 70)
    original_part = _math(group, "SUBTRACT", f"{prefix} Original Weight", factor_x, y - 80, value_1=1.0)
    effective = _math(group, "ADD", f"{prefix} Effective", factor_x + 180, y)
    result = _math(group, "MULTIPLY", f"{prefix} Alpha", factor_x + 360, y)
    links.new(available_mask, factor_part.inputs[0])
    links.new(inp.outputs["Factor"], factor_part.inputs[1])
    links.new(inp.outputs["Factor"], original_part.inputs[1])
    links.new(factor_part.outputs[0], effective.inputs[0])
    links.new(original_part.outputs[0], effective.inputs[1])
    links.new(inp.outputs["Alpha In"], result.inputs[0])
    links.new(effective.outputs[0], result.inputs[1])

    debug = _mix_rgb(group, "MIX", f"{prefix} Debug Preview", factor_x + 540, y)
    links.new(inp.outputs["Debug Preview"], debug.inputs[0])
    links.new(result.outputs[0], debug.inputs[1])
    links.new(effective.outputs[0], debug.inputs[2])
    links.new(debug.outputs[0], out.inputs["Alpha Out"])
    links.new(effective.outputs[0], out.inputs["Mask Out"])
    return group


def _create_color_mask(name):
    """Create an image-sampled color-range mask for stills and sequences."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Image Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Target Color", "INPUT", "NodeSocketColor", default=(0.0, 1.0, 0.0, 1.0))
    _socket(group, "Tolerance", "INPUT", "NodeSocketFloat", default=0.12, minimum=0.0, maximum=1.732)
    _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=0.08, minimum=0.0, maximum=1.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Preview", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    _socket(group, "Mask Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    image = _node(group, "ShaderNodeTexImage", "Color Mask Source", -760, 170)
    image["fbp_matrix_source_image_node"] = True
    image["fbp_source_interpolation"] = "Linear"
    try:
        image.interpolation = "Linear"
        image.extension = "EXTEND"
    except (AttributeError, TypeError, ValueError):
        pass
    distance = _vector_math(group, "DISTANCE", "Color Distance", -500, 160)
    safe_softness = _math(group, "MAXIMUM", "Safe Color Softness", -500, -80, value_2=0.00001)
    upper = _math(group, "ADD", "Color Mask Outer Range", -280, -40)
    ramp = _node(group, "ShaderNodeMapRange", "Color Range Mask", -40, 150)
    ramp.interpolation_type = "SMOOTHERSTEP"
    ramp.clamp = True
    ramp.inputs["To Min"].default_value = 1.0
    ramp.inputs["To Max"].default_value = 0.0

    links.new(inp.outputs["UV Vector"], image.inputs["Vector"])
    links.new(image.outputs["Color"], distance.inputs[0])
    links.new(inp.outputs["Target Color"], distance.inputs[1])
    links.new(inp.outputs["Softness"], safe_softness.inputs[0])
    links.new(inp.outputs["Tolerance"], upper.inputs[0])
    links.new(safe_softness.outputs[0], upper.inputs[1])
    links.new(distance.outputs["Value"], ramp.inputs["Value"])
    links.new(inp.outputs["Tolerance"], ramp.inputs["From Min"])
    links.new(upper.outputs[0], ramp.inputs["From Max"])

    # Transparent PNG pixels often store black RGB. Without this alpha gate a
    # black Color Mask selects the entire transparent rectangle around artwork.
    # Keep the generated mask constrained to visible source pixels.
    source_alpha = _math(group, "MULTIPLY", "Color Mask Source Alpha", 150, -170)
    links.new(ramp.outputs["Result"], source_alpha.inputs[0])
    links.new(image.outputs["Alpha"], source_alpha.inputs[1])
    group["fbp_generated_mask_contract_version"] = 2
    return _finish_generated_mask(
        group, inp, out, source_alpha.outputs[0], prefix="Color Mask",
        x=330, y=130, availability=inp.outputs["Use Image Sample"],
    )


def _create_gradient_mask(name):
    """Create a linear/radial UV-space mask."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Type", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Center X", "INPUT", "NodeSocketFloat", default=0.5, minimum=-10.0, maximum=10.0)
    _socket(group, "Center Y", "INPUT", "NodeSocketFloat", default=0.5, minimum=-10.0, maximum=10.0)
    _socket(group, "Scale", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.001, maximum=1000.0)
    _socket(group, "Angle", "INPUT", "NodeSocketFloat", default=0.0, minimum=-6.283185, maximum=6.283185)
    _socket(group, "Position", "INPUT", "NodeSocketFloat", default=0.5, minimum=-2.0, maximum=2.0)
    _socket(group, "Feather", "INPUT", "NodeSocketFloat", default=0.2, minimum=0.0, maximum=2.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Preview", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    _socket(group, "Mask Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    center = _node(group, "ShaderNodeCombineXYZ", "Gradient Center", -820, 0)
    centered = _vector_math(group, "SUBTRACT", "Centered Gradient UV", -620, 150)
    scaled = _vector_math(group, "SCALE", "Scaled Gradient UV", -420, 150)
    rotate = _node(group, "ShaderNodeVectorRotate", "Rotate Gradient", -220, 150)
    rotate.rotation_type = "Z_AXIS"
    rotate.invert = False
    rotate.inputs["Center"].default_value = (0.0, 0.0, 0.0)
    separate = _node(group, "ShaderNodeSeparateXYZ", "Gradient Axis", 0, 220)
    linear = _math(group, "ADD", "Linear Gradient Coordinate", 190, 260, value_2=0.5)
    radial_distance = _vector_math(group, "LENGTH", "Radial Gradient Distance", 0, -80)
    radial_scaled = _math(group, "MULTIPLY", "Normalized Radial Distance", 190, -80, value_2=2.0)
    radial = _math(group, "SUBTRACT", "Radial Gradient Coordinate", 370, -80, value_1=1.0)
    linear_weight = _math(group, "SUBTRACT", "Linear Gradient Weight", 370, 260, value_1=1.0)
    linear_part = _math(group, "MULTIPLY", "Linear Gradient", 550, 260)
    radial_part = _math(group, "MULTIPLY", "Radial Gradient", 550, -80)
    selected = _math(group, "ADD", "Selected Gradient", 730, 100)
    half_feather = _math(group, "MULTIPLY", "Half Gradient Feather", 550, -250, value_2=0.5)
    lower = _math(group, "SUBTRACT", "Gradient Lower", 730, -240)
    upper = _math(group, "ADD", "Gradient Upper", 730, -360)
    epsilon_upper = _math(group, "ADD", "Gradient Minimum Width", 910, -430, value_2=0.00001)
    safe_upper = _math(group, "MAXIMUM", "Safe Gradient Upper", 1090, -360)
    ramp = _node(group, "ShaderNodeMapRange", "Gradient Mask", 950, 100)
    ramp.interpolation_type = "SMOOTHERSTEP"
    ramp.clamp = True
    ramp.inputs["To Min"].default_value = 0.0
    ramp.inputs["To Max"].default_value = 1.0

    links.new(inp.outputs["Center X"], center.inputs["X"])
    links.new(inp.outputs["Center Y"], center.inputs["Y"])
    links.new(inp.outputs["UV Vector"], centered.inputs[0])
    links.new(center.outputs[0], centered.inputs[1])
    links.new(centered.outputs[0], scaled.inputs[0])
    links.new(inp.outputs["Scale"], _input(scaled, "Scale", 3))
    links.new(scaled.outputs[0], rotate.inputs["Vector"])
    links.new(inp.outputs["Angle"], rotate.inputs["Angle"])
    links.new(rotate.outputs["Vector"], separate.inputs[0])
    links.new(separate.outputs["X"], linear.inputs[0])
    links.new(rotate.outputs["Vector"], radial_distance.inputs[0])
    links.new(radial_distance.outputs["Value"], radial_scaled.inputs[0])
    links.new(radial_scaled.outputs[0], radial.inputs[1])
    links.new(inp.outputs["Type"], linear_weight.inputs[1])
    links.new(linear.outputs[0], linear_part.inputs[0])
    links.new(linear_weight.outputs[0], linear_part.inputs[1])
    links.new(radial.outputs[0], radial_part.inputs[0])
    links.new(inp.outputs["Type"], radial_part.inputs[1])
    links.new(linear_part.outputs[0], selected.inputs[0])
    links.new(radial_part.outputs[0], selected.inputs[1])
    links.new(inp.outputs["Feather"], half_feather.inputs[0])
    links.new(inp.outputs["Position"], lower.inputs[0])
    links.new(half_feather.outputs[0], lower.inputs[1])
    links.new(inp.outputs["Position"], upper.inputs[0])
    links.new(half_feather.outputs[0], upper.inputs[1])
    links.new(lower.outputs[0], epsilon_upper.inputs[0])
    links.new(upper.outputs[0], safe_upper.inputs[0])
    links.new(epsilon_upper.outputs[0], safe_upper.inputs[1])
    links.new(selected.outputs[0], ramp.inputs["Value"])
    links.new(lower.outputs[0], ramp.inputs["From Min"])
    links.new(safe_upper.outputs[0], ramp.inputs["From Max"])
    group["fbp_generated_mask_contract_version"] = 1
    return _finish_generated_mask(group, inp, out, ramp.outputs["Result"], prefix="Gradient Mask", x=1160, y=110)


def _create_noise_mask(name):
    """Create an animatable UV-space procedural noise mask."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Scale", "INPUT", "NodeSocketFloat", default=6.0, minimum=0.001, maximum=1000.0)
    _socket(group, "Detail", "INPUT", "NodeSocketFloat", default=3.0, minimum=0.0, maximum=15.0)
    _socket(group, "Roughness", "INPUT", "NodeSocketFloat", default=0.5, minimum=0.0, maximum=1.0)
    _socket(group, "Threshold", "INPUT", "NodeSocketFloat", default=0.5, minimum=0.0, maximum=1.0)
    _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=0.15, minimum=0.0, maximum=1.0)
    _socket(group, "Seed", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1000000.0, maximum=1000000.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Preview", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    _socket(group, "Mask Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    noise = _node(group, "ShaderNodeTexNoise", "Noise Mask Texture", -650, 140)
    noise.noise_dimensions = "4D"
    half_softness = _math(group, "MULTIPLY", "Half Noise Softness", -360, -170, value_2=0.5)
    lower = _math(group, "SUBTRACT", "Noise Mask Lower", -170, -100)
    upper = _math(group, "ADD", "Noise Mask Upper", -170, -230)
    epsilon_upper = _math(group, "ADD", "Noise Minimum Width", 10, -300, value_2=0.00001)
    safe_upper = _math(group, "MAXIMUM", "Safe Noise Upper", 190, -230)
    ramp = _node(group, "ShaderNodeMapRange", "Noise Threshold Mask", 80, 140)
    ramp.interpolation_type = "SMOOTHERSTEP"
    ramp.clamp = True
    ramp.inputs["To Min"].default_value = 0.0
    ramp.inputs["To Max"].default_value = 1.0

    links.new(inp.outputs["UV Vector"], noise.inputs["Vector"])
    links.new(inp.outputs["Seed"], noise.inputs["W"])
    links.new(inp.outputs["Scale"], noise.inputs["Scale"])
    links.new(inp.outputs["Detail"], noise.inputs["Detail"])
    links.new(inp.outputs["Roughness"], noise.inputs["Roughness"])
    links.new(inp.outputs["Softness"], half_softness.inputs[0])
    links.new(inp.outputs["Threshold"], lower.inputs[0])
    links.new(half_softness.outputs[0], lower.inputs[1])
    links.new(inp.outputs["Threshold"], upper.inputs[0])
    links.new(half_softness.outputs[0], upper.inputs[1])
    links.new(lower.outputs[0], epsilon_upper.inputs[0])
    links.new(upper.outputs[0], safe_upper.inputs[0])
    links.new(epsilon_upper.outputs[0], safe_upper.inputs[1])
    links.new(noise.outputs["Fac"], ramp.inputs["Value"])
    links.new(lower.outputs[0], ramp.inputs["From Min"])
    links.new(safe_upper.outputs[0], ramp.inputs["From Max"])
    group["fbp_generated_mask_contract_version"] = 1
    return _finish_generated_mask(group, inp, out, ramp.outputs["Result"], prefix="Noise Mask", x=330, y=130)



def _configure_effect_color_ramp(node, role, elements):
    """Configure and tag a native Color Ramp exposed by the Effects panel."""
    node["fbp_effect_color_ramp"] = True
    node["fbp_effect_ramp_role"] = str(role or "")
    ramp = node.color_ramp
    while len(ramp.elements) > 2:
        ramp.elements.remove(ramp.elements[-1])
    for index, (position, color) in enumerate(elements[:2]):
        element = ramp.elements[index]
        element.position = float(position)
        element.color = tuple(color)
    for position, color in elements[2:]:
        element = ramp.elements.new(float(position))
        element.color = tuple(color)
    try:
        ramp.interpolation = "LINEAR"
        ramp.color_mode = "RGB"
    except (AttributeError, TypeError, ValueError):
        pass
    return node


def _create_recolor(name):
    """Map source luminance through a user-editable native Color Ramp."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links

    luma = _node(group, "ShaderNodeRGBToBW", "Recolor Luminance", -520, 120)
    ramp = _configure_effect_color_ramp(
        _node(group, "ShaderNodeValToRGB", "Recolor Ramp", -260, 120),
        "RECOLOR",
        ((0.0, (0.02, 0.02, 0.02, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0))),
    )
    mix = _mix_rgb(group, "MIX", "Recolor Mix", 180, 100)
    links.new(inp.outputs["Color In"], luma.inputs[0])
    links.new(luma.outputs[0], ramp.inputs["Fac"])
    links.new(inp.outputs["Factor"], mix.inputs[0])
    links.new(inp.outputs["Color In"], mix.inputs[1])
    links.new(ramp.outputs["Color"], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Color Out"])
    group["fbp_color_ramp_contract_version"] = 1
    return group


def _create_gradient_light(name):
    """Multiply the source by a directional user-editable Color Ramp."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Light Angle", "INPUT", "NodeSocketFloat", default=0.0, minimum=-6.283185, maximum=6.283185)
    _socket(group, "Light Position", "INPUT", "NodeSocketFloat", default=0.0, minimum=-2.0, maximum=2.0)
    _socket(group, "Strength", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links

    center = _vector_math(group, "SUBTRACT", "Centered Light UV", -700, 120)
    center.inputs[1].default_value = (0.5, 0.5, 0.0)
    rotate = _node(group, "ShaderNodeVectorRotate", "Rotate Gradient Light", -480, 120)
    rotate.rotation_type = "Z_AXIS"
    rotate.inputs["Center"].default_value = (0.0, 0.0, 0.0)
    separate = _node(group, "ShaderNodeSeparateXYZ", "Gradient Light Axis", -250, 120)
    normalize = _math(group, "ADD", "Gradient Light Position", -50, 120, value_2=0.5)
    position = _math(group, "SUBTRACT", "Gradient Light Offset", 130, 120)
    ramp = _configure_effect_color_ramp(
        _node(group, "ShaderNodeValToRGB", "Gradient Light Ramp", 340, 120),
        "GRADIENT_LIGHT",
        ((0.0, (0.04, 0.05, 0.08, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0))),
    )
    multiply = _mix_rgb(group, "MULTIPLY", "Gradient Light Multiply", 610, 130)
    result = _mix_rgb(group, "MIX", "Gradient Light Strength", 850, 130)

    links.new(inp.outputs["UV Vector"], center.inputs[0])
    links.new(center.outputs[0], rotate.inputs["Vector"])
    links.new(inp.outputs["Light Angle"], rotate.inputs["Angle"])
    links.new(rotate.outputs["Vector"], separate.inputs[0])
    links.new(separate.outputs["X"], normalize.inputs[0])
    links.new(normalize.outputs[0], position.inputs[0])
    links.new(inp.outputs["Light Position"], position.inputs[1])
    links.new(position.outputs[0], ramp.inputs["Fac"])
    links.new(inp.outputs["Color In"], multiply.inputs[1])
    links.new(ramp.outputs["Color"], multiply.inputs[2])
    links.new(inp.outputs["Strength"], result.inputs[0])
    links.new(inp.outputs["Color In"], result.inputs[1])
    links.new(multiply.outputs[0], result.inputs[2])
    links.new(result.outputs[0], out.inputs["Color Out"])
    group["fbp_color_ramp_contract_version"] = 1
    return group


def _rim_image_sample(group, uv_output, vector_offset, name, x, y):
    add = _vector_math(group, "ADD", f"{name} UV", x, y)
    image = _node(group, "ShaderNodeTexImage", f"{name} Sample", x + 210, y)
    image["fbp_matrix_source_image_node"] = True
    image["fbp_source_interpolation"] = "Linear"
    try:
        image.extension = "EXTEND"
        image.interpolation = "Linear"
    except (AttributeError, TypeError, ValueError):
        pass
    group.links.new(uv_output, add.inputs[0])
    group.links.new(vector_offset, add.inputs[1])
    group.links.new(add.outputs[0], image.inputs["Vector"])
    return image.outputs["Alpha"]


def _create_rim(name):
    """Create a soft colorable inner/outer rim from source alpha."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Image Sample", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Width", "INPUT", "NodeSocketFloat", default=0.012, minimum=0.00001, maximum=0.5)
    _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=0.25, minimum=0.0, maximum=1.0)
    _socket(group, "Intensity", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=2.0)
    _socket(group, "Rim Color", "INPUT", "NodeSocketColor", default=(1.0, 0.35, 0.05, 1.0))
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    neg_width = _math(group, "MULTIPLY", "Negative Rim Width", -820, -240, value_2=-1.0)
    offset_r = _node(group, "ShaderNodeCombineXYZ", "Rim Right Offset", -620, 430)
    offset_l = _node(group, "ShaderNodeCombineXYZ", "Rim Left Offset", -620, 250)
    offset_u = _node(group, "ShaderNodeCombineXYZ", "Rim Up Offset", -620, 70)
    offset_d = _node(group, "ShaderNodeCombineXYZ", "Rim Down Offset", -620, -110)
    links.new(inp.outputs["Width"], neg_width.inputs[0])
    links.new(inp.outputs["Width"], offset_r.inputs["X"])
    links.new(neg_width.outputs[0], offset_l.inputs["X"])
    links.new(inp.outputs["Width"], offset_u.inputs["Y"])
    links.new(neg_width.outputs[0], offset_d.inputs["Y"])

    samples = [
        _rim_image_sample(group, inp.outputs["UV Vector"], offset_r.outputs[0], "Rim Right", -390, 430),
        _rim_image_sample(group, inp.outputs["UV Vector"], offset_l.outputs[0], "Rim Left", -390, 250),
        _rim_image_sample(group, inp.outputs["UV Vector"], offset_u.outputs[0], "Rim Up", -390, 70),
        _rim_image_sample(group, inp.outputs["UV Vector"], offset_d.outputs[0], "Rim Down", -390, -110),
    ]
    max_a = _math(group, "MAXIMUM", "Rim Neighbor Max A", 60, 360)
    max_b = _math(group, "MAXIMUM", "Rim Neighbor Max B", 60, 140)
    max_all = _math(group, "MAXIMUM", "Rim Neighbor Maximum", 250, 250)
    min_a = _math(group, "MINIMUM", "Rim Neighbor Min A", 60, -80)
    min_b = _math(group, "MINIMUM", "Rim Neighbor Min B", 60, -300)
    min_all = _math(group, "MINIMUM", "Rim Neighbor Minimum", 250, -190)
    for node, a, b in ((max_a, samples[0], samples[1]), (max_b, samples[2], samples[3]), (min_a, samples[0], samples[1]), (min_b, samples[2], samples[3])):
        links.new(a, node.inputs[0])
        links.new(b, node.inputs[1])
    links.new(max_a.outputs[0], max_all.inputs[0])
    links.new(max_b.outputs[0], max_all.inputs[1])
    links.new(min_a.outputs[0], min_all.inputs[0])
    links.new(min_b.outputs[0], min_all.inputs[1])
    outer = _math(group, "SUBTRACT", "Outer Rim", 450, 280)
    inner = _math(group, "SUBTRACT", "Inner Rim", 450, 70)
    edge = _math(group, "MAXIMUM", "Image Rim Edge", 630, 180)
    links.new(max_all.outputs[0], outer.inputs[0])
    links.new(inp.outputs["Alpha In"], outer.inputs[1])
    links.new(inp.outputs["Alpha In"], inner.inputs[0])
    links.new(min_all.outputs[0], inner.inputs[1])
    links.new(outer.outputs[0], edge.inputs[0])
    links.new(inner.outputs[0], edge.inputs[1])

    # UV-border fallback for procedural Color/Gradient planes.
    uv_sep = _node(group, "ShaderNodeSeparateXYZ", "Rim UV Axes", -360, -470)
    inv_x = _math(group, "SUBTRACT", "Rim Inverse X", -140, -520, value_1=1.0)
    inv_y = _math(group, "SUBTRACT", "Rim Inverse Y", -140, -680, value_1=1.0)
    min_x = _math(group, "MINIMUM", "Rim X Distance", 50, -520)
    min_y = _math(group, "MINIMUM", "Rim Y Distance", 50, -680)
    border_distance = _math(group, "MINIMUM", "Rim Border Distance", 250, -600)
    border_limit = _math(group, "ADD", "Rim Border Soft Limit", 450, -610)
    border_delta = _math(group, "SUBTRACT", "Rim Border Delta", 630, -600)
    safe_soft = _math(group, "MAXIMUM", "Rim Safe Softness", 630, -740, value_2=0.0001)
    border_norm = _math(group, "DIVIDE", "Rim Border Normalize", 810, -620)
    border_clamp_low = _math(group, "MAXIMUM", "Rim Border Clamp Low", 990, -620, value_2=0.0)
    border_mask = _math(group, "MINIMUM", "Rim Border Mask", 1170, -620, value_2=1.0)
    links.new(inp.outputs["UV Vector"], uv_sep.inputs[0])
    links.new(uv_sep.outputs["X"], inv_x.inputs[1])
    links.new(uv_sep.outputs["Y"], inv_y.inputs[1])
    links.new(uv_sep.outputs["X"], min_x.inputs[0])
    links.new(inv_x.outputs[0], min_x.inputs[1])
    links.new(uv_sep.outputs["Y"], min_y.inputs[0])
    links.new(inv_y.outputs[0], min_y.inputs[1])
    links.new(min_x.outputs[0], border_distance.inputs[0])
    links.new(min_y.outputs[0], border_distance.inputs[1])
    links.new(inp.outputs["Width"], border_limit.inputs[0])
    links.new(inp.outputs["Softness"], border_limit.inputs[1])
    links.new(border_limit.outputs[0], border_delta.inputs[0])
    links.new(border_distance.outputs[0], border_delta.inputs[1])
    links.new(inp.outputs["Softness"], safe_soft.inputs[0])
    links.new(border_delta.outputs[0], border_norm.inputs[0])
    links.new(safe_soft.outputs[0], border_norm.inputs[1])
    links.new(border_norm.outputs[0], border_clamp_low.inputs[0])
    links.new(border_clamp_low.outputs[0], border_mask.inputs[0])

    image_weight = _math(group, "MULTIPLY", "Image Rim Weight", 830, 180)
    fallback_weight = _math(group, "SUBTRACT", "Fallback Rim Weight", 830, -40, value_1=1.0)
    fallback_mask = _math(group, "MULTIPLY", "Fallback Rim", 1010, -40)
    combined = _math(group, "ADD", "Selected Rim", 1190, 100)
    intensity = _math(group, "MULTIPLY", "Rim Intensity", 1370, 100)
    clamp = _math(group, "MINIMUM", "Rim Clamp", 1540, 100, value_2=1.0)
    links.new(edge.outputs[0], image_weight.inputs[0])
    links.new(inp.outputs["Use Image Sample"], image_weight.inputs[1])
    links.new(inp.outputs["Use Image Sample"], fallback_weight.inputs[1])
    links.new(border_mask.outputs[0], fallback_mask.inputs[0])
    links.new(fallback_weight.outputs[0], fallback_mask.inputs[1])
    links.new(image_weight.outputs[0], combined.inputs[0])
    links.new(fallback_mask.outputs[0], combined.inputs[1])
    links.new(combined.outputs[0], intensity.inputs[0])
    links.new(inp.outputs["Intensity"], intensity.inputs[1])
    links.new(intensity.outputs[0], clamp.inputs[0])

    mix = _mix_rgb(group, "MIX", "Apply Rim Color", 1740, 160)
    alpha = _math(group, "MAXIMUM", "Rim Alpha", 1740, -40)
    links.new(clamp.outputs[0], mix.inputs[0])
    links.new(inp.outputs["Color In"], mix.inputs[1])
    links.new(inp.outputs["Rim Color"], mix.inputs[2])
    links.new(inp.outputs["Alpha In"], alpha.inputs[0])
    links.new(clamp.outputs[0], alpha.inputs[1])
    links.new(mix.outputs[0], out.inputs["Color Out"])
    links.new(alpha.outputs[0], out.inputs["Alpha Out"])
    group["fbp_rim_contract_version"] = 1
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
            except FBP_DATA_ERRORS:
                continue
    except FBP_DATA_ERRORS:
        pass

    try:
        image = bpy.data.images.load(str(path), check_existing=False)
        actual_size = tuple(int(value) for value in image.size[:2])
        if actual_size != expected_size:
            # Do not free image buffers here; Blender 5.1 can still have cache
            # users attached during UI updates/file replacement.
            try:
                image.use_fake_user = False
                image["fbp_invalid_asset"] = True
            except FBP_DATA_ERRORS:
                pass
            raise RuntimeError(
                f"Invalid Textellation atlas size {actual_size}; expected {expected_size}"
            )
        image.name = "FBP Textellation Atlas"
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
        except FBP_DATA_ERRORS:
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



TERMINAL_ASCII_FILL_SIZE = (80, 8)
TERMINAL_ASCII_EDGE_SIZE = (72, 8)
TERMINAL_ASCII_FILL_COLUMNS = 10
TERMINAL_ASCII_EDGE_COLUMNS = 9
TERMINAL_ASCII_ASSET_REVISION = "028c8bd7-87bd03d3"


def _load_terminal_ascii_asset(asset_dir, filename, datablock_name, expected_size, role):
    path = Path(asset_dir) / filename
    if not path.is_file():
        return None
    for candidate in tuple(bpy.data.images):
        try:
            if (
                str(candidate.get("fbp_terminal_ascii_revision", "") or "") == TERMINAL_ASCII_ASSET_REVISION
                and str(candidate.get("fbp_terminal_ascii_role", "") or "") == role
                and tuple(int(value) for value in candidate.size[:2]) == expected_size
            ):
                return candidate
        except FBP_DATA_ERRORS:
            continue
    try:
        image = bpy.data.images.load(str(path), check_existing=False)
        actual_size = tuple(int(value) for value in image.size[:2])
        if actual_size != expected_size:
            try:
                if image.users == 0:
                    bpy.data.images.remove(image)
            except FBP_DATA_ERRORS:
                pass
            return None
        image.name = datablock_name
        image["fbp_terminal_ascii_revision"] = TERMINAL_ASCII_ASSET_REVISION
        image["fbp_terminal_ascii_role"] = role
        try:
            image.colorspace_settings.name = "Non-Color"
        except FBP_DATA_ERRORS:
            pass
        return image
    except FBP_DATA_ERRORS:
        return None


def _load_terminal_ascii_assets(asset_dir):
    fill = _load_terminal_ascii_asset(
        asset_dir, "fillASCII.png", "FBP Ascii Fill Atlas",
        TERMINAL_ASCII_FILL_SIZE, "FILL",
    )
    edges = _load_terminal_ascii_asset(
        asset_dir, "edgesASCII.jpg", "FBP Ascii Edge Atlas",
        TERMINAL_ASCII_EDGE_SIZE, "EDGES",
    )
    return fill, edges


def _create_terminal_ascii(name, asset_dir):
    """Create terminal-style fill and directional-edge ASCII for FBP planes.

    The 8x8 glyph atlases originate from Blender-Image-To-ASCII by J. M Areeb
    Uzair (MIT). The compositor concept is adapted here to an image-aware shader
    group so it works directly on static and animated Frame By Plane materials.
    """
    fill_image, edge_image = _load_terminal_ascii_assets(asset_dir)
    if fill_image is None or edge_image is None:
        raise RuntimeError("Ascii fill or edge glyph atlas is missing or invalid")

    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Image Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Cell Scale", "INPUT", "NodeSocketFloat", default=64.0, minimum=1.0, maximum=1000.0)
    _socket(group, "Aspect Ratio", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.001, maximum=1000.0)
    _socket(group, "Contrast", "INPUT", "NodeSocketFloat", default=1.25, minimum=0.0, maximum=8.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Fill Strength", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=4.0)
    _socket(group, "Fill Threshold", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=0.95)
    _socket(group, "Use Edges", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Edge Strength", "INPUT", "NodeSocketFloat", default=4.0, minimum=0.0, maximum=32.0)
    _socket(group, "Edge Threshold", "INPUT", "NodeSocketFloat", default=0.08, minimum=0.0, maximum=1.0)
    _socket(group, "Edge Mix", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Use Source Color", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Foreground", "INPUT", "NodeSocketColor", default=(0.42, 1.0, 0.42, 1.0))
    _socket(group, "Background", "INPUT", "NodeSocketColor", default=(0.0, 0.0, 0.0, 1.0))
    _socket(group, "Transparent Background", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Seed", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100000.0, maximum=100000.0)
    _socket(group, "Debug Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    grid = _matrix_cell_coordinates(group, inp, x=-2500, y=-260)
    _center_image, center_color, center_alpha = _matrix_source_sample(
        group, inp, grid["center_uv"], x=-850, y=-120, label="Ascii"
    )

    alpha_low = _math(group, "MAXIMUM", "Ascii Alpha Minimum", -610, 560, value_2=0.0)
    alpha_high = _math(group, "MINIMUM", "Ascii Alpha Maximum", -430, 560, value_2=1.0)
    over_white = _mix_rgb(group, "MIX", "Ascii Alpha Over White", -230, 560)
    over_white.inputs[1].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(center_alpha, alpha_low.inputs[0])
    links.new(alpha_low.outputs[0], alpha_high.inputs[0])
    links.new(alpha_high.outputs[0], over_white.inputs[0])
    links.new(center_color, over_white.inputs[2])

    luminance = _controlled_luminance(
        group, over_white.outputs[0], inp.outputs["Contrast"], inp.outputs["Invert"], x=0, y=680
    )
    density = _math(group, "SUBTRACT", "Ascii Fill Density", 1540, 680, value_1=1.0)
    thresholded = _math(group, "SUBTRACT", "Ascii Fill Threshold", 1720, 680)
    threshold_room = _math(group, "SUBTRACT", "Ascii Fill Threshold Range", 1720, 530, value_1=1.0)
    safe_room = _math(group, "MAXIMUM", "Ascii Safe Fill Range", 1900, 530, value_2=0.001)
    normalized_fill = _math(group, "DIVIDE", "Ascii Normalized Fill", 1900, 680)
    fill_scaled = _math(group, "MULTIPLY", "Ascii Fill Strength", 2080, 680)
    fill_low = _math(group, "MAXIMUM", "Ascii Fill Minimum", 2260, 680, value_2=0.0)
    fill_high = _math(group, "MINIMUM", "Ascii Fill Maximum", 2440, 680, value_2=1.0)
    fill_index_scale = _math(group, "MULTIPLY", "Ascii Fill Index Scale", 2620, 680, value_2=float(TERMINAL_ASCII_FILL_COLUMNS - 1))
    fill_index = _math(group, "ROUND", "Ascii Fill Index", 2800, 680)

    # Evolution is dormant at Seed 0, preserving the original 5.3.0 look.
    # A non-zero manual or generated seed selects a deterministic neighboring
    # glyph per cell. The stepped Evolution system updates only this socket.
    seed_abs = _math(group, "ABSOLUTE", "Ascii Seed Absolute", 2600, 930)
    seed_active = _math(group, "GREATER_THAN", "Ascii Seed Active", 2780, 930, value_2=0.0001)
    fill_seed_noise = _node(group, "ShaderNodeTexWhiteNoise", "Ascii Evolution Noise", 2780, 1090)
    fill_seed_noise.noise_dimensions = "4D"
    fill_seed_center = _math(group, "SUBTRACT", "Ascii Evolution Center", 2980, 1090, value_2=0.5)
    fill_seed_range = _math(group, "MULTIPLY", "Ascii Evolution Range", 3160, 1090, value_2=2.0)
    fill_seed_step = _math(group, "ROUND", "Ascii Evolution Glyph Step", 3340, 1090)
    fill_seed_enabled = _math(group, "MULTIPLY", "Ascii Evolution Enabled", 3520, 1090)
    fill_index_varied = _math(group, "ADD", "Ascii Evolved Fill Index", 2980, 680)
    fill_index_low = _math(group, "MAXIMUM", "Ascii Evolved Fill Minimum", 3160, 680, value_2=0.0)
    fill_index_high = _math(group, "MINIMUM", "Ascii Evolved Fill Maximum", 3340, 680, value_2=float(TERMINAL_ASCII_FILL_COLUMNS - 1))
    fill_index_final = _math(group, "ROUND", "Ascii Final Fill Index", 3520, 680)

    links.new(inp.outputs["Seed"], seed_abs.inputs[0])
    links.new(seed_abs.outputs[0], seed_active.inputs[0])
    links.new(grid["cell_id"], fill_seed_noise.inputs["Vector"])
    links.new(inp.outputs["Seed"], fill_seed_noise.inputs["W"])
    links.new(fill_seed_noise.outputs["Value"], fill_seed_center.inputs[0])
    links.new(fill_seed_center.outputs[0], fill_seed_range.inputs[0])
    links.new(fill_seed_range.outputs[0], fill_seed_step.inputs[0])
    links.new(fill_seed_step.outputs[0], fill_seed_enabled.inputs[0])
    links.new(seed_active.outputs[0], fill_seed_enabled.inputs[1])
    links.new(fill_index.outputs[0], fill_index_varied.inputs[0])
    links.new(fill_seed_enabled.outputs[0], fill_index_varied.inputs[1])
    links.new(fill_index_varied.outputs[0], fill_index_low.inputs[0])
    links.new(fill_index_low.outputs[0], fill_index_high.inputs[0])
    links.new(fill_index_high.outputs[0], fill_index_final.inputs[0])

    links.new(luminance, density.inputs[1])
    links.new(density.outputs[0], thresholded.inputs[0])
    links.new(inp.outputs["Fill Threshold"], thresholded.inputs[1])
    links.new(inp.outputs["Fill Threshold"], threshold_room.inputs[1])
    links.new(threshold_room.outputs[0], safe_room.inputs[0])
    links.new(thresholded.outputs[0], normalized_fill.inputs[0])
    links.new(safe_room.outputs[0], normalized_fill.inputs[1])
    links.new(normalized_fill.outputs[0], fill_scaled.inputs[0])
    links.new(inp.outputs["Fill Strength"], fill_scaled.inputs[1])
    links.new(fill_scaled.outputs[0], fill_low.inputs[0])
    links.new(fill_low.outputs[0], fill_high.inputs[0])
    links.new(fill_high.outputs[0], fill_index_scale.inputs[0])
    links.new(fill_index_scale.outputs[0], fill_index.inputs[0])

    center_sep = _node(group, "ShaderNodeSeparateXYZ", "Ascii Center UV", -380, 170)
    inv_columns = _math(group, "DIVIDE", "Ascii U Step", -180, 250, value_1=1.0)
    inv_rows = _math(group, "DIVIDE", "Ascii V Step", -180, 90, value_1=1.0)
    right_u = _math(group, "ADD", "Ascii Right U", 20, 250)
    upper_v = _math(group, "ADD", "Ascii Upper V", 20, 90)
    right_uv = _node(group, "ShaderNodeCombineXYZ", "Ascii Right UV", 220, 220)
    upper_uv = _node(group, "ShaderNodeCombineXYZ", "Ascii Upper UV", 220, 60)
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

    def neighbor_luminance(label, uv_socket, x, y):
        image = _node(group, "ShaderNodeTexImage", f"Ascii {label} Image", x, y)
        image["fbp_matrix_source_image_node"] = True
        image.interpolation = "Closest"
        image.extension = "EXTEND"
        color = _mix_rgb(group, "MIX", f"Ascii {label} Source", x + 210, y + 50)
        fallback_weight = _math(group, "SUBTRACT", f"Ascii {label} Fallback Weight", x + 200, y - 100, value_1=1.0)
        image_alpha = _math(group, "MULTIPLY", f"Ascii {label} Image Alpha", x + 390, y - 80)
        fallback_alpha = _math(group, "MULTIPLY", f"Ascii {label} Fallback Alpha", x + 390, y - 190)
        alpha = _math(group, "ADD", f"Ascii {label} Alpha", x + 570, y - 130)
        alpha_min = _math(group, "MAXIMUM", f"Ascii {label} Alpha Min", x + 750, y - 130, value_2=0.0)
        alpha_max = _math(group, "MINIMUM", f"Ascii {label} Alpha Max", x + 930, y - 130, value_2=1.0)
        white = _mix_rgb(group, "MIX", f"Ascii {label} Over White", x + 750, y + 50)
        white.inputs[1].default_value = (1.0, 1.0, 1.0, 1.0)
        bw = _node(group, "ShaderNodeRGBToBW", f"Ascii {label} Luminance", x + 960, y + 50)
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
        links.new(alpha_max.outputs[0], white.inputs[0])
        links.new(color.outputs[0], white.inputs[2])
        links.new(white.outputs[0], bw.inputs[0])
        return bw.outputs[0]

    right_luma = neighbor_luminance("Right", right_uv.outputs[0], 410, 170)
    upper_luma = neighbor_luminance("Upper", upper_uv.outputs[0], 410, -250)
    center_bw = _node(group, "ShaderNodeRGBToBW", "Ascii Center Raw Luminance", 1190, 400)
    dx = _math(group, "SUBTRACT", "Ascii Horizontal Gradient", 1390, 260)
    dy = _math(group, "SUBTRACT", "Ascii Vertical Gradient", 1390, 80)
    abs_dx = _math(group, "ABSOLUTE", "Ascii Abs Horizontal", 1570, 260)
    abs_dy = _math(group, "ABSOLUTE", "Ascii Abs Vertical", 1570, 80)
    edge_sum = _math(group, "ADD", "Ascii Edge Magnitude", 1750, 170)
    edge_scaled = _math(group, "MULTIPLY", "Ascii Edge Strength", 1930, 170)
    edge_present = _math(group, "GREATER_THAN", "Ascii Edge Threshold", 2110, 170)
    edge_enabled = _math(group, "MULTIPLY", "Ascii Edge Enabled", 2290, 170)
    edge_mix = _math(group, "MULTIPLY", "Ascii Edge Mix", 2470, 170)
    links.new(over_white.outputs[0], center_bw.inputs[0])
    links.new(center_bw.outputs[0], dx.inputs[0])
    links.new(right_luma, dx.inputs[1])
    links.new(center_bw.outputs[0], dy.inputs[0])
    links.new(upper_luma, dy.inputs[1])
    links.new(dx.outputs[0], abs_dx.inputs[0])
    links.new(dy.outputs[0], abs_dy.inputs[0])
    links.new(abs_dx.outputs[0], edge_sum.inputs[0])
    links.new(abs_dy.outputs[0], edge_sum.inputs[1])
    links.new(edge_sum.outputs[0], edge_scaled.inputs[0])
    links.new(inp.outputs["Edge Strength"], edge_scaled.inputs[1])
    links.new(edge_scaled.outputs[0], edge_present.inputs[0])
    links.new(inp.outputs["Edge Threshold"], edge_present.inputs[1])
    links.new(edge_present.outputs[0], edge_enabled.inputs[0])
    links.new(inp.outputs["Use Edges"], edge_enabled.inputs[1])
    links.new(edge_enabled.outputs[0], edge_mix.inputs[0])
    links.new(inp.outputs["Edge Mix"], edge_mix.inputs[1])

    max_grad = _math(group, "MAXIMUM", "Ascii Max Gradient", 1750, -60)
    min_grad = _math(group, "MINIMUM", "Ascii Min Gradient", 1750, -210)
    safe_max = _math(group, "MAXIMUM", "Ascii Safe Max Gradient", 1930, -60, value_2=0.00001)
    diagonal_ratio = _math(group, "DIVIDE", "Ascii Diagonal Ratio", 2110, -110)
    diagonal = _math(group, "GREATER_THAN", "Ascii Is Diagonal", 2290, -110, value_2=0.45)
    vertical = _math(group, "GREATER_THAN", "Ascii Vertical Edge", 1930, -260)
    axis_index = _math(group, "MULTIPLY", "Ascii Axis Glyph Index", 2110, -260, value_2=2.0)
    gradient_product = _math(group, "MULTIPLY", "Ascii Gradient Sign", 1930, -410)
    positive_diagonal = _math(group, "GREATER_THAN", "Ascii Positive Diagonal", 2110, -410, value_2=0.0)
    diagonal_double = _math(group, "MULTIPLY", "Ascii Diagonal Double", 2290, -410, value_2=2.0)
    diagonal_index = _math(group, "ADD", "Ascii Diagonal Glyph Index", 2470, -410, value_2=1.0)
    non_diagonal = _math(group, "SUBTRACT", "Ascii Non Diagonal", 2470, -110, value_1=1.0)
    axis_part = _math(group, "MULTIPLY", "Ascii Axis Glyph Part", 2650, -260)
    diagonal_part = _math(group, "MULTIPLY", "Ascii Diagonal Glyph Part", 2650, -410)
    edge_index = _math(group, "ADD", "Ascii Edge Glyph Index", 2830, -330)
    links.new(abs_dx.outputs[0], max_grad.inputs[0])
    links.new(abs_dy.outputs[0], max_grad.inputs[1])
    links.new(abs_dx.outputs[0], min_grad.inputs[0])
    links.new(abs_dy.outputs[0], min_grad.inputs[1])
    links.new(max_grad.outputs[0], safe_max.inputs[0])
    links.new(min_grad.outputs[0], diagonal_ratio.inputs[0])
    links.new(safe_max.outputs[0], diagonal_ratio.inputs[1])
    links.new(diagonal_ratio.outputs[0], diagonal.inputs[0])
    links.new(abs_dx.outputs[0], vertical.inputs[0])
    links.new(abs_dy.outputs[0], vertical.inputs[1])
    links.new(vertical.outputs[0], axis_index.inputs[0])
    links.new(dx.outputs[0], gradient_product.inputs[0])
    links.new(dy.outputs[0], gradient_product.inputs[1])
    links.new(gradient_product.outputs[0], positive_diagonal.inputs[0])
    links.new(positive_diagonal.outputs[0], diagonal_double.inputs[0])
    links.new(diagonal_double.outputs[0], diagonal_index.inputs[0])
    links.new(diagonal.outputs[0], non_diagonal.inputs[1])
    links.new(axis_index.outputs[0], axis_part.inputs[0])
    links.new(non_diagonal.outputs[0], axis_part.inputs[1])
    links.new(diagonal_index.outputs[0], diagonal_part.inputs[0])
    links.new(diagonal.outputs[0], diagonal_part.inputs[1])
    links.new(axis_part.outputs[0], edge_index.inputs[0])
    links.new(diagonal_part.outputs[0], edge_index.inputs[1])

    local_sep = _node(group, "ShaderNodeSeparateXYZ", "Ascii Local Coordinates", 3000, 400)
    fill_x_add = _math(group, "ADD", "Ascii Fill X Cell", 3180, 620)
    fill_x = _math(group, "DIVIDE", "Ascii Fill Atlas X", 3360, 620, value_2=float(TERMINAL_ASCII_FILL_COLUMNS))
    fill_vector = _node(group, "ShaderNodeCombineXYZ", "Ascii Fill UV", 3540, 570)
    fill_atlas = _node(group, "ShaderNodeTexImage", "Ascii Fill Atlas", 3720, 570)
    fill_atlas["fbp_terminal_ascii_fill_node"] = True
    fill_atlas.interpolation = "Closest"
    fill_atlas.extension = "CLIP"
    fill_atlas.image = fill_image
    fill_bw = _node(group, "ShaderNodeRGBToBW", "Ascii Fill Glyph Mask", 3920, 570)
    fill_binary = _math(group, "GREATER_THAN", "Ascii Crisp Fill Glyph", 4100, 570, value_2=0.15)

    edge_x_add = _math(group, "ADD", "Ascii Edge X Cell", 3180, 260)
    edge_x = _math(group, "DIVIDE", "Ascii Edge Atlas X", 3360, 260, value_2=float(TERMINAL_ASCII_EDGE_COLUMNS))
    edge_vector = _node(group, "ShaderNodeCombineXYZ", "Ascii Edge UV", 3540, 210)
    edge_atlas = _node(group, "ShaderNodeTexImage", "Ascii Edge Atlas", 3720, 210)
    edge_atlas["fbp_terminal_ascii_edge_node"] = True
    edge_atlas.interpolation = "Closest"
    edge_atlas.extension = "CLIP"
    edge_atlas.image = edge_image
    edge_bw = _node(group, "ShaderNodeRGBToBW", "Ascii Edge Glyph Mask", 3920, 210)
    edge_binary = _math(group, "GREATER_THAN", "Ascii Crisp Edge Glyph", 4100, 210, value_2=0.15)

    links.new(grid["local_uv"], local_sep.inputs[0])
    links.new(fill_index_final.outputs[0], fill_x_add.inputs[0])
    links.new(local_sep.outputs["X"], fill_x_add.inputs[1])
    links.new(fill_x_add.outputs[0], fill_x.inputs[0])
    links.new(fill_x.outputs[0], fill_vector.inputs["X"])
    links.new(local_sep.outputs["Y"], fill_vector.inputs["Y"])
    links.new(fill_vector.outputs[0], fill_atlas.inputs["Vector"])
    links.new(fill_atlas.outputs["Color"], fill_bw.inputs[0])
    links.new(fill_bw.outputs[0], fill_binary.inputs[0])

    links.new(edge_index.outputs[0], edge_x_add.inputs[0])
    links.new(local_sep.outputs["X"], edge_x_add.inputs[1])
    links.new(edge_x_add.outputs[0], edge_x.inputs[0])
    links.new(edge_x.outputs[0], edge_vector.inputs["X"])
    links.new(local_sep.outputs["Y"], edge_vector.inputs["Y"])
    links.new(edge_vector.outputs[0], edge_atlas.inputs["Vector"])
    links.new(edge_atlas.outputs["Color"], edge_bw.inputs[0])
    links.new(edge_bw.outputs[0], edge_binary.inputs[0])

    inverse_edge_mix = _math(group, "SUBTRACT", "Ascii Fill Mix Weight", 4280, 420, value_1=1.0)
    fill_part = _math(group, "MULTIPLY", "Ascii Fill Glyph Part", 4460, 510)
    edge_part = _math(group, "MULTIPLY", "Ascii Edge Glyph Part", 4460, 310)
    glyph_mask = _math(group, "ADD", "Ascii Glyph Mask", 4640, 410)
    links.new(edge_mix.outputs[0], inverse_edge_mix.inputs[1])
    links.new(fill_binary.outputs[0], fill_part.inputs[0])
    links.new(inverse_edge_mix.outputs[0], fill_part.inputs[1])
    links.new(edge_binary.outputs[0], edge_part.inputs[0])
    links.new(edge_mix.outputs[0], edge_part.inputs[1])
    links.new(fill_part.outputs[0], glyph_mask.inputs[0])
    links.new(edge_part.outputs[0], glyph_mask.inputs[1])

    foreground = _mix_rgb(group, "MIX", "Ascii Foreground", 4820, 610)
    final = _mix_rgb(group, "MIX", "Ascii Output", 5040, 500)
    links.new(inp.outputs["Use Source Color"], foreground.inputs[0])
    links.new(inp.outputs["Foreground"], foreground.inputs[1])
    links.new(center_color, foreground.inputs[2])
    links.new(glyph_mask.outputs[0], final.inputs[0])
    links.new(inp.outputs["Background"], final.inputs[1])
    links.new(foreground.outputs[0], final.inputs[2])

    debug_color = _debug_color(
        group, final.outputs[0], luminance, edge_mix.outputs[0], inp.outputs["Debug Mode"],
        x=5260, y=500, prefix="Ascii"
    )
    links.new(debug_color, out.inputs["Color Out"])

    opaque_weight = _math(group, "SUBTRACT", "Ascii Opaque Background Weight", 4820, 90, value_1=1.0)
    background_alpha = _math(group, "MULTIPLY", "Ascii Background Alpha", 5000, 40)
    glyph_alpha = _math(group, "MULTIPLY", "Ascii Glyph Source Alpha", 5000, -100)
    transparent_alpha = _math(group, "MULTIPLY", "Ascii Transparent Glyph Alpha", 5180, -100)
    final_alpha = _math(group, "ADD", "Ascii Final Alpha", 5360, -30)
    links.new(inp.outputs["Transparent Background"], opaque_weight.inputs[1])
    links.new(center_alpha, background_alpha.inputs[0])
    links.new(opaque_weight.outputs[0], background_alpha.inputs[1])
    links.new(glyph_mask.outputs[0], glyph_alpha.inputs[0])
    links.new(center_alpha, glyph_alpha.inputs[1])
    links.new(glyph_alpha.outputs[0], transparent_alpha.inputs[0])
    links.new(inp.outputs["Transparent Background"], transparent_alpha.inputs[1])
    links.new(background_alpha.outputs[0], final_alpha.inputs[0])
    links.new(transparent_alpha.outputs[0], final_alpha.inputs[1])

    debug_active = _math(group, "GREATER_THAN", "Ascii Debug Active", 5540, -100, value_2=0.5)
    debug_alpha = _mix_rgb(group, "MIX", "Ascii Debug Alpha", 5720, -30)
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



def _create_mesh_ripple(name):
    """Create a directional/radial ripple Geometry Nodes group."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Subdivision", "INPUT", "NodeSocketInt", default=4, minimum=0, maximum=7)
    _socket(group, "Direction", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Amplitude", "INPUT", "NodeSocketFloat", default=0.08, minimum=-10.0, maximum=10.0)
    _socket(group, "Frequency", "INPUT", "NodeSocketFloat", default=3.0, minimum=0.0, maximum=100.0)
    _socket(group, "Speed", "INPUT", "NodeSocketFloat", default=1.0, minimum=-100.0, maximum=100.0)
    _socket(group, "Phase", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1000.0, maximum=1000.0)
    _socket(group, "Stepped", "INPUT", "NodeSocketInt", default=1, minimum=1, maximum=240)
    _socket(group, "Pin Borders", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Border Falloff", "INPUT", "NodeSocketFloat", default=0.15, minimum=0.001, maximum=1.0)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    subdivide = _node(group, "GeometryNodeSubdivideMesh", "Ripple Subdivision", -1500, 320)
    bounds = _node(group, "GeometryNodeBoundBox", "Ripple Bounds", -1300, 80)
    position = _node(group, "GeometryNodeInputPosition", "Ripple Position", -1300, -160)
    pos_xyz = _node(group, "ShaderNodeSeparateXYZ", "Ripple Position Axes", -1110, -160)
    min_xyz = _node(group, "ShaderNodeSeparateXYZ", "Ripple Minimum Axes", -1110, 40)
    max_xyz = _node(group, "ShaderNodeSeparateXYZ", "Ripple Maximum Axes", -1110, 220)
    links.new(inp.outputs["Geometry"], subdivide.inputs["Mesh"])
    links.new(inp.outputs["Subdivision"], subdivide.inputs["Level"])
    links.new(subdivide.outputs["Mesh"], bounds.inputs["Geometry"])
    links.new(position.outputs["Position"], pos_xyz.inputs[0])
    links.new(bounds.outputs["Min"], min_xyz.inputs[0])
    links.new(bounds.outputs["Max"], max_xyz.inputs[0])

    def normalized_axis(axis, y):
        size = _math(group, "SUBTRACT", f"Ripple {axis} Size", -910, y)
        safe = _math(group, "MAXIMUM", f"Ripple Safe {axis}", -740, y, value_2=0.000001)
        relative = _math(group, "SUBTRACT", f"Ripple {axis} Relative", -910, y - 90)
        normalized = _math(group, "DIVIDE", f"Ripple Normalized {axis}", -560, y - 40)
        links.new(max_xyz.outputs[axis], size.inputs[0])
        links.new(min_xyz.outputs[axis], size.inputs[1])
        links.new(size.outputs[0], safe.inputs[0])
        links.new(pos_xyz.outputs[axis], relative.inputs[0])
        links.new(min_xyz.outputs[axis], relative.inputs[1])
        links.new(relative.outputs[0], normalized.inputs[0])
        links.new(safe.outputs[0], normalized.inputs[1])
        return normalized.outputs[0]

    norm_x = normalized_axis("X", 210)
    norm_y = normalized_axis("Y", -20)
    centered_x = _math(group, "SUBTRACT", "Ripple Centered X", -360, 90, value_2=0.5)
    centered_y = _math(group, "SUBTRACT", "Ripple Centered Y", -360, -40, value_2=0.5)
    center_vec = _node(group, "ShaderNodeCombineXYZ", "Ripple Center Vector", -170, 20)
    radial = _vector_math(group, "LENGTH", "Ripple Radius", 20, 20)
    links.new(norm_x, centered_x.inputs[0])
    links.new(norm_y, centered_y.inputs[0])
    links.new(centered_x.outputs[0], center_vec.inputs["X"])
    links.new(centered_y.outputs[0], center_vec.inputs["Y"])
    links.new(center_vec.outputs[0], radial.inputs[0])

    use_y = _math(group, "GREATER_THAN", "Ripple Use Y", 10, 250, value_2=0.5)
    xy_switch = _node(group, "GeometryNodeSwitch", "Ripple X or Y", 210, 240)
    xy_switch.input_type = "FLOAT"
    use_radial = _math(group, "GREATER_THAN", "Ripple Use Radial", 210, 90, value_2=1.5)
    direction_switch = _node(group, "GeometryNodeSwitch", "Ripple Direction", 410, 180)
    direction_switch.input_type = "FLOAT"
    links.new(inp.outputs["Direction"], use_y.inputs[0])
    links.new(use_y.outputs[0], xy_switch.inputs["Switch"])
    links.new(norm_x, xy_switch.inputs["False"])
    links.new(norm_y, xy_switch.inputs["True"])
    links.new(inp.outputs["Direction"], use_radial.inputs[0])
    links.new(use_radial.outputs[0], direction_switch.inputs["Switch"])
    links.new(xy_switch.outputs["Output"], direction_switch.inputs["False"])
    links.new(_output(radial, "Value", 1), direction_switch.inputs["True"])

    coord_freq = _math(group, "MULTIPLY", "Ripple Coordinate Frequency", 610, 180)
    coord_cycles = _math(group, "MULTIPLY", "Ripple Coordinate Cycles", 790, 180, value_2=6.283185307179586)
    scene_time = _node(group, "GeometryNodeInputSceneTime", "Ripple Scene Time", 180, -250)
    safe_step = _math(group, "MAXIMUM", "Ripple Safe Step", 180, -390, value_2=1.0)
    frame_div = _math(group, "DIVIDE", "Ripple Frame Divide", 370, -250)
    frame_floor = _math(group, "FLOOR", "Ripple Frame Floor", 550, -250)
    stepped_frame = _math(group, "MULTIPLY", "Ripple Stepped Frame", 730, -250)
    time_scale = _math(group, "MULTIPLY", "Ripple Time Scale", 910, -250, value_2=0.1)
    time_speed = _math(group, "MULTIPLY", "Ripple Time Speed", 1090, -250)
    moving_phase = _math(group, "ADD", "Ripple Moving Phase", 1090, 80)
    user_phase = _math(group, "ADD", "Ripple User Phase", 1270, 80)
    sine = _math(group, "SINE", "Ripple Sine", 1450, 80)
    amplitude = _math(group, "MULTIPLY", "Ripple Amplitude", 1630, 80)
    links.new(direction_switch.outputs["Output"], coord_freq.inputs[0])
    links.new(inp.outputs["Frequency"], coord_freq.inputs[1])
    links.new(coord_freq.outputs[0], coord_cycles.inputs[0])
    links.new(inp.outputs["Stepped"], safe_step.inputs[0])
    links.new(scene_time.outputs["Frame"], frame_div.inputs[0])
    links.new(safe_step.outputs[0], frame_div.inputs[1])
    links.new(frame_div.outputs[0], frame_floor.inputs[0])
    links.new(frame_floor.outputs[0], stepped_frame.inputs[0])
    links.new(safe_step.outputs[0], stepped_frame.inputs[1])
    links.new(stepped_frame.outputs[0], time_scale.inputs[0])
    links.new(time_scale.outputs[0], time_speed.inputs[0])
    links.new(inp.outputs["Speed"], time_speed.inputs[1])
    links.new(coord_cycles.outputs[0], moving_phase.inputs[0])
    links.new(time_speed.outputs[0], moving_phase.inputs[1])
    links.new(moving_phase.outputs[0], user_phase.inputs[0])
    links.new(inp.outputs["Phase"], user_phase.inputs[1])
    links.new(user_phase.outputs[0], sine.inputs[0])
    links.new(sine.outputs[0], amplitude.inputs[0])
    links.new(inp.outputs["Amplitude"], amplitude.inputs[1])

    inv_x = _math(group, "SUBTRACT", "Ripple Inverse X", 720, -520, value_1=1.0)
    inv_y = _math(group, "SUBTRACT", "Ripple Inverse Y", 720, -650, value_1=1.0)
    edge_x = _math(group, "MINIMUM", "Ripple X Edge Distance", 900, -520)
    edge_y = _math(group, "MINIMUM", "Ripple Y Edge Distance", 900, -650)
    edge_min = _math(group, "MINIMUM", "Ripple Border Distance", 1080, -585)
    safe_falloff = _math(group, "MAXIMUM", "Ripple Safe Border Falloff", 1260, -650, value_2=0.001)
    edge_normalized = _math(group, "DIVIDE", "Ripple Border Normalize", 1440, -585)
    edge_clamp = _math(group, "MINIMUM", "Ripple Border Clamp", 1620, -585, value_2=1.0)
    pin_inverse = _math(group, "SUBTRACT", "Ripple Unpinned Weight", 1440, -410, value_1=1.0)
    pin_edge = _math(group, "MULTIPLY", "Ripple Pinned Edge", 1800, -520)
    pin_free = _math(group, "MULTIPLY", "Ripple Free Surface", 1800, -390)
    pin_mix = _math(group, "ADD", "Ripple Pin Mix", 1980, -455)
    masked = _math(group, "MULTIPLY", "Ripple Masked Amount", 1980, 60)
    links.new(norm_x, inv_x.inputs[1])
    links.new(norm_y, inv_y.inputs[1])
    links.new(norm_x, edge_x.inputs[0])
    links.new(inv_x.outputs[0], edge_x.inputs[1])
    links.new(norm_y, edge_y.inputs[0])
    links.new(inv_y.outputs[0], edge_y.inputs[1])
    links.new(edge_x.outputs[0], edge_min.inputs[0])
    links.new(edge_y.outputs[0], edge_min.inputs[1])
    links.new(inp.outputs["Border Falloff"], safe_falloff.inputs[0])
    links.new(edge_min.outputs[0], edge_normalized.inputs[0])
    links.new(safe_falloff.outputs[0], edge_normalized.inputs[1])
    links.new(edge_normalized.outputs[0], edge_clamp.inputs[0])
    links.new(inp.outputs["Pin Borders"], pin_inverse.inputs[1])
    links.new(edge_clamp.outputs[0], pin_edge.inputs[0])
    links.new(inp.outputs["Pin Borders"], pin_edge.inputs[1])
    pin_free.inputs[0].default_value = 1.0
    links.new(pin_inverse.outputs[0], pin_free.inputs[1])
    links.new(pin_edge.outputs[0], pin_mix.inputs[0])
    links.new(pin_free.outputs[0], pin_mix.inputs[1])
    links.new(amplitude.outputs[0], masked.inputs[0])
    links.new(pin_mix.outputs[0], masked.inputs[1])

    offset = _node(group, "ShaderNodeCombineXYZ", "Ripple Offset", 2170, 60)
    set_position = _node(group, "GeometryNodeSetPosition", "Mesh Ripple", 2370, 260)
    links.new(masked.outputs[0], offset.inputs["Z"])
    links.new(subdivide.outputs["Mesh"], set_position.inputs["Geometry"])
    links.new(offset.outputs[0], set_position.inputs["Offset"])
    links.new(set_position.outputs["Geometry"], out.inputs["Geometry"])
    group["fbp_quality_contract_version"] = 1
    return group


def _create_paper_curl(name):
    """Create a lightweight edge-curl deformation for paper and cut-out planes."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Subdivision", "INPUT", "NodeSocketInt", default=4, minimum=0, maximum=7)
    _socket(group, "Edge", "INPUT", "NodeSocketFloat", default=3.0, minimum=0.0, maximum=3.0)
    _socket(group, "Progress", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Curl Angle", "INPUT", "NodeSocketFloat", default=2.35619449, minimum=0.0, maximum=6.28318531)
    _socket(group, "Curl Radius", "INPUT", "NodeSocketFloat", default=0.15, minimum=0.0, maximum=10.0)
    _socket(group, "Curl Width", "INPUT", "NodeSocketFloat", default=0.28, minimum=0.001, maximum=1.0)
    _socket(group, "Lift", "INPUT", "NodeSocketFloat", default=0.02, minimum=-10.0, maximum=10.0)
    _socket(group, "Reverse", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    subdivide = _node(group, "GeometryNodeSubdivideMesh", "Paper Curl Subdivision", -1540, 300)
    bounds = _node(group, "GeometryNodeBoundBox", "Paper Bounds", -1340, 40)
    position = _node(group, "GeometryNodeInputPosition", "Paper Position", -1340, -180)
    pos_xyz = _node(group, "ShaderNodeSeparateXYZ", "Paper Position Axes", -1150, -180)
    min_xyz = _node(group, "ShaderNodeSeparateXYZ", "Paper Minimum Axes", -1150, 120)
    max_xyz = _node(group, "ShaderNodeSeparateXYZ", "Paper Maximum Axes", -1150, 260)
    links.new(inp.outputs["Geometry"], subdivide.inputs["Mesh"])
    links.new(inp.outputs["Subdivision"], subdivide.inputs["Level"])
    links.new(subdivide.outputs["Mesh"], bounds.inputs["Geometry"])
    links.new(position.outputs["Position"], pos_xyz.inputs[0])
    links.new(bounds.outputs["Min"], min_xyz.inputs[0])
    links.new(bounds.outputs["Max"], max_xyz.inputs[0])

    def normalized_axis(axis, y):
        size = _math(group, "SUBTRACT", f"Paper {axis} Size", -960, y)
        safe = _math(group, "MAXIMUM", f"Paper Safe {axis}", -790, y, value_2=0.000001)
        relative = _math(group, "SUBTRACT", f"Paper {axis} Relative", -960, y - 90)
        normalized = _math(group, "DIVIDE", f"Paper Normalized {axis}", -610, y - 40)
        links.new(max_xyz.outputs[axis], size.inputs[0])
        links.new(min_xyz.outputs[axis], size.inputs[1])
        links.new(size.outputs[0], safe.inputs[0])
        links.new(pos_xyz.outputs[axis], relative.inputs[0])
        links.new(min_xyz.outputs[axis], relative.inputs[1])
        links.new(relative.outputs[0], normalized.inputs[0])
        links.new(safe.outputs[0], normalized.inputs[1])
        return normalized.outputs[0]

    norm_x = normalized_axis("X", 230)
    norm_y = normalized_axis("Y", -40)
    inv_x = _math(group, "SUBTRACT", "Paper Inverse X", -420, 180, value_1=1.0)
    inv_y = _math(group, "SUBTRACT", "Paper Inverse Y", -420, -40, value_1=1.0)
    links.new(norm_x, inv_x.inputs[1])
    links.new(norm_y, inv_y.inputs[1])

    after_left = _math(group, "GREATER_THAN", "Paper Edge After Left", -520, 470, value_2=0.5)
    before_bottom = _math(group, "LESS_THAN", "Paper Edge Before Bottom", -520, 390, value_2=1.5)
    is_right = _math(group, "MULTIPLY", "Paper Right Edge", -330, 450)
    is_vertical = _math(group, "GREATER_THAN", "Paper Vertical Edge", -420, 320, value_2=1.5)
    is_top = _math(group, "GREATER_THAN", "Paper Top Edge", -420, 250, value_2=2.5)
    negative_edge = _math(group, "ADD", "Paper Negative Edge", -180, 360)
    links.new(inp.outputs["Edge"], after_left.inputs[0])
    links.new(inp.outputs["Edge"], before_bottom.inputs[0])
    links.new(after_left.outputs[0], is_right.inputs[0])
    links.new(before_bottom.outputs[0], is_right.inputs[1])
    links.new(inp.outputs["Edge"], is_vertical.inputs[0])
    links.new(inp.outputs["Edge"], is_top.inputs[0])
    links.new(is_right.outputs[0], negative_edge.inputs[0])
    links.new(is_top.outputs[0], negative_edge.inputs[1])

    horizontal_distance = _node(group, "GeometryNodeSwitch", "Paper Horizontal Distance", -190, 200)
    horizontal_distance.input_type = "FLOAT"
    vertical_distance = _node(group, "GeometryNodeSwitch", "Paper Vertical Distance", -190, -20)
    vertical_distance.input_type = "FLOAT"
    edge_distance = _node(group, "GeometryNodeSwitch", "Paper Edge Distance", 40, 100)
    edge_distance.input_type = "FLOAT"
    links.new(is_right.outputs[0], horizontal_distance.inputs["Switch"])
    links.new(norm_x, horizontal_distance.inputs["False"])
    links.new(inv_x.outputs[0], horizontal_distance.inputs["True"])
    links.new(is_top.outputs[0], vertical_distance.inputs["Switch"])
    links.new(norm_y, vertical_distance.inputs["False"])
    links.new(inv_y.outputs[0], vertical_distance.inputs["True"])
    links.new(is_vertical.outputs[0], edge_distance.inputs["Switch"])
    links.new(horizontal_distance.outputs["Output"], edge_distance.inputs["False"])
    links.new(vertical_distance.outputs["Output"], edge_distance.inputs["True"])

    safe_width = _math(group, "MAXIMUM", "Paper Safe Curl Width", 40, -180, value_2=0.001)
    reveal = _math(group, "SUBTRACT", "Paper Curl Reveal", 240, 100)
    normalized_reveal = _math(group, "DIVIDE", "Paper Curl Normalize", 420, 100)
    clamp_low = _math(group, "MAXIMUM", "Paper Curl Clamp Low", 600, 100, value_2=0.0)
    clamp_high = _math(group, "MINIMUM", "Paper Curl Clamp High", 780, 100, value_2=1.0)
    half_pi = _math(group, "MULTIPLY", "Paper Curl Half Pi", 960, 100, value_2=1.5707963267948966)
    profile = _math(group, "SINE", "Paper Curl Profile", 1140, 100)
    links.new(inp.outputs["Curl Width"], safe_width.inputs[0])
    links.new(inp.outputs["Progress"], reveal.inputs[0])
    links.new(edge_distance.outputs["Output"], reveal.inputs[1])
    links.new(reveal.outputs[0], normalized_reveal.inputs[0])
    links.new(safe_width.outputs[0], normalized_reveal.inputs[1])
    links.new(normalized_reveal.outputs[0], clamp_low.inputs[0])
    links.new(clamp_low.outputs[0], clamp_high.inputs[0])
    links.new(clamp_high.outputs[0], half_pi.inputs[0])
    links.new(half_pi.outputs[0], profile.inputs[0])

    angle = _math(group, "MULTIPLY", "Paper Curl Angle", 1320, 100)
    sine = _math(group, "SINE", "Paper Curl Sine", 1500, 180)
    cosine = _math(group, "COSINE", "Paper Curl Cosine", 1500, 20)
    one_minus_cos = _math(group, "SUBTRACT", "Paper Curl Height Profile", 1680, 20, value_1=1.0)
    axis_amount = _math(group, "MULTIPLY", "Paper Curl Axis Radius", 1680, 180)
    axis_scale = _math(group, "MULTIPLY", "Paper Curl Axis Scale", 1860, 180, value_2=0.35)
    height = _math(group, "MULTIPLY", "Paper Curl Height", 1860, 20)
    lift = _math(group, "MULTIPLY", "Paper Curl Lift", 1680, -140)
    height_lift = _math(group, "ADD", "Paper Curl Height and Lift", 2040, -20)
    links.new(profile.outputs[0], angle.inputs[0])
    links.new(inp.outputs["Curl Angle"], angle.inputs[1])
    links.new(angle.outputs[0], sine.inputs[0])
    links.new(angle.outputs[0], cosine.inputs[0])
    links.new(cosine.outputs[0], one_minus_cos.inputs[1])
    links.new(sine.outputs[0], axis_amount.inputs[0])
    links.new(inp.outputs["Curl Radius"], axis_amount.inputs[1])
    links.new(axis_amount.outputs[0], axis_scale.inputs[0])
    links.new(one_minus_cos.outputs[0], height.inputs[0])
    links.new(inp.outputs["Curl Radius"], height.inputs[1])
    links.new(profile.outputs[0], lift.inputs[0])
    links.new(inp.outputs["Lift"], lift.inputs[1])
    links.new(height.outputs[0], height_lift.inputs[0])
    links.new(lift.outputs[0], height_lift.inputs[1])

    reverse_double = _math(group, "MULTIPLY", "Paper Reverse Double", 1680, -300, value_2=2.0)
    surface_sign = _math(group, "SUBTRACT", "Paper Surface Sign", 1860, -300, value_1=1.0)
    signed_height = _math(group, "MULTIPLY", "Paper Signed Height", 2220, -20)
    links.new(inp.outputs["Reverse"], reverse_double.inputs[0])
    links.new(reverse_double.outputs[0], surface_sign.inputs[1])
    links.new(height_lift.outputs[0], signed_height.inputs[0])
    links.new(surface_sign.outputs[0], signed_height.inputs[1])

    axis_sign = _node(group, "GeometryNodeSwitch", "Paper Edge Direction", 1500, 360)
    axis_sign.input_type = "FLOAT"
    axis_sign.inputs["False"].default_value = 1.0
    axis_sign.inputs["True"].default_value = -1.0
    links.new(negative_edge.outputs[0], axis_sign.inputs["Switch"])
    signed_axis = _math(group, "MULTIPLY", "Paper Signed Axis", 2040, 180)
    links.new(axis_scale.outputs[0], signed_axis.inputs[0])
    links.new(axis_sign.outputs["Output"], signed_axis.inputs[1])

    horizontal_mask = _math(group, "SUBTRACT", "Paper Horizontal Mask", 1680, 500, value_1=1.0)
    x_offset = _math(group, "MULTIPLY", "Paper X Offset", 2220, 220)
    y_offset = _math(group, "MULTIPLY", "Paper Y Offset", 2220, 120)
    links.new(is_vertical.outputs[0], horizontal_mask.inputs[1])
    links.new(signed_axis.outputs[0], x_offset.inputs[0])
    links.new(horizontal_mask.outputs[0], x_offset.inputs[1])
    links.new(signed_axis.outputs[0], y_offset.inputs[0])
    links.new(is_vertical.outputs[0], y_offset.inputs[1])

    offset = _node(group, "ShaderNodeCombineXYZ", "Paper Curl Offset", 2420, 100)
    set_position = _node(group, "GeometryNodeSetPosition", "Paper Curl", 2620, 260)
    links.new(x_offset.outputs[0], offset.inputs["X"])
    links.new(y_offset.outputs[0], offset.inputs["Y"])
    links.new(signed_height.outputs[0], offset.inputs["Z"])
    links.new(subdivide.outputs["Mesh"], set_position.inputs["Geometry"])
    links.new(offset.outputs[0], set_position.inputs["Offset"])
    links.new(set_position.outputs["Geometry"], out.inputs["Geometry"])
    group["fbp_quality_contract_version"] = 1
    group["fbp_paper_curl_version"] = 1
    return group


def _create_cutout_outline(name):
    """Generate an alpha-derived outline while preserving the source plane."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Alpha Resolution", "INPUT", "NodeSocketInt", default=4, minimum=0, maximum=8)
    _socket(group, "Alpha Threshold", "INPUT", "NodeSocketFloat", default=0.05, minimum=0.0, maximum=1.0)
    _socket(group, "Outline Width", "INPUT", "NodeSocketFloat", default=0.012, minimum=0.00001, maximum=10.0)
    _socket(group, "Offset", "INPUT", "NodeSocketFloat", default=0.001, minimum=-10.0, maximum=10.0)
    _socket(group, "Outline Material", "INPUT", "NodeSocketMaterial")
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    masked_geometry, _image_texture = _alpha_geometry_mask(
        group, inp, prefix="Cutout Alpha", x=-1500, y=280
    )
    edge_neighbors = _node(group, "GeometryNodeInputMeshEdgeNeighbors", "Cutout Edge Neighbors", -500, -40)
    boundary = _math(group, "COMPARE", "Cutout Boundary Edges", -280, -20, value_2=1.0)
    # Blender 5.1 exposes equality through COMPARE with an epsilon input.
    if len(boundary.inputs) > 2:
        boundary.inputs[2].default_value = 0.1
    mesh_to_curve = _node(group, "GeometryNodeMeshToCurve", "Cutout Boundary Curve", -60, 240)
    set_radius = _node(group, "GeometryNodeSetCurveRadius", "Cutout Outline Width", 180, 240)

    profile = _node(group, "GeometryNodeCurvePrimitiveCircle", "Cutout Outline Profile", 140, -180)
    try:
        profile.mode = "RADIUS"
    except (AttributeError, TypeError, ValueError):
        pass
    profile_resolution = _input(profile, "Resolution")
    if profile_resolution is not None:
        profile_resolution.default_value = 6
    profile_radius = _input(profile, "Radius")
    if profile_radius is not None:
        profile_radius.default_value = 1.0

    curve_to_mesh = _node(group, "GeometryNodeCurveToMesh", "Cutout Outline Mesh", 440, 220)
    set_material = _node(group, "GeometryNodeSetMaterial", "Cutout Outline Material", 680, 220)
    offset_vector = _node(group, "ShaderNodeCombineXYZ", "Cutout Outline Offset", 680, -60)
    set_position = _node(group, "GeometryNodeSetPosition", "Offset Cutout Outline", 920, 220)
    join = _node(group, "GeometryNodeJoinGeometry", "Join Plane and Outline", 1180, 240)

    links.new(_output(edge_neighbors, "Face Count", 0), boundary.inputs[0])
    links.new(masked_geometry, mesh_to_curve.inputs["Mesh"])
    links.new(boundary.outputs[0], mesh_to_curve.inputs["Selection"])
    links.new(mesh_to_curve.outputs["Curve"], set_radius.inputs["Curve"])
    links.new(inp.outputs["Outline Width"], set_radius.inputs["Radius"])
    links.new(set_radius.outputs["Curve"], curve_to_mesh.inputs["Curve"])
    links.new(profile.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])
    links.new(curve_to_mesh.outputs["Mesh"], set_material.inputs["Geometry"])
    links.new(inp.outputs["Outline Material"], set_material.inputs["Material"])
    links.new(inp.outputs["Offset"], offset_vector.inputs["Z"])
    links.new(set_material.outputs["Geometry"], set_position.inputs["Geometry"])
    links.new(offset_vector.outputs[0], set_position.inputs["Offset"])
    links.new(inp.outputs["Geometry"], join.inputs["Geometry"])
    links.new(set_position.outputs["Geometry"], join.inputs["Geometry"])
    links.new(join.outputs["Geometry"], out.inputs["Geometry"])

    group["fbp_quality_contract_version"] = 1
    group["fbp_alpha_geometry_contract_version"] = 1
    group["fbp_cutout_outline_version"] = 2
    return group



def _alpha_geometry_pixel_grid(group, group_input, *, prefix="Alpha Pixels", x=-1700, y=300):
    """Create an exact X-by-Y alpha sampling grid for pixel-defined cutouts."""
    links = group.links
    bounds = _node(group, "GeometryNodeBoundBox", f"{prefix} Bounds", x, y + 240)
    size = _vector_math(group, "SUBTRACT", f"{prefix} Size", x + 220, y + 240)
    size_xyz = _node(group, "ShaderNodeSeparateXYZ", f"{prefix} Size Axes", x + 430, y + 240)
    plus_x = _math(group, "ADD", f"{prefix} Vertices X", x + 220, y - 20, value_2=1.0)
    plus_y = _math(group, "ADD", f"{prefix} Vertices Y", x + 220, y - 150, value_2=1.0)
    grid = _node(group, "GeometryNodeMeshGrid", f"{prefix} Grid", x + 650, y + 100)
    store_uv = _node(
        group,
        "GeometryNodeStoreNamedAttribute",
        f"{prefix} Store UVMap",
        x + 880,
        y + 150,
    )
    try:
        # Keep this as a real UV attribute. Using FLOAT_VECTOR changes the
        # existing plane UVMap from FLOAT2 to a generic 3D vector when the
        # branches are joined, so image materials sample the transparent edge.
        store_uv.data_type = "FLOAT2"
        store_uv.domain = "CORNER"
    except (AttributeError, TypeError, ValueError):
        pass
    uv_name = _input(store_uv, "Name")
    if uv_name is not None:
        uv_name.default_value = "UVMap"
    image_texture = _node(group, "GeometryNodeImageTexture", f"{prefix} Image", x + 880, y - 250)
    image_texture["fbp_alpha_image_node"] = True
    try:
        image_texture.extension = "EXTEND"
        image_texture.interpolation = "Linear"
    except (AttributeError, TypeError, ValueError):
        pass
    transparent = _math(group, "LESS_THAN", f"{prefix} Transparent", x + 1110, y - 170)
    delete = _node(group, "GeometryNodeDeleteGeometry", f"{prefix} Delete Transparent", x + 1330, y + 80)
    try:
        delete.domain = "FACE"
    except (AttributeError, TypeError, ValueError):
        pass

    links.new(group_input.outputs["Geometry"], bounds.inputs["Geometry"])
    links.new(bounds.outputs["Max"], size.inputs[0])
    links.new(bounds.outputs["Min"], size.inputs[1])
    links.new(size.outputs[0], size_xyz.inputs[0])
    links.new(size_xyz.outputs["X"], grid.inputs["Size X"])
    links.new(size_xyz.outputs["Y"], grid.inputs["Size Y"])
    links.new(group_input.outputs["Pixels X"], plus_x.inputs[0])
    links.new(group_input.outputs["Pixels Y"], plus_y.inputs[0])
    links.new(plus_x.outputs[0], grid.inputs["Vertices X"])
    links.new(plus_y.outputs[0], grid.inputs["Vertices Y"])
    links.new(grid.outputs["UV Map"], image_texture.inputs["Vector"])
    links.new(image_texture.outputs["Alpha"], transparent.inputs[0])
    links.new(group_input.outputs["Alpha Threshold"], transparent.inputs[1])
    links.new(grid.outputs["Mesh"], store_uv.inputs["Geometry"])
    links.new(grid.outputs["UV Map"], store_uv.inputs["Value"])
    links.new(store_uv.outputs["Geometry"], delete.inputs["Geometry"])
    links.new(transparent.outputs[0], delete.inputs["Selection"])
    return delete.outputs["Geometry"], image_texture

def _create_extrude(name):
    """Build a textured two-cap volume with alpha-derived side walls."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Pixels X", "INPUT", "NodeSocketInt", default=128, minimum=1, maximum=4096)
    _socket(group, "Pixels Y", "INPUT", "NodeSocketInt", default=128, minimum=1, maximum=4096)
    _socket(group, "Alpha Threshold", "INPUT", "NodeSocketFloat", default=0.05, minimum=0.0, maximum=1.0)
    _socket(group, "Use Alpha Mask", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Thickness", "INPUT", "NodeSocketFloat", default=0.04, minimum=0.0, maximum=10.0)
    _socket(group, "Direction", "INPUT", "NodeSocketFloat", default=-1.0, minimum=-1.0, maximum=1.0)
    _socket(group, "Side Material", "INPUT", "NodeSocketMaterial")
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    # Build the alpha silhouette only for the walls. Front and back are copied
    # from the actual input plane so its native UV map, animated material and
    # previous geometry effects remain untouched.
    masked_geometry, _image_texture = _alpha_geometry_pixel_grid(
        group, inp, prefix="Extrude Alpha Pixels", x=-2300, y=260
    )
    alpha_size = _node(group, "GeometryNodeAttributeDomainSize", "Alpha Cutout Size", -1080, 40)
    alpha_has_faces = _math(group, "GREATER_THAN", "Alpha Cutout Has Faces", -860, 20, value_2=0.0)
    use_alpha_cutout = _node(group, "FunctionNodeBooleanMath", "Use Valid Alpha Cutout", -650, 60)
    try:
        use_alpha_cutout.operation = "AND"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(masked_geometry, alpha_size.inputs["Geometry"])
    links.new(_output(alpha_size, "Face Count", 2), alpha_has_faces.inputs[0])
    links.new(inp.outputs["Use Alpha Mask"], use_alpha_cutout.inputs[0])
    links.new(alpha_has_faces.outputs[0], use_alpha_cutout.inputs[1])

    wall_source = _node(group, "GeometryNodeSwitch", "Wall Source", -430, 260)
    try:
        wall_source.input_type = "GEOMETRY"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(use_alpha_cutout.outputs[0], _input(wall_source, "Switch", 0))
    links.new(inp.outputs["Geometry"], _input(wall_source, "False", 1))
    links.new(masked_geometry, _input(wall_source, "True", 2))

    signed_thickness = _math(group, "MULTIPLY", "Signed Thickness", -650, -190)
    offset = _node(group, "ShaderNodeCombineXYZ", "Extrusion Offset", -430, -190)
    links.new(inp.outputs["Thickness"], signed_thickness.inputs[0])
    links.new(inp.outputs["Direction"], signed_thickness.inputs[1])
    links.new(signed_thickness.outputs[0], offset.inputs["Z"])

    # Move a real copy of the source plane for the opposite cap. This avoids
    # relying on generated-cap UV propagation, which made both textured caps
    # disappear on some Blender 5.1 configurations.
    move_back = _node(group, "GeometryNodeTransform", "Move Back Cap", -80, 520)
    links.new(inp.outputs["Geometry"], move_back.inputs["Geometry"])
    links.new(offset.outputs[0], move_back.inputs["Translation"])

    # Keep cap normals outward for both extrusion directions.
    direction_positive = _math(group, "GREATER_THAN", "Direction Is Positive", -200, -310, value_2=0.0)
    links.new(inp.outputs["Direction"], direction_positive.inputs[0])

    flip_front = _node(group, "GeometryNodeFlipFaces", "Flip Front Cap", 160, 680)
    flip_back = _node(group, "GeometryNodeFlipFaces", "Flip Back Cap", 160, 430)
    links.new(inp.outputs["Geometry"], flip_front.inputs["Mesh"])
    links.new(move_back.outputs["Geometry"], flip_back.inputs["Mesh"])

    front_switch = _node(group, "GeometryNodeSwitch", "Front Cap Direction", 400, 680)
    back_switch = _node(group, "GeometryNodeSwitch", "Back Cap Direction", 400, 430)
    for node in (front_switch, back_switch):
        try:
            node.input_type = "GEOMETRY"
        except (AttributeError, TypeError, ValueError):
            pass
    links.new(direction_positive.outputs[0], _input(front_switch, "Switch", 0))
    links.new(inp.outputs["Geometry"], _input(front_switch, "False", 1))
    links.new(flip_front.outputs["Mesh"], _input(front_switch, "True", 2))
    links.new(direction_positive.outputs[0], _input(back_switch, "Switch", 0))
    links.new(flip_back.outputs["Mesh"], _input(back_switch, "False", 1))
    links.new(move_back.outputs["Geometry"], _input(back_switch, "True", 2))

    # Extrude only to obtain boundary walls. The generated top and source faces
    # are discarded because the real plane copies above are more reliable and
    # retain the exact animated texture setup.
    extrude = _node(group, "GeometryNodeExtrudeMesh", "Extrude Side Walls", -80, 120)
    try:
        extrude.mode = "FACES"
    except (AttributeError, TypeError, ValueError):
        pass
    individual = _input(extrude, "Individual")
    if individual is not None:
        individual.default_value = False
    links.new(_output(wall_source, "Output", 0), extrude.inputs["Mesh"])
    links.new(offset.outputs[0], extrude.inputs["Offset"])

    separate_sides = _node(group, "GeometryNodeSeparateGeometry", "Keep Side Walls", 180, 110)
    try:
        separate_sides.domain = "FACE"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(extrude.outputs["Mesh"], separate_sides.inputs["Geometry"])
    links.new(extrude.outputs["Side"], separate_sides.inputs["Selection"])

    set_side_material = _node(group, "GeometryNodeSetMaterial", "Material on Sides", 420, 120)
    links.new(separate_sides.outputs["Selection"], set_side_material.inputs["Geometry"])
    links.new(inp.outputs["Side Material"], set_side_material.inputs["Material"])

    join_volume = _node(group, "GeometryNodeJoinGeometry", "Extrude Volume", 760, 420)
    links.new(_output(front_switch, "Output", 0), join_volume.inputs["Geometry"])
    links.new(_output(back_switch, "Output", 0), join_volume.inputs["Geometry"])
    links.new(set_side_material.outputs["Geometry"], join_volume.inputs["Geometry"])
    links.new(join_volume.outputs["Geometry"], out.inputs["Geometry"])

    group["fbp_quality_contract_version"] = 1
    group["fbp_alpha_geometry_contract_version"] = 3
    group["fbp_extrude_version"] = 7
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
    # Geometry node trees cannot contain ShaderNodeVectorTransform in Blender
    # 5.1.  Build the equivalent world-to-object direction conversion from the
    # modifier object's inverse transform matrix.
    self_object = _node(group, "GeometryNodeSelfObject", "Wind Modifier Object", 2700, -760)
    object_info = _node(group, "GeometryNodeObjectInfo", "Wind Object Transform", 2890, -760)
    inverse_transform = _node(group, "FunctionNodeInvertMatrix", "World To Object Transform", 3090, -760)
    world_transform = _node(group, "FunctionNodeTransformDirection", "World Wind To Object", 3290, -650)
    world_offset = _vector_math(group, "SCALE", "World Wind Offset", 3490, -600)
    direction_switch = _node(group, "GeometryNodeSwitch", "Wind Direction Space", 3690, -470)
    direction_switch.input_type = "VECTOR"
    set_position = _node(group, "GeometryNodeSetPosition", "Wind Deformation", 3890, 220)
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
    links.new(self_object.outputs["Self Object"], object_info.inputs["Object"])
    links.new(object_info.outputs["Transform"], inverse_transform.inputs["Matrix"])
    links.new(inp.outputs["Wind Direction"], world_transform.inputs["Direction"])
    links.new(inverse_transform.outputs["Matrix"], world_transform.inputs["Transform"])
    links.new(world_transform.outputs["Direction"], world_offset.inputs[0])
    links.new(motion_switch.outputs["Output"], world_offset.inputs[3])
    links.new(inp.outputs["Direction Space"], direction_switch.inputs["Switch"])
    links.new(local_offset.outputs[0], direction_switch.inputs["False"])
    links.new(world_offset.outputs[0], direction_switch.inputs["True"])
    links.new(subdivide.outputs["Mesh"], set_position.inputs["Geometry"])
    links.new(direction_switch.outputs["Output"], set_position.inputs["Offset"])
    links.new(set_position.outputs["Geometry"], out.inputs["Geometry"])
    return group



def _camera_space_vectors(group, camera_socket, *, prefix="Camera Space", x=-900, y=200):
    """Return camera location and normalized view direction in modifier-object space.

    Object Info in RELATIVE space makes the result independent from the plane
    object's world transform and provides a reusable contract for camera-aware
    Geometry Nodes effects.
    """
    camera_info = _node(group, "GeometryNodeObjectInfo", f"{prefix} Transform", x, y)
    try:
        camera_info.transform_space = "RELATIVE"
    except (AttributeError, TypeError, ValueError):
        pass
    group.links.new(camera_socket, camera_info.inputs["Object"])
    direction = _vector_math(group, "NORMALIZE", f"{prefix} Direction", x + 220, y)
    group.links.new(camera_info.outputs["Location"], direction.inputs[0])
    return camera_info.outputs["Location"], direction.outputs[0]


def _create_camera_billboard(name):
    """Rotate plane geometry toward the active camera without rotating its rig."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Camera", "INPUT", "NodeSocketObject")
    _socket(group, "Facing Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Flip", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Offset", "INPUT", "NodeSocketFloat", default=0.0, minimum=-10000.0, maximum=10000.0)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    camera_location, full_direction = _camera_space_vectors(
        group, inp.outputs["Camera"], prefix="Billboard Camera", x=-1100, y=260
    )
    separate = _node(group, "ShaderNodeSeparateXYZ", "Billboard Direction Components", -820, 40)
    links.new(camera_location, separate.inputs[0])

    horizontal = _node(group, "ShaderNodeCombineXYZ", "Horizontal Facing Vector", -600, 80)
    links.new(separate.outputs["X"], horizontal.inputs["X"])
    horizontal.inputs["Y"].default_value = 0.0
    links.new(separate.outputs["Z"], horizontal.inputs["Z"])
    horizontal_normalize = _vector_math(group, "NORMALIZE", "Normalized Horizontal Facing", -380, 80)
    links.new(horizontal.outputs[0], horizontal_normalize.inputs[0])

    vertical = _node(group, "ShaderNodeCombineXYZ", "Vertical Facing Vector", -600, -100)
    vertical.inputs["X"].default_value = 0.0
    links.new(separate.outputs["Y"], vertical.inputs["Y"])
    links.new(separate.outputs["Z"], vertical.inputs["Z"])
    vertical_normalize = _vector_math(group, "NORMALIZE", "Normalized Vertical Facing", -380, -100)
    links.new(vertical.outputs[0], vertical_normalize.inputs[0])

    mode_horizontal = _math(group, "COMPARE", "Billboard Horizontal Mode", -380, -280, value_2=1.0)
    mode_vertical = _math(group, "COMPARE", "Billboard Vertical Mode", -380, -400, value_2=2.0)
    try:
        mode_horizontal.inputs[2].default_value = 0.1
        mode_vertical.inputs[2].default_value = 0.1
    except (AttributeError, IndexError, TypeError, ValueError):
        pass
    links.new(inp.outputs["Facing Mode"], mode_horizontal.inputs[0])
    links.new(inp.outputs["Facing Mode"], mode_vertical.inputs[0])

    horizontal_switch = _node(group, "GeometryNodeSwitch", "Choose Horizontal Facing", -120, 120)
    horizontal_switch.input_type = "VECTOR"
    links.new(mode_horizontal.outputs[0], horizontal_switch.inputs["Switch"])
    links.new(full_direction, horizontal_switch.inputs["False"])
    links.new(horizontal_normalize.outputs[0], horizontal_switch.inputs["True"])
    vertical_switch = _node(group, "GeometryNodeSwitch", "Choose Vertical Facing", 100, 120)
    vertical_switch.input_type = "VECTOR"
    links.new(mode_vertical.outputs[0], vertical_switch.inputs["Switch"])
    links.new(horizontal_switch.outputs["Output"], vertical_switch.inputs["False"])
    links.new(vertical_normalize.outputs[0], vertical_switch.inputs["True"])

    flip_scale = _math(group, "MULTIPLY", "Billboard Flip Double", 100, -120, value_2=2.0)
    flip_sign = _math(group, "SUBTRACT", "Billboard Flip Sign", 300, -120, value_1=1.0)
    links.new(inp.outputs["Flip"], flip_scale.inputs[0])
    links.new(flip_scale.outputs[0], flip_sign.inputs[1])
    signed_direction = _vector_math(group, "SCALE", "Signed Billboard Direction", 340, 120)
    links.new(vertical_switch.outputs["Output"], signed_direction.inputs[0])
    links.new(flip_sign.outputs[0], signed_direction.inputs[3])

    # A camera can temporarily overlap the plane origin while editing, during
    # Undo or while switching cameras. Feeding a zero vector to Align Euler can
    # produce undefined rotations or sudden flips, so keep the current plane
    # orientation with a stable local +Z fallback until a valid direction exists.
    direction_length = _vector_math(group, "LENGTH", "Billboard Direction Length", 520, -180)
    links.new(signed_direction.outputs[0], direction_length.inputs[0])
    valid_direction = _math(group, "GREATER_THAN", "Valid Billboard Direction", 700, -180, value_2=0.000001)
    links.new(direction_length.outputs[1] if len(direction_length.outputs) > 1 else direction_length.outputs[0], valid_direction.inputs[0])
    stable_direction = _node(group, "GeometryNodeSwitch", "Stable Billboard Direction", 760, 100)
    stable_direction.input_type = "VECTOR"
    stable_direction.inputs["False"].default_value = (0.0, 0.0, 1.0)
    links.new(valid_direction.outputs[0], stable_direction.inputs["Switch"])
    links.new(signed_direction.outputs[0], stable_direction.inputs["True"])

    align = _node(group, "FunctionNodeAlignEulerToVector", "Align Plane Z to Camera", 980, 180)
    try:
        align.axis = "Z"
        # Y is the visual up axis of FBP planes. Using an explicit pivot avoids
        # the roll ambiguity of AUTO for most camera moves and horizontal mode.
        align.pivot_axis = "Y"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(stable_direction.outputs["Output"], align.inputs["Vector"])

    offset_vector = _vector_math(group, "SCALE", "Billboard Camera Offset", 980, -40)
    links.new(stable_direction.outputs["Output"], offset_vector.inputs[0])
    links.new(inp.outputs["Offset"], offset_vector.inputs[3])
    set_position = _node(group, "GeometryNodeSetPosition", "Billboard Offset", 1220, 60)
    links.new(inp.outputs["Geometry"], set_position.inputs["Geometry"])
    links.new(offset_vector.outputs[0], set_position.inputs["Offset"])
    transform = _node(group, "GeometryNodeTransform", "Camera Billboard", 1460, 160)
    links.new(set_position.outputs["Geometry"], transform.inputs["Geometry"])
    links.new(align.outputs["Rotation"], transform.inputs["Rotation"])
    links.new(transform.outputs["Geometry"], out.inputs["Geometry"])

    group["fbp_camera_contract_version"] = 3
    group["fbp_camera_space_contract_version"] = 1
    group["fbp_camera_billboard_version"] = 2
    return group

def _create_camera_scale_lock(name):
    """Keep a plane's apparent size stable as camera projection changes."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Camera", "INPUT", "NodeSocketObject")
    _socket(group, "Camera Lens", "INPUT", "NodeSocketFloat", default=50.0, minimum=0.1, maximum=10000.0)
    _socket(group, "Camera Sensor Width", "INPUT", "NodeSocketFloat", default=36.0, minimum=0.1, maximum=1000.0)
    _socket(group, "Camera Ortho Scale", "INPUT", "NodeSocketFloat", default=6.0, minimum=0.0001, maximum=100000.0)
    _socket(group, "Perspective", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Camera Shift X", "INPUT", "NodeSocketFloat", default=0.0, minimum=-10.0, maximum=10.0)
    _socket(group, "Camera Shift Y", "INPUT", "NodeSocketFloat", default=0.0, minimum=-10.0, maximum=10.0)
    _socket(group, "Reference Distance", "INPUT", "NodeSocketFloat", default=10.0, minimum=0.0001, maximum=1000000.0)
    _socket(group, "Reference Lens", "INPUT", "NodeSocketFloat", default=50.0, minimum=0.1, maximum=10000.0)
    _socket(group, "Reference Sensor Width", "INPUT", "NodeSocketFloat", default=36.0, minimum=0.1, maximum=1000.0)
    _socket(group, "Influence", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    camera_info = _node(group, "GeometryNodeObjectInfo", "Camera Transform", -760, 160)
    self_object = _node(group, "GeometryNodeSelfObject", "Effect Object", -760, -40)
    self_info = _node(group, "GeometryNodeObjectInfo", "Effect Object Transform", -560, -40)
    camera_vector = _vector_math(group, "SUBTRACT", "Camera to Plane", -360, 180)
    camera_forward = _node(group, "ShaderNodeVectorRotate", "Camera Forward", -360, -20)
    camera_forward.rotation_type = "EULER_XYZ"
    camera_forward.invert = False
    camera_forward.inputs["Vector"].default_value = (0.0, 0.0, -1.0)
    camera_forward.inputs["Center"].default_value = (0.0, 0.0, 0.0)
    camera_depth = _vector_math(group, "DOT_PRODUCT", "Camera Space Depth", -160, 160)
    safe_depth = _math(group, "MAXIMUM", "Safe Camera Depth", 20, 160, value_2=0.0001)
    safe_reference = _math(group, "MAXIMUM", "Safe Reference Depth", 20, -40, value_2=0.0001)
    distance_ratio = _math(group, "DIVIDE", "Depth Ratio", 220, 160)
    safe_lens = _math(group, "MAXIMUM", "Safe Camera Lens", 40, 20, value_2=0.001)
    lens_ratio = _math(group, "DIVIDE", "Lens Ratio", 220, 20)
    safe_reference_sensor = _math(group, "MAXIMUM", "Safe Reference Sensor", 40, -140, value_2=0.001)
    sensor_ratio = _math(group, "DIVIDE", "Sensor Ratio", 220, -140)
    distance_lens = _math(group, "MULTIPLY", "Distance and Lens", 400, 120)
    projection_ratio = _math(group, "MULTIPLY", "Projection Ratio", 580, 120)
    ratio_delta = _math(group, "SUBTRACT", "Scale Delta", 760, 120, value_2=1.0)
    influence = _math(group, "MULTIPLY", "Influence", 940, 120)
    perspective = _math(group, "MULTIPLY", "Perspective Only", 1120, 120)
    factor = _math(group, "ADD", "Camera Scale Factor", 1300, 120, value_1=1.0)
    safe_factor = _math(group, "MAXIMUM", "Safe Camera Scale", 1480, 120, value_2=0.001)
    scale = _node(group, "ShaderNodeCombineXYZ", "Camera Scale", 1660, 120)
    transform = _node(group, "GeometryNodeTransform", "Camera Scale Lock", 1850, 220)

    links.new(inp.outputs["Camera"], camera_info.inputs["Object"])
    links.new(self_object.outputs[0], self_info.inputs["Object"])
    links.new(self_info.outputs["Location"], camera_vector.inputs[0])
    links.new(camera_info.outputs["Location"], camera_vector.inputs[1])
    links.new(camera_info.outputs["Rotation"], camera_forward.inputs["Rotation"])
    links.new(camera_vector.outputs[0], camera_depth.inputs[0])
    links.new(camera_forward.outputs["Vector"], camera_depth.inputs[1])
    links.new(_output(camera_depth, "Value", 1), safe_depth.inputs[0])
    links.new(inp.outputs["Reference Distance"], safe_reference.inputs[0])
    links.new(safe_depth.outputs[0], distance_ratio.inputs[0])
    links.new(safe_reference.outputs[0], distance_ratio.inputs[1])
    links.new(inp.outputs["Camera Lens"], safe_lens.inputs[0])
    links.new(inp.outputs["Reference Lens"], lens_ratio.inputs[0])
    links.new(safe_lens.outputs[0], lens_ratio.inputs[1])
    links.new(inp.outputs["Reference Sensor Width"], safe_reference_sensor.inputs[0])
    links.new(inp.outputs["Camera Sensor Width"], sensor_ratio.inputs[0])
    links.new(safe_reference_sensor.outputs[0], sensor_ratio.inputs[1])
    links.new(distance_ratio.outputs[0], distance_lens.inputs[0])
    links.new(lens_ratio.outputs[0], distance_lens.inputs[1])
    links.new(distance_lens.outputs[0], projection_ratio.inputs[0])
    links.new(sensor_ratio.outputs[0], projection_ratio.inputs[1])
    links.new(projection_ratio.outputs[0], ratio_delta.inputs[0])
    links.new(ratio_delta.outputs[0], influence.inputs[0])
    links.new(inp.outputs["Influence"], influence.inputs[1])
    links.new(influence.outputs[0], perspective.inputs[0])
    links.new(inp.outputs["Perspective"], perspective.inputs[1])
    links.new(perspective.outputs[0], factor.inputs[1])
    links.new(factor.outputs[0], safe_factor.inputs[0])
    links.new(safe_factor.outputs[0], scale.inputs["X"])
    links.new(safe_factor.outputs[0], scale.inputs["Y"])
    scale.inputs["Z"].default_value = 1.0
    links.new(inp.outputs["Geometry"], transform.inputs["Geometry"])
    links.new(scale.outputs[0], transform.inputs["Scale"])
    links.new(transform.outputs["Geometry"], out.inputs["Geometry"])

    group["fbp_camera_contract_version"] = 2
    return group

def _interface_socket_names(group, in_out):
    """Return interface socket names without depending on one Blender API layout."""
    names = set()
    try:
        items = tuple(group.interface.items_tree)
    except FBP_DATA_ERRORS:
        items = ()
    for item in items:
        try:
            if getattr(item, "item_type", "") != "SOCKET":
                continue
            if getattr(item, "in_out", "") == in_out:
                names.add(str(getattr(item, "name", "") or ""))
        except FBP_DATA_ERRORS:
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
    required_inputs.update(
        str(socket_name or "") for socket_name in definition.get("required_input_sockets", ())
    )
    uv_input = str(definition.get("uv_input_socket", "") or "")
    alpha_input = str(definition.get("alpha_input_socket", "") or "")
    alpha_output = str(definition.get("alpha_output_socket", "") or "")
    mask_output = str(definition.get("mask_output_socket", "") or "")
    debug_input = str(definition.get("debug_socket", "") or "")
    if definition.get("camera_aware"):
        camera_contract = definition.get("camera_contract", {}) or {}
        for socket_key in (
            "object_socket", "lens_socket", "sensor_width_socket",
            "ortho_scale_socket", "perspective_socket",
            "shift_x_socket", "shift_y_socket",
        ):
            socket_name = str(camera_contract.get(socket_key, "") or "")
            if socket_name:
                required_inputs.add(socket_name)
    if debug_input:
        required_inputs.add(debug_input)
    if uv_input:
        required_inputs.add(uv_input)
    if alpha_input:
        required_inputs.add(alpha_input)
    if alpha_output:
        required_outputs.add(alpha_output)
    if mask_output:
        required_outputs.add(mask_output)
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
    if bool(definition.get("requires_alpha_geometry_contract")):
        try:
            if int(group.get("fbp_alpha_geometry_contract_version", 0) or 0) < 1:
                return False
            if not any(bool(node.get("fbp_alpha_image_node", False)) for node in group.nodes):
                return False
        except FBP_DATA_ERRORS:
            return False
    if bool(definition.get("mask_source_aware")):
        try:
            if not any(bool(node.get("fbp_mask_source_image_node", False)) for node in group.nodes):
                return False
        except FBP_DATA_ERRORS:
            return False
    if bool(definition.get("mask_source_transform_aware")):
        try:
            if int(group.get("fbp_track_matte_contract_version", 0) or 0) < 5:
                return False
            if not any(bool(node.get("fbp_mask_source_coord_node", False)) for node in group.nodes):
                return False
        except FBP_DATA_ERRORS:
            return False
    if bool(definition.get("object_mask_aware")):
        try:
            if int(group.get("fbp_object_mask_contract_version", 0) or 0) < 3:
                return False
            if not any(bool(node.get("fbp_object_mask_coord_node", False)) for node in group.nodes):
                return False
            if not any(bool(node.get("fbp_object_mask_image_node", False)) for node in group.nodes):
                return False
        except FBP_DATA_ERRORS:
            return False
    if bool(definition.get("image_aware")):
        try:
            if str(definition.get("kind", "")) == "SHADER":
                if not any(bool(node.get("fbp_matrix_source_image_node", False)) for node in group.nodes):
                    return False
            elif not any(bool(node.get("fbp_alpha_image_node", False)) for node in group.nodes):
                return False
        except FBP_DATA_ERRORS:
            return False
    if str(definition.get("asset_id", "") or "").startswith((
        "frame_by_plane.shader.color_mask",
        "frame_by_plane.shader.gradient_mask",
        "frame_by_plane.shader.noise_mask",
    )):
        try:
            if int(group.get("fbp_generated_mask_contract_version", 0) or 0) < 1:
                return False
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            return False
    if asset_id.startswith("frame_by_plane.shader.ascii"):
        try:
            fill_nodes = [node for node in group.nodes if bool(node.get("fbp_terminal_ascii_fill_node", False))]
            edge_nodes = [node for node in group.nodes if bool(node.get("fbp_terminal_ascii_edge_node", False))]
            if len(fill_nodes) != 1 or len(edge_nodes) != 1:
                return False
            fill_image = getattr(fill_nodes[0], "image", None)
            edge_image = getattr(edge_nodes[0], "image", None)
            if (
                fill_image is None or edge_image is None
                or str(fill_image.get("fbp_terminal_ascii_revision", "") or "") != TERMINAL_ASCII_ASSET_REVISION
                or str(edge_image.get("fbp_terminal_ascii_revision", "") or "") != TERMINAL_ASCII_ASSET_REVISION
                or str(fill_image.get("fbp_terminal_ascii_role", "") or "") != "FILL"
                or str(edge_image.get("fbp_terminal_ascii_role", "") or "") != "EDGES"
            ):
                return False
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            pass
        if existing is not None:
            canonical_name = canonical_name + " Rebuilt"

    builders = {
        "PIXELATE": lambda: _create_pixelate(canonical_name),
        "RECOLOR": lambda: _create_recolor(canonical_name),
        "GRADIENT_LIGHT": lambda: _create_gradient_light(canonical_name),
        "RIM": lambda: _create_rim(canonical_name),
        "DEPTH_BLUR": lambda: _create_depth_blur(canonical_name),
        "ALPHA_MATTE": lambda: _create_alpha_matte(canonical_name),
        "LUMA_MATTE": lambda: _create_luma_matte(canonical_name),
        "CLIPPING_MASK": lambda: _create_alpha_matte(canonical_name),
        "SQUARE_MASK": lambda: _create_object_shape_mask(canonical_name, shape="SQUARE"),
        "CIRCLE_MASK": lambda: _create_object_shape_mask(canonical_name, shape="CIRCLE"),
        "TRIANGLE_MASK": lambda: _create_object_shape_mask(canonical_name, shape="TRIANGLE"),
        "COLOR_MASK": lambda: _create_color_mask(canonical_name),
        "GRADIENT_MASK": lambda: _create_gradient_mask(canonical_name),
        "NOISE_MASK": lambda: _create_noise_mask(canonical_name),
        "DIGITAL_NOISE": lambda: _create_digital_noise(canonical_name),
        "CHROMA_KEY": lambda: _create_chroma_key(canonical_name),
        "HALFTONE": lambda: _create_halftone(canonical_name),
        "DOT_MATRIX": lambda: _create_dot_matrix(canonical_name),
        "ASCII_MATRIX": lambda: _create_ascii_matrix(canonical_name, asset_dir),
        "ASCII": lambda: _create_terminal_ascii(canonical_name, asset_dir),
        "TEXT_MATRIX": lambda: _create_text_matrix(canonical_name),
        "WIND_BENDER": lambda: _create_wind_bender(canonical_name),
        "MESH_RIPPLE": lambda: _create_mesh_ripple(canonical_name),
        "PAPER_CURL": lambda: _create_paper_curl(canonical_name),
        "CUTOUT_OUTLINE": lambda: _create_cutout_outline(canonical_name),
        "THICKNESS": lambda: _create_extrude(canonical_name),
        "CAMERA_SCALE_LOCK": lambda: _create_camera_scale_lock(canonical_name),
        "CAMERA_BILLBOARD": lambda: _create_camera_billboard(canonical_name),
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
            except FBP_DATA_ERRORS:
                continue
        raise
