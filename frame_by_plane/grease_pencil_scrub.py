"""Interactive Grease Pencil scrub timeline for Blender 5.2.

The overlay mirrors Blender's Timeline/Dope Sheet playhead snapping, navigation
and keyframe editing while remaining a lightweight View3D GPU drawing.
"""

import json
import math
import time
import uuid
from bisect import bisect_left, bisect_right

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Menu, Operator, Panel

from .interface_preferences import fbp_get_addon_preferences
from .registration import register_interactive_classes, unregister_classes
from .runtime import (
    FBP_DATA_ERRORS,
    fbp_action_fcurves,
    fbp_warn,
    fbp_warn_once,
)
from .safe_tasks import cancel_scheduled_prefixes, schedule_once
from .shortcut_runtime import (
    addon_keymap,
    native_keymap_names,
    primary_modifier_name,
    primary_modifier_pressed,
    refresh_keymap_registration,
    remove_matching_keymap_items,
    shortcut_enabled,
    unregister_keymap_items,
)
from .ui_context import restore_modal_cursor
from .ui_icons import floating_timeline_icon_kwargs


_PREVIOUS_ACTIVE_OPERATOR = globals().get("_ACTIVE_OPERATOR")
_PREVIOUS_PREVIEW_DRAW_HANDLE = globals().get("_PREVIEW_DRAW_HANDLE")
_PREVIOUS_UNREGISTER_HEADER = globals().get("_unregister_header")
_PREVIOUS_UNREGISTER_KEYMAPS = globals().get("_unregister_keymaps")


def _retire_previous_scrub_runtime_early():
    """Close modal/draw/keymap state before redefining the scrub module."""
    retired = 0
    active = _PREVIOUS_ACTIVE_OPERATOR
    if active is not None:
        try:
            active._cleanup(bpy.context)
            retired += 1
        except FBP_DATA_ERRORS:
            pass
    handle = _PREVIOUS_PREVIEW_DRAW_HANDLE
    if handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
            retired += 1
        except FBP_DATA_ERRORS:
            pass
    for callback in (_PREVIOUS_UNREGISTER_HEADER, _PREVIOUS_UNREGISTER_KEYMAPS):
        if not callable(callback):
            continue
        try:
            callback()
            retired += 1
        except FBP_DATA_ERRORS:
            continue
    return retired


_RETIRED_SCRUB_RUNTIME_HANDLES = _retire_previous_scrub_runtime_early()


_OVERLAY_MARGIN_PX = 28.0
_EDGE_THRESHOLD = 0.94
_EDGE_DWELL_SECONDS = 0.38
_EDGE_REPEAT_SECONDS = 0.12
_TIMER_INTERVAL = 0.04
_AXIS_CAPTURE_PX = 42.0
_MAGNET_INNER_RATIO = 0.42
_MAGNET_EPSILON_PX = 0.05
_DIRECT_SCRUB_INNER_PX = 12.0
_ONION_HANDLE_RADIUS_PX = 5.0
_ONION_HANDLE_HIT_PADDING_PX = 5.0
_BOOKMARK_PREFIX = "✦ - "
_LEGACY_BOOKMARK_PREFIXES = ("✦ - ", "✦-", "✦ ", "★ ")
_BOOKMARK_STATE_KEY = "_fbp_scrub_bookmarks_v1"
_BOOKMARK_DEFAULT_COLOR = "WHITE"
_BOOKMARK_COLOR_ITEMS = (
    ("WHITE", "White", "White bookmark", "STRIP_COLOR_01", 0),
    ("GREY", "Grey", "Grey bookmark", "STRIP_COLOR_02", 1),
    ("YELLOW", "Yellow", "Yellow bookmark", "STRIP_COLOR_03", 2),
    ("RED", "Red", "Red bookmark", "STRIP_COLOR_04", 3),
    ("ORANGE", "Orange", "Orange bookmark", "STRIP_COLOR_05", 4),
    ("GREEN", "Green", "Green bookmark", "STRIP_COLOR_06", 5),
    ("BLUE", "Blue", "Blue bookmark", "STRIP_COLOR_07", 6),
    ("MAGENTA", "Magenta", "Magenta bookmark", "STRIP_COLOR_08", 7),
    ("PURPLE", "Purple", "Purple bookmark", "STRIP_COLOR_09", 8),
)
_BOOKMARK_COLORS = {
    "WHITE": (0.94, 0.94, 0.94, 0.88),
    "GREY": (0.47, 0.47, 0.47, 0.88),
    "YELLOW": (0.95, 0.73, 0.12, 0.90),
    "RED": (0.82, 0.16, 0.15, 0.90),
    "ORANGE": (0.95, 0.39, 0.08, 0.90),
    "GREEN": (0.18, 0.67, 0.25, 0.90),
    "BLUE": (0.15, 0.42, 0.92, 0.90),
    "MAGENTA": (0.90, 0.17, 0.62, 0.90),
    "PURPLE": (0.48, 0.22, 0.82, 0.90),
}
_BOOKMARK_POINTER_UIDS = globals().get("_BOOKMARK_POINTER_UIDS", {})
if not isinstance(_BOOKMARK_POINTER_UIDS, dict):
    _BOOKMARK_POINTER_UIDS = {}
_BOOKMARK_HIT_RADIUS_PX = 9.0
_MARKER_HIT_RADIUS_PX = 7.0
_CURSOR_LABEL_CAPTURE_PX = 10.0
_KEYFRAME_HIT_PADDING_PX = 5.0
_DRAG_THRESHOLD_PX = 4.0
_TAP_HOLD_THRESHOLD_SECONDS = 0.30
_ZOOM_STEP = 0.80
_WHEEL_PAN_FRACTION = 0.12
_MAX_TIMELINE_TICKS = 2400
_FRAME_NUMBER_MIN = -1048574
_FRAME_NUMBER_MAX = 1048574
_GP_SCRUB_KEYMAPS = []
_ACTIVE_OPERATOR = None
_PREVIEW_DRAW_HANDLE = None
_PREVIEW_ACTIVE = False
_PREVIEW_STATE = None
_HEADER_REGISTERED = False
_ORIGINAL_VIEW3D_HEADER_DRAW = None
_SCRUB_FRAME_CLIPBOARD = None
# Process-only frame navigation memory. Blender includes Scene.frame_current in
# history snapshots, so a GP stroke made immediately after Scrub Slider
# navigation can otherwise restore the previous frame together with the stroke.
# These values live outside Main/RNA and therefore survive Undo without adding
# an Undo step of their own.
_SCRUB_HISTORY_FRAME = None
_PENDING_SCRUB_HISTORY_FRAME = None
_PERSISTENT_SCRUB_BINDINGS = {}
_MAX_PERSISTENT_SCRUB_BINDINGS = 64

_VIEW2D_NAVIGATION_ACTIONS = {
    "view2d.pan": "PAN",
    "view2d.zoom": "ZOOM",
    "view2d.zoom_in": "ZOOM_IN",
    "view2d.zoom_out": "ZOOM_OUT",
}

_KEYFRAME_TYPE_DEFINITIONS = (
    ("KEYFRAME", "Keyframe", "KEYTYPE_KEYFRAME_VEC", ("keyframe",), ("keyframe_selected",), 1.00),
    ("BREAKDOWN", "Breakdown", "KEYTYPE_BREAKDOWN_VEC", ("keyframe_breakdown",), ("keyframe_breakdown_selected",), 0.85),
    ("MOVING_HOLD", "Moving Hold", "KEYTYPE_MOVING_HOLD_VEC", ("keyframe_moving_hold", "keyframe_movehold"), ("keyframe_moving_hold_selected", "keyframe_movehold_selected"), 0.925),
    ("EXTREME", "Extreme", "KEYTYPE_EXTREME_VEC", ("keyframe_extreme",), ("keyframe_extreme_selected",), 1.20),
    ("JITTER", "Jitter", "KEYTYPE_JITTER_VEC", ("keyframe_jitter",), ("keyframe_jitter_selected",), 0.80),
    ("GENERATED", "Generated", "KEYTYPE_GENERATED_VEC", ("keyframe_generated",), ("keyframe_generated_selected",), 0.75),
)
_DEFAULT_BLENDER_KEYFRAME_COLORS = {
    "KEYFRAME": {"passive": (0xBF / 255, 0xBF / 255, 0xBF / 255, 1.0), "selected": (1.0, 0xBE / 255, 0x33 / 255, 1.0)},
    "BREAKDOWN": {"passive": (0xB3 / 255, 0xDB / 255, 0xE8 / 255, 1.0), "selected": (0x54 / 255, 0xBF / 255, 0xED / 255, 1.0)},
    "MOVING_HOLD": {"passive": (0x80 / 255, 0x80 / 255, 0x80 / 255, 1.0), "selected": (1.0, 0xAF / 255, 0x23 / 255, 1.0)},
    "EXTREME": {"passive": (0xE8 / 255, 0xB3 / 255, 0xCC / 255, 1.0), "selected": (0xF2 / 255, 0x80 / 255, 0x80 / 255, 1.0)},
    "JITTER": {"passive": (0x94 / 255, 0xE5 / 255, 0x75 / 255, 1.0), "selected": (0x61 / 255, 0xC0 / 255, 0x42 / 255, 1.0)},
    "GENERATED": {"passive": (0x58 / 255, 0x58 / 255, 0x58 / 255, 1.0), "selected": (0xA2 / 255, 0x89 / 255, 0x62 / 255, 1.0)},
}
_KEYFRAME_TYPE_BY_ID = {item[0]: item for item in _KEYFRAME_TYPE_DEFINITIONS}
_SNAP_TARGET_LABELS = {
    "FRAME": "Frames",
    "SECOND": "Seconds",
    "MARKER": "Markers",
    "KEY": "Keyframes",
    "STRIP": "Strips",
}
_SNAP_TARGET_ORDER = ("FRAME", "SECOND", "MARKER", "KEY", "STRIP")


