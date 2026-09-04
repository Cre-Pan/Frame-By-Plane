"""Release-scope registry for stable and preview Frame By Plane features.

This module intentionally avoids ``bpy`` imports.  UI, operators and diagnostics consume the same immutable feature definitions so a preview workflow
cannot accidentally remain visible or executable after its toggle is disabled.
"""

from __future__ import annotations

from .generic_mesh_metadata import mesh_modifier_metadata

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


def fbp_preview_feature_usage(scene=None):
    """Return primitive evidence for Preview data already stored in a file."""
    evidence = {
        "compositor_layers": [],
        "procreate_import": [],
        "generic_mesh_effects": [],
    }
    if scene is not None:
        try:
            compositor_rows = len(getattr(scene, "fbp_compositor_layers", ()) or ())
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            compositor_rows = 0
        try:
            compositor_enabled = bool(getattr(scene, "fbp_compositor_enabled", False))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            compositor_enabled = False
        if compositor_rows:
            evidence["compositor_layers"].append(f"{compositor_rows} managed compositor row(s)")
        if compositor_enabled:
            evidence["compositor_layers"].append("managed compositor contract enabled")
        try:
            compositor_tree = getattr(scene, "compositing_node_group", None)
            if compositor_tree and bool(
                compositor_tree.get("fbp_compositor_owned", False)
                or compositor_tree.get("fbp_compositor_scene_id", "")
            ):
                evidence["compositor_layers"].append("persisted managed compositor node group")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
            pass

        try:
            if str(getattr(scene, "fbp_layered_report_format", "") or "").upper() == "PROCREATE":
                evidence["procreate_import"].append("stored Procreate import report")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

        generic_count = 0
        procreate_rigs = 0
        try:
            objects = tuple(getattr(scene, "objects", ()) or ())
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            objects = ()
        for obj in objects:
            try:
                layered_document = str(obj.get("fbp_layered_source_document", "") or "")
                layered_kind = str(obj.get("fbp_layered_source_kind", "") or "").upper()
                if layered_document.lower().endswith(".procreate") or "PROCREATE" in layered_kind:
                    procreate_rigs += 1
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
                pass
            try:
                modifiers = tuple(getattr(obj, "modifiers", ()) or ())
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
            for modifier in modifiers:
                try:
                    if mesh_modifier_metadata(modifier).get("fbp_generic_mesh_effect", False):
                        generic_count += 1
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    continue
        if generic_count:
            evidence["generic_mesh_effects"].append(
                f"{generic_count} FBP-owned Generic Mesh modifier(s)"
            )
        if procreate_rigs:
            evidence["procreate_import"].append(
                f"{procreate_rigs} rig(s) with persisted Procreate source metadata"
            )

    records = []
    for definition in fbp_preview_feature_definitions():
        feature_id = str(definition.get("id", "") or "")
        details = tuple(evidence.get(feature_id, ()))
        records.append({
            "id": feature_id,
            "label": str(definition.get("label", feature_id) or feature_id),
            "enabled": fbp_feature_enabled(scene, feature_id),
            "used": bool(details),
            "evidence": details,
            "description": str(definition.get("description", "") or ""),
            "disable_hint": str(definition.get("disable_hint", "") or ""),
        })
    return tuple(records)


def fbp_preview_diagnostics_text(scene=None):
    """Build a local text report that contains policy state but no project media."""
    records = fbp_preview_feature_usage(scene)
    enabled = sum(bool(record["enabled"]) for record in records)
    used = sum(bool(record["used"]) for record in records)
    lines = [
        "Frame By Plane — Preview Feature Diagnostics",
        f"Feature scope schema: {FBP_FEATURE_SCOPE_SCHEMA}",
        f"Enabled Preview features: {enabled}/{len(records)}",
        f"Preview features with stored data: {used}/{len(records)}",
        "Policy: Preview data remains readable but is outside the Frame By Plane 7.1 LTS stability promise.",
        "",
    ]
    for record in records:
        state = "enabled" if record["enabled"] else "disabled"
        usage = "; ".join(record["evidence"]) if record["used"] else "no stored Preview data detected"
        lines.extend((
            f"[{record['label']}] {state}; {usage}",
            f"  Scope: {record['description']}",
            f"  LTS-only action: {record['disable_hint']}",
        ))
    lines.extend((
        "",
        "This report stays local and contains no file paths, project media or telemetry.",
    ))
    return "\n".join(lines)


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
    "fbp_preview_diagnostics_text",
    "fbp_preview_feature_usage",
    "fbp_preview_feature_definitions",
    "validate_feature_scope",
)
