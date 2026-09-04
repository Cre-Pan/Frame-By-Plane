"""Blender 5.2 backport of the Timeline synchronization UX from PR 162412.

Blender 5.2 already exposes ``Space*.show_locked_time`` and the original
Workspace Scene Time switch.  The 5.3 change adds a compact control in every
time editor, separates Scene Time from Follow Scene Strips and lets artists
choose which jump buttons occupy the playback header.  This module supplies
those missing RNA/UI pieces on 5.2 and leaves Blender's native implementation
untouched as soon as all upstream properties are available.

The 5.2 C API cannot expose the new Scene Strip relation helpers to Python.
For the common affine Scene Strip case, a guarded frame-change handler mirrors
the upstream bidirectional mapping without retaining RNA objects between
callbacks.  Retimed/strobed strips continue to use Blender's native 5.2 path
when Follow Scene Strips is enabled.
"""

from __future__ import annotations

import math

import bpy
from bpy.app.handlers import persistent
from bpy.app.translations import contexts as i18n_contexts
from bpy.props import BoolProperty
from bpy.types import Panel

from .registration import register_classes, unregister_classes
from .runtime import FBP_DATA_ERRORS, fbp_warn


_UPSTREAM_WORKSPACE_PROPERTIES = (
    "use_scene_time_sync_follow_scene",
    "show_jump_to_endpoints",
    "show_jump_to_keyframes",
    "show_jump_by_delta",
)
_FBP_SYNC_PROPERTY = "fbp_use_scene_time_sync"
_REGISTERED_WORKSPACE_PROPERTIES = []
_PATCHED_PLAYBACK_MODULES = {}
_REGISTERED_HEADER_CALLBACKS = []
_SYNC_GUARD = set()


def _native_upstream_timeline_available():
    """Distinguish compiled upstream RNA from this module's runtime properties."""
    try:
        for name in _UPSTREAM_WORKSPACE_PROPERTIES:
            prop = bpy.types.WorkSpace.bl_rna.properties.get(name)
            if prop is None or bool(getattr(prop, "is_runtime", False)):
                return False
        return True
    except FBP_DATA_ERRORS:
        return False


def _workspace_sync_enabled(workspace):
    if workspace is None:
        return False
    if hasattr(workspace, _FBP_SYNC_PROPERTY):
        try:
            return bool(getattr(workspace, _FBP_SYNC_PROPERTY))
        except FBP_DATA_ERRORS:
            return False
    try:
        return bool(getattr(workspace, "use_scene_time_sync", False))
    except FBP_DATA_ERRORS:
        return False


def _workspace_follow_enabled(workspace):
    try:
        return bool(getattr(workspace, "use_scene_time_sync_follow_scene", False))
    except FBP_DATA_ERRORS:
        return False


def _apply_workspace_sync_mode(workspace):
    """Keep Blender 5.2's legacy scene-follow switch behind the new split UI."""
    if workspace is None or _native_upstream_timeline_available():
        return
    try:
        enabled = _workspace_sync_enabled(workspace)
        follow = _workspace_follow_enabled(workspace)
        # In 5.2 the native switch always changes the active scene.  Keep it
        # off for time-only synchronization and let the guarded Python mapping
        # below update the two playheads without stealing window.scene.
        workspace.use_scene_time_sync = bool(enabled and follow)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not update the Blender 5.2 Scene Time backport", exc)


def _workspace_sync_update(workspace, _context):
    _apply_workspace_sync_mode(workspace)


def _register_workspace_property(name, definition):
    if hasattr(bpy.types.WorkSpace, name):
        return False
    setattr(bpy.types.WorkSpace, name, definition)
    _REGISTERED_WORKSPACE_PROPERTIES.append(name)
    return True


