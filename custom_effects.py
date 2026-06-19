"""User-defined node-group effects for Frame by Plane 5.1.x.

A custom effect is an ordinary local Geometry Nodes or Shader node group tagged
with a compact Frame by Plane contract.  The node group remains the user's
source of truth: editing it updates every layer that uses the effect, while
per-layer socket values stay on the modifier or group-node instance.
"""

import time
import uuid

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from .constants import fbp_icon
from .runtime import fbp_warn


CUSTOM_EFFECT_PREFIX = "CUSTOM_"
CUSTOM_EFFECT_CONTRACT_VERSION = 1

KEY_ID = "fbp_custom_effect_id"
KEY_LABEL = "fbp_custom_effect_label"
KEY_ICON = "fbp_custom_effect_icon"
KEY_DESCRIPTION = "fbp_custom_effect_description"
KEY_KIND = "fbp_custom_effect_kind"
KEY_CATEGORY = "fbp_custom_effect_category"
KEY_HIDDEN = "fbp_custom_effect_hidden"
KEY_CONTRACT_VERSION = "fbp_custom_effect_contract_version"
KEY_COLOR_INPUT = "fbp_custom_effect_color_input"
KEY_COLOR_OUTPUT = "fbp_custom_effect_color_output"
KEY_ALPHA_INPUT = "fbp_custom_effect_alpha_input"
KEY_ALPHA_OUTPUT = "fbp_custom_effect_alpha_output"
KEY_UV_INPUT = "fbp_custom_effect_uv_input"

_CUSTOM_REFRESH_TIME = 0.0
_CUSTOM_EFFECT_IDS = set()
_CUSTOM_GROUP_NAMES = {}
_CUSTOM_GROUP_REFS = {}
_CUSTOM_GROUP_SIGNATURES = {}
_CUSTOM_GROUP_COUNT = -1
_CUSTOM_DEFINITION_CACHE = {}
_CUSTOM_GROUP_MISS_CACHE = {}
_CUSTOM_GROUP_MISS_SECONDS = 1.0
_CUSTOM_REFRESH_MIN_SECONDS = 0.25

_CUSTOM_REGISTRY_REFRESH_CALLBACK = globals().get("_CUSTOM_REGISTRY_REFRESH_CALLBACK")


def set_custom_effect_registry_refresh_callback(callback):
    """Install the lightweight registry refresh hook without importing its module."""
    global _CUSTOM_REGISTRY_REFRESH_CALLBACK
    _CUSTOM_REGISTRY_REFRESH_CALLBACK = callback if callable(callback) else None


def request_custom_effect_registry_refresh(force=True):
    """Refresh the live registry when the registry module is available."""
    callback = _CUSTOM_REGISTRY_REFRESH_CALLBACK
    if not callable(callback):
        return False
    try:
        callback(force=bool(force))
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not refresh custom effect registry", exc)
        return False



CUSTOM_EFFECT_ICON_ITEMS = (
    ("NODETREE", "Nodes", "Generic node effect", fbp_icon("NODETREE"), 0),
    ("NODE_TEXTURE", "Texture", "Texture or image processing", fbp_icon("NODE_TEXTURE"), 1),
    ("MODIFIER", "Modifier", "Generic modifier", fbp_icon("MODIFIER"), 2),
    ("MOD_DISPLACE", "Displace", "Displacement effect", fbp_icon("MOD_DISPLACE"), 3),
    ("MOD_WAVE", "Wave", "Wave or ripple effect", fbp_icon("MOD_WAVE"), 4),
    ("MOD_SIMPLEDEFORM", "Deform", "Mesh deformation", fbp_icon("MOD_SIMPLEDEFORM"), 5),
    ("MOD_SOLIDIFY", "Solidify", "Thickness or extrusion", fbp_icon("MOD_SOLIDIFY"), 6),
    ("MATERIAL", "Material", "Material effect", fbp_icon("MATERIAL"), 7),
    ("SHADING_RENDERED", "Shader", "Shader effect", fbp_icon("SHADING_RENDERED"), 8),
    ("COLOR", "Color", "Color processing", fbp_icon("COLOR"), 9),
    ("IMAGE", "Image", "Image effect", fbp_icon("IMAGE"), 10),
    ("IMAGE_ALPHA", "Alpha", "Alpha or mask effect", fbp_icon("IMAGE_ALPHA"), 11),
    ("TEXTURE", "Pattern", "Pattern effect", fbp_icon("TEXTURE"), 12),
    ("RNDCURVE", "Noise", "Procedural or animated noise", fbp_icon("RNDCURVE"), 13),
    ("FORCE_WIND", "Wind", "Wind or motion effect", fbp_icon("FORCE_WIND"), 14),
    ("PARTICLES", "Particles", "Particle-like effect", fbp_icon("PARTICLES"), 15),
    ("LIGHT", "Light", "Light or shadow effect", fbp_icon("LIGHT"), 16),
    ("CAMERA_DATA", "Camera", "Camera-aware effect", fbp_icon("CAMERA_DATA"), 17),
    ("WORLD", "World", "Environment-style effect", fbp_icon("WORLD"), 18),
    ("MESH_GRID", "Grid", "Grid or matrix effect", fbp_icon("MESH_GRID"), 19),
    ("MESH_CIRCLE", "Circle", "Circular effect", fbp_icon("MESH_CIRCLE"), 20),
    ("MESH_CUBE", "Volume", "Volumetric or solid effect", fbp_icon("MESH_CUBE"), 21),
    ("FONT_DATA", "Text", "Text effect", fbp_icon("FONT_DATA"), 22),
    ("BRUSH_DATA", "Organic", "Organic or painted effect", fbp_icon("BRUSH_DATA"), 23),
    ("SPARKLES", "Sparkles", "Decorative effect", fbp_icon("SPARKLES"), 24),
)
_CUSTOM_EFFECT_ICON_IDS = frozenset(item[0] for item in CUSTOM_EFFECT_ICON_ITEMS)


def _valid_effect_icon(icon, kind=""):
    icon = str(icon or "")
    if icon in _CUSTOM_EFFECT_ICON_IDS:
        return icon
    return "MODIFIER" if str(kind).upper() == "GEOMETRY" else "NODETREE"


def is_custom_effect_id(effect_id):
    return str(effect_id or "").startswith(CUSTOM_EFFECT_PREFIX)


