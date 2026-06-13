"""Blender handlers, timers and render-state guards for Frame by Plane."""

import bpy
import time

try:
    from .migrations import deferred_legacy_wiggle_cleanup as fbp_deferred_legacy_wiggle_cleanup
except ImportError:
    from migrations import deferred_legacy_wiggle_cleanup as fbp_deferred_legacy_wiggle_cleanup

try:
    from . import core as _core
    from . import scene_sync as _scene_sync
except ImportError:
    import core as _core
    import scene_sync as _scene_sync


# SECTION 00A - GPU texture release safety #
_FBP_LAST_GPU_TEXTURE_RELEASE = 0.0
_FBP_UNDO_IN_PROGRESS = False


def fbp_undo_is_active():
    """Runtime guard used by handlers/timers during Blender undo decode.

    Ctrl+Z replaces/freezes large parts of Main and the depsgraph. Any FBP timer
    or depsgraph/frame handler that reads Scene/Object ID properties during that
    window can touch datablocks Blender is freeing. Keep all background listeners
    silent until undo_post schedules a deferred sync.
    """
    try:
        return bool(_FBP_UNDO_IN_PROGRESS) or bool(_core.fbp_runtime_get("fbp_undo_in_progress", False))
    except Exception:
        return bool(_FBP_UNDO_IN_PROGRESS)


def fbp_set_undo_guard(active=True):
    global _FBP_UNDO_IN_PROGRESS
    _FBP_UNDO_IN_PROGRESS = bool(active)
    try:
        _core.fbp_runtime_set("fbp_undo_in_progress", bool(active))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def fbp_cancel_safe_tasks():
    """Cancel add-on timer closures before Blender replaces Main or unloads FBP."""
    try:
        from . import safe_tasks as _fbp_safe_tasks
    except ImportError:
        try:
            import safe_tasks as _fbp_safe_tasks
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

    This is intentionally name-based so it can clean handlers left behind by
    older add-on versions after reload/reinstall. It keeps register/unregister
    code smaller and prevents duplicate background listeners.
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


def fbp_release_fbp_gpu_textures(scene=None, force=False):
    """Release cached GPU textures used by FBP image materials.

    This does not remove images, materials or files. It only asks Blender to drop
    the GPU texture cache so scene switches/undo/heavy imports do not try to keep
    hundreds of image textures resident while redrawing the viewport.
    """
    global _FBP_LAST_GPU_TEXTURE_RELEASE
    now = time.monotonic()
    if not force and (now - _FBP_LAST_GPU_TEXTURE_RELEASE) < 0.85:
        return 0
    _FBP_LAST_GPU_TEXTURE_RELEASE = now
    scene = scene or getattr(bpy.context, 'scene', None)
    if not scene:
        return 0
    released = 0
    seen_images = set()
    try:
        for obj in list(getattr(scene, 'objects', [])):
            if not (getattr(obj, 'is_fbp_plane', False) or getattr(obj, 'is_fbp_control', False)):
                continue
            plane = getattr(obj, 'fbp_plane_target', None) if getattr(obj, 'is_fbp_control', False) else obj
            if not plane or not getattr(plane, 'data', None):
                continue
            for mat in getattr(plane.data, 'materials', []):
                if not mat or not getattr(mat, 'use_nodes', False) or not getattr(mat, 'node_tree', None):
                    continue
                for node in mat.node_tree.nodes:
                    if getattr(node, 'type', None) != 'TEX_IMAGE':
                        continue
                    img = getattr(node, 'image', None)
                    if not img:
                        continue
                    ptr = img.as_pointer()
                    if ptr in seen_images:
                        continue
                    seen_images.add(ptr)
                    try:
                        img.gl_free()
                        released += 1
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                        pass
    except Exception as exc:
        try:
            _core.fbp_warn('Could not release FBP GPU textures', exc)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    return released


# SECTION 00B - Undo / GPU viewport safety #
def fbp_capture_viewport_state():
    """Return an empty viewport snapshot.

    Blender 5.1 can crash when a timer stores old SpaceView3D RNA references and
    later writes to `space.shading.*` after screens/areas have changed. Frame by
    Plane no longer forces temporary Wireframe/Solid viewport modes here; this
    intentionally avoids storing UI RNA pointers across timers.
    """
    return []


def fbp_restore_viewport_state(saved=None):
    """No-op viewport restore kept for current import/load call sites."""
    return None


