"""Shader effect nodes and their routing through the UV, Color and Mask stages.

Moved out of :mod:`geometry_nodes` (8.6.0), which re-exports every name defined
here, so ``geometry_nodes.<name>`` keeps working for callers and tests. The
helpers it uses still live in :mod:`geometry_nodes` and are imported from it;
this module is imported at the end of that one, once they all exist.
"""

import bpy

from .geometry_nodes import (  # noqa: E402 - geometry_nodes imports this module last
    ASCII_ATLAS_COLUMNS,
    ASCII_PRESET_ROWS,
    FBP_DATA_ERRORS,
    FBP_EFFECT_ASCII,
    FBP_EFFECT_ASCII_MATRIX,
    FBP_EFFECT_DEPTH_BLUR,
    FBP_EFFECT_DITHER,
    FBP_EFFECT_DOT_MATRIX,
    FBP_EFFECT_GRADIENT_LIGHT,
    FBP_EFFECT_GRADIENT_MASK,
    FBP_EFFECT_HALFTONE,
    FBP_EFFECT_LAYER_BLEND,
    FBP_EFFECT_NOISE_MASK,
    FBP_EFFECT_PIXELATE,
    FBP_EFFECT_REGISTRY,
    FBP_EFFECT_VORONOI_MASK,
    FBP_EFFECT_WAVE_MASK,
    FBP_LOCAL_EFFECT_MASK_WIRING_VERSION,
    FBP_SHADER_CHAIN_WIRING_VERSION,
    FBP_SHADER_STAGE_ORDER,
    _FBP_GATED_EFFECT_NODES,
    _fbp_cast_effect_value,
    _fbp_debug_mode_value,
    _fbp_definition_samples_property,
    _fbp_effect_ref,
    _fbp_effect_runtime_value,
    _fbp_effect_uses_multi_instances,
    _fbp_effect_values_equal,
    _fbp_ensure_effect_alpha_targets,
    _fbp_gate_properties,
    _fbp_link_single,
    _fbp_mask_target_map,
    _fbp_material_alpha_targets,
    _fbp_material_for_shader_node,
    _fbp_material_is_owned,
    _fbp_material_layer_alpha_source,
    _fbp_node_socket,
    _fbp_plane,
    _fbp_primary_color_shader,
    _fbp_scene_camera,
    _fbp_sync_gated_node_mutes,
    _fbp_sync_imported_mask_image,
    _fbp_sync_layer_blend_mode,
    _fbp_sync_mask_source,
    _fbp_sync_object_mask_helper,
    _fbp_sync_private_shader_source,
    _fbp_sync_sample_tap_mutes,
    defaultdict,
    effect_instance_id,
    effect_instance_token,
    fbp_effect_debug_mode,
    fbp_effect_definition,
    fbp_effect_input_source,
    fbp_effect_instance_channel,
    fbp_effect_instance_channel_value,
    fbp_effect_mask_target,
    fbp_mask_stack_operation,
    fbp_normalize_effect_id,
    fbp_read_effect_instance_animation_state,
    fbp_warn,
    is_node_view_helper,
    layout_layer_material,
    node_view_annotations_enabled,
    node_view_is_current,
    split_effect_instance_token,
    tidy_effect_group,
)


# ---------------------------------------------------------------------------
# Shader effect nodes and routing
# ---------------------------------------------------------------------------


def _fbp_plane_materials(rig):
    plane = _fbp_plane(rig)
    if not plane or not getattr(plane, "data", None):
        return []
    try:
        return [
            mat
            for mat in plane.data.materials
            if (
                mat
                and _fbp_material_is_owned(mat)
                and getattr(mat, "node_tree", None)
                and mat.node_tree
            )
        ]
    except FBP_DATA_ERRORS:
        return []


def _fbp_shader_image_node(material):
    """Return only the image node owned by the current FBP native material."""
    if not material or not material.node_tree:
        return None
    preferred = material.node_tree.nodes.get("FBP_Native_Media_Texture")
    if preferred and getattr(preferred, "type", "") == "TEX_IMAGE":
        return preferred
    for node in material.node_tree.nodes:
        try:
            if (
                getattr(node, "type", "") == "TEX_IMAGE"
                and bool(node.get("fbp_native_sequence_node", False))
            ):
                return node
        except FBP_DATA_ERRORS:
            continue
    return None


def _fbp_gradient_ramp_node(material):
    if not material or not material.node_tree:
        return None
    node = material.node_tree.nodes.get("FBP_ColorRamp")
    if node and getattr(node, "type", "") == "VALTORGB":
        return node
    for candidate in material.node_tree.nodes:
        try:
            if getattr(candidate, "type", "") == "VALTORGB" and bool(candidate.get("fbp_gradient_ramp", False)):
                return candidate
        except FBP_DATA_ERRORS:
            continue
    return None


def _fbp_procedural_color_source(material, *, create=False):
    """Return a stable color source for solid and gradient FBP materials."""
    if not material or not material.node_tree:
        return None
    image_node = _fbp_shader_image_node(material)
    if image_node:
        return _fbp_node_socket(image_node.outputs, "Color")
    ramp = _fbp_gradient_ramp_node(material)
    if ramp:
        return _fbp_node_socket(ramp.outputs, "Color")

    nodes = material.node_tree.nodes
    # Mesh effects that generate new faces or instances store the sampled
    # source result in named attributes. Use that real per-element color as the
    # input to every Image/Mask effect below the Mesh row.
    attribute_node_names = []
    try:
        if str(material.get("fbp_attribute_color_name", "") or ""):
            attribute_node_names.append("FBP Sampled Instance Color")
        if str(material.get("fbp_text_matrix_color_attribute", "") or ""):
            attribute_node_names.append("FBP Text Matrix Color")
    except FBP_DATA_ERRORS:
        pass
    attribute_node_names.extend((
        "FBP Glass Source Color",
        "FBP Crystal Source Color",
    ))
    for node_name in attribute_node_names:
        attribute = nodes.get(node_name)
        if attribute is None:
            continue
        color_output = _fbp_node_socket(
            getattr(attribute, "outputs", ()), "Color"
        )
        if color_output is not None:
            return color_output

    source = nodes.get("FBP_Procedural_Color_Source")
    if source and getattr(source, "type", "") == "RGB":
        # Files saved before the color sync fix can hold a stale source color:
        # the solid material's stored color is the one the user picked.
        try:
            if bool(material.get("fbp_color_material", False)) and not bool(material.get("fbp_holdout_material", False)):
                stored = tuple(float(v) for v in tuple(material.get("fbp_color_value", ()))[:4])
                if len(stored) == 4 and any(
                    abs(float(a) - b) > 1.0e-6
                    for a, b in zip(tuple(source.outputs[0].default_value), stored, strict=True)
                ):
                    source.outputs[0].default_value = stored
        except (*FBP_DATA_ERRORS, TypeError, ValueError):
            pass
        return _fbp_node_socket(source.outputs, "Color", 0)
    if not create:
        return None

    shader = _fbp_primary_color_shader(material)
    color_input = None
    if shader:
        color_input = (
            _fbp_node_socket(shader.inputs, "Color")
            or _fbp_node_socket(shader.inputs, "Base Color")
            or _fbp_node_socket(shader.inputs, "Base Color", 0)
        )
    raw_color = getattr(color_input, "default_value", (1.0, 1.0, 1.0, 1.0))
    try:
        color = tuple(raw_color)
    except TypeError:
        # Holdout and other non-color shaders can expose a scalar first input.
        # A procedural color source is still allowed to fall back safely.
        color = (1.0, 1.0, 1.0, 1.0)
    if len(color) < 4:
        color = tuple(color[:3]) + (1.0,)
    try:
        stored = tuple(material.get("fbp_color_value", color))
        if len(stored) >= 4:
            color = stored
    except FBP_DATA_ERRORS:
        pass
    try:
        source = nodes.new("ShaderNodeRGB")
        source.name = "FBP_Procedural_Color_Source"
        source.label = "Frame by Plane Color Source"
        source.location = (-380.0, 80.0)
        source["fbp_procedural_color_source"] = True
        source.outputs[0].default_value = color
        return source.outputs[0]
    except FBP_DATA_ERRORS:
        return None


def _fbp_material_color_source(material, *, create=False):
    return _fbp_procedural_color_source(material, create=create)


def _fbp_material_color_target(material):
    shader = _fbp_primary_color_shader(material)
    if not shader:
        return None
    return (
        _fbp_node_socket(shader.inputs, "Color")
        or _fbp_node_socket(shader.inputs, "Base Color")
        or _fbp_node_socket(shader.inputs, "Base Color", 0)
    )


def _fbp_material_uv_target(material):
    image_node = _fbp_shader_image_node(material)
    if image_node:
        return _fbp_node_socket(image_node.inputs, "Vector")
    if material and material.node_tree:
        center = material.node_tree.nodes.get("FBP_GradientCenter")
        if center:
            return _fbp_node_socket(center.inputs, "Vector", 0)
    return None


def _fbp_effect_texcoord_source(material, anchor=None):
    if not material or not material.node_tree:
        return None
    nodes = material.node_tree.nodes
    tex_coord = nodes.get("FBP_Effect_Texture_Coordinates")
    if tex_coord is None:
        try:
            tex_coord = nodes.new("ShaderNodeTexCoord")
            tex_coord.name = "FBP_Effect_Texture_Coordinates"
            tex_coord.label = "Frame by Plane Effect UV"
            x = float(getattr(anchor, "location", (0.0, 0.0))[0]) if anchor else -700.0
            y = float(getattr(anchor, "location", (0.0, 0.0))[1]) if anchor else -180.0
            tex_coord.location = (x - 420.0, y - 180.0)
        except FBP_DATA_ERRORS:
            return None
    return _fbp_node_socket(tex_coord.outputs, "UV", 2)


def _fbp_shader_effect_id(node):
    try:
        return fbp_normalize_effect_id(node.get("fbp_shader_effect_id", ""))
    except FBP_DATA_ERRORS:
        return ""