def _register_workspace_properties():
    if _native_upstream_timeline_available():
        return
    _register_workspace_property(
        _FBP_SYNC_PROPERTY,
        BoolProperty(
            name="Scene Time",
            description=(
                "Synchronize playhead time between the Workspace Sequencer scene "
                "and the active scene without requiring the window to follow Scene Strips"
            ),
            default=True,
            update=_workspace_sync_update,
        ),
    )
    _register_workspace_property(
        "use_scene_time_sync_follow_scene",
        BoolProperty(
            name="Follow Scene Strips",
            description="Switch the active window scene to the Scene Strip under the Sequencer playhead",
            default=False,
            update=_workspace_sync_update,
        ),
    )
    _register_workspace_property(
        "show_jump_to_endpoints",
        BoolProperty(
            name="Show Jump to Start/End",
            description="Show the jump-to-start and jump-to-end playback controls",
            default=True,
        ),
    )
    _register_workspace_property(
        "show_jump_to_keyframes",
        BoolProperty(
            name="Show Jump to Prev/Next Keyframe",
            description="Show the previous-keyframe and next-keyframe playback controls",
            default=True,
        ),
    )
    _register_workspace_property(
        "show_jump_by_delta",
        BoolProperty(
            name="Show Jump Time by Delta",
            description="Show the backward and forward time-delta playback controls",
            default=False,
        ),
    )

    # Match the upstream default: time synchronization is enabled, but scene
    # following is an explicit opt-in.  Assigning the legacy 5.2 property here
    # also prevents a factory workspace from changing scenes behind the user.
    for workspace in tuple(getattr(bpy.data, "workspaces", ()) or ()):
        _apply_workspace_sync_mode(workspace)


def _unregister_workspace_properties():
    for name in reversed(_REGISTERED_WORKSPACE_PROPERTIES):
        try:
            if hasattr(bpy.types.WorkSpace, name):
                delattr(bpy.types.WorkSpace, name)
        except FBP_DATA_ERRORS:
            pass
    _REGISTERED_WORKSPACE_PROPERTIES.clear()


def playback_controls(layout, context):
    """Blender 5.2 playback header with the upstream compact jump controls."""
    st = context.space_data
    is_sequencer = st.type == "SEQUENCE_EDITOR"
    is_timeline = st.type == "DOPESHEET_EDITOR" and st.mode == "TIMELINE"
    scene = context.scene if not is_sequencer else context.sequencer_scene
    tool_settings = scene.tool_settings if scene else None
    screen = context.screen
    workspace = context.workspace

    if not scene:
        return

    layout.popover(panel="TIME_PT_playback", text="Playback")

    if tool_settings and not is_timeline:
        icon_keytype = "KEYTYPE_{:s}_VEC".format(tool_settings.keyframe_type)
        layout.popover(
            panel="TIME_PT_keyframing_settings",
            text_ctxt=i18n_contexts.id_windowmanager,
            icon=icon_keytype,
        )

    if is_sequencer:
        sync_prop = _FBP_SYNC_PROPERTY if hasattr(workspace, _FBP_SYNC_PROPERTY) else "use_scene_time_sync"
        layout.prop(workspace, sync_prop, text="", icon="UV_SYNC_SELECT", toggle=True)

    layout.separator_spacer()

    if tool_settings:
        row = layout.row(align=True)
        row.prop(tool_settings, "use_keyframe_insert_auto", text="", toggle=True)
        sub = row.row(align=True)
        sub.active = tool_settings.use_keyframe_insert_auto
        sub.popover(panel="TIME_PT_auto_keyframing", text="")

    row = layout.row(align=True)
    if bool(getattr(workspace, "show_jump_to_endpoints", True)):
        row.operator("screen.frame_jump", text="", icon="REW").end = False
    if bool(getattr(workspace, "show_jump_by_delta", False)):
        row.operator("screen.time_jump", text="", icon="FRAME_PREV").backward = True
    if bool(getattr(workspace, "show_jump_to_keyframes", True)):
        row.operator("screen.keyframe_jump", text="", icon="PREV_KEYFRAME").next = False

    if not screen.is_animation_playing:
        if scene.sync_mode == "AUDIO_SYNC" and context.preferences.system.audio_device == "JACK":
            row.scale_x = 2
            row.operator("screen.animation_play", text="", icon="PLAY")
            row.scale_x = 1
        else:
            row.operator("screen.animation_play", text="", icon="PLAY_REVERSE").reverse = True
            row.operator("screen.animation_play", text="", icon="PLAY")
    else:
        row.scale_x = 2
        row.operator("screen.animation_pause", text="", icon="PAUSE")
        row.scale_x = 1

    if bool(getattr(workspace, "show_jump_to_keyframes", True)):
        row.operator("screen.keyframe_jump", text="", icon="NEXT_KEYFRAME").next = True
    if bool(getattr(workspace, "show_jump_by_delta", False)):
        row.operator("screen.time_jump", text="", icon="FRAME_NEXT").backward = False
    if bool(getattr(workspace, "show_jump_to_endpoints", True)):
        row.operator("screen.frame_jump", text="", icon="FF").end = True
    row.popover(panel="FBP_PT_time_jump", text="")

    if tool_settings:
        row = layout.row(align=True)
        row.prop(tool_settings, "use_snap_playhead", text="")
        row.popover(panel="TIME_PT_playhead_snapping", text="")

    layout.separator_spacer()
    if scene.show_subframe:
        row = layout.row()
        row.scale_x = 1.15
        row.prop(scene, "frame_float", text="")
    else:
        row = layout.row()
        row.scale_x = 0.95
        row.prop(scene, "frame_current", text="")

    row = layout.row(align=True)
    row.prop(scene, "use_preview_range", text="", toggle=True)
    sub = row.row(align=True)
    sub.scale_x = 0.8
    if scene.use_preview_range:
        sub.prop(scene, "frame_preview_start", text="Start")
        sub.prop(scene, "frame_preview_end", text="End")
    else:
        sub.prop(scene, "frame_start", text="Start")
        sub.prop(scene, "frame_end", text="End")


