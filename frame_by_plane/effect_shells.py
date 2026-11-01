"""Image effects and masks as native modifier "shells".

An image effect runs per pixel inside the plane material, which a Geometry
Nodes modifier cannot do. A shell is a small Geometry Nodes modifier that owns
the effect's parameters instead: the effect node in the material reads every
modifier input through an Object Attribute node (an RNA path to the input), so
the modifier itself does no geometry work at all. The artist then edits,
keyframes, reorders and hides the image effect from Blender's Modifiers panel
like any other modifier, and the material does the actual shading in Eevee and
Cycles.

Every built-in image effect and mask gets a shell as soon as it is added, so
Blender's Modifiers panel is the only effect stack. The Frame By Plane panel
draws the active effect's extra controls (curves, ramps, images, Grease Pencil
editing) and routes its plain settings to the same modifier inputs.
"""

from __future__ import annotations

import hashlib

import bpy

from .registration import register_classes, unregister_classes
from .runtime import FBP_DATA_ERRORS, fbp_warn


# Image effects and masks whose settings are not a plain copy of material
# socket values: they keep those settings on the layer until their shell
# renders identically (see tests/native_modifiers_regression.py).
_SHELL_EXCLUDED = {
    # Layer Blend is the layer's blend control, not a row of the stack.
    "LAYER_BLEND",
}
# Settings Frame By Plane converts before writing them to the material (the
# pixel grid derives its size from the image, blur samples stay odd): they
# stay on the layer and keep their usual controls.
_SHELL_DERIVED_PROPERTIES = {
    "fbp_pixelate_resolution",
    "fbp_pixelate_height",
    "fbp_gaussian_blur_samples",
    "fbp_directional_blur_samples",
}
_SHELL_CATEGORIES = {"BASE", "2D", "MASK"}
# Layer effects that do not run in the material (Crop and Extend resize the
# plane, Emission sets its surface, the others move or deform it). Their
# modifier is a row only: order, eye, camera and delete; the settings stay in
# the Frame By Plane panel, which shows them while the row is active.
FBP_SHELL_ROW_EFFECTS = (
    "CROP", "EXTEND", "EMISSION", "MOTION", "CAMERA_BILLBOARD", "LATTICE",
)
_SHELL_EFFECT_CACHE = None
_SHELL_TOKEN_KEY = "fbp_shell_token"
_SHELL_GROUP_KEY = "fbp_shell_group"
_SHELL_ATTR_NODE_KEY = "fbp_shell_attribute"
_SHELL_TARGET_KEY = "fbp_shell_target"
_SHELL_SOCKET_KEY = "fbp_shell_socket"
# Attribute names are stored in 64-byte buffers, and the RNA path to a modifier
# input contains the modifier name.
_MAX_ATTRIBUTE_NAME = 63


def _geo():
    from . import geometry_nodes
    return geometry_nodes


def fbp_shell_effects():
    """Every built-in image effect and mask that can live as a modifier."""
    global _SHELL_EFFECT_CACHE
    # Effect properties register module by module: key the cache on how many
    # Object properties exist, so a list built mid-registration is redone.
    key = len(bpy.types.Object.bl_rna.properties)
    if _SHELL_EFFECT_CACHE is None or _SHELL_EFFECT_CACHE[0] != key:
        from .effects_registry import FBP_EFFECT_REGISTRY
        found = tuple(
            effect_id for effect_id, definition in FBP_EFFECT_REGISTRY.items()
            if str(definition.get("category", "") or "") in _SHELL_CATEGORIES
            and str(definition.get("kind", "") or "") in {"SHADER", "MASK"}
            and effect_id not in _SHELL_EXCLUDED
        ) + tuple(
            effect_id for effect_id in FBP_SHELL_ROW_EFFECTS
            if effect_id in FBP_EFFECT_REGISTRY
        )
        _SHELL_EFFECT_CACHE = (key, found)
    return _SHELL_EFFECT_CACHE[1]


def fbp_shell_supported(effect_id):
    return str(effect_id or "").upper() in fbp_shell_effects()


def fbp_shell_is_row(effect_id):
    """True for effects whose modifier is a row without inputs."""
    return str(effect_id or "").upper() in FBP_SHELL_ROW_EFFECTS


