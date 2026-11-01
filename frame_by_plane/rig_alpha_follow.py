"""Frame handler that keeps Follow Frame Alpha Outline rigs on the current drawing.

Outlines are rebuilt only while the timeline is still (scrubbing or stepping);
during playback they wait and catch up once when playback stops.
"""

import bpy
from bpy.app.handlers import persistent

from .registration import append_handler_once, remove_handlers_by_name
from .runtime import fbp_render_mutation_blocked, fbp_undo_guard_active, fbp_warn


@persistent
def fbp_rig_alpha_frame_change(scene, *args):
    del args
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return
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
