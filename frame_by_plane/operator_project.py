"""Focused Frame by Plane operator module."""

import bpy
import os
import gc
import statistics
import tempfile
import time
from datetime import datetime
from pathlib import Path
from bpy.props import (
    BoolProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator

from .runtime import FBP_DATA_ERRORS, fbp_set_rna_property_silent
from .diagnostics import (
    diagnostic_report_messages,
    last_diagnostic_report,
    write_diagnostic_report,
)
from .render_parity import fbp_render_parity_status
from .layers import (
    collect_project_image_paths,
    collection_has_fbp_content,
    collection_is_hidden_in_view_layer,
    get_primary_fbp_collection,
    fbp_layer_backend_type,
    is_fbp_layer_object,
    iter_fbp_rigs_in_collection,
    missing_project_images,
    object_in_view_layer,
    project_root_for_package,
    relink_missing_images_from_root,
    rig_has_missing_images,
    sync_collection_colors_to_rigs,
)
from .scene_sync import sync_layer_collection
from .builder import build_fbp_color_rig
from .native_backend import (
    FBP_NATIVE_RENDER_CONTRACT_REVISION,
    build_native_fbp_rig,
    fbp_native_media_cache_report,
    fbp_native_rig_contract_issues,
    fbp_native_timing_self_test,
    fbp_probe_native_rig_timing,
    fbp_refresh_native_sequence_from_rig,
    rebuild_native_sequence_from_rig,
)
from .geometry_nodes import (
    fbp_add_effect,
    fbp_effect_ids_for_rig,
    fbp_effect_runtime_diagnostics,
    fbp_effect_instance_id_for_rig,
    fbp_find_effect_modifier,
    fbp_lattice_contract_report,
    fbp_local_effect_mask_contract_report,
    fbp_effect_render_guard_pre,
    fbp_effect_render_guard_post,
    fbp_effect_render_visible_state,
    fbp_effect_order_warning,
    fbp_sort_effect_stacks_transactional,
    fbp_refresh_effect_instance_ids,
    fbp_reapply_all_effects,
    fbp_sync_scene_camera_bindings,
    fbp_sync_clipping_masks,
    fbp_set_effect_mask_target,
    fbp_sync_effect_items,
    fbp_update_geometry_effect,
    fbp_update_shader_effect,
)
from .effects_registry import (
    FBP_EFFECT_REGISTRY,
    FBP_EFFECT_REGISTRY_ISSUES,
    FBP_BASE_EFFECT_MENU_ORDER,
    FBP_SHADER_STAGE_ORDER,
    FBP_3D_EFFECT_MENU_ORDER,
    fbp_effect_definition,
    fbp_effect_supported_for_rig,
    fbp_normalize_effect_id,
)
from .operator_common import (
    _fbp_active_pending_index_and_collection,
    _fbp_active_pending_tree_row,
    _fbp_refresh_pending_tree,
    _fbp_select_pending_index,
)
from .object_masks import (
    audit_object_masks,
    is_object_mask_helper,
    sync_owner_object_mask_runtime,
)
from .effect_controls import audit_effect_controls
from .lifecycle import lifecycle_audit


class FBP_OT_RemovePendingTreeSelection(Operator):
    bl_idname = "fbp.remove_pending_tree_selection"
    bl_label = "Remove Setup Selection"
    bl_description = "Remove the selected setup layer, or the selected collection with all internal layers"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sc = context.scene
        row = _fbp_active_pending_tree_row(sc)
        if row is not None and getattr(row, 'row_type', 'LAYER') == 'GROUP':
            collection_path = getattr(row, 'collection_path', '') or ''
            if not collection_path:
                return {'CANCELLED'}
            removed = 0
            for i in range(len(sc.fbp_pending_planes) - 1, -1, -1):
                cname = getattr(sc.fbp_pending_planes[i], 'collection_name', '') or ''
                if cname == collection_path or cname.startswith(collection_path + ' /'):
                    sc.fbp_pending_planes.remove(i)
                    removed += 1
            _fbp_select_pending_index(context, min(int(getattr(sc, 'fbp_pending_planes_idx', 0)), max(0, len(sc.fbp_pending_planes) - 1)))
            return {'FINISHED'} if removed else {'CANCELLED'}

        idx, _collection_name, _row_type = _fbp_active_pending_index_and_collection(sc)
        if 0 <= idx < len(sc.fbp_pending_planes):
            sc.fbp_pending_planes.remove(idx)
            _fbp_select_pending_index(context, min(idx, max(0, len(sc.fbp_pending_planes) - 1)))
            return {'FINISHED'}
        return {'CANCELLED'}

class FBP_OT_RemovePendingPlaneAtIndex(Operator):
    bl_idname = "fbp.remove_pending_plane_at_index"
    bl_label = "Remove Setup Layer"
    bl_description = "Remove this pending layer from the Multiplane Setup before generating planes"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="Index", description="Zero-based index of the pending Multiplane Setup row to remove. Source media and already generated scene layers are never deleted by this action.", default=-1)

    def execute(self, context):
        sc = context.scene
        if 0 <= self.index < len(sc.fbp_pending_planes):
            sc.fbp_pending_planes.remove(self.index)
            sc.fbp_pending_planes_idx = min(max(0, self.index - 1), max(0, len(sc.fbp_pending_planes) - 1))
            _fbp_refresh_pending_tree(context)
            return {'FINISHED'}
        return {'CANCELLED'}

class FBP_OT_ProjectHealthCheck(Operator):
    bl_idname      = "fbp.project_health_check"
    bl_label       = "Project Health Check"
    bl_description = "Check linked images, collections and layers in the current Frame by Plane project"

    def execute(self, context):
        sync_layer_collection(context)
        rigs = [obj for obj in context.scene.objects if is_fbp_layer_object(obj)]
        fbp_colls = [coll for coll in bpy.data.collections if collection_has_fbp_content(coll, True)]
        image_paths = collect_project_image_paths()
        missing = missing_project_images()
        empty_fbp_colls = [coll.name for coll in fbp_colls if not any(True for _ in iter_fbp_rigs_in_collection(coll, True))]
        lines = [
            "Frame By Plane — Project Health",
            "================================",
            f"Layers: {len(rigs)}",
            f"Collections: {len(fbp_colls)}",
            f"Linked images: {len(image_paths)}",
            f"Missing images: {len(missing)}",
            f"Empty FBP collections: {len(empty_fbp_colls)}",
            "",
        ]
        if missing:
            lines.append("Missing files:")
            lines.extend(f"- {p}" for p in missing[:200])
            if len(missing) > 200:
                lines.append(f"...and {len(missing) - 200} more")
        else:
            lines.append("No missing files found.")
        summary = f"Project Health · {len(rigs)} layers · {len(missing)} missing image(s)"
        write_diagnostic_report(
            context.scene, "FBP_Project_Health", lines,
            summary=summary, status="PASS" if not missing else "WARNING",
        )
        level = {'INFO'} if not missing else {'WARNING'}
        self.report(level, summary)
        return {'FINISHED'}


def _fbp_effect_stack_contract_audit(rigs, *, repair=False):
    """Validate effect compatibility, stored stage order and recommended order.

    This audit deliberately treats user-defined ordering as a warning rather
    than corruption. Unknown tagged effects and effects that no longer support
    their owner layer are structural issues because they cannot be rebuilt
    deterministically by the current registry.
    """
    rigs = tuple(rig for rig in tuple(rigs or ()) if rig is not None)
    stats = {
        "effect_stack_rigs": len(rigs),
        "effect_stack_unsupported": 0,
        "effect_stack_unknown_tags": 0,
        "effect_stack_order_warnings": 0,
        "effect_stack_metadata_warnings": 0,
        "effect_stack_repairs": 0,
    }
    issues = []
    warnings = []
    recommended = (
        list(FBP_BASE_EFFECT_MENU_ORDER)
        + list(FBP_SHADER_STAGE_ORDER.get("UV", ()))
        + list(FBP_SHADER_STAGE_ORDER.get("COLOR", ()))
        + list(FBP_SHADER_STAGE_ORDER.get("MASK", ()))
        + list(FBP_3D_EFFECT_MENU_ORDER)
    )

    if repair:
        out_of_order = []
        for rig in rigs:
            try:
                if any(
                    fbp_effect_order_warning(rig, effect_id)
                    for effect_id in fbp_effect_ids_for_rig(rig)
                ):
                    out_of_order.append(rig)
            except FBP_DATA_ERRORS:
                continue
        if out_of_order and fbp_sort_effect_stacks_transactional(
            out_of_order, recommended
        ):
            stats["effect_stack_repairs"] += len(out_of_order)

    for rig in rigs:
        rig_name = str(getattr(rig, "name", "<unnamed rig>") or "<unnamed rig>")
        try:
            effect_ids = tuple(fbp_effect_ids_for_rig(rig))
        except FBP_DATA_ERRORS as exc:
            issues.append(f"{rig_name}: effect stack discovery failed: {exc}")
            continue

        for effect_id in effect_ids:
            if not fbp_effect_supported_for_rig(rig, effect_id):
                stats["effect_stack_unsupported"] += 1
                issues.append(
                    f"{rig_name}: {effect_id} is active but incompatible with this layer type"
                )
            warning = fbp_effect_order_warning(rig, effect_id)
            if warning:
                stats["effect_stack_order_warnings"] += 1
                warnings.append(f"{rig_name}: {effect_id}: {warning}")

        plane = getattr(rig, "fbp_plane_target", None)
        if plane is not None:
            try:
                for modifier in tuple(getattr(plane, "modifiers", ()) or ()):
                    if str(getattr(modifier, "type", "") or "") != "NODES":
                        continue
                    raw = str(modifier.get("fbp_effect_id", "") or "")
                    group = getattr(modifier, "node_group", None)
                    if not raw and group is not None:
                        raw = str(group.get("fbp_effect_id", "") or "")
                    if not raw:
                        continue
                    normalized = fbp_normalize_effect_id(raw)
                    definition = fbp_effect_definition(normalized)
                    if not definition or definition.get("kind") != "GEOMETRY":
                        stats["effect_stack_unknown_tags"] += 1
                        issues.append(
                            f"{rig_name}: modifier {modifier.name!r} carries unknown effect tag {raw!r}"
                        )
            except FBP_DATA_ERRORS:
                warnings.append(f"{rig_name}: geometry modifier tags could not be inspected")
                stats["effect_stack_metadata_warnings"] += 1

        for material in tuple(
            mat for mat in tuple(getattr(getattr(plane, "data", None), "materials", ()) or ())
            if mat is not None
        ):
            active_by_stage = {stage: [] for stage in FBP_SHADER_STAGE_ORDER}
            try:
                node_tree = getattr(material, "node_tree", None)
                for node in tuple(getattr(node_tree, "nodes", ()) or ()):
                    raw = str(node.get("fbp_shader_effect_id", "") or "")
                    if not raw:
                        continue
                    normalized = fbp_normalize_effect_id(raw)
                    definition = fbp_effect_definition(normalized)
                    if not definition or definition.get("kind") != "SHADER":
                        stats["effect_stack_unknown_tags"] += 1
                        issues.append(
                            f"{rig_name}: material {material.name!r} contains unknown shader effect tag {raw!r}"
                        )
                        continue
                    stage = str(definition.get("stage", "") or "")
                    if stage in active_by_stage and normalized not in active_by_stage[stage]:
                        active_by_stage[stage].append(normalized)
            except FBP_DATA_ERRORS:
                warnings.append(f"{rig_name}: material {material.name!r} effect nodes could not be inspected")
                stats["effect_stack_metadata_warnings"] += 1
                continue

            for stage, active_ids in active_by_stage.items():
                key = f"fbp_shader_effect_order_{stage.lower()}"
                try:
                    raw_order = str(material.get(key, "") or "")
                except FBP_DATA_ERRORS:
                    raw_order = ""
                tokens = [token for token in raw_order.split("|") if token]
                normalized_tokens = []
                stale_tokens = []
                for token in tokens:
                    normalized = fbp_normalize_effect_id(token)
                    definition = fbp_effect_definition(normalized)
                    if (
                        definition.get("kind") == "SHADER"
                        and str(definition.get("stage", "") or "") == stage
                        and normalized in active_ids
                    ):
                        if normalized not in normalized_tokens:
                            normalized_tokens.append(normalized)
                    else:
                        stale_tokens.append(token)
                normalized_tokens.extend(
                    effect_id for effect_id in active_ids
                    if effect_id not in normalized_tokens
                )
                desired = "|".join(normalized_tokens)
                if stale_tokens or desired != raw_order:
                    stats["effect_stack_metadata_warnings"] += 1
                    warnings.append(
                        f"{rig_name}: {material.name}: {stage} stage order metadata is stale"
                    )
                    if repair:
                        try:
                            material[key] = desired
                            stats["effect_stack_repairs"] += 1
                        except FBP_DATA_ERRORS:
                            pass

        # Keep the owner-level stage mirror in sync with the evaluated material
        # order. This metadata is used after Undo or file load before the UI list
        # has been rebuilt.
        if repair:
            for stage in FBP_SHADER_STAGE_ORDER:
                desired_ids = [
                    effect_id for effect_id in effect_ids
                    if (
                        fbp_effect_definition(effect_id).get("kind") == "SHADER"
                        and fbp_effect_definition(effect_id).get("stage") == stage
                    )
                ]
                key = f"fbp_shader_effect_order_{stage.lower()}"
                desired = "|".join(desired_ids)
                try:
                    if str(rig.get(key, "") or "") != desired:
                        rig[key] = desired
                        stats["effect_stack_repairs"] += 1
                except FBP_DATA_ERRORS:
                    pass

    return {
        "stats": stats,
        "issues": tuple(issues),
        "warnings": tuple(warnings),
        "repaired": int(stats["effect_stack_repairs"]),
    }


