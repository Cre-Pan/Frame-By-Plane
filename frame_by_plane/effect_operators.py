"""Effect stack operators: add, remove, move, group, copy and paste effects and masks, presets, lattice tools, and the transactional helpers behind them.

Moved out of :mod:`geometry_nodes`, which re-exports every name defined here, so
``geometry_nodes.<name>`` keeps working for callers and tests.
"""

from pathlib import Path
import os
import copy
import json
import math
import tempfile
import uuid
import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Menu, Operator
from mathutils import Vector
from .constants import (
    COLLECTION_COLOR_ENUM_ITEMS,
    fbp_collection_color_icon,
)
from .ui_icons import effect_icon_kwargs, ui_icon
from .ui_style import adaptive_row, configure_layout, hint_row, section_header
from .ui_list_state import resolve_anchor_index, store_anchor
from .ui_context import restore_modal_cursor
from .transactions import FBPTransaction
from .user_storage import fbp_legacy_config_file, fbp_migrate_legacy_user_file, fbp_user_data_dir
from .effect_instances import (
    FBP_EFFECT_DATA_MODEL_VERSION,
    FBP_EFFECT_STACK_KEY,
    FBP_EFFECT_STACK_VERSION_KEY,
    effect_instance_token,
    encode_effect_stack,
    split_effect_instance_token,
)
from .effect_schema import (
    effect_instance_id,
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
    FBP_EFFECT_GLASS,
    FBP_EFFECT_CRYSTAL,
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
    FBP_EFFECT_RIM,
    FBP_EFFECT_SHADOW,
    FBP_EFFECT_GAUSSIAN_BLUR,
    FBP_EFFECT_DIRECTIONAL_BLUR,
    FBP_EFFECT_TRIANGLE_BLUR, FBP_EFFECT_TILT_SHIFT, FBP_EFFECT_UNSHARP_MASK, FBP_EFFECT_EDGE_DETECT,
    FBP_EFFECT_SMOOTH_TOON, FBP_EFFECT_ADAPTIVE_THRESHOLD, FBP_EFFECT_FALSE_COLOR, FBP_EFFECT_CHROMATIC_ABERRATION,
    FBP_EFFECT_INK, FBP_EFFECT_EDGE_WORK, FBP_EFFECT_PENCIL_SKETCH, FBP_EFFECT_POSTER_EDGES,
    FBP_EFFECT_CROSSHATCH, FBP_EFFECT_EMBOSS,
    FBP_EFFECT_LAYER_BLEND,
    FBP_EFFECT_COLOR_MASK,
    FBP_EFFECT_CRT_SCANLINES,
    FBP_EFFECT_SOLARIZE,
    FBP_EFFECT_TRITONE,
    FBP_EFFECT_FILM_FADE,
    FBP_EFFECT_DIGITAL_NOISE,
    FBP_EFFECT_HALFTONE,
    FBP_EFFECT_RISO_PRINT,
    FBP_EFFECT_OIL_PAINT,
    FBP_EFFECT_DOT_MATRIX,
    FBP_EFFECT_ASCII_MATRIX,
    FBP_EFFECT_ASCII,
    FBP_EFFECT_REGISTRY,
    FBP_SHADER_STAGE_ORDER,
    FBP_BASE_EFFECT_MENU_ORDER,
    FBP_3D_EFFECT_MENU_ORDER,
    fbp_effect_definition,
    fbp_effect_multi_instance_enabled,
    fbp_effect_supported_for_rig,
    fbp_effect_tooltip,
    fbp_normalize_effect_id,
)
from .ui_list_state import invoke_with_selection_modifiers
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_set_rna_property_silent,
    fbp_warn,
    fbp_obj_runtime_key,
    fbp_obj_runtime_token,
    fbp_find_id_by_runtime_key,
    fbp_tag_redraw
)
from .effect_ui import (  # noqa: E402
    _FBP_DEFAULT_EFFECT_MASK,
    _fbp_effect_display_label,
    _fbp_effect_mask_enum_items,
    fbp_effect_color_ramp_node,
)

from .geometry_nodes import (  # noqa: E402 - defined before geometry_nodes imports this module
    _FBP_COLOR_RAMP_SYNC_CACHE_LIMIT,
    _FBP_COLOR_RAMP_SYNC_PENDING,
    _FBP_COLOR_RAMP_SYNC_STATE_CACHE,
    _FBP_EFFECT_CLIPBOARD,
    _FBP_LATTICE_BAKED_KEY,
    _FBP_LATTICE_FLATTEN_CACHE,
    _FBP_LATTICE_MODE_KEY,
    _FBP_LOADABLE_EFFECT_IMAGES,
    _FBP_USER_PRESET_CACHE,
    _fbp_animation_key,
    _fbp_apply_custom_effect_inputs,
    _fbp_apply_effect_mask_transaction,
    _fbp_apply_geometry_material_composites,
    _fbp_apply_lattice_camera_flatten,
    _fbp_apply_lattice_corner_pin,
    _fbp_apply_lattice_effect,
    _fbp_apply_lattice_grid_settings,
    _fbp_apply_modifier_order_exact,
    _fbp_capture_custom_effect_inputs,
    _fbp_capture_multi_shader_effect_states,
    _fbp_capture_rig_targets,
    _fbp_cleanup_incomplete_lattice_setup,
    _fbp_configure_lattice_visibility,
    _fbp_effect_animation_contract,
    _fbp_effect_can_receive_mask,
    _fbp_effect_evolution_speed_property,
    _fbp_effect_group_record,
    _fbp_effect_ids_cache_key,
    _fbp_effect_is_local_mask,
    _fbp_effect_ref,
    _fbp_effect_ref_effect_id,
    _fbp_effect_ref_instance_id,
    _fbp_effect_ref_is_active,
    _fbp_effect_ref_parts,
    _fbp_effect_solo_view,
    _fbp_effect_stack_owner_id,
    _fbp_effect_uses_multi_instances,
    _fbp_effect_view_categories,
    _fbp_find_all_effect_modifiers,
    _fbp_find_shader_effect_nodes_for_rig,
    _fbp_geometry_composite_material,
    _fbp_geometry_effect_id_for_modifier,
    _fbp_geometry_modifier_instance_id,
    _fbp_get_rig_shader_stage_order,
    _fbp_get_shader_stage_order,
    _fbp_instance_channel_value_attr,
    _fbp_interface_inputs,
    _fbp_invalidate_effect_ids_cache,
    _fbp_invalidate_effect_runtime_profile,
    _fbp_invalidate_live_lattice_cache,
    _fbp_json_state_signature,
    _fbp_last_lattice_error,
    _fbp_lattice_compatibility_issue,
    _fbp_lattice_detail_modifier,
    _fbp_lattice_fit_matrix,
    _fbp_lattice_grid_loops,
    _fbp_lattice_mode,
    _fbp_lattice_modifier,
    _fbp_lattice_object,
    _fbp_lattice_runtime_key,
    _fbp_lattice_scene_camera,
    _fbp_load_effect_group,
    _fbp_mixed_effect_tokens,
    _fbp_modifier_pointer,
    _fbp_next_effect_group_name,
    _fbp_node_socket,
    _fbp_normalize_effect_refs,
    _fbp_plane,
    _fbp_plane_materials,
    _fbp_rebuild_shader_stage,
    _fbp_refresh_extrude_pixel_dependency,
    _fbp_refresh_geometry_source_materials,
    _fbp_reorder_geometry_effect_modifiers,
    _fbp_reset_custom_effect_inputs,
    _fbp_reset_lattice_points,
    _fbp_resolve_rig_targets,
    _fbp_restore_captured_shader_order,
    _fbp_restore_multi_shader_effect_states,
    _fbp_runtime_effect_ids,
    _fbp_select_effect_group_row,
    _fbp_select_effect_row,
    _fbp_select_lattice_helper,
    _fbp_selected_rigs,
    _fbp_set_enabled,
    _fbp_set_modifier_input,
    _fbp_set_rig_shader_stage_order,
    _fbp_set_shader_stage_order,
    _fbp_shader_effect_nodes,
    _fbp_shader_node_token,
    _fbp_shader_order_token_for_effect,
    _fbp_stabilize_lattice_helper,
    _fbp_store_effect_solo_ids,
    _fbp_unique_live_rigs,
    _fbp_update_lattice_data,
    fbp_active_effect_group_id,
    fbp_active_effect_id,
    fbp_active_effect_instance_id,
    fbp_add_effect,
    fbp_apply_mask_stack_snapshot,
    fbp_assign_effect_layer_seed,
    fbp_assign_mesh_wiggle_layer_seed,
    fbp_duplicate_effect_instance,
    fbp_effect_debug_mode,
    fbp_effect_group_collapsed,
    fbp_effect_group_color_tag,
    fbp_effect_group_id_for_rig,
    fbp_effect_group_members,
    fbp_effect_group_members_from_items,
    fbp_effect_group_name,
    fbp_effect_ids_for_rig,
    fbp_effect_input_source,
    fbp_effect_instance_animation_item,
    fbp_effect_instance_channel,
    fbp_effect_instance_channel_value,
    fbp_effect_instance_records_for_rig,
    fbp_effect_is_active,
    fbp_effect_mask_target_ref,
    fbp_effect_presence,
    fbp_effect_render_visible_state,
    fbp_effect_source_rig,
    fbp_effect_stack_v2_snapshot,
    fbp_effect_visible_state,
    fbp_ensure_effect_animation_state,
    fbp_ensure_effect_group_record,
    fbp_ensure_effect_instance_state,
    fbp_expand_effect_selection_to_groups,
    fbp_find_effect_modifier,
    fbp_focus_lattice_ui,
    fbp_load_active_effect_instance_settings,
    fbp_load_effect_instance_settings,
    fbp_local_effect_mask_contract_report,
    fbp_mask_stack_operation,
    fbp_mask_stack_snapshot,
    fbp_masks_targeting_effect,
    fbp_move_effect,
    fbp_move_effect_instance,
    fbp_persist_effect_stacks,
    fbp_remove_effect,
    fbp_remove_effect_instance,
    fbp_rename_effect_group_transactional,
    fbp_reset_effect_animation_state,
    fbp_selected_effect_ids,
    fbp_selected_effect_instances,
    fbp_set_effect_debug_mode,
    fbp_set_effect_global_visible,
    fbp_set_effect_group_collapsed,
    fbp_set_effect_group_color_transactional,
    fbp_set_effect_group_id,
    fbp_set_effect_input_source,
    fbp_set_effect_instance_selection,
    fbp_set_effect_mask_target,
    fbp_set_effect_render_visible,
    fbp_set_effect_selection,
    fbp_set_effect_visible,
    fbp_set_mask_stack_operation,
    fbp_sync_effect_groups,
    fbp_sync_effect_items,
    fbp_toggle_effect_solo,
    fbp_update_effect_instance_setting_value,
    fbp_update_geometry_effect,
    fbp_update_shader_effect,
)


class FBP_OT_AddEffectMask(Operator):
    bl_idname = "fbp.add_effect_mask"
    bl_label = "Add Mask to Effect"
    bl_description = "Create or attach a mask to one concrete effect instance"
    bl_options = {"REGISTER", "UNDO"}

    mask_effect_id: EnumProperty(
        name="Mask",
        description="Mask type to create or attach",
        items=_fbp_effect_mask_enum_items,
        options={"SKIP_SAVE"},
    )
    target_effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    target_instance_id: StringProperty(default="", options={"SKIP_SAVE"})

    @classmethod
    def description(cls, _context, properties):
        mask = fbp_effect_definition(getattr(properties, "mask_effect_id", ""))
        target = fbp_effect_definition(getattr(properties, "target_effect_id", ""))
        return f"Add or move {mask.get('label', 'Mask')} to {target.get('label', 'this effect')}"

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        mask_effect_id = fbp_normalize_effect_id(self.mask_effect_id)
        target_effect_id = fbp_normalize_effect_id(self.target_effect_id)
        target_instance_id = str(self.target_instance_id or "") if _fbp_effect_uses_multi_instances(target_effect_id) else ""
        target_ref = _fbp_effect_ref(target_effect_id, target_instance_id)
        if not _fbp_effect_is_local_mask(mask_effect_id) or not _fbp_effect_can_receive_mask(target_effect_id):
            return {"CANCELLED"}
        rigs = _fbp_selected_rigs(context)
        compatible = [
            rig for rig in rigs
            if _fbp_effect_ref_is_active(rig, target_ref)
            and fbp_effect_supported_for_rig(rig, mask_effect_id)
        ]
        success, changed = _fbp_apply_effect_mask_transaction(
            compatible, mask_effect_id, target_effect_id, target_instance_id,
            add_missing=True,
        )
        if not success:
            self.report({"ERROR"}, "Mask assignment failed; all selected layers were restored")
            return {"CANCELLED"}
        if compatible:
            fbp_sync_effect_items(compatible[0], rigs)
        try:
            context.scene.fbp_effect_mask_edit_target = target_ref
        except FBP_DATA_ERRORS:
            pass
        if not compatible:
            self.report({"WARNING"}, "This mask is not compatible with the selected layers")
            return {"CANCELLED"}
        return {"FINISHED"} if changed else {"CANCELLED"}