def _safe_int(value, default, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        number = int(default)
    return max(int(minimum), min(int(maximum), number))


def _rgb(value, fallback=(0.0, 0.0, 0.0)):
    try:
        channels = tuple(float(channel) for channel in value[:3])
        if len(channels) == 3 and all(math.isfinite(channel) for channel in channels):
            return tuple(max(0.0, min(1.0, channel)) for channel in channels)
    except (TypeError, ValueError, OverflowError, AttributeError, ReferenceError):
        pass
    return tuple(float(channel) for channel in fallback)


def _rgba(value, fallback=(0.0, 0.0, 0.0, 1.0), *, alpha=None):
    try:
        fallback_channels = tuple(float(channel) for channel in fallback[:4])
    except (TypeError, ValueError, OverflowError, AttributeError):
        fallback_channels = (0.0, 0.0, 0.0, 1.0)
    if len(fallback_channels) == 3:
        fallback_channels = (*fallback_channels, 1.0)
    elif len(fallback_channels) < 3:
        fallback_channels = (0.0, 0.0, 0.0, 1.0)
    try:
        channels = tuple(float(channel) for channel in value)
        if len(channels) >= 3 and all(math.isfinite(channel) for channel in channels[:4]):
            result = tuple(max(0.0, min(1.0, channel)) for channel in channels[:4])
            if len(result) == 3:
                result = (*result, fallback_channels[3])
            if alpha is not None:
                result = (*result[:3], max(0.0, min(1.0, float(alpha))))
            return result
    except (TypeError, ValueError, OverflowError, AttributeError, ReferenceError):
        pass
    result = fallback_channels
    if alpha is not None:
        result = (*result[:3], max(0.0, min(1.0, float(alpha))))
    return result


def _theme_color(owners, names, fallback, *, alpha=None):
    if not isinstance(owners, (tuple, list)):
        owners = (owners,)
    for owner in owners:
        if owner is None:
            continue
        for name in names:
            try:
                value = getattr(owner, name, None)
            except FBP_DATA_ERRORS:
                value = None
            if value is not None:
                return _rgba(value, fallback, alpha=alpha)
    return _rgba(fallback, fallback, alpha=alpha)


def scrub_preferences(context=None):
    """Return validated overlay, appearance and motion preferences."""
    preferences = fbp_get_addon_preferences(context)
    maximum = _safe_int(getattr(preferences, "gp_scrub_max_range", 50), 50, 1, 240)
    position = str(getattr(preferences, "gp_scrub_position", "LEFT") or "LEFT").upper()
    if position not in {"TOP", "BOTTOM", "LEFT", "RIGHT"}:
        position = "LEFT"
    line_color = _rgb(getattr(preferences, "gp_scrub_line_color", (0.0, 0.0, 0.0)))
    frame_tick_color = _rgba(getattr(preferences, "gp_scrub_frame_tick_color", (0.0, 0.0, 0.0, 0.58)), (0.0, 0.0, 0.0, 0.58))
    major_tick_color = _rgba(getattr(preferences, "gp_scrub_major_tick_color", (0.0, 0.0, 0.0, 1.0)), (0.0, 0.0, 0.0, 1.0))
    second_tick_color = _rgba(getattr(preferences, "gp_scrub_second_tick_color", (0.0, 0.0, 0.0, 1.0)), (0.0, 0.0, 0.0, 1.0))
    text_color = _rgb(getattr(preferences, "gp_scrub_text_color", (0.0, 0.0, 0.0)))
    cursor_color = _rgb(getattr(preferences, "gp_scrub_cursor_color", (71 / 255, 114 / 255, 179 / 255)))
    cursor_text_color = _rgb(getattr(preferences, "gp_scrub_cursor_text_color", (1.0, 1.0, 1.0)))
    invert_vertical = bool(getattr(preferences, "gp_scrub_invert_vertical", False))
    try:
        sensitivity = max(0.1, min(12.0, float(getattr(preferences, "gp_scrub_sensitivity", 2.0))))
        slow_factor = max(0.02, min(1.0, float(getattr(preferences, "gp_scrub_shift_factor", 0.2))))
        length_ratio = max(0.2, min(1.0, float(getattr(preferences, "gp_scrub_length_ratio", 0.5))))
        offset = max(8.0, min(240.0, float(getattr(preferences, "gp_scrub_edge_offset", 240.0))))
        tick_scale = max(0.25, min(3.0, float(getattr(preferences, "gp_scrub_tick_scale", 0.5))))
        line_width = max(0.5, min(6.0, float(getattr(preferences, "gp_scrub_line_width", 1.0))))
        cursor_width = max(0.5, min(8.0, float(getattr(preferences, "gp_scrub_cursor_width", 2.0))))
        cursor_label_scale = max(0.6, min(2.0, float(getattr(preferences, "gp_scrub_cursor_label_scale", 1.0))))
        major_interval = _safe_int(getattr(preferences, "gp_scrub_major_interval", 10), 10, 2, 100)
        micro_tick_length = max(1.0, min(20.0, float(getattr(preferences, "gp_scrub_micro_tick_length", 3.0))))
        major_tick_length = max(2.0, min(32.0, float(getattr(preferences, "gp_scrub_major_tick_length", 7.0))))
        second_tick_length = max(3.0, min(48.0, float(getattr(preferences, "gp_scrub_second_tick_length", 11.0))))
    except (TypeError, ValueError, OverflowError, AttributeError, ReferenceError):
        sensitivity, slow_factor, length_ratio, offset, tick_scale, line_width = 2.0, 0.2, 0.5, 240.0, 0.5, 1.0
        cursor_width, cursor_label_scale, major_interval = 2.0, 1.0, 10
        micro_tick_length, major_tick_length, second_tick_length = 3.0, 7.0, 11.0
    return (
        maximum,
        position,
        line_color,
        frame_tick_color,
        major_tick_color,
        second_tick_color,
        text_color,
        cursor_color,
        cursor_text_color,
        sensitivity,
        slow_factor,
        length_ratio,
        offset,
        tick_scale,
        line_width,
        cursor_width,
        cursor_label_scale,
        major_interval,
        micro_tick_length,
        major_tick_length,
        second_tick_length,
        invert_vertical,
    )


def scrub_activation_released(event_type, event_value, activation_event_type):
    """Detect release of the physical < shortcut across keyboard layouts.

    Blender may report Shift+, as ``COMMA`` on press and ``GRLESS`` on release
    (or the reverse), depending on the OS keyboard layout and modifier release
    order. Treat those two event identifiers as the same physical shortcut.
    """
    if str(event_value or "") != "RELEASE":
        return False
    event_type = str(event_type or "")
    activation_event_type = str(activation_event_type or "")
    if activation_event_type in {"GRLESS", "COMMA"}:
        return event_type in {"GRLESS", "COMMA"}
    return event_type == activation_event_type


def scrub_undo_passthrough(event_type, event_value, *, ctrl=False, oskey=False):
    """Return whether a native Blender Undo event must bypass the slider."""
    return bool(
        str(event_type or "") == "Z"
        and str(event_value or "") == "PRESS"
        and (bool(ctrl) or bool(oskey))
    )


def scrub_history_restore_target(
    recorded_scene_name, recorded_frame, current_scene_name, current_frame
):
    """Return a scrub frame that should survive the next history operation.

    The helper is deliberately RNA-free so its contract can be tested without
    creating Blender data. A restore is armed only while the active Scene is
    still on the exact frame last chosen through the Scrub Slider. Native
    Timeline navigation therefore invalidates stale slider memory naturally.
    """
    recorded_name = str(recorded_scene_name or "")
    current_name = str(current_scene_name or "")
    if not recorded_name or recorded_name != current_name:
        return None
    try:
        recorded = int(recorded_frame)
        current = int(current_frame)
    except (TypeError, ValueError, OverflowError):
        return None
    return recorded if recorded == current else None


def _scrub_history_scene_name(scene):
    if scene is None:
        return ""
    try:
        return str(getattr(scene, "name_full", "") or getattr(scene, "name", "") or "")
    except FBP_DATA_ERRORS:
        return ""


def note_scrub_history_frame(scene, frame):
    """Remember the latest frame chosen by the Scrub Slider outside RNA."""
    global _SCRUB_HISTORY_FRAME
    scene_name = _scrub_history_scene_name(scene)
    if not scene_name:
        return False
    try:
        target = int(frame)
    except (TypeError, ValueError, OverflowError):
        return False
    _SCRUB_HISTORY_FRAME = (scene_name, target)
    return True


def prepare_scrub_history_restore(scene):
    """Arm frame preservation before Blender replaces Main for Undo/Redo."""
    global _SCRUB_HISTORY_FRAME, _PENDING_SCRUB_HISTORY_FRAME
    _PENDING_SCRUB_HISTORY_FRAME = None
    recorded = _SCRUB_HISTORY_FRAME
    if not isinstance(recorded, tuple) or len(recorded) != 2 or scene is None:
        return False
    try:
        target = scrub_history_restore_target(
            recorded[0],
            recorded[1],
            _scrub_history_scene_name(scene),
            getattr(scene, "frame_current", None),
        )
    except FBP_DATA_ERRORS:
        target = None
    if target is None:
        # A native Timeline/Dope Sheet frame change happened after the last
        # slider navigation. Retire the stale frame so it cannot revive later.
        _SCRUB_HISTORY_FRAME = None
        return False
    _PENDING_SCRUB_HISTORY_FRAME = (str(recorded[0]), int(target))
    return True


def restore_scrub_history_frame(scene):
    """Restore only the playhead after Undo/Redo, leaving the GP edit undone."""
    global _PENDING_SCRUB_HISTORY_FRAME
    pending = _PENDING_SCRUB_HISTORY_FRAME
    _PENDING_SCRUB_HISTORY_FRAME = None
    if not isinstance(pending, tuple) or len(pending) != 2 or scene is None:
        return False
    scene_name = _scrub_history_scene_name(scene)
    if not scene_name or scene_name != str(pending[0] or ""):
        return False
    try:
        minimum, maximum = scene_frame_bounds(scene)
        target = max(int(minimum), min(int(maximum), int(pending[1])))
        current = int(getattr(scene, "frame_current", target))
    except (TypeError, ValueError, OverflowError, AttributeError, ReferenceError):
        return False
    if current != target:
        try:
            scene.frame_set(target)
        except FBP_DATA_ERRORS:
            try:
                scene.frame_current = target
            except FBP_DATA_ERRORS:
                return False
    active = _ACTIVE_OPERATOR
    if active is not None:
        try:
            active._current_frame = target
        except (AttributeError, ReferenceError, TypeError):
            pass
    note_scrub_history_frame(scene, target)
    return True


def clear_scrub_history_frame_state():
    """Discard process-only navigation memory during add-on teardown."""
    global _SCRUB_HISTORY_FRAME, _PENDING_SCRUB_HISTORY_FRAME
    _SCRUB_HISTORY_FRAME = None
    _PENDING_SCRUB_HISTORY_FRAME = None


def scrub_release_action(elapsed, moved, persistent_before, *, threshold=_TAP_HOLD_THRESHOLD_SECONDS):
    """Resolve the dual tap/hold shortcut without depending on Blender events."""
    try:
        is_tap = float(elapsed) < max(0.05, float(threshold)) and not bool(moved)
    except (TypeError, ValueError, OverflowError):
        is_tap = False
    if is_tap:
        return "DISABLE_PERSISTENT" if bool(persistent_before) else "ENABLE_PERSISTENT"
    return "KEEP_PERSISTENT" if bool(persistent_before) else "FINISH_MOMENTARY"


def clamp_timeline_view(center, visible_count, minimum, maximum):
    """Return a valid center/visible-frame-count pair clipped to the scene."""
    try:
        low = int(minimum)
        high = int(maximum)
        if high < low:
            low, high = high, low
        scene_count = max(1, high - low + 1)
        safe_count = max(1, min(scene_count, int(round(float(visible_count)))))
        safe_center = max(float(low), min(float(high), float(center)))
    except (TypeError, ValueError, OverflowError):
        return 0.0, 1
    return safe_center, safe_count

def resolve_keyframe_move_delta(selected_by_layer, occupied_by_layer, requested_delta, minimum, maximum):
    """Clamp a multi-layer key move to the active scene/preview bounds.

    Occupied targets are intentionally allowed. Grease Pencil stores only one
    drawing per layer/frame, so the interactive operator temporarily stashes
    an existing target drawing and removes it only when the move is confirmed.
    """
    try:
        requested = int(round(float(requested_delta)))
        low = int(minimum)
        high = int(maximum)
    except (TypeError, ValueError, OverflowError):
        return 0
    if high < low:
        low, high = high, low
    selected_map = {
        key: frozenset(int(number) for number in tuple(numbers or ()))
        for key, numbers in dict(selected_by_layer or {}).items()
    }
    del occupied_by_layer
    sources = tuple(
        number
        for selected in selected_map.values()
        for number in selected
    )
    if not sources:
        return 0
    minimum_delta = max(low - source for source in sources)
    maximum_delta = min(high - source for source in sources)
    return max(minimum_delta, min(maximum_delta, requested))


def wheel_navigation_direction(event_type):
    """Normalize Blender wheel event aliases to +1 (up/in) or -1 (down/out)."""
    token = str(event_type or "").upper()
    if token in {"WHEELUPMOUSE", "WHEELINMOUSE"}:
        return 1
    if token in {"WHEELDOWNMOUSE", "WHEELOUTMOUSE"}:
        return -1
    return 0


def preview_range_signature(scene):
    """Return a stable signature for live Preview Range synchronization."""
    try:
        enabled = bool(getattr(scene, "use_preview_range", False))
        if enabled:
            minimum = int(scene.frame_preview_start)
            maximum = int(scene.frame_preview_end)
        else:
            minimum = int(scene.frame_start)
            maximum = int(scene.frame_end)
    except FBP_DATA_ERRORS:
        return False, _FRAME_NUMBER_MIN, _FRAME_NUMBER_MAX
    if maximum < minimum:
        minimum, maximum = maximum, minimum
    return enabled, minimum, maximum


def resolve_keyframe_duplicate_delta(selected_by_layer, occupied_by_layer, minimum, maximum):
    """Find the nearest free non-zero offset for duplicating selected drawings."""
    try:
        low = int(minimum)
        high = int(maximum)
    except (TypeError, ValueError, OverflowError):
        return 0
    if high < low:
        low, high = high, low
    selected_map = {
        key: frozenset(int(number) for number in tuple(numbers or ()))
        for key, numbers in dict(selected_by_layer or {}).items()
    }
    occupied_map = {
        key: frozenset(int(number) for number in tuple(numbers or ()))
        for key, numbers in dict(occupied_by_layer or {}).items()
    }
    if not any(selected_map.values()):
        return 0

    def _valid(delta):
        for key, selected in selected_map.items():
            occupied = occupied_map.get(key, frozenset())
            targets = {source + int(delta) for source in selected}
            if any(target < low or target > high for target in targets):
                return False
            if targets.intersection(occupied):
                return False
        return True

    scene_span = max(1, high - low)
    for distance in range(1, scene_span + 1):
        if _valid(distance):
            return distance
        if _valid(-distance):
            return -distance
    return 0


def _event_matches_keymap_item(item, event):
    """Match a Blender event against one active KeyMapItem."""
    try:
        if not bool(getattr(item, "active", True)):
            return False
        if str(getattr(item, "type", "") or "") != str(getattr(event, "type", "") or ""):
            return False
        item_value = str(getattr(item, "value", "ANY") or "ANY")
        event_value = str(getattr(event, "value", "ANY") or "ANY")
        if item_value != "ANY" and item_value != event_value:
            return False
        if not bool(getattr(item, "any", False)):
            for name in ("shift", "ctrl", "alt", "oskey"):
                if bool(getattr(item, name, False)) != bool(getattr(event, name, False)):
                    return False
        key_modifier = str(getattr(item, "key_modifier", "NONE") or "NONE")
        event_key_modifier = str(getattr(event, "key_modifier", "NONE") or "NONE")
        if key_modifier not in {"", "NONE"} and key_modifier != event_key_modifier:
            return False
        direction = str(getattr(item, "direction", "ANY") or "ANY")
        event_direction = str(getattr(event, "direction", "ANY") or "ANY")
        if direction != "ANY" and event_direction not in {"ANY", direction}:
            return False
        return True
    except FBP_DATA_ERRORS:
        return False


def native_view2d_navigation_action(window_manager, event):
    """Return the action bound by the user's active native View2D keymap."""
    keyconfigs = getattr(window_manager, "keyconfigs", None)
    seen = set()
    for keyconfig_name in ("user", "active"):
        keyconfig = getattr(keyconfigs, keyconfig_name, None)
        if keyconfig is None:
            continue
        try:
            keymap = keyconfig.keymaps.get("View2D")
        except FBP_DATA_ERRORS:
            keymap = None
        if keymap is None:
            continue
        for item in tuple(getattr(keymap, "keymap_items", ()) or ()):
            identity = _rna_pointer(item) or id(item)
            if identity in seen:
                continue
            seen.add(identity)
            action = _VIEW2D_NAVIGATION_ACTIONS.get(
                str(getattr(item, "idname", "") or "")
            )
            if action and _event_matches_keymap_item(item, event):
                return action
    return ""


def _normalize_snap_target(value):
    token = str(value or "").strip().upper().replace(" ", "_")
    aliases = {
        "FRAMES": "FRAME",
        "SECONDS": "SECOND",
        "MARKERS": "MARKER",
        "KEYFRAME": "KEY",
        "KEYFRAMES": "KEY",
        "STRIPS": "STRIP",
    }
    token = aliases.get(token, token)
    return token if token in _SNAP_TARGET_ORDER else ""


def normalize_playhead_snap_targets(value):
    """Normalize Blender's mixed-case playhead snap enum values."""
    if isinstance(value, str):
        values = (value,)
    else:
        try:
            values = tuple(value or ())
        except TypeError:
            values = ()
    normalized = {_normalize_snap_target(item) for item in values}
    return frozenset(item for item in normalized if item)


def playhead_snap_settings(scene):
    """Read Timeline playhead snapping and the animation-editor magnet state."""
    try:
        settings = scene.tool_settings
    except FBP_DATA_ERRORS:
        settings = None
    if settings is None:
        return {
            "enabled": False,
            "targets": frozenset(),
            "frame_step": 2,
            "second_step": 1,
            "distance_px": 20.0,
        }

    try:
        playhead_enabled = bool(getattr(settings, "use_snap_playhead", False))
    except FBP_DATA_ERRORS:
        playhead_enabled = False
    try:
        animation_enabled = bool(getattr(settings, "use_snap_anim", False))
    except FBP_DATA_ERRORS:
        animation_enabled = False
    enabled = bool(playhead_enabled or animation_enabled)

    # Prefer the dedicated playhead targets when that mode is enabled. When the
    # user only enabled the Timeline/Dope Sheet magnet, mirror its animation
    # snap target instead of silently reading the inactive playhead target set.
    try:
        if playhead_enabled:
            raw_targets = getattr(settings, "snap_playhead_element", "FRAME")
        elif animation_enabled:
            raw_targets = getattr(settings, "snap_anim_element", "FRAME")
        else:
            raw_targets = getattr(
                settings,
                "snap_playhead_element",
                getattr(settings, "snap_anim_element", "FRAME"),
            )
    except FBP_DATA_ERRORS:
        raw_targets = "FRAME"
    targets = normalize_playhead_snap_targets(raw_targets)
    if not targets:
        targets = frozenset(("FRAME",))

    if playhead_enabled:
        frame_step = _safe_int(
            getattr(settings, "snap_playhead_frame_step", 2), 2, 1, 32768
        )
        second_step = _safe_int(
            getattr(settings, "snap_playhead_second_step", 1), 1, 1, 32768
        )
    else:
        # Animation-editor FRAME/SECOND snapping uses the native unit itself;
        # the configurable multi-frame steps belong to playhead snapping only.
        frame_step = 1
        second_step = 1
    try:
        distance_px = float(getattr(settings, "playhead_snap_distance", 20.0))
        if not math.isfinite(distance_px):
            distance_px = 20.0
    except (TypeError, ValueError, OverflowError, AttributeError, ReferenceError):
        distance_px = 20.0
    distance_px = max(0.0, distance_px)
    return {
        "enabled": enabled,
        "targets": targets,
        "frame_step": frame_step,
        "second_step": second_step,
        "distance_px": distance_px,
    }


def animation_snapping_enabled(scene):
    """Compatibility helper for diagnostics and third-party integrations."""
    return bool(playhead_snap_settings(scene)["enabled"])


def scene_fps(scene):
    try:
        render = scene.render
        fps = float(render.fps)
        base = float(render.fps_base)
        if not math.isfinite(fps) or not math.isfinite(base) or base == 0.0:
            raise ValueError
        return max(0.001, fps / base)
    except FBP_DATA_ERRORS + (OverflowError,):
        return 24.0


def major_second_frames(minimum, maximum, fps):
    """Return integer frame ticks nearest to each elapsed second."""
    try:
        left = int(math.floor(min(float(minimum), float(maximum))))
        right = int(math.ceil(max(float(minimum), float(maximum))))
        rate = max(0.001, float(fps))
    except (TypeError, ValueError, OverflowError):
        return ()
    first_second = int(math.floor(left / rate)) - 1
    last_second = int(math.ceil(right / rate)) + 1
    return tuple(sorted({int(round(second * rate)) for second in range(first_second, last_second + 1) if left <= int(round(second * rate)) <= right}))


def _rna_pointer(value):
    try:
        return int(value.as_pointer()) if value is not None else 0
    except FBP_DATA_ERRORS:
        return 0


def _normalized_keyframe_type(value):
    key_type = str(value or "KEYFRAME").upper()
    return key_type if key_type in _KEYFRAME_TYPE_BY_ID else "KEYFRAME"


def grease_pencil_keyframe_records(obj):
    """Return ``(frame, type, active_layer, selected)`` records for visible layers."""
    records = {}
    try:
        data = getattr(obj, "data", None)
        layers = getattr(data, "layers", None)
        active_layer = getattr(layers, "active", None)
        active_pointer = _rna_pointer(active_layer)
        for layer in tuple(layers or ()):
            try:
                if bool(getattr(layer, "hide", False)):
                    continue
            except FBP_DATA_ERRORS:
                pass
            is_active = bool(active_pointer and _rna_pointer(layer) == active_pointer)
            for frame in tuple(getattr(layer, "frames", ()) or ()):
                number = int(getattr(frame, "frame_number", 0) or 0)
                key_type = _normalized_keyframe_type(getattr(frame, "keyframe_type", "KEYFRAME"))
                selected = bool(getattr(frame, "select", False))
                previous = records.get(number)
                if previous is None or is_active:
                    records[number] = (number, key_type, is_active, selected)
    except FBP_DATA_ERRORS:
        pass
    return tuple(records[number] for number in sorted(records))


def grease_pencil_keyframes(obj):
    records = grease_pencil_keyframe_records(obj)
    return (
        tuple(record[0] for record in records),
        tuple(record[0] for record in records if record[2]),
    )


def grease_pencil_editable_frames(obj, *, visible_only=True):
    """Return editable ``(layer, frame)`` pairs without collapsing layers."""
    result = []
    try:
        data = getattr(obj, "data", None)
        for layer in tuple(getattr(data, "layers", ()) or ()):
            if visible_only:
                try:
                    if bool(getattr(layer, "hide", False)) or bool(
                        getattr(layer, "lock", False)
                    ):
                        continue
                except FBP_DATA_ERRORS:
                    continue
            for frame in tuple(getattr(layer, "frames", ()) or ()):
                result.append((layer, frame))
    except FBP_DATA_ERRORS:
        return ()
    return tuple(result)


def selected_grease_pencil_frames(obj):
    return tuple(
        (layer, frame)
        for layer, frame in grease_pencil_editable_frames(obj)
        if bool(getattr(frame, "select", False))
    )


def select_grease_pencil_frame_number(obj, frame_number, *, extend=False, toggle=False):
    """Select every visible drawing represented by a collapsed slider diamond."""
    try:
        target = int(frame_number)
    except (TypeError, ValueError, OverflowError):
        return 0
    rows = grease_pencil_editable_frames(obj)
    matching = tuple(
        (layer, frame)
        for layer, frame in rows
        if int(getattr(frame, "frame_number", 0) or 0) == target
    )
    if not matching:
        return 0
    matching_ids = {(_rna_pointer(layer), _rna_pointer(frame)) for layer, frame in matching}
    should_deselect = bool(
        toggle and all(bool(getattr(frame, "select", False)) for _layer, frame in matching)
    )
    changed = 0
    for layer, frame in rows:
        key = (_rna_pointer(layer), _rna_pointer(frame))
        try:
            if key in matching_ids:
                desired = not should_deselect
            elif extend:
                continue
            else:
                desired = False
            if bool(frame.select) != bool(desired):
                frame.select = bool(desired)
                changed += 1
        except FBP_DATA_ERRORS:
            continue
    return changed


def select_all_grease_pencil_frames(obj, selected=True):
    changed = 0
    for _layer, frame in grease_pencil_editable_frames(obj):
        try:
            if bool(frame.select) != bool(selected):
                frame.select = bool(selected)
                changed += 1
        except FBP_DATA_ERRORS:
            continue
    return changed


def set_selected_grease_pencil_keyframe_type(obj, keyframe_type):
    target_type = _normalized_keyframe_type(keyframe_type)
    changed = 0
    for _layer, frame in selected_grease_pencil_frames(obj):
        try:
            if str(frame.keyframe_type) != target_type:
                frame.keyframe_type = target_type
                changed += 1
        except FBP_DATA_ERRORS:
            continue
    return changed


def delete_selected_grease_pencil_frames(obj):
    """Delete selected editable Grease Pencil drawings and return their count."""
    targets = tuple(
        (layer, int(frame.frame_number))
        for layer, frame in selected_grease_pencil_frames(obj)
    )
    deleted = 0
    for layer, frame_number in targets:
        try:
            layer.frames.remove(frame_number)
            deleted += 1
        except FBP_DATA_ERRORS:
            continue
    return deleted


def _grease_pencil_frame_at(layer, frame_number):
    try:
        target = int(frame_number)
        return next(
            (
                frame
                for frame in tuple(getattr(layer, "frames", ()) or ())
                if int(getattr(frame, "frame_number", 0) or 0) == target
            ),
            None,
        )
    except FBP_DATA_ERRORS:
        return None


def _grease_pencil_layer_at(data, layer_index, layer_name):
    try:
        layers = tuple(getattr(data, "layers", ()) or ())
        index = int(layer_index)
        if 0 <= index < len(layers) and str(getattr(layers[index], "name", "")) == str(
            layer_name
        ):
            return layers[index]
        return next(
            (
                layer
                for layer in layers
                if str(getattr(layer, "name", "") or "") == str(layer_name)
            ),
            None,
        )
    except FBP_DATA_ERRORS:
        return None


def _remove_grease_pencil_data(data):
    if data is None:
        return
    try:
        if getattr(data, "users", 0) == 0:
            bpy.data.grease_pencils.remove(data)
    except FBP_DATA_ERRORS:
        pass


def _clear_scrub_frame_clipboard():
    global _SCRUB_FRAME_CLIPBOARD
    clipboard = _SCRUB_FRAME_CLIPBOARD
    _SCRUB_FRAME_CLIPBOARD = None
    if isinstance(clipboard, dict):
        _remove_grease_pencil_data(clipboard.get("data"))


def _copy_frame_from_data(
    target_layer,
    target_frame_number,
    source_data,
    source_layer_index,
    source_layer_name,
    source_frame_number,
    *,
    selected=True,
):
    source_layer = _grease_pencil_layer_at(
        source_data,
        source_layer_index,
        source_layer_name,
    )
    source_frame = (
        _grease_pencil_frame_at(source_layer, source_frame_number)
        if source_layer is not None
        else None
    )
    if source_frame is None:
        return None
    try:
        existing = _grease_pencil_frame_at(target_layer, target_frame_number)
        if existing is not None:
            target_layer.frames.remove(int(target_frame_number))
        created = target_layer.frames.new(int(target_frame_number))
        created.drawing = source_frame.drawing
        created.keyframe_type = _normalized_keyframe_type(
            getattr(source_frame, "keyframe_type", "KEYFRAME")
        )
        created.select = bool(selected)
        return created
    except FBP_DATA_ERRORS:
        return None


def _refresh_active_scrub(context):
    active = _ACTIVE_OPERATOR
    if active is not None:
        active._refresh_keyframe_cache(context)
        active._tag_redraw()
    _tag_all_view3d_redraw()


def blender_theme_palette(context, background_rgb=None):
    """Read Blender 5.2 animation-theme colors with guarded fallbacks."""
    adaptive = contrast_palette(
        viewport_background_color(context) if background_rgb is None else background_rgb
    )
    palette = {
        **adaptive,
        "grid": (*adaptive["secondary"][:3], 0.66),
        "accent": (0x47 / 255, 0x72 / 255, 0xB3 / 255, 1.0),
        "keyframe_border": (0.0, 0.0, 0.0, 1.0),
        "keyframe_border_selected": (0.0, 0.0, 0.0, 1.0),
        "keyframe_scale_factor": 1.0,
        "keyframe_types": {
            key_id: dict(colors) for key_id, colors in _DEFAULT_BLENDER_KEYFRAME_COLORS.items()
        },
    }
    try:
        themes = getattr(getattr(context, "preferences", None), "themes", None)
        theme = themes[0] if themes else None
        dope = getattr(theme, "dopesheet_editor", None)
        common = getattr(theme, "common", None)
        common_anim = getattr(common, "anim", None)
        dope_common = getattr(dope, "common", None)
        dope_anim = getattr(dope, "anim", None)
        nested_dope_anim = getattr(dope_common, "anim", None)
        animation_owners = (common_anim, nested_dope_anim, dope_anim, dope_common, dope)
        dope_owners = (dope, dope_common, dope_anim, nested_dope_anim, common_anim)
        space = getattr(dope, "space", None)
        palette["foreground"] = _theme_color((space, dope), ("text_hi", "text"), palette["foreground"])
        palette["secondary"] = _theme_color((space, dope), ("text", "header_text"), palette["secondary"])
        palette["grid"] = _theme_color(dope_owners, ("grid",), palette["grid"], alpha=0.66)
        palette["accent"] = _theme_color(
            animation_owners,
            ("playhead", "frame_current", "current_frame"),
            palette["accent"],
        )
        palette["keyframe_border"] = _theme_color(
            dope_owners,
            ("keyframe_border", "keyborder"),
            palette["keyframe_border"],
        )
        palette["keyframe_border_selected"] = _theme_color(
            dope_owners,
            ("keyframe_border_selected", "keyborder_select", "keyframe_border", "keyborder"),
            palette["keyframe_border_selected"],
        )
        scale_found = False
        for owner in dope_owners:
            for attribute in ("keyframe_scale_factor", "keyframe_scale_fac"):
                try:
                    factor = float(getattr(owner, attribute))
                    if math.isfinite(factor):
                        palette["keyframe_scale_factor"] = max(0.25, min(4.0, factor))
                        scale_found = True
                        break
                except (TypeError, ValueError, OverflowError, AttributeError, ReferenceError):
                    continue
            if scale_found:
                break
        for key_id, _label, _icon, passive_names, selected_names, _radius in _KEYFRAME_TYPE_DEFINITIONS:
            fallback = _DEFAULT_BLENDER_KEYFRAME_COLORS[key_id]
            passive = _theme_color(
                animation_owners,
                (*passive_names, "keyframe"),
                fallback["passive"],
            )
            selected = _theme_color(
                animation_owners,
                (*selected_names, "keyframe_selected", *passive_names),
                fallback["selected"],
            )
            palette["keyframe_types"][key_id] = {"passive": passive, "selected": selected}
    except FBP_DATA_ERRORS:
        pass
    regular = palette["keyframe_types"].get("KEYFRAME", _DEFAULT_BLENDER_KEYFRAME_COLORS["KEYFRAME"])
    palette["keyframe_passive"] = regular["passive"]
    palette["keyframe_selected"] = regular["selected"]
    return palette


def _diamond_triangles(x, y, radius):
    x = float(x)
    y = float(y)
    radius = max(1.0, float(radius))
    return (
        (x, y + radius), (x + radius, y), (x, y - radius),
        (x, y + radius), (x, y - radius), (x - radius, y),
    )


def _diamond_lines(x, y, radius):
    x = float(x)
    y = float(y)
    radius = max(1.0, float(radius))
    top = (x, y + radius)
    right = (x + radius, y)
    bottom = (x, y - radius)
    left = (x - radius, y)
    return (top, right, right, bottom, bottom, left, left, top)


def viewport_background_color(context):
    try:
        shading = getattr(getattr(context, "space_data", None), "shading", None)
        background_type = str(getattr(shading, "background_type", "THEME") or "THEME")
        if background_type == "VIEWPORT":
            return _rgb(getattr(shading, "background_color", (0.12, 0.12, 0.12)))
        if background_type == "WORLD":
            world = getattr(getattr(context, "scene", None), "world", None)
            if world is not None:
                return _rgb(getattr(world, "color", (0.05, 0.05, 0.05)))
        themes = getattr(getattr(context, "preferences", None), "themes", None)
        theme = themes[0] if themes else None
        space = getattr(getattr(theme, "view_3d", None), "space", None)
        gradients = getattr(space, "gradients", None)
        high = _rgb(getattr(gradients, "high_gradient", (0.12, 0.12, 0.12)))
        low = _rgb(getattr(gradients, "low_gradient", high), high)
        return tuple((high[index] + low[index]) * 0.5 for index in range(3))
    except FBP_DATA_ERRORS:
        return (0.12, 0.12, 0.12)


def inverted_rgb(color):
    """Return the literal channel-wise inverse of an RGB color."""
    red, green, blue = _rgb(color)
    return (1.0 - red, 1.0 - green, 1.0 - blue)


def _apply_inverted_scrub_ink(target, context):
    """Use transparent slider chrome with ink inverted from the Viewport."""
    inverse = inverted_rgb(viewport_background_color(context))
    target._theme_style = "INVERT"
    target._surface_color = (0.0, 0.0, 0.0, 0.0)
    target._line_color = (*inverse, 1.0)
    target._frame_tick_color = (*inverse, 0.58)
    target._major_tick_color = (*inverse, 1.0)
    target._second_tick_color = (*inverse, 1.0)
    target._text_color = (*inverse, 1.0)
    return inverse


def contrast_palette(background_rgb):
    red, green, blue = _rgb(background_rgb)
    luminance = (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)
    if luminance >= 0.52:
        return {
            "foreground": (0.035, 0.035, 0.035, 0.98),
            "secondary": (0.10, 0.10, 0.10, 0.78),
            "accent": (0.08, 0.28, 0.82, 1.0),
            "keyframe": (0.78, 0.22, 0.05, 1.0),
        }
    return {
        "foreground": (0.97, 0.97, 0.97, 0.98),
        "secondary": (0.88, 0.88, 0.88, 0.80),
        "accent": (0.42, 0.68, 1.0, 1.0),
        "keyframe": (1.0, 0.55, 0.16, 1.0),
    }


def scene_frame_bounds(scene):
    _enabled, minimum, maximum = preview_range_signature(scene)
    return minimum, maximum


def scrub_display_range(scene, center_frame, visible_count):
    """Return an inclusive display range containing at most ``visible_count`` frames.

    The preference now means the total number of visible frames, not a radius
    applied twice around the current frame. Near scene boundaries the window is
    shifted, rather than shortened, whenever enough frames remain available.
    """
    minimum, maximum = scene_frame_bounds(scene)
    try:
        center = max(float(minimum), min(float(maximum), float(center_frame)))
        scene_count = max(1, int(maximum) - int(minimum) + 1)
        count = max(1, min(scene_count, int(round(float(visible_count)))))
    except (TypeError, ValueError, OverflowError):
        return int(minimum), int(minimum)
    left = int(math.floor(center - (count - 1) * 0.5))
    right = left + count - 1
    if left < minimum:
        right += int(minimum - left)
        left = int(minimum)
    if right > maximum:
        left -= int(right - maximum)
        right = int(maximum)
    left = max(int(minimum), int(left))
    right = min(int(maximum), max(left, int(right)))
    return left, right

def continuous_scrub_offset(delta_pixels, half_extent, maximum_range):
    """Map cursor motion continuously to an integer frame offset."""
    try:
        delta = float(delta_pixels)
        extent = max(1.0, float(half_extent))
        maximum = max(1, int(maximum_range))
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(delta) or not math.isfinite(extent):
        return 0
    normalized = max(-1.0, min(1.0, delta / extent))
    return max(-maximum, min(maximum, int(round(normalized * maximum))))


def scrub_overlay_layout(region_or_width, height=None, *, position="BOTTOM", vertical=None, ui_scale=1.0, length_ratio=0.84, edge_offset=42.0):
    """Return an axis layout on any edge of the active Viewport."""
    if height is None:
        width = float(getattr(region_or_width, "width", 1.0) or 1.0)
        height_value = float(getattr(region_or_width, "height", 1.0) or 1.0)
    else:
        width = float(region_or_width or 1.0)
        height_value = float(height or 1.0)
    scale = max(0.5, float(ui_scale))
    margin = _OVERLAY_MARGIN_PX * scale
    ratio = max(0.2, min(1.0, float(length_ratio)))
    offset = max(margin, float(edge_offset) * scale)
    position = str(position or "BOTTOM").upper()
    if vertical is not None:
        position = "LEFT" if bool(vertical) else "BOTTOM"
    vertical = position in {"LEFT", "RIGHT"}
    if vertical:
        target_length = max(1.0, height_value * ratio)
        y0 = max(margin, (height_value - target_length) * 0.5)
        y1 = min(height_value - margin, y0 + target_length)
        x = offset if position == "LEFT" else width - offset
        x = min(max(margin, x), max(margin, width - margin))
        return {"vertical": True, "position": position, "x": x, "y0": y0, "y1": y1,
                "length": max(1.0, y1-y0), "half_extent": max(1.0, (y1-y0)*0.5)}
    target_length = max(1.0, width * ratio)
    x0 = max(margin, (width - target_length) * 0.5)
    x1 = min(width - margin, x0 + target_length)
    y = offset if position == "BOTTOM" else height_value - offset
    y = min(max(margin, y), max(margin, height_value - margin))
    return {"vertical": False, "position": position, "x0": x0, "x1": x1, "y": y,
            "length": max(1.0, x1-x0), "half_extent": max(1.0, (x1-x0)*0.5)}


def _scrub_layout_for_state(state, region):
    layout = scrub_overlay_layout(
        region,
        position=state._position,
        ui_scale=state._ui_scale,
        length_ratio=state._length_ratio,
        edge_offset=state._edge_offset,
    )
    try:
        offset = float(getattr(state, "_magnetic_offset", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError, AttributeError, ReferenceError):
        offset = 0.0
    if not math.isfinite(offset) or abs(offset) <= _MAGNET_EPSILON_PX:
        return layout
    scale = max(0.5, float(getattr(state, "_ui_scale", 1.0) or 1.0))
    margin = _OVERLAY_MARGIN_PX * scale
    if layout["vertical"]:
        width = max(1.0, float(getattr(region, "width", 1.0) or 1.0))
        layout["x"] = min(
            max(margin, float(layout["x"]) + offset),
            max(margin, width - margin),
        )
    else:
        height = max(1.0, float(getattr(region, "height", 1.0) or 1.0))
        layout["y"] = min(
            max(margin, float(layout["y"]) + offset),
            max(margin, height - margin),
        )
    return layout


def _scrub_frame_position(frame, left, right, layout, *, invert_vertical=False):
    span = max(1.0, float(right - left))
    factor = max(0.0, min(1.0, float(frame - left) / span))
    if layout["vertical"]:
        if invert_vertical:
            factor = 1.0 - factor
        return float(layout["x"]), float(layout["y0"]) + factor * float(layout["length"])
    return float(layout["x0"]) + factor * float(layout["length"]), float(layout["y"])


def cursor_near_scrub_axis(mouse_x, mouse_y, layout, *, capture_px=28.0):
    """Return True when the cursor is close enough to use direct axis mapping."""
    try:
        x = float(mouse_x)
        y = float(mouse_y)
        capture = max(1.0, float(capture_px))
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(x) or not math.isfinite(y) or not math.isfinite(capture):
        return False
    if bool(layout.get("vertical", False)):
        axis_x = float(layout["x"])
        low = float(layout["y0"]) - capture
        high = float(layout["y1"]) + capture
        return abs(x - axis_x) <= capture and low <= y <= high
    axis_y = float(layout["y"])
    low = float(layout["x0"]) - capture
    high = float(layout["x1"]) + capture
    return abs(y - axis_y) <= capture and low <= x <= high


def magnetic_scrub_axis_offset(
    mouse_x,
    mouse_y,
    layout,
    *,
    enabled=True,
    capture_px=96.0,
    strength=1.0,
    inner_ratio=_MAGNET_INNER_RATIO,
):
    """Return the perpendicular axis offset used by the mouse magnet.

    The bar remains fixed outside ``capture_px``. Inside the outer band it
    eases toward the cursor, then follows it exactly in the inner band. The
    returned value is relative to the configured static axis, which keeps the
    calculation stable instead of feeding the already-moved bar back into the
    next proximity test.
    """
    if not bool(enabled):
        return 0.0
    try:
        x = float(mouse_x)
        y = float(mouse_y)
        capture = max(1.0, float(capture_px))
        power = max(0.0, min(1.0, float(strength)))
        inner = max(0.0, min(0.95, float(inner_ratio))) * capture
        vertical = bool(layout.get("vertical", False))
        if vertical:
            base = float(layout["x"])
            along = y
            low = float(layout["y0"]) - capture
            high = float(layout["y1"]) + capture
            delta = x - base
        else:
            base = float(layout["y"])
            along = x
            low = float(layout["x0"]) - capture
            high = float(layout["x1"]) + capture
            delta = y - base
    except (TypeError, ValueError, OverflowError, KeyError, AttributeError):
        return 0.0
    values = (x, y, capture, power, inner, base, along, low, high, delta)
    if not all(math.isfinite(value) for value in values):
        return 0.0
    if power <= 0.0 or along < low or along > high:
        return 0.0
    distance = abs(delta)
    if distance >= capture:
        return 0.0
    if distance <= inner or capture <= inner + 1.0e-6:
        factor = 1.0
    else:
        factor = (capture - distance) / (capture - inner)
        factor = max(0.0, min(1.0, factor))
        factor = factor * factor * (3.0 - 2.0 * factor)
    return float(delta) * factor * power


def direct_scrub_mapping_factor(
    mouse_x,
    mouse_y,
    layout,
    *,
    capture_px=96.0,
    inner_px=_DIRECT_SCRUB_INNER_PX,
    strength=1.0,
):
    """Blend relative scrubbing into exact cursor mapping near the axis.

    Outside the magnetic band the result is zero. Inside the narrow inner band
    it is always one, so the playhead follows the mouse exactly. Strength only
    affects the transitional outer band.
    """
    try:
        x = float(mouse_x)
        y = float(mouse_y)
        capture = max(1.0, float(capture_px))
        inner = max(1.0, min(capture, float(inner_px)))
        power = max(0.0, min(1.0, float(strength)))
        vertical = bool(layout.get("vertical", False))
        if vertical:
            distance = abs(x - float(layout["x"]))
            along = y
            low = float(layout["y0"]) - capture
            high = float(layout["y1"]) + capture
        else:
            distance = abs(y - float(layout["y"]))
            along = x
            low = float(layout["x0"]) - capture
            high = float(layout["x1"]) + capture
    except (TypeError, ValueError, OverflowError, KeyError, AttributeError):
        return 0.0
    if not all(math.isfinite(value) for value in (x, y, capture, inner, power, distance, along, low, high)):
        return 0.0
    if along < low or along > high or distance >= capture:
        return 0.0
    if distance <= inner:
        return 1.0
    if power <= 0.0:
        return 0.0
    factor = (capture - distance) / max(1.0e-6, capture - inner)
    factor = max(0.0, min(1.0, factor))
    factor = factor * factor * (3.0 - 2.0 * factor)
    return factor * power


def _grease_pencil_onion_settings(context, obj, keyframe_numbers=()):
    """Return display-ready onion ranges and colors for a GP object."""
    if not _is_live_grease_pencil_object(obj):
        return None
    data = getattr(obj, "data", None)
    if data is None:
        return None
    try:
        mode = str(getattr(data, "onion_mode", "ABSOLUTE") or "ABSOLUTE").upper()
        if mode == "SELECTED":
            return None
        before = max(0, min(120, int(getattr(data, "ghost_before_range", 0))))
        after = max(0, min(120, int(getattr(data, "ghost_after_range", 0))))
        opacity = max(0.05, min(0.65, float(getattr(data, "onion_factor", 0.5)) * 0.72))
        custom = bool(getattr(data, "use_ghost_custom_colors", False))
    except FBP_DATA_ERRORS:
        return None
    if custom:
        before_color = _rgba(getattr(data, "before_color", (0.15, 0.42, 0.14)), (0.15, 0.42, 0.14, opacity), alpha=opacity)
        after_color = _rgba(getattr(data, "after_color", (0.13, 0.08, 0.53)), (0.13, 0.08, 0.53, opacity), alpha=opacity)
    else:
        theme_view = None
        try:
            themes = getattr(getattr(context, "preferences", None), "themes", None)
            theme = themes[0] if themes else None
            theme_view = getattr(theme, "view_3d", None)
        except FBP_DATA_ERRORS:
            theme_view = None
        before_color = _theme_color(theme_view, ("before_current_frame",), (0.15, 0.42, 0.14, opacity), alpha=opacity)
        after_color = _theme_color(theme_view, ("after_current_frame",), (0.13, 0.08, 0.53, opacity), alpha=opacity)
    return {
        "data": data,
        "mode": mode,
        "before": before,
        "after": after,
        "before_color": before_color,
        "after_color": after_color,
        "keyframes": tuple(sorted({int(value) for value in keyframe_numbers})),
    }


def _onion_endpoint_frame(current_frame, amount, side, mode, keyframes):
    current = int(current_frame)
    count = max(0, int(amount))
    direction = -1 if str(side).upper() == "BEFORE" else 1
    if count <= 0:
        return current
    if str(mode or "ABSOLUTE").upper() != "RELATIVE":
        return current + direction * count
    values = tuple(int(value) for value in keyframes)
    if direction < 0:
        candidates = values[:bisect_left(values, current)]
        return candidates[max(0, len(candidates) - count)] if candidates else current - count
    candidates = values[bisect_right(values, current):]
    return candidates[min(len(candidates) - 1, count - 1)] if candidates else current + count


def _onion_amount_from_frame(current_frame, target_frame, side, mode, keyframes):
    current = int(current_frame)
    target = int(round(float(target_frame)))
    before = str(side).upper() == "BEFORE"
    if before:
        target = min(current, target)
    else:
        target = max(current, target)
    if str(mode or "ABSOLUTE").upper() != "RELATIVE":
        return max(0, min(120, abs(target - current)))
    values = tuple(int(value) for value in keyframes)
    if before:
        return max(0, min(120, bisect_left(values, current) - bisect_left(values, target)))
    return max(0, min(120, bisect_right(values, target) - bisect_right(values, current)))


def _marker_pointer(marker):
    try:
        return int(marker.as_pointer())
    except FBP_DATA_ERRORS:
        return 0


def _bookmark_label_from_name(name):
    label = str(name or "").strip()
    for prefix in _LEGACY_BOOKMARK_PREFIXES:
        if label.startswith(prefix):
            label = label[len(prefix):].strip()
            break
    return label or "Bookmark"


def _bookmark_native_name(label):
    return f"{_BOOKMARK_PREFIX}{_bookmark_label_from_name(label)}"


def _alphabetic_bookmark_label(index):
    """Return spreadsheet-style bookmark labels: A..Z, AA..AZ, BA..."""
    try:
        value = max(0, int(index))
    except (TypeError, ValueError, OverflowError):
        value = 0
    label = ""
    while True:
        value, remainder = divmod(value, 26)
        label = chr(ord("A") + remainder) + label
        if value == 0:
            return label
        value -= 1


def _next_bookmark_default_label(scene):
    """Return the first unused alphabetic name for a new Scene bookmark."""
    used = {
        str(record.get("name") or "").strip().upper()
        for record in scrub_bookmark_records(scene)
    }
    for index in range(4096):
        candidate = _alphabetic_bookmark_label(index)
        if candidate not in used:
            return candidate
    return f"B{len(used) + 1}"


def _bookmark_color_tag(value):
    identifier = str(value or _BOOKMARK_DEFAULT_COLOR).upper()
    return identifier if identifier in _BOOKMARK_COLORS else _BOOKMARK_DEFAULT_COLOR


def _bookmark_color(value, *, selected=False):
    base = _BOOKMARK_COLORS[_bookmark_color_tag(value)]
    if not selected:
        return base
    return tuple(min(1.0, channel * 0.62 + 0.38) for channel in base[:3]) + (1.0,)


def _load_bookmark_state(scene):
    if scene is None:
        return []
    try:
        raw = scene.get(_BOOKMARK_STATE_KEY, "")
    except FBP_DATA_ERRORS:
        raw = ""
    if not raw:
        return []
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    result = []
    seen = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("uid") or "").strip() or uuid.uuid4().hex
        if uid in seen:
            uid = uuid.uuid4().hex
        seen.add(uid)
        try:
            frame = int(item.get("frame", 0))
        except (TypeError, ValueError, OverflowError):
            frame = 0
        label = _bookmark_label_from_name(item.get("label") or item.get("marker_name") or "Bookmark")
        result.append({
            "uid": uid,
            "label": label,
            "color_tag": _bookmark_color_tag(item.get("color_tag")),
            "marker_name": str(item.get("marker_name") or _bookmark_native_name(label)),
            "frame": frame,
        })
    return result


def _save_bookmark_state(scene, entries):
    if scene is None:
        return False
    payload = []
    for item in tuple(entries or ()):
        if not isinstance(item, dict):
            continue
        payload.append({
            "uid": str(item.get("uid") or uuid.uuid4().hex),
            "label": _bookmark_label_from_name(item.get("label") or "Bookmark"),
            "color_tag": _bookmark_color_tag(item.get("color_tag")),
            "marker_name": str(item.get("marker_name") or _bookmark_native_name(item.get("label"))),
            "frame": int(item.get("frame", 0)),
        })
    try:
        scene[_BOOKMARK_STATE_KEY] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not save Scrub Bar bookmark metadata", exc)
        return False


def _marker_name_has_bookmark_prefix(marker):
    try:
        name = str(getattr(marker, "name", "") or "").strip()
    except FBP_DATA_ERRORS:
        return False
    return any(name.startswith(prefix) for prefix in _LEGACY_BOOKMARK_PREFIXES)


def _new_bookmark_entry(marker, *, label=None, color_tag=_BOOKMARK_DEFAULT_COLOR):
    frame = int(getattr(marker, "frame", 0) or 0)
    label = _bookmark_label_from_name(label or getattr(marker, "name", "") or f"Bookmark {frame}")
    return {
        "uid": uuid.uuid4().hex,
        "label": label,
        "color_tag": _bookmark_color_tag(color_tag),
        "marker_name": _bookmark_native_name(label),
        "frame": frame,
    }


def reconcile_scrub_bookmarks(scene):
    """Synchronize durable FBP bookmark metadata with native Timeline markers.

    Native Timeline rename/move/duplicate/delete operations remain authoritative.
    The metadata stores only the FBP color tag and durable identity; the visible
    marker name is normalized back to ``✦ - Name`` after native renaming.
    """
    markers = tuple(getattr(scene, "timeline_markers", ()) or ()) if scene is not None else ()
    entries = _load_bookmark_state(scene)
    used = set()
    matched = []
    changed = False

    marker_by_pointer = {_marker_pointer(marker): marker for marker in markers if _marker_pointer(marker)}
    for entry in entries:
        uid = str(entry.get("uid") or "")
        marker = None
        for pointer, mapped_uid in tuple(_BOOKMARK_POINTER_UIDS.items()):
            if mapped_uid == uid and pointer in marker_by_pointer:
                marker = marker_by_pointer[pointer]
                break
        if marker is None:
            exact = [
                candidate for candidate in markers
                if _marker_pointer(candidate) not in used
                and int(getattr(candidate, "frame", 0) or 0) == int(entry.get("frame", 0))
                and str(getattr(candidate, "name", "") or "") == str(entry.get("marker_name") or "")
            ]
            marker = exact[0] if exact else None
        if marker is None:
            same_name = [
                candidate for candidate in markers
                if _marker_pointer(candidate) not in used
                and str(getattr(candidate, "name", "") or "") == str(entry.get("marker_name") or "")
            ]
            marker = same_name[0] if len(same_name) == 1 else None
        if marker is None:
            same_frame = [
                candidate for candidate in markers
                if _marker_pointer(candidate) not in used
                and int(getattr(candidate, "frame", 0) or 0) == int(entry.get("frame", 0))
            ]
            selected = [candidate for candidate in same_frame if bool(getattr(candidate, "select", False))]
            marker = selected[0] if len(selected) == 1 else (same_frame[0] if len(same_frame) == 1 else None)
        if marker is None:
            changed = True
            continue

        pointer = _marker_pointer(marker)
        used.add(pointer)
        _BOOKMARK_POINTER_UIDS[pointer] = uid
        native_label = _bookmark_label_from_name(getattr(marker, "name", ""))
        previous_name = str(entry.get("marker_name") or "")
        if str(getattr(marker, "name", "") or "") != previous_name:
            entry["label"] = native_label
            changed = True
        desired_name = _bookmark_native_name(entry.get("label") or native_label)
        try:
            if str(marker.name) != desired_name:
                marker.name = desired_name
        except FBP_DATA_ERRORS:
            pass
        frame = int(getattr(marker, "frame", 0) or 0)
        if entry.get("marker_name") != desired_name or int(entry.get("frame", 0)) != frame:
            changed = True
        entry["label"] = _bookmark_label_from_name(entry.get("label") or native_label)
        entry["marker_name"] = desired_name
        entry["frame"] = frame
        entry["color_tag"] = _bookmark_color_tag(entry.get("color_tag"))
        matched.append((entry, marker))

    for marker in markers:
        pointer = _marker_pointer(marker)
        if pointer in used or not _marker_name_has_bookmark_prefix(marker):
            continue
        entry = _new_bookmark_entry(marker)
        desired_name = _bookmark_native_name(entry["label"])
        try:
            marker.name = desired_name
        except FBP_DATA_ERRORS:
            pass
        entry["marker_name"] = desired_name
        _BOOKMARK_POINTER_UIDS[pointer] = entry["uid"]
        used.add(pointer)
        matched.append((entry, marker))
        changed = True

    valid_pointers = {_marker_pointer(marker) for _entry, marker in matched}
    for pointer in tuple(_BOOKMARK_POINTER_UIDS):
        if pointer not in valid_pointers:
            _BOOKMARK_POINTER_UIDS.pop(pointer, None)

    normalized = [entry for entry, _marker in matched]
    if changed or normalized != entries:
        _save_bookmark_state(scene, normalized)
    return tuple(matched)


def is_scrub_bookmark(marker, scene=None):
    pointer = _marker_pointer(marker)
    if pointer and pointer in _BOOKMARK_POINTER_UIDS:
        return True
    if scene is not None:
        return any(candidate is marker for _entry, candidate in reconcile_scrub_bookmarks(scene))
    return _marker_name_has_bookmark_prefix(marker)


def scrub_bookmark_records(scene):
    records = []
    for entry, marker in reconcile_scrub_bookmarks(scene):
        records.append({
            "uid": str(entry.get("uid") or ""),
            "marker": marker,
            "frame": int(getattr(marker, "frame", 0) or 0),
            "name": _bookmark_label_from_name(entry.get("label") or getattr(marker, "name", "")),
            "color_tag": _bookmark_color_tag(entry.get("color_tag")),
            "selected": bool(getattr(marker, "select", False)),
        })
    return tuple(sorted(records, key=lambda item: (item["frame"], item["name"].casefold(), item["uid"])))


def scrub_native_marker_records(scene):
    bookmark_pointers = {_marker_pointer(record["marker"]) for record in scrub_bookmark_records(scene)}
    records = []
    try:
        for marker in tuple(getattr(scene, "timeline_markers", ()) or ()):
            if _marker_pointer(marker) in bookmark_pointers:
                continue
            records.append({
                "marker": marker,
                "frame": int(getattr(marker, "frame", 0) or 0),
                "name": str(getattr(marker, "name", "") or ""),
                "selected": bool(getattr(marker, "select", False)),
            })
    except FBP_DATA_ERRORS:
        return ()
    return tuple(sorted(records, key=lambda item: (item["frame"], item["name"].casefold())))


def selected_scrub_bookmark_records(scene):
    return tuple(record for record in scrub_bookmark_records(scene) if record["selected"])


def _bookmark_record_by_uid(scene, uid):
    target = str(uid or "")
    return next((record for record in scrub_bookmark_records(scene) if record["uid"] == target), None)


def _set_bookmark_color(scene, records, color_tag):
    identifiers = {str(record.get("uid") or "") for record in tuple(records or ())}
    if not identifiers:
        return False
    entries = _load_bookmark_state(scene)
    changed = False
    for entry in entries:
        if str(entry.get("uid") or "") in identifiers:
            value = _bookmark_color_tag(color_tag)
            if entry.get("color_tag") != value:
                entry["color_tag"] = value
                changed = True
    if changed:
        _save_bookmark_state(scene, entries)
    return changed


def _delete_bookmark_records(scene, records):
    markers = getattr(scene, "timeline_markers", None) if scene is not None else None
    targets = tuple(records or ())
    if markers is None or not targets:
        return 0
    removed = 0
    for record in targets:
        marker = record.get("marker") if isinstance(record, dict) else None
        if marker is None:
            continue
        try:
            markers.remove(marker)
            removed += 1
        except FBP_DATA_ERRORS:
            continue
    reconcile_scrub_bookmarks(scene)
    return removed


def scrub_magnet_should_release(event_type, *, event_in_window, cursor_in_owned_window):
    """Return whether the persistent magnet should ease back to its base axis.

    TIMER events are not reliable indicators of the active region: Blender may
    provide no region (or a sidebar/header region) even while the cursor remains
    inside the owning Viewport. Mouse events update ``cursor_in_owned_window``;
    timer events must use that remembered state.
    """
    if str(event_type or "").upper() == "TIMER":
        return not bool(cursor_in_owned_window)
    return not bool(event_in_window)


def smooth_scrub_magnet_offset(current, target, smoothing, elapsed, *, interval=_TIMER_INTERVAL):
    """Advance the magnetic offset with frame-rate-independent easing."""
    try:
        current_value = float(current)
        target_value = float(target)
        response = max(0.01, min(1.0, float(smoothing)))
        seconds = max(0.0, min(1.0, float(elapsed)))
        base_interval = max(1.0e-4, float(interval))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    values = (current_value, target_value, response, seconds, base_interval)
    if not all(math.isfinite(value) for value in values):
        return 0.0
    if abs(target_value - current_value) <= _MAGNET_EPSILON_PX:
        return target_value
    steps = max(1.0, seconds / base_interval)
    alpha = 1.0 - math.pow(1.0 - response, steps)
    return current_value + (target_value - current_value) * max(0.0, min(1.0, alpha))


def cursor_in_scrub_bounds(mouse_x, mouse_y, bounds, *, padding=0.0):
    """Return True inside a rectangular slider hit region."""
    try:
        x = float(mouse_x)
        y = float(mouse_y)
        x0, y0, x1, y1 = (float(value) for value in bounds)
        pad = max(0.0, float(padding))
    except (TypeError, ValueError, OverflowError):
        return False
    return (
        min(x0, x1) - pad <= x <= max(x0, x1) + pad
        and min(y0, y1) - pad <= y <= max(y0, y1) + pad
    )


def timeline_cursor_frame(mouse_x, mouse_y, left, right, layout, *, invert_vertical=False):
    """Project the cursor onto the visible scrub axis and return its frame value."""
    try:
        minimum = float(left)
        maximum = float(right)
        if maximum < minimum:
            minimum, maximum = maximum, minimum
        if bool(layout.get("vertical", False)):
            length = max(1.0, float(layout["length"]))
            factor = (float(mouse_y) - float(layout["y0"])) / length
            if bool(invert_vertical):
                factor = 1.0 - factor
        else:
            length = max(1.0, float(layout["length"]))
            factor = (float(mouse_x) - float(layout["x0"])) / length
    except (TypeError, ValueError, OverflowError, KeyError):
        return float(left)
    factor = max(0.0, min(1.0, factor))
    return minimum + factor * max(0.0, maximum - minimum)


def _nearest_sorted_value(values, target):
    try:
        sequence = tuple(values or ())
    except TypeError:
        return None
    if not sequence:
        return None
    index = bisect_left(sequence, target)
    candidates = []
    if index < len(sequence):
        candidates.append(sequence[index])
    if index > 0:
        candidates.append(sequence[index - 1])
    return min(candidates, key=lambda value: abs(float(value) - float(target))) if candidates else None


def marker_snap_frames(scene):
    frames = set()
    try:
        for marker in tuple(getattr(scene, "timeline_markers", ()) or ()):
            frames.add(float(getattr(marker, "frame", 0.0)))
    except FBP_DATA_ERRORS:
        pass
    return tuple(sorted(frames))


def strip_snap_frames(scene, obj=None):
    """Collect Sequence Editor and active-object NLA strip boundaries."""
    frames = set()
    try:
        sequence_editor = getattr(scene, "sequence_editor", None)
        collections = (
            getattr(sequence_editor, "strips", None),
            getattr(sequence_editor, "sequences_all", None),
            getattr(sequence_editor, "sequences", None),
        )
        strips = next((collection for collection in collections if collection is not None), ())
        for strip in tuple(strips or ()):
            for name in ("frame_final_start", "frame_final_end", "frame_start", "frame_end"):
                value = getattr(strip, name, None)
                if value is not None:
                    frames.add(float(value))
    except FBP_DATA_ERRORS:
        pass
    try:
        animation_data = getattr(obj, "animation_data", None)
        for track in tuple(getattr(animation_data, "nla_tracks", ()) or ()):
            for strip in tuple(getattr(track, "strips", ()) or ()):
                frames.add(float(getattr(strip, "frame_start", 0.0)))
                frames.add(float(getattr(strip, "frame_end", 0.0)))
    except FBP_DATA_ERRORS:
        pass
    return tuple(sorted(frames))


def timeline_keyframe_frames(scene, grease_pencil_object=None):
    """Collect scene animation keys for Timeline-compatible KEY snapping.

    The floating timeline remains useful with no Grease Pencil object, so KEY
    snapping cannot be limited to drawings on one GP layer. Blender 5.2 stores
    Action curves in channel bags; ``fbp_action_fcurves`` resolves those safely.
    """
    frames = set()
    if _is_live_grease_pencil_object(grease_pencil_object):
        try:
            frames.update(
                float(record[0])
                for record in grease_pencil_keyframe_records(
                    grease_pencil_object
                )
            )
        except FBP_DATA_ERRORS:
            pass

    owners = []
    seen = set()

    def add_owner(owner):
        if owner is None:
            return
        try:
            key = int(owner.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(owner)
        if key in seen:
            return
        seen.add(key)
        owners.append(owner)

    add_owner(scene)
    add_owner(getattr(scene, "world", None) if scene is not None else None)
    try:
        objects = tuple(getattr(scene, "objects", ()) or ())
    except FBP_DATA_ERRORS:
        objects = ()
    for obj in objects:
        add_owner(obj)
        data = getattr(obj, "data", None)
        add_owner(data)
        add_owner(getattr(data, "shape_keys", None) if data is not None else None)
        try:
            for material in tuple(
                getattr(getattr(obj, "data", None), "materials", ()) or ()
            ):
                add_owner(material)
                add_owner(getattr(material, "node_tree", None))
        except FBP_DATA_ERRORS:
            pass

    for owner in owners:
        try:
            curves = tuple(fbp_action_fcurves(owner) or ())
        except FBP_DATA_ERRORS:
            curves = ()
        for curve in curves:
            try:
                frames.update(
                    float(point.co.x)
                    for point in tuple(
                        getattr(curve, "keyframe_points", ()) or ()
                    )
                )
            except FBP_DATA_ERRORS:
                continue
    return tuple(sorted(frames))


def snap_frame_value(raw_frame, scene, snap_settings, keyframes=(), strips=(), pixels_per_frame=1.0, markers=None):
    """Apply native playhead snap targets inside Blender's pixel threshold."""
    try:
        raw = float(raw_frame)
    except (TypeError, ValueError, OverflowError):
        return 0
    minimum, maximum = scene_frame_bounds(scene)
    raw = max(float(minimum), min(float(maximum), raw))
    if not bool((snap_settings or {}).get("enabled", False)):
        return max(minimum, min(maximum, int(round(raw))))

    targets = normalize_playhead_snap_targets((snap_settings or {}).get("targets", ()))
    candidates = []
    if "FRAME" in targets:
        step = max(1, int((snap_settings or {}).get("frame_step", 2)))
        candidates.append(float(round(raw / step) * step))
    if "SECOND" in targets:
        step_seconds = max(1, int((snap_settings or {}).get("second_step", 1)))
        interval = scene_fps(scene) * step_seconds
        candidates.append(float(round(raw / interval) * interval))
    if "MARKER" in targets:
        marker_values = marker_snap_frames(scene) if markers is None else markers
        marker = _nearest_sorted_value(marker_values, raw)
        if marker is not None:
            candidates.append(float(marker))
    if "KEY" in targets:
        key = _nearest_sorted_value(tuple(sorted(float(value) for value in keyframes)), raw)
        if key is not None:
            candidates.append(float(key))
    if "STRIP" in targets:
        strip = _nearest_sorted_value(tuple(sorted(float(value) for value in strips)), raw)
        if strip is not None:
            candidates.append(float(strip))

    candidates = [max(float(minimum), min(float(maximum), value)) for value in candidates]
    if not candidates:
        return max(minimum, min(maximum, int(round(raw))))
    nearest = min(candidates, key=lambda value: abs(value - raw))
    try:
        px_per_frame = max(1.0e-6, float(pixels_per_frame))
        threshold_frames = max(0.0, float((snap_settings or {}).get("distance_px", 20.0))) / px_per_frame
    except (TypeError, ValueError, OverflowError):
        threshold_frames = 0.0
    if abs(nearest - raw) <= threshold_frames:
        raw = nearest
    return max(minimum, min(maximum, int(round(raw))))


def relative_scrub_target(
    origin_frame,
    pixel_delta,
    scrub_radius,
    half_extent,
    *,
    sensitivity=1.0,
    shift=False,
    slow_factor=0.2,
    negative_radius=None,
    positive_radius=None,
):
    """Map relative mouse motion to a frame without using cursor position.

    ``negative_radius`` and ``positive_radius`` allow asymmetric visible ranges.
    This matters near scene boundaries: with a visible range of 1-50 and the
    playhead at frame 1, moving to the far end must reach frame 50 instead of
    stopping at the old symmetric half-range around frame 25.
    """
    try:
        origin = float(origin_frame)
        delta = float(pixel_delta) * float(sensitivity)
        radius = max(1.0, float(scrub_radius))
        backward = radius if negative_radius is None else max(0.0, float(negative_radius))
        forward = radius if positive_radius is None else max(0.0, float(positive_radius))
        extent = max(1.0, float(half_extent))
        if not all(math.isfinite(value) for value in (origin, delta, radius, backward, forward, extent)):
            raise ValueError
        if shift:
            factor = max(0.02, min(1.0, float(slow_factor)))
            if not math.isfinite(factor):
                raise ValueError
            delta *= factor
        normalized = max(-1.0, min(1.0, delta / extent))
        span = forward if normalized >= 0.0 else backward
        return origin + normalized * span, delta
    except (TypeError, ValueError, OverflowError):
        try:
            return float(origin_frame), 0.0
        except (TypeError, ValueError, OverflowError):
            return 0.0, 0.0


def playhead_snap_label(settings, *, shift=False, ctrl=False, slow_factor=0.2):
    """Describe the effective scrub mode, including temporary modifiers."""
    if ctrl:
        label = f"{primary_modifier_name()} · Snap Keyframes"
    elif not bool((settings or {}).get("enabled", False)):
        label = "Snap Off"
    else:
        targets = normalize_playhead_snap_targets((settings or {}).get("targets", ()))
        labels = [_SNAP_TARGET_LABELS[target] for target in _SNAP_TARGET_ORDER if target in targets]
        label = "Snap · " + (" + ".join(labels) if labels else "Frames")
    if shift:
        try:
            factor = max(0.02, min(1.0, float(slow_factor)))
        except (TypeError, ValueError, OverflowError):
            factor = 0.2
        label += f" · Shift {factor:.2f}×"
    return label


def _is_live_grease_pencil_object(obj):
    if obj is None:
        return False
    try:
        return bool(
            str(getattr(obj, "type", "") or "") == "GREASEPENCIL"
            and getattr(obj, "data", None) is not None
        )
    except FBP_DATA_ERRORS:
        return False


def _is_view3d_context(context, *, require_window_region=False):
    try:
        area = getattr(context, "area", None)
        if area is None or str(getattr(area, "type", "") or "") != "VIEW_3D":
            return False
        if not require_window_region:
            return True
        return str(getattr(getattr(context, "region", None), "type", "") or "") == "WINDOW"
    except FBP_DATA_ERRORS:
        return False


def _scene_contains_object(scene, obj):
    if scene is None or not _is_live_grease_pencil_object(obj):
        return False
    try:
        objects = getattr(scene, "objects", None)
        name = str(getattr(obj, "name", "") or "")
        return bool(objects is not None and name and objects.get(name) is obj)
    except FBP_DATA_ERRORS:
        return False


def _scrub_area_pointer(context):
    try:
        area = getattr(context, "area", None)
        return int(area.as_pointer()) if area is not None else 0
    except FBP_DATA_ERRORS:
        return 0


def _scrub_binding_scene_name(context):
    try:
        scene = getattr(context, "scene", None)
        return str(getattr(scene, "name", "") or "") if scene is not None else ""
    except FBP_DATA_ERRORS:
        return ""


def _scrub_binding_keys(context, *, area_pointer=0):
    """Return area-local and scene fallback keys for persistent target memory."""
    scene_name = _scrub_binding_scene_name(context)
    if not scene_name:
        return ()
    pointer = int(area_pointer or _scrub_area_pointer(context) or 0)
    keys = []
    if pointer > 0:
        keys.append((pointer, scene_name))
    keys.append((0, scene_name))
    return tuple(keys)


def _trim_persistent_scrub_bindings():
    while len(_PERSISTENT_SCRUB_BINDINGS) > _MAX_PERSISTENT_SCRUB_BINDINGS:
        try:
            _PERSISTENT_SCRUB_BINDINGS.pop(next(iter(_PERSISTENT_SCRUB_BINDINGS)))
        except (StopIteration, KeyError):
            break


def _remember_persistent_scrub_binding(context, obj, *, area_pointer=0):
    if not _scene_contains_object(getattr(context, "scene", None), obj):
        return False
    keys = _scrub_binding_keys(context, area_pointer=area_pointer)
    if not keys:
        return False
    try:
        value = (
            str(getattr(obj, "name", "") or ""),
            str(getattr(getattr(obj, "data", None), "name", "") or ""),
        )
    except FBP_DATA_ERRORS:
        return False
    for key in keys:
        _PERSISTENT_SCRUB_BINDINGS.pop(key, None)
        _PERSISTENT_SCRUB_BINDINGS[key] = value
    _trim_persistent_scrub_bindings()
    return True


def _resolve_saved_scrub_binding(context):
    keys = _scrub_binding_keys(context)
    if not keys:
        return None
    scene = getattr(context, "scene", None)
    try:
        objects = tuple(getattr(scene, "objects", ()) or ())
    except FBP_DATA_ERRORS:
        return None
    for binding_key in keys:
        binding = _PERSISTENT_SCRUB_BINDINGS.get(binding_key)
        if not binding:
            continue
        object_name, data_name = binding
        data_candidate = None
        for candidate in objects:
            if not _is_live_grease_pencil_object(candidate):
                continue
            try:
                if object_name and str(getattr(candidate, "name", "") or "") == object_name:
                    _remember_persistent_scrub_binding(context, candidate)
                    return candidate
                if (
                    data_candidate is None
                    and data_name
                    and str(getattr(getattr(candidate, "data", None), "name", "") or "") == data_name
                ):
                    data_candidate = candidate
            except FBP_DATA_ERRORS:
                continue
        if data_candidate is not None:
            _remember_persistent_scrub_binding(context, data_candidate)
            return data_candidate
        _PERSISTENT_SCRUB_BINDINGS.pop(binding_key, None)
    return None


def _resolve_scrub_target_object(context, *, explicit_name=""):
    scene = getattr(context, "scene", None)
    explicit_name = str(explicit_name or "")
    if explicit_name:
        try:
            candidate = bpy.data.objects.get(explicit_name)
        except FBP_DATA_ERRORS:
            candidate = None
        if _scene_contains_object(scene, candidate):
            return candidate
    active = getattr(context, "object", None)
    if _scene_contains_object(scene, active):
        return active
    saved = _resolve_saved_scrub_binding(context)
    if saved is not None:
        return saved
    try:
        selected = tuple(getattr(context, "selected_objects", ()) or ())
    except FBP_DATA_ERRORS:
        selected = ()
    for candidate in selected:
        if _scene_contains_object(scene, candidate):
            return candidate
    try:
        for candidate in tuple(getattr(scene, "objects", ()) or ()):
            if _is_live_grease_pencil_object(candidate):
                return candidate
    except FBP_DATA_ERRORS:
        pass
    return None


def _scrub_target_object(context):
    active = _ACTIVE_OPERATOR
    if active is not None:
        try:
            if (
                int(getattr(active, "_area_pointer", 0) or 0) == _scrub_area_pointer(context)
                and _scene_contains_object(getattr(context, "scene", None), getattr(active, "_object", None))
            ):
                return active._object
        except FBP_DATA_ERRORS:
            pass
    return _resolve_scrub_target_object(context)


def is_persistent_scrub_active(context=None):
    active = _ACTIVE_OPERATOR
    if active is None or not bool(getattr(active, "_is_persistent", False)):
        return False
    if context is None:
        return True
    try:
        area = getattr(context, "area", None)
        return bool(area is not None and int(area.as_pointer()) == int(active._area_pointer))
    except FBP_DATA_ERRORS:
        return False


def persistent_scrub_session_valid(*, persistent, bound_object_valid, gp_context_valid):
    """Keep an area-level slider alive with or without a GP binding.

    ``bound_object_valid`` is also true for intentional timeline-only sessions.
    A real GP binding is resolved separately when drawing/key editing is used.
    """
    if not bool(bound_object_valid):
        return False
    return bool(persistent or gp_context_valid)


def _scrub_header_available(context):
    """Keep the Scrub Bar control available in every 3D View mode."""
    return _is_view3d_context(context)


def _tag_all_view3d_redraw():
    try:
        window_manager = bpy.context.window_manager
        for window in tuple(getattr(window_manager, "windows", ()) or ()):
            screen = getattr(window, "screen", None)
            for area in tuple(getattr(screen, "areas", ()) or ()):
                if str(getattr(area, "type", "") or "") == "VIEW_3D":
                    area.tag_redraw()
    except FBP_DATA_ERRORS:
        pass


def _draw_text(blf, text, x, y, size=13, color=(1.0, 1.0, 1.0, 1.0)):
    try:
        blf.size(0, int(size))
        blf.color(0, *color)
        blf.position(0, float(x), float(y), 0.0)
        blf.draw(0, str(text))
    except FBP_DATA_ERRORS:
        pass


def _draw_uniform_batch(shader, batch_for_shader, primitive, vertices, color):
    if not vertices:
        return
    batch = batch_for_shader(shader, primitive, {"pos": tuple(vertices)})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _append_circle_triangles(vertices, cx, cy, radius, *, segments=10):
    radius = max(0.25, float(radius))
    segments = max(6, int(segments))
    for index in range(segments):
        a0 = (math.tau * index) / segments
        a1 = (math.tau * (index + 1)) / segments
        vertices.extend(((cx, cy), (cx + math.cos(a0) * radius, cy + math.sin(a0) * radius), (cx + math.cos(a1) * radius, cy + math.sin(a1) * radius)))


def _append_rounded_segment(vertices, x0, y0, x1, y1, width):
    """Append a GPU triangle strip with circular caps."""
    width = max(0.5, float(width))
    radius = width * 0.5
    dx, dy = float(x1) - float(x0), float(y1) - float(y0)
    length = math.hypot(dx, dy)
    if length <= 1.0e-6:
        _append_circle_triangles(vertices, x0, y0, radius)
        return
    nx, ny = -dy / length * radius, dx / length * radius
    vertices.extend(((x0 + nx, y0 + ny), (x0 - nx, y0 - ny), (x1 - nx, y1 - ny),
                     (x0 + nx, y0 + ny), (x1 - nx, y1 - ny), (x1 + nx, y1 + ny)))
    _append_circle_triangles(vertices, x0, y0, radius)
    _append_circle_triangles(vertices, x1, y1, radius)


def _rounded_rect_triangles(x0, y0, x1, y1, radius):
    x0, x1 = sorted((float(x0), float(x1)))
    y0, y1 = sorted((float(y0), float(y1)))
    radius = max(0.0, min(float(radius), (x1 - x0) * 0.5, (y1 - y0) * 0.5))
    vertices = []
    # Central cross, then quarter-circle fans.
    vertices.extend(((x0 + radius, y0), (x1 - radius, y0), (x1 - radius, y1),
                     (x0 + radius, y0), (x1 - radius, y1), (x0 + radius, y1)))
    vertices.extend(((x0, y0 + radius), (x1, y0 + radius), (x1, y1 - radius),
                     (x0, y0 + radius), (x1, y1 - radius), (x0, y1 - radius)))
    corners = ((x0 + radius, y0 + radius, math.pi, math.pi * 1.5),
               (x1 - radius, y0 + radius, math.pi * 1.5, math.tau),
               (x1 - radius, y1 - radius, 0.0, math.pi * 0.5),
               (x0 + radius, y1 - radius, math.pi * 0.5, math.pi))
    segments = 6
    for cx, cy, start, end in corners:
        for index in range(segments):
            a0 = start + (end - start) * index / segments
            a1 = start + (end - start) * (index + 1) / segments
            vertices.extend(((cx, cy), (cx + math.cos(a0) * radius, cy + math.sin(a0) * radius), (cx + math.cos(a1) * radius, cy + math.sin(a1) * radius)))
    return vertices


def _keyframe_records_in_range(records, frame_numbers, minimum, maximum):
    left = bisect_left(frame_numbers, int(minimum))
    right = bisect_right(frame_numbers, int(maximum))
    return records[left:right]


def keyframe_radius(key_type, ui_scale, theme_scale):
    definition = _KEYFRAME_TYPE_BY_ID.get(_normalized_keyframe_type(key_type), _KEYFRAME_TYPE_BY_ID["KEYFRAME"])
    try:
        scale = max(0.5, float(ui_scale)) * max(0.25, float(theme_scale))
    except (TypeError, ValueError, OverflowError):
        scale = 1.0
    return max(2.0, 5.0 * scale * float(definition[5]))


class FBP_OT_GreasePencilFrameScrub(Operator):
    """Tap < to toggle the slider, or hold it for a momentary scrub."""

    bl_idname = "fbp.grease_pencil_frame_scrub"
    bl_label = "Grease Pencil Frame Scrub"
    bl_description = "In any 3D View mode, Tap < to toggle the Scrub Bar or hold < for momentary scrubbing"
    # The persistent listener must never own Blender's Undo transaction: GP
    # strokes pass through this modal operator and need to remain the newest
    # undo step. Key moves/duplicates push their own explicit checkpoints.
    bl_options = {"INTERNAL"}

    start_persistent: BoolProperty(
        name="Persistent",
        description="Keep the interactive Scrub Slider visible after invocation",
        default=False,
        options={"SKIP_SAVE"},
    )

    target_object_name: StringProperty(
        name="Grease Pencil Target",
        description="Grease Pencil object used by the Scrub Bar outside Grease Pencil modes",
        default="",
        options={"SKIP_SAVE", "HIDDEN"},
    )

    _draw_handle = None
    _timer = None
    _window_manager = None
    _window = None
    _workspace = None
    _screen = None
    _area = None
    _region = None
    _area_pointer = 0
    _region_pointer = 0
    _scene_pointer = 0
    _window_pointer = 0
    _workspace_pointer = 0
    _screen_pointer = 0
    _cleaned = False
    _session_start_frame = 0
    _origin_frame = 0
    _overflow_offset = 0
    _current_frame = 0
    _mouse_x = 0.0
    _mouse_y = 0.0
    _drag_anchor_x = 0.0
    _drag_anchor_y = 0.0
    _maximum_range = 50
    _vertical = True
    _position = "LEFT"
    _sensitivity = 2.0
    _slow_factor = 0.2
    _length_ratio = 0.5
    _edge_offset = 240.0
    _tick_scale = 0.5
    _line_width = 1.0
    _invert_vertical = False
    _shift_held = False
    _ctrl_held = False
    _line_color = (0.0, 0.0, 0.0, 1.0)
    _frame_tick_color = (0.0, 0.0, 0.0, 0.58)
    _major_tick_color = (0.0, 0.0, 0.0, 1.0)
    _second_tick_color = (0.0, 0.0, 0.0, 1.0)
    _text_color = (0.0, 0.0, 0.0, 1.0)
    _surface_color = (0.0, 0.0, 0.0, 0.0)
    _theme_style = "INVERT"
    _edge_direction = 0
    _edge_since = 0.0
    _edge_last_repeat = 0.0
    _activation_event_type = ""
    _has_frame_change = False
    _all_keyframes = ()
    _keyframe_records = ()
    _keyframe_record_numbers = ()
    _marker_frames = ()
    _strip_frames = ()
    _snap_settings = None
    _palette = None
    _ui_scale = 1.0
    _onion_skin_overlay = None
    _onion_skin_was_enabled = None
    _is_persistent = False
    _persistent_before_shortcut = False
    _shortcut_pending = False
    _shortcut_started = 0.0
    _shortcut_start_x = 0.0
    _shortcut_start_y = 0.0
    _shortcut_moved = False
    _shortcut_anchor_pending = False
    _view_center = 0.0
    _view_radius = 50
    _persistent_view_before = None
    _hold_center = 0.0
    _hold_radius = 50
    _interaction = ""
    _interaction_event_type = ""
    _interaction_start_x = 0.0
    _interaction_start_y = 0.0
    _interaction_start_frame = 0
    _interaction_start_center = 0.0
    _interaction_start_radius = 50
    _transform_sources = ()
    _transform_delta = 0
    _collision_stashes = ()
    _duplicate_pending = False
    _duplicate_sources = ()
    _preview_signature = None
    _show_info = False
    _hover_frame = None
    _cursor_label_bounds = None
    _cache_checked_at = 0.0
    _object = None
    _object_name = ""
    _object_data_name = ""
    _cursor_over_axis = False
    _cursor_kind = ""
    _magnetic_enabled = True
    _magnetic_distance = 96.0
    _magnetic_strength = 1.0
    _magnetic_smoothing = 0.22
    _magnetic_offset = 0.0
    _magnetic_target_offset = 0.0
    _magnetic_last_tick = 0.0
    _cursor_in_owned_window = False
    _shortcut_direct_factor = 0.0
    _shortcut_direct_locked = False
    _relative_anchor_frame = 0.0
    _onion_before_handle = None
    _onion_after_handle = None
    _bookmark_records = ()
    _native_marker_records = ()
    _bookmark_hit_records = ()
    _native_marker_hit_records = ()
    _hover_bookmark_uid = ""
    _bookmark_transform_sources = ()
    _bookmark_transform_created = ()
    _bookmark_transform_delta = 0
    _onion_drag_original = None

    @classmethod
    def poll(cls, context):
        return _is_view3d_context(context, require_window_region=True)

    def _owned_window_region(self):
        """Return the original Viewport WINDOW region even on TIMER events.

        Blender can dispatch modal TIMER events with ``context.region`` set to
        ``None`` or to a non-WINDOW region, especially outside GP modes. The
        Scrub Bar must keep using the region where it was invoked instead of
        treating those timer contexts as a cursor release.
        """
        area = getattr(self, "_area", None)
        region = getattr(self, "_region", None)
        pointer = int(getattr(self, "_region_pointer", 0) or 0)
        try:
            if (
                area is not None
                and region is not None
                and pointer > 0
                and str(getattr(region, "type", "") or "") == "WINDOW"
                and any(
                    int(candidate.as_pointer()) == pointer
                    for candidate in tuple(getattr(area, "regions", ()) or ())
                )
                and int(region.as_pointer()) == pointer
            ):
                return region
        except FBP_DATA_ERRORS:
            return None
        return None

    def _resolve_bound_object(self, context):
        """Resolve the original GP object across mode switches, rename and Undo."""
        expected_name = str(getattr(self, "_object_name", "") or "")
        expected_data_name = str(getattr(self, "_object_data_name", "") or "")
        scene = getattr(context, "scene", None)
        if (
            getattr(self, "_object", None) is None
            and not expected_name
            and not expected_data_name
        ):
            # Timeline-only sessions intentionally have no GP binding.
            return True

        def _remember(candidate):
            self._object = candidate
            try:
                self._object_name = str(getattr(candidate, "name", "") or "")
                self._object_data_name = str(
                    getattr(getattr(candidate, "data", None), "name", "") or ""
                )
            except FBP_DATA_ERRORS:
                pass
            return True

        bound = getattr(self, "_object", None)
        if _scene_contains_object(scene, bound):
            return _remember(bound)

        try:
            objects = getattr(scene, "objects", None)
            candidate = objects.get(expected_name) if objects is not None and expected_name else None
        except FBP_DATA_ERRORS:
            candidate = None
        if _is_live_grease_pencil_object(candidate):
            try:
                data_name = str(getattr(getattr(candidate, "data", None), "name", "") or "")
            except FBP_DATA_ERRORS:
                data_name = ""
            if not expected_data_name or data_name == expected_data_name:
                return _remember(candidate)

        if expected_data_name:
            try:
                for candidate in tuple(getattr(scene, "objects", ()) or ()):
                    if not _is_live_grease_pencil_object(candidate):
                        continue
                    data_name = str(
                        getattr(getattr(candidate, "data", None), "name", "") or ""
                    )
                    if data_name == expected_data_name:
                        return _remember(candidate)
            except FBP_DATA_ERRORS:
                pass
        return False

    def _tag_redraw(self):
        try:
            area = getattr(self, "_area", None)
            if area is not None:
                area.tag_redraw()
        except FBP_DATA_ERRORS:
            pass

    def _set_hover_cursor(self, context, enabled):
        enabled = bool(enabled)
        if not enabled:
            desired = ""
        elif self._shortcut_pending or not self._is_persistent:
            desired = "SCROLL_Y" if self._vertical else "SCROLL_X"
        else:
            desired = "DEFAULT"
        if desired == str(self._cursor_kind or ""):
            return
        self._cursor_over_axis = enabled
        self._cursor_kind = desired
        try:
            if enabled:
                context.window.cursor_modal_set(desired)
            else:
                restore_modal_cursor(context)
        except FBP_DATA_ERRORS:
            pass

    def _sync_magnetic_preferences(self, context):
        preferences = fbp_get_addon_preferences(context)
        try:
            self._magnetic_enabled = bool(
                getattr(preferences, "gp_scrub_mouse_magnet", True)
            )
            self._magnetic_distance = max(
                24.0,
                min(
                    240.0,
                    float(
                        getattr(
                            preferences,
                            "gp_scrub_mouse_magnet_distance",
                            96.0,
                        )
                    ),
                ),
            )
            self._magnetic_strength = max(
                0.0,
                min(
                    1.0,
                    float(
                        getattr(
                            preferences,
                            "gp_scrub_mouse_magnet_strength",
                            1.0,
                        )
                    ),
                ),
            )
            self._magnetic_smoothing = max(
                0.01,
                min(
                    1.0,
                    float(
                        getattr(
                            preferences,
                            "gp_scrub_mouse_magnet_smoothing",
                            0.22,
                        )
                    ),
                ),
            )
        except (TypeError, ValueError, OverflowError, AttributeError, ReferenceError):
            self._magnetic_enabled = True
            self._magnetic_distance = 96.0
            self._magnetic_strength = 1.0
            self._magnetic_smoothing = 0.22
        if not self._magnetic_enabled:
            self._magnetic_target_offset = 0.0

    def _base_layout(self, region):
        return scrub_overlay_layout(
            region,
            position=self._position,
            ui_scale=self._ui_scale,
            length_ratio=self._length_ratio,
            edge_offset=self._edge_offset,
        )

    def _update_magnetic_target(self, context, *, release=False):
        region = self._owned_window_region()
        if self._interaction:
            self._magnetic_target_offset = float(self._magnetic_offset or 0.0)
            return self._magnetic_target_offset
        enabled = bool(
            not release
            and self._magnetic_enabled
            and self._is_persistent
            and not self._shortcut_pending
            and region is not None
            and str(getattr(region, "type", "") or "") == "WINDOW"
        )
        if not enabled:
            self._magnetic_target_offset = 0.0
            return 0.0
        self._magnetic_target_offset = magnetic_scrub_axis_offset(
            self._mouse_x,
            self._mouse_y,
            self._base_layout(region),
            enabled=True,
            capture_px=self._magnetic_distance
            * max(0.75, float(self._ui_scale)),
            strength=self._magnetic_strength,
        )
        return self._magnetic_target_offset

    def _tick_magnetic_hover(self, context, *, release=False):
        self._update_magnetic_target(context, release=release)
        now = time.monotonic()
        previous_tick = float(self._magnetic_last_tick or 0.0)
        elapsed = (
            _TIMER_INTERVAL
            if previous_tick <= 0.0
            else max(0.0, now - previous_tick)
        )
        self._magnetic_last_tick = now
        previous = float(self._magnetic_offset or 0.0)
        self._magnetic_offset = smooth_scrub_magnet_offset(
            previous,
            self._magnetic_target_offset,
            self._magnetic_smoothing,
            elapsed,
        )
        changed = abs(self._magnetic_offset - previous) > _MAGNET_EPSILON_PX
        if changed:
            self._cursor_label_bounds = None
            self._tag_redraw()
        return changed

    def _sync_live_display_preferences(self, context):
        preferences = fbp_get_addon_preferences(context)
        position = str(getattr(preferences, "gp_scrub_position", self._position) or self._position).upper()
        if position in {"TOP", "BOTTOM", "LEFT", "RIGHT"} and position != self._position:
            self._position = position
            self._vertical = position in {"LEFT", "RIGHT"}
            self._magnetic_offset = 0.0
            self._magnetic_target_offset = 0.0
            self._cursor_label_bounds = None
        self._show_info = bool(getattr(preferences, "gp_scrub_show_info", False))
        self._sync_magnetic_preferences(context)
        _apply_inverted_scrub_ink(self, context)

    def _sync_preview_range(self, scene):
        signature = preview_range_signature(scene)
        if signature == self._preview_signature:
            return
        self._preview_signature = signature
        enabled, minimum, maximum = signature
        if enabled:
            self._view_center = (float(minimum) + float(maximum)) * 0.5
            self._view_radius = max(1, int(maximum) - int(minimum) + 1)

    def _display_range(self, scene):
        self._sync_preview_range(scene)
        center, radius = clamp_timeline_view(
            self._view_center,
            self._view_radius,
            *scene_frame_bounds(scene),
        )
        self._view_center = center
        self._view_radius = radius
        return scrub_display_range(scene, int(round(center)), radius)

    def _mouse_in_axis(self, context, mouse_x=None, mouse_y=None):
        region = getattr(context, "region", None)
        if region is None or str(getattr(region, "type", "") or "") != "WINDOW":
            return False
        layout = self._layout(region)
        x = self._mouse_x if mouse_x is None else mouse_x
        y = self._mouse_y if mouse_y is None else mouse_y
        if cursor_in_scrub_bounds(
            x,
            y,
            getattr(self, "_cursor_label_bounds", None),
            padding=_CURSOR_LABEL_CAPTURE_PX * max(0.75, float(self._ui_scale)),
        ):
            return True
        return cursor_near_scrub_axis(
            x,
            y,
            layout,
            capture_px=_AXIS_CAPTURE_PX * max(0.75, float(self._ui_scale)),
        )

    def _axis_frame(self, context, mouse_x=None, mouse_y=None):
        left, right = self._display_range(context.scene)
        return timeline_cursor_frame(
            self._mouse_x if mouse_x is None else mouse_x,
            self._mouse_y if mouse_y is None else mouse_y,
            left,
            right,
            self._layout(context.region),
            invert_vertical=self._invert_vertical,
        )

    def _keyframe_hit(self, context):
        if not self._mouse_in_axis(context) or not self._keyframe_records:
            return None
        layout = self._layout(context.region)
        left, right = self._display_range(context.scene)
        palette = self._palette or blender_theme_palette(context)
        best = None
        best_distance = float("inf")
        for frame, key_type, _active, _selected in _keyframe_records_in_range(
            self._keyframe_records,
            self._keyframe_record_numbers,
            left,
            right,
        ):
            x, y = self._frame_position(frame, left, right, layout)
            radius = keyframe_radius(
                key_type,
                self._ui_scale,
                palette.get("keyframe_scale_factor", 1.0),
            )
            distance = math.hypot(float(self._mouse_x) - x, float(self._mouse_y) - y)
            if distance <= radius + _KEYFRAME_HIT_PADDING_PX and distance < best_distance:
                best = int(frame)
                best_distance = distance
        return best

    def _set_idle_hover(self, context):
        axis_inside = self._mouse_in_axis(context)
        bookmark = self._bookmark_hit()
        interactive_inside = bool(axis_inside or bookmark is not None)
        self._hover_bookmark_uid = str(bookmark.get("uid") or "") if bookmark else ""
        self._hover_frame = self._keyframe_hit(context) if axis_inside and bookmark is None else None
        self._set_hover_cursor(context, interactive_inside)
        self._tag_redraw()

    def _set_frame_from_axis(self, context):
        left, right = self._display_range(context.scene)
        layout = self._layout(context.region)
        raw_target = timeline_cursor_frame(
            self._mouse_x,
            self._mouse_y,
            left,
            right,
            layout,
            invert_vertical=self._invert_vertical,
        )
        span = max(1.0, float(right - left))
        target = snap_frame_value(
            raw_target,
            context.scene,
            playhead_snap_settings(context.scene),
            self._all_keyframes,
            self._strip_frames,
            float(layout["length"]) / span,
            self._marker_frames,
        )
        self._set_frame(context.scene, target)

    def _zoom_view(self, context, factor, *, pivot_frame=None):
        minimum, maximum = scene_frame_bounds(context.scene)
        old_left, old_right = self._display_range(context.scene)
        old_span = max(1.0, float(old_right - old_left))
        if pivot_frame is None:
            pivot_frame = float(self._current_frame)
        pivot = max(float(minimum), min(float(maximum), float(pivot_frame)))
        pivot_factor = max(0.0, min(1.0, (pivot - float(old_left)) / old_span))
        try:
            new_radius = int(round(float(self._view_radius) * float(factor)))
        except (TypeError, ValueError, OverflowError):
            return
        new_center, new_radius = clamp_timeline_view(
            pivot + (0.5 - pivot_factor) * max(1.0, float(new_radius) - 1.0),
            new_radius,
            minimum,
            maximum,
        )
        self._view_center = new_center
        self._view_radius = new_radius
        self._tag_redraw()

    def _pan_view_pixels(self, context, delta_pixels, *, start_center=None):
        left, right = self._display_range(context.scene)
        span = max(1.0, float(right - left))
        length = max(1.0, float(self._layout(context.region)["length"]))
        base = self._view_center if start_center is None else float(start_center)
        center = base - (float(delta_pixels) * span / length)
        self._view_center, self._view_radius = clamp_timeline_view(
            center,
            self._view_radius,
            *scene_frame_bounds(context.scene),
        )
        self._tag_redraw()

    def _pan_view_frames(self, context, delta_frames):
        self._view_center, self._view_radius = clamp_timeline_view(
            float(self._view_center) + float(delta_frames),
            self._view_radius,
            *scene_frame_bounds(context.scene),
        )
        self._tag_redraw()

    def _handle_wheel_navigation(self, context, event):
        direction = wheel_navigation_direction(getattr(event, "type", ""))
        if direction == 0:
            return False
        if primary_modifier_pressed(event):
            left, right = self._display_range(context.scene)
            step = max(
                1,
                int(round(max(1.0, float(right - left)) * _WHEEL_PAN_FRACTION)),
            )
            axis_direction = -direction if self._vertical and self._invert_vertical else direction
            self._pan_view_frames(context, axis_direction * step)
        else:
            self._zoom_view(
                context,
                _ZOOM_STEP if direction > 0 else (1.0 / _ZOOM_STEP),
                pivot_frame=self._axis_frame(context),
            )
        return True

    def _handle_native_navigation(self, context, event, action):
        """Apply the operation selected by Blender's active View2D keymap."""
        event_type = str(getattr(event, "type", "") or "")
        event_value = str(getattr(event, "value", "") or "")
        if action in {"ZOOM_IN", "ZOOM_OUT"}:
            if event_value not in {"PRESS", "ANY", ""}:
                return False
            self._zoom_view(
                context,
                _ZOOM_STEP if action == "ZOOM_IN" else (1.0 / _ZOOM_STEP),
                pivot_frame=self._axis_frame(context),
            )
            return True

        if action not in {"PAN", "ZOOM"}:
            return False
        if event_type in {"TRACKPADPAN", "TRACKPADZOOM"}:
            try:
                delta_x = float(event.mouse_x) - float(event.mouse_prev_x)
                delta_y = float(event.mouse_y) - float(event.mouse_prev_y)
            except (AttributeError, TypeError, ValueError, OverflowError):
                delta_x = delta_y = 0.0
            if action == "ZOOM":
                primary = delta_y if abs(delta_y) >= abs(delta_x) else delta_x
                self._zoom_view(
                    context,
                    math.exp(max(-1.0, min(1.0, -primary * 0.025))),
                    pivot_frame=self._axis_frame(context),
                )
            else:
                primary = delta_y if self._vertical else delta_x
                if self._vertical and self._invert_vertical:
                    primary = -primary
                self._pan_view_pixels(context, primary)
            return True

        if event_value != "PRESS":
            return False
        self._interaction = action
        self._interaction_event_type = event_type
        self._interaction_start_x = self._mouse_x
        self._interaction_start_y = self._mouse_y
        self._interaction_start_center = float(self._view_center)
        self._interaction_start_radius = int(self._view_radius)
        self._interaction_start_frame = int(round(self._axis_frame(context)))
        return True

    def _selected_source_maps(self):
        selected = {}
        occupied = {}
        rows = grease_pencil_editable_frames(self._object)
        for layer, frame in rows:
            key = _rna_pointer(layer)
            number = int(getattr(frame, "frame_number", 0) or 0)
            occupied.setdefault(key, set()).add(number)
            if bool(getattr(frame, "select", False)):
                selected.setdefault(key, set()).add(number)
        return selected, occupied

    def _begin_key_transform(self, context):
        selected, occupied = self._selected_source_maps()
        if not selected:
            return False
        layer_by_key = {
            _rna_pointer(layer): layer
            for layer, _frame in grease_pencil_editable_frames(self._object)
        }
        self._transform_sources = tuple(
            (layer_by_key[key], number)
            for key, numbers in selected.items()
            if key in layer_by_key
            for number in sorted(numbers)
        )
        self._transform_occupied = {
            key: frozenset(numbers) for key, numbers in occupied.items()
        }
        self._transform_selected = {
            key: frozenset(numbers) for key, numbers in selected.items()
        }
        self._transform_delta = 0
        self._interaction_start_frame = int(round(self._axis_frame(context)))
        return bool(self._transform_sources)

    @staticmethod
    def _frame_at(layer, frame_number):
        try:
            return next(
                (
                    frame
                    for frame in tuple(getattr(layer, "frames", ()) or ())
                    if int(getattr(frame, "frame_number", 0) or 0) == int(frame_number)
                ),
                None,
            )
        except FBP_DATA_ERRORS:
            return None

    @staticmethod
    def _move_layer_frame(layer, source, target, *, selected=True):
        try:
            try:
                moved = layer.frames.move(
                    from_frame_number=int(source),
                    to_frame_number=int(target),
                )
            except TypeError:
                moved = layer.frames.move(int(source), int(target))
            if moved is not None:
                moved.select = bool(selected)
            return moved
        except FBP_DATA_ERRORS:
            return None

    @staticmethod
    def _copy_layer_frame(layer, source, target):
        try:
            try:
                copied = layer.frames.copy(
                    from_frame_number=int(source),
                    to_frame_number=int(target),
                    instance_drawing=False,
                )
            except TypeError:
                copied = layer.frames.copy(int(source), int(target))
            if copied is not None:
                copied.select = True
            return copied
        except FBP_DATA_ERRORS:
            return None

    @staticmethod
    def _remove_layer_frame(layer, frame_number):
        try:
            layer.frames.remove(int(frame_number))
            return True
        except FBP_DATA_ERRORS:
            return False

    @staticmethod
    def _temporary_frame_number(layer, reserved=()):
        occupied = {
            int(getattr(frame, "frame_number", 0) or 0)
            for frame in tuple(getattr(layer, "frames", ()) or ())
        }
        occupied.update(int(number) for number in tuple(reserved or ()))
        for candidate in range(_FRAME_NUMBER_MAX, _FRAME_NUMBER_MIN - 1, -1):
            if candidate not in occupied:
                return candidate
        return None

    def _restore_transform_to_original(self):
        current = int(self._transform_delta)
        if current:
            rows = sorted(
                self._transform_sources,
                key=lambda item: (_rna_pointer(item[0]), item[1]),
                reverse=(0 > current),
            )
            restored_rows = []
            for layer, original in rows:
                source = int(original) + current
                target = int(original)
                moved = self._move_layer_frame(layer, source, target, selected=True)
                if moved is None:
                    for rollback_layer, rollback_source, rollback_target in reversed(
                        restored_rows
                    ):
                        self._move_layer_frame(
                            rollback_layer,
                            rollback_target,
                            rollback_source,
                            selected=True,
                        )
                    return False
                restored_rows.append((layer, source, target))
            self._transform_delta = 0

        remaining = []
        for layer, target, stash, was_selected in reversed(self._collision_stashes):
            restored = self._move_layer_frame(
                layer,
                stash,
                target,
                selected=was_selected,
            )
            if restored is None:
                remaining.append((layer, target, stash, was_selected))
        self._collision_stashes = tuple(reversed(remaining))
        return not self._collision_stashes

    def _stash_transform_collisions(self, desired):
        stashes = []
        reserved_by_layer = {}
        selected_by_layer = {
            key: frozenset(numbers)
            for key, numbers in self._transform_selected.items()
        }
        for layer, original in self._transform_sources:
            key = _rna_pointer(layer)
            target = int(original) + int(desired)
            if target in selected_by_layer.get(key, frozenset()):
                continue
            existing = self._frame_at(layer, target)
            if existing is None:
                continue
            was_selected = bool(getattr(existing, "select", False))
            reserved = reserved_by_layer.setdefault(key, set())
            stash = self._temporary_frame_number(layer, reserved)
            if stash is None:
                for stored_layer, stored_target, stored_stash, stored_selected in reversed(
                    stashes
                ):
                    self._move_layer_frame(
                        stored_layer,
                        stored_stash,
                        stored_target,
                        selected=stored_selected,
                    )
                return False
            reserved.add(stash)
            moved = self._move_layer_frame(
                layer,
                target,
                stash,
                selected=was_selected,
            )
            if moved is None:
                for stored_layer, stored_target, stored_stash, stored_selected in reversed(
                    stashes
                ):
                    self._move_layer_frame(
                        stored_layer,
                        stored_stash,
                        stored_target,
                        selected=stored_selected,
                    )
                return False
            stashes.append((layer, target, stash, was_selected))
        self._collision_stashes = tuple(stashes)
        return True

    def _discard_transform_collisions(self):
        removed_all = True
        for layer, _target, stash, _was_selected in reversed(self._collision_stashes):
            removed_all = self._remove_layer_frame(layer, stash) and removed_all
        self._collision_stashes = ()
        return removed_all

    def _begin_key_duplicate(self, context):
        selected, occupied = self._selected_source_maps()
        minimum, maximum = scene_frame_bounds(context.scene)
        initial_delta = resolve_keyframe_duplicate_delta(
            selected,
            occupied,
            minimum,
            maximum,
        )
        if initial_delta == 0:
            return False
        layer_by_key = {
            _rna_pointer(layer): layer
            for layer, _frame in grease_pencil_editable_frames(self._object)
        }
        copies = []
        for key, numbers in selected.items():
            layer = layer_by_key.get(key)
            if layer is None:
                continue
            for source in sorted(numbers):
                target = int(source) + int(initial_delta)
                copied = self._copy_layer_frame(layer, source, target)
                if copied is None:
                    for copied_layer, copied_number in reversed(copies):
                        self._remove_layer_frame(copied_layer, copied_number)
                    return False
                copies.append((layer, target))
        if not copies:
            return False
        select_all_grease_pencil_frames(self._object, selected=False)
        for layer, number in copies:
            copied = self._frame_at(layer, number)
            if copied is not None:
                try:
                    copied.select = True
                except FBP_DATA_ERRORS:
                    pass
        self._duplicate_pending = True
        self._duplicate_sources = tuple(copies)
        self._refresh_keyframe_cache(context)
        if not self._begin_key_transform(context):
            for copied_layer, copied_number in reversed(copies):
                self._remove_layer_frame(copied_layer, copied_number)
            self._duplicate_pending = False
            self._duplicate_sources = ()
            self._refresh_keyframe_cache(context)
            return False
        return True

    def _delete_selected_keyframes(self, context):
        if not selected_grease_pencil_frames(self._object):
            hit = self._keyframe_hit(context)
            if hit is not None:
                select_grease_pencil_frame_number(self._object, hit)
        deleted = delete_selected_grease_pencil_frames(self._object)
        if not deleted:
            return False
        self._refresh_keyframe_cache(context)
        try:
            bpy.ops.ed.undo_push(message="Delete Grease Pencil Keyframes")
        except FBP_DATA_ERRORS:
            pass
        self._tag_redraw()
        return True

    def _apply_transform_delta(self, context, requested_delta):
        minimum, maximum = scene_frame_bounds(context.scene)
        desired = resolve_keyframe_move_delta(
            self._transform_selected,
            self._transform_occupied,
            requested_delta,
            minimum,
            maximum,
        )
        current = int(self._transform_delta)
        if desired == current:
            return False
        if not self._restore_transform_to_original():
            return False
        if desired == 0:
            self._refresh_keyframe_cache(context)
            self._tag_redraw()
            return True
        if not self._stash_transform_collisions(desired):
            return False

        moving_right = desired > 0
        rows = sorted(
            self._transform_sources,
            key=lambda item: (_rna_pointer(item[0]), item[1]),
            reverse=moving_right,
        )
        moved_rows = []
        for layer, original in rows:
            source = int(original)
            target = int(original) + desired
            moved = self._move_layer_frame(layer, source, target, selected=True)
            if moved is None:
                for rollback_layer, rollback_source, rollback_target in reversed(moved_rows):
                    self._move_layer_frame(
                        rollback_layer,
                        rollback_target,
                        rollback_source,
                        selected=True,
                    )
                self._transform_delta = 0
                self._restore_transform_to_original()
                return False
            moved_rows.append((layer, source, target))
        self._transform_delta = desired
        self._refresh_keyframe_cache(context)
        self._tag_redraw()
        return True

    def _update_key_transform(self, context):
        current_frame = int(round(self._axis_frame(context)))
        self._apply_transform_delta(
            context,
            current_frame - int(self._interaction_start_frame),
        )

    def _cancel_key_transform(self, context):
        if int(self._transform_delta) or self._collision_stashes:
            self._restore_transform_to_original()
            self._refresh_keyframe_cache(context)
        self._transform_sources = ()
        self._transform_delta = 0

    def _finish_interaction(self, context, *, cancel=False):
        interaction = str(self._interaction or "")
        changed_keys = bool(
            interaction == "KEY_MOVE"
            and (int(self._transform_delta) or self._duplicate_pending)
        )
        changed_bookmarks = bool(
            interaction == "BOOKMARK_MOVE"
            and (int(self._bookmark_transform_delta) or self._bookmark_transform_created)
        )
        if cancel and interaction == "BOOKMARK_MOVE":
            self._cancel_bookmark_transform(context)
            changed_bookmarks = False
        elif cancel and interaction == "KEY_MOVE":
            self._cancel_key_transform(context)
            if self._duplicate_pending:
                for layer, number in reversed(self._duplicate_sources):
                    self._remove_layer_frame(layer, number)
                self._refresh_keyframe_cache(context)
            changed_keys = False
        elif cancel and interaction == "PAN":
            self._view_center = self._interaction_start_center
        elif cancel and interaction == "ZOOM":
            self._view_center = self._interaction_start_center
            self._view_radius = self._interaction_start_radius
        elif cancel and interaction == "SCRUB":
            self._set_frame(context.scene, self._interaction_start_frame)
        elif cancel and interaction in {"ONION_BEFORE", "ONION_AFTER"}:
            original = self._onion_drag_original
            if isinstance(original, tuple) and len(original) == 3:
                try:
                    setattr(original[0], original[1], int(original[2]))
                except FBP_DATA_ERRORS:
                    pass
        elif interaction in {"ONION_BEFORE", "ONION_AFTER"}:
            original = self._onion_drag_original
            changed_onion = False
            if isinstance(original, tuple) and len(original) == 3:
                try:
                    changed_onion = int(getattr(original[0], original[1])) != int(original[2])
                except FBP_DATA_ERRORS:
                    changed_onion = False
            if changed_onion:
                try:
                    bpy.ops.ed.undo_push(message="Adjust Grease Pencil Onion Range")
                except FBP_DATA_ERRORS:
                    pass
        self._onion_drag_original = None
        self._interaction = ""
        self._interaction_event_type = ""
        self._transform_sources = ()
        self._transform_delta = 0
        if changed_keys:
            self._discard_transform_collisions()
            try:
                bpy.ops.ed.undo_push(
                    message=(
                        "Duplicate Grease Pencil Keyframes"
                        if self._duplicate_pending
                        else "Move Grease Pencil Keyframes"
                    )
                )
            except FBP_DATA_ERRORS:
                pass
        elif self._collision_stashes:
            self._restore_transform_to_original()
        self._duplicate_pending = False
        self._duplicate_sources = ()
        if changed_bookmarks:
            try:
                bpy.ops.ed.undo_push(
                    message=(
                        "Duplicate Scrub Bookmarks"
                        if self._bookmark_transform_created
                        else "Move Scrub Bookmarks"
                    )
                )
            except FBP_DATA_ERRORS:
                pass
        self._bookmark_transform_sources = ()
        self._bookmark_transform_created = ()
        self._bookmark_transform_delta = 0
        self._update_magnetic_target(context)
        self._set_idle_hover(context)

    def _begin_shortcut(self, context, event):
        self._persistent_before_shortcut = bool(self._is_persistent)
        self._persistent_view_before = (
            (float(self._view_center), int(self._view_radius))
            if self._persistent_before_shortcut
            else None
        )
        if self._persistent_before_shortcut:
            self._hold_center = float(self._view_center)
            self._hold_radius = int(self._view_radius)
        else:
            self._hold_center = float(context.scene.frame_current)
            self._hold_radius = int(self._maximum_range)
        self._shortcut_pending = True
        self._shortcut_started = time.monotonic()
        self._shortcut_start_x = float(getattr(event, "mouse_region_x", self._mouse_x) or 0.0)
        self._shortcut_start_y = float(getattr(event, "mouse_region_y", self._mouse_y) or 0.0)
        self._shortcut_moved = False
        # Keymap invocation coordinates can be zero/stale on some Windows
        # layouts. The first real mouse event establishes a trusted relative
        # anchor and is never allowed to move the playhead.
        self._shortcut_anchor_pending = True
        self._activation_event_type = str(getattr(event, "type", "") or "")
        self._origin_frame = int(context.scene.frame_current)
        self._current_frame = self._origin_frame
        self._relative_anchor_frame = float(self._origin_frame)
        self._shortcut_direct_factor = 0.0
        self._shortcut_direct_locked = False
        self._overflow_offset = 0
        self._drag_anchor_x = self._shortcut_start_x
        self._drag_anchor_y = self._shortcut_start_y
        self._mouse_x = self._shortcut_start_x
        self._mouse_y = self._shortcut_start_y
        self._edge_direction = 0
        self._magnetic_offset = 0.0
        self._magnetic_target_offset = 0.0
        self._cursor_label_bounds = None
        self._suspend_onion_skin(context)
        self._set_hover_cursor(context, True)
        self._tag_redraw()

    def _release_shortcut(self, context):
        elapsed = time.monotonic() - float(self._shortcut_started)
        action = scrub_release_action(
            elapsed,
            self._shortcut_moved,
            self._persistent_before_shortcut,
        )
        self._shortcut_pending = False
        self._edge_direction = 0
        self._restore_onion_skin()
        if action == "DISABLE_PERSISTENT":
            return self._finish(context)
        if action == "FINISH_MOMENTARY":
            return self._finish(context)
        self._is_persistent = True
        if action == "KEEP_PERSISTENT":
            self._view_center = float(self._hold_center) + int(self._overflow_offset)
            self._view_radius = int(self._hold_radius)
        self._persistent_view_before = None
        self._activation_event_type = ""
        self._set_hover_cursor(context, self._mouse_in_axis(context))
        self._tag_redraw()
        return {"RUNNING_MODAL"}

    def _suspend_onion_skin(self, context):
        """Hide the View3D onion-skin overlay for this hold session only."""
        self._onion_skin_overlay = None
        self._onion_skin_was_enabled = None
        try:
            overlay = getattr(getattr(context, "space_data", None), "overlay", None)
            if overlay is None or not hasattr(overlay, "use_gpencil_onion_skin"):
                return
            enabled = bool(overlay.use_gpencil_onion_skin)
            self._onion_skin_overlay = overlay
            self._onion_skin_was_enabled = enabled
            if enabled:
                overlay.use_gpencil_onion_skin = False
        except FBP_DATA_ERRORS as exc:
            self._onion_skin_overlay = None
            self._onion_skin_was_enabled = None
            fbp_warn("Could not temporarily hide Grease Pencil onion skinning", exc)

    def _restore_onion_skin(self):
        """Restore the exact View3D onion-skin state captured at invoke time."""
        overlay = self._onion_skin_overlay
        enabled = self._onion_skin_was_enabled
        self._onion_skin_overlay = None
        self._onion_skin_was_enabled = None
        if overlay is None or enabled is None:
            return
        try:
            if bool(overlay.use_gpencil_onion_skin) != bool(enabled):
                overlay.use_gpencil_onion_skin = bool(enabled)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not restore Grease Pencil onion skinning", exc)

    def _refresh_keyframe_cache(self, context):
        hidden_stashes = {
            int(stash)
            for _layer, _target, stash, _selected in self._collision_stashes
        }
        self._keyframe_records = tuple(
            record
            for record in grease_pencil_keyframe_records(self._object)
            if int(record[0]) not in hidden_stashes
        )
        self._keyframe_record_numbers = tuple(record[0] for record in self._keyframe_records)
        self._all_keyframes = timeline_keyframe_frames(
            context.scene, self._object
        )
        self._marker_frames = marker_snap_frames(context.scene)
        self._bookmark_records = scrub_bookmark_records(context.scene)
        self._native_marker_records = scrub_native_marker_records(context.scene)
        self._strip_frames = strip_snap_frames(context.scene, self._object)

    def _onion_handle_hit(self):
        radius = (_ONION_HANDLE_RADIUS_PX + _ONION_HANDLE_HIT_PADDING_PX) * max(0.75, float(self._ui_scale))
        for side, point in (("BEFORE", self._onion_before_handle), ("AFTER", self._onion_after_handle)):
            if point is None:
                continue
            if math.hypot(float(self._mouse_x) - float(point[0]), float(self._mouse_y) - float(point[1])) <= radius:
                return side
        return None

    @staticmethod
    def _point_in_triangle(x, y, triangle):
        try:
            (x1, y1), (x2, y2), (x3, y3) = triangle
            denominator = ((y2 - y3) * (x1 - x3)) + ((x3 - x2) * (y1 - y3))
            if abs(float(denominator)) <= 1.0e-8:
                return False
            a = (((y2 - y3) * (x - x3)) + ((x3 - x2) * (y - y3))) / denominator
            b = (((y3 - y1) * (x - x3)) + ((x1 - x3) * (y - y3))) / denominator
            c = 1.0 - a - b
            return a >= 0.0 and b >= 0.0 and c >= 0.0
        except (TypeError, ValueError, KeyError, IndexError):
            return False

    def _bookmark_hit(self):
        best = None
        best_distance = float("inf")
        radius = _BOOKMARK_HIT_RADIUS_PX * max(0.75, float(self._ui_scale))
        mouse_x = float(self._mouse_x)
        mouse_y = float(self._mouse_y)
        for hit in tuple(getattr(self, "_bookmark_hit_records", ()) or ()):
            try:
                bounds = hit.get("label_bounds")
                label_hit = bool(
                    bounds is not None
                    and float(bounds[0]) <= mouse_x <= float(bounds[2])
                    and float(bounds[1]) <= mouse_y <= float(bounds[3])
                )
                triangle_hit = self._point_in_triangle(mouse_x, mouse_y, hit.get("triangle"))
                distance = math.hypot(mouse_x - float(hit["x"]), mouse_y - float(hit["y"]))
            except (TypeError, ValueError, KeyError, IndexError):
                continue
            if label_hit or triangle_hit:
                return hit.get("record")
            if distance <= radius and distance < best_distance:
                best = hit.get("record")
                best_distance = distance
        return best

    def _deselect_bookmarks(self, context):
        scene = getattr(context, "scene", None)
        changed = False
        for record in scrub_bookmark_records(scene):
            marker = record.get("marker")
            try:
                if bool(marker.select):
                    marker.select = False
                    changed = True
            except FBP_DATA_ERRORS:
                continue
        if changed:
            self._hover_bookmark_uid = ""
            self._refresh_keyframe_cache(context)
            self._tag_redraw()
        return changed

    def _select_bookmark_record(self, context, record, *, extend=False, toggle=False):
        if not isinstance(record, dict):
            return False
        scene = getattr(context, "scene", None)
        marker = record.get("marker")
        if scene is None or marker is None:
            return False
        try:
            if not extend:
                for candidate in tuple(getattr(scene, "timeline_markers", ()) or ()):
                    candidate.select = False
            marker.select = (not bool(marker.select)) if toggle else True
        except FBP_DATA_ERRORS:
            return False
        self._hover_bookmark_uid = str(record.get("uid") or "")
        self._refresh_keyframe_cache(context)
        self._tag_redraw()
        return True

    def _begin_bookmark_transform(self, context, *, duplicate=False):
        scene = getattr(context, "scene", None)
        markers = getattr(scene, "timeline_markers", None) if scene is not None else None
        if markers is None:
            return False
        selected = selected_scrub_bookmark_records(scene)
        if not selected:
            hit = self._bookmark_hit()
            if hit is not None and self._select_bookmark_record(context, hit):
                selected = selected_scrub_bookmark_records(scene)
        if not selected:
            return False

        created_markers = []
        if duplicate:
            entries = _load_bookmark_state(scene)
            try:
                for marker in tuple(markers):
                    marker.select = False
            except FBP_DATA_ERRORS:
                pass
            for record in selected:
                try:
                    try:
                        marker = markers.new(
                            _bookmark_native_name(record["name"]),
                            frame=int(record["frame"]),
                        )
                    except TypeError:
                        marker = markers.new(_bookmark_native_name(record["name"]))
                        marker.frame = int(record["frame"])
                    marker.select = True
                except FBP_DATA_ERRORS:
                    continue
                entry = _new_bookmark_entry(
                    marker,
                    label=record["name"],
                    color_tag=record["color_tag"],
                )
                entries.append(entry)
                _BOOKMARK_POINTER_UIDS[_marker_pointer(marker)] = entry["uid"]
                created_markers.append(marker)
            if not created_markers:
                return False
            _save_bookmark_state(scene, entries)
            reconcile_scrub_bookmarks(scene)
            self._refresh_keyframe_cache(context)
            selected = selected_scrub_bookmark_records(scene)

        self._bookmark_transform_sources = tuple(
            (record["marker"], int(record["frame"])) for record in selected
        )
        self._bookmark_transform_created = tuple(created_markers)
        self._bookmark_transform_delta = 0
        self._interaction_start_frame = int(round(self._axis_frame(context)))
        self._interaction = "BOOKMARK_MOVE"
        self._interaction_event_type = "LEFTMOUSE"
        self._tag_redraw()
        return True

    def _update_bookmark_transform(self, context):
        if not self._bookmark_transform_sources:
            return False
        delta = int(round(self._axis_frame(context))) - int(self._interaction_start_frame)
        if delta == int(self._bookmark_transform_delta):
            return False
        minimum, maximum = scene_frame_bounds(context.scene)
        for marker, original in self._bookmark_transform_sources:
            try:
                marker.frame = max(int(minimum), min(int(maximum), int(original) + delta))
            except FBP_DATA_ERRORS:
                continue
        self._bookmark_transform_delta = delta
        reconcile_scrub_bookmarks(context.scene)
        self._refresh_keyframe_cache(context)
        self._tag_redraw()
        return True

    def _cancel_bookmark_transform(self, context):
        scene = getattr(context, "scene", None)
        markers = getattr(scene, "timeline_markers", None) if scene is not None else None
        created = set(self._bookmark_transform_created)
        if markers is not None and created:
            for marker in tuple(created):
                try:
                    markers.remove(marker)
                except FBP_DATA_ERRORS:
                    continue
        else:
            for marker, original in self._bookmark_transform_sources:
                try:
                    marker.frame = int(original)
                except FBP_DATA_ERRORS:
                    continue
        reconcile_scrub_bookmarks(scene)
        self._refresh_keyframe_cache(context)
        self._bookmark_transform_sources = ()
        self._bookmark_transform_created = ()
        self._bookmark_transform_delta = 0
        self._tag_redraw()

    def _update_onion_range(self, context, side):
        settings = _grease_pencil_onion_settings(context, self._object, self._keyframe_record_numbers)
        if settings is None:
            return False
        target = self._axis_frame(context)
        amount = _onion_amount_from_frame(
            self._current_frame,
            target,
            side,
            settings["mode"],
            settings["keyframes"],
        )
        attribute = "ghost_before_range" if str(side).upper() == "BEFORE" else "ghost_after_range"
        try:
            if int(getattr(settings["data"], attribute)) != int(amount):
                setattr(settings["data"], attribute, int(amount))
                self._tag_redraw()
            return True
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not update Grease Pencil onion range", exc)
            return False

    def _set_frame(self, scene, target):
        minimum, maximum = scene_frame_bounds(scene)
        target = max(minimum, min(maximum, int(target)))
        try:
            current = int(scene.frame_current)
        except FBP_DATA_ERRORS:
            current = target - 1
        if target != current:
            try:
                scene.frame_set(target)
                self._has_frame_change = True
            except FBP_DATA_ERRORS as exc:
                fbp_warn("Could not scrub the Grease Pencil frame", exc)
                return False
        self._current_frame = target
        note_scrub_history_frame(scene, target)
        return True

    def _layout(self, region):
        return _scrub_layout_for_state(self, region)

    def _cursor_delta(self):
        if self._vertical:
            delta = float(self._mouse_y) - float(self._drag_anchor_y)
            return -delta if self._invert_vertical else delta
        return float(self._mouse_x) - float(self._drag_anchor_x)

    def _window_center(self):
        if self._shortcut_pending:
            return int(self._origin_frame) + int(self._overflow_offset)
        return int(round(self._view_center))

    def _active_scrub_count(self):
        return (
            max(1, int(self._hold_radius))
            if self._shortcut_pending
            else max(1, int(self._view_radius))
        )

    def _active_scrub_radius(self):
        return max(1.0, (float(self._active_scrub_count()) - 1.0) * 0.5)

    def _target_from_mouse(self, context):
        scene = context.scene
        layout = self._layout(context.region)
        visible_count = self._active_scrub_count()
        scrub_radius = self._active_scrub_radius()
        left, right = scrub_display_range(scene, self._window_center(), visible_count)

        factor = direct_scrub_mapping_factor(
            self._mouse_x,
            self._mouse_y,
            layout,
            capture_px=self._magnetic_distance * max(0.75, float(self._ui_scale)),
            inner_px=_DIRECT_SCRUB_INNER_PX * max(0.75, float(self._ui_scale)),
            strength=self._magnetic_strength if self._magnetic_enabled else 0.0,
        )
        previous_factor = float(getattr(self, "_shortcut_direct_factor", 0.0) or 0.0)
        was_direct_locked = bool(getattr(self, "_shortcut_direct_locked", False))
        direct_locked = factor >= 0.999
        if was_direct_locked and not direct_locked:
            # Leaving exact cursor mapping: the exit point becomes the new
            # relative origin immediately, avoiding a recoil toward the old
            # activation point while the magnetic blend fades out.
            self._relative_anchor_frame = float(self._current_frame)
            self._drag_anchor_x = float(self._mouse_x)
            self._drag_anchor_y = float(self._mouse_y)
            self._overflow_offset = 0
        elif previous_factor > 0.0 and factor <= 0.0:
            self._relative_anchor_frame = float(self._current_frame)
            self._drag_anchor_x = float(self._mouse_x)
            self._drag_anchor_y = float(self._mouse_y)
            self._overflow_offset = 0
        self._shortcut_direct_locked = direct_locked
        self._shortcut_direct_factor = factor

        relative_origin = float(getattr(self, "_relative_anchor_frame", self._window_center())) + int(self._overflow_offset)
        relative_target, relative_edge = relative_scrub_target(
            relative_origin,
            self._cursor_delta(),
            scrub_radius,
            layout["half_extent"],
            sensitivity=self._sensitivity,
            shift=self._shift_held,
            slow_factor=self._slow_factor,
            negative_radius=max(0.0, relative_origin - float(left)),
            positive_radius=max(0.0, float(right) - relative_origin),
        )
        absolute_target = timeline_cursor_frame(
            self._mouse_x,
            self._mouse_y,
            left,
            right,
            layout,
            invert_vertical=self._invert_vertical,
        )
        raw_target = relative_target + (absolute_target - relative_target) * factor

        if layout["vertical"]:
            direct_edge = self._mouse_y - (float(layout["y0"]) + float(layout["y1"])) * 0.5
            if self._invert_vertical:
                direct_edge = -direct_edge
        else:
            direct_edge = self._mouse_x - (float(layout["x0"]) + float(layout["x1"])) * 0.5
        edge_value = relative_edge + (direct_edge - relative_edge) * factor

        visible_span = max(1.0, float(right - left))
        pixels_per_frame = float(layout["length"]) / visible_span
        self._snap_settings = playhead_snap_settings(scene)
        if self._ctrl_held and self._all_keyframes:
            nearest = _nearest_sorted_value(self._all_keyframes, raw_target)
            target = int(round(nearest)) if nearest is not None else int(round(raw_target))
        else:
            target = snap_frame_value(
                raw_target,
                scene,
                self._snap_settings,
                self._all_keyframes,
                self._strip_frames,
                pixels_per_frame,
                self._marker_frames,
            )
        self._set_frame(scene, target)

        threshold = float(layout["half_extent"]) * _EDGE_THRESHOLD
        direction = 1 if edge_value >= threshold else (-1 if edge_value <= -threshold else 0)
        minimum, maximum = scene_frame_bounds(scene)
        if (direction < 0 and self._current_frame <= minimum) or (direction > 0 and self._current_frame >= maximum):
            direction = 0
        if direction != self._edge_direction:
            now = time.monotonic()
            self._edge_direction = direction
            self._edge_since = now if direction else 0.0
            self._edge_last_repeat = now if direction else 0.0

    def _edge_tick(self, context):
        direction = int(self._edge_direction)
        if direction == 0:
            return
        now = time.monotonic()
        if now - float(self._edge_since) < _EDGE_DWELL_SECONDS:
            return
        if now - float(self._edge_last_repeat) < _EDGE_REPEAT_SECONDS:
            return
        minimum, maximum = scene_frame_bounds(context.scene)
        if (direction < 0 and self._current_frame <= minimum) or (direction > 0 and self._current_frame >= maximum):
            self._edge_last_repeat = now
            return
        self._overflow_offset += direction
        self._edge_last_repeat = now
        self._target_from_mouse(context)
        self._tag_redraw()

    def _session_changed(self, scene):
        try:
            return int(scene.frame_current) != int(self._session_start_frame)
        except FBP_DATA_ERRORS:
            return bool(self._has_frame_change)

    def _finish(self, context):
        changed = self._session_changed(context.scene)
        self._cleanup(context)
        return {"FINISHED"} if changed else {"CANCELLED"}

    def _frame_position(self, frame, left, right, layout):
        return _scrub_frame_position(
            frame, left, right, layout, invert_vertical=self._invert_vertical
        )

    def _draw_callback(self):
        try:
            context = bpy.context
            area = getattr(context, "area", None)
            region = getattr(context, "region", None)
            if area is None or region is None or int(area.as_pointer()) != int(self._area_pointer):
                return
            persistent = bool(getattr(self, "_is_persistent", False))
            shortcut_pending = bool(getattr(self, "_shortcut_pending", False))
            if not persistent and not _is_view3d_context(
                context,
                require_window_region=True,
            ):
                return
            if hasattr(self, "_sync_live_display_preferences"):
                self._sync_live_display_preferences(context)
            try:
                self._current_frame = int(context.scene.frame_current)
            except FBP_DATA_ERRORS:
                pass
            now = time.monotonic()
            if (
                hasattr(self, "_refresh_keyframe_cache")
                and now - float(getattr(self, "_cache_checked_at", 0.0)) >= 0.12
            ):
                self._refresh_keyframe_cache(context)
                self._cache_checked_at = now
            import blf
            import gpu
            from gpu_extras.batch import batch_for_shader

            palette = self._palette or blender_theme_palette(context, (0.12, 0.12, 0.12))
            layout = self._layout(region)
            line = (*self._line_color[:3], 1.0)
            minor = self._frame_tick_color
            major = self._major_tick_color
            second = self._second_tick_color
            secondary = (*self._text_color[:3], 0.72)
            keyframe_colors = palette.get("keyframe_types", {})
            border = palette["keyframe_border"]
            border_selected = palette["keyframe_border_selected"]

            gpu.state.blend_set("ALPHA")
            gpu.state.line_width_set(max(0.5, float(self._line_width) * max(0.75, self._ui_scale)))
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            window_center = self._window_center()
            if persistent and not shortcut_pending:
                left, right = self._display_range(context.scene)
            else:
                left, right = scrub_display_range(
                    context.scene,
                    window_center,
                    (
                        self._active_scrub_count()
                        if hasattr(self, "_active_scrub_count")
                        else self._maximum_range
                    ),
                )
            current_x, current_y = self._frame_position(self._current_frame, left, right, layout)

            rounded_axis = []
            if layout["vertical"]:
                _append_rounded_segment(rounded_axis, layout["x"], layout["y0"], layout["x"], layout["y1"], self._line_width * max(0.75, self._ui_scale))
            else:
                _append_rounded_segment(rounded_axis, layout["x0"], layout["y"], layout["x1"], layout["y"], self._line_width * max(0.75, self._ui_scale))
            _draw_uniform_batch(shader, batch_for_shader, "TRIS", rounded_axis, line)

            second_values = major_second_frames(left, right, scene_fps(context.scene))
            if len(second_values) > _MAX_TIMELINE_TICKS:
                second_stride = int(math.ceil(len(second_values) / _MAX_TIMELINE_TICKS))
                second_values = second_values[::second_stride]
            second_frames = frozenset(second_values)
            minor_tick_tris, major_tick_tris, second_tick_tris = [], [], []
            tick_width = max(0.7, self._line_width * max(0.75, self._ui_scale))
            scale = max(0.75, self._ui_scale) * self._tick_scale
            tick_count = max(1, int(right) - int(left) + 1)
            tick_stride = max(1, int(math.ceil(tick_count / _MAX_TIMELINE_TICKS)))
            first_tick = int(math.ceil(int(left) / tick_stride) * tick_stride)
            tick_frames = sorted(
                set(range(first_tick, int(right) + 1, tick_stride)).union(second_frames)
            )
            for frame in tick_frames:
                x, y = self._frame_position(frame, left, right, layout)
                is_second = frame in second_frames
                is_major = frame % max(2, int(self._major_interval)) == 0
                if is_second:
                    extent = self._second_tick_length * scale
                    if layout["vertical"]:
                        _append_rounded_segment(second_tick_tris, x - extent, y, x + extent, y, tick_width)
                    else:
                        _append_rounded_segment(second_tick_tris, x, y - extent, x, y + extent, tick_width)
                else:
                    extent = (self._major_tick_length if is_major else self._micro_tick_length) * scale
                    target = major_tick_tris if is_major else minor_tick_tris
                    if layout["vertical"]:
                        direction = 1.0 if self._position == "LEFT" else -1.0
                        _append_rounded_segment(target, x, y, x + direction * extent, y, tick_width)
                    else:
                        direction = -1.0 if self._position == "TOP" else 1.0
                        _append_rounded_segment(
                            target,
                            x,
                            y,
                            x,
                            y + direction * extent,
                            tick_width,
                        )
            _draw_uniform_batch(shader, batch_for_shader, "TRIS", minor_tick_tris, minor)
            _draw_uniform_batch(shader, batch_for_shader, "TRIS", major_tick_tris, major)
            _draw_uniform_batch(shader, batch_for_shader, "TRIS", second_tick_tris, second)

            preferences = fbp_get_addon_preferences(context)
            scale_ui = max(0.75, self._ui_scale)
            if layout["vertical"]:
                cursor_side = 1.0 if self._position == "LEFT" else -1.0
                opposite_side = -cursor_side
            else:
                cursor_side = -1.0 if self._position == "TOP" else 1.0
                opposite_side = -cursor_side

            # Native Blender Timeline markers are distinct from FBP bookmarks.
            # They remain close to the cursor side and use a thin stem plus M.
            self._native_marker_hit_records = []
            marker_font_size = max(8, int(round(9 * scale_ui)))
            for record in tuple(self._native_marker_records or ()):
                frame = int(record["frame"])
                if frame < int(left) or frame > int(right):
                    continue
                mx, my = self._frame_position(frame, left, right, layout)
                selected = bool(record.get("selected", False))
                marker_color = palette["accent"] if selected else (*secondary[:3], 0.72)
                marker_line = []
                offset = 8.0 * scale_ui
                if layout["vertical"]:
                    end_x, end_y = mx + cursor_side * offset, my
                    _append_rounded_segment(marker_line, mx, my, end_x, end_y, max(0.65, self._line_width * scale_ui))
                    text = "M"
                    blf.size(0, marker_font_size)
                    text_w, text_h = blf.dimensions(0, text)
                    text_x = end_x + (3.0 * scale_ui if cursor_side > 0 else -text_w - 3.0 * scale_ui)
                    text_y = end_y - text_h * 0.5
                else:
                    end_x, end_y = mx, my + cursor_side * offset
                    _append_rounded_segment(marker_line, mx, my, end_x, end_y, max(0.65, self._line_width * scale_ui))
                    text = "M"
                    blf.size(0, marker_font_size)
                    text_w, text_h = blf.dimensions(0, text)
                    text_x = end_x - text_w * 0.5
                    text_y = end_y + (3.0 * scale_ui if cursor_side > 0 else -text_h - 3.0 * scale_ui)
                _draw_uniform_batch(shader, batch_for_shader, "TRIS", marker_line, marker_color)
                _draw_text(blf, text, text_x, text_y, marker_font_size, marker_color)
                self._native_marker_hit_records.append({"record": record, "x": float(end_x), "y": float(end_y)})

            # Onion-skin handles live on the side opposite the current-frame
            # cursor label, so they never disappear under the axis or playhead.
            show_onion = bool(getattr(preferences, "gp_scrub_show_onion_handles", True))
            self._onion_before_handle = None
            self._onion_after_handle = None
            onion = _grease_pencil_onion_settings(context, self._object, self._keyframe_record_numbers) if show_onion else None
            if onion is not None:
                onion_line_width = max(0.65, 0.9 * scale_ui)
                onion_handle_radius = _ONION_HANDLE_RADIUS_PX * scale_ui
                lane_offset = 15.0 * scale_ui
                for side, amount, color in (
                    ("BEFORE", onion["before"], onion["before_color"]),
                    ("AFTER", onion["after"], onion["after_color"]),
                ):
                    endpoint_frame = _onion_endpoint_frame(
                        self._current_frame,
                        amount,
                        side,
                        onion["mode"],
                        onion["keyframes"],
                    )
                    endpoint_frame = max(int(left), min(int(right), int(endpoint_frame)))
                    axis_end_x, axis_end_y = self._frame_position(endpoint_frame, left, right, layout)
                    if layout["vertical"]:
                        start_x, start_y = current_x + opposite_side * lane_offset, current_y
                        end_x, end_y = current_x + opposite_side * lane_offset, axis_end_y
                    else:
                        start_x, start_y = current_x, current_y + opposite_side * lane_offset
                        end_x, end_y = axis_end_x, current_y + opposite_side * lane_offset
                    if int(amount) <= 0:
                        tangent = -1.0 if side == "BEFORE" else 1.0
                        if layout["vertical"] and self._invert_vertical:
                            tangent = -tangent
                        if layout["vertical"]:
                            end_y += tangent * 7.0 * scale_ui
                        else:
                            end_x += tangent * 7.0 * scale_ui
                    onion_color = (*color[:3], min(0.52, max(0.16, color[3] * 0.72)))
                    onion_tris = []
                    _append_rounded_segment(onion_tris, current_x, current_y, start_x, start_y, max(0.55, onion_line_width * 0.75))
                    _append_rounded_segment(onion_tris, start_x, start_y, end_x, end_y, onion_line_width)
                    _draw_uniform_batch(shader, batch_for_shader, "TRIS", onion_tris, onion_color)
                    handle_tris = []
                    _append_circle_triangles(handle_tris, end_x, end_y, onion_handle_radius, segments=14)
                    handle_color = (*color[:3], min(0.96, max(0.48, color[3] + 0.30)))
                    _draw_uniform_batch(shader, batch_for_shader, "TRIS", handle_tris, handle_color)
                    if side == "BEFORE":
                        self._onion_before_handle = (float(end_x), float(end_y))
                    else:
                        self._onion_after_handle = (float(end_x), float(end_y))

            # FBP bookmarks are offset farther from the axis than native
            # markers. A thin stem reaches the timeline and a triangle points
            # back toward it. Selection uses a brighter variant of the tag.
            self._bookmark_hit_records = []
            if bool(getattr(preferences, "gp_scrub_show_bookmarks", True)):
                try:
                    bookmark_distance = max(10.0, min(96.0, float(getattr(preferences, "gp_scrub_bookmark_distance", 21.0))))
                    triangle_scale = max(0.45, min(3.0, float(getattr(preferences, "gp_scrub_bookmark_triangle_scale", 1.0))))
                    bookmark_stem_width = max(0.4, min(4.0, float(getattr(preferences, "gp_scrub_bookmark_stem_width", 0.9))))
                    bookmark_label_scale = max(0.6, min(2.5, float(getattr(preferences, "gp_scrub_bookmark_label_scale", 1.0))))
                    bookmark_label_gap = max(0.0, min(32.0, float(getattr(preferences, "gp_scrub_bookmark_label_gap", 5.0))))
                except (TypeError, ValueError, OverflowError, AttributeError, ReferenceError):
                    bookmark_distance, triangle_scale = 21.0, 1.0
                    bookmark_stem_width, bookmark_label_scale, bookmark_label_gap = 0.9, 1.0, 5.0
                for record in tuple(self._bookmark_records or ()):
                    frame = int(record["frame"])
                    if frame < int(left) or frame > int(right):
                        continue
                    axis_x, axis_y = self._frame_position(frame, left, right, layout)
                    selected = bool(record.get("selected", False))
                    color = _bookmark_color(record.get("color_tag"), selected=selected)
                    stem_width = max(0.4, bookmark_stem_width * (1.35 if selected else 1.0) * scale_ui)
                    base_offset = bookmark_distance * scale_ui
                    triangle_depth = max(4.0, 8.0 * triangle_scale) * scale_ui
                    tip_offset = max(2.0 * scale_ui, base_offset - triangle_depth)
                    half_base = (5.4 if selected else 4.5) * triangle_scale * scale_ui
                    stem = []
                    if layout["vertical"]:
                        tip_x, tip_y = axis_x + opposite_side * tip_offset, axis_y
                        base_x, base_y = axis_x + opposite_side * base_offset, axis_y
                        _append_rounded_segment(stem, axis_x, axis_y, tip_x, tip_y, stem_width)
                        triangle = (
                            (tip_x, tip_y),
                            (base_x, base_y - half_base),
                            (base_x, base_y + half_base),
                        )
                        label_x = base_x + (bookmark_label_gap * scale_ui if opposite_side > 0 else -bookmark_label_gap * scale_ui)
                        label_y = base_y
                    else:
                        tip_x, tip_y = axis_x, axis_y + opposite_side * tip_offset
                        base_x, base_y = axis_x, axis_y + opposite_side * base_offset
                        _append_rounded_segment(stem, axis_x, axis_y, tip_x, tip_y, stem_width)
                        triangle = (
                            (tip_x, tip_y),
                            (base_x - half_base, base_y),
                            (base_x + half_base, base_y),
                        )
                        label_x = base_x
                        label_y = base_y + (bookmark_label_gap * scale_ui if opposite_side > 0 else -bookmark_label_gap * scale_ui)
                    _draw_uniform_batch(shader, batch_for_shader, "TRIS", stem, color)
                    _draw_uniform_batch(shader, batch_for_shader, "TRIS", triangle, color)
                    hit_x = (tip_x + base_x * 2.0) / 3.0
                    hit_y = (tip_y + base_y * 2.0) / 3.0
                    hit_record = {
                        "record": record,
                        "x": float(hit_x),
                        "y": float(hit_y),
                        "triangle": tuple((float(x), float(y)) for x, y in triangle),
                        "label_bounds": None,
                    }
                    self._bookmark_hit_records.append(hit_record)
                    if selected or str(record.get("uid") or "") == str(getattr(self, "_hover_bookmark_uid", "") or ""):
                        label = str(record.get("name") or "Bookmark")
                        font_size = max(8, int(round(9 * bookmark_label_scale * scale_ui)))
                        blf.size(0, font_size)
                        text_w, text_h = blf.dimensions(0, label)
                        if layout["vertical"]:
                            text_x = label_x if opposite_side > 0 else label_x - text_w
                            text_y = label_y - text_h * 0.5
                        else:
                            text_x = label_x - text_w * 0.5
                            text_y = label_y if opposite_side > 0 else label_y - text_h
                        _draw_text(blf, label, text_x, text_y, font_size, color)
                        padding = 3.0 * scale_ui
                        hit_record["label_bounds"] = (
                            float(text_x - padding),
                            float(text_y - padding),
                            float(text_x + text_w + padding),
                            float(text_y + text_h + padding),
                        )

            grouped = {}
            for frame, key_type, _is_active, selected in _keyframe_records_in_range(
                self._keyframe_records,
                self._keyframe_record_numbers,
                left,
                right,
            ):
                x, y = self._frame_position(frame, left, right, layout)
                radius = keyframe_radius(
                    key_type,
                    self._ui_scale,
                    palette.get("keyframe_scale_factor", 1.0),
                )
                state = "selected" if selected else "passive"
                fill = keyframe_colors.get(key_type, keyframe_colors.get("KEYFRAME", {})).get(
                    state,
                    palette["keyframe"],
                )
                key_border = border_selected if selected else border
                bucket = grouped.setdefault((fill, key_border), [[], []])
                bucket[0].extend(_diamond_triangles(x, y, radius))
                bucket[1].extend(_diamond_lines(x, y, radius))
            for (fill, key_border), (triangles, lines) in grouped.items():
                _draw_uniform_batch(shader, batch_for_shader, "TRIS", triangles, fill)
                _draw_uniform_batch(shader, batch_for_shader, "LINES", lines, key_border)

            snap_label = playhead_snap_label(
                self._snap_settings,
                shift=self._shift_held,
                ctrl=self._ctrl_held,
                slow_factor=self._slow_factor,
            )
            direct_factor = float(getattr(self, "_shortcut_direct_factor", 0.0) or 0.0)
            if shortcut_pending and direct_factor > 0.0:
                snap_label += " · Direct" if direct_factor >= 0.999 else f" · Magnet {int(round(direct_factor * 100.0))}%"
            if persistent and not shortcut_pending:
                snap_label = (
                    "A bookmark · G move · Shift+D duplicate · X delete · "
                    "double-click rename · R drawing type · "
                    f"Wheel zoom · {primary_modifier_name()}+wheel pan · drag onion dots"
                )
            if layout["vertical"]:
                top_frame, bottom_frame = (left, right) if self._invert_vertical else (right, left)
                endpoint_x = float(layout["x"]) + 13.0
                if self._position == "RIGHT":
                    blf.size(0, 10)
                    endpoint_width = max(
                        blf.dimensions(0, str(top_frame))[0],
                        blf.dimensions(0, str(bottom_frame))[0],
                    )
                    endpoint_x = float(layout["x"]) - 13.0 - float(endpoint_width)
                _draw_text(blf, top_frame, endpoint_x, layout["y1"] - 5.0, 10, secondary)
                _draw_text(blf, bottom_frame, endpoint_x, layout["y0"] - 5.0, 10, secondary)
                if bool(getattr(self, "_show_info", False)):
                    info_x = float(layout["x"]) + 13.0
                    if self._position == "RIGHT":
                        blf.size(0, 10)
                        info_x = (
                            float(layout["x"])
                            - 13.0
                            - float(blf.dimensions(0, str(snap_label))[0])
                        )
                    _draw_text(blf, snap_label, info_x, layout["y0"] + 12.0, 10, secondary)
            else:
                text_y = (
                    float(layout["y"]) - 24.0
                    if self._position == "TOP"
                    else float(layout["y"]) + 14.0
                )
                _draw_text(blf, left, layout["x0"] - 7.0, text_y, 10, secondary)
                _draw_text(blf, right, layout["x1"] - 7.0, text_y, 10, secondary)
                if bool(getattr(self, "_show_info", False)):
                    info_y = (
                        float(layout["y"]) - 42.0
                        if self._position == "TOP"
                        else float(layout["y"]) + 31.0
                    )
                    _draw_text(blf, snap_label, layout["x0"], info_y, 10, secondary)

            # Draw the current-frame cursor last so no timeline text or marker can cover it.
            label_text = str(int(self._current_frame))
            font_size = max(9, int(round(12 * self._cursor_label_scale * max(0.8, self._ui_scale))))
            blf.size(0, font_size)
            text_w, text_h = blf.dimensions(0, label_text)
            pad_x = 7.0 * self._cursor_label_scale * max(0.8, self._ui_scale)
            pad_y = 4.0 * self._cursor_label_scale * max(0.8, self._ui_scale)
            box_w, box_h = text_w + pad_x * 2.0, text_h + pad_y * 2.0
            cursor_tris = []
            if layout["vertical"]:
                direction = 1.0 if self._position == "LEFT" else -1.0
                gap = 12.0 * max(0.8, self._ui_scale)
                if direction > 0:
                    box_x0, box_x1 = current_x + gap, current_x + gap + box_w
                else:
                    box_x0, box_x1 = current_x - gap - box_w, current_x - gap
                box_y0, box_y1 = current_y - box_h * 0.5, current_y + box_h * 0.5
                connector_end = box_x0 if direction > 0 else box_x1
                _append_rounded_segment(cursor_tris, current_x, current_y, connector_end, current_y, self._cursor_width * max(0.75, self._ui_scale))
            else:
                gap = 12.0 * max(0.8, self._ui_scale)
                box_x0, box_x1 = current_x - box_w * 0.5, current_x + box_w * 0.5
                if self._position == "TOP":
                    box_y0, box_y1 = current_y - gap - box_h, current_y - gap
                    connector_end = box_y1
                else:
                    box_y0, box_y1 = current_y + gap, current_y + gap + box_h
                    connector_end = box_y0
                _append_rounded_segment(
                    cursor_tris,
                    current_x,
                    current_y,
                    current_x,
                    connector_end,
                    self._cursor_width * max(0.75, self._ui_scale),
                )
            self._cursor_label_bounds = (
                float(box_x0),
                float(box_y0),
                float(box_x1),
                float(box_y1),
            )
            cursor_tris.extend(_rounded_rect_triangles(box_x0, box_y0, box_x1, box_y1, 4.5 * self._cursor_label_scale * max(0.8, self._ui_scale)))
            _draw_uniform_batch(shader, batch_for_shader, "TRIS", cursor_tris, self._cursor_color)
            cursor_text_x = box_x0 + (box_w - text_w) * 0.5
            cursor_text_y = box_y0 + (box_h - text_h) * 0.5
            _draw_text(blf, label_text, cursor_text_x, cursor_text_y, font_size, self._cursor_text_color)
        except Exception as exc:
            fbp_warn("Could not draw the Grease Pencil scrub timeline", exc)
        finally:
            try:
                import gpu
                gpu.state.line_width_set(1.0)
                gpu.state.blend_set("NONE")
            except (ImportError, AttributeError, RuntimeError):
                pass

    def _cleanup(self, context):
        global _ACTIVE_OPERATOR
        if self._cleaned:
            return
        self._cleaned = True
        if self._interaction == "BOOKMARK_MOVE":
            self._cancel_bookmark_transform(context)
        elif self._interaction == "KEY_MOVE":
            self._restore_transform_to_original()
            if self._duplicate_pending:
                for layer, number in reversed(self._duplicate_sources):
                    self._remove_layer_frame(layer, number)
        if bool(getattr(self, "_is_persistent", False)):
            _remember_persistent_scrub_binding(
                context,
                getattr(self, "_object", None),
                area_pointer=getattr(self, "_area_pointer", 0),
            )
        self._is_persistent = False
        self._shortcut_pending = False
        self._interaction = ""
        self._interaction_event_type = ""
        self._transform_sources = ()
        self._transform_delta = 0
        self._collision_stashes = ()
        self._duplicate_pending = False
        self._duplicate_sources = ()
        self._cursor_over_axis = False
        self._cursor_kind = ""
        self._cursor_label_bounds = None
        self._onion_before_handle = None
        self._onion_after_handle = None
        self._bookmark_records = ()
        self._native_marker_records = ()
        self._bookmark_hit_records = ()
        self._native_marker_hit_records = ()
        self._hover_bookmark_uid = ""
        self._bookmark_transform_sources = ()
        self._bookmark_transform_created = ()
        self._bookmark_transform_delta = 0
        self._onion_drag_original = None
        self._restore_onion_skin()
        if self._draw_handle is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, "WINDOW")
            except FBP_DATA_ERRORS:
                pass
            self._draw_handle = None
        if self._timer is not None:
            try:
                window_manager = self._window_manager or context.window_manager
                window_manager.event_timer_remove(self._timer)
            except FBP_DATA_ERRORS:
                pass
            self._timer = None
        self._window_manager = None
        self._window = None
        self._workspace = None
        self._screen = None
        self._area = None
        self._region = None
        self._region_pointer = 0
        self._cursor_in_owned_window = False
        self._magnetic_offset = 0.0
        self._magnetic_target_offset = 0.0
        restore_modal_cursor(context)
        self._tag_redraw()
        if _ACTIVE_OPERATOR is self:
            _ACTIVE_OPERATOR = None
        _tag_all_view3d_redraw()

    def invoke(self, context, event):
        global _ACTIVE_OPERATOR
        if not _is_view3d_context(context, require_window_region=True) or _ACTIVE_OPERATOR is not None:
            return {"CANCELLED"}
        target_object = _resolve_scrub_target_object(
            context,
            explicit_name=getattr(self, "target_object_name", ""),
        )
        if bool(getattr(getattr(context, "screen", None), "is_animation_playing", False)):
            self.report({"INFO"}, "Stop playback before timeline scrubbing")
            return {"CANCELLED"}

        self._area = context.area
        self._region = context.region
        self._area_pointer = int(context.area.as_pointer())
        self._region_pointer = int(context.region.as_pointer())
        self._scene_pointer = int(context.scene.as_pointer())
        self._window = context.window
        self._window_pointer = int(context.window.as_pointer()) if context.window is not None else 0
        workspace = getattr(context.window, "workspace", None) if context.window is not None else None
        screen = getattr(context.window, "screen", None) if context.window is not None else getattr(context, "screen", None)
        self._workspace = workspace
        self._screen = screen
        self._workspace_pointer = int(workspace.as_pointer()) if workspace is not None else 0
        self._screen_pointer = int(screen.as_pointer()) if screen is not None else 0
        self._cleaned = False
        self._object = target_object
        self._object_name = str(getattr(self._object, "name", "") or "")
        self._object_data_name = str(
            getattr(getattr(self._object, "data", None), "name", "") or ""
        )
        self._onion_skin_overlay = None
        self._onion_skin_was_enabled = None
        self._session_start_frame = int(context.scene.frame_current)
        self._origin_frame = self._session_start_frame
        self._current_frame = self._session_start_frame
        self._overflow_offset = 0
        self._has_frame_change = False
        self._is_persistent = bool(self.start_persistent)
        if self._is_persistent and self._object is not None:
            _remember_persistent_scrub_binding(
                context,
                self._object,
                area_pointer=self._area_pointer,
            )
        self._persistent_before_shortcut = False
        self._persistent_view_before = None
        self._hold_center = float(self._session_start_frame)
        self._hold_radius = int(self._maximum_range)
        self._shortcut_pending = False
        self._shortcut_moved = False
        self._shortcut_anchor_pending = False
        self._interaction = ""
        self._interaction_event_type = ""
        self._transform_sources = ()
        self._transform_delta = 0
        self._collision_stashes = ()
        self._duplicate_pending = False
        self._duplicate_sources = ()
        self._preview_signature = None
        self._hover_frame = None
        self._cursor_label_bounds = None
        self._cache_checked_at = 0.0
        self._cursor_over_axis = False
        self._cursor_kind = ""
        self._shortcut_direct_factor = 0.0
        self._shortcut_direct_locked = False
        self._relative_anchor_frame = float(self._session_start_frame)
        self._onion_before_handle = None
        self._onion_after_handle = None
        self._bookmark_records = ()
        self._native_marker_records = ()
        self._bookmark_hit_records = ()
        self._native_marker_hit_records = ()
        self._hover_bookmark_uid = ""
        self._bookmark_transform_sources = ()
        self._bookmark_transform_created = ()
        self._bookmark_transform_delta = 0
        self._onion_drag_original = None
        self._magnetic_offset = 0.0
        self._magnetic_target_offset = 0.0
        self._magnetic_last_tick = time.monotonic()
        self._cursor_in_owned_window = True
        (
            self._maximum_range,
            self._position,
            line_color,
            frame_tick_color,
            major_tick_color,
            second_tick_color,
            text_color,
            cursor_color,
            cursor_text_color,
            self._sensitivity,
            self._slow_factor,
            self._length_ratio,
            self._edge_offset,
            self._tick_scale,
            self._line_width,
            self._cursor_width,
            self._cursor_label_scale,
            self._major_interval,
            self._micro_tick_length,
            self._major_tick_length,
            self._second_tick_length,
            self._invert_vertical,
        ) = scrub_preferences(context)
        self._vertical = self._position in {"LEFT", "RIGHT"}
        self._line_color = (*line_color, 1.0)
        self._frame_tick_color = frame_tick_color
        self._major_tick_color = major_tick_color
        self._second_tick_color = second_tick_color
        self._text_color = (*text_color, 1.0)
        self._cursor_color = (*cursor_color, 1.0)
        self._cursor_text_color = (*cursor_text_color, 1.0)
        _apply_inverted_scrub_ink(self, context)
        preferences = fbp_get_addon_preferences(context)
        self._show_info = bool(getattr(preferences, "gp_scrub_show_info", False))
        self._sync_magnetic_preferences(context)
        self._activation_event_type = str(getattr(event, "type", "") or "")
        self._mouse_x = float(getattr(event, "mouse_region_x", 0.0) or 0.0)
        self._mouse_y = float(getattr(event, "mouse_region_y", 0.0) or 0.0)
        self._drag_anchor_x = self._mouse_x
        self._drag_anchor_y = self._mouse_y
        self._shift_held = bool(getattr(event, "shift", False))
        self._ctrl_held = primary_modifier_pressed(event)
        self._edge_direction = 0
        self._edge_since = 0.0
        self._edge_last_repeat = 0.0
        self._preview_signature = preview_range_signature(context.scene)
        if bool(self._preview_signature[0]):
            preview_minimum = int(self._preview_signature[1])
            preview_maximum = int(self._preview_signature[2])
            self._view_center = (float(preview_minimum) + float(preview_maximum)) * 0.5
            self._view_radius = max(1, preview_maximum - preview_minimum + 1)
        else:
            self._view_center = float(self._session_start_frame)
            self._view_radius = int(self._maximum_range)
        self._snap_settings = playhead_snap_settings(context.scene)
        self._refresh_keyframe_cache(context)
        self._palette = blender_theme_palette(context)
        try:
            self._ui_scale = max(0.5, float(context.preferences.system.ui_scale))
        except FBP_DATA_ERRORS:
            self._ui_scale = 1.0
        self._window_manager = context.window_manager

        try:
            self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
                self._draw_callback,
                (),
                "WINDOW",
                "POST_PIXEL",
            )
            self._timer = context.window_manager.event_timer_add(_TIMER_INTERVAL, window=context.window)
            context.window_manager.modal_handler_add(self)
            if self._is_persistent:
                self._set_idle_hover(context)
            else:
                self._begin_shortcut(context, event)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not start Grease Pencil frame scrubbing", exc)
            self._cleanup(context)
            return {"CANCELLED"}
        _ACTIVE_OPERATOR = self
        self._tag_redraw()
        _tag_all_view3d_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if self._cleaned:
            return {"CANCELLED"}
        try:
            owned_area = getattr(self, "_area", None)
            owner_window = getattr(self, "_window", None)
            owner_workspace = getattr(self, "_workspace", None)
            owner_screen = getattr(self, "_screen", None)
            window_manager = getattr(context, "window_manager", None) or getattr(self, "_window_manager", None)
            known_windows = tuple(getattr(window_manager, "windows", ()) or ()) if window_manager is not None else ()
            window_valid = bool(
                owner_window is not None
                and any(
                    int(candidate.as_pointer()) == int(getattr(self, "_window_pointer", 0) or 0)
                    for candidate in known_windows
                )
                and int(owner_window.as_pointer()) == int(getattr(self, "_window_pointer", 0) or 0)
            )
            current_workspace = getattr(owner_window, "workspace", None) if window_valid else None
            current_screen = getattr(owner_window, "screen", None) if window_valid else None
            workspace_valid = bool(
                current_workspace is not None
                and owner_workspace is not None
                and int(current_workspace.as_pointer()) == int(getattr(self, "_workspace_pointer", 0) or 0)
                and int(owner_workspace.as_pointer()) == int(getattr(self, "_workspace_pointer", 0) or 0)
            )
            screen_valid = bool(
                current_screen is not None
                and owner_screen is not None
                and int(current_screen.as_pointer()) == int(getattr(self, "_screen_pointer", 0) or 0)
                and int(owner_screen.as_pointer()) == int(getattr(self, "_screen_pointer", 0) or 0)
            )
            owner_areas = tuple(getattr(owner_screen, "areas", ()) or ()) if owner_screen is not None else ()
            owned_area_valid = bool(
                owned_area is not None
                and any(
                    int(candidate.as_pointer()) == int(self._area_pointer)
                    for candidate in owner_areas
                )
                and str(getattr(owned_area, "type", "") or "") == "VIEW_3D"
                and int(owned_area.as_pointer()) == int(self._area_pointer)
            )
            owned_regions = tuple(getattr(owned_area, "regions", ()) or ()) if owned_area is not None else ()
            owned_region_valid = bool(
                getattr(self, "_region", None) is not None
                and int(getattr(self, "_region_pointer", 0) or 0) > 0
                and any(
                    int(candidate.as_pointer()) == int(self._region_pointer)
                    for candidate in owned_regions
                )
                and str(getattr(self._region, "type", "") or "") == "WINDOW"
                and int(self._region.as_pointer()) == int(self._region_pointer)
            )
            bound_object_valid = self._resolve_bound_object(context)
            gp_context_valid = _is_view3d_context(context)
            valid_session = bool(
                owned_area_valid
                and owned_region_valid
                and window_valid
                and workspace_valid
                and screen_valid
                and persistent_scrub_session_valid(
                    persistent=bool(getattr(self, "_is_persistent", False)),
                    bound_object_valid=bound_object_valid,
                    gp_context_valid=gp_context_valid,
                )
            )
        except FBP_DATA_ERRORS:
            valid_session = False
        if not valid_session:
            self._cleanup(context)
            return {"FINISHED"}
        try:
            if int(context.scene.as_pointer()) != int(self._scene_pointer):
                self._cleanup(context)
                return {"FINISHED"}
        except FBP_DATA_ERRORS:
            self._cleanup(context)
            return {"FINISHED"}

        event_type = str(getattr(event, "type", "") or "")
        event_value = str(getattr(event, "value", "") or "")
        try:
            in_owned_area = bool(
                context.area is not None
                and int(context.area.as_pointer()) == int(self._area_pointer)
            )
        except FBP_DATA_ERRORS:
            in_owned_area = False
        in_window = bool(
            in_owned_area
            and str(getattr(getattr(context, "region", None), "type", "") or "") == "WINDOW"
        )
        previous_shift = self._shift_held
        previous_ctrl = self._ctrl_held
        self._shift_held = bool(getattr(event, "shift", False))
        self._ctrl_held = primary_modifier_pressed(event)
        modifier_changed = previous_shift != self._shift_held or previous_ctrl != self._ctrl_held

        if scrub_undo_passthrough(
            event_type,
            event_value,
            ctrl=self._ctrl_held,
            oskey=bool(getattr(event, "oskey", False)),
        ):
            # Let the native mode keymap execute Undo/Redo. Roll back only a
            # currently provisional slider transform so it cannot be replayed
            # by the next mouse move after Blender restores the undo snapshot.
            if self._interaction:
                self._finish_interaction(context, cancel=True)
            self._set_hover_cursor(context, False)
            return {"PASS_THROUGH"}

        if event_type == "WINDOW_DEACTIVATE":
            self._cursor_in_owned_window = False
            self._set_hover_cursor(context, False)
            if self._shortcut_pending:
                self._shortcut_pending = False
                self._restore_onion_skin()
                if self._persistent_before_shortcut:
                    self._is_persistent = True
                    if self._persistent_view_before is not None:
                        self._view_center, self._view_radius = self._persistent_view_before
                    self._persistent_view_before = None
                    self._magnetic_target_offset = 0.0
                    self._tag_redraw()
                else:
                    if self._session_changed(context.scene):
                        self._set_frame(context.scene, self._session_start_frame)
                    self._cleanup(context)
                    return {"CANCELLED"}
            return {"PASS_THROUGH"} if self._is_persistent else {"RUNNING_MODAL"}

        if (
            self._is_persistent
            and not self._shortcut_pending
            and in_owned_area
            and event_value == "PRESS"
            and event_type in {"GRLESS", "COMMA"}
            and (event_type != "COMMA" or self._shift_held)
        ):
            self._begin_shortcut(context, event)
            return {"RUNNING_MODAL"}

        if self._shortcut_pending and scrub_activation_released(
            event_type,
            event_value,
            self._activation_event_type,
        ):
            return self._release_shortcut(context)

        if event_type == "ESC" and event_value in {"PRESS", ""}:
            if self._interaction:
                self._finish_interaction(context, cancel=True)
                return {"RUNNING_MODAL"}
            if self._shortcut_pending:
                self._shortcut_pending = False
                self._restore_onion_skin()
                if self._persistent_before_shortcut:
                    self._is_persistent = True
                    if self._persistent_view_before is not None:
                        self._view_center, self._view_radius = self._persistent_view_before
                    self._tag_redraw()
                    return {"RUNNING_MODAL"}
                if self._session_changed(context.scene):
                    self._set_frame(context.scene, self._session_start_frame)
                self._cleanup(context)
                return {"CANCELLED"}
            return {"PASS_THROUGH"}

        if event_type == "RIGHTMOUSE":
            if self._interaction:
                self._finish_interaction(context, cancel=True)
                return {"RUNNING_MODAL"}
            if (
                self._is_persistent
                and not self._shortcut_pending
                and in_window
                and event_value == "PRESS"
                and (self._mouse_in_axis(context) or self._bookmark_hit() is not None)
            ):
                bookmark = self._bookmark_hit()
                if bookmark is not None:
                    if not bool(bookmark.get("selected", False)):
                        self._select_bookmark_record(context, bookmark)
                else:
                    hit = self._keyframe_hit(context)
                    if hit is not None:
                        hit_was_selected = any(
                            int(getattr(frame, "frame_number", 0) or 0) == int(hit)
                            and bool(getattr(frame, "select", False))
                            for _layer, frame in grease_pencil_editable_frames(self._object)
                        )
                        if not hit_was_selected:
                            select_grease_pencil_frame_number(self._object, hit)
                            self._refresh_keyframe_cache(context)
                try:
                    bpy.ops.wm.call_menu(
                        name=FBP_MT_GreasePencilScrubContextMenu.bl_idname
                    )
                except FBP_DATA_ERRORS as exc:
                    fbp_warn(
                        "Could not open the Grease Pencil Scrub Slider context menu",
                        exc,
                    )
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"} if self._shortcut_pending else {"PASS_THROUGH"}

        if (
            self._shortcut_pending
            and not self._shortcut_anchor_pending
            and modifier_changed
            and in_window
        ):
            self._target_from_mouse(context)
            self._tag_redraw()
        if event_type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            self._cursor_in_owned_window = bool(in_window)
            if not in_window:
                self._set_hover_cursor(context, False)
                self._magnetic_target_offset = 0.0
                return {"RUNNING_MODAL"} if self._shortcut_pending else {"PASS_THROUGH"}
            try:
                next_mouse_x = float(getattr(event, "mouse_region_x"))
                next_mouse_y = float(getattr(event, "mouse_region_y"))
            except (AttributeError, TypeError, ValueError, OverflowError):
                return {"RUNNING_MODAL"} if self._shortcut_pending else {"PASS_THROUGH"}
            if self._shortcut_pending and self._shortcut_anchor_pending:
                # The activation event may carry stale coordinates. Treat the
                # first real mouse event only as the trusted anchor; it must
                # never change the current frame or count as a drag.
                self._mouse_x = next_mouse_x
                self._mouse_y = next_mouse_y
                self._shortcut_start_x = next_mouse_x
                self._shortcut_start_y = next_mouse_y
                self._drag_anchor_x = next_mouse_x
                self._drag_anchor_y = next_mouse_y
                self._shortcut_moved = False
                self._shortcut_anchor_pending = False
                self._tag_redraw()
                return {"RUNNING_MODAL"}
            self._mouse_x = next_mouse_x
            self._mouse_y = next_mouse_y
            if self._is_persistent and not self._shortcut_pending and not self._interaction:
                self._update_magnetic_target(context)
            if self._shortcut_pending:
                distance = math.hypot(
                    self._mouse_x - self._shortcut_start_x,
                    self._mouse_y - self._shortcut_start_y,
                )
                if not self._shortcut_moved:
                    if distance < _DRAG_THRESHOLD_PX:
                        self._tag_redraw()
                        return {"RUNNING_MODAL"}
                    self._shortcut_moved = True
                self._target_from_mouse(context)
                self._tag_redraw()
                return {"RUNNING_MODAL"}
            if self._interaction in {"ONION_BEFORE", "ONION_AFTER"}:
                self._update_onion_range(context, self._interaction.removeprefix("ONION_"))
                return {"RUNNING_MODAL"}
            if self._interaction == "BOOKMARK_MOVE":
                self._update_bookmark_transform(context)
                return {"RUNNING_MODAL"}
            if self._interaction == "SCRUB":
                self._set_frame_from_axis(context)
                self._tag_redraw()
                return {"RUNNING_MODAL"}
            if self._interaction == "KEY_PENDING":
                distance = math.hypot(
                    self._mouse_x - self._interaction_start_x,
                    self._mouse_y - self._interaction_start_y,
                )
                if distance >= _DRAG_THRESHOLD_PX:
                    self._interaction = "KEY_MOVE"
                    self._update_key_transform(context)
                return {"RUNNING_MODAL"}
            if self._interaction == "KEY_MOVE":
                self._update_key_transform(context)
                return {"RUNNING_MODAL"}
            if self._interaction == "PAN":
                delta = (
                    self._mouse_y - self._interaction_start_y
                    if self._vertical
                    else self._mouse_x - self._interaction_start_x
                )
                if self._vertical and self._invert_vertical:
                    delta = -delta
                self._pan_view_pixels(
                    context,
                    delta,
                    start_center=self._interaction_start_center,
                )
                return {"RUNNING_MODAL"}
            if self._interaction == "ZOOM":
                delta = self._mouse_y - self._interaction_start_y
                self._view_center = self._interaction_start_center
                self._view_radius = self._interaction_start_radius
                self._zoom_view(
                    context,
                    math.exp(max(-2.0, min(2.0, -delta * 0.012))),
                    pivot_frame=self._interaction_start_frame,
                )
                return {"RUNNING_MODAL"}
            self._set_idle_hover(context)
            return {"PASS_THROUGH"}

        if event_type == "TIMER":
            try:
                owned_timer = getattr(event, "timer", None) is self._timer
            except FBP_DATA_ERRORS:
                owned_timer = False
            if owned_timer:
                if self._shortcut_pending and in_window:
                    self._edge_tick(context)
                elif self._is_persistent:
                    cursor_in_window = bool(self._cursor_in_owned_window)
                    self._tick_magnetic_hover(
                        context,
                        release=scrub_magnet_should_release(
                            event_type,
                            event_in_window=in_window,
                            cursor_in_owned_window=cursor_in_window,
                        ),
                    )
                    if cursor_in_window and not self._interaction:
                        self._set_idle_hover(context)
            return {"RUNNING_MODAL"} if self._shortcut_pending else {"PASS_THROUGH"}

        if self._shortcut_pending:
            return {"RUNNING_MODAL"}
        if (
            self._interaction in {"PAN", "ZOOM"}
            and event_value == "RELEASE"
            and event_type == self._interaction_event_type
        ):
            self._finish_interaction(context)
            return {"RUNNING_MODAL"}
        if not self._is_persistent or not in_window:
            return {"PASS_THROUGH"}

        if self._mouse_in_axis(context):
            if self._handle_wheel_navigation(context, event):
                return {"RUNNING_MODAL"}
            navigation_action = native_view2d_navigation_action(
                context.window_manager,
                event,
            )
            if navigation_action and self._handle_native_navigation(
                context,
                event,
                navigation_action,
            ):
                return {"RUNNING_MODAL"}

        if event_type == "LEFTMOUSE":
            bookmark = self._bookmark_hit()
            axis_inside = self._mouse_in_axis(context)
            if event_value == "PRESS" and self._interaction in {"KEY_MOVE", "BOOKMARK_MOVE"}:
                self._finish_interaction(context)
                return {"RUNNING_MODAL"}
            if event_value == "DOUBLE_CLICK" and bookmark is not None:
                self._select_bookmark_record(context, bookmark)
                try:
                    bpy.ops.fbp.rename_scrub_bookmark(
                        "INVOKE_DEFAULT",
                        bookmark_uid=str(bookmark.get("uid") or ""),
                    )
                except FBP_DATA_ERRORS as exc:
                    fbp_warn("Could not rename Scrub Bar bookmark", exc)
                return {"RUNNING_MODAL"}
            if event_value == "PRESS":
                if bookmark is not None:
                    self._select_bookmark_record(
                        context,
                        bookmark,
                        extend=self._shift_held,
                        toggle=self._shift_held,
                    )
                    if not self._shift_held:
                        self._begin_bookmark_transform(context, duplicate=False)
                    return {"RUNNING_MODAL"}
                if not self._shift_held:
                    self._deselect_bookmarks(context)
                if axis_inside:
                    onion_hit = self._onion_handle_hit()
                    if onion_hit is not None:
                        settings = _grease_pencil_onion_settings(context, self._object, self._keyframe_record_numbers)
                        attribute = "ghost_before_range" if onion_hit == "BEFORE" else "ghost_after_range"
                        original = None
                        if settings is not None:
                            try:
                                original = (settings["data"], attribute, int(getattr(settings["data"], attribute)))
                            except FBP_DATA_ERRORS:
                                original = None
                        self._onion_drag_original = original
                        self._interaction = f"ONION_{onion_hit}"
                        self._interaction_event_type = "LEFTMOUSE"
                        self._interaction_start_x = self._mouse_x
                        self._interaction_start_y = self._mouse_y
                        return {"RUNNING_MODAL"}
                    hit = self._keyframe_hit(context)
                    self._interaction_start_x = self._mouse_x
                    self._interaction_start_y = self._mouse_y
                    if hit is not None:
                        hit_was_selected = any(
                            int(getattr(frame, "frame_number", 0) or 0) == int(hit)
                            and bool(getattr(frame, "select", False))
                            for _layer, frame in grease_pencil_editable_frames(self._object)
                        )
                        if self._shift_held or not hit_was_selected:
                            select_grease_pencil_frame_number(
                                self._object,
                                hit,
                                extend=self._shift_held,
                                toggle=self._shift_held,
                            )
                        self._refresh_keyframe_cache(context)
                        self._interaction = "KEY_PENDING"
                        if not self._begin_key_transform(context):
                            self._interaction = ""
                        self._tag_redraw()
                    else:
                        self._interaction = "SCRUB"
                        self._magnetic_target_offset = float(self._magnetic_offset)
                        self._interaction_start_frame = int(context.scene.frame_current)
                        self._set_frame_from_axis(context)
                        self._tag_redraw()
                    return {"RUNNING_MODAL"}
                return {"PASS_THROUGH"}
            if event_value == "RELEASE" and self._interaction in {
                "SCRUB",
                "KEY_PENDING",
                "KEY_MOVE",
                "BOOKMARK_MOVE",
                "ONION_BEFORE",
                "ONION_AFTER",
            }:
                self._finish_interaction(context)
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}

        if event_value == "PRESS" and (self._mouse_in_axis(context) or self._bookmark_hit() is not None):
            bookmark_hit = self._bookmark_hit()
            selected_bookmarks = selected_scrub_bookmark_records(context.scene)
            bookmark_focus = bool(selected_bookmarks or bookmark_hit is not None)
            if event_type in {"X", "DEL"}:
                if bookmark_focus:
                    if not selected_bookmarks and bookmark_hit is not None:
                        self._select_bookmark_record(context, bookmark_hit)
                        selected_bookmarks = selected_scrub_bookmark_records(context.scene)
                    _delete_bookmark_records(context.scene, selected_bookmarks)
                    self._refresh_keyframe_cache(context)
                    self._tag_redraw()
                    return {"RUNNING_MODAL"}
                if not _is_live_grease_pencil_object(self._object):
                    return {"PASS_THROUGH"}
                if self._interaction:
                    self._finish_interaction(context, cancel=True)
                self._delete_selected_keyframes(context)
                return {"RUNNING_MODAL"}
            if event_type == "D" and self._shift_held:
                if bookmark_focus:
                    self._begin_bookmark_transform(context, duplicate=True)
                    return {"RUNNING_MODAL"}
                if not _is_live_grease_pencil_object(self._object):
                    return {"PASS_THROUGH"}
                if not selected_grease_pencil_frames(self._object):
                    hit = self._keyframe_hit(context)
                    if hit is not None:
                        select_grease_pencil_frame_number(self._object, hit)
                        self._refresh_keyframe_cache(context)
                if self._begin_key_duplicate(context):
                    self._interaction = "KEY_MOVE"
                    self._interaction_start_x = self._mouse_x
                    self._interaction_start_y = self._mouse_y
                    self._tag_redraw()
                return {"RUNNING_MODAL"}
            if event_type == "G":
                if bookmark_focus:
                    self._begin_bookmark_transform(context, duplicate=False)
                    return {"RUNNING_MODAL"}
                if not _is_live_grease_pencil_object(self._object):
                    return {"PASS_THROUGH"}
                if self._begin_key_transform(context):
                    self._interaction = "KEY_MOVE"
                    self._interaction_start_x = self._mouse_x
                    self._interaction_start_y = self._mouse_y
                return {"RUNNING_MODAL"}
            if event_type == "R":
                if not _is_live_grease_pencil_object(self._object):
                    return {"PASS_THROUGH"}
                if not selected_grease_pencil_frames(self._object):
                    hit = self._keyframe_hit(context)
                    if hit is not None:
                        select_grease_pencil_frame_number(self._object, hit)
                        self._refresh_keyframe_cache(context)
                if selected_grease_pencil_frames(self._object):
                    try:
                        bpy.ops.wm.call_menu(
                            name=FBP_MT_GreasePencilScrubKeyframeType.bl_idname
                        )
                    except FBP_DATA_ERRORS as exc:
                        fbp_warn("Could not open the Grease Pencil keyframe type menu", exc)
                return {"RUNNING_MODAL"}
            if event_type == "A" and not self._ctrl_held and not self._shift_held:
                try:
                    bpy.ops.fbp.add_scrub_bookmark("INVOKE_DEFAULT")
                except FBP_DATA_ERRORS as exc:
                    fbp_warn("Could not open New Bookmark", exc)
                return {"RUNNING_MODAL"}
            if event_type == "HOME":
                minimum, maximum = scene_frame_bounds(context.scene)
                self._view_center = (minimum + maximum) * 0.5
                self._view_radius = max(1, int(maximum) - int(minimum) + 1)
                self._tag_redraw()
                return {"RUNNING_MODAL"}
            if event_type in {"NUMPAD_PERIOD", "BUTTON4MOUSE"}:
                if not _is_live_grease_pencil_object(self._object):
                    return {"PASS_THROUGH"}
                selected_numbers = tuple(
                    int(frame.frame_number)
                    for _layer, frame in selected_grease_pencil_frames(self._object)
                )
                if selected_numbers:
                    low = min(selected_numbers)
                    high = max(selected_numbers)
                    self._view_center = (low + high) * 0.5
                    self._view_radius = max(2, int(math.ceil((high - low + 1) * 1.2)))
                    self._tag_redraw()
                return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def cancel(self, context):
        if self._interaction:
            self._finish_interaction(context, cancel=True)
        if not self._is_persistent and self._session_changed(context.scene):
            self._set_frame(context.scene, self._session_start_frame)
        self._cleanup(context)