def _fbp_rna_identity(value):
    if value is None:
        return None
    try:
        pointer = int(value.as_pointer())
    except FBP_DATA_ERRORS:
        pointer = 0
    if pointer:
        return pointer
    try:
        return (str(getattr(value, "name_full", getattr(value, "name", "")) or ""), id(value))
    except FBP_DATA_ERRORS:
        return id(value)


def _fbp_mask_interaction_contract_audit(rigs, scene, *, repair=False, context=None, _verification=False):
    """Validate every mask route as one interaction matrix.

    The existing Shape Mask audit remains the authority for editable helper
    meshes and private SDF images. This layer adds the relationships that only
    become visible when mask systems interact: source-layer pointers, clipping
    cycles, imported raster files and per-effect receiver routing.
    """
    rig_list = []
    seen = set()
    for rig in tuple(rigs or ()):
        key = _fbp_rna_identity(rig)
        if rig is None or key in seen:
            continue
        seen.add(key)
        rig_list.append(rig)

    stats = {
        "mask_rigs": len(rig_list),
        "mask_effects": 0,
        "mask_source_effects": 0,
        "mask_missing_sources": 0,
        "mask_invalid_sources": 0,
        "mask_source_cycles": 0,
        "mask_imported_files": 0,
        "mask_missing_imported_files": 0,
        "mask_repairs": 0,
    }
    issues = []
    warnings = []

    # Shape Mask helpers and images are audited first because local routing may
    # legitimately point at those mask effects.
    object_result = audit_object_masks(
        rig_list, repair=repair, context=context
    )
    stats.update(dict(object_result.get("stats", {}) or {}))
    stats["mask_repairs"] += int(object_result.get("repaired", 0) or 0)
    issues.extend(object_result.get("issues", ()) or ())
    warnings.extend(object_result.get("warnings", ()) or ())

    scene_object_keys = {
        _fbp_rna_identity(obj)
        for obj in tuple(getattr(scene, "objects", ()) or ())
        if obj is not None
    }
    source_edges = {}
    source_repairs = 0

    for rig in rig_list:
        rig_name = str(getattr(rig, "name", "<rig>") or "<rig>")
        active_ids = tuple(fbp_effect_ids_for_rig(rig))

        local_result = fbp_local_effect_mask_contract_report(
            rig, repair=repair
        )
        local_stats = dict(local_result.get("stats", {}) or {})
        for key, value in local_stats.items():
            stats[key] = int(stats.get(key, 0) or 0) + int(value or 0)
        stats["mask_repairs"] += int(local_result.get("repaired", 0) or 0)
        issues.extend(local_result.get("issues", ()) or ())
        warnings.extend(local_result.get("warnings", ()) or ())

        for effect_id in active_ids:
            definition = fbp_effect_definition(effect_id)
            if str(definition.get("stage", "") or "").upper() != "MASK":
                continue
            stats["mask_effects"] += 1

            if bool(definition.get("imported_mask_aware", False)):
                stats["mask_imported_files"] += 1
                raw_path = str(getattr(rig, "fbp_imported_mask_path", "") or "").strip()
                resolved = ""
                if raw_path:
                    try:
                        resolved = bpy.path.abspath(raw_path)
                    except FBP_DATA_ERRORS:
                        resolved = raw_path
                try:
                    imported_exists = bool(resolved and Path(resolved).is_file())
                except (OSError, ValueError):
                    imported_exists = False
                if not imported_exists:
                    stats["mask_missing_imported_files"] += 1
                    issues.append(
                        f"{rig_name}: Imported Layer Mask file is missing: {raw_path or '<empty path>'}"
                    )

            source_property = str(definition.get("mask_source_property", "") or "")
            if not source_property:
                continue
            stats["mask_source_effects"] += 1
            try:
                source = getattr(rig, source_property, None)
            except FBP_DATA_ERRORS:
                source = None
            if source is None:
                stats["mask_missing_sources"] += 1
                issues.append(
                    f"{rig_name}: {definition.get('label', effect_id)} has no source layer"
                )
                continue

            invalid_reason = ""
            try:
                if source is rig:
                    invalid_reason = "uses its own layer as source"
                elif not is_fbp_layer_object(source):
                    invalid_reason = "source is not a Frame By Plane layer"
                elif _fbp_rna_identity(source) not in scene_object_keys:
                    invalid_reason = "source belongs to another Scene"
                elif getattr(source, "fbp_plane_target", None) is None:
                    invalid_reason = "source has no linked plane"
            except FBP_DATA_ERRORS:
                invalid_reason = "source datablock is unavailable"

            if invalid_reason:
                stats["mask_invalid_sources"] += 1
                issues.append(
                    f"{rig_name}: {definition.get('label', effect_id)} {invalid_reason}"
                )
                if repair and fbp_set_rna_property_silent(rig, source_property, None):
                    source_repairs += 1
                continue

            # Only layer-feature masks form a recursive ownership chain.
            # Alpha/Luma mattes merely sample another layer and may coexist on
            # the same target with different sources, so treating them as one
            # graph edge would overwrite valid relationships and report false
            # cycles.
            if bool(definition.get("layer_feature", False)):
                source_edges[_fbp_rna_identity(rig)] = (
                    _fbp_rna_identity(source), rig, source, effect_id
                )

    # Directed source cycles are invalid even when every pointer individually
    # resolves. Report each cycle once and leave it for explicit user review;
    # choosing which artistic relation to break is not a safe automatic repair.
    reported_cycles = set()
    for start in tuple(source_edges):
        order = []
        positions = {}
        current = start
        while current in source_edges:
            if current in positions:
                cycle_keys = order[positions[current]:]
                canonical = tuple(sorted(str(item) for item in cycle_keys))
                if canonical not in reported_cycles:
                    reported_cycles.add(canonical)
                    cycle_names = []
                    for item in cycle_keys:
                        _next_key, owner, _source, effect_id = source_edges[item]
                        label = fbp_effect_definition(effect_id).get("label", effect_id)
                        cycle_names.append(f"{getattr(owner, 'name', '<rig>')} [{label}]")
                    stats["mask_source_cycles"] += 1
                    issues.append("Mask source cycle: " + " → ".join(cycle_names + cycle_names[:1]))
                break
            positions[current] = len(order)
            order.append(current)
            current = source_edges[current][0]

    stats["mask_repairs"] += source_repairs
    if repair:
        try:
            fbp_sync_clipping_masks(context or bpy.context)
        except FBP_DATA_ERRORS as exc:
            warnings.append(f"Clipping-mask resynchronization failed: {exc}")

    result = {
        "stats": stats,
        "issues": tuple(issues),
        "warnings": tuple(warnings),
        "repaired": int(stats["mask_repairs"]),
    }
    if repair and not _verification:
        verification = _fbp_mask_interaction_contract_audit(
            rig_list, scene, repair=False, context=context, _verification=True
        )
        verification_stats = dict(verification.get("stats", {}) or {})
        verification_stats["mask_repairs"] = int(stats["mask_repairs"])
        verification["stats"] = verification_stats
        verification["repaired"] = int(stats["mask_repairs"])
        return verification
    return result


def _fbp_render_contract_audit(rigs, scene, *, repair=False):
    """Probe render-only effect state and generated helper visibility.

    This does not render an image. It executes the same pre/post guard used by
    final renders, verifies that temporary RNA changes are restored losslessly,
    and catches helper cages that could leak into Eevee or Cycles.
    """
    rig_list = []
    seen = set()
    for rig in tuple(rigs or ()):
        key = _fbp_rna_identity(rig)
        if rig is None or key in seen:
            continue
        seen.add(key)
        rig_list.append(rig)

    stats = {
        "render_rigs": len(rig_list),
        "render_effects": 0,
        "render_hidden_effects": 0,
        "render_helpers": 0,
        "render_helper_leaks": 0,
        "render_guard_mutations": 0,
        "render_restore_attempts": 0,
        "render_restore_retries": 0,
        "render_restore_failures": 0,
        "render_repairs": 0,
    }
    issues = []
    warnings = []

    for rig in rig_list:
        for effect_id in tuple(fbp_effect_ids_for_rig(rig)):
            stats["render_effects"] += 1
            if not fbp_effect_render_visible_state(rig, effect_id):
                stats["render_hidden_effects"] += 1

    for obj in tuple(getattr(scene, "objects", ()) or ()):
        is_helper = False
        try:
            is_helper = is_object_mask_helper(obj)
        except FBP_DATA_ERRORS:
            is_helper = False
        if not is_helper:
            try:
                is_helper = bool(
                    getattr(obj, "type", "") == "LATTICE"
                    and str(obj.get("fbp_lattice_effect", "") or "") == "LATTICE"
                )
            except FBP_DATA_ERRORS:
                is_helper = False
        if not is_helper:
            continue
        stats["render_helpers"] += 1
        try:
            leaks = not bool(getattr(obj, "hide_render", False))
        except FBP_DATA_ERRORS:
            leaks = True
        if leaks:
            stats["render_helper_leaks"] += 1
            issues.append(f"{getattr(obj, 'name', '<helper>')}: generated helper is enabled for render")
            if repair:
                try:
                    obj.hide_render = True
                    stats["render_repairs"] += 1
                except FBP_DATA_ERRORS:
                    pass

    backup = []
    retry = []
    try:
        backup = list(fbp_effect_render_guard_pre(scene) or ())
        stats["render_guard_mutations"] = len(backup)
    except FBP_DATA_ERRORS as exc:
        issues.append(f"Render preflight failed: {exc}")
    finally:
        if backup:
            retry = list(backup)
            for attempt in range(4):
                stats["render_restore_attempts"] = attempt + 1
                try:
                    retry = list(fbp_effect_render_guard_post(retry) or ())
                except FBP_DATA_ERRORS as exc:
                    issues.append(f"Render-state restore failed: {exc}")
                    break
                if not retry:
                    break
                try:
                    for view_layer in tuple(getattr(scene, "view_layers", ()) or ()):
                        view_layer.update()
                except FBP_DATA_ERRORS:
                    pass
                time.sleep(0.01)
    stats["render_restore_retries"] = len(retry)
    if retry:
        issues.append(f"Render-state restore left {len(retry)} deferred item(s)")

    # Verify every direct state backup after the post-render restore. Local-mask
    # rebuild markers are graph operations and have no scalar value to compare.
    for item in backup:
        try:
            tag = item[0]
            restored = True
            if tag == "NODE_MUTE":
                _tag, node, value = item
                restored = bool(getattr(node, "mute", False)) == bool(value)
            elif tag == "CONSTRAINT_MUTE":
                _tag, constraint, value = item
                restored = bool(getattr(constraint, "mute", False)) == bool(value)
            elif tag == "MODIFIER_INPUT":
                _tag, modifier, identifier, value = item
                current = modifier.get(identifier) if identifier in modifier else None
                if hasattr(current, "__len__") and not isinstance(current, (str, bytes)):
                    restored = tuple(current) == tuple(value) if value is not None else current is None
                else:
                    restored = current == value
            if not restored:
                stats["render_restore_failures"] += 1
                issues.append(f"Render guard did not restore {tag}")
        except FBP_DATA_ERRORS:
            stats["render_restore_failures"] += 1
            issues.append("Render guard restoration target became unavailable")

    return {
        "stats": stats,
        "issues": tuple(issues),
        "warnings": tuple(warnings),
        "repaired": int(stats["render_repairs"]),
    }


class FBP_OT_RunEffectsContractAudit(Operator):
    bl_idname = "fbp.run_effects_contract_audit"
    bl_label = "Run Effects Contract Audit"
    bl_description = "Validate effect compatibility, effect order, shader-stage metadata and unknown generated effect tags"

    repair: BoolProperty(
        name="Repair Safe Issues",
        description="Normalize stored shader-stage order and restore the recommended effect order without deleting effects",
        default=False,
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=460)

    def execute(self, context):
        sync_layer_collection(context)
        rigs = [obj for obj in context.scene.objects if is_fbp_layer_object(obj)]
        result = _fbp_effect_stack_contract_audit(rigs, repair=self.repair)
        stats = dict(result.get("stats", {}) or {})
        issues = list(result.get("issues", ()) or ())
        warnings = list(result.get("warnings", ()) or ())
        lines = [
            "Frame By Plane — Effects Contract Audit",
            "========================================",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"Scene: {getattr(context.scene, 'name', '<none>')}",
            f"Repair requested: {'Yes' if self.repair else 'No'}",
            "",
            "Summary",
            "-------",
        ]
        lines.extend(
            f"{key.replace('_', ' ').title()}: {value}"
            for key, value in stats.items()
        )
        lines.extend(("", "Structural issues", "-----------------"))
        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- None")
        lines.extend(("", "Warnings", "--------"))
        lines.extend(f"- {item}" for item in warnings) if warnings else lines.append("- None")
        lines.extend(("", "Result", "------"))
        lines.append("PASS" if not issues else "REVIEW REQUIRED")
        summary = f"Effects Contract · {len(issues)} issue(s) · {len(warnings)} warning(s)"
        write_diagnostic_report(
            context.scene,
            "FBP_Effects_Contract_Audit",
            lines,
            summary=summary,
            status="PASS" if not issues else "WARNING",
        )
        self.report({'INFO'} if not issues else {'WARNING'}, summary)
        return {'FINISHED'}


