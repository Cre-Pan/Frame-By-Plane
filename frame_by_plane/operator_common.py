"""Shared imports, state and helper functions for Frame By Plane operators.

Operator classes live in focused modules and depend on this module only.
"""


import bpy
import json
import os
import shutil
import signal
import subprocess
import time


from . import safe_tasks as _safe_tasks

from .core import (
    fbp_native_sequence_files_from_rig,
    fbp_rig_native_sequence_needs_rename,
)
from .layers import (
    get_or_create_child_collection,
    is_fbp_layer_object,
    set_collection_color_tag,
)
from .service_registry import call_service, register_service, unregister_service
from .generation_transaction import active_generation_owner
from .runtime import (
    fbp_warn, FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS,
    fbp_obj_runtime_key, fbp_obj_matches_runtime_key, fbp_tag_redraw,
    fbp_runtime_get, fbp_runtime_set,
)
from .ui_context import restore_modal_cursor
from .ui_list_state import (
    clear_anchor,
    ensure_unique_item_identities,
    identity_at,
    index_for_identity,
    restore_active_index,
    store_anchor,
    transient_get,
    transient_set,
)


_FBP_UI_MODAL_MUTATION_DEPTH_KEY = "fbp_ui_modal_mutation_depth"
_FBP_UI_MODAL_MUTATION_DEADLINE_KEY = "fbp_ui_modal_mutation_deadline"


def fbp_begin_ui_modal_mutation(owner=None):
    """Pause deferred RNA mutations while one interactive UIList drag is active."""
    if owner is not None and bool(getattr(owner, "_fbp_ui_modal_mutation_active", False)):
        return True
    try:
        depth = max(0, int(fbp_runtime_get(_FBP_UI_MODAL_MUTATION_DEPTH_KEY, 0) or 0)) + 1
        fbp_runtime_set(_FBP_UI_MODAL_MUTATION_DEPTH_KEY, depth)
        fbp_runtime_set(_FBP_UI_MODAL_MUTATION_DEADLINE_KEY, time.monotonic() + 60.0)
        if owner is not None:
            owner._fbp_ui_modal_mutation_active = True
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError, OverflowError):
        return False


def fbp_touch_ui_modal_mutation(owner=None):
    if owner is not None and not bool(getattr(owner, "_fbp_ui_modal_mutation_active", False)):
        return False
    try:
        if int(fbp_runtime_get(_FBP_UI_MODAL_MUTATION_DEPTH_KEY, 0) or 0) <= 0:
            return False
        fbp_runtime_set(_FBP_UI_MODAL_MUTATION_DEADLINE_KEY, time.monotonic() + 60.0)
        return True
    except (RuntimeError, TypeError, ValueError, OverflowError):
        return False


def fbp_end_ui_modal_mutation(owner=None):
    """Release the drag guard and leave one short notifier-safe settling window."""
    if owner is not None and not bool(getattr(owner, "_fbp_ui_modal_mutation_active", False)):
        return False
    try:
        depth = max(0, int(fbp_runtime_get(_FBP_UI_MODAL_MUTATION_DEPTH_KEY, 0) or 0) - 1)
        fbp_runtime_set(_FBP_UI_MODAL_MUTATION_DEPTH_KEY, depth)
        if depth <= 0:
            fbp_runtime_set(_FBP_UI_MODAL_MUTATION_DEADLINE_KEY, 0.0)
            current = float(fbp_runtime_get("fbp_managed_timers_resume_after", 0.0) or 0.0)
            fbp_runtime_set("fbp_managed_timers_resume_after", max(current, time.monotonic() + 0.20))
        if owner is not None:
            owner._fbp_ui_modal_mutation_active = False
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError, OverflowError):
        return False


class FBP_VerticalDragModalMixin:
    """Shared modal loop for vertically reordered Frame By Plane UI rows."""

    def _begin_modal_mutation(self):
        return fbp_begin_ui_modal_mutation(self)

    def _touch_modal_mutation(self):
        return fbp_touch_ui_modal_mutation(self)

    def _end_modal_mutation(self):
        return fbp_end_ui_modal_mutation(self)

    def _notify_drag_finished(self, context, *, cancelled):
        callback = getattr(self, '_on_drag_finished', None)
        if callable(callback):
            try:
                callback(context, cancelled=bool(cancelled))
            except Exception as exc:
                fbp_warn('Could not finalize UIList drag', exc)

    def _cancel_drag_transaction(self, context):
        """Restore the pre-drag state when the operator provides a snapshot.

        Older drag operators attempted to undo a cancelled gesture by replaying
        the opposite move for every recorded step.  That approach is fragile:
        each move can rebuild the source list, filters may change while the
        operator is running and one failed inverse step leaves a partially
        reordered list.  Operators can now implement ``_cancel_drag`` and
        restore one atomic snapshot instead.  The inverse-history fallback is
        kept for third-party operators that do not provide a snapshot.
        """
        custom_cancel = getattr(self, '_cancel_drag', None)
        if callable(custom_cancel):
            try:
                handled = custom_cancel(context)
                if handled is not False:
                    return True
            except Exception as exc:
                fbp_warn('Could not restore cancelled drag transaction', exc)

        inverse = {'UP': 'DOWN', 'DOWN': 'UP'}
        restored = True
        for direction in reversed(getattr(self, '_history', ())):
            if not self._move_once(context, inverse[direction]):
                restored = False
                break
        return restored

    def _restore_cursor(self, context):
        restore_modal_cursor(context)

    def modal(self, context, event):
        try:
            self._touch_modal_mutation()
            if event.type == 'MOUSEMOVE':
                self._saw_drag_motion = True
                mouse_y = int(getattr(event, 'mouse_y', self._anchor_y) or self._anchor_y)
                delta = mouse_y - self._anchor_y
                while abs(delta) >= self._threshold:
                    direction = 'UP' if delta > 0 else 'DOWN'
                    if not self._move_once(context, direction):
                        self._anchor_y = mouse_y
                        break
                    self._history.append(direction)
                    self._did_change = True
                    self._anchor_y += self._threshold if delta > 0 else -self._threshold
                    delta = mouse_y - self._anchor_y
                self._redraw(context)
                return {'RUNNING_MODAL'}

            if event.type in {'ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'}:
                self._cancel_drag_transaction(context)
                self._restore_cursor(context)
                self._end_modal_mutation()
                self._notify_drag_finished(context, cancelled=True)
                self._redraw(context)
                return {'CANCELLED'}

            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                if self._finish_on_release or self._saw_drag_motion:
                    self._restore_cursor(context)
                    self._end_modal_mutation()
                    changed = bool(getattr(self, '_did_change', False))
                    self._notify_drag_finished(context, cancelled=not changed)
                    self._redraw(context)
                    # Clicking a grip without crossing one reorder threshold must
                    # not create an empty Undo entry.
                    return {'FINISHED'} if changed else {'CANCELLED'}
                self._finish_on_release = True
                return {'RUNNING_MODAL'}

            return {'RUNNING_MODAL'}
        except Exception as exc:
            # A modal exception must never leave Blender's cursor override or the
            # global timer pause latched. Restore the original list snapshot when
            # available, then fail closed.
            try:
                fbp_warn('UIList drag aborted after an unexpected error', exc)
            except Exception:
                pass
            try:
                self._cancel_drag_transaction(context)
            except Exception:
                pass
            try:
                self._restore_cursor(context)
            except Exception:
                pass
            try:
                self._end_modal_mutation()
            except Exception:
                pass
            try:
                self._notify_drag_finished(context, cancelled=True)
                self._redraw(context)
            except Exception:
                pass
            return {'CANCELLED'}



def fbp_sequence_row_start_frame(rig, index):
    """Return the first scene frame occupied by a logical sequence row.

    The Frames UIList stores per-row durations. Timeline navigation always uses
    the first forward occurrence, including when playback is set to Ping-Pong.
    """
    if not rig:
        return None
    try:
        items = list(getattr(rig, "fbp_images", []))
        index = int(index)
        if not (0 <= index < len(items)):
            return None
        frame = int(getattr(rig, "fbp_start_frame", 1))
        for item in items[:index]:
            frame += max(1, int(getattr(item, "duration", 1) or 1))
        return frame
    except FBP_DATA_IO_ERRORS:
        return None


def fbp_jump_timeline_to_sequence_row(context, rig, index):
    """Move the current scene timeline to the selected logical frame row."""
    target = fbp_sequence_row_start_frame(rig, index)
    if target is None:
        return False
    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return False
    try:
        scene.frame_set(int(target))
        return True
    except FBP_DATA_ERRORS:
        try:
            scene.frame_current = int(target)
            return True
        except FBP_DATA_ERRORS:
            return False


def _fbp_refresh_pending_tree(context):
    """Refresh virtual Multiplane Setup UIList rows after operators change setup data."""
    from .ui_layout import fbp_refresh_pending_tree_rows
    if fbp_refresh_pending_tree_rows:
        try:
            fbp_refresh_pending_tree_rows(context)
        except FBP_DATA_IO_ERRORS:
            pass