def _group_kind(node_group):
    tree_type = str(getattr(node_group, "bl_idname", "") or "")
    if tree_type == "GeometryNodeTree":
        return "GEOMETRY"
    if tree_type == "ShaderNodeTree":
        return "SHADER"
    return ""


def _interface_sockets(node_group, in_out=None):
    interface = getattr(node_group, "interface", None) if node_group else None
    if not interface:
        return []
    result = []
    try:
        for item in interface.items_tree:
            if getattr(item, "item_type", "") != "SOCKET":
                continue
            if in_out and getattr(item, "in_out", "") != in_out:
                continue
            result.append(item)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return []
    return result


def _socket_type(item):
    return str(
        getattr(item, "socket_type", "")
        or getattr(item, "bl_socket_idname", "")
        or ""
    )


def _custom_definition_signature(node_group):
    """Return a compact signature for metadata and the exposed interface."""
    try:
        group_uid = int(getattr(node_group, "session_uid", 0) or 0)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        group_uid = 0
    if not group_uid:
        try:
            group_uid = int(node_group.as_pointer())
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            group_uid = 0
    metadata_keys = (
        KEY_ID, KEY_LABEL, KEY_ICON, KEY_DESCRIPTION, KEY_KIND, KEY_CATEGORY,
        KEY_HIDDEN, KEY_CONTRACT_VERSION, KEY_COLOR_INPUT, KEY_COLOR_OUTPUT,
        KEY_ALPHA_INPUT, KEY_ALPHA_OUTPUT, KEY_UV_INPUT,
    )
    try:
        metadata = tuple(str(node_group.get(key, "") or "") for key in metadata_keys)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        metadata = ()
    sockets = []
    for item in _interface_sockets(node_group):
        try:
            sockets.append((
                str(getattr(item, "identifier", "") or ""),
                str(getattr(item, "name", "") or ""),
                str(getattr(item, "in_out", "") or ""),
                _socket_type(item),
                bool(getattr(item, "hide_value", False)),
            ))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return (
        group_uid,
        str(getattr(node_group, "name_full", getattr(node_group, "name", "")) or ""),
        str(getattr(node_group, "bl_idname", "") or ""),
        metadata,
        tuple(sockets),
    )


def _find_socket_name(node_group, in_out, aliases, socket_types=(), fallback_by_type=True):
    sockets = _interface_sockets(node_group, in_out)
    aliases = tuple(str(name).casefold() for name in aliases)
    socket_types = set(socket_types or ())
    for item in sockets:
        if str(getattr(item, "name", "") or "").casefold() in aliases:
            if not socket_types or _socket_type(item) in socket_types:
                return str(getattr(item, "name", "") or "")
    if socket_types and fallback_by_type:
        for item in sockets:
            if _socket_type(item) in socket_types:
                return str(getattr(item, "name", "") or "")
    return ""


def validate_custom_effect_group(node_group):
    """Return ``(valid, message, contract)`` for a user node group."""
    if node_group is None:
        return False, "Choose a node group", {}
    if getattr(node_group, "library", None) is not None:
        return False, "Linked node groups are read-only; make the group local first", {}
    if bool(node_group.get("fbp_private_effect_group", False)):
        return False, "Private Frame by Plane node-group copies cannot be registered", {}
    kind = _group_kind(node_group)
    if not kind:
        return False, "Only Geometry Nodes and Shader node groups are supported", {}

    if kind == "GEOMETRY":
        geometry_types = {"NodeSocketGeometry"}
        geometry_input = _find_socket_name(
            node_group, "INPUT", ("Geometry",), geometry_types
        )
        geometry_output = _find_socket_name(
            node_group, "OUTPUT", ("Geometry",), geometry_types
        )
        if not geometry_input or not geometry_output:
            return (
                False,
                "Geometry effects require a Geometry input and a Geometry output",
                {},
            )
        return True, "", {"kind": kind}

    color_types = {"NodeSocketColor"}
    float_types = {"NodeSocketFloat", "NodeSocketFloatFactor"}
    vector_types = {"NodeSocketVector"}
    color_input = _find_socket_name(
        node_group,
        "INPUT",
        ("Color In", "Color", "Image", "Input"),
        color_types,
        False,
    )
    color_output = _find_socket_name(
        node_group,
        "OUTPUT",
        ("Color Out", "Color", "Image", "Output"),
        color_types,
        False,
    )
    if not color_input or not color_output:
        return (
            False,
            "Shader effects require a Color input and a Color output",
            {},
        )
    alpha_input = _find_socket_name(
        node_group, "INPUT", ("Alpha In", "Alpha", "Mask In", "Mask"), float_types, False
    )
    alpha_output = _find_socket_name(
        node_group, "OUTPUT", ("Alpha Out", "Alpha", "Mask Out", "Mask"), float_types, False
    )
    # Alpha is all-or-nothing. A lone alpha socket would make stack routing
    # ambiguous and could silently bypass layer opacity.
    if bool(alpha_input) != bool(alpha_output):
        return (
            False,
            "Provide both Alpha In and Alpha Out, or remove both alpha sockets",
            {},
        )
    uv_input = _find_socket_name(
        node_group,
        "INPUT",
        ("UV Vector", "Vector", "UV"),
        vector_types,
        False,
    )
    return True, "", {
        "kind": kind,
        "color_input": color_input,
        "color_output": color_output,
        "alpha_input": alpha_input,
        "alpha_output": alpha_output,
        "uv_input": uv_input,
    }


def _new_custom_effect_id():
    return f"{CUSTOM_EFFECT_PREFIX}{uuid.uuid4().hex.upper()}"


def _effect_id_in_other_group(effect_id, node_group):
    if not effect_id:
        return False
    for candidate in getattr(bpy.data, "node_groups", ()):
        if candidate is node_group:
            continue
        try:
            if str(candidate.get(KEY_ID, "") or "") == effect_id:
                return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return False


