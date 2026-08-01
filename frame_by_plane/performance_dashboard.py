"""On-demand project performance profiling and optimization guidance."""

from __future__ import annotations

import json
import math
import os
import statistics
import time
import tracemalloc
from datetime import datetime, timezone

import bpy
from bpy.props import (
    CollectionProperty,
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator, PropertyGroup, UIList

from .registration import (
    register_classes,
    register_handlers,
    register_interactive_classes,
    remove_handlers_by_name,
    unregister_classes,
    unregister_type_properties,
)
from .runtime import FBP_DATA_ERRORS, fbp_runtime_get, fbp_runtime_set
from .ui_style import configure_layout, empty_state, hint_row, section_header
from .ui_list_state import mark_ui_list_draw
from .interface_preferences import (
    fbp_draw_uilist_spacer,
    fbp_draw_uilist_header,
    fbp_uilist_icon_order,
    fbp_uilist_is_spacer,
    fbp_uilist_visible_columns,
)


PERFORMANCE_REPORT_SCHEMA_VERSION = 2
PERFORMANCE_REPORT_TEXT_NAME = "FBP_Performance_Report"
PERFORMANCE_REPORT_FILENAME = "FBP_Performance_Report.json"

_MIB = 1024.0 * 1024.0
_GIB = 1024.0 * _MIB
_TIER_SCORE = {
    "LIGHT": 1.0,
    "MEDIUM": 3.0,
    "HEAVY": 6.0,
    "VERY_HEAVY": 10.0,
    "USER": 4.0,
}
_TIER_ORDER = {
    "LIGHT": 0,
    "MEDIUM": 1,
    "USER": 2,
    "HEAVY": 3,
    "VERY_HEAVY": 4,
}
_REPORT_CACHE = globals().get("_REPORT_CACHE", {})
if not isinstance(_REPORT_CACHE, dict):
    _REPORT_CACHE = {}
_PROFILE_ENV_ENABLED = str(os.environ.get("FBP_PROFILE", "") or "").strip().lower() in {
    "1", "true", "yes", "on",
}
_PROFILE_RUN_ACTIVE = False


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_name(value, fallback=""):
    try:
        return str(value or fallback)
    except FBP_DATA_ERRORS:
        return str(fallback or "")


def _pointer_key(value):
    if value is None:
        return 0
    try:
        return int(value.as_pointer())
    except FBP_DATA_ERRORS:
        return id(value)


def _scene_key(scene):
    return _pointer_key(scene)


def format_memory(byte_count):
    byte_count = max(0.0, float(byte_count or 0.0))
    if byte_count >= _GIB:
        return f"{byte_count / _GIB:.2f} GiB"
    if byte_count >= _MIB:
        return f"{byte_count / _MIB:.1f} MiB"
    if byte_count >= 1024.0:
        return f"{byte_count / 1024.0:.1f} KiB"
    return f"{int(byte_count)} B"


def _percentile(values, quantile):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * max(0.0, min(1.0, float(quantile)))
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * (position - lower))


def _timing_summary_ms(samples):
    values = tuple(max(0.0, float(value)) for value in samples)
    return {
        "samples": len(values),
        "avg_ms": statistics.fmean(values) if values else 0.0,
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "max_ms": max(values, default=0.0),
    }


def _profile_enabled():
    return bool(
        _PROFILE_ENV_ENABLED
        or fbp_runtime_get("fbp_profile_enabled", False)
    )


def _set_profile_enabled(enabled):
    return fbp_runtime_set("fbp_profile_enabled", bool(enabled))


def _profile_toggle_update(self, _context):
    try:
        _set_profile_enabled(bool(self.fbp_performance_profile_enabled))
    except FBP_DATA_ERRORS:
        pass


def runtime_profile_snapshot(scene=None):
    """Collect primitive local metrics; never writes files or uses the network."""
    from . import fbp_startup_profile_snapshot
    from .geometry_nodes import fbp_effect_runtime_profile_metrics
    from .layer_tree_snapshot import snapshot_metrics
    from .runtime_scheduler import scheduler_metrics
    from .ui_icons import custom_icon_metrics
    from .ui_list_state import transient_state_snapshot

    scene = scene or getattr(bpy.context, "scene", None)
    media_memory = 0
    managed_proxies = 0
    image_count = 0
    try:
        image_count = len(bpy.data.images)
        for image in bpy.data.images:
            media_memory += _image_estimated_bytes(image)
            try:
                managed_proxies += int(bool(
                    image.get("fbp_native_sequence_proxy", False)
                    or image.get("fbp_generated_proxy", False)
                ))
            except FBP_DATA_ERRORS:
                pass
    except FBP_DATA_ERRORS:
        pass
    return {
        "enabled": bool(_profile_enabled()),
        "local_only": True,
        "startup": fbp_startup_profile_snapshot(),
        "effect_handler": fbp_effect_runtime_profile_metrics(),
        "scheduler": scheduler_metrics(),
        "media_cache": {
            "loaded_images": int(image_count),
            "estimated_decoded_bytes": int(media_memory),
            "managed_proxy_images": int(managed_proxies),
            "hit_miss_scope": "Layer Tree snapshot cache; Blender image-cache internals are not exposed.",
            "layer_tree": snapshot_metrics(),
        },
        "ui": {
            "ui_lists": transient_state_snapshot(),
            "icons": custom_icon_metrics(),
            "panel_draw_timing": "Not exposed by Blender; interactive regression records total redraw wall time.",
        },
    }


def _profile_runtime_block_reason(context, *, reject_background=False):
    if _PROFILE_RUN_ACTIVE:
        return "Another Frame By Plane profile is already active"
    if reject_background and bool(getattr(bpy.app, "background", False)):
        return "Interactive profiling is unavailable in background mode"
    try:
        if bool(getattr(getattr(context, "screen", None), "is_animation_playing", False)):
            return "Stop animation playback before profiling"
    except FBP_DATA_ERRORS:
        pass
    try:
        from .runtime import FBP_RENDER_IDLE, fbp_render_state
        if fbp_render_state(include_guard=True) != FBP_RENDER_IDLE:
            return "Wait for the active render to finish before profiling"
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return "Render state is unavailable; profiling is blocked safely"
    try:
        from .generation_transaction import active_generation_owner
        if active_generation_owner() is not None:
            return "Wait for Frame By Plane generation to finish before profiling"
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from .handlers import fbp_undo_guard_active
        if fbp_undo_guard_active():
            return "Wait for Undo, Redo or file loading to finish before profiling"
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return ""


