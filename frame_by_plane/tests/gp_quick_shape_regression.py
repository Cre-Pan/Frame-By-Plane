"""Grease Pencil Quick Shape: line, arc, ellipse and rectangle recognition,
Ctrl snapping, point counts, the preferences and the operator behind the
Adjust Last Operation panel.

The live behaviour (rest the pen, line follows the cursor, Shift and Ctrl,
release, Undo/Redo, 10 second window) needs real input events and is checked
in an interactive Blender session.

Run with Blender 5.2 or 5.3:
    blender -b --factory-startup --python-exit-code 1 \
        --python frame_by_plane/tests/gp_quick_shape_regression.py
"""

import importlib
import math
import os
import sys
import traceback
from pathlib import Path

import bpy


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

try:
    quick = importlib.import_module(PACKAGE_NAME + ".gp_quick_shape")

    # 1. A slightly wobbly horizontal stroke is a line.
    wobbly = [(i * 10.0, 3.0 if i % 2 else -3.0) for i in range(21)]
    assert quick.is_straight_path(wobbly)
    # 2. An arc, a hook and a back-and-forth stroke are not.
    arc = [(i * 10.0, 80.0 * math.sin(i / 30.0 * math.pi)) for i in range(31)]
    assert not quick.is_straight_path(arc)
    hook = [(i * 10.0, 0.0) for i in range(21)] + [(200.0 - i * 10.0, 30.0) for i in range(1, 6)]
    assert not quick.is_straight_path(hook)
    back_and_forth = [(i * 10.0, 0.0) for i in range(21)] + [(200.0 - i * 10.0, 0.0) for i in range(1, 11)] + [(100.0 + i * 10.0, 0.0) for i in range(1, 11)]
    assert not quick.is_straight_path(back_and_forth)
    # 3. Too short to be a line.
    assert not quick.is_straight_path([(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)])

    # 4. Ctrl snapping keeps the length and lands on the step.
    for step in (5.0, 15.0, 22.5, 45.0):
        end = quick.snap_screen_angle((0.0, 0.0), (100.0, 4.0), step)
        assert abs(end[1]) < 1.0e-6 and abs(math.hypot(*end) - math.hypot(100.0, 4.0)) < 1.0e-6, (step, end)
        end = quick.snap_screen_angle((10.0, 10.0), (60.0, 58.0), step)
        assert abs(math.degrees(math.atan2(end[1] - 10.0, end[0] - 10.0)) - 45.0) < 1.0e-6, (step, end)
        end = quick.snap_screen_angle((0.0, 0.0), (-3.0, -90.0), step)
        assert abs(end[0]) < 1.0e-6 and end[1] < 0.0, (step, end)

    # 5. Preferences: defaults and validation.
    enabled, hold, snap, precision = quick.quick_shape_settings(bpy.context)
    assert enabled is True
    assert abs(hold - 0.4) < 1.0e-6
    assert snap == 15.0
    assert abs(precision - 0.25) < 1.0e-6
    assert quick.quick_shape_precision_key(bpy.context) == "SHIFT"
    assert quick.DETECTION_WINDOW_SECONDS == 10.0

    # 6. The operator never runs outside Grease Pencil Draw mode.
    assert quick.FBP_OT_GPQuickShapeStroke.bl_idname == "fbp.gp_quick_shape_stroke"

    # 7. Shape recognition: ellipse, rectangle, arc; scribbles stay free hand.
    ellipse_path = [(200.0 + 90.0 * math.cos(a / 40.0 * 2 * math.pi), 200.0 + 60.0 * math.sin(a / 40.0 * 2 * math.pi)) for a in range(41)]
    shape = quick.recognize_shape(ellipse_path)
    assert shape and shape["kind"] == quick.ELLIPSE, shape
    assert abs(shape["rx"] - 90.0) < 3.0 and abs(shape["ry"] - 60.0) < 3.0, shape
    rect_path = []
    for (x0, y0), (x1, y1) in [((0, 0), (120, 0)), ((120, 0), (120, 80)), ((120, 80), (0, 80)), ((0, 80), (0, 0))]:
        rect_path += [(x0 + (x1 - x0) * k / 10.0, y0 + (y1 - y0) * k / 10.0) for k in range(10)]
    rect_path.append((2.0, 2.0))
    shape = quick.recognize_shape(rect_path)
    assert shape and shape["kind"] == quick.RECT, shape
    arc_path = [(100.0 * math.cos(math.pi - a / 30.0 * math.pi), 100.0 * math.sin(math.pi - a / 30.0 * math.pi)) for a in range(31)]
    shape = quick.recognize_shape(arc_path)
    assert shape and shape["kind"] == quick.ARC and abs(shape["rx"] - 100.0) < 1.0 and abs(shape["ry"] - 100.0) < 1.0, shape
    import random as _random
    scribble_rng = _random.Random(11)
    scribble = [(200.0, 200.0)]
    for _i in range(60):
        scribble.append((scribble[-1][0] + scribble_rng.uniform(-25, 30), scribble[-1][1] + scribble_rng.uniform(-30, 30)))
    assert quick.recognize_shape(scribble) is None, quick.recognize_shape(scribble)
    assert quick.recognize_shape(wobbly)["kind"] == quick.LINE

    # 8. Point counts: defaults, wheel steps and limits.
    assert [quick.DEFAULT_POINTS[k] for k in (quick.LINE, quick.ARC, quick.ELLIPSE, quick.RECT)] == [2, 3, 24, 4]
    assert quick.DEFAULT_CURVE_TYPE[quick.ELLIPSE] == "POLY"
    assert quick.clamp_points(quick.RECT, 7) == 8 and quick.clamp_points(quick.RECT, 1) == 4
    assert quick.clamp_points(quick.ELLIPSE, 1) == 3 and quick.clamp_points(quick.LINE, 1) == 2
    assert quick.points_step(quick.RECT) == 4 and quick.points_step(quick.LINE) == 1
    for kind, path in ((quick.LINE, wobbly), (quick.ELLIPSE, ellipse_path), (quick.RECT, rect_path), (quick.ARC, arc_path)):
        shape = quick.recognize_shape(path)
        for count in (quick.DEFAULT_POINTS[kind], quick.DEFAULT_POINTS[kind] + quick.points_step(kind) * 2):
            knots, cyclic, handle_types = quick.shape_knots(shape, count)
            assert len(knots) == count and len(handle_types) == count, (kind, count, len(knots))
            assert cyclic == (kind in (quick.ELLIPSE, quick.RECT))
            aligned = [t == (quick._HANDLE_ALIGN, quick._HANDLE_ALIGN) for t in handle_types]
            if kind == quick.ELLIPSE:
                assert all(aligned)
            elif kind == quick.ARC:
                # Inner points aligned; the two ends have no handles at all.
                assert all(aligned[1:-1])
                assert handle_types[0] == handle_types[-1] == (quick._HANDLE_FREE, quick._HANDLE_FREE)
                assert knots[0][0] == knots[0][1] == knots[0][2]
                assert knots[-1][0] == knots[-1][1] == knots[-1][2]
                # The segments still follow the arc.
                for (_l0, p0, r0), (l1, p1, _r1) in zip(knots, knots[1:]):
                    for j in range(1, 20):
                        q = quick._bezier(p0, r0, l1, p1, j / 20.0)
                        assert quick._ellipse_distance(shape, q) < 0.02 * shape["rx"], (count, q)
            else:
                assert not any(aligned)
    # Ellipse points lie on the ellipse; Ctrl turns it into a circle.
    shape = quick.recognize_shape(ellipse_path)
    circle = quick.transform_shape(shape, 0.0, 1.0, 15.0)
    assert abs(circle["rx"] - circle["ry"]) < 1.0e-9
    for _left, point, _right in quick.shape_knots(circle, 6)[0]:
        assert abs(math.hypot(point[0] - circle["center"][0], point[1] - circle["center"][1]) - circle["rx"]) < 1.0e-6

    # 8b. The shape starts where the stroke started.
    for start_degrees in (0.0, 37.0, 140.0, 255.0):
        for direction in (1.0, -1.0):
            path = []
            for k in range(61):
                a = math.radians(start_degrees) + direction * k / 60.0 * 2.0 * math.pi
                path.append((300.0 + 110.0 * math.cos(a), 250.0 + 70.0 * math.sin(a)))
            shape = quick.recognize_shape(path)
            assert shape["kind"] == quick.ELLIPSE, (start_degrees, shape)
            first = quick.shape_knots(shape, 4)[0][0][1]
            assert math.hypot(first[0] - path[0][0], first[1] - path[0][1]) < 4.0, (start_degrees, direction, first, path[0])
            second = quick.shape_knots(shape, 16)[0][1][1]
            assert math.hypot(second[0] - path[4][0], second[1] - path[4][1]) < 12.0, (start_degrees, direction, second)
    corners = [(0, 0), (120, 0), (120, 80), (0, 80)]
    for first_corner in range(4):
        for direction in (1, -1):
            order = [corners[(first_corner + direction * i) % 4] for i in range(5)]
            path = []
            for (x0, y0), (x1, y1) in zip(order, order[1:]):
                path += [(x0 + (x1 - x0) * k / 10.0, y0 + (y1 - y0) * k / 10.0) for k in range(10)]
            path.append(order[0])
            shape = quick.recognize_shape(path)
            assert shape["kind"] == quick.RECT, shape
            knots = [k[1] for k in quick.shape_knots(shape, 4)[0]]
            assert math.hypot(knots[0][0] - order[0][0], knots[0][1] - order[0][1]) < 2.0, (order, knots)
            assert math.hypot(knots[1][0] - order[1][0], knots[1][1] - order[1][1]) < 2.0, (order, knots)
    # Overshooting where a rectangle closes does not push its side out.
    overshoot = list(rect_path) + [(2.0 - k * 2.0, 1.0) for k in range(1, 6)]
    shape = quick.recognize_shape(overshoot)
    assert shape["kind"] == quick.RECT and abs(shape["rx"] - 60.0) < 2.0 and abs(shape["ry"] - 40.0) < 2.0, shape

    # 8c. Arcs in every direction, with a shaky start, and the Line/Arc choice.
    import random
    rng = random.Random(7)
    for start_degrees in (0.0, 90.0, 180.0, 270.0, 45.0):
        for direction in (1.0, -1.0):
            for sweep_degrees in (70.0, 120.0, 200.0):
                path = []
                for k in range(41):
                    a = math.radians(start_degrees) + direction * math.radians(sweep_degrees) * k / 40.0
                    jitter = rng.uniform(-1.5, 1.5) if 0 < k < 40 else 0.0
                    path.append((400.0 + (120.0 + jitter) * math.cos(a), 300.0 + (120.0 + jitter) * math.sin(a)))
                # Pen landing: a small hook backwards at the start.
                path.insert(1, (path[0][0] - (path[1][0] - path[0][0]) * 0.5, path[0][1] - (path[1][1] - path[0][1]) * 0.5))
                kinds = [s["kind"] for s in quick.recognize_shapes(path)]
                assert kinds and kinds[0] == quick.ARC, (start_degrees, direction, sweep_degrees, kinds)
                arc = quick.recognize_shape(path)
                assert abs(arc["rx"] - 120.0) < 6.0 and abs(arc["ry"] - 120.0) < 6.0, arc
                assert abs(abs(arc["sweep"]) - math.radians(sweep_degrees)) < 0.1, arc
                assert (arc["sweep"] > 0.0) == (direction > 0.0), arc
    # A gently bowed stroke is a line that also offers the arc, both ways.
    for flip in (1.0, -1.0):
        bowed = [(400.0 - flip * (200.0 - 4.0 * k), 300.0 + 10.0 * math.sin(k / 100.0 * math.pi)) for k in range(101)]
        kinds = [s["kind"] for s in quick.recognize_shapes(bowed)]
        assert set(kinds) == {quick.LINE, quick.ARC}, kinds
    # A clean straight line offers only the line.
    assert [s["kind"] for s in quick.recognize_shapes([(i * 5.0, 2.0 * i) for i in range(50)])] == [quick.LINE]

    # 8d. Hand-drawn lines with a slight bow or a landing hook stay lines.
    for flip in (1.0, -1.0):
        for bow in (6.0, 12.0):
            path = [(400.0 - flip * (250.0 - 5.0 * k), 300.0 + bow * math.sin(k / 100.0 * math.pi) + (1.0 if k % 3 else -1.0)) for k in range(101)]
            path[0:0] = [(path[0][0] - flip * 12.0, path[0][1] - 10.0), (path[0][0] - flip * 5.0, path[0][1] - 3.0)]
            kinds = [s["kind"] for s in quick.recognize_shapes(path)]
            assert kinds[0] == quick.LINE, (flip, bow, kinds)

    # 8e. Elliptical arcs: deep U shapes and flat arcs a circle cannot follow.
    for direction in (1.0, -1.0):
        for rx, ry, sweep in ((70.0, 160.0, 200.0), (180.0, 60.0, 160.0), (60.0, 150.0, 230.0)):
            path = []
            for k in range(81):
                t = math.radians(-10.0) + direction * math.radians(sweep) * k / 80.0
                path.append((400.0 + rx * math.cos(t) + rng.uniform(-1, 1), 300.0 + ry * math.sin(t) + rng.uniform(-1, 1)))
            shapes = quick.recognize_shapes(path)
            arc = shapes[0]
            assert arc["kind"] == quick.ARC, (rx, ry, sweep, [s["kind"] for s in shapes])
            assert abs(max(arc["rx"], arc["ry"]) - max(rx, ry)) < 8.0 and abs(min(arc["rx"], arc["ry"]) - min(rx, ry)) < 8.0, arc
            assert abs(abs(arc["sweep"]) - math.radians(sweep)) < 0.15, arc
            knots = quick.shape_knots(arc, 3)[0]
            assert math.hypot(knots[0][1][0] - path[0][0], knots[0][1][1] - path[0][1]) < 6.0
            assert math.hypot(knots[-1][1][0] - path[-1][0], knots[-1][1][1] - path[-1][1]) < 6.0
            # The Bezier knots follow the ellipse.
            for (l0, p0, r0), (l1, p1, r1) in zip(knots, knots[1:]):
                mid = quick._bezier(p0, r0, l1, p1, 0.5)
                t = quick._ellipse_param(arc, mid)
                on = quick._ellipse_at(arc, t)
                assert math.hypot(mid[0] - on[0], mid[1] - on[1]) < 3.0

    # 8f. Polylines: a point only at each change of direction.
    for corners_in in (
        [(100, 100), (200, 300), (300, 100), (400, 300), (500, 100)],
        [(100, 100), (300, 120), (180, 300)],
        [(500, 100), (380, 260), (260, 90), (120, 240)],
    ):
        path = []
        for (x0, y0), (x1, y1) in zip(corners_in, corners_in[1:]):
            path += [(x0 + (x1 - x0) * k / 25.0 + rng.uniform(-1.5, 1.5), y0 + (y1 - y0) * k / 25.0 + rng.uniform(-1.5, 1.5)) for k in range(25)]
        path.append(corners_in[-1])
        shapes = quick.recognize_shapes(path)
        assert shapes and shapes[0]["kind"] == quick.POLYLINE, (corners_in, [s["kind"] for s in shapes])
        vertices = shapes[0]["vertices"]
        assert len(vertices) == len(corners_in), vertices
        for got, want in zip(vertices, corners_in):
            assert math.hypot(got[0] - want[0], got[1] - want[1]) < 6.0, (got, want)
        knots, cyclic, _types = quick.shape_knots(shapes[0])
        assert len(knots) == len(corners_in) and not cyclic
        segments = len(corners_in) - 1
        assert quick.points_step(quick.POLYLINE, shapes[0]) == segments
        assert len(quick.shape_knots(shapes[0], len(corners_in) + segments)[0]) == len(corners_in) + segments
    # Ctrl turns an elliptical arc into the circular arc through the same
    # start, middle and end.
    flat = {"kind": quick.ARC, "center": (300.0, 300.0), "rx": 160.0, "ry": 60.0, "angle": 0.2, "t0": 3.0, "sweep": -2.4}
    snapped = quick.transform_shape(flat, 0.0, 1.0, 15.0)
    assert abs(snapped["rx"] - snapped["ry"]) < 1.0e-9, snapped
    for f in (0.0, 0.5, 1.0):
        p = quick._arc_point(snapped, f)
        assert abs(math.hypot(p[0] - snapped["center"][0], p[1] - snapped["center"][1]) - snapped["rx"]) < 1.0e-6
    s0, s1 = quick._arc_point(snapped, 0.0), quick._arc_point(snapped, 1.0)
    chord = math.degrees(math.atan2(s1[1] - s0[1], s1[0] - s0[0]))
    assert abs(chord / 15.0 - round(chord / 15.0)) < 1.0e-6, chord
    # A wavy, unclear zig-zag stays free hand.
    wavy = [(100.0 + 8.0 * k, 300.0 + 60.0 * math.sin(k / 6.0) + 25.0 * math.sin(k / 1.7)) for k in range(80)]
    assert all(s["kind"] != quick.POLYLINE for s in quick.recognize_shapes(wavy)), [s["kind"] for s in quick.recognize_shapes(wavy)]
    # A triangle is a polygon.
    tri = [(100, 100), (300, 110), (190, 290)]
    path = []
    for (x0, y0), (x1, y1) in zip(tri, tri[1:] + tri[:1]):
        path += [(x0 + (x1 - x0) * k / 30.0, y0 + (y1 - y0) * k / 30.0) for k in range(30)]
    path.append((102, 103))
    shapes = quick.recognize_shapes(path)
    assert shapes[0]["kind"] == quick.POLYGON and len(shapes[0]["vertices"]) == 3, [s["kind"] for s in shapes]
    # Smooth arcs are not polylines.
    assert quick.recognize_shape(arc_path)["kind"] == quick.ARC

    # 9. The Quick Shape operator rewrites the stroke with exactly its points,
    #    keeps material and draw order, and the curve type is selectable.
    import json
    if not hasattr(bpy.types, "FBP_OT_gp_quick_shape_apply"):
        # Interactive-only module: not registered in a background process.
        bpy.utils.register_class(quick.FBP_OT_GPQuickShapeApply)
    gp = bpy.data.grease_pencils.new("FBP Quick Shape")
    obj = bpy.data.objects.new("FBP Quick Shape", gp)
    bpy.context.scene.collection.objects.link(obj)
    layer = gp.layers.new("Layer", set_active=True)
    drawing = layer.frames.new(1).drawing
    drawing.add_strokes([5, 12, 3])
    drawing.strokes[1].material_index = 2
    mapping = {
        "persinv": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]],
        "size": [2.0, 2.0], "origin": [0.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0],
        "to_layer": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]],
    }
    data = {
        "object": obj.name, "layer": layer.name, "frame": 1, "index": 1, "count": 3,
        "shape": {"kind": quick.ELLIPSE, "center": [1.0, 1.0], "rx": 0.5, "ry": 0.5, "angle": 0.0, "ccw": True},
        "mapping": mapping, "radius": 0.02, "opacity": 1.0,
    }
    for points, curve_type in ((4, "BEZIER"), (8, "POLY"), (5, "CATMULL_ROM")):
        drawing = layer.frames[0].drawing
        if len(drawing.strokes[1].points) != 12:
            drawing.resize_strokes(sizes=[12], indices=[1])
        result = bpy.ops.fbp.gp_quick_shape_apply(points=points, curve_type=curve_type, data=json.dumps(data))
        assert result == {"FINISHED"}, result
        stroke = layer.frames[0].drawing.strokes[1]
        assert len(stroke.points) == points, (points, len(stroke.points))
        assert stroke.cyclic and stroke.material_index == 2
        assert [len(s.points) for s in layer.frames[0].drawing.strokes] == [5, points, 3]
        assert stroke.curve_type == {"POLY": 1, "BEZIER": 2, "CATMULL_ROM": 0}[curve_type], stroke.curve_type
        for point in stroke.points:
            position = point.position
            assert abs(math.hypot(position[0], position[1]) - 0.5) < 1.0e-5, tuple(position)
            assert abs(point.radius - 0.02) < 1.0e-6

    # 10. Line or arc: the panel switches shape and resets points and type.
    drawing = layer.frames[0].drawing
    line = {"kind": quick.LINE, "start": [0.2, 1.0], "end": [1.8, 1.0]}
    arc = {"kind": quick.ARC, "center": [1.0, 0.4], "rx": 1.0, "ry": 1.0, "angle": 0.0, "t0": math.atan2(0.6, -0.8), "sweep": -2.0 * math.atan2(0.6, -0.8) + math.pi}
    choice = dict(data, shape=line, shapes=[line, arc])
    result = bpy.ops.fbp.gp_quick_shape_apply(points=2, curve_type="POLY", kind="LINE", last_kind="LINE", data=json.dumps(choice))
    assert result == {"FINISHED"} and len(layer.frames[0].drawing.strokes[1].points) == 2
    drawing = layer.frames[0].drawing
    drawing.resize_strokes(sizes=[12], indices=[1])
    result = bpy.ops.fbp.gp_quick_shape_apply(points=2, curve_type="POLY", kind="ARC", last_kind="LINE", data=json.dumps(choice))
    assert result == {"FINISHED"}, result
    stroke = layer.frames[0].drawing.strokes[1]
    assert len(stroke.points) == 3 and stroke.curve_type == 2 and not stroke.cyclic, (len(stroke.points), stroke.curve_type)
    attributes = layer.frames[0].drawing.attributes
    first = int(layer.frames[0].drawing.curve_offsets[1].value)
    left_types = [attributes["handle_type_left"].data[first + i].value for i in range(3)]
    assert left_types == [quick._HANDLE_FREE, quick._HANDLE_ALIGN, quick._HANDLE_FREE], left_types
    start_left = attributes["handle_left"].data[first].vector
    start_right = attributes["handle_right"].data[first].vector
    assert (start_left - stroke.points[0].position).length < 1.0e-6
    assert (start_right - stroke.points[0].position).length < 1.0e-6

    # 11. Automerge onto a Bezier shape: points left with handles at the
    #     origin get vector handles along the drawn path.
    drawing = layer.frames[0].drawing
    drawing.add_strokes([4])
    merged = len(drawing.strokes) - 1
    drawing.set_types(type="BEZIER", indices=[merged])
    first = int(drawing.curve_offsets[merged].value)
    attributes = drawing.attributes
    for i, xy in enumerate(((1.0, 1.0), (2.0, 1.5), (3.0, 1.0), (4.0, 2.0))):
        attributes["position"].data[first + i].vector = (xy[0], xy[1], 0.0)
        attributes["handle_left"].data[first + i].vector = (0.0, 0.0, 0.0)
        attributes["handle_right"].data[first + i].vector = (0.0, 0.0, 0.0)
    # The first point already has real handles: it is left alone.
    attributes["handle_left"].data[first].vector = (0.5, 1.0, 0.0)
    attributes["handle_right"].data[first].vector = (1.5, 1.0, 0.0)
    assert quick.repair_merged_handles(drawing) == 3
    middle = attributes["handle_left"].data[first + 1].vector
    assert abs(middle[0] - (2.0 - 1.0 / 3.0)) < 1.0e-5 and abs(middle[1] - (1.5 - 0.5 / 3.0)) < 1.0e-5, tuple(middle)
    assert attributes["handle_type_right"].data[first + 2].value == quick._HANDLE_VECTOR
    assert tuple(attributes["handle_left"].data[first].vector) == (0.5, 1.0, 0.0)
    assert quick.repair_merged_handles(drawing) == 0

    print("FBPTEST gp quick shape: PASS")
except Exception:
    traceback.print_exc()
    sys.exit(1)
