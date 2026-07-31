"""Lifecycle, ownership and runtime diagnostics for Frame By Plane.

The module keeps imports of mutation-heavy add-on modules lazy. It can therefore
be registered near the bottom of the dependency graph and used by diagnostics
without introducing circular imports during extension enable/disable.
"""

from __future__ import annotations

import time

import bpy

from .registration import _handler_module_matches
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_RENDER_BUSY,
    FBP_RENDER_IDLE,
    FBP_RENDER_UNKNOWN,
    fbp_obj_runtime_key,
    fbp_render_state,
    fbp_runtime_callbacks_enabled,
    fbp_runtime_get,
    fbp_runtime_set,
    fbp_undo_guard_active,
    fbp_warn,
)


_HANDLER_SPECS = (
    ("frame_change_pre", "fbp_frame_change_handler", 1, "core"),
    ("frame_change_post", "fbp_frame_change_handler", 0, "core"),
    ("frame_change_post", "fbp_shape_mask_frame_change_post", 0, "object_masks"),
    ("frame_change_pre", "fbp_effect_evolve_frame_change", 1, "geometry_nodes"),
    ("animation_playback_pre", "fbp_effect_playback_pre", 1, "geometry_nodes"),
    ("animation_playback_post", "fbp_effect_playback_post", 1, "geometry_nodes"),
    ("frame_change_post", "_fbp_motion_frame_change", 1, "motion_runtime"),
    ("load_post", "_fbp_motion_load_post", 1, "motion_runtime"),
    ("depsgraph_update_pre", "fbp_gp_depsgraph_update_pre", 1, "grease_pencil_bridge"),
    ("frame_change_post", "fbp_gp_frame_change", 1, "grease_pencil_bridge"),
    ("load_post", "fbp_gp_load_post", 1, "grease_pencil_bridge"),
    ("frame_change_post", "_frame_change_guard", 1, "grease_pencil_limited_loop"),
    ("load_post", "_load_post_guard", 1, "grease_pencil_limited_loop"),
    ("frame_change_post", "_cursor_on_camera_frame_handler", 1, "viewport_pie"),
    ("depsgraph_update_post", "fbp_depsgraph_native_ops_handler", 1, "scene_sync"),
    ("depsgraph_update_post", "effect_controls_depsgraph_update", 0, "effect_controls"),
    ("depsgraph_update_post", "fbp_gp_depsgraph_update", 0, "grease_pencil_bridge"),
    ("depsgraph_update_post", "_depsgraph_auto_timing_sync", 0, "grease_pencil_workflow"),
    ("depsgraph_update_post", "_fbp_motion_depsgraph_update", 0, "motion_runtime"),
    ("render_init", "fbp_render_guard_pre", 1, "core"),
    ("render_pre", "fbp_render_guard_pre", 0, "core"),
    ("render_pre", "fbp_shape_mask_render_pre", 0, "object_masks"),
    ("render_post", "fbp_render_guard_complete", 0, "core"),
    ("render_cancel", "fbp_render_guard_complete", 1, "core"),
    ("render_complete", "fbp_render_guard_complete", 1, "core"),
    ("undo_pre", "fbp_undo_pre_handler", 1, "handlers"),
    ("undo_post", "fbp_undo_post_handler", 1, "handlers"),
    ("load_pre", "fbp_load_pre_handler", 1, "handlers"),
    ("load_post", "fbp_load_post_handler", 1, "handlers"),
    (
        "load_post",
        "fbp_performance_load_post",
        1,
        "performance_dashboard",
    ),
    ("load_post", "fbp_compositor_sets_load_post", 1, "compositor_sets"),
    ("depsgraph_update_post", "fbp_compositor_sets_depsgraph_post", 0, "compositor_sets"),
) + (
    (("redo_pre", "fbp_redo_pre_handler", 1, "handlers"),)
    if getattr(bpy.app.handlers, "redo_pre", None) is not None else ()
) + (
    (("redo_post", "fbp_redo_post_handler", 1, "handlers"),)
    if getattr(bpy.app.handlers, "redo_post", None) is not None else ()
)