class FBP_PT_TimeJump(Panel):
    bl_idname = "FBP_PT_time_jump"
    bl_label = "Time Jump"
    bl_space_type = "DOPESHEET_EDITOR"
    bl_region_type = "HEADER"
    bl_options = {"HIDE_HEADER"}
    bl_ui_units_x = 12

    def draw(self, context):
        layout = self.layout
        layout.use_property_decorate = False
        workspace = context.workspace

        visibility = layout.column(align=True)
        visibility.use_property_split = False
        visibility.alignment = "LEFT"
        visibility.prop(workspace, "show_jump_to_endpoints", text="Jump to Start/End")
        visibility.prop(workspace, "show_jump_to_keyframes", text="Jump to Prev/Next Keyframe")
        layout.separator()
        delta = layout.column(align=True)
        delta.use_property_split = False
        delta.alignment = "LEFT"
        delta.prop(workspace, "show_jump_by_delta", text="Jump by Delta")

        st = context.space_data
        is_sequencer = st.type == "SEQUENCE_EDITOR"
        scene = context.scene if not is_sequencer else context.sequencer_scene
        settings = layout.column()
        settings.active = bool(getattr(workspace, "show_jump_by_delta", False))
        settings.use_property_split = True
        settings.prop(scene, "time_jump_unit", expand=True, text="Jump Unit")
        settings.prop(scene, "time_jump_delta", text="Delta")


class _FBPTimeSyncPanelBase:
    bl_region_type = "HEADER"
    bl_label = "Synchronization"
    bl_ui_units_x = 12

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        st = context.space_data
        layout.prop(st, "show_locked_time", text="Sync Visible Range")

        if st.type == "SEQUENCE_EDITOR":
            layout.separator()
            workspace = context.workspace
            sync_prop = _FBP_SYNC_PROPERTY if hasattr(workspace, _FBP_SYNC_PROPERTY) else "use_scene_time_sync"
            col = layout.column(heading="Scene Strips")
            col.active = bool(st.show_locked_time)
            col.prop(workspace, sync_prop, text="Scene Time")
            sub = col.column()
            sub.active = bool(st.show_locked_time and _workspace_sync_enabled(workspace))
            sub.prop(workspace, "use_scene_time_sync_follow_scene", text="Follow Scene Strips")


