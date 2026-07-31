"""Viewport controls for spatial Frame By Plane effect parameters.

The controls are lightweight Empty objects parented to the generated plane.
They are shown only for the active effect, never render, and map their local
transform back to normalized UV or directional effect properties.  The actual
effect properties remain the source of truth, so deleting a helper never damages
an effect and it can be recreated on selection.
"""

from __future__ import annotations

import math
import time

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from mathutils import Matrix, Vector

from .diagnostics import write_diagnostic_report
from .registration import register_classes, remove_handlers_by_name, unregister_classes
from .safe_tasks import schedule_once
from .managed_timers import (
    fbp_register_timer_once,
    fbp_timer_is_registered,
    fbp_unregister_managed_timer,
)

from .runtime import (
    FBP_DATA_ERRORS,
    fbp_render_mutation_blocked,
    fbp_set_rna_property_silent,
    fbp_undo_guard_active,
    fbp_obj_runtime_key,
    fbp_find_id_by_runtime_key,
    fbp_selection_snapshot,
    fbp_invalidate_selection_snapshot,
    fbp_is_grease_pencil_interaction_mode,
    fbp_warn,
)
from .viewport_handles import (
    append_rect_geometry,
    bounds_handle_geometry,
    ensure_viewport_handle_material,
)


SCHEMA_VERSION = 19
KEY_IS_CONTROL = "fbp_is_effect_control"
KEY_SCHEMA = "fbp_effect_control_schema"
KEY_EFFECT_ID = "fbp_effect_control_effect"
KEY_ROLE = "fbp_effect_control_role"
KEY_MODE = "fbp_effect_control_mode"
KEY_OWNER_NAME = "fbp_effect_control_owner"
KEY_SYNC_SIGNATURE = "fbp_effect_control_sync_signature"
KEY_IS_BOUNDS_GUIDE = "fbp_is_crop_extend_bounds_guide"
KEY_GUIDE_OWNER = "fbp_crop_extend_bounds_owner"
KEY_CONTROL_MESH_SIGNATURE = "fbp_effect_control_mesh_signature"
CROP_CLAMP_CONSTRAINT = "FBP Crop / Extend Clamp"
EXTEND_HANDLE_MAX = 1.0
DIRECTION_HANDLE_MIN_SCALE = 0.08
KEY_EXTEND_HANDLE_LIMIT_X = "fbp_extend_handle_limit_x"
KEY_EXTEND_HANDLE_LIMIT_Y = "fbp_extend_handle_limit_y"

_SYNC_GUARD = set()
_CONTROL_NAMES = set()
_GUIDE_NAMES = set()
_PENDING_CONTROL_SIGNATURES = {}
_PENDING_CONTROL_TRANSFORMS = {}
_LAST_SELECTION_SIGNATURE = None
_LAST_SELECTION_CHECK_TIME = 0.0
_LAST_SELECTION_CONTEXT_MODE = str(globals().get("_LAST_SELECTION_CONTEXT_MODE", "") or "")
_DEPSGRAPH_SUPPORT_APIS = None


def _depsgraph_support_apis():
    """Resolve helper predicates once for the high-frequency depsgraph path."""
    global _DEPSGRAPH_SUPPORT_APIS
    if _DEPSGRAPH_SUPPORT_APIS is None:
        from .fbp_index import is_scene_fbp_plane_mesh
        from .object_masks import (
            is_object_mask_bounds_handle,
            is_object_mask_helper,
            schedule_object_mask_bounds_handle_update,
            schedule_object_mask_helper_transform_update,
        )
        _DEPSGRAPH_SUPPORT_APIS = (
            is_object_mask_bounds_handle,
            is_object_mask_helper,
            schedule_object_mask_bounds_handle_update,
            schedule_object_mask_helper_transform_update,
            is_scene_fbp_plane_mesh,
        )
    return _DEPSGRAPH_SUPPORT_APIS


_SELECTION_CHECK_INTERVAL = 0.15
_FBP_PLANE_MESH_KEYS = set()
# Retire the removed negative cache after an in-place extension reload.
globals().pop("_FBP_PLANE_MESH_NEGATIVE_KEYS", None)
_CONTROL_DRIVEN_PROPS_CACHE = globals().get("_CONTROL_DRIVEN_PROPS_CACHE", {})
_SELECTION_VISIBILITY_TIMER_INTERVAL = 0.10
_SELECTION_VISIBILITY_IDLE_INTERVAL = 0.30
_SELECTION_VISIBILITY_STABLE_INTERVAL = 0.65
_SELECTION_VISIBILITY_DEEP_IDLE_INTERVAL = 1.00
_SELECTION_VISIBILITY_EMPTY_INTERVAL = 0.75
_SELECTION_VISIBILITY_EMPTY_GRACE_SECONDS = 3.0
_SELECTION_VISIBILITY_EMPTY_SINCE = globals().get("_SELECTION_VISIBILITY_EMPTY_SINCE", 0.0)
_SELECTION_VISIBILITY_STABLE_TICKS = int(globals().get("_SELECTION_VISIBILITY_STABLE_TICKS", 0) or 0)
_SCENE_SERVICE_CACHE = globals().get("_SCENE_SERVICE_CACHE", {})
if not isinstance(_SCENE_SERVICE_CACHE, dict):
    _SCENE_SERVICE_CACHE = {}
_SCENE_SERVICE_CACHE_TTL = 1.0
_LAST_CONTROL_FULL_SCAN_TIME = globals().get("_LAST_CONTROL_FULL_SCAN_TIME", 0.0)
_LAST_CONTROL_EMPTY_SCAN_TIME = globals().get("_LAST_CONTROL_EMPTY_SCAN_TIME", 0.0)
_CONTROL_FULL_SCAN_INTERVAL = 5.0
_CONTROL_OWNER_CACHE = globals().get("_CONTROL_OWNER_CACHE", {})
if not isinstance(_CONTROL_OWNER_CACHE, dict):
    _CONTROL_OWNER_CACHE = {}
# Scene-object caches retain primitive runtime keys and names only.
_CONTEXT_OBJECTS_CACHE = {}
_CONTEXT_OBJECTS_CACHE_TTL = 0.35


# One source of truth for effects that expose spatial interaction. Modes:
# POINT: normalized UV center; OFFSET: UV offset around 0.5; DIRECTION: Z angle
# and X scale; paired ranges use IN/OUT boundaries plus one CENTER helper.
CONTROL_SPECS = {
    "CROP": (
        {"role": "LEFT", "mode": "CROP_EXTEND", "axis": "X", "props": ("fbp_crop_left",)},
        {"role": "RIGHT", "mode": "CROP_EXTEND", "axis": "X", "props": ("fbp_crop_right",)},
        {"role": "TOP", "mode": "CROP_EXTEND", "axis": "Y", "props": ("fbp_crop_top",)},
        {"role": "BOTTOM", "mode": "CROP_EXTEND", "axis": "Y", "props": ("fbp_crop_bottom",)},
        {"role": "TOP_LEFT", "mode": "CROP_EXTEND", "axis": "XY", "props": ("fbp_crop_left", "fbp_crop_top")},
        {"role": "TOP_RIGHT", "mode": "CROP_EXTEND", "axis": "XY", "props": ("fbp_crop_right", "fbp_crop_top")},
        {"role": "BOTTOM_LEFT", "mode": "CROP_EXTEND", "axis": "XY", "props": ("fbp_crop_left", "fbp_crop_bottom")},
        {"role": "BOTTOM_RIGHT", "mode": "CROP_EXTEND", "axis": "XY", "props": ("fbp_crop_right", "fbp_crop_bottom")},
    ),
    "EXTEND": (
        {"role": "LEFT", "mode": "CROP_EXTEND", "axis": "X", "props": ("fbp_extend_left",)},
        {"role": "RIGHT", "mode": "CROP_EXTEND", "axis": "X", "props": ("fbp_extend_right",)},
        {"role": "TOP", "mode": "CROP_EXTEND", "axis": "Y", "props": ("fbp_extend_top",)},
        {"role": "BOTTOM", "mode": "CROP_EXTEND", "axis": "Y", "props": ("fbp_extend_bottom",)},
        {"role": "TOP_LEFT", "mode": "CROP_EXTEND", "axis": "XY", "props": ("fbp_extend_left", "fbp_extend_top")},
        {"role": "TOP_RIGHT", "mode": "CROP_EXTEND", "axis": "XY", "props": ("fbp_extend_right", "fbp_extend_top")},
        {"role": "BOTTOM_LEFT", "mode": "CROP_EXTEND", "axis": "XY", "props": ("fbp_extend_left", "fbp_extend_bottom")},
        {"role": "BOTTOM_RIGHT", "mode": "CROP_EXTEND", "axis": "XY", "props": ("fbp_extend_right", "fbp_extend_bottom")},
    ),
    "PIXELATE": ({"role": "GRID", "mode": "OFFSET", "x": "fbp_pixelate_offset_x", "y": "fbp_pixelate_offset_y", "angle": "fbp_pixelate_rotation"},),
    "SWIRL": ({"role": "CENTER", "mode": "POINT", "x": "fbp_swirl_center_x", "y": "fbp_swirl_center_y", "angle": "fbp_swirl_angle"},),
    "BULGE_PINCH": ({"role": "CENTER", "mode": "POINT", "x": "fbp_bulge_pinch_center_x", "y": "fbp_bulge_pinch_center_y"},),
    "LENS_WARP": ({"role": "CENTER", "mode": "POINT", "x": "fbp_lens_warp_center_x", "y": "fbp_lens_warp_center_y"},),
    "WAVE_WARP": ({"role": "DIRECTION", "mode": "ANGLE", "angle": "fbp_wave_warp_angle"},),
    "WIND_BENDER": ({"role": "DIRECTION", "mode": "VECTOR_DIRECTION", "vector": "fbp_wind_direction"},),
    "RIPPLE_DISTORTION": ({"role": "CENTER", "mode": "POINT", "x": "fbp_ripple_distortion_center_x", "y": "fbp_ripple_distortion_center_y"},),
    "KALEIDOSCOPE": ({"role": "CENTER", "mode": "POINT", "x": "fbp_kaleidoscope_center_x", "y": "fbp_kaleidoscope_center_y", "angle": "fbp_kaleidoscope_rotation"},),
    "HALFTONE": ({"role": "CENTER", "mode": "POINT", "x": "fbp_halftone_center_x", "y": "fbp_halftone_center_y", "angle": "fbp_halftone_rotation", "angle_sign": -1.0},),
    "RIM": ({"role": "OFFSET", "mode": "OFFSET", "x": "fbp_rim_offset_x", "y": "fbp_rim_offset_y", "angle": "fbp_rim_rotation"},),
    "SHADOW": ({"role": "OFFSET", "mode": "OFFSET", "x": "fbp_shadow_offset_x", "y": "fbp_shadow_offset_y"},),
    "DIRECTIONAL_BLUR": ({"role": "DIRECTION", "mode": "DIRECTION", "x": "fbp_directional_blur_control_x", "y": "fbp_directional_blur_control_y", "angle": "fbp_directional_blur_angle", "distance": "fbp_directional_blur_distance"},),
    "CHROMATIC_ABERRATION": ({"role": "ANGLE", "mode": "ANGLE", "angle": "fbp_chromatic_aberration_angle"},),
    "HEX_PIXELATE": ({"role": "GRID", "mode": "ANGLE", "angle": "fbp_hex_pixelate_rotation"},),
    "MOSAIC_JITTER": ({"role": "GRID", "mode": "OFFSET", "x": "fbp_mosaic_jitter_offset_x", "y": "fbp_mosaic_jitter_offset_y", "angle": "fbp_mosaic_jitter_rotation"},),
    "SLICE_SHIFT": ({"role": "BANDS", "mode": "ANGLE", "angle": "fbp_slice_shift_angle"},),
    "CROSSHATCH": ({"role": "LINES", "mode": "ANGLE", "angle": "fbp_crosshatch_rotation"},),
    "EMBOSS": ({"role": "LIGHT", "mode": "ANGLE", "angle": "fbp_emboss_angle"},),
    "GOBO_SHADOWS": ({"role": "PATTERN", "mode": "ANGLE", "angle": "fbp_gobo_rotation"},),
    "GRADIENT_MASK": (
        {"role": "CENTER", "mode": "RANGE_CENTER", "range_mode": "GRADIENT_RANGE"},
        {"role": "IN", "mode": "GRADIENT_RANGE"},
        {"role": "OUT", "mode": "GRADIENT_RANGE"},
    ),
    "GRADIENT_LIGHT": (
        {"role": "CENTER", "mode": "RANGE_CENTER", "range_mode": "GRADIENT_LIGHT_RANGE"},
        {"role": "IN", "mode": "GRADIENT_LIGHT_RANGE"},
        {"role": "OUT", "mode": "GRADIENT_LIGHT_RANGE"},
    ),
    "TILT_SHIFT": (
        {"role": "CENTER", "mode": "RANGE_CENTER", "range_mode": "TILT_RANGE"},
        {"role": "IN", "mode": "TILT_RANGE"},
        {"role": "OUT", "mode": "TILT_RANGE"},
    ),
}


def effect_has_controls(effect_id):
    return str(effect_id or "").upper() in CONTROL_SPECS


def validate_effect_control_specs():
    """Return deterministic controller-contract issues for startup diagnostics."""
    try:
        from .effects_registry import FBP_EFFECT_REGISTRY
    except (ImportError, AttributeError):
        return ("Effect registry unavailable while validating viewport controls",)
    issues = []
    try:
        object_rna_properties = getattr(getattr(bpy.types, "Object", None), "bl_rna", None)
        object_rna_properties = getattr(object_rna_properties, "properties", ()) or ()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        object_rna_properties = ()
    valid_modes = {
        "POINT", "OFFSET", "DIRECTION", "ANGLE", "VECTOR_DIRECTION",
        "CROP_EXTEND", "GRADIENT_RANGE", "GRADIENT_LIGHT_RANGE",
        "TILT_RANGE", "RANGE_CENTER",
    }
    for effect_id, specs in CONTROL_SPECS.items():
        definition = FBP_EFFECT_REGISTRY.get(effect_id, {}) or {}
        known = set((definition.get("property_map", {}) or {}).keys())
        known.update(definition.get("extra_properties", ()) or ())
        roles = set()
        for index, spec in enumerate(tuple(specs or ())):
            role = str(spec.get("role", "") or "").upper()
            mode = str(spec.get("mode", "") or "").upper()
            prefix = f"{effect_id} control {index + 1}"
            if not role:
                issues.append(f"{prefix}: missing role")
            elif role in roles:
                issues.append(f"{prefix}: duplicate role {role}")
            roles.add(role)
            if mode not in valid_modes:
                issues.append(f"{prefix}: unsupported mode {mode!r}")
                continue
            required = ()
            if mode in {"POINT", "OFFSET"}:
                required = ("x", "y")
            elif mode == "DIRECTION":
                required = ("angle", "distance")
            elif mode == "ANGLE":
                required = ("angle",)
            elif mode == "VECTOR_DIRECTION":
                required = ("vector",)
            for key in required:
                if not str(spec.get(key, "") or ""):
                    issues.append(f"{prefix}: {mode} requires {key}")
            if bool(spec.get("x")) != bool(spec.get("y")):
                issues.append(f"{prefix}: x/y controller anchors must be paired")
            property_names = set(spec.get("props", ()) or ())
            property_names.update(
                str(spec.get(key, "") or "")
                for key in ("x", "y", "angle", "distance", "vector")
                if str(spec.get(key, "") or "")
            )
            unknown = sorted(name for name in property_names if name not in known)
            if unknown:
                issues.append(
                    f"{prefix}: properties missing from effect definition: "
                    + ", ".join(unknown)
                )
            if object_rna_properties:
                missing_rna = sorted(
                    name for name in property_names
                    if not object_rna_properties.get(name)
                )
                if missing_rna:
                    issues.append(
                        f"{prefix}: Object RNA properties are not registered: "
                        + ", ".join(missing_rna)
                    )
            if mode == "CROP_EXTEND" and not tuple(spec.get("props", ()) or ()):
                issues.append(f"{prefix}: CROP_EXTEND requires driven props")
            if mode == "RANGE_CENTER" and str(spec.get("range_mode", "") or "").upper() not in {
                "GRADIENT_RANGE", "GRADIENT_LIGHT_RANGE", "TILT_RANGE"
            }:
                issues.append(f"{prefix}: RANGE_CENTER requires a supported range_mode")
        range_modes = {
            str(spec.get("mode", "") or "").upper()
            for spec in tuple(specs or ())
        }
        if range_modes.intersection({"GRADIENT_RANGE", "GRADIENT_LIGHT_RANGE", "TILT_RANGE"}):
            if not {"IN", "OUT"}.issubset(roles):
                issues.append(f"{effect_id}: range controls require IN and OUT roles")
    return tuple(issues)


_RANGE_MODE_DRIVEN_PROPERTIES = {
    "GRADIENT_RANGE": frozenset({
        "fbp_gradient_mask_center_x", "fbp_gradient_mask_center_y",
        "fbp_gradient_mask_position", "fbp_gradient_mask_angle",
        "fbp_gradient_mask_feather",
    }),
    "GRADIENT_LIGHT_RANGE": frozenset({
        "fbp_gradient_light_center_x", "fbp_gradient_light_center_y",
        "fbp_gradient_light_angle", "fbp_gradient_shadow_position",
        "fbp_gradient_softness",
    }),
    "TILT_RANGE": frozenset({
        "fbp_tilt_shift_position", "fbp_tilt_shift_width", "fbp_tilt_shift_angle",
    }),
}


def effect_control_driven_properties(effect_id):
    """Return properties represented directly by the viewport control."""
    effect_id = str(effect_id or "").upper()
    cached = _CONTROL_DRIVEN_PROPS_CACHE.get(effect_id)
    if cached is not None:
        return cached
    properties = set()
    for spec in CONTROL_SPECS.get(effect_id, ()):
        for value in tuple(spec.get("props", ()) or ()):  # direct multi-property helpers such as Crop/Extend handles
            value = str(value or "")
            if value:
                properties.add(value)
        for key in ("x", "y", "angle", "distance", "vector"):
            value = str(spec.get(key, "") or "")
            if value:
                properties.add(value)
        mode = str(spec.get("mode", "") or "").upper()
        if mode == "RANGE_CENTER":
            mode = str(spec.get("range_mode", "") or "").upper()
        properties.update(_RANGE_MODE_DRIVEN_PROPERTIES.get(mode, ()))
    cached = frozenset(properties)
    _CONTROL_DRIVEN_PROPS_CACHE[effect_id] = cached
    return cached


def is_effect_control(obj):
    try:
        return bool(obj and obj.get(KEY_IS_CONTROL, False))
    except FBP_DATA_ERRORS:
        return False


