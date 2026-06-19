"""Focused Frame by Plane operator module."""

import bpy
import os
import gc
import json
import statistics
import tempfile
import time
from datetime import datetime
from pathlib import Path
from bpy.props import (
    BoolProperty,
    IntProperty,
)
from bpy.types import Operator

from .layers import (
    collect_project_image_paths,
    collection_has_fbp_content,
    collection_is_hidden_in_view_layer,
    get_primary_fbp_collection,
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
    fbp_native_rig_contract_issues,
)
from .geometry_nodes import (
    fbp_add_effect,
    fbp_effect_ids_for_rig,
    fbp_effect_instance_id_for_rig,
    fbp_find_effect_modifier,
    fbp_refresh_effect_instance_ids,
    fbp_reapply_all_effects,
    fbp_sync_scene_camera_bindings,
    fbp_update_geometry_effect,
    fbp_update_shader_effect,
)
from .effects_registry import (
    FBP_EFFECT_REGISTRY,
    FBP_EFFECT_REGISTRY_ISSUES,
    fbp_effect_definition,
    fbp_effect_supported_for_rig,
)
from .operator_common import (
    _fbp_active_pending_index_and_collection,
    _fbp_active_pending_tree_row,
    _fbp_refresh_pending_tree,
    _fbp_select_pending_index,
)



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

    index: IntProperty(name="Index", description="Pending setup row index to remove", default=-1)

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
            "Frame by Plane - Project Health",
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
        txt = bpy.data.texts.get("FBP_Project_Health") or bpy.data.texts.new("FBP_Project_Health")
        txt.clear()
        txt.write("\n".join(lines))
        level = {'INFO'} if not missing else {'WARNING'}
        self.report(level, f"Health: {len(rigs)} layers, {len(missing)} missing image(s)")
        return {'FINISHED'}