def _fbp_active_pending_tree_row(scene):
    """Return the selected virtual setup tree row, or None."""
    try:
        idx = int(getattr(scene, 'fbp_pending_tree_rows_idx', 0))
        rows = getattr(scene, 'fbp_pending_tree_rows', [])
        if 0 <= idx < len(rows):
            return rows[idx]
    except FBP_DATA_IO_ERRORS:
        pass
    return None

def _fbp_active_pending_index_and_collection(scene):
    """Return (pending_index, collection_path, row_type) from the setup tree selection."""
    row = _fbp_active_pending_tree_row(scene)
    if row is not None:
        row_type = getattr(row, 'row_type', 'LAYER')
        if row_type == 'GROUP':
            return -1, (getattr(row, 'collection_path', '') or ''), 'GROUP'
        try:
            pending_index = int(getattr(row, 'pending_index', -1))
        except Exception:
            pending_index = -1
        if 0 <= pending_index < len(scene.fbp_pending_planes):
            return pending_index, getattr(scene.fbp_pending_planes[pending_index], 'collection_name', '') or '', 'LAYER'
    idx = int(getattr(scene, 'fbp_pending_planes_idx', 0))
    if 0 <= idx < len(scene.fbp_pending_planes):
        return idx, getattr(scene.fbp_pending_planes[idx], 'collection_name', '') or '', 'LAYER'
    return -1, '', 'NONE'

def _fbp_find_insert_index_for_pending(scene, active_index, collection_name):
    """Insert below the active layer, or at the end of the selected collection."""
    count = len(scene.fbp_pending_planes)
    collection_name = collection_name or ''
    if 0 <= active_index < count:
        return active_index + 1
    if collection_name:
        last = -1
        for i, item in enumerate(scene.fbp_pending_planes):
            if (getattr(item, 'collection_name', '') or '') == collection_name:
                last = i
        if last >= 0:
            return last + 1
    return count

_PREVIOUS_GENERATION_OVERLAY = globals().get("FBP_GENERATION_OVERLAY", {})
_PREVIOUS_GENERATION_TIMERS = globals().get("_FBP_GENERATION_TIMERS", ())
_PREVIOUS_GENERATION_OPERATORS = globals().get("_FBP_GENERATION_OPERATORS", ())


def _retire_generation_ui_on_reload():
    """Remove former draw/event handles before the new module accepts UI work."""
    retired = 0
    try:
        handle = (
            _PREVIOUS_GENERATION_OVERLAY.get("handle")
            if isinstance(_PREVIOUS_GENERATION_OVERLAY, dict)
            else None
        )
        if handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
            retired += 1
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        wm = getattr(getattr(bpy, "context", None), "window_manager", None)
        for operator in tuple(_PREVIOUS_GENERATION_OPERATORS or ()):
            try:
                iterator = getattr(operator, "_fbp_generation_iterator", None)
                close_iterator = getattr(iterator, "close", None)
                if callable(close_iterator):
                    close_iterator()
                operator._fbp_generation_iterator = None
                operator._fbp_generation_cancelled = True
                operator._fbp_generation_timer = None
                operator._fbp_generation_deadline = 0.0
            except FBP_DATA_ERRORS:
                continue
        for timer in tuple(_PREVIOUS_GENERATION_TIMERS or ()):
            try:
                if wm is not None:
                    wm.event_timer_remove(timer)
                    retired += 1
            except FBP_DATA_ERRORS:
                continue
    except FBP_DATA_ERRORS:
        pass
    try:
        if hasattr(_PREVIOUS_GENERATION_OPERATORS, "clear"):
            _PREVIOUS_GENERATION_OPERATORS.clear()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return retired


_RETIRED_GENERATION_UI_HANDLES = _retire_generation_ui_on_reload()
_FBP_GENERATION_OPERATORS = []
FBP_GENERATION_OVERLAY = {
    "handle": None,
    "active": False,
    "text": "Generating Frame By Plane Sequence…",
}
_FBP_GENERATION_TIMERS = []

def _fbp_ui_scale(context=None):
    """Return Blender UI scale for POST_PIXEL overlays.

    Viewport overlays are drawn in pixels, so hardcoded padding/font sizes must
    follow Blender's UI scale to stay readable on HiDPI displays.
    """
    try:
        ctx = context or bpy.context
        prefs = getattr(ctx, "preferences", None)
        system = getattr(prefs, "system", None)
        value = float(getattr(system, "ui_scale", 1.0) or 1.0)
        return max(0.5, min(3.0, value))
    except FBP_DATA_IO_ERRORS:
        return 1.0

def _fbp_import_blf(gpu_module=None):
    """Return Blender's text drawing module with forward-compatible fallback."""
    try:
        blf_module = getattr(gpu_module, "blf", None) if gpu_module is not None else None
        if blf_module is not None:
            return blf_module
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        import blf as blf_module
        return blf_module
    except ImportError:
        return None

def _fbp_tag_view3d_redraw():
    fbp_tag_redraw(area_types={'VIEW_3D'}, all_windows=True)

def _fbp_draw_generation_overlay():
    if not FBP_GENERATION_OVERLAY.get("active"):
        return
    gpu = None
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
        blf = _fbp_import_blf(gpu)
        if blf is None:
            return

        region = bpy.context.region
        if not region:
            return

        ui_scale = _fbp_ui_scale()
        font_id = 0
        font_size = max(10, int(round(14 * ui_scale)))
        try:
            blf.size(font_id, font_size)
        except TypeError:
            blf.size(font_id, font_size, 72)

        text_value = str(FBP_GENERATION_OVERLAY.get("text") or "Generating Frame By Plane Sequence…")
        text_w, text_h = blf.dimensions(font_id, text_value)
        pad_x = 18.0 * ui_scale
        pad_y = 11.0 * ui_scale
        box_w = text_w + pad_x * 2.0
        box_h = text_h + pad_y * 2.0
        margin = 16.0 * ui_scale
        y_offset = 42.0 * ui_scale
        x = max(margin, (float(region.width) - box_w) * 0.5)
        y = max(margin, float(region.height) - box_h - y_offset)

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(
            shader,
            'TRIS',
            {
                "pos": (
                    (x, y),
                    (x + box_w, y),
                    (x + box_w, y + box_h),
                    (x, y + box_h),
                )
            },
            indices=((0, 1, 2), (0, 2, 3)),
        )
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_float("color", (0.045, 0.045, 0.045, 0.94))
        batch.draw(shader)

        blf.color(font_id, 0.95, 0.95, 0.95, 1.0)
        blf.position(font_id, x + pad_x, y + pad_y, 0)
        blf.draw(font_id, text_value)
        gpu.state.blend_set('NONE')
    except Exception:
        try:
            if gpu is not None:
                gpu.state.blend_set('NONE')
        except FBP_DATA_IO_ERRORS:
            pass

def _fbp_hide_generation_overlay(context=None):
    handle = FBP_GENERATION_OVERLAY.get("handle")
    FBP_GENERATION_OVERLAY["active"] = False
    FBP_GENERATION_OVERLAY["handle"] = None
    if handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
        except FBP_DATA_IO_ERRORS:
            pass
    try:
        target_context = context or bpy.context
        target_context.workspace.status_text_set(None)
    except FBP_DATA_IO_ERRORS:
        pass
    _fbp_tag_view3d_redraw()

def _fbp_show_generation_start_popup(context, title="Generating Frame By Plane Sequence"):
    """Show a temporary viewport overlay that can be removed programmatically."""
    _fbp_hide_generation_overlay(context)
    FBP_GENERATION_OVERLAY["text"] = f"{str(title or 'Generating Frame By Plane Sequence').rstrip('.…')}…"
    FBP_GENERATION_OVERLAY["active"] = True
    try:
        FBP_GENERATION_OVERLAY["handle"] = bpy.types.SpaceView3D.draw_handler_add(
            _fbp_draw_generation_overlay, (), 'WINDOW', 'POST_PIXEL'
        )
        _fbp_tag_view3d_redraw()
    except Exception:
        FBP_GENERATION_OVERLAY["active"] = False
        try:
            context.workspace.status_text_set("Generating Frame By Plane Sequence…")
        except FBP_DATA_IO_ERRORS:
            pass

def _fbp_add_generation_timer(context, operator, delay=0.20):
    """Defer heavy generation by one UI tick so the start popup can draw first."""
    try:
        safe_delay = max(0.0, float(delay))
        operator._fbp_generation_cancelled = False
        operator._fbp_generation_started = False
        operator._fbp_generation_deadline = time.perf_counter() + safe_delay
        operator._fbp_generation_timer = context.window_manager.event_timer_add(safe_delay, window=context.window)
        if operator._fbp_generation_timer not in _FBP_GENERATION_TIMERS:
            _FBP_GENERATION_TIMERS.append(operator._fbp_generation_timer)
        if operator not in _FBP_GENERATION_OPERATORS:
            _FBP_GENERATION_OPERATORS.append(operator)
        context.window_manager.modal_handler_add(operator)
        return {'RUNNING_MODAL'}
    except FBP_DATA_ERRORS as exc:
        # event_timer_add() may succeed before modal_handler_add() fails. Remove
        # that partially-created timer or it remains attached to the window.
        _fbp_remove_generation_timer(context, operator)
        fbp_warn('Could not defer Frame By Plane generation', exc)
        return None