class FBP_OT_ToggleEffectMasks(Operator):
    bl_idname = "fbp.toggle_effect_masks"
    bl_label = "Enable Effect Mask"
    bl_description = "Enable or disable the mask of this effect. With no mask yet, add a Gradient Mask limited to this effect"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    target_effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    target_instance_id: StringProperty(default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        target_effect_id = fbp_normalize_effect_id(self.target_effect_id)
        target_instance_id = str(self.target_instance_id or "") if _fbp_effect_uses_multi_instances(target_effect_id) else ""
        target_ref = _fbp_effect_ref(target_effect_id, target_instance_id)
        if not _fbp_effect_can_receive_mask(target_effect_id):
            return {"CANCELLED"}
        rigs = [
            rig for rig in _fbp_selected_rigs(context)
            if _fbp_effect_ref_is_active(rig, target_ref)
        ]
        if not rigs:
            return {"CANCELLED"}
        attached = {rig: tuple(fbp_masks_targeting_effect(rig, target_effect_id, target_instance_id)) for rig in rigs}
        if not any(attached.values()):
            success, changed = _fbp_apply_effect_mask_transaction(
                rigs, _FBP_DEFAULT_EFFECT_MASK, target_effect_id, target_instance_id,
                add_missing=True,
            )
            if not success:
                self.report({"ERROR"}, "Mask assignment failed; all selected layers were restored")
                return {"CANCELLED"}
        else:
            visible = not all(
                fbp_effect_visible_state(rig, mask_id)
                for rig, masks in attached.items() for mask_id in masks
            )
            for rig, masks in attached.items():
                for mask_id in masks:
                    fbp_set_effect_visible(rig, mask_id, visible)
        fbp_sync_effect_items(rigs[0], rigs)
        return {"FINISHED"}


class FBP_OT_SetEffectMaskType(Operator):
    bl_idname = "fbp.set_effect_mask_type"
    bl_label = "Mask Type"
    bl_description = "Choose the mask of this effect. It replaces a single attached mask, or adds one more when several are attached"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    mask_effect_id: EnumProperty(
        name="Mask",
        description="Mask type limited to this effect",
        items=_fbp_effect_mask_enum_items,
        options={"SKIP_SAVE"},
    )
    target_effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    target_instance_id: StringProperty(default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        mask_effect_id = fbp_normalize_effect_id(self.mask_effect_id)
        target_effect_id = fbp_normalize_effect_id(self.target_effect_id)
        target_instance_id = str(self.target_instance_id or "") if _fbp_effect_uses_multi_instances(target_effect_id) else ""
        target_ref = _fbp_effect_ref(target_effect_id, target_instance_id)
        if not _fbp_effect_is_local_mask(mask_effect_id) or not _fbp_effect_can_receive_mask(target_effect_id):
            return {"CANCELLED"}
        rigs = [
            rig for rig in _fbp_selected_rigs(context)
            if _fbp_effect_ref_is_active(rig, target_ref)
            and fbp_effect_supported_for_rig(rig, mask_effect_id)
        ]
        if not rigs:
            self.report({"WARNING"}, "This mask is not compatible with the selected layers")
            return {"CANCELLED"}
        if not fbp_set_effect_mask_type(rigs, mask_effect_id, target_effect_id, target_instance_id):
            self.report({"ERROR"}, "Mask assignment failed; all selected layers were restored")
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        return {"FINISHED"}


def fbp_set_effect_mask_type(rigs, mask_effect_id, target_effect_id, target_instance_id=""):
    """Make ``mask_effect_id`` the mask of one effect on every layer.

    A single previously attached mask of another type is replaced; when an
    effect already combines several masks the new one is added to them.
    """
    mask_effect_id = fbp_normalize_effect_id(mask_effect_id)
    replaced = []
    for rig in tuple(rigs or ()):
        attached = tuple(fbp_masks_targeting_effect(rig, target_effect_id, target_instance_id))
        if len(attached) == 1 and attached[0] != mask_effect_id:
            replaced.append((rig, attached[0]))
    success, _changed = _fbp_apply_effect_mask_transaction(
        rigs, mask_effect_id, target_effect_id, target_instance_id, add_missing=True,
    )
    if not success:
        return False
    for rig, old_mask in replaced:
        fbp_remove_effect(rig, old_mask, sync_items=False)
    return True


class FBP_OT_SetEffectMaskTarget(Operator):
    bl_idname = "fbp.set_effect_mask_target"
    bl_label = "Attach or Detach Mask"
    bl_description = "Attach this mask to one concrete effect instance or return it to the layer"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    mask_effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    target_effect_id: StringProperty(default="LAYER", options={"SKIP_SAVE"})
    target_instance_id: StringProperty(default="", options={"SKIP_SAVE"})
    expected_target_effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    expected_target_instance_id: StringProperty(default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        mask_effect_id = fbp_normalize_effect_id(self.mask_effect_id)
        target_effect_id = fbp_normalize_effect_id(self.target_effect_id) or "LAYER"
        target_instance_id = str(self.target_instance_id or "") if _fbp_effect_uses_multi_instances(target_effect_id) else ""
        target_ref = "LAYER" if target_effect_id == "LAYER" else _fbp_effect_ref(target_effect_id, target_instance_id)
        expected_effect = fbp_normalize_effect_id(self.expected_target_effect_id)
        expected_instance = str(self.expected_target_instance_id or "") if _fbp_effect_uses_multi_instances(expected_effect) else ""
        expected_ref = _fbp_effect_ref(expected_effect, expected_instance) if expected_effect else ""
        eligible = [
            rig for rig in rigs
            if fbp_effect_is_active(rig, mask_effect_id)
            and (not expected_ref or fbp_effect_mask_target_ref(rig, mask_effect_id) == expected_ref)
            and (target_ref == "LAYER" or _fbp_effect_ref_is_active(rig, target_ref))
        ]
        success, changed = _fbp_apply_effect_mask_transaction(
            eligible, mask_effect_id, target_effect_id, target_instance_id,
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
    bl_description = 'Make this effect the active row in the Frame By Plane effect stack'
    bl_options = {"INTERNAL"}

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", name="Effect ID", default="", options={"SKIP_SAVE"})
    instance_id: StringProperty(description="Persistent identity of one concrete effect instance.", name="Instance ID", default="", options={"SKIP_SAVE"})
    use_shift: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    use_ctrl: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def description(cls, _context, properties):
        return fbp_effect_tooltip(getattr(properties, "effect_id", ""))

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def invoke(self, context, event):
        return invoke_with_selection_modifiers(self, context, event)

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
        if not _fbp_select_effect_row(
            rig, effect_id, rigs, instance_id=str(self.instance_id or "")
        ):
            return {"CANCELLED"}
        if self.instance_id:
            fbp_load_effect_instance_settings(rig, effect_id, self.instance_id)

        target_index = int(getattr(rig, "fbp_effects_index", 0) or 0)
        anchor_key = "_fbp_effect_selection_anchor"
        anchor_uid_key = "_fbp_effect_selection_anchor_uid"
        anchor = resolve_anchor_index(
            rig, anchor_key, anchor_uid_key, rig.fbp_effects,
            "row_uid", fallback=target_index,
        )
        visible_categories = _fbp_effect_view_categories(context)
        eligible = []
        for index, item in enumerate(rig.fbp_effects):
            if str(getattr(item, "row_type", "EFFECT") or "EFFECT") != "EFFECT":
                continue
            candidate_id = fbp_normalize_effect_id(getattr(item, "effect_id", ""))
            candidate_instance_id = str(getattr(item, "instance_id", "") or "")
            candidate_token = (
                effect_instance_token(candidate_id, candidate_instance_id)
                if candidate_instance_id else candidate_id
            )
            candidate_category = str(
                fbp_effect_definition(candidate_id).get("category", "2D") or "2D"
            )
            if candidate_id and candidate_category in visible_categories:
                eligible.append((index, candidate_id, candidate_token, item))
        if self.use_shift:
            lo, hi = sorted((max(0, anchor), target_index))
            range_tokens = [
                candidate_token for index, _candidate_id, candidate_token, _item in eligible
                if lo <= index <= hi
            ]
            fbp_set_effect_instance_selection(
                rig,
                range_tokens,
                mode="ADD" if self.use_ctrl else "REPLACE",
                eligible_tokens=[token for _i, _candidate_id, token, _item in eligible],
            )
        elif self.use_ctrl:
            target = next(
                (item for index, _candidate_id, _token, item in eligible if index == target_index),
                None,
            )
            if target is not None:
                target.is_selected = not bool(target.is_selected)
        else:
            target_token = effect_instance_token(effect_id, self.instance_id) if self.instance_id else effect_id
            fbp_set_effect_instance_selection(
                rig,
                (target_token,),
                mode="REPLACE",
                eligible_tokens=[token for _i, _candidate_id, token, _item in eligible],
            )
        if not self.use_shift:
            store_anchor(
                rig, anchor_key, anchor_uid_key, rig.fbp_effects,
                "row_uid", target_index,
            )
        return {"FINISHED"}


class FBP_OT_AddEffect(Operator):
    bl_idname = "fbp.add_effect"
    bl_label = "Add Frame By Plane Effect"
    bl_description = "Add the chosen effect to all compatible selected layers"
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
        if len(compatible) != len(rigs):
            incompatible = [getattr(rig, "name", "Layer") for rig in rigs if rig not in compatible]
            names = ", ".join(incompatible[:3])
            if len(incompatible) > 3:
                names += f" +{len(incompatible) - 3}"
            self.report(
                {"ERROR"},
                f"{definition.get('label', self.effect_id)} is not compatible with: {names}",
            )
            return {"CANCELLED"}
        tokens_before = {
            rig: frozenset(_fbp_mixed_effect_tokens(rig)) for rig in compatible
        }
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
        # New effects appear at the top of the visible layer stack, unless they
        # joined the active group, which already placed them inside it. The
        # mixed pipeline converts that UI order to Blender's bottom-to-top
        # evaluation order and builds the required Image/Geometry adapter stages.
        for rig in changed_rigs:
            order = list(_fbp_mixed_effect_tokens(rig))
            matches = [
                token for token in order
                if _fbp_effect_ref_effect_id(token) == requested_id
            ]
            # Prefer the row this Add created; re-adding an existing effect
            # brings its first row to the top as before.
            target = next(
                (token for token in matches if token not in tokens_before[rig]),
                matches[0] if matches else "",
            )
            if target and order[0] != target and not fbp_effect_group_id_for_rig(
                rig,
                requested_id,
                instance_id=_fbp_effect_ref_instance_id(target),
                normalize=False,
            ):
                desired = [target] + [
                    token for token in order if token != target
                ]
                _fbp_apply_mixed_effect_order(rig, desired)
        # Spatial helper objects must be created inside this operator's Undo
        # transaction. The selected-row callback runs later on a timer and now
        # only reveals existing helpers; it never creates datablocks after the
        # Undo step has already been committed.
        try:
            from .effect_controls import sync_controls_from_properties
            for rig in changed_rigs:
                sync_controls_from_properties(rig, requested_id, create=True)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

        active_rig = rigs[0]
        try:
            category = str(definition.get("category", "2D") or "2D")
            context.scene.fbp_effects_view = "3D" if category == "3D" else ("MASK" if category == "MASK" else "2D")
        except FBP_DATA_ERRORS:
            pass
        fbp_persist_effect_stacks(changed_rigs)
        fbp_sync_effect_items(
            active_rig, rigs, repair_assets=False, normalize_instance_ids=False
        )
        effect_id = requested_id
        new_instance = next(
            (
                _fbp_effect_ref_instance_id(token)
                for token in _fbp_mixed_effect_tokens(active_rig)
                if token not in tokens_before.get(active_rig, ())
                and _fbp_effect_ref_effect_id(token) == effect_id
            ),
            "",
        )
        for index, item in enumerate(getattr(active_rig, "fbp_effects", ())):
            if (
                fbp_normalize_effect_id(getattr(item, "effect_id", "")) == effect_id
                and (not new_instance or getattr(item, "instance_id", "") == new_instance)
            ):
                active_rig.fbp_effects_index = index
                break
        # Reveal shader-only results once, as part of the explicit Add action.
        # Row/tab selection and later redraws never force the artist's shading.
        try:
            from .properties import fbp_ensure_effect_preview_mode
            fbp_ensure_effect_preview_mode(context, effect_id)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
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
        source_token = _fbp_shader_order_token_for_effect(source, effect_id, source_order)
        if not source_token:
            return False
        desired_rank = source_order.index(source_token)
        changed = False
        final_order = None
        for material in target_materials:
            order = _fbp_get_shader_stage_order(material, stage)
            target_token = _fbp_shader_order_token_for_effect(target, effect_id, order)
            if not target_token:
                continue
            order.remove(target_token)
            order.insert(min(desired_rank, len(order)), target_token)
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
            current_rank = target_effect_modifiers.index(target_modifier)
            if current_rank != desired_rank:
                requested = list(target_effect_modifiers)
                requested.pop(current_rank)
                requested.insert(desired_rank, target_modifier)
                return _fbp_reorder_geometry_effect_modifiers(
                    target_plane, requested
                )
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
    FBP_EFFECT_RIM: {
        "Soft Inner": {"fbp_rim_mode": "INNER", "fbp_rim_blend_mode": "NORMAL", "fbp_rim_width": 0.012, "fbp_rim_expand": 0.004, "fbp_rim_blur": 0.025, "fbp_rim_softness": 0.75, "fbp_rim_intensity": 0.75, "fbp_rim_color": (0.75, 0.9, 1.0, 1.0)},
        "GP Outer": {"fbp_rim_mode": "OUTER", "fbp_rim_blend_mode": "NORMAL", "fbp_rim_width": 0.015, "fbp_rim_expand": 0.008, "fbp_rim_blur": 0.012, "fbp_rim_softness": 0.55, "fbp_rim_intensity": 1.0, "fbp_rim_color": (1.0, 0.32, 0.06, 1.0)},
        "Neon Both": {"fbp_rim_mode": "BOTH", "fbp_rim_blend_mode": "ADD", "fbp_rim_width": 0.01, "fbp_rim_expand": 0.015, "fbp_rim_blur": 0.04, "fbp_rim_softness": 1.0, "fbp_rim_intensity": 1.2, "fbp_rim_color": (0.05, 0.65, 1.0, 1.0)},
    },
    FBP_EFFECT_GLASS: {
        "Cracked": {"fbp_glass_pattern": "IMPACT", "fbp_glass_shatter": 0.25, "fbp_glass_spread": 1.0, "fbp_glass_gap": 0.05, "fbp_glass_explode": 0.0, "fbp_glass_depth": 0.03, "fbp_glass_fall": 0.0, "fbp_glass_spin": 0.03},
        "Shattered": {"fbp_glass_pattern": "IMPACT", "fbp_glass_shatter": 0.65, "fbp_glass_spread": 0.75, "fbp_glass_gap": 0.15, "fbp_glass_explode": 0.35, "fbp_glass_depth": 0.4, "fbp_glass_fall": 0.0, "fbp_glass_spin": 0.5},
        "Falling Shards": {"fbp_glass_pattern": "SHARDS", "fbp_glass_shatter": 0.7, "fbp_glass_spread": 0.3, "fbp_glass_gap": 0.08, "fbp_glass_explode": 0.08, "fbp_glass_depth": 0.15, "fbp_glass_fall": 0.9, "fbp_glass_spin": 0.6},
        "Glass Pane": {"fbp_glass_use_glass": True, "fbp_glass_pattern": "IMPACT", "fbp_glass_shatter": 0.35, "fbp_glass_thickness": 0.02, "fbp_glass_roughness": 0.04, "fbp_glass_ior": 1.45, "fbp_glass_source_color": 0.6, "fbp_glass_tint": (0.9, 0.97, 1.0, 1.0)},
    },
    FBP_EFFECT_CRYSTAL: {
        "Diamond Cave": {"fbp_crystal_texture_type": "VORONOI", "fbp_crystal_pattern_mode": "DIAMOND", "fbp_crystal_depth": 0.18, "fbp_crystal_roundness": 0.7, "fbp_crystal_blur_iterations": 10, "fbp_crystal_pattern_scale": 9.0, "fbp_crystal_pattern_detail": 7.0, "fbp_crystal_pattern_strength": 0.055, "fbp_crystal_roughness": 0.08, "fbp_crystal_ior": 1.47, "fbp_crystal_tint": (0.36, 0.78, 1.0, 1.0), "fbp_crystal_absorption": 0.9},
        "Clay Crystal": {"fbp_crystal_texture_type": "VORONOI", "fbp_crystal_pattern_mode": "CRYSTAL", "fbp_crystal_depth": 0.22, "fbp_crystal_roundness": 0.95, "fbp_crystal_blur_iterations": 14, "fbp_crystal_pattern_scale": 5.0, "fbp_crystal_pattern_detail": 3.0, "fbp_crystal_pattern_strength": 0.035, "fbp_crystal_surface_subdivision": 1, "fbp_crystal_roughness": 0.18, "fbp_crystal_tint": (0.55, 0.42, 0.95, 1.0)},
        "Liquid Crystal": {"fbp_crystal_texture_type": "VORONOI", "fbp_crystal_pattern_mode": "LIQUID", "fbp_crystal_depth": 0.1, "fbp_crystal_roundness": 0.9, "fbp_crystal_blur_iterations": 12, "fbp_crystal_pattern_scale": 7.0, "fbp_crystal_pattern_detail": 5.0, "fbp_crystal_pattern_strength": 0.045, "fbp_crystal_distortion": 1.5, "fbp_crystal_roughness": 0.03, "fbp_crystal_ior": 1.42, "fbp_crystal_tint": (0.42, 0.92, 0.88, 1.0), "fbp_crystal_absorption": 0.45},
        "Fractal Geode": {"fbp_crystal_texture_type": "NOISE", "fbp_crystal_depth": 0.16, "fbp_crystal_roundness": 0.82, "fbp_crystal_pattern_scale": 6.5, "fbp_crystal_pattern_detail": 8.0, "fbp_crystal_pattern_strength": 0.06, "fbp_crystal_distortion": 1.25, "fbp_crystal_roughness": 0.16, "fbp_crystal_tint": (0.52, 0.35, 0.95, 1.0)},
        "Banded Quartz": {"fbp_crystal_texture_type": "WAVE", "fbp_crystal_depth": 0.14, "fbp_crystal_roundness": 0.9, "fbp_crystal_pattern_scale": 5.0, "fbp_crystal_pattern_detail": 4.0, "fbp_crystal_pattern_strength": 0.045, "fbp_crystal_distortion": 0.9, "fbp_crystal_roughness": 0.1, "fbp_crystal_tint": (0.86, 0.72, 1.0, 1.0)},
        "Prism Blocks": {"fbp_crystal_texture_type": "BRICK", "fbp_crystal_depth": 0.2, "fbp_crystal_roundness": 0.72, "fbp_crystal_pattern_scale": 10.0, "fbp_crystal_pattern_detail": 2.0, "fbp_crystal_pattern_strength": 0.07, "fbp_crystal_distortion": 0.75, "fbp_crystal_roughness": 0.06, "fbp_crystal_tint": (0.4, 0.8, 1.0, 1.0)},
    },
    FBP_EFFECT_COLOR_MASK: {
        "Green Screen": {"fbp_color_mask_color": (0.0, 1.0, 0.0, 1.0), "fbp_color_mask_tolerance": 0.20, "fbp_color_mask_softness": 0.08, "fbp_color_mask_factor": 1.0, "fbp_color_mask_invert": True, "fbp_color_mask_despill": 0.65},
        "Blue Screen": {"fbp_color_mask_color": (0.0, 0.18, 1.0, 1.0), "fbp_color_mask_tolerance": 0.20, "fbp_color_mask_softness": 0.08, "fbp_color_mask_factor": 1.0, "fbp_color_mask_invert": True, "fbp_color_mask_despill": 0.55},
        "Keep Color": {"fbp_color_mask_tolerance": 0.12, "fbp_color_mask_softness": 0.08, "fbp_color_mask_factor": 1.0, "fbp_color_mask_invert": False, "fbp_color_mask_despill": 0.0},
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
    FBP_EFFECT_OIL_PAINT: {
        "Impasto": {"fbp_oil_paint_radius": 8.0, "fbp_oil_paint_sharpness": 10.0, "fbp_oil_paint_anisotropy": 2.0, "fbp_oil_paint_factor": 1.0},
        "Soft Gouache": {"fbp_oil_paint_radius": 4.0, "fbp_oil_paint_sharpness": 4.0, "fbp_oil_paint_anisotropy": 0.5, "fbp_oil_paint_factor": 1.0},
    },
    FBP_EFFECT_RISO_PRINT: {
        "Pink & Blue": {"fbp_riso_ink_1": (1.0, 0.27, 0.55, 1.0), "fbp_riso_ink_2": (0.0, 0.47, 0.75, 1.0), "fbp_riso_use_ink_3": False, "fbp_riso_misregistration": 4.0, "fbp_riso_halftone": 0.6, "fbp_riso_dot_size": 6.0, "fbp_riso_grain": 0.35},
        "Three Drum": {"fbp_riso_ink_1": (1.0, 0.27, 0.55, 1.0), "fbp_riso_ink_2": (0.0, 0.47, 0.75, 1.0), "fbp_riso_ink_3": (1.0, 0.9, 0.0, 1.0), "fbp_riso_use_ink_3": True, "fbp_riso_misregistration": 3.0, "fbp_riso_halftone": 0.75, "fbp_riso_dot_size": 5.0, "fbp_riso_grain": 0.3},
        "Green & Orange": {"fbp_riso_ink_1": (1.0, 0.42, 0.13, 1.0), "fbp_riso_ink_2": (0.0, 0.66, 0.36, 1.0), "fbp_riso_use_ink_3": False, "fbp_riso_misregistration": 6.0, "fbp_riso_halftone": 0.4, "fbp_riso_dot_size": 8.0, "fbp_riso_grain": 0.5},
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
        "BW Light": {"fbp_halftone_pattern": "DOT", "fbp_halftone_color_mode": "BW_LIGHT", "fbp_halftone_scale": 95.0, "fbp_halftone_dot_size": 1.0, "fbp_halftone_dot_scale": 0.9, "fbp_halftone_blend": 0.0, "fbp_halftone_softness": 0.12},
        "Blended CMYK": {"fbp_halftone_pattern": "BLENDED", "fbp_halftone_color_mode": "CMYK", "fbp_halftone_scale": 70.0, "fbp_halftone_dot_size": 0.95, "fbp_halftone_dot_scale": 0.82, "fbp_halftone_blend": 0.65, "fbp_halftone_softness": 0.44, "fbp_halftone_rotation": -0.45},
        "BW Dark": {"fbp_halftone_pattern": "BLENDED", "fbp_halftone_color_mode": "BW_DARK", "fbp_halftone_scale": 80.0, "fbp_halftone_dot_size": 0.9, "fbp_halftone_dot_scale": 0.85, "fbp_halftone_blend": 0.55, "fbp_halftone_softness": 0.32},
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
    names = list((definition.get("property_map", {}) or {}))
    names.extend(definition.get("extra_properties", ()))
    if definition.get("evolve_property"):
        names.extend(
            _fbp_animation_key(effect_id, suffix)
            for suffix in ("evolve", "step", "seed", "unique", "layer_seed", "amount", "loop")
        )
        names.append(_fbp_effect_evolution_speed_property(effect_id, definition))
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
            # The silent setter returns False both for an assignment failure
            # and for an already-equal value. Preset/clipboard restore treats
            # the latter as success: default-valued properties are a normal
            # part of every complete effect snapshot.
            fbp_set_rna_property_silent(rig, prop_name, value)
            return (
                _fbp_serialize_value(getattr(rig, prop_name))
                == _fbp_serialize_value(value)
            )
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

    source_name = str(getattr(source_rig, "name", "") or "")
    _FBP_COLOR_RAMP_SYNC_PENDING[key] = (state, target_descriptors, source_name)

    def _sync_latest():
        payload = _FBP_COLOR_RAMP_SYNC_PENDING.pop(key, None)
        if not payload:
            return None
        latest_state, descriptors, stored_source_name = payload
        current_source = fbp_find_id_by_runtime_key(
            bpy.data.objects, source_key, stored_source_name
        )
        if current_source is None:
            return None
        live_targets = []
        for runtime_key, name in descriptors:
            target = fbp_find_id_by_runtime_key(
                bpy.data.objects, runtime_key, name
            )
            if target is not None:
                live_targets.append(target)
        _fbp_apply_effect_color_ramp_to_rigs(
            current_source, effect_id, live_targets, latest_state
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
            _FBP_COLOR_RAMP_SYNC_PENDING.pop(key, None)
            return False
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
    definition = fbp_effect_definition(effect_id)
    # Capturing is read-only. Normalizing a logical row without an instance id
    # would copy one instance's group onto every duplicate of the effect.
    group_id = fbp_effect_group_id_for_rig(rig, effect_id, normalize=False)
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
        "mask_target": fbp_effect_mask_target_ref(rig, effect_id) if _fbp_effect_is_local_mask(effect_id) else "LAYER",
        "mask_operation": (
            fbp_mask_stack_operation(rig, effect_id)
            if str(definition.get("stage", "") or "") == "MASK"
            else "INTERSECT"
        ),
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
        if str(definition.get("stage", "") or "") == "MASK":
            fbp_set_mask_stack_operation(
                rig,
                effect_id,
                state.get("mask_operation", "INTERSECT"),
                rebuild=False,
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


def fbp_apply_effect_state_snapshot(rig, state, *, sync_items=True):
    """Apply one validated public effect snapshot transactionally."""
    return _fbp_apply_effect_state(
        rig,
        state,
        sync_items=sync_items,
        defer_shader_rebuild=False,
        _allow_rollback=True,
    )


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
            current_keys = [
                _fbp_modifier_pointer(modifier)
                for modifier in current_effect_modifiers
            ]
            desired_keys = [
                _fbp_modifier_pointer(modifier) for modifier in ordered
            ]
            if current_keys != desired_keys:
                changed = _fbp_reorder_geometry_effect_modifiers(
                    plane, ordered
                ) or changed
        except FBP_DATA_ERRORS:
            pass
    return changed


FBP_EFFECT_STACK_PRESET_SCHEMA_VERSION = 1


def fbp_capture_effect_stack_snapshot(rig):
    """Capture a complete, JSON-safe stack for project and shared presets."""
    effect_ids = tuple(fbp_effect_ids_for_rig(rig))
    effects = [
        _fbp_capture_effect_state(rig, effect_id)
        for effect_id in effect_ids
    ]
    multi_shader = _fbp_capture_multi_shader_effect_states(rig)
    for effect_id, states in dict(multi_shader.get("effects", {}) or {}).items():
        for state in states:
            instance_id = str(state.get("instance_id", "") or "")
            state["properties"] = _fbp_capture_effect_instance_properties(
                rig,
                effect_id,
                instance_id,
            )
    groups = []
    try:
        for record in tuple(getattr(rig, "fbp_effect_groups", ()) or ()):
            group_id = str(getattr(record, "group_id", "") or "")
            if not group_id:
                continue
            groups.append(
                {
                    "group_id": group_id,
                    "name": str(getattr(record, "group_name", "") or ""),
                    "collapsed": bool(getattr(record, "collapsed", False)),
                    "color_tag": str(
                        getattr(record, "color_tag", "NONE") or "NONE"
                    ),
                }
            )
    except FBP_DATA_ERRORS:
        groups = []
    return {
        "schema": FBP_EFFECT_STACK_PRESET_SCHEMA_VERSION,
        "effects": effects,
        "multi_shader": multi_shader,
        "data_model": fbp_effect_stack_v2_snapshot(rig, ensure=False),
        "groups": groups,
        "mask_stack": fbp_mask_stack_snapshot(rig),
    }


def _fbp_remap_preset_multi_instances(payload):
    result = copy.deepcopy(dict(payload or {}))
    instance_map = {}
    effects = dict(result.get("effects", {}) or {})
    for effect_id, states in effects.items():
        normalized_effect = fbp_normalize_effect_id(effect_id)
        for state in list(states or ()):
            old_id = str(state.get("instance_id", "") or "")
            new_id = new_effect_instance_id(normalized_effect)
            if old_id:
                instance_map[(normalized_effect, old_id)] = new_id
            state["instance_id"] = new_id
    orders = dict(result.get("orders", {}) or {})
    for stage, tokens in tuple(orders.items()):
        remapped = []
        for token in list(tokens or ()):
            effect_id, instance_id = split_effect_instance_token(str(token or ""))
            mapped = instance_map.get(
                (fbp_normalize_effect_id(effect_id), instance_id),
                instance_id,
            )
            remapped.append(effect_instance_token(effect_id, mapped))
        orders[stage] = remapped
    result["effects"] = effects
    result["orders"] = orders
    return result, instance_map


def _fbp_apply_preset_group_metadata(rig, payload, instance_map):
    groups = {
        str(item.get("group_id", "") or ""): dict(item)
        for item in list(payload.get("groups", ()) or ())
        if isinstance(item, dict) and str(item.get("group_id", "") or "")
    }
    source_records = list(
        dict(payload.get("data_model", {}) or {}).get("instances", ()) or ()
    )
    target_records = list(
        fbp_effect_instance_records_for_rig(
            rig,
            ensure=True,
            sync_storage=False,
        )
    )
    targets_by_effect = {}
    for record in target_records:
        effect_id = fbp_normalize_effect_id(record.get("effect_id", ""))
        targets_by_effect.setdefault(effect_id, []).append(record)
    source_offsets = {}
    assignments = []
    for source in source_records:
        if not isinstance(source, dict):
            continue
        effect_id = fbp_normalize_effect_id(source.get("effect_id", ""))
        if not effect_id:
            continue
        source_instance = str(source.get("instance_id", "") or "")
        target_instance = instance_map.get((effect_id, source_instance), "")
        if not target_instance:
            offset = source_offsets.get(effect_id, 0)
            candidates = targets_by_effect.get(effect_id, ())
            target_instance = (
                str(candidates[offset].get("instance_id", "") or "")
                if offset < len(candidates)
                else ""
            )
            source_offsets[effect_id] = offset + 1
        assignments.append(
            (effect_id, target_instance, str(source.get("group_id", "") or ""))
        )
    # The captured records decide membership for every applied row. Rebuilt
    # MULTI instances can inherit a provisional group while they are restored;
    # clear those first so a split group never absorbs the rows between.
    for effect_id, target_instance, group_id in assignments:
        if not group_id and fbp_effect_group_id_for_rig(
            rig, effect_id, instance_id=target_instance, normalize=False
        ):
            fbp_set_effect_group_id(
                rig, effect_id, "", instance_id=target_instance
            )
    for effect_id, target_instance, group_id in assignments:
        if not group_id:
            continue
        group = groups.get(group_id, {})
        fbp_set_effect_group_id(
            rig,
            effect_id,
            group_id,
            instance_id=target_instance,
            group_name=str(group.get("name", "") or ""),
        )
    for group_id, group in groups.items():
        record = fbp_ensure_effect_group_record(
            rig,
            group_id,
            str(group.get("name", "") or ""),
        )
        if record is None:
            continue
        try:
            record.collapsed = bool(group.get("collapsed", False))
            color_tag = str(group.get("color_tag", "NONE") or "NONE")
            if color_tag in {str(item[0]) for item in COLLECTION_COLOR_ENUM_ITEMS}:
                record.color_tag = color_tag
        except FBP_DATA_ERRORS:
            continue
    fbp_sync_effect_groups(rig)


def _fbp_snapshot_mixed_order(payload, instance_map):
    """Return the captured Image / Mask / Mesh UI order with remapped instances.

    The Effect Data Model records in ``data_model`` are stored in stack order,
    so presets saved before this order was restored still carry it.
    """
    records = dict(payload.get("data_model", {}) or {}).get("instances", ()) or ()
    tokens = []
    for record in records:
        if not isinstance(record, dict):
            continue
        effect_id = fbp_normalize_effect_id(record.get("effect_id", ""))
        if not effect_id or effect_id == FBP_EFFECT_LAYER_BLEND:
            continue
        instance_id = ""
        if _fbp_effect_uses_multi_instances(effect_id):
            instance_id = instance_map.get(
                (effect_id, str(record.get("instance_id", "") or "")), ""
            )
            if not instance_id:
                continue
        token = _fbp_effect_ref(effect_id, instance_id)
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _fbp_restore_snapshot_mixed_order(rig, payload, instance_map):
    """Reorder pasted/preset rows to the captured order, in their own slots.

    Rows that already existed only on the target (Merge mode) keep their
    positions; the captured rows fill the remaining slots in captured order.
    """
    current = _fbp_mixed_effect_tokens(rig)
    present = set(current)
    wanted = [
        token for token in _fbp_snapshot_mixed_order(payload, instance_map)
        if token in present
    ]
    if len(wanted) < 2:
        return False
    wanted_set = set(wanted)
    ordered = iter(wanted)
    desired = [
        next(ordered) if token in wanted_set else token
        for token in current
    ]
    if desired == current:
        return False
    return _fbp_apply_mixed_effect_order(rig, desired)


def fbp_apply_effect_stack_snapshot(
    rig,
    payload,
    *,
    mode="REPLACE",
    _allow_rollback=True,
):
    """Apply a complete preset transactionally in Replace or Merge mode."""
    result = {
        "success": False,
        "applied": 0,
        "removed": 0,
        "error": "",
    }
    if rig is None or not isinstance(payload, dict):
        result["error"] = "Missing target layer or preset payload"
        return result
    try:
        schema = int(payload.get("schema", 0) or 0)
    except (TypeError, ValueError):
        schema = 0
    if schema != FBP_EFFECT_STACK_PRESET_SCHEMA_VERSION:
        result["error"] = (
            f"Unsupported Effect Stack Preset schema {schema}"
        )
        return result
    states = list(payload.get("effects", ()) or ())
    if not isinstance(payload.get("effects", ()), (list, tuple)):
        result["error"] = "Effect Stack Preset effects must be an array"
        return result
    invalid = [
        index
        for index, state in enumerate(states)
        if not _fbp_validate_effect_state_for_rig(rig, state)
    ]
    if invalid:
        result["error"] = (
            "Preset contains invalid or incompatible effect rows: "
            + ", ".join(str(index + 1) for index in invalid)
        )
        return result
    mode = str(mode or "REPLACE").upper()
    if mode not in {"REPLACE", "MERGE"}:
        result["error"] = f"Unsupported apply mode {mode}"
        return result

    backup = (
        fbp_capture_effect_stack_snapshot(rig)
        if _allow_rollback
        else None
    )
    try:
        desired_ids = {
            fbp_normalize_effect_id(state.get("effect_id", ""))
            for state in states
        }
        if mode == "REPLACE":
            for effect_id in tuple(fbp_effect_ids_for_rig(rig)):
                if effect_id not in desired_ids:
                    result["removed"] += int(
                        fbp_remove_effect(
                            rig,
                            effect_id,
                            sync_items=False,
                        )
                    )

        for state in states:
            if not _fbp_apply_effect_state(
                rig,
                state,
                sync_items=False,
                defer_shader_rebuild=True,
            ):
                raise RuntimeError(
                    f"Could not apply {state.get('effect_id', 'effect')}"
                )
            result["applied"] += 1

        multi_payload, instance_map = _fbp_remap_preset_multi_instances(
            payload.get("multi_shader", {})
        )
        for effect_id, instance_states in dict(
            multi_payload.get("effects", {}) or {}
        ).items():
            if not instance_states:
                continue
            _fbp_restore_multi_shader_effect_states(
                rig,
                effect_id,
                instance_states,
            )
            for state in instance_states:
                _fbp_apply_effect_instance_properties(
                    rig,
                    effect_id,
                    str(state.get("instance_id", "") or ""),
                    state.get("properties", {}),
                )

        for state in states:
            effect_id = fbp_normalize_effect_id(state.get("effect_id", ""))
            if _fbp_effect_is_local_mask(effect_id):
                # Pasted MULTI instances receive new ids; follow the receiver.
                target_effect, target_instance = _fbp_effect_ref_parts(
                    state.get("mask_target", "LAYER")
                )
                target_instance = instance_map.get(
                    (target_effect, target_instance), target_instance
                )
                fbp_set_effect_mask_target(
                    rig,
                    effect_id,
                    _fbp_effect_ref(target_effect, target_instance) if target_effect else "LAYER",
                )
        mask_stack_payload = payload.get("mask_stack")
        if isinstance(mask_stack_payload, dict):
            if not fbp_apply_mask_stack_snapshot(
                rig,
                mask_stack_payload,
                rebuild=False,
            ):
                raise RuntimeError("Could not restore Mask Stack metadata")
        _fbp_restore_captured_shader_order(rig, multi_payload)
        _fbp_apply_captured_stack_order(
            rig,
            states,
            force_shader_rebuild=True,
        )
        # Restore the captured order first: group metadata is normalized into
        # contiguous blocks, so applying it to a differently ordered stack
        # would also capture the rows that currently sit between members.
        _fbp_restore_snapshot_mixed_order(rig, payload, instance_map)
        _fbp_apply_preset_group_metadata(rig, payload, instance_map)
        # Merge mode replaces a target's own MULTI instances; masks that were
        # attached to them return to the layer instead of dangling.
        fbp_local_effect_mask_contract_report(rig, repair=True)
        # Paste/preset is a one-shot batch: rebuild every stage once so mask
        # combinations follow the final order regardless of application order.
        for material in _fbp_plane_materials(rig):
            for stage in ("UV", "COLOR", "MASK"):
                _fbp_rebuild_shader_stage(material, stage)
        _fbp_refresh_mixed_pipeline(rig)
        fbp_effect_instance_records_for_rig(
            rig,
            ensure=True,
            sync_storage=True,
        )
        fbp_sync_effect_items(
            rig,
            repair_assets=False,
            normalize_instance_ids=False,
        )
        result["success"] = True
        return result
    except (
        AttributeError,
        ReferenceError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        if backup is not None:
            rollback = fbp_apply_effect_stack_snapshot(
                rig,
                backup,
                mode="REPLACE",
                _allow_rollback=False,
            )
            if not rollback.get("success", False):
                result["error"] += (
                    f"; rollback failed: {rollback.get('error', 'unknown')}"
                )
        return result


def _fbp_user_preset_path():
    root = fbp_user_data_dir("presets")
    if not root:
        # Without a user folder, presets last for this session only.
        root = os.path.join(tempfile.gettempdir(), "frame_by_plane_presets")
    path = Path(root) / "effect_presets.json"
    fbp_migrate_legacy_user_file(path, fbp_legacy_config_file("effect_presets.json"))
    return path


def _fbp_user_preset_stamp(path):
    try:
        stat = path.stat()
        return (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return None


def _fbp_load_user_presets(*, mutable=True):
    """Read user presets once per file revision.

    Read-only callers such as menu drawing can reuse the cached mapping without
    deep-copying the complete preset library. Mutating operators keep the safe
    copy-on-read default.
    """
    path = _fbp_user_preset_path()
    stamp = _fbp_user_preset_stamp(path)
    if stamp is None:
        _FBP_USER_PRESET_CACHE["stamp"] = None
        _FBP_USER_PRESET_CACHE["data"] = {}
        _FBP_USER_PRESET_CACHE["status"] = "MISSING"
        _FBP_USER_PRESET_CACHE["error"] = ""
        return {}
    if _FBP_USER_PRESET_CACHE.get("stamp") == stamp:
        data = _FBP_USER_PRESET_CACHE.get("data", {})
        return copy.deepcopy(data) if mutable else data
    status = "OK"
    error = ""
    try:
        data = json.loads(path.read_text(encoding="utf8"))
        if not isinstance(data, dict):
            raise TypeError("The preset library root must be a JSON object")
    except OSError as exc:
        data = {}
        status = "UNREADABLE"
        error = f"{type(exc).__name__}: {exc}"
    except (ValueError, TypeError) as exc:
        data = {}
        status = "CORRUPT"
        error = f"{type(exc).__name__}: {exc}"
        backup = path.with_name("effect_presets.backup.json")
        try:
            recovered = json.loads(backup.read_text(encoding="utf8"))
            if not isinstance(recovered, dict):
                raise TypeError("The backup preset library root must be a JSON object")
            data = recovered
            status = "RECOVERED_BACKUP"
        except (OSError, ValueError, TypeError):
            pass
    _FBP_USER_PRESET_CACHE["stamp"] = stamp
    _FBP_USER_PRESET_CACHE["data"] = data
    _FBP_USER_PRESET_CACHE["status"] = status
    _FBP_USER_PRESET_CACHE["error"] = error
    return copy.deepcopy(data) if mutable else data


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
        _FBP_USER_PRESET_CACHE["status"] = "OK"
        _FBP_USER_PRESET_CACHE["error"] = ""
        return True
    except OSError:
        return False
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass


def _fbp_backup_user_preset_library():
    """Keep one atomic rolling backup before a filesystem preset mutation."""
    path = _fbp_user_preset_path()
    if not path.is_file():
        return True, None
    backup = path.with_name("effect_presets.backup.json")
    temporary = backup.with_name(f".{backup.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(path.read_bytes())
        temporary.replace(backup)
        return True, backup
    except OSError:
        return False, backup
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass


def _fbp_write_recovery_copy(source, target):
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(source.read_bytes())
        temporary.replace(target)
        return True
    except OSError:
        return False
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass


def _fbp_prepare_user_preset_mutation():
    """Fail closed or recover before any preset-library filesystem mutation."""
    data = _fbp_load_user_presets(mutable=False)
    status = str(_FBP_USER_PRESET_CACHE.get("status", "") or "")
    path = _fbp_user_preset_path()
    recovery_path = None
    if status in {"CORRUPT", "UNREADABLE"}:
        detail = str(_FBP_USER_PRESET_CACHE.get("error", "") or "unknown read error")
        return False, None, None, f"Preset library is {status.lower()}: {detail}"
    if status == "RECOVERED_BACKUP":
        recovery_path = path.with_name("effect_presets.corrupt.json")
        if not _fbp_write_recovery_copy(path, recovery_path):
            return False, None, recovery_path, "Could not preserve the corrupted preset library"
        if not _fbp_save_user_presets(data):
            return False, None, recovery_path, "Could not restore the preset library from its backup"
    backup_ok, backup_path = _fbp_backup_user_preset_library()
    if not backup_ok:
        return False, backup_path, recovery_path, "Could not back up the preset library"
    return True, backup_path, recovery_path, ""


def _fbp_effect_instance_animation_property_map(effect_id, definition=None):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = definition or fbp_effect_definition(effect_id)
    result = {
        _fbp_animation_key(effect_id, suffix): suffix
        for suffix in ("evolve", "step", "seed", "unique", "layer_seed", "amount")
    }
    result[_fbp_effect_evolution_speed_property(effect_id, definition)] = "speed"
    return result


def _fbp_capture_effect_instance_properties(rig, effect_id, instance_id):
    """Serialize values owned by one concrete MULTI instance."""
    effect_id = fbp_normalize_effect_id(effect_id)
    instance_id = str(instance_id or "")
    definition = fbp_effect_definition(effect_id)
    result = {}
    for prop_name in (definition.get("property_map", {}) or {}):
        channel = fbp_effect_instance_channel(
            rig, effect_id, instance_id, prop_name, ensure=False
        )
        if channel is not None:
            result[prop_name] = _fbp_serialize_value(
                fbp_effect_instance_channel_value(channel)
            )
    animation = fbp_effect_instance_animation_item(
        rig, effect_id, instance_id, ensure=False
    )
    if animation is not None:
        for prop_name, suffix in _fbp_effect_instance_animation_property_map(
            effect_id, definition
        ).items():
            try:
                result[prop_name] = _fbp_serialize_value(
                    getattr(animation, suffix)
                )
            except FBP_DATA_ERRORS:
                continue
    return result


def _fbp_apply_effect_instance_properties(rig, effect_id, instance_id, values):
    """Apply a preset/reset payload to one concrete MULTI instance only."""
    effect_id = fbp_normalize_effect_id(effect_id)
    instance_id = str(instance_id or "")
    definition = fbp_effect_definition(effect_id)
    if not instance_id or not _fbp_effect_uses_multi_instances(effect_id):
        return False
    fbp_ensure_effect_instance_state(
        rig, effect_id, instance_id, prefer_node=True
    )
    animation_map = _fbp_effect_instance_animation_property_map(
        effect_id, definition
    )
    property_map = definition.get("property_map", {}) or {}
    changed = False
    changed_properties = set()
    for prop_name, serialized in dict(values or {}).items():
        value = _fbp_deserialize_value(serialized)
        if prop_name in property_map:
            speed_prop = str(definition.get("evolve_speed_property", "") or "")
            if prop_name == speed_prop:
                animation = fbp_effect_instance_animation_item(
                    rig, effect_id, instance_id, ensure=True
                )
                if animation is not None:
                    changed = fbp_set_rna_property_silent(
                        animation, "speed", value
                    ) or changed
                    changed_properties.add(prop_name)
                continue
            channel = fbp_effect_instance_channel(
                rig, effect_id, instance_id, prop_name, ensure=True,
                prefer_node=True,
            )
            if channel is None:
                continue
            changed = fbp_set_rna_property_silent(
                channel, _fbp_instance_channel_value_attr(channel), value
            ) or changed
            changed_properties.add(prop_name)
            continue
        suffix = animation_map.get(prop_name)
        if suffix:
            animation = fbp_effect_instance_animation_item(
                rig, effect_id, instance_id, ensure=True
            )
            if animation is not None:
                changed = fbp_set_rna_property_silent(
                    animation, suffix, value
                ) or changed
    if changed_properties:
        changed = fbp_update_shader_effect(
            rig,
            effect_id,
            property_names=changed_properties,
            instance_id=instance_id,
        ) or changed
    _fbp_invalidate_effect_runtime_profile(rig)
    if fbp_active_effect_id(rig) == effect_id and fbp_active_effect_instance_id(rig) == instance_id:
        fbp_load_effect_instance_settings(rig, effect_id, instance_id)
    return changed


def _fbp_reset_effect_instance(rig, effect_id, instance_id):
    """Restore one concrete instance without changing sibling copies."""
    definition = fbp_effect_definition(effect_id)
    values = {}
    for prop_name in (definition.get("property_map", {}) or {}):
        try:
            prop = rig.bl_rna.properties.get(prop_name)
            if prop is None:
                continue
            values[prop_name] = (
                tuple(prop.default_array)
                if getattr(prop, "is_array", False)
                else prop.default
            )
        except FBP_DATA_ERRORS:
            continue
    for suffix, editor_key, default, _minimum, _maximum, _description in (
        _fbp_effect_animation_contract(effect_id, definition)
    ):
        values[editor_key] = default
    return _fbp_apply_effect_instance_properties(
        rig, effect_id, instance_id, values
    )


def _fbp_apply_preset_values(rig, effect_id, values, *, instance_id=""):
    values = dict(values or {})
    instance_id = str(instance_id or "")
    if instance_id and _fbp_effect_uses_multi_instances(effect_id):
        properties = (
            dict(values.get("properties", {}) or {})
            if int(values.get("__fbp_state__", 0) or 0) >= 1
            else values
        )
        return _fbp_apply_effect_instance_properties(
            rig, effect_id, instance_id, properties
        )
    state = _fbp_capture_effect_state(rig, effect_id)
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
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        layout = configure_layout(self.layout)
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            layout.label(text="No Frame By Plane layer selected", icon="INFO")
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
                effect_id = _fbp_effect_ref_effect_id(members[0]) if members else ""
            if not effect_id:
                effect_ids = _fbp_runtime_effect_ids(rig)
                if effect_ids:
                    effect_id = effect_ids[0]
        if not effect_id:
            layout.label(text="No active effect", icon="BLANK1")
            return
        definition = fbp_effect_definition(effect_id) or {}
        active_instance_id = (
            fbp_active_effect_instance_id(rig)
            if _fbp_effect_uses_multi_instances(effect_id) else ""
        )
        layout.label(
            text=_fbp_effect_display_label(effect_id, definition),
            **effect_icon_kwargs(effect_id, definition.get("icon", "MODIFIER")),
        )
        layout.separator()
        builtins = FBP_BUILTIN_EFFECT_PRESETS.get(effect_id, {})
        users = _fbp_load_user_presets(mutable=False).get(effect_id, {}) or {}
        if builtins:
            layout.label(text="Built-in", icon="PRESET")
            for name in builtins:
                op = layout.operator("fbp.apply_effect_preset", text=name, icon="CHECKMARK")
                op.effect_id = effect_id
                op.preset_name = name
                op.user_preset = False
                op.instance_id = active_instance_id
        layout.separator()
        layout.label(text="User", icon="USER")
        if users:
            for name in sorted(users, key=lambda item: str(item).casefold()):
                row = layout.row(align=True)
                op = row.operator("fbp.apply_effect_preset", text=name, icon="PRESET")
                op.effect_id = effect_id
                op.preset_name = name
                op.user_preset = True
                op.instance_id = active_instance_id
                rename_slot = row.row(align=True)
                rename_slot.operator_context = 'INVOKE_DEFAULT'
                rename = rename_slot.operator("fbp.rename_effect_preset", text="", icon=ui_icon("action.rename"))
                rename.effect_id = effect_id
                rename.preset_name = name
                rename.new_name = name
                delete_slot = row.row(align=True)
                delete_slot.operator_context = 'INVOKE_DEFAULT'
                delete = delete_slot.operator("fbp.delete_effect_preset", text="", icon=ui_icon("action.delete"))
                delete.effect_id = effect_id
                delete.preset_name = name
        else:
            muted = layout.row()
            muted.enabled = False
            muted.label(text="No saved user presets", icon="BLANK1")
        layout.separator()
        save_row = layout.row(align=True)
        save_row.operator_context = 'INVOKE_DEFAULT'
        save_row.operator("fbp.save_effect_preset", text="Save Current Preset", icon="ADD")


class FBP_OT_OpenEffectPresets(Operator):
    bl_idname = "fbp.open_effect_presets"
    bl_label = "Effect Presets"
    bl_description = "Open presets for the effect shown in this settings panel"
    bl_options = {"INTERNAL"}

    effect_id: StringProperty(description='Effect identifier', default="", options={"SKIP_SAVE"})
    instance_id: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, _event):
        rigs = _fbp_selected_rigs(context)
        effect_id = fbp_normalize_effect_id(self.effect_id)
        if not rigs or not effect_id:
            return {"CANCELLED"}
        _fbp_select_effect_row(
            rigs[0], effect_id, rigs, instance_id=str(self.instance_id or "")
        )
        try:
            return bpy.ops.wm.call_menu(name="FBP_MT_effect_presets")
        except FBP_DATA_ERRORS:
            return {"CANCELLED"}

    def execute(self, context):
        return self.invoke(context, None)


class FBP_OT_OpenEffectToolbarMenu(Operator):
    bl_idname = "fbp.open_effect_toolbar_menu"
    bl_label = "Open Effect Tools"
    bl_description = 'Open the selected effect-stack menu for adding, grouping or managing effects'
    bl_options = {"INTERNAL"}

    menu: EnumProperty(description='Choose the Menu option for this effect-stack action. Hover each entry for the specific mode when Blender exposes enum item help.',
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
        layout = configure_layout(self.layout)
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            layout.label(text="No Frame By Plane layer selected", icon="INFO")
            return
        rig = rigs[0]
        selected_instances = fbp_selected_effect_instances(
            rig, fallback_active=True, movable_only=True,
            categories=_fbp_effect_view_categories(context),
        )
        selected = [_fbp_effect_ref(effect_id, instance_id) for effect_id, instance_id in selected_instances]
        selected = fbp_expand_effect_selection_to_groups(rig, selected)
        if any(any(not _fbp_effect_ref_is_active(target, token) for token in selected) for target in rigs):
            layout.label(text="Copy every checked instance to all selected layers first", icon="ERROR")
            return
        chain_keys = {_fbp_effect_chain_key(_fbp_effect_ref_effect_id(token)) for token in selected}
        chain_keys.discard(("", ""))
        if len(chain_keys) != 1:
            layout.label(text="Select effects from one compatible chain", icon="ERROR")
            return
        order = _fbp_logical_effect_chain_tokens(
            rig, next(iter(chain_keys))
        )
        selected_set = set(selected)
        targets = [token for token in order if token not in selected_set]
        if not targets:
            layout.label(text="No compatible destination effect", icon="BLANK1")
            return
        for heading, placement, icon in (("Move Before", "BEFORE", "TRIA_UP"), ("Move After", "AFTER", "TRIA_DOWN")):
            layout.label(text=heading, icon=icon)
            for ordinal, target in enumerate(targets, 1):
                effect_id, instance_id = _fbp_effect_ref_parts(target)
                definition = fbp_effect_definition(effect_id)
                label = _fbp_effect_display_label(effect_id, definition)
                if _fbp_effect_uses_multi_instances(effect_id):
                    label = f"{label} · {ordinal}"
                op = layout.operator(
                    "fbp.move_selected_effects_relative", text=label,
                    **effect_icon_kwargs(effect_id, definition.get("icon", "MODIFIER")),
                )
                op.target_effect_id = effect_id
                op.target_instance_id = instance_id
                op.placement = placement
            if placement == "BEFORE":
                layout.separator()



class FBP_MT_EffectVisibilityActions(Menu):
    bl_idname = "FBP_MT_effect_visibility_actions"
    bl_label = "Effect Visibility Actions"

    def draw(self, _context):
        layout = configure_layout(self.layout)
        for text, mode, icon in (
            ("Show Selected", "SHOW_SELECTED", "HIDE_OFF"),
            ("Hide Selected", "HIDE_SELECTED", "HIDE_ON"),
            ("Show All", "SHOW_ALL", "HIDE_OFF"),
        ):
            op = layout.operator("fbp.set_selected_effects_visibility", text=text, icon=icon)
            op.channel = "BOTH"
            op.mode = mode
        layout.separator()
        solo = layout.operator(
            "fbp.set_selected_effects_visibility",
            text="Solo Selected in Viewport",
            icon="CHECKMARK",
        )
        solo.channel = "VIEWPORT"
        solo.mode = "SOLO_SELECTED"


class FBP_MT_EffectStackActions(Menu):
    bl_idname = "FBP_MT_effect_stack_actions"
    bl_label = "Effect Stack Actions"

    def draw(self, context):
        layout = configure_layout(self.layout)
        rigs = _fbp_selected_rigs(context)
        rig = rigs[0] if rigs else None
        categories = _fbp_effect_view_categories(context)
        selected_instances = (
            fbp_selected_effect_instances(
                rig,
                fallback_active=True,
                movable_only=True,
                categories=categories,
            )
            if rig is not None else []
        )
        effect_refs = tuple(
            _fbp_effect_ref(effect_id, instance_id)
            for effect_id, instance_id in selected_instances
        )

        move_top = layout.row(align=True)
        move_top.enabled = bool(
            rigs and effect_refs
            and fbp_can_move_effect_selection(rigs, effect_refs, "TOP")
        )
        op = move_top.operator(
            "fbp.move_active_effect", text="Move to Top", icon="TRIA_UP_BAR"
        )
        op.direction = "TOP"
        move_bottom = layout.row(align=True)
        move_bottom.enabled = bool(
            rigs and effect_refs
            and fbp_can_move_effect_selection(rigs, effect_refs, "BOTTOM")
        )
        op = move_bottom.operator(
            "fbp.move_active_effect", text="Move to Bottom", icon="TRIA_DOWN_BAR"
        )
        op.direction = "BOTTOM"

        layout.separator()
        active_effect = fbp_active_effect_id(rig) if rig is not None else ""
        active_instance = fbp_active_effect_instance_id(rig) if rig is not None else ""
        duplicate = layout.row(align=True)
        duplicate.enabled = bool(
            len(rigs) == 1
            and active_effect
            and active_instance
            and fbp_effect_multi_instance_enabled(active_effect)
        )
        duplicate_op = duplicate.operator(
            "fbp.duplicate_effect_instance",
            text="Duplicate Effect",
            icon="DUPLICATE",
        )
        duplicate_op.effect_id = active_effect
        duplicate_op.instance_id = active_instance
        group = layout.row(align=True)
        group.enabled = bool(effect_refs)
        group.operator(
            "fbp.create_effect_group",
            text="Create Group from Selection",
            icon="COLLECTION_NEW",
        )
        layout.menu(
            "FBP_MT_effect_group_tools",
            text="Group Tools",
            icon="FILE_FOLDER",
        )

        layout.separator()
        # Copy follows the checked rows and falls back to the active row when
        # nothing is checked. One clear action replaces overlapping clipboard
        # commands from separate stack menus.
        layout.operator("fbp.copy_selected_effects", text="Copy", icon="COPYDOWN")
        layout.operator("fbp.paste_effect_stack", text="Paste", icon="PASTEDOWN")
        layout.operator("fbp.sort_effect_stack", text="Recommended Order", icon="SORT_DESC")
        layout.menu(
            "FBP_MT_effect_visibility_actions",
            text="Visibility Actions",
            icon="HIDE_OFF",
        )
        layout.separator()
        select_all = layout.operator("fbp.set_effect_selection", text="Select All Effects", icon="PROP_ON")
        select_all.mode = "ALL"
        invert = layout.operator("fbp.set_effect_selection", text="Invert Effect Selection", icon="PROP_CON")
        invert.mode = "INVERT"
        clear_selection = layout.operator("fbp.set_effect_selection", text="Clear Effect Selection", icon="PROP_OFF")
        clear_selection.mode = "NONE"
        layout.separator()
        layout.operator("fbp.apply_image_effects", text="Apply Effects", icon="RENDER_STILL")
        layout.operator("fbp.clear_effect_stack", text="Clear Stack", icon="TRASH")


class FBP_MT_EffectGroupTools(Menu):
    bl_idname = "FBP_MT_effect_group_tools"
    bl_label = "Effect Group Tools"

    def draw(self, context):
        layout = configure_layout(self.layout)
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            layout.label(text="No Frame By Plane layer selected", icon="INFO")
            return
        rig = rigs[0]
        active_effect = fbp_active_effect_id(rig)
        group_id = fbp_active_effect_group_id(rig)
        if not group_id and active_effect:
            group_id = fbp_effect_group_id_for_rig(
                rig,
                active_effect,
                instance_id=fbp_active_effect_instance_id(rig),
                normalize=False,
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
        selected_effects = fbp_selected_effect_instances(
            rig, fallback_active=True
        )
        can_ungroup = any(
            bool(fbp_effect_group_id_for_rig(
                rig, effect_id, instance_id=instance_id, normalize=False
            ))
            for effect_id, instance_id in selected_effects
        )
        ungroup_row = layout.row()
        ungroup_row.enabled = can_ungroup
        ungroup_row.operator("fbp.ungroup_selected_effects", icon="UNLINKED")


class FBP_OT_EffectHeaderWarning(Operator):
    bl_idname = "fbp.effect_header_warning"
    bl_label = "Effect Warning"
    bl_description = 'Show the current effect warning'
    bl_options = {"INTERNAL"}

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", default="", options={"SKIP_SAVE"})
    message: StringProperty(description="Diagnostic message describing the sequence or generation problem.", default="", options={"SKIP_SAVE"})

    @classmethod
    def description(cls, _context, properties):
        return str(getattr(properties, "message", "") or "Effect warning")

    def execute(self, context):
        return {"FINISHED"}


class FBP_OT_SetEffectInputSource(Operator):
    bl_idname = "fbp.set_effect_input_source"
    bl_label = "Set Effect Input Source"
    bl_description = 'Choose which source image or intermediate result feeds the active effect'
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", default="", options={"SKIP_SAVE"})
    instance_id: StringProperty(description="Persistent concrete effect instance targeted by this action.", default="", options={"SKIP_SAVE"})
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
        rigs = _fbp_selected_rigs(context)
        if self.instance_id:
            rigs = [
                rig for rig in rigs
                if fbp_active_effect_id(rig) == self.effect_id
                and fbp_active_effect_instance_id(rig) == self.instance_id
            ][:1]
        for rig in rigs:
            if fbp_effect_is_active(rig, self.effect_id):
                changed = fbp_set_effect_input_source(
                    rig, self.effect_id, self.source, instance_id=self.instance_id
                ) or changed
        return {"FINISHED"} if changed else {"CANCELLED"}


class FBP_OT_SetEffectDebugMode(Operator):
    bl_idname = "fbp.set_effect_debug_mode"
    bl_label = "Set Effect Preview"
    bl_description = 'Switch the active effect between its final result and diagnostic preview modes'
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
    bl_description = 'Copy the active effect and its editable settings to the Frame By Plane clipboard'
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
    bl_description = 'Copy the complete effect stack from the active Frame By Plane layer'
    bl_options = {"INTERNAL"}

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        # The complete snapshot keeps duplicated instances, their own values,
        # groups and the visible stack order, exactly like Effect Stack Presets.
        snapshot = fbp_capture_effect_stack_snapshot(rigs[0])
        effects = list(snapshot.get("effects", ()))
        _FBP_EFFECT_CLIPBOARD.clear()
        _FBP_EFFECT_CLIPBOARD.update(
            {"mode": "STACK", "effects": effects, "snapshot": snapshot}
        )
        self.report({"INFO"}, f"Copied {len(effects)} effect(s)")
        return {"FINISHED"}


class FBP_OT_PasteEffectStack(Operator):
    bl_idname = "fbp.paste_effect_stack"
    bl_label = "Paste Effects"
    bl_description = 'Paste copied effects onto all compatible selected Frame By Plane layers'
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

        stack_snapshot = _FBP_EFFECT_CLIPBOARD.get("snapshot")
        if isinstance(stack_snapshot, dict):
            return self._paste_stack_snapshot(rigs, stack_snapshot, len(states))

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

    def _paste_stack_snapshot(self, rigs, snapshot, effect_count):
        """Merge a copied stack into every layer, restoring all on failure."""
        backups = [(rig, fbp_capture_effect_stack_snapshot(rig)) for rig in rigs]
        for rig in rigs:
            result = fbp_apply_effect_stack_snapshot(rig, snapshot, mode="MERGE")
            if result.get("success", False):
                continue
            for restored_rig, backup in backups:
                fbp_apply_effect_stack_snapshot(
                    restored_rig, backup, mode="REPLACE", _allow_rollback=False,
                )
                fbp_sync_effect_items(restored_rig)
            self.report(
                {"ERROR"},
                "Paste failed; every selected layer was restored: "
                + str(result.get("error", "") or "unknown error"),
            )
            return {"CANCELLED"}
        fbp_sync_effect_items(
            rigs[0], rigs, repair_assets=False, normalize_instance_ids=False
        )
        self.report(
            {"INFO"},
            f"Pasted {effect_count} effect(s) to {len(rigs)} layer(s)",
        )
        return {"FINISHED"}


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
        fbp_persist_effect_stacks(rigs)
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
    bl_description = 'Restore the active effect to its registered default settings'
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(
        description="Optional explicit effect shown by the settings panel",
        default="",
        options={"SKIP_SAVE"},
    )
    instance_id: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        effect_id = fbp_normalize_effect_id(self.effect_id) or fbp_active_effect_id(rigs[0])
        if not effect_id:
            return {"CANCELLED"}
        requested_instance_id = str(self.instance_id or "")
        if requested_instance_id and _fbp_effect_uses_multi_instances(effect_id):
            compatible = [rigs[0]] if _fbp_find_shader_effect_nodes_for_rig(
                rigs[0], effect_id, requested_instance_id
            ) else []
        else:
            compatible = [
                rig for rig in rigs if fbp_effect_is_active(rig, effect_id)
            ]
        if not compatible:
            self.report({"WARNING"}, "The selected effect is not active on these layers")
            return {"CANCELLED"}

        for rig in compatible:
            if requested_instance_id and _fbp_effect_uses_multi_instances(effect_id):
                _fbp_reset_effect_instance(rig, effect_id, requested_instance_id)
                continue
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
    bl_label = "Reset Default Processing Order"
    bl_description = 'Optionally restore the factory order inside each technically compatible processing chain'
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            self.report({"WARNING"}, "Select a Frame By Plane layer")
            return {"CANCELLED"}
        recommended = (
            list(FBP_BASE_EFFECT_MENU_ORDER)
            + list(FBP_SHADER_STAGE_ORDER["UV"])
            + list(FBP_SHADER_STAGE_ORDER["COLOR"])
            + list(FBP_SHADER_STAGE_ORDER["MASK"])
            + list(FBP_3D_EFFECT_MENU_ORDER)
        )
        changed = fbp_sort_effect_stacks_transactional(
            rigs, recommended
        )
        if not changed:
            self.report({"INFO"}, "Effect Stack already uses the default order")
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_ApplyEffectPreset(Operator):
    bl_idname = "fbp.apply_effect_preset"
    bl_label = "Apply Effect Preset"
    bl_description = 'Apply this saved preset to the active effect on the selected layers'
    bl_options = {"REGISTER", "UNDO"}
    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", default="", options={"SKIP_SAVE"})
    preset_name: StringProperty(description="Name of the built-in or user effect preset targeted by this action.", default="", options={"SKIP_SAVE"})
    user_preset: BoolProperty(description="Distinguish a user-saved preset from a built-in preset when applying effect values.", default=False, options={"SKIP_SAVE"})
    instance_id: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        source = _fbp_load_user_presets(mutable=False).get(self.effect_id, {}) if self.user_preset else FBP_BUILTIN_EFFECT_PRESETS.get(self.effect_id, {})
        values = source.get(self.preset_name)
        if not isinstance(values, dict):
            self.report({"WARNING"}, "The selected effect preset is no longer available")
            return {"CANCELLED"}
        rigs = _fbp_selected_rigs(context)
        if self.instance_id and rigs:
            # A persistent instance ID belongs to one concrete layer. Applying
            # it to other selected rigs would silently target whichever duplicate
            # happens to be active there, so keep concrete presets local.
            rigs = rigs[:1]
        changed = 0
        for index, rig in enumerate(rigs):
            if not fbp_effect_is_active(rig, self.effect_id):
                continue
            instance_id = str(self.instance_id or "") if index == 0 else ""
            if _fbp_effect_uses_multi_instances(self.effect_id) and not instance_id:
                instance_id = fbp_active_effect_instance_id(rig)
            changed += int(_fbp_apply_preset_values(
                rig, self.effect_id, values, instance_id=instance_id
            ))
        if not changed:
            self.report({"INFO"}, "The selected preset is already applied")
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_SaveEffectPreset(Operator):
    bl_idname = "fbp.save_effect_preset"
    bl_label = "Save Effect Preset"
    bl_description = (
        "Save the active effect settings to the user preset library on disk; "
        "Blender Undo cannot restore this filesystem change"
    )
    bl_options = {"INTERNAL"}
    preset_name: StringProperty(
        name="Name",
        description="Name used to store this effect setup in the user preset library. Names must be unique for the active effect",
        default="My Preset",
    )
    effect_id: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    target_payload: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, _event):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        effect_id = fbp_active_effect_id(rigs[0])
        if not effect_id:
            self.report({"ERROR"}, "Select an effect before saving a preset")
            return {"CANCELLED"}
        self.effect_id = str(effect_id)
        self.target_payload = _fbp_capture_rig_targets(rigs)
        existing = _fbp_load_user_presets(mutable=False).get(effect_id, {})
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
        layout = configure_layout(self.layout)
        section_header(layout, "Save Effect Preset", icon="PRESET")
        layout.prop(self, "preset_name", text="Preset Name")
        warning = layout.box()
        warning.alert = True
        warning.label(text="This changes the user preset library on disk.", icon="ERROR")
        warning.label(text="Blender Undo cannot restore it; one rolling backup is written first.")

    def execute(self, context):
        rigs = _fbp_resolve_rig_targets(self.target_payload) if self.target_payload else _fbp_selected_rigs(context)
        if not rigs:
            self.report({"WARNING"}, "The original effect layer no longer exists")
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        effect_id = str(self.effect_id or fbp_active_effect_id(rigs[0]) or "")
        name = self.preset_name.strip()
        if not effect_id or not name:
            return {"CANCELLED"}
        active_instance_id = (
            fbp_active_effect_instance_id(rigs[0])
            if _fbp_effect_uses_multi_instances(effect_id) else ""
        )
        state = _fbp_capture_effect_state(rigs[0], effect_id)
        if active_instance_id:
            state["properties"] = _fbp_capture_effect_instance_properties(
                rigs[0], effect_id, active_instance_id
            )
        data = _fbp_load_user_presets()
        existing = data.get(effect_id, {})
        folded_name = name.casefold()
        if any(str(existing_name).casefold() == folded_name for existing_name in existing):
            self.report({"ERROR"}, "A user preset with this name already exists")
            return {"CANCELLED"}
        prepared, backup_path, recovery_path, preparation_error = (
            _fbp_prepare_user_preset_mutation()
        )
        if not prepared:
            self.report({"ERROR"}, f"Could not prepare preset save; {preparation_error}")
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
            self.report({"ERROR"}, "Could not save preset; the preset library was not changed")
            return {"CANCELLED"}
        notes = []
        if backup_path is not None:
            notes.append(f"backup: {backup_path.name}")
        if recovery_path is not None:
            notes.append(f"recovered corrupt file: {recovery_path.name}")
        self.report({"INFO"}, f"Saved preset {name}" + (f"; {'; '.join(notes)}" if notes else ""))
        return {"FINISHED"}


class FBP_OT_RenameEffectPreset(Operator):
    bl_idname = "fbp.rename_effect_preset"
    bl_label = "Rename Effect Preset"
    bl_description = 'Rename the selected user effect preset'
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
        if not self.effect_id or old_name not in _fbp_load_user_presets(mutable=False).get(self.effect_id, {}):
            self.report({"ERROR"}, "Preset no longer exists")
            return {"CANCELLED"}
        self.new_name = old_name
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, _context):
        layout = configure_layout(self.layout)
        section_header(layout, "Rename Effect Preset", icon="PRESET")
        hint_row(layout, self.preset_name, icon="BLANK1", disabled=True)
        layout.prop(self, "new_name", text="New Name")
        warning = layout.box()
        warning.alert = True
        warning.label(text="This changes the user preset library on disk.", icon="ERROR")
        warning.label(text="Blender Undo cannot restore it; one rolling backup is written first.")

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
        prepared, backup_path, recovery_path, preparation_error = (
            _fbp_prepare_user_preset_mutation()
        )
        if not prepared:
            self.report({"ERROR"}, f"Could not prepare preset rename; {preparation_error}")
            return {"CANCELLED"}
        value = presets.pop(old_name)
        presets[new_name] = value
        data[self.effect_id] = presets
        if not _fbp_save_user_presets(data):
            self.report({"ERROR"}, "Could not rename preset; the preset library was not changed")
            return {"CANCELLED"}
        notes = []
        if backup_path is not None:
            notes.append(f"backup: {backup_path.name}")
        if recovery_path is not None:
            notes.append(f"recovered corrupt file: {recovery_path.name}")
        self.report({"INFO"}, f"Renamed preset to {new_name}" + (f"; {'; '.join(notes)}" if notes else ""))
        return {"FINISHED"}


class FBP_OT_DeleteEffectPreset(Operator):
    bl_idname = "fbp.delete_effect_preset"
    bl_label = "Delete Effect Preset"
    bl_description = (
        "Delete the selected user effect preset from disk without changing existing effects; "
        "Blender Undo cannot restore this filesystem change"
    )
    bl_options = {"INTERNAL"}
    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", default="", options={"SKIP_SAVE"})
    preset_name: StringProperty(description="Name of the built-in or user effect preset targeted by this action.", default="", options={"SKIP_SAVE"})

    def invoke(self, context, event):
        if self.preset_name not in _fbp_load_user_presets(mutable=False).get(self.effect_id, {}):
            self.report({"ERROR"}, "Preset no longer exists")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, _context):
        layout = configure_layout(self.layout)
        section_header(layout, "Delete Effect Preset", icon="TRASH")
        hint_row(layout, self.preset_name, icon="PRESET", disabled=True)
        warning = layout.box()
        warning.alert = True
        warning.label(text="This permanently changes the preset library on disk.", icon="ERROR")
        warning.label(text="Blender Undo cannot restore it; one rolling backup is written first.")

    def execute(self, _context):
        data = _fbp_load_user_presets()
        presets = data.get(self.effect_id, {})
        if self.preset_name not in presets:
            return {"CANCELLED"}
        prepared, backup_path, recovery_path, preparation_error = (
            _fbp_prepare_user_preset_mutation()
        )
        if not prepared:
            self.report({"ERROR"}, f"Could not prepare preset deletion; {preparation_error}")
            return {"CANCELLED"}
        del presets[self.preset_name]
        if not presets:
            data.pop(self.effect_id, None)
        if not _fbp_save_user_presets(data):
            self.report({"ERROR"}, "Could not delete preset; the preset library was not changed")
            return {"CANCELLED"}
        notes = []
        if backup_path is not None:
            notes.append(f"backup: {backup_path.name}")
        if recovery_path is not None:
            notes.append(f"recovered corrupt file: {recovery_path.name}")
        self.report({"INFO"}, f"Deleted preset {self.preset_name}" + (f"; {'; '.join(notes)}" if notes else ""))
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
        if (
            _fbp_effect_uses_multi_instances(effect_id)
            and len(_fbp_find_shader_effect_nodes_for_rig(source, effect_id)) > 1
        ):
            self.report(
                {"WARNING"},
                "Duplicated effect stacks must be copied one instance at a time",
            )
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
            ) + (_fbp_effect_evolution_speed_property(effect_id, definition),)

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
            target_instance_id = (
                next(
                    (
                        _fbp_effect_ref_parts(token)[1]
                        for token in _fbp_mixed_effect_tokens(target)
                        if _fbp_effect_ref_effect_id(token) == effect_id
                    ),
                    "",
                )
                if _fbp_effect_uses_multi_instances(effect_id) else ""
            )
            if target_instance_id:
                # A concrete instance reads its own channels, not the layer
                # settings: copy the values there too.
                for prop_name in prop_names:
                    if hasattr(source, prop_name):
                        fbp_update_effect_instance_setting_value(
                            target, effect_id, target_instance_id, prop_name,
                            getattr(source, prop_name),
                        )
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
                unique_key = _fbp_animation_key(effect_id, "unique")
                if bool(getattr(target, unique_key, False)):
                    fbp_assign_effect_layer_seed(target, effect_id, force=True)
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

    effect_id: StringProperty(
        name="Effect ID",
        description="Resolved active effect copied by this one-step Undo transaction",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        # Poll callbacks can run repeatedly while Blender evaluates menus and
        # shortcuts. Never rebuild CollectionProperties here: that writes RNA
        # outside an operator transaction and can create misleading Undo steps.
        rigs = _fbp_selected_rigs(context)
        if len(rigs) < 2:
            return False
        effect_id = fbp_active_effect_id(rigs[0])
        if (
            effect_id
            and _fbp_effect_uses_multi_instances(effect_id)
            and len(_fbp_find_shader_effect_nodes_for_rig(rigs[0], effect_id)) > 1
        ):
            return False
        present, total = fbp_effect_presence(rigs, effect_id) if effect_id else (0, len(rigs))
        return bool(effect_id and 0 < present < total)

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        self.effect_id = fbp_active_effect_id(rigs[0])
        if not self.effect_id:
            return {"CANCELLED"}
        # Reuse the tested copy implementation directly instead of invoking a
        # second UNDO operator. Nested bpy.ops calls could split one click into
        # two history entries and made the first Ctrl+Z appear inconsistent.
        return FBP_OT_CopyEffectToSelected.execute(self, context)


class FBP_OT_SetEffectViewport(Operator):
    bl_idname = "fbp.set_effect_viewport"
    bl_label = "Set Effect Visibility"
    bl_description = 'Show or hide the selected effect in both viewport and final render'
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
        changed = sum(
            1 for rig in rigs
            if fbp_set_effect_global_visible(rig, self.effect_id, self.visible)
        )
        if changed == 0:
            return {"CANCELLED"}
        return {"FINISHED"}


def _fbp_effect_chain_key(effect_id):
    definition = fbp_effect_definition(effect_id)
    kind = str(definition.get("kind", "") or "")
    if kind == "GEOMETRY":
        return ("GEOMETRY", "")
    if kind == "SHADER":
        return ("SHADER", str(definition.get("stage", "") or ""))
    return ("", "")


def _fbp_effect_chain_tokens(rig, chain_key):
    """Return concrete evaluation tokens for one compatible chain."""
    kind, stage = chain_key
    if kind == "GEOMETRY":
        plane = _fbp_plane(rig)
        if not plane:
            return []
        result = []
        try:
            for modifier in plane.modifiers:
                effect_id = _fbp_geometry_effect_id_for_modifier(modifier)
                if not effect_id:
                    continue
                definition = fbp_effect_definition(effect_id)
                instance_id = (
                    effect_instance_id(modifier)
                    if str(definition.get("instance_policy", "SINGLE") or "SINGLE").upper() == "MULTI"
                    else ""
                )
                token = _fbp_effect_ref(effect_id, instance_id)
                if token:
                    result.append(token)
        except FBP_DATA_ERRORS:
            return []
        return result
    if kind == "SHADER":
        order = _fbp_get_rig_shader_stage_order(rig, stage)
        active = []
        active_set = set()
        materials = _fbp_plane_materials(rig)
        source = materials[0] if materials else None
        if source is not None:
            for node in _fbp_shader_effect_nodes(source, stage=stage):
                token = _fbp_shader_node_token(node)
                if token and token not in active_set:
                    active_set.add(token)
                    active.append(token)
        result = [token for token in order if token in active_set]
        result_set = set(result)
        result.extend(token for token in active if token not in result_set)
        normalized = []
        for token in result:
            effect_id = _fbp_effect_ref_effect_id(token)
            value = (
                token if _fbp_effect_uses_multi_instances(effect_id)
                else effect_id
            )
            if value and value not in normalized:
                normalized.append(value)
        return normalized
    return []
def _fbp_move_effect_ref(rig, token, direction, *, sync_items=False):
    effect_id, instance_id = _fbp_effect_ref_parts(token)
    if instance_id:
        return fbp_move_effect_instance(
            rig, effect_id, instance_id, direction, sync_items=sync_items
        )
    return fbp_move_effect(rig, effect_id, direction, sync_items=sync_items)


def _fbp_mixed_effect_tokens_uncached(rig):
    result = []
    for record in fbp_effect_instance_records_for_rig(
        rig, ensure=False, sync_storage=False
    ):
        effect_id = fbp_normalize_effect_id(record.get("effect_id", ""))
        if not effect_id or effect_id == FBP_EFFECT_LAYER_BLEND:
            continue
        instance_id = (
            str(record.get("instance_id", "") or "")
            if _fbp_effect_uses_multi_instances(effect_id) else ""
        )
        token = _fbp_effect_ref(effect_id, instance_id)
        if token and token not in result:
            result.append(token)
    return result


def _fbp_logical_effect_chain_tokens(rig, chain_key):
    """Return one compatible chain in top-to-bottom UI order.

    Native shader nodes and Geometry modifiers are deliberately stored in the
    reverse direction because Blender evaluates them bottom-to-top. Grouping,
    menus and selection must instead follow the persisted UI stack.
    """
    native = list(_fbp_effect_chain_tokens(rig, chain_key))
    native_set = set(native)
    logical = [
        token
        for token in _fbp_mixed_effect_tokens(rig)
        if token in native_set
        and _fbp_effect_chain_key(_fbp_effect_ref_effect_id(token)) == chain_key
    ]
    logical_set = set(logical)
    logical.extend(
        token for token in reversed(native)
        if token not in logical_set
    )
    return logical


def _fbp_persist_mixed_effect_order(rig, desired_order):
    desired = _fbp_normalize_effect_refs(desired_order)
    records = list(
        fbp_effect_instance_records_for_rig(
            rig, ensure=True, sync_storage=False
        )
    )
    by_token = {}
    passthrough = []
    for record in records:
        effect_id = fbp_normalize_effect_id(record.get("effect_id", ""))
        instance_id = (
            str(record.get("instance_id", "") or "")
            if _fbp_effect_uses_multi_instances(effect_id) else ""
        )
        token = _fbp_effect_ref(effect_id, instance_id)
        if effect_id == FBP_EFFECT_LAYER_BLEND:
            passthrough.append(record)
        elif token:
            by_token[token] = record
    if set(desired) != set(by_token) or len(desired) != len(by_token):
        return False
    ordered_records = passthrough + [by_token[token] for token in desired]
    for index, record in enumerate(ordered_records):
        record["order"] = index
    payload = {
        "schema": FBP_EFFECT_DATA_MODEL_VERSION,
        "owner_id": _fbp_effect_stack_owner_id(rig, ensure=True),
        "instances": ordered_records,
    }
    try:
        rig[FBP_EFFECT_STACK_KEY] = encode_effect_stack(payload)
        rig[FBP_EFFECT_STACK_VERSION_KEY] = FBP_EFFECT_DATA_MODEL_VERSION
        return True
    except FBP_DATA_ERRORS:
        return False


_FBP_MIXED_SHADER_STAGE_GROUP_NAME = "FBP_GN_Mixed_Shader_Stage"
_FBP_MIXED_SHADER_STAGE_TOKEN_KEY = "fbp_mixed_shader_stage_token"
_FBP_MIXED_SHADER_STAGE_BASE = "__BASE__"


def _fbp_ensure_mixed_shader_stage_group():
    """Return the lightweight Geometry -> Set Material -> Geometry adapter."""
    group = bpy.data.node_groups.get(_FBP_MIXED_SHADER_STAGE_GROUP_NAME)
    try:
        if group and bool(group.get("fbp_mixed_shader_stage_group", False)):
            return group
    except FBP_DATA_ERRORS:
        group = None
    if group is not None:
        try:
            group["fbp_orphan_candidate"] = True
        except FBP_DATA_ERRORS:
            pass
    try:
        group = bpy.data.node_groups.new(
            _FBP_MIXED_SHADER_STAGE_GROUP_NAME, "GeometryNodeTree"
        )
        group.is_modifier = True
        group["fbp_owned"] = True
        group["fbp_mixed_shader_stage_group"] = True
        interface = group.interface
        interface.new_socket(
            name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
        )
        interface.new_socket(
            name="Material", in_out="INPUT", socket_type="NodeSocketMaterial"
        )
        interface.new_socket(
            name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
        )
        nodes = group.nodes
        links = group.links
        group_input = nodes.new("NodeGroupInput")
        group_input.location = (-260.0, 0.0)
        set_material = nodes.new("GeometryNodeSetMaterial")
        set_material.name = "FBP Mixed Stack Material"
        set_material.label = "Apply Previous Image Effects"
        set_material.location = (0.0, 0.0)
        group_output = nodes.new("NodeGroupOutput")
        group_output.location = (260.0, 0.0)
        links.new(
            _fbp_node_socket(group_input.outputs, "Geometry"),
            _fbp_node_socket(set_material.inputs, "Geometry"),
        )
        links.new(
            _fbp_node_socket(group_input.outputs, "Material"),
            _fbp_node_socket(set_material.inputs, "Material"),
        )
        links.new(
            _fbp_node_socket(set_material.outputs, "Geometry"),
            _fbp_node_socket(group_output.inputs, "Geometry"),
        )
        return group
    except FBP_DATA_ERRORS as exc:
        fbp_warn(
            "Could not build the mixed Image/Mesh shader stage",
            exc,
            event="effects.mixed_stage_group",
        )
        return None


def _fbp_mixed_shader_stage_token(modifier):
    try:
        node_group = getattr(modifier, "node_group", None)
        if not node_group or not bool(
            node_group.get("fbp_mixed_shader_stage_group", False)
        ):
            return ""
        return str(
            node_group.get(_FBP_MIXED_SHADER_STAGE_TOKEN_KEY, "") or ""
        )
    except FBP_DATA_ERRORS:
        return ""


def _fbp_mixed_shader_stage_modifiers(plane):
    if plane is None:
        return ()
    try:
        return tuple(
            modifier
            for modifier in plane.modifiers
            if getattr(modifier, "type", "") == "NODES"
            and _fbp_mixed_shader_stage_token(modifier)
        )
    except FBP_DATA_ERRORS:
        return ()


def _fbp_cleanup_mixed_stage_group(node_group):
    """Remove a zero-user private adapter group without touching the template."""
    try:
        if (
            node_group is not None
            and int(getattr(node_group, "users", 0) or 0) == 0
            and bool(node_group.get(_FBP_MIXED_SHADER_STAGE_TOKEN_KEY, ""))
        ):
            bpy.data.node_groups.remove(node_group)
            return True
    except FBP_DATA_ERRORS:
        pass
    return False


def _fbp_remove_mixed_shader_stage_modifier(plane, modifier):
    node_group = getattr(modifier, "node_group", None)
    try:
        plane.modifiers.remove(modifier)
    except FBP_DATA_ERRORS:
        return False
    _fbp_cleanup_mixed_stage_group(node_group)
    return True


def _fbp_mixed_shader_tokens_through(rig, stage_token, order=None):
    """Return shader groups evaluated from the UI bottom through one row.

    ``order`` lets a caller that refreshes several stages reuse one
    ``_fbp_mixed_effect_tokens`` result instead of rediscovering the stack.
    """
    stage_token = str(stage_token or "")
    if stage_token == _FBP_MIXED_SHADER_STAGE_BASE:
        return ()
    if order is None:
        order = _fbp_mixed_effect_tokens(rig)
    if stage_token not in order:
        return ()
    suffix = order[order.index(stage_token):]
    return tuple(
        token
        for token in reversed(suffix)
        if fbp_effect_definition(
            _fbp_effect_ref_effect_id(token)
        ).get("kind") == "SHADER"
    )


def _fbp_mixed_stage_material(rig, stage_token, order=None):
    desired = _fbp_mixed_shader_tokens_through(rig, stage_token, order)
    effect_id = (
        _fbp_effect_ref_effect_id(stage_token)
        if stage_token != _FBP_MIXED_SHADER_STAGE_BASE else ""
    )
    return _fbp_geometry_composite_material(
        rig,
        effect_id,
        _fbp_effect_ref_instance_id(stage_token),
        boundary_token_override=f"PIPELINE::{stage_token}",
        desired_shader_tokens=desired,
    )


def _fbp_refresh_mixed_shader_stage_materials(rig):
    """Refresh material copies used by existing mixed-stack shader adapters."""
    plane = _fbp_plane(rig, repair=False)
    if plane is None:
        return False
    changed = False
    order = None
    for modifier in _fbp_mixed_shader_stage_modifiers(plane):
        token = _fbp_mixed_shader_stage_token(modifier)
        node_group = getattr(modifier, "node_group", None)
        if order is None:
            order = _fbp_mixed_effect_tokens(rig)
        material = _fbp_mixed_stage_material(rig, token, order)
        if node_group is None or material is None:
            continue
        changed = _fbp_set_modifier_input(
            modifier,
            node_group,
            "Material",
            material,
            _fbp_interface_inputs(node_group),
        ) or changed
    return changed


def _fbp_geometry_modifier_for_token(rig, token):
    effect_id, instance_id = _fbp_effect_ref_parts(token)
    if not effect_id:
        return None
    if not _fbp_effect_uses_multi_instances(effect_id):
        return fbp_find_effect_modifier(rig, effect_id)
    for modifier in _fbp_find_all_effect_modifiers(rig, effect_id):
        if _fbp_geometry_modifier_instance_id(
            rig, modifier, effect_id, ensure=False
        ) == instance_id:
            return modifier
    return None


def _fbp_remove_mixed_shader_stages(plane):
    changed = False
    for modifier in _fbp_mixed_shader_stage_modifiers(plane):
        changed = (
            _fbp_remove_mixed_shader_stage_modifier(plane, modifier)
            or changed
        )
    return changed


def _fbp_refresh_mixed_pipeline(rig):
    """Re-sync mixed Image/Mesh stages after a structural instance change."""
    changed = _fbp_sync_mixed_effect_pipeline(rig)
    return _fbp_refresh_geometry_source_materials(rig) or changed


def _fbp_sync_mixed_effect_pipeline(rig):
    """Materialize one real bottom-to-top modifier pipeline for mixed stacks.

    Shader effects remain native Shader Node Groups. In a mixed stack each
    shader row additionally receives a tiny Geometry Nodes Set Material stage,
    allowing Mesh effects before/after it to consume the correct cumulative
    material instead of the plane's always-final material.
    """
    plane = _fbp_plane(rig, repair=False)
    if plane is None:
        return False
    order = _fbp_mixed_effect_tokens(rig)
    shader_tokens = [
        token for token in order
        if fbp_effect_definition(
            _fbp_effect_ref_effect_id(token)
        ).get("kind") == "SHADER"
    ]
    geometry_tokens = [
        token for token in order
        if fbp_effect_definition(
            _fbp_effect_ref_effect_id(token)
        ).get("kind") == "GEOMETRY"
    ]
    if not shader_tokens or not geometry_tokens:
        return _fbp_remove_mixed_shader_stages(plane)

    node_group = _fbp_ensure_mixed_shader_stage_group()
    if node_group is None:
        return False

    required_stage_tokens = {
        _FBP_MIXED_SHADER_STAGE_BASE,
        *shader_tokens,
    }
    stage_by_token = {
        _fbp_mixed_shader_stage_token(modifier): modifier
        for modifier in _fbp_mixed_shader_stage_modifiers(plane)
    }
    changed = False
    for token, modifier in tuple(stage_by_token.items()):
        if token in required_stage_tokens:
            continue
        if _fbp_remove_mixed_shader_stage_modifier(plane, modifier):
            stage_by_token.pop(token, None)
            changed = True

    for token in (_FBP_MIXED_SHADER_STAGE_BASE, *shader_tokens):
        modifier = stage_by_token.get(token)
        if modifier is None:
            try:
                modifier = plane.modifiers.new(
                    name="FBP \u2022 Input Material"
                    if token == _FBP_MIXED_SHADER_STAGE_BASE
                    else (
                        "FBP \u2022 "
                        + str(
                            fbp_effect_definition(
                                _fbp_effect_ref_effect_id(token)
                            ).get("label", _fbp_effect_ref_effect_id(token))
                        )
                    ),
                    type="NODES",
                )
                private_group = node_group.copy()
                private_group.name = (
                    f"FBP Stage \u2022 {getattr(rig, 'name', 'Layer')} \u2022 "
                    + (
                        "Input"
                        if token == _FBP_MIXED_SHADER_STAGE_BASE
                        else str(
                            fbp_effect_definition(
                                _fbp_effect_ref_effect_id(token)
                            ).get("label", _fbp_effect_ref_effect_id(token))
                        )
                    )
                )
                private_group[_FBP_MIXED_SHADER_STAGE_TOKEN_KEY] = token
                private_group["fbp_mixed_shader_stage_owner"] = (
                    _fbp_effect_stack_owner_id(rig, ensure=True)
                )
                modifier.node_group = private_group
                # Internal plumbing: one folded row instead of a full panel
                # between the user's effects in the Modifiers list.
                modifier.show_expanded = False
                stage_by_token[token] = modifier
                changed = True
            except FBP_DATA_ERRORS as exc:
                if modifier is not None:
                    _fbp_remove_mixed_shader_stage_modifier(
                        plane, modifier
                    )
                fbp_warn(
                    "Could not create a mixed-stack shader modifier",
                    exc,
                    event="effects.mixed_stage_modifier",
                    context={"rig": getattr(rig, "name", ""), "token": token},
                )
                continue
        try:
            current_group = getattr(modifier, "node_group", None)
            if (
                current_group is None
                or _fbp_mixed_shader_stage_token(modifier) != token
            ):
                private_group = node_group.copy()
                private_group[_FBP_MIXED_SHADER_STAGE_TOKEN_KEY] = token
                modifier.node_group = private_group
                _fbp_cleanup_mixed_stage_group(current_group)
                changed = True
            modifier.show_viewport = True
            modifier.show_render = True
        except FBP_DATA_ERRORS:
            pass

    base_stage = stage_by_token.get(_FBP_MIXED_SHADER_STAGE_BASE)
    if base_stage is None:
        return changed
    desired_managed = [base_stage]
    for token in reversed(order):
        definition = fbp_effect_definition(_fbp_effect_ref_effect_id(token))
        if definition.get("kind") == "SHADER":
            modifier = stage_by_token.get(token)
        elif definition.get("kind") == "GEOMETRY":
            modifier = _fbp_geometry_modifier_for_token(rig, token)
        else:
            modifier = None
        if modifier is not None and modifier not in desired_managed:
            desired_managed.append(modifier)

    original = list(getattr(plane, "modifiers", ()))
    managed_slots = [
        index
        for index, modifier in enumerate(original)
        if _fbp_geometry_effect_id_for_modifier(modifier)
        or _fbp_mixed_shader_stage_token(modifier)
    ]
    current_managed = [original[index] for index in managed_slots]
    desired_keys = {_fbp_modifier_pointer(modifier) for modifier in desired_managed}
    desired_managed.extend(
        modifier
        for modifier in current_managed
        if _fbp_modifier_pointer(modifier) not in desired_keys
    )
    if len(desired_managed) == len(managed_slots):
        desired_full = list(original)
        for slot, modifier in zip(
            managed_slots, desired_managed, strict=True
        ):
            desired_full[slot] = modifier
        if desired_full != original:
            changed = _fbp_apply_modifier_order_exact(
                plane, desired_full
            ) or changed

    changed = _fbp_refresh_mixed_shader_stage_materials(rig) or changed
    # Every material-producing Mesh stage consumes the same cumulative result
    # represented by the immediately preceding shader adapters.
    for modifier in tuple(getattr(plane, "modifiers", ())):
        effect_id = _fbp_geometry_effect_id_for_modifier(modifier)
        if not effect_id:
            continue
        instance_id = (
            _fbp_geometry_modifier_instance_id(
                rig, modifier, effect_id, ensure=True
            )
            if _fbp_effect_uses_multi_instances(effect_id) else ""
        )
        changed = _fbp_apply_geometry_material_composites(
            rig, modifier, effect_id, instance_id
        ) or changed
    return changed


def _fbp_apply_mixed_effect_order(rig, desired_order):
    """Apply a mixed order and derive each native backend's relative order."""
    desired = list(_fbp_normalize_effect_refs(desired_order))
    current = _fbp_mixed_effect_tokens(rig)
    if set(current) != set(desired) or len(current) != len(desired):
        return False
    chain_keys = {
        _fbp_effect_chain_key(_fbp_effect_ref_effect_id(token))
        for token in desired
    }
    chain_keys.discard(("", ""))
    snapshots = {
        key: tuple(_fbp_effect_chain_tokens(rig, key)) for key in chain_keys
    }
    for key in chain_keys:
        native_current = list(snapshots[key])
        native_set = set(native_current)
        # UI rows are layers: Blender evaluates them from the bottom upward.
        native_desired = list(reversed([
            token for token in desired if token in native_set
        ]))
        if native_current == native_desired:
            continue
        if not _fbp_apply_effect_chain_order(rig, key, native_desired):
            for restore_key, restore_order in snapshots.items():
                _fbp_apply_effect_chain_order(rig, restore_key, restore_order)
            return False
    if not _fbp_persist_mixed_effect_order(rig, desired):
        for restore_key, restore_order in snapshots.items():
            _fbp_apply_effect_chain_order(rig, restore_key, restore_order)
        return False
    _fbp_sync_mixed_effect_pipeline(rig)
    _fbp_refresh_geometry_source_materials(rig)
    return True


def _fbp_mixed_selection_order(rig, effect_refs, action):
    order = _fbp_mixed_effect_tokens(rig)
    selected_set = set(_fbp_normalize_effect_refs(effect_refs))
    selected = [token for token in order if token in selected_set]
    if not selected:
        return ()
    action = str(action or "UP").upper()
    desired = list(order)
    if action == "UP":
        for index in range(1, len(desired)):
            if desired[index] in selected_set and desired[index - 1] not in selected_set:
                desired[index - 1], desired[index] = desired[index], desired[index - 1]
    elif action == "DOWN":
        for index in range(len(desired) - 2, -1, -1):
            if desired[index] in selected_set and desired[index + 1] not in selected_set:
                desired[index], desired[index + 1] = desired[index + 1], desired[index]
    elif action == "TOP":
        desired = selected + [token for token in order if token not in selected_set]
    elif action == "BOTTOM":
        desired = [token for token in order if token not in selected_set] + selected
    else:
        return ()
    return tuple(desired)



def _fbp_selection_action_would_change(rig, effect_refs, action):
    desired = _fbp_mixed_selection_order(rig, effect_refs, action)
    return bool(desired and list(desired) != _fbp_mixed_effect_tokens(rig))



def _fbp_move_effect_selection_on_rig(rig, effect_refs, action):
    desired = _fbp_mixed_selection_order(rig, effect_refs, action)
    if not desired or list(desired) == _fbp_mixed_effect_tokens(rig):
        return False
    return _fbp_apply_mixed_effect_order(rig, desired)



def _fbp_effect_chain_snapshots(rig, effect_ids):
    snapshots = {}
    for value in effect_ids:
        effect_id = _fbp_effect_ref_effect_id(value)
        key = _fbp_effect_chain_key(effect_id)
        if key[0] and key not in snapshots:
            snapshots[key] = tuple(_fbp_effect_chain_tokens(rig, key))
    return snapshots



def _fbp_restore_effect_chain_snapshots(rig, snapshots):
    restored = True
    for key, desired in snapshots.items():
        if not _fbp_apply_effect_chain_order(rig, key, desired):
            if _fbp_effect_chain_tokens(rig, key) != list(desired):
                restored = False
    return restored



def _fbp_capture_effect_group_state(rig):
    """Capture every concrete group assignment and folder display property."""
    groups = fbp_sync_effect_groups(rig)
    assignments = {
        token: group_id for group_id, members in groups.items() for token in members
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
    return {"assignments": assignments, "records": records}



def _fbp_restore_effect_group_state(rig, state):
    """Restore a concrete group snapshot after a cancelled transaction."""
    state = dict(state or {})
    assignments = dict(state.get("assignments", {}) or {})
    records = dict(state.get("records", {}) or {})
    tokens = [
        _fbp_effect_ref(
            item.get("effect_id", ""),
            item.get("instance_id", "") if _fbp_effect_uses_multi_instances(item.get("effect_id", "")) else "",
        )
        for item in fbp_effect_instance_records_for_rig(
            rig, ensure=True, sync_storage=False
        )
        if fbp_effect_definition(item.get("effect_id", "")).get("kind") in {"SHADER", "GEOMETRY"}
    ]
    for token in tokens:
        effect_id, instance_id = _fbp_effect_ref_parts(token)
        fbp_set_effect_group_id(rig, effect_id, "", instance_id=instance_id)
    try:
        while len(rig.fbp_effect_groups):
            rig.fbp_effect_groups.remove(len(rig.fbp_effect_groups) - 1)
    except FBP_DATA_ERRORS:
        pass
    for group_id, metadata in records.items():
        record = fbp_ensure_effect_group_record(
            rig, group_id, str(metadata.get("name", "") or "Effect Group")
        )
        if record is not None:
            try:
                record.collapsed = bool(metadata.get("collapsed", False))
                record.color_tag = str(metadata.get("color_tag", "NONE") or "NONE")
            except FBP_DATA_ERRORS:
                pass
    for token in tokens:
        effect_id, instance_id = _fbp_effect_ref_parts(token)
        group_id = str(assignments.get(token, "") or "")
        metadata = records.get(group_id, {})
        fbp_set_effect_group_id(
            rig, effect_id, group_id,
            instance_id=instance_id,
            group_name=str(metadata.get("name", "") or ""),
        )
    fbp_sync_effect_groups(rig)
    return True



def fbp_drag_effect_step_transactional(rigs, effect_ref, direction):
    """Move one concrete effect and update membership at the crossed row."""
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    refs = _fbp_normalize_effect_refs((effect_ref,))
    direction = str(direction or "UP").upper()
    if not rigs or len(refs) != 1 or direction not in {"UP", "DOWN"}:
        return False
    token = refs[0]
    effect_id, instance_id = _fbp_effect_ref_parts(token)
    if any(not _fbp_effect_ref_is_active(rig, token) for rig in rigs):
        return False

    plans = {}
    for rig in rigs:
        order = tuple(_fbp_mixed_effect_tokens(rig))
        if token not in order:
            return False
        index = order.index(token)
        target_index = index - 1 if direction == "UP" else index + 1
        if not (0 <= target_index < len(order)):
            return False
        crossed_token = order[target_index]
        group_state = _fbp_capture_effect_group_state(rig)
        assignments = dict(group_state.get("assignments", {}) or {})
        plans[rig] = {
            "mixed": order,
            "groups": group_state,
            "source_group": str(assignments.get(token, "") or ""),
            "crossed_group": str(assignments.get(crossed_token, "") or ""),
        }

    moved = []
    for rig in rigs:
        if _fbp_move_effect_selection_on_rig(rig, (token,), direction):
            moved.append(rig)
            continue
        for target in reversed(moved):
            _fbp_apply_mixed_effect_order(target, plans[target]["mixed"])
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
            metadata = plans[rig]["groups"].get("records", {}).get(target_group, {})
            if not fbp_set_effect_group_id(
                rig, effect_id, target_group,
                instance_id=instance_id,
                group_name=str(metadata.get("name", "") or ""),
            ):
                for target in rigs:
                    _fbp_apply_mixed_effect_order(target, plans[target]["mixed"])
                    _fbp_restore_effect_group_state(target, plans[target]["groups"])
                return False
            if target_group:
                record = _fbp_effect_group_record(rig, target_group)
                if record is not None:
                    try:
                        record.collapsed = bool(metadata.get("collapsed", False))
                        record.color_tag = str(metadata.get("color_tag", "NONE") or "NONE")
                    except FBP_DATA_ERRORS:
                        pass

    for rig in rigs:
        fbp_sync_effect_groups(rig)
        fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
    _fbp_select_effect_row(rigs[0], effect_id, rigs, instance_id=instance_id)
    return True



def fbp_can_move_effect_selection(rigs, effect_refs, action):
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    effect_refs = _fbp_normalize_effect_refs(effect_refs)
    if not rigs or not effect_refs:
        return False
    if any(
        any(not _fbp_effect_ref_is_active(rig, token) for token in effect_refs)
        for rig in rigs
    ):
        return False
    return all(
        _fbp_selection_action_would_change(rig, effect_refs, action)
        for rig in rigs
    )



def fbp_move_effect_selection_transactional(rigs, effect_refs, action):
    """Move concrete checked effects as stable blocks on every selected layer."""
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    effect_refs = _fbp_normalize_effect_refs(effect_refs)
    if rigs:
        effect_refs = fbp_expand_effect_selection_to_groups(rigs[0], effect_refs)
        if any(
            fbp_expand_effect_selection_to_groups(rig, effect_refs) != effect_refs
            for rig in rigs[1:]
        ):
            return False
    action = str(action or "UP").upper()
    if action not in {"UP", "DOWN", "TOP", "BOTTOM"}:
        return False
    if not fbp_can_move_effect_selection(rigs, effect_refs, action):
        return False
    snapshots = {rig: tuple(_fbp_mixed_effect_tokens(rig)) for rig in rigs}
    moved = []
    for rig in rigs:
        if _fbp_move_effect_selection_on_rig(rig, effect_refs, action):
            moved.append(rig)
            continue
        for target in reversed(moved):
            _fbp_apply_mixed_effect_order(target, snapshots.get(target, ()))
        _fbp_apply_mixed_effect_order(rig, snapshots.get(rig, ()))
        for target in rigs:
            fbp_sync_effect_items(target, rigs if target is rigs[0] else [target])
        return False
    for rig in rigs:
        fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
    if rigs and effect_refs:
        effect_id, instance_id = _fbp_effect_ref_parts(effect_refs[0])
        _fbp_select_effect_row(rigs[0], effect_id, rigs, instance_id=instance_id)
    return True



def _fbp_apply_shader_chain_order_direct(rig, stage, desired):
    """Write one complete shader-stage order and rebuild each material once."""
    _fbp_set_rig_shader_stage_order(rig, stage, desired)
    for material in _fbp_plane_materials(rig):
        active = _fbp_get_shader_stage_order(material, stage)
        if not active:
            continue
        material_order = [item for item in desired if item in active]
        material_order.extend(item for item in active if item not in material_order)
        if material_order == active:
            continue
        _fbp_set_shader_stage_order(material, stage, material_order)
        _fbp_rebuild_shader_stage(material, stage)
    _fbp_invalidate_effect_ids_cache(rig)
    if any(_fbp_effect_ref_instance_id(token) for token in desired):
        fbp_effect_instance_records_for_rig(rig, ensure=True, sync_storage=True)
    _fbp_relink_effect_shells(rig)


def _fbp_sync_effect_shell_values(rig):
    """Carry Frame By Plane writes to the effect's modifier, and back."""
    try:
        from .effect_shells import fbp_shell_sync_values
        return fbp_shell_sync_values(rig)
    except (ImportError, *FBP_DATA_ERRORS):
        return 0


def _fbp_relink_effect_shells(rig):
    """Restore modifier-driven inputs after a shader stage was rebuilt."""
    try:
        from .effect_shells import fbp_shell_refresh_links
        return fbp_shell_refresh_links(rig)
    except (ImportError, *FBP_DATA_ERRORS):
        return 0


def _fbp_apply_geometry_chain_order_direct(rig, desired):
    """Reorder every managed Mesh-effect modifier in one exact pass."""
    plane = _fbp_plane(rig)
    if not plane:
        return False
    by_token = {}
    try:
        for modifier in plane.modifiers:
            effect_id = _fbp_geometry_effect_id_for_modifier(modifier)
            if effect_id and effect_id not in by_token:
                by_token[effect_id] = modifier
    except FBP_DATA_ERRORS:
        return False
    requested = [by_token[token] for token in desired if token in by_token]
    if len(requested) != len(desired):
        return False
    if not _fbp_reorder_geometry_effect_modifiers(plane, requested):
        return False
    _fbp_invalidate_effect_ids_cache(rig)
    return True


def _fbp_apply_effect_chain_order(rig, chain_key, desired_order):
    """Apply one concrete compatible-chain order.

    The complete order is written in one pass so each material stage is
    rebuilt once instead of once per one-step move. The one-step path remains
    as a fallback for chains whose stored order cannot be resolved directly.
    """
    desired = [
        _fbp_effect_ref(*_fbp_effect_ref_parts(item))
        for item in tuple(desired_order or ()) if item
    ]
    if not desired:
        return False
    current = _fbp_effect_chain_tokens(rig, chain_key)
    if set(current) != set(desired) or len(current) != len(desired):
        return False
    changed = current != desired
    if not changed:
        return True
    kind, stage = chain_key
    if kind == "SHADER":
        _fbp_apply_shader_chain_order_direct(rig, stage, desired)
    elif kind == "GEOMETRY":
        _fbp_apply_geometry_chain_order_direct(rig, desired)
    if _fbp_effect_chain_tokens(rig, chain_key) == desired:
        return True
    for target_index, token in enumerate(desired):
        while True:
            current = _fbp_effect_chain_tokens(rig, chain_key)
            if token not in current:
                return False
            current_index = current.index(token)
            if current_index <= target_index:
                break
            if not _fbp_move_effect_ref(rig, token, "UP", sync_items=False):
                return False
    return (not changed) or _fbp_effect_chain_tokens(rig, chain_key) == desired
def fbp_sort_effect_stacks_transactional(rigs, recommended_order):
    """Sort the one mixed stack while preserving group blocks and rollback."""
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
        current = tuple(_fbp_mixed_effect_tokens(rig))
        groups = fbp_sync_effect_groups(rig)
        group_by_token = {
            token: group_id
            for group_id, members in groups.items()
            for token in members
        }
        blocks = []
        consumed = set()
        for index, token in enumerate(current):
            if token in consumed:
                continue
            group_id = group_by_token.get(token, "")
            members = tuple(
                member for member in current
                if group_id and group_by_token.get(member, "") == group_id
            )
            block = members or (token,)
            consumed.update(block)
            rank = min(
                rank_by_effect.get(
                    _fbp_effect_ref_effect_id(member),
                    len(rank_by_effect) + index,
                )
                for member in block
            )
            blocks.append((rank, index, block))
        blocks.sort(key=lambda value: (value[0], value[1]))
        desired = tuple(
            token for _rank, _index, block in blocks for token in block
        )
        plans[rig] = (current, desired)
        any_change = any_change or current != desired
    if not any_change:
        return False

    changed = []
    for rig in rigs:
        current, desired = plans[rig]
        if current == desired:
            continue
        if _fbp_apply_mixed_effect_order(rig, desired):
            changed.append(rig)
            continue
        for target in reversed(changed):
            _fbp_apply_mixed_effect_order(target, plans[target][0])
        _fbp_apply_mixed_effect_order(rig, current)
        for target in rigs:
            fbp_sync_effect_items(
                target, rigs if target is rigs[0] else [target]
            )
        return False
    for rig in rigs:
        fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
    return True


def _fbp_relative_effect_order(rig, effect_refs, target_ref, placement):
    """Return one mixed-stack order for a concrete block move."""
    selected = _fbp_normalize_effect_refs(effect_refs)
    target_ref = _fbp_normalize_effect_refs((target_ref,))
    target_ref = target_ref[0] if target_ref else ""
    if not selected or not target_ref or target_ref in selected:
        return ()
    order = _fbp_mixed_effect_tokens(rig)
    if target_ref not in order or any(token not in order for token in selected):
        return ()
    selected_set = set(selected)
    stable_block = [token for token in order if token in selected_set]
    remaining = [token for token in order if token not in selected_set]
    try:
        target_index = remaining.index(target_ref)
    except ValueError:
        return ()
    insert_index = target_index if str(placement or "BEFORE").upper() == "BEFORE" else target_index + 1
    desired = remaining[:insert_index] + stable_block + remaining[insert_index:]
    return tuple(desired)



def fbp_move_effect_selection_relative_transactional(
    rigs, effect_refs, target_ref, placement
):
    """Move one concrete checked block before or after another instance."""
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    effect_refs = _fbp_normalize_effect_refs(effect_refs)
    if rigs:
        effect_refs = fbp_expand_effect_selection_to_groups(rigs[0], effect_refs)
        if any(
            fbp_expand_effect_selection_to_groups(rig, effect_refs) != effect_refs
            for rig in rigs[1:]
        ):
            return False
    target_refs = _fbp_normalize_effect_refs((target_ref,))
    target_ref = target_refs[0] if target_refs else ""
    placement = str(placement or "BEFORE").upper()
    if not rigs or not effect_refs or not target_ref or placement not in {"BEFORE", "AFTER"}:
        return False
    plans = {}
    any_change = False
    for rig in rigs:
        desired = _fbp_relative_effect_order(rig, effect_refs, target_ref, placement)
        if not desired:
            return False
        current = tuple(_fbp_mixed_effect_tokens(rig))
        needs_change = current != desired
        any_change = any_change or needs_change
        plans[rig] = (current, desired, needs_change)
    if not any_change:
        return False
    changed_rigs = []
    for rig in rigs:
        _current, desired, needs_change = plans[rig]
        if not needs_change:
            continue
        if _fbp_apply_mixed_effect_order(rig, desired):
            changed_rigs.append(rig)
            continue
        for target in reversed(changed_rigs):
            original, _desired, _needs_change = plans[target]
            _fbp_apply_mixed_effect_order(target, original)
        original, _desired, _needs_change = plans[rig]
        _fbp_apply_mixed_effect_order(rig, original)
        for target in rigs:
            fbp_sync_effect_items(target, rigs if target is rigs[0] else [target])
        return False
    for rig in rigs:
        fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
    first_effect, first_instance = _fbp_effect_ref_parts(effect_refs[0])
    _fbp_select_effect_row(rigs[0], first_effect, rigs, instance_id=first_instance)
    return True



def _fbp_group_effect_selection_impl(
    rigs, effect_refs, *, group_id="", group_name=""
):
    """Assign checked compatible concrete effects to one persistent group."""
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    effect_refs = _fbp_normalize_effect_refs(effect_refs)
    if not rigs or not effect_refs:
        return ""
    chain_keys = {
        _fbp_effect_chain_key(_fbp_effect_ref_effect_id(token))
        for token in effect_refs
    }
    chain_keys.discard(("", ""))
    if len(chain_keys) != 1:
        return ""
    if any(
        any(not _fbp_effect_ref_is_active(rig, token) for token in effect_refs)
        for rig in rigs
    ):
        return ""
    chain_key = next(iter(chain_keys))
    selected_set = set(effect_refs)
    for rig in rigs:
        # The unified UI can interleave Shader and Geometry chains. Native-chain
        # adjacency alone is therefore insufficient: a folder must also be one
        # visually contiguous block in the mixed stack.
        mixed_order = _fbp_mixed_effect_tokens(rig)
        mixed_positions = [
            index
            for index, token in enumerate(mixed_order)
            if token in selected_set
        ]
        if (
            len(mixed_positions) != len(effect_refs)
            or mixed_positions
            != list(range(min(mixed_positions), max(mixed_positions) + 1))
        ):
            return ""
        order = _fbp_logical_effect_chain_tokens(rig, chain_key)
        positions = [index for index, token in enumerate(order) if token in selected_set]
        if (
            len(positions) != len(effect_refs)
            or positions != list(range(min(positions), max(positions) + 1))
        ):
            return ""

    group_id = str(group_id or new_effect_group_id())
    group_name = str(group_name or _fbp_next_effect_group_name(rigs[0]))
    snapshots = {}
    for rig in rigs:
        groups = fbp_sync_effect_groups(rig)
        group_by_token = {
            token: current_group
            for current_group, members in groups.items()
            for token in members
        }
        snapshots[rig] = {
            token: (
                group_by_token.get(token, ""),
                fbp_effect_group_name(rig, group_by_token.get(token, "")),
            )
            for token in effect_refs
        }
    changed = []
    for rig in rigs:
        for token in effect_refs:
            effect_id, instance_id = _fbp_effect_ref_parts(token)
            if fbp_set_effect_group_id(
                rig, effect_id, group_id,
                instance_id=instance_id, group_name=group_name,
            ):
                changed.append((rig, token))
                continue
            for target_rig, target_token in reversed(changed):
                old_group, old_name = snapshots[target_rig][target_token]
                old_effect, old_instance = _fbp_effect_ref_parts(target_token)
                fbp_set_effect_group_id(
                    target_rig, old_effect, old_group,
                    instance_id=old_instance, group_name=old_name,
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
        rigs[0], effect_refs, mode="REPLACE", eligible_ids=effect_refs
    )
    return group_id



def _fbp_restore_effect_group_transaction(rigs, group_states, chain_states):
    for rig in tuple(rigs or ()):
        _fbp_restore_effect_chain_snapshots(rig, chain_states.get(rig, {}))
        _fbp_restore_effect_group_state(rig, group_states.get(rig, {}))
        fbp_sync_effect_groups(rig)
    for index, rig in enumerate(tuple(rigs or ())):
        fbp_sync_effect_items(rig, rigs if index == 0 else [rig])
    return True


def fbp_group_effect_selection_transactional(rigs, effect_refs):
    """Group effects atomically and persist enough intent for crash recovery."""
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    effect_refs = _fbp_normalize_effect_refs(effect_refs)
    if not rigs or not effect_refs:
        return ""
    group_id = new_effect_group_id()
    group_name = _fbp_next_effect_group_name(rigs[0])
    group_states = {rig: _fbp_capture_effect_group_state(rig) for rig in rigs}
    chain_states = {
        rig: _fbp_effect_chain_snapshots(rig, effect_refs)
        for rig in rigs
    }
    try:
        with FBPTransaction(
            "Group effect selection",
            kind="EFFECT_GROUP",
            journal_owner=rigs[0],
            context={
                "rig_names": tuple(str(getattr(rig, "name", "") or "") for rig in rigs),
                "effect_refs": tuple(effect_refs),
                "group_id": group_id,
                "group_name": group_name,
            },
        ) as transaction:
            transaction.defer_rollback(
                _fbp_restore_effect_group_transaction,
                tuple(rigs),
                group_states,
                chain_states,
                label="restore effect groups and order",
            )
            transaction.checkpoint("ASSIGN_GROUP", progress=0.25)
            applied_group_id = _fbp_group_effect_selection_impl(
                rigs,
                effect_refs,
                group_id=group_id,
                group_name=group_name,
            )
            if not applied_group_id:
                raise RuntimeError("Effect group assignment returned no group ID")
            transaction.checkpoint(
                "VALIDATED",
                progress=1.0,
                group_id=group_id,
                group_name=group_name,
            )
            transaction.commit()
            return applied_group_id
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError) as exc:
        fbp_warn(
            "Could not group effect selection atomically",
            exc,
            event="effects.group.transaction",
        )
        return ""


def fbp_ungroup_effect_selection_transactional(rigs, effect_refs):
    """Remove concrete selected effects while preserving contiguous folders."""
    rigs = [rig for rig in tuple(rigs or ()) if rig]
    effect_refs = _fbp_normalize_effect_refs(effect_refs)
    if not rigs or not effect_refs:
        return False

    plans = {}
    any_grouped = False
    for rig in rigs:
        groups = fbp_sync_effect_groups(rig)
        group_by_token = {
            token: group_id
            for group_id, members in groups.items()
            for token in members
        }
        selected_grouped = [
            token for token in effect_refs if token in group_by_token
        ]
        if selected_grouped:
            any_grouped = True
        chain_snapshots = _fbp_effect_chain_snapshots(rig, selected_grouped)
        current_order = list(_fbp_mixed_effect_tokens(rig))
        desired_order = list(current_order)
        for _group_id, members in groups.items():
            selected = [token for token in members if token in selected_grouped]
            remaining = [token for token in members if token not in selected_grouped]
            if not selected or not remaining:
                continue
            # Groups are presented in the persisted top-to-bottom mixed stack,
            # while Blender's native Shader/Geometry chains are stored in the
            # opposite evaluation direction. Rebuild the visible order here;
            # applying native order directly would put the detached row on the
            # wrong side of the remaining folder.
            ordered_selected = [
                token for token in desired_order if token in selected
            ]
            without_selected = [
                token for token in desired_order if token not in selected
            ]
            remaining_positions = [
                without_selected.index(token)
                for token in remaining if token in without_selected
            ]
            if not remaining_positions:
                continue
            insert_at = max(remaining_positions) + 1
            desired_order = (
                without_selected[:insert_at]
                + ordered_selected
                + without_selected[insert_at:]
            )
        plans[rig] = {
            "groups": _fbp_capture_effect_group_state(rig),
            "chains": chain_snapshots,
            "current": current_order,
            "selected": selected_grouped,
            "desired": desired_order,
        }
    if not any_grouped:
        return False

    completed = []
    for rig in rigs:
        plan = plans[rig]
        ok = True
        for token in plan["selected"]:
            effect_id, instance_id = _fbp_effect_ref_parts(token)
            if not fbp_set_effect_group_id(
                rig, effect_id, "", instance_id=instance_id
            ):
                ok = False
                break
        if ok and plan["desired"] != plan["current"]:
            ok = _fbp_apply_mixed_effect_order(rig, plan["desired"])
        if ok:
            completed.append(rig)
            continue
        for target in completed + [rig]:
            _fbp_apply_mixed_effect_order(target, plans[target]["current"])
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
        order_token = _fbp_shader_order_token_for_effect(rig, effect_id, order)
        if not order_token:
            materials = _fbp_plane_materials(rig)
            order = _fbp_get_shader_stage_order(materials[0], stage) if materials else []
            order_token = _fbp_shader_order_token_for_effect(rig, effect_id, order)
        if not order_token:
            return False
        target = order.index(order_token) + step
        return 0 <= target < len(order)
    return False


class FBP_OT_DragEffect(Operator):
    bl_idname = "fbp.drag_effect"
    bl_label = "Drag Effect"
    bl_description = "Drag vertically to reorder one concrete effect instance or an entire group"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    effect_id: StringProperty(name="Effect ID", default="", options={"SKIP_SAVE"})
    instance_id: StringProperty(name="Instance ID", default="", options={"SKIP_SAVE"})
    group_id: StringProperty(name="Effect Group ID", default="", options={"SKIP_SAVE"})

    def _current_rigs(self):
        rigs = []
        for name in getattr(self, "_rig_names", ()):
            rig = bpy.data.objects.get(name)
            if rig is not None:
                rigs.append(rig)
        return rigs

    def _restore_cursor(self, context):
        restore_modal_cursor(context)

    def _redraw(self, context):
        fbp_tag_redraw(context, area_types={"VIEW_3D"})

    def _move_once(self, direction):
        refs = getattr(self, "_effect_refs", (self._effect_ref,))
        if len(refs) == 1 and not bool(getattr(self, "_move_group", False)):
            return fbp_drag_effect_step_transactional(self._current_rigs(), refs[0], direction)
        return fbp_move_effect_selection_transactional(self._current_rigs(), refs, direction)

    def _restore_initial_state(self):
        rigs = self._current_rigs()
        initial_orders = getattr(self, "_initial_orders", {})
        initial_groups = getattr(self, "_initial_groups", {})
        for rig in rigs:
            name = str(getattr(rig, "name", "") or "")
            _fbp_apply_mixed_effect_order(rig, initial_orders.get(name, ()))
            _fbp_restore_effect_group_state(rig, initial_groups.get(name, {}))
        for rig in rigs:
            fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])

    def invoke(self, context, event):
        rigs = _fbp_selected_rigs(context)
        effect_id = fbp_normalize_effect_id(self.effect_id)
        instance_id = str(self.instance_id or "") if _fbp_effect_uses_multi_instances(effect_id) else ""
        token = _fbp_effect_ref(effect_id, instance_id)
        definition = fbp_effect_definition(effect_id)
        if (
            not rigs
            or definition.get("kind") not in {"SHADER", "GEOMETRY"}
            or any(not _fbp_effect_ref_is_active(rig, token) for rig in rigs)
        ):
            return {"CANCELLED"}
        self.effect_id = effect_id
        self.instance_id = instance_id
        self._effect_ref = token
        fbp_sync_effect_items(rigs[0], rigs)
        requested_group = str(getattr(self, "group_id", "") or "")
        selected_instances = fbp_selected_effect_instances(
            rigs[0], fallback_active=False, movable_only=True,
            categories={"BASE", "2D", "MASK", "3D"},
        )
        selected_refs = tuple(_fbp_effect_ref(eid, iid) for eid, iid in selected_instances)
        if requested_group:
            members = tuple(fbp_effect_group_members(rigs[0], requested_group))
            if not members or token not in members:
                return {"CANCELLED"}
            self._effect_refs = members
            self._move_group = True
        else:
            self._effect_refs = tuple(selected_refs if token in selected_refs else (token,))
            self._move_group = False
        if any(
            any(not _fbp_effect_ref_is_active(rig, item) for item in self._effect_refs)
            for rig in rigs
        ):
            return {"CANCELLED"}
        self._rig_names = tuple(str(getattr(rig, "name", "") or "") for rig in rigs)
        self._initial_orders = {
            str(getattr(rig, "name", "") or ""): tuple(
                _fbp_mixed_effect_tokens(rig)
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
            _fbp_select_effect_row(rigs[0], effect_id, rigs, instance_id=instance_id)
        self._fbp_ui_modal_mutation_active = False
        try:
            from .operator_common import fbp_begin_ui_modal_mutation
            if not fbp_begin_ui_modal_mutation(self):
                return {"CANCELLED"}
            context.window_manager.modal_handler_add(self)
            context.window.cursor_modal_set("SCROLL_Y")
        except Exception as exc:
            try:
                from .operator_common import fbp_end_ui_modal_mutation
                fbp_end_ui_modal_mutation(self)
            except Exception:
                pass
            self._restore_cursor(context)
            fbp_warn("Could not start effect UIList drag", exc)
            return {"CANCELLED"}
        self._redraw(context)
        return {"RUNNING_MODAL"}

    def _finish_modal(self, context, *, cancelled):
        if cancelled:
            self._restore_initial_state()
        self._restore_cursor(context)
        try:
            from .operator_common import fbp_end_ui_modal_mutation
            fbp_end_ui_modal_mutation(self)
        except Exception:
            pass
        self._redraw(context)
        return {"CANCELLED"} if cancelled else {"FINISHED"}

    def modal(self, context, event):
        try:
            try:
                from .operator_common import fbp_touch_ui_modal_mutation
                fbp_touch_ui_modal_mutation(self)
            except Exception:
                pass
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
            if event.type in {"ESC", "RIGHTMOUSE", "WINDOW_DEACTIVATE"}:
                return self._finish_modal(context, cancelled=True)
            if event.type == "LEFTMOUSE" and event.value == "RELEASE":
                return self._finish_modal(context, cancelled=not bool(self._history))
            return {"RUNNING_MODAL"}
        except Exception as exc:
            fbp_warn("Effect UIList drag aborted after an unexpected error", exc)
            try:
                return self._finish_modal(context, cancelled=True)
            except Exception:
                try:
                    self._restore_cursor(context)
                except Exception:
                    pass
                try:
                    from .operator_common import fbp_end_ui_modal_mutation
                    fbp_end_ui_modal_mutation(self)
                except Exception:
                    pass
                return {"CANCELLED"}



class FBP_OT_MoveSelectedEffectsRelative(Operator):
    bl_idname = "fbp.move_selected_effects_relative"
    bl_label = "Move Selected Effects Before / After"
    bl_description = "Move concrete checked effect instances before or after the chosen destination"
    bl_options = {"REGISTER", "UNDO"}

    target_effect_id: StringProperty(name="Destination Effect", default="", options={"SKIP_SAVE"})
    target_instance_id: StringProperty(name="Destination Instance", default="", options={"SKIP_SAVE"})
    placement: EnumProperty(
        name="Placement",
        items=(("BEFORE", "Before", "Insert before"), ("AFTER", "After", "Insert after")),
        default="BEFORE", options={"SKIP_SAVE"},
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
        selected_instances = fbp_selected_effect_instances(
            rig, fallback_active=True, movable_only=True,
            categories=_fbp_effect_view_categories(context),
        )
        effect_refs = [_fbp_effect_ref(effect_id, instance_id) for effect_id, instance_id in selected_instances]
        target_ref = _fbp_effect_ref(self.target_effect_id, self.target_instance_id)
        if not effect_refs:
            return {"CANCELLED"}
        if not fbp_move_effect_selection_relative_transactional(
            rigs, effect_refs, target_ref, self.placement
        ):
            self.report({"INFO"}, "Select instances from one compatible chain and choose another destination")
            return {"CANCELLED"}
        return {"FINISHED"}



class FBP_OT_ToggleEffectSolo(Operator):
    bl_idname = "fbp.toggle_effect_solo"
    bl_label = "Solo Effect"
    bl_description = "Solo this effect instance in the viewport; additional Solo buttons add instances, and disabling the last Solo restores the complete stack"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(
        name="Effect ID",
        description="Effect to add to or remove from the viewport Solo set",
        default="",
        options={"SKIP_SAVE"},
    )
    instance_id: StringProperty(
        name="Instance ID",
        description="Persistent identity of one concrete duplicate",
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
            targets = (_fbp_effect_ref(effect_id, self.instance_id),) if effect_id else ()
        if not targets:
            return {"CANCELLED"}
        changed = False
        for rig in rigs:
            if all(_fbp_effect_ref_is_active(rig, token) for token in targets):
                changed = fbp_toggle_effect_solo(rig, targets) or changed
        fbp_sync_effect_items(source, rigs)
        return {"FINISHED"} if changed else {"CANCELLED"}



class FBP_OT_SetSelectedEffectsVisibility(Operator):
    bl_idname = "fbp.set_selected_effects_visibility"
    bl_label = "Set Selected Effects Visibility"
    bl_description = "Show or hide checked effects everywhere, or temporarily solo them in the viewport"
    bl_options = {"REGISTER", "UNDO"}

    channel: EnumProperty(description='Choose the Channel option for this effect-stack action. Hover each entry for the specific mode when Blender exposes enum item help.',
        name="Channel",
        items=(
            ("BOTH", "Hide", "Change the single visibility state in viewport and render"),
            ("VIEWPORT", "Solo Viewport", "Temporary viewport-only state used by Solo"),
        ),
        default="BOTH",
        options={"SKIP_SAVE"},
    )
    mode: EnumProperty(description='Action to run',
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
        selected_instances = fbp_selected_effect_instances(
            rig,
            fallback_active=True,
            movable_only=True,
            categories=categories,
        )
        all_instances = []
        seen = set()
        counts = {}
        for item in getattr(rig, "fbp_effects", ()):
            effect_id = fbp_normalize_effect_id(getattr(item, "effect_id", ""))
            definition = fbp_effect_definition(effect_id)
            if (
                str(getattr(item, "row_type", "EFFECT") or "EFFECT") != "EFFECT"
                or definition.get("kind") not in {"SHADER", "GEOMETRY"}
                or str(definition.get("category", "2D") or "2D") not in categories
            ):
                continue
            instance_id = (
                str(getattr(item, "instance_id", "") or "")
                if _fbp_effect_uses_multi_instances(effect_id)
                else ""
            )
            key = (effect_id, instance_id)
            if key not in seen:
                all_instances.append(key)
                seen.add(key)
                counts[effect_id] = counts.get(effect_id, 0) + 1
        duplicated_multi = {
            effect_id for effect_id, count in counts.items()
            if count > 1 and _fbp_effect_uses_multi_instances(effect_id)
        }
        if len(rigs) > 1 and duplicated_multi:
            self.report(
                {"INFO"},
                "Change duplicated effect instances on one layer at a time",
            )
            return {"CANCELLED"}
        selected_set = set(selected_instances)
        if self.mode != "SHOW_ALL" and not selected_set:
            return {"CANCELLED"}

        changed = 0
        if len(rigs) == 1:
            for effect_id, instance_id in all_instances:
                if self.mode == "SHOW_ALL":
                    state = True
                elif self.mode == "SOLO_SELECTED":
                    state = (effect_id, instance_id) in selected_set
                elif self.mode == "HIDE_SELECTED":
                    if (effect_id, instance_id) not in selected_set:
                        continue
                    state = False
                else:
                    if (effect_id, instance_id) not in selected_set:
                        continue
                    state = True
                if self.channel == "BOTH":
                    changed += int(
                        fbp_set_effect_global_visible(
                            rig, effect_id, state, instance_id=instance_id
                        )
                    )
                elif self.channel == "RENDER":
                    changed += int(
                        fbp_set_effect_render_visible(
                            rig, effect_id, state, instance_id=instance_id
                        )
                    )
                else:
                    changed += int(
                        fbp_set_effect_visible(
                            rig, effect_id, state, instance_id=instance_id
                        )
                    )
        else:
            selected_ids = {effect_id for effect_id, _instance_id in selected_set}
            visible_ids = list(dict.fromkeys(effect_id for effect_id, _iid in all_instances))
            for target_rig in rigs:
                target_ids = [
                    effect_id for effect_id in visible_ids
                    if fbp_effect_is_active(target_rig, effect_id)
                ]
                if self.mode == "SOLO_SELECTED" and not any(
                    effect_id in selected_ids for effect_id in target_ids
                ):
                    continue
                for effect_id in target_ids:
                    if self.mode == "SHOW_ALL":
                        state = True
                    elif self.mode == "SOLO_SELECTED":
                        state = effect_id in selected_ids
                    elif self.mode == "HIDE_SELECTED":
                        if effect_id not in selected_ids:
                            continue
                        state = False
                    else:
                        if effect_id not in selected_ids:
                            continue
                        state = True
                    if self.channel == "BOTH":
                        changed += int(fbp_set_effect_global_visible(target_rig, effect_id, state))
                    elif self.channel == "RENDER":
                        changed += int(fbp_set_effect_render_visible(target_rig, effect_id, state))
                    else:
                        changed += int(fbp_set_effect_visible(target_rig, effect_id, state))

        if self.channel == "VIEWPORT" and self.mode == "SOLO_SELECTED":
            view = "3D" if categories == {"3D"} else ("MASK" if categories == {"MASK"} else "2D")
            solo_ids = tuple(
                _fbp_effect_ref(effect_id, instance_id)
                for effect_id, instance_id in selected_instances
            )
            for target_rig in rigs:
                changed += int(_fbp_store_effect_solo_ids(target_rig, view, solo_ids))
        return {"FINISHED"} if changed else {"CANCELLED"}

class FBP_OT_RemoveSelectedEffects(Operator):
    bl_idname = "fbp.remove_selected_effects"
    bl_label = "Remove Selected Effects"
    bl_description = "Immediately remove every checked effect from all selected layers; when nothing is checked, remove the active effect"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        selection = _fbp_capture_effect_removal_selection(context)
        rig = rigs[0]
        fbp_sync_effect_items(rig, rigs)
        selected_instances = fbp_selected_effect_instances(
            rig,
            fallback_active=True,
            categories=_fbp_effect_view_categories(context),
        )
        if not selected_instances:
            return {"CANCELLED"}
        counts = {}
        for item in getattr(rig, "fbp_effects", ()):
            effect_id = fbp_normalize_effect_id(getattr(item, "effect_id", ""))
            if _fbp_effect_uses_multi_instances(effect_id):
                counts[effect_id] = counts.get(effect_id, 0) + 1
        if len(rigs) > 1 and any(counts.get(effect_id, 0) > 1 for effect_id, _iid in selected_instances):
            self.report(
                {"INFO"},
                "Remove duplicated effect instances on one layer at a time",
            )
            return {"CANCELLED"}

        removed = 0
        if len(rigs) == 1:
            for effect_id, instance_id in reversed(selected_instances):
                if instance_id and _fbp_effect_uses_multi_instances(effect_id):
                    removed += int(
                        fbp_remove_effect_instance(
                            rig, effect_id, instance_id, sync_items=False
                        )
                    )
                elif fbp_effect_is_active(rig, effect_id):
                    removed += int(fbp_remove_effect(rig, effect_id, sync_items=False))
        else:
            effect_ids = list(dict.fromkeys(effect_id for effect_id, _iid in selected_instances))
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
        fbp_persist_effect_stacks(rigs)
        fbp_sync_effect_items(
            rig, rigs, repair_assets=False, normalize_instance_ids=False
        )
        try:
            for item in rig.fbp_effects:
                item.is_selected = False
        except FBP_DATA_ERRORS:
            pass
        fbp_load_active_effect_instance_settings(rig)
        _fbp_restore_effect_removal_selection(context, rigs, selection)
        self.report({"INFO"}, f"Removed {removed} effect instance(s)")
        return {"FINISHED"}

class FBP_OT_CreateEffectGroup(Operator):
    bl_idname = "fbp.create_effect_group"
    bl_label = "Create Group from Selected"
    bl_description = "Create one persistent organizational group from checked effect instances"
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
        selected_instances = fbp_selected_effect_instances(
            active_rig,
            fallback_active=True,
            movable_only=True,
            categories=_fbp_effect_view_categories(context),
        )
        effect_refs = [
            _fbp_effect_ref(effect_id, instance_id)
            for effect_id, instance_id in selected_instances
        ]
        if not effect_refs:
            self.report({"INFO"}, "Select an effect to create a group")
            return {"CANCELLED"}
        if len({
            _fbp_effect_chain_key(_fbp_effect_ref_effect_id(token))
            for token in effect_refs
        }) != 1:
            self.report({"WARNING"}, "Effect Groups must stay inside one compatible chain")
            return {"CANCELLED"}
        group_id = fbp_group_effect_selection_transactional(rigs, effect_refs)
        if not group_id:
            self.report({"WARNING"}, "Use adjacent compatible instances shared by every selected layer")
            return {"CANCELLED"}
        _fbp_select_effect_group_row(active_rig, group_id, rigs)
        self.report({"INFO"}, f"Created {fbp_effect_group_name(active_rig, group_id)}")
        return {"FINISHED"}



class FBP_OT_SelectEffectGroup(Operator):
    bl_idname = "fbp.select_effect_group"
    bl_label = "Select Effect Group"
    bl_description = "Select this Effect Group folder row without changing member data"
    bl_options = {"INTERNAL"}

    group_id: StringProperty(name="Effect Group ID", default="", options={"SKIP_SAVE"})
    use_shift: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    use_ctrl: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        return invoke_with_selection_modifiers(self, context, event)

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs or not self.group_id:
            return {"CANCELLED"}
        rig = rigs[0]
        if not _fbp_select_effect_group_row(rig, self.group_id, rigs):
            return {"CANCELLED"}
        target_index = int(getattr(rig, "fbp_effects_index", 0) or 0)
        anchor_key = "_fbp_effect_selection_anchor"
        anchor_uid_key = "_fbp_effect_selection_anchor_uid"
        anchor = resolve_anchor_index(
            rig, anchor_key, anchor_uid_key, rig.fbp_effects,
            "row_uid", fallback=target_index,
        )
        categories = _fbp_effect_view_categories(context)
        eligible = []
        for index, item in enumerate(rig.fbp_effects):
            if str(getattr(item, "row_type", "EFFECT") or "EFFECT") != "EFFECT":
                continue
            effect_id = fbp_normalize_effect_id(getattr(item, "effect_id", ""))
            if str(fbp_effect_definition(effect_id).get("category", "2D") or "2D") not in categories:
                continue
            instance_id = str(getattr(item, "instance_id", "") or "") if _fbp_effect_uses_multi_instances(effect_id) else ""
            eligible.append((index, _fbp_effect_ref(effect_id, instance_id), item))
        member_refs = set(fbp_effect_group_members_from_items(rig, self.group_id))
        eligible_refs = [token for _index, token, _item in eligible]
        if self.use_shift:
            lo, hi = sorted((max(0, anchor), target_index))
            range_refs = [token for index, token, _item in eligible if lo <= index <= hi]
            fbp_set_effect_selection(
                rig, range_refs,
                mode="ADD" if self.use_ctrl else "REPLACE",
                eligible_ids=eligible_refs,
            )
        elif self.use_ctrl:
            all_selected = bool(member_refs) and all(
                bool(item.is_selected)
                for _index, token, item in eligible if token in member_refs
            )
            fbp_set_effect_selection(
                rig, member_refs,
                mode="REMOVE" if all_selected else "ADD",
                eligible_ids=eligible_refs,
            )
        store_anchor(
            rig, anchor_key, anchor_uid_key, rig.fbp_effects,
            "row_uid", target_index,
        )
        return {"FINISHED"}



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
            group_id = fbp_effect_group_id_for_rig(
                rig,
                active_effect,
                instance_id=fbp_active_effect_instance_id(rig),
            )
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
    bl_description = "Remove checked concrete effect instances from their groups"
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
        selected_instances = fbp_selected_effect_instances(
            rig, fallback_active=True, movable_only=True,
            categories=_fbp_effect_view_categories(context),
        )
        effect_refs = [_fbp_effect_ref(effect_id, instance_id) for effect_id, instance_id in selected_instances]
        if not fbp_ungroup_effect_selection_transactional(rigs, effect_refs):
            self.report({"INFO"}, "The selected instances are not assigned to groups")
            return {"CANCELLED"}
        return {"FINISHED"}



class FBP_OT_ToggleEffectGroupCollapse(Operator):
    bl_idname = "fbp.toggle_effect_group_collapse"
    bl_label = "Expand or Collapse Effect Group"
    bl_description = "Expand or collapse this Effect Group without changing nodes, modifiers, parameters or evaluation order"
    bl_options = {"INTERNAL"}

    group_id: StringProperty(description='Group Id value used by the current effect-stack action. Changes are applied only to compatible Frame By Plane data.', default="", options={"SKIP_SAVE"})
    collapsed: BoolProperty(description='Toggle this option for the current effect-stack action. Disabled keeps the data available but prevents this behavior from being applied.', default=True, options={"SKIP_SAVE"})

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
    bl_description = "Select or deselect every concrete effect instance inside this group"
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
            rig, members,
            mode="ADD" if self.selected else "REMOVE",
            eligible_ids=members,
        )
        return {"FINISHED"} if changed else {"CANCELLED"}



class FBP_OT_RenameEffectGroup(Operator):
    bl_idname = "fbp.rename_effect_group"
    bl_label = "Rename Effect Group"
    bl_description = "Rename this Effect Group consistently on every selected layer while preserving all effect data"
    bl_options = {"REGISTER", "UNDO"}

    group_id: StringProperty(description='Group Id value used by the current effect-stack action. Changes are applied only to compatible Frame By Plane data.', default="", options={"SKIP_SAVE"})
    target_payload: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
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
        self.target_payload = _fbp_capture_rig_targets(rigs)
        self.new_name = fbp_effect_group_name(rigs[0], self.group_id) or "Effect Group"
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        rigs = _fbp_resolve_rig_targets(self.target_payload) if self.target_payload else _fbp_selected_rigs(context)
        if not rigs:
            self.report({"WARNING"}, "The original effect layers no longer exist")
            return {"CANCELLED"}
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

    group_id: StringProperty(description='Group Id value used by the current effect-stack action. Changes are applied only to compatible Frame By Plane data.', default="", options={"SKIP_SAVE"})
    color_tag: EnumProperty(description='Color value used by the selected generated layer, mask, effect group or visual helper.',
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
    bl_description = "Run a shared action on every concrete member of this Effect Group"
    bl_options = {"REGISTER", "UNDO"}

    group_id: StringProperty(default="", options={"SKIP_SAVE"})
    action: EnumProperty(
        name="Action",
        items=(
            ("SELECT", "Select Group", "Select every member"),
            ("MOVE_UP", "Move Up", "Move the group earlier"),
            ("MOVE_DOWN", "Move Down", "Move the group later"),
            ("MOVE_TOP", "Move to Top", "Move the group to the beginning"),
            ("MOVE_BOTTOM", "Move to Bottom", "Move the group to the end"),
            ("SHOW", "Show", "Enable every member in viewport and render"),
            ("HIDE", "Hide", "Disable every member in viewport and render"),
            ("SOLO_VIEWPORT", "Solo in Viewport", "Temporarily solo this group in the viewport"),
            ("UNGROUP", "Ungroup", "Remove every member from this group"),
        ),
        default="SELECT", options={"SKIP_SAVE"},
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
            or any(not _fbp_effect_ref_is_active(target, token) for token in members)
            for target in rigs
        ):
            self.report({"WARNING"}, "The group is not shared consistently by all selected layers")
            return {"CANCELLED"}

        if self.action == "SELECT":
            categories = _fbp_effect_view_categories(context)
            eligible = []
            for record in fbp_effect_instance_records_for_rig(rig, ensure=False, sync_storage=False):
                effect_id = fbp_normalize_effect_id(record.get("effect_id", ""))
                if str(fbp_effect_definition(effect_id).get("category", "2D") or "2D") not in categories:
                    continue
                instance_id = str(record.get("instance_id", "") or "") if _fbp_effect_uses_multi_instances(effect_id) else ""
                eligible.append(_fbp_effect_ref(effect_id, instance_id))
            changed = fbp_set_effect_selection(rig, members, mode="REPLACE", eligible_ids=eligible)
            return {"FINISHED"} if changed else {"CANCELLED"}
        if self.action == "UNGROUP":
            return {"FINISHED"} if fbp_ungroup_effect_selection_transactional(rigs, members) else {"CANCELLED"}
        if self.action.startswith("MOVE_"):
            direction = self.action.removeprefix("MOVE_")
            if not fbp_move_effect_selection_transactional(rigs, members, direction):
                self.report({"INFO"}, "The group cannot move farther in this chain")
                return {"CANCELLED"}
            return {"FINISHED"}

        channel = "BOTH" if self.action in {"SHOW", "HIDE"} else "VIEWPORT"
        mode = self.action.removesuffix("_VIEWPORT")
        categories = {
            str(fbp_effect_definition(_fbp_effect_ref_effect_id(token)).get("category", "2D") or "2D")
            for token in members
        }
        changed = False
        member_set = set(members)
        for target in rigs:
            candidates = []
            for record in fbp_effect_instance_records_for_rig(target, ensure=False, sync_storage=False):
                effect_id = fbp_normalize_effect_id(record.get("effect_id", ""))
                definition = fbp_effect_definition(effect_id)
                if definition.get("kind") not in {"SHADER", "GEOMETRY"}:
                    continue
                if str(definition.get("category", "2D") or "2D") not in categories:
                    continue
                instance_id = str(record.get("instance_id", "") or "") if _fbp_effect_uses_multi_instances(effect_id) else ""
                candidates.append(_fbp_effect_ref(effect_id, instance_id))
            for token in candidates:
                effect_id, instance_id = _fbp_effect_ref_parts(token)
                if mode == "SOLO":
                    state = token in member_set
                elif token in member_set:
                    state = mode == "SHOW"
                else:
                    continue
                if channel == "BOTH":
                    changed = fbp_set_effect_global_visible(
                        target, effect_id, state, instance_id=instance_id
                    ) or changed
                else:
                    changed = fbp_set_effect_visible(target, effect_id, state, instance_id=instance_id) or changed
            if channel == "VIEWPORT":
                view = _fbp_effect_solo_view(_fbp_effect_ref_effect_id(members[0]))
                solo_ids = tuple(members) if mode == "SOLO" else ()
                changed = _fbp_store_effect_solo_ids(target, view, solo_ids) or changed
        fbp_sync_effect_items(rig, rigs)
        return {"FINISHED"} if changed else {"CANCELLED"}



class FBP_OT_EffectGroupActions(Operator):
    bl_idname = "fbp.effect_group_actions"
    bl_label = "Effect Group Actions"
    bl_description = "Open shared controls for renaming, collapsing, moving, selecting, showing or ungrouping this Effect Group"
    bl_options = {"INTERNAL"}

    group_id: StringProperty(description='Group Id value used by the current effect-stack action. Changes are applied only to compatible Frame By Plane data.', default="", options={"SKIP_SAVE"})

    def invoke(self, context, _event):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        fbp_sync_effect_items(rigs[0], rigs)
        if not self.group_id:
            active_effect = fbp_active_effect_id(rigs[0])
            self.group_id = fbp_effect_group_id_for_rig(
                rigs[0],
                active_effect,
                instance_id=fbp_active_effect_instance_id(rigs[0]),
            )
        if not self.group_id:
            self.report({"INFO"}, "The active effect is not in a group")
            return {"CANCELLED"}
        return context.window_manager.invoke_popup(self, width=330)

    def draw(self, context):
        layout = configure_layout(self.layout)
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
        noun = "effect" if len(members) == 1 else "effects"
        header = section_header(
            layout,
            name,
            icon=fbp_collection_color_icon(color_tag),
            suffix=f"· {len(members)} {noun}",
            align=True,
        )
        rename = header.operator("fbp.rename_effect_group", text="", icon=ui_icon("action.rename"))
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

        row = adaptive_row(layout, context)
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
        layout.label(text="Visibility", icon="HIDE_OFF")
        visibility = adaptive_row(layout, context)
        for text, action, icon in (
            ("Show", "SHOW", "HIDE_OFF"),
            ("Hide", "HIDE", "HIDE_ON"),
            ("Solo Viewport", "SOLO_VIEWPORT", "CHECKMARK"),
        ):
            op = visibility.operator("fbp.effect_group_action", text=text, icon=icon)
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
    bl_description = 'Enable or disable the selected effect in final renders'
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

    mode: EnumProperty(description='Action to run',
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
    bl_description = "Move checked concrete effect instances while preserving relative order"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction",
        items=(("UP", "Up", "Move earlier"), ("DOWN", "Down", "Move later"),
               ("TOP", "Top", "Move to start"), ("BOTTOM", "Bottom", "Move to end")),
        default="UP", options={"SKIP_SAVE"},
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
        selected_instances = fbp_selected_effect_instances(
            active_rig, fallback_active=True, movable_only=True,
            categories=_fbp_effect_view_categories(context),
        )
        effect_refs = [_fbp_effect_ref(effect_id, instance_id) for effect_id, instance_id in selected_instances]
        if not effect_refs:
            self.report({"INFO"}, "Select a shader or mesh effect first")
            return {"CANCELLED"}
        missing = [
            token for token in effect_refs
            if any(not _fbp_effect_ref_is_active(rig, token) for rig in rigs)
        ]
        if missing:
            self.report({"WARNING"}, "Copy every checked instance to all selected layers before reordering")
            return {"CANCELLED"}
        if not fbp_move_effect_selection_transactional(rigs, effect_refs, self.direction):
            self.report({"INFO"}, "Selected effects cannot move farther in this chain")
            return {"CANCELLED"}
        return {"FINISHED"}



def _fbp_capture_effect_removal_selection(context):
    """Capture the current object selection before helpers/nodes are removed.

    Removing a viewport controller can make Blender drop the active object.  A
    missing active object makes the Effects/Mask panel disappear even though
    the represented Frame By Plane layer still exists.
    """
    if context is None:
        return (None, ())
    try:
        active = getattr(getattr(context, "view_layer", None), "objects", None)
        active = getattr(active, "active", None) or getattr(context, "object", None)
        selected = tuple(getattr(context, "selected_objects", ()) or ())
        return (active, selected)
    except FBP_DATA_ERRORS:
        return (None, ())


def _fbp_object_available_in_view_layer(context, obj):
    if context is None or obj is None:
        return False
    try:
        name = str(getattr(obj, "name", "") or "")
        view_layer = getattr(context, "view_layer", None)
        data_object = bpy.data.objects.get(name) if name else None
        layer_object = (
            view_layer.objects.get(name)
            if name and view_layer is not None
            else None
        )
        if data_object is None or layer_object is None:
            return False
        # RNA access through bpy.data, Context and ViewLayer can yield distinct
        # Python wrapper objects for the same Blender datablock. Comparing those
        # wrappers with ``is`` made a surviving plane look deleted immediately
        # after its viewport controller was removed. Runtime datablock identity
        # is stable across those wrappers and keeps the restoration path valid.
        object_key = fbp_obj_runtime_key(obj)
        return bool(
            object_key is not None
            and fbp_obj_runtime_key(data_object) == object_key
            and fbp_obj_runtime_key(layer_object) == object_key
        )
    except FBP_DATA_ERRORS:
        return False


def _fbp_restore_effect_removal_selection(context, rigs, snapshot):
    """Restore the represented layer after Mask/2D/3D removal.

    Existing surviving selections are preserved.  When the active object was a
    deleted effect controller, the render plane becomes active; the owning rig
    is used only when no selectable plane is available.
    """
    if context is None:
        return False
    active_before, selected_before = snapshot or (None, ())
    changed = False

    def select_available(obj, *, keep_selectable=False):
        """Select a surviving target even when its selection lock is enabled.

        Native Frame By Plane render planes are normally non-selectable so
        viewport clicks target the owning layer rig. Blender also rejects
        ``select_set(True)`` while ``hide_select`` is enabled, which left a
        deleted controller's plane active but not selected. Temporarily lift the
        lock for preserved secondary selections.  The new active target must
        stay selectable: restoring ``hide_select`` immediately makes Blender
        deselect it again.
        """
        nonlocal changed
        if not _fbp_object_available_in_view_layer(context, obj):
            return False
        try:
            was_locked = bool(getattr(obj, "hide_select", False))
            if was_locked:
                obj.hide_select = False
            try:
                if not bool(obj.select_get()):
                    obj.select_set(True)
                    changed = True
                return bool(obj.select_get())
            finally:
                if was_locked and not keep_selectable:
                    obj.hide_select = True
        except FBP_DATA_ERRORS:
            return False

    try:
        for obj in tuple(selected_before or ()):
            select_available(obj)

        active_candidate = (
            active_before
            if _fbp_object_available_in_view_layer(context, active_before)
            else None
        )
        if active_candidate is None:
            for rig in tuple(rigs or ()):
                if rig is None:
                    continue
                plane = _fbp_plane(rig, repair=False)
                if _fbp_object_available_in_view_layer(context, plane):
                    active_candidate = plane
                    break
                if _fbp_object_available_in_view_layer(context, rig):
                    active_candidate = rig
                    break

        if active_candidate is None:
            return changed
        select_available(active_candidate, keep_selectable=True)
        if (
            fbp_obj_runtime_key(context.view_layer.objects.active)
            != fbp_obj_runtime_key(active_candidate)
        ):
            context.view_layer.objects.active = active_candidate
            changed = True
        return changed
    except FBP_DATA_ERRORS:
        return changed


class FBP_OT_DuplicateEffectInstance(Operator):
    bl_idname = "fbp.duplicate_effect_instance"
    bl_label = "Duplicate Effect Instance"
    bl_description = "Create an independent copy of this effect on the active layer"
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(name="Effect ID", default="", options={"SKIP_SAVE"})
    instance_id: StringProperty(name="Instance ID", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return len(_fbp_selected_rigs(context)) == 1

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if len(rigs) != 1:
            self.report({"INFO"}, "Select exactly one layer to duplicate an effect instance")
            return {"CANCELLED"}
        new_instance_id = fbp_duplicate_effect_instance(
            rigs[0], self.effect_id, self.instance_id, sync_items=True
        )
        if not new_instance_id:
            self.report({"WARNING"}, "This effect does not support independent instances yet")
            return {"CANCELLED"}
        _fbp_select_effect_row(
            rigs[0], self.effect_id, rigs, instance_id=new_instance_id
        )
        fbp_load_effect_instance_settings(rigs[0], self.effect_id, new_instance_id)
        return {"FINISHED"}


class FBP_OT_RemoveEffect(Operator):
    bl_idname = "fbp.remove_effect"
    bl_label = "Remove Effect"
    bl_description = 'Remove this effect from all compatible selected layers while preserving layer selection'
    bl_options = {"REGISTER", "UNDO"}

    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", name="Effect ID", default="", options={"SKIP_SAVE"})
    instance_id: StringProperty(description="Persistent identity of one concrete effect instance.", name="Instance ID", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        effect_id = fbp_normalize_effect_id(self.effect_id)
        rigs = _fbp_selected_rigs(context)
        if not effect_id or not rigs:
            return {"CANCELLED"}
        selection = _fbp_capture_effect_removal_selection(context)
        definition = fbp_effect_definition(effect_id)
        remove_one = bool(
            len(rigs) == 1
            and self.instance_id
            and str(definition.get("instance_policy", "SINGLE") or "SINGLE").upper() == "MULTI"
        )
        removed = (
            int(fbp_remove_effect_instance(
                rigs[0], effect_id, self.instance_id, sync_items=False
            ))
            if remove_one else sum(
                1 for rig in rigs
                if fbp_effect_is_active(rig, effect_id)
                and fbp_remove_effect(rig, effect_id, sync_items=False)
            )
        )
        fbp_persist_effect_stacks(rigs)
        fbp_sync_effect_items(
            rigs[0], rigs, repair_assets=False, normalize_instance_ids=False
        )
        fbp_load_active_effect_instance_settings(rigs[0])
        _fbp_restore_effect_removal_selection(context, rigs, selection)
        return {"FINISHED"} if removed else {"CANCELLED"}


class FBP_OT_RemoveActiveEffect(Operator):
    bl_idname = "fbp.remove_active_effect"
    bl_label = "Remove Selected Effect"
    bl_description = 'Remove the checked effects, or the active effect when no rows are checked'
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_fbp_selected_rigs(context))

    def execute(self, context):
        rigs = _fbp_selected_rigs(context)
        if not rigs:
            return {"CANCELLED"}
        selection = _fbp_capture_effect_removal_selection(context)
        active_rig = rigs[0]
        fbp_sync_effect_items(active_rig, rigs)
        effect_id = fbp_active_effect_id(active_rig)
        if not effect_id:
            return {"CANCELLED"}
        instance_id = fbp_active_effect_instance_id(active_rig)
        definition = fbp_effect_definition(effect_id)
        if (
            len(rigs) == 1
            and instance_id
            and str(definition.get("instance_policy", "SINGLE") or "SINGLE").upper() == "MULTI"
        ):
            removed = int(fbp_remove_effect_instance(
                active_rig, effect_id, instance_id, sync_items=False
            ))
        else:
            removed = sum(
                1
                for rig in rigs
                if fbp_remove_effect(rig, effect_id, sync_items=False)
            )
        fbp_persist_effect_stacks(rigs)
        fbp_sync_effect_items(
            active_rig, rigs,
            repair_assets=False,
            normalize_instance_ids=False,
        )
        fbp_load_active_effect_instance_settings(active_rig)
        _fbp_restore_effect_removal_selection(context, rigs, selection)
        if removed == 0:
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_UpdateLatticeFlatten(Operator):
    bl_idname = "fbp.update_lattice_flatten"
    bl_label = "Update Camera Flatten"
    bl_description = "Recalculate the Lattice so the plane preserves its current camera-space perspective on a camera-parallel surface"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})

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

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})

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

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})

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
        try:
            from .lattice_corner_pin import remove_handles
            remove_handles(rig, _fbp_lattice_object(rig))
        except (ImportError,) + FBP_DATA_ERRORS:
            pass
        for name, value in (
            ("fbp_lattice_mode", "CAMERA_FLATTEN"),
            ("fbp_lattice_live_update", True),
            ("fbp_lattice_show_cage", True),
            ("fbp_lattice_grid_preset", "LOOPS_4"),
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

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})

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

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})

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

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})

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

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})
    grid_size: IntProperty(description='Size control for the generated result. Higher values increase visual coverage and may increase viewport cost.', name="Grid Size", default=4, min=2, max=8, options={'SKIP_SAVE'})

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

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})

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
        try:
            from .lattice_pins import bind, reset_pins, rig_pins
            reset_pins(rig_pins(rig))
            bind(rig, helper, plane, force=False)
            from .lattice_bones import bones_object, reset_pose
            armature = bones_object(rig)
            if armature is not None:
                reset_pose(armature)
            from .lattice_corner_pin import remove_handles
            remove_handles(rig, helper)
        except (ImportError,) + FBP_DATA_ERRORS:
            pass
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

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})

    def execute(self, context):
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None or not _fbp_apply_lattice_effect(rig, select=False):
            self.report({'ERROR'}, _fbp_last_lattice_error(rig) or "Could not create the Lattice cage")
            return {'CANCELLED'}
        if _fbp_lattice_mode(rig) == "CORNER_PIN":
            # Editing the cage freezes the perspective as a Freeform shape.
            _fbp_apply_lattice_corner_pin(rig, force=True)
            fbp_set_rna_property_silent(rig, "fbp_lattice_mode", "FREEFORM")
            try:
                from .lattice_corner_pin import remove_handles
                helper = _fbp_lattice_object(rig)
                remove_handles(rig, helper)
                if helper is not None:
                    helper[_FBP_LATTICE_MODE_KEY] = "FREEFORM"
            except (ImportError,) + FBP_DATA_ERRORS:
                pass
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

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})

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
        helper = _fbp_lattice_object(rig)
        if helper is not None and _fbp_lattice_exit_edit(context, helper):
            # A pose edit ends here: later cage edits shape the rest cage again.
            from .lattice_poses import set_active_pose
            try:
                set_active_pose(helper, "")
            except FBP_DATA_ERRORS:
                pass
        return {'FINISHED'}


