"""Image, image-sequence and movie projector light preset for Frame By Plane."""

from __future__ import annotations

import os
import re

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, OperatorFileListElement, Panel
from mathutils import Vector

from .layers import fbp_resolve_rig_from_any_object
from .geometry_nodes import _fbp_material_image_node
from .ownership import tag_managed
from .runtime import FBP_DATA_ERRORS, fbp_warn
from .ui_style import configure_layout
from .registration import register_classes, unregister_classes, unregister_type_properties


PROJECTOR_TEXTURE_NODE = "FBP Projector Media Texture"
PROJECTOR_SCALE_NODE = "FBP Projector Scale"
PROJECTOR_ALPHA_NODE = "FBP Projector Use Alpha"
PROJECTOR_ASPECT_NODE = "FBP Projector Aspect"
PROJECTOR_FOCUS_NODE = "FBP Projector Focus Distance"
PROJECTOR_BLUR_NODE = "FBP Projector Focus Blur"
PROJECTOR_BLUR_MAX_NODE = "FBP Projector Maximum Blur"
PROJECTOR_SCHEMA = 2
_IMAGE_EXTENSIONS = {
    ".bmp", ".cin", ".dpx", ".exr", ".hdr", ".jpeg", ".jpg", ".png",
    ".psd", ".sgi", ".tga", ".tif", ".tiff", ".webp",
}
_VIDEO_EXTENSIONS = {
    ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".mxf",
    ".ogv", ".webm",
}
_MEDIA_EXTENSIONS = _IMAGE_EXTENSIONS | _VIDEO_EXTENSIONS


def is_fbp_projector(obj) -> bool:
    try:
        light = getattr(obj, "data", None)
        return bool(
            obj
            and str(getattr(obj, "type", "") or "") == "LIGHT"
            and bool(obj.get("fbp_is_projector", False))
            and light is not None
            and bool(light.get("fbp_is_projector", False))
        )
    except FBP_DATA_ERRORS:
        return False


def _math_node(tree, operation, name, x, y, *, value_1=None, value_2=None):
    node = tree.nodes.new("ShaderNodeMath")
    node.operation = operation
    node.name = name
    node.label = name
    node.location = (x, y)
    if value_1 is not None:
        node.inputs[0].default_value = value_1
    if value_2 is not None:
        node.inputs[1].default_value = value_2
    return node


def _value_node(tree, name, x, y, value):
    node = tree.nodes.new("ShaderNodeValue")
    node.name = name
    node.label = name
    node.location = (x, y)
    node.outputs[0].default_value = float(value)
    return node


def _projector_image_aspect(image):
    try:
        width, height = image.size
        return max(0.001, float(width) / max(1.0, float(height)))
    except FBP_DATA_ERRORS:
        return 1.0


def _copy_image_user(source_node, target_node, *, frame_duration=1):
    try:
        target = target_node.image_user
        source = getattr(source_node, "image_user", None) if source_node is not None else None
        for attr, fallback in (
            ("frame_duration", max(1, int(frame_duration or 1))),
            ("frame_start", 1),
            ("frame_offset", 0),
            ("use_cyclic", False),
            ("use_auto_refresh", True),
        ):
            setattr(target, attr, getattr(source, attr, fallback) if source is not None else fallback)
        target.use_auto_refresh = True
    except FBP_DATA_ERRORS:
        pass


def _projector_texture_nodes(light):
    try:
        if not light or not light.node_tree:
            return ()
        return tuple(
            node for node in light.node_tree.nodes
            if bool(node.get("fbp_projector_texture", False))
        )
    except FBP_DATA_ERRORS:
        return ()


def _add_driver(node, light, expression, variables):
    try:
        fcurve = node.outputs[0].driver_add("default_value")
        driver = fcurve.driver
        driver.type = "SCRIPTED"
        driver.expression = expression
        for name, data_path in variables:
            variable = driver.variables.new()
            variable.name = name
            variable.type = "SINGLE_PROP"
            variable.targets[0].id_type = "LIGHT"
            variable.targets[0].id = light
            variable.targets[0].data_path = data_path
    except FBP_DATA_ERRORS:
        pass


