"""Blender handlers, timers and render-state guards for Frame by Plane."""

import time

import bpy

from . import core as _core
from . import scene_sync as _scene_sync
from . import layers as _layers
from . import effects_registry as _effects_registry
from .runtime import (
    fbp_runtime_get,
    fbp_runtime_set,
    fbp_undo_guard_active,
    fbp_warn,
    fbp_warn_once,
    FBP_RENDER_IDLE,
    FBP_RENDER_BUSY,
    FBP_RENDER_UNKNOWN,
    fbp_render_state,
)


# SECTION 00A - Undo / reload safety #
_FBP_UNDO_FAILSAFE_SECONDS = 30.0
_FBP_LOAD_FAILSAFE_SECONDS = 120.0
_FBP_REGISTERED_TIMERS = globals().get("_FBP_REGISTERED_TIMERS", {})


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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

def fbp_cancel_safe_tasks():
    """Cancel add-on timer closures before Blender replaces Main or unloads FBP."""
    try:
        from . import safe_tasks as _fbp_safe_tasks
    except ImportError:
        _fbp_safe_tasks = None
    if _fbp_safe_tasks:
        try:
            _fbp_safe_tasks.clear_scheduled()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    try:
        from . import materials as _fbp_materials
        _fbp_materials.fbp_prepare_for_main_replacement()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        _scene_sync.fbp_reset_deferred_sync_state()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        from . import native_backend as _fbp_native_backend
        _fbp_native_backend.fbp_clear_native_runtime_cache()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def fbp_remove_handlers_by_name(handler_list, *names):
    """Remove previously registered handlers by function name.

    Name matching also removes stale function objects after an in-place module
    reload, preventing duplicate background listeners in the current session.
    """
    if not handler_list or not names:
        return
    names = set(names)
    for _h in list(handler_list):
        if getattr(_h, "__name__", "") in names:
            try:
                handler_list.remove(_h)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .drawing_plane import clear_drawing_runtime_cache
        clear_drawing_runtime_cache()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def fbp_stop_playback_for_safe_operation():
    try:
        screen = getattr(bpy.context, 'screen', None)
        if screen and getattr(screen, 'is_animation_playing', False):
            bpy.ops.screen.animation_cancel(restore_frame=False)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


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
            from .properties import fbp_apply_preferences_to_scene
            try:
                fbp_apply_preferences_to_scene(context.scene, force=False, context=context)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            # Undo can restore/remove registered custom node groups. Refresh
            # their lightweight registry once here instead of scanning all node
            # groups from every effect-stack query during playback or render.
            try:
                _effects_registry.fbp_refresh_custom_effect_registry(force=True)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            # sync_layer_collection() also refreshes UI rows and snapshots
            # rig/plane links; do not repeat those O(scene size) passes here.
            _scene_sync.sync_layer_collection(context)
            try:
                from .native_backend import fbp_repair_native_sequence_timing_scene
                fbp_repair_native_sequence_timing_scene(context.scene)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
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
            try:
                from .drawing_plane import fbp_refresh_drawing_scene
                fbp_refresh_drawing_scene(context.scene)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
    except Exception as exc:
        try:
            fbp_warn("Could not sync Frame by Plane after undo", exc)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    return None


def fbp_deferred_scene_sync():
    """Refresh lightweight layer/UI state after the active Scene changes."""
    if fbp_undo_is_active() or fbp_render_is_active():
        return 0.25
    try:
        context = bpy.context
        if context and getattr(context, "scene", None):
            from .properties import fbp_apply_preferences_to_scene
            try:
                fbp_apply_preferences_to_scene(
                    context.scene, force=False, context=context
                )
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not refresh camera-aware effects", exc)
    return None




