"""Non-destructive project validation and issue navigation for Frame By Plane."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UIList

from .runtime import (
    FBP_DATA_ERRORS,
    fbp_registration_busy,
    fbp_registration_state,
)
from .generation_transaction import (
    active_generation_snapshot,
    generation_journal_is_orphaned,
    persisted_generation_journal,
    recover_orphaned_generation,
)
from .registration import register_classes, unregister_classes, unregister_type_properties
from .identifiers import repair_scene_identities
from .ownership import audit_scene_ownership, ownership_record
from .transactions import (
    TRANSACTION_SCHEMA_VERSION,
    recover_transaction_journal,
    transaction_journal,
)
from .feature_scope import (
    FBP_FEATURE_SCOPE_ISSUES,
    fbp_enabled_preview_features,
    fbp_feature_scope_snapshot,
    fbp_preview_feature_usage,
)
from .project_schema import (
    FBP_PROJECT_SCHEMA_VERSION,
    project_schema_status,
)
from .ui_list_state import mark_ui_list_draw
from .interface_preferences import (
    fbp_draw_uilist_spacer,
    fbp_uilist_icon_order,
    fbp_uilist_is_spacer,
    fbp_uilist_visible_columns,
)


REPORT_NAME = "FBP_Project_Health"
SEVERITY_ORDER = {"ERROR": 0, "WARNING": 1, "INFO": 2}
SEVERITY_ICONS = {"ERROR": "ERROR", "WARNING": "INFO", "INFO": "DOT"}

def project_doctor_counts(scene):
    """Return stable severity counts for the visible Project Doctor UI."""
    counts = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    try:
        issues = tuple(getattr(scene, "fbp_health_issues", ()) or ())
    except FBP_DATA_ERRORS:
        return counts
    for item in issues:
        try:
            severity = str(getattr(item, "severity", "INFO") or "INFO").upper()
        except FBP_DATA_ERRORS:
            severity = "INFO"
        counts[severity if severity in counts else "INFO"] += 1
    return counts


def active_project_doctor_issue(scene):
    """Return the active issue without leaking invalid RNA references."""
    try:
        issues = scene.fbp_health_issues
        index = int(getattr(scene, "fbp_health_issue_index", -1) or -1)
        return issues[index] if 0 <= index < len(issues) else None
    except (IndexError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None



class FBP_ProjectHealthIssue(PropertyGroup):
    severity: EnumProperty(description='Choose the Severity option for this project diagnostic. Hover each entry for the specific mode when Blender exposes enum item help.', 
        name="Severity",
        items=(
            ("INFO", "Info", "Informational project-health message"),
            ("WARNING", "Warning", "Potential production problem"),
            ("ERROR", "Error", "Broken or invalid Frame By Plane contract"),
        ),
        default="INFO",
    )
    code: StringProperty(description='Code value used by the current project diagnostic. Changes are applied only to compatible Frame By Plane data.', name="Code", default="")
    message: StringProperty(description='Message value used by the current project diagnostic. Changes are applied only to compatible Frame By Plane data.', name="Message", default="")
    object_name: StringProperty(description='Name of the Blender object targeted by this operation. Used to resolve the correct generated helper safely.', name="Object", default="")
    data_name: StringProperty(description='Display name stored by Frame By Plane. Renaming keeps internal identifiers and generated links intact.', name="Data", default="")
    repair_hint: StringProperty(description='Repair Hint value used by the current project diagnostic. Changes are applied only to compatible Frame By Plane data.', name="Repair Hint", default="")
    action_schema: IntProperty(default=0, options={"HIDDEN"})
    fix_action: StringProperty(default="", options={"HIDDEN"})
    fix_label: StringProperty(default="", options={"HIDDEN"})
    fix_description: StringProperty(default="", options={"HIDDEN"})
    fix_icon: StringProperty(default="", options={"HIDDEN"})
    navigation_action: StringProperty(default="", options={"HIDDEN"})
    navigation_label: StringProperty(default="", options={"HIDDEN"})


def _issue(severity, code, message, *, object_name="", data_name="", repair_hint=""):
    return {
        "severity": str(severity or "INFO").upper(),
        "code": str(code or "GENERAL"),
        "message": str(message or ""),
        "object_name": str(object_name or ""),
        "data_name": str(data_name or ""),
        "repair_hint": str(repair_hint or ""),
    }


def _append_unique(issues, issue, seen):
    key = (
        issue["severity"], issue["code"], issue["message"],
        issue["object_name"], issue["data_name"],
    )
    if key in seen:
        return
    seen.add(key)
    issues.append(issue)


def _safe_image_path(image):
    try:
        raw = str(getattr(image, "filepath", "") or "")
        return os.path.normcase(os.path.abspath(bpy.path.abspath(raw))) if raw else ""
    except (AttributeError, OSError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ""


def _sequence_end(rig):
    try:
        start = int(getattr(rig, "fbp_start_frame", 1) or 1)
        images = tuple(getattr(rig, "fbp_images", ()) or ())
    except FBP_DATA_ERRORS:
        return None
    if not images:
        return None
    durations = []
    for item in images:
        try:
            durations.append(max(1, int(getattr(item, "duration", 1) or 1)))
        except FBP_DATA_ERRORS:
            durations.append(1)
    return start + max(1, sum(durations)) - 1


def _iter_project_driver_owners(scene, rigs):
    """Yield only FBP-owned IDs that can legitimately contain drivers."""
    seen = set()

    def _yield(owner):
        if owner is None:
            return
        try:
            key = int(owner.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(owner)
        if key in seen:
            return
        seen.add(key)
        yield owner

    for rig in tuple(rigs or ()):
        yield from _yield(rig)
        try:
            plane = getattr(rig, "fbp_plane_target", None)
        except FBP_DATA_ERRORS:
            plane = None
        yield from _yield(plane)
        try:
            yield from _yield(getattr(plane, "data", None))
        except FBP_DATA_ERRORS:
            pass
        try:
            material = getattr(rig, "active_material", None) or getattr(plane, "active_material", None)
        except FBP_DATA_ERRORS:
            material = None
        yield from _yield(material)
        try:
            yield from _yield(getattr(material, "node_tree", None))
        except FBP_DATA_ERRORS:
            pass
        for driven_object in (rig, plane):
            try:
                modifiers = tuple(getattr(driven_object, "modifiers", ()) or ())
            except FBP_DATA_ERRORS:
                modifiers = ()
            for modifier in modifiers:
                try:
                    yield from _yield(getattr(modifier, "node_group", None))
                except FBP_DATA_ERRORS:
                    continue

    try:
        objects = tuple(getattr(scene, "objects", ()) or ())
    except FBP_DATA_ERRORS:
        objects = ()
    for obj in objects:
        try:
            managed = bool(ownership_record(obj)) or bool(getattr(obj, "is_fbp_control", False)) or bool(getattr(obj, "is_fbp_plane", False))
        except FBP_DATA_ERRORS:
            managed = False
        if managed:
            yield from _yield(obj)


def _audit_project_drivers(scene, rigs):
    """Validate FBP driver curves and their external target paths."""
    stats = {"drivers": 0, "invalid_drivers": 0, "missing_driver_targets": 0}
    issues = []
    seen = set()
    for owner in _iter_project_driver_owners(scene, rigs):
        try:
            animation_data = getattr(owner, "animation_data", None)
            drivers = tuple(getattr(animation_data, "drivers", ()) or ()) if animation_data else ()
        except FBP_DATA_ERRORS:
            continue
        owner_name = str(getattr(owner, "name", type(owner).__name__) or type(owner).__name__)
        owner_is_object = False
        try:
            owner_is_object = scene.objects.get(str(getattr(owner, "name", "") or "")) is owner
        except FBP_DATA_ERRORS:
            pass
        for fcurve in drivers:
            stats["drivers"] += 1
            try:
                data_path = str(getattr(fcurve, "data_path", "") or "")
                index = int(getattr(fcurve, "array_index", 0) or 0)
                valid = bool(getattr(fcurve, "is_valid", True))
            except FBP_DATA_ERRORS:
                data_path, index, valid = "", 0, False
            curve_label = f"{owner_name}: {data_path}[{index}]" if data_path else owner_name
            if not valid:
                stats["invalid_drivers"] += 1
                key = ("INVALID_DRIVER", curve_label)
                if key not in seen:
                    seen.add(key)
                    issues.append(_issue(
                        "ERROR", "BROKEN_DRIVER",
                        f"Driver is invalid: {data_path or '<unknown path>'}",
                        object_name=owner_name if owner_is_object else "",
                        data_name="" if owner_is_object else owner_name,
                        repair_hint="Open the Drivers editor and repair or remove the invalid FBP driver",
                    ))
            try:
                variables = tuple(getattr(getattr(fcurve, "driver", None), "variables", ()) or ())
            except FBP_DATA_ERRORS:
                variables = ()
            for variable in variables:
                try:
                    variable_type = str(getattr(variable, "type", "") or "").upper()
                    variable_name = str(getattr(variable, "name", "") or "<variable>")
                except FBP_DATA_ERRORS:
                    continue
                if variable_type not in {"SINGLE_PROP", "TRANSFORMS", "ROTATION_DIFF", "LOC_DIFF"}:
                    continue
                try:
                    targets = tuple(getattr(variable, "targets", ()) or ())
                except FBP_DATA_ERRORS:
                    targets = ()
                for target_index, target in enumerate(targets):
                    try:
                        target_id = getattr(target, "id", None)
                        target_path = str(getattr(target, "data_path", "") or "")
                    except FBP_DATA_ERRORS:
                        target_id, target_path = None, ""
                    missing = target_id is None or (variable_type == "SINGLE_PROP" and not target_path)
                    if not missing and variable_type == "SINGLE_PROP":
                        try:
                            target_id.path_resolve(target_path, False)
                        except FBP_DATA_ERRORS:
                            missing = True
                    if not missing:
                        continue
                    stats["missing_driver_targets"] += 1
                    key = ("DRIVER_TARGET", curve_label, variable_name, target_index)
                    if key in seen:
                        continue
                    seen.add(key)
                    issues.append(_issue(
                        "ERROR", "DRIVER_TARGET",
                        f"Driver variable {variable_name} has a missing or invalid target",
                        object_name=owner_name if owner_is_object else "",
                        data_name="" if owner_is_object else owner_name,
                        repair_hint="Open the Drivers editor and reconnect the missing target",
                    ))
    return {"stats": stats, "issues": tuple(issues)}


def _populate_scene_issues(scene, issues):
    try:
        try:
            from .actionable_issues import project_doctor_action_metadata
        except ImportError:
            project_doctor_action_metadata = lambda _issue: {}
        collection = scene.fbp_health_issues
        collection.clear()
        for issue in issues:
            item = collection.add()
            item.severity = issue["severity"] if issue["severity"] in SEVERITY_ORDER else "INFO"
            item.code = issue["code"]
            item.message = issue["message"]
            item.object_name = issue["object_name"]
            item.data_name = issue["data_name"]
            item.repair_hint = issue["repair_hint"]
            actions = project_doctor_action_metadata(issue)
            item.action_schema = int(actions.get("action_schema", 0) or 0)
            item.fix_action = str(actions.get("fix_action", "") or "")
            item.fix_label = str(actions.get("fix_label", "") or "")
            item.fix_description = str(
                actions.get("fix_description", "") or ""
            )
            item.fix_icon = str(actions.get("fix_icon", "") or "")
            item.navigation_action = str(
                actions.get("navigation_action", "") or ""
            )
            item.navigation_label = str(
                actions.get("navigation_label", "") or ""
            )
        # Start before the first issue so the Select Problem action cycles to
        # the first selectable object on its first invocation.
        scene.fbp_health_issue_index = -1
        error_count = sum(1 for item in issues if item["severity"] == "ERROR")
        warning_count = sum(1 for item in issues if item["severity"] == "WARNING")
        info_count = sum(1 for item in issues if item["severity"] == "INFO")
        scene.fbp_health_last_status = (
            "ERROR" if error_count else "WARNING" if warning_count else "PASS"
        )
        scene.fbp_health_last_run = datetime.now().isoformat(timespec="seconds")
        scene.fbp_health_last_summary = (
            f"{error_count} error(s) · {warning_count} warning(s) · {info_count} info"
        )
    except FBP_DATA_ERRORS:
        pass



def _transaction_journal_owners(scene):
    """Yield Scene-owned datablocks that can retain an interrupted FBP journal."""
    if scene is None:
        return
    seen = set()
    candidates = [scene]
    try:
        candidates.extend(tuple(getattr(scene, "objects", ()) or ()))
    except FBP_DATA_ERRORS:
        pass
    root = getattr(scene, "collection", None)
    stack = [root] if root is not None else []
    while stack:
        collection = stack.pop()
        if collection is None:
            continue
        candidates.append(collection)
        try:
            stack.extend(tuple(getattr(collection, "children", ()) or ()))
        except FBP_DATA_ERRORS:
            pass
    for owner in candidates:
        try:
            key = int(owner.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(owner)
        if key in seen:
            continue
        seen.add(key)
        yield owner

def scan_project_health(scene, *, repair=False):
    """Return a deterministic, non-destructive production-health report."""
    issues = []
    seen = set()
    stats = defaultdict(int)
    repaired = 0

    if scene is None:
        issue = _issue("ERROR", "NO_SCENE", "No active Scene is available")
        return {"issues": (issue,), "stats": {"issues": 1}, "repaired": 0}

    registration_state = fbp_registration_state()
    stats["registration_state"] = registration_state
    stats["registration_busy"] = int(bool(fbp_registration_busy()))
    if registration_state in {"FAILED", "FAILED_UNSAFE"}:
        unsafe = registration_state == "FAILED_UNSAFE"
        _append_unique(
            issues,
            _issue(
                "ERROR",
                "ADDON_LIFECYCLE_FAILED",
                (
                    "Frame By Plane registration failed unsafely; deferred work and authoring features "
                    "remain suspended to avoid using partially registered RNA"
                    if unsafe else
                    "Frame By Plane registration failed; the rollback completed and authoring features are suspended"
                ),
                repair_hint=(
                    "Save the file, restart Blender, then reinstall or re-enable Frame By Plane; copy this Project Doctor report first"
                    if unsafe else
                    "Disable and re-enable Frame By Plane; restart Blender if registration fails again"
                ),
            ),
            seen,
        )

    generation_journal = persisted_generation_journal(scene)
    active_generation = active_generation_snapshot()
    stats["generation_active"] = int(bool(active_generation))
    stats["generation_journal"] = int(bool(generation_journal))
    if generation_journal and generation_journal_is_orphaned(scene):
        recovery = None
        if repair:
            recovery = recover_orphaned_generation(scene, getattr(bpy, "context", None))
            if recovery.get("verified", False):
                repaired += len(recovery.get("removed", ()) or ()) + len(recovery.get("restored", ()) or ())
                stats["generation_orphan_recovered"] = 1
                generation_journal = {}
        if generation_journal:
            failed = len((recovery or {}).get("failed", ()) or ())
            remaining = len((recovery or {}).get("remaining", ()) or ())
            _append_unique(
                issues,
                _issue(
                    "ERROR",
                    "ORPHAN_GENERATION_TRANSACTION",
                    (
                        f"Interrupted generation {generation_journal.get('token', 'unknown')} is orphaned "
                        f"in phase {generation_journal.get('phase', 'UNKNOWN')}"
                        + (f"; repair left {failed} failure(s) and {remaining} owned item(s)" if recovery else "")
                    ),
                    repair_hint="Run Project Doctor Repair; only datablocks carrying this transaction's owner token can be removed",
                ),
                seen,
            )

    try:
        from .compatibility_52 import blender_52_runtime_contract
        compatibility = blender_52_runtime_contract()
        stats["blender_52_capabilities"] = sum(
            1 for value in compatibility.get("capabilities", {}).values() if value is True
        )
        build = compatibility.get("build", {}) or {}
        policy = compatibility.get("policy", {}) or {}
        stats["release_channel"] = str(policy.get("release_channel", "") or "")
        stats["lts_target_version"] = str(policy.get("lts_target_version", "") or "")
        stats["runtime_platform"] = str(policy.get("runtime_platform", "") or "")
        stats["blender_build_hash"] = str(build.get("build_hash", "") or "")[:16]
        stats["blender_build_date"] = str(build.get("build_commit_date", "") or "")
        stats["blender_version_cycle"] = str(build.get("version_cycle", "") or "")
        for message in compatibility.get("issues", ()):
            _append_unique(
                issues,
                _issue("ERROR", "RUNTIME_SCOPE", message),
                seen,
            )
        for message in compatibility.get("warnings", ()):
            _append_unique(
                issues,
                _issue("WARNING", "RUNTIME_SCOPE", message),
                seen,
            )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        _append_unique(
            issues,
            _issue("ERROR", "RUNTIME_SCOPE", f"Could not validate Blender 5.2 LTS runtime scope: {exc}"),
            seen,
        )


    scope = fbp_feature_scope_snapshot(scene)
    stats["feature_scope_schema"] = int(scope.get("schema", 0) or 0)
    stats["lts_features"] = int(scope.get("lts_features", 0) or 0)
    stats["preview_features"] = int(scope.get("preview_features", 0) or 0)
    stats["enabled_preview_features"] = len(scope.get("enabled_preview_features", ()) or ())
    for message in FBP_FEATURE_SCOPE_ISSUES:
        _append_unique(
            issues,
            _issue("ERROR", "FEATURE_SCOPE", message, repair_hint="Update or reinstall Frame By Plane"),
            seen,
        )
    for definition in fbp_enabled_preview_features(scene):
        _append_unique(
            issues,
            _issue(
                "WARNING",
                "PREVIEW_FEATURE",
                f"Preview limitation (not an LTS error): {definition['label']} is enabled outside the Frame By Plane 7.1 LTS core scope",
                repair_hint=str(definition.get("disable_hint", "") or "Disable the preview feature for an LTS-only project"),
            ),
            seen,
        )

    preview_usage = fbp_preview_feature_usage(scene)
    stats["preview_data_features"] = sum(bool(item.get("used")) for item in preview_usage)
    for usage in preview_usage:
        if not usage.get("used"):
            continue
        details = "; ".join(usage.get("evidence", ())) or "stored Preview data"
        state = "enabled" if usage.get("enabled") else "disabled"
        _append_unique(
            issues,
            _issue(
                "INFO",
                "PREVIEW_DATA",
                f"Preview data notice (not an LTS error): this file contains {details} for {usage['label']}; the feature is {state}",
                repair_hint=(
                    str(usage.get("disable_hint", "") or "")
                    if usage.get("enabled")
                    else f"Existing data remains readable; enable {usage['label']} Preview only when it must be edited"
                ),
            ),
            seen,
        )

    schema = project_schema_status(scene)
    stats["project_schema"] = int(schema.get("source_schema", 0) or 0)
    stats["project_schema_target"] = FBP_PROJECT_SCHEMA_VERSION
    if schema.get("unsupported_future"):
        _append_unique(
            issues,
            _issue(
                "ERROR",
                "PROJECT_SCHEMA",
                f"Project schema {schema.get('source_schema')} is newer than this add-on supports",
                repair_hint="Open the file with the Frame By Plane version that created it",
            ),
            seen,
        )
    elif schema.get("missing_baseline") or schema.get("unsupported_older"):
        source = int(schema.get("source_schema", 0) or 0)
        detail = (
            "This Frame By Plane data has no 7.1 project contract"
            if source == 0
            else f"Project schema {source} predates the supported 7.1 baseline"
        )
        _append_unique(
            issues,
            _issue(
                "ERROR",
                "PROJECT_SCHEMA",
                detail,
                repair_hint="Open and resave the project with Frame By Plane 7.1 before using this build",
            ),
            seen,
        )

    stats["transaction_schema"] = TRANSACTION_SCHEMA_VERSION
    for owner in _transaction_journal_owners(scene):
        journal = transaction_journal(owner)
        if not journal:
            continue
        stats["pending_transactions"] += 1
        recovered = False
        if repair:
            recovered = bool(recover_transaction_journal(owner))
            if recovered:
                stats["recovered_transactions"] += 1
                repaired += 1
                continue
            stats["transaction_recovery_failures"] += 1
        state = str(journal.get("state", "OPEN") or "OPEN").upper()
        kind = str(journal.get("kind", "UNKNOWN") or "UNKNOWN").upper()
        label = str(journal.get("label", "Interrupted operation") or "Interrupted operation")
        owner_name = str(getattr(owner, "name", "") or "")
        severity = "ERROR" if state in {"CORRUPT", "ROLLBACK_FAILED"} else "WARNING"
        _append_unique(
            issues,
            _issue(
                severity,
                "PENDING_TRANSACTION",
                f"{label} did not close cleanly ({kind} · {state})",
                object_name=owner_name if getattr(owner, "is_fbp_control", False) else "",
                data_name=owner_name,
                repair_hint="Run Project Doctor Repair to reconcile or roll back generated state",
            ),
            seen,
        )

    # Normal repair remains additive. The only structural exception is recovery
    # of a persisted transaction journal, which reconciles or removes generated
    # partial state left by an interrupted Frame By Plane operation.
    identity = repair_scene_identities(scene, repair_duplicates=repair, create_missing=repair)
    ownership_repair = audit_scene_ownership(scene, repair=repair)
    identity_stats = dict(identity.get("stats", {}) or {})
    identity_repaired = sum(
        int(value or 0)
        for key, value in identity_stats.items()
        if key.endswith(("_created", "_repaired"))
    )
    repaired += identity_repaired + int(ownership_repair.get("repaired", 0) or 0)
    ownership = audit_scene_ownership(scene, repair=False) if repair else ownership_repair
    for key, value in (identity.get("stats", {}) or {}).items():
        stats[key] += int(value or 0)
    for key, value in (ownership.get("stats", {}) or {}).items():
        stats[key] += int(value or 0)
    for message in identity.get("issues", ()) or ():
        _append_unique(issues, _issue("ERROR", "IDENTITY", message, repair_hint="Run Project Doctor Repair"), seen)
    for message in identity.get("warnings", ()) or ():
        _append_unique(issues, _issue("WARNING", "IDENTITY", message, repair_hint="Run Project Doctor Repair"), seen)
    for message in ownership.get("issues", ()) or ():
        _append_unique(issues, _issue("ERROR", "OWNERSHIP", message, repair_hint="Run Project Doctor Repair"), seen)
    for message in ownership.get("warnings", ()) or ():
        _append_unique(issues, _issue("WARNING", "OWNERSHIP", message, repair_hint="Run Project Doctor Repair"), seen)

    try:
        from .layers import (
            collect_project_image_paths,
            collection_has_fbp_content,
            iter_scene_fbp_rigs,
            iter_fbp_rigs_in_collection,
            missing_project_images,
            rig_has_missing_images,
        )
        rigs = tuple(iter_scene_fbp_rigs(scene, fallback=True))
        stats["layers"] = len(rigs)
        stats["linked_images"] = len(collect_project_image_paths())
        missing_paths = tuple(missing_project_images())
        stats["missing_images"] = len(missing_paths)
        for path in missing_paths:
            _append_unique(
                issues,
                _issue("ERROR", "MISSING_FILE", f"Missing source file: {path}", data_name=path, repair_hint="Relink the project or replace the source"),
                seen,
            )
        for rig in rigs:
            rig_name = str(getattr(rig, "name", "<layer>") or "<layer>")
            if rig_has_missing_images(rig):
                _append_unique(issues, _issue("ERROR", "BROKEN_SOURCE", "Layer contains one or more missing source images", object_name=rig_name, repair_hint="Relink or replace this source"), seen)
            start = int(getattr(rig, "fbp_start_frame", scene.frame_start) or scene.frame_start)
            end = _sequence_end(rig)
            if end is not None and (start < int(scene.frame_start) or end > int(scene.frame_end)):
                stats["out_of_range_layers"] += 1
                _append_unique(
                    issues,
                    _issue("INFO", "FRAME_RANGE", f"Layer timing extends outside the Scene range ({start}–{end})", object_name=rig_name),
                    seen,
                )
            try:
                hidden_view = bool(rig.hide_viewport or rig.hide_get())
                hidden_render = bool(rig.hide_render)
            except FBP_DATA_ERRORS:
                hidden_view = hidden_render = False
            if hidden_view and not hidden_render:
                stats["hidden_render_enabled"] += 1
                _append_unique(
                    issues,
                    _issue("WARNING", "HIDDEN_RENDER", "Layer is hidden in the viewport but remains enabled for render", object_name=rig_name),
                    seen,
                )

        fbp_collections = tuple(
            coll for coll in bpy.data.collections
            if collection_has_fbp_content(coll, True)
        )
        stats["collections"] = len(fbp_collections)
        for coll in fbp_collections:
            if not any(True for _ in iter_fbp_rigs_in_collection(coll, True)):
                _append_unique(issues, _issue("INFO", "EMPTY_COLLECTION", "Frame By Plane collection contains no layers", data_name=coll.name), seen)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        rigs = ()
        _append_unique(issues, _issue("ERROR", "LAYER_SCAN", f"Could not inspect Frame By Plane layers: {exc}"), seen)

    try:
        driver_result = _audit_project_drivers(scene, rigs)
        for key, value in (driver_result.get("stats", {}) or {}).items():
            stats[key] += int(value or 0)
        for item in driver_result.get("issues", ()) or ():
            _append_unique(issues, item, seen)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        stats["driver_scan_incomplete"] += 1

    try:
        render = getattr(scene, "render", None)
        if str(getattr(render, "engine", "") or "") == "CYCLES":
            if hasattr(render, "use_texture_cache"):
                texture_cache = bool(getattr(render, "use_texture_cache", False))
                stats["cycles_texture_cache"] = int(texture_cache)
                if len(rigs) >= 8 and not texture_cache:
                    _append_unique(
                        issues,
                        _issue(
                            "INFO",
                            "CYCLES_TEXTURE_CACHE",
                            "Blender 5.2 Texture Cache is disabled in an image-heavy FBP scene",
                            repair_hint="Enable Render > Sampling > Texture Cache to reduce repeated image decoding",
                        ),
                        seen,
                    )
            if hasattr(render, "anisotropic_filter"):
                stats["anisotropic_filter"] = str(getattr(render, "anisotropic_filter", "") or "")
            from .core import _fbp_cycles_recommended_transparent_bounces
            recommended, transparent_surfaces = _fbp_cycles_recommended_transparent_bounces(scene)
            cycles = getattr(scene, "cycles", None)
            current = int(getattr(cycles, "transparent_max_bounces", 0) or 0) if cycles is not None else 0
            stats["cycles_transparent_surfaces"] = int(transparent_surfaces)
            stats["cycles_transparent_bounces"] = int(current)
            stats["cycles_transparent_bounces_recommended"] = int(recommended)
            if recommended > current:
                _append_unique(
                    issues,
                    _issue(
                        "WARNING",
                        "CYCLES_TRANSPARENCY_DEPTH",
                        f"Cycles Transparent Max Bounces is {current}; this layered FBP scene may require about {recommended}",
                        repair_hint="FBP raises it temporarily for final renders; increase Light Paths > Transparent for Cycles viewport parity",
                    ),
                    seen,
                )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    try:
        from .native_backend import fbp_native_rig_contract_issues, fbp_native_media_cache_report
        for rig in rigs:
            if bool(getattr(rig, "fbp_is_color_plane", False)):
                continue
            for message in fbp_native_rig_contract_issues(rig):
                stats["native_contract_issues"] += 1
                _append_unique(
                    issues,
                    _issue("ERROR", "NATIVE_SEQUENCE", message, object_name=getattr(rig, "name", ""), repair_hint="Run Deep Audit Repair or rebuild the source"),
                    seen,
                )
        cache_result = fbp_native_media_cache_report(repair=False)
        for key, value in (cache_result.get("stats", {}) or {}).items():
            stats[key] += int(value or 0)
        for message in cache_result.get("issues", ()) or ():
            _append_unique(issues, _issue("ERROR", "NATIVE_CACHE", message, repair_hint="Run Deep Audit Repair"), seen)
        for message in cache_result.get("warnings", ()) or ():
            _append_unique(issues, _issue("WARNING", "NATIVE_CACHE", message), seen)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    try:
        from .effects_registry import fbp_effect_definition, fbp_effect_supported_for_rig
        from .geometry_nodes import (
            fbp_effect_ids_for_rig,
            fbp_find_effect_modifier,
            fbp_geometry_modifier_52_issues,
            fbp_geometry_modifier_52_warnings,
        )
        for rig in rigs:
            rig_name = str(getattr(rig, "name", "<layer>") or "<layer>")
            for effect_id in tuple(fbp_effect_ids_for_rig(rig)):
                stats["effects"] += 1
                if not fbp_effect_supported_for_rig(rig, effect_id):
                    stats["unsupported_effects"] += 1
                    _append_unique(issues, _issue("ERROR", "UNSUPPORTED_EFFECT", f"{effect_id} is incompatible with this layer", object_name=rig_name), seen)
                definition = fbp_effect_definition(effect_id)
                if str(definition.get("kind", "") or "").upper() == "GEOMETRY":
                    modifier = fbp_find_effect_modifier(rig, effect_id)
                    if modifier is None or getattr(modifier, "node_group", None) is None:
                        stats["missing_effect_groups"] += 1
                        _append_unique(issues, _issue("ERROR", "MISSING_EFFECT_GROUP", f"{effect_id} has no valid Geometry Nodes group", object_name=rig_name, repair_hint="Run Deep Audit Repair"), seen)
                    else:
                        try:
                            execution_ms = max(0.0, float(getattr(modifier, "execution_time", 0.0) or 0.0) * 1000.0)
                        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                            execution_ms = 0.0
                        if execution_ms > 0.0:
                            stats["geometry_nodes_profiled"] += 1
                            stats["geometry_nodes_max_execution_ms"] = max(
                                float(stats.get("geometry_nodes_max_execution_ms", 0.0) or 0.0),
                                execution_ms,
                            )
                            if execution_ms >= 50.0:
                                _append_unique(
                                    issues,
                                    _issue(
                                        "WARNING",
                                        "GEOMETRY_NODES_COST",
                                        f"{effect_id} evaluates in about {execution_ms:.1f} ms",
                                        object_name=rig_name,
                                        repair_hint="Reduce effect resolution/detail or disable it outside final render",
                                    ),
                                    seen,
                                )
                            elif execution_ms >= 20.0:
                                _append_unique(
                                    issues,
                                    _issue(
                                        "INFO",
                                        "GEOMETRY_NODES_COST",
                                        f"{effect_id} evaluates in about {execution_ms:.1f} ms",
                                        object_name=rig_name,
                                    ),
                                    seen,
                                )
                        for message in fbp_geometry_modifier_52_issues(modifier, effect_id):
                            stats["geometry_nodes_52_issues"] += 1
                            _append_unique(
                                issues,
                                _issue(
                                    "WARNING",
                                    "GEOMETRY_NODES_52",
                                    f"{effect_id}: {message}",
                                    object_name=rig_name,
                                    repair_hint="Rebuild the effect or run Deep Audit Repair",
                                ),
                                seen,
                            )
                        for warning_type, message in fbp_geometry_modifier_52_warnings(modifier):
                            stats["geometry_nodes_eval_warnings"] += 1
                            severity = (
                                "ERROR" if warning_type == "ERROR"
                                else "INFO" if warning_type == "INFO"
                                else "WARNING"
                            )
                            _append_unique(
                                issues,
                                _issue(
                                    severity,
                                    "GEOMETRY_NODES_EVAL",
                                    f"{effect_id}: {message}",
                                    object_name=rig_name,
                                    repair_hint=(
                                        "Inspect the Geometry Nodes evaluation warning"
                                        if severity != "INFO" else ""
                                    ),
                                ),
                                seen,
                            )
            from .geometry_nodes import fbp_local_effect_mask_contract_report
            local_mask_result = fbp_local_effect_mask_contract_report(rig, repair=False)
            for key, value in (local_mask_result.get("stats", {}) or {}).items():
                stats[key] += int(value or 0)
            for message in local_mask_result.get("issues", ()) or ():
                _append_unique(issues, _issue("ERROR", "MASK_TARGET", message, object_name=rig_name, repair_hint="Run Deep Audit Repair"), seen)
            for message in local_mask_result.get("warnings", ()) or ():
                _append_unique(issues, _issue("WARNING", "MASK_TARGET", message, object_name=rig_name), seen)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        _append_unique(issues, _issue("WARNING", "EFFECT_SCAN", f"Effect validation was incomplete: {exc}"), seen)

    try:
        from .geometry_nodes import audit_mask_stack_rig

        for rig in rigs:
            rig_name = str(getattr(rig, "name", "<layer>") or "<layer>")
            mask_stack_result = audit_mask_stack_rig(rig, repair=repair)
            repaired += int(mask_stack_result.get("repaired", 0) or 0)
            for message in mask_stack_result.get("issues", ()) or ():
                stats["mask_stack_issues"] += 1
                _append_unique(
                    issues,
                    _issue(
                        "ERROR",
                        "MASK_STACK",
                        message,
                        object_name=rig_name,
                        repair_hint=(
                            "Open the file with the Frame By Plane version that "
                            "created this Mask Stack, or run Project Doctor Repair"
                        ),
                    ),
                    seen,
                )
            for message in mask_stack_result.get("warnings", ()) or ():
                stats["mask_stack_warnings"] += 1
                _append_unique(
                    issues,
                    _issue(
                        "WARNING",
                        "MASK_STACK",
                        message,
                        object_name=rig_name,
                        repair_hint="Update the Mask Stack or run Project Doctor Repair",
                    ),
                    seen,
                )
    except (
        ImportError,
        AttributeError,
        ReferenceError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        pass

    try:
        from .layer_sets import audit_layer_sets
        layer_set_result = audit_layer_sets(scene, repair=repair)
        repaired += int(layer_set_result.get("repaired", 0) or 0)
        for key, value in (layer_set_result.get("stats", {}) or {}).items():
            stats[key] += int(value or 0)
        for message in layer_set_result.get("issues", ()) or ():
            _append_unique(
                issues,
                _issue(
                    "ERROR",
                    "LAYER_SET",
                    message,
                    repair_hint="Open the file with the Frame By Plane version that created this Layer Set",
                ),
                seen,
            )
        for message in layer_set_result.get("warnings", ()) or ():
            _append_unique(
                issues,
                _issue(
                    "WARNING",
                    "LAYER_SET",
                    message,
                    repair_hint="Update the Layer Set or run Project Doctor Repair",
                ),
                seen,
            )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    try:
        from .visibility_snapshots import audit_visibility_snapshots

        snapshot_result = audit_visibility_snapshots(scene, repair=repair)
        repaired += int(snapshot_result.get("repaired", 0) or 0)
        for key, value in (snapshot_result.get("stats", {}) or {}).items():
            stats[key] += int(value or 0)
        for message in snapshot_result.get("issues", ()) or ():
            _append_unique(
                issues,
                _issue(
                    "ERROR",
                    "VISIBILITY_SNAPSHOT",
                    message,
                    repair_hint=(
                        "Open the file with the Frame By Plane version that "
                        "created this Visibility Snapshot"
                    ),
                ),
                seen,
            )
        for message in snapshot_result.get("warnings", ()) or ():
            _append_unique(
                issues,
                _issue(
                    "WARNING",
                    "VISIBILITY_SNAPSHOT",
                    message,
                    repair_hint=(
                        "Update the Visibility Snapshot or run "
                        "Project Doctor Repair"
                    ),
                ),
                seen,
            )
    except (
        ImportError,
        AttributeError,
        ReferenceError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        pass

    try:
        from .layer_filters import (
            audit_layer_filter_presets,
            repair_layer_filter_presets,
        )

        filter_issues = audit_layer_filter_presets(scene)
        stats["layer_filter_preset_issues"] += len(filter_issues)
        if repair:
            repaired += int(repair_layer_filter_presets(scene) or 0)
            filter_issues = audit_layer_filter_presets(scene)
        for issue in filter_issues:
            message = str(issue.get("message", "") or "")
            severity = str(issue.get("severity", "WARNING") or "WARNING")
            _append_unique(
                issues,
                _issue(
                    severity,
                    "LAYER_FILTER",
                    message,
                    repair_hint=(
                        "Rename the saved filter or run Project Doctor Repair"
                        if "newer schema" not in message
                        else (
                            "Open the file with the Frame By Plane version "
                            "that created this saved filter"
                        )
                    ),
                ),
                seen,
            )
    except (
        ImportError,
        AttributeError,
        ReferenceError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        pass

    try:
        from .mask_stack import audit_mask_sources

        mask_source_result = audit_mask_sources(scene, repair=repair)
        repaired += int(mask_source_result.get("repaired", 0) or 0)
        for key, value in (mask_source_result.get("stats", {}) or {}).items():
            stats[key] += int(value or 0)
        for message in mask_source_result.get("issues", ()) or ():
            _append_unique(
                issues,
                _issue(
                    "ERROR",
                    "MASK_SOURCE",
                    message,
                    repair_hint=(
                        "Open the file with the Frame By Plane version that "
                        "created this Mask Source"
                    ),
                ),
                seen,
            )
        for message in mask_source_result.get("warnings", ()) or ():
            _append_unique(
                issues,
                _issue(
                    "WARNING",
                    "MASK_SOURCE",
                    message,
                    repair_hint=(
                        "Update the Mask Source or run Project Doctor Repair"
                    ),
                ),
                seen,
            )
    except (
        ImportError,
        AttributeError,
        ReferenceError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        pass

    try:
        from .effect_stack_presets import audit_effect_stack_presets

        preset_result = audit_effect_stack_presets(scene, repair=repair)
        repaired += int(preset_result.get("repaired", 0) or 0)
        for key, value in (preset_result.get("stats", {}) or {}).items():
            stats[key] += int(value or 0)
        for message in preset_result.get("issues", ()) or ():
            _append_unique(
                issues,
                _issue(
                    "ERROR",
                    "EFFECT_STACK_PRESET",
                    message,
                    repair_hint=(
                        "Open the file with the Frame By Plane version that "
                        "created this Effect Stack Preset"
                    ),
                ),
                seen,
            )
        for message in preset_result.get("warnings", ()) or ():
            _append_unique(
                issues,
                _issue(
                    "WARNING",
                    "EFFECT_STACK_PRESET",
                    message,
                    repair_hint=(
                        "Update the Effect Stack Preset or run "
                        "Project Doctor Repair"
                    ),
                ),
                seen,
            )
    except (
        ImportError,
        AttributeError,
        ReferenceError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        pass

    try:
        from .grease_pencil_bridge import audit_gp_canvases
        gp_result = audit_gp_canvases(scene, repair=repair)
        repaired += int(gp_result.get("repaired", 0) or 0)
        for key, value in (gp_result.get("stats", {}) or {}).items():
            stats[key] += int(value or 0)
        for message in gp_result.get("issues", ()) or ():
            _append_unique(issues, _issue("ERROR", "GP_MASK", message, repair_hint="Refresh or recreate the Grease Pencil canvas"), seen)
        for message in gp_result.get("warnings", ()) or ():
            _append_unique(issues, _issue("WARNING", "GP_MASK", message, repair_hint="Refresh the Grease Pencil mask"), seen)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    try:
        from .grease_pencil_workflow import audit_gp_workflow
        workflow_result = audit_gp_workflow(scene, repair=repair)
        repaired += int(workflow_result.get("repaired", 0) or 0)
        for key, value in (workflow_result.get("stats", {}) or {}).items():
            stats[key] += int(value or 0)
        for message in workflow_result.get("issues", ()) or ():
            _append_unique(issues, _issue("ERROR", "GP_TIMING", message, repair_hint="Select the canvas and synchronize Drawing Timing"), seen)
        for message in workflow_result.get("warnings", ()) or ():
            _append_unique(issues, _issue("INFO", "GP_TIMING", message, repair_hint="Use Create Missing GP Drawings when explicit exposures are required"), seen)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    try:
        from .grease_pencil_limited_loop import audit_limited_loops
        loop_result = audit_limited_loops(scene, repair=repair)
        repaired += int(loop_result.get("repaired", 0) or 0)
        for key, value in (loop_result.get("stats", {}) or {}).items():
            stats[key] += int(value or 0)
        for message in loop_result.get("issues", ()) or ():
            _append_unique(issues, _issue("ERROR", "GP_LIMITED_LOOP", message, repair_hint="Rebuild or remove the Limited Loop"), seen)
        for message in loop_result.get("warnings", ()) or ():
            _append_unique(issues, _issue("WARNING", "GP_LIMITED_LOOP", message, repair_hint="Rebuild the Limited Loop or move unexpected keyframes"), seen)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    try:
        from .motion_runtime import audit_motion_system
        motion_result = audit_motion_system(scene, repair=repair)
        repaired += int(motion_result.get("repaired", 0) or 0)
        for key, value in (motion_result.get("stats", {}) or {}).items():
            stats[key] += int(value or 0)
        for message in motion_result.get("issues", ()) or ():
            object_name = str(message).split(":", 1)[0] if ":" in str(message) else ""
            _append_unique(issues, _issue("ERROR", "MOTION", message, object_name=object_name, repair_hint="Run Project Doctor Repair or recapture the Motion base transform"), seen)
        for message in motion_result.get("warnings", ()) or ():
            object_name = str(message).split(":", 1)[0] if ":" in str(message) else ""
            _append_unique(issues, _issue("WARNING", "MOTION", message, object_name=object_name), seen)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    # Validate the complete effect registry before inspecting scene instances.
    # These are build-level contract errors: missing media support, stale UI
    # properties or malformed definitions otherwise remain invisible until the
    # affected effect is added by a user.
    try:
        from .effects_registry import FBP_EFFECT_REGISTRY_ISSUES
        from .geometry_nodes import FBP_EFFECT_SETTINGS_UI_ISSUES
        registry_issues = tuple(FBP_EFFECT_REGISTRY_ISSUES or ())
        ui_issues = tuple(FBP_EFFECT_SETTINGS_UI_ISSUES or ())
        stats["effect_registry_issues"] += len(registry_issues)
        stats["effect_ui_contract_issues"] += len(ui_issues)
        for message in registry_issues:
            _append_unique(issues, _issue("ERROR", "EFFECT_REGISTRY", message, repair_hint="Update or reinstall Frame By Plane"), seen)
        for message in ui_issues:
            _append_unique(issues, _issue("ERROR", "EFFECT_UI_CONTRACT", message, repair_hint="Update or reinstall Frame By Plane"), seen)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    try:
        from .object_masks import audit_object_masks
        mask_result = audit_object_masks(scene, repair=False)
        for key, value in (mask_result.get("stats", {}) or {}).items():
            stats[key] += int(value or 0)
        for message in mask_result.get("issues", ()) or ():
            _append_unique(issues, _issue("ERROR", "MASK", message, repair_hint="Run Shape Mask repair"), seen)
        for message in mask_result.get("warnings", ()) or ():
            _append_unique(issues, _issue("WARNING", "MASK", message), seen)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    # Duplicate image wrappers waste memory and make future source refresh
    # ambiguous. Only report images that resolve to the same existing path.
    wrappers = defaultdict(list)
    try:
        for image in tuple(bpy.data.images):
            path = _safe_image_path(image)
            source_type = str(getattr(image, "source", "FILE") or "FILE")
            if path and os.path.isfile(path):
                wrappers[(path, source_type)].append(image)
    except FBP_DATA_ERRORS:
        wrappers = {}
    for (path, source_type), images in wrappers.items():
        if len(images) <= 1:
            continue
        stats["duplicate_image_wrappers"] += len(images) - 1
        names = ", ".join(str(getattr(image, "name", "<image>")) for image in images[:4])
        _append_unique(issues, _issue("WARNING", "DUPLICATE_IMAGE", f"Multiple {source_type.title()} image datablocks reference the same source: {names}", data_name=path), seen)

    # Validate the versioned Layer Node contract only when the preview has
    # actually been built. This is read-only: future schemas are never rebuilt
    # or downgraded by Project Doctor.
    try:
        from .compositor import (
            FBP_COMPOSITOR_LAYER_NODE_SCHEMA_KEY,
            fbp_compositor_layer_node_schema_status,
        )
        from .compositor_layer_node import audit_compositor_layer_node

        compositor_schema = fbp_compositor_layer_node_schema_status(scene)
        has_layer_node_state = bool(
            getattr(scene, "fbp_compositor_enabled", False)
            or FBP_COMPOSITOR_LAYER_NODE_SCHEMA_KEY in scene
        )
        if has_layer_node_state and compositor_schema["unsupported_future"]:
            stats["invalid_compositor_refs"] += 1
            _append_unique(
                issues,
                _issue(
                    "ERROR",
                    "COMPOSITOR_LAYER_NODE",
                    (
                        "Compositor Layer Node schema "
                        f"v{compositor_schema['stored']} is newer than "
                        f"supported v{compositor_schema['current']}"
                    ),
                    repair_hint="Open the project with the matching Frame By Plane version",
                ),
                seen,
            )
        elif has_layer_node_state:
            compositor_audit = audit_compositor_layer_node(scene)
            for message in compositor_audit.get("issues", ()):
                stats["invalid_compositor_refs"] += 1
                _append_unique(
                    issues,
                    _issue(
                        "ERROR",
                        "COMPOSITOR_LAYER_NODE",
                        str(message),
                        repair_hint="Run Sync Prototype from Compositor Layers",
                    ),
                    seen,
                )
            for message in compositor_audit.get("warnings", ()):
                _append_unique(
                    issues,
                    _issue(
                        "WARNING",
                        "COMPOSITOR_LAYER_NODE",
                        str(message),
                    ),
                    seen,
                )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    # Validate only FBP-owned compositor references. User nodes are never
    # interpreted as broken merely because their topology is custom.
    try:
        tree = getattr(scene, "node_tree", None)
        if bool(getattr(scene, "use_nodes", False)) and tree is not None:
            fbp_groups = [node for node in tree.nodes if bool(node.get("fbp_compositor_group", False))]
            for node in fbp_groups:
                if getattr(node, "node_tree", None) is None:
                    stats["invalid_compositor_refs"] += 1
                    _append_unique(issues, _issue("ERROR", "COMPOSITOR", "FBP compositor node has no node group", data_name=getattr(node, "name", ""), repair_hint="Rebuild only the FBP compositor group"), seen)
    except FBP_DATA_ERRORS:
        pass

    issues.sort(key=lambda item: (SEVERITY_ORDER.get(item["severity"], 3), item["code"], item["object_name"], item["message"]))
    stats["errors"] = sum(1 for item in issues if item["severity"] == "ERROR")
    stats["warnings"] = sum(1 for item in issues if item["severity"] == "WARNING")
    stats["info"] = sum(1 for item in issues if item["severity"] == "INFO")
    stats["issues"] = len(issues)
    _populate_scene_issues(scene, issues)
    return {"issues": tuple(issues), "stats": dict(stats), "repaired": repaired}


def health_report_lines(scene, result, *, repair=False):
    stats = dict(result.get("stats", {}) or {})
    issues = tuple(result.get("issues", ()) or ())
    lines = [
        "Frame By Plane — Project Doctor",
        "================================",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Scene: {getattr(scene, 'name', '<none>')}",
        f"Repair requested: {'Yes' if repair else 'No'}",
        "",
        "Summary",
        "-------",
    ]
    lines.extend(
        f"{key.replace('_', ' ').title()}: {stats[key]}"
        for key in sorted(stats)
    )
    lines.extend(("", "Issues", "------"))
    if not issues:
        lines.append("- None")
    else:
        for item in issues:
            location = item.get("object_name") or item.get("data_name")
            suffix = f" [{location}]" if location else ""
            lines.append(f"- {item['severity']} · {item['code']}: {item['message']}{suffix}")
            if item.get("repair_hint"):
                lines.append(f"  Repair: {item['repair_hint']}")
            try:
                from .actionable_issues import project_doctor_action_metadata

                action = project_doctor_action_metadata(item)
            except ImportError:
                action = {}
            if action.get("fix_action"):
                lines.append(
                    f"  Action: {action.get('fix_label', 'Fix Issue')}"
                )
    lines.extend(("", "Result", "------"))
    lines.append("REVIEW REQUIRED" if stats.get("errors", 0) else ("WARNING" if stats.get("warnings", 0) else "PASS"))
    return lines


class FBP_UL_ProjectDoctorIssues(UIList):
    """Compact searchable issue list for the Output Properties panel."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        mark_ui_list_draw()
        severity = str(getattr(item, 'severity', 'INFO') or 'INFO').upper()
        if self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text='', icon=SEVERITY_ICONS.get(severity, 'DOT'))
            return
        code = str(getattr(item, 'code', 'GENERAL') or 'GENERAL').replace('_', ' ').title()
        location = str(getattr(item, 'object_name', '') or getattr(item, 'data_name', '') or '')
        row = layout.row(align=True)
        visible = set(fbp_uilist_visible_columns(context, 'PROJECT_DOCTOR'))
        for key in fbp_uilist_icon_order(context, 'PROJECT_DOCTOR'):
            if key not in visible:
                continue
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(row)
                continue
            if key == 'doctor_severity':
                row.label(text='', icon=SEVERITY_ICONS.get(severity, 'DOT'))
            elif key == 'label':
                body = row.row(align=True)
                body.label(text=code)
                if location:
                    body.label(text=location, icon='OBJECT_DATA')
            elif key == 'doctor_fix' and str(getattr(item, 'fix_action', '') or ''):
                fix = row.operator('fbp.fix_project_health_issue', text='', icon='TOOL_SETTINGS', emboss=False)
                fix.index = int(index)
            elif key == 'doctor_select' and location:
                op = row.operator('fbp.select_project_health_issue', text='', icon='RESTRICT_SELECT_OFF', emboss=False)
                op.index = int(index)
                op.cycle = False

    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        try:
            items = getattr(data, propname)
            scene = context.scene
            severity_filter = str(getattr(scene, "fbp_health_filter", "ALL") or "ALL").upper()
            query = str(scene.get("fbp_uilist_filter_project_doctor", "") or "").strip().casefold()
            alphabetical = bool(scene.get("fbp_uilist_sort_project_doctor", False))
            reverse = bool(scene.get("fbp_uilist_reverse_project_doctor", False))
        except FBP_DATA_ERRORS:
            return [], []
        flags = []
        for item in items:
            try:
                severity = str(getattr(item, "severity", "INFO") or "INFO").upper()
                haystack = " ".join((
                    str(getattr(item, "code", "") or ""),
                    str(getattr(item, "message", "") or ""),
                    str(getattr(item, "object_name", "") or ""),
                    str(getattr(item, "data_name", "") or ""),
                    str(getattr(item, "repair_hint", "") or ""),
                    str(getattr(item, "fix_label", "") or ""),
                    str(getattr(item, "fix_description", "") or ""),
                )).casefold()
                fixable = bool(str(getattr(item, "fix_action", "") or ""))
                visible = (
                    (
                        severity_filter == "ALL"
                        or severity == severity_filter
                        or (severity_filter == "FIXABLE" and fixable)
                    )
                    and (not query or query in haystack)
                )
            except FBP_DATA_ERRORS:
                visible = False
            flags.append(self.bitflag_filter_item if visible else 0)
        order = list(range(len(items)))
        if alphabetical:
            order.sort(key=lambda i: (
                SEVERITY_ORDER.get(str(getattr(items[i], "severity", "INFO") or "INFO").upper(), 99),
                str(getattr(items[i], "code", "") or "").casefold(),
            ))
        if reverse:
            order.reverse()
        return flags, order if order != list(range(len(items))) else []