_UNSAFE_RENDER_CALLBACKS = (
    ("render_init", "fbp_gp_cycles_render_pre", "grease_pencil_bridge"),
    ("render_init", "fbp_gp_cycles_render_setup", "grease_pencil_bridge"),
    ("render_pre", "fbp_gp_cycles_render_pre", "grease_pencil_bridge"),
    ("render_pre", "fbp_gp_cycles_render_setup", "grease_pencil_bridge"),
    ("render_pre", "fbp_shape_mask_render_pre", "object_masks"),
    ("render_cancel", "fbp_gp_cycles_render_complete", "grease_pencil_bridge"),
    ("render_complete", "fbp_gp_cycles_render_complete", "grease_pencil_bridge"),
    ("frame_change_post", "fbp_shape_mask_frame_change_post", "object_masks"),
)

_BACKGROUND_DISABLED_HANDLERS = frozenset({
    ("depsgraph_update_post", "fbp_depsgraph_native_ops_handler"),
    ("undo_pre", "fbp_undo_pre_handler"),
    ("undo_post", "fbp_undo_post_handler"),
    ("redo_pre", "fbp_redo_pre_handler"),
    ("redo_post", "fbp_redo_post_handler"),
    ("load_pre", "fbp_load_pre_handler"),
    ("animation_playback_pre", "fbp_effect_playback_pre"),
    ("animation_playback_post", "fbp_effect_playback_post"),
    ("load_post", "_fbp_motion_load_post"),
    ("depsgraph_update_pre", "fbp_gp_depsgraph_update_pre"),
    ("load_post", "fbp_gp_load_post"),
    ("frame_change_post", "_frame_change_guard"),
    ("load_post", "_load_post_guard"),
    ("frame_change_post", "_cursor_on_camera_frame_handler"),
})

def _handler_count(handler_list, name, module_suffix):
    try:
        return sum(
            1
            for item in tuple(handler_list)
            if getattr(item, "__name__", "") == name
            and _handler_module_matches(
                str(getattr(item, "__module__", "") or ""),
                module_suffix,
            )
        )
    except FBP_DATA_ERRORS:
        return -1


def _object_in_scene(obj, scene):
    if obj is None or scene is None:
        return False
    try:
        return scene.objects.get(obj.name) is obj
    except FBP_DATA_ERRORS:
        try:
            return obj in scene.objects
        except FBP_DATA_ERRORS:
            return False


def _timer_registered(callback):
    if callback is None:
        return False
    try:
        from .managed_timers import fbp_timer_is_registered
        return bool(fbp_timer_is_registered(callback))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        try:
            return bool(bpy.app.timers.is_registered(callback))
        except FBP_DATA_ERRORS:
            return False