class FBP_OT_RunMaskInteractionAudit(Operator):
    bl_idname = "fbp.run_mask_interaction_audit"
    bl_label = "Run Mask Interaction Audit"
    bl_description = "Validate Shape Masks, clipping and matte sources, imported mask files and per-effect mask routing"

    repair: BoolProperty(
        name="Repair Safe Issues",
        description="Repair helper contracts, clear invalid source pointers, restore local-mask routing and resynchronize clipping masks without deleting user media",
        default=False,
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=480)

    def execute(self, context):
        sync_layer_collection(context)
        rigs = [obj for obj in context.scene.objects if is_fbp_layer_object(obj)]
        result = _fbp_mask_interaction_contract_audit(
            rigs, context.scene, repair=self.repair, context=context
        )
        stats = dict(result.get("stats", {}) or {})
        issues = list(result.get("issues", ()) or ())
        warnings = list(result.get("warnings", ()) or ())
        lines = [
            "Frame By Plane — Mask Interaction Audit",
            "=======================================",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"Scene: {getattr(context.scene, 'name', '<none>')}",
            f"Repair requested: {'Yes' if self.repair else 'No'}",
            "",
            "Summary",
            "-------",
        ]
        lines.extend(
            f"{key.replace('_', ' ').title()}: {value}"
            for key, value in stats.items()
        )
        lines.extend(("", "Structural issues", "-----------------"))
        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- None")
        lines.extend(("", "Warnings", "--------"))
        lines.extend(f"- {item}" for item in warnings) if warnings else lines.append("- None")
        lines.extend(("", "Validation totals", "-----------------"))
        lines.append(f"Structural issues: {len(issues)}")
        lines.append(f"Warnings: {len(warnings)}")
        lines.extend(("", "Result", "------"))
        lines.append("PASS" if not issues else "REVIEW REQUIRED")
        summary = f"Mask Interaction · {len(issues)} issue(s) · {len(warnings)} warning(s)"
        write_diagnostic_report(
            context.scene,
            "FBP_Mask_Interaction_Audit",
            lines,
            summary=summary,
            status="PASS" if not issues else "WARNING",
        )
        self.report({'INFO'} if not issues else {'WARNING'}, summary)
        return {'FINISHED'}


class FBP_OT_RunRenderContractAudit(Operator):
    bl_idname = "fbp.run_render_contract_audit"
    bl_label = "Run Render Contract Audit"
    bl_description = "Probe render-only effect visibility, temporary quality overrides, restoration and generated helper render safety"

    repair: BoolProperty(
        name="Repair Safe Issues",
        description="Disable rendering on generated mask and Lattice helpers while leaving layer visibility and artistic render choices unchanged",
        default=False,
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=480)

    def execute(self, context):
        sync_layer_collection(context)
        rigs = [obj for obj in context.scene.objects if is_fbp_layer_object(obj)]
        result = _fbp_render_contract_audit(
            rigs, context.scene, repair=self.repair
        )
        stats = dict(result.get("stats", {}) or {})
        issues = list(result.get("issues", ()) or ())
        warnings = list(result.get("warnings", ()) or ())
        lines = [
            "Frame By Plane — Render Contract Audit",
            "======================================",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"Scene: {getattr(context.scene, 'name', '<none>')}",
            f"Repair requested: {'Yes' if self.repair else 'No'}",
            "",
            "Summary",
            "-------",
        ]
        lines.extend(
            f"{key.replace('_', ' ').title()}: {value}"
            for key, value in stats.items()
        )
        lines.extend(("", "Structural issues", "-----------------"))
        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- None")
        lines.extend(("", "Warnings", "--------"))
        lines.extend(f"- {item}" for item in warnings) if warnings else lines.append("- None")
        lines.extend(("", "Validation totals", "-----------------"))
        lines.append(f"Structural issues: {len(issues)}")
        lines.append(f"Warnings: {len(warnings)}")
        lines.extend(("", "Result", "------"))
        lines.append("PASS" if not issues else "REVIEW REQUIRED")
        summary = f"Render Contract · {len(issues)} issue(s) · {len(warnings)} warning(s)"
        write_diagnostic_report(
            context.scene,
            "FBP_Render_Contract_Audit",
            lines,
            summary=summary,
            status="PASS" if not issues else "WARNING",
        )
        self.report({'INFO'} if not issues else {'WARNING'}, summary)
        return {'FINISHED'}


class FBP_OT_DeepAddonAudit(Operator):
    bl_idname = "fbp.deep_addon_audit"
    bl_label = "Run Deep Add-on Audit"
    bl_description = "Validate effects, masks, native media, lifecycle services, scene ownership and generated datablocks"

    repair: BoolProperty(
        name="Repair Safe Issues",
        description="Reapply effect contracts and camera bindings without deleting user datablocks",
        default=False,
    )

    def execute(self, context):
        scene = context.scene
        sync_layer_collection(context)
        rigs = [obj for obj in scene.objects if is_fbp_layer_object(obj)]
        issues = list(FBP_EFFECT_REGISTRY_ISSUES)
        warnings = []
        stats = {
            "rigs": len(rigs), "effects": 0, "geometry": 0, "shader": 0,
            "missing_modifiers": 0, "missing_groups": 0, "duplicate_modifiers": 0,
            "duplicate_instance_ids": 0, "camera_unbound": 0,
            "orphan_groups": 0, "orphan_materials": 0,
            "unsupported_native_contracts": 0,
            "native_contract_failures": 0,
            "native_duration_mismatch": 0, "native_timing_drivers": 0,
            "native_timing_self_checks": 0, "native_timing_self_failures": 0,
            "duplicate_file_wrappers": 0,
            "lattice_effects": 0, "lattice_failures": 0, "lattice_warnings": 0,
            "repaired": 0,
        }
        instance_owners = {}

        timing_self_test = fbp_native_timing_self_test()
        stats["native_timing_self_checks"] = int(timing_self_test.get("checks", 0) or 0)
        timing_self_issues = list(timing_self_test.get("issues", ()) or ())
        stats["native_timing_self_failures"] = len(timing_self_issues)
        issues.extend(f"Native timing self-test: {message}" for message in timing_self_issues)

        lifecycle_result = lifecycle_audit(scene, repair=self.repair)
        lifecycle_stats = dict(lifecycle_result.get("stats", {}) or {})
        stats.update(lifecycle_stats)
        stats["repaired"] += int(lifecycle_result.get("repaired", 0) or 0)
        issues.extend(lifecycle_result.get("issues", ()) or ())
        warnings.extend(lifecycle_result.get("warnings", ()) or ())

        effect_stack_result = _fbp_effect_stack_contract_audit(
            rigs, repair=self.repair
        )
        stats.update(dict(effect_stack_result.get("stats", {}) or {}))
        stats["repaired"] += int(effect_stack_result.get("repaired", 0) or 0)
        issues.extend(effect_stack_result.get("issues", ()) or ())
        warnings.extend(effect_stack_result.get("warnings", ()) or ())

        if self.repair:
            for rig in rigs:
                try:
                    if fbp_refresh_effect_instance_ids(rig):
                        stats["repaired"] += 1
                except FBP_DATA_ERRORS as exc:
                    issues.append(
                        f"{getattr(rig, 'name', '<rig>')}: instance identity repair failed: {exc}"
                    )

        for rig in rigs:
            rig_name = getattr(rig, "name", "<unnamed rig>")
            plane = getattr(rig, "fbp_plane_target", None)
            if plane is None:
                issues.append(f"{rig_name}: missing linked plane")
                continue
            if not bool(getattr(rig, "fbp_is_color_plane", False)):
                native_issues = fbp_native_rig_contract_issues(rig)
                if native_issues:
                    stats["native_contract_failures"] += 1
                    if any("Image/ImageUser/F-Curve contract" in message for message in native_issues):
                        stats["native_duration_mismatch"] += 1
                    issues.extend(
                        f"{rig_name}: {message}" for message in native_issues
                    )
            effect_ids = tuple(fbp_effect_ids_for_rig(rig))
            stats["effects"] += len(effect_ids)
            lattice_result = fbp_lattice_contract_report(rig, repair=self.repair)
            if bool(lattice_result.get("active", False)):
                stats["lattice_effects"] += 1
                stats["repaired"] += int(lattice_result.get("repaired", 0) or 0)
                lattice_issues = tuple(lattice_result.get("issues", ()) or ())
                lattice_warnings = tuple(lattice_result.get("warnings", ()) or ())
                stats["lattice_failures"] += len(lattice_issues)
                stats["lattice_warnings"] += len(lattice_warnings)
                issues.extend(f"{rig_name}: Lattice: {message}" for message in lattice_issues)
                warnings.extend(f"{rig_name}: Lattice: {message}" for message in lattice_warnings)
            for effect_id in effect_ids:
                definition = fbp_effect_definition(effect_id)
                kind = str(definition.get("kind", ""))
                if kind == "GEOMETRY":
                    stats["geometry"] += 1
                    modifier = fbp_find_effect_modifier(rig, effect_id)
                    if modifier is None:
                        stats["missing_modifiers"] += 1
                        issues.append(f"{rig_name}: {effect_id} is active but its modifier is missing")
                        continue
                    node_group = getattr(modifier, "node_group", None)
                    if node_group is None:
                        stats["missing_groups"] += 1
                        issues.append(f"{rig_name}: {effect_id} modifier has no node group")
                    instance_id = str(
                        fbp_effect_instance_id_for_rig(
                            rig, effect_id, ensure=False
                        ) or ""
                    )
                    if not instance_id:
                        warnings.append(f"{rig_name}: {effect_id} has no persistent instance id")
                    else:
                        instance_owners.setdefault(instance_id, []).append(f"{rig_name}/{effect_id}")
                    matches = []
                    try:
                        for candidate in plane.modifiers:
                            if getattr(candidate, "type", "") != "NODES":
                                continue
                            tagged = str(candidate.get("fbp_effect_id", "") or "")
                            if tagged == effect_id:
                                matches.append(candidate)
                    except FBP_DATA_ERRORS:
                        pass
                    if len(matches) > 1:
                        stats["duplicate_modifiers"] += len(matches) - 1
                        issues.append(f"{rig_name}: {effect_id} has {len(matches)} tagged modifiers")
                    if definition.get("camera_aware"):
                        camera = getattr(scene, "camera", None)
                        if camera is None:
                            stats["camera_unbound"] += 1
                            warnings.append(f"{rig_name}: {effect_id} has no active scene camera")
                elif kind == "SHADER":
                    stats["shader"] += 1
                    instance_id = str(
                        fbp_effect_instance_id_for_rig(
                            rig, effect_id, ensure=False
                        ) or ""
                    )
                    if not instance_id:
                        warnings.append(
                            f"{rig_name}: {effect_id} has no persistent instance id"
                        )
                    else:
                        instance_owners.setdefault(instance_id, []).append(
                            f"{rig_name}/{effect_id}"
                        )

        for instance_id, owners in sorted(instance_owners.items()):
            if len(owners) > 1:
                stats["duplicate_instance_ids"] += len(owners) - 1
                issues.append(f"Duplicate effect instance id {instance_id}: {', '.join(owners)}")

        # Treat masks as one interaction matrix: editable Shape Mask helpers,
        # source-layer track mattes, imported mask files and per-effect routing
        # can each be valid alone while their relationship is broken.
        mask_result = _fbp_mask_interaction_contract_audit(
            rigs, scene, repair=self.repair, context=context
        )
        stats.update(dict(mask_result.get("stats", {}) or {}))
        stats["repaired"] += int(mask_result.get("repaired", 0) or 0)
        issues.extend(mask_result.get("issues", ()) or ())
        warnings.extend(mask_result.get("warnings", ()) or ())

        render_result = _fbp_render_contract_audit(
            rigs, scene, repair=self.repair
        )
        stats.update(dict(render_result.get("stats", {}) or {}))
        stats["repaired"] += int(render_result.get("repaired", 0) or 0)
        issues.extend(render_result.get("issues", ()) or ())
        warnings.extend(render_result.get("warnings", ()) or ())

        if self.repair:
            repaired_controls = audit_effect_controls(scene, repair=True, context=context)
            control_result = audit_effect_controls(scene, repair=False, context=context)
            stats["repaired"] += int(repaired_controls.get("repaired", 0) or 0)
            control_stats = dict(control_result.get("stats", {}) or {})
            control_stats["control_repairs"] = int(
                repaired_controls.get("repaired", 0) or 0
            )
        else:
            control_result = audit_effect_controls(scene, repair=False, context=context)
            control_stats = dict(control_result.get("stats", {}) or {})
        stats.update(control_stats)
        issues.extend(control_result.get("issues", ()) or ())
        warnings.extend(control_result.get("warnings", ()) or ())

        cache_repair = fbp_native_media_cache_report(repair=self.repair)
        if self.repair:
            stats["repaired"] += int(cache_repair.get("repaired", 0) or 0)
            cache_result = fbp_native_media_cache_report(repair=False)
        else:
            cache_result = cache_repair
        stats.update(dict(cache_result.get("stats", {}) or {}))
        issues.extend(cache_result.get("issues", ()) or ())
        warnings.extend(cache_result.get("warnings", ()) or ())

        for group in bpy.data.node_groups:
            try:
                private = bool(group.get("fbp_private_effect_group", False))
                generated = bool(group.get("fbp_generated_effect_group", False)) or private
                if generated and group.users == 0:
                    stats["orphan_groups"] += 1
                    warnings.append(f"Unused generated node group: {group.name}")
            except FBP_DATA_ERRORS:
                continue
        for material in bpy.data.materials:
            try:
                generated = bool(material.get("fbp_generated_effect_material", False)) or bool(material.get("fbp_effect_material", False))
                if generated and material.users == 0:
                    stats["orphan_materials"] += 1
                    warnings.append(f"Unused generated material: {material.name}")
                if bool(material.get("fbp_native_sequence", False)):
                    contract_revision = int(material.get("fbp_native_render_contract", 0) or 0)
                    if contract_revision != FBP_NATIVE_RENDER_CONTRACT_REVISION:
                        stats["unsupported_native_contracts"] += 1
                        issues.append(
                            f"Unsupported native render contract: {material.name} "
                            f"({contract_revision}; rebuild this layer with {FBP_NATIVE_RENDER_CONTRACT_REVISION})"
                        )
                    for node in getattr(getattr(material, "node_tree", None), "nodes", ()) or ():
                        if not bool(node.get("fbp_native_sequence_node", False)):
                            continue
                        image = getattr(node, "image", None)
                        if image is None or str(getattr(image, "source", "FILE") or "FILE") not in {"SEQUENCE", "MOVIE"}:
                            continue
                        image_user = getattr(node, "image_user", None)
                        try:
                            data_path = image_user.path_from_id("frame_offset") if image_user else ""
                            animation_data = getattr(material.node_tree, "animation_data", None)
                            if any(
                                str(getattr(curve, "data_path", "") or "") == data_path
                                for curve in (getattr(animation_data, "drivers", ()) or ())
                            ):
                                stats["native_timing_drivers"] += 1
                                warnings.append(
                                    f"Unsupported scripted native timing driver: {material.name}"
                                )
                        except FBP_DATA_ERRORS:
                            pass
            except FBP_DATA_ERRORS:
                continue

        native_paths = {}
        for image in bpy.data.images:
            try:
                path = os.path.normcase(os.path.abspath(bpy.path.abspath(str(getattr(image, "filepath", "") or ""))))
                source = str(getattr(image, "source", "FILE") or "FILE")
                if path:
                    native_paths.setdefault(path, {}).setdefault(source, []).append(image)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
                continue
        for path, by_source in native_paths.items():
            if by_source.get("SEQUENCE") and by_source.get("FILE"):
                unused_files = [image for image in by_source["FILE"] if int(getattr(image, "users", 0) or 0) == 0]
                if unused_files:
                    stats["duplicate_file_wrappers"] += len(unused_files)
                    warnings.append(
                        f"Unused FILE wrapper beside native sequence: {path} "
                        f"({len(unused_files)} datablock(s); purge manually when safe)"
                    )

        if self.repair:
            for rig in rigs:
                try:
                    if fbp_reapply_all_effects(rig):
                        stats["repaired"] += 1
                except FBP_DATA_ERRORS as exc:
                    issues.append(f"{getattr(rig, 'name', '<rig>')}: repair failed: {exc}")
            try:
                fbp_sync_scene_camera_bindings(scene, force=True)
            except FBP_DATA_ERRORS as exc:
                issues.append(f"Camera binding repair failed: {exc}")

        lines = [
            "Frame By Plane — Deep Add-on Audit",
            "===================================",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"Scene: {scene.name}",
            f"Repair requested: {'Yes' if self.repair else 'No'}",
            "",
            "Summary",
            "-------",
        ]
        lines.extend(f"{key.replace('_', ' ').title()}: {value}" for key, value in stats.items())
        lines.extend(("", "Errors / structural issues", "--------------------------"))
        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- None")
        lines.extend(("", "Warnings", "--------"))
        lines.extend(f"- {item}" for item in warnings) if warnings else lines.append("- None")
        lines.extend(("", "Validation totals", "-----------------"))
        lines.append(f"Structural issues: {len(issues)}")
        lines.append(f"Warnings: {len(warnings)}")
        lines.extend(("", "Result", "------"))
        lines.append("PASS" if not issues else "REVIEW REQUIRED")

        summary = f"Deep Audit · {len(issues)} issue(s) · {len(warnings)} warning(s)"
        write_diagnostic_report(
            scene, "FBP_Deep_Addon_Audit", lines,
            summary=summary, status="PASS" if not issues else "WARNING",
        )
        level = {'INFO'} if not issues else {'WARNING'}
        self.report(level, summary)
        return {'FINISHED'}