def effect_control_owner(obj):
    if not is_effect_control(obj):
        return None
    try:
        pointer = int(fbp_obj_runtime_key(obj) or 0)
        owner_name = str(obj.get(KEY_OWNER_NAME, "") or "")
        plane = getattr(obj, "parent", None)
        plane_name = str(getattr(plane, "name", "") or "") if plane else ""

        # Current controls have a canonical control -> plane -> rig chain.
        # Resolve that direct RNA relation before touching bpy.data; this is the
        # hot path during viewport visibility and avoids one global collection
        # lookup for every helper on every selection refresh.
        rig = getattr(plane, "parent", None) if plane else None
        if rig and bool(getattr(rig, "is_fbp_control", False)):
            if len(_CONTROL_OWNER_CACHE) >= 4096 and pointer not in _CONTROL_OWNER_CACHE:
                _CONTROL_OWNER_CACHE.clear()
            _CONTROL_OWNER_CACHE[pointer] = (obj.name, owner_name, plane_name, rig.name)
            return rig

        cached = _CONTROL_OWNER_CACHE.get(pointer)
        if cached is not None:
            try:
                obj_name, cached_owner_name, cached_plane_name, rig_name = cached
                if obj_name == obj.name and cached_owner_name == owner_name and cached_plane_name == plane_name:
                    rig = bpy.data.objects.get(str(rig_name or ""))
                    if rig and bool(getattr(rig, "is_fbp_control", False)):
                        return rig
            except FBP_DATA_ERRORS:
                _CONTROL_OWNER_CACHE.pop(pointer, None)
        rig = bpy.data.objects.get(owner_name) if owner_name else None
        if rig and bool(getattr(rig, "is_fbp_control", False)):
            if len(_CONTROL_OWNER_CACHE) >= 4096 and pointer not in _CONTROL_OWNER_CACHE:
                _CONTROL_OWNER_CACHE.clear()
            _CONTROL_OWNER_CACHE[pointer] = (obj.name, owner_name, plane_name, rig.name)
            return rig
        _CONTROL_OWNER_CACHE.pop(pointer, None)
        return None
    except FBP_DATA_ERRORS:
        return None


def _plane_and_mapping(rig):
    """Return the render plane plus the cropped image rectangle and UV range.

    Effect controls intentionally ignore Extend geometry.  Spatial shader
    parameters operate in the source image UV domain, so their helpers must sit
    on the cropped image rectangle rather than on the enlarged border mesh.
    """
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    if plane is None or getattr(plane, "type", "") != "MESH":
        return None, (-1.0, 1.0, -1.0, 1.0), (0.0, 1.0, 0.0, 1.0)
    try:
        from .builder import fbp_plane_reference_bounds
        _source, cropped, _extended, uv_bounds = fbp_plane_reference_bounds(rig)
        return plane, tuple(cropped), tuple(uv_bounds)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    points = []
    try:
        points = [(float(p[0]), float(p[1])) for p in tuple(plane.bound_box or ())]
    except FBP_DATA_ERRORS:
        pass
    if not points:
        try:
            points = [(float(v.co.x), float(v.co.y)) for v in plane.data.vertices]
        except FBP_DATA_ERRORS:
            points = []
    if points:
        xs, ys = zip(*points, strict=False)
        bounds = (min(xs), max(xs), min(ys), max(ys))
    else:
        bounds = (-1.0, 1.0, -1.0, 1.0)
    return plane, bounds, (0.0, 1.0, 0.0, 1.0)


def _lerp(a, b, t):
    return float(a) + (float(b) - float(a)) * float(t)


def _unlerp(a, b, value):
    span = float(b) - float(a)
    return 0.5 if abs(span) < 1.0e-8 else (float(value) - float(a)) / span


def _uv_to_local(rig, u, v):
    _plane, bounds, uv_bounds = _plane_and_mapping(rig)
    min_x, max_x, min_y, max_y = bounds
    min_u, max_u, min_v, max_v = uv_bounds
    return (
        _lerp(min_x, max_x, _unlerp(min_u, max_u, u)),
        _lerp(min_y, max_y, _unlerp(min_v, max_v, v)),
    )


def _local_to_uv(rig, x, y):
    _plane, bounds, uv_bounds = _plane_and_mapping(rig)
    min_x, max_x, min_y, max_y = bounds
    min_u, max_u, min_v, max_v = uv_bounds
    return (
        _lerp(min_u, max_u, _unlerp(min_x, max_x, x)),
        _lerp(min_v, max_v, _unlerp(min_y, max_y, y)),
    )


def _control_name(rig, effect_id, role):
    return f"FBP Control • {effect_id.title().replace('_', ' ')} • {role} • {rig.name}"


def _helper_matches(obj, rig, effect_id, role):
    if not is_effect_control(obj):
        return False
    try:
        return bool(
            str(obj.get(KEY_EFFECT_ID, "") or "") == effect_id
            and str(obj.get(KEY_ROLE, "") or "") == role
            and effect_control_owner(obj) is rig
        )
    except FBP_DATA_ERRORS:
        return False


def _candidate_effect_controls(rig, *, include_cached=False):
    """Yield canonical plane children, with an optional orphan-repair fallback.

    Normal refreshes only inspect the owning plane's children. Walking the
    process-wide name cache for every role made multi-layer controller sync scale
    with every helper in the file. The cache fallback is reserved for missing or
    stale contracts, where the extra scan is useful and infrequent.
    """
    seen = set()
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    try:
        children = tuple(getattr(plane, "children", ()) or ())
    except FBP_DATA_ERRORS:
        children = ()
    for obj in children:
        try:
            pointer = int(fbp_obj_runtime_key(obj) or 0)
        except FBP_DATA_ERRORS:
            continue
        if pointer in seen or not is_effect_control(obj):
            continue
        seen.add(pointer)
        yield obj
    if not include_cached:
        return
    for name in tuple(_CONTROL_NAMES):
        obj = bpy.data.objects.get(name)
        if obj is None:
            _CONTROL_NAMES.discard(name)
            continue
        try:
            pointer = int(fbp_obj_runtime_key(obj) or 0)
        except FBP_DATA_ERRORS:
            continue
        if pointer in seen or not is_effect_control(obj):
            continue
        if effect_control_owner(obj) is not rig:
            continue
        seen.add(pointer)
        yield obj


def find_effect_control(rig, effect_id, role):
    effect_id = str(effect_id or "").upper()
    role = str(role or "").upper()
    for candidate in _candidate_effect_controls(rig):
        if _helper_matches(candidate, rig, effect_id, role):
            _CONTROL_NAMES.add(candidate.name)
            return candidate
    # Only missing canonical children pay for the orphan recovery fallback.
    for candidate in _candidate_effect_controls(rig, include_cached=True):
        if _helper_matches(candidate, rig, effect_id, role):
            _CONTROL_NAMES.add(candidate.name)
            return candidate
    return None


def _link_control(control, plane):
    collections = tuple(getattr(plane, "users_collection", ()) or ())
    collection = collections[0] if collections else getattr(bpy.context, "collection", None)
    collection = collection or getattr(getattr(bpy.context, "scene", None), "collection", None)
    if collection and control.name not in collection.objects:
        collection.objects.link(control)


def _remove_duplicate_controls(
    rig, effect_id, role, keep, *, include_cached=False
):
    """Remove stale helpers that represent the exact same control contract.

    Range effects intentionally own boundary and center controls with different roles; only
    duplicates matching owner, effect and role are removed. This repairs old
    files where repeated UI synchronization created overlapping nulls that
    fought over the same properties and appeared impossible to transform.
    """
    if rig is None or keep is None:
        return 0
    removed = 0
    for candidate in tuple(
        _candidate_effect_controls(rig, include_cached=include_cached)
    ):
        if candidate is keep or not _helper_matches(candidate, rig, effect_id, role):
            continue
        try:
            _CONTROL_NAMES.discard(candidate.name)
            _PENDING_CONTROL_SIGNATURES.pop(str(candidate.name), None)
            bpy.data.objects.remove(candidate, do_unlink=True)
            removed += 1
        except FBP_DATA_ERRORS:
            continue
    return removed


def _expected_control_locks(mode, spec=None):
    spec = spec or {}
    mode = str(mode or "").upper()
    if mode in {"POINT", "OFFSET"}:
        return (
            (False, False, True),
            (True, True, not bool(spec.get("angle"))),
            (True, True, True),
        )
    if mode == "CROP_EXTEND":
        axis = str(spec.get("axis", "XY") or "XY").upper()
        lock_x = axis == "Y"
        lock_y = axis == "X"
        return (
            (lock_x, lock_y, True),
            (True, True, True),
            (True, True, True),
        )
    if mode in {"GRADIENT_RANGE", "GRADIENT_LIGHT_RANGE", "TILT_RANGE"}:
        return (
            (False, False, True),
            (True, True, False),
            (True, True, True),
        )
    if mode == "RANGE_CENTER":
        return (
            (False, False, True),
            (True, True, False),
            (False, True, True),
        )
    if mode == "DIRECTION":
        return (
            (False, False, True),
            (True, True, False),
            (False, True, True),
        )
    if mode == "ANGLE":
        return (
            (True, True, True),
            (True, True, False),
            (True, True, True),
        )
    if mode == "VECTOR_DIRECTION":
        # Wind uses a true 3D directional null: location/scale stay fixed,
        # but the arrow can rotate freely on all axes.
        return (
            (True, True, True),
            (False, False, False),
            (True, True, True),
        )
    return None


def _configure_locks(control, mode, spec=None):
    """Apply helper transform locks only when their values really differ."""
    expected = _expected_control_locks(mode, spec)
    if expected is None:
        return False
    lock_location, lock_rotation, lock_scale = expected
    changed = False
    try:
        if tuple(control.lock_location) != lock_location:
            control.lock_location = lock_location
            changed = True
        if tuple(control.lock_rotation) != lock_rotation:
            control.lock_rotation = lock_rotation
            changed = True
        if tuple(control.lock_scale) != lock_scale:
            control.lock_scale = lock_scale
            changed = True
    except FBP_DATA_ERRORS:
        return False
    return changed


def _is_crop_extend_mode(mode):
    return str(mode or "").upper() == "CROP_EXTEND"


def _is_range_handle_mode(mode):
    return str(mode or "").upper() in {
        "GRADIENT_RANGE", "GRADIENT_LIGHT_RANGE", "TILT_RANGE", "RANGE_CENTER",
    }


def _uses_control_mesh(mode):
    return _is_crop_extend_mode(mode) or _is_range_handle_mode(mode)


def _crop_extend_handle_mesh_signature(rig, role):
    size = _control_display_size(rig, "CROP_EXTEND", role)
    return f"crop_extend_handle_v3:{str(role or '').upper()}:{size:.6f}"


def _crop_extend_handle_geometry(rig, role, *, size=None):
    """Return flat mesh geometry for Crop/Extend side and corner handles."""
    size = _control_display_size(rig, "CROP_EXTEND", role) if size is None else float(size)
    return bounds_handle_geometry(size, role)


def _range_handle_mesh_signature(rig, mode, role, *, size=None, reference=None):
    size = _control_display_size(rig, mode, role) if size is None else float(size)
    reference = _range_reference_length(rig) if reference is None else float(reference)
    return f"range_handle_v1:{str(mode or '').upper()}:{str(role or '').upper()}:{size:.6f}:{reference:.6f}"


def _range_handle_geometry(rig, mode, role, *, size=None, reference=None):
    """Return flat bar geometry for paired gradient/tilt viewport controls."""
    role = str(role or "").upper()
    size = _control_display_size(rig, mode, role) if size is None else float(size)
    reference = _range_reference_length(rig) if reference is None else float(reference)
    thickness = max(size * 0.24, 0.0035)
    verts = []
    faces = []

    if role == "CENTER":
        # The X-scaled center helper is both a movable midpoint and a visible
        # connector between the IN/OUT bars, matching Crop/Extend's flat UI.
        append_rect_geometry(verts, faces, 0.0, 0.0, reference, thickness)
        append_rect_geometry(verts, faces, 0.0, 0.0, size * 0.72, size * 0.72)
    else:
        append_rect_geometry(verts, faces, 0.0, 0.0, thickness, max(size * 2.8, thickness * 3.0))
    return verts, faces


def _remove_control_object(control):
    """Remove a viewport-control object and its private mesh datablock safely."""
    if control is None:
        return False
    try:
        name = str(getattr(control, "name", "") or "")
        pointer = int(fbp_obj_runtime_key(control) or 0)
    except FBP_DATA_ERRORS:
        name = ""
        pointer = 0
    try:
        mesh = getattr(control, "data", None) if str(getattr(control, "type", "") or "") == "MESH" else None
        if name:
            _CONTROL_NAMES.discard(name)
            _GUIDE_NAMES.discard(name)
            _PENDING_CONTROL_SIGNATURES.pop(name, None)
            _PENDING_CONTROL_TRANSFORMS.pop(name, None)
        if pointer:
            _CONTROL_OWNER_CACHE.pop(pointer, None)
        bpy.data.objects.remove(control, do_unlink=True)
        if (
            mesh is not None
            and int(getattr(mesh, "users", 0) or 0) == 0
            and str(getattr(mesh, "name", "") or "").startswith(("FBP Control Mesh", "FBP Image Bounds Mesh"))
        ):
            bpy.data.meshes.remove(mesh)
        return True
    except FBP_DATA_ERRORS:
        return False


