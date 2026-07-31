"""Procedural Motion system for Frame By Plane.

The first production alpha deliberately applies motion through Blender delta
transforms.  Base transforms and ordinary keyframes stay untouched, multiple
Motion instances can be layered, and the same evaluator works for FBP layer
controllers and cameras.  Later milestones can reuse this data model for
shared controllers, stagger, paths, springs and baking.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from bisect import bisect_left

import bpy
try:
    from bpy.app.handlers import persistent
except (ImportError, AttributeError):  # Blender-light tests
    persistent = lambda function: function
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Menu, Operator, Panel, PropertyGroup, UIList

from .constants import fbp_icon
from .math_utils import clamp, sorted_finite_values, value_near_sorted
from .layers import fbp_set_ui_units_x
from .registration import (
    append_handler_once,
    register_classes,
    remove_handlers_by_name,
    unregister_classes,
    unregister_type_properties,
)
from .service_registry import service_descriptor
from .ui_list_state import invoke_with_selection_modifiers
from .shortcut_runtime import primary_modifier_name
from .runtime import (
    FBP_DATA_ERRORS,
    fbp_is_silent_property_update,
    fbp_render_mutation_blocked,
    fbp_runtime_get,
    fbp_undo_guard_active,
    fbp_obj_runtime_key,
    fbp_obj_runtime_token,
    fbp_rna_runtime_key,
    fbp_find_id_by_runtime_key,
    fbp_depsgraph_quiet_for,
    fbp_selection_snapshot,
    fbp_is_grease_pencil_interaction_mode,
    fbp_action_fcurves,
    fbp_warn,
    fbp_capture_runtime_targets as _motion_capture_runtime_targets
)
from .ui_style import (
    FBP_UI_LIST_MIN_ROWS,
    adaptive_row,
    configure_layout,
    empty_state,
    hint_row,
    section_gap,
    section_header,
)
from .ui_list_state import (
    clear_anchor,
    ensure_item_identity,
    ensure_unique_item_identities,
    resolve_anchor_index,
    restore_active_index,
    store_anchor,
    transient_get,
)
from .interface_preferences import (
    fbp_draw_uilist_spacer,
    fbp_draw_uilist_header,
    fbp_filter_uilist_items,
    fbp_uilist_icon_order,
    fbp_uilist_is_spacer,
    fbp_uilist_visible_columns,
)
from .ui_list_state import mark_ui_list_draw


SERVICE_ID = "motion_system"
SERVICE_API_VERSION = 1


class _FBPMotionDrawProxy:
    """Minimal reusable panel proxy for the embedded Motion editor."""

    __slots__ = ("layout", "_fbp_motion_target", "_fbp_motion_embedded")

    def __init__(self, layout, target):
        self.layout = layout
        self._fbp_motion_target = target
        self._fbp_motion_embedded = True


CAPABILITIES = (
    "PRESETS", "MULTI_INSTANCE", "CAMERA", "DETERMINISTIC", "LINKING",
    "STAGGER", "FALLOFF", "PATH", "SPRING_FOLLOW", "CHANNEL_BAKE",
    "KEY_REDUCTION",
)

MOTION_PRESET_ITEMS = (
    ("INFINITE_ROTATION", "Infinite Rotation", "Continuous loopable rotation"),
    ("FLOATING", "Floating", "Soft vertical drift with subtle rotation"),
    ("HANDHELD", "Handheld", "Smooth deterministic position and rotation noise"),
    ("BREATHING", "Breathing", "Gentle scale and vertical breathing motion"),
    ("PENDULUM", "Pendulum", "Looping rotational swing"),
    ("CAMERA_DRIFT", "Camera Drift", "Slow low-frequency camera or layer drift"),
    ("STOP_MOTION_JITTER", "Stop-Motion Jitter", "Stepped deterministic transform jitter"),
    ("WIND_DRIFT", "Wind Drift", "Layered sine drift for paper and foliage"),
    ("HOVER", "Hover", "Soft hovering with a secondary vertical pulse"),
    ("MECHANICAL_VIBRATION", "Mechanical Vibration", "Fast precise vibration for machines and signs"),
    ("ELASTIC_BOUNCE", "Elastic Bounce", "Looping damped-looking bounce with scale response"),
    ("SLOW_ORBIT", "Slow Orbit", "Slow circular position motion around the neutral pose"),
    ("PARALLAX_SWAY", "Parallax Sway", "Horizontal and depth sway for layered scenes"),
    ("WATER_DRIFT", "Water Drift", "Layered floating motion with soft irregular currents"),
    ("PAPER_FLUTTER", "Paper Flutter", "Fast light rotation and lift for paper or leaves"),
    ("HANGING_SIGN", "Hanging Sign", "Weighted hanging swing with a subtle secondary axis"),
    ("IDLE_CHARACTER", "Idle Character", "Breathing, weight shift and gentle character sway"),
    ("FOLLOW_THROUGH", "Follow Through", "Delayed secondary oscillation for loose elements"),
    ("FOLLOW_PATH", "Follow Curve", "Move along a Curve with constant-speed sampling"),
    ("SPRING_FOLLOW", "Follow Spring", "Follow another Motion target through a visible spring coil"),
    ("FOLLOW_SPIRAL", "Follow Spiral", "Move along an inward or outward spiral path"),
)


MOTION_EFFECT_ITEMS = (
    ("DRIFT", "Drift / Camera Feel", "One Motion effect for floating, handheld and camera drift variants"),
    ("SWING", "Swing / Hanging", "One Motion effect for pendulum and hanging sign variants"),
    ("BREATHING", "Breathing / Scale", "Planar scale breathing with X/Y scale only"),
    ("LOOP", "Loop / Rotation", "Looping rotation and orbit-style motion"),
    ("NOISE", "Noise / Jitter", "Stepped jitter and vibration motion"),
    ("NATURE", "Nature / Organic", "Wind, water and paper-style organic motion"),
    ("BOUNCE", "Bounce", "Elastic bounce-style motion"),
    ("CHARACTER", "Character", "Idle character motion presets"),
    ("SECONDARY", "Secondary Motion", "Follow-through and delayed secondary motion"),
    ("FOLLOW", "Follow", "Curve and spring following motion"),
)

MOTION_EFFECT_ICONS = {
    "DRIFT": "VIEW_CAMERA",
    "SWING": "PROP_CON",
    "BREATHING": "FULLSCREEN_ENTER",
    "LOOP": "FILE_REFRESH",
    "NOISE": "SNAP_GRID",
    "NATURE": "FORCE_WIND",
    "BOUNCE": "MOD_SIMPLEDEFORM",
    "CHARACTER": "OUTLINER_OB_ARMATURE",
    "SECONDARY": "MOD_SIMPLEDEFORM",
    "FOLLOW": "CURVE_DATA",
}

MOTION_EFFECT_DEFAULT_PRESET = {
    "DRIFT": "FLOATING",
    "SWING": "PENDULUM",
    "BREATHING": "BREATHING",
    "LOOP": "INFINITE_ROTATION",
    "NOISE": "STOP_MOTION_JITTER",
    "NATURE": "WIND_DRIFT",
    "BOUNCE": "ELASTIC_BOUNCE",
    "CHARACTER": "IDLE_CHARACTER",
    "SECONDARY": "FOLLOW_THROUGH",
    "FOLLOW": "FOLLOW_PATH",
}

MOTION_AXIS_ITEMS = (
    ("X", "X", "Use the X axis"),
    ("Y", "Y", "Use the Y axis"),
    ("Z", "Z", "Use the Z axis"),
    ("ALL", "XYZ", "Use all configured channels"),
)

MOTION_SPACE_ITEMS = (
    ("LOCAL", "Local", "Evaluate position offsets in the target's local space"),
    ("WORLD", "World", "Convert position offsets from world space into the target's local space"),
)

MOTION_ANCHOR_ITEMS = (
    ("CENTER", "Center", "Use the target origin as the rotation anchor"),
    ("TOP", "Top", "Use the top edge as the rotation anchor"),
    ("BOTTOM", "Bottom", "Use the bottom edge as the rotation anchor"),
    ("LEFT", "Left", "Use the left edge as the rotation anchor"),
    ("RIGHT", "Right", "Use the right edge as the rotation anchor"),
)

MOTION_STAGGER_ITEMS = (
    ("PROGRESSIVE", "Progressive", "Offset layers from first to last"),
    ("REVERSE", "Reverse", "Offset layers from last to first"),
    ("CENTERED", "Centred", "Offset layers around the middle of the selection"),
    ("PING_PONG", "Ping-Pong", "Increase toward the centre, then decrease"),
    ("RANDOM", "Random", "Use a deterministic random order"),
)

MOTION_FALLOFF_ITEMS = (
    ("NONE", "None", "Keep the same influence on every target"),
    ("FRONT_TO_BACK", "Front to Back", "Reduce influence from the first layer to the last"),
    ("BACK_TO_FRONT", "Back to Front", "Increase influence from the first layer to the last"),
    ("RANDOM", "Random", "Use deterministic random influence values"),
    ("BY_DISTANCE", "By Distance", "Reduce influence with world-space distance from the active target"),
)

MOTION_PATH_MODE_ITEMS = (
    ("FORWARD", "Forward", "Travel from the beginning to the end of the Curve"),
    ("REVERSE", "Reverse", "Travel from the end to the beginning of the Curve"),
    ("PING_PONG", "Ping-Pong", "Travel forward and backward continuously"),
)

MOTION_FOLLOW_CURVE_SHAPE_ITEMS = (
    ("BEZIER", "Bezier", "Generate a smooth 45-degree Bezier follow curve"),
    ("LINE", "Line", "Generate a straight follow curve"),
    ("ZIG_ZAG", "Zig Zag", "Generate a clean 45-degree zig-zag follow curve"),
    ("CIRCLE", "Circle", "Generate a true circular follow curve"),
    ("SPIRAL", "Spiral", "Generate an expanding spiral follow curve"),
)

MOTION_SPIRAL_DIRECTION_ITEMS = (
    ("OUTWARD", "Center Out", "Start from the center and move outward"),
    ("INWARD", "Outside In", "Start from the outside and move toward the center"),
)

MOTION_SLOT_ITEMS = (
    ("LOCAL", "No Slot", "Keep this Motion independent", fbp_icon("UNLOCKED"), 0),
    ("SLOT_1", "SLOT 1", "Share this Motion through SLOT 1", fbp_icon("STRIP_COLOR_01"), 1),
    ("SLOT_2", "SLOT 2", "Share this Motion through SLOT 2", fbp_icon("STRIP_COLOR_02"), 2),
    ("SLOT_3", "SLOT 3", "Share this Motion through SLOT 3", fbp_icon("STRIP_COLOR_03"), 3),
    ("SLOT_4", "SLOT 4", "Share this Motion through SLOT 4", fbp_icon("STRIP_COLOR_04"), 4),
    ("SLOT_5", "SLOT 5", "Share this Motion through SLOT 5", fbp_icon("STRIP_COLOR_05"), 5),
    ("SLOT_6", "SLOT 6", "Share this Motion through SLOT 6", fbp_icon("STRIP_COLOR_06"), 6),
    ("SLOT_7", "SLOT 7", "Share this Motion through SLOT 7", fbp_icon("STRIP_COLOR_07"), 7),
    ("SLOT_8", "SLOT 8", "Share this Motion through SLOT 8", fbp_icon("STRIP_COLOR_08"), 8),
)

MOTION_PRESET_ICONS = {
    "INFINITE_ROTATION": "FILE_REFRESH",
    "FLOATING": "EMPTY_ARROWS",
    "HANDHELD": "VIEW_CAMERA",
    "BREATHING": "MOD_WAVE",
    "PENDULUM": "MOD_WAVE",
    "CAMERA_DRIFT": "CAMERA_DATA",
    "STOP_MOTION_JITTER": "SNAP_GRID",
    "WIND_DRIFT": "FORCE_WIND",
    "HOVER": "EMPTY_ARROWS",
    "MECHANICAL_VIBRATION": "MOD_DISPLACE",
    "ELASTIC_BOUNCE": "MOD_SIMPLEDEFORM",
    "SLOW_ORBIT": "WORLD",
    "PARALLAX_SWAY": "VIEW_CAMERA",
    "WATER_DRIFT": "MOD_WAVE",
    "PAPER_FLUTTER": "PARTICLES",
    "HANGING_SIGN": "PROP_CON",
    "IDLE_CHARACTER": "OUTLINER_OB_ARMATURE",
    "FOLLOW_THROUGH": "MOD_SIMPLEDEFORM",
    "FOLLOW_PATH": "IPO_EASE_IN_OUT",
    "SPRING_FOLLOW": "MOD_SCREW",
    "FOLLOW_SPIRAL": "FORCE_VORTEX",
}

MOTION_SLOT_ICONS = {
    "LOCAL": "UNLOCKED",
    "SLOT_1": "STRIP_COLOR_01",
    "SLOT_2": "STRIP_COLOR_02",
    "SLOT_3": "STRIP_COLOR_03",
    "SLOT_4": "STRIP_COLOR_04",
    "SLOT_5": "STRIP_COLOR_05",
    "SLOT_6": "STRIP_COLOR_06",
    "SLOT_7": "STRIP_COLOR_07",
    "SLOT_8": "STRIP_COLOR_08",
}

_PRESET_LABELS = {item[0]: item[1] for item in MOTION_PRESET_ITEMS}
_SLOT_LABELS = {item[0]: item[1] for item in MOTION_SLOT_ITEMS}

MOTION_PRESET_FAMILIES = {
    "INFINITE_ROTATION": "LOOP",
    "FLOATING": "DRIFT",
    "HANDHELD": "DRIFT",
    "CAMERA_DRIFT": "DRIFT",
    "BREATHING": "BREATHING",
    "PENDULUM": "SWING",
    "HANGING_SIGN": "SWING",
    "STOP_MOTION_JITTER": "NOISE",
    "WIND_DRIFT": "NATURE",
    "HOVER": "DRIFT",
    "MECHANICAL_VIBRATION": "NOISE",
    "ELASTIC_BOUNCE": "BOUNCE",
    "SLOW_ORBIT": "LOOP",
    "PARALLAX_SWAY": "DRIFT",
    "WATER_DRIFT": "NATURE",
    "PAPER_FLUTTER": "NATURE",
    "IDLE_CHARACTER": "CHARACTER",
    "FOLLOW_THROUGH": "SECONDARY",
    "FOLLOW_PATH": "FOLLOW",
    "SPRING_FOLLOW": "FOLLOW",
    "FOLLOW_SPIRAL": "FOLLOW",
}

MOTION_FAMILY_LABELS = {
    "DRIFT": "Drift / Camera Feel",
    "SWING": "Swing / Hanging",
    "BREATHING": "Breathing / Scale",
    "LOOP": "Loop / Rotation",
    "NOISE": "Noise / Jitter",
    "NATURE": "Nature / Organic",
    "BOUNCE": "Bounce",
    "CHARACTER": "Character",
    "SECONDARY": "Secondary Motion",
    "FOLLOW": "Follow",
}

MOTION_FAMILY_ORDER = (
    "DRIFT", "SWING", "BREATHING", "LOOP", "NOISE",
    "NATURE", "BOUNCE", "CHARACTER", "SECONDARY", "FOLLOW",
)


def _motion_effect_for_preset(preset):
    """Return the visible Motion effect family for a stored preset."""
    preset = str(preset or "FLOATING")
    return MOTION_PRESET_FAMILIES.get(preset, "DRIFT")


def _motion_effect_label(effect):
    return MOTION_FAMILY_LABELS.get(str(effect or "DRIFT"), "Motion")


def _motion_effect_icon(effect):
    return MOTION_EFFECT_ICONS.get(str(effect or "DRIFT"), "TIME")


def _motion_preset_icon_name(preset):
    """Return the Blender icon key for a Motion preset.

    Keep Follow presets explicit here so every list/menu/header that names
    Follow Curve, Follow Spiral or Follow Spring uses the requested icon.
    """
    preset = str(preset or "FLOATING")
    return MOTION_PRESET_ICONS.get(preset, _motion_effect_icon(_motion_effect_for_preset(preset)))


def _motion_preset_icon(preset, fallback="TIME"):
    return fbp_icon(_motion_preset_icon_name(preset), fallback)


def _motion_default_preset_for_effect(effect):
    return MOTION_EFFECT_DEFAULT_PRESET.get(str(effect or "DRIFT"), "FLOATING")


_PRESET_DEFAULTS = {
    "INFINITE_ROTATION": {
        "axis": "Z", "amount": 1.0, "speed": 0.12, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.0, 0.0, 0.0),
        # Store the full rotation amount on every channel so X/Y/Z axis
        # switching works without needing hidden channel-strength edits.
        "rotation_strength": (math.radians(360.0), math.radians(360.0), math.radians(360.0)),
        "scale_strength": 0.0,
    },
    "FLOATING": {
        "axis": "Z", "amount": 1.0, "speed": 0.35, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.025, 0.025, 0.12),
        "rotation_strength": (math.radians(1.2), math.radians(1.2), math.radians(2.0)),
        "scale_strength": 0.0,
        "position_axis_x": True, "position_axis_y": True, "position_axis_z": True,
        "position_strength": 1.0, "position_speed": 0.35,
    },
    "HANDHELD": {
        "axis": "ALL", "amount": 1.0, "speed": 1.0, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.025, 0.025, 0.012),
        "rotation_strength": (math.radians(0.8), math.radians(0.8), math.radians(1.2)),
        "scale_strength": 0.0,
        "position_axis_x": True, "position_axis_y": True, "position_axis_z": True,
        "position_strength": 1.0, "position_speed": 1.0,
    },
    "BREATHING": {
        "axis": "ALL", "amount": 1.0, "speed": 0.22, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.0, 0.0, 0.0),
        "rotation_strength": (0.0, 0.0, 0.0), "scale_strength": 0.025,
        # Breathing is a planar scale pulse only. Keep Z hidden/disabled so it
        # does not imply depth scaling on image planes.
        "scale_axis_x": True, "scale_axis_y": True, "scale_axis_z": False,
        "position_axis_x": False, "position_axis_y": False, "position_axis_z": False,
        "position_strength": 0.0, "position_speed": 0.22,
    },
    "PENDULUM": {
        "axis": "Z", "amount": 1.0, "speed": 0.35, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.0, 0.0, 0.0),
        "rotation_strength": (math.radians(12.0), math.radians(12.0), math.radians(12.0)),
        "scale_strength": 0.0, "anchor_point": "TOP",
    },
    "CAMERA_DRIFT": {
        "axis": "ALL", "amount": 1.0, "speed": 0.12, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.035, 0.025, 0.018),
        "rotation_strength": (math.radians(0.35), math.radians(0.45), math.radians(0.25)),
        "scale_strength": 0.0,
        "position_axis_x": True, "position_axis_y": True, "position_axis_z": True,
        "position_strength": 1.0, "position_speed": 0.12,
    },
    "STOP_MOTION_JITTER": {
        "axis": "ALL", "amount": 1.0, "speed": 1.0, "phase": 0.0,
        "step_frames": 3, "location_strength": (0.012, 0.012, 0.006),
        "rotation_strength": (math.radians(0.45), math.radians(0.45), math.radians(0.8)),
        "scale_strength": 0.006,
    },
    "WIND_DRIFT": {
        "axis": "ALL", "amount": 1.0, "speed": 0.28, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.06, 0.018, 0.045),
        "rotation_strength": (math.radians(1.0), math.radians(3.0), math.radians(2.0)),
        "scale_strength": 0.004,
    },
    "HOVER": {
        "axis": "ALL", "amount": 1.0, "speed": 0.32, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.018, 0.018, 0.09),
        "rotation_strength": (math.radians(0.8), math.radians(0.8), math.radians(1.5)),
        "scale_strength": 0.004,
    },
    "MECHANICAL_VIBRATION": {
        "axis": "ALL", "amount": 1.0, "speed": 4.0, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.006, 0.006, 0.003),
        "rotation_strength": (math.radians(0.25), math.radians(0.25), math.radians(0.4)),
        "scale_strength": 0.0015,
    },
    "ELASTIC_BOUNCE": {
        "axis": "Z", "amount": 1.0, "speed": 0.6, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.0, 0.0, 0.12),
        "rotation_strength": (0.0, 0.0, 0.0), "scale_strength": 0.035,
    },
    "SLOW_ORBIT": {
        "axis": "ALL", "amount": 1.0, "speed": 0.12, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.08, 0.08, 0.02),
        "rotation_strength": (0.0, 0.0, math.radians(2.0)), "scale_strength": 0.0,
    },
    "PARALLAX_SWAY": {
        "axis": "ALL", "amount": 1.0, "speed": 0.22, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.08, 0.015, 0.05),
        "rotation_strength": (math.radians(0.4), math.radians(1.5), math.radians(1.0)),
        "scale_strength": 0.002,
    },
    "WATER_DRIFT": {
        "axis": "ALL", "amount": 1.0, "speed": 0.16, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.055, 0.028, 0.045),
        "rotation_strength": (math.radians(0.8), math.radians(1.1), math.radians(0.7)),
        "scale_strength": 0.003,
    },
    "PAPER_FLUTTER": {
        "axis": "ALL", "amount": 1.0, "speed": 1.15, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.012, 0.008, 0.035),
        "rotation_strength": (math.radians(2.5), math.radians(7.0), math.radians(3.0)),
        "scale_strength": 0.002,
    },
    "HANGING_SIGN": {
        "axis": "ALL", "amount": 1.0, "speed": 0.28, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.0, 0.0, 0.0),
        "rotation_strength": (math.radians(1.0), math.radians(0.5), math.radians(11.0)),
        "scale_strength": 0.0, "anchor_point": "TOP",
    },
    "IDLE_CHARACTER": {
        "axis": "ALL", "amount": 1.0, "speed": 0.18, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.018, 0.006, 0.022),
        "rotation_strength": (math.radians(0.5), math.radians(0.7), math.radians(0.8)),
        "scale_strength": 0.012,
    },
    "FOLLOW_THROUGH": {
        "axis": "ALL", "amount": 1.0, "speed": 0.42, "phase": 0.0,
        "step_frames": 1, "location_strength": (0.02, 0.01, 0.04),
        "rotation_strength": (math.radians(1.2), math.radians(2.5), math.radians(4.5)),
        "scale_strength": 0.004,
    },
    "FOLLOW_PATH": {
        "axis": "ALL", "amount": 1.0, "speed": 1.0, "phase": 0.0,
        "step_frames": 1, "location_strength": (1.0, 1.0, 1.0),
        "rotation_strength": (0.0, 0.0, 0.0), "scale_strength": 0.0,
        "space": "WORLD",
    },
    "SPRING_FOLLOW": {
        "axis": "ALL", "amount": 1.0, "speed": 1.0, "phase": 0.0,
        "step_frames": 1, "location_strength": (1.0, 1.0, 1.0),
        "rotation_strength": (0.0, 0.0, 0.0), "scale_strength": 0.0,
        "space": "LOCAL", "path_extend": 6, "path_radius": 1.0,
        "path_spacing": 1.0, "spring_flatten_2d": True,
    },
    "FOLLOW_SPIRAL": {
        "axis": "ALL", "amount": 1.0, "speed": 1.0, "phase": 0.0,
        "step_frames": 1, "location_strength": (1.0, 1.0, 1.0),
        "rotation_strength": (0.0, 0.0, 0.0), "scale_strength": 0.0,
        "space": "WORLD", "path_shape": "SPIRAL", "path_extend": 4,
        "path_radius": 1.0, "path_spacing": 1.0, "path_spiral_direction": "OUTWARD",
        "path_clockwise": False,
    },
}

_SHARED_MOTION_PROPERTIES = (
    "name", "effect", "preset", "slot", "amount", "speed", "step_frames", "space",
    "axis_x", "axis_y", "axis_z", "axis_buttons_initialized", "anchor_point",
    "start_frame", "end_frame", "loop_duration", "location_strength", "rotation_strength", "scale_strength",
    "position_axis_x", "position_axis_y", "position_axis_z", "position_strength", "position_speed",
    "scale_axis_x", "scale_axis_y", "scale_axis_z",
    "path_object", "path_duration", "path_loop", "path_extend", "path_shape", "path_mode",
    "path_follow_rotation", "path_bank_strength", "path_resolution", "path_radius",
    "path_spacing", "path_spiral_direction", "path_clockwise",
    "spring_target", "spring_delay", "spring_damping", "spring_stiffness",
    "spring_overshoot", "spring_flatten_2d", "spring_vertical", "spring_follow_location", "spring_follow_rotation",
    "spring_follow_scale",
)

_MOTION_UPDATE_GUARD = False
_MOTION_HANDLER_GUARD = False
_MOTION_DEFERRED_VIEWPORT_ACTIVE = False
_MOTION_LINK_GUARD = False
_MOTION_PATH_CACHE = {}
_MOTION_PATH_CACHE_LIMIT = 64
_MOTION_HELPER_VISIBILITY_GUARD = False
# The scheduler drops callbacks from an older module generation. Pending flags
# must therefore start clean or the first selection change after reload can be
# mistaken for work that is still queued.
_MOTION_HELPER_SELECTION_SIGNATURE = None
_MOTION_HELPER_PENDING_SIGNATURE = None
_MOTION_HELPER_VISIBILITY_TASK_PENDING = False
_MOTION_HELPER_LAST_SELECTION_CHECK = 0.0
_MOTION_HELPER_SELECTION_CHECK_INTERVAL = 0.05
_MOTION_TARGET_CACHE = globals().get("_MOTION_TARGET_CACHE", {})
if not isinstance(_MOTION_TARGET_CACHE, dict):
    _MOTION_TARGET_CACHE = {}
_MOTION_TARGET_CACHE_SECONDS = 8.0


def _prune_motion_target_cache(now=None):
    """Retire stale Motion target-cache entries without discarding fresh scenes."""
    try:
        now = time.monotonic() if now is None else float(now)
        cutoff = now - max(1.0, float(_MOTION_TARGET_CACHE_SECONDS) * 2.0)
        for key, payload in tuple(_MOTION_TARGET_CACHE.items()):
            checked_at = float((payload or {}).get("checked_at", 0.0) or 0.0)
            if checked_at < cutoff:
                _MOTION_TARGET_CACHE.pop(key, None)
        if len(_MOTION_TARGET_CACHE) <= 32:
            return
        ordered = sorted(
            _MOTION_TARGET_CACHE.items(),
            key=lambda item: float((item[1] or {}).get("checked_at", 0.0) or 0.0),
        )
        for key, _payload in ordered[: max(1, len(ordered) - 16)]:
            _MOTION_TARGET_CACHE.pop(key, None)
    except Exception:
        _MOTION_TARGET_CACHE.clear()


def _clear_motion_path_cache():
    _MOTION_PATH_CACHE.clear()


def clear_motion_runtime_caches():
    """Drop Motion-only runtime caches before Undo, file load or reload."""
    global _MOTION_HELPER_SELECTION_SIGNATURE, _MOTION_HELPER_PENDING_SIGNATURE
    global _MOTION_HELPER_VISIBILITY_TASK_PENDING, _MOTION_HELPER_LAST_SELECTION_CHECK
    _clear_motion_path_cache()
    _clear_motion_target_cache(None)
    _MOTION_HELPER_SELECTION_SIGNATURE = None
    _MOTION_HELPER_PENDING_SIGNATURE = None
    _MOTION_HELPER_VISIBILITY_TASK_PENDING = False
    _MOTION_HELPER_LAST_SELECTION_CHECK = 0.0


def service_status():
    return service_descriptor(SERVICE_ID, SERVICE_API_VERSION, CAPABILITIES)


def motion_bake_frames(start, end, step=1):
    """Return an inclusive deterministic frame sequence for Motion baking."""
    start = int(start)
    end = int(end)
    step = max(1, int(step))
    if end < start:
        raise ValueError("Bake End must be greater than or equal to Bake Start")
    frames = list(range(start, end + 1, step))
    if not frames or frames[-1] != end:
        frames.append(end)
    return tuple(frames)


def _target_action_fcurves(target):
    animation_data = getattr(target, "animation_data", None)
    action = getattr(animation_data, "action", None) if animation_data is not None else None
    if action is None:
        return ()
    curves = fbp_action_fcurves(target)
    if curves is not None:
        try:
            return tuple(curves)
        except (AttributeError, ReferenceError, TypeError):
            return ()
    handle = int(getattr(animation_data, "action_slot_handle", 0) or 0)
    result = []
    try:
        for layer in action.layers:
            for strip in layer.strips:
                for channelbag in strip.channelbags:
                    if handle and int(getattr(channelbag, "slot_handle", 0) or 0) != handle:
                        continue
                    result.extend(tuple(channelbag.fcurves))
    except (AttributeError, ReferenceError, TypeError):
        pass
    return tuple(result)


def _normalize_bake_channels(channels=None):
    requested = ("LOCATION", "ROTATION", "SCALE") if channels is None else tuple(channels)
    mapping = {
        "LOCATION": "delta_location",
        "ROTATION": "delta_rotation_euler",
        "SCALE": "delta_scale",
        "delta_location": "delta_location",
        "delta_rotation_euler": "delta_rotation_euler",
        "delta_scale": "delta_scale",
    }
    paths = []
    for channel in requested:
        path = mapping.get(str(channel or "").upper(), mapping.get(str(channel or "")))
        if path and path not in paths:
            paths.append(path)
    return tuple(paths)


def motion_bake_conflicts(target, start, end, channels=None):
    paths = set(_normalize_bake_channels(channels))
    try:
        lower, upper = sorted((float(start), float(end)))
    except (OverflowError, TypeError, ValueError):
        return 0
    if not math.isfinite(lower) or not math.isfinite(upper):
        return 0
    conflicts = 0
    for fcurve in _target_action_fcurves(target):
        if str(getattr(fcurve, "data_path", "")) not in paths:
            continue
        try:
            conflicts += sum(
                1 for point in fcurve.keyframe_points
                if lower <= float(point.co.x) <= upper
            )
        except FBP_DATA_ERRORS:
            continue
    return conflicts


def _set_baked_key_interpolation(target, frames, channels=None):
    paths = set(_normalize_bake_channels(channels))
    frame_values = sorted_finite_values(frames)
    if not paths or not frame_values:
        return 0
    changed = 0
    for fcurve in _target_action_fcurves(target):
        if str(getattr(fcurve, "data_path", "")) not in paths:
            continue
        try:
            for point in fcurve.keyframe_points:
                if value_near_sorted(point.co.x, frame_values):
                    point.interpolation = "LINEAR"
                    point.type = "GENERATED"
                    changed += 1
        except FBP_DATA_ERRORS:
            continue
    return changed


def motion_reduce_samples(samples, tolerance):
    """Return safe retained indices for scalar Ramer-Douglas-Peucker reduction.

    Malformed or non-finite samples are never reduced. Keeping every original
    key is safer than deleting animation data from a partially corrupted F-Curve.
    """
    original = tuple(samples or ())
    try:
        epsilon = abs(float(tolerance))
    except (OverflowError, TypeError, ValueError):
        return tuple(range(len(original)))
    if not math.isfinite(epsilon) or epsilon <= 0.0 or len(original) <= 2:
        return tuple(range(len(original)))
    normalized = []
    try:
        for frame, value in original:
            frame_value = float(frame)
            sample_value = float(value)
            if not math.isfinite(frame_value) or not math.isfinite(sample_value):
                return tuple(range(len(original)))
            normalized.append((frame_value, sample_value))
    except (OverflowError, TypeError, ValueError):
        return tuple(range(len(original)))
    samples = tuple(normalized)
    keep = {0, len(samples) - 1}
    stack = [(0, len(samples) - 1)]
    tolerance = epsilon
    while stack:
        first, last = stack.pop()
        x0, y0 = samples[first]
        x1, y1 = samples[last]
        span = x1 - x0
        best_index = None
        best_error = -1.0
        for index in range(first + 1, last):
            x, y = samples[index]
            factor = 0.0 if abs(span) <= 1.0e-12 else (x - x0) / span
            expected = y0 + (y1 - y0) * factor
            error = abs(y - expected)
            if error > best_error:
                best_error = error
                best_index = index
        if best_index is not None and best_error > tolerance:
            keep.add(best_index)
            stack.append((first, best_index))
            stack.append((best_index, last))
    return tuple(sorted(keep))


def reduce_generated_motion_keys(target, start, end, channels=None, tolerance=0.0):
    paths = set(_normalize_bake_channels(channels))
    try:
        tolerance = float(tolerance or 0.0)
    except (OverflowError, TypeError, ValueError):
        return 0
    if not math.isfinite(tolerance) or tolerance <= 0.0:
        return 0
    removed = 0
    for fcurve in _target_action_fcurves(target):
        if str(getattr(fcurve, "data_path", "")) not in paths:
            continue
        try:
            points = [point for point in fcurve.keyframe_points if int(start) <= float(point.co.x) <= int(end)]
            if len(points) <= 2:
                continue
            samples = tuple((float(point.co.x), float(point.co.y)) for point in points)
            keep_indices = set(motion_reduce_samples(samples, tolerance))
            for index in range(len(points) - 1, -1, -1):
                point = points[index]
                if index in keep_indices or str(getattr(point, "type", "")) != "GENERATED":
                    continue
                try:
                    fcurve.keyframe_points.remove(point, fast=True)
                except TypeError:
                    fcurve.keyframe_points.remove(point)
                removed += 1
            fcurve.update()
        except FBP_DATA_ERRORS:
            continue
    return removed


def bake_motion_to_keyframes(
    target, scene, start, end, *, step=1, overwrite=False, keep_procedural=True,
    channels=None, reduce_tolerance=0.0,
):
    """Bake selected Motion channels into native Generated delta keyframes."""
    if target is None or not _target_has_motion(target):
        raise ValueError("The selected target has no Motion stack")
    paths = _normalize_bake_channels(channels)
    if not paths:
        raise ValueError("Enable at least one Motion channel to bake")
    frames = motion_bake_frames(start, end, step)
    conflicts = motion_bake_conflicts(target, frames[0], frames[-1], paths)
    if conflicts and not overwrite:
        raise ValueError(f"{conflicts} selected delta-transform keyframe(s) already exist in the bake range")
    if not keep_procedural and any(str(getattr(item, "link_id", "") or "") for item in target.fbp_motions):
        raise ValueError("Keep the procedural stack or make shared Motion items local before removing them")

    original_frame = int(getattr(scene, "frame_current", frames[0]) or frames[0])
    original_master = bool(getattr(target, "fbp_motion_master_enabled", True))
    inserted = 0
    try:
        target.fbp_motion_master_enabled = True
        for frame in frames:
            scene.frame_set(int(frame))
            evaluate_motion_target(target, scene)
            for data_path in paths:
                if target.keyframe_insert(
                    data_path=data_path,
                    frame=int(frame),
                    group="FBP Motion Bake",
                    keytype="GENERATED",
                ):
                    inserted += 1
        _set_baked_key_interpolation(target, frames, paths)
        reduced = reduce_generated_motion_keys(
            target, frames[0], frames[-1], paths, tolerance=reduce_tolerance,
        )
        if keep_procedural:
            target.fbp_motion_master_enabled = False
        else:
            target.fbp_motions.clear()
            target.fbp_motion_active_index = 0
            target.fbp_motion_base_captured = False
            target.fbp_motion_master_enabled = True
        channel_label = ", ".join(path.replace("delta_", "").replace("_euler", "") for path in paths)
        target.fbp_motion_last_bake_report = (
            f"Baked {len(frames)} frame(s) · {channel_label} · {inserted} keys"
            f" · {reduced} reduced"
        )
    finally:
        scene.frame_set(original_frame)
        if not keep_procedural and not _target_has_motion(target):
            target.fbp_motion_master_enabled = True
        elif not keep_procedural:
            target.fbp_motion_master_enabled = original_master
    return {
        "frames": frames, "channels": inserted, "conflicts": conflicts,
        "paths": paths, "reduced": reduced,
    }

def _fract(value):
    return value - math.floor(value)


def _hash_signed(seed, channel, index):
    """Small deterministic hash in the -1..1 range."""
    value = math.sin(
        (int(seed) + 1) * 12.9898
        + (int(channel) + 1) * 78.233
        + (int(index) + 1) * 37.719
    ) * 43758.5453123
    return _fract(value) * 2.0 - 1.0


def _smooth_noise(seed, channel, position):
    left = math.floor(position)
    right = left + 1
    fraction = float(position) - left
    smooth = fraction * fraction * (3.0 - 2.0 * fraction)
    a = _hash_signed(seed, channel, left)
    b = _hash_signed(seed, channel, right)
    return a + (b - a) * smooth


def _motion_axis_mask(item):
    try:
        return (
            1.0 if bool(getattr(item, "axis_x", False)) else 0.0,
            1.0 if bool(getattr(item, "axis_y", False)) else 0.0,
            1.0 if bool(getattr(item, "axis_z", False)) else 0.0,
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return (1.0, 1.0, 1.0)


def _motion_position_axis_mask(item):
    try:
        return (
            1.0 if bool(getattr(item, "position_axis_x", True)) else 0.0,
            1.0 if bool(getattr(item, "position_axis_y", True)) else 0.0,
            1.0 if bool(getattr(item, "position_axis_z", True)) else 0.0,
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return _motion_axis_mask(item)


def _motion_scale_axis_mask(item):
    try:
        return (
            1.0 if bool(getattr(item, "scale_axis_x", True)) else 0.0,
            1.0 if bool(getattr(item, "scale_axis_y", True)) else 0.0,
            1.0 if bool(getattr(item, "scale_axis_z", False)) else 0.0,
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return _motion_axis_mask(item)


def _axis_bool_tuple_from_axis(axis):
    axis = str(axis or "ALL").upper()
    if axis == "X":
        return (True, False, False)
    if axis == "Y":
        return (False, True, False)
    if axis == "Z":
        return (False, False, True)
    return (True, True, True)


def _primary_axis_from_motion(item, fallback="Z"):
    mask = tuple(bool(getattr(item, name, False)) for name in ("axis_x", "axis_y", "axis_z"))
    for axis, enabled in zip(("X", "Y", "Z"), mask, strict=False):
        if enabled:
            return axis
    return str(fallback or "Z")


def _set_motion_axis_bools(item, axis):
    values = _axis_bool_tuple_from_axis(axis)
    try:
        item.axis_x, item.axis_y, item.axis_z = values
        item.axis_buttons_initialized = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def _motion_start_frame(item):
    return int(getattr(item, "start_frame", 0) or 0)


def _motion_end_frame(item):
    return int(getattr(item, "end_frame", 0) or 0)


def _motion_frame_is_active(item, frame):
    start = _motion_start_frame(item)
    end = _motion_end_frame(item)
    if float(frame) < float(start):
        return False
    if end > start and float(frame) > float(end):
        return False
    return True


def _motion_time(item, frame, fps):
    if not _motion_frame_is_active(item, frame):
        return None
    local_frame = float(frame) - float(_motion_start_frame(item))
    loop_duration = int(getattr(item, "loop_duration", 0) or 0)
    if loop_duration > 0:
        local_frame %= float(loop_duration)
    step = max(1, int(getattr(item, "step_frames", 1) or 1))
    if step > 1:
        local_frame = math.floor(local_frame / step) * step
    return local_frame, local_frame / max(1.0, float(fps or 24.0))


def evaluate_motion_item(item, frame, fps=24.0):
    """Evaluate one motion item without touching Blender data.

    The returned scale is an additive delta around 1.0.  This pure function is
    intentionally testable outside Blender and deterministic after save/reopen.
    """
    if item is None or not bool(getattr(item, "enabled", True)):
        return {"location": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0), "scale": (0.0, 0.0, 0.0)}

    preset = str(getattr(item, "preset", "FLOATING") or "FLOATING")
    influence = clamp(float(getattr(item, "influence", 1.0) or 0.0), 0.0, 1.0)
    amount = float(getattr(item, "amount", 1.0) or 0.0) * influence
    speed = float(getattr(item, "speed", 1.0) or 0.0)
    phase = float(getattr(item, "phase", 0.0) or 0.0)
    seed = int(getattr(item, "seed", 0) or 0)
    motion_time = _motion_time(item, frame, fps)
    if motion_time is None:
        return {"location": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0), "scale": (0.0, 0.0, 0.0)}
    local_frame, seconds = motion_time
    mask = _motion_axis_mask(item)
    loc_strength = tuple(getattr(item, "location_strength", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0))
    rot_strength = tuple(getattr(item, "rotation_strength", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0))
    scale_strength = float(getattr(item, "scale_strength", 0.0) or 0.0)
    scale_mask = _motion_scale_axis_mask(item)

    location = [0.0, 0.0, 0.0]
    rotation = [0.0, 0.0, 0.0]
    scale = [0.0, 0.0, 0.0]
    cycle = math.tau * speed * seconds + phase

    if preset == "INFINITE_ROTATION":
        # rotation_strength stores the amount generated over one cycle.  The
        # default is 360 degrees on Z, making speed a cycles-per-second value.
        turns = speed * seconds + phase / math.tau
        for i in range(3):
            rotation[i] = float(rot_strength[i]) * turns * amount * mask[i]
    elif preset == "FLOATING":
        position_mask = _motion_position_axis_mask(item)
        position_amount = float(getattr(item, "position_strength", 1.0) or 0.0) * influence
        position_speed = float(getattr(item, "position_speed", speed) or 0.0)
        position_cycle = math.tau * position_speed * seconds + phase
        wave = math.sin(position_cycle)
        secondary = math.sin(position_cycle * 0.63 + 1.7)
        rotation_wave = math.sin(cycle * 0.63 + 1.7)
        for i in range(3):
            location[i] = float(loc_strength[i]) * (wave if i == 2 else secondary) * position_amount * position_mask[i]
            rotation[i] = float(rot_strength[i]) * rotation_wave * amount * mask[i]
    elif preset == "HANDHELD":
        position_mask = _motion_position_axis_mask(item)
        position_amount = float(getattr(item, "position_strength", 1.0) or 0.0) * influence
        position_speed = float(getattr(item, "position_speed", speed) or 0.0)
        position_time = seconds * max(0.001, abs(position_speed)) * 3.0 + phase / math.tau
        rotation_time = seconds * max(0.001, abs(speed)) * 3.0 + phase / math.tau
        for i in range(3):
            location[i] = float(loc_strength[i]) * _smooth_noise(seed, i, position_time) * position_amount * position_mask[i]
            rotation[i] = float(rot_strength[i]) * _smooth_noise(seed + 31, i, rotation_time * 0.87) * amount * mask[i]
    elif preset == "BREATHING":
        wave = math.sin(cycle)
        # Breathing is intentionally scale-only: no position drift and no Z/depth scaling.
        breathing_scale_mask = (scale_mask[0], scale_mask[1], 0.0)
        for i in range(3):
            scale[i] = scale_strength * wave * amount * breathing_scale_mask[i]
    elif preset == "PENDULUM":
        wave = math.sin(cycle)
        for i in range(3):
            rotation[i] = float(rot_strength[i]) * wave * amount * mask[i]
    elif preset == "CAMERA_DRIFT":
        position_mask = _motion_position_axis_mask(item)
        position_amount = float(getattr(item, "position_strength", 1.0) or 0.0) * influence
        position_speed = float(getattr(item, "position_speed", speed) or 0.0)
        position_time = seconds * max(0.001, abs(position_speed)) + phase / math.tau
        rotation_time = seconds * max(0.001, abs(speed)) + phase / math.tau
        for i in range(3):
            location[i] = float(loc_strength[i]) * _smooth_noise(seed + 101, i, position_time) * position_amount * position_mask[i]
            rotation[i] = float(rot_strength[i]) * _smooth_noise(seed + 211, i, rotation_time * 0.72) * amount * mask[i]
    elif preset == "STOP_MOTION_JITTER":
        bucket = int(math.floor(local_frame / max(1, int(getattr(item, "step_frames", 1) or 1))))
        for i in range(3):
            location[i] = float(loc_strength[i]) * _hash_signed(seed, i, bucket) * amount * mask[i]
            rotation[i] = float(rot_strength[i]) * _hash_signed(seed + 67, i, bucket) * amount * mask[i]
            scale[i] = scale_strength * _hash_signed(seed + 131, i, bucket) * amount * scale_mask[i]
    elif preset == "WIND_DRIFT":
        wave_a = math.sin(cycle)
        wave_b = math.sin(cycle * 1.83 + 1.2 + seed * 0.071)
        combined = wave_a * 0.7 + wave_b * 0.3
        for i in range(3):
            location[i] = float(loc_strength[i]) * combined * amount * mask[i]
            rotation[i] = float(rot_strength[i]) * (wave_b if i == 1 else combined) * amount * mask[i]
            scale[i] = scale_strength * wave_a * amount * scale_mask[i]
    elif preset == "HOVER":
        primary = math.sin(cycle)
        secondary = math.sin(cycle * 0.5 + 1.1)
        pulse = math.sin(cycle * 2.0 + 0.4)
        for i in range(3):
            location[i] = float(loc_strength[i]) * (primary if i == 2 else secondary) * amount * mask[i]
            rotation[i] = float(rot_strength[i]) * secondary * amount * mask[i]
            scale[i] = scale_strength * pulse * amount * scale_mask[i]
    elif preset == "MECHANICAL_VIBRATION":
        sharp = math.sin(cycle) * 0.75 + math.sin(cycle * 2.0 + 0.3) * 0.25
        for i in range(3):
            location[i] = float(loc_strength[i]) * sharp * amount * mask[i]
            rotation[i] = float(rot_strength[i]) * math.sin(cycle * 1.5 + i) * amount * mask[i]
            scale[i] = scale_strength * math.sin(cycle * 2.0) * amount * scale_mask[i]
    elif preset == "ELASTIC_BOUNCE":
        wave = math.sin(cycle)
        shaped = math.copysign(abs(wave) ** 1.7, wave)
        squash = -abs(wave)
        for i in range(3):
            location[i] = float(loc_strength[i]) * shaped * amount * mask[i]
            rotation[i] = float(rot_strength[i]) * shaped * amount * mask[i]
            scale[i] = scale_strength * (shaped if i == 2 else squash) * amount * scale_mask[i]
    elif preset == "SLOW_ORBIT":
        orbit_x = math.cos(cycle)
        orbit_y = math.sin(cycle)
        orbit_z = math.sin(cycle * 0.5)
        waves = (orbit_x, orbit_y, orbit_z)
        for i in range(3):
            location[i] = float(loc_strength[i]) * waves[i] * amount * mask[i]
            rotation[i] = float(rot_strength[i]) * orbit_y * amount * mask[i]
    elif preset == "PARALLAX_SWAY":
        sway = math.sin(cycle)
        depth = math.sin(cycle * 0.5 + 0.8)
        waves = (sway, depth * 0.35, -sway * 0.55)
        for i in range(3):
            location[i] = float(loc_strength[i]) * waves[i] * amount * mask[i]
            rotation[i] = float(rot_strength[i]) * (depth if i == 1 else sway) * amount * mask[i]
            scale[i] = scale_strength * depth * amount * scale_mask[i]
    elif preset == "WATER_DRIFT":
        current_a = math.sin(cycle)
        current_b = math.sin(cycle * 0.47 + 1.9 + seed * 0.013)
        current_c = math.sin(cycle * 1.37 + 0.5)
        waves = (current_a * 0.65 + current_b * 0.35, current_b, current_c * 0.55)
        for i in range(3):
            location[i] = float(loc_strength[i]) * waves[i] * amount * mask[i]
            rotation[i] = float(rot_strength[i]) * (current_b * 0.7 + current_c * 0.3) * amount * mask[i]
            scale[i] = scale_strength * current_a * amount * scale_mask[i]
    elif preset == "PAPER_FLUTTER":
        flutter = math.sin(cycle) * 0.55 + math.sin(cycle * 2.41 + 0.7) * 0.3 + math.sin(cycle * 4.1) * 0.15
        lift = abs(math.sin(cycle * 0.5 + 0.8))
        for i in range(3):
            location[i] = float(loc_strength[i]) * (lift if i == 2 else flutter) * amount * mask[i]
            rotation[i] = float(rot_strength[i]) * flutter * amount * mask[i]
            scale[i] = scale_strength * flutter * amount * scale_mask[i]
    elif preset == "HANGING_SIGN":
        swing = math.sin(cycle)
        secondary = math.sin(cycle * 0.5 + 0.6)
        for i in range(3):
            rotation[i] = float(rot_strength[i]) * (swing if i == 2 else secondary) * amount * mask[i]
    elif preset == "IDLE_CHARACTER":
        breath = math.sin(cycle)
        shift = math.sin(cycle * 0.43 + 1.2)
        for i in range(3):
            location[i] = float(loc_strength[i]) * (breath if i == 2 else shift) * amount * mask[i]
            rotation[i] = float(rot_strength[i]) * shift * amount * mask[i]
            scale[i] = scale_strength * breath * amount * scale_mask[i]
    elif preset == "FOLLOW_THROUGH":
        primary = math.sin(cycle - 0.65)
        secondary = math.sin(cycle * 0.72 - 1.4)
        response = primary * 0.7 + secondary * 0.3
        for i in range(3):
            location[i] = float(loc_strength[i]) * response * amount * mask[i]
            rotation[i] = float(rot_strength[i]) * (secondary if i == 2 else response) * amount * mask[i]
            scale[i] = scale_strength * primary * amount * scale_mask[i]
    elif preset in {"FOLLOW_PATH", "FOLLOW_SPIRAL", "SPRING_FOLLOW"}:
        # These target-aware presets are evaluated by _evaluate_motion_stack().
        pass

    return {
        "location": tuple(location),
        "rotation": tuple(rotation),
        "scale": tuple(scale),
    }


def combine_motion_items(items, frame, fps=24.0):
    location = [0.0, 0.0, 0.0]
    rotation = [0.0, 0.0, 0.0]
    scale_factor = [1.0, 1.0, 1.0]
    for item in tuple(items or ()):
        values = evaluate_motion_item(item, frame, fps)
        for i in range(3):
            location[i] += values["location"][i]
            rotation[i] += values["rotation"][i]
            scale_factor[i] *= max(0.01, 1.0 + values["scale"][i])
    return {
        "location": tuple(location),
        "rotation": tuple(rotation),
        "scale_factor": tuple(scale_factor),
    }


def motion_effect_active(target):
    try:
        return bool(target is not None and (target.get("fbp_motion_effect_container", False) or len(target.fbp_motions) > 0))
    except FBP_DATA_ERRORS:
        return False


def remove_motion_effect(target):
    """Remove the Motion container and restore the captured neutral delta state."""
    if target is None:
        return False
    changed = False
    try:
        if len(target.fbp_motions):
            changed = _cleanup_motion_stack_helpers(target) or changed
            try:
                target.fbp_motions.clear()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                while len(target.fbp_motions):
                    target.fbp_motions.remove(len(target.fbp_motions) - 1)
            target.fbp_motion_active_index = 0
            changed = True
        changed = _restore_motion_base(target, clear=True) or changed
        if "fbp_motion_effect_container" in target:
            del target["fbp_motion_effect_container"]
            changed = True
    except FBP_DATA_ERRORS:
        return changed
    return changed


def _target_has_motion(target):
    try:
        return target is not None and len(target.fbp_motions) > 0
    except FBP_DATA_ERRORS:
        return False


def motion_distribution_values(count, mode="PROGRESSIVE", *, seed=0):
    """Return deterministic normalized values for stagger and falloff tools."""
    count = max(0, int(count or 0))
    if count == 0:
        return ()
    if count == 1:
        return (0.0,)
    mode = str(mode or "PROGRESSIVE")
    base = [index / float(count - 1) for index in range(count)]
    if mode == "REVERSE":
        return tuple(1.0 - value for value in base)
    if mode == "CENTERED":
        centre = (count - 1) * 0.5
        maximum = max(1.0, centre)
        return tuple((index - centre) / maximum for index in range(count))
    if mode == "PING_PONG":
        return tuple(1.0 - abs((value * 2.0) - 1.0) for value in base)
    if mode == "RANDOM":
        ordered = sorted(range(count), key=lambda index: (_hash_signed(seed, 97, index), index))
        ranks = [0.0] * count
        for rank, index in enumerate(ordered):
            ranks[index] = rank / float(count - 1)
        return tuple(ranks)
    return tuple(base)


def motion_distance_values(positions, reference_index=0, *, invert=False):
    """Return normalized influence values based on distance from one position."""
    positions = tuple(tuple(float(value) for value in position[:3]) for position in positions)
    if not positions:
        return ()
    reference_index = int(clamp(int(reference_index or 0), 0, len(positions) - 1))
    reference = positions[reference_index]
    distances = [math.sqrt(sum((position[i] - reference[i]) ** 2 for i in range(3))) for position in positions]
    maximum = max(distances)
    if maximum <= 1.0e-12:
        return tuple(1.0 for _ in positions)
    normalized = [distance / maximum for distance in distances]
    if invert:
        return tuple(normalized)
    return tuple(1.0 - value for value in normalized)


def _polyline_metrics(points):
    """Normalize adjacent duplicates and build cumulative arc-length metrics."""
    normalized = []
    for point in points or ():
        value = tuple(float(component) for component in point[:3])
        if not normalized or any(abs(value[i] - normalized[-1][i]) > 1.0e-12 for i in range(3)):
            normalized.append(value)
    points = tuple(normalized)
    cumulative = [0.0]
    for first, second in zip(points, points[1:], strict=False):
        cumulative.append(
            cumulative[-1] + math.sqrt(sum((second[i] - first[i]) ** 2 for i in range(3)))
        )
    return points, tuple(cumulative), cumulative[-1] if cumulative else 0.0


def _sample_polyline_metrics(points, cumulative, total, factor):
    if not points:
        return (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0
    if len(points) == 1 or total <= 1.0e-12:
        return points[0], (1.0, 0.0, 0.0), 0.0
    distance = clamp(float(factor), 0.0, 1.0) * total
    index = max(0, min(len(points) - 2, bisect_left(cumulative, distance, lo=1) - 1))
    first = points[index]
    second = points[index + 1]
    segment_start = cumulative[index]
    segment_length = max(cumulative[index + 1] - segment_start, 1.0e-12)
    local = clamp((distance - segment_start) / segment_length, 0.0, 1.0)
    point = tuple(first[i] + (second[i] - first[i]) * local for i in range(3))
    tangent = tuple((second[i] - first[i]) / segment_length for i in range(3))
    return point, tangent, total


def _path_extend_count(item):
    """Return the visible Follow Curve repeat count."""
    try:
        extend = int(getattr(item, "path_extend", 1) or 1)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        extend = 1
    return max(1, min(500, extend))


def _path_local_frame(item, frame):
    local_frame = float(frame) - float(_motion_start_frame(item))
    loop_duration = int(getattr(item, "loop_duration", 0) or 0)
    if loop_duration > 0:
        local_frame %= float(loop_duration)
    step = max(1, int(getattr(item, "step_frames", 1) or 1))
    if step > 1:
        local_frame = math.floor(local_frame / step) * step
    return local_frame


def _path_raw_progress(item, frame):
    duration = max(1, int(getattr(item, "path_duration", 100) or 100))
    speed = float(getattr(item, "speed", 1.0) or 0.0)
    raw = _path_local_frame(item, frame) / float(duration)
    raw *= abs(speed) if abs(speed) > 1.0e-12 else 0.0
    return raw, speed


def _path_factor_from_raw(item, raw, speed):
    mode = str(getattr(item, "path_mode", "FORWARD") or "FORWARD")
    extend = float(_path_extend_count(item))
    travel = float(raw) / max(1.0, extend)
    loop = bool(getattr(item, "path_loop", True))
    if mode == "PING_PONG":
        if loop:
            wrapped = travel % 2.0
            factor = wrapped if wrapped <= 1.0 else 2.0 - wrapped
        else:
            clamped = clamp(travel, 0.0, 2.0)
            factor = clamped if clamped <= 1.0 else 2.0 - clamped
    else:
        factor = (travel % 1.0) if loop else clamp(travel, 0.0, 1.0)
        if mode == "REVERSE":
            factor = 1.0 - factor
    if float(speed) < 0.0:
        factor = 1.0 - factor
    return clamp(factor, 0.0, 1.0)


def _curve_polyline_points(path_object, resolution=12, *, world_space=True):
    if path_object is None or str(getattr(path_object, "type", "")) != "CURVE":
        return ()
    data = getattr(path_object, "data", None)
    splines = tuple(getattr(data, "splines", ()) or ())
    if not splines:
        return ()
    transform = getattr(path_object, "matrix_world", None) if world_space else None
    try:
        from mathutils import Vector
    except (ImportError, AttributeError):
        Vector = None
    try:
        from mathutils.geometry import interpolate_bezier
    except (ImportError, AttributeError):
        interpolate_bezier = None
    points = []
    for spline in splines:
        spline_type = str(getattr(spline, "type", ""))
        segment_points = []
        if spline_type == "BEZIER":
            bezier_points = tuple(getattr(spline, "bezier_points", ()) or ())
            if len(bezier_points) >= 2:
                try:
                    if interpolate_bezier is None:
                        raise ImportError("mathutils.geometry.interpolate_bezier is unavailable")
                    pairs = list(zip(bezier_points, bezier_points[1:], strict=False))
                    if bool(getattr(spline, "use_cyclic_u", False)):
                        pairs.append((bezier_points[-1], bezier_points[0]))
                    steps = max(2, int(resolution or 12))
                    for pair_index, (first, second) in enumerate(pairs):
                        sampled = tuple(interpolate_bezier(
                            first.co, first.handle_right, second.handle_left, second.co, steps + 1,
                        ))
                        if pair_index:
                            sampled = sampled[1:]
                        segment_points.extend(sampled)
                except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    segment_points = [point.co for point in bezier_points]
        else:
            for point in tuple(getattr(spline, "points", ()) or ()):
                coordinate = getattr(point, "co", (0.0, 0.0, 0.0, 1.0))
                segment_points.append(tuple(coordinate[:3]))
            if bool(getattr(spline, "use_cyclic_u", False)) and segment_points:
                segment_points.append(segment_points[0])
        for coordinate in segment_points:
            try:
                if transform is not None and Vector is not None:
                    transformed = transform @ Vector(tuple(coordinate[:3]))
                    value = tuple(float(component) for component in transformed[:3])
                else:
                    value = tuple(float(component) for component in coordinate[:3])
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                value = tuple(float(component) for component in coordinate[:3])
            if not points or any(abs(value[i] - points[-1][i]) > 1.0e-10 for i in range(3)):
                points.append(value)
        if points:
            break
    return tuple(points)


def _rounded_vector(value, digits=6):
    try:
        return tuple(round(float(component), digits) for component in value[:3])
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return (0.0, 0.0, 0.0)


def _rounded_matrix(matrix, digits=6):
    try:
        return tuple(round(float(component), digits) for row in matrix for component in row)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ()


def _curve_cache_signature(path_object, resolution=12, *, world_space=True):
    if path_object is None or str(getattr(path_object, "type", "")) != "CURVE":
        return None
    try:
        data = getattr(path_object, "data", None)
        splines = tuple(getattr(data, "splines", ()) or ())
        if not splines:
            return None
        spline_signature = []
        for spline in splines:
            spline_type = str(getattr(spline, "type", ""))
            cyclic = bool(getattr(spline, "use_cyclic_u", False))
            if spline_type == "BEZIER":
                coordinates = tuple(
                    (
                        _rounded_vector(point.co),
                        _rounded_vector(point.handle_left),
                        _rounded_vector(point.handle_right),
                        str(getattr(point, "handle_left_type", "")),
                        str(getattr(point, "handle_right_type", "")),
                    )
                    for point in tuple(getattr(spline, "bezier_points", ()) or ())
                )
            else:
                coordinates = tuple(
                    _rounded_vector(getattr(point, "co", (0.0, 0.0, 0.0, 1.0)))
                    for point in tuple(getattr(spline, "points", ()) or ())
                )
            spline_signature.append((spline_type, cyclic, coordinates))
        matrix_signature = _rounded_matrix(getattr(path_object, "matrix_world", ())) if world_space else ()
        return (
            fbp_obj_runtime_key(path_object),
            fbp_obj_runtime_key(data),
            int(max(2, resolution or 12)),
            bool(world_space),
            matrix_signature,
            tuple(spline_signature),
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _curve_polyline_metrics_cached(path_object, resolution=12, *, world_space=True):
    signature = _curve_cache_signature(path_object, resolution, world_space=world_space)
    if signature is None:
        return (), (), 0.0
    cached = _MOTION_PATH_CACHE.get(signature)
    if cached is not None:
        return cached
    metrics = _polyline_metrics(_curve_polyline_points(path_object, resolution, world_space=world_space))
    if len(_MOTION_PATH_CACHE) >= _MOTION_PATH_CACHE_LIMIT:
        _MOTION_PATH_CACHE.clear()
    _MOTION_PATH_CACHE[signature] = metrics
    return metrics


def _neutral_motion_values():
    return {"location": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0), "scale": (0.0, 0.0, 0.0)}


def _evaluate_path_motion_item(item, target, frame, fps):
    del target, fps
    if item is None or not bool(getattr(item, "enabled", True)):
        return _neutral_motion_values()
    if not _motion_frame_is_active(item, frame):
        return _neutral_motion_values()
    amount = float(getattr(item, "amount", 1.0) or 0.0) * clamp(
        float(getattr(item, "influence", 1.0) or 0.0), 0.0, 1.0,
    )
    if abs(amount) <= 1.0e-12:
        return _neutral_motion_values()
    path_object = getattr(item, "path_object", None)
    world_space = str(getattr(item, "space", "WORLD") or "WORLD") == "WORLD"
    resolution = int(getattr(item, "path_resolution", 12) or 12)
    points, cumulative, total = _curve_polyline_metrics_cached(path_object, resolution, world_space=world_space)
    if len(points) < 2 or total <= 1.0e-12:
        return _neutral_motion_values()
    raw, speed = _path_raw_progress(item, frame)
    factor = _path_factor_from_raw(item, raw, speed)
    point, tangent, _length = _sample_polyline_metrics(points, cumulative, total, factor)
    origin = points[0]
    start_tangent = _sample_polyline_metrics(points, cumulative, total, 0.0)[1]
    mask = _motion_axis_mask(item)
    location = tuple((point[i] - origin[i]) * amount * mask[i] for i in range(3))
    rotation = [0.0, 0.0, 0.0]
    if bool(getattr(item, "path_follow_rotation", False)):
        try:
            from mathutils import Vector
            start_quat = Vector(start_tangent).to_track_quat("Y", "Z")
            current_quat = Vector(tangent).to_track_quat("Y", "Z")
            delta = (start_quat.inverted() @ current_quat).to_euler("XYZ")
            rotation = [float(delta[i]) * amount for i in range(3)]
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            rotation[2] = (
                math.atan2(tangent[1], tangent[0]) - math.atan2(start_tangent[1], start_tangent[0])
            ) * amount
        bank = float(getattr(item, "path_bank_strength", 0.0) or 0.0)
        if abs(bank) > 1.0e-12:
            before = _sample_polyline_metrics(points, cumulative, total, max(0.0, factor - 0.01))[1]
            after = _sample_polyline_metrics(points, cumulative, total, min(1.0, factor + 0.01))[1]
            turn = before[0] * after[1] - before[1] * after[0]
            rotation[1] += turn * bank * amount
    return {"location": location, "rotation": tuple(rotation), "scale": (0.0, 0.0, 0.0)}


def _sample_motion_delta(target, frame):
    """Sample native delta-transform fcurves without changing the Scene frame."""
    current = _actual_motion_delta(target)
    values = {
        "delta_location": [float(value) for value in current["location"]],
        "delta_rotation_euler": [float(value) for value in current["rotation"]],
        "delta_scale": [float(value) for value in current["scale_factor"]],
    }
    found = False
    for fcurve in _target_action_fcurves(target):
        data_path = str(getattr(fcurve, "data_path", ""))
        if data_path not in values:
            continue
        try:
            index = int(getattr(fcurve, "array_index", 0) or 0)
            if 0 <= index < 3:
                values[data_path][index] = float(fcurve.evaluate(float(frame)))
                found = True
        except FBP_DATA_ERRORS:
            continue
    if not found:
        return current
    try:
        base_location = tuple(float(value) for value in target.fbp_motion_base_location)
        base_rotation = tuple(float(value) for value in target.fbp_motion_base_rotation)
        base_scale = tuple(float(value) for value in target.fbp_motion_base_scale)
    except FBP_DATA_ERRORS:
        base_location = (0.0, 0.0, 0.0)
        base_rotation = (0.0, 0.0, 0.0)
        base_scale = (1.0, 1.0, 1.0)
    return {
        "location": tuple(values["delta_location"][i] - base_location[i] for i in range(3)),
        "rotation": tuple(values["delta_rotation_euler"][i] - base_rotation[i] for i in range(3)),
        "scale_factor": tuple(values["delta_scale"][i] / max(1.0e-8, base_scale[i]) for i in range(3)),
    }


def _sample_helper_transform_delta(target, frame):
    """Sample a generated helper's object transform relative to its stored neutral pose."""
    if target is None:
        return {"location": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0), "scale_factor": (1.0, 1.0, 1.0)}
    try:
        current_location = [float(value) for value in getattr(target, "location", (0.0, 0.0, 0.0))]
        current_rotation = [float(value) for value in getattr(target, "rotation_euler", (0.0, 0.0, 0.0))]
        current_scale = [float(value) for value in getattr(target, "scale", (1.0, 1.0, 1.0))]
        values = {
            "location": current_location[:],
            "rotation_euler": current_rotation[:],
            "scale": current_scale[:],
        }
        for fcurve in _target_action_fcurves(target):
            data_path = str(getattr(fcurve, "data_path", ""))
            if data_path not in values:
                continue
            try:
                index = int(getattr(fcurve, "array_index", 0) or 0)
                if 0 <= index < 3:
                    values[data_path][index] = float(fcurve.evaluate(float(frame)))
            except FBP_DATA_ERRORS:
                continue
        base_location = tuple(float(value) for value in target.get("fbp_motion_helper_base_location", current_location))
        base_rotation = tuple(float(value) for value in target.get("fbp_motion_helper_base_rotation", current_rotation))
        base_scale = tuple(float(value) for value in target.get("fbp_motion_helper_base_scale", current_scale))
        return {
            "location": tuple(float(values["location"][i]) - base_location[i] for i in range(3)),
            "rotation": tuple(float(values["rotation_euler"][i]) - base_rotation[i] for i in range(3)),
            "scale_factor": tuple(float(values["scale"][i]) / max(1.0e-8, base_scale[i]) for i in range(3)),
        }
    except FBP_DATA_ERRORS:
        return {"location": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0), "scale_factor": (1.0, 1.0, 1.0)}


