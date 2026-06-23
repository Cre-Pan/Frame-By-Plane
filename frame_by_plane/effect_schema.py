"""Shared effect-definition, instance and group foundations for Frame By Plane.

The current stack still exposes one logical instance per effect type.  This
module adds persistent instance identities and normalized metadata now, so the
future multi-instance stack can be introduced without changing every builder,
modifier and shader-node contract again.
"""

from .runtime import FBP_DATA_ERRORS, fbp_unique_token_hex
FBP_EFFECT_SCHEMA_VERSION = 17
FBP_EFFECT_INSTANCE_VERSION = 1
FBP_EFFECT_INSTANCE_KEY = "fbp_effect_instance_id"
FBP_EFFECT_INSTANCE_VERSION_KEY = "fbp_effect_instance_version"
FBP_EFFECT_INSTANCE_OWNER_KEY = "fbp_effect_instance_owner"

FBP_EFFECT_GROUP_VERSION = 1
FBP_EFFECT_GROUP_KEY = "fbp_effect_group_id"
FBP_EFFECT_GROUP_VERSION_KEY = "fbp_effect_group_version"

# Common capabilities exposed by the current effect registry. Definitions
# are finalized once at module import and validated before any effect is built.
FBP_EFFECT_CAPABILITIES = {
    "SOURCE_COLOR",
    "SOURCE_ALPHA",
    "SOURCE_IMAGE",
    "PREVIOUS_EFFECTS",
    "FINAL_MATERIAL",
    "CAMERA_INFO",
    "TIME",
    "SEED",
    "VIEWPORT_QUALITY",
    "PLAYBACK_QUALITY",
    "RENDER_QUALITY",
    "ALPHA_GEOMETRY",
    "CAMERA_SPACE_VECTORS",
    "MASK_SOURCE",
}


def _compile_capabilities(definition, kind):
    """Compile capabilities from explicit current-registry contracts."""
    capabilities = set(definition.get("capabilities", ()) or ())
    if kind == "SHADER":
        capabilities.add("SOURCE_COLOR")
    if definition.get("image_aware"):
        capabilities.update(("SOURCE_IMAGE", "SOURCE_ALPHA"))
    elif definition.get("alpha_aware"):
        capabilities.add("SOURCE_ALPHA")
    if definition.get("supports_input_source"):
        capabilities.update(("PREVIOUS_EFFECTS", "FINAL_MATERIAL"))
    if definition.get("supports_seed"):
        capabilities.add("SEED")
    if definition.get("mask_source_aware"):
        capabilities.update(("SOURCE_IMAGE", "SOURCE_ALPHA", "MASK_SOURCE"))
    if definition.get("evolve_property"):
        capabilities.add("TIME")
    if definition.get("camera_aware"):
        capabilities.add("CAMERA_INFO")
        camera_contract = definition.get("camera_contract", {}) or {}
        if camera_contract.get("space_vectors"):
            capabilities.add("CAMERA_SPACE_VECTORS")
    if kind == "GEOMETRY" and definition.get("alpha_aware"):
        capabilities.add("ALPHA_GEOMETRY")

    quality_contracts = tuple(definition.get("quality_contracts", ()) or ())
    quality_profile = str(definition.get("quality_profile", "NONE") or "NONE").upper()
    if quality_contracts and quality_profile == "NONE":
        quality_profile = "GENERIC"
        definition["quality_profile"] = quality_profile
    if quality_profile != "NONE":
        capabilities.update(("VIEWPORT_QUALITY", "PLAYBACK_QUALITY", "RENDER_QUALITY"))
    return tuple(sorted(capabilities))


def finalize_effect_registry(registry):
    """Finalize the current registry; no project-version migration is performed."""
    for effect_id, definition in registry.items():
        kind = str(definition.get("kind", "") or "").upper()
        definition.setdefault("schema_version", FBP_EFFECT_SCHEMA_VERSION)
        definition.setdefault("instance_policy", "SINGLE")
        definition.setdefault("supports_future_instances", kind in {"SHADER", "GEOMETRY"})
        definition.setdefault("quality_profile", "NONE")
        definition.setdefault("camera_aware", False)
        # Keep UI stack categories canonical. Older built-ins and third-party
        # definitions sometimes used human-facing labels such as ``Masks`` or
        # ``Mesh``; the Effects UI filters stable identifiers instead.
        raw_category = str(definition.get("category", "") or "").strip().upper()
        category_aliases = {
            "": "BASE" if kind == "BASE" else ("3D" if kind == "GEOMETRY" else "2D"),
            "IMAGE": "2D",
            "IMAGES": "2D",
            "MASKS": "MASK",
            "MESH": "3D",
            "GEOMETRY": "3D",
        }
        definition["category"] = category_aliases.get(raw_category, raw_category)
        if definition.get("camera_aware") and kind == "GEOMETRY":
            definition.setdefault("camera_contract", {"object_socket": "Camera"})
        else:
            # Shader effects such as Depth Blur can consume camera information
            # through runtime-managed scalar sockets and do not require a Camera
            # object socket in their node-group interface.
            definition.setdefault("camera_contract", {})
        if kind == "GEOMETRY" and definition.get("alpha_aware"):
            definition.setdefault("alpha_geometry_contract", {
                "image_node_tag": "fbp_alpha_image_node",
                "threshold_socket": "Alpha Threshold",
                "quality_socket": "Alpha Resolution",
            })
        else:
            definition.setdefault("alpha_geometry_contract", {})
        definition["capabilities"] = _compile_capabilities(definition, kind)
        definition.setdefault("effect_id", str(effect_id))
    return registry