class FBP_OT_ToggleGreasePencilScrubSlider(Operator):
    """Show or hide the persistent interactive slider in the current View3D."""

    bl_idname = "fbp.toggle_grease_pencil_scrub_slider"
    bl_label = "Toggle Scrub Slider"
    bl_description = (
        "Toggle the persistent Scrub Bar in any 3D View mode; tap < for the same "
        "toggle or hold < for momentary scrubbing"
    )
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return _scrub_header_available(context)

    def execute(self, context):
        global _ACTIVE_OPERATOR
        active = _ACTIVE_OPERATOR
        try:
            area_pointer = int(context.area.as_pointer())
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}
        if (
            active is not None
            and bool(getattr(active, "_is_persistent", False))
            and int(getattr(active, "_area_pointer", 0) or 0) == area_pointer
        ):
            active._cleanup(context)
            return {"FINISHED"}
        if active is not None:
            if bool(getattr(active, "_shortcut_pending", False)):
                self.report({"INFO"}, "Release < before toggling the Scrub Slider")
                return {"CANCELLED"}
            active._cleanup(context)

        target_object = _resolve_scrub_target_object(context)
        if target_object is not None:
            _remember_persistent_scrub_binding(
                context, target_object, area_pointer=area_pointer
            )

        window_region = next(
            (
                region
                for region in tuple(getattr(context.area, "regions", ()) or ())
                if str(getattr(region, "type", "") or "") == "WINDOW"
            ),
            None,
        )
        if window_region is None:
            return {"CANCELLED"}
        try:
            with context.temp_override(
                window=context.window,
                area=context.area,
                region=window_region,
                space_data=context.space_data,
            ):
                result = bpy.ops.fbp.grease_pencil_frame_scrub(
                    "INVOKE_DEFAULT",
                    start_persistent=True,
                    target_object_name=str(getattr(target_object, "name", "") or ""),
                )
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not toggle the persistent Grease Pencil Scrub Slider", exc)
            return {"CANCELLED"}
        return {"FINISHED"} if "RUNNING_MODAL" in set(result) else {"CANCELLED"}