def _build_projector_nodes(light, image=None, *, frame_duration=1, source_node=None):
    light.use_nodes = True
    tree = light.node_tree
    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputLight")
    output.name = "FBP Projector Output"
    output.location = (2220, 260)
    emission = nodes.new("ShaderNodeEmission")
    emission.name = "FBP Projector Emission"
    emission.location = (2000, 260)

    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.name = "FBP Projector Direction"
    geometry.location = (-1500, 300)
    vector_transform = nodes.new("ShaderNodeVectorTransform")
    vector_transform.name = "FBP Projector Local Direction"
    vector_transform.vector_type = "VECTOR"
    vector_transform.convert_from = "WORLD"
    vector_transform.convert_to = "OBJECT"
    vector_transform.location = (-1280, 300)
    separate = nodes.new("ShaderNodeSeparateXYZ")
    separate.name = "FBP Projector Direction Components"
    separate.location = (-1060, 300)
    links.new(geometry.outputs["Incoming"], vector_transform.inputs["Vector"])
    links.new(vector_transform.outputs["Vector"], separate.inputs[0])

    negative_z = _math_node(tree, "MULTIPLY", "FBP Projector Forward Z", -840, 60, value_2=-1.0)
    absolute_z = _math_node(tree, "ABSOLUTE", "FBP Projector Absolute Z", -620, 60)
    safe_z = _math_node(tree, "MAXIMUM", "FBP Projector Safe Z", -400, 60, value_2=0.0001)
    links.new(separate.outputs["Z"], negative_z.inputs[0])
    links.new(negative_z.outputs[0], absolute_z.inputs[0])
    links.new(absolute_z.outputs[0], safe_z.inputs[0])

    scale = _value_node(tree, PROJECTOR_SCALE_NODE, -620, -220, 1.0)
    scale.label = "Cone x Radius x Image Zoom"
    _add_driver(
        scale,
        light,
        "max(0.001, tan(cone * 0.5) * max(0.001, radius) * max(0.01, zoom))",
        (("cone", "spot_size"), ("radius", "shadow_soft_size"), ("zoom", "fbp_projector_scale")),
    )

    aspect = _value_node(tree, PROJECTOR_ASPECT_NODE, -180, -220, _projector_image_aspect(image))

    uv_outputs = []
    for axis, y in (("X", 400), ("Y", 220)):
        ratio = _math_node(tree, "DIVIDE", f"FBP Projector {axis} Ratio", -400, y)
        corrected = ratio
        if axis == "Y":
            corrected = _math_node(tree, "MULTIPLY", "FBP Projector Aspect Correction", -180, y)
            links.new(ratio.outputs[0], corrected.inputs[0])
            links.new(aspect.outputs[0], corrected.inputs[1])
        half = _math_node(tree, "MULTIPLY", f"FBP Projector {axis} Half", 40, y, value_2=0.5)
        scaled = _math_node(tree, "DIVIDE", f"FBP Projector {axis} Scale", 260, y)
        centered = _math_node(tree, "ADD", f"FBP Projector {axis} UV", 480, y, value_2=0.5)
        links.new(separate.outputs[axis], ratio.inputs[0])
        links.new(safe_z.outputs[0], ratio.inputs[1])
        links.new(corrected.outputs[0], half.inputs[0])
        links.new(half.outputs[0], scaled.inputs[0])
        links.new(scale.outputs[0], scaled.inputs[1])
        links.new(scaled.outputs[0], centered.inputs[0])
        uv_outputs.append(centered.outputs[0])

    uv = nodes.new("ShaderNodeCombineXYZ")
    uv.name = "FBP Projector UV"
    uv.location = (700, 320)
    links.new(uv_outputs[0], uv.inputs["X"])
    links.new(uv_outputs[1], uv.inputs["Y"])

    def image_texture(name, x, y):
        node = nodes.new("ShaderNodeTexImage")
        node.name = name
        node.label = "Projected Image / Sequence"
        node.location = (x, y)
        node.image = image
        node.extension = "CLIP"
        node.interpolation = "Linear"
        node["fbp_projector_texture"] = True
        _copy_image_user(source_node, node, frame_duration=frame_duration)
        return node

    texture = image_texture(PROJECTOR_TEXTURE_NODE, 1120, 480)
    links.new(uv.outputs[0], texture.inputs["Vector"])

    # A small four-tap blur approximates depth of field without external OSL.
    # The circle of confusion grows with the relative distance from the focus
    # plane and remains bounded so the light shader stays predictable.
    focus = _value_node(
        tree, PROJECTOR_FOCUS_NODE, -620, -500,
        max(0.001, float(getattr(light, "fbp_projector_focus_distance", 2.0) or 2.0)),
    )
    blur = _value_node(
        tree, PROJECTOR_BLUR_NODE, -620, -610,
        max(0.0, float(getattr(light, "fbp_projector_blur_strength", 0.0) or 0.0)),
    )
    blur_max = _value_node(
        tree, PROJECTOR_BLUR_MAX_NODE, -620, -720,
        max(0.0, float(getattr(light, "fbp_projector_blur_max", 0.03) or 0.03)),
    )
    distance = nodes.new("ShaderNodeVectorMath")
    distance.operation = "LENGTH"
    distance.name = "FBP Projector Surface Distance"
    distance.location = (-1060, -520)
    links.new(geometry.outputs["Incoming"], distance.inputs[0])
    delta = _math_node(tree, "SUBTRACT", "FBP Projector Focus Delta", -840, -500)
    abs_delta = _math_node(tree, "ABSOLUTE", "FBP Projector Absolute Focus Delta", -620, -390)
    safe_focus = _math_node(tree, "MAXIMUM", "FBP Projector Safe Focus", -400, -500, value_2=0.001)
    relative = _math_node(tree, "DIVIDE", "FBP Projector Relative Defocus", -180, -500)
    blur_amount = _math_node(tree, "MULTIPLY", "FBP Projector Defocus Amount", 40, -500)
    blur_factor = _math_node(tree, "MINIMUM", "FBP Projector Defocus Factor", 260, -500, value_2=1.0)
    blur_radius = _math_node(tree, "MULTIPLY", "FBP Projector Blur Radius", 480, -500)
    links.new(distance.outputs["Value"], delta.inputs[0])
    links.new(focus.outputs[0], delta.inputs[1])
    links.new(delta.outputs[0], abs_delta.inputs[0])
    links.new(focus.outputs[0], safe_focus.inputs[0])
    links.new(abs_delta.outputs[0], relative.inputs[0])
    links.new(safe_focus.outputs[0], relative.inputs[1])
    links.new(relative.outputs[0], blur_amount.inputs[0])
    links.new(blur.outputs[0], blur_amount.inputs[1])
    links.new(blur_amount.outputs[0], blur_factor.inputs[0])
    links.new(blur_factor.outputs[0], blur_radius.inputs[0])
    links.new(blur_max.outputs[0], blur_radius.inputs[1])

    negative_radius = _math_node(tree, "MULTIPLY", "FBP Projector Negative Blur Radius", 700, -610, value_2=-1.0)
    links.new(blur_radius.outputs[0], negative_radius.inputs[0])
    samples = []
    for index, (sx, sy) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1)), start=1):
        offset = nodes.new("ShaderNodeCombineXYZ")
        offset.name = f"FBP Projector Blur Offset {index}"
        offset.location = (700, -420 - index * 100)
        links.new(blur_radius.outputs[0] if sx > 0 else negative_radius.outputs[0], offset.inputs["X"])
        links.new(blur_radius.outputs[0] if sy > 0 else negative_radius.outputs[0], offset.inputs["Y"])
        shifted = nodes.new("ShaderNodeVectorMath")
        shifted.operation = "ADD"
        shifted.name = f"FBP Projector Blur UV {index}"
        shifted.location = (900, -420 - index * 100)
        links.new(uv.outputs[0], shifted.inputs[0])
        links.new(offset.outputs[0], shifted.inputs[1])
        sample = image_texture(f"FBP Projector Blur Sample {index}", 1120, -300 - index * 170)
        links.new(shifted.outputs[0], sample.inputs["Vector"])
        samples.append(sample)

    color_pair_a = nodes.new("ShaderNodeVectorMath")
    color_pair_a.operation = "ADD"
    color_pair_a.location = (1360, -380)
    color_pair_b = nodes.new("ShaderNodeVectorMath")
    color_pair_b.operation = "ADD"
    color_pair_b.location = (1360, -560)
    color_sum = nodes.new("ShaderNodeVectorMath")
    color_sum.operation = "ADD"
    color_sum.location = (1540, -460)
    color_average = nodes.new("ShaderNodeVectorMath")
    color_average.operation = "SCALE"
    color_average.location = (1720, -460)
    color_average.inputs[3].default_value = 0.25
    links.new(samples[0].outputs["Color"], color_pair_a.inputs[0])
    links.new(samples[1].outputs["Color"], color_pair_a.inputs[1])
    links.new(samples[2].outputs["Color"], color_pair_b.inputs[0])
    links.new(samples[3].outputs["Color"], color_pair_b.inputs[1])
    links.new(color_pair_a.outputs[0], color_sum.inputs[0])
    links.new(color_pair_b.outputs[0], color_sum.inputs[1])
    links.new(color_sum.outputs[0], color_average.inputs[0])
    blurred_color = nodes.new("ShaderNodeMixRGB")
    blurred_color.name = "FBP Projector Focus Color"
    blurred_color.blend_type = "MIX"
    blurred_color.location = (1740, 400)
    links.new(blur_factor.outputs[0], blurred_color.inputs[0])
    links.new(texture.outputs["Color"], blurred_color.inputs[1])
    links.new(color_average.outputs[0], blurred_color.inputs[2])

    alpha_pair_a = _math_node(tree, "ADD", "FBP Projector Blur Alpha A", 1360, -820)
    alpha_pair_b = _math_node(tree, "ADD", "FBP Projector Blur Alpha B", 1360, -940)
    alpha_sum = _math_node(tree, "ADD", "FBP Projector Blur Alpha Sum", 1540, -860)
    alpha_average = _math_node(tree, "MULTIPLY", "FBP Projector Blur Alpha Average", 1720, -860, value_2=0.25)
    alpha_difference = _math_node(tree, "SUBTRACT", "FBP Projector Blur Alpha Difference", 1720, -700)
    alpha_weighted = _math_node(tree, "MULTIPLY", "FBP Projector Weighted Blur Alpha", 1900, -700)
    focused_alpha = _math_node(tree, "ADD", "FBP Projector Focus Alpha", 2080, -700)
    links.new(samples[0].outputs["Alpha"], alpha_pair_a.inputs[0])
    links.new(samples[1].outputs["Alpha"], alpha_pair_a.inputs[1])
    links.new(samples[2].outputs["Alpha"], alpha_pair_b.inputs[0])
    links.new(samples[3].outputs["Alpha"], alpha_pair_b.inputs[1])
    links.new(alpha_pair_a.outputs[0], alpha_sum.inputs[0])
    links.new(alpha_pair_b.outputs[0], alpha_sum.inputs[1])
    links.new(alpha_sum.outputs[0], alpha_average.inputs[0])
    links.new(alpha_average.outputs[0], alpha_difference.inputs[0])
    links.new(texture.outputs["Alpha"], alpha_difference.inputs[1])
    links.new(alpha_difference.outputs[0], alpha_weighted.inputs[0])
    links.new(blur_factor.outputs[0], alpha_weighted.inputs[1])
    links.new(texture.outputs["Alpha"], focused_alpha.inputs[0])
    links.new(alpha_weighted.outputs[0], focused_alpha.inputs[1])

    bounds = []
    for axis, socket, y in (("U", uv_outputs[0], 140), ("V", uv_outputs[1], -20)):
        minimum = _math_node(tree, "GREATER_THAN", f"FBP Projector {axis} Minimum", 700, y, value_2=0.0)
        maximum = _math_node(tree, "LESS_THAN", f"FBP Projector {axis} Maximum", 920, y, value_2=1.0)
        inside = _math_node(tree, "MULTIPLY", f"FBP Projector {axis} Bounds", 1140, y)
        links.new(socket, minimum.inputs[0])
        links.new(socket, maximum.inputs[0])
        links.new(minimum.outputs[0], inside.inputs[0])
        links.new(maximum.outputs[0], inside.inputs[1])
        bounds.append(inside.outputs[0])
    inside_image = _math_node(tree, "MULTIPLY", "FBP Projector Image Bounds", 1360, 60)
    links.new(bounds[0], inside_image.inputs[0])
    links.new(bounds[1], inside_image.inputs[1])

    use_alpha = nodes.new("ShaderNodeValue")
    use_alpha.name = PROJECTOR_ALPHA_NODE
    use_alpha.label = "Use Image Alpha"
    use_alpha.location = (1360, 220)
    use_alpha.outputs[0].default_value = 1.0 if bool(getattr(light, "fbp_projector_use_alpha", True)) else 0.0
    inverse_alpha_toggle = _math_node(tree, "SUBTRACT", "FBP Projector Ignore Alpha", 1540, 160, value_1=1.0)
    selected_alpha = _math_node(tree, "MULTIPLY", "FBP Projector Selected Alpha", 1540, 260)
    alpha_or_one = _math_node(tree, "ADD", "FBP Projector Alpha", 1720, 240)
    final_mask = _math_node(tree, "MULTIPLY", "FBP Projector Mask", 1900, 120)
    links.new(use_alpha.outputs[0], inverse_alpha_toggle.inputs[1])
    links.new(focused_alpha.outputs[0], selected_alpha.inputs[0])
    links.new(use_alpha.outputs[0], selected_alpha.inputs[1])
    links.new(selected_alpha.outputs[0], alpha_or_one.inputs[0])
    links.new(inverse_alpha_toggle.outputs[0], alpha_or_one.inputs[1])
    links.new(inside_image.outputs[0], final_mask.inputs[0])
    links.new(alpha_or_one.outputs[0], final_mask.inputs[1])

    color_scale = nodes.new("ShaderNodeVectorMath")
    color_scale.operation = "SCALE"
    color_scale.name = "FBP Projector Masked Color"
    color_scale.location = (1900, 400)
    links.new(blurred_color.outputs[0], color_scale.inputs[0])
    links.new(final_mask.outputs[0], color_scale.inputs[3])
    links.new(color_scale.outputs[0], emission.inputs["Color"])
    links.new(emission.outputs[0], output.inputs["Surface"])
    tree["fbp_projector_schema"] = PROJECTOR_SCHEMA
    return texture