def _fbp_shader_effect_nodes(material, effect_id=None, stage=None, instance_id=""):
    if not material or not material.node_tree:
        return []
    effect_id = fbp_normalize_effect_id(effect_id) if effect_id else ""
    instance_id = str(instance_id or "")
    result = []
    for node in material.node_tree.nodes:
        node_effect_id = _fbp_shader_effect_id(node)
        if not node_effect_id:
            continue
        if effect_id and node_effect_id != effect_id:
            continue
        if instance_id and effect_instance_id(node) != instance_id:
            continue
        if stage and fbp_effect_definition(node_effect_id).get("stage") != stage:
            continue
        result.append(node)
    return result


def _fbp_find_shader_effect_nodes_for_rig(rig, effect_id, instance_id=""):
    result = []
    for material in _fbp_plane_materials(rig):
        result.extend(
            _fbp_shader_effect_nodes(
                material, effect_id=effect_id, instance_id=instance_id
            )
        )
    return result


def _fbp_shader_order_key(stage):
    return f"fbp_shader_effect_order_{str(stage or '').lower()}"


def _fbp_shader_node_token(node):
    """Return the concrete stack token for one shader node."""
    effect_id = _fbp_shader_effect_id(node)
    if not effect_id:
        return ""
    instance_id = effect_instance_id(node)
    return (
        effect_instance_token(effect_id, instance_id)
        if instance_id and _fbp_effect_uses_multi_instances(effect_id)
        else effect_id
    )


def _fbp_shader_token_effect_id(token):
    """Resolve current effect IDs and concrete instance tokens uniformly."""
    effect_id, _instance_id = split_effect_instance_token(str(token or ""))
    return fbp_normalize_effect_id(effect_id or token)


def _fbp_canonical_shader_order_token(token):
    """Collapse ghost instance tokens for effects whose policy is SINGLE."""
    raw = str(token or "").strip()
    effect_id, instance_id = split_effect_instance_token(raw)
    effect_id = fbp_normalize_effect_id(effect_id or raw)
    if not effect_id:
        return ""
    if _fbp_effect_uses_multi_instances(effect_id) and instance_id:
        return effect_instance_token(effect_id, instance_id)
    return effect_id


def _fbp_stage_node_tokens(material, stage):
    """Scan one material stage once for its concrete node tokens.

    Returns ``(node_by_token, tokens_by_effect, node_tokens)`` where
    ``node_tokens`` keeps node-tree order and ``node_by_token`` keeps the last
    node for a repeated token, matching the previous dict-comprehension scans.
    """
    node_by_token = {}
    tokens_by_effect = {}
    node_tokens = []
    for node in _fbp_shader_effect_nodes(material, stage=stage):
        token = _fbp_shader_node_token(node)
        if not token:
            continue
        node_by_token[token] = node
        node_tokens.append(token)
        tokens_by_effect.setdefault(_fbp_shader_effect_id(node), []).append(token)
    return node_by_token, tokens_by_effect, node_tokens


def _fbp_get_rig_shader_stage_order(rig, stage):
    try:
        raw = str(rig.get(_fbp_shader_order_key(stage), "") or "")
    except FBP_DATA_ERRORS:
        raw = ""
    result = []
    for raw_token in raw.split("|"):
        token = _fbp_canonical_shader_order_token(raw_token)
        effect_id = _fbp_shader_token_effect_id(token)
        definition = fbp_effect_definition(effect_id)
        if (
            definition.get("kind") == "SHADER"
            and definition.get("stage") == stage
            and token not in result
        ):
            result.append(token)
    return result


def _fbp_set_rig_shader_stage_order(rig, stage, order):
    normalized = []
    for raw_token in order:
        token = _fbp_canonical_shader_order_token(raw_token)
        effect_id = _fbp_shader_token_effect_id(token)
        definition = fbp_effect_definition(effect_id)
        if definition.get("kind") != "SHADER" or definition.get("stage") != stage:
            continue
        if token not in normalized:
            normalized.append(token)
    value = "|".join(normalized)
    key = _fbp_shader_order_key(stage)
    try:
        if str(rig.get(key, "") or "") != value:
            rig[key] = value
    except FBP_DATA_ERRORS:
        pass
    return normalized


def _fbp_get_shader_stage_order(material, stage):
    stage = str(stage or "")
    active_by_token, tokens_by_effect, node_tokens = _fbp_stage_node_tokens(
        material, stage
    )
    raw = ""
    try:
        raw = str(material.get(_fbp_shader_order_key(stage), "") or "")
    except FBP_DATA_ERRORS:
        pass
    order = []
    for raw_token in raw.split("|"):
        token = _fbp_canonical_shader_order_token(raw_token)
        if token in active_by_token and token not in order:
            order.append(token)
    for effect_id in FBP_SHADER_STAGE_ORDER.get(stage, ()):
        for token in tokens_by_effect.get(effect_id, ()):
            if token not in order:
                order.append(token)
    for token in node_tokens:
        if token not in order:
            order.append(token)
    return order


def _fbp_set_shader_stage_order(material, stage, order):
    active_by_token, tokens_by_effect, node_tokens = _fbp_stage_node_tokens(
        material, stage
    )
    normalized = []
    for raw_token in order:
        token = _fbp_canonical_shader_order_token(raw_token)
        if token in active_by_token:
            if token not in normalized:
                normalized.append(token)
            continue
        effect_id = fbp_normalize_effect_id(token)
        for candidate in tokens_by_effect.get(effect_id, ()):
            if candidate not in normalized:
                normalized.append(candidate)
                break
    for token in node_tokens:
        if token not in normalized:
            normalized.append(token)
    value = "|".join(normalized)
    key = _fbp_shader_order_key(stage)
    try:
        if str(material.get(key, "") or "") != value:
            material[key] = value
    except FBP_DATA_ERRORS:
        pass
    return normalized


def _fbp_stage_effect_nodes(material, stage):
    nodes_by_token = _fbp_stage_node_tokens(material, stage)[0]
    return [
        nodes_by_token[token]
        for token in _fbp_get_shader_stage_order(material, stage)
        if token in nodes_by_token
    ]


def _fbp_local_mask_helper_nodes(material, kind=None):
    if not material or not material.node_tree:
        return []
    result = []
    for node in material.node_tree.nodes:
        try:
            if not bool(node.get("fbp_local_effect_mask_helper", False)):
                continue
            if kind and str(node.get("fbp_local_effect_mask_kind", "") or "") != kind:
                continue
            result.append(node)
        except FBP_DATA_ERRORS:
            continue
    return result


def _fbp_follow_local_mask_chain(material, socket):
    if not material or not material.node_tree or socket is None:
        return None
    current = socket
    visited = set()
    for _ in range(64):
        links = [link for link in material.node_tree.links if link.from_socket == current]
        if not links:
            return None
        link = links[0]
        node = link.to_node
        if node in visited:
            return link.to_socket
        visited.add(node)
        try:
            is_helper = bool(node.get("fbp_local_effect_mask_helper", False))
        except FBP_DATA_ERRORS:
            is_helper = False
        if not is_helper:
            return link.to_socket
        current = _fbp_node_socket(node.outputs, "Color", 0) or _fbp_node_socket(node.outputs, "Value", 0)
        if current is None:
            return link.to_socket
    return None


def _fbp_remove_local_mask_helpers(material, kind=None):
    if not material or not material.node_tree:
        return False
    changed = False
    for node in list(_fbp_local_mask_helper_nodes(material, kind=kind)):
        try:
            material.node_tree.nodes.remove(node)
            changed = True
        except FBP_DATA_ERRORS:
            pass
    return changed


def _fbp_mask_output_socket(node):
    if node is None:
        return None
    definition = fbp_effect_definition(_fbp_shader_effect_id(node))
    name = str(definition.get("mask_output_socket", "Mask Out") or "Mask Out")
    return _fbp_node_socket(node.outputs, name)


def _fbp_local_masks_by_target(rig, mask_nodes):
    """Return active local mask nodes grouped by concrete receiver token."""
    nodes_by_id = {}
    for node in tuple(mask_nodes or ()):
        mask_id = _fbp_shader_effect_id(node)
        if not mask_id:
            continue
        try:
            if bool(getattr(node, "mute", False)):
                continue
        except FBP_DATA_ERRORS:
            pass
        if _fbp_mask_output_socket(node) is not None:
            nodes_by_id[mask_id] = node
    if not rig or not nodes_by_id:
        return {}
    result = {}
    for target, mask_ids in _fbp_mask_target_map(rig).items():
        if target == "LAYER":
            continue
        # Combine in visible Mask-stage order (the order of ``mask_nodes``),
        # not the cached effect-id order: Subtract/Difference depend on it.
        wanted = set(mask_ids)
        resolved = [node for mask_id, node in nodes_by_id.items() if mask_id in wanted]
        if resolved:
            result[target] = resolved
    return result



def _fbp_connect_local_mask_uv_inputs(material, mask_nodes, source):
    """Connect procedural/image mask sampling to the correct pre-effect UV.

    Local masks on UV effects must sample the vector entering that specific UV
    effect. Masks on color effects sample the stable layer UV. Never feed a
    color socket into a mask UV input: Blender will coerce it to a vector and
    produce masks that appear frozen, uniform or dependent on image colors.
    """
    if not material or not material.node_tree or source is None:
        return False
    changed = False
    links = material.node_tree.links
    for node in tuple(mask_nodes or ()):
        definition = fbp_effect_definition(_fbp_shader_effect_id(node))
        socket_name = str(definition.get("uv_input_socket", "") or "")
        if not socket_name:
            continue
        target = _fbp_node_socket(node.inputs, socket_name)
        if target is None:
            continue
        try:
            if len(target.links) == 1 and target.links[0].from_socket == source:
                continue
            for link in list(target.links):
                links.remove(link)
            links.new(source, target)
            changed = True
        except FBP_DATA_ERRORS:
            continue
    return changed