def _ensure_control_handle_mesh(control, rig, mode, role):
    if control is None or getattr(control, "type", "") != "MESH":
        return False
    if _is_crop_extend_mode(mode):
        size = _control_display_size(rig, mode, role)
        signature = f"crop_extend_handle_v3:{str(role or '').upper()}:{size:.6f}"
        verts, faces = _crop_extend_handle_geometry(rig, role, size=size)
        label = "Crop/Extend"
    elif _is_range_handle_mode(mode):
        size = _control_display_size(rig, mode, role)
        reference = _range_reference_length(rig)
        signature = _range_handle_mesh_signature(
            rig, mode, role, size=size, reference=reference
        )
        verts, faces = _range_handle_geometry(
            rig, mode, role, size=size, reference=reference
        )
        label = "Gradient range"
    else:
        return False
    try:
        if str(control.get(KEY_CONTROL_MESH_SIGNATURE, "") or "") == signature and getattr(control, "data", None):
            return False
    except FBP_DATA_ERRORS:
        pass
    mesh = getattr(control, "data", None)
    if mesh is None:
        mesh = bpy.data.meshes.new(f"FBP Control Mesh • {role}")
        control.data = mesh
    try:
        mesh.clear_geometry()
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        mat = ensure_viewport_handle_material()
        if not mesh.materials:
            mesh.materials.append(mat)
        elif mesh.materials[0] is not mat:
            mesh.materials[0] = mat
        control[KEY_CONTROL_MESH_SIGNATURE] = signature
        return True
    except (ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn(f"Could not rebuild {label} viewport handle mesh", exc)
        return False


def _control_display_type(mode):
    mode = str(mode or "").upper()
    if mode in {"DIRECTION", "ANGLE", "VECTOR_DIRECTION"}:
        return "SINGLE_ARROW"
    if mode in {"RANGE_CENTER", "CROP_EXTEND"}:
        return "CUBE"
    return "CIRCLE"


def _control_base_rotation(mode):
    """Return the Empty display correction for one control shape.

    Effect helpers are parented to the render plane and use plane-local space.
    In Blender 5.2 the visual CIRCLE empty is authored on a different local
    drawing plane than the generated image mesh, so a neutral rotation can make
    Pixelate/point helpers stand upright and appear as a line from camera view.
    A +90° X correction lays circular helpers directly on the image plane.

    SINGLE_ARROW helpers used as 2D angle controls need a different correction:
    +90° Y lays the arrow on the image-plane X axis, keeping angle 0 visibly
    pointing right and aligned with UV rotation. Wind's VECTOR_DIRECTION is 3D:
    neutral rotation keeps the arrow on the plane local Z axis, crossing the
    plane by default.
    """
    mode = str(mode or "").upper()
    if mode == "VECTOR_DIRECTION":
        return (0.0, 0.0)
    if mode in {"DIRECTION", "ANGLE"}:
        return (0.0, math.pi * 0.5)
    if mode in {"RANGE_CENTER", "CROP_EXTEND"}:
        return (0.0, 0.0)
    return (math.pi * 0.5, 0.0)


def _control_depth(rig):
    _plane, bounds, _uv_bounds = _plane_and_mapping(rig)
    width = max(abs(bounds[1] - bounds[0]), 1.0e-6)
    height = max(abs(bounds[3] - bounds[2]), 1.0e-6)
    return max(0.001, min(0.025, min(width, height) * 0.006))


def _control_display_size(rig, mode="", role=""):
    _plane, bounds, _uv_bounds = _plane_and_mapping(rig)
    width = max(abs(bounds[1] - bounds[0]), 1.0e-6)
    height = max(abs(bounds[3] - bounds[2]), 1.0e-6)
    size = max(0.035, min(0.32, min(width, height) * 0.075))
    if str(mode or "").upper() in {"DIRECTION", "ANGLE", "VECTOR_DIRECTION"}:
        size *= 1.25
    elif str(mode or "").upper() == "CROP_EXTEND":
        size *= 0.62 if "_" in str(role or "") else 0.78
    elif str(mode or "").upper() == "RANGE_CENTER":
        size *= 0.72
    elif str(role or "").upper() in {"IN", "OUT"}:
        size *= 0.88
    return size


def _control_color(role, mode):
    role = str(role or "").upper()
    mode = str(mode or "").upper()
    if mode == "CROP_EXTEND":
        return (1.0, 0.55, 0.05, 1.0)
    if role == "OUT":
        return (1.0, 0.32, 0.08, 1.0)
    if role == "IN":
        return (0.12, 0.48, 1.0, 1.0)
    if role == "CENTER" and mode == "RANGE_CENTER":
        return (1.0, 0.78, 0.12, 1.0)
    if mode in {"DIRECTION", "ANGLE", "VECTOR_DIRECTION"}:
        return (0.18, 0.85, 0.35, 1.0)
    if mode == "OFFSET":
        return (0.80, 0.28, 1.0, 1.0)
    return (0.12, 0.62, 1.0, 1.0)


def ensure_effect_control(rig, effect_id, spec, *, select=False):
    """Return one helper without re-tagging Blender data on every refresh."""
    effect_id = str(effect_id or "").upper()
    role = str(spec.get("role", "CONTROL") or "CONTROL").upper()
    mode = str(spec.get("mode", "POINT") or "POINT").upper()
    control = find_effect_control(rig, effect_id, role)
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    if plane is None:
        return None

    # Paired gradient/tilt handles with a stale schema can retain an invalid
    # parent inverse or delta rotation. Recreate them so their local XY plane
    # always follows the rendered plane orientation.
    if control is not None and _is_range_handle_mode(mode):
        try:
            if int(control.get(KEY_SCHEMA, 0) or 0) < SCHEMA_VERSION:
                _remove_control_object(control)
                control = None
        except FBP_DATA_ERRORS:
            control = None

    # Crop/Extend and paired range controls require flat mesh shapes. Replace
    # an invalid non-mesh helper with a stable bar handle.
    if control is not None and _uses_control_mesh(mode) and getattr(control, "type", "") != "MESH":
        try:
            _remove_control_object(control)
        except FBP_DATA_ERRORS:
            pass
        control = None

    created = control is None
    needs_contract_repair = created
    if created:
        data = bpy.data.meshes.new(f"FBP Control Mesh • {role}") if _uses_control_mesh(mode) else None
        control = bpy.data.objects.new(_control_name(rig, effect_id, role), data)
        _link_control(control, plane)
        control.parent = plane
        control.matrix_parent_inverse = Matrix.Identity(4)
        base_x, base_y = _control_base_rotation(mode)
        control.location = (0.0, 0.0, _control_depth(rig))
        control.rotation_mode = "XYZ"
        control.rotation_euler = (base_x, base_y, 0.0)
        control.scale = (1.0, 1.0, 1.0)
        if _uses_control_mesh(mode):
            control.display_type = "SOLID"
            if _is_crop_extend_mode(mode):
                _apply_crop_extend_transform_limits(control, rig, effect_id, role)
        else:
            control.empty_display_type = _control_display_type(mode)
            control.empty_display_size = _control_display_size(rig, mode, role)
        control.show_in_front = True
        control.hide_render = True
        control.color = _control_color(role, mode)
        control[KEY_IS_CONTROL] = True
        control[KEY_SCHEMA] = SCHEMA_VERSION
        control[KEY_EFFECT_ID] = effect_id
        control[KEY_ROLE] = role
        control[KEY_MODE] = mode
        control[KEY_OWNER_NAME] = rig.name
        _CONTROL_NAMES.add(control.name)
        _register_selection_visibility_timer()
    else:
        try:
            previous_owner = str(control.get(KEY_OWNER_NAME, "") or "")
            previous_schema = int(control.get(KEY_SCHEMA, 0) or 0)
            needs_contract_repair = bool(
                previous_owner != str(rig.name)
                or previous_schema != SCHEMA_VERSION
                or getattr(control, "parent", None) is not plane
            )
            if previous_owner != str(rig.name):
                control[KEY_OWNER_NAME] = rig.name
            if previous_schema != SCHEMA_VERSION:
                control[KEY_SCHEMA] = SCHEMA_VERSION
            if str(control.get(KEY_EFFECT_ID, "") or "") != effect_id:
                control[KEY_EFFECT_ID] = effect_id
            if str(control.get(KEY_ROLE, "") or "") != role:
                control[KEY_ROLE] = role
            if str(control.get(KEY_MODE, "") or "") != mode:
                control[KEY_MODE] = mode
            if getattr(control, "parent", None) is not plane:
                control.parent = plane
                control.matrix_parent_inverse = Matrix.Identity(4)
            else:
                # Controls use plane-local XY space. Keeping a neutral parent
                # inverse makes circles and arrows inherit the complete rig/plane
                # orientation instead of remaining horizontal in world space.
                identity = Matrix.Identity(4)
                try:
                    if not control.matrix_parent_inverse.is_identity:
                        control.matrix_parent_inverse = identity
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
        except FBP_DATA_ERRORS:
            pass

    _remove_duplicate_controls(
        rig,
        effect_id,
        role,
        control,
        include_cached=needs_contract_repair,
    )
    try:
        from .ownership import tag_effect_control_contract
        tag_effect_control_contract(control, rig)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    try:
        if str(getattr(control, "rotation_mode", "") or "") != "XYZ":
            control.rotation_mode = "XYZ"
        try:
            if any(abs(float(value)) > 1.0e-8 for value in control.delta_location):
                control.delta_location = (0.0, 0.0, 0.0)
            if any(abs(float(value)) > 1.0e-8 for value in control.delta_rotation_euler):
                control.delta_rotation_euler = (0.0, 0.0, 0.0)
            if any(abs(float(value) - 1.0) > 1.0e-8 for value in control.delta_scale):
                control.delta_scale = (1.0, 1.0, 1.0)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        target_rotation_x, target_rotation_y = _control_base_rotation(mode)
        if mode != "VECTOR_DIRECTION":
            if abs(float(control.rotation_euler.x) - target_rotation_x) > 1.0e-7:
                control.rotation_euler.x = target_rotation_x
            if abs(float(control.rotation_euler.y) - target_rotation_y) > 1.0e-7:
                control.rotation_euler.y = target_rotation_y
        if _uses_control_mesh(mode):
            if str(getattr(control, "display_type", "") or "") != "SOLID":
                control.display_type = "SOLID"
            _ensure_control_handle_mesh(control, rig, mode, role)
            if _is_crop_extend_mode(mode):
                _apply_crop_extend_transform_limits(control, rig, effect_id, role)
        else:
            target_display = _control_display_type(mode)
            if str(getattr(control, "empty_display_type", "") or "") != target_display:
                control.empty_display_type = target_display
        target_color = _control_color(role, mode)
        if tuple(round(float(value), 5) for value in control.color) != tuple(round(value, 5) for value in target_color):
            control.color = target_color
        if not bool(getattr(control, "show_in_front", False)):
            control.show_in_front = True
        if not bool(getattr(control, "hide_render", False)):
            control.hide_render = True
        if bool(getattr(control, "show_name", False)):
            control.show_name = False
    except FBP_DATA_ERRORS:
        pass
    _configure_locks(control, mode, spec)
    if not _uses_control_mesh(mode):
        try:
            target_size = _control_display_size(rig, mode, role)
            if abs(float(control.empty_display_size) - target_size) > 1.0e-6:
                control.empty_display_size = target_size
        except FBP_DATA_ERRORS:
            pass
    if select:
        _select_control_preserving_layer(bpy.context, rig, control)
    return control


def _focus_effect_row_for_control(rig, effect_id):
    """Keep the Effects UI on the row represented by a selected viewport helper."""
    effect_id = str(effect_id or "").upper()
    if rig is None or not effect_id or not hasattr(rig, "fbp_effects"):
        return False
    changed = False
    try:
        current = int(getattr(rig, "fbp_effects_index", 0) or 0)
        if 0 <= current < len(rig.fbp_effects):
            item = rig.fbp_effects[current]
            if (
                str(getattr(item, "row_type", "EFFECT") or "EFFECT") == "EFFECT"
                and str(getattr(item, "effect_id", "") or "").upper() == effect_id
            ):
                return changed
        for index, item in enumerate(rig.fbp_effects):
            if str(getattr(item, "row_type", "EFFECT") or "EFFECT") != "EFFECT":
                continue
            if str(getattr(item, "effect_id", "") or "").upper() == effect_id:
                return fbp_set_rna_property_silent(rig, "fbp_effects_index", int(index)) or changed
    except FBP_DATA_ERRORS:
        return False
    return changed


def _preferred_control_for_selection(context, rig, effect_id, controls):
    """Preserve the handle the user actually selected during deferred refreshes."""
    controls = tuple(control for control in tuple(controls or ()) if control is not None)
    if not controls:
        return None, ()
    active = getattr(context, "active_object", None) if context is not None else None
    if active in controls and effect_control_owner(active) is rig:
        try:
            if str(active.get(KEY_EFFECT_ID, "") or "").upper() == str(effect_id or "").upper():
                return active, tuple(control for control in controls if control is not active)
        except FBP_DATA_ERRORS:
            pass
    return controls[0], tuple(controls[1:])


def _select_control_preserving_layer(context, rig, control, related_controls=()):
    """Activate one helper exclusively while preserving the Layer List state.

    The Layer List keeps its own logical selection. Keeping the rig or render
    plane selected in the 3D View makes Blender's G/R/S operators transform the
    plane together with the helper, which is especially destructive for the
    Crop/Extend bars. Viewport selection is therefore reduced to one active
    helper; related controls remain visible but unselected.
    """
    if context is None or rig is None or control is None:
        return False
    try:
        active_effect = str(control.get(KEY_EFFECT_ID, "") or "").upper()
        _focus_effect_row_for_control(rig, active_effect)
        for selected in tuple(getattr(context, "selected_objects", ()) or ()):
            if selected is control:
                continue
            try:
                selected.select_set(False)
            except FBP_DATA_ERRORS:
                pass
        _set_control_visibility(control, True)
        control.select_set(True)
        for related in tuple(related_controls or ()):
            if related is not None:
                _set_control_visibility(related, True)
                try:
                    related.select_set(False)
                except FBP_DATA_ERRORS:
                    pass
        context.view_layer.objects.active = control
        return True
    except FBP_DATA_ERRORS:
        return False


def _control_signature(control):
    try:
        return tuple(round(float(value), 7) for value in (
            control.location.x, control.location.y, control.location.z,
            control.rotation_euler.x, control.rotation_euler.y, control.rotation_euler.z,
            control.scale.x,
        ))
    except FBP_DATA_ERRORS:
        return ()


def _set_control_transform(control, *, location=None, angle=None, rotation=None, scale_x=None):
    if control is None:
        return False
    key = control.name
    _SYNC_GUARD.add(key)
    changed = False
    try:
        if location is not None:
            x, y = location
            if abs(float(control.location.x) - float(x)) > 1.0e-7:
                control.location.x = float(x); changed = True
            if abs(float(control.location.y) - float(y)) > 1.0e-7:
                control.location.y = float(y); changed = True
            rig = effect_control_owner(control)
            target_depth = _control_depth(rig) if rig is not None else 0.006
            if abs(float(control.location.z) - target_depth) > 1.0e-7:
                control.location.z = target_depth; changed = True
        if angle is not None and abs(float(control.rotation_euler.z) - float(angle)) > 1.0e-7:
            control.rotation_euler.z = float(angle); changed = True
        if rotation is not None:
            try:
                rx, ry, rz = rotation
                if abs(float(control.rotation_euler.x) - float(rx)) > 1.0e-7:
                    control.rotation_euler.x = float(rx); changed = True
                if abs(float(control.rotation_euler.y) - float(ry)) > 1.0e-7:
                    control.rotation_euler.y = float(ry); changed = True
                if abs(float(control.rotation_euler.z) - float(rz)) > 1.0e-7:
                    control.rotation_euler.z = float(rz); changed = True
            except (TypeError, ValueError):
                pass
        if scale_x is not None and abs(float(control.scale.x) - float(scale_x)) > 1.0e-7:
            control.scale.x = max(0.02, float(scale_x)); changed = True
        signature = _control_signature(control)
        try:
            stored = tuple(float(value) for value in control.get(KEY_SYNC_SIGNATURE, ()) or ())
        except FBP_DATA_ERRORS:
            stored = ()
        if signature != stored:
            control[KEY_SYNC_SIGNATURE] = list(signature)
    finally:
        _SYNC_GUARD.discard(key)
    return changed


def _control_direction_vector(rig, control):
    try:
        if str(getattr(rig, "fbp_wind_direction_space", "LOCAL") or "LOCAL").upper() == "WORLD":
            direction = control.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))
        else:
            direction = control.rotation_euler.to_matrix() @ Vector((0.0, 0.0, 1.0))
    except FBP_DATA_ERRORS:
        direction = Vector((0.0, 0.0, 1.0))
    if direction.length <= 1.0e-8:
        direction = Vector((0.0, 0.0, 1.0))
    direction.normalize()
    return (float(direction.x), float(direction.y), float(direction.z))


def _control_rotation_from_direction(rig, vector):
    """Convert the Wind direction RNA vector into the helper's local rotation."""
    try:
        direction = Vector(tuple(vector)[:3])
    except (TypeError, ValueError, IndexError):
        direction = Vector((0.0, 0.0, 1.0))
    if direction.length <= 1.0e-8:
        direction = Vector((0.0, 0.0, 1.0))
    try:
        if str(getattr(rig, "fbp_wind_direction_space", "LOCAL") or "LOCAL").upper() == "WORLD":
            plane = getattr(rig, "fbp_plane_target", None)
            if plane is not None:
                direction = plane.matrix_world.to_3x3().inverted_safe() @ direction
    except FBP_DATA_ERRORS:
        pass
    if direction.length <= 1.0e-8:
        direction = Vector((0.0, 0.0, 1.0))
    direction.normalize()
    try:
        return tuple(float(value) for value in direction.to_track_quat('Z', 'Y').to_euler('XYZ'))
    except (AttributeError, RuntimeError, ValueError):
        return (0.0, 0.0, 0.0)


def _range_controls(rig, effect_id):
    return (
        find_effect_control(rig, effect_id, "IN"),
        find_effect_control(rig, effect_id, "OUT"),
    )


def _range_center_control(rig, effect_id):
    return find_effect_control(rig, effect_id, "CENTER")


def _range_mode_for_effect(effect_id):
    for item in CONTROL_SPECS.get(str(effect_id or "").upper(), ()):
        mode = str(item.get("mode", "") or "").upper()
        if mode in {"GRADIENT_RANGE", "GRADIENT_LIGHT_RANGE", "TILT_RANGE"}:
            return mode
        if mode == "RANGE_CENTER":
            range_mode = str(item.get("range_mode", "") or "").upper()
            if range_mode:
                return range_mode
    return ""


def _range_reference_length(rig):
    _plane, bounds, _uv = _plane_and_mapping(rig)
    width = max(abs(bounds[1] - bounds[0]), 1.0e-6)
    height = max(abs(bounds[3] - bounds[2]), 1.0e-6)
    return max(min(width, height) * 0.5, 1.0e-6)


def _set_range_endpoint_transforms(rig, in_control, out_control, in_uv, out_uv):
    """Place UV-space range boundaries with the correct plane-local angle."""
    in_location = _uv_to_local(rig, *in_uv)
    out_location = _uv_to_local(rig, *out_uv)
    local_angle = math.atan2(
        float(out_location[1]) - float(in_location[1]),
        float(out_location[0]) - float(in_location[0]),
    )
    changed = _set_control_transform(
        in_control, location=in_location, angle=local_angle
    )
    return _set_control_transform(
        out_control, location=out_location, angle=local_angle
    ) or changed


def _sync_range_center_from_endpoints(rig, effect_id, controls=None):
    controls = controls or {}
    in_control = controls.get("IN") or find_effect_control(rig, effect_id, "IN")
    out_control = controls.get("OUT") or find_effect_control(rig, effect_id, "OUT")
    center = controls.get("CENTER") or _range_center_control(rig, effect_id)
    if in_control is None or out_control is None or center is None:
        return False
    x1, y1 = float(in_control.location.x), float(in_control.location.y)
    x2, y2 = float(out_control.location.x), float(out_control.location.y)
    dx, dy = x2 - x1, y2 - y1
    length = max(math.hypot(dx, dy), 1.0e-6)
    angle = math.atan2(dy, dx)
    reference = _range_reference_length(rig)
    return _set_control_transform(
        center,
        location=((x1 + x2) * 0.5, (y1 + y2) * 0.5),
        angle=angle,
        scale_x=max(0.05, length / reference),
    )


def _crop_extend_bounds(rig):
    try:
        from .builder import fbp_plane_reference_bounds, fbp_native_aspect_half_extents
        source, cropped, extended, _uv = fbp_plane_reference_bounds(rig)
        base_x, base_y = fbp_native_aspect_half_extents(rig)
        return tuple(source), tuple(cropped), tuple(extended), max(float(base_x), 1.0e-6), max(float(base_y), 1.0e-6)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return (-1.0, 1.0, -1.0, 1.0), (-1.0, 1.0, -1.0, 1.0), (-1.0, 1.0, -1.0, 1.0), 1.0, 1.0


def _crop_extend_handle_location(rig, effect_id, role, *, bounds_state=None):
    effect_id = str(effect_id or "").upper()
    role = str(role or "").upper()
    _source, cropped, extended, _base_x, _base_y = (
        _crop_extend_bounds(rig) if bounds_state is None else bounds_state
    )
    bounds = cropped if effect_id == "CROP" else extended
    min_x, max_x, min_y, max_y = bounds
    mid_x = (min_x + max_x) * 0.5
    mid_y = (min_y + max_y) * 0.5
    x = min_x if "LEFT" in role else max_x if "RIGHT" in role else mid_x
    y = max_y if "TOP" in role else min_y if "BOTTOM" in role else mid_y
    offset_x, offset_y = _crop_extend_visual_offset(
        rig, effect_id, role, bounds_state=bounds_state
    )
    return (x + offset_x, y + offset_y)


def _crop_extend_visual_offset(rig, effect_id, role, *, bounds_state=None):
    """Separate converging Crop/Extend handles without changing their value.

    Side and corner controls normally sit exactly on the evaluated bounds.  At
    extreme crop values those eight points converge and become impossible to
    identify.  Once either visible span is smaller than the handle footprint we
    fan the relevant handles outwards.  Drag conversion subtracts this visual
    offset again, so the crop edge remains the source of truth.
    """
    effect_id = str(effect_id or "").upper()
    role = str(role or "").upper()
    _source, cropped, extended, _base_x, _base_y = (
        _crop_extend_bounds(rig) if bounds_state is None else bounds_state
    )
    bounds = cropped if effect_id == "CROP" else extended
    width = max(0.0, float(bounds[1]) - float(bounds[0]))
    height = max(0.0, float(bounds[3]) - float(bounds[2]))
    side_size = max(
        _control_display_size(rig, "CROP_EXTEND", "LEFT"),
        _control_display_size(rig, "CROP_EXTEND", "TOP"),
        1.0e-6,
    )
    # Four handle widths leave a clear central grip plus two corner grips.
    target_span = side_size * 4.2
    spread_x = max(0.0, (target_span - width) * 0.5)
    spread_y = max(0.0, (target_span - height) * 0.5)
    offset_x = -spread_x if "LEFT" in role else spread_x if "RIGHT" in role else 0.0
    offset_y = spread_y if "TOP" in role else -spread_y if "BOTTOM" in role else 0.0
    return offset_x, offset_y


def _crop_max_for_axis(rig, horizontal=True):
    try:
        source_width = int(rig.get("fbp_source_width", 0) or 0)
        source_height = int(rig.get("fbp_source_height", 0) or 0)
    except FBP_DATA_ERRORS:
        source_width = source_height = 0
    size = source_width if horizontal else source_height
    return max(0.0, min(1.999998, 2.0 - (2.0 / max(1, size)))) if size > 0 else 1.999998


def _crop_opposite_property(prop_name):
    name = str(prop_name or "").lower()
    if name.endswith("left"):
        return "fbp_crop_right"
    if name.endswith("right"):
        return "fbp_crop_left"
    if name.endswith("top"):
        return "fbp_crop_bottom"
    if name.endswith("bottom"):
        return "fbp_crop_top"
    return ""