def validate_effect_registry(registry):
    """Return deterministic, human-readable registry issues."""
    issues = []
    valid_kinds = {"BASE", "SHADER", "GEOMETRY"}
    for effect_id, definition in registry.items():
        prefix = str(effect_id or "<empty>")
        kind = str(definition.get("kind", "") or "").upper()
        if not prefix or prefix == "<empty>":
            issues.append("Effect registry contains an empty id")
        if kind not in valid_kinds:
            issues.append(f"{prefix}: unsupported kind '{kind}'")
        category = str(definition.get("category", "") or "").upper()
        if category not in {"BASE", "2D", "MASK", "3D"}:
            issues.append(f"{prefix}: unsupported category '{category}'")
        if int(definition.get("schema_version", 0) or 0) != FBP_EFFECT_SCHEMA_VERSION:
            issues.append(f"{prefix}: stale effect schema version")
        if not str(definition.get("label", "") or "").strip():
            issues.append(f"{prefix}: missing label")
        if kind in {"SHADER", "GEOMETRY"} and not str(definition.get("asset_id", "") or "").strip():
            issues.append(f"{prefix}: missing asset_id")
        unknown = set(definition.get("capabilities", ())) - FBP_EFFECT_CAPABILITIES
        if unknown:
            issues.append(f"{prefix}: unknown capabilities {', '.join(sorted(unknown))}")
        camera_contract = definition.get("camera_contract", {}) or {}
        if definition.get("camera_aware"):
            if kind not in {"SHADER", "GEOMETRY"}:
                issues.append(f"{prefix}: camera-aware effects require a shader or Geometry Nodes effect")
            if not isinstance(camera_contract, dict):
                issues.append(f"{prefix}: camera contract is not a mapping")
            elif kind == "GEOMETRY":
                if not str(camera_contract.get("object_socket", "") or "").strip():
                    issues.append(f"{prefix}: camera contract missing object_socket")
                else:
                    for socket_key in (
                        "object_socket", "lens_socket", "sensor_width_socket",
                        "ortho_scale_socket", "perspective_socket",
                        "shift_x_socket", "shift_y_socket",
                    ):
                        if socket_key in camera_contract and not str(camera_contract.get(socket_key, "") or "").strip():
                            issues.append(f"{prefix}: camera contract has an empty {socket_key}")
        alpha_contract = definition.get("alpha_geometry_contract", {}) or {}
        if kind == "GEOMETRY" and definition.get("alpha_aware"):
            if not isinstance(alpha_contract, dict):
                issues.append(f"{prefix}: alpha geometry contract is not a mapping")
            else:
                for key in ("image_node_tag", "threshold_socket", "quality_socket"):
                    if not str(alpha_contract.get(key, "") or "").strip():
                        issues.append(f"{prefix}: alpha geometry contract missing {key}")
        property_map = definition.get("property_map", {}) or {}
        extra_properties = tuple(definition.get("extra_properties", ()) or ())
        if not isinstance(property_map, dict):
            issues.append(f"{prefix}: property_map is not a mapping")
            property_map = {}
        if any(not str(name or "").strip() for name in extra_properties):
            issues.append(f"{prefix}: extra_properties contains an empty name")
        known_properties = set(property_map) | {str(name) for name in extra_properties if name}
        evolve_property = str(definition.get("evolve_property", "") or "")
        if evolve_property and evolve_property not in known_properties:
            issues.append(f"{prefix}: evolve_property is not registered")

        required_inputs = tuple(definition.get("required_input_sockets", ()) or ())
        if any(not str(socket or "").strip() for socket in required_inputs):
            issues.append(f"{prefix}: required_input_sockets contains an empty name")
        contracts = tuple(definition.get("quality_contracts", ()) or ())
        if contracts and str(definition.get("quality_profile", "NONE") or "NONE").upper() == "NONE":
            issues.append(f"{prefix}: quality contracts require a quality_profile")
        for index, contract in enumerate(contracts):
            contract_prefix = f"{prefix}: quality contract {index + 1}"
            if not isinstance(contract, dict):
                issues.append(f"{contract_prefix} is not a mapping")
                continue
            for key in ("socket", "viewport_property", "playback_property", "render_property"):
                if not str(contract.get(key, "") or "").strip():
                    issues.append(f"{contract_prefix} missing {key}")
            for property_key in ("viewport_property", "playback_property", "render_property"):
                property_name = str(contract.get(property_key, "") or "")
                if property_name and property_name not in known_properties:
                    issues.append(f"{contract_prefix} {property_key} is not registered")
            viewport_property = str(contract.get("viewport_property", "") or "")
            if viewport_property and viewport_property not in property_map:
                issues.append(f"{contract_prefix} viewport property is not mapped to a socket")
    return tuple(issues)


