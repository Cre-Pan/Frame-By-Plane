"""Release-scope registry for stable and preview Frame By Plane features.

This module intentionally avoids ``bpy`` imports.  UI, operators and diagnostics consume the same immutable feature definitions so a preview workflow
cannot accidentally remain visible or executable after its toggle is disabled.
"""

from __future__ import annotations

from .support_policy import (
    FBP_FEATURE_DEFINITIONS,
    FBP_FEATURE_LTS,
    FBP_FEATURE_PREVIEW,
    FBP_FEATURE_SCOPE_SCHEMA,
)

_FEATURE_BY_ID = {item["id"]: item for item in FBP_FEATURE_DEFINITIONS}


def fbp_feature_definition(feature_id):
    return _FEATURE_BY_ID.get(str(feature_id or "").strip().lower())


def fbp_feature_is_preview(feature_id):
    definition = fbp_feature_definition(feature_id)
    return bool(definition and definition.get("maturity") == FBP_FEATURE_PREVIEW)


def fbp_feature_enabled(scene, feature_id):
    definition = fbp_feature_definition(feature_id)
    if definition is None:
        return False
    if definition.get("maturity") == FBP_FEATURE_LTS:
        return True
    property_name = str(definition.get("scene_property", "") or "")
    if not property_name or scene is None:
        return False
    try:
        return bool(getattr(scene, property_name, False))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def fbp_preview_feature_definitions():
    return tuple(
        definition for definition in FBP_FEATURE_DEFINITIONS
        if definition.get("maturity") == FBP_FEATURE_PREVIEW
    )


def fbp_enabled_preview_features(scene):
    return tuple(
        definition for definition in fbp_preview_feature_definitions()
        if fbp_feature_enabled(scene, definition["id"])
    )


def fbp_feature_scope_snapshot(scene=None):
    features = []
    for definition in FBP_FEATURE_DEFINITIONS:
        features.append({
            "id": definition["id"],
            "label": definition["label"],
            "maturity": definition["maturity"],
            "enabled": fbp_feature_enabled(scene, definition["id"]),
            "scene_property": str(definition.get("scene_property", "") or ""),
        })
    enabled_preview = [item["id"] for item in features if item["maturity"] == FBP_FEATURE_PREVIEW and item["enabled"]]
    return {
        "schema": FBP_FEATURE_SCOPE_SCHEMA,
        "lts_features": sum(item["maturity"] == FBP_FEATURE_LTS for item in features),
        "preview_features": sum(item["maturity"] == FBP_FEATURE_PREVIEW for item in features),
        "enabled_preview_features": enabled_preview,
        "lts_only": not enabled_preview,
        "features": features,
    }


def validate_feature_scope():
    issues = []
    seen_ids = set()
    seen_properties = set()
    allowed = {FBP_FEATURE_LTS, FBP_FEATURE_PREVIEW}
    for index, definition in enumerate(FBP_FEATURE_DEFINITIONS):
        feature_id = str(definition.get("id", "") or "")
        label = str(definition.get("label", "") or "")
        maturity = str(definition.get("maturity", "") or "")
        property_name = str(definition.get("scene_property", "") or "")
        prefix = f"feature[{index}]"
        if not feature_id:
            issues.append(f"{prefix}: missing id")
        elif feature_id in seen_ids:
            issues.append(f"{prefix}: duplicate id {feature_id!r}")
        seen_ids.add(feature_id)
        if not label:
            issues.append(f"{prefix}: missing label")
        if maturity not in allowed:
            issues.append(f"{prefix}: unsupported maturity {maturity!r}")
        if maturity == FBP_FEATURE_PREVIEW and not property_name:
            issues.append(f"{prefix}: preview feature has no scene property")
        if property_name:
            if property_name in seen_properties:
                issues.append(f"{prefix}: duplicate scene property {property_name!r}")
            seen_properties.add(property_name)
    return tuple(issues)


FBP_FEATURE_SCOPE_ISSUES = validate_feature_scope()

__all__ = (
    "FBP_FEATURE_DEFINITIONS",
    "FBP_FEATURE_LTS",
    "FBP_FEATURE_PREVIEW",
    "FBP_FEATURE_SCOPE_ISSUES",
    "FBP_FEATURE_SCOPE_SCHEMA",
    "fbp_enabled_preview_features",
    "fbp_feature_definition",
    "fbp_feature_enabled",
    "fbp_feature_is_preview",
    "fbp_feature_scope_snapshot",
    "fbp_preview_feature_definitions",
    "validate_feature_scope",
)