def _fbp_lattice_exit_edit(context, helper):
    """Leave Lattice Edit Mode on the cage itself, whatever object is active.

    Edits made in Edit Mode reach the active shape key only on exit, so this
    must run before the active pose changes or a pose is added or removed.
    """
    if helper is None or str(getattr(helper, "mode", "OBJECT") or "OBJECT") == "OBJECT":
        return True
    # mode_set acts on the active object: make the cage active both in the
    # View Layer and in any context override the caller runs under.
    view_layer = getattr(context, "view_layer", None) or bpy.context.view_layer
    previous = view_layer.objects.active
    try:
        view_layer.objects.active = helper
        with bpy.context.temp_override(active_object=helper, object=helper, edit_object=helper):
            bpy.ops.object.mode_set(mode="OBJECT")
    except FBP_DATA_ERRORS:
        return False
    finally:
        try:
            if previous is not None and previous != helper:
                view_layer.objects.active = previous
        except FBP_DATA_ERRORS:
            pass
    return str(getattr(helper, "mode", "OBJECT") or "OBJECT") == "OBJECT"


def _fbp_lattice_pose_rig(operator, context):
    """Resolve the layer for a pose operator; poses need a Freeform cage."""
    rig = bpy.data.objects.get(str(operator.rig_name or ""))
    if rig is None or not _fbp_apply_lattice_effect(rig, select=False):
        operator.report({'ERROR'}, _fbp_last_lattice_error(rig) or "Could not create the Lattice cage")
        return None, None
    if _fbp_lattice_mode(rig) == "CAMERA_FLATTEN":
        operator.report({'WARNING'}, "Poses work on a Freeform cage: Bake or Freeze Camera Flatten first")
        return None, None
    helper = _fbp_lattice_object(rig)
    if helper is None:
        operator.report({'ERROR'}, "The Lattice cage is missing")
        return None, None
    return rig, helper


