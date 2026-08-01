"""Focused Frame By Plane operator module."""

import bpy
import os
import tempfile
from pathlib import Path
from bpy.props import (
    BoolProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator

from .runtime import FBP_DATA_ERRORS
from .diagnostics import (
    diagnostic_report_messages,
    last_diagnostic_report,
    write_diagnostic_report,
)
from .layers import collection_is_hidden_in_view_layer, get_primary_fbp_collection, iter_scene_fbp_rigs, object_in_view_layer, project_root_for_package, relink_missing_images_from_root, rig_has_missing_images, sync_collection_colors_to_rigs
from .scene_sync import sync_layer_collection
from .operator_common import (
    _fbp_active_pending_index_and_collection,
    _fbp_active_pending_tree_row,
    _fbp_remove_pending_indices,
)
from .project_health import REPORT_NAME, scan_project_health, health_report_lines
from .feature_scope import fbp_preview_diagnostics_text


class FBP_OT_RemovePendingTreeSelection(Operator):
    bl_idname = "fbp.remove_pending_tree_selection"
    bl_label = "Remove Setup Selection"
    bl_description = "Remove the selected setup layer, or the selected collection with all internal layers"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sc = context.scene
        row = _fbp_active_pending_tree_row(sc)
        if row is not None and getattr(row, 'row_type', 'LAYER') == 'GROUP':
            collection_path = getattr(row, 'collection_path', '') or ''
            if not collection_path:
                return {'CANCELLED'}
            indices = [
                i for i, item in enumerate(sc.fbp_pending_planes)
                if (getattr(item, 'collection_name', '') or '') == collection_path
                or (getattr(item, 'collection_name', '') or '').startswith(collection_path + ' /')
            ]
            removed = _fbp_remove_pending_indices(context, indices)
            return {'FINISHED'} if removed else {'CANCELLED'}

        idx, _collection_name, _row_type = _fbp_active_pending_index_and_collection(sc)
        if 0 <= idx < len(sc.fbp_pending_planes):
            return {'FINISHED'} if _fbp_remove_pending_indices(context, {idx}) else {'CANCELLED'}
        return {'CANCELLED'}

class FBP_OT_RemovePendingPlaneAtIndex(Operator):
    bl_idname = "fbp.remove_pending_plane_at_index"
    bl_label = "Remove Setup Layer"
    bl_description = "Remove this pending layer from the Multiplane Setup before generating planes"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="Index", description="Zero-based index of the pending Multiplane Setup row to remove. Source media and already generated scene layers are never deleted by this action.", default=-1)

    def execute(self, context):
        sc = context.scene
        if 0 <= self.index < len(sc.fbp_pending_planes):
            return {'FINISHED'} if _fbp_remove_pending_indices(context, {self.index}) else {'CANCELLED'}
        return {'CANCELLED'}

class FBP_OT_ProjectHealthCheck(Operator):
    bl_idname = "fbp.project_health_check"
    bl_label = "Project Doctor"
    bl_description = (
        "Scan the project for missing sources, broken drivers, invalid effects, masks, ownership, "
        "production services and compositor references"
    )
    bl_options = {'REGISTER', 'UNDO'}

    repair: BoolProperty(
        name="Safe Repair",
        description=(
            "Add or repair only persistent identities and generated-data ownership tags; "
            "media, effects, nodes and user objects are never deleted or rebuilt"
        ),
        default=False,
    )

    def execute(self, context):
        sync_layer_collection(context)
        result = scan_project_health(context.scene, repair=self.repair)
        stats = dict(result.get("stats", {}) or {})
        lines = health_report_lines(context.scene, result, repair=self.repair)
        error_count = int(stats.get("errors", 0) or 0)
        warning_count = int(stats.get("warnings", 0) or 0)
        repaired = int(result.get("repaired", 0) or 0)
        summary = (
            f"Project Doctor · {error_count} error(s) · "
            f"{warning_count} warning(s)"
        )
        if repaired:
            summary += f" · {repaired} metadata repair(s)"
        status = "ERROR" if error_count else ("WARNING" if warning_count else "PASS")
        write_diagnostic_report(
            context.scene,
            REPORT_NAME,
            lines,
            summary=summary,
            status=status,
        )
        self.report({'WARNING'} if error_count or warning_count else {'INFO'}, summary)
        return {'FINISHED'}































class FBP_OT_OpenLastDiagnosticReport(Operator):
    bl_idname = "fbp.open_last_diagnostic_report"
    bl_label = "Open Last Report"
    bl_description = "Open the most recently generated Frame By Plane diagnostic report in the current area"

    @classmethod
    def poll(cls, context):
        text, _summary, _status, _timestamp = last_diagnostic_report(getattr(context, "scene", None))
        return text is not None and getattr(context, "area", None) is not None

    def execute(self, context):
        text, summary, _status, _timestamp = last_diagnostic_report(context.scene)
        if text is None:
            self.report({'WARNING'}, "No diagnostic report is available yet")
            return {'CANCELLED'}
        area = getattr(context, "area", None)
        if area is None:
            self.report({'WARNING'}, "No editor area is available for the report")
            return {'CANCELLED'}
        try:
            area.type = 'TEXT_EDITOR'
            space = getattr(area.spaces, "active", None)
            if space is not None:
                space.text = text
                if hasattr(space, "show_word_wrap"):
                    space.show_word_wrap = True
            self.report({'INFO'}, summary or text.name)
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            self.report({'WARNING'}, f"Could not open report: {exc}")
            return {'CANCELLED'}