def tag_custom_effect_group(node_group, label, icon, description="", category="AUTO"):
    valid, message, contract = validate_custom_effect_group(node_group)
    if not valid:
        raise ValueError(message)

    effect_id = str(node_group.get(KEY_ID, "") or "")
    if not is_custom_effect_id(effect_id) or _effect_id_in_other_group(effect_id, node_group):
        effect_id = _new_custom_effect_id()
    kind = contract["kind"]
    resolved_category = "3D" if kind == "GEOMETRY" else "2D"
    if category in {"2D", "3D"}:
        resolved_category = category
    asset_id = f"frame_by_plane.user.{effect_id[len(CUSTOM_EFFECT_PREFIX):].lower()}"

    node_group[KEY_ID] = effect_id
    node_group[KEY_LABEL] = str(label or getattr(node_group, "name", "Custom Effect"))
    node_group[KEY_ICON] = _valid_effect_icon(icon, kind)
    node_group[KEY_DESCRIPTION] = str(description or "User-defined node-group effect")
    node_group[KEY_KIND] = kind
    node_group[KEY_CATEGORY] = resolved_category
    node_group[KEY_HIDDEN] = False
    node_group[KEY_CONTRACT_VERSION] = CUSTOM_EFFECT_CONTRACT_VERSION
    node_group[KEY_COLOR_INPUT] = str(contract.get("color_input", "") or "")
    node_group[KEY_COLOR_OUTPUT] = str(contract.get("color_output", "") or "")
    node_group[KEY_ALPHA_INPUT] = str(contract.get("alpha_input", "") or "")
    node_group[KEY_ALPHA_OUTPUT] = str(contract.get("alpha_output", "") or "")
    node_group[KEY_UV_INPUT] = str(contract.get("uv_input", "") or "")

    # The generic effect stack already understands these tags. Keeping them on
    # the source group makes custom effects use the same repair, visibility and
    # native-render validation paths as bundled effects.
    node_group["fbp_effect_id"] = effect_id
    node_group["fbp_effect_asset_id"] = asset_id
    if kind == "GEOMETRY":
        node_group["fbp_geometry_effect_id"] = asset_id
        if "fbp_shader_effect_id" in node_group:
            del node_group["fbp_shader_effect_id"]
    else:
        node_group["fbp_shader_effect_id"] = asset_id
        if "fbp_geometry_effect_id" in node_group:
            del node_group["fbp_geometry_effect_id"]
    node_group.use_fake_user = True
    _CUSTOM_GROUP_NAMES[effect_id] = str(
        getattr(node_group, "name_full", getattr(node_group, "name", "")) or ""
    )
    _CUSTOM_GROUP_REFS[effect_id] = node_group
    _CUSTOM_GROUP_SIGNATURES[effect_id] = _custom_definition_signature(node_group)
    _CUSTOM_GROUP_MISS_CACHE.pop(effect_id, None)
    _CUSTOM_DEFINITION_CACHE.pop(effect_id, None)
    return effect_id


def custom_effect_definition(node_group, schema_version):
    """Build a live registry entry without migrating or rebuilding old data.

    Invalid registered groups remain in the registry as removable placeholders.
    This prevents an edited/broken node interface from making an existing effect
    disappear from the stack before the user can repair or remove it.
    """
    effect_id = str(node_group.get(KEY_ID, "") or "")
    if not is_custom_effect_id(effect_id):
        return None

    valid, message, contract = validate_custom_effect_group(node_group)
    detected_kind = str(contract.get("kind", "") or "").upper()
    stored_kind = str(node_group.get(KEY_KIND, "") or "").upper()
    kind = detected_kind or stored_kind or _group_kind(node_group)
    if kind not in {"GEOMETRY", "SHADER"}:
        return None

    category = str(
        node_group.get(KEY_CATEGORY, "3D" if kind == "GEOMETRY" else "2D")
        or ""
    )
    label = str(
        node_group.get(KEY_LABEL, getattr(node_group, "name", "Custom Effect"))
        or "Custom Effect"
    )
    icon = _valid_effect_icon(node_group.get(KEY_ICON, ""), kind)
    description = str(
        node_group.get(KEY_DESCRIPTION, "User-defined node-group effect") or ""
    )
    asset_id = str(node_group.get("fbp_effect_asset_id", "") or "")
    if not asset_id:
        asset_id = (
            f"frame_by_plane.user."
            f"{effect_id[len(CUSTOM_EFFECT_PREFIX):].lower()}"
        )

    definition = {
        "label": label,
        "icon": icon,
        "kind": kind,
        "category": category if category in {"2D", "3D"} else (
            "3D" if kind == "GEOMETRY" else "2D"
        ),
        "description": description,
        "performance": "USER",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
        "source_names": (str(getattr(node_group, "name", "") or ""),),
        "canonical_name": str(getattr(node_group, "name", "") or ""),
        "custom_group_name": str(
            getattr(node_group, "name_full", getattr(node_group, "name", ""))
            or ""
        ),
        "asset_id": asset_id,
        "enabled_key": (
            "fbp_custom_effect_enabled_"
            f"{effect_id[len(CUSTOM_EFFECT_PREFIX):].lower()}"
        ),
        "modifier_name": f"FBP • {label}",
        "property_map": {},
        "extra_properties": (),
        "builtin": False,
        "custom": True,
        "custom_hidden": bool(node_group.get(KEY_HIDDEN, False)),
        "custom_invalid": not valid,
        "custom_error": str(message or ""),
        "schema_version": int(schema_version),
        "alpha_aware": False,
        "private_group": False,
    }
    if kind == "SHADER":
        # Use the live interface contract when valid. Stored names are only a
        # recovery fallback for an invalid group so existing nodes stay visible.
        color_input = str(
            contract.get("color_input", "")
            or node_group.get(KEY_COLOR_INPUT, "")
            or ""
        )
        color_output = str(
            contract.get("color_output", "")
            or node_group.get(KEY_COLOR_OUTPUT, "")
            or ""
        )
        alpha_input = str(
            contract.get("alpha_input", "")
            or node_group.get(KEY_ALPHA_INPUT, "")
            or ""
        )
        alpha_output = str(
            contract.get("alpha_output", "")
            or node_group.get(KEY_ALPHA_OUTPUT, "")
            or ""
        )
        uv_input = str(
            contract.get("uv_input", "")
            or node_group.get(KEY_UV_INPUT, "")
            or ""
        )
        definition.update({
            "stage": "COLOR",
            "input_socket": color_input,
            "output_socket": color_output,
            "alpha_input_socket": alpha_input,
            "alpha_output_socket": alpha_output,
            "uv_input_socket": uv_input,
            "supports_input_source": bool(valid),
            "alpha_aware": bool(valid and alpha_input and alpha_output),
        })
    return effect_id, definition