class FBP_OT_AddLatticePose(Operator):
    bl_idname = "fbp.add_lattice_pose"
    bl_label = "Add Deformation Pose"
    bl_description = "Add an animatable deformation slider. Presets shape it for you; Custom starts from the rest cage and opens it for editing. Sliders mix and can be keyframed"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})
    preset: StringProperty(name="Preset", description="Deformation preset; empty for a custom pose", default="", options={'SKIP_SAVE'})

    def execute(self, context):
        from .lattice_poses import PRESETS, add_pose, preset_minimum_points, set_active_pose
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        # Commit the current edit to the key it belongs to first.
        if not _fbp_lattice_exit_edit(context, _fbp_lattice_object(rig) if rig is not None else None):
            return {'CANCELLED'}
        rig, helper = _fbp_lattice_pose_rig(self, context)
        if helper is None:
            return {'CANCELLED'}
        preset = str(self.preset or "").upper()
        if preset and preset not in PRESETS:
            return {'CANCELLED'}
        need_u, need_v = preset_minimum_points(preset) if preset else (2, 2)
        points_u = int(getattr(rig, "fbp_lattice_points_u", 4) or 4)
        points_v = int(getattr(rig, "fbp_lattice_points_v", 4) or 4)
        if points_u < need_u or points_v < need_v:
            # A curve cannot be expressed with too few control points: refine
            # the cage first (existing shape and poses are resampled).
            loops_u, loops_v = _fbp_lattice_grid_loops(rig)
            loops_u, loops_v = max(loops_u, need_u - 2), max(loops_v, need_v - 2)
            fbp_set_rna_property_silent(rig, "fbp_lattice_grid_preset", "CUSTOM")
            fbp_set_rna_property_silent(rig, "fbp_lattice_link_loops", loops_u == loops_v)
            fbp_set_rna_property_silent(rig, "fbp_lattice_custom_loops_u", loops_u)
            fbp_set_rna_property_silent(rig, "fbp_lattice_custom_loops_v", loops_v)
            _fbp_apply_lattice_grid_settings(rig)
            if not _fbp_apply_lattice_effect(rig, select=False):
                return {'CANCELLED'}
            helper = _fbp_lattice_object(rig)
            self.report({'INFO'}, f"Cage refined to {loops_u} × {loops_v} loops for a smooth {PRESETS[preset][0]}")
        try:
            pose = add_pose(helper, preset)
        except FBP_DATA_ERRORS as exc:
            self.report({'ERROR'}, f"Could not add the pose: {exc}")
            return {'CANCELLED'}
        _fbp_invalidate_live_lattice_cache()
        if not preset:
            set_active_pose(helper, pose.name)
            if "FINISHED" not in bpy.ops.fbp.edit_lattice_helper(rig_name=rig.name):
                set_active_pose(helper, "")
            return {'FINISHED'}
        set_active_pose(helper, "")
        fbp_focus_lattice_ui(context, rig)
        return {'FINISHED'}


