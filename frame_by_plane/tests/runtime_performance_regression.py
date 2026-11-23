"""Hot paths found by profiling a 100-layer project stay fast and correct.

* ``get_primary_fbp_collection`` answers from the hinted collection without
  ``users_collection`` and still matches the full lookup, also after a layer
  is moved to another collection by hand.
* A group row reads its members once per refresh, and a refresh that changes
  nothing writes nothing.
* Several imports in a row frame the view once, with every imported layer.
* The Alpha Outline cache keeps more than 64 layers and several drawings of
  one layer, least recently drawn first out.
* ``region_grid``, ``_marching_squares_loops`` and ``_source_index_resolver``
  give the same results as the per-cell and per-call code they replace.
* Importing a 600-frame sequence stays within a generous time budget.
* NumPy is not imported by loading the add-on, and the lazy proxy keeps each
  NumPy name after its first use.

Run with Blender 5.2 or 5.3:
    blender -b --factory-startup --python-exit-code 1 \
        --python frame_by_plane/tests/runtime_performance_regression.py
"""

import importlib
import os
import random
import struct
import sys
import tempfile
import time
import traceback
import zlib
from pathlib import Path

NUMPY_LOADED_BEFORE = "numpy" in sys.modules

import bpy


INSTALLED_PACKAGE = os.environ.get("FBP_TEST_INSTALLED") == "1"
PACKAGE_NAME = os.environ.get(
    "FBP_TEST_PACKAGE",
    "bl_ext.fbp_audit.frame_by_plane" if INSTALLED_PACKAGE else "frame_by_plane",
)
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(PACKAGE_NAME)
NUMPY_LOADED_BY_ADDON = (not NUMPY_LOADED_BEFORE) and "numpy" in sys.modules
if not INSTALLED_PACKAGE:
    addon.register()

# The base build takes about 0.8 s on a laptop; the budget leaves room for a
# slow CI runner and still fails if the pathlib-per-frame path comes back.
IMPORT_600_BUDGET_MS = 2500.0


def module(name):
    return importlib.import_module(f"{PACKAGE_NAME}.{name}")


def write_png(path, width, height, rgba):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgba) * width
    Path(path).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def import_sequence(directory, names):
    # The import operator is registered on demand by the File Browser entry.
    operator_class = module("operator_import").FBP_OT_ImportSequence
    if not getattr(operator_class, "is_registered", False):
        bpy.utils.register_class(operator_class)
    result = bpy.ops.fbp.import_sequence(
        'EXEC_DEFAULT',
        synchronous=True,
        filepath=str(directory / names[0]),
        directory=str(directory),
        files=[{"name": name} for name in names],
        media_filter='IMAGES',
    )
    assert result == {'FINISHED'}, result


def rigs():
    return [obj for obj in bpy.context.scene.objects if getattr(obj, "is_fbp_control", False)]


def check_numpy_is_lazy():
    if NUMPY_LOADED_BEFORE:
        print("numpy was already loaded by Blender; lazy import not checked")
        return
    assert not NUMPY_LOADED_BY_ADDON, "loading the add-on imported numpy"
    lazy = module("lazy_numpy").np
    assert lazy.asarray([1, 2]).sum() == 3
    import numpy
    assert vars(lazy).get("asarray") is numpy.asarray, "lazy numpy did not keep the name"


