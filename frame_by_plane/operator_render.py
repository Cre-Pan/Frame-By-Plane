"""Focused Frame By Plane operator module."""

import os
import shutil
import subprocess
import tempfile
import time

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty

from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_render_mutation_blocked,
    fbp_runtime_get,
    fbp_runtime_set,
    fbp_tag_redraw,
    fbp_warn,
)
from .registration import register_classes, unregister_classes, unregister_timer
from .runtime_scheduler import (
    PRIORITY_CRITICAL,
    cancel_task,
    schedule_task,
)
from .core import fbp_repair_all_render_state, fbp_render_guard_idle_restore, fbp_render_guard_abandon
from .scene_sync import sync_layer_collection
from .layers import iter_scene_fbp_rigs
from .ui_style import configure_layout, hint_row, section_header
from .render_output import (
    fbp_next_render_test_number,
    fbp_render_static_prefix,
    fbp_resolve_render_output,
    fbp_sync_native_render_path,
    fbp_sync_render_output_from_native,
)
from .operator_common import (
    FBP_BG_RENDER_STATE,
    _fbp_bg_cleanup_temp_files,
    _fbp_bg_clear_runtime_state,
    _fbp_bg_process_running,
    _fbp_bg_process_status,
    _fbp_bg_reset_progress_state,
    _fbp_bg_terminate_process,
    _fbp_bg_update_scene_status,
)


_PREVIOUS_BG_RENDER_MODAL_TIMERS = globals().get("_FBP_BG_RENDER_MODAL_TIMERS", ())
_PREVIOUS_BG_RENDER_APP_WATCHDOGS = globals().get("_FBP_BG_RENDER_APP_WATCHDOGS", ())
_PREVIOUS_ACTIVE_BG_RENDER_OPERATOR = globals().get("_FBP_ACTIVE_BG_RENDER_OPERATOR")
_FBP_BG_WATCHDOG_TASK_KEY = "background_render.watchdog"


def _retire_background_monitors_on_reload():
    """Retire callbacks/tasks bound to the former monitor generation."""
    retired = 0
    previous_operator = _PREVIOUS_ACTIVE_BG_RENDER_OPERATOR
    if previous_operator is not None:
        try:
            previous_operator._remove_app_watchdog()
        except FBP_DATA_ERRORS:
            pass
        try:
            previous_operator._remove_modal_timer(bpy.context)
            retired += 1
        except FBP_DATA_ERRORS:
            pass
    for monitor in tuple(_PREVIOUS_BG_RENDER_APP_WATCHDOGS or ()):
        try:
            if callable(monitor):
                retired += int(unregister_timer(monitor))
            else:
                retired += int(cancel_task(str(monitor or "")))
        except FBP_DATA_IO_ERRORS:
            continue
    try:
        wm = getattr(getattr(bpy, "context", None), "window_manager", None)
        for timer in tuple(_PREVIOUS_BG_RENDER_MODAL_TIMERS or ()):
            try:
                if wm is not None:
                    wm.event_timer_remove(timer)
                    retired += 1
            except FBP_DATA_ERRORS:
                continue
    except FBP_DATA_ERRORS:
        pass
    return retired


_RETIRED_BACKGROUND_MONITORS = _retire_background_monitors_on_reload()
_FBP_BG_RENDER_MODAL_TIMERS = []
_FBP_BG_RENDER_APP_WATCHDOGS = set()
_FBP_ACTIVE_BG_RENDER_OPERATOR = None
_FBP_CHILD_REPAIR_REGISTERED = globals().get("_FBP_CHILD_REPAIR_REGISTERED", False)