class FBP_OT_EditLatticePose(Operator):
    bl_idname = "fbp.edit_lattice_pose"
    bl_label = "Edit Pose"
    bl_description = "Shape this pose in the cage: it is shown alone at full strength until you press Done"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})
    pose_name: StringProperty(name="Pose", options={'HIDDEN'})

    def execute(self, context):
        from .lattice_poses import set_active_pose
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        # Commit the current edit to the key it belongs to first.
        if not _fbp_lattice_exit_edit(context, _fbp_lattice_object(rig) if rig is not None else None):
            return {'CANCELLED'}
        rig, helper = _fbp_lattice_pose_rig(self, context)
        if helper is None or not set_active_pose(helper, self.pose_name):
            return {'CANCELLED'}
        if "FINISHED" not in bpy.ops.fbp.edit_lattice_helper(rig_name=rig.name):
            set_active_pose(helper, "")
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_RemoveLatticePose(Operator):
    bl_idname = "fbp.remove_lattice_pose"
    bl_label = "Remove Pose"
    bl_description = "Remove this deformation pose and its animation"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})
    pose_name: StringProperty(name="Pose", options={'HIDDEN'})

    def execute(self, context):
        from .lattice_poses import remove_pose
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        helper = _fbp_lattice_object(rig) if rig is not None else None
        if helper is None:
            return {'CANCELLED'}
        if not _fbp_lattice_exit_edit(context, helper):
            return {'CANCELLED'}
        try:
            removed = remove_pose(helper, self.pose_name)
        except FBP_DATA_ERRORS as exc:
            self.report({'ERROR'}, f"Could not remove the pose: {exc}")
            return {'CANCELLED'}
        _fbp_invalidate_live_lattice_cache()
        return {'FINISHED'} if removed else {'CANCELLED'}