def _missing_custom_effect_definition(effect_id, label, kind, schema_version):
    kind = str(kind or "").upper()
    if kind not in {"GEOMETRY", "SHADER"}:
        return None
    label = str(label or "Missing Custom Effect")
    token = effect_id[len(CUSTOM_EFFECT_PREFIX):].lower()
    definition = {
        "label": label,
        "icon": "MODIFIER" if kind == "GEOMETRY" else "NODETREE",
        "kind": kind,
        "category": "3D" if kind == "GEOMETRY" else "2D",
        "description": "The source custom node group is missing",
        "performance": "USER",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
        "source_names": (),
        "canonical_name": "",
        "custom_group_name": "",
        "asset_id": f"frame_by_plane.user.{token}",
        "enabled_key": f"fbp_custom_effect_enabled_{token}",
        "modifier_name": f"FBP • {label}",
        "property_map": {},
        "extra_properties": (),
        "builtin": False,
        "custom": True,
        "custom_hidden": True,
        "custom_invalid": True,
        "custom_error": "Source custom node group is missing",
        "schema_version": int(schema_version),
        "alpha_aware": False,
        "private_group": False,
    }
    if kind == "SHADER":
        definition.update({
            "stage": "COLOR",
            "input_socket": "",
            "output_socket": "",
            "alpha_input_socket": "",
            "alpha_output_socket": "",
            "uv_input_socket": "",
            "supports_input_source": False,
        })
    return definition


def _discover_orphan_custom_effects(schema_version, known_ids):
    """Recover removable placeholders after add-on reload or forced unlink."""
    found = {}
    try:
        for obj in bpy.data.objects:
            for modifier in getattr(obj, "modifiers", ()):
                effect_id = str(modifier.get("fbp_effect_id", "") or "")
                if not is_custom_effect_id(effect_id) or effect_id in known_ids:
                    continue
                label = str(getattr(modifier, "name", "") or "Missing Custom Effect")
                if label.startswith("FBP • "):
                    label = label[6:]
                definition = _missing_custom_effect_definition(
                    effect_id, label, "GEOMETRY", schema_version
                )
                if definition:
                    found.setdefault(effect_id, definition)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        for material in bpy.data.materials:
            node_tree = getattr(material, "node_tree", None)
            for node in getattr(node_tree, "nodes", ()) if node_tree else ():
                effect_id = str(node.get("fbp_shader_effect_id", "") or "")
                if not is_custom_effect_id(effect_id) or effect_id in known_ids:
                    continue
                label = str(
                    getattr(node, "label", "")
                    or getattr(node, "name", "")
                    or "Missing Custom Effect"
                )
                if label.startswith("FBP Effect • "):
                    label = label[13:]
                definition = _missing_custom_effect_definition(
                    effect_id, label, "SHADER", schema_version
                )
                if definition:
                    found.setdefault(effect_id, definition)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return found


def _custom_effect_in_use(effect_id):
    """Return whether a missing definition still has removable scene instances."""
    effect_id = str(effect_id or "")
    if not effect_id:
        return False
    try:
        for obj in bpy.data.objects:
            for modifier in getattr(obj, "modifiers", ()):
                if str(modifier.get("fbp_effect_id", "") or "") == effect_id:
                    return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        for material in bpy.data.materials:
            node_tree = getattr(material, "node_tree", None)
            for node in getattr(node_tree, "nodes", ()) if node_tree else ():
                if str(node.get("fbp_shader_effect_id", "") or "") == effect_id:
                    return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return False


def _custom_group_is_live(effect_id, node_group):
    if node_group is None:
        return False
    try:
        name = str(
            getattr(node_group, "name_full", getattr(node_group, "name", "")) or ""
        )
        if not name or bpy.data.node_groups.get(name) is not node_group:
            return False
        return str(node_group.get(KEY_ID, "") or "") == str(effect_id or "")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _tracked_custom_groups_unchanged(group_count):
    if int(group_count) != int(_CUSTOM_GROUP_COUNT):
        return False
    for effect_id, node_group in tuple(_CUSTOM_GROUP_REFS.items()):
        if not _custom_group_is_live(effect_id, node_group):
            return False
        try:
            if _CUSTOM_GROUP_SIGNATURES.get(effect_id) != _custom_definition_signature(node_group):
                return False
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False
    return True