class FBP_PT_DopesheetTimeSync(_FBPTimeSyncPanelBase, Panel):
    bl_idname = "FBP_PT_dopesheet_time_sync"
    bl_space_type = "DOPESHEET_EDITOR"


class FBP_PT_GraphTimeSync(_FBPTimeSyncPanelBase, Panel):
    bl_idname = "FBP_PT_graph_time_sync"
    bl_space_type = "GRAPH_EDITOR"


class FBP_PT_NLATimeSync(_FBPTimeSyncPanelBase, Panel):
    bl_idname = "FBP_PT_nla_time_sync"
    bl_space_type = "NLA_EDITOR"


class FBP_PT_SequencerTimeSync(_FBPTimeSyncPanelBase, Panel):
    bl_idname = "FBP_PT_sequencer_time_sync"
    bl_space_type = "SEQUENCE_EDITOR"


classes = (
    FBP_PT_TimeJump,
    FBP_PT_DopesheetTimeSync,
    FBP_PT_GraphTimeSync,
    FBP_PT_NLATimeSync,
    FBP_PT_SequencerTimeSync,
)


def _draw_time_sync_control(layout, context, panel):
    st = context.space_data
    if not hasattr(st, "show_locked_time"):
        return
    row = layout.row(align=True)
    linked = bool(getattr(st, "show_locked_time", False))
    row.prop(st, "show_locked_time", text="", icon="LINKED" if linked else "UNLINKED", toggle=True)
    row.popover(panel=panel, text="")


def _draw_dopesheet_time_sync(self, context):
    _draw_time_sync_control(self.layout, context, FBP_PT_DopesheetTimeSync.bl_idname)


def _draw_graph_time_sync(self, context):
    _draw_time_sync_control(self.layout, context, FBP_PT_GraphTimeSync.bl_idname)


def _draw_nla_time_sync(self, context):
    _draw_time_sync_control(self.layout, context, FBP_PT_NLATimeSync.bl_idname)


def _draw_sequencer_time_sync(self, context):
    if str(getattr(context.space_data, "view_type", "SEQUENCER") or "SEQUENCER") in {"SEQUENCER", "SEQUENCER_PREVIEW"}:
        _draw_time_sync_control(self.layout, context, FBP_PT_SequencerTimeSync.bl_idname)


_HEADER_CALLBACK_SPECS = (
    ("DOPESHEET_HT_header", _draw_dopesheet_time_sync),
    ("GRAPH_HT_header", _draw_graph_time_sync),
    ("NLA_HT_header", _draw_nla_time_sync),
    ("SEQUENCER_HT_header", _draw_sequencer_time_sync),
)


def _register_header_callbacks():
    for type_name, callback in _HEADER_CALLBACK_SPECS:
        header = getattr(bpy.types, type_name, None)
        if header is None:
            continue
        try:
            header.remove(callback)
        except (ValueError, RuntimeError):
            pass
        header.append(callback)
        _REGISTERED_HEADER_CALLBACKS.append((type_name, callback))


def _unregister_header_callbacks():
    for type_name, callback in reversed(_REGISTERED_HEADER_CALLBACKS):
        header = getattr(bpy.types, type_name, None)
        if header is None:
            continue
        try:
            header.remove(callback)
        except (ValueError, RuntimeError):
            pass
    _REGISTERED_HEADER_CALLBACKS.clear()


def _patch_playback_controls():
    from bl_ui import space_dopesheet, space_graph, space_nla, space_sequencer, space_time

    for module in (space_time, space_dopesheet, space_graph, space_nla, space_sequencer):
        current = getattr(module, "playback_controls", None)
        if not callable(current) or current is playback_controls:
            continue
        _PATCHED_PLAYBACK_MODULES[module.__name__] = (module, current)
        module.playback_controls = playback_controls


