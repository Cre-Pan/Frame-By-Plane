"""Blender handlers, timers and render-state guards for Frame by Plane."""

import time

import bpy

from . import core as _core
from . import scene_sync as _scene_sync
from . import layers as _layers
from . import materials as _materials
from . import effects_registry as _effects_registry
from .service_registry import call_service
from .managed_timers import (
    fbp_invalidate_timer_epoch,
    fbp_clear_managed_timers,
    fbp_managed_timer_callbacks,
    fbp_prune_timer_registry,
    fbp_register_timer_once,
)

from .registration import register_handlers, remove_handlers_by_name

from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_runtime_get,
    fbp_runtime_set,
    fbp_undo_guard_active,
    fbp_error,
    fbp_warn,
    fbp_warn_once,
    FBP_RENDER_IDLE,
    FBP_RENDER_BUSY,
    FBP_RENDER_UNKNOWN,
    fbp_render_state,
    fbp_main_data_ready,
    fbp_main_data_collection,
    fbp_resume_pending_redraw_requests,
    fbp_depsgraph_quiet_for,
    fbp_registration_busy,
)


# SECTION 00A - Undo / reload safety #
_FBP_UNDO_FAILSAFE_SECONDS = 30.0
_FBP_LOAD_FAILSAFE_SECONDS = 120.0
def fbp_undo_is_active():
    """Return the canonical runtime guard without releasing it from callbacks."""
    return fbp_undo_guard_active()


def fbp_render_is_active():
    """Return True for both FBP-owned and externally-started Blender renders."""
    try:
        return bool(_core.fbp_is_rendering_now())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        # Mutation-sensitive callers must stop when render state is unknown.
        return True

def fbp_set_undo_guard(active=True, *, timeout=None):
    deadline = 0.0
    if active and timeout is not None and float(timeout) > 0.0:
        deadline = time.monotonic() + float(timeout)
    try:
        fbp_runtime_set("fbp_undo_in_progress", bool(active))
        fbp_runtime_set("fbp_undo_guard_deadline", deadline)
        if not active:
            fbp_runtime_set("fbp_undo_release_not_before", 0.0)
    except FBP_DATA_IO_ERRORS:
        pass


def fbp_history_runtime_snapshot():
    """Return process-only Undo/load state for diagnostics."""
    now = time.monotonic()
    def _number(key):
        try:
            return float(fbp_runtime_get(key, 0.0) or 0.0)
        except (TypeError, ValueError, OverflowError):
            return 0.0
    active = bool(fbp_runtime_get("fbp_undo_in_progress", False))
    cleanup_pending = bool(fbp_runtime_get("fbp_history_cleanup_pending", False))
    deadline = _number("fbp_undo_guard_deadline")
    release_not_before = _number("fbp_undo_release_not_before")
    return {
        "active": active,
        "cleanup_pending": cleanup_pending,
        "deadline": deadline,
        "release_not_before": release_not_before,
        "deadline_remaining": max(0.0, deadline - now) if deadline > 0.0 else 0.0,
        "release_remaining": max(0.0, release_not_before - now) if release_not_before > 0.0 else 0.0,
        "managed_timers_paused": bool(fbp_runtime_get("fbp_pause_managed_timers", False)),
    }


def fbp_history_runtime_quiescent(snapshot=None):
    """Return True only when no history transition can strand deferred work."""
    state = snapshot if isinstance(snapshot, dict) else fbp_history_runtime_snapshot()
    return not bool(state.get("active")) and not bool(state.get("cleanup_pending"))

def fbp_cancel_deferred_mutation_tasks():
    """Discard one-shot datablock tasks that belong to the pre-Undo state.

    These callbacks may contain object names, runtime tokens or intended writes
    captured before Blender replaces Main. Post-Undo synchronization schedules
    fresh work from the restored state instead of allowing stale tasks to resume.
    """
    cleared = 0
    try:
        from . import safe_tasks as _fbp_safe_tasks
        cleared += int(_fbp_safe_tasks.clear_scheduled() or 0)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        call_service("dirty.clear")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        _layers.clear_layer_runtime_caches()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return cleared


def fbp_cancel_safe_tasks():
    """Cancel add-on timer closures before Blender replaces Main or unloads FBP."""
    try:
        from . import safe_tasks as _fbp_safe_tasks
    except ImportError:
        _fbp_safe_tasks = None
    if _fbp_safe_tasks:
        try:
            _fbp_safe_tasks.clear_scheduled()
        except FBP_DATA_IO_ERRORS:
            pass
    try:
        call_service("dirty.clear")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        _layers.clear_layer_runtime_caches()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .path_utils import clear_path_runtime_caches
        clear_path_runtime_caches()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from . import materials as _fbp_materials
        _fbp_materials.fbp_prepare_for_main_replacement()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        _scene_sync.fbp_reset_deferred_sync_state()
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        from . import native_backend as _fbp_native_backend
        _fbp_native_backend.fbp_clear_native_runtime_cache()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def fbp_release_custom_ui_icons_for_main_replacement():
    """Drop PNG preview ids before File > Revert/Load replaces Blender Main."""
    try:
        from .ui_icons import unregister_custom_icons, clear_ui_icon_cache
        unregister_custom_icons()
        clear_ui_icon_cache()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def fbp_reload_custom_ui_icons_after_main_replacement():
    """Recreate PNG preview ids after File > Revert/Load."""
    try:
        from .ui_icons import reload_custom_icons_after_file_load
        reload_custom_icons_after_file_load()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        try:
            fbp_warn_once(
                "custom_ui_icons_load_refresh",
                "Could not refresh Frame by Plane custom UI icons after loading the file",
                exc,
            )
        except FBP_DATA_IO_ERRORS:
            pass
    try:
        _core.fbp_tag_view3d_ui_redraw()
    except FBP_DATA_ERRORS:
        pass

def fbp_clear_effect_runtime_caches():
    """Invalidate per-frame caches before Undo, Main replacement or teardown."""
    try:
        from . import geometry_nodes as _geometry_nodes
        _geometry_nodes.fbp_clear_effect_runtime_caches()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        _core.fbp_clear_procedural_runtime_caches()
    except FBP_DATA_ERRORS:
        pass
    try:
        from .drawing_plane import clear_drawing_runtime_cache
        clear_drawing_runtime_cache()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .object_masks import clear_object_mask_runtime_cache
        clear_object_mask_runtime_cache()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .motion_runtime import clear_motion_runtime_caches
        clear_motion_runtime_caches()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .grease_pencil_bridge import clear_grease_pencil_runtime_caches
        clear_grease_pencil_runtime_caches()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .effect_controls import clear_effect_controls_runtime_cache
        clear_effect_controls_runtime_cache()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .custom_effects import clear_custom_effect_runtime_cache
        clear_custom_effect_runtime_cache()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .alpha_crop import clear_alpha_crop_cache
        clear_alpha_crop_cache()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .path_utils import clear_path_runtime_caches
        clear_path_runtime_caches()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .fbp_index import invalidate_scene_index
        invalidate_scene_index()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def fbp_stop_playback_for_safe_operation():
    """Stop playback in every Blender window before Main-changing operations."""
    try:
        return bool(
            _scene_sync.fbp_stop_playback_for_datablock_cleanup(
                getattr(bpy, "context", None)
            )
        )
    except FBP_DATA_IO_ERRORS:
        return False


