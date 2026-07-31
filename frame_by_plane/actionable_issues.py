"""Whitelisted Project Doctor actions, navigation and post-fix verification."""

from __future__ import annotations

import os

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from .registration import (
    register_interactive_classes,
    unregister_classes,
)
from .runtime import FBP_DATA_ERRORS


PROJECT_DOCTOR_ACTION_SCHEMA_VERSION = 1

_ACTION_SPECS = {
    "MATCH_RENDER_VISIBILITY": (
        "Match Render Visibility",
        "Disable render visibility for the layer that is already hidden in the viewport.",
        "RESTRICT_RENDER_ON",
    ),
    "EXTEND_SCENE_RANGE": (
        "Extend Scene Range",
        "Expand the Scene start/end so this layer timing is inside the render range.",
        "PREVIEW_RANGE",
    ),
    "ENABLE_TEXTURE_CACHE": (
        "Enable Texture Cache",
        "Enable Blender 5.2 Cycles texture caching for this image-heavy scene.",
        "TEXTURE",
    ),
    "SET_TRANSPARENT_BOUNCES": (
        "Set Recommended Bounces",
        "Raise Cycles Transparent Max Bounces to the current FBP recommendation.",
        "LIGHT",
    ),
    "REPAIR_MASK_STACK": (
        "Repair Mask Stack",
        "Remove invalid/stale operation metadata without deleting mask effects.",
        "MOD_MASK",
    ),
    "REPAIR_MASK_SOURCES": (
        "Repair Mask Sources",
        "Canonicalize supported sources and rename empty or duplicate names.",
        "ASSET_MANAGER",
    ),
    "REPAIR_EFFECT_PRESETS": (
        "Repair Effect Presets",
        "Canonicalize supported presets and rename empty or duplicate names.",
        "PRESET",
    ),
    "REPAIR_LAYER_FILTERS": (
        "Repair Saved Filters",
        "Rename empty or duplicate saved filters without changing their criteria.",
        "FILTER",
    ),
    "REPAIR_VISIBILITY_SNAPSHOTS": (
        "Remove Stale States",
        "Remove missing or duplicate snapshot references without changing live layers.",
        "HIDE_OFF",
    ),
    "REPAIR_LAYER_SETS": (
        "Remove Stale Members",
        "Remove missing or duplicate Layer Set references without changing live layers.",
        "RESTRICT_SELECT_OFF",
    ),
    "REPAIR_IDENTITIES": (
        "Repair Stable IDs",
        "Create missing IDs and replace duplicates used by saved layer references.",
        "FILE_REFRESH",
    ),
    "REPAIR_OWNERSHIP": (
        "Repair Ownership",
        "Reconcile Frame By Plane ownership metadata for generated datablocks.",
        "LINKED",
    ),
    "REPAIR_EFFECT_ASSET": (
        "Rebuild Effect",
        "Re-inject the missing owned effect node group while preserving settings and animation.",
        "NODETREE",
    ),
    "REPAIR_LOCAL_MASK": (
        "Repair Mask Routing",
        "Rebuild invalid local effect-mask routing without removing the effects.",
        "NODE_INSERT_ON",
    ),
    "REPAIR_NATIVE_CACHE": (
        "Repair Media Cache",
        "Reconcile Frame By Plane native media-cache ownership and stale entries.",
        "FILE_REFRESH",
    ),
    "REPAIR_GP_MASK": (
        "Repair GP Mask",
        "Refresh supported Grease Pencil canvas/mask metadata and generated links.",
        "OUTLINER_OB_GREASEPENCIL",
    ),
    "REPAIR_GP_TIMING": (
        "Synchronize GP Timing",
        "Repair supported Grease Pencil drawing/exposure timing metadata.",
        "TIME",
    ),
    "REPAIR_GP_LOOP": (
        "Repair GP Loop",
        "Reconcile supported Limited Loop metadata and generated timing.",
        "FILE_REFRESH",
    ),
    "REPAIR_MOTION": (
        "Repair Motion",
        "Reconcile supported Motion metadata and base-transform records.",
        "CON_TRANSLIKE",
    ),
    "REPAIR_SHAPE_MASK": (
        "Repair Shape Mask",
        "Rebuild supported object-mask helpers and ownership contracts.",
        "MOD_MASK",
    ),
    "RECOVER_TRANSACTION": (
        "Recover Operation",
        "Roll back or reconcile the persisted journal from an interrupted FBP operation.",
        "RECOVER_LAST",
    ),
}