def fbp_shell_token(modifier):
    if modifier is None or getattr(modifier, "type", "") != "NODES":
        return ""
    group = getattr(modifier, "node_group", None)
    try:
        if group is None or not bool(group.get(_SHELL_GROUP_KEY, False)):
            return ""
        return str(group.get(_SHELL_TOKEN_KEY, "") or "")
    except FBP_DATA_ERRORS:
        return ""


def fbp_shell_modifiers(rig):
    """Return ``(token, modifier)`` for every shell on the layer plane."""
    plane = _geo()._fbp_plane(rig, repair=False)
    if plane is None:
        return ()
    result = []
    for modifier in tuple(getattr(plane, "modifiers", ()) or ()):
        token = fbp_shell_token(modifier)
        if token:
            result.append((token, modifier))
    return tuple(result)


def fbp_shell_modifier(rig, effect_id, instance_id=""):
    geo = _geo()
    token = geo._fbp_effect_ref(geo.fbp_normalize_effect_id(effect_id), instance_id)
    for shell_token, modifier in fbp_shell_modifiers(rig):
        if shell_token == token:
            return modifier
    return None


def _shell_parameters(effect_id):
    """Return ``[(rig_property, socket_name, rna_property)]`` for one effect."""
    if fbp_shell_is_row(effect_id):
        return []
    definition = _geo().fbp_effect_definition(effect_id)
    result = []
    properties = bpy.types.Object.bl_rna.properties
    for prop_name, socket_name in (definition.get("property_map", {}) or {}).items():
        if prop_name in _SHELL_DERIVED_PROPERTIES:
            continue
        rna = properties.get(prop_name)
        if rna is None or rna.type not in {"FLOAT", "INT", "BOOLEAN", "ENUM"}:
            continue
        if getattr(rna, "is_array", False) and not _is_color(rna):
            continue
        result.append((prop_name, socket_name, rna))
    return result


def _is_color(rna):
    return (
        rna is not None and rna.type == "FLOAT" and bool(getattr(rna, "is_array", False))
        and str(getattr(rna, "subtype", "") or "") in {"COLOR", "COLOR_GAMMA"}
        and int(getattr(rna, "array_length", 0) or 0) in {3, 4}
    )


def _kind(rna):
    return "COLOR" if _is_color(rna) else rna.type


def _color4(value):
    values = [float(item) for item in tuple(value)[:4]]
    while len(values) < 3:
        values.append(0.0)
    if len(values) == 3:
        values.append(1.0)
    return tuple(values)


def _new_input(interface, rna, name, panel=None):
    kind = _kind(rna)
    if kind == "COLOR":
        socket = interface.new_socket(name=name, in_out="INPUT", socket_type="NodeSocketColor", parent=panel)
        socket.default_value = _color4(rna.default_array)
        try:
            socket.description = str(rna.description or "")
        except FBP_DATA_ERRORS:
            pass
        return socket
    if kind == "BOOLEAN":
        socket = interface.new_socket(name=name, in_out="INPUT", socket_type="NodeSocketBool", parent=panel)
        socket.default_value = bool(rna.default)
    elif kind == "ENUM":
        # Object attributes read numbers, so a choice is stored as its index.
        socket = interface.new_socket(name=name, in_out="INPUT", socket_type="NodeSocketInt", parent=panel)
        socket.default_value = 0
        socket.min_value = 0
        socket.max_value = max(0, len(rna.enum_items) - 1)
        try:
            socket.description = ", ".join(
                f"{index} {item.name}" for index, item in enumerate(rna.enum_items)
            )
        except FBP_DATA_ERRORS:
            pass
        return socket
    elif kind == "INT":
        socket = interface.new_socket(name=name, in_out="INPUT", socket_type="NodeSocketInt", parent=panel)
        socket.default_value = int(rna.default)
        socket.min_value = max(int(rna.hard_min), -2147483647)
        socket.max_value = min(int(rna.hard_max), 2147483647)
    else:
        socket = interface.new_socket(name=name, in_out="INPUT", socket_type="NodeSocketFloat", parent=panel)
        subtype = str(getattr(rna, "subtype", "NONE") or "NONE")
        if subtype in {"FACTOR", "ANGLE", "DISTANCE", "PERCENTAGE"}:
            try:
                socket.subtype = subtype
            except FBP_DATA_ERRORS:
                pass
        socket.default_value = float(rna.default)
        socket.min_value = float(max(rna.hard_min, -1.0e6))
        socket.max_value = float(min(rna.hard_max, 1.0e6))
    try:
        socket.description = str(rna.description or "")
    except FBP_DATA_ERRORS:
        pass
    return socket