class FBP_OT_RunLifecycleAudit(Operator):
    bl_idname = "fbp.run_lifecycle_audit"
    bl_label = "Run Lifecycle Audit"
    bl_description = "Validate handler, timer, deferred-task, Undo/render guard and rig-plane ownership state"

    repair: BoolProperty(
        name="Repair Safe Issues",
        description="Idempotently rebuild lifecycle services, release stale guards and refresh transient effect lists while Blender is idle",
        default=False,
    )

    def execute(self, context):
        result = lifecycle_audit(context.scene, repair=self.repair)
        stats = dict(result.get("stats", {}) or {})
        issues = list(result.get("issues", ()) or ())
        warnings = list(result.get("warnings", ()) or ())
        lines = [
            "Frame By Plane — Lifecycle Audit",
            "================================",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"Scene: {getattr(context.scene, 'name', '<none>')}",
            f"Repair requested: {'Yes' if self.repair else 'No'}",
            "",
            "Summary",
            "-------",
        ]
        lines.extend(f"{key.replace('_', ' ').title()}: {value}" for key, value in stats.items())
        lines.extend(("", "Errors / structural issues", "--------------------------"))
        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- None")
        lines.extend(("", "Warnings", "--------"))
        lines.extend(f"- {item}" for item in warnings) if warnings else lines.append("- None")
        lines.extend(("", "Validation totals", "-----------------"))
        lines.append(f"Structural issues: {len(issues)}")
        lines.append(f"Warnings: {len(warnings)}")
        lines.extend(("", "Result", "------"))
        lines.append("PASS" if not issues else "REVIEW REQUIRED")
        summary = f"Lifecycle · {len(issues)} issue(s) · {len(warnings)} warning(s)"
        write_diagnostic_report(
            context.scene, "FBP_Lifecycle_Audit", lines,
            summary=summary, status="PASS" if not issues else "WARNING",
        )
        self.report({'INFO'} if not issues else {'WARNING'}, summary)
        return {'FINISHED'}


class FBP_OT_RunReleaseGate(Operator):
    bl_idname = "fbp.run_release_gate"
    bl_label = "Run Release Gate"
    bl_description = "Run lifecycle, native backend, effects, masks, render contracts, optional rendered-image parity, persistence, Undo/Redo and Deep Add-on audits"

    require_native_layers: BoolProperty(
        name="Require Native Layers",
        description="Fail when the current Scene contains no native Image, Sequence or Movie layer",
        default=True,
    )
    require_zero_warnings: BoolProperty(
        name="Require Zero Warnings",
        description="Treat audit warnings as release blockers for the regression project",
        default=True,
    )
    require_persistence_verification: BoolProperty(
        name="Require Save / Reopen Verification",
        description="Require a captured persistence baseline that has been verified after the .blend was reopened",
        default=True,
    )
    require_undo_redo_verification: BoolProperty(
        name="Require Undo / Redo Verification",
        description="Require a process-local endurance baseline verified after at least one real Undo and one real Redo",
        default=False,
    )
    require_render_parity_verification: BoolProperty(
        name="Require Eevee / Cycles Parity",
        description="Require a current PASS from the rendered-image parity audit. The result becomes stale when the Scene frame, camera, layer transforms or effect stack changes",
        default=False,
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=460)

    def execute(self, context):
        failures = []
        native_rigs = [
            obj for obj in context.scene.objects
            if is_fbp_layer_object(obj)
            and fbp_layer_backend_type(obj) in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE'}
        ]
        # A complete per-layer timeline probe intentionally switches frames many
        # times. Running it on the all-effects stress scene multiplies heavy GN
        # evaluation by every layer and can turn a release check into a minutes-
        # long stall. The dedicated Native Regression scene always receives the
        # full probe; large production/effects scenes receive contract checks and
        # the deterministic playback self-test instead.
        full_timeline_probe = bool(
            context.scene.get("fbp_native_regression_scene", False)
        ) or len(native_rigs) <= 12

        lifecycle_result = bpy.ops.fbp.run_lifecycle_audit(repair=False)
        lifecycle_text = bpy.data.texts.get("FBP_Lifecycle_Audit")
        lifecycle_report = lifecycle_text.as_string() if lifecycle_text else ""
        if "FINISHED" not in lifecycle_result or "Structural issues: 0" not in lifecycle_report:
            failures.append("Lifecycle Audit did not pass")

        native_result = bpy.ops.fbp.run_native_backend_regression(
            repair=False, probe_timeline=full_timeline_probe
        )
        native_text = bpy.data.texts.get("FBP_Native_Backend_Regression")
        native_report = native_text.as_string() if native_text else ""
        if "FINISHED" not in native_result or "REVIEW REQUIRED" in native_report:
            failures.append("Native Backend Regression did not pass")
        if self.require_native_layers and "Native layers: 0" in native_report:
            failures.append("The current Scene contains no native media layers")

        effects_result = bpy.ops.fbp.run_effects_contract_audit(repair=False)
        effects_text = bpy.data.texts.get("FBP_Effects_Contract_Audit")
        effects_report = effects_text.as_string() if effects_text else ""
        if "FINISHED" not in effects_result or "REVIEW REQUIRED" in effects_report:
            failures.append("Effects Contract Audit did not pass")
        if self.require_zero_warnings and "Effect Stack Order Warnings: 0" not in effects_report:
            failures.append("Effects Contract Audit contains order warnings")
        if self.require_zero_warnings and "Effect Stack Metadata Warnings: 0" not in effects_report:
            failures.append("Effects Contract Audit contains metadata warnings")

        mask_result = bpy.ops.fbp.run_mask_interaction_audit(repair=False)
        mask_text = bpy.data.texts.get("FBP_Mask_Interaction_Audit")
        mask_report = mask_text.as_string() if mask_text else ""
        if "FINISHED" not in mask_result or "Structural issues: 0" not in mask_report:
            failures.append("Mask Interaction Audit did not pass")
        if self.require_zero_warnings and "Warnings: 0" not in mask_report:
            failures.append("Mask Interaction Audit contains warnings")

        render_result = bpy.ops.fbp.run_render_contract_audit(repair=False)
        render_text = bpy.data.texts.get("FBP_Render_Contract_Audit")
        render_report = render_text.as_string() if render_text else ""
        if "FINISHED" not in render_result or "Structural issues: 0" not in render_report:
            failures.append("Render Contract Audit did not pass")
        if self.require_zero_warnings and "Warnings: 0" not in render_report:
            failures.append("Render Contract Audit contains warnings")

        parity_state = fbp_render_parity_status(
            context.scene, check_stale=self.require_render_parity_verification
        )
        parity_status = str(parity_state.get("status", "NOT_RUN") or "NOT_RUN")
        parity_stale = bool(parity_state.get("stale", False))
        if self.require_render_parity_verification:
            if parity_status != "PASS":
                failures.append("Eevee/Cycles rendered-image parity has not passed")
            elif parity_stale:
                failures.append("Eevee/Cycles rendered-image parity result is stale")

        persistence_report = ""
        if self.require_persistence_verification:
            persistence_result = bpy.ops.fbp.run_persistence_audit(
                action='VERIFY', require_reopen=True
            )
            persistence_text = bpy.data.texts.get("FBP_Persistence_Audit")
            persistence_report = persistence_text.as_string() if persistence_text else ""
            if (
                "FINISHED" not in persistence_result
                or "Structural issues: 0" not in persistence_report
                or "Reopen confirmed: Yes" not in persistence_report
            ):
                failures.append("Persistence save/reopen verification did not pass")

        endurance_report = ""
        if self.require_undo_redo_verification:
            endurance_result = bpy.ops.fbp.run_undo_endurance_audit(
                action='VERIFY', minimum_undo_events=1, minimum_redo_events=1
            )
            endurance_text = bpy.data.texts.get("FBP_Undo_Redo_Endurance")
            endurance_report = endurance_text.as_string() if endurance_text else ""
            if (
                "FINISHED" not in endurance_result
                or "Structural issues: 0" not in endurance_report
            ):
                failures.append("Undo/Redo endurance verification did not pass")

        deep_result = bpy.ops.fbp.deep_addon_audit(repair=False)
        deep_text = bpy.data.texts.get("FBP_Deep_Addon_Audit")
        deep_report = deep_text.as_string() if deep_text else ""
        if "FINISHED" not in deep_result or "Structural issues: 0" not in deep_report:
            failures.append("Deep Add-on Audit did not pass")
        if self.require_zero_warnings and "Warnings: 0" not in deep_report:
            failures.append("Deep Add-on Audit contains warnings")

        lines = [
            "Frame By Plane — Release Gate",
            "=================================",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"Scene: {getattr(context.scene, 'name', '<none>')}",
            f"Require native layers: {'Yes' if self.require_native_layers else 'No'}",
            f"Require zero warnings: {'Yes' if self.require_zero_warnings else 'No'}",
            f"Require save/reopen verification: {'Yes' if self.require_persistence_verification else 'No'}",
            f"Require Undo/Redo verification: {'Yes' if self.require_undo_redo_verification else 'No'}",
            f"Require Eevee/Cycles parity: {'Yes' if self.require_render_parity_verification else 'No'}",
            f"Full native timeline probe: {'Yes' if full_timeline_probe else 'No · dedicated Native Regression scene required'}",
            "",
            "Automated in-file gates",
            "-----------------------",
            f"Lifecycle Audit: {'PASS' if 'Structural issues: 0' in lifecycle_report else 'FAIL'}",
            f"Native Backend Regression: {'PASS' if 'REVIEW REQUIRED' not in native_report else 'FAIL'}",
            f"Effects Contract Audit: {'PASS' if 'REVIEW REQUIRED' not in effects_report else 'FAIL'}",
            f"Mask Interaction Audit: {'PASS' if 'Structural issues: 0' in mask_report else 'FAIL'}",
            f"Render Contract Audit: {'PASS' if 'Structural issues: 0' in render_report else 'FAIL'}",
            f"Eevee/Cycles Parity: {('NOT REQUIRED' if not self.require_render_parity_verification else ('PASS' if (parity_status == 'PASS' and not parity_stale) else 'FAIL'))}",
            f"Persistence Audit: {'PASS' if (not self.require_persistence_verification or ('Structural issues: 0' in persistence_report and 'Reopen confirmed: Yes' in persistence_report)) else 'FAIL'}",
            f"Undo/Redo Endurance: {'PASS' if (not self.require_undo_redo_verification or 'Structural issues: 0' in endurance_report) else 'FAIL'}",
            f"Deep Add-on Audit: {'PASS' if 'Structural issues: 0' in deep_report else 'FAIL'}",
            "",
            "External release matrix",
            "-----------------------",
            "- Undo/Redo uses a baseline-assisted interactive round trip when required above",
            "- Eevee/Cycles rendered-image parity is captured by Render Parity when required above",
            "- Enable/disable/reload and Windows/macOS/Linux installation tests remain platform-specific",
            "",
            "Failures",
            "--------",
        ]
        lines.extend(f"- {item}" for item in failures) if failures else lines.append("- None")
        lines.extend(("", "Result", "------"))
        lines.append("PASS" if not failures else "REVIEW REQUIRED")
        summary = "Release Gate · PASS" if not failures else f"Release Gate · {len(failures)} blocker(s)"
        write_diagnostic_report(
            context.scene, "FBP_Release_Gate", lines,
            summary=summary, status="PASS" if not failures else "WARNING",
        )
        self.report({'INFO'} if not failures else {'WARNING'}, summary)
        return {'FINISHED'}