def _clamp_crop_value(rig, prop_name, value):
    horizontal = str(prop_name).endswith(("_left", "_right"))
    axis_max = _crop_max_for_axis(rig, horizontal)
    opposite = _crop_opposite_property(prop_name)
    try:
        opposite_value = max(0.0, float(getattr(rig, opposite, 0.0))) if opposite else 0.0
    except FBP_DATA_ERRORS:
        opposite_value = 0.0
    allowed = max(0.0, axis_max - opposite_value)
    return max(0.0, min(allowed, float(value)))


def _crop_clamp_limits_for_role(rig, role, *, bounds_state=None):
    """Return plane-local hard limits for one Crop handle.

    The limits are applied as a Blender Limit Location constraint, so pressing G
    and moving freely cannot drag the helper past the source image bounds or
    through the opposite Crop edge. Values are recomputed from the opposite
    side before each sync because Crop is a four-sided constraint system.
    """
    role = str(role or "").upper()
    source, _cropped, _extended, base_x, base_y = (
        _crop_extend_bounds(rig) if bounds_state is None else bounds_state
    )
    src_min_x, src_max_x, src_min_y, src_max_y = source
    try:
        left = max(0.0, float(getattr(rig, "fbp_crop_left", 0.0)))
        right = max(0.0, float(getattr(rig, "fbp_crop_right", 0.0)))
        top = max(0.0, float(getattr(rig, "fbp_crop_top", 0.0)))
        bottom = max(0.0, float(getattr(rig, "fbp_crop_bottom", 0.0)))
    except FBP_DATA_ERRORS:
        left = right = top = bottom = 0.0
    h_max = _crop_max_for_axis(rig, True)
    v_max = _crop_max_for_axis(rig, False)
    left_allowed = max(0.0, h_max - right)
    right_allowed = max(0.0, h_max - left)
    bottom_allowed = max(0.0, v_max - top)
    top_allowed = max(0.0, v_max - bottom)

    # Defaults leave the unedited axis fixed by the transform locks; setting a
    # full source range keeps the constraint valid for corner handles too.
    min_x, max_x = src_min_x, src_max_x
    min_y, max_y = src_min_y, src_max_y
    if "LEFT" in role:
        min_x = src_min_x
        max_x = src_min_x + left_allowed * base_x
    if "RIGHT" in role:
        min_x = src_max_x - right_allowed * base_x
        max_x = src_max_x
    if "BOTTOM" in role:
        min_y = src_min_y
        max_y = src_min_y + bottom_allowed * base_y
    if "TOP" in role:
        min_y = src_max_y - top_allowed * base_y
        max_y = src_max_y
    if min_x > max_x:
        min_x = max_x = (min_x + max_x) * 0.5
    if min_y > max_y:
        min_y = max_y = (min_y + max_y) * 0.5
    return min_x, max_x, min_y, max_y


def _extend_max_for_axis(rig=None, horizontal=True):
    """Return the persistent viewport limit for one Extend axis.

    The UI keeps a compact soft range of 0..1, but typed values may exceed it.
    Once an axis reaches a larger value, its viewport handles retain that new
    limit instead of snapping back to 1.0 when the value is edited downward.
    Reset Extend explicitly restores the original limit.
    """
    key = KEY_EXTEND_HANDLE_LIMIT_X if horizontal else KEY_EXTEND_HANDLE_LIMIT_Y
    props = (
        ("fbp_extend_left", "fbp_extend_right")
        if horizontal else ("fbp_extend_bottom", "fbp_extend_top")
    )
    values = [float(EXTEND_HANDLE_MAX)]
    if rig is not None:
        try:
            values.append(float(rig.get(key, EXTEND_HANDLE_MAX) or EXTEND_HANDLE_MAX))
        except FBP_DATA_ERRORS:
            pass
        for prop_name in props:
            try:
                values.append(max(0.0, float(getattr(rig, prop_name, 0.0))))
            except FBP_DATA_ERRORS:
                pass
    return max(values)


def update_extend_handle_limits(rig, *, reset=False):
    """Grow or reset the persistent viewport limit used by Extend handles."""
    if rig is None:
        return False
    changed = False
    for horizontal, key, props in (
        (True, KEY_EXTEND_HANDLE_LIMIT_X, ("fbp_extend_left", "fbp_extend_right")),
        (False, KEY_EXTEND_HANDLE_LIMIT_Y, ("fbp_extend_bottom", "fbp_extend_top")),
    ):
        del horizontal
        desired = float(EXTEND_HANDLE_MAX)
        if not reset:
            try:
                desired = max(
                    desired,
                    float(rig.get(key, EXTEND_HANDLE_MAX) or EXTEND_HANDLE_MAX),
                    *(max(0.0, float(getattr(rig, prop_name, 0.0))) for prop_name in props),
                )
            except FBP_DATA_ERRORS:
                continue
        try:
            current = float(rig.get(key, EXTEND_HANDLE_MAX) or EXTEND_HANDLE_MAX)
            if abs(current - desired) > 1.0e-7:
                rig[key] = desired
                changed = True
        except FBP_DATA_ERRORS:
            continue
    return changed


def _clamp_extend_value(rig, prop_name, value):
    horizontal = str(prop_name).endswith(("_left", "_right"))
    allowed = _extend_max_for_axis(rig, horizontal)
    return max(0.0, min(float(allowed), float(value)))


def _extend_clamp_limits_for_role(rig, role, *, bounds_state=None):
    """Return plane-local hard limits for one Extend handle.

    Extend starts from the current cropped bounds and can move outward only, up
    to the manual handle limit. Corner handles combine the two side limits.
    """
    role = str(role or "").upper()
    _source, cropped, _extended, base_x, base_y = (
        _crop_extend_bounds(rig) if bounds_state is None else bounds_state
    )
    crop_min_x, crop_max_x, crop_min_y, crop_max_y = cropped
    h_max = _extend_max_for_axis(rig, True)
    v_max = _extend_max_for_axis(rig, False)

    min_x, max_x = crop_min_x - h_max * base_x, crop_max_x + h_max * base_x
    min_y, max_y = crop_min_y - v_max * base_y, crop_max_y + v_max * base_y
    if "LEFT" in role:
        min_x = crop_min_x - h_max * base_x
        max_x = crop_min_x
    if "RIGHT" in role:
        min_x = crop_max_x
        max_x = crop_max_x + h_max * base_x
    if "BOTTOM" in role:
        min_y = crop_min_y - v_max * base_y
        max_y = crop_min_y
    if "TOP" in role:
        min_y = crop_max_y
        max_y = crop_max_y + v_max * base_y
    if min_x > max_x:
        min_x = max_x = (min_x + max_x) * 0.5
    if min_y > max_y:
        min_y = max_y = (min_y + max_y) * 0.5
    return min_x, max_x, min_y, max_y


def _apply_crop_extend_transform_limits(
    control, rig, effect_id, role, *, bounds_state=None, depth=None
):
    """Install or remove hard transform limits for Crop/Extend helpers."""
    if control is None:
        return False
    effect_id = str(effect_id or "").upper()
    changed = False
    try:
        constraint = control.constraints.get(CROP_CLAMP_CONSTRAINT)
        if effect_id not in {"CROP", "EXTEND"}:
            if constraint is not None:
                control.constraints.remove(constraint)
                changed = True
            return changed
        if constraint is None:
            constraint = control.constraints.new(type="LIMIT_LOCATION")
            constraint.name = CROP_CLAMP_CONSTRAINT
            changed = True
        if effect_id == "EXTEND":
            min_x, max_x, min_y, max_y = _extend_clamp_limits_for_role(
                rig, role, bounds_state=bounds_state
            )
        else:
            min_x, max_x, min_y, max_y = _crop_clamp_limits_for_role(
                rig, role, bounds_state=bounds_state
            )
        offset_x, offset_y = _crop_extend_visual_offset(
            rig, effect_id, role, bounds_state=bounds_state
        )
        min_x += offset_x
        max_x += offset_x
        min_y += offset_y
        max_y += offset_y
        control_depth = _control_depth(rig) if depth is None else float(depth)
        settings = {
            "owner_space": "LOCAL",
            "use_min_x": True, "use_max_x": True,
            "use_min_y": True, "use_max_y": True,
            "use_min_z": True, "use_max_z": True,
            "min_x": float(min_x), "max_x": float(max_x),
            "min_y": float(min_y), "max_y": float(max_y),
            "min_z": control_depth, "max_z": control_depth,
        }
        settings["use_transform_limit"] = True
        for key, value in settings.items():
            if not hasattr(constraint, key):
                continue
            current = getattr(constraint, key)
            if isinstance(value, bool):
                if bool(current) != bool(value):
                    setattr(constraint, key, bool(value)); changed = True
            elif isinstance(value, str):
                if str(current) != value:
                    setattr(constraint, key, value); changed = True
            else:
                if abs(float(current) - float(value)) > 1.0e-7:
                    setattr(constraint, key, float(value)); changed = True
    except FBP_DATA_ERRORS:
        return False
    return changed


def _snap_crop_extend_control_to_valid_location(control, rig, effect_id, role):
    """Immediately pull a dragged Crop helper back onto its legal edge.

    This prevents the visible helper from lagging outside the image while the
    mesh update is queued, especially after free G transforms in the viewport.
    """
    effect_id = str(effect_id or "").upper()
    if control is None or effect_id not in {"CROP", "EXTEND"}:
        return False
    try:
        values = _crop_extend_values_from_handle(
            rig, effect_id, role, float(control.location.x), float(control.location.y)
        )
        source, cropped, _extended, base_x, base_y = _crop_extend_bounds(rig)
        src_min_x, src_max_x, src_min_y, src_max_y = source
        crop_min_x, crop_max_x, crop_min_y, crop_max_y = cropped
        x = float(control.location.x)
        y = float(control.location.y)
        role = str(role or "").upper()
        if effect_id == "CROP":
            if "LEFT" in role and "fbp_crop_left" in values:
                x = src_min_x + float(values["fbp_crop_left"]) * base_x
            if "RIGHT" in role and "fbp_crop_right" in values:
                x = src_max_x - float(values["fbp_crop_right"]) * base_x
            if "BOTTOM" in role and "fbp_crop_bottom" in values:
                y = src_min_y + float(values["fbp_crop_bottom"]) * base_y
            if "TOP" in role and "fbp_crop_top" in values:
                y = src_max_y - float(values["fbp_crop_top"]) * base_y
        else:
            if "LEFT" in role and "fbp_extend_left" in values:
                x = crop_min_x - float(values["fbp_extend_left"]) * base_x
            if "RIGHT" in role and "fbp_extend_right" in values:
                x = crop_max_x + float(values["fbp_extend_right"]) * base_x
            if "BOTTOM" in role and "fbp_extend_bottom" in values:
                y = crop_min_y - float(values["fbp_extend_bottom"]) * base_y
            if "TOP" in role and "fbp_extend_top" in values:
                y = crop_max_y + float(values["fbp_extend_top"]) * base_y
        offset_x, offset_y = _crop_extend_visual_offset(rig, effect_id, role)
        return _set_control_transform(
            control,
            location=(x + offset_x, y + offset_y),
            angle=0.0,
            scale_x=1.0,
        )
    except FBP_DATA_ERRORS:
        return False


def _crop_extend_values_from_handle(rig, effect_id, role, x, y):
    effect_id = str(effect_id or "").upper()
    role = str(role or "").upper()
    bounds_state = _crop_extend_bounds(rig)
    offset_x, offset_y = _crop_extend_visual_offset(
        rig, effect_id, role, bounds_state=bounds_state
    )
    x = float(x) - offset_x
    y = float(y) - offset_y
    source, cropped, _extended, base_x, base_y = bounds_state
    src_min_x, src_max_x, src_min_y, src_max_y = source
    crop_min_x, crop_max_x, crop_min_y, crop_max_y = cropped
    values = {}
    if effect_id == "CROP":
        if "LEFT" in role:
            values["fbp_crop_left"] = _clamp_crop_value(rig, "fbp_crop_left", (float(x) - src_min_x) / base_x)
        if "RIGHT" in role:
            values["fbp_crop_right"] = _clamp_crop_value(rig, "fbp_crop_right", (src_max_x - float(x)) / base_x)
        if "BOTTOM" in role:
            values["fbp_crop_bottom"] = _clamp_crop_value(rig, "fbp_crop_bottom", (float(y) - src_min_y) / base_y)
        if "TOP" in role:
            values["fbp_crop_top"] = _clamp_crop_value(rig, "fbp_crop_top", (src_max_y - float(y)) / base_y)
    elif effect_id == "EXTEND":
        if "LEFT" in role:
            values["fbp_extend_left"] = _clamp_extend_value(rig, "fbp_extend_left", (crop_min_x - float(x)) / base_x)
        if "RIGHT" in role:
            values["fbp_extend_right"] = _clamp_extend_value(rig, "fbp_extend_right", (float(x) - crop_max_x) / base_x)
        if "BOTTOM" in role:
            values["fbp_extend_bottom"] = _clamp_extend_value(rig, "fbp_extend_bottom", (crop_min_y - float(y)) / base_y)
        if "TOP" in role:
            values["fbp_extend_top"] = _clamp_extend_value(rig, "fbp_extend_top", (float(y) - crop_max_y) / base_y)
    return values


def _refresh_crop_extend_from_control(rig, property_names):
    if rig is None:
        return False
    try:
        from .core import update_object_padding_cb
        update_object_padding_cb(rig, getattr(bpy, "context", None))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not refresh Crop/Extend viewport control", exc)
        return False
    try:
        # The edited handle remains user-driven; update the other handles after
        # the mesh rebuild so side/corner controls stay on the visible bounds.
        effect_id = "CROP" if any(str(name).startswith("fbp_crop_") for name in property_names) else "EXTEND"
        schedule_sync_controls_from_properties(rig, effect_id, create=True)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return True


def sync_controls_from_properties(rig, effect_id, *, create=False):
    effect_id = str(effect_id or "").upper()
    specs = CONTROL_SPECS.get(effect_id, ())
    if not rig or not specs:
        return False
    changed = False
    controls = {}
    crop_extend_state = _crop_extend_bounds(rig) if effect_id in {"CROP", "EXTEND"} else None
    crop_extend_depth = _control_depth(rig) if crop_extend_state is not None else None
    for spec in specs:
        role = str(spec.get("role", "CONTROL") or "CONTROL").upper()
        control = find_effect_control(rig, effect_id, role)
        if control is None and create:
            control = ensure_effect_control(rig, effect_id, spec)
        if control is not None:
            controls[role] = control

    for spec in specs:
        role = str(spec.get("role", "CONTROL") or "CONTROL").upper()
        mode = str(spec.get("mode", "POINT") or "POINT").upper()
        control = controls.get(role)
        if control is None:
            continue
        if control.name in _PENDING_CONTROL_SIGNATURES:
            continue
        if mode in {"POINT", "OFFSET"}:
            x = float(getattr(rig, spec["x"], 0.5 if mode == "POINT" else 0.0))
            y = float(getattr(rig, spec["y"], 0.5 if mode == "POINT" else 0.0))
            if mode == "OFFSET":
                x += 0.5; y += 0.5
            angle = (
                float(getattr(rig, spec["angle"], 0.0)) * float(spec.get("angle_sign", 1.0) or 1.0)
                if spec.get("angle") else None
            )
            changed = _set_control_transform(
                control, location=_uv_to_local(rig, x, y), angle=angle
            ) or changed
        elif mode == "DIRECTION":
            _plane, bounds, _uv = _plane_and_mapping(rig)
            width = max(abs(bounds[1] - bounds[0]), 1.0e-6)
            distance = float(getattr(rig, spec["distance"], 0.0))
            angle = float(getattr(rig, spec["angle"], 0.0))
            anchor_x = float(getattr(rig, spec.get("x", ""), 0.5)) if spec.get("x") else 0.5
            anchor_y = float(getattr(rig, spec.get("y", ""), 0.5)) if spec.get("y") else 0.5
            changed = _set_control_transform(
                control,
                location=_uv_to_local(rig, anchor_x, anchor_y),
                angle=angle,
                # Keep a visible handle at zero distance without folding that
                # display floor back into the effect value on the reverse path.
                scale_x=DIRECTION_HANDLE_MIN_SCALE + max(0.0, (distance / 100.0) * width),
            ) or changed
        elif mode == "ANGLE":
            angle = float(getattr(rig, spec["angle"], 0.0)) * float(spec.get("angle_sign", 1.0) or 1.0)
            changed = _set_control_transform(
                control,
                location=_uv_to_local(rig, 0.5, 0.5),
                angle=angle,
                scale_x=1.0,
            ) or changed
        elif mode == "VECTOR_DIRECTION":
            vector_prop = spec.get("vector", "")
            vector = getattr(rig, vector_prop, (0.0, 0.0, 1.0))
            # Pending viewport edits are skipped at the top of this function.
            # Outside an active drag, the registered property remains the source
            # of truth, so UI edits must rotate the helper as well as the effect.
            changed = _set_control_transform(
                control,
                location=_uv_to_local(rig, 0.5, 0.5),
                rotation=_control_rotation_from_direction(rig, vector),
                scale_x=1.0,
            ) or changed
        elif mode == "CROP_EXTEND":
            changed = _apply_crop_extend_transform_limits(
                control,
                rig,
                effect_id,
                role,
                bounds_state=crop_extend_state,
                depth=crop_extend_depth,
            ) or changed
            changed = _set_control_transform(
                control,
                location=_crop_extend_handle_location(
                    rig, effect_id, role, bounds_state=crop_extend_state
                ),
                angle=0.0,
                scale_x=1.0,
            ) or changed

    if {"IN", "OUT"}.issubset(controls):
        in_control, out_control = controls["IN"], controls["OUT"]
        center_control = controls.get("CENTER")
        if (
            in_control.name in _PENDING_CONTROL_SIGNATURES
            or out_control.name in _PENDING_CONTROL_SIGNATURES
            or (center_control is not None and center_control.name in _PENDING_CONTROL_SIGNATURES)
        ):
            return changed
        mode = _range_mode_for_effect(effect_id)
        if mode == "GRADIENT_RANGE":
            cx = float(getattr(rig, "fbp_gradient_mask_center_x", 0.5))
            cy = float(getattr(rig, "fbp_gradient_mask_center_y", 0.5))
            angle = float(getattr(rig, "fbp_gradient_mask_angle", 0.0))
            position = float(getattr(rig, "fbp_gradient_mask_position", 0.5))
            scale = max(float(getattr(rig, "fbp_gradient_mask_scale", 1.0)), 1.0e-6)
            feather = max(float(getattr(rig, "fbp_gradient_mask_feather", 0.2)), 0.0)
            dx, dy = math.cos(angle), math.sin(angle)
            inv_scale = 1.0 / scale
            mx = cx + dx * (position - 0.5) * inv_scale
            my = cy + dy * (position - 0.5) * inv_scale
            half = feather * inv_scale * 0.5
            changed = _set_range_endpoint_transforms(
                rig, in_control, out_control,
                (mx - dx * half, my - dy * half),
                (mx + dx * half, my + dy * half),
            ) or changed
        elif mode == "GRADIENT_LIGHT_RANGE":
            angle = float(getattr(rig, "fbp_gradient_light_angle", 0.0))
            position = float(getattr(rig, "fbp_gradient_shadow_position", 0.0))
            softness = max(float(getattr(rig, "fbp_gradient_softness", 0.2)), 0.001)
            center_x = float(getattr(rig, "fbp_gradient_light_center_x", 0.5))
            center_y = float(getattr(rig, "fbp_gradient_light_center_y", 0.5))
            dx, dy = math.cos(angle), math.sin(angle)
            mx = center_x + dx * position
            my = center_y + dy * position
            half = softness * 0.5
            changed = _set_range_endpoint_transforms(
                rig, in_control, out_control,
                (mx - dx * half, my - dy * half),
                (mx + dx * half, my + dy * half),
            ) or changed
        elif mode == "TILT_RANGE":
            position = float(getattr(rig, "fbp_tilt_shift_position", 0.5))
            width = max(float(getattr(rig, "fbp_tilt_shift_width", 0.25)), 0.001)
            band_angle = float(getattr(rig, "fbp_tilt_shift_angle", 0.0))
            normal_angle = band_angle + math.pi * 0.5
            nx, ny = math.cos(normal_angle), math.sin(normal_angle)
            mx = 0.5 + nx * (position - 0.5)
            my = 0.5 + ny * (position - 0.5)
            changed = _set_range_endpoint_transforms(
                rig, in_control, out_control,
                (mx - nx * width * 0.5, my - ny * width * 0.5),
                (mx + nx * width * 0.5, my + ny * width * 0.5),
            ) or changed
        changed = _sync_range_center_from_endpoints(rig, effect_id, controls) or changed
    return changed