def check_primary_collection(work):
    layers = module("layers")
    folder = work / "primary"
    folder.mkdir()
    write_png(folder / "p_0001.png", 8, 8, (200, 10, 10, 255))
    import_sequence(folder, ["p_0001.png"])
    rig = rigs()[-1]

    def full_lookup(obj):
        users = tuple(obj.users_collection)
        hint = bpy.data.collections.get(str(obj.fbp_collection_name or ""))
        if hint is not None and hint in users:
            return hint
        for collection in users:
            if getattr(collection, "is_fbp_collection", False):
                return collection
        return users[0] if users else None

    assert layers.get_primary_fbp_collection(rig) == full_lookup(rig)
    # Move the layer by hand: the hint goes stale and the fallback answers.
    hinted = bpy.data.collections.get(str(rig.fbp_collection_name or ""))
    other = bpy.data.collections.new("FBP Perf Moved")
    bpy.context.scene.collection.children.link(other)
    other.objects.link(rig)
    if hinted is not None:
        hinted.objects.unlink(rig)
    assert layers.get_primary_fbp_collection(rig) == full_lookup(rig) == other
    other.objects.unlink(rig)
    (hinted or bpy.context.scene.collection).objects.link(rig)
    assert layers.get_primary_fbp_collection(rig) == full_lookup(rig)


def check_members_memo():
    layers = module("layers")
    ui_layout = module("ui_layout")
    collection = layers.get_primary_fbp_collection(rigs()[-1])
    assert collection is not None
    calls = {"rigs": 0}
    original = layers._collection_rigs_for_ui_uncached

    def counting(coll):
        calls["rigs"] += 1
        return original(coll)

    layers._collection_rigs_for_ui_uncached = counting
    try:
        values = ui_layout._fbp_collection_row_values(collection, bpy.context)
        assert calls["rigs"] == 1, calls
        assert layers._FBP_MEMBERS_MEMO is None
        # Outside a pass every call resolves again.
        layers._collection_rigs_for_ui(collection)
        layers._collection_rigs_for_ui(collection)
        assert calls["rigs"] == 3, calls
    finally:
        layers._collection_rigs_for_ui_uncached = original
    assert len(values) == len(ui_layout._FBP_COLLECTION_ROW_FIELDS)

    class Row:
        writes = 0

        def __setattr__(self, name, value):
            Row.writes += 1
            object.__setattr__(self, name, value)

    row = Row()
    for (name, _default), value in zip(ui_layout._FBP_COLLECTION_ROW_FIELDS, values):
        object.__setattr__(row, name, value)
    assert ui_layout._fbp_write_collection_row(row, values) is False
    assert Row.writes == 0
    changed = list(values)
    changed[1] = not changed[1]
    assert ui_layout._fbp_write_collection_row(row, tuple(changed)) is True
    assert Row.writes == 1


def check_framing_is_coalesced(work):
    operator_common = module("operator_common")
    safe_tasks = module("safe_tasks")
    # Background Blender runs no timers: drop what earlier imports queued.
    operator_common._FBP_PENDING_FRAME_RIGS.clear()
    framed = []
    original = operator_common._fbp_frame_generated_planes

    def recording(scene_key, rig_names, **_kwargs):
        framed.append(tuple(rig_names))

    operator_common._fbp_frame_generated_planes = recording
    scheduled = {}
    original_schedule = safe_tasks.schedule_once

    def capture(name, callback, **kwargs):
        scheduled[name] = callback
        return True

    safe_tasks.schedule_once = capture
    try:
        context = bpy.context
        for index in range(3):
            report = {"status": "SUCCESS", "generated_rigs": [f"Perf Rig {index}"]}
            operator_common._fbp_finish_generation_ui(context, report, show_popup=False)
        framing = [name for name in scheduled if "frame_generated_planes" in name]
        assert len(framing) == 1, framing
        scheduled[framing[0]]()
    finally:
        safe_tasks.schedule_once = original_schedule
        operator_common._fbp_frame_generated_planes = original
    assert framed == [("Perf Rig 0", "Perf Rig 1", "Perf Rig 2")], framed
    assert not operator_common._FBP_PENDING_FRAME_RIGS


