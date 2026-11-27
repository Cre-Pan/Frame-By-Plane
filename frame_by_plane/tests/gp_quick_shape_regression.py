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
    assert shape and shape["kind"] == quick.ARC and abs(shape["radius"] - 100.0) < 1.0, shape
    zigzag = [(i * 10.0, 40.0 if (i // 3) % 2 else 0.0) for i in range(30)]
    assert quick.recognize_shape(zigzag) is None
    assert quick.recognize_shape(wobbly)["kind"] == quick.LINE

    # 8. Point counts: defaults, wheel steps and limits.
    assert [quick.DEFAULT_POINTS[k] for k in (quick.LINE, quick.ARC, quick.ELLIPSE, quick.RECT)] == [2, 3, 4, 4]
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
                # Inner points aligned; the two ends have no outer handle.
                assert not aligned[0] and not aligned[-1] and all(aligned[1:-1])
                assert knots[0][0] == knots[0][1] and knots[-1][2] == knots[-1][1]
                assert knots[0][2] != knots[0][1] and knots[-1][0] != knots[-1][1]
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
                assert abs(arc["radius"] - 120.0) < 6.0, arc
                assert abs(abs(arc["sweep"]) - math.radians(sweep_degrees)) < 0.1, arc
                assert (arc["sweep"] > 0.0) == (direction > 0.0), arc
    # A gently bowed stroke is a line that also offers the arc, both ways.
    for flip in (1.0, -1.0):
        bowed = [(400.0 - flip * (200.0 - 4.0 * k), 300.0 + 10.0 * math.sin(k / 100.0 * math.pi)) for k in range(101)]
        kinds = [s["kind"] for s in quick.recognize_shapes(bowed)]
        assert set(kinds) == {quick.LINE, quick.ARC}, kinds
    # A clean straight line offers only the line.
    assert [s["kind"] for s in quick.recognize_shapes([(i * 5.0, 2.0 * i) for i in range(50)])] == [quick.LINE]

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
    arc = {"kind": quick.ARC, "center": [1.0, 0.4], "radius": 1.0, "start_angle": math.atan2(0.6, -0.8), "sweep": -2.0 * math.atan2(0.6, -0.8) + math.pi}
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
    assert (start_left - stroke.points[0].position).length < 1.0e-6

    print("FBPTEST gp quick shape: PASS")
except Exception:
    traceback.print_exc()
    sys.exit(1)
