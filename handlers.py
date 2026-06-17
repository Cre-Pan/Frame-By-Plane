"""Blender handlers, timers and render-state guards for Frame by Plane."""

import time

import bpy

from . import core as _core
from . import scene_sync as _scene_sync
from . import layers as _layers
from .runtime import (
    fbp_runtime_get,
    fbp_runtime_set,
    fbp_undo_guard_active,
    fbp_warn,
    fbp_warn_once,
)


# SECTION 00A - Undo / reload safety #
_FBP_UNDO_FAILSAFE_SECONDS = 30.0
_FBP_LOAD_FAILSAFE_SECONDS = 120.0
_FBP_REGISTERED_TIMERS = globals().get("_FBP_REGISTERED_TIMERS", {})


def fbp_undo_is_active():
    """Return the canonical runtime guard without releasing it from callbacks."""
    return fbp_undo_guard_active()

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
        _scene_sync.fbp_reset_deferred_sync_state()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
    """Invalidate effect caches that may hold RNA references across Main changes."""
    try:
        from . import geometry_nodes as _geometry_nodes
        _geometry_nodes.fbp_clear_effect_runtime_caches()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def fbp_clear_transient_ui_caches(scene=None):
    """Clear UI-only CollectionProperties before undo/load heavy operations.

    These lists are only visual caches for UIList trees. They can be rebuilt from
    real scene objects/pending planes, so keeping them out of the undo payload
    reduces IDProperty pressure and avoids stale virtual rows after Ctrl+Z.
    """
    scene = scene or getattr(bpy.context, 'scene', None)
    if not scene:
        return
    # Do not clear Scene.fbp_layers here. Layer rows do not store
    # Object PointerProperties, but mutating the main layer collection during
    # undo/load is still unnecessary and can touch Blender ID data while Main is
    # being replaced. Only clear visual tree caches.
    for attr, idx_attr in (("fbp_layer_tree_rows", "fbp_layer_tree_rows_idx"), ("fbp_pending_tree_rows", "fbp_pending_tree_rows_idx")):
        try:
            rows = getattr(scene, attr, None)
            if rows is not None:
                rows.clear()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        try:
            if hasattr(scene, idx_attr):
                setattr(scene, idx_attr, 0)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
    if fbp_undo_is_active():
        return 0.25
    try:
        context = bpy.context
        if context and getattr(context, "scene", None):
            from .properties import fbp_apply_preferences_to_scene
            try:
                fbp_apply_preferences_to_scene(context.scene, force=False, context=context)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            # sync_layer_collection() also refreshes UI rows and snapshots
            # rig/plane links; do not repeat those O(scene size) passes here.
            _scene_sync.sync_layer_collection(context)
    except Exception as exc:
        try:
            fbp_warn("Could not sync Frame by Plane after undo", exc)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    return None


def fbp_deferred_scene_sync():
    """Refresh lightweight layer/UI state after the active Scene changes."""
    if fbp_undo_is_active():
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
    except Exception as exc:
        try:
            fbp_warn("Could not sync Frame by Plane after scene switch", exc)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return None




def fbp_scene_change_notify():
    """Message-bus callback: run as soon as the active Window.scene changes."""
    if fbp_undo_is_active():
        return
    fbp_register_timer_once(fbp_deferred_scene_sync, 0.12)

def fbp_undo_guard_watchdog():
    """Release a stale guard from Blender's idle timer context."""
    if not fbp_undo_is_active():
        return None
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
    return None


@bpy.app.handlers.persistent
def fbp_undo_pre_handler(scene):
    # Ctrl+Z can free/replace scenes and ID properties while FBP
    # background handlers are still listening. Enter a strict guard first.
    fbp_set_undo_guard(True, timeout=_FBP_UNDO_FAILSAFE_SECONDS)
    fbp_register_timer_once(fbp_undo_guard_watchdog, 0.5, persistent=True)
    fbp_stop_playback_for_safe_operation()
    fbp_clear_effect_runtime_caches()
    try:
        fbp_clear_transient_ui_caches(scene)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


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
    fbp_runtime_set("fbp_undo_release_not_before", time.monotonic() + 0.35)
    if not fbp_register_timer_once(fbp_deferred_release_undo_guard, 0.35):
        # A currently registered release timer is valid and will read the newest
        # deadline above. Only force a release if no timer exists at all.
        try:
            if not bpy.app.timers.is_registered(fbp_deferred_release_undo_guard):
                fbp_set_undo_guard(False)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            fbp_set_undo_guard(False)


# Textured playback remains visible. The frame-change handler is used only by
# procedural Color / Gradient / Holdout rows.

# SECTION 00C - Scene switch / missing image GPU safety #
_FBP_SCENE_MSGBUS_OWNER = globals().get("_FBP_SCENE_MSGBUS_OWNER", object())