def check_alpha_outline_cache():
    layer_cage = module("layer_cage")
    builder = module("builder")
    calls = []
    original_geometry = builder._fbp_alpha_rig_geometry
    original_source = builder.fbp_rig_alpha_frame_source
    current = {"source": "a.png"}

    def geometry(rig, margin):
        calls.append((rig.as_pointer(), current["source"]))
        return ([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)], [(0, 1), (1, 2)])

    class FakeRig:
        def __init__(self, pointer):
            self.pointer = pointer
            self.fbp_rig_shape_alpha_style = "SMOOTH"
            self.fbp_rig_shape_alpha_detail = 64

        def as_pointer(self):
            return self.pointer

    builder._fbp_alpha_rig_geometry = geometry
    builder.fbp_rig_alpha_frame_source = lambda rig, *a, **k: current["source"]
    rig_style = module("rig_style")
    original_expand, original_shrink = rig_style.expand_margin, rig_style.shrink_factor
    rig_style.expand_margin = lambda rig: 0.0
    rig_style.shrink_factor = lambda rig: 1.0
    layer_cage._ALPHA_OUTLINES.clear()
    layer_cage._ALPHA_LAST_OUTLINE.clear()
    try:
        from mathutils import Vector
        center = Vector((0.0, 0.0, 0.0))
        fakes = [FakeRig(10_000 + index) for index in range(150)]
        for rig in fakes:
            layer_cage._alpha_box_segments(rig, center)
        first_pass = len(calls)
        for rig in fakes:
            layer_cage._alpha_box_segments(rig, center)
        assert len(calls) == first_pass == 150, (first_pass, len(calls))
        # Scrubbing an Alpha Follow layer back and forth reuses each drawing.
        for source in ("a.png", "b.png", "c.png", "a.png", "b.png", "c.png"):
            current["source"] = source
            layer_cage._alpha_box_segments(fakes[0], center)
        assert len(calls) == 152, len(calls)
        # Least recently drawn first out.
        limit = layer_cage._ALPHA_OUTLINE_LIMIT
        current["source"] = "z.png"
        for index in range(limit + 5):
            layer_cage._alpha_box_segments(FakeRig(90_000 + index), center)
        assert len(layer_cage._ALPHA_OUTLINES) == limit
    finally:
        builder._fbp_alpha_rig_geometry = original_geometry
        builder.fbp_rig_alpha_frame_source = original_source
        rig_style.expand_margin, rig_style.shrink_factor = original_expand, original_shrink
        layer_cage._ALPHA_OUTLINES.clear()
        layer_cage._ALPHA_LAST_OUTLINE.clear()


