"""Handlers that keep rig wires in step with the scene.

* Follow Frame Alpha Outline rigs follow the current drawing. Outlines are
  rebuilt only while the timeline is still (scrubbing or stepping); during
  playback they wait and catch up once when playback stops.
* Legacy Perfect Shape wires stay a square, circle or regular polygon when
  the layer is stretched, by hand or by animation: a wire is rebuilt only
  when its rig's X/Y scale ratio changes.
"""

import bpy
from bpy.app.handlers import persistent

from .registration import append_handler_once, remove_handlers_by_name
from .runtime import fbp_render_mutation_blocked, fbp_undo_guard_active, fbp_warn


def _perfect_candidates(objects):
    """FBP rigs among ``objects`` and their descendants."""
    found = {}
    for obj in objects:
        try:
            for item in (obj, *getattr(obj, "children_recursive", ())):
                if bool(getattr(item, "is_fbp_control", False)):
                    found[item.as_pointer()] = item
        except (AttributeError, ReferenceError, RuntimeError):
            continue
    return tuple(found.values())


@persistent
def fbp_rig_perfect_depsgraph_update(scene, depsgraph=None, *args):
    del args
    if depsgraph is None or fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return
    try:
        moved = []
        for update in depsgraph.updates:
            if not update.is_updated_transform:
                continue
            original = getattr(update.id, "original", None)
            if isinstance(original, bpy.types.Object):
                moved.append(original)
        if not moved:
            return
        from .builder import fbp_refresh_perfect_rigs
        fbp_refresh_perfect_rigs(_perfect_candidates(moved))
    except Exception as exc:
        fbp_warn("Perfect Shape rig update skipped", exc)


@persistent
def fbp_rig_alpha_frame_change(scene, *args):
    del args
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return
    try:
        # Animated scale: keep Perfect Shape wires regular on every frame.
        from .builder import fbp_refresh_perfect_rigs
        fbp_refresh_perfect_rigs(getattr(scene, "objects", ()))
    except Exception as exc:
        fbp_warn("Perfect Shape frame update skipped", exc)
    try:
        from .scene_sync import fbp_animation_playback_active
        if fbp_animation_playback_active():
            return
        from .builder import fbp_refresh_alpha_follow_rigs
        fbp_refresh_alpha_follow_rigs(scene)
    except Exception as exc:
        fbp_warn("Alpha Outline frame update skipped", exc)


@persistent
def fbp_rig_alpha_playback_post(scene, *args):
    del args
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return
    try:
        from .builder import fbp_refresh_alpha_follow_rigs
        fbp_refresh_alpha_follow_rigs(scene)
    except Exception as exc:
        fbp_warn("Alpha Outline update after playback skipped", exc)


def register():
    if not append_handler_once(
        bpy.app.handlers.frame_change_post,
        fbp_rig_alpha_frame_change,
        module_suffix="rig_alpha_follow",
    ):
        raise RuntimeError("Could not register the Alpha Outline frame handler")
    if not append_handler_once(
        bpy.app.handlers.animation_playback_post,
        fbp_rig_alpha_playback_post,
        module_suffix="rig_alpha_follow",
    ):
        raise RuntimeError("Could not register the Alpha Outline playback handler")
    if not append_handler_once(
        bpy.app.handlers.depsgraph_update_post,
        fbp_rig_perfect_depsgraph_update,
        module_suffix="rig_alpha_follow",
    ):
        raise RuntimeError("Could not register the Perfect Shape rig handler")


def unregister():
    remove_handlers_by_name(
        bpy.app.handlers.frame_change_post,
        "fbp_rig_alpha_frame_change",
        module_suffix="rig_alpha_follow",
    )
    remove_handlers_by_name(
        bpy.app.handlers.animation_playback_post,
        "fbp_rig_alpha_playback_post",
        module_suffix="rig_alpha_follow",
    )
    remove_handlers_by_name(
        bpy.app.handlers.depsgraph_update_post,
        "fbp_rig_perfect_depsgraph_update",
        module_suffix="rig_alpha_follow",
    )