def refresh_custom_effect_registry(registry, schema_version, force=False):
    """Synchronize tagged local node groups into the live effect registry.

    The common path validates only the already tracked custom groups. A complete
    ``bpy.data.node_groups`` scan is reserved for structural changes, explicit
    registration and file lifecycle events.
    """
    global _CUSTOM_REFRESH_TIME, _CUSTOM_EFFECT_IDS, _CUSTOM_GROUP_COUNT
    if force:
        _CUSTOM_DEFINITION_CACHE.clear()
        _CUSTOM_GROUP_MISS_CACHE.clear()
    now = time.monotonic()
    try:
        node_groups = bpy.data.node_groups
        group_count = len(node_groups)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        node_groups = ()
        group_count = -1

    if not force and (now - _CUSTOM_REFRESH_TIME) < _CUSTOM_REFRESH_MIN_SECONDS:
        return tuple(sorted(_CUSTOM_EFFECT_IDS))
    if not force and _tracked_custom_groups_unchanged(group_count):
        _CUSTOM_REFRESH_TIME = now
        return tuple(sorted(_CUSTOM_EFFECT_IDS))
    _CUSTOM_REFRESH_TIME = now

    current = {}
    current_group_names = {}
    current_group_refs = {}
    current_group_signatures = {}
    for node_group in node_groups:
        try:
            effect_id = str(node_group.get(KEY_ID, "") or "")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
        if not is_custom_effect_id(effect_id) or effect_id in current:
            continue
        try:
            signature = _custom_definition_signature(node_group)
            cached = _CUSTOM_DEFINITION_CACHE.get(effect_id)
            if cached and cached[0] == signature:
                result = (effect_id, cached[1])
            else:
                result = custom_effect_definition(node_group, schema_version)
                if result:
                    _CUSTOM_DEFINITION_CACHE[effect_id] = (signature, result[1])
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
        if not result:
            continue
        effect_id, definition = result
        # Duplicate IDs can be produced by duplicating a registered group. Keep
        # the original deterministic and require explicit registration of the
        # copy, which then receives a fresh identity.
        if effect_id not in current:
            current[effect_id] = definition
            current_group_names[effect_id] = str(
                getattr(node_group, "name_full", getattr(node_group, "name", "")) or ""
            )
            current_group_refs[effect_id] = node_group
            current_group_signatures[effect_id] = signature

    if force:
        for effect_id, definition in _discover_orphan_custom_effects(
            schema_version, set(current)
        ).items():
            current.setdefault(effect_id, definition)

    tracked_ids = set(current)
    for effect_id in tuple(_CUSTOM_EFFECT_IDS):
        if effect_id in current:
            continue
        previous = registry.get(effect_id)
        if (
            isinstance(previous, dict)
            and bool(previous.get("custom", False))
            and _custom_effect_in_use(effect_id)
        ):
            missing = dict(previous)
            missing["custom_invalid"] = True
            missing["custom_hidden"] = True
            missing["custom_error"] = "Source custom node group is missing"
            registry[effect_id] = missing
            tracked_ids.add(effect_id)
        else:
            registry.pop(effect_id, None)
            _CUSTOM_DEFINITION_CACHE.pop(effect_id, None)
    for effect_id, definition in current.items():
        registry[effect_id] = definition
    _CUSTOM_EFFECT_IDS = tracked_ids
    _CUSTOM_GROUP_COUNT = group_count
    _CUSTOM_GROUP_NAMES.clear()
    _CUSTOM_GROUP_NAMES.update(current_group_names)
    _CUSTOM_GROUP_REFS.clear()
    _CUSTOM_GROUP_REFS.update(current_group_refs)
    _CUSTOM_GROUP_SIGNATURES.clear()
    _CUSTOM_GROUP_SIGNATURES.update(current_group_signatures)
    for effect_id in current:
        _CUSTOM_GROUP_MISS_CACHE.pop(effect_id, None)
    if len(_CUSTOM_DEFINITION_CACHE) > 256:
        keep = set(current)
        for stale_id in tuple(_CUSTOM_DEFINITION_CACHE):
            if stale_id not in keep:
                _CUSTOM_DEFINITION_CACHE.pop(stale_id, None)
            if len(_CUSTOM_DEFINITION_CACHE) <= 192:
                break
    return tuple(sorted(_CUSTOM_EFFECT_IDS))


def find_custom_effect_group(effect_id):
    effect_id = str(effect_id or "")
    if not is_custom_effect_id(effect_id):
        return None
    node_group = _CUSTOM_GROUP_REFS.get(effect_id)
    if _custom_group_is_live(effect_id, node_group):
        return node_group
    _CUSTOM_GROUP_REFS.pop(effect_id, None)
    _CUSTOM_GROUP_SIGNATURES.pop(effect_id, None)

    cached_name = str(_CUSTOM_GROUP_NAMES.get(effect_id, "") or "")
    if cached_name:
        node_group = bpy.data.node_groups.get(cached_name)
        if _custom_group_is_live(effect_id, node_group):
            _CUSTOM_GROUP_REFS[effect_id] = node_group
            return node_group
        _CUSTOM_GROUP_NAMES.pop(effect_id, None)

    now = time.monotonic()
    last_miss = float(_CUSTOM_GROUP_MISS_CACHE.get(effect_id, 0.0) or 0.0)
    if now - last_miss < _CUSTOM_GROUP_MISS_SECONDS:
        return None
    for node_group in getattr(bpy.data, "node_groups", ()):
        try:
            if str(node_group.get(KEY_ID, "") or "") == effect_id:
                _CUSTOM_GROUP_NAMES[effect_id] = str(
                    getattr(node_group, "name_full", getattr(node_group, "name", "")) or ""
                )
                _CUSTOM_GROUP_REFS[effect_id] = node_group
                _CUSTOM_GROUP_SIGNATURES[effect_id] = _custom_definition_signature(node_group)
                _CUSTOM_GROUP_MISS_CACHE.pop(effect_id, None)
                return node_group
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    if len(_CUSTOM_GROUP_MISS_CACHE) >= 256 and effect_id not in _CUSTOM_GROUP_MISS_CACHE:
        for stale_id in tuple(_CUSTOM_GROUP_MISS_CACHE)[:64]:
            _CUSTOM_GROUP_MISS_CACHE.pop(stale_id, None)
    _CUSTOM_GROUP_MISS_CACHE[effect_id] = now
    return None




def refresh_one_custom_effect_definition(registry, effect_id, schema_version):
    """Refresh one group only when metadata or its interface changed."""
    effect_id = str(effect_id or "")
    if not is_custom_effect_id(effect_id):
        return registry.get(effect_id, {})
    node_group = find_custom_effect_group(effect_id)
    if node_group is None:
        _CUSTOM_DEFINITION_CACHE.pop(effect_id, None)
        return registry.get(effect_id, {})
    try:
        signature = _custom_definition_signature(node_group)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return registry.get(effect_id, {})
    cached = _CUSTOM_DEFINITION_CACHE.get(effect_id)
    if cached and cached[0] == signature:
        definition = cached[1]
        registry[effect_id] = definition
        return definition
    try:
        result = custom_effect_definition(node_group, schema_version)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return registry.get(effect_id, {})
    if not result or result[0] != effect_id:
        return registry.get(effect_id, {})
    definition = result[1]
    registry[effect_id] = definition
    _CUSTOM_DEFINITION_CACHE[effect_id] = (signature, definition)
    _CUSTOM_GROUP_REFS[effect_id] = node_group
    _CUSTOM_GROUP_SIGNATURES[effect_id] = signature
    _CUSTOM_GROUP_NAMES[effect_id] = str(
        getattr(node_group, "name_full", getattr(node_group, "name", "")) or ""
    )
    _CUSTOM_GROUP_MISS_CACHE.pop(effect_id, None)
    if len(_CUSTOM_DEFINITION_CACHE) > 256:
        for stale_id in tuple(_CUSTOM_DEFINITION_CACHE)[:64]:
            if stale_id != effect_id:
                _CUSTOM_DEFINITION_CACHE.pop(stale_id, None)
    return definition