def fbp_deferred_post_undo_sync():
    # Let Blender finish replacing Main/depsgraph before touching FBP data.
    if fbp_undo_is_active() or fbp_render_is_active():
        return 0.25
    try:
        context = bpy.context
        if context and getattr(context, "scene", None):
            # Never mutate virtual UI collections from undo_pre. The layer tree
            # is rebuilt by sync_layer_collection() below, while the pending
            # import tree is refreshed only when it actually contains data.
            from .preference_application import fbp_apply_preferences_to_scene
            try:
                fbp_apply_preferences_to_scene(context.scene, force=False, context=context)
            except FBP_DATA_ERRORS:
                pass
            # Undo can restore/remove registered custom node groups. Refresh
            # their lightweight registry once here instead of scanning all node
            # groups from every effect-stack query during playback or render.
            try:
                _effects_registry.fbp_refresh_custom_effect_registry(force=True)
            except FBP_DATA_ERRORS:
                pass
            # Native Undo can restore a rig after the conservative orphan pass
            # quarantined its plane. Reconnect that pair before rebuilding the
            # virtual layer tree; no ID datablock is created or removed here.
            try:
                _scene_sync.fbp_restore_quarantined_planes(context.scene)
            except FBP_DATA_ERRORS:
                pass
            # sync_layer_collection() also refreshes UI rows and snapshots
            # rig/plane links; do not repeat those O(scene size) passes here.
            _scene_sync.sync_layer_collection(context)
            try:
                pending = getattr(context.scene, "fbp_pending_planes", None)
                pending_rows = getattr(context.scene, "fbp_pending_tree_rows", None)
                if (pending is not None and len(pending)) or (
                    pending_rows is not None and len(pending_rows)
                ):
                    from .ui_layout import fbp_refresh_pending_tree_rows
                    fbp_refresh_pending_tree_rows(context)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            # Property callbacks intentionally stay inert while Main is being
            # restored. Reconcile rig/plane/GP visibility once all scene repair
            # has completed and Blender is back in its idle timer context.
            try:
                _layers.update_global_visibility(context)
            except FBP_DATA_ERRORS:
                pass
            # Shader/image assignment repairs are intentionally separated from
            # the first post-Undo viewport rebuild. They run only after a quiet
            # depsgraph window, preventing Eevee material workers from racing
            # Python changes to generated mask and drawing images.
            try:
                fbp_register_timer_once(
                    fbp_deferred_post_history_visual_sync,
                    1.50,
                    restart=True,
                )
            except FBP_DATA_ERRORS:
                pass
            try:
                from .grease_pencil_bridge import schedule_gp_history_reindex
                schedule_gp_history_reindex(first_interval=0.75)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
    except Exception as exc:
        fbp_error(
            "Could not sync Frame by Plane after undo",
            exc,
            event="handler.undo_post_sync",
        )
    return None


def fbp_deferred_post_history_visual_sync():
    """Repair visual bindings after Undo only when Blender evaluation is quiet."""
    if fbp_undo_is_active() or fbp_render_is_active():
        return 0.25
    if not fbp_depsgraph_quiet_for(0.75):
        return 0.15
    try:
        context = bpy.context
        scene = getattr(context, "scene", None) if context else None
        if scene is None:
            return None
        try:
            from .geometry_nodes import fbp_sync_clipping_masks
            fbp_sync_clipping_masks(context)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        try:
            from .drawing_plane import fbp_refresh_drawing_scene
            fbp_refresh_drawing_scene(scene)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    except Exception as exc:
        fbp_error(
            "Could not finish delayed post-history visual sync",
            exc,
            event="handler.post_history_visual_sync",
        )
    return None


def fbp_deferred_scene_sync():
    """Refresh lightweight layer/UI state after the active Scene changes."""
    if fbp_undo_is_active() or fbp_render_is_active():
        return 0.25
    try:
        context = bpy.context
        if context and getattr(context, "scene", None):
            from .preference_application import fbp_apply_preferences_to_scene
            try:
                fbp_apply_preferences_to_scene(
                    context.scene, force=False, context=context
                )
            except FBP_DATA_ERRORS:
                pass
            try:
                from .render_output import fbp_sync_render_output_from_native
                fbp_sync_render_output_from_native(context.scene, force=False)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass

            try:
                _materials.fbp_refresh_material_render_methods(context.scene)
            except FBP_DATA_ERRORS:
                pass

            try:
                _scene_sync.fbp_restore_quarantined_planes(context.scene)
            except FBP_DATA_ERRORS:
                pass
            # This already rebuilds the layer cache, refreshes the UI tree and
            # snapshots rig/plane links.
            _scene_sync.sync_layer_collection(context)
            try:
                from .native_backend import fbp_repair_native_sequence_timing_scene
                fbp_repair_native_sequence_timing_scene(context.scene)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            try:
                from .drawing_plane import fbp_refresh_drawing_scene
                fbp_refresh_drawing_scene(context.scene)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
    except Exception as exc:
        try:
            fbp_warn("Could not sync Frame by Plane after scene switch", exc)
        except FBP_DATA_ERRORS:
            pass
    return None


def fbp_deferred_camera_projection_sync():
    """Refresh camera-aware modifier inputs from Blender's safe timer context."""
    if fbp_undo_is_active() or fbp_render_is_active():
        return 0.25
    try:
        from . import geometry_nodes as _geometry_nodes
        scene = getattr(bpy.context, "scene", None)
        if scene is not None:
            _geometry_nodes.fbp_sync_scene_camera_bindings(scene)
            # Clipping Mask camera matrices are depsgraph-native drivers. Only
            # active-camera/type changes need a deferred binding refresh; never
            # rewrite shader sockets directly from this message-bus timer.
            _geometry_nodes.fbp_schedule_clipping_mask_sync(
                scene, camera_change=True
            )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not refresh camera-aware effects", exc)
    return None


def _fbp_reset_render_idle_confirmation():
    fbp_runtime_set("fbp_render_idle_confirmations", 0)
    fbp_runtime_set("fbp_render_idle_first_seen_at", 0.0)
    fbp_runtime_set("fbp_render_idle_last_seen_at", 0.0)