def _build_shell_group(rig, effect_id, token):
    geo = _geo()
    definition = geo.fbp_effect_definition(effect_id)
    label = str(definition.get("label", effect_id) or effect_id)
    group = bpy.data.node_groups.new(f"FBP Shell • {getattr(rig, 'name', '')} • {label}", "GeometryNodeTree")
    group.is_modifier = True
    group[_SHELL_GROUP_KEY] = True
    group[_SHELL_TOKEN_KEY] = token
    group["fbp_owned"] = True
    try:
        group.description = (
            f"{label}: Frame By Plane effect. The work runs in Frame By Plane; "
            "this modifier holds its order and visibility (and its settings, "
            "when it shows any)."
        )
    except FBP_DATA_ERRORS:
        pass
    interface = group.interface
    interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    group_input = group.nodes.new("NodeGroupInput")
    group_input.location = (-200.0, 0.0)
    group_output = group.nodes.new("NodeGroupOutput")
    group_output.location = (200.0, 0.0)
    group.links.new(group_input.outputs["Geometry"], group_output.inputs["Geometry"])
    mapping = []
    for prop_name, socket_name, rna in _shell_parameters(effect_id):
        socket = _new_input(interface, rna, socket_name)
        mapping.append((prop_name, socket_name, socket.identifier, _kind(rna)))
    group["fbp_shell_mapping"] = [
        "\x1f".join(entry) for entry in mapping
    ]
    return group


def _shell_mapping(group):
    try:
        raw = tuple(group.get("fbp_shell_mapping", ()) or ())
    except FBP_DATA_ERRORS:
        return ()
    result = []
    for entry in raw:
        parts = str(entry).split("\x1f")
        if len(parts) == 4:
            result.append(tuple(parts))
    return tuple(result)


def _effect_nodes(rig, effect_id, instance_id):
    geo = _geo()
    nodes = list(geo._fbp_find_shader_effect_nodes_for_rig(rig, effect_id, instance_id=instance_id))
    # Mixed stacks copy the effect into per-stage composite materials.
    owner = geo._fbp_effect_stack_owner_id(rig)
    seen = {int(node.as_pointer()) for node in nodes}
    for material in bpy.data.materials:
        try:
            if str(material.get("fbp_effect_composite_owner_id", "") or "") != owner:
                continue
        except FBP_DATA_ERRORS:
            continue
        for node in geo._fbp_shader_effect_nodes(material, effect_id=effect_id):
            if instance_id and geo.effect_instance_id(node) != instance_id:
                continue
            if int(node.as_pointer()) not in seen:
                nodes.append(node)
                seen.add(int(node.as_pointer()))
    return nodes


