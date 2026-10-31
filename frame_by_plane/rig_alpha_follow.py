"""Frame handler that keeps Follow Frame Alpha Outline rigs on the current drawing."""

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
        from .builder import fbp_refresh_alpha_follow_rigs
        fbp_refresh_alpha_follow_rigs(scene)
    except Exception as exc:
        fbp_warn("Alpha Outline frame update skipped", exc)


def register():
    if not append_handler_once(
        bpy.app.handlers.frame_change_post,
        fbp_rig_alpha_frame_change,
        module_suffix="rig_alpha_follow",
    ):
        raise RuntimeError("Could not register the Alpha Outline frame handler")


def unregister():
    remove_handlers_by_name(
        bpy.app.handlers.frame_change_post,
        "fbp_rig_alpha_frame_change",
        module_suffix="rig_alpha_follow",
    )
