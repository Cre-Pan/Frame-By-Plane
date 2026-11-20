"""Viewport overlays with many layers, and errors caught in callbacks.

* With 100 layers in a Top view the layer names are laid out quickly, never
  overlap, and are cached: a second redraw or a mouse move reuses them until
  the scene, the frame or the view changes.
* ``spread_label_rects`` separates 200 stacked names fast and keeps them
  centred on where they wanted to be.
* ``fbp_guarded`` keeps a failing draw callback or handler running, records
  the error once with its traceback, counts the repeats, and Project Doctor
  lists it under "Runtime messages".

Run with Blender 5.2 or 5.3:
    blender -b --factory-startup --python-exit-code 1 \
        --python frame_by_plane/tests/overlay_performance_regression.py
"""

import importlib
import math
import os
import statistics
import sys
import tempfile
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Matrix


INSTALLED_PACKAGE = os.environ.get("FBP_TEST_INSTALLED") == "1"
PACKAGE_NAME = os.environ.get(
    "FBP_TEST_PACKAGE",
    "bl_ext.fbp_audit.frame_by_plane" if INSTALLED_PACKAGE else "frame_by_plane",
)
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(PACKAGE_NAME)
if not INSTALLED_PACKAGE:
    addon.register()

LAYERS = 100
# Budgets are several times what a laptop needs, so a slow CI runner passes;
# the all-pairs layout this replaces took about 90 ms for 100 names.
LAYOUT_BUDGET_MS = 40.0
CACHED_BUDGET_MS = 1.0
SPREAD_BUDGET_MS = 60.0


def write_drawing(path, width=48, height=24):
    image = bpy.data.images.new(path.stem, width=width, height=height, alpha=True)
    try:
        pixels = [0.0] * (width * height * 4)
        for y in range(4, height - 4):
            for x in range(6, width - 6):
                index = (y * width + x) * 4
                pixels[index:index + 4] = (0.2, 0.5, 0.9, 1.0)
        image.pixels.foreach_set(pixels)
        image.filepath_raw = str(path)
        image.file_format = 'PNG'
        image.save()
    finally:
        bpy.data.images.remove(image)


class FakeRegion:
    def __init__(self, width, height):
        self.width, self.height = width, height

    def as_pointer(self):
        return id(self)