def _link_effect_node(node, modifier, mapping, token):
    """Link one material effect node to its modifier inputs; count new links."""
    geo = _geo()
    tree = node.id_data
    created = 0
    for row, (_prop_name, socket_name, identifier, kind) in enumerate(mapping):
        target = node.inputs.get(socket_name)
        handle = geo._fbp_modifier_input_handle(modifier, identifier)
        if target is None or handle is None:
            continue
        try:
            path = handle.path_from_id("value")
        except FBP_DATA_ERRORS:
            continue
        if len(path.encode("utf-8")) > _MAX_ATTRIBUTE_NAME:
            continue
        # Node names are capped at 63 bytes: hash the owner node and socket.
        digest = hashlib.sha1(f"{node.name}\x1f{socket_name}".encode("utf-8")).hexdigest()[:12]
        name = f"FBP Shell {digest}"
        attr_node = tree.nodes.get(name)
        if attr_node is None:
            attr_node = tree.nodes.new("ShaderNodeAttribute")
            attr_node.name = name
            attr_node.label = socket_name
            attr_node[_SHELL_ATTR_NODE_KEY] = token
            attr_node.hide = True
            attr_node.location = (node.location.x - 220.0, node.location.y - 30.0 * row)
        if attr_node.get(_SHELL_TARGET_KEY) != node.name:
            attr_node[_SHELL_TARGET_KEY] = node.name
        if attr_node.get(_SHELL_SOCKET_KEY) != socket_name:
            attr_node[_SHELL_SOCKET_KEY] = socket_name
        if attr_node.attribute_type != "OBJECT":
            attr_node.attribute_type = "OBJECT"
        if attr_node.attribute_name != path:
            # Follows a renamed modifier: the RNA path contains its name.
            attr_node.attribute_name = path
            created += 1
        output = attr_node.outputs["Color" if kind == "COLOR" else "Fac"]
        if target.is_linked and target.links[0].from_socket == output:
            continue
        for link in tuple(target.links):
            tree.links.remove(link)
        tree.links.new(output, target)
        created += 1
    return created


def _fit_modifier_name(modifier, mapping):
    """Shorten a renamed shell so the material can still address its inputs."""
    geo = _geo()
    longest = 0
    for _prop_name, _socket_name, identifier, _socket_kind in mapping:
        handle = geo._fbp_modifier_input_handle(modifier, identifier)
        if handle is None:
            continue
        try:
            longest = max(longest, len(handle.path_from_id("value").encode("utf-8")))
        except FBP_DATA_ERRORS:
            continue
    excess = longest - _MAX_ATTRIBUTE_NAME
    if excess <= 0:
        return False
    name = modifier.name.encode("utf-8")[:max(1, len(modifier.name.encode("utf-8")) - excess)]
    modifier.name = name.decode("utf-8", errors="ignore").rstrip() or "Effect"
    return True


def fbp_shell_refresh_links(rig):
    """Re-link every shell after Frame By Plane rebuilt or copied materials."""
    linked = 0
    geo = _geo()
    for token, modifier in fbp_shell_modifiers(rig):
        try:
            _fit_modifier_name(modifier, _shell_mapping(modifier.node_group))
        except FBP_DATA_ERRORS:
            pass
        effect_id, instance_id = geo._fbp_effect_ref_parts(token)
        mapping = _shell_mapping(modifier.node_group)
        for node in _effect_nodes(rig, effect_id, instance_id):
            linked += _link_effect_node(node, modifier, mapping, token)
    return linked



def fbp_shell_relink_material(material):
    """Re-link one material's shell attribute nodes after its chain was rebuilt.

    Rebuilding a shader stage clears the links into its effect nodes. Each
    shell attribute node remembers the node and socket it drives, so the
    material alone is enough to restore them.
    """
    tree = getattr(material, "node_tree", None)
    if tree is None:
        return 0
    linked = 0
    for attr_node in tuple(tree.nodes):
        try:
            if not attr_node.get(_SHELL_ATTR_NODE_KEY):
                continue
            node = tree.nodes.get(str(attr_node.get(_SHELL_TARGET_KEY, "") or ""))
            target = node.inputs.get(str(attr_node.get(_SHELL_SOCKET_KEY, "") or "")) if node else None
            if target is None:
                continue
            output = attr_node.outputs["Color" if target.type == "RGBA" else "Fac"]
            if target.is_linked and target.links[0].from_socket == output:
                continue
            for link in tuple(target.links):
                tree.links.remove(link)
            tree.links.new(output, target)
            linked += 1
        except FBP_DATA_ERRORS:
            continue
    return linked


def _modifier_input(modifier, identifier):
    value = _geo()._fbp_modifier_input_get(modifier, identifier)
    # Copy arrays: they stop being valid once the modifier is removed.
    return tuple(value) if hasattr(value, "__len__") and not isinstance(value, str) else value