class FBP_OT_OpenLastDiagnosticReport(Operator):
    bl_idname = "fbp.open_last_diagnostic_report"
    bl_label = "Open Last Report"
    bl_description = "Open the most recently generated Frame By Plane diagnostic report in the current area"

    @classmethod
    def poll(cls, context):
        text, _summary, _status, _timestamp = last_diagnostic_report(getattr(context, "scene", None))
        return text is not None and getattr(context, "area", None) is not None

    def execute(self, context):
        text, summary, _status, _timestamp = last_diagnostic_report(context.scene)
        if text is None:
            self.report({'WARNING'}, "No diagnostic report is available yet")
            return {'CANCELLED'}
        area = getattr(context, "area", None)
        if area is None:
            self.report({'WARNING'}, "No editor area is available for the report")
            return {'CANCELLED'}
        try:
            area.type = 'TEXT_EDITOR'
            space = getattr(area.spaces, "active", None)
            if space is not None:
                space.text = text
                if hasattr(space, "show_word_wrap"):
                    space.show_word_wrap = True
            self.report({'INFO'}, summary or text.name)
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            self.report({'WARNING'}, f"Could not open report: {exc}")
            return {'CANCELLED'}


class FBP_OT_CopyLastDiagnosticReport(Operator):
    bl_idname = "fbp.copy_last_diagnostic_report"
    bl_label = "Copy Last Report"
    bl_description = "Copy the complete most recent Frame By Plane diagnostic report to the clipboard"

    @classmethod
    def poll(cls, context):
        text, _summary, _status, _timestamp = last_diagnostic_report(getattr(context, "scene", None))
        return text is not None

    def execute(self, context):
        text, summary, _status, _timestamp = last_diagnostic_report(context.scene)
        if text is None:
            self.report({'WARNING'}, "No diagnostic report is available yet")
            return {'CANCELLED'}
        try:
            context.window_manager.clipboard = text.as_string()
            self.report({'INFO'}, f"Copied: {summary or text.name}")
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            self.report({'WARNING'}, f"Could not copy report: {exc}")
            return {'CANCELLED'}


class FBP_OT_OpenDiagnosticReport(Operator):
    bl_idname = "fbp.open_diagnostic_report"
    bl_label = "Open Diagnostic Report"
    bl_description = "Open this specific Frame By Plane diagnostic report in the current area"

    report_name: StringProperty(
        name="Report",
        description="Internal Text datablock containing the diagnostic report",
        default="",
        options={'HIDDEN'},
    )

    def execute(self, context):
        report_name = str(self.report_name or "").strip()
        text = bpy.data.texts.get(report_name) if report_name else None
        if text is None:
            self.report({'WARNING'}, "This diagnostic report has not been generated yet")
            return {'CANCELLED'}
        area = getattr(context, "area", None)
        if area is None:
            self.report({'WARNING'}, "No editor area is available for the report")
            return {'CANCELLED'}
        try:
            area.type = 'TEXT_EDITOR'
            space = getattr(area.spaces, "active", None)
            if space is not None:
                space.text = text
                if hasattr(space, "show_word_wrap"):
                    space.show_word_wrap = True
            self.report({'INFO'}, report_name)
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            self.report({'WARNING'}, f"Could not open report: {exc}")
            return {'CANCELLED'}


class FBP_OT_CopyDiagnosticMessages(Operator):
    bl_idname = "fbp.copy_diagnostic_messages"
    bl_label = "Copy Diagnostic Messages"
    bl_description = "Copy only the actionable error and warning messages from this diagnostic report"

    report_name: StringProperty(
        name="Report",
        description="Internal Text datablock containing the diagnostic report",
        default="",
        options={'HIDDEN'},
    )
    full_report: BoolProperty(
        name="Full Report",
        description="Copy the complete report instead of only actionable messages",
        default=False,
        options={'HIDDEN'},
    )

    def execute(self, context):
        report_name = str(self.report_name or "").strip()
        text = bpy.data.texts.get(report_name) if report_name else None
        if text is None:
            self.report({'WARNING'}, "This diagnostic report has not been generated yet")
            return {'CANCELLED'}
        try:
            if self.full_report:
                payload = text.as_string()
            else:
                messages = diagnostic_report_messages(text)
                if not messages:
                    self.report({'INFO'}, "This report contains no error or warning messages")
                    return {'CANCELLED'}
                payload = "\n".join(f"- {message}" for message in messages)
            context.window_manager.clipboard = payload
            self.report({'INFO'}, f"Copied diagnostic messages from {report_name}")
            return {'FINISHED'}
        except FBP_DATA_ERRORS as exc:
            self.report({'WARNING'}, f"Could not copy diagnostic messages: {exc}")
            return {'CANCELLED'}


class FBP_OT_RelinkFromProjectRoot(Operator):
    bl_idname      = "fbp.relink_from_project_root"
    bl_label       = "Relink From Project Root"
    bl_description = "Relink missing images by searching inside the Project Folder"
    bl_options     = {'UNDO'}

    def execute(self, context):
        root = project_root_for_package(context)
        if not root or not os.path.isdir(root):
            self.report({'WARNING'}, "Set a valid Project Folder first")
            return {'CANCELLED'}
        relinked, ambiguous, still_missing = relink_missing_images_from_root(root, make_relative=True)
        msg = f"Relinked {relinked}; missing {len(still_missing)}; ambiguous {len(ambiguous)}"
        self.report({'INFO' if not still_missing else 'WARNING'}, msg)
        return {'FINISHED'}

class FBP_OT_SelectMissingLayers(Operator):
    bl_idname      = "fbp.select_missing_layers"
    bl_label       = "Select Missing Layers"
    bl_description = "Select Frame by Plane rigs that contain missing linked images"
    bl_options     = {'UNDO'}

    def execute(self, context):
        sync_layer_collection(context)
        bpy.ops.object.select_all(action='DESELECT')
        selected = 0
        skipped_hidden = 0
        active = None
        for rig in [obj for obj in context.scene.objects if getattr(obj, 'is_fbp_control', False)]:
            if not rig_has_missing_images(rig):
                continue
            if collection_is_hidden_in_view_layer(context, get_primary_fbp_collection(rig)):
                skipped_hidden += 1
                continue
            if not object_in_view_layer(rig, context):
                skipped_hidden += 1
                continue
            try:
                rig.select_set(True)
                active = rig
                selected += 1
            except Exception:
                skipped_hidden += 1
        if active:
            context.view_layer.objects.active = active
        level = 'WARNING' if skipped_hidden else 'INFO'
        self.report({level}, f"Selected {selected} missing layer(s); hidden/unavailable {skipped_hidden}")
        return {'FINISHED'} if selected or skipped_hidden else {'CANCELLED'}

class FBP_OT_SyncCollectionColors(Operator):
    bl_idname      = "fbp.sync_collection_colors"
    bl_label       = "Sync Collection Colors"
    bl_description = "Apply visible Collection color tags to Frame by Plane layer viewport colors"
    bl_options     = {'UNDO'}

    def execute(self, context):
        sync_collection_colors_to_rigs(context)
        self.report({'INFO'}, "Collection colors synced")
        return {'FINISHED'}

class FBP_OT_ApplyPreferencesToScene(Operator):
    bl_idname = "fbp.apply_preferences_to_scene"
    bl_label = "Apply Frame by Plane Preferences"
    bl_description = "Apply the configured Frame by Plane defaults to the current Scene"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from .properties import fbp_apply_preferences_to_scene
        if fbp_apply_preferences_to_scene(context.scene, force=True, context=context):
            self.report({'INFO'}, "Frame by Plane preferences applied to the current Scene")
            return {'FINISHED'}
        self.report({'WARNING'}, "Frame by Plane preferences are unavailable")
        return {'CANCELLED'}


def _fbp_process_rss_bytes():
    """Return the current Blender process working set where the OS exposes it."""
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = (
                    ('cb', wintypes.DWORD),
                    ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t),
                    ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t),
                    ('PeakPagefileUsage', ctypes.c_size_t),
                )

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            process = ctypes.windll.kernel32.GetCurrentProcess()
            success = ctypes.windll.psapi.GetProcessMemoryInfo(
                process, ctypes.byref(counters), counters.cb
            )
            return int(counters.WorkingSetSize) if success else 0

        statm = Path('/proc/self/statm')
        if statm.is_file():
            resident_pages = int(statm.read_text(encoding='utf-8').split()[1])
            return resident_pages * int(os.sysconf('SC_PAGE_SIZE'))

        import resource
        usage = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # macOS reports bytes; most other Unix platforms report KiB.
        return usage if os.uname().sysname == 'Darwin' else usage * 1024
    except (AttributeError, IndexError, OSError, RuntimeError, TypeError, ValueError):
        return 0


