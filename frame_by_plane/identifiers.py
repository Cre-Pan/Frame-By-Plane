"""Persistent logical identities for Frame By Plane production data.

Names are presentation data and may change.  These compact IDs are saved on
Blender datablocks so future source refresh, GP masks, camera controllers,
motion links and package assets can keep relationships stable across rename,
reorder, duplication, Undo/Redo and save/reopen.
"""

from __future__ import annotations

from .runtime import FBP_DATA_ERRORS, fbp_unique_token_hex


FBP_IDENTITY_SCHEMA_VERSION = 1
FBP_IDENTITY_SCHEMA_KEY = "fbp_identity_schema"

FBP_LAYER_ID_KEY = "fbp_layer_id"
FBP_SOURCE_ID_KEY = "fbp_source_id"
FBP_MASK_ID_KEY = "fbp_mask_id"
FBP_CONTROLLER_ID_KEY = "fbp_controller_id"
FBP_PACKAGE_ASSET_ID_KEY = "fbp_package_asset_id"

FBP_ID_KINDS = {
    "LAYER": (FBP_LAYER_ID_KEY, "layer"),
    "SOURCE": (FBP_SOURCE_ID_KEY, "source"),
    "MASK": (FBP_MASK_ID_KEY, "mask"),
    "CONTROLLER": (FBP_CONTROLLER_ID_KEY, "controller"),
    "PACKAGE_ASSET": (FBP_PACKAGE_ASSET_ID_KEY, "asset"),
}


def new_stable_id(kind):
    kind = str(kind or "").strip().upper()
    if kind not in FBP_ID_KINDS:
        raise ValueError(f"Unsupported Frame By Plane identity kind: {kind}")
    return f"{FBP_ID_KINDS[kind][1]}:{fbp_unique_token_hex()}"


def stable_id(owner, kind):
    if owner is None:
        return ""
    kind = str(kind or "").strip().upper()
    spec = FBP_ID_KINDS.get(kind)
    if spec is None:
        return ""
    try:
        return str(owner.get(spec[0], "") or "")
    except FBP_DATA_ERRORS:
        return ""


def assign_stable_id(owner, kind, value=""):
    if owner is None:
        return ""
    kind = str(kind or "").strip().upper()
    spec = FBP_ID_KINDS.get(kind)
    if spec is None:
        raise ValueError(f"Unsupported Frame By Plane identity kind: {kind}")
    value = str(value or "") or new_stable_id(kind)
    try:
        owner[spec[0]] = value
        owner[FBP_IDENTITY_SCHEMA_KEY] = FBP_IDENTITY_SCHEMA_VERSION
    except FBP_DATA_ERRORS:
        return ""
    return value


def ensure_stable_id(owner, kind, *, preferred=""):
    current = stable_id(owner, kind)
    if current:
        try:
            if int(owner.get(FBP_IDENTITY_SCHEMA_KEY, 0) or 0) != FBP_IDENTITY_SCHEMA_VERSION:
                owner[FBP_IDENTITY_SCHEMA_KEY] = FBP_IDENTITY_SCHEMA_VERSION
        except FBP_DATA_ERRORS:
            pass
        return current
    return assign_stable_id(owner, kind, preferred)


def ensure_layer_identity(rig):
    """Ensure one logical layer ID shared by the rig and its generated plane."""
    if rig is None:
        return ""
    layer_id = ensure_stable_id(rig, "LAYER")
    ensure_stable_id(rig, "SOURCE")
    try:
        plane = getattr(rig, "fbp_plane_target", None)
    except FBP_DATA_ERRORS:
        plane = None
    if plane is not None and layer_id:
        assign_stable_id(plane, "LAYER", layer_id)
    return layer_id


def ensure_controller_identity(controller):
    return ensure_stable_id(controller, "CONTROLLER")


def ensure_mask_identity(mask):
    return ensure_stable_id(mask, "MASK")


def ensure_package_asset_identity(asset, *, preferred=""):
    return ensure_stable_id(asset, "PACKAGE_ASSET", preferred=preferred)