def profile_frame_changes(scene, *, frame_count=120, warmup=8, profile_context="PLAYBACK"):
    """Measure timing, memory and profiler overhead in separate runs."""
    global _PROFILE_RUN_ACTIVE
    from .geometry_nodes import fbp_effect_runtime_profile_metrics
    from .runtime_scheduler import scheduler_metrics

    if scene is None:
        raise ValueError("A scene is required")
    if tracemalloc.is_tracing():
        raise RuntimeError("Stop the existing Python allocation trace before timing frames")
    block_reason = _profile_runtime_block_reason(getattr(bpy, "context", None))
    if block_reason:
        raise RuntimeError(block_reason)
    frame_count = max(1, int(frame_count))
    warmup = max(0, int(warmup))
    profile_context = str(profile_context or "PLAYBACK").upper()
    if profile_context not in {"VIEWPORT", "PLAYBACK", "RENDER"}:
        profile_context = "PLAYBACK"
    original_frame = int(getattr(scene, "frame_current", 1) or 1)
    start_frame = int(getattr(scene, "frame_start", 1) or 1)
    end_frame = max(start_frame, int(getattr(scene, "frame_end", start_frame) or start_frame))
    span = max(1, end_frame - start_frame + 1)
    fps = max(
        0.001,
        float(getattr(scene.render, "fps", 24) or 24)
        / max(0.001, float(getattr(scene.render, "fps_base", 1.0) or 1.0)),
    )
    budget_ms = 1000.0 / fps
    was_enabled = _profile_enabled()
    samples = []
    calibration_samples = []
    memory_initial_bytes = 0
    memory_final_bytes = 0
    memory_tracing_started_here = False
    calibration_count = min(frame_count, 24)
    memory_count = min(frame_count, 24)
    try:
        _PROFILE_RUN_ACTIVE = True
        _set_profile_enabled(False)
        for offset in range(warmup):
            scene.frame_set(start_frame + (offset % span))
        fbp_effect_runtime_profile_metrics(reset=True)
        scheduler_metrics(reset=True)
        # Authoritative timing run: tracemalloc is deliberately off and local
        # handler timing is disabled unless forced by FBP_PROFILE in the process.
        for offset in range(frame_count):
            frame = start_frame + (offset % span)
            started = time.perf_counter()
            scene.frame_set(frame)
            if profile_context == "VIEWPORT":
                view_layer = getattr(bpy.context, "view_layer", None)
                if view_layer is not None:
                    view_layer.update()
            samples.append((time.perf_counter() - started) * 1000.0)

        # Short same-fixture calibration run with detailed handler profiling on.
        # It is reported separately and never mixed into the authoritative run.
        _set_profile_enabled(True)
        fbp_effect_runtime_profile_metrics(reset=True)
        scheduler_metrics(reset=True)
        for offset in range(calibration_count):
            frame = start_frame + (offset % span)
            started = time.perf_counter()
            scene.frame_set(frame)
            if profile_context == "VIEWPORT":
                view_layer = getattr(bpy.context, "view_layer", None)
                if view_layer is not None:
                    view_layer.update()
            calibration_samples.append((time.perf_counter() - started) * 1000.0)
        handler_metrics = fbp_effect_runtime_profile_metrics()
        scheduler_profile = scheduler_metrics()

        # Separate allocation run. No value measured here contributes to avg,
        # p50, p95 or max frame timing.
        _set_profile_enabled(False)
        memory_tracing_started_here = not tracemalloc.is_tracing()
        if memory_tracing_started_here:
            tracemalloc.start()
        memory_initial_bytes = int(tracemalloc.get_traced_memory()[0])
        for offset in range(memory_count):
            scene.frame_set(start_frame + (offset % span))
        memory_final_bytes = int(tracemalloc.get_traced_memory()[0])
        if memory_tracing_started_here and tracemalloc.is_tracing():
            tracemalloc.stop()
            memory_tracing_started_here = False

        timing = _timing_summary_ms(samples)
        timing["effective_fps"] = (
            1000.0 / timing["avg_ms"] if timing["avg_ms"] > 0.0 else 0.0
        )
        timing["target_fps"] = fps
        timing["frame_budget_ms"] = budget_ms
        timing["frames_over_budget"] = sum(1 for value in samples if value > budget_ms)
        calibration = _timing_summary_ms(calibration_samples)
        baseline_subset = _timing_summary_ms(samples[:calibration_count])
        baseline_avg = float(baseline_subset.get("avg_ms", 0.0) or 0.0)
        enabled_avg = float(calibration.get("avg_ms", 0.0) or 0.0)
        overhead_percent = (
            ((enabled_avg - baseline_avg) / baseline_avg) * 100.0
            if baseline_avg > 0.0 else 0.0
        )
        return {
            "profile_context": profile_context,
            "contract": (
                "Controlled scene.frame_set evaluation; VIEWPORT also updates the active view layer. "
                "PLAYBACK and RENDER are CPU-side approximations, not GPU presentation or final render timings. "
                "Authoritative timing runs without tracemalloc; allocation sampling is separate."
            ),
            "warmup_frames": warmup,
            "measured_frames": frame_count,
            "frame_evaluation": timing,
            "effect_handler": handler_metrics,
            "scheduler": scheduler_profile,
            "instrumentation": {
                "timing_tracemalloc": False,
                "timing_profile_enabled": bool(_PROFILE_ENV_ENABLED),
                "calibration_samples": calibration_count,
                "baseline_subset_avg_ms": baseline_avg,
                "profile_enabled_avg_ms": enabled_avg,
                "estimated_overhead_percent": overhead_percent,
                "warmup_frames": warmup,
                "machine": str(getattr(bpy.app, "build_platform", b"")),
                "blender_version": ".".join(str(value) for value in bpy.app.version),
                "scene": _safe_name(getattr(scene, "name", ""), "Scene"),
            },
            "memory": {
                "mode": "separate allocation run with tracemalloc",
                "included_in_timing": False,
                "samples": memory_count,
                "python_initial_bytes": memory_initial_bytes,
                "python_final_bytes": memory_final_bytes,
                "python_delta_bytes": memory_final_bytes - memory_initial_bytes,
            },
            "state_restored": True,
        }
    finally:
        try:
            scene.frame_set(original_frame)
        finally:
            if memory_tracing_started_here and tracemalloc.is_tracing():
                tracemalloc.stop()
            _set_profile_enabled(was_enabled)
            _PROFILE_RUN_ACTIVE = False