class FBP_OT_ClearProjectDoctorResults(Operator):
    bl_idname = "fbp.clear_project_doctor_results"
    bl_label = "Clear Project Doctor Results"
    bl_description = "Clear the current Project Doctor issue list without changing project data"

    def execute(self, context):
        scene = context.scene
        try:
            scene.fbp_health_issues.clear()
            scene.fbp_health_issue_index = -1
            scene.fbp_health_last_status = "NOT_RUN"
            scene.fbp_health_last_run = ""
            scene.fbp_health_last_summary = ""
        except FBP_DATA_ERRORS as exc:
            self.report({"WARNING"}, f"Could not clear Project Doctor results: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, "Project Doctor results cleared")
        return {"FINISHED"}


class FBP_OT_SelectProjectHealthIssue(Operator):
    bl_idname = "fbp.select_project_health_issue"
    bl_label = "Select Project Doctor Problem"
    bl_description = (
        "Select the next Blender object associated with a Project Doctor issue; "
        "repeat to cycle through selectable problems"
    )

    index: IntProperty(description='Zero-based item index used internally to target the selected row, frame, effect, preset or setup entry.', name="Issue Index", default=-1, options={"SKIP_SAVE"})
    cycle: BoolProperty(
        name="Cycle Problems",
        description="Advance to the next issue linked to a Blender object",
        default=True,
        options={"SKIP_SAVE"},
    )

    @staticmethod
    def _selectable_issue(scene, requested_index, cycle):
        try:
            issues = scene.fbp_health_issues
            count = len(issues)
        except FBP_DATA_ERRORS:
            return -1, None
        if count <= 0:
            return -1, None
        if requested_index >= 0:
            indices = (requested_index,)
        else:
            current = int(getattr(scene, "fbp_health_issue_index", -1))
            start = (current + 1) % count if cycle else max(0, current)
            indices = tuple((start + offset) % count for offset in range(count))
        for index in indices:
            try:
                item = issues[index]
                object_name = str(getattr(item, "object_name", "") or "")
            except (IndexError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
            if object_name and scene.objects.get(object_name) is not None:
                return index, item
        return -1, None

    def execute(self, context):
        scene = context.scene
        index, item = self._selectable_issue(scene, self.index, self.cycle)
        if item is None:
            self.report({'WARNING'}, "No Project Doctor issue is linked to a selectable object")
            return {'CANCELLED'}
        obj = scene.objects.get(str(item.object_name or ""))
        if obj is None:
            self.report({'WARNING'}, "This Project Doctor object no longer exists")
            return {'CANCELLED'}
        try:
            if context.mode != 'OBJECT' and bpy.ops.object.mode_set.poll():
                bpy.ops.object.mode_set(mode='OBJECT')
            for candidate in context.selected_objects:
                candidate.select_set(False)
            obj.hide_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            scene.fbp_health_issue_index = index
        except FBP_DATA_ERRORS as exc:
            self.report({'ERROR'}, f"Could not select {obj.name}: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"{item.severity} · {item.code}: {item.message}")
        return {'FINISHED'}


_CLASSES = (
    FBP_ProjectHealthIssue,
    FBP_UL_ProjectDoctorIssues,
    FBP_OT_ClearProjectDoctorResults,
    FBP_OT_SelectProjectHealthIssue,
)


_SCENE_PROPERTIES = (
    "fbp_health_issues",
    "fbp_health_issue_index",
    "fbp_health_last_status",
    "fbp_health_last_run",
    "fbp_health_last_summary",
    "fbp_health_filter",
    "fbp_health_search",
)


def _remove_scene_properties():
    return unregister_type_properties(bpy.types.Scene, _SCENE_PROPERTIES)


def register():
    register_classes(_CLASSES)
    try:
        bpy.types.Scene.fbp_health_issues = CollectionProperty(description='Internal collection of Project Doctor issues managed by Frame By Plane.', type=FBP_ProjectHealthIssue)
        bpy.types.Scene.fbp_health_issue_index = IntProperty(description='Active Project Doctor issue index.', name="Doctor Issue", default=-1)
        bpy.types.Scene.fbp_health_last_status = StringProperty(description='Last Project Doctor result.', name="Project Doctor Status", default="NOT_RUN")
        bpy.types.Scene.fbp_health_last_run = StringProperty(description='Timestamp of the latest Project Doctor scan.', name="Last Doctor Scan", default="")
        bpy.types.Scene.fbp_health_last_summary = StringProperty(description='Summary of the latest Project Doctor scan.', name="Doctor Summary", default="")
        bpy.types.Scene.fbp_health_filter = EnumProperty(
            name="Severity",
            description="Filter Project Doctor issues by severity",
            items=(
                ("ALL", "All", "Show every issue"),
                ("ERROR", "Errors", "Show errors only"),
                ("WARNING", "Warnings", "Show warnings only"),
                ("INFO", "Info", "Show informational items only"),
                (
                    "FIXABLE",
                    "Fixable",
                    "Show only issues with a whitelisted safe action",
                ),
            ),
            default="ALL",
        )
        bpy.types.Scene.fbp_health_search = StringProperty(
            name="Search",
            description="Search Project Doctor codes, messages, objects and repair hints",
            default="",
            options={"TEXTEDIT_UPDATE"},
        )
    except Exception:
        _remove_scene_properties()
        unregister_classes(_CLASSES)
        raise


def unregister():
    _remove_scene_properties()
    unregister_classes(_CLASSES)


__all__ = (
    "REPORT_NAME",
    "scan_project_health",
    "health_report_lines",
    "project_doctor_counts",
    "active_project_doctor_issue",
    "FBP_UL_ProjectDoctorIssues",
    "FBP_OT_ClearProjectDoctorResults",
    "FBP_OT_SelectProjectHealthIssue",
)