class FBP_OT_CopyLastDiagnosticReport(Operator):
    bl_idname = "fbp.copy_last_diagnostic_report"
    bl_label = "Copy Last Report"
    bl_description = "Copy the complete most recent Frame By Plane diagnostic report to the clipboard"

    @classmethod
    def poll(cls, context):
        text, _summary, _status, _timestamp = last_diagnostic_report(getattr(context, "scene", None))
        return text is not None

    def execute(self, context):
        text, summary, _status, _timestamp = last_diagnostic_report(context.scene)
        if text is None:
            self.report({'WARNING'}, "No diagnostic report is available yet")
            return {'CANCELLED'}
        try:
            context.window_manager.clipboard = text.as_string()
            self.report({'INFO'}, f"Copied: {summary or text.name}")
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            self.report({'WARNING'}, f"Could not copy report: {exc}")
            return {'CANCELLED'}


class FBP_OT_CopyPreviewDiagnostics(Operator):
    bl_idname = "fbp.copy_preview_diagnostics"
    bl_label = "Copy Preview Diagnostics"
    bl_description = (
        "Copy enabled Preview features, detected Preview data and the 7.1 LTS scope policy "
        "without including project paths, media or telemetry"
    )
    bl_options = {"INTERNAL"}

    def execute(self, context):
        try:
            context.window_manager.clipboard = fbp_preview_diagnostics_text(
                getattr(context, "scene", None)
            )
        except FBP_DATA_ERRORS as exc:
            self.report({'WARNING'}, f"Could not copy Preview diagnostics: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, "Preview diagnostics copied")
        return {'FINISHED'}


class FBP_OT_OpenDiagnosticReport(Operator):
    bl_idname = "fbp.open_diagnostic_report"
    bl_label = "Open Diagnostic Report"
    bl_description = "Open this specific Frame By Plane diagnostic report in the current area"

    report_name: StringProperty(
        name="Report",
        description="Internal Text datablock containing the diagnostic report",
        default="",
        options={'HIDDEN'},
    )

    def execute(self, context):
        report_name = str(self.report_name or "").strip()
        text = bpy.data.texts.get(report_name) if report_name else None
        if text is None:
            self.report({'WARNING'}, "This diagnostic report has not been generated yet")
            return {'CANCELLED'}
        area = getattr(context, "area", None)
        if area is None:
            self.report({'WARNING'}, "No editor area is available for the report")
            return {'CANCELLED'}
        try:
            area.type = 'TEXT_EDITOR'
            space = getattr(area.spaces, "active", None)
            if space is not None:
                space.text = text
                if hasattr(space, "show_word_wrap"):
                    space.show_word_wrap = True
            self.report({'INFO'}, report_name)
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            self.report({'WARNING'}, f"Could not open report: {exc}")
            return {'CANCELLED'}


class FBP_OT_CopyDiagnosticMessages(Operator):
    bl_idname = "fbp.copy_diagnostic_messages"
    bl_label = "Copy Diagnostic Messages"
    bl_description = "Copy only the actionable error and warning messages from this diagnostic report"

    report_name: StringProperty(
        name="Report",
        description="Internal Text datablock containing the diagnostic report",
        default="",
        options={'HIDDEN'},
    )
    full_report: BoolProperty(
        name="Full Report",
        description="Copy the complete report instead of only actionable messages",
        default=False,
        options={'HIDDEN'},
    )

    def execute(self, context):
        report_name = str(self.report_name or "").strip()
        text = bpy.data.texts.get(report_name) if report_name else None
        if text is None:
            self.report({'WARNING'}, "This diagnostic report has not been generated yet")
            return {'CANCELLED'}
        try:
            if self.full_report:
                payload = text.as_string()
            else:
                messages = diagnostic_report_messages(text)
                if not messages:
                    self.report({'INFO'}, "This report contains no error or warning messages")
                    return {'CANCELLED'}
                payload = "\n".join(f"- {message}" for message in messages)
            context.window_manager.clipboard = payload
            self.report({'INFO'}, f"Copied diagnostic messages from {report_name}")
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            self.report({'WARNING'}, f"Could not copy diagnostic messages: {exc}")
            return {'CANCELLED'}


class FBP_OT_ExportProjectDoctorReport(Operator):
    bl_idname = "fbp.export_project_doctor_report"
    bl_label = "Export Project Doctor Report"
    bl_description = "Save the latest Project Doctor report as a plain-text file"

    filepath: StringProperty(
        name="File Path",
        description="Destination text file for the Project Doctor report",
        subtype="FILE_PATH",
        default="",
    )
    filter_glob: StringProperty(default="*.txt", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        try:
            return bpy.data.texts.get(REPORT_NAME) is not None
        except FBP_DATA_ERRORS:
            return False

    def invoke(self, context, event):
        scene = context.scene
        project_root = str(getattr(scene, "fbp_project_path", "") or "").strip()
        if project_root:
            try:
                directory = bpy.path.abspath(project_root)
            except FBP_DATA_ERRORS:
                directory = ""
        elif bpy.data.filepath:
            directory = str(Path(bpy.data.filepath).parent)
        else:
            directory = tempfile.gettempdir()
        if not directory:
            directory = str(Path(bpy.data.filepath).parent) if bpy.data.filepath else tempfile.gettempdir()
        project_name = Path(bpy.data.filepath).stem if bpy.data.filepath else str(getattr(scene, "name", "Project") or "Project")
        safe_name = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in project_name).strip("_") or "Project"
        self.filepath = str(Path(directory) / f"{safe_name}_Frame_By_Plane_Project_Doctor.txt")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        report = bpy.data.texts.get(REPORT_NAME)
        if report is None:
            self.report({"WARNING"}, "Run Project Doctor before exporting a report")
            return {"CANCELLED"}
        filepath = str(self.filepath or "").strip()
        if not filepath:
            self.report({"WARNING"}, "Choose a destination file")
            return {"CANCELLED"}
        if not filepath.lower().endswith(".txt"):
            filepath += ".txt"
        try:
            target = Path(bpy.path.abspath(filepath)).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(report.as_string(), encoding="utf-8")
        except OSError as exc:
            self.report({"ERROR"}, f"Could not export Project Doctor report: {exc}")
            return {"CANCELLED"}
        except FBP_DATA_ERRORS as exc:
            self.report({"ERROR"}, f"Could not read Project Doctor report: {exc}")
            return {"CANCELLED"}
        self.filepath = str(target)
        self.report({"INFO"}, f"Project Doctor report exported: {target.name}")
        return {"FINISHED"}


class FBP_OT_RelinkFromProjectRoot(Operator):
    bl_idname      = "fbp.relink_from_project_root"
    bl_label       = "Relink From Project Root"
    bl_description = "Relink missing images by searching inside the Project Folder"
    bl_options     = {'UNDO'}

    def execute(self, context):
        root = project_root_for_package(context)
        if not root or not os.path.isdir(root):
            self.report({'WARNING'}, "Set a valid Project Folder first")
            return {'CANCELLED'}
        relinked, ambiguous, still_missing = relink_missing_images_from_root(root, make_relative=True)
        msg = f"Relinked {relinked}; missing {len(still_missing)}; ambiguous {len(ambiguous)}"
        self.report({'INFO' if not still_missing else 'WARNING'}, msg)
        return {'FINISHED'}

class FBP_OT_SelectMissingLayers(Operator):
    bl_idname      = "fbp.select_missing_layers"
    bl_label       = "Select Missing Layers"
    bl_description = "Select Frame By Plane rigs that contain missing linked images"
    bl_options     = {'UNDO'}

    def execute(self, context):
        sync_layer_collection(context)
        bpy.ops.object.select_all(action='DESELECT')
        selected = 0
        skipped_hidden = 0
        active = None
        for rig in iter_scene_fbp_rigs(context.scene):
            if not rig_has_missing_images(rig):
                continue
            if collection_is_hidden_in_view_layer(context, get_primary_fbp_collection(rig)):
                skipped_hidden += 1
                continue
            if not object_in_view_layer(rig, context):
                skipped_hidden += 1
                continue
            try:
                rig.select_set(True)
                active = rig
                selected += 1
            except Exception:
                skipped_hidden += 1
        if active:
            context.view_layer.objects.active = active
        level = 'WARNING' if skipped_hidden else 'INFO'
        self.report({level}, f"Selected {selected} missing layer(s); hidden/unavailable {skipped_hidden}")
        return {'FINISHED'} if selected or skipped_hidden else {'CANCELLED'}

class FBP_OT_SyncCollectionColors(Operator):
    bl_idname      = "fbp.sync_collection_colors"
    bl_label       = "Sync Collection Colors"
    bl_description = "Apply visible Collection color tags to Frame By Plane layer viewport colors"
    bl_options     = {'UNDO'}

    def execute(self, context):
        sync_collection_colors_to_rigs(context)
        self.report({'INFO'}, "Collection colors synced")
        return {'FINISHED'}

class FBP_OT_ApplyPreferencesToScene(Operator):
    bl_idname = "fbp.apply_preferences_to_scene"
    bl_label = "Apply Frame By Plane Preferences"
    bl_description = "Apply the configured Frame By Plane defaults to the current Scene"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from .preference_application import fbp_apply_preferences_to_scene
        if fbp_apply_preferences_to_scene(context.scene, force=True, context=context):
            self.report({'INFO'}, "Frame By Plane preferences applied to the current Scene")
            return {'FINISHED'}
        self.report({'WARNING'}, "Frame By Plane preferences are unavailable")
        return {'CANCELLED'}







# SECTION - Effects Regression Scene #





