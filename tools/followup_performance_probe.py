from __future__ import annotations

import importlib
import importlib.util
import json
import os
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

import bpy


SOURCE = Path(os.environ["FBP_TEST_SOURCE"]).resolve()
REPORT = Path(os.environ["FBP_PERF_REPORT"]).resolve()
PACKAGE = "frame_by_plane"


def load_addon():
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        SOURCE / "__init__.py",
        submodule_search_locations=[str(SOURCE)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load add-on from {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    module.register()
    return module


def timing_summary(samples):
    ordered = sorted(float(value) for value in samples)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return {
        "samples": len(ordered),
        "avg_ms": statistics.fmean(ordered),
        "median_ms": statistics.median(ordered),
        "p95_ms": ordered[p95_index],
        "max_ms": ordered[-1],
    }


def independent_frame_timing(scene, *, frames=240, warmup=12):
    if tracemalloc.is_tracing():
        tracemalloc.stop()
    scene.frame_start = 1
    scene.frame_end = 120
    original = scene.frame_current
    try:
        for offset in range(warmup):
            scene.frame_set(1 + (offset % 120))
        samples = []
        for offset in range(frames):
            started = time.perf_counter()
            scene.frame_set(1 + (offset % 120))
            samples.append((time.perf_counter() - started) * 1000.0)
        return timing_summary(samples)
    finally:
        scene.frame_set(original)


def timed(callable_, *, repeats=7):
    samples = []
    for _index in range(repeats):
        started = time.perf_counter()
        callable_()
        samples.append((time.perf_counter() - started) * 1000.0)
    return timing_summary(samples)


def generation_preparation_scaling(scene):
    operator_import = importlib.import_module(f"{PACKAGE}.operator_import")
    try:
        coordinator = importlib.import_module(f"{PACKAGE}.generation_transaction")
    except ImportError:
        coordinator = None

    rows = []
    created = 0
    for target in (1_000, 10_000, 100_000):
        while created < target:
            # Empty Mesh IDs are intentionally used instead of Materials:
            # Blender's unique Material naming becomes quadratic at this
            # cardinality and would measure fixture construction, not the
            # transaction preparation under audit.
            bpy.data.meshes.new(f"__FBP_SCALE_{created:06d}")
            created += 1
        row = {
            "global_unrelated_mesh_datablocks": target,
            "legacy_global_snapshot": timed(
                lambda: operator_import._fbp_multiplane_runtime_snapshot(bpy.context),
                repeats=5,
            ),
        }
        if coordinator is not None:
            def acquire_and_retire():
                owner, refusal = coordinator.acquire_generation(
                    bpy.context,
                    operator_id="fbp.performance_probe",
                    mode="Performance probe",
                )
                if owner is None:
                    raise RuntimeError(refusal)
                result = coordinator.retire_active_generation(
                    bpy.context,
                    reason="performance probe",
                    rollback=True,
                )
                if not result.get("verified", False):
                    raise RuntimeError(str(result))

            row["owned_journal_acquire_and_retire"] = timed(
                acquire_and_retire,
                repeats=5,
            )
        rows.append(row)
    return rows


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    module = load_addon()
    scene = bpy.context.scene
    dashboard = importlib.import_module(f"{PACKAGE}.performance_dashboard")
    payload = {
        "source": str(SOURCE),
        "git_label": os.environ.get("FBP_PERF_LABEL", "unknown"),
        "blender": bpy.app.version_string,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "default_profile_env": os.environ.get("FBP_PROFILE", ""),
        "independent_empty_scene_frame_set_240": independent_frame_timing(scene),
        "dashboard_profile_120": dashboard.profile_frame_changes(
            scene,
            frame_count=120,
            warmup=8,
            profile_context="PLAYBACK",
        ),
        "generation_preparation_scaling": generation_preparation_scaling(scene),
    }
    module.unregister()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"FBP_PERF_REPORT={REPORT}")
    bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