def _fbp_lattice_pins_target(operator, *, report=True):
    """Resolve (rig, helper, plane) for a pin operator on a Freeform cage."""
    rig = bpy.data.objects.get(str(operator.rig_name or ""))
    if rig is None or not _fbp_apply_lattice_effect(rig, select=False):
        if report:
            operator.report({'ERROR'}, _fbp_last_lattice_error(rig) or "Could not create the Lattice cage")
        return None, None, None
    if _fbp_lattice_mode(rig) == "CAMERA_FLATTEN":
        if report:
            operator.report({'WARNING'}, "Pins work on a Freeform cage: Bake or Freeze Camera Flatten first")
        return None, None, None
    helper = _fbp_lattice_object(rig)
    plane = _fbp_plane(rig)
    if helper is None or plane is None:
        if report:
            operator.report({'ERROR'}, "The Lattice cage is missing")
        return None, None, None
    return rig, helper, plane


def _fbp_refine_lattice_cage(operator, rig, plane, points_u, points_v):
    """Raise the cage to at least points_u × points_v (shape and poses are kept)."""
    current_u = int(getattr(rig, "fbp_lattice_points_u", 4) or 4)
    current_v = int(getattr(rig, "fbp_lattice_points_v", 4) or 4)
    points_u, points_v = max(points_u, current_u), max(points_v, current_v)
    if (points_u, points_v) == (current_u, current_v):
        return True
    loops_u, loops_v = points_u - 2, points_v - 2
    fbp_set_rna_property_silent(rig, "fbp_lattice_grid_preset", "CUSTOM")
    fbp_set_rna_property_silent(rig, "fbp_lattice_link_loops", loops_u == loops_v)
    fbp_set_rna_property_silent(rig, "fbp_lattice_custom_loops_u", loops_u)
    fbp_set_rna_property_silent(rig, "fbp_lattice_custom_loops_v", loops_v)
    _fbp_apply_lattice_grid_settings(rig)
    if not _fbp_apply_lattice_effect(rig, select=False):
        return False
    operator.report({'INFO'}, f"Cage refined to {points_u} × {points_v} points")
    return True