class FBP_OT_ToggleScrubOnionInterface(Operator):
    """Show or hide the interactive onion-skin range guides."""

    bl_idname = "fbp.toggle_scrub_onion_interface"
    bl_label = "Toggle Onion Range Handles"
    bl_description = (
        "Show or hide the draggable Onion Skin before/after guides on the "
        "Frame By Plane Scrub Bar"
    )
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return _scrub_header_available(context)

    def execute(self, context):
        preferences = fbp_get_addon_preferences(context)
        if preferences is None or not hasattr(preferences, "gp_scrub_show_onion_handles"):
            return {"CANCELLED"}
        try:
            preferences.gp_scrub_show_onion_handles = not bool(
                preferences.gp_scrub_show_onion_handles
            )
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not toggle Scrub Bar Onion Skin handles", exc)
            return {"CANCELLED"}
        _refresh_active_scrub(context)
        return {"FINISHED"}


class FBP_OT_CopyGreasePencilScrubKeyframes(Operator):
    """Copy selected Grease Pencil drawings to the Scrub Slider clipboard."""

    bl_idname = "fbp.copy_grease_pencil_scrub_keyframes"
    bl_label = "Copy Keyframes"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        obj = _scrub_target_object(context)
        return bool(obj is not None and selected_grease_pencil_frames(obj))

    def execute(self, context):
        global _SCRUB_FRAME_CLIPBOARD
        obj = _scrub_target_object(context)
        if obj is None:
            return {"CANCELLED"}
        data = getattr(obj, "data", None)
        layers = tuple(getattr(data, "layers", ()) or ())
        indices = {_rna_pointer(layer): index for index, layer in enumerate(layers)}
        selected = selected_grease_pencil_frames(obj)
        numbers = tuple(int(frame.frame_number) for _layer, frame in selected)
        if data is None or not selected or not numbers:
            return {"CANCELLED"}
        try:
            backup = data.copy()
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not copy Grease Pencil drawings", exc)
            return {"CANCELLED"}
        anchor = min(numbers)
        entries = tuple(
            (
                int(indices.get(_rna_pointer(layer), -1)),
                str(getattr(layer, "name", "") or ""),
                int(frame.frame_number),
                int(frame.frame_number) - int(anchor),
            )
            for layer, frame in selected
        )
        _clear_scrub_frame_clipboard()
        _SCRUB_FRAME_CLIPBOARD = {
            "data": backup,
            "entries": entries,
            "anchor": int(anchor),
        }
        self.report({"INFO"}, f"Copied {len(entries)} Grease Pencil keyframe(s)")
        return {"FINISHED"}