def top_view(points, width, height):
    """``region_data`` of an orthographic Top view framing ``points``."""
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    center_x, center_y = (min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5
    half = max(max(xs) - min(xs), (max(ys) - min(ys)) * width / height) * 0.6 + 1.0
    view = Matrix.Translation((-center_x, -center_y, -100.0))
    window = Matrix((
        (1.0 / half, 0.0, 0.0, 0.0),
        (0.0, width / (height * half), 0.0, 0.0),
        (0.0, 0.0, -0.001, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    ))
    return SimpleNamespace(perspective_matrix=window @ view, is_orthographic_side_view=True)


def overlaps(first, second, gap):
    return not (
        first[2] + gap <= second[0] + 1.0e-4 or second[2] + gap <= first[0] + 1.0e-4
        or first[3] + gap <= second[1] + 1.0e-4 or second[3] + gap <= first[1] + 1.0e-4
    )


def timed_ms(function, repeat=5):
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        function()
        samples.append((time.perf_counter() - start) * 1000.0)
    return statistics.median(samples)


try:
    overlay = importlib.import_module(f"{PACKAGE_NAME}.handle_overlay")
    runtime = importlib.import_module(f"{PACKAGE_NAME}.runtime")
    project_health = importlib.import_module(f"{PACKAGE_NAME}.project_health")
    operator_import = importlib.import_module(f"{PACKAGE_NAME}.operator_import")
    for operator_class in (operator_import.FBP_OT_ImportSequence, operator_import.FBP_OT_GenerateMultiplane):
        if getattr(bpy.types, operator_class.__name__, None) is None:
            bpy.utils.register_class(operator_class)

    # --- 1. 100 layers --------------------------------------------------------
    workdir = Path(tempfile.mkdtemp(prefix="fbp_overlay_perf_"))
    rows = []
    for index in range(LAYERS):
        write_drawing(workdir / f"layer_{index:03d}.png")
        rows.append((f"Layer {index:03d}", "", str(workdir), [f"layer_{index:03d}.png"], False))
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    scene = bpy.context.scene
    camera = bpy.data.objects.new("Perf Camera", bpy.data.cameras.new("Perf Camera"))
    camera.location = (0.0, -40.0, 0.0)
    camera.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.collection.objects.link(camera)
    scene.camera = camera
    assert operator_import._fbp_prepare_pending_rows(bpy.context, str(workdir), rows) == LAYERS
    assert 'FINISHED' in bpy.ops.fbp.generate_multiplane('EXEC_DEFAULT', camera_mode='KEEP')
    rigs = [obj for obj in scene.objects if bool(getattr(obj, "is_fbp_control", False))]
    assert len(rigs) == LAYERS, len(rigs)
    bpy.context.view_layer.update()

    region = FakeRegion(1600, 900)
    region_data = top_view([rig.matrix_world.translation for rig in rigs], region.width, region.height)
    context = SimpleNamespace(
        scene=scene,
        view_layer=bpy.context.view_layer,
        visible_objects=[obj for obj in scene.objects if obj.visible_get()],
        active_object=rigs[0],
        space_data=SimpleNamespace(local_view=None, overlay=SimpleNamespace(show_overlays=True)),
        region=region,
        region_data=region_data,
        preferences=bpy.context.preferences,
        evaluated_depsgraph_get=bpy.context.evaluated_depsgraph_get,
    )

    # --- 2. Layout: complete, no overlaps, fast ------------------------------
    def fresh_layout():
        overlay.clear_overlay_caches()
        return overlay.plane_label_layout(context)

    layout = fresh_layout()
    assert len(layout) == LAYERS, len(layout)
    scale = 1.0
    gap = overlay._LABEL_GAP_PX * scale
    rects = [entry[1] for entry in layout]
    for first in range(len(rects)):
        for second in range(first + 1, len(rects)):
            assert not overlaps(rects[first], rects[second], gap * 0.5), (layout[first][0], layout[second][0])
    uncached = timed_ms(fresh_layout)
    assert uncached < LAYOUT_BUDGET_MS, f"layout of {LAYERS} names took {uncached:.1f} ms"

    # --- 3. Cached until the scene, frame or view changes ---------------------
    overlay.clear_overlay_caches()
    first = overlay.plane_label_layout(context)
    cached = timed_ms(lambda: overlay.plane_label_layout(context), repeat=20)
    assert overlay.plane_label_layout(context) is first, "second redraw laid the names out again"
    assert cached < CACHED_BUDGET_MS, f"cached layout took {cached:.2f} ms"
    hover = overlay.plane_label_under_cursor(context, (layout[0][1][0] + 1.0, layout[0][1][1] + 1.0))
    assert hover, "no name under the cursor on a label"

    moved = rigs[5]
    before = {entry[0]: entry[1] for entry in first}[moved.name]
    moved.location.x += 3.0
    bpy.context.view_layer.update()
    assert overlay.plane_label_layout(context) is first, "cache must hold until the scene stamp changes"
    runtime.fbp_bump_scene_stamp()
    after = {entry[0]: entry[1] for entry in overlay.plane_label_layout(context)}[moved.name]
    assert abs(after[0] - before[0]) > 1.0, ("moved layer kept its old name position", before, after)

    stamp = runtime.fbp_scene_stamp()
    region.width = 1200  # a resized view lays out again
    resized = overlay.plane_label_layout(context)
    assert resized is not first and runtime.fbp_scene_stamp() == stamp

    # --- 4. Spreading many stacked names --------------------------------------
    stacked = [(0.0, 100.0 + (index % 7) * 0.5, 80.0, 115.0 + (index % 7) * 0.5) for index in range(200)]
    start = time.perf_counter()
    spread = overlay.spread_label_rects(stacked, axis=1, gap=2.0)
    spread_ms = (time.perf_counter() - start) * 1000.0
    ordered = sorted(spread, key=lambda rect: rect[1])
    for lower, upper in zip(ordered, ordered[1:]):
        assert upper[1] >= lower[3] + 2.0 - 1.0e-3, (lower, upper)
    wanted_mid = sum(rect[1] + rect[3] for rect in stacked) / len(stacked)
    spread_mid = sum(rect[1] + rect[3] for rect in spread) / len(spread)
    assert abs(wanted_mid - spread_mid) < 1.0, ("names drifted to one side", wanted_mid, spread_mid)
    assert spread_ms < SPREAD_BUDGET_MS, f"spreading 200 names took {spread_ms:.1f} ms"

    # --- 5. Errors in callbacks are recorded, not lost ------------------------
    # Nothing guarded failed while the layers were built and drawn above.
    assert not runtime.fbp_callback_failures(), runtime.fbp_callback_failures()
    runtime.fbp_clear_diagnostics()
    calls = []

    @bpy.app.handlers.persistent
    @runtime.fbp_guarded("test.failing_draw")
    def failing_draw():
        calls.append(1)
        raise ValueError("broken overlay")

    assert getattr(failing_draw, "__name__", "") == "failing_draw"
    for _ in range(5):
        assert failing_draw() is None
    assert len(calls) == 5
    failures = runtime.fbp_callback_failures()
    assert failures["test.failing_draw"]["count"] == 5, failures
    logged = [record for record in runtime.fbp_recent_diagnostics() if record["event"] == "test.failing_draw"]
    assert len(logged) == 1 and "broken overlay" in logged[0]["traceback"], logged
    lines = project_health.runtime_message_lines()
    text = "\n".join(lines)
    assert "Runtime messages (this session)" in text and "failed 5 time(s)" in text, text
    assert "ValueError: broken overlay" in text, text
    runtime.fbp_clear_diagnostics()
    assert project_health.runtime_message_lines()[-1] == "- None"

    print(
        f"FBPTEST overlay performance: PASS (layout {uncached:.1f} ms, cached {cached:.3f} ms, "
        f"spread {spread_ms:.1f} ms)"
    )
except Exception:
    traceback.print_exc()
    sys.exit(1)