def _actual_motion_delta(target):
    try:
        if bool(getattr(target, "fbp_motion_base_captured", False)):
            location = tuple(float(target.delta_location[i]) - float(target.fbp_motion_base_location[i]) for i in range(3))
            rotation = tuple(float(target.delta_rotation_euler[i]) - float(target.fbp_motion_base_rotation[i]) for i in range(3))
            scale = tuple(
                (float(target.delta_scale[i]) / max(1.0e-8, float(target.fbp_motion_base_scale[i]))) - 1.0
                for i in range(3)
            )
            return {"location": location, "rotation": rotation, "scale_factor": tuple(1.0 + value for value in scale)}
    except FBP_DATA_ERRORS:
        pass
    return {"location": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0), "scale_factor": (1.0, 1.0, 1.0)}


def _evaluate_spring_motion_item(item, target, frame, fps, visited):
    if item is None or not bool(getattr(item, "enabled", True)):
        return _neutral_motion_values()
    if not _motion_frame_is_active(item, frame):
        return _neutral_motion_values()
    source = getattr(item, "spring_target", None)
    if source is None or _same_rna(source, target):
        return _neutral_motion_values()
    pointer = fbp_obj_runtime_key(source)
    if pointer in visited:
        return _neutral_motion_values()
    delay = max(0, int(getattr(item, "spring_delay", 4) or 0))
    spring_speed = abs(float(getattr(item, "speed", 1.0) or 0.0))
    base_frame = float(_motion_start_frame(item))
    sampled_frame = base_frame + (float(frame) - base_frame) * spring_speed
    delayed_frame = sampled_frame - float(delay)
    source_enabled = bool(getattr(source, "fbp_motion_master_enabled", True))
    if _is_generated_motion_helper(source):
        source_values = _sample_helper_transform_delta(source, delayed_frame)
        previous_values = _sample_helper_transform_delta(source, delayed_frame - max(1.0e-6, spring_speed))
    elif _target_has_motion(source) and source_enabled:
        source_values = _evaluate_motion_stack(source, delayed_frame, fps, visited)
        previous_values = _evaluate_motion_stack(source, delayed_frame - max(1.0e-6, spring_speed), fps, visited)
    else:
        source_values = _sample_motion_delta(source, delayed_frame)
        previous_values = _sample_motion_delta(source, delayed_frame - max(1.0e-6, spring_speed))
    damping = max(0.0, float(getattr(item, "spring_damping", 0.65) or 0.0))
    stiffness = max(0.001, float(getattr(item, "spring_stiffness", 5.0) or 0.001))
    overshoot = max(0.0, float(getattr(item, "spring_overshoot", 0.2) or 0.0))
    response = clamp(stiffness / (stiffness + damping * 6.0), 0.0, 1.0)
    velocity_gain = overshoot * math.exp(-damping * max(0.0, delay / max(1.0, fps)))
    amount = float(getattr(item, "amount", 1.0) or 0.0) * clamp(
        float(getattr(item, "influence", 1.0) or 0.0), 0.0, 1.0,
    )
    mask = _motion_axis_mask(item)
    location = [0.0, 0.0, 0.0]
    rotation = [0.0, 0.0, 0.0]
    scale = [0.0, 0.0, 0.0]
    for index in range(3):
        if bool(getattr(item, "spring_follow_location", True)):
            velocity = source_values["location"][index] - previous_values["location"][index]
            location[index] = (source_values["location"][index] * response + velocity * velocity_gain) * amount * mask[index]
        if bool(getattr(item, "spring_follow_rotation", True)):
            velocity = source_values["rotation"][index] - previous_values["rotation"][index]
            rotation[index] = (source_values["rotation"][index] * response + velocity * velocity_gain) * amount * mask[index]
        if bool(getattr(item, "spring_follow_scale", False)):
            source_scale = source_values["scale_factor"][index] - 1.0
            previous_scale = previous_values["scale_factor"][index] - 1.0
            scale[index] = (source_scale * response + (source_scale - previous_scale) * velocity_gain) * amount
    return {"location": tuple(location), "rotation": tuple(rotation), "scale": tuple(scale)}