def _repair_runtime_services():
    """Idempotently rebuild the public lifecycle services.

    handlers.register() removes stale callback generations by name before adding
    the current functions. It is intentionally used only from explicit Repair
    diagnostics while Blender is confirmed idle and outside Undo/load.
    """
    if fbp_undo_guard_active() or fbp_render_state(include_guard=False) != FBP_RENDER_IDLE:
        return False, "Blender is not idle; lifecycle services were not rebuilt"
    try:
        from . import (
            compositor_sets,
            geometry_nodes,
            grease_pencil_bridge,
            grease_pencil_limited_loop,
            handlers,
            motion_runtime,
            performance_dashboard,
        )
        from .registration import append_handler_once, remove_handlers_by_name

        handlers.register()
        # Retire unsafe render callbacks from any replaced module generation
        # generations. This registration path is idempotent and does not touch
        # RNA classes or datablocks.
        grease_pencil_bridge._register_handlers()

        callbacks = (
            (
                bpy.app.handlers.load_post,
                compositor_sets.fbp_compositor_sets_load_post,
                "compositor_sets",
                True,
            ),
            (
                bpy.app.handlers.load_post,
                performance_dashboard.fbp_performance_load_post,
                "performance_dashboard",
                True,
            ),
            (
                bpy.app.handlers.frame_change_pre,
                geometry_nodes.fbp_effect_evolve_frame_change,
                "geometry_nodes",
                True,
            ),
            (
                bpy.app.handlers.animation_playback_pre,
                geometry_nodes.fbp_effect_playback_pre,
                "geometry_nodes",
                not bool(getattr(bpy.app, "background", False)),
            ),
            (
                bpy.app.handlers.animation_playback_post,
                geometry_nodes.fbp_effect_playback_post,
                "geometry_nodes",
                not bool(getattr(bpy.app, "background", False)),
            ),
            (
                bpy.app.handlers.frame_change_post,
                motion_runtime._fbp_motion_frame_change,
                "motion_runtime",
                True,
            ),
            (
                bpy.app.handlers.load_post,
                motion_runtime._fbp_motion_load_post,
                "motion_runtime",
                not bool(getattr(bpy.app, "background", False)),
            ),
            (
                bpy.app.handlers.frame_change_post,
                grease_pencil_limited_loop._frame_change_guard,
                "grease_pencil_limited_loop",
                not bool(getattr(bpy.app, "background", False)),
            ),
            (
                bpy.app.handlers.load_post,
                grease_pencil_limited_loop._load_post_guard,
                "grease_pencil_limited_loop",
                not bool(getattr(bpy.app, "background", False)),
            ),
        )
        if not bool(getattr(bpy.app, "background", False)):
            from . import viewport_pie
            callbacks += ((
                bpy.app.handlers.frame_change_post,
                viewport_pie._cursor_on_camera_frame_handler,
                "viewport_pie",
                True,
            ),)
        failed = []
        for handler_list, callback, module_suffix, enabled in callbacks:
            if enabled:
                if not append_handler_once(
                    handler_list,
                    callback,
                    module_suffix=module_suffix,
                ):
                    failed.append(str(getattr(callback, "__name__", callback)))
            else:
                remove_handlers_by_name(
                    handler_list,
                    str(getattr(callback, "__name__", "") or ""),
                    module_suffix=module_suffix,
                )
        if failed:
            return False, "Could not restore handlers: " + ", ".join(failed)
        return True, ""
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not rebuild Frame By Plane lifecycle services", exc)
        return False, str(exc)


def _audit_handlers(stats, issues):
    for list_name, callback_name, expected, module_suffix in _HANDLER_SPECS:
        if bool(getattr(bpy.app, "background", False)) and (
            list_name, callback_name
        ) in _BACKGROUND_DISABLED_HANDLERS:
            expected = 0
        handler_list = getattr(bpy.app.handlers, list_name, None)
        if handler_list is None:
            stats["handler_api_missing"] += 1
            issues.append(f"Handler API unavailable: bpy.app.handlers.{list_name}")
            continue
        count = _handler_count(handler_list, callback_name, module_suffix)
        stats["handler_callbacks"] += max(0, count)
        if count < 0:
            stats["handler_query_failures"] += 1
            issues.append(f"Could not inspect {list_name} for {callback_name}")
        elif count != expected:
            stats["handler_mismatches"] += abs(count - expected)
            issues.append(
                f"Handler mismatch: {list_name}/{callback_name} has {count}, expected {expected}"
            )

    for list_name, callback_name, module_suffix in _UNSAFE_RENDER_CALLBACKS:
        handler_list = getattr(bpy.app.handlers, list_name, None)
        if handler_list is None:
            continue
        count = _handler_count(handler_list, callback_name, module_suffix)
        if count > 0:
            stats["unsafe_render_callbacks"] += count
            issues.append(
                f"Unsafe stale callback: {list_name}/{callback_name} has {count}"
            )