def _set_modifier_input(modifier, identifier, rna, value):
    geo = _geo()
    if _is_color(rna):
        value = _color4(value)
    elif rna.type == "ENUM":
        identifiers = [item.identifier for item in rna.enum_items]
        value = identifiers.index(str(value)) if str(value) in identifiers else 0
    elif rna.type == "BOOLEAN":
        value = bool(value)
    elif rna.type == "INT":
        value = int(value)
    else:
        value = float(value)
    try:
        return geo._fbp_modifier_input_set(modifier, identifier, value)
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not set shell input {identifier}", exc)
        return False


def fbp_shell_reposition(rig):
    """Place shells where their image effects evaluate in the stack.

    In a mixed stack each shell sits just above its stage modifier. Otherwise
    shells follow the stack order (reversed, Blender evaluates top to bottom)
    after every other modifier.
    """
    geo = _geo()
    plane = geo._fbp_plane(rig, repair=False)
    if plane is None:
        return False
    shells = dict(fbp_shell_modifiers(rig))
    if not shells:
        return False
    others = [item for item in plane.modifiers if not fbp_shell_token(item)]
    stage_tokens = {geo._fbp_mixed_shader_stage_token(item): item for item in others}
    ordered = []
    placed = set()
    for item in others:
        ordered.append(item)
        token = geo._fbp_mixed_shader_stage_token(item)
        if token in shells:
            ordered.append(shells[token])
            placed.add(token)
    ui_order = geo._fbp_mixed_effect_tokens(rig)
    for token in reversed(ui_order):
        if token in shells and token not in placed and token not in stage_tokens:
            ordered.append(shells[token])
            placed.add(token)
    for token, modifier in shells.items():
        if token not in placed:
            ordered.append(modifier)
    return geo._fbp_apply_modifier_order_exact(plane, ordered)


def fbp_shell_maintain(rig):
    """Drop shells of removed effects, then re-link and re-place the others."""
    shells = fbp_shell_modifiers(rig)
    if not shells:
        return False
    geo = _geo()
    active = set(geo._fbp_mixed_effect_tokens(rig))
    changed = False
    for token, modifier in shells:
        if token in active:
            continue
        group = modifier.node_group
        try:
            modifier.id_data.modifiers.remove(modifier)
            if group is not None and group.users == 0:
                bpy.data.node_groups.remove(group)
            changed = True
        except FBP_DATA_ERRORS:
            continue
    if fbp_shell_modifiers(rig):
        changed = bool(fbp_shell_refresh_links(rig)) or changed
        changed = bool(fbp_shell_reposition(rig)) or changed
        changed = bool(fbp_shell_sync_values(rig)) or changed
    return changed


def fbp_shell_create(rig, effect_id, instance_id=""):
    """Turn one image effect or mask into a native modifier shell."""
    geo = _geo()
    effect_id = geo.fbp_normalize_effect_id(effect_id)
    if not fbp_shell_supported(effect_id) or not geo.fbp_effect_is_active(rig, effect_id):
        return None
    if not geo._fbp_effect_uses_multi_instances(effect_id):
        instance_id = ""
    elif not instance_id:
        tokens = [
            token for token in geo._fbp_mixed_effect_tokens(rig)
            if geo._fbp_effect_ref_effect_id(token) == effect_id
        ]
        if not tokens:
            return None
        instance_id = geo._fbp_effect_ref_parts(tokens[0])[1]
    existing = fbp_shell_modifier(rig, effect_id, instance_id)
    if existing is not None:
        return existing
    plane = geo._fbp_plane(rig, repair=False)
    row = fbp_shell_is_row(effect_id)
    nodes = [] if row else _effect_nodes(rig, effect_id, instance_id)
    if plane is None or not (nodes or row):
        return None
    token = geo._fbp_effect_ref(effect_id, instance_id)
    group = _build_shell_group(rig, effect_id, token)
    definition = geo.fbp_effect_definition(effect_id)
    modifier = plane.modifiers.new(str(definition.get("label", effect_id)), "NODES")
    modifier.node_group = group
    modifier.show_in_editmode = False
    parameters = {prop: rna for prop, _socket, rna in _shell_parameters(effect_id)}
    source = nodes[0] if nodes else None
    for prop_name, socket_name, identifier, _attribute in _shell_mapping(group):
        rna = parameters[prop_name]
        if rna.type == "ENUM":
            value = getattr(rig, prop_name, None)
        else:
            socket = source.inputs.get(socket_name)
            value = socket.default_value if socket is not None and not socket.is_linked else getattr(rig, prop_name, 0.0)
        _set_modifier_input(modifier, identifier, rna, value)
    viewport, render = (
        geo.fbp_effect_visible_state(rig, effect_id, instance_id),
        geo.fbp_effect_render_visible_state(rig, effect_id, instance_id),
    )
    modifier.show_viewport = bool(viewport)
    modifier.show_render = bool(render)
    group[_SHELL_SYNCED_KEY] = {
        identifier: _modifier_input(modifier, identifier)
        for _prop, _socket, identifier, _kind_name in _shell_mapping(group)
    }
    fbp_shell_refresh_links(rig)
    fbp_shell_reposition(rig)
    plane.update_tag()
    return modifier