class FBP_OT_ProfileEffects(Operator):
    bl_idname = "fbp.profile_effects"
    bl_label = "Profile Effects"
    bl_description = "Measure real frame/depsgraph update time and Blender process memory for the current scene"

    samples: IntProperty(
        name="Samples",
        description="Number of measured frame switches after one warm-up pass",
        default=8,
        min=3,
        max=30,
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        scene = context.scene
        view_layer = context.view_layer
        original_frame = int(scene.frame_current)
        if original_frame < int(scene.frame_end):
            alternate_frame = original_frame + 1
        elif original_frame > int(scene.frame_start):
            alternate_frame = original_frame - 1
        else:
            alternate_frame = original_frame

        rigs = [obj for obj in scene.objects if is_fbp_layer_object(obj)]
        effect_ids = [effect_id for rig in rigs for effect_id in fbp_effect_ids_for_rig(rig)]
        heavy_effects = sum(
            1 for effect_id in effect_ids
            if str(fbp_effect_definition(effect_id).get('performance', '') or '').upper()
            in {'HEAVY', 'VERY_HEAVY'}
        )

        layer_sync_started = time.perf_counter_ns()
        sync_layer_collection(context)
        layer_sync_ms = (time.perf_counter_ns() - layer_sync_started) / 1_000_000.0

        effect_discovery_started = time.perf_counter_ns()
        discovered_effects = sum(len(fbp_effect_ids_for_rig(rig)) for rig in rigs)
        effect_discovery_ms = (time.perf_counter_ns() - effect_discovery_started) / 1_000_000.0

        ui_sync_ms = 0.0
        if rigs:
            ui_sync_started = time.perf_counter_ns()
            try:
                fbp_sync_effect_items(
                    rigs[0], [rigs[0]], repair_assets=False,
                    normalize_instance_ids=False,
                )
            except FBP_DATA_ERRORS:
                pass
            ui_sync_ms = (time.perf_counter_ns() - ui_sync_started) / 1_000_000.0

        runtime_diagnostics_before = fbp_effect_runtime_diagnostics(scene)

        mask_runtime_started = time.perf_counter_ns()
        mask_runtime_updates = 0
        for rig in rigs:
            try:
                mask_runtime_updates += int(bool(sync_owner_object_mask_runtime(rig)))
            except FBP_DATA_ERRORS:
                pass
        mask_runtime_ms = (time.perf_counter_ns() - mask_runtime_started) / 1_000_000.0

        gc.collect()
        memory_before = _fbp_process_rss_bytes()
        measurements = []
        try:
            # Warm up lazy node compilation and image evaluation before timing.
            scene.frame_set(alternate_frame)
            view_layer.update()
            scene.frame_set(original_frame)
            view_layer.update()

            for index in range(int(self.samples)):
                target_frame = alternate_frame if index % 2 == 0 else original_frame
                started = time.perf_counter_ns()
                scene.frame_set(target_frame)
                view_layer.update()
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
                measurements.append(elapsed_ms)
        except FBP_DATA_ERRORS as exc:
            self.report({'ERROR'}, f"Effects profiler failed: {exc}")
            return {'CANCELLED'}
        finally:
            try:
                scene.frame_set(original_frame)
                view_layer.update()
            except FBP_DATA_ERRORS:
                pass

        gc.collect()
        memory_after = _fbp_process_rss_bytes()
        if not measurements:
            self.report({'ERROR'}, "Effects profiler produced no timing samples")
            return {'CANCELLED'}

        average_ms = statistics.fmean(measurements)
        median_ms = statistics.median(measurements)
        minimum_ms = min(measurements)
        maximum_ms = max(measurements)
        rss_mb = memory_after / (1024.0 * 1024.0) if memory_after else 0.0
        delta_mb = (
            (memory_after - memory_before) / (1024.0 * 1024.0)
            if memory_before and memory_after else 0.0
        )
        measured_at = datetime.now().isoformat(timespec='seconds')
        runtime_diagnostics_after = fbp_effect_runtime_diagnostics(scene)
        try:
            from .safe_tasks import scheduled_task_count
            pending_safe_tasks = int(scheduled_task_count())
        except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
            pending_safe_tasks = 0

        scene['fbp_effect_profile_timestamp'] = measured_at
        scene['fbp_effect_profile_samples'] = int(len(measurements))
        scene['fbp_effect_profile_avg_ms'] = float(average_ms)
        scene['fbp_effect_profile_median_ms'] = float(median_ms)
        scene['fbp_effect_profile_min_ms'] = float(minimum_ms)
        scene['fbp_effect_profile_max_ms'] = float(maximum_ms)
        scene['fbp_effect_profile_rss_mb'] = float(rss_mb)
        scene['fbp_effect_profile_delta_mb'] = float(delta_mb)
        scene['fbp_effect_profile_layer_sync_ms'] = float(layer_sync_ms)
        scene['fbp_effect_profile_discovery_ms'] = float(effect_discovery_ms)
        scene['fbp_effect_profile_ui_sync_ms'] = float(ui_sync_ms)
        scene['fbp_effect_profile_mask_runtime_ms'] = float(mask_runtime_ms)
        scene['fbp_effect_profile_frame_sync_rigs'] = int(
            runtime_diagnostics_after.get('geometry_source_sync_rigs', 0)
            + runtime_diagnostics_after.get('shader_source_sync_rigs', 0)
        )
        scene['fbp_effect_profile_held_step_skips'] = int(
            runtime_diagnostics_after.get('held_step_skips', 0)
            - runtime_diagnostics_before.get('held_step_skips', 0)
        )

        lines = [
            "Frame by Plane Effects Profiler",
            "================================",
            f"Measured: {measured_at}",
            f"Scene: {scene.name}",
            f"Frame pair: {original_frame} / {alternate_frame}",
            f"Samples: {len(measurements)} (plus warm-up)",
            f"FBP layers: {len(rigs)}",
            f"Effect instances: {len(effect_ids)}",
            f"Heavy effect instances: {heavy_effects}",
            f"Discovered effect instances: {discovered_effects}",
            "",
            "UI and runtime synchronization:",
            f"- Layer List synchronization: {layer_sync_ms:.3f} ms",
            f"- Effect discovery: {effect_discovery_ms:.3f} ms",
            f"- Active Effects UI mirror: {ui_sync_ms:.3f} ms",
            f"- Shape Mask runtime pass: {mask_runtime_ms:.3f} ms ({mask_runtime_updates} update(s))",
            f"- Effect rigs requiring Geometry source sync: {runtime_diagnostics_after.get('geometry_source_sync_rigs', 0)}",
            f"- Effect rigs requiring Shader source sync: {runtime_diagnostics_after.get('shader_source_sync_rigs', 0)}",
            f"- Animated effect contracts: {runtime_diagnostics_after.get('animated_effects', 0)}",
            f"- Active Evolution contracts: {runtime_diagnostics_after.get('evolve_effects', 0)}",
            f"- Held Evolution updates skipped during profile: {max(0, runtime_diagnostics_after.get('held_step_skips', 0) - runtime_diagnostics_before.get('held_step_skips', 0))}",
            f"- Pending safe tasks after profile: {pending_safe_tasks}",
            "",
            "Frame + depsgraph update timing:",
            f"- Average: {average_ms:.3f} ms",
            f"- Median: {median_ms:.3f} ms",
            f"- Minimum: {minimum_ms:.3f} ms",
            f"- Maximum: {maximum_ms:.3f} ms",
            "",
            "Blender process memory:",
            f"- Working set after profile: {rss_mb:.2f} MiB" if memory_after else "- Working set: unavailable on this platform",
            f"- Profile delta: {delta_mb:+.2f} MiB" if memory_before and memory_after else "- Profile delta: unavailable",
            "",
            "Per-sample timings:",
        ]
        lines.extend(f"- {index + 1:02d}: {value:.3f} ms" for index, value in enumerate(measurements))
        summary = f"Effects Profiler · {average_ms:.2f} ms average · {rss_mb:.1f} MiB"
        write_diagnostic_report(
            context.scene, "FBP_Effects_Profiler_Report", lines,
            summary=summary, status="INFO",
        )
        self.report({'INFO'}, summary)
        return {'FINISHED'}

class FBP_OT_RunNativeBackendRegression(Operator):
    bl_idname = "fbp.run_native_backend_regression"
    bl_label = "Run Native Backend Regression"
    bl_description = "Validate native playback math, media cache ownership, current layer contracts and representative evaluated timeline frames"
    bl_options = {'REGISTER', 'UNDO'}

    repair: BoolProperty(
        name="Repair Safe Issues",
        description="Refresh or transactionally rebuild native layers that fail their current render contract",
        default=False,
    )
    probe_timeline: BoolProperty(
        name="Probe Timeline",
        description="Evaluate representative frames for One Shot, Loop, Ping-Pong, variable-duration and transparent-row playback, then restore the current frame",
        default=True,
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=460)

    def execute(self, context):
        scene = context.scene
        sync_layer_collection(context)
        rigs = [
            obj for obj in scene.objects
            if is_fbp_layer_object(obj)
            and fbp_layer_backend_type(obj) in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE'}
        ]
        issues = []
        warnings = []
        repaired = 0
        probed = 0
        samples = 0

        timing = fbp_native_timing_self_test()
        issues.extend(
            f"Playback math: {message}"
            for message in (timing.get("issues", ()) or ())
        )

        cache_before = fbp_native_media_cache_report(repair=self.repair)
        repaired += int(cache_before.get("repaired", 0) or 0)
        cache = fbp_native_media_cache_report(repair=False) if self.repair else cache_before
        issues.extend(cache.get("issues", ()) or ())
        warnings.extend(cache.get("warnings", ()) or ())

        layer_lines = []
        for rig in rigs:
            name = str(getattr(rig, "name", "<rig>") or "<rig>")
            backend = fbp_layer_backend_type(rig)
            layer_issues = list(fbp_native_rig_contract_issues(rig, check_files=True))
            repaired_here = False
            if self.repair and layer_issues:
                try:
                    repaired_here = bool(fbp_refresh_native_sequence_from_rig(rig))
                    if not repaired_here:
                        repaired_here = bool(rebuild_native_sequence_from_rig(rig))
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError) as exc:
                    warnings.append(f"{name}: repair attempt failed: {exc}")
                if repaired_here:
                    repaired += 1
                    layer_issues = list(fbp_native_rig_contract_issues(rig, check_files=True))

            probe = {"issues": (), "samples": 0, "kind": backend}
            if self.probe_timeline and not layer_issues:
                probe = fbp_probe_native_rig_timing(rig, scene=scene)
                probed += 1
                samples += int(probe.get("samples", 0) or 0)
                layer_issues.extend(probe.get("issues", ()) or ())

            if layer_issues:
                issues.extend(f"{name}: {message}" for message in layer_issues)
                layer_lines.append(
                    f"- FAIL · {name} · {backend} · " + "; ".join(layer_issues[:4])
                )
            else:
                repair_label = " · repaired" if repaired_here else ""
                layer_lines.append(
                    f"- PASS · {name} · {backend} · {int(probe.get('samples', 0) or 0)} sample(s){repair_label}"
                )

        if not rigs:
            warnings.append("No native Image, Sequence or Movie layers were found in the current scene")

        cache_stats = dict(cache.get("stats", {}) or {})
        lines = [
            "Frame By Plane — Native Backend Regression",
            "==========================================",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"Scene: {scene.name}",
            f"Repair requested: {'Yes' if self.repair else 'No'}",
            f"Timeline probe: {'Yes' if self.probe_timeline else 'No'}",
            "",
            "Summary",
            "-------",
            f"Native layers: {len(rigs)}",
            f"Layers probed: {probed}",
            f"Timeline samples: {samples}",
            f"Playback math checks: {int(timing.get('checks', 0) or 0)}",
            f"Playback math failures: {len(timing.get('issues', ()) or ())}",
            f"Safe repairs: {repaired}",
        ]
        lines.extend(
            f"{key.replace('_', ' ').title()}: {value}"
            for key, value in cache_stats.items()
        )
        lines.extend(("", "Layers", "------"))
        lines.extend(layer_lines or ["- None"])
        lines.extend(("", "Structural issues", "-----------------"))
        lines.extend(f"- {message}" for message in issues) if issues else lines.append("- None")
        lines.extend(("", "Warnings", "--------"))
        lines.extend(f"- {message}" for message in warnings) if warnings else lines.append("- None")
        lines.extend(("", "Result", "------", "PASS" if not issues else "REVIEW REQUIRED"))

        summary = f"Native Backend · {len(issues)} issue(s) · {samples} timeline sample(s)"
        write_diagnostic_report(
            context.scene, "FBP_Native_Backend_Regression", lines,
            summary=summary, status="PASS" if not issues else "WARNING",
        )
        self.report({'INFO'} if not issues else {'WARNING'}, summary)
        return {'FINISHED'}