def _text(value):
    try:
        return str(value or "")
    except FBP_DATA_ERRORS:
        return ""


def _issue_dict(issue):
    if isinstance(issue, dict):
        source = issue
        getter = source.get
    else:
        getter = lambda key, default="": getattr(issue, key, default)
    return {
        "severity": _text(getter("severity", "INFO")).upper(),
        "code": _text(getter("code", "GENERAL")).upper(),
        "message": _text(getter("message", "")),
        "object_name": _text(getter("object_name", "")),
        "data_name": _text(getter("data_name", "")),
        "repair_hint": _text(getter("repair_hint", "")),
    }


def _fix_action_for_issue(issue):
    code = issue["code"]
    message = issue["message"].casefold()
    if code == "HIDDEN_RENDER":
        return "MATCH_RENDER_VISIBILITY"
    if code == "FRAME_RANGE":
        return "EXTEND_SCENE_RANGE"
    if code == "CYCLES_TEXTURE_CACHE":
        return "ENABLE_TEXTURE_CACHE"
    if code == "CYCLES_TRANSPARENCY_DEPTH":
        return "SET_TRANSPARENT_BOUNCES"
    if code == "MASK_STACK":
        return "REPAIR_MASK_STACK"
    if code == "MASK_SOURCE":
        return (
            "REPAIR_MASK_SOURCES"
            if "empty or duplicate name" in message
            else ""
        )
    if code == "EFFECT_STACK_PRESET":
        return (
            "REPAIR_EFFECT_PRESETS"
            if "empty or duplicate name" in message
            else ""
        )
    if code == "LAYER_FILTER":
        return (
            "REPAIR_LAYER_FILTERS"
            if "no name" in message or "duplicate" in message
            else ""
        )
    if code == "VISIBILITY_SNAPSHOT":
        return (
            "REPAIR_VISIBILITY_SNAPSHOTS"
            if "state reference" in message
            else ""
        )
    if code == "LAYER_SET":
        return "REPAIR_LAYER_SETS" if "member reference" in message else ""
    if code == "IDENTITY":
        return "REPAIR_IDENTITIES"
    if code == "OWNERSHIP":
        return "REPAIR_OWNERSHIP"
    if code == "MISSING_EFFECT_GROUP":
        return "REPAIR_EFFECT_ASSET"
    if code == "MASK_TARGET":
        return "REPAIR_LOCAL_MASK"
    if code == "NATIVE_CACHE":
        return "REPAIR_NATIVE_CACHE"
    if code == "GP_MASK":
        return "REPAIR_GP_MASK"
    if code == "GP_TIMING":
        return "REPAIR_GP_TIMING"
    if code == "GP_LIMITED_LOOP":
        return "REPAIR_GP_LOOP"
    if code == "MOTION":
        return "REPAIR_MOTION"
    if code == "MASK":
        return "REPAIR_SHAPE_MASK"
    if code == "PENDING_TRANSACTION":
        return "RECOVER_TRANSACTION"
    return ""


def _navigation_for_issue(issue):
    if issue["object_name"]:
        return {
            "navigation_action": "SELECT_OBJECT",
            "navigation_label": "Select Layer",
        }
    data_name = issue["data_name"]
    if data_name and (
        os.path.isabs(data_name)
        or "/" in data_name
        or "\\" in data_name
    ):
        return {
            "navigation_action": "REVEAL_PATH",
            "navigation_label": "Reveal Source",
        }
    if data_name and (
        bpy.data.texts.get(data_name) is not None
        or bpy.data.images.get(data_name) is not None
    ):
        return {
            "navigation_action": "OPEN_DATABLOCK",
            "navigation_label": "Open Data",
        }
    return {"navigation_action": "", "navigation_label": ""}