def _fbp_claim_generation_start(operator, event, *, now=None):
    """Claim one deferred generation only after its monotonic deadline.

    Blender 5.2 does not consistently expose a comparable ``event.timer``
    object. The event type remains useful, while the monotonic deadline is the
    authoritative fallback that prevents unrelated window timers from starting
    work early. Modal callbacks run serially on Blender's main thread, so the
    started flag is an atomic claim for this operator instance.
    """
    if str(getattr(event, "type", "") or "") != "TIMER":
        return False
    if bool(getattr(operator, "_fbp_generation_cancelled", False)):
        return False
    if bool(getattr(operator, "_fbp_generation_started", False)):
        return False
    owned_timer = getattr(operator, "_fbp_generation_timer", None)
    event_timer = getattr(event, "timer", None)
    if event_timer is not None and owned_timer is not None and event_timer != owned_timer:
        return False
    try:
        deadline = float(getattr(operator, "_fbp_generation_deadline", 0.0) or 0.0)
        current = time.perf_counter() if now is None else float(now)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    if deadline > 0.0 and current < deadline:
        return False
    operator._fbp_generation_started = True
    return True


def _fbp_remove_generation_timer(context, operator):
    try:
        timer = getattr(operator, '_fbp_generation_timer', None)
        if timer is not None:
            context.window_manager.event_timer_remove(timer)
            try:
                _FBP_GENERATION_TIMERS.remove(timer)
            except ValueError:
                pass
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        operator._fbp_generation_timer = None
        operator._fbp_generation_deadline = 0.0
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        _FBP_GENERATION_OPERATORS.remove(operator)
    except (ValueError, ReferenceError, RuntimeError, TypeError):
        pass


def _fbp_update_generation_progress(context, operator, payload):
    """Publish one semantically complete snapshot through one progress owner."""
    payload = payload if isinstance(payload, dict) else {}
    try:
        total = max(1, int(payload.get("total_steps", payload.get("total", 1)) or 1))
        completed = max(0, min(
            total,
            int(payload.get("completed_steps", payload.get("completed", 0)) or 0),
        ))
    except (TypeError, ValueError, OverflowError):
        total = 1
        completed = 0
    step = str(
        payload.get("current_step", payload.get("step", "Generating Frame By Plane media"))
        or "Generating Frame By Plane media"
    )
    phase = str(payload.get("phase", "WORK") or "WORK").upper()
    try:
        percent = float(payload.get("percent", completed / total))
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        percent = completed / total
    percent = max(0.0, min(1.0, percent))
    cancellable = bool(payload.get("cancellable", True))
    suffix = "Esc cancels between phases" if cancellable else "Cancellation available when this phase finishes"
    text = f"{step} — {completed}/{total} ({percent * 100.0:.0f}%) — {suffix}"
    owner = active_generation_owner()
    owner_token = str(getattr(operator, "_fbp_generation_owner_token", "") or "")
    if owner is not None and owner.token == owner_token:
        owner.checkpoint(
            phase,
            completed_steps=completed,
            total_steps=total,
            percent=percent,
            current_step=step,
        )
        operator._fbp_generation_progress_active = True
    else:
        # Direct regression helpers can drain an iterator without acquiring the
        # process-wide generation slot.
        try:
            if not bool(getattr(operator, "_fbp_generation_progress_active", False)):
                context.window_manager.progress_begin(0.0, 100.0)
                operator._fbp_generation_progress_active = True
            previous = float(getattr(operator, "_fbp_generation_progress_percent", 0.0) or 0.0)
            percent = max(previous, percent)
            context.window_manager.progress_update(percent * 100.0)
        except FBP_DATA_IO_ERRORS:
            pass
    try:
        operator._fbp_generation_progress_completed = completed
        operator._fbp_generation_progress_total = total
        operator._fbp_generation_progress_step = step
        operator._fbp_generation_progress_phase = phase
        operator._fbp_generation_progress_percent = percent
    except FBP_DATA_IO_ERRORS:
        pass
    FBP_GENERATION_OVERLAY["text"] = text
    try:
        context.workspace.status_text_set(text)
    except FBP_DATA_IO_ERRORS:
        pass
    _fbp_tag_view3d_redraw()
    return {
        "completed": completed,
        "total": total,
        "step": step,
        "phase": phase,
        "percent": percent,
        "cancellable": cancellable,
    }


def _fbp_begin_generation_chunks(context, operator, iterator, *, interval=0.01):
    """Replace the start-delay timer with a short main-thread chunk timer."""
    _fbp_remove_generation_timer(context, operator)
    try:
        operator._fbp_generation_iterator = iterator
        operator._fbp_generation_chunking = True
        operator._fbp_generation_started = True
        operator._fbp_generation_cancelled = False
        chunk_interval = max(0.001, float(interval))
        operator._fbp_generation_chunk_interval = chunk_interval
        operator._fbp_generation_next_due = time.perf_counter() + chunk_interval
        operator._fbp_generation_advancing = False
        operator._fbp_generation_timer = context.window_manager.event_timer_add(
            chunk_interval,
            window=context.window,
        )
        if operator._fbp_generation_timer not in _FBP_GENERATION_TIMERS:
            _FBP_GENERATION_TIMERS.append(operator._fbp_generation_timer)
        if operator not in _FBP_GENERATION_OPERATORS:
            _FBP_GENERATION_OPERATORS.append(operator)
        return True
    except FBP_DATA_ERRORS as exc:
        _fbp_remove_generation_timer(context, operator)
        try:
            operator._fbp_generation_iterator = None
            operator._fbp_generation_chunking = False
        except FBP_DATA_ERRORS:
            pass
        fbp_warn("Could not start incremental Frame By Plane generation", exc)
        return False


def _fbp_generation_chunk_is_due(operator, event=None, *, now=None):
    """Accept the owned event timer, or one deadline-gated fallback event."""
    if event is not None and str(getattr(event, "type", "") or "") != "TIMER":
        return False
    owned_timer = getattr(operator, "_fbp_generation_timer", None)
    event_timer = getattr(event, "timer", None) if event is not None else None
    if event_timer is not None and owned_timer is not None and event_timer != owned_timer:
        return False
    if bool(getattr(operator, "_fbp_generation_advancing", False)):
        return False
    try:
        current = time.perf_counter() if now is None else float(now)
        next_due = float(getattr(operator, "_fbp_generation_next_due", 0.0) or 0.0)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    return next_due <= 0.0 or current >= next_due


def _fbp_advance_generation_chunk(context, operator, event=None, *, now=None):
    """Advance one generator step and return a primitive state record."""
    if not _fbp_generation_chunk_is_due(operator, event, now=now):
        return {"state": "WAITING"}
    iterator = getattr(operator, "_fbp_generation_iterator", None)
    if iterator is None:
        return {"state": "ERROR", "error": RuntimeError("Generation iterator is unavailable")}
    operator._fbp_generation_advancing = True
    current = time.perf_counter() if now is None else float(now)
    interval = max(0.001, float(getattr(operator, "_fbp_generation_chunk_interval", 0.01) or 0.01))
    operator._fbp_generation_next_due = current + interval
    try:
        payload = next(iterator)
        progress = _fbp_update_generation_progress(context, operator, payload)
        return {"state": "RUNNING", "progress": progress}
    except StopIteration as finished:
        return {"state": "FINISHED", "result": finished.value}
    except Exception as exc:
        return {"state": "ERROR", "error": exc}
    finally:
        operator._fbp_generation_advancing = False


def _fbp_finish_generation_chunks(context, operator, *, close_iterator=False):
    """Retire the chunk iterator and its event timer exactly once."""
    iterator = getattr(operator, "_fbp_generation_iterator", None)
    if close_iterator:
        try:
            close_callback = getattr(iterator, "close", None)
            if callable(close_callback):
                close_callback()
        except FBP_DATA_ERRORS:
            pass
    _fbp_remove_generation_timer(context, operator)
    try:
        operator._fbp_generation_iterator = None
        operator._fbp_generation_chunking = False
        operator._fbp_generation_progress_active = False
        operator._fbp_generation_next_due = 0.0
        operator._fbp_generation_advancing = False
    except FBP_DATA_ERRORS:
        pass
    owner = active_generation_owner()
    owner_token = str(getattr(operator, "_fbp_generation_owner_token", "") or "")
    if owner is None or owner.token != owner_token:
        try:
            context.window_manager.progress_end()
        except FBP_DATA_ERRORS:
            pass
    return True

