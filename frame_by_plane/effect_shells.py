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
Blender's Modifiers panel is the only effect stack, and the shell carries every
setting of the effect panel: values the material reads, choices (dropdowns),
settings Frame By Plane converts and the Animate section. Buttons, curves,
ramps, images and Grease Pencil editing are drawn under the inputs by
``native_effect_panel``.
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
# modifier is a row for order, eye, camera and delete; the settings it cannot
# hold as inputs are drawn under them by ``native_effect_panel``.
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


_OBJECT_RNA_CACHE = {}


def _object_rna(prop_name):
    """Object RNA property by name, cached (a lookup scans ~1300 properties).

    Only hits are cached; the cache resets on (un)registration so a reload
    never keeps stale RNA structs.
    """
    rna = _OBJECT_RNA_CACHE.get(prop_name)
    if rna is None:
        rna = bpy.types.Object.bl_rna.properties.get(prop_name)
        if rna is not None:
            _OBJECT_RNA_CACHE[prop_name] = rna
    return rna


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
    for prop_name, socket_name in (definition.get("property_map", {}) or {}).items():
        if prop_name in _SHELL_DERIVED_PROPERTIES:
            continue
        rna = _object_rna(prop_name)
        # Choices are dropdowns on the layer: Frame By Plane converts them.
        if rna is None or rna.type not in {"FLOAT", "INT", "BOOLEAN"}:
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
            f"{label}: Frame By Plane effect. Its settings are this modifier's "
            "inputs; the image work runs in the layer material."
        )
    except FBP_DATA_ERRORS:
        pass
    _populate_shell_group(group, effect_id)
    return group


_SHELL_UI_KEY = "fbp_shell_ui"
# 2: every panel control (choices, extra settings, Animate) is an input.
# 3: variant, input, preview, mask operation, viewport control and sources.
# 4: Actions is the first input, with the Lattice cage and handle actions.
# 6: Action button rows rest with no button pressed.
# 7: More effects get a Tools row (mask shapes, Gradient Light, Motion...).
_SHELL_UI_VERSION = 7
_SHELL_USAGE_ATTRIBUTE = "fbp_shell_usage"
_SHELL_USAGE_NODE_KEY = "fbp_shell_usage_node"
_SHELL_LAYER_MAPPING_KEY = "fbp_shell_layer_mapping"
_SHELL_LAYER_TYPES = {"FLOAT", "INT", "BOOLEAN", "ENUM"}
# Object, material, image and file settings the panel shows (sources of a
# matte, a side material): the modifier holds them as data-block or file
# inputs. Helper objects Frame By Plane creates itself are left out.
_SHELL_DATA_PROPERTIES = {
    "fbp_alpha_matte_source",
    "fbp_luma_matte_source",
    "fbp_luma_matte_image",
    "fbp_luma_matte_path",
    "fbp_clipping_mask_source",
    "fbp_imported_mask_path",
    "fbp_thickness_side_material",
}
_SHELL_DATA_SOCKETS = {
    "Object": ("NodeSocketObject", "OBJECT"),
    "Material": ("NodeSocketMaterial", "MATERIAL"),
    "Image": ("NodeSocketImage", "IMAGE"),
}
# Animate section: (animation key suffix, input name), in panel order.
_SHELL_ANIMATE = (
    ("evolve", "Animate"),
    ("seed", "Seed"),
    ("step", "Stepped"),
    ("speed", "Speed"),
    ("unique", "Unique per Layer"),
)


class _Choice:
    __slots__ = ("identifier", "name")

    def __init__(self, identifier, name):
        self.identifier = str(identifier)
        self.name = str(name)


class _VirtualSetting:
    """RNA-like description of a panel control that is not a layer property.

    The variant dropdown, Input, Preview and the mask operation are buttons in
    the Frame By Plane panel; in the modifier they are dropdowns, read and
    written through the same functions those buttons call.
    """

    is_array = False
    subtype = "NONE"
    hard_min = 0
    hard_max = 1

    def __init__(self, key, label, choices, description=""):
        self.identifier = key
        self.name = label
        self.type = "ENUM"
        self.enum_items = tuple(_Choice(identifier, name) for identifier, name in choices)
        self.default = self.enum_items[0].identifier if self.enum_items else ""
        self.description = description


def _virtual_settings(effect_id, definition):
    """Return the panel's button rows as ``[(key, setting)]`` for one effect."""
    geo = _geo()
    result = []
    try:
        from .effects_registry import fbp_effect_family_definition, fbp_effect_variant_label
        family = fbp_effect_family_definition(effect_id)
    except ImportError:
        family = {}
    variants = tuple(family.get("variants", ()) or ())
    if len(variants) > 1:
        result.append(("@VARIANT", _VirtualSetting(
            "@VARIANT", str(family.get("label", "Variant") or "Variant"),
            [(variant_id, fbp_effect_variant_label(variant_id)) for variant_id, _label in variants],
            "Switch to another variant of this effect",
        )))
    if definition.get("supports_input_source"):
        result.append(("@SOURCE", _VirtualSetting(
            "@SOURCE", "Input",
            (("PREVIOUS", "Previous Effects"), ("ORIGINAL", "Original Material"), ("FINAL", "Final Material")),
            "Which image feeds this effect",
        )))
    debug_modes = () if effect_id in getattr(geo, "GP_MASK_EFFECT_IDS", ()) else tuple(
        definition.get("debug_modes", ()) or ()
    )
    if debug_modes:
        result.append(("@DEBUG", _VirtualSetting(
            "@DEBUG", "Preview", debug_modes, "Show the result or a diagnostic view",
        )))
    if str(definition.get("stage", "") or "") == "MASK":
        result.append(("@MASKOP", _VirtualSetting(
            "@MASKOP", "Stack Operation",
            [(item[0], item[1]) for item in geo.FBP_MASK_STACK_OPERATIONS],
            "How this mask combines with the masks above it",
        )))
    # Two rows of buttons at the top of the modifier: what the effect's
    # handles and helpers can do, then Reset, Presets and Node Editor.
    actions = _effect_actions(effect_id, definition)
    tools = [(key, label) for key, label, _op, _kwargs in actions if key not in _EFFECT_ACTIONS]
    general = [(key, label) for key, label, _op, _kwargs in actions if key in _EFFECT_ACTIONS]
    if tools:
        result.append(("@TOOLS", _VirtualSetting(
            "@TOOLS", "Tools", [("NONE", "·")] + tools, "Run a tool of this effect",
        )))
    if general:
        result.append(("@ACTION", _VirtualSetting(
            "@ACTION", "Effect", [("NONE", "·")] + general, "Reset this effect, load a preset or open its nodes",
        )))
    return result