def _shader_value(rna, value):
    """Return the value the material socket expects for one modifier value."""
    if _is_color(rna):
        return _color4(value)
    return float(value)


def fbp_shell_remove(rig, effect_id, instance_id="", *, keep_values=True):
    """Return one shelled effect to the Frame By Plane panel."""
    geo = _geo()
    effect_id = geo.fbp_normalize_effect_id(effect_id)
    modifier = fbp_shell_modifier(rig, effect_id, instance_id)
    if modifier is None:
        return False
    token = fbp_shell_token(modifier)
    group = modifier.node_group
    mapping = _shell_mapping(group)
    parameters = {prop: rna for prop, _socket, rna in _shell_parameters(effect_id)}
    values = {}
    for prop_name, socket_name, identifier, _attribute in mapping:
        values[socket_name] = (prop_name, _modifier_input(modifier, identifier))
    for node in _effect_nodes(rig, effect_id, instance_id):
        tree = node.id_data
        for attr_node in tuple(tree.nodes):
            try:
                if str(attr_node.get(_SHELL_ATTR_NODE_KEY, "") or "") == token:
                    tree.nodes.remove(attr_node)
            except FBP_DATA_ERRORS:
                continue
        if not keep_values:
            continue
        for socket_name, (prop_name, value) in values.items():
            socket = node.inputs.get(socket_name)
            if socket is None or value is None:
                continue
            try:
                shader_value = _shader_value(parameters.get(prop_name), value)
                if isinstance(shader_value, tuple):
                    length = len(tuple(socket.default_value))
                    shader_value = shader_value[:length]
                socket.default_value = shader_value
            except FBP_DATA_ERRORS:
                pass
    if keep_values:
        _write_layer_values(rig, effect_id, instance_id, values, parameters)
    plane = geo._fbp_plane(rig, repair=False)
    try:
        plane.modifiers.remove(modifier)
    except FBP_DATA_ERRORS:
        return False
    try:
        if group is not None and group.users == 0:
            bpy.data.node_groups.remove(group)
    except FBP_DATA_ERRORS:
        pass
    return True


def _write_layer_values(rig, effect_id, instance_id, values, parameters):
    """Store modifier values on the layer: rig settings or instance channels."""
    geo = _geo()
    if instance_id and geo._fbp_effect_uses_multi_instances(effect_id):
        # MULTI effects keep per-instance values in stable keyframe channels.
        for socket_name, (prop_name, value) in values.items():
            if value is None:
                continue
            channel = geo.fbp_effect_instance_channel(rig, effect_id, instance_id, prop_name, ensure=True)
            if channel is None:
                continue
            try:
                geo.fbp_set_rna_property_silent(
                    channel, geo._fbp_instance_channel_value_attr(channel), value
                )
            except FBP_DATA_ERRORS as exc:
                fbp_warn(f"Could not restore {prop_name} from its modifier", exc)
        try:
            geo.fbp_load_active_effect_instance_settings(rig)
        except FBP_DATA_ERRORS:
            pass
    else:
        for socket_name, (prop_name, value) in values.items():
            rna = parameters.get(prop_name)
            if rna is None or value is None:
                continue
            try:
                if rna.type == "ENUM":
                    index = max(0, min(int(value), len(rna.enum_items) - 1))
                    value = rna.enum_items[index].identifier
                elif rna.type == "BOOLEAN":
                    value = bool(value)
                elif _is_color(rna):
                    value = tuple(value)[:int(rna.array_length)]
                geo.fbp_set_rna_property_silent(rig, prop_name, value)
            except FBP_DATA_ERRORS as exc:
                fbp_warn(f"Could not restore {prop_name} from its modifier", exc)


