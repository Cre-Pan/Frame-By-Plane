"""Effect settings drawing: panels, effect stack list and the Add Effect columns.

Moved out of :mod:`geometry_nodes`, which re-exports every name defined here, so
``geometry_nodes.<name>`` keeps working for callers and tests.
"""

import os
import re
import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator, UIList
from mathutils import Matrix
from .constants import (
    fbp_collection_color_icon,
)
from .path_utils import natural_sort_key
from .shortcut_runtime import alt_modifier_name
from .ui_icons import effect_custom_icon_value, effect_enum_icon, effect_icon_kwargs, ui_icon, ui_icon_value
from .ui_style import configure_layout, hint_row, section_gap, section_header
from .ui_context import resolve_node_editor_area
from .interface_preferences import (
    fbp_draw_uilist_spacer,
    fbp_uilist_icon_flags,
    fbp_uilist_icon_order,
    fbp_uilist_is_spacer,
    fbp_uilist_row_layouts,
)
from .custom_effects import (
    find_custom_effect_group,
    refresh_one_custom_effect_definition,
)
from .matrix_presets import (
    ASCII_TEXT_GLYPH_LIMIT,
    ascii_gradient,
    ascii_level_gradient,
)
from .effect_schema import (
    FBP_EFFECT_SCHEMA_VERSION,
    finalize_effect_registry,
)
from .effects_registry import (
    FBP_EFFECT_MESH_WIGGLE,
    FBP_EFFECT_STOP_MOTION_CRUMPLE,
    FBP_EFFECT_WIND_BENDER,
    FBP_EFFECT_CUTOUT_OUTLINE,
    FBP_EFFECT_CAMERA_SCALE_LOCK,
    FBP_EFFECT_CAMERA_BILLBOARD,
    FBP_EFFECT_THICKNESS,
    FBP_EFFECT_FELT_FUZZ,
    FBP_EFFECT_FIBER_TUFTS,
    FBP_EFFECT_PAPER_SHARDS,
    FBP_EFFECT_SPHERE_SCREEN,
    FBP_EFFECT_IMAGE_RELIEF,
    FBP_EFFECT_GLASS,
    FBP_EFFECT_CRYSTAL,
    FBP_EFFECT_SURFACE_CONFORM,
    FBP_EFFECT_ACCORDION_FOLD,
    FBP_EFFECT_SCULPT_WAVES,
    FBP_EFFECT_KINETIC_TILES,
    FBP_EFFECT_LAYERED_ECHO,
    FBP_EFFECT_FRAME_STACK,
    FBP_EFFECT_KNIT_CROCHET,
    FBP_EFFECT_LATTICE,
    FBP_EFFECT_MOTION,
    FBP_EFFECT_CROP,
    FBP_EFFECT_EXTEND,
    FBP_EFFECT_PIXELATE,
    FBP_EFFECT_SWIRL,
    FBP_EFFECT_BULGE_PINCH,
    FBP_EFFECT_LENS_WARP,
    FBP_EFFECT_WAVE_WARP,
    FBP_EFFECT_RIPPLE_DISTORTION,
    FBP_EFFECT_KALEIDOSCOPE,
    FBP_EFFECT_HEX_PIXELATE,
    FBP_EFFECT_MOSAIC_JITTER,
    FBP_EFFECT_SLICE_SHIFT,
    FBP_EFFECT_CURVES,
    FBP_EFFECT_GRADIENT_LIGHT,
    FBP_EFFECT_RIM,
    FBP_EFFECT_SHADOW,
    FBP_EFFECT_DEPTH_BLUR,
    FBP_EFFECT_GAUSSIAN_BLUR,
    FBP_EFFECT_DIRECTIONAL_BLUR,
    FBP_EFFECT_TRIANGLE_BLUR, FBP_EFFECT_TILT_SHIFT, FBP_EFFECT_UNSHARP_MASK, FBP_EFFECT_EDGE_DETECT,
    FBP_EFFECT_SMOOTH_TOON, FBP_EFFECT_ADAPTIVE_THRESHOLD, FBP_EFFECT_FALSE_COLOR, FBP_EFFECT_CHROMATIC_ABERRATION,
    FBP_EFFECT_REPLACE_COLOR,
    FBP_EFFECT_INK, FBP_EFFECT_EDGE_WORK, FBP_EFFECT_PENCIL_SKETCH, FBP_EFFECT_POSTER_EDGES,
    FBP_EFFECT_CROSSHATCH, FBP_EFFECT_EMBOSS,
    FBP_EFFECT_ALPHA_MATTE,
    FBP_EFFECT_LUMA_MATTE,
    FBP_EFFECT_SQUARE_MASK,
    FBP_EFFECT_CIRCLE_MASK,
    FBP_EFFECT_TRIANGLE_MASK,
    FBP_EFFECT_CLIPPING_MASK,
    FBP_EFFECT_IMPORTED_MASK,
    GP_MASK_EFFECT_IDS,
    FBP_EFFECT_LAYER_BLEND,
    FBP_EFFECT_COLOR_MASK,
    FBP_EFFECT_LUMINANCE_MASK,
    FBP_EFFECT_CHANNEL_MASK,
    FBP_EFFECT_GRADIENT_MASK,
    FBP_EFFECT_NOISE_MASK,
    FBP_EFFECT_VORONOI_MASK,
    FBP_EFFECT_WAVE_MASK,
    FBP_EFFECT_EDGE_DISTANCE_MASK,
    FBP_EFFECT_DITHER,
    FBP_EFFECT_BLOOM,
    FBP_EFFECT_FILTER_PRESETS,
    FBP_EFFECT_DIGITAL_NOISE,
    FBP_EFFECT_HALFTONE,
    FBP_EFFECT_RISO_PRINT,
    FBP_EFFECT_OIL_PAINT,
    FBP_EFFECT_DOT_MATRIX,
    FBP_EFFECT_ASCII_MATRIX,
    FBP_EFFECT_ASCII,
    FBP_EFFECT_TEXT_MATRIX,
    FBP_EFFECT_REGISTRY,
    fbp_refresh_custom_effect_registry,
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
    fbp_normalize_effect_id,
)
from .runtime import (
    FBP_DATA_ERRORS,
    fbp_set_rna_property_silent,
    fbp_warn,
    fbp_obj_runtime_key,
    fbp_obj_runtime_token,
    fbp_modifier_runtime_key
)
from .ui_list_state import mark_ui_list_draw

from .geometry_nodes import (  # noqa: E402 - defined before geometry_nodes imports this module
    _FBP_EXTRUDE_SAFE_SAMPLE_BUDGETS,
    _FBP_LATTICE_BAKED_KEY,
    _FBP_VARIANT_CONTEXT_KEY,
    _fbp_animation_key,
    _fbp_auto_rows_label,
    _fbp_custom_geometry_value_sockets,
    _fbp_custom_shader_value_sockets,
    _fbp_depth_blur_focus_distance,
    _fbp_effect_can_receive_mask,
    _fbp_effect_evolution_speed_property,
    _fbp_effect_group_record,
    _fbp_effect_ids_cache_key,
    _fbp_effect_instance_channel_identity,
    _fbp_effect_is_local_mask,
    _fbp_effect_ref,
    _fbp_effect_ref_effect_id,
    _fbp_effect_ref_instance_id,
    _fbp_effect_ref_is_active,
    _fbp_effect_ref_parts,
    _fbp_effect_uses_multi_instances,
    _fbp_extrude_follows_pixelate,
    _fbp_extrude_grid,
    _fbp_find_shader_effect_nodes_for_rig,
    _fbp_instance_channel_value_attr,
    _fbp_interface_input_identifier,
    _fbp_last_lattice_error,
    _fbp_lattice_contract_is_valid,
    _fbp_lattice_mesh_detail_mode,
    _fbp_lattice_mode,
    _fbp_lattice_modifier,
    _fbp_lattice_object,
    _fbp_lattice_scene_camera,
    _fbp_material_image_node,
    _fbp_modifier_input_handle,
    _fbp_modifier_input_has,
    _fbp_modifier_input_is_visible,
    _fbp_node_socket,
    _fbp_pixelate_grid,
    _fbp_plane,
    _fbp_plane_materials,
    _fbp_runtime_effect_ids,
    _fbp_scene_camera,
    _fbp_schedule_custom_geometry_init,
    _fbp_schedule_custom_shader_sync,
    _fbp_schedule_lattice_contract_repair,
    _fbp_selected_rigs,
    _fbp_shader_effect_nodes,
    _fbp_track_to_camera_constraint,
    fbp_effect_debug_mode,
    fbp_effect_global_visible_state,
    fbp_effect_group_members_from_items,
    fbp_effect_ids_for_rig,
    fbp_effect_input_source,
    fbp_effect_instance_animation_item,
    fbp_effect_is_active,
    fbp_effect_is_soloed,
    fbp_effect_mask_raw_target_ref,
    fbp_effect_mask_target,
    fbp_effect_mask_target_ref,
    fbp_effect_performance_hint,
    fbp_effect_visible_state,
    fbp_find_effect_modifier,
    fbp_layer_relation_status,
    fbp_mask_stack_operation,
    fbp_masks_targeting_effect,
    fbp_update_shader_effect,
)


def _geometry_nodes_module():
    # Names geometry_nodes defines after importing this module.
    from . import geometry_nodes
    return geometry_nodes


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

    Related effects remain separate runtime contracts and are presented as one
    user-facing family with the active variant appended.
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


_FBP_EFFECT_UI_LABEL_CACHE = {}
_FBP_EFFECT_UI_ICON_CACHE = {}
_FBP_EFFECT_NATIVE_VISIBILITY_CACHE = {}
_FBP_EFFECT_RNA_METADATA_CACHE = {}
_FBP_EFFECT_UI_FULL_WIDTH_CACHE = {}
_FBP_EFFECT_UI_SLIDER_CACHE = {}


def _fbp_effect_property_label(definition, prop_name, labels=None):
    """Resolve one stable display label from registry metadata or local context."""
    labels = labels or {}
    definition = definition or {}
    effect_id = str(definition.get("effect_id", "") or "")
    local_label = labels.get(prop_name)
    # Registry definitions normally carry ``effect_id`` after finalization.
    # Custom entries may omit it; avoid a cross-effect label collision.
    cache_key = None if local_label is not None or not effect_id else (effect_id, prop_name)
    if cache_key is not None:
        cached = _FBP_EFFECT_UI_LABEL_CACHE.get(cache_key)
        if cached is not None:
            return cached
    ui_labels = definition.get("ui_labels", {}) or {}
    property_map = definition.get("property_map", {}) or {}
    candidate = local_label or ui_labels.get(prop_name) or property_map.get(prop_name) or prop_name
    label = _fbp_clean_effect_ui_label(candidate, effect_id=effect_id, fallback="Value")
    if cache_key is not None:
        if len(_FBP_EFFECT_UI_LABEL_CACHE) >= 2048 and cache_key not in _FBP_EFFECT_UI_LABEL_CACHE:
            _FBP_EFFECT_UI_LABEL_CACHE.clear()
        _FBP_EFFECT_UI_LABEL_CACHE[cache_key] = label
    return label


def _fbp_effect_property_icon(prop_name, label=""):
    """Choose a semantic native Blender icon for one effect control.

    Control meaning must win over the effect name embedded in the RNA property.
    For example ``fbp_wave_mask_invert`` contains the word ``wave`` but the
    button is an Invert action, so it must never inherit the Wave Mask icon.
    """
    prop_token = str(prop_name or "").strip().lower()
    label_token = str(label or "").strip().lower()
    cache_key = (prop_token, label_token)
    cached = _FBP_EFFECT_UI_ICON_CACHE.get(cache_key)
    if cached is not None:
        return cached

    probe = f"{prop_token} {label_token}"
    terminal = prop_token.rsplit("_", 1)[-1] if prop_token else ""

    # Exact action/state controls take precedence over effect-family words.
    if terminal == "invert" or label_token == "invert":
        icon = ui_icon("action.invert")
    elif terminal in {"reverse", "mirror", "flip"} or label_token in {"reverse", "mirror", "flip"}:
        icon = "ARROW_LEFTRIGHT"
    elif terminal in {"enabled", "enable", "active"}:
        icon = "CHECKBOX_HLT"
    elif terminal in {"show", "visible", "visibility"}:
        icon = "HIDE_OFF"
    else:
        icon = "OPTIONS"
        # More specific control concepts precede broad effect-family matches.
        for words, candidate in (
            (("color", "foreground", "background", "shadow", "highlight", "tint", "despill"), "COLOR"),
            (("softness", "feather", "falloff", "blur"), "MOD_SMOOTH"),
            (("alpha", "opacity", "threshold", "matte"), "IMAGE_ALPHA"),
            (("factor", "influence", "strength", "amount", "intensity", "mix"), "MODIFIER"),
            (("speed", "phase", "step", "hold", "animate", "evolve", "evolution", "flicker", "time"), "TIME"),
            (("uv", "offset", "position", "center", "pivot"), "UV"),
            (("rotation", "angle", "direction", "orientation"), "ORIENTATION_GLOBAL"),
            (("width", "height", "radius", "length", "size", "distance", "scale"), "DRIVER_DISTANCE"),
            (("subdivision", "resolution", "density", "quality", "samples"), "MOD_SUBSURF"),
            (("columns", "rows", "count", "levels", "characters"), "LINENUMBERS_ON"),
            (("pixel", "grid", "cell", "spacing"), "ALIASED"),
            (("seed", "noise", "detail", "roughness", "turbulence", "grain", "variation", "random"), "RNDCURVE"),
            (("frequency", "wave", "curl", "distortion"), "IPO_SINE"),
            (("camera", "lens", "sensor", "focus"), "CAMERA_DATA"),
            (("font", "text", "glyph", "ascii"), "FONT_DATA"),
            (("source", "image", "texture"), "IMAGE_DATA"),
            (("material", "shade", "blend"), "MATERIAL"),
            (("edge", "outline", "border"), "MOD_EDGESPLIT"),
        ):
            if any(word in probe for word in words):
                icon = candidate
                break

    if len(_FBP_EFFECT_UI_ICON_CACHE) >= 4096 and cache_key not in _FBP_EFFECT_UI_ICON_CACHE:
        _FBP_EFFECT_UI_ICON_CACHE.clear()
    _FBP_EFFECT_UI_ICON_CACHE[cache_key] = icon
    return icon


def _fbp_effect_rna_metadata(rig, prop_name):
    """Return primitive RNA metadata without caching Blender RNA wrappers.

    RNA Property objects can become invalid after extension reload, Undo or
    property re-registration. The UI only needs three scalar fields, so cache a
    primitive tuple and resolve the RNA object only on a cache miss.
    """
    prop_name = str(prop_name or "")
    try:
        rna_id = str(getattr(getattr(rig, "bl_rna", None), "identifier", "") or "")
    except FBP_DATA_ERRORS:
        rna_id = ""
    cache_key = (rna_id, prop_name)
    cached = _FBP_EFFECT_RNA_METADATA_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        properties = getattr(getattr(rig, "bl_rna", None), "properties", None)
        rna_prop = properties.get(prop_name) if properties is not None else None
        metadata = (
            str(getattr(rna_prop, "type", "") or ""),
            str(getattr(rna_prop, "subtype", "") or ""),
            int(getattr(rna_prop, "array_length", 0) or 0),
        ) if rna_prop is not None else ("", "", 0)
    except FBP_DATA_ERRORS:
        metadata = ("", "", 0)
    if len(_FBP_EFFECT_RNA_METADATA_CACHE) >= 4096 and cache_key not in _FBP_EFFECT_RNA_METADATA_CACHE:
        _FBP_EFFECT_RNA_METADATA_CACHE.clear()
    _FBP_EFFECT_RNA_METADATA_CACHE[cache_key] = metadata
    return metadata


_FBP_EFFECT_DEFINITION_ID_CACHE = {}


def _fbp_effect_id_from_definition(definition):
    """Resolve a registry dictionary to its stable effect ID once per reload."""
    if not definition:
        return ""
    pointer = id(definition)
    cached = _FBP_EFFECT_DEFINITION_ID_CACHE.get(pointer)
    if cached is not None:
        return cached
    effect_id = ""
    try:
        for candidate_id, candidate in FBP_EFFECT_REGISTRY.items():
            if candidate is definition:
                effect_id = str(candidate_id or "")
                break
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        effect_id = ""
    if len(_FBP_EFFECT_DEFINITION_ID_CACHE) >= 512:
        _FBP_EFFECT_DEFINITION_ID_CACHE.clear()
    _FBP_EFFECT_DEFINITION_ID_CACHE[pointer] = effect_id
    return effect_id


def _fbp_effect_property_native_visible(rig, definition, prop_name):
    """Use Blender 5.2 to hide GN inputs disabled by the active node setup."""
    if str((definition or {}).get("kind", "") or "").upper() != "GEOMETRY":
        return True
    socket_name = str(((definition or {}).get("property_map", {}) or {}).get(prop_name, "") or "")
    if not socket_name:
        return True
    effect_id = _fbp_effect_id_from_definition(definition)
    if not effect_id:
        return True
    modifier = fbp_find_effect_modifier(rig, effect_id)
    node_group = getattr(modifier, "node_group", None) if modifier else None
    if modifier is None or node_group is None:
        return True
    try:
        key = (
            fbp_obj_runtime_key(rig),
            effect_id,
            fbp_modifier_runtime_key(modifier),
            fbp_obj_runtime_key(node_group),
            str(prop_name or ""),
        )
    except FBP_DATA_ERRORS:
        key = None
    if key is not None and key in _FBP_EFFECT_NATIVE_VISIBILITY_CACHE:
        return bool(_FBP_EFFECT_NATIVE_VISIBILITY_CACHE[key])
    identifier = _fbp_interface_input_identifier(node_group, socket_name)
    visible = True if not identifier else _fbp_modifier_input_is_visible(modifier, identifier)
    if key is not None:
        if len(_FBP_EFFECT_NATIVE_VISIBILITY_CACHE) >= 4096:
            _FBP_EFFECT_NATIVE_VISIBILITY_CACHE.clear()
        _FBP_EFFECT_NATIVE_VISIBILITY_CACHE[key] = bool(visible)
    return bool(visible)


def _fbp_effect_property_full_width(rig, prop_name, label):
    cache_key = (str(prop_name or ""), str(label or ""))
    cached = _FBP_EFFECT_UI_FULL_WIDTH_CACHE.get(cache_key)
    if cached is not None:
        return cached
    prop_type, subtype, array_length = _fbp_effect_rna_metadata(rig, prop_name)
    result = bool(
        prop_type in {"ENUM", "STRING", "POINTER"}
        or subtype in {"COLOR", "COLOR_GAMMA", "FILE_PATH", "DIR_PATH"}
        or array_length > 1
        or len(str(label or "")) > 19
    )
    if len(_FBP_EFFECT_UI_FULL_WIDTH_CACHE) >= 4096 and cache_key not in _FBP_EFFECT_UI_FULL_WIDTH_CACHE:
        _FBP_EFFECT_UI_FULL_WIDTH_CACHE.clear()
    _FBP_EFFECT_UI_FULL_WIDTH_CACHE[cache_key] = result
    return result


def _fbp_effect_property_uses_slider(rig, prop_name, label):
    cache_key = (str(prop_name or ""), str(label or ""))
    cached = _FBP_EFFECT_UI_SLIDER_CACHE.get(cache_key)
    if cached is not None:
        return cached
    prop_type, _subtype, _array_length = _fbp_effect_rna_metadata(rig, prop_name)
    if prop_type not in {"FLOAT", "INT"}:
        result = False
    else:
        probe = f"{prop_name} {label}".lower()
        result = any(
            word in probe
            for word in (
                "amount", "contrast", "despill", "factor", "falloff", "influence",
                "intensity", "opacity", "progress", "roughness", "softness",
                "strength", "threshold", "tolerance", "width",
            )
        )
    if len(_FBP_EFFECT_UI_SLIDER_CACHE) >= 4096 and cache_key not in _FBP_EFFECT_UI_SLIDER_CACHE:
        _FBP_EFFECT_UI_SLIDER_CACHE.clear()
    _FBP_EFFECT_UI_SLIDER_CACHE[cache_key] = result
    return result