# Keys of the actions every effect has (second button row).
_EFFECT_ACTIONS = frozenset({"RESET", "PRESETS", "NODES"})
_ACTION_KEYS = ("@TOOLS", "@ACTION")


def _effect_actions(effect_id, definition):
    """Buttons of the effect panel as ``(key, label, operator, kwargs)``."""
    if bool(definition.get("custom", False)):
        return ()
    actions = [
        ("RESET", "Reset", "fbp.reset_active_effect", {"effect_id": effect_id}),
        ("PRESETS", "Presets", "fbp.open_effect_presets", {"effect_id": effect_id}),
    ]
    if definition.get("kind") in {"SHADER", "MASK", "GEOMETRY"}:
        # Color ramps and curves are edited in the node tree.
        actions.append(("NODES", "Node Editor", "fbp.open_effect_nodes", {"effect_id": effect_id}))
    if _has_viewport_control(effect_id):
        actions.append(("SELECT_CONTROL", "Select Rig", "fbp.select_effect_control", {"effect_id": effect_id}))
        actions.append(("RESET_CONTROL", "Reset Rig", "fbp.reset_effect_control", {"effect_id": effect_id}))
    if effect_id == "CROP":
        actions.append(("CROP_ALPHA", "Crop Alpha", "fbp.crop_alpha", {}))
        actions.append(("RESET_CROP", "Reset Crop", "fbp.reset_crop", {}))
    if effect_id == "SHADOW":
        actions.append(("FIT_SHADOW", "Fit Canvas", "fbp.fit_shadow_canvas", {}))
    if effect_id == "GRADIENT_LIGHT":
        actions.append(("LIGHT_CONTROLLER", "Light Controller", "fbp.gradient_light_controller", {}))
    shape = _MASK_SHAPES.get(effect_id)
    if shape:
        shape_kwargs = {"rig_name": _RIG, "shape": shape}
        actions.extend((
            ("EDIT_SHAPE", "Edit Shape", "fbp.edit_object_mask_helper", shape_kwargs),
            ("PERFECT_SHAPE", "Perfect Shape", "fbp.perfect_object_mask_shape", shape_kwargs),
            ("RECREATE_SHAPE", "Recreate Shape", "fbp.recreate_object_mask_helper", shape_kwargs),
        ))
    if effect_id == "CAMERA_SCALE_LOCK":
        actions.append(("CAPTURE_SCALE", "Capture Reference", "fbp.capture_camera_scale_reference", {}))
    if effect_id == "MOTION":
        actions.append(("CAPTURE_BASE", "Capture Base", "fbp.motion_capture_base", {}))
    if effect_id == "LATTICE":
        actions.extend((
            ("SELECT_CAGE", "Select Cage", "fbp.select_lattice_helper", {"rig_name": _RIG}),
            ("EDIT_CAGE", "Edit Cage", "fbp.edit_lattice_helper", {"rig_name": _RIG}),
            ("FINISH_CAGE", "Back to Plane", "fbp.finish_lattice_editing", {"rig_name": _RIG}),
            ("POINT_HANDLES", "Point Handles", "fbp.lattice_point_handles", {"rig_name": _RIG, "action": "ADD"}),
        ))
    return tuple(actions)


def fbp_shell_tool_operators(effect_id, key="@TOOLS"):
    """Operators one of the effect's button rows runs."""
    definition = _geo().fbp_effect_definition(effect_id) or {}
    general = key != "@TOOLS"
    return frozenset(
        op for action, _label, op, _kwargs in _effect_actions(effect_id, definition)
        if (action in _EFFECT_ACTIONS) == general
    )


# Object mask effects and the shape their helper operators take.
_MASK_SHAPES = {"CIRCLE_MASK": "CIRCLE", "SQUARE_MASK": "SQUARE", "TRIANGLE_MASK": "TRIANGLE"}

# Stands for the layer's name in an action's operator settings.
_RIG = "\x00RIG"


def _run_action(rig, effect_id, definition, key):
    """Run one panel button for the layer, with a Properties editor context."""
    action = next((item for item in _effect_actions(effect_id, definition) if item[0] == key), None)
    if action is None:
        return False
    _key, _label, idname, kwargs = action
    kwargs = {
        prop: (str(getattr(rig, "name", "") or "") if value == _RIG else value)
        for prop, value in kwargs.items()
    }
    module, _dot, name = idname.partition(".")
    operator = getattr(getattr(bpy.ops, module), name)
    window = next(iter(bpy.context.window_manager.windows), None)
    if window is None:
        return False
    area = next((item for item in window.screen.areas if item.type == "PROPERTIES"), None) or next(
        (item for item in window.screen.areas if item.type == "VIEW_3D"), None
    )
    region = next((item for item in area.regions if item.type == "WINDOW"), None) if area else None
    override = {"window": window, "screen": window.screen, "active_object": rig, "object": rig,
                "selected_objects": [rig], "selected_editable_objects": [rig]}
    if area is not None:
        override.update(area=area, region=region)
    with bpy.context.temp_override(**override):
        mode = "INVOKE_DEFAULT" if key in {"PRESETS", "NODES"} else "EXEC_DEFAULT"
        operator(mode, **kwargs)
    return True


def _has_viewport_control(effect_id):
    try:
        from .effect_controls import CONTROL_SPECS
        return bool(CONTROL_SPECS.get(str(effect_id).upper()))
    except (ImportError, AttributeError):
        return False


def _shell_animate_properties(effect_id, definition):
    """Return ``{rig_property: (suffix, label)}`` for an animatable effect."""
    # Mesh Wiggle always moves: its own Speed, Stepped and Seed are inputs.
    if not definition.get("evolve_property") or str(effect_id).upper() == "MESH_WIGGLE":
        return {}
    geo = _geo()
    result = {}
    for suffix, label in _SHELL_ANIMATE:
        if suffix == "speed":
            prop_name = geo._fbp_effect_evolution_speed_property(effect_id, definition)
        else:
            prop_name = geo._fbp_animation_key(effect_id, suffix)
        result[prop_name] = (suffix, label)
    return result