def _fbp_confirm_render_idle(now):
    """Require multiple spaced idle observations after render completion."""
    try:
        first = float(fbp_runtime_get("fbp_render_idle_first_seen_at", 0.0) or 0.0)
        last = float(fbp_runtime_get("fbp_render_idle_last_seen_at", 0.0) or 0.0)
        count = int(fbp_runtime_get("fbp_render_idle_confirmations", 0) or 0)
    except (TypeError, ValueError):
        first = last = 0.0
        count = 0
    if first <= 0.0:
        first = now
        last = 0.0
        count = 0
        fbp_runtime_set("fbp_render_idle_first_seen_at", first)
    if last <= 0.0 or now - last >= 0.20:
        count += 1
        last = now
        fbp_runtime_set("fbp_render_idle_confirmations", count)
        fbp_runtime_set("fbp_render_idle_last_seen_at", last)
    return count >= 5 and now - first >= 1.0


def fbp_render_guard_watchdog():
    """Restore render-only state after a proven native idle interval.

    ``bpy.app.is_job_running('RENDER')`` is necessary but not sufficient during
    the last window-manager transition: the render thread may still be leaving
    Cycles while queued UI notifiers are processed. Completion therefore uses a
    callback grace, several spaced idle samples and a quiet depsgraph window.
    """
    if not bool(fbp_runtime_get("fbp_render_guard_active", False)):
        return 2.0

    now = time.monotonic()
    try:
        started_at = float(fbp_runtime_get("fbp_render_started_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        started_at = 0.0
    elapsed = now - started_at if started_at > 0.0 else 0.0
    expected_end = bool(fbp_runtime_get("fbp_render_end_requested", False))
    try:
        end_requested_at = float(
            fbp_runtime_get("fbp_render_end_requested_at", 0.0) or 0.0
        )
        cleanup_not_before = float(
            fbp_runtime_get("fbp_render_cleanup_not_before", 0.0) or 0.0
        )
    except (TypeError, ValueError):
        end_requested_at = cleanup_not_before = 0.0

    if not expected_end and (started_at <= 0.0 or elapsed < 5.0):
        _fbp_reset_render_idle_confirmation()
        return 0.5

    render_state = fbp_render_state(include_guard=False)
    if render_state == FBP_RENDER_BUSY:
        _fbp_reset_render_idle_confirmation()
        return 0.25 if expected_end else 0.5

    if render_state == FBP_RENDER_UNKNOWN:
        _fbp_reset_render_idle_confirmation()
        if expected_end and end_requested_at > 0.0:
            if now - end_requested_at >= 10.0:
                fbp_warn_once(
                    "render_state_unknown_cleanup_wait",
                    "Render cleanup is waiting because Blender's render state cannot be confirmed",
                )
            return 0.5
        return 2.0

    if not expected_end and elapsed < 60.0:
        _fbp_reset_render_idle_confirmation()
        return 2.0

    if expected_end:
        if cleanup_not_before > now:
            _fbp_reset_render_idle_confirmation()
            return max(0.20, min(0.75, cleanup_not_before - now))
        if not fbp_depsgraph_quiet_for(0.75):
            _fbp_reset_render_idle_confirmation()
            return 0.25
        if not _fbp_confirm_render_idle(now):
            return 0.25

    try:
        scene = getattr(bpy.context, "scene", None)
        restored = bool(_core.fbp_render_guard_idle_restore(scene))
        if not restored and bool(fbp_runtime_get("fbp_render_guard_active", False)):
            failures = int(fbp_runtime_get("fbp_render_restore_failures", 0) or 0) + 1
            fbp_runtime_set("fbp_render_restore_failures", failures)
            if failures == 3:
                fbp_warn_once(
                    "render_guard_restore_retry",
                    "Render cleanup could not restore every temporary value and will retry safely",
                )
            if failures >= 20:
                fbp_warn_once(
                    "render_guard_restore_abandoned",
                    "Render cleanup released its guard after repeated idle restore failures",
                )
                _core.fbp_render_guard_abandon()
                fbp_runtime_set("fbp_managed_timers_resume_after", now + 1.0)
                return 2.0
            _fbp_reset_render_idle_confirmation()
            return min(2.0, 0.25 * max(1, failures))
        if not expected_end:
            fbp_warn_once(
                "render_guard_watchdog_restore",
                "Recovered an interrupted Frame by Plane render guard",
            )
        # Keep deferred mutation and editor redraws behind one extra main-loop
        # grace after the final restoration writes have emitted their notifiers.
        fbp_runtime_set("fbp_managed_timers_resume_after", now + 1.0)
        fbp_resume_pending_redraw_requests(first_interval=1.10)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not recover interrupted render guard", exc)
        _fbp_reset_render_idle_confirmation()
        return 0.5
    return 2.0


def fbp_camera_projection_notify():
    """Message-bus callback for active camera and projection-property changes."""
    if fbp_undo_is_active() or fbp_render_is_active():
        return
    fbp_register_timer_once(fbp_deferred_camera_projection_sync, 0.03)


def fbp_scene_change_notify():
    """Message-bus callback: run as soon as the active Window.scene changes."""
    if bool(fbp_runtime_get("fbp_pause_managed_timers", False)):
        return
    try:
        resume_after = float(
            fbp_runtime_get("fbp_managed_timers_resume_after", 0.0) or 0.0
        )
    except (TypeError, ValueError):
        resume_after = 0.0
    if resume_after > time.monotonic():
        return
    if fbp_undo_is_active() or fbp_render_is_active():
        return
    fbp_register_timer_once(fbp_deferred_scene_sync, 0.12)
    fbp_register_timer_once(fbp_deferred_camera_projection_sync, 0.03)

def _fbp_finalize_history_transaction():
    """Retire pre-Undo runtime work only after Blender is idle again.

    Undo callbacks must not unregister timers, clear caches containing RNA
    wrappers, stop playback or inspect restored datablocks. Eevee can still be
    synchronizing image materials on worker threads while ``undo_pre`` and
    ``undo_post`` run. The persistent watchdog reaches this function only after
    the post-history grace period from Blender's ordinary timer loop.
    """
    try:
        fbp_cancel_deferred_mutation_tasks()
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        _scene_sync.fbp_reset_deferred_sync_state()
    except FBP_DATA_ERRORS:
        pass
    try:
        fbp_clear_effect_runtime_caches()
    except FBP_DATA_ERRORS:
        pass
    try:
        from . import native_backend as _fbp_native_backend
        _fbp_native_backend.fbp_clear_native_runtime_cache()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .compositor import fbp_reset_compositor_runtime_state
        fbp_reset_compositor_runtime_state()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .compositor_sets import fbp_reset_compositor_sets_runtime_state
        fbp_reset_compositor_sets_runtime_state()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    fbp_runtime_set("fbp_history_cleanup_pending", False)


def fbp_undo_guard_watchdog():
    """Finish Undo/Redo from Blender's idle timer context."""
    if not fbp_undo_is_active():
        return 2.0
    try:
        now = time.monotonic()
        release_at = float(
            fbp_runtime_get("fbp_undo_release_not_before", 0.0) or 0.0
        )
        if release_at > 0.0:
            remaining = release_at - now
            if remaining > 0.0:
                return min(0.10, max(0.03, remaining))

            _fbp_finalize_history_transaction()
            fbp_set_undo_guard(False)
            # Keep general maintenance timers dormant for one more viewport
            # redraw. The dedicated post-history sync is registered explicitly.
            fbp_runtime_set("fbp_managed_timers_resume_after", now + 0.75)
            fbp_register_timer_once(fbp_deferred_post_undo_sync, 0.80, restart=True)
            fbp_resume_pending_redraw_requests(first_interval=0.90)
            return 2.0

        deadline = float(fbp_runtime_get("fbp_undo_guard_deadline", 0.0) or 0.0)
        if deadline <= 0.0:
            return 0.10
        remaining = deadline - now
        if remaining > 0.0:
            return min(0.25, max(0.05, remaining))

        # Missed undo_post/load_post: fail closed until this idle watchdog can
        # safely retire stale work, then recover the add-on runtime.
        _fbp_finalize_history_transaction()
        fbp_set_undo_guard(False)
        fbp_runtime_set("fbp_managed_timers_resume_after", now + 0.75)
        fbp_warn_once(
            "undo_guard_watchdog_failsafe",
            "Undo/load guard exceeded its safety deadline and was released automatically",
        )
        fbp_register_timer_once(fbp_deferred_post_undo_sync, 0.80, restart=True)
        fbp_resume_pending_redraw_requests(first_interval=0.90)
    except Exception as exc:
        # A watchdog failure must never leave the add-on permanently locked. This
        # callback itself runs from a safe timer, so a forced release is valid.
        fbp_set_undo_guard(False)
        fbp_runtime_set("fbp_history_cleanup_pending", False)
        fbp_warn("Undo/load guard watchdog failed and forced a release", exc)
        try:
            fbp_register_timer_once(fbp_deferred_post_undo_sync, 0.80, restart=True)
        except FBP_DATA_ERRORS:
            pass
    return 2.0


@bpy.app.handlers.persistent
def fbp_undo_pre_handler(_scene):
    """Enter the history guard without changing Blender data or timer ownership.

    In Blender 5.2 Eevee may still acquire Image buffers on worker threads while
    Undo begins. The only pre-history work is a process-only snapshot of the
    Scrub Slider playhead; cache/timer cleanup remains deferred to the watchdog.
    """
    if fbp_registration_busy():
        return
    try:
        from .grease_pencil_scrub import prepare_scrub_history_restore
        prepare_scrub_history_restore(_scene)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    fbp_set_undo_guard(True, timeout=_FBP_UNDO_FAILSAFE_SECONDS)
    # Process-only invalidation: do not unregister Blender timers or clear
    # runtime caches while Main/history replacement is still in progress.
    fbp_invalidate_timer_epoch()
    try:
        from .safe_tasks import invalidate_task_epoch
        invalidate_task_epoch()
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass
    fbp_runtime_set("fbp_history_cleanup_pending", True)
    fbp_runtime_set("fbp_undo_release_not_before", 0.0)


@bpy.app.handlers.persistent
def fbp_redo_pre_handler(scene):
    """Use the same Main-replacement guard for Redo as for Undo."""
    if fbp_registration_busy():
        return
    fbp_undo_pre_handler(scene)


def _fbp_history_post_handler():
    """Mark Undo/Redo complete without registering or cancelling timers.

    Blender should always emit the matching pre callback.  In practice an
    interrupted add-on reload or a third-party handler can make the post event
    arrive after our pre generation disappeared.  Re-entering the process-only
    guard here prevents a permanently pending cleanup state.
    """
    now = time.monotonic()
    if not fbp_undo_is_active():
        fbp_set_undo_guard(True, timeout=8.0)
    fbp_runtime_set("fbp_history_cleanup_pending", True)
    fbp_runtime_set("fbp_undo_release_not_before", now + 0.75)
    fbp_runtime_set("fbp_undo_guard_deadline", now + 8.0)


@bpy.app.handlers.persistent
def fbp_undo_post_handler(scene):
    if fbp_registration_busy():
        return
    # Count only completed history operations. The endurance baseline stores no
    # RNA pointers and therefore remains valid while Blender replaces Main.
    try:
        call_service("endurance.note_undo")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    # Blender restores Scene.frame_current with the GP edit snapshot. Keep the
    # frame explicitly chosen through the Scrub Slider while leaving the stroke,
    # sculpt or edit operation itself undone. The global undo guard is already
    # active, so addon frame callbacks remain mutation-free here.
    try:
        from .grease_pencil_scrub import restore_scrub_history_frame
        restore_scrub_history_frame(scene)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    _fbp_history_post_handler()


@bpy.app.handlers.persistent
def fbp_redo_post_handler(scene):
    if fbp_registration_busy():
        return
    try:
        call_service("endurance.note_redo")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .grease_pencil_scrub import restore_scrub_history_frame
        restore_scrub_history_frame(scene)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    _fbp_history_post_handler()


# Textured playback remains visible. The frame-change handler is used only by
# procedural Color / Gradient / Holdout rows.

# SECTION 00C - Scene switch / missing image GPU safety #
_FBP_SCENE_MSGBUS_OWNER = globals().get("_FBP_SCENE_MSGBUS_OWNER", object())


def _fbp_expand_layer_tree_path(scene, target):
    """Expand the canonical Layer List collection path containing ``target``.

    Layer rows can intentionally use ``fbp_collection_name`` as a visual group
    without physically relinking the Object in Blender's collection graph. The
    Layer List is built from that canonical visual assignment, so active-object
    synchronization must follow the same path instead of searching only raw
    ``Collection.objects`` links.
    """
    root = getattr(scene, "collection", None) if scene is not None else None
    if root is None or target is None:
        return False

    changed = False

    def expand(collection):
        nonlocal changed
        if collection is None or collection == root:
            return
        try:
            if bool(getattr(collection, "fbp_collapsed", False)):
                collection.fbp_collapsed = False
                changed = True
        except FBP_DATA_ERRORS:
            pass

    # Primary path: use the exact collection resolver shared by the Layer List.
    # This is both more accurate for visual-only grouping and O(tree depth)
    # after one canonical tree snapshot instead of recursively testing every
    # collection's object membership on each active-object change.
    try:
        collection = _layers.get_primary_fbp_collection(target)
        tree = _layers.fbp_build_canonical_collection_tree(scene)
        collections = tree.get("collections", {}) or {}
        parent_by_key = tree.get("parent_by_key", {}) or {}
        root_key = tree.get("root_key")
        try:
            collection_key = int(collection.as_pointer()) if collection is not None else None
        except FBP_DATA_ERRORS:
            collection_key = id(collection) if collection is not None else None
        if collection_key in collections:
            current_key = collection_key
            visited = set()
            while current_key is not None and current_key != root_key and current_key not in visited:
                visited.add(current_key)
                expand(collections.get(current_key))
                current_key = parent_by_key.get(current_key)
            return changed
    except FBP_DATA_ERRORS:
        pass

    # Physical-link fallback for malformed or transient files whose visual collection
    # hint is missing. Find only the first physical path instead of expanding all
    # duplicate links of an Object that belongs to multiple collections.
    target_name = str(getattr(target, "name", "") or "")
    if not target_name:
        return changed
    visited = set()

    def find_path(collection, path):
        try:
            pointer = int(collection.as_pointer())
        except FBP_DATA_ERRORS:
            pointer = id(collection)
        if pointer in visited:
            return None
        visited.add(pointer)
        try:
            if getattr(collection.objects, "get", lambda _name: None)(target_name) is target:
                return path + [collection]
        except FBP_DATA_ERRORS:
            pass
        try:
            children = tuple(getattr(collection, "children", ()) or ())
        except FBP_DATA_ERRORS:
            children = ()
        for child in children:
            result = find_path(child, path + [collection])
            if result:
                return result
        return None

    for collection in find_path(root, []) or ():
        expand(collection)
    return changed


def fbp_deferred_active_layer_ui_sync():
    """Highlight the Layer List row represented by the active viewport object."""
    if fbp_undo_is_active() or fbp_render_is_active():
        return 0.10
    context = getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context is not None else None
    view_layer = getattr(context, "view_layer", None) if context is not None else None
    active = getattr(getattr(view_layer, "objects", None), "active", None) if view_layer is not None else None
    try:
        from .grease_pencil_bridge import sync_gp_mask_interaction_state
        sync_gp_mask_interaction_state(context=context, scene=scene, active=active)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    # Selecting a collection row necessarily selects one or more viewport
    # objects. Blender then emits an active-object notification that used to
    # replace the blue collection row with the last selected child layer. Keep
    # the collection active only for that short selection transaction; explicit
    # layer clicks clear the guard immediately from operator_layers.
    guard = fbp_runtime_get("fbp.collection_row_selection_guard", None)
    if isinstance(guard, dict) and scene is not None:
        try:
            expires = float(guard.get("expires", 0.0) or 0.0)
            scene_pointer = int(scene.as_pointer())
            guarded_pointer = int(guard.get("scene_pointer", 0) or 0)
            collection_name = str(guard.get("collection_name", "") or "")
            if expires >= time.monotonic() and (not guarded_pointer or guarded_pointer == scene_pointer):
                rows = getattr(scene, "fbp_layer_tree_rows", ()) or ()
                guarded_index = int(guard.get("tree_index", -1) or -1)
                if not (
                    0 <= guarded_index < len(rows)
                    and str(getattr(rows[guarded_index], "row_type", "") or "") == "GROUP"
                    and str(getattr(rows[guarded_index], "collection_name", "") or "") == collection_name
                ):
                    guarded_index = next((
                        index for index, row in enumerate(rows)
                        if str(getattr(row, "row_type", "") or "") == "GROUP"
                        and str(getattr(row, "collection_name", "") or "") == collection_name
                    ), -1)
                if guarded_index >= 0:
                    if int(getattr(scene, "fbp_layer_tree_rows_idx", -1)) != guarded_index:
                        scene.fbp_layer_tree_rows_idx = guarded_index
                        try:
                            _core.fbp_tag_view3d_ui_redraw()
                        except FBP_DATA_ERRORS:
                            pass
                    return None
                # The virtual row collection may be waiting for Blender to
                # release wrappers from the click that selected this group. Keep
                # the stable collection-name guard alive and retry after the
                # deferred rebuild rather than letting the active child object
                # steal the blue UIList selection.
                try:
                    from .ui_layout import fbp_refresh_layer_tree_rows
                    fbp_refresh_layer_tree_rows(context)
                except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
                return 0.05
            fbp_runtime_set("fbp.collection_row_selection_guard", None)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OverflowError):
            fbp_runtime_set("fbp.collection_row_selection_guard", None)

    if scene is None or active is None:
        return None

    target_type = ""
    target_name = ""
    rig = None
    try:
        from .grease_pencil_bridge import is_gp_canvas
        if is_gp_canvas(active):
            target_type = "GP_CANVAS"
            target_name = str(getattr(active, "name", "") or "")
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    if not target_type:
        try:
            rig = _layers.fbp_resolve_rig_from_any_object(active, context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            rig = None
        if rig is None:
            return None
        target_type = "LAYER"
        target_name = str(getattr(rig, "name", "") or "")

    changed = False
    if rig is not None:
        try:
            for index, item in enumerate(tuple(getattr(scene, "fbp_layers", ()) or ())):
                if getattr(item, "obj", None) is rig:
                    if int(getattr(scene, "fbp_layer_stack_index", -1)) != index:
                        scene.fbp_layer_stack_index = index
                        changed = True
                    break
        except FBP_DATA_ERRORS:
            pass

    reveal_target = rig if rig is not None else active
    tree_path_changed = _fbp_expand_layer_tree_path(scene, reveal_target)
    changed = changed or tree_path_changed

    def find_tree_index():
        try:
            for index, row in enumerate(tuple(getattr(scene, "fbp_layer_tree_rows", ()) or ())):
                row_type = str(getattr(row, "row_type", "") or "")
                if row_type != target_type:
                    continue
                row_name = (
                    str(getattr(row, "canvas_name", "") or "")
                    if target_type == "GP_CANVAS"
                    else str(getattr(row, "rig_name", "") or "")
                )
                if row_name == target_name:
                    return index
        except FBP_DATA_ERRORS:
            pass
        return -1

    tree_index = -1 if tree_path_changed else find_tree_index()
    refresh_was_deferred = False
    if tree_index < 0:
        try:
            from .ui_layout import fbp_refresh_layer_tree_rows
            from .ui_list_state import ui_list_mutation_delay
            refresh_was_deferred = ui_list_mutation_delay() > 0.0
            fbp_refresh_layer_tree_rows(context)
            tree_index = find_tree_index()
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            tree_index = -1
    if tree_index < 0 and refresh_was_deferred:
        try:
            scene_pointer = int(scene.as_pointer())
        except FBP_DATA_ERRORS:
            scene_pointer = 0
        retry_token = f"{scene_pointer}:{target_type}:{target_name}"
        previous_retry = str(
            fbp_runtime_get("fbp.active_layer_ui_sync_retry_token", "") or ""
        )
        if previous_retry != retry_token:
            fbp_runtime_set("fbp.active_layer_ui_sync_retry_token", retry_token)
            return 0.06
    fbp_runtime_set("fbp.active_layer_ui_sync_retry_token", "")
    if tree_index >= 0:
        try:
            if int(getattr(scene, "fbp_layer_tree_rows_idx", -1)) != tree_index:
                scene.fbp_layer_tree_rows_idx = tree_index
                changed = True
        except FBP_DATA_ERRORS:
            pass
    if changed:
        try:
            _core.fbp_tag_view3d_ui_redraw()
        except FBP_DATA_ERRORS:
            pass
    return None


def fbp_active_object_notify():
    """Defer active-object UI synchronization outside the message-bus callback."""
    try:
        from .safe_tasks import schedule_once
        schedule_once(
            "handlers.active_layer_ui_sync",
            fbp_deferred_active_layer_ui_sync,
            first_interval=0.0,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def fbp_deferred_render_output_sync():
    """Read native RenderSettings.filepath after Blender has left the RNA callback."""
    if fbp_undo_is_active() or fbp_render_is_active():
        return 0.25
    try:
        from .render_output import fbp_sync_all_render_outputs_from_native
        fbp_sync_all_render_outputs_from_native(force=False)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not synchronize Blender and Frame By Plane output paths", exc)
    return None


def fbp_render_output_notify():
    """Coalesce native output-path edits into one safe main-loop synchronization."""
    try:
        from .safe_tasks import schedule_once
        schedule_once(
            "handlers.render_output_sync",
            fbp_deferred_render_output_sync,
            first_interval=0.02,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def fbp_deferred_render_format_sync():
    """Rebuild composed filenames when image/movie output type changes."""
    if fbp_undo_is_active() or fbp_render_is_active():
        return 0.25
    try:
        from .render_output import fbp_sync_native_render_path
        for scene in tuple(getattr(bpy.data, "scenes", ()) or ()):
            if str(getattr(scene, "fbp_render_filename_mode", "NATIVE") or "NATIVE") == 'COMPOSE':
                fbp_sync_native_render_path(scene)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not update render filename after format change", exc)
    return None


def fbp_render_format_notify():
    try:
        from .safe_tasks import schedule_once
        schedule_once(
            "handlers.render_format_sync",
            fbp_deferred_render_format_sync,
            first_interval=0.02,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def fbp_subscribe_scene_msgbus():
    """Restore scene and camera subscriptions, which Blender clears on file load."""
    try:
        bpy.msgbus.clear_by_owner(_FBP_SCENE_MSGBUS_OWNER)
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.Window, "scene"),
            owner=_FBP_SCENE_MSGBUS_OWNER,
            args=(),
            notify=fbp_scene_change_notify,
        )
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.Scene, "camera"),
            owner=_FBP_SCENE_MSGBUS_OWNER,
            args=(),
            notify=fbp_camera_projection_notify,
        )
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.RenderSettings, "filepath"),
            owner=_FBP_SCENE_MSGBUS_OWNER,
            args=(),
            notify=fbp_render_output_notify,
        )
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.ImageFormatSettings, "file_format"),
            owner=_FBP_SCENE_MSGBUS_OWNER,
            args=(),
            notify=fbp_render_format_notify,
        )
        for property_name in (
            "type", "lens", "sensor_width", "ortho_scale", "shift_x", "shift_y"
        ):
            bpy.msgbus.subscribe_rna(
                key=(bpy.types.Camera, property_name),
                owner=_FBP_SCENE_MSGBUS_OWNER,
                args=(),
                notify=fbp_camera_projection_notify,
            )
        layer_objects_type = getattr(bpy.types, "LayerObjects", None)
        if layer_objects_type is not None:
            bpy.msgbus.subscribe_rna(
                key=(layer_objects_type, "active"),
                owner=_FBP_SCENE_MSGBUS_OWNER,
                args=(),
                notify=fbp_active_object_notify,
            )
        return True
    except FBP_DATA_ERRORS as exc:
        try:
            fbp_warn("Could not subscribe to scene-switch safety message bus", exc)
        except FBP_DATA_ERRORS:
            pass
        return False