def _audit_timers(stats, issues, warnings, *, repair=False):
    try:
        from . import effect_controls, handlers, managed_timers, object_masks, runtime_scheduler, safe_tasks, scene_sync
    except (ImportError, AttributeError) as exc:
        stats["timer_query_failures"] += 1
        issues.append(f"Could not import lifecycle timer modules: {exc}")
        return 0

    if bool(getattr(bpy.app, "background", False)):
        required = ()
    else:
        required_items = [
            ("render guard watchdog", handlers.fbp_render_guard_watchdog),
            ("Undo guard watchdog", handlers.fbp_undo_guard_watchdog),
            ("orphan cleanup safety timer", scene_sync.cleanup_orphan_fbp_planes_timer),
        ]
        if effect_controls.effect_controls_runtime_service_required():
            required_items.append(
                ("effect-control visibility timer", effect_controls._selection_visibility_timer)
            )
        if object_masks.object_mask_runtime_service_required():
            required_items.append(
                ("Shape Mask runtime timer", object_masks.object_mask_runtime_timer)
            )
        required = tuple(required_items)
    for label, callback in required:
        stats["timers_checked"] += 1
        if _timer_registered(callback):
            stats["timers_registered"] += 1
        else:
            stats["timer_mismatches"] += 1
            issues.append(f"Required timer is not registered: {label}")

    # Completed one-shot timers are harmless and Blender unregisters them
    # automatically. Mirror that state before auditing so a previous callback
    # generation cannot survive only as bookkeeping noise.
    try:
        managed_timers.fbp_prune_timer_registry()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    registry = managed_timers.fbp_managed_timer_registry_snapshot()
    stale_registry_keys = []
    try:
        for key, callback in tuple(registry.items()):
            stats["timer_registry_entries"] += 1
            if not _timer_registered(callback):
                stale_registry_keys.append(key)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        stats["timer_query_failures"] += 1
        issues.append("Could not inspect the lifecycle timer registry")
    if stale_registry_keys:
        stats["stale_timer_registry_entries"] += len(stale_registry_keys)
        warnings.append(
            "Stale timer registry entries: " + ", ".join(sorted(str(item) for item in stale_registry_keys)[:20])
        )
        if repair:
            managed_timers.fbp_prune_timer_registry()

    # Reconcile the compatibility facade before inspecting its private maps.
    # Low-level scheduler cancellation is intentionally supported by lifecycle
    # repair and maintenance; completed/cancelled tasks must not survive as stale facade
    # metadata and become false structural issues.
    try:
        safe_tasks.scheduled_task_count()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    keys = getattr(safe_tasks, "_SCHEDULED_KEYS", set())
    runners = getattr(safe_tasks, "_SCHEDULED_RUNNERS", {})
    generations = getattr(safe_tasks, "_SCHEDULED_GENERATIONS", {})
    key_set = set(keys)
    runner_set = set(runners)
    generation_set = set(generations)
    stats["safe_tasks_pending"] = len(runner_set)
    if key_set != runner_set or runner_set != generation_set:
        stats["safe_task_registry_mismatches"] += 1
        issues.append(
            "Safe-task scheduler maps disagree "
            f"(keys={len(key_set)}, runners={len(runner_set)}, generations={len(generation_set)})"
        )
        if repair:
            try:
                safe_tasks.clear_scheduled()
            except FBP_DATA_ERRORS:
                pass
    else:
        for key in tuple(runner_set):
            if not runtime_scheduler.task_is_scheduled(key):
                stats["safe_task_unregistered_runners"] += 1
                issues.append(f"Safe task is missing from the central scheduler: {key}")
        if repair and stats["safe_task_unregistered_runners"]:
            try:
                safe_tasks.clear_scheduled()
            except FBP_DATA_ERRORS:
                pass

    scheduler_state = runtime_scheduler.scheduler_snapshot()
    stats["scheduler_accepting_tasks"] = int(bool(scheduler_state.get("accepting_tasks", False)))
    stats["scheduler_pending"] = int(scheduler_state.get("pending", 0) or 0)
    stats["scheduler_dispatchers"] = int(bool(scheduler_state.get("dispatcher_registered", False)))
    if fbp_runtime_callbacks_enabled() and not stats["scheduler_accepting_tasks"]:
        stats["timer_mismatches"] += 1
        issues.append("Runtime callbacks are enabled while the central scheduler is quiesced")
        if repair:
            try:
                runtime_scheduler.register()
            except FBP_DATA_ERRORS:
                pass
    if stats["scheduler_pending"] and not stats["scheduler_dispatchers"]:
        stats["timer_mismatches"] += 1
        issues.append("Central runtime scheduler has pending work but no Blender timer")
        if repair:
            runtime_scheduler.clear_tasks()
            safe_tasks.clear_scheduled()
            managed_timers.fbp_clear_managed_timers()
    return len(stale_registry_keys)