def _fbp_draw_effect_property(layout, rig, definition, prop_name, labels=None):
    if not hasattr(rig, prop_name):
        return False
    if not _fbp_effect_property_native_visible(rig, definition, prop_name):
        return False
    label = _fbp_effect_property_label(definition, prop_name, labels)
    prop_type, _subtype, _array_length = _fbp_effect_rna_metadata(rig, prop_name)
    is_bool = prop_type == "BOOLEAN"
    if is_bool:
        # On/off options read as checkboxes, like Blender's own modifiers,
        # instead of full-width blue toggle bars.
        layout.prop(rig, prop_name, text=label)
        return True
    kwargs = {
        "text": label,
        "icon": _fbp_effect_property_icon(prop_name, label),
    }
    if _fbp_effect_property_uses_slider(rig, prop_name, label):
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
        if not _fbp_effect_property_native_visible(rig, definition, prop_name):
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
        ("Quality", "MOD_SUBSURF", ("fbp_mesh_wiggle_subdivisions", "fbp_mesh_wiggle_playback_subdivisions", "fbp_mesh_wiggle_render_subdivisions", "fbp_mesh_wiggle_shade_smooth")),
        ("Motion", "MOD_NOISE", ("fbp_mesh_wiggle_strength", "fbp_mesh_wiggle_speed", "fbp_mesh_wiggle_hold", "fbp_mesh_wiggle_w")),
        ("Noise", "RNDCURVE", ("fbp_mesh_wiggle_noise_scale", "fbp_mesh_wiggle_detail", "fbp_mesh_wiggle_seed", "fbp_mesh_wiggle_unique_seed")),
    ),
    FBP_EFFECT_FELT_FUZZ: (
        ("Quality", "MOD_SUBSURF", ("fbp_felt_render_density", "fbp_felt_viewport_percentage", "fbp_felt_subdivisions", "fbp_felt_alpha_resolution")),
        ("Fuzz", "MODIFIER", ("fbp_felt_fuzz_length", "fbp_felt_fuzz_radius", "fbp_felt_curl_amount", "fbp_felt_alpha_threshold")),
    ),
    FBP_EFFECT_FIBER_TUFTS: (
        ("Quality", "MOD_SUBSURF", ("fbp_fiber_render_density", "fbp_fiber_viewport_percentage", "fbp_fiber_segments", "fbp_fiber_alpha_resolution")),
        ("Fiber", "CURVES_DATA", ("fbp_fiber_length", "fbp_fiber_luminance_length", "fbp_fiber_radius", "fbp_fiber_bend")),
        ("Variation", "RNDCURVE", ("fbp_fiber_randomness", "fbp_fiber_seed", "fbp_fiber_alpha_threshold")),
    ),
    FBP_EFFECT_PAPER_SHARDS: (
        ("Quality", "MOD_SUBSURF", ("fbp_shards_render_density", "fbp_shards_viewport_percentage", "fbp_shards_alpha_resolution")),
        ("Geometry", "MESH_CUBE", ("fbp_shards_size", "fbp_shards_aspect", "fbp_shards_thickness", "fbp_shards_lift", "fbp_shards_luminance_lift")),
        ("Scatter", "PARTICLES", ("fbp_shards_tilt", "fbp_shards_scale_randomness", "fbp_shards_seed", "fbp_shards_alpha_threshold")),
    ),
    FBP_EFFECT_SPHERE_SCREEN: (
        ("Viewport", "HIDE_OFF", ("fbp_sphere_screen_viewport_columns", "fbp_sphere_screen_viewport_rows")),
        ("Render", "RESTRICT_RENDER_OFF", ("fbp_sphere_screen_render_columns", "fbp_sphere_screen_render_rows")),
        ("Solids", "MESH_ICOSPHERE", ("fbp_sphere_screen_shape", "fbp_sphere_screen_scale", "fbp_sphere_screen_luminance_size", "fbp_sphere_screen_subdivisions")),
        ("Depth", "MOD_DISPLACE", ("fbp_sphere_screen_depth", "fbp_sphere_screen_depth_mode", "fbp_sphere_screen_depth_image")),
        ("Light & Animation", "LIGHT", ("fbp_sphere_screen_emission", "fbp_sphere_screen_flicker", "fbp_sphere_screen_phase")),
        ("Source", "IMAGE_DATA", ("fbp_sphere_screen_alpha_threshold", "fbp_sphere_screen_show_source")),
    ),
    FBP_EFFECT_IMAGE_RELIEF: (
        ("Quality", "MOD_SUBSURF", ("fbp_image_relief_subdivision", "fbp_image_relief_playback_subdivision", "fbp_image_relief_render_subdivision")),
        ("Depth", "MOD_DISPLACE", ("fbp_image_relief_depth", "fbp_image_relief_midlevel", "fbp_image_relief_depth_mode", "fbp_image_relief_depth_image")),
        ("Smoothing", "MOD_SMOOTH", ("fbp_image_relief_smooth", "fbp_image_relief_smooth_iterations")),
        ("Surface", "NORMALS_FACE", ("fbp_image_relief_alpha_threshold", "fbp_image_relief_shade_smooth")),
    ),
    FBP_EFFECT_GLASS: (
        ("Shatter", "MOD_EXPLODE", ("fbp_glass_shatter", "fbp_glass_impact_x", "fbp_glass_impact_y", "fbp_glass_spread", "fbp_glass_gap", "fbp_glass_explode", "fbp_glass_depth", "fbp_glass_fall", "fbp_glass_spin")),
        ("Pieces", "MOD_TRIANGULATE", ("fbp_glass_pattern", "fbp_glass_pieces", "fbp_glass_irregularity", "fbp_glass_phase", "fbp_glass_thickness", "fbp_glass_alpha_threshold")),
        ("Glass", "MATERIAL", ("fbp_glass_use_glass", "fbp_glass_roughness", "fbp_glass_ior", "fbp_glass_tint", "fbp_glass_source_color", "fbp_glass_edge_tint", "fbp_glass_absorption")),
    ),
    FBP_EFFECT_CRYSTAL: (
        ("Quality", "MOD_SUBSURF", ("fbp_crystal_subdivision", "fbp_crystal_playback_subdivision", "fbp_crystal_render_subdivision", "fbp_crystal_silhouette_detail", "fbp_crystal_surface_subdivision")),
        ("Alpha Depth", "MOD_DISPLACE", ("fbp_crystal_depth", "fbp_crystal_thickness", "fbp_crystal_roundness", "fbp_crystal_edge_pinning", "fbp_crystal_blur_iterations", "fbp_crystal_alpha_threshold")),
        ("Influence Map", "IMAGE_DATA", ("fbp_crystal_use_influence_map", "fbp_crystal_influence_image", "fbp_crystal_invert_influence", "fbp_crystal_influence_strength")),
        ("Procedural Surface", "NODE_TEXTURE", ("fbp_crystal_texture_type", "fbp_crystal_pattern_mode", "fbp_crystal_pattern_scale", "fbp_crystal_correct_aspect", "fbp_crystal_texture_scale_x", "fbp_crystal_texture_scale_y", "fbp_crystal_pattern_detail", "fbp_crystal_pattern_strength", "fbp_crystal_cell_randomness", "fbp_crystal_cell_seed", "fbp_crystal_phase", "fbp_crystal_shade_smooth")),
        ("Optics", "MATERIAL", ("fbp_crystal_distortion", "fbp_crystal_roughness", "fbp_crystal_ior", "fbp_crystal_tint", "fbp_crystal_source_color", "fbp_crystal_absorption", "fbp_crystal_thin_wall")),
    ),
    FBP_EFFECT_SURFACE_CONFORM: (
        ("Target", "MOD_SHRINKWRAP", ("fbp_surface_conform_target", "fbp_surface_conform_factor", "fbp_surface_conform_offset", "fbp_surface_conform_max_distance")),
        ("Quality", "MOD_SUBSURF", ("fbp_surface_conform_subdivision", "fbp_surface_conform_playback_subdivision", "fbp_surface_conform_render_subdivision")),
        ("Surface", "NORMALS_FACE", ("fbp_surface_conform_shade_smooth",)),
    ),
    FBP_EFFECT_ACCORDION_FOLD: (
        ("Quality", "MOD_SUBSURF", ("fbp_accordion_subdivision", "fbp_accordion_playback_subdivision", "fbp_accordion_render_subdivision")),
        ("Folds", "MOD_SIMPLEDEFORM", ("fbp_accordion_folds", "fbp_accordion_depth", "fbp_accordion_vertical", "fbp_accordion_shade_smooth")),
        ("Animation", "ANIM", ("fbp_accordion_phase",)),
    ),
    FBP_EFFECT_SCULPT_WAVES: (
        ("Quality", "MOD_SUBSURF", ("fbp_sculpt_waves_subdivision", "fbp_sculpt_waves_playback_subdivision", "fbp_sculpt_waves_render_subdivision")),
        ("Sculpt", "MOD_WAVE", ("fbp_sculpt_waves_style", "fbp_sculpt_waves_amplitude", "fbp_sculpt_waves_frequency", "fbp_sculpt_waves_edge_falloff")),
        ("Animation", "ANIM", ("fbp_sculpt_waves_phase",)),
        ("Surface", "NORMALS_FACE", ("fbp_sculpt_waves_shade_smooth",)),
    ),
    FBP_EFFECT_KINETIC_TILES: (
        ("Quality", "MOD_SUBSURF", ("fbp_kinetic_tiles_subdivision", "fbp_kinetic_tiles_playback_subdivision", "fbp_kinetic_tiles_render_subdivision")),
        ("Tiles", "MESH_GRID", ("fbp_kinetic_tiles_pattern", "fbp_kinetic_tiles_gap", "fbp_kinetic_tiles_thickness")),
        ("Animation", "ANIM", ("fbp_kinetic_tiles_motion", "fbp_kinetic_tiles_frequency", "fbp_kinetic_tiles_phase")),
        ("Surface", "NORMALS_FACE", ("fbp_kinetic_tiles_shade_smooth",)),
    ),
    FBP_EFFECT_LAYERED_ECHO: (
        ("Quality", "MOD_SUBSURF", ("fbp_layered_echo_layers", "fbp_layered_echo_playback_layers", "fbp_layered_echo_render_layers")),
        ("Transform", "MOD_ARRAY", ("fbp_layered_echo_offset_x", "fbp_layered_echo_offset_y", "fbp_layered_echo_spacing", "fbp_layered_echo_scale_step")),
        ("Rotation", "ORIENTATION_LOCAL", ("fbp_layered_echo_rotation_x", "fbp_layered_echo_rotation_y", "fbp_layered_echo_twist")),
        ("Animation", "ANIM", ("fbp_layered_echo_wave", "fbp_layered_echo_phase")),
    ),
    FBP_EFFECT_KNIT_CROCHET: (
        ("Stitches", "OUTLINER_DATA_CURVES", ("fbp_yarn_stitch_type", "fbp_yarn_columns", "fbp_yarn_row_height", "fbp_yarn_loop_width")),
        ("Yarn", "MOD_SCREW", ("fbp_yarn_thickness", "fbp_yarn_plies", "fbp_yarn_twist", "fbp_yarn_fuzz", "fbp_yarn_self_light")),
        ("Hand-made", "SHADERFX", ("fbp_yarn_color_variation", "fbp_yarn_jitter", "fbp_yarn_seed")),
        ("Image", "IMAGE_DATA", ("fbp_yarn_alpha_threshold", "fbp_yarn_show_plane")),
    ),
    FBP_EFFECT_FRAME_STACK: (
        ("Time", "TIME", ("fbp_frame_stack_slices", "fbp_frame_stack_step", "fbp_frame_stack_fixed_start", "fbp_frame_stack_start_frame", "fbp_frame_stack_show_plane")),
        ("Stack Shape", "MOD_ARRAY", ("fbp_frame_stack_spacing", "fbp_frame_stack_offset_x", "fbp_frame_stack_offset_y", "fbp_frame_stack_scale_step", "fbp_frame_stack_rotation_x", "fbp_frame_stack_rotation_y", "fbp_frame_stack_twist")),
        ("Opacity", "MOD_OPACITY", ("fbp_frame_stack_glow", "fbp_frame_stack_front_slices", "fbp_frame_stack_front_opacity", "fbp_frame_stack_back_opacity", "fbp_frame_stack_depth_fade", "fbp_frame_stack_luminance_opacity")),
        ("Outline", "MESH_CUBE", ("fbp_frame_stack_outline", "fbp_frame_stack_outline_width", "fbp_frame_stack_outline_color")),
        ("Quality", "MOD_SUBSURF", ("fbp_frame_stack_detail",)),
    ),
    FBP_EFFECT_SHADOW: (
        ("Shadow", "SHADING_RENDERED", ("fbp_shadow_mode", "fbp_shadow_blend_mode", "fbp_shadow_color", "fbp_shadow_opacity")),
        ("Position & Softness", "UV", ("fbp_shadow_offset_x", "fbp_shadow_offset_y", "fbp_shadow_blur")),
    ),
    FBP_EFFECT_RIM: (
        ("Rim", "MOD_OUTLINE", ("fbp_rim_mode", "fbp_rim_blend_mode", "fbp_rim_color", "fbp_rim_intensity")),
        ("Edge Selection", "SELECT_SET", ("fbp_rim_width", "fbp_rim_expand", "fbp_rim_blur", "fbp_rim_softness")),
        ("Position", "UV", ("fbp_rim_offset_x", "fbp_rim_offset_y", "fbp_rim_rotation")),
    ),
    FBP_EFFECT_DIGITAL_NOISE: (
        ("Noise", "RNDCURVE", ("fbp_digital_noise_luma", "fbp_digital_noise_chroma", "fbp_digital_noise_scale", "fbp_digital_noise_shadow_bias")),
        ("Noise Phase", "RNDCURVE", ("fbp_digital_noise_seed",)),
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
        ("Wave", "MOD_WAVE", ("fbp_wave_warp_amplitude", "fbp_wave_warp_frequency", "fbp_wave_warp_phase")),
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
    FBP_EFFECT_PIXELATE: (
        ("Grid", "MESH_GRID", ("fbp_pixelate_grid_mode", "fbp_pixelate_size", "fbp_pixelate_stretch", "fbp_pixelate_resolution", "fbp_pixelate_height")),
        ("Transform", "ORIENTATION_GLOBAL", ("fbp_pixelate_rotation", "fbp_pixelate_offset_x", "fbp_pixelate_offset_y")),
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
    FBP_EFFECT_SLICE_SHIFT: (
        ("Bands", "MOD_DISPLACE", ("fbp_slice_shift_angle", "fbp_slice_shift_bands", "fbp_slice_shift_shift")),
        ("Random & Mix", "RNDCURVE", ("fbp_slice_shift_random", "fbp_slice_shift_seed", "fbp_slice_shift_factor")),
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
    FBP_EFFECT_OIL_PAINT: (
        ("Brush", "BRUSHES_ALL", ("fbp_oil_paint_radius", "fbp_oil_paint_sharpness", "fbp_oil_paint_anisotropy")),
        ("Mix", "MODIFIER", ("fbp_oil_paint_factor",)),
    ),
    FBP_EFFECT_RISO_PRINT: (
        ("Inks", "COLOR", ("fbp_riso_ink_1", "fbp_riso_ink_2", "fbp_riso_use_ink_3", "fbp_riso_ink_3", "fbp_riso_paper")),
        ("Print", "OUTLINER_OB_IMAGE", ("fbp_riso_misregistration", "fbp_riso_halftone", "fbp_riso_dot_size", "fbp_riso_grain", "fbp_riso_drift_angle", "fbp_riso_print_rotation", "fbp_riso_seed")),
        ("Mix", "MODIFIER", ("fbp_riso_factor",)),
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
    FBP_EFFECT_REPLACE_COLOR: (
        ("Colors", "EYEDROPPER", ("fbp_replace_color_source", "fbp_replace_color_target", "fbp_replace_color_tolerance", "fbp_replace_color_softness")),
        ("Mix", "MODIFIER", ("fbp_replace_color_preserve_shading", "fbp_replace_color_factor")),
    ),
    FBP_EFFECT_CHROMATIC_ABERRATION: (
        ("Chromatic Offset", "SEQ_CHROMA_SCOPE", ("fbp_chromatic_aberration_distance", "fbp_chromatic_aberration_angle")),
        ("Mix", "MODIFIER", ("fbp_chromatic_aberration_factor",)),
    ),
    FBP_EFFECT_DITHER: (
        ("Pattern", "MESH_GRID", ("fbp_dither_style", "fbp_dither_size")),
        ("Tone", "SEQ_LUMA_WAVEFORM", ("fbp_dither_brightness", "fbp_dither_contrast", "fbp_dither_factor")),
        ("Mono", "COLOR", ("fbp_dither_mono", "fbp_dither_mono_color")),
    ),
    FBP_EFFECT_BLOOM: (
        ("Highlights", "LIGHT_SUN", ("fbp_bloom_threshold", "fbp_bloom_softness", "fbp_bloom_intensity")),
        ("Color & Mix", "COLOR", ("fbp_bloom_color", "fbp_bloom_factor")),
    ),
    FBP_EFFECT_FILTER_PRESETS: (
        ("Presets", "PRESET", ("fbp_filter_preset_sepia", "fbp_filter_preset_warm", "fbp_filter_preset_cool", "fbp_filter_preset_noir")),
        ("Mix", "MODIFIER", ("fbp_filter_preset_factor",)),
    ),
    FBP_EFFECT_INK: (
        ("Line Extraction", "OUTLINER_OB_GREASEPENCIL", ("fbp_ink_width", "fbp_ink_threshold", "fbp_ink_softness", "fbp_ink_strength")),
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


_FBP_AUTO_UI_SECTIONS = (
    # (title, icon, words or phrases). Matched as whole words, first wins.
    ("Source / UV", "UV", (
        "source", "matte", "path", "image", "texture", "camera projection",
        "follow source", "uv",
    )),
    ("Transform", "ORIENTATION_GLOBAL", (
        "center", "offset", "rotation", "angle", "direction", "position",
        "scale x", "scale y", "tracking", "face away",
    )),
    ("Grid", "MESH_GRID", (
        "grid", "cell", "pixel", "row", "column", "spacing", "cage", "loop",
    )),
    ("Quality", "MOD_SUBSURF", (
        "sample", "subdivision", "resolution", "density", "viewport", "playback",
        "render", "quality", "interpolation", "iteration",
    )),
    ("Color / Tone", "COLOR", (
        "color", "hue", "saturation", "brightness", "contrast", "tone",
        "foreground", "background", "paper", "ink", "tint", "balance",
        "temperature", "value", "gamma", "tolerance", "light", "shadow", "highlight",
        "midtone", "midpoint", "desaturation", "red", "green", "blue",
    )),
    ("Alpha / Mask", "IMAGE_ALPHA", (
        "alpha", "mask", "threshold", "softness", "feather",
        "invert", "key", "despill", "clip", "transparent", "channel",
    )),
    ("Pinning", "PINNED", ("pin",)),
    ("Pattern", "TEXTURE", (
        "pattern", "scale", "detail", "roughness", "randomness", "distortion",
        "shape", "size", "sharpness",
    )),
    ("Motion / Random", "RNDCURVE", (
        "seed", "random", "variation", "noise", "phase", "speed", "stepped",
        "hold", "animate", "flicker", "turbulence", "gust", "w", "evolution",
        "wiggle", "wave", "motion",
    )),
    ("Shape / Mix", "MODIFIER", (
        "width", "height", "radius", "amount", "strength", "factor",
        "intensity", "opacity", "distance", "blur", "falloff", "zoom",
        "thickness", "extrude", "mode", "array", "length", "influence",
        "smoothness", "top", "left", "right", "bottom",
    )),
)


def _fbp_auto_ui_words(text):
    """Lower-case words of ``text`` with a plural ``s`` dropped."""
    words = []
    for word in re.findall(r"[a-z0-9]+", str(text or "").lower()):
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.append(word)
    return words


def _fbp_auto_effect_ui_section(prop_name, label, effect_words=()):
    """Choose a compact settings section for registry-driven effect UIs.

    Words are matched whole, from the label and the property name without
    the effect's own name, so "Triangle Mask" is not a rotation setting and
    "Wind" is not the "W" of a noise.
    """
    skip = {"fbp", *(effect_words or ())}
    words = _fbp_auto_ui_words(label) + [
        word for word in _fbp_auto_ui_words(prop_name) if word not in skip
    ]
    probe = f" {' '.join(words)} "
    for title, icon, keys in _FBP_AUTO_UI_SECTIONS:
        for key in keys:
            if f" {' '.join(_fbp_auto_ui_words(key))} " in probe:
                return title, icon
    return "Settings", "OPTIONS"


def _fbp_build_auto_effect_ui_groups():
    """Add grouped settings to every effect that does not have a custom layout.

    Dedicated panels keep their hand-authored controls. Registry-only effects
    get consistent, compact sections automatically so newly added effects never
    fall back to a flat, hard-to-scan property list.
    """
    for effect_id, definition in FBP_EFFECT_REGISTRY.items():
        if effect_id in _FBP_EFFECT_UI_GROUPS:
            continue
        if bool(definition.get("hidden", False)) or bool(definition.get("custom", False)):
            continue
        if bool(definition.get("custom_ui", False)):
            continue
        property_names = tuple((definition.get("property_map", {}) or {}))
        if not property_names:
            continue
        buckets = []
        bucket_index = {}
        effect_words = set(_fbp_auto_ui_words(effect_id.replace("_", " "))) | set(
            _fbp_auto_ui_words(definition.get("label", ""))
        )
        is_mask = str(definition.get("category", "") or "").upper() == "MASK"
        for prop_name in property_names:
            label = _fbp_effect_property_label(definition, prop_name, None)
            title, icon = _fbp_auto_effect_ui_section(prop_name, label, effect_words)
            if is_mask and title in {"Shape / Mix", "Settings"}:
                # A mask's mix and inversion belong with its edge settings.
                title, icon = "Alpha / Mask", "IMAGE_ALPHA"
            key = (title, icon)
            if key not in bucket_index:
                bucket_index[key] = len(buckets)
                buckets.append([title, icon, []])
            buckets[bucket_index[key]][2].append(prop_name)
        # A lone mix factor belongs to the effect's main section, not to a
        # section of its own.
        if len(buckets) > 1:
            for bucket in tuple(buckets[1:]):
                labels = {
                    str(_fbp_effect_property_label(definition, name, None) or "").lower()
                    for name in bucket[2]
                }
                if labels and labels <= {"factor", "mix"}:
                    buckets[0][2].extend(bucket[2])
                    buckets.remove(bucket)
        _FBP_EFFECT_UI_GROUPS[effect_id] = tuple(
            (title, icon, tuple(names)) for title, icon, names in buckets if names
        )


_fbp_build_auto_effect_ui_groups()


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
        if (
            bool(definition.get("hidden", False))
            or bool(definition.get("custom", False))
            or bool(definition.get("custom_ui", False))
        ):
            continue
        property_map = definition.get("property_map", {}) or {}
        if not property_map:
            issues.append(f"{effect_id}: no editable properties registered")

    for effect_id, groups in _FBP_EFFECT_UI_GROUPS.items():
        definition = FBP_EFFECT_REGISTRY.get(effect_id)
        if not definition:
            issues.append(f"{effect_id}: UI groups reference an unknown effect")
            continue
        registered = set((definition.get("property_map", {}) or {})) | set(definition.get("extra_properties", ()))
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

    issues.extend(
        f"{effect_id}: contextual UI references an unknown effect"
        for effect_id in _FBP_CONTEXTUAL_EFFECT_SETTINGS
        if effect_id not in FBP_EFFECT_REGISTRY
    )
    return tuple(issues)


FBP_EFFECT_SETTINGS_UI_ISSUES = fbp_effect_settings_ui_issues()


def _fbp_effect_control_hidden_properties(_rig, _effect_id):
    """Properties hidden from the panel while a viewport helper drives them.

    None any more: the panel always carries every control the effect needs
    (Swirl's centre, radius and angle, Pixelate's offsets, ...). The viewport
    helper edits the same values, so both stay in sync.
    """
    return frozenset()


def _fbp_draw_registered_effect_properties(layout, rig, effect_id, definition, labels=None, skip=()):
    """Draw every registered editable property and return the number exposed.

    New effects use this path automatically. Dedicated contextual panels must be
    explicitly listed elsewhere, preventing a registry entry from silently
    appearing without settings when a new effect is added.
    """
    skip_names = set(skip or ())
    skip_names.update(_fbp_effect_control_hidden_properties(rig, effect_id))
    property_names = tuple(
        name for name in ((definition or {}).get("property_map", {}) or {})
        if (
            name not in skip_names
            and hasattr(rig, name)
            and _fbp_effect_property_native_visible(rig, definition, name)
        )
    )
    if not property_names:
        return 0

    remaining = set(property_names)
    groups = _FBP_EFFECT_UI_GROUPS.get(effect_id, ())
    visible_group_index = 0
    for title, icon, group_names in groups:
        visible = [name for name in group_names if name in remaining]
        if not visible:
            continue
        panel_id = "fbp_effect_{}_{}".format(
            str(effect_id or "effect").lower(),
            "".join(character if character.isalnum() else "_" for character in title.lower()),
        )
        # Every group starts open: the panel shows all of the effect's
        # controls (Swirl's Radius and Angle used to hide in a closed fold).
        body = _fbp_draw_native_foldout(
            layout, panel_id, title, icon,
            default_closed=False,
        )
        if body is not None:
            _fbp_draw_compact_effect_properties(body, rig, definition, visible, labels)
        visible_group_index += 1
        remaining.difference_update(visible)

    if remaining:
        body = layout
        if groups:
            body = _fbp_draw_native_foldout(
                layout, f"fbp_effect_{str(effect_id or 'effect').lower()}_additional",
                "Additional Settings", "OPTIONS", default_closed=True,
            )
        fallback_order = [name for name in property_names if name in remaining]
        if body is not None:
            _fbp_draw_compact_effect_properties(body, rig, definition, fallback_order, labels)
    return len(property_names)


def _fbp_draw_effect_instance_properties(
    layout, rig, effect_id, instance_id, definition, property_names,
    labels=None, *, grouped=False,
):
    """Draw stable keyframeable channels for one concrete MULTI instance."""
    instance_id = str(instance_id or "")
    requested = [str(name) for name in property_names if str(name or "")]
    channels = {
        str(getattr(channel, "property_name", "") or ""): channel
        for channel in getattr(rig, "fbp_effect_instance_channels", ())
        if (
            bool(getattr(channel, "active", True))
            and _fbp_effect_instance_channel_identity(channel)[:2]
            == (fbp_normalize_effect_id(effect_id), instance_id)
        )
    }
    visible = [name for name in requested if name in channels]
    if not visible:
        row = layout.row(align=False)
        row.enabled = False
        row.label(text="Instance settings are initializing", icon="FILE_REFRESH")
        return 0

    def _draw(target, names):
        for prop_name in names:
            channel = channels.get(prop_name)
            if channel is None:
                continue
            label = _fbp_effect_property_label(definition, prop_name, labels)
            attr = _fbp_instance_channel_value_attr(channel)
            row = target.row(align=False)
            row.prop(
                channel,
                attr,
                text=label,
                slider=str(getattr(channel, "value_kind", "") or "") == "FACTOR",
            )

    if not grouped:
        _draw(layout, visible)
        return len(visible)

    remaining = set(visible)
    visible_group_index = 0
    for title, icon, group_names in _FBP_EFFECT_UI_GROUPS.get(effect_id, ()):
        names = [name for name in group_names if name in remaining]
        if not names:
            continue
        panel_id = "fbp_instance_{}_{}_{}".format(
            str(effect_id or "effect").lower(),
            instance_id[-8:] or "instance",
            "".join(character if character.isalnum() else "_" for character in title.lower()),
        )
        # Every group starts open: the panel shows all of the effect's
        # controls (Swirl's Radius and Angle used to hide in a closed fold).
        body = _fbp_draw_native_foldout(
            layout, panel_id, title, icon,
            default_closed=False,
        )
        if body is not None:
            _draw(body, names)
        remaining.difference_update(names)
        visible_group_index += 1
    if remaining:
        _draw(layout, [name for name in visible if name in remaining])
    return len(visible)


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
    """Draw one shared lightweight section header without nested boxes."""
    if separator:
        section_gap(layout)
    return section_header(
        layout,
        str(title or "Settings"),
        icon=str(icon or "OPTIONS"),
    )


def _fbp_draw_native_foldout(layout, panel_id, title, icon="OPTIONS", *, default_closed=False):
    """Return the body of a Blender-native collapsible settings section."""
    try:
        header, body = layout.panel(str(panel_id), default_closed=bool(default_closed))
        header.label(text=str(title or "Settings"), icon=str(icon or "OPTIONS"))
        return body
    except (AttributeError, RuntimeError, TypeError, ValueError):
        # Defensive fallback for unusual transient UI contexts. Blender 5.2
        # normally uses the native persistent disclosure panel above.
        section_header(layout, str(title or "Settings"), icon=str(icon or "OPTIONS"))
        return layout.column(align=False)


def _fbp_draw_toggle_foldout(layout, panel_id, owner, prop_name, title, *, default_closed=True):
    """Return the body of a modifier-style foldout: arrow, checkbox, name.

    The checkbox in the header drives ``prop_name``; the body stays drawable
    while off but is greyed out, like Blender's own optional subpanels.
    """
    enabled = bool(getattr(owner, prop_name, False)) if owner is not None else False
    try:
        header, body = layout.panel(str(panel_id), default_closed=bool(default_closed))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        header, body = layout.row(align=True), layout.column(align=False)
    if owner is not None and hasattr(owner, prop_name):
        header.prop(owner, prop_name, text="")
    header.label(text=str(title or "Settings"))
    if body is not None:
        body.active = enabled
    return body


def _fbp_draw_mesh_wiggle_animate(layout, rig):
    """Animate section for Mesh Wiggle, built from its own timing controls."""
    try:
        header, body = layout.panel("fbp_effect_animation", default_closed=False)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        header, body = layout.row(align=True), layout.column(align=False)
    header.label(text="Animate")
    if body is None:
        return
    seed_row = body.row(align=True)
    seed_row.prop(rig, "fbp_mesh_wiggle_seed", text="Seed")
    seed_row.prop(rig, "fbp_mesh_wiggle_hold", text="Stepped")
    speed_row = body.row(align=False)
    speed_split = speed_row.split(factor=0.5, align=False)
    speed_split.prop(rig, "fbp_mesh_wiggle_speed", text="Speed")
    speed_split.prop(rig, "fbp_mesh_wiggle_unique_seed", text="Unique per Layer")


def _fbp_draw_icon_toggle(layout, rig, prop_name, *, icon_on, icon_off=None):
    if not hasattr(rig, prop_name):
        return False
    enabled = bool(getattr(rig, prop_name, False))
    layout.prop(
        rig, prop_name, text="", icon=(icon_on if enabled else (icon_off or icon_on)),
        icon_only=True, toggle=True,
    )
    return True


def _fbp_draw_effect_image_slot(
    layout, rig, effect_id, property_name, *, use_property="", invert_property="",
):
    """Draw datablock selection plus native file-browser and clear buttons."""
    row = layout.row(align=True)
    if use_property:
        _fbp_draw_icon_toggle(
            row, rig, use_property, icon_on="CHECKBOX_HLT", icon_off="CHECKBOX_DEHLT",
        )
    row.prop(rig, property_name, text="")
    load = row.operator("fbp.load_effect_image", text="", icon="FILE_FOLDER")
    load.rig_name = str(getattr(rig, "name", "") or "")
    load.rig_key = fbp_obj_runtime_token(rig)
    load.effect_id = str(effect_id or "")
    load.property_name = str(property_name or "")
    if getattr(rig, property_name, None) is not None:
        clear = row.operator("fbp.clear_effect_image", text="", icon="X")
        clear.rig_name = str(getattr(rig, "name", "") or "")
        clear.rig_key = fbp_obj_runtime_token(rig)
        clear.effect_id = str(effect_id or "")
        clear.property_name = str(property_name or "")
    if invert_property:
        _fbp_draw_icon_toggle(
            row, rig, invert_property, icon_on="ARROW_LEFTRIGHT", icon_off="ARROW_LEFTRIGHT",
        )
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
    show_title=True,
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
    if show_title:
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

def _fbp_draw_edge_box(layout, rig, prefix):
    """Draw crop/extend edge values as spatial controls: top, left/right, bottom."""
    names = {
        "top": f"{prefix}_top",
        "left": f"{prefix}_left",
        "right": f"{prefix}_right",
        "bottom": f"{prefix}_bottom",
    }
    if not all(hasattr(rig, name) for name in names.values()):
        return False
    row = layout.row(align=True)
    row.prop(rig, names["top"], text="Top")
    row = layout.row(align=True)
    row.prop(rig, names["left"], text="Left")
    row.prop(rig, names["right"], text="Right")
    row = layout.row(align=True)
    row.prop(rig, names["bottom"], text="Bottom")
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
            icon="BLANK1",
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
        icon=ui_icon("action.rename"),
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
                    handle = _fbp_modifier_input_handle(modifier, identifier)
                    if handle is not None and hasattr(handle, "value"):
                        controls.prop(
                            handle,
                            "value",
                            text=_fbp_clean_effect_ui_label(
                                name, effect_id=effect_id, fallback="Input"
                            ),
                            icon=_fbp_effect_property_icon(name, name),
                        )
                        drawn += 1
                    elif _fbp_modifier_input_has(modifier, identifier):
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
        controls.label(text="No editable value sockets exposed", icon="BLANK1")
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


def _fbp_effect_node_target_key(datablock):
    try:
        return int(datablock.as_pointer())
    except FBP_DATA_ERRORS:
        return id(datablock)


def fbp_effect_node_targets(rig, effect_id):
    """Return the real editable Geometry/Shader trees owned by one effect.

    Discovery is intentionally operator-driven rather than part of normal UI
    drawing. Geometry effects with generated materials may require a global
    material lookup, which should never become a sidebar-redraw cost.
    """
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = fbp_effect_definition(effect_id)
    plane = _fbp_plane(rig)
    if not plane or definition.get("kind") not in {"GEOMETRY", "SHADER"}:
        return ()
    result = []
    seen = set()

    if definition.get("kind") == "GEOMETRY":
        modifier = fbp_find_effect_modifier(rig, effect_id)
        node_group = getattr(modifier, "node_group", None) if modifier else None
        if node_group is not None:
            key = ("GEOMETRY", _fbp_effect_node_target_key(node_group))
            seen.add(key)
            result.append({
                "kind": "GEOMETRY",
                "label": "Geometry Nodes",
                "tree": node_group,
                "modifier": modifier,
                "material": None,
            })

        if bool(definition.get("owned_material", False)):
            owner = str(getattr(plane, "name", "") or "")
            materials = []
            for material in tuple(getattr(bpy.data, "materials", ()) or ()):
                try:
                    if (
                        str(material.get("fbp_effect_material_owner", "") or "") == owner
                        and fbp_normalize_effect_id(
                            material.get("fbp_effect_material_id", "")
                        ) == effect_id
                        and getattr(material, "node_tree", None) is not None
                    ):
                        materials.append(material)
                except FBP_DATA_ERRORS:
                    continue
            materials.sort(
                key=lambda material: str(
                    material.get("fbp_effect_material_role", "")
                    or getattr(material, "name", "")
                ).casefold()
            )
            for material in materials:
                tree = getattr(material, "node_tree", None)
                key = ("MATERIAL", _fbp_effect_node_target_key(tree))
                if tree is None or key in seen:
                    continue
                seen.add(key)
                role = str(
                    material.get("fbp_effect_material_role", "")
                    or getattr(material, "name", "Material")
                )
                result.append({
                    "kind": "MATERIAL",
                    "label": f"Shader Nodes · {role}",
                    "tree": tree,
                    "modifier": modifier,
                    "material": material,
                })
        return tuple(result)

    for material in _fbp_plane_materials(rig):
        for node in _fbp_shader_effect_nodes(material, effect_id=effect_id):
            node_group = getattr(node, "node_tree", None)
            if node_group is None:
                continue
            key = ("SHADER", _fbp_effect_node_target_key(node_group))
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "kind": "SHADER",
                "label": f"Shader Nodes · {getattr(material, 'name', 'Material')}",
                "tree": node_group,
                "modifier": None,
                "material": material,
            })
    return tuple(result)


def _fbp_tag_user_editable_effect_group(node_group, rig, effect_id, *, owner=""):
    if node_group is None:
        return False
    effect_id = fbp_normalize_effect_id(effect_id)
    rig_name = str(getattr(rig, "name_full", getattr(rig, "name", "")) or "")
    try:
        node_group["fbp_private_effect_group"] = True
        node_group["fbp_user_editable_effect_group"] = True
        node_group["fbp_user_editable_owner"] = rig_name
        node_group["fbp_effect_id"] = effect_id
        node_group["fbp_effect_asset_id"] = str(
            fbp_effect_definition(effect_id).get("asset_id", "") or ""
        )
        node_group["fbp_effect_schema_version"] = FBP_EFFECT_SCHEMA_VERSION
        if owner:
            node_group["fbp_effect_owner"] = str(owner)
        return True
    except FBP_DATA_ERRORS:
        return False


def _fbp_prepare_effect_node_target(rig, effect_id, target):
    """Make shared generated groups layer-private before exposing them."""
    kind = str((target or {}).get("kind", "") or "")
    node_group = (target or {}).get("tree")
    if node_group is None or kind == "MATERIAL":
        return target
    plane = _fbp_plane(rig)
    owner = str(getattr(plane, "name", "") or "")
    try:
        already_private = bool(node_group.get("fbp_private_effect_group", False))
    except FBP_DATA_ERRORS:
        already_private = False

    if kind == "GEOMETRY":
        modifier = (target or {}).get("modifier")
        if modifier is None:
            return target
        editable = node_group
        if not already_private:
            try:
                editable = node_group.copy()
                editable.name = f"{node_group.name} · {owner} · Editable"
                editable.use_fake_user = False
                modifier.node_group = editable
            except FBP_DATA_ERRORS:
                return target
        _fbp_tag_user_editable_effect_group(
            editable, rig, effect_id, owner=owner
        )
        updated = dict(target)
        updated["tree"] = editable
        return updated

    # Shader effects that already own a private group can be edited in place.
    # Shared canonical groups receive one copy, assigned only to nodes on this
    # layer. Image-aware per-material copies remain separate targets.
    editable = node_group
    if not already_private:
        try:
            editable = node_group.copy()
            editable.name = f"{node_group.name} · {getattr(rig, 'name', 'Layer')} · Editable"
            editable.use_fake_user = False
            for material in _fbp_plane_materials(rig):
                for node in _fbp_shader_effect_nodes(material, effect_id=effect_id):
                    if getattr(node, "node_tree", None) is node_group:
                        node.node_tree = editable
        except FBP_DATA_ERRORS:
            return target
    _fbp_tag_user_editable_effect_group(editable, rig, effect_id)
    updated = dict(target)
    updated["tree"] = editable
    return updated


def _fbp_select_effect_plane(context, rig):
    plane = _fbp_plane(rig)
    if plane is None:
        return None
    try:
        if getattr(context, "mode", "OBJECT") != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except FBP_DATA_ERRORS:
        pass
    try:
        for obj in tuple(getattr(context, "selected_objects", ()) or ()):
            if obj is not plane:
                obj.select_set(False)
        plane.hide_set(False)
        plane.select_set(True)
        context.view_layer.objects.active = plane
    except FBP_DATA_ERRORS:
        return None
    return plane



def _fbp_open_effect_node_target(context, rig, target):
    plane = _fbp_select_effect_plane(context, rig)
    tree = (target or {}).get("tree")
    if plane is None or tree is None:
        return False
    area = resolve_node_editor_area(context)
    if area is None:
        return False
    kind = str((target or {}).get("kind", "") or "")
    tree_type = "GeometryNodeTree" if kind == "GEOMETRY" else "ShaderNodeTree"
    try:
        area.ui_type = tree_type
    except FBP_DATA_ERRORS:
        pass
    try:
        space = area.spaces.active
        space.tree_type = tree_type
        if tree_type == "ShaderNodeTree":
            space.shader_type = "OBJECT"
        space.pin = True
        space.node_tree = tree
        try:
            space.selected_node_group = tree
        except FBP_DATA_ERRORS:
            pass
    except FBP_DATA_ERRORS:
        return False
    modifier = (target or {}).get("modifier")
    if kind == "GEOMETRY" and modifier is not None:
        try:
            plane.modifiers.active = modifier
        except FBP_DATA_ERRORS:
            pass
    try:
        region = next(
            region for region in area.regions
            if getattr(region, "type", "") == "WINDOW"
        )
        with context.temp_override(
            area=area, region=region, active_object=plane, object=plane
        ):
            bpy.ops.node.view_all()
    except (StopIteration, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        area.tag_redraw()
    except FBP_DATA_ERRORS:
        pass
    return True


class FBP_OT_OpenEffectNodes(Operator):
    bl_idname = "fbp.open_effect_nodes"
    bl_label = "Open Effect Nodes"
    bl_description = "Select the generated plane and open this effect's real Geometry or Shader node tree for per-layer customization"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(
        description="Stable Frame By Plane effect identifier",
        default="",
        options={"SKIP_SAVE"},
    )
    target_index: IntProperty(
        description="Node target selected from effects that own multiple trees",
        default=-1,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def _rig_and_targets(self, context):
        rigs = _fbp_selected_rigs(context)
        rig = rigs[0] if rigs else None
        return rig, fbp_effect_node_targets(rig, self.effect_id) if rig else ()

    def invoke(self, context, _event):
        rig, targets = self._rig_and_targets(context)
        if rig is None or not targets:
            self.report({"WARNING"}, "This effect has no editable node tree")
            return {"CANCELLED"}
        if self.target_index >= 0 or len(targets) == 1:
            if self.target_index < 0:
                self.target_index = 0
            return self.execute(context)
        return context.window_manager.invoke_popup(self, width=360)

    def draw(self, context):
        rig, targets = self._rig_and_targets(context)
        layout = self.layout
        layout.label(text="Choose a node tree", icon="NODETREE")
        if rig is None:
            return
        for index, target in enumerate(targets):
            icon = "NODETREE" if target.get("kind") == "GEOMETRY" else "MATERIAL"
            op = layout.operator(
                "fbp.open_effect_nodes",
                text=str(target.get("label", "Nodes") or "Nodes"),
                icon=icon,
            )
            op.effect_id = self.effect_id
            op.target_index = index

    def execute(self, context):
        rig, targets = self._rig_and_targets(context)
        index = int(self.target_index)
        if rig is None or not targets or index < 0 or index >= len(targets):
            self.report({"WARNING"}, "Requested node tree is unavailable")
            return {"CANCELLED"}
        target = _fbp_prepare_effect_node_target(
            rig, self.effect_id, targets[index]
        )
        if not _fbp_open_effect_node_target(context, rig, target):
            self.report({"WARNING"}, "Could not open a Node Editor in this workspace")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Opened {target.get('label', 'effect nodes')}")
        return {"FINISHED"}


_FBP_GRADIENT_LIGHT_DRIVER_VARIABLE = "fbp_pos"


def _fbp_gradient_light_plane_bounds(rig):
    plane = _fbp_plane(rig)
    try:
        vertices = tuple(getattr(getattr(plane, "data", None), "vertices", ()) or ())
        xs = [float(vertex.co.x) for vertex in vertices]
        ys = [float(vertex.co.y) for vertex in vertices]
        if xs and ys:
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            return (
                min_x, max(max_x - min_x, 1.0e-8),
                min_y, max(max_y - min_y, 1.0e-8),
            )
    except FBP_DATA_ERRORS:
        pass
    return (-0.5, 1.0, -0.5, 1.0)


def _fbp_find_driver(owner, data_path, index=-1):
    try:
        drivers = getattr(getattr(owner, "animation_data", None), "drivers", ()) or ()
        return next(
            (
                curve for curve in drivers
                if str(getattr(curve, "data_path", "") or "") == str(data_path)
                and int(getattr(curve, "array_index", -1)) == int(index)
            ),
            None,
        )
    except FBP_DATA_ERRORS:
        return None


def _fbp_remove_gradient_light_driver(owner, data_path, index=-1):
    curve = _fbp_find_driver(owner, data_path, index)
    if curve is None:
        return False
    try:
        variables = tuple(getattr(getattr(curve, "driver", None), "variables", ()) or ())
        if not any(
            str(getattr(variable, "name", "") or "")
            == _FBP_GRADIENT_LIGHT_DRIVER_VARIABLE
            for variable in variables
        ):
            return False
        if index < 0:
            owner.driver_remove(data_path)
        else:
            owner.driver_remove(data_path, index)
        return True
    except FBP_DATA_ERRORS:
        return False


def _fbp_add_gradient_light_driver(
    owner, data_path, controller, axis, expression, *, index=-1
):
    existing = _fbp_find_driver(owner, data_path, index)
    if existing is not None:
        variables = tuple(getattr(existing.driver, "variables", ()) or ())
        if not any(
            str(getattr(variable, "name", "") or "")
            == _FBP_GRADIENT_LIGHT_DRIVER_VARIABLE
            for variable in variables
        ):
            return False
        _fbp_remove_gradient_light_driver(owner, data_path, index)
    try:
        curve = (
            owner.driver_add(data_path)
            if index < 0 else owner.driver_add(data_path, index)
        )
        driver = curve.driver
        driver.type = "SCRIPTED"
        driver.expression = str(expression)
        while driver.variables:
            driver.variables.remove(driver.variables[0])
        variable = driver.variables.new()
        variable.name = _FBP_GRADIENT_LIGHT_DRIVER_VARIABLE
        variable.type = "TRANSFORMS"
        target = variable.targets[0]
        target.id = controller
        target.transform_type = "LOC_X" if int(axis) == 0 else "LOC_Y"
        target.transform_space = "TRANSFORM_SPACE"
        return True
    except FBP_DATA_ERRORS:
        return False


def fbp_bind_gradient_light_controller(rig, controller=None):
    """Bind Gradient Light center sockets to one native, keyframeable Empty."""
    if rig is None:
        return False
    controller = controller or getattr(rig, "fbp_gradient_light_controller", None)
    min_x, width, min_y, height = _fbp_gradient_light_plane_bounds(rig)
    expressions = (
        f"(fbp_pos - ({min_x:.12g})) / {width:.12g}",
        f"(fbp_pos - ({min_y:.12g})) / {height:.12g}",
    )
    changed = False

    for axis, property_name in enumerate((
        "fbp_gradient_light_center_x", "fbp_gradient_light_center_y",
    )):
        changed = _fbp_remove_gradient_light_driver(
            rig, property_name
        ) or changed
        if controller is not None:
            changed = _fbp_add_gradient_light_driver(
                rig, property_name, controller, axis, expressions[axis]
            ) or changed

    for material in _fbp_plane_materials(rig):
        tree = getattr(material, "node_tree", None)
        if tree is None:
            continue
        for node in _fbp_shader_effect_nodes(
            material, effect_id=FBP_EFFECT_GRADIENT_LIGHT
        ):
            for axis, socket_name in enumerate(("Center X", "Center Y")):
                socket = _fbp_node_socket(getattr(node, "inputs", ()), socket_name)
                if socket is None:
                    continue
                try:
                    data_path = socket.path_from_id("default_value")
                except FBP_DATA_ERRORS:
                    continue
                changed = _fbp_remove_gradient_light_driver(
                    tree, data_path
                ) or changed
                if controller is not None:
                    changed = _fbp_add_gradient_light_driver(
                        tree, data_path, controller, axis, expressions[axis]
                    ) or changed
                else:
                    try:
                        socket.default_value = float(getattr(rig, (
                            "fbp_gradient_light_center_x",
                            "fbp_gradient_light_center_y",
                        )[axis]))
                    except FBP_DATA_ERRORS:
                        pass
    return changed


class FBP_OT_GradientLightController(Operator):
    bl_idname = "fbp.gradient_light_controller"
    bl_label = "Gradient Light Controller"
    bl_description = f"Link another selected Empty, or create one, to animate Gradient Light position; {alt_modifier_name()}-click unlinks it"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(
            fbp_effect_is_active(rig, FBP_EFFECT_GRADIENT_LIGHT)
            for rig in _fbp_selected_rigs(context)
        )

    def invoke(self, context, event):
        rigs = _fbp_selected_rigs(context)
        rig = rigs[0] if rigs else None
        controller = (
            getattr(rig, "fbp_gradient_light_controller", None)
            if rig is not None else None
        )
        if bool(getattr(event, "alt", False)) and controller is not None:
            # Preserve the evaluated position as the new static center.
            min_x, width, min_y, height = _fbp_gradient_light_plane_bounds(rig)
            try:
                values = (
                    (float(controller.location.x) - min_x) / width,
                    (float(controller.location.y) - min_y) / height,
                )
            except FBP_DATA_ERRORS:
                values = (
                    float(getattr(rig, "fbp_gradient_light_center_x", 0.5)),
                    float(getattr(rig, "fbp_gradient_light_center_y", 0.5)),
                )
            rig.fbp_gradient_light_controller = None
            fbp_bind_gradient_light_controller(rig, None)
            fbp_set_rna_property_silent(
                rig, "fbp_gradient_light_center_x", values[0]
            )
            fbp_set_rna_property_silent(
                rig, "fbp_gradient_light_center_y", values[1]
            )
            fbp_update_shader_effect(rig, FBP_EFFECT_GRADIENT_LIGHT)
            self.report({"INFO"}, "Gradient Light controller unlinked")
            return {"FINISHED"}
        return self.execute(context)

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        rig = rigs[0] if rigs else None
        plane = _fbp_plane(rig) if rig is not None else None
        if rig is None or plane is None or not fbp_effect_is_active(
            rig, FBP_EFFECT_GRADIENT_LIGHT
        ):
            self.report({"WARNING"}, "Select a layer with Gradient Light")
            return {"CANCELLED"}

        controller = getattr(rig, "fbp_gradient_light_controller", None)
        if controller is not None:
            fbp_bind_gradient_light_controller(rig, controller)
            for obj in tuple(getattr(context, "selected_objects", ()) or ()):
                obj.select_set(False)
            controller.hide_set(False)
            controller.hide_viewport = False
            controller.select_set(True)
            context.view_layer.objects.active = controller
            self.report({"INFO"}, "Gradient Light controller selected; keyframe Location")
            return {"FINISHED"}

        controller = next(
            (
                obj for obj in tuple(getattr(context, "selected_objects", ()) or ())
                if obj is not rig and obj is not plane
                and getattr(obj, "type", "") == "EMPTY"
            ),
            None,
        )
        created = controller is None
        if created:
            controller = bpy.data.objects.new(
                f"{rig.name} · Gradient Light", None
            )
            collection = next(
                iter(tuple(getattr(plane, "users_collection", ()) or ())),
                context.scene.collection,
            )
            collection.objects.link(controller)
            min_x, width, min_y, height = _fbp_gradient_light_plane_bounds(rig)
            controller.parent = plane
            controller.matrix_parent_inverse = Matrix.Identity(4)
            controller.location = (
                min_x + float(getattr(rig, "fbp_gradient_light_center_x", 0.5)) * width,
                min_y + float(getattr(rig, "fbp_gradient_light_center_y", 0.5)) * height,
                0.008,
            )
            controller.empty_display_type = "SPHERE"
            controller.empty_display_size = max(0.035, min(width, height) * 0.075)
        elif getattr(controller, "parent", None) is not plane:
            world_matrix = controller.matrix_world.copy()
            controller.parent = plane
            controller.matrix_parent_inverse = Matrix.Identity(4)
            controller.matrix_world = world_matrix

        controller.show_in_front = True
        controller.hide_render = True
        controller["fbp_gradient_controller"] = True
        controller["fbp_gradient_controller_kind"] = "GRADIENT_LIGHT"
        controller["fbp_gradient_controller_owner"] = str(rig.name)
        rig.fbp_gradient_light_controller = controller
        fbp_bind_gradient_light_controller(rig, controller)

        for obj in tuple(getattr(context, "selected_objects", ()) or ()):
            obj.select_set(False)
        controller.select_set(True)
        context.view_layer.objects.active = controller
        self.report(
            {"INFO"},
            "Created Gradient Light controller" if created
            else "Linked selected Empty to Gradient Light",
        )
        return {"FINISHED"}


def fbp_draw_effect_settings(
    layout, rig, effect_id, selected_count=1, present_count=None, context=None,
    instance_id="", native=False,
):
    """Draw one effect's Frame By Plane settings.

    ``native`` draws them inside the effect's own Blender modifier panel:
    the effect's name, variant and the settings the modifier already shows
    as inputs are left to the modifier (``layout`` then filters them, see
    ``native_effect_panel``), and the viewport control buttons get labels.
    """
    if context is None:
        try:
            context = getattr(bpy, "context", None)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            context = None
    effect_id = fbp_normalize_effect_id(effect_id)
    instance_id = str(instance_id or "") if _fbp_effect_uses_multi_instances(effect_id) else ""
    definition = fbp_effect_definition(effect_id)
    if not definition:
        return
    try:
        # Image effects and masks keep their values on their modifier: the
        # settings below edit those modifier inputs instead of the layer's.
        from .effect_shells import fbp_shell_layout
        if not native:
            layout = fbp_shell_layout(layout, rig, effect_id, instance_id)
    except ImportError:
        pass
    box = layout.column(align=False) if native else layout.box()
    configure_layout(box)
    header = box.row(align=True)
    header_split = header.split(factor=0.68, align=False)
    header_left = header_split.row(align=True)
    header_left.alignment = 'LEFT'
    settings_label = _fbp_effect_display_label(effect_id, definition)
    settings_icon = str(definition.get("icon", "MODIFIER"))
    settings_icon_value = effect_custom_icon_value(effect_id)
    gp_mask_header_canvas = None
    if effect_id in GP_MASK_EFFECT_IDS:
        try:
            from .grease_pencil_bridge import gp_mask_slot_contract, is_gp_mask_canvas
            contract = gp_mask_slot_contract(effect_id)
            gp_canvas = getattr(rig, contract.get("canvas", ""), None)
            gp_source = str(getattr(rig, contract.get("source_type", ""), "") or "").upper()
            if gp_source == "GREASE_PENCIL" or is_gp_mask_canvas(gp_canvas):
                settings_label = "Grease Pencil Mask"
                settings_icon = "OUTLINER_OB_GREASEPENCIL"
                settings_icon_value = effect_custom_icon_value(effect_id) or ui_icon_value("menu.gp_layer")
                gp_mask_header_canvas = gp_canvas
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    family_id = fbp_effect_family_id(effect_id)
    family = fbp_effect_family_definition(family_id) if family_id else {}
    if native:
        # The modifier header already names the effect and its inputs hold
        # the variant: only the buttons on the right are left in this row.
        pass
    elif family and gp_mask_header_canvas is None:
        # Sub-effects: the family name with its variant dropdown right next
        # to it, at the top of the effect panel.
        # The title itself is the dropdown, so it survives narrow sidebars.
        variant_menu = header_left.row(align=True)
        variant_menu.context_string_set(_FBP_VARIANT_CONTEXT_KEY, effect_id)
        variant_menu.menu(
            "FBP_MT_effect_family_variants",
            text=(
                f"{str(family.get('label', 'Effect') or 'Effect')}: "
                f"{fbp_effect_variant_label(effect_id)}"
            ),
            **({"icon_value": settings_icon_value} if settings_icon_value else {"icon": settings_icon}),
        )
    else:
        header_left.label(
            text=settings_label,
            **({"icon_value": settings_icon_value} if settings_icon_value else {"icon": settings_icon}),
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

    performance = str(definition.get("performance", "")).upper()
    if performance in {"HEAVY", "VERY_HEAVY"}:
        # A cost note, not an error: only the heaviest effects are red.
        warning = header_right.row(align=True)
        warning.alert = performance == "VERY_HEAVY"
        op = warning.operator(
            "fbp.effect_header_warning",
            text="",
            icon="ERROR" if performance == "VERY_HEAVY" else "TIME",
            emboss=False,
        )
        op.effect_id = effect_id
        op.message = fbp_effect_performance_hint(effect_id, definition)
    if effect_id in GP_MASK_EFFECT_IDS and gp_mask_header_canvas is not None:
        try:
            from .grease_pencil_bridge import gp_mask_is_being_edited
            # Edit lives in Grease Pencil Settings; Done stays reachable here
            # while the mask strokes are being drawn.
            if gp_mask_is_being_edited(context, gp_mask_header_canvas):
                edit_gp = header_right.operator(
                    "fbp.edit_grease_pencil_mask",
                    text="Done",
                    icon="CHECKMARK",
                    depress=True,
                )
                edit_gp.rig_name = getattr(rig, "name", "")
                edit_gp.canvas_name = getattr(gp_mask_header_canvas, "name", "")
            detach_gp = header_right.operator(
                "fbp.detach_grease_pencil_mask_from_effect",
                text="",
                icon="UNLINKED",
                emboss=False,
            )
            detach_gp.target_effect_id = effect_id
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    if definition.get("kind") in {"GEOMETRY", "SHADER"}:
        nodes = header_right.operator(
            "fbp.open_effect_nodes",
            text="",
            icon="NODETREE",
            emboss=False,
        )
        nodes.effect_id = effect_id
        nodes.target_index = -1

    presets = header_right.operator(
        "fbp.open_effect_presets", text="", icon="PRESET", emboss=False
    )
    presets.effect_id = effect_id
    presets.instance_id = instance_id
    reset = header_right.operator(
        "fbp.reset_active_effect", text="", icon="FILE_REFRESH", emboss=False
    )
    reset.effect_id = effect_id
    reset.instance_id = instance_id

    if family:
        active_family_members = [
            variant_id for variant_id, _label in tuple(family.get("variants", ()) or ())
            if fbp_effect_is_active(rig, variant_id)
        ]
        if len(active_family_members) > 1:
            family_warning = box.row(align=False)
            family_warning.alert = True
            family_warning.label(
                text=f"Multiple variants: {len(active_family_members)} {family.get('label', 'effect')} effects are active",
                icon="ERROR",
            )

    try:
        from .effect_controls import (
            effect_control_driven_properties,
            effect_control_owner,
            effect_has_controls,
            is_effect_control,
        )
        if effect_has_controls(effect_id):
            duplicate_controls = bool(
                _fbp_effect_uses_multi_instances(effect_id)
                and len(_fbp_find_shader_effect_nodes_for_rig(rig, effect_id)) > 1
            )
            if duplicate_controls:
                hint_row(
                    box,
                    "Viewport controls are unavailable for duplicated instances",
                    icon="INFO",
                    disabled=True,
                )
            # A light checkbox row: the gizmo is a helper, not the effect's
            # main setting, so it no longer fills the panel with a blue bar.
            controls_row = box.row(align=False)
            controls_row.enabled = not duplicate_controls
            if native:
                # The Viewport Control checkbox is a modifier input: here the
                # rig gets labelled buttons instead of icons in a corner.
                # Row-only modifiers have no input for the checkbox: it is
                # drawn here and hidden where the modifier already shows it.
                controls_row.prop(rig, "fbp_effect_controls_enabled", text="Viewport Control")
                native_controls = controls_row.row(align=True)
                native_controls.active = bool(getattr(rig, "fbp_effect_controls_enabled", True))
                if effect_id == FBP_EFFECT_GRADIENT_LIGHT:
                    native_controls.operator(
                        "fbp.gradient_light_controller",
                        text="Light Controller",
                        icon="EMPTY_AXIS",
                        depress=getattr(rig, "fbp_gradient_light_controller", None) is not None,
                    )
                select_rig = native_controls.operator(
                    "fbp.select_effect_control", text="Select Rig", icon="RESTRICT_SELECT_OFF",
                )
                select_rig.effect_id = effect_id
                reset_rig = native_controls.operator(
                    "fbp.reset_effect_control", text="Reset Rig", icon=ui_icon("action.reset"),
                )
                reset_rig.effect_id = effect_id
            else:
                controls_split = controls_row.split(factor=0.6, align=False)
                controls_split.prop(
                    rig, "fbp_effect_controls_enabled", text="Viewport Control",
                )
                controls = controls_split.row(align=True)
                controls.alignment = 'RIGHT'
                controls.active = bool(getattr(rig, "fbp_effect_controls_enabled", True))
                if effect_id == FBP_EFFECT_GRADIENT_LIGHT:
                    controls.operator(
                        "fbp.gradient_light_controller",
                        text="",
                        icon="EMPTY_AXIS",
                        depress=getattr(
                            rig, "fbp_gradient_light_controller", None
                        ) is not None,
                    )
                active_control = getattr(context, "active_object", None) if context else None
                control_is_active = bool(
                    is_effect_control(active_control)
                    and effect_control_owner(active_control) is rig
                    and str(active_control.get("fbp_effect_control_effect", "") or "").upper() == effect_id
                    and bool(active_control.select_get())
                )
                select_control = controls.operator(
                    "fbp.select_effect_control",
                    text="",
                    icon="RESTRICT_SELECT_OFF",
                    depress=control_is_active,
                )
                select_control.effect_id = effect_id
                reset_control = controls.operator(
                    "fbp.reset_effect_control", text="", icon=ui_icon("action.reset")
                )
                reset_control.effect_id = effect_id
            if effect_id in {FBP_EFFECT_CROP, FBP_EFFECT_EXTEND}:
                hint_row(
                    box,
                    "Select any side or corner handle, then use G to edit the image bounds.",
                    icon="EMPTY_ARROWS",
                )
            elif (
                effect_id == FBP_EFFECT_GRADIENT_MASK
                and str(getattr(rig, "fbp_gradient_mask_type", "LINEAR") or "LINEAR") == "RADIAL"
            ):
                hint_row(
                    box,
                    "Centre: move and turn the circle · Stops: inner and outer radius.",
                    icon="INFO",
                )
            elif effect_id in {FBP_EFFECT_GRADIENT_MASK, FBP_EFFECT_GRADIENT_LIGHT, FBP_EFFECT_TILT_SHIFT}:
                hint_row(
                    box,
                    "Centre: move, rotate and resize · Stops: edit the ends.",
                    icon="INFO",
                )
            elif bool(getattr(rig, "fbp_effect_controls_enabled", True)):
                driven = tuple(
                    _fbp_effect_property_label(definition, name, None)
                    for name in sorted(effect_control_driven_properties(effect_id))
                    if hasattr(rig, name)
                )
                if driven:
                    hint_row(
                        box,
                        "Viewport control edits " + ", ".join(driven[:3]) + ("…" if len(driven) > 3 else ""),
                        icon="INFO",
                    )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    if definition.get("supports_input_source"):
        current_source = fbp_effect_input_source(rig, effect_id, instance_id)
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
            op.instance_id = instance_id
            op.source = source
    debug_modes = () if effect_id in GP_MASK_EFFECT_IDS else tuple(definition.get("debug_modes", ()))
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
                icon="BLANK1",
            )
    if bool(definition.get("custom", False)):
        _fbp_draw_custom_effect_inputs(box, rig, effect_id)
        if int(selected_count or 1) > 1:
            copy_row = box.row(align=True)
            copy_row.label(text="Socket edits affect the active layer", icon="BLANK1")
            copy = copy_row.operator(
                "fbp.copy_custom_effect_values_to_selected",
                text="Copy Values to Selected",
                icon="PASTEDOWN",
            )
            copy.effect_id = effect_id
        return
    if effect_id == FBP_EFFECT_MOTION:
        try:
            from .motion_runtime import draw_motion_effect_ui
            draw_motion_effect_ui(box, getattr(bpy, "context", None), rig)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not draw Motion effect", exc)
            box.label(text="Motion controls unavailable", icon="ERROR")
        return
    # Registry metadata is the single source of truth for visible parameter
    # names. Keep this table intentionally tiny and only for wording that adds
    # context not represented by the shared effect definition.
    labels = {
        "fbp_infinite_rotation_offset": "Offset (°)",
        "fbp_wind_falloff": "Pinned Falloff",
    }
    if bool(definition.get("color_ramp_role", "")):
        ramp_node = fbp_effect_color_ramp_node(rig, effect_id)
        ramp_box = box.box()
        ramp_box.label(text="Color Ramp", icon="COLOR")
        if ramp_node is not None:
            ramp_box.template_color_ramp(ramp_node, "color_ramp", expand=True)
            if int(selected_count or 0) > 1 and int(present_count or 0) == int(selected_count or 0):
                _geometry_nodes_module()._fbp_schedule_effect_color_ramp_sync(
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
                curve_box.label(text="Curve edits affect the active layer", icon="BLANK1")
        else:
            curve_box.label(text="RGB Curves unavailable — refresh the effect", icon="ERROR")
    if effect_id == FBP_EFFECT_CROP:
        _fbp_draw_effect_section(box, "Crop Edges", "FULLSCREEN_EXIT")
        _fbp_draw_edge_box(box, rig, "fbp_crop")
        crop_actions = box.row(align=True)
        crop_actions.operator("fbp.crop_alpha", text="Crop Alpha", icon="IMAGE_ALPHA")
        crop_actions.operator("fbp.reset_crop", text="Reset", icon=ui_icon("action.reset"))
        hint_row(
            box,
            "Crop trims the visible source without changing the layer transform.",
            icon="INFO",
        )
    elif effect_id == FBP_EFFECT_EXTEND:
        _fbp_draw_effect_section(box, "Extend Mode", "FULLSCREEN_ENTER")
        if hasattr(rig, "fbp_extend_mode"):
            box.prop(rig, "fbp_extend_mode", text="")
        _fbp_draw_effect_section(box, "Extend Edges", "FULLSCREEN_ENTER", separator=True)
        _fbp_draw_edge_box(box, rig, "fbp_extend")
        extend_mode = str(getattr(rig, "fbp_extend_mode", "MIRROR") or "MIRROR")
        extend_hints = {
            "TRANSPARENT": "Transparent adds empty canvas for shadows, glows and offset effects.",
            "REPEAT": "Repeat Texture tiles the source continuously beyond the original borders.",
            "MIRROR": "Repeat Flipped alternates normal and mirrored tiles to reduce visible seams.",
            "EDGE": "Edge Pixel stretches the nearest source-edge pixel into the added geometry.",
        }
        hint_row(box, extend_hints.get(extend_mode, extend_hints["EDGE"]), icon="INFO")
    elif effect_id == FBP_EFFECT_MESH_WIGGLE:
        _fbp_draw_quality_triplet(
            box,
            rig,
            title="Subdivisions",
            icon="MOD_SUBSURF",
            viewport_prop="fbp_mesh_wiggle_subdivisions",
            playback_prop="fbp_mesh_wiggle_playback_subdivisions",
            render_prop="fbp_mesh_wiggle_render_subdivisions",
        )
        _fbp_draw_effect_property(box, rig, definition, "fbp_mesh_wiggle_shade_smooth", labels)

        _fbp_draw_effect_section(box, "Motion", "MOD_NOISE", separator=True)
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            (
                "fbp_mesh_wiggle_strength",
                "fbp_mesh_wiggle_w",
                "fbp_mesh_wiggle_noise_scale",
                "fbp_mesh_wiggle_detail",
            ),
            labels,
        )
        # Mesh Wiggle always moves: its own Speed, Stepped and Seed are the
        # Animate section, drawn last like every other animatable effect.
        _fbp_draw_mesh_wiggle_animate(box, rig)
        detail = int(getattr(rig, "fbp_mesh_wiggle_subdivisions", 0) or 0)
        if detail >= 5:
            warning = box.row(align=False)
            warning.alert = True
            warning.label(text="High subdivisions may slow viewport playback", icon="ERROR")
    elif effect_id == FBP_EFFECT_STOP_MOTION_CRUMPLE:
        _fbp_draw_quality_triplet(
            box,
            rig,
            title="Paper Mesh",
            icon="MOD_SUBSURF",
            viewport_prop="fbp_stop_motion_resolution",
            playback_prop="fbp_stop_motion_playback_resolution",
            render_prop="fbp_stop_motion_render_resolution",
        )
        _fbp_draw_effect_section(box, "Crumple", "IMAGE_PLANE", separator=True)
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            ("fbp_stop_motion_strength", "fbp_stop_motion_step_frames"),
            labels,
        )
        detail = int(getattr(rig, "fbp_stop_motion_resolution", 0) or 0)
        if detail >= 5:
            warning = box.row(align=False)
            warning.alert = True
            warning.label(text="High paper mesh detail may slow viewport playback", icon="ERROR")
    elif effect_id == FBP_EFFECT_GLASS:
        # Shatter is the one slider that matters, so it leads, full width.
        _fbp_draw_effect_property(box, rig, definition, "fbp_glass_shatter", labels)
        shatter = _fbp_draw_native_foldout(
            box, "fbp_glass_motion", "Break", "MOD_EXPLODE",
        )
        if shatter is not None:
            _fbp_draw_compact_effect_properties(
                shatter, rig, definition,
                ("fbp_glass_impact_x", "fbp_glass_impact_y", "fbp_glass_spread", "fbp_glass_gap", "fbp_glass_explode", "fbp_glass_depth", "fbp_glass_fall", "fbp_glass_spin"),
                labels,
            )

        pieces = _fbp_draw_native_foldout(
            box, "fbp_glass_pieces_panel", "Pieces", "MOD_TRIANGULATE",
        )
        if pieces is not None:
            pieces.row(align=True).prop(rig, "fbp_glass_pattern", expand=True)
            _fbp_draw_compact_effect_properties(
                pieces, rig, definition,
                ("fbp_glass_pieces", "fbp_glass_irregularity", "fbp_glass_thickness", "fbp_glass_phase", "fbp_glass_alpha_threshold"),
                labels,
            )

        optics = _fbp_draw_native_foldout(
            box, "fbp_glass_optics", "Glass", "MATERIAL", default_closed=True,
        )
        if optics is not None:
            _fbp_draw_effect_property(optics, rig, definition, "fbp_glass_use_glass", labels)
            column = optics.column(align=False)
            column.active = bool(getattr(rig, "fbp_glass_use_glass", False))
            _fbp_draw_compact_effect_properties(
                column, rig, definition,
                ("fbp_glass_roughness", "fbp_glass_ior", "fbp_glass_source_color", "fbp_glass_tint", "fbp_glass_edge_tint", "fbp_glass_absorption"),
                labels,
            )
            scene = getattr(context, "scene", None) if context is not None else getattr(bpy.context, "scene", None)
            if column.active and str(getattr(getattr(scene, "render", None), "engine", "") or "") != "CYCLES":
                note = optics.row(align=False)
                note.label(text="Eevee transmission preview active · Cycles is more accurate", icon="INFO")
        if int(getattr(rig, "fbp_glass_pieces", 0) or 0) >= 64:
            warning = box.row(align=False)
            warning.alert = True
            warning.label(text="Many pieces may slow playback", icon="ERROR")
    elif effect_id == FBP_EFFECT_CRYSTAL:
        quality = _fbp_draw_native_foldout(
            box, "fbp_crystal_quality", "Quality & Silhouette", "MOD_SUBSURF",
        )
        if quality is not None:
            _fbp_draw_quality_triplet(
                quality, rig, title="Source Remesh", icon="MOD_SUBSURF",
                viewport_prop="fbp_crystal_subdivision",
                playback_prop="fbp_crystal_playback_subdivision",
                render_prop="fbp_crystal_render_subdivision", show_title=False,
            )
            surface = quality.row(align=True)
            surface.label(text="Surface")
            _fbp_draw_icon_toggle(
                surface, rig, "fbp_crystal_shade_smooth",
                icon_on="NORMALS_VERTEX", icon_off="NORMALS_FACE",
            )
            _fbp_draw_compact_effect_properties(
                quality, rig, definition,
                ("fbp_crystal_silhouette_detail", "fbp_crystal_surface_subdivision"),
                labels,
            )

        alpha = _fbp_draw_native_foldout(
            box, "fbp_crystal_alpha", "Attached Alpha Depth", "MOD_DISPLACE",
        )
        if alpha is not None:
            _fbp_draw_compact_effect_properties(
                alpha, rig, definition,
                ("fbp_crystal_depth", "fbp_crystal_thickness", "fbp_crystal_roundness", "fbp_crystal_edge_pinning", "fbp_crystal_blur_iterations", "fbp_crystal_alpha_threshold"),
                labels,
            )

        influence = _fbp_draw_native_foldout(
            box, "fbp_crystal_influence", "Influence Map", "IMAGE_DATA",
        )
        if influence is not None:
            _fbp_draw_effect_image_slot(
                influence, rig, FBP_EFFECT_CRYSTAL, "fbp_crystal_influence_image",
                use_property="fbp_crystal_use_influence_map",
                invert_property="fbp_crystal_invert_influence",
            )
            _fbp_draw_effect_property(
                influence, rig, definition, "fbp_crystal_influence_strength", labels,
            )

        procedural = _fbp_draw_native_foldout(
            box, "fbp_crystal_procedural", "Procedural Surface", "NODE_TEXTURE",
            default_closed=True,
        )
        if procedural is not None:
            options = procedural.row(align=True)
            options.label(text="Mapping")
            _fbp_draw_icon_toggle(
                options, rig, "fbp_crystal_correct_aspect",
                icon_on="FULLSCREEN_ENTER", icon_off="FULLSCREEN_EXIT",
            )
            generator = str(getattr(rig, "fbp_crystal_texture_type", "VORONOI") or "VORONOI")
            generator_properties = ["fbp_crystal_texture_type"]
            if generator == "VORONOI":
                generator_properties.append("fbp_crystal_pattern_mode")
            generator_properties.extend((
                "fbp_crystal_pattern_scale", "fbp_crystal_texture_scale_x",
                "fbp_crystal_texture_scale_y", "fbp_crystal_pattern_detail",
                "fbp_crystal_pattern_strength",
            ))
            if generator == "VORONOI":
                generator_properties.extend((
                    "fbp_crystal_cell_randomness", "fbp_crystal_cell_seed",
                ))
            generator_properties.append("fbp_crystal_phase")
            _fbp_draw_compact_effect_properties(
                procedural, rig, definition, tuple(generator_properties), labels,
            )

        optics = _fbp_draw_native_foldout(
            box, "fbp_crystal_optics", "Optics", "MATERIAL", default_closed=True,
        )
        if optics is not None:
            wall = optics.row(align=True)
            wall.label(text="Surface Model")
            _fbp_draw_icon_toggle(
                wall, rig, "fbp_crystal_thin_wall",
                icon_on="MOD_SOLIDIFY", icon_off="MESH_PLANE",
            )
            _fbp_draw_compact_effect_properties(
                optics, rig, definition,
                ("fbp_crystal_distortion", "fbp_crystal_roughness", "fbp_crystal_ior", "fbp_crystal_source_color", "fbp_crystal_tint", "fbp_crystal_absorption"),
                labels,
            )
        if float(getattr(rig, "fbp_crystal_thickness", 0.0) or 0.0) <= 1.0e-6:
            note = box.row(align=False)
            note.label(text="Single refractive surface · volume absorption disabled", icon="CHECKMARK")
        else:
            note = box.row(align=False)
            note.label(text="Closed crystal volume · heavier than the single-surface mode", icon="INFO")
        scene = getattr(context, "scene", None) if context is not None else getattr(bpy.context, "scene", None)
        if str(getattr(getattr(scene, "render", None), "engine", "") or "") != "CYCLES":
            note = box.row(align=False)
            note.label(text="Crystal is designed for Cycles · Eevee only approximates transmission", icon="INFO")
        if bool(getattr(rig, "fbp_crystal_use_influence_map", False)) and getattr(rig, "fbp_crystal_influence_image", None) is None:
            warning = box.row(align=False)
            warning.alert = True
            warning.label(text="Choose a grayscale Crystal influence map", icon="IMAGE_DATA")
        if int(getattr(rig, "fbp_crystal_subdivision", 0) or 0) >= 7 or int(getattr(rig, "fbp_crystal_silhouette_detail", 0) or 0) >= 4 or int(getattr(rig, "fbp_crystal_surface_subdivision", 0) or 0) >= 2:
            warning = box.row(align=False)
            warning.alert = True
            warning.label(text="Maximum Crystal remesh, boost or clay smoothing is render-heavy", icon="ERROR")
    elif effect_id == FBP_EFFECT_SHADOW:
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
            extend_mode = str(getattr(rig, "fbp_extend_mode", "MIRROR") or "MIRROR")
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
                    icon="BLANK1",
                )
    elif effect_id == FBP_EFFECT_LATTICE:
        from .lattice_bones import bones_object, deform_bones
        from .lattice_corner_pin import corner_handles
        from .lattice_pins import KIND_BEND, KIND_POINT, pin_kind, puppet_pins, rig_pins
        try:
            rig_type = str(getattr(rig, "fbp_lattice_rig_type", "GRID") or "GRID")
        except FBP_DATA_ERRORS:
            rig_type = "GRID"
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
        cage_editing = bool(
            helper is not None and active_object is helper
            and str(getattr(ui_context, "mode", "") or "").startswith("EDIT")
        )
        camera = _fbp_lattice_scene_camera(getattr(bpy.context, "scene", None))
        camera_valid = bool(
            camera is not None
            and str(getattr(getattr(camera, "data", None), "type", "") or "") in {"PERSP", "ORTHO"}
        )
        armature = bones_object(rig)
        bone_count = len(deform_bones(armature)) if armature is not None else 0
        corners = corner_handles(rig)
        pins = puppet_pins(rig)
        point_handles = rig_pins(rig, kinds=(KIND_POINT,))
        active_bone = getattr(ui_context, "active_pose_bone", None) if ui_context is not None else None

        def _ops_row(target, operator_id, actions, *, enabled=True, scale=1.0):
            """One aligned row of action buttons; empty labels draw icons only."""
            row = target.row(align=True)
            row.enabled = enabled
            row.scale_y = scale
            for action, label, icon in actions:
                operator = row.operator(operator_id, text=label, icon=icon)
                operator.rig_name = rig_name
                operator.action = action
            return row

        def _hint(target, text):
            row = target.row(align=False)
            row.enabled = False
            row.label(text=text, icon="INFO")

        def _section(target, identifier, title, icon, *, closed=True):
            """A collapsible sub-panel (Blender layout panels), or a plain box."""
            try:
                header, body = target.panel(f"FBP_lattice_{identifier}", default_closed=closed)
                header.label(text=title, icon=icon)
                return body
            except (AttributeError, TypeError):
                body = target.box()
                body.label(text=title, icon=icon)
                return body

        # Type picker and the cage visibility on one line.
        top = box.row(align=True)
        top.scale_y = 1.2
        top.prop(rig, "fbp_lattice_rig_type", text="")
        top.prop(
            rig, "fbp_lattice_show_cage", text="", toggle=True,
            icon="HIDE_OFF" if bool(getattr(rig, "fbp_lattice_show_cage", True)) else "HIDE_ON",
        )
        select_cage = top.operator("fbp.select_lattice_helper", text="", icon="RESTRICT_SELECT_OFF")
        select_cage.rig_name = rig_name

        stacked = []
        if lattice_mode == "CAMERA_FLATTEN" and rig_type != "CAMERA":
            stacked.append(("Camera", "CAMERA_DATA"))
        if (lattice_mode == "CORNER_PIN" or corners) and rig_type != "CORNER_PIN":
            stacked.append(("Corner Pin", "VIEW_PERSPECTIVE"))
        if bone_count and rig_type != "BONES":
            stacked.append((f"{bone_count} Bones", "BONE_DATA"))
        if pins and rig_type != "PINS":
            stacked.append((f"{len(pins)} Pins", "PINNED"))
        if point_handles and rig_type != "GRID":
            stacked.append(("Points", "MESH_GRID"))
        if stacked:
            stack_row = box.row(align=True)
            stack_row.enabled = False
            stack_row.label(text="Also:")
            for label, icon in stacked:
                stack_row.label(text=label, icon=icon)

        if not lattice_ready:
            status_row = box.row(align=False)
            status_row.alert = not repairing
            status_row.label(
                text="Repairing cage…" if repairing else "Cage missing: use Reset in the effect header",
                icon="FILE_REFRESH" if repairing else "ERROR",
            )
            last_error = _fbp_last_lattice_error(rig)
            if last_error and not repairing:
                error_row = box.row(align=False)
                error_row.alert = True
                error_row.label(text=last_error if len(last_error) <= 110 else last_error[:109].rstrip() + "…", icon="BLANK1")
        baked = bool(helper and helper.get(_FBP_LATTICE_BAKED_KEY, False))
        if baked and lattice_mode != "CAMERA_FLATTEN":
            box.label(text="Perspective baked into the cage", icon="CHECKMARK")

        def _draw_grid_settings(target, *, title="Cage & Mesh"):
            body = _section(target, "cage_settings", title, "MOD_LATTICE")
            if body is None:
                return
            _fbp_draw_effect_property(body, rig, definition, "fbp_lattice_grid_preset", labels)
            try:
                grid_preset = str(getattr(rig, "fbp_lattice_grid_preset", "LOOPS_2") or "LOOPS_2").upper()
            except FBP_DATA_ERRORS:
                grid_preset = "LOOPS_2"
            if grid_preset == "CUSTOM":
                custom = body.row(align=True)
                custom.prop(rig, "fbp_lattice_custom_loops_u", text="X")
                linked = bool(getattr(rig, "fbp_lattice_link_loops", True))
                custom.prop(rig, "fbp_lattice_link_loops", text="", icon="LINKED" if linked else "UNLINKED", toggle=True)
                custom.prop(rig, "fbp_lattice_custom_loops_v", text="Y")
            if helper is not None:
                size_row = body.row(align=False)
                size_row.enabled = False
                size_row.label(text=f"{int(helper.data.points_u)} × {int(helper.data.points_v)} points", icon="MESH_GRID")
            _fbp_draw_effect_property(body, rig, definition, "fbp_lattice_interpolation", labels)
            if armature is not None:
                body.prop(rig, "fbp_lattice_handle_size", slider=True)
            _fbp_draw_effect_property(body, rig, definition, "fbp_lattice_mesh_detail_mode", labels)
            if _fbp_lattice_mesh_detail_mode(rig) == "AUTO":
                _fbp_draw_effect_property(body, rig, definition, "fbp_lattice_mesh_density", labels)
            else:
                _fbp_draw_effect_property(body, rig, definition, "fbp_lattice_mesh_subdivisions", labels)

        def _draw_poses(target):
            from .lattice_poses import PRESETS, lattice_poses
            poses = lattice_poses(helper) if helper is not None else ()
            body = _section(target, "poses", f"Poses · {len(poses)}" if poses else "Poses", "SHAPEKEY_DATA", closed=not poses)
            if body is None:
                return
            sliders = body.column(align=True)
            sliders.enabled = lattice_ready
            for pose in poses:
                row = sliders.row(align=True)
                # A plain slider: hover and press I to keyframe the deformation.
                row.prop(pose, "value", text=pose.name, slider=True)
                edit_pose = row.operator("fbp.edit_lattice_pose", text="", icon="EDITMODE_HLT")
                edit_pose.rig_name = rig_name
                edit_pose.pose_name = pose.name
                remove_pose = row.operator("fbp.remove_lattice_pose", text="", icon="X")
                remove_pose.rig_name = rig_name
                remove_pose.pose_name = pose.name
            add_grid = body.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
            add_grid.enabled = lattice_ready
            for preset_id, (label, icon, _description, _function, _minimum) in PRESETS.items():
                add = add_grid.operator("fbp.add_lattice_pose", text=label, icon=icon)
                add.rig_name = rig_name
                add.preset = preset_id
            custom = add_grid.operator("fbp.add_lattice_pose", text="Custom", icon="EDITMODE_HLT")
            custom.rig_name = rig_name
            custom.preset = ""

        def _draw_grid(target):
            row = target.row(align=True)
            row.enabled = lattice_ready
            row.scale_y = 1.2
            if cage_editing:
                done = row.operator("fbp.finish_lattice_editing", text="Back to Plane", icon="CHECKMARK")
            else:
                done = row.operator("fbp.edit_lattice_helper", text="Edit Cage", icon="EDITMODE_HLT")
            done.rig_name = rig_name
            if not point_handles:
                add = row.operator("fbp.lattice_point_handles", text="Point Handles", icon="MESH_GRID")
                add.rig_name = rig_name
                add.action = 'ADD'
            else:
                handles_row = target.row(align=True)
                handles_row.label(text=f"{len(point_handles)} point handles", icon="MESH_GRID")
                _ops_row(handles_row, "fbp.lattice_point_handles", (
                    ("SELECT", "", "POSE_HLT"),
                    ("KEY", "", "KEYFRAME_HLT"),
                    ("REST", "", "LOOP_BACK"),
                    ("REMOVE", "", "TRASH"),
                ), enabled=lattice_ready)
            if armature is None or str(getattr(armature, "mode", "OBJECT")) != 'POSE':
                from .shortcut_runtime import primary_shortcut_label
                _hint(target, f"{primary_shortcut_label('T')} on the plane: pose it with the handles")
            _draw_poses(target)

        def _draw_corner_pin(target):
            if lattice_mode == "CORNER_PIN" and corners:
                _ops_row(target, "fbp.lattice_corner_pin", (
                    ("SELECT", "Corners", "RESTRICT_SELECT_OFF"),
                    ("KEY", "Key", "KEYFRAME_HLT"),
                    ("RESET", "Reset", "LOOP_BACK"),
                    ("REMOVE", "", "TRASH"),
                ), enabled=lattice_ready, scale=1.2)
                _hint(target, "Drag the corners (G) for a true perspective")
            else:
                _ops_row(target, "fbp.lattice_corner_pin", (
                    ("SETUP", "Set Up Corner Pin", "VIEW_PERSPECTIVE"),
                ), enabled=lattice_ready, scale=1.2)
                if lattice_mode == "CAMERA_FLATTEN":
                    _hint(target, "Replaces Camera Flatten on this layer")

        def _draw_bones(target):
            row = target.row(align=True)
            row.enabled = lattice_ready
            row.scale_y = 1.2
            drawing = _geometry_nodes_module().FBP_OT_AddLatticeBones.fbp_is_running(rig_name)
            add = row.operator(
                "fbp.add_lattice_bones", text="Done Drawing" if drawing else "Add Bones",
                icon="CHECKMARK" if drawing else "BONE_DATA", depress=drawing,
            )
            add.rig_name = rig_name
            row.prop(rig, "fbp_lattice_bones_ik", text="IK", toggle=True)
            if not bone_count:
                _hint(target, "Click shoulder, elbow, hand · Right Click: new chain")
                return
            editing_bones = bool(armature is not None and str(getattr(armature, "mode", "OBJECT")) == 'EDIT')
            actions = target.row(align=True)
            actions.label(text=f"{bone_count} bones", icon="BONE_DATA")
            _ops_row(actions, "fbp.lattice_bones_action", (
                ("DONE", "", "CHECKMARK") if editing_bones else ("POSE", "", "POSE_HLT"),
                ("EDIT", "", "EDITMODE_HLT"),
                ("KEY", "", "KEYFRAME_HLT"),
                ("REST", "", "LOOP_BACK"),
                ("REMOVE", "", "TRASH"),
            ), enabled=lattice_ready)
            target.prop(rig, "fbp_lattice_pins_follow_drawing")

        def _draw_pins(target):
            row = target.row(align=True)
            row.enabled = lattice_ready
            row.scale_y = 1.2
            row.prop(rig, "fbp_lattice_pin_kind", text="")
            placing = _geometry_nodes_module().FBP_OT_AddLatticePins.fbp_is_running(rig_name)
            add = row.operator(
                "fbp.add_lattice_pins", text="Done Placing" if placing else "Add Pins",
                icon="CHECKMARK" if placing else "PINNED", depress=placing,
            )
            add.rig_name = rig_name
            if not pins:
                _hint(target, "Click on the layer to place pins")
                return
            listing = target.column(align=True)
            for pin in pins:
                item = listing.row(align=True)
                selected = bool(getattr(pin, "select", False))
                pick = item.operator(
                    "fbp.select_lattice_pin", text=pin.name,
                    icon="FORCE_VORTEX" if pin_kind(pin) == KIND_BEND else "PINNED",
                    depress=selected,
                )
                pick.rig_name = rig_name
                pick.pin_name = pin.name
                if float(getattr(pin, "fbp_lattice_pin_stiffness", 0.0) or 0.0) > 0.0:
                    item.label(text="", icon="FREEZE")
                remove = item.operator("fbp.remove_lattice_pin", text="", icon="X")
                remove.rig_name = rig_name
                remove.pin_name = pin.name
            if active_bone is not None and active_bone in pins:
                target.prop(active_bone, "fbp_lattice_pin_stiffness", slider=True)
            actions = target.row(align=True)
            actions.enabled = lattice_ready
            for action, label, icon in (
                ("KEY", "Key", "KEYFRAME_HLT"),
                ("REST", "Rest", "LOOP_BACK"),
                ("SET_REST", "Set Rest", "PIVOT_CURSOR"),
            ):
                operator = actions.operator("fbp.lattice_pins_action", text=label, icon=icon)
                operator.rig_name = rig_name
                operator.action = action
            remove_all = actions.operator("fbp.remove_lattice_pin", text="", icon="TRASH")
            remove_all.rig_name = rig_name
            remove_all.pin_name = ""
            target.prop(rig, "fbp_lattice_pins_follow_drawing")

        def _draw_camera(target):
            if lattice_mode != "CAMERA_FLATTEN":
                row = target.row(align=False)
                row.enabled = camera_valid
                row.scale_y = 1.2
                setup = row.operator("fbp.setup_lattice_camera_flatten", text="Set Up Camera Flatten", icon="CAMERA_DATA")
                setup.rig_name = rig_name
                if not camera_valid:
                    warn = target.row(align=False)
                    warn.alert = True
                    warn.label(text="Set an active Perspective or Orthographic camera", icon="ERROR")
                else:
                    _hint(target, "Keeps a 3D layer looking flat to the camera")
                return
            controls = target.column(align=False)
            controls.enabled = camera_valid
            _fbp_draw_effect_property(controls, rig, definition, "fbp_lattice_flatten_influence", labels)
            _fbp_draw_effect_property(controls, rig, definition, "fbp_lattice_live_update", labels)
            if not camera_valid:
                warn = target.row(align=False)
                warn.alert = True
                warn.label(text="Set an active Perspective or Orthographic camera", icon="ERROR")
            action_row = target.row(align=True)
            action_row.enabled = camera_valid and lattice_ready
            for operator_id, label, icon in (
                ("fbp.update_lattice_flatten", "Update", "FILE_REFRESH"),
                ("fbp.bake_lattice_flatten", "Bake", "CHECKMARK"),
                ("fbp.freeze_lattice_flatten", "Freeze", "EDITMODE_HLT"),
            ):
                operator = action_row.operator(operator_id, text=label, icon=icon)
                operator.rig_name = rig_name

        content = box.column(align=False)
        if rig_type == "CAMERA":
            _draw_camera(content)
        elif rig_type == "CORNER_PIN":
            _draw_corner_pin(content)
        elif rig_type == "BONES":
            _draw_bones(content)
        elif rig_type == "PINS":
            _draw_pins(content)
        else:
            _draw_grid(content)
        _draw_grid_settings(box, title="Perspective Grid" if lattice_mode == "CAMERA_FLATTEN" else "Cage & Mesh")
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
            warning.label(text="High alpha detail may slow viewport playback", icon="ERROR")
    elif effect_id == FBP_EFFECT_WIND_BENDER:
        _fbp_draw_quality_triplet(
            box,
            rig,
            title="Mesh Detail",
            icon="MOD_SUBSURF",
            viewport_prop="fbp_wind_subdivision",
            playback_prop="fbp_wind_playback_subdivision",
            render_prop="fbp_wind_render_subdivision",
        )
        _fbp_draw_effect_property(box, rig, definition, "fbp_wind_shade_smooth", labels)
        _fbp_draw_effect_property(box, rig, definition, "fbp_wind_motion_mode", labels)
        motion_mode = str(getattr(rig, "fbp_wind_motion_mode", "SWAY") or "SWAY")
        motion = box.box()
        motion.label(text={"SWAY": "Sway", "FLOW": "Flowing Waves", "RIPPLE": "Ripple"}.get(motion_mode, "Wind"), icon="FORCE_WIND")
        if motion_mode == "SWAY":
            _fbp_draw_compact_effect_properties(motion, rig, definition, ("fbp_wind_bend_amount", "fbp_wind_speed"), labels)
        else:
            if motion_mode == "RIPPLE":
                _fbp_draw_effect_property(motion, rig, definition, "fbp_wind_ripple_direction", labels)
            _fbp_draw_compact_effect_properties(
                motion, rig, definition,
                ("fbp_wind_wave_count", "fbp_wind_wave_amplitude", "fbp_wind_wave_speed"),
                labels,
            )

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

        _fbp_draw_effect_section(box, "Direction", "ORIENTATION_GLOBAL", separator=True)
        direction = box.row(align=True)
        direction.prop(rig, "fbp_wind_direction_space", text="Local / World")
        direction.prop(rig, "fbp_wind_preview_falloff", text="", toggle=True, icon="HIDE_OFF")
        select_wind_direction = direction.operator(
            "fbp.select_effect_control", text="", icon="FORCE_WIND"
        )
        select_wind_direction.effect_id = effect_id
        hint = box.row(align=False)
        hint.enabled = False
        hint.label(text="Rotate the directional null to set the wind direction", icon="BLANK1")

        _fbp_draw_effect_section(box, "Noise", "RNDCURVE", separator=True)
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            ("fbp_wind_noise_scale", "fbp_wind_turbulence", "fbp_wind_gust_strength", "fbp_wind_reverse"),
            labels,
        )
        if int(getattr(rig, "fbp_wind_subdivision", 0) or 0) >= 5:
            warning = box.row(); warning.alert = True
            warning.label(text="High mesh detail may slow viewport playback", icon="ERROR")

    elif effect_id == FBP_EFFECT_COLOR_MASK:
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            (
                "fbp_color_mask_color",
                "fbp_color_mask_tolerance",
                "fbp_color_mask_softness",
                "fbp_color_mask_factor",
                "fbp_color_mask_invert",
                "fbp_color_mask_despill",
            ),
            labels,
        )
        box.label(
            text="Samples the original image or animated sequence color",
            icon="IMAGE_DATA",
        )
        if (
            float(getattr(rig, "fbp_color_mask_despill", 0.0) or 0.0) > 0.0
            and fbp_effect_mask_raw_target_ref(rig, FBP_EFFECT_COLOR_MASK) not in {"", "LAYER"}
        ):
            hint = box.row()
            hint.enabled = False
            hint.label(text="Despill applies only when the key targets the Layer", icon="INFO")
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
                "fbp_noise_mask_seed",
                "fbp_noise_mask_invert",
            ),
            labels,
        )
    else:
        # Only effects with a dedicated contextual panel are excluded from
        # the registry-driven fallback. Every other effect automatically exposes
        # its property_map, including newly added variants.
        if effect_id not in _FBP_CONTEXTUAL_EFFECT_SETTINGS:
            skip = []
            explicit_evolve_speed = str(definition.get("evolve_speed_property", "") or "")
            if explicit_evolve_speed:
                skip.append(explicit_evolve_speed)
            property_names = tuple(
                name for name in (definition.get("property_map", {}) or {})
                if name not in set(skip)
            )
            drawn = (
                _fbp_draw_effect_instance_properties(
                    box, rig, effect_id, instance_id, definition,
                    property_names, labels, grouped=True,
                )
                if instance_id and _fbp_effect_uses_multi_instances(effect_id)
                else _fbp_draw_registered_effect_properties(
                    box, rig, effect_id, definition, labels, skip=tuple(skip)
                )
            )
            if effect_id == FBP_EFFECT_GRADIENT_LIGHT:
                # Softness and Shadow Color live outside the shader socket map
                # but are part of the look: keep them in the panel.
                _fbp_draw_compact_effect_properties(
                    box, rig, definition,
                    ("fbp_gradient_softness", "fbp_gradient_shadow_color"),
                    labels,
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
        perfect = row.operator("fbp.perfect_object_mask_shape", text="", icon="MESH_CIRCLE")
        perfect.rig_name = rig.name
        perfect.shape = shape
        recreate = row.operator("fbp.recreate_object_mask_helper", text="", icon="FILE_REFRESH")
        recreate.rig_name = rig.name
        recreate.shape = shape
        external_null = getattr(rig, f"{prefix}_external_null", None)
        link = row.operator(
            "fbp.link_circle_mask_null", text="", icon="CON_LOCLIKE",
            depress=external_null is not None,
        )
        link.rig_name = rig.name
        link.shape = shape
        if external_null is not None:
            unlink = row.operator("fbp.link_circle_mask_null", text="", icon="X")
            unlink.rig_name = rig.name
            unlink.shape = shape
            unlink.unlink = True
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
        row.prop(rig, f"{prefix}_invert", text="Invert", toggle=True, icon=ui_icon("action.invert"))
        box.prop(rig, f"{prefix}_feather", text="Feather", slider=True)
        box.prop(rig, f"{prefix}_lock_to_plane", text="Lock 3D Movement", toggle=True, icon="LOCKED")
        box.prop(rig, f"{prefix}_follow_bounds", text="Follow Layer Bounds", toggle=True, icon="CON_FOLLOWPATH")
        external_null = getattr(rig, f"{prefix}_external_null", None)
        if external_null is not None:
            box.label(text=f"Tracks Null: {external_null.name}", icon="EMPTY_AXIS")
        box.label(text="Viewport-only wire helper; it hides when the layer is not selected", icon="HIDE_OFF")

    if effect_id in GP_MASK_EFFECT_IDS:
        try:
            from .grease_pencil_bridge import (
                gp_mask_slot_contract,
                is_gp_mask_canvas,
                draw_gp_mask_settings_ui,
            )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            gp_mask_slot_contract = None
            is_gp_mask_canvas = lambda _canvas: False
            draw_gp_mask_settings_ui = None
        contract = gp_mask_slot_contract(effect_id) if gp_mask_slot_contract else {}
        source_prop = contract.get("source_type", "fbp_imported_mask_source_type")
        canvas_prop = contract.get("canvas", "fbp_gp_mask_canvas")
        image_prop = contract.get("image", "fbp_imported_mask_image")
        path_prop = contract.get("path", "fbp_imported_mask_path")
        invert_prop = contract.get("invert", "fbp_imported_mask_invert")
        factor_prop = invert_prop.replace("_invert", "_factor")

        source_type = str(getattr(rig, source_prop, "FILE") or "FILE").upper()
        gp_canvas = getattr(rig, canvas_prop, None)
        pointer_image = getattr(rig, image_prop, None)
        mask_path = str(getattr(rig, path_prop, "") or "")
        if source_type == "GREASE_PENCIL" and is_gp_mask_canvas(gp_canvas):
            if draw_gp_mask_settings_ui is not None:
                draw_gp_mask_settings_ui(box, context, gp_canvas, embedded=True, header_actions=False)
            if pointer_image is None:
                warning = box.row()
                warning.alert = True
                warning.label(text="Grease Pencil mask not generated yet", icon="ERROR")
        else:
            row = box.row(align=True)
            row.prop(rig, path_prop, text="Mask Image")
            if not mask_path or not os.path.isfile(bpy.path.abspath(mask_path)):
                warning = box.row()
                warning.alert = True
                warning.label(text="Imported mask image is missing", icon="ERROR")
            else:
                box.label(text="Raster mask transferred from the layered source", icon="IMAGE_ALPHA")
        if source_type != "GREASE_PENCIL" and hasattr(rig, factor_prop) and hasattr(rig, invert_prop):
            row = box.row(align=True)
            row.prop(rig, factor_prop, text="Factor", slider=True)
            row.prop(rig, invert_prop, text="Invert", toggle=True, icon=ui_icon("action.invert"))

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
        box.label(text="Pairwise transfer; complex multi-layer composites may differ from the source app", icon="BLANK1")

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
        row.prop(rig, "fbp_clipping_mask_invert", text="Invert", toggle=True, icon=ui_icon("action.invert"))
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
        source_mode = "FBP_SEQUENCE"
        if is_luma:
            source_mode = str(getattr(rig, "fbp_luma_matte_source_type", "FBP_SEQUENCE") or "FBP_SEQUENCE").upper()
            box.prop(rig, "fbp_luma_matte_source_type", text="")
        source_rig = None
        if source_mode == "FILE":
            box.prop(rig, "fbp_luma_matte_path", text="Image / Video")
            external_image = getattr(rig, "fbp_luma_matte_image", None)
            raw_path = str(getattr(rig, "fbp_luma_matte_path", "") or "")
            resolved_path = bpy.path.abspath(raw_path) if raw_path else ""
            if not resolved_path or not os.path.isfile(resolved_path):
                warning = box.row()
                warning.alert = True
                warning.label(text="Choose an existing image or video file", icon="ERROR")
            elif external_image is not None:
                box.label(text=f"Loaded: {external_image.name}", icon="FILE_MOVIE" if str(getattr(external_image, "source", "")) == "MOVIE" else "IMAGE_DATA")
            box.label(text="External media is sampled in normalized UV space", icon="UV")
        else:
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
            preview_warning.label(text="Diagnostic preview changes the layer alpha; restore Final before rendering", icon="BLANK1")
        if source_mode != "FILE":
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
        row.prop(rig, invert_prop, text="Invert", toggle=True, icon=ui_icon("action.invert"))
        if is_luma:
            row = box.row(align=True)
            row.prop(rig, "fbp_luma_matte_threshold", text="Threshold", slider=True)
            row.prop(rig, "fbp_luma_matte_softness", text="Softness", slider=True)
        if source_mode != "FILE" and not bool(getattr(rig, transform_prop, False)):
            box.label(text="Enable Follow Source Transform for spatial track mattes", icon="BLANK1")
    if str(definition.get("stage", "") or "") == "MASK":
        operation = fbp_mask_stack_operation(rig, effect_id)
        # One block: where the operation is a modifier input, its hint goes too.
        operation_box = box.column(align=False)
        operation_row = operation_box.row(align=True)
        operation_row.label(text="Stack Operation", icon="SELECT_INTERSECT")
        operation_menu = operation_row.operator_menu_enum(
            "fbp.set_mask_stack_operation",
            "operation",
            text={
                "ADD": "Add",
                "SUBTRACT": "Subtract",
                "INTERSECT": "Intersect",
                "DIFFERENCE": "Difference",
            }.get(operation, "Intersect"),
        )
        operation_menu.mask_effect_id = effect_id
        hint = operation_box.row(align=False)
        hint.enabled = False
        hint.label(
            text=(
                "The first active mask establishes the matte; each following "
                "mask uses its operation."
            ),
            icon="INFO",
        )
    if _fbp_effect_is_local_mask(effect_id) and effect_id not in GP_MASK_EFFECT_IDS:
        mask_target_ref = fbp_effect_mask_target_ref(rig, effect_id)
        if mask_target_ref != "LAYER":
            mask_target, mask_target_instance = _fbp_effect_ref_parts(mask_target_ref)
            target_definition = fbp_effect_definition(mask_target)
            target_row = box.row(align=True)
            target_row.label(
                text=f"Limits {_fbp_effect_display_label(mask_target, target_definition)}",
                icon="CLIPUV_HLT",
            )
            open_masks = target_row.operator(
                "fbp.open_effect_masks", text="", icon=ui_icon("action.mask"), emboss=False
            )
            open_masks.effect_id = mask_target
            open_masks.instance_id = mask_target_instance
        else:
            box.label(text="Applies to the complete layer alpha", icon="IMAGE_ALPHA")


    if effect_id == FBP_EFFECT_GAUSSIAN_BLUR:
        gaussian_properties = (
            "fbp_gaussian_blur_radius_x", "fbp_gaussian_blur_radius_y",
            "fbp_gaussian_blur_samples", "fbp_gaussian_blur_factor",
        )
        if instance_id and _fbp_effect_uses_multi_instances(effect_id):
            _fbp_draw_effect_instance_properties(
                box, rig, effect_id, instance_id, definition,
                gaussian_properties, labels,
            )
        else:
            _fbp_draw_compact_effect_properties(
                box, rig, definition, gaussian_properties, labels,
            )
        box.label(text="Gaussian-weighted alpha-safe sampling", icon="IMAGE_ALPHA")
    if effect_id == FBP_EFFECT_DIRECTIONAL_BLUR:
        hidden = _fbp_effect_control_hidden_properties(rig, effect_id)
        _fbp_draw_compact_effect_properties(
            box, rig, definition,
            tuple(name for name in (
                "fbp_directional_blur_angle",
                "fbp_directional_blur_distance",
                "fbp_directional_blur_samples",
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
        _fbp_draw_effect_section(box, "Grid", "MESH_GRID")
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_pixelate_grid_mode", labels
        )
        pixels_x, pixels_y, mode = _fbp_pixelate_grid(rig)
        if mode == "EXACT":
            _fbp_draw_compact_effect_properties(
                box, rig, definition,
                ("fbp_pixelate_resolution", "fbp_pixelate_height"), labels
            )
        else:
            _fbp_draw_compact_effect_properties(
                box, rig, definition,
                ("fbp_pixelate_size", "fbp_pixelate_stretch"), labels
            )
        preview = box.row(align=False)
        preview.enabled = False
        preview.label(text=f"Resulting grid: {pixels_x} × {pixels_y}", icon="ALIASED")

        hidden = _fbp_effect_control_hidden_properties(rig, effect_id)
        _fbp_draw_effect_section(box, "Transform", "ORIENTATION_GLOBAL", separator=True)
        transform_properties = tuple(name for name in (
            "fbp_pixelate_rotation", "fbp_pixelate_offset_x", "fbp_pixelate_offset_y"
        ) if name not in hidden)
        if transform_properties:
            _fbp_draw_compact_effect_properties(
                box, rig, definition, transform_properties, labels,
            )
        elif bool(getattr(rig, "fbp_effect_controls_enabled", True)):
            hint = box.row(align=False)
            hint.enabled = False
            hint.label(text="Move or rotate the viewport control to edit the grid", icon="EMPTY_ARROWS")

    if effect_id == FBP_EFFECT_HALFTONE:
        _fbp_draw_effect_section(box, "Print Mode", "MESH_GRID")
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_halftone_pattern", labels
        )
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_halftone_color_mode", labels
        )
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_halftone_shape", labels
        )

        hidden = _fbp_effect_control_hidden_properties(rig, effect_id)
        _fbp_draw_effect_section(box, "Dot Screen", "ALIASED", separator=True)
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            tuple(name for name in (
                "fbp_halftone_scale",
                "fbp_halftone_dot_size",
                "fbp_halftone_dot_scale",
                "fbp_halftone_blend",
                "fbp_halftone_softness",
                "fbp_halftone_rotation",
                "fbp_halftone_center_x",
                "fbp_halftone_center_y",
            ) if name not in hidden),
            labels,
        )
        if bool(getattr(rig, "fbp_effect_controls_enabled", True)) and hidden:
            hint = box.row(align=False)
            hint.enabled = False
            hint.label(text="Viewport control edits center and screen angle", icon="EMPTY_ARROWS")

        _fbp_draw_effect_section(box, "Tone", "SEQ_LUMA_WAVEFORM", separator=True)
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            ("fbp_halftone_contrast",),
            labels,
        )
        _fbp_draw_toggle_strip(
            box, rig, (
                ("fbp_halftone_clip_alpha", "Clip", "IMAGE_ALPHA"),
                ("fbp_halftone_invert", "Invert", ui_icon("action.invert")),
                ("fbp_halftone_use_source_color", "Source", "IMAGE_DATA"),
            )
        )
        _fbp_draw_effect_section(box, "Ink & Paper", "COLOR", separator=True)
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            (
                "fbp_halftone_foreground",
                "fbp_halftone_background",
            ),
            labels,
        )
        _fbp_draw_toggle_strip(
            box, rig, (
                ("fbp_halftone_transparent_background", "Transparent", "IMAGE_ALPHA"),
            )
        )
    if effect_id == FBP_EFFECT_DOT_MATRIX:
        _fbp_draw_effect_section(box, "Matrix Grid", "LIGHTPROBE_VOLUME")
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
            ),
            labels,
        )
        _fbp_draw_effect_section(box, "Tone Response", "SEQ_LUMA_WAVEFORM", separator=True)
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            (
                "fbp_dot_matrix_contrast",
                "fbp_dot_matrix_response",
                "fbp_dot_matrix_glow",
            ),
            labels,
        )
        _fbp_draw_toggle_strip(
            box, rig, (
                ("fbp_dot_matrix_invert", "Invert", ui_icon("action.invert")),
                ("fbp_dot_matrix_use_source_color", "Source", "IMAGE_DATA"),
                ("fbp_dot_matrix_transparent_background", "Alpha", "IMAGE_ALPHA"),
            )
        )
        _fbp_draw_effect_section(box, "Random / Damage", "RNDCURVE", separator=True)
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            (
                "fbp_dot_matrix_random_size",
                "fbp_dot_matrix_random_brightness",
                "fbp_dot_matrix_dead_pixels",
                "fbp_dot_matrix_flicker",
            ),
            labels,
        )
        _fbp_draw_effect_property(
            box, rig, definition, "fbp_dot_matrix_seed", labels
        )
        _fbp_draw_effect_section(box, "Ink & Paper", "COLOR", separator=True)
        if not bool(getattr(rig, "fbp_dot_matrix_use_source_color", True)):
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_dot_matrix_foreground", labels
            )
        if not bool(getattr(rig, "fbp_dot_matrix_transparent_background", True)):
            _fbp_draw_effect_property(
                box, rig, definition, "fbp_dot_matrix_background", labels
            )
    if effect_id == FBP_EFFECT_ASCII_MATRIX:
        _fbp_draw_effect_section(box, "Characters", "FONT_DATA")
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
        _fbp_draw_effect_section(box, "Grid / Tone", "SEQ_LUMA_WAVEFORM", separator=True)
        _fbp_draw_compact_effect_properties(
            box,
            rig,
            definition,
            (
                "fbp_ascii_scale",
                "fbp_ascii_contrast",
                "fbp_ascii_gamma",
                "fbp_ascii_glyph_scale",
                "fbp_ascii_glyph_width",
                "fbp_ascii_variation",
                "fbp_ascii_edge_boost",
                "fbp_ascii_dither",
            ),
            labels,
        )
        _fbp_draw_effect_section(box, "Output", "COLOR", separator=True)
        _fbp_draw_toggle_strip(
            box, rig, (
                ("fbp_ascii_invert", "Invert", ui_icon("action.invert")),
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

        section_gap(box)
        edge_box = _fbp_draw_toggle_foldout(
            box, "fbp_effect_ascii_edges", rig, "fbp_terminal_ascii_use_edges",
            "Edges", default_closed=False,
        )
        if edge_box is not None:
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
        viewport.prop(rig, "fbp_text_matrix_viewport_rows", text=_fbp_auto_rows_label(rig, "fbp_text_matrix_viewport_rows"), slider=True)

        playback_body = _fbp_draw_toggle_foldout(
            box, "fbp_effect_text_matrix_playback", rig,
            "fbp_text_matrix_auto_playback_limit", "Playback Limit",
        )
        if playback_body is not None:
            playback_grid = playback_body.row(align=True)
            playback_grid.label(text="Play", icon="PLAY")
            playback_grid.prop(rig, "fbp_text_matrix_playback_columns", text="Columns", slider=True)
            playback_grid.prop(rig, "fbp_text_matrix_playback_rows", text=_fbp_auto_rows_label(rig, "fbp_text_matrix_playback_rows"), slider=True)

        render = box.row(align=True)
        render.label(text="Render", icon="RESTRICT_RENDER_OFF")
        render.prop(rig, "fbp_text_matrix_render_columns", text="Columns", slider=True)
        render.prop(rig, "fbp_text_matrix_render_rows", text=_fbp_auto_rows_label(rig, "fbp_text_matrix_render_rows"), slider=True)

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
    if definition.get("evolve_property") and not (
        effect_id == FBP_EFFECT_MESH_WIGGLE
        and not bool(getattr(rig, _fbp_animation_key(effect_id, "evolve"), False))
    ):
        instance_animation = (
            fbp_effect_instance_animation_item(
                rig, effect_id, instance_id, ensure=False
            )
            if instance_id and _fbp_effect_uses_multi_instances(effect_id)
            else None
        )
        animation_owner = instance_animation or rig
        section_gap(box)
        animation_body = None
        if instance_id and instance_animation is None:
            _fbp_draw_effect_section(box, "Animate", "TIME")
            warning = box.row(align=False)
            warning.enabled = False
            warning.label(text="Instance animation is initializing", icon="FILE_REFRESH")
        else:
            # Always the last section of an animatable effect: the checkbox
            # turns Animate on/off, Seed and Stepped are visible right away.
            animation_body = _fbp_draw_toggle_foldout(
                box, "fbp_effect_animation", animation_owner,
                "evolve" if instance_animation is not None else _fbp_animation_key(effect_id, "evolve"),
                "Animate",
                default_closed=False,
            )
        if animation_body is not None:
            per_instance = instance_animation is not None
            seed_row = animation_body.row(align=True)
            seed_row.prop(
                animation_owner,
                "seed" if per_instance else _fbp_animation_key(effect_id, "seed"),
                text="Seed",
            )
            seed_row.prop(
                animation_owner,
                "step" if per_instance else _fbp_animation_key(effect_id, "step"),
                text="Stepped",
            )
            speed_row = animation_body.row(align=False)
            speed_split = speed_row.split(factor=0.5, align=False)
            speed_split.prop(
                animation_owner,
                "speed" if per_instance else _fbp_effect_evolution_speed_property(effect_id, definition),
                text="Speed",
            )
            speed_split.prop(
                animation_owner,
                "unique" if per_instance else _fbp_animation_key(effect_id, "unique"),
                text="Unique per Layer",
            )
            if instance_animation is not None:
                hint = animation_body.row(align=False)
                hint.enabled = False
                hint.label(
                    text="Parameters and animation are keyframeable per copy",
                    icon="KEY_HLT",
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


class FBP_UL_EffectStack:
    """Shared implementation for the concrete Blender UIList classes.

    Keep this as a plain Python mixin. Registering an RNA UIList base and then
    registering subclasses of it leaves Blender with incompatible RNA
    metaclasses when an installed extension is reloaded or torn down.
    """

    category_filter = ""
    hidden_effect_ids = frozenset()

    def _profile_id(self):
        # Every Effect Stack row uses one shared customizable profile.
        return "EFFECT_IMAGE"

    def _categories(self):
        category_filter = getattr(self, "category_filter", "")
        if isinstance(category_filter, (set, tuple, list, frozenset)):
            return {str(value) for value in category_filter if value}
        category = str(category_filter or "")
        return {category} if category else set()

    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        items = getattr(data, propname, ())
        categories = self._categories()
        profile_id = self._profile_id()
        scene = getattr(context, "scene", None)
        try:
            needle = str(scene.get(f"fbp_uilist_filter_{profile_id.lower()}", "") or "").strip().casefold()
            alphabetical = bool(scene.get(f"fbp_uilist_sort_{profile_id.lower()}", False))
            reverse = bool(scene.get(f"fbp_uilist_reverse_{profile_id.lower()}", False))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            needle, alphabetical, reverse = "", False, False

        hidden_effect_ids = set(getattr(self, "hidden_effect_ids", ()))
        rows = []
        group_members = {}
        effect_categories = {}
        for index, item in enumerate(items):
            row_type = str(getattr(item, "row_type", "EFFECT") or "EFFECT")
            group_id = str(getattr(item, "group_id", "") or "")
            effect_id = ""
            item_category = ""
            searchable = str(getattr(item, "group_name", "") or getattr(item, "name", "") or "")
            if row_type != "GROUP":
                effect_id = fbp_normalize_effect_id(getattr(item, "effect_id", ""))
                definition = fbp_effect_definition(effect_id)
                item_category = str(definition.get("category", "2D") or "2D")
                searchable = " ".join((
                    searchable,
                    effect_id,
                    str(definition.get("label", "") or definition.get("name", "") or ""),
                ))
                effect_categories[effect_id] = item_category
                if group_id and effect_id:
                    group_members.setdefault(group_id, []).append((effect_id, searchable.casefold()))
            rows.append((index, item, row_type, group_id, effect_id, item_category, searchable.casefold()))

        if not categories:
            categories = {str(row[5]) for row in rows if row[5]}

        flags = []
        for _index, item, row_type, group_id, effect_id, item_category, searchable in rows:
            if row_type == "GROUP":
                members = group_members.get(group_id, ())
                visible = any(
                    member not in hidden_effect_ids
                    and effect_categories.get(member, "2D") in categories
                    and (not needle or needle in member_search or needle in searchable)
                    for member, member_search in members
                )
                if needle and needle in searchable:
                    visible = any(
                        member not in hidden_effect_ids
                        and effect_categories.get(member, "2D") in categories
                        for member, _member_search in members
                    )
            else:
                visible = item_category in categories and effect_id not in hidden_effect_ids
                if visible and needle:
                    visible = needle in searchable
                if visible and group_id and bool(getattr(item, "group_collapsed", False)):
                    visible = False
            flags.append(self.bitflag_filter_item if visible else 0)

        new_order = []
        has_groups = any(row[2] == "GROUP" or row[3] for row in rows)
        if alphabetical and not has_groups:
            new_order = sorted(
                range(len(rows)),
                key=lambda index: natural_sort_key(rows[index][6]),
                reverse=reverse,
            )
        elif reverse:
            new_order = list(reversed(range(len(rows))))
        return flags, new_order

    def _draw_group_row(self, context, layout, data, item):
        profile_id = self._profile_id()
        flags = fbp_uilist_icon_flags(context, profile_id)
        control_order = fbp_uilist_icon_order(context, profile_id)
        group_id = str(getattr(item, "group_id", "") or "")
        group_name = str(getattr(item, "group_name", "") or "Effect Group")
        collapsed = bool(getattr(item, "group_collapsed", False))
        members = fbp_effect_group_members_from_items(data, group_id)
        member_count = len(members)
        rigs = _fbp_selected_rigs(context)
        if data not in rigs:
            rigs = [data]
        member_set = set(members)
        selected_members = set()
        for effect_item in data.fbp_effects:
            if not bool(getattr(effect_item, "is_selected", False)):
                continue
            selected_effect_id = fbp_normalize_effect_id(
                getattr(effect_item, "effect_id", "")
            )
            selected_instance_id = (
                str(getattr(effect_item, "instance_id", "") or "")
                if _fbp_effect_uses_multi_instances(selected_effect_id) else ""
            )
            selected_token = _fbp_effect_ref(selected_effect_id, selected_instance_id)
            if selected_token in member_set:
                selected_members.add(selected_token)
        all_group_selected = bool(member_count) and len(selected_members) == member_count

        supported = {
            "effect_select", "effect_type", "label", "effect_solo", "effect_viewport",
            "effect_mask",
        }
        ordered_columns = [
            key for key in control_order
            if (key in supported or fbp_uilist_is_spacer(key))
            and flags.get(key, False)
        ]

        zones = fbp_uilist_row_layouts(
            layout,
            context,
            profile_id,
            order=control_order,
            # ``fixed_grip`` already reserves the structural drag handle.
            # Collapse is the only additional fixed cell on the left.
            leading_units=1,
            # The group action menu is structural and remains at the far right.
            trailing_units=1,
        )
        targets = zones["targets"]

        # The grip is structural and intentionally never enters the configurable
        # column order. It is always the absolute first cell on the left.
        handle = zones["left"].row(align=True)
        handle.enabled = bool(members)
        drag = handle.operator("fbp.drag_effect", text="", icon="GRIP_V", emboss=False)
        first_effect, first_instance = _fbp_effect_ref_parts(members[0] if members else "")
        drag.effect_id = first_effect
        drag.instance_id = first_instance
        drag.group_id = group_id

        collapse = zones["left"].operator(
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

        active_members_by_rig = [
            (rig, tuple(member for member in members if _fbp_effect_ref_is_active(rig, member)))
            for rig in rigs
        ]
        solo_states = [
            all(
                fbp_effect_is_soloed(rig, *_fbp_effect_ref_parts(member))
                for member in active_members
            )
            for rig, active_members in active_members_by_rig
            if member_count and len(active_members) == member_count
        ]
        soloed = bool(solo_states) and all(solo_states)
        global_states = [
            fbp_effect_global_visible_state(
                rig, _fbp_effect_ref_effect_id(member),
                instance_id=_fbp_effect_ref_instance_id(member),
            )
            for rig, active_members in active_members_by_rig
            for member in active_members
        ]
        globally_visible = bool(global_states) and all(global_states)

        for key in ordered_columns:
            target = targets.get(key, zones["right"])
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(target)
                continue
            if key == "effect_select":
                toggle_selection = target.operator(
                    "fbp.toggle_effect_group_selection",
                    text="",
                    icon="CHECKBOX_HLT" if all_group_selected else "CHECKBOX_DEHLT",
                    emboss=False,
                )
                toggle_selection.group_id = group_id
                toggle_selection.selected = not all_group_selected
            elif key == "effect_type":
                select = target.operator(
                    "fbp.select_effect_group",
                    text="",
                    icon=folder_icon,
                    emboss=False,
                    depress=all_group_selected,
                )
                select.group_id = group_id
            elif key == "label":
                select = target.operator(
                    "fbp.select_effect_group",
                    text=f"{group_name} ({member_count})",
                    icon="NONE",
                    emboss=False,
                    depress=all_group_selected,
                )
                select.group_id = group_id
            elif key == "effect_solo":
                solo = target.operator(
                    "fbp.toggle_effect_solo", text="",
                    icon="OUTLINER_OB_LIGHT" if soloed else "LIGHT",
                    emboss=False,
                )
                solo.effect_id = ""
                solo.group_id = group_id
            elif key == "effect_viewport":
                visibility = target.operator(
                    "fbp.effect_group_action", text="",
                    icon="HIDE_OFF" if globally_visible else "HIDE_ON",
                    emboss=False,
                )
                visibility.group_id = group_id
                visibility.action = "HIDE" if globally_visible else "SHOW"
            elif key == "effect_mask":
                target.label(text="", icon="BLANK1")

        zones["right"].operator_context = "INVOKE_DEFAULT"
        actions = zones["right"].operator(
            "fbp.effect_group_actions",
            text="",
            icon="COLLAPSEMENU",
            emboss=False,
        )
        actions.group_id = group_id

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        mark_ui_list_draw()
        profile_id = self._profile_id()
        flags = fbp_uilist_icon_flags(context, profile_id)
        control_order = fbp_uilist_icon_order(context, profile_id)
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
        instance_id = str(getattr(item, "instance_id", "") or "")
        effect_icon = str(definition.get("icon", "MODIFIER"))
        effect_icon_value = effect_custom_icon_value(effect_id)
        label = _fbp_effect_display_label(effect_id, definition)
        sibling_rows = [
            candidate for candidate in getattr(data, "fbp_effects", ())
            if str(getattr(candidate, "row_type", "EFFECT") or "EFFECT") == "EFFECT"
            and fbp_normalize_effect_id(getattr(candidate, "effect_id", "")) == effect_id
        ]
        if len(sibling_rows) > 1:
            ordinal = next(
                (sibling_index + 1 for sibling_index, candidate in enumerate(sibling_rows)
                 if str(getattr(candidate, "instance_id", "") or "") == instance_id),
                1,
            )
            label = f"{label} {ordinal}"
        if effect_id in GP_MASK_EFFECT_IDS:
            try:
                from .grease_pencil_bridge import gp_mask_slot_contract, is_gp_mask_canvas
                contract = gp_mask_slot_contract(effect_id)
                gp_canvas = getattr(data, contract.get("canvas", ""), None)
                gp_source = str(getattr(data, contract.get("source_type", ""), "") or "").upper()
                if gp_source == "GREASE_PENCIL" or is_gp_mask_canvas(gp_canvas):
                    label = "Grease Pencil Mask"
                    effect_icon = "OUTLINER_OB_GREASEPENCIL"
                    effect_icon_value = ui_icon_value("menu.gp_layer")
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        if self.layout_type == "GRID":
            layout.alignment = "CENTER"
            if effect_icon_value:
                layout.label(text="", icon_value=effect_icon_value)
            else:
                layout.label(text="", icon=effect_icon)
            return

        rigs = _fbp_selected_rigs(context)
        if data not in rigs:
            rigs = [data]
        selected_count = len(rigs)
        active_rigs = [
            rig for rig in rigs if effect_id in _fbp_runtime_effect_ids(rig)
        ]
        present_count = len(active_rigs)
        states = [
            fbp_effect_global_visible_state(
                rig, effect_id, instance_id=instance_id if len(rigs) == 1 else ""
            )
            for rig in active_rigs
        ]
        all_visible = bool(states) and all(states)
        is_partial = 0 < present_count < selected_count
        group_id = str(getattr(item, "group_id", "") or "")

        supported = {
            "effect_select", "effect_type", "label", "effect_solo", "effect_viewport",
            "effect_mask",
        }
        ordered_columns = [
            key for key in control_order
            if (key in supported or fbp_uilist_is_spacer(key))
            and flags.get(key, False)
            and (key != "effect_viewport" or definition.get("kind") != "BASE")
        ]
        layout_order = tuple(
            key
            for key in control_order
            if key != "effect_viewport" or definition.get("kind") != "BASE"
        )
        is_mask_effect = (
            str(definition.get("category", "") or "").upper() == "MASK"
        )

        zones = fbp_uilist_row_layouts(
            layout,
            context,
            profile_id,
            order=layout_order,
            # ``fixed_grip`` already accounts for the real drag handle.
            leading_units=1 if group_id else 0,
            # A partial-stack copy icon is one cell.  The mask operation button
            # contains both an icon and a short operation glyph.
            trailing_units=(1 if is_partial else 0) + (2 if is_mask_effect else 0),
        )
        targets = zones["targets"]

        drag_token = _fbp_effect_ref(
            effect_id, instance_id if _fbp_effect_uses_multi_instances(effect_id) else ""
        )
        draggable = bool(
            definition.get("kind") in {"SHADER", "GEOMETRY"}
            and present_count == selected_count
            and (
                _geometry_nodes_module().fbp_can_move_effect_selection(rigs, (drag_token,), "UP")
                or _geometry_nodes_module().fbp_can_move_effect_selection(rigs, (drag_token,), "DOWN")
            )
        )
        handle = zones["left"].row(align=True)
        handle.enabled = draggable
        drag = handle.operator("fbp.drag_effect", text="", icon="GRIP_V", emboss=False)
        drag.effect_id = effect_id
        drag.instance_id = instance_id
        drag.group_id = ""

        selected = bool(getattr(item, "is_selected", False))
        if group_id:
            zones["left"].label(text="", icon="BLANK1")

        if is_partial:
            copy = zones["right"].operator(
                "fbp.copy_effect_to_selected", text="", icon="PASTEDOWN", emboss=False
            )
            copy.effect_id = effect_id

        if is_mask_effect:
            operations = {
                fbp_mask_stack_operation(active_rig, effect_id)
                for active_rig in active_rigs
            }
            operation = next(iter(operations)) if len(operations) == 1 else ""
            operation_text = {
                "ADD": "+",
                "SUBTRACT": "−",
                "INTERSECT": "∩",
                "DIFFERENCE": "Δ",
            }.get(operation, "*")
            operation_menu = zones["right"].operator_menu_enum(
                "fbp.set_mask_stack_operation",
                "operation",
                text=operation_text,
                icon="SELECT_INTERSECT",
            )
            operation_menu.mask_effect_id = effect_id

        solo_states = [
            fbp_effect_is_soloed(
                rig, effect_id, instance_id=instance_id if len(rigs) == 1 else ""
            ) for rig in active_rigs
        ]
        soloed = bool(solo_states) and all(solo_states)
        attached_count = 0
        if _fbp_effect_can_receive_mask(effect_id):
            attached_count = sum(
                bool(fbp_masks_targeting_effect(rig, effect_id, instance_id))
                for rig in active_rigs
            )

        display_text = (
            f"↳ {label} ({present_count}/{selected_count})"
            if is_partial and group_id
            else (
                f"{label} ({present_count}/{selected_count})"
                if is_partial else (f"↳ {label}" if group_id else label)
            )
        )

        for key in ordered_columns:
            target = targets.get(key, zones["right"])
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(target)
                continue
            if key == "effect_select":
                target.prop(
                    item,
                    "is_selected",
                    text="",
                    icon="CHECKBOX_HLT" if selected else "CHECKBOX_DEHLT",
                    emboss=False,
                )
            elif key == "effect_type":
                select_kwargs = (
                    {"icon": "ERROR"} if is_partial
                    else ({"icon_value": effect_icon_value} if effect_icon_value else {"icon": effect_icon})
                )
                select = target.operator(
                    "fbp.select_effect",
                    text="",
                    **select_kwargs,
                    emboss=False,
                    depress=selected,
                )
                select.effect_id = effect_id
                select.instance_id = instance_id
            elif key == "label":
                select = target.operator(
                    "fbp.select_effect",
                    text=display_text,
                    icon="NONE",
                    emboss=False,
                    depress=selected,
                )
                select.effect_id = effect_id
                select.instance_id = instance_id
            elif key == "effect_solo":
                solo_row = target.row(align=True)
                solo_row.enabled = bool(
                    present_count == selected_count
                    and definition.get("kind") in {"SHADER", "GEOMETRY"}
                )
                solo = solo_row.operator(
                    "fbp.toggle_effect_solo", text="",
                    icon="OUTLINER_OB_LIGHT" if soloed else "LIGHT", emboss=False,
                )
                solo.effect_id = effect_id
                solo.instance_id = instance_id if len(rigs) == 1 else ""
                solo.group_id = ""
            elif key == "effect_viewport":
                target.prop(
                    item, "visible", text="",
                    icon="HIDE_OFF" if all_visible else "HIDE_ON",
                    icon_only=True, emboss=False,
                )
            elif key == "effect_mask":
                maskable = _fbp_effect_can_receive_mask(effect_id)
                mask_cell = target.row(align=True)
                mask_cell.enabled = bool(maskable and present_count == selected_count)
                if maskable:
                    mask_cell.alert = bool(0 < attached_count < selected_count)
                    mask = mask_cell.operator(
                        "fbp.open_effect_masks", text="",
                        icon="CLIPUV_HLT" if attached_count else "CLIPUV_DEHLT",
                        emboss=False,
                    )
                    mask.effect_id = effect_id
                    mask.instance_id = instance_id
                else:
                    mask_cell.label(text="", icon="BLANK1")


class FBP_UL_EffectStack2D(FBP_UL_EffectStack, UIList):
    # Layer Blend is a first-class layer property drawn above the stack.
    category_filter = {"BASE", "2D"}
    hidden_effect_ids = frozenset({FBP_EFFECT_LAYER_BLEND})


class FBP_UL_EffectStack3D(FBP_UL_EffectStack, UIList):
    category_filter = "3D"


class FBP_UL_EffectStackMask(FBP_UL_EffectStack, UIList):
    category_filter = "MASK"


class FBP_UL_EffectStackUnified(FBP_UL_EffectStack, UIList):
    """One mixed Image / Mask / Mesh stack in persistent evaluation order."""

    category_filter = ""
    hidden_effect_ids = frozenset({FBP_EFFECT_LAYER_BLEND})


_FBP_EFFECT_MASK_ENUM_CACHE = []


def _fbp_effect_mask_enum_items(_self=None, context=None):
    """Return one dropdown of attachable local masks, one column per kind.

    Columns follow the Mask menu: Shape, Nodes, Advanced. The numeric values
    stay those of the earlier flat list so stored choices keep their meaning.
    """
    rigs = _fbp_selected_rigs(context) if context is not None else []
    values = {
        effect_id: index for index, effect_id in enumerate((
            FBP_EFFECT_COLOR_MASK,
            FBP_EFFECT_LUMINANCE_MASK,
            FBP_EFFECT_CHANNEL_MASK,
            FBP_EFFECT_GRADIENT_MASK,
            FBP_EFFECT_NOISE_MASK,
            FBP_EFFECT_VORONOI_MASK,
            FBP_EFFECT_WAVE_MASK,
            FBP_EFFECT_SQUARE_MASK,
            FBP_EFFECT_CIRCLE_MASK,
            FBP_EFFECT_TRIANGLE_MASK,
            FBP_EFFECT_ALPHA_MATTE,
            FBP_EFFECT_LUMA_MATTE,
            FBP_EFFECT_EDGE_DISTANCE_MASK,
        ))
    }
    items = []
    for section_label, _icon, tokens in FBP_MASK_EFFECT_MENU_SECTIONS:
        section = []
        for effect_id in tokens:
            if effect_id not in values:
                continue
            definition = fbp_effect_definition(effect_id)
            if not definition:
                continue
            if rigs and not any(
                fbp_effect_supported_for_rig(rig, effect_id) for rig in rigs
            ):
                continue
            label = _fbp_effect_display_label(effect_id, definition, fallback="Mask")
            section.append((
                effect_id,
                label,
                f"Create or attach {label}",
                effect_enum_icon(effect_id, definition.get("icon", "MOD_MASK")),
                values[effect_id],
            ))
        if section:
            # An empty identifier starts a new titled column in enum menus.
            items.append(("", section_label, ""))
            items.extend(section)
    # Blender keeps only weak references to dynamic enum strings.
    _FBP_EFFECT_MASK_ENUM_CACHE[:] = items
    return _FBP_EFFECT_MASK_ENUM_CACHE


_FBP_DEFAULT_EFFECT_MASK = "GRADIENT_MASK"


def fbp_draw_effect_mask_panel(layout, context, rigs, rig, effect_id, instance_id=""):
    """Draw the native-style Mask subpanel under one effect's settings.

    The header checkbox enables the effect's mask, the dropdown picks its type
    and the attached mask settings are drawn inline, like a modifier panel.
    """
    effect_id = fbp_normalize_effect_id(effect_id)
    if not rig or not _fbp_effect_can_receive_mask(effect_id):
        return False
    instance_id = str(instance_id or "") if _fbp_effect_uses_multi_instances(effect_id) else ""
    attached = tuple(fbp_masks_targeting_effect(rig, effect_id, instance_id))
    enabled = bool(attached) and all(fbp_effect_visible_state(rig, mask_id) for mask_id in attached)
    try:
        header, body = layout.panel("fbp_effect_mask_panel", default_closed=True)
    except (AttributeError, TypeError):
        header, body = layout.row(align=True), layout.column(align=False)
    toggle = header.operator(
        "fbp.toggle_effect_masks",
        text="",
        icon="CHECKBOX_HLT" if enabled else "CHECKBOX_DEHLT",
        emboss=False,
    )
    toggle.target_effect_id = effect_id
    toggle.target_instance_id = instance_id
    header.label(text="Mask", icon="MOD_MASK")
    if attached:
        header.label(
            text=", ".join(
                _fbp_effect_display_label(mask_id, fbp_effect_definition(mask_id), fallback="Mask")
                for mask_id in attached
            )
        )
    if body is None:
        return True
    configure_layout(body)
    row = body.row(align=True)
    if len(attached) == 1:
        current = fbp_effect_definition(attached[0])
        text = _fbp_effect_display_label(attached[0], current, fallback="Mask")
        icon_kwargs = effect_icon_kwargs(attached[0], current.get("icon", "MOD_MASK"))
    else:
        text = "Add Mask" if attached else "None"
        icon_kwargs = {"icon": "ADD" if attached else "MOD_MASK"}
    row.label(text="Type")
    choose = row.operator_menu_enum(
        "fbp.set_effect_mask_type", "mask_effect_id", text=text, **icon_kwargs
    )
    choose.target_effect_id = effect_id
    choose.target_instance_id = instance_id
    advanced = row.operator("fbp.open_effect_masks", text="", icon="PREFERENCES")
    advanced.effect_id = effect_id
    advanced.instance_id = instance_id
    if not attached:
        hint_row(body, "Tick the box or pick a type to mask only this effect.", icon="INFO", disabled=True)
        return True
    settings = body.column(align=False)
    settings.active = enabled
    for mask_id in attached:
        fbp_draw_effect_settings(
            settings, rig, mask_id,
            selected_count=len(rigs or ()) or 1,
            present_count=sum(
                1 for item in tuple(rigs or ()) if mask_id in fbp_masks_targeting_effect(item, effect_id, instance_id)
            ) or 1,
            context=context,
        )
    return True


def fbp_draw_effect_mask_editor(layout, context, rigs, target_effect_id, target_instance_id=""):
    """Draw a compact mask popup with one native dropdown.

    Detailed mask controls remain in the normal Masks stack; this popup only
    manages attachment, selection and removal, avoiding a second nested effects
    inspector inside a transient menu.
    """
    target_effect_id = fbp_normalize_effect_id(target_effect_id)
    target_instance_id = (
        str(target_instance_id or "")
        if _fbp_effect_uses_multi_instances(target_effect_id) else ""
    )
    target_ref = _fbp_effect_ref(target_effect_id, target_instance_id)
    if not rigs or not _fbp_effect_can_receive_mask(target_effect_id):
        return False
    target_definition = fbp_effect_definition(target_effect_id)
    compatible_rigs = [
        rig for rig in rigs if _fbp_effect_ref_is_active(rig, target_ref)
    ]
    if not target_definition or not compatible_rigs:
        return False

    panel = layout.column(align=False)
    header = panel.row(align=True)
    header.label(
        text=_fbp_effect_display_label(target_effect_id, target_definition),
        icon="CLIPUV_HLT",
    )
    if len(compatible_rigs) != len(rigs):
        header.label(text=f"{len(compatible_rigs)}/{len(rigs)}", icon="ERROR")
    header.operator(
        "fbp.close_effect_masks", text="", icon=ui_icon("action.close"), emboss=False
    )

    attachment_counts = {}
    for rig in compatible_rigs:
        for mask_effect_id in fbp_masks_targeting_effect(
            rig, target_effect_id, target_instance_id
        ):
            attachment_counts[mask_effect_id] = attachment_counts.get(mask_effect_id, 0) + 1

    attached_box = panel.box()
    attached_box.label(text="Attached Masks", icon="LINKED")
    if attachment_counts:
        for mask_effect_id, count in attachment_counts.items():
            definition = fbp_effect_definition(mask_effect_id)
            row = attached_box.row(align=True)
            label = _fbp_effect_display_label(mask_effect_id, definition, fallback="Mask")
            if count != len(compatible_rigs):
                label = f"{label} ({count}/{len(compatible_rigs)})"
            select = row.operator(
                "fbp.select_effect",
                text=label,
                emboss=False,
                **effect_icon_kwargs(mask_effect_id, definition.get("icon", "MOD_MASK")),
            )
            select.effect_id = mask_effect_id
            detach = row.operator(
                "fbp.set_effect_mask_target",
                text="",
                icon="UNLINKED",
                emboss=False,
            )
            detach.mask_effect_id = mask_effect_id
            detach.target_effect_id = "LAYER"
            detach.expected_target_effect_id = target_effect_id
            detach.expected_target_instance_id = target_instance_id
    else:
        attached_box.label(text="No masks attached", icon="BLANK1")

    actions = panel.row(align=False)
    add = actions.operator_menu_enum(
        "fbp.add_effect_mask",
        "mask_effect_id",
        text="Add Mask",
        icon="ADD",
    )
    add.target_effect_id = target_effect_id
    add.target_instance_id = target_instance_id
    gp = actions.operator(
        "fbp.assign_grease_pencil_mask_to_effect",
        text="",
        icon="OUTLINER_OB_GREASEPENCIL",
    )
    gp.target_effect_id = target_effect_id
    if hasattr(gp, "target_instance_id"):
        gp.target_instance_id = target_instance_id
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
    layout, context, view, *, show_view_header=False, menu_state=None,
    max_columns=None, quick_slot_index=0, quick_kind="",
):
    """Draw the curated effect library for adding or assigning quick slots."""
    rigs, active_effects = menu_state or _fbp_effect_add_menu_state(context)
    view = str(view or "2D").upper()
    quick_slot_index = max(0, int(quick_slot_index or 0))
    quick_kind = str(quick_kind or "").upper()
    quick_assignment = bool(quick_slot_index and quick_kind in {"EFFECT", "MASK"})
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

    def draw_quick_assignment(parent, effect_id, label, icon):
        row = parent.row(align=False)
        if quick_kind == "MASK":
            op = row.operator(
                "fbp.set_quick_mask_slot",
                text=str(label),
                **effect_icon_kwargs(effect_id, icon or "MOD_MASK"),
            )
            op.slot_index = quick_slot_index
            op.mask_id = str(effect_id or "")
            return
        setter = (
            "fbp.set_quick_mesh_effect_slot"
            if view == "3D" else "fbp.set_quick_image_effect_slot"
        )
        op = row.operator(
            setter,
            text=str(label),
            **effect_icon_kwargs(effect_id, icon or "MODIFIER"),
        )
        op.slot_index = quick_slot_index
        op.effect_id = str(effect_id or "")

    def draw_effect(parent, effect_token):
        effect_token = str(effect_token or "")
        if effect_token == "GREASE_PENCIL_MASK_CONTROL":
            if quick_assignment:
                draw_quick_assignment(
                    parent,
                    "GREASE_PENCIL_MASK",
                    "Grease Pencil Mask",
                    "OUTLINER_OB_GREASEPENCIL",
                )
                return
            row = parent.row(align=False)
            row.enabled = bool(rigs) and not already_on_every_selected(
                "GREASE_PENCIL_MASK"
            )
            row.operator(
                "fbp.add_grease_pencil_mask",
                text="Grease Pencil Mask",
                **effect_icon_kwargs("GREASE_PENCIL_MASK", "OUTLINER_OB_GREASEPENCIL"),
            )
            return
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
            if quick_assignment:
                draw_quick_assignment(
                    parent,
                    default_effect,
                    str(family.get("label", family_id.title()) or family_id.title()),
                    str(family.get("icon", "MODIFIER") or "MODIFIER"),
                )
                return
            already_on_all = bool(rigs) and all(
                any(variant_id in active_effects.get(_fbp_effect_ids_cache_key(rig), set()) for variant_id, _label in variants)
                for rig in rigs
            )
            row = parent.row(align=False)
            row.enabled = bool(default_effect and supported_variants and not already_on_all)
            op = row.operator(
                "fbp.add_effect_family",
                text=str(family.get("label", family_id.title()) or family_id.title()),
                **effect_icon_kwargs(
                    f"FAMILY_{family_id}",
                    str(family.get("icon", "MODIFIER") or "MODIFIER"),
                ),
            )
            op.family_id = family_id
            return
        effect_id = fbp_normalize_effect_id(effect_token)
        definition = fbp_effect_definition(effect_id)
        if quick_assignment:
            draw_quick_assignment(
                parent,
                effect_id,
                _fbp_effect_display_label(effect_id, definition),
                str(definition.get("icon", "MODIFIER") or "MODIFIER"),
            )
            return
        row = parent.row(align=False)
        supported = not rigs or all(fbp_effect_supported_for_rig(rig, effect_id) for rig in rigs)
        row.enabled = supported and not already_on_every_selected(effect_id)
        op = row.operator(
            "fbp.add_effect",
            text=_fbp_effect_display_label(effect_id, definition),
            **effect_icon_kwargs(effect_id, definition.get("icon", "MODIFIER")),
        )
        op.effect_id = effect_id

    if show_view_header:
        header = {
            "2D": ("Image Effects", "SHADERFX"),
            "MASK": ("Mask", "MOD_MASK"),
            "3D": ("Mesh Effects", "MOD_SCATTER_ON_SURFACE"),
        }[view]
        layout.label(text=header[0], icon=header[1])

    def draw_user_effects(parent):
        """Draw user effects as the final section of the fourth column."""
        custom = parent.column(align=False)
        custom.label(text="User Effects")
        custom.separator(type="LINE")
        custom_ids = _fbp_custom_effect_ids_for_view(view)
        if custom_ids:
            for effect_id in custom_ids:
                definition = fbp_effect_definition(effect_id)
                if quick_assignment:
                    draw_quick_assignment(
                        custom,
                        effect_id,
                        _fbp_effect_display_label(effect_id, definition),
                        str(definition.get("icon", "NODETREE") or "NODETREE"),
                    )
                    continue
                row = custom.row(align=False)
                supported = not rigs or all(
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
            custom.label(text="No user effects", icon="BLANK1")
        if quick_assignment:
            return
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

    # Context menus stay tall and readable: distribute complete sections over
    # two contiguous columns instead of expanding into a very wide strip.
    requested_columns = int(max_columns or 0)
    if requested_columns == 2 and len(sections) > 1:
        weights = [max(2, len(tuple(section[2] or ())) + 2) for section in sections]
        total = sum(weights)
        running = 0
        split_index = 1
        best_distance = float("inf")
        for index, weight in enumerate(weights[:-1], start=1):
            running += weight
            distance = abs((total * 0.5) - running)
            if distance < best_distance:
                best_distance = distance
                split_index = index
        draw_groups = (tuple(range(0, split_index)), tuple(range(split_index, len(sections))))
    else:
        draw_groups = tuple(tuple(group) for group in column_groups)

    # Masks are short enough to keep User Effects under Advanced; Image and
    # Mesh effects give it a column of its own at the right.
    user_in_last_column = requested_columns == 2 or view == "MASK"
    columns = layout.row(align=False)
    for column_index, section_indices in enumerate(draw_groups):
        column = columns.column(align=False)
        for local_index, section_index in enumerate(section_indices):
            if local_index:
                column.separator()
            section_label, _section_icon, effect_tokens = sections[int(section_index)]
            section = column.column(align=False)
            section.label(text=section_label)
            section.separator(type="LINE")
            for effect_token in effect_tokens:
                draw_effect(section, effect_token)
        if user_in_last_column and column_index == len(draw_groups) - 1:
            column.separator()
            draw_user_effects(column)

    if not user_in_last_column:
        user_column = columns.column(align=False)
        draw_user_effects(user_column)
