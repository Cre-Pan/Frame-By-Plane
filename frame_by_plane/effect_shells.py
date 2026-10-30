"""Preview: image effects and masks as native modifier "shells".

An image effect runs per pixel inside the plane material, which a Geometry
Nodes modifier cannot do. A shell is a small Geometry Nodes modifier that owns
the effect's parameters instead: the effect node in the material reads every
modifier input through an Object Attribute node (an RNA path to the input), so
the modifier itself does no geometry work at all. The artist then edits,
keyframes, reorders and hides the image effect from Blender's Modifiers panel
like any other modifier, and the material does the actual shading in Eevee and
Cycles.

Prototype scope: three image effects and three masks, behind the
``native_effect_shells`` preview feature.
"""

from __future__ import annotations

import hashlib

import bpy

from .registration import register_classes, unregister_classes
from .runtime import FBP_DATA_ERRORS, fbp_warn


FBP_SHELL_EFFECTS = (
    "HUE_SATURATION",
    "VIGNETTE",
    "POSTERIZE",
    "GRADIENT_MASK",
    "CIRCLE_MASK",
    "SQUARE_MASK",
)
FBP_SHELL_FEATURE = "native_effect_shells"
_SHELL_TOKEN_KEY = "fbp_shell_token"
_SHELL_GROUP_KEY = "fbp_shell_group"
_SHELL_ATTR_NODE_KEY = "fbp_shell_attribute"
# Attribute names are stored in 64-byte buffers, and the RNA path to a modifier
# input contains the modifier name.
_MAX_ATTRIBUTE_NAME = 63


def _geo():
    from . import geometry_nodes
    return geometry_nodes


def fbp_shells_enabled(scene=None):
    from .feature_scope import fbp_feature_enabled
    scene = scene if scene is not None else getattr(bpy.context, "scene", None)
    return fbp_feature_enabled(scene, FBP_SHELL_FEATURE)


def fbp_shell_supported(effect_id):
    return str(effect_id or "").upper() in FBP_SHELL_EFFECTS


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
    definition = _geo().fbp_effect_definition(effect_id)
    result = []
    properties = bpy.types.Object.bl_rna.properties
    for prop_name, socket_name in (definition.get("property_map", {}) or {}).items():
        rna = properties.get(prop_name)
        if rna is None or rna.type not in {"FLOAT", "INT", "BOOLEAN", "ENUM"}:
            continue
        if getattr(rna, "is_array", False):
            continue
        result.append((prop_name, socket_name, rna))
    return result


def _new_input(interface, rna, name, panel=None):
    kind = rna.type
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
            f"{label}: Frame By Plane image effect. The shading runs in the plane "
            "material; this modifier holds its settings, order and visibility."
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
        mapping.append((prop_name, socket_name, socket.identifier, rna.type))
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
    for row, (_prop_name, socket_name, identifier, _kind) in enumerate(mapping):
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
        if attr_node.attribute_type != "OBJECT":
            attr_node.attribute_type = "OBJECT"
        if attr_node.attribute_name != path:
            # Follows a renamed modifier: the RNA path contains its name.
            attr_node.attribute_name = path
            created += 1
        if target.is_linked and target.links[0].from_node == attr_node:
            continue
        for link in tuple(target.links):
            tree.links.remove(link)
        tree.links.new(attr_node.outputs["Fac"], target)
        created += 1
    return created


def _fit_modifier_name(modifier, mapping):
    """Shorten a renamed shell so the material can still address its inputs."""
    geo = _geo()
    longest = 0
    for _prop_name, _socket_name, identifier, _kind in mapping:
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


def _modifier_input(modifier, identifier):
    return _geo()._fbp_modifier_input_get(modifier, identifier)


def _set_modifier_input(modifier, identifier, rna, value):
    geo = _geo()
    if rna.type == "ENUM":
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
    nodes = _effect_nodes(rig, effect_id, instance_id)
    if plane is None or not nodes:
        return None
    token = geo._fbp_effect_ref(effect_id, instance_id)
    group = _build_shell_group(rig, effect_id, token)
    definition = geo.fbp_effect_definition(effect_id)
    modifier = plane.modifiers.new(str(definition.get("label", effect_id)), "NODES")
    modifier.node_group = group
    modifier.show_in_editmode = False
    parameters = {prop: rna for prop, _socket, rna in _shell_parameters(effect_id)}
    source = nodes[0]
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
    fbp_shell_refresh_links(rig)
    fbp_shell_reposition(rig)
    plane.update_tag()
    return modifier


def _shader_value(_rna, value):
    """Return the float the material socket expects for one modifier value."""
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
                socket.default_value = float(_shader_value(parameters.get(prop_name), value))
            except FBP_DATA_ERRORS:
                pass
    if keep_values and instance_id and geo._fbp_effect_uses_multi_instances(effect_id):
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
    elif keep_values:
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
                geo.fbp_set_rna_property_silent(rig, prop_name, value)
            except FBP_DATA_ERRORS as exc:
                fbp_warn(f"Could not restore {prop_name} from its modifier", exc)
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


def fbp_shell_draw_settings(layout, rig, effect_id, instance_id=""):
    """Draw a shelled effect's settings from its modifier inputs."""
    modifier = fbp_shell_modifier(rig, effect_id, instance_id)
    if modifier is None:
        return False
    box = layout.box()
    header = box.row(align=True)
    header.label(text=modifier.name, icon="MODIFIER")
    unshell = header.operator("fbp.effect_shell_toggle", text="", icon="X", emboss=False)
    unshell.effect_id = effect_id
    unshell.instance_id = instance_id
    unshell.enable = False
    column = box.column(align=True)
    column.use_property_split = True
    geo = _geo()
    for _prop_name, socket_name, identifier, _attribute in _shell_mapping(modifier.node_group):
        handle = geo._fbp_modifier_input_handle(modifier, identifier)
        if handle is not None:
            column.prop(handle, "value", text=socket_name)
    hint = box.row()
    hint.enabled = False
    hint.label(text="Native modifier: edit, keyframe and reorder it in Modifiers", icon="INFO")
    return True


class FBP_OT_EffectShellToggle(bpy.types.Operator):
    bl_idname = "fbp.effect_shell_toggle"
    bl_label = "Show as Modifier"
    bl_description = (
        "Preview: show this image effect or mask as a native modifier whose inputs drive "
        "the material, or return it to the Frame By Plane panel"
    )
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    effect_id: bpy.props.StringProperty(default="", options={"SKIP_SAVE"})
    instance_id: bpy.props.StringProperty(default="", options={"SKIP_SAVE"})
    enable: bpy.props.BoolProperty(default=True, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return fbp_shells_enabled(getattr(context, "scene", None))

    def execute(self, context):
        from .layers import get_selected_rigs
        changed = 0
        for rig in tuple(get_selected_rigs(context) or ()):
            if self.enable:
                changed += fbp_shell_create(rig, self.effect_id, self.instance_id) is not None
            else:
                changed += bool(fbp_shell_remove(rig, self.effect_id, self.instance_id))
            try:
                from .native_modifiers import fbp_native_remember
                fbp_native_remember(rig)
            except ImportError:
                pass
        return {"FINISHED"} if changed else {"CANCELLED"}


classes = (FBP_OT_EffectShellToggle,)


def register():
    register_classes(classes)


def unregister():
    unregister_classes(classes)