def _input_kind(rna):
    """Modifier input kind for one setting, or "" when it cannot be one."""
    if rna is None:
        return ""
    if rna.type == "POINTER":
        fixed = getattr(getattr(rna, "fixed_type", None), "identifier", "")
        return _SHELL_DATA_SOCKETS.get(fixed, ("", ""))[1]
    if rna.type == "STRING":
        return "STRING"
    if rna.type not in _SHELL_LAYER_TYPES:
        return ""
    if getattr(rna, "is_array", False) and not _is_color(rna):
        return ""
    if rna.type == "ENUM" and (
        not len(rna.enum_items) or bool(getattr(rna, "is_enum_flag", False))
    ):
        return ""
    return "ENUM" if rna.type == "ENUM" else _kind(rna)


def _shell_layout_entries(effect_id, skip=()):
    """Every control of the effect panel that a modifier input can hold.

    Returns ``[(prop, socket_name, rna, storage, label, animate, section)]``.
    Storage is ``MATERIAL`` for values read by the material (``socket_name``
    is the effect node socket), ``RIG`` for layer settings Frame By Plane
    converts (choices, sample counts, extra settings), ``ANIM:<suffix>`` for
    the Animate section of a repeatable effect and ``VIRTUAL`` for the
    panel's button rows. ``skip`` lists settings that already are inputs.
    """
    geo = _geo()
    definition = geo.fbp_effect_definition(effect_id) or {}
    material = {prop: socket for prop, socket, _rna in _shell_parameters(effect_id)}
    animate = _shell_animate_properties(effect_id, definition)
    names = list((definition.get("property_map", {}) or {}).keys())
    names.extend(definition.get("extra_properties", ()) or ())
    names.extend(animate)
    if _has_viewport_control(effect_id):
        names.insert(0, "fbp_effect_controls_enabled")
    plain, animated = [], {}
    leading = []
    for key, setting in _virtual_settings(effect_id, definition):
        entry = (key, "", setting, "VIRTUAL", setting.name, False)
        # Actions opens the modifier: Select Rig, Edit Cage... come first.
        (leading if key in _ACTION_KEYS else plain).append(entry)
    plain[:0] = leading
    skip = set(skip or ())
    for prop_name in dict.fromkeys(str(name or "") for name in names):
        if prop_name in skip:
            continue
        rna = _object_rna(prop_name)
        if rna is None:
            continue
        if rna.type in {"POINTER", "STRING"} and prop_name not in _SHELL_DATA_PROPERTIES:
            continue
        if not _input_kind(rna):
            continue
        if prop_name in material:
            socket_name, storage = material[prop_name], "MATERIAL"
        else:
            socket_name, storage = "", "RIG"
        if prop_name in animate:
            suffix, label = animate[prop_name]
            if storage == "RIG" and geo._fbp_effect_uses_multi_instances(effect_id):
                storage = f"ANIM:{suffix}"
            animated[suffix] = (prop_name, socket_name, rna, storage, label, True)
            continue
        if prop_name == "fbp_effect_controls_enabled":
            label = "Viewport Control"
        else:
            label = geo._fbp_effect_property_label(definition, prop_name, None) or str(rna.name)
        plain.append((prop_name, socket_name, rna, storage, label, False))
    # Same sections as the Frame By Plane panel (Wave, Direction & Mix, ...).
    section = {}
    for title, _icon, group_names in geo._FBP_EFFECT_UI_GROUPS.get(effect_id, ()):
        for name in group_names:
            section.setdefault(name, title)
    order = list(dict.fromkeys(section.values()))
    plain.sort(key=lambda entry: (
        order.index(section[entry[0]]) + 1 if entry[0] in section else 0
    ))
    plain = [entry + (section.get(entry[0], ""),) for entry in plain]
    taken = {animated[suffix][4] for suffix in animated}
    plain = [
        entry[:4] + (f"Base {entry[4]}" if entry[4] in taken else entry[4],) + entry[5:]
        for entry in plain
    ]
    plain.extend(
        animated[suffix] + ("Animate",) for suffix, _label in _SHELL_ANIMATE if suffix in animated
    )
    return plain


def _new_menu_input(group, rna, name, panel):
    """A dropdown input with the choices of one enum setting."""
    socket = group.interface.new_socket(
        name=name, in_out="INPUT", socket_type="NodeSocketMenu", parent=panel
    )
    switch = group.nodes.new("GeometryNodeMenuSwitch")
    switch.data_type = "INT"
    switch[_SHELL_USAGE_NODE_KEY] = True
    switch.hide = True
    switch.enum_items.clear()
    choices = tuple(rna.enum_items)
    if rna.identifier in _ACTION_KEYS:
        # No resting button: the input rests on a value with no item.
        choices = tuple(item for item in choices if item.identifier != "NONE")
    for item in choices:
        switch.enum_items.new(str(item.name))
    for index, item_socket in enumerate(tuple(switch.inputs)[1:1 + len(choices)]):
        try:
            item_socket.default_value = index
        except FBP_DATA_ERRORS:
            pass
    try:
        socket.description = str(rna.description or "")
    except FBP_DATA_ERRORS:
        pass
    return socket, switch


def _new_data_input(group, rna, name, panel, kind):
    """An object, material, image or file input, plus a node that reads it."""
    if kind == "STRING":
        socket = group.interface.new_socket(
            name=name, in_out="INPUT", socket_type="NodeSocketString", parent=panel
        )
        try:
            if str(getattr(rna, "subtype", "") or "") in {"FILE_PATH", "DIR_PATH"}:
                socket.subtype = "FILE_PATH"
        except FBP_DATA_ERRORS:
            pass
        reader = group.nodes.new("FunctionNodeStringLength")
    else:
        socket_type = {value[1]: value[0] for value in _SHELL_DATA_SOCKETS.values()}[kind]
        socket = group.interface.new_socket(
            name=name, in_out="INPUT", socket_type=socket_type, parent=panel
        )
        reader = group.nodes.new({
            "OBJECT": "GeometryNodeObjectInfo",
            "MATERIAL": "GeometryNodeMaterialSelection",
            "IMAGE": "GeometryNodeImageInfo",
        }[kind])
    reader[_SHELL_USAGE_NODE_KEY] = True
    reader.hide = True
    try:
        socket.description = str(rna.description or "")
    except FBP_DATA_ERRORS:
        pass
    return socket, reader