def repair_scene_identities(scene, *, repair_duplicates=True, create_missing=True):
    """Add missing identities and optionally repair duplicated current layer IDs."""
    stats = {
        "layers_checked": 0,
        "layer_ids_created": 0,
        "source_ids_created": 0,
        "duplicate_layer_ids": 0,
        "duplicate_layer_ids_repaired": 0,
        "mask_ids_created": 0,
        "controller_ids_created": 0,
        "package_asset_ids_created": 0,
    }
    issues = []
    warnings = []
    if scene is None:
        return {"stats": stats, "issues": ("No active Scene for identity repair",), "warnings": ()}

    try:
        from .layers import iter_scene_fbp_rigs
        rigs = tuple(iter_scene_fbp_rigs(scene, fallback=True))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        rigs = ()

    seen_layers = {}
    for rig in rigs:
        stats["layers_checked"] += 1
        before_layer = stable_id(rig, "LAYER")
        before_source = stable_id(rig, "SOURCE")
        if create_missing:
            layer_id = ensure_layer_identity(rig)
            if layer_id and not before_layer:
                stats["layer_ids_created"] += 1
            if stable_id(rig, "SOURCE") and not before_source:
                stats["source_ids_created"] += 1
        else:
            layer_id = before_layer
            if not before_source:
                warnings.append(f"{getattr(rig, 'name', '<layer>')}: no stable source ID")
        if not layer_id:
            message = f"{getattr(rig, 'name', '<layer>')}: no stable layer ID"
            if create_missing:
                issues.append(message.replace("no stable", "could not assign a stable"))
            else:
                warnings.append(message)
            continue
        previous = seen_layers.get(layer_id)
        if previous is not None and previous is not rig:
            stats["duplicate_layer_ids"] += 1
            if repair_duplicates:
                replacement = assign_stable_id(rig, "LAYER", new_stable_id("LAYER"))
                try:
                    plane = getattr(rig, "fbp_plane_target", None)
                except FBP_DATA_ERRORS:
                    plane = None
                if plane is not None:
                    assign_stable_id(plane, "LAYER", replacement)
                layer_id = replacement
                stats["duplicate_layer_ids_repaired"] += 1
            else:
                warnings.append(
                    f"{getattr(rig, 'name', '<layer>')}: duplicates the stable ID of {getattr(previous, 'name', '<layer>')}"
                )
        seen_layers[layer_id] = rig

    try:
        from .object_masks import is_object_mask_helper
    except (ImportError, AttributeError):
        is_object_mask_helper = lambda _obj: False
    try:
        from .effect_controls import is_effect_control
    except (ImportError, AttributeError):
        is_effect_control = lambda _obj: False

    try:
        objects = tuple(scene.objects)
    except FBP_DATA_ERRORS:
        objects = ()
    for obj in objects:
        if is_object_mask_helper(obj):
            before = stable_id(obj, "MASK")
            if create_missing:
                if ensure_mask_identity(obj) and not before:
                    stats["mask_ids_created"] += 1
            elif not before:
                warnings.append(f"{getattr(obj, 'name', '<mask>')}: no stable mask ID")
        if is_effect_control(obj):
            before = stable_id(obj, "CONTROLLER")
            if create_missing:
                if ensure_controller_identity(obj) and not before:
                    stats["controller_ids_created"] += 1
            elif not before:
                warnings.append(f"{getattr(obj, 'name', '<control>')}: no stable controller ID")
        try:
            if str(getattr(obj, "type", "") or "") == "LATTICE" and str(obj.get("fbp_lattice_effect", "") or ""):
                before = stable_id(obj, "CONTROLLER")
                if create_missing:
                    if ensure_controller_identity(obj) and not before:
                        stats["controller_ids_created"] += 1
                elif not before:
                    warnings.append(f"{getattr(obj, 'name', '<lattice>')}: no stable controller ID")
        except FBP_DATA_ERRORS:
            pass

    # Existing built-in and custom effect assets already have a stable asset ID.
    # Mirror it into the common package-asset contract without changing names.
    try:
        import bpy
        node_groups = tuple(bpy.data.node_groups)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        node_groups = ()
    for group in node_groups:
        try:
            asset_id = str(group.get("fbp_effect_asset_id", "") or "")
        except FBP_DATA_ERRORS:
            asset_id = ""
        if not asset_id:
            continue
        before = stable_id(group, "PACKAGE_ASSET")
        if create_missing:
            if ensure_package_asset_identity(group, preferred=asset_id) and not before:
                stats["package_asset_ids_created"] += 1
        # ``fbp_effect_asset_id`` remains the canonical generated-asset ID.
        # The package contract mirrors that value so project health and export
        # share one stable identity without changing the generated asset.

    return {
        "stats": stats,
        "issues": tuple(dict.fromkeys(issues)),
        "warnings": tuple(dict.fromkeys(warnings)),
    }



__all__ = (
    "FBP_IDENTITY_SCHEMA_VERSION",
    "FBP_LAYER_ID_KEY",
    "FBP_SOURCE_ID_KEY",
    "FBP_MASK_ID_KEY",
    "FBP_CONTROLLER_ID_KEY",
    "FBP_PACKAGE_ASSET_ID_KEY",
    "new_stable_id",
    "stable_id",
    "assign_stable_id",
    "ensure_stable_id",
    "ensure_layer_identity",
    "ensure_controller_identity",
    "ensure_mask_identity",
    "ensure_package_asset_identity",
    "repair_scene_identities",
)