def _fbp_generation_rig_issue(rig):
    """Return a small issue dictionary for rigs that need attention after generation."""
    if not rig or getattr(rig, 'fbp_is_color_plane', False):
        return None

    name = getattr(rig, 'name', 'Frame By Plane Layer')
    directory, files = fbp_native_sequence_files_from_rig(rig)
    files = list(files or [])

    if directory and files:
        missing = []
        for file_name in files:
            try:
                path = os.path.join(directory, file_name)
                if not os.path.isfile(path):
                    missing.append(file_name)
            except Exception:
                missing.append(str(file_name))
        if missing:
            return {
                "rig": name,
                "kind": "MISSING_FILES",
                "message": f"{len(missing)} source file(s) are missing",
                "files": missing[:6],
            }

        try:
            if len(files) > 1 and fbp_rig_native_sequence_needs_rename(rig):
                return {
                    "rig": name,
                    "kind": "RENAME_SEQUENCE",
                    "message": "Native sequence filenames may be unsafe for Blender",
                    "files": files[:6],
                }
        except FBP_DATA_IO_ERRORS:
            pass

    plane = getattr(rig, 'fbp_plane_target', None)
    if plane and getattr(plane, 'type', None) == 'MESH':
        try:
            for slot in getattr(plane, 'material_slots', []):
                mat = getattr(slot, 'material', None)
                if not mat or not getattr(mat, 'node_tree', None):
                    continue
                for node in getattr(mat.node_tree, 'nodes', []):
                    if getattr(node, 'type', None) != 'TEX_IMAGE':
                        continue
                    image = getattr(node, 'image', None)
                    if image is None:
                        return {"rig": name, "kind": "MISSING_IMAGE", "message": "Image Texture node has no image", "files": []}
                    filepath = bpy.path.abspath(getattr(image, 'filepath', '') or '')
                    if filepath and not os.path.exists(filepath) and getattr(image, 'source', '') != 'SEQUENCE':
                        return {"rig": name, "kind": "MISSING_IMAGE", "message": "Image file could not be found", "files": [os.path.basename(filepath)]}
        except FBP_DATA_IO_ERRORS:
            pass

    return None

def _fbp_build_issue(name, directory, files, message, kind="BUILD_FAILED"):
    """Create a generation-report issue for a layer that failed before a rig existed."""
    return {
        "rig": str(name or "Layer"),
        "kind": str(kind or "BUILD_FAILED"),
        "message": str(message or "Could not generate this layer"),
        "directory": str(directory or ""),
        "files": [str(f) for f in (files or []) if f][:6],
    }

def _fbp_store_generation_report(context, *, mode="Sequence", generated_rigs=None, cancelled=False, message="", extra_issues=None):
    """Store the last generation result as scene custom properties for the popup actions."""
    sc = context.scene
    generated_rigs = [rig for rig in (generated_rigs or []) if rig]
    issues = list(extra_issues or [])
    for rig in generated_rigs:
        issue = _fbp_generation_rig_issue(rig)
        if issue:
            issues.append(issue)

    status = "CANCELLED" if cancelled else ("WARNING" if issues else "SUCCESS")
    report = {
        "mode": str(mode or "Sequence"),
        "status": status,
        "message": str(message or ""),
        "planes_created": len(generated_rigs),
        "issues_count": len(issues),
        "issues": issues,
        "generated_rigs": [str(getattr(rig, "name", "")) for rig in generated_rigs if getattr(rig, "name", "")],
        "problem_rigs": [issue.get("rig", "") for issue in issues if issue.get("rig")],
        "rename_rigs": [issue.get("rig", "") for issue in issues if issue.get("kind") == "RENAME_SEQUENCE" and issue.get("rig")],
    }
    try:
        sc["fbp_generation_report_json"] = json.dumps(report)
    except FBP_DATA_IO_ERRORS:
        sc["fbp_generation_report_json"] = "{}"
    return report

def _fbp_generation_report(context):
    try:
        raw = context.scene.get("fbp_generation_report_json", "{}")
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return {}

def _fbp_clear_generation_report(context):
    try:
        if "fbp_generation_report_json" in context.scene:
            del context.scene["fbp_generation_report_json"]
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        context.scene.fbp_generation_rename_items.clear()
        context.scene.fbp_generation_rename_index = 0
    except FBP_DATA_IO_ERRORS:
        pass

def _fbp_generation_frame_targets(scene, rig_names):
    """Resolve generated rig names to the real visible plane objects."""
    targets = []
    seen = set()
    scene_objects = getattr(scene, "objects", None) if scene else None

    def add_target(obj):
        if obj is None:
            return
        try:
            key = obj.as_pointer()
        except FBP_DATA_ERRORS:
            key = id(obj)
        if key in seen:
            return
        try:
            if getattr(obj, "hide_viewport", False) or obj.hide_get():
                return
        except FBP_DATA_IO_ERRORS:
            pass
        seen.add(key)
        targets.append(obj)

    for rig_name in rig_names or ():
        rig = bpy.data.objects.get(str(rig_name or ""))
        if (
            rig is None
            or scene_objects is None
            or scene_objects.get(getattr(rig, "name", "")) != rig
            or not is_fbp_layer_object(rig)
        ):
            continue
        plane = getattr(rig, "fbp_plane_target", None)
        if plane is not None and scene_objects.get(getattr(plane, "name", "")) == plane:
            add_target(plane)
            continue
        mesh_children = [child for child in getattr(rig, "children", ()) if getattr(child, "type", None) == 'MESH']
        if mesh_children:
            for child in mesh_children:
                add_target(child)
        else:
            add_target(rig)
    return targets


def _fbp_frame_generated_planes(scene_key, rig_names, *, window_key=None, area_key=None):
    """Frame imported planes in the originating 3D View without moving the cursor."""
    try:
        wm = bpy.context.window_manager
        windows = list(wm.windows)
        if window_key is not None:
            windows.sort(key=lambda item: 0 if getattr(item, "as_pointer", lambda: None)() == window_key else 1)
        for window in windows:
            scene = getattr(window, "scene", None)
            if scene is None or not fbp_obj_matches_runtime_key(scene, scene_key):
                continue
            targets = _fbp_generation_frame_targets(scene, rig_names)
            if not targets:
                return None
            screen = getattr(window, "screen", None)
            if screen is None:
                return None
            view_areas = [item for item in screen.areas if item.type == 'VIEW_3D']
            if area_key is not None:
                view_areas.sort(key=lambda item: 0 if getattr(item, "as_pointer", lambda: None)() == area_key else 1)
            area = view_areas[0] if view_areas else None
            if area is None:
                return None
            region = next((item for item in area.regions if item.type == 'WINDOW'), None)
            space = next((item for item in area.spaces if item.type == 'VIEW_3D'), None)
            if region is None or space is None:
                return None

            view_layer = getattr(window, "view_layer", None) or bpy.context.view_layer
            selected_before = []
            for obj in view_layer.objects:
                try:
                    if obj.select_get():
                        selected_before.append(obj)
                except FBP_DATA_IO_ERRORS:
                    continue
            active_before = getattr(view_layer.objects, "active", None)
            target_select_locks = []

            try:
                for obj in view_layer.objects:
                    try:
                        obj.select_set(False)
                    except FBP_DATA_IO_ERRORS:
                        continue
                selectable_targets = []
                for obj in targets:
                    try:
                        was_locked = bool(getattr(obj, "hide_select", False))
                        target_select_locks.append((obj, was_locked))
                        if was_locked:
                            obj.hide_select = False
                        obj.select_set(True)
                        if obj.select_get():
                            selectable_targets.append(obj)
                    except FBP_DATA_IO_ERRORS:
                        continue
                if not selectable_targets:
                    return None
                view_layer.objects.active = selectable_targets[0]
                with bpy.context.temp_override(
                    window=window,
                    screen=screen,
                    area=area,
                    region=region,
                    space_data=space,
                    scene=scene,
                    view_layer=view_layer,
                ):
                    try:
                        view_layer.update()
                        bpy.context.evaluated_depsgraph_get().update()
                    except FBP_DATA_IO_ERRORS:
                        pass
                    bpy.ops.view3d.view_selected(use_all_regions=False)
            finally:
                for obj in view_layer.objects:
                    try:
                        obj.select_set(False)
                    except FBP_DATA_IO_ERRORS:
                        continue
                for obj in selected_before:
                    try:
                        obj.select_set(True)
                    except FBP_DATA_IO_ERRORS:
                        continue
                try:
                    view_layer.objects.active = active_before
                except FBP_DATA_IO_ERRORS:
                    pass
                for obj, was_locked in target_select_locks:
                    try:
                        obj.hide_select = was_locked
                    except FBP_DATA_IO_ERRORS:
                        continue
            area.tag_redraw()
            return None
    except FBP_DATA_IO_ERRORS as exc:
        fbp_warn("Could not frame the generated Frame By Plane layers", exc)
    return None


