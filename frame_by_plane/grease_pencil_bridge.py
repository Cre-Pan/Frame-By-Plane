"""Grease Pencil 5.2 canvas and raster-mask bridge for Frame By Plane.

GP Mask v2 hard-reset: Grease Pencil geometry is read as vector input and baked
to a soft SDF image mask.  The Boolean/vector-cutter path is intentionally
removed from the live workflow; Fill, Line, Fill+Line, per-point radius,
Expand/Contract, Blur and live drawing preview are the supported contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import time
from bisect import bisect_right
from array import array
from collections import OrderedDict

import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, Menu
from mathutils import Matrix, Vector

from .ui_list_state import invoke_with_selection_modifiers, transient_get, transient_set
from .runtime import (
    FBP_DATA_ERRORS,
    fbp_is_silent_property_update,
    fbp_undo_guard_active,
    fbp_main_data_collection,
    fbp_main_data_ready,
    fbp_find_id_by_runtime_key,
    fbp_obj_runtime_key,
    fbp_obj_runtime_token,
    fbp_depsgraph_quiet_for,
    fbp_render_mutation_blocked,
    fbp_runtime_set,
    fbp_set_rna_property_silent,
    fbp_warn,
    fbp_warn_once,
    fbp_capture_runtime_targets as _gp_capture_runtime_targets
)
from .layers import (
    fbp_layer_depth_value_from_cache,
    fbp_make_depth_context_cache,
    fbp_resolve_rig_from_any_object,
    get_or_create_child_collection,
    get_primary_fbp_collection,
    get_selected_fbp_roots,
    is_fbp_layer_object,
    move_object_to_collection,
    object_in_view_layer,
)
from .identifiers import (
    assign_stable_id,
    ensure_layer_identity,
    ensure_mask_identity,
    new_stable_id,
    stable_id,
)
from .ownership import tag_managed
from .safe_tasks import cancel_scheduled_prefixes, schedule_once, scheduled_task_pending
from .gp_runtime_state import GP_TASK_PREFIXES, clear_runtime_collections
from .registration import (
    append_handler_once,
    register_classes,
    remove_handlers_by_name,
    unregister_classes,
    unregister_type_properties,
)
from .service_registry import call_service, service_descriptor
from .shortcut_runtime import (
    addon_keymap,
    alt_shortcut_label,
    refresh_keymap_registration,
    native_keymap_names,
    remove_matching_keymap_items,
    shortcut_enabled,
    unregister_keymap_items,
)
from .fbp_index import invalidate_scene_index, iter_scene_fbp_rigs, iter_scene_gp_canvases, scene_has_gp_canvas
from .effects_registry import GP_MASK_EFFECT_IDS
from .node_sockets import node_input, socket_is_available

from .ui_icons import ui_icon, ui_icon_kwargs, ui_label_icon_kwargs
from .ui_style import adaptive_row, configure_layout, empty_state, hint_row, section_gap, section_header


SERVICE_ID = "grease_pencil_bridge"
SERVICE_API_VERSION = 1
CAPABILITIES = ("CANVAS", "MASK", "TIMING", "CONVERSION")
FBP_GP_SCHEMA_VERSION = 1


class _FBPLayoutProxy:
    """Minimal reusable panel proxy for embedded draw calls."""

    __slots__ = ("layout",)

    def __init__(self, layout):
        self.layout = layout

KEY_IS_CANVAS = "fbp_is_gp_canvas"
KEY_OWNER_ID = "fbp_gp_owner_id"
KEY_OWNER_NAME = "fbp_gp_owner_name"
KEY_SCHEMA = "fbp_gp_schema"
KEY_MASK_IMAGE_NAME = "fbp_gp_mask_image_name"
KEY_MASK_SIGNATURE = "fbp_gp_mask_signature"
KEY_MASK_FRAME = "fbp_gp_mask_frame"
KEY_MASK_DIRTY = "fbp_gp_mask_dirty"
KEY_MASK_BAKED = "fbp_gp_mask_baked"
KEY_MASK_FRAME_SENSITIVE = "fbp_gp_mask_frame_sensitive"
KEY_MASK_GEOMETRY_DIRTY = "fbp_gp_mask_geometry_dirty"
KEY_MASK_GEOMETRY_FRAME_SENSITIVE = "fbp_gp_mask_geometry_frame_sensitive"
KEY_IS_MASK_IMAGE = "fbp_is_gp_mask_image"
KEY_REFERENCE_OPACITY = "fbp_gp_reference_original_opacity"
KEY_LAST_ATTACHMENT = "fbp_gp_last_attachment"
KEY_PLANE_DISTANCE = "fbp_gp_plane_distance"
KEY_CAMERA_DISTANCE = "fbp_gp_camera_distance"
KEY_CANVAS_KIND = "fbp_gp_canvas_kind"
KEY_GP_NATIVE_EFFECT_ID = "fbp_gp_native_effect_id"
KEY_GP_NATIVE_EFFECT_OPEN = "fbp_gp_native_effect_open"
KEY_CANVAS_SOLO = "fbp_gp_canvas_solo"
KEY_CANVAS_CLIPPING = "fbp_gp_canvas_clipping"
KEY_CYCLES_PROXY = "fbp_gp_cycles_proxy"
KEY_CYCLES_PROXY_SOURCE = "fbp_gp_cycles_proxy_source"
KEY_CYCLES_PROXY_SIGNATURE = "fbp_gp_cycles_proxy_signature"
KEY_CYCLES_MATERIAL_CONTRACT = "fbp_gp_cycles_material_contract"
GP_CYCLES_MATERIAL_CONTRACT = 2
GP_CYCLES_PROXY_CONTRACT = 3
COLLECTION_NAME = "FBP Grease Pencil"
CYCLES_PROXY_COLLECTION_NAME = "FBP Grease Pencil Render"

CANVAS_KIND_ITEMS = (
    ("DRAWING", "Drawing Plane", "Editable Grease Pencil layer that behaves like a Frame By Plane layer"),
    ("MASK", "Mask", "Internal Grease Pencil matte used only by mask effects"),
)

ATTACHMENT_ITEMS = (
    ("PLANE", "Follow Plane", "Keep the canvas aligned to the selected Frame By Plane image plane"),
    ("CAMERA", "Follow Camera", "Attach the canvas to the active camera as a camera-facing drawing surface"),
    ("WORLD", "World Space", "Keep the current world transform and detach the canvas from generated parents"),
)
MASK_SOURCE_ITEMS = (
    ("AUTO", "Automatic", "Detect visible fill and line geometry from each Grease Pencil stroke"),
    ("FILL", "Fill", "Use Blender 5.2 Grease Pencil fill regions identified by their native fill group"),
    ("STROKE", "Line", "Use visible Grease Pencil linework and its detected point radius"),
    ("BOTH", "Fill + Line", "Combine native Grease Pencil fill groups and visible linework"),
)
DEFAULT_GP_MASK_STROKE_WIDTH = 0.002
DEFAULT_GP_MASK_EXPAND = 0.002
DEFAULT_GP_MASK_QUALITY = "1024"
DEFAULT_GP_MASK_PREVIEW_QUALITY = "256"

QUALITY_ITEMS = (
    ("128", "Low · 128", "Fast preview mask"),
    ("256", "Medium · 256", "Balanced preview mask"),
    ("512", "High · 512", "Detailed preview mask"),
    ("1024", "Render · 1024", "High-resolution mask; slower to update"),
)
PREVIEW_QUALITY_ITEMS = (
    ("128", "Low", "Low live preview while drawing · 128 px"),
    ("256", "Medium", "Medium live preview while drawing · 256 px"),
    ("512", "High", "High live preview while drawing · 512 px"),
)
REVEAL_MODE_ITEMS = (
    ("REVEAL", "Reveal", "Progressively reveal the Grease Pencil mask"),
    ("ERASE", "Erase", "Progressively erase the Grease Pencil mask"),
)
REVEAL_DIRECTION_ITEMS = (
    ("LEFT_RIGHT", "Left to Right", "Reveal from the left edge to the right edge"),
    ("RIGHT_LEFT", "Right to Left", "Reveal from the right edge to the left edge"),
    ("BOTTOM_TOP", "Bottom to Top", "Reveal from the bottom edge to the top edge"),
    ("TOP_BOTTOM", "Top to Bottom", "Reveal from the top edge to the bottom edge"),
    ("RADIAL", "Radial", "Reveal outward from the centre of the plane"),
)

# Effects with a true Blender Grease Pencil backend in 5.2. Image-only
# Frame By Plane effects remain visible in the UI but disabled until a native or
# geometry-based equivalent is implemented.
GP_NATIVE_EFFECTS = (
    # Resolve the first Blender 5.2 native type supported by the active
    # modifier/effect collection.
    ("PIXELATE", "Pixelate", "ALIASED", "SHADER_FX", ("FX_PIXEL", "FX_PIXELATE")),
    ("RIM", "Rim", "MOD_OUTLINE", "SHADER_FX", ("FX_RIM", "FX_RIM_LIGHT")),
    ("SHADOW", "Shadow", "MOD_OPACITY", "SHADER_FX", ("FX_SHADOW",)),
    ("SWIRL", "Swirl", "FORCE_VORTEX", "SHADER_FX", ("FX_SWIRL",)),
    ("WAVE_WARP", "Wave", "MOD_WAVE", "SHADER_FX", ("FX_WAVE", "FX_WAVE_DISTORTION")),
    ("GAUSSIAN_BLUR", "Blur", "ONIONSKIN_ON", "SHADER_FX", ("FX_BLUR", "FX_GAUSSIAN_BLUR")),
    ("GP_GLOW", "Glow", "LIGHT_SUN", "SHADER_FX", ("FX_GLOW", "FX_BLOOM")),
    ("GP_COLORIZE", "Colorize", "COLOR", "SHADER_FX", ("FX_COLORIZE", "FX_COLOR")),
    ("GP_OPACITY", "Opacity", "MOD_OPACITY", "MODIFIER", ("GREASE_PENCIL_OPACITY", "GP_OPACITY")),
    ("GP_FLIP", "Flip", "ARROW_LEFTRIGHT", "SHADER_FX", ("FX_FLIP",)),
    ("GP_NOISE", "Noise", "MOD_NOISE", "MODIFIER", ("GREASE_PENCIL_NOISE", "GP_NOISE")),
    ("GP_SMOOTH", "Smooth", "MOD_SMOOTH", "MODIFIER", ("GREASE_PENCIL_SMOOTH", "GP_SMOOTH")),
    ("HUE_SATURATION", "Hue / Saturation", "COLOR", "MODIFIER", ("GREASE_PENCIL_COLOR", "GP_COLOR")),
    ("RECOLOR", "Tint", "MOD_TINT", "MODIFIER", ("GREASE_PENCIL_TINT", "GP_TINT")),
    ("THICKNESS", "Thickness", "MOD_THICKNESS", "MODIFIER", ("GREASE_PENCIL_THICKNESS", "GP_THICK", "GP_THICKNESS")),
    ("CUTOUT_OUTLINE", "Outline", "MOD_OUTLINE", "MODIFIER", ("GREASE_PENCIL_OUTLINE", "GP_OUTLINE")),
    ("GP_ARRAY", "Array", "MOD_ARRAY", "MODIFIER", ("GREASE_PENCIL_ARRAY", "GP_ARRAY")),
    ("GP_BUILD", "Build", "MODIFIER", "MODIFIER", ("GREASE_PENCIL_BUILD", "GP_BUILD")),
    ("GP_DASH", "Dash", "MOD_DASH", "MODIFIER", ("GREASE_PENCIL_DASH", "GP_DASH")),
    ("GP_ENVELOPE", "Envelope", "MODIFIER", "MODIFIER", ("GREASE_PENCIL_ENVELOPE", "GP_ENVELOPE")),
    ("GP_LENGTH", "Length", "MODIFIER", "MODIFIER", ("GREASE_PENCIL_LENGTH", "GP_LENGTH")),
    ("GP_MIRROR", "Mirror", "MOD_MIRROR", "MODIFIER", ("GREASE_PENCIL_MIRROR", "GP_MIRROR")),
    ("GP_OFFSET", "Offset", "MODIFIER", "MODIFIER", ("GREASE_PENCIL_OFFSET", "GP_OFFSET")),
    ("GP_SIMPLIFY", "Simplify", "MOD_DECIM", "MODIFIER", ("GREASE_PENCIL_SIMPLIFY", "GP_SIMPLIFY")),
    ("GP_TEXTURE", "Texture Mapping", "TEXTURE", "MODIFIER", ("GREASE_PENCIL_TEXTURE", "GP_TEXTURE")),
    ("GP_TIME_OFFSET", "Time Offset", "TIME", "MODIFIER", ("GREASE_PENCIL_TIME", "GREASE_PENCIL_TIME_OFFSET", "GP_TIME", "GP_TIME_OFFSET")),
    # Native Blender Grease Pencil Shrinkwrap is the reliable GP equivalent of
    # Frame By Plane Surface Conform. The linked source plane is assigned as the
    # default target when available.
    ("SURFACE_CONFORM", "Surface Conform", "MOD_SHRINKWRAP", "MODIFIER", ("GREASE_PENCIL_SHRINKWRAP", "GP_SHRINKWRAP")),
)
GP_EFFECT_NAME_PREFIX = "FBP GP • "
_GP_NATIVE_EFFECT_DEFINITIONS = {item[0]: item for item in GP_NATIVE_EFFECTS}
_GP_NATIVE_EFFECTS_BY_BACKEND = {
    backend: tuple(item for item in GP_NATIVE_EFFECTS if item[3] == backend)
    for backend in tuple(dict.fromkeys(item[3] for item in GP_NATIVE_EFFECTS))
}
_GP_NATIVE_BACKENDS = tuple(_GP_NATIVE_EFFECTS_BY_BACKEND.keys())
# Library groups are UI-only. They keep the Modifiers panel readable while all
# effects still bind to the real Blender Shader Effect / Modifier stacks.
_GP_NATIVE_EFFECT_LIBRARY_GROUPS = (
    ("Stylize", "SHADING_TEXTURE", ("PIXELATE", "GAUSSIAN_BLUR", "GP_GLOW", "GP_COLORIZE", "GP_OPACITY", "HUE_SATURATION", "RECOLOR")),
    ("Light & Edge", "LIGHT_SUN", ("RIM", "SHADOW", "CUTOUT_OUTLINE")),
    ("Warp", "MOD_WARP", ("SWIRL", "WAVE_WARP", "GP_NOISE", "GP_SMOOTH")),
    ("Stroke", "OUTLINER_OB_GREASEPENCIL", ("THICKNESS", "GP_DASH", "GP_LENGTH", "GP_ENVELOPE", "GP_SIMPLIFY", "GP_TEXTURE")),
    ("Motion & Build", "TIME", ("GP_BUILD", "GP_TIME_OFFSET", "GP_OFFSET")),
    ("Utility", "MODIFIER", ("GP_ARRAY", "GP_MIRROR", "GP_FLIP")),
    ("Surface", "MOD_SHRINKWRAP", ("SURFACE_CONFORM",)),
)
_GP_UNAVAILABLE_EFFECTS_CACHE = None
_GP_NATIVE_TYPE_SUPPORT_CACHE = {}
_GP_NATIVE_ATTR_RESOLVE_CACHE = {}
_GP_OWNER_ID_LOOKUP_CACHE = None
_GP_OBJECT_TYPES = frozenset({"GREASEPENCIL"})
_GP_NATIVE_ATTR_ALIASES = {
    "size": ("size", "pixel_size", "radius"),
    "use_antialiasing": ("use_antialiasing", "use_antialias", "antialiasing"),
    "rim_color": ("rim_color", "color", "outline_color"),
    "shadow_color": ("shadow_color", "color"),
    "offset": ("offset", "location", "translation"),
    "blur": ("blur", "blur_size", "radius"),
    "angle": ("angle", "rotation"),
    "amplitude": ("amplitude", "strength"),
    "period": ("period", "wavelength", "scale"),
    "phase": ("phase", "offset_time"),
    "factor": ("factor", "strength", "influence"),
    "factor_strength": ("factor_strength", "factor_opacity", "opacity_factor"),
    "factor_thickness": ("factor_thickness", "thickness_factor"),
    "noise_scale": ("noise_scale", "scale", "noise_size"),
    "step": ("step", "steps", "iterations"),
    "value": ("value", "brightness"),
    "color_mode": ("color_mode", "mode", "target"),
    "thickness_factor": ("thickness_factor", "factor", "thickness"),
    "use_uniform_thickness": ("use_uniform_thickness", "use_uniform", "uniform"),
    "sample_length": ("sample_length", "sample_length_factor", "sample_distance"),
    "use_keep_shape": ("use_keep_shape", "keep_shape"),
    "glow_color": ("glow_color", "color", "select_color"),
    "low_color": ("low_color", "low", "color", "secondary_color"),
    "high_color": ("high_color", "high", "color", "primary_color"),
    "threshold": ("threshold", "limit", "alpha_threshold"),
    "intensity": ("intensity", "strength", "factor"),
    "flip_horizontal": ("use_flip_x", "flip_x", "use_axis_x", "x_axis"),
    "flip_vertical": ("use_flip_y", "flip_y", "use_axis_y", "y_axis"),
    "count": ("count", "duplicates", "repeat"),
    "relative_offset": ("relative_offset", "relative_offset_factor", "offset", "constant_offset", "constant_offset_displace"),
    "use_object_offset": ("use_object_offset", "use_object", "object_offset", "use_offset_object"),
    "start_frame": ("start_frame", "frame_start", "start", "frame_start_offset"),
    "end_frame": ("end_frame", "frame_end", "end", "frame_end_offset"),
    "transition": ("transition", "transition_type", "mode", "build_mode"),
    "dash_offset": ("dash_offset", "offset", "segment_offset"),
    "dash_length": ("dash_length", "length", "segment_length", "dash"),
    "gap_length": ("gap_length", "gap", "space_length"),
    "spread": ("spread", "thickness", "radius", "distance"),
    "skip": ("skip", "step"),
    "start_factor": ("start_factor", "start", "factor_start", "percentage_start"),
    "end_factor": ("end_factor", "end", "factor_end", "percentage_end"),
    "mirror_object": ("object", "mirror_object", "target"),
    "use_axis_x": ("use_axis_x", "use_x", "x_axis"),
    "use_axis_y": ("use_axis_y", "use_y", "y_axis"),
    "use_axis_z": ("use_axis_z", "use_z", "z_axis"),
    "offset_location": ("location", "offset", "offset_location"),
    "offset_rotation": ("rotation", "rotation_euler", "offset_rotation"),
    "offset_scale": ("scale", "offset_scale", "offset_scale_factor"),
    "simplify_mode": ("mode", "simplify_mode", "type"),
    "distance": ("distance", "factor", "threshold"),
    "uv_offset": ("uv_offset", "offset", "translation"),
    "uv_scale": ("uv_scale", "scale", "factor"),
    "uv_rotation": ("uv_rotation", "rotation"),
    "frame_offset": ("frame_offset", "offset", "frame_shift", "frame"),
    "frame_scale": ("frame_scale", "scale", "speed", "speed_factor"),
    "use_custom_frame_range": ("use_custom_frame_range", "use_frame_range"),
    "target": ("target", "object", "target_object"),
    "wrap_method": ("wrap_method", "shrinkwrap_type", "method"),
    "wrap_mode": ("wrap_mode", "wrap_mode_type", "snap_mode"),
    "surface_offset": ("offset", "distance", "surface_offset"),
}


def _clear_gp_native_effect_ui_cache():
    """Clear lightweight GP native-effect UI caches."""
    global _GP_UNAVAILABLE_EFFECTS_CACHE
    _GP_UNAVAILABLE_EFFECTS_CACHE = None
    _GP_NATIVE_TYPE_SUPPORT_CACHE.clear()
    _GP_NATIVE_ATTR_RESOLVE_CACHE.clear()


def _gp_native_effect_definitions():
    """Return GP native effect definitions keyed by Frame By Plane effect ID."""
    return _GP_NATIVE_EFFECT_DEFINITIONS


_RNA_PROPERTIES = (
    "fbp_gp_canvas_owner",
    "fbp_gp_canvas",
    "fbp_gp_canvas_kind",
    "fbp_gp_attachment_mode",
    "fbp_gp_canvas_distance",
    "fbp_gp_canvas_offset_x",
    "fbp_gp_canvas_offset_y",
    "fbp_gp_canvas_scale",
    "fbp_gp_canvas_visible",
    "fbp_gp_canvas_selected",
    "fbp_gp_canvas_locked",
    "fbp_gp_canvas_opacity",
    "fbp_gp_ui_show_ink",
    "fbp_gp_ui_show_timing",
    "fbp_gp_ui_show_loop",
    "fbp_gp_ui_show_advanced",
    "fbp_gp_ui_show_workflow",
    "fbp_gp_ui_show_unavailable_effects",
    "fbp_gp_ui_show_effect_library",
    "fbp_gp_ui_show_effect_settings",
    "fbp_gp_ui_show_material_52",
    "fbp_gp_canvas_render",
    "fbp_gp_cycles_proxy",
    "fbp_gp_canvas_lock_transform",
    "fbp_gp_onion_skin",
    "fbp_gp_reference_opacity",
    "fbp_gp_mask_source",
    "fbp_gp_mask_invert",
    "fbp_gp_mask_feather",
    "fbp_gp_mask_expand",
    "fbp_gp_mask_opacity",
    "fbp_gp_mask_threshold",
    "fbp_gp_mask_stroke_width",
    "fbp_gp_mask_auto_radius",
    "fbp_gp_mask_quality",
    "fbp_gp_mask_preview_quality",
    "fbp_gp_reveal_enabled",
    "fbp_gp_reveal_mode",
    "fbp_gp_reveal_start",
    "fbp_gp_reveal_end",
    "fbp_gp_reveal_direction",
    "fbp_gp_reveal_invert",
    "fbp_gp_reveal_feather",
    "fbp_gp_reveal_hold",
    "fbp_gp_mask_image",
    "fbp_imported_mask_image",
    "fbp_imported_mask_source_type",
    "fbp_gp_mask_canvas",
    "fbp_gp_mask_slot_2_canvas", "fbp_gp_mask_slot_3_canvas", "fbp_gp_mask_slot_4_canvas",
    "fbp_gp_mask_slot_2_image", "fbp_gp_mask_slot_3_image", "fbp_gp_mask_slot_4_image",
    "fbp_gp_mask_slot_2_source_type", "fbp_gp_mask_slot_3_source_type", "fbp_gp_mask_slot_4_source_type",
)


# Process-local indexes keep hot mask/depsgraph paths independent from the
# total number of objects in the .blend. Blender Object names are deliberately
# not used as keys: artists may rename canvases and mask helpers at any time.
# Runtime indexes retain primitive identities only. Blender RNA wrappers can
# become invalid after deletion, Undo or Main-database replacement; every use
# resolves a fresh datablock from bpy.data at the last responsible moment.
_GP_BINDING_INDEX = None
_GP_DRAWING_OWNER_INDEX = None
_GP_CANVAS_REGISTRY = {}  # canvas identity -> latest known object name
_GP_DATA_CANVAS_INDEX = {}  # GP-data identity -> {canvas identity: object name}
_GP_CANVAS_DATA_POINTERS = {}
# Depsgraph handlers collect primitive flags only. Blender 5.2 may still be
# rebuilding GP CurvesGeometry, materials and image buffers when those handlers
# run, so every RNA write is published later from the shared safe-task loop.
# Depsgraph payloads are valid only for the Main database generation that
# produced them; never inherit them across extension reloads.
_GP_PENDING_DEPSGRAPH_EVENTS = {}
# Tri-state cache: missing means not sampled yet; True/False are the latest safe extraction result.
_GP_MASK_GEOMETRY_STATE = {}
# Extraction telemetry is diagnostic-only and must never write Blender ID
# properties on every live mask sample. Keeping it process-local avoids
# depsgraph/RNA churn and prevents temporary counters from bloating .blend data.
_GP_MASK_DEBUG_STATE = {}
_FRAME_SENSITIVE_MASKS = {}
_GP_FRAME_SENSITIVITY_CACHE = {}
_GP_CANVAS_ID_INDEX = {}  # stable mask id -> canvas identity
_GP_DEPENDENCY_CANVAS_INDEX = {}  # dependency identity -> {canvas identity: object name}
_GP_CANVAS_DEPENDENCY_POINTERS = {}
_GP_CYCLES_RENDER_BACKUP = {}
# Per-canvas/per-scene camera fingerprints let depsgraph updates distinguish a
# real camera reassignment from ordinary Scene updates such as frame changes.
_GP_SCENE_CAMERA_STATE = {}
_GP_GEOMETRY_CACHE = OrderedDict()
_GP_GEOMETRY_CACHE_BYTES = 0
_GP_GEOMETRY_CACHE_MAX_BYTES = 48 * 1024 * 1024
_GP_GEOMETRY_CACHE_MAX_ENTRIES = 72
_GP_DISTANCE_CACHE = OrderedDict()
_GP_DISTANCE_CACHE_BYTES = 0
_GP_DISTANCE_CACHE_MAX_BYTES = 48 * 1024 * 1024
_GP_DISTANCE_CACHE_MAX_ENTRIES = 48
# Exposure indexes turn timeline lookup from a linear frame scan into a binary
# search. They are transient and invalidated whenever Grease Pencil data changes.
_GP_EXPOSURE_INDEX = {}
_GP_FRAME_STATE = {}
# Geometry generation lets edit-mode updates invalidate caches lazily. Clearing
# large OrderedDict caches inside depsgraph callbacks can stutter while drawing;
# generation keys make stale entries unreachable and let LRU cleanup retire them.
_GP_GEOMETRY_GENERATION = {}
_GP_MASK_DIRTY_TIME = {}
_GP_MASK_IMAGE_RETIRED_AT = globals().get("_GP_MASK_IMAGE_RETIRED_AT", {})
if not isinstance(_GP_MASK_IMAGE_RETIRED_AT, dict):
    _GP_MASK_IMAGE_RETIRED_AT = {}
_GP_MASK_IMAGE_REUSE_DELAY = 4.0
_GP_MASK_IMAGE_RETIRED_MAX_AGE = 60.0
_GP_MASK_IMAGE_RETIRED_MAX_ENTRIES = 96
_GP_MASK_FIRST_DIRTY_TIME = {}
_GP_MASK_IMMEDIATE_KEYS = set()
# During native GP structural edits Frame By Plane records only process-local
# keys. A quiet-time timer may sample the published result at preview quality;
# the full-quality rebuild still happens after leaving Edit Mode.
_GP_MASK_STRUCTURAL_EDIT_PENDING = set()
_GP_MASK_STRUCTURAL_EDIT_LAST = {}
_GP_MASK_STROKE_COUNT_SIGNATURE = {}
_GP_MASK_LIVE_QUIET_SECONDS = 0.045
_GP_MASK_IDLE_QUIET_SECONDS = 0.025
_GP_MASK_EDIT_DEFER_SECONDS = 0.12
# Blender 5.2 can invalidate GP drawing data while Edit Mode is rebuilding
# draw batches. Ordinary refresh paths remain blocked; only the deduplicated
# quiet-time preview may sample a settled edit result at capped resolution.
_GP_MASK_EDIT_POLL_SECONDS = 0.08
_GP_MASK_MAX_DEBOUNCE_SECONDS = 0.36
_GP_MASK_LIVE_FINALIZE_DELAY_SECONDS = 0.30
_GP_MASK_LIVE_POLL_IDLE_STOP_SECONDS = 0.55
# Large drawings need a lower live-raster cadence to keep the native GP brush
# responsive. Final quality remains unchanged and is rebuilt after the stroke.
_GP_MASK_LIVE_HEAVY_POINT_THRESHOLD = 2500
_GP_MASK_LIVE_VERY_HEAVY_POINT_THRESHOLD = 8000
_GP_MASK_LIVE_FINALIZE_KEYS = {}
_GP_MASK_LIVE_POLL_KEYS = {}
_GP_MASK_LIVE_POLL_SIGNATURES = {}
# Paint-mode authoring snapshot. Blender can commit a new GP curve a few ticks
# after the stylus stroke; if the artist changes brush size immediately, reading
# only the current brush assigns the new size to the previous curve. Keep the
# brush state observed while point geometry was growing and consume it when the
# curve count finally increases. Process-local only; never touched in Edit Mode.
# Short process-local guard around GP mode transitions. Blender 5.2 can
# rebuild/free GPv3 GPU batches immediately after leaving Paint Mode and while
# entering Edit Mode. During this window we keep Frame By Plane timers quiet and
# avoid all mask image refreshes.
_GP_MASK_MODE_TRANSITION_GUARD = {}
_GP_MASK_MODE_TRANSITION_SECONDS = 1.20
_GP_MASK_EDIT_ENTRY_GUARD_SECONDS = 0.45
_GP_MASK_EDIT_KEYMAPS = []
# Cursor drawing is Blender's native way to match an arbitrarily rotated GP
# plane. Preserve the artist's cursor in process memory and restore it when the
# FBP Draw session ends.
_GP_DRAW_CURSOR_STATE = {}
KEY_MASK_FORCE_FULL_QUALITY_ONCE = "fbp_gp_mask_force_full_quality_once"
# Output-only caches are shared between masks because their content depends only
# on resolution/direction, never on a Blender datablock.
_GP_REVEAL_POSITION_CACHE = OrderedDict()
_GP_REVEAL_POSITION_CACHE_BYTES = 0
_GP_REVEAL_POSITION_CACHE_MAX_BYTES = 32 * 1024 * 1024
_GP_REVEAL_POSITION_CACHE_MAX_ENTRIES = 18
_GP_RGBA_BUFFER_CACHE = OrderedDict()
_GP_RGBA_BUFFER_CACHE_BYTES = 0
_GP_RGBA_BUFFER_CACHE_MAX_BYTES = 32 * 1024 * 1024
_GP_RGBA_BUFFER_CACHE_MAX_ENTRIES = 6


def _original_datablock(datablock):
    """Resolve evaluated Blender IDs to their editable original datablock."""
    if datablock is None:
        return None
    try:
        original = getattr(datablock, "original", None)
        return original if original is not None else datablock
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return datablock


def _runtime_int_identity(value):
    """Return one integer identity without retaining an RNA wrapper.

    Blender 5.2 ID datablocks expose ``session_uid`` specifically for runtime
    identity.  Pointer addresses can be reused after Undo, deletion or Main
    replacement, which previously allowed an old GP-mask cache entry to match a
    newly allocated Object/Image/Scene.  Non-ID GP sub-data such as Layers and
    Drawings still use their RNA address because they do not expose session_uid.
    """
    value = _original_datablock(value)
    if value is None:
        return 0
    try:
        session_uid = int(getattr(value, "session_uid", 0) or 0)
        if session_uid > 0:
            return -session_uid
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        return int(value.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0


def _canvas_pointer(canvas):
    return _runtime_int_identity(canvas)


def _data_pointer(data):
    return _runtime_int_identity(data)


def _invalidate_gp_binding_cache():
    global _GP_BINDING_INDEX
    _GP_BINDING_INDEX = None


def _invalidate_gp_owner_cache():
    global _GP_DRAWING_OWNER_INDEX, _GP_OWNER_ID_LOOKUP_CACHE
    _GP_DRAWING_OWNER_INDEX = None
    _GP_OWNER_ID_LOOKUP_CACHE = None


def _gp_owner_lookup_by_id(owner_id):
    """Resolve an FBP owner by stable id using one session cache.

    Several GP UI paths ask for canvas ownership while drawing every row.
    Without this cache each unresolved canvas can trigger a full bpy.data.objects
    scan. The cache is invalidated by the existing owner-cache invalidation path.
    """
    global _GP_OWNER_ID_LOOKUP_CACHE
    owner_id = str(owner_id or "")
    if not owner_id:
        return None
    cache = _GP_OWNER_ID_LOOKUP_CACHE
    if cache is None:
        cache = {}
        for candidate in tuple(getattr(bpy.data, "objects", ()) or ()):
            try:
                if bool(getattr(candidate, "is_fbp_control", False)):
                    cache[stable_id(candidate, "LAYER")] = (
                        _canvas_pointer(candidate),
                        str(getattr(candidate, "name", "") or ""),
                    )
            except FBP_DATA_ERRORS:
                continue
        _GP_OWNER_ID_LOOKUP_CACHE = cache
    token = cache.get(owner_id)
    if not isinstance(token, tuple) or len(token) != 2:
        return None
    rig = _gp_rig_by_pointer(token[0], token[1])
    if rig is None:
        cache.pop(owner_id, None)
    return rig


def _scene_by_pointer(pointer):
    if not pointer:
        return None
    for scene in tuple(getattr(bpy.data, "scenes", ()) or ()):
        if _canvas_pointer(scene) == pointer:
            return scene
    return None


def _object_by_runtime_identity(pointer, expected_name=""):
    """Resolve one fresh Object without trusting a retained RNA wrapper."""
    try:
        pointer = int(pointer or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if not pointer:
        return None
    objects = getattr(bpy.data, "objects", None)
    if objects is None:
        return None
    name = str(expected_name or "")
    if name:
        try:
            candidate = objects.get(name)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            candidate = None
        if candidate is not None and _canvas_pointer(candidate) == pointer:
            return candidate
    try:
        candidates = tuple(objects or ())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        candidates = ()
    for candidate in candidates:
        if _canvas_pointer(candidate) == pointer:
            return candidate
    return None


def _gp_canvas_by_pointer(pointer):
    """Resolve a registered canvas and prune stale primitive index entries."""
    try:
        pointer = int(pointer or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if not pointer:
        return None
    expected_name = str(_GP_CANVAS_REGISTRY.get(pointer, "") or "")
    canvas = _object_by_runtime_identity(pointer, expected_name)
    if not is_gp_canvas(canvas):
        _GP_CANVAS_REGISTRY.pop(pointer, None)
        return None
    try:
        current_name = str(getattr(canvas, "name", "") or "")
        if current_name and current_name != expected_name:
            _GP_CANVAS_REGISTRY[pointer] = current_name
    except FBP_DATA_ERRORS:
        pass
    return canvas


def _gp_canvas_bucket_values(bucket):
    """Yield fresh canvases from a primitive pointer/name bucket."""
    if not isinstance(bucket, dict):
        return ()
    result = []
    for pointer, expected_name in tuple(bucket.items()):
        canvas = _object_by_runtime_identity(pointer, expected_name)
        if not is_gp_canvas(canvas):
            bucket.pop(pointer, None)
            continue
        try:
            current_name = str(getattr(canvas, "name", "") or "")
            if current_name and current_name != expected_name:
                bucket[pointer] = current_name
        except FBP_DATA_ERRORS:
            pass
        result.append(canvas)
    return tuple(result)


def _gp_rig_by_pointer(pointer, expected_name=""):
    rig = _object_by_runtime_identity(pointer, expected_name)
    try:
        return rig if rig is not None and bool(getattr(rig, "is_fbp_control", False)) else None
    except FBP_DATA_ERRORS:
        return None


def _scene_contains_canvas(scene, canvas):
    if scene is None or canvas is None:
        return False
    try:
        linked = getattr(scene, "objects", None)
        candidate = linked.get(canvas.name) if linked is not None else None
        return candidate is not None and _same_datablock(candidate, canvas)
    except FBP_DATA_ERRORS:
        return False


def _scene_for_canvas(canvas, preferred=None):
    """Resolve the Scene that owns *canvas* without trusting active UI context.

    ``Object.users_scene`` avoids a global scene scan on the hot mask path and
    remains valid after object renames. A preferred Scene still wins when the
    same object is intentionally linked to multiple scenes.
    """
    canvas = _original_datablock(canvas)
    preferred = _original_datablock(preferred)
    if _scene_contains_canvas(preferred, canvas):
        return preferred
    context_scene = getattr(getattr(bpy, "context", None), "scene", None)
    if _scene_contains_canvas(context_scene, canvas):
        return context_scene
    try:
        users_scene = tuple(getattr(canvas, "users_scene", ()) or ())
    except FBP_DATA_ERRORS:
        users_scene = ()
    if users_scene:
        return users_scene[0]
    for scene in tuple(getattr(bpy.data, "scenes", ()) or ()):
        if _scene_contains_canvas(scene, canvas):
            return scene
    return preferred or context_scene


def _clear_gp_exposure_cache(canvas=None, data=None):
    """Discard cached GP frame indexes for one datablock or for all data."""
    if canvas is None and data is None:
        _GP_EXPOSURE_INDEX.clear()
        _GP_FRAME_STATE.clear()
        return
    target_data = data if data is not None else getattr(canvas, "data", None)
    data_pointer = _data_pointer(target_data)
    if data_pointer:
        _GP_EXPOSURE_INDEX.pop(data_pointer, None)
    canvas_pointers = set()
    if canvas is not None:
        canvas_pointers.add(_canvas_pointer(canvas))
    elif data_pointer:
        canvas_pointers.update(_GP_DATA_CANVAS_INDEX.get(data_pointer, {}).keys())
    if canvas_pointers:
        for key in tuple(_GP_FRAME_STATE):
            if key and key[0] in canvas_pointers:
                _GP_FRAME_STATE.pop(key, None)
        for key in tuple(_GP_FRAME_SENSITIVITY_CACHE):
            if key and key[0] in canvas_pointers:
                _GP_FRAME_SENSITIVITY_CACHE.pop(key, None)


def _clear_gp_output_caches():
    global _GP_REVEAL_POSITION_CACHE_BYTES, _GP_RGBA_BUFFER_CACHE_BYTES
    _GP_REVEAL_POSITION_CACHE.clear()
    _GP_REVEAL_POSITION_CACHE_BYTES = 0
    _GP_RGBA_BUFFER_CACHE.clear()
    _GP_RGBA_BUFFER_CACHE_BYTES = 0


def _layer_frame_summary(layer):
    """Cheap validation signature for a cached layer timeline."""
    try:
        frames = getattr(layer, "frames", ()) or ()
        count = len(frames)
        if not count:
            return (_canvas_pointer(layer), 0, None, None)
        first = int(getattr(frames[0], "frame_number", 0) or 0)
        last = int(getattr(frames[-1], "frame_number", 0) or 0)
        return (_canvas_pointer(layer), count, first, last)
    except FBP_DATA_ERRORS:
        return (_canvas_pointer(layer), -1, None, None)


def _build_gp_exposure_index(canvas):
    data = getattr(canvas, "data", None)
    data_pointer = _data_pointer(data)
    if not data_pointer:
        return {"summary": (), "records": ()}
    try:
        layers = tuple(getattr(data, "layers", ()) or ())
    except FBP_DATA_ERRORS:
        layers = ()
    records = []
    summary = []
    for layer in layers:
        layer_summary = _layer_frame_summary(layer)
        summary.append(layer_summary)
        numbers = []
        drawings = []
        drawing_pointers = []
        try:
            frames = tuple(getattr(layer, "frames", ()) or ())
        except FBP_DATA_ERRORS:
            frames = ()
        for frame in frames:
            try:
                number = int(getattr(frame, "frame_number", 0) or 0)
                drawing = getattr(frame, "drawing", None)
            except FBP_DATA_ERRORS:
                continue
            numbers.append(number)
            drawings.append(drawing)
            drawing_pointers.append(_data_pointer(drawing))
        records.append({
            "layer": layer,
            "numbers": tuple(numbers),
            "drawings": tuple(drawings),
            "drawing_pointers": tuple(drawing_pointers),
        })
    entry = {"summary": tuple(summary), "records": tuple(records)}
    _GP_EXPOSURE_INDEX[data_pointer] = entry
    return entry


def _gp_exposure_index(canvas, *, rebuild=False):
    """Return the cached binary-search timeline for a GP datablock.

    The depsgraph invalidates this cache whenever Grease Pencil data changes.
    Frame-change playback can therefore trust an existing entry without
    re-scanning every layer. Explicit geometry refreshes request ``rebuild`` to
    remain correct even when an operator mutates frames before Blender emits
    its depsgraph update.
    """
    data = getattr(canvas, "data", None)
    data_pointer = _data_pointer(data)
    if not data_pointer:
        return {"summary": (), "records": ()}
    if not rebuild:
        cached = _GP_EXPOSURE_INDEX.get(data_pointer)
        if cached is not None:
            return cached
    return _build_gp_exposure_index(canvas)


def _indexed_drawing_entry(record, frame_number):
    numbers = record.get("numbers", ())
    if not numbers:
        return None, None, 0
    index = bisect_right(numbers, int(frame_number)) - 1
    if index < 0:
        return None, None, 0
    drawings = record.get("drawings", ())
    pointers = record.get("drawing_pointers", ())
    drawing = drawings[index] if index < len(drawings) else None
    pointer = pointers[index] if index < len(pointers) else _data_pointer(drawing)
    return numbers[index], drawing, pointer


def _canvas_exposure_state(canvas, frame_number, *, rebuild_index=False):
    """Return cache key and resolved drawings for one scene frame."""
    index = _gp_exposure_index(canvas, rebuild=rebuild_index)
    key = []
    state = []
    for layer_index, record in enumerate(index.get("records", ())):
        layer = record.get("layer")
        layer_state = _gp_layer_runtime_signature(layer)
        source_frame, drawing, drawing_pointer = _indexed_drawing_entry(record, frame_number)
        key.append((layer_index, layer_state, source_frame, drawing_pointer))
        state.append((layer, drawing, source_frame))
    return (tuple(key) if key else (("EMPTY",),), tuple(state))


def _canvas_exposure_state_from_object(source_canvas, frame_number):
    """Uncached exposure state for evaluated/live Grease Pencil data."""
    key = []
    state = []
    data = getattr(source_canvas, "data", None)
    try:
        layers = tuple(getattr(data, "layers", ()) or ())
    except FBP_DATA_ERRORS:
        layers = ()
    for layer_index, layer in enumerate(layers):
        layer_state = _gp_layer_runtime_signature(layer)
        source_frame, drawing = _current_drawing_entry(layer, frame_number)
        key.append(("LIVE", layer_index, layer_state, source_frame, _data_pointer(drawing)))
        state.append((layer, drawing, source_frame))
    return (tuple(key) if key else (("EMPTY_LIVE",),), tuple(state))


def _evaluated_canvas_for_mask(canvas, scene=None):
    """Return an evaluated GP object candidate for live stroke extraction."""
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = canvas.evaluated_get(depsgraph) if depsgraph is not None else None
        if evaluated is not None and _is_grease_pencil_data_block(getattr(evaluated, "data", None)):
            return evaluated
    except FBP_DATA_ERRORS:
        pass
    return None


def _drawing_radius_signature(drawing):
    """Small radius fingerprint for live GP updates.

    Point count alone is not enough: changing brush radius can leave the same
    stroke/point structure while only the GP radius attribute changes.
    """
    try:
        attributes = getattr(drawing, "attributes", None)
        if attributes is None:
            return ()
        try:
            attr = attributes.get("radius")
        except FBP_DATA_ERRORS:
            attr = attributes["radius"] if "radius" in attributes else None
        if attr is None:
            return ()
        data = getattr(attr, "data", None)
        if data is None:
            return ()
        count = len(data)
        if count <= 0:
            return ()
        values = [0.0] * count
        try:
            data.foreach_get("value", values)
        except FBP_DATA_ERRORS:
            values = []
            for index in range(count):
                try:
                    values.append(float(getattr(data[index], "value", 0.0) or 0.0))
                except FBP_DATA_ERRORS:
                    values.append(0.0)
        clean = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
        if not clean:
            return (count, 0.0, 0.0, 0.0)
        return (count, round(min(clean), 7), round(max(clean), 7), round(sum(clean), 7))
    except FBP_DATA_ERRORS:
        return ()


def _attribute_data_by_name(drawing, names):
    try:
        attributes = getattr(drawing, "attributes", None)
        if attributes is None:
            return None
        wanted = [str(name).lower() for name in names]
        for name in names:
            try:
                attr = attributes.get(name)
            except FBP_DATA_ERRORS:
                attr = None
            if attr is not None:
                return getattr(attr, "data", None)
        try:
            for attr in attributes:
                attr_name = str(getattr(attr, "name", "") or "").lower()
                if attr_name in wanted:
                    return getattr(attr, "data", None)
        except FBP_DATA_ERRORS:
            pass
    except FBP_DATA_ERRORS:
        pass
    return None


def _attribute_numeric_values_exact(drawing, names, expected_count):
    """Read one scalar CURVE-domain attribute with an exact element count."""
    expected_count = max(0, int(expected_count or 0))
    if expected_count <= 0:
        return ()
    data = _attribute_data_by_name(drawing, names)
    if data is None:
        return ()
    try:
        if len(data) != expected_count:
            return ()
    except FBP_DATA_ERRORS:
        return ()

    values = [0.0] * expected_count
    for prop in ("value", "factor"):
        try:
            data.foreach_get(prop, values)
            return tuple(values)
        except FBP_DATA_ERRORS:
            continue

    result = []
    valid = False
    for index in range(expected_count):
        try:
            item = data[index]
        except FBP_DATA_ERRORS:
            result.append(None)
            continue
        value = None
        for prop in ("value", "factor"):
            try:
                value = getattr(item, prop)
                break
            except FBP_DATA_ERRORS:
                continue
        if value is None:
            result.append(None)
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            result.append(None)
            continue
        if math.isfinite(number):
            result.append(number)
            valid = True
        else:
            result.append(None)
    return tuple(result) if valid else ()


def _native_gp_component_mode(
    fill_id=0,
    hide_stroke=False,
    *,
    has_fill_id=False,
    has_hide_stroke=False,
):
    """Resolve Blender 5.2's native Stroke/Fill/Both representation."""
    try:
        fill_value = int(fill_id or 0)
    except (TypeError, ValueError):
        fill_value = 0
    hidden = bool(hide_stroke)
    if has_fill_id:
        if fill_value != 0:
            return "FILL" if hidden else "BOTH"
        return "AUTO" if hidden else "STROKE"
    if has_hide_stroke:
        return "AUTO" if hidden else "STROKE"
    return "AUTO"


def _drawing_curve_mode_signature(drawing):
    """Fingerprint Blender 5.2 per-curve Stroke/Fill/Both state.

    Blender stores this as ``fill_id`` + ``hide_stroke`` on the CURVE domain.
    Generic attributes named ``type`` or ``mode`` are unrelated and must never
    be interpreted as component modes.
    """
    try:
        offsets = getattr(drawing, "curve_offsets", None)
        curve_count = max(0, len(offsets) - 1) if offsets is not None else 0
    except FBP_DATA_ERRORS:
        curve_count = 0
    if curve_count <= 0:
        try:
            curve_count = len(tuple(getattr(drawing, "curves", ()) or ()))
        except FBP_DATA_ERRORS:
            curve_count = 0
    if curve_count <= 0:
        return ()
    fill_ids = _attribute_numeric_values_exact(drawing, ("fill_id",), curve_count)
    hide_strokes = _attribute_numeric_values_exact(drawing, ("hide_stroke",), curve_count)
    has_fill_ids = len(fill_ids) == curve_count
    has_hide_strokes = len(hide_strokes) == curve_count

    if has_fill_ids or has_hide_strokes:
        values = []
        for index in range(curve_count):
            fill_id = fill_ids[index] if has_fill_ids and fill_ids[index] is not None else 0
            hidden = bool(hide_strokes[index]) if has_hide_strokes and hide_strokes[index] is not None else False
            values.append(
                _native_gp_component_mode(
                    fill_id,
                    hidden,
                    has_fill_id=has_fill_ids,
                    has_hide_stroke=has_hide_strokes,
                )
            )
        return tuple(values)

    # Narrow wrapper fallback for files/builds that expose an explicit property.
    values = []
    try:
        for curve in tuple(getattr(drawing, "curves", ()) or ()):
            mode = None
            for prop in ("stroke_type", "component_mode", "gpencil_stroke_type"):
                try:
                    mode = _normalize_gp_stroke_type(getattr(curve, prop), None)
                    if mode:
                        break
                except FBP_DATA_ERRORS:
                    continue
            values.append(mode or "AUTO")
    except FBP_DATA_ERRORS:
        values = []
    return tuple(values[:curve_count]) if values else ()


def _drawing_curve_type_signature(drawing):
    """Fingerprint Blender 5.2 Poly/Catmull-Rom/Bezier/NURBS curves."""
    try:
        offsets = getattr(drawing, "curve_offsets", None)
        curve_count = max(0, len(offsets) - 1) if offsets is not None else 0
    except FBP_DATA_ERRORS:
        curve_count = 0
    if curve_count <= 0:
        return ()
    values = _attribute_numeric_values_exact(drawing, ("curve_type",), curve_count)
    return tuple(int(value) if value is not None else 1 for value in values)


def _active_gp_brush_signature(context=None):
    brush = _active_gp_brush(context)
    if brush is None:
        return ()
    mode = _active_gp_brush_stroke_type(context, fallback="STROKE")
    width = _active_gp_brush_unprojected_size(context, fallback=DEFAULT_GP_MASK_STROKE_WIDTH)
    try:
        pixel_size = float(getattr(brush, "size", 0.0) or 0.0)
    except FBP_DATA_ERRORS:
        pixel_size = 0.0
    return (mode, round(float(width or 0.0), 7), round(float(pixel_size or 0.0), 3))


def _active_gp_brush(context=None):
    context = context or bpy.context
    try:
        scene = getattr(context, "scene", None)
        tool_settings = getattr(scene, "tool_settings", None)
        paint = getattr(tool_settings, "gpencil_paint", None) or getattr(tool_settings, "grease_pencil_paint", None)
        brush = getattr(paint, "brush", None)
        if brush is not None:
            return brush
    except FBP_DATA_ERRORS:
        pass
    try:
        return getattr(bpy.context.tool_settings.gpencil_paint, "brush", None)
    except FBP_DATA_ERRORS:
        return None


def _active_gp_brush_stroke_type(context=None, fallback="STROKE"):
    brush = _active_gp_brush(context)
    try:
        settings = getattr(brush, "gpencil_settings", None)
        value = str(getattr(settings, "stroke_type", "") or "").upper()
        if value in {"STROKE", "FILL", "BOTH"}:
            return value
    except FBP_DATA_ERRORS:
        pass
    return str(fallback or "STROKE").upper()


def _active_gp_brush_unprojected_size(context=None, fallback=DEFAULT_GP_MASK_STROKE_WIDTH):
    """Return the visible GP brush width as a stable object-space value.

    Blender 5.2 exposes two useful values while drawing GP:
    - ``brush.unprojected_size``: object-space size shown in INFO for GP draw
      brushes, e.g. 0.1 / 0.6. Prefer this when available.
    - ``brush.size``: screen/radial-control pixel size. Use it only as a
      fallback and normalize it into a small object-space value so it can still
      drive the mask thickness when ``unprojected_size`` is unavailable/stale.
    """
    brush = _active_gp_brush(context)
    unprojected = None
    try:
        value = float(getattr(brush, "unprojected_size"))
        if math.isfinite(value) and value > 0.0:
            unprojected = value
    except FBP_DATA_ERRORS:
        unprojected = None
    if unprojected is not None:
        return float(unprojected)
    try:
        value = float(getattr(brush, "size"))
        if math.isfinite(value) and value > 0.0:
            # Pixel brush size fallback. Keep ratios but map to plane-ish units.
            return max(1.0e-5, value / 1000.0)
    except FBP_DATA_ERRORS:
        pass
    return float(fallback or DEFAULT_GP_MASK_STROKE_WIDTH)


def _set_active_gp_brush_stroke_type(context=None, mode="STROKE"):
    mode = str(mode or "STROKE").upper()
    if mode == "LINE":
        mode = "STROKE"
    if mode == "AUTO":
        return False
    if mode not in {"STROKE", "FILL", "BOTH"}:
        return False
    brush = _active_gp_brush(context)
    try:
        settings = getattr(brush, "gpencil_settings", None)
        if settings is not None and hasattr(settings, "stroke_type"):
            settings.stroke_type = mode
            return True
    except FBP_DATA_ERRORS:
        pass
    return False


def _gp_mask_curve_count(canvas, scene=None, *, rebuild_index=False):
    try:
        target_scene = _scene_for_canvas(canvas, scene)
        frame_number = _scene_current_frame_number(target_scene, 1)
        _exposure_key, exposure_state = _canvas_exposure_state(
            canvas,
            frame_number,
            rebuild_index=bool(rebuild_index),
        )
    except FBP_DATA_ERRORS:
        return 0
    total = 0
    for _layer, drawing, _source_frame in exposure_state:
        if drawing is None:
            continue
        count = 0
        try:
            offsets = getattr(drawing, "curve_offsets", None)
            offset_count = len(offsets) if offsets is not None else 0
            if offset_count >= 2:
                # Count only non-empty curves. After Ctrl+Z Blender can leave
                # temporary empty curve ranges; keeping metadata for those ranges
                # shifted later strokes back to stale Fill/Stroke modes.
                values = []
                try:
                    raw = [0] * offset_count
                    offsets.foreach_get("value", raw)
                    values = [int(v) for v in raw]
                except FBP_DATA_ERRORS:
                    values = []
                    for idx in range(offset_count):
                        try:
                            item = offsets[idx]
                            values.append(int(getattr(item, "value", item)))
                        except FBP_DATA_ERRORS:
                            values = []
                            break
                if len(values) >= 2:
                    count = max(count, sum(1 for idx in range(len(values) - 1) if values[idx + 1] > values[idx]))
                else:
                    count = max(count, int(offset_count) - 1)
        except FBP_DATA_ERRORS:
            pass
        if count <= 0:
            try:
                raw_items = []
                seen_items = set()
                for attr in ("strokes", "curves"):
                    for item in tuple(getattr(drawing, attr, ()) or ()):
                        item_key = id(item)
                        if item_key in seen_items:
                            continue
                        seen_items.add(item_key)
                        try:
                            pts = getattr(item, "points", None) or getattr(item, "points_co", None)
                            if pts is not None and len(pts) <= 0:
                                continue
                        except FBP_DATA_ERRORS:
                            pass
                        raw_items.append(item)
                count = len(raw_items)
            except FBP_DATA_ERRORS:
                count = 0
        total += max(0, int(count or 0))
    return total


def _json_list_from_canvas(canvas, key, default=None):
    default = [] if default is None else list(default)
    try:
        raw = canvas.get(key, "")
        if not raw:
            return list(default)
        value = json.loads(str(raw))
        return list(value) if isinstance(value, list) else list(default)
    except FBP_DATA_ERRORS:
        return list(default)


def _idprop_set_if_changed(canvas, key, value, *, epsilon=0.0):
    try:
        old = canvas.get(key, None)
        if isinstance(value, float):
            try:
                if abs(float(old) - float(value)) <= float(epsilon or 0.0):
                    return False
            except (TypeError, ValueError):
                pass
        elif old == value:
            return False
        canvas[key] = value
        return True
    except FBP_DATA_ERRORS:
        return False


def _normalize_gp_stroke_type(value, fallback=None):
    if value is None:
        return fallback
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8", "ignore")
    except FBP_DATA_ERRORS:
        pass
    text = str(value).strip().upper()
    if text in {"STROKE", "LINE", "LINES"}:
        return "STROKE"
    if text in {"FILL", "FILLED"}:
        return "FILL"
    if text in {"BOTH", "STROKE_FILL", "FILL_STROKE", "STROKE_AND_FILL", "FILL_AND_STROKE"}:
        return "BOTH"
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return fallback
    if number == 0:
        return "STROKE"
    if number == 1:
        return "FILL"
    if number in {2, 3}:
        return "BOTH"
    return fallback

def _sync_gp_mask_authored_curve_state(
    canvas,
    scene=None,
    context=None,
    observed_weight=None,
    *,
    brush_mode_override=None,
    rebuild_index=False,
):
    """Persist the authored Stroke/Fill/Both mode for completed curves.

    Width is deliberately *not* mirrored into an index-based JSON list. Blender
    publishes GP points and curves on different depsgraph ticks; binding a brush
    width to that delayed curve index caused the one/two-stroke offset and the
    repeating 10 → 1 → 10 pattern. Raster thickness now comes directly from the
    native per-point/per-curve radius stored in the drawing.

    ``brush_mode_override`` is used when the user changes the authoring mode.
    Any curves Blender committed just before that UI change must be finalized
    with the *previous* mode, not the newly selected one. Without this barrier,
    delayed GP curve publication could make changing stroke three to Fill
    retroactively mark stroke one as Fill while leaving stroke three as Stroke.
    """
    if not is_gp_mask_canvas(canvas) or _gp_mask_is_structural_edit_mode(canvas):
        return False
    try:
        curve_count = (
            int(observed_weight[0])
            if observed_weight is not None
            else _gp_mask_curve_count(canvas, scene, rebuild_index=bool(rebuild_index))
        )
    except (TypeError, ValueError, IndexError):
        curve_count = _gp_mask_curve_count(canvas, scene, rebuild_index=bool(rebuild_index))
    curve_count = max(0, int(curve_count or 0))

    modes = [str(v or "AUTO").upper() for v in _json_list_from_canvas(canvas, "fbp_gp_mask_curve_modes_json")]
    previous_modes = tuple(modes)
    if len(modes) > curve_count:
        modes = modes[:curve_count]

    try:
        fallback_mode = str(getattr(canvas, "fbp_gp_mask_source", "AUTO") or "AUTO").upper()
    except FBP_DATA_ERRORS:
        fallback_mode = "AUTO"
    if fallback_mode == "LINE":
        fallback_mode = "STROKE"
    brush_mode = _normalize_gp_stroke_type(brush_mode_override, None)
    if brush_mode not in {"STROKE", "FILL", "BOTH"}:
        try:
            brush_mode = _normalize_gp_stroke_type(
                canvas.get("fbp_gp_mask_active_brush_mode", ""),
                None,
            )
        except FBP_DATA_ERRORS:
            brush_mode = None
    if brush_mode not in {"STROKE", "FILL", "BOTH"}:
        brush_mode = _normalize_gp_stroke_type(fallback_mode, None)
    if brush_mode not in {"STROKE", "FILL", "BOTH"}:
        brush_mode = _active_gp_brush_stroke_type(context, fallback="STROKE")
    if brush_mode not in {"STROKE", "FILL", "BOTH"}:
        brush_mode = "STROKE"
    while len(modes) < curve_count:
        modes.append(brush_mode)

    changed = previous_modes != tuple(modes)
    changed = bool(
        _idprop_set_if_changed(
            canvas,
            "fbp_gp_mask_curve_modes_json",
            json.dumps(modes, separators=(",", ":")),
        )
        or changed
    )
    _idprop_set_if_changed(canvas, "fbp_gp_mask_active_brush_mode", str(brush_mode))
    return changed

def _canvas_stroke_count_signature(
    canvas,
    scene=None,
    *,
    sync_authoring=True,
    detail=True,
):
    """Return a current-frame geometry signature for GP mask invalidation.

    The live-paint poll passes ``detail=False`` and uses Blender 5.x's native
    ``curve_offsets`` arrays. That path is O(curves) and avoids walking every
    point/radius/mode attribute several times per second. Full detail remains
    available for deletion/history checks outside Paint Mode.
    """
    if _gp_mask_refresh_blocked_by_edit_mode(canvas):
        return (("EDIT_DEFER", _canvas_pointer(canvas)),), (0, 0)
    if sync_authoring:
        _sync_gp_mask_authored_curve_state(canvas, scene=scene)
    try:
        target_scene = _scene_for_canvas(canvas, scene)
        frame_number = _scene_current_frame_number(target_scene, 1)
        _exposure_key, exposure_state = _canvas_exposure_state(canvas, frame_number)
    except FBP_DATA_ERRORS:
        return (), (0, 0)

    signature = []
    total_strokes = 0
    total_points = 0
    for layer, drawing, source_frame in exposure_state:
        if drawing is None:
            signature.append((_canvas_pointer(layer), source_frame, 0, 0, 0))
            continue

        stroke_count = -1
        point_count = 0
        offsets_reliable = False
        try:
            offsets = getattr(drawing, "curve_offsets", None)
            offset_count = len(offsets) if offsets is not None else 0
            if offset_count >= 2:
                values = [0] * offset_count
                try:
                    offsets.foreach_get("value", values)
                    values = [int(value) for value in values]
                except FBP_DATA_ERRORS:
                    values = [
                        int(getattr(offsets[index], "value", offsets[index]))
                        for index in range(offset_count)
                    ]
                if len(values) >= 2:
                    point_count = max(0, int(values[-1] or 0))
                    stroke_count = sum(
                        1
                        for index in range(len(values) - 1)
                        if values[index + 1] > values[index]
                    )
                    offsets_reliable = True
        except FBP_DATA_ERRORS:
            offsets_reliable = False

        # Full/history checks preserve the old wrapper cross-check because a
        # Blender publication tick can briefly expose fresher wrapper data than
        # curve_offsets. The bounded live path skips it when offsets are valid.
        if detail or not offsets_reliable:
            try:
                raw_items = []
                seen_items = set()
                for attr in ("strokes", "curves"):
                    for item in tuple(getattr(drawing, attr, ()) or ()):
                        item_key = id(item)
                        if item_key in seen_items:
                            continue
                        seen_items.add(item_key)
                        raw_items.append(item)
                strokes = tuple(raw_items)
                wrapper_stroke_count = len(strokes)
            except FBP_DATA_ERRORS:
                strokes = ()
                wrapper_stroke_count = -1
            wrapper_point_count = 0
            for stroke in strokes:
                try:
                    wrapper_point_count += len(
                        getattr(stroke, "points", None)
                        or getattr(stroke, "points_data", ())
                        or ()
                    )
                except FBP_DATA_ERRORS:
                    continue
            if offsets_reliable:
                stroke_count = max(int(stroke_count or 0), int(wrapper_stroke_count or 0))
                point_count = max(int(point_count or 0), int(wrapper_point_count or 0))
            else:
                stroke_count = wrapper_stroke_count
                point_count = wrapper_point_count

        total_strokes += max(0, int(stroke_count or 0))
        total_points += max(0, int(point_count or 0))
        if detail:
            radius_signature = _drawing_radius_signature(drawing)
            mode_signature = _drawing_curve_mode_signature(drawing)
            curve_type_signature = _drawing_curve_type_signature(drawing)
        else:
            radius_signature = ()
            mode_signature = ()
            curve_type_signature = ()
        signature.append((
            _canvas_pointer(layer),
            source_frame,
            _data_pointer(drawing),
            int(stroke_count or 0),
            int(point_count or 0),
            radius_signature,
            mode_signature,
            curve_type_signature,
        ))
    return tuple(signature), (total_strokes, total_points)


def _gp_mask_stroke_count_decreased(canvas, scene=None):
    key = _gp_mask_dirty_key(canvas, scene)
    if not key[0]:
        return False
    signature, weight = _canvas_stroke_count_signature(canvas, scene)
    previous = _GP_MASK_STROKE_COUNT_SIGNATURE.get(key)
    _GP_MASK_STROKE_COUNT_SIGNATURE[key] = (signature, weight)
    if previous is None:
        return False
    previous_signature, previous_weight = previous
    if signature == previous_signature:
        return False
    try:
        strokes, points = weight
        previous_strokes, previous_points = previous_weight
        return int(strokes) < int(previous_strokes) or int(points) < int(previous_points)
    except (TypeError, ValueError):
        return False


def _clear_gp_geometry_cache(canvas=None):
    global _GP_GEOMETRY_CACHE_BYTES
    if canvas is None:
        _GP_GEOMETRY_CACHE.clear()
        _GP_GEOMETRY_CACHE_BYTES = 0
        _GP_GEOMETRY_GENERATION.clear()
        return
    pointer = _canvas_pointer(canvas)
    _GP_GEOMETRY_GENERATION.pop(pointer, None)
    for key in tuple(_GP_GEOMETRY_CACHE):
        if not key or key[0] != pointer:
            continue
        entry = _GP_GEOMETRY_CACHE.pop(key)
        _GP_GEOMETRY_CACHE_BYTES = max(
            0, _GP_GEOMETRY_CACHE_BYTES - int(entry.get("bytes", 0) or 0)
        )


def _gp_geometry_generation(canvas):
    return int(_GP_GEOMETRY_GENERATION.get(_canvas_pointer(canvas), 0) or 0)


def _bump_gp_geometry_generation(canvas):
    pointer = _canvas_pointer(canvas)
    if not pointer:
        return 0
    generation = int(_GP_GEOMETRY_GENERATION.get(pointer, 0) or 0) + 1
    _GP_GEOMETRY_GENERATION[pointer] = generation
    return generation


def _geometry_cache_get(canvas, exposure_key, context_signature):
    key = (_canvas_pointer(canvas), exposure_key, context_signature)
    entry = _GP_GEOMETRY_CACHE.get(key)
    if entry is None:
        return None
    _GP_GEOMETRY_CACHE.move_to_end(key)
    return entry


def _geometry_cache_put(canvas, exposure_key, context_signature, polygons, polylines):
    global _GP_GEOMETRY_CACHE_BYTES
    key = (_canvas_pointer(canvas), exposure_key, context_signature)
    point_count = sum(len(contour) for group in polygons for contour in group)
    point_count += sum(len(points) for points, _cyclic, _width in polylines)
    byte_count = int(point_count * 24 + len(polylines) * 32 + len(polygons) * 24)
    previous = _GP_GEOMETRY_CACHE.pop(key, None)
    if previous is not None:
        _GP_GEOMETRY_CACHE_BYTES = max(
            0, _GP_GEOMETRY_CACHE_BYTES - int(previous.get("bytes", 0) or 0)
        )
    entry = {
        "exposure_key": exposure_key,
        "context_signature": context_signature,
        "polygons": polygons,
        "polylines": polylines,
        "bytes": byte_count,
        "distance_signatures": {},
    }
    _GP_GEOMETRY_CACHE[key] = entry
    _GP_GEOMETRY_CACHE_BYTES += byte_count
    while (
        len(_GP_GEOMETRY_CACHE) > _GP_GEOMETRY_CACHE_MAX_ENTRIES
        or _GP_GEOMETRY_CACHE_BYTES > _GP_GEOMETRY_CACHE_MAX_BYTES
    ):
        _old_key, old = _GP_GEOMETRY_CACHE.popitem(last=False)
        _GP_GEOMETRY_CACHE_BYTES = max(
            0, _GP_GEOMETRY_CACHE_BYTES - int(old.get("bytes", 0) or 0)
        )
    return entry


def _scene_camera_dependency_state(canvas, scene=None):
    """Return a stable fingerprint for the camera affecting one canvas."""
    target_scene = _scene_for_canvas(canvas, scene)
    camera = getattr(target_scene, "camera", None) if target_scene is not None else None
    return (
        _data_pointer(target_scene),
        _data_pointer(camera),
        _data_pointer(getattr(camera, "data", None) if camera is not None else None),
    )


def _scene_camera_dependency_changed(canvas, scene=None):
    """Detect camera reassignment without treating every Scene update as geometry."""
    pointer = _canvas_pointer(canvas)
    state = _scene_camera_dependency_state(canvas, scene)
    key = (pointer, state[0])
    previous = _GP_SCENE_CAMERA_STATE.get(key)
    _GP_SCENE_CAMERA_STATE[key] = state
    return previous is None or previous != state


def _remove_canvas_dependencies(canvas):
    canvas = _original_datablock(canvas)
    pointer = _canvas_pointer(canvas)
    for key in tuple(_GP_SCENE_CAMERA_STATE):
        if key and key[0] == pointer:
            _GP_SCENE_CAMERA_STATE.pop(key, None)
    for dependency_pointer in _GP_CANVAS_DEPENDENCY_POINTERS.pop(pointer, ()):
        bucket = _GP_DEPENDENCY_CANVAS_INDEX.get(dependency_pointer)
        if bucket is None:
            continue
        bucket.pop(pointer, None)
        if not bucket:
            _GP_DEPENDENCY_CANVAS_INDEX.pop(dependency_pointer, None)


def _refresh_canvas_dependencies(canvas, scene=None):
    canvas = _original_datablock(canvas)
    scene = _original_datablock(scene)
    pointer = _canvas_pointer(canvas)
    if not pointer:
        return
    _remove_canvas_dependencies(canvas)
    dependencies = []
    try:
        owner = gp_canvas_owner(canvas)
        plane = getattr(owner, "fbp_plane_target", None) if owner is not None else None
        target_scene = _scene_for_canvas(canvas, scene)
        camera = getattr(target_scene, "camera", None) if target_scene is not None else None
        materials = tuple(getattr(getattr(canvas, "data", None), "materials", ()) or ())
        datablocks = [
            getattr(canvas, "data", None),
            owner,
            plane,
            getattr(plane, "data", None) if plane is not None else None,
            getattr(canvas, "parent", None),
            target_scene,
            camera,
            getattr(camera, "data", None) if camera is not None else None,
        ]
        # Fill/Stroke visibility lives on Material IDs in Blender 5.2.
        # Index every slot so editing a GP material invalidates its mask without
        # waiting for an unrelated object or frame update.
        datablocks.extend(materials)
        for datablock in datablocks:
            dependency_pointer = _data_pointer(datablock)
            if dependency_pointer and dependency_pointer not in dependencies:
                dependencies.append(dependency_pointer)
                _GP_DEPENDENCY_CANVAS_INDEX.setdefault(dependency_pointer, {})[pointer] = str(getattr(canvas, "name", "") or "")
        camera_state = _scene_camera_dependency_state(canvas, target_scene)
        _GP_SCENE_CAMERA_STATE[(pointer, camera_state[0])] = camera_state
    except FBP_DATA_ERRORS:
        pass
    _GP_CANVAS_DEPENDENCY_POINTERS[pointer] = tuple(dependencies)

def _clear_gp_distance_cache(canvas=None):
    global _GP_DISTANCE_CACHE_BYTES
    if canvas is None:
        _GP_DISTANCE_CACHE.clear()
        _GP_DISTANCE_CACHE_BYTES = 0
        return
    pointer = _canvas_pointer(canvas)
    for key in tuple(_GP_DISTANCE_CACHE):
        if key[0] != pointer:
            continue
        _entry_signature, payload, byte_count = _GP_DISTANCE_CACHE.pop(key)
        del _entry_signature, payload
        _GP_DISTANCE_CACHE_BYTES = max(0, _GP_DISTANCE_CACHE_BYTES - int(byte_count or 0))


def _gp_base_alpha_cache_get(canvas, resolution, signature):
    """Return a cached single-channel raster before the frame Reveal gate."""
    key = (_canvas_pointer(canvas), int(resolution))
    entry = _GP_DISTANCE_CACHE.get(key)
    if entry is None or str(entry[0]) != str(signature):
        return None
    _GP_DISTANCE_CACHE.move_to_end(key)
    return entry[1]


def _gp_base_alpha_cache_put(canvas, resolution, signature, alpha):
    global _GP_DISTANCE_CACHE_BYTES
    key = (_canvas_pointer(canvas), int(resolution))
    previous = _GP_DISTANCE_CACHE.pop(key, None)
    if previous is not None:
        _GP_DISTANCE_CACHE_BYTES = max(
            0, _GP_DISTANCE_CACHE_BYTES - int(previous[2] or 0)
        )
    byte_count = int(getattr(alpha, "nbytes", 0) or 0)
    if byte_count <= 0 or byte_count > _GP_DISTANCE_CACHE_MAX_BYTES:
        return alpha
    _GP_DISTANCE_CACHE[key] = (str(signature), alpha, byte_count)
    _GP_DISTANCE_CACHE_BYTES += byte_count
    while (
        len(_GP_DISTANCE_CACHE) > _GP_DISTANCE_CACHE_MAX_ENTRIES
        or _GP_DISTANCE_CACHE_BYTES > _GP_DISTANCE_CACHE_MAX_BYTES
    ):
        _old_key, (_old_signature, _old_alpha, old_bytes) = _GP_DISTANCE_CACHE.popitem(
            last=False
        )
        del _old_key, _old_signature, _old_alpha
        _GP_DISTANCE_CACHE_BYTES = max(
            0, _GP_DISTANCE_CACHE_BYTES - int(old_bytes or 0)
        )
    return alpha


def _schedule_duplicate_canvas_identity_repair(canvas):
    pointer = _canvas_pointer(canvas)
    if not pointer:
        return False

    def _repair():
        current = _gp_canvas_by_pointer(pointer)
        if not is_gp_canvas(current):
            return None
        current_id = stable_id(current, "MASK") or ensure_mask_identity(current)
        duplicate_pointer = _GP_CANVAS_ID_INDEX.get(current_id)
        duplicate = _gp_canvas_by_pointer(duplicate_pointer) if duplicate_pointer else None
        if duplicate is not None and not _same_datablock(duplicate, current):
            current_id = assign_stable_id(current, "MASK", new_stable_id("MASK"))
            try:
                shared_image = getattr(current, "fbp_gp_mask_image", None)
            except FBP_DATA_ERRORS:
                shared_image = None
            if shared_image is not None:
                for other_pointer in tuple(_GP_CANVAS_REGISTRY):
                    other = _gp_canvas_by_pointer(other_pointer)
                    if _same_datablock(other, current) or not is_gp_canvas(other):
                        continue
                    try:
                        if _same_datablock(getattr(other, "fbp_gp_mask_image", None), shared_image):
                            fbp_set_rna_property_silent(current, "fbp_gp_mask_image", None)
                            current[KEY_MASK_IMAGE_NAME] = ""
                            current[KEY_MASK_DIRTY] = True
                            break
                    except FBP_DATA_ERRORS:
                        continue
        _GP_CANVAS_ID_INDEX[current_id] = pointer
        return None

    return schedule_once(
        f"grease_pencil.identity_repair:{pointer}",
        _repair,
        first_interval=0.01,
    )


def _register_runtime_canvas(canvas, *, refresh_dependencies=True, invalidate_owner=True):
    canvas = _original_datablock(canvas)
    try:
        if not is_gp_canvas(canvas):
            return
        pointer = _canvas_pointer(canvas)
        if not pointer:
            return
        _GP_CANVAS_REGISTRY[pointer] = str(getattr(canvas, "name", "") or "")
        data_pointer = _data_pointer(getattr(canvas, "data", None))
        previous_data_pointer = _GP_CANVAS_DATA_POINTERS.get(pointer, 0)
        if previous_data_pointer and previous_data_pointer != data_pointer:
            previous_bucket = _GP_DATA_CANVAS_INDEX.get(previous_data_pointer)
            if previous_bucket is not None:
                previous_bucket.pop(pointer, None)
                if not previous_bucket:
                    _GP_DATA_CANVAS_INDEX.pop(previous_data_pointer, None)
        if data_pointer:
            _GP_CANVAS_DATA_POINTERS[pointer] = data_pointer
            _GP_DATA_CANVAS_INDEX.setdefault(data_pointer, {})[pointer] = str(getattr(canvas, "name", "") or "")
        canvas_id = stable_id(canvas, "MASK")
        if canvas_id:
            existing_pointer = _GP_CANVAS_ID_INDEX.get(canvas_id)
            existing = _gp_canvas_by_pointer(existing_pointer) if existing_pointer else None
            if existing is not None and not _same_datablock(existing, canvas):
                _schedule_duplicate_canvas_identity_repair(canvas)
            else:
                _GP_CANVAS_ID_INDEX[canvas_id] = pointer
        if refresh_dependencies:
            _refresh_canvas_dependencies(canvas)
        if invalidate_owner:
            _invalidate_gp_owner_cache()
    except FBP_DATA_ERRORS:
        pass


def _unregister_runtime_canvas(canvas):
    canvas = _original_datablock(canvas)
    pointer = _canvas_pointer(canvas)
    _remove_canvas_dependencies(canvas)
    data_pointer = _GP_CANVAS_DATA_POINTERS.pop(pointer, 0)
    if not data_pointer and canvas is not None:
        data_pointer = _data_pointer(getattr(canvas, "data", None))
    _GP_CANVAS_REGISTRY.pop(pointer, None)
    _remove_frame_sensitive_canvas(pointer)
    if data_pointer:
        bucket = _GP_DATA_CANVAS_INDEX.get(data_pointer)
        if bucket is not None:
            bucket.pop(pointer, None)
            if not bucket:
                _GP_DATA_CANVAS_INDEX.pop(data_pointer, None)
    for canvas_id, registered_pointer in tuple(_GP_CANVAS_ID_INDEX.items()):
        if int(registered_pointer or 0) == int(pointer or 0):
            _GP_CANVAS_ID_INDEX.pop(canvas_id, None)
    _clear_gp_geometry_cache(canvas)
    _clear_gp_distance_cache(canvas)
    _clear_gp_exposure_cache(canvas)
    _invalidate_gp_binding_cache()
    _invalidate_gp_owner_cache()


def _rebuild_gp_binding_index(candidates=None):
    global _GP_BINDING_INDEX
    index = {}
    if candidates is None:
        candidates = tuple(getattr(bpy.data, "objects", ()) or ())
    for candidate in tuple(candidates or ()):
        try:
            if not bool(getattr(candidate, "is_fbp_control", False)):
                continue
            for effect_id, assigned, contract in gp_mask_assignments(candidate):
                if assigned is None:
                    continue
                index.setdefault(_canvas_pointer(assigned), []).append((
                    _canvas_pointer(candidate),
                    str(getattr(candidate, "name", "") or ""),
                    effect_id,
                    contract,
                ))
        except FBP_DATA_ERRORS:
            continue
    _GP_BINDING_INDEX = {key: tuple(value) for key, value in index.items()}
    return _GP_BINDING_INDEX


def _rebuild_gp_owner_index():
    global _GP_DRAWING_OWNER_INDEX
    index = {}
    stale = []
    for pointer in tuple(_GP_CANVAS_REGISTRY):
        canvas = _gp_canvas_by_pointer(pointer)
        if not is_gp_canvas(canvas):
            stale.append(pointer)
            continue
        if not is_gp_drawing_canvas(canvas):
            continue
        owner = gp_canvas_owner(canvas)
        if owner is None:
            continue
        index.setdefault(_canvas_pointer(owner), []).append(pointer)
    for pointer in stale:
        _GP_CANVAS_REGISTRY.pop(pointer, None)
        _remove_frame_sensitive_canvas(pointer)
    _GP_DRAWING_OWNER_INDEX = {key: tuple(value) for key, value in index.items()}
    return _GP_DRAWING_OWNER_INDEX


def _remove_frame_sensitive_canvas(canvas_or_pointer, scene=None):
    try:
        pointer = int(canvas_or_pointer) if isinstance(canvas_or_pointer, int) else _canvas_pointer(canvas_or_pointer)
    except (TypeError, ValueError):
        pointer = 0
    if not pointer:
        return
    scene_pointer = _canvas_pointer(scene) if scene is not None else 0
    for key in tuple(_FRAME_SENSITIVE_MASKS):
        if key and key[0] == pointer and (not scene_pointer or key[1] == scene_pointer):
            _FRAME_SENSITIVE_MASKS.pop(key, None)
    for key in tuple(_GP_FRAME_STATE):
        if key and key[0] == pointer and (not scene_pointer or key[1] == scene_pointer):
            _GP_FRAME_STATE.pop(key, None)
    for key in tuple(_GP_FRAME_SENSITIVITY_CACHE):
        if key and key[0] == pointer and (not scene_pointer or key[1] == scene_pointer):
            _GP_FRAME_SENSITIVITY_CACHE.pop(key, None)
    for key in tuple(_GP_MASK_STROKE_COUNT_SIGNATURE):
        if key and key[0] == pointer and (not scene_pointer or key[1] == scene_pointer):
            _GP_MASK_STROKE_COUNT_SIGNATURE.pop(key, None)


def _sync_frame_mask_registry(canvas, *, refresh_sensitivity=False, scene=None):
    try:
        pointer = _canvas_pointer(canvas)
        target_scene = _scene_for_canvas(canvas, scene)
        scene_pointer = _canvas_pointer(target_scene)
        enabled = _gp_mask_live_refresh_enabled(canvas)
        has_image = getattr(canvas, "fbp_gp_mask_image", None) is not None
        sensitive = _canvas_mask_changes_with_frame(canvas, refresh=refresh_sensitivity, scene=target_scene)
    except FBP_DATA_ERRORS:
        return
    if pointer and scene_pointer and enabled and has_image and sensitive:
        _FRAME_SENSITIVE_MASKS[(pointer, scene_pointer)] = True
    else:
        _remove_frame_sensitive_canvas(pointer, target_scene)


def _gp_canvas_enum_items(_self, context):
    items = []
    scene = getattr(context, "scene", None) if context is not None else None
    objects = tuple(getattr(scene, "objects", ()) or ()) if scene is not None else ()
    for canvas in objects:
        if not is_gp_mask_canvas(canvas):
            continue
        owner = gp_canvas_owner(canvas)
        owner_name = str(getattr(owner, "name", "Unlinked") or "Unlinked")
        identifier = fbp_obj_runtime_token(canvas) or str(canvas.name)
        items.append((identifier, str(canvas.name), f"Grease Pencil mask · {owner_name}", "OUTLINER_OB_GREASEPENCIL", len(items)))
    if not items:
        items.append(("", "No Grease Pencil Canvas", "Create a Grease Pencil canvas first", "ERROR", 0))
    return items


def _gp_resolve_runtime_targets(payload):
    try:
        descriptors = json.loads(str(payload or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    result = []
    seen = set()
    for descriptor in descriptors if isinstance(descriptors, list) else ():
        if not isinstance(descriptor, dict):
            continue
        target = fbp_find_id_by_runtime_key(
            bpy.data.objects,
            str(descriptor.get("key", "") or ""),
            str(descriptor.get("name", "") or ""),
        )
        key = fbp_obj_runtime_key(target) if target is not None else None
        if target is not None and key not in seen:
            seen.add(key)
            result.append(target)
    return result


def service_status():
    return service_descriptor(SERVICE_ID, SERVICE_API_VERSION, CAPABILITIES)


def fbp_is_grease_pencil_object(obj):
    """Return True for a Blender 5.2 Grease Pencil object."""
    try:
        return bool(obj is not None and str(getattr(obj, "type", "") or "").upper() in _GP_OBJECT_TYPES)
    except FBP_DATA_ERRORS:
        return False


def _is_grease_pencil_data_block(data):
    """Return True for a Blender 5.2 Grease Pencil data-block."""
    if data is None:
        return False
    try:
        return bool(
            type(data).__name__.upper() == "GREASEPENCIL"
            or (hasattr(data, "layers") and hasattr(data, "materials"))
        )
    except FBP_DATA_ERRORS:
        return False


def is_gp_canvas(obj):
    try:
        return bool(
            fbp_is_grease_pencil_object(obj)
            and bool(obj.get(KEY_IS_CANVAS, False))
        )
    except FBP_DATA_ERRORS:
        return False


def _same_datablock(first, second):
    """Compare Blender ID datablocks by their RNA pointer, not wrapper identity.

    Blender may create a fresh Python wrapper when an Object is read through a
    PointerProperty.  ``is`` can therefore fail even though both values refer
    to the exact same datablock, which is especially dangerous during mask
    cleanup and primary-canvas reassignment.
    """
    if first is second:
        return True
    if first is None or second is None:
        return False
    try:
        first_pointer = _data_pointer(first)
        second_pointer = _data_pointer(second)
        if first_pointer and second_pointer:
            return first_pointer == second_pointer
        return first == second
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        try:
            return first == second
        except (ReferenceError, RuntimeError, TypeError, ValueError):
            return False


def gp_canvas_kind(canvas):
    """Return DRAWING or MASK using the current canvas ownership contract."""
    if not is_gp_canvas(canvas):
        return ""
    try:
        explicit = str(canvas.get(KEY_CANVAS_KIND, "") or "").upper()
        if explicit in {"DRAWING", "MASK"}:
            return explicit
        owner = gp_canvas_owner(canvas)
        if owner is not None and _same_datablock(getattr(owner, "fbp_gp_canvas", None), canvas):
            return "DRAWING"
        if gp_mask_bindings(canvas):
            return "MASK"
    except FBP_DATA_ERRORS:
        pass
    return "DRAWING"


def is_gp_drawing_canvas(obj):
    return is_gp_canvas(obj) and gp_canvas_kind(obj) == "DRAWING"


def is_gp_mask_canvas(obj):
    return is_gp_canvas(obj) and gp_canvas_kind(obj) == "MASK"


def gp_canvas_solo_active(canvas):
    if not is_gp_drawing_canvas(canvas):
        return False
    try:
        return bool(canvas.get(KEY_CANVAS_SOLO, False))
    except FBP_DATA_ERRORS:
        return False


def _scene_gp_drawing_canvases(scene):
    if scene is None:
        return ()
    canvases = []
    try:
        candidates = iter_scene_gp_canvases(scene, kind="DRAWING", fallback=True)
        canvases.extend(obj for obj in candidates if is_gp_drawing_canvas(obj))
    except FBP_DATA_ERRORS:
        return ()
    return tuple(canvases)


def _scene_gp_mask_canvases(scene):
    if scene is None:
        return ()
    try:
        return tuple(
            obj for obj in iter_scene_gp_canvases(scene, kind="MASK", fallback=True)
            if is_gp_mask_canvas(obj)
        )
    except FBP_DATA_ERRORS:
        return ()


def sync_gp_mask_interaction_state(context=None, scene=None, active=None):
    """Expose only the active GP mask and lock every inactive mask canvas.

    The rasterized mask image remains available to shaders and Cycles. This
    function changes only 3D View selection/display state and runs from explicit
    selection or active-object events, never from a permanent polling timer.
    """
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return False
    context = context or getattr(bpy, "context", None)
    scene = scene or (getattr(context, "scene", None) if context is not None else None)
    if scene is None:
        return False
    if active is None and context is not None:
        view_layer = getattr(context, "view_layer", None)
        active = getattr(getattr(view_layer, "objects", None), "active", None) if view_layer else None
    active_key = _canvas_pointer(active) if is_gp_mask_canvas(active) else 0
    changed = False
    for canvas in _scene_gp_mask_canvases(scene):
        try:
            is_active = bool(
                active_key and _canvas_pointer(canvas) == active_key and canvas.select_get()
            )
            if is_active:
                if bool(getattr(canvas, "hide_select", False)):
                    canvas.hide_select = False
                    changed = True
                if bool(canvas.hide_get()):
                    canvas.hide_set(False)
                    changed = True
                continue
            if bool(canvas.select_get()):
                canvas.select_set(False)
                changed = True
            if not bool(getattr(canvas, "hide_select", False)):
                canvas.hide_select = True
                changed = True
            if not bool(canvas.hide_get()):
                canvas.hide_set(True)
                changed = True
        except FBP_DATA_ERRORS:
            continue
    return changed


def any_gp_canvas_solo(scene=None):
    scene = scene or getattr(getattr(bpy, "context", None), "scene", None)
    return any(gp_canvas_solo_active(canvas) for canvas in _scene_gp_drawing_canvases(scene))


def clear_gp_canvas_solo(scene=None, *, except_canvas=None):
    """Clear GP solo flags, optionally preserving one active Drawing Plane."""
    scene = scene or getattr(getattr(bpy, "context", None), "scene", None)
    changed = False
    try:
        except_key = int(except_canvas.as_pointer()) if except_canvas is not None else None
    except FBP_DATA_ERRORS:
        except_key = None
    for canvas in _scene_gp_drawing_canvases(scene):
        try:
            try:
                canvas_key = int(canvas.as_pointer())
            except FBP_DATA_ERRORS:
                canvas_key = None
            desired = bool(except_key is not None and canvas_key == except_key)
            if bool(canvas.get(KEY_CANVAS_SOLO, False)) != desired:
                canvas[KEY_CANVAS_SOLO] = desired
                changed = True
        except FBP_DATA_ERRORS:
            continue
    return changed


def sync_gp_canvas_visibility(context=None):
    context = context or getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        return False
    try:
        layer_solo_active = any(
            bool(getattr(item, "solo", False))
            for item in (getattr(scene, "fbp_layers", ()) or ())
        )
    except FBP_DATA_ERRORS:
        layer_solo_active = False
    canvases = _scene_gp_drawing_canvases(scene)
    canvas_solo_active = any(gp_canvas_solo_active(canvas) for canvas in canvases)
    changed = False
    for canvas in canvases:
        try:
            is_solo_canvas = gp_canvas_solo_active(canvas)
            if canvas_solo_active:
                # GP Solo is exclusive: the active Drawing Plane is the only GP
                # canvas visible, regardless of each row's stored eye state.
                desired_visible = bool(is_solo_canvas)
                desired_render = bool(is_solo_canvas and getattr(canvas, "fbp_gp_canvas_render", True))
            elif layer_solo_active:
                desired_visible = False
                desired_render = False
            else:
                desired_visible = bool(getattr(canvas, "fbp_gp_canvas_visible", True))
                desired_render = bool(getattr(canvas, "fbp_gp_canvas_render", False))

            if bool(canvas.hide_get()) == desired_visible:
                canvas.hide_set(not desired_visible)
                changed = True
            if bool(getattr(canvas, "hide_viewport", False)) == desired_visible:
                canvas.hide_viewport = not desired_visible
                changed = True
            if bool(canvas.hide_render) == desired_render:
                canvas.hide_render = not desired_render
                changed = True
        except FBP_DATA_ERRORS:
            continue
    return changed


def _gp_mask_live_refresh_enabled(canvas):
    """Return whether the current GP canvas owns a live raster mask."""
    return is_gp_canvas(canvas)


def gp_canvas_owner(canvas):
    if not is_gp_canvas(canvas):
        return None
    try:
        owner = getattr(canvas, "fbp_gp_canvas_owner", None)
        if owner is not None and bool(getattr(owner, "is_fbp_control", False)):
            return owner
        owner_id = str(canvas.get(KEY_OWNER_ID, "") or "")
        owner_name = str(canvas.get(KEY_OWNER_NAME, "") or "")
    except FBP_DATA_ERRORS:
        return None
    if owner_name:
        candidate = bpy.data.objects.get(owner_name)
        if candidate is not None and bool(getattr(candidate, "is_fbp_control", False)):
            try:
                if not owner_id or stable_id(candidate, "LAYER") == owner_id:
                    canvas.fbp_gp_canvas_owner = candidate
                    return candidate
            except FBP_DATA_ERRORS:
                pass
    if owner_id:
        candidate = _gp_owner_lookup_by_id(owner_id)
        if candidate is not None:
            try:
                canvas.fbp_gp_canvas_owner = candidate
                canvas[KEY_OWNER_NAME] = candidate.name
            except FBP_DATA_ERRORS:
                pass
            return candidate
    return None


def gp_canvas_for_rig(rig):
    canvases = gp_canvases_for_rig(rig)
    return canvases[0] if canvases else None


def gp_canvases_for_rig(rig):
    """Return every Drawing Plane linked to *rig*, primary canvas first.

    The runtime owner index is rebuilt after load, Undo/Redo, relink and canvas
    creation/deletion. Layer-list drawing therefore avoids a full bpy.data
    object scan for every row while still preserving the primary pointer.
    """
    if rig is None:
        return ()
    owner_index = _GP_DRAWING_OWNER_INDEX if _GP_DRAWING_OWNER_INDEX is not None else _rebuild_gp_owner_index()
    result = []
    seen = set()

    def add(canvas):
        if not is_gp_drawing_canvas(canvas):
            return
        try:
            if not _same_datablock(gp_canvas_owner(canvas), rig):
                return
            key = _canvas_pointer(canvas)
        except FBP_DATA_ERRORS:
            return
        if not key or key in seen:
            return
        seen.add(key)
        result.append(canvas)

    try:
        add(getattr(rig, "fbp_gp_canvas", None))
    except FBP_DATA_ERRORS:
        pass
    for canvas_pointer in tuple(owner_index.get(_canvas_pointer(rig), ())):
        add(_gp_canvas_by_pointer(canvas_pointer))

    if result:
        try:
            if not _same_datablock(getattr(rig, "fbp_gp_canvas", None), result[0]):
                rig.fbp_gp_canvas = result[0]
        except FBP_DATA_ERRORS:
            pass
    return tuple(result)

def gp_mask_slot_contract(effect_id):
    effect_id = str(effect_id or "IMPORTED_MASK").upper()
    index = GP_MASK_EFFECT_IDS.index(effect_id) if effect_id in GP_MASK_EFFECT_IDS else 0
    if index == 0:
        return {"effect_id": effect_id, "canvas": "fbp_gp_mask_canvas", "image": "fbp_imported_mask_image", "source_type": "fbp_imported_mask_source_type", "path": "fbp_imported_mask_path", "invert": "fbp_imported_mask_invert"}
    slot = index + 1
    prefix = f"fbp_gp_mask_slot_{slot}"
    return {"effect_id": effect_id, "canvas": f"{prefix}_canvas", "image": f"{prefix}_image", "source_type": f"{prefix}_source_type", "path": f"{prefix}_path", "invert": f"{prefix}_invert"}


def gp_mask_effect_for_target(rig, target_effect_id, target_instance_id=""):
    """Return an existing GP slot for one concrete target or a safe free slot."""
    try:
        from .geometry_nodes import (
            _fbp_effect_ref, fbp_effect_is_active, fbp_effect_mask_target_ref,
        )
        target_effect_id = str(target_effect_id or "LAYER").upper()
        target_ref = "LAYER" if target_effect_id == "LAYER" else _fbp_effect_ref(
            target_effect_id, str(target_instance_id or "")
        )
        for effect_id in GP_MASK_EFFECT_IDS:
            contract = gp_mask_slot_contract(effect_id)
            canvas = getattr(rig, contract["canvas"], None)
            if (
                canvas is not None
                and fbp_effect_is_active(rig, effect_id)
                and fbp_effect_mask_target_ref(rig, effect_id) == target_ref
            ):
                return effect_id
        for effect_id in GP_MASK_EFFECT_IDS:
            contract = gp_mask_slot_contract(effect_id)
            if not fbp_effect_is_active(rig, effect_id):
                return effect_id
            canvas = getattr(rig, contract["canvas"], None)
            source_type = str(getattr(rig, contract["source_type"], "FILE") or "FILE")
            image = getattr(rig, contract["image"], None)
            if effect_id != "IMPORTED_MASK" and canvas is None and (source_type == "GREASE_PENCIL" or image is None):
                return effect_id
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None
    return None


def gp_mask_assignments(rig):
    result = []
    for effect_id in GP_MASK_EFFECT_IDS:
        contract = gp_mask_slot_contract(effect_id)
        try:
            canvas = getattr(rig, contract["canvas"], None)
        except FBP_DATA_ERRORS:
            canvas = None
        if canvas is not None:
            result.append((effect_id, canvas, contract))
    return tuple(result)


def gp_mask_bindings(canvas):
    """Return cached ``(rig, effect_id, slot_contract)`` bindings for *canvas*.

    Pointer-property callbacks invalidate the process-local index. Animated
    raster refreshes therefore perform an O(1) lookup instead of scanning every
    Frame By Plane rig and every mask slot.
    """
    if not is_gp_canvas(canvas):
        return ()
    index = _GP_BINDING_INDEX if _GP_BINDING_INDEX is not None else _rebuild_gp_binding_index()
    result = []
    for token in tuple(index.get(_canvas_pointer(canvas), ())):
        if not isinstance(token, tuple) or len(token) != 4:
            continue
        rig = _gp_rig_by_pointer(token[0], token[1])
        if rig is not None:
            result.append((rig, token[2], token[3]))
    return tuple(result)


def _apply_canvas_mask_to_binding(canvas, rig, effect_id, slot, *, update_shader=True):
    """Apply one GP Mask contract and optionally rebuild its shader once."""
    try:
        from .geometry_nodes import (
            fbp_effect_mask_target,
            fbp_set_effect_mask_target,
            fbp_update_shader_effect,
        )
        changed = False
        desired_invert = not bool(getattr(canvas, "fbp_gp_mask_invert", False))
        if bool(getattr(rig, slot["invert"], False)) != desired_invert:
            fbp_set_rna_property_silent(rig, slot["invert"], desired_invert)
            changed = True

        desired_factor = max(0.0, min(1.0, float(getattr(canvas, "fbp_gp_mask_opacity", 1.0) or 0.0)))
        # Unknown state preserves the existing mask while a file is loading. A
        # completed safe extraction records False for a genuinely empty canvas.
        if _GP_MASK_GEOMETRY_STATE.get(_canvas_pointer(canvas)) is False:
            desired_factor = 0.0

        factor_prop = str(slot.get("invert", "")).replace("_invert", "_factor")
        if factor_prop and hasattr(rig, factor_prop):
            current_factor = float(getattr(rig, factor_prop, 1.0) or 0.0)
            if abs(current_factor - desired_factor) > 1.0e-6:
                fbp_set_rna_property_silent(rig, factor_prop, desired_factor)
                changed = True

        if fbp_effect_mask_target(rig, effect_id) == "SHADOW":
            fbp_set_effect_mask_target(rig, effect_id, "LAYER")
            changed = True
        if changed and bool(update_shader):
            fbp_update_shader_effect(rig, effect_id, property_names=None)
        return bool(changed)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _sync_canvas_mask_bindings(canvas):
    return sum(
        int(_apply_canvas_mask_to_binding(canvas, rig, effect_id, slot))
        for rig, effect_id, slot in gp_mask_bindings(canvas)
    )


def _sync_canvas_mask_output_bindings(canvas, image):
    """Publish one raster image with one pass and one rebuild per changed slot.

    The old refresh path synchronized all slots, reduced the result to a single
    boolean and then walked the same bindings again. One changed slot therefore
    rebuilt every bound effect, including unaffected rigs.
    """
    try:
        from .geometry_nodes import fbp_update_shader_effect
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0
    changed_count = 0
    for rig, effect_id, contract in gp_mask_bindings(canvas):
        binding_changed = bool(
            _apply_canvas_mask_to_binding(
                canvas, rig, effect_id, contract, update_shader=False
            )
        )
        try:
            if not _same_datablock(getattr(rig, contract["image"], None), image):
                fbp_set_rna_property_silent(rig, contract["image"], image)
                binding_changed = True
            if str(getattr(rig, contract["source_type"], "FILE") or "FILE") != "GREASE_PENCIL":
                fbp_set_rna_property_silent(rig, contract["source_type"], "GREASE_PENCIL")
                binding_changed = True
            if binding_changed:
                fbp_update_shader_effect(rig, effect_id, property_names=None)
                changed_count += 1
        except FBP_DATA_ERRORS:
            continue
    return changed_count


def gp_mask_users(canvas):
    """Return every unique Frame By Plane rig currently driven by *canvas*."""
    result = []
    seen = set()
    for rig, _effect_id, _contract in gp_mask_bindings(canvas):
        key = _canvas_pointer(rig)
        if key not in seen:
            seen.add(key)
            result.append(rig)
    return tuple(result)


def _active_canvas(context):
    if context is None:
        return None
    # The Layer List is authoritative when its active row is a GP child. This
    # keeps Delete/Refresh/Role actions aimed at the row the artist clicked,
    # even if Blender has not yet propagated the object selection change.
    try:
        scene = getattr(context, "scene", None)
        rows = getattr(scene, "fbp_layer_tree_rows", ()) if scene is not None else ()
        index = int(getattr(scene, "fbp_layer_tree_rows_idx", -1)) if scene is not None else -1
        if 0 <= index < len(rows):
            row = rows[index]
            if str(getattr(row, "row_type", "") or "") == "GP_CANVAS":
                canvas = bpy.data.objects.get(str(getattr(row, "canvas_name", "") or ""))
                if is_gp_canvas(canvas):
                    return canvas
    except FBP_DATA_ERRORS:
        pass
    obj = getattr(context, "object", None)
    if is_gp_canvas(obj):
        return obj
    rig = fbp_resolve_rig_from_any_object(obj, context) if obj is not None else None
    if rig is None:
        roots = get_selected_fbp_roots(context)
        rig = roots[0] if roots else None
    return gp_canvas_for_rig(rig)


def _operator_canvas(context, canvas_name=""):
    name = str(canvas_name or "")
    if name:
        canvas = bpy.data.objects.get(name)
        if is_gp_canvas(canvas):
            return canvas
    return _active_canvas(context)


def _canvas_collection(rig, context, *, kind="DRAWING"):
    """Return the collection that should own a Grease Pencil canvas.

    Drawing Planes are now stored directly beside Frame By Plane layers so the
    Layers tree can sort and move them like normal planes.  Internal mask
    canvases remain isolated in the Grease Pencil helper collection.
    """
    parent = get_primary_fbp_collection(rig) if rig is not None else None
    if parent is None:
        parent = getattr(context, "collection", None) or getattr(getattr(context, "scene", None), "collection", None)
    if parent is None:
        return None
    if str(kind or "DRAWING").upper() == "MASK":
        return get_or_create_child_collection(parent, COLLECTION_NAME, color_tag="COLOR_04")
    return parent


def _drawing_stack_items_for_depth(context):
    """Return layer-like stack objects using the same near-to-far depth metric."""
    scene = getattr(context, "scene", None) if context is not None else None
    if scene is None:
        return ()
    items = []
    seen = set()
    try:
        candidates = tuple(iter_scene_fbp_rigs(scene, fallback=True)) + tuple(
            iter_scene_gp_canvases(scene, kind="DRAWING", fallback=True)
        )
        for obj in candidates:
            try:
                if not (is_fbp_layer_object(obj) or is_gp_drawing_canvas(obj)):
                    continue
                key = int(obj.as_pointer())
                if key in seen:
                    continue
                seen.add(key)
                items.append(obj)
            except FBP_DATA_ERRORS:
                continue
    except FBP_DATA_ERRORS:
        return ()
    depth_context = fbp_make_depth_context_cache(context)
    return tuple(sorted(
        items,
        key=lambda obj: (
            fbp_layer_depth_value_from_cache(obj, depth_context),
            str(getattr(obj, "name", "") or ""),
        ),
    ))


def _target_depth_above_reference(context, reference_obj):
    """Return a camera-relative depth just above *reference_obj* in the stack."""
    depth_context = fbp_make_depth_context_cache(context)
    reference_depth = fbp_layer_depth_value_from_cache(reference_obj, depth_context)
    ordered = [obj for obj in _drawing_stack_items_for_depth(context) if obj is not None]
    try:
        ref_index = ordered.index(reference_obj)
    except ValueError:
        ref_index = -1
    if ref_index > 0:
        previous_depth = fbp_layer_depth_value_from_cache(ordered[ref_index - 1], depth_context)
        if previous_depth < reference_depth:
            return (previous_depth + reference_depth) * 0.5, depth_context
    # No nearer item: place slightly closer to the camera than the reference.
    epsilon = max(0.0001, abs(float(reference_depth)) * 0.0001)
    return reference_depth - epsilon, depth_context


def _place_free_canvas_above_reference(context, canvas, reference_rig):
    """Create an unlinked Drawing Plane at the selected plane coordinates.

    The canvas stays independent (UNLINKED/WORLD), but starts in the same
    visual collection and immediately above the selected layer in camera-depth
    order. This makes Shift+A > Frame By Plane > Grease Pencil behave like a
    normal new stack item instead of a helper attached to the source plane.
    """
    if canvas is None or not is_gp_drawing_canvas(canvas) or reference_rig is None:
        return False
    plane = getattr(reference_rig, "fbp_plane_target", None)
    if plane is None:
        return False
    changed = False
    try:
        collection = get_primary_fbp_collection(reference_rig)
        if collection is not None:
            move_object_to_collection(canvas, collection)
            canvas.fbp_collection_name = collection.name
            changed = True
    except FBP_DATA_ERRORS:
        pass
    try:
        canvas.fbp_gp_canvas_owner = None
        canvas[KEY_OWNER_ID] = ""
        canvas[KEY_OWNER_NAME] = ""
        canvas.fbp_gp_attachment_mode = "WORLD"
        canvas.fbp_gp_canvas_lock_transform = False
        if hasattr(canvas, "fbp_gp_auto_sync_timing"):
            canvas.fbp_gp_auto_sync_timing = False

        world = plane.matrix_world.copy()
        target_depth, depth_context = _target_depth_above_reference(context, reference_rig)
        if depth_context.get("has_camera"):
            forward = depth_context["camera_forward"].normalized()
            current_depth = float((world.translation - depth_context["camera_location"]).dot(forward))
            world.translation += forward * (float(target_depth) - current_depth)
        else:
            axis = 1 if getattr(reference_rig, "fbp_is_vertical", False) else 2
            world.translation[axis] += float(target_depth) - float(world.translation[axis])
        canvas.parent = None
        canvas.matrix_parent_inverse = Matrix.Identity(4)
        canvas.matrix_world = world
        canvas.show_in_front = False
        _register_runtime_canvas(canvas)
        changed = True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not place free Grease Pencil canvas above selected layer", exc)
    return changed


def _sanitize_gp_active_material_index(canvas):
    """Clamp corrupted Grease Pencil material indices before slot access.

    Clamp the slot defensively after Undo, material removal or external edits.
    """
    if canvas is None:
        return 0
    try:
        data = getattr(canvas, "data", None)
        materials = getattr(data, "materials", None)
        count = len(materials) if materials is not None else 0
        current = int(getattr(canvas, "active_material_index", 0) or 0)
        target = min(max(current, 0), max(0, count - 1))
        if current != target:
            canvas.active_material_index = target
        return target
    except FBP_DATA_ERRORS:
        return 0


def _ensure_gp_material(canvas):
    data = getattr(canvas, "data", None)
    if data is None:
        return None
    try:
        for material in data.materials:
            if material and bool(getattr(material, "is_grease_pencil", False)):
                _sanitize_gp_active_material_index(canvas)
                return material
    except FBP_DATA_ERRORS:
        pass
    material = bpy.data.materials.new(f"FBP GP Ink • {canvas.name}")
    try:
        bpy.data.materials.create_gpencil_data(material)
        style = material.grease_pencil
        style.color = (0.02, 0.02, 0.02, 1.0)
        # The editable canvas is already displayed at 50% layer opacity. Keep
        # the authored fill fully opaque so Blender creates an unambiguous Fill
        # stroke and the raster mask does not depend on a faint material alpha.
        style.fill_color = (0.02, 0.02, 0.02, 1.0)
        data.materials.append(material)
        _sanitize_gp_active_material_index(canvas)
    except FBP_DATA_ERRORS:
        pass
    return material


def _gp_style_visibility(style):
    if style is None:
        return True, False
    try:
        return bool(style.is_stroke_visible), bool(style.is_fill_visible)
    except FBP_DATA_ERRORS:
        return True, False


def _active_gp_material_style(canvas):
    """Return the active Blender 5.2 Grease Pencil material and style.

    UI drawing must remain read-only, so this helper never creates material
    slots. New Frame By Plane canvases already receive a native GP material.
    """
    if canvas is None:
        return None, None
    material = None
    try:
        data = getattr(canvas, "data", None)
        materials = getattr(data, "materials", None)
        count = len(materials) if materials is not None else 0
        index = int(getattr(canvas, "active_material_index", 0) or 0)
        if count:
            material = materials[min(max(index, 0), count - 1)]
    except FBP_DATA_ERRORS:
        material = None
    try:
        style = getattr(material, "grease_pencil", None) if material else None
    except FBP_DATA_ERRORS:
        style = None
    return material, style


def _draw_gp_52_material_settings(layout, canvas):
    """Expose Blender 5.2 Dots/Squares placement and randomization controls."""
    material, style = _active_gp_material_style(canvas)
    if style is None or not hasattr(style, "placement_mode"):
        return False

    box = layout.box()
    configure_layout(box)
    opened = bool(getattr(canvas, "fbp_gp_ui_show_material_52", False))
    header = box.row(align=True)
    header.prop(
        canvas,
        "fbp_gp_ui_show_material_52",
        text="Stroke Material",
        emboss=False,
        icon="DOWNARROW_HLT" if opened else "RIGHTARROW_THIN",
    )
    header.label(text="", icon="MATERIAL")
    if not opened:
        return True

    if material is not None:
        name_row = box.row(align=True)
        name_row.label(text=str(getattr(material, "name", "Material") or "Material"), icon="MATERIAL")

    mode_row = box.row(align=True)
    mode_row.label(text="Shape", icon="STROKE")
    mode_row.prop(style, "mode", text="")
    stroke_mode = str(getattr(style, "mode", "LINE") or "LINE").upper()
    if stroke_mode not in {"DOTS", "BOX"}:
        hint_row(box, "Dots or Squares enable the Blender 5.2 stamp controls", icon="INFO")
        return True

    placement = box.row(align=True)
    placement.label(text="Placement", icon="DRIVER_DISTANCE")
    placement.prop(style, "placement_mode", text="")
    placement_mode = str(getattr(style, "placement_mode", "RADIUS") or "RADIUS").upper()
    if placement_mode == "COUNT":
        placement.prop(style, "placement_count", text="Count")
    elif placement_mode == "DENSITY":
        placement.prop(style, "placement_density", text="Density")
    else:
        placement.prop(style, "placement_radius_spacing", text="Spacing")

    random_row = box.row(align=True)
    random_row.prop(
        style,
        "use_randomization",
        text="Randomize",
        icon="RNDCURVE",
        toggle=True,
    )
    if not bool(getattr(style, "use_randomization", False)):
        return True

    row = box.row(align=False)
    split = row.split(factor=0.5, align=False)
    split.column(align=False).prop(style, "random_size_factor", text="Size", slider=True)
    split.column(align=False).prop(style, "random_strength_factor", text="Strength", slider=True)
    row = box.row(align=False)
    split = row.split(factor=0.5, align=False)
    split.column(align=False).prop(style, "random_rotation_factor", text="Rotation", slider=True)
    split.column(align=False).prop(style, "random_noise_scale", text="Noise")
    row = box.row(align=False)
    split = row.split(factor=0.5, align=False)
    split.column(align=False).prop(style, "random_hue_factor", text="Hue", slider=True)
    split.column(align=False).prop(style, "random_saturation_factor", text="Saturation", slider=True)
    box.prop(style, "random_value_factor", text="Value", slider=True)
    return True


def _gp_cycles_proxy_style_state(canvas):
    state = []
    materials = tuple(getattr(getattr(canvas, "data", None), "materials", ()) or ())
    for index, material in enumerate(materials or (None,)):
        style = getattr(material, "grease_pencil", None) if material is not None else None
        show_stroke, show_fill = _gp_style_visibility(style)
        try:
            stroke_color = tuple(float(value) for value in getattr(style, "color", (0.02, 0.02, 0.02, 1.0)))
            fill_color = tuple(float(value) for value in getattr(style, "fill_color", stroke_color))
            pixel_size = float(getattr(style, "pixel_size", 100.0) or 100.0)
            stroke_holdout = bool(getattr(style, "use_stroke_holdout", False))
            fill_holdout = bool(getattr(style, "use_fill_holdout", False))
            stroke_mode = str(getattr(style, "mode", "LINE") or "LINE").upper()
            stroke_style = str(getattr(style, "stroke_style", "SOLID") or "SOLID").upper()
            fill_style = str(getattr(style, "fill_style", "SOLID") or "SOLID").upper()
        except FBP_DATA_ERRORS:
            stroke_color = fill_color = (0.02, 0.02, 0.02, 1.0)
            pixel_size = 100.0
            stroke_holdout = fill_holdout = False
            stroke_mode = "LINE"
            stroke_style = fill_style = "SOLID"
        state.append((
            index,
            str(getattr(material, "name", "") or ""),
            show_stroke,
            show_fill,
            tuple(round(value, 6) for value in stroke_color),
            tuple(round(value, 6) for value in fill_color),
            round(pixel_size, 6),
            stroke_holdout,
            fill_holdout,
            stroke_mode,
            stroke_style,
            fill_style,
        ))
    try:
        opacity = round(max(0.0, min(1.0, float(getattr(canvas, "fbp_gp_canvas_opacity", 1.0) or 0.0))), 6)
    except FBP_DATA_ERRORS:
        opacity = 1.0
    return tuple(state), opacity


def _gp_cycles_proxy_supported(canvas):
    materials = tuple(getattr(getattr(canvas, "data", None), "materials", ()) or ())
    for material in materials:
        style = getattr(material, "grease_pencil", None) if material is not None else None
        if style is None:
            continue
        show_stroke, show_fill = _gp_style_visibility(style)
        try:
            if show_stroke and (
                str(getattr(style, "mode", "LINE") or "LINE").upper() != "LINE"
                or str(getattr(style, "stroke_style", "SOLID") or "SOLID").upper() != "SOLID"
            ):
                return False
            if show_fill and str(getattr(style, "fill_style", "SOLID") or "SOLID").upper() != "SOLID":
                return False
        except FBP_DATA_ERRORS:
            return False
    return True


def _gp_cycles_proxy_signature(canvas):
    return repr((GP_CYCLES_PROXY_CONTRACT, _gp_cycles_proxy_style_state(canvas)))


def _gp_cycles_proxy_material(canvas, source_material, index, *, fill=False):
    """Return a stable Cycles proxy material with an in-place shader contract.

    Blender materials are created with ``use_nodes`` disabled.  The old proxy
    path accessed ``material.node_tree`` immediately and could therefore fail on
    the first Cycles proxy build.  It also cleared the complete node tree on
    every style rebuild.  Blender 5.2 now receives one structural rebuild only
    when switching Emission/Holdout contract; color and opacity changes update
    existing sockets in place.
    """
    part = "Fill" if fill else "Stroke"
    name = f"FBP GP Cycles • {canvas.name} • {index + 1} {part}"
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material["fbp_owned"] = True
    material[KEY_CYCLES_PROXY] = True
    style = getattr(source_material, "grease_pencil", None) if source_material is not None else None
    try:
        color = tuple(float(value) for value in getattr(
            style, "fill_color" if fill else "color", (0.02, 0.02, 0.02, 1.0)
        ))
        holdout = bool(getattr(
            style, "use_fill_holdout" if fill else "use_stroke_holdout", False
        ))
    except FBP_DATA_ERRORS:
        color = (0.02, 0.02, 0.02, 1.0)
        holdout = False
    try:
        canvas_opacity = max(
            0.0,
            min(1.0, float(getattr(canvas, "fbp_gp_canvas_opacity", 1.0) or 0.0)),
        )
    except FBP_DATA_ERRORS:
        canvas_opacity = 1.0
    alpha = max(0.0, min(1.0, float(color[3]) * canvas_opacity))

    def set_value(owner, name, value):
        try:
            current = getattr(owner, name)
            if isinstance(value, (tuple, list)):
                if tuple(current) == tuple(value):
                    return False
            elif current == value:
                return False
            setattr(owner, name, value)
            return True
        except FBP_DATA_ERRORS:
            return False

    set_value(material, "diffuse_color", (color[0], color[1], color[2], alpha))
    set_value(material, "surface_render_method", "DITHERED")
    set_value(material, "alpha_threshold", 0.003)
    if not bool(getattr(material, "use_nodes", False)):
        material.use_nodes = True
    tree = getattr(material, "node_tree", None)
    if tree is None:
        raise RuntimeError(f"Could not create Cycles GP material nodes: {name}")

    contract = f"{GP_CYCLES_MATERIAL_CONTRACT}:{'HOLDOUT' if holdout else 'EMISSION'}"
    nodes = tree.nodes
    links = tree.links
    required_names = {
        "FBP Output",
        "FBP Shader",
        "FBP Transparent",
        "FBP Point Opacity",
        "FBP Opacity",
        "FBP Mix",
    }
    current_contract = str(material.get(KEY_CYCLES_MATERIAL_CONTRACT, "") or "")
    rebuild = current_contract != contract or any(nodes.get(name) is None for name in required_names)
    if rebuild:
        nodes.clear()
        output = nodes.new(type="ShaderNodeOutputMaterial")
        output.name = "FBP Output"
        output.location = (420, 0)
        shader = nodes.new(type="ShaderNodeHoldout" if holdout else "ShaderNodeEmission")
        shader.name = "FBP Shader"
        shader.location = (0, 80)
        transparent = nodes.new(type="ShaderNodeBsdfTransparent")
        transparent.name = "FBP Transparent"
        transparent.location = (0, -120)
        point_opacity = nodes.new(type="ShaderNodeAttribute")
        point_opacity.name = "FBP Point Opacity"
        point_opacity.attribute_name = "fbp_gp_opacity"
        point_opacity.location = (-220, -220)
        opacity_multiply = nodes.new(type="ShaderNodeMath")
        opacity_multiply.name = "FBP Opacity"
        opacity_multiply.operation = "MULTIPLY"
        opacity_multiply.location = (0, -220)
        mix = nodes.new(type="ShaderNodeMixShader")
        mix.name = "FBP Mix"
        mix.location = (220, 0)
        links.new(point_opacity.outputs["Fac"], opacity_multiply.inputs[0])
        links.new(opacity_multiply.outputs[0], mix.inputs[0])
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(shader.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], output.inputs[0])
        material[KEY_CYCLES_MATERIAL_CONTRACT] = contract
    else:
        shader = nodes.get("FBP Shader")
        point_opacity = nodes.get("FBP Point Opacity")
        opacity_multiply = nodes.get("FBP Opacity")

    if not holdout and shader is not None:
        set_value(shader.inputs["Color"], "default_value", (color[0], color[1], color[2], 1.0))
        set_value(shader.inputs["Strength"], "default_value", 1.0)
    if point_opacity is not None:
        set_value(point_opacity, "attribute_name", "fbp_gp_opacity")
    if opacity_multiply is not None:
        set_value(opacity_multiply, "operation", "MULTIPLY")
        set_value(opacity_multiply.inputs[1], "default_value", alpha)
    return material


def _gp_cycles_proxy_collection(scene):
    if scene is None:
        return None
    collections = fbp_main_data_collection("collections")
    if collections is None:
        return None
    collection = collections.get(CYCLES_PROXY_COLLECTION_NAME)
    if collection is None:
        collection = collections.new(CYCLES_PROXY_COLLECTION_NAME)
    try:
        if collection.name not in scene.collection.children:
            scene.collection.children.link(collection)
    except (TypeError, RuntimeError, ReferenceError):
        try:
            if collection not in tuple(scene.collection.children):
                scene.collection.children.link(collection)
        except FBP_DATA_ERRORS:
            return None
    try:
        collection.hide_viewport = True
    except FBP_DATA_ERRORS:
        pass
    return collection


def _gp_cycles_proxy_object(canvas, scene=None):
    if not is_gp_drawing_canvas(canvas):
        return None
    try:
        proxy = getattr(canvas, "fbp_gp_cycles_proxy", None)
        if proxy is not None and proxy.name in bpy.data.objects:
            return proxy
    except FBP_DATA_ERRORS:
        proxy = None
    scene = scene or _scene_for_canvas(canvas, getattr(getattr(bpy, "context", None), "scene", None))
    collection = _gp_cycles_proxy_collection(scene)
    if collection is None:
        return None
    mesh = bpy.data.meshes.new(f"FBP GP Cycles Mesh • {canvas.name}")
    proxy = bpy.data.objects.new(f"FBP GP Cycles • {canvas.name}", mesh)
    collection.objects.link(proxy)
    try:
        proxy[KEY_CYCLES_PROXY] = True
        proxy[KEY_CYCLES_PROXY_SOURCE] = canvas.name
        proxy.hide_render = True
        proxy.hide_viewport = True
        proxy.hide_select = True
        proxy.hide_set(True)
        canvas.fbp_gp_cycles_proxy = proxy
        tag_managed(proxy, "GREASE_PENCIL_CYCLES_PROXY", owner_id=stable_id(canvas, "MASK"), user_authored=False)
    except FBP_DATA_ERRORS:
        pass
    return proxy


def _rebuild_gp_cycles_proxy(canvas, scene=None):
    proxy = _gp_cycles_proxy_object(canvas, scene)
    if proxy is None:
        return None
    try:
        proxy.parent = None
        proxy.matrix_world = Matrix.Identity(4)
    except FBP_DATA_ERRORS:
        pass
    old_group = None
    old_materials = ()
    try:
        old_materials = tuple(getattr(proxy.data, "materials", ()) or ())
        for modifier in tuple(proxy.modifiers):
            if modifier.type == "NODES":
                old_group = modifier.node_group
            proxy.modifiers.remove(modifier)
        proxy.data.materials.clear()
    except FBP_DATA_ERRORS:
        pass

    node_group = bpy.data.node_groups.new(f"FBP GP Cycles GN • {canvas.name}", "GeometryNodeTree")
    node_group[KEY_CYCLES_PROXY] = True
    node_group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes = node_group.nodes
    links = node_group.links
    output = nodes.new(type="NodeGroupOutput")
    output.location = (1200, 0)
    object_info = nodes.new(type="GeometryNodeObjectInfo")
    object_info.location = (-1000, 0)
    object_info.inputs["Object"].default_value = canvas
    object_info.inputs["As Instance"].default_value = False
    # Strokes need the source transform before Curve to Mesh so their ribbon
    # profile is oriented correctly in 3D. Fills instead must be generated in
    # the GP local XY plane and transformed only after Fill Curve.
    object_info.transform_space = "RELATIVE"
    to_curves = nodes.new(type="GeometryNodeGreasePencilToCurves")
    to_curves.location = (-800, 80)
    to_curves.inputs["Layers as Instances"].default_value = False
    links.new(object_info.outputs["Geometry"], to_curves.inputs["Grease Pencil"])
    fill_object_info = nodes.new(type="GeometryNodeObjectInfo")
    fill_object_info.location = (-1000, -620)
    fill_object_info.inputs["Object"].default_value = canvas
    fill_object_info.inputs["As Instance"].default_value = False
    fill_object_info.transform_space = "ORIGINAL"
    fill_to_curves = nodes.new(type="GeometryNodeGreasePencilToCurves")
    fill_to_curves.location = (-800, -620)
    fill_to_curves.inputs["Layers as Instances"].default_value = False
    links.new(fill_object_info.outputs["Geometry"], fill_to_curves.inputs["Grease Pencil"])
    material_attribute = nodes.new(type="GeometryNodeInputNamedAttribute")
    material_attribute.data_type = "INT"
    material_attribute.inputs["Name"].default_value = "material_index"
    material_attribute.location = (-800, -300)
    radius_attribute = nodes.new(type="GeometryNodeInputNamedAttribute")
    radius_attribute.data_type = "FLOAT"
    radius_attribute.inputs["Name"].default_value = "radius"
    radius_attribute.location = (-800, -430)
    opacity_attribute = nodes.new(type="GeometryNodeInputNamedAttribute")
    opacity_attribute.data_type = "FLOAT"
    opacity_attribute.inputs["Name"].default_value = "opacity"
    opacity_attribute.location = (-800, -500)
    opacity_switch = nodes.new(type="GeometryNodeSwitch")
    opacity_switch.input_type = "FLOAT"
    opacity_switch.location = (-580, -500)
    opacity_switch.inputs["False"].default_value = 1.0
    links.new(opacity_attribute.outputs["Exists"], opacity_switch.inputs["Switch"])
    links.new(opacity_attribute.outputs["Attribute"], opacity_switch.inputs["True"])
    fill_group = nodes.new(type="GeometryNodeInputNamedAttribute")
    fill_group.data_type = "INT"
    fill_group.inputs["Name"].default_value = "fill_group_id"
    fill_group.location = (-800, -560)
    join = nodes.new(type="GeometryNodeJoinGeometry")
    join.location = (980, 0)
    links.new(join.outputs["Geometry"], output.inputs["Geometry"])

    materials = tuple(getattr(getattr(canvas, "data", None), "materials", ()) or ())
    if not materials:
        materials = (None,)
    y = 360
    for index, source_material in enumerate(materials):
        style = getattr(source_material, "grease_pencil", None) if source_material is not None else None
        show_stroke, show_fill = _gp_style_visibility(style)
        try:
            profile_radius = max(0.0001, min(20.0, float(getattr(style, "pixel_size", 100.0) or 100.0) / 100.0))
        except FBP_DATA_ERRORS:
            profile_radius = 1.0
        compare = nodes.new(type="FunctionNodeCompare")
        compare.data_type = "INT"
        compare.operation = "EQUAL"
        compare.location = (-580, y)
        compare_a = node_input(compare, "A", 0)
        compare_b = node_input(compare, "B", 1)
        if (
            not socket_is_available(compare_a)
            or not socket_is_available(compare_b)
            or compare_a == compare_b
        ):
            raise RuntimeError("Blender 5.2 Compare INT sockets are unavailable")
        compare_b.default_value = index
        links.new(material_attribute.outputs["Attribute"], compare_a)

        if show_stroke:
            separate = nodes.new(type="GeometryNodeSeparateGeometry")
            separate.domain = "CURVE"
            separate.location = (-360, y + 70)
            links.new(to_curves.outputs["Curves"], separate.inputs["Geometry"])
            links.new(compare.outputs["Result"], separate.inputs["Selection"])
            profile = nodes.new(type="GeometryNodeCurvePrimitiveLine")
            profile.mode = "POINTS"
            profile.location = (-130, y + 180)
            # A flat profile preserves the 2D Grease Pencil depth plane. A
            # circular tube would protrude through nearby image planes and
            # defeat Cycles occlusion for thick strokes.
            profile.inputs["Start"].default_value = (0.0, -profile_radius, 0.0)
            profile.inputs["End"].default_value = (0.0, profile_radius, 0.0)
            curve_to_mesh = nodes.new(type="GeometryNodeCurveToMesh")
            curve_to_mesh.location = (120, y + 70)
            curve_to_mesh.inputs["Fill Caps"].default_value = False
            links.new(separate.outputs["Selection"], curve_to_mesh.inputs["Curve"])
            links.new(profile.outputs["Curve"], curve_to_mesh.inputs["Profile Curve"])
            links.new(radius_attribute.outputs["Attribute"], curve_to_mesh.inputs["Scale"])
            set_material = nodes.new(type="GeometryNodeSetMaterial")
            set_material.location = (400, y + 70)
            proxy_material = _gp_cycles_proxy_material(canvas, source_material, index, fill=False)
            proxy.data.materials.append(proxy_material)
            set_material.inputs["Material"].default_value = proxy_material
            links.new(curve_to_mesh.outputs["Mesh"], set_material.inputs["Geometry"])
            store_opacity = nodes.new(type="GeometryNodeStoreNamedAttribute")
            store_opacity.data_type = "FLOAT"
            store_opacity.domain = "POINT"
            store_opacity.location = (650, y + 70)
            store_opacity.inputs["Name"].default_value = "fbp_gp_opacity"
            links.new(set_material.outputs["Geometry"], store_opacity.inputs["Geometry"])
            links.new(opacity_switch.outputs["Output"], store_opacity.inputs["Value"])
            links.new(store_opacity.outputs["Geometry"], join.inputs["Geometry"])

        if show_fill:
            separate_fill = nodes.new(type="GeometryNodeSeparateGeometry")
            separate_fill.domain = "CURVE"
            separate_fill.location = (-130, y - 130)
            links.new(fill_to_curves.outputs["Curves"], separate_fill.inputs["Geometry"])
            links.new(compare.outputs["Result"], separate_fill.inputs["Selection"])
            fill_curve = nodes.new(type="GeometryNodeFillCurve")
            fill_curve.location = (120, y - 130)
            links.new(separate_fill.outputs["Selection"], fill_curve.inputs["Curve"])
            links.new(fill_group.outputs["Attribute"], fill_curve.inputs["Group ID"])
            set_fill_material = nodes.new(type="GeometryNodeSetMaterial")
            set_fill_material.location = (400, y - 130)
            proxy_material = _gp_cycles_proxy_material(canvas, source_material, index, fill=True)
            proxy.data.materials.append(proxy_material)
            set_fill_material.inputs["Material"].default_value = proxy_material
            links.new(fill_curve.outputs["Mesh"], set_fill_material.inputs["Geometry"])
            store_fill_opacity = nodes.new(type="GeometryNodeStoreNamedAttribute")
            store_fill_opacity.data_type = "FLOAT"
            store_fill_opacity.domain = "POINT"
            store_fill_opacity.location = (650, y - 130)
            store_fill_opacity.inputs["Name"].default_value = "fbp_gp_opacity"
            links.new(set_fill_material.outputs["Geometry"], store_fill_opacity.inputs["Geometry"])
            links.new(opacity_switch.outputs["Output"], store_fill_opacity.inputs["Value"])
            transform_fill = nodes.new(type="GeometryNodeTransform")
            transform_fill.location = (850, y - 130)
            transform_fill.inputs["Mode"].default_value = "Matrix"
            links.new(store_fill_opacity.outputs["Geometry"], transform_fill.inputs["Geometry"])
            links.new(fill_object_info.outputs["Transform"], transform_fill.inputs["Transform"])
            links.new(transform_fill.outputs["Geometry"], join.inputs["Geometry"])
        y -= 460

    modifier = proxy.modifiers.new("Frame By Plane Cycles GP", "NODES")
    modifier.node_group = node_group
    try:
        proxy[KEY_CYCLES_PROXY_SIGNATURE] = _gp_cycles_proxy_signature(canvas)
        proxy[KEY_CYCLES_PROXY_SOURCE] = canvas.name
        proxy.update_tag()
    except FBP_DATA_ERRORS:
        pass
    # Do not delete replaced proxy IDs from an automatic rebuild. Blender 5.2
    # Undo may still contain references to their material Image Texture nodes.
    # Zero-user IDs remain harmless and are collected by explicit Orphan Purge.
    if old_group is not None and int(getattr(old_group, "users", 0) or 0) == 0:
        try:
            old_group["fbp_orphan_candidate"] = True
        except FBP_DATA_ERRORS:
            pass
    for material in old_materials:
        try:
            if material is not None and bool(material.get(KEY_CYCLES_PROXY, False)) and int(getattr(material, "users", 0) or 0) == 0:
                material["fbp_orphan_candidate"] = True
        except FBP_DATA_ERRORS:
            continue
    return proxy


def ensure_gp_cycles_proxy(canvas, scene=None):
    if not is_gp_drawing_canvas(canvas):
        return None
    if not _gp_cycles_proxy_supported(canvas):
        try:
            existing = getattr(canvas, "fbp_gp_cycles_proxy", None)
            if existing is not None:
                existing.hide_render = True
        except FBP_DATA_ERRORS:
            pass
        return None
    proxy = _gp_cycles_proxy_object(canvas, scene)
    if proxy is None:
        return None
    try:
        expected = _gp_cycles_proxy_signature(canvas)
        current = str(proxy.get(KEY_CYCLES_PROXY_SIGNATURE, "") or "")
        valid_modifier = any(modifier.type == "NODES" and modifier.node_group for modifier in proxy.modifiers)
    except FBP_DATA_ERRORS:
        expected, current, valid_modifier = "", "!", False
    if current != expected or not valid_modifier:
        proxy = _rebuild_gp_cycles_proxy(canvas, scene)
    if proxy is not None:
        try:
            if getattr(proxy, "parent", None) is not None:
                proxy.parent = None
            identity = Matrix.Identity(4)
            current = getattr(proxy, "matrix_world", None)
            if current is None or any(
                abs(float(current[row][column]) - float(identity[row][column])) > 1.0e-9
                for row in range(4)
                for column in range(4)
            ):
                proxy.matrix_world = identity
        except FBP_DATA_ERRORS:
            pass
    return proxy


def fbp_prepare_gp_cycles_render_assets(scene):
    """Build and validate every GP Cycles proxy before a render job starts.

    This function is intended for explicit preflight operators, including the
    isolated background child.  It may create Objects, Materials and node groups
    and must therefore never be called from render/depsgraph handlers.
    """
    if scene is None or str(getattr(getattr(scene, "render", None), "engine", "") or "") != "CYCLES":
        return 0, 0
    required = 0
    ready = 0
    for canvas in _scene_gp_drawing_canvases(scene):
        if not _gp_cycles_proxy_supported(canvas):
            # Unsupported textured/styled GP materials remain on Blender's
            # native Cycles path; only FBP proxy-compatible canvases are a hard
            # preflight requirement.
            continue
        required += 1
        try:
            proxy = ensure_gp_cycles_proxy(canvas, scene)
            if proxy is None:
                continue
            valid_nodes = any(
                modifier.type == "NODES" and getattr(modifier, "node_group", None) is not None
                for modifier in tuple(getattr(proxy, "modifiers", ()) or ())
            )
            signature_ok = (
                str(proxy.get(KEY_CYCLES_PROXY_SIGNATURE, "") or "")
                == _gp_cycles_proxy_signature(canvas)
            )
            if valid_nodes and signature_ok:
                ready += 1
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not prepare Grease Pencil Cycles proxy", exc)
    return required, ready


def _gp_cycles_proxy_live_sync_needed(canvas, scene=None):
    """Return whether a live drawing edit must update a Cycles proxy now.

    Eevee/Workbench sessions do not sample the proxy, so rebuilding it after
    each stroke only adds idle CPU/RNA work. Switching to Cycles or starting a
    render triggers the existing dependency/preflight paths and catches up from
    the current source drawing.
    """
    if not is_gp_drawing_canvas(canvas):
        return False
    target_scene = _scene_for_canvas(canvas, scene)
    try:
        return (
            str(getattr(getattr(target_scene, "render", None), "engine", "") or "")
            == "CYCLES"
        )
    except FBP_DATA_ERRORS:
        return False


def schedule_gp_cycles_proxy_sync(scene=None, canvas=None, *, first_interval=0.05):
    """Build or repair Cycles proxies only from Blender's idle timer.

    Render callbacks may toggle existing visibility, but never create/remove
    Objects, Meshes, Materials or node groups while render/viewport depsgraphs
    are being iterated.
    """
    scene = scene or getattr(getattr(bpy, "context", None), "scene", None)
    if scene is None:
        return False
    scene_key = fbp_obj_runtime_key(scene)
    scene_name = str(getattr(scene, "name_full", getattr(scene, "name", "")) or "")
    canvas_key = fbp_obj_runtime_key(canvas) if canvas is not None else None
    canvas_name = str(getattr(canvas, "name_full", getattr(canvas, "name", "")) or "") if canvas is not None else ""

    def _sync():
        target_scene = fbp_find_id_by_runtime_key(
            getattr(bpy.data, "scenes", ()), scene_key, scene_name
        )
        if target_scene is None:
            return None
        if canvas_key is not None:
            target_canvas = fbp_find_id_by_runtime_key(
                getattr(bpy.data, "objects", ()), canvas_key, canvas_name
            )
            if target_canvas is not None and is_gp_drawing_canvas(target_canvas):
                ensure_gp_cycles_proxy(target_canvas, target_scene)
            return None
        cleanup_gp_cycles_proxies()
        for target_canvas in _scene_gp_drawing_canvases(target_scene):
            ensure_gp_cycles_proxy(target_canvas, target_scene)
        return None

    key = f"gp.cycles.proxy_sync.{scene_key}.{canvas_key or 0}"
    return bool(schedule_once(key, _sync, first_interval=first_interval))


def _restore_gp_cycles_render_state():
    """Restore proxy visibility without retaining RNA wrappers across render."""
    objects = getattr(bpy.data, "objects", ())
    for _key, payload in tuple(_GP_CYCLES_RENDER_BACKUP.items()):
        try:
            if not isinstance(payload, dict):
                continue
            for slot in ("canvas", "proxy"):
                item = payload.get(slot)
                if not isinstance(item, dict):
                    continue
                obj = fbp_find_id_by_runtime_key(
                    objects, item.get("object_key"), str(item.get("name", "") or "")
                )
                previous = bool(item.get("hide_render", False))
                if obj is not None and bool(getattr(obj, "hide_render", False)) != previous:
                    obj.hide_render = previous
        except FBP_DATA_ERRORS:
            pass
    _GP_CYCLES_RENDER_BACKUP.clear()


def _set_gp_cycles_render_visibility(key, canvas, proxy, *, canvas_hidden, proxy_hidden):
    """Store primitive identities and write only changed visibility values."""
    payload = _GP_CYCLES_RENDER_BACKUP.get(key)
    for slot, obj, desired in (
        ("canvas", canvas, bool(canvas_hidden)),
        ("proxy", proxy, bool(proxy_hidden)),
    ):
        if obj is None:
            continue
        current = bool(getattr(obj, "hide_render", False))
        if current == desired:
            continue
        if payload is None:
            payload = {}
            _GP_CYCLES_RENDER_BACKUP[key] = payload
        if slot not in payload:
            payload[slot] = {
                "object_key": fbp_obj_runtime_key(obj),
                "name": str(getattr(obj, "name_full", getattr(obj, "name", "")) or ""),
                "hide_render": current,
            }
        obj.hide_render = desired


def fbp_gp_cycles_render_setup(scene, _depsgraph=None):
    """Toggle already-built Cycles proxies once at render initialization.

    Structural proxy creation/rebuild is handled by idle tasks. This callback
    performs only stable visibility writes before Blender creates the render
    pipeline depsgraph.
    """
    if scene is None or str(getattr(getattr(scene, "render", None), "engine", "") or "") != "CYCLES":
        return
    canvases = _scene_gp_drawing_canvases(scene)
    solo = any(gp_canvas_solo_active(canvas) for canvas in canvases)
    try:
        plane_solo = any(bool(getattr(item, "solo", False)) for item in getattr(scene, "fbp_layers", ()) or ())
    except FBP_DATA_ERRORS:
        plane_solo = False
    for canvas in canvases:
        try:
            proxy = getattr(canvas, "fbp_gp_cycles_proxy", None)
            if proxy is None or not bool(proxy.get(KEY_CYCLES_PROXY, False)):
                fbp_warn_once(
                    f"gp_cycles_proxy_missing:{getattr(canvas, 'name', 'canvas')}",
                    "Cycles proxy was not ready at render start; it will be rebuilt while Blender is idle",
                )
                continue
            key = _canvas_pointer(canvas)
            valid_nodes = any(
                modifier.type == "NODES" and getattr(modifier, "node_group", None) is not None
                for modifier in tuple(getattr(proxy, "modifiers", ()) or ())
            )
            if not valid_nodes:
                _set_gp_cycles_render_visibility(
                    key, canvas, proxy, canvas_hidden=True, proxy_hidden=True
                )
                fbp_warn_once(
                    f"gp_cycles_proxy_invalid:{getattr(canvas, 'name', 'canvas')}",
                    "Invalid Cycles proxy was skipped; rebuild is deferred until Blender is idle",
                )
                continue
            expected = _gp_cycles_proxy_signature(canvas)
            if str(proxy.get(KEY_CYCLES_PROXY_SIGNATURE, "") or "") != expected:
                fbp_warn_once(
                    f"gp_cycles_proxy_stale:{getattr(canvas, 'name', 'canvas')}",
                    "Cycles proxy style was stale at render start; rebuild is deferred until Blender is idle",
                )
            enabled = bool(getattr(canvas, "fbp_gp_canvas_render", False))
            enabled = enabled and bool(getattr(canvas, "fbp_gp_canvas_visible", True))
            if solo:
                enabled = enabled and gp_canvas_solo_active(canvas)
            elif plane_solo:
                enabled = False
            _set_gp_cycles_render_visibility(
                key, canvas, proxy, canvas_hidden=True, proxy_hidden=not enabled
            )
        except FBP_DATA_ERRORS:
            continue


def fbp_gp_cycles_render_idle_restore():
    """Restore proxy visibility from the core idle render watchdog."""
    _restore_gp_cycles_render_state()
    return True



def _quarantine_gp_cycles_proxy(proxy):
    """Disable an unused runtime proxy without deleting IDs outside an operator."""
    if proxy is None:
        return False
    try:
        if not bool(proxy.get(KEY_CYCLES_PROXY, False)):
            return False
        proxy.hide_render = True
        proxy.hide_viewport = True
        proxy["fbp_orphan_candidate"] = True
        return True
    except FBP_DATA_ERRORS:
        return False


def cleanup_gp_cycles_proxies():
    if not fbp_main_data_ready("scenes", "objects", "collections"):
        return 0
    live = set()
    # Proxies live in one internal collection shared by scenes. Always inspect
    # every scene before deleting one, otherwise rendering Scene A could remove
    # a valid proxy used only by Scene B.
    scenes = tuple(fbp_main_data_collection("scenes", ()) or ())
    for target_scene in scenes:
        for canvas in iter_scene_gp_canvases(target_scene, kind="DRAWING", fallback=True):
            if not is_gp_drawing_canvas(canvas):
                continue
            try:
                proxy = getattr(canvas, "fbp_gp_cycles_proxy", None)
                if proxy is not None:
                    live.add(_canvas_pointer(proxy))
            except FBP_DATA_ERRORS:
                continue
    removed = 0
    for proxy in tuple(fbp_main_data_collection("objects", ()) or ()):
        try:
            if not bool(proxy.get(KEY_CYCLES_PROXY, False)) or _canvas_pointer(proxy) in live:
                continue
        except FBP_DATA_ERRORS:
            continue
        removed += int(_quarantine_gp_cycles_proxy(proxy))
    collections = fbp_main_data_collection("collections")
    collection = collections.get(CYCLES_PROXY_COLLECTION_NAME) if collections is not None else None
    try:
        if collection is not None and not tuple(collection.objects):
            collection["fbp_orphan_candidate"] = True
    except FBP_DATA_ERRORS:
        pass
    return removed


def _ensure_gp_layer(canvas):
    data = getattr(canvas, "data", None)
    if data is None:
        return None
    try:
        layer = data.layers.active
        if layer is None:
            layer_name = "FBP Mask" if is_gp_mask_canvas(canvas) else "Drawing"
            layer = data.layers.new(layer_name, set_active=True)
        layer.use_onion_skinning = bool(getattr(canvas, "fbp_gp_onion_skin", True))
        return layer
    except FBP_DATA_ERRORS:
        return None


def _coerce_frame_number(value, default=1):
    """Coerce a frame value while preserving valid frame zero."""
    try:
        return int(default) if value is None else int(value)
    except (TypeError, ValueError, OverflowError, AttributeError, ReferenceError):
        return int(default)


def _scene_current_frame_number(scene, default=1):
    """Return ``Scene.frame_current`` without treating frame zero as missing."""
    try:
        value = getattr(scene, "frame_current", None)
    except (AttributeError, ReferenceError):
        value = None
    return _coerce_frame_number(value, default)


def _ensure_gp_current_keyframe(canvas, context=None, *, frame_number=None):
    """Ensure the active Grease Pencil layer has a blank drawing on the current frame.

    New GP Masks and Drawing Planes should be immediately drawable at the user's
    current timeline position. Blender may otherwise expose an older drawing or no
    explicit keyframe, which makes the first stroke/Undo state feel delayed or
    ambiguous.
    """
    if not is_gp_canvas(canvas):
        return False
    layer = _ensure_gp_layer(canvas)
    if layer is None:
        return False
    if frame_number is None:
        try:
            scene = getattr(context, "scene", None) if context is not None else getattr(bpy.context, "scene", None)
            frame_number = _scene_current_frame_number(scene, 1)
        except FBP_DATA_ERRORS:
            frame_number = 1
    try:
        frame_number = int(frame_number)
    except (TypeError, ValueError):
        frame_number = 1
    try:
        for frame in tuple(getattr(layer, "frames", ()) or ()):  # existing explicit key
            if int(getattr(frame, "frame_number", 0) or 0) == frame_number:
                try:
                    if hasattr(layer.frames, "active"):
                        layer.frames.active = frame
                except FBP_DATA_ERRORS:
                    pass
                return False
        try:
            frame = layer.frames.new(frame_number, active=True)
        except TypeError:
            frame = layer.frames.new(frame_number)
            try:
                if hasattr(layer.frames, "active"):
                    layer.frames.active = frame
            except FBP_DATA_ERRORS:
                pass
        data = getattr(canvas, "data", None)
        if data is not None:
            data.update_tag()
        if is_gp_mask_canvas(canvas):
            mark_gp_mask_dirty(canvas, schedule=True, geometry=True, scene=getattr(context, "scene", None) if context is not None else None)
        return True
    except FBP_DATA_ERRORS:
        return False


def _apply_canvas_opacity(canvas):
    """Apply the artist-facing viewport Visibility to every GP layer.

    This is visual-only for Frame By Plane masks: rasterization deliberately
    ignores GP layer opacity so the mask remains identical at 0% and 100%
    canvas Visibility.
    """
    try:
        opacity = max(0.0, min(1.0, float(getattr(canvas, "fbp_gp_canvas_opacity", 0.5) or 0.0)))
        data = getattr(canvas, "data", None)
        if data is None:
            return False
        changed = False
        for layer in tuple(getattr(data, "layers", ()) or ()):
            if abs(float(getattr(layer, "opacity", 1.0) or 0.0) - opacity) > 1.0e-6:
                layer.opacity = opacity
                changed = True
        if changed:
            data.update_tag()
        return changed
    except FBP_DATA_ERRORS:
        return False


def _refresh_layer_tree(context=None, *, update_compositor=True):
    try:
        call_service(
            "layers.refresh_tree",
            context or getattr(bpy, "context", None),
            update_compositor=bool(update_compositor),
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def _gp_layer_name_prefix(layer, *, limit=14):
    """Return the short source-layer prefix used for new Drawing Plane names."""
    raw = str(getattr(layer, "name", "") or "Layer")
    # Blender may append .001 suffixes or users may keep long imported file
    # names.  The Layer List only needs a compact cue, not the complete source.
    clean = raw.rsplit(".", 1)[0] if raw.rsplit(".", 1)[-1].isdigit() else raw
    clean = " ".join(clean.replace("_", " ").replace("-", " ").split())
    if not clean:
        clean = "Layer"
    return clean[:max(4, int(limit))].rstrip()


def _gp_drawing_name_for_layer(layer):
    return f"GP - {_gp_layer_name_prefix(layer)}"


def _tag_canvas(canvas, rig=None, *, kind="DRAWING"):
    kind = str(kind or "DRAWING").upper()
    if kind not in {"DRAWING", "MASK"}:
        kind = "DRAWING"
    layer_id = ensure_layer_identity(rig) if rig is not None else ""
    ensure_mask_identity(canvas)
    try:
        canvas[KEY_IS_CANVAS] = True
        canvas[KEY_CANVAS_KIND] = kind
        canvas[KEY_OWNER_ID] = layer_id
        canvas[KEY_OWNER_NAME] = rig.name if rig is not None else ""
        canvas[KEY_SCHEMA] = FBP_GP_SCHEMA_VERSION
        canvas.fbp_gp_canvas_kind = kind
        canvas.fbp_gp_canvas_owner = rig
        if rig is not None and kind == "DRAWING":
            primary = getattr(rig, "fbp_gp_canvas", None)
            if not is_gp_drawing_canvas(primary) or not _same_datablock(gp_canvas_owner(primary), rig):
                rig.fbp_gp_canvas = canvas
    except FBP_DATA_ERRORS:
        pass
    _register_runtime_canvas(canvas, refresh_dependencies=False, invalidate_owner=False)
    _invalidate_gp_binding_cache()
    try:
        tag_managed(
            canvas,
            "GREASE_PENCIL_MASK" if kind == "MASK" else "GREASE_PENCIL_CANVAS",
            owner_id=layer_id,
            user_authored=True,
        )
    except (ValueError, AttributeError, ReferenceError, RuntimeError, TypeError):
        pass


def _matrix_world_keep(obj, parent):
    try:
        world = obj.matrix_world.copy()
        obj.parent = parent
        obj.matrix_parent_inverse = parent.matrix_world.inverted_safe() if parent else Matrix.Identity(4)
        obj.matrix_world = world
    except FBP_DATA_ERRORS:
        pass


def make_drawing_canvas_stack_editable(canvas):
    """Detach a Drawing Plane from transform lock so stack reordering persists."""
    if not is_gp_drawing_canvas(canvas):
        return False
    changed = False
    try:
        world = canvas.matrix_world.copy()
        if str(getattr(canvas, "fbp_gp_attachment_mode", "WORLD") or "WORLD") != "WORLD":
            canvas.fbp_gp_attachment_mode = "WORLD"
            changed = True
        if bool(getattr(canvas, "fbp_gp_canvas_lock_transform", False)):
            canvas.fbp_gp_canvas_lock_transform = False
            changed = True
        if getattr(canvas, "parent", None) is not None:
            canvas.parent = None
            canvas.matrix_parent_inverse = Matrix.Identity(4)
            canvas.matrix_world = world
            changed = True
        if bool(getattr(canvas, "show_in_front", False)):
            canvas.show_in_front = False
            changed = True
        if changed:
            canvas.update_tag()
    except FBP_DATA_ERRORS:
        return changed
    return changed


def sync_canvas_transform(canvas, scene=None):
    if not is_gp_canvas(canvas):
        return False
    rig = gp_canvas_owner(canvas)
    plane = getattr(rig, "fbp_plane_target", None) if rig is not None else None
    target_scene = _scene_for_canvas(canvas, scene)
    camera = getattr(target_scene, "camera", None) if target_scene else None
    try:
        mode = str(getattr(canvas, "fbp_gp_attachment_mode", "PLANE") or "PLANE")
        offset_x = float(getattr(canvas, "fbp_gp_canvas_offset_x", 0.0) or 0.0)
        offset_y = float(getattr(canvas, "fbp_gp_canvas_offset_y", 0.0) or 0.0)
        distance = float(getattr(canvas, "fbp_gp_canvas_distance", 0.003) or 0.0)
        scale = max(0.0001, float(getattr(canvas, "fbp_gp_canvas_scale", 1.0) or 1.0))
    except FBP_DATA_ERRORS:
        return False

    changed = False
    try:
        if mode == "PLANE" and plane is not None:
            if canvas.parent is not plane:
                canvas.parent = plane
                canvas.matrix_parent_inverse = Matrix.Identity(4)
                changed = True
            desired_location = Vector((offset_x, offset_y, distance))
            if (canvas.location - desired_location).length > 1.0e-8:
                canvas.location = desired_location
                changed = True
            # Grease Pencil and FBP image cards both use local XY with +Z as
            # their surface normal. The old mask-only +90° X rotation put the
            # canvas on XZ, producing a visibly wrong orientation and distorted
            # plane-space projection. Masks now align exactly like drawing planes.
            desired_rotation = (0.0, 0.0, 0.0)
            if any(abs(float(current) - float(target)) > 1.0e-8 for current, target in zip(canvas.rotation_euler, desired_rotation, strict=False)):
                canvas.rotation_euler = desired_rotation
                changed = True
            desired_scale = Vector((scale, scale, scale))
            if (canvas.scale - desired_scale).length > 1.0e-8:
                canvas.scale = desired_scale
                changed = True
        elif mode == "CAMERA" and camera is not None:
            if canvas.parent is not camera:
                canvas.parent = camera
                canvas.matrix_parent_inverse = Matrix.Identity(4)
                changed = True
            camera_distance = max(0.01, abs(distance))
            desired_location = Vector((offset_x, offset_y, -camera_distance))
            if (canvas.location - desired_location).length > 1.0e-8:
                canvas.location = desired_location
                changed = True
            if any(abs(float(value)) > 1.0e-8 for value in canvas.rotation_euler):
                canvas.rotation_euler = (0.0, 0.0, 0.0)
                changed = True
            desired_scale = Vector((scale, scale, scale))
            if (canvas.scale - desired_scale).length > 1.0e-8:
                canvas.scale = desired_scale
                changed = True
        elif mode == "WORLD" and canvas.parent is not None:
            _matrix_world_keep(canvas, None)
            changed = True

        render = bool(getattr(canvas, "fbp_gp_canvas_render", False))
        if not is_gp_mask_canvas(canvas):
            visible = bool(getattr(canvas, "fbp_gp_canvas_visible", True))
            if bool(canvas.hide_get()) == visible:
                canvas.hide_set(not visible)
                changed = True
        if bool(canvas.hide_render) == render:
            canvas.hide_render = not render
            changed = True
        lock = bool(getattr(canvas, "fbp_gp_canvas_lock_transform", True))
        lock_location = (lock, lock, lock)
        lock_rotation = (lock, lock, lock)
        lock_scale = (lock, lock, lock)
        if tuple(canvas.lock_location) != lock_location:
            canvas.lock_location = lock_location
            changed = True
        if tuple(canvas.lock_rotation) != lock_rotation:
            canvas.lock_rotation = lock_rotation
            changed = True
        if tuple(canvas.lock_scale) != lock_scale:
            canvas.lock_scale = lock_scale
            changed = True
        # Drawing Planes must participate in normal viewport depth.  Keeping
        # show_in_front enabled forced GP above every image plane, making the
        # Layer Stack order visually meaningless.  Mask canvases are internal,
        # so they also do not need x-ray/front drawing here.
        if bool(getattr(canvas, "show_in_front", False)):
            canvas.show_in_front = False
            changed = True
    except FBP_DATA_ERRORS:
        return changed
    if changed:
        try:
            canvas.update_tag()
        except FBP_DATA_ERRORS:
            pass
    return changed


def _initialize_canvas_defaults(canvas, rig=None, *, kind="DRAWING"):
    default_opacity = 0.5 if kind == "MASK" else 1.0
    try:
        canvas[KEY_LAST_ATTACHMENT] = "PLANE" if rig is not None else "WORLD"
        canvas[KEY_PLANE_DISTANCE] = 0.003
        canvas[KEY_CAMERA_DISTANCE] = 1.0
        canvas.fbp_gp_canvas_kind = kind
        canvas.fbp_gp_attachment_mode = "PLANE" if rig is not None else "WORLD"
        canvas.fbp_gp_canvas_distance = 0.003
        canvas.fbp_gp_canvas_scale = 1.0
        canvas.fbp_gp_canvas_visible = True
        canvas.fbp_gp_canvas_opacity = default_opacity
        canvas.fbp_gp_canvas_render = kind == "DRAWING"
        canvas.fbp_gp_canvas_lock_transform = rig is not None
        canvas.use_grease_pencil_lights = False
        if kind == "DRAWING" and getattr(canvas, "data", None) is not None:
            canvas.data.stroke_depth_order = "3D"
        canvas.fbp_gp_onion_skin = True
        canvas.fbp_gp_reference_opacity = float(getattr(rig, "fbp_opacity", 1.0) or 1.0) if rig is not None else 1.0
        canvas[KEY_REFERENCE_OPACITY] = float(getattr(rig, "fbp_opacity", 1.0) or 1.0) if rig is not None else 1.0
        if kind == "MASK":
            canvas.fbp_gp_mask_source = "AUTO"
            canvas.fbp_gp_mask_invert = False
            canvas.fbp_gp_mask_opacity = 1.0
            canvas.fbp_gp_mask_quality = DEFAULT_GP_MASK_QUALITY
            canvas.fbp_gp_mask_preview_quality = DEFAULT_GP_MASK_PREVIEW_QUALITY
            canvas.fbp_gp_mask_feather = 0.0
            canvas.fbp_gp_mask_expand = DEFAULT_GP_MASK_EXPAND
        canvas[KEY_MASK_DIRTY] = True
        canvas[KEY_MASK_GEOMETRY_DIRTY] = True
        canvas[KEY_MASK_BAKED] = False
        canvas[KEY_MASK_FRAME_SENSITIVE] = False
        canvas[KEY_MASK_GEOMETRY_FRAME_SENSITIVE] = False
    except FBP_DATA_ERRORS:
        pass
    _apply_canvas_opacity(canvas)
    sync_canvas_transform(canvas)


def _new_canvas(context, rig=None, *, kind="DRAWING", name="", reuse_existing=True):
    kind = str(kind or "DRAWING").upper()
    if kind == "DRAWING" and rig is not None and bool(reuse_existing):
        existing = gp_canvas_for_rig(rig)
        if existing is not None:
            return existing, False
    if kind == "MASK" and rig is None:
        return None, False
    if rig is not None and getattr(rig, "fbp_plane_target", None) is None:
        return None, False
    base = name.strip() if str(name or "").strip() else (
        f"GP Mask • {getattr(rig, 'name', 'Layer')}" if kind == "MASK"
        else (_gp_drawing_name_for_layer(rig) if rig is not None else "GP - Layer")
    )
    data = bpy.data.grease_pencils.new(f"{base} Data")
    canvas = bpy.data.objects.new(base, data)
    collection = _canvas_collection(rig, context, kind=kind)
    if collection is None:
        bpy.data.objects.remove(canvas, do_unlink=True)
        bpy.data.grease_pencils.remove(data)
        return None, False
    collection.objects.link(canvas)
    _tag_canvas(canvas, rig, kind=kind)
    _ensure_gp_layer(canvas)
    _ensure_gp_material(canvas)
    _initialize_canvas_defaults(canvas, rig, kind=kind)
    if kind == "MASK":
        sync_gp_mask_interaction_state(context=context, scene=getattr(context, "scene", None))
    _ensure_gp_current_keyframe(canvas, context)
    if rig is None:
        try:
            canvas.matrix_world.translation = getattr(getattr(context, "scene", None), "cursor", None).location.copy()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    _refresh_layer_tree(context)
    return canvas, True


def _create_mask_canvas(rig, context):
    """Create a dedicated internal GP mask, never represented in the Layer List."""
    for _effect_id, assigned, _slot in gp_mask_assignments(rig):
        if is_gp_mask_canvas(assigned) and _same_datablock(gp_canvas_owner(assigned), rig):
            return assigned, False
    return _new_canvas(context, rig, kind="MASK")


def _plane_bounds(rig):
    """Return the image-bearing rectangle used by GP raster masks.

    Extend enlarges only the border mesh and UV domain. Sampling GP geometry over
    those enlarged bounds shrinks or offsets the raster while the shader still
    reads the source-image UVs. Use the cropped source rectangle so GP masks stay
    stable when Extend is enabled on image and procedural color planes.
    """
    if rig is not None and bool(getattr(rig, "is_fbp_control", False)):
        try:
            from .builder import fbp_plane_reference_bounds
            _source, cropped, _extended, _uv = fbp_plane_reference_bounds(rig)
            return tuple(float(value) for value in cropped)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    mesh = getattr(plane, "data", None) if plane else None
    try:
        coords = [(float(v.co.x), float(v.co.y)) for v in mesh.vertices]
    except FBP_DATA_ERRORS:
        coords = []
    if not coords:
        return (-1.0, 1.0, -1.0, 1.0)
    xs = [point[0] for point in coords]
    ys = [point[1] for point in coords]
    return (min(xs), max(xs), min(ys), max(ys))


def _gp_mask_image_bounds_match(image, bounds, tolerance=1.0e-7):
    if image is None:
        return False
    try:
        stored = tuple(float(value) for value in image.get("fbp_gp_mask_bounds", ()) or ())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    return bool(
        len(stored) == 4
        and all(abs(current - expected) <= tolerance for current, expected in zip(stored, bounds, strict=True))
    )


def _current_drawing_entry(layer, frame_number=None):
    """Return ``(source_frame, drawing)`` for one GP layer exposure."""
    try:
        if frame_number is None:
            frame = layer.current_frame()
            if frame is None:
                return None, None
            return int(getattr(frame, "frame_number", 0) or 0), getattr(frame, "drawing", None)
        selected = None
        target = int(frame_number)
        for candidate in tuple(getattr(layer, "frames", ()) or ()):
            number = int(getattr(candidate, "frame_number", 0) or 0)
            if number > target:
                break
            selected = candidate
        if selected is None:
            return None, None
        return int(getattr(selected, "frame_number", 0) or 0), getattr(selected, "drawing", None)
    except FBP_DATA_ERRORS:
        return None, None


def _canvas_exposure_key(canvas, frame_number):
    """Return the indexed cache key for drawings exposed at a scene frame."""
    return _canvas_exposure_state(canvas, frame_number)[0]


def _matrix_signature(matrix):
    try:
        return tuple(round(float(value), 9) for row in matrix for value in row)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ()


def _geometry_context_signature(canvas, rig, bounds, scene=None):
    """Describe transforms and scene dependencies affecting raster geometry."""
    plane = getattr(rig, "fbp_plane_target", None) if rig is not None else None
    target_scene = _scene_for_canvas(canvas, scene)
    camera = getattr(target_scene, "camera", None) if target_scene is not None else None
    try:
        mode = str(getattr(canvas, "fbp_gp_attachment_mode", "PLANE") or "PLANE")
    except FBP_DATA_ERRORS:
        mode = "PLANE"
    camera_signature = ()
    if mode == "CAMERA" and camera is not None:
        try:
            camera_signature = (
                _data_pointer(camera),
                _data_pointer(getattr(camera, "data", None)),
                str(getattr(getattr(camera, "data", None), "type", "PERSP") or "PERSP"),
                _matrix_signature(camera.matrix_world),
            )
        except FBP_DATA_ERRORS:
            camera_signature = ()
    return (
        tuple(round(float(value), 9) for value in bounds),
        mode,
        _data_pointer(target_scene),
        _data_pointer(plane),
        _data_pointer(getattr(plane, "data", None) if plane is not None else None),
        _matrix_signature(getattr(canvas, "matrix_world", Matrix.Identity(4))),
        _matrix_signature(getattr(plane, "matrix_world", Matrix.Identity(4)) if plane is not None else Matrix.Identity(4)),
        _gp_material_visibility_signature(canvas),
        str(getattr(canvas, "fbp_gp_mask_source", "AUTO") or "AUTO"),
        str(canvas.get("fbp_gp_mask_curve_modes_json", "") or ""),
        bool(getattr(canvas, "fbp_gp_mask_auto_radius", True)),
        round(float(getattr(canvas, "fbp_gp_mask_stroke_width", DEFAULT_GP_MASK_STROKE_WIDTH) or DEFAULT_GP_MASK_STROKE_WIDTH), 9),
        _gp_geometry_generation(canvas),
        camera_signature,
    )


def _rgba_alpha(value, fallback=1.0):
    """Return a safe alpha channel from an RGBA-like value."""
    try:
        return float(value[3])
    except (AttributeError, IndexError, ReferenceError, RuntimeError, TypeError, ValueError):
        return float(fallback)


def _gp_style_alpha(style, attr_name, fallback=1.0, material=None):
    """Return the alpha channel for a Grease Pencil material component.

    Blender 5.2 usually exposes component alpha on the Grease Pencil style.
    Some imported materials only provide diffuse alpha on
    the parent Material, so use that as a conservative fallback instead of
    treating transparent materials as opaque masks.
    """
    try:
        value = getattr(style, attr_name, None)
        if value is not None:
            return _rgba_alpha(value, fallback)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        return _rgba_alpha(getattr(material, "diffuse_color", None), fallback)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return float(fallback)


def _gp_layer_runtime_signature(layer):
    """Small dynamic state that changes GP mask geometry without frame edits."""
    try:
        hidden = bool(getattr(layer, "hide", False))
    except FBP_DATA_ERRORS:
        hidden = False
    try:
        radius_offset = round(float(getattr(layer, "radius_offset", 0.0) or 0.0), 6)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        radius_offset = 0.0
    try:
        matrix_sig = _matrix_signature(getattr(layer, "matrix_local", Matrix.Identity(4)))
    except FBP_DATA_ERRORS:
        matrix_sig = ()
    # Do not include layer.opacity here. Frame By Plane uses layer opacity as
    # the artist-facing viewport Visibility slider for the editable GP canvas;
    # that visibility must not change the generated raster mask. Material alpha
    # and component visibility are still evaluated separately.
    return (_canvas_pointer(layer), hidden, radius_offset, matrix_sig)


def _gp_material_visibility_signature(canvas):
    """Signature for Blender 5.2 material visibility, stamps and randomization.

    Blender 5.2 exposes component visibility through read-only flags, while the
    material alpha still affects what is actually visible. Keeping this in the
    geometry context prevents stale mask cache entries after material edits, even
    before a depsgraph update has rebuilt the runtime indexes.
    """
    result = []
    try:
        materials = tuple(getattr(getattr(canvas, "data", None), "materials", ()) or ())
    except FBP_DATA_ERRORS:
        materials = ()
    for material in materials:
        try:
            style = getattr(material, "grease_pencil", None) if material is not None else None
            if style is None:
                material_alpha = _rgba_alpha(getattr(material, "diffuse_color", None), 1.0)
                result.append((_data_pointer(material), True, True, round(float(material_alpha), 6), round(float(material_alpha), 6), "LINE"))
                continue
            show_fill = bool(getattr(style, "is_fill_visible", True))
            show_stroke = bool(getattr(style, "is_stroke_visible", True))
            fill_alpha = _gp_style_alpha(style, "fill_color", 1.0, material)
            stroke_alpha = _gp_style_alpha(style, "color", 1.0, material)
            stroke_mode = str(getattr(style, "mode", "LINE") or "LINE").upper()
            placement = (
                str(getattr(style, "placement_mode", "COUNT") or "COUNT"),
                int(getattr(style, "placement_count", 1) or 1),
                round(float(getattr(style, "placement_density", 1.0) or 1.0), 6),
                round(float(getattr(style, "placement_radius_spacing", 1.0) or 1.0), 6),
            )
            randomization = (
                bool(getattr(style, "use_randomization", False)),
                round(float(getattr(style, "random_size_factor", 0.0) or 0.0), 6),
                round(float(getattr(style, "random_strength_factor", 0.0) or 0.0), 6),
                round(float(getattr(style, "random_rotation_factor", 0.0) or 0.0), 6),
                round(float(getattr(style, "random_hue_factor", 0.0) or 0.0), 6),
                round(float(getattr(style, "random_saturation_factor", 0.0) or 0.0), 6),
                round(float(getattr(style, "random_value_factor", 0.0) or 0.0), 6),
                round(float(getattr(style, "random_noise_scale", 0.0) or 0.0), 6),
            )
            result.append((
                _data_pointer(material),
                bool(show_fill),
                bool(show_stroke),
                round(float(fill_alpha), 6),
                round(float(stroke_alpha), 6),
                stroke_mode,
                placement,
                randomization,
            ))
        except FBP_DATA_ERRORS:
            result.append((_data_pointer(material), False, False, 0.0, 0.0))
    return tuple(result)


def _canvas_geometry(canvas, rig, bounds=None, *, frame_number=None, scene=None, exposure_state=None):
    """GP Mask v2 geometry extraction with evaluated/live fallback."""
    target_scene = _scene_for_canvas(canvas, scene)
    frame = _coerce_frame_number(frame_number, _scene_current_frame_number(target_scene, 1))
    bounds = bounds if bounds is not None else _plane_bounds(rig)
    if exposure_state is None:
        _key, exposure_state = _canvas_exposure_state(canvas, frame)

    def _extract_from_state(state, label):
        try:
            from . import gp_mask_core as _gp_mask_core
            geometry = _gp_mask_core.extract_geometry(
                canvas,
                rig,
                bounds=bounds,
                frame_number=frame,
                scene=target_scene,
                exposure_state=state,
            )
            polygons = tuple(geometry.fill_groups)
            polylines = tuple(geometry.polylines)
            try:
                point_total = sum(len(contour) for group in polygons for contour in group)
                point_total += sum(len(points) for points, _cyclic, _width in polylines)
            except (TypeError, ValueError):
                point_total = 0
            canvas_pointer = _canvas_pointer(canvas)
            if canvas_pointer:
                _GP_MASK_DEBUG_STATE[canvas_pointer] = {
                    "source": str(label),
                    "points": int(point_total),
                    "polylines": len(polylines),
                    "fills": len(polygons),
                    "error": "",
                }
            if polygons or polylines:
                _GP_MASK_GEOMETRY_STATE[canvas_pointer] = True
            return polygons, polylines
        except Exception as exc:
            canvas_pointer = _canvas_pointer(canvas)
            if canvas_pointer:
                _GP_MASK_DEBUG_STATE[canvas_pointer] = {
                    "source": f"{label}: error",
                    "points": 0,
                    "polylines": 0,
                    "fills": 0,
                    "error": str(exc)[:240],
                }
            fbp_warn(f"Could not extract Grease Pencil Mask v2 geometry from {label}", exc)
            return (), ()

    polygons, polylines = _extract_from_state(exposure_state, "cached")
    if polygons or polylines:
        return polygons, polylines

    evaluated = _evaluated_canvas_for_mask(canvas, target_scene)
    if evaluated is not None:
        try:
            _live_key, live_state = _canvas_exposure_state_from_object(evaluated, frame)
        except FBP_DATA_ERRORS:
            live_state = ()
        if live_state:
            polygons, polylines = _extract_from_state(live_state, "evaluated")
            if polygons or polylines:
                return polygons, polylines

    canvas_pointer = _canvas_pointer(canvas)
    if canvas_pointer:
        _GP_MASK_DEBUG_STATE[canvas_pointer] = {
            "source": "empty",
            "points": 0,
            "polylines": 0,
            "fills": 0,
            "error": "",
        }
    _GP_MASK_GEOMETRY_STATE[canvas_pointer] = False
    return (), ()


def _distance_geometry_signature(canvas, polygons, polylines, resolution, bounds):
    """Hash only data that changes the expensive signed-distance field.

    Incremental binary hashing avoids constructing one very large temporary
    string for dense drawings. Reveal timing, opacity and edge controls are not
    included because they can reuse the same cached distance field.
    """
    digest = hashlib.blake2b(digest_size=20)
    digest.update(struct.pack("<I4f", int(resolution), *(float(v) for v in bounds)))
    digest.update(struct.pack("<f", float(getattr(canvas, "fbp_gp_mask_stroke_width", DEFAULT_GP_MASK_STROKE_WIDTH) or DEFAULT_GP_MASK_STROKE_WIDTH)))
    for contours in polygons:
        digest.update(b"G")
        digest.update(struct.pack("<I", len(contours)))
        for contour in contours:
            digest.update(b"P")
            digest.update(struct.pack("<I", len(contour)))
            for x, y in contour:
                digest.update(struct.pack("<2f", float(x), float(y)))
    for points, cyclic, width in polylines:
        digest.update(b"C" if cyclic else b"L")
        widths = _polyline_width_samples(width, len(points), getattr(canvas, "fbp_gp_mask_stroke_width", DEFAULT_GP_MASK_STROKE_WIDTH))
        digest.update(struct.pack("<I", len(points)))
        for (x, y), sample_width in zip(points, widths, strict=False):
            digest.update(struct.pack("<3f", float(x), float(y), float(sample_width)))
    return digest.hexdigest()


def _geometry_signature(canvas, rig, polygons, polylines, resolution, bounds=None, *, distance_signature="", frame_number=1):
    """Return the complete raster-output signature for one mask frame."""
    bounds = bounds if bounds is not None else _plane_bounds(rig)
    distance_signature = distance_signature or _distance_geometry_signature(
        canvas, polygons, polylines, resolution, bounds
    )
    digest = hashlib.blake2b(digest_size=20)
    digest.update(str(distance_signature).encode("ascii", "ignore"))
    values = (
        "RASTER_SDF_V2",
        str(getattr(canvas, "fbp_gp_mask_source", "BOTH")),
        f"{float(getattr(canvas, 'fbp_gp_mask_feather', 0.0)):.8f}",
        f"{float(getattr(canvas, 'fbp_gp_mask_expand', 0.0)):.8f}",
        f"{float(getattr(canvas, 'fbp_gp_mask_threshold', 0.5)):.8f}",
        "1" if bool(getattr(canvas, "fbp_gp_reveal_enabled", False)) else "0",
        str(getattr(canvas, "fbp_gp_reveal_mode", "REVEAL")),
        str(_coerce_frame_number(getattr(canvas, "fbp_gp_reveal_start", None), 1)),
        str(_coerce_frame_number(getattr(canvas, "fbp_gp_reveal_end", None), 24)),
        str(getattr(canvas, "fbp_gp_reveal_direction", "LEFT_RIGHT")),
        "1" if bool(getattr(canvas, "fbp_gp_reveal_invert", False)) else "0",
        f"{float(getattr(canvas, 'fbp_gp_reveal_feather', 0.05)):.8f}",
        "1" if bool(getattr(canvas, "fbp_gp_reveal_hold", True)) else "0",
    )
    digest.update("|".join(values).encode("utf8"))
    if bool(getattr(canvas, "fbp_gp_reveal_enabled", False)):
        digest.update(struct.pack("<i", int(frame_number)))
    return digest.hexdigest()


_NUMPY_UNSET = object()
_NUMPY_CACHE = _NUMPY_UNSET


def _numpy_module():
    global _NUMPY_CACHE
    if _NUMPY_CACHE is not _NUMPY_UNSET:
        return _NUMPY_CACHE
    try:
        import numpy as np
        _NUMPY_CACHE = np
    except ImportError:
        _NUMPY_CACHE = None
    return _NUMPY_CACHE


def _polyline_width_samples(width, point_count, fallback):
    """Return one width per point; supports scalar and per-point GP radii."""
    fallback = max(1.0e-6, float(fallback or 1.0e-6))
    try:
        if isinstance(width, (str, bytes)):
            raise TypeError
        values = tuple(width)
    except (TypeError, ValueError):
        try:
            scalar = max(1.0e-6, float(width if width is not None else fallback))
        except (TypeError, ValueError):
            scalar = fallback
        return tuple(scalar for _ in range(max(1, int(point_count or 1))))
    if not values:
        return tuple(fallback for _ in range(max(1, int(point_count or 1))))
    result = []
    for value in values[:max(1, int(point_count or 1))]:
        try:
            result.append(max(1.0e-6, float(value)))
        except (TypeError, ValueError):
            result.append(fallback)
    while len(result) < max(1, int(point_count or 1)):
        result.append(result[-1] if result else fallback)
    return tuple(result)


def _reveal_progress(canvas, frame_number=None):
    if not bool(getattr(canvas, "fbp_gp_reveal_enabled", False)):
        return None
    if frame_number is None:
        frame_number = _scene_current_frame_number(getattr(bpy.context, "scene", None), 1)
    frame = int(frame_number)
    start = _coerce_frame_number(getattr(canvas, "fbp_gp_reveal_start", None), 1)
    end = _coerce_frame_number(getattr(canvas, "fbp_gp_reveal_end", None), start + 1)
    if end < start:
        start, end = end, start
    if end == start:
        progress = 1.0 if frame >= end else 0.0
    else:
        progress = max(0.0, min(1.0, (frame - start) / float(end - start)))
    if frame > end and not bool(getattr(canvas, "fbp_gp_reveal_hold", True)):
        progress = 0.0
    return progress


def _reveal_position_numpy(height, width, direction, np):
    """Return a shared normalized reveal-position grid."""
    global _GP_REVEAL_POSITION_CACHE_BYTES
    key = (int(height), int(width), str(direction or "LEFT_RIGHT"))
    cached = _GP_REVEAL_POSITION_CACHE.get(key)
    if cached is not None:
        _GP_REVEAL_POSITION_CACHE.move_to_end(key)
        return cached[0]
    if direction in {"BOTTOM_TOP", "TOP_BOTTOM"}:
        position = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, np.newaxis]
        if direction == "TOP_BOTTOM":
            position = 1.0 - position
    elif direction == "RADIAL":
        grid_x = np.linspace(0.0, 1.0, width, dtype=np.float32)[np.newaxis, :]
        grid_y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, np.newaxis]
        position = np.clip(
            np.sqrt((grid_x - 0.5) ** 2 + (grid_y - 0.5) ** 2) / np.sqrt(0.5),
            0.0,
            1.0,
        ).astype(np.float32, copy=False)
    else:
        position = np.linspace(0.0, 1.0, width, dtype=np.float32)[np.newaxis, :]
        if direction == "RIGHT_LEFT":
            position = 1.0 - position
    byte_count = int(getattr(position, "nbytes", 0) or 0)
    _GP_REVEAL_POSITION_CACHE[key] = (position, byte_count)
    _GP_REVEAL_POSITION_CACHE_BYTES += byte_count
    while (
        len(_GP_REVEAL_POSITION_CACHE) > _GP_REVEAL_POSITION_CACHE_MAX_ENTRIES
        or _GP_REVEAL_POSITION_CACHE_BYTES > _GP_REVEAL_POSITION_CACHE_MAX_BYTES
    ):
        _old_key, (_old_position, old_bytes) = _GP_REVEAL_POSITION_CACHE.popitem(last=False)
        del _old_key, _old_position
        _GP_REVEAL_POSITION_CACHE_BYTES = max(
            0, _GP_REVEAL_POSITION_CACHE_BYTES - int(old_bytes or 0)
        )
    return position


def _rgba_pixels_numpy(alpha, np):
    """Reuse an RGBA upload buffer instead of allocating four channels per frame."""
    global _GP_RGBA_BUFFER_CACHE_BYTES
    height, width = alpha.shape
    key = (int(height), int(width))
    cached = _GP_RGBA_BUFFER_CACHE.get(key)
    if cached is None:
        rgba = np.empty((height, width, 4), dtype=np.float32)
        byte_count = int(getattr(rgba, "nbytes", 0) or 0)
        _GP_RGBA_BUFFER_CACHE[key] = (rgba, byte_count)
        _GP_RGBA_BUFFER_CACHE_BYTES += byte_count
        while (
            len(_GP_RGBA_BUFFER_CACHE) > _GP_RGBA_BUFFER_CACHE_MAX_ENTRIES
            or _GP_RGBA_BUFFER_CACHE_BYTES > _GP_RGBA_BUFFER_CACHE_MAX_BYTES
        ):
            old_key, (old_buffer, old_bytes) = _GP_RGBA_BUFFER_CACHE.popitem(last=False)
            if old_key == key:
                # A single buffer may be larger than the soft cache budget.
                # Keep it for this upload, but do not retain it globally.
                _GP_RGBA_BUFFER_CACHE_BYTES = max(
                    0, _GP_RGBA_BUFFER_CACHE_BYTES - int(old_bytes or 0)
                )
                cached = (rgba, byte_count)
                break
            del old_buffer
            _GP_RGBA_BUFFER_CACHE_BYTES = max(
                0, _GP_RGBA_BUFFER_CACHE_BYTES - int(old_bytes or 0)
            )
        else:
            cached = _GP_RGBA_BUFFER_CACHE.get(key)
        if cached is None:
            cached = (rgba, byte_count)
    else:
        _GP_RGBA_BUFFER_CACHE.move_to_end(key)
    rgba = cached[0]
    rgba[:, :, 0] = alpha
    rgba[:, :, 1] = alpha
    rgba[:, :, 2] = alpha
    rgba[:, :, 3] = alpha
    return rgba.reshape(-1)


def _apply_reveal_numpy(canvas, alpha, np, frame_number=None):
    progress = _reveal_progress(canvas, frame_number)
    if progress is None:
        return alpha
    height, width = alpha.shape
    direction = str(getattr(canvas, "fbp_gp_reveal_direction", "LEFT_RIGHT") or "LEFT_RIGHT")
    position = _reveal_position_numpy(height, width, direction, np)
    feather = max(1.0e-6, float(getattr(canvas, "fbp_gp_reveal_feather", 0.05) or 0.0))
    gate = np.clip(0.5 + (progress - position) / (2.0 * feather), 0.0, 1.0)
    if bool(getattr(canvas, "fbp_gp_reveal_invert", False)):
        gate = 1.0 - gate
    return alpha * gate


def _mask_pixels(canvas, polygons, polylines, bounds, resolution, *, distance_signature="", frame_number=1):
    """GP Mask v2 SDF raster backend.

    Input geometry remains vector data until this final bake step.  This path
    supports Fill, Line and Fill+Line, variable per-point radius, hard edges,
    soft Blur, and Expand/Contract from one signed-distance field.
    """
    try:
        from . import gp_mask_core as _gp_mask_core
        from . import gp_mask_raster as _gp_mask_raster
        geometry = _gp_mask_core.FBPMaskGeometry(
            strokes=(),
            fill_groups=tuple(polygons or ()),
            polylines=tuple(polylines or ()),
            bounds=tuple(bounds or (-1.0, 1.0, -1.0, 1.0)),
            frame=_coerce_frame_number(frame_number, 1),
        )
        base_signature = "|".join((
            str(distance_signature or ""),
            f"{float(getattr(canvas, 'fbp_gp_mask_expand', 0.0) or 0.0):.9f}",
            f"{float(getattr(canvas, 'fbp_gp_mask_feather', 0.0) or 0.0):.9f}",
            f"{float(getattr(canvas, 'fbp_gp_mask_threshold', 0.5) or 0.5):.9f}",
        ))
        base_alpha = _gp_base_alpha_cache_get(canvas, resolution, base_signature)
        if base_alpha is None:
            base_alpha = _gp_mask_raster.generate_base_alpha(
                geometry, canvas, resolution
            )
            if base_alpha is not None:
                _gp_base_alpha_cache_put(
                    canvas, resolution, base_signature, base_alpha
                )
        return _gp_mask_raster.generate_pixels(
            geometry,
            canvas,
            resolution,
            reveal_callback=lambda alpha, frame: _apply_reveal_numpy(canvas, alpha, _numpy_module(), frame),
            frame_number=frame_number,
            base_alpha=base_alpha,
        )
    except Exception as exc:
        fbp_warn("Could not rasterize Grease Pencil Mask v2", exc)
        np = _numpy_module()
        if np is not None:
            alpha = np.zeros((int(resolution), int(resolution)), dtype=np.float32)
            return _rgba_pixels_numpy(alpha, np)
        pixels = array("f")
        pixels.extend((0.0, 0.0, 0.0, 0.0) * (int(resolution) * int(resolution)))
        return pixels

def _prune_gp_mask_retired_images(now=None, *, remove_orphans=False):
    """Prune retired GP-mask bookkeeping without losing live orphan IDs.

    Cache clears and reloads may discard entries only when their Image no
    longer exists.  The raster/publish path may additionally remove old,
    zero-user generated buffers from ``bpy.data.images`` before dropping the
    corresponding timestamp.  Keeping the two operations coupled prevents an
    untracked Image leak while remaining safe during Undo/load handlers.
    """
    if not _GP_MASK_IMAGE_RETIRED_AT:
        return 0
    now = time.monotonic() if now is None else float(now)
    removed = 0
    cutoff = now - max(_GP_MASK_IMAGE_RETIRED_MAX_AGE, _GP_MASK_IMAGE_REUSE_DELAY * 4.0)
    ordered = []
    for raw_name, raw_retired_at in tuple(_GP_MASK_IMAGE_RETIRED_AT.items()):
        name = str(raw_name or "")
        try:
            retired_at = float(raw_retired_at or 0.0)
        except (TypeError, ValueError):
            retired_at = 0.0
        image = bpy.data.images.get(name) if name else None
        if image is None:
            _GP_MASK_IMAGE_RETIRED_AT.pop(name, None)
            removed += 1
            continue
        ordered.append((name, retired_at, image))

    if not remove_orphans:
        return removed

    overflow = max(0, len(ordered) - _GP_MASK_IMAGE_RETIRED_MAX_ENTRIES)
    for index, (name, retired_at, image) in enumerate(sorted(ordered, key=lambda item: item[1])):
        old_enough = retired_at <= cutoff
        must_reduce_table = index < overflow
        if not old_enough and not must_reduce_table:
            continue
        try:
            removable = (
                int(getattr(image, "users", 0) or 0) == 0
                and bool(image.get("fbp_generated_buffer", False))
                and bool(image.get("fbp_orphan_candidate", False))
            )
        except FBP_DATA_ERRORS:
            removable = False
        if not removable:
            continue
        try:
            bpy.data.images.remove(image)
        except FBP_DATA_ERRORS:
            continue
        _GP_MASK_IMAGE_RETIRED_AT.pop(name, None)
        removed += 1
    return removed


def _mask_image(canvas, resolution):
    """Return a retired GP mask buffer without resizing an existing Image.

    Eevee can transiently retain zero-user image buffers. A buffer is reused
    only after a cooldown and at the exact requested resolution; otherwise a
    fresh datablock is created and published after pixel upload completes.
    """
    try:
        current = getattr(canvas, "fbp_gp_mask_image", None)
        if current is None:
            name = str(canvas.get(KEY_MASK_IMAGE_NAME, "") or "")
            current = bpy.data.images.get(name) if name else None
    except FBP_DATA_ERRORS:
        current = None

    owner = gp_canvas_owner(canvas)
    owner_id = stable_id(owner, "LAYER") if owner else ""
    canvas_id = str(stable_id(canvas, "MASK") or ensure_mask_identity(canvas))
    token = canvas_id.split(":")[-1][:12]
    base_name = f"FBP GP Mask • {token} • Buffer"
    image = None
    now = time.monotonic()
    _prune_gp_mask_retired_images(now, remove_orphans=True)

    for candidate_name, retired_at_value in tuple(_GP_MASK_IMAGE_RETIRED_AT.items()):
        candidate = bpy.data.images.get(str(candidate_name))
        if candidate is None:
            _GP_MASK_IMAGE_RETIRED_AT.pop(str(candidate_name), None)
            continue
        try:
            if _same_datablock(candidate, current) or not str(candidate.name or "").startswith(base_name):
                continue
            candidate_canvas_id = str(candidate.get("fbp_mask_canvas_id", "") or "")
            if candidate_canvas_id and candidate_canvas_id != canvas_id:
                continue
            if int(getattr(candidate, "users", 0) or 0) > 0:
                continue
            retired_at = float(retired_at_value or 0.0)
            if retired_at <= 0.0 or now - retired_at < _GP_MASK_IMAGE_REUSE_DELAY:
                continue
            if tuple(int(v) for v in candidate.size[:2]) != (resolution, resolution):
                continue
            image = candidate
            break
        except FBP_DATA_ERRORS:
            continue

    if image is None:
        image = bpy.data.images.new(
            base_name,
            width=resolution,
            height=resolution,
            alpha=True,
            float_buffer=False,
        )

    try:
        image[KEY_IS_MASK_IMAGE] = True
        image[KEY_OWNER_ID] = owner_id
        image[KEY_SCHEMA] = FBP_GP_SCHEMA_VERSION
        image["fbp_mask_canvas_id"] = canvas_id
        image["fbp_generated_buffer"] = True
        if str(image.colorspace_settings.name or "") != "Non-Color":
            image.colorspace_settings.name = "Non-Color"
    except FBP_DATA_ERRORS:
        pass
    return image, current


def _publish_mask_image(canvas, image, previous_image=None):
    """Atomically publish a completed GP mask buffer without freeing the old ID."""
    try:
        canvas.fbp_gp_mask_image = image
        canvas[KEY_MASK_IMAGE_NAME] = image.name
        image["fbp_orphan_candidate"] = False
    except FBP_DATA_ERRORS:
        return False
    if previous_image is not None and not _same_datablock(previous_image, image):
        try:
            previous_image["fbp_orphan_candidate"] = True
            retired_at = time.monotonic()
            _GP_MASK_IMAGE_RETIRED_AT[str(previous_image.name)] = retired_at
            _prune_gp_mask_retired_images(retired_at, remove_orphans=True)
        except FBP_DATA_ERRORS:
            pass
    return True


def _gp_mask_live_preview_resolution(canvas):
    """Resolution cap used only while actively drawing GP mask strokes."""
    try:
        value = int(getattr(canvas, "fbp_gp_mask_preview_quality", DEFAULT_GP_MASK_PREVIEW_QUALITY) or DEFAULT_GP_MASK_PREVIEW_QUALITY)
    except FBP_DATA_ERRORS:
        value = int(DEFAULT_GP_MASK_PREVIEW_QUALITY)
    return max(64, min(512, int(value)))


def _gp_mask_live_finalize_delay(canvas):
    """Idle delay before the expensive 1024px rebuild.

    Fill/Both require polygon inside tests in addition to boundary distance, so
    they get a longer idle window.  Live preview quality is unchanged; this only
    prevents full-quality rebuilds between rapid consecutive strokes.
    """
    try:
        mode = str(getattr(canvas, "fbp_gp_mask_source", "AUTO") or "AUTO").upper()
    except FBP_DATA_ERRORS:
        mode = "AUTO"
    if mode == "AUTO":
        mode = _active_gp_brush_stroke_type(None, fallback="STROKE")
    return 0.55 if mode in {"FILL", "BOTH"} else _GP_MASK_LIVE_FINALIZE_DELAY_SECONDS


def _schedule_gp_mask_full_quality_refresh(canvas, scene=None, source_resolution=0):
    """After a low-res live preview, rebuild once at the requested quality."""
    pointer = _canvas_pointer(canvas)
    if not pointer:
        return False
    target_scene = _scene_for_canvas(canvas, scene)
    scene_pointer = _canvas_pointer(target_scene)
    key = (pointer, scene_pointer)
    _GP_MASK_LIVE_FINALIZE_KEYS[key] = (time.monotonic(), int(source_resolution or 0))
    finalize_delay = _gp_mask_live_finalize_delay(canvas)

    def _finalize():
        current = _gp_canvas_by_pointer(pointer)
        if not is_gp_canvas(current):
            _GP_MASK_LIVE_FINALIZE_KEYS.pop(key, None)
            return None
        if _gp_mask_refresh_blocked_by_edit_mode(current):
            # Never keep a live-paint full-quality task alive while Edit Mode
            # owns GPv3 data. Native Stroke Type edits use the separate safe
            # post-edit finalizer after Blender leaves Edit Mode.
            _GP_MASK_LIVE_FINALIZE_KEYS.pop(key, None)
            return None
        requested_at, _target_res = _GP_MASK_LIVE_FINALIZE_KEYS.get(key, (0.0, 0))
        last_dirty = float(_GP_MASK_DIRTY_TIME.get(key, 0.0) or 0.0)
        now = time.monotonic()
        latest_activity = max(float(requested_at or 0.0), last_dirty)
        if latest_activity > 0.0 and now - latest_activity < finalize_delay:
            return max(0.04, min(0.20, finalize_delay - (now - latest_activity)))
        transition_wait = _gp_mask_mode_transition_guard_active(current, _scene_by_pointer(scene_pointer))
        if transition_wait > 0.0:
            return max(0.05, min(0.25, transition_wait))
        if not fbp_depsgraph_quiet_for(0.20):
            return 0.08
        _GP_MASK_LIVE_FINALIZE_KEYS.pop(key, None)
        refresh_scene = _scene_by_pointer(scene_pointer)
        try:
            current[KEY_MASK_DIRTY] = True
        except FBP_DATA_ERRORS:
            pass
        refresh_gp_mask(current, force=True, scene=refresh_scene)
        return None

    task_name = f"grease_pencil.mask_full_quality:{pointer}:{scene_pointer}"
    scheduled = bool(
        schedule_once(
            task_name,
            _finalize,
            first_interval=finalize_delay,
        )
    )
    if not scheduled and not scheduled_task_pending(task_name):
        _GP_MASK_LIVE_FINALIZE_KEYS.pop(key, None)
    return scheduled


def refresh_gp_mask(canvas, *, force=False, scene=None, allow_edit_mode=False):
    if not is_gp_canvas(canvas):
        return None, False
    rig = gp_canvas_owner(canvas)
    # Drawing Planes can now be real, independent Layer Stack items.  When a
    # GP canvas is unlinked it still has valid drawable geometry and must be
    # able to feed Plane clipping.  Use the canvas itself as the raster surface
    # so the existing geometry pipeline can produce a mask image in local GP
    # coordinates instead of failing because no owner rig exists.
    surface = rig if rig is not None else (canvas if is_gp_drawing_canvas(canvas) else None)
    if surface is None:
        return None, False
    target_scene = _scene_for_canvas(canvas, scene)
    frame_number = _scene_current_frame_number(target_scene, 1)
    try:
        existing_image = getattr(canvas, "fbp_gp_mask_image", None)
    except FBP_DATA_ERRORS:
        existing_image = None
    if _gp_mask_refresh_blocked_by_edit_mode(canvas) and not allow_edit_mode:
        # Structural edits are sampled only by the dedicated quiet-time timer,
        # never by ordinary depsgraph or paint refresh paths.
        return existing_image, False
    try:
        existing_image = getattr(canvas, "fbp_gp_mask_image", None)
        dirty = bool(canvas.get(KEY_MASK_DIRTY, True))
        geometry_dirty = bool(canvas.get(KEY_MASK_GEOMETRY_DIRTY, True))
    except FBP_DATA_ERRORS:
        existing_image = None
        dirty = True
        geometry_dirty = True
    desired_bounds = _plane_bounds(surface)
    if existing_image is not None and not _gp_mask_image_bounds_match(existing_image, desired_bounds):
        dirty = True
        geometry_dirty = True
        try:
            canvas[KEY_MASK_DIRTY] = True
            canvas[KEY_MASK_GEOMETRY_DIRTY] = True
        except FBP_DATA_ERRORS:
            pass
    if not force and existing_image is not None and not dirty:
        return existing_image, False
    try:
        source_resolution = max(32, int(getattr(canvas, "fbp_gp_mask_quality", DEFAULT_GP_MASK_QUALITY) or DEFAULT_GP_MASK_QUALITY))
    except (TypeError, ValueError):
        source_resolution = int(DEFAULT_GP_MASK_QUALITY)
    resolution = source_resolution
    try:
        force_full_quality_once = bool(canvas.get(KEY_MASK_FORCE_FULL_QUALITY_ONCE, False))
    except FBP_DATA_ERRORS:
        force_full_quality_once = False
    live_preview = bool(
        (not force)
        and (not force_full_quality_once)
        and (_gp_live_editing(canvas) or bool(allow_edit_mode))
        and source_resolution > _gp_mask_live_preview_resolution(canvas)
    )
    if live_preview:
        preview_resolution = _gp_mask_live_preview_resolution(canvas)
        resolution = min(source_resolution, preview_resolution)
    # The pure-Python fallback is intentionally capped to keep UI refreshes safe.
    if _numpy_module() is None:
        resolution = min(resolution, 128)
    # The persistent paint poll already finalizes authored Stroke/Fill/Both
    # metadata when curve counts change. Avoid rescanning curve_offsets again
    # inside every live raster. Structural previews synchronize explicitly at
    # their safe quiet point before calling this function.
    if not (_gp_live_editing(canvas) or bool(allow_edit_mode)):
        _sync_gp_mask_authored_curve_state(canvas, scene=target_scene)
    bounds = desired_bounds
    # Resolve the exposure exactly once. The indexed timeline is also correct
    # before a lone delayed keyframe, where the old "static" shortcut leaked
    # future geometry into earlier frames.
    exposure_key, exposure_state = _canvas_exposure_state(
        canvas, frame_number, rebuild_index=bool(force or geometry_dirty)
    )
    context_signature = _geometry_context_signature(canvas, surface, bounds, target_scene)
    geometry_entry = None if (force or geometry_dirty) else _geometry_cache_get(
        canvas, exposure_key, context_signature
    )
    if geometry_entry is None:
        polygons, polylines = _canvas_geometry(
            canvas,
            surface,
            bounds,
            frame_number=frame_number,
            scene=target_scene,
            exposure_state=exposure_state,
        )
        geometry_entry = _geometry_cache_put(
            canvas, exposure_key, context_signature, polygons, polylines
        )
        try:
            canvas[KEY_MASK_GEOMETRY_DIRTY] = False
        except FBP_DATA_ERRORS:
            pass
    else:
        polygons = geometry_entry["polygons"]
        polylines = geometry_entry["polylines"]
    distance_signatures = geometry_entry.setdefault("distance_signatures", {})
    distance_signature = distance_signatures.get(resolution)
    if not distance_signature:
        distance_signature = _distance_geometry_signature(
            canvas, polygons, polylines, resolution, bounds
        )
        distance_signatures[resolution] = distance_signature
    signature = _geometry_signature(
        canvas,
        surface,
        polygons,
        polylines,
        resolution,
        bounds,
        distance_signature=distance_signature,
        frame_number=frame_number,
    )
    try:
        old_signature = str(canvas.get(KEY_MASK_SIGNATURE, "") or "")
        image = getattr(canvas, "fbp_gp_mask_image", None)
    except FBP_DATA_ERRORS:
        old_signature = ""
        image = None
    if not force and image is not None and signature == old_signature:
        try:
            canvas[KEY_MASK_DIRTY] = False
        except FBP_DATA_ERRORS:
            pass
        _remember_canvas_frame_state(canvas, target_scene, frame_number, exposure_key)
        return image, False
    image, previous_image = _mask_image(canvas, resolution)
    pixels = _mask_pixels(
        canvas,
        polygons,
        polylines,
        bounds,
        resolution,
        distance_signature=distance_signature,
        frame_number=frame_number,
    )
    try:
        image.pixels.foreach_set(pixels)
        image.update()
        image["fbp_gp_mask_bounds"] = [float(v) for v in bounds]
        image["fbp_gp_mask_frame"] = frame_number
        if not _publish_mask_image(canvas, image, previous_image):
            return previous_image or image, False
        canvas[KEY_MASK_SIGNATURE] = signature
        canvas[KEY_MASK_FRAME] = frame_number
        if live_preview and source_resolution > resolution:
            canvas[KEY_MASK_DIRTY] = True
            canvas["fbp_gp_mask_live_preview"] = True
            canvas["fbp_gp_mask_preview_resolution"] = int(resolution)
            _schedule_gp_mask_full_quality_refresh(canvas, target_scene, source_resolution)
        else:
            canvas[KEY_MASK_DIRTY] = False
            canvas["fbp_gp_mask_live_preview"] = False
            canvas["fbp_gp_mask_preview_resolution"] = int(resolution)
            try:
                canvas[KEY_MASK_FORCE_FULL_QUALITY_ONCE] = False
            except FBP_DATA_ERRORS:
                pass
        _sync_frame_mask_registry(canvas, refresh_sensitivity=False, scene=target_scene)
        _remember_canvas_frame_state(canvas, target_scene, frame_number, exposure_key)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not update Grease Pencil mask image", exc)
        return image, False
    _sync_canvas_mask_output_bindings(canvas, image)
    return image, True


def _canvas_geometry_changes_with_frame(canvas, *, refresh=False, scene=None):
    """Return whether GP exposure can change inside the owning scene range."""
    try:
        target_scene = _scene_for_canvas(canvas, scene)
        cache_key = (_canvas_pointer(canvas), _canvas_pointer(target_scene), "GEOMETRY")
        if not refresh and cache_key in _GP_FRAME_SENSITIVITY_CACHE:
            return bool(_GP_FRAME_SENSITIVITY_CACHE.get(cache_key, False))
        # A scene-less caller may still use the persisted flag as a conservative
        # fallback, but scene-specific checks are never shared: the same canvas
        # can be linked into scenes with different frame_start values.
        if scene is None and not refresh and not cache_key[1] and KEY_MASK_GEOMETRY_FRAME_SENSITIVE in canvas:
            return bool(canvas.get(KEY_MASK_GEOMETRY_FRAME_SENSITIVE, False))
        frame_start = _coerce_frame_number(getattr(target_scene, "frame_start", None), 1)
        sensitive = False
        data = getattr(canvas, "data", None)
        for layer in tuple(getattr(data, "layers", ()) or ()):
            frames = getattr(layer, "frames", ()) or ()
            count = len(frames)
            if count > 1:
                sensitive = True
                break
            if count == 1:
                first = _coerce_frame_number(getattr(frames[0], "frame_number", None), frame_start)
                # One drawing key is still animated when it begins after the
                # scene start: frames before it must remain empty.
                if first > frame_start:
                    sensitive = True
                    break
        if cache_key[0] and cache_key[1]:
            _GP_FRAME_SENSITIVITY_CACHE[cache_key] = bool(sensitive)
        canvas[KEY_MASK_GEOMETRY_FRAME_SENSITIVE] = bool(sensitive)
        return bool(sensitive)
    except FBP_DATA_ERRORS:
        return True


def _canvas_mask_changes_with_frame(canvas, *, refresh=False, scene=None):
    """Return cached timeline sensitivity for this canvas raster mask."""
    try:
        target_scene = _scene_for_canvas(canvas, scene)
        cache_key = (_canvas_pointer(canvas), _canvas_pointer(target_scene), "MASK")
        if not refresh and cache_key in _GP_FRAME_SENSITIVITY_CACHE:
            return bool(_GP_FRAME_SENSITIVITY_CACHE.get(cache_key, False))
        if scene is None and not refresh and not cache_key[1] and KEY_MASK_FRAME_SENSITIVE in canvas:
            return bool(canvas.get(KEY_MASK_FRAME_SENSITIVE, False))
        sensitive = bool(getattr(canvas, "fbp_gp_reveal_enabled", False))
        if not sensitive:
            sensitive = _canvas_geometry_changes_with_frame(canvas, refresh=refresh, scene=target_scene)
        if cache_key[0] and cache_key[1]:
            _GP_FRAME_SENSITIVITY_CACHE[cache_key] = bool(sensitive)
        canvas[KEY_MASK_FRAME_SENSITIVE] = bool(sensitive)
        return bool(sensitive)
    except FBP_DATA_ERRORS:
        return True


def _frame_state_from_exposure(canvas, frame_number, exposure_key):
    progress = _reveal_progress(canvas, frame_number)
    progress_key = None if progress is None else round(float(progress), 9)
    return exposure_key, progress_key


def _canvas_frame_state_key(canvas, scene):
    """Describe the visible mask state at the current scene frame.

    Held GP exposures and reveal ranges before/after their active interval
    produce identical keys, so no timer or image upload is scheduled.
    """
    frame_number = _scene_current_frame_number(scene, 1)
    exposure_key = _canvas_exposure_key(canvas, frame_number)
    return _frame_state_from_exposure(canvas, frame_number, exposure_key)


def _remember_canvas_frame_state(canvas, scene, frame_number, exposure_key):
    canvas_pointer = _canvas_pointer(canvas)
    scene_pointer = _canvas_pointer(scene)
    if canvas_pointer and scene_pointer:
        _GP_FRAME_STATE[(canvas_pointer, scene_pointer)] = _frame_state_from_exposure(
            canvas, frame_number, exposure_key
        )


def _gp_mask_dirty_key(canvas, scene=None):
    target_scene = _scene_for_canvas(canvas, scene)
    return (_canvas_pointer(canvas), _canvas_pointer(target_scene))


def _pause_gp_mask_mode_transition(canvas=None, scene=None, *, seconds=None):
    """Pause deferred FBP mutations during risky native GP mode changes.

    This stores only process-local state/runtime flags; it deliberately avoids
    touching Grease Pencil drawings, ID properties, mask images, or cache data.
    """
    try:
        duration = float(_GP_MASK_MODE_TRANSITION_SECONDS if seconds is None else seconds)
    except (TypeError, ValueError):
        duration = _GP_MASK_MODE_TRANSITION_SECONDS
    until = time.monotonic() + max(0.05, duration)
    try:
        fbp_runtime_set("fbp_managed_timers_resume_after", until)
    except FBP_DATA_ERRORS as exc:
        fbp_warn_once(
            "gp_mask_mode_pause_failed",
            "Could not pause managed timers during a Grease Pencil mode transition",
            exc,
            event="gp_mask.mode_transition_pause",
        )
    try:
        if canvas is not None:
            _GP_MASK_MODE_TRANSITION_GUARD[_gp_mask_dirty_key(canvas, scene)] = until
    except FBP_DATA_ERRORS:
        pass
    return until


def _gp_mask_mode_transition_guard_active(canvas=None, scene=None):
    now = time.monotonic()
    if canvas is not None:
        key = _gp_mask_dirty_key(canvas, scene)
        until = float(_GP_MASK_MODE_TRANSITION_GUARD.get(key, 0.0) or 0.0)
        if until > now:
            return until - now
        if key in _GP_MASK_MODE_TRANSITION_GUARD:
            _GP_MASK_MODE_TRANSITION_GUARD.pop(key, None)
    # Keep global timer guard conservative even if the per-canvas key was not
    # available during the mode transition.
    try:
        # safe_tasks uses this runtime value as the source of truth.
        from .runtime import fbp_runtime_get
        until = float(fbp_runtime_get("fbp_managed_timers_resume_after", 0.0) or 0.0)
        if until > now:
            return until - now
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn_once(
            "gp_mask_mode_guard_query_failed",
            "Could not query the Grease Pencil mode-transition guard",
            exc,
            event="gp_mask.mode_transition_guard",
        )
    return 0.0


def _gp_canvas_active_modes(canvas):
    """Return normalized object/context modes when *canvas* is active.

    ``Object.mode`` reports generic values such as ``EDIT`` for Grease Pencil,
    while ``Context.mode`` reports ``EDIT_GREASE_PENCIL``.  Earlier guards read
    only the object value and therefore missed Blender 5.2 Edit Mode entirely.
    """
    try:
        context = getattr(bpy, "context", None)
        active = getattr(context, "object", None) or getattr(context, "active_object", None)
        if not _same_datablock(active, canvas):
            return ()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ()
    modes = []
    for value in (
        getattr(active, "mode", None),
        getattr(context, "mode", None),
    ):
        text = str(value or "").strip().upper()
        if text and text not in modes:
            modes.append(text)
    return tuple(modes)


def _gp_canvas_active_mode(canvas):
    modes = _gp_canvas_active_modes(canvas)
    return modes[0] if modes else ""

def _gp_mask_is_live_paint_mode(canvas):
    """True only for GP paint/draw modes that can safely update live pixels."""
    return "PAINT_GREASE_PENCIL" in _gp_canvas_active_modes(canvas)


def _gp_mask_is_structural_edit_mode(canvas):
    """True whenever an active GP mask is not in Object or Paint mode.

    Blender 5.2 exposes generic ``EDIT``/``SCULPT`` values on Object.mode and
    more specific values on Context.mode. Treat every non-Object/non-Paint mode
    as unsafe so timers cannot sample CurvesGeometry during Alt+S or selection.
    """
    modes = _gp_canvas_active_modes(canvas)
    if not modes:
        return False
    paint_modes = {"PAINT_GREASE_PENCIL"}
    if any(mode in paint_modes for mode in modes):
        return False
    if all(mode == "OBJECT" for mode in modes):
        return False
    return True


def _gp_mask_refresh_blocked_by_edit_mode(canvas):
    """True while Blender is mutating GP curve data in-place.

    Ordinary depsgraph and paint refresh paths treat this as a hard barrier.
    The structural quiet-time timer explicitly opts in only after native edit
    activity and the transition guard have both settled.
    """
    return _gp_mask_is_structural_edit_mode(canvas)


def _gp_live_editing(canvas):
    """Return True only while live paint refresh is safe.

    Edit/Sculpt/Weight/Vertex modes still invalidate the mask through the
    depsgraph, but they are finalized only after leaving structural edit mode.
    """
    return _gp_mask_is_live_paint_mode(canvas)


def _structural_edit_canvases():
    """Return the active structural-edit GP mask without scanning the registry.

    ``_gp_mask_is_structural_edit_mode`` only considers Blender's active object,
    so the previous implementation walked every registered mask even though at
    most one canvas could ever pass the predicate. This hot-path shortcut keeps
    the same behavior while avoiding an O(number of canvases) scan per depsgraph
    update.
    """
    try:
        context = getattr(bpy, "context", None)
        active = getattr(context, "object", None) or getattr(context, "active_object", None)
    except FBP_DATA_ERRORS:
        active = None
    if not is_gp_canvas(active):
        return ()
    pointer = _canvas_pointer(active)
    registered = _gp_canvas_by_pointer(pointer) if pointer else None
    if not is_gp_canvas(registered):
        return ()
    try:
        has_mask = bool(
            is_gp_mask_canvas(registered)
            or getattr(registered, "fbp_gp_mask_image", None) is not None
        )
    except FBP_DATA_ERRORS:
        has_mask = False
    if not has_mask or not _gp_mask_is_structural_edit_mode(registered):
        return ()
    return (registered,)


def _updated_structural_edit_canvases(updates, canvases):
    """Return only Edit Mode canvases whose object or GP data actually changed."""
    by_object = {_canvas_pointer(canvas): canvas for canvas in canvases}
    by_data = {
        _data_pointer(getattr(canvas, "data", None)): canvas
        for canvas in canvases
    }
    affected = OrderedDict()
    for update in updates:
        updated = _original_datablock(getattr(update, "id", None))
        pointer = _data_pointer(updated)
        canvas = by_object.get(pointer)
        if canvas is None and _is_grease_pencil_data_block(updated):
            canvas = by_data.get(pointer)
            if canvas is not None:
                _clear_gp_exposure_cache(data=updated)
        if canvas is not None:
            affected[_canvas_pointer(canvas)] = canvas
    return tuple(affected.values())


def _queue_structural_gp_mask_edit(canvas, scene=None):
    """Remember an Edit Mode mutation without touching GP curve data.

    Blender 5.2 can mutate/free CurvesGeometry while Edit Mode operators are
    running. The depsgraph callback records only canvas/scene pointers; a timer
    reads the published result after both edit activity and the transition guard
    have gone quiet.
    """
    key = _gp_mask_dirty_key(canvas, scene)
    if key[0]:
        _GP_MASK_STRUCTURAL_EDIT_PENDING.add(key)
        _GP_MASK_STRUCTURAL_EDIT_LAST[key] = time.monotonic()
        _schedule_structural_gp_mask_preview(canvas, scene)
    return key


def _drawing_nonempty_curve_indices(drawing):
    """Return curve indices that currently own at least one point."""
    try:
        offsets = getattr(drawing, "curve_offsets", None)
        count = len(offsets) if offsets is not None else 0
    except FBP_DATA_ERRORS:
        return ()
    if count < 2:
        return ()
    values = [0] * count
    try:
        offsets.foreach_get("value", values)
        values = [int(value) for value in values]
    except FBP_DATA_ERRORS:
        values = []
        for index in range(count):
            try:
                item = offsets[index]
                values.append(int(getattr(item, "value", item)))
            except FBP_DATA_ERRORS:
                return ()
    return tuple(
        index for index in range(len(values) - 1)
        if values[index + 1] > values[index]
    )


def _sync_gp_mask_authored_modes_from_native(canvas, scene=None, *, allow_edit_mode=False):
    """Mirror safe post-edit native Stroke/Fill/Both values into metadata.

    Native values always win.  Existing authoring metadata is kept only for
    curves where Blender exposes no native type.  This makes
    ``grease_pencil.set_stroke_type`` affect exactly the edited curves while
    preserving Paint Mode authoring on builds that omit the attribute.
    """
    if not is_gp_mask_canvas(canvas) or (
        _gp_mask_refresh_blocked_by_edit_mode(canvas) and not allow_edit_mode
    ):
        return False
    try:
        target_scene = _scene_for_canvas(canvas, scene)
        frame_number = _scene_current_frame_number(target_scene, 1)
        _exposure_key, exposure_state = _canvas_exposure_state(
            canvas, frame_number, rebuild_index=True
        )
    except FBP_DATA_ERRORS:
        return False

    native_modes = []
    native_found = False
    for _layer, drawing, _source_frame in exposure_state:
        if drawing is None:
            continue
        signature = _drawing_curve_mode_signature(drawing)
        if not signature:
            continue
        indices = _drawing_nonempty_curve_indices(drawing)
        if not indices:
            indices = tuple(range(len(signature)))
        for curve_index in indices:
            mode = signature[curve_index] if curve_index < len(signature) else "AUTO"
            mode = _normalize_gp_stroke_type(mode, "AUTO")
            native_modes.append(mode)
            native_found = bool(native_found or mode in {"STROKE", "FILL", "BOTH"})

    if not native_modes or not native_found:
        return False

    existing = [
        _normalize_gp_stroke_type(value, "AUTO")
        for value in _json_list_from_canvas(canvas, "fbp_gp_mask_curve_modes_json")
    ]
    merged = []
    for index, native_mode in enumerate(native_modes):
        if native_mode in {"STROKE", "FILL", "BOTH"}:
            merged.append(native_mode)
        elif index < len(existing) and existing[index] in {"STROKE", "FILL", "BOTH"}:
            merged.append(existing[index])
        else:
            merged.append("AUTO")
    return _idprop_set_if_changed(
        canvas,
        "fbp_gp_mask_curve_modes_json",
        json.dumps(merged, separators=(",", ":")),
    )


def _schedule_structural_gp_mask_preview(canvas, scene=None):
    """Refresh an Edit Mode mask only after native GP data has settled.

    Blender may rebuild CurvesGeometry for several depsgraph ticks during Set
    Stroke Type and Shrink/Fatten. The handler never touches that data. This
    deduplicated timer waits for a quiet interval and for the transition guard,
    then performs one capped preview read. Full quality remains deferred until
    mode exit, which keeps the expensive raster pass out of interactive edits.
    """
    key = _gp_mask_dirty_key(canvas, scene)
    pointer, scene_pointer = key
    if not pointer:
        return False

    def _preview():
        if fbp_undo_guard_active() or fbp_render_mutation_blocked():
            return _GP_MASK_EDIT_POLL_SECONDS
        if not fbp_depsgraph_quiet_for(0.20):
            return _GP_MASK_EDIT_POLL_SECONDS
        current = _gp_canvas_by_pointer(pointer)
        if not is_gp_mask_canvas(current):
            return None
        refresh_scene = _scene_by_pointer(scene_pointer) or _scene_for_canvas(current, None)
        if not _gp_mask_is_structural_edit_mode(current):
            return None
        last_activity = float(_GP_MASK_STRUCTURAL_EDIT_LAST.get(key, 0.0) or 0.0)
        quiet_for = time.monotonic() - last_activity
        if quiet_for < _GP_MASK_EDIT_DEFER_SECONDS:
            return max(0.05, min(_GP_MASK_EDIT_POLL_SECONDS, _GP_MASK_EDIT_DEFER_SECONDS - quiet_for))
        transition_wait = _gp_mask_mode_transition_guard_active(current, refresh_scene)
        if transition_wait > 0.0:
            return max(0.05, min(_GP_MASK_EDIT_POLL_SECONDS, transition_wait))

        _sync_gp_mask_authored_modes_from_native(
            current, refresh_scene, allow_edit_mode=True
        )
        _bump_gp_geometry_generation(current)
        try:
            current[KEY_MASK_DIRTY] = True
            current[KEY_MASK_GEOMETRY_DIRTY] = True
            current[KEY_MASK_BAKED] = False
        except FBP_DATA_ERRORS:
            return None
        refresh_gp_mask(
            current,
            force=False,
            scene=refresh_scene,
            allow_edit_mode=True,
        )
        return None

    return schedule_once(
        f"grease_pencil.mask_edit_preview:{pointer}:{scene_pointer}",
        _preview,
        first_interval=max(0.10, _GP_MASK_EDIT_DEFER_SECONDS),
    )


def _flush_structural_gp_mask_edits(scene=None):
    """Finalize native Edit Mode changes after Blender returns to a safe mode."""
    if not _GP_MASK_STRUCTURAL_EDIT_PENDING:
        return False
    pending = tuple(_GP_MASK_STRUCTURAL_EDIT_PENDING)
    _GP_MASK_STRUCTURAL_EDIT_PENDING.clear()
    scheduled = False

    for pointer, scene_pointer in pending:
        canvas = _gp_canvas_by_pointer(pointer)
        if not is_gp_canvas(canvas):
            _GP_MASK_STRUCTURAL_EDIT_LAST.pop((pointer, scene_pointer), None)
            continue
        if _gp_mask_refresh_blocked_by_edit_mode(canvas):
            _GP_MASK_STRUCTURAL_EDIT_PENDING.add((pointer, scene_pointer))
            continue

        target_scene = _scene_by_pointer(scene_pointer) or _scene_for_canvas(canvas, scene)
        resolved_scene_pointer = _canvas_pointer(target_scene) or scene_pointer
        key = (pointer, resolved_scene_pointer)

        def _post_edit_refresh(
            pointer=pointer,
            scene_pointer=resolved_scene_pointer,
            key=key,
        ):
            if fbp_undo_guard_active() or fbp_render_mutation_blocked():
                return _GP_MASK_EDIT_POLL_SECONDS
            if not fbp_depsgraph_quiet_for(0.25):
                return _GP_MASK_EDIT_POLL_SECONDS
            current = _gp_canvas_by_pointer(pointer)
            if not is_gp_canvas(current):
                _GP_MASK_STRUCTURAL_EDIT_LAST.pop(key, None)
                return None
            refresh_scene = _scene_by_pointer(scene_pointer)
            if _gp_mask_refresh_blocked_by_edit_mode(current):
                _GP_MASK_STRUCTURAL_EDIT_PENDING.add(key)
                return _GP_MASK_EDIT_POLL_SECONDS
            transition_wait = _gp_mask_mode_transition_guard_active(current, refresh_scene)
            if transition_wait > 0.0:
                return max(0.05, min(_GP_MASK_EDIT_POLL_SECONDS, transition_wait))

            # All GP reads happen here, outside Edit Mode and outside depsgraph
            # handlers.  This is the safe point for native Set Stroke Type.
            _sync_gp_mask_authored_modes_from_native(current, refresh_scene)
            _bump_gp_geometry_generation(current)
            try:
                current[KEY_MASK_DIRTY] = True
                current[KEY_MASK_GEOMETRY_DIRTY] = True
                current[KEY_MASK_BAKED] = False
            except FBP_DATA_ERRORS:
                _GP_MASK_STRUCTURAL_EDIT_LAST.pop(key, None)
                return None
            refresh_gp_mask(current, force=True, scene=refresh_scene, allow_edit_mode=False)
            _GP_MASK_STRUCTURAL_EDIT_LAST.pop(key, None)
            return None

        scheduled = bool(
            schedule_once(
                f"grease_pencil.mask_post_edit:{pointer}:{resolved_scene_pointer}",
                _post_edit_refresh,
                first_interval=max(0.15, _GP_MASK_EDIT_DEFER_SECONDS),
            ) or scheduled
        )
    return scheduled


def _note_gp_mask_dirty(canvas, scene=None, *, immediate=False):
    key = _gp_mask_dirty_key(canvas, scene)
    if not key[0]:
        return key
    now = time.monotonic()
    if key not in _GP_MASK_FIRST_DIRTY_TIME:
        _GP_MASK_FIRST_DIRTY_TIME[key] = now
    _GP_MASK_DIRTY_TIME[key] = now
    if immediate:
        _GP_MASK_IMMEDIATE_KEYS.add(key)
    return key


def _clear_gp_mask_dirty_note(key):
    _GP_MASK_DIRTY_TIME.pop(key, None)
    _GP_MASK_FIRST_DIRTY_TIME.pop(key, None)
    _GP_MASK_IMMEDIATE_KEYS.discard(key)


def _gp_mask_refresh_wait(canvas, scene=None):
    key = _gp_mask_dirty_key(canvas, scene)
    if key in _GP_MASK_IMMEDIATE_KEYS and _gp_mask_mode_transition_guard_active(canvas, scene) <= 0.0:
        return 0.0
    transition_wait = _gp_mask_mode_transition_guard_active(canvas, scene)
    if transition_wait > 0.0:
        return max(0.05, min(_GP_MASK_EDIT_POLL_SECONDS, transition_wait))
    last_dirty = float(_GP_MASK_DIRTY_TIME.get(key, 0.0) or 0.0)
    if last_dirty <= 0.0:
        return 0.0
    now = time.monotonic()
    first_dirty = float(_GP_MASK_FIRST_DIRTY_TIME.get(key, last_dirty) or last_dirty)
    age = now - last_dirty
    total_age = now - first_dirty
    if _gp_mask_refresh_blocked_by_edit_mode(canvas):
        return 0.0
    else:
        quiet = _GP_MASK_LIVE_QUIET_SECONDS if _gp_live_editing(canvas) else _GP_MASK_IDLE_QUIET_SECONDS
    if total_age >= _GP_MASK_MAX_DEBOUNCE_SECONDS:
        return 0.0
    if age < quiet:
        return max(0.01, min(0.08, quiet - age))
    return 0.0


def mark_gp_mask_dirty(canvas, *, schedule=True, geometry=True, scene=None, immediate=False, sync_registry=True):
    if not is_gp_canvas(canvas):
        return False
    # Native GP Edit/Sculpt/Weight/Vertex modes are a hard no-touch zone in
    # Blender 5.2. Queue only process-local state; do not write ID properties
    # or bump caches while Blender is rebuilding CurvesGeometry/GPU batches.
    if _gp_mask_refresh_blocked_by_edit_mode(canvas):
        _pause_gp_mask_mode_transition(canvas, scene, seconds=_GP_MASK_MODE_TRANSITION_SECONDS)
        return False
    transition_wait = _gp_mask_mode_transition_guard_active(canvas, scene)
    if transition_wait > 0.0 and not immediate:
        schedule = True
    _register_runtime_canvas(canvas)
    pointer = _canvas_pointer(canvas)
    if geometry:
        _bump_gp_geometry_generation(canvas)
    try:
        canvas[KEY_MASK_DIRTY] = True
        if geometry:
            canvas[KEY_MASK_GEOMETRY_DIRTY] = True
        canvas[KEY_MASK_BAKED] = False
        auto_refresh = _gp_mask_live_refresh_enabled(canvas)
        has_mask_output = getattr(canvas, "fbp_gp_mask_image", None) is not None
    except FBP_DATA_ERRORS:
        return False
    if sync_registry:
        _sync_frame_mask_registry(canvas, refresh_sensitivity=False, scene=scene)
    if schedule and auto_refresh and has_mask_output and pointer:
        target_scene = _scene_for_canvas(canvas, scene)
        scene_pointer = _canvas_pointer(target_scene)
        dirty_key = _note_gp_mask_dirty(canvas, target_scene, immediate=immediate)
        def _refresh():
            current = _gp_canvas_by_pointer(pointer)
            if not is_gp_canvas(current):
                _clear_gp_mask_dirty_note(dirty_key)
                return None
            refresh_scene = _scene_by_pointer(scene_pointer) or _scene_for_canvas(current, None)
            wait = _gp_mask_refresh_wait(current, refresh_scene)
            if wait > 0.0:
                return wait
            if _gp_mask_refresh_blocked_by_edit_mode(current):
                _clear_gp_mask_dirty_note(dirty_key)
                return None
            if not _gp_live_editing(current) and not fbp_depsgraph_quiet_for(0.25):
                return 0.08
            _clear_gp_mask_dirty_note(dirty_key)
            refresh_gp_mask(
                current,
                force=False,
                scene=refresh_scene,
                allow_edit_mode=False,
            )
            return None
        # Scene is part of the refresh identity. A canvas can be linked in
        # multiple scenes with different frame ranges/current frames; a pending
        # refresh for one scene must not collapse a later refresh from another.
        task_name = f"grease_pencil.mask_refresh:{pointer}:{scene_pointer}"
        scheduled = bool(
            schedule_once(
                task_name,
                _refresh,
                first_interval=0.0 if immediate else 0.01,
            )
        )
        if not scheduled and not scheduled_task_pending(task_name):
            _clear_gp_mask_dirty_note(dirty_key)
    return True


def _gp_property_update_blocked(owner=None):
    return bool(
        fbp_undo_guard_active()
        or (owner is not None and fbp_is_silent_property_update(owner))
    )



def _attachment_mode_update(self, _context):
    """Restore a useful mode-specific distance when switching attachment space."""
    if _gp_property_update_blocked(self):
        return
    try:
        current = str(getattr(self, "fbp_gp_attachment_mode", "PLANE") or "PLANE")
        previous = str(self.get(KEY_LAST_ATTACHMENT, "PLANE") or "PLANE")
        distance = float(getattr(self, "fbp_gp_canvas_distance", 0.003) or 0.0)
        if previous == "PLANE":
            self[KEY_PLANE_DISTANCE] = distance
        elif previous == "CAMERA":
            self[KEY_CAMERA_DISTANCE] = distance
        self[KEY_LAST_ATTACHMENT] = current
        if current == "PLANE":
            desired = float(self.get(KEY_PLANE_DISTANCE, 0.003))
        elif current == "CAMERA":
            desired = float(self.get(KEY_CAMERA_DISTANCE, 1.0) or 1.0)
        else:
            desired = distance
        if abs(distance - desired) > 1.0e-8:
            self.fbp_gp_canvas_distance = desired
            return
        sync_canvas_transform(self, scene=_context.scene if _context else None)
        mark_gp_mask_dirty(self, geometry=True, scene=_context.scene if _context else None)
    except FBP_DATA_ERRORS:
        pass


def _canvas_property_update(self, _context):
    if _gp_property_update_blocked(self):
        return
    try:
        scene = _context.scene if _context else None
        sync_canvas_transform(self, scene=scene)
        mark_gp_mask_dirty(self, geometry=True, scene=scene)
        schedule_gp_cycles_proxy_sync(scene, self)
    except FBP_DATA_ERRORS:
        pass


def _canvas_visibility_update(self, _context):
    if _gp_property_update_blocked(self):
        return
    try:
        scene = _context.scene if _context else None
        sync_canvas_transform(self, scene=scene)
        schedule_gp_cycles_proxy_sync(scene, self)
    except FBP_DATA_ERRORS:
        pass


def _canvas_opacity_update(self, _context):
    if _gp_property_update_blocked(self):
        return
    _apply_canvas_opacity(self)
    schedule_gp_cycles_proxy_sync(_context.scene if _context else None, self)


def _onion_update(self, _context):
    if _gp_property_update_blocked(self):
        return
    try:
        data = getattr(self, "data", None)
        if data is not None:
            data.onion_factor = 0.35
            data.use_onion_fade = True
            for layer in data.layers:
                layer.use_onion_skinning = bool(self.fbp_gp_onion_skin)
    except FBP_DATA_ERRORS:
        pass


def _reference_opacity_update(self, _context):
    if _gp_property_update_blocked(self):
        return
    rig = gp_canvas_owner(self)
    if rig is None:
        return
    try:
        workflow_state = str(getattr(self, "fbp_gp_workflow_state", "INK") or "INK")
        if workflow_state != "INK":
            return
        opacity = float(self.fbp_gp_reference_opacity)
        if not fbp_set_rna_property_silent(rig, "fbp_opacity", opacity):
            return
        from .materials import do_update_opacity
        do_update_opacity(rig)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not update Grease Pencil reference opacity", exc)


def _mask_geometry_property_update(self, _context):
    if _gp_property_update_blocked(self):
        return
    scene = getattr(_context, "scene", None) if _context else None
    try:
        # Finalize every already committed curve with the mode that was active
        # *before* changing the brush. GPv3 can publish curve ranges one update
        # later than their points; switching the brush first made delayed curves
        # inherit the next stroke's mode and shifted Fill/Both across the mask.
        previous_mode = _normalize_gp_stroke_type(
            self.get("fbp_gp_mask_active_brush_mode", "STROKE"),
            "STROKE",
        )
        # Rebuild the exposure index before recording the mode boundary. The
        # cached timeline may still point at the previous depsgraph tick just
        # after a stroke is committed; using it shifted Fill/Both onto stroke 1.
        committed_curve_count = _gp_mask_curve_count(
            self,
            scene,
            rebuild_index=True,
        )
        _sync_gp_mask_authored_curve_state(
            self,
            scene=scene,
            context=_context,
            observed_weight=(committed_curve_count, 0),
            brush_mode_override=previous_mode,
            rebuild_index=True,
        )
        requested_mode = str(getattr(self, "fbp_gp_mask_source", "AUTO") or "AUTO").upper()
        _set_active_gp_brush_stroke_type(_context, requested_mode)
        # The canvas authoring mode is authoritative. Blender's brush RNA is
        # global and can be absent/stale depending on the active GP tool.
        active_mode = requested_mode if requested_mode in {"STROKE", "FILL", "BOTH"} else previous_mode
        _idprop_set_if_changed(self, "fbp_gp_mask_active_brush_mode", active_mode)
    except FBP_DATA_ERRORS:
        pass
    _canvas_geometry_changes_with_frame(self, refresh=True, scene=scene)
    _canvas_mask_changes_with_frame(self, refresh=True, scene=scene)
    _sync_frame_mask_registry(self, refresh_sensitivity=False, scene=scene)
    mark_gp_mask_dirty(
        self,
        geometry=True,
        scene=scene,
    )


def _mask_output_property_update(self, _context):
    if _gp_property_update_blocked(self):
        return
    # Invert and Mask Opacity affect only shader bindings. Do not re-hash or
    # rasterize unchanged Grease Pencil geometry while these controls are dragged.
    try:
        _sync_canvas_mask_bindings(self)
    except FBP_DATA_ERRORS:
        pass


def _mask_raster_property_update(self, _context):
    if _gp_property_update_blocked(self):
        return
    scene = getattr(_context, "scene", None) if _context else None
    # Blur, Expand, Threshold and Quality change the generated image but not the
    # Grease Pencil point/contour extraction. Keep geometry and distance caches
    # reusable where possible and only regenerate the RGBA mask output.  Property
    # edits are intentional user actions, so bypass the live-preview cap once: this
    # lets Quality immediately reach 1024 even while the object remains in GP Paint
    # mode but the stylus is idle.
    try:
        self[KEY_MASK_FORCE_FULL_QUALITY_ONCE] = True
    except FBP_DATA_ERRORS:
        pass
    _canvas_mask_changes_with_frame(self, refresh=True, scene=scene)
    _sync_frame_mask_registry(self, refresh_sensitivity=False, scene=scene)
    mark_gp_mask_dirty(
        self,
        geometry=False,
        scene=scene,
        immediate=True,
    )


def _gp_mask_pointer_update(effect_id):
    """Update one shader slot after an image pointer changes."""
    def _update(self, _context):
        if _gp_property_update_blocked(self):
            return
        try:
            from .geometry_nodes import fbp_update_shader_effect, fbp_effect_is_active
            if fbp_effect_is_active(self, effect_id):
                fbp_update_shader_effect(self, effect_id, property_names=None)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return _update


def _gp_mask_canvas_pointer_update(_effect_id):
    """Canvas pointers affect ownership lookup, not the shader image itself."""
    def _update(_self, _context):
        if _gp_property_update_blocked(_self):
            return
        _invalidate_gp_binding_cache()
    return _update


_imported_mask_pointer_update = _gp_mask_pointer_update("IMPORTED_MASK")
_gp_mask_slot_2_pointer_update = _gp_mask_pointer_update("GP_MASK_SLOT_2")
_gp_mask_slot_3_pointer_update = _gp_mask_pointer_update("GP_MASK_SLOT_3")
_gp_mask_slot_4_pointer_update = _gp_mask_pointer_update("GP_MASK_SLOT_4")
_imported_mask_canvas_pointer_update = _gp_mask_canvas_pointer_update("IMPORTED_MASK")
_gp_mask_slot_2_canvas_pointer_update = _gp_mask_canvas_pointer_update("GP_MASK_SLOT_2")
_gp_mask_slot_3_canvas_pointer_update = _gp_mask_canvas_pointer_update("GP_MASK_SLOT_3")
_gp_mask_slot_4_canvas_pointer_update = _gp_mask_canvas_pointer_update("GP_MASK_SLOT_4")


def _gp_native_attr_candidates(attr_name):
    """Return property aliases for a native GP effect item.

    Kept as a module-level constant so drawing and reset paths do not allocate
    a large alias dictionary for every property row in the Modifiers panel.
    """
    if isinstance(attr_name, (tuple, list)):
        return tuple(str(item) for item in attr_name if str(item or ""))
    attr_name = str(attr_name or "")
    return _GP_NATIVE_ATTR_ALIASES.get(attr_name, (attr_name,))


def _gp_resolve_native_attr(item, attr_name):
    if item is None:
        return ""
    try:
        cache_key = (type(item).__name__, _data_pointer(getattr(item, "bl_rna", None)), str(attr_name or ""))
        cached = _GP_NATIVE_ATTR_RESOLVE_CACHE.get(cache_key)
        if cached is not None:
            return cached
    except FBP_DATA_ERRORS:
        cache_key = None
    for candidate in _gp_native_attr_candidates(attr_name):
        try:
            if hasattr(item, candidate):
                if cache_key is not None:
                    _GP_NATIVE_ATTR_RESOLVE_CACHE[cache_key] = candidate
                return candidate
        except FBP_DATA_ERRORS:
            continue
    if cache_key is not None:
        _GP_NATIVE_ATTR_RESOLVE_CACHE[cache_key] = ""
    return ""


def _gp_native_property_rna(item, attr_name):
    try:
        properties = getattr(getattr(item, "bl_rna", None), "properties", None)
        if properties is not None and hasattr(properties, "get"):
            return properties.get(attr_name)
    except FBP_DATA_ERRORS:
        pass
    return None


def _gp_clamp_native_number(value, prop):
    try:
        number = float(value)
        hard_min = getattr(prop, "hard_min", None) if prop is not None else None
        hard_max = getattr(prop, "hard_max", None) if prop is not None else None
        if hard_min is not None:
            number = max(float(hard_min), number)
        if hard_max is not None:
            number = min(float(hard_max), number)
        return number
    except FBP_DATA_ERRORS:
        return value


def _gp_coerce_native_default_value(item, attr_name, value):
    """Coerce preset defaults to the active Blender RNA property shape.

    Grease Pencil effects expose vectors, arrays, enums and scalars depending on
    backend and Blender version.  Coerce before assignment so one preset default
    does not abort because a property changed from vector to scalar, or vice versa.
    """
    prop = _gp_native_property_rna(item, attr_name)
    try:
        current = getattr(item, attr_name)
    except FBP_DATA_ERRORS:
        current = None
    if isinstance(current, bool):
        return bool(value)
    if isinstance(current, int) and not isinstance(current, bool):
        return int(round(_gp_clamp_native_number(value, prop)))
    if isinstance(current, float):
        return float(_gp_clamp_native_number(value, prop))
    if isinstance(current, str):
        return str(value)
    if current is not None and hasattr(current, "__len__") and not isinstance(current, (str, bytes)):
        try:
            length = len(current)
            if isinstance(value, (str, bytes)):
                return value
            values = tuple(value) if hasattr(value, "__iter__") else (value,)
            if not values:
                return value
            if len(values) < length:
                values = values + tuple(values[-1] for _ in range(length - len(values)))
            return tuple(values[:length])
        except FBP_DATA_ERRORS:
            return value
    return value


def _gp_set_native_default(item, attr_name, value):
    """Set a Blender native effect property without failing the creation path."""
    try:
        resolved = _gp_resolve_native_attr(item, attr_name)
        if resolved:
            setattr(item, resolved, _gp_coerce_native_default_value(item, resolved, value))
            return True
    except FBP_DATA_ERRORS:
        pass
    return False


def _gp_native_effect_collection(canvas, backend):
    if backend == "SHADER_FX":
        return getattr(canvas, "shader_effects", None)
    return getattr(canvas, "modifiers", None)


def _gp_native_collection_supported_types(collection):
    """Return native type enum identifiers supported by a GP collection.

    Blender may rename or remove individual Grease Pencil shader effects and
    modifiers between releases.  Query the RNA enum once per collection class so
    the UI can disable unavailable entries instead of creating an operator that
    immediately fails.  ``None`` means the enum could not be inspected, so the
    caller should fall back to Blender's own creation error handling.
    """
    if collection is None:
        return frozenset()
    try:
        collection_type = type(collection).__name__
        cache_key = (collection_type, _data_pointer(getattr(collection, "bl_rna", None)))
        if cache_key in _GP_NATIVE_TYPE_SUPPORT_CACHE:
            return _GP_NATIVE_TYPE_SUPPORT_CACHE[cache_key]
        functions = getattr(getattr(collection, "bl_rna", None), "functions", None)
        new_fn = functions.get("new") if functions is not None and hasattr(functions, "get") else None
        parameters = getattr(new_fn, "parameters", None) if new_fn is not None else None
        type_param = parameters.get("type") if parameters is not None and hasattr(parameters, "get") else None
        enum_items = getattr(type_param, "enum_items", None) if type_param is not None else None
        if enum_items is None:
            _GP_NATIVE_TYPE_SUPPORT_CACHE[cache_key] = None
            return None
        supported = frozenset(str(getattr(item, "identifier", "") or "") for item in enum_items)
        _GP_NATIVE_TYPE_SUPPORT_CACHE[cache_key] = supported
        return supported
    except FBP_DATA_ERRORS:
        return None


def _gp_native_type_candidates(definition):
    if definition is None:
        return ()
    try:
        native_types = definition[4]
        if isinstance(native_types, str):
            return (native_types,)
        return tuple(str(item) for item in native_types if str(item or ""))
    except (IndexError, TypeError, ValueError):
        return ()


def _gp_supported_native_type(canvas, definition):
    if definition is None or not is_gp_drawing_canvas(canvas):
        return ""
    _effect_id, _label, _icon, backend, _native_types = definition
    collection = _gp_native_effect_collection(canvas, backend)
    if collection is None:
        return ""
    candidates = _gp_native_type_candidates(definition)
    if not candidates:
        return ""
    supported = _gp_native_collection_supported_types(collection)
    if supported is None:
        return candidates[0]
    for native_type in candidates:
        if native_type in supported:
            return native_type
    return ""


def _gp_native_effect_supported(canvas, definition):
    return bool(_gp_supported_native_type(canvas, definition))


def _gp_tag_native_effect_item(item, effect_id):
    try:
        item[KEY_GP_NATIVE_EFFECT_ID] = str(effect_id or "").upper()
        return True
    except FBP_DATA_ERRORS:
        return False


def _gp_native_effect_id_from_item(item, definitions):
    """Resolve only explicitly tagged Frame By Plane native effects.

    Stack scans run from UI draw paths, so this helper must remain read-only.
    The 7.1 baseline always tags newly created items; adopting effects from a
    name prefix would both mutate RNA during draw and risk claiming artist work.
    """
    try:
        tagged = str(item.get(KEY_GP_NATIVE_EFFECT_ID, "") or "").upper()
        return tagged if tagged in definitions else ""
    except FBP_DATA_ERRORS:
        return ""


def _gp_native_effect_instances(canvas):
    """Return FBP-owned native GP instances using the shared stack scan."""
    if not is_gp_drawing_canvas(canvas):
        return {}
    active, _ordered, _backend_lengths, _duplicate_counts = _gp_native_effect_stack_state(canvas)
    return dict(active)


def _gp_native_effect_definition(effect_id):
    return _gp_native_effect_definitions().get(str(effect_id or "").upper())


def _gp_native_effect_name(effect_id):
    return f"{GP_EFFECT_NAME_PREFIX}{str(effect_id or '').upper()}"


def _gp_native_effect_instance(canvas, effect_id):
    definition = _gp_native_effect_definition(effect_id)
    if not is_gp_drawing_canvas(canvas) or definition is None:
        return None
    try:
        return _gp_native_effect_instances(canvas).get(str(effect_id or "").upper())
    except FBP_DATA_ERRORS:
        return None


def _gp_native_effect_location(canvas, effect_id):
    """Return definition, collection, item and index for an FBP-owned GP effect."""
    definition = _gp_native_effect_definition(effect_id)
    if definition is None or not is_gp_drawing_canvas(canvas):
        return (None, None, None, -1)
    collection = _gp_native_effect_collection(canvas, definition[3])
    if collection is None:
        return (definition, None, None, -1)
    definitions = _gp_native_effect_definitions()
    target_id = str(effect_id or "").upper()
    try:
        for index, item in enumerate(collection):
            if _gp_native_effect_id_from_item(item, definitions) == target_id:
                return (definition, collection, item, index)
    except FBP_DATA_ERRORS:
        pass
    return (definition, collection, None, -1)


def _gp_native_effect_stack_state(canvas):
    """Scan native GP effect stacks once for UI redraw and menu state.

    Returns ``(active_map, ordered_items, backend_lengths, duplicate_counts)``.
    The duplicate count is collected in the same pass as active items, avoiding
    an extra full stack scan every time the Modifiers panel draws.
    """
    if not is_gp_drawing_canvas(canvas):
        return ({}, (), {}, {})
    definitions = _gp_native_effect_definitions()
    active = {}
    ordered = []
    backend_lengths = {}
    duplicate_counts = {}
    seen = set()
    for backend in _GP_NATIVE_BACKENDS:
        collection = _gp_native_effect_collection(canvas, backend)
        if collection is None:
            backend_lengths[backend] = 0
            continue
        try:
            backend_lengths[backend] = len(collection)
        except FBP_DATA_ERRORS:
            backend_lengths[backend] = 0
        try:
            for index, item in enumerate(collection):
                effect_id = _gp_native_effect_id_from_item(item, definitions)
                if not effect_id:
                    continue
                duplicate_counts[effect_id] = int(duplicate_counts.get(effect_id, 0)) + 1
                if effect_id not in seen:
                    seen.add(effect_id)
                    active[effect_id] = item
                    ordered.append((effect_id, item, backend, index))
        except FBP_DATA_ERRORS:
            continue
    return (active, tuple(ordered), backend_lengths, duplicate_counts)


_GP_NATIVE_EFFECT_DEFAULTS = {
    "PIXELATE": (("size", (8, 8)), ("use_antialiasing", False)),
    "RIM": (("offset", (2, -2)), ("blur", (1, 1))),
    "SHADOW": (("offset", (8, -8)), ("blur", (4, 4))),
    "SWIRL": (("radius", 1.0), ("angle", 0.785398)),
    "WAVE_WARP": (("amplitude", 0.05), ("period", 20.0), ("phase", 0.0)),
    "GAUSSIAN_BLUR": (("size", (6.0, 6.0)), ("samples", 8)),
    "GP_GLOW": (("threshold", 0.35), ("intensity", 0.35), ("blur", (6.0, 6.0))),
    "GP_COLORIZE": (("factor", 1.0),),
    "GP_OPACITY": (("factor", 1.0),),
    "GP_FLIP": (("flip_horizontal", False), ("flip_vertical", True)),
    "GP_NOISE": (("factor", 0.25), ("factor_thickness", 0.1), ("noise_scale", 0.5)),
    "GP_SMOOTH": (("factor", 0.35), ("step", 2)),
    "HUE_SATURATION": (("hue", 0.5), ("saturation", 1.0), ("value", 1.0)),
    "RECOLOR": (("factor", 1.0),),
    "THICKNESS": (("thickness_factor", 1.1),),
    "CUTOUT_OUTLINE": (("thickness", 1), ("sample_length", 0.2)),
    "GP_ARRAY": (("count", 2), ("relative_offset", (0.08, 0.0, 0.0))),
    "GP_BUILD": (("start_frame", 1), ("end_frame", 40)),
    "GP_DASH": (("dash_length", 0.18), ("gap_length", 0.08)),
    "GP_ENVELOPE": (("spread", 0.02),),
    "GP_LENGTH": (("start_factor", 0.0), ("end_factor", 1.0)),
    "GP_OFFSET": (("offset_location", (0.0, 0.0, 0.0)), ("offset_rotation", (0.0, 0.0, 0.0)), ("offset_scale", (1.0, 1.0, 1.0))),
    "GP_SIMPLIFY": (("factor", 0.2),),
    "GP_TEXTURE": (("uv_scale", (1.0, 1.0)), ("uv_offset", (0.0, 0.0))),
    "GP_TIME_OFFSET": (("frame_offset", 0), ("frame_scale", 1.0)),
    "SURFACE_CONFORM": (("surface_offset", 0.0),),
}


def _gp_apply_native_effect_defaults(item, effect_id):
    """Apply lightweight Frame By Plane defaults to a native GP effect item."""
    effect_id = str(effect_id or "").upper()
    if item is None:
        return False
    changed = False
    for attr_name, value in _GP_NATIVE_EFFECT_DEFAULTS.get(effect_id, ()):
        changed |= _gp_set_native_default(item, attr_name, value)
    return changed


def _gp_native_effect_has_defaults(effect_id):
    return str(effect_id or "").upper() in _GP_NATIVE_EFFECT_DEFAULTS


def _gp_reset_native_effect(canvas, effect_id):
    _definition, _collection, item, _index = _gp_native_effect_location(canvas, effect_id)
    if item is None or not _gp_native_effect_has_defaults(effect_id):
        return False
    return _gp_apply_native_effect_defaults(item, effect_id)


def _gp_move_native_effect(canvas, effect_id, direction):
    """Move an FBP-owned native GP effect inside its Blender stack."""
    _definition, collection, item, index = _gp_native_effect_location(canvas, effect_id)
    if collection is None or item is None or index < 0:
        return False
    try:
        total = len(collection)
        if total <= 1:
            return False
        target = max(0, min(total - 1, index + int(direction)))
        if target == index:
            return False
        move = getattr(collection, "move", None)
        if callable(move):
            move(index, target)
            return True
    except FBP_DATA_ERRORS:
        pass
    return False


def _gp_new_native_effect_item(collection, name, native_type):
    """Create one Blender 5.2 native GP modifier/effect item."""
    if collection is None or not native_type:
        return None
    try:
        item = collection.new(name=name, type=native_type)
        if item is not None and str(getattr(item, "name", "") or "") != str(name):
            item.name = name
        return item
    except FBP_DATA_ERRORS:
        return None


def _gp_add_native_effect(canvas, effect_id):
    definition = _gp_native_effect_definition(effect_id)
    if definition is None or not is_gp_drawing_canvas(canvas):
        return None
    existing = _gp_native_effect_instance(canvas, effect_id)
    if existing is not None:
        return existing
    if not _gp_native_effect_supported(canvas, definition):
        return None
    _effect_id, _label, _icon, backend, _native_types = definition
    native_type = _gp_supported_native_type(canvas, definition)
    if not native_type:
        return None
    name = _gp_native_effect_name(effect_id)
    try:
        collection = _gp_native_effect_collection(canvas, backend)
        if collection is None:
            return None
        item = _gp_new_native_effect_item(collection, name, native_type)
        if item is None:
            return None
        _gp_tag_native_effect_item(item, effect_id)
        try:
            item["fbp_gp_native_type"] = str(native_type)
        except FBP_DATA_ERRORS:
            pass
        _gp_apply_native_effect_defaults(item, effect_id)
        if str(effect_id or "").upper() == "SURFACE_CONFORM":
            try:
                owner = gp_canvas_owner(canvas)
                target = getattr(owner, "fbp_plane_target", None) if owner is not None else None
                target_attr = _gp_resolve_native_attr(item, "target")
                if (
                    target is not None
                    and target is not canvas
                    and str(getattr(target, "type", "") or "") == "MESH"
                    and target_attr
                ):
                    setattr(item, target_attr, target)
            except FBP_DATA_ERRORS:
                pass
        return item
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not add native Grease Pencil effect {effect_id}", exc)
        return None


def _gp_repair_native_effect_duplicates(canvas):
    """Remove duplicate Frame By Plane GP effects while preserving stack order.

    Only items carrying a valid Frame By Plane native-effect identity are
    considered. The first instance in each Blender backend is retained and all
    later duplicates are removed. Artist-authored, untagged effects are never
    touched. Returns the number of removed duplicate items.
    """
    if not is_gp_drawing_canvas(canvas):
        return 0
    definitions = _gp_native_effect_definitions()
    removed = 0
    seen = set()
    for backend in _GP_NATIVE_BACKENDS:
        collection = _gp_native_effect_collection(canvas, backend)
        if collection is None:
            continue
        try:
            items = tuple(collection)
        except FBP_DATA_ERRORS:
            continue
        for item in items:
            try:
                effect_id = _gp_native_effect_id_from_item(item, definitions)
            except FBP_DATA_ERRORS:
                effect_id = ""
            if not effect_id:
                continue
            if effect_id not in seen:
                seen.add(effect_id)
                continue
            try:
                collection.remove(item)
                removed += 1
            except FBP_DATA_ERRORS as exc:
                fbp_warn(f"Could not remove duplicate native Grease Pencil effect {effect_id}", exc)
    return removed


def _gp_remove_native_effect(canvas, effect_id):
    definition = _gp_native_effect_definition(effect_id)
    if definition is None or not is_gp_drawing_canvas(canvas):
        return False
    collection = _gp_native_effect_collection(canvas, definition[3])
    if collection is None:
        return False
    target_id = str(effect_id or "").upper()
    definitions = _gp_native_effect_definitions()
    removed = False
    try:
        items = list(collection)
        for item in reversed(items):
            if _gp_native_effect_id_from_item(item, definitions) != target_id:
                continue
            collection.remove(item)
            removed = True
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not remove native Grease Pencil effect {effect_id}", exc)
    return removed


def _gp_draw_native_prop(layout, item, attr_name, *, text="", slider=False):
    try:
        resolved = _gp_resolve_native_attr(item, attr_name)
        if resolved:
            layout.prop(item, resolved, text=text, slider=slider)
            return True
    except FBP_DATA_ERRORS:
        pass
    return False


def _gp_draw_native_bool_icon(layout, item, attr_name, *, icon_on, icon_off):
    try:
        resolved = _gp_resolve_native_attr(item, attr_name)
        if resolved:
            value = bool(getattr(item, resolved))
            layout.prop(item, resolved, text="", icon=icon_on if value else icon_off, emboss=False)
            return True
    except FBP_DATA_ERRORS:
        pass
    return False


def _gp_native_item_name(item):
    try:
        return str(getattr(item, "name", "") or "")
    except FBP_DATA_ERRORS:
        return ""


def _gp_native_effect_open(item, default=True):
    """Return whether the inline Frame By Plane settings for an item are open."""
    try:
        return bool(item.get(KEY_GP_NATIVE_EFFECT_OPEN, bool(default)))
    except FBP_DATA_ERRORS:
        return bool(default)


def _gp_set_native_effect_open(item, state):
    try:
        item[KEY_GP_NATIVE_EFFECT_OPEN] = bool(state)
        return True
    except FBP_DATA_ERRORS:
        return False


_GP_NATIVE_EFFECT_UI_PROPS = {
    "PIXELATE": ((("size", "Pixel Size", False), ("use_antialiasing", "Antialiasing", False)),),
    "RIM": ((("rim_color", "Color", False),), (("offset", "Offset", False), ("blur", "Blur", False)), (("mode", "Blend", False),)),
    "SHADOW": ((("shadow_color", "Color", False),), (("offset", "Offset", False), ("blur", "Blur", False)), (("rotation", "Rotation", False),)),
    "SWIRL": ((("radius", "Radius", False), ("angle", "Angle", False)), (("use_transparent", "Transparent", False),)),
    "WAVE_WARP": ((("orientation", "Direction", False),), (("amplitude", "Amplitude", False), ("period", "Period", False)), (("phase", "Phase", False),)),
    "GAUSSIAN_BLUR": ((("size", "Size", False), ("samples", "Samples", False)), (("rotation", "Rotation", False),)),
    "GP_GLOW": ((("glow_color", "Color", False),), (("threshold", "Threshold", True), ("intensity", "Intensity", True)), (("blur", "Blur", False),)),
    "GP_COLORIZE": ((("low_color", "Low", False), ("high_color", "High", False)), (("factor", "Factor", True), ("color_mode", "Affect", False))),
    "GP_OPACITY": ((("factor", "Opacity", True), ("use_uniform_opacity", "Uniform", False)),),
    "GP_FLIP": ((("flip_horizontal", "Horizontal", False), ("flip_vertical", "Vertical", False)),),
    "GP_NOISE": ((("factor", "Position", True),), (("factor_strength", "Opacity", True), ("factor_thickness", "Thickness", True)), (("noise_scale", "Scale", False), ("seed", "Seed", False)), (("step", "Step", False),)),
    "GP_SMOOTH": ((("factor", "Factor", True), ("step", "Iterations", False)), (("use_keep_shape", "Keep Shape", False),)),
    "HUE_SATURATION": ((("hue", "Hue", True), ("saturation", "Saturation", True)), (("value", "Value", True),)),
    "RECOLOR": ((("color", "Color", False),), (("factor", "Factor", True), ("color_mode", "Affect", False))),
    "THICKNESS": ((("thickness_factor", "Factor", False), ("use_uniform_thickness", "Uniform", False)),),
    "CUTOUT_OUTLINE": ((("thickness", "Thickness", False), ("sample_length", "Sample Length", False)), (("use_keep_shape", "Keep Shape", False),)),
    "GP_ARRAY": ((("count", "Count", False),), (("relative_offset", "Offset", False), ("use_object_offset", "Object Offset", False))),
    "GP_BUILD": ((("start_frame", "Start", False), ("end_frame", "End", False)), (("transition", "Transition", False),)),
    "GP_DASH": ((("dash_length", "Dash", False), ("gap_length", "Gap", False)), (("dash_offset", "Offset", False),)),
    "GP_ENVELOPE": ((("spread", "Spread", False), ("skip", "Skip", False)),),
    "GP_LENGTH": ((("start_factor", "Start", True), ("end_factor", "End", True)),),
    "GP_MIRROR": ((("mirror_object", "Object", False),), (("use_axis_x", "X", False), ("use_axis_y", "Y", False), ("use_axis_z", "Z", False))),
    "GP_OFFSET": ((("offset_location", "Location", False),), (("offset_rotation", "Rotation", False),), (("offset_scale", "Scale", False),)),
    "GP_SIMPLIFY": ((("simplify_mode", "Mode", False),), (("factor", "Factor", True), ("distance", "Distance", False))),
    "GP_TEXTURE": ((("uv_offset", "Offset", False),), (("uv_scale", "Scale", False), ("uv_rotation", "Rotation", False))),
    "GP_TIME_OFFSET": ((("frame_offset", "Offset", False), ("frame_scale", "Scale", False)), (("use_custom_frame_range", "Frame Range", False),)),
    "SURFACE_CONFORM": ((("target", "Target", False),), (("wrap_method", "Method", False), ("wrap_mode", "Snap", False)), (("surface_offset", "Offset", False),)),
}


def _gp_draw_native_effect_prop_spec(layout, item, spec):
    """Draw compact native-effect properties, skipping unsupported rows.

    Property availability varies between native GP modifier/effect types. Check
    row availability before drawing so unsupported controls leave no blank rows.
    """
    drawn = False
    for row_spec in tuple(spec or ()):  # each row is one or more properties
        resolved_specs = []
        for attr_name, label, slider in tuple(row_spec or ()):
            resolved = _gp_resolve_native_attr(item, attr_name)
            if resolved:
                resolved_specs.append((attr_name, label, slider))
        if not resolved_specs:
            continue
        target = layout.row(align=True) if len(resolved_specs) > 1 else layout
        for attr_name, label, slider in resolved_specs:
            drawn |= _gp_draw_native_prop(target, item, attr_name, text=label, slider=bool(slider))
    return drawn


def _draw_gp_native_effect_settings(layout, effect_id, item, *, index=-1, total=1, duplicate_count=1):
    box = layout.box()
    header = box.row(align=True)
    definition = _gp_native_effect_definition(effect_id)
    label = definition[1] if definition else effect_id.replace("_", " ").title()
    icon = definition[2] if definition else "MODIFIER"
    expanded = _gp_native_effect_open(item, default=True)
    twist = header.operator(
        "fbp.toggle_gp_native_effect_settings",
        text="",
        icon="DOWNARROW_HLT" if expanded else "RIGHTARROW_THIN",
        emboss=False,
    )
    twist.effect_id = effect_id
    header.label(text=label, icon=icon)

    if int(duplicate_count or 0) > 1:
        duplicate = header.row(align=True)
        duplicate.alert = True
        duplicate.label(text=f"×{int(duplicate_count)}", icon="DUPLICATE")

    # Keep the Blender item name visible but secondary.  Frame By Plane tracks
    # the persistent effect ID, so user renames no longer break binding.
    item_name = _gp_native_item_name(item)
    if item_name and item_name != _gp_native_effect_name(effect_id):
        name = header.row(align=True)
        name.alignment = 'RIGHT'
        name.label(text=item_name)

    up_row = header.row(align=True)
    up_row.enabled = bool(index > 0)
    up = up_row.operator("fbp.move_gp_native_effect", text="", icon="TRIA_UP", emboss=False)
    up.effect_id = effect_id
    up.direction = -1
    down_row = header.row(align=True)
    down_row.enabled = bool(index >= 0 and index < total - 1)
    down = down_row.operator("fbp.move_gp_native_effect", text="", icon="TRIA_DOWN", emboss=False)
    down.effect_id = effect_id
    down.direction = 1
    reset_row = header.row(align=True)
    reset_row.enabled = _gp_native_effect_has_defaults(effect_id)
    reset = reset_row.operator("fbp.reset_gp_native_effect", text="", icon=ui_icon("action.reset"), emboss=False)
    reset.effect_id = effect_id
    _gp_draw_native_bool_icon(header, item, "show_viewport", icon_on="RESTRICT_VIEW_OFF", icon_off="RESTRICT_VIEW_ON")
    _gp_draw_native_bool_icon(header, item, "show_render", icon_on="RESTRICT_RENDER_OFF", icon_off="RESTRICT_RENDER_ON")
    remove = header.operator("fbp.toggle_gp_native_effect", text="", icon=ui_icon("action.delete"), emboss=False)
    remove.effect_id = effect_id

    if not expanded:
        return

    spec = _GP_NATIVE_EFFECT_UI_PROPS.get(str(effect_id or "").upper(), ())
    if not _gp_draw_native_effect_prop_spec(box, item, spec):
        fallback = box.row(align=True)
        fallback.enabled = False
        fallback.label(text="Native Settings in Blender", icon="BLANK1")


def fbp_gp_effect_backend_matrix():
    """Return primitive support records for every public effect.

    The matrix is safe for diagnostics and test runners: it contains no Blender
    RNA wrappers and distinguishes native, geometry-candidate and raster-only
    effects instead of presenting every unavailable item as equivalent.
    """
    try:
        from .effects_registry import FBP_EFFECT_METADATA, fbp_effect_definition
    except ImportError:
        return ()
    native_ids = {item[0] for item in GP_NATIVE_EFFECTS}
    records = []
    for effect_id, metadata in FBP_EFFECT_METADATA.items():
        category = str(metadata[0] if metadata else "")
        if category not in {"BASE", "2D", "3D"}:
            continue
        definition = fbp_effect_definition(effect_id)
        if bool(definition.get("hidden", False)) or bool(definition.get("layer_feature", False)):
            continue
        kind = str(definition.get("kind", "") or "")
        if effect_id in native_ids:
            tier = "NATIVE"
            reason = "Blender 5.2 native Grease Pencil backend"
        elif kind == "GEOMETRY" and not bool(definition.get("alpha_aware", False)):
            tier = "GEOMETRY_CANDIDATE"
            reason = "Requires a verified Grease Pencil Geometry Nodes equivalent"
        else:
            tier = "RASTER_ONLY"
            reason = "Depends on image pixels, alpha or shader sampling"
        records.append({
            "effect_id": str(effect_id),
            "label": str(definition.get("label", effect_id.replace("_", " ").title())),
            "category": category,
            "kind": kind,
            "tier": tier,
            "reason": reason,
        })
    return tuple(records)


def fbp_gp_effect_support_summary():
    records = fbp_gp_effect_backend_matrix()
    counts = {"NATIVE": 0, "GEOMETRY_CANDIDATE": 0, "RASTER_ONLY": 0}
    for record in records:
        tier = str(record.get("tier", "RASTER_ONLY"))
        counts[tier] = counts.get(tier, 0) + 1
    return {"total": len(records), **counts}


def _gp_unavailable_effects():
    """Return the cached public FBP effects without a native GP backend."""
    global _GP_UNAVAILABLE_EFFECTS_CACHE
    if _GP_UNAVAILABLE_EFFECTS_CACHE is not None:
        return _GP_UNAVAILABLE_EFFECTS_CACHE
    try:
        disabled = [
            (record["label"], record["effect_id"], record["tier"], record["reason"])
            for record in fbp_gp_effect_backend_matrix()
            if record["tier"] != "NATIVE"
        ]
        disabled.sort(key=lambda item: item[0].lower())
        _GP_UNAVAILABLE_EFFECTS_CACHE = tuple(disabled)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        _GP_UNAVAILABLE_EFFECTS_CACHE = ()
    return _GP_UNAVAILABLE_EFFECTS_CACHE


def _gp_draw_native_effect_button(grid, canvas, active_items, effect_id, label=None):
    definition = _gp_native_effect_definition(effect_id)
    if definition is None:
        return False
    _effect_id, default_label, icon, _backend, _native_type = definition
    supported = _gp_native_effect_supported(canvas, definition)
    active = active_items.get(_effect_id) is not None
    cell = grid.row(align=True)
    cell.enabled = bool(supported or active)
    op = cell.operator(
        "fbp.toggle_gp_native_effect",
        text=str(label or default_label),
        icon="CHECKBOX_HLT" if active else (icon if supported else "LOCKED"),
        depress=active,
    )
    op.effect_id = _effect_id
    return True


def _gp_draw_native_effect_library(layout, canvas, active_items, *, compact=False):
    """Draw available native GP effects grouped by artistic purpose."""
    drawn = set()
    columns = 2 if not compact else 1
    for group_label, group_icon, effect_ids in _GP_NATIVE_EFFECT_LIBRARY_GROUPS:
        group_ids = [effect_id for effect_id in effect_ids if _gp_native_effect_definition(effect_id) is not None]
        if not group_ids:
            continue
        supported_count = sum(1 for effect_id in group_ids if _gp_native_effect_supported(canvas, _gp_native_effect_definition(effect_id)))
        active_count = sum(1 for effect_id in group_ids if active_items.get(str(effect_id).upper()) is not None)
        label = group_label if supported_count else f"{group_label} — Unavailable"
        row = layout.row(align=True)
        row.enabled = bool(supported_count or active_count)
        row.label(text=label, icon=group_icon if supported_count or active_count else "LOCKED")
        grid = layout.grid_flow(row_major=True, columns=columns, even_columns=True, even_rows=False, align=True)
        for effect_id in group_ids:
            if _gp_draw_native_effect_button(grid, canvas, active_items, effect_id):
                drawn.add(str(effect_id).upper())
    # Safety net for definitions added later without being assigned to a group.
    ungrouped = [effect_id for effect_id in _GP_NATIVE_EFFECT_DEFINITIONS if effect_id not in drawn]
    if ungrouped:
        layout.label(text="Other", icon="MODIFIER")
        grid = layout.grid_flow(row_major=True, columns=columns, even_columns=True, even_rows=False, align=True)
        for effect_id in ungrouped:
            _gp_draw_native_effect_button(grid, canvas, active_items, effect_id)


def draw_gp_native_effects_ui(layout, context, canvas=None):
    """Draw Grease Pencil effects with the same stack-first rhythm as image planes."""
    canvas = canvas or _active_canvas(context)
    if not is_gp_drawing_canvas(canvas):
        layout.label(text="Grease Pencil masks do not own effects", icon="BLANK1")
        return

    active_items, ordered_active, backend_lengths, duplicate_counts = _gp_native_effect_stack_state(canvas)
    active_count = len(ordered_active)

    header = layout.row(align=True)
    header.label(text="Grease Pencil Effects", **ui_label_icon_kwargs("menu.gp_layer", fallback="menu.gp_layer"))
    header.label(text=f"{active_count} Active" if active_count else "No Active Effects", icon="CHECKMARK" if active_count else "BLANK1")
    unsupported_active = sum(
        1 for effect_id, _item, _backend, _index in ordered_active
        if not _gp_native_effect_supported(canvas, _gp_native_effect_definition(effect_id))
    )
    if unsupported_active:
        warn = header.row(align=True)
        warn.alert = True
        warn.label(text=f"{unsupported_active} Unsupported", icon="ERROR")
    duplicate_total = sum(max(0, int(count or 0) - 1) for count in duplicate_counts.values())
    if duplicate_total:
        repair = header.row(align=True)
        repair.alert = True
        repair.operator(
            "fbp.repair_gp_native_effect_duplicates",
            text=f"Repair {duplicate_total} Duplicate" + ("s" if duplicate_total != 1 else ""),
            icon="FILE_REFRESH",
        )

    stack_row = layout.row(align=False)
    stack_box = stack_row.box()
    stack_header = stack_box.row(align=True)
    stack_header.label(text="Effect Stack", icon="SHADERFX")
    stack_header.label(text="Native Grease Pencil backend", icon="CHECKMARK")

    if active_count:
        backend_labels = {"SHADER_FX": ("Shader Effects", "SHADING_RENDERED"), "MODIFIER": ("Modifiers", "MODIFIER")}
        last_backend = None
        for effect_id, item, backend, stack_index in ordered_active:
            if backend != last_backend:
                label, icon = backend_labels.get(backend, ("Effects", "SHADERFX"))
                stack_box.label(text=label, icon=icon)
                last_backend = backend
            _draw_gp_native_effect_settings(
                stack_box, effect_id, item,
                index=stack_index,
                total=backend_lengths.get(backend, 1),
                duplicate_count=duplicate_counts.get(effect_id, 1),
            )
    else:
        empty = stack_box.row(align=True)
        empty.enabled = False
        empty.label(text="No Grease Pencil effects", icon="BLANK1")

    controls = stack_row.column(align=True)
    try:
        from .layers import fbp_set_ui_units_x
        fbp_set_ui_units_x(controls, 1.25)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    controls.menu("FBP_MT_gp_native_effects", text="", icon="ADD")
    controls.separator()
    controls.prop(
        canvas, "fbp_gp_ui_show_effect_library",
        text="",
        toggle=True,
        icon="DOWNARROW_HLT" if bool(getattr(canvas, "fbp_gp_ui_show_effect_library", False)) else "RIGHTARROW_THIN",
    )

    show_library = bool(getattr(canvas, "fbp_gp_ui_show_effect_library", False)) or not active_count
    if show_library:
        library = layout.box()
        title = library.row(align=True)
        title.label(text="Add Grease Pencil Effect", icon="ADD")
        _gp_draw_native_effect_library(library, canvas, active_items)

    show_unavailable = bool(getattr(canvas, "fbp_gp_ui_show_unavailable_effects", False))
    unavailable = layout.box()
    unavailable.prop(
        canvas, "fbp_gp_ui_show_unavailable_effects",
        text="Effects without a Native Grease Pencil Backend",
        emboss=False,
        icon="DOWNARROW_HLT" if show_unavailable else "RIGHTARROW_THIN",
    )
    if show_unavailable:
        disabled_ids = _gp_unavailable_effects()
        if disabled_ids:
            grid = unavailable.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=True)
            for label, _effect_id, tier, reason in disabled_ids:
                row = grid.row(align=True)
                row.enabled = False
                icon = "MOD_NODES" if tier == "GEOMETRY_CANDIDATE" else "IMAGE_DATA"
                row.label(text=label, icon=icon)
                row.label(text="GN" if tier == "GEOMETRY_CANDIDATE" else "Raster")
                row.active = False
        else:
            unavailable.label(text="No image-only effects listed", icon="BLANK1")


class FBP_MT_GPNativeEffects(Menu):
    bl_idname = "FBP_MT_gp_native_effects"
    bl_label = "Grease Pencil Effects"

    def draw(self, context):
        canvas = _active_canvas(context)
        if not is_gp_drawing_canvas(canvas):
            self.layout.label(text="Select a Grease Pencil Drawing Plane", icon="BLANK1")
            return
        active_items, _ordered_active, _backend_lengths, _duplicate_counts = _gp_native_effect_stack_state(canvas)
        _gp_draw_native_effect_library(self.layout, canvas, active_items, compact=True)


class FBP_OT_ToggleGPNativeEffectSettings(Operator):
    bl_idname = "fbp.toggle_gp_native_effect_settings"
    bl_label = "Toggle Grease Pencil Effect Settings"
    bl_description = "Show or hide the inline Frame By Plane controls for this Grease Pencil effect"
    bl_options = {"INTERNAL"}

    effect_id: StringProperty(description='Internal stable effect identifier used by this button. Example: PIXELATE, SHADOW or GRADIENT_MASK.', name="Effect", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return is_gp_drawing_canvas(_active_canvas(context))

    def execute(self, context):
        canvas = _active_canvas(context)
        _definition, _collection, item, _index = _gp_native_effect_location(canvas, self.effect_id)
        if item is None:
            return {"CANCELLED"}
        _gp_set_native_effect_open(item, not _gp_native_effect_open(item, default=True))
        return {"FINISHED"}


class FBP_OT_RepairGPNativeEffectDuplicates(Operator):
    bl_idname = "fbp.repair_gp_native_effect_duplicates"
    bl_label = "Repair Duplicate Grease Pencil Effects"
    bl_description = "Remove duplicate Frame By Plane native effects while preserving the first instance and all artist effects"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        canvas = _active_canvas(context)
        if not is_gp_drawing_canvas(canvas):
            return False
        _active, _ordered, _lengths, duplicate_counts = _gp_native_effect_stack_state(canvas)
        return any(int(count or 0) > 1 for count in duplicate_counts.values())

    def execute(self, context):
        canvas = _active_canvas(context)
        removed = _gp_repair_native_effect_duplicates(canvas)
        if not removed:
            self.report({"INFO"}, "No duplicate Grease Pencil effects found")
            return {"CANCELLED"}
        try:
            canvas.update_tag()
        except FBP_DATA_ERRORS:
            pass
        self.report({"INFO"}, f"Removed {removed} duplicate Grease Pencil effect" + ("s" if removed != 1 else ""))
        return {"FINISHED"}


class FBP_OT_ResetGPNativeEffect(Operator):
    bl_idname = "fbp.reset_gp_native_effect"
    bl_label = "Reset Grease Pencil Effect"
    bl_description = "Restore Frame By Plane defaults for this native Grease Pencil effect"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(description='Internal stable effect identifier used by this button. Example: PIXELATE, SHADOW or GRADIENT_MASK.', name="Effect", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return is_gp_drawing_canvas(_active_canvas(context))

    def execute(self, context):
        canvas = _active_canvas(context)
        if not _gp_reset_native_effect(canvas, self.effect_id):
            self.report({"WARNING"}, "Grease Pencil effect has no resettable settings")
            return {"CANCELLED"}
        try:
            canvas.update_tag()
        except FBP_DATA_ERRORS:
            pass
        return {"FINISHED"}


class FBP_OT_MoveGPNativeEffect(Operator):
    bl_idname = "fbp.move_gp_native_effect"
    bl_label = "Move Grease Pencil Effect"
    bl_description = "Move this native Grease Pencil effect in its Blender stack"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(description='Internal stable effect identifier used by this button. Example: PIXELATE, SHADOW or GRADIENT_MASK.', name="Effect", default="", options={"SKIP_SAVE"})
    direction: IntProperty(description='Direction used by the action. Example: UP/DOWN for stack movement, or positive/negative for directional controls.', name="Direction", default=0, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return is_gp_drawing_canvas(_active_canvas(context))

    def execute(self, context):
        canvas = _active_canvas(context)
        if not _gp_move_native_effect(canvas, self.effect_id, self.direction):
            return {"CANCELLED"}
        try:
            canvas.update_tag()
        except FBP_DATA_ERRORS:
            pass
        return {"FINISHED"}


class FBP_OT_ToggleGPNativeEffect(Operator):
    bl_idname = "fbp.toggle_gp_native_effect"
    bl_label = "Toggle Grease Pencil Effect"
    bl_description = "Add or remove the Blender-native Grease Pencil equivalent of this effect"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(description='Internal stable effect identifier used by this button. Example: PIXELATE, SHADOW or GRADIENT_MASK.', name="Effect", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return is_gp_drawing_canvas(_active_canvas(context))

    def execute(self, context):
        canvas = _active_canvas(context)
        effect_id = str(self.effect_id or "").upper()
        existing = _gp_native_effect_instance(canvas, effect_id)
        if existing is not None:
            changed = _gp_remove_native_effect(canvas, effect_id)
        else:
            definition = _gp_native_effect_definition(effect_id)
            if not _gp_native_effect_supported(canvas, definition):
                self.report({"ERROR"}, "Grease Pencil effect unavailable in this Blender build")
                return {"CANCELLED"}
            changed = _gp_add_native_effect(canvas, effect_id) is not None
        if not changed:
            self.report({"ERROR"}, "Grease Pencil effect could not be updated")
            return {"CANCELLED"}
        try:
            canvas.update_tag()
        except FBP_DATA_ERRORS:
            pass
        return {"FINISHED"}


_GP_DRAWING_OWNER_ENUM_CACHE = ()


def _gp_drawing_owner_enum_items(_self, context):
    """Return stable enum items for Drawing Plane ownership.

    Blender keeps references to dynamic EnumProperty item strings internally; if
    the callback returns freshly-created strings without a module-level owner, the
    enum can later contain corrupted identifiers or miss the active selection.
    Keep the generated tuples alive and always include currently selected FBP
    roots before assigning an enum value in operator.invoke().
    """
    global _GP_DRAWING_OWNER_ENUM_CACHE
    items = [("__FREE__", "Free / Independent", "Create a standalone Grease Pencil Drawing Plane", "UNLINKED", 0)]
    seen = {"__FREE__"}
    scene = getattr(context, "scene", None) if context is not None else None
    candidates = []

    if scene is not None:
        try:
            from .layers import iter_scene_fbp_rigs
            candidates.extend(tuple(iter_scene_fbp_rigs(scene)))
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        try:
            candidates.extend(tuple(getattr(scene, "objects", ()) or ()))
        except FBP_DATA_ERRORS:
            pass

    try:
        candidates.extend(tuple(get_selected_fbp_roots(context)))
    except FBP_DATA_ERRORS:
        pass

    for rig in candidates:
        try:
            if not bool(getattr(rig, "is_fbp_control", False)):
                continue
            plane = getattr(rig, "fbp_plane_target", None)
            if plane is None:
                continue
            label = str(getattr(rig, "name", "Frame By Plane") or "Frame By Plane")
            if not label or label in seen:
                continue
            seen.add(label)
            items.append((label, label, "Link the Drawing Plane to this Frame By Plane layer", "LINKED", len(items)))
        except FBP_DATA_ERRORS:
            continue

    _GP_DRAWING_OWNER_ENUM_CACHE = tuple(items)
    return _GP_DRAWING_OWNER_ENUM_CACHE


def _gp_enum_owner_identifiers(context):
    try:
        return {str(item[0]) for item in _gp_drawing_owner_enum_items(None, context)}
    except FBP_DATA_ERRORS:
        return {"__FREE__"}


def _gp_safe_set_owner_enum(operator, context, value):
    candidate = str(value or "__FREE__")
    if candidate != "__FREE__" and candidate not in _gp_enum_owner_identifiers(context):
        candidate = "__FREE__"
    try:
        operator.owner_name = candidate
    except TypeError:
        candidate = "__FREE__"
        operator.owner_name = candidate
    return candidate


def _set_drawing_canvas_owner(canvas, rig, *, preserve_world=True):
    """Relink a Drawing Plane while preserving user-authored object data."""
    if not is_gp_drawing_canvas(canvas):
        return False
    if rig is not None and (
        not bool(getattr(rig, "is_fbp_control", False))
        or getattr(rig, "fbp_plane_target", None) is None
    ):
        return False
    old_owner = gp_canvas_owner(canvas)
    try:
        world = canvas.matrix_world.copy() if preserve_world else None
    except FBP_DATA_ERRORS:
        world = None

    if old_owner is not None and _same_datablock(getattr(old_owner, "fbp_gp_canvas", None), canvas):
        replacement = next(
            (item for item in gp_canvases_for_rig(old_owner) if not _same_datablock(item, canvas)),
            None,
        )
        try:
            old_owner.fbp_gp_canvas = replacement
        except FBP_DATA_ERRORS:
            pass

    try:
        canvas.fbp_gp_canvas_owner = rig
        canvas[KEY_OWNER_ID] = ensure_layer_identity(rig) if rig is not None else ""
        canvas[KEY_OWNER_NAME] = rig.name if rig is not None else ""
        if rig is None:
            canvas.fbp_gp_attachment_mode = "WORLD"
            canvas.fbp_gp_canvas_lock_transform = False
            if world is not None:
                canvas.parent = None
                canvas.matrix_parent_inverse = Matrix.Identity(4)
                canvas.matrix_world = world
            if hasattr(canvas, "fbp_gp_auto_sync_timing"):
                canvas.fbp_gp_auto_sync_timing = False
        else:
            primary = getattr(rig, "fbp_gp_canvas", None)
            if not is_gp_drawing_canvas(primary) or not _same_datablock(gp_canvas_owner(primary), rig):
                rig.fbp_gp_canvas = canvas
            canvas.fbp_gp_attachment_mode = "PLANE"
            canvas.fbp_gp_canvas_lock_transform = True
            sync_canvas_transform(canvas, scene=_scene_for_canvas(canvas))
        canvas.update_tag()
        _register_runtime_canvas(canvas)
        _invalidate_gp_owner_cache()
    except FBP_DATA_ERRORS:
        return False
    return True


def _select_canvas(context, canvas):
    if canvas is None:
        return False
    try:
        if str(getattr(context, "mode", "OBJECT")) != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except FBP_DATA_ERRORS:
        pass
    try:
        for obj in tuple(getattr(context, "selected_objects", ()) or ()):
            obj.select_set(False)
        if bool(getattr(canvas, "hide_select", False)):
            canvas.hide_select = False
        canvas.hide_set(False)
        canvas.select_set(True)
        context.view_layer.objects.active = canvas
        sync_gp_mask_interaction_state(context=context, scene=getattr(context, "scene", None), active=canvas)
        return True
    except FBP_DATA_ERRORS:
        return False


def _set_enum_if_available(owner, attr, value):
    """Set Blender RNA enum values defensively across GP API revisions."""
    try:
        if owner is None or not hasattr(owner, attr):
            return False
        prop = owner.bl_rna.properties.get(attr) if hasattr(owner, "bl_rna") else None
        if prop is not None and getattr(prop, "type", "") == "ENUM":
            identifiers = {str(item.identifier) for item in getattr(prop, "enum_items", ())}
            if value not in identifiers:
                return False
        setattr(owner, attr, value)
        return True
    except FBP_DATA_ERRORS:
        return False


def _active_tool_id(context) -> str:
    try:
        workspace = getattr(context, "workspace", None)
        if workspace is None:
            return ""
        mode = str(getattr(context, "mode", "") or "")
        tool = workspace.tools.from_space_view3d_mode(mode, create=False)
        return str(getattr(tool, "idname", "") or "")
    except FBP_DATA_ERRORS:
        return ""


def _apply_gp_draw_defaults(context=None) -> bool:
    """Apply Blender 5.2's native curve type to the active GP brush."""
    brush = _active_gp_brush(context)
    settings = getattr(brush, "gpencil_settings", None) if brush else None
    if brush is None:
        return False
    try:
        from .interface_preferences import fbp_get_addon_preferences
        prefs = fbp_get_addon_preferences(context)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        prefs = None
    changed = False
    try:
        if settings is not None and hasattr(settings, "curve_type"):
            requested = str(getattr(prefs, "default_gp_curve_type", "POLY") or "POLY")
            prop = settings.bl_rna.properties.get("curve_type") if hasattr(settings, "bl_rna") else None
            identifiers = {str(item.identifier) for item in getattr(prop, "enum_items", ())} if prop is not None else set()
            aliases = {
                "CATMULL_ROM": ("CATMULL_ROM", "CATMULLROM"),
                "BEZIER": ("BEZIER",),
                "NURBS": ("NURBS",),
                "POLY": ("POLY", "POLYLINE"),
            }
            resolved = next((item for item in aliases.get(requested, ("POLY",)) if not identifiers or item in identifiers), None)
            if resolved is not None and str(getattr(settings, "curve_type", "") or "") != resolved:
                settings.curve_type = resolved
                changed = True
        if settings is not None and hasattr(settings, "conversion_threshold"):
            threshold = max(0.0, float(getattr(prefs, "default_gp_curve_conversion_threshold", 0.001) or 0.0))
            if abs(float(getattr(settings, "conversion_threshold", 0.0) or 0.0) - threshold) > 1.0e-9:
                settings.conversion_threshold = threshold
                changed = True
    except FBP_DATA_ERRORS:
        return changed
    return changed


def _apply_gp_fill_defaults(context=None) -> bool:
    """Apply Blender 5.2 native Fill preferences to the active GP brush."""
    brush = _active_gp_brush(context)
    settings = getattr(brush, "gpencil_settings", None) if brush else None
    if settings is None:
        return False
    try:
        from .interface_preferences import fbp_get_addon_preferences
        prefs = fbp_get_addon_preferences(context)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        prefs = None
    changed = False
    try:
        solver = str(getattr(prefs, "default_gp_fill_solver", "DELAUNAY") or "DELAUNAY")
        if hasattr(settings, "fill_solver"):
            desired_solver = solver if solver in {"DELAUNAY", "PIXEL"} else "DELAUNAY"
            if str(getattr(settings, "fill_solver", "") or "") != desired_solver:
                settings.fill_solver = desired_solver
                changed = True
        if hasattr(settings, "fill_gap_factor"):
            desired_gap = max(0.0, min(1.0, float(
                getattr(prefs, "default_gp_fill_gap_factor", 0.4) or 0.0
            )))
            if abs(float(getattr(settings, "fill_gap_factor", 0.0) or 0.0) - desired_gap) > 1.0e-9:
                settings.fill_gap_factor = desired_gap
                changed = True
        if hasattr(settings, "fill_internal_gaps"):
            desired_internal = bool(getattr(prefs, "default_gp_fill_internal_gaps", True))
            if bool(getattr(settings, "fill_internal_gaps", False)) != desired_internal:
                settings.fill_internal_gaps = desired_internal
                changed = True
        if hasattr(settings, "use_auto_remove_fill_guides"):
            desired_guides = bool(getattr(prefs, "default_gp_fill_auto_remove_guides", True))
            if bool(getattr(settings, "use_auto_remove_fill_guides", False)) != desired_guides:
                settings.use_auto_remove_fill_guides = desired_guides
                changed = True
    except FBP_DATA_ERRORS:
        return changed
    return changed


def _set_gp_paint_tool(context, requested="PRESERVE") -> bool:
    """Select an explicitly requested native GP tool after Paint Mode starts.

    ``PRESERVE`` deliberately performs no tool or brush mutation. This keeps
    Blender in full control of temporary Ctrl erasing and of the last native
    Draw/Eraser brush selected by the artist.
    """
    requested = str(requested or "PRESERVE").upper()
    if requested == "PRESERVE":
        return True
    if requested not in {"DRAW", "FILL", "ERASE"}:
        return False
    if requested == "ERASE":
        candidates = ("builtin_brush.Erase", "builtin_brush.Eraser", "builtin.eraser")
    elif requested == "FILL":
        candidates = ("builtin_brush.Fill",)
    else:
        candidates = ("builtin_brush.Draw", "builtin.draw")
    for tool_id in candidates:
        try:
            if bpy.ops.wm.tool_set_by_id.poll():
                bpy.ops.wm.tool_set_by_id(name=tool_id)
            else:
                continue
            if requested == "FILL":
                _apply_gp_fill_defaults(context)
            elif requested == "DRAW":
                _apply_gp_draw_defaults(context)
            return True
        except FBP_DATA_ERRORS:
            continue
    return False

def _configure_gp_mask_draw_context(context, canvas):
    """Enter GP Paint with the authored drawing plane explicitly set to local XY.

    Frame By Plane cards and GP data are both authored in local XY (+Z normal).
    Keep that contract deterministic instead of inheriting a previously used
    Front/XZ placement mode from another Blender tool session.
    """
    if canvas is None:
        return False
    configured = False
    try:
        scene = getattr(context, "scene", None)
        tool_settings = getattr(scene, "tool_settings", None)
    except FBP_DATA_ERRORS:
        tool_settings = None
    for attr in (
        "gpencil_stroke_placement_view3d",
        "gpencil_stroke_placement_view2d",
        "gpencil_stroke_placement_image_editor",
        "gpencil_stroke_placement_sequencer_preview",
        "grease_pencil_stroke_placement_view3d",
    ):
        for value in ("ORIGIN", "VIEW", "SURFACE"):
            if _set_enum_if_available(tool_settings, attr, value):
                configured = True
                break
    for attr in (
        "gpencil_stroke_placement_view3d_plane",
        "gpencil_draw_plane",
        "grease_pencil_draw_plane",
        "annotation_stroke_placement_view3d",
    ):
        # OBJECT is the native local drawing plane. It follows the parented GP
        # canvas on vertical and arbitrarily rotated Frame By Plane cards.
        for value in ("OBJECT", "XY", "TOP", "VIEW", "FRONT", "XZ"):
            if _set_enum_if_available(tool_settings, attr, value):
                configured = True
                break
    # Blender 5.2 stores the actual GP drawing-plane selector on
    # ToolSettings.gpencil_sculpt.lock_axis. It has no Object enum; CURSOR is
    # the only native plane that can follow an arbitrarily rotated FBP card.
    try:
        gp_sculpt = getattr(tool_settings, "gpencil_sculpt", None)
        cursor = getattr(scene, "cursor", None)
        if gp_sculpt is not None and cursor is not None:
            scene_pointer = _canvas_pointer(scene)
            state = _GP_DRAW_CURSOR_STATE.get(scene_pointer)
            if state is None:
                state = {
                    "canvas_pointer": _canvas_pointer(canvas),
                    "matrix": cursor.matrix.copy(),
                    "paint_seen": False,
                    "created_at": time.monotonic(),
                }
                _GP_DRAW_CURSOR_STATE[scene_pointer] = state
            else:
                state["canvas_pointer"] = _canvas_pointer(canvas)
                state["created_at"] = time.monotonic()
            target_matrix = canvas.matrix_world.to_quaternion().to_matrix().to_4x4()
            target_matrix.translation = canvas.matrix_world.translation
            cursor.matrix = target_matrix
            if _set_enum_if_available(gp_sculpt, "lock_axis", "CURSOR"):
                configured = True
    except FBP_DATA_ERRORS:
        pass
    try:
        canvas["fbp_gp_draw_setup"] = "ORIGIN_XY_PLANE"
    except FBP_DATA_ERRORS:
        pass
    return configured


def _configure_gp_active_tool_after_mode(context, canvas, *, tool="PRESERVE"):
    """Apply only explicit native tool requests after GP Paint Mode is active.

    The normal entry path preserves Blender's current tool and brush. In
    particular, Frame By Plane never chooses or restores the temporary Ctrl
    eraser. Brush-component metadata is updated only for an explicitly selected
    Draw or Fill tool, never for Erase or Preserve.
    """
    requested_tool = str(tool or "PRESERVE").upper()
    if requested_tool == "PRESERVE":
        return True
    if not _set_gp_paint_tool(context, requested=requested_tool):
        return False
    if requested_tool not in {"DRAW", "FILL"}:
        return True
    try:
        previous_mode = _normalize_gp_stroke_type(
            canvas.get("fbp_gp_mask_active_brush_mode", "STROKE"),
            "STROKE",
        )
        committed_curve_count = _gp_mask_curve_count(
            canvas,
            getattr(context, "scene", None),
            rebuild_index=True,
        )
        _sync_gp_mask_authored_curve_state(
            canvas,
            scene=getattr(context, "scene", None),
            context=context,
            observed_weight=(committed_curve_count, 0),
            brush_mode_override=previous_mode,
            rebuild_index=True,
        )
        requested_mode = str(getattr(canvas, "fbp_gp_mask_source", "AUTO") or "AUTO").upper()
        _set_active_gp_brush_stroke_type(context, requested_mode)
        active_mode = requested_mode if requested_mode in {"STROKE", "FILL", "BOTH"} else previous_mode
        _idprop_set_if_changed(canvas, "fbp_gp_mask_active_brush_mode", active_mode)
    except FBP_DATA_ERRORS:
        pass
    return True


def _restore_gp_draw_cursor_if_needed(scene=None, *, force=False):
    """Restore the cursor saved for an FBP GP Draw session."""
    target_scene = scene or getattr(bpy.context, "scene", None)
    scene_pointer = _canvas_pointer(target_scene)
    state = _GP_DRAW_CURSOR_STATE.get(scene_pointer)
    if state is None or target_scene is None:
        return False
    canvas = _gp_canvas_by_pointer(int(state.get("canvas_pointer", 0) or 0))
    active_modes = _gp_canvas_active_modes(canvas) if is_gp_canvas(canvas) else ()
    if "PAINT_GREASE_PENCIL" in active_modes and not force:
        state["paint_seen"] = True
        return False
    if not force and not bool(state.get("paint_seen", False)):
        elapsed = time.monotonic() - float(state.get("created_at", 0.0) or 0.0)
        if elapsed < 1.0:
            return False
    try:
        target_scene.cursor.matrix = state["matrix"]
    except FBP_DATA_ERRORS:
        pass
    _GP_DRAW_CURSOR_STATE.pop(scene_pointer, None)
    return True


def _restore_all_gp_draw_cursors():
    restored = False
    for scene in tuple(getattr(bpy.data, "scenes", ()) or ()):
        restored = bool(_restore_gp_draw_cursor_if_needed(scene, force=True) or restored)
    _GP_DRAW_CURSOR_STATE.clear()
    return restored


def _gp_mask_live_point_count(weight):
    try:
        return max(0, int(weight[1] or 0))
    except (TypeError, ValueError, IndexError):
        return 0


def _gp_mask_live_immediate_refresh(weight):
    """Keep small masks responsive and coalesce large masks while drawing."""
    return _gp_mask_live_point_count(weight) < _GP_MASK_LIVE_HEAVY_POINT_THRESHOLD


def _gp_mask_live_poll_interval(weight, stable_ticks):
    if stable_ticks >= 8:
        interval = 0.18
    elif stable_ticks >= 3:
        interval = 0.12
    else:
        interval = 0.075
    point_count = _gp_mask_live_point_count(weight)
    if point_count >= _GP_MASK_LIVE_VERY_HEAVY_POINT_THRESHOLD:
        return max(interval, 0.18)
    if point_count >= _GP_MASK_LIVE_HEAVY_POINT_THRESHOLD:
        return max(interval, 0.12)
    return interval


def _start_gp_mask_live_poll(canvas, scene=None):
    """Poll active GP paint sessions with one persistent lightweight probe."""
    if not is_gp_canvas(canvas):
        return False
    pointer = _canvas_pointer(canvas)
    if not pointer:
        return False
    target_scene = _scene_for_canvas(canvas, scene)
    scene_pointer = _canvas_pointer(target_scene)
    key = (pointer, scene_pointer)
    task_name = f"grease_pencil.mask_live_poll:{pointer}:{scene_pointer}"
    now = time.monotonic()

    # Depsgraph can publish several updates for one brush sample. Keep the
    # existing closure/state instead of replacing it with a fresh poll on every
    # update; only extend its idle lifetime.
    if key in _GP_MASK_LIVE_POLL_KEYS and scheduled_task_pending(task_name):
        _GP_MASK_LIVE_POLL_KEYS[key] = now
        return True

    _GP_MASK_LIVE_POLL_KEYS[key] = now
    stable_ticks = 0
    last_brush_check = 0.0
    brush_signature = None
    last_weight = None

    def _poll():
        nonlocal stable_ticks, last_brush_check, brush_signature, last_weight
        current = _gp_canvas_by_pointer(pointer)
        if not is_gp_canvas(current):
            _GP_MASK_LIVE_POLL_KEYS.pop(key, None)
            _GP_MASK_LIVE_POLL_SIGNATURES.pop(key, None)
            return None
        refresh_scene = _scene_by_pointer(scene_pointer) or _scene_for_canvas(current, None)
        if not _gp_live_editing(current):
            _pause_gp_mask_mode_transition(
                current, refresh_scene, seconds=_GP_MASK_MODE_TRANSITION_SECONDS
            )
            _GP_MASK_LIVE_POLL_KEYS.pop(key, None)
            _GP_MASK_LIVE_POLL_SIGNATURES.pop(key, None)
            return None
        has_mask = bool(
            is_gp_mask_canvas(current)
            or getattr(current, "fbp_gp_mask_image", None) is not None
            or gp_mask_bindings(current)
        )
        if has_mask and _gp_mask_live_refresh_enabled(current):
            try:
                signature, weight = _canvas_stroke_count_signature(
                    current,
                    refresh_scene,
                    sync_authoring=False,
                    detail=False,
                )
            except FBP_DATA_ERRORS:
                _GP_MASK_LIVE_POLL_KEYS.pop(key, None)
                _GP_MASK_LIVE_POLL_SIGNATURES.pop(key, None)
                return None

            weight_changed = last_weight is None or tuple(weight) != tuple(last_weight)
            authored_state_changed = False
            if weight_changed:
                authored_state_changed = _sync_gp_mask_authored_curve_state(
                    current, scene=refresh_scene, observed_weight=weight
                )
                last_weight = tuple(weight)

            current_time = time.monotonic()
            if brush_signature is None or current_time - last_brush_check >= 0.25:
                brush_signature = _active_gp_brush_signature()
                last_brush_check = current_time
            signature = (signature, brush_signature)
            previous = _GP_MASK_LIVE_POLL_SIGNATURES.get(key)
            _GP_MASK_LIVE_POLL_SIGNATURES[key] = signature
            if previous is None:
                _GP_MASK_LIVE_POLL_KEYS[key] = current_time
                has_geometry = bool(
                    int(weight[0] or 0) > 0 or int(weight[1] or 0) > 0
                )
                if authored_state_changed or has_geometry:
                    stable_ticks = 0
                    mark_gp_mask_dirty(
                        current,
                        schedule=True,
                        geometry=True,
                        scene=refresh_scene,
                        immediate=_gp_mask_live_immediate_refresh(weight),
                        sync_registry=False,
                    )
            elif signature != previous or authored_state_changed:
                stable_ticks = 0
                _GP_MASK_LIVE_POLL_KEYS[key] = current_time
                mark_gp_mask_dirty(
                    current,
                    schedule=True,
                    geometry=True,
                    scene=refresh_scene,
                    immediate=_gp_mask_live_immediate_refresh(weight),
                    sync_registry=False,
                )
            else:
                stable_ticks = min(1000, stable_ticks + 1)
                last_activity = float(
                    _GP_MASK_LIVE_POLL_KEYS.get(key, current_time) or current_time
                )
                if current_time - last_activity >= _GP_MASK_LIVE_POLL_IDLE_STOP_SECONDS:
                    _GP_MASK_LIVE_POLL_KEYS.pop(key, None)
                    _GP_MASK_LIVE_POLL_SIGNATURES.pop(key, None)
                    return None
        return _gp_mask_live_poll_interval(last_weight, stable_ticks)

    scheduled = bool(schedule_once(task_name, _poll, first_interval=0.05))
    if not scheduled and not scheduled_task_pending(task_name):
        _GP_MASK_LIVE_POLL_KEYS.pop(key, None)
        _GP_MASK_LIVE_POLL_SIGNATURES.pop(key, None)
    return scheduled


def _enter_gp_draw_mode(context, canvas, *, tool="PRESERVE"):
    if canvas is None:
        return False
    _ensure_gp_layer(canvas)
    _ensure_gp_material(canvas)
    _ensure_gp_current_keyframe(canvas, context)
    if not _select_canvas(context, canvas):
        return False
    _configure_gp_mask_draw_context(context, canvas)
    # Enter native Paint Mode before touching an explicitly requested tool.
    # Calling tool_set_by_id while still in Object/Edit Mode can leave Blender
    # without a valid Grease Pencil brush for temporary Ctrl erasing.
    try:
        bpy.ops.object.mode_set(mode="PAINT_GREASE_PENCIL")
        _configure_gp_active_tool_after_mode(context, canvas, tool=tool)
        _start_gp_mask_live_poll(canvas, scene=getattr(context, "scene", None))
        return True
    except FBP_DATA_ERRORS:
        return False


class FBP_OT_AddGreasePencilCanvas(Operator):
    bl_idname = "fbp.add_grease_pencil_canvas"
    bl_label = "Grease Pencil"
    bl_description = "Create a Grease Pencil Drawing Plane, linked to a Frame By Plane layer or free in world space"
    bl_options = {"REGISTER", "UNDO"}

    canvas_name: StringProperty(
        name="Name",
        description="Name of the Grease Pencil Drawing Plane",
        default="Grease Pencil",
    )
    owner_name: EnumProperty(
        name="Link to Plane",
        description="Choose a Frame By Plane layer or create the Grease Pencil independently",
        items=_gp_drawing_owner_enum_items,
    )
    placement_rig_name: StringProperty(
        name="Placement Reference",
        description="Internal selected Frame By Plane layer used to place an unlinked Drawing Plane at creation time",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    distance: FloatProperty(
        name="Distance",
        description="Signed offset from the linked image plane; negative places the drawing behind it",
        default=0.003, soft_min=-1.0, soft_max=1.0, precision=4,
    )
    offset_x: FloatProperty(description='Offset value for positioning the effect, mask, helper or generated element relative to its default placement.', name="Offset X", default=0.0, soft_min=-2.0, soft_max=2.0)
    offset_y: FloatProperty(description='Offset value for positioning the effect, mask, helper or generated element relative to its default placement.', name="Offset Y", default=0.0, soft_min=-2.0, soft_max=2.0)
    canvas_scale: FloatProperty(description='Size control for the generated result. Higher values increase visual coverage and may increase viewport cost.', name="Scale", default=1.0, min=0.001, soft_max=4.0)
    match_keyframes: BoolProperty(
        name="Match Keyframes with Plane",
        description="Create empty Grease Pencil drawings at every source image exposure",
        default=True,
    )
    auto_sync_timing: BoolProperty(
        name="Keep Timing Synced",
        description="Automatically update Grease Pencil exposure timing when the linked plane timing changes",
        default=False,
    )
    enter_draw_mode: BoolProperty(
        name="Start Drawing",
        description="Open Blender Grease Pencil Draw Mode after creation",
        default=False,
    )

    def invoke(self, context, _event):
        roots = tuple(get_selected_fbp_roots(context))
        if not roots:
            try:
                resolved = fbp_resolve_rig_from_any_object(getattr(context, "object", None), context)
                roots = (resolved,) if resolved is not None else ()
            except FBP_DATA_ERRORS:
                roots = ()
        reference = roots[0] if roots else None
        self.placement_rig_name = str(getattr(reference, "name", "") or "")
        # UNLINKED is the default: the Drawing Plane behaves as a new stack
        # layer, not as a helper bound to the selected image plane.  The
        # selected layer is still used as the initial placement reference.
        _gp_safe_set_owner_enum(self, context, "__FREE__")
        if reference is not None:
            self.canvas_name = _gp_drawing_name_for_layer(reference)
        else:
            self.canvas_name = "GP - Layer"
        return context.window_manager.invoke_props_dialog(
            self,
            width=580,
            title="Create Grease Pencil Drawing",
            confirm_text="Create Drawing",
        )

    def draw(self, context):
        layout = configure_layout(self.layout)

        source = layout.box()
        configure_layout(source)
        section_header(source, "Layer", icon="GREASEPENCIL")
        row = adaptive_row(source, context, align=False)
        row.prop(self, "canvas_name", text="Name")
        row.prop(self, "owner_name", text="")

        section_gap(layout, 0.2)
        linked = self.owner_name != "__FREE__"
        transform = layout.box()
        configure_layout(transform)
        section_header(
            transform,
            "Plane Alignment" if linked else "World Placement",
            icon="LINKED" if linked else "UNLINKED",
        )
        distance = transform.row(align=False)
        distance.enabled = linked
        distance.prop(self, "distance", text="Distance")
        offsets = adaptive_row(transform, context, align=False)
        offsets.enabled = linked
        offsets.prop(self, "offset_x", text="X")
        offsets.prop(self, "offset_y", text="Y")
        transform.prop(self, "canvas_scale", text="Scale")

        section_gap(layout, 0.2)
        timing_box = layout.box()
        configure_layout(timing_box)
        section_header(timing_box, "Timing and Start", icon="TIME")
        timing = adaptive_row(timing_box, context, align=False)
        timing.enabled = linked
        timing.prop(self, "match_keyframes", text="Match Keys", icon="KEYFRAME_HLT", toggle=True)
        timing.prop(self, "auto_sync_timing", text="Sync Timing", icon="FILE_REFRESH", toggle=True)
        timing.prop(self, "enter_draw_mode", text="Start Drawing", icon="GREASEPENCIL", toggle=True)

    def execute(self, context):
        rig = None if self.owner_name == "__FREE__" else bpy.data.objects.get(self.owner_name)
        if rig is not None and not bool(getattr(rig, "is_fbp_control", False)):
            self.report({"ERROR"}, "The selected Frame By Plane layer is no longer available")
            return {"CANCELLED"}
        placement_rig = None
        if rig is None:
            placement_rig = bpy.data.objects.get(str(getattr(self, "placement_rig_name", "") or ""))
            if placement_rig is not None and not bool(getattr(placement_rig, "is_fbp_control", False)):
                placement_rig = None
        canvas, created = _new_canvas(
            context,
            rig,
            kind="DRAWING",
            name=str(self.canvas_name or "Grease Pencil"),
            reuse_existing=False,
        )
        if canvas is None:
            self.report({"ERROR"}, "Could not create the Grease Pencil Drawing Plane")
            return {"CANCELLED"}
        try:
            canvas.fbp_gp_attachment_mode = "PLANE" if rig is not None else "WORLD"
            canvas.fbp_gp_canvas_distance = float(self.distance)
            canvas.fbp_gp_canvas_offset_x = float(self.offset_x)
            canvas.fbp_gp_canvas_offset_y = float(self.offset_y)
            canvas.fbp_gp_canvas_scale = float(self.canvas_scale)
            if hasattr(canvas, "fbp_gp_auto_sync_timing"):
                canvas.fbp_gp_auto_sync_timing = bool(self.auto_sync_timing and rig is not None)
            sync_canvas_transform(canvas, scene=getattr(context, "scene", None))
        except FBP_DATA_ERRORS:
            pass
        if rig is None and placement_rig is not None:
            _place_free_canvas_above_reference(context, canvas, placement_rig)
        created_frames = 0
        if rig is not None and bool(self.match_keyframes):
            try:
                from .grease_pencil_workflow import create_missing_drawings
                created_frames = int(create_missing_drawings(canvas, duplicate_previous=False).get("created", 0))
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                fbp_warn("Could not match Grease Pencil keyframes to the source plane", exc)
        _ensure_gp_current_keyframe(canvas, context)
        _select_canvas(context, canvas)
        _refresh_layer_tree(context)
        if bool(self.enter_draw_mode):
            _enter_gp_draw_mode(context, canvas)
        detail = f" · {created_frames} empty keyframe{'s' if created_frames != 1 else ''}" if created_frames else ""
        self.report({"INFO"}, ("Created" if created else "Selected") + f" {canvas.name}{detail}")
        return {"FINISHED"}


class FBP_OT_LinkGreasePencilCanvas(Operator):
    bl_idname = "fbp.link_grease_pencil_canvas"
    bl_label = "Link Grease Pencil"
    bl_description = "Link this Drawing Plane to another Frame By Plane layer or make it independent"
    bl_options = {"REGISTER", "UNDO"}

    canvas_name: StringProperty(description='Display name stored by Frame By Plane. Renaming keeps internal identifiers and generated links intact.', name="Canvas", default="", options={"SKIP_SAVE"})
    owner_name: EnumProperty(
        name="Link to Plane",
        description="Choose the Frame By Plane layer followed by this Drawing Plane",
        items=_gp_drawing_owner_enum_items,
    )
    match_keyframes: BoolProperty(
        name="Match Empty Keyframes",
        description="Create missing blank drawings for the destination plane exposures",
        default=True,
    )
    auto_sync_timing: BoolProperty(
        name="Keep Timing Synced",
        description="Continue matching the destination plane timing after it changes",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        if is_gp_drawing_canvas(_active_canvas(context)):
            return True
        scene = getattr(context, "scene", None) if context is not None else None
        try:
            return scene_has_gp_canvas(scene, kind="DRAWING")
        except FBP_DATA_ERRORS:
            return False

    def invoke(self, context, _event):
        canvas = bpy.data.objects.get(self.canvas_name) if self.canvas_name else _active_canvas(context)
        if not is_gp_drawing_canvas(canvas):
            return {"CANCELLED"}
        self.canvas_name = canvas.name
        owner = gp_canvas_owner(canvas)
        _gp_safe_set_owner_enum(self, context, owner.name if owner is not None else "__FREE__")
        self.auto_sync_timing = bool(getattr(canvas, "fbp_gp_auto_sync_timing", False))
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, _context):
        layout = configure_layout(self.layout)
        layout.prop(self, "owner_name")
        linked = self.owner_name != "__FREE__"
        timing = layout.box()
        timing.enabled = linked
        timing.label(text="Drawing Timing", icon="KEYFRAME")
        row = timing.row(align=True)
        row.prop(self, "match_keyframes")
        row.prop(self, "auto_sync_timing", text="Auto Sync")

    def execute(self, context):
        canvas = bpy.data.objects.get(self.canvas_name) if self.canvas_name else _active_canvas(context)
        if not is_gp_drawing_canvas(canvas):
            self.report({"ERROR"}, "The Grease Pencil Drawing Plane is no longer available")
            return {"CANCELLED"}
        rig = None if self.owner_name == "__FREE__" else bpy.data.objects.get(self.owner_name)
        if rig is not None and (
            not bool(getattr(rig, "is_fbp_control", False))
            or getattr(rig, "fbp_plane_target", None) is None
        ):
            self.report({"ERROR"}, "The destination Frame By Plane layer is no longer available")
            return {"CANCELLED"}
        old_owner = gp_canvas_owner(canvas)
        if not _set_drawing_canvas_owner(canvas, rig, preserve_world=True):
            self.report({"ERROR"}, "Could not update the Grease Pencil link")
            return {"CANCELLED"}

        created_frames = 0
        if rig is not None:
            try:
                canvas.fbp_gp_auto_sync_timing = bool(self.auto_sync_timing)
                if bool(self.match_keyframes):
                    from .grease_pencil_workflow import create_missing_drawings
                    created_frames = int(create_missing_drawings(canvas, duplicate_previous=False).get("created", 0))
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                fbp_warn("Could not synchronize the relinked Grease Pencil timing", exc)
        _refresh_layer_tree(context)
        destination = rig.name if rig is not None else "world space"
        changed_owner = not _same_datablock(old_owner, rig)
        detail = f" · {created_frames} empty keyframe{'s' if created_frames != 1 else ''}" if created_frames else ""
        self.report(
            {"INFO"},
            ("Relinked" if changed_owner else "Updated") + f" {canvas.name} to {destination}{detail}",
        )
        return {"FINISHED"}


class FBP_OT_SelectGreasePencilCanvas(Operator):
    bl_idname = "fbp.select_grease_pencil_canvas"
    bl_label = "Select Grease Pencil Canvas"
    bl_description = 'Select this Grease Pencil canvas and make it active in the 3D Viewport'
    bl_options = {"REGISTER", "UNDO"}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', name="Layer", default="", options={"SKIP_SAVE"})
    canvas_name: StringProperty(description='Display name stored by Frame By Plane. Renaming keeps internal identifiers and generated links intact.', name="Canvas", default="", options={"SKIP_SAVE"})
    tool: EnumProperty(
        name="Tool",
        description="Preserve Blender's active tool or explicitly choose Fill/Erase",
        items=(
            ("PRESERVE", "Current Tool", "Enter Paint Mode without changing Blender's active Grease Pencil tool or Ctrl eraser"),
            ("DRAW", "Draw", "Explicitly select Blender's native Draw tool"),
            ("FILL", "Fill", "Use Blender 5.2's native Grease Pencil Fill tool"),
            ("ERASE", "Erase", "Use Blender's native Grease Pencil eraser"),
        ),
        default="PRESERVE",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        canvas = bpy.data.objects.get(self.canvas_name) if self.canvas_name else None
        if not is_gp_canvas(canvas):
            rig = bpy.data.objects.get(self.rig_name) if self.rig_name else None
            if rig is None:
                roots = get_selected_fbp_roots(context)
                rig = roots[0] if roots else None
            canvas = gp_canvas_for_rig(rig)
        if canvas is None:
            return {"CANCELLED"}
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except FBP_DATA_ERRORS:
            pass
        if not _select_canvas(context, canvas):
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_EnterGreasePencilDraw(Operator):
    bl_idname = "fbp.enter_grease_pencil_draw"
    bl_label = "Draw on Canvas"
    bl_description = "Select the linked canvas and enter Blender's native Grease Pencil Draw Mode"
    bl_options = {"REGISTER"}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', name="Layer", default="", options={"SKIP_SAVE"})
    canvas_name: StringProperty(description='Display name stored by Frame By Plane. Renaming keeps internal identifiers and generated links intact.', name="Canvas", default="", options={"SKIP_SAVE"})
    tool: EnumProperty(
        name="Tool",
        description="Preserve Blender's active tool or explicitly choose Fill/Erase",
        items=(
            ("PRESERVE", "Current Tool", "Enter Paint Mode without changing Blender's active Grease Pencil tool or Ctrl eraser"),
            ("DRAW", "Draw", "Explicitly select Blender's native Draw tool"),
            ("FILL", "Fill", "Use Blender 5.2's native Grease Pencil Fill tool"),
            ("ERASE", "Erase", "Use Blender's native Grease Pencil eraser"),
        ),
        default="DRAW",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        canvas = bpy.data.objects.get(self.canvas_name) if self.canvas_name else None
        if not is_gp_canvas(canvas):
            rig = bpy.data.objects.get(self.rig_name) if self.rig_name else None
            canvas = gp_canvas_for_rig(rig) if rig else _active_canvas(context)
        if canvas is None:
            return {"CANCELLED"}
        if not _enter_gp_draw_mode(context, canvas, tool=self.tool):
            self.report({"ERROR"}, "Could not enter Grease Pencil Draw Mode")
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_RefreshGreasePencilMask(Operator):
    bl_idname = "fbp.refresh_grease_pencil_mask"
    bl_label = "Refresh Grease Pencil Mask"
    bl_description = "Rasterize the current Grease Pencil frame into the mask image now"
    bl_options = {"REGISTER", "UNDO"}

    canvas_name: StringProperty(description='Display name stored by Frame By Plane. Renaming keeps internal identifiers and generated links intact.', name="Canvas", default="", options={"SKIP_SAVE"})
    force: BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Force", default=True, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None or bool(get_selected_fbp_roots(context))

    def execute(self, context):
        canvas = _operator_canvas(context, self.canvas_name)
        image, changed = refresh_gp_mask(canvas, force=bool(self.force), scene=getattr(context, "scene", None))
        if image is None:
            self.report({"ERROR"}, "No valid Grease Pencil canvas or owner layer")
            return {"CANCELLED"}
        self.report({"INFO"}, "Grease Pencil mask refreshed" if changed else "Grease Pencil mask is already current")
        return {"FINISHED"}


class FBP_OT_BakeGreasePencilMask(Operator):
    bl_idname = "fbp.bake_grease_pencil_mask"
    bl_label = "Bake Grease Pencil Mask"
    bl_description = "Pack the generated Grease Pencil mask image into the .blend file without disabling live updates"
    bl_options = {"REGISTER", "UNDO"}

    canvas_name: StringProperty(description='Display name stored by Frame By Plane. Renaming keeps internal identifiers and generated links intact.', name="Canvas", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None or bool(get_selected_fbp_roots(context))

    def execute(self, context):
        canvas = _operator_canvas(context, self.canvas_name)
        image, _changed = refresh_gp_mask(canvas, force=True, scene=getattr(context, "scene", None))
        if image is None:
            return {"CANCELLED"}
        try:
            canvas[KEY_MASK_BAKED] = True
            image.pack()
        except FBP_DATA_ERRORS:
            pass
        self.report({"INFO"}, "Grease Pencil mask baked into the .blend file")
        return {"FINISHED"}


class FBP_OT_UseGreasePencilAsMask(Operator):
    bl_idname = "fbp.use_grease_pencil_as_mask"
    bl_label = "Use Grease Pencil as Mask"
    bl_description = "Apply the linked Grease Pencil canvas through Frame By Plane's non-destructive raster mask effect"
    bl_options = {"REGISTER", "UNDO"}

    canvas_name: StringProperty(description='Display name stored by Frame By Plane. Renaming keeps internal identifiers and generated links intact.', name="Canvas", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None or bool(get_selected_fbp_roots(context))

    def execute(self, context):
        canvas = _operator_canvas(context, self.canvas_name)
        owner = gp_canvas_owner(canvas)
        if owner is None:
            return {"CANCELLED"}
        image, _changed = refresh_gp_mask(canvas, force=True, scene=getattr(context, "scene", None))
        if image is None:
            return {"CANCELLED"}
        selected = list(get_selected_fbp_roots(context))
        targets = []
        for rig in selected or [owner]:
            if rig not in targets:
                targets.append(rig)
        if owner not in targets and is_gp_canvas(getattr(context, "object", None)):
            targets.insert(0, owner)
        applied = 0
        try:
            from .geometry_nodes import fbp_add_effect, fbp_effect_is_active, fbp_set_effect_mask_target
            for rig in targets:
                effect_id = gp_mask_effect_for_target(rig, "LAYER")
                if effect_id is None:
                    continue
                if not fbp_effect_is_active(rig, effect_id):
                    if not fbp_add_effect(rig, effect_id, select_object_mask_helper=False):
                        continue
                slot = gp_mask_slot_contract(effect_id)
                setattr(rig, slot["canvas"], canvas)
                setattr(rig, slot["image"], image)
                setattr(rig, slot["source_type"], "GREASE_PENCIL")
                setattr(rig, slot["path"], "")
                fbp_set_effect_mask_target(rig, effect_id, "LAYER")
                _apply_canvas_mask_to_binding(canvas, rig, effect_id, slot)
                applied += 1
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            self.report({"ERROR"}, f"Could not assign the Grease Pencil mask: {exc}")
            return {"CANCELLED"}
        if not applied:
            self.report({"ERROR"}, "Could not add the raster mask effect to the selected layers")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Grease Pencil mask assigned to {applied} layer{'s' if applied != 1 else ''}")
        return {"FINISHED"}


class FBP_OT_AddGreasePencilMask(Operator):
    bl_idname = "fbp.add_grease_pencil_mask"
    bl_label = "Grease Pencil Mask"
    bl_description = "Create or reuse a Grease Pencil layer, show it at 50% viewport opacity and assign it as a mask"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(get_selected_fbp_roots(context))

    def execute(self, context):
        targets = list(get_selected_fbp_roots(context))
        if not targets:
            return {"CANCELLED"}
        applied = 0
        first_canvas = None
        for rig in targets:
            canvas, _created = _create_mask_canvas(rig, context)
            if canvas is None:
                continue
            fbp_set_rna_property_silent(canvas, "fbp_gp_canvas_visible", True)
            fbp_set_rna_property_silent(canvas, "fbp_gp_canvas_opacity", 0.5)
            fbp_set_rna_property_silent(canvas, "fbp_gp_mask_invert", False)
            fbp_set_rna_property_silent(canvas, "fbp_gp_mask_opacity", 1.0)
            fbp_set_rna_property_silent(canvas, "fbp_gp_mask_quality", DEFAULT_GP_MASK_QUALITY)
            fbp_set_rna_property_silent(canvas, "fbp_gp_mask_preview_quality", DEFAULT_GP_MASK_PREVIEW_QUALITY)
            fbp_set_rna_property_silent(canvas, "fbp_gp_mask_feather", 0.0)
            fbp_set_rna_property_silent(canvas, "fbp_gp_mask_expand", DEFAULT_GP_MASK_EXPAND)
            fbp_set_rna_property_silent(canvas, "fbp_gp_mask_stroke_width", DEFAULT_GP_MASK_STROKE_WIDTH)
            _apply_canvas_opacity(canvas)
            _ensure_gp_current_keyframe(canvas, context)
            image, _changed = refresh_gp_mask(canvas, force=True, scene=getattr(context, "scene", None))
            if image is None:
                continue
            try:
                from .geometry_nodes import fbp_add_effect, fbp_effect_is_active, fbp_set_effect_mask_target
                effect_id = gp_mask_effect_for_target(rig, "LAYER")
                if effect_id is None:
                    continue
                if not fbp_effect_is_active(rig, effect_id) and not fbp_add_effect(rig, effect_id, select_object_mask_helper=False):
                    continue
                slot = gp_mask_slot_contract(effect_id)
                setattr(rig, slot["canvas"], canvas)
                setattr(rig, slot["image"], image)
                setattr(rig, slot["source_type"], "GREASE_PENCIL")
                setattr(rig, slot["path"], "")
                fbp_set_effect_mask_target(rig, effect_id, "LAYER")
                _apply_canvas_mask_to_binding(canvas, rig, effect_id, slot)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
            first_canvas = first_canvas or canvas
            applied += 1
        _refresh_layer_tree(context)
        if not applied:
            self.report({"ERROR"}, "Could not create a Grease Pencil mask")
            return {"CANCELLED"}
        if first_canvas is not None:
            _enter_gp_draw_mode(context, first_canvas)
        self.report({"INFO"}, f"Grease Pencil mask ready on {applied} layer{'s' if applied != 1 else ''}")
        return {"FINISHED"}


class FBP_OT_AssignGreasePencilMaskToEffect(Operator):
    bl_idname = "fbp.assign_grease_pencil_mask_to_effect"
    bl_label = "Assign Grease Pencil Mask to Effect"
    bl_description = "Use a Grease Pencil matte on one concrete image-effect instance"
    bl_options = {"REGISTER", "UNDO"}

    target_effect_id: StringProperty(name="Effect", default="", options={"SKIP_SAVE"})
    target_instance_id: StringProperty(name="Instance", default="", options={"SKIP_SAVE"})
    canvas_name: EnumProperty(name="Canvas", items=_gp_canvas_enum_items)
    target_payload: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(get_selected_fbp_roots(context))

    def invoke(self, context, _event):
        targets = list(get_selected_fbp_roots(context))
        if not targets:
            return {"CANCELLED"}
        self.target_payload = _gp_capture_runtime_targets(targets)
        active = _active_canvas(context)
        if active is not None:
            try:
                self.canvas_name = fbp_obj_runtime_token(active) or str(active.name)
            except FBP_DATA_ERRORS:
                pass
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, _context):
        layout = configure_layout(self.layout)
        layout.prop(self, "canvas_name", text="Grease Pencil Canvas")
        layout.label(text="The matte is attached only to this effect instance.", icon="BLANK1")

    def execute(self, context):
        target_effect_id = str(self.target_effect_id or "").upper()
        target_instance_id = str(self.target_instance_id or "")
        canvas_token = str(self.canvas_name or "")
        canvas = fbp_find_id_by_runtime_key(bpy.data.objects, canvas_token, "") or bpy.data.objects.get(canvas_token)
        if not is_gp_mask_canvas(canvas):
            self.report({"ERROR"}, "Choose a dedicated Grease Pencil mask")
            return {"CANCELLED"}
        image, _changed = refresh_gp_mask(canvas, force=True, scene=getattr(context, "scene", None))
        if image is None:
            self.report({"ERROR"}, "The Grease Pencil canvas could not generate a mask image")
            return {"CANCELLED"}
        try:
            from .geometry_nodes import (
                _fbp_effect_ref, _fbp_effect_ref_is_active, fbp_add_effect,
                fbp_effect_is_active, fbp_effect_mask_target_ref,
                fbp_set_effect_mask_target,
            )
            from .effects_registry import fbp_effect_definition
            definition = fbp_effect_definition(target_effect_id)
            if not definition or str(definition.get("stage", "") or "") not in {"UV", "COLOR"}:
                self.report({"ERROR"}, "This effect cannot receive a local mask")
                return {"CANCELLED"}
            target_ref = _fbp_effect_ref(target_effect_id, target_instance_id)
            applied = 0
            targets = _gp_resolve_runtime_targets(self.target_payload) if self.target_payload else list(get_selected_fbp_roots(context))
            if not targets:
                self.report({"WARNING"}, "The original target layers no longer exist")
                return {"CANCELLED"}
            for rig in targets:
                if not _fbp_effect_ref_is_active(rig, target_ref):
                    continue
                slot_effect_id = gp_mask_effect_for_target(rig, target_effect_id, target_instance_id)
                if slot_effect_id is None:
                    continue
                if not fbp_effect_is_active(rig, slot_effect_id):
                    if not fbp_add_effect(rig, slot_effect_id, select_object_mask_helper=False):
                        continue
                slot = gp_mask_slot_contract(slot_effect_id)
                setattr(rig, slot["canvas"], canvas)
                setattr(rig, slot["image"], image)
                setattr(rig, slot["source_type"], "GREASE_PENCIL")
                setattr(rig, slot["path"], "")
                fbp_set_effect_mask_target(rig, slot_effect_id, target_effect_id, target_instance_id)
                if fbp_effect_mask_target_ref(rig, slot_effect_id) != target_ref:
                    continue
                _apply_canvas_mask_to_binding(canvas, rig, slot_effect_id, slot)
                applied += 1
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            self.report({"ERROR"}, f"Could not assign the Grease Pencil mask: {exc}")
            return {"CANCELLED"}
        if not applied:
            self.report({"WARNING"}, "The target instance is not active on the selected layers")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Assigned {canvas.name} on {applied} layer{'s' if applied != 1 else ''}")
        return {"FINISHED"}



def _delete_orphan_gp_mask(context, canvas):
    """Delete a dedicated mask canvas as soon as its final effect slot is removed."""
    if not is_gp_mask_canvas(canvas) or gp_mask_bindings(canvas):
        return False
    deleted, _users, _error = delete_gp_canvas(context, canvas)
    return bool(deleted)


class FBP_OT_DetachGreasePencilMaskFromEffect(Operator):
    bl_idname = "fbp.detach_grease_pencil_mask_from_effect"
    bl_label = "Detach Grease Pencil Mask From Effect"
    bl_description = "Remove the GP mask attached to one concrete effect instance"
    bl_options = {"REGISTER", "UNDO"}

    target_effect_id: StringProperty(name="Effect", default="", options={"SKIP_SAVE"})
    target_instance_id: StringProperty(name="Instance", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(get_selected_fbp_roots(context))

    def execute(self, context):
        target = str(self.target_effect_id or "").upper()
        target_instance = str(self.target_instance_id or "")
        detached = 0
        try:
            from .geometry_nodes import _fbp_effect_ref, fbp_effect_mask_target_ref, fbp_remove_effect
            target_ref = _fbp_effect_ref(target, target_instance)
            for rig in get_selected_fbp_roots(context):
                for effect_id, assigned_canvas, _slot in gp_mask_assignments(rig):
                    if fbp_effect_mask_target_ref(rig, effect_id) != target_ref:
                        continue
                    slot = gp_mask_slot_contract(effect_id)
                    setattr(rig, slot["canvas"], None)
                    setattr(rig, slot["image"], None)
                    setattr(rig, slot["source_type"], "FILE")
                    setattr(rig, slot["path"], "")
                    fbp_remove_effect(rig, effect_id)
                    _delete_orphan_gp_mask(context, assigned_canvas)
                    detached += 1
                    break
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            self.report({"ERROR"}, f"Could not detach the effect mask: {exc}")
            return {"CANCELLED"}
        if not detached:
            self.report({"INFO"}, "No Grease Pencil mask is attached to this effect instance")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Detached {detached} Grease Pencil effect mask{'s' if detached != 1 else ''}")
        return {"FINISHED"}



class FBP_OT_DetachGreasePencilMask(Operator):
    bl_idname = "fbp.detach_grease_pencil_mask"
    bl_label = "Detach Grease Pencil Mask"
    bl_description = "Remove the Grease Pencil mask effect and delete its dedicated drawing datablock"
    bl_options = {"REGISTER", "UNDO"}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', name="Layer", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        if bool(get_selected_fbp_roots(context)):
            return True
        return gp_canvas_owner(_active_canvas(context)) is not None

    def execute(self, context):
        explicit = bpy.data.objects.get(self.rig_name) if self.rig_name else None
        targets = [explicit] if explicit is not None else list(get_selected_fbp_roots(context))
        if not targets:
            owner = gp_canvas_owner(_active_canvas(context))
            targets = [owner] if owner is not None else []
        detached = 0
        try:
            from .geometry_nodes import fbp_remove_effect
            for rig in targets:
                if rig is None:
                    continue
                assignments = tuple(gp_mask_assignments(rig))
                removed_canvases = []
                rig_detached = False
                for effect_id, assigned_canvas, slot in assignments:
                    setattr(rig, slot["canvas"], None)
                    setattr(rig, slot["image"], None)
                    setattr(rig, slot["source_type"], "FILE")
                    setattr(rig, slot["path"], "")
                    fbp_remove_effect(rig, effect_id)
                    removed_canvases.append(assigned_canvas)
                    rig_detached = True
                for assigned_canvas in dict.fromkeys(removed_canvases):
                    _delete_orphan_gp_mask(context, assigned_canvas)
                detached += int(rig_detached)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            self.report({"ERROR"}, f"Could not detach the Grease Pencil mask: {exc}")
            return {"CANCELLED"}
        if not detached:
            self.report({"INFO"}, "No selected layer is using a Grease Pencil mask")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Detached Grease Pencil mask from {detached} layer{'s' if detached != 1 else ''}")
        return {"FINISHED"}


class FBP_OT_SelectGreasePencilMaskUsers(Operator):
    bl_idname = "fbp.select_grease_pencil_mask_users"
    bl_label = "Select Grease Pencil Mask Users"
    bl_description = "Select every Frame By Plane layer currently using this Grease Pencil mask"
    bl_options = {"REGISTER", "UNDO"}

    canvas_name: StringProperty(description='Display name stored by Frame By Plane. Renaming keeps internal identifiers and generated links intact.', name="Canvas", default="", options={"SKIP_SAVE"})

    def execute(self, context):
        canvas = bpy.data.objects.get(self.canvas_name) if self.canvas_name else _active_canvas(context)
        users = gp_mask_users(canvas)
        if not users:
            return {"CANCELLED"}
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except FBP_DATA_ERRORS:
            pass
        try:
            for obj in context.selected_objects:
                obj.select_set(False)
            for rig in users:
                rig.hide_set(False)
                rig.select_set(True)
            context.view_layer.objects.active = users[0]
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_RestoreGreasePencilReferenceOpacity(Operator):
    bl_idname = "fbp.restore_grease_pencil_reference_opacity"
    bl_label = "Restore Reference Opacity"
    bl_description = 'Restore the linked source layer opacity saved before Grease Pencil editing'
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None or bool(get_selected_fbp_roots(context))

    def execute(self, context):
        canvas = _active_canvas(context)
        rig = gp_canvas_owner(canvas)
        if rig is None:
            return {"CANCELLED"}
        try:
            original = float(canvas.get(KEY_REFERENCE_OPACITY, 1.0) or 1.0)
            canvas.fbp_gp_reference_opacity = original
            if not fbp_set_rna_property_silent(rig, "fbp_opacity", original):
                return {"CANCELLED"}
            from .materials import do_update_opacity
            do_update_opacity(rig)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return {"CANCELLED"}
        return {"FINISHED"}


def delete_gp_canvas(context, canvas):
    """Delete one generated GP canvas without touching its owner layer or plane.

    Returns ``(deleted, detached_user_count, error_message)`` and is shared by
    the dedicated operator, Layer List deletion and the global Delete override.
    Keeping the operation here prevents callers from resolving a canvas back to
    its owner rig and accidentally deleting the complete Frame By Plane layer.
    """
    if not is_gp_canvas(canvas):
        return False, 0, "No Grease Pencil canvas selected"
    rig = gp_canvas_owner(canvas)
    data = getattr(canvas, "data", None)
    image = getattr(canvas, "fbp_gp_mask_image", None)
    proxy = getattr(canvas, "fbp_gp_cycles_proxy", None)
    users = gp_mask_users(canvas)
    try:
        canvas["fbp_gp_deleting"] = True
        if _same_datablock(getattr(context, "object", None), canvas) and str(getattr(context, "mode", "OBJECT")) != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if rig is not None:
            try:
                from .grease_pencil_workflow import restore_workflow_reference
                restore_workflow_reference(canvas)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                fbp_warn("Could not restore the source layer before deleting its Grease Pencil canvas", exc)
        if rig is not None and _same_datablock(getattr(rig, "fbp_gp_canvas", None), canvas):
            rig.fbp_gp_canvas = next(
                (item for item in gp_canvases_for_rig(rig) if not _same_datablock(item, canvas)),
                None,
            )
        from .geometry_nodes import fbp_remove_effect
        for user_rig in users:
            assignments = tuple(gp_mask_assignments(user_rig))
            for effect_id, assigned_canvas, slot in assignments:
                if not _same_datablock(assigned_canvas, canvas):
                    continue
                setattr(user_rig, slot["canvas"], None)
                setattr(user_rig, slot["image"], None)
                setattr(user_rig, slot["source_type"], "FILE")
                setattr(user_rig, slot["path"], "")
                fbp_remove_effect(user_rig, effect_id)
        _unregister_runtime_canvas(canvas)
        # Keep generated proxy IDs quarantined so Blender Undo never restores a
        # canvas that points into already-freed Object/Material/NodeTree data.
        _quarantine_gp_cycles_proxy(proxy)
        bpy.data.objects.remove(canvas, do_unlink=True)
        if data is not None and int(getattr(data, "users", 0) or 0) == 0:
            bpy.data.grease_pencils.remove(data)
        if image is not None and bool(image.get(KEY_IS_MASK_IMAGE, False)):
            try:
                image["fbp_orphan_candidate"] = True
                _GP_MASK_IMAGE_RETIRED_AT[str(image.name)] = time.monotonic()
            except FBP_DATA_ERRORS:
                pass
        if rig is not None and _same_datablock(bpy.data.objects.get(getattr(rig, "name", "")), rig):
            try:
                for selected in tuple(getattr(context, "selected_objects", ()) or ()):
                    selected.select_set(False)
                rig.hide_set(False)
                rig.select_set(True)
                context.view_layer.objects.active = rig
            except FBP_DATA_ERRORS:
                pass
    except FBP_DATA_ERRORS as exc:
        try:
            canvas.pop("fbp_gp_deleting", None)
        except FBP_DATA_ERRORS:
            pass
        return False, len(users), str(exc)
    _refresh_layer_tree(context)
    return True, len(users), ""


class _FBP_GPCanvasRowOperator:
    canvas_name: StringProperty(description='Display name stored by Frame By Plane. Renaming keeps internal identifiers and generated links intact.', name="Canvas", default="", options={"SKIP_SAVE"})

    def _canvas(self, context):
        canvas = _operator_canvas(context, getattr(self, "canvas_name", ""))
        return canvas if is_gp_drawing_canvas(canvas) else None


def _fbp_gp_data_layers(canvas):
    try:
        return tuple(getattr(getattr(canvas, 'data', None), 'layers', ()) or ())
    except FBP_DATA_ERRORS:
        return ()


_GP_SELECTED_LAYERS_STATE_KEY = "gp.selected_layers"
_GP_LAYER_SELECTION_ANCHOR_STATE_KEY = "gp.layer_selection_anchor"


def gp_internal_layer_selected(canvas, layer_name):
    """Return transient UI multi-selection for one native GP layer.

    Selection highlights are editor state, not project data. Keeping them out of
    Object IDProperties avoids native IDProperty reads from UIList redraws after
    Undo, object deletion, file reload or extension reinstall.
    """
    if canvas is None or not layer_name:
        return False
    values = transient_get(canvas, _GP_SELECTED_LAYERS_STATE_KEY, ())
    try:
        return str(layer_name) in {str(value) for value in tuple(values or ())}
    except (TypeError, ValueError):
        return False


def _fbp_gp_layer_by_name(canvas, layer_name):
    wanted = str(layer_name or '')
    for layer in _fbp_gp_data_layers(canvas):
        try:
            if str(getattr(layer, 'name', '') or '') == wanted:
                return layer
        except FBP_DATA_ERRORS:
            continue
    return None


def _fbp_gp_layer_index(canvas, layer):
    """Return the native stack index for a Grease Pencil layer object."""
    if canvas is None or layer is None:
        return -1
    for index, candidate in enumerate(_fbp_gp_data_layers(canvas)):
        try:
            if candidate is layer or str(getattr(candidate, 'name', '') or '') == str(getattr(layer, 'name', '') or ''):
                return int(index)
        except FBP_DATA_ERRORS:
            continue
    return -1


def _fbp_gp_layer_below(canvas, layer):
    """Return the native GP layer directly underneath ``layer``.

    Blender's Grease Pencil layer stack API stores the masking source as a
    native layer-mask item.  In the UI, the source artists expect is the layer
    immediately below the active one in the Mask panel.  On current Blender GP
    builds that maps to the previous native layer index; keep the next-index
    fallback only for imported or reordered data.
    """
    layers = _fbp_gp_data_layers(canvas)
    index = _fbp_gp_layer_index(canvas, layer)
    if index < 0 or len(layers) < 2:
        return None
    if index - 1 >= 0:
        return layers[index - 1]
    if index + 1 < len(layers):
        return layers[index + 1]
    return None


def _fbp_gp_mask_collection(layer):
    for attr in ('mask_layers', 'layer_masks', 'masks'):
        try:
            collection = getattr(layer, attr, None)
            if collection is not None:
                return collection
        except FBP_DATA_ERRORS:
            continue
    return None


def _fbp_gp_mask_item_name(mask_item):
    for attr in ('name', 'layer_name', 'mask_layer_name'):
        try:
            value = str(getattr(mask_item, attr, '') or '')
            if value:
                return value
        except FBP_DATA_ERRORS:
            continue
    for attr in ('layer', 'source_layer', 'mask_layer'):
        try:
            layer = getattr(mask_item, attr, None)
            value = str(getattr(layer, 'name', '') or '') if layer is not None else ''
            if value:
                return value
        except FBP_DATA_ERRORS:
            continue
    return ''


def _fbp_gp_layer_has_native_mask(layer, source_name=''):
    if layer is None:
        return False
    try:
        enabled = any(bool(getattr(layer, attr)) for attr in ('use_masks', 'use_mask_layer', 'use_clipping_mask') if hasattr(layer, attr))
    except FBP_DATA_ERRORS:
        enabled = False
    collection = _fbp_gp_mask_collection(layer)
    if collection is None:
        return bool(enabled)
    if not source_name:
        try:
            return bool(enabled and len(collection) > 0)
        except FBP_DATA_ERRORS:
            return bool(enabled)
    wanted = str(source_name or '')
    try:
        for mask_item in collection:
            if _fbp_gp_mask_item_name(mask_item) == wanted:
                return bool(enabled)
    except FBP_DATA_ERRORS:
        pass
    return False


def gp_internal_layer_native_mask_active(canvas, layer_name):
    """Return whether a GP internal layer is masked by its underlying layer."""
    layer = _fbp_gp_layer_by_name(canvas, layer_name) if canvas else None
    source = _fbp_gp_layer_below(canvas, layer) if layer is not None else None
    source_name = str(getattr(source, 'name', '') or '') if source is not None else ''
    return _fbp_gp_layer_has_native_mask(layer, source_name)


def _fbp_gp_remove_mask_reference(collection, source):
    wanted = str(getattr(source, 'name', source) or '')
    removed = False
    if not wanted or collection is None:
        return False
    try:
        for mask_item in tuple(collection):
            if _fbp_gp_mask_item_name(mask_item) == wanted:
                remove = getattr(collection, 'remove', None)
                if callable(remove):
                    try:
                        remove(mask_item)
                    except TypeError:
                        remove(wanted)
                    removed = True
    except FBP_DATA_ERRORS:
        pass
    return removed


def _fbp_gp_enable_native_layer_masks(layer, enabled=True):
    changed = False
    for attr in ('use_masks', 'use_mask_layers', 'use_layer_masks', 'use_mask_layer', 'use_clipping_mask', 'use_clip_mask'):
        try:
            if hasattr(layer, attr) and bool(getattr(layer, attr)) != bool(enabled):
                setattr(layer, attr, bool(enabled))
                changed = True
        except FBP_DATA_ERRORS:
            continue
    return changed


def _fbp_gp_call_native_layer_mask_rna(layer, source, *, add=True):
    """Use Blender 5.2's context-free ``GreasePencilLayerMasks`` API.

    The API landed in Blender 5.2.  Keep several guarded call signatures so
    patch releases and backports remain harmless, then verify the collection
    rather than trusting a return value.
    """
    if layer is None or source is None:
        return False
    collection = _fbp_gp_mask_collection(layer)
    source_name = str(getattr(source, 'name', '') or '')
    if collection is None or not source_name:
        return False

    def _contains():
        try:
            return any(_fbp_gp_mask_item_name(item) == source_name for item in collection)
        except FBP_DATA_ERRORS:
            return False

    if add:
        if _contains():
            return True
        method = getattr(collection, 'add', None)
        if not callable(method):
            return False
        calls = (
            lambda: method(source),
            lambda: method(source_name),
            lambda: method(layer=source),
            lambda: method(name=source_name),
        )
        for call in calls:
            try:
                call()
            except TypeError:
                continue
            except FBP_DATA_ERRORS:
                continue
            if _contains():
                return True
        return _contains()

    if not _contains():
        return True
    method = getattr(collection, 'remove', None)
    if not callable(method):
        return False
    try:
        matching = next((item for item in tuple(collection) if _fbp_gp_mask_item_name(item) == source_name), None)
    except Exception:
        matching = None
    calls = []
    if matching is not None:
        calls.append(lambda: method(matching))
    calls.extend((lambda: method(source), lambda: method(source_name)))
    for call in calls:
        try:
            call()
        except TypeError:
            continue
        except FBP_DATA_ERRORS:
            continue
        if not _contains():
            return True
    return not _contains()


def _fbp_gp_make_native_mask_target_active(context, canvas, layer):
    """Make ``canvas`` and its internal GP ``layer`` the active native target.

    Blender's native mask operator writes to the active Grease Pencil object and
    active GP layer. The Layer List button prepares the same state artists get in
    the Data
    properties panel before calling ``bpy.ops.grease_pencil.layer_mask_add``.
    """
    if canvas is None or layer is None:
        return
    try:
        if getattr(canvas, 'mode', 'OBJECT') != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except FBP_DATA_ERRORS:
        pass
    try:
        for obj in tuple(getattr(context, 'selected_objects', ()) or ()):
            obj.select_set(False)
    except FBP_DATA_ERRORS:
        pass
    try:
        canvas.hide_set(False)
        canvas.hide_viewport = False
        canvas.select_set(True)
        context.view_layer.objects.active = canvas
    except FBP_DATA_ERRORS:
        pass
    try:
        layers = getattr(getattr(canvas, 'data', None), 'layers', None)
        if layers is not None:
            index = _fbp_gp_layer_index(canvas, layer)
            if hasattr(layers, 'active'):
                layers.active = layer
            if index >= 0 and hasattr(layers, 'active_index'):
                layers.active_index = index
    except FBP_DATA_ERRORS:
        pass


def _fbp_gp_set_properties_context_to_data(context):
    """Best-effort DATA tab activation for native Grease Pencil mask ops."""
    touched = []
    candidates = []
    try:
        candidates.append(getattr(context, 'space_data', None))
    except FBP_DATA_ERRORS:
        pass
    try:
        screen = getattr(context, 'screen', None)
        for area in tuple(getattr(screen, 'areas', ()) or ()):
            if getattr(area, 'type', '') != 'PROPERTIES':
                continue
            for space in tuple(getattr(area, 'spaces', ()) or ()):
                candidates.append(space)
    except FBP_DATA_ERRORS:
        pass
    for space in candidates:
        if space is None or not hasattr(space, 'context'):
            continue
        try:
            old = space.context
            if old != 'DATA':
                space.context = 'DATA'
                touched.append((space, old))
        except FBP_DATA_ERRORS:
            continue
    return touched


def _fbp_gp_restore_properties_context(touched):
    for space, old in reversed(tuple(touched or ())):
        try:
            space.context = old
        except FBP_DATA_ERRORS:
            pass


def _fbp_gp_call_native_layer_mask_operator(context, canvas, layer, source_name, *, add=True):
    """Call Blender's native GP layer mask operator on the active GP layer."""
    wanted = str(source_name or '')
    if not wanted:
        return False
    op_name = 'layer_mask_add' if add else 'layer_mask_remove'
    op = getattr(bpy.ops.grease_pencil, op_name, None)
    if op is None:
        return False

    _fbp_gp_make_native_mask_target_active(context, canvas, layer)
    touched = _fbp_gp_set_properties_context_to_data(context)

    def _call_with_current_context():
        for kwargs in ({'name': wanted}, {'layer_name': wanted}, {'mask_name': wanted}, {}):
            try:
                result = op(**kwargs)
                if result is None or 'CANCELLED' not in set(result):
                    return True
            except TypeError:
                continue
            except FBP_DATA_ERRORS:
                continue
        return False

    try:
        if _call_with_current_context():
            return True
        # Some builds require a Properties/DATA area override.  Keep this as a
        # secondary path only, so the operator still works from the viewport UI.
        try:
            screen = getattr(context, 'screen', None)
            for area in tuple(getattr(screen, 'areas', ()) or ()):
                if getattr(area, 'type', '') != 'PROPERTIES':
                    continue
                region = next((r for r in getattr(area, 'regions', ()) if getattr(r, 'type', '') == 'WINDOW'), None)
                space = getattr(area, 'spaces', None).active if getattr(area, 'spaces', None) else None
                try:
                    with context.temp_override(area=area, region=region, space_data=space, object=canvas, active_object=canvas, selected_objects=[canvas]):
                        if _call_with_current_context():
                            return True
                except FBP_DATA_ERRORS:
                    continue
        except FBP_DATA_ERRORS:
            pass
    finally:
        _fbp_gp_restore_properties_context(touched)
    return False


def _fbp_gp_layer_color_tag_index(layer, fallback_index=-1):
    """Return 1..7 for colored GP layers; never returns the brown 08 icon."""
    if layer is None:
        return 0
    for attr in ('color_tag', 'fbp_color_tag'):
        try:
            value = str(getattr(layer, attr, '') or '').upper()
        except FBP_DATA_ERRORS:
            value = ''
        except Exception:
            value = ''
        if value:
            digits = ''.join(ch for ch in value if ch.isdigit())
            if digits:
                idx = int(digits)
                if 1 <= idx <= 7:
                    return idx
                if idx == 8:
                    return 0
    # Some Blender GP layer builds expose a display/channel color but not a
    # color-tag enum.  If a real non-default color is present, assign a stable
    # non-brown layer-group icon by row index.
    for attr in ('channel_color', 'color', 'tint_color'):
        try:
            color = tuple(getattr(layer, attr))
        except FBP_DATA_ERRORS:
            continue
        if len(color) >= 3:
            rgb = tuple(float(v) for v in color[:3])
            if any(abs(v) > 0.001 for v in rgb) and not all(abs(v - 1.0) < 0.001 for v in rgb):
                try:
                    return (max(0, int(fallback_index)) % 7) + 1
                except (TypeError, ValueError, OverflowError):
                    return 1
    return 0


def gp_internal_layer_icon(canvas, layer_name):
    layer = _fbp_gp_layer_by_name(canvas, layer_name) if canvas else None
    index = _fbp_gp_layer_index(canvas, layer)
    color_index = _fbp_gp_layer_color_tag_index(layer, index)
    if 1 <= color_index <= 7:
        return f'LAYERGROUP_COLOR_{color_index:02d}'
    return 'OUTLINER_DATA_GP_LAYER'


def _fbp_remove_gp_layer(data, layer):
    try:
        layers = getattr(data, 'layers', None)
        if layers is None or layer is None:
            return False
        remove = getattr(layers, 'remove', None)
        if callable(remove):
            remove(layer)
            return True
    except FBP_DATA_ERRORS:
        pass
    return False


class FBP_OT_ToggleGPLayersExpanded(_FBP_GPCanvasRowOperator, Operator):
    bl_idname = 'fbp.toggle_gp_layers_expanded'
    bl_label = 'Show Grease Pencil Layers'
    bl_description = 'Expand or collapse the internal layers of this Grease Pencil object'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        canvas = self._canvas(context)
        if canvas is None:
            return {'CANCELLED'}
        try:
            canvas.fbp_gp_layers_expanded = not bool(getattr(canvas, 'fbp_gp_layers_expanded', False))
        except FBP_DATA_ERRORS:
            return {'CANCELLED'}
        _refresh_layer_tree(context, update_compositor=False)
        return {'FINISHED'}


class FBP_OT_SelectGPInternalLayer(_FBP_GPCanvasRowOperator, Operator):
    bl_idname = 'fbp.select_gp_internal_layer'
    bl_label = 'Select Grease Pencil Layer'
    bl_description = 'Select this internal Grease Pencil layer and make its canvas active'
    bl_options = {'REGISTER', 'UNDO'}

    layer_name: StringProperty(name='Grease Pencil Layer', default='', options={'SKIP_SAVE'})
    use_shift: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    use_ctrl: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        return invoke_with_selection_modifiers(self, context, event)

    def execute(self, context):
        canvas = self._canvas(context)
        if canvas is None:
            return {'CANCELLED'}
        layer = _fbp_gp_layer_by_name(canvas, self.layer_name)
        names = [
            str(getattr(item, 'name', '') or '')
            for item in _fbp_gp_data_layers(canvas)
        ]
        if self.layer_name not in names:
            return {'CANCELLED'}
        target_index = names.index(self.layer_name)
        try:
            current = {
                str(value)
                for value in tuple(
                    transient_get(canvas, _GP_SELECTED_LAYERS_STATE_KEY, ()) or ()
                )
            }
        except (TypeError, ValueError):
            current = set()
        anchor = int(
            transient_get(canvas, _GP_LAYER_SELECTION_ANCHOR_STATE_KEY, target_index)
        )
        lo, hi = sorted((max(0, anchor), target_index))
        if self.use_shift:
            selected = set(names[lo:hi + 1])
            if self.use_ctrl:
                selected.update(current)
        elif self.use_ctrl:
            selected = set(current)
            if self.layer_name in selected:
                selected.remove(self.layer_name)
            else:
                selected.add(self.layer_name)
        else:
            selected = {self.layer_name}
        transient_set(
            canvas,
            _GP_SELECTED_LAYERS_STATE_KEY,
            tuple(name for name in names if name in selected),
        )
        if not self.use_shift:
            transient_set(canvas, _GP_LAYER_SELECTION_ANCHOR_STATE_KEY, target_index)
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except FBP_DATA_ERRORS:
            pass
        try:
            for obj in tuple(getattr(context, 'selected_objects', ()) or ()):
                obj.select_set(False)
            canvas.hide_set(False)
            canvas.hide_viewport = False
            canvas.select_set(True)
            context.view_layer.objects.active = canvas
        except FBP_DATA_ERRORS:
            pass
        try:
            layers = getattr(getattr(canvas, 'data', None), 'layers', None)
            if layer is not None and hasattr(layers, 'active'):
                layers.active = layer
        except FBP_DATA_ERRORS:
            pass
        return {'FINISHED'}


class FBP_OT_ToggleGPInternalLayerMask(_FBP_GPCanvasRowOperator, Operator):
    bl_idname = 'fbp.toggle_gp_internal_layer_mask'
    bl_label = 'Toggle Grease Pencil Layer Mask'
    bl_description = 'Toggle the native Blender 5.2 mask link with the Grease Pencil layer directly below'
    bl_options = {'REGISTER', 'UNDO'}

    layer_name: StringProperty(name='Grease Pencil Layer', default='', options={'SKIP_SAVE'})

    def execute(self, context):
        canvas = self._canvas(context)
        layer = _fbp_gp_layer_by_name(canvas, self.layer_name) if canvas else None
        if layer is None:
            return {'CANCELLED'}
        source = _fbp_gp_layer_below(canvas, layer)
        source_name = str(getattr(source, 'name', '') or '') if source is not None else ''
        if not source_name:
            self.report({'WARNING'}, 'This GP layer has no underlying layer to use as a native mask')
            return {'CANCELLED'}

        active = _fbp_gp_layer_has_native_mask(layer, source_name)
        changed = False
        if active:
            if _fbp_gp_call_native_layer_mask_rna(layer, source, add=False):
                changed = True
            elif _fbp_gp_call_native_layer_mask_operator(context, canvas, layer, source_name, add=False):
                changed = True
            else:
                collection = _fbp_gp_mask_collection(layer)
                changed = _fbp_gp_remove_mask_reference(collection, source)
            try:
                collection = _fbp_gp_mask_collection(layer)
                if collection is not None and len(collection) == 0:
                    changed = bool(_fbp_gp_enable_native_layer_masks(layer, False) or changed)
            except FBP_DATA_ERRORS:
                pass
        else:
            _fbp_gp_enable_native_layer_masks(layer, True)
            if not _fbp_gp_call_native_layer_mask_rna(layer, source, add=True):
                if not _fbp_gp_call_native_layer_mask_operator(context, canvas, layer, source_name, add=True):
                    self.report({'WARNING'}, f'Could not link native GP mask layer: {source_name}')
                    return {'CANCELLED'}
            changed = True

        try:
            layers = getattr(getattr(canvas, 'data', None), 'layers', None)
            if hasattr(layers, 'active'):
                layers.active = layer
        except FBP_DATA_ERRORS:
            pass
        if changed:
            try:
                getattr(canvas, 'data', None).update_tag()
            except FBP_DATA_ERRORS:
                pass
        _refresh_layer_tree(context)
        return {'FINISHED'}


class FBP_OT_SplitGPSingleLayer(_FBP_GPCanvasRowOperator, Operator):
    bl_idname = 'fbp.split_gp_single_layer'
    bl_label = 'Split Grease Pencil Layer'
    bl_description = 'Extract this internal Grease Pencil layer into a new object and remove it from the source GP when possible'
    bl_options = {'REGISTER', 'UNDO'}

    layer_name: StringProperty(name='Grease Pencil Layer', default='', options={'SKIP_SAVE'})

    def execute(self, context):
        canvas = self._canvas(context)
        source_layer = _fbp_gp_layer_by_name(canvas, self.layer_name) if canvas else None
        if canvas is None or source_layer is None:
            return {'CANCELLED'}
        source_layers = _fbp_gp_data_layers(canvas)
        if len(source_layers) <= 1:
            self.report({'WARNING'}, 'This Grease Pencil already contains only this layer')
            return {'CANCELLED'}
        try:
            new_obj = canvas.copy()
            new_obj.data = canvas.data.copy()
            new_obj.name = f'{canvas.name}_{self.layer_name}'
            parent_coll = None
            for coll in tuple(getattr(canvas, 'users_collection', ()) or ()):
                parent_coll = coll
                break
            (parent_coll or context.scene.collection).objects.link(new_obj)
            new_obj.fbp_gp_layers_expanded = True
            for layer in tuple(_fbp_gp_data_layers(new_obj)):
                if str(getattr(layer, 'name', '') or '') != str(self.layer_name):
                    _fbp_remove_gp_layer(new_obj.data, layer)
            # Extraction must not leave the same strokes inside the source GP:
            # otherwise repeated clicks on the chain/split icon generate an
            # infinite set of duplicate objects while the original stack never
            # changes. Remove the selected layer only after the isolated object
            # has been linked successfully.
            refreshed_source = _fbp_gp_layer_by_name(canvas, self.layer_name)
            if refreshed_source is not None:
                _fbp_remove_gp_layer(canvas.data, refreshed_source)
            _tag_canvas(new_obj, gp_canvas_owner(canvas), kind='DRAWING')
            for obj in tuple(getattr(context, 'selected_objects', ()) or ()):
                obj.select_set(False)
            new_obj.select_set(True)
            context.view_layer.objects.active = new_obj
            try:
                canvas.data.update_tag()
                new_obj.data.update_tag()
            except FBP_DATA_ERRORS:
                pass
        except FBP_DATA_ERRORS as exc:
            fbp_warn('Could not split Grease Pencil layer', exc)
            return {'CANCELLED'}
        except Exception as exc:
            fbp_warn('Could not split Grease Pencil layer', exc)
            return {'CANCELLED'}
        _refresh_layer_tree(context)
        self.report({'INFO'}, f'Split GP layer: {self.layer_name}')
        return {'FINISHED'}


class FBP_OT_SplitGPCanvasLayers(_FBP_GPCanvasRowOperator, Operator):
    bl_idname = 'fbp.split_gp_canvas_layers'
    bl_label = 'Split Grease Pencil Layers'
    bl_description = 'Create one Grease Pencil object per internal layer when possible'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        canvas = self._canvas(context) or _active_canvas(context)
        if canvas is None:
            self.report({'WARNING'}, 'Select one Grease Pencil canvas first')
            return {'CANCELLED'}
        layer_names = [str(getattr(layer, 'name', '') or '') for layer in _fbp_gp_data_layers(canvas)]
        if len(layer_names) <= 1:
            self.report({'WARNING'}, 'This Grease Pencil already contains a single layer')
            return {'CANCELLED'}
        created = 0
        # Extract all but the final remaining layer. The original canvas becomes
        # the last layer object, avoiding an empty Grease Pencil datablock.
        for layer_name in layer_names[:-1]:
            op = FBP_OT_SplitGPSingleLayer()
            op.canvas_name = canvas.name
            op.layer_name = layer_name
            if op.execute(context) == {'FINISHED'}:
                created += 1
        if created <= 0:
            return {'CANCELLED'}
        self.report({'INFO'}, f'Extracted {created} GP layer(s); source keeps the final layer')
        return {'FINISHED'}


class FBP_OT_CollapseGPCanvasesToOne(Operator):
    bl_idname = 'fbp.collapse_gp_canvases_to_one'
    bl_label = 'Collapse Layers in One Grease Pencil'
    bl_description = 'Join selected Grease Pencil canvases into one object when Blender supports GP object joining'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        canvases = [obj for obj in tuple(getattr(context, 'selected_objects', ()) or ()) if is_gp_drawing_canvas(obj)]
        if len(canvases) < 2:
            self.report({'WARNING'}, 'Select at least two Grease Pencil canvases')
            return {'CANCELLED'}
        active = getattr(getattr(context, 'view_layer', None), 'objects', None)
        active_obj = getattr(active, 'active', None) if active is not None else None
        target = active_obj if active_obj in canvases else canvases[0]
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except FBP_DATA_ERRORS:
            pass
        try:
            for obj in tuple(getattr(context, 'selected_objects', ()) or ()):
                obj.select_set(False)
            for obj in canvases:
                obj.hide_set(False)
                obj.select_set(True)
            context.view_layer.objects.active = target
            result = bpy.ops.object.join()
            if 'FINISHED' not in result:
                return {'CANCELLED'}
            target.fbp_gp_layers_expanded = True
            _tag_canvas(target, gp_canvas_owner(target), kind='DRAWING')
        except Exception as exc:
            fbp_warn('Could not collapse Grease Pencil canvases', exc)
            self.report({'ERROR'}, 'Blender could not join these Grease Pencil canvases')
            return {'CANCELLED'}
        _refresh_layer_tree(context)
        return {'FINISHED'}


class FBP_OT_DuplicateSelectedGPCanvases(Operator):
    bl_idname = 'fbp.duplicate_selected_gp_canvases'
    bl_label = 'Duplicate Selected Grease Pencil'
    bl_description = 'Duplicate selected Grease Pencil canvases while preserving Frame By Plane canvas tags'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        canvases = [obj for obj in tuple(getattr(context, 'selected_objects', ()) or ()) if is_gp_drawing_canvas(obj)]
        if not canvases:
            canvas = _active_canvas(context)
            canvases = [canvas] if canvas is not None else []
        if not canvases:
            return {'CANCELLED'}
        created = []
        for canvas in canvases:
            try:
                new_obj = canvas.copy()
                new_obj.data = canvas.data.copy()
                new_obj.name = f'{canvas.name}_copy'
                parent_coll = None
                for coll in tuple(getattr(canvas, 'users_collection', ()) or ()):
                    parent_coll = coll
                    break
                (parent_coll or context.scene.collection).objects.link(new_obj)
                _tag_canvas(new_obj, gp_canvas_owner(canvas), kind='DRAWING')
                created.append(new_obj)
            except Exception as exc:
                fbp_warn('Could not duplicate Grease Pencil canvas', exc)
        if not created:
            return {'CANCELLED'}
        try:
            for obj in tuple(getattr(context, 'selected_objects', ()) or ()):
                obj.select_set(False)
            for obj in created:
                obj.select_set(True)
            context.view_layer.objects.active = created[-1]
        except FBP_DATA_ERRORS:
            pass
        _refresh_layer_tree(context)
        return {'FINISHED'}


class FBP_OT_DeleteGreasePencilCanvas(Operator):
    bl_idname = "fbp.delete_grease_pencil_canvas"
    bl_label = "Delete Grease Pencil Canvas"
    bl_description = "Delete the selected generated canvas and detach its mask image; this does not delete the Frame By Plane layer"
    bl_options = {"REGISTER", "UNDO"}

    canvas_name: StringProperty(description='Display name stored by Frame By Plane. Renaming keeps internal identifiers and generated links intact.', name="Canvas", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _active_canvas(context) is not None

    def invoke(self, context, event):
        canvas = _operator_canvas(context, self.canvas_name)
        if canvas is not None and len(gp_mask_users(canvas)) > 1:
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        canvas = _operator_canvas(context, self.canvas_name)
        deleted, users, error = delete_gp_canvas(context, canvas)
        if not deleted:
            self.report({"ERROR"}, f"Could not delete the canvas: {error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Deleted canvas and detached {users} mask user{'s' if users != 1 else ''}")
        return {"FINISHED"}


class FBP_OT_ToggleGPCanvasSolo(_FBP_GPCanvasRowOperator, Operator):
    bl_idname = "fbp.toggle_gp_canvas_solo"
    bl_label = "Toggle Drawing Plane Solo"
    bl_description = "Solo or unsolo this Drawing Plane in the Layer List"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        canvas = self._canvas(context)
        if canvas is None:
            return {"CANCELLED"}
        scene = getattr(context, "scene", None) if context else None
        activating = not gp_canvas_solo_active(canvas)
        try:
            if activating:
                # GP solo is exclusive and must also isolate against normal FBP
                # plane layers. This keeps Layer List Solo consistent with Z > Solo.
                clear_gp_canvas_solo(scene, except_canvas=canvas)
                fbp_set_rna_property_silent(canvas, "fbp_gp_canvas_visible", True)
                for item in (getattr(scene, "fbp_layers", ()) or ()):
                    item.solo = False
                    rig = getattr(item, "obj", None)
                    if rig is not None:
                        fbp_set_rna_property_silent(rig, "fbp_is_visible", False)
                try:
                    canvas.hide_set(False)
                    canvas.hide_viewport = False
                    if object_in_view_layer(canvas, context):
                        for obj in tuple(getattr(context.scene, "objects", ()) or ()):  # keep Blender selection consistent with Z > Solo
                            if obj.select_get():
                                obj.select_set(False)
                        canvas.select_set(True)
                        context.view_layer.objects.active = canvas
                except FBP_DATA_ERRORS:
                    pass
            else:
                canvas[KEY_CANVAS_SOLO] = False
                if scene is not None and not any_gp_canvas_solo(scene):
                    for item in (getattr(scene, "fbp_layers", ()) or ()):
                        rig = getattr(item, "obj", None)
                        if rig is not None:
                            fbp_set_rna_property_silent(rig, "fbp_is_visible", True)
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}
        try:
            from .layers import update_global_visibility
            update_global_visibility(context)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            sync_gp_canvas_visibility(context)
        _refresh_layer_tree(context)
        return {"FINISHED"}


class FBP_OT_ToggleGPCanvasHoldout(_FBP_GPCanvasRowOperator, Operator):
    bl_idname = "fbp.toggle_gp_canvas_holdout"
    bl_label = "Toggle Drawing Plane Holdout"
    bl_description = "Toggle Blender holdout on this Drawing Plane"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        canvas = self._canvas(context)
        if canvas is None or not hasattr(canvas, "is_holdout"):
            return {"CANCELLED"}
        try:
            canvas.is_holdout = not bool(getattr(canvas, "is_holdout", False))
            _refresh_layer_tree(context)
            return {"FINISHED"}
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}


class FBP_OT_ToggleGPCanvasLockSelect(_FBP_GPCanvasRowOperator, Operator):
    bl_idname = "fbp.toggle_gp_canvas_lock_select"
    bl_label = "Toggle Drawing Plane Lock Select"
    bl_description = "Prevent or allow selecting this Drawing Plane"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        canvas = self._canvas(context)
        if canvas is None:
            return {"CANCELLED"}
        try:
            canvas.hide_select = not bool(getattr(canvas, "hide_select", False))
            if bool(getattr(canvas, "hide_select", False)) and bool(canvas.select_get()):
                canvas.select_set(False)
            _refresh_layer_tree(context)
            return {"FINISHED"}
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}


class FBP_OT_ToggleGPCanvasVisibility(_FBP_GPCanvasRowOperator, Operator):
    bl_idname = "fbp.toggle_gp_canvas_visibility"
    bl_label = "Toggle Drawing Plane Visibility"
    bl_description = "Hide or show this Drawing Plane"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        canvas = self._canvas(context)
        if canvas is None:
            return {"CANCELLED"}
        try:
            canvas.fbp_gp_canvas_visible = not bool(getattr(canvas, "fbp_gp_canvas_visible", True))
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}
        sync_gp_canvas_visibility(context)
        _refresh_layer_tree(context)
        return {"FINISHED"}


class FBP_OT_ToggleGPCanvasClipping(_FBP_GPCanvasRowOperator, Operator):
    bl_idname = "fbp.toggle_gp_canvas_clipping"
    bl_label = "Toggle Drawing Plane Clipping"
    bl_description = "Mixed Grease Pencil/Plane clipping requires a proxy-raster pipeline and is not exposed as a stable layer action yet"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        canvas = self._canvas(context)
        if canvas is None:
            return {"CANCELLED"}
        try:
            if KEY_CANVAS_CLIPPING in canvas:
                canvas[KEY_CANVAS_CLIPPING] = False
        except FBP_DATA_ERRORS:
            pass
        _refresh_layer_tree(context)
        self.report({"WARNING"}, "GP ↔ Plane clipping is not stable yet; use plane-to-plane clipping or a GP Mask effect/proxy workflow")
        return {"CANCELLED"}


def gp_mask_canvas_for_rig(rig):
    """Return the primary/internal GP Mask currently assigned to *rig*."""
    if rig is None:
        return None
    for attr in (
        "fbp_gp_mask_canvas",
        "fbp_gp_mask_slot_2_canvas",
        "fbp_gp_mask_slot_3_canvas",
        "fbp_gp_mask_slot_4_canvas",
    ):
        try:
            canvas = getattr(rig, attr, None)
            if is_gp_mask_canvas(canvas):
                return canvas
        except FBP_DATA_ERRORS:
            continue
    return None


def _gp_canvas_is_selected(context, canvas):
    try:
        return bool(canvas is not None and getattr(context, "object", None) == canvas)
    except FBP_DATA_ERRORS:
        return False


def _gp_canvas_is_draw_mode(context, canvas):
    try:
        mode = str(getattr(context, "mode", "") or "").upper()
        return bool(
            _gp_canvas_is_selected(context, canvas)
            and mode in {"PAINT_GREASE_PENCIL", "EDIT_GREASE_PENCIL"}
        )
    except FBP_DATA_ERRORS:
        return False


def _draw_gp_mask_action_buttons(row, context, canvas, rig=None, *, include_detach=True):
    selected = _gp_canvas_is_selected(context, canvas)
    select = row.operator(
        "fbp.select_grease_pencil_canvas",
        text="",
        icon="RESTRICT_SELECT_OFF" if selected else "RESTRICT_SELECT_ON",
        emboss=False,
        depress=selected,
    )
    select.rig_name = getattr(rig, "name", "") if rig else ""
    select.canvas_name = getattr(canvas, "name", "") if canvas else ""
    if include_detach:
        detached = row.operator(
            "fbp.detach_grease_pencil_mask",
            text="",
            icon="UNLINKED" if gp_mask_bindings(canvas) else "LINKED",
            emboss=False,
        )
        detached.rig_name = getattr(rig, "name", "") if rig else ""
    return selected


def draw_gp_mask_settings_ui(layout, context, canvas=None, *, embedded=False, header_actions=True):
    """Draw the simplified GP Mask controls from either mask or owner plane."""
    canvas = canvas or _active_canvas(context)
    if not is_gp_mask_canvas(canvas):
        return False
    # In native GP Edit Mode keep settings read-only/minimal. Native geometry
    # changes still reach the capped quiet-time preview, but property callbacks
    # and repair helpers remain outside Blender's structural edit window.
    if _gp_mask_is_structural_edit_mode(canvas):
        root = layout.box() if embedded else layout
        header = root.row(align=True)
        header.label(text="Grease Pencil Mask", **ui_label_icon_kwargs("menu.gp_layer", fallback="menu.gp_layer"))
        header.label(text="Edit Mode - live preview", icon="FILE_REFRESH")
        msg = root.row(align=True)
        msg.enabled = False
        msg.label(text=f"Stroke Type and {alt_shortcut_label('S')} refresh after the native tool settles", icon="INFO")
        return True
    rig = gp_canvas_owner(canvas)
    root = layout.box() if embedded else layout
    try:
        if not bool(getattr(canvas, "fbp_gp_canvas_visible", True)):
            fbp_set_rna_property_silent(canvas, "fbp_gp_canvas_visible", True)
    except FBP_DATA_ERRORS:
        pass

    if header_actions:
        header = root.row(align=False)
        header.label(text="Grease Pencil Mask", **ui_label_icon_kwargs("menu.gp_layer", fallback="menu.gp_layer"))
        actions = header.row(align=True)
        actions.alignment = 'RIGHT'
        _draw_gp_mask_action_buttons(actions, context, canvas, rig, include_detach=True)

    row = root.row(align=False)
    row.prop(canvas, "fbp_gp_mask_opacity", text="Mask Opacity", slider=True)
    row.prop(canvas, "fbp_gp_mask_invert", text="Invert", toggle=True, icon=ui_icon("action.invert"))

    row = root.row(align=False)
    row.prop(canvas, "fbp_gp_canvas_opacity", text="Visibility", slider=True)
    draw_col = row.row(align=True)
    draw_col.alignment = 'RIGHT'
    draw_mode = _gp_canvas_is_draw_mode(context, canvas)
    active_tool = _active_tool_id(context).upper()
    draw = draw_col.operator(
        "fbp.enter_grease_pencil_draw",
        text="",
        icon="GREASEPENCIL",
        emboss=True,
        depress=draw_mode and "FILL" not in active_tool and "ERASE" not in active_tool,
    )
    draw.rig_name = getattr(rig, "name", "") if rig else ""
    draw.canvas_name = getattr(canvas, "name", "")
    draw.tool = "PRESERVE"
    fill = draw_col.operator(
        "fbp.enter_grease_pencil_draw",
        text="",
        icon="COLOR",
        emboss=True,
        depress=draw_mode and "FILL" in active_tool,
    )
    fill.rig_name = getattr(rig, "name", "") if rig else ""
    fill.canvas_name = getattr(canvas, "name", "")
    fill.tool = "FILL"
    erase = draw_col.operator(
        "fbp.enter_grease_pencil_draw",
        text="",
        icon="PANEL_CLOSE",
        emboss=True,
        depress=draw_mode and "ERASE" in active_tool,
    )
    erase.rig_name = getattr(rig, "name", "") if rig else ""
    erase.canvas_name = getattr(canvas, "name", "")
    erase.tool = "ERASE"

    controls = root.column(align=False)
    row = controls.row(align=True)
    row.prop(canvas, "fbp_gp_mask_feather", text="Blur", slider=True)
    row.prop(canvas, "fbp_gp_mask_expand", text="Expand", slider=True)

    preview_row = controls.row(align=True)
    preview_row.prop(canvas, "fbp_gp_mask_preview_quality", text="Preview")

    # Final mask quality stays fixed at 1024px. The exposed control only changes
    # the live preview cap while drawing. Internal detected-mode/radius telemetry
    # remains available to the runtime but is intentionally hidden from the user.

    radius = controls.row(align=True)
    radius.prop(canvas, "fbp_gp_mask_auto_radius", text="Auto", toggle=True)
    manual = radius.row(align=True)
    manual.enabled = not bool(getattr(canvas, "fbp_gp_mask_auto_radius", True))
    manual.prop(canvas, "fbp_gp_mask_stroke_width", text="Radius", slider=True)

    controls.prop(canvas, "fbp_gp_mask_source", text="Geometry")

    # Keep extraction diagnostics at the very bottom, below all editable mask
    # controls. This is a passive cache/source hint rather than a primary status.
    try:
        debug_state = _GP_MASK_DEBUG_STATE.get(_canvas_pointer(canvas), {})
        dbg_source = str(
            debug_state.get("source", canvas.get("fbp_gp_mask_debug_source", "")) or ""
        )
        dbg_points = int(
            debug_state.get("points", canvas.get("fbp_gp_mask_debug_points", 0)) or 0
        )
        dbg_lines = int(
            debug_state.get("polylines", canvas.get("fbp_gp_mask_debug_polylines", 0)) or 0
        )
        dbg_fills = int(
            debug_state.get("fills", canvas.get("fbp_gp_mask_debug_fills", 0)) or 0
        )
        if dbg_source:
            dbg = controls.row(align=True)
            dbg.label(
                text=f"Read {dbg_source.title()} · {dbg_points} pts · {dbg_lines} lines · {dbg_fills} fills",
                icon="FILE_REFRESH",
            )
    except FBP_DATA_ERRORS:
        pass
    return True


class FBP_PT_GreasePencilCanvas(Panel):
    bl_label = "Grease Pencil"
    bl_description = "Create and manage a Grease Pencil canvas linked to the selected Frame By Plane layer"
    bl_idname = "FBP_PT_grease_pencil_canvas"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Frame By Plane"
    bl_order = 4

    @classmethod
    def poll(cls, context):
        if is_gp_canvas(getattr(context, "object", None)):
            return True
        return bool(get_selected_fbp_roots(context))

    def draw_header(self, _context):
        self.layout.label(text="", **ui_label_icon_kwargs("menu.gp_layer", fallback="menu.gp_layer"))

    def draw(self, context):
        layout = configure_layout(self.layout)
        canvas = _active_canvas(context)
        if canvas is None:
            empty = empty_state(
                layout,
                "No Grease Pencil Layer",
                "Create a drawing layer linked to the selected Frame By Plane layer.",
                icon="GREASEPENCIL",
            )
            empty.operator("fbp.add_grease_pencil_canvas", text="Add Grease Pencil Layer", **ui_icon_kwargs("menu.gp_layer", fallback="menu.gp_layer"))
            return
        if is_gp_mask_canvas(canvas):
            draw_gp_mask_settings_ui(layout, context, canvas)
            return

        rig = gp_canvas_owner(canvas)
        top = layout.box()
        configure_layout(top)
        section_header(top, "Active Drawing", icon="GREASEPENCIL")
        row = top.row(align=False)
        row.prop(canvas, "fbp_color_tag", text="", icon_only=False)
        row.prop(canvas, "fbp_layer_name", text="", **ui_icon_kwargs("menu.gp_layer", fallback="menu.gp_layer"))
        draw = row.operator("fbp.enter_grease_pencil_draw", text="", icon="BRUSH_DATA")
        draw.rig_name = getattr(rig, "name", "") if rig else ""
        draw.canvas_name = getattr(canvas, "name", "")
        draw.tool = "PRESERVE"
        fill = row.operator("fbp.enter_grease_pencil_draw", text="", icon="COLOR")
        fill.rig_name = getattr(rig, "name", "") if rig else ""
        fill.canvas_name = getattr(canvas, "name", "")
        fill.tool = "FILL"
        erase = row.operator("fbp.enter_grease_pencil_draw", text="", icon="PANEL_CLOSE")
        erase.rig_name = getattr(rig, "name", "") if rig else ""
        erase.canvas_name = getattr(canvas, "name", "")
        erase.tool = "ERASE"
        row.operator("fbp.delete_grease_pencil_canvas", text="", icon="TRASH")

        if is_gp_drawing_canvas(canvas):
            linked = rig is not None
            row = top.row(align=False)
            visible = bool(getattr(canvas, "fbp_gp_canvas_visible", True))
            row.prop(
                canvas, "fbp_gp_canvas_visible", text="", toggle=True,
                icon="HIDE_OFF" if visible else "HIDE_ON",
            )
            row.prop(canvas, "fbp_gp_canvas_opacity", text="Opacity", slider=True)
            row.prop(canvas, "fbp_gp_canvas_render", text="", toggle=True, icon="RESTRICT_RENDER_OFF")

            row = top.row(align=True)
            row.label(
                text=(f"Linked to {rig.name}" if linked else "Free / Independent"),
                icon="LINKED" if linked else "UNLINKED",
            )
            relink = row.operator(
                "fbp.link_grease_pencil_canvas",
                text="",
                icon="LINKED" if linked else "UNLINKED",
            )
            relink.canvas_name = canvas.name

            section_gap(layout)
            alignment = layout.box()
            configure_layout(alignment)
            section_header(
                alignment,
                "Plane Link" if linked else "World Placement",
                icon="LINKED" if linked else "WORLD",
            )
            if linked:
                alignment.prop(canvas, "fbp_gp_attachment_mode", text="Attachment")
                row = alignment.row(align=True)
                row.prop(canvas, "fbp_gp_canvas_distance", text="Distance")
                row.prop(canvas, "fbp_gp_canvas_scale", text="Scale")
                row = alignment.row(align=True)
                row.prop(canvas, "fbp_gp_canvas_offset_x", text="Offset X")
                row.prop(canvas, "fbp_gp_canvas_offset_y", text="Y")
                timing = alignment.row(align=True)
                timing.operator("fbp.gp_create_missing_drawings", text="Match Empty Keyframes", icon="KEYFRAME").mode = "BLANK"
                timing.operator("fbp.gp_match_plane_timing", text="Align Existing", icon="TIME")
            else:
                hint_row(alignment, "Transform the object normally in the viewport", icon="INFO")
                alignment.prop(canvas, "fbp_gp_canvas_lock_transform", text="Lock Transform")
            section_gap(layout)
            _draw_gp_52_material_settings(layout, canvas)
            return

        draw_gp_mask_settings_ui(layout, context, canvas)


def draw_gp_canvas_layer_ui(layout, context, canvas=None):
    """Draw GP controls as part of the selected Layer settings, not a panel."""
    canvas = canvas or _active_canvas(context)
    if canvas is None:
        layout.operator("fbp.add_grease_pencil_canvas", text="Add Grease Pencil Layer", **ui_icon_kwargs("menu.gp_layer", fallback="menu.gp_layer"))
        return
    if is_gp_mask_canvas(canvas):
        note = layout.box()
        note.label(text="Grease Pencil Mask", **ui_label_icon_kwargs("menu.gp_layer", fallback="menu.gp_layer"))
        note.label(text="Edit mask settings in Modifiers", icon="MODIFIER")
        return
    # Reuse the tested panel drawing implementations through lightweight UI
    # proxies. The panel classes remain implementation details and are not
    # registered, so Blender exposes one integrated Layer workflow only.
    FBP_PT_GreasePencilCanvas.draw(_FBPLayoutProxy(layout), context)
    if not is_gp_drawing_canvas(canvas):
        return
    workflow = layout.box()
    workflow_open = bool(getattr(canvas, "fbp_gp_ui_show_workflow", False))
    workflow.prop(
        canvas, "fbp_gp_ui_show_workflow", text="Drawing Tools", emboss=False,
        icon="DOWNARROW_HLT" if workflow_open else "RIGHTARROW_THIN",
    )
    if not workflow_open:
        return
    try:
        from .grease_pencil_workflow import (
            FBP_PT_GreasePencilInkWorkflow,
            FBP_PT_GreasePencilTiming,
        )
        sections = (
            ("fbp_gp_ui_show_ink", "Ink Over Image", "BRUSH_DATA", FBP_PT_GreasePencilInkWorkflow),
            ("fbp_gp_ui_show_timing", "Drawing Timing", "KEYFRAME", FBP_PT_GreasePencilTiming),
        )
        for property_name, label, icon, panel in sections:
            box = layout.box()
            opened = bool(getattr(canvas, property_name, False))
            header = box.row(align=True)
            header.prop(
                canvas, property_name, text=label, emboss=False,
                icon="DOWNARROW_HLT" if opened else "RIGHTARROW_THIN",
            )
            header.label(text="", icon=icon)
            if opened:
                panel.draw(_FBPLayoutProxy(box), context)
        from .grease_pencil_limited_loop import FBP_PT_GreasePencilLimitedLoop
        box = layout.box()
        opened = bool(getattr(canvas, "fbp_gp_ui_show_loop", False))
        header = box.row(align=True)
        header.prop(
            canvas, "fbp_gp_ui_show_loop", text="Limited Loop Blocks", emboss=False,
            icon="DOWNARROW_HLT" if opened else "RIGHTARROW_THIN",
        )
        header.label(text="", icon="PREVIEW_RANGE")
        if opened:
            FBP_PT_GreasePencilLimitedLoop.draw(_FBPLayoutProxy(box), context)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not draw integrated Grease Pencil workflow", exc)


def _iter_updated_canvas_events(depsgraph, scene=None, updates=None):
    """Yield canvases affected by meaningful geometry dependencies.

    Each yielded tuple is ``(canvas, sync_needed, dependency_refresh_needed,
    sensitivity_refresh_needed, drawing_data_updated)``. Pure Grease Pencil
    drawing edits should not resync transforms or rebuild dependency indexes on
    every brush sample; they
    only need a raster-mask refresh.  Callers that already materialized
    depsgraph updates can pass them in to avoid walking the update list twice.
    """
    affected = OrderedDict()
    if updates is None:
        updates = getattr(depsgraph, "updates", ()) or ()
    for update in updates:
        updated = _original_datablock(getattr(update, "id", None))
        gp_data_update = _is_grease_pencil_data_block(updated)
        if gp_data_update:
            _clear_gp_exposure_cache(data=updated)
        scene_update = isinstance(updated, bpy.types.Scene)
        candidates = []
        if is_gp_canvas(updated):
            candidates.append(updated)
        dependency_bucket = _GP_DEPENDENCY_CANVAS_INDEX.get(_data_pointer(updated), {})
        candidates.extend(_gp_canvas_bucket_values(dependency_bucket))
        # Rebuild from the data index when a reload invalidated dependencies.
        if gp_data_update and not dependency_bucket:
            candidates.extend(_gp_canvas_bucket_values(_GP_DATA_CANVAS_INDEX.get(_data_pointer(updated), {})))
        for canvas in candidates:
            canvas = _original_datablock(canvas)
            pointer = _canvas_pointer(canvas)
            if not pointer:
                continue
            if not is_gp_canvas(canvas):
                _unregister_runtime_canvas(canvas)
                continue
            meaningful = True
            sync_needed = not gp_data_update
            deps_needed = bool(is_gp_canvas(updated) or (not gp_data_update and not scene_update))
            sensitivity_needed = not gp_data_update
            if scene_update:
                meaningful = _scene_camera_dependency_changed(canvas, updated)
                sync_needed = bool(meaningful)
                deps_needed = bool(meaningful)
                sensitivity_needed = bool(meaningful)
            current = affected.get(pointer)
            if current is None:
                affected[pointer] = [
                    canvas,
                    bool(meaningful),
                    bool(sync_needed),
                    bool(deps_needed),
                    bool(sensitivity_needed),
                    bool(gp_data_update),
                ]
            elif meaningful:
                current[1] = True
                current[2] = bool(current[2] or sync_needed)
                current[3] = bool(current[3] or deps_needed)
                current[4] = bool(current[4] or sensitivity_needed)
                current[5] = bool(current[5] or gp_data_update)
    for (
        canvas,
        meaningful,
        sync_needed,
        deps_needed,
        sensitivity_needed,
        drawing_data_updated,
    ) in affected.values():
        if meaningful:
            yield (
                canvas,
                sync_needed,
                deps_needed,
                sensitivity_needed,
                drawing_data_updated,
            )


def _quarantine_gp_mask_edit_tasks(canvas, scene=None, *, pause_transition=True):
    """Retire every deferred raster task for one GP mask before Edit Mode work."""
    pointer = _canvas_pointer(canvas)
    if not pointer:
        return 0
    retired = cancel_scheduled_prefixes(
        f"grease_pencil.mask_refresh:{pointer}:",
        f"grease_pencil.mask_live_poll:{pointer}:",
        f"grease_pencil.mask_full_quality:{pointer}:",
        f"grease_pencil.mask_post_edit:{pointer}:",
    )
    for key in tuple(_GP_MASK_LIVE_POLL_KEYS):
        if key and key[0] == pointer:
            _GP_MASK_LIVE_POLL_KEYS.pop(key, None)
            _GP_MASK_LIVE_POLL_SIGNATURES.pop(key, None)
    for key in tuple(_GP_MASK_LIVE_FINALIZE_KEYS):
        if key and key[0] == pointer:
            _GP_MASK_LIVE_FINALIZE_KEYS.pop(key, None)
    for key in tuple(_GP_MASK_DIRTY_TIME):
        if key and key[0] == pointer:
            _clear_gp_mask_dirty_note(key)
    if pause_transition:
        _pause_gp_mask_mode_transition(
            canvas, scene, seconds=_GP_MASK_EDIT_ENTRY_GUARD_SECONDS
        )
    return retired


def _gp_mask_mode_transition_preflight(scene=None, *, restore_cursor=True):
    """Very cheap no-RNA-data guard before/post depsgraph evaluation.

    It only checks active object/mode and scheduler state. The pre-handler skips
    cursor restoration because the shared post-handler performs that check once
    after evaluation; this avoids duplicate context/mode reads per brush sample.
    """
    if not (
        _GP_DRAW_CURSOR_STATE
        or _GP_CANVAS_REGISTRY
        or _GP_MASK_STRUCTURAL_EDIT_PENDING
        or _GP_MASK_LIVE_POLL_KEYS
        or _GP_MASK_MODE_TRANSITION_GUARD
    ):
        return False
    if restore_cursor and _GP_DRAW_CURSOR_STATE:
        _restore_gp_draw_cursor_if_needed(scene)
    try:
        active = getattr(bpy.context, "object", None) or getattr(bpy.context, "active_object", None)
    except FBP_DATA_ERRORS:
        active = None
    if not is_gp_canvas(active):
        return False
    try:
        # Keep preflight cheap and no-touch: do not scan mask users here.
        has_mask = bool(is_gp_mask_canvas(active) or getattr(active, "fbp_gp_mask_image", None) is not None)
    except FBP_DATA_ERRORS:
        has_mask = False
    if not has_mask:
        return False
    mode = _gp_canvas_active_mode(active)
    if _gp_mask_is_structural_edit_mode(active):
        key = _gp_mask_dirty_key(active, scene)
        first_entry = key not in _GP_MASK_STRUCTURAL_EDIT_PENDING
        if first_entry:
            _queue_structural_gp_mask_edit(active, scene)
            _quarantine_gp_mask_edit_tasks(active, scene, pause_transition=True)
        return True
    # After leaving Paint Mode there can still be live/final mask timers queued.
    # Pause only while that paint session is still represented by our live-poll
    # key or by an existing transition guard; do not suppress ordinary Object
    # Mode refreshes forever just because the GP mask remains selected.
    if mode == "OBJECT":
        key = _gp_mask_dirty_key(active, scene)
        if key in _GP_MASK_LIVE_POLL_KEYS or _gp_mask_mode_transition_guard_active(active, scene) > 0.0:
            _pause_gp_mask_mode_transition(active, scene, seconds=_GP_MASK_MODE_TRANSITION_SECONDS)
            return True
    return False


def _queue_gp_depsgraph_event(
    canvas,
    scene=None,
    *,
    sync_needed=False,
    deps_needed=False,
    sensitivity_needed=False,
    live_data_update=False,
):
    """Merge one GP depsgraph observation into an idle-loop publication.

    Only integer pointers and booleans survive beyond the handler. This avoids
    retaining RNA wrappers across Undo and prevents transform/material/image
    writes while Blender is still iterating the evaluated graph.
    """
    pointer = _canvas_pointer(canvas)
    if not pointer:
        return False
    target_scene = _scene_for_canvas(canvas, scene)
    scene_pointer = _canvas_pointer(target_scene)
    key = (pointer, scene_pointer)
    state = _GP_PENDING_DEPSGRAPH_EVENTS.get(key)
    if not isinstance(state, dict):
        state = {
            "sync": False,
            "deps": False,
            "sensitivity": False,
            "live_data": False,
        }
        _GP_PENDING_DEPSGRAPH_EVENTS[key] = state
    state["sync"] = bool(state["sync"] or sync_needed)
    state["deps"] = bool(state["deps"] or deps_needed)
    state["sensitivity"] = bool(state["sensitivity"] or sensitivity_needed)
    state["live_data"] = bool(state["live_data"] or live_data_update)

    def _publish():
        if fbp_undo_guard_active() or fbp_render_mutation_blocked():
            return 0.20
        pending = _GP_PENDING_DEPSGRAPH_EVENTS.get(key)
        if not isinstance(pending, dict):
            return None
        current = _gp_canvas_by_pointer(pointer)
        if not is_gp_canvas(current):
            _GP_PENDING_DEPSGRAPH_EVENTS.pop(key, None)
            return None
        refresh_scene = _scene_by_pointer(scene_pointer) or _scene_for_canvas(current)
        live_data = bool(pending.get("live_data", False))
        live_paint = bool(live_data and _gp_live_editing(current))
        structural_edit = bool(live_data and _gp_mask_is_structural_edit_mode(current))
        if structural_edit:
            _GP_PENDING_DEPSGRAPH_EVENTS.pop(key, None)
            _queue_structural_gp_mask_edit(current, refresh_scene)
            return None
        # Live paint already uses copy-on-write image publication and needs a
        # responsive preview. Every other event waits for a quiet depsgraph.
        if not live_paint and not fbp_depsgraph_quiet_for(0.20):
            return 0.08
        pending = _GP_PENDING_DEPSGRAPH_EVENTS.pop(key, pending)
        sync = bool(pending.get("sync", False))
        dependencies = bool(pending.get("deps", False))
        sensitivity = bool(pending.get("sensitivity", False))

        if is_gp_drawing_canvas(current) and (
            sync
            or dependencies
            or (live_data and _gp_cycles_proxy_live_sync_needed(current, refresh_scene))
        ):
            schedule_gp_cycles_proxy_sync(refresh_scene, current)
        if sync:
            sync_canvas_transform(current, scene=refresh_scene)
            _apply_canvas_opacity(current)
        if dependencies:
            _refresh_canvas_dependencies(current, scene=refresh_scene)
        if is_gp_mask_canvas(current) or getattr(current, "fbp_gp_mask_image", None) is not None:
            if sensitivity:
                _canvas_geometry_changes_with_frame(current, refresh=True, scene=refresh_scene)
                _canvas_mask_changes_with_frame(current, refresh=True, scene=refresh_scene)
                _sync_frame_mask_registry(current, refresh_sensitivity=False, scene=refresh_scene)
            live_refresh = bool(
                live_paint and _gp_mask_live_refresh_enabled(current)
            )
            live_poll_started = bool(
                live_refresh
                and _start_gp_mask_live_poll(current, scene=refresh_scene)
            )
            # The persistent live poll owns paint-time invalidation at a bounded
            # cadence. Avoid a second immediate raster task for every depsgraph
            # sample. Non-paint edits and a rejected poll keep the existing path.
            if not live_poll_started:
                fast_delete = bool(
                    live_data
                    and not live_paint
                    and _gp_mask_stroke_count_decreased(current, refresh_scene)
                )
                mark_gp_mask_dirty(
                    current,
                    schedule=True,
                    geometry=True,
                    scene=refresh_scene,
                    immediate=bool(fast_delete),
                    sync_registry=sensitivity,
                )
        return None

    task_name = f"grease_pencil.depsgraph_publish:{pointer}:{scene_pointer}"
    scheduled = bool(
        schedule_once(
            task_name,
            _publish,
            first_interval=0.02,
        )
    )
    if not scheduled and not scheduled_task_pending(task_name):
        _GP_PENDING_DEPSGRAPH_EVENTS.pop(key, None)
    return scheduled


@persistent
def fbp_gp_depsgraph_update_pre(scene, _depsgraph):
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return
    _gp_mask_mode_transition_preflight(scene, restore_cursor=False)


@persistent
def fbp_gp_depsgraph_update(scene, depsgraph, *, updates=None):
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return
    _gp_mask_mode_transition_preflight(scene)
    if not (_GP_CANVAS_REGISTRY or _GP_DATA_CANVAS_INDEX or _FRAME_SENSITIVE_MASKS):
        return
    if updates is None:
        try:
            updates = tuple(getattr(depsgraph, "updates", ()) or ())
        except FBP_DATA_ERRORS:
            return
    if not updates:
        _flush_structural_gp_mask_edits(scene)
        return
    structural_canvases = _structural_edit_canvases()
    if structural_canvases:
        # Native-crash guard. Only relevant GP object/data updates extend the
        # quiet interval; unrelated scene updates no longer postpone previews.
        for canvas in _updated_structural_edit_canvases(updates, structural_canvases):
            _queue_structural_gp_mask_edit(canvas, scene)
        return
    _flush_structural_gp_mask_edits(scene)
    # The event collector invalidates transient indexes, but every RNA write is
    # deferred until Blender has left the depsgraph callback and the graph is
    # quiet. The pending state stores only pointers and primitive flags.
    for (
        canvas,
        sync_needed,
        deps_needed,
        sensitivity_needed,
        live_data_update,
    ) in _iter_updated_canvas_events(depsgraph, scene, updates=updates):
        _queue_gp_depsgraph_event(
            canvas,
            scene,
            sync_needed=sync_needed,
            deps_needed=deps_needed,
            sensitivity_needed=sensitivity_needed,
            live_data_update=live_data_update,
        )


def _fbp_gp_frame_change_publish(scene):
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return
    if not _FRAME_SENSITIVE_MASKS:
        _GP_FRAME_STATE.clear()
        return
    stale = []
    scene_pointer = _canvas_pointer(scene)
    for registry_key in tuple(_FRAME_SENSITIVE_MASKS):
        if not isinstance(registry_key, tuple) or len(registry_key) != 2:
            stale.append(registry_key)
            continue
        pointer, registered_scene_pointer = registry_key
        if scene_pointer and registered_scene_pointer and scene_pointer != registered_scene_pointer:
            continue
        canvas = _gp_canvas_by_pointer(pointer)
        registered_scene = _scene_by_pointer(registered_scene_pointer)
        if not is_gp_canvas(canvas):
            stale.append(registry_key)
            continue
        try:
            target_scene = _scene_for_canvas(canvas, scene or registered_scene)
            if registered_scene_pointer and _canvas_pointer(target_scene) != registered_scene_pointer:
                target_scene = _scene_by_pointer(registered_scene_pointer) or target_scene
            if scene is not None and target_scene is not None and not _same_datablock(scene, target_scene):
                continue
            if not _gp_mask_live_refresh_enabled(canvas) or getattr(canvas, "fbp_gp_mask_image", None) is None:
                stale.append(registry_key)
                continue
        except FBP_DATA_ERRORS:
            stale.append(registry_key)
            continue
        active_scene_pointer = _canvas_pointer(target_scene) or registered_scene_pointer or scene_pointer
        state_key = _canvas_frame_state_key(canvas, target_scene)
        runtime_key = (pointer, active_scene_pointer)
        if _GP_FRAME_STATE.get(runtime_key) == state_key:
            # Held exposure, or reveal before/after its active range: pixels are
            # identical, so avoid a timer, signature hash and image upload.
            continue
        _GP_FRAME_STATE[runtime_key] = state_key
        mark_gp_mask_dirty(
            canvas,
            schedule=True,
            geometry=False,
            scene=target_scene,
            sync_registry=False,
        )
    if not stale:
        return

    stale_pointers = set()
    stale_pairs = set()
    for registry_key in stale:
        _FRAME_SENSITIVE_MASKS.pop(registry_key, None)
        if not isinstance(registry_key, tuple) or not registry_key:
            continue
        pointer = registry_key[0]
        registered_scene_pointer = registry_key[1] if len(registry_key) > 1 else 0
        if registered_scene_pointer:
            stale_pairs.add((pointer, registered_scene_pointer))
        else:
            stale_pointers.add(pointer)

    def stale_runtime_key(key):
        return bool(
            key
            and (
                key[0] in stale_pointers
                or (len(key) > 1 and (key[0], key[1]) in stale_pairs)
            )
        )

    for cache in (_GP_FRAME_STATE, _GP_FRAME_SENSITIVITY_CACHE):
        for key in tuple(cache):
            if stale_runtime_key(key):
                cache.pop(key, None)
    for key in tuple(_GP_MASK_DIRTY_TIME):
        if stale_runtime_key(key):
            _clear_gp_mask_dirty_note(key)


@persistent
def fbp_gp_frame_change(scene, _depsgraph=None):
    """Observe frame changes and publish GP mask state after evaluation."""
    del _depsgraph
    if fbp_undo_guard_active() or fbp_render_mutation_blocked():
        return
    scene_pointer = _canvas_pointer(scene)
    if not scene_pointer:
        return

    def _publish():
        if fbp_undo_guard_active() or fbp_render_mutation_blocked():
            return 0.20
        if not fbp_depsgraph_quiet_for(0.15):
            return 0.06
        target_scene = _scene_by_pointer(scene_pointer)
        if target_scene is not None:
            _fbp_gp_frame_change_publish(target_scene)
        return None

    schedule_once(
        f"grease_pencil.frame_publish:{scene_pointer}",
        _publish,
        first_interval=0.03,
    )


def _schedule_gp_mask_history_refresh(canvas, scene=None):
    """Refresh a GP mask immediately after Undo/Redo without waiting for live debounce."""
    if not is_gp_canvas(canvas):
        return False
    pointer = _canvas_pointer(canvas)
    if not pointer:
        return False
    target_scene = _scene_for_canvas(canvas, scene)
    scene_pointer = _canvas_pointer(target_scene)

    def _refresh_history():
        if fbp_undo_guard_active() or fbp_render_mutation_blocked():
            return 0.25
        if not fbp_depsgraph_quiet_for(0.75):
            return 0.15
        current = _gp_canvas_by_pointer(pointer)
        if not is_gp_canvas(current):
            return None
        refresh_scene = _scene_by_pointer(scene_pointer) or _scene_for_canvas(current, None)
        try:
            current[KEY_MASK_DIRTY] = True
            current[KEY_MASK_GEOMETRY_DIRTY] = True
        except FBP_DATA_ERRORS:
            pass
        # Copy-on-write publishing keeps the image currently sampled by Eevee
        # immutable while this delayed history refresh is rasterized.
        refresh_gp_mask(current, force=False, scene=refresh_scene)
        return None

    return schedule_once(
        f"grease_pencil.mask_history_refresh:{pointer}:{scene_pointer}",
        _refresh_history,
        first_interval=1.0,
    )

def _reindex_gp_canvases_for_history(scene=None):
    """Rebuild only transient GP indexes after Undo/Redo.

    ``load_post`` performs full scene repair, transform sync and sensitivity checks.
    That is intentionally broad for file loads, but too expensive for Ctrl+Z while
    painting a Grease Pencil mask. Undo/Redo usually changes stroke data inside
    existing canvases, so rebuild the lightweight pointer indexes and schedule a
    fast mask refresh for assigned GP masks only.
    """
    _invalidate_gp_binding_cache()
    _invalidate_gp_owner_cache()
    _GP_CANVAS_REGISTRY.clear()
    _GP_PENDING_DEPSGRAPH_EVENTS.clear()
    _GP_DATA_CANVAS_INDEX.clear()
    _GP_CANVAS_DATA_POINTERS.clear()
    _GP_MASK_GEOMETRY_STATE.clear()
    _GP_MASK_DEBUG_STATE.clear()
    _GP_CANVAS_ID_INDEX.clear()
    _clear_gp_exposure_cache()
    scenes = (scene,) if scene is not None else tuple(getattr(bpy.data, "scenes", ()) or ())
    seen = set()
    touched_masks = []
    scene_objects = {}
    for target_scene in scenes:
        if target_scene is None:
            continue
        objects = tuple(getattr(target_scene, "objects", ()) or ())
        for candidate in objects:
            candidate_key = _canvas_pointer(candidate)
            if candidate_key:
                scene_objects[candidate_key] = candidate
        for canvas in objects:  # scene-local scan, not all bpy.data.objects
            key = _canvas_pointer(canvas)
            if not key or key in seen or not is_gp_canvas(canvas):
                continue
            seen.add(key)
            _GP_CANVAS_REGISTRY[key] = str(getattr(canvas, "name", "") or "")
            data_pointer = _data_pointer(getattr(canvas, "data", None))
            if data_pointer:
                _GP_CANVAS_DATA_POINTERS[key] = data_pointer
                _GP_DATA_CANVAS_INDEX.setdefault(data_pointer, {})[key] = str(getattr(canvas, "name", "") or "")
            canvas_id = stable_id(canvas, "MASK") or ensure_mask_identity(canvas)
            if canvas_id:
                _GP_CANVAS_ID_INDEX[canvas_id] = key
            if is_gp_mask_canvas(canvas) or getattr(canvas, "fbp_gp_mask_image", None) is not None:
                touched_masks.append((canvas, target_scene))
    _rebuild_gp_owner_index()
    _rebuild_gp_binding_index(tuple(scene_objects.values()) if scene is not None else None)
    refreshed = 0
    for canvas, target_scene in touched_masks:
        try:
            if not _gp_mask_live_refresh_enabled(canvas):
                continue
            if getattr(canvas, "fbp_gp_mask_image", None) is None:
                continue
            canvas[KEY_MASK_GEOMETRY_DIRTY] = True
        except FBP_DATA_ERRORS:
            continue
        _GP_MASK_STROKE_COUNT_SIGNATURE.pop(_gp_mask_dirty_key(canvas, target_scene), None)
        if mark_gp_mask_dirty(canvas, schedule=False, geometry=True, scene=target_scene, immediate=False, sync_registry=False):
            # History repair only marks the output dirty. Pixel publication is
            # delayed until Blender has completed its post-Undo viewport sync.
            _gp_mask_stroke_count_decreased(canvas, target_scene)
            _schedule_gp_mask_history_refresh(canvas, target_scene)
            refreshed += 1
    return refreshed


def _deferred_gp_history_reindex():
    try:
        scene = getattr(getattr(bpy, "context", None), "scene", None)
        if _reindex_gp_canvases_for_history(scene) <= 0:
            _reindex_gp_canvases_for_history(None)
    except FBP_DATA_ERRORS:
        _fbp_gp_load_post_rebuild(None)
    return None


def schedule_gp_history_reindex(*, first_interval=0.10):
    """Queue GP history repair only from the shared post-Undo idle path."""
    return bool(
        schedule_once(
            "fbp_gp_history_reindex",
            _deferred_gp_history_reindex,
            first_interval=max(0.05, float(first_interval)),
        )
    )


def _deferred_gp_startup_bootstrap():
    if not fbp_main_data_ready("scenes", "objects", "collections"):
        return 0.10
    _fbp_gp_load_post_rebuild(None)
    return None


@persistent
def fbp_gp_load_post(_dummy):
    # Background snapshots are rendered immediately after load. Avoid queuing a
    # broad authoring/bootstrap task that could wake during the native render;
    # the render guard and frame handlers resolve GP canvases scene-locally.
    if bool(getattr(bpy.app, "background", False)):
        return
    schedule_once(
        "fbp_gp_startup_bootstrap",
        _deferred_gp_startup_bootstrap,
        first_interval=0.05,
    )


def _fbp_gp_load_post_rebuild(_dummy):
    if not fbp_main_data_ready("scenes", "objects", "collections"):
        return 0.10
    clear_grease_pencil_runtime_caches()
    # Loaded canvases are expected to be linked to a Scene. Walk scene objects
    # once and deduplicate shared objects instead of scanning every datablock in
    # bpy.data.objects, which also keeps this callback safe during Main swaps.
    seen = set()
    seen_ids = {}
    seen_mask_images = {}
    scenes = tuple(getattr(bpy.data, "scenes", ()) or ())
    for scene in scenes:
        for canvas in tuple(getattr(scene, "objects", ()) or ()):
            key = _canvas_pointer(canvas)
            if not key or key in seen:
                continue
            seen.add(key)
            if not is_gp_canvas(canvas):
                continue
            rig = gp_canvas_owner(canvas)
            kind = gp_canvas_kind(canvas)
            if rig is None and kind == "MASK":
                _register_runtime_canvas(canvas)
                continue

            canvas_id = stable_id(canvas, "MASK") or ensure_mask_identity(canvas)
            previous = seen_ids.get(canvas_id)
            if previous is not None and not _same_datablock(previous, canvas):
                canvas_id = assign_stable_id(canvas, "MASK", new_stable_id("MASK"))
            seen_ids[canvas_id] = canvas

            if kind == "MASK":
                try:
                    image = getattr(canvas, "fbp_gp_mask_image", None)
                except FBP_DATA_ERRORS:
                    image = None
                image_pointer = _canvas_pointer(image)
                if image_pointer:
                    previous_canvas = seen_mask_images.get(image_pointer)
                    if previous_canvas is not None and not _same_datablock(previous_canvas, canvas):
                        fbp_set_rna_property_silent(canvas, "fbp_gp_mask_image", None)
                        try:
                            canvas[KEY_MASK_IMAGE_NAME] = ""
                            canvas[KEY_MASK_DIRTY] = True
                        except FBP_DATA_ERRORS:
                            pass
                    else:
                        seen_mask_images[image_pointer] = canvas

            _tag_canvas(canvas, rig, kind=kind)
            try:
                canvas.use_grease_pencil_lights = False
                if kind == "DRAWING" and getattr(canvas, "data", None) is not None:
                    canvas.data.stroke_depth_order = "3D"
            except FBP_DATA_ERRORS:
                pass
            _ensure_gp_layer(canvas)
            _apply_canvas_opacity(canvas)
            sync_canvas_transform(canvas, scene=scene)
            _refresh_canvas_dependencies(canvas, scene=scene)
            _canvas_geometry_changes_with_frame(canvas, refresh=True, scene=scene)
            _canvas_mask_changes_with_frame(canvas, refresh=True, scene=scene)
            _sync_frame_mask_registry(canvas, refresh_sensitivity=False, scene=scene)
            try:
                canvas[KEY_MASK_GEOMETRY_DIRTY] = True
            except FBP_DATA_ERRORS:
                pass
            mark_gp_mask_dirty(canvas, schedule=True, geometry=True, scene=scene)
            _sync_canvas_mask_bindings(canvas)
    context = getattr(bpy, "context", None)
    context_scene = getattr(context, "scene", None) if context is not None else None
    context_view_layer = getattr(context, "view_layer", None) if context is not None else None
    context_active = (
        getattr(getattr(context_view_layer, "objects", None), "active", None)
        if context_view_layer is not None else None
    )
    for loaded_scene in scenes:
        sync_gp_mask_interaction_state(
            context=context if loaded_scene is context_scene else None,
            scene=loaded_scene,
            active=context_active if loaded_scene is context_scene else None,
        )
    cleanup_gp_cycles_proxies()
    for proxy_scene in tuple(getattr(bpy.data, "scenes", ()) or ()):
        schedule_gp_cycles_proxy_sync(proxy_scene, first_interval=0.12)
    _rebuild_gp_owner_index()


def clear_grease_pencil_runtime_caches():
    """Drop Grease Pencil runtime caches before Undo, file load or reload.

    Render visibility backups and the saved 3D Cursor are intentionally excluded:
    their dedicated restore paths must run before those states are discarded.
    """
    global _GP_GEOMETRY_CACHE_BYTES, _GP_DISTANCE_CACHE_BYTES
    global _GP_REVEAL_POSITION_CACHE_BYTES, _GP_RGBA_BUFFER_CACHE_BYTES
    _clear_gp_native_effect_ui_cache()
    _clear_gp_exposure_cache()
    _clear_gp_output_caches()
    _clear_gp_geometry_cache()
    _clear_gp_distance_cache()
    _invalidate_gp_binding_cache()
    _invalidate_gp_owner_cache()
    lifecycle_errors = clear_runtime_collections(globals())
    if lifecycle_errors:
        fbp_warn_once(
            "gp_runtime_state_contract",
            "Grease Pencil runtime state contract is incomplete: " + ", ".join(lifecycle_errors),
        )
    _prune_gp_mask_retired_images()


def audit_gp_canvases(scene, *, repair=False):
    stats = {
        "gp_canvases": 0,
        "gp_masks_assigned": 0,
        "gp_missing_owners": 0,
        "gp_missing_images": 0,
        "gp_stale_masks": 0,
        "gp_repairs": 0,
    }
    issues = []
    warnings = []
    if scene is None:
        return {"stats": stats, "issues": ("No active Scene for Grease Pencil audit",), "warnings": (), "repaired": 0}
    for canvas in tuple(scene.objects):
        if not is_gp_canvas(canvas):
            continue
        stats["gp_canvases"] += 1
        rig = gp_canvas_owner(canvas)
        if rig is None:
            if is_gp_drawing_canvas(canvas):
                # Free Drawing Planes are intentionally independent.
                continue
            stats["gp_missing_owners"] += 1
            issues.append(f"{canvas.name}: Grease Pencil mask has no valid Frame By Plane owner")
            continue
        if repair:
            before = str(canvas.get(KEY_OWNER_NAME, "") or "")
            _tag_canvas(canvas, rig, kind=gp_canvas_kind(canvas))
            sync_canvas_transform(canvas, scene=scene)
            _refresh_canvas_dependencies(canvas, scene=scene)
            stats["gp_repairs"] += int(before != rig.name)
        image = getattr(canvas, "fbp_gp_mask_image", None)
        bindings = gp_mask_bindings(canvas)
        stats["gp_masks_assigned"] += len(bindings)
        if bindings:
            if image is None:
                stats["gp_missing_images"] += 1
                issues.append(f"{canvas.name}: assigned Grease Pencil mask image is missing")
                if repair:
                    generated, changed = refresh_gp_mask(canvas, force=True, scene=scene)
                    image = generated or image
                    stats["gp_repairs"] += int(generated is not None and changed)
            elif bool(canvas.get(KEY_MASK_DIRTY, False)):
                stats["gp_stale_masks"] += 1
                warnings.append(f"{canvas.name}: assigned Grease Pencil mask needs refresh")
                if repair:
                    _generated, changed = refresh_gp_mask(canvas, force=True, scene=scene)
                    stats["gp_repairs"] += int(changed)
            for user_rig, effect_id, slot in bindings:
                try:
                    slot_image = getattr(user_rig, slot["image"], None)
                    slot_source = str(getattr(user_rig, slot["source_type"], "FILE") or "FILE")
                    if slot_image is image and slot_source == "GREASE_PENCIL":
                        continue
                    issues.append(
                        f"{user_rig.name}: {effect_id} Grease Pencil mask binding is inconsistent"
                    )
                    if repair and image is not None:
                        setattr(user_rig, slot["image"], image)
                        setattr(user_rig, slot["source_type"], "GREASE_PENCIL")
                        stats["gp_repairs"] += 1
                except FBP_DATA_ERRORS:
                    continue
    return {
        "stats": stats,
        "issues": tuple(dict.fromkeys(issues)),
        "warnings": tuple(dict.fromkeys(warnings)),
        "repaired": int(stats["gp_repairs"]),
    }


def _remove_handler_by_name(handler_list, name):
    return remove_handlers_by_name(
        handler_list,
        name,
        module_suffix="grease_pencil_bridge",
    )


def _register_handlers():
    _remove_handler_by_name(bpy.app.handlers.depsgraph_update_pre, "fbp_gp_depsgraph_update_pre")
    _remove_handler_by_name(bpy.app.handlers.depsgraph_update_post, "fbp_gp_depsgraph_update")
    _remove_handler_by_name(bpy.app.handlers.frame_change_post, "fbp_gp_frame_change")
    _remove_handler_by_name(bpy.app.handlers.load_post, "fbp_gp_load_post")
    _remove_handler_by_name(bpy.app.handlers.undo_post, "fbp_gp_undo_redo_post")
    _remove_handler_by_name(bpy.app.handlers.redo_post, "fbp_gp_undo_redo_post")
    for handler_list in (bpy.app.handlers.render_init, bpy.app.handlers.render_pre):
        _remove_handler_by_name(handler_list, "fbp_gp_cycles_render_pre")
        _remove_handler_by_name(handler_list, "fbp_gp_cycles_render_setup")
    for handler_list in (bpy.app.handlers.render_cancel, bpy.app.handlers.render_complete):
        _remove_handler_by_name(handler_list, "fbp_gp_cycles_render_complete")
    is_background = bool(getattr(bpy.app, "background", False))
    if not is_background:
        if not append_handler_once(
            bpy.app.handlers.depsgraph_update_pre,
            fbp_gp_depsgraph_update_pre,
            module_suffix="grease_pencil_bridge",
        ):
            raise RuntimeError("Could not register the Grease Pencil depsgraph pre-handler")
        # Post-update work is dispatched by scene_sync through one shared
        # depsgraph update snapshot. The pre-handler remains standalone because
        # it protects Grease Pencil Edit Mode before evaluation begins.
    if not append_handler_once(
        bpy.app.handlers.frame_change_post,
        fbp_gp_frame_change,
        module_suffix="grease_pencil_bridge",
    ):
        raise RuntimeError("Could not register the Grease Pencil frame handler")
    if not is_background and not append_handler_once(
        bpy.app.handlers.load_post,
        fbp_gp_load_post,
        module_suffix="grease_pencil_bridge",
    ):
        raise RuntimeError("Could not register the Grease Pencil load handler")
    # History repair is scheduled by handlers.fbp_deferred_post_undo_sync after
    # the shared Undo guard and Eevee image-material grace period have ended.


def _unregister_handlers():
    _restore_gp_cycles_render_state()
    _remove_handler_by_name(bpy.app.handlers.depsgraph_update_pre, "fbp_gp_depsgraph_update_pre")
    _remove_handler_by_name(bpy.app.handlers.depsgraph_update_post, "fbp_gp_depsgraph_update")
    _remove_handler_by_name(bpy.app.handlers.frame_change_post, "fbp_gp_frame_change")
    _remove_handler_by_name(bpy.app.handlers.load_post, "fbp_gp_load_post")
    _remove_handler_by_name(bpy.app.handlers.undo_post, "fbp_gp_undo_redo_post")
    _remove_handler_by_name(bpy.app.handlers.redo_post, "fbp_gp_undo_redo_post")
    for handler_list in (bpy.app.handlers.render_init, bpy.app.handlers.render_pre):
        _remove_handler_by_name(handler_list, "fbp_gp_cycles_render_pre")
        _remove_handler_by_name(handler_list, "fbp_gp_cycles_render_setup")
    for handler_list in (bpy.app.handlers.render_cancel, bpy.app.handlers.render_complete):
        _remove_handler_by_name(handler_list, "fbp_gp_cycles_render_complete")


def _canvas_selected_get(self):
    """Selection proxy used by the Layer List so GP rows behave like FBP planes."""
    try:
        return bool(self and self.select_get())
    except FBP_DATA_ERRORS:
        return False


def _canvas_selected_set(self, value):
    """Additive GP canvas selection for native UIList click-hold painting.

    Mesh layer rows expose selection through a BooleanProperty on the layer item.
    GP canvas rows have no layer item, so this object-level proxy keeps the same
    compact Layer List behavior without using an operator button.
    """
    canvas = self
    if canvas is None:
        return
    try:
        if not is_gp_canvas(canvas):
            return
    except FBP_DATA_ERRORS:
        return
    selected = bool(value)
    context = getattr(bpy, "context", None)
    try:
        if context is not None and str(getattr(context, "mode", "OBJECT") or "OBJECT") != "OBJECT":
            if bpy.ops.object.mode_set.poll():
                bpy.ops.object.mode_set(mode="OBJECT")
    except FBP_DATA_ERRORS:
        pass
    try:
        if selected:
            if bool(getattr(canvas, "hide_select", False)):
                canvas.hide_select = False
            canvas.hide_set(False)
            if hasattr(canvas, "fbp_gp_canvas_visible"):
                fbp_set_rna_property_silent(canvas, "fbp_gp_canvas_visible", True)
        canvas.select_set(selected)
        if selected and context is not None and getattr(context, "view_layer", None) is not None:
            try:
                context.view_layer.objects.active = canvas
            except FBP_DATA_ERRORS:
                pass
        sync_gp_mask_interaction_state(
            context=context,
            scene=getattr(context, "scene", None) if context is not None else None,
            active=canvas if selected else None,
        )
    except FBP_DATA_ERRORS:
        pass


def _canvas_locked_get(self):
    """Lock proxy for GP UIList rows so the icon redraws like normal FBP layers."""
    try:
        return bool(getattr(self, "hide_select", False))
    except FBP_DATA_ERRORS:
        return False


def _canvas_kind_update(_self, _context):
    """Invalidate scene indexes after a Drawing/Mask role change.

    Kind changes are rare structural edits. Clearing the bounded primitive
    index here keeps panel visibility immediate without forcing a full scene
    scan from every UI redraw.
    """
    try:
        invalidate_scene_index()
    except FBP_DATA_ERRORS:
        pass


def _canvas_locked_set(self, value):
    canvas = self
    try:
        if canvas is None or not is_gp_canvas(canvas):
            return
        locked = bool(value)
        canvas.hide_select = locked
        if locked and bool(canvas.select_get()):
            canvas.select_set(False)
    except FBP_DATA_ERRORS:
        pass


def _register_properties():
    bpy.types.Object.fbp_gp_canvas_owner = PointerProperty(
        name="Frame By Plane Owner",
        description="Frame By Plane layer controlled by this Grease Pencil canvas",
        type=bpy.types.Object,
    )
    bpy.types.Object.fbp_gp_canvas = PointerProperty(
        name="Grease Pencil Canvas",
        description="Visible Grease Pencil Drawing Plane linked to this Frame By Plane layer",
        type=bpy.types.Object,
    )
    bpy.types.Object.fbp_gp_canvas_kind = EnumProperty(
        name="Grease Pencil Type",
        description="Drawing Planes appear in Layers and accept native GP effects; masks remain internal to mask slots",
        items=CANVAS_KIND_ITEMS,
        default="DRAWING",
        update=_canvas_kind_update,
    )
    bpy.types.Object.fbp_gp_attachment_mode = EnumProperty(description='Operation mode for this Grease Pencil workflow. Example: choose whether the command adds, removes, previews, repairs or applies settings.',
        name="Canvas Attachment",
        items=ATTACHMENT_ITEMS,
        default="PLANE",
        update=_attachment_mode_update,
    )
    bpy.types.Object.fbp_gp_canvas_distance = FloatProperty(
        name="Canvas Distance",
        description="Signed depth offset from a linked plane; negative places the canvas behind it. Camera attachment uses the absolute distance",
        default=0.003,
        soft_min=-5.0,
        soft_max=5.0,
        precision=4,
        update=_canvas_property_update,
    )
    bpy.types.Object.fbp_gp_canvas_offset_x = FloatProperty(description='Offset value for positioning the effect, mask, helper or generated element relative to its default placement.', name="Offset X", default=0.0, soft_min=-2.0, soft_max=2.0, update=_canvas_property_update)
    bpy.types.Object.fbp_gp_canvas_offset_y = FloatProperty(description='Offset value for positioning the effect, mask, helper or generated element relative to its default placement.', name="Offset Y", default=0.0, soft_min=-2.0, soft_max=2.0, update=_canvas_property_update)
    bpy.types.Object.fbp_gp_canvas_scale = FloatProperty(description='Size control for the generated result. Higher values increase visual coverage and may increase viewport cost.', name="Canvas Scale", default=1.0, min=0.001, soft_max=4.0, update=_canvas_property_update)
    bpy.types.Object.fbp_gp_canvas_visible = BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Visible", default=True, update=_canvas_visibility_update)
    bpy.types.Object.fbp_gp_canvas_selected = BoolProperty(name="Selected", description="Select this Grease Pencil canvas from the Frame By Plane Layer List", get=_canvas_selected_get, set=_canvas_selected_set, options={"SKIP_SAVE"})
    bpy.types.Object.fbp_gp_canvas_locked = BoolProperty(name="Locked", description="Lock this Grease Pencil canvas from the Frame By Plane Layer List", get=_canvas_locked_get, set=_canvas_locked_set, options={"SKIP_SAVE"})
    bpy.types.Object.fbp_gp_canvas_opacity = FloatProperty(name="Visibility", description="Viewport visibility of the editable Grease Pencil canvas", default=0.5, min=0.0, max=1.0, subtype="FACTOR", update=_canvas_opacity_update)
    bpy.types.Object.fbp_gp_ui_show_ink = BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Ink Workflow", default=False, options={"SKIP_SAVE"})
    bpy.types.Object.fbp_gp_ui_show_timing = BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Drawing Timing", default=False, options={"SKIP_SAVE"})
    bpy.types.Object.fbp_gp_ui_show_loop = BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Limited Loop", default=False, options={"SKIP_SAVE"})
    bpy.types.Object.fbp_gp_ui_show_advanced = BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Mask Settings", default=False, options={"SKIP_SAVE"})
    bpy.types.Object.fbp_gp_ui_show_workflow = BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Drawing Tools", default=False, options={"SKIP_SAVE"})
    bpy.types.Object.fbp_gp_ui_show_unavailable_effects = BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Frame By Plane Image Effects", default=False, options={"SKIP_SAVE"})
    bpy.types.Object.fbp_gp_ui_show_effect_library = BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Effect Library", default=False, options={"SKIP_SAVE"})
    bpy.types.Object.fbp_gp_ui_show_effect_settings = BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Effect Settings", default=True, options={"SKIP_SAVE"})
    bpy.types.Object.fbp_gp_ui_show_material_52 = BoolProperty(
        name="Stroke Material",
        description="Show Blender 5.2 Dots and Squares placement/randomization controls for the active Grease Pencil material",
        default=False,
        options={"SKIP_SAVE"},
    )
    bpy.types.Object.fbp_gp_canvas_render = BoolProperty(description='Include this Grease Pencil Drawing Plane in final renders.', name="Render", default=False, update=_canvas_visibility_update)
    bpy.types.Object.fbp_gp_cycles_proxy = PointerProperty(
        name="Cycles Render Proxy",
        description="Internal mesh proxy used to depth-compose Grease Pencil with Frame By Plane image layers in Cycles",
        type=bpy.types.Object,
        options={'HIDDEN'},
    )
    bpy.types.Object.fbp_gp_canvas_lock_transform = BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Lock Transform", default=True, update=_canvas_visibility_update)
    bpy.types.Object.fbp_gp_onion_skin = BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Onion Skin", default=True, update=_onion_update)
    bpy.types.Object.fbp_gp_reference_opacity = FloatProperty(
        name="Reference Opacity",
        description="Opacity of the linked Frame By Plane image while drawing",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_reference_opacity_update,
    )
    bpy.types.Object.fbp_gp_mask_source = EnumProperty(description='Choose the Grease Pencil Mask Source option for this Grease Pencil workflow. Hover each entry for the specific mode when Blender exposes enum item help.', name="Mask Source", items=MASK_SOURCE_ITEMS, default="AUTO", update=_mask_geometry_property_update)
    bpy.types.Object.fbp_gp_mask_invert = BoolProperty(description='Toggle this option for the current Grease Pencil workflow. Disabled keeps the data available but prevents this behavior from being applied.', name="Invert", default=False, update=_mask_output_property_update)
    bpy.types.Object.fbp_gp_mask_feather = FloatProperty(description='Soft transition width around the edge of the mask, gradient, threshold or shadow.', name="Blur", default=0.0, min=0.0, max=1.0, soft_max=0.25, subtype="FACTOR", update=_mask_raster_property_update)
    bpy.types.Object.fbp_gp_mask_expand = FloatProperty(description='Grease Pencil Mask Expand value used by the current Grease Pencil workflow. Changes are applied only to compatible Frame By Plane data.', name="Expand", default=DEFAULT_GP_MASK_EXPAND, min=-1.0, max=1.0, soft_min=-0.25, soft_max=0.25, update=_mask_raster_property_update)
    bpy.types.Object.fbp_gp_mask_opacity = FloatProperty(description='Blend strength of this control. 0 disables its visual contribution; 1 applies the full registered effect.', name="Mask Opacity", default=1.0, min=0.0, max=1.0, subtype="FACTOR", update=_mask_output_property_update)
    bpy.types.Object.fbp_gp_mask_threshold = FloatProperty(description='Number of frames to hold this state before the next drawing, image or procedural step is evaluated.', name="Threshold", default=0.5, min=0.0, max=1.0, subtype="FACTOR", update=_mask_raster_property_update)
    bpy.types.Object.fbp_gp_mask_stroke_width = FloatProperty(description='Size control for the generated result. Higher values increase visual coverage and may increase viewport cost.', name="Line Radius", default=DEFAULT_GP_MASK_STROKE_WIDTH, min=DEFAULT_GP_MASK_STROKE_WIDTH, max=2.0, soft_max=0.25, update=_mask_geometry_property_update)
    bpy.types.Object.fbp_gp_mask_auto_radius = BoolProperty(name="Auto Radius", description="Derive line radius from Grease Pencil point pressure/radius", default=True, update=_mask_geometry_property_update)
    bpy.types.Object.fbp_gp_mask_quality = EnumProperty(description='Choose the final Grease Pencil Mask raster quality. Kept at 1024px by default.', name="Mask Quality", items=QUALITY_ITEMS, default=DEFAULT_GP_MASK_QUALITY, update=_mask_raster_property_update)
    bpy.types.Object.fbp_gp_mask_preview_quality = EnumProperty(description='Live preview quality while drawing the Grease Pencil Mask. The final mask still resolves at 1024px.', name="Preview Quality", items=PREVIEW_QUALITY_ITEMS, default=DEFAULT_GP_MASK_PREVIEW_QUALITY)
    bpy.types.Object.fbp_gp_reveal_enabled = BoolProperty(
        name="Reveal",
        description="Animate the generated Grease Pencil mask with a directional reveal or erase",
        default=False,
        update=_mask_output_property_update,
    )
    bpy.types.Object.fbp_gp_reveal_mode = EnumProperty(description='Operation mode for this Grease Pencil workflow. Example: choose whether the command adds, removes, previews, repairs or applies settings.', name="Reveal Mode", items=REVEAL_MODE_ITEMS, default="REVEAL", update=_mask_output_property_update)
    bpy.types.Object.fbp_gp_reveal_start = IntProperty(name="Start", description="Timeline frame where the reveal begins", default=1, update=_mask_output_property_update)
    bpy.types.Object.fbp_gp_reveal_end = IntProperty(name="End", description="Timeline frame where the reveal reaches its final state", default=24, update=_mask_output_property_update)
    bpy.types.Object.fbp_gp_reveal_direction = EnumProperty(description='Direction used by the action. Example: UP/DOWN for stack movement, or positive/negative for directional controls.', name="Direction", items=REVEAL_DIRECTION_ITEMS, default="LEFT_RIGHT", update=_mask_output_property_update)
    bpy.types.Object.fbp_gp_reveal_invert = BoolProperty(name="Invert Direction", description="Invert the generated reveal matte", default=False, update=_mask_output_property_update)
    bpy.types.Object.fbp_gp_reveal_feather = FloatProperty(name="Reveal Feather", description="Soften the moving reveal edge", default=0.05, min=0.0, max=1.0, soft_max=0.25, subtype="FACTOR", update=_mask_output_property_update)
    bpy.types.Object.fbp_gp_reveal_hold = BoolProperty(name="Hold Result", description="Keep the completed reveal or erase after the End frame", default=True, update=_mask_output_property_update)
    bpy.types.Object.fbp_gp_mask_image = PointerProperty(name="Grease Pencil Mask Image", type=bpy.types.Image)
    bpy.types.Object.fbp_imported_mask_image = PointerProperty(
        name="Mask Image Data-Block",
        description="In-memory mask image used instead of a file path, including Grease Pencil masks",
        type=bpy.types.Image,
        update=_imported_mask_pointer_update,
    )
    bpy.types.Object.fbp_imported_mask_source_type = EnumProperty(description='Operation mode for this Grease Pencil workflow. Example: choose whether the command adds, removes, previews, repairs or applies settings.',
        name="Mask Source Type",
        items=(("FILE", "Image File", "Imported mask path"), ("GREASE_PENCIL", "Grease Pencil", "Generated Grease Pencil mask image")),
        default="FILE",
    )
    bpy.types.Object.fbp_gp_mask_canvas = PointerProperty(
        name="Grease Pencil Mask Canvas",
        description="Grease Pencil canvas currently assigned to this layer's raster mask effect",
        type=bpy.types.Object,
        update=_imported_mask_canvas_pointer_update,
    )
    bpy.types.Object.fbp_gp_mask_slot_2_canvas = PointerProperty(name="Grease Pencil Mask Slot 2 Canvas", description="Grease Pencil canvas assigned to independent mask slot 2", type=bpy.types.Object, update=_gp_mask_slot_2_canvas_pointer_update)
    bpy.types.Object.fbp_gp_mask_slot_2_image = PointerProperty(name="Grease Pencil Mask Slot 2 Image", type=bpy.types.Image, update=_gp_mask_slot_2_pointer_update)
    bpy.types.Object.fbp_gp_mask_slot_2_source_type = EnumProperty(description='Operation mode for this Grease Pencil workflow. Example: choose whether the command adds, removes, previews, repairs or applies settings.', name="Grease Pencil Mask Slot 2 Source", items=(("FILE", "Image File", "Image file"), ("GREASE_PENCIL", "Grease Pencil", "Generated Grease Pencil image")), default="GREASE_PENCIL")
    bpy.types.Object.fbp_gp_mask_slot_3_canvas = PointerProperty(name="Grease Pencil Mask Slot 3 Canvas", description="Grease Pencil canvas assigned to independent mask slot 3", type=bpy.types.Object, update=_gp_mask_slot_3_canvas_pointer_update)
    bpy.types.Object.fbp_gp_mask_slot_3_image = PointerProperty(name="Grease Pencil Mask Slot 3 Image", type=bpy.types.Image, update=_gp_mask_slot_3_pointer_update)
    bpy.types.Object.fbp_gp_mask_slot_3_source_type = EnumProperty(description='Operation mode for this Grease Pencil workflow. Example: choose whether the command adds, removes, previews, repairs or applies settings.', name="Grease Pencil Mask Slot 3 Source", items=(("FILE", "Image File", "Image file"), ("GREASE_PENCIL", "Grease Pencil", "Generated Grease Pencil image")), default="GREASE_PENCIL")
    bpy.types.Object.fbp_gp_mask_slot_4_canvas = PointerProperty(name="Grease Pencil Mask Slot 4 Canvas", description="Grease Pencil canvas assigned to independent mask slot 4", type=bpy.types.Object, update=_gp_mask_slot_4_canvas_pointer_update)
    bpy.types.Object.fbp_gp_mask_slot_4_image = PointerProperty(name="Grease Pencil Mask Slot 4 Image", type=bpy.types.Image, update=_gp_mask_slot_4_pointer_update)
    bpy.types.Object.fbp_gp_mask_slot_4_source_type = EnumProperty(description='Operation mode for this Grease Pencil workflow. Example: choose whether the command adds, removes, previews, repairs or applies settings.', name="Grease Pencil Mask Slot 4 Source", items=(("FILE", "Image File", "Image file"), ("GREASE_PENCIL", "Grease Pencil", "Generated Grease Pencil image")), default="GREASE_PENCIL")


def _unregister_properties():
    return unregister_type_properties(bpy.types.Object, _RNA_PROPERTIES)


class FBP_OT_SafeGPMaskShrinkFatten(Operator):
    """Guard FBP timers, then pass the native radius shortcut to Blender."""

    bl_idname = "fbp.safe_gp_mask_shrink_fatten"
    bl_label = "Grease Pencil Mask Shrink/Fatten"
    bl_description = f"Safely pass {alt_shortcut_label('S')} to native Grease Pencil Shrink/Fatten and refresh the mask afterward"
    bl_options = {"INTERNAL"}

    def invoke(self, context, _event):
        canvas = getattr(context, "object", None)
        try:
            is_mask = bool(canvas and is_gp_mask_canvas(canvas))
        except FBP_DATA_ERRORS:
            is_mask = False
        if not is_mask or not _gp_mask_is_structural_edit_mode(canvas):
            return {"PASS_THROUGH"}
        scene = getattr(context, "scene", None)
        _quarantine_gp_mask_edit_tasks(canvas, scene)
        _queue_structural_gp_mask_edit(canvas, scene)
        # PASS_THROUGH lets Blender's original radius-shortcut mapping run. The queued
        # quiet-time preview observes its published radius values afterward.
        return {"PASS_THROUGH"}


def _unregister_gp_mask_edit_keymaps():
    unregister_keymap_items(_GP_MASK_EDIT_KEYMAPS)


def _register_gp_mask_edit_keymaps():
    _unregister_gp_mask_edit_keymaps()
    if not shortcut_enabled('shortcut_gp_alt_s_guard'):
        return False

    candidates = (
        'Grease Pencil Edit Mode',
        'Grease Pencil Stroke Edit Mode',
        'Grease Pencil',
    )
    # Register only keymaps that Blender itself exposes. Creating all historical
    # names can make one radius-shortcut event run the same pass-through guard twice.
    keymap_names = native_keymap_names(candidates)
    if not keymap_names:
        keymap_names = (candidates[0],)

    registered = False
    for name in keymap_names:
        keymap = addon_keymap(name, fallback_space_type='EMPTY', fallback_region_type='WINDOW')
        if keymap is None:
            continue
        remove_matching_keymap_items(
            keymap,
            lambda item: str(getattr(item, 'idname', '') or '')
            == FBP_OT_SafeGPMaskShrinkFatten.bl_idname,
        )
        try:
            item = keymap.keymap_items.new(
                FBP_OT_SafeGPMaskShrinkFatten.bl_idname,
                type='S',
                value='PRESS',
                alt=True,
            )
            _GP_MASK_EDIT_KEYMAPS.append((keymap, item))
            registered = True
        except FBP_DATA_ERRORS:
            continue
    return registered


def refresh_keymaps():
    """Public hook used by Add-on Preferences after a shortcut toggle changes."""
    return refresh_keymap_registration(_register_gp_mask_edit_keymaps)


classes = (
    FBP_OT_SafeGPMaskShrinkFatten,
    FBP_MT_GPNativeEffects,
    FBP_OT_ToggleGPNativeEffectSettings,
    FBP_OT_RepairGPNativeEffectDuplicates,
    FBP_OT_ResetGPNativeEffect,
    FBP_OT_MoveGPNativeEffect,
    FBP_OT_ToggleGPNativeEffect,
    FBP_OT_AddGreasePencilCanvas,
    FBP_OT_LinkGreasePencilCanvas,
    FBP_OT_SelectGreasePencilCanvas,
    FBP_OT_EnterGreasePencilDraw,
    FBP_OT_RefreshGreasePencilMask,
    FBP_OT_BakeGreasePencilMask,
    FBP_OT_UseGreasePencilAsMask,
    FBP_OT_AddGreasePencilMask,
    FBP_OT_AssignGreasePencilMaskToEffect,
    FBP_OT_DetachGreasePencilMaskFromEffect,
    FBP_OT_DetachGreasePencilMask,
    FBP_OT_SelectGreasePencilMaskUsers,
    FBP_OT_RestoreGreasePencilReferenceOpacity,
    FBP_OT_ToggleGPLayersExpanded,
    FBP_OT_SelectGPInternalLayer,
    FBP_OT_ToggleGPInternalLayerMask,
    FBP_OT_SplitGPSingleLayer,
    FBP_OT_SplitGPCanvasLayers,
    FBP_OT_CollapseGPCanvasesToOne,
    FBP_OT_DuplicateSelectedGPCanvases,
    FBP_OT_ToggleGPCanvasSolo,
    FBP_OT_ToggleGPCanvasHoldout,
    FBP_OT_ToggleGPCanvasLockSelect,
    FBP_OT_ToggleGPCanvasVisibility,
    FBP_OT_ToggleGPCanvasClipping,
    FBP_OT_DeleteGreasePencilCanvas,
)


def prepare_shutdown(context=None):
    """Best-effort cleanup before add-on reload/Blender exit.

    Blender 5.2 can crash in internal Brush/CurveMapping teardown when it
    exits or reloads an add-on while a Grease Pencil paint/edit tool is active.
    The add-on cannot fix Blender's internal free path, but it can avoid leaving
    Frame By Plane GP canvases in active paint/edit modes during shutdown.
    """
    try:
        context = context or getattr(bpy, "context", None)
        if context is None:
            return False
        mode = str(getattr(context, "mode", "OBJECT") or "OBJECT")
        active = getattr(getattr(context, "view_layer", None), "objects", None)
        active_obj = getattr(active, "active", None) if active is not None else None
        should_leave = mode != "OBJECT" and (is_gp_canvas(active_obj) or "GREASE_PENCIL" in mode or mode.startswith("PAINT"))
        if not should_leave:
            return True
        try:
            if active_obj is not None:
                active_obj.select_set(True)
        except FBP_DATA_ERRORS:
            pass
        try:
            if bpy.ops.object.mode_set.poll():
                bpy.ops.object.mode_set(mode="OBJECT")
        except FBP_DATA_ERRORS:
            pass
        try:
            if bpy.ops.wm.tool_set_by_id.poll():
                bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
        except FBP_DATA_ERRORS:
            pass
        return str(getattr(context, "mode", "OBJECT") or "OBJECT") == "OBJECT"
    except FBP_DATA_ERRORS:
        return False


def register():
    clear_grease_pencil_runtime_caches()
    properties_registered = False
    classes_registered = False
    try:
        _register_properties()
        properties_registered = True
        is_background = bool(getattr(bpy.app, "background", False))
        # Operators must exist in background mode as well: the LTS runner, farm
        # scripts and command-line project repair all rely on the same public
        # API as the interactive UI. Menus are harmless when no UI is present.
        register_classes(classes)
        classes_registered = True
        _register_handlers()
        if not is_background:
            _register_gp_mask_edit_keymaps()
            # Interactive enable may happen without load_post; defer the full
            # authoring bootstrap until Main is available.
            schedule_once(
                "fbp_gp_startup_bootstrap",
                _deferred_gp_startup_bootstrap,
                first_interval=0.05,
            )
    except Exception:
        _unregister_gp_mask_edit_keymaps()
        _unregister_handlers()
        if classes_registered:
            unregister_classes(classes)
        if properties_registered:
            _unregister_properties()
        else:
            # Property registration is not atomic; remove any prefix that was
            # assigned before Blender raised.
            _unregister_properties()
        raise


def unregister():
    cancel_scheduled_prefixes(*GP_TASK_PREFIXES)
    _restore_all_gp_draw_cursors()
    _unregister_gp_mask_edit_keymaps()
    _unregister_handlers()
    clear_grease_pencil_runtime_caches()
    unregister_classes(classes)
    _unregister_properties()


__all__ = (
    "SERVICE_ID",
    "SERVICE_API_VERSION",
    "CAPABILITIES",
    "service_status",
    "is_gp_canvas", "fbp_is_grease_pencil_object",
    "gp_canvas_owner",
    "gp_canvas_for_rig", "gp_canvases_for_rig",
    "gp_canvas_kind", "is_gp_drawing_canvas", "is_gp_mask_canvas",
    "fbp_gp_effect_backend_matrix", "fbp_gp_effect_support_summary",
    "any_gp_canvas_solo", "clear_gp_canvas_solo",
    "draw_gp_canvas_layer_ui", "draw_gp_mask_settings_ui", "draw_gp_native_effects_ui",
    "gp_mask_canvas_for_rig",
    "gp_mask_bindings", "gp_mask_assignments",
    "refresh_gp_mask",
    "mark_gp_mask_dirty",
    "audit_gp_canvases",
    "gp_internal_layer_icon", "gp_internal_layer_native_mask_active",
)