def _fbp_local_mask_preview_socket(rig, mask_nodes):
    """Return the visible debug output of the last local mask in stack order."""
    if not rig:
        return None, ""
    preview_socket = None
    preview_id = ""
    for node in tuple(mask_nodes or ()):
        mask_id = _fbp_shader_effect_id(node)
        if not mask_id or fbp_effect_mask_target(rig, mask_id) == "LAYER":
            continue
        try:
            if bool(getattr(node, "mute", False)):
                continue
        except FBP_DATA_ERRORS:
            pass
        if fbp_effect_debug_mode(rig, mask_id) == "FINAL":
            continue
        definition = fbp_effect_definition(mask_id)
        socket = _fbp_node_socket(
            node.outputs, str(definition.get("output_socket", "Alpha Out") or "Alpha Out")
        ) or _fbp_mask_output_socket(node)
        if socket is not None:
            preview_socket = socket
            preview_id = mask_id
    return preview_socket, preview_id


def _fbp_apply_local_mask_preview(material, rig, mask_nodes, current, *, x=0.0, y=0.0):
    """Replace the color result with a grayscale local-mask diagnostic preview."""
    if not material or not material.node_tree or current is None:
        return current
    preview_socket, preview_id = _fbp_local_mask_preview_socket(rig, mask_nodes)
    if preview_socket is None:
        return current
    try:
        preview = material.node_tree.nodes.new("ShaderNodeMixRGB")
        preview.blend_type = "MIX"
        preview.name = f"FBP Local Mask Preview • {preview_id}"
        preview.label = "Local Mask Preview"
        preview.location = (x, y)
        preview.inputs[1].default_value = (0.0, 0.0, 0.0, 1.0)
        preview.inputs[2].default_value = (1.0, 1.0, 1.0, 1.0)
        preview["fbp_local_effect_mask_helper"] = True
        preview["fbp_local_effect_mask_kind"] = "COLOR"
        preview["fbp_local_effect_mask_preview"] = preview_id
        material.node_tree.links.new(preview_socket, preview.inputs[0])
        return preview.outputs[0]
    except FBP_DATA_ERRORS:
        return current


def _fbp_combine_mask_sockets(
    material,
    current,
    socket,
    operation,
    *,
    kind,
    index,
    x=0.0,
    y=0.0,
):
    """Build one bounded boolean-matte operation and return its result socket."""
    if (
        material is None
        or material.node_tree is None
        or current is None
        or socket is None
    ):
        return current
    operation = str(operation or "INTERSECT").upper()
    links = material.node_tree.links

    def helper(math_operation, label, offset=0):
        node = material.node_tree.nodes.new("ShaderNodeMath")
        node.operation = math_operation
        node.name = f"FBP Mask Stack {label} {kind} {index}.{offset}"
        node.label = label
        node.location = (
            x + index * 105.0 + offset * 70.0,
            y - 120.0,
        )
        node["fbp_local_effect_mask_helper"] = True
        node["fbp_local_effect_mask_kind"] = kind
        node["fbp_mask_stack_operation"] = operation
        return node

    if operation == "ADD":
        combine = helper("MAXIMUM", "Add Masks")
        links.new(current, combine.inputs[0])
        links.new(socket, combine.inputs[1])
        return combine.outputs[0]
    if operation == "SUBTRACT":
        combine = helper("SUBTRACT", "Subtract Mask")
        combine.use_clamp = True
        links.new(current, combine.inputs[0])
        links.new(socket, combine.inputs[1])
        return combine.outputs[0]
    if operation == "DIFFERENCE":
        subtract = helper("SUBTRACT", "Mask Difference", 0)
        absolute = helper("ABSOLUTE", "Absolute Difference", 1)
        links.new(current, subtract.inputs[0])
        links.new(socket, subtract.inputs[1])
        links.new(subtract.outputs[0], absolute.inputs[0])
        return absolute.outputs[0]
    combine = helper("MULTIPLY", "Intersect Masks")
    links.new(current, combine.inputs[0])
    links.new(socket, combine.inputs[1])
    return combine.outputs[0]


def _fbp_combined_mask_factor(
    material,
    mask_nodes,
    *,
    kind,
    x=0.0,
    y=0.0,
):
    active_nodes = []
    for node in tuple(mask_nodes or ()):
        try:
            if bool(getattr(node, "mute", False)):
                continue
        except FBP_DATA_ERRORS:
            pass
        if _fbp_mask_output_socket(node) is not None:
            active_nodes.append(node)
    if not active_nodes:
        return None
    rig = None
    try:
        owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
        rig = bpy.data.objects.get(owner_name) if owner_name else None
    except FBP_DATA_ERRORS:
        rig = None
    current = _fbp_mask_output_socket(active_nodes[0])
    for index, node in enumerate(active_nodes[1:], 1):
        current = _fbp_combine_mask_sockets(
            material,
            current,
            _fbp_mask_output_socket(node),
            fbp_mask_stack_operation(rig, _fbp_shader_effect_id(node)),
            kind=kind,
            index=index,
            x=x,
            y=y,
        )
    return current


def _fbp_stage_external_target(material, _source_node, stage, effect_nodes):
    """Return the socket after an effect stage for image or procedural materials."""
    if stage != "COLOR" or not material or not material.node_tree:
        return None
    effect_set = set(effect_nodes)
    color_pass_nodes = set(_fbp_mask_color_pass_nodes(material))
    source = _fbp_material_color_source(material, create=True)
    candidate_sources = [source]
    candidate_sources.extend(
        _fbp_node_socket(
            node.outputs,
            fbp_effect_definition(_fbp_shader_effect_id(node)).get("output_socket", ""),
        )
        for node in effect_nodes
    )
    for candidate in reversed(candidate_sources):
        if candidate is None:
            continue
        for link in material.node_tree.links:
            if link.from_socket != candidate:
                continue
            if link.to_node in effect_set:
                continue
            try:
                is_helper = bool(link.to_node.get("fbp_local_effect_mask_helper", False))
            except FBP_DATA_ERRORS:
                is_helper = False
            target_socket = (
                _fbp_follow_local_mask_chain(material, candidate)
                if is_helper else link.to_socket
            )
            if target_socket is None or getattr(target_socket, "node", None) in effect_set:
                continue
            if getattr(target_socket, "node", None) in color_pass_nodes:
                # Color Key passes always sit after the stage and are rewired
                # by the rebuild; the stage itself ends at the shader input.
                break
            return target_socket
    return _fbp_material_color_target(material)


def _fbp_stage_external_uv_source(material, _source_node=None, effect_nodes=()):
    if not material or not material.node_tree:
        return None
    target = _fbp_material_uv_target(material)
    effect_set = set(effect_nodes)
    targets = [target] if target is not None else []
    targets.extend(
        _fbp_node_socket(
            node.inputs,
            fbp_effect_definition(_fbp_shader_effect_id(node)).get("input_socket", ""),
        )
        for node in effect_nodes
    )
    def through_mask_mixers(socket):
        # Local-mask UV mixers are deleted and rebuilt with the stage; follow
        # them back to their unmasked input instead of returning a socket that
        # is about to disappear (e.g. after the masked effect was removed).
        seen = set()
        while socket is not None and socket.node.get("fbp_local_effect_mask_helper"):
            if socket.node in seen or len(socket.node.inputs) < 2:
                return None
            seen.add(socket.node)
            unmasked = socket.node.inputs[1]
            socket = unmasked.links[0].from_socket if unmasked.is_linked else None
        if socket is None or socket.node in effect_set:
            return None
        return socket

    for link in material.node_tree.links:
        if link.to_socket in targets and link.from_node not in effect_set:
            source = through_mask_mixers(link.from_socket)
            if source is not None:
                return source
    anchor = _fbp_shader_image_node(material) or _fbp_gradient_ramp_node(material)
    return _fbp_effect_texcoord_source(material, anchor)