def _evaluate_motion_stack(target, frame, fps=24.0, visited=None, items=None):
    visited = set(visited or ())
    pointer = fbp_obj_runtime_key(target)
    if pointer in visited:
        return {"location": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0), "scale_factor": (1.0, 1.0, 1.0)}
    visited.add(pointer)
    if items is None:
        try:
            items = tuple(target.fbp_motions)
        except FBP_DATA_ERRORS:
            items = ()
    location = [0.0, 0.0, 0.0]
    rotation = [0.0, 0.0, 0.0]
    scale_factor = [1.0, 1.0, 1.0]
    for item in tuple(items or ()):
        preset = str(getattr(item, "preset", "FLOATING") or "FLOATING")
        if preset in {"FOLLOW_PATH", "FOLLOW_SPIRAL"}:
            values = _evaluate_path_motion_item(item, target, frame, fps)
        elif preset == "SPRING_FOLLOW":
            values = _evaluate_spring_motion_item(item, target, frame, fps, visited)
        else:
            values = evaluate_motion_item(item, frame, fps)
        for index in range(3):
            location[index] += values["location"][index]
            rotation[index] += values["rotation"][index]
            scale_factor[index] *= max(0.01, 1.0 + values["scale"][index])
    return {"location": tuple(location), "rotation": tuple(rotation), "scale_factor": tuple(scale_factor)}


def _motion_scene_cache_key(scene):
    try:
        if scene is None:
            return (0, "")
        return (
            fbp_obj_runtime_key(scene),
            str(getattr(scene, "name_full", getattr(scene, "name", "")) or ""),
        )
    except FBP_DATA_ERRORS:
        return (0, "")


def _clear_motion_target_cache(scene=None):
    global _MOTION_HELPER_SELECTION_SIGNATURE
    # Target structure and helper ownership can change without changing the
    # active selection. Force one visibility pass after every target-cache
    # invalidation so newly created/removed helpers cannot inherit stale state.
    _MOTION_HELPER_SELECTION_SIGNATURE = None
    if scene is None:
        _MOTION_TARGET_CACHE.clear()
        return
    key = _motion_scene_cache_key(scene)
    if key and key[0]:
        _MOTION_TARGET_CACHE.pop(key, None)