class FBP_OT_PasteGreasePencilScrubKeyframes(Operator):
    """Paste copied drawings with the first keyframe at the current frame."""

    bl_idname = "fbp.paste_grease_pencil_scrub_keyframes"
    bl_label = "Paste Keyframes"
    bl_options = {"INTERNAL", "UNDO"}

    @classmethod
    def poll(cls, context):
        clipboard = _SCRUB_FRAME_CLIPBOARD
        return bool(
            _scrub_target_object(context) is not None
            and isinstance(clipboard, dict)
            and clipboard.get("data") is not None
            and clipboard.get("entries")
        )

    def execute(self, context):
        clipboard = _SCRUB_FRAME_CLIPBOARD
        if not isinstance(clipboard, dict):
            return {"CANCELLED"}
        obj = _scrub_target_object(context)
        if obj is None:
            return {"CANCELLED"}
        target_data = getattr(obj, "data", None)
        source_data = clipboard.get("data")
        entries = tuple(clipboard.get("entries") or ())
        minimum, maximum = scene_frame_bounds(context.scene)
        current = int(context.scene.frame_current)
        prepared = []
        for layer_index, layer_name, source_number, offset in entries:
            target_number = current + int(offset)
            target_layer = _grease_pencil_layer_at(
                target_data,
                layer_index,
                layer_name,
            )
            source_layer = _grease_pencil_layer_at(
                source_data,
                layer_index,
                layer_name,
            )
            if (
                target_layer is None
                or source_layer is None
                or _grease_pencil_frame_at(source_layer, source_number) is None
                or target_number < minimum
                or target_number > maximum
            ):
                self.report(
                    {"WARNING"},
                    "The copied keyframes do not fit the current scene or layer layout",
                )
                return {"CANCELLED"}
            prepared.append(
                (
                    target_layer,
                    target_number,
                    layer_index,
                    layer_name,
                    source_number,
                )
            )
        try:
            original_data = target_data.copy()
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}

        def restore_original():
            restored = True
            restored_targets = set()
            for (
                target_layer,
                target_number,
                layer_index,
                layer_name,
                _source_number,
            ) in prepared:
                key = (_rna_pointer(target_layer), int(target_number))
                if key in restored_targets:
                    continue
                restored_targets.add(key)
                current_frame = _grease_pencil_frame_at(
                    target_layer,
                    target_number,
                )
                if current_frame is not None:
                    try:
                        target_layer.frames.remove(int(target_number))
                    except FBP_DATA_ERRORS:
                        restored = False
                original_layer = _grease_pencil_layer_at(
                    original_data,
                    layer_index,
                    layer_name,
                )
                original_frame = (
                    _grease_pencil_frame_at(original_layer, target_number)
                    if original_layer is not None
                    else None
                )
                if original_frame is not None and _copy_frame_from_data(
                    target_layer,
                    target_number,
                    original_data,
                    layer_index,
                    layer_name,
                    target_number,
                    selected=bool(getattr(original_frame, "select", False)),
                ) is None:
                    restored = False
            for layer_index, target_layer in enumerate(
                tuple(getattr(target_data, "layers", ()) or ())
            ):
                layer_name = str(getattr(target_layer, "name", "") or "")
                original_layer = _grease_pencil_layer_at(
                    original_data,
                    layer_index,
                    layer_name,
                )
                if original_layer is None:
                    continue
                original_selection = {
                    int(frame.frame_number): bool(getattr(frame, "select", False))
                    for frame in tuple(getattr(original_layer, "frames", ()) or ())
                }
                for frame in tuple(getattr(target_layer, "frames", ()) or ()):
                    number = int(frame.frame_number)
                    if number in original_selection:
                        try:
                            frame.select = original_selection[number]
                        except FBP_DATA_ERRORS:
                            restored = False
            return restored

        select_all_grease_pencil_frames(obj, selected=False)
        pasted = 0
        for target_layer, target_number, layer_index, layer_name, source_number in prepared:
            created = _copy_frame_from_data(
                target_layer,
                target_number,
                source_data,
                layer_index,
                layer_name,
                source_number,
                selected=True,
            )
            if created is None:
                restore_original()
                _remove_grease_pencil_data(original_data)
                self.report({"WARNING"}, "Could not paste every Grease Pencil keyframe")
                return {"CANCELLED"}
            pasted += 1
        _remove_grease_pencil_data(original_data)
        _refresh_active_scrub(context)
        self.report({"INFO"}, f"Pasted {pasted} Grease Pencil keyframe(s)")
        return {"FINISHED"}