def _data_reader_output(reader):
    """A number output of the node that reads a data-block or file input."""
    for name in ("Length", "Width", "Selection"):
        if name in reader.outputs:
            return reader.outputs[name]
    if "Scale" in reader.outputs:
        return reader.outputs["Scale"]
    return reader.outputs[0]


def _menu_name(rna, identifier):
    for item in rna.enum_items:
        if item.identifier == identifier:
            return str(item.name)
    return str(rna.enum_items[0].name) if len(rna.enum_items) else ""


def _menu_identifier(rna, name):
    for item in rna.enum_items:
        if str(item.name) == str(name):
            return item.identifier
    return str(rna.enum_items[0].identifier) if len(rna.enum_items) else ""


def _add_inputs(group, entries, panels=None):
    """Create one input (in its section) per entry; return mapping and readers."""
    interface = group.interface
    mapping, layer_mapping, used, menus = [], [], [], []
    panels = {} if panels is None else panels
    for prop_name, socket_name, rna, storage, label, animate, section in entries:
        panel = None
        if section:
            panel = panels.get(section)
            if panel is None:
                panel = panels[section] = interface.new_panel(section, default_closed=False)
        kind = _input_kind(rna) if storage != "VIRTUAL" else "ENUM"
        if kind == "ENUM":
            socket, reader = _new_menu_input(group, rna, label, panel)
            menus.append((socket, rna))
        elif kind in {"OBJECT", "MATERIAL", "IMAGE", "STRING"}:
            socket, reader = _new_data_input(group, rna, label, panel, kind)
        else:
            socket, reader = _new_input(interface, rna, label, panel), None
        used.append((socket.identifier, reader))
        if animate and label == "Animate":
            try:
                socket.is_panel_toggle = True
            except FBP_DATA_ERRORS:
                pass
        if storage == "MATERIAL":
            mapping.append((prop_name, socket_name, socket.identifier, kind))
        else:
            layer_mapping.append((prop_name, storage, socket.identifier, kind))
    group["fbp_menu_defaults"] = [
        f"{socket.identifier}\x1f{_menu_name(rna, str(rna.default))}" for socket, rna in menus
    ]
    return mapping, layer_mapping, used


def _wire_usage(group, used, geometry_source, group_output):
    """Mark inputs as used: sum them into a throwaway attribute on the way out.

    Blender greys out modifier inputs that do not reach the output, and these
    inputs only feed the material or the layer. The chain stores their sum
    and drops it again, so the geometry is unchanged.
    """
    nodes, links = group.nodes, group.links
    group_input = next((node for node in nodes if node.bl_idname == "NodeGroupInput"), None)
    total = None
    for index, (identifier, reader) in enumerate(used):
        socket = next((out for out in group_input.outputs if out.identifier == identifier), None)
        if socket is None:
            continue
        if reader is not None:
            reader.location = (-200.0, -60.0 - 30.0 * index)
            links.new(socket, reader.inputs[0])
            socket = (
                reader.outputs[0] if reader.bl_idname == "GeometryNodeMenuSwitch"
                else _data_reader_output(reader)
            )
        if total is None:
            total = socket
            continue
        add = nodes.new("ShaderNodeMath")
        add.operation = "ADD"
        add[_SHELL_USAGE_NODE_KEY] = True
        add.hide = True
        add.location = (0.0, -60.0 - 30.0 * index)
        links.new(total, add.inputs[0])
        links.new(socket, add.inputs[1])
        total = add.outputs[0]
    # Menu inputs know their choices once linked to their switch.
    items = {item.identifier: item for item in group.interface.items_tree if getattr(item, "item_type", "") == "SOCKET"}
    for entry in tuple(group.get("fbp_menu_defaults", ()) or ()):
        identifier, _sep, name = str(entry).partition("\x1f")
        item = items.get(identifier)
        try:
            if item is not None and name:
                item.default_value = name
        except FBP_DATA_ERRORS:
            pass
    target = group_output.inputs[0]
    if total is None:
        links.new(geometry_source, target)
        return
    store = nodes.new("GeometryNodeStoreNamedAttribute")
    store[_SHELL_USAGE_NODE_KEY] = True
    store.data_type = "FLOAT"
    # Instance domain: plain meshes have none, so nothing is ever allocated.
    store.domain = "INSTANCE"
    store.inputs["Name"].default_value = _SHELL_USAGE_ATTRIBUTE
    store.location = (group_output.location.x - 360.0, group_output.location.y + 160.0)
    drop = nodes.new("GeometryNodeRemoveAttribute")
    drop[_SHELL_USAGE_NODE_KEY] = True
    drop.inputs["Name"].default_value = _SHELL_USAGE_ATTRIBUTE
    drop.location = (group_output.location.x - 180.0, group_output.location.y + 160.0)
    # Without instances nothing was stored: keep "attribute does not exist"
    # out of the modifier.
    for node in (store, drop):
        try:
            node.warning_propagation = "NONE"
        except FBP_DATA_ERRORS:
            pass
    try:
        drop.inputs["Pattern Mode"].default_value = "Wildcard"
    except (KeyError, *FBP_DATA_ERRORS):
        pass
    links.new(geometry_source, store.inputs["Geometry"])
    links.new(total, store.inputs["Value"])
    links.new(store.outputs["Geometry"], drop.inputs["Geometry"])
    links.new(drop.outputs["Geometry"], target)


def _populate_shell_group(group, effect_id):
    """(Re)build every input of one shell from the effect's panel controls."""
    interface = group.interface
    nodes = group.nodes
    for item in tuple(interface.items_tree):
        if getattr(item, "item_type", "") == "PANEL":
            continue
        if getattr(item, "socket_type", "") == "NodeSocketGeometry":
            continue
        interface.remove(item)
    for item in tuple(interface.items_tree):
        if getattr(item, "item_type", "") == "PANEL":
            interface.remove(item)
    nodes.clear()
    if not any(
        getattr(item, "socket_type", "") == "NodeSocketGeometry" and item.in_out == "INPUT"
        for item in interface.items_tree
    ):
        interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    if not any(
        getattr(item, "socket_type", "") == "NodeSocketGeometry" and item.in_out == "OUTPUT"
        for item in interface.items_tree
    ):
        interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    group_input = nodes.new("NodeGroupInput")
    group_input.location = (-400.0, 0.0)
    group_output = nodes.new("NodeGroupOutput")
    group_output.location = (400.0, 0.0)
    mapping, layer_mapping, used = _add_inputs(group, _shell_layout_entries(effect_id))
    group["fbp_shell_mapping"] = ["\x1f".join(entry) for entry in mapping]
    group[_SHELL_LAYER_MAPPING_KEY] = ["\x1f".join(entry) for entry in layer_mapping]
    _wire_usage(group, used, group_input.outputs[0], group_output)
    _actions_first(group)
    group[_SHELL_UI_KEY] = _SHELL_UI_VERSION
    return group