def _restore_playback_controls():
    for _name, (module, original) in tuple(_PATCHED_PLAYBACK_MODULES.items()):
        if getattr(module, "playback_controls", None) is playback_controls:
            module.playback_controls = original
    _PATCHED_PLAYBACK_MODULES.clear()


def _scene_frame(scene):
    try:
        return float(scene.frame_current) + float(scene.frame_subframe)
    except FBP_DATA_ERRORS:
        return float(getattr(scene, "frame_current", 0.0) or 0.0)


def _set_scene_frame(scene, frame):
    try:
        if bool(getattr(scene, "show_subframe", False)):
            base = math.floor(float(frame))
            scene.frame_set(int(base), subframe=float(frame) - float(base))
        else:
            scene.frame_set(int(round(float(frame))))
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not synchronize a Scene Strip frame", exc)
        return False


def _scene_strips(sequencer_scene):
    try:
        editor = getattr(sequencer_scene, "sequence_editor", None)
        if editor is None:
            return ()
        return tuple(
            strip for strip in tuple(getattr(editor, "strips", ()) or ())
            if str(getattr(strip, "type", "") or "") == "SCENE"
            and getattr(strip, "scene", None) is not None
            and not bool(getattr(strip, "mute", False))
        )
    except FBP_DATA_ERRORS:
        return ()


def _strip_visible_at(strip, frame):
    try:
        return float(strip.frame_final_start) <= float(frame) < float(strip.frame_final_end)
    except FBP_DATA_ERRORS:
        return False


def _top_scene_strip_at(sequencer_scene, frame):
    candidates = [strip for strip in _scene_strips(sequencer_scene) if _strip_visible_at(strip, frame)]
    return max(candidates, key=lambda strip: int(getattr(strip, "channel", 0) or 0), default=None)


def _relation_strip(sequencer_scene, source_scene):
    strips = [strip for strip in _scene_strips(sequencer_scene) if getattr(strip, "scene", None) == source_scene]
    if not strips:
        return None
    editor = getattr(sequencer_scene, "sequence_editor", None)
    active = getattr(editor, "active_strip", None) if editor is not None else None
    if active in strips:
        return active
    playhead = _scene_frame(sequencer_scene)
    visible = [strip for strip in strips if _strip_visible_at(strip, playhead)]
    if visible:
        return max(visible, key=lambda strip: int(getattr(strip, "channel", 0) or 0))

    def sort_key(strip):
        left = float(getattr(strip, "frame_final_start", 0.0) or 0.0)
        right = float(getattr(strip, "frame_final_end", left + 1.0) or left + 1.0)
        distance = left - playhead if playhead < left else playhead - (right - 1.0)
        return (distance, -int(getattr(strip, "channel", 0) or 0), left)

    return min(strips, key=sort_key)


def _strip_has_affine_mapping(strip):
    try:
        return float(getattr(strip, "strobe", 0.0) or 0.0) <= 1.0 and len(getattr(strip, "retiming_keys", ())) == 0
    except FBP_DATA_ERRORS:
        return False


def _strip_playback_rate(sequencer_scene, strip):
    # Scene Strips in Blender 5.2 do not expose SEQ_AUTO_PLAYBACK_RATE.  Their
    # default affine mapping is 1:1, which is also the upstream fallback.
    del sequencer_scene, strip
    return 1.0


def _timeline_to_scene_frame(sequencer_scene, strip, timeline_frame):
    if strip is None or not _strip_has_affine_mapping(strip):
        return None
    try:
        rate = _strip_playback_rate(sequencer_scene, strip)
        if not rate:
            return None
        if bool(getattr(strip, "use_reverse_frames", False)):
            strip_frame = float(strip.content_end) - 1.0 - float(timeline_frame)
        else:
            strip_frame = float(timeline_frame) - float(strip.content_start)
        return (
            strip_frame * rate
            + float(strip.scene.frame_start)
            + float(getattr(strip, "animation_offset_start", 0.0) or 0.0)
        )
    except FBP_DATA_ERRORS:
        return None