def _projector_texture(light):
    try:
        return light.node_tree.nodes.get(PROJECTOR_TEXTURE_NODE) if light and light.node_tree else None
    except FBP_DATA_ERRORS:
        return None


def _update_projector_image(light, _context=None):
    if not bool(getattr(light, "get", lambda *_: False)("fbp_is_projector", False)):
        return
    texture = _projector_texture(light)
    if texture is None:
        texture = _build_projector_nodes(light, getattr(light, "fbp_projector_image", None))
    try:
        image = light.fbp_projector_image
        for node in _projector_texture_nodes(light):
            node.image = image
            node.image_user.use_auto_refresh = True
        aspect = light.node_tree.nodes.get(PROJECTOR_ASPECT_NODE)
        if aspect is not None:
            aspect.outputs[0].default_value = _projector_image_aspect(image)
    except FBP_DATA_ERRORS:
        pass


def _update_projector_scale(light, _context=None):
    try:
        light.update_tag()
    except FBP_DATA_ERRORS:
        pass


def _update_projector_focus(light, _context=None):
    try:
        values = (
            (PROJECTOR_FOCUS_NODE, max(0.001, float(light.fbp_projector_focus_distance))),
            (PROJECTOR_BLUR_NODE, max(0.0, float(light.fbp_projector_blur_strength))),
            (PROJECTOR_BLUR_MAX_NODE, max(0.0, float(light.fbp_projector_blur_max))),
        )
        for name, value in values:
            node = light.node_tree.nodes.get(name)
            if node is not None:
                node.outputs[0].default_value = value
    except FBP_DATA_ERRORS:
        pass