def _actions_first(group):
    """Make the action button rows the modifier's first rows.

    They go right after the Geometry input: a Geometry Nodes modifier feeds
    its geometry into the group's first input.
    """
    identifiers = dict(
        (entry[0], entry[2]) for entry in _shell_layer_mapping(group) if entry[0] in _ACTION_KEYS
    )
    interface = group.interface
    offset = 1
    for key in _ACTION_KEYS:
        item = next((
            other for other in interface.items_tree
            if identifiers.get(key) and getattr(other, "identifier", "") == identifiers[key]
        ), None)
        if item is None:
            continue
        geometry = next((
            index for index, other in enumerate(interface.items_tree)
            if getattr(other, "in_out", "") == "INPUT"
            and getattr(other, "socket_type", "") == "NodeSocketGeometry"
        ), -1)
        try:
            # A row of buttons instead of a dropdown.
            item.menu_expanded = True
            interface.move(item, geometry + offset)
            offset += 1
        except FBP_DATA_ERRORS:
            pass


_GEOMETRY_INPUTS_KEY = "fbp_panel_inputs"


def _describe_mapped_choices(interface, definition):
    """Name the choices of a mesh effect's numbered inputs.

    Some mesh effects read a choice (Pattern, Mode, ...) as a number input.
    The modifier shows it as a plain number, so its tooltip lists what each
    number means and its range stops at the last choice.
    """
    sockets = {
        str(item.name): item for item in interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET" and getattr(item, "in_out", "") == "INPUT"
    }
    for prop_name, socket_name in (definition.get("property_map", {}) or {}).items():
        rna = _object_rna(prop_name)
        item = sockets.get(str(socket_name))
        if rna is None or item is None or rna.type != "ENUM" or getattr(rna, "is_enum_flag", False):
            continue
        socket_type = getattr(item, "socket_type", "")
        if socket_type == "NodeSocketFloat" and str(getattr(item, "description", "") or ""):
            # A described number input maps the choice its own way (-1/+1).
            continue
        if socket_type not in {"NodeSocketInt", "NodeSocketFloat"}:
            continue
        try:
            choices = tuple(rna.enum_items)
            item.description = ", ".join(f"{index} {choice.name}" for index, choice in enumerate(choices))
            item.min_value = 0
            item.max_value = max(0, len(choices) - 1)
        except FBP_DATA_ERRORS:
            pass


def _section_native_inputs(interface, effect_id, definition, entries):
    """Put a mesh effect's own inputs in the sections of its panel.

    The modifier then reads like the Frame By Plane panel (Quality, Depth,
    Optics, ...) instead of one long list. Sockets keep their identifiers,
    so values, keyframes and drivers are untouched. Returns the sections by
    title for the panel settings added after them.
    """
    geo = _geo()
    section_of = {}
    order = []
    for title, _icon, names in geo._FBP_EFFECT_UI_GROUPS.get(effect_id, ()):
        order.append(title)
        for name in names:
            section_of.setdefault(name, title)
    sockets = {
        str(item.name): item for item in interface.items_tree
        if getattr(item, "item_type", "") == "SOCKET"
        and getattr(item, "in_out", "") == "INPUT"
        and getattr(item, "parent", None) is not None
        and not str(getattr(item.parent, "name", "") or "")
    }
    moves = []
    for prop_name, socket_name in (definition.get("property_map", {}) or {}).items():
        item = sockets.get(str(socket_name))
        title = section_of.get(prop_name)
        if item is not None and title and getattr(item, "socket_type", "") != "NodeSocketGeometry":
            moves.append((title, item))
    titles = set(title for title, _item in moves) | set(entry[6] for entry in entries if entry[6])
    panels = {}
    for title in [title for title in dict.fromkeys(order) if title in titles]:
        panel = interface.new_panel(title, default_closed=False)
        try:
            panel.description = "fbp_panel_inputs"
        except FBP_DATA_ERRORS:
            pass
        panels[title] = panel
    for title, item in moves:
        panel = panels[title]
        try:
            interface.move_to_parent(item, panel, len(panel.interface_items))
        except FBP_DATA_ERRORS:
            pass
    return panels