def fbp_register_timer_once(callback, first_interval, *, persistent=False):
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
    """Restore the active-scene subscription, which Blender clears on file load."""
    try:
        bpy.msgbus.clear_by_owner(_FBP_SCENE_MSGBUS_OWNER)
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.Window, "scene"),
            owner=_FBP_SCENE_MSGBUS_OWNER,
            args=(),
            notify=fbp_scene_change_notify,
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
    # Keep one persistent watchdog across file replacement. ``load_post`` normally
    # releases immediately; the long deadline only covers failed/interrupted loads.
    fbp_set_undo_guard(True, timeout=_FBP_LOAD_FAILSAFE_SECONDS)
    fbp_cancel_safe_tasks()
    fbp_register_timer_once(fbp_undo_guard_watchdog, 0.5, persistent=True)
    fbp_stop_playback_for_safe_operation()
    fbp_clear_effect_runtime_caches()
    fbp_clear_transient_ui_caches(getattr(bpy.context, 'scene', None))


@bpy.app.handlers.persistent
def fbp_load_post_handler(_dummy):
    fbp_set_undo_guard(False)
    # Existing .blend scenes keep their stored project settings. Mark them as
    # initialized before the deferred scene-sync timer runs; only Scenes created
    # after load receive the Add-on Preferences defaults automatically.
    from .properties import fbp_mark_scenes_preferences_initialized
    try:
        fbp_mark_scenes_preferences_initialized()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    # Blender clears non-persistent timers and all message-bus subscriptions
    # when another .blend is loaded. Rebuild the runtime services here.
    fbp_subscribe_scene_msgbus()
    fbp_register_timer_once(fbp_deferred_scene_sync, 0.12)
    fbp_register_timer_once(_scene_sync.cleanup_orphan_fbp_planes_timer, 4.0)


# SECTION 01 - Register handlers / timers #
def register():
    if bpy.context:
        fbp_register_timer_once(_scene_sync.fbp_initial_sync_timer, 0.12)
        fbp_register_timer_once(_scene_sync.cleanup_orphan_fbp_planes_timer, 8.0)

    # Immediate scene-switch safety. This fires earlier than the fallback timer.
    fbp_subscribe_scene_msgbus()

    # Native ImageUser playback needs no Python frame-change material swapping.
    # The frame handler is kept only for animated procedural Color / Gradient / Holdout rows.
    for _handlers in (bpy.app.handlers.frame_change_pre, bpy.app.handlers.frame_change_post):
        fbp_remove_handlers_by_name(_handlers, "fbp_frame_change_handler")
    bpy.app.handlers.frame_change_post.append(_core.fbp_frame_change_handler)

    fbp_remove_handlers_by_name(bpy.app.handlers.depsgraph_update_post, "fbp_depsgraph_native_ops_handler")
    bpy.app.handlers.depsgraph_update_post.append(_scene_sync.fbp_depsgraph_native_ops_handler)

    # Remove stale function objects left by module reloads before appending the
    # current callbacks. Identity checks alone do not catch previous generations.
    fbp_remove_handlers_by_name(bpy.app.handlers.render_pre, "fbp_render_guard_pre")
    for _handlers in (bpy.app.handlers.render_post, bpy.app.handlers.render_cancel, bpy.app.handlers.render_complete):
        fbp_remove_handlers_by_name(_handlers, "fbp_render_guard_post")
    bpy.app.handlers.render_pre.append(_core.fbp_render_guard_pre)
    bpy.app.handlers.render_post.append(_core.fbp_render_guard_post)
    bpy.app.handlers.render_cancel.append(_core.fbp_render_guard_post)
    bpy.app.handlers.render_complete.append(_core.fbp_render_guard_post)


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
    # If Blender missed render_post/cancel or the extension is disabled during a
    # render, restore viewport visibility before runtime backups are cleared.
    try:
        _core.fbp_render_guard_post(getattr(bpy.context, "scene", None))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not restore render visibility during unregister", exc)
    try:
        _layers.clear_previews()
    except Exception as exc:
        fbp_warn("Could not clear Frame by Plane previews", exc)
    fbp_cancel_safe_tasks()
    try:
        bpy.msgbus.clear_by_owner(_FBP_SCENE_MSGBUS_OWNER)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    known_timers = {
        _scene_sync.fbp_initial_sync_timer,
        _scene_sync.cleanup_orphan_fbp_planes_timer,
        fbp_deferred_scene_sync,
        fbp_deferred_release_undo_guard,
        fbp_deferred_post_undo_sync,
        fbp_undo_guard_watchdog,
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

    for _handlers in (bpy.app.handlers.render_pre, bpy.app.handlers.render_post, bpy.app.handlers.render_cancel, bpy.app.handlers.render_complete):
        for _h in list(_handlers):
            if getattr(_h, "__name__", "") in {"fbp_render_guard_pre", "fbp_render_guard_post"}:
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
    for coll in bpy.data.collections:
        for key in ("fbp_has_fbp_content", "fbp_has_fbp_content_recursive"):
            try:
                if key in coll:
                    del coll[key]
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