def _iter_scene_motion_targets(scene=None):
    """Return only objects with Motion, cached for the frame-change hot path.

    The previous implementation materialized every Scene object before it could
    even consult the cache. Frame changes now read the collection length first,
    resolve cached target names directly, and scan the Scene only after the
    bounded cache expires or the object structure changes.
    """
    scene = scene or getattr(bpy.context, "scene", None)
    try:
        source = scene.objects if scene is not None else bpy.data.objects
        object_count = len(source)
    except FBP_DATA_ERRORS:
        return ()
    key = _motion_scene_cache_key(scene) if scene is not None else (0, "")
    now = time.monotonic()
    cached = _MOTION_TARGET_CACHE.get(key) if key and key[0] else None
    if cached is not None:
        try:
            if (
                int(cached.get("object_count", -1)) == object_count
                and now - float(cached.get("checked_at", 0.0) or 0.0) <= _MOTION_TARGET_CACHE_SECONDS
            ):
                names = tuple(cached.get("target_names", ()) or ())
                resolved = tuple(
                    obj for name in names
                    for obj in (source.get(str(name)),)
                    if obj is not None and _target_has_motion(obj)
                )
                if len(resolved) == len(names):
                    return resolved
        except FBP_DATA_ERRORS:
            pass
    try:
        targets = tuple(obj for obj in source if _target_has_motion(obj))
    except FBP_DATA_ERRORS:
        targets = ()
    if key and key[0]:
        if len(_MOTION_TARGET_CACHE) >= 32 and key not in _MOTION_TARGET_CACHE:
            _prune_motion_target_cache(now)
        _MOTION_TARGET_CACHE[key] = {
            "object_count": object_count,
            "checked_at": now,
            "target_names": tuple(str(getattr(obj, "name", "") or "") for obj in targets),
        }
    return targets


def _same_rna(left, right):
    if left is right:
        return True
    left_key = fbp_rna_runtime_key(left)
    return left_key is not None and left_key == fbp_rna_runtime_key(right)


def _linked_motion_items(link_id, scene=None):
    link_id = str(link_id or "")
    if not link_id:
        return ()
    found = []
    for target in _iter_scene_motion_targets(scene):
        try:
            found.extend(
                (target, item)
                for item in tuple(target.fbp_motions)
                if str(getattr(item, "link_id", "") or "") == link_id
            )
        except FBP_DATA_ERRORS:
            continue
    return tuple(found)


def _motion_values_equal(left, right):
    try:
        if isinstance(left, str) or isinstance(right, str):
            return str(left) == str(right)
        left_values = tuple(left)
        right_values = tuple(right)
        return len(left_values) == len(right_values) and all(
            abs(float(a) - float(b)) <= 1.0e-8 for a, b in zip(left_values, right_values, strict=False)
        )
    except (TypeError, ValueError):
        try:
            return abs(float(left) - float(right)) <= 1.0e-8
        except (TypeError, ValueError):
            return left == right


def _copy_motion_values(source, destination, *, include_local=True, include_seed=False):
    properties = list(_SHARED_MOTION_PROPERTIES)
    if include_local:
        properties.extend(("enabled", "influence", "phase"))
    if include_seed:
        properties.append("seed")
    global _MOTION_LINK_GUARD
    previous_guard = _MOTION_LINK_GUARD
    _MOTION_LINK_GUARD = True
    try:
        for identifier in properties:
            try:
                setattr(destination, identifier, getattr(source, identifier))
            except FBP_DATA_ERRORS:
                continue
        destination.share_seed = bool(getattr(source, "share_seed", False))
    finally:
        _MOTION_LINK_GUARD = previous_guard
    return destination


def _propagate_linked_motion(source, scene=None):
    global _MOTION_LINK_GUARD
    if _MOTION_LINK_GUARD:
        return 0
    link_id = str(getattr(source, "link_id", "") or "")
    if not link_id:
        return 0
    changed = 0
    include_seed = bool(getattr(source, "share_seed", False))
    for target, item in _linked_motion_items(link_id, scene):
        if _same_rna(item, source):
            continue
        _copy_motion_values(source, item, include_local=False, include_seed=include_seed)
        evaluate_motion_target(target, scene)
        changed += 1
    return changed


def _selected_motion_targets(context):
    targets = []
    seen = set()
    candidates = list(getattr(context, "selected_objects", ()) or ())
    active = getattr(context, "object", None)
    if active is not None and active not in candidates:
        candidates.insert(0, active)
    for candidate in candidates:
        target = None
        try:
            if str(getattr(candidate, "type", "")) == "CAMERA":
                target = candidate
            else:
                from .layers import fbp_resolve_rig_from_any_object
                target = fbp_resolve_rig_from_any_object(candidate, context)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            target = None
        if target is None:
            continue
        pointer = fbp_obj_runtime_key(target)
        if pointer is None or pointer in seen:
            continue
        seen.add(pointer)
        targets.append(target)
    return tuple(targets)


def _sort_motion_targets(targets):
    def key(target):
        is_camera = str(getattr(target, "type", "")) == "CAMERA"
        return (1 if is_camera else 0, int(getattr(target, "fbp_depth_order", 0) or 0), str(getattr(target, "name", "")))
    return tuple(sorted(targets or (), key=key))


def _active_motion_item(target):
    if target is None or not _target_has_motion(target):
        return None
    try:
        index = int(clamp(target.fbp_motion_active_index, 0, len(target.fbp_motions) - 1))
        return target.fbp_motions[index]
    except FBP_DATA_ERRORS:
        return None


def _find_linked_item(target, link_id):
    if target is None or not link_id:
        return None
    try:
        for item in tuple(target.fbp_motions):
            if str(getattr(item, "link_id", "") or "") == str(link_id):
                return item
    except FBP_DATA_ERRORS:
        return None
    return None


def _stable_target_seed(target, source_seed=0, index=0):
    name = str(getattr(target, "name", ""))
    total = sum((position + 1) * ord(character) for position, character in enumerate(name))
    return int((int(source_seed) * 1664525 + total + int(index) * 1013904223) % 1000000)


def _ensure_linked_motion(target, source, link_id, *, share_seed=False, index=0):
    item = _find_linked_item(target, link_id)
    if item is None:
        if not _capture_motion_base(target):
            return None
        target["fbp_motion_effect_container"] = True
        item = target.fbp_motions.add()
        item.uid = uuid.uuid4().hex
    _copy_motion_values(source, item, include_local=True, include_seed=share_seed)
    item.link_id = link_id
    item.share_seed = bool(share_seed)
    if not share_seed and not _same_rna(item, source):
        item.seed = _stable_target_seed(target, getattr(source, "seed", 0), index)
    return item


def _motion_target_from_context(context):
    active = getattr(context, "object", None)
    if active is None:
        return None
    try:
        helper_owner = _motion_helper_owner_target(active)
        if helper_owner is not None:
            return helper_owner
        if str(getattr(active, "type", "")) == "CAMERA":
            return active
        from .layers import fbp_resolve_rig_from_any_object
        target = fbp_resolve_rig_from_any_object(active, context)
        return target if target is not None else None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _capture_motion_base(target, *, force=False):
    if target is None:
        return False
    try:
        if bool(target.fbp_motion_base_captured) and not force:
            return True
        target.fbp_motion_base_location = tuple(float(value) for value in target.delta_location)
        target.fbp_motion_base_rotation = tuple(float(value) for value in target.delta_rotation_euler)
        target.fbp_motion_base_scale = tuple(float(value) for value in target.delta_scale)
        target.fbp_motion_base_captured = True
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not capture Motion base transform", exc)
        return False


def _restore_motion_base(target, *, clear=False):
    if target is None:
        return False
    try:
        if not bool(target.fbp_motion_base_captured):
            return False
        target.delta_location = tuple(target.fbp_motion_base_location)
        target.delta_rotation_euler = tuple(target.fbp_motion_base_rotation)
        target.delta_scale = tuple(target.fbp_motion_base_scale)
        if clear:
            target.fbp_motion_base_captured = False
        return True
    except FBP_DATA_ERRORS:
        return False


def _world_to_local_location(target, vector):
    try:
        parent = getattr(target, "parent", None)
        if parent is None:
            return tuple(vector)
        from mathutils import Vector
        converted = parent.matrix_world.to_3x3().inverted_safe() @ Vector(vector)
        return tuple(float(value) for value in converted)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return tuple(vector)


def _object_world_location(obj):
    try:
        return tuple(float(value) for value in obj.matrix_world.translation)
    except FBP_DATA_ERRORS:
        try:
            return tuple(float(value) for value in obj.location)
        except FBP_DATA_ERRORS:
            return (0.0, 0.0, 0.0)


def _object_world_bounds_center(obj):
    """Return the visible world-space center of an object, not just its origin."""
    try:
        from mathutils import Vector
        bounds = tuple(getattr(obj, "bound_box", ()) or ())
        if not bounds:
            return Vector(_object_world_location(obj))
        total = Vector((0.0, 0.0, 0.0))
        for corner in bounds:
            total += obj.matrix_world @ Vector(tuple(corner[:3]))
        return total / float(len(bounds))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        try:
            from mathutils import Vector
            return Vector(_object_world_location(obj))
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return _object_world_location(obj)


def _store_motion_helper_base(helper):
    """Store the helper's current transform as its neutral spring/reference pose."""
    if helper is None:
        return False
    try:
        helper["fbp_motion_helper_base_location"] = tuple(float(value) for value in getattr(helper, "location", (0.0, 0.0, 0.0)))
        helper["fbp_motion_helper_base_rotation"] = tuple(float(value) for value in getattr(helper, "rotation_euler", (0.0, 0.0, 0.0)))
        helper["fbp_motion_helper_base_scale"] = tuple(float(value) for value in getattr(helper, "scale", (1.0, 1.0, 1.0)))
        return True
    except FBP_DATA_ERRORS:
        return False


def _mark_motion_helper(helper, target, item, helper_type):
    try:
        if not str(getattr(item, "uid", "") or ""):
            item.uid = uuid.uuid4().hex
        helper["fbp_motion_helper"] = True
        helper["fbp_motion_helper_type"] = str(helper_type or "")
        helper["fbp_motion_helper_item_uid"] = str(getattr(item, "uid", "") or "")
        helper["fbp_motion_helper_target_name"] = str(getattr(target, "name", "") or "")
        _store_motion_helper_base(helper)
    except FBP_DATA_ERRORS:
        pass
    return helper


def _motion_helper_owner_target(helper):
    try:
        if helper is None or not bool(helper.get("fbp_motion_helper", False)):
            return None
        name = str(helper.get("fbp_motion_helper_target_name", "") or "")
        target = bpy.data.objects.get(name) if name else None
        return target if _target_has_motion(target) else None
    except FBP_DATA_ERRORS:
        return None


def _is_generated_motion_helper(obj, item=None):
    try:
        if obj is None or not bool(obj.get("fbp_motion_helper", False)):
            return False
        if item is None:
            return True
        item_uid = str(getattr(item, "uid", "") or "")
        helper_uid = str(obj.get("fbp_motion_helper_item_uid", "") or "")
        return bool(item_uid and helper_uid and item_uid == helper_uid)
    except FBP_DATA_ERRORS:
        return False


def is_motion_helper(obj):
    """Return True for generated Motion helper objects. Public wrapper used by selection/UI resolution."""
    return _is_generated_motion_helper(obj)


def motion_helper_owner(obj):
    """Return the Motion target represented by a generated helper, if available."""
    return _motion_helper_owner_target(obj)

def _remove_generated_motion_helper(obj, item=None):
    if not _is_generated_motion_helper(obj, item):
        return False
    try:
        data = getattr(obj, "data", None)
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and getattr(data, "users", 0) == 0:
            if str(getattr(data, "__class__", type(data)).__name__) == "Curve":
                bpy.data.curves.remove(data)
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _cleanup_motion_item_helpers(item):
    changed = False
    try:
        changed = _remove_generated_motion_helper(getattr(item, "path_object", None), item) or changed
    except FBP_DATA_ERRORS:
        pass
    try:
        changed = _remove_generated_motion_helper(getattr(item, "spring_target", None), item) or changed
    except FBP_DATA_ERRORS:
        pass
    return changed


def _cleanup_motion_stack_helpers(target):
    changed = False
    try:
        for item in tuple(getattr(target, "fbp_motions", ()) or ()):  # copy before collection edits
            changed = _cleanup_motion_item_helpers(item) or changed
    except FBP_DATA_ERRORS:
        pass
    return changed


def _motion_base_helper_transform(target, context=None):
    """Return a helper transform using the target's pre-Motion delta values."""
    if target is None:
        return None, None
    try:
        from mathutils import Matrix
    except (ImportError, AttributeError):
        return None, None
    scene_update = None
    try:
        scene_update = getattr(getattr(context, "view_layer", None), "update", None)
    except FBP_DATA_ERRORS:
        scene_update = None
    try:
        current_location = tuple(float(value) for value in target.delta_location)
        current_rotation = tuple(float(value) for value in target.delta_rotation_euler)
        current_scale = tuple(float(value) for value in target.delta_scale)
        if bool(getattr(target, "fbp_motion_base_captured", False)):
            target.delta_location = tuple(float(value) for value in target.fbp_motion_base_location)
            target.delta_rotation_euler = tuple(float(value) for value in target.fbp_motion_base_rotation)
            target.delta_scale = tuple(float(value) for value in target.fbp_motion_base_scale)
            if callable(scene_update):
                scene_update()
        center = _object_world_bounds_center(target)
        rotation_matrix = target.matrix_world.to_3x3().normalized().to_4x4()
        return Matrix.Translation(center) @ rotation_matrix, center
    except FBP_DATA_ERRORS:
        return None, None
    finally:
        try:
            target.delta_location = current_location
            target.delta_rotation_euler = current_rotation
            target.delta_scale = current_scale
            if callable(scene_update):
                scene_update()
        except FBP_DATA_ERRORS:
            pass


def _follow_curve_half_size(target):
    try:
        dimensions = tuple(float(value) for value in (getattr(target, "dimensions", (1.0, 1.0, 1.0)) or (1.0, 1.0, 1.0)))
        return max(0.5, max(dimensions[0], dimensions[1], dimensions[2], 0.5) * 0.35)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0.5


def _follow_curve_points(
    shape, half, repeat_count, resolution=24, *, radius_scale=1.0,
    spacing_scale=1.0, spiral_direction="OUTWARD", clockwise=False,
):
    """Return local helper-curve coordinates for generated Follow shapes.

    Open shapes start at the target center.  Spiral exposes geometry controls
    so the same Follow effect can act as a center-out or outside-in spiral.
    """
    shape = str(shape or "BEZIER")
    repeat_count = max(1, min(500, int(repeat_count or 1)))
    resolution = max(8, min(128, int(resolution or 24)))
    radius_scale = max(0.05, float(radius_scale or 1.0))
    spacing_scale = max(0.05, float(spacing_scale or 1.0))
    amplitude = max(0.1, float(half) * 0.5 * radius_scale)

    if shape == "LINE":
        unit = amplitude * 4.0 * spacing_scale
        return [(unit * index, 0.0, 0.0) for index in range(repeat_count + 1)]

    if shape in {"ZIG_ZAG", "BEZIER"}:
        unit = amplitude * 4.0 * spacing_scale
        coords = [(0.0, 0.0, 0.0)]
        for repeat in range(repeat_count):
            offset = unit * repeat
            segment = (
                (offset + amplitude, amplitude, 0.0),
                (offset + unit - amplitude, -amplitude, 0.0),
                (offset + unit, 0.0, 0.0),
            )
            coords.extend(segment)
        return coords

    if shape == "CIRCLE":
        radius = max(0.1, float(half) * 0.5 * radius_scale)
        unit = radius * 2.6 * spacing_scale
        samples = max(32, resolution * 4)
        coords = []
        sign = -1.0 if bool(clockwise) else 1.0
        for repeat in range(repeat_count):
            offset = unit * repeat
            center_x = offset
            center_y = -radius
            for index in range(samples + 1):
                if repeat and index == 0:
                    continue
                angle = (math.pi * 0.5) + sign * (math.tau * index / samples)
                coords.append((
                    center_x + math.cos(angle) * radius,
                    center_y + math.sin(angle) * radius,
                    0.0,
                ))
        return coords

    if shape == "SPIRAL":
        turns = max(1, repeat_count)
        samples = max(32, resolution * 4) * turns
        base_radius = max(0.05, float(half) * 0.25 * radius_scale)
        ring_gap = max(0.02, float(half) * 0.45 * spacing_scale)
        max_radius = base_radius + ring_gap * turns
        inward = str(spiral_direction or "OUTWARD") == "INWARD"
        sign = -1.0 if bool(clockwise) else 1.0
        coords = []
        for index in range(samples + 1):
            factor = index / max(1, samples)
            radius_factor = (1.0 - factor) if inward else factor
            angle = sign * math.tau * turns * factor
            radius = max_radius * radius_factor
            coords.append((math.cos(angle) * radius, math.sin(angle) * radius, 0.0))
        return coords

    return _follow_curve_points(
        "BEZIER", half, repeat_count, resolution,
        radius_scale=radius_scale, spacing_scale=spacing_scale,
    )


def _spring_curve_points(
    half, extend_count, resolution=24, flatten_2d=False, *, vertical=False,
    radius_scale=1.0, spacing_scale=1.0, clockwise=False,
):
    """Return a visible coil used by the Follow Spring helper."""
    extend_count = max(1, min(500, int(extend_count or 1)))
    resolution = max(8, min(96, int(resolution or 24)))
    radius_scale = max(0.05, float(radius_scale or 1.0))
    spacing_scale = max(0.05, float(spacing_scale or 1.0))
    radius = max(0.03, float(half) * 0.22 * radius_scale)
    pitch = max(0.04, radius * 2.2 * spacing_scale)
    turns = extend_count
    samples = max(16, resolution) * turns
    sign = -1.0 if bool(clockwise) else 1.0
    coords = []
    for index in range(samples + 1):
        factor = index / max(1, samples)
        angle = sign * math.tau * turns * factor
        travel = pitch * turns * factor
        wave = math.sin(angle) * radius
        depth = 0.0 if bool(flatten_2d) else math.cos(angle) * radius
        if bool(vertical):
            coords.append((wave, travel, depth))
        else:
            coords.append((travel, wave, depth))
    return coords


def _set_bezier_handles_from_neighbors(spline):
    """Use explicit handles so repeated Bezier generated paths join smoothly."""
    points = tuple(getattr(spline, "bezier_points", ()) or ())
    count = len(points)
    if count < 2:
        return
    try:
        from mathutils import Vector
    except (ImportError, AttributeError):
        Vector = None
    for index, point in enumerate(points):
        try:
            point.handle_left_type = "FREE"
            point.handle_right_type = "FREE"
            co = Vector(point.co) if Vector is not None else point.co
            prev_co = Vector(points[index - 1].co) if Vector is not None and index > 0 else None
            next_co = Vector(points[index + 1].co) if Vector is not None and index < count - 1 else None
            if prev_co is None and next_co is not None:
                tangent = next_co - co
            elif next_co is None and prev_co is not None:
                tangent = co - prev_co
            elif prev_co is not None and next_co is not None:
                tangent = next_co - prev_co
            else:
                continue
            if hasattr(tangent, "length") and tangent.length > 1.0e-8:
                tangent.normalize()
                left_len = (co - prev_co).length / 3.0 if prev_co is not None else (next_co - co).length / 3.0
                right_len = (next_co - co).length / 3.0 if next_co is not None else (co - prev_co).length / 3.0
                point.handle_left = co - tangent * left_len
                point.handle_right = co + tangent * right_len
            else:
                point.handle_left_type = "AUTO"
                point.handle_right_type = "AUTO"
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            try:
                point.handle_left_type = "AUTO"
                point.handle_right_type = "AUTO"
            except FBP_DATA_ERRORS:
                pass


def _rebuild_follow_curve_data(
    curve, shape, half, repeat_count, resolution=24, *, radius_scale=1.0,
    spacing_scale=1.0, spiral_direction="OUTWARD", clockwise=False,
):
    if curve is None:
        return False
    shape = str(shape or "BEZIER")
    repeat_count = max(1, min(500, int(repeat_count or 1)))
    resolution = max(8, min(128, int(resolution or 24)))
    try:
        while len(curve.splines):
            curve.splines.remove(curve.splines[0])
        curve.dimensions = "3D"
        curve.resolution_u = max(4, min(32, resolution))
        coords = _follow_curve_points(
            shape, half, repeat_count, resolution,
            radius_scale=radius_scale,
            spacing_scale=spacing_scale,
            spiral_direction=spiral_direction,
            clockwise=clockwise,
        )
        if len(coords) < 2:
            return False
        if shape in {"LINE", "ZIG_ZAG", "CIRCLE", "SPIRAL"}:
            spline = curve.splines.new("POLY")
            spline.points.add(len(coords) - 1)
            for point, co in zip(spline.points, coords, strict=False):
                point.co = (float(co[0]), float(co[1]), float(co[2]), 1.0)
            spline.use_cyclic_u = bool(shape == "CIRCLE" and repeat_count == 1)
        else:
            spline = curve.splines.new("BEZIER")
            spline.bezier_points.add(len(coords) - 1)
            for point, co in zip(spline.bezier_points, coords, strict=False):
                point.co = co
            _set_bezier_handles_from_neighbors(spline)
            spline.use_cyclic_u = False
        return True
    except FBP_DATA_ERRORS:
        return False


def _rebuild_spring_curve_data(
    curve, half, extend_count, resolution=24, flatten_2d=False, *, vertical=False,
    radius_scale=1.0, spacing_scale=1.0, clockwise=False,
):
    if curve is None:
        return False
    try:
        while len(curve.splines):
            curve.splines.remove(curve.splines[0])
        curve.dimensions = "3D"
        curve.resolution_u = max(4, min(32, int(resolution or 24)))
        coords = _spring_curve_points(
            half, extend_count, resolution, flatten_2d,
            vertical=vertical,
            radius_scale=radius_scale,
            spacing_scale=spacing_scale,
            clockwise=clockwise,
        )
        if len(coords) < 2:
            return False
        spline = curve.splines.new("POLY")
        spline.points.add(len(coords) - 1)
        for point, co in zip(spline.points, coords, strict=False):
            point.co = (float(co[0]), float(co[1]), float(co[2]), 1.0)
        return True
    except FBP_DATA_ERRORS:
        return False


def _refresh_generated_follow_curve(item, target=None):
    try:
        helper = getattr(item, "path_object", None)
    except FBP_DATA_ERRORS:
        return False
    if not _is_generated_motion_helper(helper, item):
        return False
    data = getattr(helper, "data", None)
    if data is None:
        return False
    if target is None:
        target = getattr(item, "id_data", None)
    half = _follow_curve_half_size(target)
    changed = _rebuild_follow_curve_data(
        data,
        getattr(item, "path_shape", "BEZIER"),
        half,
        _path_extend_count(item),
        getattr(item, "path_resolution", 24),
        radius_scale=getattr(item, "path_radius", 1.0),
        spacing_scale=getattr(item, "path_spacing", 1.0),
        spiral_direction=getattr(item, "path_spiral_direction", "OUTWARD"),
        clockwise=bool(getattr(item, "path_clockwise", False)),
    )
    if changed:
        _clear_motion_path_cache()
    return changed


def _refresh_generated_spring_curve(item, target=None):
    try:
        helper = getattr(item, "path_object", None)
    except FBP_DATA_ERRORS:
        return False
    if not _is_generated_motion_helper(helper, item):
        return False
    data = getattr(helper, "data", None)
    if data is None:
        return False
    if target is None:
        target = getattr(item, "id_data", None)
    half = _follow_curve_half_size(target)
    extend_count = _path_extend_count(item)
    resolution = getattr(item, "path_resolution", 24)
    changed = _rebuild_spring_curve_data(
        data,
        half,
        extend_count,
        resolution,
        bool(getattr(item, "spring_flatten_2d", False)),
        vertical=bool(getattr(item, "spring_vertical", False)),
        radius_scale=getattr(item, "path_radius", 1.0),
        spacing_scale=getattr(item, "path_spacing", 1.0),
        clockwise=bool(getattr(item, "path_clockwise", False)),
    )
    try:
        target_empty = getattr(item, "spring_target", None)
        if _is_generated_motion_helper(target_empty, item):
            try:
                from mathutils import Vector
            except (ImportError, AttributeError):
                Vector = None
            coords = _spring_curve_points(
                    half, extend_count, resolution, bool(getattr(item, "spring_flatten_2d", False)),
                    vertical=bool(getattr(item, "spring_vertical", False)),
                    radius_scale=getattr(item, "path_radius", 1.0),
                    spacing_scale=getattr(item, "path_spacing", 1.0),
                    clockwise=bool(getattr(item, "path_clockwise", False)),
                )
            if coords:
                end_local = coords[-1]
                if Vector is not None:
                    target_empty.location = helper.matrix_world @ Vector(end_local)
                else:
                    target_empty.location = (
                        float(getattr(helper, "location", (0.0, 0.0, 0.0))[0]) + end_local[0],
                        float(getattr(helper, "location", (0.0, 0.0, 0.0))[1]) + end_local[1],
                        float(getattr(helper, "location", (0.0, 0.0, 0.0))[2]) + end_local[2],
                    )
                _store_motion_helper_base(target_empty)
                changed = True
    except FBP_DATA_ERRORS:
        pass
    if changed:
        _clear_motion_path_cache()
    return changed