# SECTION - Effects Regression Scene #
def _fbp_write_regression_image(filepath, phase=0.0, width=128, height=72):
    """Write a deterministic alpha/color test pattern using Blender images."""
    image_name = f"FBP_Regression_Source_{phase:.2f}"
    image = bpy.data.images.get(image_name)
    if image is None or tuple(int(v) for v in image.size[:2]) != (width, height):
        image = bpy.data.images.new(
            image_name, width=width, height=height,
            alpha=True, float_buffer=False,
        )
    try:
        image["fbp_temporary"] = True
    except FBP_DATA_ERRORS:
        pass
    pixels = [0.0] * (width * height * 4)
    for y in range(height):
        v = y / max(1, height - 1)
        for x in range(width):
            u = x / max(1, width - 1)
            index = (y * width + x) * 4
            checker = 1.0 if ((x // 12 + y // 12 + int(phase * 3)) % 2 == 0) else 0.2
            pixels[index + 0] = max(0.0, min(1.0, u * 0.75 + phase * 0.25))
            pixels[index + 1] = max(0.0, min(1.0, v * 0.75 + checker * 0.25))
            pixels[index + 2] = max(0.0, min(1.0, (1.0 - u) * 0.55 + checker * 0.35))
            dx = (u - 0.5) / 0.48
            dy = (v - 0.5) / 0.48
            radius_sq = dx * dx + dy * dy
            if radius_sq <= 0.42:
                alpha = 1.0
            elif radius_sq <= 0.68:
                alpha = 0.50
            elif radius_sq <= 1.0:
                alpha = 0.15
            else:
                alpha = 0.0
            pixels[index + 3] = alpha
    try:
        image.pixels.foreach_set(pixels)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        image.pixels[:] = pixels
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.update()
    image.save()
    # Keep the generated datablock until Blender's explicit orphan purge. Removing
    # image buffers synchronously can race Blender 5.1's cache teardown.
    return str(path)


class FBP_OT_CreateNativeRegressionScene(Operator):
    bl_idname = "fbp.create_native_regression_scene"
    bl_label = "Create Native Regression Scene"
    bl_description = "Generate a separate scene covering static images, native playback modes, variable durations, reverse order, transparent rows, shared sources and long sequences"
    bl_options = {'REGISTER', 'UNDO'}

    replace_existing: BoolProperty(
        name="Replace Existing",
        description="Replace an existing FBP Native Regression scene",
        default=True,
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=440)

    def execute(self, context):
        window = getattr(context, "window", None)
        if window is None:
            self.report({'ERROR'}, "A Blender window is required to create the regression scene")
            return {'CANCELLED'}

        scene_name = "FBP Native Regression"
        old_scene = bpy.data.scenes.get(scene_name)
        if old_scene is not None and not self.replace_existing:
            self.report({'WARNING'}, "The FBP Native Regression scene already exists")
            return {'CANCELLED'}

        new_scene = bpy.data.scenes.new(scene_name + "__BUILD")
        window.scene = new_scene
        new_scene["fbp_regression_scene"] = True
        new_scene["fbp_native_regression_scene"] = True
        new_scene.frame_start = -20
        new_scene.frame_end = 120
        new_scene.frame_set(1)
        new_scene.render.resolution_x = 640
        new_scene.render.resolution_y = 360
        new_scene.render.resolution_percentage = 50
        try:
            new_scene.fbp_pre_duration = 2
            new_scene.fbp_pre_loop_mode = 'NONE'
            new_scene.fbp_pre_shadeless = True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

        root = bpy.data.collections.new("FBP Native Regression")
        root["fbp_regression_generated"] = True
        new_scene.collection.children.link(root)
        source_collection = bpy.data.collections.new("Native Playback Cases")
        source_collection["fbp_regression_generated"] = True
        root.children.link(source_collection)

        temp_root = Path(tempfile.gettempdir()) / "frame_by_plane_native_regression"
        generated_paths = []
        for index in range(12):
            size = (96, 96) if index == 6 else (128, 72)
            generated_paths.append(
                _fbp_write_regression_image(
                    temp_root / f"fbp_native_{100 + index:04d}.png",
                    phase=index / 11.0,
                    width=size[0],
                    height=size[1],
                )
            )
        directory = str(temp_root)
        filenames = [Path(value).name for value in generated_paths]

        built = []
        failures = []
        probe_samples = 0

        def build_case(name, source_files, rows, loop_mode, start_frame, location):
            try:
                rig = build_native_fbp_rig(
                    context, name, directory, source_files,
                    location, target_collection=source_collection,
                )
                rig["fbp_regression_generated"] = True
                plane = getattr(rig, "fbp_plane_target", None)
                if plane:
                    plane["fbp_regression_generated"] = True
                fbp_set_rna_property_silent(rig, "fbp_start_frame", int(start_frame))
                fbp_set_rna_property_silent(rig, "fbp_loop_mode", str(loop_mode))
                rig.fbp_images.clear()
                for label, filepath, duration, is_empty in rows:
                    item = rig.fbp_images.add()
                    item.name = str(label)
                    item.filepath = "" if is_empty else str(filepath)
                    item.is_empty = bool(is_empty)
                    item.is_selected = False
                    fbp_set_rna_property_silent(item, "duration", max(1, int(duration)))
                fbp_set_rna_property_silent(rig, "fbp_images_index", 0)
                if not fbp_refresh_native_sequence_from_rig(rig):
                    if not rebuild_native_sequence_from_rig(rig):
                        raise RuntimeError("native backend rebuild failed")
                contract = fbp_native_rig_contract_issues(rig, check_files=True)
                if contract:
                    raise RuntimeError("; ".join(contract[:4]))
                built.append(rig)
                return rig
            except Exception as exc:
                failures.append(f"{name}: {exc}")
                return None

        def normal_rows(selected, durations):
            return [
                (Path(generated_paths[index]).name, generated_paths[index], durations[position], False)
                for position, index in enumerate(selected)
            ]

        cases = [
            ("Static Image", [filenames[0]], normal_rows([0], [4]), 'NONE', 10),
            ("One Shot · Variable Holds", filenames[:5], normal_rows([0, 1, 2, 3, 4], [2, 3, 1, 4, 2]), 'NONE', 10),
            ("Loop · Variable Holds", filenames[:5], normal_rows([0, 1, 2, 3, 4], [1, 2, 3, 2, 1]), 'REPEAT', 14),
            ("Ping-Pong · Variable Holds", filenames[:5], normal_rows([0, 1, 2, 3, 4], [2, 1, 3, 1, 2]), 'PINGPONG', 18),
            ("Reverse Logical Order", filenames[:5], normal_rows([4, 3, 2, 1, 0], [1, 2, 1, 3, 2]), 'NONE', 22),
            (
                "Transparent Logical Row",
                filenames[:4],
                [
                    (filenames[0], generated_paths[0], 2, False),
                    ("Transparent Frame", "", 3, True),
                    (filenames[1], generated_paths[1], 1, False),
                    (filenames[2], generated_paths[2], 2, False),
                    (filenames[3], generated_paths[3], 1, False),
                ],
                'REPEAT', 26,
            ),
            ("Shared Source Duplicate", filenames[:5], normal_rows([0, 1, 2, 3, 4], [2, 2, 2, 2, 2]), 'REPEAT', 30),
            ("Long Sequence · 12 Frames", filenames, normal_rows(list(range(12)), [1] * 12), 'REPEAT', 34),
            ("Mixed Resolution Sequence", filenames[5:8], normal_rows([5, 6, 7], [2, 2, 2]), 'REPEAT', 38),
        ]

        columns = 3
        for index, (name, source_files, rows, loop_mode, start_frame) in enumerate(cases):
            x = (index % columns) * 5.0 - 5.0
            y = -(index // columns) * 3.2 + 3.2
            build_case(name, source_files, rows, loop_mode, start_frame, (x, y, 0.0))

        # Verify missing-path detection and recovery without touching files on disk.
        # This remains reliable on Windows where Blender may briefly retain a file
        # handle after loading an image sequence.
        missing_detection = False
        recovery_ok = False
        recovery_rig = next((rig for rig in built if getattr(rig, "name", "").startswith("One Shot")), None)
        if recovery_rig is not None and len(getattr(recovery_rig, "fbp_images", ())) > 2:
            test_item = recovery_rig.fbp_images[2]
            original_path = str(getattr(test_item, "filepath", "") or "")
            missing_path = str(temp_root / "fbp_native_missing_source.png")
            try:
                fbp_set_rna_property_silent(test_item, "filepath", missing_path)
                missing_detection = bool(fbp_native_rig_contract_issues(recovery_rig, check_files=True))
            finally:
                fbp_set_rna_property_silent(test_item, "filepath", original_path)
            if missing_detection:
                recovery_ok = not bool(fbp_native_rig_contract_issues(recovery_rig, check_files=True))
            if not missing_detection:
                failures.append("Missing-file detection: native contract did not report the missing logical row")
            elif not recovery_ok:
                failures.append("Missing-file recovery: contract remained invalid after restoring the logical row")

        for rig in built:
            probe = fbp_probe_native_rig_timing(rig, scene=new_scene)
            probe_samples += int(probe.get("samples", 0) or 0)
            for message in probe.get("issues", ()) or ():
                failures.append(f"{getattr(rig, 'name', '<rig>')}: {message}")

        # Building several sequence contracts may leave temporary FILE wrappers
        # created while reading dimensions. They are safe to remove here only
        # because this operator owns every generated source path and the wrappers
        # have no users. User images elsewhere in the .blend are never touched.
        generated_path_keys = {
            os.path.normcase(os.path.abspath(str(path)))
            for path in generated_paths
        }
        for image in tuple(bpy.data.images):
            try:
                path_key = os.path.normcase(
                    os.path.abspath(bpy.path.abspath(str(getattr(image, "filepath", "") or "")))
                )
                if (
                    path_key in generated_path_keys
                    and str(getattr(image, "source", "FILE") or "FILE") == "FILE"
                    and int(getattr(image, "users", 0) or 0) == 0
                ):
                    bpy.data.images.remove(image)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
                pass

        cache_report = fbp_native_media_cache_report(repair=False)
        failures.extend(cache_report.get("issues", ()) or ())

        camera_data = bpy.data.cameras.new("FBP Native Regression Camera")
        camera = bpy.data.objects.new("FBP Native Regression Camera", camera_data)
        root.objects.link(camera)
        camera["fbp_regression_generated"] = True
        camera.location = (0.0, 0.0, 35.0)
        camera_data.type = 'ORTHO'
        camera_data.ortho_scale = 22.0
        new_scene.camera = camera

        for obj in new_scene.objects:
            try:
                obj.select_set(False)
            except (AttributeError, RuntimeError):
                pass
        if built:
            try:
                built[0].select_set(True)
                context.view_layer.objects.active = built[0]
            except (AttributeError, RuntimeError):
                pass
        new_scene.frame_set(1)
        sync_layer_collection(context)

        lines = [
            "Frame By Plane — Native Regression Scene",
            "========================================",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"Native cases built: {len(built)}/{len(cases)}",
            f"Timeline samples: {probe_samples}",
            f"Missing-file detection: {'PASS' if missing_detection else 'FAIL'}",
            f"Missing-file recovery: {'PASS' if recovery_ok else 'FAIL'}",
            f"Temporary sources: {temp_root}",
            "Movie source: manual test still required (no synthetic video is generated)",
            "",
            "Failures",
            "--------",
        ]
        lines.extend(f"- {item}" for item in failures) if failures else lines.append("- None")
        lines.extend(("", "Result", "------", "PASS" if not failures else "REVIEW REQUIRED"))
        write_diagnostic_report(
            new_scene, "FBP_Native_Regression_Scene_Report", lines,
            summary=f"Native Regression Scene · {len(failures)} failure(s)",
            status="PASS" if not failures else "WARNING",
        )

        if old_scene is not None and self.replace_existing:
            try:
                bpy.data.scenes.remove(old_scene)
            except (ReferenceError, RuntimeError):
                pass
        new_scene.name = scene_name

        self.report(
            {'WARNING'} if failures else {'INFO'},
            f"Native regression scene: {len(built)} cases, {len(failures)} issue(s), {probe_samples} samples",
        )
        return {'FINISHED'}


def _fbp_regression_safe_defaults(rig, _effect_id):
    """Keep the generated test scene responsive while still evaluating effects."""
    values = {
        "fbp_text_matrix_quality": "CUSTOM",
        "fbp_text_matrix_viewport_columns": 12,
        "fbp_text_matrix_viewport_rows": 0,
        "fbp_text_matrix_render_columns": 24,
        "fbp_text_matrix_render_rows": 0,
        "fbp_text_matrix_playback_columns": 8,
        "fbp_text_matrix_playback_rows": 0,
        "fbp_felt_render_density": 1000,
        "fbp_felt_viewport_percentage": 1.0,
        "fbp_felt_subdivisions": 0,
        "fbp_felt_alpha_resolution": 16,
        "fbp_cutout_outline_viewport_resolution": 3,
        "fbp_cutout_outline_playback_resolution": 2,
        "fbp_cutout_outline_render_resolution": 4,
        "fbp_wind_subdivision": 2,
        "fbp_mesh_wiggle_subdivisions": 2,
        "fbp_stop_motion_resolution": 8,
        "fbp_shadow_mode": "OUTER",
        "fbp_shadow_blend_mode": "MULTIPLY",
        "fbp_shadow_offset_x": 0.035,
        "fbp_shadow_offset_y": -0.035,
        "fbp_shadow_blur": 0.025,
        "fbp_shadow_opacity": 0.7,
    }
    for name, value in values.items():
        if hasattr(rig, name):
            try:
                setattr(rig, name, value)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass


class FBP_OT_CreateEffectRegressionScene(Operator):
    bl_idname = "fbp.create_effect_regression_scene"
    bl_label = "Create Effects Regression Scene"
    bl_description = "Generate a separate scene containing source-type samples and one test layer for every registered effect"
    bl_options = {'REGISTER', 'UNDO'}

    replace_existing: BoolProperty(
        name="Replace Existing",
        description="Replace an existing FBP Effects Regression scene",
        default=True,
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        window = getattr(context, "window", None)
        if window is None:
            self.report({'ERROR'}, "A Blender window is required to create the regression scene")
            return {'CANCELLED'}

        scene_name = "FBP Effects Regression"
        old_scene = bpy.data.scenes.get(scene_name)
        if old_scene is not None and not self.replace_existing:
            self.report({'WARNING'}, "The FBP Effects Regression scene already exists")
            return {'CANCELLED'}

        previous_scene = window.scene
        new_scene = bpy.data.scenes.new(scene_name + "__BUILD")
        window.scene = new_scene
        new_scene["fbp_regression_scene"] = True
        new_scene.frame_start = 1
        new_scene.frame_end = 48
        new_scene.frame_set(1)
        try:
            new_scene.fbp_pre_duration = 6
            new_scene.fbp_pre_loop_mode = 'REPEAT'
            new_scene.fbp_pre_shadeless = True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

        # Clear orphaned data from a previous generated scene without touching user data.
        for obj in tuple(bpy.data.objects):
            try:
                if bool(obj.get("fbp_regression_generated", False)) and obj.users == 0:
                    bpy.data.objects.remove(obj)
            except FBP_DATA_ERRORS:
                pass
        for collection in tuple(bpy.data.collections):
            try:
                if bool(collection.get("fbp_regression_generated", False)) and collection.users == 0:
                    bpy.data.collections.remove(collection)
            except FBP_DATA_ERRORS:
                pass

        root = bpy.data.collections.new("FBP Regression")
        root["fbp_regression_generated"] = True
        new_scene.collection.children.link(root)

        # Camera-aware BASE effects are covered in the same registry loop as every
        # other effect, so the regression Scene must own a camera before that loop.
        camera_data = bpy.data.cameras.new("FBP Regression Camera")
        camera = bpy.data.objects.new("FBP Regression Camera", camera_data)
        root.objects.link(camera)
        camera["fbp_regression_generated"] = True
        camera.location = (0.0, 0.0, 35.0)
        camera_data.type = 'ORTHO'
        camera_data.ortho_scale = 24.0
        new_scene.camera = camera

        source_collection = bpy.data.collections.new("00 - Source Types")
        image_collection = bpy.data.collections.new("01 - Image Effects")
        mesh_collection = bpy.data.collections.new("02 - Mesh Effects")
        combination_collection = bpy.data.collections.new("03 - Combination Stacks")
        mask_interaction_collection = bpy.data.collections.new("04 - Mask Interaction")
        for collection in (
            source_collection, image_collection, mesh_collection,
            combination_collection, mask_interaction_collection,
        ):
            collection["fbp_regression_generated"] = True
            root.children.link(collection)

        temp_root = Path(tempfile.gettempdir()) / "frame_by_plane_regression"
        paths = [
            _fbp_write_regression_image(temp_root / f"fbp_regression_{index:04d}.png", phase=index / 3.0)
            for index in range(1, 4)
        ]
        directory = str(temp_root)
        filenames = [Path(path).name for path in paths]

        built = []
        source_rigs = []
        try:
            image_rig = build_native_fbp_rig(
                context, "SOURCE - Image", directory, [filenames[0]],
                (-5.25, 4.0, 0.0), target_collection=source_collection,
            )
            sequence_rig = build_native_fbp_rig(
                context, "SOURCE - Sequence", directory, filenames,
                (-1.75, 4.0, 0.0), target_collection=source_collection,
            )
            color_rig = build_fbp_color_rig(
                context, "SOURCE - Color", (0.12, 0.48, 0.92, 1.0), True,
                location=(1.75, 4.0, 0.0), target_collection=source_collection,
            )
            gradient_rig = build_fbp_color_rig(
                context, "SOURCE - Gradient", (1.0, 0.45, 0.08, 1.0), True,
                location=(5.25, 4.0, 0.0), target_collection=source_collection,
                gradient_settings={
                    "mode": "LINEAR", "kind": "COLOR",
                    "color_a": (0.02, 0.02, 0.02, 1.0),
                    "color_b": (1.0, 0.45, 0.08, 1.0),
                },
            )
            source_rigs = [image_rig, sequence_rig, color_rig, gradient_rig]
            for source in source_rigs:
                source["fbp_regression_generated"] = True
                plane = getattr(source, "fbp_plane_target", None)
                if plane:
                    plane["fbp_regression_generated"] = True
            # Representative compatibility stacks exercise procedural sources.
            for source, effects in (
                (color_rig, ("HUE_SATURATION", "DOT_MATRIX")),
                (gradient_rig, ("DUOTONE", "HALFTONE", "ASCII_MATRIX")),
            ):
                for source_effect in effects:
                    if fbp_effect_supported_for_rig(source, source_effect):
                        fbp_add_effect(source, source_effect)
            built.extend(source_rigs)
        except Exception as exc:
            try:
                if previous_scene is not None and previous_scene.name in bpy.data.scenes:
                    window.scene = previous_scene
            except (AttributeError, ReferenceError, RuntimeError):
                pass
            try:
                bpy.data.scenes.remove(new_scene)
            except (ReferenceError, RuntimeError):
                pass
            self.report({'ERROR'}, f"Could not create regression sources: {exc}")
            return {'CANCELLED'}

        image_index = 0
        mesh_index = 0
        failures = []
        last_rig_by_collection = {}
        for effect_id, definition in FBP_EFFECT_REGISTRY.items():
            kind = str(definition.get("kind", "") or "")
            category = str(definition.get("category", "") or "")
            is_mesh = kind == "GEOMETRY" or category == "3D"
            index = mesh_index if is_mesh else image_index
            columns = 5
            x = (index % columns) * 3.4 - 6.8
            y = -(index // columns) * 3.2 - (2.0 if is_mesh else 7.0)
            collection = mesh_collection if is_mesh else image_collection
            if is_mesh:
                mesh_index += 1
            else:
                image_index += 1
            label = str(definition.get("label", effect_id) or effect_id)
            try:
                test_files = [filenames[0]] if index % 2 == 0 else filenames
                source_tag = "IMG" if len(test_files) == 1 else "SEQ"
                rig = build_native_fbp_rig(
                    context, f"TEST {source_tag} - {label}", directory, test_files,
                    (x, y, 0.0), target_collection=collection,
                )
                rig["fbp_regression_generated"] = True
                plane = getattr(rig, "fbp_plane_target", None)
                if plane:
                    plane["fbp_regression_generated"] = True
                    plane.is_fbp_plane = True
                    try:
                        if getattr(plane, "data", None) is not None:
                            plane.data["fbp_plane_mesh"] = True
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                        pass
                    plane["fbp_parent_rig_name"] = str(rig.name)
                    # Keep the relation explicit in generated regression scenes;
                    # this also exercises the same contract used by mesh effects.
                    rig.fbp_plane_target = plane
                _fbp_regression_safe_defaults(rig, effect_id)
                if not fbp_effect_supported_for_rig(rig, effect_id):
                    failures.append(f"{label}: unsupported by regression image source")
                    continue
                if not fbp_add_effect(rig, effect_id):
                    failures.append(f"{label}: add returned false")
                    continue
                # Verify immediately while the exact rig and effect are still
                # known. This exposes builder/modifier failures in the scene
                # report instead of leaving the later aggregate coverage check
                # with only a missing effect id.
                if effect_id not in fbp_effect_ids_for_rig(rig):
                    failures.append(
                        f"{label}: effect was added but is not discoverable on its generated rig"
                    )
                    continue
                source_property = str(definition.get("mask_source_property", "") or "")
                if source_property and source_rigs:
                    source_index = 1 if len(test_files) > 1 and len(source_rigs) > 1 else 0
                    source_candidate = source_rigs[source_index]
                    if bool(definition.get("layer_feature", False)):
                        source_candidate = last_rig_by_collection.get(
                            str(getattr(collection, "name", "") or ""),
                            source_candidate,
                        )
                    fbp_set_rna_property_silent(
                        rig, source_property, source_candidate
                    )
                if bool(definition.get("imported_mask_aware", False)):
                    fbp_set_rna_property_silent(
                        rig, "fbp_imported_mask_path", paths[0]
                    )
                if kind == "GEOMETRY":
                    fbp_update_geometry_effect(rig, effect_id)
                elif kind == "SHADER":
                    fbp_update_shader_effect(rig, effect_id)
                built.append(rig)
                last_rig_by_collection[str(getattr(collection, "name", "") or "")] = rig
            except Exception as exc:
                failures.append(f"{label}: {exc}")


        # Curated multi-effect stacks exercise the interactions that individual
        # one-effect samples cannot reveal. Every effect remains registry- and
        # source-checked so a renamed or temporarily unavailable effect reports
        # a precise regression failure instead of aborting the whole scene.
        combination_specs = (
            ("UV + Color", ("PIXELATE", "SWIRL", "CHROMATIC_ABERRATION", "VIGNETTE"), False),
            ("Print Finish", ("BRIGHTNESS_CONTRAST", "DUOTONE", "HALFTONE", "GRAIN"), False),
            ("Local Effect Masks", ("VIGNETTE", "SQUARE_MASK", "COLOR_MASK", "GRADIENT_MASK", "NOISE_MASK"), False),
            ("Mesh Deformation", ("LATTICE", "MESH_WIGGLE", "THICKNESS"), False),
            ("Paper Surface", ("CUTOUT_OUTLINE", "FELT_FUZZ"), False),
            ("Shadow & Alpha", ("SHADOW", "RIM", "COLOR_MASK"), False),
            ("Animated Stress", ("PIXELATE", "ASCII_MATRIX", "WIND_BENDER"), True),
        )
        combination_built = 0
        combination_base_y = -(
            max((image_index + 4) // 5, (mesh_index + 4) // 5) * 3.2 + 10.0
        )
        for combo_index, (label, effect_stack, animated_source) in enumerate(combination_specs):
            x = (combo_index % 3) * 5.0 - 5.0
            y = combination_base_y - (combo_index // 3) * 3.6
            test_files = filenames if animated_source else [filenames[0]]
            try:
                rig = build_native_fbp_rig(
                    context,
                    f"STACK - {label}",
                    directory,
                    test_files,
                    (x, y, 0.0),
                    target_collection=combination_collection,
                )
                rig["fbp_regression_generated"] = True
                plane = getattr(rig, "fbp_plane_target", None)
                if plane is not None:
                    plane["fbp_regression_generated"] = True
                added_ids = []
                for effect_id in effect_stack:
                    if effect_id not in FBP_EFFECT_REGISTRY:
                        failures.append(f"{label}: missing registered effect {effect_id}")
                        continue
                    if not fbp_effect_supported_for_rig(rig, effect_id):
                        failures.append(f"{label}: {effect_id} is unsupported by this source")
                        continue
                    _fbp_regression_safe_defaults(rig, effect_id)
                    if not fbp_add_effect(rig, effect_id):
                        failures.append(f"{label}: could not add {effect_id}")
                        continue
                    definition = fbp_effect_definition(effect_id)
                    if definition.get("kind") == "GEOMETRY":
                        fbp_update_geometry_effect(rig, effect_id)
                    elif definition.get("kind") == "SHADER":
                        fbp_update_shader_effect(rig, effect_id)
                    added_ids.append(effect_id)
                if not added_ids:
                    failures.append(f"{label}: no effect in the stack could be created")
                    continue
                if label == "Local Effect Masks" and "VIGNETTE" in added_ids:
                    for mask_id in ("SQUARE_MASK", "COLOR_MASK", "GRADIENT_MASK", "NOISE_MASK"):
                        if mask_id in added_ids:
                            fbp_set_effect_mask_target(rig, mask_id, "VIGNETTE")
                elif label == "Shadow & Alpha" and {"COLOR_MASK", "SHADOW"}.issubset(added_ids):
                    fbp_set_effect_mask_target(rig, "COLOR_MASK", "SHADOW")
                recommended = (
                    list(FBP_BASE_EFFECT_MENU_ORDER)
                    + list(FBP_SHADER_STAGE_ORDER.get("UV", ()))
                    + list(FBP_SHADER_STAGE_ORDER.get("COLOR", ()))
                    + list(FBP_SHADER_STAGE_ORDER.get("MASK", ()))
                    + list(FBP_3D_EFFECT_MENU_ORDER)
                )
                fbp_sort_effect_stacks_transactional([rig], recommended)
                order_issues = [
                    f"{effect_id}: {fbp_effect_order_warning(rig, effect_id)}"
                    for effect_id in added_ids
                    if fbp_effect_order_warning(rig, effect_id)
                ]
                failures.extend(f"{label}: {message}" for message in order_issues)
                built.append(rig)
                combination_built += 1
            except Exception as exc:
                failures.append(f"{label}: {exc}")

        # Build a real source/target matte relationship. Individual mask samples
        # verify node construction; this pair exercises animated source binding,
        # clipping projection, imported raster masks and local effect routing in
        # one saveable setup.
        mask_interaction_built = 0
        try:
            pair_y = combination_base_y - ((len(combination_specs) + 2) // 3) * 3.6 - 1.0
            matte_source = build_native_fbp_rig(
                context,
                "MASK SOURCE - Animated",
                directory,
                filenames,
                (-2.6, pair_y, 0.0),
                target_collection=mask_interaction_collection,
            )
            matte_target = build_native_fbp_rig(
                context,
                "MASK TARGET - Interaction Matrix",
                directory,
                [filenames[0]],
                (2.6, pair_y, 1.0),
                target_collection=mask_interaction_collection,
            )
            for generated in (matte_source, matte_target):
                generated["fbp_regression_generated"] = True
                generated_plane = getattr(generated, "fbp_plane_target", None)
                if generated_plane is not None:
                    generated_plane["fbp_regression_generated"] = True

            interaction_effects = (
                "BRIGHTNESS_CONTRAST",
                "CLIPPING_MASK",
                "IMPORTED_MASK",
                "ALPHA_MATTE",
                "LUMA_MATTE",
            )
            interaction_added = []
            for effect_id in interaction_effects:
                if not fbp_effect_supported_for_rig(matte_target, effect_id):
                    failures.append(f"Mask Interaction Matrix: unsupported effect {effect_id}")
                    continue
                _fbp_regression_safe_defaults(matte_target, effect_id)
                if not fbp_add_effect(matte_target, effect_id):
                    failures.append(f"Mask Interaction Matrix: could not add {effect_id}")
                    continue
                interaction_added.append(effect_id)

            for property_name in (
                "fbp_clipping_mask_source",
                "fbp_alpha_matte_source",
                "fbp_luma_matte_source",
            ):
                fbp_set_rna_property_silent(
                    matte_target, property_name, matte_source
                )
            fbp_set_rna_property_silent(
                matte_target, "fbp_imported_mask_path", paths[0]
            )
            if "BRIGHTNESS_CONTRAST" in interaction_added:
                for mask_id in ("ALPHA_MATTE", "LUMA_MATTE"):
                    if mask_id in interaction_added:
                        fbp_set_effect_mask_target(
                            matte_target, mask_id, "BRIGHTNESS_CONTRAST"
                        )
            for effect_id in interaction_added:
                definition = fbp_effect_definition(effect_id)
                if definition.get("kind") == "SHADER":
                    fbp_update_shader_effect(matte_target, effect_id)
            fbp_sync_clipping_masks(
                context, collections=(mask_interaction_collection,)
            )
            if getattr(matte_target, "fbp_clipping_mask_source", None) is not matte_source:
                failures.append(
                    "Mask Interaction Matrix: Clipping Mask source binding did not persist"
                )

            mask_audit = _fbp_mask_interaction_contract_audit(
                (matte_source, matte_target), new_scene,
                repair=False, context=context,
            )
            failures.extend(
                f"Mask Interaction Matrix: {message}"
                for message in (mask_audit.get("issues", ()) or ())
            )
            built.extend((matte_source, matte_target))
            mask_interaction_built = 2
        except Exception as exc:
            failures.append(f"Mask Interaction Matrix: {exc}")

        # Remove only unused FILE wrappers created while probing the generated
        # regression sources. Sequence datablocks and all user-owned images are
        # preserved.
        generated_path_keys = {
            os.path.normcase(os.path.abspath(str(path)))
            for path in paths
        }
        for image in tuple(bpy.data.images):
            try:
                path_key = os.path.normcase(
                    os.path.abspath(bpy.path.abspath(str(getattr(image, "filepath", "") or "")))
                )
                if (
                    path_key in generated_path_keys
                    and str(getattr(image, "source", "FILE") or "FILE") == "FILE"
                    and int(getattr(image, "users", 0) or 0) == 0
                ):
                    bpy.data.images.remove(image)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
                pass

        # Reframe the camera created before effect construction so camera-aware
        # effects and final visual inspection use the same Scene contract.
        positions = []
        for rig in built:
            try:
                positions.append((float(rig.location.x), float(rig.location.y)))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        if positions:
            xs, ys = zip(*positions)
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
        else:
            min_x, max_x, min_y, max_y = -8.0, 8.0, -8.0, 8.0
        center_x = (min_x + max_x) * 0.5
        center_y = (min_y + max_y) * 0.5
        width = max(1.0, max_x - min_x)
        height = max(1.0, max_y - min_y)
        camera.location = (center_x, center_y, 35.0)
        camera_data.ortho_scale = max(24.0, height + 7.0, width / 1.55 + 7.0)
        new_scene.camera = camera

        for obj in new_scene.objects:
            try:
                obj.select_set(False)
            except (AttributeError, RuntimeError):
                pass
        if built:
            try:
                built[0].select_set(True)
                context.view_layer.objects.active = built[0]
            except (AttributeError, RuntimeError):
                pass
        sync_layer_collection(context)

        lines = [
            "Frame By Plane — Effects Regression Scene",
            "=======================================",
            f"Source rigs: {len(source_rigs)}",
            f"Effect rigs: {max(0, len(built) - len(source_rigs) - combination_built - mask_interaction_built)}",
            f"Combination stacks: {combination_built}/{len(combination_specs)}",
            f"Mask interaction layers: {mask_interaction_built}/2",
            f"Temporary sources: {temp_root}",
            "",
            "Failures",
            "--------",
        ]
        lines.extend(f"- {item}" for item in failures)
        if not failures:
            lines.append("- None")
        lines.extend((
            "",
            "Result",
            "------",
            "PASS" if not failures else "WARNING",
        ))
        write_diagnostic_report(
            new_scene, "FBP_Effects_Regression_Report", lines,
            summary=f"Effects Regression Scene · {len(failures)} failure(s)",
            status="PASS" if not failures else "WARNING",
        )
        if old_scene is not None and self.replace_existing:
            try:
                bpy.data.scenes.remove(old_scene)
            except (ReferenceError, RuntimeError):
                pass
        new_scene.name = scene_name

        self.report(
            {'WARNING' if failures else 'INFO'},
            f"Regression scene: {len(built)} layers, {len(failures)} issue(s)",
        )
        return {'FINISHED'}