class FBP_OT_DuplicateGreasePencilScrubKeyframes(Operator):
    """Duplicate selected drawings to the nearest free frame."""

    bl_idname = "fbp.duplicate_grease_pencil_scrub_keyframes"
    bl_label = "Duplicate Keyframes"
    bl_options = {"INTERNAL", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = _scrub_target_object(context)
        return bool(obj is not None and selected_grease_pencil_frames(obj))

    def execute(self, context):
        obj = _scrub_target_object(context)
        if obj is None:
            return {"CANCELLED"}
        rows = selected_grease_pencil_frames(obj)
        selected_by_layer = {}
        occupied_by_layer = {}
        layer_by_key = {}
        for layer, frame in grease_pencil_editable_frames(obj):
            key = _rna_pointer(layer)
            layer_by_key[key] = layer
            number = int(frame.frame_number)
            occupied_by_layer.setdefault(key, set()).add(number)
            if bool(getattr(frame, "select", False)):
                selected_by_layer.setdefault(key, set()).add(number)
        minimum, maximum = scene_frame_bounds(context.scene)
        delta = resolve_keyframe_duplicate_delta(
            selected_by_layer,
            occupied_by_layer,
            minimum,
            maximum,
        )
        if not rows or not delta:
            return {"CANCELLED"}
        copies = []
        for key, numbers in selected_by_layer.items():
            layer = layer_by_key.get(key)
            if layer is None:
                continue
            for source in sorted(numbers):
                target = int(source) + int(delta)
                copied = FBP_OT_GreasePencilFrameScrub._copy_layer_frame(
                    layer,
                    source,
                    target,
                )
                if copied is None:
                    for copied_layer, copied_number in reversed(copies):
                        FBP_OT_GreasePencilFrameScrub._remove_layer_frame(
                            copied_layer,
                            copied_number,
                        )
                    return {"CANCELLED"}
                copies.append((layer, target))
        if not copies:
            return {"CANCELLED"}
        select_all_grease_pencil_frames(obj, selected=False)
        for layer, number in copies:
            frame = _grease_pencil_frame_at(layer, number)
            if frame is not None:
                frame.select = True
        _refresh_active_scrub(context)
        return {"FINISHED"}


class FBP_OT_DeleteGreasePencilScrubKeyframes(Operator):
    """Delete selected drawings from the Scrub Slider."""

    bl_idname = "fbp.delete_grease_pencil_scrub_keyframes"
    bl_label = "Delete Keyframes"
    bl_options = {"INTERNAL", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = _scrub_target_object(context)
        return bool(obj is not None and selected_grease_pencil_frames(obj))

    def execute(self, context):
        obj = _scrub_target_object(context)
        if obj is None:
            return {"CANCELLED"}
        deleted = delete_selected_grease_pencil_frames(obj)
        if not deleted:
            return {"CANCELLED"}
        _refresh_active_scrub(context)
        return {"FINISHED"}


class FBP_OT_SelectAllGreasePencilScrubKeyframes(Operator):
    """Select or deselect every editable drawing keyframe."""

    bl_idname = "fbp.select_all_grease_pencil_scrub_keyframes"
    bl_label = "Select All Keyframes"
    bl_options = {"INTERNAL"}

    action: EnumProperty(
        name="Action",
        items=(
            ("SELECT", "Select All", "Select all editable drawing keyframes"),
            ("DESELECT", "Deselect All", "Deselect all editable drawing keyframes"),
        ),
        default="SELECT",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return _scrub_target_object(context) is not None

    def execute(self, context):
        obj = _scrub_target_object(context)
        if obj is None:
            return {"CANCELLED"}
        select_all_grease_pencil_frames(
            obj,
            selected=self.action == "SELECT",
        )
        _refresh_active_scrub(context)
        return {"FINISHED"}


class FBP_OT_MirrorGreasePencilScrubKeyframes(Operator):
    """Mirror selected drawing keyframes around a Timeline-style pivot."""

    bl_idname = "fbp.mirror_grease_pencil_scrub_keyframes"
    bl_label = "Mirror Keyframes"
    bl_options = {"INTERNAL", "UNDO"}

    pivot: EnumProperty(
        name="Mirror",
        items=(
            (
                "CURRENT_FRAME",
                "By Current Frame",
                "Mirror selected keyframes around the current frame",
            ),
            (
                "PREVIEW_RANGE",
                "By Preview Range",
                "Mirror selected keyframes around the Preview Range center",
            ),
            (
                "FIRST_SELECTED",
                "By First Selected Keyframe",
                "Mirror around the first selected keyframe",
            ),
            (
                "LAST_SELECTED",
                "By Last Selected Keyframe",
                "Mirror around the last selected keyframe",
            ),
        ),
        default="CURRENT_FRAME",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        obj = _scrub_target_object(context)
        return bool(obj is not None and selected_grease_pencil_frames(obj))

    def execute(self, context):
        obj = _scrub_target_object(context)
        if obj is None:
            return {"CANCELLED"}
        data = getattr(obj, "data", None)
        layers = tuple(getattr(data, "layers", ()) or ())
        indices = {_rna_pointer(layer): index for index, layer in enumerate(layers)}
        selected = selected_grease_pencil_frames(obj)
        numbers = tuple(int(frame.frame_number) for _layer, frame in selected)
        if not selected or not numbers:
            return {"CANCELLED"}
        if self.pivot == "FIRST_SELECTED":
            pivot = float(min(numbers))
        elif self.pivot == "LAST_SELECTED":
            pivot = float(max(numbers))
        elif self.pivot == "PREVIEW_RANGE":
            if bool(getattr(context.scene, "use_preview_range", False)):
                start = int(context.scene.frame_preview_start)
                end = int(context.scene.frame_preview_end)
            else:
                start, end = scene_frame_bounds(context.scene)
            pivot = (float(start) + float(end)) * 0.5
        else:
            pivot = float(context.scene.frame_current)
        minimum, maximum = scene_frame_bounds(context.scene)
        entries = []
        touched = {}
        for layer, frame in selected:
            source = int(frame.frame_number)
            target = int(round((2.0 * pivot) - float(source)))
            if target < minimum or target > maximum:
                self.report({"WARNING"}, "Mirrored keyframes would leave the scene range")
                return {"CANCELLED"}
            index = int(indices.get(_rna_pointer(layer), -1))
            name = str(getattr(layer, "name", "") or "")
            entries.append((layer, index, name, source, target))
            touched.setdefault(_rna_pointer(layer), set()).update((source, target))
        try:
            backup = data.copy()
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}

        def restore_original():
            restored = True
            for layer, index, name, _source, _target in entries:
                layer_key = _rna_pointer(layer)
                numbers_to_restore = touched.pop(layer_key, None)
                if numbers_to_restore is None:
                    continue
                for number in numbers_to_restore:
                    existing = _grease_pencil_frame_at(layer, number)
                    if existing is not None:
                        try:
                            layer.frames.remove(number)
                        except FBP_DATA_ERRORS:
                            restored = False
                backup_layer = _grease_pencil_layer_at(backup, index, name)
                for number in numbers_to_restore:
                    backup_frame = _grease_pencil_frame_at(backup_layer, number)
                    if backup_frame is None:
                        continue
                    if _copy_frame_from_data(
                        layer,
                        number,
                        backup,
                        index,
                        name,
                        number,
                        selected=bool(getattr(backup_frame, "select", False)),
                    ) is None:
                        restored = False
            return restored

        for layer, numbers_to_remove in (
            (
                layer,
                touched.get(_rna_pointer(layer), ()),
            )
            for layer, _index, _name, _source, _target in entries
        ):
            for number in tuple(numbers_to_remove):
                existing = _grease_pencil_frame_at(layer, number)
                if existing is not None:
                    try:
                        layer.frames.remove(number)
                    except FBP_DATA_ERRORS:
                        restore_original()
                        _remove_grease_pencil_data(backup)
                        return {"CANCELLED"}
        created = 0
        for layer, index, name, source, target in entries:
            if _copy_frame_from_data(
                layer,
                target,
                backup,
                index,
                name,
                source,
                selected=True,
            ) is None:
                restore_original()
                _remove_grease_pencil_data(backup)
                return {"CANCELLED"}
            created += 1
        _remove_grease_pencil_data(backup)
        _refresh_active_scrub(context)
        return {"FINISHED"} if created else {"CANCELLED"}


class FBP_OT_AddScrubBookmark(Operator):
    """Create a named FBP bookmark using Blender's native Timeline markers."""

    bl_idname = "fbp.add_scrub_bookmark"
    bl_label = "New Bookmark"
    bl_description = "Create a named bookmark at the current frame; it is also visible in Blender's native Timeline and Dope Sheet"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Name", default="")
    color_tag: EnumProperty(
        name="Color",
        description="Color tag used by the Frame By Plane Scrub Bar",
        items=_BOOKMARK_COLOR_ITEMS,
        default=_BOOKMARK_DEFAULT_COLOR,
    )
    frame: IntProperty(name="Frame", default=_FRAME_NUMBER_MIN, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return getattr(context, "scene", None) is not None

    def invoke(self, context, _event):
        target_frame = int(context.scene.frame_current) if int(self.frame) == _FRAME_NUMBER_MIN else int(self.frame)
        if not str(self.name or "").strip():
            self.name = _next_bookmark_default_label(context.scene)
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "name")
        layout.prop(self, "color_tag", text="Color")

    def execute(self, context):
        scene = getattr(context, "scene", None)
        markers = getattr(scene, "timeline_markers", None) if scene is not None else None
        if markers is None:
            return {"CANCELLED"}
        frame = int(scene.frame_current) if int(self.frame) == _FRAME_NUMBER_MIN else int(self.frame)
        label = _bookmark_label_from_name(self.name or _next_bookmark_default_label(scene))
        full_name = _bookmark_native_name(label)
        try:
            try:
                marker = markers.new(full_name, frame=frame)
            except TypeError:
                marker = markers.new(full_name)
                marker.frame = frame
            for candidate in markers:
                candidate.select = candidate is marker
            entries = _load_bookmark_state(scene)
            entry = _new_bookmark_entry(marker, label=label, color_tag=self.color_tag)
            entries.append(entry)
            _BOOKMARK_POINTER_UIDS[_marker_pointer(marker)] = entry["uid"]
            _save_bookmark_state(scene, entries)
            reconcile_scrub_bookmarks(scene)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not create Scrub Bar bookmark", exc)
            return {"CANCELLED"}
        _refresh_active_scrub(context)
        return {"FINISHED"}


class FBP_OT_RenameScrubBookmark(Operator):
    bl_idname = "fbp.rename_scrub_bookmark"
    bl_label = "Rename Bookmark"
    bl_description = "Rename the selected Frame By Plane bookmark"
    bl_options = {"REGISTER", "UNDO"}

    bookmark_uid: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    name: StringProperty(name="Name", default="")

    @classmethod
    def poll(cls, context):
        return len(selected_scrub_bookmark_records(getattr(context, "scene", None))) == 1

    def _record(self, context):
        scene = getattr(context, "scene", None)
        if self.bookmark_uid:
            return _bookmark_record_by_uid(scene, self.bookmark_uid)
        selected = selected_scrub_bookmark_records(scene)
        return selected[0] if len(selected) == 1 else None

    def invoke(self, context, _event):
        record = self._record(context)
        if record is None:
            return {"CANCELLED"}
        self.bookmark_uid = record["uid"]
        self.name = record["name"]
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, _context):
        self.layout.prop(self, "name")

    def execute(self, context):
        scene = getattr(context, "scene", None)
        record = self._record(context)
        if record is None:
            return {"CANCELLED"}
        label = _bookmark_label_from_name(self.name)
        try:
            record["marker"].name = _bookmark_native_name(label)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not rename Scrub Bar bookmark", exc)
            return {"CANCELLED"}
        entries = _load_bookmark_state(scene)
        for entry in entries:
            if str(entry.get("uid") or "") == record["uid"]:
                entry["label"] = label
                entry["marker_name"] = _bookmark_native_name(label)
                entry["frame"] = int(getattr(record["marker"], "frame", record["frame"]))
                break
        _save_bookmark_state(scene, entries)
        reconcile_scrub_bookmarks(scene)
        _refresh_active_scrub(context)
        return {"FINISHED"}


class FBP_OT_SetScrubBookmarkColor(Operator):
    bl_idname = "fbp.set_scrub_bookmark_color"
    bl_label = "Set Bookmark Color"
    bl_description = "Assign a color tag to selected Frame By Plane bookmarks"
    bl_options = {"REGISTER", "UNDO"}

    color_tag: EnumProperty(items=_BOOKMARK_COLOR_ITEMS, default=_BOOKMARK_DEFAULT_COLOR)

    @classmethod
    def poll(cls, context):
        return bool(selected_scrub_bookmark_records(getattr(context, "scene", None)))

    def execute(self, context):
        scene = getattr(context, "scene", None)
        records = selected_scrub_bookmark_records(scene)
        if not _set_bookmark_color(scene, records, self.color_tag):
            return {"CANCELLED"}
        _refresh_active_scrub(context)
        return {"FINISHED"}


class FBP_OT_SelectScrubBookmarks(Operator):
    bl_idname = "fbp.select_scrub_bookmarks"
    bl_label = "Select Bookmarks"
    bl_description = "Change selection of Frame By Plane bookmarks"
    bl_options = {"REGISTER", "UNDO"}

    action: EnumProperty(
        items=(
            ("SELECT", "Select All", "Select every Frame By Plane bookmark"),
            ("DESELECT", "Deselect All", "Deselect every Frame By Plane bookmark"),
            ("INVERT", "Invert", "Invert bookmark selection"),
        ),
        default="SELECT",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return bool(scrub_bookmark_records(getattr(context, "scene", None)))

    def execute(self, context):
        scene = getattr(context, "scene", None)
        records = scrub_bookmark_records(scene)
        changed = False
        for record in records:
            marker = record["marker"]
            try:
                before = bool(marker.select)
                if self.action == "SELECT":
                    marker.select = True
                elif self.action == "DESELECT":
                    marker.select = False
                else:
                    marker.select = not before
                changed = changed or bool(marker.select) != before
            except FBP_DATA_ERRORS:
                continue
        _refresh_active_scrub(context)
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_RemoveScrubBookmark(Operator):
    """Remove selected FBP bookmarks, or the bookmark at the current frame."""

    bl_idname = "fbp.remove_scrub_bookmark"
    bl_label = "Delete Selected Bookmark"
    bl_description = "Remove selected Frame By Plane bookmarks or the bookmark at the current frame"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        if scene is None:
            return False
        records = scrub_bookmark_records(scene)
        frame = int(scene.frame_current)
        return any(record["selected"] or record["frame"] == frame for record in records)

    def execute(self, context):
        scene = getattr(context, "scene", None)
        frame = int(scene.frame_current)
        records = scrub_bookmark_records(scene)
        targets = tuple(record for record in records if record["selected"])
        if not targets:
            targets = tuple(record for record in records if record["frame"] == frame)
        removed = _delete_bookmark_records(scene, targets)
        if not removed:
            return {"CANCELLED"}
        _refresh_active_scrub(context)
        return {"FINISHED"}


class FBP_OT_DeleteAllScrubBookmarks(Operator):
    bl_idname = "fbp.delete_all_scrub_bookmarks"
    bl_label = "Delete All Bookmarks"
    bl_description = "Delete every Frame By Plane bookmark in the current Scene"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(scrub_bookmark_records(getattr(context, "scene", None)))

    def execute(self, context):
        scene = getattr(context, "scene", None)
        removed = _delete_bookmark_records(scene, scrub_bookmark_records(scene))
        if not removed:
            return {"CANCELLED"}
        _refresh_active_scrub(context)
        return {"FINISHED"}


class FBP_OT_DuplicateScrubBookmarks(Operator):
    bl_idname = "fbp.duplicate_scrub_bookmarks"
    bl_label = "Duplicate Bookmarks"
    bl_description = "Duplicate selected Frame By Plane bookmarks one frame later"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(selected_scrub_bookmark_records(getattr(context, "scene", None)))

    def execute(self, context):
        scene = getattr(context, "scene", None)
        markers = getattr(scene, "timeline_markers", None) if scene is not None else None
        selected = selected_scrub_bookmark_records(scene)
        if markers is None or not selected:
            return {"CANCELLED"}
        minimum, maximum = scene_frame_bounds(scene)
        entries = _load_bookmark_state(scene)
        for marker in tuple(getattr(scene, "timeline_markers", ()) or ()):
            try:
                marker.select = False
            except FBP_DATA_ERRORS:
                pass
        created = 0
        for record in selected:
            target = max(minimum, min(maximum, int(record["frame"]) + 1))
            try:
                try:
                    marker = markers.new(_bookmark_native_name(record["name"]), frame=target)
                except TypeError:
                    marker = markers.new(_bookmark_native_name(record["name"]))
                    marker.frame = target
                marker.select = True
            except FBP_DATA_ERRORS:
                continue
            entry = _new_bookmark_entry(marker, label=record["name"], color_tag=record["color_tag"])
            entries.append(entry)
            _BOOKMARK_POINTER_UIDS[_marker_pointer(marker)] = entry["uid"]
            created += 1
        _save_bookmark_state(scene, entries)
        reconcile_scrub_bookmarks(scene)
        _refresh_active_scrub(context)
        return {"FINISHED"} if created else {"CANCELLED"}


class FBP_OT_SetGreasePencilScrubKeyframeType(Operator):
    """Set the type of selected drawing keyframes in the Scrub Slider."""

    bl_idname = "fbp.set_grease_pencil_scrub_keyframe_type"
    bl_label = "Set Drawing Keyframe Type"
    bl_options = {"INTERNAL", "UNDO"}

    keyframe_type: EnumProperty(
        name="Type",
        items=tuple(
            (key_id, label, f"Set selected drawings to {label}", icon, index)
            for index, (key_id, label, icon, _passive, _selected, _radius) in enumerate(
                _KEYFRAME_TYPE_DEFINITIONS
            )
        ),
        default="KEYFRAME",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        obj = _scrub_target_object(context)
        return bool(obj is not None and selected_grease_pencil_frames(obj))

    def execute(self, context):
        obj = _scrub_target_object(context)
        if obj is None:
            return {"CANCELLED"}
        changed = set_selected_grease_pencil_keyframe_type(
            obj,
            self.keyframe_type,
        )
        if not changed:
            return {"CANCELLED"}
        active = _ACTIVE_OPERATOR
        if active is not None:
            active._refresh_keyframe_cache(context)
            active._tag_redraw()
        return {"FINISHED"}


class FBP_OT_SetGreasePencilScrubPosition(Operator):
    """Move the active Scrub Slider to a Viewport edge."""

    bl_idname = "fbp.set_grease_pencil_scrub_position"
    bl_label = "Set Scrub Slider Position"
    bl_options = {"INTERNAL"}

    position: EnumProperty(
        name="Position",
        items=(
            ("TOP", "North", "Place the slider at the top"),
            ("BOTTOM", "South", "Place the slider at the bottom"),
            ("LEFT", "West", "Place the slider on the left"),
            ("RIGHT", "East", "Place the slider on the right"),
        ),
        default="LEFT",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return _is_view3d_context(context)

    def execute(self, context):
        preferences = fbp_get_addon_preferences(context)
        if preferences is None or not hasattr(preferences, "gp_scrub_position"):
            return {"CANCELLED"}
        position = str(self.position or "LEFT").upper()
        if position not in {"TOP", "BOTTOM", "LEFT", "RIGHT"}:
            return {"CANCELLED"}
        preferences.gp_scrub_position = position
        active = _ACTIVE_OPERATOR
        if active is not None:
            active._position = position
            active._vertical = position in {"LEFT", "RIGHT"}
            active._tag_redraw()
        _tag_all_view3d_redraw()
        return {"FINISHED"}


class FBP_MT_GreasePencilScrubKeyframeType(Menu):
    bl_idname = "FBP_MT_grease_pencil_scrub_keyframe_type"
    bl_label = "Set Keyframe Type"

    def draw(self, _context):
        layout = self.layout
        for key_id, label, icon, _passive, _selected, _radius in _KEYFRAME_TYPE_DEFINITIONS:
            operator = layout.operator(
                FBP_OT_SetGreasePencilScrubKeyframeType.bl_idname,
                text=label,
                icon=icon,
            )
            operator.keyframe_type = key_id


class FBP_MT_GreasePencilScrubMirror(Menu):
    bl_idname = "FBP_MT_grease_pencil_scrub_mirror"
    bl_label = "Mirror"

    def draw(self, _context):
        layout = self.layout
        for pivot, label in (
            ("CURRENT_FRAME", "By Current Frame"),
            ("PREVIEW_RANGE", "By Preview Range"),
            ("FIRST_SELECTED", "By First Selected Keyframe"),
            ("LAST_SELECTED", "By Last Selected Keyframe"),
        ):
            operator = layout.operator(
                FBP_OT_MirrorGreasePencilScrubKeyframes.bl_idname,
                text=label,
            )
            operator.pivot = pivot


class FBP_MT_ScrubBookmarkColor(Menu):
    bl_idname = "FBP_MT_scrub_bookmark_color"
    bl_label = "Color Tag"

    def draw(self, context):
        layout = self.layout
        has_selected = bool(selected_scrub_bookmark_records(getattr(context, "scene", None)))
        for identifier, label, _description, icon, _index in _BOOKMARK_COLOR_ITEMS:
            row = layout.row()
            row.enabled = has_selected
            operator = row.operator(
                FBP_OT_SetScrubBookmarkColor.bl_idname,
                text=label,
                icon=icon,
            )
            operator.color_tag = identifier


class FBP_MT_ScrubBookmarkMenu(Menu):
    bl_idname = "FBP_MT_scrub_bookmark"
    bl_label = "Bookmark"

    def draw(self, context):
        layout = self.layout
        scene = getattr(context, "scene", None)
        records = scrub_bookmark_records(scene)
        selected = tuple(record for record in records if record["selected"])

        row = layout.row()
        row.enabled = bool(selected)
        row.menu(FBP_MT_ScrubBookmarkColor.bl_idname, text="Color Tag", icon="STRIP_COLOR_01")
        layout.separator()
        layout.operator(FBP_OT_AddScrubBookmark.bl_idname, text="New", icon="ADD")
        row = layout.row()
        row.enabled = len(selected) == 1
        row.operator(FBP_OT_RenameScrubBookmark.bl_idname, text="Rename Selected", icon="GREASEPENCIL")
        row = layout.row()
        row.enabled = bool(selected)
        row.operator(FBP_OT_DuplicateScrubBookmarks.bl_idname, text="Duplicate Selected", icon="DUPLICATE")

        layout.separator()
        row = layout.row()
        row.enabled = bool(records)
        operator = row.operator(FBP_OT_SelectScrubBookmarks.bl_idname, text="Select All", icon="PROP_ON")
        operator.action = "SELECT"
        row = layout.row()
        row.enabled = bool(selected)
        operator = row.operator(FBP_OT_SelectScrubBookmarks.bl_idname, text="Deselect All", icon="PROP_OFF")
        operator.action = "DESELECT"
        layout.separator()
        row = layout.row()
        row.enabled = bool(selected)
        row.operator(FBP_OT_RemoveScrubBookmark.bl_idname, text="Delete Selected", icon="X")
        row = layout.row()
        row.enabled = bool(records)
        row.operator(FBP_OT_DeleteAllScrubBookmarks.bl_idname, text="Delete All", icon="TRASH")


class FBP_MT_GreasePencilScrubContextMenu(Menu):
    bl_idname = "FBP_MT_grease_pencil_scrub_context"
    bl_label = "Scrub Slider"

    def draw(self, context):
        layout = self.layout
        obj = _scrub_target_object(context)
        gp_live = _is_live_grease_pencil_object(obj)
        selected_frames = selected_grease_pencil_frames(obj) if gp_live else ()
        has_selected_frames = bool(selected_frames)
        has_frames = bool(grease_pencil_editable_frames(obj)) if gp_live else False
        can_paste = bool(gp_live and _SCRUB_FRAME_CLIPBOARD is not None)

        row = layout.row()
        row.enabled = has_selected_frames
        row.operator(FBP_OT_CopyGreasePencilScrubKeyframes.bl_idname, text="Copy", icon="COPYDOWN")
        row = layout.row()
        row.enabled = can_paste
        row.operator(FBP_OT_PasteGreasePencilScrubKeyframes.bl_idname, text="Paste", icon="PASTEDOWN")
        layout.separator()
        row = layout.row()
        row.enabled = has_selected_frames
        row.operator(FBP_OT_DuplicateGreasePencilScrubKeyframes.bl_idname, text="Duplicate", icon="DUPLICATE")
        row = layout.row()
        row.enabled = has_selected_frames
        row.operator(FBP_OT_DeleteGreasePencilScrubKeyframes.bl_idname, text="Delete", icon="X")
        layout.separator()
        row = layout.row()
        row.enabled = has_selected_frames
        row.menu(FBP_MT_GreasePencilScrubKeyframeType.bl_idname, text="Keyframe Type", icon="KEY_HLT")
        row = layout.row()
        row.enabled = has_selected_frames
        row.menu(FBP_MT_GreasePencilScrubMirror.bl_idname, text="Mirror", icon="MOD_MIRROR")
        layout.separator()
        layout.menu(FBP_MT_ScrubBookmarkMenu.bl_idname, text="Bookmark", icon="MARKER_HLT")
        layout.separator()
        row = layout.row()
        row.enabled = has_frames
        select_operator = row.operator(FBP_OT_SelectAllGreasePencilScrubKeyframes.bl_idname, text="Select All Drawings", icon="PROP_ON")
        select_operator.action = "SELECT"
        row = layout.row()
        row.enabled = has_selected_frames
        deselect_operator = row.operator(FBP_OT_SelectAllGreasePencilScrubKeyframes.bl_idname, text="Deselect Drawings", icon="PROP_OFF")
        deselect_operator.action = "DESELECT"


class FBP_PT_GreasePencilScrubSliderPopover(Panel):
    bl_idname = "FBP_PT_grease_pencil_scrub_slider"
    bl_label = "Scrub Slider"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"

    @classmethod
    def poll(cls, context):
        return _scrub_header_available(context)

    def draw(self, context):
        layout = self.layout
        preferences = fbp_get_addon_preferences(context)

        if preferences is not None and hasattr(preferences, "gp_scrub_position"):
            layout.prop(preferences, "gp_scrub_position", text="Viewport Edge")
        layout.label(
            text="Transparent · Lines and text invert the Viewport",
            icon="SHADING_SOLID",
        )

        obj = _scrub_target_object(context)
        gp_data = getattr(obj, "data", None) if _is_live_grease_pencil_object(obj) else None

        if preferences is not None:
            layout.separator()
            if hasattr(preferences, "gp_scrub_show_onion_handles"):
                layout.prop(
                    preferences,
                    "gp_scrub_show_onion_handles",
                    text="Onion Range Interface",
                    icon="ONIONSKIN_ON",
                    toggle=True,
                )
            if hasattr(preferences, "gp_scrub_show_bookmarks"):
                layout.prop(
                    preferences,
                    "gp_scrub_show_bookmarks",
                    text="Show Bookmarks",
                    icon="BOOKMARKS",
                    toggle=True,
                )
            if hasattr(preferences, "gp_scrub_show_info"):
                layout.prop(
                    preferences,
                    "gp_scrub_show_info",
                    text="Show Interaction Info",
                    toggle=True,
                )

        if gp_data is not None:
            layout.separator()
            layout.label(text="Onion Skin", icon="ONIONSKIN_ON")
            overlay = getattr(getattr(context, "space_data", None), "overlay", None)
            if overlay is not None and hasattr(overlay, "use_gpencil_onion_skin"):
                layout.prop(overlay, "use_gpencil_onion_skin", text="Viewport Onion Skin", toggle=True)
            if hasattr(gp_data, "onion_mode"):
                layout.prop(gp_data, "onion_mode", text="Range Type")
            if hasattr(gp_data, "onion_keyframe_type"):
                layout.prop(gp_data, "onion_keyframe_type", text="Keyframe Type")
            onion_mode = str(getattr(gp_data, "onion_mode", "ABSOLUTE") or "ABSOLUTE").upper()
            if onion_mode != "SELECTED":
                ranges = layout.row(align=True)
                range_label = "Frames" if onion_mode == "ABSOLUTE" else "Keyframes"
                if hasattr(gp_data, "ghost_before_range"):
                    ranges.prop(gp_data, "ghost_before_range", text=f"{range_label} Before")
                if hasattr(gp_data, "ghost_after_range"):
                    ranges.prop(gp_data, "ghost_after_range", text=f"{range_label} After")
            if hasattr(gp_data, "onion_factor"):
                layout.prop(gp_data, "onion_factor", text="Opacity", slider=True)
            display = layout.row(align=True)
            if hasattr(gp_data, "use_onion_fade"):
                display.prop(gp_data, "use_onion_fade", text="Fade", toggle=True)
            if hasattr(gp_data, "use_onion_loop"):
                display.prop(gp_data, "use_onion_loop", text="Loop", toggle=True)
            if hasattr(gp_data, "use_ghost_custom_colors"):
                layout.prop(gp_data, "use_ghost_custom_colors", text="Custom Colors", toggle=True)
                colors = layout.row(align=True)
                colors.enabled = bool(getattr(gp_data, "use_ghost_custom_colors", False))
                if hasattr(gp_data, "before_color"):
                    colors.prop(gp_data, "before_color", text="Before")
                if hasattr(gp_data, "after_color"):
                    colors.prop(gp_data, "after_color", text="After")

        scene = getattr(context, "scene", None)
        if scene is not None:
            layout.separator()
            row = layout.row(align=True)
            row.operator(FBP_OT_AddScrubBookmark.bl_idname, text="Add Bookmark", icon="MARKER_HLT")
            row.operator(FBP_OT_RemoveScrubBookmark.bl_idname, text="", icon="X")
        if scene is not None and hasattr(scene, "use_preview_range"):
            layout.separator()
            layout.prop(
                scene,
                "use_preview_range",
                text="Use Timeline Preview Range",
                toggle=True,
            )
            bounds = layout.column(align=True)
            bounds.active = bool(scene.use_preview_range)
            row = bounds.row(align=True)
            row.prop(scene, "frame_preview_start", text="In")
            row.prop(scene, "frame_preview_end", text="Out")


def _draw_scrub_header_control(layout, context):
    if not _scrub_header_available(context):
        return
    row = layout.row(align=True)
    row.operator(
        FBP_OT_ToggleGreasePencilScrubSlider.bl_idname,
        text="",
        depress=is_persistent_scrub_active(context),
        **floating_timeline_icon_kwargs("ACTION"),
    )
    preferences = fbp_get_addon_preferences(context)
    onion_row = row.row(align=True)
    onion_row.enabled = _is_live_grease_pencil_object(_scrub_target_object(context))
    onion_row.operator(
        FBP_OT_ToggleScrubOnionInterface.bl_idname,
        text="",
        icon="ONIONSKIN_ON",
        depress=bool(
            getattr(preferences, "gp_scrub_show_onion_handles", True)
            if preferences is not None
            else True
        ),
    )
    row.popover(
        panel=FBP_PT_GreasePencilScrubSliderPopover.bl_idname,
        text="",
    )


class _FBPHeaderLayoutProxy:
    """Inject the slider immediately after the header's first right spacer."""

    __slots__ = ("_layout", "_context", "_inserted")

    def __init__(self, layout, context):
        self._layout = layout
        self._context = context
        self._inserted = False

    def __setattr__(self, name, value):
        if name in self.__slots__:
            object.__setattr__(self, name, value)
        else:
            setattr(self._layout, name, value)

    def separator_spacer(self):
        result = self._layout.separator_spacer()
        if not self._inserted:
            self._inserted = True
            try:
                _draw_scrub_header_control(self._layout, self._context)
            except Exception as exc:
                # The Scrub Slider is optional UI. A bad preference state or a
                # future header API change must never abort Blender's native
                # header and hide the editor-type/menu controls.
                fbp_warn_once(
                    "scrub.header_injection",
                    "Could not draw the Scrub Slider header control",
                    exc,
                )
        return result

    def __getattr__(self, name):
        return getattr(self._layout, name)


class _FBPHeaderSelfProxy:
    __slots__ = ("_header", "layout")

    def __init__(self, header, context):
        self._header = header
        self.layout = _FBPHeaderLayoutProxy(header.layout, context)

    def __getattr__(self, name):
        return getattr(self._header, name)


def _draw_view3d_header_with_scrub(self, context):
    original = getattr(
        _draw_view3d_header_with_scrub,
        "_fbp_original_draw",
        None,
    )
    if original is None:
        return None
    try:
        return original(_FBPHeaderSelfProxy(self, context), context)
    except Exception as exc:
        # The proxy exists only to position one optional icon. If Blender changes
        # the native header layout contract, retry the untouched native draw so
        # an add-on UI regression can never blank the complete Viewport header.
        fbp_warn_once(
            "scrub.header_proxy_fallback",
            "Scrub Slider header injection failed; restored Blender's native header",
            exc,
        )
        return original(self, context)


def _register_header():
    global _HEADER_REGISTERED, _ORIGINAL_VIEW3D_HEADER_DRAW
    if _HEADER_REGISTERED:
        return
    try:
        header_type = bpy.types.VIEW3D_HT_header
        original = header_type.draw
        while bool(getattr(original, "_fbp_scrub_header_patch", False)):
            original = getattr(original, "_fbp_original_draw", original)
        _ORIGINAL_VIEW3D_HEADER_DRAW = original
        _draw_view3d_header_with_scrub._fbp_original_draw = original
        _draw_view3d_header_with_scrub._fbp_scrub_header_patch = True
        header_type.draw = _draw_view3d_header_with_scrub
        _HEADER_REGISTERED = True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not add the Grease Pencil Scrub Slider header icon", exc)


def _unregister_header():
    global _HEADER_REGISTERED, _ORIGINAL_VIEW3D_HEADER_DRAW
    try:
        header_type = bpy.types.VIEW3D_HT_header
        current = header_type.draw
        if bool(getattr(current, "_fbp_scrub_header_patch", False)):
            header_type.draw = getattr(
                current,
                "_fbp_original_draw",
                _ORIGINAL_VIEW3D_HEADER_DRAW,
            )
    except FBP_DATA_ERRORS:
        pass
    _ORIGINAL_VIEW3D_HEADER_DRAW = None
    _HEADER_REGISTERED = False


class _ScrubPreviewOverlay:
    """Live, non-interactive slider preview used by Add-on Preferences."""

    def _layout(self, region):
        return _scrub_layout_for_state(self, region)

    def _window_center(self):
        return int(self._origin_frame) + int(self._overflow_offset)

    def _frame_position(self, frame, left, right, layout):
        return _scrub_frame_position(
            frame, left, right, layout, invert_vertical=self._invert_vertical
        )

    def configure(self, context):
        scene = getattr(context, "scene", None)
        area = getattr(context, "area", None)
        if scene is None or area is None or getattr(area, "type", "") != "VIEW_3D":
            return False
        (
            self._maximum_range,
            self._position,
            line_color,
            frame_tick_color,
            major_tick_color,
            second_tick_color,
            text_color,
            cursor_color,
            cursor_text_color,
            self._sensitivity,
            self._slow_factor,
            self._length_ratio,
            self._edge_offset,
            self._tick_scale,
            self._line_width,
            self._cursor_width,
            self._cursor_label_scale,
            self._major_interval,
            self._micro_tick_length,
            self._major_tick_length,
            self._second_tick_length,
            self._invert_vertical,
        ) = scrub_preferences(context)
        self._vertical = self._position in {"LEFT", "RIGHT"}
        self._line_color = (*line_color, 1.0)
        self._frame_tick_color = frame_tick_color
        self._major_tick_color = major_tick_color
        self._second_tick_color = second_tick_color
        self._text_color = (*text_color, 1.0)
        self._cursor_color = (*cursor_color, 1.0)
        self._cursor_text_color = (*cursor_text_color, 1.0)
        preferences = fbp_get_addon_preferences(context)
        self._show_info = bool(getattr(preferences, "gp_scrub_show_info", False))
        _apply_inverted_scrub_ink(self, context)
        try:
            self._ui_scale = max(0.5, float(context.preferences.system.ui_scale))
        except FBP_DATA_ERRORS:
            self._ui_scale = 1.0
        self._area_pointer = int(area.as_pointer())
        self._origin_frame = int(scene.frame_current)
        self._current_frame = self._origin_frame
        self._overflow_offset = 0
        self._shift_held = False
        self._ctrl_held = False
        self._snap_settings = playhead_snap_settings(scene)
        obj = getattr(context, "object", None)
        if obj is not None and str(getattr(obj, "type", "") or "") == "GREASEPENCIL":
            self._keyframe_records = grease_pencil_keyframe_records(obj)
            self._object = obj
        else:
            self._keyframe_records = ()
            self._object = None
        self._keyframe_record_numbers = tuple(record[0] for record in self._keyframe_records)
        self._all_keyframes = timeline_keyframe_frames(scene, obj)
        self._bookmark_records = scrub_bookmark_records(scene)
        self._onion_before_handle = None
        self._onion_after_handle = None
        self._shortcut_direct_factor = 0.0
        self._shortcut_direct_locked = False
        self._is_persistent = False
        self._shortcut_pending = False
        self._palette = blender_theme_palette(context)
        return True

    def draw(self):
        if _ACTIVE_OPERATOR is not None:
            return
        context = bpy.context
        if self.configure(context):
            FBP_OT_GreasePencilFrameScrub._draw_callback(self)


def _preview_redraw_areas():
    """Collect preview areas and Preferences state in one window traversal."""
    redraw_areas = []
    preferences_open = False
    try:
        window_manager = bpy.context.window_manager
        for window in tuple(getattr(window_manager, "windows", ()) or ()):
            screen = getattr(window, "screen", None)
            for area in tuple(getattr(screen, "areas", ()) or ()):
                area_type = str(getattr(area, "type", "") or "")
                if area_type == "PREFERENCES":
                    preferences_open = True
                    redraw_areas.append(area)
                elif area_type == "VIEW_3D":
                    redraw_areas.append(area)
    except FBP_DATA_ERRORS:
        return (), False
    return tuple(redraw_areas), preferences_open


def _tag_preview_redraw(areas=None):
    if areas is None:
        areas, _preferences_open = _preview_redraw_areas()
    for area in tuple(areas or ()):
        try:
            area.tag_redraw()
        except FBP_DATA_ERRORS:
            continue


def is_scrub_preview_active():
    return bool(_PREVIEW_ACTIVE and _PREVIEW_DRAW_HANDLE is not None)


def _stop_scrub_preview():
    global _PREVIEW_ACTIVE, _PREVIEW_DRAW_HANDLE, _PREVIEW_STATE
    _PREVIEW_ACTIVE = False
    handle = _PREVIEW_DRAW_HANDLE
    _PREVIEW_DRAW_HANDLE = None
    _PREVIEW_STATE = None
    if handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except FBP_DATA_ERRORS:
            pass
    cancel_scheduled_prefixes("grease_pencil.scrub_preview")
    _tag_preview_redraw()


def _scrub_preview_watchdog():
    if not is_scrub_preview_active():
        return None
    areas, preferences_open = _preview_redraw_areas()
    if not preferences_open:
        _stop_scrub_preview()
        return None
    _tag_preview_redraw(areas)
    return 0.10


def _start_scrub_preview():
    global _PREVIEW_ACTIVE, _PREVIEW_DRAW_HANDLE, _PREVIEW_STATE
    if is_scrub_preview_active():
        return True
    try:
        _PREVIEW_STATE = _ScrubPreviewOverlay()
        _PREVIEW_DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            _PREVIEW_STATE.draw,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
        _PREVIEW_ACTIVE = True
        if not schedule_once(
            "grease_pencil.scrub_preview.watchdog",
            _scrub_preview_watchdog,
            first_interval=0.05,
        ):
            raise RuntimeError("Could not schedule the scrub preview watchdog")
        _tag_preview_redraw()
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not start the Frame Scrub Slider preview", exc)
        _stop_scrub_preview()
        return False


class FBP_OT_GreasePencilScrubPreview(Operator):
    """Toggle a temporary live slider preview while Preferences stay open."""

    bl_idname = "fbp.grease_pencil_scrub_preview"
    bl_label = "Preview Frame Scrub Slider"
    bl_description = "Show the slider in visible 3D Viewports while editing its Preferences; it closes automatically with Preferences"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return str(getattr(getattr(context, "area", None), "type", "") or "") == "PREFERENCES"

    def execute(self, context):
        if is_scrub_preview_active():
            _stop_scrub_preview()
        elif not _start_scrub_preview():
            self.report({"WARNING"}, "Could not show the Frame Scrub Slider preview")
            return {"CANCELLED"}
        return {"FINISHED"}


_classes = (
    FBP_OT_GreasePencilFrameScrub,
    FBP_OT_ToggleGreasePencilScrubSlider,
    FBP_OT_ToggleScrubOnionInterface,
    FBP_OT_CopyGreasePencilScrubKeyframes,
    FBP_OT_PasteGreasePencilScrubKeyframes,
    FBP_OT_DuplicateGreasePencilScrubKeyframes,
    FBP_OT_DeleteGreasePencilScrubKeyframes,
    FBP_OT_SelectAllGreasePencilScrubKeyframes,
    FBP_OT_MirrorGreasePencilScrubKeyframes,
    FBP_OT_AddScrubBookmark,
    FBP_OT_RenameScrubBookmark,
    FBP_OT_SetScrubBookmarkColor,
    FBP_OT_SelectScrubBookmarks,
    FBP_OT_RemoveScrubBookmark,
    FBP_OT_DeleteAllScrubBookmarks,
    FBP_OT_DuplicateScrubBookmarks,
    FBP_OT_SetGreasePencilScrubKeyframeType,
    FBP_OT_SetGreasePencilScrubPosition,
    FBP_MT_GreasePencilScrubKeyframeType,
    FBP_MT_GreasePencilScrubMirror,
    FBP_MT_ScrubBookmarkColor,
    FBP_MT_ScrubBookmarkMenu,
    FBP_MT_GreasePencilScrubContextMenu,
    FBP_PT_GreasePencilScrubSliderPopover,
    FBP_OT_GreasePencilScrubPreview,
)
_registered_classes = globals().get("_registered_classes", [])
if not isinstance(_registered_classes, list):
    _registered_classes = []


def _unregister_keymaps():
    unregister_keymap_items(_GP_SCRUB_KEYMAPS)


def _register_keymaps():
    _unregister_keymaps()
    if not shortcut_enabled("shortcut_gp_frame_scrub"):
        return False
    keymap_names = ["3D View"]
    registered = False
    for requested_name in keymap_names:
        candidates = native_keymap_names((requested_name,))
        keymap_name = candidates[0] if candidates else requested_name
        keymap = addon_keymap(
            keymap_name,
            fallback_space_type="VIEW_3D",
            fallback_region_type="WINDOW",
        )
        if keymap is None:
            continue
        remove_matching_keymap_items(
            keymap,
            lambda item: str(getattr(item, "idname", "") or "") in {
                FBP_OT_GreasePencilFrameScrub.bl_idname,
                "fbp.grease_pencil_keyframe_type_pie",
            },
        )
        for event_type, shift in (("GRLESS", False), ("COMMA", True)):
            try:
                item = keymap.keymap_items.new(
                    FBP_OT_GreasePencilFrameScrub.bl_idname,
                    type=event_type,
                    value="PRESS",
                    shift=shift,
                )
                _GP_SCRUB_KEYMAPS.append((keymap, item))
                registered = True
            except FBP_DATA_ERRORS as exc:
                fbp_warn(
                    f"Could not register {keymap_name} scrub shortcut {event_type}",
                    exc,
                )
    return registered


def refresh_keymaps():
    return refresh_keymap_registration(_register_keymaps)


def quiesce_scrub_runtime():
    """Stop modal and preview runtime before any RNA/UI class is removed."""
    global _ACTIVE_OPERATOR
    _stop_scrub_preview()
    active = _ACTIVE_OPERATOR
    _ACTIVE_OPERATOR = None
    if active is None:
        return False
    try:
        active._cleanup(bpy.context)
        return True
    except FBP_DATA_ERRORS:
        return False


def register():
    quiesce_scrub_runtime()
    _registered_classes.clear()
    try:
        _registered_classes.extend(register_interactive_classes(_classes))
        _register_header()
        _register_keymaps()
    except Exception:
        _unregister_header()
        _unregister_keymaps()
        unregister_classes(tuple(_registered_classes))
        _registered_classes.clear()
        raise


def unregister():
    _clear_scrub_frame_clipboard()
    clear_scrub_history_frame_state()
    _PERSISTENT_SCRUB_BINDINGS.clear()
    _unregister_header()
    quiesce_scrub_runtime()
    _unregister_keymaps()
    unregister_classes(tuple(_registered_classes))
    _registered_classes.clear()