_SHELL_SYNCED_KEY = "fbp_shell_synced"


def _comparable(value):
    if hasattr(value, "__len__") and not isinstance(value, str):
        return tuple(round(float(v), 5) for v in tuple(value)[:4])
    try:
        return round(float(value), 5)
    except (TypeError, ValueError):
        return None


def _socket_as_modifier_value(rna, socket):
    value = socket.default_value
    if _is_color(rna):
        return _color4(value)
    if rna.type in {"ENUM", "INT"}:
        return int(round(float(value)))
    if rna.type == "BOOLEAN":
        return bool(float(value) >= 0.5)
    return float(value)


def fbp_shell_sync_values(rig):
    """Keep each shell's inputs and the layer's settings equal.

    Each shell group remembers the values of the last sync. A modifier input that
    moved since then was edited in the Modifiers panel (or is animated) and is
    written back to the layer; otherwise a material socket that moved was set
    by Frame By Plane (a preset, Copy to Selected, a script) and is written to
    the modifier. Returns the number of values that moved.
    """
    geo = _geo()
    moved = 0
    for token, modifier in fbp_shell_modifiers(rig):
        effect_id, instance_id = geo._fbp_effect_ref_parts(token)
        nodes = _effect_nodes(rig, effect_id, instance_id)
        if not nodes:
            continue
        parameters = {prop: rna for prop, _socket, rna in _shell_parameters(effect_id)}
        try:
            synced = dict(modifier.node_group.get(_SHELL_SYNCED_KEY, {}) or {})
        except FBP_DATA_ERRORS:
            synced = {}
        to_layer = {}
        stored = {}
        for prop_name, socket_name, identifier, _kind_name in _shell_mapping(modifier.node_group):
            rna = parameters.get(prop_name)
            socket = nodes[0].inputs.get(socket_name)
            if rna is None or socket is None:
                continue
            current = _modifier_input(modifier, identifier)
            if current is None:
                continue
            last = synced.get(identifier)
            last = _comparable(last) if last is not None else None
            if last is not None and _comparable(current) != last:
                to_layer[socket_name] = (prop_name, current)
            elif last is not None:
                try:
                    material_value = _socket_as_modifier_value(rna, socket)
                except FBP_DATA_ERRORS:
                    material_value = None
                if material_value is not None and _comparable(material_value) != last:
                    if rna.type == "ENUM":
                        material_value = rna.enum_items[
                            max(0, min(int(material_value), len(rna.enum_items) - 1))
                        ].identifier
                    _set_modifier_input(modifier, identifier, rna, material_value)
                    current = _modifier_input(modifier, identifier)
                    moved += 1
            stored[identifier] = current
        if to_layer:
            moved += len(to_layer)
            for node in nodes:
                for socket_name, (prop_name, value) in to_layer.items():
                    socket = node.inputs.get(socket_name)
                    if socket is None:
                        continue
                    try:
                        shader_value = _shader_value(parameters.get(prop_name), value)
                        if isinstance(shader_value, tuple):
                            shader_value = shader_value[:len(tuple(socket.default_value))]
                        socket.default_value = shader_value
                    except FBP_DATA_ERRORS:
                        pass
            _write_layer_values(rig, effect_id, instance_id, to_layer, parameters)
        if stored != synced:
            try:
                modifier.node_group[_SHELL_SYNCED_KEY] = stored
            except FBP_DATA_ERRORS:
                pass
    return moved


def fbp_shell_ensure(rig):
    """Give every active image effect and mask of one layer its modifier."""
    geo = _geo()
    created = 0
    for token in tuple(geo._fbp_mixed_effect_tokens(rig)):
        effect_id, instance_id = geo._fbp_effect_ref_parts(token)
        if not fbp_shell_supported(effect_id):
            continue
        if fbp_shell_modifier(rig, effect_id, instance_id) is not None:
            continue
        created += fbp_shell_create(rig, effect_id, instance_id) is not None
    return created


