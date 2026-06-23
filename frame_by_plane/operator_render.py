"""Focused Frame by Plane operator module."""

import os
import re
import shutil
import subprocess
import tempfile
import time

import bpy
from bpy.types import Operator

from .runtime import FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS
from .core import fbp_repair_all_render_state
from .scene_sync import sync_layer_collection
from .operator_common import (
    FBP_BG_RENDER_STATE,
    _fbp_bg_cleanup_temp_files,
    _fbp_bg_clear_runtime_state,
    _fbp_bg_process_running,
    _fbp_bg_process_status,
    _fbp_bg_read_progress_log,
    _fbp_bg_reset_progress_state,
    _fbp_bg_terminate_process,
    _fbp_bg_update_scene_status,
)




_FBP_INVALID_RENDER_PREFIX_RE = re.compile(r'[<>:"/\\|?*\x00-\x1F]+')


_FBP_BG_RENDER_MODAL_TIMERS = globals().get("_FBP_BG_RENDER_MODAL_TIMERS", [])

class FBP_OT_RepairRenderState(Operator):
    bl_idname      = "fbp.repair_render_state"
    bl_label       = "Repair FBP Render State"
    bl_description = "Validate native media, timing, material slots, UVs and material indices before rendering"
    bl_options     = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sync_layer_collection(context)
        expected = sum(
            1 for obj in context.scene.objects
            if bool(getattr(obj, "is_fbp_control", False))
        )
        fixed = fbp_repair_all_render_state(
            context.scene, context.scene.frame_current
        )
        if fixed != expected:
            self.report(
                {'ERROR'},
                f"Render validation failed on {expected - fixed} of {expected} FBP layer(s)",
            )
            return {'CANCELLED'}
        self.report({'INFO'}, f"Render state validated on {fixed} FBP layer(s)")
        return {'FINISHED'}