def _tag_effect_control_ui_redraw():
    """Refresh panels after silent viewport-to-RNA controller writes."""
    try:
        windows = tuple(getattr(getattr(bpy.context, "window_manager", None), "windows", ()) or ())
    except FBP_DATA_ERRORS:
        return
    for window in windows:
        try:
            screen = getattr(window, "screen", None)
            for area in tuple(getattr(screen, "areas", ()) or ()):
                if str(getattr(area, "type", "") or "") in {
                    "VIEW_3D", "PROPERTIES", "NODE_EDITOR"
                }:
                    area.tag_redraw()
        except FBP_DATA_ERRORS:
            continue


def _set_property(rig, prop_name, value):
    """Set one driven property only when the effective value changed."""
    if not prop_name or not hasattr(rig, prop_name):
        return False
    try:
        current = getattr(rig, prop_name)
        if isinstance(current, bool) or isinstance(value, bool):
            if bool(current) == bool(value):
                return False
        elif isinstance(current, (int, float)) and isinstance(value, (int, float)):
            if abs(float(current) - float(value)) <= 1.0e-7:
                return False
        elif current == value:
            return False
    except FBP_DATA_ERRORS:
        pass
    return fbp_set_rna_property_silent(rig, prop_name, value)


def schedule_sync_controls_from_properties(rig, effect_id, *, create=False):
    """Coalesce RNA slider updates before mirroring them to viewport controls.

    Effect values themselves are still pushed immediately by geometry_nodes; the
    helper Empty transform only needs to catch up once per UI tick. This avoids
    scanning and rewriting helper objects for every intermediate slider sample.
    """
    effect_id = str(effect_id or "").upper()
    if not rig or not effect_has_controls(effect_id):
        return False
    try:
        rig_name = str(getattr(rig, "name", "") or "")
        rig_key = int(fbp_obj_runtime_key(rig) or 0)
    except FBP_DATA_ERRORS:
        return False
    if not rig_name:
        return False

    def _sync():
        try:
            target = fbp_find_id_by_runtime_key(
                getattr(bpy.data, "objects", ()), rig_key, rig_name
            )
            if target is None or not bool(getattr(target, "is_fbp_control", False)):
                return None
            sync_controls_from_properties(target, effect_id, create=create)
        except FBP_DATA_ERRORS:
            pass
        return None

    try:
        accepted = schedule_once(
            f"effect_controls.sync_props.{rig_key}.{effect_id}.{int(bool(create))}",
            _sync,
            first_interval=0.0,
        )
        if accepted:
            return True
        if not fbp_undo_guard_active() and not fbp_render_mutation_blocked():
            return bool(sync_controls_from_properties(rig, effect_id, create=create))
        return False
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        try:
            return bool(sync_controls_from_properties(rig, effect_id, create=create))
        except FBP_DATA_ERRORS:
            return False


def _apply_control_transform_snapshot(control, snapshot):
    """Copy one evaluated viewport transform onto the original helper datablock.

    Depsgraph callbacks can expose an evaluated Object whose transform is newer
    than ``Object.original``.  Preserve that exact transform before resolving the
    original datablock, otherwise the Empty visibly moves but its driven RNA
    properties keep the previous value.
    """
    if control is None or len(tuple(snapshot or ())) < 7:
        return False
    values = tuple(float(value) for value in tuple(snapshot)[:7])
    key = str(getattr(control, "name", "") or "")
    _SYNC_GUARD.add(key)
    try:
        control.location = values[0:3]
        control.rotation_euler = values[3:6]
        control.scale.x = values[6]
    except FBP_DATA_ERRORS:
        return False
    finally:
        _SYNC_GUARD.discard(key)
    return True


def schedule_properties_from_control(control, *, transform_snapshot=None):
    """Apply a moved helper from a safe timer instead of inside depsgraph."""
    if not is_effect_control(control):
        return False
    try:
        control_name = str(control.name)
        control_key = fbp_obj_runtime_key(control)
        snapshot = tuple(transform_snapshot or _control_signature(control))
        _PENDING_CONTROL_SIGNATURES[control_name] = snapshot
        _PENDING_CONTROL_TRANSFORMS[control_name] = snapshot
        mode = str(control.get(KEY_MODE, "") or "").upper()
    except FBP_DATA_ERRORS:
        return False

    def apply_latest_transform():
        try:
            current = fbp_find_id_by_runtime_key(
                getattr(bpy.data, "objects", ()), control_key, control_name
            )
            snapshot_now = _PENDING_CONTROL_TRANSFORMS.get(control_name, snapshot)
            if current is not None and is_effect_control(current):
                if snapshot_now and _control_signature(current) != tuple(snapshot_now):
                    _apply_control_transform_snapshot(current, snapshot_now)
                sync_properties_from_control(current)
        finally:
            _PENDING_CONTROL_SIGNATURES.pop(control_name, None)
            _PENDING_CONTROL_TRANSFORMS.pop(control_name, None)
        return None

    try:
        accepted = schedule_once(
            f"effect_controls.apply.{control_name}",
            apply_latest_transform,
            first_interval=0.0 if mode == "CROP_EXTEND" else 0.01,
        )
        if not accepted:
            _PENDING_CONTROL_SIGNATURES.pop(control_name, None)
            snapshot_now = _PENDING_CONTROL_TRANSFORMS.pop(control_name, snapshot)
            if not fbp_undo_guard_active() and not fbp_render_mutation_blocked():
                try:
                    if snapshot_now and _control_signature(control) != tuple(snapshot_now):
                        _apply_control_transform_snapshot(control, snapshot_now)
                    return bool(sync_properties_from_control(control))
                except FBP_DATA_ERRORS:
                    return False
        return bool(accepted)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        _PENDING_CONTROL_SIGNATURES.pop(control_name, None)
        snapshot_now = _PENDING_CONTROL_TRANSFORMS.pop(control_name, snapshot)
        if not fbp_undo_guard_active() and not fbp_render_mutation_blocked():
            try:
                if snapshot_now and _control_signature(control) != tuple(snapshot_now):
                    _apply_control_transform_snapshot(control, snapshot_now)
                return bool(sync_properties_from_control(control))
            except FBP_DATA_ERRORS:
                pass
        return False


def _refresh_effect_from_control(rig, effect_id, property_names):
    """Refresh only the owner rig after a viewport-control edit.

    Viewport helpers represent one concrete layer. Routing their edits through
    the generic RNA callback would also modify every other selected rig, which
    is useful for panel multi-edit but surprising for direct manipulation.
    """
    property_names = {str(name) for name in tuple(property_names or ()) if name}
    if rig is None or not property_names:
        return False
    if str(effect_id or "").upper() in {"CROP", "EXTEND"}:
        return _refresh_crop_extend_from_control(rig, property_names)
    try:
        from .effects_registry import fbp_effect_definition
        from .geometry_nodes import fbp_update_geometry_effect, fbp_update_shader_effect
        definition = fbp_effect_definition(effect_id)
        if str(definition.get("kind", "") or "").upper() == "GEOMETRY":
            return bool(fbp_update_geometry_effect(
                rig, effect_id, sync_alpha=False, property_names=property_names
            ))
        return bool(fbp_update_shader_effect(
            rig, effect_id, property_names=property_names
        ))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not refresh effect from viewport control", exc)
        return False


def _rna_property_default(obj, prop_name):
    """Return the registered default for one control-driven RNA property."""
    try:
        prop = obj.bl_rna.properties.get(str(prop_name))
        if prop is None:
            raise AttributeError(prop_name)
        if bool(getattr(prop, "is_array", False)):
            return tuple(prop.default_array)
        return prop.default
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return getattr(obj, prop_name)


def reset_effect_control_properties(rig, effect_id):
    """Reset only the properties represented by one viewport control."""
    effect_id = str(effect_id or "").upper()
    properties = tuple(sorted(effect_control_driven_properties(effect_id)))
    if rig is None or not properties:
        return False
    changed_properties = set()
    for prop_name in properties:
        if not hasattr(rig, prop_name):
            continue
        default = _rna_property_default(rig, prop_name)
        try:
            current = getattr(rig, prop_name)
            same = (
                abs(float(current) - float(default)) <= 1.0e-7
                if isinstance(current, (int, float)) and isinstance(default, (int, float))
                else current == default
            )
        except (ReferenceError, RuntimeError, TypeError, ValueError):
            same = False
        if same:
            continue
        if fbp_set_rna_property_silent(rig, prop_name, default):
            changed_properties.add(prop_name)
    if changed_properties:
        _refresh_effect_from_control(rig, effect_id, changed_properties)
    sync_controls_from_properties(rig, effect_id, create=True)
    return bool(changed_properties)


def sync_properties_from_control(control):
    if not is_effect_control(control) or control.name in _SYNC_GUARD:
        return False
    rig = effect_control_owner(control)
    if rig is None:
        return False
    effect_id = str(control.get(KEY_EFFECT_ID, "") or "").upper()
    try:
        from .geometry_nodes import fbp_effect_is_active
        if not fbp_effect_is_active(rig, effect_id):
            return False
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    role = str(control.get(KEY_ROLE, "") or "").upper()
    mode = str(control.get(KEY_MODE, "") or "").upper()
    spec = next((item for item in CONTROL_SPECS.get(effect_id, ()) if item.get("role") == role), None)
    if not spec:
        return False

    changed_properties = set()

    def set_driven(prop_name, value):
        if _set_property(rig, prop_name, value):
            changed_properties.add(str(prop_name))
            return True
        return False

    if mode in {"POINT", "OFFSET"}:
        u, v = _local_to_uv(rig, control.location.x, control.location.y)
        if mode == "OFFSET":
            u -= 0.5
            v -= 0.5
        set_driven(spec.get("x"), u)
        set_driven(spec.get("y"), v)
        if spec.get("angle"):
            set_driven(spec.get("angle"), float(control.rotation_euler.z) * float(spec.get("angle_sign", 1.0) or 1.0))
    elif mode == "DIRECTION":
        _plane, bounds, _uv = _plane_and_mapping(rig)
        width = max(abs(bounds[1] - bounds[0]), 1.0e-6)
        distance = max(
            0.0,
            (float(control.scale.x) - DIRECTION_HANDLE_MIN_SCALE) / width * 100.0,
        )
        anchor_x, anchor_y = _local_to_uv(rig, control.location.x, control.location.y)
        set_driven(spec.get("x"), anchor_x)
        set_driven(spec.get("y"), anchor_y)
        set_driven(spec.get("angle"), float(control.rotation_euler.z) * float(spec.get("angle_sign", 1.0) or 1.0))
        set_driven(spec.get("distance"), distance)
    elif mode == "ANGLE":
        set_driven(spec.get("angle"), float(control.rotation_euler.z) * float(spec.get("angle_sign", 1.0) or 1.0))
    elif mode == "VECTOR_DIRECTION":
        set_driven(spec.get("vector"), _control_direction_vector(rig, control))
    elif mode == "CROP_EXTEND":
        values = _crop_extend_values_from_handle(
            rig, effect_id, role, float(control.location.x), float(control.location.y)
        )
        for prop_name, value in values.items():
            set_driven(prop_name, value)
        _apply_crop_extend_transform_limits(control, rig, effect_id, role)
        _snap_crop_extend_control_to_valid_location(control, rig, effect_id, role)
    elif mode in {"GRADIENT_RANGE", "GRADIENT_LIGHT_RANGE", "TILT_RANGE", "RANGE_CENTER"}:
        pair_mode = str(spec.get("range_mode", mode) or mode).upper()
        in_control, out_control = _range_controls(rig, effect_id)
        if in_control is None or out_control is None:
            return False
        if mode == "RANGE_CENTER":
            reference = _range_reference_length(rig)
            half_length = max(float(control.scale.x) * reference * 0.5, 1.0e-6)
            angle = float(control.rotation_euler.z)
            dx, dy = math.cos(angle) * half_length, math.sin(angle) * half_length
            cx, cy = float(control.location.x), float(control.location.y)
            _set_control_transform(in_control, location=(cx - dx, cy - dy), angle=angle)
            _set_control_transform(out_control, location=(cx + dx, cy + dy), angle=angle)
        try:
            stored = tuple(float(value) for value in control.get(KEY_SYNC_SIGNATURE, ()) or ())
        except FBP_DATA_ERRORS:
            stored = ()
        current = _control_signature(control)
        rotation_changed = bool(
            len(stored) >= 6 and len(current) >= 6
            and abs(float(current[5]) - float(stored[5])) > 1.0e-6
        )
        if mode != "RANGE_CENTER" and rotation_changed and pair_mode in {"GRADIENT_RANGE", "GRADIENT_LIGHT_RANGE", "TILT_RANGE"}:
            midpoint_x = (float(in_control.location.x) + float(out_control.location.x)) * 0.5
            midpoint_y = (float(in_control.location.y) + float(out_control.location.y)) * 0.5
            half_length = max(
                math.hypot(
                    float(out_control.location.x) - float(in_control.location.x),
                    float(out_control.location.y) - float(in_control.location.y),
                ) * 0.5,
                1.0e-6,
            )
            angle = float(control.rotation_euler.z)
            dx, dy = math.cos(angle) * half_length, math.sin(angle) * half_length
            _set_control_transform(
                in_control,
                location=(midpoint_x - dx, midpoint_y - dy),
                angle=angle,
            )
            _set_control_transform(
                out_control,
                location=(midpoint_x + dx, midpoint_y + dy),
                angle=angle,
            )
        u1, v1 = _local_to_uv(rig, in_control.location.x, in_control.location.y)
        u2, v2 = _local_to_uv(rig, out_control.location.x, out_control.location.y)
        if pair_mode == "TILT_RANGE":
            dx, dy = u2 - u1, v2 - v1
            normal_angle = math.atan2(dy, dx)
            band_angle = normal_angle - math.pi * 0.5
            nx, ny = math.cos(normal_angle), math.sin(normal_angle)
            mx, my = (u1 + u2) * 0.5, (v1 + v2) * 0.5
            position = 0.5 + (mx - 0.5) * nx + (my - 0.5) * ny
            set_driven("fbp_tilt_shift_position", position)
            set_driven("fbp_tilt_shift_width", max(math.hypot(dx, dy), 0.001))
            set_driven("fbp_tilt_shift_angle", band_angle)
        elif pair_mode == "GRADIENT_LIGHT_RANGE":
            dx, dy = u2 - u1, v2 - v1
            angle = math.atan2(dy, dx)
            mx, my = (u1 + u2) * 0.5, (v1 + v2) * 0.5
            set_driven("fbp_gradient_light_center_x", mx)
            set_driven("fbp_gradient_light_center_y", my)
            set_driven("fbp_gradient_light_angle", angle)
            set_driven("fbp_gradient_shadow_position", 0.0)
            set_driven("fbp_gradient_softness", max(math.hypot(dx, dy), 0.001))
        else:
            dx, dy = u2 - u1, v2 - v1
            angle = math.atan2(dy, dx)
            scale = max(float(getattr(rig, "fbp_gradient_mask_scale", 1.0)), 1.0e-6)
            position = float(getattr(rig, "fbp_gradient_mask_position", 0.5))
            mx, my = (u1 + u2) * 0.5, (v1 + v2) * 0.5
            # Preserve the Position slider. The visible transition midpoint is
            # offset from Center by (Position - .5) / Scale in shader space.
            set_driven("fbp_gradient_mask_center_x", mx - math.cos(angle) * (position - 0.5) / scale)
            set_driven("fbp_gradient_mask_center_y", my - math.sin(angle) * (position - 0.5) / scale)
            set_driven("fbp_gradient_mask_angle", angle)
            set_driven("fbp_gradient_mask_feather", math.hypot(dx, dy) * scale)
        _sync_range_center_from_endpoints(rig, effect_id)

    if changed_properties:
        _refresh_effect_from_control(rig, effect_id, changed_properties)
        _tag_effect_control_ui_redraw()
    signature = _control_signature(control)
    try:
        stored = tuple(float(value) for value in control.get(KEY_SYNC_SIGNATURE, ()) or ())
    except FBP_DATA_ERRORS:
        stored = ()
    if signature != stored:
        control[KEY_SYNC_SIGNATURE] = list(signature)
    return bool(changed_properties)

def is_crop_extend_bounds_guide(obj):
    try:
        return bool(obj and obj.get(KEY_IS_BOUNDS_GUIDE, False))
    except FBP_DATA_ERRORS:
        return False


def _guide_owner(obj):
    if not is_crop_extend_bounds_guide(obj):
        return None
    try:
        plane = getattr(obj, "parent", None)
        rig = getattr(plane, "parent", None) if plane else None
        if rig and bool(getattr(rig, "is_fbp_control", False)):
            return rig
        name = str(obj.get(KEY_GUIDE_OWNER, "") or "")
        rig = bpy.data.objects.get(name) if name else None
        return rig if rig and bool(getattr(rig, "is_fbp_control", False)) else None
    except FBP_DATA_ERRORS:
        return None