class _ShellLayout:
    """Layout proxy that draws an effect's layer settings from its shell.

    Effect panels call ``layout.prop(rig, "fbp_...")`` (or a MULTI instance
    channel). While the effect lives on a modifier those values are inert, so
    this proxy swaps every mapped property for the modifier input it feeds.
    Sub-layouts are wrapped too; everything else goes to the real layout.
    """

    _WRAPPED = {"row", "column", "box", "split", "grid_flow", "column_flow"}

    def __init__(self, layout, rig, handles, labels, channel_key):
        object.__setattr__(self, "_layout", layout)
        object.__setattr__(self, "_rig", rig)
        object.__setattr__(self, "_handles", handles)
        object.__setattr__(self, "_labels", labels)
        object.__setattr__(self, "_channel_key", channel_key)

    def _wrap(self, layout):
        if layout is None:
            return None
        return _ShellLayout(layout, self._rig, self._handles, self._labels, self._channel_key)

    def __getattr__(self, name):
        attr = getattr(self._layout, name)
        if name in self._WRAPPED:
            def wrapped(*args, **kwargs):
                return self._wrap(attr(*args, **kwargs))
            return wrapped
        if name in {"panel", "panel_prop"}:
            def panel(*args, **kwargs):
                header, body = attr(*args, **kwargs)
                return self._wrap(header), self._wrap(body)
            return panel
        return attr

    def __setattr__(self, name, value):
        setattr(self._layout, name, value)

    def _target(self, owner, prop_name):
        prop_name = str(prop_name or "")
        if owner is self._rig:
            return prop_name if prop_name in self._handles else ""
        try:
            identity = _geo()._fbp_effect_instance_channel_identity(owner)[:2]
        except (AttributeError, *FBP_DATA_ERRORS):
            return ""
        if identity != self._channel_key:
            return ""
        mapped = str(getattr(owner, "property_name", "") or "")
        if mapped in self._handles and prop_name == _geo()._fbp_instance_channel_value_attr(owner):
            return mapped
        return ""

    def prop(self, owner, prop_name, **kwargs):
        mapped = self._target(owner, prop_name)
        if not mapped:
            return self._layout.prop(owner, prop_name, **kwargs)
        kwargs.setdefault("text", self._labels.get(mapped, ""))
        # Enum choices are stored as an index: a dropdown cannot be drawn.
        for key in ("expand", "icon_only", "emboss", "index"):
            if key == "expand" or (key == "icon_only" and kwargs.get("icon_only")):
                kwargs.pop(key, None)
        return self._layout.prop(self._handles[mapped], "value", **kwargs)

    def prop_enum(self, owner, prop_name, value, **kwargs):
        mapped = self._target(owner, prop_name)
        if not mapped:
            return self._layout.prop_enum(owner, prop_name, value, **kwargs)
        return self.prop(owner, prop_name, text=kwargs.get("text", ""))

    def props_enum(self, owner, prop_name):
        mapped = self._target(owner, prop_name)
        if not mapped:
            return self._layout.props_enum(owner, prop_name)
        return self.prop(owner, prop_name)


def fbp_shell_layout(layout, rig, effect_id, instance_id=""):
    """Return ``layout``, or a proxy routing settings to the effect's shell."""
    modifier = fbp_shell_modifier(rig, effect_id, instance_id)
    if modifier is None or modifier.node_group is None:
        return layout
    geo = _geo()
    handles, labels = {}, {}
    properties = bpy.types.Object.bl_rna.properties
    for prop_name, socket_name, identifier, _kind in _shell_mapping(modifier.node_group):
        handle = geo._fbp_modifier_input_handle(modifier, identifier)
        if handle is None:
            continue
        handles[prop_name] = handle
        rna = properties.get(prop_name)
        labels[prop_name] = str(getattr(rna, "name", "") or socket_name)
    if not handles:
        return layout
    channel_key = (geo.fbp_normalize_effect_id(effect_id), str(instance_id or ""))
    return _ShellLayout(layout, rig, handles, labels, channel_key)


classes = ()


def register():
    register_classes(classes)


def unregister():
    unregister_classes(classes)