def new_effect_instance_id(effect_id):
    """Create a compact persistent identity for a concrete effect owner."""
    token = fbp_unique_token_hex()
    prefix = str(effect_id or "effect").strip().lower().replace(" ", "_")
    return f"{prefix}:{token}"


def assign_effect_instance_id(owner, effect_id, instance_id="", owner_token=""):
    """Assign one persistent logical identity to a concrete effect owner.

    ``owner_token`` identifies the Frame by Plane stack that owns the modifier
    or shader node.  It lets duplicated Blender datablocks self-heal copied
    instance IDs without a project-wide scan.
    """
    if owner is None:
        return ""
    current = str(instance_id or new_effect_instance_id(effect_id))
    try:
        owner[FBP_EFFECT_INSTANCE_KEY] = current
        owner[FBP_EFFECT_INSTANCE_VERSION_KEY] = FBP_EFFECT_INSTANCE_VERSION
        if owner_token:
            owner[FBP_EFFECT_INSTANCE_OWNER_KEY] = str(owner_token)
    except FBP_DATA_ERRORS:
        return ""
    return current


def ensure_effect_instance_id(owner, effect_id, owner_token=""):
    """Tag a modifier or shader node with a stable future-ready instance id."""
    if owner is None:
        return ""
    try:
        current = str(owner.get(FBP_EFFECT_INSTANCE_KEY, "") or "")
        stored_owner = str(owner.get(FBP_EFFECT_INSTANCE_OWNER_KEY, "") or "")
    except FBP_DATA_ERRORS:
        return ""
    if not current or (owner_token and stored_owner and stored_owner != str(owner_token)):
        current = new_effect_instance_id(effect_id)
    return assign_effect_instance_id(owner, effect_id, current, owner_token)


def effect_instance_id(owner):
    if owner is None:
        return ""
    try:
        return str(owner.get(FBP_EFFECT_INSTANCE_KEY, "") or "")
    except FBP_DATA_ERRORS:
        return ""


def new_effect_group_id():
    """Create a persistent identity shared by grouped effect owners."""
    return f"group:{fbp_unique_token_hex()}"


def assign_effect_group_id(owner, group_id):
    """Assign or clear organizational group metadata on an effect owner."""
    if owner is None:
        return False
    group_id = str(group_id or "")
    try:
        current = str(owner.get(FBP_EFFECT_GROUP_KEY, "") or "")
        version = int(owner.get(FBP_EFFECT_GROUP_VERSION_KEY, 0) or 0)
        if not group_id:
            changed = False
            if FBP_EFFECT_GROUP_KEY in owner:
                del owner[FBP_EFFECT_GROUP_KEY]
                changed = True
            if FBP_EFFECT_GROUP_VERSION_KEY in owner:
                del owner[FBP_EFFECT_GROUP_VERSION_KEY]
                changed = True
            return changed
        if current == group_id and version == FBP_EFFECT_GROUP_VERSION:
            return False
        owner[FBP_EFFECT_GROUP_KEY] = group_id
        owner[FBP_EFFECT_GROUP_VERSION_KEY] = FBP_EFFECT_GROUP_VERSION
        return True
    except FBP_DATA_ERRORS:
        return False


def effect_group_id(owner):
    """Return the persistent organizational group identity of an effect owner."""
    if owner is None:
        return ""
    try:
        return str(owner.get(FBP_EFFECT_GROUP_KEY, "") or "")
    except FBP_DATA_ERRORS:
        return ""