def _fbp_finish_generation_ui(context, report=None, *, show_popup=True):
    _fbp_hide_generation_overlay(context)
    try:
        context.window_manager.progress_end()
    except FBP_DATA_IO_ERRORS:
        pass

    report = report if isinstance(report, dict) else _fbp_generation_report(context)
    status = str(report.get("status", "SUCCESS") or "SUCCESS")
    scene = getattr(context, "scene", None) if context else None
    scene_key = fbp_obj_runtime_key(scene) if scene else None
    source_window = getattr(context, "window", None) if context else None
    source_area = getattr(context, "area", None) if context else None
    try:
        window_key = source_window.as_pointer() if source_window is not None else None
    except FBP_DATA_ERRORS:
        window_key = None
    try:
        area_key = source_area.as_pointer() if getattr(source_area, "type", None) == 'VIEW_3D' else None
    except FBP_DATA_ERRORS:
        area_key = None

    # A clean import no longer opens a confirmation dialog. Instead, frame the
    # generated plane geometry in the active scene while preserving selection,
    # active object and 3D cursor position.
    if status == "SUCCESS":
        rig_names = tuple(str(name) for name in report.get("generated_rigs", ()) if name)
        _fbp_clear_generation_report(context)
        if scene_key is not None and rig_names:
            task_token = time.monotonic_ns()
            _safe_tasks.schedule_once(
                f'operators.frame_generated_planes.{scene_key}.{task_token}',
                lambda: _fbp_frame_generated_planes(
                    scene_key,
                    rig_names,
                    window_key=window_key,
                    area_key=area_key,
                ),
                first_interval=0.08,
            )
        return

    if not show_popup or scene_key is None:
        return

    # Warnings and failures still open the report because they contain repair
    # actions that must remain accessible to the user.
    def _show_report():
        try:
            wm = bpy.context.window_manager
            for window in wm.windows:
                target_scene = getattr(window, "scene", None)
                try:
                    if not fbp_obj_matches_runtime_key(target_scene, scene_key):
                        continue
                except FBP_DATA_ERRORS:
                    continue
                screen = getattr(window, 'screen', None)
                if not screen:
                    continue
                for area in screen.areas:
                    if area.type != 'VIEW_3D':
                        continue
                    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                    if region is None:
                        continue
                    with bpy.context.temp_override(
                        window=window, screen=screen, area=area, region=region, scene=target_scene
                    ):
                        bpy.ops.fbp.generation_report_popup('INVOKE_DEFAULT')
                    return None
        except FBP_DATA_IO_ERRORS:
            pass
        return None

    _safe_tasks.schedule_once(
        f'operators.generation_report_popup.{scene_key}',
        _show_report,
        first_interval=0.12,
    )

def _fbp_rigs_from_report(context, key="problem_rigs"):
    report = _fbp_generation_report(context)
    names = [str(name) for name in report.get(key, []) if name]
    rigs = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj and is_fbp_layer_object(obj):
            rigs.append(obj)
    return rigs

def _fbp_sync_generation_rename_items(context):
    """Populate the generation report without losing its logical active row."""
    scene = context.scene
    anchor_index_key = "_fbp_generation_rename_selection_anchor"
    anchor_uid_key = "_fbp_generation_rename_selection_anchor_uid"
    try:
        items = scene.fbp_generation_rename_items
        ensure_unique_item_identities(items, "stable_id")
        previous_index = int(getattr(scene, 'fbp_generation_rename_index', 0) or 0)
        previous_active_uid = identity_at(items, "stable_id", previous_index)
        previous_selected = {
            identity_at(items, "stable_id", index)
            for index, item in enumerate(items)
            if bool(getattr(item, "selected", False))
        }
        previous_anchor_uid = str(transient_get(scene, anchor_uid_key, "") or "")
        items.clear()
    except FBP_DATA_IO_ERRORS:
        return []

    report = _fbp_generation_report(context)
    issues = list(report.get("issues", []) or [])
    created = []
    occurrences = {}
    for issue in issues:
        kind = str(issue.get("kind", "") or "")
        if kind not in {"RENAME_SEQUENCE", "RENAMED_SEQUENCE"}:
            continue
        rig_name = str(issue.get("rig", "") or "")
        if not rig_name:
            continue
        occurrence = occurrences.get(rig_name, 0)
        occurrences[rig_name] = occurrence + 1
        item = items.add()
        item.stable_id = f"generation:{rig_name}:{occurrence}"
        item.rig_name = rig_name
        item.display_name = rig_name
        item.is_renamed = bool(issue.get("renamed", False) or kind == "RENAMED_SEQUENCE")
        item.message = str(issue.get("message", "Renamed successfully" if item.is_renamed else "Needs rename") or "")
        files = list(issue.get("files", []) or [])
        item.preview_files = ", ".join(str(f) for f in files[:3])
        item.selected = item.stable_id in previous_selected
        created.append(rig_name)

    ensure_unique_item_identities(items, "stable_id")
    try:
        active_index = restore_active_index(
            items, "stable_id", previous_active_uid, fallback=previous_index
        )
        scene.fbp_generation_rename_index = active_index
        anchor_index = index_for_identity(
            items, "stable_id", previous_anchor_uid, default=-1
        )
        if anchor_index >= 0:
            store_anchor(
                scene, anchor_index_key, anchor_uid_key, items,
                "stable_id", anchor_index,
            )
        elif items:
            store_anchor(
                scene, anchor_index_key, anchor_uid_key, items,
                "stable_id", active_index,
            )
        else:
            clear_anchor(scene, anchor_index_key, anchor_uid_key)
    except FBP_DATA_IO_ERRORS:
        pass
    return created

def _fbp_mark_generation_sequence_renamed(context, rig_name, files=None):
    """Mark one generation-report sequence as renamed, so the UIList shows a checkmark."""
    rig_name = str(rig_name or "")
    if not rig_name:
        return False
    report = _fbp_generation_report(context)
    if not report:
        return False

    changed = False
    issues = list(report.get("issues", []) or [])
    display_files = [str(f) for f in (files or []) if f]
    for issue in issues:
        if str(issue.get("rig", "") or "") != rig_name:
            continue
        if str(issue.get("kind", "") or "") not in {"RENAME_SEQUENCE", "RENAMED_SEQUENCE"}:
            continue
        issue["kind"] = "RENAMED_SEQUENCE"
        issue["renamed"] = True
        issue["message"] = "Renamed successfully"
        if display_files:
            issue["files"] = display_files[:6]
        changed = True
        break

    if not changed:
        return False

    renamed = {str(name) for name in (report.get("renamed_rigs", []) or []) if name}
    renamed.add(rig_name)
    report["renamed_rigs"] = sorted(renamed)
    report["rename_rigs"] = [
        str(issue.get("rig", "") or "")
        for issue in issues
        if str(issue.get("kind", "") or "") == "RENAME_SEQUENCE" and issue.get("rig")
    ]
    report["issues"] = issues
    try:
        context.scene["fbp_generation_report_json"] = json.dumps(report)
    except (ReferenceError, RuntimeError, TypeError, ValueError, OSError):
        return False
    _fbp_sync_generation_rename_items(context)
    return True

def _fbp_active_generation_rename_item(context):
    try:
        items = context.scene.fbp_generation_rename_items
        if not items:
            return None
        idx = int(getattr(context.scene, 'fbp_generation_rename_index', 0))
        idx = min(max(idx, 0), len(items) - 1)
        return items[idx]
    except FBP_DATA_IO_ERRORS:
        return None

FBP_BG_RENDER_STATE = globals().get("FBP_BG_RENDER_STATE", {})
for _key, _default in {
    "process": None,
    "log_handle": None,
    "log_path": "",
    "log_offset": 0,
    "log_partial": "",
    "rendered_frames": set(),
    "last_rendered_frame": 0,
    "last_log_message": "",
    "last_log_copy": "",
    "log_complete": False,
    "last_filesystem_scan": 0.0,
    "filesystem_progress": 0,
    "temp_dir": "",
    "out_dir": "",
    "prefix": "",
    "output_path": "",
    "expected_paths": (),
    "scheduled_frames": (),
    "output_files": set(),
    "is_movie_format": False,
    "auto_video": False,
    "requires_movie_output": False,
    "movie_output_path": "",
    "accept_existing_outputs": False,
    "start": 0,
    "end": 0,
    "step": 1,
    "total": 0,
    "started_at": 0.0,
    "session_token": "",
    "state_path": "",
    "stop_path": "",
    "state_mtime_ns": 0,
    "state_status": "",
    "state_progress": 0,
    "state_error": "",
    "current_frame": 0,
    "current_frame_known": False,
    "current_frame_started_at": 0.0,
    "last_activity_at": 0.0,
    "frame_durations": [],
    "last_status_signature": None,
    "last_status_write_at": 0.0,
}.items():
    FBP_BG_RENDER_STATE.setdefault(_key, _default)
del _key, _default