def _motion_update_blocked(owner=None):
    return bool(
        _MOTION_UPDATE_GUARD
        or _MOTION_LINK_GUARD
        or fbp_undo_guard_active()
        or fbp_render_mutation_blocked()
        or (owner is not None and fbp_is_silent_property_update(owner))
    )



def _motion_follow_curve_update(self, context):
    if _motion_update_blocked(self):
        return
    target = getattr(self, "id_data", None)
    if str(getattr(self, "preset", "") or "") == "SPRING_FOLLOW":
        _refresh_generated_spring_curve(self, target)
    else:
        _refresh_generated_follow_curve(self, target)
    _motion_property_update(self, context)


def _sync_generated_follow_helper_for_preset(item, target=None, context=None):
    """Rebuild an existing generated Follow helper when switching Follow presets.

    This keeps the same visible helper object but changes its generated geometry:
    Follow Curve/Spiral become path shapes, Follow Spring becomes a coil.
    """
    if item is None:
        return False
    preset = str(getattr(item, "preset", "") or "")
    helper = getattr(item, "path_object", None)
    if not _is_generated_motion_helper(helper, item):
        return False
    if target is None:
        target = getattr(item, "id_data", None)
    changed = False
    try:
        if preset == "SPRING_FOLLOW":
            _mark_motion_helper(helper, target, item, "SPRING_CURVE")
            changed = _refresh_generated_spring_curve(item, target) or changed
            if not _is_generated_motion_helper(getattr(item, "spring_target", None), item):
                collection = getattr(context, "collection", None) if context is not None else None
                if collection is not None:
                    try:
                        empty = bpy.data.objects.new(f"FBP Spring Target · {target.name}", None)
                        empty.empty_display_type = "ARROWS"
                        empty.empty_display_size = max(0.5, _follow_curve_half_size(target))
                        collection.objects.link(empty)
                        item.spring_target = empty
                        _mark_motion_helper(empty, target, item, "SPRING_TARGET")
                        _refresh_generated_spring_curve(item, target)
                        changed = True
                    except FBP_DATA_ERRORS:
                        pass
        elif preset in {"FOLLOW_PATH", "FOLLOW_SPIRAL"}:
            if preset == "FOLLOW_SPIRAL":
                item.path_shape = "SPIRAL"
            _mark_motion_helper(helper, target, item, "CURVE")
            changed = _refresh_generated_follow_curve(item, target) or changed
            spring_target = getattr(item, "spring_target", None)
            if _is_generated_motion_helper(spring_target, item):
                _remove_generated_motion_helper(spring_target, item)
                item.spring_target = None
                changed = True
    except FBP_DATA_ERRORS:
        return changed
    if changed:
        _clear_motion_path_cache()
    return changed


def _motion_helper_selection_signature(context=None, *, fresh=False):
    """Return the shared primitive selection signature used by hot observers."""
    return fbp_selection_snapshot(context, max_age=0.0 if fresh else 0.05)


def _sync_motion_helper_visibility(context=None, *, force=False):
    """Show generated Motion helpers only while their owning target is selected.

    The depsgraph callback can run many times per viewport refresh. Bail out
    before resolving Motion targets when the scene/selection signature is
    unchanged; creation and explicit repair paths pass ``force=True``.
    """
    global _MOTION_HELPER_VISIBILITY_GUARD, _MOTION_HELPER_SELECTION_SIGNATURE
    if _MOTION_HELPER_VISIBILITY_GUARD:
        return 0
    context = context or getattr(bpy, "context", None)
    signature = _motion_helper_selection_signature(context, fresh=force)
    if not force and signature == _MOTION_HELPER_SELECTION_SIGNATURE:
        return 0
    _MOTION_HELPER_SELECTION_SIGNATURE = signature
    _MOTION_HELPER_VISIBILITY_GUARD = True
    changed = 0
    try:
        scene = getattr(context, "scene", None) if context is not None else None
        selected_pointers = signature[2]
        if signature[1] and signature[1] not in selected_pointers:
            selected_pointers = selected_pointers | {signature[1]}
        for target in _iter_scene_motion_targets(scene):
            try:
                plane = getattr(target, "fbp_plane_target", None) if bool(getattr(target, "is_fbp_control", False)) else None
                if selected_pointers:
                    target_selected = False
                    try:
                        target_selected = fbp_obj_runtime_key(target) in selected_pointers
                        if plane is not None:
                            target_selected = target_selected or fbp_obj_runtime_key(plane) in selected_pointers
                    except FBP_DATA_ERRORS:
                        target_selected = bool(
                            target.select_get()
                            or (plane is not None and plane.select_get())
                        )
                else:
                    target_selected = False
                for item in tuple(getattr(target, "fbp_motions", ()) or ()):  # Motion items own generated helpers
                    for helper in (getattr(item, "path_object", None), getattr(item, "spring_target", None)):
                        if not _is_generated_motion_helper(helper, item):
                            continue
                        helper_selected = False
                        if selected_pointers:
                            try:
                                helper_selected = fbp_obj_runtime_key(helper) in selected_pointers
                            except FBP_DATA_ERRORS:
                                try:
                                    helper_selected = bool(helper.select_get())
                                except FBP_DATA_ERRORS:
                                    helper_selected = False
                        visible = target_selected or helper_selected
                        hide = not visible
                        if bool(getattr(helper, "hide_viewport", False)) != hide:
                            helper.hide_viewport = hide
                            changed += 1
                        if not bool(getattr(helper, "hide_render", False)):
                            helper.hide_render = True
                            changed += 1
            except FBP_DATA_ERRORS:
                continue
    finally:
        _MOTION_HELPER_VISIBILITY_GUARD = False
    return changed


def _world_location_to_parent_space(target, world_location):
    try:
        parent = getattr(target, "parent", None)
        if parent is None:
            return tuple(world_location)
        from mathutils import Vector
        return tuple(float(value) for value in (parent.matrix_world.inverted_safe() @ Vector(world_location))[:3])
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return tuple(world_location)


def _motion_anchor_parent_location(target, item, base_location, base_rotation, base_scale):
    anchor = str(getattr(item, "anchor_point", "CENTER") or "CENTER").upper()
    if anchor == "CENTER":
        return None
    try:
        from mathutils import Euler, Vector
        bounds = tuple(getattr(target, "bound_box", ()) or ())
        if not bounds:
            return None
        xs = [float(point[0]) for point in bounds]
        ys = [float(point[1]) for point in bounds]
        zs = [float(point[2]) for point in bounds]
        x = (min(xs) + max(xs)) * 0.5
        y = (min(ys) + max(ys)) * 0.5
        z = (min(zs) + max(zs)) * 0.5
        if anchor == "TOP":
            y = max(ys)
        elif anchor == "BOTTOM":
            y = min(ys)
        elif anchor == "LEFT":
            x = min(xs)
        elif anchor == "RIGHT":
            x = max(xs)
        scale_values = tuple(float(getattr(target, "scale", (1.0, 1.0, 1.0))[i]) * float(base_scale[i]) for i in range(3))
        local = Vector((x * scale_values[0], y * scale_values[1], z * scale_values[2]))
        base_euler = tuple(float(getattr(target, "rotation_euler", (0.0, 0.0, 0.0))[i]) + float(base_rotation[i]) for i in range(3))
        rotated = Euler(base_euler, "XYZ").to_matrix() @ local
        origin = Vector(tuple(float(getattr(target, "location", (0.0, 0.0, 0.0))[i]) + float(base_location[i]) for i in range(3)))
        return tuple(float(value) for value in (origin + rotated)[:3])
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _motion_pivot_location_offset(target, item, rotation, base_location, base_rotation=None, base_scale=None):
    base_rotation = tuple(base_rotation or (0.0, 0.0, 0.0))
    base_scale = tuple(base_scale or (1.0, 1.0, 1.0))
    pivot = getattr(item, "pivot_object", None)
    try:
        from mathutils import Euler, Vector
        if pivot is not None:
            pivot_local = Vector(_world_location_to_parent_space(target, _object_world_location(pivot)))
        else:
            anchor_location = _motion_anchor_parent_location(target, item, base_location, base_rotation, base_scale)
            if anchor_location is None:
                return (0.0, 0.0, 0.0)
            pivot_local = Vector(anchor_location)
        base_origin = Vector(tuple(float(getattr(target, "location", (0.0, 0.0, 0.0))[i]) + float(base_location[i]) for i in range(3)))
        offset = base_origin - pivot_local
        rotated = Euler(tuple(float(value) for value in rotation), "XYZ").to_matrix() @ offset
        delta = rotated - offset
        return tuple(float(value) for value in delta[:3])
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return (0.0, 0.0, 0.0)

def _normalize_motion_slot(slot):
    slot = str(slot or "LOCAL").upper()
    return slot if slot in _SLOT_LABELS else "LOCAL"


def _motion_slot_link_id(slot):
    slot = _normalize_motion_slot(slot)
    return "" if slot == "LOCAL" else f"FBP_MOTION_SLOT:{slot}"


def _motion_slot_from_link_id(link_id):
    prefix = "FBP_MOTION_SLOT:"
    link_id = str(link_id or "")
    return _normalize_motion_slot(link_id[len(prefix):]) if link_id.startswith(prefix) else "LOCAL"


def _sync_motion_pivot_orientation(item):
    pivot = getattr(item, "pivot_object", None)
    if pivot is None:
        return False
    axis = _primary_axis_from_motion(item, "Z")
    rotation = {
        "X": (0.0, math.radians(90.0), 0.0),
        "Y": (math.radians(90.0), 0.0, 0.0),
        "Z": (0.0, 0.0, 0.0),
        "ALL": (0.0, 0.0, 0.0),
    }.get(axis, (0.0, 0.0, 0.0))
    try:
        pivot.rotation_mode = "XYZ"
        pivot.rotation_euler = rotation
        return True
    except FBP_DATA_ERRORS:
        return False


def _motion_slot_update(self, context):
    if _motion_update_blocked(self):
        return
    slot = _normalize_motion_slot(getattr(self, "slot", "LOCAL") or "LOCAL")
    old_link_id = str(getattr(self, "link_id", "") or "")
    new_link_id = _motion_slot_link_id(slot)
    if slot == "LOCAL":
        if old_link_id.startswith("FBP_MOTION_SLOT:"):
            self.link_id = ""
            self.share_seed = False
    else:
        self.link_id = new_link_id
        self.share_seed = True
        # Slot is only a shared tag. Do not rename the visible Motion effect.
        _propagate_linked_motion(self, getattr(context, "scene", None))
    target = getattr(self, "id_data", None)
    if target is not None:
        evaluate_motion_target(target, getattr(context, "scene", None))


def _motion_pivot_poll(_self, obj):
    return obj is not None and str(getattr(obj, "type", "")) == "EMPTY"


def evaluate_motion_target(target, scene=None):
    """Apply all enabled Motion instances to one target's delta transforms."""
    global _MOTION_UPDATE_GUARD
    if target is None or _MOTION_UPDATE_GUARD:
        return False
    try:
        items = tuple(target.fbp_motions)
    except FBP_DATA_ERRORS:
        return False

    if not items:
        return _restore_motion_base(target, clear=True)
    if not _capture_motion_base(target):
        return False

    scene = scene or getattr(bpy.context, "scene", None)
    frame = float(getattr(scene, "frame_current", 1) or 1)
    render = getattr(scene, "render", None)
    fps = float(getattr(render, "fps", 24) or 24)
    fps_base = float(getattr(render, "fps_base", 1.0) or 1.0)
    fps = fps / fps_base if fps_base else fps

    if not bool(getattr(target, "fbp_motion_master_enabled", True)):
        # The master toggle restores the base once in its update callback, then
        # leaves delta channels editable while Motion is paused.
        return False

    # Evaluate local and world-space location channels separately. Rotation and
    # scale use delta-transform local space in this Alpha; the UI states this
    # explicitly while retaining the shared data contract for future expansion.
    local_items = [item for item in items if str(getattr(item, "space", "LOCAL")) != "WORLD"]
    world_items = [item for item in items if str(getattr(item, "space", "LOCAL")) == "WORLD"]
    local_values = _evaluate_motion_stack(target, frame, fps, items=local_items)
    world_values = _evaluate_motion_stack(target, frame, fps, items=world_items)
    world_location = _world_to_local_location(target, world_values["location"])

    base_location = tuple(target.fbp_motion_base_location)
    base_rotation = tuple(target.fbp_motion_base_rotation)
    base_scale = tuple(target.fbp_motion_base_scale)
    motion_rotation = tuple(local_values["rotation"][i] + world_values["rotation"][i] for i in range(3))
    pivot_offset = [0.0, 0.0, 0.0]
    for item in items:
        item_rotation = evaluate_motion_item(item, frame, fps)["rotation"] if str(getattr(item, "preset", "FLOATING") or "FLOATING") not in {"FOLLOW_PATH", "FOLLOW_SPIRAL", "SPRING_FOLLOW"} else (0.0, 0.0, 0.0)
        item_offset = _motion_pivot_location_offset(target, item, item_rotation, base_location, base_rotation, base_scale)
        for axis_index in range(3):
            pivot_offset[axis_index] += item_offset[axis_index]
    location = tuple(base_location[i] + local_values["location"][i] + world_location[i] + pivot_offset[i] for i in range(3))
    rotation = tuple(base_rotation[i] + motion_rotation[i] for i in range(3))
    scale_factor = tuple(local_values["scale_factor"][i] * world_values["scale_factor"][i] for i in range(3))
    scale = tuple(max(0.0001, base_scale[i] * scale_factor[i]) for i in range(3))

    try:
        current_location = tuple(float(value) for value in target.delta_location)
        current_rotation = tuple(float(value) for value in target.delta_rotation_euler)
        current_scale = tuple(float(value) for value in target.delta_scale)
        location_changed = any(abs(current_location[i] - location[i]) > 1.0e-10 for i in range(3))
        rotation_changed = any(abs(current_rotation[i] - rotation[i]) > 1.0e-10 for i in range(3))
        scale_changed = any(abs(current_scale[i] - scale[i]) > 1.0e-10 for i in range(3))
        if not (location_changed or rotation_changed or scale_changed):
            return False
        _MOTION_UPDATE_GUARD = True
        if location_changed:
            target.delta_location = location
        if rotation_changed:
            target.delta_rotation_euler = rotation
        if scale_changed:
            target.delta_scale = scale
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not evaluate Motion for {getattr(target, 'name', '<object>')}", exc)
        return False
    finally:
        _MOTION_UPDATE_GUARD = False


def scene_has_runtime_motion(scene=None):
    """Return True when the Scene contains enabled procedural Motion targets.

    Motion still evaluates through delta-transform writes. Render preflight uses
    this fast test to force Blender's interface lock, preventing viewport and
    render dependency graphs from iterating the same Object data concurrently.
    """
    scene = scene or getattr(getattr(bpy, "context", None), "scene", None)
    if scene is None:
        return False
    for target in _iter_scene_motion_targets(scene):
        try:
            if bool(getattr(target, "fbp_motion_master_enabled", True)) and len(
                getattr(target, "fbp_motions", ()) or ()
            ) > 0:
                return True
        except FBP_DATA_ERRORS:
            # Unknown state must choose the conservative managed-render path.
            return True
    return False


