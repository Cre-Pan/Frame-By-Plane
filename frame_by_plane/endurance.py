"""Interactive Undo/Redo endurance diagnostics for Frame By Plane.

The audit is deliberately baseline-assisted instead of attempting to drive
Blender's Undo stack from Python. The user captures a semantic project state,
performs real Undo/Redo operations in the UI, returns to the captured state and
then verifies that layers, effects, masks, animation and Lattice data match.
"""

from __future__ import annotations

from datetime import datetime

import bpy
from bpy.props import EnumProperty, IntProperty
from bpy.types import Operator

from .constants import FBP_VERSION_STRING
from .diagnostics import write_diagnostic_report
from .persistence import (
    _fbp_build_persistence_contract,
    _fbp_persistence_diff,
    _fbp_persistence_digest,
)
from .runtime import FBP_DATA_ERRORS
from .scene_sync import sync_layer_collection


# Module globals intentionally survive a normal in-place module reload. They do
# not retain RNA pointers: scene names, counters and JSON-like contracts only.
_FBP_HISTORY_COUNTS = globals().get(
    "_FBP_HISTORY_COUNTS", {"undo": 0, "redo": 0, "generation": 0}
)
if not isinstance(_FBP_HISTORY_COUNTS, dict):
    _FBP_HISTORY_COUNTS = {"undo": 0, "redo": 0, "generation": 0}

_FBP_UNDO_BASELINES = globals().get("_FBP_UNDO_BASELINES", {})
if not isinstance(_FBP_UNDO_BASELINES, dict):
    _FBP_UNDO_BASELINES = {}


_STATUS_NOT_CAPTURED = "NOT_CAPTURED"
_STATUS_CAPTURED = "CAPTURED"
_STATUS_PASS = "PASS"
_STATUS_FAIL = "FAIL"


def _scene_key(scene):
    if scene is None:
        return ""
    try:
        return str(getattr(scene, "name_full", "") or getattr(scene, "name", "") or "")
    except FBP_DATA_ERRORS:
        return ""


def fbp_note_undo_event(scene=None):
    """Record one completed Blender Undo event without touching scene data."""
    _FBP_HISTORY_COUNTS["undo"] = int(_FBP_HISTORY_COUNTS.get("undo", 0) or 0) + 1
    _FBP_HISTORY_COUNTS["generation"] = int(
        _FBP_HISTORY_COUNTS.get("generation", 0) or 0
    ) + 1
    return _scene_key(scene)


def fbp_note_redo_event(scene=None):
    """Record one completed Blender Redo event without touching scene data."""
    _FBP_HISTORY_COUNTS["redo"] = int(_FBP_HISTORY_COUNTS.get("redo", 0) or 0) + 1
    _FBP_HISTORY_COUNTS["generation"] = int(
        _FBP_HISTORY_COUNTS.get("generation", 0) or 0
    ) + 1
    return _scene_key(scene)


def fbp_clear_undo_endurance_runtime():
    """Discard process-local baselines when Blender replaces Main."""
    _FBP_UNDO_BASELINES.clear()
    return True


def _history_snapshot():
    return {
        "undo": int(_FBP_HISTORY_COUNTS.get("undo", 0) or 0),
        "redo": int(_FBP_HISTORY_COUNTS.get("redo", 0) or 0),
        "generation": int(_FBP_HISTORY_COUNTS.get("generation", 0) or 0),
    }