def fbp_set_viewports_wireframe_temporarily(restore_after=1.25, release=False):
    """No-op safe viewport guard.

    Earlier builds temporarily changed all View3D areas to Wireframe and restored
    them from a timer. That can crash Blender 5.1 if the saved `space` RNA
    pointer becomes stale. Heavy operations now avoid touching viewport shading
    from background timers. Optional GPU texture release is kept, but only when
    explicitly requested.
    """
    if release:
        try:
            fbp_release_fbp_gpu_textures(getattr(bpy.context, 'scene', None), force=False)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    return None


def fbp_make_viewports_undo_safe(restore_after=1.25, release=False):
    """Compatibility wrapper kept for callers; intentionally no-op."""
    return fbp_set_viewports_wireframe_temporarily(restore_after=restore_after, release=release)

def fbp_deferred_post_undo_sync():
    # Let Blender finish replacing Main/depsgraph before touching FBP data.
    if fbp_undo_is_active():
        return 0.25
    try:
        context = bpy.context
        if context and getattr(context, "scene", None):
            _scene_sync.sync_layer_collection(context)
            _scene_sync.fbp_snapshot_layer_plane_links(context)
    except Exception as exc:
        try:
            _core.fbp_warn("Could not sync Frame by Plane after undo", exc)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    return None


def fbp_deferred_scene_sync():
    """Rebuild Frame by Plane layer data after Blender switches the active scene.

    Scene switching can leave the Layers UIList looking at stale virtual rows or
    an empty tree until the next explicit operator runs. This deferred sync reads
    the new active scene, repopulates Scene.fbp_layers from FBP rigs, refreshes
    collection caches and rebuilds the virtual Layer UIList rows.
    """
    if fbp_undo_is_active():
        return 0.25
    try:
        context = bpy.context
        if context and getattr(context, "scene", None):
            _scene_sync.sync_layer_collection(context)
            try:
                from .ui_layout import fbp_refresh_layer_tree_rows
            except ImportError:
                try:
                    from ui_layout import fbp_refresh_layer_tree_rows
                except ImportError:
                    fbp_refresh_layer_tree_rows = None
            if fbp_refresh_layer_tree_rows:
                try:
                    fbp_refresh_layer_tree_rows(context)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
    except Exception as exc:
        try:
            _core.fbp_warn("Could not sync Frame by Plane after scene switch", exc)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    return None


def fbp_scene_change_notify():
    """Message-bus callback: run as soon as the active Window.scene changes."""
    if fbp_undo_is_active():
        return
    fbp_make_viewports_undo_safe(restore_after=1.25, release=False)
    fbp_register_timer_once(fbp_deferred_scene_sync, 0.12)

@bpy.app.handlers.persistent
def fbp_undo_pre_handler(scene):
    # Ctrl+Z can free/replace scenes and ID properties while FBP
    # background handlers are still listening. Enter a strict guard first.
    fbp_set_undo_guard(True)
    fbp_stop_playback_for_safe_operation()
    try:
        fbp_clear_transient_ui_caches(scene)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    fbp_make_viewports_undo_safe(restore_after=None, release=False)


def fbp_deferred_release_undo_guard():
    """Release the undo guard once, then schedule one post-undo resync."""
    fbp_set_undo_guard(False)
    fbp_register_timer_once(fbp_deferred_post_undo_sync, 0.25)
    return None


@bpy.app.handlers.persistent
def fbp_undo_post_handler(scene):
    # Do not sync immediately inside undo_post. Schedule a deferred release of the
    # guard, then rebuild UI caches after Blender has completed undo decode.
    fbp_make_viewports_undo_safe(restore_after=1.25, release=False)
    if not fbp_register_timer_once(fbp_deferred_release_undo_guard, 0.35):
        # If scheduling fails entirely, never leave the add-on stuck in undo mode.
        try:
            if not bpy.app.timers.is_registered(fbp_deferred_release_undo_guard):
                fbp_set_undo_guard(False)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            fbp_set_undo_guard(False)


# Playback viewport safety is disabled so textured animation stays visible.
# The frame-change handler stays active so animated planes remain visible during playback.
# Register/unregister still remove old playback handlers by name to clean stale versions.

# SECTION 00C - Scene switch / missing image GPU safety #
_FBP_SCENE_MSGBUS_OWNER = globals().get("_FBP_SCENE_MSGBUS_OWNER", object())


