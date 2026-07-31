"""Explicit ownership contract for generated Frame By Plane datablocks.

Cleanup code must be able to distinguish add-on generated helpers from objects
created by the artist.  These tags are additive and never imply permission to
remove a datablock unless the expected owner also matches.
"""

from __future__ import annotations

import importlib

from .constants import FBP_VERSION_STRING
from .runtime import FBP_DATA_ERRORS
from .identifiers import ensure_layer_identity, ensure_controller_identity, ensure_mask_identity


FBP_OWNERSHIP_SCHEMA_VERSION = 1
KEY_MANAGED = "fbp_managed"
KEY_OWNER_ID = "fbp_owner_id"
KEY_ROLE = "fbp_owner_role"
KEY_SCHEMA = "fbp_owner_schema"
KEY_CREATED_VERSION = "fbp_created_version"
KEY_USER_AUTHORED = "fbp_user_authored"

VALID_ROLES = {
    "LAYER_RIG",
    "LAYER_PLANE",
    "EFFECT_CONTROL",
    "MASK_HELPER",
    "GREASE_PENCIL_CANVAS",
    "GREASE_PENCIL_MASK",
    "LATTICE_HELPER",
    "CAMERA_CONTROLLER",
    "MOTION_CONTROLLER",
    "PROJECTOR",
    "PROJECTOR_LIGHT",
    "COMPOSITOR_GROUP",
    "PACKAGE_ASSET",
}


def tag_managed(owner, role, *, owner_id="", user_authored=False):
    if owner is None:
        return False
    role = str(role or "").strip().upper()
    if role not in VALID_ROLES:
        raise ValueError(f"Unsupported Frame By Plane ownership role: {role}")
    changed = False
    values = {
        KEY_MANAGED: True,
        KEY_OWNER_ID: str(owner_id or ""),
        KEY_ROLE: role,
        KEY_SCHEMA: FBP_OWNERSHIP_SCHEMA_VERSION,
        KEY_CREATED_VERSION: FBP_VERSION_STRING,
        KEY_USER_AUTHORED: bool(user_authored),
    }
    try:
        for key, value in values.items():
            if owner.get(key) != value:
                owner[key] = value
                changed = True
    except FBP_DATA_ERRORS:
        return False
    return changed


def ownership_record(owner):
    if owner is None:
        return {}
    try:
        if not bool(owner.get(KEY_MANAGED, False)):
            return {}
        return {
            "managed": True,
            "owner_id": str(owner.get(KEY_OWNER_ID, "") or ""),
            "role": str(owner.get(KEY_ROLE, "") or "").upper(),
            "schema": int(owner.get(KEY_SCHEMA, 0) or 0),
            "created_version": str(owner.get(KEY_CREATED_VERSION, "") or ""),
            "user_authored": bool(owner.get(KEY_USER_AUTHORED, False)),
        }
    except FBP_DATA_ERRORS:
        return {}


def can_remove_managed(owner, *, expected_owner_id="", roles=()):
    record = ownership_record(owner)
    if not record or record.get("user_authored"):
        return False
    if expected_owner_id and record.get("owner_id") != str(expected_owner_id):
        return False
    accepted = {str(item).upper() for item in roles if str(item)}
    if accepted and record.get("role") not in accepted:
        return False
    return record.get("role") in VALID_ROLES


def tag_layer_contract(rig):
    if rig is None:
        return False
    layer_id = ensure_layer_identity(rig)
    changed = tag_managed(rig, "LAYER_RIG", owner_id=layer_id)
    try:
        plane = getattr(rig, "fbp_plane_target", None)
    except FBP_DATA_ERRORS:
        plane = None
    if plane is not None:
        changed = tag_managed(plane, "LAYER_PLANE", owner_id=layer_id) or changed
    try:
        project_schema = importlib.import_module(f"{__package__}.project_schema")
        for scene in tuple(getattr(rig, "users_scene", ()) or ()):
            project_schema.mark_scene_current(scene)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return changed


def tag_effect_control_contract(control, rig):
    layer_id = ensure_layer_identity(rig)
    ensure_controller_identity(control)
    return tag_managed(control, "EFFECT_CONTROL", owner_id=layer_id)


def tag_mask_helper_contract(helper, rig):
    layer_id = ensure_layer_identity(rig)
    ensure_mask_identity(helper)
    return tag_managed(helper, "MASK_HELPER", owner_id=layer_id)


def tag_lattice_helper_contract(helper, rig):
    layer_id = ensure_layer_identity(rig)
    ensure_controller_identity(helper)
    return tag_managed(helper, "LATTICE_HELPER", owner_id=layer_id)