def fbp_extend_geometry_group(group, effect_id):
    """Give a mesh effect's node group the panel controls it lacks.

    Mesh effects already take their main settings as modifier inputs. This
    adds the rest of the panel (Animate, quality for playback and render,
    shading, choices) as extra inputs in their own sections, synced with the
    layer like an image effect's. Idempotent: a group extended by this
    version is left alone.
    """
    if group is None:
        return False
    marker = f"{_SHELL_UI_VERSION}:{effect_id}"
    try:
        if str(group.get(_GEOMETRY_INPUTS_KEY, "") or "") == marker:
            return False
        if getattr(group, "library", None) is not None:
            return False
    except FBP_DATA_ERRORS:
        return False
    geo = _geo()
    definition = geo.fbp_effect_definition(effect_id) or {}
    try:
        interface = group.interface
        nodes, links = group.nodes, group.links
        # Drop what an earlier version added.
        added = set(str(name) for name in (group.get("fbp_panel_input_ids", ()) or ()))
        for item in tuple(interface.items_tree):
            if getattr(item, "item_type", "") == "SOCKET" and item.identifier in added:
                interface.remove(item)
        for item in tuple(interface.items_tree):
            if getattr(item, "item_type", "") == "PANEL" and bool(
                str(getattr(item, "description", "") or "") == "fbp_panel_inputs"
            ):
                interface.remove(item)
        group_output = next(
            (node for node in nodes if node.bl_idname == "NodeGroupOutput" and node.is_active_output),
            None,
        ) or next((node for node in nodes if node.bl_idname == "NodeGroupOutput"), None)
        group_input = next((node for node in nodes if node.bl_idname == "NodeGroupInput"), None)
        if group_output is None or group_input is None:
            return False
        source = None
        for node in tuple(nodes):
            if node.get(_SHELL_USAGE_NODE_KEY):
                if node.bl_idname == "GeometryNodeStoreNamedAttribute" and node.inputs["Geometry"].is_linked:
                    source = node.inputs["Geometry"].links[0].from_socket
                nodes.remove(node)
        target = group_output.inputs[0]
        if source is None:
            if not target.is_linked:
                return False
            source = target.links[0].from_socket
        _describe_mapped_choices(interface, definition)
        mapped_sockets = set((definition.get("property_map", {}) or {}).keys())
        entries = _shell_layout_entries(effect_id, skip=mapped_sockets)
        entries = [entry[:3] + ("RIG" if entry[3] == "MATERIAL" else entry[3],) + entry[4:] for entry in entries]
        before = {item.identifier for item in interface.items_tree if getattr(item, "item_type", "") == "SOCKET"}
        panels_before = {
            int(item.as_pointer()) for item in interface.items_tree if getattr(item, "item_type", "") == "PANEL"
        }
        panels = _section_native_inputs(interface, effect_id, definition, entries)
        _mapping, layer_mapping, used = _add_inputs(group, entries, panels)
        for item in interface.items_tree:
            if getattr(item, "item_type", "") == "PANEL" and int(item.as_pointer()) not in panels_before:
                try:
                    item.description = "fbp_panel_inputs"
                except FBP_DATA_ERRORS:
                    pass
        group["fbp_panel_input_ids"] = [
            item.identifier for item in interface.items_tree
            if getattr(item, "item_type", "") == "SOCKET" and item.identifier not in before
        ]
        group[_SHELL_LAYER_MAPPING_KEY] = ["\x1f".join(entry) for entry in layer_mapping]
        if used:
            _wire_usage(group, used, source, group_output)
        elif not target.is_linked:
            links.new(source, target)
        _actions_first(group)
        group[_GEOMETRY_INPUTS_KEY] = marker
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not add the effect's panel settings to its modifier", exc)
        return False


def _shell_needs_rebuild(group):
    try:
        return group is not None and int(group.get(_SHELL_UI_KEY, 0) or 0) < _SHELL_UI_VERSION
    except FBP_DATA_ERRORS:
        return False


def _stored_mapping(group, key):
    """Rows of four fields stored under ``key`` on a shell node group."""
    try:
        raw = tuple(group.get(key, ()) or ())
    except FBP_DATA_ERRORS:
        return ()
    return tuple(
        tuple(parts) for parts in (str(entry).split("\x1f") for entry in raw)
        if len(parts) == 4
    )


def _shell_layer_mapping(group):
    return _stored_mapping(group, _SHELL_LAYER_MAPPING_KEY)


def _layer_owner(rig, effect_id, instance_id, prop_name, storage):
    """Return ``(owner, attribute)`` holding one layer setting."""
    geo = _geo()
    if storage.startswith("ANIM:"):
        item = geo.fbp_effect_instance_animation_item(rig, effect_id, instance_id, ensure=False)
        if item is not None:
            return item, storage[5:]
        return rig, prop_name
    if instance_id and geo._fbp_effect_uses_multi_instances(effect_id):
        channel = geo.fbp_effect_instance_channel(rig, effect_id, instance_id, prop_name, ensure=False)
        if channel is not None:
            return channel, geo._fbp_instance_channel_value_attr(channel)
    return rig, prop_name


def _layer_rna(effect_id, prop_name):
    """RNA (or virtual setting) behind one layer-mapped modifier input."""
    if str(prop_name).startswith("@"):
        definition = _geo().fbp_effect_definition(effect_id) or {}
        return dict(_virtual_settings(effect_id, definition)).get(prop_name)
    return _object_rna(prop_name)


def _virtual_value(rig, effect_id, instance_id, key):
    geo = _geo()
    if key == "@VARIANT":
        return effect_id
    if key == "@SOURCE":
        return geo.fbp_effect_input_source(rig, effect_id, instance_id)
    if key == "@DEBUG":
        return geo.fbp_effect_debug_mode(rig, effect_id)
    if key == "@MASKOP":
        return geo.fbp_mask_stack_operation(rig, effect_id)
    if key in _ACTION_KEYS:
        return "NONE"
    return None


def _run_virtual(rig_name, effect_id, instance_id, key, value):
    """Apply a dropdown change outside the depsgraph update that saw it."""
    geo = _geo()
    rig = bpy.data.objects.get(rig_name)
    if rig is None or not geo.fbp_effect_is_active(rig, effect_id):
        return None
    try:
        if key == "@VARIANT":
            if value != effect_id and not geo.fbp_effect_is_active(rig, value):
                if geo.fbp_switch_effect_family_variant(rig, effect_id, value):
                    geo.fbp_sync_effect_items(rig, [rig])
        elif key == "@SOURCE":
            geo.fbp_set_effect_input_source(rig, effect_id, value, instance_id=instance_id)
        elif key == "@DEBUG":
            geo.fbp_set_effect_debug_mode(rig, effect_id, value)
        elif key == "@MASKOP":
            from .mask_stack import fbp_set_mask_stack_operation
            fbp_set_mask_stack_operation(rig, effect_id, value, rebuild=True)
        elif key in _ACTION_KEYS and value != "NONE":
            _run_action(rig, effect_id, geo.fbp_effect_definition(effect_id) or {}, value)
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not apply {key[1:].title()} from the modifier", exc)
    return None


def _layer_value(rig, effect_id, instance_id, prop_name, storage, rna, kind):
    """One layer setting as the value its modifier input holds."""
    if storage == "VIRTUAL":
        if prop_name in _ACTION_KEYS:
            return ""
        value = _virtual_value(rig, effect_id, instance_id, prop_name)
        return None if value is None else _menu_name(rna, str(value))
    owner, attr = _layer_owner(rig, effect_id, instance_id, prop_name, storage)
    try:
        value = getattr(owner, attr)
    except FBP_DATA_ERRORS:
        return None
    if kind == "ENUM":
        return _menu_name(rna, str(value))
    if kind in {"OBJECT", "MATERIAL", "IMAGE"}:
        return value
    if kind == "STRING":
        return str(value or "")
    if kind == "COLOR":
        return _color4(value)
    if kind == "BOOLEAN":
        return bool(value)
    if kind == "INT":
        return int(value)
    return float(value)