def fbp_register_timer_once(callback, first_interval):
    """Register a timer only when the current callback is not already active."""
    try:
        if not bpy.app.timers.is_registered(callback):
            bpy.app.timers.register(callback, first_interval=first_interval)
            return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        try:
            _core.fbp_warn(f"Could not register timer {getattr(callback, '__name__', callback)}", exc)
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
            _core.fbp_warn("Could not subscribe to scene-switch safety message bus", exc)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return False


@bpy.app.handlers.persistent
def fbp_load_pre_handler(_dummy):
    fbp_set_undo_guard(True)
    fbp_cancel_safe_tasks()
    fbp_stop_playback_for_safe_operation()
    fbp_clear_transient_ui_caches(getattr(bpy.context, 'scene', None))
    fbp_make_viewports_undo_safe(restore_after=None, release=False)


@bpy.app.handlers.persistent
def fbp_load_post_handler(_dummy):
    fbp_set_undo_guard(False)
    fbp_make_viewports_undo_safe(restore_after=1.25, release=False)

    # Blender clears non-persistent timers and all message-bus subscriptions
    # when another .blend is loaded. Rebuild the runtime services here.
    fbp_subscribe_scene_msgbus()
    fbp_register_timer_once(fbp_deferred_scene_sync, 0.12)
    fbp_register_timer_once(_scene_sync.cleanup_orphan_fbp_planes_timer, 2.0)
    fbp_register_timer_once(fbp_deferred_legacy_wiggle_cleanup, 0.25)


# SECTION 01 - Register handlers / timers #
def register():
    if bpy.context:
        fbp_register_timer_once(_scene_sync.fbp_initial_sync_timer, 0.12)
        fbp_register_timer_once(_scene_sync.cleanup_orphan_fbp_planes_timer, 8.0)
        fbp_register_timer_once(fbp_deferred_legacy_wiggle_cleanup, 0.25)

    # Immediate scene-switch safety. This fires earlier than the fallback timer.
    fbp_subscribe_scene_msgbus()

    # Native ImageUser playback needs no Python frame-change material swapping.
    # The frame handler is kept only for animated procedural Color / Gradient / Holdout rows.
    for _handlers in (bpy.app.handlers.frame_change_pre, bpy.app.handlers.frame_change_post):
        fbp_remove_handlers_by_name(_handlers, "fbp_frame_change_handler")
    bpy.app.handlers.frame_change_post.append(_core.fbp_frame_change_handler)

    # Do not force Wireframe during playback; animated textured planes must stay visible.
    fbp_remove_handlers_by_name(bpy.app.handlers.animation_playback_pre, "fbp_playback_pre_handler")
    fbp_remove_handlers_by_name(bpy.app.handlers.animation_playback_post, "fbp_playback_post_handler")

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
    _core.clear_previews()
    try:
        fbp_restore_viewport_state()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    fbp_cancel_safe_tasks()
    try:
        bpy.msgbus.clear_by_owner(_FBP_SCENE_MSGBUS_OWNER)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    for _timer in (
        _scene_sync.fbp_initial_sync_timer,
        _scene_sync.cleanup_orphan_fbp_planes_timer,
        fbp_deferred_scene_sync,
        fbp_deferred_release_undo_guard,
        fbp_deferred_post_undo_sync,
        fbp_deferred_legacy_wiggle_cleanup,
    ):
        try:
            if bpy.app.timers.is_registered(_timer):
                bpy.app.timers.unregister(_timer)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

    for _handlers in (bpy.app.handlers.frame_change_pre, bpy.app.handlers.frame_change_post):
        fbp_remove_handlers_by_name(_handlers, "fbp_frame_change_handler")

    # Also clean stale playback handlers from older versions.
    fbp_remove_handlers_by_name(bpy.app.handlers.animation_playback_pre, "fbp_playback_pre_handler")
    fbp_remove_handlers_by_name(bpy.app.handlers.animation_playback_post, "fbp_playback_post_handler")

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
    wm = getattr(bpy.context, "window_manager", None)
    if wm:
        for key in (
            "fbp_render_guard_active",
            "fbp_layer_cache_dirty",
            "fbp_fast_import_depth",
            "fbp_fast_import_queued_rigs",
            "fbp_fast_import_undo_state",
            "fbp_undo_in_progress",
        ):
            try:
                if key in wm:
                    del wm[key]
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass

    for coll in bpy.data.collections:
        for key in ("fbp_has_fbp_content", "fbp_has_fbp_content_recursive"):
            try:
                if key in coll:
                    del coll[key]
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