def refresh_all_motion(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    changed = 0
    for target in _iter_scene_motion_targets(scene):
        try:
            if not bool(getattr(target, "fbp_motion_master_enabled", True)):
                continue
        except FBP_DATA_ERRORS:
            continue
        if evaluate_motion_target(target, scene):
            changed += 1
    return changed


def _motion_property_update(self, context):
    if _motion_update_blocked(self):
        return
    _clear_motion_path_cache()
    _sync_motion_pivot_orientation(self)
    target = getattr(self, "id_data", None)
    scene = getattr(context, "scene", None)
    if target is not None:
        evaluate_motion_target(target, scene)
    _propagate_linked_motion(self, scene)


def _motion_effect_update(self, context):
    if _motion_update_blocked(self):
        return
    effect = str(getattr(self, "effect", "DRIFT") or "DRIFT")
    preset = str(getattr(self, "preset", "") or "")
    if _motion_effect_for_preset(preset) != effect:
        preset = _motion_default_preset_for_effect(effect)
    apply_motion_preset_defaults(self, preset, rename=True)
    target = getattr(self, "id_data", None)
    if target is not None:
        _sync_generated_follow_helper_for_preset(self, target, context)
        evaluate_motion_target(target, getattr(context, "scene", None))


def _motion_preset_update(self, context):
    global _MOTION_UPDATE_GUARD
    if _motion_update_blocked(self):
        return
    preset = str(getattr(self, "preset", "FLOATING") or "FLOATING")
    effect = _motion_effect_for_preset(preset)
    previous_guard = _MOTION_UPDATE_GUARD
    _MOTION_UPDATE_GUARD = True
    try:
        self.effect = effect
    finally:
        _MOTION_UPDATE_GUARD = previous_guard
    apply_motion_preset_defaults(self, preset, rename=True)
    target = getattr(self, "id_data", None)
    if target is not None:
        evaluate_motion_target(target, getattr(context, "scene", None))


def _motion_axis_bool_update(self, context):
    global _MOTION_UPDATE_GUARD
    if _motion_update_blocked(self):
        return
    previous_guard = _MOTION_UPDATE_GUARD
    _MOTION_UPDATE_GUARD = True
    try:
        self.axis_buttons_initialized = True
    finally:
        _MOTION_UPDATE_GUARD = previous_guard
    _motion_property_update(self, context)


def _motion_master_update(self, context):
    if _motion_update_blocked(self):
        return
    if bool(getattr(self, "fbp_motion_master_enabled", True)):
        evaluate_motion_target(self, getattr(context, "scene", None))
    else:
        _restore_motion_base(self, clear=False)


def _motion_curve_poll(_self, obj):
    return obj is not None and str(getattr(obj, "type", "")) == "CURVE"


def _motion_follow_target_poll(self, obj):
    target = getattr(self, "id_data", None)
    return obj is not None and not _same_rna(obj, target)


class FBP_PG_MotionItem(PropertyGroup):
    uid: StringProperty(description='Uid value used by the current Motion system. Changes are applied only to compatible Frame By Plane data.', name="Motion ID", default="")
    link_id: StringProperty(description='Link Id value used by the current Motion system. Changes are applied only to compatible Frame By Plane data.', name="Shared Motion ID", default="", options={"HIDDEN"})
    share_seed: BoolProperty(
        name="Share Seed",
        description="Use the same deterministic seed on every linked target; timing and influence remain local",
        default=False,
        update=_motion_property_update,
    )
    name: StringProperty(description='Display name stored by Frame By Plane. Renaming keeps internal identifiers and generated links intact.', name="Name", default="Motion", update=_motion_property_update)
    selected: BoolProperty(
        name="Select Motion",
        description="Include this Motion row in multi-row actions",
        default=False,
    )
    # Stored as a string instead of EnumProperty: Blender can reject reloaded
    # PropertyGroup enums when their item set changes during development.
    # The UI still exposes controlled presets; this field stores the Motion family.
    effect: StringProperty(description="Visible Motion effect family. Variants are selected with Effect Preset.", name="Motion Effect", default="DRIFT", update=_motion_effect_update)
    # Stored as a string for the same reason as effect: dynamic EnumProperty
    # item lists are fragile during add-on reloads and same-cycle family changes.
    preset: StringProperty(description="Internal preset for the selected Motion effect.", name="Effect Preset", default="FLOATING", update=_motion_preset_update)
    slot: EnumProperty(name="Slot", description="Assign this Motion to a shared slot. Local keeps it independent; a slot shares settings with other users of the same slot.", items=MOTION_SLOT_ITEMS, default="LOCAL", update=_motion_slot_update)
    enabled: BoolProperty(description='Toggle this option for the current Motion system. Disabled keeps the data available but prevents this behavior from being applied.', name="Enabled", default=True, update=_motion_property_update)
    amount: FloatProperty(description='Amplitude multiplier. Use it to increase travel distance without changing the blend Influence.', name="Strength", default=1.0, soft_min=0.0, soft_max=5.0, precision=3, update=_motion_property_update)
    speed: FloatProperty(name="Speed", description="Cycles per second for looping presets", default=0.35, soft_min=-5.0, soft_max=5.0, precision=3, update=_motion_property_update)
    phase: FloatProperty(description='Starting phase offset for this Motion.', name="Starting Phase", subtype="ANGLE", unit="ROTATION", default=0.0, update=_motion_property_update)
    seed: IntProperty(description='Deterministic random seed. Change it to get a different variation without changing the overall settings.', name="Seed", default=0, min=0, max=999999, update=_motion_property_update, options={"HIDDEN"})
    step_frames: IntProperty(description='Number of timeline frames each Motion pose is held. Set to 1 for smooth motion.', name="Stepped", default=1, min=1, soft_max=24, update=_motion_property_update)
    axis_buttons_initialized: BoolProperty(name="Axis Buttons Initialized", default=False, options={"HIDDEN"})
    axis_x: BoolProperty(name="X", description="Use X axis for this Motion", default=False, update=_motion_axis_bool_update)
    axis_y: BoolProperty(name="Y", description="Use Y axis for this Motion", default=False, update=_motion_axis_bool_update)
    axis_z: BoolProperty(name="Z", description="Use Z axis for this Motion", default=False, update=_motion_axis_bool_update)
    position_axis_x: BoolProperty(name="X", description="Use X axis for position drift", default=True, update=_motion_property_update)
    position_axis_y: BoolProperty(name="Y", description="Use Y axis for position drift", default=True, update=_motion_property_update)
    position_axis_z: BoolProperty(name="Z", description="Use Z axis for position drift", default=True, update=_motion_property_update)
    position_speed: FloatProperty(name="Position Speed", description="Speed of the position drift", default=0.35, soft_min=-5.0, soft_max=5.0, precision=3, update=_motion_property_update)
    position_strength: FloatProperty(name="Position Strength", description="Distance multiplier for the position drift", default=1.0, soft_min=0.0, soft_max=5.0, precision=3, update=_motion_property_update)
    scale_axis_x: BoolProperty(name="X", description="Scale on X axis", default=True, update=_motion_property_update)
    scale_axis_y: BoolProperty(name="Y", description="Scale on Y axis", default=True, update=_motion_property_update)
    scale_axis_z: BoolProperty(name="Z", description="Scale on Z axis", default=False, update=_motion_property_update)
    anchor_point: EnumProperty(name="Anchor Point", description="Virtual pivot used when no Pivot Null is assigned", items=MOTION_ANCHOR_ITEMS, default="CENTER", update=_motion_property_update)
    space: EnumProperty(description='Evaluate the Motion in local or world space.', name="Local / World", items=MOTION_SPACE_ITEMS, default="LOCAL", update=_motion_property_update)
    influence: FloatProperty(description='Blend strength of this Motion. 0 disables its visual contribution; 1 applies the full preset.', name="Influence", subtype="FACTOR", default=1.0, min=0.0, max=1.0, update=_motion_property_update)
    start_frame: IntProperty(description='First timeline frame where this Motion is active.', name="Start", default=0, soft_min=-250, soft_max=2500, update=_motion_property_update)
    end_frame: IntProperty(description='Last timeline frame where this Motion is active. Set to 0 to leave it open-ended.', name="End", default=0, min=0, soft_max=2500, update=_motion_property_update)
    loop_duration: IntProperty(name="Loop Frames", description="Optional exact loop length; zero uses the preset's natural timing", default=0, min=0, soft_max=250, update=_motion_property_update, options={"HIDDEN"})
    location_strength: FloatVectorProperty(description='Vector value for Location Strength. Used for positions, colors or grouped numeric controls in the current Motion system.', name="Position", subtype="TRANSLATION", size=3, default=(0.0, 0.0, 0.1), precision=4, update=_motion_property_update)
    rotation_strength: FloatVectorProperty(description='Rotation angle used by the effect or helper. Example: rotate bands, hatch lines, gradients or directional sampling.', name="Rotation", subtype="EULER", unit="ROTATION", size=3, default=(0.0, 0.0, math.radians(2.0)), update=_motion_property_update)
    scale_strength: FloatProperty(description='Size control for the generated result. Higher values increase visual coverage and may increase viewport cost.', name="Scale", default=0.0, soft_min=-0.5, soft_max=0.5, precision=4, update=_motion_property_update)
    pivot_object: PointerProperty(
        name="Pivot Null", type=bpy.types.Object, poll=_motion_pivot_poll, update=_motion_property_update,
        description="Optional Empty used as the pivot for rotation. Empty means the target origin is used.",
    )
    path_object: PointerProperty(
        name="Curve", type=bpy.types.Object, poll=_motion_curve_poll, update=_motion_property_update,
        description="Curve used by the Follow Curve Motion preset",
    )
    path_duration: IntProperty(description='Number of frames used to travel through one generated curve unit before Extend repeats.', name="Path Frames", default=100, min=1, soft_max=500, update=_motion_property_update)
    path_loop: BoolProperty(description="Repeat the full extended path after it reaches the last generated repeat.", name="Loop Path", default=True, update=_motion_property_update)
    path_extend: IntProperty(description="Visibly duplicate the generated curve forward. 1 is a single curve; 500 is the maximum preview length.", name="Extend", default=1, min=1, max=500, soft_max=24, update=_motion_follow_curve_update)
    path_shape: EnumProperty(name="Curve Type", description="Shape used when generating a Follow Curve helper", items=MOTION_FOLLOW_CURVE_SHAPE_ITEMS, default="BEZIER", update=_motion_follow_curve_update)
    path_mode: EnumProperty(description='Operation mode for this Motion system. Example: choose whether the command adds, removes, previews, repairs or applies settings.', name="Direction", items=MOTION_PATH_MODE_ITEMS, default="FORWARD", update=_motion_property_update)
    path_follow_rotation: BoolProperty(description='Toggle this option for the current Motion system. Disabled keeps the data available but prevents this behavior from being applied.', name="Follow Rotation", default=False, update=_motion_property_update)
    path_bank_strength: FloatProperty(description='Optional roll added while the object follows a curved path.', name="Bank", subtype="ANGLE", unit="ROTATION", default=0.0, soft_min=-math.pi, soft_max=math.pi, update=_motion_property_update)
    path_resolution: IntProperty(description='Sampling quality for generated paths and spring coils. Higher values are smoother but cost more in viewport playback.', name="Path Quality", default=12, min=2, max=64, update=_motion_follow_curve_update)
    path_radius: FloatProperty(name="Radius", description="Generated spiral/spring radius multiplier", default=1.0, min=0.05, soft_max=5.0, precision=3, update=_motion_follow_curve_update)
    path_spacing: FloatProperty(name="Spacing", description="Distance between spring waves or spiral rings", default=1.0, min=0.05, soft_max=5.0, precision=3, update=_motion_follow_curve_update)
    path_spiral_direction: EnumProperty(name="Spiral Direction", description="Choose whether the spiral travels from center to outside or outside to center", items=MOTION_SPIRAL_DIRECTION_ITEMS, default="OUTWARD", update=_motion_follow_curve_update)
    path_clockwise: BoolProperty(name="Clockwise", description="Reverse the generated spiral or spring direction", default=False, update=_motion_follow_curve_update)
    spring_target: PointerProperty(
        name="Follow Target", type=bpy.types.Object, poll=_motion_follow_target_poll, update=_motion_property_update,
        description="Object or generated helper target whose transform drives this spring follow",
    )
    spring_delay: IntProperty(description='Spring Delay value used by the current Motion system. Changes are applied only to compatible Frame By Plane data.', name="Delay", default=4, min=0, soft_max=48, update=_motion_property_update)
    spring_damping: FloatProperty(description='Spring Damping value used by the current Motion system. Changes are applied only to compatible Frame By Plane data.', name="Damping", default=0.65, min=0.0, soft_max=3.0, precision=3, update=_motion_property_update)
    spring_stiffness: FloatProperty(description='Spring Stiffness value used by the current Motion system. Changes are applied only to compatible Frame By Plane data.', name="Stiffness", default=5.0, min=0.001, soft_max=20.0, precision=3, update=_motion_property_update)
    spring_overshoot: FloatProperty(description='Spring Overshoot value used by the current Motion system. Changes are applied only to compatible Frame By Plane data.', name="Overshoot", default=0.2, min=0.0, soft_max=2.0, precision=3, update=_motion_property_update)
    spring_flatten_2d: BoolProperty(name="Flat 2D", description="Flatten the generated spring coil onto a 2D curve so it stays readable on planes", default=True, update=_motion_follow_curve_update)
    spring_vertical: BoolProperty(name="Vertical", description="Rotate the generated spring coil into a vertical 2D orientation", default=False, update=_motion_follow_curve_update)
    spring_follow_location: BoolProperty(description='Toggle this option for the current Motion system. Disabled keeps the data available but prevents this behavior from being applied.', name="Position", default=True, update=_motion_property_update)
    spring_follow_rotation: BoolProperty(description='Toggle this option for the current Motion system. Disabled keeps the data available but prevents this behavior from being applied.', name="Rotation", default=True, update=_motion_property_update)
    spring_follow_scale: BoolProperty(description='Toggle this option for the current Motion system. Disabled keeps the data available but prevents this behavior from being applied.', name="Scale", default=False, update=_motion_property_update)
    show_advanced: BoolProperty(description='Toggle this option for the current Motion system. Disabled keeps the data available but prevents this behavior from being applied.', name="Advanced", default=False)


def apply_motion_preset_defaults(item, preset=None, *, rename=True):
    preset = str(preset or getattr(item, "preset", "FLOATING") or "FLOATING")
    defaults = _PRESET_DEFAULTS.get(preset, _PRESET_DEFAULTS["FLOATING"])
    global _MOTION_UPDATE_GUARD
    previous_guard = _MOTION_UPDATE_GUARD
    _MOTION_UPDATE_GUARD = True
    try:
        # Set the visible Motion family before the preset enum.
        # Blender validates dynamic EnumProperty values against the current
        # item set, so assigning FOLLOW_PATH while the item still belongs to
        # DRIFT raises "enum not found".
        item.effect = _motion_effect_for_preset(preset)
        item.preset = preset
        if rename:
            item.name = _motion_effect_label(item.effect)
        for key, value in defaults.items():
            if key != "axis":
                setattr(item, key, value)
        _set_motion_axis_bools(item, defaults.get("axis", "ALL"))
        if any(key in defaults for key in ("axis_x", "axis_y", "axis_z")):
            item.axis_x = bool(defaults.get("axis_x", item.axis_x))
            item.axis_y = bool(defaults.get("axis_y", item.axis_y))
            item.axis_z = bool(defaults.get("axis_z", item.axis_z))
            item.axis_buttons_initialized = True
        item.influence = 1.0
        item.loop_duration = 0
        item.start_frame = 0
        item.end_frame = 0
        if not str(getattr(item, "slot", "LOCAL") or "LOCAL"):
            item.slot = "LOCAL"
        if preset in {"FOLLOW_PATH", "FOLLOW_SPIRAL"}:
            item.path_duration = 100
            item.path_loop = True
            item.path_extend = 4 if preset == "FOLLOW_SPIRAL" else 1
            item.path_shape = "SPIRAL" if preset == "FOLLOW_SPIRAL" else "BEZIER"
            item.path_mode = "FORWARD"
            item.path_follow_rotation = bool(preset == "FOLLOW_SPIRAL")
            item.path_bank_strength = 0.0
            item.path_resolution = 24 if preset == "FOLLOW_SPIRAL" else 16
            item.path_radius = 1.0
            item.path_spacing = 1.0
            item.path_spiral_direction = "OUTWARD"
            item.path_clockwise = False
        elif preset == "SPRING_FOLLOW":
            item.path_extend = 6
            item.path_resolution = 16
            item.path_radius = 1.0
            item.path_spacing = 1.0
            item.path_clockwise = False
            item.speed = 1.0
            item.spring_delay = 4
            item.spring_damping = 0.65
            item.spring_stiffness = 5.0
            item.spring_overshoot = 0.2
            item.spring_flatten_2d = True
            item.spring_vertical = False
            item.spring_follow_location = True
            item.spring_follow_rotation = False
            item.spring_follow_scale = False
        if not str(getattr(item, "uid", "") or ""):
            item.uid = uuid.uuid4().hex
    finally:
        _MOTION_UPDATE_GUARD = previous_guard
    target = getattr(item, "id_data", None)
    if target is not None:
        evaluate_motion_target(target)
    _propagate_linked_motion(item)
    return item


class FBP_UL_MotionItems(UIList):
    bl_idname = "FBP_UL_motion_items"
    _PROFILE = "MOTION_ITEMS"

    def filter_items(self, context, data, propname):
        return fbp_filter_uilist_items(
            context, getattr(data, propname, ()), self._PROFILE,
            self.bitflag_filter_item,
            attributes=("name", "preset", "slot", "link_id"),
        )

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        mark_ui_list_draw()
        del data, icon, active_data, active_propname
        preset = str(getattr(item, "preset", "FLOATING") or "FLOATING")
        slot = _normalize_motion_slot(
            getattr(item, "slot", "LOCAL") or _motion_slot_from_link_id(getattr(item, "link_id", ""))
        )
        preset_icon = _motion_preset_icon(preset)
        linked = bool(str(getattr(item, "link_id", "") or ""))
        slot_icon = fbp_icon(
            MOTION_SLOT_ICONS.get(slot, "LINKED" if linked else "UNLOCKED"), "LINKED"
        )
        row = layout.row(align=True)
        visible = set(fbp_uilist_visible_columns(context, self._PROFILE))
        for key in fbp_uilist_icon_order(context, self._PROFILE):
            if key not in visible:
                continue
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(row)
                continue
            if key == "enabled":
                row.prop(
                    item, "enabled", text="", emboss=False,
                    icon="HIDE_OFF" if item.enabled else "HIDE_ON",
                )
            elif key == "preview":
                row.label(text="", icon=preset_icon)
            elif key == "selected":
                select = row.operator(
                    "fbp.motion_select_row", text="",
                    icon="CHECKBOX_HLT" if item.selected else "CHECKBOX_DEHLT",
                    emboss=False, depress=bool(item.selected),
                )
                select.index = index
            elif key == "label":
                row.prop(item, "name", text="", emboss=False)
            elif key == "slot":
                row.label(text="", icon=slot_icon)
            elif key == "link":
                if linked:
                    row.operator("fbp.motion_make_local", text="", emboss=False, icon="UNLINKED")
                else:
                    row.label(text="", icon="BLANK1")
            elif key == "remove":
                remove = row.operator("fbp.motion_remove", text="", emboss=False, icon="TRASH")
                remove.index = index


class FBP_OT_MotionSelectRow(Operator):
    bl_idname = "fbp.motion_select_row"
    bl_label = "Select Motion Row"
    bl_description = f"Select one Motion; Shift selects a range and {primary_modifier_name()} toggles one row"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})
    use_shift: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    use_ctrl: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        return invoke_with_selection_modifiers(self, context, event)

    def execute(self, context):
        target = _motion_target_from_context(context)
        if target is None or not (0 <= self.index < len(target.fbp_motions)):
            return {"CANCELLED"}
        ensure_unique_item_identities(target.fbp_motions, "uid")
        anchor_index_key = "_fbp_motion_selection_anchor"
        anchor_uid_key = "_fbp_motion_selection_anchor_uid"
        anchor = resolve_anchor_index(
            target, anchor_index_key, anchor_uid_key, target.fbp_motions, "uid",
            fallback=self.index,
        )
        lo, hi = sorted((anchor, self.index))
        for row_index, item in enumerate(target.fbp_motions):
            if self.use_shift:
                selected = (lo <= row_index <= hi) or (
                    self.use_ctrl and bool(item.selected)
                )
            elif self.use_ctrl:
                selected = not bool(item.selected) if row_index == self.index else bool(item.selected)
            else:
                selected = row_index == self.index
            item.selected = selected
        target.fbp_motion_active_index = self.index
        if not self.use_shift:
            store_anchor(
                target, anchor_index_key, anchor_uid_key, target.fbp_motions,
                "uid", self.index,
            )
        return {"FINISHED"}


class FBP_OT_MotionAdd(Operator):
    bl_idname = "fbp.motion_add"
    bl_label = "Add Motion"
    bl_description = "Add a repeatable procedural Motion instance without changing source timing"
    bl_options = {"REGISTER", "UNDO"}

    effect: StringProperty(description="Motion effect family to add. The variant can be changed later with Effect Preset.", name="Motion Effect", default="DRIFT")
    preset: StringProperty(description="Preset identifier used when adding from compatibility code.", name="Preset", default="")

    def execute(self, context):
        target = _motion_target_from_context(context)
        if target is None:
            self.report({"WARNING"}, "Select a Frame By Plane layer or Camera")
            return {"CANCELLED"}
        if not _capture_motion_base(target):
            return {"CANCELLED"}
        try:
            target["fbp_motion_effect_container"] = True
        except FBP_DATA_ERRORS:
            pass
        item = target.fbp_motions.add()
        _clear_motion_target_cache(getattr(context, "scene", None))
        effect = str(getattr(self, "effect", "DRIFT") or "DRIFT")
        preset = str(getattr(self, "preset", "") or "")
        if _motion_effect_for_preset(preset) != effect:
            preset = _motion_default_preset_for_effect(effect)
        apply_motion_preset_defaults(item, preset)
        ensure_item_identity(item, "uid")
        target.fbp_motion_active_index = len(target.fbp_motions) - 1
        store_anchor(
            target, "_fbp_motion_selection_anchor",
            "_fbp_motion_selection_anchor_uid", target.fbp_motions, "uid",
            target.fbp_motion_active_index,
        )
        evaluate_motion_target(target, context.scene)
        return {"FINISHED"}


class FBP_OT_MotionRemove(Operator):
    bl_idname = "fbp.motion_remove"
    bl_label = "Remove Motion"
    bl_description = "Remove the active Motion instance and restore the base delta transform when the stack becomes empty"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index", default=-1, options={"HIDDEN"})

    def execute(self, context):
        target = _motion_target_from_context(context)
        if target is None or not _target_has_motion(target):
            return {"CANCELLED"}
        ensure_unique_item_identities(target.fbp_motions, "uid")
        requested_index = int(getattr(self, "index", -1) or -1)
        active_index = int(target.fbp_motion_active_index)
        index = int(clamp(
            requested_index if requested_index >= 0 else active_index,
            0, len(target.fbp_motions) - 1,
        ))
        active_uid = ensure_item_identity(
            target.fbp_motions[int(clamp(active_index, 0, len(target.fbp_motions) - 1))],
            "uid",
        )
        removed_uid = ensure_item_identity(target.fbp_motions[index], "uid")
        anchor_uid = str(transient_get(target, "_fbp_motion_selection_anchor_uid", "") or "")
        try:
            _cleanup_motion_item_helpers(target.fbp_motions[index])
        except FBP_DATA_ERRORS:
            pass
        target.fbp_motions.remove(index)
        _clear_motion_target_cache(getattr(context, "scene", None))
        if target.fbp_motions:
            target.fbp_motion_active_index = restore_active_index(
                target.fbp_motions, "uid",
                "" if active_uid == removed_uid else active_uid,
                fallback=min(index, len(target.fbp_motions) - 1),
            )
            if anchor_uid == removed_uid:
                store_anchor(
                    target, "_fbp_motion_selection_anchor",
                    "_fbp_motion_selection_anchor_uid", target.fbp_motions,
                    "uid", target.fbp_motion_active_index,
                )
        else:
            target.fbp_motion_active_index = 0
            clear_anchor(
                target, "_fbp_motion_selection_anchor",
                "_fbp_motion_selection_anchor_uid",
            )
        evaluate_motion_target(target, context.scene)
        return {"FINISHED"}


class FBP_OT_MotionDuplicate(Operator):
    bl_idname = "fbp.motion_duplicate"
    bl_label = "Duplicate Motion"
    bl_description = "Duplicate the active Motion as an independent instance"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = _motion_target_from_context(context)
        if target is None or not _target_has_motion(target):
            return {"CANCELLED"}
        source = target.fbp_motions[int(clamp(target.fbp_motion_active_index, 0, len(target.fbp_motions) - 1))]
        duplicate = target.fbp_motions.add()
        for prop in source.bl_rna.properties:
            identifier = prop.identifier
            if identifier in {"rna_type", "uid"} or getattr(prop, "is_readonly", False):
                continue
            try:
                setattr(duplicate, identifier, getattr(source, identifier))
            except FBP_DATA_ERRORS:
                pass
        duplicate.uid = uuid.uuid4().hex
        duplicate.name = f"{source.name} Copy"
        target.fbp_motion_active_index = len(target.fbp_motions) - 1
        store_anchor(
            target, "_fbp_motion_selection_anchor",
            "_fbp_motion_selection_anchor_uid", target.fbp_motions, "uid",
            target.fbp_motion_active_index,
        )
        evaluate_motion_target(target, context.scene)
        return {"FINISHED"}


class FBP_OT_MotionMove(Operator):
    bl_idname = "fbp.motion_move"
    bl_label = "Move Motion"
    bl_description = "Reorder the active Motion instance"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(description='Direction used by the action. Example: UP/DOWN for stack movement, or positive/negative for directional controls.', items=(("UP", "Up", "Move up"), ("DOWN", "Down", "Move down")), default="UP")

    def execute(self, context):
        target = _motion_target_from_context(context)
        if target is None or len(target.fbp_motions) < 2:
            return {"CANCELLED"}
        ensure_unique_item_identities(target.fbp_motions, "uid")
        index = int(clamp(target.fbp_motion_active_index, 0, len(target.fbp_motions) - 1))
        active_uid = ensure_item_identity(target.fbp_motions[index], "uid")
        destination = index - 1 if self.direction == "UP" else index + 1
        destination = int(clamp(destination, 0, len(target.fbp_motions) - 1))
        if destination == index:
            return {"CANCELLED"}
        target.fbp_motions.move(index, destination)
        target.fbp_motion_active_index = restore_active_index(
            target.fbp_motions, "uid", active_uid, fallback=destination,
        )
        evaluate_motion_target(target, context.scene)
        return {"FINISHED"}


class FBP_OT_MotionSetPreset(Operator):
    bl_idname = "fbp.motion_set_preset"
    bl_label = "Set Motion Preset"
    bl_description = "Choose the preset variant for the active unified Motion effect"
    bl_options = {"REGISTER", "UNDO"}

    preset: StringProperty(name="Preset", default="FLOATING", options={"HIDDEN"})

    def execute(self, context):
        target = _motion_target_from_context(context)
        if target is None or not _target_has_motion(target):
            return {"CANCELLED"}
        index = int(clamp(target.fbp_motion_active_index, 0, len(target.fbp_motions) - 1))
        item = target.fbp_motions[index]
        preset = str(getattr(self, "preset", "FLOATING") or "FLOATING")
        if preset not in _PRESET_DEFAULTS:
            self.report({"WARNING"}, "Unknown Motion preset")
            return {"CANCELLED"}
        apply_motion_preset_defaults(item, preset, rename=True)
        _sync_generated_follow_helper_for_preset(item, target, context)
        evaluate_motion_target(target, context.scene)
        return {"FINISHED"}


class FBP_MT_MotionPreset(Menu):
    bl_idname = "FBP_MT_motion_preset"
    bl_label = "Effect Preset"

    def draw(self, context):
        layout = configure_layout(self.layout)
        target = _motion_target_from_context(context)
        item = _active_motion_item(target)
        if item is None:
            layout.label(text="No active Motion", icon="INFO")
            return
        preset = str(getattr(item, "preset", "FLOATING") or "FLOATING")
        effect = str(getattr(item, "effect", "") or _motion_effect_for_preset(preset))
        if effect not in MOTION_FAMILY_LABELS:
            effect = _motion_effect_for_preset(preset)
        for preset_id, label, _description in _motion_presets_for_family(effect):
            op = layout.operator(
                "fbp.motion_set_preset",
                text=label,
                icon=_motion_preset_icon(preset_id),
            )
            op.preset = preset_id


class FBP_OT_MotionResetPreset(Operator):
    bl_idname = "fbp.motion_reset_preset"
    bl_label = "Reset Motion Preset"
    bl_description = "Restore the active preset's recommended values"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = _motion_target_from_context(context)
        if target is None or not _target_has_motion(target):
            return {"CANCELLED"}
        item = target.fbp_motions[int(clamp(target.fbp_motion_active_index, 0, len(target.fbp_motions) - 1))]
        apply_motion_preset_defaults(item, item.preset, rename=False)
        evaluate_motion_target(target, context.scene)
        return {"FINISHED"}


class FBP_OT_MotionCaptureBase(Operator):
    bl_idname = "fbp.motion_capture_base"
    bl_label = "Capture Base Transform"
    bl_description = "Use the target's current delta transform as the neutral base for the Motion stack"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = _motion_target_from_context(context)
        if target is None:
            return {"CANCELLED"}
        if bool(getattr(target, "fbp_motion_master_enabled", True)) and _target_has_motion(target):
            self.report({'WARNING'}, "Pause Motion before capturing a new base transform")
            return {"CANCELLED"}
        if not _capture_motion_base(target, force=True):
            return {"CANCELLED"}
        if bool(getattr(target, "fbp_motion_master_enabled", True)):
            evaluate_motion_target(target, context.scene)
        self.report({'INFO'}, "Motion base transform captured")
        return {"FINISHED"}


class FBP_OT_MotionCreatePivot(Operator):
    bl_idname = "fbp.motion_create_pivot"
    bl_label = "Create Motion Pivot Null"
    bl_description = "Create an Empty at the target origin and assign it as the active Motion pivot"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = _motion_target_from_context(context)
        item = _active_motion_item(target)
        if target is None or item is None:
            return {"CANCELLED"}
        collection = getattr(context, "collection", None)
        if collection is None:
            self.report({"ERROR"}, "No active collection available for the Motion pivot")
            return {"CANCELLED"}
        try:
            empty = bpy.data.objects.new(f"FBP Motion Pivot · {target.name}", None)
            empty.empty_display_type = "SINGLE_ARROW"
            size = max(0.25, max(tuple(getattr(target, "dimensions", (1.0, 1.0, 1.0))) or (1.0,)) * 0.18)
            empty.empty_display_size = size
            collection.objects.link(empty)
            empty.location = _object_world_location(target)
            item.pivot_object = empty
            _sync_motion_pivot_orientation(item)
            try:
                empty.select_set(True)
                target.select_set(True)
                context.view_layer.objects.active = target
            except FBP_DATA_ERRORS:
                pass
        except FBP_DATA_ERRORS as exc:
            self.report({"ERROR"}, f"Could not create Motion pivot: {exc}")
            return {"CANCELLED"}
        evaluate_motion_target(target, context.scene)
        return {"FINISHED"}


class FBP_OT_MotionRandomizeSeed(Operator):
    bl_idname = "fbp.motion_randomize_seed"
    bl_label = "Randomize Motion Seed"
    bl_description = "Assign a new deterministic seed to the active Motion"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = _motion_target_from_context(context)
        if target is None or not _target_has_motion(target):
            return {"CANCELLED"}
        item = target.fbp_motions[int(clamp(target.fbp_motion_active_index, 0, len(target.fbp_motions) - 1))]
        item.seed = (int(item.seed) * 1664525 + 1013904223 + len(target.name)) % 1000000
        evaluate_motion_target(target, context.scene)
        return {"FINISHED"}


class FBP_OT_MotionLinkSelected(Operator):
    bl_idname = "fbp.motion_link_selected"
    bl_label = "Link Motion to Selected"
    bl_description = "Share the active Motion settings with the selected Frame By Plane layers and cameras"
    bl_options = {"REGISTER", "UNDO"}

    share_seed: BoolProperty(
        name="Share Seed",
        description="Use the same deterministic seed on every linked target",
        default=False,
    )

    def execute(self, context):
        source_target = _motion_target_from_context(context)
        source = _active_motion_item(source_target)
        targets = _sort_motion_targets(_selected_motion_targets(context))
        if source is None or len(targets) < 2:
            self.report({"WARNING"}, "Select at least two compatible targets and an active Motion")
            return {"CANCELLED"}
        link_id = str(getattr(source, "link_id", "") or uuid.uuid4().hex)
        source.link_id = link_id
        source.share_seed = bool(self.share_seed)
        linked = 0
        for index, target in enumerate(targets):
            item = source if _same_rna(target, source_target) else _ensure_linked_motion(
                target, source, link_id, share_seed=self.share_seed, index=index
            )
            if item is None:
                continue
            item.link_id = link_id
            item.share_seed = bool(self.share_seed)
            evaluate_motion_target(target, context.scene)
            linked += 1
        _propagate_linked_motion(source, context.scene)
        self.report({"INFO"}, f"Motion linked to {linked} targets")
        return {"FINISHED"}


class FBP_OT_MotionMakeLocal(Operator):
    bl_idname = "fbp.motion_make_local"
    bl_label = "Make Motion Local"
    bl_description = "Detach the active Motion from its shared link while keeping its current settings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = _motion_target_from_context(context)
        item = _active_motion_item(target)
        link_id = str(getattr(item, "link_id", "") or "") if item is not None else ""
        if not link_id:
            self.report({"INFO"}, "The active Motion is already local")
            return {"CANCELLED"}
        item.link_id = ""
        item.share_seed = False
        item.slot = "LOCAL"
        remaining = list(_linked_motion_items(link_id, context.scene))
        if len(remaining) == 1:
            remaining[0][1].link_id = ""
            remaining[0][1].share_seed = False
        self.report({"INFO"}, "Motion made local")
        return {"FINISHED"}