def _set_layer_value(rig, effect_id, instance_id, prop_name, storage, rna, kind, value):
    """Write one modifier value to the layer, running its usual update."""
    if storage == "VIRTUAL":
        identifier = _menu_identifier(rna, value)
        if str(_virtual_value(rig, effect_id, instance_id, prop_name)) == identifier:
            return False
        from .safe_tasks import schedule_once
        schedule_once(
            f"effect_shells.virtual.{rig.name}.{effect_id}.{prop_name}",
            lambda name=rig.name: _run_virtual(name, effect_id, instance_id, prop_name, identifier),
            first_interval=0.0,
        )
        return True
    owner, attr = _layer_owner(rig, effect_id, instance_id, prop_name, storage)
    if kind == "ENUM":
        value = _menu_identifier(rna, value)
    elif kind in {"OBJECT", "MATERIAL", "IMAGE"}:
        pass
    elif kind == "STRING":
        value = str(value or "")
    elif kind == "COLOR":
        value = tuple(value)[:int(rna.array_length)]
    elif kind == "BOOLEAN":
        value = bool(value)
    elif kind == "INT":
        value = int(value)
    else:
        value = float(value)
    try:
        if _comparable(getattr(owner, attr)) == _comparable(value):
            return False
        setattr(owner, attr, value)
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not apply {prop_name} from its modifier", exc)
        return False


def _remove_shell_attribute_nodes(rig, token):
    geo = _geo()
    effect_id, instance_id = geo._fbp_effect_ref_parts(token)
    for node in _effect_nodes(rig, effect_id, instance_id):
        tree = node.id_data
        for attr_node in tuple(tree.nodes):
            try:
                if str(attr_node.get(_SHELL_ATTR_NODE_KEY, "") or "") == token:
                    tree.nodes.remove(attr_node)
            except FBP_DATA_ERRORS:
                continue


def _init_shell_values(rig, modifier, effect_id, instance_id, source=None):
    """Fill a new or rebuilt shell from the material and the layer."""
    group = modifier.node_group
    parameters = {prop: rna for prop, _socket, rna in _shell_parameters(effect_id)}
    for prop_name, socket_name, identifier, _kind_name in _shell_mapping(group):
        rna = parameters.get(prop_name)
        if rna is None:
            continue
        socket = source.inputs.get(socket_name) if source is not None else None
        if socket is not None and not socket.is_linked:
            value = socket.default_value
        else:
            value = getattr(rig, prop_name, 0.0)
        _set_modifier_input(modifier, identifier, rna, value)
    for prop_name, storage, identifier, kind in _shell_layer_mapping(group):
        rna = _layer_rna(effect_id, prop_name)
        if rna is None:
            continue
        value = _layer_value(rig, effect_id, instance_id, prop_name, storage, rna, kind)
        if value is None and kind not in _DATA_KINDS:
            continue
        try:
            if prop_name in _ACTION_KEYS:
                _rest_action_input(modifier, identifier)
            else:
                _geo()._fbp_modifier_input_set(modifier, identifier, _color4(value) if kind == "COLOR" else value)
        except FBP_DATA_ERRORS as exc:
            fbp_warn(f"Could not set shell input {identifier}", exc)
    group[_SHELL_SYNCED_KEY] = _shell_snapshot(modifier)


def _shell_snapshot(modifier):
    group = modifier.node_group
    identifiers = [entry[2] for entry in _shell_mapping(group)]
    identifiers.extend(entry[2] for entry in _shell_layer_mapping(group) if entry[0] not in _ACTION_KEYS)
    snapshot = {identifier: _storable(_modifier_input(modifier, identifier)) for identifier in identifiers}
    snapshot.update(
        (entry[2], _action_input(modifier, entry[2]))
        for entry in _shell_layer_mapping(group) if entry[0] in _ACTION_KEYS
    )
    return snapshot


def _rebuild_shell(rig, token, modifier):
    """Bring a shell saved by an older version up to the current inputs."""
    geo = _geo()
    effect_id, instance_id = geo._fbp_effect_ref_parts(token)
    nodes = _effect_nodes(rig, effect_id, instance_id)
    # Keep the values the material shows before its links are dropped.
    source_values = {}
    if nodes:
        parameters = {prop: rna for prop, _socket, rna in _shell_parameters(effect_id)}
        for prop_name, socket_name, identifier, _kind_name in _shell_mapping(modifier.node_group):
            value = _modifier_input(modifier, identifier)
            if value is not None and prop_name in parameters:
                source_values[socket_name] = value
    _remove_shell_attribute_nodes(rig, token)
    _populate_shell_group(modifier.node_group, effect_id)
    source = nodes[0] if nodes else None
    if source is not None:
        for socket_name, value in source_values.items():
            socket = source.inputs.get(socket_name)
            if socket is None:
                continue
            try:
                if hasattr(value, "__len__"):
                    value = tuple(value)[:len(tuple(socket.default_value))]
                socket.default_value = value
            except FBP_DATA_ERRORS:
                pass
    _init_shell_values(rig, modifier, effect_id, instance_id, source)
    # Choices left the material links: let the layer write them again.
    for prop_name, storage, _identifier, kind in _shell_layer_mapping(modifier.node_group):
        if kind != "ENUM" or storage != "RIG":
            continue
        try:
            setattr(rig, prop_name, getattr(rig, prop_name))
        except FBP_DATA_ERRORS:
            pass
    return True


def _shell_mapping(group):
    return _stored_mapping(group, "fbp_shell_mapping")


def fbp_shell_covered_settings(group):
    """Layer settings (and ``@`` panel controls) that are inputs of ``group``."""
    return frozenset(
        entry[0] for entry in _shell_mapping(group) + _shell_layer_mapping(group)
    )


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
    for token, modifier in fbp_shell_modifiers(rig):
        # Files saved before every panel control became an input.
        if _shell_needs_rebuild(modifier.node_group):
            try:
                changed = bool(_rebuild_shell(rig, token, modifier)) or changed
            except FBP_DATA_ERRORS as exc:
                fbp_warn("Could not update the effect's modifier inputs", exc)
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
    _init_shell_values(rig, modifier, effect_id, instance_id, nodes[0] if nodes else None)
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


_DATA_KINDS = {"OBJECT", "MATERIAL", "IMAGE"}
_ID_PREFIX = "\x00ID:"


def _storable(value):
    """A value the sync snapshot (an ID property) can hold."""
    if value is None or isinstance(value, bpy.types.ID):
        return _ID_PREFIX + (getattr(value, "name_full", "") if value is not None else "")
    return value