def _fbp_bg_reset_progress_state():
    """Reset the incremental progress parser without touching the child process."""
    FBP_BG_RENDER_STATE.update({
        "log_offset": 0,
        "log_partial": "",
        "rendered_frames": set(),
        "output_files": set(),
        "last_rendered_frame": 0,
        "last_log_message": "",
        "last_log_copy": "",
        "log_complete": False,
        "last_filesystem_scan": 0.0,
        "filesystem_progress": 0,
        "state_mtime_ns": 0,
        "state_status": "",
        "state_progress": 0,
        "state_error": "",
        "current_frame": 0,
        "current_frame_known": False,
        "current_frame_started_at": 0.0,
        "last_activity_at": 0.0,
        "frame_durations": [],
        "last_status_signature": None,
        "last_status_write_at": 0.0,
    })


def _fbp_bg_clear_runtime_state(scene=None):
    """Clear stale background-render process/log state after finish or unload."""
    _fbp_bg_cleanup_temp_files()
    FBP_BG_RENDER_STATE.update({
        "process": None,
        "log_handle": None,
        "log_path": "",
        "temp_dir": "",
        "out_dir": "",
        "prefix": "",
        "output_path": "",
        "expected_paths": (),
        "scheduled_frames": (),
        "output_files": set(),
        "is_movie_format": False,
        "auto_video": False,
        "requires_movie_output": False,
        "movie_output_path": "",
        "accept_existing_outputs": False,
        "start": 0,
        "end": 0,
        "step": 1,
        "total": 0,
        "started_at": 0.0,
        "session_token": "",
        "state_path": "",
        "stop_path": "",
    })
    _fbp_bg_reset_progress_state()
    if scene:
        try:
            scene.fbp_background_render_running = False
            scene.fbp_background_render_progress = 0
            scene.fbp_background_render_total = 0
            scene.fbp_background_render_output_dir = ""
            scene.fbp_background_render_current_frame = 0
            scene.fbp_background_render_eta = ""
            scene.fbp_background_render_status = "Idle"
        except FBP_DATA_IO_ERRORS:
            pass


def _fbp_bg_process_status():
    """Return ``(running, returncode, state_known)`` for the child process.

    A transient ``Popen.poll()`` failure must never be interpreted as process
    completion. Callers that mutate or delete session files can therefore keep
    the conservative running state until process termination is confirmed.
    """
    proc = FBP_BG_RENDER_STATE.get("process")
    if proc is None:
        return False, None, True
    try:
        returncode = proc.poll()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return True, None, False
    return returncode is None, returncode, True


def _fbp_bg_process_running():
    running, _returncode, _state_known = _fbp_bg_process_status()
    return bool(running)

def _fbp_bg_close_log_handle():
    handle = FBP_BG_RENDER_STATE.get("log_handle")
    if handle:
        try:
            handle.close()
        except FBP_DATA_IO_ERRORS:
            pass
    FBP_BG_RENDER_STATE["log_handle"] = None


def _fbp_bg_cleanup_temp_files():
    """Close the background log and remove the temporary script directory."""
    _fbp_bg_close_log_handle()
    temp_dir = str(FBP_BG_RENDER_STATE.get("temp_dir", "") or "")
    if temp_dir:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
    FBP_BG_RENDER_STATE["temp_dir"] = ""
    FBP_BG_RENDER_STATE["log_path"] = ""


def _fbp_bg_read_state_file():
    """Read the child job-state file only when its atomic replacement changed."""
    state_path = str(FBP_BG_RENDER_STATE.get("state_path", "") or "")
    if not state_path:
        return False
    try:
        stat = os.stat(state_path)
        mtime_ns = int(getattr(stat, "st_mtime_ns", 0) or 0)
        if mtime_ns and mtime_ns == int(FBP_BG_RENDER_STATE.get("state_mtime_ns", 0) or 0):
            return True
        with open(state_path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError, RuntimeError, TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    token = str(payload.get("session_token", "") or "")
    active_token = str(FBP_BG_RENDER_STATE.get("session_token", "") or "")
    if token and active_token and token != active_token:
        return False
    FBP_BG_RENDER_STATE["state_mtime_ns"] = mtime_ns
    status = str(payload.get("status", "") or "").upper()
    FBP_BG_RENDER_STATE["state_status"] = status
    try:
        FBP_BG_RENDER_STATE["state_progress"] = max(
            int(FBP_BG_RENDER_STATE.get("state_progress", 0) or 0),
            int(payload.get("rendered_count", 0) or 0),
        )
    except (TypeError, ValueError):
        pass
    try:
        if "current_frame" in payload:
            FBP_BG_RENDER_STATE["current_frame"] = int(payload.get("current_frame", 0) or 0)
            FBP_BG_RENDER_STATE["current_frame_known"] = True
    except (TypeError, ValueError):
        pass
    try:
        updated_at = float(payload.get("updated_at", 0.0) or 0.0)
        if updated_at > 0.0:
            FBP_BG_RENDER_STATE["last_activity_at"] = updated_at
    except (TypeError, ValueError):
        pass
    error = str(payload.get("error", "") or "").strip()
    if error:
        FBP_BG_RENDER_STATE["state_error"] = error[-500:]
        FBP_BG_RENDER_STATE["last_log_message"] = error[-500:]
    if status == "DONE":
        FBP_BG_RENDER_STATE["log_complete"] = True
    return True


def _fbp_bg_read_progress_log():
    """Incrementally parse only newly appended child-process log bytes.

    The previous monitor listed and stat-ed the complete output directory every
    0.75 seconds. Large or network output folders therefore became slower as a
    render progressed. ``render_write`` already emits one deterministic marker,
    so progress can be O(new log bytes) and independent of folder size.
    """
    log_path = str(FBP_BG_RENDER_STATE.get("log_path", "") or "")
    if not log_path or not os.path.isfile(log_path):
        return False
    try:
        offset = max(0, int(FBP_BG_RENDER_STATE.get("log_offset", 0) or 0))
        size = os.path.getsize(log_path)
        if offset > size:
            # The file was truncated or replaced; restart the parser instead of
            # silently skipping the new render session.
            offset = 0
            FBP_BG_RENDER_STATE["log_partial"] = ""
        with open(log_path, "rb") as stream:
            stream.seek(offset)
            payload = stream.read()
            FBP_BG_RENDER_STATE["log_offset"] = int(stream.tell())
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    if not payload:
        return True

    text = str(FBP_BG_RENDER_STATE.get("log_partial", "") or "") + payload.decode(
        "utf-8", errors="replace"
    )
    lines = text.split("\n")
    FBP_BG_RENDER_STATE["log_partial"] = lines.pop() if lines else ""

    rendered = FBP_BG_RENDER_STATE.get("rendered_frames")
    if not isinstance(rendered, set):
        rendered = set(rendered or ())
        FBP_BG_RENDER_STATE["rendered_frames"] = rendered
    start = int(FBP_BG_RENDER_STATE.get("start", 0) or 0)
    end = int(FBP_BG_RENDER_STATE.get("end", 0) or 0)
    scheduled = set(FBP_BG_RENDER_STATE.get("scheduled_frames", ()) or ())

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[FBP_BG_FRAME_START]"):
            try:
                payload_text = line.split("]", 1)[1].strip()
                frame_text, _, timestamp_text = payload_text.partition("|")
                frame = int(frame_text.strip())
                if not scheduled or frame in scheduled:
                    FBP_BG_RENDER_STATE["current_frame"] = frame
                    FBP_BG_RENDER_STATE["current_frame_known"] = True
                    started_wall = float(timestamp_text.strip() or time.time())
                    FBP_BG_RENDER_STATE["current_frame_started_at"] = started_wall
                    FBP_BG_RENDER_STATE["last_activity_at"] = started_wall
            except (IndexError, TypeError, ValueError):
                pass
            continue
        if line.startswith("[FBP_BG_FRAME]"):
            try:
                payload_text = line.split("]", 1)[1].strip()
                parts = payload_text.split("|", 2)
                frame_payload = parts[0]
                output_path = parts[1].strip() if len(parts) > 1 else ""
                timestamp = float(parts[2].strip()) if len(parts) > 2 and parts[2].strip() else time.time()
                frame_text = frame_payload.split("/", 1)[0].strip()
                frame = int(frame_text)
                valid_frame = frame in scheduled if scheduled else start <= frame <= end
                if valid_frame:
                    rendered.add(frame)
                    FBP_BG_RENDER_STATE["last_rendered_frame"] = frame
                    FBP_BG_RENDER_STATE["current_frame"] = frame
                    FBP_BG_RENDER_STATE["current_frame_known"] = True
                    FBP_BG_RENDER_STATE["last_activity_at"] = timestamp
                    started_wall = float(FBP_BG_RENDER_STATE.get("current_frame_started_at", 0.0) or 0.0)
                    if started_wall > 0.0 and timestamp >= started_wall:
                        durations = FBP_BG_RENDER_STATE.get("frame_durations")
                        if not isinstance(durations, list):
                            durations = list(durations or ())
                        duration = timestamp - started_wall
                        if 0.0 <= duration < 7 * 24 * 3600:
                            durations.append(duration)
                            del durations[:-32]
                            FBP_BG_RENDER_STATE["frame_durations"] = durations
                    if output_path:
                        output_files = FBP_BG_RENDER_STATE.get("output_files")
                        if not isinstance(output_files, set):
                            output_files = set(output_files or ())
                            FBP_BG_RENDER_STATE["output_files"] = output_files
                        output_files.add(os.path.normpath(output_path))
            except (IndexError, TypeError, ValueError):
                pass
            continue
        if line.startswith("[FBP_BG_ERROR]"):
            FBP_BG_RENDER_STATE["last_log_message"] = line.split("]", 1)[-1].strip()[-500:]
            continue
        if line.startswith("[FBP_BG]"):
            message = line.split("]", 1)[1].strip() if "]" in line else line
            FBP_BG_RENDER_STATE["last_log_message"] = message[-500:]
            if message == "DONE":
                FBP_BG_RENDER_STATE["log_complete"] = True
            continue
        lowered = line.lower()
        if "traceback (most recent call last)" in lowered or "error" in lowered or "exception" in lowered:
            FBP_BG_RENDER_STATE["last_log_message"] = line[-500:]
    return True


def _fbp_bg_count_rendered_frames(out_dir, prefix):
    """Count only files expected by the active native Blender output pattern."""
    started_at = float(FBP_BG_RENDER_STATE.get("started_at", 0.0) or 0.0)
    expected_paths = tuple(FBP_BG_RENDER_STATE.get("expected_paths", ()) or ())
    accept_existing = bool(FBP_BG_RENDER_STATE.get("accept_existing_outputs", False))
    if expected_paths:
        count = 0
        for path in expected_paths:
            try:
                if not os.path.isfile(path) or os.path.getsize(path) <= 0:
                    continue
                if (
                    not accept_existing
                    and started_at > 0.0
                    and os.path.getmtime(path) < started_at - 1.0
                ):
                    continue
                count += 1
            except OSError:
                continue
        return count

    # Movie formats and engines without deterministic frame paths rely on log
    # markers. Keep one broad final fallback without assuming a file extension.
    try:
        names = os.listdir(out_dir) if out_dir and os.path.isdir(out_dir) else []
    except (OSError, RuntimeError, TypeError, ValueError):
        return 0
    prefix = str(prefix or "")
    count = 0
    for name in names:
        if prefix and not str(name).startswith(prefix):
            continue
        path = os.path.join(out_dir, name)
        try:
            if not os.path.isfile(path) or os.path.getsize(path) <= 0:
                continue
            if (
                not accept_existing
                and started_at > 0.0
                and os.path.getmtime(path) < started_at - 1.0
            ):
                continue
        except OSError:
            continue
        count += 1
    return count


def _fbp_bg_progress(*, force_filesystem_scan=False):
    _fbp_bg_read_progress_log()
    _fbp_bg_read_state_file()
    rendered = FBP_BG_RENDER_STATE.get("rendered_frames")
    log_progress = len(rendered) if isinstance(rendered, set) else len(set(rendered or ()))
    log_progress = max(log_progress, int(FBP_BG_RENDER_STATE.get("state_progress", 0) or 0))
    now = time.monotonic()
    last_scan = float(FBP_BG_RENDER_STATE.get("last_filesystem_scan", 0.0) or 0.0)
    # A filesystem scan is only needed if no marker has appeared yet, or once at
    # process completion to verify engines that omit render_write callbacks.
    should_scan = bool(force_filesystem_scan or (log_progress <= 0 and now - last_scan >= 3.0))
    if should_scan:
        filesystem_progress = _fbp_bg_count_rendered_frames(
            FBP_BG_RENDER_STATE.get("out_dir", ""),
            FBP_BG_RENDER_STATE.get("prefix", ""),
        )
        FBP_BG_RENDER_STATE["filesystem_progress"] = max(
            int(FBP_BG_RENDER_STATE.get("filesystem_progress", 0) or 0),
            int(filesystem_progress),
        )
        FBP_BG_RENDER_STATE["last_filesystem_scan"] = now
    return max(log_progress, int(FBP_BG_RENDER_STATE.get("filesystem_progress", 0) or 0))


def _fbp_bg_format_duration(seconds):
    try:
        value = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return ""
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}h {minutes:02d}m"
    if minutes:
        return f"{minutes:d}m {secs:02d}s"
    return f"{secs:d}s"