def _normalized_path(value):
    try:
        raw = bpy.path.abspath(str(value or ""))
        return os.path.normcase(os.path.abspath(raw)) if raw else ""
    except (AttributeError, OSError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ""


def _image_estimated_bytes(image, fallback_width=0, fallback_height=0):
    width = max(0, int(fallback_width or 0))
    height = max(0, int(fallback_height or 0))
    channels = 4
    depth = 32
    if image is not None:
        try:
            size = tuple(getattr(image, "size", ()) or ())
            if len(size) >= 2:
                width = max(width, int(size[0] or 0))
                height = max(height, int(size[1] or 0))
            channels = max(1, int(getattr(image, "channels", 4) or 4))
            depth = max(
                channels * 8,
                int(getattr(image, "depth", channels * 8) or channels * 8),
            )
        except FBP_DATA_ERRORS:
            pass
    # Blender Image.depth reports total pixel depth (for example RGBA8 = 32).
    bytes_per_pixel = max(channels, (depth + 7) // 8)
    return max(0, width * height * bytes_per_pixel), width, height, channels


def _image_record(image, *, filepath="", width=0, height=0, label=""):
    estimate, width, height, channels = _image_estimated_bytes(
        image,
        width,
        height,
    )
    image_path = ""
    if image is not None:
        try:
            image_path = _normalized_path(getattr(image, "filepath", ""))
        except FBP_DATA_ERRORS:
            image_path = ""
    image_path = image_path or _normalized_path(filepath)
    pointer = _pointer_key(image)
    key = (
        ("IMAGE", pointer)
        if pointer
        else ("PATH", image_path, int(width), int(height))
    )
    return {
        "key": key,
        "name": _safe_name(
            getattr(image, "name", "") if image is not None else label,
            os.path.basename(image_path) or "Media",
        ),
        "filepath": image_path,
        "width": int(width),
        "height": int(height),
        "channels": int(channels),
        "estimated_bytes": int(estimate),
        "loaded": bool(image is not None),
    }


def _rig_media_records(rig):
    records = {}
    try:
        items = tuple(getattr(rig, "fbp_images", ()) or ())
    except FBP_DATA_ERRORS:
        items = ()
    for item in items:
        try:
            if bool(getattr(item, "is_empty", False)):
                continue
            image = getattr(item, "image", None)
            if image is None:
                image_name = _safe_name(getattr(item, "image_name", ""))
                image = bpy.data.images.get(image_name) if image_name else None
            record = _image_record(
                image,
                filepath=getattr(item, "filepath", ""),
                width=getattr(item, "source_width", 0),
                height=getattr(item, "source_height", 0),
                label=getattr(item, "name", ""),
            )
            records.setdefault(record["key"], record)
        except FBP_DATA_ERRORS:
            continue

    # Include generated/current material images that may not have a logical
    # frame row (for example a generated color or an imported cutout buffer).
    try:
        plane = getattr(rig, "fbp_plane_target", None)
        materials = tuple(getattr(getattr(plane, "data", None), "materials", ()) or ())
    except FBP_DATA_ERRORS:
        materials = ()
    for material in materials:
        try:
            node_tree = getattr(material, "node_tree", None)
            nodes = tuple(getattr(node_tree, "nodes", ()) or ()) if node_tree else ()
        except FBP_DATA_ERRORS:
            nodes = ()
        for node in nodes:
            try:
                image = getattr(node, "image", None)
            except FBP_DATA_ERRORS:
                image = None
            if image is None:
                continue
            record = _image_record(image)
            records.setdefault(record["key"], record)
    return tuple(records.values())


def _gp_canvas_stats(canvas):
    frames = 0
    strokes = 0
    points = 0
    drawings_seen = set()
    try:
        layers = tuple(getattr(getattr(canvas, "data", None), "layers", ()) or ())
    except FBP_DATA_ERRORS:
        layers = ()
    for layer in layers:
        try:
            layer_frames = tuple(getattr(layer, "frames", ()) or ())
        except FBP_DATA_ERRORS:
            layer_frames = ()
        frames += len(layer_frames)
        for frame in layer_frames:
            try:
                drawing = getattr(frame, "drawing", None)
            except FBP_DATA_ERRORS:
                drawing = None
            key = _pointer_key(drawing)
            if drawing is None or key in drawings_seen:
                continue
            drawings_seen.add(key)
            try:
                drawing_strokes = tuple(getattr(drawing, "strokes", ()) or ())
            except FBP_DATA_ERRORS:
                drawing_strokes = ()
            strokes += len(drawing_strokes)
            for stroke in drawing_strokes:
                try:
                    points += len(getattr(stroke, "points", ()) or ())
                except FBP_DATA_ERRORS:
                    continue
    # Explicitly labeled estimate: geometry, attributes and RNA overhead vary
    # across Blender builds, so this is useful for comparison, not accounting.
    estimated_bytes = points * 64 + strokes * 192 + frames * 256
    return {
        "layers": len(layers),
        "frames": frames,
        "strokes": strokes,
        "points": points,
        "estimated_bytes": estimated_bytes,
    }


def _modifier_execution_ms(modifier):
    if modifier is None:
        return 0.0
    try:
        return max(
            0.0,
            float(getattr(modifier, "execution_time", 0.0) or 0.0)
            * 1000.0,
        )
    except FBP_DATA_ERRORS:
        return 0.0


def _effect_node_count(rig, effect_id, instance_id, definition):
    try:
        from .geometry_nodes import (
            _fbp_find_shader_effect_nodes_for_rig,
            fbp_find_effect_modifier,
        )
    except ImportError:
        return 0, 0.0
    kind = _safe_name(definition.get("kind", "")).upper()
    if kind == "GEOMETRY":
        modifier = fbp_find_effect_modifier(rig, effect_id, instance_id)
        try:
            node_group = getattr(modifier, "node_group", None)
            nodes = len(getattr(node_group, "nodes", ()) or ()) if node_group else 0
        except FBP_DATA_ERRORS:
            nodes = 0
        return int(nodes), _modifier_execution_ms(modifier)
    try:
        group_nodes = tuple(
            _fbp_find_shader_effect_nodes_for_rig(
                rig,
                effect_id,
                instance_id=instance_id,
            )
            or ()
        )
    except FBP_DATA_ERRORS:
        group_nodes = ()
    node_count = 0
    for node in group_nodes:
        try:
            node_tree = getattr(node, "node_tree", None)
            node_count += (
                len(getattr(node_tree, "nodes", ()) or ())
                if node_tree is not None
                else 1
            )
        except FBP_DATA_ERRORS:
            node_count += 1
    return int(node_count), 0.0


def _effect_records(rig):
    from .effects_registry import fbp_effect_definition
    from .geometry_nodes import (
        fbp_effect_ids_for_rig,
        fbp_effect_instance_records_for_rig,
    )

    effect_ids = tuple(fbp_effect_ids_for_rig(rig))
    try:
        instances = tuple(
            fbp_effect_instance_records_for_rig(
                rig,
                effect_ids=effect_ids,
                ensure=False,
                sync_storage=False,
            )
            or ()
        )
    except FBP_DATA_ERRORS:
        instances = ()
    if not instances:
        instances = tuple(
            {"effect_id": effect_id, "instance_id": ""}
            for effect_id in effect_ids
        )
    totals = {}
    for record in instances:
        effect_id = _safe_name(record.get("effect_id", "")).upper()
        if effect_id:
            totals[effect_id] = totals.get(effect_id, 0) + 1
    ordinals = {}
    result = []
    seen = set()
    for record in instances:
        effect_id = _safe_name(record.get("effect_id", "")).upper()
        instance_id = _safe_name(record.get("instance_id", ""))
        if not effect_id:
            continue
        token = (effect_id, instance_id)
        if token in seen:
            continue
        seen.add(token)
        definition = fbp_effect_definition(effect_id) or {}
        tier = _safe_name(definition.get("performance", "LIGHT"), "LIGHT").upper()
        if tier not in _TIER_SCORE:
            tier = "USER"
        node_count, observed_ms = _effect_node_count(
            rig,
            effect_id,
            instance_id,
            definition,
        )
        ordinals[effect_id] = ordinals.get(effect_id, 0) + 1
        label = _safe_name(
            definition.get("label", ""),
            effect_id.replace("_", " ").title(),
        )
        if totals.get(effect_id, 0) > 1:
            label = f"{label} {ordinals[effect_id]}"
        result.append(
            {
                "effect_id": effect_id,
                "instance_id": instance_id,
                "label": label,
                "kind": _safe_name(definition.get("kind", "SHADER")).upper(),
                "category": _safe_name(
                    definition.get("category", "2D")
                ).upper(),
                "tier": tier,
                "cost_score": float(_TIER_SCORE[tier]),
                "node_count": int(node_count),
                "observed_ms": round(float(observed_ms), 6),
                "has_observed_timing": bool(observed_ms > 0.0),
                "quality_controls": bool(
                    definition.get("quality_contracts")
                    or definition.get("quality_profile", "NONE") != "NONE"
                ),
            }
        )
    return tuple(result)


def _guidance(
    severity,
    code,
    message,
    *,
    object_name="",
    effect_id="",
    action="",
):
    return {
        "severity": _safe_name(severity, "INFO").upper(),
        "code": _safe_name(code, "PERFORMANCE").upper(),
        "message": _safe_name(message),
        "object_name": _safe_name(object_name),
        "effect_id": _safe_name(effect_id).upper(),
        "action": _safe_name(action),
    }


def _effect_guidance(rig_name, effect):
    tier = effect["tier"]
    label = effect["label"]
    result = []
    if effect["observed_ms"] >= 50.0:
        result.append(
            _guidance(
                "WARNING",
                "SLOW_EFFECT",
                f"{label} last evaluated in {effect['observed_ms']:.1f} ms.",
                object_name=rig_name,
                effect_id=effect["effect_id"],
                action=(
                    "Lower viewport detail/density or disable this effect "
                    "during layout and playback."
                ),
            )
        )
    elif effect["observed_ms"] >= 20.0:
        result.append(
            _guidance(
                "INFO",
                "EFFECT_TIMING",
                f"{label} last evaluated in {effect['observed_ms']:.1f} ms.",
                object_name=rig_name,
                effect_id=effect["effect_id"],
                action="Review viewport quality if playback misses its target.",
            )
        )
    if tier in {"HEAVY", "VERY_HEAVY"}:
        action = (
            "Use lower Viewport/Playback quality while retaining Render quality."
            if effect["quality_controls"]
            else (
                "Bypass the effect during layout or use a lower-resolution "
                "source when interactive playback matters."
            )
        )
        result.append(
            _guidance(
                "WARNING" if tier == "VERY_HEAVY" else "INFO",
                "HEAVY_EFFECT",
                f"{label} is classified {tier.replace('_', ' ').title()}.",
                object_name=rig_name,
                effect_id=effect["effect_id"],
                action=action,
            )
        )
    return result


def build_performance_report(scene):
    """Build a primitive, deterministic and non-destructive report snapshot."""
    from .fbp_index import iter_scene_fbp_rigs, iter_scene_gp_canvases
    from .layers import fbp_layer_backend_type

    layers = []
    effects = []
    guidance = []
    unique_media = {}
    layer_media_sum = 0
    rigs = tuple(iter_scene_fbp_rigs(scene, fallback=True)) if scene else ()
    for rig in rigs:
        rig_name = _safe_name(getattr(rig, "name", ""), "<layer>")
        media = _rig_media_records(rig)
        memory_bytes = sum(
            int(record.get("estimated_bytes", 0) or 0) for record in media
        )
        layer_media_sum += memory_bytes
        for record in media:
            unique_media.setdefault(tuple(record["key"]), record)
        layer_effects = _effect_records(rig)
        effect_score = sum(
            float(effect.get("cost_score", 0.0) or 0.0)
            for effect in layer_effects
        )
        observed_ms = sum(
            float(effect.get("observed_ms", 0.0) or 0.0)
            for effect in layer_effects
        )
        node_count = sum(
            int(effect.get("node_count", 0) or 0)
            for effect in layer_effects
        )
        heavy_count = sum(
            1
            for effect in layer_effects
            if effect.get("tier") in {"HEAVY", "VERY_HEAVY"}
        )
        layer_record = {
            "object_name": rig_name,
            "backend": _safe_name(fbp_layer_backend_type(rig), "UNKNOWN"),
            "memory_bytes": int(memory_bytes),
            "media_sources": len(media),
            "effect_count": len(layer_effects),
            "heavy_effects": heavy_count,
            "cost_score": round(effect_score, 3),
            "observed_ms": round(observed_ms, 6),
            "node_count": int(node_count),
            "gp": None,
        }
        layers.append(layer_record)
        for effect in layer_effects:
            effect_record = dict(effect)
            effect_record["object_name"] = rig_name
            effects.append(effect_record)
            guidance.extend(_effect_guidance(rig_name, effect_record))
        if memory_bytes >= 256.0 * _MIB:
            guidance.append(
                _guidance(
                    "WARNING",
                    "LAYER_MEMORY",
                    f"{rig_name} uses about {format_memory(memory_bytes)} of decoded media.",
                    object_name=rig_name,
                    action=(
                        "Use proxies or lower-resolution sources, and release "
                        "inactive managed buffers when they are not needed."
                    ),
                )
            )
        if len(layer_effects) >= 8 or effect_score >= 28.0:
            guidance.append(
                _guidance(
                    "INFO",
                    "DENSE_EFFECT_STACK",
                    f"{rig_name} has {len(layer_effects)} effects with cost score {effect_score:.0f}.",
                    object_name=rig_name,
                    action=(
                        "Bypass nonessential effects during layout and keep "
                        "high-quality evaluation for final review/render."
                    ),
                )
            )

    rig_names = {record["object_name"] for record in layers}
    canvases = (
        tuple(iter_scene_gp_canvases(scene, kind="DRAWING", fallback=True))
        if scene
        else ()
    )
    for canvas in canvases:
        canvas_name = _safe_name(getattr(canvas, "name", ""), "<Grease Pencil>")
        if canvas_name in rig_names:
            continue
        stats = _gp_canvas_stats(canvas)
        layers.append(
            {
                "object_name": canvas_name,
                "backend": "GREASE_PENCIL",
                "memory_bytes": int(stats["estimated_bytes"]),
                "media_sources": 0,
                "effect_count": 0,
                "heavy_effects": 0,
                "cost_score": 0.0,
                "observed_ms": 0.0,
                "node_count": 0,
                "gp": stats,
            }
        )
        if stats["points"] >= 250_000:
            guidance.append(
                _guidance(
                    "WARNING",
                    "GP_POINT_COUNT",
                    f"{canvas_name} contains about {stats['points']:,} Grease Pencil points.",
                    object_name=canvas_name,
                    action=(
                        "Simplify dense drawings or split shots/canvases when "
                        "interactive editing becomes slow."
                    ),
                )
            )

    unique_memory = sum(
        int(record.get("estimated_bytes", 0) or 0)
        for record in unique_media.values()
    ) + sum(
        int(layer["memory_bytes"])
        for layer in layers
        if layer.get("backend") == "GREASE_PENCIL"
    )
    total_observed_ms = sum(
        float(effect.get("observed_ms", 0.0) or 0.0) for effect in effects
    )
    heavy_effects = sum(
        1
        for effect in effects
        if effect.get("tier") in {"HEAVY", "VERY_HEAVY"}
    )
    if unique_memory >= 1.0 * _GIB:
        guidance.append(
            _guidance(
                "WARNING",
                "PROJECT_MEMORY",
                f"Decoded project media is estimated at {format_memory(unique_memory)}.",
                action=(
                    "Prefer proxies for large sequences, reuse shared Image "
                    "datablocks and release inactive managed buffers."
                ),
            )
        )
    if total_observed_ms >= 100.0:
        guidance.append(
            _guidance(
                "WARNING",
                "FRAME_BUDGET",
                f"Observed Geometry Nodes time totals {total_observed_ms:.1f} ms.",
                action=(
                    "Profile the highest timed layers first and reduce their "
                    "viewport density/detail before changing render quality."
                ),
            )
        )
    if len(layers) >= 100:
        guidance.append(
            _guidance(
                "INFO",
                "LAYER_COUNT",
                f"The scene contains {len(layers)} Frame By Plane layers.",
                action=(
                    "Use Layer Sets, filters and viewport visibility to keep "
                    "only the current shot section active."
                ),
            )
        )

    # De-duplicate guidance while keeping the most specific stable order.
    unique_guidance = []
    seen_guidance = set()
    for item in guidance:
        key = (
            item["severity"],
            item["code"],
            item["message"],
            item["object_name"],
            item["effect_id"],
        )
        if key in seen_guidance:
            continue
        seen_guidance.add(key)
        unique_guidance.append(item)
    layers.sort(key=lambda item: item["object_name"].casefold())
    effects.sort(
        key=lambda item: (
            item["object_name"].casefold(),
            -_TIER_ORDER.get(item["tier"], 0),
            item["label"].casefold(),
        )
    )
    unique_guidance.sort(
        key=lambda item: (
            {"WARNING": 0, "INFO": 1}.get(item["severity"], 2),
            item["object_name"].casefold(),
            item["code"],
        )
    )
    summary = {
        "layers": len(layers),
        "effects": len(effects),
        "heavy_effects": heavy_effects,
        "unique_media_sources": len(unique_media),
        "unique_memory_bytes": int(unique_memory),
        "layer_memory_sum_bytes": int(layer_media_sum),
        "observed_geometry_ms": round(total_observed_ms, 6),
        "guidance": len(unique_guidance),
    }
    return {
        "schema": PERFORMANCE_REPORT_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "summary": summary,
        "runtime_profile": runtime_profile_snapshot(scene),
        "layers": layers,
        "effects": effects,
        "guidance": unique_guidance,
        "methodology": {
            "memory": (
                "Estimated decoded pixel/Grease Pencil memory; file size, GPU "
                "mipmaps, caches and allocator overhead are not included."
            ),
            "effect_cost": (
                "Registry Light/Medium/Heavy classification converted to a "
                "comparison score, not elapsed time."
            ),
            "observed_timing": (
                "Blender Modifier.execution_time from the latest evaluated "
                "Geometry Nodes state; zero means unavailable/not evaluated."
            ),
            "runtime_profile": (
                "Local process counters only. Detailed handler timing is sampled "
                "only while Developer/Profile mode or Profile 120 Frames is active."
            ),
        },
    }


def performance_report_text(report):
    summary = dict((report or {}).get("summary", {}) or {})
    lines = [
        "Frame By Plane — Performance Dashboard",
        f"Schema: {int((report or {}).get('schema', 0) or 0)}",
        f"Generated: {_safe_name((report or {}).get('generated_at', ''))}",
        "",
        "Summary",
        f"- Layers: {int(summary.get('layers', 0) or 0)}",
        f"- Effects: {int(summary.get('effects', 0) or 0)}",
        f"- Heavy effects: {int(summary.get('heavy_effects', 0) or 0)}",
        (
            "- Estimated decoded memory: "
            + format_memory(summary.get("unique_memory_bytes", 0))
        ),
        (
            "- Observed Geometry Nodes: "
            f"{float(summary.get('observed_geometry_ms', 0.0) or 0.0):.2f} ms"
        ),
        "",
        "Layers",
    ]
    for layer in (report or {}).get("layers", ()) or ():
        lines.append(
            "- {name} [{backend}] · {memory} · {effects} effect(s) · "
            "score {score:.0f} · observed {ms:.2f} ms".format(
                name=layer.get("object_name", "<layer>"),
                backend=layer.get("backend", "UNKNOWN"),
                memory=format_memory(layer.get("memory_bytes", 0)),
                effects=int(layer.get("effect_count", 0) or 0),
                score=float(layer.get("cost_score", 0.0) or 0.0),
                ms=float(layer.get("observed_ms", 0.0) or 0.0),
            )
        )
    lines.extend(("", "Effects"))
    for effect in (report or {}).get("effects", ()) or ():
        timing = (
            f"{float(effect.get('observed_ms', 0.0) or 0.0):.2f} ms"
            if effect.get("has_observed_timing")
            else "not observed"
        )
        lines.append(
            "- {layer} / {label} · {tier} · {nodes} nodes · {timing}".format(
                layer=effect.get("object_name", "<layer>"),
                label=effect.get("label", effect.get("effect_id", "Effect")),
                tier=effect.get("tier", "USER").replace("_", " ").title(),
                nodes=int(effect.get("node_count", 0) or 0),
                timing=timing,
            )
        )
    lines.extend(("", "Optimization guidance"))
    guidance = tuple((report or {}).get("guidance", ()) or ())
    if not guidance:
        lines.append("- No current bottleneck guidance.")
    for item in guidance:
        location = " / ".join(
            value
            for value in (
                item.get("object_name", ""),
                item.get("effect_id", ""),
            )
            if value
        )
        prefix = f" [{location}]" if location else ""
        lines.append(
            f"- {item.get('severity', 'INFO')} {item.get('code', 'PERFORMANCE')}"
            f"{prefix}: {item.get('message', '')}"
        )
        if item.get("action"):
            lines.append(f"  Suggestion: {item['action']}")
    runtime_profile = dict((report or {}).get("runtime_profile", {}) or {})
    handler = dict(runtime_profile.get("effect_handler", {}) or {})
    scheduler = dict(runtime_profile.get("scheduler", {}) or {})
    icons = dict((runtime_profile.get("ui", {}) or {}).get("icons", {}) or {})
    lines.extend((
        "",
        "Local runtime profile",
        f"- Developer/Profile enabled: {bool(runtime_profile.get('enabled', False))}",
        (
            "- Effect handler: {avg:.4f} ms avg · {p95:.4f} ms p95 · "
            "{maximum:.4f} ms max · {samples} sample(s)"
        ).format(
            avg=float(handler.get("avg_ms", 0.0) or 0.0),
            p95=float(handler.get("p95_ms", 0.0) or 0.0),
            maximum=float(handler.get("max_ms", 0.0) or 0.0),
            samples=int(handler.get("timed_samples", 0) or 0),
        ),
        (
            "- Scheduler: {pending} pending · {executed} executed · "
            "{coalesced} coalesced · {avg:.4f} ms/task"
        ).format(
            pending=int(scheduler.get("pending", 0) or 0),
            executed=int(scheduler.get("executed", 0) or 0),
            coalesced=int(scheduler.get("coalesced", 0) or 0),
            avg=float(scheduler.get("average_task_duration_ms", 0.0) or 0.0),
        ),
        (
            "- Icons: {loads} preview load(s) · {hits} cache hit(s) · "
            "{checks} filesystem check(s)"
        ).format(
            loads=int(icons.get("preview_loads", 0) or 0),
            hits=int(icons.get("cache_hits", 0) or 0),
            checks=int(icons.get("filesystem_checks", 0) or 0),
        ),
    ))
    frame_profile = dict((report or {}).get("frame_profile", {}) or {})
    if frame_profile:
        frame_timing = dict(frame_profile.get("frame_evaluation", {}) or {})
        instrumentation = dict(frame_profile.get("instrumentation", {}) or {})
        memory = dict(frame_profile.get("memory", {}) or {})
        lines.extend((
            "",
            "Profile 120 Frames",
            f"- Context: {frame_profile.get('profile_context', 'PLAYBACK')}",
            (
                "- Frame evaluation: {avg:.3f} ms avg · {p50:.3f} ms p50 · "
                "{p95:.3f} ms p95 · {maximum:.3f} ms max"
            ).format(
                avg=float(frame_timing.get("avg_ms", 0.0) or 0.0),
                p50=float(frame_timing.get("p50_ms", 0.0) or 0.0),
                p95=float(frame_timing.get("p95_ms", 0.0) or 0.0),
                maximum=float(frame_timing.get("max_ms", 0.0) or 0.0),
            ),
            (
                "- Effective FPS: {actual:.2f} · target {target:.2f} · "
                "{missed} frame(s) over budget"
            ).format(
                actual=float(frame_timing.get("effective_fps", 0.0) or 0.0),
                target=float(frame_timing.get("target_fps", 0.0) or 0.0),
                missed=int(frame_timing.get("frames_over_budget", 0) or 0),
            ),
            f"- State restored: {bool(frame_profile.get('state_restored', False))}",
            (
                "- Profiler calibration: {samples} sample(s) · estimated overhead "
                "{overhead:.2f}% · timing tracemalloc {tracing}"
            ).format(
                samples=int(instrumentation.get("calibration_samples", 0) or 0),
                overhead=float(instrumentation.get("estimated_overhead_percent", 0.0) or 0.0),
                tracing="on" if instrumentation.get("timing_tracemalloc", False) else "off",
            ),
            (
                "- Memory: separate {samples}-frame allocation run; never included in timing"
            ).format(samples=int(memory.get("samples", 0) or 0)),
            f"- Limit: {frame_profile.get('contract', '')}",
        ))
    lines.extend(
        (
            "",
            "Methodology / limits",
            f"- {(report or {}).get('methodology', {}).get('memory', '')}",
            f"- {(report or {}).get('methodology', {}).get('effect_cost', '')}",
            f"- {(report or {}).get('methodology', {}).get('observed_timing', '')}",
            f"- {(report or {}).get('methodology', {}).get('runtime_profile', '')}",
        )
    )
    return "\n".join(lines).rstrip() + "\n"


def cached_performance_report(scene):
    key = _scene_key(scene)
    report = _REPORT_CACHE.get(key)
    state = getattr(bpy.context, "window_manager", None)
    try:
        last_run = _safe_name(state.fbp_performance_last_run)
        state_scene_key = _safe_name(state.fbp_performance_scene_key)
    except FBP_DATA_ERRORS:
        last_run = ""
        state_scene_key = ""
    if (
        not report
        or not last_run
        or state_scene_key != str(key)
        or _safe_name(report.get("generated_at", "")) != last_run
    ):
        _REPORT_CACHE.pop(key, None)
        return None
    return report


class FBP_PerformanceRow(PropertyGroup):
    row_type: EnumProperty(
        items=(
            ("LAYER", "Layer", "Layer summary"),
            ("EFFECT", "Effect", "Effect cost"),
            ("GUIDANCE", "Guidance", "Optimization guidance"),
        ),
        default="LAYER",
        options={"SKIP_SAVE"},
    )
    name: StringProperty(default="", options={"SKIP_SAVE"})
    object_name: StringProperty(default="", options={"SKIP_SAVE"})
    effect_id: StringProperty(default="", options={"SKIP_SAVE"})
    severity: StringProperty(default="INFO", options={"SKIP_SAVE"})
    tier: StringProperty(default="", options={"SKIP_SAVE"})
    message: StringProperty(default="", options={"SKIP_SAVE"})
    action: StringProperty(default="", options={"SKIP_SAVE"})
    backend: StringProperty(default="", options={"SKIP_SAVE"})
    memory_bytes: FloatProperty(default=0.0, options={"SKIP_SAVE"})
    cost_score: FloatProperty(default=0.0, options={"SKIP_SAVE"})
    observed_ms: FloatProperty(default=0.0, options={"SKIP_SAVE"})
    node_count: IntProperty(default=0, options={"SKIP_SAVE"})


def _populate_scene_report(scene, report):
    state = getattr(bpy.context, "window_manager", None)
    if state is None:
        raise RuntimeError("No WindowManager is available for dashboard state")
    rows = state.fbp_performance_rows
    rows.clear()
    for layer in report["layers"]:
        row = rows.add()
        row.row_type = "LAYER"
        row.name = layer["object_name"]
        row.object_name = layer["object_name"]
        row.backend = layer["backend"]
        row.memory_bytes = float(layer["memory_bytes"])
        row.cost_score = float(layer["cost_score"])
        row.observed_ms = float(layer["observed_ms"])
        row.node_count = int(layer["node_count"])
        row.message = (
            f"{layer['effect_count']} effect(s), "
            f"{layer['media_sources']} media source(s)"
        )
    for effect in report["effects"]:
        row = rows.add()
        row.row_type = "EFFECT"
        row.name = effect["label"]
        row.object_name = effect["object_name"]
        row.effect_id = effect["effect_id"]
        row.tier = effect["tier"]
        row.cost_score = float(effect["cost_score"])
        row.observed_ms = float(effect["observed_ms"])
        row.node_count = int(effect["node_count"])
        row.message = (
            f"{effect['kind'].title()} · "
            f"{effect['category'].replace('_', ' ').title()}"
        )
    for guidance in report["guidance"]:
        row = rows.add()
        row.row_type = "GUIDANCE"
        row.name = guidance["code"].replace("_", " ").title()
        row.object_name = guidance["object_name"]
        row.effect_id = guidance["effect_id"]
        row.severity = guidance["severity"]
        row.message = guidance["message"]
        row.action = guidance["action"]
    summary = report["summary"]
    state.fbp_performance_row_index = 0 if rows else -1
    state.fbp_performance_last_run = report["generated_at"]
    state.fbp_performance_scene_key = str(_scene_key(scene))
    state.fbp_performance_status = (
        "ATTENTION"
        if any(
            item.get("severity") == "WARNING"
            for item in report["guidance"]
        )
        else "GOOD"
    )
    state.fbp_performance_layers = int(summary["layers"])
    state.fbp_performance_effects = int(summary["effects"])
    state.fbp_performance_heavy_effects = int(summary["heavy_effects"])
    state.fbp_performance_memory_mb = (
        float(summary["unique_memory_bytes"]) / _MIB
    )
    state.fbp_performance_observed_ms = float(
        summary["observed_geometry_ms"]
    )
    state.fbp_performance_guidance = int(summary["guidance"])
    if len(_REPORT_CACHE) >= 64 and _scene_key(scene) not in _REPORT_CACHE:
        _REPORT_CACHE.clear()
    _REPORT_CACHE[_scene_key(scene)] = report


def clear_performance_report(scene):
    state = getattr(bpy.context, "window_manager", None)
    try:
        state.fbp_performance_rows.clear()
        state.fbp_performance_row_index = -1
        state.fbp_performance_last_run = ""
        state.fbp_performance_scene_key = ""
        state.fbp_performance_status = "NOT_RUN"
        state.fbp_performance_layers = 0
        state.fbp_performance_effects = 0
        state.fbp_performance_heavy_effects = 0
        state.fbp_performance_memory_mb = 0.0
        state.fbp_performance_observed_ms = 0.0
        state.fbp_performance_guidance = 0
    except FBP_DATA_ERRORS:
        pass
    _REPORT_CACHE.pop(_scene_key(scene), None)


@bpy.app.handlers.persistent
def fbp_performance_load_post(_unused):
    """Discard process-local measurements whenever Blender replaces Main."""
    _REPORT_CACHE.clear()
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        clear_performance_report(scene)


class FBP_OT_ScanPerformance(Operator):
    bl_idname = "fbp.scan_performance"
    bl_label = "Scan Performance"
    bl_description = (
        "Profile Frame By Plane layers without changing scene content or "
        "creating an Undo step"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        report = build_performance_report(context.scene)
        _populate_scene_report(context.scene, report)
        summary = report["summary"]
        self.report(
            {"INFO"},
            (
                f"{summary['layers']} layer(s), {summary['effects']} effect(s), "
                f"{format_memory(summary['unique_memory_bytes'])} estimated"
            ),
        )
        return {"FINISHED"}


class FBP_OT_Profile120Frames(Operator):
    bl_idname = "fbp.profile_120_frames"
    bl_label = "Profile 120 Frames"
    bl_description = (
        "Measure 120 controlled frame evaluations after warm-up, collect local "
        "handler/scheduler/memory counters, then restore the original frame"
    )
    bl_options = {"REGISTER"}

    profile_context: EnumProperty(
        items=(
            ("VIEWPORT", "Viewport", "Frame evaluation plus active View Layer update"),
            ("PLAYBACK", "Playback", "CPU-side frame-change/playback approximation"),
            ("RENDER", "Render", "CPU-side render-frame approximation; no image is rendered"),
        ),
        default="PLAYBACK",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        if getattr(context, "scene", None) is None:
            cls.poll_message_set("An active scene is required")
            return False
        reason = _profile_runtime_block_reason(context, reject_background=True)
        if reason:
            cls.poll_message_set(reason)
            return False
        if tracemalloc.is_tracing():
            cls.poll_message_set("Stop the existing Python allocation trace before profiling")
            return False
        return True

    def execute(self, context):
        try:
            frame_profile = profile_frame_changes(
                context.scene,
                frame_count=120,
                warmup=8,
                profile_context=self.profile_context,
            )
            report = build_performance_report(context.scene)
            report["frame_profile"] = frame_profile
            _populate_scene_report(context.scene, report)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            self.report({"ERROR"}, f"Profile failed; scene state was restored: {exc}")
            return {"CANCELLED"}
        timing = frame_profile["frame_evaluation"]
        self.report(
            {"INFO"},
            (
                f"120 frames: {timing['avg_ms']:.2f} ms avg, "
                f"{timing['p95_ms']:.2f} ms p95, {timing['effective_fps']:.1f} FPS"
            ),
        )
        return {"FINISHED"}


class FBP_OT_ClearPerformance(Operator):
    bl_idname = "fbp.clear_performance"
    bl_label = "Clear Performance Results"
    bl_description = "Clear transient dashboard results without changing project data"
    bl_options = {"REGISTER"}

    def execute(self, context):
        clear_performance_report(context.scene)
        return {"FINISHED"}


class FBP_OT_SelectPerformanceItem(Operator):
    bl_idname = "fbp.select_performance_item"
    bl_label = "Select Profiled Layer"
    bl_description = "Select the layer associated with this dashboard row"
    bl_options = {"REGISTER"}

    object_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        obj = bpy.data.objects.get(_safe_name(self.object_name))
        if obj is None:
            self.report({"WARNING"}, "The profiled object no longer exists")
            return {"CANCELLED"}
        try:
            for selected in tuple(context.selected_objects or ()):
                selected.select_set(False)
            obj.hide_select = False
            obj.select_set(True)
            context.view_layer.objects.active = obj
        except FBP_DATA_ERRORS as exc:
            self.report({"WARNING"}, f"Could not select the layer: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class FBP_OT_CopyPerformanceReport(Operator):
    bl_idname = "fbp.copy_performance_report"
    bl_label = "Copy Performance Report"
    bl_description = "Copy the complete current dashboard report as text"
    bl_options = {"REGISTER"}

    def execute(self, context):
        report = cached_performance_report(context.scene)
        if not report:
            self.report({"WARNING"}, "Run the Performance Dashboard first")
            return {"CANCELLED"}
        context.window_manager.clipboard = performance_report_text(report)
        self.report({"INFO"}, "Performance report copied")
        return {"FINISHED"}


class FBP_OT_OpenPerformanceReport(Operator):
    bl_idname = "fbp.open_performance_report"
    bl_label = "Open Performance Report"
    bl_description = "Create or update a readable Text Editor report"
    bl_options = {"REGISTER"}

    def execute(self, context):
        report = cached_performance_report(context.scene)
        if not report:
            self.report({"WARNING"}, "Run the Performance Dashboard first")
            return {"CANCELLED"}
        text = bpy.data.texts.get(PERFORMANCE_REPORT_TEXT_NAME)
        if text is None:
            text = bpy.data.texts.new(PERFORMANCE_REPORT_TEXT_NAME)
        text.clear()
        text.write(performance_report_text(report))
        area = getattr(context, "area", None)
        if area is not None:
            try:
                area.type = "TEXT_EDITOR"
                area.spaces.active.text = text
            except FBP_DATA_ERRORS:
                pass
        return {"FINISHED"}


class FBP_OT_ExportPerformanceReport(Operator):
    bl_idname = "fbp.export_performance_report"
    bl_label = "Export Performance Report"
    bl_description = "Export the current versioned dashboard snapshot as JSON"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
    filename_ext = ".json"

    def invoke(self, context, _event):
        if not self.filepath:
            self.filepath = bpy.path.abspath(f"//{PERFORMANCE_REPORT_FILENAME}")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        report = cached_performance_report(context.scene)
        if not report:
            self.report({"WARNING"}, "Run the Performance Dashboard first")
            return {"CANCELLED"}
        filepath = bpy.path.ensure_ext(self.filepath, ".json")
        try:
            with open(filepath, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except (OSError, TypeError, ValueError) as exc:
            self.report({"ERROR"}, f"Could not export report: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Exported {os.path.basename(filepath)}")
        return {"FINISHED"}


class FBP_UL_PerformanceRows(UIList):
    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        items = tuple(getattr(data, propname, ()) or ())
        flags = []
        search = _safe_name(
            getattr(data, "fbp_performance_search", "")
        ).casefold()
        scene = getattr(context, "scene", None)
        header_search = (
            _safe_name(
                scene.get("fbp_uilist_filter_performance_rows", "")
            ).casefold()
            if scene is not None
            else ""
        )
        row_filter = _safe_name(
            getattr(data, "fbp_performance_filter", "ALL"),
            "ALL",
        ).upper()
        for item in items:
            visible = (
                row_filter == "ALL"
                or item.row_type == row_filter
                or (
                    row_filter == "BOTTLENECKS"
                    and (
                        item.severity == "WARNING"
                        or item.tier in {"HEAVY", "VERY_HEAVY"}
                        or item.observed_ms >= 20.0
                    )
                )
            )
            if visible and (search or header_search):
                haystack = " ".join(
                    (
                        item.name,
                        item.object_name,
                        item.effect_id,
                        item.message,
                        item.action,
                    )
                ).casefold()
                visible = (
                    (not search or search in haystack)
                    and (not header_search or header_search in haystack)
                )
            flags.append(self.bitflag_filter_item if visible else 0)

        sort_mode = _safe_name(
            getattr(data, "fbp_performance_sort", "COST"),
            "COST",
        ).upper()
        indices = list(range(len(items)))

        def sort_key(index):
            item = items[index]
            row_rank = {"LAYER": 0, "EFFECT": 1, "GUIDANCE": 2}.get(
                item.row_type,
                3,
            )
            if sort_mode == "MEMORY":
                metric = -float(item.memory_bytes)
            elif sort_mode == "TIME":
                metric = -float(item.observed_ms)
            elif sort_mode == "NAME":
                metric = 0.0
            else:
                metric = -float(item.cost_score)
            return (
                metric,
                row_rank,
                item.object_name.casefold(),
                item.name.casefold(),
            )

        if scene is not None and bool(
            scene.get("fbp_uilist_sort_performance_rows", False)
        ):
            indices.sort(key=lambda index: items[index].name.casefold())
        else:
            indices.sort(key=sort_key)
        if scene is not None and bool(
            scene.get("fbp_uilist_reverse_performance_rows", False)
        ):
            indices.reverse()
        new_order = [0] * len(items)
        for new_index, original_index in enumerate(indices):
            new_order[original_index] = new_index
        return flags, new_order

    def draw_item(
        self, context, layout, data, item, icon,
        active_data, active_propname, index,
    ):
        mark_ui_list_draw()
        row = layout.row(align=True)
        if item.row_type == "LAYER":
            status_icon = "OUTLINER_OB_GREASEPENCIL" if item.backend == "GREASE_PENCIL" else "IMAGE_DATA"
            label = item.name
            primary = format_memory(item.memory_bytes)
            secondary = (
                f"{item.observed_ms:.1f} ms" if item.observed_ms > 0.0
                else f"{item.cost_score:.0f}" if item.cost_score > 0.0
                else ""
            )
            secondary_icon = "TIME" if item.observed_ms > 0.0 else "SHADERFX"
        elif item.row_type == "EFFECT":
            status_icon = "ERROR" if item.tier == "VERY_HEAVY" else "INFO" if item.tier == "HEAVY" else "SHADERFX"
            label = f"↳ {item.name}"
            primary = item.tier.replace("_", " ").title()
            secondary = (
                f"{item.observed_ms:.1f} ms" if item.observed_ms > 0.0
                else f"{item.node_count} nodes" if item.node_count else ""
            )
            secondary_icon = "TIME" if item.observed_ms > 0.0 else "NODETREE"
        else:
            status_icon = "ERROR" if item.severity == "WARNING" else "INFO"
            label = item.name
            primary = item.object_name or ""
            secondary = ""
            secondary_icon = "DOT"
        visible = set(fbp_uilist_visible_columns(context, "PERFORMANCE_ROWS"))
        for key in fbp_uilist_icon_order(context, "PERFORMANCE_ROWS"):
            if key not in visible:
                continue
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(row)
                continue
            if key == "status":
                row.label(text="", icon=status_icon)
            elif key == "label":
                row.label(text=label)
            elif key == "metric_primary" and primary:
                row.label(text=primary)
            elif key == "metric_secondary" and secondary:
                row.label(text=secondary, icon=secondary_icon)


def _active_row(state):
    try:
        rows = state.fbp_performance_rows
        index = int(state.fbp_performance_row_index)
        return rows[index] if 0 <= index < len(rows) else None
    except FBP_DATA_ERRORS:
        return None


def draw_performance_dashboard_ui(layout, context):
    layout = configure_layout(layout)
    scene = context.scene
    state = context.window_manager
    current_report = cached_performance_report(scene)
    profile_controls = layout.row(align=True)
    profile_controls.prop(
        state,
        "fbp_performance_profile_enabled",
        text="Developer/Profile",
        toggle=True,
        icon="CONSOLE",
    )
    profile_controls.prop(state, "fbp_performance_profile_context", text="")
    profile_operator = profile_controls.operator(
        "fbp.profile_120_frames",
        text="Profile 120 Frames",
        icon="PLAY",
    )
    profile_operator.profile_context = state.fbp_performance_profile_context
    actions = layout.row(align=True)
    actions.operator("fbp.scan_performance", text="Scan", icon="TIME")
    report_tools = actions.row(align=True)
    report_tools.enabled = current_report is not None
    report_tools.operator(
        "fbp.open_performance_report",
        text="",
        icon="TEXT",
    )
    report_tools.operator(
        "fbp.copy_performance_report",
        text="",
        icon="COPYDOWN",
    )
    report_tools.operator(
        "fbp.export_performance_report",
        text="",
        icon="EXPORT",
    )
    actions.operator("fbp.clear_performance", text="", icon="X")

    if current_report is None:
        empty_state(
            layout,
            "Run a read-only performance scan",
            "Memory values are estimates; Geometry Nodes timing is observed.",
            icon="TIME",
        )
        return

    summary = layout.box()
    section_header(summary, "Project Cost", icon="TIME")
    first = summary.row(align=True)
    first.label(text=f"{state.fbp_performance_layers} layers", icon="IMAGE_DATA")
    first.label(text=f"{state.fbp_performance_effects} effects", icon="SHADERFX")
    first.label(
        text=format_memory(state.fbp_performance_memory_mb * _MIB),
        icon="DISK_DRIVE",
    )
    second = summary.row(align=True)
    second.label(
        text=f"{state.fbp_performance_heavy_effects} heavy",
        icon="INFO",
    )
    second.label(
        text=f"{state.fbp_performance_observed_ms:.1f} ms GN",
        icon="TIME",
    )
    second.label(
        text=f"{state.fbp_performance_guidance} suggestions",
        icon="LIGHT",
    )

    filters = layout.row(align=True)
    filters.prop(state, "fbp_performance_filter", text="")
    filters.prop(state, "fbp_performance_sort", text="")
    layout.prop(state, "fbp_performance_search", text="", icon="VIEWZOOM")
    rows = state.fbp_performance_rows
    list_box = fbp_draw_uilist_header(
        layout, context, "PERFORMANCE_ROWS"
    )
    list_box.template_list(
        "FBP_UL_PerformanceRows",
        "performance",
        state,
        "fbp_performance_rows",
        state,
        "fbp_performance_row_index",
        rows=max(5, min(9, len(rows))),
    )
    active = _active_row(state)
    if active is not None:
        detail = layout.box()
        if active.row_type == "LAYER":
            section_header(detail, active.name, icon="IMAGE_DATA")
            detail.label(text=f"Backend: {active.backend.replace('_', ' ').title()}")
            detail.label(
                text=f"Estimated decoded memory: {format_memory(active.memory_bytes)}"
            )
            detail.label(
                text=(
                    f"Effect score: {active.cost_score:.0f} · "
                    f"Observed GN: {active.observed_ms:.2f} ms"
                )
            )
        elif active.row_type == "EFFECT":
            section_header(detail, active.name, icon="SHADERFX")
            detail.label(
                text=(
                    f"{active.tier.replace('_', ' ').title()} · "
                    f"score {active.cost_score:.0f} · {active.node_count} nodes"
                )
            )
            detail.label(
                text=(
                    f"Observed GN: {active.observed_ms:.2f} ms"
                    if active.observed_ms > 0.0
                    else "Observed timing unavailable (shader or not evaluated)"
                )
            )
        else:
            section_header(
                detail,
                active.name,
                icon="ERROR" if active.severity == "WARNING" else "INFO",
            )
            for line in _wrap_text(active.message, 58):
                detail.label(text=line)
            if active.action:
                detail.separator(factor=0.25)
                for line_index, line in enumerate(_wrap_text(active.action, 58)):
                    row = detail.row(align=False)
                    row.enabled = False
                    row.label(
                        text=line,
                        icon="LIGHT" if line_index == 0 else "BLANK1",
                    )
        if active.object_name:
            select = detail.operator(
                "fbp.select_performance_item",
                text="Select Layer",
                icon="RESTRICT_SELECT_OFF",
            )
            select.object_name = active.object_name
    hint_row(
        layout,
        "Estimates compare layers; they are not OS/GPU memory accounting.",
        icon="INFO",
    )


def _wrap_text(value, width):
    import textwrap

    text = _safe_name(value)
    return tuple(textwrap.wrap(text, width=max(12, int(width)))) or (text,)


_model_classes = (FBP_PerformanceRow,)
_interactive_classes = (
    FBP_OT_ScanPerformance,
    FBP_OT_Profile120Frames,
    FBP_OT_ClearPerformance,
    FBP_OT_SelectPerformanceItem,
    FBP_OT_CopyPerformanceReport,
    FBP_OT_OpenPerformanceReport,
    FBP_OT_ExportPerformanceReport,
    FBP_UL_PerformanceRows,
)
_registered_classes = globals().get("_registered_classes", [])
if not isinstance(_registered_classes, list):
    _registered_classes = []


def _register_runtime_properties():
    runtime_type = bpy.types.WindowManager
    runtime_type.fbp_performance_profile_enabled = BoolProperty(
        name="Developer/Profile",
        description=(
            "Collect local runtime timings in memory; disabled by default and "
            "never sends data over the network"
        ),
        default=False,
        options={"SKIP_SAVE"},
        update=_profile_toggle_update,
    )
    runtime_type.fbp_performance_profile_context = EnumProperty(
        name="Profile Context",
        items=(
            ("VIEWPORT", "Viewport", "Frame evaluation plus active View Layer update"),
            ("PLAYBACK", "Playback", "CPU-side frame-change/playback approximation"),
            ("RENDER", "Render", "CPU-side render-frame approximation; no image is rendered"),
        ),
        default="PLAYBACK",
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_rows = CollectionProperty(
        type=FBP_PerformanceRow,
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_row_index = IntProperty(
        default=-1,
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_status = EnumProperty(
        items=(
            ("NOT_RUN", "Not Run", "No current scan"),
            ("GOOD", "Good", "No current warnings"),
            ("ATTENTION", "Attention", "Review optimization guidance"),
        ),
        default="NOT_RUN",
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_last_run = StringProperty(
        default="",
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_scene_key = StringProperty(
        default="",
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_filter = EnumProperty(
        items=(
            ("ALL", "All", "Show every row"),
            ("BOTTLENECKS", "Bottlenecks", "Show heavy, timed and warning rows"),
            ("LAYER", "Layers", "Show layer summaries"),
            ("EFFECT", "Effects", "Show effect costs"),
            ("GUIDANCE", "Guidance", "Show optimization guidance"),
        ),
        default="ALL",
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_sort = EnumProperty(
        items=(
            ("COST", "Cost", "Sort by estimated effect cost"),
            ("MEMORY", "Memory", "Sort by estimated decoded memory"),
            ("TIME", "Time", "Sort by observed Geometry Nodes timing"),
            ("NAME", "Name", "Sort alphabetically"),
        ),
        default="COST",
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_search = StringProperty(
        default="",
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_layers = IntProperty(
        default=0,
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_effects = IntProperty(
        default=0,
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_heavy_effects = IntProperty(
        default=0,
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_memory_mb = FloatProperty(
        default=0.0,
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_observed_ms = FloatProperty(
        default=0.0,
        options={"SKIP_SAVE"},
    )
    runtime_type.fbp_performance_guidance = IntProperty(
        default=0,
        options={"SKIP_SAVE"},
    )


_SCENE_PROPERTIES = (
    "fbp_performance_profile_enabled",
    "fbp_performance_profile_context",
    "fbp_performance_rows",
    "fbp_performance_row_index",
    "fbp_performance_status",
    "fbp_performance_last_run",
    "fbp_performance_scene_key",
    "fbp_performance_filter",
    "fbp_performance_sort",
    "fbp_performance_search",
    "fbp_performance_layers",
    "fbp_performance_effects",
    "fbp_performance_heavy_effects",
    "fbp_performance_memory_mb",
    "fbp_performance_observed_ms",
    "fbp_performance_guidance",
)


def register():
    _REPORT_CACHE.clear()
    _set_profile_enabled(False)
    unregister_type_properties(bpy.types.WindowManager, _SCENE_PROPERTIES)
    remove_handlers_by_name(
        bpy.app.handlers.load_post,
        "fbp_performance_load_post",
        module_suffix="performance_dashboard",
    )
    _registered_classes.clear()
    try:
        _registered_classes.extend(register_classes(_model_classes))
        _register_runtime_properties()
        _registered_classes.extend(
            register_interactive_classes(_interactive_classes)
        )
        register_handlers(
            (
                (
                    bpy.app.handlers.load_post,
                    fbp_performance_load_post,
                    "performance_dashboard",
                ),
            )
        )
    except Exception:
        remove_handlers_by_name(
            bpy.app.handlers.load_post,
            "fbp_performance_load_post",
            module_suffix="performance_dashboard",
        )
        unregister_type_properties(bpy.types.WindowManager, _SCENE_PROPERTIES)
        unregister_classes(tuple(_registered_classes))
        _registered_classes.clear()
        raise


def unregister():
    _REPORT_CACHE.clear()
    _set_profile_enabled(False)
    remove_handlers_by_name(
        bpy.app.handlers.load_post,
        "fbp_performance_load_post",
        module_suffix="performance_dashboard",
    )
    unregister_type_properties(bpy.types.WindowManager, _SCENE_PROPERTIES)
    unregister_classes(tuple(_registered_classes))
    _registered_classes.clear()


__all__ = [
    "PERFORMANCE_REPORT_SCHEMA_VERSION",
    "PERFORMANCE_REPORT_TEXT_NAME",
    "build_performance_report",
    "cached_performance_report",
    "clear_performance_report",
    "draw_performance_dashboard_ui",
    "format_memory",
    "performance_report_text",
    "profile_frame_changes",
    "runtime_profile_snapshot",
]