def _audit_runtime_guards(stats, issues, warnings, *, repair=False):
    now = time.monotonic()
    try:
        from .handlers import fbp_history_runtime_snapshot
        history_state = fbp_history_runtime_snapshot()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        history_state = {
            "active": bool(fbp_undo_guard_active()),
            "cleanup_pending": bool(fbp_runtime_get("fbp_history_cleanup_pending", False)),
            "managed_timers_paused": bool(fbp_runtime_get("fbp_pause_managed_timers", False)),
        }
    undo_active = bool(history_state.get("active", False))
    cleanup_pending = bool(history_state.get("cleanup_pending", False))
    stats["undo_guard_active"] = int(undo_active)
    stats["history_cleanup_pending"] = int(cleanup_pending)
    stats["history_state_quiescent"] = int(not undo_active and not cleanup_pending)
    stats["managed_timers_paused"] = int(bool(history_state.get("managed_timers_paused", False)))
    if cleanup_pending and not undo_active:
        stats["orphaned_history_cleanup"] += 1
        issues.append("History cleanup is pending without an active Undo/load guard")
        if repair:
            fbp_runtime_set("fbp_history_cleanup_pending", False)
    if undo_active:
        try:
            deadline = float(fbp_runtime_get("fbp_undo_guard_deadline", 0.0) or 0.0)
        except (TypeError, ValueError):
            deadline = 0.0
        if deadline > 0.0 and deadline < now:
            stats["stale_undo_guards"] += 1
            issues.append("Undo/load guard is active past its safety deadline")
            if repair:
                fbp_runtime_set("fbp_undo_in_progress", False)
                fbp_runtime_set("fbp_undo_guard_deadline", 0.0)
                fbp_runtime_set("fbp_undo_release_not_before", 0.0)
        else:
            warnings.append("Undo/load guard is currently active; rerun the audit when Blender is idle")

    render_guard = bool(fbp_runtime_get("fbp_render_guard_active", False))
    raw_render_state = fbp_render_state(include_guard=False)
    stats["render_guard_active"] = int(render_guard)
    stats["render_state_idle"] = int(raw_render_state == FBP_RENDER_IDLE)
    stats["render_state_busy"] = int(raw_render_state == FBP_RENDER_BUSY)
    stats["render_state_unknown"] = int(raw_render_state == FBP_RENDER_UNKNOWN)
    if raw_render_state == FBP_RENDER_UNKNOWN:
        warnings.append("Blender render-job state is unknown; mutation diagnostics fail closed")
    if render_guard and raw_render_state == FBP_RENDER_IDLE:
        try:
            started_at = float(fbp_runtime_get("fbp_render_started_at", 0.0) or 0.0)
        except (TypeError, ValueError):
            started_at = 0.0
        age = now - started_at if started_at > 0.0 else 10_000.0
        if age >= 60.0 or bool(fbp_runtime_get("fbp_render_end_requested", False)):
            stats["stale_render_guards"] += 1
            issues.append("Frame By Plane render guard remained active while Blender is idle")
            if repair:
                try:
                    from . import core

                    if not core.fbp_render_guard_idle_restore(getattr(bpy.context, "scene", None)):
                        core.fbp_render_guard_abandon()
                except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
        else:
            warnings.append("Render guard is active while Blender reports idle; it may still be in its startup grace period")


