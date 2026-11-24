"""Link Timelines: keep every time editor lined up frame by frame.

A toggle at the right of the header of every Timeline, Dope Sheet, Graph
Editor, NLA and Sequencer links their visible ranges. Blender's own "Sync
Visible Range" copies the same start/end frame to every editor, so two
timelines stacked one above the other drift apart as soon as one of them has a
wider channel list or an open sidebar: the same frame no longer sits at the
same screen position.

This link aligns them in screen space instead. The editor you scroll, zoom or
resize leads; every other linked editor in the same window gets the same
pixels per frame and puts each frame at the same horizontal position on the
screen, so the playhead, the scene start/end and the preview range line up
vertically across editors whatever their channel list or sidebar width.
Editors that sit side by side (no common horizontal span) or in another window
get the leader's visible range, like the native option.

The toggle is on by default. While it is on, the native "Sync Visible Range"
is switched off on those editors so the two do not fight each other.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty

from .managed_timers import fbp_register_timer_once, fbp_unregister_managed_timer
from .registration import append_handler_once, remove_handlers_by_name
from .runtime import FBP_DATA_ERRORS, fbp_warn_once


LINK_PROPERTY = "fbp_link_timelines"
_TIME_SPACE_TYPES = frozenset({"DOPESHEET_EDITOR", "GRAPH_EDITOR", "NLA_EDITOR", "SEQUENCE_EDITOR"})
_TICK_ACTIVE = 1.0 / 30.0
_TICK_IDLE = 0.5
_PIXEL_TOLERANCE = 0.5
_SCALE_TOLERANCE = 1.0e-4
_MAX_PASSES = 3

# Region key -> (window x of the region, region width, pixels per frame,
# window x of frame 0). Plain numbers only: no RNA survives between ticks.
_STATES = {}
_LEADER = [None]
_LEADER_HINT = [None]
_HEADER_CALLBACKS = []
_SCENE_SYNC_SEEN = set()


def link_enabled(window_manager=None):
    wm = window_manager
    if wm is None:
        wm = getattr(bpy.context, "window_manager", None)
    return bool(getattr(wm, LINK_PROPERTY, True)) if wm is not None else False


def _space_is_time_editor(space):
    space_type = getattr(space, "type", "")
    if space_type not in _TIME_SPACE_TYPES:
        return False
    if space_type == "GRAPH_EDITOR" and getattr(space, "mode", "") == "DRIVERS":
        return False
    if space_type == "SEQUENCE_EDITOR" and getattr(space, "view_type", "SEQUENCER") == "PREVIEW":
        return False
    return True


def _region_key(window, area, region):
    return (int(window.as_pointer()), int(area.as_pointer()), int(region.as_pointer()))


def _time_regions():
    """Yield (key, window, area, region) for every visible time editor."""
    wm = getattr(bpy.context, "window_manager", None)
    for window in tuple(getattr(wm, "windows", ()) or ()):
        screen = getattr(window, "screen", None)
        for area in tuple(getattr(screen, "areas", ()) or ()):
            if area.type not in _TIME_SPACE_TYPES or not _space_is_time_editor(area.spaces.active):
                continue
            for region in area.regions:
                if region.type == "WINDOW" and region.width > 1 and region.height > 1:
                    yield _region_key(window, area, region), window, area, region
                    break


def _measure(region):
    """Return (region x, width, pixels per frame, window x of frame 0)."""
    view = region.view2d
    left = float(view.region_to_view(0.0, 0.0)[0])
    right = float(view.region_to_view(float(region.width), 0.0)[0])
    span = right - left
    if span <= 1.0e-9:
        return None
    scale = float(region.width) / span
    return (float(region.x), float(region.width), scale, float(region.x) - left * scale)


def _state_changed(old, new):
    if old is None or new is None:
        return old is not new
    if abs(old[0] - new[0]) > _PIXEL_TOLERANCE or abs(old[1] - new[1]) > _PIXEL_TOLERANCE:
        return True
    if abs(old[2] - new[2]) > _SCALE_TOLERANCE * max(abs(old[2]), 1.0e-9):
        return True
    return abs(old[3] - new[3]) > _PIXEL_TOLERANCE


def _target_range(leader_window, leader_region, leader_state, window, region):
    """Return the (first, last) frame the follower region should show."""
    scale, origin = leader_state[2], leader_state[3]
    same_window = leader_window == window
    overlap = (
        min(leader_region.x + leader_region.width, region.x + region.width)
        - max(leader_region.x, region.x)
    )
    if same_window and overlap > 0:
        # Same pixels per frame and every frame at the same screen x.
        first = (float(region.x) - origin) / scale
        last = (float(region.x + region.width) - origin) / scale
    else:
        first = (float(leader_region.x) - origin) / scale
        last = (float(leader_region.x + leader_region.width) - origin) / scale
    return first, last


def _frame_to_pixels(region, frames):
    """Map frames to float region pixels (View2D.view_to_region rounds)."""
    view = region.view2d
    left = float(view.region_to_view(0.0, 0.0)[0])
    right = float(view.region_to_view(float(region.width), 0.0)[0])
    span = right - left
    if span <= 1.0e-9:
        return None
    scale = float(region.width) / span
    return tuple((float(frame) - left) * scale for frame in frames)


def _range_matches(region, first, last):
    pixels = _frame_to_pixels(region, (first, last))
    if pixels is None:
        return True
    return (
        abs(pixels[0]) <= _PIXEL_TOLERANCE
        and abs(pixels[1] - float(region.width)) <= _PIXEL_TOLERANCE
    )


def _apply_range(window, area, region, first, last):
    """Show frames first..last in region, keeping its vertical view.

    ``view2d.zoom_border`` takes whole pixels of the current view, so a big
    zoom change lands within half a pixel of the old scale: a second pass at
    the new scale brings it within half a pixel of the target.
    """
    for _pass in range(_MAX_PASSES):
        if _range_matches(region, first, last):
            return
        pixels = _frame_to_pixels(region, (first, last))
        if pixels is None:
            return
        x0, x1 = pixels
        ix0, ix1 = int(round(x0)), int(round(x1))
        if ix1 <= ix0:
            return
        try:
            with bpy.context.temp_override(window=window, area=area, region=region):
                result = bpy.ops.view2d.zoom_border(
                    xmin=ix0, xmax=ix1, ymin=0, ymax=int(region.height),
                    wait_for_input=False, zoom_out=False,
                )
        except FBP_DATA_ERRORS as exc:
            fbp_warn_once("timeline_link.zoom_border", "Could not align a linked timeline", exc)
            return
        if "FINISHED" not in result:
            return


def _disable_native_lock(area):
    space = area.spaces.active
    if bool(getattr(space, "show_locked_time", False)):
        try:
            space.show_locked_time = False
        except FBP_DATA_ERRORS:
            pass


def _enable_scene_time_sync(window):
    """Let the Sequencer playhead follow the scene playhead when they differ."""
    workspace = getattr(window, "workspace", None)
    if workspace is None:
        return
    key = int(workspace.as_pointer())
    if key in _SCENE_SYNC_SEEN:
        return
    _SCENE_SYNC_SEEN.add(key)
    sequencer_scene = getattr(workspace, "sequencer_scene", None)
    if sequencer_scene is None or sequencer_scene == getattr(window, "scene", None):
        return
    if hasattr(workspace, "use_scene_time_sync") and not workspace.use_scene_time_sync:
        try:
            workspace.use_scene_time_sync = True
        except FBP_DATA_ERRORS:
            pass


def _pick_default_leader(entries):
    """Prefer a Timeline, then the widest editor."""
    best = None
    best_score = None
    for key, _window, area, region in entries:
        space = area.spaces.active
        is_timeline = area.type == "DOPESHEET_EDITOR" and getattr(space, "mode", "") == "TIMELINE"
        score = (1 if is_timeline else 0, int(region.width))
        if best_score is None or score > best_score:
            best, best_score = key, score
    return best


def sync_linked_timelines():
    """Align every linked time editor to the leader. Return True if any moved."""
    entries = list(_time_regions())
    if not entries:
        _STATES.clear()
        return False
    by_key = {entry[0]: entry for entry in entries}
    current = {}
    for key, _window, area, region in entries:
        _disable_native_lock(area)
        current[key] = _measure(region)
    for _key, window, _area, _region in entries:
        _enable_scene_time_sync(window)

    known = [key for key in current if key in _STATES]
    changed = [key for key in known if _state_changed(_STATES[key], current[key])]
    fresh = [key for key in current if key not in _STATES]

    leader = None
    hint = _LEADER_HINT[0]
    _LEADER_HINT[0] = None
    if hint is not None:
        hint_key = next((key for key in by_key if key[1] == hint), None)
        if hint_key is not None:
            leader = hint_key
    if leader is None and changed:
        leader = _LEADER[0] if _LEADER[0] in changed else changed[0]
    if leader is None and fresh:
        leader = _LEADER[0] if _LEADER[0] in by_key else _pick_default_leader(
            [by_key[key] for key in known] or entries
        )

    moved = False
    if leader is not None and current.get(leader) is not None:
        _LEADER[0] = leader
        _key, leader_window, _leader_area, leader_region = by_key[leader]
        leader_state = current[leader]
        for key, window, area, region in entries:
            if key == leader or current.get(key) is None:
                continue
            first, last = _target_range(leader_window, leader_region, leader_state, window, region)
            if _range_matches(region, first, last):
                continue
            _apply_range(window, area, region, first, last)
            current[key] = _measure(region)
            moved = True

    _STATES.clear()
    _STATES.update(current)
    return moved


def _link_timer():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return _TICK_IDLE
    if not link_enabled(wm):
        _STATES.clear()
        _LEADER[0] = None
        return _TICK_IDLE
    try:
        sync_linked_timelines()
    except FBP_DATA_ERRORS as exc:
        fbp_warn_once("timeline_link.sync", "Could not keep the linked timelines aligned", exc)
        _STATES.clear()
    return _TICK_ACTIVE


def _ensure_timer():
    try:
        fbp_register_timer_once(_link_timer, 0.1, persistent=True)
    except FBP_DATA_ERRORS:
        pass


def _link_update(wm, context):
    _STATES.clear()
    _SCENE_SYNC_SEEN.clear()
    area = getattr(context, "area", None)
    _LEADER_HINT[0] = int(area.as_pointer()) if area is not None and area.type in _TIME_SPACE_TYPES else None
    _LEADER[0] = None
    if link_enabled(wm):
        _ensure_timer()


def draw_link_toggle(self, context):
    space = getattr(context, "space_data", None)
    wm = getattr(context, "window_manager", None)
    if space is None or wm is None or not hasattr(wm, LINK_PROPERTY) or not _space_is_time_editor(space):
        return
    linked = link_enabled(wm)
    self.layout.prop(wm, LINK_PROPERTY, text="", icon="LINKED" if linked else "UNLINKED", toggle=True)


_HEADER_NAMES = ("DOPESHEET_HT_header", "GRAPH_HT_header", "NLA_HT_header", "SEQUENCER_HT_header")


def _register_headers():
    for name in _HEADER_NAMES:
        header = getattr(bpy.types, name, None)
        if header is None:
            continue
        for callback in tuple(getattr(header.draw, "_draw_funcs", ()) or ()):
            if getattr(callback, "__name__", "") == draw_link_toggle.__name__ and callback is not draw_link_toggle:
                try:
                    header.remove(callback)
                except (ValueError, RuntimeError):
                    pass
        header.append(draw_link_toggle)
        _HEADER_CALLBACKS.append(name)


def _unregister_headers():
    for name in _HEADER_CALLBACKS:
        header = getattr(bpy.types, name, None)
        if header is None:
            continue
        try:
            header.remove(draw_link_toggle)
        except (ValueError, RuntimeError):
            pass
    _HEADER_CALLBACKS.clear()


@persistent
def fbp_timeline_link_load_post(*_args):
    _STATES.clear()
    _SCENE_SYNC_SEEN.clear()
    _LEADER[0] = None
    _ensure_timer()


def register():
    bpy.types.WindowManager.fbp_link_timelines = BoolProperty(
        name="Link Timelines",
        description=(
            "Link every timeline (Timeline, Dope Sheet, Graph Editor, NLA, Sequencer): "
            "the same frame sits at the same screen position in all of them, so the "
            "playhead and the start/end frames stay lined up, even when one editor has a "
            "wider channel list or an open sidebar. The editor you scroll or zoom leads"
        ),
        default=True,
        update=_link_update,
    )
    _register_headers()
    append_handler_once(bpy.app.handlers.load_post, fbp_timeline_link_load_post)
    _ensure_timer()


def unregister():
    remove_handlers_by_name(bpy.app.handlers.load_post, fbp_timeline_link_load_post.__name__)
    fbp_unregister_managed_timer(_link_timer)
    _unregister_headers()
    _STATES.clear()
    _SCENE_SYNC_SEEN.clear()
    _LEADER[0] = None
    _LEADER_HINT[0] = None
    try:
        del bpy.types.WindowManager.fbp_link_timelines
    except (AttributeError, RuntimeError):
        pass


__all__ = (
    "LINK_PROPERTY",
    "draw_link_toggle",
    "link_enabled",
    "sync_linked_timelines",
)