def project_doctor_action_metadata(issue):
    """Return conservative, versioned actions for one diagnostic."""
    issue = _issue_dict(issue)
    action_id = _fix_action_for_issue(issue)
    label = ""
    description = ""
    icon = ""
    if action_id:
        label, description, icon = _ACTION_SPECS[action_id]
    result = {
        "action_schema": PROJECT_DOCTOR_ACTION_SCHEMA_VERSION,
        "fix_action": action_id,
        "fix_label": label,
        "fix_description": description,
        "fix_icon": icon,
    }
    result.update(_navigation_for_issue(issue))
    return result


def _rig(scene, issue):
    name = issue.get("object_name", "")
    try:
        return scene.objects.get(name) if name else None
    except FBP_DATA_ERRORS:
        return None


def _repaired_count(result):
    if isinstance(result, dict):
        return int(result.get("repaired", 0) or 0)
    if isinstance(result, bool):
        return int(result)
    try:
        return int(result or 0)
    except (TypeError, ValueError):
        return 0


def execute_project_doctor_action(scene, issue, action_id=""):
    """Execute one whitelisted repair and return a primitive outcome."""
    issue = _issue_dict(issue)
    metadata = project_doctor_action_metadata(issue)
    expected = metadata["fix_action"]
    action_id = _text(action_id or expected).upper()
    if not expected or action_id != expected or action_id not in _ACTION_SPECS:
        return {
            "success": False,
            "changed": 0,
            "message": "This issue has no safe automatic fix",
        }
    rig = _rig(scene, issue)
    changed = 0
    try:
        if action_id == "MATCH_RENDER_VISIBILITY":
            if rig is None:
                raise ValueError("The affected layer no longer exists")
            before = bool(rig.hide_render)
            rig.hide_render = True
            changed = int(before != bool(rig.hide_render))
        elif action_id == "EXTEND_SCENE_RANGE":
            if rig is None:
                raise ValueError("The affected layer no longer exists")
            start = int(
                getattr(rig, "fbp_start_frame", scene.frame_start)
                or scene.frame_start
            )
            durations = [
                max(1, int(getattr(item, "duration", 1) or 1))
                for item in tuple(getattr(rig, "fbp_images", ()) or ())
            ]
            end = start + max(1, sum(durations)) - 1
            old = (int(scene.frame_start), int(scene.frame_end))
            scene.frame_start = min(old[0], start)
            scene.frame_end = max(old[1], end)
            changed = int(old != (int(scene.frame_start), int(scene.frame_end)))
        elif action_id == "ENABLE_TEXTURE_CACHE":
            render = scene.render
            if not hasattr(render, "use_texture_cache"):
                raise ValueError("Texture Cache is unavailable in this runtime")
            before = bool(render.use_texture_cache)
            render.use_texture_cache = True
            changed = int(before != bool(render.use_texture_cache))
        elif action_id == "SET_TRANSPARENT_BOUNCES":
            from .core import _fbp_cycles_recommended_transparent_bounces

            recommended, _surfaces = (
                _fbp_cycles_recommended_transparent_bounces(scene)
            )
            cycles = getattr(scene, "cycles", None)
            if cycles is None:
                raise ValueError("Cycles settings are unavailable")
            before = int(cycles.transparent_max_bounces)
            cycles.transparent_max_bounces = max(before, int(recommended))
            changed = int(before != int(cycles.transparent_max_bounces))
        elif action_id == "REPAIR_MASK_STACK":
            from .geometry_nodes import audit_mask_stack_rig

            if rig is None:
                raise ValueError("The affected layer no longer exists")
            changed = _repaired_count(audit_mask_stack_rig(rig, repair=True))
        elif action_id == "REPAIR_MASK_SOURCES":
            from .mask_stack import audit_mask_sources

            changed = _repaired_count(audit_mask_sources(scene, repair=True))
        elif action_id == "REPAIR_EFFECT_PRESETS":
            from .effect_stack_presets import audit_effect_stack_presets

            changed = _repaired_count(
                audit_effect_stack_presets(scene, repair=True)
            )
        elif action_id == "REPAIR_LAYER_FILTERS":
            from .layer_filters import repair_layer_filter_presets

            changed = int(repair_layer_filter_presets(scene) or 0)
        elif action_id == "REPAIR_VISIBILITY_SNAPSHOTS":
            from .visibility_snapshots import audit_visibility_snapshots

            changed = _repaired_count(
                audit_visibility_snapshots(scene, repair=True)
            )
        elif action_id == "REPAIR_LAYER_SETS":
            from .layer_sets import audit_layer_sets

            changed = _repaired_count(audit_layer_sets(scene, repair=True))
        elif action_id == "REPAIR_IDENTITIES":
            from .identifiers import repair_scene_identities

            result = repair_scene_identities(
                scene,
                repair_duplicates=True,
                create_missing=True,
            )
            changed = sum(
                int(value or 0)
                for key, value in dict(result.get("stats", {}) or {}).items()
                if key.endswith(("_created", "_repaired"))
            )
        elif action_id == "REPAIR_OWNERSHIP":
            from .ownership import audit_scene_ownership

            changed = _repaired_count(
                audit_scene_ownership(scene, repair=True)
            )
        elif action_id == "REPAIR_EFFECT_ASSET":
            from .geometry_nodes import fbp_repair_effect_assets

            if rig is None:
                raise ValueError("The affected layer no longer exists")
            effect_id = issue["message"].split(" ", 1)[0].strip().upper()
            changed = int(
                fbp_repair_effect_assets(rig, effect_ids=(effect_id,))
            )
        elif action_id == "REPAIR_LOCAL_MASK":
            from .geometry_nodes import fbp_local_effect_mask_contract_report

            if rig is None:
                raise ValueError("The affected layer no longer exists")
            changed = _repaired_count(
                fbp_local_effect_mask_contract_report(rig, repair=True)
            )
        elif action_id == "REPAIR_NATIVE_CACHE":
            from .native_backend import fbp_native_media_cache_report

            changed = _repaired_count(
                fbp_native_media_cache_report(repair=True)
            )
        elif action_id == "REPAIR_GP_MASK":
            from .grease_pencil_bridge import audit_gp_canvases

            changed = _repaired_count(audit_gp_canvases(scene, repair=True))
        elif action_id == "REPAIR_GP_TIMING":
            from .grease_pencil_workflow import audit_gp_workflow

            changed = _repaired_count(audit_gp_workflow(scene, repair=True))
        elif action_id == "REPAIR_GP_LOOP":
            from .grease_pencil_limited_loop import audit_limited_loops

            changed = _repaired_count(audit_limited_loops(scene, repair=True))
        elif action_id == "REPAIR_MOTION":
            from .motion_runtime import audit_motion_system

            changed = _repaired_count(audit_motion_system(scene, repair=True))
        elif action_id == "REPAIR_SHAPE_MASK":
            from .layers import iter_scene_fbp_rigs
            from .object_masks import audit_object_masks

            changed = _repaired_count(
                audit_object_masks(
                    tuple(iter_scene_fbp_rigs(scene, fallback=True)),
                    repair=True,
                    context=bpy.context,
                )
            )
        elif action_id == "RECOVER_TRANSACTION":
            from .transactions import recover_transaction_journal

            candidates = [scene]
            candidates.extend(tuple(getattr(scene, "objects", ()) or ()))
            candidates.extend(tuple(getattr(bpy.data, "collections", ()) or ()))
            owner_name = issue["object_name"] or issue["data_name"]
            owner = next(
                (
                    candidate
                    for candidate in candidates
                    if _text(getattr(candidate, "name", "")) == owner_name
                ),
                scene if not owner_name else None,
            )
            if owner is None:
                raise ValueError("The interrupted-operation owner is missing")
            changed = int(bool(recover_transaction_journal(owner)))
        return {
            "success": True,
            "changed": int(changed),
            "message": (
                f"{_ACTION_SPECS[action_id][0]} completed"
                + (f" ({changed} change(s))" if changed else "")
            ),
        }
    except (
        ImportError,
        AttributeError,
        IndexError,
        ReferenceError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        return {
            "success": False,
            "changed": int(changed),
            "message": f"{type(exc).__name__}: {exc}",
        }


def _issue_signature(issue):
    issue = _issue_dict(issue)
    return (
        issue["code"],
        issue["message"],
        issue["object_name"],
        issue["data_name"],
    )


class FBP_OT_FixProjectHealthIssue(Operator):
    bl_idname = "fbp.fix_project_health_issue"
    bl_label = "Fix Project Doctor Issue"
    bl_description = "Run the whitelisted reversible action for this issue"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        scene = context.scene
        try:
            issue = scene.fbp_health_issues[int(self.index)]
        except (IndexError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            self.report({"WARNING"}, "The Project Doctor issue no longer exists")
            return {"CANCELLED"}
        captured = _issue_dict(issue)
        action_id = project_doctor_action_metadata(captured)["fix_action"]
        outcome = execute_project_doctor_action(scene, captured, action_id)
        if not outcome["success"]:
            self.report({"ERROR"}, outcome["message"])
            return {"FINISHED"} if outcome["changed"] else {"CANCELLED"}

        from .project_health import scan_project_health

        result = scan_project_health(scene, repair=False)
        signature = _issue_signature(captured)
        remains = any(
            _issue_signature(item) == signature
            for item in result.get("issues", ())
        )
        if remains:
            self.report(
                {"WARNING"},
                outcome["message"] + "; the issue still needs review",
            )
            return {"FINISHED"} if outcome["changed"] else {"CANCELLED"}
        self.report({"INFO"}, outcome["message"] + "; verified")
        return {"FINISHED"}


def _nearest_existing_directory(path):
    path = os.path.abspath(path)
    candidate = path if os.path.isdir(path) else os.path.dirname(path)
    while candidate and not os.path.isdir(candidate):
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    return candidate if os.path.isdir(candidate) else ""


class FBP_OT_NavigateProjectHealthIssue(Operator):
    bl_idname = "fbp.navigate_project_health_issue"
    bl_label = "Navigate to Project Doctor Issue"
    bl_description = "Select the affected layer or open the associated data/source"
    bl_options = {"REGISTER"}

    index: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        scene = context.scene
        try:
            issue = scene.fbp_health_issues[int(self.index)]
        except (IndexError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return {"CANCELLED"}
        captured = _issue_dict(issue)
        navigation = project_doctor_action_metadata(captured)[
            "navigation_action"
        ]
        if navigation == "SELECT_OBJECT":
            result = bpy.ops.fbp.select_project_health_issue(
                "EXEC_DEFAULT",
                index=int(self.index),
                cycle=False,
            )
            return {"FINISHED"} if "FINISHED" in set(result) else {"CANCELLED"}
        if navigation == "REVEAL_PATH":
            directory = _nearest_existing_directory(captured["data_name"])
            if not directory:
                self.report({"WARNING"}, "No existing parent folder was found")
                return {"CANCELLED"}
            result = bpy.ops.wm.path_open(filepath=directory)
            return {"FINISHED"} if "FINISHED" in set(result) else {"CANCELLED"}
        if navigation == "OPEN_DATABLOCK":
            name = captured["data_name"]
            area = getattr(context, "area", None)
            text = bpy.data.texts.get(name)
            image = bpy.data.images.get(name)
            if area is not None and text is not None:
                area.type = "TEXT_EDITOR"
                area.spaces.active.text = text
                return {"FINISHED"}
            if area is not None and image is not None:
                area.type = "IMAGE_EDITOR"
                area.spaces.active.image = image
                return {"FINISHED"}
        self.report({"WARNING"}, "No direct navigation is available")
        return {"CANCELLED"}


_interactive_classes = (
    FBP_OT_FixProjectHealthIssue,
    FBP_OT_NavigateProjectHealthIssue,
)
_registered_classes = globals().get("_registered_classes", [])
if not isinstance(_registered_classes, list):
    _registered_classes = []


def register():
    _registered_classes.clear()
    _registered_classes.extend(
        register_interactive_classes(_interactive_classes)
    )


def unregister():
    unregister_classes(tuple(_registered_classes))
    _registered_classes.clear()


__all__ = [
    "PROJECT_DOCTOR_ACTION_SCHEMA_VERSION",
    "execute_project_doctor_action",
    "project_doctor_action_metadata",
]