def _audit_scene_ownership(scene, stats, issues, warnings, *, repair=False):
    try:
        from .geometry_nodes import (
            fbp_effect_ids_for_rig,
            fbp_effect_instance_records_for_rig,
            fbp_sync_effect_items,
        )
        from .layers import is_fbp_layer_object
    except (ImportError, AttributeError) as exc:
        stats["ownership_query_failures"] += 1
        issues.append(f"Could not import ownership diagnostics: {exc}")
        return

    scenes = tuple(getattr(bpy.data, "scenes", ()) or ())
    plane_claims = {}
    for candidate_scene in scenes:
        rigs = []
        try:
            rigs = [obj for obj in candidate_scene.objects if is_fbp_layer_object(obj)]
        except FBP_DATA_ERRORS:
            stats["ownership_query_failures"] += 1
            continue
        stats["scenes_checked"] += 1
        stats["rigs_checked"] += len(rigs)
        for rig in rigs:
            rig_name = str(getattr(rig, "name", "<rig>") or "<rig>")
            plane = getattr(rig, "fbp_plane_target", None)
            if plane is None:
                stats["missing_plane_links"] += 1
                issues.append(f"{candidate_scene.name}/{rig_name}: linked plane is missing")
                continue
            plane_key = fbp_obj_runtime_key(plane)
            plane_claims.setdefault(plane_key, []).append((candidate_scene, rig, plane))
            if not bool(getattr(plane, "is_fbp_plane", False)):
                stats["plane_marker_mismatches"] += 1
                issues.append(f"{candidate_scene.name}/{rig_name}: linked object is not marked as an FBP plane")
                if repair:
                    try:
                        plane.is_fbp_plane = True
                        try:
                            if getattr(plane, "data", None) is not None:
                                plane.data["fbp_plane_mesh"] = True
                        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                            pass
                    except FBP_DATA_ERRORS:
                        pass
            if not _object_in_scene(plane, candidate_scene):
                stats["cross_scene_links"] += 1
                issues.append(f"{candidate_scene.name}/{rig_name}: linked plane is not in the same Scene")
            try:
                parent = plane.parent
            except FBP_DATA_ERRORS:
                parent = None
            if parent is not rig:
                stats["parent_mismatches"] += 1
                issues.append(f"{candidate_scene.name}/{rig_name}: linked plane is not parented to its rig")
                if repair and _object_in_scene(plane, candidate_scene):
                    try:
                        world = plane.matrix_world.copy()
                        plane.parent = rig
                        plane.matrix_parent_inverse = rig.matrix_world.inverted_safe()
                        plane.matrix_world = world
                    except FBP_DATA_ERRORS:
                        pass

            actual_ids = tuple(fbp_effect_ids_for_rig(rig))
            try:
                records = tuple(
                    fbp_effect_instance_records_for_rig(
                        rig,
                        effect_ids=actual_ids,
                        ensure=False,
                        sync_storage=False,
                    )
                    or ()
                )
                desired_ui_ids = tuple(
                    str(record.get("effect_id", "") or "")
                    for record in records
                    if str(record.get("effect_id", "") or "")
                )
                if not desired_ui_ids:
                    desired_ui_ids = actual_ids
                ui_ids = tuple(
                    str(getattr(item, "effect_id", "") or "")
                    for item in rig.fbp_effects
                    if str(getattr(item, "row_type", "EFFECT") or "EFFECT") == "EFFECT"
                    and str(getattr(item, "effect_id", "") or "")
                )
            except FBP_DATA_ERRORS:
                desired_ui_ids = actual_ids
                ui_ids = ()
            if ui_ids != desired_ui_ids:
                stats["effect_ui_mismatches"] += 1
                warnings.append(
                    f"{candidate_scene.name}/{rig_name}: transient Effects UI mirror differs from the stored stack"
                )
                if repair:
                    try:
                        fbp_sync_effect_items(
                            rig, [rig], repair_assets=False, normalize_instance_ids=True
                        )
                    except FBP_DATA_ERRORS:
                        pass

    for records in plane_claims.values():
        owner_keys = {
            (fbp_obj_runtime_key(scene_item), fbp_obj_runtime_key(rig))
            for scene_item, rig, _plane in records
        }
        if len(owner_keys) <= 1:
            continue
        stats["multiply_claimed_planes"] += len(records) - 1
        plane_name = str(getattr(records[0][2], "name", "<plane>") or "<plane>")
        owners = ", ".join(
            f"{scene_item.name}/{getattr(rig, 'name', '<rig>')}" for scene_item, rig, _plane in records
        )
        issues.append(f"Plane {plane_name} is claimed by multiple rig owners: {owners}")

    # Current scene must remain addressable after diagnostics. This is a warning,
    # not corruption, because background scripts may not have an active Scene.
    if scene is None:
        warnings.append("No active Scene was available for lifecycle diagnostics")