class FBP_OT_DeepAddonAudit(Operator):
    bl_idname = "fbp.deep_addon_audit"
    bl_label = "Run Deep Add-on Audit"
    bl_description = "Validate effects, native media bindings, camera links and generated datablocks"

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
            "duplicate_file_wrappers": 0,
            "repaired": 0,
        }
        instance_owners = {}

        if self.repair:
            for rig in rigs:
                try:
                    if fbp_refresh_effect_instance_ids(rig):
                        stats["repaired"] += 1
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
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
                    issues.extend(
                        f"{rig_name}: {message}" for message in native_issues
                    )
            effect_ids = tuple(fbp_effect_ids_for_rig(rig))
            stats["effects"] += len(effect_ids)
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
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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

        for group in bpy.data.node_groups:
            try:
                private = bool(group.get("fbp_private_effect_group", False))
                generated = bool(group.get("fbp_generated_effect_group", False)) or private
                if generated and group.users == 0:
                    stats["orphan_groups"] += 1
                    warnings.append(f"Unused generated node group: {group.name}")
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
                    expected_source_count = 1
                    try:
                        runtime_payload = json.loads(str(material.get("fbp_native_runtime_sequence_json", "") or "{}"))
                        runtime_files = runtime_payload.get("files", []) if isinstance(runtime_payload, dict) else []
                        expected_source_count = max(1, len(runtime_files))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        expected_source_count = 1
                    for node in getattr(getattr(material, "node_tree", None), "nodes", ()) or ():
                        if not bool(node.get("fbp_native_sequence_node", False)):
                            continue
                        image = getattr(node, "image", None)
                        if image is None or str(getattr(image, "source", "FILE") or "FILE") not in {"SEQUENCE", "MOVIE"}:
                            continue
                        if str(getattr(image, "source", "FILE") or "FILE") == "SEQUENCE":
                            image_user = getattr(node, "image_user", None)
                            actual_duration = int(getattr(image_user, "frame_duration", 0) or 0) if image_user else 0
                            if actual_duration != expected_source_count:
                                stats["native_duration_mismatch"] += 1
                                warnings.append(
                                    f"Native source-count mismatch: {material.name} uses "
                                    f"frame_duration={actual_duration}, expected {expected_source_count}"
                                )
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
                            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                                pass
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                    issues.append(f"{getattr(rig, 'name', '<rig>')}: repair failed: {exc}")
            try:
                fbp_sync_scene_camera_bindings(scene, force=True)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
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
        lines.extend(("", "Result", "------"))
        lines.append("PASS" if not issues else "REVIEW REQUIRED")

        text = bpy.data.texts.get("FBP_Deep_Addon_Audit") or bpy.data.texts.new("FBP_Deep_Addon_Audit")
        text.clear()
        text.write("\n".join(lines))
        level = {'INFO'} if not issues else {'WARNING'}
        self.report(level, f"Audit: {len(issues)} issue(s), {len(warnings)} warning(s); report saved in Text Editor")
        return {'FINISHED'}

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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            self.report({'ERROR'}, f"Effects profiler failed: {exc}")
            return {'CANCELLED'}
        finally:
            try:
                scene.frame_set(original_frame)
                view_layer.update()
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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

        scene['fbp_effect_profile_timestamp'] = measured_at
        scene['fbp_effect_profile_samples'] = int(len(measurements))
        scene['fbp_effect_profile_avg_ms'] = float(average_ms)
        scene['fbp_effect_profile_median_ms'] = float(median_ms)
        scene['fbp_effect_profile_min_ms'] = float(minimum_ms)
        scene['fbp_effect_profile_max_ms'] = float(maximum_ms)
        scene['fbp_effect_profile_rss_mb'] = float(rss_mb)
        scene['fbp_effect_profile_delta_mb'] = float(delta_mb)

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
        text = bpy.data.texts.get("FBP_Effects_Profiler_Report") or bpy.data.texts.new("FBP_Effects_Profiler_Report")
        text.clear()
        text.write("\n".join(lines))

        self.report({'INFO'}, f"Effects profile: {average_ms:.2f} ms average · {rss_mb:.1f} MiB")
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
        "fbp_thickness_alpha_resolution": 6,
        "fbp_cutout_outline_viewport_resolution": 3,
        "fbp_cutout_outline_playback_resolution": 2,
        "fbp_cutout_outline_render_resolution": 4,
        "fbp_wind_subdivision": 2,
        "fbp_mesh_wiggle_subdivisions": 2,
        "fbp_stop_motion_resolution": 8,
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
            new_scene.fbp_pre_loop_mode = 'LOOP'
            new_scene.fbp_pre_shadeless = True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

        # Clear orphaned data from a previous generated scene without touching user data.
        for obj in tuple(bpy.data.objects):
            try:
                if bool(obj.get("fbp_regression_generated", False)) and obj.users == 0:
                    bpy.data.objects.remove(obj)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        for collection in tuple(bpy.data.collections):
            try:
                if bool(collection.get("fbp_regression_generated", False)) and collection.users == 0:
                    bpy.data.collections.remove(collection)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass

        root = bpy.data.collections.new("FBP Regression")
        root["fbp_regression_generated"] = True
        new_scene.collection.children.link(root)
        source_collection = bpy.data.collections.new("00 - Source Types")
        image_collection = bpy.data.collections.new("01 - Image Effects")
        mesh_collection = bpy.data.collections.new("02 - Mesh Effects")
        for collection in (source_collection, image_collection, mesh_collection):
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
                _fbp_regression_safe_defaults(rig, effect_id)
                if not fbp_effect_supported_for_rig(rig, effect_id):
                    failures.append(f"{label}: unsupported by regression image source")
                    continue
                if not fbp_add_effect(rig, effect_id):
                    failures.append(f"{label}: add returned false")
                    continue
                if kind == "GEOMETRY":
                    fbp_update_geometry_effect(rig, effect_id)
                elif kind == "SHADER":
                    fbp_update_shader_effect(rig, effect_id)
                built.append(rig)
            except Exception as exc:
                failures.append(f"{label}: {exc}")

        # Camera points down the local -Z axis onto the XY layout.
        camera_data = bpy.data.cameras.new("FBP Regression Camera")
        camera = bpy.data.objects.new("FBP Regression Camera", camera_data)
        root.objects.link(camera)
        camera["fbp_regression_generated"] = True
        camera.location = (0.0, -8.0, 35.0)
        camera_data.type = 'ORTHO'
        rows = max(1, (max(image_index, mesh_index) + 4) // 5)
        camera_data.ortho_scale = max(24.0, rows * 7.0 + 12.0)
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
            "Frame by Plane Effects Regression Scene",
            "=======================================",
            f"Source rigs: {len(source_rigs)}",
            f"Effect rigs: {max(0, len(built) - len(source_rigs))}",
            f"Failures: {len(failures)}",
            f"Temporary sources: {temp_root}",
            "",
        ]
        lines.extend(f"- {item}" for item in failures)
        text = bpy.data.texts.get("FBP_Effects_Regression_Report") or bpy.data.texts.new("FBP_Effects_Regression_Report")
        text.clear()
        text.write("\n".join(lines))
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