def _candidate_node_groups():
    groups = []
    for node_group in getattr(bpy.data, "node_groups", ()):
        try:
            if getattr(node_group, "library", None) is not None:
                continue
            if bool(node_group.get("fbp_private_effect_group", False)):
                continue
            if bool(node_group.get("fbp_effect_asset_id", "")) and not is_custom_effect_id(node_group.get(KEY_ID, "")):
                continue
            if _group_kind(node_group) not in {"GEOMETRY", "SHADER"}:
                continue
            groups.append(node_group)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return sorted(groups, key=lambda item: (0 if _group_kind(item) == "SHADER" else 1, str(getattr(item, "name", "")).casefold()))


def _active_edit_tree(context):
    space = getattr(context, "space_data", None)
    for attr in ("edit_tree", "node_tree"):
        tree = getattr(space, attr, None) if space else None
        if not tree or _group_kind(tree) not in {"GEOMETRY", "SHADER"}:
            continue
        if getattr(tree, "library", None) is not None:
            continue
        name = str(getattr(tree, "name_full", getattr(tree, "name", "")) or "")
        if name and bpy.data.node_groups.get(name) is tree:
            return tree
    return None


def _selected_fbp_rigs(context):
    """Resolve selected Frame by Plane rigs without creating an import cycle."""
    try:
        from .layers import get_selected_rigs
        return [rig for rig in list(get_selected_rigs(context) or []) if rig]
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return []


def _custom_effect_plane(rig):
    if not rig:
        return None
    try:
        plane = getattr(rig, "fbp_plane_target", None)
        if plane and getattr(plane, "type", "") == "MESH":
            return plane
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _new_interface_socket(
    node_group,
    name,
    in_out,
    socket_type,
    *,
    default=None,
    minimum=None,
    maximum=None,
    hide_value=False,
):
    socket = node_group.interface.new_socket(
        name=name,
        in_out=in_out,
        socket_type=socket_type,
    )
    for attr, value in (
        ("default_value", default),
        ("min_value", minimum),
        ("max_value", maximum),
        ("hide_value", bool(hide_value)),
    ):
        if value is None:
            continue
        try:
            setattr(socket, attr, value)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return socket


def _group_node_socket(sockets, name):
    try:
        socket = sockets.get(name)
        if socket is not None:
            return socket
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        for socket in sockets:
            if str(getattr(socket, "name", "") or "") == name:
                return socket
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _link_group_passthrough(node_group, group_input, group_output, input_name, output_name=None):
    output_name = str(output_name or input_name)
    source = _group_node_socket(getattr(group_input, "outputs", ()), input_name)
    target = _group_node_socket(getattr(group_output, "inputs", ()), output_name)
    if source is None or target is None:
        return False
    try:
        node_group.links.new(source, target)
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def create_custom_effect_group(kind="SHADER"):
    """Create a valid no-op custom effect ready for authoring."""
    kind = "GEOMETRY" if str(kind or "").upper() == "GEOMETRY" else "SHADER"
    tree_type = "GeometryNodeTree" if kind == "GEOMETRY" else "ShaderNodeTree"
    base_name = (
        "FBP Custom Geometry Effect"
        if kind == "GEOMETRY"
        else "FBP Custom Shader Effect"
    )
    node_group = bpy.data.node_groups.new(base_name, tree_type)
    try:
        node_group.use_fake_user = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    if kind == "GEOMETRY":
        _new_interface_socket(
            node_group, "Geometry", "INPUT", "NodeSocketGeometry", hide_value=True
        )
        _new_interface_socket(
            node_group, "Geometry", "OUTPUT", "NodeSocketGeometry", hide_value=True
        )
    else:
        _new_interface_socket(
            node_group,
            "Color In",
            "INPUT",
            "NodeSocketColor",
            default=(1.0, 1.0, 1.0, 1.0),
        )
        _new_interface_socket(
            node_group,
            "Alpha In",
            "INPUT",
            "NodeSocketFloat",
            default=1.0,
            minimum=0.0,
            maximum=1.0,
        )
        _new_interface_socket(
            node_group,
            "UV Vector",
            "INPUT",
            "NodeSocketVector",
            default=(0.0, 0.0, 0.0),
        )
        _new_interface_socket(
            node_group,
            "Color Out",
            "OUTPUT",
            "NodeSocketColor",
            default=(1.0, 1.0, 1.0, 1.0),
        )
        _new_interface_socket(
            node_group,
            "Alpha Out",
            "OUTPUT",
            "NodeSocketFloat",
            default=1.0,
            minimum=0.0,
            maximum=1.0,
        )

    group_input = node_group.nodes.new("NodeGroupInput")
    group_input.name = "Group Input"
    group_input.label = "Effect Input"
    group_input.location = (-360.0, 0.0)
    group_output = node_group.nodes.new("NodeGroupOutput")
    group_output.name = "Group Output"
    group_output.label = "Effect Output"
    group_output.location = (360.0, 0.0)
    try:
        group_output.is_active_output = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    if kind == "GEOMETRY":
        _link_group_passthrough(
            node_group, group_input, group_output, "Geometry", "Geometry"
        )
    else:
        _link_group_passthrough(
            node_group, group_input, group_output, "Color In", "Color Out"
        )
        _link_group_passthrough(
            node_group, group_input, group_output, "Alpha In", "Alpha Out"
        )

    try:
        node_group.nodes.active = group_output
        group_output.select = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return node_group


def _select_custom_effect_plane(context, rig):
    plane = _custom_effect_plane(rig)
    if plane is None:
        return None
    try:
        for obj in tuple(getattr(context, "selected_objects", ()) or ()):
            if obj is not plane:
                obj.select_set(False)
        plane.select_set(True)
        context.view_layer.objects.active = plane
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return plane


def _node_editor_area(context):
    area = getattr(context, "area", None)
    if area is not None and getattr(area, "type", "") == "NODE_EDITOR":
        return area
    screen = getattr(context, "screen", None)
    for candidate in tuple(getattr(screen, "areas", ()) or ()):
        if getattr(candidate, "type", "") == "NODE_EDITOR":
            return candidate
    if area is not None and getattr(area, "type", "") in {
        "VIEW_3D",
        "PROPERTIES",
    }:
        try:
            area.type = "NODE_EDITOR"
            return area
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return None