def _find_crop_extend_guide(rig):
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    candidates = []
    try:
        candidates.extend(tuple(getattr(plane, "children", ()) or ()))
    except FBP_DATA_ERRORS:
        pass
    for name in tuple(_GUIDE_NAMES):
        obj = bpy.data.objects.get(name)
        if obj is None:
            _GUIDE_NAMES.discard(name)
        else:
            candidates.append(obj)
    seen = set()
    for obj in candidates:
        try:
            pointer = int(fbp_obj_runtime_key(obj) or 0)
        except FBP_DATA_ERRORS:
            continue
        if pointer in seen:
            continue
        seen.add(pointer)
        if not is_crop_extend_bounds_guide(obj):
            continue
        if getattr(obj, "parent", None) is plane or _guide_owner(obj) is rig:
            return obj
    return None


def _set_guide_visibility(guide, visible):
    if guide is None:
        return False
    hidden = not bool(visible)
    changed = False
    try:
        if bool(getattr(guide, "hide_viewport", False)) != hidden:
            guide.hide_viewport = hidden
            changed = True
        try:
            current = bool(guide.hide_get())
        except FBP_DATA_ERRORS:
            current = not hidden
        if current != hidden:
            guide.hide_set(hidden)
            changed = True
        if not bool(getattr(guide, "hide_render", False)):
            guide.hide_render = True
            changed = True
        if not bool(getattr(guide, "hide_select", False)):
            guide.hide_select = True
            changed = True
    except FBP_DATA_ERRORS:
        return False
    return changed


def sync_crop_extend_bounds_guide(rig, visible=None):
    """Hide the retired source-bounds guide.

    Crop/Extend now use explicit side and corner handles. The old original-size
    wire rectangle was visually confusing because it stayed on the source bounds
    while the plane mesh changed, so existing guides are kept non-rendering and
    hidden instead of being shown beside the active handles.
    """
    guide = _find_crop_extend_guide(rig)
    if guide is None:
        return False
    return _set_guide_visibility(guide, False)


def _set_control_visibility(control, visible):
    hidden = not bool(visible)
    changed = False
    try:
        if not bool(getattr(control, "hide_render", False)):
            control.hide_render = True
            changed = True
        if bool(getattr(control, "hide_viewport", False)) != hidden:
            control.hide_viewport = hidden
            changed = True
        try:
            hidden_in_view_layer = bool(control.hide_get())
        except FBP_DATA_ERRORS:
            hidden_in_view_layer = not hidden
        if hidden_in_view_layer != hidden:
            control.hide_set(hidden)
            changed = True
        if bool(getattr(control, "hide_select", False)) != hidden:
            control.hide_select = hidden
            changed = True
        if hidden:
            try:
                if bool(control.select_get()):
                    control.select_set(False)
                    changed = True
            except FBP_DATA_ERRORS:
                pass
    except FBP_DATA_ERRORS:
        return False
    return changed


def remove_effect_controls(rig, effect_id):
    effect_id = str(effect_id or "").upper()
    removed = False
    for child in tuple(_candidate_effect_controls(rig, include_cached=True)):
        if not _helper_matches(
            child, rig, effect_id, str(child.get(KEY_ROLE, "") or "").upper()
        ):
            continue
        try:
            removed = bool(_remove_control_object(child)) or removed
        except FBP_DATA_ERRORS:
            continue
    return removed


def cleanup_orphan_effect_controls(scene):
    """Remove only FBP helper empties whose plane or rig no longer exists."""
    if scene is None:
        return 0
    removed = 0
    tracked_names = tuple(_CONTROL_NAMES) + tuple(_GUIDE_NAMES)
    objects = []
    for name in tracked_names:
        obj = bpy.data.objects.get(str(name or ""))
        if obj is None:
            _CONTROL_NAMES.discard(name)
            _GUIDE_NAMES.discard(name)
            continue
        objects.append(obj)
    for control in tuple(objects):
        if not (is_effect_control(control) or is_crop_extend_bounds_guide(control)):
            continue
        keep = False
        try:
            plane = getattr(control, "parent", None)
            rig = effect_control_owner(control) if is_effect_control(control) else _guide_owner(control)
            keep = bool(
                plane
                and getattr(plane, "type", "") == "MESH"
                and bool(getattr(plane, "is_fbp_plane", False))
                and rig
                and bool(getattr(rig, "is_fbp_control", False))
                and getattr(plane, "parent", None) is rig
                and scene.objects.get(plane.name) is plane
                and scene.objects.get(rig.name) is rig
            )
        except FBP_DATA_ERRORS:
            keep = False
        if keep:
            continue
        try:
            if _remove_control_object(control):
                removed += 1
        except FBP_DATA_ERRORS:
            continue
    return removed


def _context_scene_objects(context=None):
    """Return scene objects with a tiny cache for controller visibility passes.

    Several controller systems ask for the same scene-object tuple during one
    selection/depsgraph burst. Building that tuple repeatedly becomes visible in
    scenes with many helpers, masks and Grease Pencil objects. The cache is short
    lived and keyed by scene pointer plus object count, so new/deleted objects are
    picked up without requiring explicit invalidation.
    """
    context = context or getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context is not None else None
    try:
        source = getattr(scene, "objects", None) if scene is not None else getattr(bpy.data, "objects", None)
        if source is None:
            return ()
        scene_key = int(fbp_obj_runtime_key(scene) or 0) if scene is not None else 0
        object_count = len(source)
        now = time.monotonic()
        cached = _CONTEXT_OBJECTS_CACHE.get(scene_key)
        if cached is not None:
            try:
                cached_count, cached_at, cached_records = cached
                if int(cached_count) == int(object_count) and now - float(cached_at) <= _CONTEXT_OBJECTS_CACHE_TTL:
                    resolved = []
                    for runtime_key, object_name in tuple(cached_records or ()):
                        obj = fbp_find_id_by_runtime_key(source, runtime_key, object_name)
                        if obj is None:
                            resolved = []
                            break
                        resolved.append(obj)
                    if len(resolved) == int(object_count):
                        return tuple(resolved)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OverflowError):
                pass
        objects = tuple(source or ())
        records = []
        for obj in objects:
            try:
                records.append((
                    fbp_obj_runtime_key(obj),
                    str(getattr(obj, "name", "") or ""),
                ))
            except FBP_DATA_ERRORS:
                records = []
                break
        if len(_CONTEXT_OBJECTS_CACHE) >= 16 and scene_key not in _CONTEXT_OBJECTS_CACHE:
            _CONTEXT_OBJECTS_CACHE.clear()
        if len(records) == len(objects):
            _CONTEXT_OBJECTS_CACHE[scene_key] = (object_count, now, tuple(records))
        return objects
    except FBP_DATA_ERRORS:
        return ()