def audit_scene_ownership(scene, *, repair=False):
    stats = {
        "managed_objects": 0,
        "untagged_layer_rigs": 0,
        "untagged_layer_planes": 0,
        "untagged_helpers": 0,
        "orphan_managed_helpers": 0,
        "ownership_repairs": 0,
    }
    issues = []
    warnings = []
    if scene is None:
        return {"stats": stats, "issues": ("No active Scene for ownership audit",), "warnings": (), "repaired": 0}

    try:
        from .layers import iter_scene_fbp_rigs
        rigs = tuple(iter_scene_fbp_rigs(scene, fallback=True))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        rigs = ()
    layer_ids = set()
    for rig in rigs:
        try:
            layer_id = ensure_layer_identity(rig) if repair else str(rig.get("fbp_layer_id", "") or "")
        except FBP_DATA_ERRORS:
            layer_id = ""
        if layer_id:
            layer_ids.add(layer_id)
        record = ownership_record(rig)
        if record.get("role") != "LAYER_RIG" or record.get("owner_id") != layer_id:
            stats["untagged_layer_rigs"] += 1
            warnings.append(
                f"{getattr(rig, 'name', '<layer>')}: layer rig ownership does not match its stable layer ID"
            )
            if repair:
                stats["ownership_repairs"] += int(tag_layer_contract(rig))
        try:
            plane = getattr(rig, "fbp_plane_target", None)
        except FBP_DATA_ERRORS:
            plane = None
        plane_record = ownership_record(plane) if plane is not None else {}
        if plane is not None and (
            plane_record.get("role") != "LAYER_PLANE"
            or plane_record.get("owner_id") != layer_id
        ):
            stats["untagged_layer_planes"] += 1
            warnings.append(
                f"{getattr(rig, 'name', '<layer>')}: linked plane ownership does not match its stable layer ID"
            )
            if repair:
                stats["ownership_repairs"] += int(tag_layer_contract(rig))

    try:
        from .effect_controls import is_effect_control, effect_control_owner
    except (ImportError, AttributeError):
        is_effect_control = lambda _obj: False
        effect_control_owner = lambda _obj: None
    try:
        from .object_masks import is_object_mask_helper, find_object_mask_owner
    except (ImportError, AttributeError):
        is_object_mask_helper = lambda _obj: False
        find_object_mask_owner = lambda _obj: None

    try:
        objects = tuple(scene.objects)
    except FBP_DATA_ERRORS:
        objects = ()
    for obj in objects:
        record = ownership_record(obj)
        if record:
            stats["managed_objects"] += 1
            if record.get("role") not in {"LAYER_RIG", "LAYER_PLANE"}:
                owner_id = str(record.get("owner_id", "") or "")
                if owner_id and owner_id not in layer_ids:
                    stats["orphan_managed_helpers"] += 1
                    issues.append(f"{getattr(obj, 'name', '<helper>')}: managed helper references a missing layer owner")
        if is_effect_control(obj):
            owner = effect_control_owner(obj)
            owner_id = ensure_layer_identity(owner) if repair and owner is not None else (
                str(owner.get("fbp_layer_id", "") or "") if owner is not None else ""
            )
            helper_record = ownership_record(obj)
            if (
                helper_record.get("role") != "EFFECT_CONTROL"
                or (owner_id and helper_record.get("owner_id") != owner_id)
            ):
                stats["untagged_helpers"] += 1
                warnings.append(
                    f"{getattr(obj, 'name', '<control>')}: effect-control ownership does not match its layer"
                )
                if repair and owner is not None:
                    stats["ownership_repairs"] += int(tag_effect_control_contract(obj, owner))
        elif is_object_mask_helper(obj):
            owner = find_object_mask_owner(obj)
            owner_id = ensure_layer_identity(owner) if repair and owner is not None else (
                str(owner.get("fbp_layer_id", "") or "") if owner is not None else ""
            )
            helper_record = ownership_record(obj)
            if (
                helper_record.get("role") != "MASK_HELPER"
                or (owner_id and helper_record.get("owner_id") != owner_id)
            ):
                stats["untagged_helpers"] += 1
                warnings.append(
                    f"{getattr(obj, 'name', '<mask>')}: mask-helper ownership does not match its layer"
                )
                if repair and owner is not None:
                    stats["ownership_repairs"] += int(tag_mask_helper_contract(obj, owner))
        else:
            try:
                is_lattice = str(getattr(obj, "type", "") or "") == "LATTICE" and bool(obj.get("fbp_lattice_effect", ""))
            except FBP_DATA_ERRORS:
                is_lattice = False
            if is_lattice:
                rig = getattr(obj, "parent", None)
                owner_id = ensure_layer_identity(rig) if repair and rig is not None else (
                    str(rig.get("fbp_layer_id", "") or "") if rig is not None else ""
                )
                helper_record = ownership_record(obj)
                if (
                    helper_record.get("role") != "LATTICE_HELPER"
                    or (owner_id and helper_record.get("owner_id") != owner_id)
                ):
                    stats["untagged_helpers"] += 1
                    warnings.append(
                        f"{getattr(obj, 'name', '<lattice>')}: lattice ownership does not match its layer"
                    )
                    if repair and rig is not None:
                        stats["ownership_repairs"] += int(tag_lattice_helper_contract(obj, rig))

    return {
        "stats": stats,
        "issues": tuple(dict.fromkeys(issues)),
        "warnings": tuple(dict.fromkeys(warnings)),
        "repaired": int(stats["ownership_repairs"]),
    }



__all__ = (
    "FBP_OWNERSHIP_SCHEMA_VERSION",
    "VALID_ROLES",
    "tag_managed",
    "ownership_record",
    "can_remove_managed",
    "tag_layer_contract",
    "tag_effect_control_contract",
    "tag_mask_helper_contract",
    "tag_lattice_helper_contract",
    "audit_scene_ownership",
)