class FBP_OT_RunUndoEnduranceAudit(Operator):
    bl_idname = "fbp.run_undo_endurance_audit"
    bl_label = "Undo / Redo Endurance"
    bl_description = (
        "Capture a semantic project baseline, perform real Undo and Redo operations, "
        "return to the captured state and verify that Frame By Plane data did not drift"
    )

    action: EnumProperty(
        name="Action",
        description="Capture, verify or clear the process-local Undo/Redo baseline",
        items=(
            (
                "CAPTURE",
                "Capture Baseline",
                "Capture the current layer, effect, mask, animation and Lattice state before testing Undo and Redo",
            ),
            (
                "VERIFY",
                "Verify Round Trip",
                "Verify the current project against the captured state after real Undo and Redo operations",
            ),
            (
                "CLEAR",
                "Clear Baseline",
                "Discard the current process-local Undo/Redo baseline",
            ),
        ),
        default="VERIFY",
    )
    minimum_undo_events: IntProperty(
        name="Minimum Undo Events",
        description="Minimum number of completed Undo operations required after capture",
        default=1,
        min=0,
        max=1000,
    )
    minimum_redo_events: IntProperty(
        name="Minimum Redo Events",
        description="Minimum number of completed Redo operations required after capture",
        default=1,
        min=0,
        max=1000,
    )

    def execute(self, context):
        scene = getattr(context, "scene", None)
        key = _scene_key(scene)
        if scene is None or not key:
            self.report({'ERROR'}, "An active Scene is required")
            return {'CANCELLED'}

        if self.action == "CLEAR":
            _FBP_UNDO_BASELINES.pop(key, None)
            self.report({'INFO'}, "Undo/Redo endurance baseline cleared")
            return {'FINISHED'}

        sync_layer_collection(context)

        if self.action == "CAPTURE":
            contract, assigned_ids, duplicate_ids = _fbp_build_persistence_contract(
                scene, prepare_ids=True
            )
            digest = _fbp_persistence_digest(contract)
            captured_at = datetime.now().isoformat(timespec="seconds")
            _FBP_UNDO_BASELINES[key] = {
                "schema": 1,
                "addon_version": FBP_VERSION_STRING,
                "captured_at": captured_at,
                "history": _history_snapshot(),
                "hash": digest,
                "contract": contract,
                "status": _STATUS_CAPTURED,
            }
            lines = [
                "Frame By Plane — Undo / Redo Endurance Baseline",
                "================================================",
                f"Generated: {captured_at}",
                f"Scene: {key}",
                f"Layers captured: {len(contract.get('rigs', ())) }",
                f"Persistent IDs assigned: {assigned_ids}",
                f"Hash: {digest}",
                "",
                "Test workflow",
                "-------------",
                "1. Perform real Undo and Redo operations in Blender.",
                "2. Return the project to this captured state.",
                "3. Run Verify Round Trip.",
            ]
            if duplicate_ids:
                lines.extend(("", "Warnings", "--------"))
                lines.extend(
                    f"- Duplicate or missing ID {item!r}: {', '.join(names)}"
                    for item, names in sorted(duplicate_ids.items())
                )
            write_diagnostic_report(
                scene,
                "FBP_Undo_Redo_Endurance",
                lines,
                summary=f"Undo/Redo · baseline captured · {len(contract.get('rigs', ())) } layer(s)",
                status="INFO",
            )
            self.report({'INFO'}, "Undo/Redo baseline captured")
            return {'FINISHED'}

        baseline = _FBP_UNDO_BASELINES.get(key)
        issues = []
        warnings = []
        differences = []
        current_hash = ""
        current_contract = {}
        current_history = _history_snapshot()
        undo_events = 0
        redo_events = 0

        if not baseline:
            issues.append("No process-local Undo/Redo baseline is available for this Scene")
        else:
            start_history = baseline.get("history", {}) or {}
            undo_events = max(
                0,
                current_history["undo"] - int(start_history.get("undo", 0) or 0),
            )
            redo_events = max(
                0,
                current_history["redo"] - int(start_history.get("redo", 0) or 0),
            )
            if undo_events < int(self.minimum_undo_events):
                issues.append(
                    f"Only {undo_events} Undo event(s) completed; {int(self.minimum_undo_events)} required"
                )
            if redo_events < int(self.minimum_redo_events):
                issues.append(
                    f"Only {redo_events} Redo event(s) completed; {int(self.minimum_redo_events)} required"
                )

            current_contract, _assigned_ids, duplicate_ids = _fbp_build_persistence_contract(
                scene, prepare_ids=False
            )
            current_hash = _fbp_persistence_digest(current_contract)
            differences = _fbp_persistence_diff(
                baseline.get("contract", {}), current_contract
            )
            issues.extend(differences)
            if duplicate_ids:
                for item, names in sorted(duplicate_ids.items()):
                    issues.append(
                        f"Duplicate or missing persistence ID {item!r}: {', '.join(names)}"
                    )
            if str(baseline.get("addon_version", "") or "") != FBP_VERSION_STRING:
                issues.append(
                    "The baseline belongs to another Frame By Plane version; capture it again"
                )
            expected_hash = str(baseline.get("hash", "") or "")
            if expected_hash and expected_hash != _fbp_persistence_digest(
                baseline.get("contract", {})
            ):
                issues.append("The stored baseline hash is internally inconsistent")

            baseline["status"] = _STATUS_PASS if not issues else _STATUS_FAIL

        if len(differences) >= 250:
            warnings.append("Difference report was limited to the first 250 changes")

        lines = [
            "Frame By Plane — Undo / Redo Endurance Audit",
            "==============================================",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"Scene: {key}",
            f"Baseline captured: {baseline.get('captured_at', '<missing>') if baseline else '<missing>'}",
            f"Undo events since capture: {undo_events}",
            f"Redo events since capture: {redo_events}",
            f"Current hash: {current_hash or '<unavailable>'}",
            "",
            "Structural issues",
            "-----------------",
        ]
        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- None")
        lines.extend(("", "Warnings", "--------"))
        lines.extend(f"- {item}" for item in warnings) if warnings else lines.append("- None")
        lines.extend(("", "Validation totals", "-----------------"))
        lines.append(f"Structural issues: {len(issues)}")
        lines.append(f"Warnings: {len(warnings)}")
        lines.extend(("", "Result", "------", "PASS" if not issues else "REVIEW REQUIRED"))
        summary = (
            f"Undo/Redo · {len(issues)} issue(s) · {undo_events} undo / {redo_events} redo"
        )
        write_diagnostic_report(
            scene,
            "FBP_Undo_Redo_Endurance",
            lines,
            summary=summary,
            status="PASS" if not issues else "WARNING",
        )
        self.report({'INFO'} if not issues else {'WARNING'}, summary)
        return {'FINISHED'}


classes = (FBP_OT_RunUndoEnduranceAudit,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    fbp_clear_undo_endurance_runtime()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except FBP_DATA_ERRORS:
            pass


__all__ = (
    "FBP_OT_RunUndoEnduranceAudit",
    "fbp_clear_undo_endurance_runtime",
    "fbp_note_redo_event",
    "fbp_note_undo_event",
)