def check_region_grid():
    import numpy as np
    shape = module("rig_alpha_shape")

    def per_cell(region, cells):
        rh, rw = region.shape
        longest = max(rw, rh)
        gw = max(1, int(round(rw * cells / float(longest))))
        gh = max(1, int(round(rh * cells / float(longest))))
        col_edges = np.linspace(0, rw, gw + 1).astype(int)
        row_edges = np.linspace(0, rh, gh + 1).astype(int)
        grid = np.zeros((gh, gw), dtype=bool)
        for gy in range(gh):
            ra, rb = row_edges[gy], max(row_edges[gy] + 1, row_edges[gy + 1])
            for gx in range(gw):
                ca, cb = col_edges[gx], max(col_edges[gx] + 1, col_edges[gx + 1])
                grid[gy, gx] = bool(region[ra:rb, ca:cb].any())
        return grid

    generator = np.random.default_rng(7)
    for _attempt in range(300):
        height, width = (int(value) for value in generator.integers(20, 300, 2))
        mask = generator.random((height, width)) < generator.random() * 0.05
        mask[height // 2, width // 2] = True
        union = shape.AlphaUnion(mask, width, height, (0, 0, width, height), True)
        cells = int(generator.integers(4, 64))
        grid = shape.region_grid(union, (0.0, 1.0, 0.0, 1.0), cells=cells)
        if max(height, width) <= cells:
            continue
        expected = per_cell(mask, cells)
        assert grid.shape == expected.shape and (grid == expected).all()


def _reference_marching_squares(field, iso=0.5):
    """The cell-by-cell contour tracer that the vectorised version replaced."""
    import numpy as np
    inside = field >= iso

    def crossing(edge):
        kind, r, c = edge
        if kind == "h":
            a, b = field[r, c], field[r, c + 1]
            t = 0.5 if a == b else (iso - a) / (b - a)
            return (c + t, float(r))
        a, b = field[r, c], field[r + 1, c]
        t = 0.5 if a == b else (iso - a) / (b - a)
        return (float(c), r + t)

    links = {}

    def link(a, b):
        links.setdefault(a, []).append(b)
        links.setdefault(b, []).append(a)

    codes = (
        (inside[:-1, :-1].astype(np.int8) << 3)
        | (inside[:-1, 1:].astype(np.int8) << 2)
        | (inside[1:, 1:].astype(np.int8) << 1)
        | inside[1:, :-1].astype(np.int8)
    )
    for r, c in zip(*np.nonzero((codes != 0) & (codes != 15))):
        r, c = int(r), int(c)
        code = int(codes[r, c])
        tl, tr = bool(code & 8), bool(code & 4)
        br, bl = bool(code & 2), bool(code & 1)
        top, bottom = ("h", r, c), ("h", r + 1, c)
        left, right = ("v", r, c), ("v", r, c + 1)
        if code in (5, 10):
            centre = (field[r, c] + field[r, c + 1] + field[r + 1, c] + field[r + 1, c + 1]) / 4.0
            if (code == 5) == bool(centre >= iso):
                link(top, left)
                link(bottom, right)
            else:
                link(top, right)
                link(bottom, left)
            continue
        crossed = [edge for edge, hit in ((top, tl != tr), (right, tr != br), (bottom, bl != br), (left, tl != bl)) if hit]
        if len(crossed) == 2:
            link(crossed[0], crossed[1])

    loops = []
    seen = set()
    for start in links:
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        prev, current = None, start
        while True:
            nxt = None
            for option in links[current]:
                if option != prev and option not in seen:
                    nxt = option
                    break
            if nxt is None:
                break
            seen.add(nxt)
            loop.append(nxt)
            prev, current = current, nxt
        if len(loop) >= 3:
            loops.append([crossing(edge) for edge in loop])
    return [[(float(x), float(y)) for x, y in loop] for loop in loops]


def check_marching_squares():
    import numpy as np
    shape = module("rig_alpha_shape")
    generator = np.random.default_rng(11)
    loops_seen = 0
    for attempt in range(1500):
        height, width = (int(value) for value in generator.integers(1, 40, 2))
        mode = attempt % 4
        if mode == 3:
            field = shape._soften(generator.random((height, width)) > generator.random())
        else:
            field = np.zeros((height + 2, width + 2), dtype=np.float32 if mode == 2 else np.float64)
            if mode == 0:
                field[1:-1, 1:-1] = generator.random((height, width))
            elif mode == 1:
                field[1:-1, 1:-1] = generator.choice([0.0, 0.25, 0.5, 0.75, 1.0], (height, width))
            else:
                field[1:-1, 1:-1] = generator.random((height, width)) > 0.5
        expected = _reference_marching_squares(field)
        loops_seen += len(expected)
        assert shape._marching_squares_loops(field) == expected, f"contours differ on case {attempt}"
    assert loops_seen > 1000, loops_seen
    assert shape._marching_squares_loops(np.zeros((5, 5))) == []


def check_source_index_resolver():
    native = module("native_backend")
    generator = random.Random(11)
    for _attempt in range(1500):
        count = generator.randint(0, 30)
        durations = [generator.randint(0, 4) for _ in range(generator.randint(0, 35))]
        mode = generator.choice(["NONE", "REPEAT", "PINGPONG", None])
        resolve = native._source_index_resolver(count, durations, mode)
        for elapsed in range(-3, 90):
            assert resolve(elapsed) == native._source_index_at_elapsed(
                elapsed, count, durations, mode
            )


def check_timing_write_resets_effect_check():
    native = module("native_backend")
    geometry = module("geometry_nodes")
    geometry._FBP_PRIVATE_IMAGE_SOURCE_SYNC_CACHE[("perf", 1)] = ("signature", 0.0, None)
    original = native._install_frame_offset_keyframes_impl
    native._install_frame_offset_keyframes_impl = lambda *args, **kwargs: True
    try:
        assert native._install_frame_offset_keyframes(None, file_count=2) is True
    finally:
        native._install_frame_offset_keyframes_impl = original
    assert not geometry._FBP_PRIVATE_IMAGE_SOURCE_SYNC_CACHE


def check_effects_on_sequence(work):
    """Image effects on a sequence keep the samples' timing and static offset."""
    geometry = module("geometry_nodes")
    registry = module("effects_registry")
    folder = work / "fx"
    folder.mkdir()
    names = []
    for index in range(6):
        name = f"fx_{index + 1:04d}.png"
        write_png(folder / name, 16, 16, (40 * index, 90, 160, 255))
        names.append(name)
    import_sequence(folder, names)
    rig = rigs()[-1]
    assert geometry.fbp_add_effect(rig, registry.FBP_EFFECT_GAUSSIAN_BLUR)
    material = None
    plane = rig.fbp_plane_target
    for slot in plane.material_slots:
        if slot.material is not None:
            material = slot.material
            break
    assert material is not None
    source = module("effect_shader_routing")._fbp_shader_image_node(material)
    groups = [
        node.node_tree for node in material.node_tree.nodes
        if node.type == 'GROUP' and node.node_tree is not None
        and geometry._fbp_matrix_source_image_nodes(node.node_tree)
    ]
    assert groups, "no private image samples"
    for group in groups:
        for node in geometry._fbp_matrix_source_image_nodes(group):
            assert node.image_user.frame_offset == source.image_user.frame_offset
            curve = geometry._fbp_frame_offset_curve(node)
            if curve is not None:
                assert len(curve.keyframe_points) == len(
                    geometry._fbp_frame_offset_curve(source).keyframe_points
                )


def check_long_import(work):
    folder = work / "long"
    folder.mkdir()
    names = []
    for index in range(600):
        name = f"long_{index + 1:04d}.png"
        write_png(folder / name, 16, 16, (index % 255, 90, 160, 255))
        names.append(name)
    native = module("native_backend")
    assert native._valid_files(str(folder), names) == names
    assert native._valid_files(str(folder), names[:2] + ["missing_0001.png"]) == names[:2]
    absolute = str(folder / names[0])
    assert native._valid_files(str(work), [absolute]) == [absolute]
    started = time.perf_counter()
    import_sequence(folder, names)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    print(f"600-frame import: {elapsed_ms:.0f} ms")
    assert elapsed_ms < IMPORT_600_BUDGET_MS, elapsed_ms
    rig = rigs()[-1]
    assert len(rig.fbp_images) == 600


def main():
    scene = bpy.context.scene
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj)
    with tempfile.TemporaryDirectory(prefix="fbp_runtime_perf_") as temp:
        work = Path(temp)
        checks = (
            ("numpy is lazy", check_numpy_is_lazy),
            ("primary collection", lambda: check_primary_collection(work)),
            ("group row memo", check_members_memo),
            ("framing coalesced", lambda: check_framing_is_coalesced(work)),
            ("alpha outline cache", check_alpha_outline_cache),
            ("region grid", check_region_grid),
            ("marching squares", check_marching_squares),
            ("source index resolver", check_source_index_resolver),
            ("timing write resets effect check", check_timing_write_resets_effect_check),
            ("effects on a sequence", lambda: check_effects_on_sequence(work)),
            ("long import", lambda: check_long_import(work)),
        )
        for label, check in checks:
            check()
            print(f"[OK] {label}")
    print("RUNTIME_PERFORMANCE_REGRESSION_PASS")


try:
    main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
finally:
    if not INSTALLED_PACKAGE:
        try:
            addon.unregister()
        except Exception:
            traceback.print_exc()