@bpy.app.handlers.persistent
def fbp_load_pre_handler(_dummy):
    """Enter a process-only Main-replacement barrier.

    Blender 5.2 may still have viewport workers reading Image/Material data when
    ``load_pre`` runs. Do not unregister timers, release previews or inspect any
    Blender IDs here. Epoch invalidation makes every pre-load safe-task runner
    inert; actual cleanup happens from the post-load idle loop.
    """
    if fbp_registration_busy():
        return
    fbp_set_undo_guard(True, timeout=_FBP_LOAD_FAILSAFE_SECONDS)
    # Keep the persistent idle watchdog registered. It is the component that
    # safely performs cleanup after Blender finishes replacing Main.
    fbp_invalidate_timer_epoch()
    fbp_runtime_set("fbp_history_cleanup_pending", True)
    fbp_runtime_set("fbp_pause_managed_timers", True)
    try:
        from .safe_tasks import invalidate_task_epoch
        invalidate_task_epoch()
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass


def fbp_register_object_mask_runtime_timer():
    try:
        from .object_masks import object_mask_runtime_timer
        return fbp_register_timer_once(
            object_mask_runtime_timer, 0.12, persistent=True
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not start Shape Mask runtime service", exc)
        return False


def fbp_deferred_load_post_rebuild():
    """Rebuild loaded-file services only after Blender exposes an idle Main."""
    # Retire pre-load Python runtime from the ordinary idle loop, never from
    # load_pre while Eevee or Blender's Main replacement may still be active.
    try:
        call_service("endurance.clear")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        fbp_cancel_safe_tasks()
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        _core.fbp_render_guard_abandon()
    except FBP_DATA_ERRORS:
        pass
    try:
        _layers.clear_previews()
    except FBP_DATA_ERRORS:
        pass
    try:
        fbp_release_custom_ui_icons_for_main_replacement()
    except FBP_DATA_ERRORS:
        pass
    try:
        _layers.fbp_reset_layer_view_cache_state()
    except FBP_DATA_ERRORS:
        pass
    try:
        fbp_clear_effect_runtime_caches()
    except FBP_DATA_ERRORS:
        pass
    fbp_runtime_set("fbp_pause_managed_timers", False)
    fbp_runtime_set("fbp_managed_timers_resume_after", time.monotonic() + 0.20)

    # Persistence baselines use a saved generation counter in addition to a
    # process-local token. This proves that Verify Reopened File actually ran
    # after Blender replaced Main, even when the same application session is
    # used to close and reopen the .blend.
    for scene in tuple(getattr(bpy.data, "scenes", ()) or ()):
        try:
            scene["fbp_persistence_load_generation"] = int(
                scene.get("fbp_persistence_load_generation", 0) or 0
            ) + 1
        except FBP_DATA_ERRORS:
            continue
    try:
        from .preference_application import fbp_mark_scenes_preferences_initialized
        fbp_mark_scenes_preferences_initialized()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    try:
        _effects_registry.fbp_refresh_custom_effect_registry(force=True)
    except FBP_DATA_ERRORS as exc:
        fbp_warn_once(
            "custom_effect_registry_load_refresh",
            "Could not refresh custom effects after loading the file",
            exc,
        )

    fbp_subscribe_scene_msgbus()
    fbp_reload_custom_ui_icons_after_main_replacement()
    fbp_register_timer_once(fbp_deferred_scene_sync, 0.12)
    fbp_register_timer_once(_scene_sync.cleanup_orphan_fbp_planes_timer, 4.0)
    fbp_register_object_mask_runtime_timer()
    return None


@bpy.app.handlers.persistent
def fbp_load_post_handler(_dummy):
    if fbp_registration_busy():
        return
    # Load callbacks may run while Blender is finalizing a Main replacement.
    # Keep this callback process-local: restore namespaces/watchdogs, then defer
    # every Scene, node-group, icon and message-bus operation to the idle loop.
    fbp_set_undo_guard(False)
    fbp_runtime_set("fbp_pause_managed_timers", False)
    fbp_runtime_set("fbp_managed_timers_resume_after", time.monotonic() + 0.10)
    try:
        from .object_masks import register_shape_mask_driver_namespace
        register_shape_mask_driver_namespace()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .geometry_nodes import register_clipping_matrix_driver_namespace
        register_clipping_matrix_driver_namespace()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .render_output import fbp_clear_render_output_cache
        fbp_clear_render_output_cache()
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass
    # A background render process has no editor, selection, Undo stack or UI
    # notifier work to maintain. The render/frame handlers below remain active;
    # all viewport and maintenance timers stay disabled for the child process.
    if bool(getattr(bpy.app, "background", False)):
        # Background children have no persistent idle watchdog.  A load_pre
        # event must therefore not leave the process-only cleanup flag set after
        # Main has finished loading.
        fbp_runtime_set("fbp_history_cleanup_pending", False)
        fbp_runtime_set("fbp_pause_managed_timers", False)
        return
    fbp_register_timer_once(fbp_render_guard_watchdog, 2.0, persistent=True)
    fbp_register_timer_once(fbp_undo_guard_watchdog, 2.0, persistent=True)
    fbp_register_timer_once(fbp_deferred_load_post_rebuild, 0.08, restart=True)

# SECTION 01 - Register handlers / timers #
def register():
    is_background = bool(getattr(bpy.app, "background", False))
    # Recover from an interrupted maintenance run or in-place extension reload.
    # No process-local maintenance guard may survive a fresh registration.
    fbp_runtime_set("fbp_pause_managed_timers", False)
    fbp_runtime_set("fbp_managed_timers_resume_after", 0.0)
    fbp_prune_timer_registry()
    # Retire runtime data left by an in-place extension reload before any handler
    # can observe identities or pointers from the previous module generation.
    fbp_clear_effect_runtime_caches()
    try:
        _scene_sync.fbp_reset_deferred_sync_state()
    except FBP_DATA_ERRORS:
        pass
    if bpy.context and not is_background:
        # One complete scene sync replaces the older pair of overlapping startup
        # scans. It already rebuilds layers, native timing and Drawing Plane data.
        fbp_register_timer_once(fbp_deferred_scene_sync, 0.12)
        fbp_register_timer_once(_scene_sync.cleanup_orphan_fbp_planes_timer, 8.0)
        fbp_register_timer_once(fbp_render_guard_watchdog, 2.0, persistent=True)
        fbp_register_timer_once(fbp_undo_guard_watchdog, 2.0, persistent=True)
        fbp_register_object_mask_runtime_timer()

    # Background Blender has no scene-switching Window or editor message bus.
    if not is_background:
        fbp_subscribe_scene_msgbus()

    # Retire current and stale generations before installing one owned callback
    # per lifecycle slot. Module ownership prevents touching another extension
    # that happens to use the same Python function name.
    for handler_list in (
        bpy.app.handlers.frame_change_pre,
        bpy.app.handlers.frame_change_post,
    ):
        remove_handlers_by_name(
            handler_list, "fbp_frame_change_handler", module_suffix="core"
        )
        remove_handlers_by_name(
            handler_list,
            "fbp_shape_mask_frame_change_post",
            module_suffix="object_masks",
        )

    owned_depsgraph_handlers = (
        ("fbp_depsgraph_native_ops_handler", "scene_sync"),
        ("effect_controls_depsgraph_update", "effect_controls"),
        ("fbp_gp_depsgraph_update", "grease_pencil_bridge"),
        ("_depsgraph_auto_timing_sync", "grease_pencil_workflow"),
        ("_fbp_motion_depsgraph_update", "motion_runtime"),
        ("fbp_compositor_sets_depsgraph_post", "compositor_sets"),
    )
    for name, module_suffix in owned_depsgraph_handlers:
        remove_handlers_by_name(
            bpy.app.handlers.depsgraph_update_post,
            name,
            module_suffix=module_suffix,
        )

    for handler_list in (
        bpy.app.handlers.render_init,
        bpy.app.handlers.render_pre,
        bpy.app.handlers.render_post,
        bpy.app.handlers.render_cancel,
        bpy.app.handlers.render_complete,
    ):
        remove_handlers_by_name(
            handler_list,
            "fbp_render_guard_pre",
            "fbp_render_guard_complete",
            module_suffix="core",
        )
        remove_handlers_by_name(
            handler_list,
            "fbp_shape_mask_render_pre",
            module_suffix="object_masks",
        )

    history_names = (
        (bpy.app.handlers.undo_pre, "fbp_undo_pre_handler"),
        (bpy.app.handlers.undo_post, "fbp_undo_post_handler"),
        (bpy.app.handlers.load_pre, "fbp_load_pre_handler"),
        (bpy.app.handlers.load_post, "fbp_load_post_handler"),
    )
    for handler_list, name in history_names:
        remove_handlers_by_name(handler_list, name, module_suffix="handlers")
    redo_pre = getattr(bpy.app.handlers, "redo_pre", None)
    redo_post = getattr(bpy.app.handlers, "redo_post", None)
    if redo_pre is not None:
        remove_handlers_by_name(
            redo_pre, "fbp_redo_pre_handler", module_suffix="handlers"
        )
    if redo_post is not None:
        remove_handlers_by_name(
            redo_post, "fbp_redo_post_handler", module_suffix="handlers"
        )

    handler_specs = [
        (bpy.app.handlers.frame_change_pre, _core.fbp_frame_change_handler, "core"),
        (bpy.app.handlers.render_init, _core.fbp_render_guard_pre, "core"),
        (bpy.app.handlers.render_cancel, _core.fbp_render_guard_complete, "core"),
        (bpy.app.handlers.render_complete, _core.fbp_render_guard_complete, "core"),
        # Background processes also replace Main when opening a .blend. Their
        # load_post path restores pure driver namespace functions, then exits.
        (bpy.app.handlers.load_post, fbp_load_post_handler, "handlers"),
    ]
    if not is_background:
        handler_specs.extend((
            (
                bpy.app.handlers.depsgraph_update_post,
                _scene_sync.fbp_depsgraph_native_ops_handler,
                "scene_sync",
            ),
            (bpy.app.handlers.undo_pre, fbp_undo_pre_handler, "handlers"),
            (bpy.app.handlers.undo_post, fbp_undo_post_handler, "handlers"),
            (bpy.app.handlers.load_pre, fbp_load_pre_handler, "handlers"),
        ))
        if redo_pre is not None:
            handler_specs.append((redo_pre, fbp_redo_pre_handler, "handlers"))
        if redo_post is not None:
            handler_specs.append((redo_post, fbp_redo_post_handler, "handlers"))
    register_handlers(handler_specs)


# SECTION 02 - Unregister handlers / timers #
def unregister():
    fbp_set_undo_guard(False)
    fbp_runtime_set("fbp_pause_managed_timers", False)
    fbp_runtime_set("fbp_managed_timers_resume_after", 0.0)
    can_mutate_ids = False
    # If the extension is disabled during a managed render, restore temporary
    # viewport/effect overrides before runtime backups are cleared.
    try:
        render_state = fbp_render_state(include_guard=False)
        if render_state != FBP_RENDER_IDLE:
            # Never mutate render-owned datablocks while Blender is evaluating.
            # Unknown job state is also unsafe, even when the FBP guard was not
            # the component that started the render.
            _core.fbp_render_guard_abandon()
        else:
            _core.fbp_render_guard_force_restore(getattr(bpy.context, "scene", None))
            # The force-restore call above retires the managed guard. Once
            # Blender has confirmed an idle render state, cosmetic cache
            # properties can be removed even when the guard was active on entry.
            can_mutate_ids = not bool(
                fbp_runtime_get("fbp_render_guard_active", False)
            )
    except FBP_DATA_ERRORS as exc:
        try:
            _core.fbp_render_guard_abandon()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        fbp_warn("Could not retire render state during unregister", exc)
    try:
        _layers.clear_previews()
    except Exception as exc:
        fbp_warn("Could not clear Frame by Plane previews", exc)
    fbp_cancel_safe_tasks()
    fbp_clear_effect_runtime_caches()
    try:
        bpy.msgbus.clear_by_owner(_FBP_SCENE_MSGBUS_OWNER)
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        from .render_output import fbp_clear_render_output_cache
        fbp_clear_render_output_cache()
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass

    known_timers = {
        _scene_sync.fbp_initial_sync_timer,
        _scene_sync.cleanup_orphan_fbp_planes_timer,
        fbp_deferred_scene_sync,
        fbp_deferred_camera_projection_sync,
        fbp_deferred_post_undo_sync,
        fbp_undo_guard_watchdog,
        fbp_render_guard_watchdog,
        *fbp_managed_timer_callbacks(),
    }
    for _timer in known_timers:
        try:
            if bpy.app.timers.is_registered(_timer):
                bpy.app.timers.unregister(_timer)
        except FBP_DATA_IO_ERRORS:
            pass
    fbp_clear_managed_timers()

    for handler_list in (
        bpy.app.handlers.frame_change_pre,
        bpy.app.handlers.frame_change_post,
    ):
        remove_handlers_by_name(
            handler_list, "fbp_frame_change_handler", module_suffix="core"
        )
        remove_handlers_by_name(
            handler_list,
            "fbp_shape_mask_frame_change_post",
            module_suffix="object_masks",
        )

    owned_depsgraph_handlers = (
        ("fbp_depsgraph_native_ops_handler", "scene_sync"),
        ("effect_controls_depsgraph_update", "effect_controls"),
        ("fbp_gp_depsgraph_update", "grease_pencil_bridge"),
        ("_depsgraph_auto_timing_sync", "grease_pencil_workflow"),
        ("_fbp_motion_depsgraph_update", "motion_runtime"),
        ("fbp_compositor_sets_depsgraph_post", "compositor_sets"),
    )
    for name, module_suffix in owned_depsgraph_handlers:
        remove_handlers_by_name(
            bpy.app.handlers.depsgraph_update_post,
            name,
            module_suffix=module_suffix,
        )

    for handler_list in (
        bpy.app.handlers.render_init,
        bpy.app.handlers.render_pre,
        bpy.app.handlers.render_post,
        bpy.app.handlers.render_cancel,
        bpy.app.handlers.render_complete,
    ):
        remove_handlers_by_name(
            handler_list,
            "fbp_render_guard_pre",
            "fbp_render_guard_complete",
            module_suffix="core",
        )
        remove_handlers_by_name(
            handler_list,
            "fbp_shape_mask_render_pre",
            module_suffix="object_masks",
        )

    history_handlers = [
        (bpy.app.handlers.undo_pre, "fbp_undo_pre_handler"),
        (bpy.app.handlers.undo_post, "fbp_undo_post_handler"),
        (bpy.app.handlers.load_pre, "fbp_load_pre_handler"),
        (bpy.app.handlers.load_post, "fbp_load_post_handler"),
    ]
    redo_pre = getattr(bpy.app.handlers, "redo_pre", None)
    redo_post = getattr(bpy.app.handlers, "redo_post", None)
    if redo_pre is not None:
        history_handlers.append((redo_pre, "fbp_redo_pre_handler"))
    if redo_post is not None:
        history_handlers.append((redo_post, "fbp_redo_post_handler"))
    for handler_list, name in history_handlers:
        remove_handlers_by_name(handler_list, name, module_suffix="handlers")
    # Collection ID-properties are cosmetic caches. Skip their deletion when a
    # render is active or its state could not be queried; unregistering handlers
    # is safe, mutating render-owned datablocks is not.
    if can_mutate_ids and fbp_main_data_ready("collections"):
        collections = fbp_main_data_collection("collections", ()) or ()
        for coll in tuple(collections):
            for key in ("fbp_has_fbp_content", "fbp_has_fbp_content_recursive"):
                try:
                    if key in coll:
                        del coll[key]
                except FBP_DATA_IO_ERRORS:
                    pass