def _fbp_bg_update_scene_status(scene, message=None, *, force_filesystem_scan=False):
    """Publish monitor state and return True only when Scene RNA changed."""
    if not scene:
        return False
    explicit_message = message is not None
    total = int(FBP_BG_RENDER_STATE.get("total", 0) or 0)
    progress = _fbp_bg_progress(force_filesystem_scan=force_filesystem_scan)
    progress = max(0, min(progress, total)) if total else progress
    remaining = max(0, total - progress)
    start = int(FBP_BG_RENDER_STATE.get("start", 0) or 0)
    end = int(FBP_BG_RENDER_STATE.get("end", 0) or 0)
    step = max(1, int(FBP_BG_RENDER_STATE.get("step", 1) or 1))
    scheduled = tuple(FBP_BG_RENDER_STATE.get("scheduled_frames", ()) or ())
    current_known = bool(FBP_BG_RENDER_STATE.get("current_frame_known", False))
    current = int(FBP_BG_RENDER_STATE.get("current_frame", 0) or 0)
    if not current_known:
        current = int(FBP_BG_RENDER_STATE.get("last_rendered_frame", 0) or start)
    running = _fbp_bg_process_running()
    durations = [float(value) for value in list(FBP_BG_RENDER_STATE.get("frame_durations", ()) or ()) if isinstance(value, (int, float)) and value >= 0.0]
    eta_seconds = (sum(durations) / len(durations) * remaining) if durations and remaining else 0.0
    eta_text = _fbp_bg_format_duration(eta_seconds) if eta_seconds > 0.0 else ""
    if message is None:
        if running:
            if progress > 0:
                if scheduled and progress < len(scheduled):
                    next_frame = int(scheduled[progress])
                else:
                    next_frame = min(end or current, current + step)
                message = f"Rendered {progress}/{total} · Frame {current} · Next {next_frame}"
                if eta_text:
                    message += f" · ETA {eta_text}"
            elif current:
                message = f"Rendering Frame {current} · {total} frames total"
            else:
                message = f"Rendering starting · {total} frames total"
        else:
            message = "Idle"

    now = time.monotonic()
    signature = (bool(running), int(progress), int(total), int(current), str(message))
    previous_signature = FBP_BG_RENDER_STATE.get("last_status_signature")
    last_write = float(FBP_BG_RENDER_STATE.get("last_status_write_at", 0.0) or 0.0)
    should_write_status = explicit_message or signature != previous_signature or now - last_write >= 5.0

    scene_changed = False

    def set_changed(name, value):
        nonlocal scene_changed
        try:
            if getattr(scene, name) != value:
                setattr(scene, name, value)
                scene_changed = True
        except FBP_DATA_IO_ERRORS:
            pass

    set_changed("fbp_background_render_running", bool(running))
    set_changed("fbp_background_render_progress", int(progress))
    set_changed("fbp_background_render_total", int(total))
    set_changed("fbp_background_render_output_dir", str(FBP_BG_RENDER_STATE.get("out_dir", "") or ""))
    set_changed("fbp_background_render_current_frame", int(current))
    set_changed("fbp_background_render_eta", str(eta_text))
    last_log_copy = str(FBP_BG_RENDER_STATE.get("last_log_copy", "") or "")
    if last_log_copy:
        set_changed("fbp_background_render_last_log", last_log_copy)
    if should_write_status:
        set_changed("fbp_background_render_status", str(message))
        FBP_BG_RENDER_STATE["last_status_signature"] = signature
        FBP_BG_RENDER_STATE["last_status_write_at"] = now
    return scene_changed


