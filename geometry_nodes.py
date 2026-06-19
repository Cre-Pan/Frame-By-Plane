"""Frame by Plane geometry and shader effect stack.

Geometry effects are stored as Geometry Nodes modifiers on the generated plane.
Shader effects are stored as tagged group nodes inside the plane material and are
inserted into the controlled UV or Color stages.

Bundled node groups are appended lazily from ``assets/fbp_geometry_nodes.blend``.
Alpha-aware geometry effects receive a private node-group copy per plane so the
current image/sequence and ImageUser timing never leak between layers.
"""

from pathlib import Path
import copy
import json
import math
import time
import uuid

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.app.handlers import persistent
from bpy.types import Menu, Operator, UIList
from mathutils import Vector

from .builtin_effects import create_builtin_effect_group, _builtin_group_is_complete
from .custom_effects import (
    find_custom_effect_group,
    refresh_one_custom_effect_definition,
)
from .matrix_presets import (
    ASCII_ATLAS_COLUMNS,
    ASCII_PRESET_ROWS,
    ASCII_TEXT_GLYPH_LIMIT,
    ascii_level_gradient,
)

from .effect_schema import (
    FBP_EFFECT_SCHEMA_VERSION,
    FBP_EFFECT_INSTANCE_KEY,
    FBP_EFFECT_INSTANCE_OWNER_KEY,
    FBP_EFFECT_INSTANCE_VERSION,
    FBP_EFFECT_INSTANCE_VERSION_KEY,
    assign_effect_instance_id,
    ensure_effect_instance_id,
    effect_instance_id,
    finalize_effect_registry,
    new_effect_instance_id,
)

from .effects_registry import (
    FBP_EFFECT_MESH_WIGGLE,
    FBP_EFFECT_WIND_BENDER,
    FBP_EFFECT_MESH_RIPPLE,
    FBP_EFFECT_PAPER_CURL,
    FBP_EFFECT_CUTOUT_OUTLINE,
    FBP_EFFECT_EXTRUDED_CUTOUT,
    FBP_EFFECT_CAMERA_SCALE_LOCK,
    FBP_EFFECT_CAMERA_BILLBOARD,
    FBP_EFFECT_THICKNESS,
    FBP_EFFECT_FELT_FUZZ,
    FBP_EFFECT_PIXELATE,
    FBP_EFFECT_CRT_SCANLINES,
    FBP_EFFECT_DIGITAL_NOISE,
    FBP_EFFECT_CHROMA_KEY,
    FBP_EFFECT_HALFTONE,
    FBP_EFFECT_DOT_MATRIX,
    FBP_EFFECT_ASCII_MATRIX,
    FBP_EFFECT_TEXT_MATRIX,
    FBP_EFFECT_REGISTRY,
    FBP_EFFECT_REGISTRY_ISSUES,
    fbp_refresh_custom_effect_registry,
    FBP_SHADER_STAGE_ORDER,
    FBP_BASE_EFFECT_MENU_ORDER,
    FBP_3D_EFFECT_MENU_ORDER,
    FBP_IMAGE_EFFECT_MENU_SECTIONS,
    FBP_MESH_EFFECT_MENU_SECTIONS,
    fbp_effect_definition,
    fbp_effect_supported_for_rig,
    fbp_effect_tooltip,
    fbp_normalize_effect_id,
    fbp_rig_media_type,
)

from .runtime import (
    fbp_runtime_get,
    fbp_render_mutation_blocked,
    fbp_is_silent_property_update,
    fbp_undo_guard_active,
    fbp_set_rna_property_silent,
    fbp_warn,
    fbp_remove_action_fcurves,
    fbp_action_fcurves,
    fbp_obj_runtime_key,
)


FBP_GN_LIBRARY_FILENAME = "fbp_geometry_nodes.blend"
FBP_ALPHA_MASK_PATCH_VERSION = 7

_FBP_EFFECT_HEALTH_CACHE = globals().get("_FBP_EFFECT_HEALTH_CACHE", {})
_FBP_EFFECT_GROUP_CACHE = globals().get("_FBP_EFFECT_GROUP_CACHE", {})
_FBP_INTERFACE_INPUT_CACHE = globals().get("_FBP_INTERFACE_INPUT_CACHE", {})
_FBP_MATRIX_IMAGE_NODE_CACHE = globals().get("_FBP_MATRIX_IMAGE_NODE_CACHE", {})
_FBP_EFFECT_IDS_CACHE = globals().get("_FBP_EFFECT_IDS_CACHE", {})
_FBP_EFFECT_IDS_CACHE_TIME = globals().get("_FBP_EFFECT_IDS_CACHE_TIME", {})
if not isinstance(_FBP_EFFECT_IDS_CACHE_TIME, dict):
    _FBP_EFFECT_IDS_CACHE_TIME = {}
_FBP_EFFECT_IDS_CACHE_SECONDS = 4.0
_FBP_EFFECT_RUNTIME_PROFILE_CACHE = globals().get("_FBP_EFFECT_RUNTIME_PROFILE_CACHE", {})
_FBP_EFFECT_SCENE_RIG_CACHE = globals().get("_FBP_EFFECT_SCENE_RIG_CACHE", {})
_FBP_EFFECT_SCENE_CACHE_SECONDS = 2.0
_FBP_EFFECT_PROFILE_CACHE_SECONDS = 4.0
_FBP_EFFECT_HEALTH_CACHE_SECONDS = 2.0
_FBP_CAMERA_BINDING_CACHE = globals().get("_FBP_CAMERA_BINDING_CACHE", {})
_FBP_CUSTOM_SHADER_SYNC_PENDING = globals().get("_FBP_CUSTOM_SHADER_SYNC_PENDING", {})
_FBP_CUSTOM_GEOMETRY_INIT_PENDING = globals().get("_FBP_CUSTOM_GEOMETRY_INIT_PENDING", {})
_FBP_CUSTOM_GEOMETRY_SOCKET_CACHE = globals().get("_FBP_CUSTOM_GEOMETRY_SOCKET_CACHE", {})
_FBP_CUSTOM_SHADER_SOCKET_CACHE = globals().get("_FBP_CUSTOM_SHADER_SOCKET_CACHE", {})
_FBP_CUSTOM_SHADER_SYNC_STATE_CACHE = globals().get("_FBP_CUSTOM_SHADER_SYNC_STATE_CACHE", {})
_FBP_EFFECT_STACK_OWNER_CACHE = globals().get("_FBP_EFFECT_STACK_OWNER_CACHE", {})
_FBP_EFFECT_INSTANCE_OWNER_CACHE = globals().get("_FBP_EFFECT_INSTANCE_OWNER_CACHE", {})
_FBP_CUSTOM_SOCKET_CACHE_SECONDS = 0.25
_FBP_CUSTOM_SHADER_SYNC_CACHE_SECONDS = 0.75
_FBP_USER_PRESET_CACHE = globals().get("_FBP_USER_PRESET_CACHE", {"stamp": None, "data": {}})
if not isinstance(_FBP_USER_PRESET_CACHE, dict):
    _FBP_USER_PRESET_CACHE = {"stamp": None, "data": {}}
_FBP_DEFAULT_FONT_CACHE = globals().get("_FBP_DEFAULT_FONT_CACHE", None)
_FBP_PREVIOUS_OBJECT_CONTEXT_CALLBACK = globals().get("_fbp_draw_object_context_effects")



_FBP_EVOLVE_HANDLER_ACTIVE = False
_FBP_EFFECT_PLAYBACK_ACTIVE = False
_FBP_EFFECT_CLIPBOARD = {}




def _fbp_effect_visibility_key(effect_id):
    return f"fbp_effect_visible_{fbp_normalize_effect_id(effect_id).lower()}"


def _fbp_effect_render_visibility_key(effect_id):
    return f"fbp_effect_render_visible_{fbp_normalize_effect_id(effect_id).lower()}"


def _fbp_effect_state_key(effect_id, suffix):
    return f"fbp_effect_{fbp_normalize_effect_id(effect_id).lower()}_{suffix}"


def fbp_effect_input_source(rig, effect_id):
    definition = fbp_effect_definition(effect_id)
    if not rig or not definition.get("supports_input_source"):
        return "PREVIOUS"
    default_source = str(definition.get("default_input_source", "PREVIOUS") or "PREVIOUS").upper()
    if default_source not in {"PREVIOUS", "ORIGINAL", "FINAL"}:
        default_source = "PREVIOUS"
    try:
        value = str(
            rig.get(_fbp_effect_state_key(effect_id, "input_source"), default_source)
            or default_source
        ).upper()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        value = default_source
    return value if value in {"PREVIOUS", "ORIGINAL", "FINAL"} else default_source


def fbp_set_effect_input_source(rig, effect_id, source):
    definition = fbp_effect_definition(effect_id)
    if not rig or not definition.get("supports_input_source"):
        return False
    source = str(source or "PREVIOUS").upper()
    default_source = str(definition.get("default_input_source", "PREVIOUS") or "PREVIOUS").upper()
    if default_source not in {"PREVIOUS", "ORIGINAL", "FINAL"}:
        default_source = "PREVIOUS"
    if source not in {"PREVIOUS", "ORIGINAL", "FINAL"}:
        source = default_source
    key = _fbp_effect_state_key(effect_id, "input_source")
    try:
        if str(rig.get(key, default_source) or default_source).upper() == source:
            return False
        rig[key] = source
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    if definition.get("kind") == "SHADER":
        for material in _fbp_plane_materials(rig):
            _fbp_rebuild_shader_stage(material, str(definition.get("stage", "COLOR")))
    return True


def fbp_effect_debug_mode(rig, effect_id):
    definition = fbp_effect_definition(effect_id)
    modes = tuple(item[0] for item in definition.get("debug_modes", ()))
    if not modes:
        return "FINAL"
    try:
        value = str(rig.get(_fbp_effect_state_key(effect_id, "debug"), "FINAL") or "FINAL").upper()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        value = "FINAL"
    return value if value in modes else modes[0]


def fbp_set_effect_debug_mode(rig, effect_id, mode):
    definition = fbp_effect_definition(effect_id)
    modes = tuple(item[0] for item in definition.get("debug_modes", ()))
    if not rig or not modes:
        return False
    mode = str(mode or modes[0]).upper()
    if mode not in modes:
        mode = modes[0]
    key = _fbp_effect_state_key(effect_id, "debug")
    try:
        if str(rig.get(key, modes[0]) or modes[0]).upper() == mode:
            return False
        rig[key] = mode
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    if definition.get("kind") == "SHADER":
        return fbp_update_shader_effect(rig, effect_id) or True
    return fbp_update_geometry_effect(rig, effect_id) or True


def _fbp_debug_mode_value(definition, mode):
    modes = tuple(item[0] for item in definition.get("debug_modes", ()))
    try:
        return float(modes.index(str(mode or "FINAL").upper()))
    except ValueError:
        return 0.0


def _fbp_stored_effect_render_visibility(rig, effect_id, default=True):
    if not rig:
        return bool(default)
    try:
        return bool(rig.get(_fbp_effect_render_visibility_key(effect_id), default))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return bool(default)


def _fbp_store_effect_render_visibility(rig, effect_id, visible):
    if not rig:
        return False
    key = _fbp_effect_render_visibility_key(effect_id)
    visible = bool(visible)
    try:
        if key in rig and bool(rig.get(key, True)) == visible:
            return False
        rig[key] = visible
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_clear_effect_render_visibility(rig, effect_id):
    if not rig:
        return False
    key = _fbp_effect_render_visibility_key(effect_id)
    try:
        if key in rig:
            del rig[key]
            return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        pass
    return False


def _fbp_stored_effect_visibility(rig, effect_id, default=True):
    if not rig:
        return bool(default)
    try:
        return bool(rig.get(_fbp_effect_visibility_key(effect_id), default))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return bool(default)


def _fbp_store_effect_visibility(rig, effect_id, visible):
    if not rig:
        return False
    key = _fbp_effect_visibility_key(effect_id)
    visible = bool(visible)
    try:
        if key in rig and bool(rig.get(key, True)) == visible:
            return False
        rig[key] = visible
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_clear_effect_visibility(rig, effect_id):
    if not rig:
        return False
    key = _fbp_effect_visibility_key(effect_id)
    try:
        if key in rig:
            del rig[key]
            return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        pass
    return False


def fbp_geometry_nodes_library_path():
    return Path(__file__).resolve().parent / "assets" / FBP_GN_LIBRARY_FILENAME










def _fbp_animation_key(effect_id, suffix):
    effect_id = fbp_normalize_effect_id(effect_id).lower()
    return f"fbp_anim_{effect_id}_{suffix}"


_FBP_NOISE_MASK_64 = (1 << 64) - 1


def _fbp_stable_string_seed(value):
    """Return a stable process-independent 64-bit seed for an effect id."""
    result = 1469598103934665603
    for byte in str(value or "").encode("utf8", "replace"):
        result ^= int(byte)
        result = (result * 1099511628211) & _FBP_NOISE_MASK_64
    return result


def _fbp_mix64(value):
    """SplitMix64 finalizer used as a non-periodic frame hash."""
    value = int(value) & _FBP_NOISE_MASK_64
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & _FBP_NOISE_MASK_64
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & _FBP_NOISE_MASK_64
    value ^= value >> 31
    return value & _FBP_NOISE_MASK_64


def _fbp_effect_noise_u01(effect_id, stream_seed, step_index):
    """Deterministic random value for an unbounded timeline step.

    There is deliberately no modulo/loop length: every held timeline step is
    hashed independently, so Evolve does not return to an earlier phase.
    """
    value = _fbp_stable_string_seed(effect_id)
    value ^= (int(stream_seed) * 0x9E3779B97F4A7C15) & _FBP_NOISE_MASK_64
    value ^= (int(step_index) * 0xD1B54A32D192ED03) & _FBP_NOISE_MASK_64
    mixed = _fbp_mix64(value)
    return float(mixed >> 11) / float(1 << 53)


# Precomputed once at import time: frame-change handlers must avoid rebuilding
# registry-derived lists on every evaluated frame.
FBP_EVOLVE_EFFECT_PROPERTIES = tuple(
    (effect_id, _fbp_animation_key(effect_id, "evolve"))
    for effect_id, definition in FBP_EFFECT_REGISTRY.items()
    if definition.get("evolve_property")
)
FBP_ALPHA_AWARE_GEOMETRY_EFFECT_IDS = tuple(
    effect_id
    for effect_id, definition in FBP_EFFECT_REGISTRY.items()
    if definition.get("kind") == "GEOMETRY" and definition.get("alpha_aware")
)
FBP_FRAME_SYNC_GEOMETRY_EFFECT_IDS = tuple(
    effect_id
    for effect_id, definition in FBP_EFFECT_REGISTRY.items()
    if definition.get("kind") == "GEOMETRY"
    and (definition.get("alpha_aware") or definition.get("image_aware"))
)
FBP_FRAME_SYNC_SHADER_EFFECT_IDS = tuple(
    effect_id
    for effect_id, definition in FBP_EFFECT_REGISTRY.items()
    if definition.get("kind") == "SHADER" and definition.get("image_aware")
)


def _fbp_effect_animatable_properties(definition):
    """Return RNA properties whose keyframes must be pushed into effect sockets."""
    properties = list(dict(definition.get("property_map", {})).keys())
    properties.extend(definition.get("extra_properties", ()))
    return tuple(dict.fromkeys(str(name) for name in properties if name))


FBP_ANIMATED_PROPERTY_EFFECTS = {}
for _effect_id, _definition in FBP_EFFECT_REGISTRY.items():
    for _prop_name in _fbp_effect_animatable_properties(_definition):
        FBP_ANIMATED_PROPERTY_EFFECTS.setdefault(_prop_name, []).append(_effect_id)
# Mesh Wiggle exposes seed outside its socket map but still needs real keyframe playback.
for _prop_name in ("fbp_mesh_wiggle_seed", "fbp_mesh_wiggle_unique_seed"):
    FBP_ANIMATED_PROPERTY_EFFECTS.setdefault(_prop_name, []).append(FBP_EFFECT_MESH_WIGGLE)
FBP_ANIMATED_PROPERTY_EFFECTS = {
    key: tuple(dict.fromkeys(value)) for key, value in FBP_ANIMATED_PROPERTY_EFFECTS.items()
}


def _fbp_scene_camera_binding_is_animated(scene, active_effect_ids):
    """Return whether camera-aware sockets can change between rendered frames.

    Object transforms are evaluated natively by Geometry Nodes. Python work is
    needed only for camera switches or numeric projection sockets driven by an
    animated Camera datablock.
    """
    camera_effects = [
        fbp_effect_definition(effect_id)
        for effect_id in active_effect_ids
        if fbp_effect_definition(effect_id).get("camera_aware")
    ]
    if not camera_effects:
        return False

    try:
        if any(getattr(marker, "camera", None) is not None for marker in scene.timeline_markers):
            return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    projection_sockets = any(
        any(
            str((definition.get("camera_contract", {}) or {}).get(key, "") or "")
            for key in (
                "lens_socket", "sensor_width_socket", "ortho_scale_socket",
                "perspective_socket", "shift_x_socket", "shift_y_socket",
            )
        )
        for definition in camera_effects
    )
    if not projection_sockets:
        return False

    camera = _fbp_scene_camera(scene)
    camera_data = getattr(camera, "data", None) if camera else None
    if camera_data is None:
        return False
    animated_paths = {"type", "lens", "sensor_width", "ortho_scale", "shift_x", "shift_y"}
    try:
        curves = fbp_action_fcurves(camera_data)
        if any(
            not bool(getattr(curve, "mute", False))
            and str(getattr(curve, "data_path", "") or "") in animated_paths
            for curve in curves or ()
        ):
            return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        animation_data = getattr(camera_data, "animation_data", None)
        for curve in getattr(animation_data, "drivers", ()) or ():
            if str(getattr(curve, "data_path", "") or "") in animated_paths:
                return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return False


def fbp_scene_requires_effect_frame_sync(scene):
    """Return whether active effects require Python writes for rendered frames.

    Camera transforms and ordinary native ImageUser playback remain fully native.
    The render session only keeps this handler active for image-aware effects,
    animated effect properties, procedural Evolve controls, or camera projection
    values that are passed through modifier sockets.
    """
    if scene is None:
        return False
    try:
        from .layers import iter_scene_fbp_rigs
        rigs = iter_scene_fbp_rigs(scene)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        # Unknown effect state must never opt a render into native pass-through.
        return True

    frame_sync_ids = set(FBP_FRAME_SYNC_GEOMETRY_EFFECT_IDS)
    frame_sync_ids.update(FBP_FRAME_SYNC_SHADER_EFFECT_IDS)
    for rig in rigs:
        try:
            active_effect_ids = set(_fbp_runtime_effect_ids(rig))
            if not active_effect_ids:
                continue
            if active_effect_ids.intersection(frame_sync_ids):
                return True
            if _fbp_scene_camera_binding_is_animated(scene, active_effect_ids):
                return True
            if any(
                effect_id in active_effect_ids
                and bool(getattr(rig, property_key, False))
                for effect_id, property_key in FBP_EVOLVE_EFFECT_PROPERTIES
            ):
                return True

            curves = fbp_action_fcurves(rig)
            for curve in curves or ():
                if bool(getattr(curve, "mute", False)):
                    continue
                data_path = str(getattr(curve, "data_path", "") or "")
                if any(
                    effect_id in active_effect_ids
                    for effect_id in FBP_ANIMATED_PROPERTY_EFFECTS.get(data_path, ())
                ):
                    return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            # A preflight read failure is not evidence that frame sync is
            # unnecessary. Keep the conservative managed render path enabled.
            return True
    return False


def _fbp_set_custom_property_ui(rig, key, *, default, minimum=None, maximum=None, description=""):
    try:
        if key not in rig:
            rig[key] = default
        ui = rig.id_properties_ui(key)
        kwargs = {"default": default}
        if minimum is not None:
            kwargs["min"] = minimum
        if maximum is not None:
            kwargs["max"] = maximum
        if description:
            kwargs["description"] = description
        ui.update(**kwargs)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        try:
            if key not in rig:
                rig[key] = default
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass


def fbp_assign_effect_layer_seed(rig, effect_id, *, force=False):
    """Return a persistent per-layer seed for a specific effect."""
    if not rig:
        return 0
    key = _fbp_animation_key(effect_id, "layer_seed")
    try:
        current = int(getattr(rig, key, 0) or 0) if hasattr(rig, key) else int(rig.get(key, 0) or 0)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        current = 0
    if force or current <= 0:
        current = int(uuid.uuid4().int % 2147483646) + 1
        try:
            if hasattr(rig, key):
                fbp_set_rna_property_silent(rig, key, current)
            else:
                rig[key] = current
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return current


def _fbp_effect_animation_defaults(definition):
    return {
        "evolve": (False, None, None, "Animate the procedural parameter with non-repeating deterministic noise"),
        "step": (4, 1, 240, "Number of frames held before a new procedural value is generated"),
        "seed": (0, 0, 999999, "Select the deterministic infinite procedural-noise stream"),
        "unique": (False, None, None, "Give every layer an independent procedural-noise stream"),
        "layer_seed": (0, 0, 2147483647, "Persistent internal seed used by Unique per Layer"),
        # Hidden amplitude shared by the current non-repeating effect stack.
        "amount": (float(definition.get("evolve_amount", 1.0)), -100000.0, 100000.0, "Automatic evolve amount"),
    }


def fbp_read_effect_animation_state(rig, effect_id):
    """Read procedural animation state without mutating Blender datablocks.

    This variant is safe inside frame handlers and UI drawing. Registered RNA
    properties already expose their defaults; only the hidden ``amount`` may be
    absent. A deterministic fallback seed avoids assigning ID properties from a
    frame callback when an older/current file has Unique enabled but no seed.
    """
    definition = fbp_effect_definition(effect_id)
    if rig is None or not definition:
        return {}
    result = {}
    for suffix, (default, _minimum, _maximum, _description) in _fbp_effect_animation_defaults(definition).items():
        key = _fbp_animation_key(effect_id, suffix)
        try:
            if hasattr(rig, key):
                result[suffix] = getattr(rig, key)
            else:
                result[suffix] = rig.get(key, default)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            result[suffix] = default
    if bool(result.get("unique", False)) and int(result.get("layer_seed", 0) or 0) <= 0:
        try:
            stable_name = str(getattr(rig, "name_full", getattr(rig, "name", "")) or "")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            stable_name = ""
        result["layer_seed"] = int(
            _fbp_stable_string_seed(f"{stable_name}:{fbp_normalize_effect_id(effect_id)}")
            % 2147483646
        ) + 1
    return result


def fbp_ensure_effect_animation_state(rig, effect_id):
    """Initialize missing persistent animation state from a mutation-safe path."""
    definition = fbp_effect_definition(effect_id)
    if rig is None or not definition:
        return {}
    defaults = _fbp_effect_animation_defaults(definition)
    for suffix, (default, minimum, maximum, description) in defaults.items():
        key = _fbp_animation_key(effect_id, suffix)
        if hasattr(rig, key):
            continue
        _fbp_set_custom_property_ui(
            rig,
            key,
            default=default,
            minimum=minimum,
            maximum=maximum,
            description=description,
        )
    state = fbp_read_effect_animation_state(rig, effect_id)
    if bool(state.get("unique", False)):
        try:
            current_seed = int(getattr(rig, _fbp_animation_key(effect_id, "layer_seed"), 0) or 0)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            current_seed = 0
        if current_seed <= 0:
            state["layer_seed"] = fbp_assign_effect_layer_seed(rig, effect_id)
    return state



def fbp_reset_effect_animation_state(rig, effect_id):
    """Restore registered animation controls and remove hidden ID properties."""
    definition = fbp_effect_definition(effect_id)
    if rig is None or not definition:
        return False
    changed = False
    for suffix, (default, _minimum, _maximum, _description) in _fbp_effect_animation_defaults(definition).items():
        key = _fbp_animation_key(effect_id, suffix)
        try:
            if hasattr(rig, key):
                current = getattr(rig, key)
                if current != default:
                    changed = fbp_set_rna_property_silent(rig, key, default) or changed
                continue
            if key in rig:
                del rig[key]
                changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
            continue
    return changed

def _fbp_quality_contracts(definition):
    """Return normalized quality contracts declared by an effect definition."""
    contracts = definition.get("quality_contracts", ()) if definition else ()
    return tuple(contract for contract in contracts if isinstance(contract, dict))


def _fbp_quality_value(value, contract):
    """Clamp one quality value while preserving documented Auto sentinels."""
    try:
        raw = int(value)
        if bool(contract.get("zero_is_auto", False)) and raw <= 0:
            return 0
        return max(int(contract.get("minimum", 0)), raw)
    except (TypeError, ValueError, AttributeError):
        return value


def _fbp_effective_quality_value(rig, effect_id, prop_name, value):
    """Resolve viewport quality, including temporary playback overrides."""
    definition = fbp_effect_definition(effect_id)
    for contract in _fbp_quality_contracts(definition):
        if prop_name != str(contract.get("viewport_property", "")):
            continue
        viewport_value = _fbp_quality_value(value, contract)
        if not _FBP_EFFECT_PLAYBACK_ACTIVE:
            return viewport_value
        if effect_id == FBP_EFFECT_TEXT_MATRIX and not bool(
            getattr(rig, "fbp_text_matrix_auto_playback_limit", True)
        ):
            return viewport_value
        playback_property = str(contract.get("playback_property", ""))
        if not playback_property:
            return viewport_value
        try:
            playback_value = _fbp_quality_value(getattr(rig, playback_property), contract)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return viewport_value
        if bool(contract.get("zero_is_auto", False)) and playback_value == 0:
            return viewport_value
        if str(contract.get("playback_mode", "REPLACE")).upper() == "LIMIT":
            if bool(contract.get("zero_is_auto", False)) and viewport_value == 0:
                return 0
            try:
                return min(int(viewport_value), int(playback_value))
            except (TypeError, ValueError):
                return viewport_value
        return playback_value
    return value


def _fbp_refresh_effect_quality(scene=None):
    """Refresh only the sockets participating in playback quality contracts."""
    try:
        from .layers import iter_scene_fbp_rigs
        rigs = iter_scene_fbp_rigs(scene or getattr(bpy.context, "scene", None))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return
    for rig in rigs:
        for effect_id in _fbp_runtime_effect_ids(rig):
            definition = fbp_effect_definition(effect_id)
            contracts = _fbp_quality_contracts(definition)
            if not contracts or not fbp_effect_is_active(rig, effect_id):
                continue
            properties = {
                str(contract.get("viewport_property", ""))
                for contract in contracts
                if str(contract.get("viewport_property", ""))
            }
            if not properties:
                continue
            try:
                fbp_update_geometry_effect(
                    rig, effect_id, scene=scene, sync_alpha=False,
                    property_names=properties,
                )
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue


@persistent
def fbp_effect_playback_pre(scene, depsgraph=None):
    """Apply playback-specific quality contracts for all active effects."""
    del depsgraph
    global _FBP_EFFECT_PLAYBACK_ACTIVE
    _FBP_EFFECT_PLAYBACK_ACTIVE = True
    # Keyframes may have been added since the previous playback session. Build
    # one fresh property map now, then reuse it throughout playback.
    _FBP_EFFECT_RUNTIME_PROFILE_CACHE.clear()
    _fbp_refresh_effect_quality(scene)


@persistent
def fbp_effect_playback_post(scene, depsgraph=None):
    """Restore viewport quality contracts after animation playback."""
    del depsgraph
    global _FBP_EFFECT_PLAYBACK_ACTIVE
    _FBP_EFFECT_PLAYBACK_ACTIVE = False
    _fbp_refresh_effect_quality(scene)

def _fbp_effect_runtime_value(rig, effect_id, prop_name, value, scene=None):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if effect_id == FBP_EFFECT_MESH_WIGGLE and prop_name == "fbp_mesh_wiggle_w":
        value = fbp_mesh_wiggle_effective_w(rig)
    if not definition or prop_name != definition.get("evolve_property"):
        return value
    state = fbp_read_effect_animation_state(rig, effect_id)
    if not bool(state.get("evolve", False)):
        return value
    try:
        base = float(value)
        stepped_frames = max(1, int(state.get("step", 4)))
        stream_seed = int(state.get("seed", 0))
        if bool(state.get("unique", False)):
            stream_seed += int(state.get("layer_seed", 0) or 0)
        amount = float(state.get("amount", definition.get("evolve_amount", 1.0)))
        scene = scene or getattr(bpy.context, "scene", None)
        frame = int(getattr(scene, "frame_current", 1))
        start = int(getattr(scene, "frame_start", 1))
        step_index = math.floor((frame - start) / stepped_frames)

        if definition.get("evolve_mode") == "SEED_STEP":
            # The visible seed property participates in the stream itself. Each
            # held step is hashed independently, avoiding linear increments and
            # any fixed loop length while remaining reproducible after reopening.
            stream_seed += int(round(base)) * 104729
            return int(_fbp_effect_noise_u01(effect_id, stream_seed, step_index) * 1000003.0)

        noise_value = _fbp_effect_noise_u01(effect_id, stream_seed, step_index)
        return base + amount * noise_value
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ZeroDivisionError):
        return value


@persistent
def fbp_effect_evolve_frame_change(scene, depsgraph=None):
    """Refresh only effects that really need per-frame synchronization."""
    del depsgraph
    global _FBP_EVOLVE_HANDLER_ACTIVE
    if _FBP_EVOLVE_HANDLER_ACTIVE or fbp_undo_guard_active():
        return
    render_guard_active = bool(fbp_runtime_get("fbp_render_guard_active", False))
    if (
        render_guard_active
        and not bool(fbp_runtime_get("fbp_render_needs_effect_frame_sync", False))
    ):
        return
    if not render_guard_active and fbp_render_mutation_blocked(include_guard=False):
        # Do not update node trees when an external render is active or Blender
        # cannot confirm its job state. Managed renders are handled above.
        return
    _FBP_EVOLVE_HANDLER_ACTIVE = True
    try:
        try:
            # Resolve only rigs with an active effect stack. The index is rebuilt
            # on structural changes and periodically self-heals external edits.
            rigs = _fbp_scene_effect_runtime_rigs(scene)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return

        _fbp_sync_scene_camera_bindings(scene, rigs)

        for rig in rigs:
            try:
                if not bool(getattr(rig, "is_fbp_control", False)):
                    continue

                # Discover the real effect stack once per rig. The previous
                # implementation rescanned modifiers/materials separately for
                # every alpha-aware and Evolve-capable effect on every frame.
                runtime_profile = _fbp_effect_runtime_profile(rig)
                active_effect_ids = runtime_profile.get("active_ids", frozenset())
                if not active_effect_ids:
                    continue
                geometry_source_sync = bool(runtime_profile.get("geometry_source_sync", False))
                shader_source_sync = (
                    fbp_rig_media_type(rig) in {"IMAGE", "SEQUENCE"}
                    and bool(runtime_profile.get("shader_source_sync", False))
                )
                animated_effect_properties = runtime_profile.get(
                    "animated_effect_properties", {}
                ) or {}
                has_animated_effects = bool(animated_effect_properties)
                evolve_pairs = runtime_profile.get("evolve_pairs", ()) or ()
                evolve_enabled = any(
                    bool(getattr(rig, property_key, False))
                    for _effect_id, property_key in evolve_pairs
                )
                if not (geometry_source_sync or shader_source_sync or has_animated_effects or evolve_enabled):
                    continue

                # Matrix effects follow the evaluated source image/sequence
                # even when no procedural Evolve control is enabled.
                if geometry_source_sync:
                    _fbp_sync_geometry_alpha_frame_offset(
                        rig,
                        scene=scene,
                        effect_modifiers=runtime_profile.get("frame_geometry_modifiers", ()),
                    )
                if shader_source_sync:
                    _fbp_sync_shader_image_sources(
                        rig,
                        active_effect_ids,
                        target_nodes=runtime_profile.get("frame_shader_targets", ()),
                    )

            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                _fbp_invalidate_effect_runtime_profile(rig)
                continue

            # Keyframes on registered Object properties are evaluated by Blender,
            # but socket values are not RNA-linked and update callbacks are not
            # called during animation evaluation. The profile caches only the
            # topology (effect -> property names); evaluated values remain live.
            updated_effect_ids = set()
            for animated_effect_id, animated_properties in animated_effect_properties.items():
                try:
                    if animated_effect_id not in active_effect_ids:
                        continue
                    definition = fbp_effect_definition(animated_effect_id)
                    if definition.get("kind") == "GEOMETRY":
                        fbp_update_geometry_effect(
                            rig,
                            animated_effect_id,
                            modifier=runtime_profile.get("geometry_modifiers", {}).get(animated_effect_id),
                            scene=scene,
                            sync_alpha=False,
                            property_names=animated_properties,
                        )
                    else:
                        fbp_update_shader_effect(
                            rig,
                            animated_effect_id,
                            scene=scene,
                            property_names=animated_properties,
                            nodes=runtime_profile.get("shader_nodes", {}).get(animated_effect_id),
                        )
                    updated_effect_ids.add(animated_effect_id)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    _fbp_invalidate_effect_runtime_profile(rig)
                    continue

            if not evolve_enabled:
                continue

            # Avoid allocating a temporary tuple for every rig on every frame.
            for effect_id, property_key in evolve_pairs:
                try:
                    if not bool(getattr(rig, property_key, False)):
                        continue
                    if effect_id in updated_effect_ids:
                        continue
                    if effect_id not in active_effect_ids:
                        continue
                    definition = fbp_effect_definition(effect_id)
                    evolve_property = str(definition.get("evolve_property", "") or "")
                    property_names = {evolve_property} if evolve_property else None
                    if definition.get("kind") == "GEOMETRY":
                        fbp_update_geometry_effect(
                            rig,
                            effect_id,
                            modifier=runtime_profile.get("geometry_modifiers", {}).get(effect_id),
                            scene=scene,
                            sync_alpha=False,
                            property_names=property_names,
                        )
                    else:
                        fbp_update_shader_effect(
                            rig,
                            effect_id,
                            scene=scene,
                            property_names=property_names,
                            nodes=runtime_profile.get("shader_nodes", {}).get(effect_id),
                        )
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    # A deleted/rebuilt datablock must not abort updates for the
                    # remaining layers during playback or background rendering.
                    # Retire the profile so the next frame resolves fresh targets.
                    _fbp_invalidate_effect_runtime_profile(rig)
                    continue
    finally:
        _FBP_EVOLVE_HANDLER_ACTIVE = False


def _fbp_selected_rigs(context):
    from .layers import get_selected_rigs
    try:
        return list(get_selected_rigs(context) or [])
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return []


def _fbp_plane(rig):
    if not rig:
        return None
    try:
        plane = getattr(rig, "fbp_plane_target", None)
        if plane and getattr(plane, "type", "") == "MESH":
            return plane
    except ReferenceError:
        pass
    return None


def _fbp_node_group_cache_key(node_group):
    """Return a cache key resilient to RNA pointer reuse."""
    if node_group is None:
        return None
    try:
        return (
            int(node_group.as_pointer()),
            str(getattr(node_group, "name_full", getattr(node_group, "name", "")) or ""),
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _fbp_interface_inputs(node_group):
    """Return Geometry Nodes input sockets with a small runtime cache.

    Modifier updates previously walked ``interface.items_tree`` once per property.
    A Text Matrix refresh could therefore rescan the same interface more than a
    dozen times before writing any values. The cache is invalidated whenever the
    interface item count or datablock name changes.
    """
    interface = getattr(node_group, "interface", None) if node_group else None
    if not interface:
        return {}
    try:
        cache_key = _fbp_node_group_cache_key(node_group)
        if cache_key is None:
            return {}
        items = interface.items_tree
        # Keep the hot path O(1). Explicit group rebuild/removal clears this
        # cache; the pointer+name key also prevents aliasing after datablock reuse.
        signature = (len(items),)
        cached = _FBP_INTERFACE_INPUT_CACHE.get(cache_key)
        if cached and cached[0] == signature:
            return cached[1]
        result = {
            str(getattr(item, "name", "") or ""): item
            for item in items
            if getattr(item, "item_type", "") == "SOCKET"
            and getattr(item, "in_out", "") == "INPUT"
        }
        if len(_FBP_INTERFACE_INPUT_CACHE) >= 512 and cache_key not in _FBP_INTERFACE_INPUT_CACHE:
            _FBP_INTERFACE_INPUT_CACHE.clear()
        _FBP_INTERFACE_INPUT_CACHE[cache_key] = (signature, result)
        return result
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return {}


def _fbp_interface_input(node_group, socket_name):
    return _fbp_interface_inputs(node_group).get(str(socket_name or ""))


def _fbp_node_socket(sockets, socket_name, fallback_index=None):
    # Blender nodes often expose several sockets with the same display name
    # (for example both Math operands are named ``Value``).  An explicit
    # index must therefore win over name lookup; otherwise ``sockets.get``
    # silently returns the first socket and later links replace each other.
    if fallback_index is not None:
        try:
            return sockets[fallback_index]
        except (AttributeError, IndexError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    try:
        found = sockets.get(socket_name)
        if found is not None:
            return found
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        for item in sockets:
            if getattr(item, "name", "") == socket_name:
                return item
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _fbp_effect_values_equal(current, value, tolerance=1e-6):
    """Compare socket values without dirtying Blender data for no-op writes."""
    if current is value:
        return True
    try:
        if isinstance(current, (int, float, bool)) and isinstance(value, (int, float, bool)):
            return abs(float(current) - float(value)) <= tolerance
    except (TypeError, ValueError, OverflowError):
        pass
    if not isinstance(current, (str, bytes)) and not isinstance(value, (str, bytes)):
        try:
            current_values = tuple(current)
            value_values = tuple(value)
            if len(current_values) == len(value_values):
                return all(
                    abs(float(a) - float(b)) <= tolerance
                    for a, b in zip(current_values, value_values, strict=True)
                )
        except (TypeError, ValueError, OverflowError):
            pass
    try:
        return bool(current == value)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_set_modifier_input(modifier, node_group, socket_name, value, interface_inputs=None):
    inputs = (
        interface_inputs
        if interface_inputs is not None
        else _fbp_interface_inputs(node_group)
    )
    interface_socket = inputs.get(str(socket_name or ""))
    identifier = getattr(interface_socket, "identifier", "") if interface_socket else ""
    if not identifier:
        return False
    try:
        current = modifier.get(identifier)
        if _fbp_effect_values_equal(current, value):
            return False
        modifier[identifier] = value
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn(f"Could not set effect input {socket_name}", exc)
        return False



def _fbp_scene_camera(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    camera = getattr(scene, "camera", None) if scene else None
    try:
        return camera if camera and getattr(camera, "type", "") == "CAMERA" else None
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _fbp_camera_contract_values(camera, contract):
    """Return standardized active-camera values keyed by declared socket name."""
    values = {}
    object_socket = str(contract.get("object_socket", "Camera") or "Camera")
    if object_socket:
        values[object_socket] = camera
    data = getattr(camera, "data", None) if camera else None
    camera_type = str(getattr(data, "type", "PERSP") or "PERSP") if data else "PERSP"
    bindings = (
        ("lens_socket", float(getattr(data, "lens", 50.0) or 50.0) if data else 50.0),
        ("sensor_width_socket", float(getattr(data, "sensor_width", 36.0) or 36.0) if data else 36.0),
        ("ortho_scale_socket", float(getattr(data, "ortho_scale", 6.0) or 6.0) if data else 6.0),
        ("perspective_socket", 1.0 if camera is not None and camera_type == "PERSP" else 0.0),
        ("shift_x_socket", float(getattr(data, "shift_x", 0.0) or 0.0) if data else 0.0),
        ("shift_y_socket", float(getattr(data, "shift_y", 0.0) or 0.0) if data else 0.0),
    )
    for key, value in bindings:
        socket_name = str(contract.get(key, "") or "")
        if socket_name:
            values[socket_name] = value
    return values


def _fbp_camera_binding_signature(scene):
    camera = _fbp_scene_camera(scene)
    try:
        camera_key = int(camera.as_pointer()) if camera else 0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        camera_key = id(camera) if camera else 0
    data = getattr(camera, "data", None) if camera else None
    try:
        return (
            camera_key,
            str(getattr(data, "type", "") or ""),
            round(float(getattr(data, "lens", 0.0) or 0.0), 6),
            round(float(getattr(data, "sensor_width", 0.0) or 0.0), 6),
            round(float(getattr(data, "ortho_scale", 0.0) or 0.0), 6),
            round(float(getattr(data, "shift_x", 0.0) or 0.0), 6),
            round(float(getattr(data, "shift_y", 0.0) or 0.0), 6),
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return (camera_key,)


def _fbp_bind_geometry_camera_input(rig, effect_id, modifier, node_group=None, scene=None):
    """Bind standardized active-camera inputs without rebuilding the node group."""
    definition = fbp_effect_definition(effect_id)
    if not definition.get("camera_aware") or not modifier:
        return False
    contract = definition.get("camera_contract", {}) or {}
    node_group = node_group or getattr(modifier, "node_group", None)
    if not node_group:
        return False
    interface_inputs = _fbp_interface_inputs(node_group)
    camera = _fbp_scene_camera(scene)
    changed = False
    for socket_name, value in _fbp_camera_contract_values(camera, contract).items():
        changed = _fbp_set_modifier_input(
            modifier, node_group, socket_name, value, interface_inputs
        ) or changed
    return changed


def _fbp_scene_camera_cache_key(scene):
    """Return a Scene cache key that cannot alias a newly-created Scene."""
    try:
        return (
            int(scene.as_pointer()),
            str(getattr(scene, "name_full", getattr(scene, "name", "")) or ""),
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return (0, "")


def _fbp_sync_scene_camera_bindings(scene, rigs):
    """Refresh declared projection values only when the active camera data changes.

    Camera-object transforms remain live through Geometry Nodes Object Info, so
    ordinary camera or layer movement does not require Python socket writes.
    """
    if scene is None:
        return False
    scene_key = _fbp_scene_camera_cache_key(scene)
    if not scene_key[0]:
        return False
    signature = _fbp_camera_binding_signature(scene)
    if _FBP_CAMERA_BINDING_CACHE.get(scene_key) == signature:
        return False
    changed = False
    for rig in rigs or ():
        try:
            for effect_id in _fbp_runtime_effect_ids(rig):
                definition = fbp_effect_definition(effect_id)
                if not definition.get("camera_aware"):
                    continue
                modifier = fbp_find_effect_modifier(rig, effect_id)
                if not modifier:
                    continue
                changed = _fbp_bind_geometry_camera_input(
                    rig, effect_id, modifier, scene=scene
                ) or changed
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    if len(_FBP_CAMERA_BINDING_CACHE) >= 64 and scene_key not in _FBP_CAMERA_BINDING_CACHE:
        _FBP_CAMERA_BINDING_CACHE.clear()
    _FBP_CAMERA_BINDING_CACHE[scene_key] = signature
    return changed


def fbp_sync_scene_camera_bindings(scene=None, *, force=False):
    """Safely refresh camera-aware effect sockets from timer or handler code."""
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return False
    scene_key = _fbp_scene_camera_cache_key(scene)
    if force:
        _FBP_CAMERA_BINDING_CACHE.pop(scene_key, None)
    try:
        from .layers import iter_scene_fbp_rigs
        rigs = iter_scene_fbp_rigs(scene)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        rigs = ()
    return _fbp_sync_scene_camera_bindings(scene, rigs)


def fbp_camera_distance_for_rig(rig, scene=None):
    """Return positive camera-space depth from the active camera to one FBP plane."""
    camera = _fbp_scene_camera(scene)
    target = _fbp_plane(rig) or rig
    if not camera or not target:
        return 0.0
    try:
        camera_location = camera.matrix_world.translation
        target_location = target.matrix_world.translation
        camera_forward = camera.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
        depth = (target_location - camera_location).dot(camera_forward)
        return max(0.0001, float(depth))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0.0


def _fbp_set_enabled(rig, effect_id, enabled):
    definition = fbp_effect_definition(effect_id)
    key = str(definition.get("enabled_key", "") or "")
    if not rig or not key:
        return False
    enabled = bool(enabled)
    try:
        if key in rig and bool(rig.get(key, False)) == enabled:
            return False
        rig[key] = enabled
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_is_enabled(rig, effect_id):
    definition = fbp_effect_definition(effect_id)
    key = str(definition.get("enabled_key", "") or "")
    try:
        return bool(rig and key and rig.get(key, False))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_node_group_asset_id(node_group):
    try:
        return str(node_group.get("fbp_geometry_effect_id", "") or "") if node_group else ""
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ""


def _fbp_group_matches(node_group, effect_id):
    """Match only explicitly tagged Frame by Plane node groups."""
    if not node_group:
        return False
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    asset_id = str(definition.get("asset_id", "") or "")
    if not definition or not asset_id:
        return False
    try:
        tagged_effect = fbp_normalize_effect_id(node_group.get("fbp_effect_id", ""))
        tagged_asset = str(node_group.get("fbp_effect_asset_id", "") or "")
        geometry_asset = _fbp_node_group_asset_id(node_group)
        # Programmatically generated groups must match the exact current asset
        # revision. Reusing a stale generated group can preserve an obsolete
        # socket layout and corrupt the active effect graph.
        if bool(definition.get("builtin", False)):
            return tagged_asset == asset_id or geometry_asset == asset_id
        return tagged_effect == effect_id or tagged_asset == asset_id or geometry_asset == asset_id
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_invalidate_node_group_caches(node_group):
    """Forget cached RNA references before a node-group datablock is removed."""
    if node_group is None:
        return
    try:
        pointer = int(node_group.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pointer = None
    if pointer is not None:
        for cache in (
            _FBP_INTERFACE_INPUT_CACHE,
            _FBP_MATRIX_IMAGE_NODE_CACHE,
            _FBP_CUSTOM_GEOMETRY_SOCKET_CACHE,
        ):
            for key in tuple(cache):
                if isinstance(key, tuple) and key and key[0] == pointer:
                    cache.pop(key, None)
        for key in tuple(_FBP_CUSTOM_SHADER_SOCKET_CACHE):
            if isinstance(key, tuple) and len(key) > 2 and key[2] == pointer:
                _FBP_CUSTOM_SHADER_SOCKET_CACHE.pop(key, None)
    for effect_id, cached in list(_FBP_EFFECT_GROUP_CACHE.items()):
        if cached is node_group:
            _FBP_EFFECT_GROUP_CACHE.pop(effect_id, None)


def _fbp_remove_node_group(node_group):
    _fbp_invalidate_node_group_caches(node_group)
    bpy.data.node_groups.remove(node_group)


def _fbp_cached_effect_group(effect_id, asset_id):
    """Return a live canonical effect group without rescanning bpy.data."""
    cached = _FBP_EFFECT_GROUP_CACHE.get(str(effect_id or ""))
    if cached is None:
        return None
    try:
        name = str(getattr(cached, "name_full", getattr(cached, "name", "")) or "")
        if not name or bpy.data.node_groups.get(name) is not cached:
            raise ReferenceError
        if bool(cached.get("fbp_private_effect_group", False)):
            raise ReferenceError
        if str(cached.get("fbp_effect_asset_id", "") or "") != str(asset_id or ""):
            raise ReferenceError
        return cached
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        _FBP_EFFECT_GROUP_CACHE.pop(str(effect_id or ""), None)
        return None


def _fbp_store_effect_group_cache(effect_id, node_group):
    if node_group is None:
        _FBP_EFFECT_GROUP_CACHE.pop(str(effect_id or ""), None)
        return None
    _FBP_EFFECT_GROUP_CACHE[str(effect_id or "")] = node_group
    return node_group


def _fbp_load_effect_group(effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if not definition:
        return None

    asset_id = str(definition.get("asset_id", "") or "")
    if bool(definition.get("custom", False)):
        if bool(definition.get("custom_invalid", False)):
            return None
        node_group = find_custom_effect_group(effect_id)
        if node_group is None:
            return None
        try:
            node_group.use_fake_user = True
            node_group["fbp_effect_id"] = effect_id
            node_group["fbp_effect_asset_id"] = asset_id
            node_group["fbp_effect_schema_version"] = FBP_EFFECT_SCHEMA_VERSION
            if definition.get("kind") == "GEOMETRY":
                node_group["fbp_geometry_effect_id"] = asset_id
            else:
                node_group["fbp_shader_effect_id"] = asset_id
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return None
        return _fbp_store_effect_group_cache(effect_id, node_group)

    canonical_name = str(definition.get("canonical_name", "") or "")
    source_names = tuple(definition.get("source_names", ()))

    cached = _fbp_cached_effect_group(effect_id, asset_id)
    if cached is not None:
        return cached

    candidates = []
    for node_group in getattr(bpy.data, "node_groups", []):
        try:
            if bool(node_group.get("fbp_private_effect_group", False)):
                continue
            if str(node_group.get("fbp_effect_asset_id", "") or "") != asset_id:
                continue
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
        priority = 0 if getattr(node_group, "name", "") == canonical_name else 1
        candidates.append((priority, node_group))

    if candidates:
        node_group = sorted(candidates, key=lambda item: item[0])[0][1]
        if bool(definition.get("builtin", False)) and not _builtin_group_is_complete(node_group, definition):
            try:
                if int(getattr(node_group, "users", 0) or 0) == 0:
                    _fbp_remove_node_group(node_group)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            node_group = None
        if node_group is not None:
            try:
                node_group.use_fake_user = True
                node_group["fbp_effect_id"] = effect_id
                node_group["fbp_effect_asset_id"] = asset_id
                node_group["fbp_effect_schema_version"] = FBP_EFFECT_SCHEMA_VERSION
                if definition.get("kind") == "GEOMETRY":
                    node_group["fbp_geometry_effect_id"] = asset_id
                else:
                    node_group["fbp_shader_effect_id"] = asset_id
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            return _fbp_store_effect_group_cache(effect_id, node_group)

    if bool(definition.get("builtin", False)):
        try:
            node_group = create_builtin_effect_group(
                effect_id,
                definition,
                Path(__file__).resolve().parent / "assets",
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn(f"Could not build {definition.get('label', effect_id)} effect", exc)
            node_group = None
        if node_group:
            return _fbp_store_effect_group_cache(effect_id, node_group)

    library_path = fbp_geometry_nodes_library_path()
    if not library_path.is_file():
        fbp_warn(f"Effect library not found: {library_path}")
        return None

    loaded = []
    try:
        with bpy.data.libraries.load(str(library_path), link=False) as (data_from, data_to):
            available = set(getattr(data_from, "node_groups", []) or [])
            source_name = next((name for name in source_names if name in available), None)
            if source_name is None:
                raise RuntimeError(
                    f"The bundled .blend does not contain {definition.get('label', effect_id)}"
                )
            data_to.node_groups = [source_name]
            loaded = data_to.node_groups
    except (OSError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn(f"Could not append {definition.get('label', effect_id)}", exc)
        return None

    node_group = loaded[0] if loaded else None
    if not node_group:
        return None
    try:
        if canonical_name:
            node_group.name = canonical_name
        node_group.use_fake_user = True
        node_group["fbp_effect_id"] = effect_id
        node_group["fbp_effect_asset_id"] = asset_id
        node_group["fbp_effect_schema_version"] = FBP_EFFECT_SCHEMA_VERSION
        if definition.get("kind") == "GEOMETRY":
            node_group["fbp_geometry_effect_id"] = asset_id
        else:
            node_group["fbp_shader_effect_id"] = asset_id
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not tag appended effect group", exc)
    return _fbp_store_effect_group_cache(effect_id, node_group)


# ---------------------------------------------------------------------------
# Mesh Wiggle effect loading
# ---------------------------------------------------------------------------


def fbp_load_mesh_wiggle_group():
    return _fbp_load_effect_group(FBP_EFFECT_MESH_WIGGLE)


def fbp_assign_mesh_wiggle_layer_seed(rig, *, force=False):
    if not rig:
        return 0
    try:
        current = int(getattr(rig, "fbp_mesh_wiggle_layer_seed", 0) or 0)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        current = 0
    if force or current <= 0:
        current = int(uuid.uuid4().int % 2147483646) + 1
        fbp_set_rna_property_silent(rig, "fbp_mesh_wiggle_layer_seed", current)
    return current


def fbp_mesh_wiggle_effective_w(rig):
    try:
        phase = float(getattr(rig, "fbp_mesh_wiggle_w", 0.0) or 0.0)
        seed = int(getattr(rig, "fbp_mesh_wiggle_seed", 0) or 0)
        unique = bool(getattr(rig, "fbp_mesh_wiggle_unique_seed", False))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0.0
    value = phase + (float(seed) * 13.731)
    if unique:
        layer_seed = fbp_assign_mesh_wiggle_layer_seed(rig)
        value += float(layer_seed % 1000003) * 0.017
    return value


# ---------------------------------------------------------------------------
# Alpha-aware geometry group copies
# ---------------------------------------------------------------------------


def _fbp_add_interface_socket(node_group, name, socket_type, default, minimum=None, maximum=None):
    existing = _fbp_interface_input(node_group, name)
    if existing is not None:
        return existing
    interface_socket = node_group.interface.new_socket(
        name=name, in_out="INPUT", socket_type=socket_type
    )
    for attr, value in (
        ("default_value", default),
        ("min_value", minimum),
        ("max_value", maximum),
    ):
        if value is None:
            continue
        try:
            setattr(interface_socket, attr, value)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return interface_socket


def _fbp_patch_fuzz_alpha_mask(node_group):
    """Mask only the strand distribution, never the original plane geometry.

    A destructive alpha-mask layout can feed thousands of invisible surfaces
    through the Fuzz graph and make the original image appear to vanish. Keep
    the plane on an untouched output branch and use image alpha only as a
    boolean field for point distribution and opaque-area measurement.
    """
    if not node_group:
        return False

    try:
        if int(node_group.get("fbp_alpha_mask_patch_version", 0) or 0) >= FBP_ALPHA_MASK_PATCH_VERSION:
            return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    _fbp_add_interface_socket(node_group, "Alpha Threshold", "NodeSocketFloat", 0.05, 0.0, 1.0)
    _fbp_add_interface_socket(node_group, "Alpha Resolution", "NodeSocketInt", 2, 0, 6)
    _fbp_add_interface_socket(node_group, "Use Alpha Mask", "NodeSocketBool", True)

    nodes = node_group.nodes
    links = node_group.links
    group_input = next(
        (
            node for node in nodes
            if getattr(node, "bl_idname", "") == "NodeGroupInput"
            and _fbp_node_socket(node.outputs, "Geometry") is not None
        ),
        None,
    )
    distribute = nodes.get("Distribute Fibers")
    area_stats = nodes.get("Total Surface Area")
    if group_input is None or distribute is None or area_stats is None:
        return False

    # Remove only the old geometry links feeding the Fuzz-generation branch.
    # The direct Group Input -> Join Base and Fuzz link remains untouched.
    for target in (
        _fbp_node_socket(distribute.inputs, "Mesh", 0),
        _fbp_node_socket(area_stats.inputs, "Geometry", 0),
        _fbp_node_socket(distribute.inputs, "Selection", 1),
        _fbp_node_socket(area_stats.inputs, "Selection", 1),
    ):
        if target is None:
            continue
        for link in list(target.links):
            links.remove(link)

    subdivide = nodes.new("GeometryNodeSubdivideMesh")
    subdivide.name = "FBP Fuzz Alpha Subdivide"
    subdivide.label = "Fuzz Alpha Detail"
    subdivide.location = (-820, -520)

    named_uv = nodes.new("GeometryNodeInputNamedAttribute")
    named_uv.name = "FBP Fuzz Alpha UV"
    named_uv.label = "UVMap"
    named_uv.location = (-820, -760)
    try:
        named_uv.data_type = "FLOAT_VECTOR"
    except (AttributeError, TypeError, ValueError):
        pass
    uv_name = _fbp_node_socket(named_uv.inputs, "Name")
    if uv_name is not None:
        uv_name.default_value = "UVMap"

    image_texture = nodes.new("GeometryNodeImageTexture")
    image_texture.name = "FBP Alpha Image Texture"
    image_texture.label = "Current FBP Image Alpha"
    image_texture.location = (-560, -720)
    image_texture["fbp_alpha_image_node"] = True
    try:
        image_texture.extension = "EXTEND"
        image_texture.interpolation = "Linear"
    except (AttributeError, TypeError, ValueError):
        pass

    compare = nodes.new("ShaderNodeMath")
    compare.name = "FBP Fuzz Alpha Visible"
    compare.label = "Visible Pixels"
    compare.operation = "GREATER_THAN"
    compare.location = (-300, -680)

    selection_switch = nodes.new("GeometryNodeSwitch")
    selection_switch.name = "FBP Fuzz Use Alpha Mask"
    selection_switch.label = "Use Alpha Mask"
    selection_switch.location = (-50, -620)
    try:
        selection_switch.input_type = "BOOLEAN"
    except (AttributeError, TypeError, ValueError):
        pass
    false_input = _fbp_node_socket(selection_switch.inputs, "False", 1)
    if false_input is not None:
        false_input.default_value = True

    geometry_source = _fbp_node_socket(group_input.outputs, "Geometry")
    resolution_source = _fbp_node_socket(group_input.outputs, "Alpha Resolution")
    threshold_source = _fbp_node_socket(group_input.outputs, "Alpha Threshold")
    use_source = _fbp_node_socket(group_input.outputs, "Use Alpha Mask")

    subdivide_mesh = _fbp_node_socket(subdivide.inputs, "Mesh", 0)
    subdivide_level = _fbp_node_socket(subdivide.inputs, "Level", 1)
    if geometry_source is None or subdivide_mesh is None:
        return False
    links.new(geometry_source, subdivide_mesh)
    if resolution_source is not None and subdivide_level is not None:
        links.new(resolution_source, subdivide_level)

    uv_output = _fbp_node_socket(named_uv.outputs, "Attribute", 0)
    vector_input = _fbp_node_socket(image_texture.inputs, "Vector")
    if uv_output is not None and vector_input is not None:
        links.new(uv_output, vector_input)

    alpha_output = _fbp_node_socket(image_texture.outputs, "Alpha")
    compare_a = _fbp_node_socket(compare.inputs, "Value", 0)
    compare_b = _fbp_node_socket(compare.inputs, "Value", 1)
    if alpha_output is not None and compare_a is not None:
        links.new(alpha_output, compare_a)
    if threshold_source is not None and compare_b is not None:
        links.new(threshold_source, compare_b)

    switch_toggle = _fbp_node_socket(selection_switch.inputs, "Switch", 0)
    switch_true = _fbp_node_socket(selection_switch.inputs, "True", 2)
    if use_source is not None and switch_toggle is not None:
        links.new(use_source, switch_toggle)
    visible_output = _fbp_node_socket(compare.outputs, "Value", 0)
    if visible_output is not None and switch_true is not None:
        links.new(visible_output, switch_true)

    subdivided_geometry = _fbp_node_socket(subdivide.outputs, "Mesh", 0)
    distribute_mesh = _fbp_node_socket(distribute.inputs, "Mesh", 0)
    area_geometry = _fbp_node_socket(area_stats.inputs, "Geometry", 0)
    if subdivided_geometry is not None:
        if distribute_mesh is not None:
            links.new(subdivided_geometry, distribute_mesh)
        if area_geometry is not None:
            links.new(subdivided_geometry, area_geometry)

    selection_output = _fbp_node_socket(selection_switch.outputs, "Output", 0)
    distribute_selection = _fbp_node_socket(distribute.inputs, "Selection", 1)
    area_selection = _fbp_node_socket(area_stats.inputs, "Selection", 1)
    if selection_output is not None:
        if distribute_selection is not None:
            links.new(selection_output, distribute_selection)
        if area_selection is not None:
            links.new(selection_output, area_selection)

    node_group["fbp_alpha_mask_patch_version"] = FBP_ALPHA_MASK_PATCH_VERSION
    return True


def _fbp_patch_alpha_mask(node_group):
    if not node_group:
        return False
    try:
        effect_id = fbp_normalize_effect_id(node_group.get("fbp_effect_id", ""))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        effect_id = ""
    if effect_id == FBP_EFFECT_FELT_FUZZ:
        return _fbp_patch_fuzz_alpha_mask(node_group)
    try:
        if int(node_group.get("fbp_alpha_mask_patch_version", 0) or 0) >= FBP_ALPHA_MASK_PATCH_VERSION:
            return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    _fbp_add_interface_socket(node_group, "Alpha Threshold", "NodeSocketFloat", 0.05, 0.0, 1.0)
    _fbp_add_interface_socket(
        node_group,
        "Alpha Resolution",
        "NodeSocketInt",
        2 if fbp_normalize_effect_id(node_group.get("fbp_effect_id", "")) == FBP_EFFECT_FELT_FUZZ else 4,
        0,
        6,
    )
    _fbp_add_interface_socket(node_group, "Use Alpha Mask", "NodeSocketBool", True)

    group_inputs = [
        node for node in node_group.nodes
        if getattr(node, "bl_idname", "") == "NodeGroupInput"
        and _fbp_node_socket(node.outputs, "Geometry") is not None
    ]
    if not group_inputs:
        return False

    outgoing_targets = []
    for input_node in group_inputs:
        geometry_output = _fbp_node_socket(input_node.outputs, "Geometry")
        for link in list(node_group.links):
            if link.from_socket != geometry_output:
                continue
            target_node = getattr(link, "to_node", None)
            try:
                preserve_original = bool(
                    target_node and target_node.get("fbp_preserve_unmasked_geometry", False)
                )
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                preserve_original = False
            if preserve_original:
                continue
            outgoing_targets.append(link.to_socket)
            node_group.links.remove(link)
    if not outgoing_targets:
        return False

    primary = group_inputs[0]
    nodes = node_group.nodes
    links = node_group.links

    subdivide = nodes.new("GeometryNodeSubdivideMesh")
    subdivide.name = "FBP Alpha Subdivide"
    subdivide.label = "Alpha Mask Resolution"
    subdivide.location = (-780, -520)

    named_uv = nodes.new("GeometryNodeInputNamedAttribute")
    named_uv.name = "FBP Alpha UV"
    named_uv.label = "UVMap"
    named_uv.location = (-780, -760)
    try:
        named_uv.data_type = "FLOAT_VECTOR"
    except (AttributeError, TypeError, ValueError):
        pass
    name_input = _fbp_node_socket(named_uv.inputs, "Name")
    if name_input:
        name_input.default_value = "UVMap"

    image_texture = nodes.new("GeometryNodeImageTexture")
    image_texture.name = "FBP Alpha Image Texture"
    image_texture.label = "Current FBP Image Alpha"
    image_texture.location = (-520, -720)
    image_texture["fbp_alpha_image_node"] = True
    try:
        image_texture.extension = "EXTEND"
        image_texture.interpolation = "Linear"
    except (AttributeError, TypeError, ValueError):
        pass

    compare = nodes.new("ShaderNodeMath")
    compare.name = "FBP Alpha Below Threshold"
    compare.label = "Transparent Pixels"
    compare.operation = "LESS_THAN"
    compare.location = (-260, -660)

    use_mask = nodes.new("FunctionNodeBooleanMath")
    use_mask.name = "FBP Use Alpha Mask"
    use_mask.label = "Use Alpha Mask"
    use_mask.operation = "AND"
    use_mask.location = (-40, -600)

    delete_geometry = nodes.new("GeometryNodeDeleteGeometry")
    delete_geometry.name = "FBP Delete Transparent Geometry"
    delete_geometry.label = "Delete Transparent Pixels"
    delete_geometry.location = (180, -500)
    try:
        delete_geometry.domain = "FACE"
    except (AttributeError, TypeError, ValueError):
        pass

    geometry_source = _fbp_node_socket(primary.outputs, "Geometry")
    resolution_source = _fbp_node_socket(primary.outputs, "Alpha Resolution")
    threshold_source = _fbp_node_socket(primary.outputs, "Alpha Threshold")
    use_source = _fbp_node_socket(primary.outputs, "Use Alpha Mask")

    links.new(geometry_source, _fbp_node_socket(subdivide.inputs, "Mesh", 0))
    if resolution_source:
        links.new(resolution_source, _fbp_node_socket(subdivide.inputs, "Level", 1))

    attribute_output = _fbp_node_socket(named_uv.outputs, "Attribute", 0)
    vector_input = _fbp_node_socket(image_texture.inputs, "Vector")
    if attribute_output and vector_input:
        links.new(attribute_output, vector_input)

    alpha_output = _fbp_node_socket(image_texture.outputs, "Alpha")
    if alpha_output:
        links.new(alpha_output, _fbp_node_socket(compare.inputs, "Value", 0))
    if threshold_source:
        links.new(threshold_source, _fbp_node_socket(compare.inputs, "Value", 1))
    links.new(_fbp_node_socket(compare.outputs, "Value", 0), _fbp_node_socket(use_mask.inputs, "Boolean", 0))
    if use_source:
        links.new(use_source, _fbp_node_socket(use_mask.inputs, "Boolean", 1))

    links.new(_fbp_node_socket(subdivide.outputs, "Mesh", 0), _fbp_node_socket(delete_geometry.inputs, "Geometry", 0))
    links.new(_fbp_node_socket(use_mask.outputs, "Boolean", 0), _fbp_node_socket(delete_geometry.inputs, "Selection", 1))
    masked_output = _fbp_node_socket(delete_geometry.outputs, "Geometry", 0)
    for target in outgoing_targets:
        links.new(masked_output, target)

    node_group["fbp_alpha_mask_patch_version"] = FBP_ALPHA_MASK_PATCH_VERSION
    return True


def _fbp_material_image_node(rig):
    plane = _fbp_plane(rig)
    if not plane or not getattr(plane, "data", None):
        return None, None
    try:
        materials = [mat for mat in plane.data.materials if mat and getattr(mat, "use_nodes", False)]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        materials = []
    for material in materials:
        node_tree = getattr(material, "node_tree", None)
        if not node_tree:
            continue
        for preferred_name in ("FBP_Native_Media_Texture", "FBP_AlphaHoldout_Texture"):
            preferred = node_tree.nodes.get(preferred_name)
            if preferred and getattr(preferred, "type", "") == "TEX_IMAGE" and getattr(preferred, "image", None):
                return material, preferred
        for node in node_tree.nodes:
            try:
                is_owned = bool(node.get("fbp_native_sequence_node", False)) or bool(
                    node.get("fbp_holdout_image_node", False)
                )
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                is_owned = False
            if is_owned and getattr(node, "type", "") == "TEX_IMAGE" and getattr(node, "image", None):
                return material, node
    return None, None


def _fbp_geometry_image_frame(src_user, scene_frame):
    """Return the 1-based sequence frame expected by Geometry Image Texture.

    Shader Image Texture timing is expressed as timeline frame plus
    ``ImageUser.frame_offset``. Geometry Nodes uses an explicit 1-based Frame
    input, so omitting the final +1 evaluates the first source frame as frame
    zero and returns transparent alpha.
    """
    if src_user is None:
        return 1
    try:
        return int(
            int(scene_frame)
            - int(getattr(src_user, "frame_start", 1) or 1)
            + int(getattr(src_user, "frame_offset", 0) or 0)
            + 1
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 1


def _fbp_copy_image_user(src_owner, src_node, dst_owner, dst_node):
    """Initialize direct Geometry Image Texture timing from the material ImageUser.

    Geometry Nodes exposes an integer Frame input instead of an ImageUser.
    Frame by Plane updates that input from the frame-change handler; nested RNA
    drivers are removed once and are not rescanned on every material refresh.
    """
    del src_owner
    src_user = getattr(src_node, "image_user", None)
    frame_input = _fbp_node_socket(getattr(dst_node, "inputs", ()), "Frame")
    if src_user is None or frame_input is None:
        return False

    initialized = False
    try:
        initialized = bool(dst_owner.get("fbp_alpha_frame_direct", False))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    if not initialized:
        try:
            dst_path = frame_input.path_from_id("default_value")
            animation_data = getattr(dst_owner, "animation_data", None)
            if animation_data:
                for curve in list(getattr(animation_data, "drivers", ()) or ()):
                    if curve.data_path == dst_path:
                        dst_owner.driver_remove(dst_path)
                        break
                fbp_remove_action_fcurves(dst_owner, dst_path)
            dst_owner["fbp_alpha_frame_direct"] = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    try:
        current_frame = int(getattr(getattr(bpy.context, "scene", None), "frame_current", 1))
        value = _fbp_geometry_image_frame(src_user, current_frame)
        if int(getattr(frame_input, "default_value", 0) or 0) == value:
            return False
        frame_input.default_value = value
        dst_owner.update_tag()
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_alpha_image_node(node_group):
    if not node_group:
        return None
    try:
        for name in ("FBP Alpha Image Texture", "Text Matrix Source Image"):
            node = node_group.nodes.get(name)
            if node and bool(node.get("fbp_alpha_image_node", False)):
                return node
        for node in node_group.nodes:
            if bool(node.get("fbp_alpha_image_node", False)):
                return node
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _fbp_sync_geometry_alpha(rig, modifier):
    node_group = getattr(modifier, "node_group", None) if modifier else None
    if not node_group:
        return False
    image_node = _fbp_alpha_image_node(node_group)
    if not image_node:
        return False
    interface_inputs = _fbp_interface_inputs(node_group)
    source_material, source_node = _fbp_material_image_node(rig)
    source_image = getattr(source_node, "image", None) if source_node else None
    has_image = bool(source_image)
    changed = False
    try:
        image_input = _fbp_node_socket(image_node.inputs, "Image")
        if image_input is not None:
            if getattr(image_input, "default_value", None) is not source_image:
                image_input.default_value = source_image
                changed = True
        elif hasattr(image_node, "image") and getattr(image_node, "image", None) is not source_image:
            image_node.image = source_image
            changed = True
        if has_image:
            try:
                is_text_matrix = bool(image_node.get("fbp_text_matrix_image_node", False))
                interpolation = (
                    "Closest"
                    if is_text_matrix
                    else getattr(source_node, "interpolation", image_node.interpolation)
                )
                extension = (
                    "EXTEND"
                    if is_text_matrix
                    else getattr(source_node, "extension", image_node.extension)
                )
                if getattr(image_node, "interpolation", None) != interpolation:
                    image_node.interpolation = interpolation
                    changed = True
                if getattr(image_node, "extension", None) != extension:
                    image_node.extension = extension
                    changed = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            changed = _fbp_copy_image_user(
                source_material.node_tree, source_node, node_group, image_node
            ) or changed
        if "Use Alpha Mask" in interface_inputs:
            changed = _fbp_set_modifier_input(
                modifier, node_group, "Use Alpha Mask", has_image, interface_inputs
            ) or changed
        if changed:
            try:
                node_group.update_tag()
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        return changed
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not synchronize geometry alpha image", exc)
        if "Use Alpha Mask" in interface_inputs:
            return _fbp_set_modifier_input(
                modifier, node_group, "Use Alpha Mask", False, interface_inputs
            )
        return False


def _fbp_sync_geometry_alpha_frame_offset(rig, scene=None, effect_modifiers=None):
    """Keep image-aware Geometry Nodes bound to the current FBP source.

    Besides sequence timing, this also refreshes the image datablock itself.
    Text Matrix therefore follows material/image replacements and every frame of
    native image sequences instead of retaining the image that was active when
    the modifier was first created.
    """
    plane = _fbp_plane(rig)
    if not plane:
        return False

    _source_material, source_node = _fbp_material_image_node(rig)
    try:
        source_image = getattr(source_node, "image", None) if source_node else None
        source_kind = str(getattr(source_image, "source", "") or "")
        src_user = getattr(source_node, "image_user", None) if source_node else None
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        source_image = None
        source_kind = ""
        src_user = None

    if effect_modifiers is None:
        resolved_modifiers = []
        try:
            for modifier in plane.modifiers:
                if getattr(modifier, "type", "") != "NODES":
                    continue
                try:
                    tagged = fbp_normalize_effect_id(modifier.get("fbp_effect_id", ""))
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    tagged = ""
                if tagged in FBP_FRAME_SYNC_GEOMETRY_EFFECT_IDS:
                    resolved_modifiers.append(modifier)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False
    else:
        resolved_modifiers = list(effect_modifiers or ())
    if not resolved_modifiers:
        return False

    scene = scene or getattr(bpy.context, "scene", None)
    scene_frame = int(getattr(scene, "frame_current", 1))
    sequence_frame = (
        _fbp_geometry_image_frame(src_user, scene_frame)
        if source_kind in {"SEQUENCE", "MOVIE"} and src_user is not None
        else 1
    )
    synced = False
    plane_changed = False

    for modifier in resolved_modifiers:
        node_group = getattr(modifier, "node_group", None)
        image_node = _fbp_alpha_image_node(node_group) if node_group else None
        if image_node is None:
            continue
        interface_inputs = _fbp_interface_inputs(node_group)
        changed = False
        try:
            image_input = _fbp_node_socket(getattr(image_node, "inputs", ()), "Image")
            if image_input is not None:
                if getattr(image_input, "default_value", None) is not source_image:
                    image_input.default_value = source_image
                    changed = True
            elif hasattr(image_node, "image") and getattr(image_node, "image", None) is not source_image:
                image_node.image = source_image
                changed = True

            is_text_matrix = bool(image_node.get("fbp_text_matrix_image_node", False))
            if source_node is not None:
                interpolation = "Closest" if is_text_matrix else getattr(source_node, "interpolation", None)
                extension = "EXTEND" if is_text_matrix else getattr(source_node, "extension", None)
                if interpolation is not None and getattr(image_node, "interpolation", None) != interpolation:
                    image_node.interpolation = interpolation
                    changed = True
                if extension is not None and getattr(image_node, "extension", None) != extension:
                    image_node.extension = extension
                    changed = True

            frame_input = _fbp_node_socket(getattr(image_node, "inputs", ()), "Frame")
            if frame_input is not None and int(getattr(frame_input, "default_value", 0) or 0) != sequence_frame:
                frame_input.default_value = sequence_frame
                changed = True

            if "Use Alpha Mask" in interface_inputs:
                changed = _fbp_set_modifier_input(
                    modifier,
                    node_group,
                    "Use Alpha Mask",
                    bool(source_image),
                    interface_inputs,
                ) or changed

            if changed:
                node_group.update_tag()
                plane_changed = True
            synced = bool(source_image) or synced or changed
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    if plane_changed:
        try:
            plane.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return synced

def _fbp_owned_geometry_group(rig, effect_id, source_group, current=None):
    plane = _fbp_plane(rig)
    if not plane or not source_group:
        return None
    if current:
        try:
            owns_current = (
                fbp_normalize_effect_id(current.get("fbp_effect_id", ""))
                == fbp_normalize_effect_id(effect_id)
                and current.get("fbp_effect_owner", "") == plane.name
                and str(current.get("fbp_effect_asset_id", "") or "")
                == str(fbp_effect_definition(effect_id).get("asset_id", "") or "")
            )
            if owns_current:
                # Private groups preserve per-plane images, fonts and frame timing.
                # Only alpha-aware effects need the destructive alpha-mask patch.
                if not bool(fbp_effect_definition(effect_id).get("alpha_aware")):
                    return current
                if _fbp_patch_alpha_mask(current):
                    return current
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    try:
        node_group = source_group.copy()
        node_group.name = f"{source_group.name} • {plane.name}"
        node_group.use_fake_user = False
        node_group["fbp_effect_id"] = effect_id
        node_group["fbp_effect_asset_id"] = str(fbp_effect_definition(effect_id).get("asset_id", "") or "")
        node_group["fbp_effect_schema_version"] = FBP_EFFECT_SCHEMA_VERSION
        node_group["fbp_effect_owner"] = plane.name
        node_group["fbp_private_effect_group"] = True
        if bool(fbp_effect_definition(effect_id).get("alpha_aware")):
            if not _fbp_patch_alpha_mask(node_group):
                _fbp_remove_node_group(node_group)
                return None
        return node_group
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not create alpha-aware effect group", exc)
        return None


def _fbp_find_owned_effect_material(rig, effect_id, label=""):
    plane = _fbp_plane(rig)
    owner = str(getattr(plane, "name", "") or "")
    effect_id = fbp_normalize_effect_id(effect_id)
    role = str(label or "")

    # Current materials use a deterministic name. Resolve that directly before
    # falling back to a global scan, which is costly during animated effects.
    if role and owner:
        try:
            candidate = bpy.data.materials.get(f"FBP {role} • {owner}")
            if (
                candidate
                and candidate.get("fbp_effect_material_owner", "") == owner
                and fbp_normalize_effect_id(candidate.get("fbp_effect_material_id", "")) == effect_id
            ):
                return candidate
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    for material in bpy.data.materials:
        try:
            if (
                material.get("fbp_effect_material_owner", "") == owner
                and fbp_normalize_effect_id(material.get("fbp_effect_material_id", "")) == effect_id
                and (not role or str(material.get("fbp_effect_material_role", "") or "") == role)
            ):
                return material
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return None


def _fbp_ensure_owned_effect_material(rig, effect_id, label, color):
    """Create one lightweight solid material owned by an effect on one plane."""
    plane = _fbp_plane(rig)
    if not plane:
        return None
    owner = str(getattr(plane, "name", "") or "")
    effect_id = fbp_normalize_effect_id(effect_id)
    material = _fbp_find_owned_effect_material(rig, effect_id, label)
    if material is None:
        try:
            material = bpy.data.materials.new(name=f"FBP {label} • {owner}")
            material.use_nodes = True
            material.use_fake_user = False
            material["fbp_owned"] = True
            material["fbp_effect_material_owner"] = owner
            material["fbp_effect_material_id"] = effect_id
            material["fbp_effect_material_role"] = str(label or "")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn(f"Could not create {label} material", exc)
            return None

    try:
        color = tuple(color)
        if not _fbp_effect_values_equal(getattr(material, "diffuse_color", ()), color):
            material.diffuse_color = color
        node_tree = material.node_tree
        if not node_tree:
            material.use_nodes = True
            node_tree = material.node_tree
        nodes = node_tree.nodes
        links = node_tree.links
        principled = next(
            (node for node in nodes if getattr(node, "type", "") == "BSDF_PRINCIPLED"),
            None,
        )
        output = next(
            (node for node in nodes if getattr(node, "type", "") == "OUTPUT_MATERIAL"),
            None,
        )
        if principled is None:
            principled = nodes.new("ShaderNodeBsdfPrincipled")
            principled.name = "FBP Effect Material"
        if output is None:
            output = nodes.new("ShaderNodeOutputMaterial")
        base_color = _fbp_node_socket(principled.inputs, "Base Color")
        roughness = _fbp_node_socket(principled.inputs, "Roughness")
        metallic = _fbp_node_socket(principled.inputs, "Metallic")
        if base_color is not None and not _fbp_effect_values_equal(base_color.default_value, color):
            base_color.default_value = color
        if roughness is not None and not _fbp_effect_values_equal(roughness.default_value, 0.8):
            roughness.default_value = 0.8
        if metallic is not None and not _fbp_effect_values_equal(metallic.default_value, 0.0):
            metallic.default_value = 0.0
        surface = _fbp_node_socket(output.inputs, "Surface")
        bsdf = _fbp_node_socket(principled.outputs, "BSDF")
        if surface is not None and bsdf is not None:
            linked = (
                len(surface.links) == 1
                and surface.links[0].from_socket == bsdf
            )
            if not linked:
                for link in list(surface.links):
                    links.remove(link)
                links.new(bsdf, surface)
        if material.get("fbp_effect_material_owner", "") != owner:
            material["fbp_effect_material_owner"] = owner
        if fbp_normalize_effect_id(material.get("fbp_effect_material_id", "")) != effect_id:
            material["fbp_effect_material_id"] = effect_id
        role = str(label or "")
        if str(material.get("fbp_effect_material_role", "") or "") != role:
            material["fbp_effect_material_role"] = role
        for attr, value in (
            ("surface_render_method", "DITHERED"),
            ("show_transparent_back", False),
        ):
            if hasattr(material, attr):
                try:
                    if getattr(material, attr) != value:
                        setattr(material, attr, value)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn(f"Could not update {label} material", exc)
    return material


def _fbp_ensure_text_matrix_material(rig, color):
    """Return one lightweight per-cell-color material for Text Matrix.

    Geometry Nodes stores ``fbp_text_matrix_color`` on the instancing points.
    The shader reads it from the instancer while glyphs remain instances, and
    from geometry after Realize Instances transfers the attribute to the mesh.
    Emission preserves sampled RGB without one material per glyph or light tint.
    """
    plane = _fbp_plane(rig)
    if not plane:
        return None
    owner = str(getattr(plane, "name", "") or "")
    role = "Text Matrix Text"
    material = _fbp_find_owned_effect_material(rig, FBP_EFFECT_TEXT_MATRIX, role)
    if material is None:
        try:
            material = bpy.data.materials.new(name=f"FBP {role} • {owner}")
            material.use_nodes = True
            material.use_fake_user = False
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not create Text Matrix material", exc)
            return None

    try:
        color = tuple(color)
        material.diffuse_color = color
        material["fbp_owned"] = True
        material["fbp_effect_material_owner"] = owner
        material["fbp_effect_material_id"] = FBP_EFFECT_TEXT_MATRIX
        material["fbp_effect_material_role"] = role
        material["fbp_text_matrix_color_attribute"] = "fbp_text_matrix_color"

        if not bool(getattr(material, "use_nodes", False)):
            material.use_nodes = True
        node_tree = material.node_tree
        nodes = node_tree.nodes
        links = node_tree.links
        structure_version = int(material.get("fbp_text_matrix_material_version", 0) or 0)
        attribute = nodes.get("FBP Text Matrix Color")
        emission = nodes.get("FBP Text Matrix Emission")
        output = nodes.get("FBP Text Matrix Output")
        color_linked = bool(
            attribute is not None
            and emission is not None
            and any(link.from_node == attribute and link.to_node == emission for link in links)
        )
        surface_linked = bool(
            emission is not None
            and output is not None
            and any(link.from_node == emission and link.to_node == output for link in links)
        )
        if (
            structure_version != 3
            or attribute is None
            or emission is None
            or output is None
            or not color_linked
            or not surface_linked
        ):
            nodes.clear()
            attribute = nodes.new("ShaderNodeAttribute")
            attribute.name = "FBP Text Matrix Color"
            attribute.label = "Per-cell Source Color"
            emission = nodes.new("ShaderNodeEmission")
            emission.name = "FBP Text Matrix Emission"
            emission.label = "Unlit Glyph Color"
            output = nodes.new("ShaderNodeOutputMaterial")
            output.name = "FBP Text Matrix Output"
            attribute.location = (-420.0, 40.0)
            emission.location = (-160.0, 40.0)
            output.location = (100.0, 40.0)
            links.new(attribute.outputs["Color"], emission.inputs["Color"])
            links.new(emission.outputs["Emission"], output.inputs["Surface"])
            material["fbp_text_matrix_material_version"] = 3

        attribute.attribute_name = "fbp_text_matrix_color"
        attribute_type = (
            "GEOMETRY"
            if bool(getattr(rig, "fbp_text_matrix_realize", False))
            else "INSTANCER"
        )
        material["fbp_text_matrix_attribute_type"] = attribute_type
        if hasattr(attribute, "attribute_type"):
            try:
                attribute.attribute_type = attribute_type
            except (AttributeError, TypeError, ValueError):
                pass
        color_input = _fbp_node_socket(emission.inputs, "Color")
        strength_input = _fbp_node_socket(emission.inputs, "Strength")
        if color_input is not None:
            color_input.default_value = color
        if strength_input is not None:
            strength_input.default_value = 1.0
        for attr, value in (
            ("surface_render_method", "DITHERED"),
            ("show_transparent_back", False),
        ):
            if hasattr(material, attr):
                try:
                    setattr(material, attr, value)
                except (AttributeError, TypeError, ValueError):
                    pass
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not configure Text Matrix source-color material", exc)
    return material


def _fbp_material_is_owned(material):
    try:
        return bool(material and material.get("fbp_owned", False))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_plane_source_material(rig):
    """Return the exact FBP-owned material evaluated by the animated mesh."""
    plane = _fbp_plane(rig)
    mesh = getattr(plane, "data", None) if plane else None
    materials = getattr(mesh, "materials", None) if mesh else None
    if not materials:
        return None

    try:
        if mesh.polygons:
            index = int(getattr(mesh.polygons[0], "material_index", 0) or 0)
            if 0 <= index < len(materials):
                material = materials[index]
                if _fbp_material_is_owned(material):
                    return material
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        pass

    try:
        for material in materials:
            if _fbp_material_is_owned(material):
                return material
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _fbp_cleanup_owned_effect_materials(rig, effect_id):
    plane = _fbp_plane(rig)
    owner = str(getattr(plane, "name", "") or "")
    effect_id = fbp_normalize_effect_id(effect_id)
    for material in list(bpy.data.materials):
        try:
            if (
                material.get("fbp_effect_material_owner", "") == owner
                and fbp_normalize_effect_id(material.get("fbp_effect_material_id", "")) == effect_id
                and material.users == 0
            ):
                bpy.data.materials.remove(material)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass


# ---------------------------------------------------------------------------
# Geometry effect modifiers
# ---------------------------------------------------------------------------


def fbp_find_effect_modifier(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") != "GEOMETRY":
        return None
    plane = _fbp_plane(rig)
    if not plane:
        return None
    try:
        for modifier in plane.modifiers:
            if getattr(modifier, "type", "") != "NODES":
                continue
            tagged = fbp_normalize_effect_id(modifier.get("fbp_effect_id", ""))
            if tagged == effect_id or _fbp_group_matches(getattr(modifier, "node_group", None), effect_id):
                return modifier
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _fbp_find_all_effect_modifiers(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    plane = _fbp_plane(rig)
    if not plane or definition.get("kind") != "GEOMETRY":
        return []
    result = []
    try:
        for modifier in plane.modifiers:
            if getattr(modifier, "type", "") != "NODES":
                continue
            tagged = fbp_normalize_effect_id(modifier.get("fbp_effect_id", ""))
            if tagged == effect_id or _fbp_group_matches(getattr(modifier, "node_group", None), effect_id):
                result.append(modifier)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return []
    return result


def _fbp_remove_duplicate_effect_modifiers(rig, effect_id, keep):
    plane = _fbp_plane(rig)
    if not plane:
        return
    for modifier in _fbp_find_all_effect_modifiers(rig, effect_id):
        if modifier == keep:
            continue
        node_group = getattr(modifier, "node_group", None)
        try:
            plane.modifiers.remove(modifier)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
        try:
            if node_group and bool(node_group.get("fbp_private_effect_group", False)) and node_group.users == 0:
                _fbp_remove_node_group(node_group)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass


def _fbp_cast_effect_value(prop_name, value):
    enum_values = {
        "fbp_wind_pin_edge": {"LEFT": 0.0, "RIGHT": 1.0, "BOTTOM": 2.0, "TOP": 3.0},
        "fbp_wind_motion_mode": {"SWAY": 0.0, "FLOW": 1.0},
        "fbp_wind_direction_space": {"LOCAL": 0.0, "WORLD": 1.0},
        "fbp_halftone_shape": {"CIRCLE": 0.0, "SQUARE": 1.0, "DIAMOND": 2.0, "LINE": 3.0},
        "fbp_dot_matrix_shape": {"CIRCLE": 0.0, "SQUARE": 1.0, "DIAMOND": 2.0, "LINE": 3.0},
        "fbp_mesh_ripple_direction": {"X": 0.0, "Y": 1.0, "RADIAL": 2.0},
        "fbp_paper_curl_edge": {"LEFT": 0.0, "RIGHT": 1.0, "BOTTOM": 2.0, "TOP": 3.0},
        "fbp_camera_billboard_mode": {"FULL": 0.0, "HORIZONTAL": 1.0, "VERTICAL": 2.0},
    }
    if prop_name in enum_values:
        return enum_values[prop_name].get(str(value), 0.0)
    if isinstance(value, bool):
        return bool(value)
    if prop_name.endswith(("subdivisions", "subdivision", "resolution")) or prop_name in {
        "fbp_felt_render_density",
        "fbp_mesh_wiggle_hold",
        "fbp_stop_motion_step_frames",
        "fbp_wind_stepped",
        "fbp_infinite_rotation_stepped",
        "fbp_thickness_alpha_resolution",
        "fbp_felt_seed",
        "fbp_felt_alpha_resolution",
        "fbp_text_matrix_viewport_columns",
        "fbp_text_matrix_viewport_rows",
        "fbp_text_matrix_render_columns",
        "fbp_text_matrix_render_rows",
        "fbp_text_matrix_playback_columns",
        "fbp_text_matrix_playback_rows",
        "fbp_text_matrix_character_count",
        "fbp_mesh_ripple_viewport_subdivision",
        "fbp_mesh_ripple_playback_subdivision",
        "fbp_mesh_ripple_render_subdivision",
        "fbp_mesh_ripple_stepped",
        "fbp_paper_curl_viewport_subdivision",
        "fbp_paper_curl_playback_subdivision",
        "fbp_paper_curl_render_subdivision",
        "fbp_cutout_outline_viewport_resolution",
        "fbp_cutout_outline_playback_resolution",
        "fbp_cutout_outline_render_resolution",
    }:
        return int(value)
    if prop_name.endswith("shade_smooth"):
        return bool(value)
    if isinstance(value, (tuple, list)):
        return tuple(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _fbp_ensure_geometry_effect_group(rig, effect_id, modifier):
    """Restore a missing/outdated effect group without replacing the modifier."""
    if not rig or not modifier:
        return None
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    current = getattr(modifier, "node_group", None)
    if current and _fbp_group_matches(current, effect_id):
        if not (definition.get("alpha_aware") or definition.get("private_group")):
            return current
        owned = _fbp_owned_geometry_group(rig, effect_id, current, current)
        if owned:
            return owned

    source = (
        fbp_load_mesh_wiggle_group()
        if effect_id == FBP_EFFECT_MESH_WIGGLE
        else _fbp_load_effect_group(effect_id)
    )
    if not source:
        return None
    target = source
    if definition.get("alpha_aware") or definition.get("private_group"):
        target = _fbp_owned_geometry_group(rig, effect_id, source, current)
    if not target:
        return None

    try:
        modifier.node_group = target
        modifier["fbp_effect_id"] = effect_id
        ensure_effect_instance_id(modifier, effect_id)
        modifier.name = str(
            definition.get("modifier_name", definition.get("label", effect_id))
        )
        visible = _fbp_stored_effect_visibility(rig, effect_id, True)
        render_visible = _fbp_stored_effect_render_visibility(rig, effect_id, True)
        modifier.show_viewport = visible
        modifier.show_render = render_visible
        if current and current != target:
            try:
                if bool(current.get("fbp_private_effect_group", False)) and current.users == 0:
                    _fbp_remove_node_group(current)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        return target
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn(f"Could not restore {definition.get('label', effect_id)} asset", exc)
        return None



def _fbp_default_vector_font():
    """Return Blender's built-in vector font without rescanning on every edit."""
    global _FBP_DEFAULT_FONT_CACHE
    cached = _FBP_DEFAULT_FONT_CACHE
    if cached is not None:
        try:
            name = str(getattr(cached, "name_full", getattr(cached, "name", "")) or "")
            if name and bpy.data.fonts.get(name) is cached:
                return cached
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        _FBP_DEFAULT_FONT_CACHE = None
    try:
        for font in bpy.data.fonts:
            if str(getattr(font, "name", "")).startswith("Bfont"):
                _FBP_DEFAULT_FONT_CACHE = font
                return font
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    curve = None
    try:
        curve = bpy.data.curves.new("FBP_Default_Font_Loader", type="FONT")
        font = getattr(curve, "font", None)
        _FBP_DEFAULT_FONT_CACHE = font
        return font
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None
    finally:
        if curve is not None:
            try:
                bpy.data.curves.remove(curve)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass

def _fbp_update_text_matrix_charset(node_group, rig):
    if not node_group or not rig:
        return False
    preset = str(getattr(rig, "fbp_text_matrix_charset", "CLASSIC") or "CLASSIC")
    custom = str(getattr(rig, "fbp_text_matrix_custom_charset", "") or "")
    count = max(2, min(ASCII_TEXT_GLYPH_LIMIT, int(getattr(rig, "fbp_text_matrix_character_count", ASCII_TEXT_GLYPH_LIMIT) or ASCII_TEXT_GLYPH_LIMIT)))
    chars = ascii_level_gradient(preset, levels=count, custom=custom)
    # The group always contains sixteen branches; repeat the densest glyph for
    # unused slots so changing Character Count cannot expose stale characters.
    chars = (chars + chars[-1] * ASCII_TEXT_GLYPH_LIMIT)[:ASCII_TEXT_GLYPH_LIMIT]
    signature = f"{preset}|{count}|{custom}|{chars}"
    try:
        if str(node_group.get("fbp_text_matrix_charset_signature", "") or "") == signature:
            return False
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    changed = False
    for node in getattr(node_group, "nodes", ()):
        try:
            glyph_index = int(node.get("fbp_text_matrix_glyph_index", -1))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
        if glyph_index < 0 or glyph_index >= len(chars):
            continue
        socket = _fbp_node_socket(getattr(node, "inputs", ()), "String")
        if socket is None or str(getattr(socket, "default_value", "")) == chars[glyph_index]:
            continue
        try:
            socket.default_value = chars[glyph_index]
            changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    try:
        node_group["fbp_text_matrix_charset_signature"] = signature
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return changed


def fbp_update_geometry_effect(
    rig,
    effect_id,
    modifier=None,
    scene=None,
    *,
    sync_alpha=True,
    property_names=None,
):
    """Push effect values into one Geometry Nodes modifier.

    ``property_names`` limits interactive RNA callbacks to the sockets that
    actually changed. Full updates are still used after asset repair, file load,
    frame evaluation and explicit stack rebuilds.
    """
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") != "GEOMETRY" or not rig:
        return False
    modifier = modifier or fbp_find_effect_modifier(rig, effect_id)
    if not modifier:
        return False
    previous_group = getattr(modifier, "node_group", None)
    node_group = _fbp_ensure_geometry_effect_group(rig, effect_id, modifier)
    if not node_group:
        return False

    requested = None if property_names is None else {
        str(name) for name in property_names if str(name or "")
    }
    # Mesh Wiggle folds its Seed and Unique Seed controls into the effective W
    # socket. A property-scoped update must therefore refresh W as a dependency.
    if effect_id == FBP_EFFECT_MESH_WIGGLE and requested is not None:
        if requested & {"fbp_mesh_wiggle_seed", "fbp_mesh_wiggle_unique_seed"}:
            requested.add("fbp_mesh_wiggle_w")
    # A repaired/replaced group contains defaults and needs one complete sync.
    if node_group is not previous_group:
        requested = None
    full_update = requested is None
    interface_inputs = _fbp_interface_inputs(node_group)

    updated = False
    for prop_name, socket_name in dict(definition.get("property_map", {})).items():
        if requested is not None and prop_name not in requested:
            continue
        try:
            value = getattr(rig, prop_name)
        except (AttributeError, ReferenceError):
            continue
        value = _fbp_effect_runtime_value(rig, effect_id, prop_name, value, scene=scene)
        value = _fbp_effective_quality_value(rig, effect_id, prop_name, value)
        if prop_name == "fbp_infinite_rotation_direction":
            value = -1.0 if str(value) == "RIGHT" else 1.0
        value = _fbp_cast_effect_value(prop_name, value)
        updated = _fbp_set_modifier_input(
            modifier,
            node_group,
            socket_name,
            value,
            interface_inputs,
        ) or updated

    if definition.get("camera_aware"):
        updated = _fbp_bind_geometry_camera_input(
            rig, effect_id, modifier, node_group=node_group, scene=scene
        ) or updated

    if effect_id == FBP_EFFECT_CUTOUT_OUTLINE and (
        full_update or "fbp_cutout_outline_color" in (requested or set())
    ):
        material = _fbp_ensure_owned_effect_material(
            rig,
            effect_id,
            "Cutout Outline",
            tuple(getattr(rig, "fbp_cutout_outline_color", (0.02, 0.02, 0.02, 1.0))),
        )
        if material:
            updated = _fbp_set_modifier_input(
                modifier, node_group, "Outline Material", material, interface_inputs
            ) or updated

    if effect_id == FBP_EFFECT_EXTRUDED_CUTOUT and (
        full_update
        or bool(requested & {"fbp_extruded_cutout_side_material", "fbp_extruded_cutout_side_color"})
    ):
        try:
            material = getattr(rig, "fbp_extruded_cutout_side_material", None)
            if material is None:
                material = _fbp_ensure_owned_effect_material(
                    rig,
                    effect_id,
                    "Extruded Cutout",
                    tuple(getattr(rig, "fbp_extruded_cutout_side_color", (0.18, 0.12, 0.08, 1.0))),
                )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            material = None
        if material:
            updated = _fbp_set_modifier_input(
                modifier, node_group, "Side Material", material, interface_inputs
            ) or updated

    if effect_id == FBP_EFFECT_THICKNESS and (
        full_update
        or bool(requested & {"fbp_thickness_side_material", "fbp_thickness_side_color"})
    ):
        try:
            material = getattr(rig, "fbp_thickness_side_material", None)
            if material is None:
                material = _fbp_ensure_owned_effect_material(
                    rig,
                    effect_id,
                    "Thickness",
                    tuple(getattr(rig, "fbp_thickness_side_color", (0.18, 0.12, 0.08, 1.0))),
                )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            material = None
        if material:
            updated = _fbp_set_modifier_input(
                modifier,
                node_group,
                "Side Material",
                material,
                interface_inputs,
            ) or updated

    if effect_id == FBP_EFFECT_FELT_FUZZ and full_update:
        # Use the exact animated material already assigned to the plane. This
        # preserves the Frame by Plane image sequence and prevents parameter
        # refreshes from replacing a user-correct material with a generated one.
        material = _fbp_plane_source_material(rig)
        if material:
            updated = _fbp_set_modifier_input(
                modifier,
                node_group,
                "Fuzz Material",
                material,
                interface_inputs,
            ) or updated

    if effect_id == FBP_EFFECT_TEXT_MATRIX:
        text_material_props = {"fbp_text_matrix_text_color", "fbp_text_matrix_realize"}
        if full_update or bool(requested & text_material_props):
            text_material = _fbp_ensure_text_matrix_material(
                rig,
                tuple(getattr(rig, "fbp_text_matrix_text_color", (0.1, 1.0, 0.2, 1.0))),
            )
            if text_material:
                updated = _fbp_set_modifier_input(
                    modifier,
                    node_group,
                    "Text Material",
                    text_material,
                    interface_inputs,
                ) or updated

        if full_update or "fbp_text_matrix_background_color" in requested:
            background_material = _fbp_ensure_owned_effect_material(
                rig,
                effect_id,
                "Text Matrix Background",
                tuple(getattr(rig, "fbp_text_matrix_background_color", (0.0, 0.0, 0.0, 1.0))),
            )
            if background_material:
                updated = _fbp_set_modifier_input(
                    modifier,
                    node_group,
                    "Background Material",
                    background_material,
                    interface_inputs,
                ) or updated

        if full_update or "fbp_text_matrix_font" in requested:
            font = getattr(rig, "fbp_text_matrix_font", None)
            if font is None:
                font = _fbp_default_vector_font()
            if font is not None:
                updated = _fbp_set_modifier_input(
                    modifier,
                    node_group,
                    "Font",
                    font,
                    interface_inputs,
                ) or updated

        charset_props = {
            "fbp_text_matrix_charset",
            "fbp_text_matrix_custom_charset",
            "fbp_text_matrix_character_count",
        }
        if full_update or bool(requested & charset_props):
            updated = _fbp_update_text_matrix_charset(node_group, rig) or updated

    alpha_changed = False
    if (definition.get("alpha_aware") or definition.get("image_aware")) and sync_alpha:
        alpha_changed = _fbp_sync_geometry_alpha(rig, modifier)

    if updated or alpha_changed:
        try:
            plane = _fbp_plane(rig)
            if plane:
                plane.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return updated or alpha_changed


def fbp_update_mesh_wiggle_modifier(rig, modifier=None):
    return fbp_update_geometry_effect(rig, FBP_EFFECT_MESH_WIGGLE, modifier)


def fbp_apply_geometry_effect(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    plane = _fbp_plane(rig)
    if definition.get("kind") != "GEOMETRY" or not plane:
        return False
    source_group = fbp_load_mesh_wiggle_group() if effect_id == FBP_EFFECT_MESH_WIGGLE else _fbp_load_effect_group(effect_id)
    if not source_group:
        return False

    modifier = fbp_find_effect_modifier(rig, effect_id)
    created_modifier = modifier is None
    if modifier is None:
        try:
            modifier = plane.modifiers.new(
                name=str(definition.get("modifier_name", definition.get("label", effect_id))),
                type="NODES",
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn(f"Could not add {definition.get('label', effect_id)}", exc)
            return False

    _fbp_remove_duplicate_effect_modifiers(rig, effect_id, modifier)

    previous_group = getattr(modifier, "node_group", None)
    node_group = source_group
    if definition.get("alpha_aware") or definition.get("private_group"):
        node_group = _fbp_owned_geometry_group(
            rig, effect_id, source_group, previous_group
        )
        if not node_group:
            if created_modifier:
                plane.modifiers.remove(modifier)
            return False

    try:
        modifier.name = str(definition.get("modifier_name", definition.get("label", effect_id)))
        modifier.node_group = node_group
        visible = _fbp_stored_effect_visibility(rig, effect_id, True)
        render_visible = _fbp_stored_effect_render_visibility(rig, effect_id, True)
        modifier.show_viewport = visible
        modifier.show_render = render_visible
        modifier["fbp_effect_id"] = effect_id
        ensure_effect_instance_id(modifier, effect_id)
        if bool(definition.get("custom", False)):
            _fbp_initialize_custom_geometry_inputs(modifier, node_group)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not configure Geometry Nodes effect", exc)
        return False

    if previous_group and previous_group != node_group:
        try:
            if bool(previous_group.get("fbp_private_effect_group", False)) and previous_group.users == 0:
                _fbp_remove_node_group(previous_group)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    if effect_id == FBP_EFFECT_MESH_WIGGLE:
        fbp_assign_mesh_wiggle_layer_seed(rig)
        fbp_set_rna_property_silent(rig, "fbp_mesh_wiggle_enabled", True)
    if effect_id == FBP_EFFECT_CAMERA_SCALE_LOCK and created_modifier:
        reference_distance = fbp_camera_distance_for_rig(rig)
        camera = _fbp_scene_camera()
        camera_data = getattr(camera, "data", None) if camera else None
        if reference_distance > 0.0:
            fbp_set_rna_property_silent(
                rig, "fbp_camera_scale_lock_reference_distance", reference_distance
            )
        if camera_data:
            fbp_set_rna_property_silent(
                rig, "fbp_camera_scale_lock_reference_lens",
                float(getattr(camera_data, "lens", 50.0) or 50.0),
            )
            fbp_set_rna_property_silent(
                rig, "fbp_camera_scale_lock_reference_sensor_width",
                float(getattr(camera_data, "sensor_width", 36.0) or 36.0),
            )
    _fbp_set_enabled(rig, effect_id, True)
    # A False return here means that every socket already matched its target,
    # not that the modifier failed. Keeping a newly created modifier is required
    # when the bundled node-group defaults already equal the layer settings.
    fbp_update_geometry_effect(rig, effect_id, modifier)
    if effect_id == FBP_EFFECT_FELT_FUZZ:
        _fbp_cleanup_owned_effect_materials(rig, effect_id)
    fbp_sync_effect_items(rig)
    return True


def fbp_apply_mesh_wiggle(rig):
    return fbp_apply_geometry_effect(rig, FBP_EFFECT_MESH_WIGGLE)


def fbp_remove_geometry_effect(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    plane = _fbp_plane(rig)
    modifiers = _fbp_find_all_effect_modifiers(rig, effect_id)
    if not plane or not modifiers:
        cleaned = _fbp_set_enabled(rig, effect_id, False)
        cleaned = _fbp_clear_effect_visibility(rig, effect_id) or cleaned
        cleaned = _fbp_clear_effect_render_visibility(rig, effect_id) or cleaned
        if effect_id in {FBP_EFFECT_CUTOUT_OUTLINE, FBP_EFFECT_EXTRUDED_CUTOUT, FBP_EFFECT_THICKNESS, FBP_EFFECT_FELT_FUZZ, FBP_EFFECT_TEXT_MATRIX}:
            cleaned = _fbp_cleanup_owned_effect_materials(rig, effect_id) or cleaned
        if rig:
            fbp_sync_effect_items(rig)
        return cleaned

    # Snapshot the original slots because Geometry Nodes evaluation must not
    # replace the image material.
    try:
        material_snapshot = list(plane.data.materials) if getattr(plane, "data", None) else []
        active_material_index = int(getattr(plane, "active_material_index", 0) or 0)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        material_snapshot = []
        active_material_index = 0

    removed_groups = []
    removed = False
    for modifier in list(modifiers):
        removed_groups.append(getattr(modifier, "node_group", None))
        try:
            plane.modifiers.remove(modifier)
            removed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not remove Geometry Nodes effect", exc)

    if not removed:
        return False

    try:
        current_materials = list(plane.data.materials) if getattr(plane, "data", None) else []
        if current_materials != material_snapshot:
            plane.data.materials.clear()
            for material in material_snapshot:
                if material:
                    plane.data.materials.append(material)
        if material_snapshot:
            plane.active_material_index = min(active_material_index, len(material_snapshot) - 1)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not restore the plane material after removing an effect", exc)

    if effect_id == FBP_EFFECT_MESH_WIGGLE:
        fbp_set_rna_property_silent(rig, "fbp_mesh_wiggle_enabled", False)
    if effect_id in {FBP_EFFECT_CUTOUT_OUTLINE, FBP_EFFECT_EXTRUDED_CUTOUT, FBP_EFFECT_THICKNESS, FBP_EFFECT_FELT_FUZZ, FBP_EFFECT_TEXT_MATRIX}:
        _fbp_cleanup_owned_effect_materials(rig, effect_id)
    _fbp_set_enabled(rig, effect_id, False)
    _fbp_clear_effect_visibility(rig, effect_id)
    _fbp_clear_effect_render_visibility(rig, effect_id)

    for node_group in removed_groups:
        try:
            if node_group and bool(node_group.get("fbp_private_effect_group", False)) and node_group.users == 0:
                _fbp_remove_node_group(node_group)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    fbp_sync_effect_items(rig)
    return True


def fbp_remove_mesh_wiggle(rig):
    return fbp_remove_geometry_effect(rig, FBP_EFFECT_MESH_WIGGLE)


# ---------------------------------------------------------------------------
# Shader effect nodes and routing
# ---------------------------------------------------------------------------


def _fbp_plane_materials(rig):
    plane = _fbp_plane(rig)
    if not plane or not getattr(plane, "data", None):
        return []
    try:
        return [
            mat
            for mat in plane.data.materials
            if (
                mat
                and _fbp_material_is_owned(mat)
                and getattr(mat, "use_nodes", False)
                and mat.node_tree
            )
        ]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return []


def _fbp_shader_image_node(material):
    """Return only the image node owned by the current FBP native material."""
    if not material or not material.node_tree:
        return None
    preferred = material.node_tree.nodes.get("FBP_Native_Media_Texture")
    if preferred and getattr(preferred, "type", "") == "TEX_IMAGE":
        return preferred
    for node in material.node_tree.nodes:
        try:
            if (
                getattr(node, "type", "") == "TEX_IMAGE"
                and bool(node.get("fbp_native_sequence_node", False))
            ):
                return node
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return None


def _fbp_gradient_ramp_node(material):
    if not material or not material.node_tree:
        return None
    node = material.node_tree.nodes.get("FBP_ColorRamp")
    if node and getattr(node, "type", "") == "VALTORGB":
        return node
    for candidate in material.node_tree.nodes:
        try:
            if getattr(candidate, "type", "") == "VALTORGB" and bool(candidate.get("fbp_gradient_ramp", False)):
                return candidate
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return None


def _fbp_procedural_color_source(material, *, create=False):
    """Return a stable color source for solid and gradient FBP materials."""
    if not material or not material.node_tree:
        return None
    image_node = _fbp_shader_image_node(material)
    if image_node:
        return _fbp_node_socket(image_node.outputs, "Color")
    ramp = _fbp_gradient_ramp_node(material)
    if ramp:
        return _fbp_node_socket(ramp.outputs, "Color")

    nodes = material.node_tree.nodes
    source = nodes.get("FBP_Procedural_Color_Source")
    if source and getattr(source, "type", "") == "RGB":
        return _fbp_node_socket(source.outputs, "Color", 0)
    if not create:
        return None

    shader = _fbp_primary_color_shader(material)
    color_input = None
    if shader:
        color_input = (
            _fbp_node_socket(shader.inputs, "Color")
            or _fbp_node_socket(shader.inputs, "Base Color")
            or _fbp_node_socket(shader.inputs, "Base Color", 0)
        )
    color = tuple(getattr(color_input, "default_value", (1.0, 1.0, 1.0, 1.0)))
    try:
        stored = tuple(material.get("fbp_color_value", color))
        if len(stored) >= 4:
            color = stored
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        source = nodes.new("ShaderNodeRGB")
        source.name = "FBP_Procedural_Color_Source"
        source.label = "Frame by Plane Color Source"
        source.location = (-380.0, 80.0)
        source["fbp_procedural_color_source"] = True
        source.outputs[0].default_value = color
        return source.outputs[0]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _fbp_material_color_source(material, *, create=False):
    return _fbp_procedural_color_source(material, create=create)


def _fbp_material_color_target(material):
    shader = _fbp_primary_color_shader(material)
    if not shader:
        return None
    return (
        _fbp_node_socket(shader.inputs, "Color")
        or _fbp_node_socket(shader.inputs, "Base Color")
        or _fbp_node_socket(shader.inputs, "Base Color", 0)
    )


def _fbp_material_uv_target(material):
    image_node = _fbp_shader_image_node(material)
    if image_node:
        return _fbp_node_socket(image_node.inputs, "Vector")
    if material and material.node_tree:
        center = material.node_tree.nodes.get("FBP_GradientCenter")
        if center:
            return _fbp_node_socket(center.inputs, "Vector", 0)
    return None


def _fbp_effect_texcoord_source(material, anchor=None):
    if not material or not material.node_tree:
        return None
    nodes = material.node_tree.nodes
    tex_coord = nodes.get("FBP_Effect_Texture_Coordinates")
    if tex_coord is None:
        try:
            tex_coord = nodes.new("ShaderNodeTexCoord")
            tex_coord.name = "FBP_Effect_Texture_Coordinates"
            tex_coord.label = "Frame by Plane Effect UV"
            x = float(getattr(anchor, "location", (0.0, 0.0))[0]) if anchor else -700.0
            y = float(getattr(anchor, "location", (0.0, 0.0))[1]) if anchor else -180.0
            tex_coord.location = (x - 420.0, y - 180.0)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return None
    return _fbp_node_socket(tex_coord.outputs, "UV", 2)


def _fbp_shader_effect_id(node):
    try:
        return fbp_normalize_effect_id(node.get("fbp_shader_effect_id", ""))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ""


def _fbp_shader_effect_nodes(material, effect_id=None, stage=None):
    if not material or not material.node_tree:
        return []
    result = []
    for node in material.node_tree.nodes:
        node_effect_id = _fbp_shader_effect_id(node)
        if not node_effect_id:
            continue
        definition = fbp_effect_definition(node_effect_id)
        if effect_id and node_effect_id != effect_id:
            continue
        if stage and definition.get("stage") != stage:
            continue
        result.append(node)
    return result


def _fbp_find_shader_effect_nodes_for_rig(rig, effect_id):
    result = []
    for material in _fbp_plane_materials(rig):
        result.extend(_fbp_shader_effect_nodes(material, effect_id=effect_id))
    return result


def _fbp_shader_order_key(stage):
    return f"fbp_shader_effect_order_{str(stage or '').lower()}"


def _fbp_get_rig_shader_stage_order(rig, stage):
    try:
        raw = str(rig.get(_fbp_shader_order_key(stage), "") or "")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        raw = ""
    result = []
    for token in raw.split("|"):
        effect_id = fbp_normalize_effect_id(token)
        definition = fbp_effect_definition(effect_id)
        if definition.get("kind") == "SHADER" and definition.get("stage") == stage and effect_id not in result:
            result.append(effect_id)
    return result


def _fbp_set_rig_shader_stage_order(rig, stage, order):
    normalized = []
    for effect_id in order:
        effect_id = fbp_normalize_effect_id(effect_id)
        definition = fbp_effect_definition(effect_id)
        if definition.get("kind") == "SHADER" and definition.get("stage") == stage and effect_id not in normalized:
            normalized.append(effect_id)
    value = "|".join(normalized)
    key = _fbp_shader_order_key(stage)
    try:
        if str(rig.get(key, "") or "") != value:
            rig[key] = value
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return normalized


def _fbp_get_shader_stage_order(material, stage):
    stage = str(stage or "")
    active_ids = []
    for node in _fbp_shader_effect_nodes(material, stage=stage):
        effect_id = _fbp_shader_effect_id(node)
        if effect_id and effect_id not in active_ids:
            active_ids.append(effect_id)
    raw = ""
    try:
        raw = str(material.get(_fbp_shader_order_key(stage), "") or "")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    order = []
    for token in raw.split("|"):
        effect_id = fbp_normalize_effect_id(token)
        if effect_id in active_ids and effect_id not in order:
            order.append(effect_id)
    for effect_id in FBP_SHADER_STAGE_ORDER.get(stage, ()):
        if effect_id in active_ids and effect_id not in order:
            order.append(effect_id)
    for effect_id in active_ids:
        if effect_id not in order:
            order.append(effect_id)
    return order


def _fbp_set_shader_stage_order(material, stage, order):
    normalized = []
    for effect_id in order:
        effect_id = fbp_normalize_effect_id(effect_id)
        definition = fbp_effect_definition(effect_id)
        if definition.get("kind") != "SHADER" or definition.get("stage") != stage:
            continue
        if effect_id not in normalized:
            normalized.append(effect_id)
    value = "|".join(normalized)
    key = _fbp_shader_order_key(stage)
    try:
        if str(material.get(key, "") or "") != value:
            material[key] = value
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return normalized


def _fbp_stage_effect_nodes(material, stage):
    nodes_by_id = {
        _fbp_shader_effect_id(node): node
        for node in _fbp_shader_effect_nodes(material, stage=stage)
    }
    return [nodes_by_id[effect_id] for effect_id in _fbp_get_shader_stage_order(material, stage) if effect_id in nodes_by_id]


def _fbp_stage_external_target(material, _source_node, stage, effect_nodes):
    """Return the socket after an effect stage for image or procedural materials."""
    if stage != "COLOR" or not material or not material.node_tree:
        return None
    effect_set = set(effect_nodes)
    source = _fbp_material_color_source(material, create=True)
    candidate_sources = [source]
    candidate_sources.extend(
        _fbp_node_socket(
            node.outputs,
            fbp_effect_definition(_fbp_shader_effect_id(node)).get("output_socket", ""),
        )
        for node in effect_nodes
    )
    for link in material.node_tree.links:
        if link.from_socket in candidate_sources and link.to_node not in effect_set:
            return link.to_socket
    return _fbp_material_color_target(material)


def _fbp_stage_external_uv_source(material, _source_node=None, effect_nodes=()):
    if not material or not material.node_tree:
        return None
    target = _fbp_material_uv_target(material)
    effect_set = set(effect_nodes)
    targets = [target] if target is not None else []
    targets.extend(
        _fbp_node_socket(
            node.inputs,
            fbp_effect_definition(_fbp_shader_effect_id(node)).get("input_socket", ""),
        )
        for node in effect_nodes
    )
    for link in material.node_tree.links:
        if link.to_socket in targets and link.from_node not in effect_set:
            return link.from_socket
    anchor = _fbp_shader_image_node(material) or _fbp_gradient_ramp_node(material)
    return _fbp_effect_texcoord_source(material, anchor)


def _fbp_auxiliary_uv_source(material, _source_node=None):
    """Return the vector used by UV-aware color effects on every FBP material."""
    if not material or not material.node_tree:
        return None
    target = _fbp_material_uv_target(material)
    if target is not None and getattr(target, "is_linked", False):
        try:
            return target.links[0].from_socket
        except (AttributeError, IndexError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    source = _fbp_effect_texcoord_source(
        material,
        _fbp_shader_image_node(material) or _fbp_gradient_ramp_node(material),
    )
    if source is not None and target is not None:
        try:
            material.node_tree.links.new(source, target)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return source


def _fbp_connect_color_aux_uv(material, _source_node=None, source=None):
    if not material or not material.node_tree:
        return False
    source = source or _fbp_auxiliary_uv_source(material)
    if source is None:
        return False
    changed = False
    for node in _fbp_stage_effect_nodes(material, "COLOR"):
        definition = fbp_effect_definition(_fbp_shader_effect_id(node))
        socket_name = str(definition.get("uv_input_socket", "") or "")
        if not socket_name:
            continue
        target = _fbp_node_socket(node.inputs, socket_name)
        if target is None:
            continue
        try:
            if len(target.links) == 1 and target.links[0].from_socket == source:
                continue
            for link in list(target.links):
                material.node_tree.links.remove(link)
            material.node_tree.links.new(source, target)
            changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return changed


def _fbp_remove_stage_links(material, _source_node, stage, effect_nodes):
    if not material or not material.node_tree:
        return
    links = material.node_tree.links
    effect_set = set(effect_nodes)
    if stage == "COLOR":
        source = _fbp_material_color_source(material, create=True)
        target = _fbp_material_color_target(material)
        for link in list(links):
            if (
                link.from_socket == source
                or link.from_node in effect_set
                or link.to_node in effect_set
                or (target is not None and link.to_socket == target and link.from_node in effect_set)
            ):
                try:
                    links.remove(link)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
        return

    if stage == "UV":
        target = _fbp_material_uv_target(material)
        for link in list(links):
            if (
                (target is not None and link.to_socket == target)
                or link.from_node in effect_set
                or link.to_node in effect_set
            ):
                try:
                    links.remove(link)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass


def _fbp_relink_effect_alpha(material, effect_nodes, base_alpha):
    """Route alpha-aware color effects and restore the normal alpha when absent."""
    if not material or not material.node_tree:
        return False
    current = base_alpha
    changed = False
    links = material.node_tree.links
    for node in effect_nodes:
        definition = fbp_effect_definition(_fbp_shader_effect_id(node))
        input_name = str(definition.get("alpha_input_socket", "") or "")
        output_name = str(definition.get("alpha_output_socket", "") or "")
        if input_name:
            target = _fbp_node_socket(node.inputs, input_name)
            if target is not None and current is not None:
                try:
                    if len(target.links) == 1 and target.links[0].from_socket == current:
                        pass
                    else:
                        for link in list(target.links):
                            links.remove(link)
                        links.new(current, target)
                        changed = True
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
        if output_name:
            current = _fbp_node_socket(node.outputs, output_name) or current

    if current is None:
        return changed
    has_alpha_effect = any(
        bool(fbp_effect_definition(_fbp_shader_effect_id(node)).get("alpha_output_socket"))
        for node in effect_nodes
    )
    targets = _fbp_material_alpha_targets(material)
    if has_alpha_effect and not targets:
        targets = _fbp_ensure_effect_alpha_targets(material)
    for target in targets:
        try:
            if len(target.links) == 1 and target.links[0].from_socket == current:
                continue
            for link in list(target.links):
                links.remove(link)
            links.new(current, target)
            changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return changed


def _fbp_color_stage_evaluation_nodes(material, rig=None):
    """Return color effect nodes in their real evaluation order."""
    effect_nodes = _fbp_stage_effect_nodes(material, "COLOR")
    if rig is None:
        try:
            owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
            rig = bpy.data.objects.get(owner_name) if owner_name else None
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            rig = None
    regular_nodes = []
    final_nodes = []
    for node in effect_nodes:
        effect_id = _fbp_shader_effect_id(node)
        if rig and fbp_effect_input_source(rig, effect_id) == "FINAL":
            final_nodes.append(node)
        else:
            regular_nodes.append(node)
    return regular_nodes + final_nodes


def _fbp_rebuild_shader_stage(material, stage, source_override=None, target_override=None):
    if not material or not material.node_tree:
        return False
    effect_nodes = _fbp_stage_effect_nodes(material, stage)
    links = material.node_tree.links
    image_node = _fbp_shader_image_node(material)

    if stage == "UV":
        source = source_override or _fbp_stage_external_uv_source(material, image_node, effect_nodes)
        target = _fbp_material_uv_target(material)
        _fbp_remove_stage_links(material, image_node, stage, effect_nodes)
        current = source
        anchor = image_node or _fbp_gradient_ramp_node(material)
        anchor_x = float(getattr(anchor, "location", (-80.0, 0.0))[0])
        anchor_y = float(getattr(anchor, "location", (0.0, 0.0))[1])
        for index, node in enumerate(effect_nodes):
            definition = fbp_effect_definition(_fbp_shader_effect_id(node))
            input_socket = _fbp_node_socket(node.inputs, definition.get("input_socket", ""))
            output_socket = _fbp_node_socket(node.outputs, definition.get("output_socket", ""))
            if current and input_socket:
                try:
                    links.new(current, input_socket)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
            current = output_socket or current
            node.location = (anchor_x - 360.0 + index * 180.0, anchor_y - 220.0)
        if current and target:
            try:
                links.new(current, target)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        _fbp_connect_color_aux_uv(material, image_node, current)
        return bool(current)

    if stage != "COLOR":
        return False

    source = _fbp_material_color_source(material, create=True)
    target = target_override or _fbp_stage_external_target(material, image_node, stage, effect_nodes)
    if source is None or target is None:
        return False
    uv_source = _fbp_auxiliary_uv_source(material, image_node)
    layer_alpha = _fbp_material_layer_alpha_source(material, image_node)
    _fbp_remove_stage_links(material, image_node, stage, effect_nodes)
    current = source
    anchor = image_node or _fbp_gradient_ramp_node(material) or getattr(source, "node", None)
    anchor_x = float(getattr(anchor, "location", (-180.0, 0.0))[0])
    anchor_y = float(getattr(anchor, "location", (0.0, 0.0))[1])
    rig = None
    try:
        owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
        rig = bpy.data.objects.get(owner_name) if owner_name else None
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        rig = None
    # Final Material is deliberately evaluated as a terminal pass. This keeps
    # the graph acyclic: normal Previous/Original effects build the regular
    # stack first, then every Final Material effect processes that completed
    # result in its relative stack order.
    evaluation_nodes = _fbp_color_stage_evaluation_nodes(material, rig)

    for index, node in enumerate(evaluation_nodes):
        effect_id = _fbp_shader_effect_id(node)
        definition = fbp_effect_definition(effect_id)
        input_socket = _fbp_node_socket(node.inputs, definition.get("input_socket", ""))
        output_socket = _fbp_node_socket(node.outputs, definition.get("output_socket", ""))
        input_source = fbp_effect_input_source(rig, effect_id) if rig else "PREVIOUS"
        node_source = source if input_source == "ORIGINAL" else current
        if node_source and input_socket:
            try:
                links.new(node_source, input_socket)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        if uv_source:
            uv_input = _fbp_node_socket(node.inputs, definition.get("uv_input_socket", ""))
            if uv_input:
                try:
                    links.new(uv_source, uv_input)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
        current = output_socket or current
        node.location = (anchor_x + 120.0 + index * 190.0, anchor_y + 250.0)
    try:
        links.new(current, target)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    _fbp_relink_effect_alpha(material, evaluation_nodes, layer_alpha)
    return True

def _fbp_set_shader_node_values(
    rig,
    effect_id,
    node,
    scene=None,
    *,
    property_names=None,
):
    """Update one shader effect node, optionally limiting writes to changed RNA properties."""
    definition = fbp_effect_definition(effect_id)
    requested = None if property_names is None else {
        str(name) for name in property_names if str(name or "")
    }
    full_update = requested is None
    changed = False

    # Image binding is structural state. It is synchronized on full updates and
    # by the frame-change hot path, not on every unrelated slider movement.
    if full_update and bool(definition.get("image_aware", False)):
        material = _fbp_material_for_shader_node(rig, node)
        has_image, source_changed = _fbp_sync_private_shader_source(
            material, getattr(node, "node_tree", None)
        )
        changed = source_changed or changed
        use_image = _fbp_node_socket(getattr(node, "inputs", ()), "Use Image Sample")
        if use_image is not None:
            value = 1.0 if has_image else 0.0
            if not _fbp_effect_values_equal(getattr(use_image, "default_value", None), value):
                try:
                    use_image.default_value = value
                    changed = True
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass

    for prop_name, socket_name in dict(definition.get("property_map", {})).items():
        if requested is not None and prop_name not in requested:
            continue
        input_socket = _fbp_node_socket(node.inputs, socket_name)
        if input_socket is None:
            continue
        try:
            value = getattr(rig, prop_name)
            value = _fbp_effect_runtime_value(rig, effect_id, prop_name, value, scene=scene)
            value = tuple(value) if hasattr(value, "__len__") and not isinstance(value, str) else value
            if _fbp_effect_values_equal(getattr(input_socket, "default_value", None), value):
                continue
            input_socket.default_value = value
            changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue

    debug_socket_name = str(definition.get("debug_socket", "") or "")
    if full_update and debug_socket_name:
        debug_socket = _fbp_node_socket(getattr(node, "inputs", ()), debug_socket_name)
        debug_value = _fbp_debug_mode_value(definition, fbp_effect_debug_mode(rig, effect_id))
        if debug_socket is not None and not _fbp_effect_values_equal(
            getattr(debug_socket, "default_value", None), debug_value
        ):
            try:
                debug_socket.default_value = debug_value
                changed = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass

    aspect_effects = {
        FBP_EFFECT_PIXELATE,
        FBP_EFFECT_HALFTONE,
        FBP_EFFECT_DOT_MATRIX,
        FBP_EFFECT_ASCII_MATRIX,
    }
    aspect_properties = {"fbp_pixelate_square_pixels"}
    if effect_id in aspect_effects and (full_update or bool(requested & aspect_properties)):
        aspect_socket = _fbp_node_socket(node.inputs, "Aspect Ratio")
        if aspect_socket is not None:
            aspect = 1.0
            use_square = True
            if effect_id == FBP_EFFECT_PIXELATE:
                use_square = bool(getattr(rig, "fbp_pixelate_square_pixels", True))
            if use_square:
                aspect = _fbp_rig_plane_aspect(rig)
            if not _fbp_effect_values_equal(aspect_socket.default_value, aspect):
                try:
                    aspect_socket.default_value = aspect
                    changed = True
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass

    if effect_id == FBP_EFFECT_ASCII_MATRIX:
        special_properties = {"fbp_ascii_charset", "fbp_ascii_character_count"}
        if full_update or bool(requested & special_properties):
            special_values = {
                "Charset Row": float(
                    ASCII_PRESET_ROWS.get(
                        str(getattr(rig, "fbp_ascii_charset", "CLASSIC")), 0
                    )
                ),
                "Character Count": float(
                    getattr(rig, "fbp_ascii_character_count", ASCII_ATLAS_COLUMNS)
                    or ASCII_ATLAS_COLUMNS
                ),
            }
            for socket_name, value in special_values.items():
                socket = _fbp_node_socket(node.inputs, socket_name)
                if socket is None or _fbp_effect_values_equal(socket.default_value, value):
                    continue
                try:
                    socket.default_value = value
                    changed = True
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
    return changed


def _fbp_rig_plane_aspect(rig):
    """Return a stable local width/height ratio for square shader cells."""
    plane = _fbp_plane(rig)
    mesh = getattr(plane, "data", None) if plane else None
    try:
        vertices = iter(mesh.vertices)
        first = next(vertices)
        min_x = max_x = float(first.co.x)
        min_y = max_y = float(first.co.y)
        for vertex in vertices:
            x = float(vertex.co.x)
            y = float(vertex.co.y)
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
        height = max_y - min_y
        if height > 1e-8:
            return max(0.001, min(1000.0, float((max_x - min_x) / height)))
    except (AttributeError, ReferenceError, RuntimeError, StopIteration, TypeError, ValueError):
        pass
    return 1.0


def _fbp_material_for_shader_node(rig, node):
    node_tree = getattr(node, "id_data", None) if node else None
    for material in _fbp_plane_materials(rig):
        if getattr(material, "node_tree", None) is node_tree:
            return material
    return None


def _fbp_matrix_source_image_nodes(node_group):
    if not node_group:
        return ()
    try:
        cache_key = _fbp_node_group_cache_key(node_group)
        if cache_key is None:
            return ()
        signature = (len(node_group.nodes),)
        cached = _FBP_MATRIX_IMAGE_NODE_CACHE.get(cache_key)
        if cached and cached[0] == signature:
            return cached[1]
        result = tuple(
            node for node in node_group.nodes
            if bool(node.get("fbp_matrix_source_image_node", False))
        )
        if len(_FBP_MATRIX_IMAGE_NODE_CACHE) >= 512 and cache_key not in _FBP_MATRIX_IMAGE_NODE_CACHE:
            _FBP_MATRIX_IMAGE_NODE_CACHE.clear()
        _FBP_MATRIX_IMAGE_NODE_CACHE[cache_key] = (signature, result)
        return result
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ()


def _fbp_copy_shader_image_user(source_node, target_node):
    source_user = getattr(source_node, "image_user", None) if source_node else None
    target_user = getattr(target_node, "image_user", None) if target_node else None
    if source_user is None or target_user is None:
        return False
    changed = False
    for attr in ("frame_duration", "frame_start", "frame_offset", "use_cyclic", "use_auto_refresh"):
        try:
            value = getattr(source_user, attr)
            if getattr(target_user, attr) != value:
                setattr(target_user, attr, value)
                changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return changed


def _fbp_sync_private_shader_source(material, node_group):
    """Synchronize every private Matrix image sample with the FBP source."""
    image_nodes = _fbp_matrix_source_image_nodes(node_group)
    if not image_nodes:
        return False, False
    source_node = _fbp_shader_image_node(material)
    source_image = getattr(source_node, "image", None) if source_node else None
    changed = False
    for image_node in image_nodes:
        try:
            if getattr(image_node, "image", None) is not source_image:
                image_node.image = source_image
                changed = True
            if source_node is not None:
                for attr in ("projection", "projection_blend"):
                    try:
                        value = getattr(source_node, attr)
                        if getattr(image_node, attr) != value:
                            setattr(image_node, attr, value)
                            changed = True
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                        continue
                try:
                    if image_node.interpolation != "Closest":
                        image_node.interpolation = "Closest"
                        changed = True
                    if image_node.extension != "EXTEND":
                        image_node.extension = "EXTEND"
                        changed = True
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
                changed = _fbp_copy_shader_image_user(source_node, image_node) or changed
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    if changed:
        try:
            node_group.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return bool(source_image), changed


def _fbp_sync_shader_image_sources(
    rig,
    active_effect_ids=None,
    target_nodes=None,
):
    """Refresh image-aware shader groups from the evaluated FBP material.

    ``target_nodes`` is the cached ``(material, node, effect_id)`` list produced
    by the runtime profile. The fallback traversal remains available for repair,
    file-load and direct API calls outside the frame handler.
    """
    active = (
        active_effect_ids
        if isinstance(active_effect_ids, (set, frozenset))
        else set(active_effect_ids or FBP_FRAME_SYNC_SHADER_EFFECT_IDS)
    )
    if target_nodes is None:
        resolved_targets = []
        for material in _fbp_plane_materials(rig):
            for node in _fbp_shader_effect_nodes(material):
                effect_id = _fbp_shader_effect_id(node)
                if effect_id in active and effect_id in FBP_FRAME_SYNC_SHADER_EFFECT_IDS:
                    resolved_targets.append((material, node, effect_id))
    else:
        resolved_targets = [
            (material, node, effect_id)
            for material, node, effect_id in (target_nodes or ())
            if effect_id in active and effect_id in FBP_FRAME_SYNC_SHADER_EFFECT_IDS
        ]

    changed = False
    for material, node, _effect_id in resolved_targets:
        try:
            has_image, source_changed = _fbp_sync_private_shader_source(
                material, getattr(node, "node_tree", None)
            )
            use_image = _fbp_node_socket(getattr(node, "inputs", ()), "Use Image Sample")
            if use_image is not None:
                desired = 1.0 if has_image else 0.0
                if not _fbp_effect_values_equal(getattr(use_image, "default_value", None), desired):
                    use_image.default_value = desired
                    source_changed = True
            changed = source_changed or changed
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return changed


def _fbp_owned_shader_group(rig, material, effect_id, source_group, current=None):
    """Return a private group only when an effect stores material-specific images.

    Procedural color and gradient materials have no source Image Texture. They
    can safely share the canonical Dot Matrix/Textellation group, avoiding a full
    50-70 node copy for every procedural frame material.
    """
    if not material or not source_group:
        return source_group
    definition = fbp_effect_definition(effect_id)
    if not bool(definition.get("private_group", False)):
        return source_group
    if bool(definition.get("image_aware", False)):
        source_node = _fbp_shader_image_node(material)
        if source_node is None or getattr(source_node, "image", None) is None:
            return source_group
    owner = str(getattr(material, "name_full", getattr(material, "name", "")) or "")
    asset_id = str(definition.get("asset_id", "") or "")
    if current:
        try:
            if (
                bool(current.get("fbp_private_effect_group", False))
                and fbp_normalize_effect_id(current.get("fbp_effect_id", "")) == effect_id
                and str(current.get("fbp_effect_asset_id", "") or "") == asset_id
                and str(current.get("fbp_effect_material_owner", "") or "") == owner
                and _builtin_group_is_complete(current, definition)
            ):
                return current
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    try:
        private = source_group.copy()
        private.name = f"{source_group.name} • {owner}"
        private.use_fake_user = False
        private["fbp_private_effect_group"] = True
        private["fbp_effect_id"] = effect_id
        private["fbp_effect_asset_id"] = asset_id
        private["fbp_effect_schema_version"] = FBP_EFFECT_SCHEMA_VERSION
        private["fbp_effect_material_owner"] = owner
        return private
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn(f"Could not create private {definition.get('label', effect_id)} shader group", exc)
        return source_group


def _fbp_remove_unused_effect_group(node_group, keep=None):
    """Remove an unreferenced Frame by Plane node-group copy safely."""
    if not node_group or node_group == keep:
        return False
    try:
        if getattr(node_group, "library", None):
            return False
        tagged = bool(
            node_group.get("fbp_effect_id", "")
            or node_group.get("fbp_effect_asset_id", "")
            or node_group.get("fbp_shader_effect_id", "")
            or node_group.get("fbp_geometry_effect_id", "")
        )
        if not tagged:
            return False
        fake_user = bool(getattr(node_group, "use_fake_user", False))
        real_users = int(getattr(node_group, "users", 0) or 0) - int(fake_user)
        if real_users > 0:
            return False
        if fake_user:
            node_group.use_fake_user = False
        _fbp_remove_node_group(node_group)
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_canonical_shader_effect_node(material, effect_id, node_group):
    """Return one canonical shader node and collapse duplicate nodes."""
    definition = fbp_effect_definition(effect_id)
    nodes = _fbp_shader_effect_nodes(material, effect_id=effect_id)
    if not nodes:
        return None, False

    desired_asset = str(definition.get("asset_id", "") or "")

    def _priority(node):
        current_group = getattr(node, "node_tree", None)
        if current_group == node_group:
            return 0
        try:
            if str(current_group.get("fbp_effect_asset_id", "") or "") == desired_asset:
                return 1
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return 2

    node = min(nodes, key=_priority)
    changed = False
    duplicate_groups = []
    for duplicate in list(nodes):
        if duplicate == node:
            continue
        duplicate_groups.append(getattr(duplicate, "node_tree", None))
        try:
            material.node_tree.nodes.remove(duplicate)
            changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    previous_group = getattr(node, "node_tree", None)
    if previous_group != node_group:
        try:
            node.node_tree = node_group
            changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    try:
        node.label = str(definition.get("label", effect_id))
        node["fbp_shader_effect_id"] = effect_id
        ensure_effect_instance_id(node, effect_id)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    for old_group in duplicate_groups + [previous_group]:
        _fbp_remove_unused_effect_group(old_group, keep=node_group)
    return node, changed


def fbp_apply_shader_effect(rig, effect_id, *, rebuild=True, sync_items=True):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") != "SHADER":
        return False
    node_group = _fbp_load_effect_group(effect_id)
    if not node_group:
        return False
    materials = [
        mat for mat in _fbp_plane_materials(rig)
        if not bool(mat.get("fbp_holdout_material", False))
        and _fbp_material_color_source(mat, create=True) is not None
    ]
    if not materials:
        return False

    changed = False
    for material in materials:
        try:
            material["fbp_effect_rig_owner"] = str(getattr(rig, "name_full", getattr(rig, "name", "")) or "")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        existing_nodes = _fbp_shader_effect_nodes(material, effect_id=effect_id)
        current_group = getattr(existing_nodes[0], "node_tree", None) if existing_nodes else None
        material_group = _fbp_owned_shader_group(
            rig, material, effect_id, node_group, current=current_group
        )
        node, repaired = _fbp_canonical_shader_effect_node(
            material, effect_id, material_group
        )
        changed = repaired or changed
        if node is None:
            try:
                node = material.node_tree.nodes.new("ShaderNodeGroup")
                node.node_tree = material_group
                node.name = f"FBP Effect • {definition.get('label', effect_id)}"
                node.label = str(definition.get("label", effect_id))
                node["fbp_shader_effect_id"] = effect_id
                ensure_effect_instance_id(node, effect_id)
                changed = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                fbp_warn("Could not add shader effect node", exc)
                continue
        try:
            muted = not _fbp_stored_effect_visibility(rig, effect_id, True)
            if bool(getattr(node, "mute", False)) != muted:
                node.mute = muted
                changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        stage = str(definition.get("stage", ""))
        order = _fbp_get_rig_shader_stage_order(rig, stage) or _fbp_get_shader_stage_order(material, stage)
        for active_id in _fbp_get_shader_stage_order(material, stage):
            if active_id not in order:
                order.append(active_id)
        if effect_id not in order:
            order.append(effect_id)
        _fbp_set_rig_shader_stage_order(rig, stage, order)
        _fbp_set_shader_stage_order(material, stage, order)
        changed = _fbp_set_shader_node_values(rig, effect_id, node) or changed
        if rebuild:
            changed = _fbp_rebuild_shader_stage(material, stage) or changed
    _fbp_set_enabled(rig, effect_id, True)
    if sync_items:
        fbp_sync_effect_items(rig)
    return changed or bool(materials)


def fbp_remove_shader_effect(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") != "SHADER":
        return False
    removed = False
    for material in _fbp_plane_materials(rig):
        nodes = _fbp_shader_effect_nodes(material, effect_id=effect_id)
        if not nodes:
            continue
        stage = str(definition.get("stage", ""))
        image_node = _fbp_shader_image_node(material)
        stage_nodes = _fbp_stage_effect_nodes(material, stage)
        source_override = None
        target_override = None
        if stage == "UV":
            source_override = _fbp_stage_external_uv_source(
                material, image_node, stage_nodes
            )
        else:
            target_override = _fbp_stage_external_target(
                material, image_node, stage, stage_nodes
            )
        removed_groups = []
        for node in nodes:
            removed_groups.append(getattr(node, "node_tree", None))
            try:
                material.node_tree.nodes.remove(node)
                removed = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        for node_group in removed_groups:
            try:
                if node_group and bool(node_group.get("fbp_private_effect_group", False)):
                    _fbp_remove_unused_effect_group(node_group)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        order = [item for item in (_fbp_get_rig_shader_stage_order(rig, stage) or _fbp_get_shader_stage_order(material, stage)) if item != effect_id]
        _fbp_set_rig_shader_stage_order(rig, stage, order)
        _fbp_set_shader_stage_order(material, stage, order)
        _fbp_rebuild_shader_stage(
            material, stage,
            source_override=source_override,
            target_override=target_override,
        )
    cleaned = _fbp_set_enabled(rig, effect_id, False)
    cleaned = _fbp_clear_effect_visibility(rig, effect_id) or cleaned
    cleaned = _fbp_clear_effect_render_visibility(rig, effect_id) or cleaned
    fbp_sync_effect_items(rig)
    return removed or cleaned


def fbp_update_shader_effect(
    rig,
    effect_id,
    scene=None,
    *,
    property_names=None,
    nodes=None,
):
    effect_id = fbp_normalize_effect_id(effect_id)
    nodes = list(nodes) if nodes is not None else _fbp_find_shader_effect_nodes_for_rig(rig, effect_id)
    repaired = not nodes or any(
        not getattr(node, "node_tree", None)
        or not _fbp_group_matches(getattr(node, "node_tree", None), effect_id)
        for node in nodes
    )
    if repaired:
        # Re-inject the bundled group before updating values. The material node
        # remains tagged, so this repairs a missing/renamed asset without asking
        # the user to remove and re-add the effect.
        fbp_apply_shader_effect(
            rig, effect_id, rebuild=True, sync_items=False
        )
        nodes = _fbp_find_shader_effect_nodes_for_rig(rig, effect_id)
        property_names = None
    if not nodes:
        return False
    changed = False
    for node in nodes:
        changed = _fbp_set_shader_node_values(
            rig,
            effect_id,
            node,
            scene=scene,
            property_names=property_names,
        ) or changed
    if changed:
        try:
            plane = _fbp_plane(rig)
            if plane:
                plane.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return changed


def _fbp_material_base_alpha_source(material, image_node):
    """Return the alpha source *before* the optional layer-opacity node.

    Returning ``FBP_Opacity`` itself here creates a self-link on the next slider
    update (node output -> its own input). The base source must remain the image,
    native transparent-row mask, gradient ramp or procedural alpha value.
    """
    node_tree = getattr(material, "node_tree", None) if material else None
    if not node_tree:
        return None
    if image_node:
        native_mask = node_tree.nodes.get("FBP_Native_Frame_Alpha")
        if native_mask and getattr(native_mask, "type", "") == "MATH":
            output = _fbp_node_socket(native_mask.outputs, "Value", 0)
            if output:
                return output
        return _fbp_node_socket(image_node.outputs, "Alpha")

    ramp = _fbp_gradient_ramp_node(material)
    if ramp:
        return _fbp_node_socket(ramp.outputs, "Alpha")

    alpha = node_tree.nodes.get("FBP_Procedural_Alpha_Source")
    if not alpha or getattr(alpha, "type", "") != "VALUE":
        try:
            alpha = node_tree.nodes.new("ShaderNodeValue")
            alpha.name = "FBP_Procedural_Alpha_Source"
            alpha.label = "Frame by Plane Alpha Source"
            alpha.location = (-380.0, -80.0)
            alpha["fbp_procedural_alpha_source"] = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return None
    value = 1.0
    try:
        color = tuple(material.get("fbp_color_value", (1.0, 1.0, 1.0, 1.0)))
        value = float(color[3]) if len(color) > 3 else 1.0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        pass
    try:
        alpha.outputs[0].default_value = value
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return _fbp_node_socket(alpha.outputs, "Value", 0)


def _fbp_material_layer_alpha_source(material, image_node):
    """Return alpha after the optional layer-opacity multiplier."""
    base_alpha = _fbp_material_base_alpha_source(material, image_node)
    node_tree = getattr(material, "node_tree", None) if material else None
    if not node_tree or base_alpha is None:
        return base_alpha
    try:
        opacity = node_tree.nodes.get("FBP_Opacity")
        if (
            opacity
            and getattr(opacity, "type", "") == "MATH"
            and str(getattr(opacity, "operation", "") or "") == "MULTIPLY"
            and len(opacity.inputs[0].links) == 1
            and opacity.inputs[0].links[0].from_socket == base_alpha
        ):
            return _fbp_node_socket(opacity.outputs, "Value", 0) or base_alpha
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        pass
    return base_alpha


def _fbp_active_surface_node(material):
    """Return the shader node connected to the active Material Output."""
    node_tree = getattr(material, "node_tree", None) if material else None
    if not node_tree:
        return None
    try:
        outputs = [
            node for node in node_tree.nodes
            if getattr(node, "type", "") == "OUTPUT_MATERIAL"
        ]
        output = next(
            (node for node in outputs if bool(getattr(node, "is_active_output", False))),
            outputs[0] if outputs else None,
        )
        surface = _fbp_node_socket(
            getattr(output, "inputs", ()), "Surface", 0
        ) if output else None
        if surface and surface.is_linked:
            return surface.links[0].from_node
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        return None
    return None


def _fbp_primary_color_shader(material):
    """Return the visible color shader below the active alpha mix, if present."""
    node = _fbp_active_surface_node(material)
    visited = set()
    while node and getattr(node, "type", "") == "MIX_SHADER":
        pointer = id(node)
        if pointer in visited:
            return None
        visited.add(pointer)
        next_node = None
        # FBP alpha mixes use shader 2 as the visible image branch. Fall back to
        # shader 1 for custom but still valid material layouts.
        for index in (2, 1):
            socket = _fbp_node_socket(node.inputs, "Shader", index)
            if socket and socket.is_linked:
                next_node = socket.links[0].from_node
                break
        node = next_node
    return node


def _fbp_material_alpha_targets(material):
    """Return alpha inputs from the shader that actually feeds Material Output.

    Restricting the search to the active surface chain prevents the layer-opacity
    slider from modifying unrelated Principled or Mix Shader nodes that a user may
    have added elsewhere in the Frame by Plane material.
    """
    node_tree = getattr(material, "node_tree", None) if material else None
    if not node_tree:
        return []
    try:
        shader_node = _fbp_active_surface_node(material)
        if shader_node is None:
            return []
        node_type = getattr(shader_node, "type", "")
        if node_type == "MIX_SHADER":
            target = _fbp_node_socket(shader_node.inputs, "Fac", 0)
            return [target] if target else []
        if node_type == "BSDF_PRINCIPLED":
            target = _fbp_node_socket(shader_node.inputs, "Alpha")
            return [target] if target else []
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        return []
    return []


def _fbp_ensure_effect_alpha_targets(material):
    """Create an alpha Mix Shader for opaque emission materials when required."""
    targets = _fbp_material_alpha_targets(material)
    if targets:
        return targets
    node_tree = getattr(material, "node_tree", None) if material else None
    if not node_tree:
        return []
    shader = _fbp_active_surface_node(material)
    if not shader or getattr(shader, "type", "") != "EMISSION":
        return []
    outputs = [
        node for node in node_tree.nodes
        if getattr(node, "type", "") == "OUTPUT_MATERIAL"
    ]
    output = next((node for node in outputs if bool(getattr(node, "is_active_output", False))), None)
    output = output or (outputs[0] if outputs else None)
    if output is None:
        return []
    try:
        transparent = node_tree.nodes.get("FBP_Effect_Transparent")
        if not transparent or getattr(transparent, "type", "") != "BSDF_TRANSPARENT":
            transparent = node_tree.nodes.new("ShaderNodeBsdfTransparent")
            transparent.name = "FBP_Effect_Transparent"
            transparent.label = "Frame by Plane Effect Transparency"
            transparent.location = (shader.location.x, shader.location.y - 180.0)
            transparent["fbp_effect_alpha_helper"] = True
        mix = node_tree.nodes.get("FBP_Effect_Alpha_Mix")
        if not mix or getattr(mix, "type", "") != "MIX_SHADER":
            mix = node_tree.nodes.new("ShaderNodeMixShader")
            mix.name = "FBP_Effect_Alpha_Mix"
            mix.label = "Frame by Plane Effect Alpha"
            mix.location = (shader.location.x + 220.0, shader.location.y)
            mix["fbp_effect_alpha_helper"] = True
        _fbp_link_single(node_tree, transparent.outputs[0], mix.inputs[1])
        _fbp_link_single(node_tree, shader.outputs[0], mix.inputs[2])
        _fbp_link_single(node_tree, mix.outputs[0], output.inputs[0])
        target = _fbp_node_socket(mix.inputs, "Fac", 0)
        return [target] if target else []
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        return []


def _fbp_link_single(node_tree, source, target):
    if not node_tree or not source or not target:
        return False
    try:
        if len(target.links) == 1 and target.links[0].from_socket == source:
            return False
        for link in list(target.links):
            node_tree.links.remove(link)
        node_tree.links.new(source, target)
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_opacity_nodes(node_tree):
    """Return only opacity nodes explicitly owned by Frame By Plane."""
    if not node_tree:
        return []
    result = []
    for node in list(node_tree.nodes):
        try:
            if (
                getattr(node, "type", "") == "MATH"
                and bool(node.get("fbp_internal_opacity_node", False))
            ):
                result.append(node)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return result


def _fbp_prepare_opacity_node(node_tree):
    """Keep at most one Math opacity node and remove duplicates."""
    candidates = _fbp_opacity_nodes(node_tree)
    valid = [node for node in candidates if getattr(node, "type", "") == "MATH"]
    keep = next((node for node in valid if getattr(node, "name", "") == "FBP_Opacity"), None)
    keep = keep or (valid[0] if valid else None)
    changed = False
    for node in candidates:
        if node == keep:
            continue
        try:
            node_tree.nodes.remove(node)
            changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    if keep:
        try:
            keep.name = "FBP_Opacity"
            keep.label = "Layer Opacity"
            keep["fbp_internal_opacity_node"] = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return keep, changed


def fbp_sync_layer_opacity_effect(rig, opacity=None):
    """Update one alpha Multiply node and remove it completely at 100%."""
    if not rig:
        return False
    try:
        opacity = float(getattr(rig, "fbp_opacity", 1.0) if opacity is None else opacity)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        opacity = 1.0
    opacity = max(0.0, min(1.0, opacity))
    changed = False
    for material in _fbp_plane_materials(rig):
        node_tree = getattr(material, "node_tree", None)
        image_node = _fbp_shader_image_node(material)
        if not node_tree or not image_node:
            continue
        try:
            if abs(float(material.get("fbp_opacity", 1.0)) - opacity) > 1e-6:
                material["fbp_opacity"] = opacity
                changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        base_alpha = _fbp_material_base_alpha_source(material, image_node)
        if not base_alpha or not _fbp_material_alpha_targets(material):
            continue
        opacity_node, repaired = _fbp_prepare_opacity_node(node_tree)
        changed = repaired or changed
        if opacity < 0.999:
            if opacity_node is None:
                opacity_node = node_tree.nodes.new("ShaderNodeMath")
                opacity_node.name = "FBP_Opacity"
                opacity_node.label = "Layer Opacity"
                opacity_node["fbp_internal_opacity_node"] = True
                opacity_node.location = (image_node.location.x + 260.0, image_node.location.y - 220.0)
                changed = True
            opacity_node.operation = "MULTIPLY"
            if abs(float(opacity_node.inputs[1].default_value) - opacity) > 1e-6:
                opacity_node.inputs[1].default_value = opacity
                changed = True
            changed = _fbp_link_single(node_tree, base_alpha, opacity_node.inputs[0]) or changed
            alpha_output = _fbp_node_socket(opacity_node.outputs, "Value", 0)
        else:
            if opacity_node is not None:
                try:
                    node_tree.nodes.remove(opacity_node)
                    changed = True
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
            alpha_output = base_alpha

        evaluation_nodes = _fbp_color_stage_evaluation_nodes(material, rig)
        changed = _fbp_relink_effect_alpha(
            material, evaluation_nodes, alpha_output
        ) or changed
    return changed


# ---------------------------------------------------------------------------
# Generic effect stack state
# ---------------------------------------------------------------------------


def fbp_retag_effect_owners_after_layer_rename(rig, old_plane_name=""):
    """Update current name-based effect ownership markers after a layer rename.

    Effect datablocks are linked by pointers, but a few lightweight ownership
    tags intentionally store readable datablock names for repair and cleanup.
    Renaming a rig or its generated plane must update those tags atomically or
    later effect refreshes can treat valid data as foreign and duplicate it.
    """
    if not rig:
        return False
    plane = _fbp_plane(rig)
    if not plane:
        return False

    new_rig_name = str(getattr(rig, "name_full", getattr(rig, "name", "")) or "")
    new_plane_name = str(getattr(plane, "name_full", getattr(plane, "name", "")) or "")
    old_plane_name = str(old_plane_name or "")
    changed = False

    # Shader materials use the rig name to resolve input-source settings.
    for material in _fbp_plane_materials(rig):
        try:
            tagged_owner = str(material.get("fbp_effect_rig_owner", "") or "")
            has_effect_nodes = bool(_fbp_shader_effect_nodes(material))
            if has_effect_nodes and tagged_owner != new_rig_name:
                material["fbp_effect_rig_owner"] = new_rig_name
                changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue

    # Private Geometry Nodes groups use the generated plane name as owner.
    try:
        for modifier in list(getattr(plane, "modifiers", ()) or ()):
            group = getattr(modifier, "node_group", None)
            if not group or not str(group.get("fbp_effect_id", "") or ""):
                continue
            owner = str(group.get("fbp_effect_owner", "") or "")
            if owner == old_plane_name or (not owner and bool(group.get("fbp_private_effect_group", False))):
                group["fbp_effect_owner"] = new_plane_name
                changed = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    # Effect-owned side/back/text materials are not always in the plane slots.
    # Rename is a rare user action, so a bounded global material scan is safer
    # than leaving stale owners that later cleanup may misclassify.
    if old_plane_name and old_plane_name != new_plane_name:
        for material in list(bpy.data.materials):
            try:
                if str(material.get("fbp_effect_material_owner", "") or "") != old_plane_name:
                    continue
                material["fbp_effect_material_owner"] = new_plane_name
                role = str(material.get("fbp_effect_material_role", "") or "")
                expected_old = f"FBP {role} • {old_plane_name}" if role else ""
                if expected_old and material.name == expected_old:
                    material.name = f"FBP {role} • {new_plane_name}"
                changed = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue

    if changed:
        _FBP_EFFECT_HEALTH_CACHE.clear()
        try:
            plane.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return changed


def fbp_effect_is_active(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") == "BASE":
        if _fbp_is_enabled(rig, effect_id):
            return True
        properties = tuple(definition.get("property_map", {}))
        for prop_name in properties:
            if prop_name == "fbp_extend_mode":
                continue
            try:
                if abs(float(getattr(rig, prop_name, 0.0) or 0.0)) > 1e-6:
                    return True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        return False
    if definition.get("kind") == "GEOMETRY":
        return fbp_find_effect_modifier(rig, effect_id) is not None
    if definition.get("kind") == "SHADER":
        return bool(_fbp_find_shader_effect_nodes_for_rig(rig, effect_id))
    return False


def _fbp_effect_ids_cache_key(rig):
    """Return a cache key resilient to pointer reuse after datablock deletion."""
    try:
        pointer = int(rig.as_pointer())
        name = str(getattr(rig, "name_full", getattr(rig, "name", "")) or "")
        return (pointer, name)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return (0, "")


def _fbp_invalidate_effect_runtime_profile(rig=None):
    """Drop cached per-frame targets without retaining stale RNA references."""
    if rig is None:
        _FBP_EFFECT_RUNTIME_PROFILE_CACHE.clear()
        return
    key = _fbp_effect_ids_cache_key(rig)
    if key and key[0]:
        _FBP_EFFECT_RUNTIME_PROFILE_CACHE.pop(key, None)


def _fbp_store_runtime_effect_ids(rig, effect_ids):
    key = _fbp_effect_ids_cache_key(rig)
    if not key or not key[0]:
        return tuple(effect_ids or ())
    normalized = tuple(
        effect_id
        for effect_id in (fbp_normalize_effect_id(item) for item in effect_ids or ())
        if effect_id in FBP_EFFECT_REGISTRY
    )
    # Discovery is also the structural invalidation boundary. Even when the IDs
    # are unchanged, a material or modifier may have been rebuilt and its cached
    # RNA targets must not survive that replacement.
    previous = _FBP_EFFECT_IDS_CACHE.get(key)
    _FBP_EFFECT_RUNTIME_PROFILE_CACHE.pop(key, None)
    if previous != normalized:
        _FBP_EFFECT_SCENE_RIG_CACHE.clear()
    if len(_FBP_EFFECT_IDS_CACHE) >= 512 and key not in _FBP_EFFECT_IDS_CACHE:
        _FBP_EFFECT_IDS_CACHE.clear()
        _FBP_EFFECT_IDS_CACHE_TIME.clear()
        _FBP_EFFECT_RUNTIME_PROFILE_CACHE.clear()
        _FBP_EFFECT_SCENE_RIG_CACHE.clear()
    _FBP_EFFECT_IDS_CACHE[key] = normalized
    _FBP_EFFECT_IDS_CACHE_TIME[key] = time.monotonic()
    return normalized


def _fbp_runtime_effect_ids(rig):
    """Return the current effect stack for per-frame hot paths.

    ``Object.fbp_effects`` is a ``SKIP_SAVE`` UI mirror, so it is empty after a
    file load and may also be cleared by Undo. Treating that transient list as
    the source of truth silently disabled camera, quality and frame-sync work
    until the Effects panel happened to rebuild it. On a cache miss, inspect
    only the current effect modifiers/material nodes once, then keep the result
    in the bounded runtime cache. No legacy conversion or asset rebuild occurs.
    """
    key = _fbp_effect_ids_cache_key(rig)
    if not key or not key[0]:
        return ()
    cached = _FBP_EFFECT_IDS_CACHE.get(key)
    checked_at = float(_FBP_EFFECT_IDS_CACHE_TIME.get(key, 0.0) or 0.0)
    if (
        cached is not None
        and time.monotonic() - checked_at <= _FBP_EFFECT_IDS_CACHE_SECONDS
    ):
        return cached
    try:
        return tuple(fbp_effect_ids_for_rig(rig))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        # Preserve the last known stack when Blender temporarily invalidates an
        # RNA reference during depsgraph evaluation. Back off until the next TTL
        # window instead of retrying the same failed scan on every frame.
        fallback = cached if cached is not None else ()
        _FBP_EFFECT_IDS_CACHE[key] = fallback
        _FBP_EFFECT_IDS_CACHE_TIME[key] = time.monotonic()
        return fallback


def _fbp_scene_effect_runtime_rigs(scene):
    """Return only rigs with active effects, using a self-healing scene index."""
    if scene is None:
        return ()
    try:
        scene_key = (
            int(scene.as_pointer()),
            str(getattr(scene, "name_full", getattr(scene, "name", "")) or ""),
        )
        object_count = len(scene.objects)
        layer_count = len(getattr(scene, "fbp_layers", ()) or ())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        scene_key = (0, "")
        object_count = -1
        layer_count = -1
    now = time.monotonic()
    cached = _FBP_EFFECT_SCENE_RIG_CACHE.get(scene_key) if scene_key[0] else None
    if cached is not None:
        try:
            if (
                int(cached.get("object_count", -2)) == object_count
                and int(cached.get("layer_count", -2)) == layer_count
                and now - float(cached.get("checked_at", 0.0) or 0.0)
                <= _FBP_EFFECT_SCENE_CACHE_SECONDS
            ):
                names = tuple(cached.get("rig_names", ()) or ())
                resolved = tuple(
                    rig for name in names
                    for rig in (scene.objects.get(name),)
                    if rig is not None
                )
                if len(resolved) == len(names):
                    return resolved
                _FBP_EFFECT_SCENE_RIG_CACHE.pop(scene_key, None)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    try:
        from .layers import iter_scene_fbp_rigs
        rigs = tuple(
            rig for rig in iter_scene_fbp_rigs(scene)
            if tuple(_fbp_runtime_effect_ids(rig))
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ()
    if scene_key[0]:
        if len(_FBP_EFFECT_SCENE_RIG_CACHE) >= 32 and scene_key not in _FBP_EFFECT_SCENE_RIG_CACHE:
            _FBP_EFFECT_SCENE_RIG_CACHE.clear()
        _FBP_EFFECT_SCENE_RIG_CACHE[scene_key] = {
            "object_count": object_count,
            "layer_count": layer_count,
            "checked_at": now,
            "rig_names": tuple(
                str(getattr(rig, "name", "") or "") for rig in rigs if rig is not None
            ),
        }
    return rigs


def _fbp_effect_runtime_profile(rig):
    """Return cached targets and flags used by the frame-change hot path.

    Effect discovery already has an explicit cache. This second-level profile
    turns its ordered tuple into a reusable frozenset and resolves modifiers and
    shader nodes once per structural stack change instead of once per frame.
    """
    key = _fbp_effect_ids_cache_key(rig)
    if not key or not key[0]:
        return {
            "effect_ids": (), "active_ids": frozenset(),
            "geometry_source_sync": False, "shader_source_sync": False,
            "evolve_pairs": (), "geometry_modifiers": {},
            "shader_nodes": {}, "frame_geometry_modifiers": (),
            "frame_shader_targets": (),
        }
    effect_ids = tuple(_fbp_runtime_effect_ids(rig))
    plane = _fbp_plane(rig)
    try:
        plane_key = (
            int(plane.as_pointer()) if plane else 0,
            str(getattr(plane, "name_full", getattr(plane, "name", "")) or "") if plane else "",
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        plane_key = (0, "")
    cached = _FBP_EFFECT_RUNTIME_PROFILE_CACHE.get(key)
    if (
        cached is not None
        and cached.get("effect_ids") == effect_ids
        and cached.get("plane_key") == plane_key
        and time.monotonic() - float(cached.get("built_at", 0.0) or 0.0)
        <= _FBP_EFFECT_PROFILE_CACHE_SECONDS
    ):
        return cached

    active_ids = frozenset(effect_ids)
    geometry_modifiers = {}
    frame_geometry_modifiers = []
    if plane is not None:
        try:
            for modifier in plane.modifiers:
                if getattr(modifier, "type", "") != "NODES":
                    continue
                effect_id = _fbp_geometry_effect_id_for_modifier(modifier)
                if effect_id not in active_ids or effect_id in geometry_modifiers:
                    continue
                geometry_modifiers[effect_id] = modifier
                if effect_id in FBP_FRAME_SYNC_GEOMETRY_EFFECT_IDS:
                    frame_geometry_modifiers.append(modifier)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            geometry_modifiers.clear()
            frame_geometry_modifiers.clear()

    shader_node_lists = {}
    frame_shader_targets = []
    try:
        for material in _fbp_plane_materials(rig):
            for node in _fbp_shader_effect_nodes(material):
                effect_id = _fbp_shader_effect_id(node)
                if effect_id not in active_ids:
                    continue
                shader_node_lists.setdefault(effect_id, []).append(node)
                if effect_id in FBP_FRAME_SYNC_SHADER_EFFECT_IDS:
                    frame_shader_targets.append((material, node, effect_id))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        shader_node_lists.clear()
        frame_shader_targets.clear()
    shader_nodes = {
        effect_id: tuple(nodes) for effect_id, nodes in shader_node_lists.items()
    }

    animated_effect_properties = {}
    try:
        for curve in fbp_action_fcurves(rig) or ():
            if bool(getattr(curve, "mute", False)):
                continue
            data_path = str(getattr(curve, "data_path", "") or "")
            for effect_id in FBP_ANIMATED_PROPERTY_EFFECTS.get(data_path, ()):
                if effect_id in active_ids:
                    animated_effect_properties.setdefault(effect_id, set()).add(data_path)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        animated_effect_properties.clear()
    animated_effect_properties = {
        effect_id: frozenset(property_names)
        for effect_id, property_names in animated_effect_properties.items()
    }

    profile = {
        "effect_ids": effect_ids,
        "active_ids": active_ids,
        "plane_key": plane_key,
        "built_at": time.monotonic(),
        "geometry_source_sync": bool(active_ids.intersection(FBP_FRAME_SYNC_GEOMETRY_EFFECT_IDS)),
        "shader_source_sync": bool(active_ids.intersection(FBP_FRAME_SYNC_SHADER_EFFECT_IDS)),
        "animated_effect_properties": animated_effect_properties,
        "evolve_pairs": tuple(
            (effect_id, property_key)
            for effect_id, property_key in FBP_EVOLVE_EFFECT_PROPERTIES
            if effect_id in active_ids
        ),
        "geometry_modifiers": geometry_modifiers,
        "shader_nodes": shader_nodes,
        "frame_geometry_modifiers": tuple(frame_geometry_modifiers),
        "frame_shader_targets": tuple(frame_shader_targets),
    }
    if len(_FBP_EFFECT_RUNTIME_PROFILE_CACHE) >= 512 and key not in _FBP_EFFECT_RUNTIME_PROFILE_CACHE:
        _FBP_EFFECT_RUNTIME_PROFILE_CACHE.clear()
    _FBP_EFFECT_RUNTIME_PROFILE_CACHE[key] = profile
    return profile


def fbp_effect_ids_for_rig(rig, *, refresh_custom=False):
    if refresh_custom:
        fbp_refresh_custom_effect_registry()
    plane = _fbp_plane(rig)
    if not plane:
        return []
    result = []
    seen = set()

    def append_once(effect_id):
        effect_id = fbp_normalize_effect_id(effect_id)
        if not effect_id or effect_id in seen or effect_id not in FBP_EFFECT_REGISTRY:
            return
        seen.add(effect_id)
        result.append(effect_id)

    for effect_id in FBP_BASE_EFFECT_MENU_ORDER:
        if fbp_effect_is_active(rig, effect_id):
            append_once(effect_id)

    try:
        for modifier in plane.modifiers:
            append_once(_fbp_geometry_effect_id_for_modifier(modifier))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    for material in _fbp_plane_materials(rig):
        tagged_nodes = _fbp_shader_effect_nodes(material)
        tagged_ids = {_fbp_shader_effect_id(node) for node in tagged_nodes}
        for stage in ("UV", "COLOR"):
            for effect_id in _fbp_get_shader_stage_order(material, stage):
                if effect_id in tagged_ids:
                    append_once(effect_id)
        # Keep the UI recoverable if a tagged effect node exists but its stored
        # order string was cleared or partially written. The node itself remains
        # the source of truth for effect presence.
        for node in tagged_nodes:
            append_once(_fbp_shader_effect_id(node))
    _fbp_store_runtime_effect_ids(rig, result)
    return result


def fbp_union_effect_ids(rigs):
    """Return every visible effect found on the selected rigs, preserving stack order."""
    result = []
    for rig in [item for item in list(rigs or []) if item]:
        for effect_id in fbp_effect_ids_for_rig(rig):
            if effect_id not in result:
                result.append(effect_id)
    return result


def fbp_effect_presence(rigs, effect_id):
    rigs = [rig for rig in list(rigs or []) if rig]
    effect_id = fbp_normalize_effect_id(effect_id)
    count = sum(1 for rig in rigs if effect_id in _fbp_runtime_effect_ids(rig))
    return count, len(rigs)


def fbp_effect_source_rig(rigs, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    return next(
        (rig for rig in list(rigs or []) if rig and effect_id in _fbp_runtime_effect_ids(rig)),
        None,
    )



def fbp_effect_asset_health_signature(rig, *, force=False, effect_ids=None):
    """Describe whether active effects still reference their expected assets.

    UI draw calls may request this signature repeatedly. Cache only the resulting
    string for a fraction of a second; explicit synchronization forces a fresh
    check before attempting repairs.
    """
    cache_key = _fbp_effect_ids_cache_key(rig)
    cacheable = bool(cache_key and cache_key[0])
    now = time.monotonic()
    if not force and cacheable:
        cached = _FBP_EFFECT_HEALTH_CACHE.get(cache_key)
        if cached and (now - float(cached[0])) < _FBP_EFFECT_HEALTH_CACHE_SECONDS:
            return str(cached[1])

    tokens = []
    active_ids = (
        tuple(effect_ids)
        if effect_ids is not None
        else tuple(fbp_effect_ids_for_rig(rig))
    )
    for effect_id in active_ids:
        definition = fbp_effect_definition(effect_id)
        if definition.get("kind") == "BASE":
            tokens.append(f"{effect_id}:ok")
            continue
        if definition.get("kind") == "GEOMETRY":
            modifier = fbp_find_effect_modifier(rig, effect_id)
            group = getattr(modifier, "node_group", None) if modifier else None
            healthy = bool(group and _fbp_group_matches(group, effect_id))
            if healthy and definition.get("alpha_aware"):
                try:
                    plane = _fbp_plane(rig)
                    healthy = bool(
                        group.get("fbp_effect_owner", "")
                        == str(getattr(plane, "name", "") or "")
                        and int(group.get("fbp_alpha_mask_patch_version", 0) or 0)
                        >= FBP_ALPHA_MASK_PATCH_VERSION
                    )
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    healthy = False
            tokens.append(f"{effect_id}:{'ok' if healthy else 'broken'}")
            continue

        nodes = _fbp_find_shader_effect_nodes_for_rig(rig, effect_id)
        healthy = bool(nodes)
        for node in nodes:
            group = getattr(node, "node_tree", None)
            if not group or not _fbp_group_matches(group, effect_id):
                healthy = False
                break
        tokens.append(f"{effect_id}:{'ok' if healthy else 'broken'}")
    signature = ",".join(tokens)
    if cacheable:
        if len(_FBP_EFFECT_HEALTH_CACHE) >= 512 and cache_key not in _FBP_EFFECT_HEALTH_CACHE:
            _FBP_EFFECT_HEALTH_CACHE.clear()
        _FBP_EFFECT_HEALTH_CACHE[cache_key] = (now, signature)
    return signature


def fbp_repair_effect_assets(rig):
    """Re-inject missing bundled groups while preserving modifiers and keyframes."""
    if not rig:
        return False
    changed = False
    for effect_id in fbp_effect_ids_for_rig(rig):
        definition = fbp_effect_definition(effect_id)
        if definition.get("kind") == "BASE":
            continue
        if definition.get("kind") == "GEOMETRY":
            modifier = fbp_find_effect_modifier(rig, effect_id)
            if not modifier:
                continue
            previous = getattr(modifier, "node_group", None)
            group = _fbp_ensure_geometry_effect_group(rig, effect_id, modifier)
            if group and group != previous:
                changed = True
                changed = fbp_update_geometry_effect(
                    rig, effect_id, modifier
                ) or changed
            continue

        nodes = _fbp_find_shader_effect_nodes_for_rig(rig, effect_id)
        broken = not nodes or any(
            not getattr(node, "node_tree", None)
            or not _fbp_group_matches(getattr(node, "node_tree", None), effect_id)
            for node in nodes
        )
        if broken:
            changed = fbp_apply_shader_effect(
                rig, effect_id, rebuild=True, sync_items=False
            ) or changed
    return changed


def fbp_effect_items_signature(
    rig, rigs=None, *, force_health=False, include_health=True
):
    target_rigs = list(rigs or [rig])
    target_ids = []
    for item in target_rigs:
        effect_ids = (
            fbp_effect_ids_for_rig(item)
            if force_health
            else _fbp_runtime_effect_ids(item)
        )
        for effect_id in effect_ids:
            if effect_id not in target_ids:
                target_ids.append(effect_id)
    names = []
    health = []
    for item in target_rigs:
        try:
            names.append(str(getattr(item, "name_full", getattr(item, "name", "")) or ""))
            health.append(
                fbp_effect_asset_health_signature(item, force=force_health)
                if include_health else "runtime"
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            names.append("")
            health.append("broken" if include_health else "runtime")
    return (
        "|".join(target_ids)
        + "::"
        + "|".join(names)
        + "::"
        + "|".join(health)
    )


FBP_EFFECT_STACK_OWNER_KEY = "fbp_effect_stack_owner_id"


def _fbp_effect_stack_owner_id(rig, *, force=False):
    """Return a persistent per-rig owner identity and repair copied IDs.

    Blender duplicates ID properties during Shift+D. The runtime owner index
    detects two live rigs claiming the same stack identity and gives the later
    claimant a fresh token without scanning every object in the project.
    """
    if rig is None:
        return ""
    rig_key = _fbp_effect_ids_cache_key(rig)
    try:
        owner_id = str(rig.get(FBP_EFFECT_STACK_OWNER_KEY, "") or "")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ""
    claimed_by = _FBP_EFFECT_STACK_OWNER_CACHE.get(owner_id) if owner_id else None
    if force or not owner_id or (claimed_by is not None and claimed_by != rig_key):
        owner_id = uuid.uuid4().hex
        try:
            rig[FBP_EFFECT_STACK_OWNER_KEY] = owner_id
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return ""
    if len(_FBP_EFFECT_STACK_OWNER_CACHE) >= 1024 and owner_id not in _FBP_EFFECT_STACK_OWNER_CACHE:
        _FBP_EFFECT_STACK_OWNER_CACHE.clear()
    _FBP_EFFECT_STACK_OWNER_CACHE[owner_id] = rig_key
    return owner_id


def _fbp_assign_logical_effect_instance(owners, effect_id, owner_token, *, force=False):
    owners = [owner for owner in tuple(owners or ()) if owner is not None]
    if not owners:
        return False
    existing_ids = []
    owner_tokens = []
    for owner in owners:
        try:
            current = str(owner.get(FBP_EFFECT_INSTANCE_KEY, "") or "")
            stored_owner = str(owner.get(FBP_EFFECT_INSTANCE_OWNER_KEY, "") or "")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            current = ""
            stored_owner = ""
        if current:
            existing_ids.append(current)
        owner_tokens.append(stored_owner)
    unique_ids = tuple(dict.fromkeys(existing_ids))
    claimed_owner = (
        _FBP_EFFECT_INSTANCE_OWNER_CACHE.get(unique_ids[0])
        if len(unique_ids) == 1 else None
    )
    needs_fresh = bool(
        force
        or not unique_ids
        or len(unique_ids) != 1
        or any(token and token != owner_token for token in owner_tokens)
        or (claimed_owner is not None and claimed_owner != owner_token)
    )
    instance_id = new_effect_instance_id(effect_id) if needs_fresh else unique_ids[0]
    changed = False
    for owner in owners:
        try:
            current = str(owner.get(FBP_EFFECT_INSTANCE_KEY, "") or "")
            stored_owner = str(owner.get(FBP_EFFECT_INSTANCE_OWNER_KEY, "") or "")
            version = int(owner.get(FBP_EFFECT_INSTANCE_VERSION_KEY, 0) or 0)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            current = ""
            stored_owner = ""
            version = 0
        if (
            current == instance_id
            and stored_owner == owner_token
            and version == FBP_EFFECT_INSTANCE_VERSION
        ):
            continue
        if assign_effect_instance_id(owner, effect_id, instance_id, owner_token):
            changed = True
    if len(_FBP_EFFECT_INSTANCE_OWNER_CACHE) >= 2048 and instance_id not in _FBP_EFFECT_INSTANCE_OWNER_CACHE:
        _FBP_EFFECT_INSTANCE_OWNER_CACHE.clear()
    _FBP_EFFECT_INSTANCE_OWNER_CACHE[instance_id] = owner_token
    return changed


def fbp_refresh_effect_instance_ids(rig, *, force=False, refresh_stack_owner=False):
    """Normalize logical effect-instance IDs for one Frame by Plane layer.

    All material copies of one shader effect share one instance ID. Geometry
    modifiers keep one ID each. Duplicated rigs receive a new stack owner and
    therefore cannot retain the source layer's persistent instance identities.
    """
    if rig is None:
        return False
    owner_id = _fbp_effect_stack_owner_id(
        rig, force=bool(force or refresh_stack_owner)
    )
    if not owner_id:
        return False
    changed = False
    plane = _fbp_plane(rig)
    if plane is not None:
        try:
            for modifier in plane.modifiers:
                effect_id = _fbp_geometry_effect_id_for_modifier(modifier)
                if not effect_id:
                    continue
                changed = _fbp_assign_logical_effect_instance(
                    (modifier,), effect_id, f"{owner_id}:{effect_id}", force=force
                ) or changed
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    shader_owners = {}
    try:
        for material in _fbp_plane_materials(rig):
            for node in _fbp_shader_effect_nodes(material):
                effect_id = _fbp_shader_effect_id(node)
                if effect_id:
                    shader_owners.setdefault(effect_id, []).append(node)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        shader_owners.clear()
    for effect_id, owners in shader_owners.items():
        changed = _fbp_assign_logical_effect_instance(
            owners, effect_id, f"{owner_id}:{effect_id}", force=force
        ) or changed
    return changed


def fbp_effect_instance_id_for_rig(rig, effect_id, *, ensure=True):
    """Return the logical identity of the concrete owner in the active stack."""
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") == "GEOMETRY":
        modifier = fbp_find_effect_modifier(rig, effect_id)
        if modifier:
            return (
                ensure_effect_instance_id(modifier, effect_id)
                if ensure else effect_instance_id(modifier)
            )
        return ""
    if definition.get("kind") == "SHADER":
        nodes = _fbp_find_shader_effect_nodes_for_rig(rig, effect_id)
        if nodes:
            return (
                ensure_effect_instance_id(nodes[0], effect_id)
                if ensure else effect_instance_id(nodes[0])
            )
    if definition.get("kind") == "BASE":
        return f"base:{fbp_normalize_effect_id(effect_id).lower()}"
    return ""


def fbp_sync_effect_items(rig, rigs=None, *, repair_assets=True):
    if not rig or not hasattr(rig, "fbp_effects"):
        return []
    target_rigs = list(rigs or [rig])
    for target_rig in target_rigs:
        if repair_assets:
            fbp_repair_effect_assets(target_rig)
        fbp_refresh_effect_instance_ids(target_rig)

    # Discover each repaired stack once and reuse it for union, health,
    # visibility and UI mirroring. The old path traversed every modifier and
    # material node tree several times during one synchronization.
    ids_by_key = {}
    target_ids = []
    for target_rig in target_rigs:
        effect_ids = tuple(fbp_effect_ids_for_rig(target_rig))
        ids_by_key[_fbp_effect_ids_cache_key(target_rig)] = effect_ids
        for effect_id in effect_ids:
            if effect_id not in target_ids:
                target_ids.append(effect_id)

    names = []
    health = []
    for target_rig in target_rigs:
        try:
            names.append(
                str(
                    getattr(
                        target_rig,
                        "name_full",
                        getattr(target_rig, "name", ""),
                    )
                    or ""
                )
            )
            effect_ids = ids_by_key.get(_fbp_effect_ids_cache_key(target_rig), ())
            health.append(
                fbp_effect_asset_health_signature(
                    target_rig,
                    force=True,
                    effect_ids=effect_ids,
                )
                if repair_assets else "runtime"
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            names.append("")
            health.append("broken" if repair_assets else "runtime")
    signature = (
        "|".join(target_ids)
        + "::"
        + "|".join(names)
        + "::"
        + "|".join(health)
    )

    for target_rig in target_rigs:
        for effect_id in ids_by_key.get(_fbp_effect_ids_cache_key(target_rig), ()):
            viewport_key = _fbp_effect_visibility_key(effect_id)
            render_key = _fbp_effect_render_visibility_key(effect_id)
            try:
                if viewport_key not in target_rig:
                    _fbp_store_effect_visibility(
                        target_rig,
                        effect_id,
                        fbp_effect_visible_state(target_rig, effect_id),
                    )
                if render_key not in target_rig:
                    _fbp_store_effect_render_visibility(
                        target_rig,
                        effect_id,
                        fbp_effect_render_visible_state(target_rig, effect_id),
                    )
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
    try:
        active_index = int(getattr(rig, "fbp_effects_index", 0) or 0)
        active_id = ""
        if 0 <= active_index < len(rig.fbp_effects):
            active_id = str(getattr(rig.fbp_effects[active_index], "effect_id", "") or "")
        current_ids = [str(getattr(item, "effect_id", "") or "") for item in rig.fbp_effects]
        if current_ids != target_ids:
            rig.fbp_effects.clear()
            for effect_id in target_ids:
                item = rig.fbp_effects.add()
                item.effect_id = effect_id
                item.instance_id = fbp_effect_instance_id_for_rig(rig, effect_id)
                item.label = str(fbp_effect_definition(effect_id).get("label", effect_id))
        else:
            for item in rig.fbp_effects:
                effect_id = str(getattr(item, "effect_id", "") or "")
                item.instance_id = fbp_effect_instance_id_for_rig(rig, effect_id)
        if target_ids:
            rig.fbp_effects_index = target_ids.index(active_id) if active_id in target_ids else min(active_index, len(target_ids) - 1)
        else:
            rig.fbp_effects_index = 0
        if hasattr(rig, "fbp_effects_signature"):
            rig.fbp_effects_signature = signature
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return []
    return target_ids


def fbp_schedule_effect_items_sync(rig, rigs=None):
    if not rig or not hasattr(rig, "fbp_effects"):
        return []
    rigs = [item for item in list(rigs or [rig]) if item]
    target_ids = []
    for target_rig in rigs:
        for effect_id in _fbp_runtime_effect_ids(target_rig):
            if effect_id not in target_ids:
                target_ids.append(effect_id)
    signature = fbp_effect_items_signature(rig, rigs, include_health=False)
    try:
        current_ids = [str(getattr(item, "effect_id", "") or "") for item in rig.fbp_effects]
        if current_ids == target_ids and str(getattr(rig, "fbp_effects_signature", "") or "") == signature:
            return target_ids
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    from . import safe_tasks as _safe_tasks
    rig_name = str(getattr(rig, "name", "") or "")
    rig_key = fbp_obj_runtime_key(rig)

    def _timer():
        active_rig = bpy.data.objects.get(rig_name) if rig_name else None
        if active_rig is None or fbp_obj_runtime_key(active_rig) != rig_key:
            active_rig = next(
                (obj for obj in bpy.data.objects if fbp_obj_runtime_key(obj) == rig_key),
                None,
            )
        if not active_rig:
            return None
        current_rigs = _fbp_selected_rigs(getattr(bpy, "context", None))
        if active_rig not in current_rigs:
            current_rigs = [active_rig]
        # UI mirroring must stay lightweight. Structural repair is performed by
        # effect operators, Scene sync and explicit diagnostics, not every time
        # the sidebar needs to rebuild its transient list.
        fbp_sync_effect_items(active_rig, current_rigs, repair_assets=False)
        return None

    _safe_tasks.schedule_once(f"ui.effect_stack.{rig_key}", _timer, first_interval=0.03)
    return target_ids


def fbp_active_effect_id(rig):
    if not rig or not hasattr(rig, "fbp_effects"):
        return ""
    try:
        index = int(getattr(rig, "fbp_effects_index", 0) or 0)
        if 0 <= index < len(rig.fbp_effects):
            return str(getattr(rig.fbp_effects[index], "effect_id", "") or "")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return ""


def _fbp_select_effect_row(rig, effect_id, rigs=None):
    """Select an effect in the runtime UI mirror without changing Blender data."""
    effect_id = fbp_normalize_effect_id(effect_id)
    if not rig or not effect_id:
        return False
    fbp_sync_effect_items(rig, rigs)
    try:
        for index, item in enumerate(rig.fbp_effects):
            if fbp_normalize_effect_id(getattr(item, "effect_id", "")) == effect_id:
                rig.fbp_effects_index = index
                return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return False


def fbp_add_effect(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if not fbp_effect_supported_for_rig(rig, effect_id):
        return False
    if definition.get("kind") == "BASE":
        changed = _fbp_set_enabled(rig, effect_id, True)
        fbp_sync_effect_items(rig)
        applied = changed or fbp_effect_is_active(rig, effect_id)
    elif definition.get("kind") == "GEOMETRY":
        applied = fbp_apply_geometry_effect(rig, effect_id)
    elif definition.get("kind") == "SHADER":
        applied = fbp_apply_shader_effect(rig, effect_id)
    else:
        return False
    if applied and definition.get("evolve_property"):
        fbp_ensure_effect_animation_state(rig, effect_id)
    return bool(applied)


def fbp_capture_custom_shader_effect_states(rig):
    """Capture per-instance custom shader socket values before material rebuilds."""
    if not rig:
        return {}
    fbp_refresh_custom_effect_registry(force=False)
    states = {}
    for effect_id, definition in tuple(FBP_EFFECT_REGISTRY.items()):
        if not bool(definition.get("custom", False)):
            continue
        if definition.get("kind") != "SHADER":
            continue
        if bool(definition.get("custom_invalid", False)):
            continue
        if not _fbp_find_shader_effect_nodes_for_rig(rig, effect_id):
            continue
        state = _fbp_capture_custom_effect_inputs(rig, effect_id)
        if state:
            states[effect_id] = state
    return states


def fbp_restore_enabled_shader_effects(rig, custom_states=None):
    """Restore shader nodes after a color/gradient material was rebuilt."""
    if not rig:
        return False
    changed = False
    custom_states = dict(custom_states or {})
    fbp_refresh_custom_effect_registry(force=False)
    for effect_id, definition in FBP_EFFECT_REGISTRY.items():
        if definition.get("kind") != "SHADER":
            continue
        if not _fbp_is_enabled(rig, effect_id):
            continue
        if not fbp_effect_supported_for_rig(rig, effect_id):
            continue
        applied = fbp_apply_shader_effect(
            rig, effect_id, rebuild=True, sync_items=False
        )
        changed = applied or changed
        if applied and effect_id in custom_states:
            changed = _fbp_apply_custom_effect_inputs(
                rig, effect_id, custom_states[effect_id]
            ) or changed
    fbp_sync_effect_items(rig)
    return changed



def _fbp_clear_effect_auxiliary_state(rig, effect_id):
    changed = False
    for key in (
        _fbp_effect_state_key(effect_id, "input_source"),
        _fbp_effect_state_key(effect_id, "debug"),
    ):
        try:
            if key in rig:
                del rig[key]
                changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
            pass
    if fbp_effect_definition(effect_id).get("evolve_property"):
        changed = fbp_reset_effect_animation_state(rig, effect_id) or changed
    return changed

def fbp_remove_effect(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") == "BASE":
        defaults = {
            "fbp_extend_mode": "EDGE",
            "fbp_extend_top": 0.0, "fbp_extend_left": 0.0,
            "fbp_extend_right": 0.0, "fbp_extend_bottom": 0.0,
            "fbp_crop_top": 0.0, "fbp_crop_left": 0.0,
            "fbp_crop_right": 0.0, "fbp_crop_bottom": 0.0,
        }
        changed = False
        for prop_name in definition.get("property_map", {}):
            if not hasattr(rig, prop_name):
                continue
            changed = fbp_set_rna_property_silent(
                rig, prop_name, defaults.get(prop_name, 0.0)
            ) or changed
        changed = _fbp_set_enabled(rig, effect_id, False) or changed
        changed = _fbp_clear_effect_visibility(rig, effect_id) or changed
        changed = _fbp_clear_effect_render_visibility(rig, effect_id) or changed
        try:
            from .core import update_object_padding_cb
            update_object_padding_cb(rig, bpy.context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not reset Crop / Extend geometry", exc)
        _fbp_clear_effect_auxiliary_state(rig, effect_id)
        fbp_sync_effect_items(rig)
        return changed
    if definition.get("kind") == "GEOMETRY":
        changed = fbp_remove_geometry_effect(rig, effect_id)
        if changed:
            _fbp_clear_effect_auxiliary_state(rig, effect_id)
        return changed
    if definition.get("kind") == "SHADER":
        changed = fbp_remove_shader_effect(rig, effect_id)
        if changed:
            _fbp_clear_effect_auxiliary_state(rig, effect_id)
        return changed
    return False


def _fbp_geometry_effect_id_for_modifier(modifier):
    if not modifier or getattr(modifier, "type", "") != "NODES":
        return ""
    try:
        tagged = fbp_normalize_effect_id(modifier.get("fbp_effect_id", ""))
        if tagged in FBP_EFFECT_REGISTRY and fbp_effect_definition(tagged).get("kind") == "GEOMETRY":
            return tagged
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    node_group = getattr(modifier, "node_group", None)
    for effect_id, definition in FBP_EFFECT_REGISTRY.items():
        if definition.get("kind") == "GEOMETRY" and _fbp_group_matches(node_group, effect_id):
            return effect_id
    return ""


def fbp_move_effect(rig, effect_id, direction):
    """Move an effect in its real Blender evaluation chain."""
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    direction = -1 if str(direction).upper() == "UP" else 1
    if definition.get("kind") == "GEOMETRY":
        plane = _fbp_plane(rig)
        modifier = fbp_find_effect_modifier(rig, effect_id)
        if not plane or not modifier:
            return False
        ordered = []
        try:
            for index, item in enumerate(plane.modifiers):
                item_effect = _fbp_geometry_effect_id_for_modifier(item)
                if item_effect:
                    ordered.append((index, item, item_effect))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False
        current = next((index for index, data in enumerate(ordered) if data[1] == modifier), -1)
        target = current + direction
        if current < 0 or target < 0 or target >= len(ordered):
            return False
        from_index = ordered[current][0]
        to_index = ordered[target][0]
        try:
            plane.modifiers.move(from_index, to_index)
            plane.update_tag()
            fbp_sync_effect_items(rig)
            return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False

    if definition.get("kind") == "SHADER":
        stage = str(definition.get("stage", ""))
        materials = [
            material for material in _fbp_plane_materials(rig)
            if _fbp_shader_effect_nodes(material, effect_id=effect_id)
        ]
        if not materials:
            return False

        # Compute the new order once and push it to every material. Procedural
        # frame materials can otherwise drift into different effect orders when
        # one material has a temporarily incomplete stored order.
        order = _fbp_get_rig_shader_stage_order(rig, stage)
        if effect_id not in order:
            order = _fbp_get_shader_stage_order(materials[0], stage)
        if effect_id not in order:
            return False
        current = order.index(effect_id)
        target = current + direction
        if target < 0 or target >= len(order):
            return False
        order[current], order[target] = order[target], order[current]
        _fbp_set_rig_shader_stage_order(rig, stage, order)

        moved = False
        for material in materials:
            active = _fbp_get_shader_stage_order(material, stage)
            material_order = [item for item in order if item in active]
            material_order.extend(item for item in active if item not in material_order)
            _fbp_set_shader_stage_order(material, stage, material_order)
            moved = _fbp_rebuild_shader_stage(material, stage) or moved
        if moved:
            fbp_sync_effect_items(rig)
        return moved
    return False


def fbp_reapply_all_effects(rig, custom_states=None):
    """Restore shader routing and alpha images after an FBP material rebuild."""
    if not rig:
        return False
    changed = False
    custom_states = dict(custom_states or {})
    fbp_refresh_custom_effect_registry(force=False)
    for effect_id, definition in FBP_EFFECT_REGISTRY.items():
        if definition.get("kind") == "SHADER" and (
            _fbp_is_enabled(rig, effect_id)
            or bool(_fbp_find_shader_effect_nodes_for_rig(rig, effect_id))
        ):
            applied = fbp_apply_shader_effect(
                rig, effect_id, rebuild=False, sync_items=False
            )
            changed = applied or changed
            if applied and effect_id in custom_states:
                changed = _fbp_apply_custom_effect_inputs(
                    rig, effect_id, custom_states[effect_id]
                ) or changed
    # Restore the user-defined order after a material rebuild.
    for stage in ("UV", "COLOR"):
        desired = _fbp_get_rig_shader_stage_order(rig, stage)
        for material in _fbp_plane_materials(rig):
            active = _fbp_get_shader_stage_order(material, stage)
            order = [effect_id for effect_id in desired if effect_id in active]
            order.extend(effect_id for effect_id in active if effect_id not in order)
            _fbp_set_shader_stage_order(material, stage, order)
            _fbp_rebuild_shader_stage(material, stage)
    for effect_id, definition in FBP_EFFECT_REGISTRY.items():
        if definition.get("kind") != "GEOMETRY":
            continue
        modifier = fbp_find_effect_modifier(rig, effect_id)
        if not modifier:
            continue
        _fbp_remove_duplicate_effect_modifiers(rig, effect_id, modifier)
        previous_group = getattr(modifier, "node_group", None)
        try:
            modifier.name = str(definition.get("modifier_name", definition.get("label", effect_id)))
            modifier["fbp_effect_id"] = effect_id
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        source_group = (
            fbp_load_mesh_wiggle_group()
            if effect_id == FBP_EFFECT_MESH_WIGGLE
            else _fbp_load_effect_group(effect_id)
        )
        if definition.get("alpha_aware") or definition.get("private_group"):
            owned_group = _fbp_owned_geometry_group(
                rig, effect_id, source_group, previous_group
            )
            if owned_group and owned_group != previous_group:
                try:
                    modifier.node_group = owned_group
                    changed = True
                    if (
                        previous_group
                        and bool(previous_group.get("fbp_private_effect_group", False))
                        and previous_group.users == 0
                    ):
                        _fbp_remove_node_group(previous_group)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
        elif source_group and previous_group != source_group:
            try:
                current_asset = str(previous_group.get("fbp_effect_asset_id", "") or "") if previous_group else ""
                desired_asset = str(definition.get("asset_id", "") or "")
                if current_asset != desired_asset:
                    modifier.node_group = source_group
                    changed = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        try:
            viewport_visible = _fbp_stored_effect_visibility(rig, effect_id, True)
            render_visible = _fbp_stored_effect_render_visibility(rig, effect_id, True)
            if bool(getattr(modifier, "show_viewport", True)) != viewport_visible:
                modifier.show_viewport = viewport_visible
                changed = True
            if bool(getattr(modifier, "show_render", True)) != render_visible:
                modifier.show_render = render_visible
                changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        changed = fbp_update_geometry_effect(rig, effect_id, modifier) or changed
    changed = fbp_sync_layer_opacity_effect(rig) or changed
    fbp_sync_effect_items(rig)
    return changed


def _fbp_callback_targets(rig, context, *, effect_id=""):
    selected = _fbp_selected_rigs(context)
    targets = selected if rig in selected else [rig]
    if effect_id:
        targets = [target for target in targets if fbp_effect_is_active(target, effect_id)]
    return targets


def update_text_matrix_grid_settings_cb(self, context):
    """Apply viewport grid changes once after a Text Matrix quality preset.

    The quality callback changes columns and resets rows to Auto silently. This
    wrapper mirrors those values to selected rigs and pushes both modifier
    sockets in a single Geometry Nodes update.
    """
    if fbp_is_silent_property_update(self):
        return
    names = (
        "fbp_text_matrix_quality",
        "fbp_text_matrix_viewport_columns",
        "fbp_text_matrix_viewport_rows",
        "fbp_text_matrix_render_columns",
        "fbp_text_matrix_render_rows",
    )
    targets = _fbp_callback_targets(self, context, effect_id=FBP_EFFECT_TEXT_MATRIX)
    for rig in targets:
        if rig != self:
            for name in names:
                try:
                    fbp_set_rna_property_silent(rig, name, getattr(self, name))
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    continue
        fbp_update_geometry_effect(
            rig,
            FBP_EFFECT_TEXT_MATRIX,
            sync_alpha=False,
            property_names={
                "fbp_text_matrix_viewport_columns",
                "fbp_text_matrix_viewport_rows",
            },
        )


def update_effect_setting_cb(self, context, effect_id, prop_name):
    effect_id = fbp_normalize_effect_id(effect_id)
    if fbp_is_silent_property_update(self):
        return
    definition = fbp_effect_definition(effect_id)
    allowed = set(definition.get("property_map", {})) | set(definition.get("extra_properties", ()))
    if prop_name not in allowed and not (
        effect_id == FBP_EFFECT_MESH_WIGGLE and prop_name in {"fbp_mesh_wiggle_seed", "fbp_mesh_wiggle_unique_seed"}
    ):
        return
    try:
        value = getattr(self, prop_name)
    except (AttributeError, ReferenceError):
        return
    targets = _fbp_callback_targets(self, context, effect_id=effect_id)
    text_matrix_manual_grid = {
        "fbp_text_matrix_viewport_columns",
        "fbp_text_matrix_viewport_rows",
        "fbp_text_matrix_render_columns",
        "fbp_text_matrix_render_rows",
    }
    text_matrix_playback_controls = {
        "fbp_text_matrix_auto_playback_limit",
        "fbp_text_matrix_playback_columns",
        "fbp_text_matrix_playback_rows",
    }
    for rig in targets:
        if rig != self:
            fbp_set_rna_property_silent(rig, prop_name, value)
        if effect_id == FBP_EFFECT_TEXT_MATRIX and prop_name in text_matrix_manual_grid:
            fbp_set_rna_property_silent(rig, "fbp_text_matrix_quality", "CUSTOM")
        if effect_id == FBP_EFFECT_MESH_WIGGLE and bool(getattr(rig, "fbp_mesh_wiggle_unique_seed", False)):
            fbp_assign_mesh_wiggle_layer_seed(rig)
        if definition.get("kind") == "GEOMETRY":
            requested = {prop_name}
            if effect_id == FBP_EFFECT_TEXT_MATRIX and prop_name in text_matrix_playback_controls:
                requested = {
                    "fbp_text_matrix_viewport_columns",
                    "fbp_text_matrix_viewport_rows",
                }
            for contract in _fbp_quality_contracts(definition):
                playback_property = str(contract.get("playback_property", ""))
                render_property = str(contract.get("render_property", ""))
                viewport_property = str(contract.get("viewport_property", ""))
                if prop_name == playback_property:
                    requested = {viewport_property} if _FBP_EFFECT_PLAYBACK_ACTIVE and viewport_property else set()
                    break
                if prop_name == render_property:
                    requested = set()
                    break
            if requested:
                fbp_update_geometry_effect(
                    rig,
                    effect_id,
                    sync_alpha=False,
                    property_names=requested,
                )
        else:
            fbp_update_shader_effect(
                rig,
                effect_id,
                property_names={prop_name},
            )


def update_effect_animation_setting_cb(self, context, effect_id, suffix):
    effect_id = fbp_normalize_effect_id(effect_id)
    if fbp_is_silent_property_update(self):
        return
    key = _fbp_animation_key(effect_id, suffix)
    try:
        value = getattr(self, key)
    except (AttributeError, ReferenceError):
        return
    targets = _fbp_callback_targets(self, context, effect_id=effect_id)
    for rig in targets:
        if rig != self and hasattr(rig, key):
            fbp_set_rna_property_silent(rig, key, value)
        state = fbp_ensure_effect_animation_state(rig, effect_id)
        if suffix == "evolve" or bool(state.get("evolve", False)):
            definition = fbp_effect_definition(effect_id)
            evolve_property = str(definition.get("evolve_property", "") or "")
            property_names = {evolve_property} if evolve_property else None
            if definition.get("kind") == "GEOMETRY":
                fbp_update_geometry_effect(
                    rig,
                    effect_id,
                    sync_alpha=False,
                    property_names=property_names,
                )
            else:
                fbp_update_shader_effect(
                    rig,
                    effect_id,
                    property_names=property_names,
                )


def update_mesh_wiggle_enabled_cb(self, context):
    if fbp_is_silent_property_update(self):
        return
    enabled = bool(getattr(self, "fbp_mesh_wiggle_enabled", False))
    for rig in _fbp_callback_targets(self, context):
        if rig != self:
            fbp_set_rna_property_silent(rig, "fbp_mesh_wiggle_enabled", enabled)
        if enabled:
            fbp_apply_mesh_wiggle(rig)
        else:
            fbp_remove_mesh_wiggle(rig)


def update_mesh_wiggle_setting_cb(self, context, prop_name):
    return update_effect_setting_cb(self, context, FBP_EFFECT_MESH_WIGGLE, prop_name)


def fbp_effect_visible_state(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") == "BASE":
        return fbp_effect_is_active(rig, effect_id)
    profile = _fbp_effect_runtime_profile(rig)
    if effect_id not in profile.get("active_ids", ()):
        return False
    if definition.get("kind") == "GEOMETRY":
        modifier = profile.get("geometry_modifiers", {}).get(effect_id)
        if modifier is None:
            modifier = fbp_find_effect_modifier(rig, effect_id)
        return bool(modifier and getattr(modifier, "show_viewport", True))
    nodes = profile.get("shader_nodes", {}).get(effect_id, ())
    if not nodes:
        nodes = _fbp_find_shader_effect_nodes_for_rig(rig, effect_id)
    return bool(nodes) and all(not bool(getattr(node, "mute", False)) for node in nodes)


def fbp_set_effect_visible(rig, effect_id, visible):
    definition = fbp_effect_definition(effect_id)
    visible = bool(visible)
    if definition.get("kind") == "BASE":
        return False
    stored_changed = _fbp_store_effect_visibility(rig, effect_id, visible)
    if definition.get("kind") == "GEOMETRY":
        modifier = fbp_find_effect_modifier(rig, effect_id)
        if not modifier:
            return stored_changed
        changed = stored_changed
        if bool(getattr(modifier, "show_viewport", True)) != visible:
            modifier.show_viewport = visible
            changed = True
        return changed
    nodes = _fbp_find_shader_effect_nodes_for_rig(rig, effect_id)
    if not nodes:
        return stored_changed
    muted = not visible
    changed = stored_changed
    for node in nodes:
        if bool(getattr(node, "mute", False)) != muted:
            node.mute = muted
            changed = True
    return changed


def fbp_effect_render_visible_state(rig, effect_id):
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") == "BASE":
        return True
    if definition.get("kind") == "GEOMETRY":
        profile = _fbp_effect_runtime_profile(rig)
        modifier = profile.get("geometry_modifiers", {}).get(effect_id)
        if modifier is None and effect_id in profile.get("active_ids", ()):
            modifier = fbp_find_effect_modifier(rig, effect_id)
        if modifier is not None:
            return bool(getattr(modifier, "show_render", True))
        return _fbp_stored_effect_render_visibility(rig, effect_id, True)
    return _fbp_stored_effect_render_visibility(rig, effect_id, True)


def fbp_set_effect_render_visible(rig, effect_id, visible):
    definition = fbp_effect_definition(effect_id)
    visible = bool(visible)
    if definition.get("kind") == "BASE":
        return False
    changed = _fbp_store_effect_render_visibility(rig, effect_id, visible)
    if definition.get("kind") == "GEOMETRY":
        modifier = fbp_find_effect_modifier(rig, effect_id)
        if modifier and bool(getattr(modifier, "show_render", True)) != visible:
            modifier.show_render = visible
            changed = True
    return changed


def fbp_effect_render_guard_pre(scene=None):
    """Apply render-only states once and return enough data for a lossless restore."""
    backup = []
    try:
        from .layers import iter_scene_fbp_rigs
        rigs = iter_scene_fbp_rigs(scene or getattr(bpy.context, "scene", None))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        rigs = ()
    for rig in rigs:
        if not bool(getattr(rig, "is_fbp_control", False)):
            continue
        # Render preflight is a correctness boundary: refresh discovery once,
        # which also invalidates stale profile targets after external node or
        # modifier edits, then reuse the rebuilt profile for every effect.
        fbp_effect_ids_for_rig(rig)
        profile = _fbp_effect_runtime_profile(rig)
        for effect_id in profile.get("effect_ids", ()):
            definition = fbp_effect_definition(effect_id)
            if definition.get("kind") == "SHADER":
                render_visible = _fbp_stored_effect_render_visibility(rig, effect_id, True)
                for node in profile.get("shader_nodes", {}).get(effect_id, ()):
                    try:
                        target_mute = not render_visible
                        current_mute = bool(node.mute)
                        if current_mute != target_mute:
                            backup.append(("NODE_MUTE", node, current_mute))
                            node.mute = target_mute
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                        pass
                continue
            contracts = _fbp_quality_contracts(definition)
            if not contracts:
                continue
            modifier = profile.get("geometry_modifiers", {}).get(effect_id)
            node_group = getattr(modifier, "node_group", None) if modifier else None
            if not modifier or not node_group:
                continue
            for contract in contracts:
                socket_name = str(contract.get("socket", ""))
                property_name = str(contract.get("render_property", ""))
                if not socket_name or not property_name:
                    continue
                interface_socket = _fbp_interface_input(node_group, socket_name)
                identifier = str(getattr(interface_socket, "identifier", "") or "")
                if not identifier:
                    continue
                try:
                    old_value = modifier.get(identifier)
                    render_value = _fbp_quality_value(getattr(rig, property_name), contract)
                    if old_value != render_value:
                        backup.append(("MODIFIER_INPUT", modifier, identifier, old_value))
                        modifier[identifier] = render_value
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    continue
    return backup


def fbp_effect_render_guard_post(backup):
    """Restore render-only effect values and return transient failures.

    Reference/shape errors mean the original datablock no longer exists and can
    be discarded. RuntimeError can be temporary while Blender is still releasing
    render-owned data, so those entries remain queued for the idle watchdog.
    """
    retry = []
    for item in list(backup or ()):
        try:
            tag = item[0]
            if tag == "NODE_MUTE":
                _tag, node, muted = item
                node.mute = bool(muted)
            elif tag == "MODIFIER_INPUT":
                _tag, modifier, identifier, value = item
                if value is None:
                    try:
                        del modifier[identifier]
                    except (KeyError, TypeError):
                        pass
                else:
                    modifier[identifier] = value
        except RuntimeError:
            retry.append(item)
        except (AttributeError, ReferenceError, TypeError, ValueError):
            continue
    return retry


def fbp_effect_item_visible_get(rig, effect_id):
    return fbp_effect_visible_state(rig, fbp_normalize_effect_id(effect_id))


def fbp_effect_item_visible_set(rig, effect_id, visible):
    """Property callback used by UIList eye icons, including click-drag paint."""
    effect_id = fbp_normalize_effect_id(effect_id)
    if not rig or not effect_id:
        return False
    rigs = _fbp_selected_rigs(getattr(bpy, "context", None))
    if rig not in rigs:
        rigs = [rig]
    changed = False
    for target in rigs:
        if fbp_effect_is_active(target, effect_id):
            changed = fbp_set_effect_visible(target, effect_id, visible) or changed
    return changed



def _fbp_custom_effect_reserved_socket_names(definition):
    return {
        str(definition.get(key, "") or "")
        for key in (
            "input_socket", "output_socket", "alpha_input_socket",
            "alpha_output_socket", "uv_input_socket",
        )
        if str(definition.get(key, "") or "")
    }


def _fbp_runtime_rna_key(value):
    if value is None:
        return (0, "")
    try:
        return (
            int(value.as_pointer()),
            str(getattr(value, "name_full", getattr(value, "name", "")) or ""),
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return (0, "")


def _fbp_cache_custom_socket_descriptors(cache, key, value):
    if not key or not key[0]:
        return value
    if len(cache) >= 512 and key not in cache:
        for stale_key in tuple(cache)[:128]:
            cache.pop(stale_key, None)
    cache[key] = (time.monotonic(), value)
    return value


def _fbp_custom_geometry_value_sockets(node_group):
    """Return editable modifier inputs using stable interface identifiers.

    The descriptors are cached for a fraction of a second. This keeps socket
    renames responsive while avoiding repeated full interface walks during
    rapid sidebar redraws and slider interaction.
    """
    interface = getattr(node_group, "interface", None) if node_group else None
    if interface is None:
        return []
    try:
        items = interface.items_tree
        item_count = len(items)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return []
    base_key = _fbp_node_group_cache_key(node_group)
    key = (base_key[0], base_key[1], item_count) if base_key else (0, "", item_count)
    cached = _FBP_CUSTOM_GEOMETRY_SOCKET_CACHE.get(key)
    if cached and time.monotonic() - float(cached[0]) <= _FBP_CUSTOM_SOCKET_CACHE_SECONDS:
        return cached[1]

    result = []
    for item in items:
        try:
            if getattr(item, "item_type", "") != "SOCKET":
                continue
            if getattr(item, "in_out", "") != "INPUT":
                continue
            if bool(getattr(item, "hide_in_modifier", False)):
                continue
            socket_type = str(
                getattr(item, "socket_type", "")
                or getattr(item, "bl_socket_idname", "")
                or ""
            )
            if socket_type in {
                "NodeSocketGeometry", "NodeSocketShader", "NodeSocketVirtual",
            }:
                continue
            name = str(getattr(item, "name", "") or "")
            identifier = str(getattr(item, "identifier", "") or "")
            if not name or not identifier:
                continue
            result.append((name, identifier, item))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return _fbp_cache_custom_socket_descriptors(
        _FBP_CUSTOM_GEOMETRY_SOCKET_CACHE, key, result
    )


def _fbp_custom_shader_value_sockets(node, definition):
    reserved = _fbp_custom_effect_reserved_socket_names(definition)
    try:
        input_count = len(node.inputs)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return []
    node_key = _fbp_runtime_rna_key(node)
    group_key = _fbp_node_group_cache_key(getattr(node, "node_tree", None))
    key = (
        node_key[0], node_key[1],
        group_key[0] if group_key else 0,
        group_key[1] if group_key else "",
        input_count,
        tuple(sorted(reserved)),
    )
    cached = _FBP_CUSTOM_SHADER_SOCKET_CACHE.get(key)
    if cached and time.monotonic() - float(cached[0]) <= _FBP_CUSTOM_SOCKET_CACHE_SECONDS:
        return cached[1]

    result = []
    for socket in getattr(node, "inputs", ()):
        try:
            name = str(getattr(socket, "name", "") or "")
            identifier = str(getattr(socket, "identifier", "") or name)
            if not name or name in reserved:
                continue
            if bool(getattr(socket, "hide_value", False)):
                continue
            if not bool(getattr(socket, "enabled", True)):
                continue
            if bool(getattr(socket, "is_linked", False)):
                continue
            if not hasattr(socket, "default_value"):
                continue
            result.append((name, identifier, socket))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return _fbp_cache_custom_socket_descriptors(
        _FBP_CUSTOM_SHADER_SOCKET_CACHE, key, result
    )



def _fbp_capture_custom_effect_inputs(rig, effect_id):
    definition = fbp_effect_definition(effect_id)
    if not bool(definition.get("custom", False)):
        return {}
    if definition.get("kind") == "GEOMETRY":
        modifier = fbp_find_effect_modifier(rig, effect_id)
        node_group = getattr(modifier, "node_group", None) if modifier else None
        if not modifier or not node_group:
            return {}
        values = {}
        for _name, identifier, item in _fbp_custom_geometry_value_sockets(node_group):
            try:
                default = getattr(item, "default_value", None)
                values[identifier] = _fbp_serialize_value(
                    modifier.get(identifier, default)
                )
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        return {"kind": "GEOMETRY", "values": values}

    nodes = _fbp_find_shader_effect_nodes_for_rig(rig, effect_id)
    node = nodes[0] if nodes else None
    if node is None:
        return {}
    values = {}
    for _name, identifier, socket in _fbp_custom_shader_value_sockets(
        node, definition
    ):
        try:
            values[identifier] = _fbp_serialize_value(socket.default_value)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return {"kind": "SHADER", "values": values}


def _fbp_custom_shader_nodes_need_sync(nodes, definition, master_state=None):
    """Return whether material instances differ from the master group node."""
    nodes = list(nodes or ())
    if len(nodes) < 2:
        return False
    values = dict((master_state or {}).get("values", {}) or {})
    if not values:
        for _name, identifier, socket in _fbp_custom_shader_value_sockets(
            nodes[0], definition
        ):
            try:
                values[identifier] = _fbp_serialize_value(socket.default_value)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
    if not values:
        return False
    for node in nodes[1:]:
        sockets = {
            identifier: socket
            for _name, identifier, socket
            in _fbp_custom_shader_value_sockets(node, definition)
        }
        for identifier, serialized in values.items():
            socket = sockets.get(identifier)
            if socket is None:
                continue
            value = _fbp_deserialize_value(serialized)
            if isinstance(value, list):
                value = tuple(value)
            try:
                if not _fbp_effect_values_equal(socket.default_value, value):
                    return True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
    return False


def _fbp_custom_shader_topology_signature(nodes):
    return tuple(_fbp_runtime_rna_key(node) for node in tuple(nodes or ()))


def _fbp_custom_state_signature(state):
    try:
        return json.dumps(state or {}, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(state or {})


def _fbp_schedule_custom_shader_sync(rig, effect_id, nodes, definition):
    """Defer multi-material value propagation outside UI drawing.

    The master socket state is captured once per draw. A short-lived validated
    state cache avoids rescanning every secondary material while no value or
    node topology changed.
    """
    nodes = list(nodes or ())
    state = _fbp_capture_custom_effect_inputs(rig, effect_id)
    if not state:
        return False
    rig_key = fbp_obj_runtime_key(rig)
    if rig_key is None:
        return False
    key = (rig_key, str(effect_id or ""))
    topology = _fbp_custom_shader_topology_signature(nodes)
    state_signature = _fbp_custom_state_signature(state)
    cached = _FBP_CUSTOM_SHADER_SYNC_STATE_CACHE.get(key)
    if (
        cached
        and cached[0] == topology
        and cached[1] == state_signature
        and time.monotonic() - float(cached[2]) <= _FBP_CUSTOM_SHADER_SYNC_CACHE_SECONDS
    ):
        return False
    if not _fbp_custom_shader_nodes_need_sync(
        nodes, definition, master_state=state
    ):
        _FBP_CUSTOM_SHADER_SYNC_STATE_CACHE[key] = (
            topology, state_signature, time.monotonic()
        )
        return False

    rig_name = str(getattr(rig, "name", "") or "")
    try:
        expected_instance = str(effect_instance_id(nodes[0]) or "") if nodes else ""
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        expected_instance = ""
    if not expected_instance:
        return False
    _FBP_CUSTOM_SHADER_SYNC_PENDING[key] = (
        rig_name, expected_instance, state, topology, state_signature
    )

    def _sync_latest():
        payload = _FBP_CUSTOM_SHADER_SYNC_PENDING.pop(key, None)
        if not payload:
            return None
        (
            stored_name, stored_instance, latest_state,
            _stored_topology, latest_signature,
        ) = payload
        target_rig = bpy.data.objects.get(stored_name) if stored_name else None
        if target_rig is None or fbp_obj_runtime_key(target_rig) != rig_key:
            target_rig = next(
                (obj for obj in bpy.data.objects if fbp_obj_runtime_key(obj) == rig_key),
                None,
            )
        if target_rig is not None:
            current_nodes = _fbp_find_shader_effect_nodes_for_rig(target_rig, effect_id)
            try:
                current_instance = (
                    str(effect_instance_id(current_nodes[0]) or "")
                    if current_nodes else ""
                )
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                current_instance = ""
            if current_instance == stored_instance:
                _fbp_apply_custom_effect_inputs(
                    target_rig, effect_id, latest_state
                )
                _FBP_CUSTOM_SHADER_SYNC_STATE_CACHE[key] = (
                    _fbp_custom_shader_topology_signature(current_nodes),
                    latest_signature,
                    time.monotonic(),
                )
        return None

    try:
        from .safe_tasks import schedule_once
        return schedule_once(
            f"fbp_custom_shader_sync:{key[0]}:{key[1]}",
            _sync_latest,
            first_interval=0.03,
        )
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        _FBP_CUSTOM_SHADER_SYNC_PENDING.pop(key, None)
        return False


def _fbp_apply_custom_effect_inputs(rig, effect_id, state):
    definition = fbp_effect_definition(effect_id)
    values = dict((state or {}).get("values", {}) or {})
    if not bool(definition.get("custom", False)) or not values:
        return False
    changed = False
    if definition.get("kind") == "GEOMETRY":
        modifier = fbp_find_effect_modifier(rig, effect_id)
        node_group = getattr(modifier, "node_group", None) if modifier else None
        if not modifier or not node_group:
            return False
        by_identifier = {
            identifier: item
            for _name, identifier, item
            in _fbp_custom_geometry_value_sockets(node_group)
        }
        for identifier, serialized in values.items():
            if identifier not in by_identifier:
                continue
            value = _fbp_deserialize_value(serialized)
            try:
                current = modifier.get(identifier)
                if _fbp_effect_values_equal(current, value):
                    continue
                modifier[identifier] = value
                changed = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        return changed

    for node in _fbp_find_shader_effect_nodes_for_rig(rig, effect_id):
        sockets = {
            identifier: socket
            for _name, identifier, socket
            in _fbp_custom_shader_value_sockets(node, definition)
        }
        for identifier, serialized in values.items():
            socket = sockets.get(identifier)
            if socket is None:
                continue
            value = _fbp_deserialize_value(serialized)
            try:
                if isinstance(value, list):
                    value = tuple(value)
                if _fbp_effect_values_equal(socket.default_value, value):
                    continue
                socket.default_value = value
                changed = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
    return changed


def _fbp_reset_custom_effect_inputs(rig, effect_id):
    definition = fbp_effect_definition(effect_id)
    group = find_custom_effect_group(effect_id)
    if not bool(definition.get("custom", False)) or group is None:
        return False
    changed = False
    if definition.get("kind") == "GEOMETRY":
        modifier = fbp_find_effect_modifier(rig, effect_id)
        if modifier is None:
            return False
        for _name, identifier, item in _fbp_custom_geometry_value_sockets(group):
            try:
                value = getattr(item, "default_value", None)
                if value is None or _fbp_effect_values_equal(
                    modifier.get(identifier), value
                ):
                    continue
                modifier[identifier] = value
                changed = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        return changed

    defaults = {
        str(getattr(item, "identifier", "") or getattr(item, "name", "") or ""):
            getattr(item, "default_value", None)
        for item in getattr(getattr(group, "interface", None), "items_tree", ())
        if getattr(item, "item_type", "") == "SOCKET"
        and getattr(item, "in_out", "") == "INPUT"
        and hasattr(item, "default_value")
    }
    for node in _fbp_find_shader_effect_nodes_for_rig(rig, effect_id):
        for _name, identifier, socket in _fbp_custom_shader_value_sockets(
            node, definition
        ):
            if identifier not in defaults or defaults[identifier] is None:
                continue
            value = defaults[identifier]
            try:
                if _fbp_effect_values_equal(socket.default_value, value):
                    continue
                socket.default_value = value
                changed = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
    return changed


def _fbp_custom_geometry_missing_defaults(modifier, node_group):
    """Return serializable defaults that are not initialized on the modifier."""
    if not modifier or not node_group:
        return {}
    missing = {}
    for _name, identifier, item in _fbp_custom_geometry_value_sockets(node_group):
        try:
            if identifier in modifier:
                continue
            default = getattr(item, "default_value", None)
            if default is not None:
                missing[identifier] = _fbp_serialize_value(default)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return missing


def _fbp_initialize_custom_geometry_inputs(modifier, node_group):
    """Initialize missing custom GN inputs from their interface defaults.

    Call this only from operators, deferred safe tasks or other mutation-safe
    paths. UI draw callbacks must remain read-only.
    """
    changed = False
    for identifier, serialized in _fbp_custom_geometry_missing_defaults(
        modifier, node_group
    ).items():
        try:
            modifier[identifier] = _fbp_deserialize_value(serialized)
            changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return changed


def _fbp_schedule_custom_geometry_init(rig, effect_id, modifier, node_group):
    """Repair newly exposed GN sockets outside panel drawing and Undo teardown."""
    defaults = _fbp_custom_geometry_missing_defaults(modifier, node_group)
    if not defaults:
        return False
    rig_key = fbp_obj_runtime_key(rig)
    if rig_key is None:
        return False
    rig_name = str(getattr(rig, "name", "") or "")
    try:
        expected_instance = str(effect_instance_id(modifier) or "")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        expected_instance = ""
    if not expected_instance:
        return False
    key = (rig_key, str(effect_id or ""))
    _FBP_CUSTOM_GEOMETRY_INIT_PENDING[key] = (
        rig_name, expected_instance, defaults
    )

    def _initialize_latest():
        payload = _FBP_CUSTOM_GEOMETRY_INIT_PENDING.pop(key, None)
        if not payload:
            return None
        stored_name, stored_instance, latest_defaults = payload
        target_rig = bpy.data.objects.get(stored_name) if stored_name else None
        if target_rig is None or fbp_obj_runtime_key(target_rig) != rig_key:
            target_rig = next(
                (obj for obj in bpy.data.objects if fbp_obj_runtime_key(obj) == rig_key),
                None,
            )
        target_modifier = (
            fbp_find_effect_modifier(target_rig, effect_id)
            if target_rig is not None else None
        )
        target_group = (
            getattr(target_modifier, "node_group", None)
            if target_modifier is not None else None
        )
        try:
            current_instance = (
                str(effect_instance_id(target_modifier) or "")
                if target_modifier is not None else ""
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            current_instance = ""
        if (
            target_modifier is not None
            and target_group is not None
            and current_instance == stored_instance
        ):
            for identifier, serialized in latest_defaults.items():
                try:
                    if identifier not in target_modifier:
                        target_modifier[identifier] = _fbp_deserialize_value(serialized)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    continue
            try:
                from .core import fbp_tag_view3d_ui_redraw
                fbp_tag_view3d_ui_redraw()
            except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
                pass
        return None

    try:
        from .safe_tasks import schedule_once
        return schedule_once(
            f"fbp_custom_geometry_init:{key[0]}:{key[1]}",
            _initialize_latest,
            first_interval=0.03,
        )
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        _FBP_CUSTOM_GEOMETRY_INIT_PENDING.pop(key, None)
        return False


def _fbp_draw_custom_effect_inputs(layout, rig, effect_id):
    group = find_custom_effect_group(effect_id)
    live_definition = None
    if group is not None:
        live_definition = refresh_one_custom_effect_definition(
            FBP_EFFECT_REGISTRY, effect_id, FBP_EFFECT_SCHEMA_VERSION
        )
        if live_definition:
            finalize_effect_registry({effect_id: live_definition})
    definition = live_definition or fbp_effect_definition(effect_id)
    metadata = layout.box()
    metadata.label(
        text=str(
            getattr(group, "name", "Missing Node Group")
            if group else "Missing Node Group"
        ),
        icon="NODETREE" if group else "ERROR",
    )
    if bool(definition.get("custom_invalid", False)):
        warning = metadata.row()
        warning.alert = True
        warning.label(
            text=str(
                definition.get("custom_error", "Invalid custom node interface")
                or "Invalid custom node interface"
            ),
            icon="ERROR",
        )
        metadata.label(
            text="Fix the node-group interface, then edit or re-register the effect",
            icon="INFO",
        )
    edit_nodes = metadata.operator(
        "fbp.edit_custom_node_effect_nodes",
        text="Edit Nodes",
        icon="NODETREE",
    )
    edit_nodes.effect_id = effect_id
    row = metadata.row(align=True)
    edit = row.operator(
        "fbp.register_custom_node_effect",
        text="Edit Name & Icon",
        icon="GREASEPENCIL",
    )
    edit.effect_id = effect_id
    hide = row.operator(
        "fbp.hide_custom_node_effect",
        text="Hide from Library",
        icon="HIDE_ON",
    )
    hide.effect_id = effect_id

    if bool(definition.get("custom_invalid", False)):
        return 0

    controls = layout.box()
    controls.label(text="Node Group Inputs", icon="OPTIONS")
    drawn = 0
    if definition.get("kind") == "GEOMETRY":
        modifier = fbp_find_effect_modifier(rig, effect_id)
        node_group = getattr(modifier, "node_group", None) if modifier else None
        if modifier and node_group:
            for name, identifier, _item in _fbp_custom_geometry_value_sockets(
                node_group
            ):
                try:
                    if identifier in modifier:
                        controls.prop(
                            modifier,
                            f'["{identifier}"]',
                            text=name,
                        )
                        drawn += 1
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    continue
            _fbp_schedule_custom_geometry_init(
                rig, effect_id, modifier, node_group
            )
    else:
        nodes = _fbp_find_shader_effect_nodes_for_rig(rig, effect_id)
        node = nodes[0] if nodes else None
        if node:
            _fbp_schedule_custom_shader_sync(
                rig, effect_id, nodes, definition
            )
            for name, _identifier, socket in _fbp_custom_shader_value_sockets(
                node, definition
            ):
                try:
                    controls.prop(socket, "default_value", text=name)
                    drawn += 1
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    continue
    if not drawn:
        controls.label(text="No editable value sockets exposed", icon="INFO")
    return drawn


def fbp_draw_effect_settings(layout, rig, effect_id, selected_count=1, present_count=None):
    definition = fbp_effect_definition(effect_id)
    if not definition:
        return
    box = layout.box()
    header = box.row(align=False)
    header.label(text=str(definition.get("label", effect_id)), icon=str(definition.get("icon", "MODIFIER")))
    order_warning = fbp_effect_order_warning(rig, effect_id)
    warning_messages = []
    if order_warning:
        warning_messages.append(order_warning)
    if str(definition.get("performance", "")).upper() in {"HEAVY", "VERY_HEAVY"}:
        warning_messages.append("Heavy effect: may reduce viewport playback performance")
    if warning_messages:
        warning = header.row(align=True)
        warning.alert = True
        op = warning.operator("fbp.effect_header_warning", text="", icon="ERROR", emboss=False)
        op.effect_id = effect_id
        op.message = "\n".join(warning_messages)
        op.fix_order = bool(order_warning)
    preset_menu = header.operator("wm.call_menu", text="", icon="PRESET")
    preset_menu.name = "FBP_MT_effect_presets"
    actions_menu = header.operator("wm.call_menu", text="", icon="DOWNARROW_HLT")
    actions_menu.name = "FBP_MT_effect_stack_actions"
    if definition.get("supports_input_source"):
        current_source = fbp_effect_input_source(rig, effect_id)
        source_row = box.row(align=True)
        source_row.label(text="Input", icon="NODETREE")
        for source, label in (
            ("PREVIOUS", "Previous"),
            ("ORIGINAL", "Original"),
            ("FINAL", "Final Material"),
        ):
            op = source_row.operator(
                "fbp.set_effect_input_source", text=label,
                depress=current_source == source,
            )
            op.effect_id = effect_id
            op.source = source
        if current_source == "FINAL":
            hint = box.row()
            hint.label(
                text="Final Material evaluates after the regular color stack",
                icon="INFO",
            )
    debug_modes = tuple(definition.get("debug_modes", ()))
    if debug_modes:
        current_debug = fbp_effect_debug_mode(rig, effect_id)
        debug_row = box.row(align=True)
        debug_row.label(text="Preview", icon="HIDE_OFF")
        for mode, label in debug_modes:
            op = debug_row.operator(
                "fbp.set_effect_debug_mode", text=label,
                depress=current_debug == mode,
            )
            op.effect_id = effect_id
            op.mode = mode
    if bool(definition.get("custom", False)):
        _fbp_draw_custom_effect_inputs(box, rig, effect_id)
        if int(selected_count or 1) > 1:
            copy_row = box.row(align=True)
            copy_row.label(text="Socket edits affect the active layer", icon="INFO")
            copy = copy_row.operator(
                "fbp.copy_custom_effect_values_to_selected",
                text="Copy Values to Selected",
                icon="PASTEDOWN",
            )
            copy.effect_id = effect_id
        return
    labels = {
        "fbp_mesh_wiggle_shade_smooth": "Shade Smooth",
        "fbp_mesh_wiggle_strength": "Strength",
        "fbp_mesh_wiggle_speed": "Speed",
        "fbp_mesh_wiggle_hold": "Stepped",
        "fbp_mesh_wiggle_w": "W",
        "fbp_mesh_wiggle_noise_scale": "Noise Scale",
        "fbp_mesh_wiggle_detail": "Noise Detail",
        "fbp_mesh_wiggle_subdivisions": "Subdivision",
        "fbp_stop_motion_resolution": "Resolution",
        "fbp_stop_motion_strength": "Strength",
        "fbp_stop_motion_step_frames": "Step Frames",
        "fbp_wind_subdivision": "Subdivision",
        "fbp_wind_bend_amount": "Bend Amount",
        "fbp_wind_speed": "Wind Speed",
        "fbp_wind_stepped": "Stepped",
        "fbp_wind_pin_edge": "Pin Edge",
        "fbp_wind_motion_mode": "Motion Mode",
        "fbp_wind_wave_count": "Wave Count",
        "fbp_wind_wave_amplitude": "Wave Amplitude",
        "fbp_wind_wave_speed": "Wave Speed",
        "fbp_wind_phase": "Phase",
        "fbp_wind_turbulence": "Turbulence",
        "fbp_wind_falloff": "Pinned Falloff",
        "fbp_wind_noise_scale": "Noise Scale",
        "fbp_wind_gust_strength": "Gust Strength",
        "fbp_wind_direction_space": "Direction Space",
        "fbp_wind_direction": "Wind Direction",
        "fbp_wind_preview_falloff": "Preview Falloff",
        "fbp_wind_reverse": "Reverse Direction",
        "fbp_mesh_ripple_viewport_subdivision": "Viewport",
        "fbp_mesh_ripple_playback_subdivision": "Playback",
        "fbp_mesh_ripple_render_subdivision": "Render",
        "fbp_mesh_ripple_direction": "Direction",
        "fbp_mesh_ripple_amplitude": "Amplitude",
        "fbp_mesh_ripple_frequency": "Frequency",
        "fbp_mesh_ripple_speed": "Speed",
        "fbp_mesh_ripple_phase": "Phase",
        "fbp_mesh_ripple_stepped": "Stepped",
        "fbp_mesh_ripple_pin_borders": "Pin Borders",
        "fbp_mesh_ripple_border_falloff": "Border Falloff",
        "fbp_paper_curl_viewport_subdivision": "Viewport",
        "fbp_paper_curl_playback_subdivision": "Playback",
        "fbp_paper_curl_render_subdivision": "Render",
        "fbp_paper_curl_edge": "Edge",
        "fbp_paper_curl_progress": "Progress",
        "fbp_paper_curl_angle": "Curl Angle",
        "fbp_paper_curl_radius": "Curl Radius",
        "fbp_paper_curl_width": "Curl Width",
        "fbp_paper_curl_lift": "Lift",
        "fbp_paper_curl_reverse": "Reverse",
        "fbp_camera_scale_lock_reference_distance": "Reference Distance",
        "fbp_camera_scale_lock_reference_lens": "Reference Lens",
        "fbp_camera_scale_lock_reference_sensor_width": "Reference Sensor Width",
        "fbp_camera_scale_lock_influence": "Influence",
        "fbp_thickness_amount": "Thickness",
        "fbp_thickness_alpha_threshold": "Alpha Threshold",
        "fbp_thickness_alpha_resolution": "Alpha Resolution",
        "fbp_infinite_rotation_speed": "Speed",
        "fbp_infinite_rotation_direction": "Direction",
        "fbp_infinite_rotation_stepped": "Stepped",
        "fbp_infinite_rotation_offset": "Offset (°)",
        "fbp_felt_render_density": "Render Density",
        "fbp_felt_viewport_percentage": "Viewport %",
        "fbp_felt_fuzz_length": "Fuzz Length",
        "fbp_felt_subdivisions": "Subdivisions",
        "fbp_felt_fuzz_radius": "Fuzz Radius",
        "fbp_felt_curl_amount": "Curl Amount",
        "fbp_felt_seed": "Seed",
        "fbp_felt_alpha_threshold": "Alpha Threshold",
        "fbp_felt_alpha_resolution": "Alpha Resolution",
        "fbp_uv_distortion_scale": "Noise Scale",
        "fbp_uv_distortion_amount": "Distortion Amount",
        "fbp_pixelate_resolution": "Pixel Density",
        "fbp_solid_mask_color": "Mask Color",
        "fbp_solid_mask_factor": "Mask Factor",
        "fbp_hue_saturation_hue": "Hue",
        "fbp_hue_saturation_saturation": "Saturation",
        "fbp_hue_saturation_value": "Value",
        "fbp_brightness_contrast_brightness": "Brightness",
        "fbp_brightness_contrast_contrast": "Contrast",
        "fbp_invert_factor": "Factor",
        "fbp_threshold_value": "Threshold",
        "fbp_color_isolate_target": "Target Color",
        "fbp_color_isolate_tolerance": "Tolerance",
        "fbp_color_isolate_falloff": "Falloff",
        "fbp_duotone_shadows": "Shadows Tone",
        "fbp_duotone_highlights": "Highlights Tone",
        "fbp_grain_strength": "Intensity",
        "fbp_grain_scale": "Grain Scale",
        "fbp_grain_seed": "Animate (W)",
        "fbp_digital_noise_luma": "Luminance Noise",
        "fbp_digital_noise_chroma": "Chroma Noise",
        "fbp_digital_noise_scale": "Noise Scale",
        "fbp_digital_noise_shadow_bias": "Shadow Bias",
        "fbp_digital_noise_seed": "Animate (W)",
        "fbp_chroma_key_color": "Key Color",
        "fbp_chroma_key_tolerance": "Tolerance",
        "fbp_chroma_key_softness": "Softness",
        "fbp_chroma_key_despill": "Despill",
        "fbp_chroma_key_invert": "Invert",
        "fbp_halftone_scale": "Cell Scale",
        "fbp_halftone_dot_size": "Dot Size",
        "fbp_halftone_rotation": "Rotation",
        "fbp_halftone_contrast": "Contrast",
        "fbp_halftone_invert": "Invert",
        "fbp_halftone_shape": "Shape",
        "fbp_halftone_use_source_color": "Use Source Color",
        "fbp_halftone_foreground": "Ink Color",
        "fbp_halftone_background": "Background",
        "fbp_halftone_transparent_background": "Transparent Background",
        "fbp_dot_matrix_scale": "Cell Scale",
        "fbp_dot_matrix_dot_size": "Dot Size",
        "fbp_dot_matrix_spacing": "Spacing",
        "fbp_dot_matrix_contrast": "Contrast",
        "fbp_dot_matrix_response": "Brightness Response",
        "fbp_dot_matrix_invert": "Invert",
        "fbp_dot_matrix_random_size": "Random Size",
        "fbp_dot_matrix_random_brightness": "Random Brightness",
        "fbp_dot_matrix_seed": "Seed",
        "fbp_dot_matrix_glow": "Glow",
        "fbp_dot_matrix_use_source_color": "Use Source Color",
        "fbp_dot_matrix_foreground": "Text / Dot Color",
        "fbp_dot_matrix_background": "Background Color",
        "fbp_dot_matrix_transparent_background": "Transparent Background",
        "fbp_dot_matrix_shape": "Shape",
        "fbp_dot_matrix_min_size": "Minimum Size",
        "fbp_dot_matrix_max_size": "Maximum Size",
        "fbp_dot_matrix_dead_pixels": "Dead Pixels",
        "fbp_dot_matrix_flicker": "Flicker",
        "fbp_ascii_scale": "Cell Scale",
        "fbp_ascii_contrast": "Contrast",
        "fbp_ascii_invert": "Invert",
        "fbp_ascii_colorize": "Use Source Color",
        "fbp_ascii_foreground": "Foreground",
        "fbp_ascii_background": "Background",
        "fbp_ascii_variation": "Variation",
        "fbp_ascii_random_seed": "Seed",
        "fbp_ascii_transparent_background": "Transparent Background",
        "fbp_ascii_edge_boost": "Edge Boost",
        "fbp_ascii_dither": "Dither",
        "fbp_text_matrix_quality": "Quality",
        "fbp_text_matrix_viewport_columns": "Viewport Columns",
        "fbp_text_matrix_viewport_rows": "Viewport Rows",
        "fbp_text_matrix_render_columns": "Render Columns",
        "fbp_text_matrix_render_rows": "Render Rows",
        "fbp_text_matrix_playback_rows": "Playback Rows",
        "fbp_paper_fiber_scale": "Fiber Scale",
        "fbp_paper_fiber_intensity": "Intensity",
        "fbp_paper_fiber_phase": "Animate (W)",
        "fbp_gradient_light_angle": "Light Angle",
        "fbp_gradient_shadow_position": "Shadow Position",
        "fbp_gradient_softness": "Softness",
        "fbp_gradient_shadow_color": "Shadow Color",
        "fbp_gobo_pattern_scale": "Pattern Scale",
        "fbp_gobo_rotation": "Rotation Angle",
        "fbp_gobo_sharpness": "Sharpness",
        "fbp_crt_line_count": "Line Count",
        "fbp_crt_opacity": "Opacity",
        "fbp_vignette_radius": "Radius",
        "fbp_vignette_smoothness": "Smoothness",
        "fbp_vignette_strength": "Strength",
        "fbp_posterize_steps": "Color Steps",
    }
    property_map = dict(definition.get("property_map", {}))
    if effect_id == FBP_EFFECT_CAMERA_BILLBOARD:
        box.prop(rig, "fbp_camera_billboard_mode", text="Facing Mode")
        row = box.row(align=True)
        row.prop(rig, "fbp_camera_billboard_flip", text="Flip", toggle=True)
        row.prop(rig, "fbp_camera_billboard_offset", text="Camera Offset")
        camera = _fbp_scene_camera(getattr(bpy.context, "scene", None))
        if not camera:
            box.label(text="Set an active scene camera to use this effect", icon="ERROR")
        box.label(text="Rotates generated geometry only; rig transforms remain untouched", icon="CONSTRAINT")
    elif effect_id == FBP_EFFECT_CAMERA_SCALE_LOCK:
        box.prop(rig, "fbp_camera_scale_lock_influence", text="Influence", slider=True)
        row = box.row(align=True)
        row.prop(rig, "fbp_camera_scale_lock_reference_distance", text="Reference Distance")
        row.operator("fbp.capture_camera_scale_reference", text="", icon="EYEDROPPER")
        projection = box.row(align=True)
        projection.prop(rig, "fbp_camera_scale_lock_reference_lens", text="Reference Lens")
        projection.prop(rig, "fbp_camera_scale_lock_reference_sensor_width", text="Sensor")
        camera = _fbp_scene_camera(getattr(bpy.context, "scene", None))
        if not camera:
            box.label(text="Set an active scene camera to use this effect", icon="ERROR")
        elif str(getattr(getattr(camera, "data", None), "type", "") or "") != "PERSP":
            box.label(text="Orthographic cameras leave the scale unchanged", icon="INFO")
        box.label(text="The reference is captured automatically when the effect is added", icon="CAMERA_DATA")
    elif effect_id == FBP_EFFECT_EXTRUDED_CUTOUT:
        quality = box.box()
        quality.label(text="Alpha Detail", icon="IMAGE_ALPHA")
        row = quality.row(align=True)
        row.prop(rig, "fbp_extruded_cutout_viewport_resolution", text="Viewport")
        row.prop(rig, "fbp_extruded_cutout_playback_resolution", text="Playback")
        row.prop(rig, "fbp_extruded_cutout_render_resolution", text="Render")
        row = box.row(align=True)
        row.prop(rig, "fbp_extruded_cutout_thickness", text="Thickness")
        row.prop(rig, "fbp_extruded_cutout_direction", text="Direction")
        materials = box.box()
        materials.label(text="Sides and Back", icon="MATERIAL")
        materials.prop(rig, "fbp_extruded_cutout_side_material", text="Material Override")
        if getattr(rig, "fbp_extruded_cutout_side_material", None) is None:
            materials.prop(rig, "fbp_extruded_cutout_side_color", text="Color")
        box.prop(rig, "fbp_extruded_cutout_alpha_threshold", text="Alpha Threshold", slider=True)
        box.label(text="The original animated plane remains the front surface", icon="IMAGE_ALPHA")
        if int(getattr(rig, "fbp_extruded_cutout_viewport_resolution", 0) or 0) >= 7:
            warning = box.row()
            warning.alert = True
            warning.label(text="High alpha detail may slow interaction", icon="ERROR")
    elif effect_id == FBP_EFFECT_CUTOUT_OUTLINE:
        quality = box.box()
        quality.label(text="Alpha Detail", icon="IMAGE_ALPHA")
        row = quality.row(align=True)
        row.prop(rig, "fbp_cutout_outline_viewport_resolution", text="Viewport")
        row.prop(rig, "fbp_cutout_outline_playback_resolution", text="Playback")
        row.prop(rig, "fbp_cutout_outline_render_resolution", text="Render")
        row = box.row(align=True)
        row.prop(rig, "fbp_cutout_outline_width", text="Width")
        row.prop(rig, "fbp_cutout_outline_offset", text="Offset")
        box.prop(rig, "fbp_cutout_outline_color", text="Outline Color")
        box.prop(rig, "fbp_cutout_outline_alpha_threshold", text="Alpha Threshold", slider=True)
        box.label(text="The animated image alpha defines the outline", icon="IMAGE_ALPHA")
        detail = int(getattr(rig, "fbp_cutout_outline_viewport_resolution", 0) or 0)
        if detail >= 7:
            warning = box.row()
            warning.alert = True
            warning.label(text="High alpha detail may slow interaction", icon="ERROR")
    elif effect_id == FBP_EFFECT_PAPER_CURL:
        quality = box.box()
        quality.label(text="Geometry Quality", icon="MOD_SUBSURF")
        row = quality.row(align=True)
        row.prop(rig, "fbp_paper_curl_viewport_subdivision", text="Viewport")
        row.prop(rig, "fbp_paper_curl_playback_subdivision", text="Playback")
        row.prop(rig, "fbp_paper_curl_render_subdivision", text="Render")
        box.prop(rig, "fbp_paper_curl_edge", text="Curl Edge")
        box.prop(rig, "fbp_paper_curl_progress", text="Progress", slider=True)
        row = box.row(align=True)
        row.prop(rig, "fbp_paper_curl_angle", text="Angle")
        row.prop(rig, "fbp_paper_curl_radius", text="Radius")
        row = box.row(align=True)
        row.prop(rig, "fbp_paper_curl_width", text="Width", slider=True)
        row.prop(rig, "fbp_paper_curl_lift", text="Lift")
        box.prop(rig, "fbp_paper_curl_reverse", text="Reverse Curl", toggle=True)
        if int(getattr(rig, "fbp_paper_curl_viewport_subdivision", 0) or 0) >= 6:
            warning = box.row()
            warning.alert = True
            warning.label(text="High viewport subdivisions may slow interaction", icon="ERROR")
    elif effect_id == FBP_EFFECT_MESH_RIPPLE:
        quality = box.box()
        quality.label(text="Geometry Quality", icon="MOD_SUBSURF")
        row = quality.row(align=True)
        row.prop(rig, "fbp_mesh_ripple_viewport_subdivision", text="Viewport")
        row.prop(rig, "fbp_mesh_ripple_playback_subdivision", text="Playback")
        row.prop(rig, "fbp_mesh_ripple_render_subdivision", text="Render")
        box.prop(rig, "fbp_mesh_ripple_direction", text="Direction")
        row = box.row(align=True)
        row.prop(rig, "fbp_mesh_ripple_amplitude", text="Amplitude")
        row.prop(rig, "fbp_mesh_ripple_frequency", text="Frequency")
        row = box.row(align=True)
        row.prop(rig, "fbp_mesh_ripple_speed", text="Speed")
        row.prop(rig, "fbp_mesh_ripple_phase", text="Phase")
        box.prop(rig, "fbp_mesh_ripple_stepped", text="Stepped")
        box.prop(rig, "fbp_mesh_ripple_pin_borders", text="Pin Borders", slider=True)
        if float(getattr(rig, "fbp_mesh_ripple_pin_borders", 0.0) or 0.0) > 0.0:
            box.prop(rig, "fbp_mesh_ripple_border_falloff", text="Border Falloff", slider=True)
        if int(getattr(rig, "fbp_mesh_ripple_viewport_subdivision", 0) or 0) >= 6:
            warning = box.row()
            warning.alert = True
            warning.label(text="High viewport subdivisions may slow playback", icon="ERROR")
    elif effect_id == FBP_EFFECT_WIND_BENDER:
        for prop_name in ("fbp_wind_subdivision", "fbp_wind_pin_edge", "fbp_wind_motion_mode"):
            if hasattr(rig, prop_name):
                box.prop(rig, prop_name, text=labels.get(prop_name, prop_name))
        motion_mode = str(getattr(rig, "fbp_wind_motion_mode", "SWAY") or "SWAY")
        motion = box.box()
        motion.label(
            text="Sway Motion" if motion_mode == "SWAY" else "Flowing Waves",
            icon="FORCE_WIND",
        )
        motion_props = (
            ("fbp_wind_bend_amount", "fbp_wind_speed")
            if motion_mode == "SWAY"
            else ("fbp_wind_wave_count", "fbp_wind_wave_amplitude", "fbp_wind_wave_speed")
        )
        for prop_name in motion_props:
            if hasattr(rig, prop_name):
                motion.prop(rig, prop_name, text=labels.get(prop_name, prop_name))
        direction = box.row(align=True)
        direction.prop(rig, "fbp_wind_direction_space", text="Direction Space")
        direction.prop(rig, "fbp_wind_preview_falloff", text="", toggle=True, icon="HIDE_OFF")
        box.prop(rig, "fbp_wind_direction", text="Wind Direction")
        for prop_name in (
            "fbp_wind_stepped", "fbp_wind_phase", "fbp_wind_falloff",
            "fbp_wind_noise_scale", "fbp_wind_turbulence",
            "fbp_wind_gust_strength", "fbp_wind_reverse",
        ):
            if hasattr(rig, prop_name):
                box.prop(rig, prop_name, text=labels.get(prop_name, prop_name))
        if int(getattr(rig, "fbp_wind_subdivision", 0) or 0) >= 5:
            warning = box.row()
            warning.alert = True
            warning.label(text="High subdivisions may slow viewport playback", icon="ERROR")
    else:
        contextual = {
            FBP_EFFECT_HALFTONE,
            FBP_EFFECT_DOT_MATRIX,
            FBP_EFFECT_ASCII_MATRIX,
            FBP_EFFECT_TEXT_MATRIX,
        }
        if effect_id not in contextual:
            for prop_name in property_map:
                # Felt Fuzz draws Seed with its adjacent Evolve clock below.
                if effect_id == FBP_EFFECT_FELT_FUZZ and prop_name == "fbp_felt_seed":
                    continue
                if hasattr(rig, prop_name):
                    box.prop(rig, prop_name, text=labels.get(prop_name, prop_name))
    if effect_id == FBP_EFFECT_PIXELATE:
        box.prop(rig, "fbp_pixelate_square_pixels", text="Square Pixels", toggle=True)
    if effect_id == FBP_EFFECT_HALFTONE:
        box.prop(rig, "fbp_halftone_shape", text="Shape")
        row = box.row(align=True)
        row.prop(rig, "fbp_halftone_scale", text="Cell Scale")
        row.prop(rig, "fbp_halftone_dot_size", text="Dot Size")
        row = box.row(align=True)
        row.prop(rig, "fbp_halftone_rotation", text="Rotation")
        row.prop(rig, "fbp_halftone_contrast", text="Contrast")
        box.prop(rig, "fbp_halftone_invert", text="Invert", toggle=True)
        box.prop(rig, "fbp_halftone_use_source_color", text="Use Source Color", toggle=True)
        if not bool(getattr(rig, "fbp_halftone_use_source_color", True)):
            box.prop(rig, "fbp_halftone_foreground", text="Ink Color")
        box.prop(rig, "fbp_halftone_transparent_background", text="Transparent Background", toggle=True)
        if not bool(getattr(rig, "fbp_halftone_transparent_background", False)):
            box.prop(rig, "fbp_halftone_background", text="Background")
    if effect_id == FBP_EFFECT_DOT_MATRIX:
        box.prop(rig, "fbp_dot_matrix_shape", text="Shape")
        box.prop(rig, "fbp_dot_matrix_scale", text="Cell Scale")
        row = box.row(align=True)
        row.prop(rig, "fbp_dot_matrix_dot_size", text="Dot Size")
        row.prop(rig, "fbp_dot_matrix_spacing", text="Spacing")
        row = box.row(align=True)
        row.prop(rig, "fbp_dot_matrix_min_size", text="Minimum")
        row.prop(rig, "fbp_dot_matrix_max_size", text="Maximum")
        row = box.row(align=True)
        row.prop(rig, "fbp_dot_matrix_contrast", text="Contrast")
        row.prop(rig, "fbp_dot_matrix_response", text="Response")
        box.prop(rig, "fbp_dot_matrix_invert", text="Invert", toggle=True)
        row = box.row(align=True)
        row.prop(rig, "fbp_dot_matrix_random_size", text="Random Size")
        row.prop(rig, "fbp_dot_matrix_random_brightness", text="Random Brightness")
        row = box.row(align=True)
        row.prop(rig, "fbp_dot_matrix_dead_pixels", text="Dead Pixels")
        row.prop(rig, "fbp_dot_matrix_flicker", text="Flicker")
        box.prop(rig, "fbp_dot_matrix_glow", text="Glow")
        box.prop(rig, "fbp_dot_matrix_use_source_color", text="Use Source Color", toggle=True)
        if not bool(getattr(rig, "fbp_dot_matrix_use_source_color", True)):
            box.prop(rig, "fbp_dot_matrix_foreground", text="Dot Color")
        box.prop(rig, "fbp_dot_matrix_transparent_background", text="Transparent Background", toggle=True)
        if not bool(getattr(rig, "fbp_dot_matrix_transparent_background", True)):
            box.prop(rig, "fbp_dot_matrix_background", text="Background Color")
        box.prop(rig, "fbp_dot_matrix_seed", text="Pattern Seed")
    if effect_id == FBP_EFFECT_ASCII_MATRIX:
        box.prop(rig, "fbp_ascii_charset", text="Character Set")
        box.prop(rig, "fbp_ascii_character_count", text="Character Count", slider=True)
        row = box.row(align=True)
        row.prop(rig, "fbp_ascii_scale", text="Cell Scale")
        row.prop(rig, "fbp_ascii_contrast", text="Contrast")
        box.prop(rig, "fbp_ascii_invert", text="Invert", toggle=True)
        box.prop(rig, "fbp_ascii_variation", text="Character Variation")
        row = box.row(align=True)
        row.prop(rig, "fbp_ascii_edge_boost", text="Edge Boost")
        row.prop(rig, "fbp_ascii_dither", text="Dither")
        box.prop(rig, "fbp_ascii_colorize", text="Use Source Color", toggle=True)
        if not bool(getattr(rig, "fbp_ascii_colorize", False)):
            box.prop(rig, "fbp_ascii_foreground", text="Text Color")
        box.prop(rig, "fbp_ascii_transparent_background", text="Transparent Background", toggle=True)
        if not bool(getattr(rig, "fbp_ascii_transparent_background", True)):
            box.prop(rig, "fbp_ascii_background", text="Background Color")
        box.prop(rig, "fbp_ascii_random_seed", text="Character Seed")
    if effect_id == FBP_EFFECT_TEXT_MATRIX:
        box.prop(rig, "fbp_text_matrix_charset", text="Character Set")
        if str(getattr(rig, "fbp_text_matrix_charset", "")) == "CUSTOM":
            box.prop(rig, "fbp_text_matrix_custom_charset", text="Characters")
        box.prop(rig, "fbp_text_matrix_font", text="Font")
        box.prop(rig, "fbp_text_matrix_quality", text="Quality")
        box.label(text="Viewport Grid")
        row = box.row(align=True)
        row.prop(rig, "fbp_text_matrix_viewport_columns", text="Columns", slider=True)
        row.prop(rig, "fbp_text_matrix_viewport_rows", text="Rows", slider=True)
        box.label(text="Render Grid")
        row = box.row(align=True)
        row.prop(rig, "fbp_text_matrix_render_columns", text="Columns", slider=True)
        row.prop(rig, "fbp_text_matrix_render_rows", text="Rows", slider=True)
        playback = box.row(align=True)
        playback.prop(rig, "fbp_text_matrix_auto_playback_limit", text="Playback Limit", toggle=True)
        playback_grid = playback.row(align=True)
        playback_grid.enabled = bool(getattr(rig, "fbp_text_matrix_auto_playback_limit", True))
        playback_grid.prop(rig, "fbp_text_matrix_playback_columns", text="Columns", slider=True)
        playback_grid.prop(rig, "fbp_text_matrix_playback_rows", text="Rows", slider=True)
        box.label(text="Rows set to 0 are calculated automatically", icon="INFO")
        box.prop(rig, "fbp_text_matrix_character_count", text="Levels")
        row = box.row(align=True)
        row.prop(rig, "fbp_text_matrix_character_aspect", text="Aspect")
        row.prop(rig, "fbp_text_matrix_glyph_scale", text="Scale")
        row = box.row(align=True)
        row.prop(rig, "fbp_text_matrix_contrast", text="Contrast")
        row.prop(rig, "fbp_text_matrix_invert", text="Invert", toggle=True)
        box.prop(rig, "fbp_text_matrix_variation", text="Character Variation")
        box.prop(rig, "fbp_text_matrix_use_source_color", text="Use Source Color", toggle=True)
        if not bool(getattr(rig, "fbp_text_matrix_use_source_color", True)):
            box.prop(rig, "fbp_text_matrix_text_color", text="Text Color")
        box.prop(rig, "fbp_text_matrix_transparent_background", text="Transparent Background", toggle=True)
        box.prop(rig, "fbp_text_matrix_realize", text="Realize Text Geometry", toggle=True)
        if not bool(getattr(rig, "fbp_text_matrix_transparent_background", True)):
            box.prop(rig, "fbp_text_matrix_background_color", text="Background Color")
        box.prop(rig, "fbp_text_matrix_alpha_threshold", text="Alpha Threshold")
        box.prop(rig, "fbp_text_matrix_seed", text="Character Seed")
        viewport_columns = max(2, int(getattr(rig, "fbp_text_matrix_viewport_columns", 2) or 2))
        viewport_rows = int(getattr(rig, "fbp_text_matrix_viewport_rows", 0) or 0)
        if viewport_columns > 96 or (viewport_rows > 0 and viewport_columns * viewport_rows > 6000):
            warning = box.row()
            warning.alert = True
            warning.label(text="Large grids create many text instances", icon="ERROR")
    if effect_id == FBP_EFFECT_MESH_WIGGLE:
        seed_row = box.row(align=True)
        seed_row.prop(rig, "fbp_mesh_wiggle_seed", text="Seed")
        seed_row.prop(rig, "fbp_mesh_wiggle_unique_seed", text="Unique per Layer", toggle=True)
    if effect_id == FBP_EFFECT_THICKNESS:
        materials = box.box()
        materials.label(text="Side and Back", icon="MATERIAL")
        materials.prop(rig, "fbp_thickness_side_material", text="Material Override")
        if getattr(rig, "fbp_thickness_side_material", None) is None:
            materials.prop(rig, "fbp_thickness_side_color", text="Color")
    if definition.get("alpha_aware"):
        if effect_id in {FBP_EFFECT_CUTOUT_OUTLINE, FBP_EFFECT_EXTRUDED_CUTOUT}:
            pass
        elif effect_id == FBP_EFFECT_THICKNESS:
            box.label(text="Image alpha defines the extruded silhouette", icon="IMAGE_ALPHA")
        elif effect_id == FBP_EFFECT_FELT_FUZZ:
            box.label(text="Uses the animated plane material", icon="MATERIAL")
            box.label(text="Image alpha limits generated fibers", icon="IMAGE_ALPHA")

    if definition.get("evolve_property") and effect_id != FBP_EFFECT_MESH_WIGGLE:
        animation = box.box()
        animation.label(text="Procedural Noise", icon="RNDCURVE")
        seed_row = animation.row(align=True)
        if effect_id == FBP_EFFECT_FELT_FUZZ:
            seed_row.prop(rig, "fbp_felt_seed", text="Seed")
        else:
            seed_row.prop(rig, _fbp_animation_key(effect_id, "seed"), text="Seed")
        evolve_key = _fbp_animation_key(effect_id, "evolve")
        seed_row.prop(
            rig,
            evolve_key,
            text="",
            toggle=True,
            icon="TIME",
        )
        if bool(getattr(rig, evolve_key, False)):
            animation.prop(
                rig,
                _fbp_animation_key(effect_id, "step"),
                text="Stepped",
                slider=True,
            )
        if bool(definition.get("supports_seed", False)):
            animation.prop(
                rig,
                _fbp_animation_key(effect_id, "unique"),
                text="Unique per Layer",
                toggle=True,
            )
    if present_count is None:
        present_count = selected_count
    if selected_count > 1:
        if present_count < selected_count:
            warning = box.row(align=True)
            warning.alert = True
            warning.label(
                text=f"Effect exists on {present_count} of {selected_count} selected layers",
                icon="ERROR",
            )
            copy = warning.operator(
                "fbp.copy_effect_to_selected",
                text="Copy to Selected",
                icon="PASTEDOWN",
            )
            copy.effect_id = effect_id


# ---------------------------------------------------------------------------
# UI classes and operators
# ---------------------------------------------------------------------------


class FBP_UL_EffectStack(UIList):
    category_filter = ""

    def filter_items(self, _context, data, propname):
        items = getattr(data, propname, ())
        category_filter = getattr(self, "category_filter", "")
        if isinstance(category_filter, (set, tuple, list, frozenset)):
            categories = {str(value) for value in category_filter if value}
        else:
            category = str(category_filter or "")
            categories = {category} if category else set()
        if not categories:
            return [self.bitflag_filter_item] * len(items), []
        flags = []
        for item in items:
            effect_id = fbp_normalize_effect_id(getattr(item, "effect_id", ""))
            item_category = str(fbp_effect_definition(effect_id).get("category", "2D") or "2D")
            flags.append(self.bitflag_filter_item if item_category in categories else 0)
        return flags, []

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        effect_id = fbp_normalize_effect_id(getattr(item, "effect_id", ""))
        definition = fbp_effect_definition(effect_id)
        effect_icon = str(definition.get("icon", "MODIFIER"))
        label = str(getattr(item, "label", "") or definition.get("label", effect_id) or "Effect")
        if self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text="", icon=effect_icon)
            return

        rigs = _fbp_selected_rigs(context)
        if data not in rigs:
            rigs = [data]
        present_count, selected_count = fbp_effect_presence(rigs, effect_id)
        states = [
            fbp_effect_visible_state(rig, effect_id)
            for rig in rigs
            if fbp_effect_is_active(rig, effect_id)
        ]
        all_visible = bool(states) and all(states)
        is_partial = 0 < present_count < selected_count

        row = layout.row(align=False)
        split = row.split(factor=0.70 if is_partial else 0.76, align=False)

        left = split.row(align=True)
        left.alignment = "LEFT"
        draggable = bool(
            definition.get("kind") in {"SHADER", "GEOMETRY"}
            and present_count == selected_count
            and (
                all(fbp_can_move_effect(rig, effect_id, "UP") for rig in rigs)
                or all(fbp_can_move_effect(rig, effect_id, "DOWN") for rig in rigs)
            )
        )
        handle = left.row(align=True)
        handle.enabled = draggable
        drag = handle.operator(
            "fbp.drag_effect",
            text="",
            icon="GRIP",
            emboss=False,
        )
        drag.effect_id = effect_id
        select = left.operator(
            "fbp.select_effect",
            text=f"{label} ({present_count}/{selected_count})" if is_partial else label,
            icon="ERROR" if is_partial else effect_icon,
            emboss=False,
        )
        select.effect_id = effect_id

        right = split.row(align=True)
        right.alignment = "RIGHT"
        try:
            right.ui_units_x = 4.4 if is_partial else 3.4
        except (AttributeError, TypeError, ValueError):
            pass
        if is_partial:
            copy = right.operator(
                "fbp.copy_effect_to_selected",
                text="",
                icon="PASTEDOWN",
                emboss=False,
            )
            copy.effect_id = effect_id
        if definition.get("kind") != "BASE":
            right.prop(
                item,
                "visible",
                text="",
                icon="HIDE_OFF" if all_visible else "HIDE_ON",
                icon_only=True,
                emboss=False,
            )
            render_visible = bool(getattr(item, "render_visible", True))
            right.prop(
                item,
                "render_visible",
                text="",
                icon="RESTRICT_RENDER_OFF" if render_visible else "RESTRICT_RENDER_ON",
                icon_only=True,
                emboss=False,
            )
        remove = right.operator(
            "fbp.remove_effect",
            text="",
            icon="TRASH",
            emboss=False,
        )
        remove.effect_id = effect_id


class FBP_UL_EffectStack2D(FBP_UL_EffectStack):
    # Base editing effects live at the top of the 2D stack.
    category_filter = {"BASE", "2D"}


class FBP_UL_EffectStack3D(FBP_UL_EffectStack):
    category_filter = "3D"


def _fbp_custom_effect_ids_for_view(view):
    view = "3D" if str(view or "2D") == "3D" else "2D"
    custom_ids = [
        effect_id for effect_id, definition in FBP_EFFECT_REGISTRY.items()
        if bool(definition.get("custom", False))
        and not bool(definition.get("custom_invalid", False))
        and not bool(definition.get("custom_hidden", False))
        and str(definition.get("category", "2D") or "2D") == view
    ]
    custom_ids.sort(
        key=lambda item: str(fbp_effect_definition(item).get("label", item)).casefold()
    )
    return custom_ids


def _fbp_effect_add_menu_state(context):
    """Cache selected rigs and active stack IDs once per menu draw."""
    fbp_refresh_custom_effect_registry()
    rigs = _fbp_selected_rigs(context)
    active_effects = {
        _fbp_effect_ids_cache_key(rig): set(
            fbp_effect_ids_for_rig(rig, refresh_custom=False)
        )
        for rig in rigs
    }
    return rigs, active_effects


def _fbp_draw_effect_add_columns(
    layout, context, view, *, show_view_header=False, menu_state=None
):
    """Draw one horizontal row of effect categories.

    Shared by the Effects panel add button and the viewport right-click menu so
    both entry points use the same compatibility and duplicate checks.
    """
    rigs, active_effects = menu_state or _fbp_effect_add_menu_state(context)
    view = "3D" if str(view or "2D") == "3D" else "2D"
    sections = FBP_MESH_EFFECT_MENU_SECTIONS if view == "3D" else FBP_IMAGE_EFFECT_MENU_SECTIONS

    def already_on_every_selected(effect_id):
        return bool(rigs) and all(
            effect_id in active_effects.get(_fbp_effect_ids_cache_key(rig), set())
            for rig in rigs
        )

    if show_view_header:
        layout.label(
            text="Mesh Effects" if view == "3D" else "Image Effects",
            icon="MODIFIER" if view == "3D" else "NODE_TEXTURE",
        )

    columns = layout.row(align=False)
    for section_label, section_icon, effect_ids in sections:
        column = columns.column(align=True)
        column.label(text=section_label, icon=section_icon)
        column.separator()
        for effect_id in effect_ids:
            definition = fbp_effect_definition(effect_id)
            row = column.row(align=True)
            supported = not rigs or any(
                fbp_effect_supported_for_rig(rig, effect_id) for rig in rigs
            )
            already_on_all = already_on_every_selected(effect_id)
            row.enabled = supported and not already_on_all
            operator = row.operator(
                "fbp.add_effect",
                text=str(definition.get("label", effect_id)),
                icon=str(definition.get("icon", "MODIFIER")),
            )
            operator.effect_id = effect_id

    custom_column = columns.column(align=True)
    custom_column.label(text="Custom Nodes", icon="NODETREE")
    custom_column.separator()
    custom_ids = _fbp_custom_effect_ids_for_view(view)
    if custom_ids:
        for effect_id in custom_ids:
            definition = fbp_effect_definition(effect_id)
            row = custom_column.row(align=True)
            supported = not rigs or any(
                fbp_effect_supported_for_rig(rig, effect_id) for rig in rigs
            )
            already_on_all = already_on_every_selected(effect_id)
            row.enabled = supported and not already_on_all
            operator = row.operator(
                "fbp.add_effect",
                text=str(definition.get("label", effect_id)),
                icon=str(definition.get("icon", "NODETREE")),
            )
            operator.effect_id = effect_id
    else:
        custom_column.label(text="No custom effects", icon="INFO")
    custom_column.separator()
    create = custom_column.operator(
        "fbp.create_custom_node_effect",
        text="New Custom Effect",
        icon="ADD",
    )
    create.kind = "GEOMETRY" if view == "3D" else "SHADER"
    custom_column.operator(
        "fbp.register_custom_node_effect",
        text="Register Existing...",
        icon="NODETREE",
    )


class FBP_MT_AddEffect(Menu):
    bl_idname = "FBP_MT_add_effect"
    bl_label = "Add Effect"

    def draw(self, context):
        view = getattr(getattr(context, "scene", None), "fbp_effects_view", "2D")
        _fbp_draw_effect_add_columns(self.layout, context, view)


class FBP_MT_ObjectEffects2D(Menu):
    bl_idname = "FBP_MT_object_effects_2d"
    bl_label = "2D Effects"

    def draw(self, context):
        if not _fbp_selected_rigs(context):
            self.layout.label(text="Select a Frame by Plane layer", icon="INFO")
            return
        _fbp_draw_effect_add_columns(self.layout, context, "2D")


class FBP_MT_ObjectEffects3D(Menu):
    bl_idname = "FBP_MT_object_effects_3d"
    bl_label = "3D Effects"

    def draw(self, context):
        if not _fbp_selected_rigs(context):
            self.layout.label(text="Select a Frame by Plane layer", icon="INFO")
            return
        _fbp_draw_effect_add_columns(self.layout, context, "3D")


class FBP_MT_ObjectEffects(Menu):
    bl_idname = "FBP_MT_object_effects"
    bl_label = "Frame by Plane Effects"

    def draw(self, context):
        layout = self.layout
        if not _fbp_selected_rigs(context):
            layout.label(text="Select a Frame by Plane layer", icon="INFO")
            return
        layout.menu(
            FBP_MT_ObjectEffects2D.bl_idname,
            text="2D Effects",
            icon="NODE_TEXTURE",
        )
        layout.menu(
            FBP_MT_ObjectEffects3D.bl_idname,
            text="3D Effects",
            icon="MODIFIER",
        )


def _fbp_draw_object_context_effects(self, context):
    """Prepend the lightweight Effects root menu to Blender's context menu."""
    if not _fbp_selected_rigs(context):
        return
    self.layout.menu(
        FBP_MT_ObjectEffects.bl_idname,
        text="Effects",
        icon="MODIFIER",
    )
    self.layout.separator()


class FBP_OT_CaptureCameraScaleReference(Operator):
    bl_idname = "fbp.capture_camera_scale_reference"
    bl_label = "Capture Camera Scale Reference"
    bl_description = "Capture the current camera-space depth, lens and sensor width as the framing reference"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context) and _fbp_scene_camera(getattr(context, "scene", None)))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        scene = getattr(context, "scene", None)
        changed = 0
        for rig in rigs:
            if not fbp_effect_is_active(rig, FBP_EFFECT_CAMERA_SCALE_LOCK):
                continue
            distance = fbp_camera_distance_for_rig(rig, scene)
            if distance <= 0.0:
                continue
            camera = _fbp_scene_camera(scene)
            camera_data = getattr(camera, "data", None) if camera else None
            fbp_set_rna_property_silent(
                rig, "fbp_camera_scale_lock_reference_distance", distance
            )
            if camera_data:
                fbp_set_rna_property_silent(
                    rig, "fbp_camera_scale_lock_reference_lens",
                    float(getattr(camera_data, "lens", 50.0) or 50.0),
                )
                fbp_set_rna_property_silent(
                    rig, "fbp_camera_scale_lock_reference_sensor_width",
                    float(getattr(camera_data, "sensor_width", 36.0) or 36.0),
                )
            fbp_update_geometry_effect(
                rig,
                FBP_EFFECT_CAMERA_SCALE_LOCK,
                scene=scene,
                sync_alpha=False,
                property_names={
                    "fbp_camera_scale_lock_reference_distance",
                    "fbp_camera_scale_lock_reference_lens",
                    "fbp_camera_scale_lock_reference_sensor_width",
                },
            )
            changed += 1
        if not changed:
            self.report({"WARNING"}, "No selected layer has Camera Scale Lock")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Captured camera reference for {changed} layer(s)")
        return {"FINISHED"}


class FBP_OT_SelectEffect(Operator):
    bl_idname = "fbp.select_effect"
    bl_label = "Select Effect"
    bl_options = {"INTERNAL"}

    effect_id: StringProperty(name="Effect ID", default="", options={"SKIP_SAVE"})

    @classmethod
    def description(cls, _context, properties):
        return fbp_effect_tooltip(getattr(properties, "effect_id", ""))

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        rig = rigs[0]
        effect_id = fbp_normalize_effect_id(self.effect_id)
        return {"FINISHED"} if _fbp_select_effect_row(rig, effect_id, rigs) else {"CANCELLED"}


class FBP_OT_AddEffect(Operator):
    bl_idname = "fbp.add_effect"
    bl_label = "Add Frame by Plane Effect"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(name="Effect ID", default="", options={"SKIP_SAVE"})

    @classmethod
    def description(cls, _context, properties):
        return fbp_effect_tooltip(getattr(properties, "effect_id", ""))

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        definition = fbp_effect_definition(self.effect_id)
        if not definition:
            return {"CANCELLED"}
        rigs = _fbp_selected_rigs(context)
        compatible = [rig for rig in rigs if fbp_effect_supported_for_rig(rig, self.effect_id)]
        changed = sum(1 for rig in compatible if fbp_add_effect(rig, self.effect_id))
        if changed == 0:
            self.report({"ERROR"}, f"{definition.get('label', self.effect_id)} is not compatible with the selected layers")
            return {"CANCELLED"}
        # New effects start at the beginning of their compatible evaluation chain.
        for rig in compatible:
            while fbp_can_move_effect(rig, self.effect_id, "UP"):
                if not fbp_move_effect(rig, self.effect_id, "UP"):
                    break
        active_rig = rigs[0]
        try:
            context.scene.fbp_effects_view = "3D" if definition.get("category") == "3D" else "2D"
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        fbp_sync_effect_items(active_rig, rigs)
        effect_id = fbp_normalize_effect_id(self.effect_id)
        for index, item in enumerate(getattr(active_rig, "fbp_effects", ())):
            if fbp_normalize_effect_id(getattr(item, "effect_id", "")) == effect_id:
                active_rig.fbp_effects_index = index
                break
        return {"FINISHED"}


def _fbp_copy_effect_stack_position(source, target, effect_id):
    """Match the copied effect position to the source stack when possible."""
    definition = fbp_effect_definition(effect_id)
    kind = definition.get("kind")
    if kind == "SHADER":
        stage = str(definition.get("stage", ""))
        source_materials = _fbp_plane_materials(source)
        target_materials = _fbp_plane_materials(target)
        if not source_materials or not target_materials:
            return False
        source_order = _fbp_get_shader_stage_order(source_materials[0], stage)
        if effect_id not in source_order:
            return False
        desired_rank = source_order.index(effect_id)
        changed = False
        final_order = None
        for material in target_materials:
            order = _fbp_get_shader_stage_order(material, stage)
            if effect_id not in order:
                continue
            order.remove(effect_id)
            order.insert(min(desired_rank, len(order)), effect_id)
            _fbp_set_shader_stage_order(material, stage, order)
            _fbp_rebuild_shader_stage(material, stage)
            final_order = order
            changed = True
        if changed and final_order is not None:
            _fbp_set_rig_shader_stage_order(target, stage, final_order)
        return changed

    if kind == "GEOMETRY":
        source_plane = _fbp_plane(source)
        target_plane = _fbp_plane(target)
        target_modifier = fbp_find_effect_modifier(target, effect_id)
        if not source_plane or not target_plane or not target_modifier:
            return False
        source_effect_ids = []
        for modifier in source_plane.modifiers:
            current_id = _fbp_geometry_effect_id_for_modifier(modifier)
            if current_id and current_id not in source_effect_ids:
                source_effect_ids.append(current_id)
        if effect_id not in source_effect_ids:
            return False
        desired_rank = source_effect_ids.index(effect_id)
        target_effect_modifiers = [
            modifier for modifier in target_plane.modifiers
            if _fbp_geometry_effect_id_for_modifier(modifier)
        ]
        if target_modifier not in target_effect_modifiers:
            return False
        desired_rank = min(desired_rank, len(target_effect_modifiers) - 1)
        try:
            current_index = target_plane.modifiers.find(target_modifier.name)
            destination = target_plane.modifiers.find(target_effect_modifiers[desired_rank].name)
            if current_index >= 0 and destination >= 0 and current_index != destination:
                target_plane.modifiers.move(current_index, destination)
                return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return False


FBP_BUILTIN_EFFECT_PRESETS = {
    FBP_EFFECT_EXTRUDED_CUTOUT: {
        "Paper Cutout": {"fbp_extruded_cutout_thickness": 0.025, "fbp_extruded_cutout_direction": -1.0, "fbp_extruded_cutout_alpha_threshold": 0.05, "fbp_extruded_cutout_side_color": (0.22, 0.16, 0.10, 1.0)},
        "Thick Card": {"fbp_extruded_cutout_thickness": 0.08, "fbp_extruded_cutout_direction": -1.0, "fbp_extruded_cutout_alpha_threshold": 0.08, "fbp_extruded_cutout_side_color": (0.12, 0.08, 0.05, 1.0)},
        "Forward Relief": {"fbp_extruded_cutout_thickness": 0.04, "fbp_extruded_cutout_direction": 1.0, "fbp_extruded_cutout_alpha_threshold": 0.05, "fbp_extruded_cutout_side_color": (0.35, 0.35, 0.35, 1.0)},
    },
    FBP_EFFECT_CUTOUT_OUTLINE: {
        "Graphic Ink": {"fbp_cutout_outline_width": 0.012, "fbp_cutout_outline_offset": 0.001, "fbp_cutout_outline_alpha_threshold": 0.05, "fbp_cutout_outline_color": (0.01, 0.01, 0.01, 1.0)},
        "Paper Sticker": {"fbp_cutout_outline_width": 0.025, "fbp_cutout_outline_offset": -0.001, "fbp_cutout_outline_alpha_threshold": 0.08, "fbp_cutout_outline_color": (0.92, 0.88, 0.76, 1.0)},
        "Neon Edge": {"fbp_cutout_outline_width": 0.009, "fbp_cutout_outline_offset": 0.003, "fbp_cutout_outline_alpha_threshold": 0.03, "fbp_cutout_outline_color": (0.05, 0.75, 1.0, 1.0)},
    },
    FBP_EFFECT_CAMERA_SCALE_LOCK: {
        "Lock Framing": {"fbp_camera_scale_lock_influence": 1.0},
        "Soft Compensation": {"fbp_camera_scale_lock_influence": 0.5},
        "Off": {"fbp_camera_scale_lock_influence": 0.0},
    },
    FBP_EFFECT_CAMERA_BILLBOARD: {
        "Face Camera": {"fbp_camera_billboard_mode": "FULL", "fbp_camera_billboard_flip": False, "fbp_camera_billboard_offset": 0.0},
        "Horizontal Only": {"fbp_camera_billboard_mode": "HORIZONTAL", "fbp_camera_billboard_flip": False, "fbp_camera_billboard_offset": 0.0},
        "Vertical Only": {"fbp_camera_billboard_mode": "VERTICAL", "fbp_camera_billboard_flip": False, "fbp_camera_billboard_offset": 0.0},
    },
    FBP_EFFECT_CHROMA_KEY: {
        "Green Screen": {"fbp_chroma_key_color": (0.0, 1.0, 0.0, 1.0), "fbp_chroma_key_tolerance": 0.20, "fbp_chroma_key_softness": 0.08, "fbp_chroma_key_despill": 0.65},
        "Blue Screen": {"fbp_chroma_key_color": (0.0, 0.18, 1.0, 1.0), "fbp_chroma_key_tolerance": 0.20, "fbp_chroma_key_softness": 0.08, "fbp_chroma_key_despill": 0.55},
    },
    FBP_EFFECT_DIGITAL_NOISE: {
        "High ISO": {"fbp_digital_noise_luma": 0.12, "fbp_digital_noise_chroma": 0.045, "fbp_digital_noise_scale": 650.0, "fbp_digital_noise_shadow_bias": 0.75},
        "Night Sensor": {"fbp_digital_noise_luma": 0.20, "fbp_digital_noise_chroma": 0.08, "fbp_digital_noise_scale": 900.0, "fbp_digital_noise_shadow_bias": 1.0},
        "Cheap Camera": {"fbp_digital_noise_luma": 0.10, "fbp_digital_noise_chroma": 0.13, "fbp_digital_noise_scale": 320.0, "fbp_digital_noise_shadow_bias": 0.55},
    },
    FBP_EFFECT_HALFTONE: {
        "Newspaper": {"fbp_halftone_scale": 95.0, "fbp_halftone_dot_size": 1.0, "fbp_halftone_contrast": 1.6, "fbp_halftone_shape": "CIRCLE", "fbp_halftone_use_source_color": False},
        "Comic": {"fbp_halftone_scale": 55.0, "fbp_halftone_dot_size": 1.1, "fbp_halftone_contrast": 2.0, "fbp_halftone_rotation": 0.35, "fbp_halftone_shape": "CIRCLE"},
        "Line Print": {"fbp_halftone_scale": 80.0, "fbp_halftone_dot_size": 0.85, "fbp_halftone_shape": "LINE", "fbp_halftone_rotation": 0.25},
    },
    FBP_EFFECT_DOT_MATRIX: {
        "LED Wall": {"fbp_dot_matrix_scale": 64.0, "fbp_dot_matrix_dot_size": 0.9, "fbp_dot_matrix_min_size": 0.08, "fbp_dot_matrix_max_size": 1.0, "fbp_dot_matrix_response": 0.82, "fbp_dot_matrix_glow": 0.04, "fbp_dot_matrix_shape": "CIRCLE"},
        "Printed Dots": {"fbp_dot_matrix_scale": 90.0, "fbp_dot_matrix_dot_size": 0.8, "fbp_dot_matrix_response": 1.25, "fbp_dot_matrix_glow": 0.005, "fbp_dot_matrix_use_source_color": False, "fbp_dot_matrix_shape": "CIRCLE"},
        "Dead Display": {"fbp_dot_matrix_scale": 52.0, "fbp_dot_matrix_dead_pixels": 0.08, "fbp_dot_matrix_flicker": 0.12, "fbp_dot_matrix_glow": 0.06},
    },
    FBP_EFFECT_ASCII_MATRIX: {
        "Green Terminal": {"fbp_ascii_charset": "CLASSIC", "fbp_ascii_colorize": False, "fbp_ascii_foreground": (0.08, 1.0, 0.22, 1.0), "fbp_ascii_background": (0.0, 0.015, 0.0, 1.0), "fbp_ascii_transparent_background": False},
        "Binary": {"fbp_ascii_charset": "BINARY", "fbp_ascii_character_count": 2, "fbp_ascii_colorize": False, "fbp_ascii_foreground": (0.75, 1.0, 0.75, 1.0)},
        "Typewriter": {"fbp_ascii_charset": "ALPHANUMERIC", "fbp_ascii_scale": 56.0, "fbp_ascii_colorize": False, "fbp_ascii_foreground": (0.08, 0.06, 0.04, 1.0), "fbp_ascii_background": (0.92, 0.88, 0.78, 1.0), "fbp_ascii_transparent_background": False},
    },
    FBP_EFFECT_PAPER_CURL: {
        "Gentle Lift": {"fbp_paper_curl_edge": "TOP", "fbp_paper_curl_progress": 0.22, "fbp_paper_curl_angle": 1.35, "fbp_paper_curl_radius": 0.10, "fbp_paper_curl_width": 0.34, "fbp_paper_curl_lift": 0.015},
        "Rolling Page": {"fbp_paper_curl_edge": "RIGHT", "fbp_paper_curl_progress": 0.58, "fbp_paper_curl_angle": 3.2, "fbp_paper_curl_radius": 0.18, "fbp_paper_curl_width": 0.30, "fbp_paper_curl_lift": 0.025},
        "Reverse Peel": {"fbp_paper_curl_edge": "BOTTOM", "fbp_paper_curl_progress": 0.42, "fbp_paper_curl_angle": 2.5, "fbp_paper_curl_radius": 0.14, "fbp_paper_curl_width": 0.24, "fbp_paper_curl_lift": 0.02, "fbp_paper_curl_reverse": True},
    },
    FBP_EFFECT_MESH_RIPPLE: {
        "Gentle Water": {"fbp_mesh_ripple_direction": "X", "fbp_mesh_ripple_amplitude": 0.035, "fbp_mesh_ripple_frequency": 2.5, "fbp_mesh_ripple_speed": 0.65, "fbp_mesh_ripple_pin_borders": 0.2},
        "Paper Pulse": {"fbp_mesh_ripple_direction": "Y", "fbp_mesh_ripple_amplitude": 0.08, "fbp_mesh_ripple_frequency": 4.0, "fbp_mesh_ripple_speed": 1.2, "fbp_mesh_ripple_stepped": 2, "fbp_mesh_ripple_pin_borders": 0.55},
        "Radial Shockwave": {"fbp_mesh_ripple_direction": "RADIAL", "fbp_mesh_ripple_amplitude": 0.16, "fbp_mesh_ripple_frequency": 6.0, "fbp_mesh_ripple_speed": 2.5, "fbp_mesh_ripple_pin_borders": 0.0},
    },
    FBP_EFFECT_WIND_BENDER: {
        "Gentle Breeze": {"fbp_wind_bend_amount": 0.18, "fbp_wind_speed": 1.1, "fbp_wind_turbulence": 0.018, "fbp_wind_gust_strength": 0.12, "fbp_wind_falloff": 1.4},
        "Flag": {"fbp_wind_motion_mode": "FLOW", "fbp_wind_wave_count": 2.5, "fbp_wind_wave_amplitude": 0.16, "fbp_wind_wave_speed": 2.1, "fbp_wind_turbulence": 0.025, "fbp_wind_falloff": 1.0},
        "Strong Flag": {"fbp_wind_motion_mode": "FLOW", "fbp_wind_bend_amount": 0.42, "fbp_wind_speed": 2.4, "fbp_wind_wave_count": 3.2, "fbp_wind_wave_amplitude": 0.26, "fbp_wind_wave_speed": 3.0, "fbp_wind_turbulence": 0.055, "fbp_wind_gust_strength": 0.38, "fbp_wind_falloff": 0.9},
        "Strong Gusts": {"fbp_wind_bend_amount": 0.55, "fbp_wind_speed": 2.8, "fbp_wind_turbulence": 0.09, "fbp_wind_gust_strength": 0.65, "fbp_wind_noise_scale": 2.2},
    },
    FBP_EFFECT_CRT_SCANLINES: {
        "VHS": {"fbp_crt_line_count": 420.0, "fbp_crt_opacity": 0.22},
        "Soft CRT": {"fbp_crt_line_count": 260.0, "fbp_crt_opacity": 0.10},
    },
    FBP_EFFECT_THICKNESS: {
        "Cardboard Poster": {"fbp_thickness_amount": 0.018, "fbp_thickness_alpha_threshold": 0.12, "fbp_thickness_alpha_resolution": 256},
    },
}


def _fbp_effect_property_names(effect_id):
    definition = fbp_effect_definition(effect_id)
    names = list(dict(definition.get("property_map", {})))
    names.extend(definition.get("extra_properties", ()))
    if definition.get("evolve_property"):
        names.extend(_fbp_animation_key(effect_id, suffix) for suffix in ("evolve", "step", "seed", "unique", "layer_seed", "amount", "loop"))
    return tuple(dict.fromkeys(names))


def _fbp_serialize_value(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "name") and hasattr(value, "bl_rna"):
        return {"__datablock__": str(getattr(value, "name", "")), "__type__": str(getattr(getattr(value, "bl_rna", None), "identifier", ""))}
    try:
        return [_fbp_serialize_value(item) for item in value]
    except TypeError:
        return str(value)


def _fbp_deserialize_value(value):
    if not isinstance(value, dict) or "__datablock__" not in value:
        return value
    name = str(value.get("__datablock__", "") or "")
    kind = str(value.get("__type__", "") or "")
    collection = {
        "VectorFont": getattr(bpy.data, "fonts", None),
        "Material": getattr(bpy.data, "materials", None),
        "Image": getattr(bpy.data, "images", None),
        "Object": getattr(bpy.data, "objects", None),
        "Collection": getattr(bpy.data, "collections", None),
        "Texture": getattr(bpy.data, "textures", None),
    }.get(kind)
    return collection.get(name) if collection and name else None


def _fbp_read_effect_property(rig, prop_name):
    try:
        if hasattr(rig, prop_name):
            return getattr(rig, prop_name)
        return rig.get(prop_name)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _fbp_write_effect_property(rig, prop_name, value):
    value = _fbp_deserialize_value(value)
    try:
        if hasattr(rig, prop_name):
            return fbp_set_rna_property_silent(rig, prop_name, value)
        rig[prop_name] = value
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_capture_effect_state(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    return {
        "effect_id": effect_id,
        "properties": {
            name: _fbp_serialize_value(_fbp_read_effect_property(rig, name))
            for name in _fbp_effect_property_names(effect_id)
        },
        "custom_inputs": _fbp_capture_custom_effect_inputs(rig, effect_id),
        "visible": fbp_effect_visible_state(rig, effect_id),
        "render_visible": fbp_effect_render_visible_state(rig, effect_id),
        "input_source": fbp_effect_input_source(rig, effect_id),
        "debug": fbp_effect_debug_mode(rig, effect_id),
    }


def _fbp_apply_effect_state(rig, state):
    effect_id = fbp_normalize_effect_id(state.get("effect_id", ""))
    if not effect_id or not fbp_effect_supported_for_rig(rig, effect_id):
        return False
    fbp_add_effect(rig, effect_id)
    for prop_name, value in dict(state.get("properties", {})).items():
        _fbp_write_effect_property(rig, prop_name, value)
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") == "BASE":
        try:
            from .core import update_object_padding_cb
            update_object_padding_cb(rig, bpy.context)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    elif definition.get("kind") == "GEOMETRY":
        fbp_update_geometry_effect(rig, effect_id)
    else:
        fbp_update_shader_effect(rig, effect_id)
    _fbp_apply_custom_effect_inputs(rig, effect_id, state.get("custom_inputs", {}))
    fbp_set_effect_visible(rig, effect_id, bool(state.get("visible", True)))
    fbp_set_effect_render_visible(rig, effect_id, bool(state.get("render_visible", True)))
    default_source = str(definition.get("default_input_source", "PREVIOUS") or "PREVIOUS")
    fbp_set_effect_input_source(rig, effect_id, state.get("input_source", default_source))
    fbp_set_effect_debug_mode(rig, effect_id, state.get("debug", "FINAL"))
    return True


def _fbp_apply_captured_stack_order(rig, states):
    """Restore copied effect order without disturbing unrelated Blender modifiers."""
    desired_ids = [
        fbp_normalize_effect_id(state.get("effect_id", ""))
        for state in list(states or ())
        if fbp_normalize_effect_id(state.get("effect_id", "")) in FBP_EFFECT_REGISTRY
    ]
    changed = False

    for stage in ("UV", "COLOR"):
        desired = [
            effect_id for effect_id in desired_ids
            if fbp_effect_definition(effect_id).get("kind") == "SHADER"
            and fbp_effect_definition(effect_id).get("stage") == stage
            and fbp_effect_is_active(rig, effect_id)
        ]
        if not desired:
            continue
        stage_order = list(desired)
        for material in _fbp_plane_materials(rig):
            current = _fbp_get_shader_stage_order(material, stage)
            merged = desired + [effect_id for effect_id in current if effect_id not in desired]
            stage_order = merged
            if merged != current:
                _fbp_set_shader_stage_order(material, stage, merged)
                _fbp_rebuild_shader_stage(material, stage)
                changed = True
        _fbp_set_rig_shader_stage_order(rig, stage, stage_order)

    desired_geometry = [
        effect_id for effect_id in desired_ids
        if fbp_effect_definition(effect_id).get("kind") == "GEOMETRY"
        and fbp_effect_is_active(rig, effect_id)
    ]
    plane = _fbp_plane(rig)
    if plane and desired_geometry:
        try:
            current_effect_modifiers = [
                modifier for modifier in plane.modifiers
                if _fbp_geometry_effect_id_for_modifier(modifier)
            ]
            desired_modifiers = [
                fbp_find_effect_modifier(rig, effect_id)
                for effect_id in desired_geometry
            ]
            desired_modifiers = [modifier for modifier in desired_modifiers if modifier]
            ordered = desired_modifiers + [
                modifier for modifier in current_effect_modifiers
                if modifier not in desired_modifiers
            ]
            for rank, modifier in enumerate(ordered):
                live_slots = [
                    index for index, item in enumerate(plane.modifiers)
                    if _fbp_geometry_effect_id_for_modifier(item)
                ]
                if rank >= len(live_slots):
                    break
                destination = live_slots[rank]
                current_index = plane.modifiers.find(modifier.name)
                if current_index >= 0 and current_index != destination:
                    plane.modifiers.move(current_index, destination)
                    changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return changed

def _fbp_user_preset_path():
    try:
        root = Path(bpy.utils.user_resource("CONFIG", path="frame_by_plane", create=True))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        root = Path.home() / ".frame_by_plane"
        root.mkdir(parents=True, exist_ok=True)
    return root / "effect_presets.json"


def _fbp_user_preset_stamp(path):
    try:
        stat = path.stat()
        return (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return None


def _fbp_load_user_presets():
    """Read user presets once per file revision instead of on every menu draw."""
    path = _fbp_user_preset_path()
    stamp = _fbp_user_preset_stamp(path)
    if stamp is None:
        _FBP_USER_PRESET_CACHE["stamp"] = None
        _FBP_USER_PRESET_CACHE["data"] = {}
        return {}
    if _FBP_USER_PRESET_CACHE.get("stamp") == stamp:
        return copy.deepcopy(_FBP_USER_PRESET_CACHE.get("data", {}))
    try:
        data = json.loads(path.read_text(encoding="utf8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        data = {}
    _FBP_USER_PRESET_CACHE["stamp"] = stamp
    _FBP_USER_PRESET_CACHE["data"] = data
    return copy.deepcopy(data)


def _fbp_save_user_presets(data):
    """Write preset JSON atomically so an interrupted save cannot corrupt it."""
    path = _fbp_user_preset_path()
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = data if isinstance(data, dict) else {}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf8",
        )
        temporary.replace(path)
        _FBP_USER_PRESET_CACHE["stamp"] = _fbp_user_preset_stamp(path)
        _FBP_USER_PRESET_CACHE["data"] = copy.deepcopy(payload)
        return True
    except OSError:
        return False
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass


def _fbp_apply_preset_values(rig, effect_id, values):
    state = _fbp_capture_effect_state(rig, effect_id)
    values = dict(values or {})
    if int(values.get("__fbp_state__", 0) or 0) >= 1:
        state["properties"].update(dict(values.get("properties", {}) or {}))
        state["custom_inputs"] = dict(values.get("custom_inputs", {}) or {})
    else:
        normalized = {}
        for name, value in values.items():
            normalized[name] = value if isinstance(value, dict) and "__datablock__" in value else _fbp_serialize_value(value)
        state["properties"].update(normalized)
    return _fbp_apply_effect_state(rig, state)


class FBP_MT_EffectPresets(Menu):
    bl_idname = "FBP_MT_effect_presets"
    bl_label = "Effect Presets"

    def draw(self, context):
        layout = self.layout
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            layout.label(text="No Frame by Plane layer selected", icon="INFO")
            return
        rig = rigs[0]
        # Menu drawing must remain read-only. The runtime mirror is normally
        # synchronized by the Effects panel; after load/Undo, fall back to the
        # current cached stack without repairing assets or writing UI rows.
        effect_id = fbp_active_effect_id(rig)
        if not effect_id:
            effect_ids = _fbp_runtime_effect_ids(rig)
            try:
                index = max(0, int(getattr(rig, "fbp_effects_index", 0) or 0))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                index = 0
            if effect_ids:
                effect_id = effect_ids[min(index, len(effect_ids) - 1)]
        builtins = FBP_BUILTIN_EFFECT_PRESETS.get(effect_id, {})
        users = dict(_fbp_load_user_presets().get(effect_id, {}))
        if builtins:
            layout.label(text="Built-in", icon="PRESET")
            for name in builtins:
                op = layout.operator("fbp.apply_effect_preset", text=name, icon="CHECKMARK")
                op.effect_id = effect_id
                op.preset_name = name
                op.user_preset = False
        if users:
            layout.separator()
            layout.label(text="User", icon="USER")
            for name in users:
                row = layout.row(align=True)
                op = row.operator("fbp.apply_effect_preset", text=name, icon="PRESET")
                op.effect_id = effect_id
                op.preset_name = name
                op.user_preset = True
                rename = row.operator("fbp.rename_effect_preset", text="", icon="GREASEPENCIL")
                rename.effect_id = effect_id
                rename.preset_name = name
                rename.new_name = name
                delete = row.operator("fbp.delete_effect_preset", text="", icon="X")
                delete.effect_id = effect_id
                delete.preset_name = name
        layout.separator()
        layout.operator("fbp.save_effect_preset", text="Save Current Preset", icon="ADD")


class FBP_MT_EffectStackActions(Menu):
    bl_idname = "FBP_MT_effect_stack_actions"
    bl_label = "Effect Stack Actions"

    def draw(self, _context):
        layout = self.layout
        layout.operator("fbp.copy_active_effect", icon="COPYDOWN")
        layout.operator("fbp.copy_effect_stack", icon="COPYDOWN")
        layout.operator("fbp.paste_effect_stack", icon="PASTEDOWN")
        layout.separator()
        layout.operator("fbp.reset_active_effect", icon="LOOP_BACK")
        preset_menu = layout.operator("wm.call_menu", text="Effect Presets", icon="PRESET")
        preset_menu.name = "FBP_MT_effect_presets"
        layout.operator("fbp.sort_effect_stack", icon="SORT_DESC")
        layout.separator()
        layout.operator("fbp.clear_effect_stack", icon="TRASH")


class FBP_OT_EffectHeaderWarning(Operator):
    bl_idname = "fbp.effect_header_warning"
    bl_label = "Effect Warning"
    bl_options = {"INTERNAL"}

    effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    message: StringProperty(default="", options={"SKIP_SAVE"})
    fix_order: BoolProperty(default=False, options={"SKIP_SAVE"})

    @classmethod
    def description(cls, _context, properties):
        message = str(getattr(properties, "message", "") or "Effect warning")
        if bool(getattr(properties, "fix_order", False)):
            message += "\nClick to restore the recommended effect order"
        return message

    def execute(self, context):
        if not self.fix_order:
            return {"FINISHED"}
        changed = False
        recommended = list(FBP_BASE_EFFECT_MENU_ORDER) + list(FBP_SHADER_STAGE_ORDER["UV"]) + list(FBP_SHADER_STAGE_ORDER["COLOR"]) + list(FBP_3D_EFFECT_MENU_ORDER)
        for rig in _fbp_selected_rigs(context):
            active = set(fbp_effect_ids_for_rig(rig))
            for effect_id in reversed([item for item in recommended if item in active]):
                while fbp_can_move_effect(rig, effect_id, "UP"):
                    if not fbp_move_effect(rig, effect_id, "UP"):
                        break
                    changed = True
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_SetEffectInputSource(Operator):
    bl_idname = "fbp.set_effect_input_source"
    bl_label = "Set Effect Input Source"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    source: EnumProperty(
        items=(
            ("PREVIOUS", "Previous Effects", "Read the current compatible stack result"),
            ("ORIGINAL", "Original Material", "Read the original Frame by Plane material color"),
            ("FINAL", "Final Material", "Evaluate after the regular color stack and read its completed result"),
        ),
        default="PREVIOUS",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        changed = False
        for rig in _fbp_selected_rigs(context):
            if fbp_effect_is_active(rig, self.effect_id):
                changed = fbp_set_effect_input_source(rig, self.effect_id, self.source) or changed
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_SetEffectDebugMode(Operator):
    bl_idname = "fbp.set_effect_debug_mode"
    bl_label = "Set Effect Preview"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    mode: StringProperty(default="FINAL", options={"SKIP_SAVE"})

    def execute(self, context):
        changed = False
        for rig in _fbp_selected_rigs(context):
            if fbp_effect_is_active(rig, self.effect_id):
                changed = fbp_set_effect_debug_mode(rig, self.effect_id, self.mode) or changed
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_CopyActiveEffect(Operator):
    bl_idname = "fbp.copy_active_effect"
    bl_label = "Copy Active Effect"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        effect_id = fbp_active_effect_id(rigs[0])
        if not effect_id:
            return {"CANCELLED"}
        _FBP_EFFECT_CLIPBOARD.clear()
        _FBP_EFFECT_CLIPBOARD.update({"mode": "EFFECT", "effects": [_fbp_capture_effect_state(rigs[0], effect_id)]})
        self.report({"INFO"}, f"Copied {fbp_effect_definition(effect_id).get('label', effect_id)}")
        return {"FINISHED"}


class FBP_OT_CopyEffectStack(Operator):
    bl_idname = "fbp.copy_effect_stack"
    bl_label = "Copy Effect Stack"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        effects = [_fbp_capture_effect_state(rigs[0], effect_id) for effect_id in fbp_effect_ids_for_rig(rigs[0])]
        _FBP_EFFECT_CLIPBOARD.clear()
        _FBP_EFFECT_CLIPBOARD.update({"mode": "STACK", "effects": effects})
        self.report({"INFO"}, f"Copied {len(effects)} effect(s)")
        return {"FINISHED"}


class FBP_OT_PasteEffectStack(Operator):
    bl_idname = "fbp.paste_effect_stack"
    bl_label = "Paste Effects"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context)) and bool(_FBP_EFFECT_CLIPBOARD.get("effects"))

    def execute(self, context):
        changed = 0
        states = list(_FBP_EFFECT_CLIPBOARD.get("effects", ()))
        for rig in _fbp_selected_rigs(context):
            for state in states:
                changed += int(_fbp_apply_effect_state(rig, state))
            changed += int(_fbp_apply_captured_stack_order(rig, states))
        if changed:
            rigs = _fbp_selected_rigs(context)
            if rigs:
                fbp_sync_effect_items(rigs[0], rigs)
            return {"FINISHED"}
        return {"CANCELLED"}


class FBP_OT_ClearEffectStack(Operator):
    bl_idname = "fbp.clear_effect_stack"
    bl_label = "Clear Effect Stack"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        changed = 0
        for rig in _fbp_selected_rigs(context):
            for effect_id in tuple(fbp_effect_ids_for_rig(rig)):
                changed += int(fbp_remove_effect(rig, effect_id))
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_ResetActiveEffect(Operator):
    bl_idname = "fbp.reset_active_effect"
    bl_label = "Reset Active Effect"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        effect_id = fbp_active_effect_id(rigs[0])
        if not effect_id:
            return {"CANCELLED"}
        for rig in rigs:
            for prop_name in _fbp_effect_property_names(effect_id):
                try:
                    prop = rig.bl_rna.properties.get(prop_name)
                    if prop is None:
                        continue
                    value = tuple(prop.default_array) if getattr(prop, "is_array", False) else prop.default
                    fbp_set_rna_property_silent(rig, prop_name, value)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    continue
            definition = fbp_effect_definition(effect_id)
            if definition.get("evolve_property"):
                fbp_reset_effect_animation_state(rig, effect_id)
                fbp_ensure_effect_animation_state(rig, effect_id)
            if bool(definition.get("custom", False)):
                _fbp_reset_custom_effect_inputs(rig, effect_id)
            default_source = str(definition.get("default_input_source", "PREVIOUS") or "PREVIOUS")
            fbp_set_effect_input_source(rig, effect_id, default_source)
            fbp_set_effect_debug_mode(rig, effect_id, "FINAL")
            if definition.get("kind") == "GEOMETRY":
                fbp_update_geometry_effect(rig, effect_id)
            elif definition.get("kind") == "SHADER":
                fbp_update_shader_effect(rig, effect_id)
        return {"FINISHED"}


class FBP_OT_SortEffectStack(Operator):
    bl_idname = "fbp.sort_effect_stack"
    bl_label = "Sort to Recommended Order"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        changed = False
        recommended = list(FBP_BASE_EFFECT_MENU_ORDER) + list(FBP_SHADER_STAGE_ORDER["UV"]) + list(FBP_SHADER_STAGE_ORDER["COLOR"]) + list(FBP_3D_EFFECT_MENU_ORDER)
        for rig in _fbp_selected_rigs(context):
            active = set(fbp_effect_ids_for_rig(rig))
            for effect_id in reversed([item for item in recommended if item in active]):
                while fbp_can_move_effect(rig, effect_id, "UP"):
                    if not fbp_move_effect(rig, effect_id, "UP"):
                        break
                    changed = True
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_ApplyEffectPreset(Operator):
    bl_idname = "fbp.apply_effect_preset"
    bl_label = "Apply Effect Preset"
    bl_options = {"REGISTER", "UNDO"}
    effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    preset_name: StringProperty(default="", options={"SKIP_SAVE"})
    user_preset: BoolProperty(default=False, options={"SKIP_SAVE"})

    def execute(self, context):
        source = _fbp_load_user_presets().get(self.effect_id, {}) if self.user_preset else FBP_BUILTIN_EFFECT_PRESETS.get(self.effect_id, {})
        values = source.get(self.preset_name)
        if not isinstance(values, dict):
            return {"CANCELLED"}
        changed = sum(int(_fbp_apply_preset_values(rig, self.effect_id, values)) for rig in _fbp_selected_rigs(context) if fbp_effect_is_active(rig, self.effect_id))
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_SaveEffectPreset(Operator):
    bl_idname = "fbp.save_effect_preset"
    bl_label = "Save Effect Preset"
    bl_options = {"INTERNAL"}
    preset_name: StringProperty(name="Name", default="My Preset")

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        effect_id = fbp_active_effect_id(rigs[0])
        name = self.preset_name.strip()
        if not effect_id or not name:
            return {"CANCELLED"}
        state = _fbp_capture_effect_state(rigs[0], effect_id)
        data = _fbp_load_user_presets()
        if bool(fbp_effect_definition(effect_id).get("custom", False)):
            preset_value = {
                "__fbp_state__": 1,
                "properties": state["properties"],
                "custom_inputs": state.get("custom_inputs", {}),
            }
        else:
            preset_value = state["properties"]
        data.setdefault(effect_id, {})[name] = preset_value
        if not _fbp_save_user_presets(data):
            self.report({"ERROR"}, "Could not save preset")
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_RenameEffectPreset(Operator):
    bl_idname = "fbp.rename_effect_preset"
    bl_label = "Rename Effect Preset"
    bl_options = {"REGISTER", "INTERNAL"}

    effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    preset_name: StringProperty(default="", options={"SKIP_SAVE"})
    new_name: StringProperty(name="Name", default="My Preset")

    def invoke(self, context, _event):
        self.new_name = str(self.preset_name or "My Preset")
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, _context):
        self.layout.prop(self, "new_name")

    def execute(self, _context):
        old_name = str(self.preset_name or "").strip()
        new_name = str(self.new_name or "").strip()
        if not old_name or not new_name:
            self.report({"ERROR"}, "Preset names cannot be empty")
            return {"CANCELLED"}
        data = _fbp_load_user_presets()
        presets = data.get(self.effect_id, {})
        if old_name not in presets:
            self.report({"ERROR"}, "Preset no longer exists")
            return {"CANCELLED"}
        if new_name != old_name and new_name in presets:
            self.report({"ERROR"}, "A preset with this name already exists")
            return {"CANCELLED"}
        if new_name == old_name:
            return {"FINISHED"}
        value = presets.pop(old_name)
        presets[new_name] = value
        data[self.effect_id] = presets
        if not _fbp_save_user_presets(data):
            self.report({"ERROR"}, "Could not rename preset")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Renamed preset to {new_name}")
        return {"FINISHED"}


class FBP_OT_DeleteEffectPreset(Operator):
    bl_idname = "fbp.delete_effect_preset"
    bl_label = "Delete Effect Preset"
    bl_options = {"INTERNAL"}
    effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    preset_name: StringProperty(default="", options={"SKIP_SAVE"})

    def execute(self, _context):
        data = _fbp_load_user_presets()
        presets = data.get(self.effect_id, {})
        if self.preset_name not in presets:
            return {"CANCELLED"}
        del presets[self.preset_name]
        if not presets:
            data.pop(self.effect_id, None)
        return {"FINISHED"} if _fbp_save_user_presets(data) else {"CANCELLED"}


class FBP_OT_CopyCustomEffectValuesToSelected(Operator):
    bl_idname = "fbp.copy_custom_effect_values_to_selected"
    bl_label = "Copy Custom Effect Values to Selected"
    bl_description = "Copy the active layer custom node socket values to every selected Frame by Plane layer"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(name="Effect ID", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return len(_fbp_selected_rigs(context)) > 1

    def execute(self, context):
        effect_id = fbp_normalize_effect_id(self.effect_id)
        definition = fbp_effect_definition(effect_id)
        rigs = _fbp_selected_rigs(context)
        source = fbp_effect_source_rig(rigs, effect_id)
        if (
            not bool(definition.get("custom", False))
            or bool(definition.get("custom_invalid", False))
            or source is None
        ):
            return {"CANCELLED"}
        state = _fbp_capture_custom_effect_inputs(source, effect_id)
        if not state:
            self.report({"WARNING"}, "This custom effect exposes no editable values")
            return {"CANCELLED"}

        changed = 0
        for target in rigs:
            if target is source:
                continue
            if not fbp_effect_is_active(target, effect_id):
                if not fbp_add_effect(target, effect_id):
                    continue
            if _fbp_apply_custom_effect_inputs(target, effect_id, state):
                changed += 1
        if not changed:
            self.report({"INFO"}, "Selected layers already use the same values")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Copied custom values to {changed} layer(s)")
        return {"FINISHED"}


class FBP_OT_CopyEffectToSelected(Operator):
    bl_idname = "fbp.copy_effect_to_selected"
    bl_label = "Copy Effect to Selected"
    bl_description = "Copy this effect and its settings to selected layers that do not have it"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(name="Effect ID", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return len(_fbp_selected_rigs(context)) > 1

    def execute(self, context):
        effect_id = fbp_normalize_effect_id(self.effect_id)
        definition = fbp_effect_definition(effect_id)
        rigs = _fbp_selected_rigs(context)
        source = fbp_effect_source_rig(rigs, effect_id)
        targets = [rig for rig in rigs if not fbp_effect_is_active(rig, effect_id)]
        if not definition or source is None or not targets:
            return {"CANCELLED"}

        prop_names = list(definition.get("property_map", {}))
        prop_names.extend(definition.get("extra_properties", ()))
        if effect_id == FBP_EFFECT_MESH_WIGGLE:
            prop_names.extend(("fbp_mesh_wiggle_seed", "fbp_mesh_wiggle_unique_seed"))
        animation_keys = ()
        if definition.get("evolve_property"):
            animation_keys = tuple(
                _fbp_animation_key(effect_id, suffix)
                for suffix in ("evolve", "step", "seed", "unique", "amount")
            )

        copied = 0
        source_custom_inputs = _fbp_capture_custom_effect_inputs(source, effect_id)
        source_visible = fbp_effect_visible_state(source, effect_id)
        source_render_visible = fbp_effect_render_visible_state(source, effect_id)
        for target in targets:
            if not fbp_add_effect(target, effect_id):
                continue
            for prop_name in dict.fromkeys((*prop_names, *animation_keys)):
                if not hasattr(source, prop_name) or not hasattr(target, prop_name):
                    continue
                try:
                    if not fbp_set_rna_property_silent(
                        target, prop_name, getattr(source, prop_name)
                    ):
                        continue
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    continue
            if definition.get("kind") == "BASE":
                try:
                    from .core import update_object_padding_cb
                    update_object_padding_cb(target, context)
                except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
            elif definition.get("kind") == "GEOMETRY":
                fbp_update_geometry_effect(target, effect_id)
            else:
                fbp_update_shader_effect(target, effect_id)
            _fbp_apply_custom_effect_inputs(target, effect_id, source_custom_inputs)

            if effect_id == FBP_EFFECT_MESH_WIGGLE:
                if bool(getattr(target, "fbp_mesh_wiggle_unique_seed", False)):
                    fbp_assign_mesh_wiggle_layer_seed(target, force=True)
                    fbp_update_geometry_effect(target, effect_id)
            elif definition.get("supports_seed"):
                unique_key = _fbp_animation_key(effect_id, "unique")
                if bool(getattr(target, unique_key, False)):
                    fbp_assign_effect_layer_seed(target, effect_id, force=True)
                    if definition.get("kind") == "GEOMETRY":
                        fbp_update_geometry_effect(target, effect_id)
                    else:
                        fbp_update_shader_effect(target, effect_id)

            _fbp_copy_effect_stack_position(source, target, effect_id)
            fbp_set_effect_visible(target, effect_id, source_visible)
            fbp_set_effect_render_visible(target, effect_id, source_render_visible)
            fbp_set_effect_input_source(target, effect_id, fbp_effect_input_source(source, effect_id))
            fbp_set_effect_debug_mode(target, effect_id, fbp_effect_debug_mode(source, effect_id))
            copied += 1

        if rigs:
            fbp_sync_effect_items(rigs[0], rigs)
        if copied == 0:
            return {"CANCELLED"}
        self.report({"INFO"}, f"Copied {definition.get('label', effect_id)} to {copied} layer(s)")
        return {"FINISHED"}


class FBP_OT_DuplicateActiveEffect(Operator):
    bl_idname = "fbp.duplicate_active_effect"
    bl_label = "Duplicate Effect to Selected Layers"
    bl_description = "Copy the selected effect and its settings to selected layers that do not already contain it"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        rigs = _fbp_selected_rigs(context)
        if len(rigs) < 2:
            return False
        fbp_sync_effect_items(rigs[0], rigs)
        effect_id = fbp_active_effect_id(rigs[0])
        present, total = fbp_effect_presence(rigs, effect_id) if effect_id else (0, len(rigs))
        return bool(effect_id and 0 < present < total)

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        effect_id = fbp_active_effect_id(rigs[0])
        if not effect_id:
            return {"CANCELLED"}
        return bpy.ops.fbp.copy_effect_to_selected(effect_id=effect_id)


class FBP_OT_SetEffectViewport(Operator):
    bl_idname = "fbp.set_effect_viewport"
    bl_label = "Set Effect Viewport Visibility"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(name="Effect ID", default="", options={"SKIP_SAVE"})
    visible: BoolProperty(name="Visible", default=True, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs or any(not fbp_effect_is_active(rig, self.effect_id) for rig in rigs):
            self.report({"WARNING"}, "The selected layers do not share this effect")
            return {"CANCELLED"}
        changed = sum(1 for rig in rigs if fbp_set_effect_visible(rig, self.effect_id, self.visible))
        if changed == 0:
            return {"CANCELLED"}
        return {"FINISHED"}


def _fbp_effect_chain_ids(rig, effect_id):
    """Return the real compatible evaluation chain containing ``effect_id``."""
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    kind = definition.get("kind")
    if kind == "GEOMETRY":
        plane = _fbp_plane(rig)
        if not plane:
            return []
        try:
            return [
                item_id for item_id in (
                    _fbp_geometry_effect_id_for_modifier(modifier)
                    for modifier in plane.modifiers
                )
                if item_id
            ]
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return []
    if kind == "SHADER":
        stage = str(definition.get("stage", "") or "")
        order = _fbp_get_rig_shader_stage_order(rig, stage)
        if order:
            return list(order)
        materials = _fbp_plane_materials(rig)
        return _fbp_get_shader_stage_order(materials[0], stage) if materials else []
    return []


def _fbp_recommended_chain(effect_id):
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") == "GEOMETRY":
        return tuple(FBP_3D_EFFECT_MENU_ORDER)
    if definition.get("kind") == "SHADER":
        return tuple(FBP_SHADER_STAGE_ORDER.get(str(definition.get("stage", "") or ""), ()))
    return ()


def fbp_effect_order_warning(rig, effect_id):
    """Return a compact warning when an effect differs from recommended order."""
    effect_id = fbp_normalize_effect_id(effect_id)
    if not rig or not effect_id:
        return ""
    current = _fbp_effect_chain_ids(rig, effect_id)
    recommended = _fbp_recommended_chain(effect_id)
    if effect_id not in current or not recommended:
        return ""
    rank = {item: index for index, item in enumerate(recommended)}
    expected = sorted(current, key=lambda item: (rank.get(item, len(rank)), current.index(item)))
    if current == expected:
        return ""
    try:
        current_index = current.index(effect_id)
        expected_index = expected.index(effect_id)
    except ValueError:
        return ""
    if current_index > expected_index:
        return "Recommended earlier in this effect chain"
    if current_index < expected_index:
        return "Recommended later in this effect chain"
    return "This chain differs from the recommended effect order"


def fbp_move_effects_transactional(rigs, effect_id, direction):
    """Move the same effect on every rig or roll back partial changes."""
    rigs = [rig for rig in list(rigs or ()) if rig]
    effect_id = fbp_normalize_effect_id(effect_id)
    direction = "UP" if str(direction).upper() == "UP" else "DOWN"
    if not rigs or not all(fbp_can_move_effect(rig, effect_id, direction) for rig in rigs):
        return False
    moved = []
    for rig in rigs:
        if fbp_move_effect(rig, effect_id, direction):
            moved.append(rig)
            continue
        inverse = "DOWN" if direction == "UP" else "UP"
        for previous in reversed(moved):
            fbp_move_effect(previous, effect_id, inverse)
        return False
    _fbp_select_effect_row(rigs[0], effect_id, rigs)
    return True


def fbp_can_move_effect(rig, effect_id, direction):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    step = -1 if str(direction).upper() == "UP" else 1
    if definition.get("kind") == "GEOMETRY":
        plane = _fbp_plane(rig)
        modifier = fbp_find_effect_modifier(rig, effect_id)
        if not plane or not modifier:
            return False
        ordered = [m for m in plane.modifiers if _fbp_geometry_effect_id_for_modifier(m)]
        try:
            current = ordered.index(modifier)
        except ValueError:
            return False
        target = current + step
        return 0 <= target < len(ordered)
    if definition.get("kind") == "SHADER":
        stage = str(definition.get("stage", ""))
        order = _fbp_get_rig_shader_stage_order(rig, stage)
        if effect_id not in order:
            materials = _fbp_plane_materials(rig)
            order = _fbp_get_shader_stage_order(materials[0], stage) if materials else []
        if effect_id not in order:
            return False
        target = order.index(effect_id) + step
        return 0 <= target < len(order)
    return False


class FBP_OT_DragEffect(Operator):
    bl_idname = "fbp.drag_effect"
    bl_label = "Drag Effect"
    bl_description = "Drag vertically to reorder this effect inside its compatible chain"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    effect_id: StringProperty(name="Effect ID", default="", options={"SKIP_SAVE"})

    def _current_rigs(self):
        rigs = []
        for name in getattr(self, "_rig_names", ()):
            rig = bpy.data.objects.get(name)
            if rig is not None:
                rigs.append(rig)
        return rigs

    def _restore_cursor(self, context):
        try:
            context.window.cursor_modal_restore()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    def _redraw(self, context):
        try:
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            try:
                context.area.tag_redraw()
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass

    def _move_once(self, direction):
        return fbp_move_effects_transactional(
            self._current_rigs(), self.effect_id, direction
        )

    def invoke(self, context, event):
        rigs = _fbp_selected_rigs(context)
        effect_id = fbp_normalize_effect_id(self.effect_id)
        definition = fbp_effect_definition(effect_id)
        if (
            not rigs
            or definition.get("kind") not in {"SHADER", "GEOMETRY"}
            or any(not fbp_effect_is_active(rig, effect_id) for rig in rigs)
        ):
            return {"CANCELLED"}
        self.effect_id = effect_id
        self._rig_names = tuple(str(getattr(rig, "name", "") or "") for rig in rigs)
        self._anchor_y = int(getattr(event, "mouse_y", 0) or 0)
        self._history = []
        try:
            ui_scale = float(context.preferences.system.ui_scale)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            ui_scale = 1.0
        self._threshold = max(12, int(round(18.0 * ui_scale)))
        _fbp_select_effect_row(rigs[0], effect_id, rigs)
        context.window_manager.modal_handler_add(self)
        try:
            context.window.cursor_modal_set("SCROLL_Y")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        self._redraw(context)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            mouse_y = int(getattr(event, "mouse_y", self._anchor_y) or self._anchor_y)
            delta = mouse_y - self._anchor_y
            while abs(delta) >= self._threshold:
                direction = "UP" if delta > 0 else "DOWN"
                if not self._move_once(direction):
                    self._anchor_y = mouse_y
                    break
                self._history.append(direction)
                self._anchor_y += self._threshold if delta > 0 else -self._threshold
                delta = mouse_y - self._anchor_y
            self._redraw(context)
            return {"RUNNING_MODAL"}

        if event.type in {"ESC", "RIGHTMOUSE"}:
            inverse = {"UP": "DOWN", "DOWN": "UP"}
            for direction in reversed(getattr(self, "_history", ())):
                self._move_once(inverse[direction])
            self._restore_cursor(context)
            self._redraw(context)
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self._restore_cursor(context)
            self._redraw(context)
            return {"FINISHED"}

        if event.type == "WINDOW_DEACTIVATE":
            self._restore_cursor(context)
            return {"FINISHED"}

        return {"RUNNING_MODAL"}


class FBP_OT_SetEffectRender(Operator):
    bl_idname = "fbp.set_effect_render"
    bl_label = "Set Effect Render Visibility"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(name="Effect ID", default="", options={"SKIP_SAVE"})
    visible: BoolProperty(name="Visible in Render", default=True, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs or any(not fbp_effect_is_active(rig, self.effect_id) for rig in rigs):
            return {"CANCELLED"}
        changed = sum(1 for rig in rigs if fbp_set_effect_render_visible(rig, self.effect_id, self.visible))
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_MoveActiveEffect(Operator):
    bl_idname = "fbp.move_active_effect"
    bl_label = "Move Selected Effect"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction",
        items=(("UP", "Up", "Move the effect earlier in its compatible chain"),
               ("DOWN", "Down", "Move the effect later in its compatible chain")),
        default="UP",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        active_rig = rigs[0]
        fbp_sync_effect_items(active_rig, rigs)
        effect_id = fbp_active_effect_id(active_rig)
        if not effect_id:
            return {"CANCELLED"}
        present_count, selected_count = fbp_effect_presence(rigs, effect_id)
        if present_count != selected_count:
            self.report({"WARNING"}, "Copy the effect to all selected layers before reordering it")
            return {"CANCELLED"}
        moved = sum(1 for rig in rigs if fbp_move_effect(rig, effect_id, self.direction))
        fbp_sync_effect_items(active_rig, rigs)
        if moved == 0:
            self.report({"INFO"}, "The effect cannot move farther in this chain")
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_RemoveEffect(Operator):
    bl_idname = "fbp.remove_effect"
    bl_label = "Remove Effect"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(name="Effect ID", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        effect_id = fbp_normalize_effect_id(self.effect_id)
        rigs = _fbp_selected_rigs(context)
        if not effect_id or not rigs:
            return {"CANCELLED"}
        removed = sum(
            1 for rig in rigs
            if fbp_effect_is_active(rig, effect_id) and fbp_remove_effect(rig, effect_id)
        )
        fbp_sync_effect_items(rigs[0], rigs)
        return {"FINISHED"} if removed else {"CANCELLED"}


class FBP_OT_RemoveActiveEffect(Operator):
    bl_idname = "fbp.remove_active_effect"
    bl_label = "Remove Selected Effect"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        active_rig = rigs[0]
        fbp_sync_effect_items(active_rig, rigs)
        effect_id = fbp_active_effect_id(active_rig)
        if not effect_id:
            return {"CANCELLED"}
        removed = sum(1 for rig in rigs if fbp_remove_effect(rig, effect_id))
        fbp_sync_effect_items(active_rig, rigs)
        if removed == 0:
            return {"CANCELLED"}
        return {"FINISHED"}


classes = (
    FBP_UL_EffectStack,
    FBP_UL_EffectStack2D,
    FBP_UL_EffectStack3D,
    FBP_MT_AddEffect,
    FBP_MT_ObjectEffects2D,
    FBP_MT_ObjectEffects3D,
    FBP_MT_ObjectEffects,
    FBP_MT_EffectPresets,
    FBP_MT_EffectStackActions,
    FBP_OT_EffectHeaderWarning,
    FBP_OT_CaptureCameraScaleReference,
    FBP_OT_SelectEffect,
    FBP_OT_AddEffect,
    FBP_OT_SetEffectInputSource,
    FBP_OT_SetEffectDebugMode,
    FBP_OT_CopyActiveEffect,
    FBP_OT_CopyEffectStack,
    FBP_OT_PasteEffectStack,
    FBP_OT_ClearEffectStack,
    FBP_OT_ResetActiveEffect,
    FBP_OT_SortEffectStack,
    FBP_OT_ApplyEffectPreset,
    FBP_OT_SaveEffectPreset,
    FBP_OT_RenameEffectPreset,
    FBP_OT_DeleteEffectPreset,
    FBP_OT_CopyCustomEffectValuesToSelected,
    FBP_OT_CopyEffectToSelected,
    FBP_OT_DuplicateActiveEffect,
    FBP_OT_SetEffectViewport,
    FBP_OT_DragEffect,
    FBP_OT_SetEffectRender,
    FBP_OT_MoveActiveEffect,
    FBP_OT_RemoveEffect,
    FBP_OT_RemoveActiveEffect,
)


def _fbp_remove_named_handler(collection, function):
    for handler in list(collection):
        if (
            handler is function
            or (
                getattr(handler, "__name__", "") == getattr(function, "__name__", "")
                and str(getattr(handler, "__module__", "")).endswith("geometry_nodes")
            )
        ):
            try:
                collection.remove(handler)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass


def _fbp_remove_evolve_handlers():
    _fbp_remove_named_handler(bpy.app.handlers.frame_change_post, fbp_effect_evolve_frame_change)
    _fbp_remove_named_handler(bpy.app.handlers.animation_playback_pre, fbp_effect_playback_pre)
    _fbp_remove_named_handler(bpy.app.handlers.animation_playback_post, fbp_effect_playback_post)




def fbp_clear_effect_runtime_caches():
    """Drop transient RNA caches before Undo, file load or module teardown."""
    global _FBP_DEFAULT_FONT_CACHE
    _FBP_EFFECT_HEALTH_CACHE.clear()
    _FBP_EFFECT_GROUP_CACHE.clear()
    _FBP_INTERFACE_INPUT_CACHE.clear()
    _FBP_MATRIX_IMAGE_NODE_CACHE.clear()
    _FBP_EFFECT_IDS_CACHE.clear()
    _FBP_EFFECT_IDS_CACHE_TIME.clear()
    _FBP_EFFECT_RUNTIME_PROFILE_CACHE.clear()
    _FBP_EFFECT_SCENE_RIG_CACHE.clear()
    _FBP_CAMERA_BINDING_CACHE.clear()
    _FBP_CUSTOM_SHADER_SYNC_PENDING.clear()
    _FBP_CUSTOM_GEOMETRY_INIT_PENDING.clear()
    _FBP_CUSTOM_GEOMETRY_SOCKET_CACHE.clear()
    _FBP_CUSTOM_SHADER_SOCKET_CACHE.clear()
    _FBP_CUSTOM_SHADER_SYNC_STATE_CACHE.clear()
    _FBP_EFFECT_STACK_OWNER_CACHE.clear()
    _FBP_EFFECT_INSTANCE_OWNER_CACHE.clear()
    _FBP_USER_PRESET_CACHE["stamp"] = None
    _FBP_USER_PRESET_CACHE["data"] = {}
    _FBP_DEFAULT_FONT_CACHE = None


def _fbp_remove_object_context_menu_entry():
    menu_type = getattr(bpy.types, "VIEW3D_MT_object_context_menu", None)
    if menu_type is None:
        return
    callbacks = (
        _FBP_PREVIOUS_OBJECT_CONTEXT_CALLBACK,
        _fbp_draw_object_context_effects,
    )
    seen = set()
    for callback in callbacks:
        if not callable(callback) or id(callback) in seen:
            continue
        seen.add(id(callback))
        try:
            menu_type.remove(callback)
        except (AttributeError, RuntimeError, ValueError):
            pass


def register():
    fbp_clear_effect_runtime_caches()
    fbp_refresh_custom_effect_registry(force=True)
    for issue in FBP_EFFECT_REGISTRY_ISSUES:
        fbp_warn(f"Effect registry validation: {issue}")
    for cls in classes:
        bpy.utils.register_class(cls)
    _fbp_remove_object_context_menu_entry()
    menu_type = getattr(bpy.types, "VIEW3D_MT_object_context_menu", None)
    if menu_type is not None:
        menu_type.prepend(_fbp_draw_object_context_effects)
    _fbp_remove_evolve_handlers()
    bpy.app.handlers.frame_change_post.append(fbp_effect_evolve_frame_change)
    bpy.app.handlers.animation_playback_pre.append(fbp_effect_playback_pre)
    bpy.app.handlers.animation_playback_post.append(fbp_effect_playback_post)


def unregister():
    global _FBP_EFFECT_PLAYBACK_ACTIVE
    _FBP_EFFECT_PLAYBACK_ACTIVE = False
    fbp_clear_effect_runtime_caches()
    _fbp_remove_object_context_menu_entry()
    _fbp_remove_evolve_handlers()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