class FBP_OT_BackgroundRenderFrames(Operator):
    bl_idname      = "fbp.background_render_frames"
    bl_label       = "Background Render FBP Frames"
    bl_description = "Render frames in a separate Blender process without blocking the UI"
    bl_options     = {'REGISTER'}

    _timer = None
    _session_token = ""

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

    def _finish_modal(self, context, status_message, result=None):
        if result is None:
            result = {'FINISHED'}
        self._remove_modal_timer(context)
        if not self._owns_render_state():
            return result
        # Consume the final child-process markers before deleting the temporary
        # log. A single final filesystem verification covers engines that omit a
        # render_write callback without scanning the output folder every tick.
        _fbp_bg_update_scene_status(
            context.scene, None, force_filesystem_scan=True
        )
        FBP_BG_RENDER_STATE["process"] = None
        FBP_BG_RENDER_STATE["session_token"] = ""
        _fbp_bg_cleanup_temp_files()
        _fbp_bg_update_scene_status(context.scene, status_message)
        try:
            context.area.tag_redraw()
        except FBP_DATA_IO_ERRORS:
            pass
        return result

    def modal(self, context, event):
        if not self._owns_render_state():
            self._remove_modal_timer(context)
            return {'CANCELLED'}
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
            proc = FBP_BG_RENDER_STATE.get("process")
            _fbp_bg_update_scene_status(context.scene)
            try:
                for area in context.screen.areas:
                    area.tag_redraw()
            except FBP_DATA_IO_ERRORS:
                pass
            running, code, state_known = _fbp_bg_process_status()
            if not state_known:
                # A failed poll is not proof of completion. Preserve process,
                # token and temporary files and try again on the next timer.
                return {'RUNNING_MODAL'}
            if not proc or not running:
                if code in {None, 0}:
                    out_dir = FBP_BG_RENDER_STATE.get("out_dir", "")
                    self.report({'INFO'}, f"Background render finished: {out_dir}")
                    return self._finish_modal(context, "Background render finished", {'FINISHED'})
                _fbp_bg_read_progress_log()
                detail = str(FBP_BG_RENDER_STATE.get("last_log_message", "") or "").strip()
                report_message = f"Background render stopped or failed with code {code}"
                if detail:
                    report_message += f": {detail[:220]}"
                self.report({'WARNING'}, report_message)
                return self._finish_modal(
                    context,
                    f"Stopped or failed with code {code}" + (f" · {detail[:160]}" if detail else ""),
                    {'CANCELLED'},
                )
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def execute(self, context):
        sc = context.scene
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

        # Always render the Scene timeline In/Out. Keeping one authoritative
        # range avoids mismatches between the Timeline, Output properties and
        # the background Blender process.
        start = int(sc.frame_start)
        end = int(sc.frame_end)
        if end < start:
            self.report({'WARNING'}, "Scene Out must be after Scene In")
            return {'CANCELLED'}

        configured_dir = str(getattr(sc, 'fbp_render_output_dir', '') or '').strip()
        if configured_dir:
            out_dir = bpy.path.abspath(configured_dir)
        else:
            out_dir = os.path.join(os.path.dirname(bpy.data.filepath), "FBP_Render_Frames")
        out_dir = os.path.normpath(out_dir)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            self.report({'ERROR'}, f"Could not create render folder: {exc}")
            return {'CANCELLED'}
        if not os.path.isdir(out_dir):
            self.report({'ERROR'}, "The selected render output path is not a folder")
            return {'CANCELLED'}

        raw_prefix = str(getattr(sc, 'fbp_render_prefix', '') or 'frame_').strip()
        prefix = os.path.basename(raw_prefix) or "frame_"
        prefix = _FBP_INVALID_RENDER_PREFIX_RE.sub('_', prefix).strip(' .') or "frame_"
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

        script = f"""
import bpy
import os

OUT_DIR = {out_dir!r}
START = {start}
END = {end}
PREFIX = {prefix!r}

scene = bpy.context.scene
os.makedirs(OUT_DIR, exist_ok=True)

# Validate only the isolated snapshot, never the live interactive project.
result = bpy.ops.fbp.repair_render_state()
print(f"[FBP_BG] Native render-state validation: {{result}}", flush=True)
if 'FINISHED' not in result:
    raise RuntimeError("Frame by Plane render-state validation failed")

scene.frame_start = START
scene.frame_end = END
scene.render.image_settings.file_format = 'PNG'
if hasattr(scene.render, "use_file_extension"):
    scene.render.use_file_extension = True

# Background safety: keep procedural FBP Color/Gradient/Holdout planes out of
# the viewport while rendering. They remain renderable unless the layer is muted.
try:
    for obj in list(scene.objects):
        if getattr(obj, "is_fbp_control", False):
            obj.hide_render = True
            plane = getattr(obj, "fbp_plane_target", None)
            if plane and getattr(plane, "is_fbp_plane", False):
                plane.hide_render = not bool(getattr(obj, "fbp_is_visible", True))
                if getattr(obj, "fbp_is_color_plane", False):
                    plane.hide_viewport = True
except Exception as exc:
    print(f"[FBP_BG] Viewport render guard skipped: {{exc}}", flush=True)

# Use one native animation render job. The previous per-frame write_still loop
# repeatedly created and destroyed Blender render sessions and image buffers,
# which was slower and amplified native image-cache lifecycle risk.
scene.render.filepath = os.path.join(OUT_DIR, PREFIX)

def _fbp_bg_render_write(_scene):
    print(f"[FBP_BG_FRAME] {{int(_scene.frame_current)}}/{{END}}", flush=True)

bpy.app.handlers.render_write.append(_fbp_bg_render_write)
try:
    print(f"[FBP_BG] Rendering frames {{START}}-{{END}} -> {{OUT_DIR}}", flush=True)
    bpy.ops.render.render(animation=True)
finally:
    try:
        bpy.app.handlers.render_write.remove(_fbp_bg_render_write)
    except ValueError:
        pass
print("[FBP_BG] DONE", flush=True)
"""

        log_handle = None
        try:
            script_path = os.path.join(temp_dir, "fbp_background_render.py")
            log_path = os.path.join(temp_dir, "fbp_background_render.log")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script)

            cmd = [blender_bin, "-b", snapshot_path, "--python", script_path]
            log_handle = open(log_path, "w", encoding="utf-8")
            proc = subprocess.Popen(cmd, stdout=log_handle, stderr=subprocess.STDOUT)
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

        self._session_token = f"{time.monotonic_ns()}:{id(self)}"
        _fbp_bg_reset_progress_state()
        FBP_BG_RENDER_STATE.update({
            "process": proc,
            "session_token": self._session_token,
            "log_handle": log_handle,
            "log_path": log_path,
            "temp_dir": temp_dir,
            "out_dir": out_dir,
            "prefix": prefix,
            "start": start,
            "end": end,
            "total": max(0, end - start + 1),
            "started_at": time.time(),
        })
        _fbp_bg_update_scene_status(sc, f"Rendering starting · {max(0, end - start + 1)} frames total")

        try:
            self._timer = context.window_manager.event_timer_add(0.75, window=context.window)
            if self._timer not in _FBP_BG_RENDER_MODAL_TIMERS:
                _FBP_BG_RENDER_MODAL_TIMERS.append(self._timer)
            context.window_manager.modal_handler_add(self)
        except FBP_DATA_ERRORS as exc:
            self._timer = None
            _fbp_bg_terminate_process(sc)
            self.report({'ERROR'}, f"Could not monitor background render: {exc}")
            return {'CANCELLED'}

        try:
            bpy.ops.fbp.background_render_status('INVOKE_DEFAULT')
        except FBP_DATA_IO_ERRORS:
            pass

        self.report({'INFO'}, f"Background render started: {start}-{end}")
        return {'RUNNING_MODAL'}