class FBP_OT_MotionSelectLinked(Operator):
    bl_idname = "fbp.motion_select_linked"
    bl_label = "Select Linked Motion Users"
    bl_description = "Select every layer or camera using the active shared Motion"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = _motion_target_from_context(context)
        item = _active_motion_item(target)
        link_id = str(getattr(item, "link_id", "") or "") if item is not None else ""
        users = _linked_motion_items(link_id, context.scene)
        if not users:
            return {"CANCELLED"}
        try:
            for candidate in tuple(context.selected_objects):
                candidate.select_set(False)
            for candidate, _motion in users:
                candidate.hide_set(False)
                candidate.select_set(True)
            context.view_layer.objects.active = target
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}
        self.report({"INFO"}, f"Selected {len(users)} linked Motion users")
        return {"FINISHED"}


class FBP_OT_MotionSyncLinked(Operator):
    bl_idname = "fbp.motion_sync_linked"
    bl_label = "Sync Linked Motion"
    bl_description = "Push the active shared Motion settings to all linked targets now"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = _motion_target_from_context(context)
        item = _active_motion_item(target)
        if item is None or not str(getattr(item, "link_id", "") or ""):
            return {"CANCELLED"}
        changed = _propagate_linked_motion(item, context.scene)
        self.report({"INFO"}, f"Updated {changed} linked Motion users")
        return {"FINISHED"}


def _motion_resolve_runtime_target(name, token, collection=None):
    if collection is None:
        collection = getattr(bpy.data, "objects", ())
    return fbp_find_id_by_runtime_key(collection, token, name) if token else None


