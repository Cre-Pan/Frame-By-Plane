"""Programmatically generated shader groups for Frame by Plane effects.

These groups are generated from the current Python contracts instead of being
reused from node groups embedded by previous add-on releases.
"""

from pathlib import Path

import bpy

from .runtime import FBP_DATA_ERRORS
from .effect_schema import FBP_EFFECT_SCHEMA_VERSION
from .node_sockets import node_input as _input, node_output as _output

from .matrix_presets import (
    ASCII_ATLAS_CELL_HEIGHT,
    ASCII_ATLAS_CELL_WIDTH,
    ASCII_ATLAS_COLUMNS,
    ASCII_ATLAS_REVISION,
    ASCII_ATLAS_VERSION,
    ASCII_PRESETS,
)


BUILTIN_EFFECT_IDS = {
    "UV_DISTORTION",
    "PIXELATE",
    "SWIRL",
    "BULGE_PINCH",
    "LENS_WARP",
    "WAVE_WARP",
    "RIPPLE_DISTORTION",
    "KALEIDOSCOPE",
    "HEX_PIXELATE",
    "MOSAIC_JITTER",
    "SLICE_SHIFT",
    "RECOLOR",
    "GRADIENT_MAP",
    "CHANNEL_MIXER",
    "DITHER",
    "BLOOM",
    "FILTER_PRESETS",
    "WHITE_BALANCE",
    "CURVES",
    "COLOR_ISOLATE",
    "GRADIENT_LIGHT",
    "RIM",
    "SHADOW",
    "DEPTH_BLUR",
    "GAUSSIAN_BLUR",
    "DIRECTIONAL_BLUR",
    "TRIANGLE_BLUR",
    "TILT_SHIFT",
    "UNSHARP_MASK",
    "EDGE_DETECT",
    "SMOOTH_TOON",
    "ADAPTIVE_THRESHOLD",
    "FALSE_COLOR",
    "CHROMATIC_ABERRATION",
    "INK",
    "EDGE_WORK",
    "PENCIL_SKETCH",
    "POSTER_EDGES",
    "CROSSHATCH",
    "EMBOSS",
    "ALPHA_MATTE",
    "LUMA_MATTE",
    "SQUARE_MASK",
    "CIRCLE_MASK",
    "TRIANGLE_MASK",
    "CLIPPING_MASK",
    "IMPORTED_MASK",
    "GP_MASK_SLOT_2",
    "GP_MASK_SLOT_3",
    "GP_MASK_SLOT_4",
    "LAYER_BLEND",
    "COLOR_MASK",
    "LUMINANCE_MASK",
    "CHANNEL_MASK",
    "GRADIENT_MASK",
    "NOISE_MASK",
    "VORONOI_MASK",
    "WAVE_MASK",
    "DIGITAL_NOISE",
    "CHROMA_KEY",
    "HALFTONE",
    "DOT_MATRIX",
    "ASCII_MATRIX",
    "ASCII",
    "TEXT_MATRIX",
    "WIND_BENDER",
    "CUTOUT_OUTLINE",
    "THICKNESS",
    "FIBER_TUFTS",
    "PAPER_SHARDS",
    "SPHERE_SCREEN",
    "IMAGE_RELIEF",
    "GLASS",
    "CRYSTAL",
    "SURFACE_CONFORM",
    "ACCORDION_FOLD",
    "SCULPT_WAVES",
    "KINETIC_TILES",
    "LAYERED_ECHO",
    "CAMERA_SCALE_LOCK",
    "MIRROR",
    "SOLARIZE",
    "TRITONE",
    "FILM_FADE",
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


def _build_aspect_remesh_nodes(group, geometry_socket, level_socket, *, prefix, x, y, triangulate=True):
    """Build an aspect-balanced planar grid and project it onto the input mesh.

    ``Subdivide Mesh`` creates the same number of cuts on both axes, so a wide
    image produces long rectangular faces. This helper keeps approximately the
    same vertex budget (``2 ** level`` squared), distributes it according to
    the plane aspect ratio, raycasts the source ``UVMap`` onto the new surface
    and optionally emits a Beauty-triangulated surface. Preserving the source
    UVs is essential for FBP Crop / Extend: values outside 0–1 must reach the
    image node unchanged so Edge, Repeat, Mirror and Transparent behave exactly
    like the original plane. A single raycast also preserves upstream planar
    deformation and holes instead of flattening the modifier stack.
    """
    links = group.links
    bounds = _node(group, "GeometryNodeBoundBox", f"{prefix} Remesh Bounds", x, y)
    size = _vector_math(group, "SUBTRACT", f"{prefix} Remesh Size", x + 220, y)
    size_components = _node(group, "ShaderNodeSeparateXYZ", f"{prefix} Remesh Dimensions", x + 440, y)
    safe_x = _math(group, "MAXIMUM", f"{prefix} Safe Remesh Width", x + 660, y + 80, value_2=1.0e-6)
    safe_y = _math(group, "MAXIMUM", f"{prefix} Safe Remesh Height", x + 660, y - 80, value_2=1.0e-6)
    ratio = _math(group, "DIVIDE", f"{prefix} Remesh Aspect", x + 880, y)
    aspect_root = _math(group, "SQRT", f"{prefix} Remesh Aspect Root", x + 1100, y)
    links.new(geometry_socket, bounds.inputs["Geometry"])
    links.new(bounds.outputs["Max"], size.inputs[0])
    links.new(bounds.outputs["Min"], size.inputs[1])
    links.new(size.outputs[0], size_components.inputs[0])
    links.new(size_components.outputs["X"], safe_x.inputs[0])
    links.new(size_components.outputs["Y"], safe_y.inputs[0])
    links.new(safe_x.outputs[0], ratio.inputs[0])
    links.new(safe_y.outputs[0], ratio.inputs[1])
    links.new(ratio.outputs[0], aspect_root.inputs[0])

    base_segments = _math(group, "POWER", f"{prefix} Remesh Base Segments", x + 880, y - 240, value_1=2.0)
    segments_x = _math(group, "MULTIPLY", f"{prefix} Remesh Segments X", x + 1320, y + 80)
    segments_y = _math(group, "DIVIDE", f"{prefix} Remesh Segments Y", x + 1320, y - 80)
    round_x = _math(group, "ROUND", f"{prefix} Round Remesh X", x + 1540, y + 80)
    round_y = _math(group, "ROUND", f"{prefix} Round Remesh Y", x + 1540, y - 80)
    clamp_x_low = _math(group, "MAXIMUM", f"{prefix} Minimum Remesh X", x + 1760, y + 80, value_2=1.0)
    clamp_y_low = _math(group, "MAXIMUM", f"{prefix} Minimum Remesh Y", x + 1760, y - 80, value_2=1.0)
    clamp_x = _math(group, "MINIMUM", f"{prefix} Maximum Remesh X", x + 1980, y + 80, value_2=512.0)
    clamp_y = _math(group, "MINIMUM", f"{prefix} Maximum Remesh Y", x + 1980, y - 80, value_2=512.0)
    vertices_x = _math(group, "ADD", f"{prefix} Remesh Vertices X", x + 2200, y + 80, value_2=1.0)
    vertices_y = _math(group, "ADD", f"{prefix} Remesh Vertices Y", x + 2200, y - 80, value_2=1.0)
    links.new(level_socket, base_segments.inputs[1])
    links.new(base_segments.outputs[0], segments_x.inputs[0])
    links.new(aspect_root.outputs[0], segments_x.inputs[1])
    links.new(base_segments.outputs[0], segments_y.inputs[0])
    links.new(aspect_root.outputs[0], segments_y.inputs[1])
    links.new(segments_x.outputs[0], round_x.inputs[0])
    links.new(segments_y.outputs[0], round_y.inputs[0])
    links.new(round_x.outputs[0], clamp_x_low.inputs[0])
    links.new(round_y.outputs[0], clamp_y_low.inputs[0])
    links.new(clamp_x_low.outputs[0], clamp_x.inputs[0])
    links.new(clamp_y_low.outputs[0], clamp_y.inputs[0])
    links.new(clamp_x.outputs[0], vertices_x.inputs[0])
    links.new(clamp_y.outputs[0], vertices_y.inputs[0])

    # Keep boundary rays microscopically inside the source polygon. Exact-edge
    # ray tests can drop one complete row on some GPU/CPU geometry backends.
    grid_size_x = _math(group, "MULTIPLY", f"{prefix} Remesh Grid Width", x + 2200, y + 220, value_2=0.999999)
    grid_size_y = _math(group, "MULTIPLY", f"{prefix} Remesh Grid Height", x + 2200, y - 220, value_2=0.999999)
    links.new(safe_x.outputs[0], grid_size_x.inputs[0])
    links.new(safe_y.outputs[0], grid_size_y.inputs[0])
    grid = _node(group, "GeometryNodeMeshGrid", f"{prefix} Aspect Grid", x + 2440, y)
    links.new(grid_size_x.outputs[0], grid.inputs["Size X"])
    links.new(grid_size_y.outputs[0], grid.inputs["Size Y"])
    links.new(vertices_x.outputs[0], grid.inputs["Vertices X"])
    links.new(vertices_y.outputs[0], grid.inputs["Vertices Y"])

    center_sum = _vector_math(group, "ADD", f"{prefix} Remesh Center Sum", x + 660, y + 320)
    center = _vector_math(group, "SCALE", f"{prefix} Remesh Center", x + 880, y + 320)
    center.inputs["Scale"].default_value = 0.5
    center_components = _node(group, "ShaderNodeSeparateXYZ", f"{prefix} Remesh Center Components", x + 1100, y + 320)
    max_components = _node(group, "ShaderNodeSeparateXYZ", f"{prefix} Remesh Maximum", x + 880, y + 500)
    min_components = _node(group, "ShaderNodeSeparateXYZ", f"{prefix} Remesh Minimum", x + 880, y + 640)
    max_dimension = _math(group, "MAXIMUM", f"{prefix} Remesh Maximum Dimension", x + 1100, y + 560)
    margin_scale = _math(group, "MULTIPLY", f"{prefix} Remesh Ray Margin", x + 1320, y + 560, value_2=0.001)
    margin = _math(group, "MAXIMUM", f"{prefix} Safe Remesh Ray Margin", x + 1540, y + 560, value_2=1.0e-4)
    start_z = _math(group, "ADD", f"{prefix} Remesh Ray Start", x + 1760, y + 500)
    depth = _math(group, "SUBTRACT", f"{prefix} Remesh Depth", x + 1320, y + 700)
    double_margin = _math(group, "MULTIPLY", f"{prefix} Remesh Double Margin", x + 1760, y + 700, value_2=2.0)
    ray_length = _math(group, "ADD", f"{prefix} Remesh Ray Length", x + 1980, y + 640)
    translation = _node(group, "ShaderNodeCombineXYZ", f"{prefix} Remesh Ray Origin", x + 2200, y + 420)
    links.new(bounds.outputs["Max"], center_sum.inputs[0])
    links.new(bounds.outputs["Min"], center_sum.inputs[1])
    links.new(center_sum.outputs[0], center.inputs[0])
    links.new(center.outputs[0], center_components.inputs[0])
    links.new(bounds.outputs["Max"], max_components.inputs[0])
    links.new(bounds.outputs["Min"], min_components.inputs[0])
    links.new(safe_x.outputs[0], max_dimension.inputs[0])
    links.new(safe_y.outputs[0], max_dimension.inputs[1])
    links.new(max_dimension.outputs[0], margin_scale.inputs[0])
    links.new(margin_scale.outputs[0], margin.inputs[0])
    links.new(max_components.outputs["Z"], start_z.inputs[0])
    links.new(margin.outputs[0], start_z.inputs[1])
    links.new(max_components.outputs["Z"], depth.inputs[0])
    links.new(min_components.outputs["Z"], depth.inputs[1])
    links.new(margin.outputs[0], double_margin.inputs[0])
    links.new(depth.outputs[0], ray_length.inputs[0])
    links.new(double_margin.outputs[0], ray_length.inputs[1])
    links.new(center_components.outputs["X"], translation.inputs["X"])
    links.new(center_components.outputs["Y"], translation.inputs["Y"])
    links.new(start_z.outputs[0], translation.inputs["Z"])

    transform = _node(group, "GeometryNodeTransform", f"{prefix} Position Aspect Grid", x + 2660, y)
    links.new(grid.outputs["Mesh"], transform.inputs["Geometry"])
    links.new(translation.outputs[0], transform.inputs["Translation"])

    position = _node(group, "GeometryNodeInputPosition", f"{prefix} Remesh Source Position", x + 2660, y - 220)
    source_uv = _node(group, "GeometryNodeInputNamedAttribute", f"{prefix} Source UVMap", x + 2660, y - 420)
    source_uv.data_type = "FLOAT_VECTOR"
    source_uv.inputs["Name"].default_value = "UVMap"
    raycast = _node(group, "GeometryNodeRaycast", f"{prefix} Project Aspect Grid", x + 2880, y - 160)
    try:
        raycast.data_type = "FLOAT_VECTOR"
        raycast.mapping = "INTERPOLATED"
    except (AttributeError, TypeError, ValueError):
        pass
    raycast.inputs["Ray Direction"].default_value = (0.0, 0.0, -1.0)
    links.new(geometry_socket, raycast.inputs["Target Geometry"])
    links.new(position.outputs["Position"], raycast.inputs["Source Position"])
    links.new(ray_length.outputs[0], raycast.inputs["Ray Length"])
    sampled_attribute = _input(raycast, "Attribute")
    if sampled_attribute is not None:
        links.new(source_uv.outputs["Attribute"], sampled_attribute)

    store_uv = _node(group, "GeometryNodeStoreNamedAttribute", f"{prefix} Store Remesh UVMap", x + 3100, y)
    # Blender recognizes a CORNER/FLOAT2 named attribute as an actual UV layer;
    # FLOAT_VECTOR would create a generic 3D attribute invisible to materials.
    store_uv.data_type = "FLOAT2"
    store_uv.domain = "CORNER"
    store_uv.inputs["Name"].default_value = "UVMap"
    links.new(transform.outputs["Geometry"], store_uv.inputs["Geometry"])
    sampled_uv = _output(raycast, "Attribute")
    links.new(sampled_uv if sampled_uv is not None else grid.outputs["UV Map"], store_uv.inputs["Value"])

    hit_name = "fbp_internal_remesh_hit"
    store_hit = _node(group, "GeometryNodeStoreNamedAttribute", f"{prefix} Store Remesh Hits", x + 3320, y)
    store_hit.data_type = "BOOLEAN"
    store_hit.domain = "POINT"
    store_hit.inputs["Name"].default_value = hit_name
    links.new(store_uv.outputs["Geometry"], store_hit.inputs["Geometry"])
    links.new(raycast.outputs["Is Hit"], store_hit.inputs["Value"])
    hit_attribute = _node(group, "GeometryNodeInputNamedAttribute", f"{prefix} Remesh Hit Attribute", x + 3320, y - 220)
    hit_attribute.data_type = "BOOLEAN"
    hit_attribute.inputs["Name"].default_value = hit_name
    project = _node(group, "GeometryNodeSetPosition", f"{prefix} Project Remesh", x + 3320, y)
    links.new(store_hit.outputs["Geometry"], project.inputs["Geometry"])
    links.new(hit_attribute.outputs["Attribute"], project.inputs["Selection"])
    links.new(raycast.outputs["Hit Position"], project.inputs["Position"])
    missed = _node(group, "FunctionNodeBooleanMath", f"{prefix} Missed Remesh Rays", x + 3320, y - 220)
    missed.operation = "NOT"
    links.new(hit_attribute.outputs["Attribute"], missed.inputs[0])
    delete = _node(group, "GeometryNodeDeleteGeometry", f"{prefix} Trim Remesh", x + 3540, y)
    delete.domain = "POINT"
    links.new(project.outputs["Geometry"], delete.inputs["Geometry"])
    links.new(missed.outputs[0], delete.inputs["Selection"])

    final_socket = delete.outputs["Geometry"]
    if triangulate:
        triangles = _node(group, "GeometryNodeTriangulate", f"{prefix} Triangulated Remesh", x + 3760, y)
        triangles.inputs["Quad Method"].default_value = "Beauty"
        links.new(final_socket, triangles.inputs["Mesh"])
        final_socket = triangles.outputs["Mesh"]

    # Generated meshes have no material table of their own. Join the source for
    # one topology step, mark only generated faces, then delete the originals.
    # Blender keeps the source material slots on the surviving remesh without a
    # public Material socket on every effect.
    marker_name = "fbp_internal_remesh_generated"
    mark_generated = _node(group, "GeometryNodeStoreNamedAttribute", f"{prefix} Mark Remesh Faces", x + 3980, y)
    mark_generated.data_type = "BOOLEAN"
    mark_generated.domain = "FACE"
    mark_generated.inputs["Name"].default_value = marker_name
    mark_generated.inputs["Value"].default_value = True
    links.new(final_socket, mark_generated.inputs["Geometry"])
    join_materials = _node(group, "GeometryNodeJoinGeometry", f"{prefix} Preserve Remesh Materials", x + 4200, y)
    links.new(geometry_socket, join_materials.inputs["Geometry"])
    links.new(mark_generated.outputs["Geometry"], join_materials.inputs["Geometry"])
    generated = _node(group, "GeometryNodeInputNamedAttribute", f"{prefix} Generated Remesh Faces", x + 4200, y - 220)
    generated.data_type = "BOOLEAN"
    generated.inputs["Name"].default_value = marker_name
    original = _node(group, "FunctionNodeBooleanMath", f"{prefix} Original Remesh Faces", x + 4420, y - 220)
    original.operation = "NOT"
    links.new(generated.outputs["Attribute"], original.inputs[0])
    delete_original = _node(group, "GeometryNodeDeleteGeometry", f"{prefix} Keep Remesh Only", x + 4420, y)
    delete_original.domain = "FACE"
    links.new(join_materials.outputs["Geometry"], delete_original.inputs["Geometry"])
    links.new(original.outputs[0], delete_original.inputs["Selection"])
    remove_marker = _node(group, "GeometryNodeRemoveAttribute", f"{prefix} Clean Remesh Marker", x + 4640, y)
    remove_marker.inputs["Name"].default_value = marker_name
    links.new(delete_original.outputs["Geometry"], remove_marker.inputs["Geometry"])
    remove_hit = _node(group, "GeometryNodeRemoveAttribute", f"{prefix} Clean Remesh Hit Attribute", x + 4860, y)
    remove_hit.inputs["Name"].default_value = hit_name
    links.new(remove_marker.outputs["Geometry"], remove_hit.inputs["Geometry"])
    return remove_hit.outputs["Geometry"]


def _aspect_remesh_group():
    """Return the one shared aspect-remesh implementation used by all effects."""
    name = "FBP_GN_Aspect_Remesh_6222"
    existing = bpy.data.node_groups.get(name)
    if existing is not None:
        return existing
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    group.use_fake_user = True
    group["fbp_internal_aspect_remesh_version"] = 2
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Level", "INPUT", "NodeSocketInt", default=4, minimum=0, maximum=8)
    _socket(group, "Triangulate", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    quads = _build_aspect_remesh_nodes(
        group, inp.outputs["Geometry"], inp.outputs["Level"],
        prefix="Adaptive Plane", x=-4600, y=500, triangulate=False,
    )
    triangles = _node(group, "GeometryNodeTriangulate", "Aspect Triangulated Remesh", -400, 500)
    triangles.inputs["Quad Method"].default_value = "Beauty"
    group.links.new(quads, triangles.inputs["Mesh"])
    output_switch = _node(group, "GeometryNodeSwitch", "Aspect Remesh Topology", -140, 500)
    output_switch.input_type = "GEOMETRY"
    group.links.new(inp.outputs["Triangulate"], output_switch.inputs["Switch"])
    group.links.new(quads, output_switch.inputs["False"])
    group.links.new(triangles.outputs["Mesh"], output_switch.inputs["True"])
    group.links.new(output_switch.outputs["Output"], out.inputs["Geometry"])
    return group


def _aspect_remesh(group, geometry_socket, level_socket, *, prefix, x, y, triangulate=True):
    """Insert the compact shared remesh group and return its geometry output."""
    node = _node(group, "GeometryNodeGroup", f"{prefix} Aspect Remesh", x, y)
    node.node_tree = _aspect_remesh_group()
    node.inputs["Triangulate"].default_value = bool(triangulate)
    group.links.new(geometry_socket, node.inputs["Geometry"])
    group.links.new(level_socket, node.inputs["Level"])
    return node.outputs["Geometry"]


def _alpha_geometry_mask(group, group_input, *, prefix="Alpha", x=-1500, y=240):
    """Build the shared image-alpha to temporary mesh contract.

    The returned mesh is an aspect-balanced copy with transparent faces
    removed. The source geometry is never modified, so callers can join
    generated geometry back to the animated plane without replacing its
    material or topology.
    """
    links = group.links
    remeshed = _aspect_remesh(
        group, group_input.outputs["Geometry"], group_input.outputs["Alpha Resolution"],
        prefix=f"{prefix} Alpha", x=x, y=y, triangulate=False,
    )
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

    links.new(_output(named_uv, "Attribute", 0), _input(image_texture, "Vector"))
    links.new(_output(image_texture, "Alpha"), transparent.inputs[0])
    links.new(group_input.outputs["Alpha Threshold"], transparent.inputs[1])
    links.new(remeshed, delete.inputs["Geometry"])
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
    group["fbp_builtin_effect_version"] = 13
    group["fbp_effect_schema_version"] = FBP_EFFECT_SCHEMA_VERSION
    return group


def _uv_mix(group, original, warped, factor, *, prefix, x=1100, y=0):
    """Blend two UV vectors without relying on color-only mix nodes."""
    delta = _vector_math(group, "SUBTRACT", f"{prefix} Delta", x, y)
    scale = _vector_math(group, "SCALE", f"{prefix} Factor", x + 190, y)
    result = _vector_math(group, "ADD", f"{prefix} Result", x + 380, y)
    group.links.new(warped, delta.inputs[0])
    group.links.new(original, delta.inputs[1])
    group.links.new(delta.outputs[0], scale.inputs[0])
    group.links.new(factor, _input(scale, "Scale", 3))
    group.links.new(original, result.inputs[0])
    group.links.new(scale.outputs[0], result.inputs[1])
    return result.outputs[0]


def _uv_center_vector(group, inp, *, prefix, x=-1100, y=0):
    center = _node(group, "ShaderNodeCombineXYZ", f"{prefix} Center", x, y)
    group.links.new(inp.outputs["Center X"], center.inputs["X"])
    group.links.new(inp.outputs["Center Y"], center.inputs["Y"])
    return center.outputs[0]


def _create_uv_distortion(name):
    """Procedural 4D turbulence that separates pattern evolution from strength."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Vector", "INPUT", "NodeSocketVector", default=(0.0, 0.0, 0.0))
    _socket(group, "Noise Scale", "INPUT", "NodeSocketFloat", default=10.0, minimum=0.001, maximum=1000.0)
    _socket(group, "Distortion Amount", "INPUT", "NodeSocketFloat", default=0.05, minimum=-10.0, maximum=10.0)
    _socket(group, "Evolution", "INPUT", "NodeSocketFloat", default=0.0, minimum=-10000.0, maximum=10000.0)
    _socket(group, "Vector Out", "OUTPUT", "NodeSocketVector")
    inp, out = _group_io(group)
    links = group.links

    noise = _node(group, "ShaderNodeTexNoise", "Turbulence Field", -620, 80)
    noise.noise_dimensions = '4D'
    detail = _input(noise, "Detail", 3)
    roughness = _input(noise, "Roughness", 4)
    if detail is not None:
        detail.default_value = 2.0
    if roughness is not None:
        roughness.default_value = 0.55

    centered = _vector_math(group, "SUBTRACT", "Center Turbulence", -350, 80)
    centered.inputs[1].default_value = (0.5, 0.5, 0.5)
    scaled = _vector_math(group, "SCALE", "Scale Turbulence", -110, 80)
    warped = _vector_math(group, "ADD", "Distorted UV", 150, 80)

    links.new(inp.outputs["Vector"], noise.inputs["Vector"])
    links.new(inp.outputs["Noise Scale"], noise.inputs["Scale"])
    links.new(inp.outputs["Evolution"], noise.inputs["W"])
    links.new(noise.outputs["Color"], centered.inputs[0])
    links.new(centered.outputs[0], scaled.inputs[0])
    links.new(inp.outputs["Distortion Amount"], _input(scaled, "Scale", 3))
    links.new(inp.outputs["Vector"], warped.inputs[0])
    links.new(scaled.outputs[0], warped.inputs[1])
    links.new(warped.outputs[0], out.inputs["Vector Out"])
    group["fbp_uv_distortion_contract_version"] = 1
    return group


def _create_pixelate(name):
    """Aspect-aware rectangular pixel grid with rotatable sampling cells."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Vector", "INPUT", "NodeSocketVector", default=(0.0, 0.0, 0.0))
    _socket(group, "Pixels X", "INPUT", "NodeSocketFloat", default=64.0, minimum=1.0, maximum=8192.0)
    _socket(group, "Pixels Y", "INPUT", "NodeSocketFloat", default=36.0, minimum=1.0, maximum=8192.0)
    _socket(group, "Rotation", "INPUT", "NodeSocketFloat", default=0.0, minimum=-6.283185307, maximum=6.283185307)
    _socket(group, "Offset X", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1.0, maximum=1.0)
    _socket(group, "Offset Y", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1.0, maximum=1.0)
    _socket(group, "Vector Out", "OUTPUT", "NodeSocketVector")
    inp, out = _group_io(group)
    links = group.links

    offset = _node(group, "ShaderNodeCombineXYZ", "Pixel Grid Offset", -980, 230)
    shifted = _vector_math(group, "ADD", "Offset Pixel Grid", -790, 120)
    rotate = _node(group, "ShaderNodeVectorRotate", "Rotate Pixel Grid", -590, 120)
    rotate.rotation_type = "Z_AXIS"
    rotate.inputs["Center"].default_value = (0.5, 0.5, 0.0)
    separate = _node(group, "ShaderNodeSeparateXYZ", "Separate Pixel UV", -390, 120)

    x_mul = _math(group, "MULTIPLY", "X Cells", -180, 250)
    x_floor = _math(group, "FLOOR", "X Floor", 0, 250)
    x_half = _math(group, "ADD", "X Center", 180, 250, value_2=0.5)
    x_div = _math(group, "DIVIDE", "X Normalize", 360, 250)
    y_mul = _math(group, "MULTIPLY", "Y Cells", -180, -20)
    y_floor = _math(group, "FLOOR", "Y Floor", 0, -20)
    y_half = _math(group, "ADD", "Y Center", 180, -20, value_2=0.5)
    y_div = _math(group, "DIVIDE", "Y Normalize", 360, -20)
    combine = _node(group, "ShaderNodeCombineXYZ", "Pixelated UV", 560, 120)
    inverse_angle = _math(group, "MULTIPLY", "Inverse Pixel Rotation", 360, -210, value_2=-1.0)
    unrotate = _node(group, "ShaderNodeVectorRotate", "Restore Pixel Grid Rotation", 760, 120)
    unrotate.rotation_type = "Z_AXIS"
    unrotate.inputs["Center"].default_value = (0.5, 0.5, 0.0)
    subtract_offset = _vector_math(group, "SUBTRACT", "Restore Pixel Grid Offset", 970, 120)

    links.new(inp.outputs["Offset X"], offset.inputs["X"])
    links.new(inp.outputs["Offset Y"], offset.inputs["Y"])
    links.new(inp.outputs["Vector"], shifted.inputs[0])
    links.new(offset.outputs[0], shifted.inputs[1])
    links.new(shifted.outputs[0], rotate.inputs["Vector"])
    links.new(inp.outputs["Rotation"], rotate.inputs["Angle"])
    links.new(rotate.outputs["Vector"], separate.inputs[0])
    links.new(separate.outputs["X"], x_mul.inputs[0]); links.new(inp.outputs["Pixels X"], x_mul.inputs[1])
    links.new(x_mul.outputs[0], x_floor.inputs[0]); links.new(x_floor.outputs[0], x_half.inputs[0])
    links.new(x_half.outputs[0], x_div.inputs[0]); links.new(inp.outputs["Pixels X"], x_div.inputs[1])
    links.new(separate.outputs["Y"], y_mul.inputs[0]); links.new(inp.outputs["Pixels Y"], y_mul.inputs[1])
    links.new(y_mul.outputs[0], y_floor.inputs[0]); links.new(y_floor.outputs[0], y_half.inputs[0])
    links.new(y_half.outputs[0], y_div.inputs[0]); links.new(inp.outputs["Pixels Y"], y_div.inputs[1])
    links.new(x_div.outputs[0], combine.inputs["X"]); links.new(y_div.outputs[0], combine.inputs["Y"])
    links.new(separate.outputs["Z"], combine.inputs["Z"])
    links.new(inp.outputs["Rotation"], inverse_angle.inputs[0])
    links.new(combine.outputs[0], unrotate.inputs["Vector"]); links.new(inverse_angle.outputs[0], unrotate.inputs["Angle"])
    links.new(unrotate.outputs["Vector"], subtract_offset.inputs[0]); links.new(offset.outputs[0], subtract_offset.inputs[1])
    links.new(subtract_offset.outputs[0], out.inputs["Vector Out"])
    group["fbp_pixelate_contract_version"] = 2
    return group


def _create_swirl(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Center X", "INPUT", "NodeSocketFloat", default=0.5, minimum=-2.0, maximum=3.0)
    _socket(group, "Center Y", "INPUT", "NodeSocketFloat", default=0.5, minimum=-2.0, maximum=3.0)
    _socket(group, "Radius", "INPUT", "NodeSocketFloat", default=0.5, minimum=0.001, maximum=4.0)
    _socket(group, "Angle", "INPUT", "NodeSocketFloat", default=3.141592654, minimum=-25.13274123, maximum=25.13274123)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Vector Out", "OUTPUT", "NodeSocketVector")
    inp, out = _group_io(group); links = group.links
    center = _uv_center_vector(group, inp, prefix="Swirl", x=-1260, y=80)
    centered = _vector_math(group, "SUBTRACT", "Swirl Centered UV", -1060, 80)
    sep = _node(group, "ShaderNodeSeparateXYZ", "Swirl Coordinates", -860, 80)
    x2 = _math(group, "MULTIPLY", "Swirl X Squared", -650, 250); y2 = _math(group, "MULTIPLY", "Swirl Y Squared", -650, 100)
    r2 = _math(group, "ADD", "Swirl Radius Squared", -470, 180); radius = _math(group, "SQRT", "Swirl Radius", -290, 180)
    safe_radius = _math(group, "MAXIMUM", "Safe Swirl Radius", -470, -20, value_2=0.0001)
    normalized = _math(group, "DIVIDE", "Normalized Swirl Radius", -100, 180)
    inv = _math(group, "SUBTRACT", "Swirl Falloff", 80, 180, value_1=1.0); clamp = _math(group, "MAXIMUM", "Clamp Swirl Falloff", 260, 180, value_2=0.0)
    falloff = _math(group, "MULTIPLY", "Smooth Swirl Falloff", 440, 180); theta = _math(group, "MULTIPLY", "Swirl Angle", 620, 180)
    cosine = _math(group, "COSINE", "Swirl Cosine", 800, 260); sine = _math(group, "SINE", "Swirl Sine", 800, 100)
    xcos = _math(group, "MULTIPLY", "Swirl X Cos", 980, 320); ysin = _math(group, "MULTIPLY", "Swirl Y Sin", 980, 210); xr = _math(group, "SUBTRACT", "Swirl X", 1160, 280)
    xsin = _math(group, "MULTIPLY", "Swirl X Sin", 980, 80); ycos = _math(group, "MULTIPLY", "Swirl Y Cos", 980, -30); yr = _math(group, "ADD", "Swirl Y", 1160, 30)
    combine = _node(group, "ShaderNodeCombineXYZ", "Swirled Coordinates", 1340, 150); warped = _vector_math(group, "ADD", "Swirl Restore Center", 1530, 150)
    links.new(inp.outputs["Vector"], centered.inputs[0]); links.new(center, centered.inputs[1]); links.new(centered.outputs[0], sep.inputs[0])
    links.new(sep.outputs["X"], x2.inputs[0]); links.new(sep.outputs["X"], x2.inputs[1]); links.new(sep.outputs["Y"], y2.inputs[0]); links.new(sep.outputs["Y"], y2.inputs[1])
    links.new(x2.outputs[0], r2.inputs[0]); links.new(y2.outputs[0], r2.inputs[1]); links.new(r2.outputs[0], radius.inputs[0]); links.new(inp.outputs["Radius"], safe_radius.inputs[0])
    links.new(radius.outputs[0], normalized.inputs[0]); links.new(safe_radius.outputs[0], normalized.inputs[1]); links.new(normalized.outputs[0], inv.inputs[1]); links.new(inv.outputs[0], clamp.inputs[0])
    links.new(clamp.outputs[0], falloff.inputs[0]); links.new(clamp.outputs[0], falloff.inputs[1]); links.new(falloff.outputs[0], theta.inputs[0]); links.new(inp.outputs["Angle"], theta.inputs[1])
    links.new(theta.outputs[0], cosine.inputs[0]); links.new(theta.outputs[0], sine.inputs[0])
    links.new(sep.outputs["X"], xcos.inputs[0]); links.new(cosine.outputs[0], xcos.inputs[1]); links.new(sep.outputs["Y"], ysin.inputs[0]); links.new(sine.outputs[0], ysin.inputs[1]); links.new(xcos.outputs[0], xr.inputs[0]); links.new(ysin.outputs[0], xr.inputs[1])
    links.new(sep.outputs["X"], xsin.inputs[0]); links.new(sine.outputs[0], xsin.inputs[1]); links.new(sep.outputs["Y"], ycos.inputs[0]); links.new(cosine.outputs[0], ycos.inputs[1]); links.new(xsin.outputs[0], yr.inputs[0]); links.new(ycos.outputs[0], yr.inputs[1])
    links.new(xr.outputs[0], combine.inputs["X"]); links.new(yr.outputs[0], combine.inputs["Y"]); links.new(combine.outputs[0], warped.inputs[0]); links.new(center, warped.inputs[1])
    result = _uv_mix(group, inp.outputs["Vector"], warped.outputs[0], inp.outputs["Factor"], prefix="Swirl", x=1720, y=150)
    links.new(result, out.inputs["Vector Out"])
    return group


def _create_bulge_pinch(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for n,d,mi,ma in (("Center X",.5,-2,3),("Center Y",.5,-2,3),("Radius",.5,.001,4),("Strength",.5,-2,2),("Factor",1,0,1)):
        _socket(group,n,"INPUT","NodeSocketFloat",default=d,minimum=mi,maximum=ma)
    _socket(group,"Vector","INPUT","NodeSocketVector"); _socket(group,"Vector Out","OUTPUT","NodeSocketVector")
    inp,out=_group_io(group); links=group.links; center=_uv_center_vector(group,inp,prefix="Bulge",x=-1100,y=80)
    centered=_vector_math(group,"SUBTRACT","Bulge Centered UV",-900,80); length=_vector_math(group,"LENGTH","Bulge Radius",-700,80)
    safe=_math(group,"MAXIMUM","Safe Bulge Radius",-700,-100,value_2=.0001); norm=_math(group,"DIVIDE","Bulge Normalized Radius",-500,80)
    inv=_math(group,"SUBTRACT","Bulge Falloff",-320,80,value_1=1); clamp=_math(group,"MAXIMUM","Clamp Bulge Falloff",-140,80,value_2=0)
    smooth=_math(group,"MULTIPLY","Smooth Bulge Falloff",40,80); amount=_math(group,"MULTIPLY","Bulge Amount",220,80)
    scale=_math(group,"SUBTRACT","Bulge Scale",400,80,value_1=1); safe_scale=_math(group,"MAXIMUM","Safe Bulge Scale",580,80,value_2=.001)
    scaled=_vector_math(group,"SCALE","Scale Bulge UV",760,80); warped=_vector_math(group,"ADD","Restore Bulge Center",950,80)
    links.new(inp.outputs["Vector"],centered.inputs[0]); links.new(center,centered.inputs[1]); links.new(centered.outputs[0],length.inputs[0]); links.new(inp.outputs["Radius"],safe.inputs[0])
    links.new(length.outputs["Value"],norm.inputs[0]); links.new(safe.outputs[0],norm.inputs[1]); links.new(norm.outputs[0],inv.inputs[1]); links.new(inv.outputs[0],clamp.inputs[0])
    links.new(clamp.outputs[0],smooth.inputs[0]); links.new(clamp.outputs[0],smooth.inputs[1]); links.new(smooth.outputs[0],amount.inputs[0]); links.new(inp.outputs["Strength"],amount.inputs[1]); links.new(amount.outputs[0],scale.inputs[1]); links.new(scale.outputs[0],safe_scale.inputs[0])
    links.new(centered.outputs[0],scaled.inputs[0]); links.new(safe_scale.outputs[0],_input(scaled,"Scale",3)); links.new(scaled.outputs[0],warped.inputs[0]); links.new(center,warped.inputs[1])
    result=_uv_mix(group,inp.outputs["Vector"],warped.outputs[0],inp.outputs["Factor"],prefix="Bulge Pinch",x=1140,y=80); links.new(result,out.inputs["Vector Out"]); return group


def _create_lens_warp(name):
    group=bpy.data.node_groups.new(name,"ShaderNodeTree")
    for n,d,mi,ma in (("Center X",.5,-2,3),("Center Y",.5,-2,3),("Distortion",0,-4,4),("Zoom",1,.01,8),("Factor",1,0,1)):_socket(group,n,"INPUT","NodeSocketFloat",default=d,minimum=mi,maximum=ma)
    _socket(group,"Vector","INPUT","NodeSocketVector");_socket(group,"Vector Out","OUTPUT","NodeSocketVector");inp,out=_group_io(group);links=group.links;center=_uv_center_vector(group,inp,prefix="Lens",x=-1050,y=80)
    centered=_vector_math(group,"SUBTRACT","Lens Centered UV",-850,80);sep=_node(group,"ShaderNodeSeparateXYZ","Lens Coordinates",-650,80)
    x2=_math(group,"MULTIPLY","Lens X Squared",-450,190);y2=_math(group,"MULTIPLY","Lens Y Squared",-450,40);r2=_math(group,"ADD","Lens Radius Squared",-270,120)
    distort=_math(group,"MULTIPLY","Lens Distortion Amount",-90,120);scale=_math(group,"ADD","Lens Radial Scale",90,120,value_1=1);safezoom=_math(group,"MAXIMUM","Safe Lens Zoom",90,-40,value_2=.001);finalscale=_math(group,"DIVIDE","Lens Scale and Zoom",270,120)
    scaled=_vector_math(group,"SCALE","Warp Lens UV",460,120);warped=_vector_math(group,"ADD","Restore Lens Center",650,120)
    links.new(inp.outputs["Vector"],centered.inputs[0]);links.new(center,centered.inputs[1]);links.new(centered.outputs[0],sep.inputs[0]);links.new(sep.outputs["X"],x2.inputs[0]);links.new(sep.outputs["X"],x2.inputs[1]);links.new(sep.outputs["Y"],y2.inputs[0]);links.new(sep.outputs["Y"],y2.inputs[1]);links.new(x2.outputs[0],r2.inputs[0]);links.new(y2.outputs[0],r2.inputs[1]);links.new(r2.outputs[0],distort.inputs[0]);links.new(inp.outputs["Distortion"],distort.inputs[1]);links.new(distort.outputs[0],scale.inputs[1]);links.new(inp.outputs["Zoom"],safezoom.inputs[0]);links.new(scale.outputs[0],finalscale.inputs[0]);links.new(safezoom.outputs[0],finalscale.inputs[1]);links.new(centered.outputs[0],scaled.inputs[0]);links.new(finalscale.outputs[0],_input(scaled,"Scale",3));links.new(scaled.outputs[0],warped.inputs[0]);links.new(center,warped.inputs[1])
    result=_uv_mix(group,inp.outputs["Vector"],warped.outputs[0],inp.outputs["Factor"],prefix="Lens Warp",x=840,y=120);links.new(result,out.inputs["Vector Out"]);return group


def _create_wave_warp(name):
    group=bpy.data.node_groups.new(name,"ShaderNodeTree");_socket(group,"Vector","INPUT","NodeSocketVector")
    for n,d,mi,ma in (("Amplitude",.025,-1,1),("Frequency",6,.01,256),("Phase",0,-1000,1000),("Speed",1,-20,20),("Angle",0,-6.283185307,6.283185307),("Factor",1,0,1)):_socket(group,n,"INPUT","NodeSocketFloat",default=d,minimum=mi,maximum=ma)
    _socket(group,"Vector Out","OUTPUT","NodeSocketVector");inp,out=_group_io(group);links=group.links
    centered=_vector_math(group,"SUBTRACT","Wave Centered UV",-1000,80);centered.inputs[1].default_value=(.5,.5,0);rotate=_node(group,"ShaderNodeVectorRotate","Wave Direction",-800,80);rotate.rotation_type="Z_AXIS";sep=_node(group,"ShaderNodeSeparateXYZ","Wave Coordinates",-600,80)
    freq=_math(group,"MULTIPLY","Wave Frequency",-400,180);tau=_math(group,"MULTIPLY","Wave Tau",-220,180,value_2=6.283185307);phase=_math(group,"ADD","Wave Phase",-40,180);sine=_math(group,"SINE","Wave Sine",140,180);amp=_math(group,"MULTIPLY","Wave Amplitude",320,180);yadd=_math(group,"ADD","Wave Y",500,40);comb=_node(group,"ShaderNodeCombineXYZ","Wave Coordinates Out",680,80);inv=_math(group,"MULTIPLY","Inverse Wave Angle",500,-180,value_2=-1);unrotate=_node(group,"ShaderNodeVectorRotate","Restore Wave Direction",880,80);unrotate.rotation_type="Z_AXIS";restore=_vector_math(group,"ADD","Restore Wave Center",1080,80);restore.inputs[1].default_value=(.5,.5,0)
    links.new(inp.outputs["Vector"],centered.inputs[0]);links.new(centered.outputs[0],rotate.inputs["Vector"]);links.new(inp.outputs["Angle"],rotate.inputs["Angle"]);links.new(rotate.outputs["Vector"],sep.inputs[0]);links.new(sep.outputs["X"],freq.inputs[0]);links.new(inp.outputs["Frequency"],freq.inputs[1]);links.new(freq.outputs[0],tau.inputs[0]);links.new(tau.outputs[0],phase.inputs[0]);links.new(inp.outputs["Phase"],phase.inputs[1]);links.new(phase.outputs[0],sine.inputs[0]);links.new(sine.outputs[0],amp.inputs[0]);links.new(inp.outputs["Amplitude"],amp.inputs[1]);links.new(sep.outputs["Y"],yadd.inputs[0]);links.new(amp.outputs[0],yadd.inputs[1]);links.new(sep.outputs["X"],comb.inputs["X"]);links.new(yadd.outputs[0],comb.inputs["Y"]);links.new(sep.outputs["Z"],comb.inputs["Z"]);links.new(inp.outputs["Angle"],inv.inputs[0]);links.new(comb.outputs[0],unrotate.inputs["Vector"]);links.new(inv.outputs[0],unrotate.inputs["Angle"]);links.new(unrotate.outputs["Vector"],restore.inputs[0]);result=_uv_mix(group,inp.outputs["Vector"],restore.outputs[0],inp.outputs["Factor"],prefix="Wave Warp",x=1270,y=80);links.new(result,out.inputs["Vector Out"]);return group


def _create_ripple_distortion(name):
    group=bpy.data.node_groups.new(name,"ShaderNodeTree");_socket(group,"Vector","INPUT","NodeSocketVector")
    for n,d,mi,ma in (("Center X",.5,-2,3),("Center Y",.5,-2,3),("Amplitude",.02,-1,1),("Frequency",12,.01,512),("Phase",0,-1000,1000),("Speed",1,-20,20),("Radius",.75,.001,4),("Falloff",1,.05,8),("Factor",1,0,1)):_socket(group,n,"INPUT","NodeSocketFloat",default=d,minimum=mi,maximum=ma)
    _socket(group,"Vector Out","OUTPUT","NodeSocketVector");inp,out=_group_io(group);links=group.links;center=_uv_center_vector(group,inp,prefix="Ripple",x=-1250,y=100);centered=_vector_math(group,"SUBTRACT","Ripple Centered UV",-1050,100);length=_vector_math(group,"LENGTH","Ripple Radius",-850,180);normal=_vector_math(group,"NORMALIZE","Ripple Direction",-850,20)
    freq=_math(group,"MULTIPLY","Ripple Frequency",-650,220);tau=_math(group,"MULTIPLY","Ripple Tau",-470,220,value_2=6.283185307);phase=_math(group,"ADD","Ripple Phase",-290,220);sine=_math(group,"SINE","Ripple Sine",-110,220);wave=_math(group,"MULTIPLY","Ripple Amplitude",70,220)
    safe_radius=_math(group,"MAXIMUM","Safe Ripple Radius",-650,-100,value_2=.0001);normr=_math(group,"DIVIDE","Normalized Ripple Radius",-470,-100);inv=_math(group,"SUBTRACT","Ripple Falloff",-290,-100,value_1=1);clamp=_math(group,"MAXIMUM","Clamp Ripple Falloff",-110,-100,value_2=0);power=_math(group,"POWER","Ripple Falloff Power",70,-100);disp=_math(group,"MULTIPLY","Ripple Displacement",250,120)
    offset=_vector_math(group,"SCALE","Ripple Offset",440,120);warpedc=_vector_math(group,"ADD","Ripple Warped Centered",630,120);warped=_vector_math(group,"ADD","Restore Ripple Center",820,120)
    links.new(inp.outputs["Vector"],centered.inputs[0]);links.new(center,centered.inputs[1]);links.new(centered.outputs[0],length.inputs[0]);links.new(centered.outputs[0],normal.inputs[0]);links.new(length.outputs["Value"],freq.inputs[0]);links.new(inp.outputs["Frequency"],freq.inputs[1]);links.new(freq.outputs[0],tau.inputs[0]);links.new(tau.outputs[0],phase.inputs[0]);links.new(inp.outputs["Phase"],phase.inputs[1]);links.new(phase.outputs[0],sine.inputs[0]);links.new(sine.outputs[0],wave.inputs[0]);links.new(inp.outputs["Amplitude"],wave.inputs[1]);links.new(inp.outputs["Radius"],safe_radius.inputs[0]);links.new(length.outputs["Value"],normr.inputs[0]);links.new(safe_radius.outputs[0],normr.inputs[1]);links.new(normr.outputs[0],inv.inputs[1]);links.new(inv.outputs[0],clamp.inputs[0]);links.new(clamp.outputs[0],power.inputs[0]);links.new(inp.outputs["Falloff"],power.inputs[1]);links.new(wave.outputs[0],disp.inputs[0]);links.new(power.outputs[0],disp.inputs[1]);links.new(normal.outputs[0],offset.inputs[0]);links.new(disp.outputs[0],_input(offset,"Scale",3));links.new(centered.outputs[0],warpedc.inputs[0]);links.new(offset.outputs[0],warpedc.inputs[1]);links.new(warpedc.outputs[0],warped.inputs[0]);links.new(center,warped.inputs[1]);result=_uv_mix(group,inp.outputs["Vector"],warped.outputs[0],inp.outputs["Factor"],prefix="Ripple Distortion",x=1010,y=120);links.new(result,out.inputs["Vector Out"]);return group


def _create_kaleidoscope(name):
    group=bpy.data.node_groups.new(name,"ShaderNodeTree");_socket(group,"Vector","INPUT","NodeSocketVector")
    for n,d,mi,ma in (("Center X",.5,-2,3),("Center Y",.5,-2,3),("Segments",6,1,64),("Rotation",0,-6.283185307,6.283185307),("Factor",1,0,1)):_socket(group,n,"INPUT","NodeSocketFloat",default=d,minimum=mi,maximum=ma)
    _socket(group,"Vector Out","OUTPUT","NodeSocketVector");inp,out=_group_io(group);links=group.links;center=_uv_center_vector(group,inp,prefix="Kaleidoscope",x=-1250,y=100);centered=_vector_math(group,"SUBTRACT","Kaleidoscope Centered UV",-1050,100);sep=_node(group,"ShaderNodeSeparateXYZ","Kaleidoscope Coordinates",-850,100)
    x2=_math(group,"MULTIPLY","Kaleidoscope X2",-650,250);y2=_math(group,"MULTIPLY","Kaleidoscope Y2",-650,100);r2=_math(group,"ADD","Kaleidoscope R2",-470,180);radius=_math(group,"SQRT","Kaleidoscope Radius",-290,180);angle=_math(group,"ARCTAN2","Kaleidoscope Angle",-470,-20);rot=_math(group,"ADD","Kaleidoscope Rotation",-290,-20);safe=_math(group,"MAXIMUM","Kaleidoscope Segments",-290,-180,value_2=1);sector=_math(group,"DIVIDE","Kaleidoscope Sector",-110,-100,value_1=6.283185307);mod=_math(group,"MODULO","Kaleidoscope Modulo",70,-20);half=_math(group,"MULTIPLY","Kaleidoscope Half Sector",70,-150,value_2=.5);centerangle=_math(group,"SUBTRACT","Kaleidoscope Center Angle",250,-20);fold=_math(group,"ABSOLUTE","Kaleidoscope Fold",430,-20);unrot=_math(group,"SUBTRACT","Kaleidoscope Unrotate",610,-20);cos=_math(group,"COSINE","Kaleidoscope Cos",790,80);sin=_math(group,"SINE","Kaleidoscope Sin",790,-80);x=_math(group,"MULTIPLY","Kaleidoscope X",970,80);y=_math(group,"MULTIPLY","Kaleidoscope Y",970,-80);comb=_node(group,"ShaderNodeCombineXYZ","Kaleidoscope Folded UV",1150,20);warped=_vector_math(group,"ADD","Restore Kaleidoscope Center",1340,20)
    links.new(inp.outputs["Vector"],centered.inputs[0]);links.new(center,centered.inputs[1]);links.new(centered.outputs[0],sep.inputs[0]);links.new(sep.outputs["X"],x2.inputs[0]);links.new(sep.outputs["X"],x2.inputs[1]);links.new(sep.outputs["Y"],y2.inputs[0]);links.new(sep.outputs["Y"],y2.inputs[1]);links.new(x2.outputs[0],r2.inputs[0]);links.new(y2.outputs[0],r2.inputs[1]);links.new(r2.outputs[0],radius.inputs[0]);links.new(sep.outputs["Y"],angle.inputs[0]);links.new(sep.outputs["X"],angle.inputs[1]);links.new(angle.outputs[0],rot.inputs[0]);links.new(inp.outputs["Rotation"],rot.inputs[1]);links.new(inp.outputs["Segments"],safe.inputs[0]);links.new(safe.outputs[0],sector.inputs[1]);links.new(rot.outputs[0],mod.inputs[0]);links.new(sector.outputs[0],mod.inputs[1]);links.new(sector.outputs[0],half.inputs[0]);links.new(mod.outputs[0],centerangle.inputs[0]);links.new(half.outputs[0],centerangle.inputs[1]);links.new(centerangle.outputs[0],fold.inputs[0]);links.new(fold.outputs[0],unrot.inputs[0]);links.new(inp.outputs["Rotation"],unrot.inputs[1]);links.new(unrot.outputs[0],cos.inputs[0]);links.new(unrot.outputs[0],sin.inputs[0]);links.new(cos.outputs[0],x.inputs[0]);links.new(radius.outputs[0],x.inputs[1]);links.new(sin.outputs[0],y.inputs[0]);links.new(radius.outputs[0],y.inputs[1]);links.new(x.outputs[0],comb.inputs["X"]);links.new(y.outputs[0],comb.inputs["Y"]);links.new(comb.outputs[0],warped.inputs[0]);links.new(center,warped.inputs[1]);result=_uv_mix(group,inp.outputs["Vector"],warped.outputs[0],inp.outputs["Factor"],prefix="Kaleidoscope",x=1530,y=20);links.new(result,out.inputs["Vector Out"]);return group


def _create_hex_pixelate(name):
    group=bpy.data.node_groups.new(name,"ShaderNodeTree");_socket(group,"Vector","INPUT","NodeSocketVector")
    for n,d,mi,ma in (("Cells X",48,1,8192),("Cells Y",32,1,8192),("Rotation",0,-6.283185307,6.283185307),("Factor",1,0,1)):_socket(group,n,"INPUT","NodeSocketFloat",default=d,minimum=mi,maximum=ma)
    _socket(group,"Vector Out","OUTPUT","NodeSocketVector");inp,out=_group_io(group);links=group.links;rotate=_node(group,"ShaderNodeVectorRotate","Rotate Hex Grid",-1050,100);rotate.rotation_type="Z_AXIS";rotate.inputs["Center"].default_value=(.5,.5,0);sep=_node(group,"ShaderNodeSeparateXYZ","Hex Grid Coordinates",-850,100)
    ys=_math(group,"MULTIPLY","Hex Row Scale",-650,-20);yf=_math(group,"FLOOR","Hex Row",-470,-20);parity=_math(group,"MODULO","Hex Row Parity",-290,-20,value_2=2);stagger=_math(group,"MULTIPLY","Hex Row Stagger",-110,-20,value_2=.5)
    xs=_math(group,"MULTIPLY","Hex Column Scale",-650,220);xshift=_math(group,"SUBTRACT","Hex Staggered Column",70,220);xf=_math(group,"FLOOR","Hex Column",250,220);xhalf=_math(group,"ADD","Hex Column Center",430,220,value_2=.5);xstagger=_math(group,"ADD","Hex Stagger Restore",610,220);xn=_math(group,"DIVIDE","Hex X Normalize",790,220)
    yhalf=_math(group,"ADD","Hex Row Center",-110,-140,value_2=.5);yn=_math(group,"DIVIDE","Hex Y Normalize",70,-140);comb=_node(group,"ShaderNodeCombineXYZ","Hex Sample UV",970,80);inv=_math(group,"MULTIPLY","Inverse Hex Rotation",790,-120,value_2=-1);unrotate=_node(group,"ShaderNodeVectorRotate","Restore Hex Rotation",1160,80);unrotate.rotation_type="Z_AXIS";unrotate.inputs["Center"].default_value=(.5,.5,0)
    links.new(inp.outputs["Vector"],rotate.inputs["Vector"]);links.new(inp.outputs["Rotation"],rotate.inputs["Angle"]);links.new(rotate.outputs["Vector"],sep.inputs[0]);links.new(sep.outputs["Y"],ys.inputs[0]);links.new(inp.outputs["Cells Y"],ys.inputs[1]);links.new(ys.outputs[0],yf.inputs[0]);links.new(yf.outputs[0],parity.inputs[0]);links.new(parity.outputs[0],stagger.inputs[0]);links.new(sep.outputs["X"],xs.inputs[0]);links.new(inp.outputs["Cells X"],xs.inputs[1]);links.new(xs.outputs[0],xshift.inputs[0]);links.new(stagger.outputs[0],xshift.inputs[1]);links.new(xshift.outputs[0],xf.inputs[0]);links.new(xf.outputs[0],xhalf.inputs[0]);links.new(xhalf.outputs[0],xstagger.inputs[0]);links.new(stagger.outputs[0],xstagger.inputs[1]);links.new(xstagger.outputs[0],xn.inputs[0]);links.new(inp.outputs["Cells X"],xn.inputs[1]);links.new(yf.outputs[0],yhalf.inputs[0]);links.new(yhalf.outputs[0],yn.inputs[0]);links.new(inp.outputs["Cells Y"],yn.inputs[1]);links.new(xn.outputs[0],comb.inputs["X"]);links.new(yn.outputs[0],comb.inputs["Y"]);links.new(inp.outputs["Rotation"],inv.inputs[0]);links.new(comb.outputs[0],unrotate.inputs["Vector"]);links.new(inv.outputs[0],unrotate.inputs["Angle"]);result=_uv_mix(group,inp.outputs["Vector"],unrotate.outputs["Vector"],inp.outputs["Factor"],prefix="Hex Pixelate",x=1350,y=80);links.new(result,out.inputs["Vector Out"]);return group


def _create_mosaic_jitter(name):
    """Rotatable block sampling with stable per-cell random offsets."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Vector", "INPUT", "NodeSocketVector")
    for socket_name, default, minimum, maximum in (
        ("Cells X", 32, 1, 8192), ("Cells Y", 18, 1, 8192),
        ("Rotation", 0.0, -6.283185307, 6.283185307),
        ("Jitter", 0.6, 0, 4), ("Offset X", 0.0, -2, 2),
        ("Offset Y", 0.0, -2, 2), ("Seed", 0, -100000, 100000),
        ("Factor", 1, 0, 1),
    ):
        _socket(group, socket_name, "INPUT", "NodeSocketFloat", default=default, minimum=minimum, maximum=maximum)
    _socket(group, "Vector Out", "OUTPUT", "NodeSocketVector")
    inp, out = _group_io(group)
    links = group.links

    offset = _node(group, "ShaderNodeCombineXYZ", "Mosaic Grid Offset", -1540, 120)
    shifted = _vector_math(group, "ADD", "Offset Mosaic Grid", -1360, 120)
    rotate = _node(group, "ShaderNodeVectorRotate", "Rotate Mosaic Grid", -1160, 120)
    rotate.rotation_type = "Z_AXIS"
    rotate.inputs["Center"].default_value = (0.5, 0.5, 0.0)
    coordinates = _node(group, "ShaderNodeSeparateXYZ", "Mosaic Coordinates", -960, 120)
    links.new(inp.outputs["Offset X"], offset.inputs["X"])
    links.new(inp.outputs["Offset Y"], offset.inputs["Y"])
    links.new(inp.outputs["Vector"], shifted.inputs[0])
    links.new(offset.outputs[0], shifted.inputs[1])
    links.new(shifted.outputs[0], rotate.inputs["Vector"])
    links.new(inp.outputs["Rotation"], rotate.inputs["Angle"])
    links.new(rotate.outputs["Vector"], coordinates.inputs[0])

    xs = _math(group, "MULTIPLY", "Mosaic X Cells", -760, 250)
    xf = _math(group, "FLOOR", "Mosaic X Cell", -580, 250)
    xh = _math(group, "ADD", "Mosaic X Center", -400, 250, value_2=0.5)
    xn = _math(group, "DIVIDE", "Mosaic X Normalize", -220, 250)
    ys = _math(group, "MULTIPLY", "Mosaic Y Cells", -760, 0)
    yf = _math(group, "FLOOR", "Mosaic Y Cell", -580, 0)
    yh = _math(group, "ADD", "Mosaic Y Center", -400, 0, value_2=0.5)
    yn = _math(group, "DIVIDE", "Mosaic Y Normalize", -220, 0)
    cell = _node(group, "ShaderNodeCombineXYZ", "Mosaic Cell ID", -220, -230)
    noise = _node(group, "ShaderNodeTexWhiteNoise", "Mosaic Random", 0, -190)
    try:
        noise.noise_dimensions = '3D'
    except (AttributeError, TypeError, ValueError):
        pass
    split = _node(group, "ShaderNodeSeparateColor", "Mosaic Random Channels", 200, -190)
    try:
        split.mode = 'RGB'
    except (AttributeError, TypeError, ValueError):
        pass
    rx = _math(group, "SUBTRACT", "Mosaic Random X", 400, -90, value_2=0.5)
    ry = _math(group, "SUBTRACT", "Mosaic Random Y", 400, -230, value_2=0.5)
    jx = _math(group, "MULTIPLY", "Mosaic Jitter X", 580, -90)
    jy = _math(group, "MULTIPLY", "Mosaic Jitter Y", 580, -230)
    jxcell = _math(group, "DIVIDE", "Mosaic X Cell Size", 760, -90)
    jycell = _math(group, "DIVIDE", "Mosaic Y Cell Size", 760, -230)
    xo = _math(group, "ADD", "Mosaic Sample X", 940, 180)
    yo = _math(group, "ADD", "Mosaic Sample Y", 940, 0)
    sample = _node(group, "ShaderNodeCombineXYZ", "Mosaic Rotated Sample UV", 1120, 100)
    inverse_angle = _math(group, "MULTIPLY", "Inverse Mosaic Rotation", 940, -330, value_2=-1.0)
    unrotate = _node(group, "ShaderNodeVectorRotate", "Restore Mosaic Rotation", 1320, 100)
    unrotate.rotation_type = "Z_AXIS"
    unrotate.inputs["Center"].default_value = (0.5, 0.5, 0.0)
    restore_offset = _vector_math(group, "SUBTRACT", "Restore Mosaic Grid Offset", 1520, 100)

    links.new(coordinates.outputs["X"], xs.inputs[0]); links.new(inp.outputs["Cells X"], xs.inputs[1])
    links.new(xs.outputs[0], xf.inputs[0]); links.new(xf.outputs[0], xh.inputs[0]); links.new(xh.outputs[0], xn.inputs[0]); links.new(inp.outputs["Cells X"], xn.inputs[1])
    links.new(coordinates.outputs["Y"], ys.inputs[0]); links.new(inp.outputs["Cells Y"], ys.inputs[1])
    links.new(ys.outputs[0], yf.inputs[0]); links.new(yf.outputs[0], yh.inputs[0]); links.new(yh.outputs[0], yn.inputs[0]); links.new(inp.outputs["Cells Y"], yn.inputs[1])
    links.new(xf.outputs[0], cell.inputs["X"]); links.new(yf.outputs[0], cell.inputs["Y"]); links.new(inp.outputs["Seed"], cell.inputs["Z"])
    links.new(cell.outputs[0], noise.inputs["Vector"]); links.new(noise.outputs["Color"], split.inputs[0])
    links.new(split.outputs[0], rx.inputs[0]); links.new(split.outputs[1], ry.inputs[0])
    links.new(rx.outputs[0], jx.inputs[0]); links.new(inp.outputs["Jitter"], jx.inputs[1])
    links.new(ry.outputs[0], jy.inputs[0]); links.new(inp.outputs["Jitter"], jy.inputs[1])
    links.new(jx.outputs[0], jxcell.inputs[0]); links.new(inp.outputs["Cells X"], jxcell.inputs[1])
    links.new(jy.outputs[0], jycell.inputs[0]); links.new(inp.outputs["Cells Y"], jycell.inputs[1])
    links.new(xn.outputs[0], xo.inputs[0]); links.new(jxcell.outputs[0], xo.inputs[1])
    links.new(yn.outputs[0], yo.inputs[0]); links.new(jycell.outputs[0], yo.inputs[1])
    links.new(xo.outputs[0], sample.inputs["X"]); links.new(yo.outputs[0], sample.inputs["Y"])
    links.new(inp.outputs["Rotation"], inverse_angle.inputs[0])
    links.new(sample.outputs[0], unrotate.inputs["Vector"]); links.new(inverse_angle.outputs[0], unrotate.inputs["Angle"])
    links.new(unrotate.outputs["Vector"], restore_offset.inputs[0]); links.new(offset.outputs[0], restore_offset.inputs[1])
    result = _uv_mix(group, inp.outputs["Vector"], restore_offset.outputs[0], inp.outputs["Factor"], prefix="Mosaic Jitter", x=1710, y=100)
    links.new(result, out.inputs["Vector Out"])
    group["fbp_mosaic_jitter_version"] = 2
    return group


def _create_slice_shift(name):
    """Figma-inspired angled band shift with stable per-slice randomness."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Vector", "INPUT", "NodeSocketVector")
    for socket_name, default, minimum, maximum in (
        ("Angle", 0.0, -6.283185307, 6.283185307),
        ("Bands", 18.0, 1.0, 512.0),
        ("Shift", 0.08, -2.0, 2.0),
        ("Random", 0.0, 0.0, 2.0),
        ("Seed", 0.0, -100000.0, 100000.0),
        ("Factor", 1.0, 0.0, 1.0),
    ):
        _socket(group, socket_name, "INPUT", "NodeSocketFloat", default=default, minimum=minimum, maximum=maximum)
    _socket(group, "Vector Out", "OUTPUT", "NodeSocketVector")
    inp, out = _group_io(group)
    links = group.links

    rotate = _node(group, "ShaderNodeVectorRotate", "Rotate Slice Space", -1180, 120)
    rotate.rotation_type = "Z_AXIS"
    rotate.inputs["Center"].default_value = (0.5, 0.5, 0.0)
    sep = _node(group, "ShaderNodeSeparateXYZ", "Slice Coordinates", -980, 120)
    band_scaled = _math(group, "MULTIPLY", "Slice Band Scale", -760, -20)
    band_index = _math(group, "FLOOR", "Slice Band Index", -560, -20)
    seed_vector = _node(group, "ShaderNodeCombineXYZ", "Slice Seed Vector", -360, -120)
    noise = _node(group, "ShaderNodeTexWhiteNoise", "Slice Band Noise", -160, -120)
    try:
        noise.noise_dimensions = '3D'
    except (AttributeError, TypeError, ValueError):
        pass
    random_center = _math(group, "SUBTRACT", "Centered Slice Random", 60, -120, value_2=0.5)
    random_amount = _math(group, "MULTIPLY", "Slice Random Amount", 260, -120)
    shift_total = _math(group, "ADD", "Slice Shift Total", 460, 120)
    shifted_x = _math(group, "ADD", "Shifted Slice X", 660, 180)
    shifted = _node(group, "ShaderNodeCombineXYZ", "Shifted Slice UV", 860, 120)
    inv_angle = _math(group, "MULTIPLY", "Inverse Slice Angle", 660, -80, value_2=-1.0)
    unrotate = _node(group, "ShaderNodeVectorRotate", "Restore Slice Space", 1060, 120)
    unrotate.rotation_type = "Z_AXIS"
    unrotate.inputs["Center"].default_value = (0.5, 0.5, 0.0)

    links.new(inp.outputs["Vector"], rotate.inputs["Vector"])
    links.new(inp.outputs["Angle"], rotate.inputs["Angle"])
    links.new(rotate.outputs["Vector"], sep.inputs[0])
    links.new(sep.outputs["Y"], band_scaled.inputs[0])
    links.new(inp.outputs["Bands"], band_scaled.inputs[1])
    links.new(band_scaled.outputs[0], band_index.inputs[0])
    links.new(band_index.outputs[0], seed_vector.inputs["X"])
    links.new(inp.outputs["Seed"], seed_vector.inputs["Y"])
    links.new(seed_vector.outputs[0], noise.inputs["Vector"])
    links.new(noise.outputs["Value"], random_center.inputs[0])
    links.new(random_center.outputs[0], random_amount.inputs[0])
    links.new(inp.outputs["Random"], random_amount.inputs[1])
    links.new(inp.outputs["Shift"], shift_total.inputs[0])
    links.new(random_amount.outputs[0], shift_total.inputs[1])
    links.new(sep.outputs["X"], shifted_x.inputs[0])
    links.new(shift_total.outputs[0], shifted_x.inputs[1])
    links.new(shifted_x.outputs[0], shifted.inputs["X"])
    links.new(sep.outputs["Y"], shifted.inputs["Y"])
    links.new(sep.outputs["Z"], shifted.inputs["Z"])
    links.new(inp.outputs["Angle"], inv_angle.inputs[0])
    links.new(shifted.outputs[0], unrotate.inputs["Vector"])
    links.new(inv_angle.outputs[0], unrotate.inputs["Angle"])
    result = _uv_mix(group, inp.outputs["Vector"], unrotate.outputs["Vector"], inp.outputs["Factor"], prefix="Slice Shift", x=1260, y=120)
    links.new(result, out.inputs["Vector Out"])
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


def _blur_sample(group, inp, uv_socket, weight, label, x, y, prefix):
    """Create one premultiplied image sample used by an alpha-safe blur.

    ``weight`` can be a numeric constant or a node socket. Socket weights let
    Samples disable taps without rebuilding the material node tree.
    """
    links = group.links
    image = _node(group, "ShaderNodeTexImage", f"{prefix} {label}", x, y)
    image["fbp_matrix_source_image_node"] = True
    image["fbp_source_interpolation"] = "Linear"
    try:
        image.interpolation = "Linear"
        image.extension = "EXTEND"
    except (AttributeError, TypeError, ValueError):
        pass
    premultiply = _vector_math(group, "SCALE", f"{label} Premultiply", x + 220, y + 35)
    weighted_color = _vector_math(group, "SCALE", f"{label} Color Weight", x + 430, y + 35)
    weighted_alpha = _math(group, "MULTIPLY", f"{label} Alpha Weight", x + 430, y - 75)
    links.new(uv_socket, image.inputs["Vector"])
    links.new(image.outputs["Color"], premultiply.inputs[0])
    links.new(image.outputs["Alpha"], _input(premultiply, "Scale", 3))
    links.new(premultiply.outputs[0], weighted_color.inputs[0])
    links.new(image.outputs["Alpha"], weighted_alpha.inputs[0])
    if isinstance(weight, (int, float)):
        _input(weighted_color, "Scale", 3).default_value = float(weight)
        weighted_alpha.inputs[1].default_value = float(weight)
    else:
        links.new(weight, _input(weighted_color, "Scale", 3))
        links.new(weight, weighted_alpha.inputs[1])
    return weighted_color.outputs[0], weighted_alpha.outputs[0]


def _blur_add_chain(group, sockets, *, vector, prefix, x, y):
    current = sockets[0]
    for index, socket in enumerate(sockets[1:], 1):
        node = (
            _vector_math(group, "ADD", f"{prefix} {index}", x + index * 150, y)
            if vector else
            _math(group, "ADD", f"{prefix} {index}", x + index * 150, y)
        )
        group.links.new(current, node.inputs[0])
        group.links.new(socket, node.inputs[1])
        current = node.outputs[0]
    return current


def _blur_dynamic_weight(group, samples_socket, index, static_weight, prefix, x, y):
    """Return a tap weight enabled only when Samples includes this tap."""
    enabled = _math(group, "GREATER_THAN", f"{prefix} Tap {index + 1} Enabled", x, y, value_2=float(index) + 0.5)
    weighted = _math(group, "MULTIPLY", f"{prefix} Tap {index + 1} Weight", x + 170, y, value_2=float(static_weight))
    group.links.new(samples_socket, enabled.inputs[0])
    group.links.new(enabled.outputs[0], weighted.inputs[0])
    return weighted.outputs[0]


def _finish_alpha_safe_blur(group, inp, out, color_terms, alpha_terms, *, total_weight, enabled_socket, prefix):
    """Average premultiplied samples, unpremultiply safely and blend with input."""
    links = group.links
    color_sum = _blur_add_chain(group, color_terms, vector=True, prefix=f"{prefix} Color Sum", x=3800, y=350)
    alpha_sum = _blur_add_chain(group, alpha_terms, vector=False, prefix=f"{prefix} Alpha Sum", x=3800, y=-120)
    safe_total = _math(group, "MAXIMUM", f"Safe {prefix} Sample Weight", 7550, -310, value_2=0.0001)
    normalize = _math(group, "DIVIDE", f"{prefix} Sample Normalization", 7730, -310, value_1=1.0)
    if isinstance(total_weight, (int, float)):
        safe_total.inputs[0].default_value = float(total_weight)
    else:
        links.new(total_weight, safe_total.inputs[0])
    links.new(safe_total.outputs[0], normalize.inputs[1])

    color_avg = _vector_math(group, "SCALE", f"{prefix} Color Average", 7900, 350)
    alpha_avg = _math(group, "MULTIPLY", f"{prefix} Alpha Average", 7900, -120)
    safe_alpha = _math(group, "MAXIMUM", f"Safe {prefix} Alpha", 8090, -120, value_2=0.0001)
    reciprocal = _math(group, "DIVIDE", f"{prefix} Unpremultiply Factor", 8270, -120, value_1=1.0)
    unpremultiply = _vector_math(group, "SCALE", f"Unpremultiplied {prefix}", 8450, 350)
    valid_alpha = _math(group, "GREATER_THAN", f"Valid {prefix} Alpha", 8450, 180, value_2=0.0005)
    guarded_color = _mix_rgb(group, "MIX", f"Guard Transparent {prefix}", 8630, 430)
    image_weight = _math(group, "MULTIPLY", f"{prefix} Image Weight", 8270, 40)
    effect_weight = _math(group, "MULTIPLY", f"{prefix} Effect Weight", 8450, 40)
    fallback_weight = _math(group, "SUBTRACT", f"{prefix} Fallback Weight", 8450, -120, value_1=1.0)
    color_mix = _mix_rgb(group, "MIX", f"{prefix} Source Mix", 8870, 300)
    image_alpha = _math(group, "MULTIPLY", f"{prefix} Image Alpha", 8870, -60)
    fallback_alpha = _math(group, "MULTIPLY", f"{prefix} Fallback Alpha", 8870, -190)
    alpha_out = _math(group, "ADD", f"{prefix} Final Alpha", 9060, -120)

    links.new(color_sum, color_avg.inputs[0])
    links.new(normalize.outputs[0], _input(color_avg, "Scale", 3))
    links.new(alpha_sum, alpha_avg.inputs[0])
    links.new(normalize.outputs[0], alpha_avg.inputs[1])
    links.new(alpha_avg.outputs[0], safe_alpha.inputs[0])
    links.new(safe_alpha.outputs[0], reciprocal.inputs[1])
    links.new(color_avg.outputs[0], unpremultiply.inputs[0])
    links.new(reciprocal.outputs[0], _input(unpremultiply, "Scale", 3))
    links.new(alpha_avg.outputs[0], valid_alpha.inputs[0])
    links.new(valid_alpha.outputs[0], guarded_color.inputs[0])
    links.new(inp.outputs["Color In"], guarded_color.inputs[1])
    links.new(unpremultiply.outputs[0], guarded_color.inputs[2])
    links.new(inp.outputs["Use Image Sample"], image_weight.inputs[0])
    links.new(enabled_socket, image_weight.inputs[1])
    links.new(image_weight.outputs[0], effect_weight.inputs[0])
    links.new(inp.outputs["Factor"], effect_weight.inputs[1])
    links.new(effect_weight.outputs[0], fallback_weight.inputs[1])
    links.new(effect_weight.outputs[0], color_mix.inputs[0])
    links.new(inp.outputs["Color In"], color_mix.inputs[1])
    links.new(guarded_color.outputs[0], color_mix.inputs[2])
    links.new(alpha_avg.outputs[0], image_alpha.inputs[0])
    links.new(effect_weight.outputs[0], image_alpha.inputs[1])
    links.new(inp.outputs["Alpha In"], fallback_alpha.inputs[0])
    links.new(fallback_weight.outputs[0], fallback_alpha.inputs[1])
    links.new(image_alpha.outputs[0], alpha_out.inputs[0])
    links.new(fallback_alpha.outputs[0], alpha_out.inputs[1])
    links.new(color_mix.outputs[0], out.inputs["Color Out"])
    links.new(alpha_out.outputs[0], out.inputs["Alpha Out"])


def _create_gaussian_blur(name):
    """Up-to-25-tap alpha-safe Gaussian-style blur with editable quality."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Image Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Radius X", "INPUT", "NodeSocketFloat", default=4.0, minimum=0.0, maximum=256.0)
    _socket(group, "Radius Y", "INPUT", "NodeSocketFloat", default=4.0, minimum=0.0, maximum=256.0)
    _socket(group, "Samples", "INPUT", "NodeSocketInt", default=17, minimum=3, maximum=25)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Texel X", "INPUT", "NodeSocketFloat", default=0.001, minimum=0.0, maximum=1.0)
    _socket(group, "Texel Y", "INPUT", "NodeSocketFloat", default=0.001, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    radius_x = _math(group, "MULTIPLY", "Gaussian Radius X", -1150, 620)
    radius_y = _math(group, "MULTIPLY", "Gaussian Radius Y", -1150, 470)
    maximum_radius = _math(group, "MAXIMUM", "Gaussian Maximum Radius", -1150, 300)
    enabled = _math(group, "GREATER_THAN", "Gaussian Radius Enabled", -950, 300, value_2=0.0001)
    links.new(inp.outputs["Radius X"], radius_x.inputs[0])
    links.new(inp.outputs["Texel X"], radius_x.inputs[1])
    links.new(inp.outputs["Radius Y"], radius_y.inputs[0])
    links.new(inp.outputs["Texel Y"], radius_y.inputs[1])
    links.new(inp.outputs["Radius X"], maximum_radius.inputs[0])
    links.new(inp.outputs["Radius Y"], maximum_radius.inputs[1])
    links.new(maximum_radius.outputs[0], enabled.inputs[0])

    # Center plus twelve mirrored pairs. Any odd Samples value therefore keeps
    # the kernel spatially balanced instead of revealing offset image copies.
    taps = [
        (0.0, 0.0, 1.0000, "Center"),
        (0.25, 0.0, 0.8569, "Inner Right"), (-0.25, 0.0, 0.8569, "Inner Left"),
        (0.0, 0.25, 0.8569, "Inner Top"), (0.0, -0.25, 0.8569, "Inner Bottom"),
        (0.25, 0.25, 0.7344, "Inner Top Right"), (-0.25, -0.25, 0.7344, "Inner Bottom Left"),
        (-0.25, 0.25, 0.7344, "Inner Top Left"), (0.25, -0.25, 0.7344, "Inner Bottom Right"),
        (0.5, 0.0, 0.5394, "Middle Right"), (-0.5, 0.0, 0.5394, "Middle Left"),
        (0.0, 0.5, 0.5394, "Middle Top"), (0.0, -0.5, 0.5394, "Middle Bottom"),
        (0.5, 0.5, 0.2910, "Middle Top Right"), (-0.5, -0.5, 0.2910, "Middle Bottom Left"),
        (-0.5, 0.5, 0.2910, "Middle Top Left"), (0.5, -0.5, 0.2910, "Middle Bottom Right"),
        (0.75, 0.0, 0.1724, "Outer Right"), (-0.75, 0.0, 0.1724, "Outer Left"),
        (0.0, 0.75, 0.1724, "Outer Top"), (0.0, -0.75, 0.1724, "Outer Bottom"),
        (1.0, 0.0, 0.0622, "Far Right"), (-1.0, 0.0, 0.0622, "Far Left"),
        (0.0, 1.0, 0.0622, "Far Top"), (0.0, -1.0, 0.0622, "Far Bottom"),
    ]
    color_terms, alpha_terms, weight_terms = [], [], []
    for index, (ox, oy, static_weight, label) in enumerate(taps):
        y = 610 - index * 150
        x_scale = _math(group, "MULTIPLY", f"{label} Gaussian X", -760, y + 38, value_2=ox)
        y_scale = _math(group, "MULTIPLY", f"{label} Gaussian Y", -760, y - 38, value_2=oy)
        offset = _node(group, "ShaderNodeCombineXYZ", f"{label} Gaussian Offset", -580, y)
        uv = _vector_math(group, "ADD", f"{label} Gaussian UV", -390, y)
        weight = _blur_dynamic_weight(group, inp.outputs["Samples"], index, static_weight, "Gaussian", -1100, y)
        links.new(radius_x.outputs[0], x_scale.inputs[0])
        links.new(radius_y.outputs[0], y_scale.inputs[0])
        links.new(x_scale.outputs[0], offset.inputs["X"])
        links.new(y_scale.outputs[0], offset.inputs["Y"])
        links.new(inp.outputs["UV Vector"], uv.inputs[0])
        links.new(offset.outputs[0], uv.inputs[1])
        color, alpha = _blur_sample(group, inp, uv.outputs[0], weight, label, -170, y, "Gaussian Blur")
        color_terms.append(color); alpha_terms.append(alpha); weight_terms.append(weight)

    total_weight = _blur_add_chain(group, weight_terms, vector=False, prefix="Gaussian Weight Sum", x=3800, y=-340)
    _finish_alpha_safe_blur(group, inp, out, color_terms, alpha_terms,
        total_weight=total_weight, enabled_socket=enabled.outputs[0], prefix="Gaussian Blur")
    group["fbp_blur_contract_version"] = 2
    group["fbp_blur_kind"] = "GAUSSIAN"
    return group


def _create_directional_blur(name):
    """Up-to-25-tap alpha-safe directional blur centered on the source pixel."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Image Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Angle", "INPUT", "NodeSocketFloat", default=0.0, minimum=-6.283185307, maximum=6.283185307)
    _socket(group, "Distance", "INPUT", "NodeSocketFloat", default=12.0, minimum=0.0, maximum=512.0)
    _socket(group, "Samples", "INPUT", "NodeSocketInt", default=17, minimum=3, maximum=25)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Texel X", "INPUT", "NodeSocketFloat", default=0.001, minimum=0.0, maximum=1.0)
    _socket(group, "Texel Y", "INPUT", "NodeSocketFloat", default=0.001, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    cosine = _math(group, "COSINE", "Directional Blur Cosine", -1250, 620)
    sine = _math(group, "SINE", "Directional Blur Sine", -1250, 470)
    distance_x = _math(group, "MULTIPLY", "Directional Distance X", -1050, 620)
    distance_y = _math(group, "MULTIPLY", "Directional Distance Y", -1050, 470)
    texel_x = _math(group, "MULTIPLY", "Directional Texel X", -850, 620)
    texel_y = _math(group, "MULTIPLY", "Directional Texel Y", -850, 470)
    enabled = _math(group, "GREATER_THAN", "Directional Distance Enabled", -850, 300, value_2=0.0001)
    links.new(inp.outputs["Angle"], cosine.inputs[0]); links.new(inp.outputs["Angle"], sine.inputs[0])
    links.new(cosine.outputs[0], distance_x.inputs[0]); links.new(inp.outputs["Distance"], distance_x.inputs[1])
    links.new(sine.outputs[0], distance_y.inputs[0]); links.new(inp.outputs["Distance"], distance_y.inputs[1])
    links.new(distance_x.outputs[0], texel_x.inputs[0]); links.new(inp.outputs["Texel X"], texel_x.inputs[1])
    links.new(distance_y.outputs[0], texel_y.inputs[0]); links.new(inp.outputs["Texel Y"], texel_y.inputs[1])
    links.new(inp.outputs["Distance"], enabled.inputs[0])

    taps = [(0.0, 13.0, "Center")]
    for pair in range(1, 13):
        position = 0.5 * (float(pair) / 12.0)
        weight = float(13 - pair)
        taps.extend(((position, weight, f"Forward {pair}"), (-position, weight, f"Back {pair}")))
    color_terms, alpha_terms, weight_terms = [], [], []
    for index, (position, static_weight, label) in enumerate(taps):
        y = 610 - index * 150
        x_scale = _math(group, "MULTIPLY", f"{label} Direction X", -650, y + 38, value_2=position)
        y_scale = _math(group, "MULTIPLY", f"{label} Direction Y", -650, y - 38, value_2=position)
        offset = _node(group, "ShaderNodeCombineXYZ", f"{label} Direction Offset", -470, y)
        uv = _vector_math(group, "ADD", f"{label} Direction UV", -280, y)
        weight = _blur_dynamic_weight(group, inp.outputs["Samples"], index, static_weight, "Directional", -1200, y)
        links.new(texel_x.outputs[0], x_scale.inputs[0]); links.new(texel_y.outputs[0], y_scale.inputs[0])
        links.new(x_scale.outputs[0], offset.inputs["X"]); links.new(y_scale.outputs[0], offset.inputs["Y"])
        links.new(inp.outputs["UV Vector"], uv.inputs[0]); links.new(offset.outputs[0], uv.inputs[1])
        color, alpha = _blur_sample(group, inp, uv.outputs[0], weight, label, -60, y, "Directional Blur")
        color_terms.append(color); alpha_terms.append(alpha); weight_terms.append(weight)

    total_weight = _blur_add_chain(group, weight_terms, vector=False, prefix="Directional Weight Sum", x=3800, y=-340)
    _finish_alpha_safe_blur(group, inp, out, color_terms, alpha_terms,
        total_weight=total_weight, enabled_socket=enabled.outputs[0], prefix="Directional Blur")
    group["fbp_blur_contract_version"] = 2
    group["fbp_blur_kind"] = "DIRECTIONAL"
    return group

def _create_track_matte(name, *, luma=False, source_opacity=False):
    """Create an alpha-only track matte sampled from another FBP source image.

    ``source_opacity`` is enabled for Clipping Mask so the sampled alpha follows
    the visible opacity of the base layer rather than only the raw file alpha.
    """
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Mask Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Use Source Transform", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    if source_opacity:
        _socket(group, "Use Camera Projection", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
        _socket(group, "Camera Perspective", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
        # Camera-local point -> source-plane-local point matrix.  Passing the
        # actual affine transform is more robust than reconstructing a 2D
        # homography from four corners, especially with parent scale, camera
        # animation and planes placed at different depths.
        for row in range(3):
            for column in range(4):
                default = 1.0 if row == column else 0.0
                _socket(group, f"Camera To Source M{row}{column}", "INPUT", "NodeSocketFloat", default=default)
        _socket(group, "Source Opacity", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
        # Plane-to-plane clipping should follow the source layer as artists see
        # it, not only the raw file alpha.  Keep this lightweight by mirroring
        # the most common alpha/UV-changing source effects inside the clipping
        # sampler.  Chroma Key updates the sampled alpha; Pixelate updates the
        # matte UV before the source is sampled.
        _socket(group, "Use Source Pixelate", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
        _socket(group, "Source Pixels X", "INPUT", "NodeSocketFloat", default=64.0, minimum=1.0, maximum=8192.0)
        _socket(group, "Source Pixels Y", "INPUT", "NodeSocketFloat", default=36.0, minimum=1.0, maximum=8192.0)
        _socket(group, "Source Pixel Rotation", "INPUT", "NodeSocketFloat", default=0.0, minimum=-6.283185307, maximum=6.283185307)
        _socket(group, "Source Pixel Offset X", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1.0, maximum=1.0)
        _socket(group, "Source Pixel Offset Y", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1.0, maximum=1.0)
        _socket(group, "Use Source Chroma Key", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
        _socket(group, "Source Key Color", "INPUT", "NodeSocketColor", default=(0.0, 1.0, 0.0, 1.0))
        _socket(group, "Source Key Tolerance", "INPUT", "NodeSocketFloat", default=0.20, minimum=0.0, maximum=1.732)
        _socket(group, "Source Key Softness", "INPUT", "NodeSocketFloat", default=0.08, minimum=0.0, maximum=1.0)
        _socket(group, "Source Key Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Source Min X", "INPUT", "NodeSocketFloat", default=-1.0)
    _socket(group, "Source Max X", "INPUT", "NodeSocketFloat", default=1.0)
    _socket(group, "Source Min Y", "INPUT", "NodeSocketFloat", default=-1.0)
    _socket(group, "Source Max Y", "INPUT", "NodeSocketFloat", default=1.0)
    _socket(group, "Source UV Min X", "INPUT", "NodeSocketFloat", default=0.0)
    _socket(group, "Source UV Max X", "INPUT", "NodeSocketFloat", default=1.0)
    _socket(group, "Source UV Min Y", "INPUT", "NodeSocketFloat", default=0.0)
    _socket(group, "Source UV Max Y", "INPUT", "NodeSocketFloat", default=1.0)
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
    links.new(inp.outputs["Source UV Min X"], map_x.inputs["To Min"])
    links.new(inp.outputs["Source UV Max X"], map_x.inputs["To Max"])
    links.new(separate.outputs["Y"], map_y.inputs["Value"])
    links.new(inp.outputs["Source Min Y"], map_y.inputs["From Min"])
    links.new(inp.outputs["Source Max Y"], map_y.inputs["From Max"])
    links.new(inp.outputs["Source UV Min Y"], map_y.inputs["To Min"])
    links.new(inp.outputs["Source UV Max Y"], map_y.inputs["To Max"])
    links.new(map_x.outputs["Result"], combine.inputs["X"])
    links.new(map_y.outputs["Result"], combine.inputs["Y"])
    links.new(inp.outputs["Use Source Transform"], uv_mix.inputs[0])
    links.new(inp.outputs["UV Vector"], uv_mix.inputs[1])
    links.new(combine.outputs[0], uv_mix.inputs[2])

    coordinate_output = uv_mix.outputs[0]
    if source_opacity:
        # Convert the shaded point to camera-local space, intersect the camera
        # ray with the real source plane, then transform that hit point into the
        # source plane's local XY coordinates.  This avoids the visible offset
        # caused by fitting a corner homography and remains exact with parented,
        # scaled or depth-separated planes.
        camera_coords = _node(group, "ShaderNodeTexCoord", "Clipping Camera Coordinates", -1580, -80)
        camera_coords["fbp_mask_camera_coord_node"] = True
        camera_sep = _node(group, "ShaderNodeSeparateXYZ", "Separate Camera Coordinates", -1380, -80)
        links.new(camera_coords.outputs["Object"], camera_sep.inputs[0])

        def _sum_three_terms(prefix, row, x, y):
            terms = []
            for column, socket in enumerate((camera_sep.outputs["X"], camera_sep.outputs["Y"], camera_sep.outputs["Z"])):
                term = _math(group, "MULTIPLY", f"{prefix} M{row}{column}", x, y - column * 70)
                links.new(socket, term.inputs[0])
                links.new(inp.outputs[f"Camera To Source M{row}{column}"], term.inputs[1])
                terms.append(term.outputs[0])
            first = _math(group, "ADD", f"{prefix} First Sum", x + 190, y - 35)
            total = _math(group, "ADD", f"{prefix} Total", x + 370, y - 55)
            links.new(terms[0], first.inputs[0]); links.new(terms[1], first.inputs[1])
            links.new(first.outputs[0], total.inputs[0]); links.new(terms[2], total.inputs[1])
            return total.outputs[0]

        # Perspective: P = t * camera_point, where source-local Z(P) = 0.
        perspective_denominator = _sum_three_terms("Perspective Plane Denominator", 2, -1160, -330)
        perspective_numerator = _math(group, "MULTIPLY", "Perspective Plane Numerator", -780, -370, value_2=-1.0)
        perspective_t = _math(group, "DIVIDE", "Perspective Ray Distance", -600, -320)
        links.new(inp.outputs["Camera To Source M23"], perspective_numerator.inputs[0])
        links.new(perspective_numerator.outputs[0], perspective_t.inputs[0])
        links.new(perspective_denominator, perspective_t.inputs[1])
        perspective_point = _node(group, "ShaderNodeVectorMath", "Perspective Source Plane Hit", -390, -280)
        perspective_point.operation = "SCALE"
        links.new(camera_coords.outputs["Object"], perspective_point.inputs[0])
        links.new(perspective_t.outputs[0], perspective_point.inputs["Scale"])

        # Orthographic: X/Y stay constant along the camera ray; solve only Z.
        ortho_x_term = _math(group, "MULTIPLY", "Ortho Plane X", -1160, -610)
        ortho_y_term = _math(group, "MULTIPLY", "Ortho Plane Y", -1160, -680)
        ortho_xy = _math(group, "ADD", "Ortho Plane XY", -970, -640)
        ortho_offset = _math(group, "ADD", "Ortho Plane With Offset", -790, -640)
        ortho_negated = _math(group, "MULTIPLY", "Ortho Plane Negated", -610, -640, value_2=-1.0)
        ortho_z = _math(group, "DIVIDE", "Orthographic Source Plane Z", -430, -640)
        links.new(camera_sep.outputs["X"], ortho_x_term.inputs[0]); links.new(inp.outputs["Camera To Source M20"], ortho_x_term.inputs[1])
        links.new(camera_sep.outputs["Y"], ortho_y_term.inputs[0]); links.new(inp.outputs["Camera To Source M21"], ortho_y_term.inputs[1])
        links.new(ortho_x_term.outputs[0], ortho_xy.inputs[0]); links.new(ortho_y_term.outputs[0], ortho_xy.inputs[1])
        links.new(ortho_xy.outputs[0], ortho_offset.inputs[0]); links.new(inp.outputs["Camera To Source M23"], ortho_offset.inputs[1])
        links.new(ortho_offset.outputs[0], ortho_negated.inputs[0])
        links.new(ortho_negated.outputs[0], ortho_z.inputs[0]); links.new(inp.outputs["Camera To Source M22"], ortho_z.inputs[1])
        ortho_point = _node(group, "ShaderNodeCombineXYZ", "Orthographic Source Plane Hit", -210, -610)
        links.new(camera_sep.outputs["X"], ortho_point.inputs["X"]); links.new(camera_sep.outputs["Y"], ortho_point.inputs["Y"]); links.new(ortho_z.outputs[0], ortho_point.inputs["Z"])

        ray_mode = _mix_rgb(group, "MIX", "Camera Ray Type", 0, -330)
        try:
            ray_mode.use_clamp = False
        except AttributeError:
            pass
        links.new(inp.outputs["Camera Perspective"], ray_mode.inputs[0])
        links.new(ortho_point.outputs[0], ray_mode.inputs[1])
        links.new(perspective_point.outputs[0], ray_mode.inputs[2])
        hit_sep = _node(group, "ShaderNodeSeparateXYZ", "Separate Source Plane Hit", 190, -330)
        links.new(ray_mode.outputs[0], hit_sep.inputs[0])

        def _source_local_component(prefix, row, y):
            terms = []
            for column, socket in enumerate((hit_sep.outputs["X"], hit_sep.outputs["Y"], hit_sep.outputs["Z"])):
                term = _math(group, "MULTIPLY", f"{prefix} M{row}{column}", 390, y - column * 70)
                links.new(socket, term.inputs[0])
                links.new(inp.outputs[f"Camera To Source M{row}{column}"], term.inputs[1])
                terms.append(term.outputs[0])
            first = _math(group, "ADD", f"{prefix} First Sum", 580, y - 35)
            total = _math(group, "ADD", f"{prefix} Linear Sum", 760, y - 55)
            translated = _math(group, "ADD", f"{prefix} With Translation", 940, y - 55)
            links.new(terms[0], first.inputs[0]); links.new(terms[1], first.inputs[1])
            links.new(first.outputs[0], total.inputs[0]); links.new(terms[2], total.inputs[1])
            links.new(total.outputs[0], translated.inputs[0]); links.new(inp.outputs[f"Camera To Source M{row}3"], translated.inputs[1])
            return translated.outputs[0]

        source_local_x = _source_local_component("Source Local X", 0, -180)
        source_local_y = _source_local_component("Source Local Y", 1, -500)
        camera_map_x = _node(group, "ShaderNodeMapRange", "Map Camera Source X", 1140, -210)
        camera_map_y = _node(group, "ShaderNodeMapRange", "Map Camera Source Y", 1140, -480)
        for mapper in (camera_map_x, camera_map_y):
            mapper.interpolation_type = "LINEAR"
            mapper.clamp = False
        links.new(source_local_x, camera_map_x.inputs["Value"]); links.new(inp.outputs["Source Min X"], camera_map_x.inputs["From Min"]); links.new(inp.outputs["Source Max X"], camera_map_x.inputs["From Max"]); links.new(inp.outputs["Source UV Min X"], camera_map_x.inputs["To Min"]); links.new(inp.outputs["Source UV Max X"], camera_map_x.inputs["To Max"])
        links.new(source_local_y, camera_map_y.inputs["Value"]); links.new(inp.outputs["Source Min Y"], camera_map_y.inputs["From Min"]); links.new(inp.outputs["Source Max Y"], camera_map_y.inputs["From Max"]); links.new(inp.outputs["Source UV Min Y"], camera_map_y.inputs["To Min"]); links.new(inp.outputs["Source UV Max Y"], camera_map_y.inputs["To Max"])
        camera_uv = _node(group, "ShaderNodeCombineXYZ", "Camera Projected UV", 1370, -330)
        links.new(camera_map_x.outputs["Result"], camera_uv.inputs["X"]); links.new(camera_map_y.outputs["Result"], camera_uv.inputs["Y"])

        camera_mix = _mix_rgb(group, "MIX", "Clipping Projection Mode", 1550, 180)
        try:
            camera_mix.use_clamp = False
        except AttributeError:
            pass
        links.new(inp.outputs["Use Camera Projection"], camera_mix.inputs[0])
        links.new(uv_mix.outputs[0], camera_mix.inputs[1])
        links.new(camera_uv.outputs[0], camera_mix.inputs[2])
        coordinate_output = camera_mix.outputs[0]

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

    links.new(coordinate_output, uv_sep.inputs[0])
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

    matte_uv = uv_final.outputs[0]
    if source_opacity:
        # Mirror the source layer Pixelate UV stage in the matte sampler.  This
        # makes clipping follow a pixelated source silhouette instead of the
        # unpixelated original alpha.
        px_offset = _node(group, "ShaderNodeCombineXYZ", "Source Pixel Offset", 1040, 770)
        px_shifted = _vector_math(group, "ADD", "Source Pixel Offset UV", 1210, 650)
        px_rotate = _node(group, "ShaderNodeVectorRotate", "Source Pixel Rotate", 1390, 650)
        px_rotate.rotation_type = "Z_AXIS"
        px_rotate.inputs["Center"].default_value = (0.5, 0.5, 0.0)
        px_sep = _node(group, "ShaderNodeSeparateXYZ", "Source Pixel Separate", 1570, 650)
        px_x_mul = _math(group, "MULTIPLY", "Source Pixel X Cells", 1750, 760)
        px_x_floor = _math(group, "FLOOR", "Source Pixel X Floor", 1930, 760)
        px_x_half = _math(group, "ADD", "Source Pixel X Center", 2110, 760, value_2=0.5)
        px_x_div = _math(group, "DIVIDE", "Source Pixel X Normalize", 2290, 760)
        px_y_mul = _math(group, "MULTIPLY", "Source Pixel Y Cells", 1750, 520)
        px_y_floor = _math(group, "FLOOR", "Source Pixel Y Floor", 1930, 520)
        px_y_half = _math(group, "ADD", "Source Pixel Y Center", 2110, 520, value_2=0.5)
        px_y_div = _math(group, "DIVIDE", "Source Pixel Y Normalize", 2290, 520)
        px_combine = _node(group, "ShaderNodeCombineXYZ", "Source Pixel UV", 2470, 650)
        px_inverse = _math(group, "MULTIPLY", "Source Pixel Inverse Rotation", 2290, 400, value_2=-1.0)
        px_unrotate = _node(group, "ShaderNodeVectorRotate", "Source Pixel Restore", 2650, 650)
        px_unrotate.rotation_type = "Z_AXIS"
        px_unrotate.inputs["Center"].default_value = (0.5, 0.5, 0.0)
        px_restore = _vector_math(group, "SUBTRACT", "Source Pixel Restore Offset", 2830, 650)
        links.new(inp.outputs["Source Pixel Offset X"], px_offset.inputs["X"])
        links.new(inp.outputs["Source Pixel Offset Y"], px_offset.inputs["Y"])
        links.new(uv_final.outputs[0], px_shifted.inputs[0]); links.new(px_offset.outputs[0], px_shifted.inputs[1])
        links.new(px_shifted.outputs[0], px_rotate.inputs["Vector"]); links.new(inp.outputs["Source Pixel Rotation"], px_rotate.inputs["Angle"])
        links.new(px_rotate.outputs["Vector"], px_sep.inputs[0])
        links.new(px_sep.outputs["X"], px_x_mul.inputs[0]); links.new(inp.outputs["Source Pixels X"], px_x_mul.inputs[1])
        links.new(px_x_mul.outputs[0], px_x_floor.inputs[0]); links.new(px_x_floor.outputs[0], px_x_half.inputs[0])
        links.new(px_x_half.outputs[0], px_x_div.inputs[0]); links.new(inp.outputs["Source Pixels X"], px_x_div.inputs[1])
        links.new(px_sep.outputs["Y"], px_y_mul.inputs[0]); links.new(inp.outputs["Source Pixels Y"], px_y_mul.inputs[1])
        links.new(px_y_mul.outputs[0], px_y_floor.inputs[0]); links.new(px_y_floor.outputs[0], px_y_half.inputs[0])
        links.new(px_y_half.outputs[0], px_y_div.inputs[0]); links.new(inp.outputs["Source Pixels Y"], px_y_div.inputs[1])
        links.new(px_x_div.outputs[0], px_combine.inputs["X"]); links.new(px_y_div.outputs[0], px_combine.inputs["Y"]); links.new(px_sep.outputs["Z"], px_combine.inputs["Z"])
        links.new(inp.outputs["Source Pixel Rotation"], px_inverse.inputs[0])
        links.new(px_combine.outputs[0], px_unrotate.inputs["Vector"]); links.new(px_inverse.outputs[0], px_unrotate.inputs["Angle"])
        links.new(px_unrotate.outputs["Vector"], px_restore.inputs[0]); links.new(px_offset.outputs[0], px_restore.inputs[1])
        matte_uv = _uv_mix(group, uv_final.outputs[0], px_restore.outputs[0], inp.outputs["Use Source Pixelate"], prefix="Source Pixelate Matte", x=3020, y=650)

    links.new(matte_uv, image.inputs["Vector"])

    if luma:
        bw = _node(group, "ShaderNodeRGBToBW", "Matte Luminance", -760, 260)
        luma_alpha = _math(group, "MULTIPLY", "Luminance Alpha", -580, 210)
        links.new(image.outputs["Color"], bw.inputs[0])
        links.new(bw.outputs[0], luma_alpha.inputs[0])
        links.new(image.outputs["Alpha"], luma_alpha.inputs[1])
        raw_source = luma_alpha.outputs[0]
    else:
        raw_source = image.outputs["Alpha"]

    if source_opacity:
        # Mirror Chroma Key's alpha stage from the source layer so clipping uses
        # keyed transparency immediately, without requiring a baked proxy.
        ck_distance = _vector_math(group, "DISTANCE", "Source Chroma Distance", -1040, -430)
        ck_low = _math(group, "SUBTRACT", "Source Chroma Lower", -860, -560)
        ck_high = _math(group, "ADD", "Source Chroma Upper", -860, -660)
        ck_range = _node(group, "ShaderNodeMapRange", "Source Chroma Softness", -660, -500)
        ck_range.interpolation_type = "SMOOTHERSTEP"
        ck_range.inputs["To Min"].default_value = 0.0
        ck_range.inputs["To Max"].default_value = 1.0
        ck_inverse = _math(group, "SUBTRACT", "Source Chroma Inverse", -460, -610, value_1=1.0)
        ck_normal_weight = _math(group, "SUBTRACT", "Source Chroma Normal Weight", -460, -450, value_1=1.0)
        ck_normal = _math(group, "MULTIPLY", "Source Chroma Normal", -260, -450)
        ck_inverted = _math(group, "MULTIPLY", "Source Chroma Inverted", -260, -610)
        ck_mask = _math(group, "ADD", "Source Chroma Mask", -60, -520)
        ck_keyed = _math(group, "MULTIPLY", "Source Chroma Keyed Alpha", 140, -520)
        ck_delta = _math(group, "SUBTRACT", "Source Chroma Alpha Delta", 340, -520)
        ck_scaled = _math(group, "MULTIPLY", "Source Chroma Alpha Scale", 540, -520)
        ck_mixed = _math(group, "ADD", "Source Chroma Alpha Result", 740, -520)
        links.new(image.outputs["Color"], ck_distance.inputs[0]); links.new(inp.outputs["Source Key Color"], ck_distance.inputs[1])
        links.new(inp.outputs["Source Key Tolerance"], ck_low.inputs[0]); links.new(inp.outputs["Source Key Softness"], ck_low.inputs[1])
        links.new(inp.outputs["Source Key Tolerance"], ck_high.inputs[0]); links.new(inp.outputs["Source Key Softness"], ck_high.inputs[1])
        links.new(_output(ck_distance, "Value", 1), ck_range.inputs["Value"])
        links.new(ck_low.outputs[0], ck_range.inputs["From Min"]); links.new(ck_high.outputs[0], ck_range.inputs["From Max"])
        links.new(ck_range.outputs["Result"], ck_inverse.inputs[1])
        links.new(inp.outputs["Source Key Invert"], ck_normal_weight.inputs[1])
        links.new(ck_range.outputs["Result"], ck_normal.inputs[0]); links.new(ck_normal_weight.outputs[0], ck_normal.inputs[1])
        links.new(ck_inverse.outputs[0], ck_inverted.inputs[0]); links.new(inp.outputs["Source Key Invert"], ck_inverted.inputs[1])
        links.new(ck_normal.outputs[0], ck_mask.inputs[0]); links.new(ck_inverted.outputs[0], ck_mask.inputs[1])
        links.new(raw_source, ck_keyed.inputs[0]); links.new(ck_mask.outputs[0], ck_keyed.inputs[1])
        links.new(ck_keyed.outputs[0], ck_delta.inputs[0]); links.new(raw_source, ck_delta.inputs[1])
        links.new(ck_delta.outputs[0], ck_scaled.inputs[0]); links.new(inp.outputs["Use Source Chroma Key"], ck_scaled.inputs[1])
        links.new(raw_source, ck_mixed.inputs[0]); links.new(ck_scaled.outputs[0], ck_mixed.inputs[1])
        raw_source = ck_mixed.outputs[0]

        visible_source = _math(group, "MULTIPLY", "Visible Source Alpha", -390, 40)
        links.new(raw_source, visible_source.inputs[0])
        links.new(inp.outputs["Source Opacity"], visible_source.inputs[1])
        raw_source = visible_source.outputs[0]

    if luma:
        low = _math(group, "SUBTRACT", "Luma Lower Bound", -580, 20)
        safe_softness = _math(group, "MAXIMUM", "Safe Luma Softness", -760, -100, value_2=0.0001)
        high = _math(group, "ADD", "Luma Upper Bound", -400, 20)
        ramp = _node(group, "ShaderNodeMapRange", "Luma Matte Transition", -190, 170)
        ramp.interpolation_type = "SMOOTHERSTEP"
        ramp.clamp = True
        ramp.inputs["To Min"].default_value = 0.0
        ramp.inputs["To Max"].default_value = 1.0
        links.new(inp.outputs["Softness"], safe_softness.inputs[0])
        links.new(inp.outputs["Threshold"], low.inputs[0])
        links.new(safe_softness.outputs[0], low.inputs[1])
        links.new(inp.outputs["Threshold"], high.inputs[0])
        links.new(safe_softness.outputs[0], high.inputs[1])
        links.new(raw_source, ramp.inputs["Value"])
        links.new(low.outputs[0], ramp.inputs["From Min"])
        links.new(high.outputs[0], ramp.inputs["From Max"])
        matte = ramp.outputs["Result"]
    else:
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
    group["fbp_track_matte_contract_version"] = 10
    return group


def _create_alpha_matte(name):
    return _create_track_matte(name, luma=False)


def _create_clipping_mask(name):
    return _create_track_matte(name, luma=False, source_opacity=True)


def _create_imported_mask(name):
    """Create an alpha mask sampled from an imported full-canvas grayscale PNG."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Mask Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Preview", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    _socket(group, "Mask Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    image = _node(group, "ShaderNodeTexImage", "Imported Layer Mask", -780, 120)
    image["fbp_imported_mask_image_node"] = True
    try:
        image.interpolation = "Linear"
        image.extension = "CLIP"
    except (AttributeError, TypeError, ValueError):
        pass
    bw = _node(group, "ShaderNodeRGBToBW", "Imported Mask Value", -560, 120)
    available = _math(group, "MULTIPLY", "Available Imported Mask", -360, 120)
    missing = _math(group, "SUBTRACT", "Missing Imported Mask", -360, -40, value_1=1.0)
    source = _math(group, "ADD", "Imported Mask or Pass Through", -160, 80)
    inverse = _math(group, "SUBTRACT", "Imported Mask Inverse", 20, -20, value_1=1.0)
    normal_weight = _math(group, "SUBTRACT", "Imported Mask Normal Weight", 20, 150, value_1=1.0)
    normal_part = _math(group, "MULTIPLY", "Imported Mask Normal", 200, 150)
    inverse_part = _math(group, "MULTIPLY", "Imported Mask Inverted", 200, -20)
    selected = _math(group, "ADD", "Selected Imported Mask", 380, 70)
    factor_part = _math(group, "MULTIPLY", "Imported Mask Factor", 560, 100)
    original_weight = _math(group, "SUBTRACT", "Imported Mask Original Weight", 560, -40, value_1=1.0)
    effective = _math(group, "ADD", "Effective Imported Mask", 740, 50)
    result = _math(group, "MULTIPLY", "Imported Mask Alpha", 920, 50)

    links.new(inp.outputs["UV Vector"], image.inputs["Vector"])
    links.new(image.outputs["Color"], bw.inputs[0])
    links.new(bw.outputs[0], available.inputs[0])
    links.new(inp.outputs["Use Mask Sample"], available.inputs[1])
    links.new(inp.outputs["Use Mask Sample"], missing.inputs[1])
    links.new(available.outputs[0], source.inputs[0])
    links.new(missing.outputs[0], source.inputs[1])
    links.new(source.outputs[0], inverse.inputs[1])
    links.new(inp.outputs["Invert"], normal_weight.inputs[1])
    links.new(source.outputs[0], normal_part.inputs[0])
    links.new(normal_weight.outputs[0], normal_part.inputs[1])
    links.new(inverse.outputs[0], inverse_part.inputs[0])
    links.new(inp.outputs["Invert"], inverse_part.inputs[1])
    links.new(normal_part.outputs[0], selected.inputs[0])
    links.new(inverse_part.outputs[0], selected.inputs[1])
    links.new(selected.outputs[0], factor_part.inputs[0])
    links.new(inp.outputs["Factor"], factor_part.inputs[1])
    links.new(inp.outputs["Factor"], original_weight.inputs[1])
    links.new(factor_part.outputs[0], effective.inputs[0])
    links.new(original_weight.outputs[0], effective.inputs[1])
    links.new(inp.outputs["Alpha In"], result.inputs[0])
    links.new(effective.outputs[0], result.inputs[1])
    links.new(result.outputs[0], out.inputs["Alpha Out"])
    links.new(effective.outputs[0], out.inputs["Mask Out"])
    group["fbp_imported_mask_contract_version"] = 1
    return group


def _create_layer_blend(name):
    """Create a pairwise layer blend from an image or flat procedural RGBA."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Source Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Source Color", "INPUT", "NodeSocketColor", default=(0.0, 0.0, 0.0, 0.0))
    _socket(group, "Source Alpha", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Use Procedural Source", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Source Opacity", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Use Hard Light", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links

    image = _node(group, "ShaderNodeTexImage", "Layer Below Image", -720, 80)
    image["fbp_mask_source_image_node"] = True
    try:
        image.interpolation = "Linear"
        image.extension = "CLIP"
    except (AttributeError, TypeError, ValueError):
        pass
    source_selector = _mix_rgb(group, "MIX", "Layer Below Source Selector", -520, 230)
    normal = _mix_rgb(group, "MULTIPLY", "Imported Blend Mode", -420, 150)
    normal["fbp_layer_blend_mix_node"] = True
    hard = _mix_rgb(group, "OVERLAY", "Hard Light", -420, -80)
    selector = _mix_rgb(group, "MIX", "Blend Mode Selector", -160, 80)
    inverse_procedural = _math(group, "SUBTRACT", "Use Image Source", -500, -260)
    image_available = _math(group, "MULTIPLY", "Image Source Alpha", -300, -250)
    procedural_available = _math(group, "MULTIPLY", "Procedural Source Alpha", -300, -330)
    availability = _math(group, "ADD", "Blend Source Alpha", -110, -280)
    opacity = _math(group, "MULTIPLY", "Blend Source Opacity", 70, -230)
    effective = _math(group, "MULTIPLY", "Blend Source Availability", 250, -180)
    effective_factor = _math(group, "MULTIPLY", "Layer Blend Factor", 430, -100)
    final = _mix_rgb(group, "MIX", "Layer Blend Result", 240, 80)
    try:
        source_selector.inputs[0].default_value = 0.0
        normal.inputs[0].default_value = 1.0
        hard.inputs[0].default_value = 1.0
        inverse_procedural.inputs[0].default_value = 1.0
    except (AttributeError, IndexError, TypeError, ValueError):
        pass

    links.new(inp.outputs["UV Vector"], image.inputs["Vector"])
    links.new(inp.outputs["Use Procedural Source"], source_selector.inputs[0])
    links.new(image.outputs["Color"], source_selector.inputs[1])
    links.new(inp.outputs["Source Color"], source_selector.inputs[2])
    links.new(source_selector.outputs[0], normal.inputs[1])
    links.new(inp.outputs["Color In"], normal.inputs[2])
    # Photoshop Hard Light is Overlay with the foreground/background roles swapped.
    links.new(inp.outputs["Color In"], hard.inputs[1])
    links.new(source_selector.outputs[0], hard.inputs[2])
    links.new(inp.outputs["Use Hard Light"], selector.inputs[0])
    links.new(normal.outputs[0], selector.inputs[1])
    links.new(hard.outputs[0], selector.inputs[2])
    links.new(inp.outputs["Use Procedural Source"], inverse_procedural.inputs[1])
    links.new(image.outputs["Alpha"], image_available.inputs[0])
    links.new(inverse_procedural.outputs[0], image_available.inputs[1])
    links.new(inp.outputs["Source Alpha"], procedural_available.inputs[0])
    links.new(inp.outputs["Use Procedural Source"], procedural_available.inputs[1])
    links.new(image_available.outputs[0], availability.inputs[0])
    links.new(procedural_available.outputs[0], availability.inputs[1])
    links.new(availability.outputs[0], opacity.inputs[0])
    links.new(inp.outputs["Source Opacity"], opacity.inputs[1])
    links.new(opacity.outputs[0], effective.inputs[0])
    links.new(inp.outputs["Use Source Sample"], effective.inputs[1])
    links.new(effective.outputs[0], effective_factor.inputs[0])
    links.new(inp.outputs["Factor"], effective_factor.inputs[1])
    links.new(effective_factor.outputs[0], final.inputs[0])
    links.new(inp.outputs["Color In"], final.inputs[1])
    links.new(selector.outputs[0], final.inputs[2])
    links.new(final.outputs[0], out.inputs["Color Out"])
    group["fbp_layer_blend_contract_version"] = 2
    return group


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

    # The SDF edge is encoded at 0.5. Feather must soften *inside* the
    # editable silhouette only. A symmetric 0.5 +/- Feather range leaks a
    # positive mask into the rectangular SDF atlas at high values, making the
    # image bounds visible. Map 0.5 -> 0.5 + width instead: pixels outside the
    # polygon remain exactly zero while the interior dissolves progressively.
    feather_width = _math(group, "MULTIPLY", "Shape Mask Feather Width", -100, 460, value_2=0.5)
    safe_width = _math(group, "MAXIMUM", "Safe Shape Mask Feather", 80, 460, value_2=0.0005)
    upper = _math(group, "ADD", "Shape Mask Inner Feather Limit", 260, 420, value_1=0.5)
    ramp = _node(group, "ShaderNodeMapRange", "Editable Shape Mask Feather", 480, 260)
    ramp.interpolation_type = "SMOOTHERSTEP"
    ramp.clamp = True
    ramp.inputs["From Min"].default_value = 0.5
    ramp.inputs["To Min"].default_value = 0.0
    ramp.inputs["To Max"].default_value = 1.0
    links.new(inp.outputs["Feather"], feather_width.inputs[0])
    links.new(feather_width.outputs[0], safe_width.inputs[0])
    links.new(safe_width.outputs[0], upper.inputs[1])
    links.new(image.outputs["Alpha"], ramp.inputs["Value"])
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
    group["fbp_object_mask_contract_version"] = 4
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


def _create_luminance_mask(name):
    """Create an alpha-safe luminance-range mask with normalized softness."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Image Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Minimum", "INPUT", "NodeSocketFloat", default=0.2, minimum=0.0, maximum=1.0)
    _socket(group, "Maximum", "INPUT", "NodeSocketFloat", default=0.8, minimum=0.0, maximum=1.0)
    _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=0.1, minimum=0.0, maximum=1.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Preview", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    _socket(group, "Mask Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    image = _node(group, "ShaderNodeTexImage", "Luminance Mask Source", -1040, 180)
    image["fbp_matrix_source_image_node"] = True
    image["fbp_source_interpolation"] = "Linear"
    try:
        image.interpolation = "Linear"
        image.extension = "EXTEND"
    except (AttributeError, TypeError, ValueError):
        pass

    luminance = _node(group, "ShaderNodeRGBToBW", "Source Luminance", -820, 180)
    ordered_min = _math(group, "MINIMUM", "Ordered Luminance Minimum", -820, -80)
    ordered_max = _math(group, "MAXIMUM", "Ordered Luminance Maximum", -820, -210)
    span = _math(group, "SUBTRACT", "Luminance Selected Span", -600, -180)
    half_span = _math(group, "MULTIPLY", "Luminance Half Span", -420, -180, value_2=0.5)
    edge_width = _math(group, "MULTIPLY", "Luminance Soft Edge", -240, -180)
    safe_edge = _math(group, "MAXIMUM", "Safe Luminance Soft Edge", -60, -180, value_2=0.00001)
    lower_end = _math(group, "ADD", "Luminance Lower Soft End", 120, -40)
    upper_start = _math(group, "SUBTRACT", "Luminance Upper Soft Start", 120, -230)

    lower = _node(group, "ShaderNodeMapRange", "Luminance Lower Range", 350, 210)
    lower.interpolation_type = "SMOOTHERSTEP"
    lower.clamp = True
    lower.inputs["To Min"].default_value = 0.0
    lower.inputs["To Max"].default_value = 1.0

    upper = _node(group, "ShaderNodeMapRange", "Luminance Upper Range", 350, -80)
    upper.interpolation_type = "SMOOTHERSTEP"
    upper.clamp = True
    upper.inputs["To Min"].default_value = 1.0
    upper.inputs["To Max"].default_value = 0.0

    band = _math(group, "MULTIPLY", "Luminance Range Mask", 600, 120)
    source_alpha = _math(group, "MULTIPLY", "Luminance Mask Source Alpha", 790, 120)

    links.new(inp.outputs["UV Vector"], image.inputs["Vector"])
    links.new(image.outputs["Color"], luminance.inputs["Color"])
    links.new(inp.outputs["Minimum"], ordered_min.inputs[0])
    links.new(inp.outputs["Maximum"], ordered_min.inputs[1])
    links.new(inp.outputs["Minimum"], ordered_max.inputs[0])
    links.new(inp.outputs["Maximum"], ordered_max.inputs[1])
    links.new(ordered_max.outputs[0], span.inputs[0])
    links.new(ordered_min.outputs[0], span.inputs[1])
    links.new(span.outputs[0], half_span.inputs[0])
    links.new(half_span.outputs[0], edge_width.inputs[0])
    links.new(inp.outputs["Softness"], edge_width.inputs[1])
    links.new(edge_width.outputs[0], safe_edge.inputs[0])
    links.new(ordered_min.outputs[0], lower_end.inputs[0])
    links.new(safe_edge.outputs[0], lower_end.inputs[1])
    links.new(ordered_max.outputs[0], upper_start.inputs[0])
    links.new(safe_edge.outputs[0], upper_start.inputs[1])

    links.new(luminance.outputs["Val"], lower.inputs["Value"])
    links.new(ordered_min.outputs[0], lower.inputs["From Min"])
    links.new(lower_end.outputs[0], lower.inputs["From Max"])
    links.new(luminance.outputs["Val"], upper.inputs["Value"])
    links.new(upper_start.outputs[0], upper.inputs["From Min"])
    links.new(ordered_max.outputs[0], upper.inputs["From Max"])
    links.new(lower.outputs["Result"], band.inputs[0])
    links.new(upper.outputs["Result"], band.inputs[1])
    links.new(band.outputs[0], source_alpha.inputs[0])
    links.new(image.outputs["Alpha"], source_alpha.inputs[1])

    group["fbp_generated_mask_contract_version"] = 3
    return _finish_generated_mask(
        group, inp, out, source_alpha.outputs[0], prefix="Luminance Mask",
        x=980, y=120, availability=inp.outputs["Use Image Sample"],
    )


def _create_channel_mask(name):
    """Create an alpha-safe source-channel mask with normalized softness."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Image Sample", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Channel", "INPUT", "NodeSocketFloat", default=4.0, minimum=0.0, maximum=4.0)
    _socket(group, "Minimum", "INPUT", "NodeSocketFloat", default=0.2, minimum=0.0, maximum=1.0)
    _socket(group, "Maximum", "INPUT", "NodeSocketFloat", default=0.8, minimum=0.0, maximum=1.0)
    _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=0.1, minimum=0.0, maximum=1.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Preview", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    _socket(group, "Mask Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    image = _node(group, "ShaderNodeTexImage", "Channel Mask Source", -1340, 220)
    image["fbp_matrix_source_image_node"] = True
    image["fbp_source_interpolation"] = "Linear"
    try:
        image.interpolation = "Linear"
        image.extension = "EXTEND"
    except (AttributeError, TypeError, ValueError):
        pass

    separate = _node(group, "ShaderNodeSeparateXYZ", "Source RGB Channels", -1120, 320)
    luminance = _node(group, "ShaderNodeRGBToBW", "Source Luminance", -1120, 80)
    links.new(inp.outputs["UV Vector"], image.inputs["Vector"])
    links.new(image.outputs["Color"], separate.inputs[0])
    links.new(image.outputs["Color"], luminance.inputs["Color"])

    channel_sources = (
        separate.outputs["X"], separate.outputs["Y"], separate.outputs["Z"],
        image.outputs["Alpha"], luminance.outputs["Val"],
    )
    selected_parts = []
    alpha_selector = None
    for index, source in enumerate(channel_sources):
        selector = _math(group, "COMPARE", f"Select Channel {index}", -900, 400 - index * 120)
        selector.inputs[1].default_value = float(index)
        selector.inputs[2].default_value = 0.1
        links.new(inp.outputs["Channel"], selector.inputs[0])
        part = _math(group, "MULTIPLY", f"Channel {index} Part", -680, 400 - index * 120)
        links.new(source, part.inputs[0])
        links.new(selector.outputs[0], part.inputs[1])
        selected_parts.append(part.outputs[0])
        if index == 3:
            alpha_selector = selector.outputs[0]

    sum_a = _math(group, "ADD", "Channel Sum A", -440, 300)
    sum_b = _math(group, "ADD", "Channel Sum B", -440, 100)
    sum_c = _math(group, "ADD", "Channel Sum C", -220, 220)
    selected = _math(group, "ADD", "Selected Channel", 0, 180)
    links.new(selected_parts[0], sum_a.inputs[0])
    links.new(selected_parts[1], sum_a.inputs[1])
    links.new(selected_parts[2], sum_b.inputs[0])
    links.new(selected_parts[3], sum_b.inputs[1])
    links.new(sum_a.outputs[0], sum_c.inputs[0])
    links.new(sum_b.outputs[0], sum_c.inputs[1])
    links.new(sum_c.outputs[0], selected.inputs[0])
    links.new(selected_parts[4], selected.inputs[1])

    ordered_min = _math(group, "MINIMUM", "Ordered Channel Minimum", 0, -40)
    ordered_max = _math(group, "MAXIMUM", "Ordered Channel Maximum", 0, -160)
    span = _math(group, "SUBTRACT", "Channel Selected Span", 220, -130)
    half_span = _math(group, "MULTIPLY", "Channel Half Span", 400, -130, value_2=0.5)
    edge_width = _math(group, "MULTIPLY", "Channel Soft Edge", 580, -130)
    safe_edge = _math(group, "MAXIMUM", "Safe Channel Soft Edge", 760, -130, value_2=0.00001)
    lower_end = _math(group, "ADD", "Channel Lower Soft End", 940, -20)
    upper_start = _math(group, "SUBTRACT", "Channel Upper Soft Start", 940, -220)
    links.new(inp.outputs["Minimum"], ordered_min.inputs[0])
    links.new(inp.outputs["Maximum"], ordered_min.inputs[1])
    links.new(inp.outputs["Minimum"], ordered_max.inputs[0])
    links.new(inp.outputs["Maximum"], ordered_max.inputs[1])
    links.new(ordered_max.outputs[0], span.inputs[0])
    links.new(ordered_min.outputs[0], span.inputs[1])
    links.new(span.outputs[0], half_span.inputs[0])
    links.new(half_span.outputs[0], edge_width.inputs[0])
    links.new(inp.outputs["Softness"], edge_width.inputs[1])
    links.new(edge_width.outputs[0], safe_edge.inputs[0])
    links.new(ordered_min.outputs[0], lower_end.inputs[0])
    links.new(safe_edge.outputs[0], lower_end.inputs[1])
    links.new(ordered_max.outputs[0], upper_start.inputs[0])
    links.new(safe_edge.outputs[0], upper_start.inputs[1])

    lower = _node(group, "ShaderNodeMapRange", "Channel Lower Range", 1160, 220)
    lower.interpolation_type = "SMOOTHERSTEP"
    lower.clamp = True
    lower.inputs["To Min"].default_value = 0.0
    lower.inputs["To Max"].default_value = 1.0
    upper = _node(group, "ShaderNodeMapRange", "Channel Upper Range", 1160, -40)
    upper.interpolation_type = "SMOOTHERSTEP"
    upper.clamp = True
    upper.inputs["To Min"].default_value = 1.0
    upper.inputs["To Max"].default_value = 0.0
    links.new(selected.outputs[0], lower.inputs["Value"])
    links.new(ordered_min.outputs[0], lower.inputs["From Min"])
    links.new(lower_end.outputs[0], lower.inputs["From Max"])
    links.new(selected.outputs[0], upper.inputs["Value"])
    links.new(upper_start.outputs[0], upper.inputs["From Min"])
    links.new(ordered_max.outputs[0], upper.inputs["From Max"])

    band = _math(group, "MULTIPLY", "Channel Range Mask", 1390, 120)
    links.new(lower.outputs["Result"], band.inputs[0])
    links.new(upper.outputs["Result"], band.inputs[1])

    non_alpha = _math(group, "SUBTRACT", "Non Alpha Channel", 1390, -180, value_1=1.0)
    rgb_alpha = _math(group, "MULTIPLY", "RGB Channel Source Alpha", 1600, 60)
    alpha_part = _math(group, "MULTIPLY", "Alpha Channel Range", 1600, -100)
    source_mask = _math(group, "ADD", "Channel Mask Source Alpha", 1810, 20)
    links.new(alpha_selector, non_alpha.inputs[1])
    links.new(band.outputs[0], rgb_alpha.inputs[0])
    links.new(image.outputs["Alpha"], rgb_alpha.inputs[1])
    links.new(band.outputs[0], alpha_part.inputs[0])
    links.new(alpha_selector, alpha_part.inputs[1])
    non_alpha_weighted = _math(group, "MULTIPLY", "Non Alpha Range", 1600, 180)
    links.new(rgb_alpha.outputs[0], non_alpha_weighted.inputs[0])
    links.new(non_alpha.outputs[0], non_alpha_weighted.inputs[1])
    links.new(non_alpha_weighted.outputs[0], source_mask.inputs[0])
    links.new(alpha_part.outputs[0], source_mask.inputs[1])

    group["fbp_generated_mask_contract_version"] = 3
    return _finish_generated_mask(
        group, inp, out, source_mask.outputs[0], prefix="Channel Mask",
        x=1990, y=80, availability=inp.outputs["Use Image Sample"],
    )


def _create_gradient_mask(name):
    """Create a linear/radial UV-space mask with controller-aligned rotation."""
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

    center = _node(group, "ShaderNodeCombineXYZ", "Gradient Center", -1020, 0)
    centered = _vector_math(group, "SUBTRACT", "Centered Gradient UV", -820, 150)
    scaled = _vector_math(group, "SCALE", "Scaled Gradient UV", -620, 150)
    angle_sign = _math(group, "MULTIPLY", "Gradient Controller Angle", -620, -80, value_2=-1.0)
    rotate = _node(group, "ShaderNodeVectorRotate", "Rotate Gradient", -400, 150)
    rotate.rotation_type = "Z_AXIS"
    rotate.invert = False
    rotate.inputs["Center"].default_value = (0.0, 0.0, 0.0)
    separate = _node(group, "ShaderNodeSeparateXYZ", "Gradient Axis", -180, 220)
    linear = _math(group, "ADD", "Linear Gradient Coordinate", 10, 260, value_2=0.5)
    radial_distance = _vector_math(group, "LENGTH", "Radial Gradient Distance", -180, -80)
    radial_scaled = _math(group, "MULTIPLY", "Normalized Radial Distance", 10, -80, value_2=2.0)
    radial = _math(group, "SUBTRACT", "Radial Gradient Coordinate", 190, -80, value_1=1.0)
    linear_weight = _math(group, "SUBTRACT", "Linear Gradient Weight", 190, 260, value_1=1.0)
    linear_part = _math(group, "MULTIPLY", "Linear Gradient", 370, 260)
    radial_part = _math(group, "MULTIPLY", "Radial Gradient", 370, -80)
    selected = _math(group, "ADD", "Selected Gradient", 550, 100)
    half_feather = _math(group, "MULTIPLY", "Half Gradient Feather", 370, -250, value_2=0.5)
    lower = _math(group, "SUBTRACT", "Gradient Lower", 550, -240)
    upper = _math(group, "ADD", "Gradient Upper", 550, -360)
    epsilon_upper = _math(group, "ADD", "Gradient Minimum Width", 730, -430, value_2=0.00001)
    safe_upper = _math(group, "MAXIMUM", "Safe Gradient Upper", 910, -360)
    ramp = _node(group, "ShaderNodeMapRange", "Gradient Mask", 770, 100)
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
    links.new(inp.outputs["Angle"], angle_sign.inputs[0])
    links.new(scaled.outputs[0], rotate.inputs["Vector"])
    links.new(angle_sign.outputs[0], rotate.inputs["Angle"])
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
    group["fbp_generated_mask_contract_version"] = 3
    return _finish_generated_mask(group, inp, out, ramp.outputs["Result"], prefix="Gradient Mask", x=1080, y=110)


def _create_voronoi_mask(name):
    """Create an animatable Voronoi texture-map mask in UV space."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for socket_name, default, minimum, maximum in (
        ("Alpha In", 1.0, 0.0, 1.0), ("Scale", 5.0, 0.001, 1000.0),
        ("Aspect Ratio", 1.0, 0.001, 1000.0),
        ("Angle", 0.7853981633974483, -6.283185, 6.283185), ("Randomness", 0.5, 0.0, 1.0),
        ("Threshold", 0.5, 0.0, 1.0), ("Softness", 0.5, 0.0, 1.0),
        ("Seed", 0.0, -1000000.0, 1000000.0), ("Factor", 1.0, 0.0, 1.0),
        ("Invert", 0.0, 0.0, 1.0), ("Debug Preview", 0.0, 0.0, 1.0),
    ):
        _socket(group, socket_name, "INPUT", "NodeSocketFloat", default=default, minimum=minimum, maximum=maximum)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    _socket(group, "Mask Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    center = _node(group, "ShaderNodeCombineXYZ", "Voronoi Center", -850, -80)
    center.inputs["X"].default_value = 0.5
    center.inputs["Y"].default_value = 0.5
    centered = _vector_math(group, "SUBTRACT", "Centered Voronoi UV", -650, 150)
    separate_uv = _node(group, "ShaderNodeSeparateXYZ", "Voronoi Physical UV", -470, 280)
    aspect_x = _math(group, "MULTIPLY", "Voronoi Aspect X", -270, 360)
    isotropic_uv = _node(group, "ShaderNodeCombineXYZ", "Isotropic Voronoi UV", -70, 270)
    angle_sign = _math(group, "MULTIPLY", "Voronoi Angle", -270, -90, value_2=-1.0)
    rotate = _node(group, "ShaderNodeVectorRotate", "Rotate Voronoi", 130, 180)
    rotate.rotation_type = "Z_AXIS"
    rotate.inputs["Center"].default_value = (0.0, 0.0, 0.0)
    voronoi = _node(group, "ShaderNodeTexVoronoi", "Voronoi Mask Texture", 370, 180)
    try:
        voronoi.voronoi_dimensions = "4D"
        voronoi.feature = "F1"
        voronoi.distance = "EUCLIDEAN"
    except (AttributeError, TypeError, ValueError):
        pass

    half_softness = _math(group, "MULTIPLY", "Half Voronoi Softness", 50, -130, value_2=0.5)
    lower = _math(group, "SUBTRACT", "Voronoi Mask Lower", 230, -80)
    upper = _math(group, "ADD", "Voronoi Mask Upper", 230, -210)
    epsilon_upper = _math(group, "ADD", "Voronoi Minimum Width", 410, -280, value_2=0.00001)
    safe_upper = _math(group, "MAXIMUM", "Safe Voronoi Upper", 590, -210)
    ramp = _node(group, "ShaderNodeMapRange", "Voronoi Threshold Mask", 480, 140)
    ramp.interpolation_type = "SMOOTHERSTEP"
    ramp.clamp = True
    ramp.inputs["To Min"].default_value = 1.0
    ramp.inputs["To Max"].default_value = 0.0

    links.new(inp.outputs["UV Vector"], centered.inputs[0])
    links.new(center.outputs[0], centered.inputs[1])
    links.new(centered.outputs[0], separate_uv.inputs[0])
    links.new(separate_uv.outputs["X"], aspect_x.inputs[0])
    links.new(inp.outputs["Aspect Ratio"], aspect_x.inputs[1])
    links.new(aspect_x.outputs[0], isotropic_uv.inputs["X"])
    links.new(separate_uv.outputs["Y"], isotropic_uv.inputs["Y"])
    links.new(separate_uv.outputs["Z"], isotropic_uv.inputs["Z"])
    links.new(inp.outputs["Angle"], angle_sign.inputs[0])
    links.new(isotropic_uv.outputs[0], rotate.inputs["Vector"])
    links.new(angle_sign.outputs[0], rotate.inputs["Angle"])
    links.new(rotate.outputs["Vector"], voronoi.inputs["Vector"])
    for input_name, source_name in (("Scale", "Scale"), ("Randomness", "Randomness"), ("W", "Seed")):
        socket = _input(voronoi, input_name)
        if socket is not None:
            links.new(inp.outputs[source_name], socket)
    links.new(inp.outputs["Softness"], half_softness.inputs[0])
    links.new(inp.outputs["Threshold"], lower.inputs[0])
    links.new(half_softness.outputs[0], lower.inputs[1])
    links.new(inp.outputs["Threshold"], upper.inputs[0])
    links.new(half_softness.outputs[0], upper.inputs[1])
    links.new(lower.outputs[0], epsilon_upper.inputs[0])
    links.new(upper.outputs[0], safe_upper.inputs[0])
    links.new(epsilon_upper.outputs[0], safe_upper.inputs[1])
    distance = _output(voronoi, "Distance", 0)
    links.new(distance, ramp.inputs["Value"])
    links.new(lower.outputs[0], ramp.inputs["From Min"])
    links.new(safe_upper.outputs[0], ramp.inputs["From Max"])
    group["fbp_generated_mask_contract_version"] = 4
    return _finish_generated_mask(group, inp, out, ramp.outputs["Result"], prefix="Voronoi Mask", x=780, y=130)


def _create_wave_mask(name):
    """Create an animatable Wave texture-map mask in UV space."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for socket_name, default, minimum, maximum in (
        ("Alpha In", 1.0, 0.0, 1.0), ("Scale", 2.0, 0.001, 1000.0),
        ("Aspect Ratio", 1.0, 0.001, 1000.0),
        ("Angle", 0.7853981633974483, -6.283185, 6.283185), ("Distortion", 10.0, 0.0, 100.0),
        ("Detail", 5.0, 0.0, 15.0), ("Detail Scale", 1.75, 0.0, 1000.0),
        ("Detail Roughness", 0.0, 0.0, 1.0), ("Phase", 3.0, -1000000.0, 1000000.0),
        ("Threshold", 0.5, 0.0, 1.0), ("Softness", 0.0, 0.0, 1.0),
        ("Factor", 1.0, 0.0, 1.0), ("Invert", 0.0, 0.0, 1.0),
        ("Debug Preview", 0.0, 0.0, 1.0),
    ):
        _socket(group, socket_name, "INPUT", "NodeSocketFloat", default=default, minimum=minimum, maximum=maximum)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    _socket(group, "Mask Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    center = _node(group, "ShaderNodeCombineXYZ", "Wave Mask Center", -900, -80)
    center.inputs["X"].default_value = 0.5
    center.inputs["Y"].default_value = 0.5
    centered = _vector_math(group, "SUBTRACT", "Centered Wave UV", -700, 150)
    separate_uv = _node(group, "ShaderNodeSeparateXYZ", "Wave Physical UV", -520, 300)
    aspect_x = _math(group, "MULTIPLY", "Wave Aspect X", -320, 380)
    isotropic_uv = _node(group, "ShaderNodeCombineXYZ", "Isotropic Wave UV", -120, 290)
    angle_sign = _math(group, "MULTIPLY", "Wave Mask Angle", -320, -90, value_2=-1.0)
    rotate = _node(group, "ShaderNodeVectorRotate", "Rotate Wave Mask", 80, 170)
    rotate.rotation_type = "Z_AXIS"
    rotate.inputs["Center"].default_value = (0.0, 0.0, 0.0)
    wave = _node(group, "ShaderNodeTexWave", "Wave Mask Texture", -230, 150)
    try:
        wave.wave_type = "BANDS"
        wave.bands_direction = "X"
        wave.wave_profile = "SIN"
    except (AttributeError, TypeError, ValueError):
        pass
    to_bw = _node(group, "ShaderNodeRGBToBW", "Wave Mask Value", 0, 170)

    half_softness = _math(group, "MULTIPLY", "Half Wave Softness", 0, -130, value_2=0.5)
    lower = _math(group, "SUBTRACT", "Wave Mask Lower", 180, -80)
    upper = _math(group, "ADD", "Wave Mask Upper", 180, -210)
    epsilon_upper = _math(group, "ADD", "Wave Minimum Width", 360, -280, value_2=0.00001)
    safe_upper = _math(group, "MAXIMUM", "Safe Wave Upper", 540, -210)
    ramp = _node(group, "ShaderNodeMapRange", "Wave Threshold Mask", 430, 140)
    ramp.interpolation_type = "SMOOTHERSTEP"
    ramp.clamp = True
    ramp.inputs["To Min"].default_value = 0.0
    ramp.inputs["To Max"].default_value = 1.0

    links.new(inp.outputs["UV Vector"], centered.inputs[0])
    links.new(center.outputs[0], centered.inputs[1])
    links.new(centered.outputs[0], separate_uv.inputs[0])
    links.new(separate_uv.outputs["X"], aspect_x.inputs[0])
    links.new(inp.outputs["Aspect Ratio"], aspect_x.inputs[1])
    links.new(aspect_x.outputs[0], isotropic_uv.inputs["X"])
    links.new(separate_uv.outputs["Y"], isotropic_uv.inputs["Y"])
    links.new(separate_uv.outputs["Z"], isotropic_uv.inputs["Z"])
    links.new(inp.outputs["Angle"], angle_sign.inputs[0])
    links.new(isotropic_uv.outputs[0], rotate.inputs["Vector"])
    links.new(angle_sign.outputs[0], rotate.inputs["Angle"])
    links.new(rotate.outputs["Vector"], wave.inputs["Vector"])
    for input_name, source_name in (
        ("Scale", "Scale"), ("Distortion", "Distortion"), ("Detail", "Detail"),
        ("Detail Scale", "Detail Scale"), ("Detail Roughness", "Detail Roughness"),
        ("Phase Offset", "Phase"),
    ):
        socket = _input(wave, input_name)
        if socket is not None:
            links.new(inp.outputs[source_name], socket)
    color_output = _output(wave, "Color", 0)
    links.new(color_output, to_bw.inputs["Color"])
    links.new(inp.outputs["Softness"], half_softness.inputs[0])
    links.new(inp.outputs["Threshold"], lower.inputs[0])
    links.new(half_softness.outputs[0], lower.inputs[1])
    links.new(inp.outputs["Threshold"], upper.inputs[0])
    links.new(half_softness.outputs[0], upper.inputs[1])
    links.new(lower.outputs[0], epsilon_upper.inputs[0])
    links.new(upper.outputs[0], safe_upper.inputs[0])
    links.new(epsilon_upper.outputs[0], safe_upper.inputs[1])
    links.new(to_bw.outputs["Val"], ramp.inputs["Value"])
    links.new(lower.outputs[0], ramp.inputs["From Min"])
    links.new(safe_upper.outputs[0], ramp.inputs["From Max"])
    group["fbp_generated_mask_contract_version"] = 4
    return _finish_generated_mask(group, inp, out, ramp.outputs["Result"], prefix="Wave Mask", x=730, y=130)


def _create_noise_mask(name):
    """Create an animatable UV-space procedural noise mask."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Scale", "INPUT", "NodeSocketFloat", default=11.34, minimum=0.001, maximum=1000.0)
    _socket(group, "Aspect Ratio", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.001, maximum=1000.0)
    _socket(group, "Detail", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=15.0)
    _socket(group, "Roughness", "INPUT", "NodeSocketFloat", default=0.5, minimum=0.0, maximum=1.0)
    _socket(group, "Threshold", "INPUT", "NodeSocketFloat", default=0.5, minimum=0.0, maximum=1.0)
    _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Seed", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1000000.0, maximum=1000000.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Preview", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    _socket(group, "Mask Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    center = _node(group, "ShaderNodeCombineXYZ", "Noise Mask Center", -1050, -120)
    center.inputs["X"].default_value = 0.5
    center.inputs["Y"].default_value = 0.5
    centered = _vector_math(group, "SUBTRACT", "Centered Noise UV", -850, 140)
    separate_uv = _node(group, "ShaderNodeSeparateXYZ", "Noise Physical UV", -650, 300)
    aspect_x = _math(group, "MULTIPLY", "Noise Aspect X", -450, 380)
    isotropic_uv = _node(group, "ShaderNodeCombineXYZ", "Isotropic Noise UV", -250, 290)
    noise = _node(group, "ShaderNodeTexNoise", "Noise Mask Texture", -20, 160)
    try:
        noise.noise_dimensions = "4D"
    except (AttributeError, TypeError, ValueError):
        pass
    half_softness = _math(group, "MULTIPLY", "Half Noise Softness", -120, -170, value_2=0.5)
    lower = _math(group, "SUBTRACT", "Noise Mask Lower", -170, -100)
    upper = _math(group, "ADD", "Noise Mask Upper", -170, -230)
    epsilon_upper = _math(group, "ADD", "Noise Minimum Width", 10, -300, value_2=0.00001)
    safe_upper = _math(group, "MAXIMUM", "Safe Noise Upper", 190, -230)
    ramp = _node(group, "ShaderNodeMapRange", "Noise Threshold Mask", 80, 140)
    ramp.interpolation_type = "SMOOTHERSTEP"
    ramp.clamp = True
    ramp.inputs["To Min"].default_value = 0.0
    ramp.inputs["To Max"].default_value = 1.0

    links.new(inp.outputs["UV Vector"], centered.inputs[0])
    links.new(center.outputs[0], centered.inputs[1])
    links.new(centered.outputs[0], separate_uv.inputs[0])
    links.new(separate_uv.outputs["X"], aspect_x.inputs[0])
    links.new(inp.outputs["Aspect Ratio"], aspect_x.inputs[1])
    links.new(aspect_x.outputs[0], isotropic_uv.inputs["X"])
    links.new(separate_uv.outputs["Y"], isotropic_uv.inputs["Y"])
    links.new(separate_uv.outputs["Z"], isotropic_uv.inputs["Z"])
    vector_socket = _input(noise, "Vector")
    if vector_socket is not None:
        links.new(isotropic_uv.outputs[0], vector_socket)
    for input_name, source_name in (
        ("W", "Seed"), ("Scale", "Scale"),
        ("Detail", "Detail"), ("Roughness", "Roughness"),
    ):
        socket = _input(noise, input_name)
        if socket is not None:
            links.new(inp.outputs[source_name], socket)
    links.new(inp.outputs["Softness"], half_softness.inputs[0])
    links.new(inp.outputs["Threshold"], lower.inputs[0])
    links.new(half_softness.outputs[0], lower.inputs[1])
    links.new(inp.outputs["Threshold"], upper.inputs[0])
    links.new(half_softness.outputs[0], upper.inputs[1])
    links.new(lower.outputs[0], epsilon_upper.inputs[0])
    links.new(upper.outputs[0], safe_upper.inputs[0])
    links.new(epsilon_upper.outputs[0], safe_upper.inputs[1])
    noise_factor = _output(noise, "Fac", 0)
    links.new(noise_factor, ramp.inputs["Value"])
    links.new(lower.outputs[0], ramp.inputs["From Min"])
    links.new(safe_upper.outputs[0], ramp.inputs["From Max"])
    group["fbp_generated_mask_contract_version"] = 2
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


def _create_white_balance(name):
    """Apply artist-friendly temperature and green/magenta tint correction."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Temperature", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1.0, maximum=1.0)
    _socket(group, "Tint", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1.0, maximum=1.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links

    temp_r = _math(group, "MULTIPLY", "Warm Red", -700, 300, value_2=0.30)
    tint_r = _math(group, "MULTIPLY", "Tint Red", -700, 180, value_2=0.15)
    red_sum = _math(group, "ADD", "Red Balance", -500, 260)
    red = _math(group, "ADD", "Red Multiplier", -300, 260, value_1=1.0)
    tint_g = _math(group, "MULTIPLY", "Tint Green", -700, 20, value_2=-0.25)
    green = _math(group, "ADD", "Green Multiplier", -300, 20, value_1=1.0)
    temp_b = _math(group, "MULTIPLY", "Cool Blue", -700, -160, value_2=-0.30)
    tint_b = _math(group, "MULTIPLY", "Tint Blue", -700, -280, value_2=0.15)
    blue_sum = _math(group, "ADD", "Blue Balance", -500, -220)
    blue = _math(group, "ADD", "Blue Multiplier", -300, -220, value_1=1.0)
    balance = _node(group, "ShaderNodeCombineColor", "White Balance Multipliers", -80, 80)
    try:
        balance.mode = "RGB"
    except (AttributeError, TypeError, ValueError):
        pass
    corrected = _mix_rgb(group, "MULTIPLY", "White Balanced Color", 160, 100, fac=1.0)
    result = _mix_rgb(group, "MIX", "White Balance Factor", 400, 100)

    links.new(inp.outputs["Temperature"], temp_r.inputs[0])
    links.new(inp.outputs["Tint"], tint_r.inputs[0])
    links.new(temp_r.outputs[0], red_sum.inputs[0]); links.new(tint_r.outputs[0], red_sum.inputs[1])
    links.new(red_sum.outputs[0], red.inputs[1])
    links.new(inp.outputs["Tint"], tint_g.inputs[0]); links.new(tint_g.outputs[0], green.inputs[1])
    links.new(inp.outputs["Temperature"], temp_b.inputs[0]); links.new(inp.outputs["Tint"], tint_b.inputs[0])
    links.new(temp_b.outputs[0], blue_sum.inputs[0]); links.new(tint_b.outputs[0], blue_sum.inputs[1])
    links.new(blue_sum.outputs[0], blue.inputs[1])
    links.new(red.outputs[0], balance.inputs[0]); links.new(green.outputs[0], balance.inputs[1]); links.new(blue.outputs[0], balance.inputs[2])
    links.new(inp.outputs["Color In"], corrected.inputs[1]); links.new(balance.outputs[0], corrected.inputs[2])
    links.new(inp.outputs["Factor"], result.inputs[0]); links.new(inp.outputs["Color In"], result.inputs[1]); links.new(corrected.outputs[0], result.inputs[2])
    links.new(result.outputs[0], out.inputs["Color Out"])
    group["fbp_white_balance_version"] = 1
    return group


def _create_curves(name):
    """Expose Blender's native RGB Curves widget inside a private effect group."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links
    curves = _node(group, "ShaderNodeRGBCurve", "Frame By Plane Curves", -220, 120)
    curves["fbp_effect_curve_mapping"] = True
    curves["fbp_effect_curve_role"] = "COLOR_CURVES"
    try:
        curves.mapping.initialize()
        curves.mapping.update()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    mix = _mix_rgb(group, "MIX", "Curves Factor", 120, 120)
    links.new(inp.outputs["Color In"], curves.inputs["Color"])
    links.new(inp.outputs["Factor"], mix.inputs[0])
    links.new(inp.outputs["Color In"], mix.inputs[1])
    links.new(curves.outputs["Color"], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Color Out"])
    group["fbp_curve_mapping_contract_version"] = 1
    return group


def _create_color_isolate(name):
    """Preserve a perceptual HSV color range while desaturating the rest."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Target Color", "INPUT", "NodeSocketColor", default=(1.0, 0.0, 0.0, 1.0))
    _socket(group, "Tolerance", "INPUT", "NodeSocketFloat", default=0.15, minimum=0.0, maximum=1.0)
    _socket(group, "Falloff", "INPUT", "NodeSocketFloat", default=0.10, minimum=0.0, maximum=1.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links

    source_hsv = _node(group, "ShaderNodeSeparateColor", "Source HSV", -1120, 250)
    target_hsv = _node(group, "ShaderNodeSeparateColor", "Target HSV", -1120, 20)
    try:
        source_hsv.mode = target_hsv.mode = "HSV"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(inp.outputs["Color In"], source_hsv.inputs[0])
    links.new(inp.outputs["Target Color"], target_hsv.inputs[0])

    hue_sub = _math(group, "SUBTRACT", "Hue Difference", -900, 330)
    hue_abs = _math(group, "ABSOLUTE", "Absolute Hue Difference", -720, 330)
    hue_wrap = _math(group, "SUBTRACT", "Wrapped Hue Difference", -540, 250, value_1=1.0)
    hue_min = _math(group, "MINIMUM", "Shortest Hue Distance", -360, 330)
    hue_norm = _math(group, "MULTIPLY", "Normalized Hue Distance", -180, 330, value_2=2.0)
    links.new(source_hsv.outputs[0], hue_sub.inputs[0]); links.new(target_hsv.outputs[0], hue_sub.inputs[1])
    links.new(hue_sub.outputs[0], hue_abs.inputs[0]); links.new(hue_abs.outputs[0], hue_wrap.inputs[1])
    links.new(hue_abs.outputs[0], hue_min.inputs[0]); links.new(hue_wrap.outputs[0], hue_min.inputs[1])
    links.new(hue_min.outputs[0], hue_norm.inputs[0])

    sat_sub = _math(group, "SUBTRACT", "Saturation Difference", -900, 120)
    sat_abs = _math(group, "ABSOLUTE", "Absolute Saturation Difference", -720, 120)
    sat_weight = _math(group, "MULTIPLY", "Weighted Saturation Difference", -540, 120, value_2=0.35)
    value_sub = _math(group, "SUBTRACT", "Value Difference", -900, -40)
    value_abs = _math(group, "ABSOLUTE", "Absolute Value Difference", -720, -40)
    value_weight = _math(group, "MULTIPLY", "Weighted Value Difference", -540, -40, value_2=0.15)
    links.new(source_hsv.outputs[1], sat_sub.inputs[0]); links.new(target_hsv.outputs[1], sat_sub.inputs[1])
    links.new(sat_sub.outputs[0], sat_abs.inputs[0]); links.new(sat_abs.outputs[0], sat_weight.inputs[0])
    links.new(source_hsv.outputs[2], value_sub.inputs[0]); links.new(target_hsv.outputs[2], value_sub.inputs[1])
    links.new(value_sub.outputs[0], value_abs.inputs[0]); links.new(value_abs.outputs[0], value_weight.inputs[0])

    chroma_sum = _math(group, "ADD", "Hue and Saturation Distance", 0, 250)
    chroma_metric = _math(group, "ADD", "Perceptual Chroma Distance", 180, 250)
    gray_sat = _math(group, "MULTIPLY", "Gray Saturation Distance", -360, -80, value_2=0.5)
    gray_val = _math(group, "MULTIPLY", "Gray Value Distance", -360, -180, value_2=0.5)
    gray_metric = _math(group, "ADD", "Neutral Color Distance", -180, -120)
    links.new(hue_norm.outputs[0], chroma_sum.inputs[0]); links.new(sat_weight.outputs[0], chroma_sum.inputs[1])
    links.new(chroma_sum.outputs[0], chroma_metric.inputs[0]); links.new(value_weight.outputs[0], chroma_metric.inputs[1])
    links.new(sat_abs.outputs[0], gray_sat.inputs[0]); links.new(value_abs.outputs[0], gray_val.inputs[0])
    links.new(gray_sat.outputs[0], gray_metric.inputs[0]); links.new(gray_val.outputs[0], gray_metric.inputs[1])

    saturation_gate = _node(group, "ShaderNodeMapRange", "Target Saturation Gate", 0, -80)
    saturation_gate.clamp = True
    saturation_gate.interpolation_type = "SMOOTHERSTEP"
    saturation_gate.inputs["From Min"].default_value = 0.05
    saturation_gate.inputs["From Max"].default_value = 0.25
    saturation_gate.inputs["To Min"].default_value = 0.0
    saturation_gate.inputs["To Max"].default_value = 1.0
    inverse_gate = _math(group, "SUBTRACT", "Neutral Target Weight", 180, -80, value_1=1.0)
    chroma_scaled = _math(group, "MULTIPLY", "Chroma Metric Weight", 360, 210)
    gray_scaled = _math(group, "MULTIPLY", "Neutral Metric Weight", 360, -80)
    distance = _math(group, "ADD", "Color Isolate Distance", 540, 120)
    links.new(target_hsv.outputs[1], saturation_gate.inputs["Value"])
    links.new(saturation_gate.outputs["Result"], inverse_gate.inputs[1])
    links.new(chroma_metric.outputs[0], chroma_scaled.inputs[0]); links.new(saturation_gate.outputs["Result"], chroma_scaled.inputs[1])
    links.new(gray_metric.outputs[0], gray_scaled.inputs[0]); links.new(inverse_gate.outputs[0], gray_scaled.inputs[1])
    links.new(chroma_scaled.outputs[0], distance.inputs[0]); links.new(gray_scaled.outputs[0], distance.inputs[1])

    upper = _math(group, "ADD", "Color Isolate Outer Range", 540, -80)
    transition = _node(group, "ShaderNodeMapRange", "Color Isolate Transition", 760, 150)
    transition.interpolation_type = "SMOOTHERSTEP"
    transition.clamp = True
    transition.inputs["To Min"].default_value = 1.0
    transition.inputs["To Max"].default_value = 0.0
    links.new(inp.outputs["Tolerance"], upper.inputs[0]); links.new(inp.outputs["Falloff"], upper.inputs[1])
    links.new(distance.outputs[0], transition.inputs["Value"])
    links.new(inp.outputs["Tolerance"], transition.inputs["From Min"]); links.new(upper.outputs[0], transition.inputs["From Max"])

    gray_value = _node(group, "ShaderNodeRGBToBW", "Color Isolate Grayscale", 540, -260)
    gray = _node(group, "ShaderNodeCombineColor", "Color Isolate Gray Color", 760, -260)
    try:
        gray.mode = "RGB"
    except (AttributeError, TypeError, ValueError):
        pass
    isolated = _mix_rgb(group, "MIX", "Color Isolate Mask", 980, 100)
    result = _mix_rgb(group, "MIX", "Color Isolate Factor", 1200, 100)
    links.new(inp.outputs["Color In"], gray_value.inputs[0])
    for index in range(3):
        links.new(gray_value.outputs[0], gray.inputs[index])
    links.new(transition.outputs["Result"], isolated.inputs[0]); links.new(gray.outputs[0], isolated.inputs[1]); links.new(inp.outputs["Color In"], isolated.inputs[2])
    links.new(inp.outputs["Factor"], result.inputs[0]); links.new(inp.outputs["Color In"], result.inputs[1]); links.new(isolated.outputs[0], result.inputs[2])
    links.new(result.outputs[0], out.inputs["Color Out"])
    group["fbp_color_isolate_version"] = 2
    return group


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


def _create_gradient_map(name):
    """Figma-inspired Gradient Map: luminance through an editable ramp."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links
    luma = _node(group, "ShaderNodeRGBToBW", "Gradient Map Luminance", -520, 120)
    ramp = _configure_effect_color_ramp(
        _node(group, "ShaderNodeValToRGB", "Gradient Map Ramp", -260, 120),
        "GRADIENT_MAP",
        ((0.0, (0.02, 0.03, 0.08, 1.0)), (0.52, (0.58, 0.12, 0.78, 1.0)), (1.0, (1.0, 0.88, 0.24, 1.0))),
    )
    mix = _mix_rgb(group, "MIX", "Gradient Map Mix", 180, 100)
    links.new(inp.outputs["Color In"], luma.inputs[0])
    links.new(luma.outputs[0], ramp.inputs["Fac"])
    links.new(inp.outputs["Factor"], mix.inputs[0])
    links.new(inp.outputs["Color In"], mix.inputs[1])
    links.new(ramp.outputs["Color"], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Color Out"])
    group["fbp_color_ramp_contract_version"] = 1
    return group


def _create_channel_mixer(name):
    """Lightweight RGB channel gain mixer for grading and false-color looks."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Red", "INPUT", "NodeSocketFloat", default=1.0, minimum=-2.0, maximum=2.0)
    _socket(group, "Green", "INPUT", "NodeSocketFloat", default=1.0, minimum=-2.0, maximum=2.0)
    _socket(group, "Blue", "INPUT", "NodeSocketFloat", default=1.0, minimum=-2.0, maximum=2.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links
    split = _node(group, "ShaderNodeSeparateColor", "Source RGB", -520, 120)
    combine = _node(group, "ShaderNodeCombineColor", "Mixed RGB", 140, 120)
    try:
        split.mode = 'RGB'
        combine.mode = 'RGB'
    except (AttributeError, TypeError, ValueError):
        pass
    red = _math(group, "MULTIPLY", "Red Gain", -250, 260)
    green = _math(group, "MULTIPLY", "Green Gain", -250, 120)
    blue = _math(group, "MULTIPLY", "Blue Gain", -250, -20)
    mix = _mix_rgb(group, "MIX", "Channel Mixer Factor", 430, 120)
    links.new(inp.outputs["Color In"], split.inputs[0])
    links.new(_output(split, "Red", 0), red.inputs[0])
    links.new(inp.outputs["Red"], red.inputs[1])
    links.new(_output(split, "Green", 1), green.inputs[0])
    links.new(inp.outputs["Green"], green.inputs[1])
    links.new(_output(split, "Blue", 2), blue.inputs[0])
    links.new(inp.outputs["Blue"], blue.inputs[1])
    links.new(red.outputs[0], _input(combine, "Red", 0))
    links.new(green.outputs[0], _input(combine, "Green", 1))
    links.new(blue.outputs[0], _input(combine, "Blue", 2))
    links.new(inp.outputs["Factor"], mix.inputs[0])
    links.new(inp.outputs["Color In"], mix.inputs[1])
    links.new(combine.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Color Out"])
    return group


def _float_style_select(group, links, current_socket, candidate_socket, style_socket, index, *, x, y, label):
    """Return candidate when Style == index, otherwise current.

    Shader node groups do not expose a compact enum-switch node in every
    Blender build we support, so the dither graph uses a tiny math switch per
    pattern.  It is deterministic, cheap, and survives old saved files.
    """
    is_style = _math(group, "COMPARE", f"{label} Select {index}", x, y)
    try:
        is_style.inputs[1].default_value = float(index)
        eps = _input(is_style, "Epsilon", 2)
        if eps is not None:
            eps.default_value = 0.1
    except (AttributeError, TypeError, ValueError):
        pass
    inverse = _math(group, "SUBTRACT", f"{label} Keep Previous {index}", x + 180, y, value_1=1.0)
    previous = _math(group, "MULTIPLY", f"{label} Previous Part {index}", x + 360, y + 60)
    selected = _math(group, "MULTIPLY", f"{label} Candidate Part {index}", x + 360, y - 60)
    combined = _math(group, "ADD", f"{label} Mixed {index}", x + 540, y)
    links.new(style_socket, is_style.inputs[0])
    links.new(is_style.outputs[0], inverse.inputs[1])
    links.new(current_socket, previous.inputs[0])
    links.new(inverse.outputs[0], previous.inputs[1])
    links.new(candidate_socket, selected.inputs[0])
    links.new(is_style.outputs[0], selected.inputs[1])
    links.new(previous.outputs[0], combined.inputs[0])
    links.new(selected.outputs[0], combined.inputs[1])
    return combined.outputs[0]


def _create_dither(name):
    """True ordered dithering.

    This version intentionally removes the previous symbol/halftone approach.
    It performs the classic ordered-dither operation in shader math:

        adjusted luminance -> ink density -> compare against a threshold matrix

    The pattern is a binary pixel grid.  Bayer modes use fixed threshold
    matrices; Noise uses stable per-cell white noise; Threshold is the plain
    one-bit fallback; Line Screen is kept as a practical screen-style option.
    """
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Style", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=4.0)
    _socket(group, "Size", "INPUT", "NodeSocketFloat", default=3.0, minimum=1.0, maximum=512.0)
    _socket(group, "Texel X", "INPUT", "NodeSocketFloat", default=0.001, minimum=0.000001, maximum=1.0)
    _socket(group, "Texel Y", "INPUT", "NodeSocketFloat", default=0.001, minimum=0.000001, maximum=1.0)
    _socket(group, "Brightness", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=8.0)
    _socket(group, "Contrast", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=8.0)
    _socket(group, "Mono", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Mono Color", "INPUT", "NodeSocketColor", default=(0.0, 0.0, 0.0, 1.0))
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links

    def _bayer2_value(x_bit, y_bit, label, x, y):
        """Return the exact 2x2 Bayer index: 2*x + 3*y - 4*x*y."""
        x_term = _math(group, "MULTIPLY", f"{label} X", x, y + 100, value_2=2.0)
        y_term = _math(group, "MULTIPLY", f"{label} Y", x, y - 20, value_2=3.0)
        xy = _math(group, "MULTIPLY", f"{label} XY", x, y - 140)
        xy_term = _math(group, "MULTIPLY", f"{label} XY Correction", x + 200, y - 140, value_2=4.0)
        base = _math(group, "ADD", f"{label} Base", x + 200, y + 40)
        value = _math(group, "SUBTRACT", f"{label} Index", x + 400, y + 40)
        links.new(x_bit, x_term.inputs[0])
        links.new(y_bit, y_term.inputs[0])
        links.new(x_bit, xy.inputs[0])
        links.new(y_bit, xy.inputs[1])
        links.new(xy.outputs[0], xy_term.inputs[0])
        links.new(x_term.outputs[0], base.inputs[0])
        links.new(y_term.outputs[0], base.inputs[1])
        links.new(base.outputs[0], value.inputs[0])
        links.new(xy_term.outputs[0], value.inputs[1])
        return value.outputs[0]

    def _threshold_mask(density_sock, threshold_sock, name, x, y):
        node = _math(group, "GREATER_THAN", name, x, y)
        links.new(density_sock, node.inputs[0])
        links.new(threshold_sock, node.inputs[1])
        return node.outputs[0]

    def _const(value, name, x, y):
        node = _math(group, "ADD", name, x, y, value_1=0.0, value_2=float(value))
        return node.outputs[0]

    # --- Source tone: luminance to ink density --------------------------
    luma = _node(group, "ShaderNodeRGBToBW", "Dither Luminance", -1760, 520)
    bright = _math(group, "MULTIPLY", "Dither Brightness", -1540, 520)
    center = _math(group, "SUBTRACT", "Dither Center", -1320, 520, value_2=0.5)
    contrast = _math(group, "MULTIPLY", "Dither Contrast", -1100, 520)
    restore = _math(group, "ADD", "Dither Restore", -880, 520, value_2=0.5)
    clamp_low = _math(group, "MAXIMUM", "Dither Clamp Low", -660, 520, value_2=0.0)
    tone = _math(group, "MINIMUM", "Dither Clamp High", -440, 520, value_2=1.0)
    density = _math(group, "SUBTRACT", "Dither Ink Density", -220, 520, value_1=1.0)

    links.new(inp.outputs["Color In"], luma.inputs[0])
    links.new(luma.outputs[0], bright.inputs[0])
    links.new(inp.outputs["Brightness"], bright.inputs[1])
    links.new(bright.outputs[0], center.inputs[0])
    links.new(center.outputs[0], contrast.inputs[0])
    links.new(inp.outputs["Contrast"], contrast.inputs[1])
    links.new(contrast.outputs[0], restore.inputs[0])
    links.new(restore.outputs[0], clamp_low.inputs[0])
    links.new(clamp_low.outputs[0], tone.inputs[0])
    links.new(tone.outputs[0], density.inputs[1])

    # --- Pixel coordinate grid -----------------------------------------
    # The previous Dither grid used a fixed 0..1 UV scale.  On non-square or
    # resized planes this made each dither cell stretch with the object, and on
    # some procedural materials the external UV socket could be missing, making
    # one huge cell cover the whole plane.  Use the material UV coordinates and
    # source texel size instead: floor(U * image_width / Pixel Size).  This
    # keeps the Bayer pixels square in image space and independent from the
    # physical plane size.
    texcoord = _node(group, "ShaderNodeTexCoord", "Dither Stable UV", -1980, -40)
    separate = _node(group, "ShaderNodeSeparateXYZ", "Dither UV", -1760, -40)
    safe_size = _math(group, "MAXIMUM", "Dither Safe Size", -1540, -40, value_2=1.0)
    safe_texel_x = _math(group, "MAXIMUM", "Dither Safe Texel X", -1540, -220, value_2=0.000001)
    safe_texel_y = _math(group, "MAXIMUM", "Dither Safe Texel Y", -1540, -380, value_2=0.000001)
    source_width = _math(group, "DIVIDE", "Dither Source Width", -1320, -220, value_1=1.0)
    source_height = _math(group, "DIVIDE", "Dither Source Height", -1320, -380, value_1=1.0)
    cells_x = _math(group, "DIVIDE", "Dither Cells X", -1100, 80)
    cells_y = _math(group, "DIVIDE", "Dither Cells Y", -1100, -160)
    scaled_x = _math(group, "MULTIPLY", "Dither Pixel X Scaled", -880, 80)
    scaled_y = _math(group, "MULTIPLY", "Dither Pixel Y Scaled", -880, -160)
    cell_x = _math(group, "FLOOR", "Dither Pixel X", -660, 80)
    cell_y = _math(group, "FLOOR", "Dither Pixel Y", -660, -160)

    links.new(texcoord.outputs["UV"], separate.inputs[0])
    links.new(inp.outputs["Size"], safe_size.inputs[0])
    links.new(inp.outputs["Texel X"], safe_texel_x.inputs[0])
    links.new(inp.outputs["Texel Y"], safe_texel_y.inputs[0])
    links.new(safe_texel_x.outputs[0], source_width.inputs[1])
    links.new(safe_texel_y.outputs[0], source_height.inputs[1])
    links.new(source_width.outputs[0], cells_x.inputs[0])
    links.new(source_height.outputs[0], cells_y.inputs[0])
    links.new(safe_size.outputs[0], cells_x.inputs[1])
    links.new(safe_size.outputs[0], cells_y.inputs[1])
    links.new(separate.outputs["X"], scaled_x.inputs[0])
    links.new(separate.outputs["Y"], scaled_y.inputs[0])
    links.new(cells_x.outputs[0], scaled_x.inputs[1])
    links.new(cells_y.outputs[0], scaled_y.inputs[1])
    links.new(scaled_x.outputs[0], cell_x.inputs[0])
    links.new(scaled_y.outputs[0], cell_y.inputs[0])

    # Compute Bayer indices arithmetically instead of evaluating one compare,
    # gate and weighted sum for every matrix cell. The recursive identity is:
    # B4(x,y) = 4*B2(x mod 2,y mod 2) + B2(floor(x/2),floor(y/2)).
    # This preserves the exact matrix while cutting dozens of per-pixel nodes.
    x4 = _math(group, "MODULO", "Dither X4", -440, 220, value_2=4.0)
    y4 = _math(group, "MODULO", "Dither Y4", -440, 40, value_2=4.0)
    x2 = _math(group, "MODULO", "Dither X2", -220, 220, value_2=2.0)
    y2 = _math(group, "MODULO", "Dither Y2", -220, 40, value_2=2.0)
    x_high_div = _math(group, "DIVIDE", "Dither X High / 2", -220, -160, value_2=2.0)
    y_high_div = _math(group, "DIVIDE", "Dither Y High / 2", -220, -340, value_2=2.0)
    x_high = _math(group, "FLOOR", "Dither X High", 0, -160)
    y_high = _math(group, "FLOOR", "Dither Y High", 0, -340)
    links.new(cell_x.outputs[0], x4.inputs[0])
    links.new(cell_y.outputs[0], y4.inputs[0])
    links.new(x4.outputs[0], x2.inputs[0])
    links.new(y4.outputs[0], y2.inputs[0])
    links.new(x4.outputs[0], x_high_div.inputs[0])
    links.new(y4.outputs[0], y_high_div.inputs[0])
    links.new(x_high_div.outputs[0], x_high.inputs[0])
    links.new(y_high_div.outputs[0], y_high.inputs[0])

    bayer_low = _bayer2_value(x2.outputs[0], y2.outputs[0], "Bayer Low Bits", 320, 260)
    bayer_high = _bayer2_value(x_high.outputs[0], y_high.outputs[0], "Bayer High Bits", 320, -180)
    low_scaled = _math(group, "MULTIPLY", "Bayer4 Low Scaled", 920, 260, value_2=4.0)
    bayer4_index = _math(group, "ADD", "Bayer4 Index", 1140, 260)
    bayer4_half = _math(group, "ADD", "Bayer4 Half Step", 1360, 260, value_2=0.5)
    bayer4_normalized = _math(group, "DIVIDE", "Bayer4 Threshold", 1580, 260, value_2=16.0)
    links.new(bayer_low, low_scaled.inputs[0])
    links.new(low_scaled.outputs[0], bayer4_index.inputs[0])
    links.new(bayer_high, bayer4_index.inputs[1])
    links.new(bayer4_index.outputs[0], bayer4_half.inputs[0])
    links.new(bayer4_half.outputs[0], bayer4_normalized.inputs[0])
    bayer4_mask = _threshold_mask(density.outputs[0], bayer4_normalized.outputs[0], "Bayer 4x4 Mask", 2460, 360)

    bayer2_half = _math(group, "ADD", "Bayer2 Half Step", 1140, -80, value_2=0.5)
    bayer2_normalized = _math(group, "DIVIDE", "Bayer2 Threshold", 1360, -80, value_2=4.0)
    links.new(bayer_low, bayer2_half.inputs[0])
    links.new(bayer2_half.outputs[0], bayer2_normalized.inputs[0])
    bayer2_mask = _threshold_mask(density.outputs[0], bayer2_normalized.outputs[0], "Bayer 2x2 Mask", 2460, -80)

    # Stable per-cell stochastic dithering.  This is not error diffusion, but
    # it is a real threshold comparison rather than decorative symbol output.
    cell_vec = _node(group, "ShaderNodeCombineXYZ", "Dither Cell Vector", 1560, -360)
    noise = _node(group, "ShaderNodeTexWhiteNoise", "Dither Noise Threshold", 1780, -360)
    try:
        noise.noise_dimensions = "3D"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(cell_x.outputs[0], cell_vec.inputs["X"])
    links.new(cell_y.outputs[0], cell_vec.inputs["Y"])
    links.new(inp.outputs["Size"], cell_vec.inputs["Z"])
    links.new(cell_vec.outputs[0], noise.inputs["Vector"])
    noise_mask = _threshold_mask(density.outputs[0], _output(noise, "Value", 1), "Noise Dither Mask", 2460, -360)

    threshold_value = _const(0.5, "Plain Threshold Value", 1780, -560)
    plain_mask = _threshold_mask(density.outputs[0], threshold_value, "Plain Threshold Mask", 2460, -560)

    # Line screen: threshold against local fractional Y inside the dither pixel.
    local_y = _math(group, "FRACT", "Line Screen Local Y", 1780, -760)
    links.new(scaled_y.outputs[0], local_y.inputs[0])
    line_mask = _threshold_mask(density.outputs[0], local_y.outputs[0], "Line Screen Mask", 2460, -760)

    selected_mask = bayer4_mask
    selected_mask = _float_style_select(group, links, selected_mask, bayer2_mask, inp.outputs["Style"], 1, x=2700, y=260, label="Dither Style")
    selected_mask = _float_style_select(group, links, selected_mask, noise_mask, inp.outputs["Style"], 2, x=2700, y=60, label="Dither Style")
    selected_mask = _float_style_select(group, links, selected_mask, plain_mask, inp.outputs["Style"], 3, x=2700, y=-140, label="Dither Style")
    selected_mask = _float_style_select(group, links, selected_mask, line_mask, inp.outputs["Style"], 4, x=2700, y=-340, label="Dither Style")

    # --- Output ----------------------------------------------------------
    paper = _node(group, "ShaderNodeRGB", "Dither Paper White", 3360, -180)
    try:
        paper.outputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    except (AttributeError, TypeError, ValueError):
        pass
    ink_color = _mix_rgb(group, "MIX", "Dither Ink Color", 3360, 120)
    dithered = _mix_rgb(group, "MIX", "Dithered Output", 3600, 60)
    final = _mix_rgb(group, "MIX", "Dither Factor", 3840, 60)

    links.new(inp.outputs["Mono"], ink_color.inputs[0])
    links.new(inp.outputs["Color In"], ink_color.inputs[1])
    links.new(inp.outputs["Mono Color"], ink_color.inputs[2])
    links.new(selected_mask, dithered.inputs[0])
    links.new(paper.outputs[0], dithered.inputs[1])
    links.new(ink_color.outputs[0], dithered.inputs[2])
    links.new(inp.outputs["Factor"], final.inputs[0])
    links.new(inp.outputs["Color In"], final.inputs[1])
    links.new(dithered.outputs[0], final.inputs[2])
    links.new(final.outputs[0], out.inputs["Color Out"])
    group["fbp_dither_contract_version"] = 11
    return group

def _create_bloom(name):
    """Lightweight highlight bloom/glow, designed to stay shader-only."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Threshold", "INPUT", "NodeSocketFloat", default=0.72, minimum=0.0, maximum=1.0)
    _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=0.18, minimum=0.001, maximum=1.0)
    _socket(group, "Intensity", "INPUT", "NodeSocketFloat", default=0.65, minimum=0.0, maximum=4.0)
    _socket(group, "Glow Color", "INPUT", "NodeSocketColor", default=(1.0, 0.82, 0.48, 1.0))
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links

    luma = _node(group, "ShaderNodeRGBToBW", "Bloom Luminance", -720, 180)
    above = _math(group, "SUBTRACT", "Highlights Above Threshold", -520, 180)
    safe_soft = _math(group, "MAXIMUM", "Safe Bloom Softness", -520, -20, value_2=0.001)
    normalized = _math(group, "DIVIDE", "Bloom Region", -320, 180)
    clamp_low = _math(group, "MAXIMUM", "Bloom Region Minimum", -120, 180, value_2=0.0)
    clamp = _math(group, "MINIMUM", "Bloom Region Maximum", 80, 180, value_2=1.0)
    amount = _math(group, "MULTIPLY", "Bloom Amount", 280, 180)
    glow = _mix_rgb(group, "ADD", "Bloom Glow", 500, 80)
    final = _mix_rgb(group, "MIX", "Bloom Factor", 720, 80)

    links.new(inp.outputs["Color In"], luma.inputs[0])
    links.new(luma.outputs[0], above.inputs[0])
    links.new(inp.outputs["Threshold"], above.inputs[1])
    links.new(inp.outputs["Softness"], safe_soft.inputs[0])
    links.new(above.outputs[0], normalized.inputs[0])
    links.new(safe_soft.outputs[0], normalized.inputs[1])
    links.new(normalized.outputs[0], clamp_low.inputs[0])
    links.new(clamp_low.outputs[0], clamp.inputs[0])
    links.new(clamp.outputs[0], amount.inputs[0])
    links.new(inp.outputs["Intensity"], amount.inputs[1])
    links.new(amount.outputs[0], glow.inputs[0])
    links.new(inp.outputs["Color In"], glow.inputs[1])
    links.new(inp.outputs["Glow Color"], glow.inputs[2])
    links.new(inp.outputs["Factor"], final.inputs[0])
    links.new(inp.outputs["Color In"], final.inputs[1])
    links.new(glow.outputs[0], final.inputs[2])
    links.new(final.outputs[0], out.inputs["Color Out"])
    return group


def _create_filter_presets(name):
    """Figma-inspired quick filter stack: sepia, warm, cool and noir."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Sepia", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Warm", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Cool", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Noir", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links

    luma = _node(group, "ShaderNodeRGBToBW", "Filter Luminance", -900, 160)
    gray = _node(group, "ShaderNodeCombineColor", "Filter Grayscale", -700, 160)
    sepia_tone = _mix_rgb(group, "MULTIPLY", "Filter Sepia Tone", -470, 160)
    sepia_tone.inputs[2].default_value = (1.22, 0.94, 0.62, 1.0)
    sepia_mix = _mix_rgb(group, "MIX", "Sepia Amount", -220, 160)
    warm_mix = _mix_rgb(group, "SCREEN", "Warm Amount", 20, 160)
    warm_mix.inputs[2].default_value = (1.0, 0.46, 0.10, 1.0)
    cool_mix = _mix_rgb(group, "SCREEN", "Cool Amount", 260, 160)
    cool_mix.inputs[2].default_value = (0.18, 0.46, 1.0, 1.0)

    noir_center = _math(group, "SUBTRACT", "Noir Center", -470, -120, value_2=0.5)
    noir_contrast = _math(group, "MULTIPLY", "Noir Contrast", -270, -120, value_2=1.75)
    noir_restore = _math(group, "ADD", "Noir Restore", -70, -120, value_2=0.5)
    noir_low = _math(group, "MAXIMUM", "Noir Min", 130, -120, value_2=0.0)
    noir_clamp = _math(group, "MINIMUM", "Noir Max", 330, -120, value_2=1.0)
    noir_color = _node(group, "ShaderNodeCombineColor", "Noir Color", 530, -120)
    noir_mix = _mix_rgb(group, "MIX", "Noir Amount", 620, 160)
    final = _mix_rgb(group, "MIX", "Filter Presets Factor", 860, 160)

    try:
        gray.mode = 'RGB'
        noir_color.mode = 'RGB'
    except (AttributeError, TypeError, ValueError):
        pass

    links.new(inp.outputs["Color In"], luma.inputs[0])
    for channel in ("Red", "Green", "Blue"):
        if channel in gray.inputs:
            links.new(luma.outputs[0], gray.inputs[channel])
        if channel in noir_color.inputs:
            links.new(noir_clamp.outputs[0], noir_color.inputs[channel])
    links.new(gray.outputs[0], sepia_tone.inputs[1])
    links.new(inp.outputs["Sepia"], sepia_mix.inputs[0])
    links.new(inp.outputs["Color In"], sepia_mix.inputs[1])
    links.new(sepia_tone.outputs[0], sepia_mix.inputs[2])
    links.new(inp.outputs["Warm"], warm_mix.inputs[0])
    links.new(sepia_mix.outputs[0], warm_mix.inputs[1])
    links.new(inp.outputs["Cool"], cool_mix.inputs[0])
    links.new(warm_mix.outputs[0], cool_mix.inputs[1])

    links.new(luma.outputs[0], noir_center.inputs[0])
    links.new(noir_center.outputs[0], noir_contrast.inputs[0])
    links.new(noir_contrast.outputs[0], noir_restore.inputs[0])
    links.new(noir_restore.outputs[0], noir_low.inputs[0])
    links.new(noir_low.outputs[0], noir_clamp.inputs[0])
    links.new(inp.outputs["Noir"], noir_mix.inputs[0])
    links.new(cool_mix.outputs[0], noir_mix.inputs[1])
    links.new(noir_color.outputs[0], noir_mix.inputs[2])
    links.new(inp.outputs["Factor"], final.inputs[0])
    links.new(inp.outputs["Color In"], final.inputs[1])
    links.new(noir_mix.outputs[0], final.inputs[2])
    links.new(final.outputs[0], out.inputs["Color Out"])
    return group


def _create_solarize(name):
    """Invert highlights above a luminance threshold with a soft transition."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Threshold", "INPUT", "NodeSocketFloat", default=0.5, minimum=0.0, maximum=1.0)
    _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=0.08, minimum=0.0, maximum=1.0)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links

    luma = _node(group, "ShaderNodeRGBToBW", "Solarize Luminance", -680, 180)
    delta = _math(group, "SUBTRACT", "Luminance Above Threshold", -470, 180)
    safe_softness = _math(group, "MAXIMUM", "Safe Solarize Softness", -470, -40, value_2=0.00001)
    normalize = _math(group, "DIVIDE", "Solarize Transition", -250, 180)
    center = _math(group, "ADD", "Centered Solarize Transition", -50, 180, value_2=0.5)
    clamp_low = _math(group, "MAXIMUM", "Solarize Mask Minimum", 140, 180, value_2=0.0)
    clamp = _math(group, "MINIMUM", "Solarize Mask", 320, 180, value_2=1.0)
    invert = _node(group, "ShaderNodeInvert", "Solarized Color", -50, -80)
    amount = _math(group, "MULTIPLY", "Solarize Amount", 340, 180)
    mix = _mix_rgb(group, "MIX", "Solarize Mix", 560, 80)

    links.new(inp.outputs["Color In"], luma.inputs[0])
    links.new(luma.outputs[0], delta.inputs[0])
    links.new(inp.outputs["Threshold"], delta.inputs[1])
    links.new(inp.outputs["Softness"], safe_softness.inputs[0])
    links.new(delta.outputs[0], normalize.inputs[0])
    links.new(safe_softness.outputs[0], normalize.inputs[1])
    links.new(normalize.outputs[0], center.inputs[0])
    links.new(center.outputs[0], clamp_low.inputs[0])
    links.new(clamp_low.outputs[0], clamp.inputs[0])
    links.new(inp.outputs["Color In"], invert.inputs[1])
    links.new(clamp.outputs[0], amount.inputs[0])
    links.new(inp.outputs["Factor"], amount.inputs[1])
    links.new(amount.outputs[0], mix.inputs[0])
    links.new(inp.outputs["Color In"], mix.inputs[1])
    links.new(invert.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Color Out"])
    return group


def _create_tritone(name):
    """Map source luminance to editable shadow, midtone and highlight colors."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Shadows Tone", "INPUT", "NodeSocketColor", default=(0.02, 0.03, 0.08, 1.0))
    _socket(group, "Midtones Tone", "INPUT", "NodeSocketColor", default=(0.55, 0.20, 0.22, 1.0))
    _socket(group, "Highlights Tone", "INPUT", "NodeSocketColor", default=(1.0, 0.86, 0.55, 1.0))
    _socket(group, "Midpoint", "INPUT", "NodeSocketFloat", default=0.5, minimum=0.01, maximum=0.99)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links

    luma = _node(group, "ShaderNodeRGBToBW", "Tritone Luminance", -760, 170)
    safe_mid = _math(group, "MAXIMUM", "Safe Tritone Midpoint", -560, 40, value_2=0.00001)
    inverse_mid = _math(group, "SUBTRACT", "Highlight Range", -560, -120, value_1=1.0)
    safe_inverse = _math(group, "MAXIMUM", "Safe Highlight Range", -360, -120, value_2=0.00001)
    low_t = _math(group, "DIVIDE", "Shadow to Midtone", -350, 200)
    low_clamp_min = _math(group, "MAXIMUM", "Shadow Midtone Clamp Minimum", -150, 200, value_2=0.0)
    low_clamp = _math(group, "MINIMUM", "Shadow Midtone Clamp", 40, 200, value_2=1.0)
    high_delta = _math(group, "SUBTRACT", "Luminance Above Midpoint", -360, 40)
    high_t = _math(group, "DIVIDE", "Midtone to Highlight", -150, 40)
    high_clamp_min = _math(group, "MAXIMUM", "Midtone Highlight Clamp Minimum", 40, 40, value_2=0.0)
    high_clamp = _math(group, "MINIMUM", "Midtone Highlight Clamp", 230, 40, value_2=1.0)
    lower_mix = _mix_rgb(group, "MIX", "Shadow Midtone Mix", 60, 250)
    upper_mix = _mix_rgb(group, "MIX", "Midtone Highlight Mix", 260, 80)
    select_upper = _math(group, "GREATER_THAN", "Select Highlight Range", 60, -100)
    tritone = _mix_rgb(group, "MIX", "Tritone Range Mix", 470, 190)
    result = _mix_rgb(group, "MIX", "Tritone Factor", 700, 140)

    links.new(inp.outputs["Color In"], luma.inputs[0])
    links.new(inp.outputs["Midpoint"], safe_mid.inputs[0])
    links.new(inp.outputs["Midpoint"], inverse_mid.inputs[1])
    links.new(inverse_mid.outputs[0], safe_inverse.inputs[0])
    links.new(luma.outputs[0], low_t.inputs[0])
    links.new(safe_mid.outputs[0], low_t.inputs[1])
    links.new(low_t.outputs[0], low_clamp_min.inputs[0])
    links.new(low_clamp_min.outputs[0], low_clamp.inputs[0])
    links.new(luma.outputs[0], high_delta.inputs[0])
    links.new(inp.outputs["Midpoint"], high_delta.inputs[1])
    links.new(high_delta.outputs[0], high_t.inputs[0])
    links.new(safe_inverse.outputs[0], high_t.inputs[1])
    links.new(high_t.outputs[0], high_clamp_min.inputs[0])
    links.new(high_clamp_min.outputs[0], high_clamp.inputs[0])
    links.new(low_clamp.outputs[0], lower_mix.inputs[0])
    links.new(inp.outputs["Shadows Tone"], lower_mix.inputs[1])
    links.new(inp.outputs["Midtones Tone"], lower_mix.inputs[2])
    links.new(high_clamp.outputs[0], upper_mix.inputs[0])
    links.new(inp.outputs["Midtones Tone"], upper_mix.inputs[1])
    links.new(inp.outputs["Highlights Tone"], upper_mix.inputs[2])
    links.new(luma.outputs[0], select_upper.inputs[0])
    links.new(inp.outputs["Midpoint"], select_upper.inputs[1])
    links.new(select_upper.outputs[0], tritone.inputs[0])
    links.new(lower_mix.outputs[0], tritone.inputs[1])
    links.new(upper_mix.outputs[0], tritone.inputs[2])
    links.new(inp.outputs["Factor"], result.inputs[0])
    links.new(inp.outputs["Color In"], result.inputs[1])
    links.new(tritone.outputs[0], result.inputs[2])
    links.new(result.outputs[0], out.inputs["Color Out"])
    return group


def _create_film_fade(name):
    """Create a light faded-film grade without requiring compositor nodes."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Fade Color", "INPUT", "NodeSocketColor", default=(0.72, 0.48, 0.28, 1.0))
    _socket(group, "Amount", "INPUT", "NodeSocketFloat", default=0.35, minimum=0.0, maximum=1.0)
    _socket(group, "Desaturation", "INPUT", "NodeSocketFloat", default=0.45, minimum=0.0, maximum=1.0)
    _socket(group, "Contrast Loss", "INPUT", "NodeSocketFloat", default=0.30, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group)
    links = group.links

    luma = _node(group, "ShaderNodeRGBToBW", "Film Fade Luminance", -700, 120)
    desat_amount = _math(group, "MULTIPLY", "Film Fade Desaturation", -500, 260)
    desaturate = _mix_rgb(group, "MIX", "Film Fade Desaturate", -260, 170)
    contrast_amount = _math(group, "MULTIPLY", "Film Fade Contrast Loss", -260, -40)
    reduce_contrast = _mix_rgb(group, "MIX", "Film Fade Lift", 0, 130)
    reduce_contrast.inputs[2].default_value = (0.5, 0.5, 0.5, 1.0)
    tint_amount = _math(group, "MULTIPLY", "Film Fade Tint Amount", 0, -80, value_2=0.55)
    tint = _mix_rgb(group, "SCREEN", "Film Fade Tint", 250, 130)
    final = _mix_rgb(group, "MIX", "Film Fade Amount", 500, 130)

    links.new(inp.outputs["Color In"], luma.inputs[0])
    links.new(inp.outputs["Amount"], desat_amount.inputs[0])
    links.new(inp.outputs["Desaturation"], desat_amount.inputs[1])
    links.new(desat_amount.outputs[0], desaturate.inputs[0])
    links.new(inp.outputs["Color In"], desaturate.inputs[1])
    links.new(luma.outputs[0], desaturate.inputs[2])
    links.new(inp.outputs["Amount"], contrast_amount.inputs[0])
    links.new(inp.outputs["Contrast Loss"], contrast_amount.inputs[1])
    links.new(contrast_amount.outputs[0], reduce_contrast.inputs[0])
    links.new(desaturate.outputs[0], reduce_contrast.inputs[1])
    links.new(inp.outputs["Amount"], tint_amount.inputs[0])
    links.new(tint_amount.outputs[0], tint.inputs[0])
    links.new(reduce_contrast.outputs[0], tint.inputs[1])
    links.new(inp.outputs["Fade Color"], tint.inputs[2])
    links.new(inp.outputs["Amount"], final.inputs[0])
    links.new(inp.outputs["Color In"], final.inputs[1])
    links.new(tint.outputs[0], final.inputs[2])
    links.new(final.outputs[0], out.inputs["Color Out"])
    return group


def _source_image_node(group, name, x, y):
    node = _node(group, "ShaderNodeTexImage", name, x, y)
    node["fbp_matrix_source_image_node"] = True
    node["fbp_source_interpolation"] = "Linear"
    try:
        node.interpolation = "Linear"; node.extension = "EXTEND"
    except (AttributeError, TypeError, ValueError):
        pass
    return node


def _create_triangle_blur(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for n,t,d,mi,ma in (("Color In","NodeSocketColor",(0.5,0.5,0.5,1),None,None),("Alpha In","NodeSocketFloat",1,0,1),("UV Vector","NodeSocketVector",None,None,None),("Use Image Sample","NodeSocketFloat",0,0,1),("Radius","NodeSocketFloat",8,0,512),("Samples","NodeSocketInt",17,3,25),("Factor","NodeSocketFloat",1,0,1),("Texel X","NodeSocketFloat",.001,0,1),("Texel Y","NodeSocketFloat",.001,0,1)):
        _socket(group,n,"INPUT",t,default=d,minimum=mi,maximum=ma)
    _socket(group,"Color Out","OUTPUT","NodeSocketColor"); _socket(group,"Alpha Out","OUTPUT","NodeSocketFloat")
    inp,out=_group_io(group); links=group.links
    rx=_math(group,"MULTIPLY","Triangle Radius X",-1100,500); ry=_math(group,"MULTIPLY","Triangle Radius Y",-1100,360)
    links.new(inp.outputs["Radius"],rx.inputs[0]); links.new(inp.outputs["Texel X"],rx.inputs[1]); links.new(inp.outputs["Radius"],ry.inputs[0]); links.new(inp.outputs["Texel Y"],ry.inputs[1])
    enabled=_math(group,"GREATER_THAN","Triangle Enabled",-900,220,value_2=.0001); links.new(inp.outputs["Radius"],enabled.inputs[0])
    positions=[(0,0,1),(0.2,0,.8),(-.2,0,.8),(0,.2,.8),(0,-.2,.8),(.4,0,.6),(-.4,0,.6),(0,.4,.6),(0,-.4,.6),(.6,0,.4),(-.6,0,.4),(0,.6,.4),(0,-.6,.4),(.8,0,.2),(-.8,0,.2),(0,.8,.2),(0,-.8,.2),(1,0,.08),(-1,0,.08),(0,1,.08),(0,-1,.08)]
    cs=[]; al=[]; ws=[]
    for i,(ox,oy,w) in enumerate(positions):
        y=620-i*145; sx=_math(group,"MULTIPLY",f"Triangle X {i}",-730,y+30,value_2=ox); sy=_math(group,"MULTIPLY",f"Triangle Y {i}",-730,y-30,value_2=oy); comb=_node(group,"ShaderNodeCombineXYZ",f"Triangle Offset {i}",-550,y); uv=_vector_math(group,"ADD",f"Triangle UV {i}",-360,y); wt=_blur_dynamic_weight(group,inp.outputs["Samples"],i,w,"Triangle",-1100,y)
        links.new(rx.outputs[0],sx.inputs[0]); links.new(ry.outputs[0],sy.inputs[0]); links.new(sx.outputs[0],comb.inputs["X"]); links.new(sy.outputs[0],comb.inputs["Y"]); links.new(inp.outputs["UV Vector"],uv.inputs[0]); links.new(comb.outputs[0],uv.inputs[1]); c,a=_blur_sample(group,inp,uv.outputs[0],wt,str(i),-150,y,"Triangle Blur"); cs.append(c); al.append(a); ws.append(wt)
    total=_blur_add_chain(group,ws,vector=False,prefix="Triangle Weight",x=3500,y=-320); _finish_alpha_safe_blur(group,inp,out,cs,al,total_weight=total,enabled_socket=enabled.outputs[0],prefix="Triangle Blur")
    return group


def _create_tilt_shift(name):
    """Create an alpha-safe Tilt Shift blur with a rotatable focus band."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for socket_name, socket_type, default, minimum, maximum in (
        ("Color In", "NodeSocketColor", (0.5, 0.5, 0.5, 1.0), None, None),
        ("Alpha In", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("UV Vector", "NodeSocketVector", None, None, None),
        ("Use Image Sample", "NodeSocketFloat", 0.0, 0.0, 1.0),
        ("Focus Position", "NodeSocketFloat", 0.5, -1.0, 2.0),
        ("Focus Width", "NodeSocketFloat", 0.25, 0.001, 2.0),
        ("Focus Angle", "NodeSocketFloat", 0.0, -6.283185307, 6.283185307),
        ("Blur Radius", "NodeSocketFloat", 16.0, 0.0, 512.0),
        ("Factor", "NodeSocketFloat", 1.0, 0.0, 1.0),
        ("Texel X", "NodeSocketFloat", 0.001, 0.0, 1.0),
        ("Texel Y", "NodeSocketFloat", 0.001, 0.0, 1.0),
    ):
        _socket(group, socket_name, "INPUT", socket_type, default=default, minimum=minimum, maximum=maximum)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    # Project centered UV coordinates onto the normal of the focus band.
    separate = _node(group, "ShaderNodeSeparateXYZ", "Tilt UV", -1450, 560)
    centered_x = _math(group, "SUBTRACT", "Tilt Centered X", -1260, 650, value_2=0.5)
    centered_y = _math(group, "SUBTRACT", "Tilt Centered Y", -1260, 500, value_2=0.5)
    sine = _math(group, "SINE", "Tilt Angle Sine", -1260, 300)
    cosine = _math(group, "COSINE", "Tilt Angle Cosine", -1260, 180)
    negative_sine = _math(group, "MULTIPLY", "Tilt Normal X", -1070, 300, value_2=-1.0)
    projected_x = _math(group, "MULTIPLY", "Tilt Project X", -880, 650)
    projected_y = _math(group, "MULTIPLY", "Tilt Project Y", -880, 500)
    projected = _math(group, "ADD", "Tilt Projected Coordinate", -690, 570)
    projected_centered = _math(group, "ADD", "Tilt Projected UV", -510, 570, value_2=0.5)
    delta = _math(group, "SUBTRACT", "Tilt Distance", -330, 570)
    absolute = _math(group, "ABSOLUTE", "Tilt Absolute", -150, 570)
    half = _math(group, "MULTIPLY", "Tilt Half Width", -330, 390, value_2=0.5)
    outside = _math(group, "SUBTRACT", "Tilt Outside", 30, 570)
    normalized = _math(group, "DIVIDE", "Tilt Normalized", 210, 570)
    clamp_high = _math(group, "MINIMUM", "Tilt Clamp High", 390, 570, value_2=1.0)
    clamp_low = _math(group, "MAXIMUM", "Tilt Clamp Low", 570, 570, value_2=0.0)

    links.new(inp.outputs["UV Vector"], separate.inputs[0])
    links.new(separate.outputs["X"], centered_x.inputs[0])
    links.new(separate.outputs["Y"], centered_y.inputs[0])
    links.new(inp.outputs["Focus Angle"], sine.inputs[0])
    links.new(inp.outputs["Focus Angle"], cosine.inputs[0])
    links.new(sine.outputs[0], negative_sine.inputs[0])
    links.new(centered_x.outputs[0], projected_x.inputs[0])
    links.new(negative_sine.outputs[0], projected_x.inputs[1])
    links.new(centered_y.outputs[0], projected_y.inputs[0])
    links.new(cosine.outputs[0], projected_y.inputs[1])
    links.new(projected_x.outputs[0], projected.inputs[0])
    links.new(projected_y.outputs[0], projected.inputs[1])
    links.new(projected.outputs[0], projected_centered.inputs[0])
    links.new(projected_centered.outputs[0], delta.inputs[0])
    links.new(inp.outputs["Focus Position"], delta.inputs[1])
    links.new(delta.outputs[0], absolute.inputs[0])
    links.new(inp.outputs["Focus Width"], half.inputs[0])
    links.new(absolute.outputs[0], outside.inputs[0])
    links.new(half.outputs[0], outside.inputs[1])
    links.new(outside.outputs[0], normalized.inputs[0])
    links.new(half.outputs[0], normalized.inputs[1])
    links.new(normalized.outputs[0], clamp_high.inputs[0])
    links.new(clamp_high.outputs[0], clamp_low.inputs[0])

    radius = _math(group, "MULTIPLY", "Tilt Radius", 760, 570)
    enabled = _math(group, "GREATER_THAN", "Tilt Enabled", 950, 570, value_2=0.0001)
    links.new(inp.outputs["Blur Radius"], radius.inputs[0])
    links.new(clamp_low.outputs[0], radius.inputs[1])
    links.new(radius.outputs[0], enabled.inputs[0])

    color_samples = []
    alpha_samples = []
    weights = []
    taps = [0.0, -1.0, -0.8, -0.6, -0.4, -0.2, 0.2, 0.4, 0.6, 0.8, 1.0, -0.3, 0.3]
    for index, tap_value in enumerate(taps):
        y = 430 - index * 150
        tap = _math(group, "MULTIPLY", f"Tilt Tap {index}", 1120, y, value_2=tap_value)
        x_pixels = _math(group, "MULTIPLY", f"Tilt X Pixels {index}", 1300, y + 35)
        y_pixels = _math(group, "MULTIPLY", f"Tilt Y Pixels {index}", 1300, y - 35)
        x_normal = _math(group, "MULTIPLY", f"Tilt X Normal {index}", 1480, y + 35)
        y_normal = _math(group, "MULTIPLY", f"Tilt Y Normal {index}", 1480, y - 35)
        offset = _node(group, "ShaderNodeCombineXYZ", f"Tilt Offset {index}", 1660, y)
        uv = _vector_math(group, "ADD", f"Tilt UV {index}", 1840, y)
        links.new(radius.outputs[0], tap.inputs[0])
        links.new(tap.outputs[0], x_pixels.inputs[0])
        links.new(inp.outputs["Texel X"], x_pixels.inputs[1])
        links.new(tap.outputs[0], y_pixels.inputs[0])
        links.new(inp.outputs["Texel Y"], y_pixels.inputs[1])
        links.new(x_pixels.outputs[0], x_normal.inputs[0])
        links.new(negative_sine.outputs[0], x_normal.inputs[1])
        links.new(y_pixels.outputs[0], y_normal.inputs[0])
        links.new(cosine.outputs[0], y_normal.inputs[1])
        links.new(x_normal.outputs[0], offset.inputs["X"])
        links.new(y_normal.outputs[0], offset.inputs["Y"])
        links.new(inp.outputs["UV Vector"], uv.inputs[0])
        links.new(offset.outputs[0], uv.inputs[1])
        weight = max(0.1, 1.0 - abs(tap_value))
        color, alpha = _blur_sample(group, inp, uv.outputs[0], weight, str(index), 2020, y, "Tilt Shift")
        color_samples.append(color)
        alpha_samples.append(alpha)
        weights.append(weight)

    _finish_alpha_safe_blur(
        group, inp, out,
        color_samples, alpha_samples,
        total_weight=sum(weights),
        enabled_socket=enabled.outputs[0],
        prefix="Tilt Shift",
    )
    return group


def _sample_source_luma(group, inp, radius_socket, ox, oy, prefix, x, y):
    """Sample source-image luminance at an offset measured in source pixels."""
    links = group.links
    px = _math(group, "MULTIPLY", f"{prefix} Radius X", x, y + 45, value_2=float(ox))
    py = _math(group, "MULTIPLY", f"{prefix} Radius Y", x, y - 45, value_2=float(oy))
    tx = _math(group, "MULTIPLY", f"{prefix} Texel X", x + 180, y + 45)
    ty = _math(group, "MULTIPLY", f"{prefix} Texel Y", x + 180, y - 45)
    offset = _node(group, "ShaderNodeCombineXYZ", f"{prefix} Offset", x + 360, y)
    uv = _vector_math(group, "ADD", f"{prefix} UV", x + 540, y)
    image = _source_image_node(group, f"{prefix} Sample", x + 720, y)
    luma = _node(group, "ShaderNodeRGBToBW", f"{prefix} Luminance", x + 910, y)
    links.new(radius_socket, px.inputs[0])
    links.new(radius_socket, py.inputs[0])
    links.new(px.outputs[0], tx.inputs[0])
    links.new(inp.outputs["Texel X"], tx.inputs[1])
    links.new(py.outputs[0], ty.inputs[0])
    links.new(inp.outputs["Texel Y"], ty.inputs[1])
    links.new(tx.outputs[0], offset.inputs["X"])
    links.new(ty.outputs[0], offset.inputs["Y"])
    links.new(inp.outputs["UV Vector"], uv.inputs[0])
    links.new(offset.outputs[0], uv.inputs[1])
    links.new(uv.outputs[0], image.inputs["Vector"])
    links.new(image.outputs["Color"], luma.inputs[0])
    return luma.outputs[0]


def _weighted_scalar_sum(group, terms, prefix, x, y):
    """Return a scalar socket containing a weighted sum of input sockets."""
    weighted = []
    for index, (socket, weight) in enumerate(terms):
        if float(weight) == 1.0:
            weighted.append(socket)
            continue
        node = _math(group, "MULTIPLY", f"{prefix} Weight {index}", x, y - index * 90, value_2=float(weight))
        group.links.new(socket, node.inputs[0])
        weighted.append(node.outputs[0])
    if not weighted:
        return None
    current = weighted[0]
    for index, socket in enumerate(weighted[1:], 1):
        add = _math(group, "ADD", f"{prefix} Sum {index}", x + 190 * index, y)
        group.links.new(current, add.inputs[0])
        group.links.new(socket, add.inputs[1])
        current = add.outputs[0]
    return current


def _local_luma_average(group, inp, radius_socket, prefix, x, y):
    """Weighted eight-neighbor luminance average (cardinals 2, diagonals 1)."""
    positions = (
        (-1, 1, 1), (0, 1, 2), (1, 1, 1),
        (-1, 0, 2), (1, 0, 2),
        (-1, -1, 1), (0, -1, 2), (1, -1, 1),
    )
    terms = []
    for index, (ox, oy, weight) in enumerate(positions):
        sample = _sample_source_luma(
            group, inp, radius_socket, ox, oy,
            f"{prefix} {index}", x, y - index * 155,
        )
        terms.append((sample, weight))
    total = _weighted_scalar_sum(group, terms, f"{prefix} Weighted", x + 1120, y)
    average = _math(group, "MULTIPLY", f"{prefix} Average", x + 2650, y, value_2=(1.0 / 12.0))
    group.links.new(total, average.inputs[0])
    return average.outputs[0]


def _sobel_magnitude(group, inp, radius_socket, prefix, x, y):
    """Build a true 3×3 Sobel magnitude from source-image luminance."""
    samples = {}
    positions = ((-1, 1), (0, 1), (1, 1), (-1, 0), (1, 0), (-1, -1), (0, -1), (1, -1))
    for index, (ox, oy) in enumerate(positions):
        samples[(ox, oy)] = _sample_source_luma(
            group, inp, radius_socket, ox, oy,
            f"{prefix} Sample {index}", x, y - index * 155,
        )
    gx = _weighted_scalar_sum(group, (
        (samples[(-1, 1)], -1), (samples[(-1, 0)], -2), (samples[(-1, -1)], -1),
        (samples[(1, 1)], 1), (samples[(1, 0)], 2), (samples[(1, -1)], 1),
    ), f"{prefix} Gx", x + 1120, y + 220)
    gy = _weighted_scalar_sum(group, (
        (samples[(-1, 1)], -1), (samples[(0, 1)], -2), (samples[(1, 1)], -1),
        (samples[(-1, -1)], 1), (samples[(0, -1)], 2), (samples[(1, -1)], 1),
    ), f"{prefix} Gy", x + 1120, y - 220)
    gx2 = _math(group, "MULTIPLY", f"{prefix} Gx Squared", x + 2450, y + 180)
    gy2 = _math(group, "MULTIPLY", f"{prefix} Gy Squared", x + 2450, y - 180)
    total = _math(group, "ADD", f"{prefix} Gradient Sum", x + 2650, y)
    magnitude = _math(group, "SQRT", f"{prefix} Magnitude", x + 2840, y)
    group.links.new(gx, gx2.inputs[0]); group.links.new(gx, gx2.inputs[1])
    group.links.new(gy, gy2.inputs[0]); group.links.new(gy, gy2.inputs[1])
    group.links.new(gx2.outputs[0], total.inputs[0]); group.links.new(gy2.outputs[0], total.inputs[1])
    group.links.new(total.outputs[0], magnitude.inputs[0])
    return magnitude.outputs[0]


def _smooth_threshold(group, value_socket, threshold_socket, softness_socket, prefix, x, y):
    """Convert a value to a smooth 0–1 mask around an editable threshold."""
    half = _math(group, "MULTIPLY", f"{prefix} Half Softness", x, y - 120, value_2=0.5)
    lower = _math(group, "SUBTRACT", f"{prefix} Lower", x + 190, y + 40)
    upper = _math(group, "ADD", f"{prefix} Upper", x + 190, y - 80)
    epsilon = _math(group, "ADD", f"{prefix} Minimum Width", x + 370, y - 170, value_2=0.00001)
    safe_upper = _math(group, "MAXIMUM", f"{prefix} Safe Upper", x + 550, y - 80)
    ramp = _node(group, "ShaderNodeMapRange", f"{prefix} Smooth Threshold", x + 760, y)
    ramp.interpolation_type = "SMOOTHERSTEP"
    ramp.clamp = True
    ramp.inputs["To Min"].default_value = 0.0
    ramp.inputs["To Max"].default_value = 1.0
    links = group.links
    links.new(softness_socket, half.inputs[0])
    links.new(threshold_socket, lower.inputs[0]); links.new(half.outputs[0], lower.inputs[1])
    links.new(threshold_socket, upper.inputs[0]); links.new(half.outputs[0], upper.inputs[1])
    links.new(lower.outputs[0], epsilon.inputs[0])
    links.new(upper.outputs[0], safe_upper.inputs[0]); links.new(epsilon.outputs[0], safe_upper.inputs[1])
    links.new(value_socket, ramp.inputs["Value"])
    links.new(lower.outputs[0], ramp.inputs["From Min"])
    links.new(safe_upper.outputs[0], ramp.inputs["From Max"])
    return ramp.outputs["Result"]


def _smooth_quantized_color(group, color_socket, levels_socket, softness_socket, prefix, x, y):
    """Quantize RGB channels with true smooth transitions at band boundaries."""
    links = group.links
    separate = _node(group, "ShaderNodeSeparateColor", f"{prefix} Separate", x, y)
    try:
        separate.mode = "RGB"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(color_socket, separate.inputs[0])
    safe_levels = _math(group, "MAXIMUM", f"{prefix} Safe Levels", x, y - 260, value_2=2.0)
    intervals = _math(group, "SUBTRACT", f"{prefix} Intervals", x + 180, y - 260, value_2=1.0)
    links.new(levels_socket, safe_levels.inputs[0]); links.new(safe_levels.outputs[0], intervals.inputs[0])
    results = []
    for index, channel in enumerate(("Red", "Green", "Blue")):
        cy = y + 260 - index * 210
        scaled = _math(group, "MULTIPLY", f"{prefix} {channel} Scaled", x + 200, cy)
        base = _math(group, "FLOOR", f"{prefix} {channel} Base", x + 390, cy + 55)
        fraction = _math(group, "FRACT", f"{prefix} {channel} Fraction", x + 390, cy - 55)
        half_soft = _math(group, "MULTIPLY", f"{prefix} {channel} Half Softness", x + 390, cy - 150, value_2=0.5)
        lower = _math(group, "SUBTRACT", f"{prefix} {channel} Lower", x + 580, cy - 100, value_1=0.5)
        upper = _math(group, "ADD", f"{prefix} {channel} Upper", x + 580, cy - 190, value_1=0.5)
        epsilon = _math(group, "ADD", f"{prefix} {channel} Epsilon", x + 760, cy - 250, value_2=0.00001)
        safe_upper = _math(group, "MAXIMUM", f"{prefix} {channel} Safe Upper", x + 940, cy - 190)
        transition = _node(group, "ShaderNodeMapRange", f"{prefix} {channel} Transition", x + 1120, cy)
        transition.interpolation_type = "SMOOTHERSTEP"; transition.clamp = True
        transition.inputs["To Min"].default_value = 0.0; transition.inputs["To Max"].default_value = 1.0
        rounded = _math(group, "ADD", f"{prefix} {channel} Rounded", x + 1320, cy)
        result = _math(group, "DIVIDE", f"{prefix} {channel} Quantized", x + 1510, cy)
        links.new(separate.outputs[channel], scaled.inputs[0]); links.new(intervals.outputs[0], scaled.inputs[1])
        links.new(scaled.outputs[0], base.inputs[0]); links.new(scaled.outputs[0], fraction.inputs[0])
        links.new(softness_socket, half_soft.inputs[0])
        links.new(half_soft.outputs[0], lower.inputs[1]); links.new(half_soft.outputs[0], upper.inputs[1])
        links.new(lower.outputs[0], epsilon.inputs[0])
        links.new(upper.outputs[0], safe_upper.inputs[0]); links.new(epsilon.outputs[0], safe_upper.inputs[1])
        links.new(fraction.outputs[0], transition.inputs["Value"])
        links.new(lower.outputs[0], transition.inputs["From Min"]); links.new(safe_upper.outputs[0], transition.inputs["From Max"])
        links.new(base.outputs[0], rounded.inputs[0]); links.new(transition.outputs["Result"], rounded.inputs[1])
        links.new(rounded.outputs[0], result.inputs[0]); links.new(intervals.outputs[0], result.inputs[1])
        results.append(result.outputs[0])
    combine = _node(group, "ShaderNodeCombineColor", f"{prefix} Combine", x + 1710, y)
    try:
        combine.mode = "RGB"
    except (AttributeError, TypeError, ValueError):
        pass
    for index, result in enumerate(results):
        links.new(result, combine.inputs[index])
    return combine.outputs[0]


def _create_unsharp_mask(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for n, t, d, mi, ma in (("Color In", "NodeSocketColor", (.5,.5,.5,1), None, None), ("UV Vector", "NodeSocketVector", None, None, None), ("Radius", "NodeSocketFloat", 1, 0, 32), ("Amount", "NodeSocketFloat", 1, 0, 4), ("Factor", "NodeSocketFloat", 1, 0, 1), ("Texel X", "NodeSocketFloat", .001, 0, 1), ("Texel Y", "NodeSocketFloat", .001, 0, 1)):
        _socket(group, n, "INPUT", t, default=d, minimum=mi, maximum=ma)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group); links = group.links
    average_luma = _local_luma_average(group, inp, inp.outputs["Radius"], "Unsharp", -1500, 420)
    source_luma = _node(group, "ShaderNodeRGBToBW", "Unsharp Source Luminance", 1450, 300)
    detail = _math(group, "SUBTRACT", "Unsharp Luminance Detail", 1650, 300)
    scaled = _math(group, "MULTIPLY", "Unsharp Detail Amount", 1840, 300)
    detail_color = _node(group, "ShaderNodeCombineColor", "Unsharp Detail Color", 2040, 300)
    result = _vector_math(group, "ADD", "Unsharp Result", 2240, 300)
    mix = _mix_rgb(group, "MIX", "Unsharp Factor", 2440, 300)
    try:
        detail_color.mode = "RGB"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(inp.outputs["Color In"], source_luma.inputs[0])
    links.new(source_luma.outputs[0], detail.inputs[0]); links.new(average_luma, detail.inputs[1])
    links.new(detail.outputs[0], scaled.inputs[0]); links.new(inp.outputs["Amount"], scaled.inputs[1])
    for index in range(3):
        links.new(scaled.outputs[0], detail_color.inputs[index])
    links.new(inp.outputs["Color In"], result.inputs[0]); links.new(detail_color.outputs[0], result.inputs[1])
    links.new(inp.outputs["Factor"], mix.inputs[0]); links.new(inp.outputs["Color In"], mix.inputs[1]); links.new(result.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Color Out"])
    return group


def _create_edge_detect(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for n, t, d, mi, ma in (("Color In", "NodeSocketColor", (.5,.5,.5,1), None, None), ("UV Vector", "NodeSocketVector", None, None, None), ("Width", "NodeSocketFloat", 1, 0, 32), ("Strength", "NodeSocketFloat", 2, 0, 10), ("Threshold", "NodeSocketFloat", .05, 0, 1), ("Softness", "NodeSocketFloat", .04, 0, 1), ("Edge Color", "NodeSocketColor", (0,0,0,1), None, None), ("Factor", "NodeSocketFloat", 1, 0, 1), ("Texel X", "NodeSocketFloat", .001, 0, 1), ("Texel Y", "NodeSocketFloat", .001, 0, 1)):
        _socket(group, n, "INPUT", t, default=d, minimum=mi, maximum=ma)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group); links = group.links
    magnitude = _sobel_magnitude(group, inp, inp.outputs["Width"], "Edge Detect", -1650, 500)
    strength = _math(group, "MULTIPLY", "Edge Detect Strength", 1400, 350)
    amount = _math(group, "MULTIPLY", "Edge Detect Factor", 2700, 350)
    mix = _mix_rgb(group, "MIX", "Edge Detect Color Mix", 2900, 350)
    links.new(magnitude, strength.inputs[0]); links.new(inp.outputs["Strength"], strength.inputs[1])
    mask = _smooth_threshold(group, strength.outputs[0], inp.outputs["Threshold"], inp.outputs["Softness"], "Edge Detect", 1600, 350)
    links.new(mask, amount.inputs[0]); links.new(inp.outputs["Factor"], amount.inputs[1])
    links.new(amount.outputs[0], mix.inputs[0]); links.new(inp.outputs["Color In"], mix.inputs[1]); links.new(inp.outputs["Edge Color"], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Color Out"])
    return group


def _create_smooth_toon(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(.5,.5,.5,1))
    _socket(group, "Levels", "INPUT", "NodeSocketFloat", default=6, minimum=2, maximum=64)
    _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=.15, minimum=0, maximum=1)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1, minimum=0, maximum=1)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group); links = group.links
    toon = _smooth_quantized_color(group, inp.outputs["Color In"], inp.outputs["Levels"], inp.outputs["Softness"], "Smooth Toon", -1050, 200)
    mix = _mix_rgb(group, "MIX", "Smooth Toon Factor", 900, 200)
    links.new(inp.outputs["Factor"], mix.inputs[0]); links.new(inp.outputs["Color In"], mix.inputs[1]); links.new(toon, mix.inputs[2]); links.new(mix.outputs[0], out.inputs["Color Out"])
    return group


def _create_adaptive_threshold(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for n, t, d, mi, ma in (("Color In", "NodeSocketColor", (.5,.5,.5,1), None, None), ("UV Vector", "NodeSocketVector", None, None, None), ("Radius", "NodeSocketFloat", 4, 0, 64), ("Offset", "NodeSocketFloat", 0, -1, 1), ("Softness", "NodeSocketFloat", .05, 0, 1), ("Invert", "NodeSocketFloat", 0, 0, 1), ("Factor", "NodeSocketFloat", 1, 0, 1), ("Texel X", "NodeSocketFloat", .001, 0, 1), ("Texel Y", "NodeSocketFloat", .001, 0, 1)):
        _socket(group, n, "INPUT", t, default=d, minimum=mi, maximum=ma)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group); links = group.links
    average = _local_luma_average(group, inp, inp.outputs["Radius"], "Adaptive Threshold", -1500, 420)
    source = _node(group, "ShaderNodeRGBToBW", "Adaptive Source Luminance", 1450, 360)
    cutoff = _math(group, "ADD", "Adaptive Cutoff", 1650, 160)
    delta = _math(group, "SUBTRACT", "Adaptive Delta", 1840, 360)
    zero = _node(group, "ShaderNodeValue", "Adaptive Zero Threshold", 1840, 120); zero.outputs[0].default_value = 0.0
    mask = _smooth_threshold(group, delta.outputs[0], zero.outputs[0], inp.outputs["Softness"], "Adaptive", 2040, 360)
    invert = _node(group, "ShaderNodeInvert", "Adaptive Invert", 3200, 240)
    invert_mix = _mix_rgb(group, "MIX", "Adaptive Invert Mix", 3400, 300)
    bw = _node(group, "ShaderNodeCombineColor", "Adaptive Black White", 3600, 300)
    final = _mix_rgb(group, "MIX", "Adaptive Factor", 3800, 300)
    try:
        bw.mode = "RGB"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(inp.outputs["Color In"], source.inputs[0])
    links.new(average, cutoff.inputs[0]); links.new(inp.outputs["Offset"], cutoff.inputs[1])
    links.new(source.outputs[0], delta.inputs[0]); links.new(cutoff.outputs[0], delta.inputs[1])
    links.new(mask, invert.inputs[1])
    links.new(inp.outputs["Invert"], invert_mix.inputs[0]); links.new(mask, invert_mix.inputs[1]); links.new(invert.outputs[0], invert_mix.inputs[2])
    for index in range(3): links.new(invert_mix.outputs[0], bw.inputs[index])
    links.new(inp.outputs["Factor"], final.inputs[0]); links.new(inp.outputs["Color In"], final.inputs[1]); links.new(bw.outputs[0], final.inputs[2])
    links.new(final.outputs[0], out.inputs["Color Out"])
    return group


def _create_ink(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for n, t, d, mi, ma in (("Color In", "NodeSocketColor", (.5,.5,.5,1), None, None), ("UV Vector", "NodeSocketVector", None, None, None), ("Width", "NodeSocketFloat", 1, 0, 32), ("Threshold", "NodeSocketFloat", .045, 0, 1), ("Softness", "NodeSocketFloat", .05, 0, 1), ("Strength", "NodeSocketFloat", 2.5, 0, 16), ("Ink Color", "NodeSocketColor", (.015,.01,.008,1), None, None), ("Paper Color", "NodeSocketColor", (.94,.90,.80,1), None, None), ("Preserve Color", "NodeSocketFloat", .2, 0, 1), ("Factor", "NodeSocketFloat", 1, 0, 1), ("Texel X", "NodeSocketFloat", .001, 0, 1), ("Texel Y", "NodeSocketFloat", .001, 0, 1)):
        _socket(group, n, "INPUT", t, default=d, minimum=mi, maximum=ma)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group); links = group.links
    magnitude = _sobel_magnitude(group, inp, inp.outputs["Width"], "Ink", -1650, 500)
    strength = _math(group, "MULTIPLY", "Ink Strength", 1400, 360)
    base = _mix_rgb(group, "MIX", "Ink Paper Base", 1400, 80)
    ink_mix = _mix_rgb(group, "MIX", "Ink Lines", 2800, 300)
    final = _mix_rgb(group, "MIX", "Ink Factor", 3000, 300)
    links.new(magnitude, strength.inputs[0]); links.new(inp.outputs["Strength"], strength.inputs[1])
    mask = _smooth_threshold(group, strength.outputs[0], inp.outputs["Threshold"], inp.outputs["Softness"], "Ink", 1600, 360)
    links.new(inp.outputs["Preserve Color"], base.inputs[0]); links.new(inp.outputs["Paper Color"], base.inputs[1]); links.new(inp.outputs["Color In"], base.inputs[2])
    links.new(mask, ink_mix.inputs[0]); links.new(base.outputs[0], ink_mix.inputs[1]); links.new(inp.outputs["Ink Color"], ink_mix.inputs[2])
    links.new(inp.outputs["Factor"], final.inputs[0]); links.new(inp.outputs["Color In"], final.inputs[1]); links.new(ink_mix.outputs[0], final.inputs[2])
    links.new(final.outputs[0], out.inputs["Color Out"])
    return group


def _create_edge_work(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for n, t, d, mi, ma in (("Color In", "NodeSocketColor", (.5,.5,.5,1), None, None), ("UV Vector", "NodeSocketVector", None, None, None), ("Radius", "NodeSocketFloat", 1.5, 0, 64), ("Thickness", "NodeSocketFloat", 4, 0, 128), ("Strength", "NodeSocketFloat", 5, 0, 32), ("Threshold", "NodeSocketFloat", .025, 0, 1), ("Softness", "NodeSocketFloat", .06, 0, 1), ("Edge Color", "NodeSocketColor", (.02,.015,.01,1), None, None), ("Factor", "NodeSocketFloat", 1, 0, 1), ("Texel X", "NodeSocketFloat", .001, 0, 1), ("Texel Y", "NodeSocketFloat", .001, 0, 1)):
        _socket(group, n, "INPUT", t, default=d, minimum=mi, maximum=ma)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group); links = group.links
    outer_radius = _math(group, "ADD", "Edge Work Outer Radius", -1600, -850)
    links.new(inp.outputs["Radius"], outer_radius.inputs[0]); links.new(inp.outputs["Thickness"], outer_radius.inputs[1])
    inner = _local_luma_average(group, inp, inp.outputs["Radius"], "Edge Work Inner", -1500, 650)
    outer = _local_luma_average(group, inp, outer_radius.outputs[0], "Edge Work Outer", -1500, -900)
    difference = _math(group, "SUBTRACT", "Edge Work Difference", 1500, 260)
    absolute = _math(group, "ABSOLUTE", "Edge Work Absolute", 1690, 260)
    strength = _math(group, "MULTIPLY", "Edge Work Strength", 1880, 260)
    amount = _math(group, "MULTIPLY", "Edge Work Factor", 3150, 260)
    mix = _mix_rgb(group, "MIX", "Edge Work Color", 3350, 260)
    links.new(inner, difference.inputs[0]); links.new(outer, difference.inputs[1]); links.new(difference.outputs[0], absolute.inputs[0])
    links.new(absolute.outputs[0], strength.inputs[0]); links.new(inp.outputs["Strength"], strength.inputs[1])
    mask = _smooth_threshold(group, strength.outputs[0], inp.outputs["Threshold"], inp.outputs["Softness"], "Edge Work", 2070, 260)
    links.new(mask, amount.inputs[0]); links.new(inp.outputs["Factor"], amount.inputs[1])
    links.new(amount.outputs[0], mix.inputs[0]); links.new(inp.outputs["Color In"], mix.inputs[1]); links.new(inp.outputs["Edge Color"], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Color Out"])
    return group


def _create_pencil_sketch(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for n, t, d, mi, ma in (("Color In", "NodeSocketColor", (.5,.5,.5,1), None, None), ("UV Vector", "NodeSocketVector", None, None, None), ("Radius", "NodeSocketFloat", 6, 0, 128), ("Contrast", "NodeSocketFloat", 1.6, 0, 8), ("Graphite Color", "NodeSocketColor", (.03,.025,.02,1), None, None), ("Paper Color", "NodeSocketColor", (.96,.93,.84,1), None, None), ("Color Amount", "NodeSocketFloat", 0, 0, 1), ("Factor", "NodeSocketFloat", 1, 0, 1), ("Texel X", "NodeSocketFloat", .001, 0, 1), ("Texel Y", "NodeSocketFloat", .001, 0, 1)):
        _socket(group, n, "INPUT", t, default=d, minimum=mi, maximum=ma)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group); links = group.links
    average = _local_luma_average(group, inp, inp.outputs["Radius"], "Pencil", -1500, 420)
    source = _node(group, "ShaderNodeRGBToBW", "Pencil Source Luminance", 1450, 360)
    safe_average = _math(group, "MAXIMUM", "Pencil Safe Average", 1650, 160, value_2=0.00001)
    divide = _math(group, "DIVIDE", "Pencil Color Dodge", 1840, 360)
    clamp = _math(group, "MINIMUM", "Pencil Clamp", 2030, 360, value_2=1.0)
    darkness = _math(group, "SUBTRACT", "Pencil Darkness", 2220, 360, value_1=1.0)
    contrast = _math(group, "MULTIPLY", "Pencil Contrast", 2410, 360)
    dark_clamp = _math(group, "MINIMUM", "Pencil Dark Clamp", 2600, 360, value_2=1.0)
    sketch = _math(group, "SUBTRACT", "Pencil Sketch Value", 2790, 360, value_1=1.0)
    sketch_color = _node(group, "ShaderNodeCombineColor", "Pencil Sketch Grayscale", 2980, 80)
    tone = _mix_rgb(group, "MIX", "Pencil Tone Map", 3180, 420)
    colorized = _mix_rgb(group, "MULTIPLY", "Pencil Source Color", 3180, 160, fac=1.0)
    color_mix = _mix_rgb(group, "MIX", "Pencil Color Amount", 3400, 340)
    final = _mix_rgb(group, "MIX", "Pencil Factor", 3620, 340)
    try:
        sketch_color.mode = "RGB"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(inp.outputs["Color In"], source.inputs[0]); links.new(average, safe_average.inputs[0])
    links.new(source.outputs[0], divide.inputs[0]); links.new(safe_average.outputs[0], divide.inputs[1]); links.new(divide.outputs[0], clamp.inputs[0])
    links.new(clamp.outputs[0], darkness.inputs[1]); links.new(darkness.outputs[0], contrast.inputs[0]); links.new(inp.outputs["Contrast"], contrast.inputs[1])
    links.new(contrast.outputs[0], dark_clamp.inputs[0]); links.new(dark_clamp.outputs[0], sketch.inputs[1])
    for index in range(3):
        links.new(sketch.outputs[0], sketch_color.inputs[index])
    links.new(sketch.outputs[0], tone.inputs[0]); links.new(inp.outputs["Graphite Color"], tone.inputs[1]); links.new(inp.outputs["Paper Color"], tone.inputs[2])
    links.new(inp.outputs["Color In"], colorized.inputs[1]); links.new(sketch_color.outputs[0], colorized.inputs[2])
    links.new(inp.outputs["Color Amount"], color_mix.inputs[0]); links.new(tone.outputs[0], color_mix.inputs[1]); links.new(colorized.outputs[0], color_mix.inputs[2])
    links.new(inp.outputs["Factor"], final.inputs[0]); links.new(inp.outputs["Color In"], final.inputs[1]); links.new(color_mix.outputs[0], final.inputs[2])
    links.new(final.outputs[0], out.inputs["Color Out"])
    return group


def _create_poster_edges(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for n, t, d, mi, ma in (("Color In", "NodeSocketColor", (.5,.5,.5,1), None, None), ("UV Vector", "NodeSocketVector", None, None, None), ("Levels", "NodeSocketFloat", 5, 2, 64), ("Band Softness", "NodeSocketFloat", .08, 0, 1), ("Edge Width", "NodeSocketFloat", 1, 0, 32), ("Edge Strength", "NodeSocketFloat", 2.8, 0, 16), ("Edge Threshold", "NodeSocketFloat", .045, 0, 1), ("Edge Color", "NodeSocketColor", (.01,.008,.006,1), None, None), ("Factor", "NodeSocketFloat", 1, 0, 1), ("Texel X", "NodeSocketFloat", .001, 0, 1), ("Texel Y", "NodeSocketFloat", .001, 0, 1)):
        _socket(group, n, "INPUT", t, default=d, minimum=mi, maximum=ma)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group); links = group.links
    poster = _smooth_quantized_color(group, inp.outputs["Color In"], inp.outputs["Levels"], inp.outputs["Band Softness"], "Poster Edges", -1650, 1000)
    magnitude = _sobel_magnitude(group, inp, inp.outputs["Edge Width"], "Poster Edges", -1650, -300)
    strength = _math(group, "MULTIPLY", "Poster Edge Strength", 1400, -220)
    zero_soft = _node(group, "ShaderNodeValue", "Poster Edge Softness", 1400, -420); zero_soft.outputs[0].default_value = 0.035
    edge_mix = _mix_rgb(group, "MIX", "Poster Edge Color", 2800, 300)
    final = _mix_rgb(group, "MIX", "Poster Edges Factor", 3020, 300)
    links.new(magnitude, strength.inputs[0]); links.new(inp.outputs["Edge Strength"], strength.inputs[1])
    mask = _smooth_threshold(group, strength.outputs[0], inp.outputs["Edge Threshold"], zero_soft.outputs[0], "Poster Edges", 1600, -220)
    links.new(mask, edge_mix.inputs[0]); links.new(poster, edge_mix.inputs[1]); links.new(inp.outputs["Edge Color"], edge_mix.inputs[2])
    links.new(inp.outputs["Factor"], final.inputs[0]); links.new(inp.outputs["Color In"], final.inputs[1]); links.new(edge_mix.outputs[0], final.inputs[2])
    links.new(final.outputs[0], out.inputs["Color Out"])
    return group


def _periodic_line(group, coordinate_socket, scale_socket, width_socket, prefix, x, y):
    scaled = _math(group, "MULTIPLY", f"{prefix} Scale", x, y)
    fraction = _math(group, "FRACT", f"{prefix} Fraction", x + 180, y)
    center = _math(group, "SUBTRACT", f"{prefix} Center", x + 360, y, value_2=0.5)
    absolute = _math(group, "ABSOLUTE", f"{prefix} Absolute", x + 540, y)
    line = _math(group, "LESS_THAN", f"{prefix} Line", x + 720, y)
    group.links.new(coordinate_socket, scaled.inputs[0]); group.links.new(scale_socket, scaled.inputs[1])
    group.links.new(scaled.outputs[0], fraction.inputs[0]); group.links.new(fraction.outputs[0], center.inputs[0])
    group.links.new(center.outputs[0], absolute.inputs[0]); group.links.new(absolute.outputs[0], line.inputs[0]); group.links.new(width_socket, line.inputs[1])
    return line.outputs[0]


def _create_crosshatch(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for n, t, d, mi, ma in (("Color In", "NodeSocketColor", (.5,.5,.5,1), None, None), ("UV Vector", "NodeSocketVector", None, None, None), ("Scale", "NodeSocketFloat", 72, 1, 2000), ("Rotation", "NodeSocketFloat", 0, -6.283, 6.283), ("Line Width", "NodeSocketFloat", .10, .001, .49), ("Levels", "NodeSocketInt", 4, 1, 4), ("Ink Color", "NodeSocketColor", (.02,.015,.01,1), None, None), ("Paper Color", "NodeSocketColor", (.95,.91,.80,1), None, None), ("Preserve Color", "NodeSocketFloat", .10, 0, 1), ("Factor", "NodeSocketFloat", 1, 0, 1), ("Texel X", "NodeSocketFloat", .001, 0, 1), ("Texel Y", "NodeSocketFloat", .001, 0, 1)):
        _socket(group, n, "INPUT", t, default=d, minimum=mi, maximum=ma)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group); links = group.links
    centered = _vector_math(group, "SUBTRACT", "Crosshatch Center UV", -1200, 420); centered.inputs[1].default_value = (0.5,0.5,0.0)
    separate = _node(group, "ShaderNodeSeparateXYZ", "Crosshatch Source Axes", -1020, 420)
    aspect = _math(group, "DIVIDE", "Crosshatch Aspect", -1020, 120)
    x_aspect = _math(group, "MULTIPLY", "Crosshatch Aspect X", -820, 500)
    combine = _node(group, "ShaderNodeCombineXYZ", "Crosshatch Aspect UV", -620, 420)
    rotate = _node(group, "ShaderNodeVectorRotate", "Crosshatch Rotation", -420, 420); rotate.rotation_type = "Z_AXIS"; rotate.inputs["Center"].default_value = (0,0,0)
    axes = _node(group, "ShaderNodeSeparateXYZ", "Crosshatch Axes", -220, 420)
    diag_a = _math(group, "ADD", "Crosshatch Diagonal A", -20, 300)
    diag_b = _math(group, "SUBTRACT", "Crosshatch Diagonal B", -20, 150)
    luma = _node(group, "ShaderNodeRGBToBW", "Crosshatch Luminance", -220, 20)
    darkness = _math(group, "SUBTRACT", "Crosshatch Darkness", -20, 20, value_1=1.0)
    links.new(inp.outputs["UV Vector"], centered.inputs[0]); links.new(centered.outputs[0], separate.inputs[0])
    links.new(inp.outputs["Texel Y"], aspect.inputs[0]); links.new(inp.outputs["Texel X"], aspect.inputs[1])
    links.new(separate.outputs["X"], x_aspect.inputs[0]); links.new(aspect.outputs[0], x_aspect.inputs[1])
    links.new(x_aspect.outputs[0], combine.inputs["X"]); links.new(separate.outputs["Y"], combine.inputs["Y"])
    links.new(combine.outputs[0], rotate.inputs["Vector"]); links.new(inp.outputs["Rotation"], rotate.inputs["Angle"]); links.new(rotate.outputs["Vector"], axes.inputs[0])
    links.new(axes.outputs["X"], diag_a.inputs[0]); links.new(axes.outputs["Y"], diag_a.inputs[1]); links.new(axes.outputs["X"], diag_b.inputs[0]); links.new(axes.outputs["Y"], diag_b.inputs[1])
    links.new(inp.outputs["Color In"], luma.inputs[0]); links.new(luma.outputs[0], darkness.inputs[1])
    coordinates = (axes.outputs["X"], axes.outputs["Y"], diag_a.outputs[0], diag_b.outputs[0])
    thresholds = (0.18, 0.38, 0.58, 0.76)
    active_lines = []
    for index, (coordinate, threshold) in enumerate(zip(coordinates, thresholds, strict=False), 1):
        line = _periodic_line(group, coordinate, inp.outputs["Scale"], inp.outputs["Line Width"], f"Crosshatch {index}", 180, 620 - index * 160)
        dark_test = _math(group, "GREATER_THAN", f"Crosshatch Darkness Level {index}", 1100, 620 - index * 160, value_2=threshold)
        level_test = _math(group, "GREATER_THAN", f"Crosshatch Enabled Level {index}", 1100, 540 - index * 160, value_2=(index - 0.5))
        active = _math(group, "MULTIPLY", f"Crosshatch Active {index}", 1300, 600 - index * 160)
        active_level = _math(group, "MULTIPLY", f"Crosshatch Active Level {index}", 1490, 600 - index * 160)
        links.new(darkness.outputs[0], dark_test.inputs[0]); links.new(inp.outputs["Levels"], level_test.inputs[0])
        links.new(line, active.inputs[0]); links.new(dark_test.outputs[0], active.inputs[1]); links.new(active.outputs[0], active_level.inputs[0]); links.new(level_test.outputs[0], active_level.inputs[1])
        active_lines.append(active_level.outputs[0])
    hatch = active_lines[0]
    for index, socket in enumerate(active_lines[1:], 2):
        maximum = _math(group, "MAXIMUM", f"Crosshatch Combine {index}", 1700 + index * 150, 300)
        links.new(hatch, maximum.inputs[0]); links.new(socket, maximum.inputs[1]); hatch = maximum.outputs[0]
    base = _mix_rgb(group, "MIX", "Crosshatch Paper Base", 2450, 180)
    ink = _mix_rgb(group, "MIX", "Crosshatch Ink", 2650, 300)
    final = _mix_rgb(group, "MIX", "Crosshatch Factor", 2860, 300)
    links.new(inp.outputs["Preserve Color"], base.inputs[0]); links.new(inp.outputs["Paper Color"], base.inputs[1]); links.new(inp.outputs["Color In"], base.inputs[2])
    links.new(hatch, ink.inputs[0]); links.new(base.outputs[0], ink.inputs[1]); links.new(inp.outputs["Ink Color"], ink.inputs[2])
    links.new(inp.outputs["Factor"], final.inputs[0]); links.new(inp.outputs["Color In"], final.inputs[1]); links.new(ink.outputs[0], final.inputs[2]); links.new(final.outputs[0], out.inputs["Color Out"])
    return group


def _create_emboss(name):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for n, t, d, mi, ma in (("Color In", "NodeSocketColor", (.5,.5,.5,1), None, None), ("UV Vector", "NodeSocketVector", None, None, None), ("Angle", "NodeSocketFloat", .785398, -6.283, 6.283), ("Distance", "NodeSocketFloat", 2, 0, 128), ("Strength", "NodeSocketFloat", 2, -8, 8), ("Bias", "NodeSocketFloat", .5, 0, 1), ("Color Amount", "NodeSocketFloat", 0, 0, 1), ("Factor", "NodeSocketFloat", 1, 0, 1), ("Texel X", "NodeSocketFloat", .001, 0, 1), ("Texel Y", "NodeSocketFloat", .001, 0, 1)):
        _socket(group, n, "INPUT", t, default=d, minimum=mi, maximum=ma)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    inp, out = _group_io(group); links = group.links
    cosine = _math(group, "COSINE", "Emboss Cosine", -1100, 500); sine = _math(group, "SINE", "Emboss Sine", -1100, 350)
    dx = _math(group, "MULTIPLY", "Emboss Direction X", -900, 500); dy = _math(group, "MULTIPLY", "Emboss Direction Y", -900, 350)
    tx = _math(group, "MULTIPLY", "Emboss Texel X", -700, 500); ty = _math(group, "MULTIPLY", "Emboss Texel Y", -700, 350)
    offset = _node(group, "ShaderNodeCombineXYZ", "Emboss Offset", -500, 420)
    uv_plus = _vector_math(group, "ADD", "Emboss Positive UV", -300, 500); uv_minus = _vector_math(group, "SUBTRACT", "Emboss Negative UV", -300, 280)
    image_plus = _source_image_node(group, "Emboss Positive Sample", -100, 500); image_minus = _source_image_node(group, "Emboss Negative Sample", -100, 280)
    luma_plus = _node(group, "ShaderNodeRGBToBW", "Emboss Positive Luminance", 100, 500); luma_minus = _node(group, "ShaderNodeRGBToBW", "Emboss Negative Luminance", 100, 280)
    difference = _math(group, "SUBTRACT", "Emboss Difference", 300, 400); strength = _math(group, "MULTIPLY", "Emboss Strength", 500, 400); bias = _math(group, "ADD", "Emboss Bias", 700, 400)
    minimum = _math(group, "MAXIMUM", "Emboss Minimum", 900, 400, value_2=0); maximum = _math(group, "MINIMUM", "Emboss Maximum", 1080, 400, value_2=1)
    grayscale = _node(group, "ShaderNodeCombineColor", "Emboss Grayscale", 1260, 400)
    colorized = _mix_rgb(group, "MULTIPLY", "Emboss Colorized", 1450, 220, fac=1.0)
    color_mix = _mix_rgb(group, "MIX", "Emboss Color Amount", 1660, 360)
    final = _mix_rgb(group, "MIX", "Emboss Factor", 1870, 360)
    try: grayscale.mode = "RGB"
    except (AttributeError, TypeError, ValueError): pass
    links.new(inp.outputs["Angle"], cosine.inputs[0]); links.new(inp.outputs["Angle"], sine.inputs[0])
    links.new(cosine.outputs[0], dx.inputs[0]); links.new(inp.outputs["Distance"], dx.inputs[1]); links.new(sine.outputs[0], dy.inputs[0]); links.new(inp.outputs["Distance"], dy.inputs[1])
    links.new(dx.outputs[0], tx.inputs[0]); links.new(inp.outputs["Texel X"], tx.inputs[1]); links.new(dy.outputs[0], ty.inputs[0]); links.new(inp.outputs["Texel Y"], ty.inputs[1])
    links.new(tx.outputs[0], offset.inputs["X"]); links.new(ty.outputs[0], offset.inputs["Y"])
    links.new(inp.outputs["UV Vector"], uv_plus.inputs[0]); links.new(offset.outputs[0], uv_plus.inputs[1]); links.new(inp.outputs["UV Vector"], uv_minus.inputs[0]); links.new(offset.outputs[0], uv_minus.inputs[1])
    links.new(uv_plus.outputs[0], image_plus.inputs["Vector"]); links.new(uv_minus.outputs[0], image_minus.inputs["Vector"])
    links.new(image_plus.outputs["Color"], luma_plus.inputs[0]); links.new(image_minus.outputs["Color"], luma_minus.inputs[0])
    links.new(luma_plus.outputs[0], difference.inputs[0]); links.new(luma_minus.outputs[0], difference.inputs[1]); links.new(difference.outputs[0], strength.inputs[0]); links.new(inp.outputs["Strength"], strength.inputs[1])
    links.new(strength.outputs[0], bias.inputs[0]); links.new(inp.outputs["Bias"], bias.inputs[1]); links.new(bias.outputs[0], minimum.inputs[0]); links.new(minimum.outputs[0], maximum.inputs[0])
    for index in range(3): links.new(maximum.outputs[0], grayscale.inputs[index])
    links.new(inp.outputs["Color In"], colorized.inputs[1]); links.new(grayscale.outputs[0], colorized.inputs[2])
    links.new(inp.outputs["Color Amount"], color_mix.inputs[0]); links.new(grayscale.outputs[0], color_mix.inputs[1]); links.new(colorized.outputs[0], color_mix.inputs[2])
    links.new(inp.outputs["Factor"], final.inputs[0]); links.new(inp.outputs["Color In"], final.inputs[1]); links.new(color_mix.outputs[0], final.inputs[2]); links.new(final.outputs[0], out.inputs["Color Out"])
    return group


def _create_false_color(name):
    group=bpy.data.node_groups.new(name,"ShaderNodeTree");_socket(group,"Color In","INPUT","NodeSocketColor",default=(.5,.5,.5,1));_socket(group,"Dark Color","INPUT","NodeSocketColor",default=(0,.05,.3,1));_socket(group,"Light Color","INPUT","NodeSocketColor",default=(1,.65,.05,1));_socket(group,"Factor","INPUT","NodeSocketFloat",default=1,minimum=0,maximum=1);_socket(group,"Color Out","OUTPUT","NodeSocketColor");inp,out=_group_io(group);links=group.links;l=_node(group,"ShaderNodeRGBToBW","False Color Luma",-400,150);mapc=_mix_rgb(group,"MIX","False Color Map",-100,150);mix=_mix_rgb(group,"MIX","False Color Factor",180,150);links.new(inp.outputs["Color In"],l.inputs[0]);links.new(l.outputs[0],mapc.inputs[0]);links.new(inp.outputs["Dark Color"],mapc.inputs[1]);links.new(inp.outputs["Light Color"],mapc.inputs[2]);links.new(inp.outputs["Factor"],mix.inputs[0]);links.new(inp.outputs["Color In"],mix.inputs[1]);links.new(mapc.outputs[0],mix.inputs[2]);links.new(mix.outputs[0],out.inputs["Color Out"]);return group


def _create_chromatic_aberration(name):
    group=bpy.data.node_groups.new(name,"ShaderNodeTree")
    for n,t,d,mi,ma in (("Color In","NodeSocketColor",(.5,.5,.5,1),None,None),("UV Vector","NodeSocketVector",None,None,None),("Distance","NodeSocketFloat",3,0,128),("Angle","NodeSocketFloat",0,-6.283,6.283),("Factor","NodeSocketFloat",1,0,1),("Texel X","NodeSocketFloat",.001,0,1),("Texel Y","NodeSocketFloat",.001,0,1)):_socket(group,n,"INPUT",t,default=d,minimum=mi,maximum=ma)
    _socket(group,"Color Out","OUTPUT","NodeSocketColor");inp,out=_group_io(group);links=group.links;cos=_math(group,"COSINE","CA Cos",-900,400);sin=_math(group,"SINE","CA Sin",-900,250);dx=_math(group,"MULTIPLY","CA DX",-720,400);dy=_math(group,"MULTIPLY","CA DY",-720,250);tx=_math(group,"MULTIPLY","CA TX",-540,400);ty=_math(group,"MULTIPLY","CA TY",-540,250);off=_node(group,"ShaderNodeCombineXYZ","CA Offset",-360,320);uvr=_vector_math(group,"ADD","CA Red UV",-180,420);uvb=_vector_math(group,"SUBTRACT","CA Blue UV",-180,180);red=_source_image_node(group,"CA Red",20,420);blue=_source_image_node(group,"CA Blue",20,180);sr=_node(group,"ShaderNodeSeparateColor","CA Red Split",220,420);ss=_node(group,"ShaderNodeSeparateColor","CA Source Split",220,300);sb=_node(group,"ShaderNodeSeparateColor","CA Blue Split",220,180);comb=_node(group,"ShaderNodeCombineColor","CA Combine",440,300);mix=_mix_rgb(group,"MIX","CA Factor",660,300)
    for n in (sr, ss, sb, comb):
        try:
            n.mode = 'RGB'
        except (AttributeError, TypeError, ValueError):
            pass
    links.new(inp.outputs["Angle"],cos.inputs[0]);links.new(inp.outputs["Angle"],sin.inputs[0]);links.new(cos.outputs[0],dx.inputs[0]);links.new(inp.outputs["Distance"],dx.inputs[1]);links.new(sin.outputs[0],dy.inputs[0]);links.new(inp.outputs["Distance"],dy.inputs[1]);links.new(dx.outputs[0],tx.inputs[0]);links.new(inp.outputs["Texel X"],tx.inputs[1]);links.new(dy.outputs[0],ty.inputs[0]);links.new(inp.outputs["Texel Y"],ty.inputs[1]);links.new(tx.outputs[0],off.inputs["X"]);links.new(ty.outputs[0],off.inputs["Y"]);links.new(inp.outputs["UV Vector"],uvr.inputs[0]);links.new(off.outputs[0],uvr.inputs[1]);links.new(inp.outputs["UV Vector"],uvb.inputs[0]);links.new(off.outputs[0],uvb.inputs[1]);links.new(uvr.outputs[0],red.inputs["Vector"]);links.new(uvb.outputs[0],blue.inputs["Vector"]);links.new(red.outputs["Color"],sr.inputs[0]);links.new(inp.outputs["Color In"],ss.inputs[0]);links.new(blue.outputs["Color"],sb.inputs[0]);links.new(sr.outputs["Red"],comb.inputs[0]);links.new(ss.outputs["Green"],comb.inputs[1]);links.new(sb.outputs["Blue"],comb.inputs[2]);links.new(inp.outputs["Factor"],mix.inputs[0]);links.new(inp.outputs["Color In"],mix.inputs[1]);links.new(comb.outputs[0],mix.inputs[2]);links.new(mix.outputs[0],out.inputs["Color Out"]);return group


def _create_gradient_light(name):
    """Multiply the source by a directional user-editable Color Ramp."""
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Center X", "INPUT", "NodeSocketFloat", default=0.5, minimum=-2.0, maximum=3.0)
    _socket(group, "Center Y", "INPUT", "NodeSocketFloat", default=0.5, minimum=-2.0, maximum=3.0)
    _socket(group, "Light Angle", "INPUT", "NodeSocketFloat", default=0.0, minimum=-6.283185, maximum=6.283185)
    _socket(group, "Light Position", "INPUT", "NodeSocketFloat", default=0.0, minimum=-2.0, maximum=2.0)
    _socket(group, "Strength", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    center_vector = _node(group, "ShaderNodeCombineXYZ", "Gradient Light Center", -900, -80)
    center = _vector_math(group, "SUBTRACT", "Centered Light UV", -700, 120)
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

    links.new(inp.outputs["Center X"], center_vector.inputs["X"])
    links.new(inp.outputs["Center Y"], center_vector.inputs["Y"])
    links.new(inp.outputs["UV Vector"], center.inputs[0])
    links.new(center_vector.outputs[0], center.inputs[1])
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
    links.new(inp.outputs["Alpha In"], out.inputs["Alpha Out"])
    group["fbp_color_ramp_contract_version"] = 1
    return group


def _rim_image_sample(group, uv_output, vector_offset, name, x, y):
    add = _vector_math(group, "ADD", f"{name} UV", x, y)
    image = _node(group, "ShaderNodeTexImage", f"{name} Sample", x + 210, y)
    image["fbp_matrix_source_image_node"] = True
    image["fbp_source_interpolation"] = "Linear"
    # Rim samples must not extend edge pixels beyond the image domain. The
    # private-source synchronizer reads this explicit contract instead of
    # forcing EXTEND on every image-aware shader effect.
    image["fbp_source_extension"] = "CLIP"
    try:
        image.extension = "CLIP"
        image.interpolation = "Linear"
    except (AttributeError, TypeError, ValueError):
        pass
    group.links.new(uv_output, add.inputs[0])
    group.links.new(vector_offset, add.inputs[1])
    group.links.new(add.outputs[0], image.inputs["Vector"])
    return image.outputs["Alpha"]


def _create_rim(name):
    """Create a Grease-Pencil-like inner/outer rim with editable blending.

    Two spatial alpha kernels provide an actual feather radius. The signed
    selection control grows or shrinks the band, while straight-alpha
    compositing lets Outer and Both modes expand the silhouette cleanly.
    """
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Image Sample", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Blend Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=7.0)
    _socket(group, "Width", "INPUT", "NodeSocketFloat", default=0.012, minimum=0.00001, maximum=0.5)
    _socket(group, "Expand / Shrink", "INPUT", "NodeSocketFloat", default=0.0, minimum=-0.5, maximum=0.5)
    _socket(group, "Offset X", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1.0, maximum=1.0)
    _socket(group, "Offset Y", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1.0, maximum=1.0)
    _socket(group, "Rotation", "INPUT", "NodeSocketFloat", default=0.0, minimum=-6.283185307, maximum=6.283185307)
    _socket(group, "Blur", "INPUT", "NodeSocketFloat", default=0.015, minimum=0.0, maximum=0.5)
    _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=0.5, minimum=0.0, maximum=1.0)
    _socket(group, "Intensity", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=2.0)
    _socket(group, "Rim Color", "INPUT", "NodeSocketColor", default=(1.0, 0.35, 0.05, 1.0))
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    # Rotate the controller offset in plane-local space. The controller itself
    # is parented to the plane, so its local Z rotation follows any rig/plane
    # orientation without introducing world-space assumptions.
    cosine = _math(group, "COSINE", "Rim Rotation Cosine", -1900, 820)
    sine = _math(group, "SINE", "Rim Rotation Sine", -1900, 680)
    x_cos = _math(group, "MULTIPLY", "Rim X Cos", -1710, 860)
    y_sin = _math(group, "MULTIPLY", "Rim Y Sin", -1710, 750)
    x_sin = _math(group, "MULTIPLY", "Rim X Sin", -1710, 630)
    y_cos = _math(group, "MULTIPLY", "Rim Y Cos", -1710, 520)
    rotated_x = _math(group, "SUBTRACT", "Rim Rotated X", -1510, 820)
    rotated_y = _math(group, "ADD", "Rim Rotated Y", -1510, 600)
    negative_x = _math(group, "MULTIPLY", "Rim Negative X", -1320, 820, value_2=-1.0)
    negative_y = _math(group, "MULTIPLY", "Rim Negative Y", -1320, 600, value_2=-1.0)
    spatial_offset = _node(group, "ShaderNodeCombineXYZ", "Rim Spatial Offset", -1130, 710)
    shifted_uv = _vector_math(group, "ADD", "Rim Shifted UV", -930, 710)
    links.new(inp.outputs["Rotation"], cosine.inputs[0])
    links.new(inp.outputs["Rotation"], sine.inputs[0])
    links.new(inp.outputs["Offset X"], x_cos.inputs[0])
    links.new(cosine.outputs[0], x_cos.inputs[1])
    links.new(inp.outputs["Offset Y"], y_sin.inputs[0])
    links.new(sine.outputs[0], y_sin.inputs[1])
    links.new(inp.outputs["Offset X"], x_sin.inputs[0])
    links.new(sine.outputs[0], x_sin.inputs[1])
    links.new(inp.outputs["Offset Y"], y_cos.inputs[0])
    links.new(cosine.outputs[0], y_cos.inputs[1])
    links.new(x_cos.outputs[0], rotated_x.inputs[0])
    links.new(y_sin.outputs[0], rotated_x.inputs[1])
    links.new(x_sin.outputs[0], rotated_y.inputs[0])
    links.new(y_cos.outputs[0], rotated_y.inputs[1])
    links.new(rotated_x.outputs[0], negative_x.inputs[0])
    links.new(rotated_y.outputs[0], negative_y.inputs[0])
    links.new(negative_x.outputs[0], spatial_offset.inputs["X"])
    links.new(negative_y.outputs[0], spatial_offset.inputs["Y"])
    links.new(inp.outputs["UV Vector"], shifted_uv.inputs[0])
    links.new(spatial_offset.outputs[0], shifted_uv.inputs[1])

    expanded_width = _math(group, "ADD", "Rim Expanded Selection", -1120, 450)
    safe_width = _math(group, "MAXIMUM", "Rim Safe Width", -930, 450, value_2=0.00001)
    soft_radius = _math(group, "ADD", "Rim Soft Radius", -740, 450)
    safe_soft_radius = _math(group, "MAXIMUM", "Rim Safe Soft Radius", -550, 450, value_2=0.00001)
    blur_low = _math(group, "MAXIMUM", "Rim Feather Clamp Low", -170, 450, value_2=0.0)
    blur_factor = _math(group, "MINIMUM", "Rim Feather Factor", 20, 450, value_2=1.0)
    inverse_blur = _math(group, "SUBTRACT", "Rim Sharp Weight", 210, 450, value_1=1.0)
    links.new(inp.outputs["Width"], expanded_width.inputs[0])
    links.new(inp.outputs["Expand / Shrink"], expanded_width.inputs[1])
    links.new(expanded_width.outputs[0], safe_width.inputs[0])
    links.new(safe_width.outputs[0], soft_radius.inputs[0])
    links.new(inp.outputs["Blur"], soft_radius.inputs[1])
    links.new(soft_radius.outputs[0], safe_soft_radius.inputs[0])
    # Blur controls the second spatial radius; Softness controls how strongly
    # that genuinely blurred radius is mixed in. This behaves like a drawing
    # effect instead of the previous coupled ratio/exponent response.
    links.new(inp.outputs["Softness"], blur_low.inputs[0])
    links.new(blur_low.outputs[0], blur_factor.inputs[0])
    links.new(blur_factor.outputs[0], inverse_blur.inputs[1])

    def build_image_kernel(radius_socket, prefix, x, y):
        diagonal = _math(group, "MULTIPLY", f"{prefix} Diagonal Radius", x, y - 30, value_2=0.70710678118)
        negative_radius = _math(group, "MULTIPLY", f"{prefix} Negative Radius", x, y - 140, value_2=-1.0)
        negative_diagonal = _math(group, "MULTIPLY", f"{prefix} Negative Diagonal", x + 190, y - 140, value_2=-1.0)
        links.new(radius_socket, diagonal.inputs[0])
        links.new(radius_socket, negative_radius.inputs[0])
        links.new(diagonal.outputs[0], negative_diagonal.inputs[0])
        specs = (
            (None, None, "Center", 4.0),
            (radius_socket, None, "Right", 2.0),
            (negative_radius.outputs[0], None, "Left", 2.0),
            (None, radius_socket, "Up", 2.0),
            (None, negative_radius.outputs[0], "Down", 2.0),
            (diagonal.outputs[0], diagonal.outputs[0], "Up Right", 1.0),
            (negative_diagonal.outputs[0], diagonal.outputs[0], "Up Left", 1.0),
            (diagonal.outputs[0], negative_diagonal.outputs[0], "Down Right", 1.0),
            (negative_diagonal.outputs[0], negative_diagonal.outputs[0], "Down Left", 1.0),
        )
        weighted_samples = []
        for index, (x_socket, y_socket, label, weight) in enumerate(specs):
            row_y = y + 250 - index * 115
            combine = _node(group, "ShaderNodeCombineXYZ", f"{prefix} {label} Offset", x + 380, row_y)
            if x_socket is not None:
                links.new(x_socket, combine.inputs["X"])
            if y_socket is not None:
                links.new(y_socket, combine.inputs["Y"])
            alpha_sample = _rim_image_sample(
                group, shifted_uv.outputs[0], combine.outputs[0],
                f"{prefix} {label}", x + 570, row_y,
            )
            if weight != 1.0:
                weighted = _math(group, "MULTIPLY", f"{prefix} {label} Weight", x + 980, row_y, value_2=weight)
                links.new(alpha_sample, weighted.inputs[0])
                weighted_samples.append(weighted.outputs[0])
            else:
                weighted_samples.append(alpha_sample)
        total = weighted_samples[0]
        for index, sample in enumerate(weighted_samples[1:], 1):
            add = _math(group, "ADD", f"{prefix} Sample Sum {index}", x + 1180 + index * 120, y)
            links.new(total, add.inputs[0])
            links.new(sample, add.inputs[1])
            total = add.outputs[0]
        average = _math(group, "MULTIPLY", f"{prefix} Gaussian Alpha", x + 2250, y, value_2=(1.0 / 16.0))
        links.new(total, average.inputs[0])
        return average.outputs[0]

    sharp_image_alpha = build_image_kernel(safe_width.outputs[0], "Rim Sharp", -120, 1150)
    soft_image_alpha = build_image_kernel(safe_soft_radius.outputs[0], "Rim Blur", -120, -100)
    sharp_image_weight = _math(group, "MULTIPLY", "Rim Sharp Image Weight", 2550, 780)
    soft_image_weight = _math(group, "MULTIPLY", "Rim Soft Image Weight", 2550, 620)
    blended_image_alpha = _math(group, "ADD", "Rim Blended Image Alpha", 2740, 700)
    links.new(sharp_image_alpha, sharp_image_weight.inputs[0])
    links.new(inverse_blur.outputs[0], sharp_image_weight.inputs[1])
    links.new(soft_image_alpha, soft_image_weight.inputs[0])
    links.new(blur_factor.outputs[0], soft_image_weight.inputs[1])
    links.new(sharp_image_weight.outputs[0], blended_image_alpha.inputs[0])
    links.new(soft_image_weight.outputs[0], blended_image_alpha.inputs[1])

    # Procedural Color/Gradient planes do not expose an image texture. Recreate
    # the same two-radius contract from the shifted UV distance to the border.
    uv_axes = _node(group, "ShaderNodeSeparateXYZ", "Rim UV Axes", 2550, 250)
    inv_x = _math(group, "SUBTRACT", "Rim Inverse X", 2740, 300, value_1=1.0)
    inv_y = _math(group, "SUBTRACT", "Rim Inverse Y", 2740, 160, value_1=1.0)
    min_x = _math(group, "MINIMUM", "Rim X Border Distance", 2930, 300)
    min_y = _math(group, "MINIMUM", "Rim Y Border Distance", 2930, 160)
    border_distance = _math(group, "MINIMUM", "Rim Border Distance", 3120, 230)
    links.new(shifted_uv.outputs[0], uv_axes.inputs[0])
    links.new(uv_axes.outputs["X"], inv_x.inputs[1])
    links.new(uv_axes.outputs["Y"], inv_y.inputs[1])
    links.new(uv_axes.outputs["X"], min_x.inputs[0])
    links.new(inv_x.outputs[0], min_x.inputs[1])
    links.new(uv_axes.outputs["Y"], min_y.inputs[0])
    links.new(inv_y.outputs[0], min_y.inputs[1])
    links.new(min_x.outputs[0], border_distance.inputs[0])
    links.new(min_y.outputs[0], border_distance.inputs[1])

    def build_procedural_alpha(radius_socket, prefix, x, y):
        normalized = _math(group, "DIVIDE", f"{prefix} Normalize", x, y)
        half_range = _math(group, "MULTIPLY", f"{prefix} Half Range", x + 190, y, value_2=0.5)
        centered = _math(group, "ADD", f"{prefix} Centered Edge", x + 380, y, value_2=0.5)
        clamp_low = _math(group, "MAXIMUM", f"{prefix} Clamp Low", x + 570, y, value_2=0.0)
        clamp_high = _math(group, "MINIMUM", f"{prefix} Alpha", x + 760, y, value_2=1.0)
        links.new(border_distance.outputs[0], normalized.inputs[0])
        links.new(radius_socket, normalized.inputs[1])
        links.new(normalized.outputs[0], half_range.inputs[0])
        links.new(half_range.outputs[0], centered.inputs[0])
        links.new(centered.outputs[0], clamp_low.inputs[0])
        links.new(clamp_low.outputs[0], clamp_high.inputs[0])
        return clamp_high.outputs[0]

    sharp_procedural = build_procedural_alpha(safe_width.outputs[0], "Rim Sharp Procedural", 3310, 310)
    soft_procedural = build_procedural_alpha(safe_soft_radius.outputs[0], "Rim Soft Procedural", 3310, 120)
    sharp_proc_weight = _math(group, "MULTIPLY", "Rim Sharp Procedural Weight", 3890, 310)
    soft_proc_weight = _math(group, "MULTIPLY", "Rim Soft Procedural Weight", 3890, 120)
    blended_procedural = _math(group, "ADD", "Rim Blended Procedural Alpha", 4080, 220)
    links.new(sharp_procedural, sharp_proc_weight.inputs[0])
    links.new(inverse_blur.outputs[0], sharp_proc_weight.inputs[1])
    links.new(soft_procedural, soft_proc_weight.inputs[0])
    links.new(blur_factor.outputs[0], soft_proc_weight.inputs[1])
    links.new(sharp_proc_weight.outputs[0], blended_procedural.inputs[0])
    links.new(soft_proc_weight.outputs[0], blended_procedural.inputs[1])

    image_weight = _math(group, "MULTIPLY", "Rim Image Source Weight", 4260, 700)
    inverse_use = _math(group, "SUBTRACT", "Rim Procedural Source Weight", 4260, 500, value_1=1.0)
    procedural_weight = _math(group, "MULTIPLY", "Rim Procedural Weighted", 4450, 500)
    sampled_alpha = _math(group, "ADD", "Rim Selected Alpha", 4640, 620)
    links.new(blended_image_alpha.outputs[0], image_weight.inputs[0])
    links.new(inp.outputs["Use Image Sample"], image_weight.inputs[1])
    links.new(inp.outputs["Use Image Sample"], inverse_use.inputs[1])
    links.new(blended_procedural.outputs[0], procedural_weight.inputs[0])
    links.new(inverse_use.outputs[0], procedural_weight.inputs[1])
    links.new(image_weight.outputs[0], sampled_alpha.inputs[0])
    links.new(procedural_weight.outputs[0], sampled_alpha.inputs[1])

    # Build both sides of the edge. Mode 0 is Inner, 1 is Outer and 2 keeps
    # both, matching the familiar Grease Pencil Rim workflow.
    inner_difference = _math(group, "SUBTRACT", "Rim Inner Difference", 4830, 700)
    inner_positive = _math(group, "MAXIMUM", "Rim Inner Positive", 5020, 700, value_2=0.0)
    inner_mask = _math(group, "MULTIPLY", "Rim Inner Mask", 5210, 700)
    outer_difference = _math(group, "SUBTRACT", "Rim Outer Difference", 4830, 500)
    outer_positive = _math(group, "MAXIMUM", "Rim Outer Positive", 5020, 500, value_2=0.0)
    inverse_alpha = _math(group, "SUBTRACT", "Rim Outside Source", 5020, 320, value_1=1.0)
    outer_mask = _math(group, "MULTIPLY", "Rim Outer Mask", 5210, 500)
    links.new(inp.outputs["Alpha In"], inner_difference.inputs[0])
    links.new(sampled_alpha.outputs[0], inner_difference.inputs[1])
    links.new(inner_difference.outputs[0], inner_positive.inputs[0])
    links.new(inner_positive.outputs[0], inner_mask.inputs[0])
    links.new(inp.outputs["Alpha In"], inner_mask.inputs[1])
    links.new(sampled_alpha.outputs[0], outer_difference.inputs[0])
    links.new(inp.outputs["Alpha In"], outer_difference.inputs[1])
    links.new(outer_difference.outputs[0], outer_positive.inputs[0])
    links.new(inp.outputs["Alpha In"], inverse_alpha.inputs[1])
    links.new(outer_positive.outputs[0], outer_mask.inputs[0])
    links.new(inverse_alpha.outputs[0], outer_mask.inputs[1])

    outer_active = _math(group, "GREATER_THAN", "Rim Outer Or Both", 5400, 380, value_2=0.5)
    both_active = _math(group, "GREATER_THAN", "Rim Both", 5400, 250, value_2=1.5)
    outer_only = _math(group, "SUBTRACT", "Rim Outer Only", 5590, 310)
    inner_active = _math(group, "SUBTRACT", "Rim Inner Active", 5780, 310, value_1=1.0)
    selected_inner = _math(group, "MULTIPLY", "Rim Selected Inner", 5590, 700)
    selected_outer = _math(group, "MULTIPLY", "Rim Selected Outer", 5590, 500)
    inner_strength = _math(group, "MULTIPLY", "Rim Inner Intensity", 5780, 700)
    outer_strength = _math(group, "MULTIPLY", "Rim Outer Intensity", 5780, 500)
    inner_clamp = _math(group, "MINIMUM", "Rim Inner Clamp", 5970, 700, value_2=1.0)
    outer_clamp = _math(group, "MINIMUM", "Rim Outer Clamp", 5970, 500, value_2=1.0)
    links.new(inp.outputs["Mode"], outer_active.inputs[0])
    links.new(inp.outputs["Mode"], both_active.inputs[0])
    links.new(outer_active.outputs[0], outer_only.inputs[0])
    links.new(both_active.outputs[0], outer_only.inputs[1])
    links.new(outer_only.outputs[0], inner_active.inputs[1])
    links.new(inner_mask.outputs[0], selected_inner.inputs[0])
    links.new(inner_active.outputs[0], selected_inner.inputs[1])
    links.new(outer_mask.outputs[0], selected_outer.inputs[0])
    links.new(outer_active.outputs[0], selected_outer.inputs[1])
    links.new(selected_inner.outputs[0], inner_strength.inputs[0])
    links.new(inp.outputs["Intensity"], inner_strength.inputs[1])
    links.new(selected_outer.outputs[0], outer_strength.inputs[0])
    links.new(inp.outputs["Intensity"], outer_strength.inputs[1])
    links.new(inner_strength.outputs[0], inner_clamp.inputs[0])
    links.new(outer_strength.outputs[0], outer_clamp.inputs[0])

    # Editable per-effect blend modes, deliberately matching Shadow and the
    # compact choices artists already know from Grease Pencil effects.
    blend_specs = (
        ("NORMAL", None), ("MULTIPLY", "MULTIPLY"), ("SCREEN", "SCREEN"),
        ("OVERLAY", "OVERLAY"), ("SOFT_LIGHT", "SOFT_LIGHT"),
        ("HARD_LIGHT", "HARD_LIGHT"), ("ADD", "ADD"),
        ("DIFFERENCE", "DIFFERENCE"),
    )
    blend_outputs = [inp.outputs["Rim Color"]]
    for index, (label, blend_type) in enumerate(blend_specs[1:], 1):
        y = 1180 - index * 120
        if blend_type == "HARD_LIGHT":
            branch = _mix_rgb(group, "OVERLAY", "Rim Hard Light", 5700, y)
            links.new(inp.outputs["Rim Color"], branch.inputs[1])
            links.new(inp.outputs["Color In"], branch.inputs[2])
        else:
            branch = _mix_rgb(group, blend_type, f"Rim {label.title().replace('_', ' ')}", 5700, y)
            links.new(inp.outputs["Color In"], branch.inputs[1])
            links.new(inp.outputs["Rim Color"], branch.inputs[2])
        blend_outputs.append(branch.outputs[0])

    selected_blend = blend_outputs[0]
    for index, branch in enumerate(blend_outputs[1:], 1):
        threshold = _math(group, "GREATER_THAN", f"Rim Blend Select {index}", 5980 + index * 95, 1180 - index * 85, value_2=index - 0.5)
        selector = _mix_rgb(group, "MIX", f"Rim Blend Result {index}", 6170 + index * 145, 1080 - index * 70)
        links.new(inp.outputs["Blend Mode"], threshold.inputs[0])
        links.new(threshold.outputs[0], selector.inputs[0])
        links.new(selected_blend, selector.inputs[1])
        links.new(branch, selector.inputs[2])
        selected_blend = selector.outputs[0]

    inner_color = _mix_rgb(group, "MIX", "Apply Inner Rim", 7350, 700)
    links.new(inner_clamp.outputs[0], inner_color.inputs[0])
    links.new(inp.outputs["Color In"], inner_color.inputs[1])
    links.new(selected_blend, inner_color.inputs[2])

    # Outer/Both modes enlarge alpha using straight-alpha source-over. This
    # avoids colored transparent texels and keeps antialiased edges stable.
    outer_effect_color = _mix_rgb(group, "MIX", "Rim Outer Edge Blend", 7160, 940)
    links.new(inp.outputs["Alpha In"], outer_effect_color.inputs[0])
    links.new(inp.outputs["Rim Color"], outer_effect_color.inputs[1])
    links.new(selected_blend, outer_effect_color.inputs[2])
    outer_contribution = _math(group, "MINIMUM", "Rim Outer Contribution", 7350, 430)
    expanded_alpha = _math(group, "ADD", "Rim Expanded Alpha", 7540, 430)
    safe_alpha = _math(group, "MAXIMUM", "Rim Safe Expanded Alpha", 7730, 430, value_2=0.000001)
    links.new(outer_clamp.outputs[0], outer_contribution.inputs[0])
    links.new(inverse_alpha.outputs[0], outer_contribution.inputs[1])
    links.new(inp.outputs["Alpha In"], expanded_alpha.inputs[0])
    links.new(outer_contribution.outputs[0], expanded_alpha.inputs[1])
    links.new(expanded_alpha.outputs[0], safe_alpha.inputs[0])

    source_premult = _mix_rgb(group, "MULTIPLY", "Rim Source Premultiplied", 7540, 820)
    outer_premult = _mix_rgb(group, "MULTIPLY", "Rim Outer Premultiplied", 7540, 660)
    premult_sum = _mix_rgb(group, "ADD", "Rim Premultiplied Sum", 7770, 750)
    straight_color = _mix_rgb(group, "DIVIDE", "Rim Straight Color", 8000, 750)
    links.new(inner_color.outputs[0], source_premult.inputs[1])
    links.new(inp.outputs["Alpha In"], source_premult.inputs[2])
    links.new(outer_effect_color.outputs[0], outer_premult.inputs[1])
    links.new(outer_contribution.outputs[0], outer_premult.inputs[2])
    links.new(source_premult.outputs[0], premult_sum.inputs[1])
    links.new(outer_premult.outputs[0], premult_sum.inputs[2])
    links.new(premult_sum.outputs[0], straight_color.inputs[1])
    links.new(safe_alpha.outputs[0], straight_color.inputs[2])
    links.new(straight_color.outputs[0], out.inputs["Color Out"])
    links.new(expanded_alpha.outputs[0], out.inputs["Alpha Out"])
    group["fbp_rim_contract_version"] = 6
    return group


def _create_shadow(name):
    """Create an alpha-aware inner/outer shadow with straight-alpha compositing.

    Outer shadows are composited as a real source-over operation instead of
    mixing hidden RGB values from transparent texels. This avoids pale fringes,
    dark seams and opacity-dependent color shifts around antialiased edges.
    """
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    _socket(group, "Color In", "INPUT", "NodeSocketColor", default=(0.5, 0.5, 0.5, 1.0))
    _socket(group, "Alpha In", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "UV Vector", "INPUT", "NodeSocketVector")
    _socket(group, "Use Image Sample", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Blend Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=7.0)
    _socket(group, "Offset X", "INPUT", "NodeSocketFloat", default=0.025, minimum=-1.0, maximum=1.0)
    _socket(group, "Offset Y", "INPUT", "NodeSocketFloat", default=-0.025, minimum=-1.0, maximum=1.0)
    _socket(group, "Blur", "INPUT", "NodeSocketFloat", default=0.02, minimum=0.0, maximum=0.5)
    _socket(group, "Opacity", "INPUT", "NodeSocketFloat", default=0.65, minimum=0.0, maximum=1.0)
    _socket(group, "Shadow Color", "INPUT", "NodeSocketColor", default=(0.0, 0.0, 0.0, 1.0))
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    # Positive Position values move the visible shadow in the same direction,
    # therefore the source alpha is sampled from the inverse UV direction.
    neg_x = _math(group, "MULTIPLY", "Shadow Negative X", -1850, 720, value_2=-1.0)
    neg_y = _math(group, "MULTIPLY", "Shadow Negative Y", -1850, 590, value_2=-1.0)
    base_offset = _node(group, "ShaderNodeCombineXYZ", "Shadow Position", -1650, 660)
    shifted_uv = _vector_math(group, "ADD", "Shadow Shifted UV", -1450, 660)
    links.new(inp.outputs["Offset X"], neg_x.inputs[0])
    links.new(inp.outputs["Offset Y"], neg_y.inputs[0])
    links.new(neg_x.outputs[0], base_offset.inputs["X"])
    links.new(neg_y.outputs[0], base_offset.inputs["Y"])
    links.new(inp.outputs["UV Vector"], shifted_uv.inputs[0])
    links.new(base_offset.outputs[0], shifted_uv.inputs[1])

    # Nine-tap Gaussian-like kernel. It is deliberately fixed-size so slider
    # edits stay cheap and animated image sequences do not allocate runtime data.
    safe_blur = _math(group, "MAXIMUM", "Shadow Safe Blur", -1450, 390, value_2=0.000001)
    diagonal = _math(group, "MULTIPLY", "Shadow Diagonal Radius", -1260, 390, value_2=0.70710678118)
    negative = _math(group, "MULTIPLY", "Shadow Negative Radius", -1260, 270, value_2=-1.0)
    negative_diagonal = _math(group, "MULTIPLY", "Shadow Negative Diagonal", -1070, 270, value_2=-1.0)
    links.new(inp.outputs["Blur"], safe_blur.inputs[0])
    links.new(safe_blur.outputs[0], diagonal.inputs[0])
    links.new(safe_blur.outputs[0], negative.inputs[0])
    links.new(diagonal.outputs[0], negative_diagonal.inputs[0])

    specs = (
        (None, None, "Center", 4.0),
        (safe_blur.outputs[0], None, "Right", 2.0),
        (negative.outputs[0], None, "Left", 2.0),
        (None, safe_blur.outputs[0], "Up", 2.0),
        (None, negative.outputs[0], "Down", 2.0),
        (diagonal.outputs[0], diagonal.outputs[0], "Up Right", 1.0),
        (negative_diagonal.outputs[0], diagonal.outputs[0], "Up Left", 1.0),
        (diagonal.outputs[0], negative_diagonal.outputs[0], "Down Right", 1.0),
        (negative_diagonal.outputs[0], negative_diagonal.outputs[0], "Down Left", 1.0),
    )
    weighted_samples = []
    for index, (x_socket, y_socket, label, weight) in enumerate(specs):
        y = 1220 - index * 135
        offset = _node(group, "ShaderNodeCombineXYZ", f"Shadow {label} Offset", -1020, y)
        if x_socket is not None:
            links.new(x_socket, offset.inputs["X"])
        if y_socket is not None:
            links.new(y_socket, offset.inputs["Y"])
        alpha = _rim_image_sample(group, shifted_uv.outputs[0], offset.outputs[0], f"Shadow {label}", -820, y)
        if weight != 1.0:
            weighted = _math(group, "MULTIPLY", f"Shadow {label} Weight", -390, y, value_2=weight)
            links.new(alpha, weighted.inputs[0])
            weighted_samples.append(weighted.outputs[0])
        else:
            weighted_samples.append(alpha)
    total = weighted_samples[0]
    for index, sample in enumerate(weighted_samples[1:], 1):
        add = _math(group, "ADD", f"Shadow Sample Sum {index}", 20 + index * 125, 850)
        links.new(total, add.inputs[0])
        links.new(sample, add.inputs[1])
        total = add.outputs[0]
    image_alpha = _math(group, "MULTIPLY", "Shadow Gaussian Alpha", 1120, 850, value_2=1.0 / 16.0)
    links.new(total, image_alpha.inputs[0])

    # Color and Gradient planes have no private image sample. Reconstruct their
    # rectangular alpha from UVs so Inner Shadow remains useful and deterministic.
    axes = _node(group, "ShaderNodeSeparateXYZ", "Shadow Procedural UV", 500, 470)
    inv_x = _math(group, "SUBTRACT", "Shadow Procedural Inverse X", 690, 540, value_1=1.0)
    inv_y = _math(group, "SUBTRACT", "Shadow Procedural Inverse Y", 690, 400, value_1=1.0)
    min_x = _math(group, "MINIMUM", "Shadow Procedural X Distance", 880, 540)
    min_y = _math(group, "MINIMUM", "Shadow Procedural Y Distance", 880, 400)
    edge = _math(group, "MINIMUM", "Shadow Procedural Edge Distance", 1070, 470)
    normalized = _math(group, "DIVIDE", "Shadow Procedural Soft Edge", 1260, 470)
    clamp_low = _math(group, "MAXIMUM", "Shadow Procedural Clamp Low", 1450, 470, value_2=0.0)
    proc_alpha = _math(group, "MINIMUM", "Shadow Procedural Alpha", 1640, 470, value_2=1.0)
    links.new(shifted_uv.outputs[0], axes.inputs[0])
    links.new(axes.outputs["X"], inv_x.inputs[1])
    links.new(axes.outputs["Y"], inv_y.inputs[1])
    links.new(axes.outputs["X"], min_x.inputs[0])
    links.new(inv_x.outputs[0], min_x.inputs[1])
    links.new(axes.outputs["Y"], min_y.inputs[0])
    links.new(inv_y.outputs[0], min_y.inputs[1])
    links.new(min_x.outputs[0], edge.inputs[0])
    links.new(min_y.outputs[0], edge.inputs[1])
    links.new(edge.outputs[0], normalized.inputs[0])
    links.new(safe_blur.outputs[0], normalized.inputs[1])
    links.new(normalized.outputs[0], clamp_low.inputs[0])
    links.new(clamp_low.outputs[0], proc_alpha.inputs[0])

    image_weight = _math(group, "MULTIPLY", "Shadow Image Weight", 1840, 790)
    inverse_use = _math(group, "SUBTRACT", "Shadow Procedural Weight", 1840, 600, value_1=1.0)
    proc_weight = _math(group, "MULTIPLY", "Shadow Procedural Weighted", 2030, 600)
    sampled = _math(group, "ADD", "Shadow Selected Alpha", 2220, 720)
    links.new(image_alpha.outputs[0], image_weight.inputs[0])
    links.new(inp.outputs["Use Image Sample"], image_weight.inputs[1])
    links.new(inp.outputs["Use Image Sample"], inverse_use.inputs[1])
    links.new(proc_alpha.outputs[0], proc_weight.inputs[0])
    links.new(inverse_use.outputs[0], proc_weight.inputs[1])
    links.new(image_weight.outputs[0], sampled.inputs[0])
    links.new(proc_weight.outputs[0], sampled.inputs[1])

    # Outer is the positive alpha expansion only. Subtracting the current alpha
    # prevents the previous A*(1-A) edge halo and keeps zero-offset shadows clean.
    outer_difference = _math(group, "SUBTRACT", "Shadow Outer Difference", 2410, 860)
    outer = _math(group, "MAXIMUM", "Shadow Outer Mask", 2600, 860, value_2=0.0)
    inv_sampled = _math(group, "SUBTRACT", "Shadow Inside Gap", 2410, 650, value_1=1.0)
    inner = _math(group, "MULTIPLY", "Shadow Inner Mask", 2600, 650)
    inv_mode = _math(group, "SUBTRACT", "Shadow Outer Mode Weight", 2600, 430, value_1=1.0)
    outer_mode = _math(group, "MULTIPLY", "Shadow Outer Selected", 2790, 850)
    inner_mode = _math(group, "MULTIPLY", "Shadow Inner Selected", 2790, 650)
    selected_mask = _math(group, "ADD", "Shadow Selected Mask", 2980, 760)
    opacity = _math(group, "MULTIPLY", "Shadow Opacity", 3170, 760)
    clamp_mask = _math(group, "MINIMUM", "Shadow Mask Clamp", 3360, 760, value_2=1.0)
    links.new(sampled.outputs[0], outer_difference.inputs[0])
    links.new(inp.outputs["Alpha In"], outer_difference.inputs[1])
    links.new(outer_difference.outputs[0], outer.inputs[0])
    links.new(sampled.outputs[0], inv_sampled.inputs[1])
    links.new(inp.outputs["Alpha In"], inner.inputs[0])
    links.new(inv_sampled.outputs[0], inner.inputs[1])
    links.new(inp.outputs["Mode"], inv_mode.inputs[1])
    links.new(outer.outputs[0], outer_mode.inputs[0])
    links.new(inv_mode.outputs[0], outer_mode.inputs[1])
    links.new(inner.outputs[0], inner_mode.inputs[0])
    links.new(inp.outputs["Mode"], inner_mode.inputs[1])
    links.new(outer_mode.outputs[0], selected_mask.inputs[0])
    links.new(inner_mode.outputs[0], selected_mask.inputs[1])
    links.new(selected_mask.outputs[0], opacity.inputs[0])
    links.new(inp.outputs["Opacity"], opacity.inputs[1])
    links.new(opacity.outputs[0], clamp_mask.inputs[0])

    # Build the editable effect blend. Blend Mode combines the shadow color with
    # this layer only; scene/background layer blending remains a separate feature.
    blend_specs = (
        ("NORMAL", None),
        ("MULTIPLY", "MULTIPLY"),
        ("SCREEN", "SCREEN"),
        ("OVERLAY", "OVERLAY"),
        ("SOFT_LIGHT", "SOFT_LIGHT"),
        ("HARD_LIGHT", "HARD_LIGHT"),
        ("ADD", "ADD"),
        ("DIFFERENCE", "DIFFERENCE"),
    )
    blend_outputs = [inp.outputs["Shadow Color"]]
    for index, (label, blend_type) in enumerate(blend_specs[1:], 1):
        y = 1150 - index * 125
        if blend_type == "HARD_LIGHT":
            node = _mix_rgb(group, "OVERLAY", "Shadow Hard Light", 2450, y)
            links.new(inp.outputs["Shadow Color"], node.inputs[1])
            links.new(inp.outputs["Color In"], node.inputs[2])
        else:
            node = _mix_rgb(group, blend_type, f"Shadow {label.title().replace('_', ' ')}", 2450, y)
            links.new(inp.outputs["Color In"], node.inputs[1])
            links.new(inp.outputs["Shadow Color"], node.inputs[2])
        blend_outputs.append(node.outputs[0])

    selected_blend = blend_outputs[0]
    for index, branch in enumerate(blend_outputs[1:], 1):
        threshold = _math(group, "GREATER_THAN", f"Shadow Blend Select {index}", 2730 + index * 95, 1180 - index * 90, value_2=index - 0.5)
        selector = _mix_rgb(group, "MIX", f"Shadow Blend Result {index}", 2920 + index * 150, 1080 - index * 75)
        links.new(inp.outputs["Blend Mode"], threshold.inputs[0])
        links.new(threshold.outputs[0], selector.inputs[0])
        links.new(selected_blend, selector.inputs[1])
        links.new(branch, selector.inputs[2])
        selected_blend = selector.outputs[0]

    # Inner shadow stays inside the original alpha and simply blends color.
    inner_color = _mix_rgb(group, "MIX", "Apply Inner Shadow", 4050, 780)
    links.new(clamp_mask.outputs[0], inner_color.inputs[0])
    links.new(inp.outputs["Color In"], inner_color.inputs[1])
    links.new(selected_blend, inner_color.inputs[2])

    # Outer shadow is a straight-alpha source-over composite. The shadow color
    # remains stable as opacity falls instead of being mixed toward hidden RGB.
    outer_effect_color = _mix_rgb(group, "MIX", "Outer Shadow Edge Blend", 3860, 1040)
    links.new(inp.outputs["Alpha In"], outer_effect_color.inputs[0])
    links.new(inp.outputs["Shadow Color"], outer_effect_color.inputs[1])
    links.new(selected_blend, outer_effect_color.inputs[2])

    inverse_alpha = _math(group, "SUBTRACT", "Shadow Remaining Transparency", 3550, 560, value_1=1.0)
    shadow_contribution = _math(group, "MULTIPLY", "Shadow Outer Contribution", 3740, 560)
    outer_alpha = _math(group, "ADD", "Shadow Outer Alpha", 3930, 560)
    safe_outer_alpha = _math(group, "MAXIMUM", "Shadow Safe Outer Alpha", 4120, 560, value_2=0.000001)
    links.new(inp.outputs["Alpha In"], inverse_alpha.inputs[1])
    links.new(clamp_mask.outputs[0], shadow_contribution.inputs[0])
    links.new(inverse_alpha.outputs[0], shadow_contribution.inputs[1])
    links.new(inp.outputs["Alpha In"], outer_alpha.inputs[0])
    links.new(shadow_contribution.outputs[0], outer_alpha.inputs[1])
    links.new(outer_alpha.outputs[0], safe_outer_alpha.inputs[0])

    source_premult = _mix_rgb(group, "MULTIPLY", "Shadow Source Premultiplied", 4240, 1010)
    shadow_premult = _mix_rgb(group, "MULTIPLY", "Shadow Color Premultiplied", 4240, 850)
    premult_sum = _mix_rgb(group, "ADD", "Shadow Premultiplied Sum", 4470, 930)
    straight_outer = _mix_rgb(group, "DIVIDE", "Shadow Straight Color", 4700, 930)
    links.new(inp.outputs["Color In"], source_premult.inputs[1])
    links.new(inp.outputs["Alpha In"], source_premult.inputs[2])
    links.new(outer_effect_color.outputs[0], shadow_premult.inputs[1])
    links.new(shadow_contribution.outputs[0], shadow_premult.inputs[2])
    links.new(source_premult.outputs[0], premult_sum.inputs[1])
    links.new(shadow_premult.outputs[0], premult_sum.inputs[2])
    links.new(premult_sum.outputs[0], straight_outer.inputs[1])
    links.new(safe_outer_alpha.outputs[0], straight_outer.inputs[2])

    final_color = _mix_rgb(group, "MIX", "Shadow Inner Outer Color", 4950, 850)
    links.new(inp.outputs["Mode"], final_color.inputs[0])
    links.new(straight_outer.outputs[0], final_color.inputs[1])
    links.new(inner_color.outputs[0], final_color.inputs[2])
    links.new(final_color.outputs[0], out.inputs["Color Out"])

    inner_alpha = _math(group, "MULTIPLY", "Shadow Inner Alpha Selected", 4310, 430)
    outer_alpha_selected = _math(group, "MULTIPLY", "Shadow Outer Alpha Selected", 4310, 300)
    alpha_out = _math(group, "ADD", "Shadow Final Alpha", 4500, 360)
    alpha_clamp = _math(group, "MINIMUM", "Shadow Final Alpha Clamp", 4690, 360, value_2=1.0)
    links.new(inp.outputs["Alpha In"], inner_alpha.inputs[0])
    links.new(inp.outputs["Mode"], inner_alpha.inputs[1])
    links.new(outer_alpha.outputs[0], outer_alpha_selected.inputs[0])
    links.new(inv_mode.outputs[0], outer_alpha_selected.inputs[1])
    links.new(inner_alpha.outputs[0], alpha_out.inputs[0])
    links.new(outer_alpha_selected.outputs[0], alpha_out.inputs[1])
    links.new(alpha_out.outputs[0], alpha_clamp.inputs[0])
    links.new(alpha_clamp.outputs[0], out.inputs["Alpha Out"])

    group["fbp_shadow_contract_version"] = 2
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


def _cell_distance(group, inp, scale_socket, x=-720, y=-180, rotation_socket=None, aspect_socket="Aspect Ratio", center_x_socket=None, center_y_socket=None):
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
    if center_x_socket and center_x_socket in inp.outputs:
        links.new(inp.outputs[center_x_socket], x_center.inputs[1])
    if center_y_socket and center_y_socket in inp.outputs:
        links.new(inp.outputs[center_y_socket], y_center.inputs[1])
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
    _socket(group, "Pattern", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Color Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=3.0)
    _socket(group, "Dot Size", "INPUT", "NodeSocketFloat", default=0.9, minimum=0.0, maximum=1.5)
    _socket(group, "Dot Scale", "INPUT", "NodeSocketFloat", default=0.82, minimum=0.0, maximum=3.0)
    _socket(group, "Blend", "INPUT", "NodeSocketFloat", default=0.65, minimum=0.0, maximum=1.0)
    _socket(group, "Softness", "INPUT", "NodeSocketFloat", default=0.44, minimum=0.0, maximum=1.0)
    _socket(group, "Rotation", "INPUT", "NodeSocketFloat", default=0.0, minimum=-6.283, maximum=6.283)
    _socket(group, "Contrast", "INPUT", "NodeSocketFloat", default=1.4, minimum=0.0, maximum=8.0)
    _socket(group, "Invert", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Shape", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=3.0)
    _socket(group, "Use Source Color", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Foreground", "INPUT", "NodeSocketColor", default=(0.0, 0.0, 0.0, 1.0))
    _socket(group, "Background", "INPUT", "NodeSocketColor", default=(1.0, 1.0, 1.0, 1.0))
    _socket(group, "Transparent Background", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Center X", "INPUT", "NodeSocketFloat", default=0.5, minimum=-10.0, maximum=10.0)
    _socket(group, "Center Y", "INPUT", "NodeSocketFloat", default=0.5, minimum=-10.0, maximum=10.0)
    _socket(group, "Clip to Alpha", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Debug Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Color Out", "OUTPUT", "NodeSocketColor")
    _socket(group, "Alpha Out", "OUTPUT", "NodeSocketFloat")
    inp, out = _group_io(group)
    links = group.links

    luminance = _luminance_controls(group, inp, -1150, 480)
    _circle, _scaled, centered = _cell_distance(
        group, inp, "Cell Scale", x=-1120, y=-300, rotation_socket="Rotation",
        center_x_socket="Center X", center_y_socket="Center Y",
    )
    distance = _shape_distance(group, centered, inp.outputs["Shape"], x=140, y=-260, prefix="Halftone")
    inverse_luma = _math(group, "SUBTRACT", "Ink Amount", 200, 430, value_1=1.0)
    scaled_luma = _math(group, "MULTIPLY", "Halftone Dot Growth", 380, 430)
    diameter = _math(group, "MULTIPLY", "Halftone Diameter", 560, 430)
    radius = _math(group, "MULTIPLY", "Halftone Radius", 740, 430, value_2=0.5)
    soft_base = _math(group, "MULTIPLY", "Halftone Softness Amount", 560, 260, value_2=0.12)
    blended_weight = _math(group, "MULTIPLY", "Halftone Blend Weight", 650, 310)
    blended_soft = _math(group, "MULTIPLY", "Halftone Blended Softness", 740, 260)
    dot_soft_weight = _math(group, "SUBTRACT", "Halftone Dot Pattern Weight", 740, 120, value_1=1.0)
    dot_soft = _math(group, "MULTIPLY", "Halftone Dot Softness", 920, 120, value_2=0.018)
    soft_edge_mix = _math(group, "ADD", "Halftone Softness Mix", 1060, 260)
    edge = _math(group, "ADD", "Halftone Soft Edge", 1240, 350)
    mask = _node(group, "ShaderNodeMapRange", "Halftone Mask", 760, 120)
    mask.interpolation_type = "SMOOTHERSTEP"
    mask.clamp = True
    mask.inputs["To Min"].default_value = 1.0
    mask.inputs["To Max"].default_value = 0.0
    color_source_mode = _math(group, "LESS_THAN", "Halftone Source Color Mode", 1000, 620, value_2=1.5)
    bw_dark_mode = _math(group, "GREATER_THAN", "Halftone BW Dark Mode", 1000, 480, value_2=2.5)
    bw_ink = _mix_rgb(group, "MIX", "Halftone BW Ink", 1190, 560)
    bw_paper = _mix_rgb(group, "MIX", "Halftone BW Paper", 1190, 400)
    ink = _mix_rgb(group, "MIX", "Halftone Ink Color", 1390, 560)
    paper = _mix_rgb(group, "MIX", "Halftone Paper Color", 1390, 400)
    result = _mix_rgb(group, "MIX", "Halftone Output", 1620, 350)
    alpha_mask = _math(group, "MULTIPLY", "Halftone Ink Alpha", 1620, 60)
    clip_alpha_part = _math(group, "MULTIPLY", "Halftone Clipped Alpha", 1620, -120)
    no_clip_weight = _math(group, "SUBTRACT", "Halftone No Clip Weight", 1620, -220, value_1=1.0)
    effective_alpha = _math(group, "ADD", "Halftone Effective Alpha", 1800, -140)
    opaque_weight = _math(group, "SUBTRACT", "Halftone Opaque Background", 1620, -260, value_1=1.0)
    bg_alpha = _math(group, "MULTIPLY", "Halftone Background Alpha", 1800, -260)
    fg_alpha = _math(group, "MULTIPLY", "Halftone Transparent Alpha", 1800, 60)
    final_alpha = _math(group, "ADD", "Halftone Alpha", 1980, 0)

    links.new(luminance, inverse_luma.inputs[1])
    links.new(inverse_luma.outputs[0], scaled_luma.inputs[0])
    links.new(inp.outputs["Dot Scale"], scaled_luma.inputs[1])
    links.new(scaled_luma.outputs[0], diameter.inputs[0])
    links.new(inp.outputs["Dot Size"], diameter.inputs[1])
    links.new(diameter.outputs[0], radius.inputs[0])
    links.new(inp.outputs["Softness"], soft_base.inputs[0])
    links.new(inp.outputs["Pattern"], blended_weight.inputs[0])
    links.new(inp.outputs["Blend"], blended_weight.inputs[1])
    links.new(soft_base.outputs[0], blended_soft.inputs[0])
    links.new(blended_weight.outputs[0], blended_soft.inputs[1])
    links.new(inp.outputs["Pattern"], dot_soft_weight.inputs[1])
    links.new(dot_soft_weight.outputs[0], dot_soft.inputs[0])
    links.new(blended_soft.outputs[0], soft_edge_mix.inputs[0])
    links.new(dot_soft.outputs[0], soft_edge_mix.inputs[1])
    links.new(radius.outputs[0], edge.inputs[0])
    links.new(soft_edge_mix.outputs[0], edge.inputs[1])
    links.new(distance, mask.inputs["Value"])
    links.new(radius.outputs[0], mask.inputs["From Min"])
    links.new(edge.outputs[0], mask.inputs["From Max"])
    bw_ink.inputs[1].default_value = (0.0, 0.0, 0.0, 1.0)
    bw_ink.inputs[2].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(bw_dark_mode.outputs[0], bw_ink.inputs[0])
    bw_paper.inputs[1].default_value = (1.0, 1.0, 1.0, 1.0)
    bw_paper.inputs[2].default_value = (0.0, 0.0, 0.0, 1.0)
    links.new(bw_dark_mode.outputs[0], bw_paper.inputs[0])
    links.new(color_source_mode.outputs[0], ink.inputs[0])
    links.new(bw_ink.outputs[0], ink.inputs[1])
    links.new(inp.outputs["Color In"], ink.inputs[2])
    links.new(color_source_mode.outputs[0], paper.inputs[0])
    links.new(bw_paper.outputs[0], paper.inputs[1])
    links.new(inp.outputs["Background"], paper.inputs[2])
    links.new(mask.outputs["Result"], result.inputs[0])
    links.new(paper.outputs[0], result.inputs[1])
    links.new(ink.outputs[0], result.inputs[2])
    debug_color = _debug_color(group, result.outputs[0], luminance, mask.outputs["Result"], inp.outputs["Debug Mode"], x=1450, y=420, prefix="Halftone")
    links.new(debug_color, out.inputs["Color Out"])

    links.new(mask.outputs["Result"], alpha_mask.inputs[0])
    links.new(inp.outputs["Alpha In"], alpha_mask.inputs[1])
    links.new(inp.outputs["Alpha In"], clip_alpha_part.inputs[0])
    links.new(inp.outputs["Clip to Alpha"], clip_alpha_part.inputs[1])
    links.new(inp.outputs["Clip to Alpha"], no_clip_weight.inputs[1])
    links.new(clip_alpha_part.outputs[0], effective_alpha.inputs[0])
    links.new(no_clip_weight.outputs[0], effective_alpha.inputs[1])
    links.new(inp.outputs["Transparent Background"], opaque_weight.inputs[1])
    links.new(effective_alpha.outputs[0], bg_alpha.inputs[0])
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
            # Do not free image buffers here; Blender 5.2 can still have cache
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
    _socket(group, "Gamma", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.05, maximum=5.0)
    _socket(group, "Glyph Scale", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.25, maximum=2.5)
    _socket(group, "Glyph Width", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.25, maximum=2.5)
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
    tone_luminance = _math(group, "POWER", "Textellation Gamma", 1180, 650)
    links.new(base_luminance, tone_luminance.inputs[0])
    links.new(inp.outputs["Gamma"], tone_luminance.inputs[1])

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
    links.new(tone_luminance.outputs[0], source_density.inputs[1])
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
    local_x_center = _math(group, "SUBTRACT", "Textellation Glyph X Center", 4660, -220, value_2=0.5)
    local_x_width = _math(group, "DIVIDE", "Textellation Glyph Width", 4840, -220)
    local_x_scale = _math(group, "DIVIDE", "Textellation Glyph X Scale", 5020, -220)
    local_x_final = _math(group, "ADD", "Textellation Glyph X", 5200, -220, value_2=0.5)
    local_y_center = _math(group, "SUBTRACT", "Textellation Glyph Y Center", 4660, -380, value_2=0.5)
    local_y_scale = _math(group, "DIVIDE", "Textellation Glyph Y Scale", 4840, -380)
    local_y_final = _math(group, "ADD", "Textellation Glyph Y", 5020, -380, value_2=0.5)
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
    links.new(local_sep.outputs["X"], local_x_center.inputs[0])
    links.new(local_x_center.outputs[0], local_x_width.inputs[0])
    links.new(inp.outputs["Glyph Width"], local_x_width.inputs[1])
    links.new(local_x_width.outputs[0], local_x_scale.inputs[0])
    links.new(inp.outputs["Glyph Scale"], local_x_scale.inputs[1])
    links.new(local_x_scale.outputs[0], local_x_final.inputs[0])
    links.new(local_sep.outputs["Y"], local_y_center.inputs[0])
    links.new(local_y_center.outputs[0], local_y_scale.inputs[0])
    links.new(inp.outputs["Glyph Scale"], local_y_scale.inputs[1])
    links.new(local_y_scale.outputs[0], local_y_final.inputs[0])
    links.new(index_round.outputs[0], atlas_x_add.inputs[0])
    links.new(local_x_final.outputs[0], atlas_x_add.inputs[1])
    links.new(atlas_x_add.outputs[0], atlas_x.inputs[0])
    links.new(inp.outputs["Charset Row"], row_flip.inputs[1])
    links.new(row_flip.outputs[0], atlas_y_add.inputs[0])
    links.new(local_y_final.outputs[0], atlas_y_add.inputs[1])
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
        tone_luminance.outputs[0],
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
    store_uv = _node(group, "GeometryNodeStoreNamedAttribute", "Store Text Matrix UV", 1950, 470)
    store_uv.data_type = "FLOAT_VECTOR"
    store_uv.domain = "POINT"
    store_uv.inputs["Name"].default_value = "fbp_text_matrix_uv"

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
    links.new(store_color.outputs["Geometry"], store_uv.inputs["Geometry"])
    links.new(center_uv.outputs[0], store_uv.inputs["Value"])

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
        links.new(store_uv.outputs["Geometry"], instance.inputs["Points"])
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
    group["fbp_text_matrix_uv_version"] = 3
    group["fbp_text_matrix_rows_version"] = 1
    return group


def _instanced_effect_density(group, inp, *, prefix, x, y):
    """Select render or reduced viewport density without rebuilding geometry."""
    links = group.links
    viewport_density = _math(group, "MULTIPLY", f"{prefix} Viewport Density", x, y)
    is_viewport = _node(group, "GeometryNodeIsViewport", f"{prefix} Is Viewport", x, y - 180)
    density_switch = _node(group, "GeometryNodeSwitch", f"{prefix} Density", x + 220, y)
    density_switch.input_type = "FLOAT"
    links.new(inp.outputs["Render Density"], viewport_density.inputs[0])
    links.new(inp.outputs["Viewport %"], viewport_density.inputs[1])
    links.new(is_viewport.outputs["Is Viewport"], density_switch.inputs["Switch"])
    links.new(inp.outputs["Render Density"], density_switch.inputs["False"])
    links.new(viewport_density.outputs[0], density_switch.inputs["True"])
    return density_switch.outputs["Output"]


def _instanced_effect_variation(
    group,
    seed_socket,
    variation_socket,
    tilt_socket,
    *,
    prefix,
    x,
    y,
):
    """Return stable local rotation and uniform scale fields for instances."""
    links = group.links
    negative_tilt = _math(group, "MULTIPLY", f"{prefix} Negative Tilt", x, y + 250, value_2=-1.0)
    rotation_min = _node(group, "ShaderNodeCombineXYZ", f"{prefix} Rotation Min", x + 190, y + 260)
    rotation_max = _node(group, "ShaderNodeCombineXYZ", f"{prefix} Rotation Max", x + 190, y + 100)
    rotation_min.inputs["Z"].default_value = -3.141592654
    rotation_max.inputs["Z"].default_value = 3.141592654
    links.new(tilt_socket, negative_tilt.inputs[0])
    links.new(negative_tilt.outputs[0], rotation_min.inputs["X"])
    links.new(negative_tilt.outputs[0], rotation_min.inputs["Y"])
    links.new(tilt_socket, rotation_max.inputs["X"])
    links.new(tilt_socket, rotation_max.inputs["Y"])

    random_rotation = _node(group, "FunctionNodeRandomValue", f"{prefix} Random Rotation", x + 410, y + 180)
    random_rotation.data_type = "FLOAT_VECTOR"
    links.new(rotation_min.outputs[0], _input(random_rotation, "Min", 0))
    links.new(rotation_max.outputs[0], _input(random_rotation, "Max", 1))
    links.new(seed_socket, _input(random_rotation, "Seed", 8))
    euler_rotation = _node(group, "FunctionNodeEulerToRotation", f"{prefix} Euler Rotation", x + 620, y + 180)
    links.new(_output(random_rotation, "Value", 0), euler_rotation.inputs["Euler"])

    scale_min = _math(group, "SUBTRACT", f"{prefix} Scale Min", x + 190, y - 80, value_1=1.0)
    scale_max = _math(group, "ADD", f"{prefix} Scale Max", x + 190, y - 220, value_1=1.0)
    links.new(variation_socket, scale_min.inputs[1])
    links.new(variation_socket, scale_max.inputs[1])
    random_scale = _node(group, "FunctionNodeRandomValue", f"{prefix} Random Scale", x + 410, y - 130)
    random_scale.data_type = "FLOAT"
    links.new(scale_min.outputs[0], _input(random_scale, "Min", 2))
    links.new(scale_max.outputs[0], _input(random_scale, "Max", 3))
    links.new(seed_socket, _input(random_scale, "Seed", 8))
    uniform_scale = _node(group, "ShaderNodeCombineXYZ", f"{prefix} Uniform Scale", x + 620, y - 130)
    for axis in ("X", "Y", "Z"):
        # Blender 5.2 exposes the active Random Value output by name. Resolve
        # that socket directly so the generated group follows the current API.
        links.new(_output(random_scale, "Value", 0), uniform_scale.inputs[axis])
    return euler_rotation.outputs["Rotation"], uniform_scale.outputs[0]


def _create_fiber_tufts(name):
    """Alpha-aware bent fibers using one shared, unrealized mesh instance."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Render Density", "INPUT", "NodeSocketFloat", default=12000.0, minimum=0.0, maximum=3000000.0)
    _socket(group, "Viewport %", "INPUT", "NodeSocketFloat", default=0.05, minimum=0.0, maximum=1.0)
    _socket(group, "Length", "INPUT", "NodeSocketFloat", default=0.035, minimum=0.0, maximum=10.0)
    _socket(group, "Luminance Length", "INPUT", "NodeSocketFloat", default=0.5, minimum=-1.0, maximum=1.0)
    _socket(group, "Radius", "INPUT", "NodeSocketFloat", default=0.0007, minimum=0.00001, maximum=1.0)
    _socket(group, "Segments", "INPUT", "NodeSocketInt", default=4, minimum=2, maximum=32)
    _socket(group, "Bend", "INPUT", "NodeSocketFloat", default=0.008, minimum=-1.0, maximum=1.0)
    _socket(group, "Randomness", "INPUT", "NodeSocketFloat", default=0.35, minimum=0.0, maximum=1.0)
    _socket(group, "Seed", "INPUT", "NodeSocketInt", default=0, minimum=0, maximum=2147483647)
    _socket(group, "Alpha Threshold", "INPUT", "NodeSocketFloat", default=0.05, minimum=0.0, maximum=1.0)
    _socket(group, "Alpha Resolution", "INPUT", "NodeSocketInt", default=2, minimum=0, maximum=6)
    _socket(group, "Fiber Material", "INPUT", "NodeSocketMaterial")
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    masked_geometry, image_texture = _alpha_geometry_mask(
        group, inp, prefix="Fiber Source", x=-1980, y=620
    )
    density = _instanced_effect_density(group, inp, prefix="Fiber", x=-1580, y=620)
    distribute = _node(group, "GeometryNodeDistributePointsOnFaces", "Distribute Fiber Tufts", -1120, 500)
    distribute.distribute_method = "RANDOM"
    links.new(masked_geometry, distribute.inputs["Mesh"])
    links.new(density, distribute.inputs["Density"])
    links.new(inp.outputs["Seed"], distribute.inputs["Seed"])
    store_color = _node(group, "GeometryNodeStoreNamedAttribute", "Store Fiber Source Color", -880, 500)
    store_color.data_type = "FLOAT_COLOR"
    store_color.domain = "POINT"
    store_color.inputs["Name"].default_value = "fbp_fiber_color"
    links.new(distribute.outputs["Points"], store_color.inputs["Geometry"])
    links.new(image_texture.outputs["Color"], store_color.inputs["Value"])
    source_uv = _node(group, "GeometryNodeInputNamedAttribute", "Fiber Source UV", -880, 300)
    source_uv.data_type = "FLOAT_VECTOR"
    source_uv.inputs["Name"].default_value = "UVMap"
    store_uv = _node(group, "GeometryNodeStoreNamedAttribute", "Store Fiber Source UV", -650, 500)
    store_uv.data_type = "FLOAT_VECTOR"
    store_uv.domain = "POINT"
    store_uv.inputs["Name"].default_value = "fbp_fiber_uv"
    links.new(store_color.outputs["Geometry"], store_uv.inputs["Geometry"])
    links.new(source_uv.outputs["Attribute"], store_uv.inputs["Value"])

    end = _node(group, "ShaderNodeCombineXYZ", "Fiber End", -1360, 80)
    links.new(inp.outputs["Length"], end.inputs["Z"])
    line = _node(group, "GeometryNodeCurvePrimitiveLine", "Fiber Line", -1120, 120)
    try:
        line.mode = "POINTS"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(end.outputs[0], line.inputs["End"])
    resample = _node(group, "GeometryNodeResampleCurve", "Fiber Segments", -880, 120)
    links.new(line.outputs["Curve"], resample.inputs["Curve"])
    links.new(inp.outputs["Segments"], resample.inputs["Count"])

    spline = _node(group, "GeometryNodeSplineParameter", "Fiber Parameter", -880, -160)
    inverse = _math(group, "SUBTRACT", "Fiber Inverse Parameter", -650, -220, value_1=1.0)
    bow = _math(group, "MULTIPLY", "Fiber Bow", -430, -150)
    bow_peak = _math(group, "MULTIPLY", "Fiber Bow Peak", -210, -150, value_2=4.0)
    bow_amount = _math(group, "MULTIPLY", "Fiber Bend Amount", 10, -150)
    offset = _node(group, "ShaderNodeCombineXYZ", "Fiber Bend Offset", 230, -150)
    set_position = _node(group, "GeometryNodeSetPosition", "Bend Fiber", 450, 120)
    links.new(spline.outputs["Factor"], inverse.inputs[1])
    links.new(spline.outputs["Factor"], bow.inputs[0])
    links.new(inverse.outputs[0], bow.inputs[1])
    links.new(bow.outputs[0], bow_peak.inputs[0])
    links.new(bow_peak.outputs[0], bow_amount.inputs[0])
    links.new(inp.outputs["Bend"], bow_amount.inputs[1])
    links.new(bow_amount.outputs[0], offset.inputs["X"])
    links.new(resample.outputs["Curve"], set_position.inputs["Geometry"])
    links.new(offset.outputs[0], set_position.inputs["Offset"])

    profile = _node(group, "GeometryNodeCurvePrimitiveCircle", "Fiber Profile", 210, -430)
    profile.inputs["Resolution"].default_value = 4
    links.new(inp.outputs["Radius"], profile.inputs["Radius"])
    curve_mesh = _node(group, "GeometryNodeCurveToMesh", "Fiber Mesh", 690, 120)
    links.new(set_position.outputs["Geometry"], curve_mesh.inputs["Curve"])
    links.new(profile.outputs["Curve"], curve_mesh.inputs["Profile Curve"])
    material = _node(group, "GeometryNodeSetMaterial", "Fiber Material", 910, 120)
    links.new(curve_mesh.outputs["Mesh"], material.inputs["Geometry"])
    links.new(inp.outputs["Fiber Material"], material.inputs["Material"])

    tilt = _math(group, "MULTIPLY", "Fiber Random Tilt", -880, -510, value_2=0.85)
    links.new(inp.outputs["Randomness"], tilt.inputs[0])
    rotation, scale = _instanced_effect_variation(
        group, inp.outputs["Seed"], inp.outputs["Randomness"], tilt.outputs[0],
        prefix="Fiber", x=-650, y=-590,
    )
    fiber_luminance = _vector_math(group, "DOT_PRODUCT", "Fiber Source Luminance", 690, -520)
    fiber_luminance.inputs[1].default_value = (0.2126, 0.7152, 0.0722)
    centered_luminance = _math(group, "SUBTRACT", "Centered Fiber Luminance", 900, -520, value_2=0.5)
    signed_luminance = _math(group, "MULTIPLY", "Signed Fiber Luminance", 1110, -520, value_2=2.0)
    luminance_response = _math(group, "MULTIPLY", "Fiber Luminance Response", 1320, -520)
    length_scale = _math(group, "ADD", "Fiber Length Scale", 1530, -520, value_2=1.0)
    safe_length_scale = _math(group, "MAXIMUM", "Safe Fiber Length Scale", 1740, -520, value_2=0.05)
    length_vector = _node(group, "ShaderNodeCombineXYZ", "Fiber Length Vector", 1950, -520)
    length_vector.inputs["X"].default_value = 1.0
    length_vector.inputs["Y"].default_value = 1.0
    final_scale = _vector_math(group, "MULTIPLY", "Fiber Image Driven Scale", 2160, -430)
    links.new(image_texture.outputs["Color"], fiber_luminance.inputs[0])
    links.new(fiber_luminance.outputs["Value"], centered_luminance.inputs[0])
    links.new(centered_luminance.outputs[0], signed_luminance.inputs[0])
    links.new(signed_luminance.outputs[0], luminance_response.inputs[0])
    links.new(inp.outputs["Luminance Length"], luminance_response.inputs[1])
    links.new(luminance_response.outputs[0], length_scale.inputs[0])
    links.new(length_scale.outputs[0], safe_length_scale.inputs[0])
    links.new(safe_length_scale.outputs[0], length_vector.inputs["Z"])
    links.new(scale, final_scale.inputs[0])
    links.new(length_vector.outputs[0], final_scale.inputs[1])
    instance = _node(group, "GeometryNodeInstanceOnPoints", "Instance Fiber Tufts", 1140, 420)
    links.new(store_uv.outputs["Geometry"], instance.inputs["Points"])
    links.new(material.outputs["Geometry"], instance.inputs["Instance"])
    links.new(distribute.outputs["Rotation"], instance.inputs["Rotation"])
    links.new(final_scale.outputs[0], instance.inputs["Scale"])
    rotate = _node(group, "GeometryNodeRotateInstances", "Vary Fiber Tufts", 1370, 420)
    rotate.inputs["Local Space"].default_value = True
    links.new(instance.outputs["Instances"], rotate.inputs["Instances"])
    links.new(rotation, rotate.inputs["Rotation"])

    join = _node(group, "GeometryNodeJoinGeometry", "Join Plane and Fiber Tufts", 1610, 420)
    join["fbp_preserve_unmasked_geometry"] = True
    links.new(inp.outputs["Geometry"], join.inputs["Geometry"])
    links.new(rotate.outputs["Instances"], join.inputs["Geometry"])
    links.new(join.outputs["Geometry"], out.inputs["Geometry"])
    group["fbp_instancing_contract_version"] = 4
    group["fbp_alpha_geometry_contract_version"] = 2
    return group


def _create_paper_shards(name):
    """Alpha-aware paper chips using one shared, unrealized cube instance."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Render Density", "INPUT", "NodeSocketFloat", default=1800.0, minimum=0.0, maximum=1000000.0)
    _socket(group, "Viewport %", "INPUT", "NodeSocketFloat", default=0.15, minimum=0.0, maximum=1.0)
    _socket(group, "Shard Size", "INPUT", "NodeSocketFloat", default=0.025, minimum=0.0001, maximum=10.0)
    _socket(group, "Aspect", "INPUT", "NodeSocketFloat", default=1.8, minimum=0.05, maximum=100.0)
    _socket(group, "Thickness", "INPUT", "NodeSocketFloat", default=0.001, minimum=0.00001, maximum=2.0)
    _socket(group, "Lift", "INPUT", "NodeSocketFloat", default=0.002, minimum=-1.0, maximum=10.0)
    _socket(group, "Luminance Lift", "INPUT", "NodeSocketFloat", default=0.01, minimum=-10.0, maximum=10.0)
    _socket(group, "Tilt", "INPUT", "NodeSocketFloat", default=0.35, minimum=0.0, maximum=3.141592654)
    _socket(group, "Scale Randomness", "INPUT", "NodeSocketFloat", default=0.4, minimum=0.0, maximum=0.95)
    _socket(group, "Seed", "INPUT", "NodeSocketInt", default=0, minimum=0, maximum=2147483647)
    _socket(group, "Alpha Threshold", "INPUT", "NodeSocketFloat", default=0.05, minimum=0.0, maximum=1.0)
    _socket(group, "Alpha Resolution", "INPUT", "NodeSocketInt", default=2, minimum=0, maximum=6)
    _socket(group, "Shard Material", "INPUT", "NodeSocketMaterial")
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    masked_geometry, image_texture = _alpha_geometry_mask(
        group, inp, prefix="Shard Source", x=-1920, y=620
    )
    density = _instanced_effect_density(group, inp, prefix="Shards", x=-1500, y=600)
    distribute = _node(group, "GeometryNodeDistributePointsOnFaces", "Distribute Paper Shards", -1040, 500)
    distribute.distribute_method = "RANDOM"
    links.new(masked_geometry, distribute.inputs["Mesh"])
    links.new(density, distribute.inputs["Density"])
    links.new(inp.outputs["Seed"], distribute.inputs["Seed"])
    store_color = _node(group, "GeometryNodeStoreNamedAttribute", "Store Shard Source Color", -800, 500)
    store_color.data_type = "FLOAT_COLOR"
    store_color.domain = "POINT"
    store_color.inputs["Name"].default_value = "fbp_shard_color"
    links.new(distribute.outputs["Points"], store_color.inputs["Geometry"])
    links.new(image_texture.outputs["Color"], store_color.inputs["Value"])
    source_uv = _node(group, "GeometryNodeInputNamedAttribute", "Shard Source UV", -800, 300)
    source_uv.data_type = "FLOAT_VECTOR"
    source_uv.inputs["Name"].default_value = "UVMap"
    store_uv = _node(group, "GeometryNodeStoreNamedAttribute", "Store Shard Source UV", -580, 500)
    store_uv.data_type = "FLOAT_VECTOR"
    store_uv.domain = "POINT"
    store_uv.inputs["Name"].default_value = "fbp_shard_uv"
    links.new(store_color.outputs["Geometry"], store_uv.inputs["Geometry"])
    links.new(source_uv.outputs["Attribute"], store_uv.inputs["Value"])

    shard_length = _math(group, "MULTIPLY", "Shard Length", -1260, 80)
    links.new(inp.outputs["Shard Size"], shard_length.inputs[0])
    links.new(inp.outputs["Aspect"], shard_length.inputs[1])
    size = _node(group, "ShaderNodeCombineXYZ", "Paper Shard Size", -1020, 80)
    links.new(inp.outputs["Shard Size"], size.inputs["X"])
    links.new(shard_length.outputs[0], size.inputs["Y"])
    links.new(inp.outputs["Thickness"], size.inputs["Z"])
    cube = _node(group, "GeometryNodeMeshCube", "Paper Shard", -780, 80)
    links.new(size.outputs[0], cube.inputs["Size"])

    half_thickness = _math(group, "MULTIPLY", "Half Shard Thickness", -1020, -180, value_2=0.5)
    shard_offset = _math(group, "ADD", "Shard Surface Offset", -780, -180)
    translation = _node(group, "ShaderNodeCombineXYZ", "Shard Lift", -560, -180)
    transform = _node(group, "GeometryNodeTransform", "Lift Paper Shard", -540, 80)
    links.new(inp.outputs["Thickness"], half_thickness.inputs[0])
    links.new(half_thickness.outputs[0], shard_offset.inputs[0])
    links.new(inp.outputs["Lift"], shard_offset.inputs[1])
    links.new(shard_offset.outputs[0], translation.inputs["Z"])
    links.new(cube.outputs["Mesh"], transform.inputs["Geometry"])
    links.new(translation.outputs[0], transform.inputs["Translation"])
    material = _node(group, "GeometryNodeSetMaterial", "Shard Material", -300, 80)
    links.new(transform.outputs["Geometry"], material.inputs["Geometry"])
    links.new(inp.outputs["Shard Material"], material.inputs["Material"])

    rotation, scale = _instanced_effect_variation(
        group, inp.outputs["Seed"], inp.outputs["Scale Randomness"], inp.outputs["Tilt"],
        prefix="Shards", x=-620, y=-520,
    )
    instance = _node(group, "GeometryNodeInstanceOnPoints", "Instance Paper Shards", 260, 430)
    links.new(store_uv.outputs["Geometry"], instance.inputs["Points"])
    links.new(material.outputs["Geometry"], instance.inputs["Instance"])
    links.new(distribute.outputs["Rotation"], instance.inputs["Rotation"])
    links.new(scale, instance.inputs["Scale"])
    rotate = _node(group, "GeometryNodeRotateInstances", "Vary Paper Shards", 500, 430)
    rotate.inputs["Local Space"].default_value = True
    links.new(instance.outputs["Instances"], rotate.inputs["Instances"])
    links.new(rotation, rotate.inputs["Rotation"])

    shard_luminance = _vector_math(group, "DOT_PRODUCT", "Shard Source Luminance", -80, -360)
    shard_luminance.inputs[1].default_value = (0.2126, 0.7152, 0.0722)
    centered_luminance = _math(group, "SUBTRACT", "Centered Shard Luminance", 140, -360, value_2=0.5)
    signed_luminance = _math(group, "MULTIPLY", "Signed Shard Luminance", 360, -360, value_2=2.0)
    image_lift = _math(group, "MULTIPLY", "Shard Image Lift", 580, -360)
    lift_vector = _node(group, "ShaderNodeCombineXYZ", "Shard Image Lift Vector", 800, -360)
    translate = _node(group, "GeometryNodeTranslateInstances", "Lift Shards From Image", 740, 430)
    links.new(image_texture.outputs["Color"], shard_luminance.inputs[0])
    links.new(shard_luminance.outputs["Value"], centered_luminance.inputs[0])
    links.new(centered_luminance.outputs[0], signed_luminance.inputs[0])
    links.new(signed_luminance.outputs[0], image_lift.inputs[0])
    links.new(inp.outputs["Luminance Lift"], image_lift.inputs[1])
    links.new(image_lift.outputs[0], lift_vector.inputs["Z"])
    links.new(rotate.outputs["Instances"], translate.inputs["Instances"])
    links.new(lift_vector.outputs[0], translate.inputs["Translation"])

    join = _node(group, "GeometryNodeJoinGeometry", "Join Plane and Paper Shards", 1000, 430)
    join["fbp_preserve_unmasked_geometry"] = True
    links.new(inp.outputs["Geometry"], join.inputs["Geometry"])
    links.new(translate.outputs["Instances"], join.inputs["Geometry"])
    links.new(join.outputs["Geometry"], out.inputs["Geometry"])
    group["fbp_instancing_contract_version"] = 4
    group["fbp_alpha_geometry_contract_version"] = 2
    return group


def _image_depth_metric(group, color_socket, custom_color_socket, mode_socket, *, prefix, x, y):
    """Return light, shadow, saturation or custom-map depth as one float field."""
    links = group.links
    luminance = _vector_math(group, "DOT_PRODUCT", f"{prefix} Luminance", x, y + 300)
    luminance.inputs[1].default_value = (0.2126, 0.7152, 0.0722)
    shadows = _math(group, "SUBTRACT", f"{prefix} Shadow Depth", x + 220, y + 300, value_1=1.0)
    # Geometry node trees expose the function variant; ShaderNodeSeparateColor
    # is valid only in shader node trees in Blender 5.2.
    split = _node(group, "FunctionNodeSeparateColor", f"{prefix} RGB", x, y)
    try:
        split.mode = "RGB"
    except (AttributeError, TypeError, ValueError):
        pass
    max_rg = _math(group, "MAXIMUM", f"{prefix} Max RG", x + 220, y + 80)
    maximum = _math(group, "MAXIMUM", f"{prefix} Maximum", x + 440, y + 80)
    min_rg = _math(group, "MINIMUM", f"{prefix} Min RG", x + 220, y - 100)
    minimum = _math(group, "MINIMUM", f"{prefix} Minimum", x + 440, y - 100)
    saturation = _math(group, "SUBTRACT", f"{prefix} Saturation Depth", x + 660, y)
    custom_luminance = _vector_math(group, "DOT_PRODUCT", f"{prefix} Custom Depth", x, y - 300)
    custom_luminance.inputs[1].default_value = (0.2126, 0.7152, 0.0722)
    links.new(color_socket, luminance.inputs[0])
    links.new(luminance.outputs["Value"], shadows.inputs[1])
    links.new(color_socket, split.inputs[0])
    links.new(_output(split, "Red", 0), max_rg.inputs[0])
    links.new(_output(split, "Green", 1), max_rg.inputs[1])
    links.new(max_rg.outputs[0], maximum.inputs[0])
    links.new(_output(split, "Blue", 2), maximum.inputs[1])
    links.new(_output(split, "Red", 0), min_rg.inputs[0])
    links.new(_output(split, "Green", 1), min_rg.inputs[1])
    links.new(min_rg.outputs[0], minimum.inputs[0])
    links.new(_output(split, "Blue", 2), minimum.inputs[1])
    links.new(maximum.outputs[0], saturation.inputs[0])
    links.new(minimum.outputs[0], saturation.inputs[1])
    links.new(custom_color_socket, custom_luminance.inputs[0])
    selected = _select_float_style(
        group,
        mode_socket,
        (
            luminance.outputs["Value"],
            shadows.outputs[0],
            saturation.outputs[0],
            custom_luminance.outputs["Value"],
        ),
        prefix=f"{prefix} Depth Mode",
        x=x + 900,
        y=y,
    )
    return selected, luminance.outputs["Value"]


def _create_sphere_screen(name):
    """Sample an image onto an efficient matrix of selectable solid instances."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Viewport Columns", "INPUT", "NodeSocketInt", default=24, minimum=2, maximum=512)
    _socket(group, "Viewport Rows", "INPUT", "NodeSocketInt", default=14, minimum=2, maximum=512)
    _socket(group, "Render Columns", "INPUT", "NodeSocketInt", default=64, minimum=2, maximum=1024)
    _socket(group, "Render Rows", "INPUT", "NodeSocketInt", default=36, minimum=2, maximum=1024)
    _socket(group, "Shape", "INPUT", "NodeSocketInt", default=0, minimum=0, maximum=3)
    _socket(group, "Solid Scale", "INPUT", "NodeSocketFloat", default=0.82, minimum=0.01, maximum=4.0)
    _socket(group, "Luminance Size", "INPUT", "NodeSocketFloat", default=0.5, minimum=-1.0, maximum=1.0)
    _socket(group, "Sphere Detail", "INPUT", "NodeSocketInt", default=1, minimum=1, maximum=5)
    _socket(group, "Depth", "INPUT", "NodeSocketFloat", default=0.0, minimum=-10.0, maximum=10.0)
    _socket(group, "Depth Mode", "INPUT", "NodeSocketInt", default=0, minimum=0, maximum=3)
    _socket(group, "Depth Image", "INPUT", "NodeSocketImage")
    _socket(group, "Flicker", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Phase", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100000.0, maximum=100000.0)
    _socket(group, "Alpha Threshold", "INPUT", "NodeSocketFloat", default=0.05, minimum=0.0, maximum=1.0)
    _socket(group, "Show Source", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Solid Material", "INPUT", "NodeSocketMaterial")
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    is_viewport = _node(group, "GeometryNodeIsViewport", "Image Solids Is Viewport", -1900, 780)
    columns = _node(group, "GeometryNodeSwitch", "Image Solids Columns", -1680, 820)
    rows = _node(group, "GeometryNodeSwitch", "Image Solids Rows", -1680, 640)
    for switch in (columns, rows):
        switch.input_type = "INT"
        links.new(is_viewport.outputs["Is Viewport"], switch.inputs["Switch"])
    links.new(inp.outputs["Render Columns"], columns.inputs["False"])
    links.new(inp.outputs["Viewport Columns"], columns.inputs["True"])
    links.new(inp.outputs["Render Rows"], rows.inputs["False"])
    links.new(inp.outputs["Viewport Rows"], rows.inputs["True"])

    bbox = _node(group, "GeometryNodeBoundBox", "Image Solids Bounds", -1900, 360)
    size = _vector_math(group, "SUBTRACT", "Image Solids Size", -1680, 380)
    center_add = _vector_math(group, "ADD", "Image Solids Center Sum", -1680, 220)
    center = _vector_math(group, "SCALE", "Image Solids Center", -1460, 220)
    center.inputs[3].default_value = 0.5
    separate_size = _node(group, "ShaderNodeSeparateXYZ", "Image Solids Size Components", -1460, 420)
    safe_width = _math(group, "MAXIMUM", "Image Solids Safe Width", -1240, 500, value_2=0.0001)
    safe_height = _math(group, "MAXIMUM", "Image Solids Safe Height", -1240, 340, value_2=0.0001)
    cell_width = _math(group, "DIVIDE", "Image Solids Cell Width", -1020, 500)
    cell_height = _math(group, "DIVIDE", "Image Solids Cell Height", -1020, 340)
    grid_width = _math(group, "SUBTRACT", "Image Solids Grid Width", -800, 500)
    grid_height = _math(group, "SUBTRACT", "Image Solids Grid Height", -800, 340)
    grid = _node(group, "GeometryNodeMeshGrid", "Image Solids Grid", -560, 420)
    transform_grid = _node(group, "GeometryNodeTransform", "Center Image Solids Grid", -320, 420)
    points = _node(group, "GeometryNodeMeshToPoints", "Image Solids Points", -80, 420)
    links.new(inp.outputs["Geometry"], bbox.inputs["Geometry"])
    links.new(bbox.outputs["Max"], size.inputs[0])
    links.new(bbox.outputs["Min"], size.inputs[1])
    links.new(bbox.outputs["Max"], center_add.inputs[0])
    links.new(bbox.outputs["Min"], center_add.inputs[1])
    links.new(center_add.outputs[0], center.inputs[0])
    links.new(size.outputs[0], separate_size.inputs[0])
    links.new(separate_size.outputs["X"], safe_width.inputs[0])
    links.new(separate_size.outputs["Y"], safe_height.inputs[0])
    links.new(safe_width.outputs[0], cell_width.inputs[0])
    links.new(columns.outputs["Output"], cell_width.inputs[1])
    links.new(safe_height.outputs[0], cell_height.inputs[0])
    links.new(rows.outputs["Output"], cell_height.inputs[1])
    links.new(safe_width.outputs[0], grid_width.inputs[0])
    links.new(cell_width.outputs[0], grid_width.inputs[1])
    links.new(safe_height.outputs[0], grid_height.inputs[0])
    links.new(cell_height.outputs[0], grid_height.inputs[1])
    links.new(grid_width.outputs[0], grid.inputs["Size X"])
    links.new(grid_height.outputs[0], grid.inputs["Size Y"])
    links.new(columns.outputs["Output"], grid.inputs["Vertices X"])
    links.new(rows.outputs["Output"], grid.inputs["Vertices Y"])
    links.new(grid.outputs["Mesh"], transform_grid.inputs["Geometry"])
    links.new(center.outputs[0], transform_grid.inputs["Translation"])
    links.new(transform_grid.outputs["Geometry"], points.inputs["Mesh"])

    position = _node(group, "GeometryNodeInputPosition", "Image Solids Point Position", 80, 40)
    separate_position = _node(group, "ShaderNodeSeparateXYZ", "Image Solids Position Components", 280, 40)
    separate_min = _node(group, "ShaderNodeSeparateXYZ", "Image Solids Bounds Minimum", 280, -140)
    u_offset = _math(group, "SUBTRACT", "Image Solids U Offset", 480, 80)
    v_offset = _math(group, "SUBTRACT", "Image Solids V Offset", 480, -60)
    u = _math(group, "DIVIDE", "Image Solids U", 680, 80)
    v = _math(group, "DIVIDE", "Image Solids V", 680, -60)
    uv = _node(group, "ShaderNodeCombineXYZ", "Image Solids UV", 880, 20)
    links.new(position.outputs["Position"], separate_position.inputs[0])
    links.new(bbox.outputs["Min"], separate_min.inputs[0])
    links.new(separate_position.outputs["X"], u_offset.inputs[0])
    links.new(separate_min.outputs["X"], u_offset.inputs[1])
    links.new(separate_position.outputs["Y"], v_offset.inputs[0])
    links.new(separate_min.outputs["Y"], v_offset.inputs[1])
    links.new(u_offset.outputs[0], u.inputs[0])
    links.new(safe_width.outputs[0], u.inputs[1])
    links.new(v_offset.outputs[0], v.inputs[0])
    links.new(safe_height.outputs[0], v.inputs[1])
    links.new(u.outputs[0], uv.inputs["X"])
    links.new(v.outputs[0], uv.inputs["Y"])

    image = _node(group, "GeometryNodeImageTexture", "Image Solids Source Image", 1080, 20)
    image["fbp_alpha_image_node"] = True
    try:
        image.extension = "EXTEND"
        image.interpolation = "Closest"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(uv.outputs[0], image.inputs["Vector"])
    depth_image = _node(group, "GeometryNodeImageTexture", "Image Solids Custom Depth", 1080, -220)
    try:
        depth_image.extension = "EXTEND"
        depth_image.interpolation = "Linear"
        depth_image.image_user.use_auto_refresh = True
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(inp.outputs["Depth Image"], depth_image.inputs["Image"])
    links.new(uv.outputs[0], depth_image.inputs["Vector"])
    visible = _math(group, "GREATER_THAN", "Image Solids Visible", 1300, -120)
    links.new(image.outputs["Alpha"], visible.inputs[0])
    links.new(inp.outputs["Alpha Threshold"], visible.inputs[1])

    depth_metric, source_luminance = _image_depth_metric(
        group, image.outputs["Color"], depth_image.outputs["Color"], inp.outputs["Depth Mode"],
        prefix="Image Solids", x=1300, y=40,
    )
    depth = _math(group, "MULTIPLY", "Image Solids Depth", 1510, 160)
    depth_offset = _node(group, "ShaderNodeCombineXYZ", "Image Solids Depth Offset", 1720, 160)
    set_position = _node(group, "GeometryNodeSetPosition", "Image Solids Relief", 1940, 420)
    links.new(depth_metric, depth.inputs[0])
    links.new(inp.outputs["Depth"], depth.inputs[1])
    links.new(depth.outputs[0], depth_offset.inputs["Z"])
    links.new(points.outputs["Points"], set_position.inputs["Geometry"])
    links.new(depth_offset.outputs[0], set_position.inputs["Offset"])

    noise = _node(group, "ShaderNodeTexWhiteNoise", "Image Solids Flicker", 1300, -360)
    noise.noise_dimensions = "4D"
    noise_center = _math(group, "SUBTRACT", "Centered Solid Flicker", 1510, -360, value_2=0.5)
    noise_double = _math(group, "MULTIPLY", "Full Solid Flicker", 1720, -360, value_2=2.0)
    noise_amount = _math(group, "MULTIPLY", "Solid Flicker Amount", 1930, -360)
    brightness = _math(group, "ADD", "Solid Flicker Brightness", 2140, -360, value_2=1.0)
    color_scale = _vector_math(group, "SCALE", "Image Solids Animated Color", 2350, -100)
    links.new(uv.outputs[0], noise.inputs["Vector"])
    links.new(inp.outputs["Phase"], noise.inputs["W"])
    links.new(noise.outputs["Value"], noise_center.inputs[0])
    links.new(noise_center.outputs[0], noise_double.inputs[0])
    links.new(noise_double.outputs[0], noise_amount.inputs[0])
    links.new(inp.outputs["Flicker"], noise_amount.inputs[1])
    links.new(noise_amount.outputs[0], brightness.inputs[0])
    links.new(image.outputs["Color"], color_scale.inputs[0])
    links.new(brightness.outputs[0], color_scale.inputs[3])

    store_color = _node(group, "GeometryNodeStoreNamedAttribute", "Store Image Solids Color", 2180, 420)
    store_color.data_type = "FLOAT_COLOR"
    store_color.domain = "POINT"
    store_color.inputs["Name"].default_value = "fbp_sphere_screen_color"
    links.new(set_position.outputs["Geometry"], store_color.inputs["Geometry"])
    links.new(color_scale.outputs[0], store_color.inputs["Value"])
    store_uv = _node(group, "GeometryNodeStoreNamedAttribute", "Store Image Solids UV", 2390, 420)
    store_uv.data_type = "FLOAT_VECTOR"
    store_uv.domain = "POINT"
    store_uv.inputs["Name"].default_value = "fbp_sphere_screen_uv"
    links.new(store_color.outputs["Geometry"], store_uv.inputs["Geometry"])
    links.new(uv.outputs[0], store_uv.inputs["Value"])

    cell_size = _math(group, "MINIMUM", "Image Solids Cell Size", -560, 100)
    radius_half = _math(group, "MULTIPLY", "Image Solids Half Cell", -340, 100, value_2=0.5)
    radius = _math(group, "MULTIPLY", "Image Solids Radius", -120, 100)
    sphere = _node(group, "GeometryNodeMeshIcoSphere", "Image Solid Sphere", 120, 160)
    links.new(cell_width.outputs[0], cell_size.inputs[0])
    links.new(cell_height.outputs[0], cell_size.inputs[1])
    links.new(cell_size.outputs[0], radius_half.inputs[0])
    links.new(radius_half.outputs[0], radius.inputs[0])
    links.new(inp.outputs["Solid Scale"], radius.inputs[1])
    links.new(radius.outputs[0], sphere.inputs["Radius"])
    links.new(inp.outputs["Sphere Detail"], sphere.inputs["Subdivisions"])
    diameter = _math(group, "MULTIPLY", "Image Solid Diameter", 120, -20, value_2=2.0)
    solid_size = _node(group, "ShaderNodeCombineXYZ", "Image Solid Size", 340, -20)
    cube = _node(group, "GeometryNodeMeshCube", "Image Solid Cube", 560, 20)
    cylinder = _node(group, "GeometryNodeMeshCylinder", "Image Solid Cylinder", 560, -160)
    cone = _node(group, "GeometryNodeMeshCone", "Image Solid Cone", 560, -360)
    cylinder.inputs["Vertices"].default_value = 12
    cylinder.inputs["Side Segments"].default_value = 1
    cylinder.inputs["Fill Segments"].default_value = 1
    cone.inputs["Vertices"].default_value = 12
    cone.inputs["Side Segments"].default_value = 1
    cone.inputs["Fill Segments"].default_value = 1
    cone.inputs["Radius Top"].default_value = 0.0
    links.new(radius.outputs[0], diameter.inputs[0])
    for axis in ("X", "Y", "Z"):
        links.new(diameter.outputs[0], solid_size.inputs[axis])
    links.new(solid_size.outputs[0], cube.inputs["Size"])
    links.new(radius.outputs[0], cylinder.inputs["Radius"])
    links.new(diameter.outputs[0], cylinder.inputs["Depth"])
    links.new(radius.outputs[0], cone.inputs["Radius Bottom"])
    links.new(diameter.outputs[0], cone.inputs["Depth"])
    selected_geometry = sphere.outputs["Mesh"]
    for shape_index, candidate, label in (
        (1, cube.outputs["Mesh"], "Cube"),
        (2, cylinder.outputs["Mesh"], "Cylinder"),
        (3, cone.outputs["Mesh"], "Cone"),
    ):
        is_shape = _math(group, "COMPARE", f"Image Solids Select {label}", 800, 160 - shape_index * 160)
        is_shape.inputs[1].default_value = float(shape_index)
        epsilon = _input(is_shape, "Epsilon", 2)
        if epsilon is not None:
            epsilon.default_value = 0.1
        links.new(inp.outputs["Shape"], is_shape.inputs[0])
        switch = _node(group, "GeometryNodeSwitch", f"Image Solids {label}", 1020, 160 - shape_index * 120)
        switch.input_type = "GEOMETRY"
        links.new(is_shape.outputs[0], switch.inputs["Switch"])
        links.new(selected_geometry, switch.inputs["False"])
        links.new(candidate, switch.inputs["True"])
        selected_geometry = switch.outputs["Output"]
    material = _node(group, "GeometryNodeSetMaterial", "Image Solids Material", 1260, 100)
    links.new(selected_geometry, material.inputs["Geometry"])
    links.new(inp.outputs["Solid Material"], material.inputs["Material"])
    instance = _node(group, "GeometryNodeInstanceOnPoints", "Instance Image Solids", 2580, 420)
    links.new(store_uv.outputs["Geometry"], instance.inputs["Points"])
    links.new(visible.outputs[0], instance.inputs["Selection"])
    links.new(material.outputs["Geometry"], instance.inputs["Instance"])
    centered_size_luminance = _math(group, "SUBTRACT", "Centered Solid Size Luminance", 2140, -540, value_2=0.5)
    signed_size_luminance = _math(group, "MULTIPLY", "Signed Solid Size Luminance", 2350, -540, value_2=2.0)
    size_response = _math(group, "MULTIPLY", "Solid Luminance Size Response", 2560, -540)
    size_factor = _math(group, "ADD", "Solid Luminance Size", 2770, -540, value_2=1.0)
    safe_size = _math(group, "MAXIMUM", "Safe Solid Luminance Size", 2980, -540, value_2=0.05)
    size_vector = _node(group, "ShaderNodeCombineXYZ", "Solid Luminance Scale", 3190, -540)
    links.new(source_luminance, centered_size_luminance.inputs[0])
    links.new(centered_size_luminance.outputs[0], signed_size_luminance.inputs[0])
    links.new(signed_size_luminance.outputs[0], size_response.inputs[0])
    links.new(inp.outputs["Luminance Size"], size_response.inputs[1])
    links.new(size_response.outputs[0], size_factor.inputs[0])
    links.new(size_factor.outputs[0], safe_size.inputs[0])
    for axis in ("X", "Y", "Z"):
        links.new(safe_size.outputs[0], size_vector.inputs[axis])
    links.new(size_vector.outputs[0], instance.inputs["Scale"])

    source_switch = _node(group, "GeometryNodeSwitch", "Show Image Solids Source", 2580, 160)
    source_switch.input_type = "GEOMETRY"
    links.new(inp.outputs["Show Source"], source_switch.inputs["Switch"])
    links.new(inp.outputs["Geometry"], source_switch.inputs["True"])
    join = _node(group, "GeometryNodeJoinGeometry", "Image Solids Output", 2820, 380)
    links.new(source_switch.outputs["Output"], join.inputs["Geometry"])
    links.new(instance.outputs["Instances"], join.inputs["Geometry"])
    links.new(join.outputs["Geometry"], out.inputs["Geometry"])
    group["fbp_instancing_contract_version"] = 1
    group["fbp_image_geometry_contract_version"] = 1
    return group


def _create_image_relief(name):
    """Displace the UV-preserving source mesh from image-derived depth."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Subdivision", "INPUT", "NodeSocketInt", default=5, minimum=0, maximum=8)
    _socket(group, "Depth", "INPUT", "NodeSocketFloat", default=0.12, minimum=-10.0, maximum=10.0)
    _socket(group, "Midlevel", "INPUT", "NodeSocketFloat", default=0.5, minimum=0.0, maximum=1.0)
    _socket(group, "Depth Mode", "INPUT", "NodeSocketInt", default=0, minimum=0, maximum=3)
    _socket(group, "Depth Image", "INPUT", "NodeSocketImage")
    _socket(group, "Smooth", "INPUT", "NodeSocketFloat", default=0.35, minimum=0.0, maximum=1.0)
    _socket(group, "Smooth Iterations", "INPUT", "NodeSocketInt", default=4, minimum=0, maximum=64)
    _socket(group, "Alpha Threshold", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Shade Smooth", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    remeshed = _aspect_remesh(
        group, inp.outputs["Geometry"], inp.outputs["Subdivision"],
        prefix="Image Relief", x=-4600, y=620, triangulate=True,
    )
    named_uv = _node(group, "GeometryNodeInputNamedAttribute", "Image Relief UVMap", -1280, -40)
    named_uv.data_type = "FLOAT_VECTOR"
    named_uv.inputs["Name"].default_value = "UVMap"
    image = _node(group, "GeometryNodeImageTexture", "Image Relief Source", -1040, -20)
    image["fbp_alpha_image_node"] = True
    custom = _node(group, "GeometryNodeImageTexture", "Image Relief Custom Depth", -1040, -260)
    try:
        image.extension = "EXTEND"
        image.interpolation = "Linear"
        custom.extension = "EXTEND"
        custom.interpolation = "Linear"
        custom.image_user.use_auto_refresh = True
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(named_uv.outputs["Attribute"], image.inputs["Vector"])
    links.new(named_uv.outputs["Attribute"], custom.inputs["Vector"])
    links.new(inp.outputs["Depth Image"], custom.inputs["Image"])

    depth_metric, _source_luminance = _image_depth_metric(
        group, image.outputs["Color"], custom.outputs["Color"], inp.outputs["Depth Mode"],
        prefix="Image Relief", x=-760, y=-40,
    )
    blur = _node(group, "GeometryNodeBlurAttribute", "Smooth Image Relief Depth", 80, -40)
    blur.data_type = "FLOAT"
    inverse_smooth = _math(group, "SUBTRACT", "Image Relief Original Weight", 80, -280, value_1=1.0)
    original_depth = _math(group, "MULTIPLY", "Image Relief Original Depth", 300, -180)
    blurred_depth = _math(group, "MULTIPLY", "Image Relief Smoothed Depth", 300, -40)
    blended_depth = _math(group, "ADD", "Image Relief Blended Depth", 520, -100)
    smooth_enabled = _math(group, "GREATER_THAN", "Image Relief Smooth Enabled", 520, -300, value_2=0.000001)
    iterations_enabled = _math(group, "GREATER_THAN", "Image Relief Smooth Iterations Enabled", 520, -420, value_2=0.5)
    smooth_active = _math(group, "MULTIPLY", "Image Relief Smoothing Active", 740, -360)
    smooth_switch = _node(group, "GeometryNodeSwitch", "Image Relief Smoothed Depth Switch", 740, -140)
    smooth_switch.input_type = "FLOAT"
    centered = _math(group, "SUBTRACT", "Image Relief Midlevel", 520, -20)
    displacement = _math(group, "MULTIPLY", "Image Relief Depth", 740, -20)
    offset = _node(group, "ShaderNodeCombineXYZ", "Image Relief Offset", 960, -20)
    visible = _math(group, "GREATER_THAN", "Image Relief Alpha", 740, -220)
    set_position = _node(group, "GeometryNodeSetPosition", "Displace Image Relief", 1180, 340)
    smooth = _node(group, "GeometryNodeSetShadeSmooth", "Image Relief Shading", 1400, 340)
    links.new(depth_metric, blur.inputs["Value"])
    links.new(inp.outputs["Smooth Iterations"], blur.inputs["Iterations"])
    links.new(inp.outputs["Smooth"], inverse_smooth.inputs[1])
    links.new(depth_metric, original_depth.inputs[0])
    links.new(inverse_smooth.outputs[0], original_depth.inputs[1])
    links.new(blur.outputs["Value"], blurred_depth.inputs[0])
    links.new(inp.outputs["Smooth"], blurred_depth.inputs[1])
    links.new(original_depth.outputs[0], blended_depth.inputs[0])
    links.new(blurred_depth.outputs[0], blended_depth.inputs[1])
    links.new(inp.outputs["Smooth"], smooth_enabled.inputs[0])
    links.new(inp.outputs["Smooth Iterations"], iterations_enabled.inputs[0])
    links.new(smooth_enabled.outputs[0], smooth_active.inputs[0])
    links.new(iterations_enabled.outputs[0], smooth_active.inputs[1])
    links.new(smooth_active.outputs[0], smooth_switch.inputs["Switch"])
    links.new(depth_metric, smooth_switch.inputs["False"])
    links.new(blended_depth.outputs[0], smooth_switch.inputs["True"])
    links.new(smooth_switch.outputs["Output"], centered.inputs[0])
    links.new(inp.outputs["Midlevel"], centered.inputs[1])
    links.new(centered.outputs[0], displacement.inputs[0])
    links.new(inp.outputs["Depth"], displacement.inputs[1])
    links.new(displacement.outputs[0], offset.inputs["Z"])
    links.new(image.outputs["Alpha"], visible.inputs[0])
    links.new(inp.outputs["Alpha Threshold"], visible.inputs[1])
    links.new(remeshed, set_position.inputs["Geometry"])
    links.new(visible.outputs[0], set_position.inputs["Selection"])
    links.new(offset.outputs[0], set_position.inputs["Offset"])
    links.new(set_position.outputs["Geometry"], smooth.inputs["Mesh"])
    links.new(inp.outputs["Shade Smooth"], smooth.inputs["Shade Smooth"])
    links.new(smooth.outputs["Mesh"], out.inputs["Geometry"])
    group["fbp_image_relief_contract_version"] = 3
    group["fbp_image_geometry_contract_version"] = 1
    return group


def _configure_voronoi(node, feature):
    """Configure a texture node defensively across supported Blender builds."""
    try:
        node.voronoi_dimensions = "3D"
        node.feature = feature
        node.distance = "EUCLIDEAN"
    except (AttributeError, TypeError, ValueError):
        pass
    return node


def _aspect_corrected_texture_coordinates(
    group,
    geometry_socket,
    uv_socket,
    correct_aspect_socket,
    overall_scale_socket,
    scale_x_socket,
    scale_y_socket,
    *,
    prefix,
    result_name,
    x,
    y,
):
    """Return UV coordinates with world-shape aspect correction and X/Y trim."""
    links = group.links
    bounds = _node(group, "GeometryNodeBoundBox", f"{prefix} Texture Bounds", x, y + 320)
    size = _vector_math(group, "SUBTRACT", f"{prefix} Texture Size", x + 220, y + 320)
    separate = _node(group, "ShaderNodeSeparateXYZ", f"{prefix} Texture Dimensions", x + 440, y + 320)
    safe_x = _math(group, "MAXIMUM", f"{prefix} Safe Texture Width", x + 660, y + 400, value_2=1.0e-6)
    safe_y = _math(group, "MAXIMUM", f"{prefix} Safe Texture Height", x + 660, y + 280, value_2=1.0e-6)
    minimum = _math(group, "MINIMUM", f"{prefix} Texture Minimum Dimension", x + 880, y + 340)
    aspect_x = _math(group, "DIVIDE", f"{prefix} Texture Aspect X", x + 1100, y + 400)
    aspect_y = _math(group, "DIVIDE", f"{prefix} Texture Aspect Y", x + 1100, y + 280)
    auto_vector = _node(group, "ShaderNodeCombineXYZ", f"{prefix} Automatic Texture Aspect", x + 1320, y + 360)
    auto_vector.inputs["Z"].default_value = 1.0
    aspect_switch = _node(group, "GeometryNodeSwitch", f"{prefix} Use Automatic Texture Aspect", x + 1540, y + 260)
    aspect_switch.input_type = "VECTOR"
    aspect_switch.inputs["False"].default_value = (1.0, 1.0, 1.0)
    manual_vector = _node(group, "ShaderNodeCombineXYZ", f"{prefix} Manual Texture Scale", x + 1320, y + 80)
    manual_vector.inputs["Z"].default_value = 1.0
    combined = _vector_math(group, "MULTIPLY", f"{prefix} Texture Scale Vector", x + 1760, y + 180)
    scaled_uv = _vector_math(group, "MULTIPLY", f"{prefix} Aspect Corrected UV", x + 1980, y)
    overall = _vector_math(group, "SCALE", result_name, x + 2200, y)

    links.new(geometry_socket, bounds.inputs["Geometry"])
    links.new(bounds.outputs["Max"], size.inputs[0])
    links.new(bounds.outputs["Min"], size.inputs[1])
    links.new(size.outputs[0], separate.inputs[0])
    links.new(separate.outputs["X"], safe_x.inputs[0])
    links.new(separate.outputs["Y"], safe_y.inputs[0])
    links.new(safe_x.outputs[0], minimum.inputs[0])
    links.new(safe_y.outputs[0], minimum.inputs[1])
    links.new(safe_x.outputs[0], aspect_x.inputs[0])
    links.new(minimum.outputs[0], aspect_x.inputs[1])
    links.new(safe_y.outputs[0], aspect_y.inputs[0])
    links.new(minimum.outputs[0], aspect_y.inputs[1])
    links.new(aspect_x.outputs[0], auto_vector.inputs["X"])
    links.new(aspect_y.outputs[0], auto_vector.inputs["Y"])
    links.new(correct_aspect_socket, aspect_switch.inputs["Switch"])
    links.new(auto_vector.outputs[0], aspect_switch.inputs["True"])
    links.new(scale_x_socket, manual_vector.inputs["X"])
    links.new(scale_y_socket, manual_vector.inputs["Y"])
    links.new(aspect_switch.outputs["Output"], combined.inputs[0])
    links.new(manual_vector.outputs[0], combined.inputs[1])
    links.new(uv_socket, scaled_uv.inputs[0])
    links.new(combined.outputs[0], scaled_uv.inputs[1])
    links.new(scaled_uv.outputs[0], overall.inputs[0])
    links.new(overall_scale_socket, overall.inputs[3])
    return overall.outputs[0]


def _create_glass(name):
    """Create separated Voronoi shards from the animated source silhouette."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Subdivision", "INPUT", "NodeSocketInt", default=5, minimum=0, maximum=8)
    _socket(group, "Thickness", "INPUT", "NodeSocketFloat", default=0.025, minimum=0.0001, maximum=10.0)
    _socket(group, "Bevel", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Shard Lift", "INPUT", "NodeSocketFloat", default=0.015, minimum=-10.0, maximum=10.0)
    _socket(group, "Damage Source", "INPUT", "NodeSocketInt", default=1, minimum=0, maximum=2)
    _socket(group, "Damage Map", "INPUT", "NodeSocketImage")
    _socket(group, "Cell Scale", "INPUT", "NodeSocketFloat", default=7.0, minimum=0.01, maximum=10000.0)
    _socket(group, "Correct Aspect", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Texture Scale X", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.01, maximum=10000.0)
    _socket(group, "Texture Scale Y", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.01, maximum=10000.0)
    _socket(group, "Crack Width", "INPUT", "NodeSocketFloat", default=0.035, minimum=0.0, maximum=0.5)
    _socket(group, "Damage", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Chaos", "INPUT", "NodeSocketFloat", default=0.65, minimum=0.0, maximum=1.0)
    _socket(group, "Seed", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100000.0, maximum=100000.0)
    _socket(group, "Alpha Threshold", "INPUT", "NodeSocketFloat", default=0.02, minimum=0.0, maximum=1.0)
    _socket(group, "Shade Smooth", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Glass Material", "INPUT", "NodeSocketMaterial")
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    remeshed = _aspect_remesh(
        group, inp.outputs["Geometry"], inp.outputs["Subdivision"],
        # Quads remain preferable for shard extrusion: they halve cap polygon
        # count while the aspect-balanced grid removes the old wide cells.
        prefix="Broken Glass", x=-4600, y=700, triangulate=False,
    )
    named_uv = _node(group, "GeometryNodeInputNamedAttribute", "Broken Glass UVMap", -1800, 80)
    named_uv.data_type = "FLOAT_VECTOR"
    named_uv.inputs["Name"].default_value = "UVMap"
    source = _node(group, "GeometryNodeImageTexture", "Broken Glass Source Image", -1560, 180)
    source["fbp_alpha_image_node"] = True
    damage_image = _node(group, "GeometryNodeImageTexture", "Broken Glass Damage Map", -1560, -80)
    damage_bw = _node(group, "ShaderNodeSeparateXYZ", "Broken Glass Damage Luminance", -1320, -80)
    try:
        source.extension = "EXTEND"
        source.interpolation = "Linear"
        damage_image.extension = "EXTEND"
        damage_image.interpolation = "Linear"
        damage_image.image_user.use_auto_refresh = True
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(named_uv.outputs["Attribute"], source.inputs["Vector"])
    links.new(named_uv.outputs["Attribute"], damage_image.inputs["Vector"])
    links.new(inp.outputs["Damage Map"], damage_image.inputs["Image"])
    links.new(damage_image.outputs["Color"], damage_bw.inputs["Vector"])

    coordinate_scale = _aspect_corrected_texture_coordinates(
        group,
        inp.outputs["Geometry"],
        named_uv.outputs["Attribute"],
        inp.outputs["Correct Aspect"],
        inp.outputs["Cell Scale"],
        inp.outputs["Texture Scale X"],
        inp.outputs["Texture Scale Y"],
        prefix="Broken Glass",
        result_name="Broken Glass Cell Scale",
        x=-2880,
        y=-380,
    )
    seed_vector = _node(group, "ShaderNodeCombineXYZ", "Broken Glass Seed Vector", -1320, -620)
    seed_y = _math(group, "MULTIPLY", "Broken Glass Seed Y", -1540, -720, value_2=0.618033989)
    seed_z = _math(group, "MULTIPLY", "Broken Glass Seed Z", -1540, -820, value_2=-0.414213562)
    shifted = _vector_math(group, "ADD", "Broken Glass Shifted Cells", -1080, -420)
    links.new(inp.outputs["Seed"], seed_vector.inputs["X"])
    links.new(inp.outputs["Seed"], seed_y.inputs[0])
    links.new(inp.outputs["Seed"], seed_z.inputs[0])
    links.new(seed_y.outputs[0], seed_vector.inputs["Y"])
    links.new(seed_z.outputs[0], seed_vector.inputs["Z"])
    links.new(coordinate_scale, shifted.inputs[0])
    links.new(seed_vector.outputs[0], shifted.inputs[1])

    edges = _configure_voronoi(
        _node(group, "ShaderNodeTexVoronoi", "Broken Glass Voronoi Edges", -820, -520),
        "DISTANCE_TO_EDGE",
    )
    cells = _configure_voronoi(
        _node(group, "ShaderNodeTexVoronoi", "Broken Glass Cell Identity", -820, -760),
        "F1",
    )
    cell_bw = _node(group, "ShaderNodeSeparateXYZ", "Broken Glass Cell Random", -580, -760)
    links.new(shifted.outputs[0], edges.inputs["Vector"])
    links.new(shifted.outputs[0], cells.inputs["Vector"])
    links.new(cells.outputs["Color"], cell_bw.inputs["Vector"])

    damage_field = _select_float_style(
        group,
        inp.outputs["Damage Source"],
        (source.outputs["Alpha"], inp.outputs["Damage"], damage_bw.outputs["X"]),
        prefix="Broken Glass Damage Source",
        x=-900,
        y=-40,
    )
    damage_amount = _math(group, "MULTIPLY", "Broken Glass Damage Amount", -520, -80)
    crack_width = _math(group, "MULTIPLY", "Broken Glass Open Crack Width", -300, -80)
    crack = _math(group, "LESS_THAN", "Broken Glass Crack Selection", -60, -80)
    links.new(damage_field, damage_amount.inputs[0])
    links.new(inp.outputs["Damage"], damage_amount.inputs[1])
    links.new(inp.outputs["Crack Width"], crack_width.inputs[0])
    links.new(damage_amount.outputs[0], crack_width.inputs[1])
    links.new(edges.outputs["Distance"], crack.inputs[0])
    links.new(crack_width.outputs[0], crack.inputs[1])

    cell_centered = _math(group, "SUBTRACT", "Broken Glass Center Cell", -300, -620, value_2=0.5)
    lift_chaos = _math(group, "MULTIPLY", "Broken Glass Lift Chaos", -60, -620)
    lift_amount = _math(group, "MULTIPLY", "Broken Glass Shard Lift", 180, -620)
    lift_damage = _math(group, "MULTIPLY", "Broken Glass Lift Damage", 420, -620)
    lift_vector = _node(group, "ShaderNodeCombineXYZ", "Broken Glass Lift Vector", 660, -620)
    links.new(cell_bw.outputs["X"], cell_centered.inputs[0])
    links.new(cell_centered.outputs[0], lift_chaos.inputs[0])
    links.new(inp.outputs["Chaos"], lift_chaos.inputs[1])
    links.new(lift_chaos.outputs[0], lift_amount.inputs[0])
    links.new(inp.outputs["Shard Lift"], lift_amount.inputs[1])
    links.new(lift_amount.outputs[0], lift_damage.inputs[0])
    links.new(damage_amount.outputs[0], lift_damage.inputs[1])
    links.new(lift_damage.outputs[0], lift_vector.inputs["Z"])

    store_color = _node(group, "GeometryNodeStoreNamedAttribute", "Store Broken Glass Color", -1040, 520)
    store_color.data_type = "FLOAT_COLOR"
    store_color.domain = "POINT"
    store_color.inputs["Name"].default_value = "fbp_glass_color"
    store_alpha = _node(group, "GeometryNodeStoreNamedAttribute", "Store Broken Glass Alpha", -800, 520)
    store_alpha.data_type = "FLOAT"
    store_alpha.domain = "POINT"
    store_alpha.inputs["Name"].default_value = "fbp_glass_alpha"
    store_height = _node(group, "GeometryNodeStoreNamedAttribute", "Store Broken Glass Crack Field", -560, 520)
    store_height.data_type = "FLOAT"
    store_height.domain = "POINT"
    store_height.inputs["Name"].default_value = "fbp_glass_height"
    store_normal = _node(group, "GeometryNodeStoreNamedAttribute", "Store Broken Glass Cell Color", -320, 520)
    store_normal.data_type = "FLOAT_COLOR"
    store_normal.domain = "POINT"
    store_normal.inputs["Name"].default_value = "fbp_glass_normal"
    links.new(remeshed, store_color.inputs["Geometry"])
    links.new(source.outputs["Color"], store_color.inputs["Value"])
    links.new(store_color.outputs["Geometry"], store_alpha.inputs["Geometry"])
    links.new(source.outputs["Alpha"], store_alpha.inputs["Value"])
    links.new(store_alpha.outputs["Geometry"], store_height.inputs["Geometry"])
    links.new(edges.outputs["Distance"], store_height.inputs["Value"])
    links.new(store_height.outputs["Geometry"], store_normal.inputs["Geometry"])
    links.new(cells.outputs["Color"], store_normal.inputs["Value"])

    set_position = _node(group, "GeometryNodeSetPosition", "Lift Broken Glass Shards", -60, 520)
    transparent = _math(group, "LESS_THAN", "Broken Glass Transparent Faces", 160, 180)
    remove = _node(group, "FunctionNodeBooleanMath", "Broken Glass Remove Faces", 400, 180)
    remove.operation = "OR"
    delete = _node(group, "GeometryNodeDeleteGeometry", "Open Broken Glass Cracks", 420, 520)
    delete.domain = "FACE"
    links.new(store_normal.outputs["Geometry"], set_position.inputs["Geometry"])
    links.new(lift_vector.outputs[0], set_position.inputs["Offset"])
    links.new(source.outputs["Alpha"], transparent.inputs[0])
    links.new(inp.outputs["Alpha Threshold"], transparent.inputs[1])
    links.new(transparent.outputs[0], remove.inputs[0])
    links.new(crack.outputs[0], remove.inputs[1])
    links.new(set_position.outputs["Geometry"], delete.inputs["Geometry"])
    links.new(remove.outputs[0], delete.inputs["Selection"])

    back_amount = _math(group, "MULTIPLY", "Broken Glass Back Thickness", 500, 180, value_2=-1.0)
    thickness = _node(group, "ShaderNodeCombineXYZ", "Broken Glass Thickness", 700, 180)
    extrude = _node(group, "GeometryNodeExtrudeMesh", "Close Broken Glass Shards", 680, 520)
    extrude.mode = "FACES"
    # Extrude each connected shard as one region. Blender's per-face mode makes
    # one closed cell for every subdivided quad, leaving coincident inner walls
    # that look like a false tessellation after smooth shading/subdivision.
    individual = _input(extrude, "Individual")
    if individual is not None:
        individual.default_value = False
    links.new(inp.outputs["Thickness"], back_amount.inputs[0])
    links.new(back_amount.outputs[0], thickness.inputs["Z"])
    links.new(delete.outputs["Geometry"], extrude.inputs["Mesh"])
    links.new(thickness.outputs[0], extrude.inputs["Offset"])

    # A region extrusion contains the displaced cap and its boundary walls, but
    # not the original front cap. Re-add that source surface, flip only the
    # generated back cap, then weld the shared rim. This produces one manifold
    # shell per shard without duplicate faces or hidden walls inside the grid.
    flip_back = _node(group, "GeometryNodeFlipFaces", "Orient Broken Glass Back Cap", 920, 520)
    links.new(extrude.outputs["Mesh"], flip_back.inputs["Mesh"])
    links.new(extrude.outputs["Top"], flip_back.inputs["Selection"])
    join_volume = _node(group, "GeometryNodeJoinGeometry", "Assemble Broken Glass Volume", 1160, 520)
    links.new(delete.outputs["Geometry"], join_volume.inputs["Geometry"])
    links.new(flip_back.outputs["Mesh"], join_volume.inputs["Geometry"])
    merge_rim = _node(group, "GeometryNodeMergeByDistance", "Weld Broken Glass Rim", 1400, 520)
    merge_rim.inputs["Distance"].default_value = 1.0e-6
    links.new(join_volume.outputs["Geometry"], merge_rim.inputs["Geometry"])

    edge_angle = _node(group, "GeometryNodeInputMeshEdgeAngle", "Broken Glass Edge Angle", 1400, 80)
    sharp_edges = _math(group, "GREATER_THAN", "Broken Glass Sharp Edges", 1640, 80, value_2=0.017453292)
    bevel = _node(group, "GeometryNodeMeshBevel", "Bevel Broken Glass Geometry", 1640, 520)
    bevel.inputs["Segments"].default_value = 1
    bevel.inputs["Shape"].default_value = 0.5
    bevel.inputs["Miter"].default_value = True
    has_bevel = _math(group, "GREATER_THAN", "Broken Glass Has Bevel", 1640, 240, value_2=1.0e-6)
    bevel_switch = _node(group, "GeometryNodeSwitch", "Broken Glass Bevel Bypass", 2120, 520)
    bevel_switch.input_type = "GEOMETRY"
    links.new(merge_rim.outputs["Geometry"], bevel.inputs["Mesh"])
    links.new(edge_angle.outputs["Unsigned Angle"], sharp_edges.inputs[0])
    links.new(sharp_edges.outputs[0], bevel.inputs["Selection"])
    links.new(inp.outputs["Bevel"], bevel.inputs["Offset"])
    links.new(inp.outputs["Bevel"], has_bevel.inputs[0])
    links.new(has_bevel.outputs[0], bevel_switch.inputs["Switch"])
    links.new(merge_rim.outputs["Geometry"], bevel_switch.inputs["False"])
    links.new(bevel.outputs["Mesh"], bevel_switch.inputs["True"])

    material = _node(group, "GeometryNodeSetMaterial", "Broken Glass Material", 2360, 520)
    smooth = _node(group, "GeometryNodeSetShadeSmooth", "Broken Glass Smooth Shading", 2600, 520)
    links.new(bevel_switch.outputs["Output"], material.inputs["Geometry"])
    links.new(inp.outputs["Glass Material"], material.inputs["Material"])
    links.new(material.outputs["Geometry"], smooth.inputs["Mesh"])
    links.new(inp.outputs["Shade Smooth"], smooth.inputs["Shade Smooth"])
    links.new(smooth.outputs["Mesh"], out.inputs["Geometry"])
    group["fbp_glass_contract_version"] = 6
    group["fbp_image_geometry_contract_version"] = 1
    return group


def _create_crystal(name):
    """Create rounded alpha-depth crystal geometry with procedural structure."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Subdivision", "INPUT", "NodeSocketInt", default=4, minimum=0, maximum=8)
    _socket(group, "Silhouette Detail", "INPUT", "NodeSocketInt", default=2, minimum=0, maximum=4)
    _socket(group, "Depth", "INPUT", "NodeSocketFloat", default=0.14, minimum=-10.0, maximum=10.0)
    _socket(group, "Thickness", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=10.0)
    _socket(group, "Roundness", "INPUT", "NodeSocketFloat", default=0.8, minimum=0.0, maximum=1.0)
    _socket(group, "Edge Pinning", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Blur Iterations", "INPUT", "NodeSocketInt", default=4, minimum=0, maximum=32)
    _socket(group, "Use Influence Map", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Influence Map", "INPUT", "NodeSocketImage")
    _socket(group, "Invert Influence", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Influence Strength", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Texture Type", "INPUT", "NodeSocketInt", default=0, minimum=0, maximum=3)
    _socket(group, "Pattern Mode", "INPUT", "NodeSocketInt", default=1, minimum=0, maximum=2)
    _socket(group, "Pattern Scale", "INPUT", "NodeSocketFloat", default=8.0, minimum=0.01, maximum=10000.0)
    _socket(group, "Correct Aspect", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Texture Scale X", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.01, maximum=10000.0)
    _socket(group, "Texture Scale Y", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.01, maximum=10000.0)
    _socket(group, "Pattern Detail", "INPUT", "NodeSocketFloat", default=4.0, minimum=0.0, maximum=64.0)
    _socket(group, "Pattern Strength", "INPUT", "NodeSocketFloat", default=0.035, minimum=-10.0, maximum=10.0)
    _socket(group, "Cell Randomness", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Cell Seed", "INPUT", "NodeSocketInt", default=0, minimum=0, maximum=2147483647)
    _socket(group, "Phase", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100000.0, maximum=100000.0)
    _socket(group, "Alpha Threshold", "INPUT", "NodeSocketFloat", default=0.5, minimum=0.0, maximum=1.0)
    _socket(group, "Surface Subdivision", "INPUT", "NodeSocketInt", default=1, minimum=0, maximum=2)
    _socket(group, "Shade Smooth", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Crystal Material", "INPUT", "NodeSocketMaterial")
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    # Build Crystal in two topology stages. The first stage is one level below
    # the requested quality and is cheap enough to classify the painted alpha.
    # Only the visible region plus its blur halo is refined back to the requested
    # edge density. Transparent canvas therefore stops multiplying the cost of
    # every downstream image, blur and Voronoi field.
    coarse_offset = _math(group, "SUBTRACT", "Crystal Coarse Offset", -5060, 420, value_2=1.0)
    coarse_level = _math(group, "MAXIMUM", "Crystal Coarse Level", -4840, 420, value_2=0.0)
    links.new(inp.outputs["Subdivision"], coarse_offset.inputs[0])
    links.new(coarse_offset.outputs[0], coarse_level.inputs[0])
    coarse_mesh = _aspect_remesh(
        group, inp.outputs["Geometry"], coarse_level.outputs[0],
        # Catmull-Clark rounds an all-quad volume more evenly and with fewer
        # faces; aspect balancing solves the stretched-cell problem upstream.
        prefix="Crystal", x=-4600, y=720, triangulate=False,
    )
    named_uv = _node(group, "GeometryNodeInputNamedAttribute", "Crystal UVMap", -1900, 100)
    named_uv.data_type = "FLOAT_VECTOR"
    named_uv.inputs["Name"].default_value = "UVMap"
    source = _node(group, "GeometryNodeImageTexture", "Crystal Source Image", -1660, 140)
    source["fbp_alpha_image_node"] = True
    source["fbp_plane_uv_source_image_node"] = True
    try:
        source.extension = "EXTEND"
        source.interpolation = "Linear"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(named_uv.outputs["Attribute"], source.inputs["Vector"])

    # Optional painted influence. White receives Crystal geometry and optics;
    # black keeps an opaque copy of the source image at the original plane.
    # The explicit switch guarantees full Crystal coverage when no influence
    # map is requested, independent of an unassigned Image socket evaluation.
    influence_image = _node(group, "GeometryNodeImageTexture", "Crystal Influence Map", -1660, -60)
    influence_image["fbp_plane_uv_aux_image_node"] = True
    try:
        influence_image.extension = "EXTEND"
        influence_image.interpolation = "Linear"
    except (AttributeError, TypeError, ValueError):
        pass
    influence_luma = _vector_math(group, "DOT_PRODUCT", "Crystal Influence Luminance", -1420, -40)
    influence_luma.inputs[1].default_value = (0.2126, 0.7152, 0.0722)
    influence_with_alpha = _math(group, "MULTIPLY", "Crystal Influence With Alpha", -1180, -40)
    influence_low = _math(group, "MAXIMUM", "Crystal Influence Minimum", -940, -40, value_2=0.0)
    influence_high = _math(group, "MINIMUM", "Crystal Influence Maximum", -700, -40, value_2=1.0)
    influence_inverse = _math(group, "SUBTRACT", "Crystal Inverted Influence", -700, -160, value_1=1.0)
    influence_invert = _node(group, "GeometryNodeSwitch", "Crystal Invert Influence", -460, -40)
    influence_invert.input_type = "FLOAT"
    influence_use = _node(group, "GeometryNodeSwitch", "Crystal Use Influence Map", -220, -40)
    influence_use.input_type = "FLOAT"
    influence_use.inputs["False"].default_value = 1.0
    influence_missing = _math(group, "SUBTRACT", "Crystal Missing Influence", 20, -40, value_1=1.0)
    influence_weighted = _math(group, "MULTIPLY", "Crystal Influence Strength", 260, -40)
    effective_influence = _math(group, "SUBTRACT", "Crystal Effective Influence", 500, -40, value_1=1.0)
    links.new(inp.outputs["Influence Map"], influence_image.inputs["Image"])
    links.new(named_uv.outputs["Attribute"], influence_image.inputs["Vector"])
    links.new(influence_image.outputs["Color"], influence_luma.inputs[0])
    links.new(influence_luma.outputs["Value"], influence_with_alpha.inputs[0])
    links.new(influence_image.outputs["Alpha"], influence_with_alpha.inputs[1])
    links.new(influence_with_alpha.outputs[0], influence_low.inputs[0])
    links.new(influence_low.outputs[0], influence_high.inputs[0])
    links.new(influence_high.outputs[0], influence_inverse.inputs[1])
    links.new(inp.outputs["Invert Influence"], influence_invert.inputs["Switch"])
    links.new(influence_high.outputs[0], influence_invert.inputs["False"])
    links.new(influence_inverse.outputs[0], influence_invert.inputs["True"])
    links.new(inp.outputs["Use Influence Map"], influence_use.inputs["Switch"])
    links.new(influence_invert.outputs["Output"], influence_use.inputs["True"])
    links.new(influence_use.outputs["Output"], influence_missing.inputs[1])
    links.new(influence_missing.outputs[0], influence_weighted.inputs[0])
    links.new(inp.outputs["Influence Strength"], influence_weighted.inputs[1])
    links.new(influence_weighted.outputs[0], effective_influence.inputs[1])

    alpha_visible = _math(group, "GREATER_THAN", "Crystal Exact Alpha Cutoff", -1420, 120)
    links.new(source.outputs["Alpha"], alpha_visible.inputs[0])
    links.new(inp.outputs["Alpha Threshold"], alpha_visible.inputs[1])

    active_edge_profile = _math(group, "MAXIMUM", "Crystal Active Edge Profile", -2340, -220)
    halo_roundness = _math(group, "MULTIPLY", "Crystal Active Halo Passes", -2120, -220)
    halo_iterations = _math(group, "ADD", "Crystal Edge Halo Passes", -1900, -220, value_2=1.0)
    halo_blur = _node(group, "GeometryNodeBlurAttribute", "Crystal Alpha Edge Halo", -1660, -220)
    halo_blur.data_type = "FLOAT"
    try:
        halo_blur.domain = "POINT"
    except (AttributeError, TypeError, ValueError):
        pass
    outside_halo = _math(group, "LESS_THAN", "Crystal Outside Edge Halo", -1420, -220, value_2=1.0e-6)
    coarse_cut = _node(group, "GeometryNodeDeleteGeometry", "Cull Transparent Crystal Canvas", -1180, 500)
    coarse_cut.domain = "FACE"
    has_detail = _math(group, "GREATER_THAN", "Crystal Has Edge Detail", -1180, 260, value_2=0.0)
    silhouette_detail = _math(group, "ADD", "Crystal Silhouette Detail Level", -940, 260)
    adaptive_detail = _node(group, "GeometryNodeSubdivideMesh", "Refine Crystal Alpha Region", -940, 500)
    links.new(inp.outputs["Roundness"], active_edge_profile.inputs[0])
    links.new(inp.outputs["Edge Pinning"], active_edge_profile.inputs[1])
    links.new(inp.outputs["Blur Iterations"], halo_roundness.inputs[0])
    links.new(active_edge_profile.outputs[0], halo_roundness.inputs[1])
    links.new(halo_roundness.outputs[0], halo_iterations.inputs[0])
    links.new(alpha_visible.outputs[0], halo_blur.inputs["Value"])
    links.new(halo_iterations.outputs[0], halo_blur.inputs["Iterations"])
    links.new(halo_blur.outputs["Value"], outside_halo.inputs[0])
    links.new(coarse_mesh, coarse_cut.inputs["Geometry"])
    links.new(outside_halo.outputs[0], coarse_cut.inputs["Selection"])
    links.new(inp.outputs["Subdivision"], has_detail.inputs[0])
    links.new(has_detail.outputs[0], silhouette_detail.inputs[0])
    links.new(inp.outputs["Silhouette Detail"], silhouette_detail.inputs[1])
    links.new(coarse_cut.outputs["Geometry"], adaptive_detail.inputs["Mesh"])
    links.new(silhouette_detail.outputs[0], adaptive_detail.inputs["Level"])
    remeshed = adaptive_detail.outputs["Mesh"]

    influence_visible = _math(group, "GREATER_THAN", "Crystal Influence Region", -1660, -360, value_2=1.0e-6)
    exact_region = _math(group, "MULTIPLY", "Crystal Exact Effect Region", -1420, -360)
    blur = _node(group, "GeometryNodeBlurAttribute", "Crystal Edge Distance Blur", -1420, -80)
    blur.data_type = "FLOAT"
    try:
        blur.domain = "POINT"
    except (AttributeError, TypeError, ValueError):
        pass
    distance_double = _math(group, "MULTIPLY", "Crystal Edge Distance Double", -1180, -80, value_2=2.0)
    distance_center = _math(group, "SUBTRACT", "Crystal Edge Distance Center", -940, -80, value_2=1.0)
    distance_low = _math(group, "MAXIMUM", "Crystal Edge Distance Minimum", -700, -80, value_2=0.0)
    edge_distance = _math(group, "MINIMUM", "Crystal Edge Distance", -460, -80, value_2=1.0)
    maximum_roundness = _math(group, "POWER", "Crystal Maximum Roundness", -1180, -320, value_2=2.2)
    inverse_roundness = _math(group, "SUBTRACT", "Crystal Flat Weight", -940, -420, value_1=1.0)
    flat_depth = _math(group, "MULTIPLY", "Crystal Flat Depth", -700, -360)
    curved_depth = _math(group, "MULTIPLY", "Crystal Curved Depth", -700, -220)
    rounded_depth = _math(group, "ADD", "Crystal Rounded Depth", -460, -160)
    has_roundness = _math(group, "GREATER_THAN", "Crystal Has Roundness", -460, -360, value_2=1.0e-6)
    roundness_switch = _node(group, "GeometryNodeSwitch", "Crystal Flat or Rounded", -220, -160)
    roundness_switch.input_type = "FLOAT"
    roundness_switch.inputs["False"].default_value = 1.0
    edge_missing = _math(group, "SUBTRACT", "Crystal Edge Missing", 20, -200, value_1=1.0)
    edge_pin_amount = _math(group, "MULTIPLY", "Crystal Edge Pin Amount", 260, -200)
    edge_pin_profile = _math(group, "SUBTRACT", "Crystal Edge Pin Profile", 500, -200, value_1=1.0)
    body_profile = _math(group, "MINIMUM", "Crystal Attached Body Profile", 740, -160)
    body_influence = _math(group, "MULTIPLY", "Crystal Masked Body Profile", 980, -160)
    links.new(effective_influence.outputs[0], influence_visible.inputs[0])
    links.new(alpha_visible.outputs[0], exact_region.inputs[0])
    links.new(influence_visible.outputs[0], exact_region.inputs[1])
    links.new(exact_region.outputs[0], blur.inputs["Value"])
    links.new(inp.outputs["Blur Iterations"], blur.inputs["Iterations"])
    links.new(blur.outputs["Value"], distance_double.inputs[0])
    links.new(distance_double.outputs[0], distance_center.inputs[0])
    links.new(distance_center.outputs[0], distance_low.inputs[0])
    links.new(distance_low.outputs[0], edge_distance.inputs[0])
    links.new(edge_distance.outputs[0], maximum_roundness.inputs[0])
    links.new(inp.outputs["Roundness"], inverse_roundness.inputs[1])
    flat_depth.inputs[0].default_value = 1.0
    links.new(inverse_roundness.outputs[0], flat_depth.inputs[1])
    links.new(maximum_roundness.outputs[0], curved_depth.inputs[0])
    links.new(inp.outputs["Roundness"], curved_depth.inputs[1])
    links.new(flat_depth.outputs[0], rounded_depth.inputs[0])
    links.new(curved_depth.outputs[0], rounded_depth.inputs[1])
    links.new(inp.outputs["Roundness"], has_roundness.inputs[0])
    links.new(has_roundness.outputs[0], roundness_switch.inputs["Switch"])
    links.new(rounded_depth.outputs[0], roundness_switch.inputs["True"])
    links.new(edge_distance.outputs[0], edge_missing.inputs[1])
    links.new(edge_missing.outputs[0], edge_pin_amount.inputs[0])
    links.new(inp.outputs["Edge Pinning"], edge_pin_amount.inputs[1])
    links.new(edge_pin_amount.outputs[0], edge_pin_profile.inputs[1])
    links.new(roundness_switch.outputs["Output"], body_profile.inputs[0])
    links.new(edge_pin_profile.outputs[0], body_profile.inputs[1])
    links.new(body_profile.outputs[0], body_influence.inputs[0])
    links.new(effective_influence.outputs[0], body_influence.inputs[1])

    coordinate_scale = _aspect_corrected_texture_coordinates(
        group,
        inp.outputs["Geometry"],
        named_uv.outputs["Attribute"],
        inp.outputs["Correct Aspect"],
        inp.outputs["Pattern Scale"],
        inp.outputs["Texture Scale X"],
        inp.outputs["Texture Scale Y"],
        prefix="Crystal",
        result_name="Crystal Pattern Scale",
        x=-2980,
        y=-600,
    )
    phase_vector = _node(group, "ShaderNodeCombineXYZ", "Crystal Phase Vector", -1420, -820)
    phase_y = _math(group, "MULTIPLY", "Crystal Phase Y", -1660, -900, value_2=0.754877666)
    phase_z = _math(group, "MULTIPLY", "Crystal Phase Z", -1660, -1000, value_2=-0.569840291)
    shifted = _vector_math(group, "ADD", "Crystal Animated Coordinates", -1180, -620)
    links.new(inp.outputs["Phase"], phase_vector.inputs["X"])
    links.new(inp.outputs["Phase"], phase_y.inputs[0])
    links.new(inp.outputs["Phase"], phase_z.inputs[0])
    links.new(phase_y.outputs[0], phase_vector.inputs["Y"])
    links.new(phase_z.outputs[0], phase_vector.inputs["Z"])
    links.new(coordinate_scale, shifted.inputs[0])
    links.new(phase_vector.outputs[0], shifted.inputs[1])

    edge_voronoi = _configure_voronoi(
        _node(group, "ShaderNodeTexVoronoi", "Crystal Diamond Voronoi", -920, -620),
        "DISTANCE_TO_EDGE",
    )
    cell_voronoi = _configure_voronoi(
        _node(group, "ShaderNodeTexVoronoi", "Crystal Mineral Voronoi", -920, -840),
        "F1",
    )
    liquid_voronoi = _configure_voronoi(
        _node(group, "ShaderNodeTexVoronoi", "Crystal Liquid Voronoi", -920, -1060),
        "SMOOTH_F1",
    )
    links.new(shifted.outputs[0], edge_voronoi.inputs["Vector"])
    links.new(shifted.outputs[0], cell_voronoi.inputs["Vector"])
    links.new(shifted.outputs[0], liquid_voronoi.inputs["Vector"])

    diamond_detail = _math(group, "MULTIPLY", "Crystal Diamond Detail", -660, -620)
    diamond = _math(group, "SUBTRACT", "Crystal Diamond Ridges", -420, -620, value_1=1.0)
    diamond.use_clamp = True
    crystal_detail = _math(group, "MULTIPLY", "Crystal Mineral Detail", -660, -820)
    crystal_wave = _math(group, "SINE", "Crystal Mineral Facets", -420, -820)
    crystal_half = _math(group, "MULTIPLY", "Crystal Mineral Half", -180, -820, value_2=0.5)
    crystal_pattern = _math(group, "ADD", "Crystal Mineral Pattern", 60, -820, value_2=0.5)
    liquid_detail = _math(group, "MULTIPLY", "Crystal Liquid Detail", -660, -1040)
    liquid_wave = _math(group, "SINE", "Crystal Liquid Flow", -420, -1040)
    liquid_half = _math(group, "MULTIPLY", "Crystal Liquid Half", -180, -1040, value_2=0.5)
    liquid_pattern = _math(group, "ADD", "Crystal Liquid Pattern", 60, -1040, value_2=0.5)
    links.new(edge_voronoi.outputs["Distance"], diamond_detail.inputs[0])
    links.new(inp.outputs["Pattern Detail"], diamond_detail.inputs[1])
    links.new(diamond_detail.outputs[0], diamond.inputs[1])
    links.new(cell_voronoi.outputs["Distance"], crystal_detail.inputs[0])
    links.new(inp.outputs["Pattern Detail"], crystal_detail.inputs[1])
    links.new(crystal_detail.outputs[0], crystal_wave.inputs[0])
    links.new(crystal_wave.outputs[0], crystal_half.inputs[0])
    links.new(crystal_half.outputs[0], crystal_pattern.inputs[0])
    links.new(liquid_voronoi.outputs["Distance"], liquid_detail.inputs[0])
    links.new(inp.outputs["Pattern Detail"], liquid_detail.inputs[1])
    links.new(liquid_detail.outputs[0], liquid_wave.inputs[0])
    links.new(liquid_wave.outputs[0], liquid_half.inputs[0])
    links.new(liquid_half.outputs[0], liquid_pattern.inputs[0])
    voronoi_pattern = _select_float_style(
        group,
        inp.outputs["Pattern Mode"],
        (diamond.outputs[0], crystal_pattern.outputs[0], liquid_pattern.outputs[0]),
        prefix="Crystal Pattern Mode",
        x=420,
        y=-760,
    )

    # Keep the established Voronoi shaping modes, but let artists replace the
    # generator entirely without editing the node group. All generators share
    # the aspect-correct coordinates and Phase animation contract.
    noise_texture = _node(group, "ShaderNodeTexNoise", "Crystal Fractal Noise", -660, -1260)
    noise_texture.noise_dimensions = "4D"
    noise_texture.inputs["Scale"].default_value = 1.0
    wave_texture = _node(group, "ShaderNodeTexWave", "Crystal Generated Bands", -420, -1260)
    wave_texture.wave_type = "RINGS"
    wave_texture.rings_direction = "Z"
    wave_texture.inputs["Scale"].default_value = 1.0
    wave_distortion = _math(group, "MULTIPLY", "Crystal Band Distortion", -660, -1420, value_2=0.15)
    brick_texture = _node(group, "ShaderNodeTexBrick", "Crystal Geometric Blocks", -180, -1260)
    brick_texture.inputs["Scale"].default_value = 1.0
    brick_texture.inputs["Mortar Size"].default_value = 0.08
    links.new(shifted.outputs[0], noise_texture.inputs["Vector"])
    links.new(inp.outputs["Phase"], noise_texture.inputs["W"])
    links.new(inp.outputs["Pattern Detail"], noise_texture.inputs["Detail"])
    links.new(shifted.outputs[0], wave_texture.inputs["Vector"])
    links.new(inp.outputs["Pattern Detail"], wave_distortion.inputs[0])
    links.new(wave_distortion.outputs[0], wave_texture.inputs["Distortion"])
    links.new(shifted.outputs[0], brick_texture.inputs["Vector"])
    pattern = _select_float_style(
        group,
        inp.outputs["Texture Type"],
        (
            voronoi_pattern,
            _output(noise_texture, "Fac", 1),
            _output(wave_texture, "Fac", 1),
            _output(brick_texture, "Fac", 1),
        ),
        prefix="Crystal Texture Generator",
        x=540,
        y=-1140,
    )

    body_depth = _math(group, "MULTIPLY", "Crystal Alpha Body Depth", -660, -180)
    pattern_centered = _math(group, "SUBTRACT", "Crystal Center Pattern", 820, -760, value_2=0.5)
    pattern_strength = _math(group, "MULTIPLY", "Crystal Pattern Height", 1060, -760)
    pattern_profile = _math(group, "MULTIPLY", "Crystal Attached Pattern Profile", 1060, -600)
    pattern_inside = _math(group, "MULTIPLY", "Crystal Pattern Inside Alpha", 1300, -760)
    total_depth = _math(group, "ADD", "Crystal Total Depth", 1540, -300)
    cell_randomizer = _node(group, "ShaderNodeTexWhiteNoise", "Crystal Cell Randomizer", 820, -980)
    cell_randomizer.noise_dimensions = "4D"
    random_center = _math(group, "SUBTRACT", "Crystal Center Cell Random", 1060, -980, value_2=0.5)
    random_double = _math(group, "MULTIPLY", "Crystal Signed Cell Random", 1300, -980, value_2=2.0)
    voronoi_generator = _math(group, "LESS_THAN", "Crystal Voronoi Random Gate", 1300, -1140, value_2=0.5)
    voronoi_randomness = _math(group, "MULTIPLY", "Crystal Voronoi Cell Randomness", 1540, -1140)
    random_amount = _math(group, "MULTIPLY", "Crystal Cell Random Amount", 1540, -980)
    random_factor = _math(group, "ADD", "Crystal Cell Height Factor", 1760, -980, value_2=1.0)
    randomized_depth = _math(group, "MULTIPLY", "Crystal Randomized Island Depth", 1780, -300)
    depth_vector = _node(group, "ShaderNodeCombineXYZ", "Crystal Depth Vector", 2000, -300)
    links.new(body_influence.outputs[0], body_depth.inputs[0])
    links.new(inp.outputs["Depth"], body_depth.inputs[1])
    links.new(pattern, pattern_centered.inputs[0])
    links.new(pattern_centered.outputs[0], pattern_strength.inputs[0])
    links.new(inp.outputs["Pattern Strength"], pattern_strength.inputs[1])
    links.new(edge_pin_profile.outputs[0], pattern_profile.inputs[0])
    links.new(effective_influence.outputs[0], pattern_profile.inputs[1])
    links.new(pattern_strength.outputs[0], pattern_inside.inputs[0])
    links.new(pattern_profile.outputs[0], pattern_inside.inputs[1])
    links.new(body_depth.outputs[0], total_depth.inputs[0])
    links.new(pattern_inside.outputs[0], total_depth.inputs[1])
    links.new(_output(cell_voronoi, "Color", 1), _input(cell_randomizer, "Vector", 0))
    links.new(inp.outputs["Cell Seed"], _input(cell_randomizer, "W", 1))
    links.new(_output(cell_randomizer, "Value", 1), random_center.inputs[0])
    links.new(random_center.outputs[0], random_double.inputs[0])
    links.new(inp.outputs["Texture Type"], voronoi_generator.inputs[0])
    links.new(inp.outputs["Cell Randomness"], voronoi_randomness.inputs[0])
    links.new(voronoi_generator.outputs[0], voronoi_randomness.inputs[1])
    links.new(random_double.outputs[0], random_amount.inputs[0])
    links.new(voronoi_randomness.outputs[0], random_amount.inputs[1])
    links.new(random_amount.outputs[0], random_factor.inputs[0])
    links.new(total_depth.outputs[0], randomized_depth.inputs[0])
    links.new(random_factor.outputs[0], randomized_depth.inputs[1])
    links.new(randomized_depth.outputs[0], depth_vector.inputs["Z"])

    store_color = _node(group, "GeometryNodeStoreNamedAttribute", "Store Crystal Source Color", -1180, 540)
    store_color.data_type = "FLOAT_COLOR"
    store_color.domain = "POINT"
    store_color.inputs["Name"].default_value = "fbp_crystal_color"
    store_depth = _node(group, "GeometryNodeStoreNamedAttribute", "Store Crystal Alpha Depth", -700, 540)
    store_depth.data_type = "FLOAT"
    store_depth.domain = "POINT"
    store_depth.inputs["Name"].default_value = "fbp_crystal_depth"
    store_influence = _node(group, "GeometryNodeStoreNamedAttribute", "Store Crystal Influence", -460, 540)
    store_influence.data_type = "FLOAT"
    store_influence.domain = "POINT"
    store_influence.inputs["Name"].default_value = "fbp_crystal_influence"
    store_pattern = _node(group, "GeometryNodeStoreNamedAttribute", "Store Crystal Pattern", -460, 540)
    store_pattern.data_type = "FLOAT"
    store_pattern.domain = "POINT"
    store_pattern.inputs["Name"].default_value = "fbp_crystal_pattern"
    links.new(remeshed, store_color.inputs["Geometry"])
    links.new(source.outputs["Color"], store_color.inputs["Value"])
    # The exact cutoff owns visibility. The AO-like edge-distance profile and
    # painted influence are stored independently; neither can reintroduce a
    # source-alpha opacity fade around the silhouette.
    links.new(store_color.outputs["Geometry"], store_depth.inputs["Geometry"])
    links.new(body_influence.outputs[0], store_depth.inputs["Value"])
    links.new(store_depth.outputs["Geometry"], store_influence.inputs["Geometry"])
    links.new(effective_influence.outputs[0], store_influence.inputs["Value"])
    links.new(store_influence.outputs["Geometry"], store_pattern.inputs["Geometry"])
    links.new(pattern, store_pattern.inputs["Value"])

    set_position = _node(group, "GeometryNodeSetPosition", "Shape Crystal From Alpha", -180, 540)
    transparent = _math(group, "LESS_THAN", "Crystal Outside Exact Alpha", 60, 160, value_2=0.5)
    delete = _node(group, "GeometryNodeDeleteGeometry", "Cut Crystal Silhouette", 80, 540)
    delete.domain = "FACE"
    links.new(store_pattern.outputs["Geometry"], set_position.inputs["Geometry"])
    links.new(depth_vector.outputs[0], set_position.inputs["Offset"])
    links.new(alpha_visible.outputs[0], transparent.inputs[0])
    links.new(set_position.outputs["Geometry"], delete.inputs["Geometry"])
    links.new(transparent.outputs[0], delete.inputs["Selection"])

    back_amount = _math(group, "MULTIPLY", "Crystal Back Thickness", 320, 120, value_2=-1.0)
    back_vector = _node(group, "ShaderNodeCombineXYZ", "Crystal Back Vector", 540, 120)
    extrude = _node(group, "GeometryNodeExtrudeMesh", "Close Crystal Volume", 340, 540)
    extrude.mode = "FACES"
    # The alpha silhouette is a single surface region. Per-face extrusion would
    # turn its subdivision grid into thousands of hidden cubes before the
    # Subdivision Surface node, producing the reported tiled/faceted result.
    individual = _input(extrude, "Individual")
    if individual is not None:
        individual.default_value = False
    links.new(inp.outputs["Thickness"], back_amount.inputs[0])
    # Keep the back shell at a uniform thickness.  Masking it to zero would
    # collapse the two caps onto each other in black influence-map regions and
    # create coincident faces.  The influence map controls the front relief and
    # the optical material there; a requested closed volume remains watertight.
    links.new(back_amount.outputs[0], back_vector.inputs["Z"])
    links.new(delete.outputs["Geometry"], extrude.inputs["Mesh"])
    links.new(back_vector.outputs[0], extrude.inputs["Offset"])

    # Preserve the original displaced alpha surface as the front cap. The
    # extrusion supplies only the opposite cap and silhouette walls; flipping
    # its Top selection and welding the rim makes a clean closed crystal volume
    # before Catmull-Clark subdivision is evaluated.
    flip_back = _node(group, "GeometryNodeFlipFaces", "Orient Crystal Back Cap", 600, 540)
    links.new(extrude.outputs["Mesh"], flip_back.inputs["Mesh"])
    links.new(extrude.outputs["Top"], flip_back.inputs["Selection"])
    join_volume = _node(group, "GeometryNodeJoinGeometry", "Assemble Crystal Volume", 840, 540)
    links.new(delete.outputs["Geometry"], join_volume.inputs["Geometry"])
    links.new(flip_back.outputs["Mesh"], join_volume.inputs["Geometry"])
    merge_rim = _node(group, "GeometryNodeMergeByDistance", "Weld Crystal Rim", 1080, 540)
    merge_rim.inputs["Distance"].default_value = 1.0e-6
    links.new(join_volume.outputs["Geometry"], merge_rim.inputs["Geometry"])

    has_volume = _math(group, "GREATER_THAN", "Crystal Has Back Volume", 1080, 280, value_2=1.0e-6)
    volume_switch = _node(group, "GeometryNodeSwitch", "Crystal Surface or Volume", 1320, 540)
    volume_switch.input_type = "GEOMETRY"
    links.new(inp.outputs["Thickness"], has_volume.inputs[0])
    links.new(has_volume.outputs[0], volume_switch.inputs["Switch"])
    links.new(delete.outputs["Geometry"], volume_switch.inputs["False"])
    links.new(merge_rim.outputs["Geometry"], volume_switch.inputs["True"])

    surface_subdivision = _node(group, "GeometryNodeSubdivisionSurface", "Round Crystal Surface", 1560, 540)
    links.new(volume_switch.outputs["Output"], surface_subdivision.inputs["Mesh"])
    links.new(inp.outputs["Surface Subdivision"], surface_subdivision.inputs["Level"])
    material = _node(group, "GeometryNodeSetMaterial", "Crystal Material", 1800, 540)
    smooth = _node(group, "GeometryNodeSetShadeSmooth", "Crystal Smooth Shading", 2040, 540)
    links.new(surface_subdivision.outputs["Mesh"], material.inputs["Geometry"])
    links.new(inp.outputs["Crystal Material"], material.inputs["Material"])
    links.new(material.outputs["Geometry"], smooth.inputs["Mesh"])
    links.new(inp.outputs["Shade Smooth"], smooth.inputs["Shade Smooth"])
    links.new(smooth.outputs["Mesh"], out.inputs["Geometry"])
    group["fbp_crystal_contract_version"] = 10
    group["fbp_image_geometry_contract_version"] = 2
    return group


def _create_surface_conform(name):
    """Conform a subdivided plane to the nearest points of a target mesh."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Target", "INPUT", "NodeSocketObject")
    _socket(group, "Subdivision", "INPUT", "NodeSocketInt", default=3, minimum=0, maximum=8)
    _socket(group, "Factor", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Offset", "INPUT", "NodeSocketFloat", default=0.002, minimum=-10.0, maximum=10.0)
    _socket(group, "Max Distance", "INPUT", "NodeSocketFloat", default=10.0, minimum=0.0, maximum=100000.0)
    _socket(group, "Shade Smooth", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    remeshed = _aspect_remesh(
        group, inp.outputs["Geometry"], inp.outputs["Subdivision"],
        prefix="Surface Conform", x=-4600, y=620, triangulate=True,
    )
    target = _node(group, "GeometryNodeObjectInfo", "Surface Conform Target", -1120, -80)
    try:
        target.transform_space = "RELATIVE"
    except (AttributeError, TypeError, ValueError):
        pass
    position = _node(group, "GeometryNodeInputPosition", "Surface Conform Source Position", -880, 40)
    sample_position = _node(group, "GeometryNodeSampleNearestSurface", "Sample Closest Target Position", -640, 80)
    sample_position.data_type = "FLOAT_VECTOR"
    target_size = _node(group, "GeometryNodeAttributeDomainSize", "Surface Conform Target Size", -640, -180)
    normal = _node(group, "GeometryNodeInputNormal", "Conformed Surface Normal", 900, -180)

    links.new(inp.outputs["Target"], target.inputs["Object"])
    links.new(target.outputs["Geometry"], sample_position.inputs["Mesh"])
    links.new(position.outputs["Position"], sample_position.inputs["Value"])
    links.new(position.outputs["Position"], sample_position.inputs["Sample Position"])
    links.new(target.outputs["Geometry"], target_size.inputs["Geometry"])

    delta = _vector_math(group, "SUBTRACT", "Surface Conform Delta", -400, 80)
    influence = _vector_math(group, "SCALE", "Surface Conform Influence", -180, 80)
    blended = _vector_math(group, "ADD", "Surface Conform Position", 40, 80)
    distance = _vector_math(group, "DISTANCE", "Surface Conform Distance", -400, -180)
    links.new(sample_position.outputs["Value"], delta.inputs[0])
    links.new(position.outputs["Position"], delta.inputs[1])
    links.new(delta.outputs[0], influence.inputs[0])
    links.new(inp.outputs["Factor"], influence.inputs[3])
    links.new(position.outputs["Position"], blended.inputs[0])
    links.new(influence.outputs[0], blended.inputs[1])
    links.new(sample_position.outputs["Value"], distance.inputs[0])
    links.new(position.outputs["Position"], distance.inputs[1])

    within_distance = _math(group, "LESS_THAN", "Surface Conform Within Distance", -180, -260)
    has_target_faces = _math(group, "GREATER_THAN", "Surface Conform Has Target Faces", -180, -400, value_2=0.5)
    valid = _node(group, "FunctionNodeBooleanMath", "Surface Conform Valid", 40, -260)
    valid.operation = "AND"
    links.new(distance.outputs["Value"], within_distance.inputs[0])
    links.new(inp.outputs["Max Distance"], within_distance.inputs[1])
    links.new(_output(target_size, "Face Count", 2), has_target_faces.inputs[0])
    links.new(has_target_faces.outputs[0], valid.inputs[0])
    links.new(within_distance.outputs[0], valid.inputs[1])

    set_position = _node(group, "GeometryNodeSetPosition", "Conform To Surface", 280, 300)
    normal_offset = _vector_math(group, "SCALE", "Surface Conform Normal Offset", 500, -140)
    offset_position = _node(group, "GeometryNodeSetPosition", "Offset Conformed Surface", 720, 300)
    smooth = _node(group, "GeometryNodeSetShadeSmooth", "Smooth Conformed Surface", 960, 300)
    links.new(remeshed, set_position.inputs["Geometry"])
    links.new(valid.outputs[0], set_position.inputs["Selection"])
    links.new(blended.outputs[0], set_position.inputs["Position"])
    links.new(normal.outputs["Normal"], normal_offset.inputs[0])
    links.new(inp.outputs["Offset"], normal_offset.inputs[3])
    links.new(set_position.outputs["Geometry"], offset_position.inputs["Geometry"])
    links.new(valid.outputs[0], offset_position.inputs["Selection"])
    links.new(normal_offset.outputs[0], offset_position.inputs["Offset"])
    links.new(offset_position.outputs["Geometry"], smooth.inputs["Geometry"])
    links.new(inp.outputs["Shade Smooth"], smooth.inputs["Shade Smooth"])
    links.new(smooth.outputs["Geometry"], out.inputs["Geometry"])
    group["fbp_surface_conform_contract_version"] = 2
    return group


def _create_accordion_fold(name):
    """Fold the source mesh with a UV-preserving triangular wave profile."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Subdivision", "INPUT", "NodeSocketInt", default=5, minimum=0, maximum=8)
    _socket(group, "Folds", "INPUT", "NodeSocketInt", default=8, minimum=1, maximum=256)
    _socket(group, "Depth", "INPUT", "NodeSocketFloat", default=0.06, minimum=-10.0, maximum=10.0)
    _socket(group, "Phase", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100000.0, maximum=100000.0)
    _socket(group, "Vertical", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Shade Smooth", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    remeshed = _aspect_remesh(
        group, inp.outputs["Geometry"], inp.outputs["Subdivision"],
        prefix="Accordion", x=-4600, y=660, triangulate=True,
    )
    bbox = _node(group, "GeometryNodeBoundBox", "Accordion Bounds", -1320, 40)
    size = _vector_math(group, "SUBTRACT", "Accordion Size", -1100, 40)
    separate_size = _node(group, "ShaderNodeSeparateXYZ", "Accordion Size Components", -880, 20)
    safe_x = _math(group, "MAXIMUM", "Accordion Safe Width", -660, 80, value_2=0.0001)
    safe_y = _math(group, "MAXIMUM", "Accordion Safe Height", -660, -80, value_2=0.0001)
    links.new(inp.outputs["Geometry"], bbox.inputs["Geometry"])
    links.new(bbox.outputs["Max"], size.inputs[0])
    links.new(bbox.outputs["Min"], size.inputs[1])
    links.new(size.outputs[0], separate_size.inputs[0])
    links.new(separate_size.outputs["X"], safe_x.inputs[0])
    links.new(separate_size.outputs["Y"], safe_y.inputs[0])

    position = _node(group, "GeometryNodeInputPosition", "Accordion Position", -880, -300)
    separate_position = _node(group, "ShaderNodeSeparateXYZ", "Accordion Position Components", -660, -300)
    coordinate = _node(group, "GeometryNodeSwitch", "Accordion Axis", -440, -220)
    coordinate.input_type = "FLOAT"
    dimension = _node(group, "GeometryNodeSwitch", "Accordion Dimension", -440, -20)
    dimension.input_type = "FLOAT"
    links.new(position.outputs["Position"], separate_position.inputs[0])
    links.new(inp.outputs["Vertical"], coordinate.inputs["Switch"])
    links.new(separate_position.outputs["X"], coordinate.inputs["False"])
    links.new(separate_position.outputs["Y"], coordinate.inputs["True"])
    links.new(inp.outputs["Vertical"], dimension.inputs["Switch"])
    links.new(safe_x.outputs[0], dimension.inputs["False"])
    links.new(safe_y.outputs[0], dimension.inputs["True"])

    normalized = _math(group, "DIVIDE", "Accordion Normalized Coordinate", -220, -180)
    cycles = _math(group, "MULTIPLY", "Accordion Cycles", 0, -180)
    radians = _math(group, "MULTIPLY", "Accordion Radians", 220, -180, value_2=6.283185307)
    phase = _math(group, "ADD", "Accordion Animated Phase", 440, -180)
    sine = _math(group, "SINE", "Accordion Sine", 660, -180)
    triangle = _math(group, "ARCSINE", "Accordion Triangle Wave", 880, -180)
    normalize_triangle = _math(group, "MULTIPLY", "Accordion Triangle Normalize", 1100, -180, value_2=0.636619772)
    amplitude = _math(group, "MULTIPLY", "Accordion Depth", 1320, -180)
    offset = _node(group, "ShaderNodeCombineXYZ", "Accordion Offset", 1540, -180)
    links.new(coordinate.outputs["Output"], normalized.inputs[0])
    links.new(dimension.outputs["Output"], normalized.inputs[1])
    links.new(normalized.outputs[0], cycles.inputs[0])
    links.new(inp.outputs["Folds"], cycles.inputs[1])
    links.new(cycles.outputs[0], radians.inputs[0])
    links.new(radians.outputs[0], phase.inputs[0])
    links.new(inp.outputs["Phase"], phase.inputs[1])
    links.new(phase.outputs[0], sine.inputs[0])
    links.new(sine.outputs[0], triangle.inputs[0])
    links.new(triangle.outputs[0], normalize_triangle.inputs[0])
    links.new(normalize_triangle.outputs[0], amplitude.inputs[0])
    links.new(inp.outputs["Depth"], amplitude.inputs[1])
    links.new(amplitude.outputs[0], offset.inputs["Z"])

    set_position = _node(group, "GeometryNodeSetPosition", "Fold Accordion", 1760, 360)
    smooth = _node(group, "GeometryNodeSetShadeSmooth", "Accordion Shading", 1980, 360)
    links.new(remeshed, set_position.inputs["Geometry"])
    links.new(offset.outputs[0], set_position.inputs["Offset"])
    links.new(set_position.outputs["Geometry"], smooth.inputs["Mesh"])
    links.new(inp.outputs["Shade Smooth"], smooth.inputs["Shade Smooth"])
    links.new(smooth.outputs["Mesh"], out.inputs["Geometry"])
    group["fbp_accordion_fold_contract_version"] = 2
    return group


def _normalized_plane_position(group, geometry_socket, *, prefix, x, y):
    """Return aspect-preserving centered coordinates for a planar geometry field."""
    bounds = _node(group, "GeometryNodeBoundBox", f"{prefix} Bounds", x, y)
    size = _vector_math(group, "SUBTRACT", f"{prefix} Size", x + 200, y - 80)
    center_sum = _vector_math(group, "ADD", f"{prefix} Center Sum", x + 200, y + 80)
    center = _vector_math(group, "SCALE", f"{prefix} Center", x + 400, y + 80)
    center.inputs["Scale"].default_value = 0.5
    position = _node(group, "GeometryNodeInputPosition", f"{prefix} Position", x + 200, y + 240)
    centered = _vector_math(group, "SUBTRACT", f"{prefix} Centered", x + 600, y + 180)
    diagonal = _vector_math(group, "LENGTH", f"{prefix} Diagonal", x + 400, y - 100)
    safe_diagonal = _math(group, "MAXIMUM", f"{prefix} Safe Diagonal", x + 600, y - 100, value_2=0.0001)
    reciprocal = _math(group, "DIVIDE", f"{prefix} Normalize Scale", x + 800, y - 100, value_1=1.0)
    normalized = _vector_math(group, "SCALE", f"{prefix} Normalized Position", x + 1000, y + 160)
    links = group.links
    links.new(geometry_socket, bounds.inputs["Geometry"])
    links.new(bounds.outputs["Max"], size.inputs[0])
    links.new(bounds.outputs["Min"], size.inputs[1])
    links.new(bounds.outputs["Max"], center_sum.inputs[0])
    links.new(bounds.outputs["Min"], center_sum.inputs[1])
    links.new(center_sum.outputs[0], center.inputs[0])
    links.new(position.outputs["Position"], centered.inputs[0])
    links.new(center.outputs[0], centered.inputs[1])
    links.new(size.outputs[0], diagonal.inputs[0])
    links.new(diagonal.outputs["Value"], safe_diagonal.inputs[0])
    links.new(safe_diagonal.outputs[0], reciprocal.inputs[1])
    links.new(centered.outputs[0], normalized.inputs[0])
    links.new(reciprocal.outputs[0], normalized.inputs["Scale"])
    return normalized.outputs["Vector"]


def _select_float_style(group, style_socket, candidates, *, prefix, x, y):
    """Select one float field with Blender's compact lazy index switch."""
    candidates = tuple(candidates or ())
    if not candidates:
        return None
    switch = _node(group, "GeometryNodeIndexSwitch", prefix, x, y)
    switch.data_type = "FLOAT"
    while len(switch.index_switch_items) < len(candidates):
        switch.index_switch_items.new()
    while len(switch.index_switch_items) > len(candidates):
        switch.index_switch_items.remove(switch.index_switch_items[-1])
    group.links.new(style_socket, switch.inputs[0])
    for index, candidate in enumerate(candidates, 1):
        group.links.new(candidate, switch.inputs[index])
    return switch.outputs[0]


def _create_sculpt_waves(name):
    """Create three UV-preserving artistic displacement styles in one effect."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Subdivision", "INPUT", "NodeSocketInt", default=5, minimum=0, maximum=8)
    _socket(group, "Style", "INPUT", "NodeSocketInt", default=0, minimum=0, maximum=2)
    _socket(group, "Amplitude", "INPUT", "NodeSocketFloat", default=0.08, minimum=-10.0, maximum=10.0)
    _socket(group, "Frequency", "INPUT", "NodeSocketFloat", default=5.0, minimum=0.01, maximum=1000.0)
    _socket(group, "Phase", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100000.0, maximum=100000.0)
    _socket(group, "Edge Falloff", "INPUT", "NodeSocketFloat", default=0.35, minimum=0.0, maximum=1.0)
    _socket(group, "Shade Smooth", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    remeshed = _aspect_remesh(
        group, inp.outputs["Geometry"], inp.outputs["Subdivision"],
        prefix="Sculpt Waves", x=-4600, y=680, triangulate=True,
    )
    normalized = _normalized_plane_position(
        group, remeshed, prefix="Sculpt Waves", x=-1800, y=-40
    )
    separate = _node(group, "ShaderNodeSeparateXYZ", "Sculpt Waves Coordinates", -520, 140)
    radial = _vector_math(group, "LENGTH", "Sculpt Waves Radius", -520, -80)
    links.new(normalized, separate.inputs[0])
    links.new(normalized, radial.inputs[0])

    angular_scale = _math(group, "MULTIPLY", "Sculpt Waves Angular Frequency", -300, -260, value_2=6.283185307)
    links.new(inp.outputs["Frequency"], angular_scale.inputs[0])

    radial_argument = _math(group, "MULTIPLY", "Sculpt Waves Radial Argument", -80, -80)
    radial_phase = _math(group, "ADD", "Sculpt Waves Radial Phase", 140, -80)
    radial_wave = _math(group, "SINE", "Sculpt Waves Radial", 360, -80)
    links.new(radial.outputs["Value"], radial_argument.inputs[0])
    links.new(angular_scale.outputs[0], radial_argument.inputs[1])
    links.new(radial_argument.outputs[0], radial_phase.inputs[0])
    links.new(inp.outputs["Phase"], radial_phase.inputs[1])
    links.new(radial_phase.outputs[0], radial_wave.inputs[0])

    x_argument = _math(group, "MULTIPLY", "Sculpt Waves Moire X Argument", -80, 220)
    y_argument = _math(group, "MULTIPLY", "Sculpt Waves Moire Y Argument", -80, 380)
    x_phase = _math(group, "ADD", "Sculpt Waves Moire X Phase", 140, 220)
    y_phase = _math(group, "SUBTRACT", "Sculpt Waves Moire Y Phase", 140, 380)
    x_sine = _math(group, "SINE", "Sculpt Waves Moire X", 360, 220)
    y_sine = _math(group, "SINE", "Sculpt Waves Moire Y", 360, 380)
    moire = _math(group, "MULTIPLY", "Sculpt Waves Moire", 580, 300)
    links.new(separate.outputs["X"], x_argument.inputs[0])
    links.new(angular_scale.outputs[0], x_argument.inputs[1])
    links.new(separate.outputs["Y"], y_argument.inputs[0])
    links.new(angular_scale.outputs[0], y_argument.inputs[1])
    links.new(x_argument.outputs[0], x_phase.inputs[0])
    links.new(inp.outputs["Phase"], x_phase.inputs[1])
    links.new(y_argument.outputs[0], y_phase.inputs[0])
    links.new(inp.outputs["Phase"], y_phase.inputs[1])
    links.new(x_phase.outputs[0], x_sine.inputs[0])
    links.new(y_phase.outputs[0], y_sine.inputs[0])
    links.new(x_sine.outputs[0], moire.inputs[0])
    links.new(y_sine.outputs[0], moire.inputs[1])

    angle = _math(group, "ARCTAN2", "Sculpt Waves Spiral Angle", -80, -460)
    arms = _math(group, "MULTIPLY", "Sculpt Waves Spiral Arms", 140, -460, value_2=3.0)
    spiral_base = _math(group, "ADD", "Sculpt Waves Spiral Base", 360, -380)
    spiral_phase = _math(group, "ADD", "Sculpt Waves Spiral Phase", 580, -380)
    spiral = _math(group, "SINE", "Sculpt Waves Spiral", 800, -380)
    links.new(separate.outputs["Y"], angle.inputs[0])
    links.new(separate.outputs["X"], angle.inputs[1])
    links.new(angle.outputs[0], arms.inputs[0])
    links.new(radial_argument.outputs[0], spiral_base.inputs[0])
    links.new(arms.outputs[0], spiral_base.inputs[1])
    links.new(spiral_base.outputs[0], spiral_phase.inputs[0])
    links.new(inp.outputs["Phase"], spiral_phase.inputs[1])
    links.new(spiral_phase.outputs[0], spiral.inputs[0])

    selected = _select_float_style(
        group,
        inp.outputs["Style"],
        (radial_wave.outputs[0], moire.outputs[0], spiral.outputs[0]),
        prefix="Sculpt Waves",
        x=800,
        y=180,
    )
    edge_distance = _math(group, "SUBTRACT", "Sculpt Waves Edge Distance", 580, -600, value_1=0.55)
    edge_gain = _math(group, "MULTIPLY", "Sculpt Waves Edge Gain", 800, -600, value_2=8.0)
    edge_min = _math(group, "MAXIMUM", "Sculpt Waves Edge Minimum", 1020, -600, value_2=0.0)
    edge_fade = _math(group, "MINIMUM", "Sculpt Waves Edge Fade", 1240, -600, value_2=1.0)
    inverse_falloff = _math(group, "SUBTRACT", "Sculpt Waves No Falloff", 1020, -760, value_1=1.0)
    weighted_fade = _math(group, "MULTIPLY", "Sculpt Waves Weighted Falloff", 1240, -760)
    falloff = _math(group, "ADD", "Sculpt Waves Falloff", 1460, -660)
    displacement = _math(group, "MULTIPLY", "Sculpt Waves Shape", 1460, 80)
    displacement_with_falloff = _math(group, "MULTIPLY", "Sculpt Waves Edge Shape", 1680, 80)
    amplitude = _math(group, "MULTIPLY", "Sculpt Waves Displacement", 1900, 80)
    offset = _node(group, "ShaderNodeCombineXYZ", "Sculpt Waves Offset", 2120, 80)
    set_position = _node(group, "GeometryNodeSetPosition", "Sculpt Waves Surface", 2340, 420)
    smooth = _node(group, "GeometryNodeSetShadeSmooth", "Smooth Sculpt Waves", 2560, 420)
    links.new(radial.outputs["Value"], edge_distance.inputs[1])
    links.new(edge_distance.outputs[0], edge_gain.inputs[0])
    links.new(edge_gain.outputs[0], edge_min.inputs[0])
    links.new(edge_min.outputs[0], edge_fade.inputs[0])
    links.new(inp.outputs["Edge Falloff"], inverse_falloff.inputs[1])
    links.new(edge_fade.outputs[0], weighted_fade.inputs[0])
    links.new(inp.outputs["Edge Falloff"], weighted_fade.inputs[1])
    links.new(inverse_falloff.outputs[0], falloff.inputs[0])
    links.new(weighted_fade.outputs[0], falloff.inputs[1])
    links.new(selected, displacement.inputs[0])
    displacement.inputs[1].default_value = 1.0
    links.new(displacement.outputs[0], displacement_with_falloff.inputs[0])
    links.new(falloff.outputs[0], displacement_with_falloff.inputs[1])
    links.new(displacement_with_falloff.outputs[0], amplitude.inputs[0])
    links.new(inp.outputs["Amplitude"], amplitude.inputs[1])
    links.new(amplitude.outputs[0], offset.inputs["Z"])
    links.new(remeshed, set_position.inputs["Geometry"])
    links.new(offset.outputs[0], set_position.inputs["Offset"])
    links.new(set_position.outputs["Geometry"], smooth.inputs["Geometry"])
    links.new(inp.outputs["Shade Smooth"], smooth.inputs["Shade Smooth"])
    links.new(smooth.outputs["Geometry"], out.inputs["Geometry"])
    group["fbp_sculpt_waves_contract_version"] = 2
    return group


def _create_kinetic_tiles(name):
    """Split the source into UV-preserving tiles with three animated patterns."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Subdivision", "INPUT", "NodeSocketInt", default=3, minimum=0, maximum=7)
    _socket(group, "Pattern", "INPUT", "NodeSocketInt", default=0, minimum=0, maximum=2)
    _socket(group, "Gap", "INPUT", "NodeSocketFloat", default=0.08, minimum=0.0, maximum=0.95)
    _socket(group, "Thickness", "INPUT", "NodeSocketFloat", default=0.02, minimum=-10.0, maximum=10.0)
    _socket(group, "Motion", "INPUT", "NodeSocketFloat", default=0.04, minimum=-10.0, maximum=10.0)
    _socket(group, "Frequency", "INPUT", "NodeSocketFloat", default=6.0, minimum=0.01, maximum=1000.0)
    _socket(group, "Phase", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100000.0, maximum=100000.0)
    _socket(group, "Shade Smooth", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    remeshed = _aspect_remesh(
        group, inp.outputs["Geometry"], inp.outputs["Subdivision"],
        prefix="Kinetic Tiles", x=-4600, y=680, triangulate=False,
    )
    split = _node(group, "GeometryNodeSplitEdges", "Split Kinetic Tiles", -1580, 420)
    scale = _node(group, "GeometryNodeScaleElements", "Kinetic Tiles Gap", -1360, 420)
    scale.domain = "FACE"
    tile_scale = _math(group, "SUBTRACT", "Kinetic Tiles Scale", -1580, 100, value_1=1.0)
    links.new(remeshed, split.inputs["Mesh"])
    links.new(split.outputs["Mesh"], scale.inputs["Geometry"])
    links.new(inp.outputs["Gap"], tile_scale.inputs[1])
    links.new(tile_scale.outputs[0], scale.inputs["Scale"])

    normalized = _normalized_plane_position(
        group, remeshed, prefix="Kinetic Tiles", x=-1800, y=-520
    )
    separate = _node(group, "ShaderNodeSeparateXYZ", "Kinetic Tiles Coordinates", -520, -320)
    radial = _vector_math(group, "LENGTH", "Kinetic Tiles Radius", -520, -500)
    angular_scale = _math(group, "MULTIPLY", "Kinetic Tiles Angular Frequency", -300, -680, value_2=6.283185307)
    links.new(normalized, separate.inputs[0])
    links.new(normalized, radial.inputs[0])
    links.new(inp.outputs["Frequency"], angular_scale.inputs[0])

    diagonal_sum = _math(group, "ADD", "Kinetic Tiles Diagonal", -300, -240)
    diagonal_argument = _math(group, "MULTIPLY", "Kinetic Tiles Wave Argument", -80, -240)
    diagonal_phase = _math(group, "ADD", "Kinetic Tiles Wave Phase", 140, -240)
    wave = _math(group, "SINE", "Kinetic Tiles Wave", 360, -240)
    links.new(separate.outputs["X"], diagonal_sum.inputs[0])
    links.new(separate.outputs["Y"], diagonal_sum.inputs[1])
    links.new(diagonal_sum.outputs[0], diagonal_argument.inputs[0])
    links.new(angular_scale.outputs[0], diagonal_argument.inputs[1])
    links.new(diagonal_argument.outputs[0], diagonal_phase.inputs[0])
    links.new(inp.outputs["Phase"], diagonal_phase.inputs[1])
    links.new(diagonal_phase.outputs[0], wave.inputs[0])

    checker_x_argument = _math(group, "MULTIPLY", "Kinetic Tiles Checker X Argument", -80, 40)
    checker_y_argument = _math(group, "MULTIPLY", "Kinetic Tiles Checker Y Argument", -80, 180)
    checker_x_phase = _math(group, "ADD", "Kinetic Tiles Checker X Phase", 140, 40)
    checker_y_phase = _math(group, "ADD", "Kinetic Tiles Checker Y Phase", 140, 180)
    checker_x = _math(group, "SINE", "Kinetic Tiles Checker X", 360, 40)
    checker_y = _math(group, "SINE", "Kinetic Tiles Checker Y", 360, 180)
    checker = _math(group, "MULTIPLY", "Kinetic Tiles Checker", 580, 100)
    links.new(separate.outputs["X"], checker_x_argument.inputs[0])
    links.new(angular_scale.outputs[0], checker_x_argument.inputs[1])
    links.new(separate.outputs["Y"], checker_y_argument.inputs[0])
    links.new(angular_scale.outputs[0], checker_y_argument.inputs[1])
    links.new(checker_x_argument.outputs[0], checker_x_phase.inputs[0])
    links.new(inp.outputs["Phase"], checker_x_phase.inputs[1])
    links.new(checker_y_argument.outputs[0], checker_y_phase.inputs[0])
    links.new(inp.outputs["Phase"], checker_y_phase.inputs[1])
    links.new(checker_x_phase.outputs[0], checker_x.inputs[0])
    links.new(checker_y_phase.outputs[0], checker_y.inputs[0])
    links.new(checker_x.outputs[0], checker.inputs[0])
    links.new(checker_y.outputs[0], checker.inputs[1])

    ripple_argument = _math(group, "MULTIPLY", "Kinetic Tiles Ripple Argument", -80, -500)
    ripple_phase = _math(group, "SUBTRACT", "Kinetic Tiles Ripple Phase", 140, -500)
    ripple = _math(group, "SINE", "Kinetic Tiles Ripple", 360, -500)
    links.new(radial.outputs["Value"], ripple_argument.inputs[0])
    links.new(angular_scale.outputs[0], ripple_argument.inputs[1])
    links.new(ripple_argument.outputs[0], ripple_phase.inputs[0])
    links.new(inp.outputs["Phase"], ripple_phase.inputs[1])
    links.new(ripple_phase.outputs[0], ripple.inputs[0])

    selected = _select_float_style(
        group,
        inp.outputs["Pattern"],
        (wave.outputs[0], checker.outputs[0], ripple.outputs[0]),
        prefix="Kinetic Tiles",
        x=800,
        y=-80,
    )
    absolute_motion = _math(group, "ABSOLUTE", "Kinetic Tiles Absolute Motion", 1020, -340)
    has_motion = _math(group, "GREATER_THAN", "Kinetic Tiles Motion Enabled", 1240, -340, value_2=0.000001)
    pattern_switch = _node(group, "GeometryNodeSwitch", "Kinetic Tiles Animated Pattern", 1240, -220)
    pattern_switch.input_type = "FLOAT"
    motion = _math(group, "MULTIPLY", "Kinetic Tiles Motion", 1240, -180)
    depth = _math(group, "ADD", "Kinetic Tiles Depth", 1460, -100)
    extrude = _node(group, "GeometryNodeExtrudeMesh", "Extrude Kinetic Tiles", 1680, 420)
    extrude.mode = "FACES"
    extrude.inputs["Individual"].default_value = True
    smooth = _node(group, "GeometryNodeSetShadeSmooth", "Smooth Kinetic Tiles", 1900, 420)
    links.new(inp.outputs["Motion"], absolute_motion.inputs[0])
    links.new(absolute_motion.outputs[0], has_motion.inputs[0])
    links.new(has_motion.outputs[0], pattern_switch.inputs["Switch"])
    pattern_switch.inputs["False"].default_value = 0.0
    links.new(selected, pattern_switch.inputs["True"])
    links.new(pattern_switch.outputs["Output"], motion.inputs[0])
    links.new(inp.outputs["Motion"], motion.inputs[1])
    links.new(inp.outputs["Thickness"], depth.inputs[0])
    links.new(motion.outputs[0], depth.inputs[1])
    links.new(scale.outputs["Geometry"], extrude.inputs["Mesh"])
    links.new(depth.outputs[0], extrude.inputs["Offset Scale"])
    links.new(extrude.outputs["Mesh"], smooth.inputs["Geometry"])
    links.new(inp.outputs["Shade Smooth"], smooth.inputs["Shade Smooth"])
    links.new(smooth.outputs["Geometry"], out.inputs["Geometry"])
    group["fbp_kinetic_tiles_contract_version"] = 2
    group["fbp_image_geometry_contract_version"] = 1
    return group


def _create_layered_echo(name):
    """Build a textured 3D array from shared, unrealized source instances."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Layers", "INPUT", "NodeSocketInt", default=8, minimum=1, maximum=512)
    _socket(group, "Offset X", "INPUT", "NodeSocketFloat", default=0.0, minimum=-10.0, maximum=10.0)
    _socket(group, "Offset Y", "INPUT", "NodeSocketFloat", default=0.0, minimum=-10.0, maximum=10.0)
    _socket(group, "Spacing", "INPUT", "NodeSocketFloat", default=0.025, minimum=-10.0, maximum=10.0)
    _socket(group, "Scale Step", "INPUT", "NodeSocketFloat", default=-0.025, minimum=-10.0, maximum=10.0)
    _socket(group, "Rotation X", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100.0, maximum=100.0)
    _socket(group, "Rotation Y", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100.0, maximum=100.0)
    _socket(group, "Twist", "INPUT", "NodeSocketFloat", default=0.08, minimum=-100.0, maximum=100.0)
    _socket(group, "Wave", "INPUT", "NodeSocketFloat", default=0.12, minimum=-6.283185307, maximum=6.283185307)
    _socket(group, "Phase", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100000.0, maximum=100000.0)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    offset = _node(group, "ShaderNodeCombineXYZ", "Array Layer Offset", -1100, 300)
    line = _node(group, "GeometryNodeMeshLine", "Array Layer Points", -880, 300)
    line.mode = "OFFSET"
    links.new(inp.outputs["Offset X"], offset.inputs["X"])
    links.new(inp.outputs["Offset Y"], offset.inputs["Y"])
    links.new(inp.outputs["Spacing"], offset.inputs["Z"])
    links.new(inp.outputs["Layers"], line.inputs["Count"])
    links.new(offset.outputs[0], line.inputs["Offset"])

    index = _node(group, "GeometryNodeInputIndex", "Array Layer Index", -880, -40)
    scale_delta = _math(group, "MULTIPLY", "Array Scale Delta", -660, 20)
    scale_value = _math(group, "ADD", "Array Scale", -440, 20, value_2=1.0)
    safe_scale = _math(group, "MAXIMUM", "Array Safe Scale", -220, 20, value_2=0.01)
    scale_vector = _node(group, "ShaderNodeCombineXYZ", "Array Scale Vector", 0, 20)
    links.new(index.outputs["Index"], scale_delta.inputs[0])
    links.new(inp.outputs["Scale Step"], scale_delta.inputs[1])
    links.new(scale_delta.outputs[0], scale_value.inputs[0])
    links.new(scale_value.outputs[0], safe_scale.inputs[0])
    for axis in ("X", "Y", "Z"):
        links.new(safe_scale.outputs[0], scale_vector.inputs[axis])

    base_twist = _math(group, "MULTIPLY", "Array Base Twist", -660, -220)
    rotation_x = _math(group, "MULTIPLY", "Array Rotation X", -440, -80)
    rotation_y = _math(group, "MULTIPLY", "Array Rotation Y", -220, -80)
    wave_position = _math(group, "MULTIPLY", "Array Wave Position", -660, -380, value_2=0.85)
    wave_phase = _math(group, "ADD", "Array Wave Phase", -440, -380)
    wave_sine = _math(group, "SINE", "Array Wave Sine", -220, -380)
    wave_amount = _math(group, "MULTIPLY", "Array Wave Amount", 0, -380)
    angle = _math(group, "ADD", "Array Rotation Angle", 220, -260)
    euler = _node(group, "ShaderNodeCombineXYZ", "Array Euler", 440, -260)
    rotation = _node(group, "FunctionNodeEulerToRotation", "Array Rotation", 660, -260)
    links.new(index.outputs["Index"], base_twist.inputs[0])
    links.new(inp.outputs["Twist"], base_twist.inputs[1])
    links.new(index.outputs["Index"], rotation_x.inputs[0])
    links.new(inp.outputs["Rotation X"], rotation_x.inputs[1])
    links.new(index.outputs["Index"], rotation_y.inputs[0])
    links.new(inp.outputs["Rotation Y"], rotation_y.inputs[1])
    links.new(index.outputs["Index"], wave_position.inputs[0])
    links.new(wave_position.outputs[0], wave_phase.inputs[0])
    links.new(inp.outputs["Phase"], wave_phase.inputs[1])
    links.new(wave_phase.outputs[0], wave_sine.inputs[0])
    links.new(wave_sine.outputs[0], wave_amount.inputs[0])
    links.new(inp.outputs["Wave"], wave_amount.inputs[1])
    links.new(base_twist.outputs[0], angle.inputs[0])
    links.new(wave_amount.outputs[0], angle.inputs[1])
    links.new(rotation_x.outputs[0], euler.inputs["X"])
    links.new(rotation_y.outputs[0], euler.inputs["Y"])
    links.new(angle.outputs[0], euler.inputs["Z"])
    links.new(euler.outputs[0], rotation.inputs["Euler"])

    instance = _node(group, "GeometryNodeInstanceOnPoints", "Instance Array", 900, 300)
    links.new(line.outputs["Mesh"], instance.inputs["Points"])
    links.new(inp.outputs["Geometry"], instance.inputs["Instance"])
    links.new(rotation.outputs["Rotation"], instance.inputs["Rotation"])
    links.new(scale_vector.outputs[0], instance.inputs["Scale"])
    links.new(instance.outputs["Instances"], out.inputs["Geometry"])
    group["fbp_instancing_contract_version"] = 1
    group["fbp_layered_echo_contract_version"] = 1
    return group


def _create_cutout_outline(name):
    """Generate an alpha-derived outline with a Blender-version-safe graph."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Alpha Resolution", "INPUT", "NodeSocketInt", default=4, minimum=0, maximum=8)
    _socket(group, "Alpha Threshold", "INPUT", "NodeSocketFloat", default=0.05, minimum=0.0, maximum=1.0)
    _socket(group, "Outline Width", "INPUT", "NodeSocketFloat", default=0.012, minimum=0.00001, maximum=10.0)
    _socket(group, "Offset", "INPUT", "NodeSocketFloat", default=0.001, minimum=-10.0, maximum=10.0)
    _socket(group, "Show Image", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Wiggle Amount", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=10.0)
    _socket(group, "Wiggle Scale", "INPUT", "NodeSocketFloat", default=8.0, minimum=0.01, maximum=1000.0)
    _socket(group, "Wiggle Phase", "INPUT", "NodeSocketFloat", default=0.0, minimum=-100000.0, maximum=100000.0)
    _socket(group, "Outline Material", "INPUT", "NodeSocketMaterial")
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    def link(output_socket, input_socket):
        if output_socket is None or input_socket is None:
            return False
        try:
            links.new(output_socket, input_socket)
            return True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    masked_geometry, _image_texture = _alpha_geometry_mask(
        group, inp, prefix="Cutout Alpha", x=-1760, y=320
    )

    edge_neighbors = _node(
        group, "GeometryNodeInputMeshEdgeNeighbors", "Cutout Edge Neighbors", -760, -40
    )
    boundary = _math(
        group, "COMPARE", "Cutout Boundary Edges", -560, -20, value_2=1.0
    )
    try:
        if len(boundary.inputs) > 2:
            boundary.inputs[2].default_value = 0.1
    except (AttributeError, IndexError, TypeError, ValueError):
        pass
    mesh_to_curve = _node(
        group, "GeometryNodeMeshToCurve", "Cutout Boundary Curve", -340, 260
    )
    link(_output(edge_neighbors, "Face Count", 0), _input(boundary, "Value", 0))
    link(masked_geometry, _input(mesh_to_curve, "Mesh", 0))
    link(_output(boundary, "Value", 0), _input(mesh_to_curve, "Selection", 1))

    # Use two scalar noise samples instead of color-channel socket indexing.
    # This avoids socket-layout differences between Blender builds while still
    # producing independent X/Y displacement controlled by one Evolution phase.
    spline_parameter = _node(
        group, "GeometryNodeSplineParameter", "Cutout Spline Parameter", -340, -150
    )
    noise_vector = _node(
        group, "ShaderNodeCombineXYZ", "Cutout Wiggle Coordinate", -120, -210
    )
    noise_x = _node(group, "ShaderNodeTexNoise", "Cutout Wiggle X", 100, -150)
    noise_y = _node(group, "ShaderNodeTexNoise", "Cutout Wiggle Y", 100, -350)
    for noise in (noise_x, noise_y):
        try:
            noise.noise_dimensions = "4D"
        except (AttributeError, TypeError, ValueError):
            pass
    phase_y = _math(group, "ADD", "Cutout Wiggle Y Phase", -120, -430, value_2=17.0)
    center_x = _math(group, "SUBTRACT", "Center Cutout Wiggle X", 330, -130, value_2=0.5)
    center_y = _math(group, "SUBTRACT", "Center Cutout Wiggle Y", 330, -330, value_2=0.5)
    signed_x = _math(group, "MULTIPLY", "Signed Cutout Wiggle X", 520, -130, value_2=2.0)
    signed_y = _math(group, "MULTIPLY", "Signed Cutout Wiggle Y", 520, -330, value_2=2.0)
    amount_x = _math(group, "MULTIPLY", "Cutout Wiggle Amount X", 710, -130)
    amount_y = _math(group, "MULTIPLY", "Cutout Wiggle Amount Y", 710, -330)
    offset_xy = _node(group, "ShaderNodeCombineXYZ", "Cutout Wiggle Offset", 900, -220)
    wiggle = _node(group, "GeometryNodeSetPosition", "Wiggle Cutout Outline", 1090, 230)

    link(_output(spline_parameter, "Factor", 0), _input(noise_vector, "X", 0))
    for noise in (noise_x, noise_y):
        link(_output(noise_vector, "Vector", 0), _input(noise, "Vector", 0))
        link(inp.outputs.get("Wiggle Scale"), _input(noise, "Scale"))
    link(inp.outputs.get("Wiggle Phase"), _input(noise_x, "W"))
    link(inp.outputs.get("Wiggle Phase"), _input(phase_y, "Value", 0))
    link(_output(phase_y, "Value", 0), _input(noise_y, "W"))
    link(_output(noise_x, "Fac", 0), _input(center_x, "Value", 0))
    link(_output(noise_y, "Fac", 0), _input(center_y, "Value", 0))
    link(_output(center_x, "Value", 0), _input(signed_x, "Value", 0))
    link(_output(center_y, "Value", 0), _input(signed_y, "Value", 0))
    link(_output(signed_x, "Value", 0), _input(amount_x, "Value", 0))
    link(_output(signed_y, "Value", 0), _input(amount_y, "Value", 0))
    link(inp.outputs.get("Wiggle Amount"), _input(amount_x, "Value", 1))
    link(inp.outputs.get("Wiggle Amount"), _input(amount_y, "Value", 1))
    link(_output(amount_x, "Value", 0), _input(offset_xy, "X", 0))
    link(_output(amount_y, "Value", 0), _input(offset_xy, "Y", 1))
    link(_output(mesh_to_curve, "Curve", 0), _input(wiggle, "Geometry", 0))
    link(_output(offset_xy, "Vector", 0), _input(wiggle, "Offset"))

    profile = _node(
        group, "GeometryNodeCurvePrimitiveCircle", "Cutout Outline Profile", 760, -500
    )
    try:
        profile.mode = "RADIUS"
    except (AttributeError, TypeError, ValueError):
        pass
    resolution_input = _input(profile, "Resolution")
    if resolution_input is not None:
        try:
            resolution_input.default_value = 6
        except (AttributeError, TypeError, ValueError):
            pass
    curve_to_mesh = _node(
        group, "GeometryNodeCurveToMesh", "Cutout Outline Mesh", 1300, 220
    )
    set_material = _node(
        group, "GeometryNodeSetMaterial", "Cutout Outline Material", 1510, 220
    )
    z_offset = _node(
        group, "ShaderNodeCombineXYZ", "Cutout Outline Offset", 1510, -30
    )
    set_position = _node(
        group, "GeometryNodeSetPosition", "Offset Cutout Outline", 1720, 220
    )
    image_switch = _node(
        group, "GeometryNodeSwitch", "Show Source Image", 1720, 450
    )
    try:
        image_switch.input_type = "GEOMETRY"
    except (AttributeError, TypeError, ValueError):
        pass
    join = _node(group, "GeometryNodeJoinGeometry", "Join Plane and Outline", 1950, 310)

    link(_output(wiggle, "Geometry", 0), _input(curve_to_mesh, "Curve", 0))
    link(_output(profile, "Curve", 0), _input(curve_to_mesh, "Profile Curve", 1))
    link(inp.outputs.get("Outline Width"), _input(profile, "Radius"))
    link(_output(curve_to_mesh, "Mesh", 0), _input(set_material, "Geometry", 0))
    link(inp.outputs.get("Outline Material"), _input(set_material, "Material"))
    link(inp.outputs.get("Offset"), _input(z_offset, "Z", 2))
    link(_output(set_material, "Geometry", 0), _input(set_position, "Geometry", 0))
    link(_output(z_offset, "Vector", 0), _input(set_position, "Offset"))
    link(inp.outputs.get("Show Image"), _input(image_switch, "Switch"))
    link(inp.outputs.get("Geometry"), _input(image_switch, "True"))
    link(_output(image_switch, "Output", 0), _input(join, "Geometry", 0))
    link(_output(set_position, "Geometry", 0), _input(join, "Geometry", 0))
    link(_output(join, "Geometry", 0), out.inputs.get("Geometry"))

    group["fbp_quality_contract_version"] = 1
    group["fbp_alpha_geometry_contract_version"] = 2
    group["fbp_cutout_outline_version"] = 6
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
    _socket(group, "Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Array Count", "INPUT", "NodeSocketInt", default=12, minimum=2, maximum=128)
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
    # disappear on some Blender 5.2 configurations.
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

    # Fake Array mode repeats the complete textured plane through the requested
    # depth. This is intentionally different from true side-wall extrusion and
    # is useful for graphic stacked-card or cel-layer thickness.
    safe_array_count = _math(group, "MAXIMUM", "Safe Extrude Array Count", 160, -520, value_2=2.0)
    array_denominator = _math(group, "SUBTRACT", "Extrude Array Divisions", 340, -520, value_2=1.0)
    array_spacing = _math(group, "DIVIDE", "Extrude Array Spacing", 520, -520)
    array_offset = _node(group, "ShaderNodeCombineXYZ", "Extrude Array Offset", 700, -520)
    mesh_line = _node(group, "GeometryNodeMeshLine", "Extrude Array Points", 880, -420)
    try:
        mesh_line.mode = "OFFSET"
    except (AttributeError, TypeError, ValueError):
        pass
    geometry_instance = _node(group, "GeometryNodeGeometryToInstance", "Extrude Plane Instance", 880, -650)
    instance_on_points = _node(group, "GeometryNodeInstanceOnPoints", "Extrude Plane Array", 1120, -420)
    realize_array = _node(group, "GeometryNodeRealizeInstances", "Realize Extrude Array", 1360, -420)
    links.new(inp.outputs["Array Count"], safe_array_count.inputs[0])
    links.new(safe_array_count.outputs[0], array_denominator.inputs[0])
    links.new(signed_thickness.outputs[0], array_spacing.inputs[0])
    links.new(array_denominator.outputs[0], array_spacing.inputs[1])
    links.new(array_spacing.outputs[0], array_offset.inputs["Z"])
    links.new(safe_array_count.outputs[0], _input(mesh_line, "Count", 0))
    links.new(array_offset.outputs[0], _input(mesh_line, "Offset", 2))
    links.new(inp.outputs["Geometry"], geometry_instance.inputs["Geometry"])
    links.new(mesh_line.outputs["Mesh"], instance_on_points.inputs["Points"])
    links.new(geometry_instance.outputs["Instances"], instance_on_points.inputs["Instance"])
    links.new(instance_on_points.outputs["Instances"], realize_array.inputs["Geometry"])

    array_mode = _math(group, "GREATER_THAN", "Use Extrude Array", 1120, 40, value_2=0.5)
    mode_switch = _node(group, "GeometryNodeSwitch", "Extrude Method", 1360, 420)
    try:
        mode_switch.input_type = "GEOMETRY"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(inp.outputs["Mode"], array_mode.inputs[0])
    links.new(array_mode.outputs[0], _input(mode_switch, "Switch", 0))
    links.new(join_volume.outputs["Geometry"], _input(mode_switch, "False", 1))
    links.new(realize_array.outputs["Geometry"], _input(mode_switch, "True", 2))

    # At zero effective depth, return the original input plane instead of two
    # coincident caps. This prevents z-fighting, doubled transparency and an
    # unnecessary side-wall branch when Thickness or animated Direction is zero.
    absolute_depth = _math(group, "ABSOLUTE", "Absolute Extrude Depth", 760, 80)
    has_depth = _math(group, "GREATER_THAN", "Extrude Has Depth", 950, 80, value_2=0.000001)
    output_switch = _node(group, "GeometryNodeSwitch", "Extrude Depth Bypass", 1120, 420)
    try:
        output_switch.input_type = "GEOMETRY"
    except (AttributeError, TypeError, ValueError):
        pass
    links.new(signed_thickness.outputs[0], absolute_depth.inputs[0])
    links.new(absolute_depth.outputs[0], has_depth.inputs[0])
    links.new(has_depth.outputs[0], _input(output_switch, "Switch", 0))
    links.new(inp.outputs["Geometry"], _input(output_switch, "False", 1))
    links.new(_output(mode_switch, "Output", 0), _input(output_switch, "True", 2))
    links.new(_output(output_switch, "Output", 0), out.inputs["Geometry"])

    group["fbp_quality_contract_version"] = 2
    group["fbp_alpha_geometry_contract_version"] = 3
    group["fbp_extrude_version"] = 9
    return group

def _create_wind_bender(name):
    """Create a pin-aware flag/paper deformation Geometry Nodes group."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Subdivision", "INPUT", "NodeSocketInt", default=4, minimum=0, maximum=7)
    _socket(group, "Bend Amount", "INPUT", "NodeSocketFloat", default=0.5, minimum=-10.0, maximum=10.0)
    _socket(group, "Wind Speed", "INPUT", "NodeSocketFloat", default=2.0, minimum=-100.0, maximum=100.0)
    _socket(group, "Shade Smooth", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Stepped", "INPUT", "NodeSocketInt", default=1, minimum=1, maximum=240)
    _socket(group, "Pin Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=5.0)
    _socket(group, "Pin Strength", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.0, maximum=1.0)
    _socket(group, "Pin Vertex Group", "INPUT", "NodeSocketString", default="")
    _socket(group, "Motion Mode", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Ripple Direction", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Wave Count", "INPUT", "NodeSocketFloat", default=2.0, minimum=0.0, maximum=40.0)
    _socket(group, "Wave Amplitude", "INPUT", "NodeSocketFloat", default=0.12, minimum=0.0, maximum=10.0)
    _socket(group, "Wave Speed", "INPUT", "NodeSocketFloat", default=2.0, minimum=-100.0, maximum=100.0)
    _socket(group, "Phase", "INPUT", "NodeSocketFloat", default=0.0, minimum=-1000.0, maximum=1000.0)
    _socket(group, "Turbulence", "INPUT", "NodeSocketFloat", default=0.03, minimum=0.0, maximum=2.0)
    _socket(group, "Falloff", "INPUT", "NodeSocketFloat", default=1.0, minimum=0.1, maximum=8.0)
    _socket(group, "Noise Scale", "INPUT", "NodeSocketFloat", default=3.0, minimum=0.01, maximum=100.0)
    _socket(group, "Gust Strength", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=2.0)
    _socket(group, "Direction Space", "INPUT", "NodeSocketFloat", default=0.0, minimum=0.0, maximum=1.0)
    _socket(group, "Wind Direction", "INPUT", "NodeSocketVector", default=(1.0, 0.0, 0.0))
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

    # Individual edge modes: Left, Right, Bottom and Top.
    weighted = []
    for index, distance in enumerate(distances):
        compare = _math(group, "COMPARE", f"Pin Edge {index}", -30, 390 - index * 105)
        compare.inputs[1].default_value = float(index)
        epsilon = _input(compare, "Epsilon", 2)
        if epsilon is not None:
            epsilon.default_value = 0.1
        multiply = _math(group, "MULTIPLY", f"Pinned Edge Distance {index}", 150, 390 - index * 105)
        links.new(inp.outputs["Pin Mode"], compare.inputs[0])
        links.new(distance, multiply.inputs[0])
        links.new(compare.outputs[0], multiply.inputs[1])
        weighted.append(multiply.outputs[0])
    add_a = _math(group, "ADD", "Pinned Horizontal", 340, 310)
    add_b = _math(group, "ADD", "Pinned Vertical", 340, 80)
    individual_distance = _math(group, "ADD", "Selected Pinned Edge", 520, 195)
    links.new(weighted[0], add_a.inputs[0]); links.new(weighted[1], add_a.inputs[1])
    links.new(weighted[2], add_b.inputs[0]); links.new(weighted[3], add_b.inputs[1])
    links.new(add_a.outputs[0], individual_distance.inputs[0]); links.new(add_b.outputs[0], individual_distance.inputs[1])
    individual_falloff = _math(group, "POWER", "Individual Pin Falloff", 700, 195)
    links.new(individual_distance.outputs[0], individual_falloff.inputs[0])
    links.new(inp.outputs["Falloff"], individual_falloff.inputs[1])

    # All Borders follows the actual evaluated bounds, so Crop and Extend are
    # naturally included without any separate UV assumptions.
    edge_x = _math(group, "MINIMUM", "Pin X Border Distance", 150, -130)
    edge_y = _math(group, "MINIMUM", "Pin Y Border Distance", 150, -250)
    all_distance = _math(group, "MINIMUM", "All Border Distance", 340, -190)
    all_falloff = _math(group, "POWER", "All Borders Falloff", 520, -190)
    links.new(norm_x, edge_x.inputs[0]); links.new(right_distance.outputs[0], edge_x.inputs[1])
    links.new(norm_y, edge_y.inputs[0]); links.new(top_distance.outputs[0], edge_y.inputs[1])
    links.new(edge_x.outputs[0], all_distance.inputs[0]); links.new(edge_y.outputs[0], all_distance.inputs[1])
    links.new(all_distance.outputs[0], all_falloff.inputs[0]); links.new(inp.outputs["Falloff"], all_falloff.inputs[1])

    named_group = _node(group, "GeometryNodeInputNamedAttribute", "Pinned Vertex Group", 150, -430)
    try:
        named_group.data_type = "FLOAT"
    except (AttributeError, TypeError, ValueError):
        pass
    vertex_free = _math(group, "SUBTRACT", "Vertex Group Free Weight", 360, -430, value_1=1.0)
    vertex_falloff = _math(group, "POWER", "Vertex Group Pin Falloff", 540, -430)
    links.new(inp.outputs["Pin Vertex Group"], named_group.inputs["Name"])
    links.new(named_group.outputs["Attribute"], vertex_free.inputs[1])
    links.new(vertex_free.outputs[0], vertex_falloff.inputs[0]); links.new(inp.outputs["Falloff"], vertex_falloff.inputs[1])

    special_mode = _math(group, "GREATER_THAN", "Use All Or Vertex Pin", 710, -80, value_2=3.5)
    vertex_mode = _math(group, "GREATER_THAN", "Use Vertex Group Pin", 710, -230, value_2=4.5)
    all_or_vertex = _node(group, "GeometryNodeSwitch", "All Or Vertex Pin", 900, -250)
    selected_pin = _node(group, "GeometryNodeSwitch", "Selected Pin Mode", 1090, 30)
    for switch in (all_or_vertex, selected_pin):
        try:
            switch.input_type = "FLOAT"
        except (AttributeError, TypeError, ValueError):
            pass
    links.new(inp.outputs["Pin Mode"], special_mode.inputs[0]); links.new(inp.outputs["Pin Mode"], vertex_mode.inputs[0])
    links.new(vertex_mode.outputs[0], all_or_vertex.inputs["Switch"])
    links.new(all_falloff.outputs[0], all_or_vertex.inputs["False"])
    links.new(vertex_falloff.outputs[0], all_or_vertex.inputs["True"])
    links.new(special_mode.outputs[0], selected_pin.inputs["Switch"])
    links.new(individual_falloff.outputs[0], selected_pin.inputs["False"])
    links.new(all_or_vertex.outputs["Output"], selected_pin.inputs["True"])

    strength_inverse = _math(group, "SUBTRACT", "Unpinned Strength", 1270, -80, value_1=1.0)
    pinned_weight = _math(group, "MULTIPLY", "Pinned Surface Weight", 1270, 80)
    free_weight = _math(group, "MULTIPLY", "Unpinned Surface Weight", 1450, -80)
    shaped_falloff = _math(group, "ADD", "Final Pin Falloff", 1630, 30)
    links.new(inp.outputs["Pin Strength"], strength_inverse.inputs[1])
    links.new(selected_pin.outputs["Output"], pinned_weight.inputs[0]); links.new(inp.outputs["Pin Strength"], pinned_weight.inputs[1])
    free_weight.inputs[0].default_value = 1.0; links.new(strength_inverse.outputs[0], free_weight.inputs[1])
    links.new(pinned_weight.outputs[0], shaped_falloff.inputs[0]); links.new(free_weight.outputs[0], shaped_falloff.inputs[1])

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

    # Ripple is now a third behavior of Mesh Motion instead of a separate
    # add-menu effect. It shares quality, time and pinning with Sway and Flow.
    centered_x = _math(group, "SUBTRACT", "Motion Centered X", 920, 520, value_2=0.5)
    centered_y = _math(group, "SUBTRACT", "Motion Centered Y", 920, 390, value_2=0.5)
    radial_vec = _node(group, "ShaderNodeCombineXYZ", "Motion Radial Vector", 1100, 455)
    radial_coord = _vector_math(group, "LENGTH", "Motion Radial Coordinate", 1280, 455)
    use_y = _math(group, "GREATER_THAN", "Ripple Uses Y", 920, 690, value_2=0.5)
    xy_switch = _node(group, "GeometryNodeSwitch", "Ripple X or Y", 1100, 680)
    use_radial = _math(group, "GREATER_THAN", "Ripple Uses Radius", 1280, 620, value_2=1.5)
    ripple_coord = _node(group, "GeometryNodeSwitch", "Ripple Coordinate", 1460, 610)
    for switch in (xy_switch, ripple_coord):
        switch.input_type = "FLOAT"
    links.new(norm_x, centered_x.inputs[0]); links.new(norm_y, centered_y.inputs[0])
    links.new(centered_x.outputs[0], radial_vec.inputs["X"]); links.new(centered_y.outputs[0], radial_vec.inputs["Y"])
    links.new(radial_vec.outputs[0], radial_coord.inputs[0])
    links.new(inp.outputs["Ripple Direction"], use_y.inputs[0]); links.new(use_y.outputs[0], xy_switch.inputs["Switch"])
    links.new(norm_x, xy_switch.inputs["False"]); links.new(norm_y, xy_switch.inputs["True"])
    links.new(inp.outputs["Ripple Direction"], use_radial.inputs[0]); links.new(use_radial.outputs[0], ripple_coord.inputs["Switch"])
    links.new(xy_switch.outputs["Output"], ripple_coord.inputs["False"]); links.new(radial_coord.outputs["Value"], ripple_coord.inputs["True"])
    ripple_frequency = _math(group, "MULTIPLY", "Mesh Motion Ripple Frequency", 1640, 610)
    ripple_cycles = _math(group, "MULTIPLY", "Mesh Motion Ripple Cycles", 1820, 610, value_2=6.283185307)
    ripple_time = _math(group, "MULTIPLY", "Mesh Motion Ripple Time", 1640, 480)
    ripple_phase_a = _math(group, "ADD", "Mesh Motion Ripple Moving Phase", 2000, 550)
    ripple_phase_b = _math(group, "ADD", "Mesh Motion Ripple User Phase", 2180, 550)
    ripple_sine = _math(group, "SINE", "Mesh Motion Ripple", 2360, 550)
    ripple_amount = _math(group, "MULTIPLY", "Mesh Motion Ripple Amount", 2540, 550)
    ripple_falloff = _math(group, "MULTIPLY", "Mesh Motion Ripple Pinning", 2720, 550)
    links.new(ripple_coord.outputs["Output"], ripple_frequency.inputs[0]); links.new(inp.outputs["Wave Count"], ripple_frequency.inputs[1])
    links.new(ripple_frequency.outputs[0], ripple_cycles.inputs[0])
    links.new(time_scale.outputs[0], ripple_time.inputs[0]); links.new(inp.outputs["Wave Speed"], ripple_time.inputs[1])
    links.new(ripple_cycles.outputs[0], ripple_phase_a.inputs[0]); links.new(ripple_time.outputs[0], ripple_phase_a.inputs[1])
    links.new(ripple_phase_a.outputs[0], ripple_phase_b.inputs[0]); links.new(inp.outputs["Phase"], ripple_phase_b.inputs[1])
    links.new(ripple_phase_b.outputs[0], ripple_sine.inputs[0]); links.new(ripple_sine.outputs[0], ripple_amount.inputs[0])
    links.new(inp.outputs["Wave Amplitude"], ripple_amount.inputs[1]); links.new(ripple_amount.outputs[0], ripple_falloff.inputs[0])
    links.new(shaped_falloff.outputs[0], ripple_falloff.inputs[1])

    use_flow = _math(group, "GREATER_THAN", "Use Flow Behavior", 1980, -500, value_2=0.5)
    use_ripple = _math(group, "GREATER_THAN", "Use Ripple Behavior", 2180, -500, value_2=1.5)
    sway_or_flow = _node(group, "GeometryNodeSwitch", "Sway Or Flow", 2180, -360)
    selected_motion = _node(group, "GeometryNodeSwitch", "Selected Mesh Motion", 2920, 120)
    for switch in (sway_or_flow, selected_motion):
        switch.input_type = "FLOAT"
    links.new(inp.outputs["Motion Mode"], use_flow.inputs[0]); links.new(inp.outputs["Motion Mode"], use_ripple.inputs[0])
    links.new(use_flow.outputs[0], sway_or_flow.inputs["Switch"])
    links.new(sway_falloff.outputs[0], sway_or_flow.inputs["False"]); links.new(wave_falloff.outputs[0], sway_or_flow.inputs["True"])
    links.new(use_ripple.outputs[0], selected_motion.inputs["Switch"])
    links.new(sway_or_flow.outputs["Output"], selected_motion.inputs["False"]); links.new(ripple_falloff.outputs[0], selected_motion.inputs["True"])

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
    shade_smooth = _node(group, "GeometryNodeSetShadeSmooth", "Wind Shade Smooth", 4100, 220)
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
    links.new(set_position.outputs["Geometry"], shade_smooth.inputs["Geometry"])
    links.new(inp.outputs["Shade Smooth"], shade_smooth.inputs["Shade Smooth"])
    links.new(shade_smooth.outputs["Geometry"], out.inputs["Geometry"])
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


def _create_mirror(name):
    """Mirror plane geometry around its local origin without moving the rig pivot."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    _socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(group, "Mirror X", "INPUT", "NodeSocketBool", default=True)
    _socket(group, "Mirror Y", "INPUT", "NodeSocketBool", default=False)
    _socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    inp, out = _group_io(group)
    links = group.links

    x_double = _math(group, "MULTIPLY", "Mirror X Double", -520, 140, value_2=2.0)
    x_sign = _math(group, "SUBTRACT", "Mirror X Sign", -300, 140, value_1=1.0)
    y_double = _math(group, "MULTIPLY", "Mirror Y Double", -520, -20, value_2=2.0)
    y_sign = _math(group, "SUBTRACT", "Mirror Y Sign", -300, -20, value_1=1.0)
    scale = _node(group, "ShaderNodeCombineXYZ", "Mirror Scale", -80, 80)
    scale.inputs["Z"].default_value = 1.0
    transform = _node(group, "GeometryNodeTransform", "Mirror Geometry", 160, 80)

    links.new(inp.outputs["Mirror X"], x_double.inputs[0])
    links.new(x_double.outputs[0], x_sign.inputs[1])
    links.new(inp.outputs["Mirror Y"], y_double.inputs[0])
    links.new(y_double.outputs[0], y_sign.inputs[1])
    links.new(x_sign.outputs[0], scale.inputs["X"])
    links.new(y_sign.outputs[0], scale.inputs["Y"])
    links.new(inp.outputs["Geometry"], transform.inputs["Geometry"])
    links.new(scale.outputs[0], transform.inputs["Scale"])
    links.new(transform.outputs["Geometry"], out.inputs["Geometry"])
    group["fbp_mirror_contract_version"] = 1
    return group


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
    asset_id = str(definition.get("asset_id", "") or "")
    if asset_id.startswith(("frame_by_plane.fiber_tufts", "frame_by_plane.paper_shards")):
        try:
            if int(group.get("fbp_instancing_contract_version", 0) or 0) < 4:
                return False
        except FBP_DATA_ERRORS:
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
    if definition.get("layer_blend_contract_version"):
        try:
            required_contract = int(
                definition.get("layer_blend_contract_version", 2) or 2
            )
            if int(group.get("fbp_layer_blend_contract_version", 0) or 0) < required_contract:
                return False
        except FBP_DATA_ERRORS:
            return False
    if bool(definition.get("mask_source_transform_aware")):
        try:
            required_contract = max(
                5, int(definition.get("track_matte_contract_version", 5) or 5)
            )
            if int(group.get("fbp_track_matte_contract_version", 0) or 0) < required_contract:
                return False
            if not any(bool(node.get("fbp_mask_source_coord_node", False)) for node in group.nodes):
                return False
            if bool(definition.get("mask_camera_projection_aware")) and not any(
                bool(node.get("fbp_mask_camera_coord_node", False)) for node in group.nodes
            ):
                return False
        except FBP_DATA_ERRORS:
            return False
    if bool(definition.get("object_mask_aware")):
        try:
            if int(group.get("fbp_object_mask_contract_version", 0) or 0) < 4:
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
    required_uv_store = str(
        definition.get("attribute_material_uv_store", "") or ""
    )
    if required_uv_store and group.nodes.get(required_uv_store) is None:
        return False
    generated_mask_contracts = {
        "frame_by_plane.shader.color_mask": 2,
        "frame_by_plane.shader.luminance_mask": 3,
        "frame_by_plane.shader.channel_mask": 3,
        "frame_by_plane.shader.gradient_mask": 3,
        "frame_by_plane.shader.noise_mask": 2,
        "frame_by_plane.shader.voronoi_mask": 4,
        "frame_by_plane.shader.wave_mask": 4,
    }
    definition_asset_id = str(definition.get("asset_id", "") or "")
    required_mask_contract = next(
        (version for prefix, version in generated_mask_contracts.items() if definition_asset_id.startswith(prefix)),
        0,
    )
    if required_mask_contract:
        try:
            if int(group.get("fbp_generated_mask_contract_version", 0) or 0) < required_mask_contract:
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
            uv_store = group.nodes.get("Store Text Matrix UV")
            if (
                len(glyph_nodes) != 16
                or color_store is None
                or uv_store is None
                or int(group.get("fbp_text_matrix_uv_version", 0) or 0) < 3
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
        "UV_DISTORTION": lambda: _create_uv_distortion(canonical_name),
        "PIXELATE": lambda: _create_pixelate(canonical_name),
        "SWIRL": lambda: _create_swirl(canonical_name),
        "BULGE_PINCH": lambda: _create_bulge_pinch(canonical_name),
        "LENS_WARP": lambda: _create_lens_warp(canonical_name),
        "WAVE_WARP": lambda: _create_wave_warp(canonical_name),
        "RIPPLE_DISTORTION": lambda: _create_ripple_distortion(canonical_name),
        "KALEIDOSCOPE": lambda: _create_kaleidoscope(canonical_name),
        "HEX_PIXELATE": lambda: _create_hex_pixelate(canonical_name),
        "MOSAIC_JITTER": lambda: _create_mosaic_jitter(canonical_name),
        "SLICE_SHIFT": lambda: _create_slice_shift(canonical_name),
        "RECOLOR": lambda: _create_recolor(canonical_name),
        "GRADIENT_MAP": lambda: _create_gradient_map(canonical_name),
        "CHANNEL_MIXER": lambda: _create_channel_mixer(canonical_name),
        "DITHER": lambda: _create_dither(canonical_name),
        "BLOOM": lambda: _create_bloom(canonical_name),
        "FILTER_PRESETS": lambda: _create_filter_presets(canonical_name),
        "WHITE_BALANCE": lambda: _create_white_balance(canonical_name),
        "CURVES": lambda: _create_curves(canonical_name),
        "COLOR_ISOLATE": lambda: _create_color_isolate(canonical_name),
        "GRADIENT_LIGHT": lambda: _create_gradient_light(canonical_name),
        "RIM": lambda: _create_rim(canonical_name),
        "SHADOW": lambda: _create_shadow(canonical_name),
        "DEPTH_BLUR": lambda: _create_depth_blur(canonical_name),
        "GAUSSIAN_BLUR": lambda: _create_gaussian_blur(canonical_name),
        "DIRECTIONAL_BLUR": lambda: _create_directional_blur(canonical_name),
        "TRIANGLE_BLUR": lambda: _create_triangle_blur(canonical_name),
        "TILT_SHIFT": lambda: _create_tilt_shift(canonical_name),
        "UNSHARP_MASK": lambda: _create_unsharp_mask(canonical_name),
        "EDGE_DETECT": lambda: _create_edge_detect(canonical_name),
        "SMOOTH_TOON": lambda: _create_smooth_toon(canonical_name),
        "ADAPTIVE_THRESHOLD": lambda: _create_adaptive_threshold(canonical_name),
        "FALSE_COLOR": lambda: _create_false_color(canonical_name),
        "CHROMATIC_ABERRATION": lambda: _create_chromatic_aberration(canonical_name),
        "INK": lambda: _create_ink(canonical_name),
        "EDGE_WORK": lambda: _create_edge_work(canonical_name),
        "PENCIL_SKETCH": lambda: _create_pencil_sketch(canonical_name),
        "POSTER_EDGES": lambda: _create_poster_edges(canonical_name),
        "CROSSHATCH": lambda: _create_crosshatch(canonical_name),
        "EMBOSS": lambda: _create_emboss(canonical_name),
        "ALPHA_MATTE": lambda: _create_alpha_matte(canonical_name),
        "LUMA_MATTE": lambda: _create_luma_matte(canonical_name),
        "CLIPPING_MASK": lambda: _create_clipping_mask(canonical_name),
        "IMPORTED_MASK": lambda: _create_imported_mask(canonical_name),
        "GP_MASK_SLOT_2": lambda: _create_imported_mask(canonical_name),
        "GP_MASK_SLOT_3": lambda: _create_imported_mask(canonical_name),
        "GP_MASK_SLOT_4": lambda: _create_imported_mask(canonical_name),
        "LAYER_BLEND": lambda: _create_layer_blend(canonical_name),
        "SQUARE_MASK": lambda: _create_object_shape_mask(canonical_name, shape="SQUARE"),
        "CIRCLE_MASK": lambda: _create_object_shape_mask(canonical_name, shape="CIRCLE"),
        "TRIANGLE_MASK": lambda: _create_object_shape_mask(canonical_name, shape="TRIANGLE"),
        "COLOR_MASK": lambda: _create_color_mask(canonical_name),
        "LUMINANCE_MASK": lambda: _create_luminance_mask(canonical_name),
        "CHANNEL_MASK": lambda: _create_channel_mask(canonical_name),
        "GRADIENT_MASK": lambda: _create_gradient_mask(canonical_name),
        "NOISE_MASK": lambda: _create_noise_mask(canonical_name),
        "VORONOI_MASK": lambda: _create_voronoi_mask(canonical_name),
        "WAVE_MASK": lambda: _create_wave_mask(canonical_name),
        "DIGITAL_NOISE": lambda: _create_digital_noise(canonical_name),
        "CHROMA_KEY": lambda: _create_chroma_key(canonical_name),
        "HALFTONE": lambda: _create_halftone(canonical_name),
        "DOT_MATRIX": lambda: _create_dot_matrix(canonical_name),
        "ASCII_MATRIX": lambda: _create_ascii_matrix(canonical_name, asset_dir),
        "ASCII": lambda: _create_terminal_ascii(canonical_name, asset_dir),
        "TEXT_MATRIX": lambda: _create_text_matrix(canonical_name),
        "WIND_BENDER": lambda: _create_wind_bender(canonical_name),
        "CUTOUT_OUTLINE": lambda: _create_cutout_outline(canonical_name),
        "THICKNESS": lambda: _create_extrude(canonical_name),
        "FIBER_TUFTS": lambda: _create_fiber_tufts(canonical_name),
        "PAPER_SHARDS": lambda: _create_paper_shards(canonical_name),
        "SPHERE_SCREEN": lambda: _create_sphere_screen(canonical_name),
        "IMAGE_RELIEF": lambda: _create_image_relief(canonical_name),
        "GLASS": lambda: _create_glass(canonical_name),
        "CRYSTAL": lambda: _create_crystal(canonical_name),
        "SURFACE_CONFORM": lambda: _create_surface_conform(canonical_name),
        "ACCORDION_FOLD": lambda: _create_accordion_fold(canonical_name),
        "SCULPT_WAVES": lambda: _create_sculpt_waves(canonical_name),
        "KINETIC_TILES": lambda: _create_kinetic_tiles(canonical_name),
        "LAYERED_ECHO": lambda: _create_layered_echo(canonical_name),
        "CAMERA_SCALE_LOCK": lambda: _create_camera_scale_lock(canonical_name),
        "CAMERA_BILLBOARD": lambda: _create_camera_billboard(canonical_name),
        "MIRROR": lambda: _create_mirror(canonical_name),
        "SOLARIZE": lambda: _create_solarize(canonical_name),
        "TRITONE": lambda: _create_tritone(canonical_name),
        "FILM_FADE": lambda: _create_film_fade(canonical_name),
    }
    builder = builders.get(effect_id)
    if builder is None:
        return None
    before = {group.as_pointer() for group in bpy.data.node_groups}
    try:
        group = builder()
        # Builders already assign stable editor coordinates. Re-parenting every
        # node into decorative frames is disproportionately expensive in Blender
        # 5.2 (nearly one second for large effects such as Rim) and has no
        # evaluation benefit, so generated groups keep the builder layout.
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