def _fbp_auxiliary_uv_source(material, _source_node=None):
    """Return the vector used by UV-aware color effects on every FBP material."""
    if not material or not material.node_tree:
        return None
    target = _fbp_material_uv_target(material)
    if target is not None and getattr(target, "is_linked", False):
        try:
            return target.links[0].from_socket
        except (AttributeError, IndexError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    source = _fbp_effect_texcoord_source(
        material,
        _fbp_shader_image_node(material) or _fbp_gradient_ramp_node(material),
    )
    if source is not None and target is not None:
        try:
            material.node_tree.links.new(source, target)
        except FBP_DATA_ERRORS:
            pass
    return source


def _fbp_connect_color_aux_uv(material, _source_node=None, source=None):
    if not material or not material.node_tree:
        return False
    source = source or _fbp_auxiliary_uv_source(material)
    if source is None:
        return False
    changed = False
    for node in _fbp_stage_effect_nodes(material, "COLOR"):
        definition = fbp_effect_definition(_fbp_shader_effect_id(node))
        socket_name = str(definition.get("uv_input_socket", "") or "")
        if not socket_name:
            continue
        target = _fbp_node_socket(node.inputs, socket_name)
        if target is None:
            continue
        try:
            if len(target.links) == 1 and target.links[0].from_socket == source:
                continue
            for link in list(target.links):
                material.node_tree.links.remove(link)
            material.node_tree.links.new(source, target)
            changed = True
        except FBP_DATA_ERRORS:
            pass
    return changed


def _fbp_remove_stage_links(material, _source_node, stage, effect_nodes):
    if not material or not material.node_tree:
        return
    links = material.node_tree.links
    effect_set = set(effect_nodes)
    if stage == "COLOR":
        source = _fbp_material_color_source(material, create=True)
        target = _fbp_material_color_target(material)
        for link in list(links):
            if (
                link.from_socket == source
                or link.from_node in effect_set
                or link.to_node in effect_set
                or (target is not None and link.to_socket == target and link.from_node in effect_set)
            ):
                try:
                    links.remove(link)
                except FBP_DATA_ERRORS:
                    pass
        return

    if stage == "MASK":
        targets = set(_fbp_material_alpha_targets(material))
        for link in list(links):
            if (
                link.from_node in effect_set
                or link.to_node in effect_set
                or link.to_socket in targets
            ):
                try:
                    links.remove(link)
                except FBP_DATA_ERRORS:
                    pass
        return

    if stage == "UV":
        target = _fbp_material_uv_target(material)
        for link in list(links):
            if (
                (target is not None and link.to_socket == target)
                or link.from_node in effect_set
                or link.to_node in effect_set
            ):
                try:
                    links.remove(link)
                except FBP_DATA_ERRORS:
                    pass


def _fbp_apply_global_mask_stack(material, rig, mask_nodes, base_alpha):
    """Combine ordered raw mattes, then apply the result to layer alpha."""
    if (
        material is None
        or material.node_tree is None
        or base_alpha is None
    ):
        return base_alpha, False
    factor = _fbp_combined_mask_factor(
        material,
        mask_nodes,
        kind="ALPHA",
        x=180.0,
        y=-620.0,
    )
    if factor is None:
        return base_alpha, False
    try:
        apply = material.node_tree.nodes.new("ShaderNodeMath")
        apply.operation = "MULTIPLY"
        apply.name = "FBP Mask Stack Layer Alpha"
        apply.label = "Apply Mask Stack"
        apply.location = (520.0, -620.0)
        apply["fbp_local_effect_mask_helper"] = True
        apply["fbp_local_effect_mask_kind"] = "ALPHA"
        apply["fbp_mask_stack_final"] = True
        material.node_tree.links.new(base_alpha, apply.inputs[0])
        material.node_tree.links.new(factor, apply.inputs[1])
        return apply.outputs[0], True
    except FBP_DATA_ERRORS:
        return base_alpha, False


def _fbp_clear_mask_alpha_chain_links(material, mask_nodes):
    """Remove invalid global-alpha links without touching local Mask Out links.

    A mask moved from Layer to one specific effect used to keep its previous
    Alpha In/Alpha Out chain. The local receiver then worked, but the same mask
    could still clip the complete layer. Preserve UV and diagnostic-preview
    links while removing only links that belong to the alpha chain.
    """
    if not material or not material.node_tree:
        return False
    alpha_inputs = set()
    alpha_outputs = set()
    for node in tuple(mask_nodes or ()):
        definition = fbp_effect_definition(_fbp_shader_effect_id(node))
        input_socket = _fbp_node_socket(
            node.inputs, str(definition.get("input_socket", "") or "")
        )
        output_socket = _fbp_node_socket(
            node.outputs, str(definition.get("output_socket", "") or "")
        )
        if input_socket is not None:
            alpha_inputs.add(input_socket)
        if output_socket is not None:
            alpha_outputs.add(output_socket)
    if not alpha_inputs and not alpha_outputs:
        return False
    alpha_targets = set(_fbp_material_alpha_targets(material))
    changed = False
    for link in list(material.node_tree.links):
        remove = link.to_socket in alpha_inputs
        if not remove and link.from_socket in alpha_outputs:
            helper_kind = ""
            try:
                helper_kind = str(link.to_node.get("fbp_local_effect_mask_kind", "") or "")
            except FBP_DATA_ERRORS:
                pass
            remove = (
                link.to_socket in alpha_inputs
                or link.to_socket in alpha_targets
                or helper_kind == "ALPHA"
            )
        if not remove:
            continue
        try:
            material.node_tree.links.remove(link)
            changed = True
        except FBP_DATA_ERRORS:
            pass
    return changed


def _fbp_local_target_by_mask(rig):
    """Return ``{mask_effect_id: target_ref}`` for locally targeted masks."""
    if not rig:
        return {}
    return {
        mask_id: target
        for target, mask_ids in _fbp_mask_target_map(rig).items()
        for mask_id in mask_ids
    }


def _fbp_connect_base_mask_uv_inputs(
    material, rig, mask_nodes, uv_source, *, local_target_by_mask=None
):
    """Feed the final layer UV into every mask that does not target a UV effect.

    Masks attached to a UV effect receive that effect's incoming vector while
    the UV stage is rebuilt. Every other mask samples the final layer UV, which
    changes whenever the UV stage is reordered or rebuilt.
    """
    if local_target_by_mask is None:
        local_target_by_mask = _fbp_local_target_by_mask(rig)
    base_uv_masks = []
    for node in tuple(mask_nodes or ()):
        target_effect_id = local_target_by_mask.get(_fbp_shader_effect_id(node), "LAYER")
        if str(fbp_effect_definition(target_effect_id).get("stage", "") or "") != "UV":
            base_uv_masks.append(node)
    return _fbp_connect_local_mask_uv_inputs(material, base_uv_masks, uv_source)


def _fbp_relink_effect_alpha(material, effect_nodes, base_alpha):
    """Route effect alpha through local masks, then the global Mask Stack."""
    if not material or not material.node_tree:
        return False
    changed = _fbp_remove_local_mask_helpers(material, kind="ALPHA")
    links = material.node_tree.links
    rig = None
    try:
        owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
        rig = bpy.data.objects.get(owner_name) if owner_name else None
    except FBP_DATA_ERRORS:
        rig = None
    mask_nodes = _fbp_stage_effect_nodes(material, "MASK")
    changed = _fbp_clear_mask_alpha_chain_links(material, mask_nodes) or changed
    local_by_target = _fbp_local_masks_by_target(rig, mask_nodes)
    current = base_alpha
    for node in effect_nodes:
        effect_id = _fbp_shader_effect_id(node)
        definition = fbp_effect_definition(effect_id)
        previous = current
        alpha_input = _fbp_node_socket(node.inputs, str(definition.get("alpha_input_socket", "") or ""))
        if alpha_input is not None and current is not None:
            try:
                if len(alpha_input.links) != 1 or alpha_input.links[0].from_socket != current:
                    for link in list(alpha_input.links):
                        links.remove(link)
                    links.new(current, alpha_input)
                    changed = True
            except FBP_DATA_ERRORS:
                pass
        effect_alpha = _fbp_node_socket(node.outputs, str(definition.get("alpha_output_socket", "") or "")) or current
        target_token = _fbp_effect_ref(
            effect_id,
            (
                effect_instance_id(node)
                if _fbp_effect_uses_multi_instances(effect_id)
                else ""
            ),
        )
        masks = local_by_target.get(target_token, ())
        if masks and previous is not None and effect_alpha is not None:
            factor = _fbp_combined_mask_factor(
                material, masks, kind="ALPHA", x=float(node.location.x), y=float(node.location.y) - 220.0
            )
            if factor is not None:
                inv = material.node_tree.nodes.new("ShaderNodeMath")
                inv.operation = "SUBTRACT"
                inv.inputs[0].default_value = 1.0
                inv.name = f"FBP Local Alpha Mask Invert • {effect_id}"
                inv["fbp_local_effect_mask_helper"] = True
                inv["fbp_local_effect_mask_kind"] = "ALPHA"
                a = material.node_tree.nodes.new("ShaderNodeMath")
                a.operation = "MULTIPLY"
                a.name = f"FBP Local Alpha Original • {effect_id}"
                a["fbp_local_effect_mask_helper"] = True
                a["fbp_local_effect_mask_kind"] = "ALPHA"
                b = material.node_tree.nodes.new("ShaderNodeMath")
                b.operation = "MULTIPLY"
                b.name = f"FBP Local Alpha Effect • {effect_id}"
                b["fbp_local_effect_mask_helper"] = True
                b["fbp_local_effect_mask_kind"] = "ALPHA"
                add = material.node_tree.nodes.new("ShaderNodeMath")
                add.operation = "ADD"
                add.name = f"FBP Local Alpha Result • {effect_id}"
                add["fbp_local_effect_mask_helper"] = True
                add["fbp_local_effect_mask_kind"] = "ALPHA"
                for helper_index, helper in enumerate((inv, a, b, add)):
                    helper.location = (float(node.location.x) + 90.0 + helper_index * 70.0, float(node.location.y) - 260.0)
                links.new(factor, inv.inputs[1])
                links.new(previous, a.inputs[0])
                links.new(inv.outputs[0], a.inputs[1])
                links.new(effect_alpha, b.inputs[0])
                links.new(factor, b.inputs[1])
                links.new(a.outputs[0], add.inputs[0])
                links.new(b.outputs[0], add.inputs[1])
                current = add.outputs[0]
            else:
                current = effect_alpha
        else:
            current = effect_alpha

    global_masks = []
    local_target_by_mask = _fbp_local_target_by_mask(rig)
    for index, node in enumerate(mask_nodes):
        node.location = (180.0 + index * 190.0, -420.0)
        if local_target_by_mask.get(_fbp_shader_effect_id(node), "LAYER") == "LAYER":
            global_masks.append(node)
    changed = _fbp_connect_base_mask_uv_inputs(
        material, rig, mask_nodes, _fbp_auxiliary_uv_source(material),
        local_target_by_mask=local_target_by_mask,
    ) or changed
    current, mask_changed = _fbp_apply_global_mask_stack(
        material,
        rig,
        global_masks,
        current,
    )
    changed = mask_changed or changed
    if current is None:
        return changed
    has_alpha_effect = bool(global_masks) or any(
        bool(fbp_effect_definition(_fbp_shader_effect_id(node)).get("alpha_output_socket"))
        for node in effect_nodes
    )
    targets = _fbp_material_alpha_targets(material)
    if has_alpha_effect and not targets:
        targets = _fbp_ensure_effect_alpha_targets(material)
    for target in targets:
        try:
            if len(target.links) == 1 and target.links[0].from_socket == current:
                continue
            for link in list(target.links):
                links.remove(link)
            links.new(current, target)
            changed = True
        except FBP_DATA_ERRORS:
            pass
    return changed

def _fbp_color_stage_evaluation_nodes(material, rig=None):
    """Return color effect nodes in their real evaluation order."""
    effect_nodes = _fbp_stage_effect_nodes(material, "COLOR")
    if rig is None:
        try:
            owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
            rig = bpy.data.objects.get(owner_name) if owner_name else None
        except FBP_DATA_ERRORS:
            rig = None
    regular_nodes = []
    final_nodes = []
    for node in effect_nodes:
        effect_id = _fbp_shader_effect_id(node)
        instance_id = effect_instance_id(node)
        if rig and fbp_effect_input_source(rig, effect_id, instance_id) == "FINAL":
            final_nodes.append(node)
        else:
            regular_nodes.append(node)
    return regular_nodes + final_nodes


def _fbp_mask_color_pass_nodes(material, mask_nodes=None):
    """Return mask nodes that also filter color (Color Key despill)."""
    if mask_nodes is None:
        mask_nodes = _fbp_stage_effect_nodes(material, "MASK")
    result = []
    for node in tuple(mask_nodes or ()):
        definition = fbp_effect_definition(_fbp_shader_effect_id(node))
        if (
            _fbp_node_socket(node.inputs, str(definition.get("color_input_socket", "") or "")) is not None
            and _fbp_node_socket(node.outputs, str(definition.get("color_output_socket", "") or "")) is not None
        ):
            result.append(node)
    return result


def _fbp_apply_mask_color_passes(material, rig, mask_nodes, current):
    """Route the final layer color through every Layer-targeted color pass.

    Masks normally only shape alpha. Color Key also greys the leftover key
    color (Despill), so when it targets the whole layer the completed color
    chain flows through its ``Color In``/``Color Out`` pair. Locally targeted
    keys leave the color untouched: their matte already blends one effect.
    """
    if not material or not material.node_tree or current is None:
        return current
    tree = material.node_tree
    local_target_by_mask = _fbp_local_target_by_mask(rig)
    for node in _fbp_mask_color_pass_nodes(material, mask_nodes):
        effect_id = _fbp_shader_effect_id(node)
        definition = fbp_effect_definition(effect_id)
        color_in = _fbp_node_socket(node.inputs, str(definition.get("color_input_socket", "") or ""))
        color_out = _fbp_node_socket(node.outputs, str(definition.get("color_output_socket", "") or ""))
        try:
            for link in list(color_in.links):
                tree.links.remove(link)
        except FBP_DATA_ERRORS:
            continue
        if local_target_by_mask.get(effect_id, "LAYER") != "LAYER":
            continue
        try:
            tree.links.new(current, color_in)
            current = color_out
        except FBP_DATA_ERRORS:
            continue
    try:
        material["fbp_mask_color_pass"] = bool(_fbp_mask_color_pass_nodes(material, mask_nodes))
    except FBP_DATA_ERRORS:
        pass
    return current


def _fbp_rebuild_local_mask_receivers(material):
    """Rebuild every shader stage that can receive a local mask."""
    changed = _fbp_rebuild_shader_stage(material, "UV")
    changed = _fbp_rebuild_shader_stage(material, "COLOR") or changed
    try:
        if int(material.get("fbp_local_effect_mask_wiring_version", 0) or 0) != FBP_LOCAL_EFFECT_MASK_WIRING_VERSION:
            material["fbp_local_effect_mask_wiring_version"] = FBP_LOCAL_EFFECT_MASK_WIRING_VERSION
            changed = True
    except FBP_DATA_ERRORS:
        pass
    return changed


def _fbp_rebuild_shader_stage(material, stage, source_override=None, target_override=None):
    """Rebuild one shader stage, then restore the links modifiers drive."""
    result = _fbp_rebuild_shader_stage_links(material, stage, source_override, target_override)
    if material is not None and getattr(material, "node_tree", None) is not None:
        try:
            from .effect_shells import fbp_shell_relink_material
            fbp_shell_relink_material(material)
        except (ImportError, *FBP_DATA_ERRORS):
            pass
        fbp_tidy_layer_material(material)
    return result


# Shared coordinates stay in the Source section even when one effect uses them.
_FBP_NODE_VIEW_SOURCE_TYPES = {"ShaderNodeTexCoord", "ShaderNodeUVMap", "ShaderNodeNewGeometry"}


def _fbp_node_view_owned(node):
    """True for nodes Frame By Plane generated in a layer material."""
    try:
        if node.bl_idname in {"NodeFrame", "NodeComment"}:
            return False
        name = str(node.name or "")
        if name.startswith(("FBP", "fbp")) or str(node.label or "").startswith("Frame by Plane"):
            return True
        return any(str(key).startswith("fbp_") for key in node.keys())
    except FBP_DATA_ERRORS:
        return False


def fbp_layer_material_view_sections(material):
    """Group a layer material's generated nodes into readable sections.

    Returns ``{section: [(label, nodes), ...]}`` for
    :func:`node_layout.layout_layer_material`. Each effect becomes one block
    with the nodes that only feed it (its modifier inputs, local mask mix).
    """
    tree = getattr(material, "node_tree", None)
    if tree is None:
        return {}
    owned = []
    for node in tree.nodes:
        if not _fbp_node_view_owned(node):
            continue
        parent = getattr(node, "parent", None)
        if parent is not None and not is_node_view_helper(parent):
            continue  # inside an artist's own frame
        owned.append(node)
    if not owned:
        return {}
    members = set(owned)
    producers = {node: set() for node in owned}
    consumers = {node: set() for node in owned}
    for link in tuple(tree.links):
        try:
            source, target = link.from_node, link.to_node
        except FBP_DATA_ERRORS:
            continue
        if source in members and target in members and source is not target:
            producers[target].add(source)
            consumers[source].add(target)

    rig = None
    try:
        owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
        rig = bpy.data.objects.get(owner_name) if owner_name else None
    except FBP_DATA_ERRORS:
        rig = None
    stage_of = {}
    order_of = {}
    for stage in ("UV", "COLOR", "MASK"):
        try:
            ordered = (
                _fbp_color_stage_evaluation_nodes(material, rig)
                if stage == "COLOR" else _fbp_stage_effect_nodes(material, stage)
            )
        except FBP_DATA_ERRORS:
            ordered = []
        for index, node in enumerate(ordered):
            if node in members:
                stage_of[node] = stage
                order_of[node] = index
    for node in owned:
        if node in stage_of:
            continue
        effect_id = _fbp_shader_effect_id(node)
        if effect_id:
            stage = str(fbp_effect_definition(effect_id).get("stage", "") or "COLOR")
            stage_of[node] = stage if stage in {"UV", "COLOR", "MASK"} else "COLOR"
            order_of[node] = 10_000 + len(order_of)

    block_of = {node: node for node in stage_of}
    token_owner = {}
    for node in stage_of:
        effect_id = _fbp_shader_effect_id(node)
        token = _fbp_effect_ref(
            effect_id,
            effect_instance_id(node) if _fbp_effect_uses_multi_instances(effect_id) else "",
        )
        token_owner.setdefault(token, node)
        token_owner.setdefault(effect_id, node)
    by_name = {node.name: node for node in owned}
    image_nodes = [node for node in owned if node.bl_idname == "ShaderNodeTexImage" and node not in block_of]
    for node in image_nodes:
        block_of[node] = "IMAGE"
    for node in owned:
        if node in block_of:
            continue
        try:
            target_name = str(node.get("fbp_shell_target", "") or "")
            target_token = str(node.get("fbp_local_effect_mask_target", "") or "")
        except FBP_DATA_ERRORS:
            target_name = target_token = ""
        anchor = by_name.get(target_name) if target_name else token_owner.get(target_token)
        if anchor is not None and anchor in block_of:
            block_of[node] = block_of[anchor]

    # Nodes whose only neighbours belong to one block join that block.
    changed = True
    while changed:
        changed = False
        for node in owned:
            if node in block_of or node.bl_idname in _FBP_NODE_VIEW_SOURCE_TYPES:
                continue
            outs = consumers[node]
            ins = producers[node]
            if not outs:
                continue
            blocks = {block_of[item] for item in outs if item in block_of}
            blocks.update(block_of[item] for item in ins if item in block_of)
            if len(blocks) != 1:
                continue
            if any(item not in block_of for item in outs):
                continue
            if any(item not in block_of and producers[item] for item in ins):
                continue
            block_of[node] = next(iter(blocks))
            changed = True

    def upstream_stages(node):
        seen = set()
        stack = list(producers[node])
        stages = set()
        while stack:
            item = stack.pop()
            if item in seen:
                continue
            seen.add(item)
            block = block_of.get(item)
            if block == "IMAGE" or item in image_nodes:
                stages.add("IMAGE")
            elif block is not None:
                stages.add(stage_of.get(block, "COLOR"))
            stack.extend(producers[item])
        return stages

    sections = {key: [] for key in ("SOURCE", "UV", "IMAGE", "COLOR", "MASK", "OUTPUT")}
    leftovers = {"SOURCE": [], "MASK": [], "OUTPUT": []}
    for node in owned:
        if node in block_of:
            continue
        if not producers[node]:
            leftovers["SOURCE"].append(node)
            continue
        stages = upstream_stages(node)
        leftovers["MASK" if stages and stages <= {"MASK", "UV"} and "MASK" in stages else "OUTPUT"].append(node)

    grouped = defaultdict(list)
    for node, block in block_of.items():
        grouped[block].append(node)
    for stage in ("UV", "COLOR", "MASK"):
        effects = sorted(
            (node for node in stage_of if stage_of[node] == stage),
            key=lambda item: (order_of.get(item, 0), item.name),
        )
        for index, node in enumerate(effects):
            label = str(node.label or fbp_effect_definition(_fbp_shader_effect_id(node)).get("label", "") or node.name)
            if bool(getattr(node, "mute", False)):
                label += " (hidden)"
            sections[stage].append((f"{index + 1} · {label}", grouped[node]))
    if grouped.get("IMAGE"):
        sections["IMAGE"].append(("Layer image", grouped["IMAGE"]))
    if leftovers["SOURCE"]:
        sections["SOURCE"].append(("Source", leftovers["SOURCE"]))
    if leftovers["MASK"]:
        sections["MASK"].append(("Combine masks", leftovers["MASK"]))
    if leftovers["OUTPUT"]:
        sections["OUTPUT"].append(("Output", leftovers["OUTPUT"]))
    return {key: value for key, value in sections.items() if value}


def fbp_tidy_layer_material(material, *, force=False, annotate=None):
    """Keep a layer material readable: effects in order, framed and labelled.

    Display only: nodes are moved and framed, never renamed or relinked. The
    check is a cheap signature, so calling this after every rebuild is fine.
    """
    tree = getattr(material, "node_tree", None)
    if tree is None:
        return False
    try:
        if not bool(material.get("fbp_effect_rig_owner", "")) and not any(
            _fbp_shader_effect_id(node) for node in tree.nodes
        ):
            return False
    except FBP_DATA_ERRORS:
        return False
    if annotate is None:
        annotate = node_view_annotations_enabled()
    if not force and node_view_is_current(tree, annotate=annotate):
        return True
    try:
        sections = fbp_layer_material_view_sections(material)
        return layout_layer_material(
            tree,
            sections,
            title=str(getattr(material, "name", "") or ""),
            annotate=annotate,
            force=True,
        )
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not tidy the layer material's nodes", exc)
        return False


def fbp_tidy_effect_group(node_group, effect_id="", *, force=False, annotate=None):
    """Lay out one generated effect group (never a custom or user-edited one)."""
    if node_group is None:
        return False
    try:
        if bool(node_group.get("fbp_user_editable_effect_group", False)):
            return False
    except FBP_DATA_ERRORS:
        return False
    definition = fbp_effect_definition(effect_id) if effect_id else {}
    if bool(definition.get("custom", False)):
        return False
    title = str(definition.get("label", "") or "")
    description = str(definition.get("description", "") or "")
    asset_id = str(definition.get("asset_id", "") or "")
    if asset_id:
        # Some groups serve several effects (Mesh Wiggle and Wind Bender):
        # name them all and leave out a description that fits only one.
        sharing = [
            str(other.get("label", "") or key)
            for key, other in FBP_EFFECT_REGISTRY.items()
            if str(other.get("asset_id", "") or "") == asset_id
        ]
        if len(sharing) > 1:
            title = " / ".join(sharing[:3])
            description = "Shared by: " + ", ".join(sharing) + "."
    return tidy_effect_group(
        node_group,
        title=title,
        description=description,
        annotate=annotate,
        force=force,
    )


def fbp_tidy_all_node_views(*, force=True, annotate=None):
    """Re-tidy every generated layer material and effect group in the file."""
    count = 0
    for material in tuple(bpy.data.materials):
        try:
            if getattr(material, "library", None) is not None or material.node_tree is None:
                continue
        except FBP_DATA_ERRORS:
            continue
        if fbp_tidy_layer_material(material, force=force, annotate=annotate):
            count += 1
    for node_group in tuple(bpy.data.node_groups):
        try:
            if getattr(node_group, "library", None) is not None:
                continue
            effect_id = str(node_group.get("fbp_effect_id", "") or "")
            shell = bool(node_group.get("fbp_shell_group", False))
            if shell:
                from .effect_shells import fbp_tidy_shell_group
                if fbp_tidy_shell_group(node_group, force=force, annotate=annotate):
                    count += 1
                continue
            if not effect_id:
                continue
        except (ImportError, *FBP_DATA_ERRORS):
            continue
        if fbp_tidy_effect_group(node_group, effect_id, force=force, annotate=annotate):
            count += 1
    return count


def _fbp_rebuild_shader_stage_links(material, stage, source_override=None, target_override=None):
    if not material or not material.node_tree:
        return False
    effect_nodes = _fbp_stage_effect_nodes(material, stage)
    links = material.node_tree.links
    image_node = _fbp_shader_image_node(material)

    if stage == "UV":
        source = source_override or _fbp_stage_external_uv_source(material, image_node, effect_nodes)
        target = _fbp_material_uv_target(material)
        _fbp_remove_local_mask_helpers(material, kind="UV")
        _fbp_remove_stage_links(material, image_node, stage, effect_nodes)
        current = source
        anchor = image_node or _fbp_gradient_ramp_node(material)
        anchor_x = float(getattr(anchor, "location", (-80.0, 0.0))[0])
        anchor_y = float(getattr(anchor, "location", (0.0, 0.0))[1])
        rig = None
        try:
            owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
            rig = bpy.data.objects.get(owner_name) if owner_name else None
        except FBP_DATA_ERRORS:
            rig = None
        local_masks_by_target = _fbp_local_masks_by_target(
            rig, _fbp_stage_effect_nodes(material, "MASK")
        )
        for index, node in enumerate(effect_nodes):
            effect_id = _fbp_shader_effect_id(node)
            definition = fbp_effect_definition(effect_id)
            input_socket = _fbp_node_socket(node.inputs, definition.get("input_socket", ""))
            output_socket = _fbp_node_socket(node.outputs, definition.get("output_socket", ""))
            previous = current
            if current and input_socket:
                _fbp_link_single(material.node_tree, current, input_socket)
            effect_output = output_socket or current
            node.location = (anchor_x - 360.0 + index * 220.0, anchor_y - 220.0)
            target_token = _fbp_effect_ref(
                effect_id,
                (
                    effect_instance_id(node)
                    if _fbp_effect_uses_multi_instances(effect_id)
                    else ""
                ),
            )
            masks = local_masks_by_target.get(target_token, ())
            if masks and previous is not None and effect_output is not None:
                _fbp_connect_local_mask_uv_inputs(material, masks, previous)
                factor = _fbp_combined_mask_factor(
                    material, masks, kind="UV",
                    x=float(node.location.x), y=float(node.location.y) - 120.0,
                )
                if factor is not None:
                    mixer = material.node_tree.nodes.new("ShaderNodeMixRGB")
                    mixer.blend_type = "MIX"
                    mixer.name = f"FBP UV Effect Mask Mix • {effect_id}"
                    mixer.label = "UV Effect Mask"
                    mixer.location = (float(node.location.x) + 150.0, float(node.location.y))
                    mixer["fbp_local_effect_mask_helper"] = True
                    mixer["fbp_local_effect_mask_kind"] = "UV"
                    mixer["fbp_local_effect_mask_target"] = target_token
                    links.new(factor, mixer.inputs[0])
                    links.new(previous, mixer.inputs[1])
                    links.new(effect_output, mixer.inputs[2])
                    current = mixer.outputs[0]
                else:
                    current = effect_output
            else:
                current = effect_output
        if current and target:
            _fbp_link_single(material.node_tree, current, target)
        _fbp_connect_color_aux_uv(material, image_node, current)
        # Removing the old UV stage links also detached mask UV inputs that
        # sampled the previous final UV; restore them from the new chain end.
        _fbp_connect_base_mask_uv_inputs(
            material, rig, _fbp_stage_effect_nodes(material, "MASK"), current
        )
        try:
            material["fbp_shader_chain_wiring_version"] = FBP_SHADER_CHAIN_WIRING_VERSION
        except FBP_DATA_ERRORS:
            pass
        return bool(current)

    if stage == "MASK":
        rig = None
        try:
            owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
            rig = bpy.data.objects.get(owner_name) if owner_name else None
        except FBP_DATA_ERRORS:
            rig = None
        # A color-pass mask (Color Key) sits at the end of the color chain, so
        # adding, removing or retargeting it rewires the color stage too.
        color_pass = bool(_fbp_mask_color_pass_nodes(material, effect_nodes))
        try:
            color_pass = color_pass or bool(material.get("fbp_mask_color_pass", False))
        except FBP_DATA_ERRORS:
            pass
        if (
            (rig and bool(_fbp_mask_target_map(rig)))
            or bool(_fbp_local_mask_helper_nodes(material))
            or color_pass
        ):
            return _fbp_rebuild_local_mask_receivers(material)
        _fbp_remove_stage_links(material, image_node, stage, effect_nodes)
        layer_alpha = _fbp_material_layer_alpha_source(material, image_node)
        evaluation_nodes = _fbp_color_stage_evaluation_nodes(material, rig)
        return _fbp_relink_effect_alpha(material, evaluation_nodes, layer_alpha)

    if stage != "COLOR":
        return False

    source = _fbp_material_color_source(material, create=True)
    target = target_override or _fbp_stage_external_target(material, image_node, stage, effect_nodes)
    if source is None or target is None:
        return False
    _fbp_remove_local_mask_helpers(material, kind="COLOR")
    uv_source = _fbp_auxiliary_uv_source(material, image_node)
    layer_alpha = _fbp_material_layer_alpha_source(material, image_node)
    _fbp_remove_stage_links(material, image_node, stage, effect_nodes)
    current = source
    anchor = image_node or _fbp_gradient_ramp_node(material) or getattr(source, "node", None)
    anchor_x = float(getattr(anchor, "location", (-180.0, 0.0))[0])
    anchor_y = float(getattr(anchor, "location", (0.0, 0.0))[1])
    rig = None
    try:
        owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
        rig = bpy.data.objects.get(owner_name) if owner_name else None
    except FBP_DATA_ERRORS:
        rig = None
    # Final Material is deliberately evaluated as a terminal pass. This keeps
    # the graph acyclic: normal Previous/Original effects build the regular
    # stack first, then every Final Material effect processes that completed
    # result in its relative stack order.
    evaluation_nodes = _fbp_color_stage_evaluation_nodes(material, rig)

    local_masks_by_target = _fbp_local_masks_by_target(
        rig, _fbp_stage_effect_nodes(material, "MASK")
    )
    for index, node in enumerate(evaluation_nodes):
        effect_id = _fbp_shader_effect_id(node)
        definition = fbp_effect_definition(effect_id)
        input_socket = _fbp_node_socket(node.inputs, definition.get("input_socket", ""))
        output_socket = _fbp_node_socket(node.outputs, definition.get("output_socket", ""))
        input_source = (
            fbp_effect_input_source(rig, effect_id, effect_instance_id(node))
            if rig else "PREVIOUS"
        )
        previous = current
        node_source = source if input_source == "ORIGINAL" else current
        if node_source and input_socket:
            # Every effect input owns exactly one upstream link. Clearing stale
            # links here is essential after add/reorder/undo and makes the real
            # stack deterministic for downstream effects such as Color Ramp.
            _fbp_link_single(material.node_tree, node_source, input_socket)
        if uv_source:
            uv_input = _fbp_node_socket(node.inputs, definition.get("uv_input_socket", ""))
            if uv_input:
                _fbp_link_single(material.node_tree, uv_source, uv_input)
        effect_output = output_socket or current
        node.location = (anchor_x + 120.0 + index * 240.0, anchor_y + 250.0)
        target_token = _fbp_effect_ref(
            effect_id,
            (
                effect_instance_id(node)
                if _fbp_effect_uses_multi_instances(effect_id)
                else ""
            ),
        )
        masks = local_masks_by_target.get(target_token, ())
        if masks and previous is not None and effect_output is not None:
            # Color effects do not alter the layer UV. Their masks therefore
            # sample the stable UV source, while the color blend still mixes
            # the previous and processed colors below.
            _fbp_connect_local_mask_uv_inputs(material, masks, uv_source)
            factor = _fbp_combined_mask_factor(
                material, masks, kind="COLOR", x=float(node.location.x), y=float(node.location.y)
            )
            if factor is not None:
                mixer = material.node_tree.nodes.new("ShaderNodeMixRGB")
                mixer.blend_type = "MIX"
                mixer.name = f"FBP Effect Mask Mix • {effect_id}"
                mixer.label = "Effect Mask"
                mixer.location = (float(node.location.x) + 150.0, float(node.location.y))
                mixer["fbp_local_effect_mask_helper"] = True
                mixer["fbp_local_effect_mask_kind"] = "COLOR"
                mixer["fbp_local_effect_mask_target"] = target_token
                links.new(factor, mixer.inputs[0])
                links.new(previous, mixer.inputs[1])
                links.new(effect_output, mixer.inputs[2])
                current = mixer.outputs[0]
            else:
                current = effect_output
        else:
            current = effect_output
    current = _fbp_apply_mask_color_passes(
        material,
        rig,
        _fbp_stage_effect_nodes(material, "MASK"),
        current,
    )
    current = _fbp_apply_local_mask_preview(
        material,
        rig,
        _fbp_stage_effect_nodes(material, "MASK"),
        current,
        x=anchor_x + 120.0 + max(1, len(evaluation_nodes)) * 240.0,
        y=anchor_y + 250.0,
    )
    if not _fbp_link_single(material.node_tree, current, target):
        try:
            already_linked = bool(
                len(target.links) == 1 and target.links[0].from_socket == current
            )
        except FBP_DATA_ERRORS:
            already_linked = False
        if not already_linked:
            return False
    _fbp_relink_effect_alpha(material, evaluation_nodes, layer_alpha)
    try:
        material["fbp_shader_chain_wiring_version"] = FBP_SHADER_CHAIN_WIRING_VERSION
    except FBP_DATA_ERRORS:
        pass
    return True


def _fbp_depth_blur_focus_distance(rig, scene=None):
    """Resolve the effective focus distance for the Depth Blur effect."""
    fallback = max(0.0, float(getattr(rig, "fbp_depth_blur_focus_distance", 10.0) or 10.0))
    if not bool(getattr(rig, "fbp_depth_blur_use_camera_focus", True)):
        return fallback
    scene = scene or getattr(bpy.context, "scene", None)
    camera = _fbp_scene_camera(scene)
    camera_data = getattr(camera, "data", None) if camera else None
    dof = getattr(camera_data, "dof", None) if camera_data else None
    if camera is None or dof is None:
        return fallback
    focus_object = getattr(dof, "focus_object", None)
    if focus_object is not None:
        try:
            local = camera.matrix_world.inverted_safe() @ focus_object.matrix_world.translation
            return max(0.0, abs(float(local.z)))
        except FBP_DATA_ERRORS:
            pass
    try:
        return max(0.0, float(getattr(dof, "focus_distance", fallback) or fallback))
    except FBP_DATA_ERRORS:
        return fallback


def _fbp_sync_source_texel_inputs(rig, node, material=None):
    """Push inverse source-image dimensions into image-aware sampling effects."""
    if not rig or not node:
        return False
    material = material or _fbp_material_for_shader_node(rig, node)
    source_node = _fbp_shader_image_node(material) if material else None
    source_image = getattr(source_node, "image", None) if source_node else None
    width = height = 1
    try:
        size = tuple(getattr(source_image, "size", (1, 1)) or (1, 1))
        width = max(1, int(size[0]))
        height = max(1, int(size[1]))
    except FBP_DATA_ERRORS:
        pass
    if source_image is None and _fbp_shader_effect_id(node) == FBP_EFFECT_DITHER:
        # Procedural Color/Gradient planes have no source image dimensions.
        # Give ordered dithering a stable virtual raster instead of collapsing
        # the whole plane into a single 1x1 cell.
        width = height = 1024
    changed = False
    for socket_name, value in (("Texel X", 1.0 / float(width)), ("Texel Y", 1.0 / float(height))):
        socket = _fbp_node_socket(getattr(node, "inputs", ()), socket_name)
        if socket is None or _fbp_effect_values_equal(getattr(socket, "default_value", None), value):
            continue
        try:
            socket.default_value = value
            changed = True
        except FBP_DATA_ERRORS:
            pass
    return changed


def _fbp_sync_depth_blur_runtime_inputs(rig, node, material=None, scene=None):
    """Push mode and camera focus into one private depth-blur node."""
    if not rig or not node:
        return False
    changed = False
    depth_mode = str(getattr(rig, "fbp_depth_blur_mode", "MANUAL") or "MANUAL") == "DEPTH"
    values = {
        "Mode": 1.0 if depth_mode else 0.0,
    }
    # Camera focus can change every frame, but it is irrelevant in Manual mode.
    # Avoid resolving camera/object matrices and touching the socket when the
    # effect uses a fixed radius.
    if depth_mode:
        values["Focus Distance"] = _fbp_depth_blur_focus_distance(rig, scene=scene)
    for socket_name, value in values.items():
        socket = _fbp_node_socket(getattr(node, "inputs", ()), socket_name)
        if socket is None or _fbp_effect_values_equal(getattr(socket, "default_value", None), value):
            continue
        try:
            socket.default_value = value
            changed = True
        except FBP_DATA_ERRORS:
            pass
    return changed


def _fbp_sync_gradient_light_ramp(rig, node, *, property_names=None):
    """Apply the compact Gradient controls to its editable native ramp."""
    requested = None if property_names is None else {
        str(name) for name in property_names if str(name or "")
    }
    color_property = "fbp_gradient_shadow_color"
    softness_property = "fbp_gradient_softness"
    if requested is not None and not requested.intersection(
        {color_property, softness_property}
    ):
        return False
    node_group = getattr(node, "node_tree", None)
    if node_group is None:
        return False
    ramp_node = None
    for candidate in tuple(getattr(node_group, "nodes", ()) or ()):
        try:
            if (
                getattr(candidate, "type", "") == "VALTORGB"
                and bool(candidate.get("fbp_effect_color_ramp", False))
                and str(candidate.get("fbp_effect_ramp_role", "") or "")
                == "GRADIENT_LIGHT"
            ):
                ramp_node = candidate
                break
        except FBP_DATA_ERRORS:
            continue
    color_ramp = getattr(ramp_node, "color_ramp", None)
    elements = sorted(
        tuple(getattr(color_ramp, "elements", ()) or ()),
        key=lambda item: float(getattr(item, "position", 0.0) or 0.0),
    )
    if len(elements) < 2:
        return False
    changed = False
    shadow, light = elements[0], elements[-1]
    if requested is None or color_property in requested:
        try:
            color = tuple(
                max(0.0, min(1.0, float(component)))
                for component in tuple(
                    getattr(rig, color_property, (0.0, 0.0, 0.05, 1.0))
                )[:4]
            )
            if len(color) == 4 and not _fbp_effect_values_equal(
                tuple(shadow.color), color
            ):
                shadow.color = color
                changed = True
        except FBP_DATA_ERRORS:
            pass
    if requested is None or softness_property in requested:
        try:
            softness = max(
                0.0,
                min(1.0, float(getattr(rig, softness_property, 0.5) or 0.0)),
            )
            half_width = max(0.0005, softness * 0.5)
            shadow_position = 0.5 - half_width
            light_position = 0.5 + half_width
            if not _fbp_effect_values_equal(shadow.position, shadow_position):
                shadow.position = shadow_position
                changed = True
            if not _fbp_effect_values_equal(light.position, light_position):
                light.position = light_position
                changed = True
        except FBP_DATA_ERRORS:
            pass
    return changed


def _fbp_set_shader_node_values(
    rig,
    effect_id,
    node,
    scene=None,
    *,
    property_names=None,
):
    """Update one shader effect node, optionally limiting writes to changed RNA properties."""
    definition = fbp_effect_definition(effect_id)
    requested = None if property_names is None else {
        str(name) for name in property_names if str(name or "")
    }
    full_update = requested is None
    changed = False

    # Image binding is structural state. It is synchronized on full updates and
    # by the frame-change hot path, not on every unrelated slider movement.
    if full_update and bool(definition.get("image_aware", False)):
        material = _fbp_material_for_shader_node(rig, node)
        has_image, source_changed = _fbp_sync_private_shader_source(
            material, getattr(node, "node_tree", None)
        )
        changed = source_changed or changed
        use_image = _fbp_node_socket(getattr(node, "inputs", ()), "Use Image Sample")
        if use_image is not None:
            value = 1.0 if has_image else 0.0
            if not _fbp_effect_values_equal(getattr(use_image, "default_value", None), value):
                try:
                    use_image.default_value = value
                    changed = True
                except FBP_DATA_ERRORS:
                    pass

    if full_update and bool(definition.get("uses_source_texel", False)):
        material = _fbp_material_for_shader_node(rig, node)
        changed = _fbp_sync_source_texel_inputs(rig, node, material=material) or changed

    mask_source_properties = {
        str(definition.get("mask_source_property", "") or ""),
        *(str(name or "") for name in definition.get("extra_properties", ()) or ()),
    }
    mask_source_properties.discard("")
    if bool(definition.get("mask_source_aware", False)) and (
        full_update or requested is None or bool(requested.intersection(mask_source_properties))
    ):
        _has_mask, mask_changed = _fbp_sync_mask_source(rig, effect_id, node)
        changed = mask_changed or changed

    if bool(definition.get("imported_mask_aware", False)):
        prefix = str(definition.get("imported_mask_prefix", "fbp_imported_mask") or "fbp_imported_mask")
        if full_update or requested is None or f"{prefix}_path" in requested:
            _has_imported_mask, imported_changed = _fbp_sync_imported_mask_image(rig, node, effect_id)
            changed = imported_changed or changed

    if effect_id == FBP_EFFECT_LAYER_BLEND and (
        full_update or requested is None or "fbp_layer_blend_mode" in requested
    ):
        changed = _fbp_sync_layer_blend_mode(rig, node) or changed

    if bool(definition.get("object_mask_aware", False)) and (
        full_update
        or requested is None
        or str(definition.get("object_mask_pointer_property", "") or "") in requested
    ):
        _has_object, object_changed = _fbp_sync_object_mask_helper(
            rig, effect_id, node, create=True
        )
        changed = object_changed or changed

    if effect_id == FBP_EFFECT_DEPTH_BLUR and (
        full_update or requested is None or requested & {
            "fbp_depth_blur_mode", "fbp_depth_blur_use_camera_focus",
            "fbp_depth_blur_focus_distance",
        }
    ):
        material = _fbp_material_for_shader_node(rig, node)
        changed = _fbp_sync_depth_blur_runtime_inputs(
            rig, node, material=material, scene=scene
        ) or changed

    if effect_id == FBP_EFFECT_GRADIENT_LIGHT:
        changed = _fbp_sync_gradient_light_ramp(
            rig, node, property_names=requested
        ) or changed

    for prop_name, socket_name in (definition.get("property_map", {}) or {}).items():
        if requested is not None and prop_name not in requested:
            continue
        input_socket = _fbp_node_socket(node.inputs, socket_name)
        if input_socket is None:
            continue
        try:
            instance_id = (
                effect_instance_id(node)
                if _fbp_effect_uses_multi_instances(effect_id) else ""
            )
            channel = (
                fbp_effect_instance_channel(
                    rig, effect_id, instance_id, prop_name, ensure=False
                )
                if instance_id else None
            )
            state = (
                fbp_read_effect_instance_animation_state(
                    rig, effect_id, instance_id
                )
                if instance_id else {}
            )
            speed_prop = str(definition.get("evolve_speed_property", "") or "")
            if channel is not None:
                value = fbp_effect_instance_channel_value(channel)
            elif instance_id and prop_name == speed_prop and state:
                value = state.get("speed", getattr(rig, prop_name))
            else:
                value = getattr(rig, prop_name)
            value = _fbp_effect_runtime_value(
                rig, effect_id, prop_name, value, scene=scene, node=node
            )
            value = _fbp_cast_effect_value(prop_name, value)
            value = tuple(value) if hasattr(value, "__len__") and not isinstance(value, str) else value
            if _fbp_effect_values_equal(getattr(input_socket, "default_value", None), value):
                continue
            input_socket.default_value = value
            changed = True
        except FBP_DATA_ERRORS:
            continue

    gates = _FBP_GATED_EFFECT_NODES.get(effect_id)
    if gates and (full_update or bool(requested & _fbp_gate_properties(definition, gates))):
        changed = _fbp_sync_gated_node_mutes(rig, node, gates) or changed

    if _fbp_definition_samples_property(definition) and (
        full_update or bool(requested & {_fbp_definition_samples_property(definition)})
    ):
        changed = _fbp_sync_sample_tap_mutes(rig, effect_id, node, definition) or changed

    debug_socket_name = str(definition.get("debug_socket", "") or "")
    if full_update and debug_socket_name:
        debug_socket = _fbp_node_socket(getattr(node, "inputs", ()), debug_socket_name)
        debug_value = _fbp_debug_mode_value(definition, fbp_effect_debug_mode(rig, effect_id))
        if debug_socket is not None and not _fbp_effect_values_equal(
            getattr(debug_socket, "default_value", None), debug_value
        ):
            try:
                debug_socket.default_value = debug_value
                changed = True
            except FBP_DATA_ERRORS:
                pass

    aspect_effects = {
        FBP_EFFECT_HALFTONE,
        FBP_EFFECT_DOT_MATRIX,
        FBP_EFFECT_ASCII_MATRIX,
        FBP_EFFECT_ASCII,
        FBP_EFFECT_NOISE_MASK,
        FBP_EFFECT_VORONOI_MASK,
        FBP_EFFECT_WAVE_MASK,
        FBP_EFFECT_GRADIENT_MASK,
    }
    # Aspect is derived from the current plane/UV contract rather than an RNA
    # property, so refresh it on every scoped update as well as full rebuilds.
    if effect_id in aspect_effects:
        aspect_socket = _fbp_node_socket(node.inputs, "Aspect Ratio")
        if aspect_socket is not None:
            aspect = 1.0
            aspect = _fbp_rig_plane_aspect(rig)
            if not _fbp_effect_values_equal(aspect_socket.default_value, aspect):
                try:
                    aspect_socket.default_value = aspect
                    changed = True
                except FBP_DATA_ERRORS:
                    pass

    if effect_id == FBP_EFFECT_PIXELATE:
        pixel_properties = {
            "fbp_pixelate_resolution",
            "fbp_pixelate_height",
            "fbp_pixelate_grid_mode",
            "fbp_pixelate_size",
            "fbp_pixelate_stretch",
        }
        if full_update or bool(requested & pixel_properties):
            pixels_x, pixels_y, _mode = _fbp_pixelate_grid(rig)
            for socket_name, value in (("Pixels X", float(pixels_x)), ("Pixels Y", float(pixels_y))):
                socket = _fbp_node_socket(node.inputs, socket_name)
                if socket is None or _fbp_effect_values_equal(socket.default_value, value):
                    continue
                try:
                    socket.default_value = value
                    changed = True
                except FBP_DATA_ERRORS:
                    pass

    if effect_id == FBP_EFFECT_ASCII_MATRIX:
        special_properties = {"fbp_ascii_charset", "fbp_ascii_character_count"}
        if full_update or bool(requested & special_properties):
            special_values = {
                "Charset Row": float(
                    ASCII_PRESET_ROWS.get(
                        str(getattr(rig, "fbp_ascii_charset", "CLASSIC")), 0
                    )
                ),
                "Character Count": float(
                    getattr(rig, "fbp_ascii_character_count", ASCII_ATLAS_COLUMNS)
                    or ASCII_ATLAS_COLUMNS
                ),
            }
            for socket_name, value in special_values.items():
                socket = _fbp_node_socket(node.inputs, socket_name)
                if socket is None or _fbp_effect_values_equal(socket.default_value, value):
                    continue
                try:
                    socket.default_value = value
                    changed = True
                except FBP_DATA_ERRORS:
                    pass
    return changed


def _fbp_rig_plane_aspect(rig):
    """Return physical canvas width/height, including cropped UV spans.

    Auto-cropped planes keep the original canvas pivot and a sub-rectangle of
    the source UV map. Measuring mesh bounds alone therefore turns circles into
    ellipses. Dividing each physical dimension by its active UV span restores
    the original pixel-space aspect while remaining correct for uncropped and
    extended meshes.
    """
    plane = _fbp_plane(rig)
    mesh = getattr(plane, "data", None) if plane else None
    try:
        vertices = iter(mesh.vertices)
        first = next(vertices)
        min_x = max_x = float(first.co.x)
        min_y = max_y = float(first.co.y)
        for vertex in vertices:
            x = float(vertex.co.x)
            y = float(vertex.co.y)
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
        width = max_x - min_x
        height = max_y - min_y
        if width <= 1e-8 or height <= 1e-8:
            return 1.0

        uv_span_x = uv_span_y = 1.0
        uv_layer = getattr(getattr(mesh, "uv_layers", None), "active", None)
        uv_data = getattr(uv_layer, "data", None)
        if uv_data:
            first_uv = uv_data[0].uv
            min_u = max_u = float(first_uv.x)
            min_v = max_v = float(first_uv.y)
            for loop_uv in uv_data[1:]:
                uv = loop_uv.uv
                u = float(uv.x)
                v = float(uv.y)
                min_u = min(min_u, u)
                max_u = max(max_u, u)
                min_v = min(min_v, v)
                max_v = max(max_v, v)
            uv_span_x = max(1e-8, max_u - min_u)
            uv_span_y = max(1e-8, max_v - min_v)

        physical_aspect = (width / uv_span_x) / (height / uv_span_y)
        return max(0.001, min(1000.0, float(physical_aspect)))
    except (AttributeError, IndexError, ReferenceError, RuntimeError, StopIteration, TypeError, ValueError):
        return 1.0

def _fbp_pixelate_grid(rig):
    """Return Pixelate's effective X by Y grid from one shared contract.

    Keeping this in one helper prevents the shader update, UI preview and
    Extrude dependency from drifting apart when Pixelate settings change.
    """
    try:
        mode = str(getattr(rig, "fbp_pixelate_grid_mode", "AUTO") or "AUTO")
        size = max(1.0, float(getattr(rig, "fbp_pixelate_size", 10.0) or 10.0))
        if mode == "EXACT":
            pixels_x = max(
                1, min(8192, int(getattr(rig, "fbp_pixelate_resolution", 64) or 64))
            )
            pixels_y = max(1, int(getattr(rig, "fbp_pixelate_height", 36) or 36))
        else:
            pixels_x = max(1, min(8192, int(round(640.0 / size))))
            aspect = max(0.001, float(_fbp_rig_plane_aspect(rig) or 1.0))
            stretch = max(0.05, float(getattr(rig, "fbp_pixelate_stretch", 1.0) or 1.0))
            pixels_y = max(1, int(round(float(pixels_x) / aspect / stretch)))
    except FBP_DATA_ERRORS:
        pixels_x, pixels_y, mode = 64, 36, "AUTO"
    return pixels_x, pixels_y, mode