def _fbp_bg_terminate_process(scene=None):
    """Stop the complete background-render process group conservatively.

    This function confirms process exit but deliberately leaves session files and
    ownership tokens intact. The modal owner or Stop operator preserves the log
    and performs cleanup after termination, preventing cancelled jobs from losing
    their diagnostics.
    """
    proc = FBP_BG_RENDER_STATE.get("process")
    if proc is None:
        _fbp_bg_update_scene_status(scene, "No background render is running")
        return False

    try:
        stop_path = str(FBP_BG_RENDER_STATE.get("stop_path", "") or "")
        if stop_path:
            try:
                with open(stop_path, "w", encoding="utf-8") as stream:
                    stream.write("stop\n")
            except OSError:
                pass
        _fbp_bg_update_scene_status(scene, "Stopping background render")

        running, _returncode, state_known = _fbp_bg_process_status()
        if state_known and not running:
            FBP_BG_RENDER_STATE["process"] = None
            return True

        stopped = False
        if os.name == "nt":
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            except (AttributeError, OSError, RuntimeError, ValueError):
                try:
                    proc.terminate()
                except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                    pass
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (AttributeError, OSError, ProcessLookupError, RuntimeError, TypeError, ValueError):
                try:
                    proc.terminate()
                except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                    pass

        try:
            proc.wait(timeout=6)
            stopped = True
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError, subprocess.TimeoutExpired):
            pass

        if not stopped and os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(int(proc.pid)), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=8,
                    check=False,
                )
            except (OSError, RuntimeError, TypeError, ValueError, subprocess.TimeoutExpired):
                pass
        elif not stopped:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (AttributeError, OSError, ProcessLookupError, RuntimeError, TypeError, ValueError):
                try:
                    proc.kill()
                except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                    pass

        if not stopped:
            try:
                proc.wait(timeout=3)
                stopped = True
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError, subprocess.TimeoutExpired):
                pass

        if not stopped:
            running, _returncode, state_known = _fbp_bg_process_status()
            stopped = bool(state_known and not running)
        if not stopped:
            _fbp_bg_read_progress_log()
            _fbp_bg_read_state_file()
            _fbp_bg_update_scene_status(
                scene,
                "Could not confirm that the background render stopped",
                force_filesystem_scan=True,
            )
            return False

        FBP_BG_RENDER_STATE["process"] = None
        _fbp_bg_update_scene_status(
            scene, "Background render stopped", force_filesystem_scan=True
        )
        return True
    except Exception:
        _fbp_bg_read_progress_log()
        _fbp_bg_read_state_file()
        _fbp_bg_update_scene_status(
            scene,
            "Could not stop background render",
            force_filesystem_scan=True,
        )
        return False


def _fbp_select_pending_index(context, pending_index):
    scene = context.scene
    focus_uid = ""
    try:
        pending = scene.fbp_pending_planes
        ensure_unique_item_identities(pending, "stable_id")
        clamped_index = max(0, min(int(pending_index), max(0, len(pending) - 1)))
        scene.fbp_pending_planes_idx = clamped_index
        focus_uid = identity_at(pending, "stable_id", clamped_index)
        if focus_uid:
            transient_set(scene, "_fbp_pending_tree_focus_uid", focus_uid)
    except FBP_DATA_IO_ERRORS:
        pass
    _fbp_refresh_pending_tree(context)
    # Move the virtual tree selection by stable identity when the refresh was
    # immediate. If it was deferred, fbp_rebuild_pending_tree_rows consumes the
    # same primitive focus token after Blender releases the current row wrappers.
    if not focus_uid:
        return
    try:
        pending = scene.fbp_pending_planes
        for row_index, row in enumerate(scene.fbp_pending_tree_rows):
            if getattr(row, 'row_type', 'LAYER') != 'LAYER':
                continue
            source_index = int(getattr(row, 'pending_index', -1))
            if not (0 <= source_index < len(pending)):
                continue
            if identity_at(pending, "stable_id", source_index) == focus_uid:
                scene.fbp_pending_tree_rows_idx = row_index
                break
    except FBP_DATA_IO_ERRORS:
        pass

def _fbp_remove_pending_indices(context, indices):
    """Remove setup rows while keeping the same logical active row when possible."""
    scene = context.scene
    pending = getattr(scene, 'fbp_pending_planes', None)
    if pending is None:
        return 0
    ensure_unique_item_identities(pending, "stable_id")
    valid = sorted({int(index) for index in indices if 0 <= int(index) < len(pending)})
    if not valid:
        return 0
    active_index = max(0, min(
        int(getattr(scene, 'fbp_pending_planes_idx', 0) or 0),
        max(0, len(pending) - 1),
    ))
    active_uid = identity_at(pending, "stable_id", active_index)
    removed_uids = {identity_at(pending, "stable_id", index) for index in valid}
    for index in reversed(valid):
        pending.remove(index)
    if pending:
        fallback = min(valid[0], len(pending) - 1)
        new_index = restore_active_index(
            pending, "stable_id",
            "" if active_uid in removed_uids else active_uid,
            fallback=fallback,
        )
    else:
        new_index = 0
    _fbp_select_pending_index(context, new_index)
    return len(valid)


def _fbp_refresh_layer_tree(context, *, update_compositor=True):
    """Refresh virtual Layers UIList rows without invalidating an active row drag."""
    from .ui_layout import fbp_refresh_layer_tree_rows, fbp_schedule_layer_tree_rebuild
    if not fbp_refresh_layer_tree_rows:
        return False
    try:
        call_service("layers.invalidate_tree_snapshot", context)
        scene = getattr(context, "scene", None)
        if int(fbp_runtime_get(_FBP_UI_MODAL_MUTATION_DEPTH_KEY, 0) or 0) > 0:
            if scene is not None:
                try:
                    scene.fbp_layer_tree_signature = ""
                except FBP_DATA_IO_ERRORS:
                    pass
            fbp_schedule_layer_tree_rebuild(context)
            _fbp_tag_view3d_redraw()
            return True
        refreshed = bool(fbp_refresh_layer_tree_rows(context))
        _fbp_tag_view3d_redraw()
        if bool(update_compositor):
            try:
                from .compositor import fbp_schedule_compositor_update
                fbp_schedule_compositor_update(scene)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        return refreshed
    except FBP_DATA_IO_ERRORS:
        return False

def _fbp_color_tag_for_group(key, color_map):
    key = str(key or "Root")
    if key not in color_map:
        # Blender Collections expose seven artist-facing color tags; Brown/Grey are intentionally hidden.
        color_map[key] = f"COLOR_{(len(color_map) % 7) + 1:02d}"
    return color_map[key]

def _fbp_get_or_create_collection_path(
    parent_collection,
    collection_path,
    color_tag=None,
    *,
    on_create=None,
):
    """Create nested collections, keeping parent folders colorless."""
    current = parent_collection
    parts = [part.strip() for part in str(collection_path or '').split(' / ') if part.strip()]
    for index, part in enumerate(parts):
        is_leaf = index == len(parts) - 1
        previous = next((child for child in current.children if child.name == part), None)
        current = get_or_create_child_collection(current, part)
        if previous is None and callable(on_create):
            on_create(current)
        # Reapplying NONE is intentional: a collection may first be created as
        # a leaf and later become a parent when another setup row is processed.
        set_collection_color_tag(current, color_tag if is_leaf and color_tag else 'NONE')
    return current

def fbp_hex_name_from_color(color):
    try:
        from .color_names import normalize_color_hex
        return normalize_color_hex(color, color_space="LINEAR")[:7]
    except (ImportError, IndexError, TypeError, ValueError, OverflowError):
        return "Color"

def fbp_default_color_plane_name(kind, color):
    if kind == 'GRADIENT':
        return "Gradient Plane"
    if kind == 'HOLDOUT':
        return "Holdout Plane"
    try:
        from .color_names import color_plane_name_from_color
        return color_plane_name_from_color(color, color_space="LINEAR")
    except (ImportError, TypeError, ValueError, OverflowError):
        return f"Color Plane {fbp_hex_name_from_color(color)}"


def quiesce_generation_runtime(context=None):
    """Retire deferred generation modals before operator classes are removed."""
    target_context = context or getattr(bpy, "context", None)
    for operator in tuple(_FBP_GENERATION_OPERATORS):
        cancel_incremental = getattr(
            operator,
            "_fbp_cancel_incremental_generation",
            None,
        )
        if (
            bool(getattr(operator, "_fbp_generation_chunking", False))
            and callable(cancel_incremental)
            and target_context is not None
        ):
            try:
                cancel_incremental(target_context, from_quiesce=True)
                continue
            except FBP_DATA_ERRORS as exc:
                fbp_warn("Could not roll back incremental generation during teardown", exc)
        try:
            operator._fbp_generation_cancelled = True
        except FBP_DATA_ERRORS:
            continue
        if target_context is not None:
            _fbp_remove_generation_timer(target_context, operator)
    try:
        wm = getattr(target_context, "window_manager", None) if target_context else None
        for timer in tuple(_FBP_GENERATION_TIMERS):
            try:
                if wm is not None:
                    wm.event_timer_remove(timer)
            except FBP_DATA_ERRORS:
                continue
    except FBP_DATA_ERRORS:
        pass
    _FBP_GENERATION_TIMERS.clear()
    _FBP_GENERATION_OPERATORS.clear()
    _fbp_hide_generation_overlay(target_context)
    return True


def register():
    quiesce_generation_runtime(getattr(bpy, "context", None))
    from .ui_layout import fbp_invalidate_layer_tree_snapshot
    register_service("layers.refresh_tree", _fbp_refresh_layer_tree, owner=__name__)
    register_service(
        "layers.invalidate_tree_snapshot",
        fbp_invalidate_layer_tree_snapshot,
        owner=__name__,
    )


def unregister():
    """Remove transient overlays/timers when the extension is disabled or reloaded."""
    unregister_service("layers.invalidate_tree_snapshot")
    unregister_service("layers.refresh_tree")
    quiesce_generation_runtime(getattr(bpy, "context", None))