def fbp_render_guard_watchdog():
    """Clear/restore render state only after Blender's render job is idle.

    Completion callbacks merely request teardown. This timer owns the actual
    release so no queued FBP task can mutate IDs while Blender is finalizing a
    native animation frame, result buffer or dependency graph.
    """
    if not bool(fbp_runtime_get("fbp_render_guard_active", False)):
        return 2.0

    try:
        started_at = float(fbp_runtime_get("fbp_render_started_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        started_at = 0.0
    elapsed = time.monotonic() - started_at if started_at > 0.0 else 0.0
    expected_end = bool(fbp_runtime_get("fbp_render_end_requested", False))
    try:
        end_requested_at = float(
            fbp_runtime_get("fbp_render_end_requested_at", 0.0) or 0.0
        )
    except (TypeError, ValueError):
        end_requested_at = 0.0

    # Before a completion callback, allow Blender time to register the job. This
    # prevents one early false sample immediately after render_init from being
    # mistaken for an interrupted render.
    if not expected_end and (started_at <= 0.0 or elapsed < 5.0):
        return 0.5

    render_state = fbp_render_state(include_guard=False)
    if render_state == FBP_RENDER_BUSY:
        return 0.10 if expected_end else 0.5

    if render_state == FBP_RENDER_UNKNOWN:
        # UNKNOWN is never equivalent to IDLE. Even a native pass-through guard
        # must remain active because releasing it would allow deferred tasks to
        # mutate Blender IDs while render finalization may still be running.
        if expected_end and end_requested_at > 0.0:
            if time.monotonic() - end_requested_at >= 10.0:
                fbp_warn_once(
                    "render_state_unknown_cleanup_wait",
                    "Render cleanup is waiting because Blender's render state cannot be confirmed",
                )
            return 0.5
        return 2.0

    if not expected_end and elapsed < 60.0:
        return 2.0

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
                # Blender is positively IDLE here. A value that still raises
                # after repeated idle retries is no longer transient; release
                # the runtime lock rather than freezing every FBP update for the
                # remainder of the session. The affected stale datablock may need
                # a manual refresh, but no render-owned memory is being touched.
                fbp_warn_once(
                    "render_guard_restore_abandoned",
                    "Render cleanup released its guard after repeated idle restore failures",
                )
                _core.fbp_render_guard_abandon()
                return 2.0
            return min(2.0, 0.25 * max(1, failures))
        if not expected_end:
            fbp_warn_once(
                "render_guard_watchdog_restore",
                "Recovered an interrupted Frame by Plane render guard",
            )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not recover interrupted render guard", exc)
        return 0.5
    return 2.0


def fbp_camera_projection_notify():
    """Message-bus callback for active camera and projection-property changes."""
    if fbp_undo_is_active() or fbp_render_is_active():
        return
    fbp_register_timer_once(fbp_deferred_camera_projection_sync, 0.03)


def fbp_scene_change_notify():
    """Message-bus callback: run as soon as the active Window.scene changes."""
    if fbp_undo_is_active() or fbp_render_is_active():
        return
    fbp_register_timer_once(fbp_deferred_scene_sync, 0.12)
    fbp_register_timer_once(fbp_deferred_camera_projection_sync, 0.03)

def fbp_undo_guard_watchdog():
    """Release a stale guard from Blender's idle timer context."""
    if not fbp_undo_is_active():
        return 2.0
    try:
        deadline = float(fbp_runtime_get("fbp_undo_guard_deadline", 0.0) or 0.0)
        if deadline <= 0.0:
            return 0.5
        remaining = deadline - time.monotonic()
        if remaining > 0.0:
            return min(0.5, max(0.1, remaining))

        # The timer runs only after Blender returns to its event loop. Releasing
        # here is safer than allowing arbitrary RNA/depsgraph callbacks to expire
        # the guard while Main may still be under reconstruction.
        fbp_set_undo_guard(False)
        fbp_warn_once(
            "undo_guard_watchdog_failsafe",
            "Undo/load guard exceeded its safety deadline and was released automatically",
        )
        fbp_register_timer_once(fbp_deferred_post_undo_sync, 0.05)
    except Exception as exc:
        # A watchdog failure must never leave the add-on permanently locked. This
        # callback itself runs from a safe timer, so a forced release is valid.
        fbp_set_undo_guard(False)
        fbp_warn("Undo/load guard watchdog failed and forced a release", exc)
        try:
            fbp_register_timer_once(fbp_deferred_post_undo_sync, 0.05)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return 2.0


@bpy.app.handlers.persistent
def fbp_undo_pre_handler(scene):
    # Ctrl+Z can free/replace scenes and ID properties while FBP
    # background handlers are still listening. Enter a strict guard first.
    fbp_set_undo_guard(True, timeout=_FBP_UNDO_FAILSAFE_SECONDS)
    fbp_register_timer_once(fbp_undo_guard_watchdog, 0.5, persistent=True)
    fbp_stop_playback_for_safe_operation()
    fbp_clear_effect_runtime_caches()
    try:
        from . import native_backend as _fbp_native_backend
        _fbp_native_backend.fbp_clear_native_runtime_cache()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    # Do not clear Scene CollectionProperties from undo_pre. The deferred
    # post-undo sync rebuilds those visual caches from Blender's idle loop.


def fbp_deferred_release_undo_guard():
    """Release only after the most recent undo_post grace period has elapsed.

    Blender can emit a second undo before the release timer created by the first
    one runs. Reusing one timer is intentional, but it must honor the newest
    deadline instead of unlocking the add-on while the second undo is decoding.
    """
    if not fbp_undo_is_active():
        fbp_runtime_set("fbp_undo_release_not_before", 0.0)
        return None
    release_at = float(
        fbp_runtime_get("fbp_undo_release_not_before", 0.0) or 0.0
    )
    remaining = release_at - time.monotonic()
    if remaining > 0.0:
        return min(0.35, max(0.05, remaining))
    fbp_set_undo_guard(False)
    fbp_register_timer_once(fbp_deferred_post_undo_sync, 0.25)
    return None


@bpy.app.handlers.persistent
def fbp_undo_post_handler(scene):
    # Do not sync immediately inside undo_post. Schedule a deferred release of the
    # guard, then rebuild UI caches after Blender has completed undo decode.
    now = time.monotonic()
    fbp_runtime_set("fbp_undo_release_not_before", now + 0.35)
    if not fbp_register_timer_once(fbp_deferred_release_undo_guard, 0.35):
        # False normally means the deduplicated timer is already registered. If
        # Blender rejected registration, fail closed: the persistent watchdog
        # releases the guard from an idle timer instead of unlocking inside the
        # undo_post callback itself. Tighten its deadline so recovery is prompt.
        try:
            timer_registered = bpy.app.timers.is_registered(
                fbp_deferred_release_undo_guard
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            timer_registered = False
        if not timer_registered:
            fbp_runtime_set("fbp_undo_guard_deadline", now + 5.0)
            fbp_warn_once(
                "undo_release_timer_unavailable",
                "Undo release timer was unavailable; the persistent watchdog will recover it",
            )


# Textured playback remains visible. The frame-change handler is used only by
# procedural Color / Gradient / Holdout rows.

# SECTION 00C - Scene switch / missing image GPU safety #
_FBP_SCENE_MSGBUS_OWNER = globals().get("_FBP_SCENE_MSGBUS_OWNER", object())


def fbp_register_timer_once(callback, first_interval, *, persistent=False, restart=False):
    """Register one current timer callback and retire stale reload generations."""
    callback_name = str(getattr(callback, "__name__", "") or id(callback))
    callback_module = str(getattr(callback, "__module__", "") or "")
    key = f"{callback_module}.{callback_name}"
    try:
        previous = _FBP_REGISTERED_TIMERS.get(key)
        if previous is not None and previous is not callback:
            try:
                if bpy.app.timers.is_registered(previous):
                    bpy.app.timers.unregister(previous)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        if bpy.app.timers.is_registered(callback):
            if not restart:
                _FBP_REGISTERED_TIMERS[key] = callback
                return False
            try:
                bpy.app.timers.unregister(callback)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                _FBP_REGISTERED_TIMERS[key] = callback
                return False
        bpy.app.timers.register(
            callback,
            first_interval=max(0.0, float(first_interval)),
            persistent=bool(persistent),
        )
        _FBP_REGISTERED_TIMERS[key] = callback
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        _FBP_REGISTERED_TIMERS.pop(key, None)
        try:
            fbp_warn(f"Could not register timer {getattr(callback, '__name__', callback)}", exc)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return False


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
        for property_name in (
            "type", "lens", "sensor_width", "ortho_scale", "shift_x", "shift_y"
        ):
            bpy.msgbus.subscribe_rna(
                key=(bpy.types.Camera, property_name),
                owner=_FBP_SCENE_MSGBUS_OWNER,
                args=(),
                notify=fbp_camera_projection_notify,
            )
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        try:
            fbp_warn("Could not subscribe to scene-switch safety message bus", exc)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return False


@bpy.app.handlers.persistent
def fbp_load_pre_handler(_dummy):
    """Retire Python runtime state without mutating the Main being destroyed."""
    fbp_set_undo_guard(True, timeout=_FBP_LOAD_FAILSAFE_SECONDS)
    fbp_cancel_safe_tasks()
    try:
        _core.fbp_render_guard_abandon()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    # Preview collections own native image/icon caches outside bpy.data.images.
    # Free them before Blender starts tearing down the old Main.
    try:
        _layers.clear_previews()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        _layers.fbp_reset_layer_view_cache_state()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    fbp_clear_effect_runtime_caches()

    # Do not call operators, alter Scene data or register timers from load_pre.
    # load_post releases the guard. If a load is aborted, the runtime deadline is
    # released by the existing idle safety paths after Blender returns to the UI.


@bpy.app.handlers.persistent
def fbp_load_post_handler(_dummy):
    fbp_set_undo_guard(False)
    # Existing .blend scenes keep their stored project settings. Mark them as
    # initialized before the deferred scene-sync timer runs; only Scenes created
    # after load receive the Add-on Preferences defaults automatically.
    try:
        from .properties import fbp_mark_scenes_preferences_initialized
        fbp_mark_scenes_preferences_initialized()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    # A newly loaded file can contain a different set of registered custom
    # node groups. Refresh once on load rather than from per-frame stack reads.
    try:
        _effects_registry.fbp_refresh_custom_effect_registry(force=True)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn_once(
            "custom_effect_registry_load_refresh",
            "Could not refresh custom effects after loading the file",
            exc,
        )

    # Blender clears non-persistent timers and all message-bus subscriptions
    # when another .blend is loaded. Rebuild the runtime services here.
    fbp_subscribe_scene_msgbus()
    fbp_register_timer_once(fbp_deferred_scene_sync, 0.12)
    fbp_register_timer_once(_scene_sync.cleanup_orphan_fbp_planes_timer, 4.0)
    fbp_register_timer_once(fbp_render_guard_watchdog, 2.0, persistent=True)
    fbp_register_timer_once(fbp_undo_guard_watchdog, 2.0, persistent=True)


# SECTION 01 - Register handlers / timers #
def register():
    # Retire runtime data left by an in-place extension reload before any handler
    # can observe pointers from the previous module generation.
    fbp_clear_effect_runtime_caches()
    if bpy.context:
        fbp_register_timer_once(_scene_sync.fbp_initial_sync_timer, 0.12)
        fbp_register_timer_once(fbp_deferred_scene_sync, 0.18)
        fbp_register_timer_once(_scene_sync.cleanup_orphan_fbp_planes_timer, 8.0)
        fbp_register_timer_once(fbp_render_guard_watchdog, 2.0, persistent=True)
        fbp_register_timer_once(fbp_undo_guard_watchdog, 2.0, persistent=True)

    # Immediate scene-switch safety. This fires earlier than the fallback timer.
    fbp_subscribe_scene_msgbus()

    # Native ImageUser playback needs no Python frame-change material swapping.
    # The frame handler is kept only for animated procedural Color / Gradient / Holdout rows.
    for _handlers in (bpy.app.handlers.frame_change_pre, bpy.app.handlers.frame_change_post):
        fbp_remove_handlers_by_name(_handlers, "fbp_frame_change_handler")
    bpy.app.handlers.frame_change_post.append(_core.fbp_frame_change_handler)

    fbp_remove_handlers_by_name(bpy.app.handlers.depsgraph_update_post, "fbp_depsgraph_native_ops_handler")
    bpy.app.handlers.depsgraph_update_post.append(_scene_sync.fbp_depsgraph_native_ops_handler)

    # Render state is session-scoped. Enter only from render_init: render_pre and
    # render_post are per-frame callbacks and must stay completely outside the
    # native image-sequence render path. Restore after complete/cancel only.
    render_handler_names = {
        "fbp_render_guard_pre", "fbp_render_guard_complete",
    }
    for _handlers in (
        bpy.app.handlers.render_init, bpy.app.handlers.render_pre,
        bpy.app.handlers.render_post, bpy.app.handlers.render_cancel,
        bpy.app.handlers.render_complete,
    ):
        fbp_remove_handlers_by_name(_handlers, *render_handler_names)
    bpy.app.handlers.render_init.append(_core.fbp_render_guard_pre)
    bpy.app.handlers.render_cancel.append(_core.fbp_render_guard_complete)
    bpy.app.handlers.render_complete.append(_core.fbp_render_guard_complete)


    fbp_remove_handlers_by_name(bpy.app.handlers.undo_pre, "fbp_undo_pre_handler")
    fbp_remove_handlers_by_name(bpy.app.handlers.undo_post, "fbp_undo_post_handler")
    bpy.app.handlers.undo_pre.append(fbp_undo_pre_handler)
    bpy.app.handlers.undo_post.append(fbp_undo_post_handler)

    for _handlers, _handler in ((bpy.app.handlers.load_pre, fbp_load_pre_handler), (bpy.app.handlers.load_post, fbp_load_post_handler)):
        fbp_remove_handlers_by_name(_handlers, getattr(_handler, "__name__", ""))
        _handlers.append(_handler)


# SECTION 02 - Unregister handlers / timers #
def unregister():
    fbp_set_undo_guard(False)
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    known_timers = {
        _scene_sync.fbp_initial_sync_timer,
        _scene_sync.cleanup_orphan_fbp_planes_timer,
        fbp_deferred_scene_sync,
        fbp_deferred_camera_projection_sync,
        fbp_deferred_release_undo_guard,
        fbp_deferred_post_undo_sync,
        fbp_undo_guard_watchdog,
        fbp_render_guard_watchdog,
        *_FBP_REGISTERED_TIMERS.values(),
    }
    for _timer in known_timers:
        try:
            if bpy.app.timers.is_registered(_timer):
                bpy.app.timers.unregister(_timer)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    _FBP_REGISTERED_TIMERS.clear()

    for _handlers in (bpy.app.handlers.frame_change_pre, bpy.app.handlers.frame_change_post):
        fbp_remove_handlers_by_name(_handlers, "fbp_frame_change_handler")

    fbp_remove_handlers_by_name(bpy.app.handlers.depsgraph_update_post, "fbp_depsgraph_native_ops_handler")

    for _handlers in (
        bpy.app.handlers.render_init, bpy.app.handlers.render_pre,
        bpy.app.handlers.render_post, bpy.app.handlers.render_cancel,
        bpy.app.handlers.render_complete,
    ):
        for _h in list(_handlers):
            if getattr(_h, "__name__", "") in {
                "fbp_render_guard_pre", "fbp_render_guard_complete",
            }:
                try:
                    _handlers.remove(_h)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass


    for _handlers, _name in ((bpy.app.handlers.undo_pre, "fbp_undo_pre_handler"), (bpy.app.handlers.undo_post, "fbp_undo_post_handler"), (bpy.app.handlers.load_pre, "fbp_load_pre_handler"), (bpy.app.handlers.load_post, "fbp_load_post_handler")):
        for _h in list(_handlers):
            if getattr(_h, "__name__", "") == _name:
                try:
                    _handlers.remove(_h)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
    # Collection ID-properties are cosmetic caches. Skip their deletion when a
    # render is active or its state could not be queried; unregistering handlers
    # is safe, mutating render-owned datablocks is not.
    if can_mutate_ids:
        for coll in bpy.data.collections:
            for key in ("fbp_has_fbp_content", "fbp_has_fbp_content_recursive"):
                try:
                    if key in coll:
                        del coll[key]
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