def _fbp_preserve_background_log(*, success=False):
    """Copy the child log and atomic job state beside the render output."""
    source = str(FBP_BG_RENDER_STATE.get("log_path", "") or "")
    state_source = str(FBP_BG_RENDER_STATE.get("state_path", "") or "")
    out_dir = str(FBP_BG_RENDER_STATE.get("out_dir", "") or "")
    if not out_dir:
        return ""
    try:
        os.makedirs(out_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        label = "Complete" if success else "Error"
        base = os.path.join(out_dir, f"FBP_Background_Render_{label}_{stamp}")
        destination = f"{base}.log"
        serial = 1
        while os.path.exists(destination):
            destination = f"{base}_{serial:02d}.log"
            serial += 1
        if source and os.path.isfile(source):
            shutil.copy2(source, destination)
        else:
            with open(destination, "w", encoding="utf-8") as stream:
                stream.write(str(FBP_BG_RENDER_STATE.get("last_log_message", "") or label))
                stream.write("\n")
        if state_source and os.path.isfile(state_source):
            shutil.copy2(state_source, os.path.splitext(destination)[0] + ".json")
        if not success:
            temp_dir = str(FBP_BG_RENDER_STATE.get("temp_dir", "") or "")
            try:
                candidates = tuple(os.listdir(temp_dir)) if temp_dir and os.path.isdir(temp_dir) else ()
            except OSError:
                candidates = ()
            for name in candidates:
                lowered = str(name).lower()
                if not (
                    lowered.endswith(".dmp")
                    or ("crash" in lowered and lowered.endswith((".txt", ".log")))
                ):
                    continue
                source_path = os.path.join(temp_dir, name)
                try:
                    if os.path.isfile(source_path):
                        shutil.copy2(
                            source_path,
                            os.path.splitext(destination)[0] + "_" + os.path.basename(name),
                        )
                except OSError:
                    pass
        FBP_BG_RENDER_STATE["last_log_copy"] = destination
        return destination
    except OSError:
        return ""




def _fbp_bg_resolve_scene():
    """Resolve the live Scene for the active background-render session."""
    scene_name = str(FBP_BG_RENDER_STATE.get("scene_name", "") or "")
    try:
        scene = bpy.data.scenes.get(scene_name) if scene_name else None
    except FBP_DATA_ERRORS:
        scene = None
    if scene is not None:
        return scene
    try:
        return getattr(getattr(bpy, "context", None), "scene", None)
    except FBP_DATA_ERRORS:
        return None


def _fbp_bg_poll_outcome(scene):
    """Poll child state without retaining an Operator or WindowManager timer."""
    if scene is None:
        return {
            "done": False,
            "success": False,
            "status": "",
            "report": "",
            "level": "WARNING",
        }
    try:
        status_changed = _fbp_bg_update_scene_status(scene)
        if status_changed:
            fbp_tag_redraw(area_types={'PROPERTIES'})
    except FBP_DATA_ERRORS:
        status_changed = False

    proc = FBP_BG_RENDER_STATE.get("process")
    running, code, state_known = _fbp_bg_process_status()
    if not state_known:
        return {
            "done": False,
            "success": False,
            "status": "",
            "report": "",
            "level": "WARNING",
        }
    if proc is not None and running:
        return {
            "done": False,
            "success": False,
            "status": "",
            "report": "",
            "level": "INFO",
        }

    _fbp_bg_update_scene_status(scene, None, force_filesystem_scan=True)
    try:
        progress = int(getattr(scene, "fbp_background_render_progress", 0) or 0)
    except FBP_DATA_ERRORS:
        progress = 0
    total = int(FBP_BG_RENDER_STATE.get("total", 0) or 0)
    complete_marker = bool(
        FBP_BG_RENDER_STATE.get("log_complete", False)
        or str(FBP_BG_RENDER_STATE.get("state_status", "") or "").upper() == "DONE"
    )
    if bool(FBP_BG_RENDER_STATE.get("requires_movie_output", False)):
        movie_path = str(FBP_BG_RENDER_STATE.get("movie_output_path", "") or "")
        try:
            movie_complete = bool(
                movie_path
                and os.path.isfile(movie_path)
                and os.path.getsize(movie_path) > 0
            )
        except OSError:
            movie_complete = False
        if bool(FBP_BG_RENDER_STATE.get("auto_video", False)):
            outputs_complete = movie_complete
        else:
            outputs_complete = movie_complete or (not total or progress >= total)
    else:
        outputs_complete = not total or progress >= total

    detail = str(FBP_BG_RENDER_STATE.get("last_log_message", "") or "").strip()
    if code in {None, 0} and complete_marker and outputs_complete:
        out_dir = str(FBP_BG_RENDER_STATE.get("out_dir", "") or "")
        return {
            "done": True,
            "success": True,
            "status": "Background render finished",
            "report": f"Background render finished: {out_dir}",
            "level": "INFO",
        }

    if code in {None, 0}:
        if not complete_marker:
            message = "Background Blender exited without the completion marker"
        elif bool(FBP_BG_RENDER_STATE.get("requires_movie_output", False)):
            message = "Background render did not produce the expected movie file"
        else:
            message = f"Background render wrote only {progress}/{total} expected frames"
        if detail:
            message += f": {detail[:180]}"
        return {
            "done": True,
            "success": False,
            "status": message,
            "report": message,
            "level": "WARNING",
        }

    report_message = f"Background render stopped or failed with code {code}"
    if detail:
        report_message += f": {detail[:220]}"
    return {
        "done": True,
        "success": False,
        "status": (
            f"Stopped or failed with code {code}"
            + (f" · {detail[:160]}" if detail else "")
        ),
        "report": report_message,
        "level": "WARNING",
    }


def _fbp_bg_finalize_runtime(scene, status_message, *, success, expected_token=""):
    """Finalize one monitor session without depending on an Operator instance."""
    current_token = str(FBP_BG_RENDER_STATE.get("session_token", "") or "")
    if expected_token and current_token != str(expected_token):
        return False
    if not current_token:
        return False
    try:
        _fbp_bg_update_scene_status(scene, None, force_filesystem_scan=True)
    except FBP_DATA_ERRORS:
        pass
    FBP_BG_RENDER_STATE["process"] = None
    keep_success_log = False
    try:
        keep_success_log = bool(
            success and getattr(scene, "fbp_background_render_keep_log", False)
        )
    except FBP_DATA_ERRORS:
        keep_success_log = False
    if not success or keep_success_log:
        _fbp_preserve_background_log(success=bool(success))
    FBP_BG_RENDER_STATE["session_token"] = ""
    _fbp_bg_cleanup_temp_files()
    FBP_BG_RENDER_STATE["state_path"] = ""
    FBP_BG_RENDER_STATE["stop_path"] = ""
    if scene is not None:
        _fbp_bg_update_scene_status(scene, str(status_message or "Background render finished"))
    try:
        fbp_tag_redraw(area_types={'PROPERTIES'})
    except FBP_DATA_IO_ERRORS:
        pass
    return True


def _fbp_background_app_watchdog():
    """Global scheduler callback; retains no Operator, Scene or timer RNA."""
    session_token = str(FBP_BG_RENDER_STATE.get("session_token", "") or "")
    if not session_token:
        _FBP_BG_RENDER_APP_WATCHDOGS.discard(_FBP_BG_WATCHDOG_TASK_KEY)
        return None
    scene = _fbp_bg_resolve_scene()
    if scene is None:
        return 0.5
    try:
        outcome = _fbp_bg_poll_outcome(scene)
    except FBP_DATA_ERRORS:
        return 0.5
    if not bool(outcome.get("done", False)):
        return 0.25
    _fbp_bg_finalize_runtime(
        scene,
        str(outcome.get("status", "") or "Background render finished"),
        success=bool(outcome.get("success", False)),
        expected_token=session_token,
    )
    _FBP_BG_RENDER_APP_WATCHDOGS.discard(_FBP_BG_WATCHDOG_TASK_KEY)
    return None




def _fbp_run_render_state_repair(context, *, sync_layers=True):
    """Validate render state, optionally rebuilding authoring-only layer UI.

    The dedicated background child has no useful Layer List, selection state or
    editor context.  Rebuilding those structures before every render snapshot
    adds work and can emit unrelated RNA notifiers, so the child validates the
    scene directly while the interactive operator keeps the full repair path.
    """
    scene = getattr(context, "scene", None)
    if scene is None:
        return 0, 0, 0, 0
    if sync_layers:
        sync_layer_collection(context)
    expected = sum(1 for _rig in iter_scene_fbp_rigs(scene))
    fixed = fbp_repair_all_render_state(scene, scene.frame_current)
    gp_required = gp_ready = 0
    if str(getattr(getattr(scene, "render", None), "engine", "") or "") == "CYCLES":
        try:
            from .grease_pencil_bridge import fbp_prepare_gp_cycles_render_assets
            gp_required, gp_ready = fbp_prepare_gp_cycles_render_assets(scene)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not prepare Grease Pencil Cycles render assets", exc)
            gp_required, gp_ready = 1, 0
    return expected, fixed, int(gp_required), int(gp_ready)


class FBP_OT_RepairRenderState(Operator):
    bl_idname      = "fbp.repair_render_state"
    bl_label       = "Repair FBP Render State"
    bl_description = "Validate native media, timing, material slots, UVs and material indices before rendering"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        expected, fixed, gp_required, gp_ready = _fbp_run_render_state_repair(context)
        if fixed != expected or gp_ready != gp_required:
            details = []
            if fixed != expected:
                details.append(f"{expected - fixed} invalid FBP layer(s)")
            if gp_ready != gp_required:
                details.append(f"{gp_required - gp_ready} invalid Grease Pencil Cycles proxy/proxies")
            self.report({'ERROR'}, "Render validation failed: " + "; ".join(details))
            return {'CANCELLED'}
        message = f"Render state validated on {fixed} FBP layer(s)"
        if gp_required:
            message += f" and {gp_ready} Grease Pencil Cycles proxy/proxies"
        self.report({'INFO'}, message)
        return {'FINISHED'}


class FBP_OT_RepairRenderStateBackground(Operator):
    bl_idname = "fbp.repair_render_state_background"
    bl_label = "Background Render State Validation"
    bl_description = "Validate the isolated render snapshot without creating an Undo step"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        expected, fixed, gp_required, gp_ready = _fbp_run_render_state_repair(
            context, sync_layers=False
        )
        return {'FINISHED'} if fixed == expected and gp_ready == gp_required else {'CANCELLED'}


class FBP_OT_FinalizeRenderStateBackground(Operator):
    bl_idname = "fbp.finalize_render_state_background"
    bl_label = "Finalize Background Render State"
    bl_description = "Restore temporary Frame By Plane render overrides after the blocking background render returns"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        scene = getattr(context, "scene", None)
        if not bool(fbp_runtime_get("fbp_render_guard_active", False)):
            return {'FINISHED'}
        # bpy.ops.render.render() has returned, so Cycles no longer owns the
        # render session. Retry transient RNA failures without registering a
        # timer or touching UI/notifier infrastructure in the child process.
        for _attempt in range(20):
            try:
                if fbp_render_guard_idle_restore(scene):
                    return {'FINISHED'}
            except FBP_DATA_ERRORS:
                pass
            time.sleep(0.05)
        fbp_render_guard_abandon()
        return {'CANCELLED'}


class FBP_OT_SyncRenderOutput(Operator):
    bl_idname = "fbp.sync_render_output"
    bl_label = "Synchronize Render Output"
    bl_description = (
        "Synchronize Frame By Plane output settings with Blender's native Render File Path; "
        "this repeatable scene-only action does not create folders or render files"
    )
    bl_options = {'REGISTER'}

    from_native: BoolProperty(
        name="Read Native Path",
        description="Read Blender's native output path into Frame By Plane instead of pushing the FBP builder path",
        default=True,
    )

    @classmethod
    def description(cls, _context, properties):
        if bool(getattr(properties, "from_native", True)):
            return (
                "Read Blender's native Render File Path into the Frame By Plane output builder. "
                "Only scene RNA changes; no folders or files are created, the operation is idempotent, "
                "and Blender Undo is intentionally not advertised for runtime path synchronization."
            )
        return (
            "Push the Frame By Plane output builder path into Blender's native Render File Path. "
            "Only scene RNA changes; no folders or files are created, the operation is idempotent, "
            "and Blender Undo is intentionally not advertised for runtime path synchronization."
        )

    @classmethod
    def poll(cls, context):
        available = getattr(context, "scene", None) is not None
        if not available:
            cls.poll_message_set("No active scene is available for render output synchronization")
        return available

    def execute(self, context):
        if self.from_native:
            changed = fbp_sync_render_output_from_native(context.scene, force=True)
            message = "Read Blender output path" if changed else "Output paths already synchronized"
        else:
            changed = fbp_sync_native_render_path(context.scene)
            message = "Updated Blender output path" if changed else "Output paths already synchronized"
        self.report({'INFO'}, message)
        return {'FINISHED'}


class FBP_OT_OpenRenderOutputFolder(Operator):
    bl_idname = "fbp.open_render_output_folder"
    bl_label = "Open Render Folder"
    bl_description = "Create and open the currently resolved render destination"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            resolved = fbp_resolve_render_output(context.scene, create=True, update_native=True)
            bpy.ops.wm.path_open(filepath=resolved["output_dir"])
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self.report({'ERROR'}, f"Could not open render folder: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_NextRenderTestFolder(Operator):
    bl_idname = "fbp.next_render_test_folder"
    bl_label = "Next TEST Folder"
    bl_description = "Select the next available numbered TEST folder without starting a render"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        try:
            scene.fbp_render_folder_mode = 'TEST'
            scene.fbp_render_test_number = fbp_next_render_test_number(scene)
            fbp_sync_native_render_path(scene)
        except (AttributeError, OSError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            self.report({'ERROR'}, f"Could not select the next TEST folder: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"TEST {int(scene.fbp_render_test_number):0{int(scene.fbp_render_test_digits)}d}")
        return {'FINISHED'}


class FBP_OT_BackgroundRenderFrames(Operator):
    bl_idname      = "fbp.background_render_frames"
    bl_label       = "Background Render FBP Frames"
    bl_description = "Render frames in a separate Blender process without blocking the UI"
    bl_options     = {'REGISTER'}

    _timer = None
    _session_token = ""
    _app_watchdog_key = ""

    def invoke(self, context, event):
        if bool(getattr(context.scene.render, "use_overwrite", True)):
            return context.window_manager.invoke_confirm(
                self,
                event,
                title="Overwrite Existing Render Files?",
                message="Matching frames or video files can be replaced. Continue with the background render?",
                confirm_text="Render and Overwrite",
                icon='ERROR',
            )
        return self.execute(context)

    def _owns_render_state(self):
        token = str(getattr(self, "_session_token", "") or "")
        return bool(token and token == str(FBP_BG_RENDER_STATE.get("session_token", "") or ""))

    def _remove_modal_timer(self, context):
        try:
            if self._timer:
                context.window_manager.event_timer_remove(self._timer)
                try:
                    _FBP_BG_RENDER_MODAL_TIMERS.remove(self._timer)
                except ValueError:
                    pass
        except FBP_DATA_IO_ERRORS:
            pass
        self._timer = None

    def _remove_app_watchdog(self):
        key = str(getattr(self, "_app_watchdog_key", "") or "")
        self._app_watchdog_key = ""
        if not key:
            return False
        _FBP_BG_RENDER_APP_WATCHDOGS.discard(key)
        try:
            return bool(cancel_task(key))
        except FBP_DATA_IO_ERRORS:
            return False

    def _finish_modal(self, context, status_message, result=None):
        global _FBP_ACTIVE_BG_RENDER_OPERATOR
        if result is None:
            result = {'FINISHED'}
        token = str(getattr(self, "_session_token", "") or "")
        self._remove_app_watchdog()
        self._remove_modal_timer(context)
        if _FBP_ACTIVE_BG_RENDER_OPERATOR is self:
            _FBP_ACTIVE_BG_RENDER_OPERATOR = None
        if not self._owns_render_state():
            return result
        _fbp_bg_finalize_runtime(
            context.scene,
            status_message,
            success='CANCELLED' not in result,
            expected_token=token,
        )
        return result

    def modal(self, context, event):
        if not self._owns_render_state():
            return self._finish_modal(context, "Background render monitor retired", {'CANCELLED'})
        if event.type == 'ESC':
            if _fbp_bg_terminate_process(context.scene):
                return self._finish_modal(
                    context, "Background render stopped", {'CANCELLED'}
                )
            # Keep the modal owner alive when process exit could not be
            # confirmed. Clearing its token/log here could orphan a live child.
            self.report({'ERROR'}, "Could not confirm that the background render stopped")
            return {'RUNNING_MODAL'}

        if event.type == 'TIMER':
            event_timer = getattr(event, "timer", None)
            if self._timer is not None and event_timer != self._timer:
                return {'PASS_THROUGH'}
            outcome = _fbp_bg_poll_outcome(context.scene)
            if not bool(outcome.get("done", False)):
                return {'RUNNING_MODAL'}
            level = str(outcome.get("level", "INFO") or "INFO")
            report_text = str(outcome.get("report", "") or "")
            if report_text:
                self.report({level}, report_text)
            result = {'FINISHED'} if bool(outcome.get("success", False)) else {'CANCELLED'}
            return self._finish_modal(
                context,
                str(outcome.get("status", "") or "Background render finished"),
                result,
            )

        return {'PASS_THROUGH'}

    def execute(self, context):
        global _FBP_ACTIVE_BG_RENDER_OPERATOR
        sc = context.scene
        self._remove_app_watchdog()
        if _fbp_bg_process_running():
            _fbp_bg_update_scene_status(sc)
            try:
                bpy.ops.fbp.background_render_status('INVOKE_DEFAULT')
            except FBP_DATA_IO_ERRORS:
                pass
            self.report({'WARNING'}, "A background render is already running")
            return {'CANCELLED'}

        # A lost modal/window may leave a completed Popen and temporary log in
        # memory. Clear only completed stale state before starting a new session.
        if any((
            FBP_BG_RENDER_STATE.get("process") is not None,
            FBP_BG_RENDER_STATE.get("log_handle") is not None,
            bool(FBP_BG_RENDER_STATE.get("temp_dir")),
            bool(FBP_BG_RENDER_STATE.get("session_token")),
        )):
            _fbp_bg_clear_runtime_state(sc)

        if not bpy.data.is_saved:
            self.report({'WARNING'}, "Save the .blend file first")
            return {'CANCELLED'}

        # Never serialize a snapshot while a native render owns scene data or
        # while FBP is still restoring temporary render overrides.  Capturing
        # that transient state would bake hidden planes/proxies or raised Cycles
        # settings into the child .blend.
        if bool(fbp_runtime_get("fbp_render_guard_active", False)):
            self.report({'WARNING'}, "Wait for Frame By Plane render cleanup to finish")
            return {'CANCELLED'}
        if fbp_render_mutation_blocked(include_guard=False):
            self.report({'WARNING'}, "A Blender render job is still active")
            return {'CANCELLED'}

        requested_video = str(
            getattr(sc, "fbp_render_output_kind", "IMAGES") or "IMAGES"
        ) == 'VIDEO'
        if requested_video and not bool(getattr(sc.render, "is_movie_format", False)):
            # Blender 5.2 Windows can expose FFmpeg in static RNA while rejecting
            # it from the runtime enum used by background renders.  PNG is the
            # lossless, resumable intermediate for the automatic MP4 fallback.
            try:
                sc.render.image_settings.file_format = 'PNG'
                if hasattr(sc.render, "use_file_extension"):
                    sc.render.use_file_extension = True
            except FBP_DATA_ERRORS as exc:
                self.report({'ERROR'}, f"Could not prepare PNG video frames: {exc}")
                return {'CANCELLED'}

        # Render Blender's native Scene range, including frame step. The exact
        # native output path is resolved before snapshot creation so the live
        # project, child process and Output Properties always agree.
        start = int(sc.frame_start)
        end = int(sc.frame_end)
        step = max(1, int(getattr(sc, "frame_step", 1) or 1))
        if end < start:
            self.report({'WARNING'}, "Scene Out must be after Scene In")
            return {'CANCELLED'}
        scheduled_frames = tuple(range(start, end + 1, step))
        if not scheduled_frames:
            self.report({'WARNING'}, "The Scene frame range contains no frames")
            return {'CANCELLED'}

        try:
            resolved_output = fbp_resolve_render_output(
                sc,
                advance_test=True,
                create=True,
                update_native=True,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self.report({'ERROR'}, f"Could not prepare render destination: {exc}")
            return {'CANCELLED'}
        out_dir = resolved_output["output_dir"]
        output_path = resolved_output["filepath"]
        prefix = fbp_render_static_prefix(sc)
        auto_video = bool(resolved_output.get("auto_video", False))
        ffmpeg_executable = str(resolved_output.get("ffmpeg_executable", "") or "")
        if auto_video and not ffmpeg_executable:
            self.report(
                {'ERROR'},
                "Video output needs ffmpeg.exe. Select it in File Extension or install FFmpeg in PATH.",
            )
            return {'CANCELLED'}
        try:
            probe_path = os.path.join(out_dir, f".fbp_write_probe_{time.monotonic_ns()}")
            with open(probe_path, "wb") as probe:
                probe.write(b"FBP")
                probe.flush()
            os.remove(probe_path)
        except OSError as exc:
            self.report({'ERROR'}, f"Render destination is not writable: {exc}")
            return {'CANCELLED'}
        expected_paths = []
        is_movie_format = bool(getattr(sc.render, "is_movie_format", False))
        movie_output_path = ""
        if is_movie_format:
            try:
                movie_output_path = os.path.normpath(sc.render.frame_path(frame=start))
            except FBP_DATA_ERRORS:
                movie_output_path = ""
        else:
            for frame in scheduled_frames:
                try:
                    expected_paths.append(os.path.normpath(sc.render.frame_path(frame=frame)))
                except FBP_DATA_ERRORS:
                    expected_paths = []
                    break
        if auto_video:
            movie_output_path = str(resolved_output.get("video_path", "") or "")
        accept_existing_outputs = not bool(getattr(sc.render, "use_overwrite", True))
        existing_frames = set()
        if expected_paths:
            normalized_to_frame = {}
            for frame, path in zip(scheduled_frames, expected_paths, strict=False):
                normalized = os.path.normcase(os.path.abspath(path))
                previous = normalized_to_frame.get(normalized)
                if previous is not None and previous != frame:
                    self.report(
                        {'ERROR'},
                        f"Output naming maps Frames {previous} and {frame} to the same file",
                    )
                    return {'CANCELLED'}
                normalized_to_frame[normalized] = frame
                if accept_existing_outputs:
                    try:
                        if os.path.isfile(path) and os.path.getsize(path) > 0:
                            existing_frames.add(frame)
                    except OSError:
                        pass
            if (
                accept_existing_outputs
                and len(existing_frames) == len(scheduled_frames)
                and not auto_video
            ):
                FBP_BG_RENDER_STATE.update({
                    "out_dir": out_dir,
                    "prefix": prefix,
                    "output_path": output_path,
                    "expected_paths": tuple(expected_paths),
                    "scheduled_frames": scheduled_frames,
                    "rendered_frames": set(existing_frames),
                    "filesystem_progress": len(existing_frames),
                    "start": start,
                    "end": end,
                    "step": step,
                    "total": len(scheduled_frames),
                })
                _fbp_bg_update_scene_status(
                    sc, f"All {len(scheduled_frames)} output frames already exist"
                )
                self.report({'INFO'}, "All scheduled output frames already exist")
                return {'FINISHED'}

        blender_bin = os.path.abspath(str(getattr(bpy.app, "binary_path", "") or ""))
        if not blender_bin or not os.path.isfile(blender_bin):
            self.report({'ERROR'}, "Could not locate the current Blender executable")
            return {'CANCELLED'}

        # Render an isolated snapshot. Saving the active project in-place here
        # could overwrite unrelated user changes and couples the render process
        # to the live Main. copy=True keeps the current .blend active while
        # relative_remap=True preserves external media paths in the snapshot.
        temp_dir = tempfile.mkdtemp(prefix="fbp_bg_render_")
        snapshot_path = os.path.join(temp_dir, "frame_by_plane_render_snapshot.blend")
        pause_before = bool(fbp_runtime_get("fbp_pause_managed_timers", False))
        try:
            resume_before = float(
                fbp_runtime_get("fbp_managed_timers_resume_after", 0.0) or 0.0
            )
        except (TypeError, ValueError):
            resume_before = 0.0
        # save_as_mainfile(copy=True) serializes the complete Main database.  Do
        # not let an idle maintenance timer alter layers, masks or generated IDs
        # halfway through the snapshot transaction.
        fbp_runtime_set("fbp_pause_managed_timers", True)
        try:
            result = bpy.ops.wm.save_as_mainfile(
                filepath=snapshot_path,
                copy=True,
                relative_remap=True,
                check_existing=False,
            )
            if 'FINISHED' not in result or not os.path.isfile(snapshot_path):
                raise RuntimeError("Blender did not create the render snapshot")
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            self.report({'ERROR'}, f"Could not create background render snapshot: {exc}")
            return {'CANCELLED'}
        finally:
            fbp_runtime_set("fbp_pause_managed_timers", pause_before)
            if pause_before:
                fbp_runtime_set("fbp_managed_timers_resume_after", resume_before)
            else:
                fbp_runtime_set(
                    "fbp_managed_timers_resume_after",
                    max(resume_before, time.monotonic() + 0.50),
                )

        scene_name = str(getattr(sc, "name", "Scene") or "Scene")
        self._session_token = f"{time.monotonic_ns()}:{id(self)}"
        state_path = os.path.join(temp_dir, "fbp_background_render_state.json")
        stop_path = os.path.join(temp_dir, "fbp_background_render_stop.request")
        initial_completed = len(existing_frames)
        script = f"""
import bpy
import importlib
import json
import os
import subprocess
import sys
import time
import traceback

SCENE_NAME = {scene_name!r}
OUTPUT_PATH = {output_path!r}
START = {start}
END = {end}
STEP = {step}
TOTAL = {len(scheduled_frames)}
INITIAL_COMPLETED = {initial_completed}
SESSION_TOKEN = {self._session_token!r}
STATE_PATH = {state_path!r}
STOP_PATH = {stop_path!r}
AUTO_VIDEO = {auto_video!r}
VIDEO_PATH = {movie_output_path!r}
FFMPEG_EXECUTABLE = {ffmpeg_executable!r}
FPS = {float(sc.render.fps) / max(float(sc.render.fps_base), 1.0e-8)!r}
OVERWRITE = {bool(getattr(sc.render, "use_overwrite", True))!r}
ADDON_PACKAGE = {__package__!r}
ADDON_PARENT = {os.path.dirname(os.path.dirname(__file__))!r}

_state = {{
    "session_token": SESSION_TOKEN,
    "status": "STARTING",
    "current_frame": START,
    "rendered_count": INITIAL_COMPLETED,
    "total": TOTAL,
    "updated_at": time.time(),
    "error": "",
}}

def _write_state(status=None, **updates):
    if status is not None:
        _state["status"] = str(status)
    _state.update(updates)
    _state["updated_at"] = time.time()
    temp_path = STATE_PATH + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as stream:
            json.dump(_state, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            if str(_state.get("status", "")).upper() in {{"DONE", "ERROR"}}:
                os.fsync(stream.fileno())
        os.replace(temp_path, STATE_PATH)
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

if not bool(getattr(bpy.app, "background", False)):
    raise RuntimeError("Frame By Plane background render child was not started with -b")
if tuple(getattr(bpy.app, "version", (0, 0, 0)))[:3] < (5, 2, 0):
    raise RuntimeError(f"Blender 5.2.0 or newer is required, got {{bpy.app.version_string}}")
if not hasattr(bpy.types, "FBP_OT_repair_render_state_background"):
    if ADDON_PARENT and ADDON_PARENT not in sys.path:
        sys.path.insert(0, ADDON_PARENT)
    importlib.import_module(ADDON_PACKAGE).register()

def _app_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value or "")

scene = bpy.data.scenes.get(SCENE_NAME) or bpy.context.scene
if scene is None:
    raise RuntimeError(f"Scene not found: {{SCENE_NAME}}")
scene["fbp_background_render_child"] = True
scene.frame_start = START
scene.frame_end = END
scene.frame_step = STEP
scene.render.filepath = OUTPUT_PATH
if hasattr(scene.render, "save_output"):
    scene.render.save_output = True
# The child process is isolated from interactive editing, so Blender can safely
# retain render data between animation frames.  This is especially valuable for
# Cycles and effect-heavy scenes and does not alter the saved authoring file.
if hasattr(scene.render, "use_persistent_data"):
    scene.render.use_persistent_data = True

first_path = scene.render.frame_path(frame=START)
os.makedirs(os.path.dirname(first_path) or os.path.dirname(OUTPUT_PATH), exist_ok=True)
_write_state(
    "VALIDATING",
    blender_version=".".join(str(int(value)) for value in tuple(bpy.app.version)[:3]),
    blender_version_cycle=_app_text(getattr(bpy.app, "version_cycle", "")),
    blender_build_hash=_app_text(getattr(bpy.app, "build_hash", "")),
    blender_build_date=_app_text(getattr(bpy.app, "build_commit_date", "")),
    persistent_data=bool(getattr(scene.render, "use_persistent_data", False)),
)

result = bpy.ops.fbp.repair_render_state_background()
print(f"[FBP_BG] Native render-state validation: {{result}}", flush=True)
if 'FINISHED' not in result:
    raise RuntimeError("Frame By Plane render-state validation failed")

_new_rendered = 0
_last_started_frame = None
_finalize_result = {{'CANCELLED'}}

def _fbp_bg_mark_frame_start(_scene):
    global _last_started_frame
    frame = int(_scene.frame_current)
    if frame == _last_started_frame:
        return
    _last_started_frame = frame
    now = time.time()
    print(f"[FBP_BG_FRAME_START] {{frame}}|{{now}}", flush=True)
    _write_state("RENDERING", current_frame=frame)

def _fbp_bg_render_pre(_scene):
    _fbp_bg_mark_frame_start(_scene)

def _fbp_bg_frame_change_post(_scene, _depsgraph=None):
    _fbp_bg_mark_frame_start(_scene)

def _fbp_bg_render_write(_scene):
    global _new_rendered
    frame = int(_scene.frame_current)
    try:
        path = _scene.render.frame_path(frame=frame)
    except Exception:
        path = ""
    _new_rendered += 1
    now = time.time()
    print(f"[FBP_BG_FRAME] {{frame}}/{{END}}|{{path}}|{{now}}", flush=True)
    _write_state(
        "RENDERING",
        current_frame=frame,
        rendered_count=min(TOTAL, INITIAL_COMPLETED + _new_rendered),
        last_output=path,
    )

bpy.app.handlers.render_pre.append(_fbp_bg_render_pre)
bpy.app.handlers.frame_change_post.append(_fbp_bg_frame_change_post)
bpy.app.handlers.render_write.append(_fbp_bg_render_write)
try:
    if os.path.exists(STOP_PATH):
        raise RuntimeError("Render stopped before start")
    _write_state("RENDERING", current_frame=START)
    print(
        f"[FBP_BG] Rendering frames {{START}}-{{END}} step {{STEP}} -> {{OUTPUT_PATH}}",
        flush=True,
    )
    render_result = bpy.ops.render.render(animation=True, scene=scene.name)
    if 'FINISHED' not in render_result:
        raise RuntimeError(f"Blender animation render returned: {{render_result}}")
except Exception as exc:
    error = f"{{type(exc).__name__}}: {{exc}}"
    _write_state("ERROR", error=error)
    print(f"[FBP_BG_ERROR] {{error}}", flush=True)
    traceback.print_exc()
    raise
finally:
    for handlers, callback in (
        (bpy.app.handlers.render_pre, _fbp_bg_render_pre),
        (bpy.app.handlers.frame_change_post, _fbp_bg_frame_change_post),
        (bpy.app.handlers.render_write, _fbp_bg_render_write),
    ):
        try:
            handlers.remove(callback)
        except ValueError:
            pass
    try:
        _finalize_result = bpy.ops.fbp.finalize_render_state_background()
        print(f"[FBP_BG] Render-state finalization: {{_finalize_result}}", flush=True)
    except Exception as finalize_exc:
        print(f"[FBP_BG_ERROR] Render-state finalization failed: {{finalize_exc}}", flush=True)
if 'FINISHED' not in _finalize_result:
    raise RuntimeError("Frame By Plane background render-state finalization failed")
if AUTO_VIDEO:
    try:
        if not FFMPEG_EXECUTABLE or not os.path.isfile(FFMPEG_EXECUTABLE):
            raise RuntimeError("FFmpeg executable is missing")
        if not (VIDEO_PATH and os.path.isfile(VIDEO_PATH) and not OVERWRITE):
            manifest_path = STATE_PATH + ".ffconcat"
            duration = max(1.0 / max(FPS, 1.0e-6), STEP / max(FPS, 1.0e-6))
            frame_paths = [
                os.path.abspath(scene.render.frame_path(frame=frame))
                for frame in range(START, END + 1, STEP)
            ]
            missing = [path for path in frame_paths if not os.path.isfile(path)]
            if missing:
                raise RuntimeError(f"{{len(missing)}} PNG frame(s) are missing before video encoding")
            with open(manifest_path, "w", encoding="utf-8", newline="") as stream:
                stream.write("ffconcat version 1.0" + chr(10))
                for frame_path in frame_paths:
                    escaped = frame_path.replace(os.sep, "/").replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))
                    stream.write(f"file '{{escaped}}'" + chr(10))
                    stream.write(f"duration {{duration:.9f}}" + chr(10))
                if frame_paths:
                    escaped = frame_paths[-1].replace(os.sep, "/").replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))
                    stream.write(f"file '{{escaped}}'" + chr(10))
            _write_state("ENCODING", current_frame=END, rendered_count=TOTAL)
            print(f"[FBP_BG] Encoding MP4 -> {{VIDEO_PATH}}", flush=True)
            command = [
                FFMPEG_EXECUTABLE,
                "-hide_banner", "-loglevel", "error",
                "-y" if OVERWRITE else "-n",
                "-f", "concat", "-safe", "0", "-i", manifest_path,
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", VIDEO_PATH,
            ]
            completed = subprocess.run(command, check=False)
            if completed.returncode != 0:
                raise RuntimeError(f"FFmpeg exited with code {{completed.returncode}}")
        if not os.path.isfile(VIDEO_PATH) or os.path.getsize(VIDEO_PATH) <= 0:
            raise RuntimeError("FFmpeg did not produce the expected MP4")
    except Exception as exc:
        error = f"{{type(exc).__name__}}: {{exc}}"
        _write_state("ERROR", error=error)
        print(f"[FBP_BG_ERROR] {{error}}", flush=True)
        traceback.print_exc()
        raise
_write_state("DONE", rendered_count=TOTAL, current_frame=END)
print("[FBP_BG] DONE", flush=True)
"""

        log_handle = None
        try:
            script_path = os.path.join(temp_dir, "fbp_background_render.py")
            log_path = os.path.join(temp_dir, "fbp_background_render.log")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script)

            cmd = [
                blender_bin,
                "-b",
                snapshot_path,
                "--python-exit-code",
                "2",
                "--python",
                script_path,
            ]
            log_handle = open(log_path, "w", encoding="utf-8")
            child_env = os.environ.copy()
            child_env["FBP_BACKGROUND_RENDER_CHILD"] = "1"
            child_env["PYTHONUNBUFFERED"] = "1"
            popen_kwargs = {
                "stdout": log_handle,
                "stderr": subprocess.STDOUT,
                "env": child_env,
                "cwd": temp_dir,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = int(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                )
            else:
                popen_kwargs["start_new_session"] = True
            proc = subprocess.Popen(cmd, **popen_kwargs)
            # Popen duplicates the redirected handle for the child. Closing the
            # parent copy avoids keeping a Windows file handle alive for the
            # entire render and still allows incremental read-only log parsing.
            log_handle.close()
            log_handle = None
        except (OSError, RuntimeError, ValueError) as exc:
            if log_handle is not None:
                try:
                    log_handle.close()
                except OSError:
                    pass
            if temp_dir:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except (OSError, RuntimeError, TypeError, ValueError):
                    pass
            self.report({'ERROR'}, f"Could not start background render: {exc}")
            return {'CANCELLED'}

        _fbp_bg_reset_progress_state()
        FBP_BG_RENDER_STATE.update({
            "process": proc,
            "session_token": self._session_token,
            "scene_name": str(getattr(sc, "name", "") or ""),
            "log_handle": log_handle,
            "log_path": log_path,
            "state_path": state_path,
            "stop_path": stop_path,
            "temp_dir": temp_dir,
            "out_dir": out_dir,
            "prefix": prefix,
            "output_path": output_path,
            "expected_paths": tuple(expected_paths),
            "scheduled_frames": scheduled_frames,
            "rendered_frames": set(existing_frames),
            "filesystem_progress": len(existing_frames),
            "state_progress": len(existing_frames),
            "is_movie_format": is_movie_format,
            "auto_video": auto_video,
            "requires_movie_output": bool(is_movie_format or auto_video),
            "movie_output_path": movie_output_path,
            "accept_existing_outputs": accept_existing_outputs,
            "start": start,
            "end": end,
            "step": step,
            "total": len(scheduled_frames),
            "started_at": time.time(),
        })
        _fbp_bg_update_scene_status(sc, f"Rendering starting · {len(scheduled_frames)} frames total")

        try:
            self._timer = context.window_manager.event_timer_add(0.75, window=context.window)
            if self._timer not in _FBP_BG_RENDER_MODAL_TIMERS:
                _FBP_BG_RENDER_MODAL_TIMERS.append(self._timer)
            context.window_manager.modal_handler_add(self)
            _FBP_ACTIVE_BG_RENDER_OPERATOR = self
        except FBP_DATA_ERRORS as exc:
            if _FBP_ACTIVE_BG_RENDER_OPERATOR is self:
                _FBP_ACTIVE_BG_RENDER_OPERATOR = None
            self._timer = None
            stopped = _fbp_bg_terminate_process(sc)
            if stopped:
                _fbp_preserve_background_log(success=False)
                FBP_BG_RENDER_STATE["session_token"] = ""
                _fbp_bg_cleanup_temp_files()
                FBP_BG_RENDER_STATE["state_path"] = ""
                FBP_BG_RENDER_STATE["stop_path"] = ""
                _fbp_bg_update_scene_status(sc, "Background render monitor could not start")
            self.report({'ERROR'}, f"Could not monitor background render: {exc}")
            return {'CANCELLED'}

        # A global scheduler callback monitors the child when WindowManager
        # TIMER events are temporarily blocked by another modal UI. It retains
        # only primitive state from FBP_BG_RENDER_STATE, never this Operator or
        # its WindowManager timer RNA.
        try:
            accepted = schedule_task(
                _FBP_BG_WATCHDOG_TASK_KEY,
                _fbp_background_app_watchdog,
                delay=0.25,
                priority=PRIORITY_CRITICAL,
                category="background_render",
                persistent=True,
                restart=True,
                allow_during_undo=True,
                allow_during_render=True,
            )
            if accepted:
                self._app_watchdog_key = _FBP_BG_WATCHDOG_TASK_KEY
                _FBP_BG_RENDER_APP_WATCHDOGS.add(_FBP_BG_WATCHDOG_TASK_KEY)
            else:
                self._app_watchdog_key = ""
        except FBP_DATA_IO_ERRORS:
            self._app_watchdog_key = ""

        try:
            bpy.ops.fbp.background_render_status('INVOKE_DEFAULT')
        except FBP_DATA_IO_ERRORS:
            pass

        self.report({'INFO'}, f"Background render started: {start}-{end}")
        return {'RUNNING_MODAL'}

class FBP_OT_StopBackgroundRender(Operator):
    bl_idname      = "fbp.stop_background_render"
    bl_label       = "Stop Background Render"
    bl_description = "Stop the active Frame By Plane background render process"
    bl_options     = {'REGISTER'}

    def execute(self, context):
        if _fbp_bg_terminate_process(context.scene):
            cancel_task(_FBP_BG_WATCHDOG_TASK_KEY)
            _FBP_BG_RENDER_APP_WATCHDOGS.discard(_FBP_BG_WATCHDOG_TASK_KEY)
            _fbp_bg_finalize_runtime(
                context.scene,
                "Background render stopped",
                success=False,
                expected_token=str(FBP_BG_RENDER_STATE.get("session_token", "") or ""),
            )
            self.report({'INFO'}, "Background render stopped")
            return {'FINISHED'}
        if _fbp_bg_process_running():
            self.report({'ERROR'}, "Could not confirm that the background render stopped")
        else:
            self.report({'WARNING'}, "No background render is running")
        return {'CANCELLED'}

class FBP_OT_BackgroundRenderStatus(Operator):
    bl_idname      = "fbp.background_render_status"
    bl_label       = "Background Render Status"
    bl_description = "Show the current Frame By Plane background render status"
    bl_options     = {'REGISTER'}

    def draw(self, context):
        sc = context.scene
        layout = configure_layout(self.layout)
        total = int(getattr(sc, 'fbp_background_render_total', 0) or 0)
        progress = int(getattr(sc, 'fbp_background_render_progress', 0) or 0)
        remaining = max(0, total - progress)

        status_box = layout.box()
        configure_layout(status_box)
        section_header(status_box, "Background Render", icon='RENDER_ANIMATION')
        hint_row(
            status_box,
            getattr(sc, 'fbp_background_render_status', 'Idle'),
            icon='INFO',
            disabled=False,
        )
        if total > 0:
            row = status_box.row(align=True)
            row.label(text=f"Rendered {progress} / {total}", icon='RENDER_RESULT')
            row.label(text=f"Remaining {remaining}", icon='TIME')
            current_frame = int(getattr(sc, 'fbp_background_render_current_frame', 0) or 0)
            eta = str(getattr(sc, 'fbp_background_render_eta', '') or '')
            detail = status_box.row(align=True)
            if current_frame or int(getattr(sc, 'frame_start', 0) or 0) == 0:
                detail.label(text=f"Frame {current_frame}", icon='KEYTYPE_KEYFRAME_VEC')
            if eta:
                detail.label(text=f"ETA {eta}", icon='PREVIEW_RANGE')
        out_dir = getattr(sc, 'fbp_background_render_output_dir', '') or ''
        if out_dir:
            hint_row(status_box, out_dir, icon='FILE_FOLDER', disabled=False)
        last_log = str(getattr(sc, 'fbp_background_render_last_log', '') or '')
        if last_log:
            log_row = status_box.row(align=True)
            log_row.label(text=last_log, icon='TEXT')
            open_log = log_row.operator('wm.path_open', text='', icon='FILE_FOLDER')
            open_log.filepath = last_log
        if getattr(sc, 'fbp_background_render_running', False):
            action = layout.row(align=True)
            action.scale_y = 1.08
            action.operator('fbp.stop_background_render', icon='CANCEL', text='Stop Render')

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        # Refresh before opening the dialog. ``draw`` must remain read-only and
        # must never parse logs or write Scene RNA during a UI redraw.
        _fbp_bg_update_scene_status(context.scene)
        return context.window_manager.invoke_props_dialog(self, width=420)


def quiesce_background_render_runtime():
    """Stop every render monitor before its Operator class is unregistered."""
    global _FBP_ACTIVE_BG_RENDER_OPERATOR
    active = _FBP_ACTIVE_BG_RENDER_OPERATOR
    _FBP_ACTIVE_BG_RENDER_OPERATOR = None
    if active is not None:
        try:
            active._remove_app_watchdog()
        except FBP_DATA_ERRORS:
            pass
        try:
            active._remove_modal_timer(bpy.context)
        except FBP_DATA_ERRORS:
            pass
    try:
        wm = getattr(getattr(bpy, "context", None), "window_manager", None)
        for timer in tuple(_FBP_BG_RENDER_MODAL_TIMERS):
            try:
                if wm is not None:
                    wm.event_timer_remove(timer)
            except FBP_DATA_ERRORS:
                continue
    except FBP_DATA_ERRORS:
        pass
    _FBP_BG_RENDER_MODAL_TIMERS.clear()
    cancel_task(_FBP_BG_WATCHDOG_TASK_KEY)
    for key in tuple(_FBP_BG_RENDER_APP_WATCHDOGS):
        try:
            if callable(key):
                unregister_timer(key)
            else:
                cancel_task(str(key or ""))
        except FBP_DATA_IO_ERRORS:
            continue
    _FBP_BG_RENDER_APP_WATCHDOGS.clear()
    scene = getattr(getattr(bpy, "context", None), "scene", None)
    if _fbp_bg_process_running():
        if _fbp_bg_terminate_process(scene):
            _fbp_preserve_background_log(success=False)
            _fbp_bg_clear_runtime_state(scene)
            return True
        return False
    _fbp_bg_clear_runtime_state(scene)
    return True


def register():
    """Register only the render validator in the dedicated background child."""
    global _FBP_CHILD_REPAIR_REGISTERED
    if not (
        bool(getattr(bpy.app, "background", False))
        and os.environ.get("FBP_BACKGROUND_RENDER_CHILD") == "1"
    ):
        return
    register_classes((
        FBP_OT_RepairRenderStateBackground,
        FBP_OT_FinalizeRenderStateBackground,
    ))
    _FBP_CHILD_REPAIR_REGISTERED = True


def unregister():
    """Do not leave child processes, modal timers or temporary files after unload."""
    global _FBP_CHILD_REPAIR_REGISTERED
    if _FBP_CHILD_REPAIR_REGISTERED or (
        bool(getattr(bpy.app, "background", False))
        and os.environ.get("FBP_BACKGROUND_RENDER_CHILD") == "1"
    ):
        unregister_classes((
            FBP_OT_RepairRenderStateBackground,
            FBP_OT_FinalizeRenderStateBackground,
        ))
        _FBP_CHILD_REPAIR_REGISTERED = False
    quiesce_background_render_runtime()