def _open_custom_effect_nodes(context, rig, effect_id, node_group):
    """Open the source group when a usable UI area is available."""
    plane = _select_custom_effect_plane(context, rig)
    if plane is None:
        return False
    area = _node_editor_area(context)
    if area is None:
        return False
    try:
        space = area.spaces.active
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    kind = _group_kind(node_group)
    try:
        area.ui_type = "GeometryNodeTree" if kind == "GEOMETRY" else "ShaderNodeTree"
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        space.tree_type = "GeometryNodeTree" if kind == "GEOMETRY" else "ShaderNodeTree"
        space.pin = False
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    if kind == "GEOMETRY":
        try:
            space.geometry_nodes_type = "MODIFIER"
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    try:
        area.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    try:
        from . import geometry_nodes as _geometry_nodes
    except (ImportError, AttributeError):
        return True

    if kind == "GEOMETRY":
        modifier = _geometry_nodes.fbp_find_effect_modifier(rig, effect_id)
        if modifier is not None:
            try:
                plane.modifiers.active = modifier
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            try:
                region = next(
                    region for region in area.regions
                    if getattr(region, "type", "") == "WINDOW"
                )
                with context.temp_override(
                    area=area,
                    region=region,
                    active_object=plane,
                    object=plane,
                ):
                    operator = getattr(bpy.ops.object, "modifier_set_active", None)
                    if callable(operator):
                        operator(modifier=modifier.name)
            except (StopIteration, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        return True

    try:
        space.shader_type = "OBJECT"
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    target_node = None
    target_tree = None
    target_index = -1
    try:
        materials = getattr(getattr(plane, "data", None), "materials", ())
        for index, material in enumerate(materials):
            tree = getattr(material, "node_tree", None) if material else None
            if tree is None:
                continue
            for node in tree.nodes:
                if getattr(node, "node_tree", None) is node_group:
                    target_node = node
                    target_tree = tree
                    target_index = index
                    break
            if target_node is not None:
                break
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        target_node = None
    if target_node is None or target_tree is None:
        return True
    try:
        plane.active_material_index = max(0, target_index)
        for node in target_tree.nodes:
            node.select = False
        target_node.select = True
        target_tree.nodes.active = target_node
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return True
    try:
        region = next(
            region for region in area.regions
            if getattr(region, "type", "") == "WINDOW"
        )
        with context.temp_override(
            area=area,
            region=region,
            active_object=plane,
            object=plane,
        ):
            bpy.ops.node.group_edit(exit=False)
    except (StopIteration, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return True


class FBP_OT_CreateCustomNodeEffect(Operator):
    bl_idname = "fbp.create_custom_node_effect"
    bl_label = "New Custom Effect"
    bl_description = "Create, register and apply a ready-to-edit custom node effect"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(
        name="Type",
        items=(
            ("AUTO", "Automatic", "Use the current 2D or 3D Effects view"),
            ("SHADER", "Shader", "Create a Color, Alpha and UV shader effect"),
            ("GEOMETRY", "Geometry Nodes", "Create a Geometry pass-through effect"),
        ),
        default="AUTO",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return bool(_selected_fbp_rigs(context))

    def execute(self, context):
        rigs = _selected_fbp_rigs(context)
        if not rigs:
            self.report({"WARNING"}, "Select a Frame by Plane layer first")
            return {"CANCELLED"}
        kind = str(self.kind or "AUTO").upper()
        if kind == "AUTO":
            view = str(
                getattr(getattr(context, "scene", None), "fbp_effects_view", "2D")
                or "2D"
            )
            kind = "GEOMETRY" if view == "3D" else "SHADER"
        node_group = None
        try:
            node_group = create_custom_effect_group(kind)
            label = str(getattr(node_group, "name", "Custom Effect") or "Custom Effect")
            effect_id = tag_custom_effect_group(
                node_group,
                label,
                "MODIFIER" if kind == "GEOMETRY" else "NODETREE",
                "User-defined Geometry Nodes effect"
                if kind == "GEOMETRY"
                else "User-defined Shader effect",
            )
            request_custom_effect_registry_refresh(force=True)
        except (ValueError, AttributeError, ReferenceError, RuntimeError, TypeError) as exc:
            if node_group is not None:
                try:
                    if getattr(node_group, "users", 0) == 0:
                        bpy.data.node_groups.remove(node_group)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
            fbp_warn("Could not create custom node effect", exc)
            self.report({"ERROR"}, str(exc) or "Could not create the custom effect")
            return {"CANCELLED"}

        changed = 0
        try:
            from . import geometry_nodes as _geometry_nodes
            compatible = [
                rig
                for rig in rigs
                if _geometry_nodes.fbp_effect_supported_for_rig(rig, effect_id)
            ]
            changed = sum(
                1
                for rig in compatible
                if _geometry_nodes.fbp_add_effect(rig, effect_id)
            )
            for rig in compatible:
                while _geometry_nodes.fbp_can_move_effect(rig, effect_id, "UP"):
                    if not _geometry_nodes.fbp_move_effect(rig, effect_id, "UP"):
                        break
            if changed:
                _geometry_nodes.fbp_sync_effect_items(rigs[0], rigs)
                for index, item in enumerate(getattr(rigs[0], "fbp_effects", ())):
                    if str(getattr(item, "effect_id", "") or "") == effect_id:
                        rigs[0].fbp_effects_index = index
                        break
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Custom effect was created but could not be applied", exc)

        try:
            context.scene.fbp_effects_view = "3D" if kind == "GEOMETRY" else "2D"
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        _open_custom_effect_nodes(context, rigs[0], effect_id, node_group)
        if changed:
            self.report({"INFO"}, f"Created and applied {node_group.name}")
        else:
            self.report(
                {"WARNING"},
                f"Created {node_group.name}; it could not be applied to the selected layer",
            )
        return {"FINISHED"}


class FBP_OT_EditCustomNodeEffectNodes(Operator):
    bl_idname = "fbp.edit_custom_node_effect_nodes"
    bl_label = "Edit Custom Effect Nodes"
    bl_description = "Select the linked plane and open this custom effect node group"
    bl_options = {"INTERNAL"}

    effect_id: StringProperty(default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_selected_fbp_rigs(context))

    def execute(self, context):
        rigs = _selected_fbp_rigs(context)
        node_group = find_custom_effect_group(self.effect_id)
        if not rigs or node_group is None:
            self.report(
                {"WARNING"},
                "Custom effect or Frame by Plane layer is unavailable",
            )
            return {"CANCELLED"}
        if not _open_custom_effect_nodes(context, rigs[0], self.effect_id, node_group):
            self.report(
                {"WARNING"},
                "Could not open a Node Editor in the current workspace",
            )
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_RegisterCustomNodeEffect(Operator):
    bl_idname = "fbp.register_custom_node_effect"
    bl_label = "Register Custom Node Effect"
    bl_description = "Register a local Shader or Geometry node group as a reusable Frame by Plane effect"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    node_group: StringProperty(
        name="Node Group",
        description="Local Shader or Geometry node group to expose as an effect",
        default="",
        options={"SKIP_SAVE"},
    )
    effect_name: StringProperty(
        name="Effect Name",
        description="Name displayed in the Frame by Plane Effects panel",
        default="Custom Effect",
    )
    effect_icon: EnumProperty(
        name="Icon",
        description="Icon displayed in the effect menu and stack",
        items=CUSTOM_EFFECT_ICON_ITEMS,
        default="NODETREE",
    )
    description: StringProperty(
        name="Description",
        description="Short tooltip description",
        default="User-defined node-group effect",
    )

    @classmethod
    def poll(cls, _context):
        return bool(_candidate_node_groups())

    def invoke(self, context, _event):
        node_group = find_custom_effect_group(self.effect_id) if self.effect_id else _active_edit_tree(context)
        if node_group is None:
            candidates = _candidate_node_groups()
            node_group = candidates[0] if candidates else None
        if node_group is None:
            self.report({"WARNING"}, "Create a local Shader or Geometry node group first")
            return {"CANCELLED"}
        self.node_group = str(getattr(node_group, "name_full", getattr(node_group, "name", "")) or "")
        self.effect_name = str(node_group.get(KEY_LABEL, getattr(node_group, "name", "Custom Effect")) or "Custom Effect")
        self.effect_icon = _valid_effect_icon(
            node_group.get(KEY_ICON, ""), _group_kind(node_group)
        )
        self.description = str(node_group.get(KEY_DESCRIPTION, "User-defined node-group effect") or "")
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, _context):
        layout = self.layout
        group_row = layout.row()
        group_row.enabled = not bool(self.effect_id)
        group_row.prop_search(self, "node_group", bpy.data, "node_groups", text="Node Group")
        layout.prop(self, "effect_name")
        layout.prop(self, "effect_icon")
        layout.prop(self, "description")
        selected = bpy.data.node_groups.get(self.node_group)
        if selected:
            valid, message, contract = validate_custom_effect_group(selected)
            info = layout.box()
            info.label(
                text=("Geometry Nodes effect" if contract.get("kind") == "GEOMETRY" else "Shader color effect") if valid else "Invalid node contract",
                icon="CHECKMARK" if valid else "ERROR",
            )
            if message:
                info.label(text=message)
            elif contract.get("kind") == "SHADER":
                info.label(text=f"Color: {contract.get('color_input')} → {contract.get('color_output')}")
                if contract.get("alpha_input"):
                    info.label(text=f"Alpha: {contract.get('alpha_input')} → {contract.get('alpha_output')}")
                if contract.get("uv_input"):
                    info.label(text=f"UV: {contract.get('uv_input')}")
            asset_hint = layout.box()
            asset_hint.label(text="Optional: mark this node group as an Asset for reuse in other files", icon="ASSET_MANAGER")

    def execute(self, _context):
        node_group = bpy.data.node_groups.get(self.node_group)
        if self.effect_id:
            registered_group = find_custom_effect_group(self.effect_id)
            if registered_group is None:
                self.report({"ERROR"}, "Registered node group no longer exists")
                return {"CANCELLED"}
            node_group = registered_group
        if node_group is None:
            self.report({"ERROR"}, "Node group no longer exists")
            return {"CANCELLED"}
        try:
            effect_id = tag_custom_effect_group(
                node_group,
                self.effect_name.strip() or str(getattr(node_group, "name", "Custom Effect")),
                self.effect_icon,
                self.description.strip(),
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except (AttributeError, ReferenceError, RuntimeError, TypeError) as exc:
            fbp_warn("Could not register custom node effect", exc)
            self.report({"ERROR"}, "Could not register the node group")
            return {"CANCELLED"}
        request_custom_effect_registry_refresh(force=True)
        self.report({"INFO"}, f"Registered {self.effect_name.strip() or node_group.name}")
        self.effect_id = effect_id
        return {"FINISHED"}


class FBP_OT_HideCustomNodeEffect(Operator):
    bl_idname = "fbp.hide_custom_node_effect"
    bl_label = "Hide Custom Effect from Library"
    bl_description = "Hide this custom effect from the Add Effect menu without breaking layers that already use it"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(default="", options={"SKIP_SAVE"})

    def execute(self, _context):
        node_group = find_custom_effect_group(self.effect_id)
        if node_group is None:
            return {"CANCELLED"}
        try:
            node_group[KEY_HIDDEN] = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not hide custom effect", exc)
            return {"CANCELLED"}
        request_custom_effect_registry_refresh(force=True)
        self.report({"INFO"}, "Custom effect hidden from the library")
        return {"FINISHED"}


classes = (
    FBP_OT_CreateCustomNodeEffect,
    FBP_OT_EditCustomNodeEffectNodes,
    FBP_OT_RegisterCustomNodeEffect,
    FBP_OT_HideCustomNodeEffect,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    global _CUSTOM_REFRESH_TIME, _CUSTOM_REGISTRY_REFRESH_CALLBACK, _CUSTOM_GROUP_COUNT
    _CUSTOM_REFRESH_TIME = 0.0
    _CUSTOM_GROUP_COUNT = -1
    _CUSTOM_REGISTRY_REFRESH_CALLBACK = None
    _CUSTOM_EFFECT_IDS.clear()
    _CUSTOM_GROUP_NAMES.clear()
    _CUSTOM_GROUP_REFS.clear()
    _CUSTOM_GROUP_SIGNATURES.clear()
    _CUSTOM_GROUP_MISS_CACHE.clear()
    _CUSTOM_DEFINITION_CACHE.clear()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