class FBP_OT_StopBackgroundRender(Operator):
    bl_idname      = "fbp.stop_background_render"
    bl_label       = "Stop Background Render"
    bl_description = "Stop the active Frame by Plane background render process"
    bl_options     = {'REGISTER'}

    def execute(self, context):
        if _fbp_bg_terminate_process(context.scene):
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
    bl_description = "Show the current Frame by Plane background render status"
    bl_options     = {'REGISTER'}

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        total = int(getattr(sc, 'fbp_background_render_total', 0) or 0)
        progress = int(getattr(sc, 'fbp_background_render_progress', 0) or 0)
        remaining = max(0, total - progress)
        layout.label(text=getattr(sc, 'fbp_background_render_status', 'Idle'), icon='RENDER_ANIMATION')
        if total > 0:
            layout.label(text=f"Rendered: {progress}/{total} · Remaining: {remaining}")
        out_dir = getattr(sc, 'fbp_background_render_output_dir', '') or ''
        if out_dir:
            layout.label(text=out_dir, icon='FILE_FOLDER')
        if getattr(sc, 'fbp_background_render_running', False):
            layout.operator('fbp.stop_background_render', icon='CANCEL', text='Stop Render')

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        # Refresh before opening the dialog. ``draw`` must remain read-only and
        # must never parse logs or write Scene RNA during a UI redraw.
        _fbp_bg_update_scene_status(context.scene)
        return context.window_manager.invoke_props_dialog(self, width=420)


def unregister():
    """Do not leave child processes, modal timers or temporary files after unload."""
    try:
        wm = getattr(bpy.context, "window_manager", None)
        for timer in list(_FBP_BG_RENDER_MODAL_TIMERS):
            try:
                if wm is not None:
                    wm.event_timer_remove(timer)
            except FBP_DATA_ERRORS:
                pass
        _FBP_BG_RENDER_MODAL_TIMERS.clear()
    except FBP_DATA_ERRORS:
        _FBP_BG_RENDER_MODAL_TIMERS.clear()
    scene = getattr(getattr(bpy, "context", None), "scene", None)
    if _fbp_bg_process_running():
        _fbp_bg_terminate_process(scene)
    else:
        _fbp_bg_clear_runtime_state(scene)