def _motion_resolve_runtime_targets(payload):
    try:
        descriptors = json.loads(str(payload or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    resolved = []
    seen = set()
    for descriptor in descriptors if isinstance(descriptors, list) else ():
        if not isinstance(descriptor, dict):
            continue
        target = _motion_resolve_runtime_target(
            str(descriptor.get("name", "") or ""),
            str(descriptor.get("key", "") or ""),
        )
        key = fbp_obj_runtime_key(target) if target is not None else None
        if target is not None and key not in seen:
            seen.add(key)
            resolved.append(target)
    return resolved


def _motion_item_by_uid(target, uid):
    uid = str(uid or "")
    if target is None or not uid:
        return None
    return next(
        (item for item in getattr(target, "fbp_motions", ()) if str(getattr(item, "uid", "") or "") == uid),
        None,
    )


class FBP_OT_MotionDistribute(Operator):
    bl_idname = "fbp.motion_distribute"
    bl_label = "Distribute Motion"
    bl_description = "Link the active Motion across selected targets, then apply stagger and influence falloff"
    bl_options = {"REGISTER", "UNDO"}

    stagger_mode: EnumProperty(description='Operation mode for this Motion system. Example: choose whether the command adds, removes, previews, repairs or applies settings.', name="Stagger", items=MOTION_STAGGER_ITEMS, default="PROGRESSIVE")
    stagger_frames: IntProperty(description='Timeline frame or frame-count value used by the selected animation, sequence or loop operation.', name="Frames per Step", default=2, min=0, soft_max=48)
    phase_step: FloatProperty(description='Phase Step value used by the current Motion system. Changes are applied only to compatible Frame By Plane data.', name="Phase per Step", subtype="ANGLE", unit="ROTATION", default=0.0)
    falloff_mode: EnumProperty(description='Operation mode for this Motion system. Example: choose whether the command adds, removes, previews, repairs or applies settings.', name="Falloff", items=MOTION_FALLOFF_ITEMS, default="NONE")
    minimum_influence: FloatProperty(description='Blend strength of this control. 0 disables its visual contribution; 1 applies the full registered effect.', name="Minimum", subtype="FACTOR", default=0.35, min=0.0, max=1.0)
    invert_distance: BoolProperty(name="Invert Distance", description="Give distant targets more influence than the active target", default=False)
    randomize_seed: BoolProperty(description='Deterministic random seed. Change it to get a different variation without changing the overall settings.', name="Randomize Seed per Target", default=True)
    scene_name: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    scene_key: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    source_name: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    source_key: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    source_motion_uid: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    target_payload: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        del event
        source_target = _motion_target_from_context(context)
        source = _active_motion_item(source_target)
        targets = _sort_motion_targets(_selected_motion_targets(context))
        if source is None or len(targets) < 2:
            self.report({"WARNING"}, "Select at least two compatible targets and an active Motion")
            return {"CANCELLED"}
        ensure_unique_item_identities(source_target.fbp_motions, "uid")
        self.scene_name = str(getattr(context.scene, "name", "") or "")
        self.scene_key = fbp_obj_runtime_token(context.scene)
        self.source_name = str(getattr(source_target, "name", "") or "")
        self.source_key = fbp_obj_runtime_token(source_target)
        self.source_motion_uid = ensure_item_identity(source, "uid")
        self.target_payload = _motion_capture_runtime_targets(targets)
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        del context
        layout = configure_layout(self.layout)
        section_header(layout, "Stagger", icon=fbp_icon("TIME"))
        layout.prop(self, "stagger_mode")
        row = layout.row(align=False)
        row.prop(self, "stagger_frames")
        row.prop(self, "phase_step")
        section_gap(layout)
        section_header(layout, "Influence Falloff", icon=fbp_icon("IPO_EASE_IN_OUT"))
        layout.prop(self, "falloff_mode")
        if self.falloff_mode != "NONE":
            layout.prop(self, "minimum_influence")
        if self.falloff_mode == "BY_DISTANCE":
            layout.prop(self, "invert_distance")
        layout.prop(self, "randomize_seed")

    def execute(self, context):
        scene = _motion_resolve_runtime_target(
            self.scene_name, self.scene_key, getattr(bpy.data, "scenes", ()),
        ) if self.scene_key else getattr(context, "scene", None)
        if self.source_key:
            source_target = _motion_resolve_runtime_target(self.source_name, self.source_key)
            source = _motion_item_by_uid(source_target, self.source_motion_uid)
            targets = _motion_resolve_runtime_targets(self.target_payload)
        else:
            # Preserve explicit EXEC_DEFAULT/script compatibility. Invoked UI
            # dialogs always use the captured branch above.
            source_target = _motion_target_from_context(context)
            source = _active_motion_item(source_target)
            targets = _sort_motion_targets(_selected_motion_targets(context))
        source_in_targets = any(_same_rna(target, source_target) for target in targets)
        if scene is None or source is None or len(targets) < 2 or not source_in_targets:
            self.report({"WARNING"}, "The original Motion selection changed or no longer exists")
            return {"CANCELLED"}

        link_id = str(getattr(source, "link_id", "") or uuid.uuid4().hex)
        source.link_id = link_id
        if self.randomize_seed:
            source.share_seed = False
        stagger_values = motion_distribution_values(len(targets), self.stagger_mode, seed=int(source.seed))
        falloff_mode = {
            "FRONT_TO_BACK": "REVERSE",
            "BACK_TO_FRONT": "PROGRESSIVE",
            "RANDOM": "RANDOM",
        }.get(self.falloff_mode, "PROGRESSIVE")
        if self.falloff_mode == "BY_DISTANCE":
            positions = []
            source_index = 0
            for index, target in enumerate(targets):
                if _same_rna(target, source_target):
                    source_index = index
                try:
                    positions.append(tuple(float(value) for value in target.matrix_world.translation))
                except FBP_DATA_ERRORS:
                    positions.append(tuple(float(value) for value in getattr(target, "location", (0.0, 0.0, 0.0))))
            falloff_values = motion_distance_values(positions, source_index, invert=self.invert_distance)
        else:
            falloff_values = motion_distribution_values(len(targets), falloff_mode, seed=int(source.seed) + 409)
        base_offset = int(getattr(source, "start_frame", 0) or 0)
        base_phase = float(source.phase)
        base_influence = float(source.influence)
        count = len(targets)
        linked = 0

        global _MOTION_LINK_GUARD
        previous_guard = _MOTION_LINK_GUARD
        _MOTION_LINK_GUARD = True
        try:
            for index, target in enumerate(targets):
                item = source if _same_rna(target, source_target) else _ensure_linked_motion(
                    target, source, link_id, share_seed=not self.randomize_seed, index=index
                )
                if item is None:
                    continue
                item.link_id = link_id
                item.share_seed = not self.randomize_seed
                value = float(stagger_values[index])
                extent = (count - 1) * 0.5 if self.stagger_mode in {"CENTERED", "PING_PONG"} else (count - 1)
                item.start_frame = base_offset + int(round(value * extent * int(self.stagger_frames)))
                item.phase = base_phase + float(self.phase_step) * index
                if self.falloff_mode == "NONE":
                    item.influence = base_influence
                else:
                    factor = float(self.minimum_influence) + (1.0 - float(self.minimum_influence)) * float(falloff_values[index])
                    item.influence = clamp(base_influence * factor, 0.0, 1.0)
                if self.randomize_seed:
                    item.seed = _stable_target_seed(target, source.seed, index)
                evaluate_motion_target(target, scene)
                linked += 1
        finally:
            _MOTION_LINK_GUARD = previous_guard
        _propagate_linked_motion(source, scene)
        self.report({"INFO"}, f"Distributed Motion across {linked} targets")
        return {"FINISHED"}


class FBP_OT_MotionBake(Operator):
    bl_idname = "fbp.motion_bake"
    bl_label = "Bake Motion to Keyframes"
    bl_description = "Bake the complete Motion stack into native Generated delta-transform keyframes"
    bl_options = {"REGISTER", "UNDO"}

    frame_start: IntProperty(description='Timeline frame or frame-count value used by the selected animation, sequence or loop operation.', name="Start", default=1, min=-1048574, max=1048574)
    frame_end: IntProperty(description='Timeline frame or frame-count value used by the selected animation, sequence or loop operation.', name="End", default=250, min=-1048574, max=1048574)
    step: IntProperty(description='Step value used by the current Motion system. Changes are applied only to compatible Frame By Plane data.', name="Step", default=1, min=1, soft_max=12)
    overwrite: BoolProperty(
        name="Overwrite Existing Delta Keys",
        description="Allow the bake to replace delta-transform keyframes already present in the range",
        default=False,
    )
    keep_procedural: BoolProperty(
        name="Keep Motion Stack",
        description="Keep the procedural Motion stack but pause it after baking",
        default=True,
    )
    bake_location: BoolProperty(description='Toggle this option for the current Motion system. Disabled keeps the data available but prevents this behavior from being applied.', name="Position", default=True)
    bake_rotation: BoolProperty(description='Toggle this option for the current Motion system. Disabled keeps the data available but prevents this behavior from being applied.', name="Rotation", default=True)
    bake_scale: BoolProperty(description='Toggle this option for the current Motion system. Disabled keeps the data available but prevents this behavior from being applied.', name="Scale", default=True)
    reduce_tolerance: FloatProperty(
        name="Key Reduction", description="Remove redundant Generated keys after baking; zero keeps every sample",
        default=0.0, min=0.0, soft_max=0.01, precision=5,
    )
    scene_name: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    scene_key: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    target_name: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    target_key: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        target = _motion_target_from_context(context)
        return target is not None and _target_has_motion(target)

    def invoke(self, context, _event):
        target = _motion_target_from_context(context)
        if target is None or not _target_has_motion(target):
            return {"CANCELLED"}
        self.scene_name = str(getattr(context.scene, "name", "") or "")
        self.scene_key = fbp_obj_runtime_token(context.scene)
        self.target_name = str(getattr(target, "name", "") or "")
        self.target_key = fbp_obj_runtime_token(target)
        self.frame_start = int(context.scene.frame_start)
        self.frame_end = int(context.scene.frame_end)
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, _context):
        layout = configure_layout(self.layout)
        section_header(layout, "Bake Range", icon=fbp_icon("KEYFRAME"))
        row = layout.row(align=True)
        row.prop(self, "frame_start")
        row.prop(self, "frame_end")
        row.prop(self, "step")
        section_gap(layout)
        channels = layout.box()
        configure_layout(channels)
        section_header(channels, "Channels", icon=fbp_icon("KEYFRAME"))
        row = channels.row(align=False)
        row.prop(self, "bake_location")
        row.prop(self, "bake_rotation")
        row.prop(self, "bake_scale")
        layout.prop(self, "reduce_tolerance")
        layout.prop(self, "keep_procedural")
        layout.prop(self, "overwrite")
        hint_row(layout, "Baked keys use Generated type and Linear interpolation.", icon="INFO")

    def execute(self, context):
        scene = _motion_resolve_runtime_target(
            self.scene_name, self.scene_key, getattr(bpy.data, "scenes", ()),
        ) if self.scene_key else getattr(context, "scene", None)
        target = (
            _motion_resolve_runtime_target(self.target_name, self.target_key)
            if self.target_key else _motion_target_from_context(context)
        )
        if scene is None or target is None or not _target_has_motion(target):
            self.report({"WARNING"}, "The original Motion target no longer exists")
            return {"CANCELLED"}
        try:
            channels = tuple(
                channel for channel, enabled in (
                    ("LOCATION", self.bake_location),
                    ("ROTATION", self.bake_rotation),
                    ("SCALE", self.bake_scale),
                ) if enabled
            )
            result = bake_motion_to_keyframes(
                target, scene, self.frame_start, self.frame_end,
                step=self.step, overwrite=self.overwrite, keep_procedural=self.keep_procedural,
                channels=channels, reduce_tolerance=self.reduce_tolerance,
            )
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Baked Motion on {len(result['frames'])} frame(s); reduced {result['reduced']} key(s)")
        return {"FINISHED"}


def _motion_presets_for_family(family):
    family = str(family or "SECONDARY")
    return tuple(
        (preset, label, description)
        for preset, label, description in MOTION_PRESET_ITEMS
        if MOTION_PRESET_FAMILIES.get(preset, "SECONDARY") == family
    )


def _draw_motion_effect_menu(layout):
    """Draw Add Motion as a flat list of effects, not nested folders."""
    for effect, label, _description in MOTION_EFFECT_ITEMS:
        preset = _motion_default_preset_for_effect(effect)
        operator = layout.operator(
            "fbp.motion_add", text=label,
            icon=_motion_preset_icon(preset),
        )
        operator.effect = effect
        operator.preset = preset


class FBP_MT_MotionAdd(Menu):
    bl_idname = "FBP_MT_motion_add"
    bl_label = "Add Motion"

    def draw(self, context):
        del context
        _draw_motion_effect_menu(self.layout)


class FBP_MT_MotionListActions(Menu):
    bl_idname = "FBP_MT_motion_list_actions"
    bl_label = "Motion List Actions"

    def draw(self, context):
        layout = configure_layout(self.layout)
        target = _motion_target_from_context(context)
        has_item = _active_motion_item(target) is not None
        duplicate = layout.row(align=True)
        duplicate.enabled = has_item
        duplicate.operator("fbp.motion_duplicate", text="Duplicate Motion", icon="DUPLICATE")
        remove = layout.row(align=True)
        remove.enabled = has_item
        remove.operator("fbp.motion_remove", text="Remove Motion", icon="TRASH")


class FBP_OT_MotionCreateFollowHelper(Operator):
    bl_idname = "fbp.motion_create_follow_helper"
    bl_label = "Create Motion Follow Helper"
    bl_description = "Create and assign the helper needed by the active Follow Curve, Follow Spiral or Follow Spring preset"
    bl_options = {"REGISTER", "UNDO"}

    helper_type: EnumProperty(
        name="Helper Type",
        items=(
            ("CURVE", "Curve", "Create a Curve helper for Follow Curve"),
            ("SPRING", "Follow Spring", "Create a visible coil plus target for Follow Spring"),
        ),
        default="CURVE",
        options={"HIDDEN"},
    )

    def execute(self, context):
        target = _motion_target_from_context(context)
        item = _active_motion_item(target)
        if target is None or item is None:
            return {"CANCELLED"}
        collection = getattr(context, "collection", None)
        if collection is None:
            self.report({"ERROR"}, "No active collection available for the Motion helper")
            return {"CANCELLED"}
        helper_type = str(getattr(self, "helper_type", "CURVE") or "CURVE")
        try:
            _cleanup_motion_item_helpers(item)
            world_location = _object_world_location(target)
            size = max(0.5, max(tuple(getattr(target, "dimensions", (1.0, 1.0, 1.0))) or (1.0,)) * 0.35)
            if helper_type == "SPRING":
                transform, center = _motion_base_helper_transform(target, context)
                half = _follow_curve_half_size(target)
                curve = bpy.data.curves.new(f"FBP Spring Coil · {target.name}", "CURVE")
                _rebuild_spring_curve_data(
                    curve,
                    half,
                    _path_extend_count(item),
                    getattr(item, "path_resolution", 24),
                    bool(getattr(item, "spring_flatten_2d", False)),
                    vertical=bool(getattr(item, "spring_vertical", False)),
                    radius_scale=getattr(item, "path_radius", 1.0),
                    spacing_scale=getattr(item, "path_spacing", 1.0),
                    clockwise=bool(getattr(item, "path_clockwise", False)),
                )
                spring_curve = bpy.data.objects.new(f"FBP Spring Coil · {target.name}", curve)
                collection.objects.link(spring_curve)
                try:
                    if transform is not None:
                        spring_curve.matrix_world = transform
                        spring_curve.scale = (1.0, 1.0, 1.0)
                    elif center is not None:
                        spring_curve.location = center
                    else:
                        spring_curve.location = world_location
                except FBP_DATA_ERRORS:
                    spring_curve.location = world_location
                spring_curve.hide_render = True
                _mark_motion_helper(spring_curve, target, item, "SPRING_CURVE")
                item.path_object = spring_curve

                empty = bpy.data.objects.new(f"FBP Spring Target · {target.name}", None)
                empty.empty_display_type = "ARROWS"
                empty.empty_display_size = size
                collection.objects.link(empty)
                try:
                    try:
                        from mathutils import Vector
                    except (ImportError, AttributeError):
                        Vector = None
                    coords = _spring_curve_points(
                        half,
                        _path_extend_count(item),
                        getattr(item, "path_resolution", 24),
                        bool(getattr(item, "spring_flatten_2d", False)),
                        vertical=bool(getattr(item, "spring_vertical", False)),
                        radius_scale=getattr(item, "path_radius", 1.0),
                        spacing_scale=getattr(item, "path_spacing", 1.0),
                        clockwise=bool(getattr(item, "path_clockwise", False)),
                    )
                    end_local = coords[-1] if coords else (0.0, 0.0, 0.0)
                    if transform is not None and Vector is not None:
                        empty.location = transform @ Vector(end_local)
                    elif center is not None:
                        empty.location = (center[0] + end_local[0], center[1] + end_local[1], center[2] + end_local[2])
                    else:
                        empty.location = (world_location[0] + end_local[0], world_location[1] + end_local[1], world_location[2] + end_local[2])
                except FBP_DATA_ERRORS:
                    empty.location = center if center is not None else world_location
                empty.hide_render = True
                _mark_motion_helper(empty, target, item, "SPRING_TARGET")
                item.spring_target = empty
                helper = spring_curve
            else:
                curve = bpy.data.curves.new(f"FBP Follow Spiral · {target.name}" if str(getattr(item, "preset", "")) == "FOLLOW_SPIRAL" else f"FBP Follow Curve · {target.name}", "CURVE")
                half = _follow_curve_half_size(target)
                _rebuild_follow_curve_data(
                    curve,
                    getattr(item, "path_shape", "BEZIER"),
                    half,
                    _path_extend_count(item),
                    getattr(item, "path_resolution", 24),
                    radius_scale=getattr(item, "path_radius", 1.0),
                    spacing_scale=getattr(item, "path_spacing", 1.0),
                    spiral_direction=getattr(item, "path_spiral_direction", "OUTWARD"),
                    clockwise=bool(getattr(item, "path_clockwise", False)),
                )
                helper = bpy.data.objects.new(f"FBP Follow Spiral · {target.name}" if str(getattr(item, "preset", "")) == "FOLLOW_SPIRAL" else f"FBP Follow Curve · {target.name}", curve)
                collection.objects.link(helper)
                transform, center = _motion_base_helper_transform(target, context)
                try:
                    if transform is not None:
                        helper.matrix_world = transform
                        helper.scale = (1.0, 1.0, 1.0)
                    elif center is not None:
                        helper.location = center
                    else:
                        helper.location = _object_world_location(target)
                except FBP_DATA_ERRORS:
                    helper.location = _object_world_location(target)
                helper.hide_render = True
                _mark_motion_helper(helper, target, item, "CURVE")
                item.path_object = helper
            try:
                helper.select_set(True)
                target.select_set(True)
                context.view_layer.objects.active = target
            except FBP_DATA_ERRORS:
                pass
        except FBP_DATA_ERRORS as exc:
            self.report({"ERROR"}, f"Could not create Motion helper: {exc}")
            return {"CANCELLED"}
        _sync_motion_helper_visibility(context, force=True)
        evaluate_motion_target(target, context.scene)
        return {"FINISHED"}


def _motion_default_channels(preset):
    defaults = _PRESET_DEFAULTS.get(str(preset or ""), {})
    loc = tuple(defaults.get("location_strength", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0))
    rot = tuple(defaults.get("rotation_strength", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0))
    scale = float(defaults.get("scale_strength", 0.0) or 0.0)
    return {
        "position": any(abs(float(value)) > 1.0e-12 for value in loc),
        "rotation": any(abs(float(value)) > 1.0e-12 for value in rot),
        "scale": abs(scale) > 1.0e-12,
    }


def _draw_axis_toggles(layout, item, names=("axis_x", "axis_y", "axis_z"), labels=("X", "Y", "Z")):
    row = layout.row(align=True)
    for prop_name, label in zip(tuple(names), tuple(labels), strict=False):
        row.prop(item, prop_name, text=label, toggle=True)
    return row


def _draw_motion_axis_box(parent, item, title, icon="EMPTY_ARROWS", names=("axis_x", "axis_y", "axis_z"), *, speed=True, strength=True, labels=("X", "Y", "Z"), context=None):
    box = parent.box()
    configure_layout(box)
    section_header(box, title, icon=fbp_icon(icon))
    _draw_axis_toggles(box, item, names, labels=labels)
    if speed or strength:
        row = adaptive_row(box, context) if context is not None else box.row(align=True)
        if speed:
            row.prop(item, "speed", text="Speed")
        if strength:
            row.prop(item, "amount", text="Strength")
    return box

class FBP_PT_Motion(Panel):
    bl_label = "Motion"
    bl_description = "Layer repeatable procedural animation without changing image-sequence timing"
    bl_idname = "FBP_PT_motion"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Frame By Plane"
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return _motion_target_from_context(context) is not None

    def draw_header(self, context):
        del context
        self.layout.label(text="", icon=fbp_icon("TIME"))

    def draw(self, context):
        layout = configure_layout(self.layout)
        target = getattr(self, "_fbp_motion_target", None) or _motion_target_from_context(context)
        if target is None:
            return

        if not bool(getattr(self, "_fbp_motion_embedded", False)):
            header = layout.row(align=False)
            target_kind = "Camera" if str(getattr(target, "type", "")) == "CAMERA" else "Layer"
            header.label(text=f"{target_kind}: {target.name}", icon=fbp_icon("CAMERA_DATA") if target_kind == "Camera" else fbp_icon("EMPTY_ARROWS"))
            header.operator("fbp.motion_capture_base", text="", icon="PIVOT_CURSOR")

        list_box = fbp_draw_uilist_header(
            layout, context, "MOTION_ITEMS"
        )
        row = list_box.row(align=False)
        row.template_list(
            "FBP_UL_motion_items", "",
            target, "fbp_motions",
            target, "fbp_motion_active_index",
            rows=FBP_UI_LIST_MIN_ROWS,
        )
        controls = row.column(align=True)
        fbp_set_ui_units_x(controls, 1.0)
        controls.menu("FBP_MT_motion_list_actions", text="", icon="COLLAPSEMENU")
        controls.separator()
        movement = controls.column(align=True)
        up = movement.operator("fbp.motion_move", text="", icon="SORT_DESC")
        up.direction = "UP"
        down = movement.operator("fbp.motion_move", text="", icon="SORT_ASC")
        down.direction = "DOWN"
        controls.separator()
        controls.menu("FBP_MT_motion_add", text="", icon="ADD")

        if not _target_has_motion(target):
            empty = empty_state(
                layout,
                "No Motion presets",
                "Add a preset to create procedural transform animation.",
                icon="INFO",
            )
            empty.menu("FBP_MT_motion_add", text="Add Motion", icon="ADD")
            return

        index = int(clamp(target.fbp_motion_active_index, 0, len(target.fbp_motions) - 1))
        item = target.fbp_motions[index]
        section_gap(layout)
        box = layout.box()
        configure_layout(box)

        preset = str(getattr(item, "preset", "FLOATING") or "FLOATING")
        effect = _motion_effect_for_preset(preset)
        preset_icon = _motion_preset_icon(preset)
        header = box.row(align=False)
        title = header.row(align=False)
        title.alignment = "LEFT"
        title.label(text=_motion_effect_label(effect), icon=preset_icon)
        header.prop(item, "slot", text="")
        header.operator("fbp.motion_reset_preset", text="", icon=fbp_icon("REFRESH", "FILE_REFRESH"))
        if str(getattr(item, "link_id", "") or ""):
            header.operator("fbp.motion_make_local", text="", icon="UNLINKED")

        preset_row = box.row(align=False)
        preset_row.label(text="Effect Preset", icon=_motion_preset_icon(preset))
        preset_row.menu(
            "FBP_MT_motion_preset",
            text=_PRESET_LABELS.get(preset, preset.replace("_", " ").title()),
            icon=_motion_preset_icon(preset),
        )

        timing = box.box()
        configure_layout(timing)
        section_header(timing, "Timing", icon="TIME")
        row = adaptive_row(timing, context)
        row.prop(item, "start_frame")
        row.prop(item, "end_frame")
        row.prop(item, "step_frames")
        row = adaptive_row(timing, context)
        row.prop(item, "influence")
        row.prop(item, "phase")

        channels = _motion_default_channels(preset)
        if preset in {"FLOATING", "HANDHELD", "CAMERA_DRIFT"}:
            _draw_motion_axis_box(box, item, "Rotation Axes", "EMPTY_ARROWS", context=context)
            position = box.box()
            configure_layout(position)
            section_header(position, "Position Axes", icon=fbp_icon("EMPTY_ARROWS"))
            _draw_axis_toggles(position, item, ("position_axis_x", "position_axis_y", "position_axis_z"))
            row = adaptive_row(position, context)
            row.prop(item, "position_speed", text="Speed")
            row.prop(item, "position_strength", text="Strength")
        elif preset == "BREATHING":
            _draw_motion_axis_box(
                box, item, "Scale Axes", "FULLSCREEN_ENTER",
                ("scale_axis_x", "scale_axis_y"), labels=("X", "Y"), context=context,
            )
        elif preset in {"PENDULUM", "HANGING_SIGN"}:
            swing = _draw_motion_axis_box(box, item, "Rotation Axes", "EMPTY_ARROWS", context=context)
            swing.prop(item, "anchor_point", text="Anchor Point")
        elif preset not in {"FOLLOW_PATH", "FOLLOW_SPIRAL", "SPRING_FOLLOW"}:
            if channels["rotation"] and not channels["position"] and not channels["scale"]:
                title = "Rotation Axes"
            elif channels["position"] and not channels["rotation"] and not channels["scale"]:
                title = "Position Axes"
            elif channels["scale"] and not channels["rotation"] and not channels["position"]:
                title = "Scale Axes"
            else:
                title = "Transform Axes"
            _draw_motion_axis_box(box, item, title, "EMPTY_ARROWS", context=context)
            if channels["scale"] and title != "Scale Axes":
                scale_box = box.box()
                configure_layout(scale_box)
                section_header(scale_box, "Scale Axes", icon=fbp_icon("FULLSCREEN_ENTER"))
                _draw_axis_toggles(scale_box, item, ("scale_axis_x", "scale_axis_y", "scale_axis_z"))

        row = box.row(align=False)
        row.prop(item, "space", text="")
        row = adaptive_row(box, context)
        row.prop(item, "pivot_object", text="Pivot Null")
        row.operator("fbp.motion_create_pivot", text="", icon=fbp_icon("EMPTY_ARROWS"))
        if item.preset in {"FOLLOW_PATH", "FOLLOW_SPIRAL"}:
            path_box = box.box()
            path_header = path_box.row(align=False)
            path_header.label(text="Spiral Path" if item.preset == "FOLLOW_SPIRAL" else "Curve Path", icon=_motion_preset_icon(item.preset))
            make_curve = path_header.operator("fbp.motion_create_follow_helper", text="", icon=_motion_preset_icon(item.preset, "CURVE_BEZCURVE"))
            make_curve.helper_type = "CURVE"
            path_box.prop(item, "path_object")
            row = adaptive_row(path_box, context)
            row.prop(item, "path_shape")
            row.prop(item, "path_extend")
            if item.path_shape == "SPIRAL" or item.preset == "FOLLOW_SPIRAL":
                row = adaptive_row(path_box, context)
                row.prop(item, "path_radius")
                row.prop(item, "path_spacing")
                row = adaptive_row(path_box, context)
                row.prop(item, "path_spiral_direction", text="Direction")
                row.prop(item, "path_clockwise")
            row = adaptive_row(path_box, context)
            row.prop(item, "path_duration")
            row.prop(item, "speed", text="Speed")
            row = adaptive_row(path_box, context)
            row.prop(item, "path_mode")
            row.prop(item, "path_loop")
            row = adaptive_row(path_box, context)
            row.prop(item, "path_follow_rotation")
            row.prop(item, "path_resolution")
            if item.path_follow_rotation:
                row = path_box.row(align=False)
                row.prop(item, "path_bank_strength")
            if item.path_object is None:
                warning = path_box.row(align=False)
                warning.alert = True
                warning.label(text="Choose a Curve object", icon="ERROR")
        elif item.preset == "SPRING_FOLLOW":
            spring = box.box()
            spring_header = spring.row(align=False)
            spring_header.label(text="Follow Spring", icon=_motion_preset_icon("SPRING_FOLLOW", "MOD_WAVE"))
            make_spring = spring_header.operator("fbp.motion_create_follow_helper", text="", icon=_motion_preset_icon("SPRING_FOLLOW", "MOD_WAVE"))
            make_spring.helper_type = "SPRING"
            row = adaptive_row(spring, context)
            row.prop(item, "spring_target", text="Target")
            row.prop(item, "path_object", text="Coil")
            row = adaptive_row(spring, context)
            row.prop(item, "path_extend", text="Extend")
            row.prop(item, "path_resolution", text="Coil Quality")
            row = adaptive_row(spring, context)
            row.prop(item, "path_radius", text="Radius")
            row.prop(item, "path_spacing", text="Wave Spacing")
            row = adaptive_row(spring, context, threshold=430.0)
            row.prop(item, "speed", text="Speed")
            row.prop(item, "spring_vertical", text="Vertical")
            row.prop(item, "spring_flatten_2d", text="Flat 2D")
            row.prop(item, "path_clockwise", text="Clockwise")
            row = adaptive_row(spring, context)
            row.prop(item, "spring_delay")
            row.prop(item, "spring_stiffness")
            row = adaptive_row(spring, context)
            row.prop(item, "spring_damping")
            row.prop(item, "spring_overshoot")
            if item.spring_target is None:
                warning = spring.row(align=False)
                warning.alert = True
                warning.label(text="Create or choose a Spring target", icon="ERROR")

        bake = box.row(align=False)
        bake.operator("fbp.motion_bake", text="Bake Motion to Keyframes", icon=fbp_icon("KEYFRAME"))
        if getattr(target, "fbp_motion_last_bake_report", ""):
            box.label(text=target.fbp_motion_last_bake_report, icon="CHECKMARK")

def _remove_motion_handler(handler_list, callback_name):
    """Remove current and stale reload copies of one Motion handler."""
    return remove_handlers_by_name(
        handler_list,
        callback_name,
        module_suffix="motion_runtime",
    )


@persistent
def _fbp_motion_frame_change(scene, _depsgraph=None):
    global _MOTION_HANDLER_GUARD, _MOTION_DEFERRED_VIEWPORT_ACTIVE
    if _MOTION_HANDLER_GUARD or fbp_undo_guard_active():
        return
    render_guard_active = bool(fbp_runtime_get("fbp_render_guard_active", False))
    if not render_guard_active and not _MOTION_DEFERRED_VIEWPORT_ACTIVE:
        scene_key = fbp_obj_runtime_key(scene)
        if scene_key is None:
            return
        try:
            scene_name = str(getattr(scene, "name_full", getattr(scene, "name", "")) or "")
        except FBP_DATA_ERRORS:
            scene_name = ""

        def _sync():
            global _MOTION_DEFERRED_VIEWPORT_ACTIVE
            if fbp_undo_guard_active() or fbp_render_mutation_blocked():
                return 0.20
            if not fbp_depsgraph_quiet_for(0.20):
                return 0.08
            target_scene = fbp_find_id_by_runtime_key(
                getattr(bpy.data, "scenes", ()), scene_key, scene_name
            )
            if target_scene is None:
                return None
            _MOTION_DEFERRED_VIEWPORT_ACTIVE = True
            try:
                _fbp_motion_frame_change(target_scene)
            finally:
                _MOTION_DEFERRED_VIEWPORT_ACTIVE = False
            return None

        try:
            from .safe_tasks import schedule_once
            schedule_once(
                f"motion.viewport_frame_sync.{scene_key}",
                _sync,
                first_interval=0.05,
            )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return
    if not render_guard_active and fbp_render_mutation_blocked(include_guard=False):
        # Never write Object transforms for renders not owned by FBP's managed
        # interface-lock session. The last evaluated frame is safer than racing
        # viewport/depsgraph iteration.
        return
    try:
        _MOTION_HANDLER_GUARD = True
        refresh_all_motion(scene)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Motion frame update failed", exc)
    finally:
        _MOTION_HANDLER_GUARD = False


def _fbp_motion_deferred_load_refresh():
    clear_motion_runtime_caches()
    try:
        for scene in tuple(getattr(bpy.data, "scenes", ()) or ()):
            refresh_all_motion(scene)
    except FBP_DATA_ERRORS:
        pass
    return None


@persistent
def _fbp_motion_load_post(_dummy):
    # File-load callbacks run while Blender is still replacing Main. Background
    # render children evaluate Motion from the frame handler and need no initial
    # viewport transform refresh.
    clear_motion_runtime_caches()
    if bool(getattr(bpy.app, "background", False)):
        return
    try:
        from .safe_tasks import schedule_once
        schedule_once(
            "motion.load_refresh",
            _fbp_motion_deferred_load_refresh,
            first_interval=0.08,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def _fbp_motion_deferred_visibility_sync():
    global _MOTION_HELPER_PENDING_SIGNATURE, _MOTION_HELPER_VISIBILITY_TASK_PENDING
    global _MOTION_HELPER_LAST_SELECTION_CHECK
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return 0.20
    try:
        _MOTION_HELPER_LAST_SELECTION_CHECK = time.monotonic()
        _sync_motion_helper_visibility(getattr(bpy, "context", None))
    except FBP_DATA_ERRORS:
        pass
    finally:
        _MOTION_HELPER_PENDING_SIGNATURE = None
        _MOTION_HELPER_VISIBILITY_TASK_PENDING = False
    return None


@persistent
def _fbp_motion_depsgraph_update(scene, _depsgraph=None, *, updates=None):
    """Observe depsgraph changes and defer helper writes to Blender's idle loop.

    Rendered viewports can emit many depsgraph callbacks per frame although
    helper visibility depends only on selection. Limit Python selection scans
    to 20 Hz and coalesce one final deferred check so rapid clicks remain exact.
    """
    del _depsgraph
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return
    if updates is not None and not updates:
        return
    context = getattr(bpy, "context", None)
    if fbp_is_grease_pencil_interaction_mode(context):
        return
    if not _iter_scene_motion_targets(scene):
        return
    global _MOTION_HELPER_PENDING_SIGNATURE, _MOTION_HELPER_VISIBILITY_TASK_PENDING
    global _MOTION_HELPER_LAST_SELECTION_CHECK
    now = time.monotonic()
    elapsed = now - float(_MOTION_HELPER_LAST_SELECTION_CHECK or 0.0)
    if elapsed < _MOTION_HELPER_SELECTION_CHECK_INTERVAL:
        if not _MOTION_HELPER_VISIBILITY_TASK_PENDING:
            try:
                from .safe_tasks import schedule_once
                _MOTION_HELPER_VISIBILITY_TASK_PENDING = bool(schedule_once(
                    "motion.helper_visibility",
                    _fbp_motion_deferred_visibility_sync,
                    first_interval=max(0.01, _MOTION_HELPER_SELECTION_CHECK_INTERVAL - elapsed),
                ))
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                _MOTION_HELPER_VISIBILITY_TASK_PENDING = False
        return
    _MOTION_HELPER_LAST_SELECTION_CHECK = now
    signature = _motion_helper_selection_signature(getattr(bpy, "context", None))
    if (
        signature == _MOTION_HELPER_SELECTION_SIGNATURE
        or signature == _MOTION_HELPER_PENDING_SIGNATURE
    ):
        return
    _MOTION_HELPER_PENDING_SIGNATURE = signature
    try:
        from .safe_tasks import schedule_once
        task_key = "motion.helper_visibility"
        scheduled = schedule_once(
            task_key,
            _fbp_motion_deferred_visibility_sync,
            first_interval=0.04,
        )
        _MOTION_HELPER_VISIBILITY_TASK_PENDING = bool(scheduled)
        if not scheduled:
            _MOTION_HELPER_PENDING_SIGNATURE = None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        _MOTION_HELPER_PENDING_SIGNATURE = None
        _MOTION_HELPER_VISIBILITY_TASK_PENDING = False


def draw_motion_effect_ui(layout, context, target=None):
    """Draw Motion inside the normal effect settings container."""
    target = target or _motion_target_from_context(context)
    if target is None:
        return
    configure_layout(layout)
    target_kind = "Camera" if str(getattr(target, "type", "")) == "CAMERA" else "Layer"
    header = section_header(
        layout,
        f"Target · {getattr(target, 'name', 'Target')}",
        icon=fbp_icon("CAMERA_DATA") if target_kind == "Camera" else fbp_icon("EMPTY_ARROWS"),
        align=True,
    )
    header.operator("fbp.motion_capture_base", text="", icon="PIVOT_CURSOR")
    # Reuse the full tested editor without registering a permanent sidebar panel.
    FBP_PT_Motion.draw(_FBPMotionDrawProxy(layout, target), context)


def audit_motion_system(scene, *, repair=False):
    """Return non-destructive Motion diagnostics for Project Health."""
    issues = []
    warnings = []
    links = {}
    global_ids = set()
    stats = {
        "motion_targets": 0,
        "motion_instances": 0,
        "motion_shared_links": 0,
        "motion_shared_users": 0,
        "motion_paths": 0,
        "motion_springs": 0,
        "motion_repaired": 0,
    }
    try:
        objects = tuple(getattr(scene, "objects", ()) or ())
    except FBP_DATA_ERRORS:
        objects = ()
    for target in objects:
        try:
            items = tuple(target.fbp_motions)
        except FBP_DATA_ERRORS:
            continue
        if not items:
            continue
        stats["motion_targets"] += 1
        stats["motion_instances"] += len(items)
        if not bool(getattr(target, "fbp_motion_base_captured", False)):
            if repair and _capture_motion_base(target):
                stats["motion_repaired"] += 1
            else:
                issues.append(f"{target.name}: Motion stack has no captured base transform")
        for item in items:
            uid = str(getattr(item, "uid", "") or "")
            if not uid or uid in global_ids:
                if repair:
                    item.uid = uuid.uuid4().hex
                    stats["motion_repaired"] += 1
                else:
                    issues.append(f"{target.name}: Motion instance has a missing or duplicated ID")
            global_ids.add(str(getattr(item, "uid", "") or ""))
            preset = str(getattr(item, "preset", ""))
            if preset not in _PRESET_DEFAULTS:
                warnings.append(f"{target.name}: unsupported Motion preset {getattr(item, 'preset', '<unknown>')}")
            elif preset in {"FOLLOW_PATH", "FOLLOW_SPIRAL"}:
                stats["motion_paths"] += 1
                path_object = getattr(item, "path_object", None)
                if path_object is None or str(getattr(path_object, "type", "")) != "CURVE":
                    warnings.append(f"{target.name}: Follow Curve Motion has no valid Curve")
            elif preset == "SPRING_FOLLOW":
                stats["motion_springs"] += 1
                spring_target = getattr(item, "spring_target", None)
                if spring_target is None:
                    warnings.append(f"{target.name}: Follow Spring has no target")
                elif _same_rna(spring_target, target):
                    warnings.append(f"{target.name}: Follow Spring cannot target itself")
            link_id = str(getattr(item, "link_id", "") or "")
            if link_id:
                links.setdefault(link_id, []).append((target, item))

    for _link_id, users in links.items():
        stats["motion_shared_users"] += len(users)
        if len(users) < 2:
            if repair:
                users[0][1].link_id = ""
                users[0][1].share_seed = False
                users[0][1].slot = "LOCAL"
                stats["motion_repaired"] += 1
            else:
                warnings.append(f"{users[0][0].name}: shared Motion link has only one user")
            continue
        stats["motion_shared_links"] += 1
        source_target, source = users[0]
        for target, item in users[1:]:
            mismatch = any(
                not _motion_values_equal(getattr(item, key), getattr(source, key))
                for key in _SHARED_MOTION_PROPERTIES
            )
            if mismatch:
                if repair:
                    _copy_motion_values(source, item, include_local=False, include_seed=bool(source.share_seed))
                    evaluate_motion_target(target, scene)
                    stats["motion_repaired"] += 1
                else:
                    warnings.append(f"{target.name}: shared Motion settings differ from {source_target.name}")

    return {"issues": tuple(issues), "warnings": tuple(warnings), "stats": stats, "repaired": stats["motion_repaired"]}


_CLASSES = (
    FBP_PG_MotionItem,
    FBP_UL_MotionItems,
    FBP_OT_MotionSelectRow,
    FBP_OT_MotionAdd,
    FBP_OT_MotionCreateFollowHelper,
    FBP_OT_MotionRemove,
    FBP_OT_MotionDuplicate,
    FBP_OT_MotionMove,
    FBP_OT_MotionSetPreset,
    FBP_MT_MotionPreset,
    FBP_OT_MotionResetPreset,
    FBP_OT_MotionCaptureBase,
    FBP_OT_MotionCreatePivot,
    FBP_OT_MotionRandomizeSeed,
    FBP_OT_MotionLinkSelected,
    FBP_OT_MotionMakeLocal,
    FBP_OT_MotionSelectLinked,
    FBP_OT_MotionSyncLinked,
    FBP_OT_MotionDistribute,
    FBP_OT_MotionBake,
    FBP_MT_MotionListActions,
    FBP_MT_MotionAdd,
)

_MOTION_OBJECT_RNA_PROPS = (
    "fbp_motion_last_bake_report",
    "fbp_motion_base_scale",
    "fbp_motion_base_rotation",
    "fbp_motion_base_location",
    "fbp_motion_base_captured",
    "fbp_motion_master_enabled",
    "fbp_motion_active_index",
    "fbp_motions",
)


def _safe_remove_motion_object_rna():
    return unregister_type_properties(bpy.types.Object, _MOTION_OBJECT_RNA_PROPS)


def _prepare_motion_registration():
    # Blender can keep old RNA classes alive after an in-place reinstall or a
    # failed registration. Remove owned RNA and stale FBP class generations
    # through the shared transactional lifecycle helpers.
    _safe_remove_motion_object_rna()
    unregister_classes(_CLASSES)

def register():
    _prepare_motion_registration()
    registered = []
    is_background = bool(getattr(bpy.app, "background", False))
    classes_to_register = (FBP_PG_MotionItem,) if is_background else _CLASSES
    try:
        # Background rendering needs the PropertyGroup schema to deserialize
        # motion stacks, but none of the UI lists, menus or authoring operators.
        registered.extend(register_classes(classes_to_register))

        bpy.types.Object.fbp_motions = CollectionProperty(description='Internal collection of Motions entries managed by Frame By Plane. Edit it through the visible UI actions instead of manual data changes.', type=FBP_PG_MotionItem)
        bpy.types.Object.fbp_motion_active_index = IntProperty(description='Zero-based item index used internally to target the selected row, frame, effect, preset or setup entry.', name="Active Motion", default=0, min=0)
        bpy.types.Object.fbp_motion_master_enabled = BoolProperty(description='Toggle this option for the current Motion system. Disabled keeps the data available but prevents this behavior from being applied.', name="Enable Motion", default=True, update=_motion_master_update)
        bpy.types.Object.fbp_motion_base_captured = BoolProperty(description='Toggle this option for the current Motion system. Disabled keeps the data available but prevents this behavior from being applied.', name="Motion Base Captured", default=False, options={"HIDDEN"})
        bpy.types.Object.fbp_motion_base_location = FloatVectorProperty(description='Vector value for Motion Base Location. Used for positions, colors or grouped numeric controls in the current Motion system.', name="Motion Base Position", size=3, default=(0.0, 0.0, 0.0), options={"HIDDEN"})
        bpy.types.Object.fbp_motion_base_rotation = FloatVectorProperty(description='Rotation angle used by the effect or helper. Example: rotate bands, hatch lines, gradients or directional sampling.', name="Motion Base Rotation", size=3, subtype="EULER", unit="ROTATION", default=(0.0, 0.0, 0.0), options={"HIDDEN"})
        bpy.types.Object.fbp_motion_base_scale = FloatVectorProperty(description='Size control for the generated result. Higher values increase visual coverage and may increase viewport cost.', name="Motion Base Scale", size=3, default=(1.0, 1.0, 1.0), options={"HIDDEN"})
        bpy.types.Object.fbp_motion_last_bake_report = StringProperty(description='Motion Last Bake Report value used by the current Motion system. Changes are applied only to compatible Frame By Plane data.', name="Motion Bake Report", default="")

        _remove_motion_handler(bpy.app.handlers.frame_change_post, "_fbp_motion_frame_change")
        _remove_motion_handler(bpy.app.handlers.load_post, "_fbp_motion_load_post")
        _remove_motion_handler(bpy.app.handlers.depsgraph_update_post, "_fbp_motion_depsgraph_update")
        if not append_handler_once(
            bpy.app.handlers.frame_change_post,
            _fbp_motion_frame_change,
            module_suffix="motion_runtime",
        ):
            raise RuntimeError("Could not register the Motion frame handler")
        if not is_background and not append_handler_once(
            bpy.app.handlers.load_post,
            _fbp_motion_load_post,
            module_suffix="motion_runtime",
        ):
            raise RuntimeError("Could not register the Motion load handler")
        # The Scene Sync dispatcher observes selection changes through one
        # shared depsgraph callback instead of registering another post-handler.
    except Exception:
        _remove_motion_handler(bpy.app.handlers.depsgraph_update_post, "_fbp_motion_depsgraph_update")
        _remove_motion_handler(bpy.app.handlers.load_post, "_fbp_motion_load_post")
        _remove_motion_handler(bpy.app.handlers.frame_change_post, "_fbp_motion_frame_change")
        _safe_remove_motion_object_rna()
        unregister_classes(registered)
        raise


def unregister():
    try:
        from .safe_tasks import cancel_scheduled_prefixes
        cancel_scheduled_prefixes("motion.load_refresh")
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    _remove_motion_handler(bpy.app.handlers.depsgraph_update_post, "_fbp_motion_depsgraph_update")
    _remove_motion_handler(bpy.app.handlers.load_post, "_fbp_motion_load_post")
    _remove_motion_handler(bpy.app.handlers.frame_change_post, "_fbp_motion_frame_change")

    if not bool(getattr(bpy.app, "background", False)):
        try:
            objects = getattr(getattr(bpy, "data", None), "objects", None)
            for target in tuple(objects or ()):
                if _target_has_motion(target):
                    _restore_motion_base(target, clear=False)
        except FBP_DATA_ERRORS:
            pass

    _safe_remove_motion_object_rna()
    unregister_classes(_CLASSES)


__all__ = (
    "SERVICE_ID",
    "SERVICE_API_VERSION",
    "CAPABILITIES",
    "MOTION_PRESET_ITEMS",
    "MOTION_SLOT_ITEMS",
    "MOTION_STAGGER_ITEMS",
    "MOTION_FALLOFF_ITEMS",
    "service_status",
    "motion_bake_frames",
    "motion_bake_conflicts",
    "bake_motion_to_keyframes",
    "evaluate_motion_item",
    "combine_motion_items",
    "motion_distribution_values",
    "evaluate_motion_target",
    "clear_motion_runtime_caches",
    "refresh_all_motion",
    "apply_motion_preset_defaults",
    "audit_motion_system",
    "motion_effect_active",
    "remove_motion_effect",
    "draw_motion_effect_ui",
)