def lifecycle_audit(scene=None, *, repair=False):
    """Return handler, timer, guard, ownership and UI synchronization health."""
    stats = {
        "handler_callbacks": 0,
        "handler_mismatches": 0,
        "handler_api_missing": 0,
        "handler_query_failures": 0,
        "unsafe_render_callbacks": 0,
        "timers_checked": 0,
        "timers_registered": 0,
        "timer_mismatches": 0,
        "timer_registry_entries": 0,
        "stale_timer_registry_entries": 0,
        "timer_query_failures": 0,
        "safe_tasks_pending": 0,
        "safe_task_registry_mismatches": 0,
        "safe_task_unregistered_runners": 0,
        "undo_guard_active": 0,
        "stale_undo_guards": 0,
        "history_cleanup_pending": 0,
        "history_state_quiescent": 0,
        "orphaned_history_cleanup": 0,
        "managed_timers_paused": 0,
        "render_guard_active": 0,
        "render_state_idle": 0,
        "render_state_busy": 0,
        "render_state_unknown": 0,
        "stale_render_guards": 0,
        "scenes_checked": 0,
        "rigs_checked": 0,
        "missing_plane_links": 0,
        "plane_marker_mismatches": 0,
        "cross_scene_links": 0,
        "parent_mismatches": 0,
        "multiply_claimed_planes": 0,
        "effect_ui_mismatches": 0,
        "ownership_query_failures": 0,
        "lifecycle_repairs": 0,
    }
    issues = []
    warnings = []

    if repair:
        repaired, message = _repair_runtime_services()
        if repaired:
            stats["lifecycle_repairs"] += 1
        elif message:
            warnings.append(message)

    _audit_handlers(stats, issues)
    stale_registry_entries = _audit_timers(
        stats, issues, warnings, repair=repair
    )
    if repair and stale_registry_entries:
        stats["lifecycle_repairs"] += stale_registry_entries
    _audit_runtime_guards(stats, issues, warnings, repair=repair)
    _audit_scene_ownership(scene, stats, issues, warnings, repair=repair)

    if repair:
        # Re-audit externally visible services after repair; leave scene-specific
        # warnings untouched because UI mirrors are transient by design.
        post_stats = dict.fromkeys(stats, 0)
        post_issues = []
        _audit_handlers(post_stats, post_issues)
        repaired_handlers = int(stats["handler_mismatches"]) + int(
            stats["unsafe_render_callbacks"]
        )
        if not post_issues and repaired_handlers:
            stats["lifecycle_repairs"] += repaired_handlers
            issues = [
                item for item in issues
                if not item.startswith(("Handler mismatch:", "Unsafe stale callback:"))
            ]
            stats["handler_mismatches"] = 0
            stats["unsafe_render_callbacks"] = 0

    return {
        "stats": stats,
        "issues": tuple(dict.fromkeys(str(item) for item in issues if item)),
        "warnings": tuple(dict.fromkeys(str(item) for item in warnings if item)),
        "repaired": int(stats.get("lifecycle_repairs", 0) or 0),
    }



__all__ = ("lifecycle_audit",)