def _update_projector_alpha(light, _context=None):
    try:
        node = light.node_tree.nodes.get(PROJECTOR_ALPHA_NODE)
        node.outputs[0].default_value = 1.0 if light.fbp_projector_use_alpha else 0.0
    except FBP_DATA_ERRORS:
        pass


def _update_projector_frame_offset(light, _context=None):
    try:
        for texture in _projector_texture_nodes(light):
            texture.image_user.frame_offset = int(light.fbp_projector_frame_offset)
            texture.image_user.use_auto_refresh = True
    except FBP_DATA_ERRORS:
        pass


def _natural_key(path):
    return tuple(int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", os.path.basename(path)))


def _load_projector_media(paths):
    """Load one image/sequence or one movie without guessing mixed selections."""
    valid = [
        os.path.normpath(path)
        for path in paths
        if os.path.splitext(path)[1].lower() in _MEDIA_EXTENSIONS
    ]
    if not valid:
        return None, 0
    valid.sort(key=_natural_key)
    movie_paths = [path for path in valid if os.path.splitext(path)[1].lower() in _VIDEO_EXTENSIONS]
    image_paths = [path for path in valid if os.path.splitext(path)[1].lower() in _IMAGE_EXTENSIONS]
    if movie_paths and image_paths:
        raise ValueError("Choose one movie or an image sequence, not both")
    if len(movie_paths) > 1:
        raise ValueError("Choose one movie at a time")

    source_path = movie_paths[0] if movie_paths else image_paths[0]
    image = bpy.data.images.load(source_path, check_existing=True)
    if movie_paths:
        try:
            image.source = "MOVIE"
            image.name = f"FBP Projector Movie • {os.path.basename(source_path)}"
        except FBP_DATA_ERRORS:
            pass
        try:
            duration = max(1, int(getattr(image, "frame_duration", 1) or 1))
        except FBP_DATA_ERRORS:
            duration = 1
        return image, duration

    duration = len(image_paths)
    if duration > 1:
        try:
            image.source = "SEQUENCE"
            image.name = f"FBP Projector Sequence • {os.path.basename(source_path)}"
        except FBP_DATA_ERRORS:
            pass
    return image, max(1, duration)


def _projector_transform(context, distance):
    active = getattr(context, "object", None)
    rig = fbp_resolve_rig_from_any_object(active, context)
    plane = getattr(rig, "fbp_plane_target", None) if rig is not None else None
    if plane is not None:
        matrix = plane.matrix_world
        target = matrix.translation.copy()
        normal = (matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
        location = target + normal * max(0.01, float(distance))
        rotation = (target - location).to_track_quat("-Z", "Y").to_euler()
        return location, rotation, rig
    cursor = getattr(getattr(context, "scene", None), "cursor", None)
    location = cursor.location.copy() if cursor is not None else Vector((0.0, 0.0, 0.0))
    camera = getattr(getattr(context, "scene", None), "camera", None)
    rotation = camera.matrix_world.to_euler() if camera is not None else (0.0, 0.0, 0.0)
    return location, rotation, None


def _activate_cycles_for_projector(scene):
    """Select Cycles for projector light shaders and report whether it changed."""
    render = getattr(scene, "render", None)
    if render is None:
        return False
    if str(getattr(render, "engine", "") or "") == "CYCLES":
        return False
    render.engine = "CYCLES"
    return True


class FBP_OT_AddProjector(Operator):
    bl_idname = "fbp.add_projector"
    bl_label = "Image Projector"
    bl_description = "Create a custom Spot light that projects an image, image sequence or movie"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH", options={"SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH", options={"SKIP_SAVE"})
    files: CollectionProperty(type=OperatorFileListElement, options={"SKIP_SAVE"})
    filter_glob: StringProperty(
        default="*.bmp;*.cin;*.dpx;*.exr;*.hdr;*.jpeg;*.jpg;*.png;*.psd;*.sgi;*.tga;*.tif;*.tiff;*.webp;*.avi;*.m4v;*.mkv;*.mov;*.mp4;*.mpeg;*.mpg;*.mxf;*.ogv;*.webm",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    energy: FloatProperty(name="Power", default=1000.0, min=0.0, soft_max=5000.0)
    spot_size: FloatProperty(name="Cone", default=0.785398, min=0.017453, max=3.124139, subtype="ANGLE")
    spot_blend: FloatProperty(name="Blend", default=0.05, min=0.0, max=1.0, subtype="FACTOR")
    projection_scale: FloatProperty(name="Projection Scale", default=1.0, min=0.01, soft_max=4.0)
    distance: FloatProperty(name="Distance from Plane", default=2.0, min=0.01, soft_max=20.0, subtype="DISTANCE")
    use_alpha: BoolProperty(name="Use Alpha", default=True)
    use_selected_layer: BoolProperty(
        name="Use Selected FBP Layer",
        description="Use the image, movie or sequence already linked to the selected Frame By Plane layer",
        default=False,
        options={"SKIP_SAVE"},
    )

    def invoke(self, context, _event):
        if self.use_selected_layer:
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        source_rig = None
        source_node = None
        if self.use_selected_layer:
            source_rig = fbp_resolve_rig_from_any_object(getattr(context, "object", None), context)
            _source_material, source_node = _fbp_material_image_node(source_rig)
            image = getattr(source_node, "image", None) if source_node is not None else None
            try:
                duration = int(getattr(source_node.image_user, "frame_duration", 1) or 1)
            except FBP_DATA_ERRORS:
                duration = 1
        else:
            paths = [os.path.join(self.directory, item.name) for item in self.files]
            if not paths and self.filepath:
                paths = [self.filepath]
            try:
                image, duration = _load_projector_media(paths)
            except FBP_DATA_ERRORS as exc:
                self.report({"ERROR"}, f"Could not load projector media: {exc}")
                return {"CANCELLED"}
        if image is None:
            self.report({"ERROR"}, "Choose supported media or select an image-based Frame By Plane layer")
            return {"CANCELLED"}

        light = bpy.data.lights.new("FBP Projector", type="SPOT")
        projector = bpy.data.objects.new("FBP Projector", light)
        collection = getattr(context, "collection", None) or context.scene.collection
        collection.objects.link(projector)
        try:
            light["fbp_is_projector"] = True
            light["fbp_projector_schema"] = PROJECTOR_SCHEMA
            projector["fbp_is_projector"] = True
            projector["fbp_projector_schema"] = PROJECTOR_SCHEMA
            light.fbp_projector_scale = self.projection_scale
            light.fbp_projector_use_alpha = self.use_alpha
            light.fbp_projector_focus_distance = self.distance
            light.shadow_soft_size = 1.0
            _build_projector_nodes(light, image, frame_duration=duration, source_node=source_node)
            light.fbp_projector_image = image
            light.energy = self.energy
            light.spot_size = self.spot_size
            light.spot_blend = self.spot_blend
            light.use_shadow = True
            location, rotation, rig = _projector_transform(context, self.distance)
            projector.location = location
            projector.rotation_euler = rotation
            target_rig = source_rig or rig
            if target_rig is not None:
                projector["fbp_projector_target_layer"] = str(getattr(target_rig, "name", "") or "")
            tag_managed(projector, "PROJECTOR", user_authored=True)
            tag_managed(light, "PROJECTOR_LIGHT", user_authored=True)
        except FBP_DATA_ERRORS as exc:
            bpy.data.objects.remove(projector, do_unlink=True)
            if light.users == 0:
                bpy.data.lights.remove(light)
            self.report({"ERROR"}, f"Could not create projector: {exc}")
            return {"CANCELLED"}

        for selected in tuple(getattr(context, "selected_objects", ()) or ()):
            try:
                selected.select_set(False)
            except FBP_DATA_ERRORS:
                pass
        projector.select_set(True)
        context.view_layer.objects.active = projector
        source_kind = str(getattr(image, "source", "") or "").upper()
        media_label = "movie" if source_kind == "MOVIE" else ("sequence" if duration > 1 else "image")
        try:
            switched_to_cycles = _activate_cycles_for_projector(context.scene)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not switch the Projector scene to Cycles", exc)
            switched_to_cycles = False
        cycles_notice = (
            "Projector requires Cycles: render engine switched to Cycles."
            if switched_to_cycles
            else "Projector uses Cycles."
        )
        # Operator reports are Blender's small temporary notifications, so the
        # warning remains visible for a few seconds without blocking the user.
        self.report(
            {"WARNING"},
            f"{cycles_notice} Created from {media_label} ({duration} frame{'s' if duration != 1 else ''}).",
        )
        return {"FINISHED"}


class FBP_PT_ProjectorLight(Panel):
    bl_label = "Frame By Plane Projector"
    bl_idname = "FBP_PT_projector_light"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"
    bl_parent_id = "DATA_PT_context_light"
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return is_fbp_projector(getattr(context, "object", None))

    def draw(self, context):
        layout = configure_layout(self.layout)
        light = context.object.data
        layout.prop(light, "fbp_projector_image", text="Media")
        row = layout.row(align=False)
        row.prop(light, "fbp_projector_scale", text="Image Zoom")
        row.prop(light, "fbp_projector_use_alpha", text="Alpha")
        layout.prop(light, "fbp_projector_frame_offset", text="Frame Offset")
        layout.separator(factor=0.4)
        layout.prop(light, "energy", text="Power")
        layout.prop(light, "spot_size", text="Cone Angle")
        layout.prop(light, "shadow_soft_size", text="Projection Radius")
        layout.prop(light, "spot_blend", text="Blend")
        layout.separator(factor=0.4)
        focus = layout.box()
        focus.label(text="Focus", icon="CAMERA_DATA")
        focus.prop(light, "fbp_projector_focus_distance", text="Focus Distance")
        focus.prop(light, "fbp_projector_blur_strength", text="Defocus")
        focus.prop(light, "fbp_projector_blur_max", text="Maximum Blur")
        note = layout.box()
        note.label(text="Projection and focus blur use the light shader (Cycles).", icon="INFO")


_FBP_PREVIOUS_LIGHT_ADD_CALLBACK = globals().get("_FBP_LIGHT_ADD_CALLBACK")


def draw_fbp_projector_light_add(self, context):
    """Place Projector with Blender's native Light creation tools."""
    layout = self.layout
    layout.separator()
    layout.operator_context = "INVOKE_DEFAULT"
    layout.operator(
        "fbp.add_projector",
        text="Frame By Plane Projector",
        icon="LIGHT_SPOT",
    ).use_selected_layer = False
    rig = fbp_resolve_rig_from_any_object(getattr(context, "object", None), context)
    _material, source_node = _fbp_material_image_node(rig)
    if source_node is not None and getattr(source_node, "image", None) is not None:
        layout.operator(
            "fbp.add_projector",
            text="Project Selected FBP Layer",
            icon="IMAGE_DATA",
        ).use_selected_layer = True


_FBP_LIGHT_ADD_CALLBACK = draw_fbp_projector_light_add


classes = (FBP_OT_AddProjector, FBP_PT_ProjectorLight)


_LIGHT_PROPERTIES = (
    "fbp_projector_image",
    "fbp_projector_scale",
    "fbp_projector_use_alpha",
    "fbp_projector_frame_offset",
    "fbp_projector_focus_distance",
    "fbp_projector_blur_strength",
    "fbp_projector_blur_max",
)


def _remove_light_add_callbacks():
    seen = set()
    for callback in (draw_fbp_projector_light_add, _FBP_PREVIOUS_LIGHT_ADD_CALLBACK):
        if callback is None or id(callback) in seen:
            continue
        seen.add(id(callback))
        try:
            bpy.types.VIEW3D_MT_light_add.remove(callback)
        except FBP_DATA_ERRORS:
            continue


def _remove_projector_properties():
    return unregister_type_properties(bpy.types.Light, _LIGHT_PROPERTIES)


def register():
    is_background = bool(getattr(bpy.app, "background", False))
    classes_registered = False
    try:
        if not is_background:
            register_classes(classes)
            classes_registered = True
        bpy.types.Light.fbp_projector_image = PointerProperty(
            name="Projector Image", type=bpy.types.Image, update=_update_projector_image
        )
        bpy.types.Light.fbp_projector_scale = FloatProperty(
            name="Projection Scale", default=1.0, min=0.01, soft_max=4.0,
            update=_update_projector_scale,
        )
        bpy.types.Light.fbp_projector_use_alpha = BoolProperty(
            name="Use Alpha", default=True, update=_update_projector_alpha
        )
        bpy.types.Light.fbp_projector_frame_offset = IntProperty(
            name="Frame Offset", default=0, min=-1048574, max=1048574,
            update=_update_projector_frame_offset,
        )
        bpy.types.Light.fbp_projector_focus_distance = FloatProperty(
            name="Focus Distance", description="Distance from the projector where the image is sharp",
            default=2.0, min=0.001, soft_max=100.0, subtype="DISTANCE", update=_update_projector_focus,
        )
        bpy.types.Light.fbp_projector_blur_strength = FloatProperty(
            name="Defocus", description="How quickly the projection becomes blurred away from the focus distance",
            default=0.0, min=0.0, soft_max=4.0, max=20.0, update=_update_projector_focus,
        )
        bpy.types.Light.fbp_projector_blur_max = FloatProperty(
            name="Maximum Blur", description="Maximum image-space blur radius used by the projector shader",
            default=0.03, min=0.0, soft_max=0.1, max=0.5, subtype="FACTOR", update=_update_projector_focus,
        )
        if not is_background:
            _remove_light_add_callbacks()
            bpy.types.VIEW3D_MT_light_add.append(draw_fbp_projector_light_add)
    except Exception:
        _remove_light_add_callbacks()
        _remove_projector_properties()
        if classes_registered:
            unregister_classes(classes)
        raise


def unregister():
    _remove_light_add_callbacks()
    _remove_projector_properties()
    if not bool(getattr(bpy.app, "background", False)):
        unregister_classes(classes)