def _fbp_click_rest_point(context, plane, region, region_3d, coord):
    """World point on the flat layer under a click (follows a bent layer)."""
    from bpy_extras import view3d_utils
    from .lattice_pins import deformed_hit, ray_plane_point
    origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coord)
    hit = deformed_hit(plane, context.evaluated_depsgraph_get(), origin, direction)
    rest = hit[1] if hit is not None else None
    if rest is None:
        rest = ray_plane_point(plane, origin, direction)
    return rest


# Regions drawn over the 3D View (sidebar, toolbar, headers, asset shelf):
# a click there belongs to the interface, never to the layer under it.
_FBP_VIEW3D_OVERLAP_REGIONS = frozenset({
    'UI', 'TOOLS', 'HEADER', 'TOOL_HEADER', 'FOOTER', 'HUD',
    'ASSET_SHELF', 'ASSET_SHELF_HEADER', 'NAVIGATION_BAR', 'TOOL_PROPS',
})


def _fbp_view3d_under_mouse(context, event):
    """Return (area, region, region_3d) of the 3D View under the mouse.

    Over a 3D View's sidebar, toolbar or header the area comes back without a
    region, so the click reaches the interface instead of placing a handle.
    In Quad View the region under the mouse brings its own view.
    """
    screen = getattr(getattr(context, "window", None), "screen", None)
    if screen is None:
        return None, None, None
    x, y = int(event.mouse_x), int(event.mouse_y)

    def inside(item):
        return item.x <= x < item.x + item.width and item.y <= y < item.y + item.height

    for area in screen.areas:
        if area.type != 'VIEW_3D' or not inside(area):
            continue
        for region in area.regions:
            if region.type in _FBP_VIEW3D_OVERLAP_REGIONS and region.width > 1 and region.height > 1 and inside(region):
                return area, None, None
        for region in area.regions:
            if region.type == 'WINDOW' and inside(region):
                region_3d = getattr(region, "data", None)
                if not isinstance(region_3d, bpy.types.RegionView3D):
                    region_3d = getattr(area.spaces.active, "region_3d", None)
                return area, region, region_3d
        return area, None, None
    return None, None, None


def _fbp_point_on_layer(plane, world_point, margin=0.02):
    """True when a world point on the plane's surface lies inside the layer rectangle."""
    try:
        local = plane.matrix_world.inverted_safe() @ Vector(world_point)
        xs = [vertex.co.x for vertex in plane.data.vertices]
        ys = [vertex.co.y for vertex in plane.data.vertices]
        pad_x = (max(xs) - min(xs)) * margin
        pad_y = (max(ys) - min(ys)) * margin
        return min(xs) - pad_x <= local.x <= max(xs) + pad_x and min(ys) - pad_y <= local.y <= max(ys) + pad_y
    except (ValueError,) + FBP_DATA_ERRORS:
        return True


class _FBPLatticeClickModal:
    """Shared behaviour of the click-to-place Lattice tools (pins, bones).

    Only one of them runs at a time: pressing its button again ends it, and
    starting another one ends the previous one. A failed click is reported and
    never leaves the tool stuck, so Enter, Esc and Right Click always finish.
    """

    _fbp_active_token = None
    _fbp_active_key = None

    @classmethod
    def fbp_is_running(cls, rig_name=""):
        key = _FBPLatticeClickModal._fbp_active_key
        return bool(
            _FBPLatticeClickModal._fbp_active_token is not None and key is not None
            and key[0] == cls.__name__ and (not rig_name or key[1] == rig_name)
        )

    def _fbp_claim(self):
        """Start this tool; return False when the call only ended a running one."""
        if type(self).fbp_is_running(str(self.rig_name or "")):
            _FBPLatticeClickModal._fbp_active_token = None
            _FBPLatticeClickModal._fbp_active_key = None
            _fbp_tag_view3d_redraw()
            return False
        token = object()
        _FBPLatticeClickModal._fbp_active_token = token
        _FBPLatticeClickModal._fbp_active_key = (type(self).__name__, str(self.rig_name or ""))
        self._fbp_token = token
        return True

    def _fbp_superseded(self):
        return getattr(self, "_fbp_token", None) is not _FBPLatticeClickModal._fbp_active_token

    def _fbp_release(self):
        if not self._fbp_superseded():
            _FBPLatticeClickModal._fbp_active_token = None
            _FBPLatticeClickModal._fbp_active_key = None
        self._fbp_token = None

    def cancel(self, context):
        # Blender drops modal handlers on file load or window close.
        self._fbp_release()
        try:
            context.workspace.status_text_set(None)
        except FBP_DATA_ERRORS:
            pass
        restore_modal_cursor(context)


def _fbp_tag_view3d_redraw():
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except FBP_DATA_ERRORS:
        pass


class FBP_OT_AddLatticePins(_FBPLatticeClickModal, Operator):
    bl_idname = "fbp.add_lattice_pins"
    bl_label = "Add Puppet Pins"
    bl_description = "Click on the layer in the 3D View to place puppet pins; Ctrl+Click removes the nearest pin. Enter, Esc, Right Click or this button again finishes in Pose Mode. Move (G) or rotate (R) a pin to bend the drawing around it, and keyframe it like any bone"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})

    _NAVIGATION = {
        'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM',
        'NDOF_MOTION', 'MOUSEROTATE', 'MOUSESMARTZOOM',
        'NUMPAD_0', 'NUMPAD_1', 'NUMPAD_2', 'NUMPAD_3', 'NUMPAD_4', 'NUMPAD_5',
        'NUMPAD_6', 'NUMPAD_7', 'NUMPAD_8', 'NUMPAD_9', 'NUMPAD_PERIOD', 'NUMPAD_PLUS', 'NUMPAD_MINUS',
        'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'TIMER', 'TIMER_REPORT', 'TIMERREGION',
    }

    def _status(self, context):
        from .lattice_pins import rig_pins
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        count = len(rig_pins(rig)) if rig is not None else 0
        try:
            context.workspace.status_text_set(
                f"Puppet Pins ({count}): Click on the layer to add a pin  ·  Ctrl+Click removes the nearest pin  ·  Enter / Esc / Right Click: done"
            )
        except FBP_DATA_ERRORS:
            pass

    def invoke(self, context, event):
        del event
        from .lattice_pins import needs_denser_cage, puppet_grid_points, rig_pins
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if not _fbp_lattice_exit_edit(context, _fbp_lattice_object(rig) if rig is not None else None):
            return {'CANCELLED'}
        if type(self).fbp_is_running(str(self.rig_name or "")):
            self._fbp_claim()
            return {'CANCELLED'}
        rig, helper, plane = _fbp_lattice_pins_target(self)
        if helper is None:
            return {'CANCELLED'}
        screen = getattr(getattr(context, "window", None), "screen", None)
        if screen is None or not any(area.type == 'VIEW_3D' for area in screen.areas):
            self.report({'ERROR'}, "Open a 3D View to place pins")
            return {'CANCELLED'}
        # Bones left in Edit Mode would keep new pins from getting pose bones.
        from .lattice_bones import bones_object, leave_edit_mode
        if not leave_edit_mode(bones_object(rig)):
            self.report({'ERROR'}, "Press Done on the bones before adding pins")
            return {'CANCELLED'}
        if not rig_pins(rig) and needs_denser_cage(helper):
            # Pins bend the drawing through the cage: give them enough points.
            points_u, points_v = puppet_grid_points(plane)
            loops_u, loops_v = points_u - 2, points_v - 2
            fbp_set_rna_property_silent(rig, "fbp_lattice_grid_preset", "CUSTOM")
            fbp_set_rna_property_silent(rig, "fbp_lattice_link_loops", loops_u == loops_v)
            fbp_set_rna_property_silent(rig, "fbp_lattice_custom_loops_u", loops_u)
            fbp_set_rna_property_silent(rig, "fbp_lattice_custom_loops_v", loops_v)
            _fbp_apply_lattice_grid_settings(rig)
            if not _fbp_apply_lattice_effect(rig, select=False):
                return {'CANCELLED'}
            self.report({'INFO'}, f"Cage refined to {points_u} × {points_v} points for puppet pins")
        fbp_set_rna_property_silent(rig, "fbp_lattice_show_cage", False)
        self._fbp_claim()
        self._status(context)
        try:
            context.window.cursor_modal_set('CROSSHAIR')
        except FBP_DATA_ERRORS:
            pass
        context.window_manager.modal_handler_add(self)
        _fbp_tag_view3d_redraw()
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        self._fbp_release()
        try:
            context.workspace.status_text_set(None)
        except FBP_DATA_ERRORS:
            pass
        restore_modal_cursor(context)
        _fbp_tag_view3d_redraw()
        return {'FINISHED'}

    def _add(self, context, region, region_3d, coord):
        from bpy_extras import view3d_utils
        from .lattice_bones import armature_world
        from .lattice_pins import add_pin, blended_location, deformed_hit, ray_plane_point, rig_pins, select_pins
        rig, helper, plane = _fbp_lattice_pins_target(self)
        if helper is None:
            return False
        origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coord)
        hit = deformed_hit(plane, context.evaluated_depsgraph_get(), origin, direction)
        rest = hit[1] if hit is not None else None
        if rest is None:
            rest = ray_plane_point(plane, origin, direction)
        if rest is None or not _fbp_point_on_layer(plane, rest):
            self.report({'WARNING'}, "Click on the layer to place a pin")
            return False
        # A click on an existing pin picks it instead of stacking a second pin on it.
        nearest = self._nearest_pin(context, rig, region, region_3d, coord, 12.0)
        if nearest is not None:
            select_pins(context, rig, [nearest])
            return False
        existing = rig_pins(rig)
        current = blended_location(rig, helper, existing, rest)
        kind = str(getattr(rig, "fbp_lattice_pin_kind", "PIN") or "PIN")
        pin = add_pin(rig, helper, plane, rest, kind=kind)
        # On a bent layer the new pin starts where the drawing is now.
        local = armature_world(rig, pin.id_data).inverted_safe() @ current - pin.bone.head_local
        if kind != "BEND":
            pin.location = (local.x, local.y, 0.0)
        select_pins(context, rig, [pin])
        _fbp_invalidate_live_lattice_cache()
        return True

    @staticmethod
    def _nearest_pin(context, rig, region, region_3d, coord, pixels):
        """The puppet pin drawn within ``pixels`` (UI scaled) of a click, or None."""
        from bpy_extras import view3d_utils
        from .lattice_pins import pin_world, puppet_pins
        best = None
        limit = pixels * float(getattr(context.preferences.system, "ui_scale", 1.0) or 1.0)
        for pin in puppet_pins(rig):
            # A pin added by the previous click may not be evaluated yet.
            world = pin_world(rig, pin).translation
            point = view3d_utils.location_3d_to_region_2d(region, region_3d, world)
            if point is None:
                continue
            distance = (point - Vector(coord)).length
            if distance <= limit and (best is None or distance < best[0]):
                best = (distance, pin)
        return best[1] if best is not None else None

    def _remove_nearest(self, context, region, region_3d, coord):
        from .lattice_pins import remove_pin
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        helper = _fbp_lattice_object(rig) if rig is not None else None
        pin = self._nearest_pin(context, rig, region, region_3d, coord, 24.0)
        if pin is None:
            return False
        return remove_pin(rig, helper, pin)

    def modal(self, context, event):
        if self._fbp_superseded():
            return self._finish(context)
        if event.type in {'RET', 'NUMPAD_ENTER', 'ESC'} and event.value == 'PRESS':
            return self._finish(context)
        area, region, region_3d = _fbp_view3d_under_mouse(context, event)
        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            if area is not None:
                return self._finish(context)
            return {'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and region is not None and region_3d is not None:
            coord = (event.mouse_x - region.x, event.mouse_y - region.y)
            try:
                if event.ctrl:
                    self._remove_nearest(context, region, region_3d, coord)
                else:
                    self._add(context, region, region_3d, coord)
            except Exception as exc:  # noqa: BLE001 - a failed click must never leave the tool stuck
                self.report({'ERROR'}, f"Could not place the pin: {exc}")
            self._status(context)
            area.tag_redraw()
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}