def _iter_all_effect_controls(context=None):
    """Yield every effect viewport control, including controls from previous reloads.

    The name cache is the hot path. A full scene scan is still needed after
    reinstall/reload because old helper objects can outlive the Python module,
    but scanning every selection poll becomes expensive in complex scenes.
    Empty scenes are also cached briefly: when no controls exist yet, repeated
    selection timers should not walk every object ten times per second.
    """
    global _LAST_CONTROL_FULL_SCAN_TIME, _LAST_CONTROL_EMPTY_SCAN_TIME
    global _SELECTION_VISIBILITY_EMPTY_SINCE
    seen = set()
    scene_objects = _context_scene_objects(context)
    if scene_objects and len(_CONTROL_NAMES) >= max(24, len(scene_objects) // 4):
        found = False
        for obj in scene_objects:
            if not is_effect_control(obj):
                continue
            try:
                pointer = int(fbp_obj_runtime_key(obj) or 0)
            except FBP_DATA_ERRORS:
                continue
            if pointer in seen:
                continue
            found = True
            seen.add(pointer)
            _CONTROL_NAMES.add(obj.name)
            yield obj
        if found:
            _LAST_CONTROL_FULL_SCAN_TIME = time.monotonic()
            return
    for name in tuple(_CONTROL_NAMES):
        obj = bpy.data.objects.get(str(name or ""))
        if obj is None:
            _CONTROL_NAMES.discard(name)
            continue
        try:
            pointer = int(fbp_obj_runtime_key(obj) or 0)
        except FBP_DATA_ERRORS:
            continue
        if pointer not in seen and is_effect_control(obj):
            seen.add(pointer)
            yield obj

    try:
        now = time.monotonic()
    except (RuntimeError, TypeError, ValueError):
        now = 0.0
    if not _CONTROL_NAMES:
        if now - float(_LAST_CONTROL_EMPTY_SCAN_TIME or 0.0) < _CONTROL_FULL_SCAN_INTERVAL:
            return
        scan_scene = True
    else:
        scan_scene = now - float(_LAST_CONTROL_FULL_SCAN_TIME or 0.0) >= _CONTROL_FULL_SCAN_INTERVAL
    if not scan_scene:
        return
    _LAST_CONTROL_FULL_SCAN_TIME = now

    found_control = False
    for obj in _context_scene_objects(context):
        try:
            pointer = int(fbp_obj_runtime_key(obj) or 0)
        except FBP_DATA_ERRORS:
            continue
        if pointer in seen or not is_effect_control(obj):
            continue
        found_control = True
        seen.add(pointer)
        _CONTROL_NAMES.add(obj.name)
        yield obj
    if not found_control and not _CONTROL_NAMES:
        _LAST_CONTROL_EMPTY_SCAN_TIME = now


def _object_is_selected_or_active(obj, context=None):
    if obj is None:
        return False
    context = context or getattr(bpy, "context", None)
    try:
        if getattr(context, "active_object", None) is obj or getattr(context, "object", None) is obj:
            return True
        return bool(obj.select_get())
    except FBP_DATA_ERRORS:
        return False


def _selected_pointer_set(context=None):
    """Return selected object identities from the shared primitive snapshot."""
    _scene_key, active_key, selected_keys = fbp_selection_snapshot(context)
    if active_key and active_key not in selected_keys:
        return set(selected_keys) | {active_key}
    return set(selected_keys)


def _rna_in_pointer_set(obj, pointers):
    if obj is None:
        return False
    try:
        return int(fbp_obj_runtime_key(obj) or 0) in pointers
    except FBP_DATA_ERRORS:
        return False


def _current_selection_signature(context=None):
    """Return the active/selected portion of the shared selection snapshot."""
    _scene_key, active_key, selected_keys = fbp_selection_snapshot(context)
    return (active_key, selected_keys)


def _enforce_crop_extend_exclusive_selection(context=None):
    """Keep an active Crop/Extend handle as the sole viewport selection.

    This also repairs mixed selections created by Shift-clicks, Undo or external
    scripts. The Frame By Plane Layer List selection is independent
    from Object selection, so multi-layer editing remains available.
    """
    context = context or getattr(bpy, "context", None)
    if context is None:
        return False
    active = getattr(context, "active_object", None) or getattr(context, "object", None)
    if not is_effect_control(active):
        return False
    try:
        if str(active.get(KEY_MODE, "") or "").upper() != "CROP_EXTEND":
            return False
    except FBP_DATA_ERRORS:
        return False
    try:
        # Blender can retain a stale active object after clicking empty space.
        # Never resurrect a deselected handle; only make an already selected
        # handle exclusive after a real viewport click.
        if not bool(active.select_get()):
            return False
    except FBP_DATA_ERRORS:
        return False
    changed = False
    for selected in tuple(getattr(context, "selected_objects", ()) or ()):
        if selected is active:
            continue
        try:
            selected.select_set(False)
            changed = True
        except FBP_DATA_ERRORS:
            pass
    try:
        if getattr(context.view_layer.objects, "active", None) is not active:
            context.view_layer.objects.active = active
            changed = True
    except FBP_DATA_ERRORS:
        pass
    return changed


def _rig_or_controller_is_selected(rig, helper=None, context=None):
    if rig is None:
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    return bool(
        _object_is_selected_or_active(rig, context)
        or _object_is_selected_or_active(plane, context)
        or _object_is_selected_or_active(helper, context)
    )


def _sync_all_effect_control_visibility(context=None):
    """Keep only the active effect's helpers visible while its layer is selected.

    Crop/Extend handles are stricter editing tools: selecting the plane alone
    must hide them, even if Crop is still the active UI row. They remain visible
    only while one handle in their control group is actually selected.
    """
    context = context or getattr(bpy, "context", None)
    changed = False
    controls = tuple(_iter_all_effect_controls(context))
    selected_pointers = _selected_pointer_set(context)
    if not selected_pointers:
        for control in controls:
            changed = _set_control_visibility(control, False) or changed
        return changed

    owner_by_control = {}
    effect_by_control = {}
    active_effect_by_owner = {}
    active_groups = set()
    try:
        from .geometry_nodes import fbp_active_effect_id
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        fbp_active_effect_id = None
    for control in controls:
        owner = effect_control_owner(control)
        owner_by_control[control.name] = owner
        try:
            effect_id = str(control.get(KEY_EFFECT_ID, "") or "").upper()
        except FBP_DATA_ERRORS:
            effect_id = ""
        effect_by_control[control.name] = effect_id
        if owner is not None:
            try:
                owner_key = int(fbp_obj_runtime_key(owner) or 0)
                if owner_key not in active_effect_by_owner:
                    active_effect_by_owner[owner_key] = str(
                        fbp_active_effect_id(owner) if fbp_active_effect_id else ""
                    ).upper()
            except FBP_DATA_ERRORS:
                pass
        if owner is not None and _rna_in_pointer_set(control, selected_pointers):
            try:
                active_groups.add((int(fbp_obj_runtime_key(owner) or 0), effect_id))
            except FBP_DATA_ERRORS:
                pass

    for control in controls:
        owner = owner_by_control.get(control.name)
        effect_id = effect_by_control.get(control.name, "")
        plane = getattr(owner, "fbp_plane_target", None) if owner else None
        try:
            owner_key = int(fbp_obj_runtime_key(owner) or 0) if owner else 0
            group_selected = bool(owner and (owner_key, effect_id) in active_groups)
            active_effect = active_effect_by_owner.get(owner_key, "")
        except FBP_DATA_ERRORS:
            group_selected = False
            active_effect = ""
        owner_selected = bool(
            _rna_in_pointer_set(owner, selected_pointers)
            or _rna_in_pointer_set(plane, selected_pointers)
        )
        visible = bool(
            owner
            and (
                group_selected
                or (
                    owner_selected
                    and effect_id == active_effect
                    and effect_id not in {"CROP", "EXTEND"}
                )
            )
        )
        changed = _set_control_visibility(control, visible) or changed
    return changed


def _sync_object_mask_controller_visibility(context=None):
    """Delegate Shape Mask visibility to its authoritative runtime registry."""
    del context
    try:
        from .object_masks import sync_all_object_mask_runtime
        return bool(sync_all_object_mask_runtime(discover=True))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _sync_lattice_controller_visibility(context=None):
    """Hide Lattice cages unless the owning plane/rig or cage is selected."""
    context = context or getattr(bpy, "context", None)
    changed = False
    try:
        from .geometry_nodes import FBP_EFFECT_LATTICE, _fbp_is_enabled, _fbp_stored_effect_visibility
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        FBP_EFFECT_LATTICE = "LATTICE"
        _fbp_is_enabled = None
        _fbp_stored_effect_visibility = None
    selected_pointers = _selected_pointer_set(context)
    if not selected_pointers:
        for obj in _context_scene_objects(context):
            try:
                if str(getattr(obj, "type", "") or "") != "LATTICE":
                    continue
                owner = getattr(obj, "parent", None)
                if not (owner and bool(getattr(owner, "is_fbp_control", False))) and not str(obj.get("fbp_lattice_owner", "") or ""):
                    continue
                if not bool(obj.hide_get()):
                    obj.hide_set(True)
                    changed = True
                if not bool(getattr(obj, "hide_render", False)):
                    obj.hide_render = True
                    changed = True
            except FBP_DATA_ERRORS:
                continue
        return changed
    for obj in _context_scene_objects(context):
        try:
            if str(getattr(obj, "type", "") or "") != "LATTICE":
                continue
            owner = getattr(obj, "parent", None)
            if not (owner and bool(getattr(owner, "is_fbp_control", False))):
                owner_name = str(obj.get("fbp_lattice_owner", "") or "")
                owner = bpy.data.objects.get(owner_name) if owner_name else None
            if not (owner and bool(getattr(owner, "is_fbp_control", False))):
                continue
            show_cage_pref = bool(getattr(owner, "fbp_lattice_show_cage", True))
            effect_enabled = True
            viewport_enabled = True
            try:
                if _fbp_is_enabled is not None:
                    effect_enabled = bool(_fbp_is_enabled(owner, FBP_EFFECT_LATTICE))
                if _fbp_stored_effect_visibility is not None:
                    viewport_enabled = bool(_fbp_stored_effect_visibility(owner, FBP_EFFECT_LATTICE, True))
            except FBP_DATA_ERRORS:
                pass
            visible = bool(effect_enabled and viewport_enabled and show_cage_pref and _rig_or_controller_is_selected(owner, obj, context))
            hidden = not visible
            try:
                hidden_now = bool(obj.hide_get())
            except FBP_DATA_ERRORS:
                hidden_now = hidden
            if hidden_now != hidden:
                obj.hide_set(hidden)
                changed = True
            if not bool(getattr(obj, "hide_render", False)):
                obj.hide_render = True
                changed = True
        except FBP_DATA_ERRORS:
            continue
    return changed


def sync_global_controller_visibility(context=None):
    """Central visibility pass for every FBP controller/helper object.

    Controllers are visible only while their owner layer/plane is selected, or
    while the controller itself is selected for editing. This keeps the viewport
    clean and makes selecting a controller behave like selecting its plane for
    the UI resolver.
    """
    if fbp_undo_guard_active():
        return False
    context = context or getattr(bpy, "context", None)
    changed = False
    changed = _sync_all_effect_control_visibility(context) or changed
    try:
        from .motion_runtime import _sync_motion_helper_visibility
        changed = bool(_sync_motion_helper_visibility(context)) or changed
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    changed = _sync_object_mask_controller_visibility(context) or changed
    changed = _sync_lattice_controller_visibility(context) or changed
    return changed

def hide_rig_effect_controls(rig, except_effect_id=""):
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    try:
        children = tuple(getattr(plane, "children", ()) or ())
    except FBP_DATA_ERRORS:
        children = ()
    for child in children:
        if not is_effect_control(child):
            continue
        show = bool(except_effect_id and str(child.get(KEY_EFFECT_ID, "") or "") == except_effect_id)
        _set_control_visibility(child, show)


def prepare_effect_control_selection(context, rig, effect_id):
    """Detach a stale active helper before a different effect row takes focus.

    Without this synchronous hand-off, Blender can report the old Crop handle
    as a fresh selection before the deferred UI callback runs. The selection
    observer then restores Crop and makes rows underneath appear unclickable.
    """
    if context is None or rig is None:
        return False
    active = getattr(context, "active_object", None)
    if not is_effect_control(active) or effect_control_owner(active) is not rig:
        return False
    current = str(active.get(KEY_EFFECT_ID, "") or "").upper()
    requested = str(effect_id or "").upper()
    if current == requested:
        return False
    hide_rig_effect_controls(rig)
    try:
        rig.select_set(True)
        context.view_layer.objects.active = rig
    except FBP_DATA_ERRORS:
        pass
    return True


def sync_active_effect_controls(
    context=None, *, select_active=False, create_missing=False
):
    """Reveal/sync controls for the selected effect without surprise mutations.

    UI selection callbacks run through a deferred timer. They must never create
    Blender objects because those objects would live outside the operator's Undo
    transaction. Missing controls are created only by an explicit UNDO operator
    or synchronously while the effect itself is being added.
    """
    if fbp_undo_guard_active():
        return False
    context = context or bpy.context
    try:
        from .layers import get_selected_rigs
        from .geometry_nodes import fbp_active_effect_id, fbp_effect_is_active
        rigs = list(get_selected_rigs(context) or ())
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    changed = False
    selected_rig_names = {str(getattr(rig, "name", "") or "") for rig in rigs}
    for name in tuple(_GUIDE_NAMES):
        control = bpy.data.objects.get(name)
        if control is None:
            _GUIDE_NAMES.discard(name)
            continue
        owner = _guide_owner(control)
        if owner is None or str(getattr(owner, "name", "") or "") not in selected_rig_names:
            _set_guide_visibility(control, False)
    active_object = getattr(context, "active_object", None) if context else None
    active_is_control = is_effect_control(active_object)
    active_control_owner = effect_control_owner(active_object) if active_is_control else None
    active_control_effect = (
        str(active_object.get(KEY_EFFECT_ID, "") or "").upper()
        if active_is_control else ""
    )

    selected_control = None
    selected_related = ()
    selected_rig = None
    for rig_index, rig in enumerate(rigs):
        enabled = bool(getattr(rig, "fbp_effect_controls_enabled", True))
        effect_id = str(fbp_active_effect_id(rig) or "").upper()
        active_crop_extend_control = bool(
            effect_id in {"CROP", "EXTEND"}
            and active_is_control
            and active_control_owner is rig
            and active_control_effect == effect_id
        )
        show_crop_extend_controls = bool(active_crop_extend_control or (select_active and rig_index == 0))
        sync_crop_extend_bounds_guide(
            rig,
            visible=bool(effect_id in {"CROP", "EXTEND"} and show_crop_extend_controls),
        )
        if not enabled or not effect_has_controls(effect_id) or not fbp_effect_is_active(rig, effect_id):
            continue
        if effect_id in {"CROP", "EXTEND"} and not show_crop_extend_controls:
            # Crop/Extend helpers are editing handles, not persistent overlays.
            # Keep them hidden while the user has the layer/plane selected, then
            # reveal them only from the explicit Viewport Control button or while
            # one handle is the active object.
            continue
        controls = []
        for spec in CONTROL_SPECS[effect_id]:
            role = str(spec.get("role", "CONTROL") or "CONTROL").upper()
            control = find_effect_control(rig, effect_id, role)
            if control is None and create_missing:
                control = ensure_effect_control(rig, effect_id, spec)
            if control:
                controls.append(control)
                changed = _set_control_visibility(control, True) or changed
        if controls and not any(
            control.name in _PENDING_CONTROL_SIGNATURES for control in controls
        ):
            sync_controls_from_properties(
                rig, effect_id, create=create_missing
            )
        if select_active and rig_index == 0 and controls:
            selected_control, selected_related = _preferred_control_for_selection(
                context, rig, effect_id, controls
            )
            selected_rig = rig
    if selected_control is not None:
        _select_control_preserving_layer(
            context, selected_rig, selected_control, selected_related
        )
    changed = sync_global_controller_visibility(context) or changed
    return changed


def schedule_active_effect_controls(
    context=None, *, select_active=False, create_missing=False
):
    """Defer visibility/synchronization, never structural creation by default."""
    if fbp_undo_guard_active():
        return False
    context = context or getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context else None
    try:
        scene_key = int(fbp_obj_runtime_key(scene) or 0) if scene else 0
    except FBP_DATA_ERRORS:
        scene_key = 0
    try:
        return schedule_once(
            (
                f"effect_controls.sync_active.{scene_key}."
                f"{int(bool(select_active))}.{int(bool(create_missing))}"
            ),
            lambda: sync_active_effect_controls(
                getattr(bpy, "context", None),
                select_active=select_active,
                create_missing=create_missing,
            ),
            first_interval=0.01,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _focus_effect_row_callback(owner_name, effect_id):
    """Create a deferred row-focus callback without duplicating stale-RNA guards."""
    def _focus():
        current_owner = bpy.data.objects.get(owner_name)
        if current_owner is not None:
            _focus_effect_row_for_control(current_owner, effect_id)
        return None

    return _focus


def effect_controls_depsgraph_update(scene, depsgraph, *, updates=None):
    """Observe only relevant helper transforms and plane geometry changes.

    Shader-only updates are deliberately ignored. Reacting to them used to run
    the helper synchronizer after every rendered-viewport refresh; the helper
    then rewrote unchanged Object data and could restart the render indefinitely.
    """
    global _LAST_SELECTION_SIGNATURE, _LAST_SELECTION_CHECK_TIME
    global _LAST_SELECTION_CONTEXT_MODE
    if fbp_render_mutation_blocked() or fbp_undo_guard_active():
        return
    if updates is None:
        try:
            updates = tuple(getattr(depsgraph, "updates", ()) or ())
        except FBP_DATA_ERRORS:
            return
    if not updates or not _scene_has_fbp_rigs(scene=scene):
        return
    # The fallback timer intentionally stops in empty projects. A newly created
    # Frame By Plane rig restarts it through this first relevant object update.
    if not fbp_timer_is_registered(_selection_visibility_timer):
        _register_selection_visibility_timer()

    # Resolve module APIs once per depsgraph callback, not once per updated ID.
    # Large scenes can report hundreds of updates in one evaluation pass.
    try:
        (
            is_object_mask_bounds_handle,
            is_object_mask_helper,
            schedule_object_mask_bounds_handle_update,
            schedule_object_mask_helper_transform_update,
            is_scene_fbp_plane_mesh,
        ) = _depsgraph_support_apis()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        is_object_mask_bounds_handle = None
        is_object_mask_helper = None
        schedule_object_mask_bounds_handle_update = None
        schedule_object_mask_helper_transform_update = None
        is_scene_fbp_plane_mesh = None

    object_rna = bpy.types.Object
    mesh_rna = bpy.types.Mesh
    lattice_rna = bpy.types.Lattice
    camera_rna = bpy.types.Camera
    needs_control_refresh = False
    needs_lattice_refresh = False
    for update in updates:
        datablock = getattr(update, "id", None)
        # Capture evaluated helper transforms before resolving Object.original.
        # Blender can report a transform update one depsgraph step earlier on the
        # evaluated copy, so reading only the original made most viewport Nulls
        # appear disconnected from their UI properties.
        evaluated_control_snapshot = ()
        try:
            evaluated_datablock = datablock
            original = getattr(evaluated_datablock, "original", None)
            original_datablock = original if original is not None else evaluated_datablock
            # Some Blender builds omit custom ID properties from the evaluated
            # proxy even though the original Object is a Frame By Plane helper.
            # Detect the helper on either side, but always capture the newest
            # evaluated local transform before resolving ``Object.original``.
            if (
                isinstance(evaluated_datablock, object_rna)
                and (
                    is_effect_control(evaluated_datablock)
                    or is_effect_control(original_datablock)
                )
            ):
                evaluated_control_snapshot = _control_signature(evaluated_datablock)
            datablock = original_datablock
        except FBP_DATA_ERRORS:
            pass
        if isinstance(datablock, object_rna):
            object_type = str(getattr(datablock, "type", "") or "")
            is_control = is_effect_control(datablock)
            try:
                is_mask_bounds_handle = bool(
                    is_object_mask_bounds_handle
                    and is_object_mask_bounds_handle(datablock)
                )
                is_mask_helper = bool(
                    is_object_mask_helper and is_object_mask_helper(datablock)
                )
            except FBP_DATA_ERRORS:
                is_mask_bounds_handle = False
                is_mask_helper = False
            is_fbp_control = bool(getattr(datablock, "is_fbp_control", False))
            is_fbp_plane = bool(getattr(datablock, "is_fbp_plane", False))
            if is_mask_helper:
                if bool(getattr(update, "is_updated_transform", False)):
                    if schedule_object_mask_helper_transform_update is not None:
                        schedule_object_mask_helper_transform_update(datablock)
            elif is_mask_bounds_handle:
                if bool(getattr(update, "is_updated_transform", False)):
                    try:
                        signature = tuple(round(float(value), 7) for value in (
                            datablock.location.x, datablock.location.y,
                            datablock.location.z, datablock.rotation_euler.z,
                        ))
                        stored = tuple(float(value) for value in datablock.get(
                            "fbp_object_mask_handle_signature", ()
                        ) or ())
                        if signature != stored and schedule_object_mask_bounds_handle_update is not None:
                            schedule_object_mask_bounds_handle_update(datablock)
                    except FBP_DATA_ERRORS:
                        pass
            elif is_control:
                if not bool(getattr(update, "is_updated_transform", False)):
                    continue
                try:
                    signature = _control_signature(datablock)
                    stored = tuple(float(value) for value in datablock.get(KEY_SYNC_SIGNATURE, ()) or ())
                    pending = _PENDING_CONTROL_SIGNATURES.get(str(datablock.name))
                    latest = tuple(evaluated_control_snapshot or signature)
                    if latest != stored and latest != pending:
                        schedule_properties_from_control(
                            datablock, transform_snapshot=latest
                        )
                except FBP_DATA_ERRORS:
                    pass
            elif object_type == "LATTICE":
                continue
            elif is_fbp_plane:
                if bool(getattr(update, "is_updated_transform", False)) or bool(
                    getattr(update, "is_updated_geometry", False)
                ):
                    needs_control_refresh = True
                    needs_lattice_refresh = True
            elif is_fbp_control:
                if bool(getattr(update, "is_updated_transform", False)):
                    needs_lattice_refresh = True
            elif object_type == "CAMERA":
                if bool(getattr(update, "is_updated_transform", False)):
                    needs_lattice_refresh = True
        elif isinstance(datablock, mesh_rna) and scene is not None:
            if not bool(getattr(update, "is_updated_geometry", False)):
                continue
            try:
                mesh_key = (
                    int(fbp_obj_runtime_key(datablock) or 0),
                    str(getattr(datablock, "name_full", getattr(datablock, "name", "")) or ""),
                )
                if is_scene_fbp_plane_mesh is not None:
                    try:
                        is_fbp_mesh = bool(is_scene_fbp_plane_mesh(scene, datablock))
                    except FBP_DATA_ERRORS:
                        is_fbp_mesh = False
                else:
                    is_fbp_mesh = bool(datablock.get("fbp_plane_mesh", False)) or mesh_key in _FBP_PLANE_MESH_KEYS
                needs_control_refresh = is_fbp_mesh or needs_control_refresh
                needs_lattice_refresh = is_fbp_mesh or needs_lattice_refresh
            except FBP_DATA_ERRORS:
                pass
        elif isinstance(datablock, lattice_rna):
            continue
        elif isinstance(datablock, camera_rna):
            needs_lattice_refresh = True

    active_object = None
    context = getattr(bpy, "context", None)
    try:
        context_mode = str(getattr(context, "mode", "") or "").upper()
    except FBP_DATA_ERRORS:
        context_mode = ""
    mode_changed = context_mode != _LAST_SELECTION_CONTEXT_MODE
    if mode_changed:
        _LAST_SELECTION_CONTEXT_MODE = context_mode
    gp_interaction = fbp_is_grease_pencil_interaction_mode(context_mode)

    check_selection = bool(needs_control_refresh or mode_changed)
    if not check_selection and not gp_interaction:
        try:
            now = time.monotonic()
        except (RuntimeError, TypeError, ValueError):
            now = 0.0
        if now - float(_LAST_SELECTION_CHECK_TIME or 0.0) >= _SELECTION_CHECK_INTERVAL:
            _LAST_SELECTION_CHECK_TIME = now
            check_selection = True
    if check_selection:
        active_object = getattr(context, "active_object", None) if context else None
        selection_signature = _current_selection_signature(context)
    else:
        selection_signature = _LAST_SELECTION_SIGNATURE
    if selection_signature != _LAST_SELECTION_SIGNATURE:
        previous_signature = _LAST_SELECTION_SIGNATURE
        previous_active_key = (
            int(previous_signature[0])
            if isinstance(previous_signature, tuple) and previous_signature else 0
        )
        current_active_key = int(selection_signature[0]) if selection_signature else 0
        active_controller_changed = bool(
            current_active_key and current_active_key != previous_active_key
        )
        _LAST_SELECTION_SIGNATURE = selection_signature
        needs_control_refresh = True
        if active_controller_changed and active_object is not None and is_effect_control(active_object):
            try:
                owner = effect_control_owner(active_object)
                owner_name = str(getattr(owner, "name", "") or "") if owner is not None else ""
                effect_id = str(active_object.get(KEY_EFFECT_ID, "") or "")
                if owner_name and effect_id:
                    schedule_once(
                        f"effect_controls.focus:{owner_name}:{effect_id}",
                        _focus_effect_row_callback(owner_name, effect_id),
                        first_interval=0.02,
                    )
            except FBP_DATA_ERRORS:
                pass
        if active_controller_changed and active_object is not None:
            try:
                from .object_masks import (
                    find_object_mask_controller_owner,
                    is_object_mask_controller,
                    object_mask_effect_id,
                    object_mask_controller_shape,
                )
                if is_object_mask_controller(active_object):
                    owner = find_object_mask_controller_owner(active_object)
                    owner_name = str(getattr(owner, "name", "") or "") if owner is not None else ""
                    effect_id = object_mask_effect_id(object_mask_controller_shape(active_object))
                    if owner_name and effect_id:
                        schedule_once(
                            f"effect_controls.mask_focus:{owner_name}:{effect_id}",
                            _focus_effect_row_callback(owner_name, effect_id),
                            first_interval=0.02,
                        )
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        if active_object is not None and str(getattr(active_object, "type", "") or "") == "LATTICE":
            try:
                from .layers import fbp_resolve_rig_from_any_object
                owner = fbp_resolve_rig_from_any_object(active_object, bpy.context)
                if owner is not None:
                    helper_name = str(getattr(active_object, "name", "") or "")
                    owner_name = str(getattr(owner, "name", "") or "")

                    def _focus_selected_lattice():
                        current = getattr(bpy.context, "active_object", None)
                        if (
                            current is None
                            or str(getattr(current, "name", "") or "") != helper_name
                            or str(getattr(current, "type", "") or "") != "LATTICE"
                        ):
                            return None
                        current_owner = bpy.data.objects.get(owner_name)
                        if current_owner is None:
                            return None
                        from .geometry_nodes import fbp_focus_lattice_ui
                        fbp_focus_lattice_ui(bpy.context, current_owner)
                        return None

                    schedule_once(
                        f"lattice.selection_focus.{owner_name}",
                        _focus_selected_lattice,
                        first_interval=0.0,
                    )
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass

    if needs_control_refresh:
        schedule_active_effect_controls(getattr(bpy, "context", None))
        try:
            schedule_once(
                "effect_controls.global_visibility",
                lambda: sync_global_controller_visibility(getattr(bpy, "context", None)),
                first_interval=0.0,
            )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            # Depsgraph handlers remain observer-only. A failed scheduler must
            # never fall back to direct Object visibility writes.
            pass
    if needs_lattice_refresh and scene is not None:
        try:
            from .geometry_nodes import schedule_live_lattice_updates
            schedule_live_lattice_updates(scene)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass


def _control_shape_is_stale(control, owner, expected_mode, role):
    expected_mode = str(expected_mode or "").upper()
    if _uses_control_mesh(expected_mode):
        try:
            expected_signature = (
                _crop_extend_handle_mesh_signature(owner, role)
                if _is_crop_extend_mode(expected_mode)
                else _range_handle_mesh_signature(owner, expected_mode, role)
            )
            return bool(
                getattr(control, "type", "") != "MESH"
                or str(control.get(KEY_CONTROL_MESH_SIGNATURE, "") or "") != expected_signature
            )
        except FBP_DATA_ERRORS:
            return True
    return bool(
        str(getattr(control, "empty_display_type", "") or "") != _control_display_type(expected_mode)
        or abs(float(getattr(control, "empty_display_size", 0.0)) - _control_display_size(owner, expected_mode, role)) > 1.0e-5
    )


def audit_effect_controls(scene, *, repair=False, context=None):
    """Validate viewport-control ownership without scanning during playback."""
    stats = {
        "control_objects": 0,
        "control_duplicates": 0,
        "control_orphans": 0,
        "control_stale_contracts": 0,
        "control_missing_active": 0,
        "control_guides": 0,
        "control_repairs": 0,
    }
    issues = []
    warnings = []
    if scene is None:
        return {"stats": stats, "issues": ("No active Scene",), "warnings": (), "repaired": 0}
    try:
        objects = tuple(getattr(scene, "objects", ()) or ())
    except FBP_DATA_ERRORS:
        objects = ()
    controls = [obj for obj in objects if is_effect_control(obj)]
    guides = [obj for obj in objects if is_crop_extend_bounds_guide(obj)]
    stats["control_objects"] = len(controls)
    stats["control_guides"] = len(guides)
    seen = {}

    for control in tuple(controls):
        try:
            owner = effect_control_owner(control)
            effect_id = str(control.get(KEY_EFFECT_ID, "") or "").upper()
            role = str(control.get(KEY_ROLE, "") or "").upper()
            spec = next(
                (item for item in CONTROL_SPECS.get(effect_id, ())
                 if str(item.get("role", "") or "").upper() == role),
                None,
            )
            plane = getattr(owner, "fbp_plane_target", None) if owner else None
            if owner is None or plane is None or spec is None:
                stats["control_orphans"] += 1
                issues.append(f"{control.name}: invalid owner, effect or role")
                if repair:
                    if _remove_control_object(control):
                        stats["control_repairs"] += 1
                continue
            key = (int(fbp_obj_runtime_key(owner) or 0), effect_id, role)
            if key in seen:
                stats["control_duplicates"] += 1
                issues.append(f"{control.name}: duplicate of {seen[key].name}")
                if repair:
                    if _remove_control_object(control):
                        stats["control_repairs"] += 1
                continue
            seen[key] = control
            expected_mode = str(spec.get("mode", "POINT") or "POINT").upper()
            expected_locks = _expected_control_locks(expected_mode, spec)
            stale = bool(
                int(control.get(KEY_SCHEMA, 0) or 0) != SCHEMA_VERSION
                or str(control.get(KEY_MODE, "") or "").upper() != expected_mode
                or str(control.get(KEY_OWNER_NAME, "") or "") != str(owner.name)
                or getattr(control, "parent", None) is not plane
                or not bool(getattr(control, "matrix_parent_inverse", Matrix.Identity(4)).is_identity)
                or str(getattr(control, "rotation_mode", "") or "") != "XYZ"
                or any(abs(float(value)) > 1.0e-8 for value in control.delta_location)
                or any(abs(float(value)) > 1.0e-8 for value in control.delta_rotation_euler)
                or any(abs(float(value) - 1.0) > 1.0e-8 for value in control.delta_scale)
                or (
                    expected_mode != "VECTOR_DIRECTION"
                    and (
                        abs(float(control.rotation_euler.x) - _control_base_rotation(expected_mode)[0]) > 1.0e-6
                        or abs(float(control.rotation_euler.y) - _control_base_rotation(expected_mode)[1]) > 1.0e-6
                    )
                )
                or _control_shape_is_stale(control, owner, expected_mode, role)
                or not bool(getattr(control, "show_in_front", False))
                or not bool(getattr(control, "hide_render", False))
                or (
                    expected_locks is not None
                    and (
                        tuple(control.lock_location) != expected_locks[0]
                        or tuple(control.lock_rotation) != expected_locks[1]
                        or tuple(control.lock_scale) != expected_locks[2]
                    )
                )
            )
            if stale:
                stats["control_stale_contracts"] += 1
                warnings.append(f"{control.name}: stale viewport-control contract")
                if repair:
                    ensure_effect_control(owner, effect_id, spec)
                    stats["control_repairs"] += 1
        except FBP_DATA_ERRORS:
            stats["control_orphans"] += 1
            issues.append(f"{getattr(control, 'name', '<control>')}: unreadable control datablock")

    # Only the currently active spatial effect is expected to own visible
    # helpers. Other effects create their controls lazily when selected.
    try:
        from .geometry_nodes import fbp_active_effect_id, fbp_effect_is_active
        rigs = (
            []
            if bool(getattr(bpy.app, "background", False))
            else [obj for obj in objects if bool(getattr(obj, "is_fbp_control", False))]
        )
        for rig in rigs:
            effect_id = str(fbp_active_effect_id(rig) or "").upper()
            if not bool(getattr(rig, "fbp_effect_controls_enabled", True)):
                continue
            if not effect_has_controls(effect_id) or not fbp_effect_is_active(rig, effect_id):
                continue
            for spec in CONTROL_SPECS.get(effect_id, ()):
                role = str(spec.get("role", "CONTROL") or "CONTROL").upper()
                if find_effect_control(rig, effect_id, role) is not None:
                    continue
                stats["control_missing_active"] += 1
                warnings.append(f"{rig.name}: missing lazy {effect_id}/{role} viewport control")
                if repair:
                    ensure_effect_control(rig, effect_id, spec)
                    stats["control_repairs"] += 1
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    for guide in tuple(guides):
        owner = _guide_owner(guide)
        plane = getattr(owner, "fbp_plane_target", None) if owner else None
        if owner is not None and plane is not None and getattr(guide, "parent", None) is plane:
            continue
        stats["control_orphans"] += 1
        issues.append(f"{guide.name}: invalid Crop/Extend bounds-guide owner")
        if repair:
            try:
                if _remove_control_object(guide):
                    stats["control_repairs"] += 1
            except FBP_DATA_ERRORS:
                pass

    return {
        "stats": stats,
        "issues": tuple(issues),
        "warnings": tuple(warnings),
        "repaired": int(stats["control_repairs"]),
    }


def _selected_effect_control_rigs_available(context):
    try:
        from .layers import get_selected_rigs
        return bool(get_selected_rigs(context))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


class FBP_OT_ResetEffectControl(Operator):
    bl_idname = "fbp.reset_effect_control"
    bl_label = "Reset Viewport Control"
    bl_description = "Reset only the position, rotation and range represented by this viewport control"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(description='Internal stable effect identifier used by this button. Example: PIXELATE, SHADOW or GRADIENT_MASK.', default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _selected_effect_control_rigs_available(context)

    def execute(self, context):
        try:
            from .layers import get_selected_rigs
            from .geometry_nodes import fbp_effect_is_active
            rigs = [rig for rig in get_selected_rigs(context) if rig]
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return {"CANCELLED"}
        effect_id = str(self.effect_id or "").upper()
        compatible = [rig for rig in rigs if fbp_effect_is_active(rig, effect_id)]
        snapshots = [
            (rig, {name: getattr(rig, name) for name in effect_control_driven_properties(effect_id) if hasattr(rig, name)})
            for rig in compatible
        ]
        changed = 0
        try:
            for rig in compatible:
                changed += int(reset_effect_control_properties(rig, effect_id))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            for rig, values in snapshots:
                for name, value in values.items():
                    fbp_set_rna_property_silent(rig, name, value)
                _refresh_effect_from_control(rig, effect_id, values.keys())
            self.report({"ERROR"}, f"Control reset failed and was restored: {exc}")
            return {"CANCELLED"}
        schedule_active_effect_controls(context, select_active=True)
        if not compatible:
            self.report({"WARNING"}, "The selected layers do not contain this effect")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Reset {changed} viewport control(s)")
        return {"FINISHED"}


class FBP_OT_RepairEffectControls(Operator):
    bl_idname = "fbp.repair_effect_controls"
    bl_label = "Repair Effect Controls"
    bl_description = "Audit and safely repair missing, duplicated, stale or orphaned viewport controls"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        repaired = audit_effect_controls(context.scene, repair=True, context=context)
        result = audit_effect_controls(context.scene, repair=False, context=context)
        stats = dict(result.get("stats", {}) or {})
        issues = list(result.get("issues", ()) or ())
        warnings = list(result.get("warnings", ()) or ())
        lines = [
            "Frame By Plane — Viewport Control Health",
            "========================================",
            f"Scene: {getattr(context.scene, 'name', '<none>')}",
            f"Repaired: {int(repaired.get('repaired', 0) or 0)}",
            "",
            "Summary",
            "-------",
        ]
        lines.extend(f"{key.replace('_', ' ').title()}: {value}" for key, value in stats.items())
        lines.extend(("", "Remaining issues", "----------------"))
        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- None")
        lines.extend(("", "Warnings", "--------"))
        lines.extend(f"- {item}" for item in warnings) if warnings else lines.append("- None")
        summary = (
            f"Viewport Controls · repaired {int(repaired.get('repaired', 0) or 0)} · "
            f"{len(issues)} remaining issue(s)"
        )
        write_diagnostic_report(
            context.scene, "FBP_Effect_Control_Health", lines,
            summary=summary, status="PASS" if not issues else "WARNING",
        )
        schedule_active_effect_controls(context)
        level = {"INFO"} if not issues else {"WARNING"}
        self.report(level, summary)
        return {"FINISHED"}


class FBP_OT_SelectEffectControl(Operator):
    bl_idname = "fbp.select_effect_control"
    bl_label = "Select Effect Control"
    bl_description = "Reveal the controls and keep the handle currently selected in the viewport"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(description='Internal stable effect identifier used by this button. Example: PIXELATE, SHADOW or GRADIENT_MASK.', default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _selected_effect_control_rigs_available(context)

    def execute(self, context):
        from .layers import get_selected_rigs
        rigs = list(get_selected_rigs(context) or ())
        if not rigs:
            return {"CANCELLED"}
        rig = rigs[0]
        effect_id = str(self.effect_id or "").upper()
        specs = CONTROL_SPECS.get(effect_id, ())
        if not specs:
            return {"CANCELLED"}
        try:
            from .geometry_nodes import fbp_effect_is_active
            if not fbp_effect_is_active(rig, effect_id):
                self.report({"INFO"}, "The effect is not active on this layer")
                return {"CANCELLED"}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

        prepare_effect_control_selection(context, rig, effect_id)
        _focus_effect_row_for_control(rig, effect_id)
        fbp_set_rna_property_silent(rig, "fbp_effect_controls_enabled", True)
        controls = [ensure_effect_control(rig, effect_id, spec) for spec in specs]
        sync_controls_from_properties(rig, effect_id, create=True)
        controls = [control for control in controls if control]
        if not controls:
            self.report({"WARNING"}, "Could not create the viewport controller")
            return {"CANCELLED"}
        for child in controls:
            _set_control_visibility(child, True)
        selected, related = _preferred_control_for_selection(
            context, rig, effect_id, controls
        )
        _select_control_preserving_layer(context, rig, selected, related)
        sync_global_controller_visibility(context)
        return {"FINISHED"}


classes = (FBP_OT_ResetEffectControl, FBP_OT_RepairEffectControls, FBP_OT_SelectEffectControl,)


def _scene_has_fbp_rigs(context=None, *, scene=None):
    """Cached service-presence check for observers and fallback polling."""
    context = context or getattr(bpy, "context", None)
    scene = scene or (getattr(context, "scene", None) if context else None)
    if scene is None:
        return False
    try:
        scene_key = int(fbp_obj_runtime_key(scene) or 0)
        object_count = len(scene.objects)
        now = time.monotonic()
        cached = _SCENE_SERVICE_CACHE.get(scene_key)
        if cached is not None:
            cached_count, checked_at, result = cached
            if int(cached_count) == object_count and now - float(checked_at) <= _SCENE_SERVICE_CACHE_TTL:
                return bool(result)
        from .fbp_index import iter_scene_fbp_rigs
        result = next(iter_scene_fbp_rigs(scene, fallback=False), None) is not None
        if len(_SCENE_SERVICE_CACHE) >= 16 and scene_key not in _SCENE_SERVICE_CACHE:
            _SCENE_SERVICE_CACHE.clear()
        _SCENE_SERVICE_CACHE[scene_key] = (object_count, now, bool(result))
        return bool(result)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        try:
            return any(bool(getattr(obj, "is_fbp_control", False)) for obj in scene.objects)
        except FBP_DATA_ERRORS:
            return False


def effect_controls_runtime_service_required(context=None):
    """Return whether the fallback visibility observer should stay active."""
    return bool(_CONTROL_NAMES or _scene_has_fbp_rigs(context))


def _sync_selected_effect_control_transforms(context=None):
    """Fallback bidirectional sync for actively manipulated viewport helpers.

    The depsgraph observer is the primary path.  A small selected-object scan
    covers transform tools and Blender builds that omit ``is_updated_transform``
    on the original Object while an evaluated copy is being manipulated.
    """
    context = context or getattr(bpy, "context", None)
    if context is None or fbp_render_mutation_blocked() or fbp_undo_guard_active():
        return False
    candidates = []
    try:
        active = getattr(context, "active_object", None)
        if active is not None:
            candidates.append(active)
        candidates.extend(tuple(getattr(context, "selected_objects", ()) or ()))
    except FBP_DATA_ERRORS:
        return False
    changed = False
    seen = set()
    for control in candidates:
        try:
            evaluated = control
            original = getattr(evaluated, "original", None)
            control = original if original is not None else evaluated
            evaluated_signature = (
                _control_signature(evaluated)
                if is_effect_control(control) or is_effect_control(evaluated)
                else ()
            )
            key = int(fbp_obj_runtime_key(control) or 0)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            if not is_effect_control(control):
                continue
            signature = tuple(evaluated_signature or _control_signature(control))
            stored = tuple(float(value) for value in control.get(KEY_SYNC_SIGNATURE, ()) or ())
            pending = _PENDING_CONTROL_SIGNATURES.get(str(control.name))
            if signature == stored or signature == pending:
                continue
            if signature and _control_signature(control) != signature:
                _apply_control_transform_snapshot(control, signature)
            changed = bool(sync_properties_from_control(control)) or changed
        except FBP_DATA_ERRORS:
            continue
    return changed


def _selection_visibility_timer():
    """Fallback selection observer with adaptive idle backoff.

    Depsgraph callbacks handle the responsive path. During active Grease Pencil
    brush/edit modes, selection cannot meaningfully target viewport helpers, so
    the timer performs one check on mode entry and then avoids repeated RNA
    selection walks until the mode changes again.
    """
    global _LAST_SELECTION_SIGNATURE, _SELECTION_VISIBILITY_EMPTY_SINCE
    global _SELECTION_VISIBILITY_STABLE_TICKS, _LAST_SELECTION_CONTEXT_MODE
    try:
        if fbp_render_mutation_blocked() or fbp_undo_guard_active():
            return _SELECTION_VISIBILITY_EMPTY_INTERVAL
        context = getattr(bpy, "context", None)

        service_needed = effect_controls_runtime_service_required(context)
        if not service_needed:
            now = time.monotonic()
            if _SELECTION_VISIBILITY_EMPTY_SINCE <= 0.0:
                _SELECTION_VISIBILITY_EMPTY_SINCE = now
            if now - _SELECTION_VISIBILITY_EMPTY_SINCE >= _SELECTION_VISIBILITY_EMPTY_GRACE_SECONDS:
                _SELECTION_VISIBILITY_EMPTY_SINCE = 0.0
                return None
            return _SELECTION_VISIBILITY_EMPTY_INTERVAL

        _SELECTION_VISIBILITY_EMPTY_SINCE = 0.0
        context_mode = str(getattr(context, "mode", "") or "").upper() if context else ""
        mode_changed = context_mode != _LAST_SELECTION_CONTEXT_MODE
        if mode_changed:
            _LAST_SELECTION_CONTEXT_MODE = context_mode
        gp_interaction = fbp_is_grease_pencil_interaction_mode(context_mode)
        if gp_interaction and not mode_changed:
            _SELECTION_VISIBILITY_STABLE_TICKS = min(1000, _SELECTION_VISIBILITY_STABLE_TICKS + 1)
            return _SELECTION_VISIBILITY_DEEP_IDLE_INTERVAL

        signature = _current_selection_signature(context)
        # Keep viewport -> UI synchronization responsive even when Blender does
        # not publish the original helper Object in depsgraph.updates.
        _sync_selected_effect_control_transforms(context)
        if signature != _LAST_SELECTION_SIGNATURE:
            _SELECTION_VISIBILITY_STABLE_TICKS = 0
            if _enforce_crop_extend_exclusive_selection(context):
                fbp_invalidate_selection_snapshot()
            signature = _current_selection_signature(context)
            _LAST_SELECTION_SIGNATURE = signature
            sync_global_controller_visibility(context)
            try:
                from .grease_pencil_bridge import sync_gp_mask_interaction_state
                sync_gp_mask_interaction_state(context=context)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        else:
            _SELECTION_VISIBILITY_STABLE_TICKS = min(1000, _SELECTION_VISIBILITY_STABLE_TICKS + 1)

        selected_keys = signature[1] if isinstance(signature, tuple) and len(signature) > 1 else frozenset()
        if not selected_keys:
            if _SELECTION_VISIBILITY_STABLE_TICKS >= 16:
                return _SELECTION_VISIBILITY_DEEP_IDLE_INTERVAL
            return _SELECTION_VISIBILITY_IDLE_INTERVAL
        if _SELECTION_VISIBILITY_STABLE_TICKS >= 24:
            return _SELECTION_VISIBILITY_DEEP_IDLE_INTERVAL
        if _SELECTION_VISIBILITY_STABLE_TICKS >= 6:
            return _SELECTION_VISIBILITY_STABLE_INTERVAL
    except FBP_DATA_ERRORS:
        return _SELECTION_VISIBILITY_IDLE_INTERVAL
    return _SELECTION_VISIBILITY_TIMER_INTERVAL


def clear_effect_controls_runtime_cache():
    """Drop viewport-controller caches without unregistering handlers/classes."""
    global _DEPSGRAPH_SUPPORT_APIS
    global _LAST_SELECTION_SIGNATURE, _LAST_SELECTION_CHECK_TIME
    global _LAST_SELECTION_CONTEXT_MODE
    global _LAST_CONTROL_FULL_SCAN_TIME, _LAST_CONTROL_EMPTY_SCAN_TIME
    global _SELECTION_VISIBILITY_EMPTY_SINCE, _SELECTION_VISIBILITY_STABLE_TICKS
    _CONTROL_DRIVEN_PROPS_CACHE.clear()
    _PENDING_CONTROL_SIGNATURES.clear()
    _PENDING_CONTROL_TRANSFORMS.clear()
    _CONTROL_NAMES.clear()
    _CONTROL_OWNER_CACHE.clear()
    _CONTEXT_OBJECTS_CACHE.clear()
    _SCENE_SERVICE_CACHE.clear()
    _GUIDE_NAMES.clear()
    _FBP_PLANE_MESH_KEYS.clear()
    # Lazy imports cache function objects from other add-on modules. Retire them
    # on Undo/reload so an in-place extension reload cannot call an old module
    # generation from the shared depsgraph dispatcher.
    _DEPSGRAPH_SUPPORT_APIS = None
    _LAST_SELECTION_SIGNATURE = None
    _LAST_SELECTION_CHECK_TIME = 0.0
    _LAST_SELECTION_CONTEXT_MODE = ""
    _LAST_CONTROL_FULL_SCAN_TIME = 0.0
    _LAST_CONTROL_EMPTY_SCAN_TIME = 0.0
    _SELECTION_VISIBILITY_EMPTY_SINCE = 0.0
    _SELECTION_VISIBILITY_STABLE_TICKS = 0


def _register_selection_visibility_timer():
    global _SELECTION_VISIBILITY_EMPTY_SINCE, _SELECTION_VISIBILITY_STABLE_TICKS
    _SELECTION_VISIBILITY_EMPTY_SINCE = 0.0
    _SELECTION_VISIBILITY_STABLE_TICKS = 0
    try:
        fbp_register_timer_once(
            _selection_visibility_timer,
            _SELECTION_VISIBILITY_TIMER_INTERVAL,
            persistent=True,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def _unregister_selection_visibility_timer():
    try:
        fbp_unregister_managed_timer(_selection_visibility_timer)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def _remove_named_handler():
    return remove_handlers_by_name(
        bpy.app.handlers.depsgraph_update_post,
        "effect_controls_depsgraph_update",
        module_suffix="effect_controls",
    )


def register():
    _remove_named_handler()
    if bool(getattr(bpy.app, "background", False)):
        return
    for issue in validate_effect_control_specs():
        fbp_warn(f"Viewport control contract: {issue}")
    register_classes(classes)
    try:
        # The shared Scene Sync depsgraph dispatcher invokes this observer with one
        # materialized update snapshot. Keep removing stale standalone handlers from
        # older builds, but do not add a second pass over depsgraph.updates.
        _register_selection_visibility_timer()
    except Exception:
        _unregister_selection_visibility_timer()
        unregister_classes(classes)
        raise


def unregister():
    _unregister_selection_visibility_timer()
    _remove_named_handler()
    clear_effect_controls_runtime_cache()
    unregister_classes(classes)