def _scene_to_timeline_frame(sequencer_scene, strip, scene_frame):
    if strip is None or not _strip_has_affine_mapping(strip):
        return None
    try:
        rate = _strip_playback_rate(sequencer_scene, strip)
        if not rate:
            return None
        frame_index = (
            float(scene_frame)
            - float(strip.scene.frame_start)
            - float(getattr(strip, "animation_offset_start", 0.0) or 0.0)
        )
        strip_frame = frame_index / rate
        if bool(getattr(strip, "use_reverse_frames", False)):
            return float(strip.content_end) - 1.0 - strip_frame
        return float(strip.content_start) + strip_frame
    except FBP_DATA_ERRORS:
        return None


def _sync_window_scene_time(window, changed_scene):
    workspace = getattr(window, "workspace", None)
    if workspace is None or not _workspace_sync_enabled(workspace):
        return
    sequencer_scene = getattr(workspace, "sequencer_scene", None)
    active_scene = getattr(window, "scene", None)
    if sequencer_scene is None or active_scene is None or sequencer_scene == active_scene:
        return

    window_key = int(window.as_pointer())
    if window_key in _SYNC_GUARD:
        return
    _SYNC_GUARD.add(window_key)
    try:
        if changed_scene == sequencer_scene:
            strip = _top_scene_strip_at(sequencer_scene, _scene_frame(sequencer_scene))
            if strip is None or getattr(strip, "scene", None) != active_scene:
                return
            target = _timeline_to_scene_frame(sequencer_scene, strip, _scene_frame(sequencer_scene))
            if target is not None and abs(_scene_frame(active_scene) - target) > 1.0e-6:
                _set_scene_frame(active_scene, target)
        elif changed_scene == active_scene:
            strip = _relation_strip(sequencer_scene, active_scene)
            target = _scene_to_timeline_frame(sequencer_scene, strip, _scene_frame(active_scene))
            if target is None or not _strip_visible_at(strip, target):
                return
            if abs(_scene_frame(sequencer_scene) - target) > 1.0e-6:
                _set_scene_frame(sequencer_scene, target)
    finally:
        _SYNC_GUARD.discard(window_key)


@persistent
def fbp_timeline_scene_time_sync(scene, _depsgraph=None):
    if _native_upstream_timeline_available():
        return
    try:
        windows = tuple(getattr(getattr(bpy.context, "window_manager", None), "windows", ()) or ())
    except FBP_DATA_ERRORS:
        windows = ()
    for window in windows:
        try:
            _sync_window_scene_time(window, scene)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not evaluate the Blender 5.2 Scene Time backport", exc)


def _register_handler():
    handlers = bpy.app.handlers.frame_change_post
    for callback in tuple(handlers):
        if getattr(callback, "__name__", "") == fbp_timeline_scene_time_sync.__name__:
            handlers.remove(callback)
    handlers.append(fbp_timeline_scene_time_sync)


def _unregister_handler():
    handlers = bpy.app.handlers.frame_change_post
    for callback in tuple(handlers):
        if getattr(callback, "__name__", "") == fbp_timeline_scene_time_sync.__name__:
            handlers.remove(callback)
    _SYNC_GUARD.clear()


def register():
    if _native_upstream_timeline_available():
        return
    _register_workspace_properties()
    register_classes(classes)
    _patch_playback_controls()
    _register_header_callbacks()
    _register_handler()


def unregister():
    _unregister_handler()
    _unregister_header_callbacks()
    _restore_playback_controls()
    if not _native_upstream_timeline_available():
        unregister_classes(classes)
    _unregister_workspace_properties()


__all__ = (
    "fbp_timeline_scene_time_sync",
    "playback_controls",
)
