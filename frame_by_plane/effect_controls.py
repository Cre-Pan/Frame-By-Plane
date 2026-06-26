"""Viewport controls for spatial Frame By Plane effect parameters.

The controls are lightweight Empty objects parented to the generated plane.
They are shown only for the active effect, never render, and map their local
transform back to normalized UV or directional effect properties.  The actual
effect properties remain the source of truth, so deleting a helper never damages
an effect and it can be recreated on selection.
"""

from __future__ import annotations

import math

import bpy
from bpy.app.handlers import persistent
from bpy.props import StringProperty
from bpy.types import Operator
from mathutils import Matrix

from .diagnostics import write_diagnostic_report
from .runtime import (
    FBP_DATA_ERRORS,
    fbp_render_mutation_blocked,
    fbp_set_rna_property_silent,
    fbp_warn,
)


SCHEMA_VERSION = 7
KEY_IS_CONTROL = "fbp_is_effect_control"
KEY_SCHEMA = "fbp_effect_control_schema"
KEY_EFFECT_ID = "fbp_effect_control_effect"
KEY_ROLE = "fbp_effect_control_role"
KEY_MODE = "fbp_effect_control_mode"
KEY_OWNER_NAME = "fbp_effect_control_owner"
KEY_SYNC_SIGNATURE = "fbp_effect_control_sync_signature"
KEY_IS_BOUNDS_GUIDE = "fbp_is_crop_extend_bounds_guide"
KEY_GUIDE_OWNER = "fbp_crop_extend_bounds_owner"

_SYNC_GUARD = set()
_CONTROL_NAMES = set()
_PENDING_CONTROL_SIGNATURES = {}
_LAST_SELECTION_SIGNATURE = None
_FBP_PLANE_MESH_KEYS = set()


