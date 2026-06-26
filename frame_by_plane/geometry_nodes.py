"""Frame by Plane geometry and shader effect stack.

Geometry effects are stored as Geometry Nodes modifiers on the generated plane.
Shader effects are stored as tagged group nodes inside the plane material and are
inserted into the controlled UV or Color stages.

Bundled node groups are appended lazily from ``assets/fbp_geometry_nodes.blend``.
Alpha-aware geometry effects receive a private node-group copy per plane so the
current image/sequence and ImageUser timing never leak between layers.
"""

from pathlib import Path
import os
import copy
import importlib
import json
import math
import time
import uuid

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.app.handlers import persistent
from bpy.types import Menu, Operator, UIList
from mathutils import Matrix, Vector

from .constants import (
    COLLECTION_COLOR_ENUM_ITEMS,
    fbp_collection_color_icon,
    fbp_layer_blend_label,
    fbp_layer_blend_short,
)
from .storage_keys import fbp_effect_storage_key

from .custom_effects import (
    find_custom_effect_group,
    refresh_one_custom_effect_definition,
)
from .matrix_presets import (
    ASCII_ATLAS_COLUMNS,
    ASCII_PRESET_ROWS,
    ASCII_TEXT_GLYPH_LIMIT,
    ascii_gradient,
    ascii_level_gradient,
)

from .effect_schema import (
    FBP_EFFECT_SCHEMA_VERSION,
    FBP_EFFECT_INSTANCE_KEY,
    FBP_EFFECT_INSTANCE_OWNER_KEY,
    FBP_EFFECT_INSTANCE_VERSION,
    FBP_EFFECT_INSTANCE_VERSION_KEY,
    assign_effect_group_id,
    assign_effect_instance_id,
    ensure_effect_instance_id,
    effect_group_id,
    effect_instance_id,
    finalize_effect_registry,
    new_effect_group_id,
    new_effect_instance_id,
)

from .effects_registry import (
    FBP_EFFECT_MESH_WIGGLE,
    FBP_EFFECT_WIND_BENDER,
    FBP_EFFECT_CUTOUT_OUTLINE,
    FBP_EFFECT_CAMERA_SCALE_LOCK,
    FBP_EFFECT_CAMERA_BILLBOARD,
    FBP_EFFECT_MIRROR,
    FBP_EFFECT_THICKNESS,
    FBP_EFFECT_FELT_FUZZ,
    FBP_EFFECT_LATTICE,
    FBP_EFFECT_PIXELATE,
    FBP_EFFECT_SWIRL,
    FBP_EFFECT_BULGE_PINCH,
    FBP_EFFECT_LENS_WARP,
    FBP_EFFECT_WAVE_WARP,
    FBP_EFFECT_RIPPLE_DISTORTION,
    FBP_EFFECT_KALEIDOSCOPE,
    FBP_EFFECT_HEX_PIXELATE,
    FBP_EFFECT_MOSAIC_JITTER,
    FBP_EFFECT_RECOLOR,
    FBP_EFFECT_CURVES,
    FBP_EFFECT_GRADIENT_LIGHT,
    FBP_EFFECT_SHADOW,
    FBP_EFFECT_DEPTH_BLUR,
    FBP_EFFECT_GAUSSIAN_BLUR,
    FBP_EFFECT_DIRECTIONAL_BLUR,
    FBP_EFFECT_TRIANGLE_BLUR, FBP_EFFECT_TILT_SHIFT, FBP_EFFECT_UNSHARP_MASK, FBP_EFFECT_EDGE_DETECT,
    FBP_EFFECT_SMOOTH_TOON, FBP_EFFECT_ADAPTIVE_THRESHOLD, FBP_EFFECT_FALSE_COLOR, FBP_EFFECT_CHROMATIC_ABERRATION,
    FBP_EFFECT_INK, FBP_EFFECT_EDGE_WORK, FBP_EFFECT_PENCIL_SKETCH, FBP_EFFECT_POSTER_EDGES,
    FBP_EFFECT_CROSSHATCH, FBP_EFFECT_EMBOSS,
    FBP_EFFECT_ALPHA_MATTE,
    FBP_EFFECT_LUMA_MATTE,
    FBP_EFFECT_SQUARE_MASK,
    FBP_EFFECT_CIRCLE_MASK,
    FBP_EFFECT_TRIANGLE_MASK,
    FBP_EFFECT_CLIPPING_MASK,
    FBP_EFFECT_IMPORTED_MASK,
    FBP_EFFECT_LAYER_BLEND,
    FBP_EFFECT_COLOR_MASK,
    FBP_EFFECT_LUMINANCE_MASK,
    FBP_EFFECT_CHANNEL_MASK,
    FBP_EFFECT_GRADIENT_MASK,
    FBP_EFFECT_NOISE_MASK,
    FBP_EFFECT_CRT_SCANLINES,
    FBP_EFFECT_SOLARIZE,
    FBP_EFFECT_DUOTONE,
    FBP_EFFECT_TRITONE,
    FBP_EFFECT_FILM_FADE,
    FBP_EFFECT_DIGITAL_NOISE,
    FBP_EFFECT_CHROMA_KEY,
    FBP_EFFECT_HALFTONE,
    FBP_EFFECT_DOT_MATRIX,
    FBP_EFFECT_ASCII_MATRIX,
    FBP_EFFECT_ASCII,
    FBP_EFFECT_TEXT_MATRIX,
    FBP_EFFECT_REGISTRY,
    FBP_EFFECT_REGISTRY_ISSUES,
    fbp_refresh_custom_effect_registry,
    FBP_SHADER_STAGE_ORDER,
    FBP_BASE_EFFECT_MENU_ORDER,
    FBP_3D_EFFECT_MENU_ORDER,
    FBP_IMAGE_EFFECT_MENU_SECTIONS,
    FBP_MASK_EFFECT_MENU_SECTIONS,
    FBP_MESH_EFFECT_MENU_SECTIONS,
    FBP_IMAGE_EFFECT_MENU_COLUMNS,
    FBP_MASK_EFFECT_MENU_COLUMNS,
    FBP_MESH_EFFECT_MENU_COLUMNS,
    fbp_effect_family_id,
    fbp_effect_family_definition,
    fbp_effect_variant_label,
    fbp_effect_definition,
    fbp_effect_supported_for_rig,
    fbp_effect_tooltip,
    fbp_normalize_effect_id,
)

from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_runtime_get,
    fbp_render_mutation_blocked,
    fbp_is_silent_property_update,
    fbp_undo_guard_active,
    fbp_set_rna_property_silent,
    fbp_warn,
    fbp_remove_action_fcurves,
    fbp_action_fcurves,
    fbp_obj_runtime_key,
    fbp_find_id_by_runtime_key,
    fbp_unique_token_hex,
)


_BUILTIN_EFFECTS_MODULE = None


def _fbp_builtin_effects_module():
    """Load procedural built-in effect builders only when first required.

    The generated-node implementation is one of the largest Python modules in
    the extension, but most sessions use existing bundled groups or no effects
    at all. Delaying its import reduces extension enable time and Python memory
    without changing the effect contract.
    """
    global _BUILTIN_EFFECTS_MODULE
    if _BUILTIN_EFFECTS_MODULE is None:
        _BUILTIN_EFFECTS_MODULE = importlib.import_module(
            ".builtin_effects", __package__
        )
    return _BUILTIN_EFFECTS_MODULE


def _builtin_group_is_complete(node_group, definition):
    return _fbp_builtin_effects_module()._builtin_group_is_complete(
        node_group, definition
    )


def create_builtin_effect_group(effect_id, definition, asset_dir):
    return _fbp_builtin_effects_module().create_builtin_effect_group(
        effect_id, definition, asset_dir
    )


FBP_GN_LIBRARY_FILENAME = "fbp_geometry_nodes.blend"
FBP_ALPHA_MASK_PATCH_VERSION = 7
FBP_LOCAL_EFFECT_MASK_WIRING_VERSION = 3

_FBP_EFFECT_HEALTH_CACHE = globals().get("_FBP_EFFECT_HEALTH_CACHE", {})
_FBP_EFFECT_GROUP_CACHE = globals().get("_FBP_EFFECT_GROUP_CACHE", {})
_FBP_INTERFACE_INPUT_CACHE = globals().get("_FBP_INTERFACE_INPUT_CACHE", {})
_FBP_MATRIX_IMAGE_NODE_CACHE = globals().get("_FBP_MATRIX_IMAGE_NODE_CACHE", {})
_FBP_PRIVATE_IMAGE_SOURCE_SYNC_CACHE = globals().get("_FBP_PRIVATE_IMAGE_SOURCE_SYNC_CACHE", {})
_FBP_MASK_SOURCE_SYNC_CACHE = globals().get("_FBP_MASK_SOURCE_SYNC_CACHE", {})
_FBP_IMPORTED_MASK_SYNC_CACHE = globals().get("_FBP_IMPORTED_MASK_SYNC_CACHE", {})
_FBP_EFFECT_IDS_CACHE = globals().get("_FBP_EFFECT_IDS_CACHE", {})
_FBP_EFFECT_IDS_CACHE_TIME = globals().get("_FBP_EFFECT_IDS_CACHE_TIME", {})
if not isinstance(_FBP_EFFECT_IDS_CACHE_TIME, dict):
    _FBP_EFFECT_IDS_CACHE_TIME = {}
_FBP_EFFECT_IDS_CACHE_SECONDS = 4.0
_FBP_EFFECT_RUNTIME_PROFILE_CACHE = globals().get("_FBP_EFFECT_RUNTIME_PROFILE_CACHE", {})
_FBP_EFFECT_SCENE_RIG_CACHE = globals().get("_FBP_EFFECT_SCENE_RIG_CACHE", {})
_FBP_EFFECT_EVOLVE_STEP_CACHE = globals().get("_FBP_EFFECT_EVOLVE_STEP_CACHE", {})
_FBP_EFFECT_RUNTIME_STATS = globals().get(
    "_FBP_EFFECT_RUNTIME_STATS",
    {"handler_runs": 0, "rig_updates": 0, "held_step_skips": 0},
)
if not isinstance(_FBP_EFFECT_RUNTIME_STATS, dict):
    _FBP_EFFECT_RUNTIME_STATS = {"handler_runs": 0, "rig_updates": 0, "held_step_skips": 0}
_FBP_EFFECT_SCENE_CACHE_SECONDS = 8.0
_FBP_EFFECT_PROFILE_CACHE_SECONDS = 12.0
_FBP_EFFECT_HEALTH_CACHE_SECONDS = 2.0
_FBP_CAMERA_BINDING_CACHE = globals().get("_FBP_CAMERA_BINDING_CACHE", {})
_FBP_CUSTOM_SHADER_SYNC_PENDING = globals().get("_FBP_CUSTOM_SHADER_SYNC_PENDING", {})
_FBP_CUSTOM_GEOMETRY_INIT_PENDING = globals().get("_FBP_CUSTOM_GEOMETRY_INIT_PENDING", {})
_FBP_CUSTOM_GEOMETRY_SOCKET_CACHE = globals().get("_FBP_CUSTOM_GEOMETRY_SOCKET_CACHE", {})
_FBP_CUSTOM_SHADER_SOCKET_CACHE = globals().get("_FBP_CUSTOM_SHADER_SOCKET_CACHE", {})
_FBP_CUSTOM_SHADER_SYNC_STATE_CACHE = globals().get("_FBP_CUSTOM_SHADER_SYNC_STATE_CACHE", {})
_FBP_COLOR_RAMP_SYNC_PENDING = globals().get("_FBP_COLOR_RAMP_SYNC_PENDING", {})
_FBP_COLOR_RAMP_SYNC_STATE_CACHE = globals().get("_FBP_COLOR_RAMP_SYNC_STATE_CACHE", {})
_FBP_EFFECT_STACK_OWNER_CACHE = globals().get("_FBP_EFFECT_STACK_OWNER_CACHE", {})
_FBP_EFFECT_INSTANCE_OWNER_CACHE = globals().get("_FBP_EFFECT_INSTANCE_OWNER_CACHE", {})
_FBP_RELATION_SYNC_PENDING = globals().get("_FBP_RELATION_SYNC_PENDING", {})
if not isinstance(_FBP_RELATION_SYNC_PENDING, dict):
    _FBP_RELATION_SYNC_PENDING = {}
# Incremented whenever Undo, file load or module teardown invalidates transient
# effect UI mirrors. The epoch is embedded in the mirror signature so a stack
# with unchanged effect IDs is still rebuilt after Blender replaces Main data.
_FBP_EFFECT_UI_EPOCH = int(globals().get("_FBP_EFFECT_UI_EPOCH", 0) or 0)
_FBP_CUSTOM_SOCKET_CACHE_SECONDS = 0.25
_FBP_CUSTOM_SHADER_SYNC_CACHE_SECONDS = 0.75
_FBP_COLOR_RAMP_SYNC_CACHE_LIMIT = 256
_FBP_USER_PRESET_CACHE = globals().get("_FBP_USER_PRESET_CACHE", {"stamp": None, "data": {}})
if not isinstance(_FBP_USER_PRESET_CACHE, dict):
    _FBP_USER_PRESET_CACHE = {"stamp": None, "data": {}}
_FBP_DEFAULT_FONT_CACHE = globals().get("_FBP_DEFAULT_FONT_CACHE", None)
_FBP_PREVIOUS_OBJECT_CONTEXT_CALLBACK = globals().get("_fbp_draw_object_context_effects")


_FBP_EVOLVE_HANDLER_ACTIVE = False
_FBP_EFFECT_PLAYBACK_ACTIVE = False
_FBP_EFFECT_CLIPBOARD = {}
_FBP_MASK_TARGET_CACHE = globals().get("_FBP_MASK_TARGET_CACHE", {})
_FBP_MASK_TARGET_CACHE_SECONDS = 1.0


def _fbp_effect_visibility_key(effect_id):
    return fbp_effect_storage_key(
        "fbp_effect_visible_", fbp_normalize_effect_id(effect_id)
    )


def _fbp_effect_render_visibility_key(effect_id):
    return fbp_effect_storage_key(
        "fbp_effect_render_visible_", fbp_normalize_effect_id(effect_id)
    )


def _fbp_effect_state_key(effect_id, suffix):
    return fbp_effect_storage_key(
        "fbp_effect_", fbp_normalize_effect_id(effect_id), f"_{suffix}"
    )


def _fbp_effect_mask_target_key(mask_effect_id):
    return _fbp_effect_state_key(mask_effect_id, "mask_target")


def _fbp_effect_is_local_mask(mask_effect_id):
    definition = fbp_effect_definition(mask_effect_id)
    return bool(
        definition.get("kind") == "SHADER"
        and str(definition.get("stage", "") or "") == "MASK"
        and str(definition.get("mask_output_socket", "") or "")
        and not bool(definition.get("layer_feature", False))
    )


def _fbp_effect_can_receive_mask(effect_id):
    definition = fbp_effect_definition(effect_id)
    return bool(
        definition.get("kind") == "SHADER"
        and str(definition.get("stage", "") or "") in {"UV", "COLOR"}
        and str(definition.get("input_socket", "") or "")
        and str(definition.get("output_socket", "") or "")
    )


def fbp_effect_mask_target(rig, mask_effect_id):
    mask_effect_id = fbp_normalize_effect_id(mask_effect_id)
    if not rig or not _fbp_effect_is_local_mask(mask_effect_id):
        return "LAYER"
    key = _fbp_effect_mask_target_key(mask_effect_id)
    try:
        target = fbp_normalize_effect_id(rig.get(key, "LAYER"))
    except FBP_DATA_ERRORS:
        target = "LAYER"
    if not target or target == "LAYER":
        return "LAYER"
    if not _fbp_effect_can_receive_mask(target) or not fbp_effect_is_active(rig, target):
        return "LAYER"
    return target


def fbp_effect_mask_raw_target(rig, mask_effect_id):
    """Return the stored local-mask target without applying validity fallback.

    ``fbp_effect_mask_target`` intentionally falls back to ``LAYER`` when the
    saved target is missing or no longer compatible. Diagnostics need the raw
    value as well so they can distinguish a deliberate layer mask from stale
    metadata left after effect removal, Undo or file migration.
    """
    mask_effect_id = fbp_normalize_effect_id(mask_effect_id)
    if not rig or not _fbp_effect_is_local_mask(mask_effect_id):
        return "LAYER"
    try:
        return (
            fbp_normalize_effect_id(
                rig.get(_fbp_effect_mask_target_key(mask_effect_id), "LAYER")
            )
            or "LAYER"
        )
    except FBP_DATA_ERRORS:
        return "LAYER"


def fbp_local_effect_mask_contract_report(rig, *, repair=False):
    """Validate per-effect mask assignments and generated receiver wiring.

    Repair mode is deliberately non-destructive: invalid targets are returned
    to the whole-layer route and generated UV/Color receiver helpers are rebuilt
    from the active effect stack. User mask values, helper geometry and source
    media are never deleted.
    """
    stats = {
        "local_mask_effects": 0,
        "local_mask_targets": 0,
        "local_mask_invalid_targets": 0,
        "local_mask_materials": 0,
        "local_mask_stale_wiring": 0,
        "local_mask_stale_helpers": 0,
        "local_mask_repairs": 0,
    }
    issues = []
    warnings = []
    if not rig:
        return {"stats": stats, "issues": (), "warnings": (), "repaired": 0}

    rig_name = str(getattr(rig, "name", "<rig>") or "<rig>")
    active_ids = tuple(fbp_effect_ids_for_rig(rig))
    active_set = set(active_ids)
    local_masks = tuple(
        effect_id for effect_id in active_ids
        if _fbp_effect_is_local_mask(effect_id)
    )
    stats["local_mask_effects"] = len(local_masks)
    valid_targets = []

    for mask_id in local_masks:
        raw_target = fbp_effect_mask_raw_target(rig, mask_id)
        if raw_target == "LAYER":
            continue
        stats["local_mask_targets"] += 1
        reason = ""
        if raw_target == mask_id:
            reason = "targets itself"
        elif raw_target not in active_set:
            reason = f"targets inactive or missing effect {raw_target}"
        elif not _fbp_effect_can_receive_mask(raw_target):
            reason = f"targets incompatible effect {raw_target}"
        if reason:
            stats["local_mask_invalid_targets"] += 1
            issues.append(f"{rig_name}: {mask_id} {reason}")
            if repair and fbp_set_effect_mask_target(rig, mask_id, "LAYER"):
                stats["local_mask_repairs"] += 1
            continue
        valid_targets.append(raw_target)

    materials = tuple(_fbp_plane_materials(rig))
    stats["local_mask_materials"] = len(materials)
    has_local_routes = bool(valid_targets)
    for material in materials:
        material_name = str(getattr(material, "name", "<material>") or "<material>")
        try:
            version = int(
                material.get("fbp_local_effect_mask_wiring_version", 0) or 0
            )
        except FBP_DATA_ERRORS:
            version = 0
        try:
            helper_nodes = tuple(_fbp_local_mask_helper_nodes(material))
            routing_helpers = tuple(
                node for node in helper_nodes
                if not bool(node.get("fbp_local_effect_mask_preview", False))
            )
        except FBP_DATA_ERRORS:
            helper_nodes = ()
            routing_helpers = ()
        stale_helpers = []
        for node in routing_helpers:
            try:
                target = fbp_normalize_effect_id(
                    node.get("fbp_local_effect_mask_target", "")
                )
            except FBP_DATA_ERRORS:
                target = ""
            if target and target not in active_set:
                stale_helpers.append(target)
        if stale_helpers:
            stats["local_mask_stale_helpers"] += len(stale_helpers)
            warnings.append(
                f"{rig_name}/{material_name}: stale local-mask helper target(s): "
                + ", ".join(sorted(set(stale_helpers)))
            )

        wiring_stale = bool(
            (has_local_routes and version < FBP_LOCAL_EFFECT_MASK_WIRING_VERSION)
            or stale_helpers
            or (not has_local_routes and routing_helpers)
        )
        if wiring_stale:
            stats["local_mask_stale_wiring"] += 1
            issues.append(
                f"{rig_name}/{material_name}: local-mask receiver wiring is stale"
            )
            if repair:
                try:
                    if _fbp_rebuild_local_mask_receivers(material):
                        stats["local_mask_repairs"] += 1
                except FBP_DATA_ERRORS:
                    pass

    _fbp_invalidate_mask_target_cache(rig)
    return {
        "stats": stats,
        "issues": tuple(issues),
        "warnings": tuple(warnings),
        "repaired": int(stats["local_mask_repairs"]),
    }


def _fbp_mask_target_cache_key(rig):
    """Return a cache identity that cannot alias a newly created Blender ID."""
    key = fbp_obj_runtime_key(rig) if rig is not None else None
    return key if key is not None else id(rig)


def _fbp_invalidate_mask_target_cache(rig=None):
    """Invalidate the lightweight local-mask target lookup cache."""
    if rig is None:
        _FBP_MASK_TARGET_CACHE.clear()
        return
    _FBP_MASK_TARGET_CACHE.pop(_fbp_mask_target_cache_key(rig), None)


def _fbp_mask_target_map(rig):
    """Return target effect -> local mask IDs with bounded self-validation.

    Normal UI redraws reuse the cached map. Once per second the lightweight raw
    target signature is checked so Undo, driver edits or direct custom-property
    changes cannot leave mask icons and node routing stale indefinitely.
    """
    if not rig:
        return {}
    key = _fbp_mask_target_cache_key(rig)
    now = time.monotonic()
    cached = _FBP_MASK_TARGET_CACHE.get(key)
    if isinstance(cached, tuple) and len(cached) == 3:
        cached_time, cached_signature, cached_map = cached
        if now - float(cached_time) < _FBP_MASK_TARGET_CACHE_SECONDS:
            return cached_map
    else:
        cached_signature, cached_map = None, None

    effect_ids = tuple(fbp_effect_ids_for_rig(rig))
    local_mask_ids = tuple(
        mask_id for mask_id in effect_ids if _fbp_effect_is_local_mask(mask_id)
    )
    signature_parts = []
    for mask_id in local_mask_ids:
        try:
            raw_target = fbp_normalize_effect_id(
                rig.get(_fbp_effect_mask_target_key(mask_id), "LAYER")
            ) or "LAYER"
        except FBP_DATA_ERRORS:
            raw_target = "LAYER"
        signature_parts.append((mask_id, raw_target))
    signature = (effect_ids, tuple(signature_parts))
    if cached_map is not None and signature == cached_signature:
        _FBP_MASK_TARGET_CACHE[key] = (now, signature, cached_map)
        return cached_map

    result = {}
    for mask_id, _raw_target in signature[1]:
        target = fbp_effect_mask_target(rig, mask_id)
        if target != "LAYER":
            result.setdefault(target, []).append(mask_id)
    frozen = {target: tuple(mask_ids) for target, mask_ids in result.items()}
    if len(_FBP_MASK_TARGET_CACHE) >= 1024 and key not in _FBP_MASK_TARGET_CACHE:
        _FBP_MASK_TARGET_CACHE.clear()
    _FBP_MASK_TARGET_CACHE[key] = (now, signature, frozen)
    return frozen


def fbp_masks_targeting_effect(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    if not rig or not effect_id:
        return ()
    return _fbp_mask_target_map(rig).get(effect_id, ())


def _fbp_effect_mask_target_stage(effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    if not effect_id or effect_id == "LAYER":
        return "LAYER"
    if not _fbp_effect_can_receive_mask(effect_id):
        return "LAYER"
    return str(fbp_effect_definition(effect_id).get("stage", "") or "").upper()


def _fbp_rebuild_mask_target_routing(material, previous_target, target_effect_id):
    """Rebuild only the receiver stages affected by one mask reassignment.

    Moving a mask between the whole layer and a UV effect does not require the
    complete Color stack to be reconstructed. Color targets still rebuild the
    Color stage because that stage also restores the alpha chain. UV-only
    changes rebuild UV and relink alpha directly.
    """
    if not material or not material.node_tree:
        return False
    previous_stage = _fbp_effect_mask_target_stage(previous_target)
    target_stage = _fbp_effect_mask_target_stage(target_effect_id)
    stages = {stage for stage in (previous_stage, target_stage) if stage in {"UV", "COLOR"}}
    # A UV-only reassignment normally avoids the Color stack. Diagnostic Matte
    # preview is the exception because its temporary grayscale node lives in
    # that stack. Rebuild Color only while a preview exists or must be removed.
    rig = None
    try:
        owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
        rig = bpy.data.objects.get(owner_name) if owner_name else None
    except FBP_DATA_ERRORS:
        rig = None
    preview_helpers = any(
        bool(node.get("fbp_local_effect_mask_preview", False))
        for node in _fbp_local_mask_helper_nodes(material, kind="COLOR")
    )
    preview_socket = None
    if rig is not None:
        preview_socket, _preview_id = _fbp_local_mask_preview_socket(
            rig, _fbp_stage_effect_nodes(material, "MASK")
        )
    if preview_helpers or preview_socket is not None:
        stages.add("COLOR")

    changed = False
    if "UV" in stages:
        changed = _fbp_rebuild_shader_stage(material, "UV") or changed
    if "COLOR" in stages:
        changed = _fbp_rebuild_shader_stage(material, "COLOR") or changed
    else:
        image_node = _fbp_shader_image_node(material)
        layer_alpha = _fbp_material_layer_alpha_source(material, image_node)
        changed = _fbp_relink_effect_alpha(
            material,
            _fbp_color_stage_evaluation_nodes(material),
            layer_alpha,
        ) or changed
    try:
        if int(material.get("fbp_local_effect_mask_wiring_version", 0) or 0) != FBP_LOCAL_EFFECT_MASK_WIRING_VERSION:
            material["fbp_local_effect_mask_wiring_version"] = FBP_LOCAL_EFFECT_MASK_WIRING_VERSION
            changed = True
    except FBP_DATA_ERRORS:
        pass
    return changed


def _fbp_rebuild_mask_target_batch(material, target_effect_ids):
    """Rebuild local-mask receiver stages once for a group of targets."""
    targets = []
    seen = set()
    for value in tuple(target_effect_ids or ()):
        effect_id = fbp_normalize_effect_id(value)
        if not effect_id or effect_id in seen:
            continue
        seen.add(effect_id)
        targets.append(effect_id)
    if not targets:
        return False
    uv_target = next(
        (value for value in targets if _fbp_effect_mask_target_stage(value) == "UV"),
        None,
    )
    color_target = next(
        (value for value in targets if _fbp_effect_mask_target_stage(value) == "COLOR"),
        None,
    )
    if uv_target and color_target:
        return _fbp_rebuild_mask_target_routing(material, uv_target, color_target)
    target = uv_target or color_target or "LAYER"
    return _fbp_rebuild_mask_target_routing(material, target, target)


def fbp_set_effect_mask_target(rig, mask_effect_id, target_effect_id):
    mask_effect_id = fbp_normalize_effect_id(mask_effect_id)
    if (
        not rig
        or not _fbp_effect_is_local_mask(mask_effect_id)
        or not fbp_effect_is_active(rig, mask_effect_id)
    ):
        return False
    target_effect_id = fbp_normalize_effect_id(target_effect_id)
    if (
        not target_effect_id
        or target_effect_id == mask_effect_id
        or not _fbp_effect_can_receive_mask(target_effect_id)
        or not fbp_effect_is_active(rig, target_effect_id)
    ):
        target_effect_id = "LAYER"
    key = _fbp_effect_mask_target_key(mask_effect_id)
    previous_effective = fbp_effect_mask_target(rig, mask_effect_id)
    try:
        previous_raw = fbp_normalize_effect_id(rig.get(key, "LAYER")) or "LAYER"
        if previous_raw == target_effect_id and previous_effective == target_effect_id:
            return False
        if target_effect_id == "LAYER":
            if key in rig:
                del rig[key]
        else:
            rig[key] = target_effect_id
    except FBP_DATA_ERRORS:
        return False
    _fbp_invalidate_mask_target_cache(rig)
    changed = False
    for material in _fbp_plane_materials(rig):
        changed = _fbp_rebuild_mask_target_routing(
            material, previous_effective, target_effect_id
        ) or changed
    return changed or previous_raw != target_effect_id


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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        value = "FINAL"
    return value if value in modes else modes[0]


def fbp_set_effect_debug_mode(rig, effect_id, mode):
    definition = fbp_effect_definition(effect_id)
    modes = tuple(item[0] for item in definition.get("debug_modes", ()))
    if not rig or not modes:
        return False
    effect_id = fbp_normalize_effect_id(effect_id)
    mode = str(mode or modes[0]).upper()
    if mode not in modes:
        mode = modes[0]

    is_local_preview = bool(
        _fbp_effect_is_local_mask(effect_id)
        and fbp_effect_mask_target(rig, effect_id) != "LAYER"
    )
    reset_preview_ids = []
    if is_local_preview and mode != "FINAL":
        # Only one local mask diagnostic can replace the layer color at a time.
        # Reset older previews silently, then rebuild the COLOR stage once.
        for other_id in fbp_effect_ids_for_rig(rig):
            if other_id == effect_id or not _fbp_effect_is_local_mask(other_id):
                continue
            if fbp_effect_mask_target(rig, other_id) == "LAYER":
                continue
            if fbp_effect_debug_mode(rig, other_id) == "FINAL":
                continue
            try:
                rig[_fbp_effect_state_key(other_id, "debug")] = "FINAL"
                reset_preview_ids.append(other_id)
            except FBP_DATA_ERRORS:
                continue

    key = _fbp_effect_state_key(effect_id, "debug")
    try:
        current = str(rig.get(key, modes[0]) or modes[0]).upper()
        if current != mode:
            rig[key] = mode
            selected_changed = True
        else:
            selected_changed = False
    except FBP_DATA_ERRORS:
        return False
    if not selected_changed and not reset_preview_ids:
        return False

    if definition.get("kind") == "SHADER":
        changed = False
        for other_id in reset_preview_ids:
            changed = fbp_update_shader_effect(rig, other_id) or changed
        if selected_changed:
            changed = fbp_update_shader_effect(rig, effect_id) or changed
        if is_local_preview or reset_preview_ids:
            for material in _fbp_plane_materials(rig):
                changed = _fbp_rebuild_shader_stage(material, "COLOR") or changed
        return changed or True
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
    except FBP_DATA_IO_ERRORS:
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
    except FBP_DATA_IO_ERRORS:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_IO_ERRORS:
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
    return fbp_effect_storage_key(
        "fbp_anim_", fbp_normalize_effect_id(effect_id), f"_{suffix}"
    )


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
FBP_FRAME_SYNC_GEOMETRY_EFFECT_IDS = tuple(
    effect_id
    for effect_id, definition in FBP_EFFECT_REGISTRY.items()
    if definition.get("kind") == "GEOMETRY"
    and (definition.get("alpha_aware") or definition.get("image_aware"))
)
FBP_FRAME_SYNC_SHADER_EFFECT_IDS = tuple(
    effect_id
    for effect_id, definition in FBP_EFFECT_REGISTRY.items()
    if definition.get("kind") == "SHADER"
    and (definition.get("image_aware") or definition.get("mask_source_aware"))
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        pass
    try:
        animation_data = getattr(camera_data, "animation_data", None)
        for curve in getattr(animation_data, "drivers", ()) or ():
            if str(getattr(curve, "data_path", "") or "") in animated_paths:
                return True
    except FBP_DATA_ERRORS:
        pass
    return False


def _fbp_effect_evolution_is_visible(rig, effect_id):
    """Return False when Evolution cannot change the visible result.

    Heavy geometry effects such as Cutout Outline previously rebuilt every held
    frame even with a zero wiggle amount.  Definitions may declare one numeric
    property that must be non-zero before their procedural Evolution needs any
    socket synchronization.
    """
    definition = fbp_effect_definition(effect_id)
    property_name = str((definition or {}).get("evolve_active_property", "") or "")
    if not property_name:
        return True
    try:
        return abs(float(getattr(rig, property_name, 0.0) or 0.0)) > 1.0e-8
    except FBP_DATA_ERRORS:
        return True


def _fbp_image_user_has_animation(image_node):
    """Return whether ImageUser timing is evaluated by F-Curves or drivers.

    A copied Image Texture node follows ordinary sequence playback natively when
    its ImageUser settings are constant. Python synchronization is required only
    when the source ImageUser itself is animated, because private effect nodes do
    not share the source node's F-Curves or drivers.
    """
    if image_node is None:
        return False
    try:
        image_user = getattr(image_node, "image_user", None)
        id_data = getattr(image_node, "id_data", None)
        if image_user is None or id_data is None:
            return False
        paths = {
            image_user.path_from_id(name)
            for name in (
                "frame_offset", "frame_start", "frame_duration",
                "use_cyclic", "use_auto_refresh",
            )
        }
        animation_data = getattr(id_data, "animation_data", None)
        for curve in getattr(animation_data, "drivers", ()) or ():
            if str(getattr(curve, "data_path", "") or "") in paths:
                return True
        return any(
            not bool(getattr(curve, "mute", False))
            and str(getattr(curve, "data_path", "") or "") in paths
            for curve in (fbp_action_fcurves(id_data) or ())
        )
    except FBP_DATA_ERRORS:
        return True


def _fbp_geometry_source_requires_frame_sync(rig):
    """Return whether Geometry Nodes needs an explicit source Frame update."""
    _material, source_node = _fbp_material_image_node(rig)
    try:
        source_image = getattr(source_node, "image", None) if source_node else None
        return str(getattr(source_image, "source", "") or "").upper() in {"SEQUENCE", "MOVIE"}
    except FBP_DATA_ERRORS:
        return True


def _fbp_shader_source_requires_frame_sync(rig, active_effect_ids):
    """Return whether private shader samplers need evaluated timing/runtime data."""
    active_effect_ids = set(active_effect_ids or ())
    if FBP_EFFECT_DEPTH_BLUR in active_effect_ids:
        try:
            if str(getattr(rig, "fbp_depth_blur_mode", "MANUAL") or "MANUAL").upper() == "DEPTH":
                return True
        except FBP_DATA_ERRORS:
            return True

    _material, source_node = _fbp_material_image_node(rig)
    try:
        source_image = getattr(source_node, "image", None) if source_node else None
        source_kind = str(getattr(source_image, "source", "") or "").upper()
    except FBP_DATA_ERRORS:
        source_kind = ""
    if source_kind in {"SEQUENCE", "MOVIE"} and _fbp_image_user_has_animation(source_node):
        return True

    for effect_id in active_effect_ids:
        definition = fbp_effect_definition(effect_id)
        if not bool(definition.get("mask_source_aware", False)):
            continue
        source_property = str(definition.get("mask_source_property", "") or "")
        if not source_property:
            continue
        try:
            source_rig = getattr(rig, source_property, None)
        except FBP_DATA_ERRORS:
            return True
        if source_rig is None:
            continue
        _source_material, mask_node = _fbp_material_image_node(source_rig)
        try:
            mask_image = getattr(mask_node, "image", None) if mask_node else None
            mask_kind = str(getattr(mask_image, "source", "") or "").upper()
        except FBP_DATA_ERRORS:
            mask_kind = ""
        if mask_kind in {"SEQUENCE", "MOVIE"} and _fbp_image_user_has_animation(mask_node):
            return True
        animated_bounds = {
            "fbp_crop_left", "fbp_crop_right", "fbp_crop_top", "fbp_crop_bottom",
            "fbp_extend_left", "fbp_extend_right", "fbp_extend_top", "fbp_extend_bottom",
            "fbp_opacity",
        }
        try:
            if any(
                not bool(getattr(curve, "mute", False))
                and str(getattr(curve, "data_path", "") or "") in animated_bounds
                for curve in (fbp_action_fcurves(source_rig) or ())
            ):
                return True
        except FBP_DATA_ERRORS:
            return True
    return False


def _fbp_effect_evolve_step_signature(rig, evolve_pairs, scene):
    """Return the held Evolution state that can alter visible socket values."""
    try:
        frame = int(getattr(scene, "frame_current", 1))
        start = int(getattr(scene, "frame_start", 1))
    except FBP_DATA_ERRORS:
        return None
    result = []
    for effect_id, property_key in evolve_pairs or ():
        try:
            if not bool(getattr(rig, property_key, False)):
                continue
            if not _fbp_effect_evolution_is_visible(rig, effect_id):
                continue
            state = fbp_read_effect_animation_state(rig, effect_id)
            step = max(1, int(state.get("step", 4) or 4))
            step_index = max(0, math.floor((frame - start) / step))
            definition = fbp_effect_definition(effect_id)
            speed = 1.0
            if effect_id == FBP_EFFECT_WAVE_WARP:
                speed = float(getattr(rig, "fbp_wave_warp_speed", 1.0) or 0.0)
            elif effect_id == FBP_EFFECT_RIPPLE_DISTORTION:
                speed = float(getattr(rig, "fbp_ripple_distortion_speed", 1.0) or 0.0)
            result.append((
                effect_id,
                step_index,
                int(state.get("seed", 0) or 0),
                bool(state.get("unique", False)),
                int(state.get("layer_seed", 0) or 0),
                round(float(state.get("amount", definition.get("evolve_amount", 1.0)) or 0.0), 9),
                round(speed, 9),
            ))
        except FBP_DATA_ERRORS:
            return None
    return tuple(result)


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

    geometry_sync_ids = set(FBP_FRAME_SYNC_GEOMETRY_EFFECT_IDS)
    shader_sync_ids = set(FBP_FRAME_SYNC_SHADER_EFFECT_IDS)
    for rig in rigs:
        try:
            active_effect_ids = set(_fbp_runtime_effect_ids(rig))
            if not active_effect_ids:
                continue
            if (
                FBP_EFFECT_LATTICE in active_effect_ids
                and _fbp_lattice_mode(rig) == "CAMERA_FLATTEN"
                and bool(getattr(rig, "fbp_lattice_live_update", True))
            ):
                return True
            if (
                active_effect_ids.intersection(geometry_sync_ids)
                and _fbp_geometry_source_requires_frame_sync(rig)
            ):
                return True
            if (
                active_effect_ids.intersection(shader_sync_ids)
                and _fbp_shader_source_requires_frame_sync(rig, active_effect_ids)
            ):
                return True
            if _fbp_scene_camera_binding_is_animated(scene, active_effect_ids):
                return True
            if any(
                effect_id in active_effect_ids
                and bool(getattr(rig, property_key, False))
                and _fbp_effect_evolution_is_visible(rig, effect_id)
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
        except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        try:
            if key not in rig:
                rig[key] = default
        except FBP_DATA_ERRORS:
            pass


def fbp_assign_effect_layer_seed(rig, effect_id, *, force=False):
    """Return a persistent per-layer seed for a specific effect."""
    if not rig:
        return 0
    key = _fbp_animation_key(effect_id, "layer_seed")
    try:
        current = int(getattr(rig, key, 0) or 0) if hasattr(rig, key) else int(rig.get(key, 0) or 0)
    except FBP_DATA_ERRORS:
        current = 0
    if force or current <= 0:
        current = int(uuid.uuid4().int % 2147483646) + 1
        try:
            if hasattr(rig, key):
                fbp_set_rna_property_silent(rig, key, current)
            else:
                rig[key] = current
        except FBP_DATA_ERRORS:
            pass
    return current


def _fbp_effect_animation_defaults(definition):
    return {
        "evolve": (False, None, None, "Advance the procedural parameter progressively over time"),
        "step": (4, 1, 240, "Number of frames held before the progressive value advances again"),
        "seed": (0, 0, 999999, "Choose the initial phase or integer offset used by Evolution"),
        "unique": (False, None, None, "Give every layer an independent starting phase while preserving progressive motion"),
        "layer_seed": (0, 0, 2147483647, "Persistent internal seed used by Unique per Layer"),
        # Hidden increment shared by the current progressive effect stack.
        "amount": (float(definition.get("evolve_amount", 1.0)), -100000.0, 100000.0, "Amount added at each Evolution step"),
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
        except FBP_DATA_ERRORS:
            result[suffix] = default
    if bool(result.get("unique", False)) and int(result.get("layer_seed", 0) or 0) <= 0:
        try:
            stable_name = str(getattr(rig, "name_full", getattr(rig, "name", "")) or "")
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
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
        if effect_id == FBP_EFFECT_WAVE_WARP:
            amount *= float(getattr(rig, "fbp_wave_warp_speed", 1.0) or 0.0)
        elif effect_id == FBP_EFFECT_RIPPLE_DISTORTION:
            amount *= float(getattr(rig, "fbp_ripple_distortion_speed", 1.0) or 0.0)
        scene = scene or getattr(bpy.context, "scene", None)
        frame = int(getattr(scene, "frame_current", 1))
        start = int(getattr(scene, "frame_start", 1))
        step_index = max(0, math.floor((frame - start) / stepped_frames))

        # Evolution is a progression, not bounded random jitter. Each held
        # step advances from the visible base value by the configured amount.
        # For non-seed parameters, Seed/Per Layer can only choose one constant
        # starting phase; the value still grows monotonically frame after frame.
        if definition.get("evolve_mode") == "SEED_STEP":
            unique_offset = stream_seed if (stream_seed or bool(state.get("unique", False))) else 0
            return int(round(base + unique_offset + (amount * step_index)))

        phase = 0.0
        if stream_seed or bool(state.get("unique", False)):
            phase = _fbp_effect_noise_u01(effect_id, stream_seed, 0)
        return base + (amount * (step_index + phase))
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
            _FBP_EFFECT_RUNTIME_STATS["handler_runs"] = int(
                _FBP_EFFECT_RUNTIME_STATS.get("handler_runs", 0) or 0
            ) + 1
        except (AttributeError, TypeError, ValueError):
            pass
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
                shader_source_sync = bool(
                    runtime_profile.get("shader_source_sync", False)
                )
                animated_effect_properties = runtime_profile.get(
                    "animated_effect_properties", {}
                ) or {}
                has_animated_effects = bool(animated_effect_properties)
                lattice_live = bool(
                    FBP_EFFECT_LATTICE in active_effect_ids
                    and _fbp_lattice_mode(rig) == "CAMERA_FLATTEN"
                    and bool(getattr(rig, "fbp_lattice_live_update", True))
                )
                if lattice_live:
                    _fbp_apply_lattice_camera_flatten(rig, scene=scene, force=False)
                evolve_pairs = runtime_profile.get("evolve_pairs", ()) or ()
                evolve_enabled = any(
                    bool(getattr(rig, property_key, False))
                    and _fbp_effect_evolution_is_visible(rig, effect_id)
                    for effect_id, property_key in evolve_pairs
                )
                if not (geometry_source_sync or shader_source_sync or has_animated_effects or evolve_enabled or lattice_live):
                    continue

                profile_key = _fbp_effect_ids_cache_key(rig)
                if (
                    evolve_enabled
                    and not geometry_source_sync
                    and not shader_source_sync
                    and not has_animated_effects
                ):
                    evolve_signature = _fbp_effect_evolve_step_signature(
                        rig, evolve_pairs, scene
                    )
                    if (
                        profile_key and profile_key[0]
                        and evolve_signature is not None
                        and _FBP_EFFECT_EVOLVE_STEP_CACHE.get(profile_key) == evolve_signature
                    ):
                        _FBP_EFFECT_RUNTIME_STATS["held_step_skips"] = int(
                            _FBP_EFFECT_RUNTIME_STATS.get("held_step_skips", 0) or 0
                        ) + 1
                        continue
                    if profile_key and profile_key[0] and evolve_signature is not None:
                        if (
                            len(_FBP_EFFECT_EVOLVE_STEP_CACHE) >= 512
                            and profile_key not in _FBP_EFFECT_EVOLVE_STEP_CACHE
                        ):
                            _FBP_EFFECT_EVOLVE_STEP_CACHE.clear()
                        _FBP_EFFECT_EVOLVE_STEP_CACHE[profile_key] = evolve_signature
                elif profile_key and profile_key[0]:
                    _FBP_EFFECT_EVOLVE_STEP_CACHE.pop(profile_key, None)

                _FBP_EFFECT_RUNTIME_STATS["rig_updates"] = int(
                    _FBP_EFFECT_RUNTIME_STATS.get("rig_updates", 0) or 0
                ) + 1

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
                        scene=scene,
                    )

            except FBP_DATA_ERRORS:
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
                    if animated_effect_id == FBP_EFFECT_CAMERA_BILLBOARD:
                        _fbp_apply_track_to_camera_constraint(rig, scene)
                    elif definition.get("kind") == "GEOMETRY":
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
                        if animated_effect_id == FBP_EFFECT_PIXELATE:
                            _fbp_refresh_extrude_pixel_dependency(
                                rig,
                                modifier=runtime_profile.get(
                                    "geometry_modifiers", {}
                                ).get(FBP_EFFECT_THICKNESS),
                                scene=scene,
                            )
                    updated_effect_ids.add(animated_effect_id)
                except FBP_DATA_ERRORS:
                    _fbp_invalidate_effect_runtime_profile(rig)
                    continue

            if not evolve_enabled:
                continue

            # Avoid allocating a temporary tuple for every rig on every frame.
            for effect_id, property_key in evolve_pairs:
                try:
                    if not bool(getattr(rig, property_key, False)):
                        continue
                    if not _fbp_effect_evolution_is_visible(rig, effect_id):
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
                except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        return []


def _fbp_plane(rig, *, repair=True):
    """Resolve the mesh plane owned by ``rig`` and repair recoverable pointers.

    The explicit pointer remains authoritative, but generated test scenes,
    duplicated rigs and older files can briefly retain only the parent/metadata
    relation. Lattice and other mesh-only tools should recover that plane rather
    than reporting a false compatibility error.
    """
    if not rig:
        return None
    try:
        plane = getattr(rig, "fbp_plane_target", None)
        if plane and getattr(plane, "type", "") == "MESH":
            return plane
    except FBP_DATA_ERRORS:
        plane = None

    tagged = []
    fallback = []
    owner_name = str(getattr(rig, "name", "") or "")
    try:
        # Scan globally rather than only through ``rig.children``. Undo, object
        # duplication and generated test scenes can temporarily lose parenting
        # while preserving the explicit owner metadata.
        for child in tuple(getattr(bpy.data, "objects", ()) or ()):
            if str(getattr(child, "type", "") or "") != "MESH":
                continue
            is_parented = getattr(child, "parent", None) is rig
            try:
                stored_owner = str(child.get("fbp_parent_rig_name", "") or "")
            except FBP_DATA_ERRORS:
                stored_owner = ""
            if not is_parented and stored_owner != owner_name:
                continue
            fallback.append(child)
            if bool(getattr(child, "is_fbp_plane", False)) or stored_owner == owner_name:
                tagged.append(child)
    except FBP_DATA_ERRORS:
        return None

    candidate = tagged[0] if len(tagged) == 1 else (fallback[0] if not tagged and len(fallback) == 1 else None)
    if candidate is None:
        return None
    if repair and not fbp_render_mutation_blocked():
        try:
            rig.fbp_plane_target = candidate
            candidate.is_fbp_plane = True
            try:
                if getattr(candidate, "data", None) is not None:
                    candidate.data["fbp_plane_mesh"] = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            candidate["fbp_parent_rig_name"] = str(rig.name)
        except FBP_DATA_ERRORS:
            pass
    return candidate


def _fbp_lattice_compatibility_issue(rig):
    """Return a user-facing reason when Lattice cannot be created."""
    if rig is None:
        return "Select a Frame By Plane layer"
    plane = _fbp_plane(rig, repair=True)
    if plane is None:
        return "The selected rig has no recoverable mesh plane. Run Tools > Repair Safe Issues"
    try:
        if getattr(plane, "data", None) is None:
            return "The linked plane has no mesh datablock"
        if len(getattr(plane.data, "vertices", ())) < 3:
            return "The linked mesh has insufficient geometry for a Lattice"
    except FBP_DATA_ERRORS:
        return "The linked mesh is temporarily unavailable"
    if fbp_render_mutation_blocked():
        return "Lattice cannot be created while Blender is rendering or rebuilding data"
    return ""


_FBP_LATTICE_OWNER_KEY = "fbp_lattice_owner"
_FBP_LATTICE_EFFECT_KEY = "fbp_lattice_effect"
_FBP_LATTICE_SCHEMA_KEY = "fbp_lattice_schema"
_FBP_LATTICE_MODE_KEY = "fbp_lattice_mode"
_FBP_LATTICE_BAKED_KEY = "fbp_lattice_baked"
_FBP_LATTICE_SCHEMA_VERSION = 9
_FBP_LATTICE_MODIFIER_NAME = "FBP • Lattice"
_FBP_LATTICE_DETAIL_MODIFIER_NAME = "FBP • Lattice Detail"
# 6.0.38-6.0.40 stored a transform-baking bridge on the cage object.
# Native Lattice editing is now kept entirely in Edit Mode; these keys are
# removed lazily from existing helpers so old files stop triggering feedback
# loops without discarding their current point deformation.
_FBP_LATTICE_LEGACY_TRANSFORM_KEYS = (
    "fbp_lattice_rest_local",
    "fbp_lattice_base_points",
    "fbp_lattice_object_signature",
)
# Regular Blender modifiers such as LatticeModifier and SubsurfModifier do not
# accept arbitrary ID properties. Keep their stable names on the owning mesh
# object instead of writing modifier["..."] tags. Geometry Nodes modifiers are
# different and may still use ID properties for socket values elsewhere.
_FBP_LATTICE_MODIFIER_REF_KEY = "fbp_lattice_modifier_name"
_FBP_LATTICE_DETAIL_REF_KEY = "fbp_lattice_detail_modifier_name"
_FBP_LATTICE_HELPER_NAME_KEY = "fbp_lattice_helper_name"
_FBP_LATTICE_FLATTEN_CACHE = {}
_FBP_LATTICE_UPDATE_PENDING = set()
_FBP_LATTICE_LAST_ACTIVITY = {}
_FBP_LATTICE_LAST_ERROR = {}
# Helper resolution is called by sidebar drawing, stack syncing and audits. Cache
# both positive and negative legacy scans so a missing cage never causes a full
# bpy.data.objects walk on every UI redraw. The cache is naturally invalidated
# when the object count changes and explicitly cleared on load/undo/rebuild.
_FBP_LATTICE_HELPER_RESOLVE_CACHE = {}
_FBP_LATTICE_REPAIR_PENDING = set()
_FBP_LATTICE_REPAIR_ATTEMPTED = {}
# Live Camera Flatten rigs are indexed per Scene. Freeform cages are fully native
# and therefore keep an indefinitely reusable empty index until an explicit
# effect/property/object-count change invalidates it.
_FBP_LATTICE_LIVE_SCENE_CACHE = {}


def _fbp_lattice_error_key(rig):
    try:
        key = fbp_obj_runtime_key(rig)
        if key is not None:
            return ("PTR", int(key))
    except FBP_DATA_ERRORS:
        pass
    try:
        return ("NAME", str(getattr(rig, "name_full", getattr(rig, "name", "")) or ""))
    except FBP_DATA_ERRORS:
        return ("NAME", "")


def _fbp_set_lattice_error(rig, message, exc=None):
    text = str(message or "Lattice setup failed").strip() or "Lattice setup failed"
    if exc is not None:
        detail = str(exc).strip()
        if detail and detail.lower() not in text.lower():
            text = f"{text}: {detail}"
    if len(text) > 240:
        text = text[:237].rstrip() + "..."
    key = _fbp_lattice_error_key(rig)
    if len(_FBP_LATTICE_LAST_ERROR) >= 512 and key not in _FBP_LATTICE_LAST_ERROR:
        _FBP_LATTICE_LAST_ERROR.clear()
    _FBP_LATTICE_LAST_ERROR[key] = text
    fbp_warn(text, exc)
    return text


def _fbp_clear_lattice_error(rig):
    _FBP_LATTICE_LAST_ERROR.pop(_fbp_lattice_error_key(rig), None)


def _fbp_last_lattice_error(rig):
    return str(_FBP_LATTICE_LAST_ERROR.get(_fbp_lattice_error_key(rig), "") or "")


def _fbp_stabilize_lattice_helper(helper):
    """Keep the cage in a stable native Lattice coordinate space.

    A previous bridge watched Object Mode transforms, baked them into every
    control point, and then restored the object matrix. Both writes generated
    new depsgraph updates, so Blender could alternate forever between the rig
    transform and the temporary cage transform. Native Lattice deformation is
    reliable when the cage object remains fixed and its planar points are edited
    in Edit Mode. A single point controls one visible cage intersection; pressing
    A still selects the entire cage for whole-grid G/R/S transforms.
    """
    if helper is None:
        return False
    changed = False
    try:
        for key in _FBP_LATTICE_LEGACY_TRANSFORM_KEYS:
            if key in helper:
                del helper[key]
                changed = True
        locked = (True, True, True)
        for attribute in ("lock_location", "lock_rotation", "lock_scale"):
            if tuple(bool(value) for value in getattr(helper, attribute, (False, False, False))) != locked:
                setattr(helper, attribute, locked)
                changed = True
    except FBP_DATA_ERRORS:
        return changed
    return changed


def _fbp_lattice_contract_is_valid(rig, plane=None, helper=None, modifier=None):
    """Return True only when the complete generated Lattice contract is usable."""
    if rig is None:
        return False
    plane = plane or _fbp_plane(rig, repair=False)
    helper = helper or _fbp_lattice_object(rig)
    modifier = modifier or _fbp_lattice_modifier(plane)
    try:
        return bool(
            plane is not None
            and getattr(plane, "type", "") == "MESH"
            and getattr(plane, "data", None) is not None
            and helper is not None
            and getattr(helper, "type", "") == "LATTICE"
            and getattr(helper, "data", None) is not None
            and modifier is not None
            and getattr(modifier, "type", "") == "LATTICE"
            and getattr(modifier, "object", None) is helper
        )
    except FBP_DATA_ERRORS:
        return False


def _fbp_scene_collections(scene):
    """Yield Scene collections once without relying on the active UI context."""
    if scene is None:
        return
    try:
        stack = [scene.collection]
    except FBP_DATA_ERRORS:
        return
    seen = set()
    while stack:
        collection = stack.pop()
        try:
            key = int(collection.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(collection)
        if key in seen:
            continue
        seen.add(key)
        yield collection
        try:
            stack.extend(tuple(collection.children))
        except FBP_DATA_ERRORS:
            pass


def _fbp_collection_in_scene(scene, collection):
    if scene is None or collection is None:
        return False
    try:
        return any(candidate is collection for candidate in _fbp_scene_collections(scene))
    except FBP_DATA_ERRORS:
        return False


def _fbp_lattice_target_collection(rig, plane, context=None):
    """Choose a writable collection that belongs to the current Scene.

    The old implementation blindly used ``plane.users_collection[0]``. A plane
    can be linked into multiple Scenes, so that collection may be outside the
    active View Layer; the later visibility call then raises and leaves a
    half-created cage behind. Prefer collections owned by the active Scene and
    fall back to its root collection.
    """
    context = context or getattr(bpy, "context", None)
    scene = getattr(context, "scene", None) if context is not None else None
    candidates = []
    for obj in (plane, rig):
        try:
            candidates.extend(tuple(getattr(obj, "users_collection", ()) or ()))
        except FBP_DATA_ERRORS:
            pass
    try:
        active_collection = getattr(context, "collection", None)
        if active_collection is not None:
            candidates.append(active_collection)
    except FBP_DATA_ERRORS:
        pass
    seen = set()
    for collection in candidates:
        if collection is None:
            continue
        try:
            key = int(collection.as_pointer())
        except FBP_DATA_ERRORS:
            key = id(collection)
        if key in seen:
            continue
        seen.add(key)
        if scene is None or _fbp_collection_in_scene(scene, collection):
            return collection
    try:
        return scene.collection if scene is not None else None
    except FBP_DATA_ERRORS:
        return None


def _fbp_ensure_lattice_link(helper, rig, plane, context=None):
    context = context or getattr(bpy, "context", None)
    target_collection = _fbp_lattice_target_collection(rig, plane, context)
    if helper is None or target_collection is None:
        _fbp_set_lattice_error(rig, "No writable Scene collection is available for the Lattice cage")
        return False
    first_error = None
    candidates = [target_collection]
    try:
        scene_root = getattr(getattr(context, "scene", None), "collection", None)
        if scene_root is not None and scene_root is not target_collection:
            candidates.append(scene_root)
    except FBP_DATA_ERRORS:
        pass
    for collection in candidates:
        try:
            if not any(existing is collection for existing in helper.users_collection):
                collection.objects.link(helper)
            try:
                view_layer = getattr(context, "view_layer", None)
                if view_layer is not None:
                    view_layer.update()
            except FBP_DATA_ERRORS:
                pass
            return True
        except FBP_DATA_ERRORS as exc:
            if first_error is None:
                first_error = exc
    _fbp_set_lattice_error(rig, "Could not link the Lattice cage to the active Scene", first_error)
    return False


def _fbp_cleanup_incomplete_lattice_setup(rig, *, force=False):
    """Remove owned partial Lattice data, including failed previous attempts.

    A merely linked helper/modifier pair is not enough to count as healthy. The
    previous early return preserved broken cages after a visibility or View
    Layer error, which explains the common pattern where the first click created
    something but reported an error and every following click failed again.
    """
    if rig is None:
        return False
    plane = _fbp_plane(rig, repair=False)
    helper = _fbp_lattice_object(rig)
    modifier = _fbp_lattice_modifier(plane)
    if not force and _fbp_lattice_contract_is_valid(rig, plane, helper, modifier):
        return False

    changed = False
    if plane is not None:
        stored_names = set()
        for key in (_FBP_LATTICE_MODIFIER_REF_KEY, _FBP_LATTICE_DETAIL_REF_KEY):
            try:
                name = str(plane.get(key, "") or "")
                if name:
                    stored_names.add(name)
            except FBP_DATA_ERRORS:
                pass
        for owned in tuple(getattr(plane, "modifiers", ()) or ()):
            try:
                name = str(getattr(owned, "name", "") or "")
                is_owned = (
                    name in stored_names
                    or (getattr(owned, "type", "") == "LATTICE" and _fbp_modifier_name_matches(
                        owned, _FBP_LATTICE_MODIFIER_NAME
                    ))
                    or (getattr(owned, "type", "") == "SUBSURF" and _fbp_modifier_name_matches(
                        owned, _FBP_LATTICE_DETAIL_MODIFIER_NAME
                    ))
                )
                if is_owned:
                    plane.modifiers.remove(owned)
                    changed = True
            except FBP_DATA_ERRORS:
                continue
        _fbp_store_modifier_reference(plane, _FBP_LATTICE_MODIFIER_REF_KEY, None)
        _fbp_store_modifier_reference(plane, _FBP_LATTICE_DETAIL_REF_KEY, None)

    owner_name = str(getattr(rig, "name", "") or "")
    helpers = []
    if helper is not None:
        helpers.append(helper)
    try:
        for obj in tuple(getattr(bpy.data, "objects", ()) or ()):
            if getattr(obj, "type", "") != "LATTICE" or obj in helpers:
                continue
            try:
                owned = (
                    str(obj.get(_FBP_LATTICE_OWNER_KEY, "") or "") == owner_name
                    or (
                        getattr(obj, "parent", None) is rig
                        and str(obj.get(_FBP_LATTICE_EFFECT_KEY, "") or "") == FBP_EFFECT_LATTICE
                    )
                )
            except FBP_DATA_ERRORS:
                owned = False
            if owned:
                helpers.append(obj)
    except FBP_DATA_ERRORS:
        pass

    for owned_helper in helpers:
        data = getattr(owned_helper, "data", None)
        try:
            bpy.data.objects.remove(owned_helper, do_unlink=True)
            changed = True
        except FBP_DATA_ERRORS:
            pass
        try:
            if data is not None and data.users == 0:
                bpy.data.lattices.remove(data)
        except FBP_DATA_ERRORS:
            pass
    try:
        if getattr(rig, "fbp_lattice_object", None) is not None:
            rig.fbp_lattice_object = None
            changed = True
        if _FBP_LATTICE_HELPER_NAME_KEY in rig:
            del rig[_FBP_LATTICE_HELPER_NAME_KEY]
            changed = True
    except FBP_DATA_ERRORS:
        pass
    repair_key = _fbp_lattice_error_key(rig)
    _FBP_LATTICE_HELPER_RESOLVE_CACHE.pop(repair_key, None)
    _FBP_LATTICE_REPAIR_ATTEMPTED.pop(repair_key, None)
    _FBP_LATTICE_REPAIR_PENDING.discard(repair_key)
    return changed

def _fbp_claim_lattice_helper(rig, helper, *, trusted=False):
    """Repair and return a cage owned by ``rig``.

    A rig pointer, parent relation or Lattice modifier binding is authoritative.
    Older builds stored only a readable owner name, which becomes stale after a
    layer rename and previously made a perfectly valid cage look missing.
    """
    if rig is None or helper is None:
        return None
    try:
        if getattr(helper, "type", "") != "LATTICE" or getattr(helper, "data", None) is None:
            return None
        owner_name = str(getattr(rig, "name", "") or "")
        stored_owner = str(helper.get(_FBP_LATTICE_OWNER_KEY, "") or "")
        helper_parent = getattr(helper, "parent", None)
        parent_matches = helper_parent is rig
        # Duplicating a layer can temporarily copy PointerProperties and modifier
        # bindings to the original cage. Never steal a cage that is still owned
        # by another live Frame By Plane rig; the transactional apply path will
        # instead remove the copied binding and create a private helper.
        foreign_parent = bool(
            helper_parent is not None
            and helper_parent is not rig
            and bool(getattr(helper_parent, "is_fbp_control", False))
        )
        foreign_owner = None
        if stored_owner and stored_owner != owner_name:
            foreign_owner = bpy.data.objects.get(stored_owner)
        foreign_owner_live = bool(
            foreign_owner is not None
            and foreign_owner is not rig
            and bool(getattr(foreign_owner, "is_fbp_control", False))
        )
        if (foreign_parent or foreign_owner_live) and not parent_matches:
            return None
        if not trusted and stored_owner not in {"", owner_name} and not parent_matches:
            return None
        # Resolver calls happen during every sidebar redraw. Write Blender data
        # only when repair is actually needed; assigning an unchanged ID property
        # still tags the datablock and can trigger unnecessary depsgraph work.
        if stored_owner != owner_name:
            helper[_FBP_LATTICE_OWNER_KEY] = owner_name
        if str(helper.get(_FBP_LATTICE_EFFECT_KEY, "") or "") != FBP_EFFECT_LATTICE:
            helper[_FBP_LATTICE_EFFECT_KEY] = FBP_EFFECT_LATTICE
        if not parent_matches:
            world = helper.matrix_world.copy()
            helper.parent = rig
            helper.matrix_world = world
        if getattr(rig, "fbp_lattice_object", None) is not helper:
            rig.fbp_lattice_object = helper
        try:
            if str(rig.get(_FBP_LATTICE_HELPER_NAME_KEY, "") or "") != str(helper.name):
                rig[_FBP_LATTICE_HELPER_NAME_KEY] = str(helper.name)
        except FBP_DATA_ERRORS:
            pass
        cache_key = _fbp_lattice_error_key(rig)
        try:
            object_count = len(bpy.data.objects)
        except FBP_DATA_ERRORS:
            object_count = -1
        _FBP_LATTICE_HELPER_RESOLVE_CACHE[cache_key] = (object_count, str(helper.name))
        return helper
    except FBP_DATA_ERRORS:
        return None


def _fbp_lattice_object(rig):
    """Resolve the owned cage with O(1) common paths and one cached legacy scan."""
    if rig is None:
        return None

    # 1. The saved pointer is the fastest and strongest ownership signal.
    try:
        helper = _fbp_claim_lattice_helper(
            rig, getattr(rig, "fbp_lattice_object", None), trusted=True
        )
        if helper is not None:
            return helper
    except FBP_DATA_ERRORS:
        pass

    # Cached legacy resolution comes before any collection/property walks. The
    # common missing-cage UI state then costs only two dictionary lookups.
    cache_key = _fbp_lattice_error_key(rig)
    try:
        object_count = len(bpy.data.objects)
    except FBP_DATA_ERRORS:
        object_count = -1
    cached = _FBP_LATTICE_HELPER_RESOLVE_CACHE.get(cache_key)
    if cached is not None and int(cached[0]) == object_count:
        cached_name = str(cached[1] or "")
        if not cached_name:
            return None
        helper = _fbp_claim_lattice_helper(
            rig, bpy.data.objects.get(cached_name), trusted=True
        )
        if helper is not None:
            return helper

    # 2. The modifier binding is authoritative even when rename/undo invalidated
    # the rig pointer or readable owner metadata. This is the main repair path
    # for 6.0.38-6.0.44 files reporting a false incomplete cage.
    try:
        plane = _fbp_plane(rig, repair=False)
        modifier = _fbp_lattice_modifier(plane)
        candidate = getattr(modifier, "object", None) if modifier is not None else None
        helper = _fbp_claim_lattice_helper(rig, candidate, trusted=True)
        if helper is not None:
            return helper
    except FBP_DATA_ERRORS:
        pass

    # 3. Stored helper name survives PointerProperty recovery failures cheaply.
    try:
        helper_name = str(rig.get(_FBP_LATTICE_HELPER_NAME_KEY, "") or "")
        if helper_name:
            helper = _fbp_claim_lattice_helper(
                rig, bpy.data.objects.get(helper_name), trusted=True
            )
            if helper is not None:
                return helper
    except FBP_DATA_ERRORS:
        pass

    # 4. Legacy metadata-only files require one global scan. Cache the negative
    # result as well: this function is called from panel draw and must stay O(1)
    # after the first recovery attempt. ``Object.children`` is intentionally not
    # used here because Blender computes it by scanning every Object.
    owner_name = str(getattr(rig, "name", "") or "")
    if not owner_name:
        return None
    cached = _FBP_LATTICE_HELPER_RESOLVE_CACHE.get(cache_key)
    if cached is not None and int(cached[0]) == object_count:
        cached_name = str(cached[1] or "")
        if not cached_name:
            return None
        helper = _fbp_claim_lattice_helper(
            rig, bpy.data.objects.get(cached_name), trusted=True
        )
        if helper is not None:
            return helper

    helper = None
    try:
        for obj in tuple(getattr(bpy.data, "objects", ()) or ()):
            try:
                if getattr(obj, "type", "") != "LATTICE":
                    continue
                metadata_owner = str(obj.get(_FBP_LATTICE_OWNER_KEY, "") or "") == owner_name
                parent_owner = (
                    getattr(obj, "parent", None) is rig
                    and str(obj.get(_FBP_LATTICE_EFFECT_KEY, "") or "") == FBP_EFFECT_LATTICE
                )
                if not (metadata_owner or parent_owner):
                    continue
            except FBP_DATA_ERRORS:
                continue
            helper = _fbp_claim_lattice_helper(rig, obj, trusted=True)
            if helper is not None:
                break
    except FBP_DATA_ERRORS:
        helper = None
    _FBP_LATTICE_HELPER_RESOLVE_CACHE[cache_key] = (
        object_count, str(getattr(helper, "name", "") or "")
    )
    return helper


def _fbp_modifier_name_matches(modifier, base_name):
    """Match an addon-owned modifier without relying on unsupported ID props."""
    try:
        name = str(getattr(modifier, "name", "") or "")
        return name == base_name or name.startswith(f"{base_name}.")
    except FBP_DATA_ERRORS:
        return False


def _fbp_stored_modifier(plane, key, modifier_type):
    if plane is None:
        return None
    try:
        name = str(plane.get(key, "") or "")
        if not name:
            return None
        modifier = plane.modifiers.get(name)
        if modifier is not None and str(getattr(modifier, "type", "") or "") == modifier_type:
            return modifier
    except FBP_DATA_ERRORS:
        pass
    return None


def _fbp_store_modifier_reference(plane, key, modifier):
    if plane is None:
        return False
    try:
        if modifier is None:
            if key in plane:
                del plane[key]
        else:
            plane[key] = str(modifier.name)
        return True
    except FBP_DATA_ERRORS:
        return False


def _fbp_lattice_modifier(plane):
    if plane is None:
        return None
    stored = _fbp_stored_modifier(plane, _FBP_LATTICE_MODIFIER_REF_KEY, "LATTICE")
    if stored is not None:
        return stored
    for modifier in tuple(getattr(plane, "modifiers", ())):
        try:
            if getattr(modifier, "type", "") == "LATTICE" and _fbp_modifier_name_matches(
                modifier, _FBP_LATTICE_MODIFIER_NAME
            ):
                _fbp_store_modifier_reference(plane, _FBP_LATTICE_MODIFIER_REF_KEY, modifier)
                return modifier
        except FBP_DATA_ERRORS:
            continue
    return None


def _fbp_lattice_detail_modifier(plane):
    if plane is None:
        return None
    stored = _fbp_stored_modifier(plane, _FBP_LATTICE_DETAIL_REF_KEY, "SUBSURF")
    if stored is not None:
        return stored
    for modifier in tuple(getattr(plane, "modifiers", ())):
        try:
            if getattr(modifier, "type", "") == "SUBSURF" and _fbp_modifier_name_matches(
                modifier, _FBP_LATTICE_DETAIL_MODIFIER_NAME
            ):
                _fbp_store_modifier_reference(plane, _FBP_LATTICE_DETAIL_REF_KEY, modifier)
                return modifier
        except FBP_DATA_ERRORS:
            continue
    return None


def _fbp_lattice_mesh_detail_mode(rig):
    try:
        mode = str(getattr(rig, "fbp_lattice_mesh_detail_mode", "AUTO") or "AUTO").upper()
    except FBP_DATA_ERRORS:
        mode = "AUTO"
    return mode if mode in {"AUTO", "CUSTOM"} else "AUTO"


def _fbp_lattice_mesh_density_multiplier(rig):
    try:
        density = str(getattr(rig, "fbp_lattice_mesh_density", "DOUBLE") or "DOUBLE").upper()
    except FBP_DATA_ERRORS:
        density = "DOUBLE"
    return {"MATCH": 1.0, "DOUBLE": 2.0, "QUADRUPLE": 4.0}.get(density, 2.0)


_FBP_LATTICE_GRID_PRESET_LOOPS = {
    "CORNERS": (0, 0),
    "BASIC": (1, 1),
    "LOOPS_2": (2, 2),
    "LOOPS_4": (4, 4),
}


def _fbp_lattice_grid_loops(rig):
    """Return internal loop counts; corner control points are not counted."""
    try:
        preset = str(getattr(rig, "fbp_lattice_grid_preset", "LOOPS_2") or "LOOPS_2").upper()
    except FBP_DATA_ERRORS:
        preset = "LOOPS_2"
    if preset in _FBP_LATTICE_GRID_PRESET_LOOPS:
        return _FBP_LATTICE_GRID_PRESET_LOOPS[preset]
    try:
        loops_u = max(0, min(62, int(getattr(rig, "fbp_lattice_custom_loops_u", 6) or 0)))
        loops_v = max(0, min(62, int(getattr(rig, "fbp_lattice_custom_loops_v", 6) or 0)))
    except FBP_DATA_ERRORS:
        loops_u = loops_v = 6
    return loops_u, loops_v


def _fbp_sync_lattice_grid_preset_from_points(rig):
    """Infer the new loop-based UI from an older saved point resolution.

    This migration changes only RNA controls. It never rebuilds the cage or
    touches edited Lattice points, so opening a 6.0.45 project is lossless.
    """
    if rig is None:
        return False
    try:
        if bool(rig.is_property_set("fbp_lattice_grid_preset")):
            return False
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        # Some Blender data proxies do not expose ``is_property_set``. In that
        # case preserve the declared default and avoid guessing destructively.
        return False
    try:
        points_u = max(2, min(64, int(getattr(rig, "fbp_lattice_points_u", 4) or 4)))
        points_v = max(2, min(64, int(getattr(rig, "fbp_lattice_points_v", 4) or 4)))
    except FBP_DATA_ERRORS:
        return False
    loops_u, loops_v = points_u - 2, points_v - 2
    preset = None
    if loops_u == loops_v:
        preset = {
            0: "CORNERS",
            1: "BASIC",
            2: "LOOPS_2",
            4: "LOOPS_4",
        }.get(loops_u)
    if preset is None:
        preset = "CUSTOM"
        fbp_set_rna_property_silent(rig, "fbp_lattice_custom_loops_u", loops_u)
        fbp_set_rna_property_silent(rig, "fbp_lattice_custom_loops_v", loops_v)
        fbp_set_rna_property_silent(rig, "fbp_lattice_link_loops", loops_u == loops_v)
    fbp_set_rna_property_silent(rig, "fbp_lattice_grid_preset", preset)
    return True


def _fbp_apply_lattice_grid_settings(rig):
    """Translate user-facing internal loops to Blender Lattice point counts."""
    if rig is None:
        return False
    loops_u, loops_v = _fbp_lattice_grid_loops(rig)
    target_u = max(2, min(64, loops_u + 2))
    target_v = max(2, min(64, loops_v + 2))
    changed = False
    try:
        if int(getattr(rig, "fbp_lattice_points_u", 4) or 4) != target_u:
            fbp_set_rna_property_silent(rig, "fbp_lattice_points_u", target_u)
            changed = True
        if int(getattr(rig, "fbp_lattice_points_v", 4) or 4) != target_v:
            fbp_set_rna_property_silent(rig, "fbp_lattice_points_v", target_v)
            changed = True
        if int(getattr(rig, "fbp_lattice_points_w", 1) or 1) != 1:
            fbp_set_rna_property_silent(rig, "fbp_lattice_points_w", 1)
            changed = True
    except FBP_DATA_ERRORS:
        return False
    return changed


def _fbp_lattice_mesh_detail_levels(rig):
    """Return Simple Subdivision levels for the requested planar mesh density.

    Blender's Simple Subdivision doubles the number of face segments per level,
    so automatic mode converts the cage cell count into the smallest power-of-two
    mesh grid meeting the requested density. Custom mode exposes Blender's native
    levels directly.
    """
    if _fbp_lattice_mesh_detail_mode(rig) == "CUSTOM":
        try:
            return max(0, min(6, int(getattr(rig, "fbp_lattice_mesh_subdivisions", 2) or 0)))
        except FBP_DATA_ERRORS:
            return 2
    try:
        cage_cells = max(
            1,
            int(getattr(rig, "fbp_lattice_points_u", 2) or 2) - 1,
            int(getattr(rig, "fbp_lattice_points_v", 2) or 2) - 1,
        )
    except FBP_DATA_ERRORS:
        cage_cells = 1
    target_segments = max(1, int(math.ceil(cage_cells * _fbp_lattice_mesh_density_multiplier(rig))))
    return max(0, min(6, int(math.ceil(math.log2(target_segments)))))


def _fbp_lattice_mesh_segment_count(rig):
    return 1 << _fbp_lattice_mesh_detail_levels(rig)


def _fbp_sync_lattice_detail_modifier(rig, plane, lattice_modifier=None):
    """Create or update the lightweight Simple Subdivision before Lattice."""
    levels = _fbp_lattice_mesh_detail_levels(rig)
    detail = _fbp_lattice_detail_modifier(plane)
    if levels <= 0:
        if detail is not None:
            try:
                plane.modifiers.remove(detail)
                _fbp_store_modifier_reference(plane, _FBP_LATTICE_DETAIL_REF_KEY, None)
                return None
            except FBP_DATA_ERRORS:
                return detail
        _fbp_store_modifier_reference(plane, _FBP_LATTICE_DETAIL_REF_KEY, None)
        return None
    if detail is None:
        try:
            detail = plane.modifiers.new(_FBP_LATTICE_DETAIL_MODIFIER_NAME, "SUBSURF")
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not add Lattice detail modifier", exc)
            return None
    try:
        detail.subdivision_type = 'SIMPLE'
        detail.levels = levels
        detail.render_levels = levels
        # SIMPLE subdivision has no smoothing cost. Hide generated interior
        # control edges and disable edit-cage evaluation to keep dense planes
        # responsive while the user manipulates the Lattice points.
        detail.show_only_control_edges = True
        detail.show_in_editmode = False
        detail.show_on_cage = False
        detail.show_viewport = _fbp_stored_effect_visibility(rig, FBP_EFFECT_LATTICE, True)
        detail.show_render = _fbp_stored_effect_render_visibility(rig, FBP_EFFECT_LATTICE, True)
        _fbp_store_modifier_reference(plane, _FBP_LATTICE_DETAIL_REF_KEY, detail)
        if lattice_modifier is not None:
            detail_index = next((i for i, item in enumerate(plane.modifiers) if item == detail), -1)
            lattice_index = next((i for i, item in enumerate(plane.modifiers) if item == lattice_modifier), -1)
            if detail_index >= 0 and lattice_index >= 0 and detail_index > lattice_index:
                plane.modifiers.move(detail_index, lattice_index)
    except FBP_DATA_ERRORS:
        pass
    return detail


def _fbp_lattice_local_bounds(plane):
    """Return stable undeformed local bounds for the image plane."""
    try:
        points = [Vector(point) for point in tuple(plane.bound_box or ())]
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        points = []
    if not points:
        try:
            points = [vertex.co.copy() for vertex in plane.data.vertices]
        except FBP_DATA_ERRORS:
            points = []
    if not points:
        points = [Vector((-0.5, -0.5, 0.0)), Vector((0.5, 0.5, 0.0))]
    minimum = Vector((
        min(point.x for point in points),
        min(point.y for point in points),
        min(point.z for point in points),
    ))
    maximum = Vector((
        max(point.x for point in points),
        max(point.y for point in points),
        max(point.z for point in points),
    ))
    return minimum, maximum


def _fbp_lattice_fit_matrix(plane, bounds=None):
    """Return a world transform enclosing the plane in its own local axes."""
    minimum, maximum = bounds or _fbp_lattice_local_bounds(plane)
    center = (minimum + maximum) * 0.5
    size = maximum - minimum
    size.x = max(abs(float(size.x)), 0.001)
    size.y = max(abs(float(size.y)), 0.001)
    # Keep a small non-zero local Z scale even for the planar one-layer cage.
    # This preserves an invertible object transform without adding overlapping
    # front/back control points.
    size.z = max(abs(float(size.z)), min(size.x, size.y) * 0.08, 0.01)
    local = Matrix.Translation(center) @ Matrix.Diagonal((size.x, size.y, size.z, 1.0))
    return plane.matrix_world @ local


def _fbp_lattice_runtime_key(rig):
    try:
        return fbp_obj_runtime_key(rig)
    except FBP_DATA_ERRORS:
        return None


def _fbp_lattice_matrix_signature(matrix, precision=7):
    try:
        return tuple(round(float(value), precision) for row in matrix for value in row)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ()


def _fbp_lattice_bounds_signature(plane, precision=7):
    try:
        minimum, maximum = _fbp_lattice_local_bounds(plane)
        return tuple(round(float(value), precision) for value in (*minimum, *maximum))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ()


def _fbp_lattice_scene_camera(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    try:
        camera = getattr(scene, "camera", None)
        if camera is not None and getattr(camera, "type", "") == "CAMERA":
            return camera
    except FBP_DATA_ERRORS:
        pass
    return None


def _fbp_lattice_mode(rig):
    try:
        return str(getattr(rig, "fbp_lattice_mode", "FREEFORM") or "FREEFORM").upper()
    except FBP_DATA_ERRORS:
        return "FREEFORM"


def _fbp_lattice_camera_flatten_enabled(rig):
    try:
        return (
            _fbp_is_enabled(rig, FBP_EFFECT_LATTICE)
            and _fbp_lattice_mode(rig) == "CAMERA_FLATTEN"
        )
    except FBP_DATA_ERRORS:
        return False


def _fbp_update_lattice_data(rig, helper):
    """Synchronize cage topology and interpolation.

    Return True only when the point topology changed. Interpolation changes are
    deliberately excluded: older builds treated every interpolation update as a
    topology rebuild and silently reset all manual cage deformation.
    """
    data = getattr(helper, "data", None) if helper else None
    if data is None:
        return False
    topology_changed = False
    # Frame By Plane layers are planar, therefore the cage uses one depth
    # layer. Each visible grid intersection is one selectable control point: a
    # 2 × 2 cage has exactly four corner points rather than front/back pairs.
    try:
        if int(getattr(rig, "fbp_lattice_points_w", 1) or 1) != 1:
            fbp_set_rna_property_silent(rig, "fbp_lattice_points_w", 1)
    except FBP_DATA_ERRORS:
        pass
    values = (
        ("points_u", max(2, int(getattr(rig, "fbp_lattice_points_u", 4) or 4))),
        ("points_v", max(2, int(getattr(rig, "fbp_lattice_points_v", 4) or 4))),
        ("points_w", 1),
    )
    for attribute, value in values:
        try:
            if int(getattr(data, attribute)) != value:
                setattr(data, attribute, value)
                topology_changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    interpolation = (
        "KEY_LINEAR"
        if _fbp_lattice_mode(rig) == "CAMERA_FLATTEN"
        else {
            "LINEAR": "KEY_LINEAR",
            "CARDINAL": "KEY_CARDINAL",
            "CATMULL_ROM": "KEY_CATMULL_ROM",
            "BSPLINE": "KEY_BSPLINE",
        }.get(str(getattr(rig, "fbp_lattice_interpolation", "BSPLINE") or "BSPLINE"), "KEY_BSPLINE")
    )
    for attribute in ("interpolation_type_u", "interpolation_type_v", "interpolation_type_w"):
        try:
            if str(getattr(data, attribute, "")) != interpolation:
                setattr(data, attribute, interpolation)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return topology_changed


def _fbp_lattice_point_index(u_index, v_index, w_index, points_u, points_v):
    # Blender stores U as the fastest axis, followed by V and then W.
    return (
        int(u_index)
        + int(v_index) * int(points_u)
        + int(w_index) * int(points_u) * int(points_v)
    )


def _fbp_capture_planar_lattice_points(rig, helper):
    """Average a legacy volumetric cage into one planar point per U/V cell.

    The capture is used only when U and V resolutions are unchanged, allowing
    6.0.43 and earlier cages to migrate without discarding their visible shape.
    """
    data = getattr(helper, "data", None) if helper else None
    if data is None:
        return None
    try:
        points_u = int(data.points_u)
        points_v = int(data.points_v)
        points_w = int(data.points_w)
        target_u = max(2, int(getattr(rig, "fbp_lattice_points_u", points_u) or points_u))
        target_v = max(2, int(getattr(rig, "fbp_lattice_points_v", points_v) or points_v))
        if points_w <= 1 or points_u != target_u or points_v != target_v:
            return None
        captured = []
        for v_index in range(points_v):
            for u_index in range(points_u):
                total = Vector((0.0, 0.0, 0.0))
                for w_index in range(points_w):
                    index = _fbp_lattice_point_index(
                        u_index, v_index, w_index, points_u, points_v
                    )
                    total += Vector(data.points[index].co_deform)
                captured.append(total / float(points_w))
        return tuple(captured)
    except FBP_DATA_ERRORS:
        return None


def _fbp_restore_planar_lattice_points(helper, captured):
    data = getattr(helper, "data", None) if helper else None
    if data is None or not captured:
        return False
    try:
        points_u = max(2, int(data.points_u))
        points_v = max(2, int(data.points_v))
        if int(data.points_w) != 1 or len(captured) != points_u * points_v:
            return False
        for v_index in range(points_v):
            for u_index in range(points_u):
                source_index = u_index + v_index * points_u
                target_index = _fbp_lattice_point_index(
                    u_index, v_index, 0, points_u, points_v
                )
                coordinate = Vector(captured[source_index])
                data.points[target_index].co_deform = coordinate
        data.update_tag()
        helper.update_tag(refresh={'DATA'})
        return True
    except FBP_DATA_ERRORS:
        return False


def _fbp_reset_lattice_points(helper):
    """Restore a regular undeformed lattice without replacing the datablock."""
    data = getattr(helper, "data", None) if helper else None
    if data is None:
        return False
    try:
        points_u = max(2, int(data.points_u))
        points_v = max(2, int(data.points_v))
        points_w = max(1, int(data.points_w))
        points = data.points
        for u_index in range(points_u):
            u = u_index / float(points_u - 1)
            x = u - 0.5
            for v_index in range(points_v):
                v = v_index / float(points_v - 1)
                y = v - 0.5
                for w_index in range(points_w):
                    z = 0.0 if points_w == 1 else (w_index / float(points_w - 1)) - 0.5
                    index = _fbp_lattice_point_index(
                        u_index, v_index, w_index, points_u, points_v
                    )
                    points[index].co_deform = (x, y, z)
        data.update_tag()
        helper.update_tag(refresh={'DATA'})
        return True
    except FBP_DATA_ERRORS:
        return False


def _fbp_lattice_flatten_signature(rig, plane, helper, camera, bounds=None):
    data = getattr(helper, "data", None)
    camera_data = getattr(camera, "data", None)
    try:
        influence = round(float(getattr(rig, "fbp_lattice_flatten_influence", 1.0) or 0.0), 7)
        dimensions = (
            int(getattr(data, "points_u", 0) or 0),
            int(getattr(data, "points_v", 0) or 0),
            int(getattr(data, "points_w", 0) or 0),
        )
        if bounds is None:
            bounds_signature = _fbp_lattice_bounds_signature(plane)
        else:
            minimum, maximum = bounds
            bounds_signature = tuple(
                round(float(value), 7) for value in (*minimum, *maximum)
            )
        return (
            _fbp_lattice_matrix_signature(plane.matrix_world),
            bounds_signature,
            _fbp_lattice_matrix_signature(camera.matrix_world),
            str(getattr(camera_data, "type", "PERSP") or "PERSP"),
            influence,
            dimensions,
            int(getattr(helper, "as_pointer", lambda: 0)()),
        )
    except FBP_DATA_ERRORS:
        return None


def _fbp_apply_lattice_camera_flatten(rig, *, scene=None, force=False):
    """Bake camera-space perspective using one projection setup per cage.

    Earlier builds rebuilt the camera basis for every control point and sampled
    plane bounds three times per update. A 64 × 64 cage therefore performed
    thousands of redundant matrix copies and quaternion conversions.
    """
    if not _fbp_lattice_camera_flatten_enabled(rig):
        return False
    plane = _fbp_plane(rig, repair=False)
    helper = _fbp_lattice_object(rig)
    camera = _fbp_lattice_scene_camera(scene)
    if plane is None or helper is None or camera is None:
        return False
    data = getattr(helper, "data", None)
    if data is None:
        return False

    try:
        expected_u = max(2, int(getattr(rig, "fbp_lattice_points_u", 4) or 4))
        expected_v = max(2, int(getattr(rig, "fbp_lattice_points_v", 4) or 4))
        if (int(data.points_u), int(data.points_v), int(data.points_w)) != (expected_u, expected_v, 1):
            _fbp_update_lattice_data(rig, helper)

        minimum, maximum = _fbp_lattice_local_bounds(plane)
        bounds = (minimum, maximum)
        signature = _fbp_lattice_flatten_signature(
            rig, plane, helper, camera, bounds=bounds
        )
        cache_key = _fbp_lattice_runtime_key(rig)
        if not force and cache_key is not None and _FBP_LATTICE_FLATTEN_CACHE.get(cache_key) == signature:
            return False

        fit_matrix = _fbp_lattice_fit_matrix(plane, bounds=bounds)
        if _fbp_lattice_matrix_signature(helper.matrix_world) != _fbp_lattice_matrix_signature(fit_matrix):
            helper.matrix_world = fit_matrix
        inverse_fit = fit_matrix.inverted_safe()
        plane_matrix = plane.matrix_world.copy()
        center_local = (minimum + maximum) * 0.5
        pivot_world = plane_matrix @ center_local

        camera_matrix = camera.matrix_world.copy()
        camera_forward = camera_matrix.to_quaternion() @ Vector((0.0, 0.0, -1.0))
        if camera_forward.length_squared <= 1.0e-12:
            return False
        camera_forward.normalize()
        camera_origin = camera_matrix.translation.copy()
        camera_type = str(getattr(getattr(camera, "data", None), "type", "PERSP") or "PERSP").upper()
        if camera_type not in {"PERSP", "ORTHO"}:
            return False
        perspective_plane_distance = (pivot_world - camera_origin).dot(camera_forward)
        influence = max(0.0, min(1.0, float(getattr(rig, "fbp_lattice_flatten_influence", 1.0) or 0.0)))

        points_u = max(2, int(data.points_u))
        points_v = max(2, int(data.points_v))
        points_w = max(1, int(data.points_w))
        points = data.points
        min_x, max_x = float(minimum.x), float(maximum.x)
        min_y, max_y = float(minimum.y), float(maximum.y)
        center_z = float(center_local.z)
        span_x = max_x - min_x
        span_y = max_y - min_y
        inv_u = 1.0 / float(points_u - 1)
        inv_v = 1.0 / float(points_v - 1)
        layer_stride = points_u * points_v
        coordinates = [0.0] * (layer_stride * points_w * 3)

        for v_index in range(points_v):
            local_y = min_y + span_y * (v_index * inv_v)
            row_offset = v_index * points_u
            for u_index in range(points_u):
                local_x = min_x + span_x * (u_index * inv_u)
                source_world = plane_matrix @ Vector((local_x, local_y, center_z))
                if camera_type == "ORTHO":
                    target_world = source_world + camera_forward * (
                        (pivot_world - source_world).dot(camera_forward)
                    )
                else:
                    direction = source_world - camera_origin
                    denominator = direction.dot(camera_forward)
                    if abs(float(denominator)) <= 1.0e-10:
                        return False
                    target_world = camera_origin + direction * (
                        perspective_plane_distance / denominator
                    )
                if influence < 1.0:
                    target_world = source_world.lerp(target_world, influence)
                surface = inverse_fit @ target_world
                base_index = row_offset + u_index
                if points_w == 1:
                    target = base_index * 3
                    coordinates[target] = float(surface.x)
                    coordinates[target + 1] = float(surface.y)
                    coordinates[target + 2] = float(surface.z)
                else:
                    for w_index in range(points_w):
                        depth = (w_index / float(points_w - 1)) - 0.5
                        target = (base_index + w_index * layer_stride) * 3
                        coordinates[target] = float(surface.x)
                        coordinates[target + 1] = float(surface.y)
                        coordinates[target + 2] = float(surface.z + depth)

        # One bulk RNA write replaces thousands of individual co_deform
        # assignments and is the dominant Camera Flatten performance gain.
        points.foreach_set("co_deform", coordinates)

        helper[_FBP_LATTICE_SCHEMA_KEY] = _FBP_LATTICE_SCHEMA_VERSION
        helper[_FBP_LATTICE_MODE_KEY] = "CAMERA_FLATTEN"
        if bool(getattr(rig, "fbp_lattice_live_update", True)):
            helper[_FBP_LATTICE_BAKED_KEY] = False
        data.update_tag()
        helper.update_tag(refresh={'DATA'})
        if cache_key is not None and signature is not None:
            if len(_FBP_LATTICE_FLATTEN_CACHE) >= 512 and cache_key not in _FBP_LATTICE_FLATTEN_CACHE:
                _FBP_LATTICE_FLATTEN_CACHE.clear()
            _FBP_LATTICE_FLATTEN_CACHE[cache_key] = signature
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not flatten Lattice to camera", exc)
        return False


def _fbp_configure_lattice_visibility(rig, plane, helper, modifier, detail_modifier=None, *, context=None):
    """Apply presentation state without making cosmetic failures transactional."""
    viewport_visible = _fbp_stored_effect_visibility(rig, FBP_EFFECT_LATTICE, True)
    render_visible = _fbp_stored_effect_render_visibility(rig, FBP_EFFECT_LATTICE, True)
    show_cage = bool(getattr(rig, "fbp_lattice_show_cage", True))
    for owned_modifier in (modifier, detail_modifier):
        if owned_modifier is None:
            continue
        try:
            owned_modifier.show_viewport = viewport_visible
            owned_modifier.show_render = render_visible
        except FBP_DATA_ERRORS:
            pass
    try:
        helper.hide_render = True
        helper.display_type = "WIRE"
        helper.show_in_front = True
        # Only disable evaluation when the effect itself is disabled. Cage
        # drawing is controlled separately through hide_set.
        helper.hide_viewport = not viewport_visible
    except FBP_DATA_ERRORS:
        pass

    context = context or getattr(bpy, "context", None)
    try:
        view_layer = getattr(context, "view_layer", None)
        if view_layer is not None and view_layer.objects.get(helper.name) is not None:
            helper.hide_set(not bool(viewport_visible and show_cage))
    except FBP_DATA_ERRORS:
        # An object outside the active View Layer can still evaluate correctly;
        # do not destroy a valid modifier just because its drawing state failed.
        pass


def fbp_focus_lattice_ui(context, rig):
    """Keep the Mesh stack and Lattice row visible while the cage is selected."""
    if context is None or rig is None:
        return False
    changed = False
    try:
        scene = getattr(context, "scene", None)
        if scene is not None and str(getattr(scene, "fbp_effects_view", "2D") or "2D") != "3D":
            scene.fbp_effects_view = "3D"
            changed = True
    except FBP_DATA_ERRORS:
        pass
    try:
        changed = _fbp_select_effect_row(rig, FBP_EFFECT_LATTICE, [rig]) or changed
    except FBP_DATA_ERRORS:
        pass
    return changed


def _fbp_select_lattice_helper(rig, helper, *, context=None):
    context = context or getattr(bpy, "context", None)
    if rig is None or helper is None or context is None:
        return False
    try:
        view_layer = getattr(context, "view_layer", None)
        if view_layer is None or view_layer.objects.get(helper.name) is None:
            return False
        if getattr(context, "mode", "OBJECT") != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in tuple(getattr(context, "selected_objects", ()) or ()):
            try:
                obj.select_set(False)
            except FBP_DATA_ERRORS:
                pass
        helper.hide_viewport = False
        helper.hide_set(False)
        helper.select_set(True)
        view_layer.objects.active = helper
        fbp_focus_lattice_ui(context, rig)
        return True
    except FBP_DATA_ERRORS:
        return False


def _fbp_apply_lattice_effect(rig, *, select=False):
    """Create or repair a complete, editable Lattice setup transactionally."""
    issue = _fbp_lattice_compatibility_issue(rig)
    if issue:
        _fbp_set_lattice_error(rig, issue)
        return False
    plane = _fbp_plane(rig, repair=True)
    if plane is None:
        _fbp_set_lattice_error(rig, "The selected layer has no recoverable mesh plane")
        return False

    # Upgrade the 6.0.45 point-count controls to the loop-count presets without
    # changing topology or destroying an existing deformation.
    _fbp_sync_lattice_grid_preset_from_points(rig)

    helper = _fbp_lattice_object(rig)
    modifier = _fbp_lattice_modifier(plane)
    detail_modifier = _fbp_lattice_detail_modifier(plane)
    # Never reuse a half-created pair from a previous failed attempt.
    if any(item is not None for item in (helper, modifier, detail_modifier)) and not _fbp_lattice_contract_is_valid(
        rig, plane, helper, modifier
    ):
        _fbp_cleanup_incomplete_lattice_setup(rig, force=True)
        helper = None
        modifier = None
        detail_modifier = None

    created_helper = False
    created_modifier = False
    data = None
    try:
        if helper is None:
            data = bpy.data.lattices.new(f"FBP Lattice • {rig.name}")
            helper = bpy.data.objects.new(f"FBP Lattice • {rig.name}", data)
            created_helper = True
            # Claim ownership before linking so rollback can still find and
            # remove the object when collection linking itself fails.
            helper[_FBP_LATTICE_OWNER_KEY] = str(rig.name)
            helper[_FBP_LATTICE_EFFECT_KEY] = FBP_EFFECT_LATTICE
            helper[_FBP_LATTICE_SCHEMA_KEY] = _FBP_LATTICE_SCHEMA_VERSION
            helper[_FBP_LATTICE_MODE_KEY] = _fbp_lattice_mode(rig)
            helper[_FBP_LATTICE_BAKED_KEY] = False
            rig.fbp_lattice_object = helper
            if not _fbp_ensure_lattice_link(helper, rig, plane, getattr(bpy, "context", None)):
                raise RuntimeError(_fbp_last_lattice_error(rig) or "No writable Scene collection is available")
            helper.hide_render = True
            helper.display_type = "WIRE"
            helper.show_in_front = True
            helper.parent = rig
            helper.matrix_world = _fbp_lattice_fit_matrix(plane)
        else:
            if not _fbp_ensure_lattice_link(helper, rig, plane, getattr(bpy, "context", None)):
                raise RuntimeError(_fbp_last_lattice_error(rig) or "Could not relink the existing cage")

        helper_data = getattr(helper, "data", None)
        if helper_data is None:
            raise RuntimeError("The Lattice cage has no datablock")
        if int(getattr(helper_data, "users", 1) or 1) > 1:
            helper.data = helper_data.copy()
            helper_data = helper.data
        legacy_planar_points = _fbp_capture_planar_lattice_points(rig, helper)
        resolution_changed = _fbp_update_lattice_data(rig, helper)
        if created_helper or resolution_changed:
            helper.matrix_world = _fbp_lattice_fit_matrix(plane)
            restored = bool(
                not created_helper
                and legacy_planar_points
                and _fbp_restore_planar_lattice_points(helper, legacy_planar_points)
            )
            if not restored and not _fbp_reset_lattice_points(helper):
                raise RuntimeError("Could not initialize the Lattice control points")
            _fbp_stabilize_lattice_helper(helper)

        helper[_FBP_LATTICE_OWNER_KEY] = str(rig.name)
        helper[_FBP_LATTICE_EFFECT_KEY] = FBP_EFFECT_LATTICE
        helper[_FBP_LATTICE_SCHEMA_KEY] = _FBP_LATTICE_SCHEMA_VERSION
        helper[_FBP_LATTICE_MODE_KEY] = _fbp_lattice_mode(rig)
        _fbp_stabilize_lattice_helper(helper)
        if _fbp_lattice_mode(rig) == "CAMERA_FLATTEN" and bool(getattr(rig, "fbp_lattice_live_update", True)):
            helper[_FBP_LATTICE_BAKED_KEY] = False

        modifier = _fbp_lattice_modifier(plane)
        if modifier is None:
            modifier = plane.modifiers.new(_FBP_LATTICE_MODIFIER_NAME, "LATTICE")
            created_modifier = True
        modifier.object = helper
        _fbp_store_modifier_reference(plane, _FBP_LATTICE_MODIFIER_REF_KEY, modifier)

        # Mesh detail improves deformation but is not allowed to invalidate an
        # otherwise functional cage. A failed Subdivision modifier can be
        # repaired later without blocking the Lattice itself.
        try:
            detail_modifier = _fbp_sync_lattice_detail_modifier(rig, plane, modifier)
        except FBP_DATA_ERRORS as exc:
            detail_modifier = None
            fbp_warn("Could not update optional Lattice mesh detail", exc)

        if not _fbp_lattice_contract_is_valid(rig, plane, helper, modifier):
            raise RuntimeError("Blender did not accept the Lattice modifier binding")

        _fbp_configure_lattice_visibility(
            rig, plane, helper, modifier, detail_modifier, context=getattr(bpy, "context", None)
        )
        if _fbp_lattice_mode(rig) == "CAMERA_FLATTEN":
            _fbp_apply_lattice_camera_flatten(
                rig,
                scene=getattr(getattr(bpy, "context", None), "scene", None),
                force=bool(created_helper or created_modifier or resolution_changed),
            )
        else:
            _fbp_stabilize_lattice_helper(helper)

        if select:
            _fbp_select_lattice_helper(rig, helper, context=getattr(bpy, "context", None))
        _fbp_invalidate_live_lattice_cache()
        repair_key = _fbp_lattice_error_key(rig)
        _FBP_LATTICE_REPAIR_ATTEMPTED.pop(repair_key, None)
        _FBP_LATTICE_REPAIR_PENDING.discard(repair_key)
        _fbp_clear_lattice_error(rig)
        return True
    except Exception as exc:
        # This is the transaction boundary for Blender RNA calls. Keep the exact
        # reason for the UI and always remove generated partial state.
        _fbp_set_lattice_error(rig, "Lattice setup failed", exc)
        if created_helper or created_modifier or not _fbp_lattice_contract_is_valid(rig, plane, helper, modifier):
            _fbp_cleanup_incomplete_lattice_setup(rig, force=True)
        else:
            _fbp_configure_lattice_visibility(
                rig, plane, helper, modifier, detail_modifier, context=getattr(bpy, "context", None)
            )
        try:
            if data is not None and data.users == 0:
                bpy.data.lattices.remove(data)
        except FBP_DATA_ERRORS:
            pass
        return False

def _fbp_lattice_repair_signature(rig):
    """Cheap signature used to attempt automatic repair once per broken state."""
    plane = _fbp_plane(rig, repair=False)
    modifier = _fbp_lattice_modifier(plane)
    try:
        helper_pointer = getattr(rig, "fbp_lattice_object", None)
        helper_name = str(getattr(helper_pointer, "name", "") or "")
    except FBP_DATA_ERRORS:
        helper_name = ""
    try:
        stored_name = str(rig.get(_FBP_LATTICE_HELPER_NAME_KEY, "") or "")
    except FBP_DATA_ERRORS:
        stored_name = ""
    try:
        bound_name = str(getattr(getattr(modifier, "object", None), "name", "") or "")
    except FBP_DATA_ERRORS:
        bound_name = ""
    try:
        object_count = len(bpy.data.objects)
    except FBP_DATA_ERRORS:
        object_count = -1
    return (
        object_count,
        str(getattr(plane, "name", "") or ""),
        str(getattr(modifier, "name", "") or ""),
        helper_name,
        stored_name,
        bound_name,
    )


def _fbp_schedule_lattice_contract_repair(rig, *, first_interval=0.02):
    """Queue one non-recursive repair for an active incomplete Lattice."""
    if rig is None or fbp_render_mutation_blocked():
        return False
    try:
        active = bool(
            _fbp_is_enabled(rig, FBP_EFFECT_LATTICE)
            or getattr(rig, "fbp_lattice_object", None)
            or _fbp_lattice_modifier(_fbp_plane(rig, repair=False))
        )
    except FBP_DATA_ERRORS:
        active = False
    if not active:
        return False
    plane = _fbp_plane(rig, repair=False)
    helper = _fbp_lattice_object(rig)
    modifier = _fbp_lattice_modifier(plane)
    if _fbp_lattice_contract_is_valid(rig, plane, helper, modifier):
        return False

    key = _fbp_lattice_error_key(rig)
    signature = _fbp_lattice_repair_signature(rig)
    if key in _FBP_LATTICE_REPAIR_PENDING:
        return True
    if _FBP_LATTICE_REPAIR_ATTEMPTED.get(key) == signature:
        return False
    _FBP_LATTICE_REPAIR_PENDING.add(key)
    _FBP_LATTICE_REPAIR_ATTEMPTED[key] = signature
    rig_key = _fbp_lattice_runtime_key(rig)
    rig_name = str(getattr(rig, "name", "") or "")

    def _run():
        _FBP_LATTICE_REPAIR_PENDING.discard(key)
        active_rig = fbp_find_id_by_runtime_key(bpy.data.objects, rig_key, rig_name)
        if active_rig is None or fbp_render_mutation_blocked():
            return None
        try:
            _fbp_set_enabled(active_rig, FBP_EFFECT_LATTICE, True)
            if _fbp_apply_lattice_effect(active_rig, select=False):
                _FBP_LATTICE_REPAIR_ATTEMPTED.pop(key, None)
        except FBP_DATA_ERRORS:
            pass
        return None

    try:
        from .safe_tasks import schedule_once
        if schedule_once(
            f"lattice.contract_repair.{rig_key or rig_name}",
            _run,
            first_interval=max(0.0, float(first_interval)),
        ):
            return True
        # An equivalent safe task may already exist after module reload.
        return True
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        _FBP_LATTICE_REPAIR_PENDING.discard(key)
        _run()
        return _fbp_lattice_contract_is_valid(rig)


def fbp_repair_existing_lattice_contracts():
    """Repair enabled/owned Lattice effects once after register or file load."""
    repaired = 0
    seen = set()
    for scene in tuple(getattr(bpy.data, "scenes", ()) or ()):
        for rig in tuple(getattr(scene, "objects", ()) or ()):
            try:
                key = int(rig.as_pointer())
                if key in seen or not bool(getattr(rig, "is_fbp_control", False)):
                    continue
                seen.add(key)
                plane = _fbp_plane(rig, repair=False)
                modifier = _fbp_lattice_modifier(plane)
                active = bool(
                    _fbp_is_enabled(rig, FBP_EFFECT_LATTICE)
                    or getattr(rig, "fbp_lattice_object", None)
                    or modifier
                )
                if not active:
                    continue
                # One-time, non-destructive migration from point counts to the
                # new user-facing internal-loop presets.
                _fbp_sync_lattice_grid_preset_from_points(rig)
                helper = _fbp_lattice_object(rig)
                if _fbp_lattice_contract_is_valid(rig, plane, helper, modifier):
                    _fbp_stabilize_lattice_helper(helper)
                    continue
                _fbp_set_enabled(rig, FBP_EFFECT_LATTICE, True)
                repaired += int(_fbp_apply_lattice_effect(rig, select=False))
            except FBP_DATA_ERRORS:
                continue
    return None


def _fbp_remove_lattice_effect(rig):
    # Deleting the active cage datablock while Blender is in Lattice Edit Mode
    # is unreliable. Return to Object Mode first, then remove only the generated
    # helper and modifiers and finally restore the layer rig selection.
    helper = _fbp_lattice_object(rig)
    context = getattr(bpy, "context", None)
    try:
        if (
            helper is not None
            and context is not None
            and getattr(context, "active_object", None) is helper
            and str(getattr(context, "mode", "OBJECT") or "OBJECT") != "OBJECT"
        ):
            bpy.ops.object.mode_set(mode="OBJECT")
    except FBP_DATA_ERRORS:
        pass
    cache_key = _fbp_lattice_runtime_key(rig)
    if cache_key is not None:
        _FBP_LATTICE_FLATTEN_CACHE.pop(cache_key, None)
    changed = _fbp_cleanup_incomplete_lattice_setup(rig, force=True)
    try:
        if context is not None and rig is not None:
            for obj in tuple(getattr(context, "selected_objects", ()) or ()):
                obj.select_set(False)
            rig.hide_set(False)
            rig.select_set(True)
            context.view_layer.objects.active = rig
    except FBP_DATA_ERRORS:
        pass
    _fbp_invalidate_live_lattice_cache()
    _fbp_clear_lattice_error(rig)
    return changed


def fbp_lattice_contract_report(rig, *, repair=False):
    """Return lightweight release-audit data for one active Lattice effect."""
    result = {
        "active": False,
        "valid": True,
        "repaired": 0,
        "issues": [],
        "warnings": [],
    }
    if rig is None:
        return result
    try:
        plane_hint = _fbp_plane(rig, repair=False)
        result["active"] = bool(
            _fbp_is_enabled(rig, FBP_EFFECT_LATTICE)
            or _fbp_lattice_object(rig)
            or _fbp_lattice_modifier(plane_hint)
        )
    except FBP_DATA_ERRORS:
        return result
    if not result["active"]:
        return result

    issue = _fbp_lattice_compatibility_issue(rig)
    if issue:
        result["valid"] = False
        result["issues"].append(issue)
        return result

    plane = _fbp_plane(rig, repair=bool(repair))
    helper = _fbp_lattice_object(rig)
    modifier = _fbp_lattice_modifier(plane)
    if repair and not _fbp_lattice_contract_is_valid(rig, plane, helper, modifier):
        if _fbp_apply_lattice_effect(rig, select=False):
            result["repaired"] += 1
            plane = _fbp_plane(rig, repair=False)
            helper = _fbp_lattice_object(rig)
            modifier = _fbp_lattice_modifier(plane)

    if not _fbp_lattice_contract_is_valid(rig, plane, helper, modifier):
        result["valid"] = False
        result["issues"].append("Lattice cage or modifier binding is incomplete")
        return result

    if repair:
        try:
            if getattr(helper, "parent", None) is not rig:
                world_matrix = helper.matrix_world.copy()
                helper.parent = rig
                helper.matrix_world = world_matrix
                result["repaired"] += 1
            owner_name = str(getattr(rig, "name", "") or "")
            if str(helper.get(_FBP_LATTICE_OWNER_KEY, "") or "") != owner_name:
                helper[_FBP_LATTICE_OWNER_KEY] = owner_name
                result["repaired"] += 1
            helper_data = getattr(helper, "data", None)
            if helper_data is not None and int(getattr(helper_data, "points_w", 0) or 0) != 1:
                if _fbp_apply_lattice_effect(rig, select=False):
                    helper = _fbp_lattice_object(rig)
                    modifier = _fbp_lattice_modifier(plane)
                    result["repaired"] += 1
            if _fbp_stabilize_lattice_helper(helper):
                result["repaired"] += 1
            previous_detail = _fbp_lattice_detail_modifier(plane)
            synced_detail = _fbp_sync_lattice_detail_modifier(rig, plane, modifier)
            if previous_detail is not synced_detail:
                result["repaired"] += 1
            _fbp_configure_lattice_visibility(
                rig, plane, helper, modifier, synced_detail,
                context=getattr(bpy, "context", None),
            )
        except FBP_DATA_ERRORS as exc:
            result["warnings"].append(f"Lattice safe repair was incomplete: {exc}")

    try:
        if getattr(helper, "parent", None) is not rig:
            result["warnings"].append("Lattice cage is not parented to the layer rig")
        if str(helper.get(_FBP_LATTICE_OWNER_KEY, "") or "") != str(getattr(rig, "name", "") or ""):
            result["warnings"].append("Lattice cage owner metadata is stale")
        if tuple(bool(value) for value in getattr(helper, "lock_location", ())) != (True, True, True):
            result["warnings"].append("Lattice Object Mode location is not locked")
        if tuple(bool(value) for value in getattr(helper, "lock_rotation", ())) != (True, True, True):
            result["warnings"].append("Lattice Object Mode rotation is not locked")
        if tuple(bool(value) for value in getattr(helper, "lock_scale", ())) != (True, True, True):
            result["warnings"].append("Lattice Object Mode scale is not locked")
        helper_data = getattr(helper, "data", None)
        if helper_data is not None and int(getattr(helper_data, "points_w", 0) or 0) != 1:
            result["issues"].append("Lattice cage still uses overlapping depth layers instead of the planar contract")
        detail = _fbp_lattice_detail_modifier(plane)
        if detail is not None:
            modifiers = tuple(getattr(plane, "modifiers", ()) or ())
            if modifiers.index(detail) > modifiers.index(modifier):
                result["issues"].append("Lattice mesh detail modifier is evaluated after the Lattice")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        result["warnings"].append("Lattice metadata could not be fully inspected")

    result["valid"] = not bool(result["issues"])
    return result


def _fbp_invalidate_live_lattice_cache():
    _FBP_LATTICE_LIVE_SCENE_CACHE.clear()


def _fbp_live_lattice_rigs(scene):
    """Return live Camera Flatten rigs through a persistent Scene index.

    The old 0.75-second expiry repeatedly rescanned every object even when a
    project contained only Freeform cages. Effect callbacks, object-count
    changes, load and undo already provide deterministic invalidation, so an
    empty result can safely remain cached and makes Freeform cost zero at idle.
    """
    if scene is None:
        return ()
    try:
        scene_key = int(scene.as_pointer())
        object_count = len(scene.objects)
    except FBP_DATA_ERRORS:
        scene_key = 0
        object_count = -1
    cached = _FBP_LATTICE_LIVE_SCENE_CACHE.get(scene_key) if scene_key else None
    if cached is not None and int(cached.get("object_count", -2)) == object_count:
        try:
            resolved = tuple(
                scene.objects.get(name)
                for name in tuple(cached.get("rig_names", ()) or ())
            )
            if all(rig is not None for rig in resolved):
                return resolved
        except FBP_DATA_ERRORS:
            pass

    result = []
    try:
        objects = tuple(getattr(scene, "objects", ()) or ())
    except FBP_DATA_ERRORS:
        objects = ()
    for rig in objects:
        try:
            if not bool(getattr(rig, "is_fbp_control", False)):
                continue
            if not _fbp_is_enabled(rig, FBP_EFFECT_LATTICE):
                continue
            if _fbp_lattice_mode(rig) != "CAMERA_FLATTEN":
                continue
            if not bool(getattr(rig, "fbp_lattice_live_update", True)):
                continue
            result.append(rig)
        except FBP_DATA_ERRORS:
            continue
    result = tuple(result)
    if scene_key:
        if len(_FBP_LATTICE_LIVE_SCENE_CACHE) >= 64 and scene_key not in _FBP_LATTICE_LIVE_SCENE_CACHE:
            _FBP_LATTICE_LIVE_SCENE_CACHE.clear()
        _FBP_LATTICE_LIVE_SCENE_CACHE[scene_key] = {
            "object_count": object_count,
            "rig_names": tuple(str(getattr(rig, "name", "") or "") for rig in result),
        }
    return result


def fbp_update_live_lattices(scene=None, *, force=False):
    """Update only live Camera Flatten cages.

    Freeform cages are fully native and require no Python transform polling.
    This prevents recursive depsgraph writes while reducing idle scene scans.
    """
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None or fbp_undo_guard_active():
        return 0
    updated = 0
    for rig in _fbp_live_lattice_rigs(scene):
        try:
            if not (
                _fbp_lattice_camera_flatten_enabled(rig)
                and bool(getattr(rig, "fbp_lattice_live_update", True))
            ):
                continue
            helper = _fbp_lattice_object(rig)
            if helper is None:
                if not _fbp_apply_lattice_effect(rig, select=False):
                    continue
                helper = _fbp_lattice_object(rig)
            updated += int(_fbp_apply_lattice_camera_flatten(rig, scene=scene, force=force))
        except FBP_DATA_ERRORS:
            continue
    return updated


def schedule_live_lattice_updates(scene=None, *, force=False):
    """Defer live Camera Flatten writes outside depsgraph callbacks."""
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return False
    if not force and not _fbp_live_lattice_rigs(scene):
        return False
    try:
        scene_key = int(scene.as_pointer())
    except FBP_DATA_ERRORS:
        scene_key = 0
    pending_key = (scene_key, bool(force))
    _FBP_LATTICE_LAST_ACTIVITY[scene_key] = time.monotonic()
    if pending_key in _FBP_LATTICE_UPDATE_PENDING:
        return False
    _FBP_LATTICE_UPDATE_PENDING.add(pending_key)

    def _run():
        # Debounce layer/camera motion before recalculating Camera Flatten.
        # Freeform point editing never enters this timer.
        elapsed = time.monotonic() - float(_FBP_LATTICE_LAST_ACTIVITY.get(scene_key, 0.0) or 0.0)
        if elapsed < 0.12:
            return max(0.02, 0.12 - elapsed)
        _FBP_LATTICE_UPDATE_PENDING.discard(pending_key)
        _FBP_LATTICE_LAST_ACTIVITY.pop(scene_key, None)
        active_scene = None
        try:
            active_scene = next(
                (candidate for candidate in bpy.data.scenes if int(candidate.as_pointer()) == scene_key),
                None,
            )
        except FBP_DATA_ERRORS:
            active_scene = None
        if active_scene is not None:
            fbp_update_live_lattices(active_scene, force=force)
        return None

    try:
        from .safe_tasks import schedule_once
        return bool(schedule_once(
            f"lattice.update.{scene_key}.{int(bool(force))}",
            _run,
            first_interval=0.12,
        ))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        _FBP_LATTICE_UPDATE_PENDING.discard(pending_key)
        _FBP_LATTICE_LAST_ACTIVITY.pop(scene_key, None)
        return False


def update_lattice_effect_cb(rig, context=None):
    """Debounce structural Lattice updates triggered by slider drags.

    A single drag can emit many RNA updates. Rebuilding topology and subdivision
    for every sample made the sidebar feel sticky and could reset a cage several
    times before the mouse was released.
    """
    if fbp_is_silent_property_update(rig):
        return None
    if fbp_render_mutation_blocked() or not rig:
        return None
    try:
        enabled = _fbp_is_enabled(rig, FBP_EFFECT_LATTICE)
    except FBP_DATA_ERRORS:
        enabled = False
    if not enabled:
        return None

    _fbp_invalidate_live_lattice_cache()
    _FBP_LATTICE_REPAIR_ATTEMPTED.pop(_fbp_lattice_error_key(rig), None)
    rig_key = _fbp_lattice_runtime_key(rig)
    rig_name = str(getattr(rig, "name", "") or "")
    scene_name = str(getattr(getattr(context, "scene", None), "name", "") or "") if context else ""

    def _run():
        active_rig = fbp_find_id_by_runtime_key(bpy.data.objects, rig_key, rig_name)
        if active_rig is None or not _fbp_is_enabled(active_rig, FBP_EFFECT_LATTICE):
            return None
        # The transactional apply path already performs one forced Camera
        # Flatten when topology changed. Do not calculate the same cage twice.
        _fbp_apply_lattice_effect(active_rig, select=False)
        return None

    try:
        from .safe_tasks import schedule_once
        schedule_once(
            f"lattice.property.{rig_key or rig_name}",
            _run,
            first_interval=0.06,
        )
        # False also means an equivalent task is already queued, which is the
        # desired debounce behavior rather than a reason to rebuild immediately.
        return None
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    _run()
    return None


def update_lattice_grid_preset_cb(rig, context=None):
    """Apply a named planar-grid preset without counting the corner points."""
    if fbp_is_silent_property_update(rig) or not rig:
        return None
    _fbp_apply_lattice_grid_settings(rig)
    return update_lattice_effect_cb(rig, context)


def update_lattice_custom_loops_cb(rig, context=None, axis="U"):
    """Synchronize linked custom loop counts and rebuild the planar cage once."""
    if fbp_is_silent_property_update(rig) or not rig:
        return None
    try:
        if bool(getattr(rig, "fbp_lattice_link_loops", True)):
            source_name = "fbp_lattice_custom_loops_v" if str(axis).upper() == "V" else "fbp_lattice_custom_loops_u"
            target_name = "fbp_lattice_custom_loops_u" if str(axis).upper() == "V" else "fbp_lattice_custom_loops_v"
            value = max(0, min(62, int(getattr(rig, source_name, 6) or 0)))
            if int(getattr(rig, target_name, value) or 0) != value:
                fbp_set_rna_property_silent(rig, target_name, value)
    except FBP_DATA_ERRORS:
        pass
    try:
        preset = str(getattr(rig, "fbp_lattice_grid_preset", "LOOPS_2") or "LOOPS_2").upper()
    except FBP_DATA_ERRORS:
        preset = "LOOPS_2"
    if preset != "CUSTOM":
        return None
    _fbp_apply_lattice_grid_settings(rig)
    return update_lattice_effect_cb(rig, context)


def update_lattice_loop_link_cb(rig, context=None):
    """When the chain is enabled, immediately make both custom axes equal."""
    if fbp_is_silent_property_update(rig) or not rig:
        return None
    try:
        linked = bool(getattr(rig, "fbp_lattice_link_loops", True))
    except FBP_DATA_ERRORS:
        linked = True
    if linked:
        try:
            value = max(0, min(62, int(getattr(rig, "fbp_lattice_custom_loops_u", 6) or 0)))
            fbp_set_rna_property_silent(rig, "fbp_lattice_custom_loops_v", value)
        except FBP_DATA_ERRORS:
            pass
    try:
        custom = str(getattr(rig, "fbp_lattice_grid_preset", "LOOPS_2") or "LOOPS_2").upper() == "CUSTOM"
    except FBP_DATA_ERRORS:
        custom = False
    if custom:
        _fbp_apply_lattice_grid_settings(rig)
        return update_lattice_effect_cb(rig, context)
    return None


def update_lattice_mesh_detail_cb(rig, context=None):
    """Debounce only the optional Simple Subdivision modifier.

    Mesh density changes do not touch cage topology or control points, so they
    must not run the complete Lattice transaction.
    """
    if fbp_is_silent_property_update(rig) or fbp_render_mutation_blocked() or not rig:
        return None
    try:
        if not _fbp_is_enabled(rig, FBP_EFFECT_LATTICE):
            return None
    except FBP_DATA_ERRORS:
        return None
    rig_key = _fbp_lattice_runtime_key(rig)
    rig_name = str(getattr(rig, "name", "") or "")

    def _run():
        active_rig = fbp_find_id_by_runtime_key(bpy.data.objects, rig_key, rig_name)
        if active_rig is None or not _fbp_is_enabled(active_rig, FBP_EFFECT_LATTICE):
            return None
        plane = _fbp_plane(active_rig, repair=False)
        helper = _fbp_lattice_object(active_rig)
        modifier = _fbp_lattice_modifier(plane)
        if not _fbp_lattice_contract_is_valid(active_rig, plane, helper, modifier):
            _fbp_apply_lattice_effect(active_rig, select=False)
            return None
        detail = _fbp_sync_lattice_detail_modifier(active_rig, plane, modifier)
        _fbp_configure_lattice_visibility(
            active_rig, plane, helper, modifier, detail, context=getattr(bpy, "context", None)
        )
        return None

    try:
        from .safe_tasks import schedule_once
        schedule_once(
            f"lattice.mesh_detail.{rig_key or rig_name}",
            _run,
            first_interval=0.04,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        _run()
    return None


def update_lattice_camera_settings_cb(rig, context=None):
    """Update mode/live/influence without rebuilding cage or mesh detail."""
    if fbp_is_silent_property_update(rig) or fbp_render_mutation_blocked() or not rig:
        return None
    try:
        if not _fbp_is_enabled(rig, FBP_EFFECT_LATTICE):
            return None
    except FBP_DATA_ERRORS:
        return None
    _fbp_invalidate_live_lattice_cache()
    rig_key = _fbp_lattice_runtime_key(rig)
    rig_name = str(getattr(rig, "name", "") or "")
    scene_name = str(getattr(getattr(context, "scene", None), "name", "") or "") if context else ""

    def _run():
        active_rig = fbp_find_id_by_runtime_key(bpy.data.objects, rig_key, rig_name)
        if active_rig is None or not _fbp_is_enabled(active_rig, FBP_EFFECT_LATTICE):
            return None
        plane = _fbp_plane(active_rig, repair=False)
        helper = _fbp_lattice_object(active_rig)
        modifier = _fbp_lattice_modifier(plane)
        if not _fbp_lattice_contract_is_valid(active_rig, plane, helper, modifier):
            _fbp_apply_lattice_effect(active_rig, select=False)
            return None
        mode = _fbp_lattice_mode(active_rig)
        try:
            helper[_FBP_LATTICE_MODE_KEY] = mode
        except FBP_DATA_ERRORS:
            pass
        if mode == "CAMERA_FLATTEN":
            scene = bpy.data.scenes.get(scene_name) if scene_name else getattr(bpy.context, "scene", None)
            _fbp_apply_lattice_camera_flatten(active_rig, scene=scene, force=True)
        else:
            cache_key = _fbp_lattice_runtime_key(active_rig)
            if cache_key is not None:
                _FBP_LATTICE_FLATTEN_CACHE.pop(cache_key, None)
            _fbp_stabilize_lattice_helper(helper)
        return None

    try:
        from .safe_tasks import schedule_once
        schedule_once(
            f"lattice.camera_settings.{rig_key or rig_name}",
            _run,
            first_interval=0.04,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        _run()
    return None


def update_lattice_visibility_cb(rig, context=None):
    """Apply cage visibility immediately without rebuilding its topology."""
    if fbp_is_silent_property_update(rig) or not rig:
        return None
    plane = _fbp_plane(rig, repair=False)
    helper = _fbp_lattice_object(rig)
    modifier = _fbp_lattice_modifier(plane)
    if helper is not None and modifier is not None:
        _fbp_configure_lattice_visibility(
            rig,
            plane,
            helper,
            modifier,
            _fbp_lattice_detail_modifier(plane),
            context=context,
        )
    return None


def update_lattice_interpolation_cb(rig, context=None):
    """Update interpolation without rebuilding modifiers or resetting points."""
    if fbp_is_silent_property_update(rig) or not rig:
        return None
    try:
        if not _fbp_is_enabled(rig, FBP_EFFECT_LATTICE):
            return None
    except FBP_DATA_ERRORS:
        return None
    helper = _fbp_lattice_object(rig)
    if helper is None:
        # A missing cage still needs the normal transactional setup path.
        _fbp_apply_lattice_effect(rig, select=False)
        return None
    _fbp_update_lattice_data(rig, helper)
    try:
        helper.data.update_tag()
        helper.update_tag(refresh={'DATA'})
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        pass
    try:
        for item in sockets:
            if getattr(item, "name", "") == socket_name:
                return item
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not set effect input {socket_name}", exc)
        return False


def _fbp_scene_camera(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    camera = getattr(scene, "camera", None) if scene else None
    try:
        return camera if camera and getattr(camera, "type", "") == "CAMERA" else None
    except FBP_DATA_ERRORS:
        return None


_FBP_TRACK_TO_CAMERA_CONSTRAINT_NAME = "FBP • Track to Camera"


def _fbp_track_to_camera_constraint(rig):
    if not rig:
        return None
    try:
        for constraint in rig.constraints:
            if str(getattr(constraint, "name", "") or "") == _FBP_TRACK_TO_CAMERA_CONSTRAINT_NAME:
                return constraint
    except FBP_DATA_ERRORS:
        pass
    return None


def _fbp_remove_track_to_camera_constraint(rig):
    constraint = _fbp_track_to_camera_constraint(rig)
    if not constraint:
        return False
    try:
        rig.constraints.remove(constraint)
        return True
    except FBP_DATA_ERRORS:
        return False


def _fbp_remove_legacy_camera_billboard_modifier(rig):
    """Remove the pre-6.0.11 modifier while preserving visibility choices."""
    plane = _fbp_plane(rig)
    if not plane:
        return False
    removed = False
    viewport_visible = None
    render_visible = None
    try:
        modifiers = tuple(plane.modifiers)
    except FBP_DATA_ERRORS:
        return False
    for modifier in modifiers:
        try:
            if getattr(modifier, "type", "") != "NODES":
                continue
            node_group = getattr(modifier, "node_group", None)
            tagged = fbp_normalize_effect_id(modifier.get("fbp_effect_id", ""))
            group_tagged = fbp_normalize_effect_id(
                node_group.get("fbp_effect_id", "") if node_group else ""
            )
            group_name = str(getattr(node_group, "name", "") or "").lower()
            legacy = (
                tagged == FBP_EFFECT_CAMERA_BILLBOARD
                or group_tagged == FBP_EFFECT_CAMERA_BILLBOARD
                or "camera billboard" in group_name
            )
            if not legacy:
                continue
            if viewport_visible is None:
                viewport_visible = bool(getattr(modifier, "show_viewport", True))
                render_visible = bool(getattr(modifier, "show_render", True))
            plane.modifiers.remove(modifier)
            removed = True
            if (
                node_group
                and bool(node_group.get("fbp_private_effect_group", False))
                and int(getattr(node_group, "users", 0) or 0) == 0
            ):
                _fbp_remove_node_group(node_group)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not remove legacy Camera Billboard modifier", exc)
    if removed:
        constraint = _fbp_track_to_camera_constraint(rig)
        try:
            if viewport_visible is not None:
                _fbp_store_effect_visibility(
                    rig, FBP_EFFECT_CAMERA_BILLBOARD, viewport_visible
                )
                if constraint is not None:
                    constraint.mute = not viewport_visible
            if render_visible is not None:
                _fbp_store_effect_render_visibility(
                    rig, FBP_EFFECT_CAMERA_BILLBOARD, render_visible
                )
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not preserve Camera Billboard visibility", exc)
    return removed


def _fbp_apply_track_to_camera_constraint(rig, scene=None):
    """Track the complete rig, not only its generated plane geometry."""
    if not rig:
        return False
    camera = _fbp_scene_camera(scene)
    if not camera:
        return False
    mode = str(getattr(rig, "fbp_camera_billboard_mode", "FULL") or "FULL")
    constraint_type = "TRACK_TO" if mode == "FULL" else "LOCKED_TRACK"
    constraint = _fbp_track_to_camera_constraint(rig)
    if constraint is not None and str(getattr(constraint, "type", "") or "") != constraint_type:
        _fbp_remove_track_to_camera_constraint(rig)
        constraint = None
    created = constraint is None
    if constraint is None:
        try:
            constraint = rig.constraints.new(type=constraint_type)
            constraint.name = _FBP_TRACK_TO_CAMERA_CONSTRAINT_NAME
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not create Track to Camera constraint", exc)
            return False
    changed = created
    try:
        if getattr(constraint, "target", None) != camera:
            constraint.target = camera
            changed = True
        track_axis = "TRACK_NEGATIVE_Z" if bool(getattr(rig, "fbp_camera_billboard_flip", False)) else "TRACK_Z"
        if str(getattr(constraint, "track_axis", "") or "") != track_axis:
            constraint.track_axis = track_axis
            changed = True
        if constraint_type == "TRACK_TO":
            if str(getattr(constraint, "up_axis", "") or "") != "UP_Y":
                constraint.up_axis = "UP_Y"
                changed = True
        else:
            lock_axis = "LOCK_Y" if mode == "HORIZONTAL" else "LOCK_X"
            if str(getattr(constraint, "lock_axis", "") or "") != lock_axis:
                constraint.lock_axis = lock_axis
                changed = True
        influence = max(0.0, min(1.0, float(getattr(rig, "fbp_camera_billboard_influence", 1.0) or 0.0)))
        if abs(float(getattr(constraint, "influence", 1.0) or 0.0) - influence) > 1e-6:
            constraint.influence = influence
            changed = True
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not update Track to Camera constraint", exc)
        return False
    if _fbp_remove_legacy_camera_billboard_modifier(rig):
        changed = True
    return changed


def fbp_update_track_to_camera(rig, scene=None):
    if not rig or not _fbp_is_enabled(rig, FBP_EFFECT_CAMERA_BILLBOARD):
        return False
    return _fbp_apply_track_to_camera_constraint(rig, scene)


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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
        identity = fbp_obj_runtime_key(scene)
        return (
            identity if identity is not None else 0,
            str(getattr(scene, "name_full", getattr(scene, "name", "")) or ""),
        )
    except FBP_DATA_ERRORS:
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
            if _fbp_is_enabled(rig, FBP_EFFECT_CAMERA_BILLBOARD):
                changed = _fbp_apply_track_to_camera_constraint(rig, scene) or changed
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
        except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        return False


def _fbp_is_enabled(rig, effect_id):
    definition = fbp_effect_definition(effect_id)
    key = str(definition.get("enabled_key", "") or "")
    try:
        return bool(rig and key and rig.get(key, False))
    except FBP_DATA_ERRORS:
        return False


def _fbp_node_group_asset_id(node_group):
    try:
        return str(node_group.get("fbp_geometry_effect_id", "") or "") if node_group else ""
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        return False


def _fbp_group_declares_effect(node_group, effect_id):
    """Return True when a node group belongs to an effect, even if stale.

    Asset revisions are intentionally ignored here. This helper is used only
    to discover an existing modifier so the strict health check can replace
    its outdated node group without losing modifier order or animated inputs.
    """
    if not node_group:
        return False
    try:
        return (
            fbp_normalize_effect_id(node_group.get("fbp_effect_id", ""))
            == fbp_normalize_effect_id(effect_id)
        )
    except FBP_DATA_ERRORS:
        return False


def _fbp_invalidate_node_group_caches(node_group):
    """Forget cached RNA references before a node-group datablock is removed."""
    if node_group is None:
        return
    try:
        pointer = int(node_group.as_pointer())
    except FBP_DATA_ERRORS:
        pointer = None
    if pointer is not None:
        for cache in (
            _FBP_INTERFACE_INPUT_CACHE,
            _FBP_MATRIX_IMAGE_NODE_CACHE,
            _FBP_PRIVATE_IMAGE_SOURCE_SYNC_CACHE,
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
        definition = fbp_effect_definition(effect_id)
        if bool(definition.get("builtin", False)) and not _builtin_group_is_complete(
            cached, definition
        ):
            raise ReferenceError
        return cached
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            continue
        priority = 0 if getattr(node_group, "name", "") == canonical_name else 1
        candidates.append((priority, node_group))

    if candidates:
        node_group = sorted(candidates, key=lambda item: item[0])[0][1]
        if bool(definition.get("builtin", False)) and not _builtin_group_is_complete(node_group, definition):
            try:
                if int(getattr(node_group, "users", 0) or 0) == 0:
                    _fbp_remove_node_group(node_group)
            except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
                pass
            return _fbp_store_effect_group_cache(effect_id, node_group)

    if bool(definition.get("builtin", False)):
        try:
            node_group = create_builtin_effect_group(
                effect_id,
                definition,
                Path(__file__).resolve().parent / "assets",
            )
        except FBP_DATA_ERRORS as exc:
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
    except FBP_DATA_ERRORS as exc:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        effect_id = ""
    if effect_id == FBP_EFFECT_FELT_FUZZ:
        return _fbp_patch_fuzz_alpha_mask(node_group)
    try:
        if int(node_group.get("fbp_alpha_mask_patch_version", 0) or 0) >= FBP_ALPHA_MASK_PATCH_VERSION:
            return True
    except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            pass

    try:
        current_frame = int(getattr(getattr(bpy.context, "scene", None), "frame_current", 1))
        value = _fbp_geometry_image_frame(src_user, current_frame)
        if int(getattr(frame_input, "default_value", 0) or 0) == value:
            return False
        frame_input.default_value = value
        dst_owner.update_tag()
        return True
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
                pass
        return changed
    except FBP_DATA_ERRORS as exc:
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
    except FBP_DATA_ERRORS:
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
                except FBP_DATA_ERRORS:
                    tagged = ""
                if tagged in FBP_FRAME_SYNC_GEOMETRY_EFFECT_IDS:
                    resolved_modifiers.append(modifier)
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            continue
    if plane_changed:
        try:
            plane.update_tag()
        except FBP_DATA_ERRORS:
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
                # Effects with their own alpha-geometry contract already build and
                # sample a dedicated cutout mesh. Applying the generic alpha patch
                # would insert a second mask in front of that graph and disconnect
                # the image node actually used by Extrude/Cutout Outline.
                definition = fbp_effect_definition(effect_id)
                if (
                    not bool(definition.get("alpha_aware"))
                    or bool(definition.get("requires_alpha_geometry_contract"))
                ):
                    return current
                if _fbp_patch_alpha_mask(current):
                    return current
        except FBP_DATA_ERRORS:
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
        definition = fbp_effect_definition(effect_id)
        if (
            bool(definition.get("alpha_aware"))
            and not bool(definition.get("requires_alpha_geometry_contract"))
        ):
            if not _fbp_patch_alpha_mask(node_group):
                _fbp_remove_node_group(node_group)
                return None
        return node_group
    except FBP_DATA_ERRORS as exc:
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
        except FBP_DATA_ERRORS:
            pass

    for material in bpy.data.materials:
        try:
            if (
                material.get("fbp_effect_material_owner", "") == owner
                and fbp_normalize_effect_id(material.get("fbp_effect_material_id", "")) == effect_id
                and (not role or str(material.get("fbp_effect_material_role", "") or "") == role)
            ):
                return material
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS as exc:
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
                except FBP_DATA_ERRORS:
                    pass
    except FBP_DATA_ERRORS as exc:
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
        except FBP_DATA_ERRORS as exc:
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
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not configure Text Matrix source-color material", exc)
    return material


def _fbp_material_is_owned(material):
    try:
        return bool(material and material.get("fbp_owned", False))
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
            node_group = getattr(modifier, "node_group", None)
            if (
                tagged == effect_id
                or _fbp_group_declares_effect(node_group, effect_id)
                or _fbp_group_matches(node_group, effect_id)
            ):
                return modifier
    except FBP_DATA_ERRORS:
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
            node_group = getattr(modifier, "node_group", None)
            if (
                tagged == effect_id
                or _fbp_group_declares_effect(node_group, effect_id)
                or _fbp_group_matches(node_group, effect_id)
            ):
                result.append(modifier)
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            continue
        try:
            if node_group and bool(node_group.get("fbp_private_effect_group", False)) and node_group.users == 0:
                _fbp_remove_node_group(node_group)
        except FBP_DATA_ERRORS:
            pass


def _fbp_cast_effect_value(prop_name, value):
    enum_values = {
        "fbp_wind_pin_edge": {"LEFT": 0.0, "RIGHT": 1.0, "BOTTOM": 2.0, "TOP": 3.0, "ALL": 4.0, "VERTEX_GROUP": 5.0},
        "fbp_wind_motion_mode": {"SWAY": 0.0, "FLOW": 1.0, "RIPPLE": 2.0},
        "fbp_wind_ripple_direction": {"X": 0.0, "Y": 1.0, "RADIAL": 2.0},
        "fbp_wind_direction_space": {"LOCAL": 0.0, "WORLD": 1.0},
        "fbp_halftone_shape": {"CIRCLE": 0.0, "SQUARE": 1.0, "DIAMOND": 2.0, "LINE": 3.0},
        "fbp_dot_matrix_shape": {"CIRCLE": 0.0, "SQUARE": 1.0, "DIAMOND": 2.0, "LINE": 3.0},
        "fbp_camera_billboard_mode": {"FULL": 0.0, "HORIZONTAL": 1.0, "VERTICAL": 2.0},
        "fbp_thickness_mode": {"VOLUME": 0.0, "ARRAY": 1.0},
        "fbp_gradient_mask_type": {"LINEAR": 0.0, "RADIAL": 1.0},
        "fbp_channel_mask_channel": {"RED": 0.0, "GREEN": 1.0, "BLUE": 2.0, "ALPHA": 3.0, "LUMINANCE": 4.0},
        "fbp_shadow_mode": {"OUTER": 0.0, "INNER": 1.0},
        "fbp_shadow_blend_mode": {"NORMAL": 0.0, "MULTIPLY": 1.0, "SCREEN": 2.0, "OVERLAY": 3.0, "SOFT_LIGHT": 4.0, "HARD_LIGHT": 5.0, "ADD": 6.0, "DIFFERENCE": 7.0},
    }
    if prop_name in enum_values:
        return enum_values[prop_name].get(str(value), 0.0)
    if prop_name in {"fbp_gaussian_blur_samples", "fbp_directional_blur_samples"}:
        samples = max(3, min(25, int(value or 3)))
        return samples if samples % 2 else min(25, samples + 1)
    if prop_name == "fbp_felt_curl_amount":
        # The bundled group treats Curl Amount almost linearly. A quadratic
        # response creates actual self-turning coils at the upper half of the
        # slider while keeping subtle fuzz controllable near zero.
        curl = max(0.0, float(value or 0.0))
        return curl * (1.0 + curl * 0.85)
    if isinstance(value, bool):
        return bool(value)
    if prop_name.endswith(("subdivisions", "subdivision", "resolution")) or prop_name in {
        "fbp_felt_render_density",
        "fbp_mesh_wiggle_hold",
        "fbp_stop_motion_step_frames",
        "fbp_wind_stepped",
        "fbp_infinite_rotation_stepped",
        "fbp_felt_seed",
        "fbp_felt_alpha_resolution",
        "fbp_text_matrix_viewport_columns",
        "fbp_text_matrix_viewport_rows",
        "fbp_text_matrix_render_columns",
        "fbp_text_matrix_render_rows",
        "fbp_text_matrix_playback_columns",
        "fbp_text_matrix_playback_rows",
        "fbp_text_matrix_character_count",
        "fbp_cutout_outline_viewport_resolution",
        "fbp_cutout_outline_playback_resolution",
        "fbp_cutout_outline_render_resolution",
        "fbp_thickness_viewport_pixels_x",
        "fbp_thickness_viewport_pixels_y",
        "fbp_thickness_playback_pixels_x",
        "fbp_thickness_playback_pixels_y",
        "fbp_thickness_render_pixels_x",
        "fbp_thickness_render_pixels_y",
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
        instance_id = ensure_effect_instance_id(modifier, effect_id)
        _fbp_store_effect_instance_id(rig, effect_id, instance_id)
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
            except FBP_DATA_ERRORS:
                pass
        return target
    except FBP_DATA_ERRORS as exc:
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
        except FBP_DATA_ERRORS:
            pass
        _FBP_DEFAULT_FONT_CACHE = None
    try:
        for font in bpy.data.fonts:
            if str(getattr(font, "name", "")).startswith("Bfont"):
                _FBP_DEFAULT_FONT_CACHE = font
                return font
    except FBP_DATA_ERRORS:
        pass
    curve = None
    try:
        curve = bpy.data.curves.new("FBP_Default_Font_Loader", type="FONT")
        font = getattr(curve, "font", None)
        _FBP_DEFAULT_FONT_CACHE = font
        return font
    except FBP_DATA_ERRORS:
        return None
    finally:
        if curve is not None:
            try:
                bpy.data.curves.remove(curve)
            except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        pass
    changed = False
    for node in getattr(node_group, "nodes", ()):
        try:
            glyph_index = int(node.get("fbp_text_matrix_glyph_index", -1))
        except FBP_DATA_ERRORS:
            continue
        if glyph_index < 0 or glyph_index >= len(chars):
            continue
        socket = _fbp_node_socket(getattr(node, "inputs", ()), "String")
        if socket is None or str(getattr(socket, "default_value", "")) == chars[glyph_index]:
            continue
        try:
            socket.default_value = chars[glyph_index]
            changed = True
        except FBP_DATA_ERRORS:
            pass
    try:
        node_group["fbp_text_matrix_charset_signature"] = signature
    except FBP_DATA_ERRORS:
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
    extrude_grid = None
    if effect_id == FBP_EFFECT_THICKNESS and (
        full_update
        or bool(
            requested
            & {
                "fbp_thickness_viewport_pixels_x",
                "fbp_thickness_viewport_pixels_y",
            }
        )
    ):
        profile = "PLAYBACK" if _FBP_EFFECT_PLAYBACK_ACTIVE else "VIEWPORT"
        extrude_grid = _fbp_extrude_grid(rig, profile)

    updated = False
    for prop_name, socket_name in dict(definition.get("property_map", {})).items():
        if requested is not None and prop_name not in requested:
            continue
        try:
            value = getattr(rig, prop_name)
        except (AttributeError, ReferenceError):
            continue
        if extrude_grid is not None and prop_name in {
            "fbp_thickness_viewport_pixels_x",
            "fbp_thickness_viewport_pixels_y",
        }:
            value = (
                extrude_grid[0]
                if prop_name.endswith("_x") else extrude_grid[1]
            )
        else:
            value = _fbp_effect_runtime_value(
                rig, effect_id, prop_name, value, scene=scene
            )
            value = _fbp_effective_quality_value(
                rig, effect_id, prop_name, value
            )
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

    if effect_id == FBP_EFFECT_THICKNESS and (
        full_update
        or bool(
            requested
            & {
                "fbp_thickness_side_material",
                "fbp_thickness_side_color",
                "fbp_thickness_use_plane_colors",
            }
        )
    ):
        source_material = _fbp_plane_source_material(rig)
        if source_material is None:
            source_material, _source_image_node = _fbp_material_image_node(rig)
        if source_material is None:
            plane = _fbp_plane(rig)
            source_material = getattr(plane, "active_material", None) if plane else None
        try:
            use_plane_colors = bool(
                getattr(rig, "fbp_thickness_use_plane_colors", False)
            )
            material = source_material if use_plane_colors else getattr(
                rig, "fbp_thickness_side_material", None
            )
            if material is None:
                material = _fbp_ensure_owned_effect_material(
                    rig,
                    effect_id,
                    "Extrude",
                    tuple(getattr(rig, "fbp_thickness_side_color", (0.18, 0.12, 0.08, 1.0))),
                )
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            pass
    return updated or alpha_changed


def fbp_update_mesh_wiggle_modifier(rig, modifier=None):
    return fbp_update_geometry_effect(rig, FBP_EFFECT_MESH_WIGGLE, modifier)


def fbp_apply_geometry_effect(rig, effect_id, *, sync_items=True):
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
        except FBP_DATA_ERRORS as exc:
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
        instance_id = ensure_effect_instance_id(modifier, effect_id)
        _fbp_store_effect_instance_id(rig, effect_id, instance_id)
        if bool(definition.get("custom", False)):
            _fbp_initialize_custom_geometry_inputs(modifier, node_group)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not configure Geometry Nodes effect", exc)
        return False

    if previous_group and previous_group != node_group:
        try:
            if bool(previous_group.get("fbp_private_effect_group", False)) and previous_group.users == 0:
                _fbp_remove_node_group(previous_group)
        except FBP_DATA_ERRORS:
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
    stored_group = _fbp_stored_effect_group_id(rig, effect_id)
    if stored_group:
        fbp_set_effect_group_id(rig, effect_id, stored_group)
    # A False return here means that every socket already matched its target,
    # not that the modifier failed. Keeping a newly created modifier is required
    # when the bundled node-group defaults already equal the layer settings.
    fbp_update_geometry_effect(rig, effect_id, modifier)
    if effect_id == FBP_EFFECT_FELT_FUZZ:
        _fbp_cleanup_owned_effect_materials(rig, effect_id)
    _fbp_invalidate_effect_ids_cache(rig)
    if sync_items:
        fbp_sync_effect_items(rig)
    return True


def fbp_apply_mesh_wiggle(rig):
    return fbp_apply_geometry_effect(rig, FBP_EFFECT_MESH_WIGGLE)


def fbp_remove_geometry_effect(rig, effect_id, *, sync_items=True):
    effect_id = fbp_normalize_effect_id(effect_id)
    plane = _fbp_plane(rig)
    modifiers = _fbp_find_all_effect_modifiers(rig, effect_id)
    if not plane or not modifiers:
        cleaned = _fbp_set_enabled(rig, effect_id, False)
        cleaned = _fbp_clear_effect_visibility(rig, effect_id) or cleaned
        cleaned = _fbp_clear_effect_render_visibility(rig, effect_id) or cleaned
        if effect_id in {FBP_EFFECT_CUTOUT_OUTLINE, FBP_EFFECT_THICKNESS, FBP_EFFECT_FELT_FUZZ, FBP_EFFECT_TEXT_MATRIX}:
            cleaned = _fbp_cleanup_owned_effect_materials(rig, effect_id) or cleaned
        if cleaned:
            _fbp_invalidate_effect_ids_cache(rig)
        if rig and sync_items:
            fbp_sync_effect_items(rig)
        return cleaned

    # Snapshot the original slots because Geometry Nodes evaluation must not
    # replace the image material.
    try:
        material_snapshot = list(plane.data.materials) if getattr(plane, "data", None) else []
        active_material_index = int(getattr(plane, "active_material_index", 0) or 0)
    except FBP_DATA_ERRORS:
        material_snapshot = []
        active_material_index = 0

    removed_groups = []
    removed = False
    for modifier in list(modifiers):
        removed_groups.append(getattr(modifier, "node_group", None))
        try:
            plane.modifiers.remove(modifier)
            removed = True
        except FBP_DATA_ERRORS as exc:
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
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not restore the plane material after removing an effect", exc)

    if effect_id == FBP_EFFECT_MESH_WIGGLE:
        fbp_set_rna_property_silent(rig, "fbp_mesh_wiggle_enabled", False)
    if effect_id in {FBP_EFFECT_CUTOUT_OUTLINE, FBP_EFFECT_THICKNESS, FBP_EFFECT_FELT_FUZZ, FBP_EFFECT_TEXT_MATRIX}:
        _fbp_cleanup_owned_effect_materials(rig, effect_id)
    _fbp_set_enabled(rig, effect_id, False)
    _fbp_clear_effect_visibility(rig, effect_id)
    _fbp_clear_effect_render_visibility(rig, effect_id)

    for node_group in removed_groups:
        try:
            if node_group and bool(node_group.get("fbp_private_effect_group", False)) and node_group.users == 0:
                _fbp_remove_node_group(node_group)
        except FBP_DATA_ERRORS:
            pass
    _fbp_invalidate_effect_ids_cache(rig)
    if sync_items:
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
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        pass
    try:
        source = nodes.new("ShaderNodeRGB")
        source.name = "FBP_Procedural_Color_Source"
        source.label = "Frame by Plane Color Source"
        source.location = (-380.0, 80.0)
        source["fbp_procedural_color_source"] = True
        source.outputs[0].default_value = color
        return source.outputs[0]
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            return None
    return _fbp_node_socket(tex_coord.outputs, "UV", 2)


def _fbp_shader_effect_id(node):
    try:
        return fbp_normalize_effect_id(node.get("fbp_shader_effect_id", ""))
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        pass
    return normalized


def _fbp_stage_effect_nodes(material, stage):
    nodes_by_id = {
        _fbp_shader_effect_id(node): node
        for node in _fbp_shader_effect_nodes(material, stage=stage)
    }
    return [nodes_by_id[effect_id] for effect_id in _fbp_get_shader_stage_order(material, stage) if effect_id in nodes_by_id]


def _fbp_local_mask_helper_nodes(material, kind=None):
    if not material or not material.node_tree:
        return []
    result = []
    for node in material.node_tree.nodes:
        try:
            if not bool(node.get("fbp_local_effect_mask_helper", False)):
                continue
            if kind and str(node.get("fbp_local_effect_mask_kind", "") or "") != kind:
                continue
            result.append(node)
        except FBP_DATA_ERRORS:
            continue
    return result


def _fbp_follow_local_mask_chain(material, socket):
    if not material or not material.node_tree or socket is None:
        return None
    current = socket
    visited = set()
    for _ in range(64):
        links = [link for link in material.node_tree.links if link.from_socket == current]
        if not links:
            return None
        link = links[0]
        node = link.to_node
        if node in visited:
            return link.to_socket
        visited.add(node)
        try:
            is_helper = bool(node.get("fbp_local_effect_mask_helper", False))
        except FBP_DATA_ERRORS:
            is_helper = False
        if not is_helper:
            return link.to_socket
        current = _fbp_node_socket(node.outputs, "Color", 0) or _fbp_node_socket(node.outputs, "Value", 0)
        if current is None:
            return link.to_socket
    return None


def _fbp_remove_local_mask_helpers(material, kind=None):
    if not material or not material.node_tree:
        return False
    changed = False
    for node in list(_fbp_local_mask_helper_nodes(material, kind=kind)):
        try:
            material.node_tree.nodes.remove(node)
            changed = True
        except FBP_DATA_ERRORS:
            pass
    return changed


def _fbp_mask_output_socket(node):
    if node is None:
        return None
    definition = fbp_effect_definition(_fbp_shader_effect_id(node))
    name = str(definition.get("mask_output_socket", "Mask Out") or "Mask Out")
    return _fbp_node_socket(node.outputs, name)


def _fbp_local_masks_by_target(rig, mask_nodes):
    """Return active local mask nodes grouped by their receiving effect.

    The persistent target map is already cached per rig. Reusing it here avoids
    resolving the same target once for every material node during each stage
    rebuild, which is especially noticeable with multi-material or multi-edit
    layers.
    """
    nodes_by_id = {}
    for node in tuple(mask_nodes or ()):
        mask_id = _fbp_shader_effect_id(node)
        if not mask_id:
            continue
        try:
            if bool(getattr(node, "mute", False)):
                continue
        except FBP_DATA_ERRORS:
            pass
        if _fbp_mask_output_socket(node) is not None:
            nodes_by_id[mask_id] = node
    if not rig or not nodes_by_id:
        return {}
    result = {}
    for target, mask_ids in _fbp_mask_target_map(rig).items():
        if target == "LAYER":
            continue
        resolved = [nodes_by_id[mask_id] for mask_id in mask_ids if mask_id in nodes_by_id]
        if resolved:
            result[target] = resolved
    return result


def _fbp_connect_local_mask_uv_inputs(material, mask_nodes, source):
    """Connect procedural/image mask sampling to the correct pre-effect UV.

    Local masks on UV effects must sample the vector entering that specific UV
    effect. Masks on color effects sample the stable layer UV. Never feed a
    color socket into a mask UV input: Blender will coerce it to a vector and
    produce masks that appear frozen, uniform or dependent on image colors.
    """
    if not material or not material.node_tree or source is None:
        return False
    changed = False
    links = material.node_tree.links
    for node in tuple(mask_nodes or ()):
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
                links.remove(link)
            links.new(source, target)
            changed = True
        except FBP_DATA_ERRORS:
            continue
    return changed


def _fbp_local_mask_preview_socket(rig, mask_nodes):
    """Return the visible debug output of the last local mask in stack order."""
    if not rig:
        return None, ""
    preview_socket = None
    preview_id = ""
    for node in tuple(mask_nodes or ()):
        mask_id = _fbp_shader_effect_id(node)
        if not mask_id or fbp_effect_mask_target(rig, mask_id) == "LAYER":
            continue
        try:
            if bool(getattr(node, "mute", False)):
                continue
        except FBP_DATA_ERRORS:
            pass
        if fbp_effect_debug_mode(rig, mask_id) == "FINAL":
            continue
        definition = fbp_effect_definition(mask_id)
        socket = _fbp_node_socket(
            node.outputs, str(definition.get("output_socket", "Alpha Out") or "Alpha Out")
        ) or _fbp_mask_output_socket(node)
        if socket is not None:
            preview_socket = socket
            preview_id = mask_id
    return preview_socket, preview_id


def _fbp_apply_local_mask_preview(material, rig, mask_nodes, current, *, x=0.0, y=0.0):
    """Replace the color result with a grayscale local-mask diagnostic preview."""
    if not material or not material.node_tree or current is None:
        return current
    preview_socket, preview_id = _fbp_local_mask_preview_socket(rig, mask_nodes)
    if preview_socket is None:
        return current
    try:
        preview = material.node_tree.nodes.new("ShaderNodeMixRGB")
        preview.blend_type = "MIX"
        preview.name = f"FBP Local Mask Preview • {preview_id}"
        preview.label = "Local Mask Preview"
        preview.location = (x, y)
        preview.inputs[1].default_value = (0.0, 0.0, 0.0, 1.0)
        preview.inputs[2].default_value = (1.0, 1.0, 1.0, 1.0)
        preview["fbp_local_effect_mask_helper"] = True
        preview["fbp_local_effect_mask_kind"] = "COLOR"
        preview["fbp_local_effect_mask_preview"] = preview_id
        material.node_tree.links.new(preview_socket, preview.inputs[0])
        return preview.outputs[0]
    except FBP_DATA_ERRORS:
        return current


def _fbp_combined_mask_factor(material, mask_nodes, *, kind, x=0.0, y=0.0):
    sockets = [socket for socket in (_fbp_mask_output_socket(node) for node in mask_nodes) if socket is not None]
    if not sockets:
        return None
    current = sockets[0]
    for index, socket in enumerate(sockets[1:], 1):
        multiply = material.node_tree.nodes.new("ShaderNodeMath")
        multiply.operation = "MULTIPLY"
        multiply.name = f"FBP Local Effect Mask {kind} Factor {index}"
        multiply.label = "Combine Effect Masks"
        multiply.location = (x + index * 80.0, y - 120.0)
        multiply["fbp_local_effect_mask_helper"] = True
        multiply["fbp_local_effect_mask_kind"] = kind
        material.node_tree.links.new(current, multiply.inputs[0])
        material.node_tree.links.new(socket, multiply.inputs[1])
        current = multiply.outputs[0]
    return current


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
    for candidate in reversed(candidate_sources):
        if candidate is None:
            continue
        for link in material.node_tree.links:
            if link.from_socket != candidate:
                continue
            if link.to_node in effect_set:
                continue
            try:
                is_helper = bool(link.to_node.get("fbp_local_effect_mask_helper", False))
            except FBP_DATA_ERRORS:
                is_helper = False
            target_socket = (
                _fbp_follow_local_mask_chain(material, candidate)
                if is_helper else link.to_socket
            )
            if target_socket is None or getattr(target_socket, "node", None) in effect_set:
                continue
            return target_socket
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
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
                except FBP_DATA_ERRORS:
                    pass
        return

    if stage == "MASK":
        targets = set(_fbp_material_alpha_targets(material))
        for link in list(links):
            if (
                link.from_node in effect_set
                or link.to_node in effect_set
                or link.to_socket in targets
            ):
                try:
                    links.remove(link)
                except FBP_DATA_ERRORS:
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
                except FBP_DATA_ERRORS:
                    pass


def _fbp_link_alpha_effect_nodes(material, effect_nodes, base_alpha, *, primary=False):
    """Connect one ordered alpha chain and return its final socket."""
    if not material or not material.node_tree:
        return base_alpha, False
    current = base_alpha
    changed = False
    links = material.node_tree.links
    for node in effect_nodes:
        definition = fbp_effect_definition(_fbp_shader_effect_id(node))
        input_name = str(
            definition.get("input_socket", "")
            if primary else definition.get("alpha_input_socket", "")
        )
        output_name = str(
            definition.get("output_socket", "")
            if primary else definition.get("alpha_output_socket", "")
        )
        target = _fbp_node_socket(node.inputs, input_name) if input_name else None
        if target is not None and current is not None:
            try:
                if len(target.links) != 1 or target.links[0].from_socket != current:
                    for link in list(target.links):
                        links.remove(link)
                    links.new(current, target)
                    changed = True
            except FBP_DATA_ERRORS:
                pass
        if output_name:
            current = _fbp_node_socket(node.outputs, output_name) or current
    return current, changed


def _fbp_clear_mask_alpha_chain_links(material, mask_nodes):
    """Remove obsolete global-alpha links without touching local Mask Out links.

    A mask moved from Layer to one specific effect used to keep its previous
    Alpha In/Alpha Out chain. The local receiver then worked, but the same mask
    could still clip the complete layer. Preserve UV and diagnostic-preview
    links while removing only links that belong to the alpha chain.
    """
    if not material or not material.node_tree:
        return False
    alpha_inputs = set()
    alpha_outputs = set()
    for node in tuple(mask_nodes or ()):
        definition = fbp_effect_definition(_fbp_shader_effect_id(node))
        input_socket = _fbp_node_socket(
            node.inputs, str(definition.get("input_socket", "") or "")
        )
        output_socket = _fbp_node_socket(
            node.outputs, str(definition.get("output_socket", "") or "")
        )
        if input_socket is not None:
            alpha_inputs.add(input_socket)
        if output_socket is not None:
            alpha_outputs.add(output_socket)
    if not alpha_inputs and not alpha_outputs:
        return False
    alpha_targets = set(_fbp_material_alpha_targets(material))
    changed = False
    for link in list(material.node_tree.links):
        remove = link.to_socket in alpha_inputs
        if not remove and link.from_socket in alpha_outputs:
            helper_kind = ""
            try:
                helper_kind = str(link.to_node.get("fbp_local_effect_mask_kind", "") or "")
            except FBP_DATA_ERRORS:
                pass
            remove = (
                link.to_socket in alpha_inputs
                or link.to_socket in alpha_targets
                or helper_kind == "ALPHA"
            )
        if not remove:
            continue
        try:
            material.node_tree.links.remove(link)
            changed = True
        except FBP_DATA_ERRORS:
            pass
    return changed


def _fbp_relink_effect_alpha(material, effect_nodes, base_alpha):
    """Route effect alpha through local masks, then the global Mask Stack."""
    if not material or not material.node_tree:
        return False
    changed = _fbp_remove_local_mask_helpers(material, kind="ALPHA")
    links = material.node_tree.links
    rig = None
    try:
        owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
        rig = bpy.data.objects.get(owner_name) if owner_name else None
    except FBP_DATA_ERRORS:
        rig = None
    mask_nodes = _fbp_stage_effect_nodes(material, "MASK")
    changed = _fbp_clear_mask_alpha_chain_links(material, mask_nodes) or changed
    local_by_target = _fbp_local_masks_by_target(rig, mask_nodes)
    current = base_alpha
    for node in effect_nodes:
        effect_id = _fbp_shader_effect_id(node)
        definition = fbp_effect_definition(effect_id)
        previous = current
        alpha_input = _fbp_node_socket(node.inputs, str(definition.get("alpha_input_socket", "") or ""))
        if alpha_input is not None and current is not None:
            try:
                if len(alpha_input.links) != 1 or alpha_input.links[0].from_socket != current:
                    for link in list(alpha_input.links):
                        links.remove(link)
                    links.new(current, alpha_input)
                    changed = True
            except FBP_DATA_ERRORS:
                pass
        effect_alpha = _fbp_node_socket(node.outputs, str(definition.get("alpha_output_socket", "") or "")) or current
        masks = local_by_target.get(effect_id, ())
        if masks and previous is not None and effect_alpha is not None:
            factor = _fbp_combined_mask_factor(
                material, masks, kind="ALPHA", x=float(node.location.x), y=float(node.location.y) - 220.0
            )
            if factor is not None:
                inv = material.node_tree.nodes.new("ShaderNodeMath")
                inv.operation = "SUBTRACT"
                inv.inputs[0].default_value = 1.0
                inv.name = f"FBP Local Alpha Mask Invert • {effect_id}"
                inv["fbp_local_effect_mask_helper"] = True
                inv["fbp_local_effect_mask_kind"] = "ALPHA"
                a = material.node_tree.nodes.new("ShaderNodeMath")
                a.operation = "MULTIPLY"
                a.name = f"FBP Local Alpha Original • {effect_id}"
                a["fbp_local_effect_mask_helper"] = True
                a["fbp_local_effect_mask_kind"] = "ALPHA"
                b = material.node_tree.nodes.new("ShaderNodeMath")
                b.operation = "MULTIPLY"
                b.name = f"FBP Local Alpha Effect • {effect_id}"
                b["fbp_local_effect_mask_helper"] = True
                b["fbp_local_effect_mask_kind"] = "ALPHA"
                add = material.node_tree.nodes.new("ShaderNodeMath")
                add.operation = "ADD"
                add.name = f"FBP Local Alpha Result • {effect_id}"
                add["fbp_local_effect_mask_helper"] = True
                add["fbp_local_effect_mask_kind"] = "ALPHA"
                for helper_index, helper in enumerate((inv, a, b, add)):
                    helper.location = (float(node.location.x) + 90.0 + helper_index * 70.0, float(node.location.y) - 260.0)
                links.new(factor, inv.inputs[1])
                links.new(previous, a.inputs[0])
                links.new(inv.outputs[0], a.inputs[1])
                links.new(effect_alpha, b.inputs[0])
                links.new(factor, b.inputs[1])
                links.new(a.outputs[0], add.inputs[0])
                links.new(b.outputs[0], add.inputs[1])
                current = add.outputs[0]
            else:
                current = effect_alpha
        else:
            current = effect_alpha

    uv_source = _fbp_auxiliary_uv_source(material)
    global_masks = []
    local_target_by_mask = {
        mask_id: target
        for target, mask_ids in _fbp_mask_target_map(rig).items()
        for mask_id in mask_ids
    } if rig else {}
    base_uv_masks = []
    for index, node in enumerate(mask_nodes):
        mask_effect_id = _fbp_shader_effect_id(node)
        target_effect_id = local_target_by_mask.get(mask_effect_id, "LAYER")
        target_definition = fbp_effect_definition(target_effect_id)
        targets_uv_effect = str(target_definition.get("stage", "") or "") == "UV"
        if not targets_uv_effect:
            base_uv_masks.append(node)
        node.location = (180.0 + index * 190.0, -420.0)
        if target_effect_id == "LAYER":
            global_masks.append(node)
    changed = _fbp_connect_local_mask_uv_inputs(
        material, base_uv_masks, uv_source
    ) or changed
    current, mask_changed = _fbp_link_alpha_effect_nodes(
        material, global_masks, current, primary=True
    )
    changed = mask_changed or changed
    if current is None:
        return changed
    has_alpha_effect = bool(global_masks) or any(
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
        except FBP_DATA_ERRORS:
            pass
    return changed

def _fbp_color_stage_evaluation_nodes(material, rig=None):
    """Return color effect nodes in their real evaluation order."""
    effect_nodes = _fbp_stage_effect_nodes(material, "COLOR")
    if rig is None:
        try:
            owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
            rig = bpy.data.objects.get(owner_name) if owner_name else None
        except FBP_DATA_ERRORS:
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


def _fbp_rebuild_local_mask_receivers(material):
    """Rebuild every shader stage that can receive a local mask."""
    changed = _fbp_rebuild_shader_stage(material, "UV")
    changed = _fbp_rebuild_shader_stage(material, "COLOR") or changed
    try:
        if int(material.get("fbp_local_effect_mask_wiring_version", 0) or 0) != FBP_LOCAL_EFFECT_MASK_WIRING_VERSION:
            material["fbp_local_effect_mask_wiring_version"] = FBP_LOCAL_EFFECT_MASK_WIRING_VERSION
            changed = True
    except FBP_DATA_ERRORS:
        pass
    return changed


def _fbp_rebuild_shader_stage(material, stage, source_override=None, target_override=None):
    if not material or not material.node_tree:
        return False
    effect_nodes = _fbp_stage_effect_nodes(material, stage)
    links = material.node_tree.links
    image_node = _fbp_shader_image_node(material)

    if stage == "UV":
        source = source_override or _fbp_stage_external_uv_source(material, image_node, effect_nodes)
        target = _fbp_material_uv_target(material)
        _fbp_remove_local_mask_helpers(material, kind="UV")
        _fbp_remove_stage_links(material, image_node, stage, effect_nodes)
        current = source
        anchor = image_node or _fbp_gradient_ramp_node(material)
        anchor_x = float(getattr(anchor, "location", (-80.0, 0.0))[0])
        anchor_y = float(getattr(anchor, "location", (0.0, 0.0))[1])
        rig = None
        try:
            owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
            rig = bpy.data.objects.get(owner_name) if owner_name else None
        except FBP_DATA_ERRORS:
            rig = None
        local_masks_by_target = _fbp_local_masks_by_target(
            rig, _fbp_stage_effect_nodes(material, "MASK")
        )
        for index, node in enumerate(effect_nodes):
            effect_id = _fbp_shader_effect_id(node)
            definition = fbp_effect_definition(effect_id)
            input_socket = _fbp_node_socket(node.inputs, definition.get("input_socket", ""))
            output_socket = _fbp_node_socket(node.outputs, definition.get("output_socket", ""))
            previous = current
            if current and input_socket:
                try:
                    links.new(current, input_socket)
                except FBP_DATA_ERRORS:
                    pass
            effect_output = output_socket or current
            node.location = (anchor_x - 360.0 + index * 220.0, anchor_y - 220.0)
            masks = local_masks_by_target.get(effect_id, ())
            if masks and previous is not None and effect_output is not None:
                _fbp_connect_local_mask_uv_inputs(material, masks, previous)
                factor = _fbp_combined_mask_factor(
                    material, masks, kind="UV",
                    x=float(node.location.x), y=float(node.location.y) - 120.0,
                )
                if factor is not None:
                    mixer = material.node_tree.nodes.new("ShaderNodeMixRGB")
                    mixer.blend_type = "MIX"
                    mixer.name = f"FBP UV Effect Mask Mix • {effect_id}"
                    mixer.label = "UV Effect Mask"
                    mixer.location = (float(node.location.x) + 150.0, float(node.location.y))
                    mixer["fbp_local_effect_mask_helper"] = True
                    mixer["fbp_local_effect_mask_kind"] = "UV"
                    mixer["fbp_local_effect_mask_target"] = effect_id
                    links.new(factor, mixer.inputs[0])
                    links.new(previous, mixer.inputs[1])
                    links.new(effect_output, mixer.inputs[2])
                    current = mixer.outputs[0]
                else:
                    current = effect_output
            else:
                current = effect_output
        if current and target:
            try:
                links.new(current, target)
            except FBP_DATA_ERRORS:
                pass
        _fbp_connect_color_aux_uv(material, image_node, current)
        return bool(current)

    if stage == "MASK":
        rig = None
        try:
            owner_name = str(material.get("fbp_effect_rig_owner", "") or "")
            rig = bpy.data.objects.get(owner_name) if owner_name else None
        except FBP_DATA_ERRORS:
            rig = None
        if (
            (rig and bool(_fbp_mask_target_map(rig)))
            or bool(_fbp_local_mask_helper_nodes(material))
        ):
            return _fbp_rebuild_local_mask_receivers(material)
        _fbp_remove_stage_links(material, image_node, stage, effect_nodes)
        layer_alpha = _fbp_material_layer_alpha_source(material, image_node)
        evaluation_nodes = _fbp_color_stage_evaluation_nodes(material, rig)
        return _fbp_relink_effect_alpha(material, evaluation_nodes, layer_alpha)

    if stage != "COLOR":
        return False

    source = _fbp_material_color_source(material, create=True)
    target = target_override or _fbp_stage_external_target(material, image_node, stage, effect_nodes)
    if source is None or target is None:
        return False
    _fbp_remove_local_mask_helpers(material, kind="COLOR")
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
    except FBP_DATA_ERRORS:
        rig = None
    # Final Material is deliberately evaluated as a terminal pass. This keeps
    # the graph acyclic: normal Previous/Original effects build the regular
    # stack first, then every Final Material effect processes that completed
    # result in its relative stack order.
    evaluation_nodes = _fbp_color_stage_evaluation_nodes(material, rig)

    local_masks_by_target = _fbp_local_masks_by_target(
        rig, _fbp_stage_effect_nodes(material, "MASK")
    )
    for index, node in enumerate(evaluation_nodes):
        effect_id = _fbp_shader_effect_id(node)
        definition = fbp_effect_definition(effect_id)
        input_socket = _fbp_node_socket(node.inputs, definition.get("input_socket", ""))
        output_socket = _fbp_node_socket(node.outputs, definition.get("output_socket", ""))
        input_source = fbp_effect_input_source(rig, effect_id) if rig else "PREVIOUS"
        previous = current
        node_source = source if input_source == "ORIGINAL" else current
        if node_source and input_socket:
            try:
                links.new(node_source, input_socket)
            except FBP_DATA_ERRORS:
                pass
        if uv_source:
            uv_input = _fbp_node_socket(node.inputs, definition.get("uv_input_socket", ""))
            if uv_input:
                try:
                    links.new(uv_source, uv_input)
                except FBP_DATA_ERRORS:
                    pass
        effect_output = output_socket or current
        node.location = (anchor_x + 120.0 + index * 240.0, anchor_y + 250.0)
        masks = local_masks_by_target.get(effect_id, ())
        if masks and previous is not None and effect_output is not None:
            # Color effects do not alter the layer UV. Their masks therefore
            # sample the stable UV source, while the color blend still mixes
            # the previous and processed colors below.
            _fbp_connect_local_mask_uv_inputs(material, masks, uv_source)
            factor = _fbp_combined_mask_factor(
                material, masks, kind="COLOR", x=float(node.location.x), y=float(node.location.y)
            )
            if factor is not None:
                mixer = material.node_tree.nodes.new("ShaderNodeMixRGB")
                mixer.blend_type = "MIX"
                mixer.name = f"FBP Effect Mask Mix • {effect_id}"
                mixer.label = "Effect Mask"
                mixer.location = (float(node.location.x) + 150.0, float(node.location.y))
                mixer["fbp_local_effect_mask_helper"] = True
                mixer["fbp_local_effect_mask_kind"] = "COLOR"
                mixer["fbp_local_effect_mask_target"] = effect_id
                links.new(factor, mixer.inputs[0])
                links.new(previous, mixer.inputs[1])
                links.new(effect_output, mixer.inputs[2])
                current = mixer.outputs[0]
            else:
                current = effect_output
        else:
            current = effect_output
    current = _fbp_apply_local_mask_preview(
        material,
        rig,
        _fbp_stage_effect_nodes(material, "MASK"),
        current,
        x=anchor_x + 120.0 + max(1, len(evaluation_nodes)) * 240.0,
        y=anchor_y + 250.0,
    )
    try:
        links.new(current, target)
    except FBP_DATA_ERRORS:
        return False
    _fbp_relink_effect_alpha(material, evaluation_nodes, layer_alpha)
    return True


def _fbp_depth_blur_focus_distance(rig, scene=None):
    """Resolve the effective focus distance for the Depth Blur effect."""
    fallback = max(0.0, float(getattr(rig, "fbp_depth_blur_focus_distance", 10.0) or 10.0))
    if not bool(getattr(rig, "fbp_depth_blur_use_camera_focus", True)):
        return fallback
    scene = scene or getattr(bpy.context, "scene", None)
    camera = _fbp_scene_camera(scene)
    camera_data = getattr(camera, "data", None) if camera else None
    dof = getattr(camera_data, "dof", None) if camera_data else None
    if camera is None or dof is None:
        return fallback
    focus_object = getattr(dof, "focus_object", None)
    if focus_object is not None:
        try:
            local = camera.matrix_world.inverted_safe() @ focus_object.matrix_world.translation
            return max(0.0, abs(float(local.z)))
        except FBP_DATA_ERRORS:
            pass
    try:
        return max(0.0, float(getattr(dof, "focus_distance", fallback) or fallback))
    except FBP_DATA_ERRORS:
        return fallback


def _fbp_sync_source_texel_inputs(rig, node, material=None):
    """Push inverse source-image dimensions into image-aware sampling effects."""
    if not rig or not node:
        return False
    material = material or _fbp_material_for_shader_node(rig, node)
    source_node = _fbp_shader_image_node(material) if material else None
    source_image = getattr(source_node, "image", None) if source_node else None
    width = height = 1
    try:
        size = tuple(getattr(source_image, "size", (1, 1)) or (1, 1))
        width = max(1, int(size[0]))
        height = max(1, int(size[1]))
    except FBP_DATA_ERRORS:
        pass
    changed = False
    for socket_name, value in (("Texel X", 1.0 / float(width)), ("Texel Y", 1.0 / float(height))):
        socket = _fbp_node_socket(getattr(node, "inputs", ()), socket_name)
        if socket is None or _fbp_effect_values_equal(getattr(socket, "default_value", None), value):
            continue
        try:
            socket.default_value = value
            changed = True
        except FBP_DATA_ERRORS:
            pass
    return changed


def _fbp_sync_depth_blur_runtime_inputs(rig, node, material=None, scene=None):
    """Push mode and camera focus into one private depth-blur node."""
    if not rig or not node:
        return False
    changed = False
    depth_mode = str(getattr(rig, "fbp_depth_blur_mode", "MANUAL") or "MANUAL") == "DEPTH"
    values = {
        "Mode": 1.0 if depth_mode else 0.0,
    }
    # Camera focus can change every frame, but it is irrelevant in Manual mode.
    # Avoid resolving camera/object matrices and touching the socket when the
    # effect uses a fixed radius.
    if depth_mode:
        values["Focus Distance"] = _fbp_depth_blur_focus_distance(rig, scene=scene)
    for socket_name, value in values.items():
        socket = _fbp_node_socket(getattr(node, "inputs", ()), socket_name)
        if socket is None or _fbp_effect_values_equal(getattr(socket, "default_value", None), value):
            continue
        try:
            socket.default_value = value
            changed = True
        except FBP_DATA_ERRORS:
            pass
    return changed

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
                except FBP_DATA_ERRORS:
                    pass

    if full_update and bool(definition.get("uses_source_texel", False)):
        material = _fbp_material_for_shader_node(rig, node)
        changed = _fbp_sync_source_texel_inputs(rig, node, material=material) or changed

    if bool(definition.get("mask_source_aware", False)) and (
        full_update or requested is None or str(definition.get("mask_source_property", "") or "") in requested
    ):
        _has_mask, mask_changed = _fbp_sync_mask_source(rig, effect_id, node)
        changed = mask_changed or changed

    if effect_id == FBP_EFFECT_IMPORTED_MASK and (
        full_update or requested is None or "fbp_imported_mask_path" in requested
    ):
        _has_imported_mask, imported_changed = _fbp_sync_imported_mask_image(rig, node)
        changed = imported_changed or changed

    if effect_id == FBP_EFFECT_LAYER_BLEND and (
        full_update or requested is None or "fbp_layer_blend_mode" in requested
    ):
        changed = _fbp_sync_layer_blend_mode(rig, node) or changed

    if bool(definition.get("object_mask_aware", False)) and (
        full_update
        or requested is None
        or str(definition.get("object_mask_pointer_property", "") or "") in requested
    ):
        _has_object, object_changed = _fbp_sync_object_mask_helper(
            rig, effect_id, node, create=True
        )
        changed = object_changed or changed

    if effect_id == FBP_EFFECT_DEPTH_BLUR and (
        full_update or requested is None or requested & {
            "fbp_depth_blur_mode", "fbp_depth_blur_use_camera_focus",
            "fbp_depth_blur_focus_distance",
        }
    ):
        material = _fbp_material_for_shader_node(rig, node)
        changed = _fbp_sync_depth_blur_runtime_inputs(
            rig, node, material=material, scene=scene
        ) or changed

    for prop_name, socket_name in dict(definition.get("property_map", {})).items():
        if requested is not None and prop_name not in requested:
            continue
        input_socket = _fbp_node_socket(node.inputs, socket_name)
        if input_socket is None:
            continue
        try:
            value = getattr(rig, prop_name)
            value = _fbp_effect_runtime_value(rig, effect_id, prop_name, value, scene=scene)
            value = _fbp_cast_effect_value(prop_name, value)
            value = tuple(value) if hasattr(value, "__len__") and not isinstance(value, str) else value
            if _fbp_effect_values_equal(getattr(input_socket, "default_value", None), value):
                continue
            input_socket.default_value = value
            changed = True
        except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
                pass

    aspect_effects = {
        FBP_EFFECT_HALFTONE,
        FBP_EFFECT_DOT_MATRIX,
        FBP_EFFECT_ASCII_MATRIX,
        FBP_EFFECT_ASCII,
    }
    aspect_properties = set()
    if effect_id in aspect_effects and (full_update or bool(requested & aspect_properties)):
        aspect_socket = _fbp_node_socket(node.inputs, "Aspect Ratio")
        if aspect_socket is not None:
            aspect = 1.0
            aspect = _fbp_rig_plane_aspect(rig)
            if not _fbp_effect_values_equal(aspect_socket.default_value, aspect):
                try:
                    aspect_socket.default_value = aspect
                    changed = True
                except FBP_DATA_ERRORS:
                    pass

    if effect_id == FBP_EFFECT_PIXELATE:
        pixel_properties = {
            "fbp_pixelate_resolution",
            "fbp_pixelate_height",
            "fbp_pixelate_grid_mode",
        }
        if full_update or bool(requested & pixel_properties):
            pixels_x, pixels_y, _mode = _fbp_pixelate_grid(rig)
            for socket_name, value in (("Pixels X", float(pixels_x)), ("Pixels Y", float(pixels_y))):
                socket = _fbp_node_socket(node.inputs, socket_name)
                if socket is None or _fbp_effect_values_equal(socket.default_value, value):
                    continue
                try:
                    socket.default_value = value
                    changed = True
                except FBP_DATA_ERRORS:
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
                except FBP_DATA_ERRORS:
                    pass
    return changed


def _fbp_rig_plane_aspect(rig):
    """Return physical canvas width/height, including cropped UV spans.

    Auto-cropped planes keep the original canvas pivot and a sub-rectangle of
    the source UV map. Measuring mesh bounds alone therefore turns circles into
    ellipses. Dividing each physical dimension by its active UV span restores
    the original pixel-space aspect while remaining correct for uncropped and
    extended meshes.
    """
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
        width = max_x - min_x
        height = max_y - min_y
        if width <= 1e-8 or height <= 1e-8:
            return 1.0

        uv_span_x = uv_span_y = 1.0
        uv_layer = getattr(getattr(mesh, "uv_layers", None), "active", None)
        uv_data = getattr(uv_layer, "data", None)
        if uv_data:
            first_uv = uv_data[0].uv
            min_u = max_u = float(first_uv.x)
            min_v = max_v = float(first_uv.y)
            for loop_uv in uv_data[1:]:
                uv = loop_uv.uv
                u = float(uv.x)
                v = float(uv.y)
                min_u = min(min_u, u)
                max_u = max(max_u, u)
                min_v = min(min_v, v)
                max_v = max(max_v, v)
            uv_span_x = max(1e-8, max_u - min_u)
            uv_span_y = max(1e-8, max_v - min_v)

        physical_aspect = (width / uv_span_x) / (height / uv_span_y)
        return max(0.001, min(1000.0, float(physical_aspect)))
    except (AttributeError, IndexError, ReferenceError, RuntimeError, StopIteration, TypeError, ValueError):
        return 1.0

def _fbp_pixelate_grid(rig):
    """Return Pixelate's effective X by Y grid from one shared contract.

    Keeping this in one helper prevents the shader update, UI preview and
    Extrude dependency from drifting apart when Pixelate settings change.
    """
    try:
        pixels_x = max(1, int(getattr(rig, "fbp_pixelate_resolution", 64) or 64))
        mode = str(getattr(rig, "fbp_pixelate_grid_mode", "AUTO") or "AUTO")
        if mode == "EXACT":
            pixels_y = max(1, int(getattr(rig, "fbp_pixelate_height", 36) or 36))
        else:
            aspect = max(0.001, float(_fbp_rig_plane_aspect(rig) or 1.0))
            pixels_y = max(1, int(round(float(pixels_x) / aspect)))
    except FBP_DATA_ERRORS:
        pixels_x, pixels_y, mode = 64, 36, "AUTO"
    return pixels_x, pixels_y, mode


_FBP_EXTRUDE_SAFE_SAMPLE_BUDGETS = {
    "PLAYBACK": 65_536,
    "VIEWPORT": 262_144,
    "RENDER": 1_048_576,
}


def _fbp_limit_extrude_grid(pixels_x, pixels_y, profile, enabled=True):
    """Return a proportional grid within the quality profile's safe budget."""
    pixels_x = max(1, min(4096, int(pixels_x or 1)))
    pixels_y = max(1, min(4096, int(pixels_y or 1)))
    if not enabled:
        return pixels_x, pixels_y, False
    budget = int(_FBP_EXTRUDE_SAFE_SAMPLE_BUDGETS.get(
        str(profile or "VIEWPORT").upper(),
        _FBP_EXTRUDE_SAFE_SAMPLE_BUDGETS["VIEWPORT"],
    ))
    samples = pixels_x * pixels_y
    if samples <= budget:
        return pixels_x, pixels_y, False
    scale = math.sqrt(float(budget) / float(samples))
    limited_x = max(1, min(pixels_x, int(math.floor(pixels_x * scale))))
    limited_y = max(1, min(pixels_y, int(math.floor(pixels_y * scale))))
    while limited_x * limited_y > budget:
        if limited_x >= limited_y and limited_x > 1:
            limited_x -= 1
        elif limited_y > 1:
            limited_y -= 1
        else:
            break
    return limited_x, limited_y, True


def _fbp_extrude_follows_pixelate(rig, profile="VIEWPORT"):
    """Return True when Extrude should mirror a visible Pixelate grid."""
    try:
        if not bool(getattr(rig, "fbp_thickness_follow_pixelate", True)):
            return False
        if FBP_EFFECT_PIXELATE not in _fbp_runtime_effect_ids(rig):
            return False
        if str(profile or "VIEWPORT").upper() == "RENDER":
            return _fbp_stored_effect_render_visibility(
                rig, FBP_EFFECT_PIXELATE, True
            )
        return _fbp_stored_effect_visibility(rig, FBP_EFFECT_PIXELATE, True)
    except FBP_DATA_ERRORS:
        return False


def _fbp_extrude_grid(rig, profile="VIEWPORT"):
    """Resolve Extrude's effective grid for viewport, playback or render.

    The requested grid remains stored on the rig, while Safe Grid Limits can
    proportionally reduce only the evaluated grid. This keeps files editable
    and prevents accidental multi-million-cell meshes during playback.
    """
    profile = str(profile or "VIEWPORT").upper()
    try:
        safe_grid = bool(getattr(rig, "fbp_thickness_safe_grid", True))
    except FBP_DATA_ERRORS:
        safe_grid = True

    if _fbp_extrude_follows_pixelate(rig, profile):
        pixels_x, pixels_y, _mode = _fbp_pixelate_grid(rig)
        pixels_x, pixels_y, limited = _fbp_limit_extrude_grid(
            pixels_x, pixels_y, profile, safe_grid
        )
        return pixels_x, pixels_y, "PIXELATE_LIMITED" if limited else "PIXELATE"

    properties = {
        "VIEWPORT": ("fbp_thickness_viewport_pixels_x", "fbp_thickness_viewport_pixels_y"),
        "PLAYBACK": ("fbp_thickness_playback_pixels_x", "fbp_thickness_playback_pixels_y"),
        "RENDER": ("fbp_thickness_render_pixels_x", "fbp_thickness_render_pixels_y"),
    }
    prop_x, prop_y = properties.get(profile, properties["VIEWPORT"])
    try:
        pixels_x = max(1, min(4096, int(getattr(rig, prop_x, 128) or 128)))
        mode = str(getattr(rig, "fbp_thickness_grid_mode", "AUTO") or "AUTO")
        if mode == "EXACT":
            pixels_y = max(1, min(4096, int(getattr(rig, prop_y, pixels_x) or pixels_x)))
        else:
            aspect = max(0.001, float(_fbp_rig_plane_aspect(rig) or 1.0))
            pixels_y = max(1, min(4096, int(round(float(pixels_x) / aspect))))
    except FBP_DATA_ERRORS:
        pixels_x, pixels_y, mode = 128, 128, "AUTO"
    pixels_x, pixels_y, limited = _fbp_limit_extrude_grid(
        pixels_x, pixels_y, profile, safe_grid
    )
    return pixels_x, pixels_y, f"{mode}_LIMITED" if limited else mode


def _fbp_refresh_extrude_pixel_dependency(
    rig, *, force=False, modifier=None, scene=None
):
    """Refresh only Extrude's two grid sockets after Pixelate changes."""
    if not rig:
        return False
    try:
        follows_setting = bool(
            getattr(rig, "fbp_thickness_follow_pixelate", True)
        )
    except FBP_DATA_ERRORS:
        follows_setting = False
    if not follows_setting:
        return False
    if not force and not _fbp_extrude_follows_pixelate(rig):
        return False
    if FBP_EFFECT_THICKNESS not in _fbp_runtime_effect_ids(rig):
        return False
    return bool(
        fbp_update_geometry_effect(
            rig,
            FBP_EFFECT_THICKNESS,
            modifier=modifier,
            scene=scene,
            sync_alpha=False,
            property_names={
                "fbp_thickness_viewport_pixels_x",
                "fbp_thickness_viewport_pixels_y",
            },
        )
    )


def fbp_refresh_aspect_dependent_effect_grids(rig):
    """Refresh Auto Height grids after Crop/Extend changes plane aspect.

    Pixelate and Extrude derive their vertical sample count from the local plane
    bounds. Updating only the UI after a mesh-bound change can leave the actual
    shader or Geometry Nodes sockets on the previous aspect ratio.
    """
    if rig is None:
        return False
    active_ids = _fbp_runtime_effect_ids(rig)
    changed = False
    if (
        FBP_EFFECT_PIXELATE in active_ids
        and str(getattr(rig, "fbp_pixelate_grid_mode", "AUTO") or "AUTO") == "AUTO"
    ):
        changed = bool(
            fbp_update_shader_effect(
                rig,
                FBP_EFFECT_PIXELATE,
                property_names={
                    "fbp_pixelate_resolution",
                    "fbp_pixelate_height",
                },
            )
        ) or changed
    if FBP_EFFECT_THICKNESS in active_ids:
        follows_pixelate = _fbp_extrude_follows_pixelate(rig, "VIEWPORT")
        own_auto = (
            not follows_pixelate
            and str(getattr(rig, "fbp_thickness_grid_mode", "AUTO") or "AUTO")
            == "AUTO"
        )
        if follows_pixelate or own_auto:
            changed = bool(
                fbp_update_geometry_effect(
                    rig,
                    FBP_EFFECT_THICKNESS,
                    sync_alpha=False,
                    property_names={
                        "fbp_thickness_viewport_pixels_x",
                        "fbp_thickness_viewport_pixels_y",
                    },
                )
            ) or changed
    return changed


def _fbp_material_for_shader_node(rig, node):
    node_tree = getattr(node, "id_data", None) if node else None
    for material in _fbp_plane_materials(rig):
        if getattr(material, "node_tree", None) is node_tree:
            return material
    return None


def _fbp_matrix_source_image_nodes(node_group):
    """Return live private image nodes, caching only stable node names.

    Caching RNA node wrappers across a group rebuild is unsafe in Blender 5.1:
    the Python object may survive after its C node is deleted. Re-resolving the
    cached names preserves most of the lookup benefit without stale pointers.
    """
    if not node_group:
        return ()
    try:
        cache_key = _fbp_node_group_cache_key(node_group)
        if cache_key is None:
            return ()
        signature = (len(node_group.nodes),)
        cached = _FBP_MATRIX_IMAGE_NODE_CACHE.get(cache_key)
        if cached and cached[0] == signature:
            live = tuple(
                node for name in cached[1]
                for node in (node_group.nodes.get(name),)
                if node is not None and bool(node.get("fbp_matrix_source_image_node", False))
            )
            if len(live) == len(cached[1]):
                return live
        names = tuple(
            str(node.name)
            for node in node_group.nodes
            if bool(node.get("fbp_matrix_source_image_node", False))
        )
        if len(_FBP_MATRIX_IMAGE_NODE_CACHE) >= 512 and cache_key not in _FBP_MATRIX_IMAGE_NODE_CACHE:
            _FBP_MATRIX_IMAGE_NODE_CACHE.clear()
        _FBP_MATRIX_IMAGE_NODE_CACHE[cache_key] = (signature, names)
        return tuple(
            node for name in names
            for node in (node_group.nodes.get(name),)
            if node is not None
        )
    except FBP_DATA_ERRORS:
        return ()


def _fbp_copy_shader_image_user(source_node, target_node):
    """Copy sequence timing without retaining or dereferencing stale RNA nodes.

    Blender 5.1 can leave a Python wrapper alive for a node that was removed while
    an effect group was rebuilt. Reading ``ImageUser`` through that wrapper may
    crash in C before Python can raise ``ReferenceError``. Only freshly resolved
    nodes reach this helper, and still images skip ImageUser access entirely.
    """
    if source_node is None or target_node is None:
        return False
    try:
        source_image = getattr(source_node, "image", None)
        source_kind = str(getattr(source_image, "source", "") or "").upper()
    except FBP_DATA_ERRORS:
        return False
    if source_kind not in {"SEQUENCE", "MOVIE"}:
        return False
    try:
        source_user = getattr(source_node, "image_user", None)
        target_user = getattr(target_node, "image_user", None)
        if source_user is None or target_user is None:
            return False
        snapshot = tuple(
            getattr(source_user, attr)
            for attr in (
                "frame_duration", "frame_start", "frame_offset",
                "use_cyclic", "use_auto_refresh",
            )
        )
    except FBP_DATA_ERRORS:
        return False
    changed = False
    for attr, value in zip(
        ("frame_duration", "frame_start", "frame_offset", "use_cyclic", "use_auto_refresh"),
        snapshot,
        strict=True,
    ):
        try:
            if getattr(target_user, attr) != value:
                setattr(target_user, attr, value)
                changed = True
        except FBP_DATA_ERRORS:
            continue
    return changed


def _fbp_sync_private_shader_source(material, node_group):
    """Synchronize private image samples with a bounded validation cache.

    A sequence image datablock advances internally; copying the same ImageUser
    values into every blur sample on every frame is unnecessary.  Revalidate
    periodically so external node edits still self-heal without imposing nine
    image-node comparisons per frame and per layer.
    """
    image_nodes = _fbp_matrix_source_image_nodes(node_group)
    if not image_nodes:
        return False, False
    source_node = _fbp_shader_image_node(material)
    source_image = getattr(source_node, "image", None) if source_node else None
    try:
        group_key = _fbp_node_group_cache_key(node_group)
    except FBP_DATA_ERRORS:
        group_key = None
    try:
        image_key = fbp_obj_runtime_key(source_image) if source_image else None
    except FBP_DATA_ERRORS:
        image_key = None
    image_user = getattr(source_node, "image_user", None) if source_node else None
    user_signature = []
    for attr in ("frame_duration", "frame_start", "frame_offset", "use_cyclic", "use_auto_refresh"):
        try:
            user_signature.append(getattr(image_user, attr))
        except FBP_DATA_ERRORS:
            user_signature.append(None)
    try:
        source_signature = (
            image_key,
            str(getattr(source_node, "projection", "FLAT") or "FLAT"),
            float(getattr(source_node, "projection_blend", 0.0) or 0.0),
            tuple(user_signature),
            len(image_nodes),
        )
    except FBP_DATA_ERRORS:
        source_signature = (image_key, tuple(user_signature), len(image_nodes))
    now = time.monotonic()
    cached = _FBP_PRIVATE_IMAGE_SOURCE_SYNC_CACHE.get(group_key) if group_key is not None else None
    if cached and cached[0] == source_signature and now - float(cached[1]) < 2.0:
        return bool(source_image), False

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
                    except FBP_DATA_ERRORS:
                        continue
                try:
                    desired_interpolation = str(
                        image_node.get("fbp_source_interpolation", "Closest") or "Closest"
                    )
                    desired_extension = str(
                        image_node.get("fbp_source_extension", "EXTEND") or "EXTEND"
                    ).upper()
                    if desired_extension not in {"REPEAT", "EXTEND", "CLIP", "MIRROR"}:
                        desired_extension = "EXTEND"
                    if image_node.interpolation != desired_interpolation:
                        image_node.interpolation = desired_interpolation
                        changed = True
                    if image_node.extension != desired_extension:
                        image_node.extension = desired_extension
                        changed = True
                except FBP_DATA_ERRORS:
                    pass
                changed = _fbp_copy_shader_image_user(source_node, image_node) or changed
        except FBP_DATA_ERRORS:
            continue
    if group_key is not None:
        if len(_FBP_PRIVATE_IMAGE_SOURCE_SYNC_CACHE) >= 512 and group_key not in _FBP_PRIVATE_IMAGE_SOURCE_SYNC_CACHE:
            _FBP_PRIVATE_IMAGE_SOURCE_SYNC_CACHE.clear()
        _FBP_PRIVATE_IMAGE_SOURCE_SYNC_CACHE[group_key] = (source_signature, now)
    if changed:
        try:
            node_group.update_tag()
        except FBP_DATA_ERRORS:
            pass
    return bool(source_image), changed


def _fbp_mask_source_image_nodes(node_group):
    """Resolve live mask image nodes on demand.

    Do not cache ``ShaderNodeTexImage`` Python objects here. A private Clipping
    Mask group may be replaced with the same node count, making a length-based
    cache return wrappers for deleted nodes and causing an access violation.
    """
    if not node_group:
        return ()
    try:
        return tuple(
            node for node in node_group.nodes
            if bool(node.get("fbp_mask_source_image_node", False))
        )
    except FBP_DATA_ERRORS:
        return ()


def _fbp_mask_source_coord_nodes(node_group):
    """Return Texture Coordinate nodes bound to a track-matte source plane."""
    if not node_group:
        return ()
    try:
        return tuple(
            node for node in node_group.nodes
            if bool(node.get("fbp_mask_source_coord_node", False))
        )
    except FBP_DATA_ERRORS:
        return ()


def _fbp_mask_camera_coord_nodes(node_group):
    """Return live Texture Coordinate nodes bound to the active camera object."""
    if not node_group:
        return ()
    try:
        return tuple(
            node for node in node_group.nodes
            if bool(node.get("fbp_mask_camera_coord_node", False))
        )
    except FBP_DATA_ERRORS:
        return ()


def _fbp_source_plane_bounds(source_rig):
    """Return source plane, cropped local bounds and matching source-image UV."""
    try:
        plane = getattr(source_rig, "fbp_plane_target", None) if source_rig else None
        if not plane:
            return None, (-1.0, 1.0, -1.0, 1.0), (0.0, 1.0, 0.0, 1.0)

        points = []
        try:
            from .builder import fbp_plane_reference_bounds
            _source_bounds, cropped_bounds, _extended_bounds, uv_bounds = (
                fbp_plane_reference_bounds(source_rig)
            )
            min_x, max_x, min_y, max_y = tuple(float(v) for v in cropped_bounds)
            uv_min_x, uv_max_x, uv_min_y, uv_max_y = tuple(float(v) for v in uv_bounds)
            if abs(max_x - min_x) >= 1.0e-8 and abs(max_y - min_y) >= 1.0e-8:
                return (
                    plane,
                    (min_x, max_x, min_y, max_y),
                    (uv_min_x, uv_max_x, uv_min_y, uv_max_y),
                )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

        try:
            for point in tuple(getattr(plane, "bound_box", ()) or ()):
                if len(point) >= 2:
                    points.append((float(point[0]), float(point[1])))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            points = []
        if not points:
            mesh = getattr(plane, "data", None)
            vertices = tuple(getattr(mesh, "vertices", ()) or ()) if mesh else ()
            points = [(float(vertex.co.x), float(vertex.co.y)) for vertex in vertices]
        if not points:
            return plane, (-1.0, 1.0, -1.0, 1.0), (0.0, 1.0, 0.0, 1.0)
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        if abs(max_x - min_x) < 1.0e-8:
            min_x, max_x = -1.0, 1.0
        if abs(max_y - min_y) < 1.0e-8:
            min_y, max_y = -1.0, 1.0
        return plane, (min_x, max_x, min_y, max_y), (0.0, 1.0, 0.0, 1.0)
    except FBP_DATA_ERRORS:
        return None, (-1.0, 1.0, -1.0, 1.0), (0.0, 1.0, 0.0, 1.0)


def _fbp_clipping_camera_matrix(scene, source_plane):
    """Return camera-local -> source-plane-local affine coefficients.

    The shader intersects each camera ray with the actual source plane.  Passing
    the real transform avoids fitting errors and remains exact with parented or
    non-uniformly scaled planes. Evaluated matrices are copied immediately so no
    temporary RNA wrapper survives the synchronization call.
    """
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None or source_plane is None:
        return None
    try:
        camera_matrix = camera.matrix_world.copy()
        source_matrix = source_plane.matrix_world.copy()
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            camera_matrix = camera.evaluated_get(depsgraph).matrix_world.copy()
            source_matrix = source_plane.evaluated_get(depsgraph).matrix_world.copy()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        camera_to_source = source_matrix.inverted_safe() @ camera_matrix
        coefficients = tuple(
            float(camera_to_source[row][column])
            for row in range(3)
            for column in range(4)
        )
        if not all(math.isfinite(value) for value in coefficients):
            return None
        try:
            camera_type = str(getattr(getattr(camera, "data", None), "type", "PERSP") or "PERSP").upper()
        except FBP_DATA_ERRORS:
            camera_type = "PERSP"
        # Orthographic rays are parallel to camera -Z. If that direction lies
        # in the source plane, there is no unique intersection and the shader
        # should fall back to the ordinary source-transform mode.
        if camera_type == "ORTHO" and abs(coefficients[10]) < 1.0e-8:
            return None
        return coefficients
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ZeroDivisionError):
        return None

def _fbp_camera_projection_signature(scene, source_plane, coefficients):
    camera = getattr(scene, "camera", None) if scene else None
    if camera is None or coefficients is None:
        return (None,)
    try:
        camera_data = getattr(camera, "data", None)
        return (
            fbp_obj_runtime_key(camera),
            tuple(round(float(value), 8) for row in camera.matrix_world for value in row),
            str(getattr(camera_data, "type", "") or ""),
            round(float(getattr(camera_data, "lens", 0.0)), 6),
            round(float(getattr(camera_data, "ortho_scale", 0.0)), 6),
            round(float(getattr(camera_data, "shift_x", 0.0)), 6),
            round(float(getattr(camera_data, "shift_y", 0.0)), 6),
            tuple(round(float(value), 9) for value in coefficients),
            fbp_obj_runtime_key(source_plane),
        )
    except FBP_DATA_ERRORS:
        return (None,)


def _fbp_objects_share_scene(first, second, scene=None):
    """Return whether two object datablocks are linked to the same live Scene."""
    if not first or not second:
        return False
    try:
        if scene is not None:
            return (
                scene.objects.get(first.name) is first
                and scene.objects.get(second.name) is second
            )
        first_scenes = tuple(getattr(first, "users_scene", ()) or ())
        second_scenes = tuple(getattr(second, "users_scene", ()) or ())
        if first_scenes and second_scenes:
            first_keys = {int(item.as_pointer()) for item in first_scenes}
            return any(int(item.as_pointer()) in first_keys for item in second_scenes)
    except FBP_DATA_ERRORS:
        return False
    # Temporarily unlinked objects can occur during import/Undo. Do not reject
    # them solely because Blender has not populated users_scene yet.
    return True

def _fbp_matte_visibility_request_for_source(source_rig, scene=None):
    """Return the least restrictive active display request for one matte source."""
    if not source_rig:
        return "NORMAL"
    try:
        from .layers import iter_scene_fbp_rigs
        rigs = iter_scene_fbp_rigs(scene) if scene is not None else (
            obj for obj in bpy.data.objects if bool(getattr(obj, "is_fbp_control", False))
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        rigs = ()
    requests = []
    contracts = (
        (FBP_EFFECT_ALPHA_MATTE, "fbp_alpha_matte_source", "fbp_alpha_matte_source_display"),
        (FBP_EFFECT_LUMA_MATTE, "fbp_luma_matte_source", "fbp_luma_matte_source_display"),
    )
    for target in rigs or ():
        for effect_id, source_prop, display_prop in contracts:
            try:
                if not fbp_effect_is_active(target, effect_id):
                    continue
                if getattr(target, source_prop, None) is not source_rig:
                    continue
                if not _fbp_objects_share_scene(target, source_rig, scene=scene):
                    continue
                requests.append(str(getattr(target, display_prop, "GUIDE") or "GUIDE").upper())
            except FBP_DATA_ERRORS:
                continue
    if "NORMAL" in requests:
        return "NORMAL"
    if "GUIDE" in requests:
        return "GUIDE"
    if "HIDDEN" in requests:
        return "HIDDEN"
    return "NORMAL"


def fbp_apply_matte_source_visibility(source_rig, scene=None, *, restore_normal=True, mode=None):
    """Apply Guide/Hidden display without changing the source layer's eye property."""
    if not source_rig:
        return False
    plane = getattr(source_rig, "fbp_plane_target", None)
    if not plane:
        return False
    mode = str(mode or _fbp_matte_visibility_request_for_source(source_rig, scene=scene) or "NORMAL").upper()
    if mode == "NORMAL":
        if not restore_normal:
            return False
        try:
            visible = bool(getattr(source_rig, "fbp_is_visible", True))
            viewport_hidden = not visible
            render_hidden = not visible
        except FBP_DATA_ERRORS:
            return False
    elif mode == "GUIDE":
        viewport_hidden = False
        render_hidden = True
    else:
        viewport_hidden = True
        render_hidden = True
    changed = False
    try:
        if bool(getattr(plane, "hide_viewport", False)) != viewport_hidden:
            plane.hide_viewport = viewport_hidden
            changed = True
        if bool(getattr(plane, "hide_render", False)) != render_hidden:
            plane.hide_render = render_hidden
            changed = True
    except FBP_DATA_ERRORS:
        return False
    return changed


def fbp_sync_matte_source_visibility(scene=None):
    """Reconcile source visibility in one O(layers) pass after structural changes."""
    try:
        from .layers import iter_scene_fbp_rigs
        rigs = tuple(iter_scene_fbp_rigs(scene)) if scene is not None else tuple(
            obj for obj in bpy.data.objects if bool(getattr(obj, "is_fbp_control", False))
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        rigs = ()
    priority = {"HIDDEN": 1, "GUIDE": 2, "NORMAL": 3}
    requests = {}
    contracts = (
        (FBP_EFFECT_ALPHA_MATTE, "fbp_alpha_matte_source", "fbp_alpha_matte_source_display"),
        (FBP_EFFECT_LUMA_MATTE, "fbp_luma_matte_source", "fbp_luma_matte_source_display"),
    )
    for target in rigs:
        # Resolve the complete active stack once per rig. The runtime cache is
        # authoritative after external node edits and avoids two independent
        # material traversals for Alpha and Luma Matte checks.
        active_effect_ids = set(_fbp_runtime_effect_ids(target))
        for effect_id, source_prop, display_prop in contracts:
            try:
                if effect_id not in active_effect_ids:
                    continue
                source = getattr(target, source_prop, None)
                if (
                    not source
                    or source is target
                    or not bool(getattr(source, "is_fbp_control", False))
                    or bool(getattr(source, "fbp_is_color_plane", False))
                    or not _fbp_objects_share_scene(target, source, scene=scene)
                ):
                    continue
                mode = str(getattr(target, display_prop, "GUIDE") or "GUIDE").upper()
                key = fbp_obj_runtime_key(source)
                current = requests.get(key)
                if current is None or priority.get(mode, 2) > priority.get(current[1], 2):
                    requests[key] = (source, mode)
            except FBP_DATA_ERRORS:
                continue
    changed = False
    for rig in rigs:
        key = fbp_obj_runtime_key(rig)
        requested = requests.get(key)
        mode = requested[1] if requested else "NORMAL"
        changed = fbp_apply_matte_source_visibility(
            rig, scene=scene, mode=mode
        ) or changed
    return changed


def _fbp_scene_for_mask_rig(rig):
    """Resolve the scene that owns a mask rig without assuming active context."""
    try:
        scenes = tuple(getattr(rig, "users_scene", ()) or ()) if rig else ()
        if scenes:
            active = getattr(bpy.context, "scene", None)
            if active in scenes:
                return active
            return scenes[0]
    except FBP_DATA_ERRORS:
        pass
    return getattr(bpy.context, "scene", None)


def _fbp_sync_mask_source(rig, effect_id, node):
    """Bind a track-matte node group to another FBP layer's source media."""
    definition = fbp_effect_definition(effect_id)
    prop_name = str(definition.get("mask_source_property", "") or "")
    node_group = getattr(node, "node_tree", None) if node else None
    image_nodes = _fbp_mask_source_image_nodes(node_group)
    coord_nodes = _fbp_mask_source_coord_nodes(node_group)
    camera_coord_nodes = _fbp_mask_camera_coord_nodes(node_group)
    if not prop_name or not image_nodes:
        return False, False
    try:
        source_rig = getattr(rig, prop_name, None)
    except FBP_DATA_ERRORS:
        source_rig = None
    if (
        source_rig is rig
        or not bool(getattr(source_rig, "is_fbp_control", False))
        or bool(getattr(source_rig, "fbp_is_color_plane", False))
        or not _fbp_objects_share_scene(rig, source_rig)
    ):
        source_rig = None
    _source_material, source_node = _fbp_material_image_node(source_rig) if source_rig else (None, None)
    source_image = getattr(source_node, "image", None) if source_node else None
    source_user = None
    try:
        if source_node is not None and str(getattr(source_image, "source", "") or "").upper() in {"SEQUENCE", "MOVIE"}:
            source_user = getattr(source_node, "image_user", None)
    except FBP_DATA_ERRORS:
        source_user = None
    try:
        source_opacity = (
            max(0.0, min(1.0, float(getattr(source_rig, "fbp_opacity", 1.0))))
            if source_rig else 1.0
        )
        if effect_id == FBP_EFFECT_CLIPPING_MASK and source_rig is not None:
            # A clipped layer follows the visible base, including Eye/Solo.
            # Keep the source bound and drive its alpha to zero rather than
            # treating a hidden source as missing (missing sources pass through).
            source_opacity *= 1.0 if bool(getattr(source_rig, "fbp_is_visible", True)) else 0.0
    except FBP_DATA_ERRORS:
        source_opacity = 1.0
    source_plane, source_bounds, source_uv_bounds = _fbp_source_plane_bounds(source_rig)
    scene = _fbp_scene_for_mask_rig(rig)
    camera = getattr(scene, "camera", None) if scene is not None else None
    camera_requested = bool(
        effect_id == FBP_EFFECT_CLIPPING_MASK
        and getattr(rig, "fbp_clipping_mask_use_camera_projection", True)
    )
    camera_coefficients = (
        _fbp_clipping_camera_matrix(scene, source_plane)
        if camera_requested and source_plane is not None else None
    )
    camera_enabled = bool(camera_requested and camera_coefficients is not None)

    user_signature = []
    try:
        source_kind = str(getattr(source_image, "source", "") or "").upper()
    except FBP_DATA_ERRORS:
        source_kind = ""
    if source_kind in {"SEQUENCE", "MOVIE"} and source_user is not None:
        for attr in ("frame_duration", "frame_start", "frame_offset", "use_cyclic", "use_auto_refresh"):
            try:
                user_signature.append(getattr(source_user, attr))
            except FBP_DATA_ERRORS:
                user_signature.append(None)
    try:
        group_key = _fbp_node_group_cache_key(node_group)
        signature = (
            fbp_obj_runtime_key(source_rig) if source_rig else None,
            fbp_obj_runtime_key(source_image) if source_image else None,
            tuple(user_signature),
            fbp_obj_runtime_key(source_plane) if source_plane else None,
            tuple(round(float(value), 9) for value in source_bounds),
            tuple(round(float(value), 9) for value in source_uv_bounds),
            bool(camera_enabled),
            _fbp_camera_projection_signature(scene, source_plane, camera_coefficients),
            round(float(source_opacity), 6),
        )
    except FBP_DATA_ERRORS:
        group_key = None
        signature = (
            None, None, tuple(user_signature), None,
            tuple(source_bounds), tuple(source_uv_bounds),
            bool(camera_enabled), (None,), round(float(source_opacity), 6),
        )
    cached = _FBP_MASK_SOURCE_SYNC_CACHE.get(group_key) if group_key is not None else None
    if cached == signature:
        return bool(source_image), False
    changed = False
    for image_node in image_nodes:
        try:
            if getattr(image_node, "image", None) is not source_image:
                image_node.image = source_image
                changed = True
            if source_node is not None:
                changed = _fbp_copy_shader_image_user(source_node, image_node) or changed
            if image_node.interpolation != "Linear":
                image_node.interpolation = "Linear"
                changed = True
            if image_node.extension != "CLIP":
                image_node.extension = "CLIP"
                changed = True
        except FBP_DATA_ERRORS:
            continue
    for coord_node in coord_nodes:
        try:
            if getattr(coord_node, "object", None) is not source_plane:
                coord_node.object = source_plane
                changed = True
        except FBP_DATA_ERRORS:
            continue
    for camera_coord_node in camera_coord_nodes:
        try:
            if getattr(camera_coord_node, "object", None) is not camera:
                camera_coord_node.object = camera
                changed = True
        except FBP_DATA_ERRORS:
            continue
    for socket_name, value in zip(
        (
            "Source Min X", "Source Max X", "Source Min Y", "Source Max Y",
            "Source UV Min X", "Source UV Max X", "Source UV Min Y", "Source UV Max Y",
        ),
        tuple(source_bounds) + tuple(source_uv_bounds),
        strict=True,
    ):
        socket = _fbp_node_socket(getattr(node, "inputs", ()), socket_name)
        if socket is not None and not _fbp_effect_values_equal(
            getattr(socket, "default_value", None), value
        ):
            try:
                socket.default_value = float(value)
                changed = True
            except FBP_DATA_ERRORS:
                pass
    camera_perspective_socket = _fbp_node_socket(
        getattr(node, "inputs", ()), "Camera Perspective"
    )
    if camera_perspective_socket is not None:
        try:
            camera_is_perspective = 0.0 if str(getattr(getattr(camera, "data", None), "type", "PERSP") or "PERSP").upper() == "ORTHO" else 1.0
        except FBP_DATA_ERRORS:
            camera_is_perspective = 1.0
        if not _fbp_effect_values_equal(
            getattr(camera_perspective_socket, "default_value", None), camera_is_perspective
        ):
            try:
                camera_perspective_socket.default_value = camera_is_perspective
                changed = True
            except FBP_DATA_ERRORS:
                pass

    camera_projection_socket = _fbp_node_socket(
        getattr(node, "inputs", ()), "Use Camera Projection"
    )
    if camera_projection_socket is not None:
        desired_camera = 1.0 if camera_enabled else 0.0
        if not _fbp_effect_values_equal(
            getattr(camera_projection_socket, "default_value", None), desired_camera
        ):
            try:
                camera_projection_socket.default_value = desired_camera
                changed = True
            except FBP_DATA_ERRORS:
                pass
    if camera_coefficients is not None:
        for coefficient_name, value in zip(
            tuple(f"M{row}{column}" for row in range(3) for column in range(4)),
            camera_coefficients,
            strict=True,
        ):
            socket = _fbp_node_socket(
                getattr(node, "inputs", ()), f"Camera To Source {coefficient_name}"
            )
            if socket is not None and not _fbp_effect_values_equal(
                getattr(socket, "default_value", None), value
            ):
                try:
                    socket.default_value = float(value)
                    changed = True
                except FBP_DATA_ERRORS:
                    pass

    source_opacity_socket = _fbp_node_socket(getattr(node, "inputs", ()), "Source Opacity")
    if source_opacity_socket is not None and not _fbp_effect_values_equal(
        getattr(source_opacity_socket, "default_value", None), source_opacity
    ):
        try:
            source_opacity_socket.default_value = float(source_opacity)
            changed = True
        except FBP_DATA_ERRORS:
            pass

    use_socket_name = str(definition.get("mask_use_socket", "Use Mask Sample") or "Use Mask Sample")
    use_mask = _fbp_node_socket(getattr(node, "inputs", ()), use_socket_name)
    desired = 1.0 if source_image is not None else 0.0
    if use_mask is not None and not _fbp_effect_values_equal(
        getattr(use_mask, "default_value", None), desired
    ):
        try:
            use_mask.default_value = desired
            changed = True
        except FBP_DATA_ERRORS:
            pass
    if group_key is not None:
        if len(_FBP_MASK_SOURCE_SYNC_CACHE) >= 256 and group_key not in _FBP_MASK_SOURCE_SYNC_CACHE:
            _FBP_MASK_SOURCE_SYNC_CACHE.clear()
        _FBP_MASK_SOURCE_SYNC_CACHE[group_key] = signature
    if changed and node_group:
        try:
            node_group.update_tag()
        except FBP_DATA_ERRORS:
            pass
    return bool(source_image), changed


def _fbp_imported_mask_image_nodes(node_group):
    if not node_group:
        return ()
    try:
        return tuple(
            node for node in node_group.nodes
            if bool(node.get("fbp_imported_mask_image_node", False))
        )
    except FBP_DATA_ERRORS:
        return ()


def _fbp_sync_imported_mask_image(rig, node):
    """Load and bind one persistent mask image extracted from a layered document."""
    node_group = getattr(node, "node_tree", None) if node else None
    image_nodes = _fbp_imported_mask_image_nodes(node_group)
    if not image_nodes:
        return False, False
    try:
        raw_path = str(getattr(rig, "fbp_imported_mask_path", "") or "")
        path = bpy.path.abspath(raw_path) if raw_path else ""
        path = os.path.normcase(os.path.realpath(path)) if path else ""
    except (AttributeError, OSError, TypeError, ValueError):
        path = ""
    image = None
    if path and os.path.isfile(path):
        try:
            image = bpy.data.images.load(path, check_existing=True)
            try:
                image.colorspace_settings.name = "Non-Color"
            except FBP_DATA_ERRORS:
                pass
        except (OSError, RuntimeError, ValueError):
            image = None
    try:
        group_key = _fbp_node_group_cache_key(node_group)
        signature = (path, fbp_obj_runtime_key(image) if image else None)
    except FBP_DATA_ERRORS:
        group_key = None
        signature = (path, None)
    if group_key is not None and _FBP_IMPORTED_MASK_SYNC_CACHE.get(group_key) == signature:
        return bool(image), False
    changed = False
    for image_node in image_nodes:
        try:
            if getattr(image_node, "image", None) is not image:
                image_node.image = image
                changed = True
            if image_node.interpolation != "Linear":
                image_node.interpolation = "Linear"
                changed = True
            if image_node.extension != "CLIP":
                image_node.extension = "CLIP"
                changed = True
        except FBP_DATA_ERRORS:
            continue
    use_sample = _fbp_node_socket(getattr(node, "inputs", ()), "Use Mask Sample")
    desired = 1.0 if image is not None else 0.0
    if use_sample is not None and not _fbp_effect_values_equal(getattr(use_sample, "default_value", None), desired):
        try:
            use_sample.default_value = desired
            changed = True
        except FBP_DATA_ERRORS:
            pass
    if group_key is not None:
        if len(_FBP_IMPORTED_MASK_SYNC_CACHE) >= 256 and group_key not in _FBP_IMPORTED_MASK_SYNC_CACHE:
            _FBP_IMPORTED_MASK_SYNC_CACHE.clear()
        _FBP_IMPORTED_MASK_SYNC_CACHE[group_key] = signature
    if changed and node_group:
        try:
            node_group.update_tag()
        except FBP_DATA_ERRORS:
            pass
    return bool(image), changed


_FBP_LAYER_BLEND_NODE_TYPES = {
    "MULTIPLY": "MULTIPLY",
    "SCREEN": "SCREEN",
    "OVERLAY": "OVERLAY",
    "DARKEN": "DARKEN",
    "LIGHTEN": "LIGHTEN",
    "COLOR_DODGE": "DODGE",
    "DODGE": "DODGE",
    "COLOR_BURN": "BURN",
    "BURN": "BURN",
    "SOFT_LIGHT": "SOFT_LIGHT",
    "DIFFERENCE": "DIFFERENCE",
    "EXCLUSION": "EXCLUSION",
    "ADD": "ADD",
    "LINEAR_DODGE": "ADD",
    "SUBTRACT": "SUBTRACT",
    "DIVIDE": "DIVIDE",
    "HUE": "HUE",
    "SATURATION": "SATURATION",
    "COLOR": "COLOR",
    "LUMINOSITY": "VALUE",
    "VALUE": "VALUE",
    "LINEAR_LIGHT": "LINEAR_LIGHT",
}


def _fbp_sync_layer_blend_mode(rig, node):
    node_group = getattr(node, "node_tree", None) if node else None
    if not node_group:
        return False
    try:
        mode = str(getattr(rig, "fbp_layer_blend_mode", "MULTIPLY") or "MULTIPLY").upper()
    except FBP_DATA_ERRORS:
        mode = "MULTIPLY"
    hard_light = mode == "HARD_LIGHT"
    blend_type = _FBP_LAYER_BLEND_NODE_TYPES.get(mode, "MULTIPLY")
    changed = False
    try:
        for internal in node_group.nodes:
            if not bool(internal.get("fbp_layer_blend_mix_node", False)):
                continue
            if getattr(internal, "blend_type", None) != blend_type:
                internal.blend_type = blend_type
                changed = True
    except FBP_DATA_ERRORS:
        pass
    hard_socket = _fbp_node_socket(getattr(node, "inputs", ()), "Use Hard Light")
    desired = 1.0 if hard_light else 0.0
    if hard_socket is not None and not _fbp_effect_values_equal(getattr(hard_socket, "default_value", None), desired):
        try:
            hard_socket.default_value = desired
            changed = True
        except FBP_DATA_ERRORS:
            pass
    if changed:
        try:
            node_group.update_tag()
        except FBP_DATA_ERRORS:
            pass
    return changed


def _fbp_object_mask_coord_nodes(node_group):
    if not node_group:
        return ()
    try:
        return tuple(
            node for node in node_group.nodes
            if bool(node.get("fbp_object_mask_coord_node", False))
        )
    except FBP_DATA_ERRORS:
        return ()


def _fbp_object_mask_image_nodes(node_group):
    if not node_group:
        return ()
    try:
        return tuple(
            node for node in node_group.nodes
            if bool(node.get("fbp_object_mask_image_node", False))
        )
    except FBP_DATA_ERRORS:
        return ()


def _fbp_sync_object_mask_helper(rig, effect_id, node, *, create=True):
    definition = fbp_effect_definition(effect_id)
    if not bool(definition.get("object_mask_aware", False)):
        return False, False
    shape = str(definition.get("object_mask_shape", "SQUARE") or "SQUARE")
    pointer_prop = str(definition.get("object_mask_pointer_property", "") or "")
    mask_image = None
    bounds = (-1.0, 1.0, -1.0, 1.0)
    try:
        from .object_masks import (
            ensure_object_mask_helper,
            ensure_object_mask_image,
            find_object_mask_helper,
            object_mask_image_bounds,
        )
        helper = (
            ensure_object_mask_helper(rig, shape, context=bpy.context, select=False)
            if create else find_object_mask_helper(rig, shape)
        )
        if helper:
            mask_image, bounds, _geometry_changed = ensure_object_mask_image(helper, force=False)
            bounds = object_mask_image_bounds(helper, fallback=bounds)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        helper = getattr(rig, pointer_prop, None) if pointer_prop else None
    node_group = getattr(node, "node_tree", None) if node else None
    changed = False
    valid = bool(helper and mask_image and node_group)
    for coord in _fbp_object_mask_coord_nodes(node_group):
        try:
            if getattr(coord, "object", None) is not helper:
                coord.object = helper
                changed = True
        except FBP_DATA_ERRORS:
            continue
    for image_node in _fbp_object_mask_image_nodes(node_group):
        try:
            if getattr(image_node, "image", None) is not mask_image:
                image_node.image = mask_image
                changed = True
        except FBP_DATA_ERRORS:
            continue
    for socket_name, value in (
        ("Shape Min X", bounds[0]), ("Shape Max X", bounds[1]),
        ("Shape Min Y", bounds[2]), ("Shape Max Y", bounds[3]),
    ):
        socket = _fbp_node_socket(getattr(node, "inputs", ()), socket_name)
        if socket is None or _fbp_effect_values_equal(getattr(socket, "default_value", None), value):
            continue
        try:
            socket.default_value = float(value)
            changed = True
        except FBP_DATA_ERRORS:
            pass
    use_socket = _fbp_node_socket(getattr(node, "inputs", ()), "Use Mask Object")
    desired = 1.0 if valid else 0.0
    if use_socket is not None and not _fbp_effect_values_equal(getattr(use_socket, "default_value", None), desired):
        try:
            use_socket.default_value = desired
            changed = True
        except FBP_DATA_ERRORS:
            pass
    if changed and node_group:
        try:
            node_group.update_tag()
        except FBP_DATA_ERRORS:
            pass
    return valid, changed


def fbp_refresh_object_mask_binding(rig, effect_id):
    """Refresh only the shader bindings for one edited Shape Mask."""
    changed = False
    for node in _fbp_find_shader_effect_nodes_for_rig(rig, effect_id):
        _valid, node_changed = _fbp_sync_object_mask_helper(rig, effect_id, node, create=False)
        changed = node_changed or changed
    return changed


def fbp_object_mask_binding_issues(
    rig, effect_id, *, helper=None, mask_image=None, bounds=None
):
    """Return structural binding problems for one active editable Shape Mask.

    Supplying the helper/image contract keeps audit-only callers read-only.
    Interactive callers may omit them and use the normal discovery path.
    """
    definition = fbp_effect_definition(effect_id)
    if not bool(definition.get("object_mask_aware", False)):
        return ()
    shape = str(definition.get("object_mask_shape", "SQUARE") or "SQUARE")
    if bounds is None:
        try:
            from .object_masks import (
                find_object_mask_helper,
                object_mask_image,
                object_mask_image_bounds,
            )
            if helper is None:
                helper = find_object_mask_helper(rig, shape)
            if mask_image is None and helper is not None:
                mask_image = object_mask_image(helper)
            bounds = (
                object_mask_image_bounds(helper)
                if helper else (-1.0, 1.0, -1.0, 1.0)
            )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            helper = None
            mask_image = None
            bounds = (-1.0, 1.0, -1.0, 1.0)
    else:
        bounds = tuple(bounds)

    issues = []
    nodes = tuple(_fbp_find_shader_effect_nodes_for_rig(rig, effect_id))
    if not nodes:
        return ("active Shape Mask shader node is missing",)
    for index, node in enumerate(nodes, start=1):
        node_group = getattr(node, "node_tree", None)
        prefix = f"Shape Mask node {index}" if len(nodes) > 1 else "Shape Mask node"
        if node_group is None:
            issues.append(f"{prefix} has no node group")
            continue
        coord_nodes = _fbp_object_mask_coord_nodes(node_group)
        image_nodes = _fbp_object_mask_image_nodes(node_group)
        if not coord_nodes:
            issues.append(f"{prefix} has no tagged object-coordinate node")
        elif any(getattr(coord, "object", None) is not helper for coord in coord_nodes):
            issues.append(f"{prefix} is bound to the wrong helper object")
        if not image_nodes:
            issues.append(f"{prefix} has no tagged SDF image node")
        elif any(getattr(image_node, "image", None) is not mask_image for image_node in image_nodes):
            issues.append(f"{prefix} is bound to the wrong SDF image")
        use_socket = _fbp_node_socket(getattr(node, "inputs", ()), "Use Mask Object")
        expected_use = 1.0 if helper is not None and mask_image is not None else 0.0
        if use_socket is None:
            issues.append(f"{prefix} has no Use Mask Object input")
        elif not _fbp_effect_values_equal(
            getattr(use_socket, "default_value", None), expected_use
        ):
            issues.append(f"{prefix} has an invalid Use Mask Object state")
        for socket_name, expected in zip(
            ("Shape Min X", "Shape Max X", "Shape Min Y", "Shape Max Y"),
            bounds,
            strict=True,
        ):
            socket = _fbp_node_socket(getattr(node, "inputs", ()), socket_name)
            if socket is None:
                issues.append(f"{prefix} has no {socket_name} input")
            elif not _fbp_effect_values_equal(
                getattr(socket, "default_value", None), float(expected)
            ):
                issues.append(f"{prefix} has stale {socket_name} bounds")
    return tuple(issues)


def fbp_sync_object_mask_bindings(scene=None):
    """Repair active Shape Mask bindings after helper deletion or file load."""
    try:
        from .layers import iter_scene_fbp_rigs
        rigs = tuple(iter_scene_fbp_rigs(scene)) if scene is not None else tuple(
            obj for obj in bpy.data.objects if bool(getattr(obj, "is_fbp_control", False))
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    changed = False
    for rig in rigs:
        for effect_id in (
            FBP_EFFECT_SQUARE_MASK,
            FBP_EFFECT_CIRCLE_MASK,
            FBP_EFFECT_TRIANGLE_MASK,
        ):
            if not fbp_effect_is_active(rig, effect_id):
                continue
            changed = fbp_refresh_object_mask_binding(rig, effect_id) or changed
    # A helper deleted directly with X can leave its private image datablock
    # behind. Once every shader binding is repaired, unused tagged images are
    # safe to remove without touching any file on disk.
    try:
        for image in tuple(bpy.data.images):
            if (
                int(getattr(image, "users", 0) or 0) == 0
                and bool(image.get("fbp_is_object_mask_image", False))
            ):
                bpy.data.images.remove(image)
                changed = True
    except FBP_DATA_ERRORS:
        pass
    return changed


def fbp_schedule_object_mask_binding_sync(scene=None):
    """Coalesce helper deletion/link changes into one safe binding repair."""
    try:
        from .safe_tasks import schedule_once
        scene_name = str(getattr(scene, "name", "") or "")

        def _sync():
            target_scene = bpy.data.scenes.get(scene_name) if scene_name else getattr(bpy.context, "scene", None)
            fbp_sync_object_mask_bindings(target_scene)

        schedule_once("fbp.sync_object_mask_bindings", _sync, first_interval=0.03)
        return True
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return fbp_sync_object_mask_bindings(scene)


def fbp_sync_clipping_masks(context=None, *, collections=None):
    """Bind active Clipping Masks to the physical layer directly below them.

    ``collections`` limits reorder-driven updates to the affected collection(s),
    avoiding a complete scene-wide shader scan after every Up, Down or Reverse
    action. Load, delete and repair paths continue to call the full-scene mode.
    """
    context = context or bpy.context
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    try:
        from .layers import (
            fbp_clipping_source_map,
            fbp_immediate_layer_below_map,
            get_primary_fbp_collection,
            iter_fbp_rigs_in_collection,
            iter_scene_fbp_rigs,
        )
        if collections is None:
            collection_scope = None
        else:
            unique_collections = []
            seen_collections = set()
            for collection in tuple(collections or ()):
                if collection is None:
                    continue
                try:
                    collection_key = int(collection.as_pointer())
                except FBP_DATA_ERRORS:
                    continue
                if collection_key in seen_collections:
                    continue
                seen_collections.add(collection_key)
                unique_collections.append(collection)
            collection_scope = tuple(unique_collections)
        if collection_scope is None:
            rigs = tuple(iter_scene_fbp_rigs(scene))
        else:
            scoped_rigs = []
            seen_rigs = set()
            for collection in collection_scope:
                for rig in iter_fbp_rigs_in_collection(collection, recursive=False):
                    try:
                        key = int(rig.as_pointer())
                    except FBP_DATA_ERRORS:
                        continue
                    if key in seen_rigs or get_primary_fbp_collection(rig) != collection:
                        continue
                    seen_rigs.add(key)
                    scoped_rigs.append(rig)
            rigs = tuple(scoped_rigs)
        if collection_scope is not None and not collection_scope:
            return False

        active_rigs = []
        relation_effects = (
            (FBP_EFFECT_CLIPPING_MASK, "fbp_clipping_mask_source"),
            (FBP_EFFECT_LAYER_BLEND, "fbp_layer_blend_source"),
        )
        for rig in rigs:
            has_relation_effect = False
            for relation_effect_id, _source_property in relation_effects:
                definition = fbp_effect_definition(relation_effect_id)
                enabled_key = str(definition.get("enabled_key", "") or "")
                try:
                    enabled_hint = bool(enabled_key and rig.get(enabled_key, False))
                except FBP_DATA_ERRORS:
                    enabled_hint = False
                runtime_active = fbp_effect_is_active(rig, relation_effect_id)
                if runtime_active and enabled_key and not enabled_hint:
                    # Legacy/private groups can survive while their persistent
                    # enabled hint is missing. Repair the hint before resolving
                    # stacked clipping chains, whose source map intentionally
                    # avoids expensive shader scans.
                    try:
                        rig[enabled_key] = True
                        enabled_hint = True
                    except FBP_DATA_ERRORS:
                        pass
                elif enabled_hint and not runtime_active:
                    # A stored enabled flag with a missing node is a recoverable
                    # partial rebuild, not a disabled effect. Restore the small
                    # relation group now while running in the deferred safe task.
                    try:
                        fbp_apply_shader_effect(
                            rig, relation_effect_id, rebuild=True, sync_items=False
                        )
                        runtime_active = fbp_effect_is_active(rig, relation_effect_id)
                    except FBP_DATA_ERRORS:
                        runtime_active = False
                if enabled_hint or runtime_active:
                    has_relation_effect = True
                else:
                    try:
                        if getattr(rig, _source_property, None) is not None:
                            has_relation_effect = True
                    except FBP_DATA_ERRORS:
                        pass
            if has_relation_effect:
                active_rigs.append(rig)
        if not active_rigs:
            return False
        clipping_source_map = fbp_clipping_source_map(
            context,
            rigs=rigs,
            collections=collection_scope,
        )
        blend_source_map = fbp_immediate_layer_below_map(
            context,
            rigs=rigs,
            collections=collection_scope,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    changed = False
    relation_effects = (
        (FBP_EFFECT_CLIPPING_MASK, "fbp_clipping_mask_source"),
        (FBP_EFFECT_LAYER_BLEND, "fbp_layer_blend_source"),
    )
    for rig in active_rigs:
        for relation_effect_id, source_property in relation_effects:
            projection_migrated = False
            if relation_effect_id == FBP_EFFECT_CLIPPING_MASK:
                try:
                    projection_version = int(rig.get("fbp_clipping_projection_version", 0) or 0)
                except FBP_DATA_ERRORS:
                    projection_version = 0
                if projection_version < 3:
                    try:
                        imported_clipping = bool(rig.get("fbp_layered_source_is_clipping", False))
                    except FBP_DATA_ERRORS:
                        imported_clipping = False
                    projection_migrated = fbp_set_rna_property_silent(
                        rig,
                        "fbp_clipping_mask_use_source_transform",
                        not imported_clipping,
                    )
                    projection_migrated = fbp_set_rna_property_silent(
                        rig,
                        "fbp_clipping_mask_use_camera_projection",
                        not imported_clipping,
                    ) or projection_migrated
                    try:
                        rig["fbp_clipping_projection_version"] = 3
                    except FBP_DATA_ERRORS:
                        pass
            source = (
                clipping_source_map.get(rig)
                if relation_effect_id == FBP_EFFECT_CLIPPING_MASK
                else blend_source_map.get(rig)
            )
            if not fbp_effect_is_active(rig, relation_effect_id):
                # Disabled relations must not retain an apparently live source
                # pointer. Clearing it also prevents stale source references from
                # being serialized and later mistaken for an active chain.
                try:
                    if getattr(rig, source_property, None) is not None:
                        changed = bool(
                            fbp_set_rna_property_silent(rig, source_property, None)
                        ) or changed
                except FBP_DATA_ERRORS:
                    pass
                continue
            try:
                current_source = getattr(rig, source_property, None)
                pointer_changed = bool(
                    current_source is not source
                    and fbp_set_rna_property_silent(rig, source_property, source)
                )
            except FBP_DATA_ERRORS:
                pointer_changed = False
            if pointer_changed:
                changed = True
            relation_nodes = list(
                _fbp_find_shader_effect_nodes_for_rig(rig, relation_effect_id)
            )
            if relation_effect_id == FBP_EFFECT_CLIPPING_MASK:
                needs_rebuild = not relation_nodes
                if not needs_rebuild:
                    for relation_node in relation_nodes:
                        try:
                            relation_group = getattr(relation_node, "node_tree", None)
                            if int(relation_group.get("fbp_track_matte_contract_version", 0) or 0) < 8:
                                needs_rebuild = True
                                break
                        except FBP_DATA_ERRORS:
                            needs_rebuild = True
                            break
                if needs_rebuild:
                    fbp_apply_shader_effect(
                        rig,
                        relation_effect_id,
                        rebuild=True,
                        sync_items=False,
                    )
                    relation_nodes = list(
                        _fbp_find_shader_effect_nodes_for_rig(rig, relation_effect_id)
                    )
                    changed = True
            for node in relation_nodes:
                _has_source, node_changed = _fbp_sync_mask_source(rig, relation_effect_id, node)
                if projection_migrated:
                    node_changed = _fbp_set_shader_node_values(
                        rig,
                        relation_effect_id,
                        node,
                        property_names={"fbp_clipping_mask_use_source_transform", "fbp_clipping_mask_use_camera_projection"},
                    ) or node_changed
                if relation_effect_id == FBP_EFFECT_LAYER_BLEND:
                    node_changed = _fbp_sync_layer_blend_mode(rig, node) or node_changed
                changed = node_changed or changed
    return changed


def fbp_layer_relation_status(rig, effect_id):
    """Return a read-only health summary for Layer Blend or Clipping Mask.

    The draw path deliberately avoids rebuilding data or resolving the complete
    collection order. It only validates the persistent relation contract that
    should already have been produced by the deferred synchronizer.
    """
    effect_id = str(effect_id or "").upper()
    if effect_id not in {FBP_EFFECT_CLIPPING_MASK, FBP_EFFECT_LAYER_BLEND}:
        return "UNSUPPORTED", "Unsupported layer relation", "ERROR"
    if rig is None:
        return "INVALID_TARGET", "Layer is no longer available", "ERROR"

    definition = fbp_effect_definition(effect_id)
    enabled_key = str(definition.get("enabled_key", "") or "")
    source_property = str(definition.get("mask_source_property", "") or "")
    try:
        enabled_hint = bool(enabled_key and rig.get(enabled_key, False))
    except FBP_DATA_ERRORS:
        enabled_hint = False
    try:
        runtime_active = bool(fbp_effect_is_active(rig, effect_id))
    except FBP_DATA_ERRORS:
        runtime_active = False
    if not enabled_hint and not runtime_active:
        return "DISABLED", "Relation is disabled", "HIDE_ON"

    try:
        source = getattr(rig, source_property, None) if source_property else None
    except FBP_DATA_ERRORS:
        source = None
    if source is None:
        return "MISSING_SOURCE", "Source layer is missing or still pending", "ERROR"
    if source is rig:
        return "SELF_SOURCE", "Layer cannot use itself as the relation source", "ERROR"

    try:
        from .layers import (
            fbp_layer_has_sampleable_image,
            get_primary_fbp_collection,
            is_fbp_layer_object,
        )
        if not is_fbp_layer_object(source):
            return "INVALID_SOURCE", "Source is not a Frame By Plane layer", "ERROR"
        target_collection = get_primary_fbp_collection(rig)
        source_collection = get_primary_fbp_collection(source)
        if target_collection is None or source_collection is None or target_collection is not source_collection:
            return "WRONG_COLLECTION", "Source no longer belongs to the same layer collection", "ERROR"
        if not fbp_layer_has_sampleable_image(source):
            return "UNSAMPLEABLE", "Source layer has no sampleable image alpha", "ERROR"
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return "INVALID_SOURCE", "Source layer could not be validated", "ERROR"

    nodes = tuple(_fbp_find_shader_effect_nodes_for_rig(rig, effect_id))
    if not nodes:
        return "MISSING_NODE", "Relation shader node is missing", "ERROR"
    if effect_id == FBP_EFFECT_CLIPPING_MASK:
        required_contract = int(definition.get("track_matte_contract_version", 0) or 0)
        for node in nodes:
            try:
                group = getattr(node, "node_tree", None)
                current_contract = int(group.get("fbp_track_matte_contract_version", 0) or 0) if group else 0
                if group is None or current_contract < required_contract:
                    return "OUTDATED_NODE", "Clipping shader contract needs repair", "FILE_REFRESH"
            except FBP_DATA_ERRORS:
                return "OUTDATED_NODE", "Clipping shader contract needs repair", "FILE_REFRESH"

    source_name = str(getattr(source, "name", "Source Layer") or "Source Layer")
    return "OK", f"Relation ready — source: {source_name}", "CHECKMARK"

def fbp_schedule_clipping_mask_sync(scene=None, *, collections=None):
    """Coalesce Layer Blend and Clipping Mask source refreshes safely.

    Calls that know which collection changed merge into one scoped refresh.
    Passing ``collections=None`` requests a full active-scene refresh, which is
    required after camera transforms because every collection's depth order may
    change. Pending scopes are stored separately per Scene so rapid edits in two
    scenes cannot silently replace one another.
    """
    try:
        from .safe_tasks import schedule_once
        scene = scene or getattr(bpy.context, "scene", None)
        scene_name = str(getattr(scene, "name", "") or "")
        scene_runtime_key = fbp_obj_runtime_key(scene)
        pending_key = f"{scene_name}:{scene_runtime_key}" if scene_runtime_key is not None else (scene_name or "__ACTIVE_SCENE__")

        record = _FBP_RELATION_SYNC_PENDING.get(pending_key)
        if not isinstance(record, dict):
            record = {"full": False, "collections": set()}
            _FBP_RELATION_SYNC_PENDING[pending_key] = record
        if collections is None:
            record["full"] = True
            record["collections"] = set()
        elif not bool(record.get("full", False)):
            names = record.setdefault("collections", set())
            if not isinstance(names, set):
                names = set()
                record["collections"] = names
            for collection in tuple(collections or ()):
                try:
                    name = str(getattr(collection, "name", "") or "")
                except FBP_DATA_ERRORS:
                    name = ""
                if name:
                    names.add(name)

        def _sync():
            requested = _FBP_RELATION_SYNC_PENDING.pop(pending_key, None)
            if not isinstance(requested, dict):
                return None
            target_scene = (
                bpy.data.scenes.get(scene_name)
                if scene_name else getattr(bpy.context, "scene", None)
            )
            if target_scene is None and scene_runtime_key is not None:
                try:
                    target_scene = next(
                        candidate for candidate in bpy.data.scenes
                        if fbp_obj_runtime_key(candidate) == scene_runtime_key
                    )
                except (StopIteration, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    target_scene = None
            context = bpy.context
            if target_scene is None or getattr(context, "scene", None) is not target_scene:
                return None
            if bool(requested.get("full", False)):
                fbp_sync_clipping_masks(context)
                return None
            requested_names = requested.get("collections", set())
            if not isinstance(requested_names, (set, tuple, list)):
                requested_names = ()
            resolved = tuple(
                collection
                for name in sorted(requested_names)
                for collection in (bpy.data.collections.get(name),)
                if collection is not None
            )
            if resolved:
                fbp_sync_clipping_masks(context, collections=resolved)
            elif requested_names:
                # A collection may have been renamed between the depsgraph
                # update and this safe timer. Fall back to a full refresh rather
                # than leaving one relation bound to a stale source.
                fbp_sync_clipping_masks(context)
            return None

        task_name = f"fbp.sync_layer_relations:{pending_key}"
        schedule_once(task_name, _sync, first_interval=0.03)
        return True
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return fbp_sync_clipping_masks(bpy.context, collections=collections)


def fbp_sync_mattes_for_source_bounds(source_rig, scene=None):
    """Immediately refresh spatial track mattes after Crop / Extend changes."""
    if not source_rig:
        return False
    try:
        from .layers import iter_scene_fbp_rigs
        rigs = tuple(iter_scene_fbp_rigs(scene)) if scene is not None else tuple(
            obj for obj in bpy.data.objects if bool(getattr(obj, "is_fbp_control", False))
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        rigs = ()
    changed = False
    contracts = (
        (FBP_EFFECT_ALPHA_MATTE, "fbp_alpha_matte_source", "fbp_alpha_matte_use_source_transform"),
        (FBP_EFFECT_LUMA_MATTE, "fbp_luma_matte_source", "fbp_luma_matte_use_source_transform"),
        (FBP_EFFECT_CLIPPING_MASK, "fbp_clipping_mask_source", "fbp_clipping_mask_use_source_transform"),
    )
    for target in rigs:
        for effect_id, source_prop, transform_prop in contracts:
            try:
                if getattr(target, source_prop, None) is not source_rig:
                    continue
                follows_source = bool(getattr(target, transform_prop, False))
                if effect_id == FBP_EFFECT_CLIPPING_MASK:
                    follows_source = follows_source or bool(
                        getattr(target, "fbp_clipping_mask_use_camera_projection", True)
                    )
                if not follows_source:
                    continue
                for node in _fbp_find_shader_effect_nodes_for_rig(target, effect_id):
                    _has_source, node_changed = _fbp_sync_mask_source(target, effect_id, node)
                    changed = node_changed or changed
            except FBP_DATA_ERRORS:
                continue
    return changed


def _fbp_sync_shader_image_sources(
    rig,
    active_effect_ids=None,
    target_nodes=None,
    scene=None,
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
            definition = fbp_effect_definition(_effect_id)
            if bool(definition.get("mask_source_aware", False)):
                _has_image, source_changed = _fbp_sync_mask_source(
                    rig, _effect_id, node
                )
            else:
                has_image, source_changed = _fbp_sync_private_shader_source(
                    material, getattr(node, "node_tree", None)
                )
                use_image = _fbp_node_socket(getattr(node, "inputs", ()), "Use Image Sample")
                if use_image is not None:
                    desired = 1.0 if has_image else 0.0
                    if not _fbp_effect_values_equal(getattr(use_image, "default_value", None), desired):
                        use_image.default_value = desired
                        source_changed = True
            if bool(definition.get("uses_source_texel", False)):
                source_changed = _fbp_sync_source_texel_inputs(
                    rig, node, material=material
                ) or source_changed
            if _effect_id == FBP_EFFECT_DEPTH_BLUR:
                source_changed = _fbp_sync_depth_blur_runtime_inputs(
                    rig, node, material=material, scene=scene
                ) or source_changed
            changed = source_changed or changed
        except FBP_DATA_ERRORS:
            continue
    return changed


def _fbp_owned_shader_group(rig, material, effect_id, source_group, current=None):
    """Return a stable private shader group for image- or rig-owned state.

    Image-aware effects remain material-private. Effects exposing editable node
    widgets such as Color Ramps are rig-private, so every material belonging to
    one animated layer shares the same user-edited ramp without leaking it to
    another layer.
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

    rig_private = bool(definition.get("rig_private_group", False))
    owner_object = rig if rig_private else material
    owner = str(getattr(owner_object, "name_full", getattr(owner_object, "name", "")) or "")
    owner_kind = "RIG" if rig_private else "MATERIAL"
    asset_id = str(definition.get("asset_id", "") or "")

    def matches(candidate):
        if not candidate:
            return False
        try:
            stored_owner = str(
                candidate.get("fbp_effect_private_owner", "")
                or candidate.get("fbp_effect_material_owner", "")
                or ""
            )
            stored_kind = str(candidate.get("fbp_effect_private_owner_kind", "") or "")
            return (
                bool(candidate.get("fbp_private_effect_group", False))
                and fbp_normalize_effect_id(candidate.get("fbp_effect_id", "")) == effect_id
                and str(candidate.get("fbp_effect_asset_id", "") or "") == asset_id
                and stored_owner == owner
                and (not stored_kind or stored_kind == owner_kind)
                and _builtin_group_is_complete(candidate, definition)
            )
        except FBP_DATA_ERRORS:
            return False

    if matches(current):
        return current
    if rig_private:
        for candidate in bpy.data.node_groups:
            if matches(candidate):
                return candidate
    try:
        private = source_group.copy()
        private.name = f"{source_group.name} • {owner}"
        private.use_fake_user = False
        private["fbp_private_effect_group"] = True
        private["fbp_effect_id"] = effect_id
        private["fbp_effect_asset_id"] = asset_id
        private["fbp_effect_schema_version"] = FBP_EFFECT_SCHEMA_VERSION
        private["fbp_effect_private_owner"] = owner
        private["fbp_effect_private_owner_kind"] = owner_kind
        # Preserve the legacy key for old cleanup/migration code.
        private["fbp_effect_material_owner"] = owner
        return private
    except FBP_DATA_ERRORS as exc:
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
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            pass

    previous_group = getattr(node, "node_tree", None)
    if previous_group != node_group:
        try:
            node.node_tree = node_group
            changed = True
        except FBP_DATA_ERRORS:
            pass
    try:
        node.label = str(definition.get("label", effect_id))
        node["fbp_shader_effect_id"] = effect_id
        ensure_effect_instance_id(node, effect_id)
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS as exc:
                fbp_warn("Could not add shader effect node", exc)
                continue
        try:
            muted = not _fbp_stored_effect_visibility(rig, effect_id, True)
            if bool(getattr(node, "mute", False)) != muted:
                node.mute = muted
                changed = True
        except FBP_DATA_ERRORS:
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
    stored_group = _fbp_stored_effect_group_id(rig, effect_id)
    if stored_group:
        fbp_set_effect_group_id(rig, effect_id, stored_group)
    _fbp_invalidate_effect_ids_cache(rig)
    if sync_items:
        fbp_sync_effect_items(rig)
    return changed or bool(materials)


def fbp_remove_shader_effect(rig, effect_id, *, sync_items=True):
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
            except FBP_DATA_ERRORS:
                pass
        for node_group in removed_groups:
            try:
                if node_group and bool(node_group.get("fbp_private_effect_group", False)):
                    _fbp_remove_unused_effect_group(node_group)
            except FBP_DATA_ERRORS:
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
    if removed or cleaned:
        _fbp_invalidate_effect_ids_cache(rig)
    if sync_items:
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
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            return None
    value = 1.0
    try:
        color = tuple(material.get("fbp_color_value", (1.0, 1.0, 1.0, 1.0)))
        value = float(color[3]) if len(color) > 3 else 1.0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        pass
    try:
        alpha.outputs[0].default_value = value
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            pass
    if keep:
        try:
            keep.name = "FBP_Opacity"
            keep.label = "Layer Opacity"
            keep["fbp_internal_opacity_node"] = True
        except FBP_DATA_ERRORS:
            pass
    return keep, changed


def fbp_sync_layer_opacity_effect(rig, opacity=None):
    """Update one alpha Multiply node and remove it completely at 100%."""
    if not rig:
        return False
    try:
        opacity = float(getattr(rig, "fbp_opacity", 1.0) if opacity is None else opacity)
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
                except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
                continue

    if changed:
        _FBP_EFFECT_HEALTH_CACHE.clear()
        try:
            plane.update_tag()
        except FBP_DATA_ERRORS:
            pass
    return changed


def fbp_effect_is_active(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") == "BASE":
        if effect_id == FBP_EFFECT_CAMERA_BILLBOARD:
            return bool(_fbp_is_enabled(rig, effect_id) and _fbp_track_to_camera_constraint(rig))
        if effect_id == FBP_EFFECT_LATTICE:
            plane = _fbp_plane(rig)
            # Keep corrupted or partially migrated cages visible in the Mesh
            # stack so the user can inspect, rebuild or remove them. Requiring a
            # perfect helper/modifier pair made the row disappear exactly when
            # recovery controls were needed most.
            return bool(
                _fbp_is_enabled(rig, effect_id)
                or _fbp_lattice_object(rig)
                or _fbp_lattice_modifier(plane)
            )
        if _fbp_is_enabled(rig, effect_id):
            return True
        properties = tuple(definition.get("property_map", {}))
        for prop_name in properties:
            if prop_name == "fbp_extend_mode":
                continue
            try:
                if abs(float(getattr(rig, prop_name, 0.0) or 0.0)) > 1e-6:
                    return True
            except FBP_DATA_ERRORS:
                continue
        return False
    if definition.get("kind") == "GEOMETRY":
        return fbp_find_effect_modifier(rig, effect_id) is not None
    if definition.get("kind") == "SHADER":
        return bool(_fbp_find_shader_effect_nodes_for_rig(rig, effect_id))
    return False


def _fbp_effect_ids_cache_key(rig):
    """Return a cache key resilient to rename, deletion and pointer reuse."""
    try:
        identity = fbp_obj_runtime_key(rig)
        name = str(getattr(rig, "name_full", getattr(rig, "name", "")) or "")
        return (identity, name) if identity is not None else (0, "")
    except FBP_DATA_ERRORS:
        return (0, "")


def _fbp_invalidate_effect_runtime_profile(rig=None):
    """Drop cached per-frame targets without retaining stale RNA references."""
    if rig is None:
        _FBP_EFFECT_RUNTIME_PROFILE_CACHE.clear()
        _FBP_EFFECT_EVOLVE_STEP_CACHE.clear()
        return
    key = _fbp_effect_ids_cache_key(rig)
    if key and key[0]:
        _FBP_EFFECT_RUNTIME_PROFILE_CACHE.pop(key, None)
        _FBP_EFFECT_EVOLVE_STEP_CACHE.pop(key, None)


def _fbp_invalidate_effect_ids_cache(rig=None):
    """Invalidate cached stack presence/order after a structural mutation."""
    if rig is None:
        _FBP_EFFECT_IDS_CACHE.clear()
        _FBP_EFFECT_IDS_CACHE_TIME.clear()
        _FBP_EFFECT_RUNTIME_PROFILE_CACHE.clear()
        _FBP_EFFECT_EVOLVE_STEP_CACHE.clear()
        _FBP_EFFECT_SCENE_RIG_CACHE.clear()
        return
    key = _fbp_effect_ids_cache_key(rig)
    if key and key[0]:
        _FBP_EFFECT_IDS_CACHE.pop(key, None)
        _FBP_EFFECT_IDS_CACHE_TIME.pop(key, None)
        _FBP_EFFECT_RUNTIME_PROFILE_CACHE.pop(key, None)
        _FBP_EFFECT_EVOLVE_STEP_CACHE.pop(key, None)
    _FBP_EFFECT_SCENE_RIG_CACHE.clear()


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
    except FBP_DATA_ERRORS:
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
            fbp_obj_runtime_key(scene),
            str(getattr(scene, "name_full", getattr(scene, "name", "")) or ""),
        )
        object_count = len(scene.objects)
        layer_count = len(getattr(scene, "fbp_layers", ()) or ())
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
        animation_data = getattr(rig, "animation_data", None)
        action = getattr(animation_data, "action", None) if animation_data else None
        slot = getattr(animation_data, "action_slot", None) if animation_data else None
        curves = fbp_action_fcurves(rig) if action and slot else None
        animation_key = (
            int(action.as_pointer()) if action else 0,
            int(slot.as_pointer()) if slot and hasattr(slot, "as_pointer") else 0,
            len(curves) if curves is not None else 0,
        )
    except FBP_DATA_ERRORS:
        animation_key = (0, 0, 0)
    try:
        plane_key = (
            int(plane.as_pointer()) if plane else 0,
            str(getattr(plane, "name_full", getattr(plane, "name", "")) or "") if plane else "",
        )
    except FBP_DATA_ERRORS:
        plane_key = (0, "")
    cached = _FBP_EFFECT_RUNTIME_PROFILE_CACHE.get(key)
    if (
        cached is not None
        and cached.get("effect_ids") == effect_ids
        and cached.get("plane_key") == plane_key
        and cached.get("animation_key") == animation_key
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
        except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
        animated_effect_properties.clear()
    animated_effect_properties = {
        effect_id: frozenset(property_names)
        for effect_id, property_names in animated_effect_properties.items()
    }

    profile = {
        "effect_ids": effect_ids,
        "active_ids": active_ids,
        "plane_key": plane_key,
        "animation_key": animation_key,
        "built_at": time.monotonic(),
        "geometry_source_sync": bool(
            active_ids.intersection(FBP_FRAME_SYNC_GEOMETRY_EFFECT_IDS)
            and _fbp_geometry_source_requires_frame_sync(rig)
        ),
        "shader_source_sync": bool(
            active_ids.intersection(FBP_FRAME_SYNC_SHADER_EFFECT_IDS)
            and _fbp_shader_source_requires_frame_sync(rig, active_ids)
        ),
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


def fbp_effect_runtime_diagnostics(scene=None):
    """Return lightweight counters for the Effects performance profiler."""
    scene = scene or getattr(bpy.context, "scene", None)
    rigs = tuple(_fbp_scene_effect_runtime_rigs(scene)) if scene is not None else ()
    result = {
        "effect_rigs": len(rigs),
        "geometry_source_sync_rigs": 0,
        "shader_source_sync_rigs": 0,
        "animated_effects": 0,
        "evolve_effects": 0,
        "profile_cache_entries": len(_FBP_EFFECT_RUNTIME_PROFILE_CACHE),
        "step_cache_entries": len(_FBP_EFFECT_EVOLVE_STEP_CACHE),
        "handler_runs": int(_FBP_EFFECT_RUNTIME_STATS.get("handler_runs", 0) or 0),
        "rig_updates": int(_FBP_EFFECT_RUNTIME_STATS.get("rig_updates", 0) or 0),
        "held_step_skips": int(_FBP_EFFECT_RUNTIME_STATS.get("held_step_skips", 0) or 0),
    }
    for rig in rigs:
        try:
            profile = _fbp_effect_runtime_profile(rig)
            result["geometry_source_sync_rigs"] += int(
                bool(profile.get("geometry_source_sync", False))
            )
            result["shader_source_sync_rigs"] += int(
                bool(profile.get("shader_source_sync", False))
            )
            result["animated_effects"] += len(
                profile.get("animated_effect_properties", {}) or {}
            )
            result["evolve_effects"] += sum(
                1
                for effect_id, property_key in (profile.get("evolve_pairs", ()) or ())
                if bool(getattr(rig, property_key, False))
                and _fbp_effect_evolution_is_visible(rig, effect_id)
            )
        except FBP_DATA_ERRORS:
            continue
    result["profile_cache_entries"] = len(_FBP_EFFECT_RUNTIME_PROFILE_CACHE)
    result["step_cache_entries"] = len(_FBP_EFFECT_EVOLVE_STEP_CACHE)
    return result


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

    # BASE effects exist in both Image and Mesh categories. Older builds only
    # enumerated the Image BASE order, so Lattice and camera layout effects could
    # be active in Blender while remaining absent from the Mesh stack and thus
    # impossible to select or remove from the Effects UI.
    base_effect_order = tuple(FBP_BASE_EFFECT_MENU_ORDER) + tuple(
        effect_id for effect_id in FBP_3D_EFFECT_MENU_ORDER
        if fbp_effect_definition(effect_id).get("kind") == "BASE"
    )
    for effect_id in base_effect_order:
        if fbp_effect_is_active(rig, effect_id):
            append_once(effect_id)

    try:
        for modifier in plane.modifiers:
            append_once(_fbp_geometry_effect_id_for_modifier(modifier))
    except FBP_DATA_ERRORS:
        pass

    for material in _fbp_plane_materials(rig):
        tagged_nodes = _fbp_shader_effect_nodes(material)
        tagged_ids = {_fbp_shader_effect_id(node) for node in tagged_nodes}
        for stage in ("UV", "COLOR", "MASK"):
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
    rig_cache_key = _fbp_effect_ids_cache_key(rig)
    cache_key = (
        rig_cache_key,
        FBP_EFFECT_SCHEMA_VERSION,
        FBP_LOCAL_EFFECT_MASK_WIRING_VERSION,
    )
    cacheable = bool(rig_cache_key and rig_cache_key[0])
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
                    owns_group = (
                        group.get("fbp_effect_owner", "")
                        == str(getattr(plane, "name", "") or "")
                    )
                    if bool(definition.get("requires_alpha_geometry_contract")):
                        alpha_contract = bool(
                            int(group.get("fbp_alpha_geometry_contract_version", 0) or 0) >= 1
                            and len(
                                [
                                    node for node in group.nodes
                                    if bool(node.get("fbp_alpha_image_node", False))
                                ]
                            ) == 1
                        )
                    else:
                        alpha_contract = bool(
                            int(group.get("fbp_alpha_mask_patch_version", 0) or 0)
                            >= FBP_ALPHA_MASK_PATCH_VERSION
                        )
                    healthy = bool(owns_group and alpha_contract)
                except FBP_DATA_ERRORS:
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

    if _fbp_mask_target_map(rig):
        wiring_healthy = True
        for material in _fbp_plane_materials(rig):
            try:
                if int(material.get("fbp_local_effect_mask_wiring_version", 0) or 0) < FBP_LOCAL_EFFECT_MASK_WIRING_VERSION:
                    wiring_healthy = False
                    break
            except FBP_DATA_ERRORS:
                wiring_healthy = False
                break
        tokens.append(
            f"LOCAL_MASK_WIRING:{'ok' if wiring_healthy else 'broken'}"
        )
    signature = ",".join(tokens)
    if cacheable:
        if len(_FBP_EFFECT_HEALTH_CACHE) >= 512 and cache_key not in _FBP_EFFECT_HEALTH_CACHE:
            _FBP_EFFECT_HEALTH_CACHE.clear()
        _FBP_EFFECT_HEALTH_CACHE[cache_key] = (now, signature)
    return signature


def fbp_repair_effect_assets(rig, *, effect_ids=None):
    """Re-inject missing bundled groups while preserving modifiers and keyframes.

    ``effect_ids`` lets callers reuse an existing stack discovery pass. Healthy
    stacks therefore avoid a second material/modifier traversal during UI sync.
    """
    if not rig:
        return False
    changed = False
    active_ids = (
        tuple(effect_ids)
        if effect_ids is not None
        else tuple(fbp_effect_ids_for_rig(rig))
    )
    for effect_id in active_ids:
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

    # 5.5.15 repairs graphs created by the first per-effect mask releases.
    # Besides incorrect UV wiring, those graphs could preserve obsolete global
    # Alpha links after a mask was moved onto one effect. Rebuild once per
    # material and store a compact version so healthy files pay no recurring cost.
    if _fbp_mask_target_map(rig):
        for material in _fbp_plane_materials(rig):
            try:
                version = int(material.get("fbp_local_effect_mask_wiring_version", 0) or 0)
            except FBP_DATA_ERRORS:
                version = 0
            if version < FBP_LOCAL_EFFECT_MASK_WIRING_VERSION:
                changed = _fbp_rebuild_local_mask_receivers(material) or changed
    return changed


def _fbp_unique_live_rigs(rig, rigs=None):
    """Return valid rigs once, keeping active first and the remainder stable."""
    result = []
    seen = set()
    candidates = [rig]
    candidates.extend(tuple(rigs or ()))
    for candidate in candidates:
        if candidate is None:
            continue
        key = _fbp_effect_ids_cache_key(candidate)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    if len(result) <= 2:
        return result

    def _sort_key(candidate):
        try:
            name = str(
                getattr(candidate, "name_full", getattr(candidate, "name", ""))
                or ""
            )
        except FBP_DATA_ERRORS:
            name = ""
        return (name.casefold(), repr(_fbp_effect_ids_cache_key(candidate)))

    return [result[0], *sorted(result[1:], key=_sort_key)]


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
    except FBP_DATA_ERRORS:
        return ""
    claimed_by = _FBP_EFFECT_STACK_OWNER_CACHE.get(owner_id) if owner_id else None
    if force or not owner_id or (claimed_by is not None and claimed_by != rig_key):
        owner_id = fbp_unique_token_hex()
        try:
            rig[FBP_EFFECT_STACK_OWNER_KEY] = owner_id
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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


def _fbp_prepare_new_extrude(rig):
    """Apply the current defaults when Extrude is added for the first time."""
    if rig is None:
        return False
    changed = bool(
        fbp_set_rna_property_silent(rig, "fbp_thickness_grid_mode", "AUTO")
    )
    changed = bool(
        fbp_set_rna_property_silent(rig, "fbp_thickness_follow_pixelate", True)
    ) or changed
    changed = bool(
        fbp_set_rna_property_silent(rig, "fbp_thickness_safe_grid", True)
    ) or changed
    return changed


def fbp_ensure_extrude_effect_integrity(rig):
    """Keep the current Extrude modifier unique and on the latest node contract."""
    if rig is None or _fbp_plane(rig) is None:
        return False

    modifiers = _fbp_find_all_effect_modifiers(rig, FBP_EFFECT_THICKNESS)
    if not modifiers:
        return False

    changed = False
    keep = modifiers[0]
    if len(modifiers) > 1:
        _fbp_remove_duplicate_effect_modifiers(rig, FBP_EFFECT_THICKNESS, keep)
        changed = True

    current_group = getattr(keep, "node_group", None)
    stale_asset = not _fbp_group_matches(current_group, FBP_EFFECT_THICKNESS)
    if stale_asset or changed:
        changed = bool(
            fbp_update_geometry_effect(rig, FBP_EFFECT_THICKNESS, keep)
        ) or changed

    if changed:
        _fbp_invalidate_effect_runtime_profile(rig)
    return changed


def fbp_refresh_effect_instance_ids(rig, *, force=False, refresh_stack_owner=False):
    """Normalize logical effect-instance IDs for one Frame by Plane layer.

    All material copies of one shader effect share one instance ID. Geometry
    modifiers keep one ID each. Duplicated rigs receive a new stack owner and
    therefore cannot retain the source layer's persistent instance identities.
    """
    if rig is None:
        return False
    fbp_ensure_extrude_effect_integrity(rig)
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
                owner_token = f"{owner_id}:{effect_id}"
                stored_instance = _fbp_stored_effect_instance_id(rig, effect_id)
                if stored_instance and not effect_instance_id(modifier) and not force:
                    assign_effect_instance_id(
                        modifier, effect_id, stored_instance, owner_token
                    )
                changed = _fbp_assign_logical_effect_instance(
                    (modifier,), effect_id, owner_token, force=force
                ) or changed
                current_instance = str(effect_instance_id(modifier) or "")
                if current_instance:
                    changed = _fbp_store_effect_instance_id(
                        rig, effect_id, current_instance
                    ) or changed
        except FBP_DATA_ERRORS:
            pass

    shader_owners = {}
    try:
        for material in _fbp_plane_materials(rig):
            for node in _fbp_shader_effect_nodes(material):
                effect_id = _fbp_shader_effect_id(node)
                if effect_id:
                    shader_owners.setdefault(effect_id, []).append(node)
    except FBP_DATA_ERRORS:
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
            current = str(effect_instance_id(modifier) or "")
            stored = _fbp_stored_effect_instance_id(rig, effect_id)
            if not current and stored:
                if ensure:
                    current = str(assign_effect_instance_id(modifier, effect_id, stored) or "")
                else:
                    current = stored
            if ensure and not current:
                current = str(ensure_effect_instance_id(modifier, effect_id) or "")
            if current:
                _fbp_store_effect_instance_id(rig, effect_id, current)
            return current
        return _fbp_stored_effect_instance_id(rig, effect_id)
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


def _fbp_effect_instance_storage_key(effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    return f"fbp_effect_instance::{effect_id}" if effect_id else ""


def _fbp_stored_effect_instance_id(rig, effect_id):
    key = _fbp_effect_instance_storage_key(effect_id)
    if rig is None or not key:
        return ""
    try:
        return str(rig.get(key, "") or "")
    except FBP_DATA_ERRORS:
        return ""


def _fbp_store_effect_instance_id(rig, effect_id, instance_id):
    key = _fbp_effect_instance_storage_key(effect_id)
    if rig is None or not key or not instance_id:
        return False
    try:
        current = str(rig.get(key, "") or "")
        if current == str(instance_id):
            return False
        rig[key] = str(instance_id)
        return True
    except FBP_DATA_ERRORS:
        return False


def _fbp_effect_group_storage_key(effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    return f"fbp_effect_group::{effect_id}" if effect_id else ""


def _fbp_stored_effect_group_id(rig, effect_id):
    key = _fbp_effect_group_storage_key(effect_id)
    if not rig or not key:
        return ""
    try:
        return str(rig.get(key, "") or "")
    except FBP_DATA_ERRORS:
        return ""


def _fbp_store_effect_group_id(rig, effect_id, group_id):
    key = _fbp_effect_group_storage_key(effect_id)
    if not rig or not key:
        return False
    group_id = str(group_id or "")
    try:
        current = str(rig.get(key, "") or "")
        if group_id:
            if current == group_id:
                return False
            rig[key] = group_id
            return True
        if key in rig:
            del rig[key]
            return True
    except FBP_DATA_ERRORS:
        return False
    return False


def _fbp_effect_group_owners(rig, effect_id):
    """Return every concrete Blender owner representing one logical effect."""
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") == "GEOMETRY":
        modifier = fbp_find_effect_modifier(rig, effect_id)
        return [modifier] if modifier is not None else []
    if definition.get("kind") == "SHADER":
        return list(_fbp_find_shader_effect_nodes_for_rig(rig, effect_id))
    return []


def _fbp_resolve_effect_group_id(rig, effect_id, owners, *, normalize=True):
    """Resolve one logical group without reviving stale rig metadata.

    A unanimous concrete owner state wins over a conflicting rig-level cache.
    When owners disagree, the stored value remains authoritative only if it is
    still represented by at least one owner. This makes Undo and manual node
    repair self-healing instead of propagating an obsolete group identifier.
    """
    effect_id = fbp_normalize_effect_id(effect_id)
    owners = tuple(owner for owner in tuple(owners or ()) if owner is not None)
    stored = _fbp_stored_effect_group_id(rig, effect_id)
    raw_owner_ids = [effect_group_id(owner) for owner in owners]
    owner_ids = list(dict.fromkeys(item for item in raw_owner_ids if item))
    owners_unanimous = bool(
        owners
        and owner_ids
        and all(item == owner_ids[0] for item in raw_owner_ids)
    )

    if stored and stored in owner_ids:
        group_id = stored
    elif stored and not owners_unanimous:
        group_id = stored
    elif owner_ids:
        group_id = owner_ids[0]
    else:
        group_id = stored

    if normalize:
        _fbp_store_effect_group_id(rig, effect_id, group_id)
        for owner in owners:
            assign_effect_group_id(owner, group_id)
    return group_id


def fbp_effect_group_id_for_rig(rig, effect_id, *, normalize=True):
    """Return and optionally repair the group shared by all effect owners."""
    effect_id = fbp_normalize_effect_id(effect_id)
    owners = _fbp_effect_group_owners(rig, effect_id)
    return _fbp_resolve_effect_group_id(
        rig, effect_id, owners, normalize=normalize
    )


def _fbp_effect_group_record(rig, group_id):
    group_id = str(group_id or "")
    if not rig or not group_id or not hasattr(rig, "fbp_effect_groups"):
        return None
    try:
        return next(
            (item for item in rig.fbp_effect_groups
             if str(getattr(item, "group_id", "") or "") == group_id),
            None,
        )
    except FBP_DATA_ERRORS:
        return None


def _fbp_clean_effect_group_name(group_name):
    """Normalize one UI folder name before storing it in Blender RNA."""
    return " ".join(str(group_name or "").strip().split())[:64]


def _fbp_next_effect_group_name(rig):
    used = {
        _fbp_clean_effect_group_name(getattr(item, "group_name", ""))
        for item in getattr(rig, "fbp_effect_groups", ())
    } if rig else set()
    index = 1
    while f"Effect Group {index}" in used:
        index += 1
    return f"Effect Group {index}"


def fbp_ensure_effect_group_record(rig, group_id, group_name=""):
    """Ensure persistent per-rig metadata exists for one Effect Group."""
    group_id = str(group_id or "")
    if not rig or not group_id or not hasattr(rig, "fbp_effect_groups"):
        return None
    record = _fbp_effect_group_record(rig, group_id)
    clean_name = _fbp_clean_effect_group_name(group_name)
    if record is None:
        try:
            record = rig.fbp_effect_groups.add()
            record.group_id = group_id
            record.group_name = clean_name or _fbp_next_effect_group_name(rig)
        except FBP_DATA_ERRORS:
            return None
    elif clean_name and not _fbp_clean_effect_group_name(
        getattr(record, "group_name", "")
    ):
        try:
            record.group_name = clean_name
        except FBP_DATA_ERRORS:
            pass
    return record


def fbp_effect_group_name(rig, group_id):
    record = _fbp_effect_group_record(rig, group_id)
    return str(getattr(record, "group_name", "") or "") if record else ""


def fbp_effect_group_color_tag(rig, group_id):
    record = _fbp_effect_group_record(rig, group_id)
    return str(getattr(record, "color_tag", "NONE") or "NONE") if record else "NONE"


def fbp_effect_group_collapsed(rig, group_id):
    """Return the persistent UI collapse state for one Effect Group."""
    record = _fbp_effect_group_record(rig, group_id)
    return bool(getattr(record, "collapsed", False)) if record else False


def fbp_set_effect_group_name(rig, group_id, group_name):
    """Rename one existing group without changing membership or stack order."""
    group_id = str(group_id or "")
    group_name = _fbp_clean_effect_group_name(group_name)
    if not rig or not group_id or not group_name:
        return False
    record = _fbp_effect_group_record(rig, group_id)
    if record is None:
        return False
    current = str(getattr(record, "group_name", "") or "")
    if current == group_name:
        return True
    try:
        record.group_name = group_name
    except FBP_DATA_ERRORS:
        return False
    return str(getattr(record, "group_name", "") or "") == group_name


def fbp_set_effect_group_collapsed(rig, group_id, collapsed):
    """Persist a group collapse state while leaving effect data untouched."""
    record = _fbp_effect_group_record(rig, group_id)
    if record is None:
        return False
    collapsed = bool(collapsed)
    try:
        if bool(getattr(record, "collapsed", False)) == collapsed:
            return True
        record.collapsed = collapsed
    except FBP_DATA_ERRORS:
        return False
    return bool(getattr(record, "collapsed", False)) == collapsed


def fbp_set_effect_group_color_transactional(rigs, group_id, color_tag):
    """Assign one folder color to a shared Effect Group with rollback."""
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    group_id = str(group_id or "")
    color_tag = str(color_tag or "NONE")
    valid_tags = {str(item[0]) for item in COLLECTION_COLOR_ENUM_ITEMS}
    if not rigs or not group_id or color_tag not in valid_tags:
        return False
    snapshots = {}
    for rig in rigs:
        record = _fbp_effect_group_record(rig, group_id)
        if record is None or not fbp_effect_group_members(rig, group_id):
            return False
        snapshots[rig] = str(getattr(record, "color_tag", "NONE") or "NONE")
    changed = False
    written = []
    for rig in rigs:
        record = _fbp_effect_group_record(rig, group_id)
        try:
            if str(getattr(record, "color_tag", "NONE") or "NONE") != color_tag:
                record.color_tag = color_tag
                changed = True
            written.append(rig)
        except FBP_DATA_ERRORS:
            for target in written:
                target_record = _fbp_effect_group_record(target, group_id)
                if target_record is not None:
                    try:
                        target_record.color_tag = snapshots[target]
                    except FBP_DATA_ERRORS:
                        pass
            return False
    for rig in rigs:
        fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
    return changed or all(
        fbp_effect_group_color_tag(rig, group_id) == color_tag for rig in rigs
    )


def fbp_expand_effect_selection_to_groups(rig, effect_ids):
    """Expand any touched group to all of its members in stable stack order.

    Grouped effects are intentionally moved as indivisible blocks. To move one
    member independently the user must first remove it from the group.
    """
    normalized = {
        fbp_normalize_effect_id(effect_id)
        for effect_id in tuple(effect_ids or ())
        if fbp_effect_definition(effect_id).get("kind") in {"SHADER", "GEOMETRY"}
    }
    if not rig or not normalized:
        return []
    stack_ids = tuple(fbp_effect_ids_for_rig(rig))
    groups = fbp_sync_effect_groups(rig, effect_ids=stack_ids)
    group_by_effect = {
        effect_id: group_id
        for group_id, members in groups.items()
        for effect_id in members
    }
    touched_groups = {
        group_by_effect.get(effect_id, "") for effect_id in normalized
    }
    touched_groups.discard("")
    for group_id in touched_groups:
        normalized.update(groups.get(group_id, ()))
    return [effect_id for effect_id in stack_ids if effect_id in normalized]


def fbp_rename_effect_group_transactional(rigs, group_id, group_name):
    """Rename a shared group on every selected layer with rollback."""
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    group_id = str(group_id or "")
    group_name = _fbp_clean_effect_group_name(group_name)
    if not rigs or not group_id or not group_name:
        return False
    snapshots = {}
    for rig in rigs:
        record = _fbp_effect_group_record(rig, group_id)
        if record is None or not fbp_effect_group_members(rig, group_id):
            return False
        duplicate = any(
            str(getattr(item, "group_id", "") or "") != group_id
            and str(getattr(item, "group_name", "") or "").casefold() == group_name.casefold()
            for item in getattr(rig, "fbp_effect_groups", ())
        )
        if duplicate:
            return False
        snapshots[rig] = str(getattr(record, "group_name", "") or "")
    changed = []
    for rig in rigs:
        if fbp_set_effect_group_name(rig, group_id, group_name):
            changed.append(rig)
            continue
        for target in changed:
            fbp_set_effect_group_name(target, group_id, snapshots[target])
        return False
    for rig in rigs:
        fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
    return True


def fbp_set_effect_group_id(rig, effect_id, group_id, *, group_name=""):
    """Assign one logical effect to a persistent organizational group.

    The rig-level mapping and every concrete modifier or shader node are
    updated as one small transaction. If Blender rejects any owner write, the
    previous metadata is restored so the next synchronization cannot revive a
    half-applied group assignment.
    """
    effect_id = fbp_normalize_effect_id(effect_id)
    owners = _fbp_effect_group_owners(rig, effect_id)
    if not owners:
        return False
    group_id = str(group_id or "")
    old_stored = _fbp_stored_effect_group_id(rig, effect_id)
    old_owner_ids = [effect_group_id(owner) for owner in owners]
    _fbp_store_effect_group_id(rig, effect_id, group_id)
    for owner in owners:
        assign_effect_group_id(owner, group_id)

    consistent = (
        _fbp_stored_effect_group_id(rig, effect_id) == group_id
        and all(effect_group_id(owner) == group_id for owner in owners)
    )
    if not consistent:
        _fbp_store_effect_group_id(rig, effect_id, old_stored)
        for owner, old_group_id in zip(owners, old_owner_ids, strict=True):
            assign_effect_group_id(owner, old_group_id)
        return False
    if group_id and fbp_ensure_effect_group_record(
        rig, group_id, group_name
    ) is None:
        # Membership without a persistent folder row is an invalid half-state.
        # Roll back every owner so drag/drop, Undo and save/reopen cannot later
        # reinterpret this effect as belonging to a missing group.
        _fbp_store_effect_group_id(rig, effect_id, old_stored)
        for owner, old_group_id in zip(owners, old_owner_ids, strict=True):
            assign_effect_group_id(owner, old_group_id)
        return False
    # Callers use the return value as transaction success, not as a dirty flag.
    # Re-applying an already consistent assignment must therefore succeed.
    return True


def _fbp_read_effect_groups_fast(rig, effect_ids):
    """Read a healthy group layout without scanning shader/modifier owners.

    Operators and full synchronizations keep rig-owned membership mirrors in
    sync with concrete nodes/modifiers. Sidebar redraws can therefore validate
    the compact mirrors first and fall back to the repairing path only when the
    records are missing, duplicated or non-contiguous.
    """
    if not rig or not hasattr(rig, "fbp_effect_groups"):
        return {}
    records = {}
    try:
        for record in rig.fbp_effect_groups:
            group_id = str(getattr(record, "group_id", "") or "")
            if not group_id or group_id in records:
                return None
            records[group_id] = record
    except FBP_DATA_ERRORS:
        return None

    groups = {}
    for effect_id in tuple(effect_ids or ()):
        effect_id = fbp_normalize_effect_id(effect_id)
        if fbp_effect_definition(effect_id).get("kind") not in {"SHADER", "GEOMETRY"}:
            continue
        group_id = _fbp_stored_effect_group_id(rig, effect_id)
        if not group_id:
            continue
        if group_id not in records:
            return None
        groups.setdefault(group_id, []).append(effect_id)

    # Empty rows and split/overlapping blocks require the repairing path.
    if any(group_id not in groups for group_id in records):
        return None
    for _group_id, members in groups.items():
        chain_keys = {_fbp_effect_chain_key(effect_id) for effect_id in members}
        chain_keys.discard(("", ""))
        if len(chain_keys) != 1:
            return None
        order = _fbp_effect_chain_ids(rig, next(iter(chain_keys)))
        try:
            positions = [order.index(effect_id) for effect_id in members]
        except ValueError:
            return None
        if positions != list(range(min(positions), max(positions) + 1)):
            return None
    return {group_id: tuple(members) for group_id, members in groups.items()}


def fbp_sync_effect_groups(rig, effect_ids=None):
    """Repair group membership, deduplicate records and prune invalid groups."""
    if not rig or not hasattr(rig, "fbp_effect_groups"):
        return {}

    raw_effect_ids = (
        effect_ids if effect_ids is not None else fbp_effect_ids_for_rig(rig)
    )
    effect_ids = tuple(
        dict.fromkeys(
            normalized
            for normalized in (
                fbp_normalize_effect_id(effect_id)
                for effect_id in tuple(raw_effect_ids or ())
            )
            if normalized
        )
    )
    active_ids = set(effect_ids)

    try:
        for key in tuple(rig.keys()):
            key = str(key or "")
            if not key.startswith("fbp_effect_group::"):
                continue
            stored_effect = fbp_normalize_effect_id(
                key.removeprefix("fbp_effect_group::")
            )
            if stored_effect not in active_ids:
                del rig[key]
    except FBP_DATA_ERRORS:
        pass

    # Resolve each effect owner only once. Shader effects may be represented by
    # several material nodes, so repeated owner discovery was the main cost of
    # group validation on large multi-plane selections.
    groups = {}
    owners_by_effect = {}
    for effect_id in effect_ids:
        if fbp_effect_definition(effect_id).get("kind") not in {"SHADER", "GEOMETRY"}:
            continue
        owners = tuple(_fbp_effect_group_owners(rig, effect_id))
        owners_by_effect[effect_id] = owners
        group_id = _fbp_resolve_effect_group_id(
            rig, effect_id, owners, normalize=True
        )
        if not group_id:
            continue
        record = fbp_ensure_effect_group_record(rig, group_id)
        if record is None:
            # A group without its independent folder row cannot be represented
            # safely. Clear the stale membership instead of exposing a ghost
            # folder that disappears or absorbs unrelated effects on the next sync.
            _fbp_store_effect_group_id(rig, effect_id, "")
            for owner in owners:
                assign_effect_group_id(owner, "")
            continue
        groups.setdefault(group_id, []).append(effect_id)

    # A group is a contiguous block in exactly one compatible chain.  Single
    # member groups are valid: they preserve the folder identity while users
    # drag effects in or out.  When an ungrouped effect lands between two
    # members, absorb it instead of dissolving the folder.  This also repairs
    # newly-created effects inserted inside an expanded group.
    invalid_groups = set()
    chain_positions = {}
    group_by_effect = {
        effect_id: group_id
        for group_id, members in groups.items()
        for effect_id in members
    }
    for group_id, members in tuple(groups.items()):
        chain_keys = {_fbp_effect_chain_key(effect_id) for effect_id in members}
        chain_keys.discard(("", ""))
        if len(chain_keys) != 1:
            invalid_groups.add(group_id)
            continue
        chain_key = next(iter(chain_keys))
        position_map = chain_positions.get(chain_key)
        if position_map is None:
            chain_order = _fbp_effect_chain_ids(rig, chain_key)
            position_map = {
                effect_id: index for index, effect_id in enumerate(chain_order)
            }
            chain_positions[chain_key] = position_map
        positions = [
            position_map[effect_id]
            for effect_id in members
            if effect_id in position_map
        ]
        if len(positions) != len(members) or not positions:
            invalid_groups.add(group_id)
            continue
        expected = list(range(min(positions), max(positions) + 1))
        if positions == expected:
            continue

        chain_order = _fbp_effect_chain_ids(rig, chain_key)
        gap_effects = [chain_order[index] for index in expected if index < len(chain_order)]
        conflicting = [
            effect_id for effect_id in gap_effects
            if group_by_effect.get(effect_id, "") not in {"", group_id}
        ]
        if conflicting:
            # Overlapping folders cannot be represented safely.  Keep the
            # established conservative behavior only for this true conflict.
            invalid_groups.add(group_id)
            continue
        for effect_id in gap_effects:
            if group_by_effect.get(effect_id, "") == group_id:
                continue
            owners = owners_by_effect.get(effect_id)
            if owners is None:
                owners = tuple(_fbp_effect_group_owners(rig, effect_id))
                owners_by_effect[effect_id] = owners
            _fbp_store_effect_group_id(rig, effect_id, group_id)
            for owner in owners:
                assign_effect_group_id(owner, group_id)
            group_by_effect[effect_id] = group_id
        groups[group_id] = [
            effect_id for effect_id in chain_order
            if group_by_effect.get(effect_id, "") == group_id
        ]

    for group_id in invalid_groups:
        for effect_id in groups.pop(group_id, ()):
            _fbp_store_effect_group_id(rig, effect_id, "")
            for owner in owners_by_effect.get(effect_id, ()):
                assign_effect_group_id(owner, "")

    # Undo, copy/paste and old builds can leave duplicate metadata rows carrying
    # the same UUID. Merge useful display state into the first row, then remove
    # duplicates and records without live members.
    try:
        canonical = {}
        remove_indices = []
        for index, record in enumerate(rig.fbp_effect_groups):
            group_id = str(getattr(record, "group_id", "") or "")
            if not group_id or group_id not in groups:
                remove_indices.append(index)
                continue
            first = canonical.get(group_id)
            if first is None:
                clean_name = _fbp_clean_effect_group_name(
                    getattr(record, "group_name", "")
                )
                if str(getattr(record, "group_name", "") or "") != clean_name:
                    record.group_name = clean_name or _fbp_next_effect_group_name(rig)
                canonical[group_id] = record
                continue
            first_name = _fbp_clean_effect_group_name(
                getattr(first, "group_name", "")
            )
            duplicate_name = _fbp_clean_effect_group_name(
                getattr(record, "group_name", "")
            )
            if str(getattr(first, "group_name", "") or "") != first_name:
                first.group_name = first_name or _fbp_next_effect_group_name(rig)
            first_is_default = first_name.startswith("Effect Group ")
            duplicate_is_custom = bool(
                duplicate_name and not duplicate_name.startswith("Effect Group ")
            )
            if duplicate_name and (not first_name or (first_is_default and duplicate_is_custom)):
                first.group_name = duplicate_name
            if bool(getattr(record, "collapsed", False)):
                first.collapsed = True
            first_color = str(getattr(first, "color_tag", "NONE") or "NONE")
            duplicate_color = str(getattr(record, "color_tag", "NONE") or "NONE")
            if first_color == "NONE" and duplicate_color != "NONE":
                first.color_tag = duplicate_color
            remove_indices.append(index)
        for index in reversed(remove_indices):
            rig.fbp_effect_groups.remove(index)
    except FBP_DATA_ERRORS:
        pass

    return {group_id: tuple(members) for group_id, members in groups.items()}

def fbp_effect_group_members(rig, group_id, *, effect_ids=None):
    groups = fbp_sync_effect_groups(rig, effect_ids=effect_ids)
    return tuple(groups.get(str(group_id or ""), ()))


def fbp_effect_group_members_from_items(rig, group_id):
    """Read group membership from the transient UI mirror without mutation.

    UIList and popup draw callbacks must remain read-only. Structural repair is
    performed by ``fbp_sync_effect_items`` before drawing, while this helper only
    reads the already mirrored rows.
    """
    group_id = str(group_id or "")
    if not rig or not group_id or not hasattr(rig, "fbp_effects"):
        return ()
    result = []
    try:
        for item in rig.fbp_effects:
            if str(getattr(item, "group_id", "") or "") != group_id:
                continue
            effect_id = fbp_normalize_effect_id(getattr(item, "effect_id", ""))
            if effect_id:
                result.append(effect_id)
    except FBP_DATA_ERRORS:
        return ()
    return tuple(result)


def _fbp_effect_group_state_signature(rig, effect_ids=()):
    """Return a compact read-only signature for persistent group UI metadata."""
    if not rig:
        return ""
    records = {}
    try:
        records = {
            str(getattr(item, "group_id", "") or ""): (
                str(getattr(item, "group_name", "") or ""),
                bool(getattr(item, "collapsed", False)),
                str(getattr(item, "color_tag", "NONE") or "NONE"),
            )
            for item in getattr(rig, "fbp_effect_groups", ())
            if str(getattr(item, "group_id", "") or "")
        }
    except FBP_DATA_ERRORS:
        records = {}
    parts = []
    for effect_id in tuple(effect_ids or ()):
        normalized = fbp_normalize_effect_id(effect_id)
        if not normalized:
            continue
        try:
            group_id = _fbp_stored_effect_group_id(rig, normalized)
        except FBP_DATA_ERRORS:
            group_id = ""
        name, collapsed, color_tag = records.get(group_id, ("", False, "NONE"))
        parts.append((normalized, group_id, name, bool(collapsed), color_tag))
    return repr(tuple(parts))


def fbp_sync_effect_items(
    rig, rigs=None, *, repair_assets=True, normalize_instance_ids=True
):
    if rig is None or not hasattr(rig, "fbp_effects"):
        return []
    target_rigs = _fbp_unique_live_rigs(rig, rigs)
    if not target_rigs:
        return []
    # Mask-target state is invalidated by the mutations that change it. Keeping
    # the cache across ordinary UI synchronizations avoids rebuilding the same
    # target map on every sidebar redraw; Undo and direct property edits still
    # self-heal through the bounded signature check in _fbp_mask_target_map().

    # Discover healthy stacks once. Repair receives the discovered IDs and only
    # triggers another traversal when it actually replaced a missing asset.
    ids_by_key = {}
    groups_by_key = {}
    repaired_by_key = {}
    target_ids = []
    target_seen = set()
    for target_rig in target_rigs:
        target_key = _fbp_effect_ids_cache_key(target_rig)
        fast_ui_read = not repair_assets and not normalize_instance_ids
        effect_ids = tuple(
            _fbp_runtime_effect_ids(target_rig)
            if fast_ui_read else fbp_effect_ids_for_rig(target_rig)
        )
        repaired = False
        if repair_assets:
            health_before = fbp_effect_asset_health_signature(
                target_rig, force=False, effect_ids=effect_ids
            )
            if "broken" in health_before:
                repaired = bool(
                    fbp_repair_effect_assets(target_rig, effect_ids=effect_ids)
                )
        if normalize_instance_ids:
            fbp_refresh_effect_instance_ids(target_rig)
        if repaired:
            effect_ids = tuple(fbp_effect_ids_for_rig(target_rig))
        ids_by_key[target_key] = effect_ids
        repaired_by_key[target_key] = repaired
        fast_groups = (
            _fbp_read_effect_groups_fast(target_rig, effect_ids)
            if fast_ui_read else None
        )
        groups_by_key[target_key] = (
            fast_groups
            if fast_groups is not None
            else fbp_sync_effect_groups(target_rig, effect_ids=effect_ids)
        )
        for effect_id in effect_ids:
            if effect_id in target_seen:
                continue
            target_seen.add(effect_id)
            target_ids.append(effect_id)

    names = []
    health = []
    group_signatures = []
    for target_rig in target_rigs:
        target_key = _fbp_effect_ids_cache_key(target_rig)
        effect_ids = ids_by_key.get(target_key, ())
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
            health.append(
                fbp_effect_asset_health_signature(
                    target_rig,
                    force=bool(repaired_by_key.get(target_key, False)),
                    effect_ids=effect_ids,
                )
                if repair_assets else "runtime"
            )
            group_signatures.append(
                _fbp_effect_group_state_signature(target_rig, effect_ids)
            )
        except FBP_DATA_ERRORS:
            names.append("")
            health.append("broken" if repair_assets else "runtime")
            group_signatures.append("")
    signature = repr(
        (
            tuple(target_ids),
            tuple(names),
            tuple(health),
            tuple(group_signatures),
            int(_FBP_EFFECT_UI_EPOCH),
        )
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
            except FBP_DATA_ERRORS:
                pass

    try:
        active_index = int(getattr(rig, "fbp_effects_index", 0) or 0)
        active_token = ("EFFECT", "")
        if 0 <= active_index < len(rig.fbp_effects):
            active_item = rig.fbp_effects[active_index]
            active_type = str(getattr(active_item, "row_type", "EFFECT") or "EFFECT")
            active_value = (
                str(getattr(active_item, "group_id", "") or "")
                if active_type == "GROUP"
                else fbp_normalize_effect_id(getattr(active_item, "effect_id", ""))
            )
            active_token = (active_type, active_value)
        selected_ids = {
            effect_id
            for effect_id in (
                fbp_normalize_effect_id(getattr(item, "effect_id", ""))
                for item in rig.fbp_effects
                if (
                    str(getattr(item, "row_type", "EFFECT") or "EFFECT") == "EFFECT"
                    and bool(getattr(item, "is_selected", False))
                )
            )
            if effect_id
        }

        active_groups = groups_by_key.get(_fbp_effect_ids_cache_key(rig), {})
        group_by_effect = {
            effect_id: group_id
            for group_id, members in active_groups.items()
            for effect_id in members
        }
        group_member_counts = {
            group_id: len(members) for group_id, members in active_groups.items()
        }
        group_records = {
            str(getattr(record, "group_id", "") or ""): (
                str(getattr(record, "group_name", "") or ""),
                bool(getattr(record, "collapsed", False)),
            )
            for record in getattr(rig, "fbp_effect_groups", ())
            if str(getattr(record, "group_id", "") or "")
        }

        # A folder is a real UI row that owns no effect. Member effects follow
        # it as independent rows, so the first effect is never overloaded as
        # the folder header and groups remain stable with a single member.
        target_rows = []
        emitted_groups = set()
        for effect_id in target_ids:
            group_id = str(group_by_effect.get(effect_id, "") or "")
            if group_id and group_id not in emitted_groups:
                group_name, collapsed = group_records.get(group_id, ("Effect Group", False))
                target_rows.append((
                    "GROUP", "", group_id, group_name or "Effect Group",
                    bool(collapsed), int(group_member_counts.get(group_id, 0)),
                ))
                emitted_groups.add(group_id)
            group_name, collapsed = group_records.get(group_id, ("", False))
            target_rows.append((
                "EFFECT", effect_id, group_id, group_name, bool(collapsed),
                int(group_member_counts.get(group_id, 0)),
            ))

        current_rows = tuple(
            (
                str(getattr(item, "row_type", "EFFECT") or "EFFECT"),
                str(getattr(item, "effect_id", "") or ""),
                str(getattr(item, "group_id", "") or ""),
            )
            for item in rig.fbp_effects
        )
        desired_rows = tuple((row_type, effect_id, group_id) for row_type, effect_id, group_id, _name, _collapsed, _count in target_rows)
        if current_rows != desired_rows:
            rig.fbp_effects.clear()
            for row_type, effect_id, group_id, group_name, collapsed, member_count in target_rows:
                item = rig.fbp_effects.add()
                item.row_type = row_type
                item.effect_id = effect_id
                item.group_id = group_id
                item.group_name = group_name
                item.group_is_first = row_type == "GROUP"
                item.group_collapsed = collapsed
                item.group_member_count = member_count
                if row_type == "GROUP":
                    item.label = group_name or "Effect Group"
                    item.instance_id = ""
                    item.is_selected = False
                else:
                    item.instance_id = fbp_effect_instance_id_for_rig(
                        rig, effect_id, ensure=normalize_instance_ids
                    )
                    item.label = _fbp_effect_display_label(
                        effect_id, fbp_effect_definition(effect_id)
                    )
                    item.is_selected = effect_id in selected_ids
        else:
            for item, row_data in zip(rig.fbp_effects, target_rows, strict=True):
                row_type, effect_id, group_id, group_name, collapsed, member_count = row_data
                item.row_type = row_type
                item.group_id = group_id
                item.group_name = group_name
                item.group_is_first = row_type == "GROUP"
                item.group_collapsed = collapsed
                item.group_member_count = member_count
                if row_type == "GROUP":
                    item.label = group_name or "Effect Group"
                    item.effect_id = ""
                    item.instance_id = ""
                elif normalize_instance_ids:
                    expected_instance = fbp_effect_instance_id_for_rig(rig, effect_id)
                    if str(getattr(item, "instance_id", "") or "") != expected_instance:
                        item.instance_id = expected_instance

        if target_rows:
            index_by_token = {
                ((row_type, group_id) if row_type == "GROUP" else (row_type, effect_id)): index
                for index, (row_type, effect_id, group_id, _name, _collapsed, _count) in enumerate(target_rows)
            }
            next_index = index_by_token.get(
                active_token, min(active_index, len(target_rows) - 1)
            )
        else:
            next_index = 0
        if int(getattr(rig, "fbp_effects_index", 0) or 0) != next_index:
            rig.fbp_effects_index = next_index
        if (
            hasattr(rig, "fbp_effects_signature")
            and str(getattr(rig, "fbp_effects_signature", "") or "") != signature
        ):
            rig.fbp_effects_signature = signature
    except FBP_DATA_ERRORS:
        return []
    return target_ids


def fbp_schedule_effect_items_sync(rig, rigs=None):
    if rig is None or not hasattr(rig, "fbp_effects"):
        return []
    target_rigs = _fbp_unique_live_rigs(rig, rigs)
    if not target_rigs:
        return []
    target_ids = []
    target_seen = set()
    rig_names = []
    group_signatures = []
    for target_rig in target_rigs:
        try:
            rig_names.append(
                str(
                    getattr(
                        target_rig,
                        "name_full",
                        getattr(target_rig, "name", ""),
                    )
                    or ""
                )
            )
        except FBP_DATA_ERRORS:
            rig_names.append("")
        runtime_ids = tuple(_fbp_runtime_effect_ids(target_rig))
        group_signatures.append(
            _fbp_effect_group_state_signature(target_rig, runtime_ids)
        )
        for effect_id in runtime_ids:
            if effect_id in target_seen:
                continue
            target_seen.add(effect_id)
            target_ids.append(effect_id)
    # Build the UI-only signature from the same cached discovery pass instead
    # of walking every selected stack a second time.
    signature = repr(
        (
            tuple(target_ids),
            tuple(rig_names),
            tuple("runtime" for _item in target_rigs),
            tuple(group_signatures),
            int(_FBP_EFFECT_UI_EPOCH),
        )
    )
    try:
        current_ids = tuple(
            str(getattr(item, "effect_id", "") or "")
            for item in rig.fbp_effects
            if str(getattr(item, "row_type", "EFFECT") or "EFFECT") == "EFFECT"
        )
        if (
            current_ids == tuple(target_ids)
            and str(getattr(rig, "fbp_effects_signature", "") or "") == signature
        ):
            return target_ids
    except FBP_DATA_ERRORS:
        pass
    from . import safe_tasks as _safe_tasks
    rig_name = str(getattr(rig, "name", "") or "")
    rig_key = fbp_obj_runtime_key(rig)

    def _timer():
        active_rig = fbp_find_id_by_runtime_key(
            bpy.data.objects, rig_key, rig_name
        )
        if active_rig is None:
            return None
        current_rigs = _fbp_unique_live_rigs(
            active_rig,
            _fbp_selected_rigs(getattr(bpy, "context", None)),
        )
        # UI mirroring must stay lightweight. Structural repair is performed by
        # effect operators, Scene sync and explicit diagnostics, not every time
        # the sidebar needs to rebuild its transient list.
        fbp_sync_effect_items(
            active_rig,
            current_rigs,
            repair_assets=False,
            normalize_instance_ids=False,
        )
        return None

    _safe_tasks.schedule_once(
        f"ui.effect_stack.{rig_key}", _timer, first_interval=0.03
    )
    return target_ids


def fbp_active_effect_id(rig):
    if not rig or not hasattr(rig, "fbp_effects"):
        return ""
    try:
        index = int(getattr(rig, "fbp_effects_index", 0) or 0)
        if 0 <= index < len(rig.fbp_effects):
            item = rig.fbp_effects[index]
            if str(getattr(item, "row_type", "EFFECT") or "EFFECT") != "EFFECT":
                return ""
            return str(getattr(item, "effect_id", "") or "")
    except FBP_DATA_ERRORS:
        pass
    return ""


def fbp_active_effect_group_id(rig):
    """Return the folder selected in the Effects UI, or the active effect folder."""
    if not rig or not hasattr(rig, "fbp_effects"):
        return ""
    try:
        index = int(getattr(rig, "fbp_effects_index", 0) or 0)
        if 0 <= index < len(rig.fbp_effects):
            item = rig.fbp_effects[index]
            group_id = str(getattr(item, "group_id", "") or "")
            if group_id:
                return group_id
    except FBP_DATA_ERRORS:
        pass
    return ""


def _fbp_effect_view_categories(context=None, *, effect_id=""):
    """Return the effect categories represented by the active stack view."""
    if effect_id:
        category = str(fbp_effect_definition(effect_id).get("category", "2D") or "2D")
        if category == "3D":
            return {"3D"}
        if category == "MASK":
            return {"MASK"}
        return {"BASE", "2D"}
    scene = getattr(context, "scene", None) if context is not None else None
    view = str(getattr(scene, "fbp_effects_view", "2D") or "2D")
    if view == "3D":
        return {"3D"}
    if view == "MASK":
        return {"MASK"}
    return {"BASE", "2D"}


def fbp_selected_effect_ids(
    rig, *, fallback_active=True, movable_only=False, categories=None
):
    """Return checked effect rows in stack order, optionally limited by view.

    The active row is used as a fallback so all legacy single-row operations
    keep working when no multi-selection checkbox is enabled.
    """
    if not rig or not hasattr(rig, "fbp_effects"):
        return []
    category_filter = {str(value) for value in tuple(categories or ()) if value}
    selected = []
    try:
        for item in rig.fbp_effects:
            if not bool(getattr(item, "is_selected", False)):
                continue
            effect_id = fbp_normalize_effect_id(getattr(item, "effect_id", ""))
            definition = fbp_effect_definition(effect_id)
            category = str(definition.get("category", "2D") or "2D")
            if not effect_id or (category_filter and category not in category_filter):
                continue
            if movable_only and definition.get("kind") not in {"SHADER", "GEOMETRY"}:
                continue
            if effect_id not in selected:
                selected.append(effect_id)
    except FBP_DATA_ERRORS:
        selected = []
    if not selected and fallback_active:
        active = fbp_active_effect_id(rig)
        definition = fbp_effect_definition(active)
        category = str(definition.get("category", "2D") or "2D")
        if (
            active
            and (not category_filter or category in category_filter)
            and (not movable_only or definition.get("kind") in {"SHADER", "GEOMETRY"})
        ):
            selected.append(active)
        elif not active:
            group_id = fbp_active_effect_group_id(rig)
            for member in fbp_effect_group_members_from_items(rig, group_id):
                member_definition = fbp_effect_definition(member)
                member_category = str(member_definition.get("category", "2D") or "2D")
                if category_filter and member_category not in category_filter:
                    continue
                if movable_only and member_definition.get("kind") not in {"SHADER", "GEOMETRY"}:
                    continue
                selected.append(member)
    return selected


def fbp_set_effect_selection(
    rig, effect_ids=(), *, mode="REPLACE", eligible_ids=None
):
    """Update transient effect-row selection without touching effect data."""
    if not rig or not hasattr(rig, "fbp_effects"):
        return False
    requested = {fbp_normalize_effect_id(value) for value in effect_ids if value}
    eligible = None
    if eligible_ids is not None:
        eligible = {
            fbp_normalize_effect_id(value) for value in eligible_ids if value
        }
    mode = str(mode or "REPLACE").upper()
    changed = False
    try:
        for item in rig.fbp_effects:
            if str(getattr(item, "row_type", "EFFECT") or "EFFECT") != "EFFECT":
                continue
            effect_id = fbp_normalize_effect_id(getattr(item, "effect_id", ""))
            if eligible is not None and effect_id not in eligible:
                continue
            current = bool(getattr(item, "is_selected", False))
            if mode == "ADD":
                target = current or effect_id in requested
            elif mode == "REMOVE":
                target = current and effect_id not in requested
            elif mode == "INVERT":
                target = not current
            else:
                target = effect_id in requested
            if current != target:
                item.is_selected = target
                changed = True
    except FBP_DATA_ERRORS:
        return False
    return changed


def _fbp_select_effect_row(rig, effect_id, rigs=None):
    """Select an effect in the runtime UI mirror without changing Blender data."""
    effect_id = fbp_normalize_effect_id(effect_id)
    if not rig or not effect_id:
        return False
    fbp_sync_effect_items(rig, rigs)
    try:
        for index, item in enumerate(rig.fbp_effects):
            if (
                str(getattr(item, "row_type", "EFFECT") or "EFFECT") == "EFFECT"
                and fbp_normalize_effect_id(getattr(item, "effect_id", "")) == effect_id
            ):
                rig.fbp_effects_index = index
                return True
    except FBP_DATA_ERRORS:
        pass
    return False


def _fbp_select_effect_group_row(rig, group_id, rigs=None):
    """Select a real Effect Group folder row without selecting a member effect."""
    group_id = str(group_id or "")
    if not rig or not group_id:
        return False
    fbp_sync_effect_items(rig, rigs)
    try:
        for index, item in enumerate(rig.fbp_effects):
            if (
                str(getattr(item, "row_type", "EFFECT") or "EFFECT") == "GROUP"
                and str(getattr(item, "group_id", "") or "") == group_id
            ):
                rig.fbp_effects_index = index
                return True
    except FBP_DATA_ERRORS:
        pass
    return False


def fbp_add_effect(
    rig,
    effect_id,
    *,
    select_object_mask_helper=True,
    inherit_active_group=True,
    sync_items=True,
    rebuild_shader=True,
):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if effect_id == FBP_EFFECT_LATTICE:
        lattice_issue = _fbp_lattice_compatibility_issue(rig)
        if lattice_issue:
            _fbp_set_lattice_error(rig, lattice_issue)
            return False
    elif not fbp_effect_supported_for_rig(rig, effect_id):
        return False
    was_active = (
        fbp_effect_is_active(rig, effect_id)
        if effect_id == FBP_EFFECT_THICKNESS else False
    )
    if effect_id == FBP_EFFECT_THICKNESS and not was_active:
        _fbp_prepare_new_extrude(rig)

    # Capture the active folder before applying the new nodes/modifier, because
    # the apply routines synchronize and select the new row.  User-created
    # effects inherit the open group they were added from when both effects
    # belong to the same real evaluation chain.
    group_anchor = ""
    inherited_group_id = ""
    inherited_group_name = ""
    inherited_group_color = "NONE"
    inherited_group_collapsed = False
    if inherit_active_group:
        group_anchor = fbp_active_effect_id(rig)
        inherited_group_id = fbp_active_effect_group_id(rig)
        if inherited_group_id and not group_anchor:
            # A selected folder inserts new compatible effects at the end of
            # that folder instead of treating one member as the container row.
            members = fbp_effect_group_members_from_items(rig, inherited_group_id)
            group_anchor = members[-1] if members else ""
        elif group_anchor and group_anchor != effect_id:
            inherited_group_id = fbp_effect_group_id_for_rig(
                rig, group_anchor, normalize=False
            )
        if inherited_group_id:
            inherited_group_name = fbp_effect_group_name(
                rig, inherited_group_id
            )
            inherited_group_color = fbp_effect_group_color_tag(
                rig, inherited_group_id
            )
            inherited_group_collapsed = fbp_effect_group_collapsed(
                rig, inherited_group_id
            )
    if definition.get("kind") == "BASE":
        changed = _fbp_set_enabled(rig, effect_id, True)
        if effect_id == FBP_EFFECT_CAMERA_BILLBOARD:
            applied_constraint = _fbp_apply_track_to_camera_constraint(rig)
            applied = bool(applied_constraint or _fbp_track_to_camera_constraint(rig))
            if not applied:
                _fbp_set_enabled(rig, effect_id, False)
        elif effect_id == FBP_EFFECT_LATTICE:
            applied = _fbp_apply_lattice_effect(rig, select=False)
            if not applied:
                _fbp_set_enabled(rig, effect_id, False)
                _fbp_cleanup_incomplete_lattice_setup(rig)
        else:
            applied = changed or fbp_effect_is_active(rig, effect_id)
        if changed or applied:
            _fbp_invalidate_effect_ids_cache(rig)
        if sync_items:
            fbp_sync_effect_items(rig)
    elif definition.get("kind") == "GEOMETRY":
        applied = fbp_apply_geometry_effect(
            rig, effect_id, sync_items=sync_items
        )
    elif definition.get("kind") == "SHADER":
        applied = fbp_apply_shader_effect(
            rig,
            effect_id,
            rebuild=bool(rebuild_shader),
            sync_items=sync_items,
        )
    else:
        return False
    if applied and definition.get("evolve_property"):
        fbp_ensure_effect_animation_state(rig, effect_id)
    if applied and definition.get("mask_source_visibility_aware"):
        fbp_sync_matte_source_visibility(getattr(bpy.context, "scene", None))
    if applied and effect_id in {FBP_EFFECT_CLIPPING_MASK, FBP_EFFECT_LAYER_BLEND}:
        try:
            from .layers import get_primary_fbp_collection
            relation_collection = get_primary_fbp_collection(rig)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            relation_collection = None
        fbp_schedule_clipping_mask_sync(
            getattr(bpy.context, "scene", None),
            collections=(relation_collection,) if relation_collection is not None else None,
        )
    if applied:
        _fbp_invalidate_mask_target_cache(rig)
        if effect_id == FBP_EFFECT_PIXELATE:
            _fbp_refresh_extrude_pixel_dependency(rig)
    if applied and definition.get("object_mask_aware"):
        try:
            from .object_masks import ensure_object_mask_helper
            helper = ensure_object_mask_helper(
                rig,
                definition.get("object_mask_shape", "SQUARE"),
                context=bpy.context,
                select=bool(select_object_mask_helper),
            )
            for node in _fbp_find_shader_effect_nodes_for_rig(rig, effect_id):
                _fbp_sync_object_mask_helper(rig, effect_id, node, create=False)
            if not helper:
                fbp_remove_effect(rig, effect_id, sync_items=sync_items)
                applied = False
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not create Shape Mask helper", exc)
            # Do not leave an active Shape Mask effect with no editable helper.
            try:
                fbp_remove_effect(rig, effect_id, sync_items=sync_items)
            except FBP_DATA_ERRORS:
                pass
            applied = False
    if (
        applied
        and inherited_group_id
        and _fbp_effect_chain_key(group_anchor) == _fbp_effect_chain_key(effect_id)
    ):
        # Place the new effect directly after the active member, then attach it
        # to the same persistent folder.  If Blender cannot move it safely, the
        # effect remains valid and simply stays outside the group.
        fbp_move_effect_selection_relative_transactional(
            [rig], [effect_id], group_anchor, "AFTER"
        )
        if fbp_set_effect_group_id(
            rig,
            effect_id,
            inherited_group_id,
            group_name=inherited_group_name,
        ):
            record = _fbp_effect_group_record(rig, inherited_group_id)
            if record is not None:
                try:
                    record.color_tag = inherited_group_color
                    record.collapsed = inherited_group_collapsed
                except FBP_DATA_ERRORS:
                    pass
            fbp_sync_effect_groups(rig)
            if sync_items:
                fbp_sync_effect_items(rig)
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
    if fbp_effect_is_active(rig, FBP_EFFECT_PIXELATE):
        changed = _fbp_refresh_extrude_pixel_dependency(rig) or changed
    fbp_sync_effect_items(rig)
    return changed


def _fbp_clear_effect_auxiliary_state(rig, effect_id):
    changed = False
    for key in (
        _fbp_effect_state_key(effect_id, "input_source"),
        _fbp_effect_state_key(effect_id, "debug"),
        _fbp_effect_mask_target_key(effect_id),
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

def _fbp_remove_effect_viewport_controls(rig, effect_id):
    try:
        from .effect_controls import remove_effect_controls
        return bool(remove_effect_controls(rig, effect_id))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def fbp_remove_effect(rig, effect_id, *, sync_items=True):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    solo_before = (
        tuple(fbp_effect_solo_ids(rig, _fbp_effect_solo_view(effect_id)))
        if definition.get("kind") in {"SHADER", "GEOMETRY"} else ()
    )
    if definition.get("kind") == "BASE":
        if effect_id == FBP_EFFECT_LATTICE:
            changed = _fbp_remove_lattice_effect(rig)
            changed = _fbp_set_enabled(rig, effect_id, False) or changed
            changed = _fbp_clear_effect_visibility(rig, effect_id) or changed
            changed = _fbp_clear_effect_render_visibility(rig, effect_id) or changed
            _fbp_clear_effect_auxiliary_state(rig, effect_id)
            _fbp_invalidate_effect_ids_cache(rig)
            if sync_items:
                fbp_sync_effect_items(rig)
            return changed
        if effect_id == FBP_EFFECT_CAMERA_BILLBOARD:
            changed = _fbp_remove_track_to_camera_constraint(rig)
            changed = _fbp_set_enabled(rig, effect_id, False) or changed
            changed = _fbp_clear_effect_visibility(rig, effect_id) or changed
            changed = _fbp_clear_effect_render_visibility(rig, effect_id) or changed
            _fbp_clear_effect_auxiliary_state(rig, effect_id)
            _fbp_invalidate_effect_ids_cache(rig)
            if changed:
                _fbp_remove_effect_viewport_controls(rig, effect_id)
            if sync_items:
                fbp_sync_effect_items(rig)
            return changed
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
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not reset Crop / Extend geometry", exc)
        _fbp_clear_effect_auxiliary_state(rig, effect_id)
        if changed:
            _fbp_invalidate_effect_ids_cache(rig)
        if changed:
            _fbp_remove_effect_viewport_controls(rig, effect_id)
        if sync_items:
            fbp_sync_effect_items(rig)
        return changed
    if definition.get("kind") == "GEOMETRY":
        old_group = fbp_effect_group_id_for_rig(rig, effect_id)
        old_group_name = fbp_effect_group_name(rig, old_group)
        fbp_set_effect_group_id(rig, effect_id, "")
        changed = fbp_remove_geometry_effect(rig, effect_id, sync_items=sync_items)
        if changed:
            _fbp_clear_effect_auxiliary_state(rig, effect_id)
            _fbp_remove_effect_viewport_controls(rig, effect_id)
            _fbp_reconcile_effect_solo_after_removal(rig, effect_id, solo_before)
        elif old_group:
            fbp_set_effect_group_id(
                rig, effect_id, old_group, group_name=old_group_name
            )
        return changed
    if definition.get("kind") == "SHADER":
        old_group = fbp_effect_group_id_for_rig(rig, effect_id)
        old_group_name = fbp_effect_group_name(rig, old_group)
        fbp_set_effect_group_id(rig, effect_id, "")
        changed = fbp_remove_shader_effect(rig, effect_id, sync_items=sync_items)
        if changed:
            _fbp_clear_effect_auxiliary_state(rig, effect_id)
            _fbp_remove_effect_viewport_controls(rig, effect_id)
            for mask_id in tuple(fbp_effect_ids_for_rig(rig)):
                if not _fbp_effect_is_local_mask(mask_id):
                    continue
                try:
                    raw_target = fbp_normalize_effect_id(
                        rig.get(_fbp_effect_mask_target_key(mask_id), "LAYER")
                    )
                except FBP_DATA_ERRORS:
                    raw_target = "LAYER"
                if raw_target == effect_id:
                    fbp_set_effect_mask_target(rig, mask_id, "LAYER")
            _fbp_reconcile_effect_solo_after_removal(rig, effect_id, solo_before)
            if definition.get("mask_source_aware"):
                source_prop = str(definition.get("mask_source_property", "") or "")
                if definition.get("layer_feature") and source_prop:
                    fbp_set_rna_property_silent(rig, source_prop, None)
                if definition.get("mask_source_visibility_aware"):
                    fbp_sync_matte_source_visibility(
                        getattr(bpy.context, "scene", None)
                    )
            if definition.get("object_mask_aware"):
                try:
                    from .object_masks import remove_object_mask_helper
                    remove_object_mask_helper(rig, definition.get("object_mask_shape", "SQUARE"))
                except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                    fbp_warn("Could not remove Shape Mask helper", exc)
        elif old_group:
            fbp_set_effect_group_id(
                rig, effect_id, old_group, group_name=old_group_name
            )
        if changed:
            _fbp_invalidate_mask_target_cache(rig)
            if effect_id == FBP_EFFECT_PIXELATE:
                _fbp_refresh_extrude_pixel_dependency(rig, force=True)
        return changed
    return False


def _fbp_geometry_effect_id_for_modifier(modifier):
    if not modifier or getattr(modifier, "type", "") != "NODES":
        return ""
    try:
        tagged = fbp_normalize_effect_id(modifier.get("fbp_effect_id", ""))
        if tagged in FBP_EFFECT_REGISTRY and fbp_effect_definition(tagged).get("kind") == "GEOMETRY":
            return tagged
    except FBP_DATA_ERRORS:
        pass
    node_group = getattr(modifier, "node_group", None)
    try:
        declared = fbp_normalize_effect_id(node_group.get("fbp_effect_id", "")) if node_group else ""
        if (
            declared in FBP_EFFECT_REGISTRY
            and fbp_effect_definition(declared).get("kind") == "GEOMETRY"
        ):
            return declared
    except FBP_DATA_ERRORS:
        pass
    for effect_id, definition in FBP_EFFECT_REGISTRY.items():
        if definition.get("kind") == "GEOMETRY" and _fbp_group_matches(node_group, effect_id):
            return effect_id
    return ""


def _fbp_move_shader_effect_to_stage_edge(
    rig, effect_id, *, first=True, rebuild=True, sync_items=True
):
    """Move one shader effect to a stage edge without iterative rebuilds."""
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if definition.get("kind") != "SHADER":
        return False
    stage = str(definition.get("stage", "") or "")
    materials = [
        material for material in _fbp_plane_materials(rig)
        if _fbp_shader_effect_nodes(material, effect_id=effect_id)
    ]
    if not materials:
        return False

    order = _fbp_get_rig_shader_stage_order(rig, stage)
    if effect_id not in order:
        order = _fbp_get_shader_stage_order(materials[0], stage)
    if effect_id not in order:
        return False

    desired = [item for item in order if item != effect_id]
    if first:
        desired.insert(0, effect_id)
    else:
        desired.append(effect_id)
    if desired == order:
        return True

    _fbp_set_rig_shader_stage_order(rig, stage, desired)
    rebuilt = False
    for material in materials:
        active = _fbp_get_shader_stage_order(material, stage)
        material_order = [item for item in desired if item in active]
        material_order.extend(item for item in active if item not in material_order)
        _fbp_set_shader_stage_order(material, stage, material_order)
        if rebuild:
            rebuilt = _fbp_rebuild_shader_stage(material, stage) or rebuilt
        else:
            rebuilt = True
    if sync_items:
        fbp_sync_effect_items(rig)
    return rebuilt or bool(materials)


def fbp_move_effect(rig, effect_id, direction, *, sync_items=True):
    """Move an effect in its real Blender evaluation chain.

    ``sync_items=False`` is reserved for grouped transactions so several real
    Blender moves can be committed before rebuilding the transient UI mirror.
    """
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
        except FBP_DATA_ERRORS:
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
            _fbp_invalidate_effect_ids_cache(rig)
            if sync_items:
                fbp_sync_effect_items(rig)
            return True
        except FBP_DATA_ERRORS:
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
            _fbp_invalidate_effect_ids_cache(rig)
            if sync_items:
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
    for stage in ("UV", "COLOR", "MASK"):
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
        except FBP_DATA_ERRORS:
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
                except FBP_DATA_ERRORS:
                    pass
        elif source_group and previous_group != source_group:
            try:
                current_asset = str(previous_group.get("fbp_effect_asset_id", "") or "") if previous_group else ""
                desired_asset = str(definition.get("asset_id", "") or "")
                if current_asset != desired_asset:
                    modifier.node_group = source_group
                    changed = True
            except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
                except FBP_DATA_ERRORS:
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


def _fbp_sanitize_mask_source_for_target(target, value, definition, scene=None):
    """Return a valid matte source for one target in a multi-edit transaction.

    A shared PointerProperty update can otherwise assign one selected layer as
    its own matte source. Keep the source for compatible targets, but clear it
    for the source layer itself or for targets from another Scene.
    """
    source_prop = str(definition.get("mask_source_property", "") or "")
    if not source_prop:
        return value
    source = value
    if not source or source is target:
        return None
    try:
        if not bool(getattr(source, "is_fbp_control", False)):
            return None
        if bool(getattr(source, "fbp_is_color_plane", False)):
            return None
        if not _fbp_objects_share_scene(target, source, scene=scene):
            return None
    except FBP_DATA_ERRORS:
        return None
    return source


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
    scene = getattr(context, "scene", None) if context else None
    for rig in targets:
        target_value = value
        if prop_name == str(definition.get("mask_source_property", "") or ""):
            target_value = _fbp_sanitize_mask_source_for_target(
                rig, value, definition, scene=scene
            )
        if rig != self or target_value is not value:
            fbp_set_rna_property_silent(rig, prop_name, target_value)
        if effect_id == FBP_EFFECT_TEXT_MATRIX and prop_name in text_matrix_manual_grid:
            fbp_set_rna_property_silent(rig, "fbp_text_matrix_quality", "CUSTOM")
        if effect_id == FBP_EFFECT_MESH_WIGGLE and bool(getattr(rig, "fbp_mesh_wiggle_unique_seed", False)):
            fbp_assign_mesh_wiggle_layer_seed(rig)
        if definition.get("kind") == "GEOMETRY":
            requested = {prop_name}
            if effect_id == FBP_EFFECT_THICKNESS and prop_name in {
                "fbp_thickness_grid_mode",
                "fbp_thickness_follow_pixelate",
                "fbp_thickness_safe_grid",
            }:
                requested = {
                    "fbp_thickness_viewport_pixels_x",
                    "fbp_thickness_viewport_pixels_y",
                }
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
            if effect_id == FBP_EFFECT_THICKNESS and requested & {
                "fbp_thickness_viewport_pixels_x",
                "fbp_thickness_viewport_pixels_y",
            }:
                # Auto Height and Follow Pixelate make X and Y one logical
                # contract. Refresh both sockets after either axis changes so
                # the generated geometry cannot retain a stale vertical grid.
                requested = {
                    "fbp_thickness_viewport_pixels_x",
                    "fbp_thickness_viewport_pixels_y",
                }
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
            if effect_id == FBP_EFFECT_PIXELATE:
                _fbp_refresh_extrude_pixel_dependency(rig)
    if definition.get("mask_source_visibility_aware") and prop_name in {
        definition.get("mask_source_property", ""),
        "fbp_alpha_matte_source_display",
        "fbp_luma_matte_source_display",
    }:
        fbp_sync_matte_source_visibility(scene)


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
    if effect_id == FBP_EFFECT_CAMERA_BILLBOARD:
        constraint = _fbp_track_to_camera_constraint(rig)
        return bool(
            fbp_effect_is_active(rig, effect_id)
            and constraint is not None
            and not bool(getattr(constraint, "mute", False))
        )
    if effect_id == FBP_EFFECT_LATTICE:
        plane = _fbp_plane(rig)
        modifier = _fbp_lattice_modifier(plane)
        detail = _fbp_lattice_detail_modifier(plane)
        return bool(
            fbp_effect_is_active(rig, effect_id)
            and modifier is not None
            and bool(getattr(modifier, "show_viewport", True))
            and (detail is None or bool(getattr(detail, "show_viewport", True)))
        )
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
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    visible = bool(visible)
    if effect_id == FBP_EFFECT_CAMERA_BILLBOARD:
        changed = _fbp_store_effect_visibility(rig, effect_id, visible)
        constraint = _fbp_track_to_camera_constraint(rig)
        if constraint is not None and bool(getattr(constraint, "mute", False)) == visible:
            constraint.mute = not visible
            changed = True
        return changed
    if effect_id == FBP_EFFECT_LATTICE:
        changed = _fbp_store_effect_visibility(rig, effect_id, visible)
        plane = _fbp_plane(rig)
        modifier = _fbp_lattice_modifier(plane)
        detail = _fbp_lattice_detail_modifier(plane)
        for owned_modifier in (modifier, detail):
            if owned_modifier is not None and bool(getattr(owned_modifier, "show_viewport", True)) != visible:
                owned_modifier.show_viewport = visible
                changed = True
        helper = _fbp_lattice_object(rig)
        if helper is not None:
            try:
                show_cage = bool(getattr(rig, "fbp_lattice_show_cage", True))
                target_hide_viewport = not visible
                target_hidden = not bool(visible and show_cage)
                if bool(getattr(helper, "hide_viewport", False)) != target_hide_viewport:
                    helper.hide_viewport = target_hide_viewport
                    changed = True
                if bool(helper.hide_get()) != target_hidden:
                    helper.hide_set(target_hidden)
                    changed = True
            except FBP_DATA_ERRORS:
                pass
        return changed
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
    if changed and _fbp_effect_is_local_mask(effect_id):
        target_effect_id = fbp_effect_mask_target(rig, effect_id)
        if target_effect_id != "LAYER":
            for material in _fbp_plane_materials(rig):
                changed = _fbp_rebuild_mask_target_routing(
                    material, target_effect_id, target_effect_id
                ) or changed
    if changed and effect_id == FBP_EFFECT_PIXELATE:
        changed = _fbp_refresh_extrude_pixel_dependency(
            rig, force=True
        ) or changed
    return changed


_FBP_EFFECT_SOLO_PROP_2D = "fbp_effect_solo_ids_2d"
_FBP_EFFECT_SOLO_PROP_MASK = "fbp_effect_solo_ids_mask"
_FBP_EFFECT_SOLO_PROP_3D = "fbp_effect_solo_ids_3d"


def _fbp_effect_solo_view(effect_id):
    category = str(fbp_effect_definition(effect_id).get("category", "2D") or "2D")
    if category == "3D":
        return "3D"
    if category == "MASK":
        return "MASK"
    return "2D"


def _fbp_effect_solo_prop(view):
    view = str(view or "2D")
    if view == "3D":
        return _FBP_EFFECT_SOLO_PROP_3D
    if view == "MASK":
        return _FBP_EFFECT_SOLO_PROP_MASK
    return _FBP_EFFECT_SOLO_PROP_2D


def _fbp_effect_solo_candidates(rig, view):
    view = str(view or "2D")
    categories = {"3D"} if view == "3D" else ({"MASK"} if view == "MASK" else {"BASE", "2D"})
    return tuple(
        effect_id for effect_id in fbp_effect_ids_for_rig(rig)
        if (
            fbp_effect_definition(effect_id).get("kind") in {"SHADER", "GEOMETRY"}
            or effect_id == FBP_EFFECT_LATTICE
        )
        and str(fbp_effect_definition(effect_id).get("category", "2D") or "2D") in categories
    )


def fbp_effect_solo_ids(rig, view):
    key = _fbp_effect_solo_prop(view)
    try:
        raw = rig.get(key, "[]")
        values = json.loads(raw) if isinstance(raw, str) else list(raw or ())
    except (AttributeError, ReferenceError, TypeError, ValueError, json.JSONDecodeError):
        values = ()
    candidates = set(_fbp_effect_solo_candidates(rig, view))
    return tuple(
        effect_id for effect_id in dict.fromkeys(
            fbp_normalize_effect_id(value) for value in values
        )
        if effect_id and effect_id in candidates
    )


def fbp_effect_is_soloed(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    return bool(effect_id and effect_id in fbp_effect_solo_ids(rig, _fbp_effect_solo_view(effect_id)))


def _fbp_store_effect_solo_ids(rig, view, effect_ids):
    key = _fbp_effect_solo_prop(view)
    normalized = tuple(dict.fromkeys(
        effect_id for effect_id in (fbp_normalize_effect_id(item) for item in effect_ids)
        if effect_id
    ))
    encoded = json.dumps(normalized, separators=(",", ":"))
    try:
        previous = str(rig.get(key, "[]") or "[]")
        if previous == encoded:
            return False
        rig[key] = encoded
        return True
    except (AttributeError, ReferenceError, TypeError, ValueError):
        return False


def fbp_toggle_effect_solo(rig, target_ids):
    target_ids = tuple(dict.fromkeys(
        effect_id for effect_id in (fbp_normalize_effect_id(item) for item in target_ids)
        if effect_id and fbp_effect_is_active(rig, effect_id)
        and (
            fbp_effect_definition(effect_id).get("kind") in {"SHADER", "GEOMETRY"}
            or effect_id == FBP_EFFECT_LATTICE
        )
    ))
    if not target_ids:
        return False
    view = _fbp_effect_solo_view(target_ids[0])
    candidates = tuple(_fbp_effect_solo_candidates(rig, view))
    target_set = {effect_id for effect_id in target_ids if effect_id in candidates}
    if not target_set:
        return False
    current = set(fbp_effect_solo_ids(rig, view))
    if target_set.issubset(current):
        current.difference_update(target_set)
    else:
        current.update(target_set)
    changed = False
    if current:
        for effect_id in candidates:
            changed = fbp_set_effect_visible(rig, effect_id, effect_id in current) or changed
    else:
        for effect_id in candidates:
            changed = fbp_set_effect_visible(rig, effect_id, True) or changed
    changed = _fbp_store_effect_solo_ids(rig, view, current) or changed
    return changed


def _fbp_reconcile_effect_solo_after_removal(rig, removed_effect_id, solo_before):
    removed_effect_id = fbp_normalize_effect_id(removed_effect_id)
    previous = {fbp_normalize_effect_id(item) for item in solo_before if item}
    if removed_effect_id not in previous:
        return False
    view = _fbp_effect_solo_view(removed_effect_id)
    remaining = {
        effect_id for effect_id in previous
        if effect_id != removed_effect_id and fbp_effect_is_active(rig, effect_id)
    }
    changed = False
    for effect_id in _fbp_effect_solo_candidates(rig, view):
        changed = fbp_set_effect_visible(
            rig, effect_id, effect_id in remaining if remaining else True
        ) or changed
    changed = _fbp_store_effect_solo_ids(rig, view, remaining) or changed
    return changed


def fbp_effect_render_visible_state(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    if effect_id == FBP_EFFECT_CAMERA_BILLBOARD:
        return _fbp_stored_effect_render_visibility(rig, effect_id, True)
    if effect_id == FBP_EFFECT_LATTICE:
        plane = _fbp_plane(rig)
        modifier = _fbp_lattice_modifier(plane)
        detail = _fbp_lattice_detail_modifier(plane)
        if modifier is not None:
            return bool(
                getattr(modifier, "show_render", True)
                and (detail is None or getattr(detail, "show_render", True))
            )
        return _fbp_stored_effect_render_visibility(rig, effect_id, True)
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
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    visible = bool(visible)
    if effect_id == FBP_EFFECT_CAMERA_BILLBOARD:
        return _fbp_store_effect_render_visibility(rig, effect_id, visible)
    if effect_id == FBP_EFFECT_LATTICE:
        changed = _fbp_store_effect_render_visibility(rig, effect_id, visible)
        plane = _fbp_plane(rig)
        modifier = _fbp_lattice_modifier(plane)
        detail = _fbp_lattice_detail_modifier(plane)
        for owned_modifier in (modifier, detail):
            if owned_modifier is not None and bool(getattr(owned_modifier, "show_render", True)) != visible:
                owned_modifier.show_render = visible
                changed = True
        return changed
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
        active_ids = profile.get("active_ids", frozenset())
        # Static image-aware effects no longer run a Python frame callback. Bind
        # their source once at render start so external material/image edits are
        # still repaired before the first sample. Animated sources continue to
        # use the managed per-frame path selected by the runtime profile.
        try:
            if active_ids.intersection(FBP_FRAME_SYNC_GEOMETRY_EFFECT_IDS):
                _fbp_sync_geometry_alpha_frame_offset(
                    rig,
                    scene=scene,
                    effect_modifiers=profile.get("frame_geometry_modifiers", ()),
                )
            if active_ids.intersection(FBP_FRAME_SYNC_SHADER_EFFECT_IDS):
                _fbp_sync_shader_image_sources(
                    rig,
                    active_ids,
                    target_nodes=profile.get("frame_shader_targets", ()),
                    scene=scene,
                )
        except FBP_DATA_ERRORS:
            _fbp_invalidate_effect_runtime_profile(rig)
        local_mask_target_ids = set()
        for effect_id in profile.get("effect_ids", ()):
            definition = fbp_effect_definition(effect_id)
            if effect_id == FBP_EFFECT_CAMERA_BILLBOARD:
                constraint = _fbp_track_to_camera_constraint(rig)
                if constraint is not None:
                    try:
                        render_visible = _fbp_stored_effect_render_visibility(
                            rig, effect_id, True
                        )
                        target_mute = not render_visible
                        current_mute = bool(getattr(constraint, "mute", False))
                        if current_mute != target_mute:
                            backup.append(("CONSTRAINT_MUTE", constraint, current_mute))
                            constraint.mute = target_mute
                    except FBP_DATA_ERRORS:
                        pass
                continue
            if definition.get("kind") == "SHADER":
                render_visible = _fbp_stored_effect_render_visibility(rig, effect_id, True)
                for node in profile.get("shader_nodes", {}).get(effect_id, ()):
                    try:
                        target_mute = not render_visible
                        current_mute = bool(node.mute)
                        if current_mute != target_mute:
                            backup.append(("NODE_MUTE", node, current_mute))
                            node.mute = target_mute
                            if _fbp_effect_is_local_mask(effect_id):
                                local_target = fbp_effect_mask_target(rig, effect_id)
                                if local_target != "LAYER":
                                    local_mask_target_ids.add(local_target)
                    except FBP_DATA_ERRORS:
                        pass
                continue
            contracts = _fbp_quality_contracts(definition)
            if not contracts:
                continue
            modifier = profile.get("geometry_modifiers", {}).get(effect_id)
            node_group = getattr(modifier, "node_group", None) if modifier else None
            if not modifier or not node_group:
                continue
            extrude_render_grid = (
                _fbp_extrude_grid(rig, "RENDER")
                if effect_id == FBP_EFFECT_THICKNESS else None
            )
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
                    if extrude_render_grid is not None and socket_name in {"Pixels X", "Pixels Y"}:
                        render_value = (
                            extrude_render_grid[0]
                            if socket_name == "Pixels X" else extrude_render_grid[1]
                        )
                    else:
                        render_value = _fbp_quality_value(getattr(rig, property_name), contract)
                    if old_value != render_value:
                        backup.append(("MODIFIER_INPUT", modifier, identifier, old_value))
                        modifier[identifier] = render_value
                except FBP_DATA_ERRORS:
                    continue
        if local_mask_target_ids:
            for material in _fbp_plane_materials(rig):
                _fbp_rebuild_mask_target_batch(material, local_mask_target_ids)
            backup.append(("LOCAL_MASK_REBUILD", rig, tuple(local_mask_target_ids)))
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
            elif tag == "CONSTRAINT_MUTE":
                _tag, constraint, muted = item
                constraint.mute = bool(muted)
            elif tag == "LOCAL_MASK_REBUILD":
                _tag, rig, target_ids = item
                for material in _fbp_plane_materials(rig):
                    _fbp_rebuild_mask_target_batch(material, target_ids)
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
            view = _fbp_effect_solo_view(effect_id)
            if fbp_effect_solo_ids(target, view):
                changed = _fbp_store_effect_solo_ids(target, view, ()) or changed
            changed = fbp_set_effect_visible(target, effect_id, visible) or changed
    return changed


def _fbp_custom_effect_reserved_socket_names(definition):
    return {
        str(definition.get(key, "") or "")
        for key in (
            "input_socket", "output_socket", "alpha_input_socket",
            "alpha_output_socket", "mask_output_socket", "uv_input_socket",
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
    except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
            continue
    return _fbp_cache_custom_socket_descriptors(
        _FBP_CUSTOM_GEOMETRY_SOCKET_CACHE, key, result
    )


def _fbp_custom_shader_value_sockets(node, definition):
    reserved = _fbp_custom_effect_reserved_socket_names(definition)
    try:
        input_count = len(node.inputs)
    except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
                continue
    return False


def _fbp_custom_shader_topology_signature(nodes):
    return tuple(_fbp_runtime_rna_key(node) for node in tuple(nodes or ()))


def _fbp_json_state_signature(state):
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
    state_signature = _fbp_json_state_signature(state)
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
    except FBP_DATA_ERRORS:
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
        target_rig = fbp_find_id_by_runtime_key(
            bpy.data.objects, rig_key, stored_name
        )
        if target_rig is not None:
            current_nodes = _fbp_find_shader_effect_nodes_for_rig(target_rig, effect_id)
            try:
                current_instance = (
                    str(effect_instance_id(current_nodes[0]) or "")
                    if current_nodes else ""
                )
            except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
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
            except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
        except FBP_DATA_ERRORS:
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
    except FBP_DATA_ERRORS:
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
        target_rig = fbp_find_id_by_runtime_key(
            bpy.data.objects, rig_key, stored_name
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
        except FBP_DATA_ERRORS:
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
                except FBP_DATA_ERRORS:
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


_FBP_EFFECT_UI_ACRONYMS = {
    "alpha": "Alpha",
    "ascii": "ASCII",
    "fps": "FPS",
    "rgb": "RGB",
    "rgba": "RGBA",
    "uv": "UV",
    "x": "X",
    "y": "Y",
    "z": "Z",
    "w": "W",
    "2d": "2D",
    "3d": "3D",
}


def _fbp_clean_effect_ui_label(value, *, effect_id="", fallback="Value"):
    """Return a readable UI label without exposing internal FBP identifiers."""
    label = str(value or "").strip()
    if not label:
        label = str(fallback or "Value")

    # Human-written names remain untouched. Internal identifiers and bare
    # snake_case socket names are normalized defensively for built-in and
    # user-created effects alike.
    looks_internal = (
        label.lower().startswith(("fbp_", "frame_by_plane_"))
        or ("_" in label and " " not in label)
    )
    if not looks_internal:
        return label

    token = label.strip(" _")
    lowered = token.lower()
    for prefix in ("frame_by_plane_", "fbp_effect_", "fbp_anim_", "fbp_"):
        if lowered.startswith(prefix):
            token = token[len(prefix):]
            lowered = token.lower()
            break
    if lowered.startswith("effect_"):
        token = token[len("effect_"):]
        lowered = token.lower()

    effect_token = str(effect_id or "").strip().lower().replace(" ", "_")
    if effect_token and lowered.startswith(effect_token + "_"):
        token = token[len(effect_token) + 1:]

    words = [part for part in token.replace("-", "_").split("_") if part]
    if not words:
        return str(fallback or "Value")
    return " ".join(
        _FBP_EFFECT_UI_ACRONYMS.get(word.lower(), word.capitalize())
        for word in words
    )


def _fbp_effect_display_label(effect_id, definition=None, fallback="Effect"):
    """Resolve a safe human-readable effect name for every UI surface.

    Related effects remain separate internally for backward compatibility, but
    are presented as one user-facing family with the active variant appended.
    """
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = definition or fbp_effect_definition(effect_id) or {}
    family_id = fbp_effect_family_id(effect_id)
    if family_id:
        family = fbp_effect_family_definition(family_id)
        family_label = str(family.get("label", "Effect") or "Effect")
        variant_label = fbp_effect_variant_label(effect_id)
        return f"{family_label} · {variant_label}"
    return _fbp_clean_effect_ui_label(
        definition.get("label", effect_id),
        effect_id=effect_id,
        fallback=fallback,
    )


def _fbp_effect_property_label(definition, prop_name, labels=None):
    """Resolve one stable display label from registry metadata or local context."""
    labels = labels or {}
    definition = definition or {}
    ui_labels = dict(definition.get("ui_labels", {}))
    property_map = dict(definition.get("property_map", {}))
    candidate = (
        labels.get(prop_name)
        or ui_labels.get(prop_name)
        or property_map.get(prop_name)
        or prop_name
    )
    return _fbp_clean_effect_ui_label(
        candidate,
        effect_id=str(definition.get("effect_id", "") or ""),
        fallback="Value",
    )


def _fbp_effect_property_icon(prop_name, label=""):
    """Choose a readable native Blender icon for common effect controls."""
    probe = f"{prop_name} {label}".lower()
    if any(word in probe for word in ("color", "foreground", "background", "shadow", "highlight", "tint", "despill")):
        return "COLOR"
    if any(word in probe for word in ("alpha", "opacity", "threshold", "matte")):
        return "IMAGE_ALPHA"
    if any(word in probe for word in ("factor", "influence", "strength", "amount", "intensity", "mix")):
        return "MODIFIER"
    if any(word in probe for word in ("uv", "offset", "position", "center", "pivot")):
        return "UV"
    if any(word in probe for word in ("rotation", "angle", "direction", "reverse", "flip", "orientation")):
        return "ORIENTATION_GLOBAL"
    if any(word in probe for word in ("width", "height", "radius", "length", "size", "distance", "scale")):
        return "DRIVER_DISTANCE"
    if any(word in probe for word in ("subdivision", "resolution", "density", "quality", "samples")):
        return "MOD_SUBSURF"
    if any(word in probe for word in ("columns", "rows", "count", "levels", "characters")):
        return "LINENUMBERS_ON"
    if any(word in probe for word in ("pixel", "grid", "cell", "spacing")):
        return "ALIASED"
    if any(word in probe for word in ("seed", "noise", "detail", "roughness", "turbulence", "grain", "variation", "random")):
        return "RNDCURVE"
    if any(word in probe for word in ("frequency", "wave", "curl")):
        return "IPO_SINE"
    if any(word in probe for word in ("speed", "phase", "step", "hold", "animate", "evolve", "flicker", "time")):
        return "TIME"
    if any(word in probe for word in ("camera", "lens", "sensor", "focus")):
        return "CAMERA_DATA"
    if any(word in probe for word in ("font", "text", "glyph", "ascii")):
        return "FONT_DATA"
    if any(word in probe for word in ("source", "image", "texture")):
        return "IMAGE_DATA"
    if any(word in probe for word in ("material", "shade", "smooth", "blend")):
        return "MATERIAL"
    if any(word in probe for word in ("edge", "outline", "border")):
        return "MOD_EDGESPLIT"
    if any(word in probe for word in ("invert", "mirror")):
        return "ARROW_LEFTRIGHT"
    return "OPTIONS"


def _fbp_effect_rna_property(rig, prop_name):
    try:
        properties = getattr(getattr(rig, "bl_rna", None), "properties", None)
        return properties.get(prop_name) if properties is not None else None
    except FBP_DATA_ERRORS:
        return None


def _fbp_effect_property_full_width(rig, prop_name, label):
    rna_prop = _fbp_effect_rna_property(rig, prop_name)
    prop_type = str(getattr(rna_prop, "type", "") or "")
    subtype = str(getattr(rna_prop, "subtype", "") or "")
    array_length = int(getattr(rna_prop, "array_length", 0) or 0)
    return bool(
        prop_type in {"ENUM", "STRING", "POINTER"}
        or subtype in {"COLOR", "COLOR_GAMMA", "FILE_PATH", "DIR_PATH"}
        or array_length > 1
        or len(str(label or "")) > 19
    )


def _fbp_effect_property_uses_slider(rig, prop_name, label):
    rna_prop = _fbp_effect_rna_property(rig, prop_name)
    if str(getattr(rna_prop, "type", "") or "") not in {"FLOAT", "INT"}:
        return False
    probe = f"{prop_name} {label}".lower()
    return any(
        word in probe
        for word in (
            "amount", "contrast", "despill", "factor", "falloff", "influence",
            "intensity", "opacity", "progress", "roughness", "softness",
            "strength", "threshold", "tolerance", "width",
        )
    )


def _fbp_draw_effect_property(layout, rig, definition, prop_name, labels=None):
    if not hasattr(rig, prop_name):
        return False
    label = _fbp_effect_property_label(definition, prop_name, labels)
    rna_prop = _fbp_effect_rna_property(rig, prop_name)
    is_bool = str(getattr(rna_prop, "type", "") or "") == "BOOLEAN"
    kwargs = {
        "text": label,
        "icon": _fbp_effect_property_icon(prop_name, label),
    }
    if is_bool:
        kwargs["toggle"] = True
    elif _fbp_effect_property_uses_slider(rig, prop_name, label):
        kwargs["slider"] = True
    layout.prop(rig, prop_name, **kwargs)
    return True


def _fbp_draw_compact_effect_properties(layout, rig, definition, prop_names, labels=None):
    """Draw scalar controls two per row while preserving wide/color controls."""
    pending = []

    def flush_pending():
        nonlocal pending
        while len(pending) >= 2:
            first, second = pending[:2]
            pending = pending[2:]
            row = layout.row(align=False)
            split = row.split(factor=0.5, align=False)
            left = split.column(align=False)
            right = split.column(align=False)
            _fbp_draw_effect_property(left, rig, definition, first, labels)
            _fbp_draw_effect_property(right, rig, definition, second, labels)
        if pending:
            prop_name = pending.pop(0)
            _fbp_draw_effect_property(layout, rig, definition, prop_name, labels)

    for prop_name in prop_names:
        if not hasattr(rig, prop_name):
            continue
        label = _fbp_effect_property_label(definition, prop_name, labels)
        if _fbp_effect_property_full_width(rig, prop_name, label):
            flush_pending()
            _fbp_draw_effect_property(layout, rig, definition, prop_name, labels)
        else:
            pending.append(prop_name)
            if len(pending) == 2:
                flush_pending()
    flush_pending()


_FBP_EFFECT_UI_GROUPS = {
    FBP_EFFECT_MESH_WIGGLE: (
        ("Quality", "MOD_SUBSURF", ("fbp_mesh_wiggle_subdivisions", "fbp_mesh_wiggle_shade_smooth")),
        ("Motion", "MOD_NOISE", ("fbp_mesh_wiggle_strength", "fbp_mesh_wiggle_speed", "fbp_mesh_wiggle_hold", "fbp_mesh_wiggle_w")),
        ("Noise", "RNDCURVE", ("fbp_mesh_wiggle_noise_scale", "fbp_mesh_wiggle_detail")),
    ),
    FBP_EFFECT_FELT_FUZZ: (
        ("Quality", "MOD_SUBSURF", ("fbp_felt_render_density", "fbp_felt_viewport_percentage", "fbp_felt_subdivisions", "fbp_felt_alpha_resolution")),
        ("Fuzz", "MODIFIER", ("fbp_felt_fuzz_length", "fbp_felt_fuzz_radius", "fbp_felt_curl_amount", "fbp_felt_alpha_threshold")),
    ),
    FBP_EFFECT_SHADOW: (
        ("Shadow", "SHADING_RENDERED", ("fbp_shadow_mode", "fbp_shadow_blend_mode", "fbp_shadow_color", "fbp_shadow_opacity")),
        ("Position & Softness", "UV", ("fbp_shadow_offset_x", "fbp_shadow_offset_y", "fbp_shadow_blur")),
    ),
    FBP_EFFECT_DIGITAL_NOISE: (
        ("Noise", "RNDCURVE", ("fbp_digital_noise_luma", "fbp_digital_noise_chroma", "fbp_digital_noise_scale", "fbp_digital_noise_shadow_bias")),
        ("Animation", "TIME", ("fbp_digital_noise_seed",)),
    ),
    FBP_EFFECT_SWIRL: (
        ("Center", "EMPTY_ARROWS", ("fbp_swirl_center_x", "fbp_swirl_center_y")),
        ("Distortion", "FORCE_VORTEX", ("fbp_swirl_radius", "fbp_swirl_angle", "fbp_swirl_factor")),
    ),
    FBP_EFFECT_BULGE_PINCH: (
        ("Center", "EMPTY_ARROWS", ("fbp_bulge_pinch_center_x", "fbp_bulge_pinch_center_y")),
        ("Distortion", "MOD_SIMPLEDEFORM", ("fbp_bulge_pinch_radius", "fbp_bulge_pinch_strength", "fbp_bulge_pinch_factor")),
    ),
    FBP_EFFECT_LENS_WARP: (
        ("Optical Center", "EMPTY_ARROWS", ("fbp_lens_warp_center_x", "fbp_lens_warp_center_y")),
        ("Lens", "CAMERA_DATA", ("fbp_lens_warp_distortion", "fbp_lens_warp_zoom", "fbp_lens_warp_factor")),
    ),
    FBP_EFFECT_WAVE_WARP: (
        ("Wave", "MOD_WAVE", ("fbp_wave_warp_amplitude", "fbp_wave_warp_frequency", "fbp_wave_warp_phase", "fbp_wave_warp_speed")),
        ("Direction & Mix", "ORIENTATION_GLOBAL", ("fbp_wave_warp_angle", "fbp_wave_warp_factor")),
    ),
    FBP_EFFECT_RIPPLE_DISTORTION: (
        ("Center", "EMPTY_ARROWS", ("fbp_ripple_distortion_center_x", "fbp_ripple_distortion_center_y")),
        ("Ripple", "MOD_WAVE", ("fbp_ripple_distortion_amplitude", "fbp_ripple_distortion_frequency", "fbp_ripple_distortion_phase")),
        ("Area & Mix", "DRIVER_DISTANCE", ("fbp_ripple_distortion_radius", "fbp_ripple_distortion_falloff", "fbp_ripple_distortion_factor")),
    ),
    FBP_EFFECT_KALEIDOSCOPE: (
        ("Center", "EMPTY_ARROWS", ("fbp_kaleidoscope_center_x", "fbp_kaleidoscope_center_y")),
        ("Mirrors", "MOD_MIRROR", ("fbp_kaleidoscope_segments", "fbp_kaleidoscope_rotation", "fbp_kaleidoscope_factor")),
    ),
    FBP_EFFECT_HEX_PIXELATE: (
        ("Grid", "ALIASED", ("fbp_hex_pixelate_cells_x", "fbp_hex_pixelate_cells_y", "fbp_hex_pixelate_rotation")),
        ("Mix", "MODIFIER", ("fbp_hex_pixelate_factor",)),
    ),
    FBP_EFFECT_MOSAIC_JITTER: (
        ("Grid", "ALIASED", ("fbp_mosaic_jitter_cells_x", "fbp_mosaic_jitter_cells_y", "fbp_mosaic_jitter_rotation")),
        ("Jitter", "RNDCURVE", ("fbp_mosaic_jitter_amount", "fbp_mosaic_jitter_offset_x", "fbp_mosaic_jitter_offset_y", "fbp_mosaic_jitter_seed")),
        ("Mix", "MODIFIER", ("fbp_mosaic_jitter_factor",)),
    ),
    FBP_EFFECT_TRIANGLE_BLUR: (
        ("Blur Quality", "MOD_SMOOTH", ("fbp_triangle_blur_radius", "fbp_triangle_blur_samples")),
        ("Mix", "MODIFIER", ("fbp_triangle_blur_factor",)),
    ),
    FBP_EFFECT_TILT_SHIFT: (
        ("Focus Band", "CAMERA_DATA", ("fbp_tilt_shift_position", "fbp_tilt_shift_width", "fbp_tilt_shift_angle")),
        ("Blur", "MOD_SMOOTH", ("fbp_tilt_shift_radius", "fbp_tilt_shift_factor")),
    ),
    FBP_EFFECT_UNSHARP_MASK: (
        ("Detail", "SHARPCURVE", ("fbp_unsharp_radius", "fbp_unsharp_amount")),
        ("Mix", "MODIFIER", ("fbp_unsharp_factor",)),
    ),
    FBP_EFFECT_EDGE_DETECT: (
        ("Lines", "MOD_LINEART", ("fbp_edge_detect_width", "fbp_edge_detect_strength", "fbp_edge_detect_threshold", "fbp_edge_detect_softness")),
        ("Color & Mix", "COLOR", ("fbp_edge_detect_color", "fbp_edge_detect_factor")),
    ),
    FBP_EFFECT_SMOOTH_TOON: (
        ("Stylization", "SHADING_RENDERED", ("fbp_smooth_toon_levels", "fbp_smooth_toon_softness", "fbp_smooth_toon_factor")),
    ),
    FBP_EFFECT_ADAPTIVE_THRESHOLD: (
        ("Local Threshold", "MOD_MASK", ("fbp_adaptive_threshold_radius", "fbp_adaptive_threshold_offset", "fbp_adaptive_threshold_softness", "fbp_adaptive_threshold_invert")),
        ("Mix", "MODIFIER", ("fbp_adaptive_threshold_factor",)),
    ),
    FBP_EFFECT_FALSE_COLOR: (
        ("Palette", "COLOR", ("fbp_false_color_dark", "fbp_false_color_light")),
        ("Mix", "MODIFIER", ("fbp_false_color_factor",)),
    ),
    FBP_EFFECT_CHROMATIC_ABERRATION: (
        ("Chromatic Offset", "SEQ_CHROMA_SCOPE", ("fbp_chromatic_aberration_distance", "fbp_chromatic_aberration_angle")),
        ("Mix", "MODIFIER", ("fbp_chromatic_aberration_factor",)),
    ),
    FBP_EFFECT_INK: (
        ("Line Extraction", "GREASEPENCIL", ("fbp_ink_width", "fbp_ink_threshold", "fbp_ink_softness", "fbp_ink_strength")),
        ("Palette", "COLOR", ("fbp_ink_color", "fbp_ink_paper_color", "fbp_ink_preserve_color", "fbp_ink_factor")),
    ),
    FBP_EFFECT_EDGE_WORK: (
        ("Lines", "MOD_LINEART", ("fbp_edge_work_radius", "fbp_edge_work_thickness", "fbp_edge_work_strength", "fbp_edge_work_threshold", "fbp_edge_work_softness")),
        ("Color & Mix", "COLOR", ("fbp_edge_work_color", "fbp_edge_work_factor")),
    ),
    FBP_EFFECT_PENCIL_SKETCH: (
        ("Drawing", "BRUSH_DATA", ("fbp_pencil_sketch_radius", "fbp_pencil_sketch_contrast")),
        ("Palette", "COLOR", ("fbp_pencil_sketch_graphite", "fbp_pencil_sketch_paper", "fbp_pencil_sketch_color_amount", "fbp_pencil_sketch_factor")),
    ),
    FBP_EFFECT_POSTER_EDGES: (
        ("Posterization", "IMAGE_DATA", ("fbp_poster_edges_levels", "fbp_poster_edges_softness")),
        ("Edges", "MOD_LINEART", ("fbp_poster_edges_width", "fbp_poster_edges_strength", "fbp_poster_edges_threshold")),
        ("Color & Mix", "COLOR", ("fbp_poster_edges_color", "fbp_poster_edges_factor")),
    ),
    FBP_EFFECT_CROSSHATCH: (
        ("Pattern", "MOD_LINEART", ("fbp_crosshatch_scale", "fbp_crosshatch_rotation", "fbp_crosshatch_line_width", "fbp_crosshatch_levels")),
        ("Palette", "COLOR", ("fbp_crosshatch_ink", "fbp_crosshatch_paper", "fbp_crosshatch_preserve_color", "fbp_crosshatch_factor")),
    ),
    FBP_EFFECT_EMBOSS: (
        ("Relief", "NORMALS_FACE", ("fbp_emboss_angle", "fbp_emboss_distance", "fbp_emboss_strength", "fbp_emboss_bias")),
        ("Color & Mix", "COLOR", ("fbp_emboss_color_amount", "fbp_emboss_factor")),
    ),
}


_FBP_CONTEXTUAL_EFFECT_SETTINGS = frozenset({
    FBP_EFFECT_PIXELATE,
    FBP_EFFECT_DEPTH_BLUR,
    FBP_EFFECT_ALPHA_MATTE,
    FBP_EFFECT_LUMA_MATTE,
    FBP_EFFECT_SQUARE_MASK,
    FBP_EFFECT_CIRCLE_MASK,
    FBP_EFFECT_TRIANGLE_MASK,
    FBP_EFFECT_CLIPPING_MASK,
    FBP_EFFECT_IMPORTED_MASK,
    FBP_EFFECT_LAYER_BLEND,
    FBP_EFFECT_GAUSSIAN_BLUR,
    FBP_EFFECT_DIRECTIONAL_BLUR,
    FBP_EFFECT_HALFTONE,
    FBP_EFFECT_DOT_MATRIX,
    FBP_EFFECT_ASCII_MATRIX,
    FBP_EFFECT_ASCII,
    FBP_EFFECT_TEXT_MATRIX,
    FBP_EFFECT_THICKNESS,
})


def fbp_effect_settings_ui_issues():
    """Return static settings-panel contract issues for diagnostics and tests."""
    issues = []
    for effect_id, definition in FBP_EFFECT_REGISTRY.items():
        if bool(definition.get("hidden", False)) or bool(definition.get("custom", False)):
            continue
        property_map = dict(definition.get("property_map", {}))
        if not property_map:
            issues.append(f"{effect_id}: no editable properties registered")

    for effect_id, groups in _FBP_EFFECT_UI_GROUPS.items():
        definition = FBP_EFFECT_REGISTRY.get(effect_id)
        if not definition:
            issues.append(f"{effect_id}: UI groups reference an unknown effect")
            continue
        registered = set(dict(definition.get("property_map", {})))
        grouped = []
        for _title, _icon, properties in groups:
            grouped.extend(properties)
        unknown = sorted(set(grouped) - registered)
        duplicates = sorted(
            name for name in set(grouped) if grouped.count(name) > 1
        )
        if unknown:
            issues.append(
                f"{effect_id}: unknown grouped properties {', '.join(unknown)}"
            )
        if duplicates:
            issues.append(
                f"{effect_id}: duplicated grouped properties {', '.join(duplicates)}"
            )

    for effect_id in _FBP_CONTEXTUAL_EFFECT_SETTINGS:
        if effect_id not in FBP_EFFECT_REGISTRY:
            issues.append(f"{effect_id}: contextual UI references an unknown effect")
    return tuple(issues)


FBP_EFFECT_SETTINGS_UI_ISSUES = fbp_effect_settings_ui_issues()


def _fbp_effect_control_hidden_properties(rig, effect_id):
    """Properties represented by the active viewport helper instead of sliders."""
    if not bool(getattr(rig, "fbp_effect_controls_enabled", True)):
        return frozenset()
    try:
        from .effect_controls import effect_control_driven_properties
        return effect_control_driven_properties(effect_id)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return frozenset()


def _fbp_draw_registered_effect_properties(layout, rig, effect_id, definition, labels=None, skip=()):
    """Draw every registered editable property and return the number exposed.

    New effects use this path automatically. Dedicated contextual panels must be
    explicitly listed elsewhere, preventing a registry entry from silently
    appearing without settings when a new effect is added.
    """
    skip_names = set(skip or ())
    skip_names.update(_fbp_effect_control_hidden_properties(rig, effect_id))
    property_names = [
        name for name in dict((definition or {}).get("property_map", {}))
        if name not in skip_names and hasattr(rig, name)
    ]
    if not property_names:
        return 0

    remaining = list(property_names)
    groups = _FBP_EFFECT_UI_GROUPS.get(effect_id, ())
    for title, icon, group_names in groups:
        visible = [name for name in group_names if name in remaining]
        if not visible:
            continue
        section = layout.row(align=False)
        section.label(text=title, icon=icon)
        _fbp_draw_compact_effect_properties(
            layout, rig, definition, visible, labels
        )
        for name in visible:
            if name in remaining:
                remaining.remove(name)
        if remaining:
            layout.separator(factor=0.25)

    if remaining:
        if groups:
            section = layout.row(align=False)
            section.label(text="Additional Settings", icon="OPTIONS")
        _fbp_draw_compact_effect_properties(
            layout, rig, definition, remaining, labels
        )
    return len(property_names)


def _fbp_draw_toggle_strip(layout, rig, controls):
    """Draw related Boolean options as one compact icon-assisted row."""
    available = [item for item in controls if hasattr(rig, item[0])]
    if not available:
        return None
    row = layout.row(align=True)
    for prop_name, label, icon in available:
        row.prop(
            rig,
            prop_name,
            text=label,
            icon=icon,
            toggle=True,
        )
    return row


def _fbp_draw_effect_section(layout, title, icon="OPTIONS", *, separator=False):
    """Draw one lightweight section label without nesting another box."""
    if separator:
        layout.separator(factor=0.35)
    row = layout.row(align=False)
    row.label(text=str(title or "Settings"), icon=str(icon or "OPTIONS"))
    return row


def _fbp_draw_quality_triplet(
    layout,
    rig,
    *,
    title,
    icon,
    viewport_prop,
    playback_prop,
    render_prop,
):
    """Draw View/Play/Render quality controls as one compact icon row."""
    available = [
        (viewport_prop, "View", "HIDE_OFF"),
        (playback_prop, "Play", "PLAY"),
        (render_prop, "Render", "RESTRICT_RENDER_OFF"),
    ]
    available = [item for item in available if item[0] and hasattr(rig, item[0])]
    if not available:
        return None
    _fbp_draw_effect_section(layout, title, icon)
    row = layout.row(align=True)
    for prop_name, label, prop_icon in available:
        row.prop(rig, prop_name, text=label, icon=prop_icon)
    return row


def _fbp_draw_uv_transform(layout, rig, definition, prefix, *, title="UV Transform"):
    """Draw a repeated UV offset/scale/rotation group consistently."""
    names = (
        f"{prefix}_uv_offset_x",
        f"{prefix}_uv_offset_y",
        f"{prefix}_uv_scale_x",
        f"{prefix}_uv_scale_y",
        f"{prefix}_uv_rotation",
    )
    visible = [name for name in names if hasattr(rig, name)]
    if not visible:
        return None
    _fbp_draw_effect_section(layout, title, "UV", separator=True)
    _fbp_draw_compact_effect_properties(layout, rig, definition, visible)
    return True

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
                            text=_fbp_clean_effect_ui_label(
                                name, effect_id=effect_id, fallback="Input"
                            ),
                            icon=_fbp_effect_property_icon(name, name),
                        )
                        drawn += 1
                except FBP_DATA_ERRORS:
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
                    controls.prop(
                        socket,
                        "default_value",
                        text=_fbp_clean_effect_ui_label(
                            name, effect_id=effect_id, fallback="Input"
                        ),
                        icon=_fbp_effect_property_icon(name, name),
                    )
                    drawn += 1
                except FBP_DATA_ERRORS:
                    continue
    if not drawn:
        controls.label(text="No editable value sockets exposed", icon="INFO")
    return drawn


def _fbp_draw_matrix_character_preview(layout, characters):
    """Show the exact active light-to-dense glyph ramp in a compact block."""
    characters = str(characters or " ")
    preview = layout.box()
    header = preview.row(align=False)
    header.label(text="Character Ramp", icon="FONT_DATA")
    header.label(text="Light → Dense")
    visible = characters.replace(" ", "␠")
    for start in range(0, len(visible), 24):
        row = preview.row(align=False)
        row.alignment = "CENTER"
        row.label(text=visible[start:start + 24])


def fbp_effect_color_ramp_node(rig, effect_id):
    """Return the native editable Color Ramp owned by one rig effect."""
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    role = str(definition.get("color_ramp_role", "") or "")
    if not role:
        return None
    for effect_node in _fbp_find_shader_effect_nodes_for_rig(rig, effect_id):
        node_group = getattr(effect_node, "node_tree", None)
        if not node_group:
            continue
        for node in node_group.nodes:
            try:
                if (
                    getattr(node, "type", "") == "VALTORGB"
                    and bool(node.get("fbp_effect_color_ramp", False))
                    and str(node.get("fbp_effect_ramp_role", "") or "") == role
                ):
                    return node
            except FBP_DATA_ERRORS:
                continue
    return None

def fbp_effect_curve_node(rig, effect_id):
    """Return the native RGB Curves node owned by one private effect group."""
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    role = str(definition.get("curve_mapping_role", "") or "")
    if not role:
        return None
    for effect_node in _fbp_find_shader_effect_nodes_for_rig(rig, effect_id):
        node_group = getattr(effect_node, "node_tree", None)
        if not node_group:
            continue
        for node in node_group.nodes:
            try:
                if (
                    getattr(node, "type", "") == "CURVE_RGB"
                    and bool(node.get("fbp_effect_curve_mapping", False))
                    and str(node.get("fbp_effect_curve_role", "") or "") == role
                ):
                    return node
            except FBP_DATA_ERRORS:
                continue
    return None


def fbp_draw_effect_settings(layout, rig, effect_id, selected_count=1, present_count=None):
    definition = fbp_effect_definition(effect_id)
    if not definition:
        return
    box = layout.box()
    header = box.row(align=False)
    header_split = header.split(factor=0.68, align=False)
    header_left = header_split.row(align=True)
    header_left.alignment = 'LEFT'
    header_left.label(
        text=_fbp_effect_display_label(effect_id, definition),
        icon=str(definition.get("icon", "MODIFIER")),
    )
    if present_count is None:
        present_count = selected_count

    header_right = header_split.row(align=True)
    header_right.alignment = 'RIGHT'
    partial_selection = bool(
        int(selected_count or 0) > 1
        and 0 < int(present_count or 0) < int(selected_count or 0)
    )
    if partial_selection:
        duplicate_op = header_right.operator(
            "fbp.copy_effect_to_selected",
            text="",
            icon="DUPLICATE",
            emboss=False,
        )
        duplicate_op.effect_id = effect_id
        header_right.separator(factor=0.25)

    order_warning = fbp_effect_order_warning(rig, effect_id)
    if str(definition.get("performance", "")).upper() in {"HEAVY", "VERY_HEAVY"}:
        warning = header_right.row(align=True)
        warning.alert = True
        op = warning.operator(
            "fbp.effect_header_warning", text="", icon="ERROR", emboss=False
        )
        op.effect_id = effect_id
        op.message = "Heavy effect: may reduce viewport playback performance"
        op.fix_order = False
        header_right.separator(factor=0.25)
    if order_warning:
        order = header_right.row(align=True)
        order.alert = True
        op = order.operator(
            "fbp.effect_header_warning",
            text="",
            icon="SEQ_STRIP_MODIFIER",
            emboss=False,
        )
        op.effect_id = effect_id
        op.message = order_warning
        op.fix_order = True
        header_right.separator(factor=0.25)

    presets = header_right.operator(
        "fbp.open_effect_presets", text="", icon="PRESET", emboss=False
    )
    presets.effect_id = effect_id
    header_right.separator(factor=0.25)
    reset = header_right.operator(
        "fbp.reset_active_effect", text="", icon="FILE_REFRESH", emboss=False
    )
    reset.effect_id = effect_id

    family_id = fbp_effect_family_id(effect_id)
    if family_id:
        family = fbp_effect_family_definition(family_id)
        variant = box.row(align=False)
        variant.label(text=str(family.get("label", "Effect") or "Effect"), icon="DOWNARROW_HLT")
        variant.menu(
            "FBP_MT_effect_family_variants",
            text=fbp_effect_variant_label(effect_id),
        )
        active_family_members = [
            variant_id for variant_id, _label in tuple(family.get("variants", ()) or ())
            if fbp_effect_is_active(rig, variant_id)
        ]
        if len(active_family_members) > 1:
            family_warning = box.row(align=False)
            family_warning.alert = True
            family_warning.label(
                text=f"Legacy stack: {len(active_family_members)} {family.get('label', 'effect')} variants are active",
                icon="ERROR",
            )

    try:
        from .effect_controls import effect_has_controls
        if effect_has_controls(effect_id):
            controls = box.row(align=True)
            controls.prop(
                rig, "fbp_effect_controls_enabled", text="Viewport Control",
                toggle=True, icon="EMPTY_ARROWS",
            )
            select_control = controls.operator(
                "fbp.select_effect_control", text="", icon="RESTRICT_SELECT_OFF"
            )
            select_control.effect_id = effect_id
            reset_control = controls.operator(
                "fbp.reset_effect_control", text="", icon="LOOP_BACK"
            )
            reset_control.effect_id = effect_id
            if effect_id in {FBP_EFFECT_GRADIENT_MASK, FBP_EFFECT_GRADIENT_LIGHT, FBP_EFFECT_TILT_SHIFT}:
                control_hint = box.row(align=False)
                control_hint.enabled = False
                control_hint.label(
                    text="Yellow: move / rotate / resize · Blue and Orange: edit boundaries",
                    icon="INFO",
                )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

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
        if (
            current_debug != "FINAL"
            and _fbp_effect_is_local_mask(effect_id)
            and fbp_effect_mask_target(rig, effect_id) != "LAYER"
        ):
            preview_hint = box.row(align=False)
            preview_hint.alert = True
            preview_hint.label(
                text="Mask preview temporarily replaces the layer color",
                icon="INFO",
            )
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
    # Registry metadata is the single source of truth for visible parameter
    # names. Keep this table intentionally tiny and only for wording that adds
    # context not represented by the shared effect definition.
    labels = {
        "fbp_infinite_rotation_offset": "Offset (°)",
        "fbp_wind_falloff": "Pinned Falloff",
    }
    if effect_id in {FBP_EFFECT_RECOLOR, FBP_EFFECT_GRADIENT_LIGHT}:
        ramp_node = fbp_effect_color_ramp_node(rig, effect_id)
        ramp_box = box.box()
        ramp_box.label(text="Color Ramp", icon="COLOR")
        if ramp_node is not None:
            ramp_box.template_color_ramp(ramp_node, "color_ramp", expand=True)
            if int(selected_count or 0) > 1 and int(present_count or 0) == int(selected_count or 0):
                _fbp_schedule_effect_color_ramp_sync(
                    rig, effect_id, _fbp_selected_rigs(getattr(bpy, "context", None))
                )
        else:
            ramp_box.label(text="Color Ramp unavailable — refresh the effect", icon="ERROR")
    if effect_id == FBP_EFFECT_CURVES:
        curve_node = fbp_effect_curve_node(rig, effect_id)
        curve_box = box.box()
        curve_box.label(text="RGB Curves", icon="FORCE_HARMONIC")
        if curve_node is not None:
            curve_box.template_curve_mapping(curve_node, "mapping", type='COLOR')
            if int(selected_count or 1) > 1:
                curve_box.label(text="Curve edits affect the active layer", icon="INFO")
        else:
            curve_box.label(text="RGB Curves unavailable — refresh the effect", icon="ERROR")
    if effect_id == FBP_EFFECT_SHADOW:
        _fbp_draw_registered_effect_properties(
            box, rig, effect_id, definition, labels
        )
        if str(getattr(rig, "fbp_shadow_mode", "OUTER") or "OUTER") == "OUTER":
            canvas = box.row(align=False)
            canvas.operator(
                "fbp.fit_shadow_canvas",
                text="Fit Transparent Canvas",
                icon="FULLSCREEN_ENTER",
            )
            extend_mode = str(getattr(rig, "fbp_extend_mode", "EDGE") or "EDGE")
            padding = max(
                float(getattr(rig, "fbp_extend_left", 0.0) or 0.0),
                float(getattr(rig, "fbp_extend_right", 0.0) or 0.0),
                float(getattr(rig, "fbp_extend_top", 0.0) or 0.0),
                float(getattr(rig, "fbp_extend_bottom", 0.0) or 0.0),
            )
            if extend_mode != "TRANSPARENT" or padding <= 1e-6:
                hint = box.row(align=False)
                hint.enabled = False
                hint.label(
                    text="Outer shadows need transparent border geometry when they reach the plane edge",
                    icon="INFO",
                )
    elif effect_id == FBP_EFFECT_LATTICE:
        _fbp_draw_effect_property(box, rig, definition, "fbp_lattice_mode", labels)
        helper = _fbp_lattice_object(rig)
        lattice_mode = _fbp_lattice_mode(rig)
        rig_name = str(getattr(rig, "name", "") or "")
        plane = _fbp_plane(rig, repair=False)
        lattice_ready = _fbp_lattice_contract_is_valid(
            rig, plane, helper, _fbp_lattice_modifier(plane)
        )
        repairing = bool(
            not lattice_ready
            and _fbp_schedule_lattice_contract_repair(rig, first_interval=0.01)
        )
        ui_context = getattr(bpy, "context", None)
        active_object = getattr(ui_context, "object", None) if ui_context is not None else None
        cage_selected = bool(helper is not None and active_object is helper)
        cage_editing = bool(
            cage_selected and str(getattr(ui_context, "mode", "") or "").startswith("EDIT")
        )
        camera = _fbp_lattice_scene_camera(getattr(bpy.context, "scene", None))
        camera_valid = bool(
            camera is not None
            and str(getattr(getattr(camera, "data", None), "type", "") or "") in {"PERSP", "ORTHO"}
        )

        status_row = box.row(align=False)
        status_row.alert = bool(not lattice_ready and not repairing)
        status_row.label(
            text=(
                "Editing cage"
                if cage_editing
                else ("Cage ready" if lattice_ready else ("Repairing cage…" if repairing else "Cage missing or incomplete"))
            ),
            icon=(
                "EDITMODE_HLT"
                if cage_editing
                else ("CHECKMARK" if lattice_ready else ("FILE_REFRESH" if repairing else "ERROR"))
            ),
        )
        if not lattice_ready and not repairing:
            status_row.label(text="Use Reset in the effect header to rebuild it", icon="INFO")
        last_error = _fbp_last_lattice_error(rig)
        if last_error and not lattice_ready and not repairing:
            error_row = box.row(align=False)
            error_row.alert = True
            ui_error = last_error if len(last_error) <= 110 else last_error[:107].rstrip() + "..."
            error_row.label(text=ui_error, icon="INFO")

        cage_row = box.row(align=False)
        _fbp_draw_effect_property(cage_row, rig, definition, "fbp_lattice_show_cage", labels)
        select_part = cage_row.row(align=False)
        select_part.enabled = lattice_ready
        select_cage = select_part.operator(
            "fbp.select_lattice_helper", text="Select Cage", icon="RESTRICT_SELECT_OFF"
        )
        select_cage.rig_name = rig_name

        workflow_row = box.row(align=False)
        flatten_slot = workflow_row.row(align=False)
        flatten_slot.enabled = camera_valid
        if lattice_mode == "CAMERA_FLATTEN":
            flatten_slot.label(text="Camera Flatten active", icon="CAMERA_DATA")
        else:
            setup = flatten_slot.operator(
                "fbp.setup_lattice_camera_flatten",
                text="Set Up Camera Flatten",
                icon="CAMERA_DATA",
            )
            setup.rig_name = rig_name
        edit_slot = workflow_row.row(align=False)
        edit_slot.enabled = lattice_ready
        if cage_editing:
            done = edit_slot.operator(
                "fbp.finish_lattice_editing", text="Back to Plane", icon="CHECKMARK"
            )
            done.rig_name = rig_name
        else:
            edit = edit_slot.operator(
                "fbp.edit_lattice_helper", text="Edit Cage", icon="EDITMODE_HLT"
            )
            edit.rig_name = rig_name
        if not camera_valid and lattice_mode != "CAMERA_FLATTEN":
            no_camera = box.row(align=False)
            no_camera.enabled = False
            no_camera.label(
                text="Camera Flatten is unavailable until the Scene has an active camera",
                icon="CAMERA_DATA",
            )

        def _draw_lattice_grid_controls(target, *, title="Planar Cage"):
            loops_u, loops_v = _fbp_lattice_grid_loops(rig)
            grid_box = target.box()
            title_row = grid_box.row(align=False)
            title_row.label(text=title, icon="MOD_LATTICE")
            if loops_u == 0 and loops_v == 0:
                title_row.label(text="Corners only", icon="MESH_GRID")
            else:
                title_row.label(
                    text=f"{loops_u} × {loops_v} internal loops",
                    icon="MESH_GRID",
                )
            _fbp_draw_effect_property(
                grid_box, rig, definition, "fbp_lattice_grid_preset", labels
            )
            try:
                grid_preset = str(
                    getattr(rig, "fbp_lattice_grid_preset", "LOOPS_2") or "LOOPS_2"
                ).upper()
            except FBP_DATA_ERRORS:
                grid_preset = "LOOPS_2"
            if grid_preset == "CUSTOM":
                custom = grid_box.row(align=True)
                custom.prop(rig, "fbp_lattice_custom_loops_u", text="X")
                linked = bool(getattr(rig, "fbp_lattice_link_loops", True))
                custom.prop(
                    rig,
                    "fbp_lattice_link_loops",
                    text="",
                    icon="LINKED" if linked else "UNLINKED",
                    toggle=True,
                )
                custom.prop(rig, "fbp_lattice_custom_loops_v", text="Y")
                hint = grid_box.row(align=False)
                hint.enabled = False
                hint.label(
                    text="Values count internal loops; the four corner points are added automatically",
                    icon="INFO",
                )
            _fbp_draw_effect_property(
                grid_box, rig, definition, "fbp_lattice_interpolation", labels
            )

            mesh_box = grid_box.box()
            mesh_box.label(text="Deformed Mesh", icon="MOD_SUBSURF")
            _fbp_draw_effect_property(
                mesh_box, rig, definition, "fbp_lattice_mesh_detail_mode", labels
            )
            if _fbp_lattice_mesh_detail_mode(rig) == "AUTO":
                _fbp_draw_effect_property(
                    mesh_box, rig, definition, "fbp_lattice_mesh_density", labels
                )
                segments = _fbp_lattice_mesh_segment_count(rig)
                estimate = mesh_box.row(align=False)
                estimate.enabled = False
                estimate.label(
                    text=f"Approx. {segments} × {segments} deformable faces",
                    icon="MESH_GRID",
                )
            else:
                _fbp_draw_effect_property(
                    mesh_box, rig, definition, "fbp_lattice_mesh_subdivisions", labels
                )
            reset_warning = grid_box.row(align=False)
            reset_warning.enabled = False
            reset_warning.label(
                text="Changing the Cage Grid rebuilds its topology and resets point edits",
                icon="INFO",
            )

        if lattice_mode == "CAMERA_FLATTEN":
            camera_box = box.box()
            camera_title = camera_box.row(align=False)
            camera_title.label(text="Camera Flatten", icon="CAMERA_DATA")
            camera_box.label(text="Pose or animate the layer in 3D, then preserve its camera appearance.", icon="KEYFRAME_HLT")
            controls = camera_box.column(align=False)
            controls.enabled = camera_valid
            _fbp_draw_effect_property(
                controls, rig, definition, "fbp_lattice_flatten_influence", labels
            )
            _fbp_draw_effect_property(
                controls, rig, definition, "fbp_lattice_live_update", labels
            )
            status = camera_box.row(align=False)
            if camera is None:
                status.alert = True
                status.label(text="Set an active Scene Camera", icon="ERROR")
            elif not camera_valid:
                status.alert = True
                status.label(text="Perspective and Orthographic cameras are supported", icon="ERROR")
            else:
                status.label(text=f"Camera: {camera.name}", icon="CAMERA_DATA")

            action_row = camera_box.row(align=False)
            action_row.enabled = camera_valid and lattice_ready
            update = action_row.operator(
                "fbp.update_lattice_flatten", text="Update", icon="FILE_REFRESH"
            )
            update.rig_name = rig_name
            bake = action_row.operator(
                "fbp.bake_lattice_flatten", text="Bake & Animate", icon="CHECKMARK"
            )
            bake.rig_name = rig_name
            freeze = action_row.operator(
                "fbp.freeze_lattice_flatten", text="Freeze & Edit", icon="EDITMODE_HLT"
            )
            freeze.rig_name = rig_name
            _draw_lattice_grid_controls(camera_box, title="Perspective Grid")
        else:
            baked = bool(helper and helper.get(_FBP_LATTICE_BAKED_KEY, False))
            if baked:
                baked_row = box.row(align=False)
                baked_row.label(
                    text="Perspective baked: the correction now follows local layer animation",
                    icon="CHECKMARK",
                )
            _draw_lattice_grid_controls(box, title="Planar Cage")
    elif effect_id == FBP_EFFECT_CAMERA_BILLBOARD:
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_camera_billboard_mode", labels
        )
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            ("fbp_camera_billboard_flip", "fbp_camera_billboard_influence"),
            labels,
        )
        camera = _fbp_scene_camera(getattr(bpy.context, "scene", None))
        if not camera:
            box.label(text="Set an active scene camera to use this effect", icon="ERROR")
        elif not _fbp_track_to_camera_constraint(rig):
            box.label(text="Constraint missing — remove and add the effect again", icon="ERROR")
    elif effect_id == FBP_EFFECT_CAMERA_SCALE_LOCK:
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_camera_scale_lock_influence", labels
        )
        reference = box.row(align=True)
        _fbp_draw_effect_property(
            reference, rig, definition,
            "fbp_camera_scale_lock_reference_distance", labels,
        )
        reference.operator(
            "fbp.capture_camera_scale_reference", text="", icon="EYEDROPPER"
        )
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            (
                "fbp_camera_scale_lock_reference_lens",
                "fbp_camera_scale_lock_reference_sensor_width",
            ),
            labels,
        )
        camera = _fbp_scene_camera(getattr(bpy.context, "scene", None))
        if not camera:
            box.label(text="Set an active scene camera to use this effect", icon="ERROR")
    elif effect_id == FBP_EFFECT_CUTOUT_OUTLINE:
        _fbp_draw_quality_triplet(
            box,
            rig,
            title="Alpha Detail",
            icon="IMAGE_ALPHA",
            viewport_prop="fbp_cutout_outline_viewport_resolution",
            playback_prop="fbp_cutout_outline_playback_resolution",
            render_prop="fbp_cutout_outline_render_resolution",
        )
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            (
                "fbp_cutout_outline_show_image",
                "fbp_cutout_outline_width",
                "fbp_cutout_outline_offset",
                "fbp_cutout_outline_color",
                "fbp_cutout_outline_alpha_threshold",
                "fbp_cutout_outline_wiggle_amount",
                "fbp_cutout_outline_wiggle_scale",
                "fbp_cutout_outline_wiggle_phase",
            ),
            labels,
        )
        detail = int(getattr(rig, "fbp_cutout_outline_viewport_resolution", 0) or 0)
        if detail >= 7:
            warning = box.row()
            warning.alert = True
            warning.label(text="High alpha detail may slow interaction", icon="ERROR")
            warning.label(text="High viewport subdivisions may slow interaction", icon="ERROR")
            warning.label(text="High viewport subdivisions may slow playback", icon="ERROR")
    elif effect_id == FBP_EFFECT_WIND_BENDER:
        _fbp_draw_effect_property(box, rig, definition, "fbp_wind_subdivision", labels)
        _fbp_draw_effect_property(box, rig, definition, "fbp_wind_motion_mode", labels)
        motion_mode = str(getattr(rig, "fbp_wind_motion_mode", "SWAY") or "SWAY")
        motion = box.box()
        motion.label(text={"SWAY": "Sway", "FLOW": "Flowing Waves", "RIPPLE": "Ripple"}.get(motion_mode, "Mesh Motion"), icon="FORCE_WIND")
        if motion_mode == "SWAY":
            motion_props = ("fbp_wind_bend_amount", "fbp_wind_speed")
        else:
            motion_props = ("fbp_wind_wave_count", "fbp_wind_wave_amplitude", "fbp_wind_wave_speed")
        if motion_mode == "RIPPLE":
            _fbp_draw_effect_property(motion, rig, definition, "fbp_wind_ripple_direction", labels)
        for prop_name in motion_props:
            _fbp_draw_effect_property(motion, rig, definition, prop_name, labels)

        _fbp_draw_effect_section(box, "Pinning", "PINNED", separator=True)
        _fbp_draw_effect_property(box, rig, definition, "fbp_wind_pin_edge", labels)
        if str(getattr(rig, "fbp_wind_pin_edge", "LEFT") or "LEFT") == "VERTEX_GROUP":
            plane = _fbp_plane(rig)
            if plane is not None and hasattr(plane, "vertex_groups"):
                group_row = box.row(align=False)
                group_row.prop_search(
                    rig, "fbp_wind_pin_vertex_group", plane, "vertex_groups",
                    text=labels.get("fbp_wind_pin_vertex_group", "Vertex Group"),
                    icon="GROUP_VERTEX",
                )
            else:
                _fbp_draw_effect_property(box, rig, definition, "fbp_wind_pin_vertex_group", labels)
        _fbp_draw_compact_effect_properties(box, rig, definition, ("fbp_wind_pin_strength", "fbp_wind_falloff"), labels)

        _fbp_draw_effect_section(box, "Motion Space", "ORIENTATION_GLOBAL", separator=True)
        direction = box.row(align=True)
        direction.prop(rig, "fbp_wind_direction_space", text="Direction Space")
        direction.prop(rig, "fbp_wind_preview_falloff", text="", toggle=True, icon="HIDE_OFF")
        box.prop(rig, "fbp_wind_direction", text="Motion Direction")
        for prop_name in ("fbp_wind_stepped", "fbp_wind_phase", "fbp_wind_noise_scale", "fbp_wind_turbulence", "fbp_wind_gust_strength", "fbp_wind_reverse"):
            _fbp_draw_effect_property(box, rig, definition, prop_name, labels)
        if int(getattr(rig, "fbp_wind_subdivision", 0) or 0) >= 5:
            warning = box.row(); warning.alert = True
            warning.label(text="High subdivisions may slow viewport playback", icon="ERROR")

    elif effect_id == FBP_EFFECT_COLOR_MASK:
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            (
                "fbp_color_mask_color",
                "fbp_color_mask_tolerance",
                "fbp_color_mask_softness",
                "fbp_color_mask_factor",
                "fbp_color_mask_invert",
            ),
            labels,
        )
        box.label(
            text="Samples the original image or animated sequence color",
            icon="IMAGE_DATA",
        )
    elif effect_id == FBP_EFFECT_LUMINANCE_MASK:
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            (
                "fbp_luminance_mask_minimum",
                "fbp_luminance_mask_maximum",
                "fbp_luminance_mask_softness",
                "fbp_luminance_mask_factor",
                "fbp_luminance_mask_invert",
            ),
            labels,
        )
        box.label(
            text="Samples the original image or animated sequence luminance",
            icon="IMAGE_DATA",
        )
    elif effect_id == FBP_EFFECT_CHANNEL_MASK:
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            (
                "fbp_channel_mask_channel",
                "fbp_channel_mask_minimum",
                "fbp_channel_mask_maximum",
                "fbp_channel_mask_softness",
                "fbp_channel_mask_factor",
                "fbp_channel_mask_invert",
            ),
            labels,
        )
        box.label(
            text="Samples a selected channel from the original image or sequence",
            icon="IMAGE_DATA",
        )
    elif effect_id == FBP_EFFECT_GRADIENT_MASK:
        hidden = _fbp_effect_control_hidden_properties(rig, effect_id)
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            tuple(name for name in (
                "fbp_gradient_mask_type",
                "fbp_gradient_mask_center_x",
                "fbp_gradient_mask_center_y",
                "fbp_gradient_mask_scale",
                "fbp_gradient_mask_angle",
                "fbp_gradient_mask_position",
                "fbp_gradient_mask_feather",
                "fbp_gradient_mask_factor",
                "fbp_gradient_mask_invert",
            ) if name not in hidden),
            labels,
        )
    elif effect_id == FBP_EFFECT_NOISE_MASK:
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            (
                "fbp_noise_mask_scale",
                "fbp_noise_mask_detail",
                "fbp_noise_mask_roughness",
                "fbp_noise_mask_threshold",
                "fbp_noise_mask_softness",
                "fbp_noise_mask_factor",
                "fbp_noise_mask_invert",
            ),
            labels,
        )
    else:
        # Only effects with a dedicated contextual panel are excluded from
        # the registry-driven fallback. Every other effect automatically exposes
        # its property_map, including newly added variants.
        if effect_id not in _FBP_CONTEXTUAL_EFFECT_SETTINGS:
            skip = ("fbp_felt_seed",) if effect_id == FBP_EFFECT_FELT_FUZZ else ()
            drawn = _fbp_draw_registered_effect_properties(
                box, rig, effect_id, definition, labels, skip=skip
            )
            if drawn == 0:
                missing = box.row(align=False)
                missing.alert = True
                missing.label(
                    text="No editable settings are registered for this effect",
                    icon="ERROR",
                )
    if effect_id in {FBP_EFFECT_SQUARE_MASK, FBP_EFFECT_CIRCLE_MASK, FBP_EFFECT_TRIANGLE_MASK}:
        shape_data = {
            FBP_EFFECT_SQUARE_MASK: ("fbp_square_mask", "SQUARE", "Square"),
            FBP_EFFECT_CIRCLE_MASK: ("fbp_circle_mask", "CIRCLE", "Circle"),
            FBP_EFFECT_TRIANGLE_MASK: ("fbp_triangle_mask", "TRIANGLE", "Triangle"),
        }
        prefix, shape, label = shape_data[effect_id]
        helper = getattr(rig, f"{prefix}_object", None)
        row = box.row(align=True)
        row.label(
            text=getattr(helper, "name", "Missing Shape") if helper else "Missing Shape",
            icon="MESH_DATA" if helper else "ERROR",
        )
        if hasattr(rig, f"{prefix}_show_helper"):
            show_helper = bool(getattr(rig, f"{prefix}_show_helper", True))
            row.prop(
                rig, f"{prefix}_show_helper", text="",
                icon="HIDE_OFF" if show_helper else "HIDE_ON", toggle=True,
            )
        recreate = row.operator("fbp.recreate_object_mask_helper", text="", icon="FILE_REFRESH")
        recreate.rig_name = rig.name
        recreate.shape = shape
        if helper is None:
            warning = box.row()
            warning.alert = True
            warning.label(text="Mask shape is missing; use Refresh to recreate it", icon="ERROR")
        else:
            edit = box.operator("fbp.edit_object_mask_helper", text=f"Edit {label} Shape", icon="EDITMODE_HLT")
            edit.rig_name = rig.name
            edit.shape = shape
        row = box.row(align=True)
        row.prop(rig, f"{prefix}_factor", text="Factor", slider=True)
        row.prop(rig, f"{prefix}_invert", text="Invert", toggle=True, icon="ARROW_LEFTRIGHT")
        box.prop(rig, f"{prefix}_feather", text="Feather", slider=True)
        box.prop(rig, f"{prefix}_lock_to_plane", text="Lock 3D Movement", toggle=True, icon="LOCKED")
        box.prop(rig, f"{prefix}_follow_bounds", text="Follow Layer Bounds", toggle=True, icon="CON_FOLLOWPATH")
        box.label(text="Viewport-only wire helper; it hides when the layer is not selected", icon="HIDE_OFF")

    if effect_id == FBP_EFFECT_IMPORTED_MASK:
        mask_path = str(getattr(rig, "fbp_imported_mask_path", "") or "")
        row = box.row(align=True)
        row.prop(rig, "fbp_imported_mask_path", text="Mask Image")
        row = box.row(align=True)
        row.prop(rig, "fbp_imported_mask_factor", text="Factor", slider=True)
        row.prop(rig, "fbp_imported_mask_invert", text="Invert", toggle=True, icon="ARROW_LEFTRIGHT")
        if not mask_path or not os.path.isfile(bpy.path.abspath(mask_path)):
            warning = box.row()
            warning.alert = True
            warning.label(text="Imported mask image is missing", icon="ERROR")
        else:
            box.label(text="Raster mask transferred from the layered source", icon="IMAGE_ALPHA")

    if effect_id == FBP_EFFECT_LAYER_BLEND:
        source_rig = getattr(rig, "fbp_layer_blend_source", None)
        source_row = box.row(align=True)
        source_row.label(text="Blends with Layer Below", icon="NODE_MATERIAL")
        if source_rig is not None:
            select_source = source_row.operator(
                "fbp.select_layer_relation_source",
                text=getattr(source_rig, "name", "Source Layer"),
                icon="RESTRICT_SELECT_OFF",
            )
            select_source.rig_name = rig.name
            select_source.relation = 'BLEND'
        else:
            source_row.label(text="No layer below", icon="ERROR")
        box.prop(rig, "fbp_layer_blend_mode", text="Blend Mode")
        box.prop(rig, "fbp_layer_blend_factor", text="Factor", slider=True)
        relation_status, relation_message, relation_icon = fbp_layer_relation_status(
            rig, FBP_EFFECT_LAYER_BLEND
        )
        health = box.row(align=False)
        health.alert = relation_status not in {"OK", "DISABLED"}
        health.label(text=relation_message, icon=relation_icon)
        if relation_status != "OK":
            repair = health.operator(
                "fbp.repair_layer_relation", text="Repair", icon="FILE_REFRESH"
            )
            repair.rig_name = rig.name
            repair.relation = 'BLEND'
        if source_rig is None:
            warning = box.row()
            warning.alert = True
            warning.label(text="Move this layer above an image layer to provide the blend base", icon="ERROR")
        else:
            box.label(text="The base updates automatically when layers are reordered", icon="FILE_REFRESH")
        box.label(text="Pairwise transfer; complex multi-layer composites may differ from the source app", icon="INFO")

    if effect_id == FBP_EFFECT_CLIPPING_MASK:
        source_rig = getattr(rig, "fbp_clipping_mask_source", None)
        source_row = box.row(align=True)
        source_row.label(text="Clips to Layer Below", icon="MOD_MASK")
        if source_rig is not None:
            select_source = source_row.operator(
                "fbp.select_layer_relation_source",
                text=getattr(source_rig, "name", "Source Layer"),
                icon="RESTRICT_SELECT_OFF",
            )
            select_source.rig_name = rig.name
            select_source.relation = 'CLIPPING'
        else:
            source_row.label(text="No layer below", icon="ERROR")
        if source_rig is None:
            warning = box.row()
            warning.alert = True
            warning.label(text="Move this layer above an image layer to create a clipping source", icon="ERROR")
        else:
            _source_material, source_node = _fbp_material_image_node(source_rig)
            if source_node is None or getattr(source_node, "image", None) is None:
                warning = box.row()
                warning.alert = True
                warning.label(text="The layer below has no image alpha to sample", icon="ERROR")
            else:
                box.label(text="The source updates automatically when layers are reordered", icon="FILE_REFRESH")
        row = box.row(align=True)
        row.prop(rig, "fbp_clipping_mask_factor", text="Factor", slider=True)
        row.prop(rig, "fbp_clipping_mask_invert", text="Invert", toggle=True, icon="ARROW_LEFTRIGHT")
        relation_status, relation_message, relation_icon = fbp_layer_relation_status(
            rig, FBP_EFFECT_CLIPPING_MASK
        )
        health = box.row(align=False)
        health.alert = relation_status not in {"OK", "DISABLED"}
        health.label(text=relation_message, icon=relation_icon)
        if relation_status != "OK":
            repair = health.operator(
                "fbp.repair_layer_relation", text="Repair", icon="FILE_REFRESH"
            )
            repair.rig_name = rig.name
            repair.relation = 'CLIPPING'
        box.prop(rig, "fbp_clipping_mask_use_camera_projection", text="Camera Projection", toggle=True, icon="CAMERA_DATA")
        if not bool(getattr(rig, "fbp_clipping_mask_use_camera_projection", True)):
            box.prop(rig, "fbp_clipping_mask_use_source_transform", text="Follow Source Transform", toggle=True, icon="CON_FOLLOWPATH")
        if bool(getattr(rig, "fbp_clipping_mask_use_source_transform", False)) or bool(getattr(rig, "fbp_clipping_mask_use_camera_projection", True)):
            _fbp_draw_uv_transform(
                box,
                rig,
                definition,
                "fbp_clipping_mask",
                title="Clipping UV",
            )

    if effect_id in {FBP_EFFECT_ALPHA_MATTE, FBP_EFFECT_LUMA_MATTE}:
        is_luma = effect_id == FBP_EFFECT_LUMA_MATTE
        source_prop = "fbp_luma_matte_source" if is_luma else "fbp_alpha_matte_source"
        factor_prop = "fbp_luma_matte_factor" if is_luma else "fbp_alpha_matte_factor"
        invert_prop = "fbp_luma_matte_invert" if is_luma else "fbp_alpha_matte_invert"
        transform_prop = "fbp_luma_matte_use_source_transform" if is_luma else "fbp_alpha_matte_use_source_transform"
        box.prop(rig, source_prop, text="Source Layer", icon="OUTLINER_OB_IMAGE")
        source_rig = getattr(rig, source_prop, None)
        if source_rig is None:
            warning = box.row()
            warning.alert = True
            warning.label(text="Choose an image or sequence layer as the matte source", icon="ERROR")
        else:
            _source_material, source_node = _fbp_material_image_node(source_rig)
            if source_node is None or getattr(source_node, "image", None) is None:
                warning = box.row()
                warning.alert = True
                warning.label(text="The selected source has no image or sequence media", icon="ERROR")
            else:
                if bool(getattr(rig, transform_prop, False)):
                    box.label(text="Following source plane position, rotation and scale", icon="ORIENTATION_GLOBAL")
                else:
                    box.label(text="Sampled in normalized UV space", icon="UV")
        display_prop = "fbp_luma_matte_source_display" if is_luma else "fbp_alpha_matte_source_display"
        prefix = "fbp_luma_matte" if is_luma else "fbp_alpha_matte"
        if fbp_effect_debug_mode(rig, effect_id) != "FINAL":
            preview_warning = box.row()
            preview_warning.alert = True
            preview_warning.label(text="Diagnostic preview changes the layer alpha; restore Final before rendering", icon="INFO")
        box.prop(rig, display_prop, text="Source Display")
        box.prop(rig, transform_prop, text="Follow Source Transform", toggle=True, icon="CON_FOLLOWPATH")
        _fbp_draw_uv_transform(
            box,
            rig,
            definition,
            prefix,
            title="Matte UV",
        )
        row = box.row(align=True)
        row.prop(rig, factor_prop, text="Factor", slider=True)
        row.prop(rig, invert_prop, text="Invert", toggle=True, icon="ARROW_LEFTRIGHT")
        if is_luma:
            row = box.row(align=True)
            row.prop(rig, "fbp_luma_matte_threshold", text="Threshold", slider=True)
            row.prop(rig, "fbp_luma_matte_softness", text="Softness", slider=True)
        if not bool(getattr(rig, transform_prop, False)):
            box.label(text="Enable Follow Source Transform for spatial track mattes", icon="INFO")
    if _fbp_effect_is_local_mask(effect_id):
        mask_target = fbp_effect_mask_target(rig, effect_id)
        if mask_target != "LAYER":
            target_definition = fbp_effect_definition(mask_target)
            target_row = box.row(align=True)
            target_row.label(
                text=f"Limits {_fbp_effect_display_label(mask_target, target_definition)}",
                icon="CLIPUV_HLT",
            )
            open_masks = target_row.operator(
                "fbp.open_effect_masks", text="", icon="PREFERENCES", emboss=False
            )
            open_masks.effect_id = mask_target
        else:
            box.label(text="Applies to the complete layer alpha", icon="IMAGE_ALPHA")

    assigned_masks = fbp_masks_targeting_effect(rig, effect_id)
    open_mask_editor = fbp_normalize_effect_id(
        getattr(getattr(bpy.context, "scene", None), "fbp_effect_mask_edit_target", "") or ""
    )
    if assigned_masks and open_mask_editor != effect_id:
        local_box = box.box()
        local_box.label(text="Effect Masks", icon="MOD_MASK")
        for mask_id in assigned_masks:
            mask_definition = fbp_effect_definition(mask_id)
            row = local_box.row(align=True)
            row.label(
                text=_fbp_effect_display_label(mask_id, mask_definition, fallback="Mask"),
                icon=str(mask_definition.get("icon", "MOD_MASK") or "MOD_MASK"),
            )
            clear = row.operator("fbp.set_effect_mask_target", text="", icon="X")
            clear.mask_effect_id = mask_id
            clear.target_effect_id = "LAYER"
            clear.expected_target_effect_id = effect_id

    if effect_id == FBP_EFFECT_GAUSSIAN_BLUR:
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            ("fbp_gaussian_blur_radius_x", "fbp_gaussian_blur_radius_y", "fbp_gaussian_blur_factor"),
            labels,
        )
        box.label(text="Gaussian-weighted alpha-safe sampling", icon="IMAGE_ALPHA")
    if effect_id == FBP_EFFECT_DIRECTIONAL_BLUR:
        hidden = _fbp_effect_control_hidden_properties(rig, effect_id)
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            tuple(name for name in (
                "fbp_directional_blur_angle",
                "fbp_directional_blur_distance",
                "fbp_directional_blur_factor",
            ) if name not in hidden),
            labels,
        )
        box.label(text="Centered alpha-safe motion sampling", icon="IMAGE_ALPHA")
    if effect_id == FBP_EFFECT_DEPTH_BLUR:
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_depth_blur_mode", labels
        )
        mode = str(getattr(rig, "fbp_depth_blur_mode", "MANUAL") or "MANUAL")
        if mode == "MANUAL":
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_depth_blur_manual_radius", labels
            )
        else:
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_depth_blur_max_radius", labels
            )
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_depth_blur_use_camera_focus", labels
            )
            if not bool(getattr(rig, "fbp_depth_blur_use_camera_focus", True)):
                _fbp_draw_effect_property(
                    box, rig, definition, "fbp_depth_blur_focus_distance", labels
                )
            else:
                scene = getattr(bpy.context, "scene", None)
                camera = _fbp_scene_camera(scene)
                if camera:
                    box.label(text=f"Camera focus: {_fbp_depth_blur_focus_distance(rig, scene):.3f}", icon="CAMERA_DATA")
                else:
                    warning = box.row()
                    warning.alert = True
                    warning.label(text="No active camera; using the stored focus distance", icon="ERROR")
            _fbp_draw_compact_effect_properties(
                box,
                rig,
                definition,
                (
                    "fbp_depth_blur_focus_range",
                    "fbp_depth_blur_falloff",
                    "fbp_depth_blur_near_strength",
                    "fbp_depth_blur_far_strength",
                ),
                labels,
            )
        box.label(
            text="Alpha-safe blur; source sync is cached during playback",
            icon="IMAGE_ALPHA",
        )
    if effect_id == FBP_EFFECT_PIXELATE:
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_pixelate_grid_mode", labels
        )
        pixels_x, pixels_y, mode = _fbp_pixelate_grid(rig)
        pixel_props = ["fbp_pixelate_resolution"]
        if mode == "EXACT":
            pixel_props.append("fbp_pixelate_height")
        _fbp_draw_compact_effect_properties(
            box, rig, definition, pixel_props, labels
        )
        preview = box.row(align=False)
        preview.label(text=f"Grid {pixels_x} × {pixels_y}", icon="ALIASED")
        hidden = _fbp_effect_control_hidden_properties(rig, effect_id)
        transform_properties = tuple(name for name in (
            "fbp_pixelate_rotation", "fbp_pixelate_offset_x", "fbp_pixelate_offset_y"
        ) if name not in hidden)
        if transform_properties:
            _fbp_draw_compact_effect_properties(
                box, rig, definition, transform_properties, labels,
            )
    if effect_id == FBP_EFFECT_HALFTONE:
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_halftone_shape", labels
        )
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            (
                "fbp_halftone_scale",
                "fbp_halftone_dot_size",
                "fbp_halftone_rotation",
                "fbp_halftone_contrast",
            ),
            labels,
        )
        _fbp_draw_toggle_strip(
            box, rig, (
                ("fbp_halftone_invert", "Invert", "ARROW_LEFTRIGHT"),
                ("fbp_halftone_use_source_color", "Source", "IMAGE_DATA"),
                ("fbp_halftone_transparent_background", "Alpha", "IMAGE_ALPHA"),
            )
        )
        if not bool(getattr(rig, "fbp_halftone_use_source_color", True)):
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_halftone_foreground", labels
            )
        if not bool(getattr(rig, "fbp_halftone_transparent_background", False)):
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_halftone_background", labels
            )
    if effect_id == FBP_EFFECT_DOT_MATRIX:
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_dot_matrix_shape", labels
        )
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            (
                "fbp_dot_matrix_scale",
                "fbp_dot_matrix_dot_size",
                "fbp_dot_matrix_spacing",
                "fbp_dot_matrix_min_size",
                "fbp_dot_matrix_max_size",
                "fbp_dot_matrix_contrast",
                "fbp_dot_matrix_response",
            ),
            labels,
        )
        _fbp_draw_toggle_strip(
            box, rig, (
                ("fbp_dot_matrix_invert", "Invert", "ARROW_LEFTRIGHT"),
                ("fbp_dot_matrix_use_source_color", "Source", "IMAGE_DATA"),
                ("fbp_dot_matrix_transparent_background", "Alpha", "IMAGE_ALPHA"),
            )
        )
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            (
                "fbp_dot_matrix_random_size",
                "fbp_dot_matrix_random_brightness",
                "fbp_dot_matrix_dead_pixels",
                "fbp_dot_matrix_flicker",
                "fbp_dot_matrix_glow",
            ),
            labels,
        )
        if not bool(getattr(rig, "fbp_dot_matrix_use_source_color", True)):
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_dot_matrix_foreground", labels
            )
        if not bool(getattr(rig, "fbp_dot_matrix_transparent_background", True)):
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_dot_matrix_background", labels
            )
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_dot_matrix_seed", labels
        )
    if effect_id == FBP_EFFECT_ASCII_MATRIX:
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_ascii_charset", labels
        )
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_ascii_character_count", labels
        )
        _fbp_draw_matrix_character_preview(
            box,
            ascii_gradient(
                str(getattr(rig, "fbp_ascii_charset", "CLASSIC") or "CLASSIC"),
                length=max(2, int(getattr(rig, "fbp_ascii_character_count", 16) or 16)),
            ),
        )
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            (
                "fbp_ascii_scale",
                "fbp_ascii_contrast",
                "fbp_ascii_variation",
                "fbp_ascii_edge_boost",
                "fbp_ascii_dither",
            ),
            labels,
        )
        _fbp_draw_toggle_strip(
            box, rig, (
                ("fbp_ascii_invert", "Invert", "ARROW_LEFTRIGHT"),
                ("fbp_ascii_colorize", "Source", "IMAGE_DATA"),
                ("fbp_ascii_transparent_background", "Alpha", "IMAGE_ALPHA"),
            )
        )
        if not bool(getattr(rig, "fbp_ascii_colorize", False)):
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_ascii_foreground", labels
            )
        if not bool(getattr(rig, "fbp_ascii_transparent_background", True)):
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_ascii_background", labels
            )
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_ascii_random_seed", labels
        )
    if effect_id == FBP_EFFECT_ASCII:
        _fbp_draw_effect_section(box, "ASCII", "CONSOLE")
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            ("fbp_terminal_ascii_scale", "fbp_terminal_ascii_contrast"),
            labels,
        )
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_terminal_ascii_invert", labels
        )

        _fbp_draw_effect_section(box, "Fill", "IMAGE_ALPHA", separator=True)
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            (
                "fbp_terminal_ascii_fill_strength",
                "fbp_terminal_ascii_fill_threshold",
            ),
            labels,
        )

        _fbp_draw_effect_section(box, "Edges", "MOD_EDGESPLIT", separator=True)
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_terminal_ascii_use_edges", labels
        )
        edge_box = box.column(align=False)
        edge_box.enabled = bool(getattr(rig, "fbp_terminal_ascii_use_edges", True))
        _fbp_draw_compact_effect_properties(
            edge_box,
            rig,
            definition,
            (
                "fbp_terminal_ascii_edge_strength",
                "fbp_terminal_ascii_edge_threshold",
                "fbp_terminal_ascii_edge_mix",
            ),
            labels,
        )

        _fbp_draw_effect_section(box, "Color", "COLOR", separator=True)
        _fbp_draw_toggle_strip(
            box, rig, (
                ("fbp_terminal_ascii_use_source_color", "Source", "IMAGE_DATA"),
                ("fbp_terminal_ascii_transparent_background", "Alpha", "IMAGE_ALPHA"),
            )
        )
        if not bool(getattr(rig, "fbp_terminal_ascii_use_source_color", False)):
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_terminal_ascii_foreground", labels
            )
        if not bool(getattr(rig, "fbp_terminal_ascii_transparent_background", True)):
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_terminal_ascii_background", labels
            )
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_terminal_ascii_seed", labels
        )
    if effect_id == FBP_EFFECT_TEXT_MATRIX:
        _fbp_draw_effect_section(box, "Characters", "FONT_DATA")
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_text_matrix_charset", labels
        )
        if str(getattr(rig, "fbp_text_matrix_charset", "")) == "CUSTOM":
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_text_matrix_custom_charset", labels
            )
        _fbp_draw_matrix_character_preview(
            box,
            ascii_level_gradient(
                str(getattr(rig, "fbp_text_matrix_charset", "CLASSIC") or "CLASSIC"),
                levels=min(
                    ASCII_TEXT_GLYPH_LIMIT,
                    max(2, int(getattr(rig, "fbp_text_matrix_character_count", 8) or 8)),
                ),
                custom=str(getattr(rig, "fbp_text_matrix_custom_charset", "") or ""),
            ),
        )
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            ("fbp_text_matrix_font", "fbp_text_matrix_quality"),
            labels,
        )

        _fbp_draw_effect_section(box, "Grid", "SNAP_GRID", separator=True)
        viewport = box.row(align=True)
        viewport.label(text="View", icon="HIDE_OFF")
        viewport.prop(rig, "fbp_text_matrix_viewport_columns", text="Columns", slider=True)
        viewport.prop(rig, "fbp_text_matrix_viewport_rows", text="Rows", slider=True)

        playback_toggle = box.row(align=True)
        playback_toggle.prop(
            rig,
            "fbp_text_matrix_auto_playback_limit",
            text="Playback Limit",
            toggle=True,
            icon="PLAY",
        )
        playback_grid = box.row(align=True)
        playback_grid.enabled = bool(getattr(rig, "fbp_text_matrix_auto_playback_limit", True))
        playback_grid.label(text="Play", icon="PLAY")
        playback_grid.prop(rig, "fbp_text_matrix_playback_columns", text="Columns", slider=True)
        playback_grid.prop(rig, "fbp_text_matrix_playback_rows", text="Rows", slider=True)

        render = box.row(align=True)
        render.label(text="Render", icon="RESTRICT_RENDER_OFF")
        render.prop(rig, "fbp_text_matrix_render_columns", text="Columns", slider=True)
        render.prop(rig, "fbp_text_matrix_render_rows", text="Rows", slider=True)

        _fbp_draw_effect_section(box, "Glyphs", "OUTLINER_OB_FONT", separator=True)
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            (
                "fbp_text_matrix_character_count",
                "fbp_text_matrix_character_aspect",
                "fbp_text_matrix_glyph_scale",
                "fbp_text_matrix_contrast",
                "fbp_text_matrix_variation",
            ),
            labels,
        )
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_text_matrix_invert", labels
        )

        _fbp_draw_effect_section(box, "Output", "COLOR", separator=True)
        _fbp_draw_toggle_strip(
            box, rig, (
                ("fbp_text_matrix_use_source_color", "Source", "IMAGE_DATA"),
                ("fbp_text_matrix_transparent_background", "Alpha", "IMAGE_ALPHA"),
                ("fbp_text_matrix_realize", "Realize", "MODIFIER"),
            )
        )
        if not bool(getattr(rig, "fbp_text_matrix_use_source_color", True)):
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_text_matrix_text_color", labels
            )
        if not bool(getattr(rig, "fbp_text_matrix_transparent_background", True)):
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_text_matrix_background_color", labels
            )
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            ("fbp_text_matrix_alpha_threshold", "fbp_text_matrix_seed"),
            labels,
        )
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
        _fbp_draw_effect_section(box, "Alpha Pixels", "IMAGE_ALPHA")
        follows_visible_pixelate = _fbp_extrude_follows_pixelate(rig, "VIEWPORT")
        link_row = box.row(align=True)
        link_row.prop(
            rig,
            "fbp_thickness_follow_pixelate",
            text="Follow Pixelate",
            toggle=True,
            icon="LINKED" if follows_visible_pixelate else "UNLINKED",
        )
        link_row.prop(
            rig,
            "fbp_thickness_safe_grid",
            text="Safe Limits",
            toggle=True,
            icon="LOCKED",
        )
        if follows_visible_pixelate:
            raw_x, raw_y, _pixelate_mode = _fbp_pixelate_grid(rig)
            effective_x, effective_y, source = _fbp_extrude_grid(rig, "VIEWPORT")
            linked = box.row(align=False)
            linked.label(text=f"Pixelate grid {raw_x} × {raw_y}", icon="ALIASED")
            if source.endswith("_LIMITED") or raw_x > 4096 or raw_y > 4096:
                clamp_warning = box.row()
                clamp_warning.alert = True
                clamp_warning.label(
                    text=f"Viewport evaluates {effective_x} × {effective_y}",
                    icon="LOCKED",
                )
        else:
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_thickness_grid_mode", labels
            )
            grid_mode = str(getattr(rig, "fbp_thickness_grid_mode", "AUTO") or "AUTO")
            for profile, short_label, profile_icon, prop_x, prop_y in (
                ("VIEWPORT", "View", "HIDE_OFF", "fbp_thickness_viewport_pixels_x", "fbp_thickness_viewport_pixels_y"),
                ("PLAYBACK", "Play", "PLAY", "fbp_thickness_playback_pixels_x", "fbp_thickness_playback_pixels_y"),
                ("RENDER", "Render", "RESTRICT_RENDER_OFF", "fbp_thickness_render_pixels_x", "fbp_thickness_render_pixels_y"),
            ):
                effective_x, effective_y, source = _fbp_extrude_grid(rig, profile)
                row = box.row(align=True)
                row.label(text=short_label, icon=profile_icon)
                row.prop(
                    rig,
                    prop_x,
                    text="Pixels X" if grid_mode == "EXACT" else "Pixels",
                )
                if grid_mode == "EXACT":
                    row.prop(rig, prop_y, text="Pixels Y")
                else:
                    row.label(text=f"Y {effective_y}")
                if source.endswith("_LIMITED"):
                    row.label(text=f"→ {effective_x} × {effective_y}", icon="LOCKED")

        _fbp_draw_effect_section(box, "Geometry", "MOD_SOLIDIFY", separator=True)
        _fbp_draw_effect_property(box, rig, definition, "fbp_thickness_mode", labels)
        if str(getattr(rig, "fbp_thickness_mode", "VOLUME") or "VOLUME") == "ARRAY":
            _fbp_draw_effect_property(box, rig, definition, "fbp_thickness_array_count", labels)
        thickness_row = box.row(align=True)
        thickness_row.prop(
            rig,
            "fbp_thickness_amount",
            text="Thickness",
            slider=True,
            icon="DRIVER_DISTANCE",
        )
        direction = float(getattr(rig, "fbp_thickness_direction", -1.0) or -1.0)
        negative = thickness_row.operator(
            "fbp.set_extrude_direction",
            text="",
            icon="REMOVE",
            depress=direction < 0.0,
        )
        negative.direction = -1.0
        positive = thickness_row.operator(
            "fbp.set_extrude_direction",
            text="",
            icon="ADD",
            depress=direction >= 0.0,
        )
        positive.direction = 1.0
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_thickness_alpha_threshold", labels
        )

        if str(getattr(rig, "fbp_thickness_mode", "VOLUME") or "VOLUME") == "VOLUME":
            _fbp_draw_effect_section(box, "Extruded Sides", "MATERIAL", separator=True)
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_thickness_use_plane_colors", labels
            )
            if not bool(getattr(rig, "fbp_thickness_use_plane_colors", False)):
                _fbp_draw_effect_property(
                    box, rig, definition, "fbp_thickness_side_material", labels
                )
                if getattr(rig, "fbp_thickness_side_material", None) is None:
                    _fbp_draw_effect_property(
                        box, rig, definition, "fbp_thickness_side_color", labels
                    )
        else:
            box.label(text="Array uses the animated plane material on every copy", icon="DUPLICATE")
        viewport_x, viewport_y, viewport_source = _fbp_extrude_grid(rig, "VIEWPORT")
        if viewport_source.endswith("_LIMITED"):
            info = box.row()
            info.label(
                text=f"Safe viewport grid: {viewport_x} × {viewport_y}",
                icon="LOCKED",
            )
        elif viewport_x * viewport_y > _FBP_EXTRUDE_SAFE_SAMPLE_BUDGETS["VIEWPORT"]:
            warning = box.row()
            warning.alert = True
            warning.label(text="High pixel sampling may slow interaction", icon="ERROR")
    if definition.get("evolve_property") and effect_id != FBP_EFFECT_MESH_WIGGLE:
        _fbp_draw_effect_section(box, "Animation", "TIME", separator=True)
        seed_row = box.row(align=True)
        if effect_id == FBP_EFFECT_FELT_FUZZ:
            seed_row.prop(rig, "fbp_felt_seed", text="Seed", icon="RNDCURVE")
        else:
            seed_row.prop(
                rig,
                _fbp_animation_key(effect_id, "seed"),
                text="Seed",
                icon="RNDCURVE",
            )
        evolve_key = _fbp_animation_key(effect_id, "evolve")
        seed_row.prop(
            rig,
            evolve_key,
            text="Evolution",
            toggle=True,
            icon="TIME",
        )
        show_step = bool(getattr(rig, evolve_key, False))
        show_unique = bool(definition.get("supports_seed", False))
        if show_step or show_unique:
            options = box.row(align=True)
            if show_step:
                options.prop(
                    rig,
                    _fbp_animation_key(effect_id, "step"),
                    text="Stepped",
                    slider=True,
                    icon="TIME",
                )
            if show_unique:
                options.prop(
                    rig,
                    _fbp_animation_key(effect_id, "unique"),
                    text="Per Layer",
                    toggle=True,
                    icon="DUPLICATE",
                )
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
    hidden_effect_ids = frozenset()

    def _categories(self):
        category_filter = getattr(self, "category_filter", "")
        if isinstance(category_filter, (set, tuple, list, frozenset)):
            return {str(value) for value in category_filter if value}
        category = str(category_filter or "")
        return {category} if category else set()

    def filter_items(self, _context, data, propname):
        items = getattr(data, propname, ())
        categories = self._categories()
        if not categories:
            return [self.bitflag_filter_item] * len(items), []
        hidden_effect_ids = set(getattr(self, "hidden_effect_ids", ()))
        flags = []
        for item in items:
            row_type = str(getattr(item, "row_type", "EFFECT") or "EFFECT")
            group_id = str(getattr(item, "group_id", "") or "")
            if row_type == "GROUP":
                members = fbp_effect_group_members_from_items(data, group_id)
                visible = any(
                    member not in hidden_effect_ids
                    and str(fbp_effect_definition(member).get("category", "2D") or "2D")
                    in categories
                    for member in members
                )
            else:
                effect_id = fbp_normalize_effect_id(getattr(item, "effect_id", ""))
                item_category = str(
                    fbp_effect_definition(effect_id).get("category", "2D") or "2D"
                )
                visible = (
                    item_category in categories
                    and effect_id not in hidden_effect_ids
                )
                if visible and group_id and bool(getattr(item, "group_collapsed", False)):
                    visible = False
            flags.append(self.bitflag_filter_item if visible else 0)
        return flags, []

    def _draw_group_row(self, context, layout, data, item):
        group_id = str(getattr(item, "group_id", "") or "")
        group_name = str(getattr(item, "group_name", "") or "Effect Group")
        collapsed = bool(getattr(item, "group_collapsed", False))
        members = fbp_effect_group_members_from_items(data, group_id)
        member_count = len(members)
        rigs = _fbp_selected_rigs(context)
        if data not in rigs:
            rigs = [data]
        selected_by_id = {
            fbp_normalize_effect_id(getattr(effect_item, "effect_id", "")):
            bool(getattr(effect_item, "is_selected", False))
            for effect_item in data.fbp_effects
            if str(getattr(effect_item, "row_type", "EFFECT") or "EFFECT") == "EFFECT"
        }
        all_group_selected = bool(members) and all(
            selected_by_id.get(member, False) for member in members
        )

        row = layout.row(align=False)
        split = row.split(factor=0.76, align=False)
        left = split.row(align=True)
        left.alignment = "LEFT"

        handle = left.row(align=True)
        handle.enabled = bool(members)
        drag = handle.operator("fbp.drag_effect", text="", icon="GRIP", emboss=False)
        drag.effect_id = members[0] if members else ""
        drag.group_id = group_id

        toggle_selection = left.operator(
            "fbp.toggle_effect_group_selection",
            text="",
            icon="CHECKBOX_HLT" if all_group_selected else "CHECKBOX_DEHLT",
            emboss=False,
        )
        toggle_selection.group_id = group_id
        toggle_selection.selected = not all_group_selected

        collapse = left.operator(
            "fbp.toggle_effect_group_collapse",
            text="",
            icon="RIGHTARROW" if collapsed else "DOWNARROW_HLT",
            emboss=False,
        )
        collapse.group_id = group_id
        collapse.collapsed = not collapsed

        record = _fbp_effect_group_record(data, group_id)
        folder_icon = fbp_collection_color_icon(
            getattr(record, "color_tag", "NONE") if record else "NONE"
        )
        select = left.operator(
            "fbp.select_effect_group",
            text=f"{group_name} ({member_count})",
            icon=folder_icon,
            emboss=False,
        )
        select.group_id = group_id

        actions = left.operator(
            "fbp.effect_group_actions",
            text="",
            icon="DOWNARROW_HLT",
            emboss=False,
        )
        actions.group_id = group_id

        right = split.row(align=True)
        right.alignment = "RIGHT"
        is_image_stack = isinstance(self, FBP_UL_EffectStack2D)
        try:
            right.ui_units_x = 5.4 if is_image_stack else 4.4
        except (AttributeError, TypeError, ValueError):
            pass

        solo_states = [
            all(fbp_effect_is_soloed(rig, member) for member in members)
            for rig in rigs
            if members and all(fbp_effect_is_active(rig, member) for member in members)
        ]
        soloed = bool(solo_states) and all(solo_states)
        solo = right.operator(
            "fbp.toggle_effect_solo",
            text="",
            icon="OUTLINER_OB_LIGHT" if soloed else "LIGHT",
            emboss=False,
        )
        solo.effect_id = ""
        solo.group_id = group_id

        view_states = [
            fbp_effect_visible_state(rig, member)
            for rig in rigs for member in members
            if fbp_effect_is_active(rig, member)
        ]
        render_states = [
            fbp_effect_render_visible_state(rig, member)
            for rig in rigs for member in members
            if fbp_effect_is_active(rig, member)
        ]
        view_visible = bool(view_states) and all(view_states)
        render_visible = bool(render_states) and all(render_states)
        viewport = right.operator(
            "fbp.effect_group_action",
            text="",
            icon="HIDE_OFF" if view_visible else "HIDE_ON",
            emboss=False,
        )
        viewport.group_id = group_id
        viewport.action = "HIDE_VIEWPORT" if view_visible else "SHOW_VIEWPORT"
        render = right.operator(
            "fbp.effect_group_action",
            text="",
            icon="RESTRICT_RENDER_OFF" if render_visible else "RESTRICT_RENDER_ON",
            emboss=False,
        )
        render.group_id = group_id
        render.action = "HIDE_RENDER" if render_visible else "SHOW_RENDER"
        if is_image_stack:
            right.label(text="", icon="BLANK1")

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        row_type = str(getattr(item, "row_type", "EFFECT") or "EFFECT")
        if row_type == "GROUP":
            if self.layout_type == "GRID":
                layout.alignment = "CENTER"
                layout.label(text="", icon=fbp_collection_color_icon(
                    getattr(_fbp_effect_group_record(data, getattr(item, "group_id", "")), "color_tag", "NONE")
                ))
                return
            self._draw_group_row(context, layout, data, item)
            return

        effect_id = fbp_normalize_effect_id(getattr(item, "effect_id", ""))
        definition = fbp_effect_definition(effect_id)
        effect_icon = str(definition.get("icon", "MODIFIER"))
        label = _fbp_effect_display_label(effect_id, definition)
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
        group_id = str(getattr(item, "group_id", "") or "")

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
        drag = handle.operator("fbp.drag_effect", text="", icon="GRIP", emboss=False)
        drag.effect_id = effect_id
        drag.group_id = ""

        selected = bool(getattr(item, "is_selected", False))
        left.prop(
            item,
            "is_selected",
            text="",
            icon="CHECKBOX_HLT" if selected else "CHECKBOX_DEHLT",
            emboss=False,
        )
        if group_id:
            left.label(text="", icon="BLANK1")

        select = left.operator(
            "fbp.select_effect",
            text=(
                f"↳ {label} ({present_count}/{selected_count})"
                if is_partial and group_id
                else (
                    f"{label} ({present_count}/{selected_count})"
                    if is_partial else (f"↳ {label}" if group_id else label)
                )
            ),
            icon="ERROR" if is_partial else effect_icon,
            emboss=False,
        )
        select.effect_id = effect_id

        right = split.row(align=True)
        right.alignment = "RIGHT"
        is_image_stack = isinstance(self, FBP_UL_EffectStack2D)
        try:
            right.ui_units_x = (6.4 if is_partial else 5.4) if is_image_stack else (5.4 if is_partial else 4.4)
        except (AttributeError, TypeError, ValueError):
            pass
        if is_partial:
            copy = right.operator("fbp.copy_effect_to_selected", text="", icon="PASTEDOWN", emboss=False)
            copy.effect_id = effect_id

        solo_states = [
            fbp_effect_is_soloed(rig, effect_id)
            for rig in rigs
            if fbp_effect_is_active(rig, effect_id)
        ]
        soloed = bool(solo_states) and all(solo_states)
        solo_row = right.row(align=True)
        solo_row.enabled = bool(
            present_count == selected_count
            and definition.get("kind") in {"SHADER", "GEOMETRY"}
        )
        solo = solo_row.operator(
            "fbp.toggle_effect_solo",
            text="",
            icon="OUTLINER_OB_LIGHT" if soloed else "LIGHT",
            emboss=False,
        )
        solo.effect_id = effect_id
        solo.group_id = ""

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
        if is_image_stack:
            maskable = _fbp_effect_can_receive_mask(effect_id)
            mask_cell = right.row(align=True)
            mask_cell.enabled = bool(maskable and present_count == selected_count)
            if maskable:
                attached_count = sum(
                    1 for rig in rigs
                    if fbp_effect_is_active(rig, effect_id)
                    and bool(fbp_masks_targeting_effect(rig, effect_id))
                )
                mask_cell.alert = bool(0 < attached_count < selected_count)
                mask = mask_cell.operator(
                    "fbp.open_effect_masks", text="",
                    icon="CLIPUV_HLT" if attached_count else "CLIPUV_DEHLT",
                    emboss=False,
                )
                mask.effect_id = effect_id
            else:
                mask_cell.label(text="", icon="BLANK1")
        remove = right.operator("fbp.remove_effect", text="", icon="TRASH", emboss=False)
        remove.effect_id = effect_id


class FBP_UL_EffectStack2D(FBP_UL_EffectStack):
    # Layer Blend is a first-class layer property drawn above the stack.
    category_filter = {"BASE", "2D"}
    hidden_effect_ids = frozenset({FBP_EFFECT_LAYER_BLEND})


class FBP_UL_EffectStack3D(FBP_UL_EffectStack):
    category_filter = "3D"


class FBP_UL_EffectStackMask(FBP_UL_EffectStack):
    category_filter = "MASK"


def fbp_draw_effect_mask_editor(layout, context, rigs, target_effect_id):
    """Draw masks attached to one Image/UV effect below the normal stack.

    All attachment and presence state is resolved once per selected rig. This
    avoids repeating effect discovery for every mask row and keeps mixed
    multi-selection states explicit instead of silently editing unrelated masks.
    """
    target_effect_id = fbp_normalize_effect_id(target_effect_id)
    if not rigs or not _fbp_effect_can_receive_mask(target_effect_id):
        return False
    target_definition = fbp_effect_definition(target_effect_id)
    compatible_rigs = [
        rig for rig in rigs if fbp_effect_is_active(rig, target_effect_id)
    ]
    if not target_definition or not compatible_rigs:
        return False

    panel = layout.box()
    header = panel.row(align=True)
    header.label(
        text=f"Masks · {_fbp_effect_display_label(target_effect_id, target_definition)}",
        icon="CLIPUV_HLT",
    )
    if len(compatible_rigs) != len(rigs):
        header.label(text=f"{len(compatible_rigs)}/{len(rigs)} layers", icon="ERROR")
    header.operator("fbp.close_effect_masks", text="", icon="X", emboss=False)

    rig_states = []
    active_mask_ids = []
    seen_mask_ids = set()
    for rig in compatible_rigs:
        effect_ids = tuple(fbp_effect_ids_for_rig(rig))
        effect_id_set = set(effect_ids)
        target_map = _fbp_mask_target_map(rig)
        rig_states.append((rig, effect_id_set, target_map))
        for effect_id in effect_ids:
            if effect_id in seen_mask_ids or not _fbp_effect_is_local_mask(effect_id):
                continue
            seen_mask_ids.add(effect_id)
            active_mask_ids.append(effect_id)

    selected_count = len(compatible_rigs)
    presence_counts = {
        mask_id: sum(1 for _rig, effect_ids, _targets in rig_states if mask_id in effect_ids)
        for mask_id in active_mask_ids
    }
    attachment_counts = {
        mask_id: sum(
            1 for _rig, _effect_ids, targets in rig_states
            if mask_id in targets.get(target_effect_id, ())
        )
        for mask_id in active_mask_ids
    }
    attached = [
        mask_id for mask_id in active_mask_ids
        if attachment_counts.get(mask_id, 0) > 0
    ]

    if attached:
        for mask_effect_id in attached:
            definition = fbp_effect_definition(mask_effect_id)
            attached_count = attachment_counts.get(mask_effect_id, 0)
            present_count = presence_counts.get(mask_effect_id, 0)
            source_rig = next(
                (
                    rig for rig, _effect_ids, targets in rig_states
                    if mask_effect_id in targets.get(target_effect_id, ())
                ),
                compatible_rigs[0],
            )
            mask_box = panel.box()
            row = mask_box.row(align=True)
            label = _fbp_effect_display_label(mask_effect_id, definition, fallback="Mask")
            if attached_count != selected_count:
                label = f"{label} ({attached_count}/{selected_count})"
            row.label(
                text=label,
                icon=str(definition.get("icon", "MOD_MASK") or "MOD_MASK"),
            )
            if attached_count != selected_count:
                apply_all = row.operator(
                    "fbp.add_effect_mask", text="", icon="PASTEDOWN", emboss=False,
                )
                apply_all.mask_effect_id = mask_effect_id
                apply_all.target_effect_id = target_effect_id
            show = row.operator("fbp.select_effect", text="", icon="IMAGE_ALPHA", emboss=False)
            show.effect_id = mask_effect_id
            detach = row.operator(
                "fbp.set_effect_mask_target", text="", icon="UNLINKED", emboss=False
            )
            detach.mask_effect_id = mask_effect_id
            detach.target_effect_id = "LAYER"
            detach.expected_target_effect_id = target_effect_id

            fully_shared = attached_count == selected_count and present_count == selected_count
            if not fully_shared:
                warning = mask_box.row(align=False)
                warning.alert = True
                warning.label(
                    text="Attach this mask to all selected layers before multi-editing",
                    icon="ERROR",
                )
            settings = mask_box.column(align=False)
            settings.enabled = fully_shared
            fbp_draw_effect_settings(
                settings, source_rig, mask_effect_id,
                selected_count=selected_count, present_count=present_count,
            )
    else:
        panel.label(text="No mask limits this effect yet", icon="INFO")

    reusable = [
        effect_id for effect_id in active_mask_ids
        if attachment_counts.get(effect_id, 0) == 0
    ]
    if reusable:
        panel.separator()
        panel.label(text="Move Existing Mask", icon="LINKED")
        flow = panel.grid_flow(
            row_major=True, columns=2, even_columns=True, even_rows=False, align=False
        )
        for mask_effect_id in reusable:
            definition = fbp_effect_definition(mask_effect_id)
            attach = flow.operator(
                "fbp.add_effect_mask",
                text=_fbp_effect_display_label(mask_effect_id, definition, fallback="Mask"),
                icon=str(definition.get("icon", "MOD_MASK") or "MOD_MASK"),
            )
            attach.mask_effect_id = mask_effect_id
            attach.target_effect_id = target_effect_id

    panel.separator()
    panel.label(text="Add Mask", icon="ADD")
    sections = (
        ("Generated", (FBP_EFFECT_COLOR_MASK, FBP_EFFECT_LUMINANCE_MASK, FBP_EFFECT_CHANNEL_MASK, FBP_EFFECT_GRADIENT_MASK, FBP_EFFECT_NOISE_MASK)),
        ("Shapes", (FBP_EFFECT_SQUARE_MASK, FBP_EFFECT_CIRCLE_MASK, FBP_EFFECT_TRIANGLE_MASK)),
        ("Mattes", (FBP_EFFECT_ALPHA_MATTE, FBP_EFFECT_LUMA_MATTE)),
    )
    existing_masks = set(active_mask_ids)
    for label, effect_ids in sections:
        available = [
            effect_id for effect_id in effect_ids
            if effect_id not in existing_masks
            and any(fbp_effect_supported_for_rig(rig, effect_id) for rig in compatible_rigs)
        ]
        if not available:
            continue
        panel.label(text=label)
        flow = panel.grid_flow(
            row_major=True, columns=2, even_columns=True, even_rows=False, align=False
        )
        for mask_effect_id in available:
            definition = fbp_effect_definition(mask_effect_id)
            add = flow.operator(
                "fbp.add_effect_mask",
                text=_fbp_effect_display_label(mask_effect_id, definition, fallback="Mask"),
                icon=str(definition.get("icon", "MOD_MASK") or "MOD_MASK"),
            )
            add.mask_effect_id = mask_effect_id
            add.target_effect_id = target_effect_id
    return True


def _fbp_custom_effect_ids_for_view(view):
    view = str(view or "2D").upper()
    if view not in {"2D", "3D", "MASK"}:
        view = "2D"
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
    """Draw Image, Mask and Mesh menus in the exact curated section order."""
    rigs, active_effects = menu_state or _fbp_effect_add_menu_state(context)
    view = str(view or "2D").upper()
    if view not in {"2D", "3D", "MASK"}:
        view = "2D"
    if view == "3D":
        sections, column_groups = FBP_MESH_EFFECT_MENU_SECTIONS, FBP_MESH_EFFECT_MENU_COLUMNS
    elif view == "MASK":
        sections, column_groups = FBP_MASK_EFFECT_MENU_SECTIONS, FBP_MASK_EFFECT_MENU_COLUMNS
    else:
        sections, column_groups = FBP_IMAGE_EFFECT_MENU_SECTIONS, FBP_IMAGE_EFFECT_MENU_COLUMNS

    def already_on_every_selected(effect_id):
        return bool(rigs) and all(
            effect_id in active_effects.get(_fbp_effect_ids_cache_key(rig), set())
            for rig in rigs
        )

    def draw_effect(parent, effect_token):
        effect_token = str(effect_token or "")
        if effect_token == "LAYER_BLEND_CONTROL":
            effect_token = FBP_EFFECT_LAYER_BLEND
        if effect_token.startswith("FAMILY:"):
            family_id = effect_token.split(":", 1)[1].upper()
            family = fbp_effect_family_definition(family_id)
            default_effect = str(family.get("default", "") or "")
            variants = tuple(family.get("variants", ()) or ())
            supported_variants = [
                variant_id for variant_id, _label in variants
                if not rigs or all(fbp_effect_supported_for_rig(rig, variant_id) for rig in rigs)
            ]
            already_on_all = bool(rigs) and all(
                any(variant_id in active_effects.get(_fbp_effect_ids_cache_key(rig), set()) for variant_id, _label in variants)
                for rig in rigs
            )
            row = parent.row(align=False)
            row.enabled = bool(default_effect and supported_variants and not already_on_all)
            op = row.operator(
                "fbp.add_effect_family",
                text=str(family.get("label", family_id.title()) or family_id.title()),
                icon=str(family.get("icon", "MODIFIER") or "MODIFIER"),
            )
            op.family_id = family_id
            return
        effect_id = fbp_normalize_effect_id(effect_token)
        definition = fbp_effect_definition(effect_id)
        row = parent.row(align=False)
        supported = not rigs or any(fbp_effect_supported_for_rig(rig, effect_id) for rig in rigs)
        row.enabled = supported and not already_on_every_selected(effect_id)
        op = row.operator(
            "fbp.add_effect",
            text=_fbp_effect_display_label(effect_id, definition),
            icon=str(definition.get("icon", "MODIFIER") or "MODIFIER"),
        )
        op.effect_id = effect_id

    if show_view_header:
        header = {
            "2D": ("Image", "IMAGE_BACKGROUND"),
            "MASK": ("Mask", "CLIPUV_DEHLT"),
            "3D": ("Mesh", "WORKSPACE"),
        }[view]
        layout.label(text=header[0], icon=header[1])

    def draw_user_effects(parent):
        """Draw user effects as the final section of the fourth column."""
        custom = parent.column(align=False)
        custom.label(text="User Effects", icon="NODETREE")
        custom.separator(factor=0.35)
        custom_ids = _fbp_custom_effect_ids_for_view(view)
        if custom_ids:
            for effect_id in custom_ids:
                definition = fbp_effect_definition(effect_id)
                row = custom.row(align=False)
                supported = not rigs or any(
                    fbp_effect_supported_for_rig(rig, effect_id) for rig in rigs
                )
                row.enabled = supported and not already_on_every_selected(effect_id)
                op = row.operator(
                    "fbp.add_effect",
                    text=_fbp_effect_display_label(effect_id, definition),
                    icon=str(definition.get("icon", "NODETREE") or "NODETREE"),
                )
                op.effect_id = effect_id
        else:
            custom.label(text="No user effects", icon="INFO")
        # Keep both library actions inside the User Effects block. A shared
        # horizontal row allowed Blender to stretch Register Existing into what
        # looked like a fifth empty column in wide popovers.
        create = custom.operator(
            "fbp.create_custom_node_effect", text="New User Effect", icon="ADD"
        )
        create.kind = "GEOMETRY" if view == "3D" else "SHADER"
        custom.operator(
            "fbp.register_custom_node_effect",
            text="Register Existing…",
            icon="NODETREE",
        )

    # The first three columns are reserved for curated native effects. The
    # fourth column is always and exclusively the user library, so custom
    # effects never move when native sections are reorganized.
    columns = layout.row(align=False)
    native_groups = list(column_groups[:3])
    while len(native_groups) < 3:
        native_groups.append(())

    for section_indices in native_groups:
        column = columns.column(align=False)
        for local_index, section_index in enumerate(section_indices):
            if local_index:
                column.separator()
            section_label, section_icon, effect_tokens = sections[int(section_index)]
            section = column.column(align=False)
            section.label(text=section_label, icon=section_icon)
            section.separator(factor=0.35)
            for effect_token in effect_tokens:
                draw_effect(section, effect_token)

    user_column = columns.column(align=False)
    draw_user_effects(user_column)


def _fbp_draw_family_variant_operator(layout, rigs, source_effect_id, target_effect_id, label):
    row = layout.row(align=False)
    supported = all(
        fbp_effect_supported_for_rig(target_rig, target_effect_id)
        for target_rig in rigs
    )
    already_target_everywhere = bool(rigs) and all(
        fbp_effect_is_active(target_rig, target_effect_id)
        for target_rig in rigs
    )
    row.enabled = supported and not already_target_everywhere
    op = row.operator(
        "fbp.set_effect_family_variant",
        text=str(label),
        depress=target_effect_id == source_effect_id,
    )
    op.source_effect_id = source_effect_id
    op.target_effect_id = target_effect_id


class FBP_MT_DuotoneVariants(Menu):
    bl_idname = "FBP_MT_duotone_variants"
    bl_label = "Duotone"

    def draw(self, context):
        layout = self.layout
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            layout.label(text="Select a Frame By Plane layer", icon="INFO")
            return
        effect_id = fbp_active_effect_id(rigs[0])
        _fbp_draw_family_variant_operator(
            layout, rigs, effect_id, FBP_EFFECT_DUOTONE, "Duotone"
        )
        _fbp_draw_family_variant_operator(
            layout, rigs, effect_id, FBP_EFFECT_FALSE_COLOR, "False Color"
        )


class FBP_MT_EffectFamilyVariants(Menu):
    bl_idname = "FBP_MT_effect_family_variants"
    bl_label = "Effect Variant"

    def draw(self, context):
        layout = self.layout
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            layout.label(text="Select a Frame By Plane layer", icon="INFO")
            return
        effect_id = fbp_active_effect_id(rigs[0])
        family_id = fbp_effect_family_id(effect_id)
        family = fbp_effect_family_definition(family_id)
        variants = tuple(family.get("variants", ()) or ())
        if not variants:
            layout.label(text="This effect has no variants", icon="INFO")
            return
        for target_effect_id, label in variants:
            if family_id == "COLORIZE" and target_effect_id == FBP_EFFECT_FALSE_COLOR:
                continue
            if family_id == "COLORIZE" and target_effect_id == FBP_EFFECT_DUOTONE:
                row = layout.row(align=False)
                row.menu("FBP_MT_duotone_variants", text="Duotone")
                continue
            _fbp_draw_family_variant_operator(
                layout, rigs, effect_id, target_effect_id, label
            )


def _fbp_family_variant_ramp_key(effect_id):
    return f"fbp_family_variant_ramp::{fbp_normalize_effect_id(effect_id)}"


def _fbp_store_family_variant_ramp(rig, effect_id):
    state = _fbp_capture_effect_color_ramp(rig, effect_id)
    if state is None:
        return False
    try:
        rig[_fbp_family_variant_ramp_key(effect_id)] = json.dumps(
            state, sort_keys=True, separators=(",", ":")
        )
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_restore_family_variant_ramp(rig, effect_id):
    try:
        raw = rig.get(_fbp_family_variant_ramp_key(effect_id), "")
        state = json.loads(raw) if isinstance(raw, str) and raw else None
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        state = None
    return bool(state and _fbp_apply_effect_color_ramp(rig, effect_id, state))


def _fbp_copy_shared_family_properties(rig, source_effect_id, target_effect_id):
    """Copy shared and family-specific settings while switching variants."""
    source = fbp_effect_definition(source_effect_id)
    target = fbp_effect_definition(target_effect_id)
    source_by_socket = {
        str(socket): str(prop)
        for prop, socket in dict(source.get("property_map", {})).items()
    }
    target_by_socket = {
        str(socket): str(prop)
        for prop, socket in dict(target.get("property_map", {})).items()
    }

    def get_value(prop_name, default=None):
        try:
            return getattr(rig, prop_name) if hasattr(rig, prop_name) else default
        except FBP_DATA_ERRORS:
            return default

    def set_value(prop_name, value):
        if value is None or not hasattr(rig, prop_name):
            return False
        return fbp_set_rna_property_silent(rig, prop_name, value)

    copied = False
    for socket_name in sorted(set(source_by_socket) & set(target_by_socket)):
        source_prop = source_by_socket[socket_name]
        target_prop = target_by_socket[socket_name]
        copied = set_value(target_prop, get_value(source_prop)) or copied

    family_id = fbp_effect_family_id(source_effect_id)
    if family_id == "TINT":
        black = (0.0, 0.0, 0.0, 1.0)
        white = (1.0, 1.0, 1.0, 1.0)
        source_effect_id = fbp_normalize_effect_id(source_effect_id)
        target_effect_id = fbp_normalize_effect_id(target_effect_id)
        if source_effect_id == "SOLID_MASK":
            accent = tuple(get_value("fbp_solid_mask_color", white))
            shadows, midtones, highlights = black, accent, accent
            factor = get_value("fbp_solid_mask_factor", 1.0)
        elif source_effect_id == "DUOTONE":
            shadows = tuple(get_value("fbp_duotone_shadows", black))
            highlights = tuple(get_value("fbp_duotone_highlights", white))
            midtones = tuple((float(a) + float(b)) * 0.5 for a, b in zip(shadows, highlights))
            factor = 1.0
        elif source_effect_id == "TRITONE":
            shadows = tuple(get_value("fbp_tritone_shadows", black))
            midtones = tuple(get_value("fbp_tritone_midtones", (0.5, 0.5, 0.5, 1.0)))
            highlights = tuple(get_value("fbp_tritone_highlights", white))
            factor = get_value("fbp_tritone_factor", 1.0)
        elif source_effect_id == "FALSE_COLOR":
            shadows = tuple(get_value("fbp_false_color_dark", black))
            highlights = tuple(get_value("fbp_false_color_light", white))
            midtones = tuple((float(a) + float(b)) * 0.5 for a, b in zip(shadows, highlights))
            factor = get_value("fbp_false_color_factor", 1.0)
        else:
            shadows, midtones, highlights, factor = black, (0.5, 0.5, 0.5, 1.0), white, 1.0

        if target_effect_id == "SOLID_MASK":
            copied = set_value("fbp_solid_mask_color", highlights) or copied
            copied = set_value("fbp_solid_mask_factor", factor) or copied
        elif target_effect_id == "DUOTONE":
            copied = set_value("fbp_duotone_shadows", shadows) or copied
            copied = set_value("fbp_duotone_highlights", highlights) or copied
        elif target_effect_id == "TRITONE":
            copied = set_value("fbp_tritone_shadows", shadows) or copied
            copied = set_value("fbp_tritone_midtones", midtones) or copied
            copied = set_value("fbp_tritone_highlights", highlights) or copied
            copied = set_value("fbp_tritone_factor", factor) or copied
        elif target_effect_id == "FALSE_COLOR":
            copied = set_value("fbp_false_color_dark", shadows) or copied
            copied = set_value("fbp_false_color_light", highlights) or copied
            copied = set_value("fbp_false_color_factor", factor) or copied
        elif target_effect_id == "RECOLOR":
            copied = set_value("fbp_recolor_factor", factor) or copied

    elif family_id == "BLUR":
        radius_props = {
            "GAUSSIAN_BLUR": ("fbp_gaussian_blur_radius_x", "fbp_gaussian_blur_radius_y"),
            "DIRECTIONAL_BLUR": ("fbp_directional_blur_distance",),
            "DEPTH_BLUR": ("fbp_depth_blur_manual_radius",),
            "TRIANGLE_BLUR": ("fbp_triangle_blur_radius",),
            "TILT_SHIFT": ("fbp_tilt_shift_radius",),
        }
        sample_props = {
            "GAUSSIAN_BLUR": "fbp_gaussian_blur_samples",
            "DIRECTIONAL_BLUR": "fbp_directional_blur_samples",
            "TRIANGLE_BLUR": "fbp_triangle_blur_samples",
        }
        source_radius_values = [
            float(get_value(prop_name, 0.0) or 0.0)
            for prop_name in radius_props.get(fbp_normalize_effect_id(source_effect_id), ())
        ]
        radius = max(source_radius_values, default=0.0)
        for prop_name in radius_props.get(fbp_normalize_effect_id(target_effect_id), ()):
            copied = set_value(prop_name, radius) or copied
        source_samples = sample_props.get(fbp_normalize_effect_id(source_effect_id), "")
        target_samples = sample_props.get(fbp_normalize_effect_id(target_effect_id), "")
        if source_samples and target_samples:
            copied = set_value(target_samples, get_value(source_samples)) or copied

    elif family_id == "PIXELATE":
        grid_props = {
            "PIXELATE": ("fbp_pixelate_resolution", "fbp_pixelate_height"),
            "MOSAIC_JITTER": ("fbp_mosaic_jitter_cells_x", "fbp_mosaic_jitter_cells_y"),
            "HEX_PIXELATE": ("fbp_hex_pixelate_cells_x", "fbp_hex_pixelate_cells_y"),
        }
        source_grid = grid_props.get(fbp_normalize_effect_id(source_effect_id), ())
        target_grid = grid_props.get(fbp_normalize_effect_id(target_effect_id), ())
        if source_grid and target_grid:
            copied = set_value(target_grid[0], get_value(source_grid[0])) or copied
            copied = set_value(target_grid[1], get_value(source_grid[1])) or copied

    return copied


def fbp_switch_effect_family_variant(rig, source_effect_id, target_effect_id):
    source_effect_id = fbp_normalize_effect_id(source_effect_id)
    target_effect_id = fbp_normalize_effect_id(target_effect_id)
    if not rig or not source_effect_id or not target_effect_id:
        return False
    if source_effect_id == target_effect_id:
        return True
    if fbp_effect_family_id(source_effect_id) != fbp_effect_family_id(target_effect_id):
        return False
    if not fbp_effect_is_active(rig, source_effect_id):
        return False
    if fbp_effect_is_active(rig, target_effect_id):
        return False

    visible = fbp_effect_visible_state(rig, source_effect_id)
    render_visible = fbp_effect_render_visible_state(rig, source_effect_id)
    solo_view = _fbp_effect_solo_view(source_effect_id)
    solo_before = tuple(fbp_effect_solo_ids(rig, solo_view))
    source_was_soloed = source_effect_id in solo_before
    source_input = fbp_effect_input_source(rig, source_effect_id)
    source_debug = fbp_effect_debug_mode(rig, source_effect_id)
    attached_masks = tuple(fbp_masks_targeting_effect(rig, source_effect_id))
    _fbp_store_family_variant_ramp(rig, source_effect_id)

    _fbp_select_effect_row(rig, source_effect_id)
    if not fbp_add_effect(
        rig, target_effect_id, sync_items=False, inherit_active_group=True
    ):
        return False
    _fbp_copy_shared_family_properties(rig, source_effect_id, target_effect_id)
    _fbp_restore_family_variant_ramp(rig, target_effect_id)
    fbp_set_effect_visible(rig, target_effect_id, visible)
    fbp_set_effect_render_visible(rig, target_effect_id, render_visible)
    if fbp_effect_definition(target_effect_id).get("supports_input_source"):
        fbp_set_effect_input_source(rig, target_effect_id, source_input)
    if tuple(fbp_effect_definition(target_effect_id).get("debug_modes", ()) or ()):
        fbp_set_effect_debug_mode(rig, target_effect_id, source_debug)
    for mask_effect_id in attached_masks:
        fbp_set_effect_mask_target(rig, mask_effect_id, target_effect_id)

    if not fbp_remove_effect(rig, source_effect_id, sync_items=False):
        fbp_remove_effect(rig, target_effect_id, sync_items=False)
        return False
    if source_was_soloed:
        desired_solo = {
            effect_id for effect_id in solo_before
            if effect_id != source_effect_id and fbp_effect_is_active(rig, effect_id)
        }
        desired_solo.add(target_effect_id)
        for effect_id in _fbp_effect_solo_candidates(rig, solo_view):
            fbp_set_effect_visible(rig, effect_id, effect_id in desired_solo)
        _fbp_store_effect_solo_ids(rig, solo_view, desired_solo)
    fbp_sync_effect_items(rig)
    _fbp_select_effect_row(rig, target_effect_id)
    try:
        from .effect_controls import sync_active_effect_controls
        sync_active_effect_controls(getattr(bpy, "context", None))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return True


class FBP_OT_SetEffectFamilyVariant(Operator):
    bl_idname = "fbp.set_effect_family_variant"
    bl_label = "Set Effect Variant"
    bl_description = "Replace the selected effect with another variant from the same family while preserving order, masks and shared settings"
    bl_options = {"REGISTER", "UNDO"}

    source_effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    target_effect_id: StringProperty(default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        family = fbp_effect_family_definition(self.source_effect_id)
        variants = tuple(family.get("variants", ()) or ())
        changed = 0
        for rig in rigs:
            if fbp_effect_is_active(rig, self.target_effect_id):
                continue
            current_effect_id = next((
                effect_id for effect_id, _label in variants
                if fbp_effect_is_active(rig, effect_id)
            ), "")
            if current_effect_id and fbp_switch_effect_family_variant(
                rig, current_effect_id, self.target_effect_id
            ):
                changed += 1
        if not changed:
            self.report({"INFO"}, "The selected variant is already active")
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        return {"FINISHED"}


class FBP_OT_AddEffectFamily(Operator):
    bl_idname = "fbp.add_effect_family"
    bl_label = "Add Effect Family"
    bl_description = "Add the default variant of a unified Frame By Plane effect family"
    bl_options = {"REGISTER", "UNDO"}

    family_id: StringProperty(default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        family = fbp_effect_family_definition(self.family_id)
        default_effect_id = str(family.get("default", "") or "")
        variants = tuple(family.get("variants", ()) or ())
        rigs = _fbp_selected_rigs(context)
        if not default_effect_id or not rigs:
            return {"CANCELLED"}
        common_variants = [
            effect_id for effect_id, _label in variants
            if all(fbp_effect_supported_for_rig(rig, effect_id) for rig in rigs)
        ]
        if not common_variants:
            self.report({"WARNING"}, "No variant in this family supports every selected layer")
            return {"CANCELLED"}
        target_effect_id = (
            default_effect_id if default_effect_id in common_variants
            else common_variants[0]
        )
        changed = 0
        for rig in rigs:
            active_variant = next(
                (effect_id for effect_id, _label in variants if fbp_effect_is_active(rig, effect_id)),
                "",
            )
            if active_variant:
                continue
            if fbp_add_effect(rig, target_effect_id, sync_items=False):
                changed += 1
        fbp_sync_effect_items(rigs[0], rigs)
        if not changed:
            self.report({"INFO"}, "This effect family is already present")
            return {"CANCELLED"}
        _fbp_select_effect_row(rigs[0], target_effect_id, rigs)
        return {"FINISHED"}


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


class FBP_MT_ObjectMasks(Menu):
    bl_idname = "FBP_MT_object_masks"
    bl_label = "Masks"

    def draw(self, context):
        if not _fbp_selected_rigs(context):
            self.layout.label(text="Select a Frame by Plane layer", icon="INFO")
            return
        _fbp_draw_effect_add_columns(self.layout, context, "MASK")


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
            FBP_MT_ObjectMasks.bl_idname,
            text="Masks",
            icon="IMAGE_ALPHA",
        )
        layout.menu(
            FBP_MT_ObjectEffects3D.bl_idname,
            text="3D Effects",
            icon="MODIFIER",
        )


def _fbp_context_layer_blend_mode(rig):
    """Read the lightweight persistent Blend state for context-menu labels."""
    if rig is None:
        return "NORMAL"
    definition = fbp_effect_definition(FBP_EFFECT_LAYER_BLEND)
    enabled_key = str(
        definition.get("enabled_key", "fbp_effect_layer_blend")
        or "fbp_effect_layer_blend"
    )
    try:
        if not bool(rig.get(enabled_key, False)):
            return "NORMAL"
        return str(getattr(rig, "fbp_layer_blend_mode", "MULTIPLY") or "MULTIPLY").upper()
    except FBP_DATA_ERRORS:
        return "NORMAL"


def _fbp_context_layer_blend_text(rigs):
    modes = {_fbp_context_layer_blend_mode(rig) for rig in rigs if rig is not None}
    if len(modes) != 1:
        return "Blend · Mixed"
    mode = next(iter(modes))
    return f"Blend · {fbp_layer_blend_short(mode)}  {fbp_layer_blend_label(mode)}"


def _fbp_draw_object_context_effects(self, context):
    """Prepend Blend, contextual masks and Effects to Blender's menu."""
    rigs = _fbp_selected_rigs(context)
    if not rigs:
        return

    active = getattr(context, "active_object", None)
    try:
        from .object_masks import (
            find_object_mask_owner,
            is_object_mask_helper,
            object_mask_contract,
            object_mask_label,
            object_mask_lock_property,
            object_mask_show_property,
        )
        if active is not None and is_object_mask_helper(active):
            contract = object_mask_contract(active) or {}
            shape = str(contract.get("shape", "SQUARE") or "SQUARE")
            owner = find_object_mask_owner(active)
            if owner is not None:
                label = object_mask_label(shape)
                self.layout.label(text=f"{label} Shape Mask", icon="MOD_MASK")
                row = self.layout.row(align=True)
                edit = row.operator(
                    "fbp.edit_object_mask_helper",
                    text="Edit Shape",
                    icon="EDITMODE_HLT",
                )
                edit.rig_name = owner.name
                edit.shape = shape
                recreate = row.operator(
                    "fbp.recreate_object_mask_helper",
                    text="",
                    icon="FILE_REFRESH",
                )
                recreate.rig_name = owner.name
                recreate.shape = shape

                show_prop = object_mask_show_property(shape)
                lock_prop = object_mask_lock_property(shape)
                controls = self.layout.row(align=True)
                if hasattr(owner, show_prop):
                    visible = bool(getattr(owner, show_prop, True))
                    controls.prop(
                        owner, show_prop, text="Show Helper", toggle=True,
                        icon="HIDE_OFF" if visible else "HIDE_ON",
                    )
                if hasattr(owner, lock_prop):
                    locked = bool(getattr(owner, lock_prop, True))
                    controls.prop(
                        owner, lock_prop, text="Lock 3D", toggle=True,
                        icon="LOCKED" if locked else "UNLOCKED",
                    )
                self.layout.separator()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    # Blender submenus open on hover, so Blend no longer requires an extra
    # click. It intentionally sits immediately above Effects.
    self.layout.menu(
        "FBP_MT_layer_blend_dropdown",
        text=_fbp_context_layer_blend_text(rigs),
        icon="NODE_MATERIAL",
    )
    self.layout.menu(
        FBP_MT_ObjectEffects.bl_idname,
        text="Effects",
        icon="MODIFIER",
    )
    self.layout.separator()


class FBP_OT_FitShadowCanvas(Operator):
    bl_idname = "fbp.fit_shadow_canvas"
    bl_label = "Fit Transparent Shadow Canvas"
    bl_description = (
        "Extend the plane only where the current outer shadow needs room and "
        "sample the added border as transparent pixels. Existing larger Crop / "
        "Extend margins are preserved"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(
            fbp_effect_is_active(rig, FBP_EFFECT_SHADOW)
            and str(getattr(rig, "fbp_shadow_mode", "OUTER") or "OUTER") == "OUTER"
            for rig in _fbp_selected_rigs(context)
        )

    def execute(self, context):
        changed = 0
        for rig in _fbp_selected_rigs(context):
            if not fbp_effect_is_active(rig, FBP_EFFECT_SHADOW):
                continue
            if str(getattr(rig, "fbp_shadow_mode", "OUTER") or "OUTER") != "OUTER":
                continue
            offset_x = float(getattr(rig, "fbp_shadow_offset_x", 0.0) or 0.0)
            offset_y = float(getattr(rig, "fbp_shadow_offset_y", 0.0) or 0.0)
            blur = max(0.0, float(getattr(rig, "fbp_shadow_blur", 0.0) or 0.0))
            # Crop / Extend margins are expressed in half-width units while
            # shadow position and blur are UV distances, hence the factor 2.
            safety = 0.005
            required = {
                "fbp_extend_left": 2.0 * (blur + max(0.0, -offset_x) + safety),
                "fbp_extend_right": 2.0 * (blur + max(0.0, offset_x) + safety),
                "fbp_extend_bottom": 2.0 * (blur + max(0.0, -offset_y) + safety),
                "fbp_extend_top": 2.0 * (blur + max(0.0, offset_y) + safety),
            }
            local_change = fbp_set_rna_property_silent(
                rig, "fbp_extend_mode", "TRANSPARENT"
            )
            for prop_name, minimum in required.items():
                current = max(0.0, float(getattr(rig, prop_name, 0.0) or 0.0))
                if minimum > current + 1e-6:
                    local_change = fbp_set_rna_property_silent(
                        rig, prop_name, minimum
                    ) or local_change
            if not local_change:
                continue
            try:
                from .builder import set_plane_mesh_extension
                from .layers import fbp_layer_backend_type
                set_plane_mesh_extension(
                    rig,
                    getattr(rig, "fbp_extend_left", 0.0),
                    getattr(rig, "fbp_extend_right", 0.0),
                    getattr(rig, "fbp_extend_bottom", 0.0),
                    getattr(rig, "fbp_extend_top", 0.0),
                    "TRANSPARENT",
                    getattr(rig, "fbp_crop_left", 0.0),
                    getattr(rig, "fbp_crop_right", 0.0),
                    getattr(rig, "fbp_crop_bottom", 0.0),
                    getattr(rig, "fbp_crop_top", 0.0),
                )
                backend = fbp_layer_backend_type(rig)
                if str(backend).startswith("NATIVE_"):
                    from .native_backend import fbp_sync_native_texture_settings
                    if not fbp_sync_native_texture_settings(rig):
                        from .core import fbp_refresh_sequence_backend_from_rig
                        fbp_refresh_sequence_backend_from_rig(rig)
                elif backend == "CUTOUT":
                    from .drawing_plane import fbp_sync_drawing_texture_settings
                    fbp_sync_drawing_texture_settings(rig)
                try:
                    from .object_masks import sync_owner_object_mask_helpers
                    sync_owner_object_mask_helpers(rig)
                except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
                fbp_refresh_aspect_dependent_effect_grids(rig)
                fbp_sync_mattes_for_source_bounds(
                    rig, scene=getattr(context, "scene", None)
                )
                try:
                    from .effect_controls import schedule_active_effect_controls, sync_crop_extend_bounds_guide
                    sync_crop_extend_bounds_guide(rig)
                    schedule_active_effect_controls(context)
                except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                fbp_warn("Could not fit transparent shadow canvas", exc)
                continue
            changed += 1
        if not changed:
            self.report({"INFO"}, "The selected outer shadows already have enough transparent canvas")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Fitted transparent canvas for {changed} layer{'s' if changed != 1 else ''}")
        return {"FINISHED"}


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


class FBP_OT_SetExtrudeDirection(Operator):
    bl_idname = "fbp.set_extrude_direction"
    bl_label = "Set Extrude Direction"
    bl_description = "Extrude behind the plane with minus or toward the local front with plus"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    direction: FloatProperty(default=-1.0, min=-1.0, max=1.0, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        value = -1.0 if float(self.direction) < 0.0 else 1.0
        changed = 0
        for rig in _fbp_selected_rigs(context):
            if not fbp_effect_is_active(rig, FBP_EFFECT_THICKNESS):
                continue
            previous = float(getattr(rig, "fbp_thickness_direction", -1.0) or -1.0)
            if abs(previous - value) <= 1.0e-6:
                continue
            fbp_set_rna_property_silent(rig, "fbp_thickness_direction", value)
            fbp_update_geometry_effect(
                rig,
                FBP_EFFECT_THICKNESS,
                sync_alpha=False,
                property_names={"fbp_thickness_direction"},
            )
            changed += 1
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_OpenEffectMasks(Operator):
    bl_idname = "fbp.open_effect_masks"
    bl_label = "Edit Effect Masks"
    bl_options = {"INTERNAL"}

    effect_id: StringProperty(default="", options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        effect_id = fbp_normalize_effect_id(getattr(properties, "effect_id", ""))
        definition = fbp_effect_definition(effect_id)
        label = str(definition.get("label", effect_id) or "effect")
        rigs = _fbp_selected_rigs(context)
        attached = sum(1 for rig in rigs if fbp_masks_targeting_effect(rig, effect_id))
        if attached:
            return f"Edit masks used by {label} on {attached} selected layer(s)"
        return f"Add or edit masks for {label}"

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        effect_id = fbp_normalize_effect_id(self.effect_id)
        rigs = _fbp_selected_rigs(context)
        if not rigs or not _fbp_effect_can_receive_mask(effect_id):
            return {"CANCELLED"}
        try:
            # Per-effect mask controls belong to the 2D stack. Switch the view
            # before selecting the row because the view callback may otherwise
            # replace the requested target with the first visible effect.
            context.scene.fbp_effects_view = "2D"
            context.scene.fbp_effect_mask_edit_target = effect_id
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}
        _fbp_select_effect_row(rigs[0], effect_id, rigs)
        return {"FINISHED"}


class FBP_OT_CloseEffectMasks(Operator):
    bl_idname = "fbp.close_effect_masks"
    bl_label = "Close Effect Masks"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        try:
            context.scene.fbp_effect_mask_edit_target = ""
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}
        return {"FINISHED"}


def _fbp_restore_effect_mask_assignment(rig, mask_effect_id, was_active, previous_target):
    """Restore one mask assignment after a failed multi-layer transaction."""
    if not rig:
        return False
    try:
        if not was_active:
            if not fbp_effect_is_active(rig, mask_effect_id):
                return True
            return fbp_remove_effect(rig, mask_effect_id)
        if not fbp_effect_is_active(rig, mask_effect_id):
            return False
        if fbp_effect_mask_target(rig, mask_effect_id) == previous_target:
            return True
        fbp_set_effect_mask_target(rig, mask_effect_id, previous_target)
        return fbp_effect_mask_target(rig, mask_effect_id) == previous_target
    except FBP_DATA_ERRORS:
        return False


def _fbp_apply_effect_mask_transaction(
    rigs, mask_effect_id, target_effect_id, *, add_missing=False
):
    """Assign one mask atomically across compatible selected layers.

    Blender RNA updates are immediate. Without an explicit transaction, one
    failed material rebuild can leave only part of a multi-selection attached.
    Snapshot the previous assignment, verify every result, and roll all touched
    layers back when any one of them fails.
    """
    mask_effect_id = fbp_normalize_effect_id(mask_effect_id)
    target_effect_id = fbp_normalize_effect_id(target_effect_id) or "LAYER"
    candidates = [rig for rig in tuple(rigs or ()) if rig]
    if candidates:
        candidates = _fbp_unique_live_rigs(candidates[0], candidates[1:])
    snapshots = []
    changed = 0
    for rig in candidates:
        was_active = fbp_effect_is_active(rig, mask_effect_id)
        previous_target = (
            fbp_effect_mask_target(rig, mask_effect_id) if was_active else "LAYER"
        )
        snapshots.append((rig, was_active, previous_target))

    failed = False
    for rig, was_active, previous_target in snapshots:
        if not was_active:
            if not add_missing or not fbp_add_effect(
                rig, mask_effect_id, select_object_mask_helper=False
            ):
                failed = True
                break
            _fbp_move_shader_effect_to_stage_edge(
                rig, mask_effect_id, first=True, rebuild=False, sync_items=False
            )
        if target_effect_id != "LAYER" and not fbp_effect_is_active(rig, target_effect_id):
            failed = True
            break
        if fbp_effect_mask_target(rig, mask_effect_id) != target_effect_id:
            fbp_set_effect_mask_target(rig, mask_effect_id, target_effect_id)
        if (
            not fbp_effect_is_active(rig, mask_effect_id)
            or fbp_effect_mask_target(rig, mask_effect_id) != target_effect_id
        ):
            failed = True
            break
        if not was_active or previous_target != target_effect_id:
            changed += 1

    if failed:
        for rig, was_active, previous_target in reversed(snapshots):
            _fbp_restore_effect_mask_assignment(
                rig, mask_effect_id, was_active, previous_target
            )
        return False, 0
    return True, changed


class FBP_OT_AddEffectMask(Operator):
    bl_idname = "fbp.add_effect_mask"
    bl_label = "Add Mask to Effect"
    bl_options = {"REGISTER", "UNDO"}

    mask_effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    target_effect_id: StringProperty(default="", options={"SKIP_SAVE"})

    @classmethod
    def description(cls, _context, properties):
        mask = fbp_effect_definition(getattr(properties, "mask_effect_id", ""))
        target = fbp_effect_definition(getattr(properties, "target_effect_id", ""))
        return (
            f"Add or move {mask.get('label', 'Mask')} to "
            f"{target.get('label', 'this effect')}; one mask can target one effect at a time"
        )

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        mask_effect_id = fbp_normalize_effect_id(self.mask_effect_id)
        target_effect_id = fbp_normalize_effect_id(self.target_effect_id)
        if not _fbp_effect_is_local_mask(mask_effect_id) or not _fbp_effect_can_receive_mask(target_effect_id):
            return {"CANCELLED"}
        rigs = _fbp_selected_rigs(context)
        compatible = [
            rig for rig in rigs
            if fbp_effect_is_active(rig, target_effect_id)
            and fbp_effect_supported_for_rig(rig, mask_effect_id)
        ]
        success, changed = _fbp_apply_effect_mask_transaction(
            compatible,
            mask_effect_id,
            target_effect_id,
            add_missing=True,
        )
        if not success:
            self.report({"ERROR"}, "Mask assignment failed; all selected layers were restored")
            return {"CANCELLED"}
        if compatible:
            fbp_sync_effect_items(compatible[0], rigs)
        try:
            context.scene.fbp_effect_mask_edit_target = target_effect_id
        except FBP_DATA_ERRORS:
            pass
        if not compatible:
            self.report({"WARNING"}, "This mask is not compatible with the selected layers")
            return {"CANCELLED"}
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_SetEffectMaskTarget(Operator):
    bl_idname = "fbp.set_effect_mask_target"
    bl_label = "Attach or Detach Mask"
    bl_description = "Attach this mask to the selected 2D effect, or return it to the whole layer"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    mask_effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    target_effect_id: StringProperty(default="LAYER", options={"SKIP_SAVE"})
    expected_target_effect_id: StringProperty(
        default="", options={"SKIP_SAVE"},
        description="Only change masks currently attached to this effect",
    )

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        mask_effect_id = fbp_normalize_effect_id(self.mask_effect_id)
        target_effect_id = fbp_normalize_effect_id(self.target_effect_id) or "LAYER"
        expected_target_effect_id = fbp_normalize_effect_id(
            self.expected_target_effect_id
        )
        eligible = [
            rig for rig in rigs
            if fbp_effect_is_active(rig, mask_effect_id)
            and (
                not expected_target_effect_id
                or fbp_effect_mask_target(rig, mask_effect_id) == expected_target_effect_id
            )
            and (
                target_effect_id == "LAYER"
                or fbp_effect_is_active(rig, target_effect_id)
            )
        ]
        success, changed = _fbp_apply_effect_mask_transaction(
            eligible,
            mask_effect_id,
            target_effect_id,
            add_missing=False,
        )
        if not success:
            self.report({"ERROR"}, "Mask assignment failed; all selected layers were restored")
            return {"CANCELLED"}
        if eligible:
            fbp_sync_effect_items(eligible[0], rigs)
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_SelectEffect(Operator):
    bl_idname = "fbp.select_effect"
    bl_label = "Select Effect"
    bl_options = {"INTERNAL"}

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", name="Effect ID", default="", options={"SKIP_SAVE"})

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
        definition = fbp_effect_definition(effect_id) or {}
        category = str(definition.get("category", "2D") or "2D")
        try:
            # Switch the visible stack first. Its update callback selects the
            # first compatible row, so the requested effect must be selected
            # afterwards to avoid losing the user's exact target.
            context.scene.fbp_effects_view = (
                "3D" if category == "3D"
                else ("MASK" if category == "MASK" else "2D")
            )
        except FBP_DATA_ERRORS:
            pass
        return {"FINISHED"} if _fbp_select_effect_row(rig, effect_id, rigs) else {"CANCELLED"}


class FBP_OT_AddEffect(Operator):
    bl_idname = "fbp.add_effect"
    bl_label = "Add Frame by Plane Effect"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", name="Effect ID", default="", options={"SKIP_SAVE"})

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
        requested_id = fbp_normalize_effect_id(self.effect_id)
        if requested_id == FBP_EFFECT_LATTICE:
            compatible = [rig for rig in rigs if not _fbp_lattice_compatibility_issue(rig)]
        else:
            compatible = [rig for rig in rigs if fbp_effect_supported_for_rig(rig, self.effect_id)]
        changed_rigs = [
            rig for rig in compatible
            if fbp_add_effect(rig, self.effect_id, sync_items=False)
        ]
        changed = len(changed_rigs)
        if changed == 0:
            if fbp_normalize_effect_id(self.effect_id) == FBP_EFFECT_LATTICE and rigs:
                messages = [
                    _fbp_last_lattice_error(rig) or _fbp_lattice_compatibility_issue(rig)
                    for rig in rigs
                ]
                message = next((item for item in messages if item), "Lattice setup failed")
                self.report({"ERROR"}, message)
            else:
                self.report({"ERROR"}, f"{definition.get('label', self.effect_id)} is not compatible with the selected layers")
            return {"CANCELLED"}
        # New effects start at the beginning of their compatible evaluation
        # chain. Commit every real move first, then rebuild the transient UI
        # mirror once for the complete multi-layer operation.
        for rig in changed_rigs:
            while fbp_can_move_effect(rig, self.effect_id, "UP"):
                if not fbp_move_effect(
                    rig, self.effect_id, "UP", sync_items=False
                ):
                    break
        active_rig = rigs[0]
        try:
            category = str(definition.get("category", "2D") or "2D")
            context.scene.fbp_effects_view = "3D" if category == "3D" else ("MASK" if category == "MASK" else "2D")
        except FBP_DATA_ERRORS:
            pass
        fbp_sync_effect_items(
            active_rig, rigs, repair_assets=False, normalize_instance_ids=False
        )
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
        except FBP_DATA_ERRORS:
            pass
    return False


FBP_BUILTIN_EFFECT_PRESETS = {
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
        "Face Camera": {"fbp_camera_billboard_mode": "FULL", "fbp_camera_billboard_flip": False, "fbp_camera_billboard_influence": 1.0},
        "Horizontal Only": {"fbp_camera_billboard_mode": "HORIZONTAL", "fbp_camera_billboard_flip": False, "fbp_camera_billboard_influence": 1.0},
        "Vertical Only": {"fbp_camera_billboard_mode": "VERTICAL", "fbp_camera_billboard_flip": False, "fbp_camera_billboard_influence": 1.0},
    },
    FBP_EFFECT_MIRROR: {
        "Horizontal": {"fbp_mirror_x": True, "fbp_mirror_y": False},
        "Vertical": {"fbp_mirror_x": False, "fbp_mirror_y": True},
        "Both Axes": {"fbp_mirror_x": True, "fbp_mirror_y": True},
    },
    FBP_EFFECT_SHADOW: {
        "Soft Drop": {"fbp_shadow_mode": "OUTER", "fbp_shadow_blend_mode": "NORMAL", "fbp_shadow_offset_x": 0.025, "fbp_shadow_offset_y": -0.025, "fbp_shadow_blur": 0.025, "fbp_shadow_opacity": 0.45, "fbp_shadow_color": (0.0, 0.0, 0.0, 1.0)},
        "Graphic Offset": {"fbp_shadow_mode": "OUTER", "fbp_shadow_blend_mode": "NORMAL", "fbp_shadow_offset_x": 0.045, "fbp_shadow_offset_y": -0.045, "fbp_shadow_blur": 0.004, "fbp_shadow_opacity": 0.85, "fbp_shadow_color": (0.02, 0.02, 0.02, 1.0)},
        "Inner Depth": {"fbp_shadow_mode": "INNER", "fbp_shadow_blend_mode": "MULTIPLY", "fbp_shadow_offset_x": 0.018, "fbp_shadow_offset_y": -0.018, "fbp_shadow_blur": 0.018, "fbp_shadow_opacity": 0.55, "fbp_shadow_color": (0.05, 0.04, 0.03, 1.0)},
    },
    FBP_EFFECT_CHROMA_KEY: {
        "Green Screen": {"fbp_chroma_key_color": (0.0, 1.0, 0.0, 1.0), "fbp_chroma_key_tolerance": 0.20, "fbp_chroma_key_softness": 0.08, "fbp_chroma_key_despill": 0.65},
        "Blue Screen": {"fbp_chroma_key_color": (0.0, 0.18, 1.0, 1.0), "fbp_chroma_key_tolerance": 0.20, "fbp_chroma_key_softness": 0.08, "fbp_chroma_key_despill": 0.55},
    },
    FBP_EFFECT_SOLARIZE: {
        "Classic Solarize": {"fbp_solarize_threshold": 0.5, "fbp_solarize_softness": 0.04, "fbp_solarize_factor": 1.0},
        "Soft Highlight Flip": {"fbp_solarize_threshold": 0.62, "fbp_solarize_softness": 0.18, "fbp_solarize_factor": 0.75},
        "Graphic Negative": {"fbp_solarize_threshold": 0.32, "fbp_solarize_softness": 0.01, "fbp_solarize_factor": 1.0},
    },
    FBP_EFFECT_TRITONE: {
        "Cinema Amber": {"fbp_tritone_shadows": (0.015, 0.025, 0.07, 1.0), "fbp_tritone_midtones": (0.50, 0.16, 0.12, 1.0), "fbp_tritone_highlights": (1.0, 0.82, 0.42, 1.0), "fbp_tritone_midpoint": 0.48},
        "Cyanotype": {"fbp_tritone_shadows": (0.005, 0.02, 0.08, 1.0), "fbp_tritone_midtones": (0.03, 0.25, 0.48, 1.0), "fbp_tritone_highlights": (0.78, 0.93, 1.0, 1.0), "fbp_tritone_midpoint": 0.52},
        "Rose Print": {"fbp_tritone_shadows": (0.08, 0.01, 0.03, 1.0), "fbp_tritone_midtones": (0.62, 0.10, 0.30, 1.0), "fbp_tritone_highlights": (1.0, 0.78, 0.68, 1.0), "fbp_tritone_midpoint": 0.50},
    },
    FBP_EFFECT_PIXELATE: {
        "Classic Pixel Art": {"fbp_pixelate_grid_mode": "AUTO", "fbp_pixelate_resolution": 64, "fbp_pixelate_rotation": 0.0, "fbp_pixelate_offset_x": 0.0, "fbp_pixelate_offset_y": 0.0},
        "Rotated Tiles": {"fbp_pixelate_grid_mode": "AUTO", "fbp_pixelate_resolution": 48, "fbp_pixelate_rotation": 0.78539816339, "fbp_pixelate_offset_x": 0.0, "fbp_pixelate_offset_y": 0.0},
        "Offset Grid": {"fbp_pixelate_grid_mode": "EXACT", "fbp_pixelate_resolution": 40, "fbp_pixelate_height": 24, "fbp_pixelate_offset_x": 0.0125, "fbp_pixelate_offset_y": 0.0208},
    },
    FBP_EFFECT_SWIRL: {
        "Gentle Twist": {"fbp_swirl_radius": 0.65, "fbp_swirl_angle": 1.25, "fbp_swirl_factor": 1.0},
        "Vortex": {"fbp_swirl_radius": 0.75, "fbp_swirl_angle": 6.283185307, "fbp_swirl_factor": 1.0},
        "Reverse Spiral": {"fbp_swirl_radius": 0.6, "fbp_swirl_angle": -4.71238898, "fbp_swirl_factor": 1.0},
    },
    FBP_EFFECT_BULGE_PINCH: {
        "Soft Bulge": {"fbp_bulge_pinch_radius": 0.55, "fbp_bulge_pinch_strength": 0.45, "fbp_bulge_pinch_factor": 1.0},
        "Strong Bulge": {"fbp_bulge_pinch_radius": 0.7, "fbp_bulge_pinch_strength": 1.1, "fbp_bulge_pinch_factor": 1.0},
        "Pinch": {"fbp_bulge_pinch_radius": 0.65, "fbp_bulge_pinch_strength": -0.75, "fbp_bulge_pinch_factor": 1.0},
    },
    FBP_EFFECT_LENS_WARP: {
        "Barrel Lens": {"fbp_lens_warp_distortion": 0.75, "fbp_lens_warp_zoom": 1.12, "fbp_lens_warp_factor": 1.0},
        "Pincushion": {"fbp_lens_warp_distortion": -0.65, "fbp_lens_warp_zoom": 0.96, "fbp_lens_warp_factor": 1.0},
        "Action Camera": {"fbp_lens_warp_distortion": 1.35, "fbp_lens_warp_zoom": 1.32, "fbp_lens_warp_factor": 1.0},
    },
    FBP_EFFECT_WAVE_WARP: {
        "Water Sway": {"fbp_wave_warp_amplitude": 0.018, "fbp_wave_warp_frequency": 5.0, "fbp_wave_warp_phase": 0.0, "fbp_wave_warp_angle": 0.0},
        "Heat Wave": {"fbp_wave_warp_amplitude": 0.012, "fbp_wave_warp_frequency": 18.0, "fbp_wave_warp_phase": 0.0, "fbp_wave_warp_angle": 1.57079632679},
        "Ribbon": {"fbp_wave_warp_amplitude": 0.06, "fbp_wave_warp_frequency": 3.0, "fbp_wave_warp_phase": 0.0, "fbp_wave_warp_angle": 0.78539816339},
    },
    FBP_EFFECT_RIPPLE_DISTORTION: {
        "Water Drop": {"fbp_ripple_distortion_amplitude": 0.018, "fbp_ripple_distortion_frequency": 18.0, "fbp_ripple_distortion_radius": 0.7, "fbp_ripple_distortion_falloff": 1.5},
        "Shockwave": {"fbp_ripple_distortion_amplitude": 0.055, "fbp_ripple_distortion_frequency": 8.0, "fbp_ripple_distortion_radius": 0.9, "fbp_ripple_distortion_falloff": 2.5},
        "Soft Pulse": {"fbp_ripple_distortion_amplitude": 0.01, "fbp_ripple_distortion_frequency": 5.0, "fbp_ripple_distortion_radius": 1.2, "fbp_ripple_distortion_falloff": 0.7},
    },
    FBP_EFFECT_KALEIDOSCOPE: {
        "Six Mirrors": {"fbp_kaleidoscope_segments": 6, "fbp_kaleidoscope_rotation": 0.0, "fbp_kaleidoscope_factor": 1.0},
        "Crystal": {"fbp_kaleidoscope_segments": 12, "fbp_kaleidoscope_rotation": 0.2617993878, "fbp_kaleidoscope_factor": 1.0},
        "Three Fold": {"fbp_kaleidoscope_segments": 3, "fbp_kaleidoscope_rotation": 0.0, "fbp_kaleidoscope_factor": 1.0},
    },
    FBP_EFFECT_HEX_PIXELATE: {
        "Honeycomb": {"fbp_hex_pixelate_cells_x": 48, "fbp_hex_pixelate_cells_y": 32, "fbp_hex_pixelate_rotation": 0.0, "fbp_hex_pixelate_factor": 1.0},
        "Large Hex": {"fbp_hex_pixelate_cells_x": 18, "fbp_hex_pixelate_cells_y": 12, "fbp_hex_pixelate_rotation": 0.0, "fbp_hex_pixelate_factor": 1.0},
        "Diagonal Hex": {"fbp_hex_pixelate_cells_x": 36, "fbp_hex_pixelate_cells_y": 24, "fbp_hex_pixelate_rotation": 0.5235987756, "fbp_hex_pixelate_factor": 1.0},
    },
    FBP_EFFECT_MOSAIC_JITTER: {
        "Broken Mosaic": {"fbp_mosaic_jitter_cells_x": 32, "fbp_mosaic_jitter_cells_y": 18, "fbp_mosaic_jitter_amount": 0.65, "fbp_mosaic_jitter_seed": 0, "fbp_mosaic_jitter_factor": 1.0},
        "Digital Blocks": {"fbp_mosaic_jitter_cells_x": 64, "fbp_mosaic_jitter_cells_y": 36, "fbp_mosaic_jitter_amount": 1.25, "fbp_mosaic_jitter_seed": 11, "fbp_mosaic_jitter_factor": 1.0},
        "Subtle Mosaic": {"fbp_mosaic_jitter_cells_x": 80, "fbp_mosaic_jitter_cells_y": 45, "fbp_mosaic_jitter_amount": 0.25, "fbp_mosaic_jitter_seed": 3, "fbp_mosaic_jitter_factor": 0.7},
    },
    FBP_EFFECT_GAUSSIAN_BLUR: {
        "Soft Focus": {"fbp_gaussian_blur_radius_x": 4.0, "fbp_gaussian_blur_radius_y": 4.0, "fbp_gaussian_blur_factor": 0.65},
        "Strong Defocus": {"fbp_gaussian_blur_radius_x": 14.0, "fbp_gaussian_blur_radius_y": 14.0, "fbp_gaussian_blur_samples": 17, "fbp_gaussian_blur_factor": 1.0},
        "Horizontal Soften": {"fbp_gaussian_blur_radius_x": 12.0, "fbp_gaussian_blur_radius_y": 1.5, "fbp_gaussian_blur_samples": 17, "fbp_gaussian_blur_factor": 0.85},
    },
    FBP_EFFECT_DIRECTIONAL_BLUR: {
        "Horizontal Motion": {"fbp_directional_blur_angle": 0.0, "fbp_directional_blur_distance": 18.0, "fbp_directional_blur_samples": 17, "fbp_directional_blur_factor": 1.0},
        "Vertical Motion": {"fbp_directional_blur_angle": 1.57079632679, "fbp_directional_blur_distance": 18.0, "fbp_directional_blur_samples": 17, "fbp_directional_blur_factor": 1.0},
        "Diagonal Motion": {"fbp_directional_blur_angle": 0.78539816339, "fbp_directional_blur_distance": 26.0, "fbp_directional_blur_samples": 21, "fbp_directional_blur_factor": 0.9},
    },
    FBP_EFFECT_TRIANGLE_BLUR: {
        "Soft Triangle": {"fbp_triangle_blur_radius": 6.0, "fbp_triangle_blur_samples": 13, "fbp_triangle_blur_factor": 0.75},
        "Wide Triangle": {"fbp_triangle_blur_radius": 22.0, "fbp_triangle_blur_samples": 21, "fbp_triangle_blur_factor": 1.0},
    },
    FBP_EFFECT_TILT_SHIFT: {
        "Miniature": {"fbp_tilt_shift_position": 0.52, "fbp_tilt_shift_width": 0.18, "fbp_tilt_shift_angle": 0.0, "fbp_tilt_shift_radius": 24.0, "fbp_tilt_shift_factor": 1.0},
        "Dream Band": {"fbp_tilt_shift_position": 0.45, "fbp_tilt_shift_width": 0.32, "fbp_tilt_shift_angle": 0.0, "fbp_tilt_shift_radius": 14.0, "fbp_tilt_shift_factor": 0.75},
    },
    FBP_EFFECT_UNSHARP_MASK: {
        "Gentle Sharpen": {"fbp_unsharp_radius": 1.0, "fbp_unsharp_amount": 0.65, "fbp_unsharp_factor": 1.0},
        "Graphic Detail": {"fbp_unsharp_radius": 2.0, "fbp_unsharp_amount": 1.8, "fbp_unsharp_factor": 1.0},
    },
    FBP_EFFECT_EDGE_DETECT: {
        "Ink Lines": {"fbp_edge_detect_width": 1.0, "fbp_edge_detect_strength": 2.4, "fbp_edge_detect_threshold": 0.05, "fbp_edge_detect_softness": 0.035, "fbp_edge_detect_color": (0.0,0.0,0.0,1.0), "fbp_edge_detect_factor": 1.0},
        "White Technical": {"fbp_edge_detect_width": 1.5, "fbp_edge_detect_strength": 3.0, "fbp_edge_detect_threshold": 0.09, "fbp_edge_detect_softness": 0.025, "fbp_edge_detect_color": (1.0,1.0,1.0,1.0), "fbp_edge_detect_factor": 1.0},
    },
    FBP_EFFECT_SMOOTH_TOON: {
        "Soft Cel": {"fbp_smooth_toon_levels": 6.0, "fbp_smooth_toon_softness": 0.18, "fbp_smooth_toon_factor": 1.0},
        "Graphic Cel": {"fbp_smooth_toon_levels": 4.0, "fbp_smooth_toon_softness": 0.02, "fbp_smooth_toon_factor": 1.0},
    },
    FBP_EFFECT_ADAPTIVE_THRESHOLD: {
        "Photocopy": {"fbp_adaptive_threshold_radius": 5.0, "fbp_adaptive_threshold_offset": -0.03, "fbp_adaptive_threshold_softness": 0.025, "fbp_adaptive_threshold_invert": False, "fbp_adaptive_threshold_factor": 1.0},
        "Pencil Map": {"fbp_adaptive_threshold_radius": 10.0, "fbp_adaptive_threshold_offset": 0.05, "fbp_adaptive_threshold_softness": 0.10, "fbp_adaptive_threshold_factor": 0.85},
    },
    FBP_EFFECT_INK: {
        "Warm Ink": {"fbp_ink_width": 1.0, "fbp_ink_threshold": 0.045, "fbp_ink_softness": 0.05, "fbp_ink_strength": 2.5, "fbp_ink_color": (0.015,0.01,0.008,1.0), "fbp_ink_paper_color": (0.94,0.90,0.80,1.0), "fbp_ink_preserve_color": 0.15},
        "Color Comic": {"fbp_ink_width": 1.2, "fbp_ink_threshold": 0.055, "fbp_ink_softness": 0.03, "fbp_ink_strength": 3.0, "fbp_ink_color": (0.0,0.0,0.0,1.0), "fbp_ink_preserve_color": 0.85},
        "Blue Draft": {"fbp_ink_width": 0.8, "fbp_ink_threshold": 0.035, "fbp_ink_softness": 0.07, "fbp_ink_strength": 2.2, "fbp_ink_color": (0.02,0.12,0.32,1.0), "fbp_ink_paper_color": (0.92,0.95,1.0,1.0), "fbp_ink_preserve_color": 0.0},
    },
    FBP_EFFECT_EDGE_WORK: {
        "Illustrated Edges": {"fbp_edge_work_radius": 1.5, "fbp_edge_work_thickness": 4.0, "fbp_edge_work_strength": 5.0, "fbp_edge_work_threshold": 0.025, "fbp_edge_work_softness": 0.06},
        "Broad Charcoal": {"fbp_edge_work_radius": 3.0, "fbp_edge_work_thickness": 9.0, "fbp_edge_work_strength": 8.0, "fbp_edge_work_threshold": 0.035, "fbp_edge_work_softness": 0.12, "fbp_edge_work_color": (0.025,0.018,0.012,1.0)},
    },
    FBP_EFFECT_PENCIL_SKETCH: {
        "Graphite": {"fbp_pencil_sketch_radius": 6.0, "fbp_pencil_sketch_contrast": 1.6, "fbp_pencil_sketch_graphite": (0.03,0.025,0.02,1.0), "fbp_pencil_sketch_paper": (0.96,0.93,0.84,1.0), "fbp_pencil_sketch_color_amount": 0.0},
        "Colored Pencil": {"fbp_pencil_sketch_radius": 4.0, "fbp_pencil_sketch_contrast": 1.35, "fbp_pencil_sketch_graphite": (0.08,0.04,0.02,1.0), "fbp_pencil_sketch_paper": (0.98,0.95,0.88,1.0), "fbp_pencil_sketch_color_amount": 0.65},
    },
    FBP_EFFECT_POSTER_EDGES: {
        "Graphic Poster": {"fbp_poster_edges_levels": 5.0, "fbp_poster_edges_softness": 0.08, "fbp_poster_edges_width": 1.0, "fbp_poster_edges_strength": 2.8, "fbp_poster_edges_threshold": 0.045},
        "Hard Comic": {"fbp_poster_edges_levels": 3.0, "fbp_poster_edges_softness": 0.015, "fbp_poster_edges_width": 1.4, "fbp_poster_edges_strength": 3.8, "fbp_poster_edges_threshold": 0.055},
    },
    FBP_EFFECT_CROSSHATCH: {
        "Fine Engraving": {"fbp_crosshatch_scale": 110.0, "fbp_crosshatch_line_width": 0.075, "fbp_crosshatch_levels": 4, "fbp_crosshatch_preserve_color": 0.0},
        "Comic Hatch": {"fbp_crosshatch_scale": 58.0, "fbp_crosshatch_line_width": 0.13, "fbp_crosshatch_levels": 3, "fbp_crosshatch_preserve_color": 0.55},
    },
    FBP_EFFECT_EMBOSS: {
        "Raised Paper": {"fbp_emboss_angle": 0.785398, "fbp_emboss_distance": 2.0, "fbp_emboss_strength": 2.0, "fbp_emboss_bias": 0.5, "fbp_emboss_color_amount": 0.15},
        "Engraved": {"fbp_emboss_angle": 0.785398, "fbp_emboss_distance": 3.0, "fbp_emboss_strength": -2.8, "fbp_emboss_bias": 0.5, "fbp_emboss_color_amount": 0.0},
    },
    FBP_EFFECT_FALSE_COLOR: {
        "Thermal": {"fbp_false_color_dark": (0.0,0.02,0.25,1.0), "fbp_false_color_light": (1.0,0.4,0.0,1.0), "fbp_false_color_factor": 1.0},
        "Cyan Amber": {"fbp_false_color_dark": (0.0,0.25,0.35,1.0), "fbp_false_color_light": (1.0,0.65,0.12,1.0), "fbp_false_color_factor": 1.0},
    },
    FBP_EFFECT_CHROMATIC_ABERRATION: {
        "Lens Fringe": {"fbp_chromatic_aberration_distance": 2.0, "fbp_chromatic_aberration_angle": 0.0, "fbp_chromatic_aberration_factor": 0.8},
        "VHS Split": {"fbp_chromatic_aberration_distance": 8.0, "fbp_chromatic_aberration_angle": 0.0, "fbp_chromatic_aberration_factor": 1.0},
    },
    FBP_EFFECT_FILM_FADE: {
        "Warm Print": {"fbp_film_fade_color": (0.72, 0.48, 0.28, 1.0), "fbp_film_fade_amount": 0.35, "fbp_film_fade_desaturation": 0.45, "fbp_film_fade_contrast_loss": 0.30},
        "Faded Cyan": {"fbp_film_fade_color": (0.20, 0.55, 0.62, 1.0), "fbp_film_fade_amount": 0.28, "fbp_film_fade_desaturation": 0.30, "fbp_film_fade_contrast_loss": 0.38},
        "Old Projection": {"fbp_film_fade_color": (0.82, 0.62, 0.30, 1.0), "fbp_film_fade_amount": 0.52, "fbp_film_fade_desaturation": 0.65, "fbp_film_fade_contrast_loss": 0.48},
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
    FBP_EFFECT_ASCII: {
        "Green Terminal": {
            "fbp_terminal_ascii_scale": 64.0,
            "fbp_terminal_ascii_contrast": 1.25,
            "fbp_terminal_ascii_fill_strength": 1.0,
            "fbp_terminal_ascii_use_edges": True,
            "fbp_terminal_ascii_edge_strength": 4.0,
            "fbp_terminal_ascii_edge_threshold": 0.08,
            "fbp_terminal_ascii_edge_mix": 1.0,
            "fbp_terminal_ascii_use_source_color": False,
            "fbp_terminal_ascii_foreground": (0.42, 1.0, 0.42, 1.0),
            "fbp_terminal_ascii_background": (0.0, 0.0, 0.0, 1.0),
            "fbp_terminal_ascii_transparent_background": False,
        },
        "Edges Only": {
            "fbp_terminal_ascii_fill_strength": 0.0,
            "fbp_terminal_ascii_use_edges": True,
            "fbp_terminal_ascii_edge_strength": 6.0,
            "fbp_terminal_ascii_edge_threshold": 0.06,
            "fbp_terminal_ascii_edge_mix": 1.0,
            "fbp_terminal_ascii_use_source_color": False,
            "fbp_terminal_ascii_foreground": (1.0, 1.0, 1.0, 1.0),
            "fbp_terminal_ascii_transparent_background": True,
        },
        "Source Color": {
            "fbp_terminal_ascii_scale": 72.0,
            "fbp_terminal_ascii_contrast": 1.4,
            "fbp_terminal_ascii_fill_strength": 1.15,
            "fbp_terminal_ascii_use_edges": True,
            "fbp_terminal_ascii_edge_strength": 3.5,
            "fbp_terminal_ascii_edge_threshold": 0.10,
            "fbp_terminal_ascii_edge_mix": 0.8,
            "fbp_terminal_ascii_use_source_color": True,
            "fbp_terminal_ascii_transparent_background": True,
        },
    },
    FBP_EFFECT_WIND_BENDER: {
        "Gentle Breeze": {"fbp_wind_bend_amount": 0.18, "fbp_wind_speed": 1.1, "fbp_wind_turbulence": 0.018, "fbp_wind_gust_strength": 0.12, "fbp_wind_falloff": 1.4},
        "Flag": {"fbp_wind_motion_mode": "FLOW", "fbp_wind_wave_count": 2.5, "fbp_wind_wave_amplitude": 0.16, "fbp_wind_wave_speed": 2.1, "fbp_wind_turbulence": 0.025, "fbp_wind_falloff": 1.0},
        "Strong Flag": {"fbp_wind_motion_mode": "FLOW", "fbp_wind_bend_amount": 0.42, "fbp_wind_speed": 2.4, "fbp_wind_wave_count": 3.2, "fbp_wind_wave_amplitude": 0.26, "fbp_wind_wave_speed": 3.0, "fbp_wind_turbulence": 0.055, "fbp_wind_gust_strength": 0.38, "fbp_wind_falloff": 0.9},
        "Strong Gusts": {"fbp_wind_bend_amount": 0.55, "fbp_wind_speed": 2.8, "fbp_wind_turbulence": 0.09, "fbp_wind_gust_strength": 0.65, "fbp_wind_noise_scale": 2.2},
        "Water Ripple": {"fbp_wind_motion_mode": "RIPPLE", "fbp_wind_ripple_direction": "RADIAL", "fbp_wind_wave_count": 5.0, "fbp_wind_wave_amplitude": 0.08, "fbp_wind_wave_speed": 1.4, "fbp_wind_pin_edge": "ALL", "fbp_wind_pin_strength": 0.35},
    },
    FBP_EFFECT_CRT_SCANLINES: {
        "VHS": {"fbp_crt_line_count": 420.0, "fbp_crt_opacity": 0.22},
        "Soft CRT": {"fbp_crt_line_count": 260.0, "fbp_crt_opacity": 0.10},
    },
    FBP_EFFECT_THICKNESS: {
        "Paper Cutout": {"fbp_thickness_mode": "VOLUME", "fbp_thickness_amount": 0.025, "fbp_thickness_direction": -1.0, "fbp_thickness_alpha_threshold": 0.05, "fbp_thickness_side_color": (0.22, 0.16, 0.10, 1.0)},
        "Cardboard": {"fbp_thickness_mode": "VOLUME", "fbp_thickness_amount": 0.08, "fbp_thickness_direction": -1.0, "fbp_thickness_alpha_threshold": 0.08, "fbp_thickness_side_color": (0.12, 0.08, 0.05, 1.0)},
        "Forward Relief": {"fbp_thickness_mode": "VOLUME", "fbp_thickness_amount": 0.04, "fbp_thickness_direction": 1.0, "fbp_thickness_alpha_threshold": 0.05, "fbp_thickness_side_color": (0.35, 0.35, 0.35, 1.0)},
        "Stacked Cels": {"fbp_thickness_mode": "ARRAY", "fbp_thickness_amount": 0.08, "fbp_thickness_direction": -1.0, "fbp_thickness_array_count": 18},
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
    except FBP_DATA_ERRORS:
        return None


def _fbp_write_effect_property(rig, prop_name, value):
    value = _fbp_deserialize_value(value)
    try:
        if hasattr(rig, prop_name):
            return fbp_set_rna_property_silent(rig, prop_name, value)
        rig[prop_name] = value
        return True
    except FBP_DATA_ERRORS:
        return False


def _fbp_capture_effect_color_ramp(rig, effect_id):
    node = fbp_effect_color_ramp_node(rig, effect_id)
    if node is None:
        return None
    try:
        ramp = node.color_ramp
        return {
            "interpolation": str(ramp.interpolation),
            "color_mode": str(ramp.color_mode),
            "hue_interpolation": str(ramp.hue_interpolation),
            "elements": [
                {
                    "position": float(element.position),
                    "color": [float(value) for value in element.color],
                }
                for element in ramp.elements
            ],
        }
    except FBP_DATA_ERRORS:
        return None


def _fbp_apply_effect_color_ramp_to_rigs(source_rig, effect_id, rigs, state=None):
    """Propagate one native Color Ramp to compatible selected layers."""
    state = state or _fbp_capture_effect_color_ramp(source_rig, effect_id)
    if _fbp_parse_effect_color_ramp_state(state) is None:
        return 0
    source_key = _fbp_effect_ids_cache_key(source_rig)
    changed = 0
    for target in _fbp_unique_live_rigs(source_rig, rigs):
        if _fbp_effect_ids_cache_key(target) == source_key:
            continue
        if not fbp_effect_is_active(target, effect_id):
            continue
        current = _fbp_capture_effect_color_ramp(target, effect_id)
        if _fbp_json_state_signature(current) == _fbp_json_state_signature(state):
            continue
        changed += int(_fbp_apply_effect_color_ramp(target, effect_id, state))
    return changed


def _fbp_schedule_effect_color_ramp_sync(source_rig, effect_id, rigs):
    """Mirror an edited ramp across a stable multi-selection outside UI draw."""
    targets = _fbp_unique_live_rigs(source_rig, rigs)
    if len(targets) < 2:
        return False
    state = _fbp_capture_effect_color_ramp(source_rig, effect_id)
    if _fbp_parse_effect_color_ramp_state(state) is None:
        return False
    source_key = _fbp_effect_ids_cache_key(source_rig)
    target_descriptors = tuple(
        (
            _fbp_effect_ids_cache_key(target),
            str(getattr(target, "name", "") or ""),
        )
        for target in targets
        if _fbp_effect_ids_cache_key(target) != source_key
        and fbp_effect_is_active(target, effect_id)
    )
    if not target_descriptors:
        return False
    key = (source_key, str(effect_id or ""), tuple(item[0] for item in target_descriptors))
    signature = _fbp_json_state_signature(state)
    previous = _FBP_COLOR_RAMP_SYNC_STATE_CACHE.get(key)
    _FBP_COLOR_RAMP_SYNC_STATE_CACHE[key] = signature
    if len(_FBP_COLOR_RAMP_SYNC_STATE_CACHE) > _FBP_COLOR_RAMP_SYNC_CACHE_LIMIT:
        # Selection keys are transient. Keeping only the current selection avoids
        # retaining stale object identities across long editing sessions.
        _FBP_COLOR_RAMP_SYNC_STATE_CACHE.clear()
        _FBP_COLOR_RAMP_SYNC_STATE_CACHE[key] = signature
    if previous is None or previous == signature:
        return False

    _FBP_COLOR_RAMP_SYNC_PENDING[key] = (state, target_descriptors)

    def _sync_latest():
        payload = _FBP_COLOR_RAMP_SYNC_PENDING.pop(key, None)
        if not payload:
            return None
        latest_state, descriptors = payload
        live_targets = []
        for runtime_key, name in descriptors:
            target = fbp_find_id_by_runtime_key(
                bpy.data.objects, runtime_key, name
            )
            if target is not None:
                live_targets.append(target)
        _fbp_apply_effect_color_ramp_to_rigs(
            source_rig, effect_id, live_targets, latest_state
        )
        return None

    try:
        from .safe_tasks import schedule_once
        scheduled = schedule_once(
            f"fbp_color_ramp_sync:{source_key[0]}:{effect_id}",
            _sync_latest,
            first_interval=0.03,
        )
        if not scheduled:
            # A runner for this selection may already be pending; its payload was
            # replaced above with the newest ramp state.
            return key in _FBP_COLOR_RAMP_SYNC_PENDING
        return True
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        _FBP_COLOR_RAMP_SYNC_PENDING.pop(key, None)
        return False

def _fbp_parse_effect_color_ramp_state(state):
    """Validate and normalize a serialized Color Ramp without touching RNA."""
    if not isinstance(state, dict):
        return None
    raw_elements = list(state.get("elements", ()) or ())
    if not 2 <= len(raw_elements) <= 32:
        return None

    parsed = []
    try:
        for item in raw_elements:
            if not isinstance(item, dict):
                return None
            position = float(item.get("position", 0.0))
            raw_color = tuple(item.get("color", ()))
            if len(raw_color) != 4:
                return None
            color = tuple(float(value) for value in raw_color)
            if not math.isfinite(position) or not all(
                math.isfinite(value) for value in color
            ):
                return None
            position = max(0.0, min(1.0, position))
            color = tuple(max(0.0, min(1.0, value)) for value in color)
            parsed.append((position, color))
        parsed.sort(key=lambda item: item[0])
    except (TypeError, ValueError, OverflowError):
        return None

    interpolation = str(state.get("interpolation", "") or "")
    color_mode = str(state.get("color_mode", "") or "")
    hue_interpolation = str(state.get("hue_interpolation", "") or "")
    if interpolation not in {"", "EASE", "CARDINAL", "LINEAR", "B_SPLINE", "CONSTANT"}:
        return None
    if color_mode not in {"", "RGB", "HSV", "HSL"}:
        return None
    if hue_interpolation not in {"", "NEAR", "FAR", "CW", "CCW"}:
        return None
    return parsed, interpolation, color_mode, hue_interpolation


def _fbp_write_effect_color_ramp_state(node, parsed_state):
    """Write one already validated Color Ramp payload to a node."""
    parsed, interpolation, color_mode, hue_interpolation = parsed_state
    ramp = node.color_ramp

    # Blender keeps at least two elements. Build the target count first, then
    # assign ordered values. Re-fetching the sequence avoids stale element
    # references when Blender reorders markers after a position change.
    while len(ramp.elements) > 2:
        ramp.elements.remove(ramp.elements[-1])
    while len(ramp.elements) < len(parsed):
        ramp.elements.new(parsed[len(ramp.elements)][0])

    # Place markers from left to right. Equal positions are legal and remain
    # deterministic because colors are assigned after every position update.
    for index, (position, _color) in enumerate(parsed):
        elements = list(ramp.elements)
        elements[index].position = position
    for index, (_position, color) in enumerate(parsed):
        elements = list(ramp.elements)
        elements[index].color = color

    if interpolation:
        ramp.interpolation = interpolation
    if color_mode:
        ramp.color_mode = color_mode
    if hue_interpolation:
        ramp.hue_interpolation = hue_interpolation
    node.id_data.update_tag()


def _fbp_apply_effect_color_ramp(rig, effect_id, state):
    """Atomically apply a validated serialized Color Ramp.

    Clipboard and user-preset data can outlive Blender enum changes or be
    edited manually. The complete payload is validated before touching RNA and
    the previous ramp is restored if Blender rejects any write mid-operation.
    """
    parsed_state = _fbp_parse_effect_color_ramp_state(state)
    node = fbp_effect_color_ramp_node(rig, effect_id)
    if parsed_state is None or node is None:
        return False

    previous = _fbp_capture_effect_color_ramp(rig, effect_id)
    previous_parsed = _fbp_parse_effect_color_ramp_state(previous)
    try:
        _fbp_write_effect_color_ramp_state(node, parsed_state)
        return True
    except FBP_DATA_ERRORS as exc:
        if previous_parsed is not None:
            try:
                _fbp_write_effect_color_ramp_state(node, previous_parsed)
            except FBP_DATA_ERRORS as rollback_exc:
                fbp_warn("Could not restore Color Ramp after a failed write", rollback_exc)
        fbp_warn("Could not apply Color Ramp state", exc)
        return False

def _fbp_reset_effect_color_ramp(rig, effect_id):
    definition = fbp_effect_definition(effect_id)
    if not definition.get("color_ramp_role"):
        return False
    target = fbp_effect_color_ramp_node(rig, effect_id)
    source_group = _fbp_load_effect_group(effect_id)
    if target is None or source_group is None:
        return False
    role = str(definition.get("color_ramp_role", "") or "")
    source = None
    try:
        source = next(
            node for node in source_group.nodes
            if getattr(node, "type", "") == "VALTORGB"
            and bool(node.get("fbp_effect_color_ramp", False))
            and str(node.get("fbp_effect_ramp_role", "") or "") == role
        )
    except (StopIteration, TypeError, AttributeError, ReferenceError, RuntimeError):
        return False
    try:
        state = {
            "interpolation": str(source.color_ramp.interpolation),
            "color_mode": str(source.color_ramp.color_mode),
            "hue_interpolation": str(source.color_ramp.hue_interpolation),
            "elements": [
                {"position": float(item.position), "color": list(item.color)}
                for item in source.color_ramp.elements
            ],
        }
    except FBP_DATA_ERRORS:
        return False
    return _fbp_apply_effect_color_ramp(rig, effect_id, state)


def _fbp_capture_effect_state(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    group_id = fbp_effect_group_id_for_rig(rig, effect_id)
    return {
        "effect_id": effect_id,
        "properties": {
            name: _fbp_serialize_value(_fbp_read_effect_property(rig, name))
            for name in _fbp_effect_property_names(effect_id)
        },
        "custom_inputs": _fbp_capture_custom_effect_inputs(rig, effect_id),
        "color_ramp": _fbp_capture_effect_color_ramp(rig, effect_id),
        "visible": fbp_effect_visible_state(rig, effect_id),
        "render_visible": fbp_effect_render_visible_state(rig, effect_id),
        "input_source": fbp_effect_input_source(rig, effect_id),
        "debug": fbp_effect_debug_mode(rig, effect_id),
        "mask_target": fbp_effect_mask_target(rig, effect_id) if _fbp_effect_is_local_mask(effect_id) else "LAYER",
        "group_id": group_id,
        "group_name": fbp_effect_group_name(rig, group_id),
        "group_collapsed": fbp_effect_group_collapsed(rig, group_id),
        "group_color_tag": fbp_effect_group_color_tag(rig, group_id),
    }


def fbp_capture_effect_state_snapshot(rig, effect_id):
    """Return a JSON-safe, read-only snapshot of one active effect.

    Diagnostics and persistence tests use the same serializer as presets and
    clipboard operations, so color ramps, custom inputs, visibility, local-mask
    routing and grouped-effect metadata are validated against the real public
    effect contract instead of a second partial implementation.
    """
    return _fbp_capture_effect_state(rig, effect_id)


def _fbp_validate_effect_state_for_rig(rig, state):
    """Return a normalized effect ID when a clipboard/preset state is usable."""
    if not isinstance(state, dict):
        return ""
    effect_id = fbp_normalize_effect_id(state.get("effect_id", ""))
    definition = fbp_effect_definition(effect_id)
    if not effect_id or not definition or not fbp_effect_supported_for_rig(rig, effect_id):
        return ""
    properties = state.get("properties", {})
    custom_inputs = state.get("custom_inputs", {})
    if properties is not None and not isinstance(properties, dict):
        return ""
    if custom_inputs is not None and not isinstance(custom_inputs, dict):
        return ""
    ramp_state = state.get("color_ramp")
    if ramp_state is not None:
        if not definition.get("color_ramp_role"):
            return ""
        if _fbp_parse_effect_color_ramp_state(ramp_state) is None:
            return ""
    return effect_id


def _fbp_apply_effect_state(
    rig,
    state,
    *,
    sync_items=True,
    defer_shader_rebuild=False,
    _allow_rollback=True,
):
    """Apply one captured effect state as a small recoverable transaction."""
    effect_id = _fbp_validate_effect_state_for_rig(rig, state)
    if not effect_id:
        return False

    was_active = fbp_effect_is_active(rig, effect_id)
    previous_state = (
        _fbp_capture_effect_state(rig, effect_id)
        if was_active and _allow_rollback else None
    )
    added = fbp_add_effect(
        rig,
        effect_id,
        inherit_active_group=False,
        sync_items=False,
        rebuild_shader=not bool(defer_shader_rebuild),
    )
    if not added and not fbp_effect_is_active(rig, effect_id):
        return False

    definition = fbp_effect_definition(effect_id)
    success = True
    allowed_properties = set(_fbp_effect_property_names(effect_id))
    for prop_name, value in dict(state.get("properties", {}) or {}).items():
        # Old clipboard/preset payloads may contain retired properties. Ignore
        # them, but never write arbitrary new IDProperties to the rig.
        if prop_name not in allowed_properties:
            continue
        if not _fbp_write_effect_property(rig, prop_name, value):
            success = False
            break

    if success:
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
            if effect_id == FBP_EFFECT_PIXELATE:
                _fbp_refresh_extrude_pixel_dependency(rig)

        ramp_state = state.get("color_ramp")
        if ramp_state is not None:
            success = _fbp_apply_effect_color_ramp(
                rig, effect_id, ramp_state
            ) and success
        _fbp_apply_custom_effect_inputs(
            rig, effect_id, state.get("custom_inputs", {})
        )
        fbp_set_effect_visible(rig, effect_id, bool(state.get("visible", True)))
        fbp_set_effect_render_visible(
            rig, effect_id, bool(state.get("render_visible", True))
        )
        default_source = str(
            definition.get("default_input_source", "PREVIOUS") or "PREVIOUS"
        )
        fbp_set_effect_input_source(
            rig, effect_id, state.get("input_source", default_source)
        )
        fbp_set_effect_debug_mode(rig, effect_id, state.get("debug", "FINAL"))
        if _fbp_effect_is_local_mask(effect_id):
            fbp_set_effect_mask_target(
                rig, effect_id, state.get("mask_target", "LAYER")
            )

        group_id = str(state.get("group_id", "") or "")
        group_ok = fbp_set_effect_group_id(
            rig,
            effect_id,
            group_id,
            group_name=str(state.get("group_name", "") or ""),
        )
        if group_id and not group_ok:
            success = False
        if success and group_id:
            fbp_set_effect_group_collapsed(
                rig, group_id, bool(state.get("group_collapsed", False))
            )
            record = _fbp_effect_group_record(rig, group_id)
            if record is not None:
                color_tag = str(state.get("group_color_tag", "NONE") or "NONE")
                valid_tags = {str(item[0]) for item in COLLECTION_COLOR_ENUM_ITEMS}
                if color_tag in valid_tags:
                    try:
                        record.color_tag = color_tag
                    except FBP_DATA_ERRORS:
                        pass

    if not success and _allow_rollback:
        if previous_state is not None:
            _fbp_apply_effect_state(
                rig,
                previous_state,
                sync_items=False,
                _allow_rollback=False,
            )
        elif not was_active:
            fbp_remove_effect(rig, effect_id, sync_items=False)
        if sync_items:
            fbp_sync_effect_items(rig)
        return False

    if sync_items:
        fbp_sync_effect_items(rig)
    return bool(success)

def _fbp_apply_captured_stack_order(
    rig, states, *, force_shader_rebuild=False
):
    """Restore copied effect order without disturbing unrelated Blender modifiers."""
    desired_ids = [
        fbp_normalize_effect_id(state.get("effect_id", ""))
        for state in list(states or ())
        if fbp_normalize_effect_id(state.get("effect_id", "")) in FBP_EFFECT_REGISTRY
    ]
    changed = False

    for stage in ("UV", "COLOR", "MASK"):
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
            order_changed = merged != current
            if order_changed:
                _fbp_set_shader_stage_order(material, stage, merged)
                changed = True
            if order_changed or force_shader_rebuild:
                changed = _fbp_rebuild_shader_stage(material, stage) or changed
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
        except FBP_DATA_ERRORS:
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
        if "color_ramp" in values:
            state["color_ramp"] = dict(values.get("color_ramp", {}) or {})
        if "mask_target" in values:
            state["mask_target"] = str(values.get("mask_target", "LAYER") or "LAYER")
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
            group_id = fbp_active_effect_group_id(rig)
            if group_id:
                members = fbp_effect_group_members_from_items(rig, group_id)
                effect_id = members[0] if members else ""
            if not effect_id:
                effect_ids = _fbp_runtime_effect_ids(rig)
                if effect_ids:
                    effect_id = effect_ids[0]
        if not effect_id:
            layout.label(text="No active effect", icon="INFO")
            return
        definition = fbp_effect_definition(effect_id) or {}
        layout.label(
            text=_fbp_effect_display_label(effect_id, definition),
            icon=str(definition.get("icon", "MODIFIER")),
        )
        layout.separator()
        builtins = FBP_BUILTIN_EFFECT_PRESETS.get(effect_id, {})
        users = _fbp_load_user_presets().get(effect_id, {}) or {}
        if builtins:
            layout.label(text="Built-in", icon="PRESET")
            for name in builtins:
                op = layout.operator("fbp.apply_effect_preset", text=name, icon="CHECKMARK")
                op.effect_id = effect_id
                op.preset_name = name
                op.user_preset = False
        layout.separator()
        layout.label(text="User", icon="USER")
        if users:
            for name in sorted(users, key=lambda item: str(item).casefold()):
                row = layout.row(align=True)
                op = row.operator("fbp.apply_effect_preset", text=name, icon="PRESET")
                op.effect_id = effect_id
                op.preset_name = name
                op.user_preset = True
                rename_slot = row.row(align=True)
                rename_slot.operator_context = 'INVOKE_DEFAULT'
                rename = rename_slot.operator("fbp.rename_effect_preset", text="", icon="GREASEPENCIL")
                rename.effect_id = effect_id
                rename.preset_name = name
                rename.new_name = name
                delete_slot = row.row(align=True)
                delete_slot.operator_context = 'INVOKE_DEFAULT'
                delete = delete_slot.operator("fbp.delete_effect_preset", text="", icon="X")
                delete.effect_id = effect_id
                delete.preset_name = name
        else:
            muted = layout.row()
            muted.enabled = False
            muted.label(text="No saved user presets", icon="INFO")
        layout.separator()
        save_row = layout.row(align=True)
        save_row.operator_context = 'INVOKE_DEFAULT'
        save_row.operator("fbp.save_effect_preset", text="Save Current Preset", icon="ADD")


class FBP_OT_OpenEffectPresets(Operator):
    bl_idname = "fbp.open_effect_presets"
    bl_label = "Effect Presets"
    bl_description = "Open presets for the effect shown in this settings panel"
    bl_options = {"INTERNAL"}

    effect_id: StringProperty(default="", options={"SKIP_SAVE"})

    def invoke(self, context, _event):
        rigs = _fbp_selected_rigs(context)
        effect_id = fbp_normalize_effect_id(self.effect_id)
        if not rigs or not effect_id:
            return {"CANCELLED"}
        _fbp_select_effect_row(rigs[0], effect_id, rigs)
        try:
            return bpy.ops.wm.call_menu(name="FBP_MT_effect_presets")
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}

    def execute(self, context):
        return self.invoke(context, None)


class FBP_OT_OpenEffectToolbarMenu(Operator):
    bl_idname = "fbp.open_effect_toolbar_menu"
    bl_label = "Open Effect Tools"
    bl_options = {"INTERNAL"}

    menu: EnumProperty(
        name="Menu",
        items=(
            ("ADD", "Add Effect", "Open the effect library for the active category"),
            ("GROUP", "Effect Groups", "Create, edit, select or ungroup Effect Groups"),
            ("ACTIONS", "Effect Stack Actions", "Copy, paste, sort, select, show or clear effects"),
        ),
        default="ACTIONS",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def description(cls, _context, properties):
        return {
            "ADD": "Add an effect to the selected Frame By Plane layers",
            "GROUP": "Manage persistent Effect Groups",
            "ACTIONS": "Open compact actions for the current effect stack",
        }.get(str(getattr(properties, "menu", "ACTIONS") or "ACTIONS"), cls.bl_label)

    def invoke(self, _context, _event):
        menu_name = {
            "ADD": "FBP_MT_add_effect",
            "GROUP": "FBP_MT_effect_group_tools",
            "ACTIONS": "FBP_MT_effect_stack_actions",
        }.get(str(self.menu or "ACTIONS"), "FBP_MT_effect_stack_actions")
        try:
            return bpy.ops.wm.call_menu(name=menu_name)
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}

    def execute(self, context):
        return self.invoke(context, None)


class FBP_MT_MoveSelectedEffects(Menu):
    bl_idname = "FBP_MT_move_selected_effects"
    bl_label = "Move Selected Before / After"

    def draw(self, context):
        layout = self.layout
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            layout.label(text="No Frame by Plane layer selected", icon="INFO")
            return
        rig = rigs[0]
        selected = fbp_selected_effect_ids(
            rig,
            fallback_active=True,
            movable_only=True,
            categories=_fbp_effect_view_categories(context),
        )
        selected = fbp_expand_effect_selection_to_groups(rig, selected)
        if any(
            fbp_effect_presence(rigs, effect_id)[0] != len(rigs)
            for effect_id in selected
        ):
            layout.label(
                text="Copy every checked effect to all selected layers first",
                icon="ERROR",
            )
            return
        chain_keys = {_fbp_effect_chain_key(effect_id) for effect_id in selected}
        chain_keys.discard(("", ""))
        if len(chain_keys) != 1:
            layout.label(text="Select effects from one compatible chain", icon="ERROR")
            return
        chain_key = next(iter(chain_keys))
        order = _fbp_effect_chain_ids(rig, chain_key)
        selected_set = set(selected)
        targets = [effect_id for effect_id in order if effect_id not in selected_set]
        if not targets:
            layout.label(text="No compatible destination effect", icon="INFO")
            return
        layout.label(text="Move Before", icon="TRIA_UP")
        for target in targets:
            definition = fbp_effect_definition(target)
            op = layout.operator(
                "fbp.move_selected_effects_relative",
                text=_fbp_effect_display_label(target, definition),
                icon=str(definition.get("icon", "MODIFIER")),
            )
            op.target_effect_id = target
            op.placement = "BEFORE"
        layout.separator()
        layout.label(text="Move After", icon="TRIA_DOWN")
        for target in targets:
            definition = fbp_effect_definition(target)
            op = layout.operator(
                "fbp.move_selected_effects_relative",
                text=_fbp_effect_display_label(target, definition),
                icon=str(definition.get("icon", "MODIFIER")),
            )
            op.target_effect_id = target
            op.placement = "AFTER"


class FBP_MT_EffectVisibilityActions(Menu):
    bl_idname = "FBP_MT_effect_visibility_actions"
    bl_label = "Effect Visibility Actions"

    def draw(self, _context):
        layout = self.layout
        for text, mode, icon in (
            ("Show Selected in Viewport", "SHOW_SELECTED", "HIDE_OFF"),
            ("Hide Selected in Viewport", "HIDE_SELECTED", "HIDE_ON"),
            ("Solo Selected in Viewport", "SOLO_SELECTED", "CHECKMARK"),
            ("Enable All in Viewport", "SHOW_ALL", "HIDE_OFF"),
        ):
            op = layout.operator("fbp.set_selected_effects_visibility", text=text, icon=icon)
            op.channel = "VIEWPORT"
            op.mode = mode
        layout.separator()
        for text, mode, icon in (
            ("Show Selected in Render", "SHOW_SELECTED", "RESTRICT_RENDER_OFF"),
            ("Hide Selected in Render", "HIDE_SELECTED", "RESTRICT_RENDER_ON"),
            ("Solo Selected in Render", "SOLO_SELECTED", "CHECKMARK"),
            ("Enable All in Render", "SHOW_ALL", "RESTRICT_RENDER_OFF"),
        ):
            op = layout.operator("fbp.set_selected_effects_visibility", text=text, icon=icon)
            op.channel = "RENDER"
            op.mode = mode


class FBP_MT_EffectStackActions(Menu):
    bl_idname = "FBP_MT_effect_stack_actions"
    bl_label = "Effect Stack Actions"

    def draw(self, _context):
        layout = self.layout
        # Copy follows the checked rows and falls back to the active row when
        # nothing is checked.  One clear action replaces three overlapping
        # clipboard commands in the old menu.
        layout.operator("fbp.copy_selected_effects", text="Copy", icon="COPYDOWN")
        layout.operator("fbp.paste_effect_stack", text="Paste", icon="PASTEDOWN")
        layout.separator()
        layout.operator("fbp.sort_effect_stack", icon="SORT_DESC")
        layout.menu(
            "FBP_MT_effect_visibility_actions",
            text="Visibility Actions",
            icon="HIDE_OFF",
        )
        layout.separator()
        select_all = layout.operator("fbp.set_effect_selection", text="Select All Effects", icon="CHECKBOX_HLT")
        select_all.mode = "ALL"
        invert = layout.operator("fbp.set_effect_selection", text="Invert Effect Selection", icon="SELECT_SUBTRACT")
        invert.mode = "INVERT"
        clear_selection = layout.operator("fbp.set_effect_selection", text="Clear Effect Selection", icon="CHECKBOX_DEHLT")
        clear_selection.mode = "NONE"
        layout.separator()
        layout.operator("fbp.clear_effect_stack", icon="TRASH")


class FBP_MT_EffectGroupTools(Menu):
    bl_idname = "FBP_MT_effect_group_tools"
    bl_label = "Effect Group Tools"

    def draw(self, context):
        layout = self.layout
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            layout.label(text="No Frame By Plane layer selected", icon="INFO")
            return
        rig = rigs[0]
        active_effect = fbp_active_effect_id(rig)
        group_id = fbp_active_effect_group_id(rig)
        if not group_id and active_effect:
            group_id = fbp_effect_group_id_for_rig(
                rig, active_effect, normalize=False
            )

        layout.operator("fbp.create_effect_group", icon="COLLECTION_NEW")
        if group_id:
            active = layout.operator(
                "fbp.effect_group_actions",
                text="Active Group Settings",
                icon=fbp_collection_color_icon(
                    getattr(_fbp_effect_group_record(rig, group_id), "color_tag", "NONE")
                ),
            )
            active.group_id = group_id
            layout.operator("fbp.select_active_effect_group", icon="RESTRICT_SELECT_OFF")
        else:
            muted = layout.row()
            muted.enabled = False
            muted.label(text="Active effect is not grouped", icon="INFO")
        layout.separator()
        selected_effects = fbp_selected_effect_ids(
            rig, fallback_active=True
        )
        can_ungroup = any(
            bool(fbp_effect_group_id_for_rig(rig, effect_id, normalize=False))
            for effect_id in selected_effects
        )
        ungroup_row = layout.row()
        ungroup_row.enabled = can_ungroup
        ungroup_row.operator("fbp.ungroup_selected_effects", icon="UNLINKED")


class FBP_OT_EffectHeaderWarning(Operator):
    bl_idname = "fbp.effect_header_warning"
    bl_label = "Effect Warning"
    bl_options = {"INTERNAL"}

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", default="", options={"SKIP_SAVE"})
    message: StringProperty(description="Diagnostic message describing the sequence or generation problem.", default="", options={"SKIP_SAVE"})
    fix_order: BoolProperty(description="When enabled, clicking the warning automatically restores the recommended compatible effect order.", default=False, options={"SKIP_SAVE"})

    @classmethod
    def description(cls, _context, properties):
        message = str(getattr(properties, "message", "") or "Effect warning")
        if bool(getattr(properties, "fix_order", False)):
            message += "\nClick to restore the recommended effect order"
        return message

    def execute(self, context):
        if not self.fix_order:
            return {"FINISHED"}
        recommended = (
            list(FBP_BASE_EFFECT_MENU_ORDER)
            + list(FBP_SHADER_STAGE_ORDER["UV"])
            + list(FBP_SHADER_STAGE_ORDER["COLOR"])
            + list(FBP_SHADER_STAGE_ORDER["MASK"])
            + list(FBP_3D_EFFECT_MENU_ORDER)
        )
        changed = fbp_sort_effect_stacks_transactional(
            _fbp_selected_rigs(context), recommended
        )
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_SetEffectInputSource(Operator):
    bl_idname = "fbp.set_effect_input_source"
    bl_label = "Set Effect Input Source"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", default="", options={"SKIP_SAVE"})
    source: EnumProperty(description="Material stage selected as the input of this effect: previous compatible effects, the untouched original material, or the completed final material.",
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
    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", default="", options={"SKIP_SAVE"})
    mode: StringProperty(description="Operation mode passed to this Frame By Plane action. The available meaning depends on the button or menu entry that invoked it.", default="FINAL", options={"SKIP_SAVE"})

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


class FBP_OT_CopySelectedEffects(Operator):
    bl_idname = "fbp.copy_selected_effects"
    bl_label = "Copy Selected Effects"
    bl_description = "Copy checked effects in their current relative order; when nothing is checked, copy the active effect"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        rig = rigs[0]
        fbp_sync_effect_items(rig, rigs)
        effect_ids = fbp_selected_effect_ids(
            rig,
            fallback_active=True,
            categories=_fbp_effect_view_categories(context),
        )
        effect_ids = [
            effect_id for effect_id in effect_ids
            if fbp_effect_is_active(rig, effect_id)
        ]
        if not effect_ids:
            return {"CANCELLED"}
        effects = [_fbp_capture_effect_state(rig, effect_id) for effect_id in effect_ids]
        _FBP_EFFECT_CLIPBOARD.clear()
        _FBP_EFFECT_CLIPBOARD.update({"mode": "SELECTION", "effects": effects})
        self.report({"INFO"}, f"Copied {len(effects)} selected effect(s)")
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
        rigs = _fbp_selected_rigs(context)
        states = list(_FBP_EFFECT_CLIPBOARD.get("effects", ()))
        if not rigs or not states:
            return {"CANCELLED"}

        # Refuse malformed or unavailable custom effects before changing any
        # selected layer. This avoids a partially pasted multi-layer stack.
        invalid = [
            (rig, state)
            for rig in rigs
            for state in states
            if not _fbp_validate_effect_state_for_rig(rig, state)
        ]
        if invalid:
            self.report(
                {"ERROR"},
                "Paste cancelled: one or more effects are invalid or incompatible",
            )
            return {"CANCELLED"}

        snapshots = [
            (
                rig,
                [
                    _fbp_capture_effect_state(rig, effect_id)
                    for effect_id in fbp_effect_ids_for_rig(rig)
                ],
            )
            for rig in rigs
        ]
        changed = 0
        failed = False
        for rig in rigs:
            for state in states:
                if not _fbp_apply_effect_state(
                    rig,
                    state,
                    sync_items=False,
                    defer_shader_rebuild=True,
                ):
                    failed = True
                    break
                changed += 1
            if failed:
                break
            # Local masks can target effects pasted later in the same batch.
            # Resolve those references after every target effect exists.
            for state in states:
                mask_id = fbp_normalize_effect_id(state.get("effect_id", ""))
                if _fbp_effect_is_local_mask(mask_id):
                    fbp_set_effect_mask_target(
                        rig, mask_id, state.get("mask_target", "LAYER")
                    )
            _fbp_apply_captured_stack_order(
                rig, states, force_shader_rebuild=True
            )

        if failed:
            # Restore every selected layer, including those completed before a
            # later layer failed. Rollback is deliberately slower than paste;
            # it only runs on exceptional Blender RNA/data errors.
            for rig, previous_states in snapshots:
                previous_ids = {
                    fbp_normalize_effect_id(state.get("effect_id", ""))
                    for state in previous_states
                }
                for effect_id in tuple(fbp_effect_ids_for_rig(rig)):
                    if effect_id not in previous_ids:
                        fbp_remove_effect(rig, effect_id, sync_items=False)
                for state in previous_states:
                    _fbp_apply_effect_state(
                        rig,
                        state,
                        sync_items=False,
                        _allow_rollback=False,
                    )
                _fbp_apply_captured_stack_order(rig, previous_states)
                fbp_sync_effect_items(rig)
            self.report(
                {"ERROR"},
                "Paste failed; every selected layer was restored",
            )
            return {"CANCELLED"}

        fbp_sync_effect_items(
            rigs[0], rigs, repair_assets=False, normalize_instance_ids=False
        )
        self.report(
            {"INFO"},
            f"Pasted {len(states)} effect(s) to {len(rigs)} layer(s)",
        )
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_ClearEffectStack(Operator):
    bl_idname = "fbp.clear_effect_stack"
    bl_label = "Clear Effect Stack"
    bl_description = "Remove every effect from all selected Frame By Plane layers"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        changed = 0
        for rig in rigs:
            for effect_id in tuple(fbp_effect_ids_for_rig(rig)):
                changed += int(
                    fbp_remove_effect(rig, effect_id, sync_items=False)
                )
        if changed and rigs:
            fbp_sync_effect_items(
                rigs[0], rigs,
                repair_assets=False,
                normalize_instance_ids=False,
            )
            self.report(
                {"INFO"},
                f"Cleared {changed} effect(s) from {len(rigs)} layer(s)",
            )
            return {"FINISHED"}
        return {"CANCELLED"}


class FBP_OT_ResetActiveEffect(Operator):
    bl_idname = "fbp.reset_active_effect"
    bl_label = "Reset Active Effect"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(
        description="Optional explicit effect shown by the settings panel",
        default="",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        effect_id = fbp_normalize_effect_id(self.effect_id) or fbp_active_effect_id(rigs[0])
        if not effect_id:
            return {"CANCELLED"}
        compatible = [
            rig for rig in rigs if fbp_effect_is_active(rig, effect_id)
        ]
        if not compatible:
            self.report({"WARNING"}, "The selected effect is not active on these layers")
            return {"CANCELLED"}

        for rig in compatible:
            for prop_name in _fbp_effect_property_names(effect_id):
                try:
                    prop = rig.bl_rna.properties.get(prop_name)
                    if prop is None:
                        continue
                    value = tuple(prop.default_array) if getattr(prop, "is_array", False) else prop.default
                    fbp_set_rna_property_silent(rig, prop_name, value)
                except FBP_DATA_ERRORS:
                    continue
            definition = fbp_effect_definition(effect_id)
            if effect_id == FBP_EFFECT_LATTICE:
                # The standard header Reset is the single recovery action for
                # Lattice: restore defaults, refit to the current plane and
                # rebuild a clean cage/modifier contract in one undoable step.
                _fbp_apply_lattice_grid_settings(rig)
                _fbp_cleanup_incomplete_lattice_setup(rig, force=True)
                _fbp_set_enabled(rig, FBP_EFFECT_LATTICE, True)
                if not _fbp_apply_lattice_effect(rig, select=False):
                    self.report({"ERROR"}, _fbp_last_lattice_error(rig) or "Lattice reset failed")
                    return {"CANCELLED"}
                continue
            if definition.get("evolve_property"):
                fbp_reset_effect_animation_state(rig, effect_id)
                fbp_ensure_effect_animation_state(rig, effect_id)
            if bool(definition.get("custom", False)):
                _fbp_reset_custom_effect_inputs(rig, effect_id)
            _fbp_reset_effect_color_ramp(rig, effect_id)
            default_source = str(definition.get("default_input_source", "PREVIOUS") or "PREVIOUS")
            fbp_set_effect_input_source(rig, effect_id, default_source)
            fbp_set_effect_debug_mode(rig, effect_id, "FINAL")
            if _fbp_effect_is_local_mask(effect_id):
                fbp_set_effect_mask_target(rig, effect_id, "LAYER")
            if definition.get("kind") == "GEOMETRY":
                fbp_update_geometry_effect(rig, effect_id)
            elif definition.get("kind") == "SHADER":
                fbp_update_shader_effect(rig, effect_id)

        fbp_sync_effect_items(
            compatible[0], compatible,
            repair_assets=False,
            normalize_instance_ids=False,
        )
        suffix = (
            f" of {len(rigs)} selected" if len(compatible) != len(rigs) else ""
        )
        self.report(
            {"INFO"},
            f"Reset effect on {len(compatible)}{suffix} layer(s)",
        )
        return {"FINISHED"}


class FBP_OT_SortEffectStack(Operator):
    bl_idname = "fbp.sort_effect_stack"
    bl_label = "Sort to Recommended Order"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        recommended = (
            list(FBP_BASE_EFFECT_MENU_ORDER)
            + list(FBP_SHADER_STAGE_ORDER["UV"])
            + list(FBP_SHADER_STAGE_ORDER["COLOR"])
            + list(FBP_SHADER_STAGE_ORDER["MASK"])
            + list(FBP_3D_EFFECT_MENU_ORDER)
        )
        changed = fbp_sort_effect_stacks_transactional(
            _fbp_selected_rigs(context), recommended
        )
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_ApplyEffectPreset(Operator):
    bl_idname = "fbp.apply_effect_preset"
    bl_label = "Apply Effect Preset"
    bl_options = {"REGISTER", "UNDO"}
    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", default="", options={"SKIP_SAVE"})
    preset_name: StringProperty(description="Name of the built-in or user effect preset targeted by this action.", default="", options={"SKIP_SAVE"})
    user_preset: BoolProperty(description="Distinguish a user-saved preset from a built-in preset when applying effect values.", default=False, options={"SKIP_SAVE"})

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
    preset_name: StringProperty(
        name="Name",
        description="Name used to store this effect setup in the user preset library. Names must be unique for the active effect",
        default="My Preset",
    )

    def invoke(self, context, _event):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        effect_id = fbp_active_effect_id(rigs[0])
        if not effect_id:
            self.report({"ERROR"}, "Select an effect before saving a preset")
            return {"CANCELLED"}
        existing = _fbp_load_user_presets().get(effect_id, {})
        base = "My Preset"
        candidate = base
        suffix = 2
        existing_folded = {str(name).casefold() for name in existing}
        while candidate.casefold() in existing_folded:
            candidate = f"{base} {suffix}"
            suffix += 1
        self.preset_name = candidate
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, _context):
        column = self.layout.column(align=False)
        column.label(text="Save current active-effect settings", icon="PRESET")
        column.prop(self, "preset_name", text="Preset Name")

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
        existing = data.get(effect_id, {})
        folded_name = name.casefold()
        if any(str(existing_name).casefold() == folded_name for existing_name in existing):
            self.report({"ERROR"}, "A user preset with this name already exists")
            return {"CANCELLED"}
        definition = fbp_effect_definition(effect_id)
        if (
            bool(definition.get("custom", False))
            or _fbp_effect_is_local_mask(effect_id)
            or bool(definition.get("color_ramp_role"))
        ):
            preset_value = {
                "__fbp_state__": 1,
                "properties": state["properties"],
                "custom_inputs": state.get("custom_inputs", {}),
            }
            if definition.get("color_ramp_role"):
                preset_value["color_ramp"] = state.get("color_ramp")
            if _fbp_effect_is_local_mask(effect_id):
                preset_value["mask_target"] = state.get("mask_target", "LAYER")
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
    bl_options = {"REGISTER"}

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", default="", options={"SKIP_SAVE"})
    preset_name: StringProperty(description="Name of the built-in or user effect preset targeted by this action.", default="", options={"SKIP_SAVE"})
    new_name: StringProperty(
        name="Name",
        description="New unique name for this user preset. Preset values and effect compatibility are preserved",
        default="My Preset",
    )

    def invoke(self, context, _event):
        old_name = str(self.preset_name or "").strip()
        if not self.effect_id or old_name not in _fbp_load_user_presets().get(self.effect_id, {}):
            self.report({"ERROR"}, "Preset no longer exists")
            return {"CANCELLED"}
        self.new_name = old_name
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, _context):
        column = self.layout.column(align=False)
        column.label(text=f"Rename user preset: {self.preset_name}", icon="PRESET")
        column.prop(self, "new_name", text="New Name")

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
        if new_name.casefold() != old_name.casefold() and any(
            str(name).casefold() == new_name.casefold() for name in presets
        ):
            self.report({"ERROR"}, "A preset with this name already exists")
            return {"CANCELLED"}
        if new_name == old_name:
            return {"FINISHED"}
        value = presets.pop(old_name)
        presets[new_name] = value
        data[self.effect_id] = presets
        if not _fbp_save_user_presets(data):
            self.report({"ERROR"}, "Could not rename preset; the preset library was not changed")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Renamed preset to {new_name}")
        return {"FINISHED"}


class FBP_OT_DeleteEffectPreset(Operator):
    bl_idname = "fbp.delete_effect_preset"
    bl_label = "Delete Effect Preset"
    bl_options = {"INTERNAL"}
    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", default="", options={"SKIP_SAVE"})
    preset_name: StringProperty(description="Name of the built-in or user effect preset targeted by this action.", default="", options={"SKIP_SAVE"})

    def invoke(self, context, event):
        if self.preset_name not in _fbp_load_user_presets().get(self.effect_id, {}):
            self.report({"ERROR"}, "Preset no longer exists")
            return {"CANCELLED"}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, _context):
        data = _fbp_load_user_presets()
        presets = data.get(self.effect_id, {})
        if self.preset_name not in presets:
            return {"CANCELLED"}
        del presets[self.preset_name]
        if not presets:
            data.pop(self.effect_id, None)
        if not _fbp_save_user_presets(data):
            self.report({"ERROR"}, "Could not delete preset; the preset library was not changed")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Deleted preset {self.preset_name}")
        return {"FINISHED"}


class FBP_OT_CopyCustomEffectValuesToSelected(Operator):
    bl_idname = "fbp.copy_custom_effect_values_to_selected"
    bl_label = "Copy Custom Effect Values to Selected"
    bl_description = "Copy the active layer custom node socket values to every selected Frame by Plane layer"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", name="Effect ID", default="", options={"SKIP_SAVE"})

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

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", name="Effect ID", default="", options={"SKIP_SAVE"})

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
                except FBP_DATA_ERRORS:
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

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", name="Effect ID", default="", options={"SKIP_SAVE"})
    visible: BoolProperty(description="Requested viewport or render visibility state for this effect.", name="Visible", default=True, options={"SKIP_SAVE"})

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


def _fbp_effect_chain_ids_for_effect(rig, effect_id):
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
        except FBP_DATA_ERRORS:
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
    current = _fbp_effect_chain_ids_for_effect(rig, effect_id)
    recommended = _fbp_recommended_chain(effect_id)
    if effect_id not in current or not recommended:
        return ""
    rank = {item: index for index, item in enumerate(recommended)}
    original_positions = {item: index for index, item in enumerate(current)}
    expected = sorted(
        current,
        key=lambda item: (rank.get(item, len(rank)), original_positions.get(item, 0)),
    )
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


def _fbp_effect_chain_key(effect_id):
    definition = fbp_effect_definition(effect_id)
    kind = str(definition.get("kind", "") or "")
    if kind == "GEOMETRY":
        return ("GEOMETRY", "")
    if kind == "SHADER":
        return ("SHADER", str(definition.get("stage", "") or ""))
    return ("", "")


def _fbp_effect_chain_ids(rig, chain_key):
    kind, stage = chain_key
    if kind == "GEOMETRY":
        plane = _fbp_plane(rig)
        if not plane:
            return []
        result = []
        seen = set()
        try:
            for modifier in plane.modifiers:
                effect_id = _fbp_geometry_effect_id_for_modifier(modifier)
                if not effect_id or effect_id in seen:
                    continue
                seen.add(effect_id)
                result.append(effect_id)
        except FBP_DATA_ERRORS:
            return []
        return result
    if kind == "SHADER":
        order = _fbp_get_rig_shader_stage_order(rig, stage)
        active = []
        active_set = set()
        for material in _fbp_plane_materials(rig):
            for node in _fbp_shader_effect_nodes(material, stage=stage):
                effect_id = _fbp_shader_effect_id(node)
                if not effect_id or effect_id in active_set:
                    continue
                active_set.add(effect_id)
                active.append(effect_id)
        result = [effect_id for effect_id in order if effect_id in active_set]
        result_set = set(result)
        result.extend(effect_id for effect_id in active if effect_id not in result_set)
        return result
    return []


def _fbp_selection_action_would_change(rig, effect_ids, action):
    action = str(action or "UP").upper()
    requested = {fbp_normalize_effect_id(effect_id) for effect_id in effect_ids}
    chains = {}
    for effect_id in requested:
        key = _fbp_effect_chain_key(effect_id)
        if key[0]:
            chains.setdefault(key, set()).add(effect_id)
    for key, selected_set in chains.items():
        order = _fbp_effect_chain_ids(rig, key)
        selected = [effect_id for effect_id in order if effect_id in selected_set]
        if not selected:
            continue
        positions = [order.index(effect_id) for effect_id in selected]
        if action == "UP" and any(
            index > 0 and order[index - 1] not in selected_set for index in positions
        ):
            return True
        if action == "DOWN" and any(
            index < len(order) - 1 and order[index + 1] not in selected_set
            for index in positions
        ):
            return True
        if action == "TOP" and positions != list(range(len(selected))):
            return True
        if action == "BOTTOM":
            target = list(range(len(order) - len(selected), len(order)))
            if positions != target:
                return True
    return False


def _fbp_move_effect_selection_on_rig(rig, effect_ids, action):
    action = str(action or "UP").upper()
    requested = {fbp_normalize_effect_id(effect_id) for effect_id in effect_ids}
    chains = {}
    for effect_id in requested:
        key = _fbp_effect_chain_key(effect_id)
        if key[0]:
            chains.setdefault(key, set()).add(effect_id)
    changed = False
    for key, selected_set in chains.items():
        order = _fbp_effect_chain_ids(rig, key)
        selected = [effect_id for effect_id in order if effect_id in selected_set]
        if not selected:
            continue
        if action == "UP":
            for effect_id in selected:
                current = _fbp_effect_chain_ids(rig, key)
                index = current.index(effect_id) if effect_id in current else -1
                if index > 0 and current[index - 1] not in selected_set:
                    changed = fbp_move_effect(
                        rig, effect_id, "UP", sync_items=False
                    ) or changed
        elif action == "DOWN":
            for effect_id in reversed(selected):
                current = _fbp_effect_chain_ids(rig, key)
                index = current.index(effect_id) if effect_id in current else -1
                if 0 <= index < len(current) - 1 and current[index + 1] not in selected_set:
                    changed = fbp_move_effect(
                        rig, effect_id, "DOWN", sync_items=False
                    ) or changed
        elif action == "TOP":
            for target_index, effect_id in enumerate(selected):
                while True:
                    current = _fbp_effect_chain_ids(rig, key)
                    if effect_id not in current or current.index(effect_id) <= target_index:
                        break
                    if not fbp_move_effect(rig, effect_id, "UP", sync_items=False):
                        return False
                    changed = True
        elif action == "BOTTOM":
            first_target = len(order) - len(selected)
            for offset, effect_id in reversed(tuple(enumerate(selected))):
                target_index = first_target + offset
                while True:
                    current = _fbp_effect_chain_ids(rig, key)
                    if effect_id not in current or current.index(effect_id) >= target_index:
                        break
                    if not fbp_move_effect(rig, effect_id, "DOWN", sync_items=False):
                        return False
                    changed = True
    return changed


def _fbp_effect_chain_snapshots(rig, effect_ids):
    snapshots = {}
    for effect_id in effect_ids:
        key = _fbp_effect_chain_key(effect_id)
        if key[0] and key not in snapshots:
            snapshots[key] = tuple(_fbp_effect_chain_ids(rig, key))
    return snapshots


def _fbp_restore_effect_chain_snapshots(rig, snapshots):
    restored = True
    for key, desired in snapshots.items():
        for target_index, effect_id in enumerate(desired):
            while True:
                current = _fbp_effect_chain_ids(rig, key)
                if effect_id not in current:
                    restored = False
                    break
                current_index = current.index(effect_id)
                if current_index <= target_index:
                    break
                if not fbp_move_effect(rig, effect_id, "UP", sync_items=False):
                    restored = False
                    break
    return restored


def _fbp_capture_effect_group_state(rig):
    """Capture every group assignment and folder display property on one rig."""
    effect_ids = tuple(fbp_effect_ids_for_rig(rig))
    groups = fbp_sync_effect_groups(rig, effect_ids=effect_ids)
    assignments = {
        effect_id: group_id
        for group_id, members in groups.items()
        for effect_id in members
    }
    records = {}
    try:
        for record in getattr(rig, "fbp_effect_groups", ()):
            group_id = str(getattr(record, "group_id", "") or "")
            if not group_id:
                continue
            records[group_id] = {
                "name": str(getattr(record, "group_name", "") or "Effect Group"),
                "collapsed": bool(getattr(record, "collapsed", False)),
                "color_tag": str(getattr(record, "color_tag", "NONE") or "NONE"),
            }
    except FBP_DATA_ERRORS:
        records = {}
    return {
        "assignments": assignments,
        "records": records,
    }


def _fbp_restore_effect_group_state(rig, state):
    """Restore a group snapshot after a cancelled or failed drag transaction."""
    state = dict(state or {})
    assignments = dict(state.get("assignments", {}) or {})
    records = dict(state.get("records", {}) or {})
    effect_ids = tuple(fbp_effect_ids_for_rig(rig))

    for effect_id in effect_ids:
        fbp_set_effect_group_id(rig, effect_id, "")
    try:
        while len(rig.fbp_effect_groups):
            rig.fbp_effect_groups.remove(len(rig.fbp_effect_groups) - 1)
    except FBP_DATA_ERRORS:
        pass

    for group_id, metadata in records.items():
        record = fbp_ensure_effect_group_record(
            rig, group_id, str(metadata.get("name", "") or "Effect Group")
        )
        if record is None:
            continue
        try:
            record.collapsed = bool(metadata.get("collapsed", False))
            record.color_tag = str(metadata.get("color_tag", "NONE") or "NONE")
        except FBP_DATA_ERRORS:
            pass
    for effect_id in effect_ids:
        group_id = str(assignments.get(effect_id, "") or "")
        metadata = records.get(group_id, {})
        fbp_set_effect_group_id(
            rig,
            effect_id,
            group_id,
            group_name=str(metadata.get("name", "") or ""),
        )
    fbp_sync_effect_groups(rig, effect_ids=effect_ids)
    return True


def fbp_drag_effect_step_transactional(rigs, effect_id, direction):
    """Move one dragged effect and update folder membership at the crossed row.

    Crossing a grouped neighbour inserts the dragged effect into that folder.
    Crossing an ungrouped neighbour while leaving a folder removes only the
    dragged effect, preserving the remaining group even when one member stays.
    """
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    effect_id = fbp_normalize_effect_id(effect_id)
    direction = str(direction or "UP").upper()
    if not rigs or not effect_id or direction not in {"UP", "DOWN"}:
        return False
    if any(not fbp_effect_is_active(rig, effect_id) for rig in rigs):
        return False

    plans = {}
    for rig in rigs:
        chain_key = _fbp_effect_chain_key(effect_id)
        order = tuple(_fbp_effect_chain_ids(rig, chain_key))
        if effect_id not in order:
            return False
        index = order.index(effect_id)
        target_index = index - 1 if direction == "UP" else index + 1
        if not (0 <= target_index < len(order)):
            return False
        crossed_effect = order[target_index]
        group_state = _fbp_capture_effect_group_state(rig)
        assignments = dict(group_state.get("assignments", {}) or {})
        plans[rig] = {
            "chain": _fbp_effect_chain_snapshots(rig, (effect_id,)),
            "groups": group_state,
            "source_group": str(assignments.get(effect_id, "") or ""),
            "crossed_group": str(assignments.get(crossed_effect, "") or ""),
        }

    moved = []
    for rig in rigs:
        if _fbp_move_effect_selection_on_rig(rig, (effect_id,), direction):
            moved.append(rig)
            continue
        for target in reversed(moved):
            _fbp_restore_effect_chain_snapshots(target, plans[target]["chain"])
            _fbp_restore_effect_group_state(target, plans[target]["groups"])
        return False

    for rig in rigs:
        source_group = plans[rig]["source_group"]
        crossed_group = plans[rig]["crossed_group"]
        target_group = source_group
        if crossed_group and crossed_group != source_group:
            target_group = crossed_group
        elif source_group and crossed_group != source_group:
            target_group = ""

        if target_group != source_group:
            metadata = plans[rig]["groups"].get("records", {}).get(
                target_group, {}
            )
            if not fbp_set_effect_group_id(
                rig,
                effect_id,
                target_group,
                group_name=str(metadata.get("name", "") or ""),
            ):
                for target in rigs:
                    _fbp_restore_effect_chain_snapshots(
                        target, plans[target]["chain"]
                    )
                    _fbp_restore_effect_group_state(
                        target, plans[target]["groups"]
                    )
                return False
            if target_group:
                record = _fbp_effect_group_record(rig, target_group)
                if record is not None:
                    try:
                        record.collapsed = bool(metadata.get("collapsed", False))
                        record.color_tag = str(
                            metadata.get("color_tag", "NONE") or "NONE"
                        )
                    except FBP_DATA_ERRORS:
                        pass

    for rig in rigs:
        fbp_sync_effect_groups(rig)
        fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
    _fbp_select_effect_row(rigs[0], effect_id, rigs)
    return True


def fbp_can_move_effect_selection(rigs, effect_ids, action):
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    effect_ids = [
        fbp_normalize_effect_id(effect_id) for effect_id in tuple(effect_ids or ())
        if fbp_effect_definition(effect_id).get("kind") in {"SHADER", "GEOMETRY"}
    ]
    if not rigs or not effect_ids:
        return False
    if any(
        any(not fbp_effect_is_active(rig, effect_id) for effect_id in effect_ids)
        for rig in rigs
    ):
        return False
    return all(
        _fbp_selection_action_would_change(rig, effect_ids, action)
        for rig in rigs
    )


def fbp_move_effect_selection_transactional(rigs, effect_ids, action):
    """Move checked effects as stable blocks on every selected layer.

    Every rig is snapshotted first. A partial Blender failure restores all
    chains, preventing material and modifier orders from diverging across a
    multi-layer edit.
    """
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    effect_ids = [
        fbp_normalize_effect_id(effect_id) for effect_id in tuple(effect_ids or ())
        if fbp_effect_definition(effect_id).get("kind") in {"SHADER", "GEOMETRY"}
    ]
    effect_ids = list(dict.fromkeys(effect_ids))
    if rigs:
        effect_ids = fbp_expand_effect_selection_to_groups(rigs[0], effect_ids)
        if any(
            fbp_expand_effect_selection_to_groups(rig, effect_ids) != effect_ids
            for rig in rigs[1:]
        ):
            return False
    action = str(action or "UP").upper()
    if action not in {"UP", "DOWN", "TOP", "BOTTOM"}:
        return False
    if not fbp_can_move_effect_selection(rigs, effect_ids, action):
        return False
    snapshots = {rig: _fbp_effect_chain_snapshots(rig, effect_ids) for rig in rigs}
    moved = []
    for rig in rigs:
        if _fbp_move_effect_selection_on_rig(rig, effect_ids, action):
            moved.append(rig)
            continue
        for target in reversed(moved):
            _fbp_restore_effect_chain_snapshots(target, snapshots.get(target, {}))
        _fbp_restore_effect_chain_snapshots(rig, snapshots.get(rig, {}))
        for target in rigs:
            fbp_sync_effect_items(target, rigs if target is rigs[0] else [target])
        return False
    for rig in rigs:
        fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
    if rigs:
        _fbp_select_effect_row(rigs[0], effect_ids[0], rigs)
    return True


def _fbp_apply_effect_chain_order(rig, chain_key, desired_order):
    """Apply one compatible effect-chain order using safe one-step moves."""
    desired = [fbp_normalize_effect_id(item) for item in tuple(desired_order or ()) if item]
    if not desired:
        return False
    current = _fbp_effect_chain_ids(rig, chain_key)
    if set(current) != set(desired) or len(current) != len(desired):
        return False
    changed = current != desired
    for target_index, effect_id in enumerate(desired):
        while True:
            current = _fbp_effect_chain_ids(rig, chain_key)
            if effect_id not in current:
                return False
            current_index = current.index(effect_id)
            if current_index <= target_index:
                break
            if not fbp_move_effect(rig, effect_id, "UP", sync_items=False):
                return False
    return changed and _fbp_effect_chain_ids(rig, chain_key) == desired


def _fbp_group_preserving_recommended_order(rig, chain_key, rank_by_effect):
    """Sort one compatible chain while treating contiguous groups as blocks."""
    current = list(_fbp_effect_chain_ids(rig, chain_key))
    if not current:
        return ()
    groups = fbp_sync_effect_groups(rig, effect_ids=current)
    group_by_effect = {
        effect_id: group_id
        for group_id, members in groups.items()
        for effect_id in members
    }
    blocks = []
    consumed = set()
    for index, effect_id in enumerate(current):
        if effect_id in consumed:
            continue
        group_id = group_by_effect.get(effect_id, "")
        block = tuple(groups.get(group_id, (effect_id,))) if group_id else (effect_id,)
        consumed.update(block)
        rank = min(
            rank_by_effect.get(member, len(rank_by_effect) + index)
            for member in block
        )
        blocks.append((rank, index, block))
    blocks.sort(key=lambda item: (item[0], item[1]))
    return tuple(effect_id for _rank, _index, block in blocks for effect_id in block)


def fbp_sort_effect_stacks_transactional(rigs, recommended_order):
    """Sort every compatible chain while preserving groups and rolling back."""
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    if not rigs:
        return False
    rank_by_effect = {
        fbp_normalize_effect_id(effect_id): index
        for index, effect_id in enumerate(tuple(recommended_order or ()))
    }
    plans = {}
    any_change = False
    for rig in rigs:
        chain_keys = {
            _fbp_effect_chain_key(effect_id)
            for effect_id in fbp_effect_ids_for_rig(rig)
            if fbp_effect_definition(effect_id).get("kind") in {"SHADER", "GEOMETRY"}
        }
        chain_keys.discard(("", ""))
        rig_plans = {}
        for chain_key in chain_keys:
            current = tuple(_fbp_effect_chain_ids(rig, chain_key))
            desired = _fbp_group_preserving_recommended_order(
                rig, chain_key, rank_by_effect
            )
            if current and desired and current != desired:
                rig_plans[chain_key] = (current, desired)
                any_change = True
        plans[rig] = rig_plans
    if not any_change:
        return False

    changed = []
    for rig in rigs:
        for chain_key, (current, desired) in plans[rig].items():
            if _fbp_apply_effect_chain_order(rig, chain_key, desired):
                changed.append((rig, chain_key, current))
                continue
            for target_rig, target_key, original in reversed(changed):
                _fbp_apply_effect_chain_order(target_rig, target_key, original)
            _fbp_apply_effect_chain_order(rig, chain_key, current)
            for target in rigs:
                fbp_sync_effect_items(target, rigs if target is rigs[0] else [target])
            return False
    for rig in rigs:
        fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
    return True


def _fbp_relative_effect_order(rig, effect_ids, target_effect_id, placement):
    """Return ``(chain_key, desired_order)`` for a before/after block move."""
    selected = [fbp_normalize_effect_id(item) for item in tuple(effect_ids or ()) if item]
    selected = list(dict.fromkeys(selected))
    target_effect_id = fbp_normalize_effect_id(target_effect_id)
    target_key = _fbp_effect_chain_key(target_effect_id)
    if not selected or not target_key[0] or target_effect_id in selected:
        return None, ()
    if any(_fbp_effect_chain_key(effect_id) != target_key for effect_id in selected):
        return None, ()
    order = _fbp_effect_chain_ids(rig, target_key)
    if target_effect_id not in order or any(effect_id not in order for effect_id in selected):
        return None, ()
    selected_set = set(selected)
    stable_block = [effect_id for effect_id in order if effect_id in selected_set]
    remaining = [effect_id for effect_id in order if effect_id not in selected_set]
    try:
        target_index = remaining.index(target_effect_id)
    except ValueError:
        return None, ()
    insert_index = target_index if str(placement or "BEFORE").upper() == "BEFORE" else target_index + 1
    desired = remaining[:insert_index] + stable_block + remaining[insert_index:]
    return target_key, tuple(desired)


def fbp_move_effect_selection_relative_transactional(
    rigs, effect_ids, target_effect_id, placement
):
    """Move one checked compatible block before or after another effect.

    All selected layers are validated and snapshotted first. If any Blender
    move fails, every affected chain is restored before the operator exits.
    """
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    effect_ids = [
        fbp_normalize_effect_id(effect_id)
        for effect_id in tuple(effect_ids or ())
        if fbp_effect_definition(effect_id).get("kind") in {"SHADER", "GEOMETRY"}
    ]
    effect_ids = list(dict.fromkeys(effect_ids))
    if rigs:
        effect_ids = fbp_expand_effect_selection_to_groups(rigs[0], effect_ids)
        if any(
            fbp_expand_effect_selection_to_groups(rig, effect_ids) != effect_ids
            for rig in rigs[1:]
        ):
            return False
    target_effect_id = fbp_normalize_effect_id(target_effect_id)
    placement = str(placement or "BEFORE").upper()
    if not rigs or not effect_ids or placement not in {"BEFORE", "AFTER"}:
        return False
    plans = {}
    any_change = False
    for rig in rigs:
        key, desired = _fbp_relative_effect_order(
            rig, effect_ids, target_effect_id, placement
        )
        if not key or not desired:
            return False
        current = tuple(_fbp_effect_chain_ids(rig, key))
        needs_change = current != desired
        any_change = any_change or needs_change
        plans[rig] = (key, current, desired, needs_change)
    if not any_change:
        return False
    changed_rigs = []
    for rig in rigs:
        key, _current, desired, needs_change = plans[rig]
        if not needs_change:
            continue
        if _fbp_apply_effect_chain_order(rig, key, desired):
            changed_rigs.append(rig)
            continue
        for target in reversed(changed_rigs):
            restore_key, original, _desired, _needs_change = plans[target]
            _fbp_apply_effect_chain_order(target, restore_key, original)
        restore_key, original, _desired, _needs_change = plans[rig]
        _fbp_apply_effect_chain_order(rig, restore_key, original)
        for target in rigs:
            fbp_sync_effect_items(target, rigs if target is rigs[0] else [target])
        return False
    for rig in rigs:
        fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
    _fbp_select_effect_row(rigs[0], effect_ids[0], rigs)
    return True


def fbp_group_effect_selection_transactional(rigs, effect_ids):
    """Assign checked compatible effects to one new persistent group."""
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    effect_ids = [
        fbp_normalize_effect_id(effect_id)
        for effect_id in tuple(effect_ids or ())
        if fbp_effect_definition(effect_id).get("kind") in {"SHADER", "GEOMETRY"}
    ]
    effect_ids = list(dict.fromkeys(effect_ids))
    if not rigs or len(effect_ids) < 1:
        return ""
    chain_keys = {_fbp_effect_chain_key(effect_id) for effect_id in effect_ids}
    chain_keys.discard(("", ""))
    if len(chain_keys) != 1:
        return ""
    if any(
        any(not fbp_effect_is_active(rig, effect_id) for effect_id in effect_ids)
        for rig in rigs
    ):
        return ""
    chain_key = next(iter(chain_keys))
    selected_set = set(effect_ids)
    for rig in rigs:
        order = _fbp_effect_chain_ids(rig, chain_key)
        positions = [index for index, item in enumerate(order) if item in selected_set]
        if (
            len(positions) != len(effect_ids)
            or positions != list(range(min(positions), max(positions) + 1))
        ):
            return ""

    group_id = new_effect_group_id()
    group_name = _fbp_next_effect_group_name(rigs[0])
    snapshots = {}
    for rig in rigs:
        groups = fbp_sync_effect_groups(rig)
        group_by_effect = {
            effect_id: group_id
            for group_id, members in groups.items()
            for effect_id in members
        }
        snapshots[rig] = {
            effect_id: (
                group_by_effect.get(effect_id, ""),
                fbp_effect_group_name(
                    rig, group_by_effect.get(effect_id, "")
                ),
            )
            for effect_id in effect_ids
        }
    changed = []
    for rig in rigs:
        for effect_id in effect_ids:
            if fbp_set_effect_group_id(
                rig, effect_id, group_id, group_name=group_name
            ):
                changed.append((rig, effect_id))
                continue
            for target_rig, target_effect in reversed(changed):
                old_group, old_name = snapshots[target_rig][target_effect]
                fbp_set_effect_group_id(
                    target_rig, target_effect, old_group, group_name=old_name
                )
            for target_rig in rigs:
                fbp_sync_effect_groups(target_rig)
                fbp_sync_effect_items(
                    target_rig, rigs if target_rig is rigs[0] else [target_rig]
                )
            return ""
    for rig in rigs:
        fbp_sync_effect_groups(rig)
        fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
    fbp_set_effect_selection(
        rigs[0], effect_ids, mode="REPLACE", eligible_ids=effect_ids
    )
    return group_id


def fbp_ungroup_effect_selection_transactional(rigs, effect_ids):
    """Remove selected effects from folders while keeping every folder valid.

    A folder is a contiguous block. If a middle member is removed, move the
    removed selection immediately after the remaining folder before clearing
    membership. This prevents synchronization from reabsorbing the gap and
    lets singleton folders survive without corrupting evaluation order.
    """
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    effect_ids = list(dict.fromkeys(
        fbp_normalize_effect_id(effect_id)
        for effect_id in tuple(effect_ids or ())
        if fbp_effect_definition(effect_id).get("kind") in {"SHADER", "GEOMETRY"}
    ))
    if not rigs or not effect_ids:
        return False

    plans = {}
    any_grouped = False
    for rig in rigs:
        groups = fbp_sync_effect_groups(rig)
        group_by_effect = {
            effect_id: group_id
            for group_id, members in groups.items()
            for effect_id in members
        }
        selected_grouped = [
            effect_id for effect_id in effect_ids if effect_id in group_by_effect
        ]
        if selected_grouped:
            any_grouped = True
        chain_keys = {
            _fbp_effect_chain_key(effect_id) for effect_id in selected_grouped
        }
        chain_snapshots = _fbp_effect_chain_snapshots(rig, selected_grouped)
        desired_by_chain = {
            chain_key: list(_fbp_effect_chain_ids(rig, chain_key))
            for chain_key in chain_keys
        }
        for _group_id, members in groups.items():
            selected = [item for item in members if item in selected_grouped]
            remaining = [item for item in members if item not in selected_grouped]
            if not selected or not remaining:
                continue
            chain_key = _fbp_effect_chain_key(members[0])
            order = desired_by_chain.get(chain_key, [])
            if not order:
                continue
            ordered_selected = [item for item in order if item in selected]
            without_selected = [item for item in order if item not in selected]
            remaining_positions = [
                without_selected.index(item)
                for item in remaining if item in without_selected
            ]
            if not remaining_positions:
                continue
            insert_at = max(remaining_positions) + 1
            desired_by_chain[chain_key] = (
                without_selected[:insert_at]
                + ordered_selected
                + without_selected[insert_at:]
            )
        plans[rig] = {
            "groups": _fbp_capture_effect_group_state(rig),
            "chains": chain_snapshots,
            "selected": selected_grouped,
            "desired": desired_by_chain,
        }
    if not any_grouped:
        return False

    completed = []
    for rig in rigs:
        plan = plans[rig]
        ok = True
        for effect_id in plan["selected"]:
            if not fbp_set_effect_group_id(rig, effect_id, ""):
                ok = False
                break
        if ok:
            for chain_key, desired in plan["desired"].items():
                if desired and not _fbp_apply_effect_chain_order(rig, chain_key, desired):
                    # An unchanged order is also a successful application.
                    if _fbp_effect_chain_ids(rig, chain_key) != desired:
                        ok = False
                        break
        if ok:
            completed.append(rig)
            continue
        for target in completed + [rig]:
            _fbp_restore_effect_chain_snapshots(target, plans[target]["chains"])
            _fbp_restore_effect_group_state(target, plans[target]["groups"])
        for target in rigs:
            fbp_sync_effect_groups(target)
            fbp_sync_effect_items(target, rigs if target is rigs[0] else [target])
        return False

    for rig in rigs:
        fbp_sync_effect_groups(rig)
        fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
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
    bl_description = "Drag vertically to reorder this effect; crossing a folder boundary moves it into or out of that Effect Group"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", name="Effect ID", default="", options={"SKIP_SAVE"})
    group_id: StringProperty(description="Optional persistent Effect Group dragged as one folder block.", name="Effect Group ID", default="", options={"SKIP_SAVE"})

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
        except FBP_DATA_ERRORS:
            pass

    def _redraw(self, context):
        try:
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        except FBP_DATA_ERRORS:
            try:
                context.area.tag_redraw()
            except FBP_DATA_ERRORS:
                pass

    def _move_once(self, direction):
        if len(getattr(self, "_effect_ids", ())) == 1 and not bool(
            getattr(self, "_move_group", False)
        ):
            return fbp_drag_effect_step_transactional(
                self._current_rigs(), self.effect_id, direction
            )
        return fbp_move_effect_selection_transactional(
            self._current_rigs(), getattr(self, "_effect_ids", (self.effect_id,)), direction
        )

    def _restore_initial_state(self):
        rigs = self._current_rigs()
        initial_chains = getattr(self, "_initial_chains", {})
        initial_groups = getattr(self, "_initial_groups", {})
        for rig in rigs:
            name = str(getattr(rig, "name", "") or "")
            _fbp_restore_effect_chain_snapshots(
                rig, initial_chains.get(name, {})
            )
            _fbp_restore_effect_group_state(
                rig, initial_groups.get(name, {})
            )
        for rig in rigs:
            fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])

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
        fbp_sync_effect_items(rigs[0], rigs)
        requested_group = str(getattr(self, "group_id", "") or "")
        selected_ids = fbp_selected_effect_ids(
            rigs[0],
            fallback_active=False,
            movable_only=True,
            categories=_fbp_effect_view_categories(effect_id=effect_id),
        )
        if requested_group:
            members = tuple(fbp_effect_group_members(rigs[0], requested_group))
            if not members or effect_id not in members:
                return {"CANCELLED"}
            self._effect_ids = members
            self._move_group = True
        else:
            self._effect_ids = tuple(
                selected_ids if effect_id in selected_ids else (effect_id,)
            )
            self._move_group = False
        if any(
            any(not fbp_effect_is_active(rig, item) for item in self._effect_ids)
            for rig in rigs
        ):
            return {"CANCELLED"}
        self._rig_names = tuple(str(getattr(rig, "name", "") or "") for rig in rigs)
        self._initial_chains = {
            str(getattr(rig, "name", "") or ""): _fbp_effect_chain_snapshots(
                rig, self._effect_ids
            )
            for rig in rigs
        }
        self._initial_groups = {
            str(getattr(rig, "name", "") or ""): _fbp_capture_effect_group_state(rig)
            for rig in rigs
        }
        self._anchor_y = int(getattr(event, "mouse_y", 0) or 0)
        self._history = []
        try:
            ui_scale = float(context.preferences.system.ui_scale)
        except FBP_DATA_ERRORS:
            ui_scale = 1.0
        self._threshold = max(12, int(round(18.0 * ui_scale)))
        if requested_group:
            _fbp_select_effect_group_row(rigs[0], requested_group, rigs)
        else:
            _fbp_select_effect_row(rigs[0], effect_id, rigs)
        context.window_manager.modal_handler_add(self)
        try:
            context.window.cursor_modal_set("SCROLL_Y")
        except FBP_DATA_ERRORS:
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
            self._restore_initial_state()
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


class FBP_OT_MoveSelectedEffectsRelative(Operator):
    bl_idname = "fbp.move_selected_effects_relative"
    bl_label = "Move Selected Effects Before / After"
    bl_description = "Move the checked compatible effect block before or after the chosen destination while preserving relative order on every selected layer"
    bl_options = {"REGISTER", "UNDO"}

    target_effect_id: StringProperty(
        name="Destination Effect",
        description="Compatible effect used as the destination for this grouped move",
        default="",
        options={"SKIP_SAVE"},
    )
    placement: EnumProperty(
        name="Placement",
        items=(
            ("BEFORE", "Before", "Insert the selected effect block immediately before the destination"),
            ("AFTER", "After", "Insert the selected effect block immediately after the destination"),
        ),
        default="BEFORE",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        rig = rigs[0]
        fbp_sync_effect_items(rig, rigs)
        effect_ids = fbp_selected_effect_ids(
            rig,
            fallback_active=True,
            movable_only=True,
            categories=_fbp_effect_view_categories(context),
        )
        if not effect_ids:
            return {"CANCELLED"}
        if not fbp_move_effect_selection_relative_transactional(
            rigs, effect_ids, self.target_effect_id, self.placement
        ):
            self.report(
                {"INFO"},
                "Select effects from one compatible chain and choose a different destination",
            )
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_ToggleEffectSolo(Operator):
    bl_idname = "fbp.toggle_effect_solo"
    bl_label = "Solo Effect"
    bl_description = "Solo this effect in the viewport; additional Solo buttons add effects, and disabling the last Solo restores the complete stack"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(
        name="Effect ID",
        description="Effect to add to or remove from the viewport Solo set",
        default="",
        options={"SKIP_SAVE"},
    )
    group_id: StringProperty(
        name="Group ID",
        description="Optional Effect Group to solo as one block",
        default="",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        source = rigs[0]
        fbp_sync_effect_items(source, rigs)
        if self.group_id:
            targets = tuple(fbp_effect_group_members(source, self.group_id))
            if not targets:
                return {"CANCELLED"}
        else:
            effect_id = fbp_normalize_effect_id(self.effect_id)
            targets = (effect_id,) if effect_id else ()
        if not targets:
            return {"CANCELLED"}
        changed = False
        for rig in rigs:
            if all(fbp_effect_is_active(rig, effect_id) for effect_id in targets):
                changed = fbp_toggle_effect_solo(rig, targets) or changed
        fbp_sync_effect_items(source, rigs)
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_SetSelectedEffectsVisibility(Operator):
    bl_idname = "fbp.set_selected_effects_visibility"
    bl_label = "Set Selected Effects Visibility"
    bl_description = "Show, hide or solo checked effects in the viewport or final render across all selected layers"
    bl_options = {"REGISTER", "UNDO"}

    channel: EnumProperty(
        name="Channel",
        items=(
            ("VIEWPORT", "Viewport", "Change viewport visibility"),
            ("RENDER", "Render", "Change final-render visibility"),
        ),
        default="VIEWPORT",
        options={"SKIP_SAVE"},
    )
    mode: EnumProperty(
        name="Mode",
        items=(
            ("SHOW_SELECTED", "Show Selected", "Enable checked effects"),
            ("HIDE_SELECTED", "Hide Selected", "Disable checked effects"),
            ("SOLO_SELECTED", "Solo Selected", "Enable checked effects and disable the other effects in this view"),
            ("SHOW_ALL", "Enable All", "Enable every effect in this view"),
        ),
        default="SHOW_SELECTED",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        rig = rigs[0]
        fbp_sync_effect_items(rig, rigs)
        categories = _fbp_effect_view_categories(context)
        selected = set(
            fbp_selected_effect_ids(
                rig,
                fallback_active=True,
                movable_only=True,
                categories=categories,
            )
        )
        visible_ids = [
            fbp_normalize_effect_id(getattr(item, "effect_id", ""))
            for item in rig.fbp_effects
            if fbp_effect_definition(getattr(item, "effect_id", "")).get("kind")
            in {"SHADER", "GEOMETRY"}
            and str(
                fbp_effect_definition(getattr(item, "effect_id", "")).get(
                    "category", "2D"
                )
                or "2D"
            )
            in categories
        ]
        visible_ids = list(dict.fromkeys(effect_id for effect_id in visible_ids if effect_id))
        if self.mode != "SHOW_ALL" and not selected:
            return {"CANCELLED"}
        changed = 0
        for target_rig in rigs:
            target_ids = [
                effect_id for effect_id in visible_ids
                if fbp_effect_is_active(target_rig, effect_id)
            ]
            if self.mode == "SOLO_SELECTED" and not any(
                effect_id in selected for effect_id in target_ids
            ):
                continue
            for effect_id in target_ids:
                if self.mode == "SHOW_ALL":
                    state = True
                elif self.mode == "SOLO_SELECTED":
                    state = effect_id in selected
                elif self.mode == "HIDE_SELECTED":
                    if effect_id not in selected:
                        continue
                    state = False
                else:
                    if effect_id not in selected:
                        continue
                    state = True
                if self.channel == "RENDER":
                    changed += int(fbp_set_effect_render_visible(target_rig, effect_id, state))
                else:
                    changed += int(fbp_set_effect_visible(target_rig, effect_id, state))
            if self.channel == "VIEWPORT":
                view = "3D" if categories == {"3D"} else ("MASK" if categories == {"MASK"} else "2D")
                solo_ids = (
                    tuple(effect_id for effect_id in target_ids if effect_id in selected)
                    if self.mode == "SOLO_SELECTED" else ()
                )
                changed += int(_fbp_store_effect_solo_ids(target_rig, view, solo_ids))
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_RemoveSelectedEffects(Operator):
    bl_idname = "fbp.remove_selected_effects"
    bl_label = "Remove Selected Effects"
    bl_description = "Remove every checked effect from all selected layers; when nothing is checked, remove the active effect"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        rig = rigs[0]
        fbp_sync_effect_items(rig, rigs)
        effect_ids = fbp_selected_effect_ids(
            rig,
            fallback_active=True,
            categories=_fbp_effect_view_categories(context),
        )
        if not effect_ids:
            return {"CANCELLED"}
        removed = 0
        for target_rig in rigs:
            for effect_id in effect_ids:
                if fbp_effect_is_active(target_rig, effect_id):
                    removed += int(
                        fbp_remove_effect(
                            target_rig, effect_id, sync_items=False
                        )
                    )
        if not removed:
            return {"CANCELLED"}
        fbp_sync_effect_items(
            rig, rigs, repair_assets=False, normalize_instance_ids=False
        )
        fbp_set_effect_selection(
            rig, (), mode="REPLACE", eligible_ids=effect_ids
        )
        self.report({"INFO"}, f"Removed {len(effect_ids)} selected effect(s)")
        return {"FINISHED"}


class FBP_OT_CreateEffectGroup(Operator):
    bl_idname = "fbp.create_effect_group"
    bl_label = "Create Group from Selected"
    bl_description = "Create one persistent organizational group from checked effects, or from the active effect when nothing is checked"
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
        effect_ids = fbp_selected_effect_ids(
            active_rig,
            fallback_active=True,
            movable_only=True,
            categories=_fbp_effect_view_categories(context),
        )
        if not effect_ids:
            self.report({"INFO"}, "Select an effect to create a group")
            return {"CANCELLED"}
        if len({_fbp_effect_chain_key(effect_id) for effect_id in effect_ids}) != 1:
            self.report({"WARNING"}, "Effect Groups must stay inside one compatible chain")
            return {"CANCELLED"}
        group_id = fbp_group_effect_selection_transactional(rigs, effect_ids)
        if not group_id:
            self.report(
                {"WARNING"},
                "Use adjacent compatible effects shared by every selected layer",
            )
            return {"CANCELLED"}
        _fbp_select_effect_group_row(active_rig, group_id, rigs)
        self.report({"INFO"}, f"Created {fbp_effect_group_name(active_rig, group_id)}")
        return {"FINISHED"}


class FBP_OT_SelectEffectGroup(Operator):
    bl_idname = "fbp.select_effect_group"
    bl_label = "Select Effect Group"
    bl_description = "Select this Effect Group folder row without changing the member-effect selection"
    bl_options = {"INTERNAL"}

    group_id: StringProperty(
        name="Effect Group ID",
        description="Persistent Effect Group folder selected in the Effects Stack",
        default="",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs or not self.group_id:
            return {"CANCELLED"}
        return (
            {"FINISHED"}
            if _fbp_select_effect_group_row(rigs[0], self.group_id, rigs)
            else {"CANCELLED"}
        )


class FBP_OT_SelectActiveEffectGroup(Operator):
    bl_idname = "fbp.select_active_effect_group"
    bl_label = "Select Active Group"
    bl_description = "Select every effect that belongs to the active effect's organizational group"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        rig = rigs[0]
        fbp_sync_effect_items(rig, rigs)
        active_effect = fbp_active_effect_id(rig)
        group_id = fbp_active_effect_group_id(rig)
        if not group_id and active_effect:
            group_id = fbp_effect_group_id_for_rig(rig, active_effect)
        if not group_id:
            self.report({"INFO"}, "The active effect is not in a group")
            return {"CANCELLED"}
        members = fbp_effect_group_members(rig, group_id)
        categories = _fbp_effect_view_categories(context)
        eligible = [
            effect_id for effect_id in fbp_effect_ids_for_rig(rig)
            if str(fbp_effect_definition(effect_id).get("category", "2D") or "2D")
            in categories
        ]
        fbp_set_effect_selection(
            rig, members, mode="REPLACE", eligible_ids=eligible
        )
        return {"FINISHED"}


class FBP_OT_UngroupSelectedEffects(Operator):
    bl_idname = "fbp.ungroup_selected_effects"
    bl_label = "Remove Selected from Groups"
    bl_description = "Remove checked effects from their organizational groups without changing effect order or settings"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        rig = rigs[0]
        fbp_sync_effect_items(rig, rigs)
        effect_ids = fbp_selected_effect_ids(
            rig,
            fallback_active=True,
            movable_only=True,
            categories=_fbp_effect_view_categories(context),
        )
        if not fbp_ungroup_effect_selection_transactional(rigs, effect_ids):
            self.report({"INFO"}, "The selected effects are not assigned to groups")
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_ToggleEffectGroupCollapse(Operator):
    bl_idname = "fbp.toggle_effect_group_collapse"
    bl_label = "Expand or Collapse Effect Group"
    bl_description = "Expand or collapse this Effect Group without changing nodes, modifiers, parameters or evaluation order"
    bl_options = {"INTERNAL"}

    group_id: StringProperty(default="", options={"SKIP_SAVE"})
    collapsed: BoolProperty(default=True, options={"SKIP_SAVE"})

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs or not self.group_id:
            return {"CANCELLED"}
        changed = False
        for rig in rigs:
            previous = fbp_effect_group_collapsed(rig, self.group_id)
            if fbp_set_effect_group_collapsed(rig, self.group_id, self.collapsed):
                changed = changed or previous != bool(self.collapsed)
        active_rig = rigs[0]
        _fbp_select_effect_group_row(active_rig, self.group_id, rigs)
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_ToggleEffectGroupSelection(Operator):
    bl_idname = "fbp.toggle_effect_group_selection"
    bl_label = "Select Effect Group"
    bl_description = "Select or deselect every effect inside this collapsed Effect Group for shared stack actions"
    bl_options = {"INTERNAL"}

    group_id: StringProperty(default="", options={"SKIP_SAVE"})
    selected: BoolProperty(default=True, options={"SKIP_SAVE"})

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        rig = rigs[0]
        fbp_sync_effect_items(rig, rigs)
        members = fbp_effect_group_members(rig, self.group_id)
        if not members:
            return {"CANCELLED"}
        changed = fbp_set_effect_selection(
            rig,
            members,
            mode="ADD" if self.selected else "REMOVE",
            eligible_ids=members,
        )
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_RenameEffectGroup(Operator):
    bl_idname = "fbp.rename_effect_group"
    bl_label = "Rename Effect Group"
    bl_description = "Rename this Effect Group consistently on every selected layer while preserving all effect data"
    bl_options = {"REGISTER", "UNDO"}

    group_id: StringProperty(default="", options={"SKIP_SAVE"})
    new_name: StringProperty(
        name="Group Name",
        description="Unique display name for this Effect Group",
        default="Effect Group",
        maxlen=64,
    )

    def invoke(self, context, _event):
        rigs = _fbp_selected_rigs(context)
        if not rigs or not self.group_id:
            return {"CANCELLED"}
        self.new_name = fbp_effect_group_name(rigs[0], self.group_id) or "Effect Group"
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        clean_name = " ".join(str(self.new_name or "").strip().split())
        if not clean_name:
            self.report({"WARNING"}, "Enter a group name")
            return {"CANCELLED"}
        if not fbp_rename_effect_group_transactional(rigs, self.group_id, clean_name):
            self.report({"WARNING"}, "Group name must be unique on every selected layer")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Renamed group to {clean_name[:64]}")
        return {"FINISHED"}


class FBP_OT_SetEffectGroupColor(Operator):
    bl_idname = "fbp.set_effect_group_color"
    bl_label = "Set Effect Group Color"
    bl_description = "Assign a color tag to this Effect Group folder on every selected layer"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    group_id: StringProperty(default="", options={"SKIP_SAVE"})
    color_tag: EnumProperty(
        name="Color Tag",
        items=COLLECTION_COLOR_ENUM_ITEMS,
        default="NONE",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        changed = fbp_set_effect_group_color_transactional(
            _fbp_selected_rigs(context), self.group_id, self.color_tag
        )
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_EffectGroupAction(Operator):
    bl_idname = "fbp.effect_group_action"
    bl_label = "Effect Group Action"
    bl_description = "Run a shared movement, visibility, selection or ungroup action on every member of this Effect Group"
    bl_options = {"REGISTER", "UNDO"}

    group_id: StringProperty(default="", options={"SKIP_SAVE"})
    action: EnumProperty(
        name="Action",
        items=(
            ("SELECT", "Select Group", "Select every member for grouped stack actions"),
            ("MOVE_UP", "Move Up", "Move the complete group one valid position earlier"),
            ("MOVE_DOWN", "Move Down", "Move the complete group one valid position later"),
            ("MOVE_TOP", "Move to Top", "Move the complete group to the beginning of its chain"),
            ("MOVE_BOTTOM", "Move to Bottom", "Move the complete group to the end of its chain"),
            ("SHOW_VIEWPORT", "Show in Viewport", "Enable every group member in the viewport"),
            ("HIDE_VIEWPORT", "Hide in Viewport", "Disable every group member in the viewport"),
            ("SOLO_VIEWPORT", "Solo in Viewport", "Show the group and hide other effects in the same Effects view"),
            ("SHOW_RENDER", "Show in Render", "Enable every group member in final rendering"),
            ("HIDE_RENDER", "Hide in Render", "Disable every group member in final rendering"),
            ("SOLO_RENDER", "Solo in Render", "Render the group and disable other effects in the same Effects view"),
            ("UNGROUP", "Ungroup", "Remove every member from this organizational group"),
        ),
        default="SELECT",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs or not self.group_id:
            return {"CANCELLED"}
        rig = rigs[0]
        fbp_sync_effect_items(rig, rigs)
        members = list(fbp_effect_group_members(rig, self.group_id))
        if not members or any(
            tuple(fbp_effect_group_members(target, self.group_id)) != tuple(members)
            or any(not fbp_effect_is_active(target, effect_id) for effect_id in members)
            for target in rigs
        ):
            self.report({"WARNING"}, "The group is not shared consistently by all selected layers")
            return {"CANCELLED"}

        if self.action == "SELECT":
            categories = _fbp_effect_view_categories(context)
            eligible = [
                effect_id for effect_id in fbp_effect_ids_for_rig(rig)
                if str(fbp_effect_definition(effect_id).get("category", "2D") or "2D") in categories
            ]
            changed = fbp_set_effect_selection(
                rig, members, mode="REPLACE", eligible_ids=eligible
            )
            return {"FINISHED"} if changed else {"CANCELLED"}
        if self.action == "UNGROUP":
            return {"FINISHED"} if fbp_ungroup_effect_selection_transactional(rigs, members) else {"CANCELLED"}
        if self.action.startswith("MOVE_"):
            direction = self.action.removeprefix("MOVE_")
            if not fbp_move_effect_selection_transactional(rigs, members, direction):
                self.report({"INFO"}, "The group cannot move farther in this chain")
                return {"CANCELLED"}
            return {"FINISHED"}

        channel = "RENDER" if self.action.endswith("RENDER") else "VIEWPORT"
        mode = self.action.removesuffix("_RENDER").removesuffix("_VIEWPORT")
        categories = {
            str(fbp_effect_definition(effect_id).get("category", "2D") or "2D")
            for effect_id in members
        }
        changed = False
        for target in rigs:
            candidate_ids = [
                effect_id for effect_id in fbp_effect_ids_for_rig(target)
                if fbp_effect_definition(effect_id).get("kind") in {"SHADER", "GEOMETRY"}
                and str(fbp_effect_definition(effect_id).get("category", "2D") or "2D") in categories
            ]
            for effect_id in candidate_ids:
                if mode == "SOLO":
                    state = effect_id in members
                elif effect_id in members:
                    state = mode == "SHOW"
                else:
                    continue
                if channel == "RENDER":
                    changed = fbp_set_effect_render_visible(target, effect_id, state) or changed
                else:
                    changed = fbp_set_effect_visible(target, effect_id, state) or changed
            if channel == "VIEWPORT":
                view = _fbp_effect_solo_view(members[0])
                solo_ids = tuple(members) if mode == "SOLO" else ()
                changed = _fbp_store_effect_solo_ids(target, view, solo_ids) or changed
        fbp_sync_effect_items(rig, rigs)
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_EffectGroupActions(Operator):
    bl_idname = "fbp.effect_group_actions"
    bl_label = "Effect Group Actions"
    bl_description = "Open shared controls for renaming, collapsing, moving, selecting, showing or ungrouping this Effect Group"
    bl_options = {"INTERNAL"}

    group_id: StringProperty(default="", options={"SKIP_SAVE"})

    def invoke(self, context, _event):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        if not self.group_id:
            active_effect = fbp_active_effect_id(rigs[0])
            self.group_id = fbp_effect_group_id_for_rig(rigs[0], active_effect)
        if not self.group_id:
            self.report({"INFO"}, "The active effect is not in a group")
            return {"CANCELLED"}
        return context.window_manager.invoke_popup(self, width=330)

    def draw(self, context):
        layout = self.layout
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            layout.label(text="No Frame By Plane layer selected", icon="INFO")
            return
        rig = rigs[0]
        name = fbp_effect_group_name(rig, self.group_id) or "Effect Group"
        members = fbp_effect_group_members_from_items(rig, self.group_id)
        record = _fbp_effect_group_record(rig, self.group_id)
        collapsed = bool(getattr(record, "collapsed", False)) if record else False
        color_tag = str(getattr(record, "color_tag", "NONE") or "NONE") if record else "NONE"
        header = layout.row(align=False)
        noun = "effect" if len(members) == 1 else "effects"
        header.label(
            text=f"{name} · {len(members)} {noun}",
            icon=fbp_collection_color_icon(color_tag),
        )
        rename = header.operator("fbp.rename_effect_group", text="", icon="GREASEPENCIL")
        rename.group_id = self.group_id

        colors = layout.row(align=True)
        for tag, _label, _description, icon, _value in COLLECTION_COLOR_ENUM_ITEMS:
            op = colors.operator(
                "fbp.set_effect_group_color",
                text="",
                icon=icon,
                depress=color_tag == tag,
            )
            op.group_id = self.group_id
            op.color_tag = tag

        row = layout.row(align=True)
        collapse = row.operator(
            "fbp.toggle_effect_group_collapse",
            text="Expand" if collapsed else "Collapse",
            icon="RIGHTARROW" if collapsed else "DOWNARROW_HLT",
        )
        collapse.group_id = self.group_id
        collapse.collapsed = not collapsed
        select = row.operator("fbp.effect_group_action", text="Select", icon="RESTRICT_SELECT_OFF")
        select.group_id = self.group_id
        select.action = "SELECT"

        layout.separator()
        layout.label(text="Move Group", icon="GRIP")
        move = layout.row(align=True)
        for action, icon in (
            ("MOVE_TOP", "TRIA_UP_BAR"),
            ("MOVE_UP", "SORT_DESC"),
            ("MOVE_DOWN", "SORT_ASC"),
            ("MOVE_BOTTOM", "TRIA_DOWN_BAR"),
        ):
            op = move.operator("fbp.effect_group_action", text="", icon=icon)
            op.group_id = self.group_id
            op.action = action

        layout.separator()
        layout.label(text="Viewport", icon="HIDE_OFF")
        viewport = layout.row(align=True)
        for text, action, icon in (
            ("Show", "SHOW_VIEWPORT", "HIDE_OFF"),
            ("Hide", "HIDE_VIEWPORT", "HIDE_ON"),
            ("Solo", "SOLO_VIEWPORT", "CHECKMARK"),
        ):
            op = viewport.operator("fbp.effect_group_action", text=text, icon=icon)
            op.group_id = self.group_id
            op.action = action

        layout.label(text="Render", icon="RESTRICT_RENDER_OFF")
        render = layout.row(align=True)
        for text, action, icon in (
            ("Show", "SHOW_RENDER", "RESTRICT_RENDER_OFF"),
            ("Hide", "HIDE_RENDER", "RESTRICT_RENDER_ON"),
            ("Solo", "SOLO_RENDER", "CHECKMARK"),
        ):
            op = render.operator("fbp.effect_group_action", text=text, icon=icon)
            op.group_id = self.group_id
            op.action = action

        layout.separator()
        ungroup = layout.operator("fbp.effect_group_action", text="Ungroup All Effects", icon="UNLINKED")
        ungroup.group_id = self.group_id
        ungroup.action = "UNGROUP"

    def execute(self, _context):
        return {"FINISHED"}


class FBP_OT_SetEffectRender(Operator):
    bl_idname = "fbp.set_effect_render"
    bl_label = "Set Effect Render Visibility"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", name="Effect ID", default="", options={"SKIP_SAVE"})
    visible: BoolProperty(description="Requested viewport or render visibility state for this effect.", name="Visible in Render", default=True, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs or any(not fbp_effect_is_active(rig, self.effect_id) for rig in rigs):
            return {"CANCELLED"}
        changed = sum(1 for rig in rigs if fbp_set_effect_render_visible(rig, self.effect_id, self.visible))
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_SetEffectSelection(Operator):
    bl_idname = "fbp.set_effect_selection"
    bl_label = "Set Effect Selection"
    bl_description = "Select, clear or invert effect rows used by grouped stack actions"
    bl_options = {"INTERNAL"}

    mode: EnumProperty(
        name="Mode",
        items=(
            ("ALL", "All", "Select every effect row"),
            ("NONE", "None", "Clear every effect-row checkbox"),
            ("INVERT", "Invert", "Invert all effect-row checkboxes"),
        ),
        default="ALL",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        rig = rigs[0]
        fbp_sync_effect_items(rig, rigs)
        categories = _fbp_effect_view_categories(context)
        visible_ids = [
            effect_id
            for item in rig.fbp_effects
            if str(getattr(item, "row_type", "EFFECT") or "EFFECT") == "EFFECT"
            for effect_id in (fbp_normalize_effect_id(getattr(item, "effect_id", "")),)
            if effect_id and str(
                fbp_effect_definition(effect_id).get("category", "2D") or "2D"
            ) in categories
        ]
        if self.mode == "INVERT":
            changed = fbp_set_effect_selection(
                rig, mode="INVERT", eligible_ids=visible_ids
            )
        elif self.mode == "NONE":
            changed = fbp_set_effect_selection(
                rig, (), mode="REPLACE", eligible_ids=visible_ids
            )
        else:
            changed = fbp_set_effect_selection(
                rig, visible_ids, mode="REPLACE", eligible_ids=visible_ids
            )
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_MoveActiveEffect(Operator):
    bl_idname = "fbp.move_active_effect"
    bl_label = "Move Selected Effects"
    bl_description = "Move checked effects together while preserving their relative order; the active row is used when nothing is checked"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction",
        description="Move checked effects by one position or directly to the chain boundary",
        items=(
            ("UP", "Up", "Move selected effects one position earlier"),
            ("DOWN", "Down", "Move selected effects one position later"),
            ("TOP", "Top", "Move selected effects to the start of each compatible chain"),
            ("BOTTOM", "Bottom", "Move selected effects to the end of each compatible chain"),
        ),
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
        effect_ids = fbp_selected_effect_ids(
            active_rig,
            fallback_active=True,
            movable_only=True,
            categories=_fbp_effect_view_categories(context),
        )
        if not effect_ids:
            self.report({"INFO"}, "Select a shader or mesh effect first")
            return {"CANCELLED"}
        missing = [
            effect_id for effect_id in effect_ids
            if any(not fbp_effect_is_active(rig, effect_id) for rig in rigs)
        ]
        if missing:
            self.report(
                {"WARNING"},
                "Copy every checked effect to all selected layers before reordering",
            )
            return {"CANCELLED"}
        if not fbp_move_effect_selection_transactional(
            rigs, effect_ids, self.direction
        ):
            self.report({"INFO"}, "Selected effects cannot move farther in this chain")
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_RemoveEffect(Operator):
    bl_idname = "fbp.remove_effect"
    bl_label = "Remove Effect"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", name="Effect ID", default="", options={"SKIP_SAVE"})

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
            if fbp_effect_is_active(rig, effect_id)
            and fbp_remove_effect(rig, effect_id, sync_items=False)
        )
        fbp_sync_effect_items(
            rigs[0], rigs, repair_assets=False, normalize_instance_ids=False
        )
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
        removed = sum(
            1
            for rig in rigs
            if fbp_remove_effect(rig, effect_id, sync_items=False)
        )
        fbp_sync_effect_items(
            active_rig, rigs,
            repair_assets=False,
            normalize_instance_ids=False,
        )
        if removed == 0:
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_UpdateLatticeFlatten(Operator):
    bl_idname = "fbp.update_lattice_flatten"
    bl_label = "Update Camera Flatten"
    bl_description = "Recalculate the Lattice so the plane preserves its current camera-space perspective on a camera-parallel surface"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None:
            return {'CANCELLED'}
        if _fbp_lattice_scene_camera(getattr(context, "scene", None)) is None:
            self.report({'ERROR'}, "Set an active Scene Camera before using Camera Flatten")
            return {'CANCELLED'}
        if not _fbp_apply_lattice_effect(rig, select=False):
            self.report({'ERROR'}, _fbp_last_lattice_error(rig) or "Could not create the Lattice cage")
            return {'CANCELLED'}
        if not _fbp_apply_lattice_camera_flatten(rig, scene=context.scene, force=True):
            self.report({'WARNING'}, "Camera Flatten could not be calculated for this plane and camera")
            return {'CANCELLED'}
        fbp_focus_lattice_ui(context, rig)
        self.report({'INFO'}, "Updated Camera Flatten")
        return {'FINISHED'}


class FBP_OT_FreezeLatticeFlatten(Operator):
    bl_idname = "fbp.freeze_lattice_flatten"
    bl_label = "Freeze and Edit Lattice"
    bl_description = "Bake the current Camera Flatten into the Lattice, stop live updates and switch to Freeform editing"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None or not _fbp_apply_lattice_effect(rig, select=False):
            return {'CANCELLED'}
        if _fbp_lattice_scene_camera(getattr(context, "scene", None)) is None:
            self.report({'ERROR'}, "Set an active Scene Camera before freezing Camera Flatten")
            return {'CANCELLED'}
        _fbp_apply_lattice_camera_flatten(rig, scene=context.scene, force=True)
        fbp_set_rna_property_silent(rig, "fbp_lattice_live_update", False)
        fbp_set_rna_property_silent(rig, "fbp_lattice_mode", "FREEFORM")
        fbp_set_rna_property_silent(rig, "fbp_lattice_interpolation", "LINEAR")
        fbp_set_rna_property_silent(rig, "fbp_lattice_show_cage", True)
        helper = _fbp_lattice_object(rig)
        if helper is not None:
            try:
                helper[_FBP_LATTICE_MODE_KEY] = "FREEFORM"
                helper[_FBP_LATTICE_BAKED_KEY] = True
                _fbp_stabilize_lattice_helper(helper)
                if bpy.context.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")
                bpy.ops.object.select_all(action="DESELECT")
                helper.hide_set(False)
                helper.select_set(True)
                bpy.context.view_layer.objects.active = helper
                bpy.ops.object.mode_set(mode='EDIT')
                try:
                    bpy.ops.lattice.select_all(action='DESELECT')
                except FBP_DATA_ERRORS:
                    pass
            except FBP_DATA_ERRORS:
                pass
        cache_key = _fbp_lattice_runtime_key(rig)
        if cache_key is not None:
            _FBP_LATTICE_FLATTEN_CACHE.pop(cache_key, None)
        fbp_focus_lattice_ui(context, rig)
        self.report({'INFO'}, "Camera perspective baked into an editable Freeform Lattice")
        return {'FINISHED'}


class FBP_OT_SetupLatticeCameraFlatten(Operator):
    bl_idname = "fbp.setup_lattice_camera_flatten"
    bl_label = "Set Up Camera Flatten"
    bl_description = "Configure a balanced perspective cage, enable Camera Flatten and start live camera-relative correction"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None:
            return {'CANCELLED'}
        camera = _fbp_lattice_scene_camera(getattr(context, "scene", None))
        if camera is None:
            self.report({'ERROR'}, "Set an active Scene Camera before using Camera Flatten")
            return {'CANCELLED'}
        camera_type = str(getattr(getattr(camera, "data", None), "type", "") or "").upper()
        if camera_type not in {"PERSP", "ORTHO"}:
            self.report({'ERROR'}, "Camera Flatten supports Perspective and Orthographic cameras")
            return {'CANCELLED'}
        for name, value in (
            ("fbp_lattice_mode", "CAMERA_FLATTEN"),
            ("fbp_lattice_live_update", True),
            ("fbp_lattice_show_cage", True),
            ("fbp_lattice_grid_preset", "LOOPS_4"),
            ("fbp_lattice_points_w", 1),
            ("fbp_lattice_mesh_detail_mode", "AUTO"),
            ("fbp_lattice_mesh_density", "DOUBLE"),
            ("fbp_lattice_mesh_subdivisions", 3),
        ):
            fbp_set_rna_property_silent(rig, name, value)
        _fbp_apply_lattice_grid_settings(rig)
        if not _fbp_apply_lattice_effect(rig, select=False):
            return {'CANCELLED'}
        if not _fbp_apply_lattice_camera_flatten(rig, scene=context.scene, force=True):
            self.report({'WARNING'}, "Camera Flatten could not be calculated for this pose")
            return {'CANCELLED'}
        helper = _fbp_lattice_object(rig)
        if helper is not None:
            try:
                helper[_FBP_LATTICE_BAKED_KEY] = False
            except FBP_DATA_ERRORS:
                pass
        fbp_focus_lattice_ui(context, rig)
        self.report({'INFO'}, "Camera Flatten ready: animate the layer or bake the correction")
        return {'FINISHED'}


class FBP_OT_BakeLatticeFlatten(Operator):
    bl_idname = "fbp.bake_lattice_flatten"
    bl_label = "Bake and Keep Animating"
    bl_description = "Bake the current camera correction into the Lattice, stop live recalculation and keep the layer selected for normal animation"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None or not _fbp_apply_lattice_effect(rig, select=False):
            return {'CANCELLED'}
        if _fbp_lattice_scene_camera(getattr(context, "scene", None)) is None:
            self.report({'ERROR'}, "Set an active Scene Camera before baking Camera Flatten")
            return {'CANCELLED'}
        if not _fbp_apply_lattice_camera_flatten(rig, scene=context.scene, force=True):
            self.report({'WARNING'}, "Camera Flatten could not be calculated for this pose")
            return {'CANCELLED'}
        fbp_set_rna_property_silent(rig, "fbp_lattice_live_update", False)
        fbp_set_rna_property_silent(rig, "fbp_lattice_mode", "FREEFORM")
        fbp_set_rna_property_silent(rig, "fbp_lattice_interpolation", "LINEAR")
        helper = _fbp_lattice_object(rig)
        if helper is not None:
            try:
                helper[_FBP_LATTICE_MODE_KEY] = "FREEFORM"
                helper[_FBP_LATTICE_BAKED_KEY] = True
                _fbp_stabilize_lattice_helper(helper)
            except FBP_DATA_ERRORS:
                pass
        cache_key = _fbp_lattice_runtime_key(rig)
        if cache_key is not None:
            _FBP_LATTICE_FLATTEN_CACHE.pop(cache_key, None)
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            plane = _fbp_plane(rig)
            if helper is not None:
                helper.select_set(False)
            for obj in (rig, plane):
                if obj is not None:
                    obj.select_set(True)
            bpy.context.view_layer.objects.active = rig
        except FBP_DATA_ERRORS:
            pass
        fbp_focus_lattice_ui(context, rig)
        self.report({'INFO'}, "Perspective baked. Local rotation and animation remain editable")
        return {'FINISHED'}


class FBP_OT_RebuildLatticeHelper(Operator):
    bl_idname = "fbp.rebuild_lattice_helper"
    bl_label = "Rebuild Lattice Cage"
    bl_description = "Remove only the generated Lattice helper and modifiers for this layer, then create a clean cage without changing the source plane or image"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None:
            self.report({'ERROR'}, "Frame By Plane layer not found")
            return {'CANCELLED'}
        _fbp_cleanup_incomplete_lattice_setup(rig, force=True)
        _fbp_set_enabled(rig, FBP_EFFECT_LATTICE, True)
        if not _fbp_apply_lattice_effect(rig, select=False):
            _fbp_set_enabled(rig, FBP_EFFECT_LATTICE, False)
            self.report({'ERROR'}, _fbp_last_lattice_error(rig) or "Lattice rebuild failed")
            return {'CANCELLED'}
        fbp_focus_lattice_ui(context, rig)
        self.report({'INFO'}, "Lattice cage rebuilt")
        return {'FINISHED'}


class FBP_OT_SelectLatticeHelper(Operator):
    bl_idname = "fbp.select_lattice_helper"
    bl_label = "Select Lattice Cage"
    bl_description = "Reveal and select the generated Lattice cage. Object transforms stay locked; use Edit Cage for deformation"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None or not _fbp_apply_lattice_effect(rig, select=False):
            self.report({'ERROR'}, _fbp_last_lattice_error(rig) or "Could not create the Lattice cage")
            return {'CANCELLED'}
        helper = _fbp_lattice_object(rig)
        if helper is None:
            self.report({'ERROR'}, "The Lattice cage is missing")
            return {'CANCELLED'}
        fbp_set_rna_property_silent(rig, "fbp_lattice_show_cage", True)
        plane = _fbp_plane(rig)
        _fbp_configure_lattice_visibility(
            rig, plane, helper, _fbp_lattice_modifier(plane),
            _fbp_lattice_detail_modifier(plane), context=context,
        )
        if not _fbp_select_lattice_helper(rig, helper, context=context):
            self.report({'ERROR'}, "The cage exists but is not available in the active View Layer")
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_SetLatticePerspectiveGrid(Operator):
    bl_idname = "fbp.set_lattice_perspective_grid"
    bl_label = "Set Lattice Grid"
    bl_description = "Set a cage grid preset and matching non-destructive mesh detail. Changing grid resolution resets existing point edits"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(options={'HIDDEN'})
    grid_size: IntProperty(name="Grid Size", default=4, min=2, max=8, options={'SKIP_SAVE'})

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None:
            return {'CANCELLED'}
        raw_size = int(self.grid_size)
        size = 2 if raw_size <= 2 else (4 if raw_size <= 4 else (8 if raw_size >= 8 else 6))
        detail = {2: 1, 4: 2, 6: 3, 8: 4}[size]
        loops = max(0, size - 2)
        preset = {0: "CORNERS", 1: "BASIC", 2: "LOOPS_2", 4: "LOOPS_4"}.get(loops, "CUSTOM")
        fbp_set_rna_property_silent(rig, "fbp_lattice_grid_preset", preset)
        fbp_set_rna_property_silent(rig, "fbp_lattice_custom_loops_u", loops)
        fbp_set_rna_property_silent(rig, "fbp_lattice_custom_loops_v", loops)
        fbp_set_rna_property_silent(rig, "fbp_lattice_points_w", 1)
        _fbp_apply_lattice_grid_settings(rig)
        fbp_set_rna_property_silent(rig, "fbp_lattice_mesh_detail_mode", "AUTO")
        fbp_set_rna_property_silent(rig, "fbp_lattice_mesh_density", "DOUBLE")
        fbp_set_rna_property_silent(rig, "fbp_lattice_mesh_subdivisions", detail)
        if not _fbp_apply_lattice_effect(rig, select=False):
            return {'CANCELLED'}
        fbp_focus_lattice_ui(context, rig)
        self.report({'INFO'}, f"Planar Lattice set to {size} × {size}; mesh density follows at 2×")
        return {'FINISHED'}


class FBP_OT_ResetLatticeHelper(Operator):
    bl_idname = "fbp.reset_lattice_helper"
    bl_label = "Reset Lattice"
    bl_description = "Restore a regular undeformed cage around the current plane and return to Freeform mode"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None or not _fbp_apply_lattice_effect(rig, select=False):
            return {'CANCELLED'}
        helper = _fbp_lattice_object(rig)
        plane = _fbp_plane(rig)
        if helper is None or plane is None:
            return {'CANCELLED'}
        fbp_set_rna_property_silent(rig, "fbp_lattice_mode", "FREEFORM")
        fbp_set_rna_property_silent(rig, "fbp_lattice_live_update", True)
        try:
            helper.matrix_world = _fbp_lattice_fit_matrix(plane)
            helper[_FBP_LATTICE_MODE_KEY] = "FREEFORM"
            helper[_FBP_LATTICE_BAKED_KEY] = False
        except FBP_DATA_ERRORS:
            return {'CANCELLED'}
        if not _fbp_reset_lattice_points(helper):
            return {'CANCELLED'}
        _fbp_stabilize_lattice_helper(helper)
        cache_key = _fbp_lattice_runtime_key(rig)
        if cache_key is not None:
            _FBP_LATTICE_FLATTEN_CACHE.pop(cache_key, None)
        fbp_focus_lattice_ui(context, rig)
        self.report({'INFO'}, "Lattice reset")
        return {'FINISHED'}


class FBP_OT_EditLatticeHelper(Operator):
    bl_idname = "fbp.edit_lattice_helper"
    bl_label = "Edit Lattice"
    bl_description = "Enter planar Lattice Edit Mode with all points deselected. Move one control point for a corner, or press A to transform the whole cage"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None or not _fbp_apply_lattice_effect(rig, select=False):
            self.report({'ERROR'}, _fbp_last_lattice_error(rig) or "Could not create the Lattice cage")
            return {'CANCELLED'}
        if _fbp_lattice_mode(rig) == "CAMERA_FLATTEN":
            _fbp_apply_lattice_camera_flatten(rig, scene=context.scene, force=True)
            fbp_set_rna_property_silent(rig, "fbp_lattice_live_update", False)
            fbp_set_rna_property_silent(rig, "fbp_lattice_mode", "FREEFORM")
            fbp_set_rna_property_silent(rig, "fbp_lattice_interpolation", "LINEAR")
            helper = _fbp_lattice_object(rig)
            if helper is not None:
                try:
                    helper[_FBP_LATTICE_MODE_KEY] = "FREEFORM"
                    helper[_FBP_LATTICE_BAKED_KEY] = True
                    _fbp_stabilize_lattice_helper(helper)
                except FBP_DATA_ERRORS:
                    pass
        fbp_set_rna_property_silent(rig, "fbp_lattice_show_cage", True)
        if not _fbp_apply_lattice_effect(rig, select=True):
            return {'CANCELLED'}
        fbp_focus_lattice_ui(context, rig)
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            try:
                bpy.ops.lattice.select_all(action='DESELECT')
            except FBP_DATA_ERRORS:
                pass
        except FBP_DATA_ERRORS as exc:
            self.report({'ERROR'}, f"Could not enter Lattice Edit Mode: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_FinishLatticeEditing(Operator):
    bl_idname = "fbp.finish_lattice_editing"
    bl_label = "Finish Lattice Editing"
    bl_description = "Exit Lattice Edit Mode and return selection to the Frame By Plane layer rig"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None:
            self.report({'ERROR'}, "Frame By Plane layer not found")
            return {'CANCELLED'}
        try:
            if getattr(context, "mode", "OBJECT") != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            for obj in tuple(getattr(context, "selected_objects", ()) or ()):
                try:
                    obj.select_set(False)
                except FBP_DATA_ERRORS:
                    pass
            rig.hide_set(False)
            rig.select_set(True)
            context.view_layer.objects.active = rig
            fbp_focus_lattice_ui(context, rig)
        except FBP_DATA_ERRORS as exc:
            self.report({'ERROR'}, f"Could not return to the layer: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_RefitLatticeHelper(Operator):
    bl_idname = "fbp.refit_lattice_helper"
    bl_label = "Refit Lattice"
    bl_description = "Refit the generated Lattice around the current linked plane bounds without deleting manual point edits"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        helper = _fbp_lattice_object(rig) if rig else None
        plane = _fbp_plane(rig) if rig else None
        if helper is None or plane is None:
            if rig is None or not _fbp_apply_lattice_effect(rig, select=False):
                return {'CANCELLED'}
            helper = _fbp_lattice_object(rig)
            plane = _fbp_plane(rig)
        if _fbp_lattice_mode(rig) == "CAMERA_FLATTEN":
            if not _fbp_apply_lattice_camera_flatten(rig, scene=context.scene, force=True):
                return {'CANCELLED'}
            return {'FINISHED'}
        try:
            helper.matrix_world = _fbp_lattice_fit_matrix(plane)
            _fbp_stabilize_lattice_helper(helper)
        except FBP_DATA_ERRORS:
            return {'CANCELLED'}
        fbp_focus_lattice_ui(context, rig)
        return {'FINISHED'}


classes = (
    FBP_UL_EffectStack,
    FBP_UL_EffectStack2D,
    FBP_UL_EffectStack3D,
    FBP_UL_EffectStackMask,
    FBP_MT_DuotoneVariants,
    FBP_MT_EffectFamilyVariants,
    FBP_MT_AddEffect,
    FBP_MT_ObjectEffects2D,
    FBP_MT_ObjectEffects3D,
    FBP_MT_ObjectMasks,
    FBP_MT_ObjectEffects,
    FBP_MT_EffectPresets,
    FBP_OT_OpenEffectPresets,
    FBP_OT_OpenEffectToolbarMenu,
    FBP_MT_MoveSelectedEffects,
    FBP_MT_EffectVisibilityActions,
    FBP_MT_EffectStackActions,
    FBP_MT_EffectGroupTools,
    FBP_OT_EffectHeaderWarning,
    FBP_OT_FitShadowCanvas,
    FBP_OT_CaptureCameraScaleReference,
    FBP_OT_UpdateLatticeFlatten,
    FBP_OT_FreezeLatticeFlatten,
    FBP_OT_SetupLatticeCameraFlatten,
    FBP_OT_BakeLatticeFlatten,
    FBP_OT_RebuildLatticeHelper,
    FBP_OT_SelectLatticeHelper,
    FBP_OT_SetLatticePerspectiveGrid,
    FBP_OT_ResetLatticeHelper,
    FBP_OT_EditLatticeHelper,
    FBP_OT_FinishLatticeEditing,
    FBP_OT_RefitLatticeHelper,
    FBP_OT_SetExtrudeDirection,
    FBP_OT_OpenEffectMasks,
    FBP_OT_CloseEffectMasks,
    FBP_OT_AddEffectMask,
    FBP_OT_SetEffectMaskTarget,
    FBP_OT_SelectEffect,
    FBP_OT_AddEffect,
    FBP_OT_AddEffectFamily,
    FBP_OT_SetEffectFamilyVariant,
    FBP_OT_SetEffectInputSource,
    FBP_OT_SetEffectDebugMode,
    FBP_OT_CopyActiveEffect,
    FBP_OT_CopySelectedEffects,
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
    FBP_OT_MoveSelectedEffectsRelative,
    FBP_OT_ToggleEffectSolo,
    FBP_OT_SetSelectedEffectsVisibility,
    FBP_OT_RemoveSelectedEffects,
    FBP_OT_CreateEffectGroup,
    FBP_OT_SelectEffectGroup,
    FBP_OT_SelectActiveEffectGroup,
    FBP_OT_UngroupSelectedEffects,
    FBP_OT_ToggleEffectGroupCollapse,
    FBP_OT_ToggleEffectGroupSelection,
    FBP_OT_RenameEffectGroup,
    FBP_OT_SetEffectGroupColor,
    FBP_OT_EffectGroupAction,
    FBP_OT_EffectGroupActions,
    FBP_OT_SetEffectRender,
    FBP_OT_SetEffectSelection,
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
            except FBP_DATA_ERRORS:
                pass


def _fbp_remove_evolve_handlers():
    _fbp_remove_named_handler(bpy.app.handlers.frame_change_post, fbp_effect_evolve_frame_change)
    _fbp_remove_named_handler(bpy.app.handlers.animation_playback_pre, fbp_effect_playback_pre)
    _fbp_remove_named_handler(bpy.app.handlers.animation_playback_post, fbp_effect_playback_post)


def fbp_clear_effect_runtime_caches():
    """Drop transient RNA caches before Undo, file load or module teardown."""
    global _FBP_DEFAULT_FONT_CACHE
    global _FBP_EFFECT_UI_EPOCH
    _FBP_EFFECT_UI_EPOCH += 1
    _FBP_EFFECT_HEALTH_CACHE.clear()
    _FBP_EFFECT_GROUP_CACHE.clear()
    _FBP_INTERFACE_INPUT_CACHE.clear()
    _FBP_MATRIX_IMAGE_NODE_CACHE.clear()
    _FBP_PRIVATE_IMAGE_SOURCE_SYNC_CACHE.clear()
    _FBP_MASK_SOURCE_SYNC_CACHE.clear()
    _FBP_IMPORTED_MASK_SYNC_CACHE.clear()
    _FBP_MASK_TARGET_CACHE.clear()
    _FBP_EFFECT_IDS_CACHE.clear()
    _FBP_EFFECT_IDS_CACHE_TIME.clear()
    _FBP_EFFECT_RUNTIME_PROFILE_CACHE.clear()
    _FBP_EFFECT_SCENE_RIG_CACHE.clear()
    _FBP_EFFECT_EVOLVE_STEP_CACHE.clear()
    _FBP_LATTICE_FLATTEN_CACHE.clear()
    _FBP_LATTICE_UPDATE_PENDING.clear()
    _FBP_LATTICE_LAST_ACTIVITY.clear()
    _FBP_LATTICE_LAST_ERROR.clear()
    _FBP_LATTICE_HELPER_RESOLVE_CACHE.clear()
    _FBP_LATTICE_REPAIR_PENDING.clear()
    _FBP_LATTICE_REPAIR_ATTEMPTED.clear()
    _FBP_LATTICE_LIVE_SCENE_CACHE.clear()
    _FBP_EFFECT_RUNTIME_STATS.clear()
    _FBP_EFFECT_RUNTIME_STATS.update(
        {"handler_runs": 0, "rig_updates": 0, "held_step_skips": 0}
    )
    _FBP_CAMERA_BINDING_CACHE.clear()
    _FBP_CUSTOM_SHADER_SYNC_PENDING.clear()
    _FBP_CUSTOM_GEOMETRY_INIT_PENDING.clear()
    _FBP_CUSTOM_GEOMETRY_SOCKET_CACHE.clear()
    _FBP_CUSTOM_SHADER_SOCKET_CACHE.clear()
    _FBP_CUSTOM_SHADER_SYNC_STATE_CACHE.clear()
    _FBP_COLOR_RAMP_SYNC_PENDING.clear()
    _FBP_COLOR_RAMP_SYNC_STATE_CACHE.clear()
    _FBP_EFFECT_STACK_OWNER_CACHE.clear()
    _FBP_EFFECT_INSTANCE_OWNER_CACHE.clear()
    _FBP_RELATION_SYNC_PENDING.clear()
    _FBP_USER_PRESET_CACHE["stamp"] = None
    _FBP_USER_PRESET_CACHE["data"] = {}
    _FBP_DEFAULT_FONT_CACHE = None


def _fbp_stabilize_existing_lattice_helpers():
    """Upgrade cages and heal active contracts once outside UI/depsgraph draw."""
    try:
        objects = tuple(getattr(bpy.data, "objects", ()) or ())
    except FBP_DATA_ERRORS:
        return None
    for helper in objects:
        try:
            if (
                str(getattr(helper, "type", "") or "") == "LATTICE"
                and str(helper.get(_FBP_LATTICE_EFFECT_KEY, "") or "") == FBP_EFFECT_LATTICE
            ):
                _fbp_stabilize_lattice_helper(helper)
        except FBP_DATA_ERRORS:
            continue
    fbp_repair_existing_lattice_contracts()
    return None


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
    for issue in FBP_EFFECT_SETTINGS_UI_ISSUES:
        fbp_warn(f"Effect settings UI validation: {issue}")
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
    try:
        from .safe_tasks import schedule_once
        schedule_once(
            "lattice.stabilize_native_cages",
            _fbp_stabilize_existing_lattice_helpers,
            first_interval=0.05,
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def unregister():
    global _FBP_EFFECT_PLAYBACK_ACTIVE
    _FBP_EFFECT_PLAYBACK_ACTIVE = False
    fbp_clear_effect_runtime_caches()
    _fbp_remove_object_context_menu_entry()
    _fbp_remove_evolve_handlers()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except FBP_DATA_ERRORS:
            pass