def _comparable(value):
    if value is None or isinstance(value, bpy.types.ID):
        return ("ID", getattr(value, "name_full", "") if value is not None else "")
    if isinstance(value, str):
        if value.startswith(_ID_PREFIX):
            return ("ID", value[len(_ID_PREFIX):])
        return value
    if hasattr(value, "__len__"):
        return tuple(round(float(v), 5) for v in tuple(value)[:4])
    try:
        return round(float(value), 5)
    except (TypeError, ValueError):
        return None


def _same_snapshot(stored, synced):
    """True when the new sync snapshot equals the one already saved.

    The saved snapshot comes back from the ID property with vectors and
    colours as ``IDPropertyArray``, which never equals a tuple: a plain ``!=``
    rewrote the snapshot on every sync, on every geometry update of the plane.
    """
    if stored.keys() != synced.keys():
        return False
    return all(_comparable(stored[key]) == _comparable(synced[key]) for key in stored)


def _socket_as_modifier_value(rna, socket):
    value = socket.default_value
    if _is_color(rna):
        return _color4(value)
    if rna.type == "INT":
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
        if _shell_needs_rebuild(modifier.node_group):
            continue
        nodes = _effect_nodes(rig, effect_id, instance_id)
        parameters = {prop: rna for prop, _socket, rna in _shell_parameters(effect_id)}
        try:
            synced = dict(modifier.node_group.get(_SHELL_SYNCED_KEY, {}) or {})
        except FBP_DATA_ERRORS:
            synced = {}
        to_layer = {}
        stored = {}
        for prop_name, socket_name, identifier, _kind_name in (
            _shell_mapping(modifier.node_group) if nodes else ()
        ):
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
                    _set_modifier_input(modifier, identifier, rna, material_value)
                    current = _modifier_input(modifier, identifier)
                    moved += 1
            stored[identifier] = current
        moved += _sync_layer_inputs(rig, modifier, effect_id, instance_id, synced, stored)
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
        for node in nodes:
            # Samples or a gating input edited or keyed in the Modifiers
            # panel: keep reading exactly the texture taps the values need.
            try:
                geo._fbp_sync_runtime_mutes(rig, effect_id, node)
            except FBP_DATA_ERRORS:
                pass
        if not _same_snapshot(stored, synced):
            try:
                modifier.node_group[_SHELL_SYNCED_KEY] = stored
            except FBP_DATA_ERRORS:
                pass
    return moved


def _sync_layer_inputs(rig, modifier, effect_id, instance_id, synced, stored):
    """Two-way sync of the inputs that mirror layer settings (see above)."""
    geo = _geo()
    moved = 0
    for prop_name, storage, identifier, kind in _shell_layer_mapping(modifier.node_group):
        rna = _layer_rna(effect_id, prop_name)
        if rna is None:
            continue
        if _geo()._fbp_modifier_input_handle(modifier, identifier) is None:
            continue
        current = (
            _action_input(modifier, identifier) if prop_name in _ACTION_KEYS
            else _modifier_input(modifier, identifier)
        )
        if current is None and kind not in _DATA_KINDS:
            continue
        layer = _layer_value(rig, effect_id, instance_id, prop_name, storage, rna, kind)
        last = synced.get(identifier)
        last = _comparable(last) if last is not None else None
        if last is not None and _comparable(current) != last:
            moved += bool(_set_layer_value(
                rig, effect_id, instance_id, prop_name, storage, rna, kind, current
            ))
        elif (layer is not None or kind in _DATA_KINDS) and _comparable(layer) != _comparable(current):
            try:
                if prop_name in _ACTION_KEYS:
                    _rest_action_input(modifier, identifier)
                else:
                    geo._fbp_modifier_input_set(modifier, identifier, layer)
            except FBP_DATA_ERRORS as exc:
                fbp_warn(f"Could not set shell input {identifier}", exc)
            current = (
                _action_input(modifier, identifier) if prop_name in _ACTION_KEYS
                else _modifier_input(modifier, identifier)
            )
            moved += 1
        stored[identifier] = _storable(current)
    return moved


def _action_input(modifier, identifier):
    """The pressed button of a button row, or "" when none is.

    Reads the stored number: reading ``value`` while it names no item makes
    Blender print a warning every time.
    """
    handle = _geo()._fbp_modifier_input_handle(modifier, identifier)
    if handle is None:
        return None
    try:
        number = int(handle.get("value", -1))
        items = handle.bl_rna.properties["value"].enum_items
    except FBP_DATA_ERRORS:
        return None
    return next((str(item.name) for item in items if int(item.value) == number), "")


def _rest_action_input(modifier, identifier):
    """Put a button row back to no pressed button after it ran its action.

    The menu value is stored as a number; one that names no item draws every
    button unpressed.
    """
    handle = _geo()._fbp_modifier_input_handle(modifier, identifier)
    if handle is None:
        return
    try:
        used = {int(item.value) for item in handle.bl_rna.properties["value"].enum_items}
    except FBP_DATA_ERRORS:
        used = set()
    handle["value"] = next(number for number in range(len(used) + 1) if number not in used)


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
    for prop_name, socket_name, identifier, _kind in _shell_mapping(modifier.node_group):
        handle = geo._fbp_modifier_input_handle(modifier, identifier)
        if handle is None:
            continue
        handles[prop_name] = handle
        rna = _object_rna(prop_name)
        labels[prop_name] = str(getattr(rna, "name", "") or socket_name)
    if not handles:
        return layout
    channel_key = (geo.fbp_normalize_effect_id(effect_id), str(instance_id or ""))
    return _ShellLayout(layout, rig, handles, labels, channel_key)


classes = ()


def register():
    _OBJECT_RNA_CACHE.clear()
    register_classes(classes)


def unregister():
    _OBJECT_RNA_CACHE.clear()
    unregister_classes(classes)


_GEOMETRY_SYNCED = {}


def fbp_sync_geometry_panel_inputs(rig, effect_id, modifier):
    """Two-way sync of the panel settings added to a mesh effect's group."""
    if modifier is None or modifier.node_group is None:
        return 0
    try:
        key = int(modifier.as_pointer())
    except FBP_DATA_ERRORS:
        return 0
    synced = _GEOMETRY_SYNCED.get(key, {})
    stored = {}
    moved = _sync_layer_inputs(rig, modifier, effect_id, "", synced, stored)
    _GEOMETRY_SYNCED[key] = stored
    return moved