# One source of truth for effects that expose spatial interaction. Modes:
# POINT: normalized UV center; OFFSET: UV offset around 0.5; DIRECTION: Z angle
# and X scale; paired ranges use IN/OUT boundaries plus one CENTER helper.
CONTROL_SPECS = {
    "PIXELATE": ({"role": "GRID", "mode": "OFFSET", "x": "fbp_pixelate_offset_x", "y": "fbp_pixelate_offset_y", "angle": "fbp_pixelate_rotation"},),
    "SWIRL": ({"role": "CENTER", "mode": "POINT", "x": "fbp_swirl_center_x", "y": "fbp_swirl_center_y", "angle": "fbp_swirl_angle"},),
    "BULGE_PINCH": ({"role": "CENTER", "mode": "POINT", "x": "fbp_bulge_pinch_center_x", "y": "fbp_bulge_pinch_center_y"},),
    "LENS_WARP": ({"role": "CENTER", "mode": "POINT", "x": "fbp_lens_warp_center_x", "y": "fbp_lens_warp_center_y"},),
    "WAVE_WARP": ({"role": "DIRECTION", "mode": "ANGLE", "angle": "fbp_wave_warp_angle"},),
    "RIPPLE_DISTORTION": ({"role": "CENTER", "mode": "POINT", "x": "fbp_ripple_distortion_center_x", "y": "fbp_ripple_distortion_center_y"},),
    "KALEIDOSCOPE": ({"role": "CENTER", "mode": "POINT", "x": "fbp_kaleidoscope_center_x", "y": "fbp_kaleidoscope_center_y", "angle": "fbp_kaleidoscope_rotation"},),
    "RIM": ({"role": "OFFSET", "mode": "OFFSET", "x": "fbp_rim_offset_x", "y": "fbp_rim_offset_y", "angle": "fbp_rim_rotation"},),
    "DIRECTIONAL_BLUR": ({"role": "DIRECTION", "mode": "DIRECTION", "x": "fbp_directional_blur_control_x", "y": "fbp_directional_blur_control_y", "angle": "fbp_directional_blur_angle", "distance": "fbp_directional_blur_distance"},),
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


def effect_control_driven_properties(effect_id):
    """Return properties represented directly by the viewport control."""
    effect_id = str(effect_id or "").upper()
    properties = set()
    for spec in CONTROL_SPECS.get(effect_id, ()):
        for key in ("x", "y", "angle", "distance"):
            value = str(spec.get(key, "") or "")
            if value:
                properties.add(value)
        mode = str(spec.get("mode", "") or "").upper()
        if mode == "GRADIENT_RANGE":
            properties.update({
                "fbp_gradient_mask_center_x", "fbp_gradient_mask_center_y",
                "fbp_gradient_mask_position", "fbp_gradient_mask_angle",
                "fbp_gradient_mask_feather",
            })
        elif mode == "GRADIENT_LIGHT_RANGE":
            properties.update({
                "fbp_gradient_light_center_x", "fbp_gradient_light_center_y",
                "fbp_gradient_light_angle", "fbp_gradient_shadow_position",
                "fbp_gradient_softness",
            })
        elif mode == "TILT_RANGE":
            properties.update({"fbp_tilt_shift_position", "fbp_tilt_shift_width", "fbp_tilt_shift_angle"})
        elif mode == "RANGE_CENTER":
            range_mode = str(spec.get("range_mode", "") or "").upper()
            if range_mode == "GRADIENT_RANGE":
                properties.update({
                    "fbp_gradient_mask_center_x", "fbp_gradient_mask_center_y",
                    "fbp_gradient_mask_position", "fbp_gradient_mask_angle",
                    "fbp_gradient_mask_feather",
                })
            elif range_mode == "GRADIENT_LIGHT_RANGE":
                properties.update({
                    "fbp_gradient_light_center_x", "fbp_gradient_light_center_y",
                    "fbp_gradient_light_angle", "fbp_gradient_shadow_position",
                    "fbp_gradient_softness",
                })
            elif range_mode == "TILT_RANGE":
                properties.update({"fbp_tilt_shift_position", "fbp_tilt_shift_width", "fbp_tilt_shift_angle"})
    return frozenset(properties)


def is_effect_control(obj):
    try:
        return bool(obj and obj.get(KEY_IS_CONTROL, False))
    except FBP_DATA_ERRORS:
        return False


def effect_control_owner(obj):
    if not is_effect_control(obj):
        return None
    try:
        plane = getattr(obj, "parent", None)
        rig = getattr(plane, "parent", None) if plane else None
        if rig and bool(getattr(rig, "is_fbp_control", False)):
            return rig
        name = str(obj.get(KEY_OWNER_NAME, "") or "")
        rig = bpy.data.objects.get(name) if name else None
        return rig if rig and bool(getattr(rig, "is_fbp_control", False)) else None
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
        xs, ys = zip(*points)
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


def _candidate_effect_controls(rig):
    """Yield all helpers that can belong to one rig without duplicates.

    The plane children are checked first because they are the canonical storage
    location. The scene/global fallbacks recover controls after duplicated rigs,
    Undo or older files where the runtime name cache has not been populated yet.
    """
    seen = set()
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    sources = []
    try:
        sources.append(tuple(getattr(plane, "children", ()) or ()))
    except FBP_DATA_ERRORS:
        pass
    cached = []
    for name in tuple(_CONTROL_NAMES):
        obj = bpy.data.objects.get(name)
        if obj is None:
            _CONTROL_NAMES.discard(name)
        else:
            cached.append(obj)
    sources.append(tuple(cached))
    try:
        scene = getattr(bpy.context, "scene", None)
        if scene is not None:
            sources.append(tuple(getattr(scene, "objects", ()) or ()))
    except FBP_DATA_ERRORS:
        pass
    # Last-resort recovery for controls stored in a non-active Scene. This path
    # is reached only while an effect helper is being ensured, not per frame.
    sources.append(tuple(getattr(bpy.data, "objects", ()) or ()))
    for source in sources:
        for obj in source:
            try:
                pointer = int(obj.as_pointer())
            except FBP_DATA_ERRORS:
                continue
            if pointer in seen or not is_effect_control(obj):
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
    return None


def _link_control(control, plane):
    collections = tuple(getattr(plane, "users_collection", ()) or ())
    collection = collections[0] if collections else getattr(bpy.context, "collection", None)
    collection = collection or getattr(getattr(bpy.context, "scene", None), "collection", None)
    if collection and control.name not in collection.objects:
        collection.objects.link(control)


def _remove_duplicate_controls(rig, effect_id, role, keep):
    """Remove stale helpers that represent the exact same control contract.

    Range effects intentionally own boundary and center controls with different roles; only
    duplicates matching owner, effect and role are removed. This repairs old
    files where repeated UI synchronization created overlapping nulls that
    fought over the same properties and appeared impossible to transform.
    """
    if rig is None or keep is None:
        return 0
    removed = 0
    for candidate in tuple(_candidate_effect_controls(rig)):
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

def _control_display_type(mode):
    mode = str(mode or "").upper()
    if mode in {"DIRECTION", "ANGLE"}:
        return "SINGLE_ARROW"
    if mode == "RANGE_CENTER":
        return "CUBE"
    return "CIRCLE"


def _control_base_rotation(mode):
    """Return the Empty display correction for one control shape.

    Blender CIRCLE empties are already authored in local XY and must therefore
    inherit the image-plane orientation without an extra rotation. A
    SINGLE_ARROW points along local Z and needs a +90° X correction to lie
    inside the image plane. Treating both shapes alike caused circles to appear
    horizontal while their parent plane was vertical.
    """
    mode = str(mode or "").upper()
    return (math.pi * 0.5, 0.0) if mode in {"DIRECTION", "ANGLE"} else (0.0, 0.0)


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
    if str(mode or "").upper() in {"DIRECTION", "ANGLE"}:
        size *= 1.25
    elif str(mode or "").upper() == "RANGE_CENTER":
        size *= 0.72
    elif str(role or "").upper() in {"IN", "OUT"}:
        size *= 0.88
    return size


def _control_color(role, mode):
    role = str(role or "").upper()
    mode = str(mode or "").upper()
    if role == "OUT":
        return (1.0, 0.32, 0.08, 1.0)
    if role == "IN":
        return (0.12, 0.48, 1.0, 1.0)
    if role == "CENTER" and mode == "RANGE_CENTER":
        return (1.0, 0.78, 0.12, 1.0)
    if mode in {"DIRECTION", "ANGLE"}:
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

    created = control is None
    if created:
        control = bpy.data.objects.new(_control_name(rig, effect_id, role), None)
        _link_control(control, plane)
        control.parent = plane
        control.matrix_parent_inverse = Matrix.Identity(4)
        base_x, base_y = _control_base_rotation(mode)
        control.location = (0.0, 0.0, _control_depth(rig))
        control.rotation_mode = "XYZ"
        control.rotation_euler = (base_x, base_y, 0.0)
        control.scale = (1.0, 1.0, 1.0)
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
    else:
        try:
            if str(control.get(KEY_OWNER_NAME, "") or "") != str(rig.name):
                control[KEY_OWNER_NAME] = rig.name
            if int(control.get(KEY_SCHEMA, 0) or 0) != SCHEMA_VERSION:
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

    _remove_duplicate_controls(rig, effect_id, role, control)

    try:
        if str(getattr(control, "rotation_mode", "") or "") != "XYZ":
            control.rotation_mode = "XYZ"
        target_rotation_x, target_rotation_y = _control_base_rotation(mode)
        if abs(float(control.rotation_euler.x) - target_rotation_x) > 1.0e-7:
            control.rotation_euler.x = target_rotation_x
        if abs(float(control.rotation_euler.y) - target_rotation_y) > 1.0e-7:
            control.rotation_euler.y = target_rotation_y
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
    try:
        target_size = _control_display_size(rig, mode, role)
        if abs(float(control.empty_display_size) - target_size) > 1.0e-6:
            control.empty_display_size = target_size
    except FBP_DATA_ERRORS:
        pass
    if select:
        _select_control_preserving_layer(bpy.context, rig, control)
    return control


def _select_control_preserving_layer(context, rig, control, related_controls=()):
    """Activate one helper without clearing the represented layer selection.

    Existing non-control selections and user visibility choices are preserved.
    Only helpers belonging to a different effect are deselected, preventing the
    active plane/rig from disappearing from multi-edit when the effect changes.
    """
    if context is None or rig is None or control is None:
        return False
    plane = getattr(rig, "fbp_plane_target", None)
    try:
        active_effect = str(control.get(KEY_EFFECT_ID, "") or "").upper()
        for selected in tuple(getattr(context, "selected_objects", ()) or ()):
            if not is_effect_control(selected) or selected is control:
                continue
            selected_effect = str(selected.get(KEY_EFFECT_ID, "") or "").upper()
            if selected_effect != active_effect or effect_control_owner(selected) is not rig:
                selected.select_set(False)
        _set_control_visibility(control, True)
        control.select_set(True)
        # The rig and render plane remain selected when Blender allows it, but
        # their hidden/viewport state is never forcefully changed here.
        for obj in (rig, plane):
            if obj is None:
                continue
            try:
                obj.select_set(True)
            except FBP_DATA_ERRORS:
                pass
        for related in tuple(related_controls or ()):
            if related is not None:
                _set_control_visibility(related, True)
        context.view_layer.objects.active = control
        return True
    except FBP_DATA_ERRORS:
        return False


def _control_signature(control):
    try:
        return tuple(round(float(value), 7) for value in (
            control.location.x, control.location.y,
            control.rotation_euler.z, control.scale.x,
        ))
    except FBP_DATA_ERRORS:
        return ()


def _set_control_transform(control, *, location=None, angle=None, scale_x=None):
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


def sync_controls_from_properties(rig, effect_id, *, create=False):
    effect_id = str(effect_id or "").upper()
    specs = CONTROL_SPECS.get(effect_id, ())
    if not rig or not specs:
        return False
    changed = False
    controls = {}
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
                float(getattr(rig, spec["angle"], 0.0))
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
                scale_x=max(0.08, (distance / 100.0) * width),
            ) or changed
        elif mode == "ANGLE":
            angle = float(getattr(rig, spec["angle"], 0.0))
            changed = _set_control_transform(
                control,
                location=_uv_to_local(rig, 0.5, 0.5),
                angle=angle,
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
            mx = cx + dx * (position - 0.5) * scale
            my = cy + dy * (position - 0.5) * scale
            half = feather * scale * 0.5
            changed = _set_control_transform(in_control, location=_uv_to_local(rig, mx - dx * half, my - dy * half), angle=angle) or changed
            changed = _set_control_transform(out_control, location=_uv_to_local(rig, mx + dx * half, my + dy * half), angle=angle) or changed
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
            changed = _set_control_transform(in_control, location=_uv_to_local(rig, mx - dx * half, my - dy * half), angle=angle) or changed
            changed = _set_control_transform(out_control, location=_uv_to_local(rig, mx + dx * half, my + dy * half), angle=angle) or changed
        elif mode == "TILT_RANGE":
            position = float(getattr(rig, "fbp_tilt_shift_position", 0.5))
            width = max(float(getattr(rig, "fbp_tilt_shift_width", 0.25)), 0.001)
            band_angle = float(getattr(rig, "fbp_tilt_shift_angle", 0.0))
            normal_angle = band_angle + math.pi * 0.5
            nx, ny = math.cos(normal_angle), math.sin(normal_angle)
            mx = 0.5 + nx * (position - 0.5)
            my = 0.5 + ny * (position - 0.5)
            changed = _set_control_transform(
                in_control,
                location=_uv_to_local(rig, mx - nx * width * 0.5, my - ny * width * 0.5),
                angle=normal_angle,
            ) or changed
            changed = _set_control_transform(
                out_control,
                location=_uv_to_local(rig, mx + nx * width * 0.5, my + ny * width * 0.5),
                angle=normal_angle,
            ) or changed
        changed = _sync_range_center_from_endpoints(rig, effect_id, controls) or changed
    return changed


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


def schedule_properties_from_control(control):
    """Apply a moved helper from a safe timer instead of inside depsgraph."""
    if not is_effect_control(control):
        return False
    try:
        control_name = str(control.name)
        _PENDING_CONTROL_SIGNATURES[control_name] = _control_signature(control)
    except FBP_DATA_ERRORS:
        return False

    def apply_latest_transform():
        try:
            current = bpy.data.objects.get(control_name)
            if current is not None and is_effect_control(current):
                sync_properties_from_control(current)
        finally:
            _PENDING_CONTROL_SIGNATURES.pop(control_name, None)
        return None

    try:
        from .safe_tasks import schedule_once
        return schedule_once(
            f"effect_controls.apply.{control_name}",
            apply_latest_transform,
            first_interval=0.01,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
            set_driven(spec.get("angle"), float(control.rotation_euler.z))
    elif mode == "DIRECTION":
        _plane, bounds, _uv = _plane_and_mapping(rig)
        width = max(abs(bounds[1] - bounds[0]), 1.0e-6)
        distance = max(0.0, float(control.scale.x) / width * 100.0)
        anchor_x, anchor_y = _local_to_uv(rig, control.location.x, control.location.y)
        set_driven(spec.get("x"), anchor_x)
        set_driven(spec.get("y"), anchor_y)
        set_driven(spec.get("angle"), float(control.rotation_euler.z))
        set_driven(spec.get("distance"), distance)
    elif mode == "ANGLE":
        set_driven(spec.get("angle"), float(control.rotation_euler.z))
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
            len(stored) >= 3 and len(current) >= 3
            and abs(float(current[2]) - float(stored[2])) > 1.0e-6
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
            scale = max(float(getattr(rig, "fbp_gradient_mask_scale", 1.0)), 1.0e-6)
            set_driven("fbp_gradient_mask_center_x", (u1 + u2) * 0.5)
            set_driven("fbp_gradient_mask_center_y", (v1 + v2) * 0.5)
            set_driven("fbp_gradient_mask_position", 0.5)
            set_driven("fbp_gradient_mask_angle", math.atan2(dy, dx))
            set_driven("fbp_gradient_mask_feather", math.hypot(dx, dy) / scale)
        _sync_range_center_from_endpoints(rig, effect_id)

    if changed_properties:
        _refresh_effect_from_control(rig, effect_id, changed_properties)
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
    try:
        candidates.extend(tuple(getattr(bpy.data, "objects", ()) or ()))
    except FBP_DATA_ERRORS:
        pass
    seen = set()
    for obj in candidates:
        try:
            pointer = int(obj.as_pointer())
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


def ensure_crop_extend_bounds_guide(rig):
    """Create one non-rendering wire rectangle at the original image bounds."""
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    if plane is None or getattr(plane, "type", "") != "MESH":
        return None
    guide = _find_crop_extend_guide(rig)
    created = guide is None
    if created:
        mesh = bpy.data.meshes.new(f"FBP Image Bounds Mesh • {rig.name}")
        guide = bpy.data.objects.new(f"FBP Image Bounds • {rig.name}", mesh)
        _link_control(guide, plane)
    try:
        if getattr(guide, "parent", None) is not plane:
            guide.parent = plane
            guide.matrix_parent_inverse = Matrix.Identity(4)
        guide.location = (0.0, 0.0, 0.018)
        guide.rotation_mode = "XYZ"
        guide.rotation_euler = (0.0, 0.0, 0.0)
        guide.scale = (1.0, 1.0, 1.0)
        guide.display_type = "WIRE"
        guide.show_in_front = True
        guide.hide_render = True
        guide.hide_select = True
        guide.color = (1.0, 0.55, 0.05, 1.0)
        guide[KEY_IS_BOUNDS_GUIDE] = True
        guide[KEY_GUIDE_OWNER] = rig.name
        from .builder import fbp_plane_reference_bounds
        source_bounds, _cropped, _extended, _uv = fbp_plane_reference_bounds(rig)
        min_x, max_x, min_y, max_y = source_bounds
        verts = [
            (min_x, min_y, 0.0), (max_x, min_y, 0.0),
            (max_x, max_y, 0.0), (min_x, max_y, 0.0),
        ]
        edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
        mesh = guide.data
        if mesh is None:
            mesh = bpy.data.meshes.new(f"FBP Image Bounds Mesh • {rig.name}")
            guide.data = mesh
        elif int(getattr(mesh, "users", 1) or 1) > 1:
            mesh = mesh.copy()
            mesh.name = f"FBP Image Bounds Mesh • {rig.name}"
            guide.data = mesh
        current = tuple(
            (round(float(v.co.x), 7), round(float(v.co.y), 7))
            for v in tuple(getattr(mesh, "vertices", ()) or ())
        )
        wanted = tuple((round(x, 7), round(y, 7)) for x, y, _z in verts)
        if current != wanted or len(getattr(mesh, "edges", ())) != 4:
            mesh.clear_geometry()
            mesh.from_pydata(verts, edges, [])
            mesh.update()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not create Crop/Extend image-bounds guide", exc)
        if created:
            try:
                mesh = getattr(guide, "data", None)
                bpy.data.objects.remove(guide, do_unlink=True)
                if mesh and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            except FBP_DATA_ERRORS:
                pass
        return None
    return guide


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
    if visible is None:
        try:
            from .geometry_nodes import fbp_active_effect_id
            visible = str(fbp_active_effect_id(rig) or "").upper() in {"CROP", "EXTEND"}
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            visible = False
    guide = _find_crop_extend_guide(rig)
    if guide is None and not bool(visible):
        return False
    guide = guide or ensure_crop_extend_bounds_guide(rig)
    if guide is None:
        return False
    # Refresh geometry when the guide already exists, including after source
    # aspect changes or duplicated rigs with a shared mesh datablock.
    if bool(visible):
        guide = ensure_crop_extend_bounds_guide(rig) or guide
    return _set_guide_visibility(guide, bool(visible))


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
    except FBP_DATA_ERRORS:
        return False
    return changed


def remove_effect_controls(rig, effect_id):
    effect_id = str(effect_id or "").upper()
    removed = False
    for child in tuple(_candidate_effect_controls(rig)):
        if not _helper_matches(
            child, rig, effect_id, str(child.get(KEY_ROLE, "") or "").upper()
        ):
            continue
        try:
            _CONTROL_NAMES.discard(child.name)
            _PENDING_CONTROL_SIGNATURES.pop(str(child.name), None)
            bpy.data.objects.remove(child, do_unlink=True)
            removed = True
        except FBP_DATA_ERRORS:
            continue
    return removed


def cleanup_orphan_effect_controls(scene):
    """Remove only FBP helper empties whose plane or rig no longer exists."""
    if scene is None:
        return 0
    removed = 0
    try:
        objects = tuple(getattr(scene, "objects", ()) or ())
    except FBP_DATA_ERRORS:
        objects = ()
    for control in objects:
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
            _CONTROL_NAMES.discard(control.name)
            mesh = getattr(control, "data", None) if is_crop_extend_bounds_guide(control) else None
            bpy.data.objects.remove(control, do_unlink=True)
            if mesh and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
            removed += 1
        except FBP_DATA_ERRORS:
            continue
    return removed

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


def sync_active_effect_controls(context=None, *, select_active=False):
    context = context or bpy.context
    try:
        from .layers import get_selected_rigs
        from .geometry_nodes import fbp_active_effect_id, fbp_effect_is_active
        rigs = list(get_selected_rigs(context) or ())
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    changed = False
    selected_rig_names = {str(getattr(rig, "name", "") or "") for rig in rigs}
    scene = getattr(context, "scene", None) if context else None
    try:
        scene_objects = tuple(getattr(scene, "objects", ()) or ())
    except FBP_DATA_ERRORS:
        scene_objects = ()
    for control in scene_objects:
        if is_crop_extend_bounds_guide(control):
            owner = _guide_owner(control)
            if owner is None or str(getattr(owner, "name", "") or "") not in selected_rig_names:
                _set_guide_visibility(control, False)
            continue
        if not is_effect_control(control):
            continue
        owner = effect_control_owner(control)
        if owner is None or str(getattr(owner, "name", "") or "") not in selected_rig_names:
            _set_control_visibility(control, False)

    selected_control = None
    selected_related = ()
    selected_rig = None
    for rig_index, rig in enumerate(rigs):
        enabled = bool(getattr(rig, "fbp_effect_controls_enabled", True))
        effect_id = str(fbp_active_effect_id(rig) or "").upper()
        sync_crop_extend_bounds_guide(rig, visible=effect_id in {"CROP", "EXTEND"})
        if not enabled or not effect_has_controls(effect_id) or not fbp_effect_is_active(rig, effect_id):
            hide_rig_effect_controls(rig)
            continue
        hide_rig_effect_controls(rig, except_effect_id=effect_id)
        controls = []
        for spec in CONTROL_SPECS[effect_id]:
            control = ensure_effect_control(rig, effect_id, spec)
            if control:
                controls.append(control)
                _set_control_visibility(control, True)
                changed = True
        if not any(control.name in _PENDING_CONTROL_SIGNATURES for control in controls):
            sync_controls_from_properties(rig, effect_id, create=True)
        if select_active and rig_index == 0 and controls:
            selected_control = controls[0]
            selected_related = tuple(controls[1:])
            selected_rig = rig
    if selected_control is not None:
        _select_control_preserving_layer(
            context, selected_rig, selected_control, selected_related
        )
    return changed


def schedule_active_effect_controls(context=None, *, select_active=False):
    """Defer helper creation to Blender's safe timer scheduler."""
    context = context or getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context else None
    try:
        scene_key = int(scene.as_pointer()) if scene else 0
    except FBP_DATA_ERRORS:
        scene_key = 0
    try:
        from .safe_tasks import schedule_once
        return schedule_once(
            f"effect_controls.sync_active.{scene_key}.{int(bool(select_active))}",
            lambda: sync_active_effect_controls(
                getattr(bpy, "context", None), select_active=select_active
            ),
            first_interval=0.01,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


@persistent
def effect_controls_depsgraph_update(scene, depsgraph):
    """Observe only relevant helper transforms and plane geometry changes.

    Shader-only updates are deliberately ignored. Reacting to them used to run
    the helper synchronizer after every rendered-viewport refresh; the helper
    then rewrote unchanged Object data and could restart the render indefinitely.
    """
    global _LAST_SELECTION_SIGNATURE
    if fbp_render_mutation_blocked():
        return
    try:
        updates = tuple(getattr(depsgraph, "updates", ()) or ())
    except FBP_DATA_ERRORS:
        return

    needs_control_refresh = False
    needs_lattice_refresh = False
    for update in updates:
        datablock = getattr(update, "id", None)
        if isinstance(datablock, bpy.types.Object):
            if is_effect_control(datablock):
                # Visibility, selection and custom-property writes are not user
                # movement. Only transform updates may drive effect parameters.
                if not bool(getattr(update, "is_updated_transform", False)):
                    continue
                try:
                    signature = _control_signature(datablock)
                    stored = tuple(float(value) for value in datablock.get(KEY_SYNC_SIGNATURE, ()) or ())
                    pending = _PENDING_CONTROL_SIGNATURES.get(str(datablock.name))
                    if signature != stored and signature != pending:
                        schedule_properties_from_control(datablock)
                except FBP_DATA_ERRORS:
                    pass
            elif str(getattr(datablock, "type", "") or "") == "LATTICE":
                # Freeform cages are native Edit Mode data. Never mirror Object
                # transforms back into point coordinates from the depsgraph:
                # doing so creates a transform/reset feedback loop.
                continue
            elif bool(getattr(datablock, "is_fbp_plane", False)):
                # Material/shader evaluation must never reposition controls.
                # Bounds can change only after object transforms or mesh geometry.
                if bool(getattr(update, "is_updated_transform", False)) or bool(
                    getattr(update, "is_updated_geometry", False)
                ):
                    needs_control_refresh = True
                    needs_lattice_refresh = True
            elif bool(getattr(datablock, "is_fbp_control", False)):
                if bool(getattr(update, "is_updated_transform", False)):
                    needs_lattice_refresh = True
            elif getattr(datablock, "type", "") == "CAMERA":
                if bool(getattr(update, "is_updated_transform", False)):
                    needs_lattice_refresh = True
        elif isinstance(datablock, bpy.types.Mesh) and scene is not None:
            if not bool(getattr(update, "is_updated_geometry", False)):
                continue
            try:
                mesh_key = (
                    int(datablock.as_pointer()),
                    str(getattr(datablock, "name_full", getattr(datablock, "name", "")) or ""),
                )
                is_fbp_mesh = bool(datablock.get("fbp_plane_mesh", False)) or mesh_key in _FBP_PLANE_MESH_KEYS
                if not is_fbp_mesh:
                    is_fbp_mesh = any(
                        bool(getattr(obj, "is_fbp_plane", False))
                        and getattr(obj, "data", None) is datablock
                        for obj in scene.objects
                    )
                    if is_fbp_mesh:
                        if len(_FBP_PLANE_MESH_KEYS) >= 2048:
                            _FBP_PLANE_MESH_KEYS.clear()
                        _FBP_PLANE_MESH_KEYS.add(mesh_key)
                        try:
                            datablock["fbp_plane_mesh"] = True
                        except FBP_DATA_ERRORS:
                            pass
                needs_control_refresh = is_fbp_mesh or needs_control_refresh
                needs_lattice_refresh = is_fbp_mesh or needs_lattice_refresh
            except FBP_DATA_ERRORS:
                pass
        elif isinstance(datablock, bpy.types.Lattice):
            # Native point edits already invalidate the Lattice modifier.
            # Additional Python writes are both unnecessary and recursive.
            continue
        elif isinstance(datablock, bpy.types.Camera):
            needs_lattice_refresh = True

    try:
        active_object = getattr(bpy.context, "active_object", None)
        active_key = int(active_object.as_pointer()) if active_object is not None else 0
        selected = tuple(sorted(
            int(obj.as_pointer()) for obj in tuple(getattr(bpy.context, "selected_objects", ()) or ())
            if obj is not None
        ))
        selection_signature = (active_key, selected)
    except FBP_DATA_ERRORS:
        active_object = None
        selection_signature = (0, ())
    if selection_signature != _LAST_SELECTION_SIGNATURE:
        _LAST_SELECTION_SIGNATURE = selection_signature
        needs_control_refresh = True
        if active_object is not None and str(getattr(active_object, "type", "") or "") == "LATTICE":
            try:
                from .layers import fbp_resolve_rig_from_any_object
                from .safe_tasks import schedule_once
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
    if needs_lattice_refresh and scene is not None:
        try:
            from .geometry_nodes import schedule_live_lattice_updates
            schedule_live_lattice_updates(scene)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass


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
                    _CONTROL_NAMES.discard(control.name)
                    _PENDING_CONTROL_SIGNATURES.pop(str(control.name), None)
                    bpy.data.objects.remove(control, do_unlink=True)
                    stats["control_repairs"] += 1
                continue
            key = (int(owner.as_pointer()), effect_id, role)
            if key in seen:
                stats["control_duplicates"] += 1
                issues.append(f"{control.name}: duplicate of {seen[key].name}")
                if repair:
                    _CONTROL_NAMES.discard(control.name)
                    _PENDING_CONTROL_SIGNATURES.pop(str(control.name), None)
                    bpy.data.objects.remove(control, do_unlink=True)
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
                or str(getattr(control, "rotation_mode", "") or "") != "XYZ"
                or abs(float(control.rotation_euler.x) - _control_base_rotation(expected_mode)[0]) > 1.0e-6
                or abs(float(control.rotation_euler.y) - _control_base_rotation(expected_mode)[1]) > 1.0e-6
                or str(getattr(control, "empty_display_type", "") or "") != _control_display_type(expected_mode)
                or abs(float(getattr(control, "empty_display_size", 0.0)) - _control_display_size(owner, expected_mode, role)) > 1.0e-5
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
        rigs = [obj for obj in objects if bool(getattr(obj, "is_fbp_control", False))]
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
                mesh = getattr(guide, "data", None)
                bpy.data.objects.remove(guide, do_unlink=True)
                if mesh is not None and int(getattr(mesh, "users", 0) or 0) == 0:
                    bpy.data.meshes.remove(mesh)
                stats["control_repairs"] += 1
            except FBP_DATA_ERRORS:
                pass

    return {
        "stats": stats,
        "issues": tuple(issues),
        "warnings": tuple(warnings),
        "repaired": int(stats["control_repairs"]),
    }


class FBP_OT_ResetEffectControl(Operator):
    bl_idname = "fbp.reset_effect_control"
    bl_label = "Reset Viewport Control"
    bl_description = "Reset only the position, rotation and range represented by this viewport control"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        try:
            from .layers import get_selected_rigs
            return bool(get_selected_rigs(context))
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False

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
    bl_description = "Create, reveal and select the viewport control for this effect"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        try:
            from .layers import get_selected_rigs
            return bool(get_selected_rigs(context))
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False

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
        rig.fbp_effect_controls_enabled = True
        controls = [ensure_effect_control(rig, effect_id, spec) for spec in specs]
        sync_controls_from_properties(rig, effect_id, create=True)
        controls = [control for control in controls if control]
        if not controls:
            return {"CANCELLED"}
        for child in controls:
            _set_control_visibility(child, True)
        _select_control_preserving_layer(
            context, rig, controls[0], tuple(controls[1:])
        )
        return {"FINISHED"}


classes = (FBP_OT_ResetEffectControl, FBP_OT_RepairEffectControls, FBP_OT_SelectEffectControl,)


def _remove_named_handler():
    for handler in list(bpy.app.handlers.depsgraph_update_post):
        if handler is effect_controls_depsgraph_update or (
            getattr(handler, "__name__", "") == "effect_controls_depsgraph_update"
            and str(getattr(handler, "__module__", "")).endswith("effect_controls")
        ):
            try:
                bpy.app.handlers.depsgraph_update_post.remove(handler)
            except FBP_DATA_ERRORS:
                pass


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _remove_named_handler()
    bpy.app.handlers.depsgraph_update_post.append(effect_controls_depsgraph_update)


def unregister():
    _remove_named_handler()
    _PENDING_CONTROL_SIGNATURES.clear()
    _CONTROL_NAMES.clear()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except FBP_DATA_ERRORS:
            pass