class FBP_OT_RemoveLatticePin(Operator):
    bl_idname = "fbp.remove_lattice_pin"
    bl_label = "Remove Pin"
    bl_description = "Remove this puppet pin and its animation; the other pins take over its area"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})
    pin_name: StringProperty(name="Pin", default="", description="Pin to remove; empty removes every pin", options={'HIDDEN'})

    def execute(self, context):
        del context
        from .lattice_pins import remove_all_pins, remove_pin, rig_pins
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        helper = _fbp_lattice_object(rig) if rig is not None else None
        if rig is None:
            return {'CANCELLED'}
        if not self.pin_name:
            removed = remove_all_pins(rig, helper, kinds=("PIN", "BEND"))
        else:
            pin = next((item for item in rig_pins(rig) if item.name == self.pin_name), None)
            removed = bool(pin is not None and remove_pin(rig, helper, pin))
        _fbp_invalidate_live_lattice_cache()
        return {'FINISHED'} if removed else {'CANCELLED'}


class FBP_OT_SelectLatticePin(Operator):
    bl_idname = "fbp.select_lattice_pin"
    bl_label = "Select Pin"
    bl_description = "Select this pin in Pose Mode (Shift adds it to the selection). Then G moves it, R rotates it and I keyframes it"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})
    pin_name: StringProperty(name="Pin", default="", description="Pin to select; empty selects every pin", options={'HIDDEN'})
    extend: BoolProperty(name="Extend", default=False, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.extend = bool(event.shift)
        return self.execute(context)

    def execute(self, context):
        from .lattice_pins import puppet_pins
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        pins = puppet_pins(rig)
        chosen = [pin for pin in pins if not self.pin_name or pin.name == self.pin_name]
        if not chosen:
            return {'CANCELLED'}
        from .lattice_pins import select_pins
        if self.extend:
            chosen = [pin for pin in pins if pin in chosen or bool(getattr(pin, "select", False))]
        if not select_pins(context, rig, chosen):
            self.report({'ERROR'}, "Could not select the pin")
            return {'CANCELLED'}
        fbp_focus_lattice_ui(context, rig)
        return {'FINISHED'}


def _fbp_select_only(context, obj, mode=None):
    """Make obj the only selected, active object, optionally entering a mode."""
    try:
        current = context.view_layer.objects.active
        for item in (current, obj):
            if item is not None and str(getattr(item, "mode", "OBJECT")) != "OBJECT":
                with context.temp_override(active_object=item, object=item, selected_objects=[item], selected_editable_objects=[item]):
                    bpy.ops.object.mode_set(mode="OBJECT")
        for item in tuple(context.view_layer.objects.selected):
            item.select_set(False)
        obj.hide_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        if mode and mode != "OBJECT":
            with context.temp_override(active_object=obj, object=obj, selected_objects=[obj], selected_editable_objects=[obj]):
                bpy.ops.object.mode_set(mode=mode)
        return str(getattr(obj, "mode", "OBJECT")) == str(mode or "OBJECT")
    except FBP_DATA_ERRORS:
        return False


class FBP_OT_AddLatticeBones(_FBPLatticeClickModal, Operator):
    bl_idname = "fbp.add_lattice_bones"
    bl_label = "Add Bones"
    bl_description = "Click joints on the layer to draw a chain of bones: shoulder, elbow, hand. Right Click ends the chain (start the next one on a joint to branch from it), Ctrl+Click removes the last bone, Enter finishes in Pose Mode. Chains get an IK handle at their end"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})

    def _status(self, context):
        text = (
            "Bones: Click the next joint  ·  Right Click ends this chain  ·  Ctrl+Click removes the last bone  ·  Enter: done"
            if self._joint is not None
            else "Bones: Click the first joint (on a joint to branch from it)  ·  Enter / Esc / Right Click: done"
        )
        try:
            context.workspace.status_text_set(text)
        except FBP_DATA_ERRORS:
            pass

    def invoke(self, context, event):
        del event
        from .lattice_bones import bones_object, ensure_armature
        from .lattice_pins import needs_denser_cage, puppet_grid_points
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if not _fbp_lattice_exit_edit(context, _fbp_lattice_object(rig) if rig is not None else None):
            return {'CANCELLED'}
        if type(self).fbp_is_running(str(self.rig_name or "")):
            self._fbp_claim()
            return {'CANCELLED'}
        rig, helper, plane = _fbp_lattice_pins_target(self)
        if helper is None:
            return {'CANCELLED'}
        screen = getattr(getattr(context, "window", None), "screen", None)
        if screen is None or not any(area.type == 'VIEW_3D' for area in screen.areas):
            self.report({'ERROR'}, "Open a 3D View to draw bones")
            return {'CANCELLED'}
        if bones_object(rig) is None and needs_denser_cage(helper):
            if not _fbp_refine_lattice_cage(self, rig, plane, *puppet_grid_points(plane)):
                return {'CANCELLED'}
            helper = _fbp_lattice_object(rig)
        armature = ensure_armature(rig, helper, plane)
        # The bones are the handles now; the dense cage would only add clutter.
        fbp_set_rna_property_silent(rig, "fbp_lattice_show_cage", False)
        if not _fbp_select_only(context, armature, "EDIT"):
            self.report({'ERROR'}, "Could not edit the bones")
            return {'CANCELLED'}
        self._armature_name = armature.name
        self._joint = None
        self._parent = ""
        self._chain = []
        self._chains = []
        self._fbp_claim()
        self._status(context)
        try:
            context.window.cursor_modal_set('CROSSHAIR')
        except FBP_DATA_ERRORS:
            pass
        context.window_manager.modal_handler_add(self)
        _fbp_tag_view3d_redraw()
        return {'RUNNING_MODAL'}

    def _armature(self):
        return bpy.data.objects.get(self._armature_name)

    def _end_chain(self):
        if self._chain:
            self._chains.append(list(self._chain))
        self._chain = []
        self._joint = None
        self._parent = ""

    def _click(self, context, region, region_3d, coord, ctrl):
        from bpy_extras import view3d_utils
        from .lattice_bones import add_bone, armature_world, local_point, nearest_joint, remove_bone
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        armature = self._armature()
        plane = _fbp_plane(rig) if rig is not None else None
        if rig is None or armature is None or plane is None:
            return
        if str(armature.mode) != 'EDIT':
            _fbp_select_only(context, armature, "EDIT")
        if ctrl:
            if self._chain:
                name = self._chain.pop()
                bone = armature.data.edit_bones.get(name)
                self._joint = bone.head.copy() if bone is not None else None
                self._parent = bone.parent.name if bone is not None and bone.parent else ""
                remove_bone(armature, name)
            else:
                self._joint = None
                self._parent = ""
            return
        rest = _fbp_click_rest_point(context, plane, region, region_3d, coord)
        if rest is None:
            return
        world = armature_world(rig, armature)
        if self._joint is None:
            limit = 16.0 * float(getattr(context.preferences.system, "ui_scale", 1.0) or 1.0)
            joint, parent = nearest_joint(
                armature, world,
                lambda point: view3d_utils.location_3d_to_region_2d(region, region_3d, point),
                coord, limit,
            )
            if joint is None:
                joint, parent = local_point(rig, armature, rest), ""
            self._joint = joint
            self._parent = parent
            try:
                context.scene.cursor.location = world @ joint
            except FBP_DATA_ERRORS:
                pass
            return
        local = local_point(rig, armature, rest)
        if (local - self._joint).length < 1.0e-4:
            return
        name = add_bone(armature, self._joint, local, self._parent)
        self._chain.append(name)
        self._joint = local
        self._parent = name

    def _fbp_safe_finish(self, context):
        try:
            return self._finish(context)
        except Exception as exc:  # noqa: BLE001 - the tool must end even if the bones could not be finished
            self._fbp_release()
            restore_modal_cursor(context)
            try:
                context.workspace.status_text_set(None)
            except FBP_DATA_ERRORS:
                pass
            self.report({'ERROR'}, f"Could not finish the bones: {exc}")
            return {'CANCELLED'}

    def _finish(self, context):
        from .lattice_bones import add_ik_target, bind, bones_object, deform_bones, handle_size, remove_bones, setup_pose_constraints
        self._fbp_release()
        _fbp_tag_view3d_redraw()
        self._end_chain()
        try:
            context.workspace.status_text_set(None)
        except FBP_DATA_ERRORS:
            pass
        restore_modal_cursor(context)
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        armature = self._armature()
        helper = _fbp_lattice_object(rig) if rig is not None else None
        plane = _fbp_plane(rig) if rig is not None else None
        if armature is None or helper is None or plane is None:
            return {'CANCELLED'}
        chains = []
        use_ik = bool(getattr(rig, "fbp_lattice_bones_ik", True))
        if str(armature.mode) != 'EDIT':
            _fbp_select_only(context, armature, "EDIT")
        for chain in self._chains:
            target = add_ik_target(armature, chain) if use_ik and len(chain) >= 2 else ""
            chains.append((chain, target))
        _fbp_select_only(context, armature, "OBJECT")
        if not deform_bones(armature):
            remove_bones(rig, helper)
            if bones_object(rig) is None:
                _fbp_select_only(context, rig)
            return {'CANCELLED'}
        _fbp_select_only(context, armature, "POSE")
        setup_pose_constraints(armature, chains, size=handle_size(plane, "IK", rig))
        bind(rig, helper, plane, force=True)
        _fbp_invalidate_live_lattice_cache()
        self.report({'INFO'}, "Bones ready: R rotates a bone, G moves an IK handle, I keys the pose")
        for area in getattr(getattr(context, "screen", None), "areas", ()) or ():
            area.tag_redraw()
        return {'FINISHED'}

    def modal(self, context, event):
        if self._fbp_superseded():
            return self._fbp_safe_finish(context)
        if event.type in {'RET', 'NUMPAD_ENTER', 'ESC'} and event.value == 'PRESS':
            return self._fbp_safe_finish(context)
        area, region, region_3d = _fbp_view3d_under_mouse(context, event)
        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            if area is None or region is None:
                return {'PASS_THROUGH'}
            if self._joint is None:
                return self._fbp_safe_finish(context)
            self._end_chain()
            self._status(context)
            area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and region is not None and region_3d is not None:
            coord = (event.mouse_x - region.x, event.mouse_y - region.y)
            try:
                self._click(context, region, region_3d, coord, bool(event.ctrl))
            except Exception as exc:  # noqa: BLE001 - a failed click must never leave the tool stuck
                self.report({'ERROR'}, f"Could not add the bone: {exc}")
            self._status(context)
            area.tag_redraw()
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}


_FBP_LATTICE_BONE_ACTIONS = (
    ('POSE', "Pose", "Select the bones in Pose Mode: R rotates a bone, G moves an IK handle"),
    ('EDIT', "Edit Bones", "Move joints in Edit Mode; the weights follow when you press Done"),
    ('DONE', "Done", "Leave the bones and rebuild their weights on the layer"),
    ('REST', "Rest Pose", "Clear the pose of every bone at the current frame"),
    ('KEY', "Key Pose", "Keyframe every bone at the current frame"),
    ('REMOVE', "Remove Bones", "Remove the bones, their weights and their animation"),
)


class FBP_OT_LatticeBonesAction(Operator):
    bl_idname = "fbp.lattice_bones_action"
    bl_label = "Lattice Bones"
    bl_description = "Pose, edit, key or remove the bones of this layer"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})
    action: EnumProperty(name="Action", items=_FBP_LATTICE_BONE_ACTIONS, default='POSE', options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        del context
        for identifier, _label, text in _FBP_LATTICE_BONE_ACTIONS:
            if identifier == properties.action:
                return text
        return cls.bl_description

    def execute(self, context):
        from .lattice_bones import bind, bones_object, deform_bones, key_pose, remove_bones, reset_pose
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        helper = _fbp_lattice_object(rig) if rig is not None else None
        plane = _fbp_plane(rig) if rig is not None else None
        armature = bones_object(rig)
        if armature is None or helper is None or plane is None or not deform_bones(armature):
            self.report({'WARNING'}, "This layer has no bones")
            return {'CANCELLED'}
        if self.action == 'POSE':
            if not _fbp_select_only(context, armature, "POSE"):
                return {'CANCELLED'}
            try:
                from .effect_controls import ensure_posed_layer_controls
                ensure_posed_layer_controls(context, rig)
            except (ImportError,) + FBP_DATA_ERRORS:
                pass
        elif self.action == 'EDIT':
            if not _fbp_select_only(context, armature, "EDIT"):
                return {'CANCELLED'}
        elif self.action == 'DONE':
            _fbp_select_only(context, armature, "OBJECT")
            bind(rig, helper, plane, force=False)
            _fbp_select_only(context, armature, "POSE")
        elif self.action == 'REST':
            reset_pose(armature)
        elif self.action == 'KEY':
            count = key_pose(armature, frame=context.scene.frame_current)
            self.report({'INFO'}, f"Keyed {len(deform_bones(armature))} bones" if count else "Nothing to key")
        else:
            if str(armature.mode) == 'EDIT':
                _fbp_select_only(context, armature, "OBJECT")
            remove_bones(rig, helper)
            if bones_object(rig) is None:
                _fbp_select_only(context, rig)
        fbp_focus_lattice_ui(context, rig)
        _fbp_invalidate_live_lattice_cache()
        return {'FINISHED'}


_FBP_LATTICE_CORNER_ACTIONS = (
    ('SETUP', "Set Up Corner Pin", "Put four handles on the corners. Move them to place the layer in perspective"),
    ('RESET', "Reset Corners", "Return the handles to the layer's corners"),
    ('KEY', "Key Corners", "Keyframe the four handles at the current frame"),
    ('SELECT', "Select Corners", "Select the four handles"),
    ('REMOVE', "Remove Corner Pin", "Remove the handles and return to a flat Freeform cage"),
)


class FBP_OT_LatticeCornerPin(Operator):
    bl_idname = "fbp.lattice_corner_pin"
    bl_label = "Corner Pin"
    bl_description = "Set up, reset, key or remove the Corner Pin of this layer"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})
    action: EnumProperty(name="Action", items=_FBP_LATTICE_CORNER_ACTIONS, default='SETUP', options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        del context
        for identifier, _label, text in _FBP_LATTICE_CORNER_ACTIONS:
            if identifier == properties.action:
                return text
        return cls.bl_description

    def execute(self, context):
        from .lattice_corner_pin import MIN_POINTS, corner_handles, ensure_handles, remove_handles, reset_handles
        from .lattice_pins import select_pins
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None or not _fbp_lattice_exit_edit(context, _fbp_lattice_object(rig)):
            return {'CANCELLED'}
        if rig is None or not _fbp_apply_lattice_effect(rig, select=False):
            self.report({'ERROR'}, _fbp_last_lattice_error(rig) or "Could not create the Lattice cage")
            return {'CANCELLED'}
        helper = _fbp_lattice_object(rig)
        plane = _fbp_plane(rig)
        if self.action == 'SETUP':
            if not _fbp_refine_lattice_cage(self, rig, plane, MIN_POINTS, MIN_POINTS):
                return {'CANCELLED'}
            helper = _fbp_lattice_object(rig)
            fbp_set_rna_property_silent(rig, "fbp_lattice_mode", "CORNER_PIN")
            helper[_FBP_LATTICE_MODE_KEY] = "CORNER_PIN"
            _fbp_update_lattice_data(rig, helper)
            ensure_handles(rig, helper, plane)
            _fbp_apply_lattice_corner_pin(rig, force=True)
            _fbp_invalidate_live_lattice_cache()
            select_pins(context, rig, list(corner_handles(rig).values()))
            self.report({'INFO'}, "Corner Pin ready: move the corner handles (G)")
        elif self.action == 'RESET':
            reset_handles(rig, helper)
            _fbp_apply_lattice_corner_pin(rig, force=True)
        elif self.action == 'KEY':
            for handle in corner_handles(rig).values():
                handle.keyframe_insert("location", frame=context.scene.frame_current)
        elif self.action == 'SELECT':
            handles = list(corner_handles(rig).values())
            if not handles or not select_pins(context, rig, handles):
                return {'CANCELLED'}
        else:
            remove_handles(rig, helper)
            fbp_set_rna_property_silent(rig, "fbp_lattice_mode", "FREEFORM")
            helper[_FBP_LATTICE_MODE_KEY] = "FREEFORM"
            _fbp_update_lattice_data(rig, helper)
            _fbp_reset_lattice_points(helper)
            _fbp_invalidate_live_lattice_cache()
        fbp_focus_lattice_ui(context, rig)
        return {'FINISHED'}


_FBP_LATTICE_HANDLE_ACTIONS = (
    ('ADD', "Add Point Handles", "Give every cage point a handle you can move and keyframe in Pose Mode, without editing the cage"),
    ('KEY', "Key Points", "Keyframe every point handle at the current frame"),
    ('REST', "Rest", "Return every point handle to its cage point"),
    ('SELECT', "Pose Points", "Enter Pose Mode on the point handles (Ctrl+T on the plane does the same)"),
    ('REMOVE', "Remove Point Handles", "Remove the point handles and their animation"),
)


class FBP_OT_LatticePointHandles(Operator):
    bl_idname = "fbp.lattice_point_handles"
    bl_label = "Point Handles"
    bl_description = "Add, key, reset or remove the point handles of the Grid cage"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})
    action: EnumProperty(name="Action", items=_FBP_LATTICE_HANDLE_ACTIONS, default='ADD', options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        del context
        for identifier, _label, text in _FBP_LATTICE_HANDLE_ACTIONS:
            if identifier == properties.action:
                return text
        return cls.bl_description

    def execute(self, context):
        from .lattice_pins import KIND_POINT, MAX_POINT_HANDLES, add_point_handles, key_pins, remove_all_pins, reset_pins, rig_pins, select_pins
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None or not _fbp_lattice_exit_edit(context, _fbp_lattice_object(rig)):
            return {'CANCELLED'}
        rig, helper, plane = _fbp_lattice_pins_target(self)
        if helper is None:
            return {'CANCELLED'}
        handles = rig_pins(rig, kinds=(KIND_POINT,))
        if self.action == 'ADD':
            if not add_point_handles(rig, helper, plane):
                self.report({'WARNING'}, f"Point handles need a cage of at most {MAX_POINT_HANDLES} points (for example 8 × 8)")
                return {'CANCELLED'}
            fbp_set_rna_property_silent(rig, "fbp_lattice_show_cage", True)
            select_pins(context, rig, [])
        elif not handles:
            self.report({'WARNING'}, "This layer has no point handles")
            return {'CANCELLED'}
        elif self.action == 'KEY':
            key_pins(handles, frame=context.scene.frame_current)
        elif self.action == 'REST':
            reset_pins(handles)
        elif self.action == 'SELECT':
            select_pins(context, rig, handles)
        else:
            remove_all_pins(rig, helper, kinds=(KIND_POINT,))
        fbp_focus_lattice_ui(context, rig)
        _fbp_invalidate_live_lattice_cache()
        return {'FINISHED'}


_FBP_LATTICE_PIN_ACTIONS = (
    ('KEY', "Key Pins", "Keyframe the location, rotation and scale of every pin at the current frame"),
    ('REST', "Rest Pose", "Return every pin to its rest placement so the layer is no longer bent by the pins"),
    ('SET_REST', "Set as Rest", "Keep the pins where they are and make that their rest placement: the drawing under them goes back to its undeformed shape. Use it to move a pin to a better spot"),
)


class FBP_OT_LatticePinsAction(Operator):
    bl_idname = "fbp.lattice_pins_action"
    bl_label = "Puppet Pins"
    bl_description = "Keyframe, reset or rebind the puppet pins of this layer"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})
    action: EnumProperty(
        name="Action",
        items=_FBP_LATTICE_PIN_ACTIONS,
        default='KEY',
        options={'SKIP_SAVE'},
    )

    @classmethod
    def description(cls, context, properties):
        del context
        for identifier, _label, text in _FBP_LATTICE_PIN_ACTIONS:
            if identifier == properties.action:
                return text
        return cls.bl_description

    def execute(self, context):
        from .lattice_pins import key_pins, puppet_pins, reset_pins, set_rest_from_current
        rig, helper, plane = _fbp_lattice_pins_target(self)
        if helper is None:
            return {'CANCELLED'}
        pins = puppet_pins(rig)
        if not pins:
            self.report({'WARNING'}, "This layer has no puppet pins")
            return {'CANCELLED'}
        if self.action == 'KEY':
            key_pins(pins, frame=context.scene.frame_current)
            self.report({'INFO'}, f"Keyed {len(pins)} pin{'s' if len(pins) != 1 else ''}")
        elif self.action == 'REST':
            reset_pins(pins)
        else:
            set_rest_from_current(rig, helper, plane, pins)
        _fbp_invalidate_live_lattice_cache()
        return {'FINISHED'}


class FBP_OT_RefitLatticeHelper(Operator):
    bl_idname = "fbp.refit_lattice_helper"
    bl_label = "Refit Lattice"
    bl_description = "Refit the generated Lattice around the current linked plane bounds without deleting manual point edits"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(description='Name of the generated Frame By Plane rig that owns the layer, helper, mask or action target.', options={'HIDDEN'})

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


class FBP_OT_LoadEffectImage(Operator):
    bl_idname = "fbp.load_effect_image"
    bl_label = "Load Effect Image"
    bl_description = "Load an image from disk and assign it directly to this effect map slot"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    filepath: StringProperty(name="Image", subtype='FILE_PATH', options={'SKIP_SAVE'})
    filter_glob: StringProperty(
        default="*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.tga;*.bmp;*.webp;*.exr;*.hdr;*.dpx",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    rig_name: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    rig_key: StringProperty(
        default="", options={'HIDDEN', 'SKIP_SAVE'},
        description="Runtime identity captured before the file browser opens",
    )
    effect_id: StringProperty(default=FBP_EFFECT_CRYSTAL, options={'HIDDEN', 'SKIP_SAVE'})
    property_name: StringProperty(
        default="fbp_crystal_influence_image", options={'HIDDEN', 'SKIP_SAVE'}
    )

    def invoke(self, context, event):
        del event
        rig = bpy.data.objects.get(str(self.rig_name or ""))
        if rig is not None and not self.rig_key:
            self.rig_key = fbp_obj_runtime_token(rig)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        effect_id = fbp_normalize_effect_id(self.effect_id)
        property_name = str(self.property_name or "")
        enable_property = _FBP_LOADABLE_EFFECT_IMAGES.get((effect_id, property_name))
        if enable_property is None:
            self.report({'ERROR'}, "Unsupported effect image slot")
            return {'CANCELLED'}
        rig = fbp_find_id_by_runtime_key(
            bpy.data.objects, self.rig_key, self.rig_name,
        ) if self.rig_key else bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None or not hasattr(rig, property_name):
            self.report({'ERROR'}, "Frame By Plane layer is unavailable")
            return {'CANCELLED'}
        path = os.path.abspath(bpy.path.abspath(str(self.filepath or "")))
        if not path or not os.path.isfile(path):
            self.report({'ERROR'}, "Choose an existing image file")
            return {'CANCELLED'}
        try:
            image = bpy.data.images.load(path, check_existing=True)
            # Data masks must not receive a display transform before Geometry
            # Nodes samples their grayscale values.
            try:
                image.colorspace_settings.name = "Non-Color"
            except FBP_DATA_ERRORS:
                pass
            fbp_set_rna_property_silent(rig, property_name, image)
            changed = {property_name}
            if enable_property and hasattr(rig, enable_property):
                fbp_set_rna_property_silent(rig, enable_property, True)
                changed.add(enable_property)
            if fbp_effect_is_active(rig, effect_id):
                fbp_update_geometry_effect(
                    rig, effect_id, scene=getattr(context, "scene", None),
                    property_names=changed,
                )
            fbp_tag_redraw(context, area_types={'VIEW_3D', 'PROPERTIES'})
        except FBP_DATA_IO_ERRORS as exc:
            self.report({'ERROR'}, f"Could not load effect image: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Loaded map: {os.path.basename(path)}")
        return {'FINISHED'}


class FBP_OT_ClearEffectImage(Operator):
    bl_idname = "fbp.clear_effect_image"
    bl_label = "Clear Effect Image"
    bl_description = "Remove the image assigned to this effect map slot"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    rig_name: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    rig_key: StringProperty(
        default="", options={'HIDDEN', 'SKIP_SAVE'},
        description="Runtime identity captured before the file browser opens",
    )
    effect_id: StringProperty(default=FBP_EFFECT_CRYSTAL, options={'HIDDEN', 'SKIP_SAVE'})
    property_name: StringProperty(
        default="fbp_crystal_influence_image", options={'HIDDEN', 'SKIP_SAVE'}
    )

    def execute(self, context):
        effect_id = fbp_normalize_effect_id(self.effect_id)
        property_name = str(self.property_name or "")
        if (effect_id, property_name) not in _FBP_LOADABLE_EFFECT_IMAGES:
            return {'CANCELLED'}
        rig = fbp_find_id_by_runtime_key(
            bpy.data.objects, self.rig_key, self.rig_name,
        ) if self.rig_key else bpy.data.objects.get(str(self.rig_name or ""))
        if rig is None or not hasattr(rig, property_name):
            return {'CANCELLED'}
        fbp_set_rna_property_silent(rig, property_name, None)
        if fbp_effect_is_active(rig, effect_id):
            fbp_update_geometry_effect(
                rig, effect_id, scene=getattr(context, "scene", None),
                property_names={property_name},
            )
        fbp_tag_redraw(context, area_types={'VIEW_3D', 'PROPERTIES'})
        return {'FINISHED'}
