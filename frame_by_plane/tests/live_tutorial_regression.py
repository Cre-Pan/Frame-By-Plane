import importlib
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
    tutorial = importlib.import_module(f"{PACKAGE_NAME}.live_tutorial")

    # Every guide is offered in the chooser and every step is wired up: a
    # detector (or a manual completion), guidance, a button and a shortcut.
    assert set(tutorial._CHOOSER_ROUTES) == set(tutorial.ROUTES)
    for route_key, route in tutorial.ROUTES.items():
        assert route_key in tutorial._ROUTE_SHORT_LABELS
        assert route_key in tutorial._ROUTE_ICON_UI_KEYS
        assert route_key in tutorial._ROUTE_CARD_DETAILS
        for page in route.pages[:-1]:
            for task in page.tasks:
                assert task.detector in tutorial.DETECTORS or task.detector == "", task.key
                assert task.key in tutorial._TASK_GUIDANCE, task.key
                assert task.key in tutorial._TASK_ACTION_LABELS, task.key
                assert task.key in tutorial._TASK_SHORTCUTS, task.key
    for label in ("Shift + A", "G", "Hold <", "Ctrl + Tab", "N", "→"):
        assert tutorial._is_key_label(label), label
    for label in ("Frame By Plane", "Header", "Layer Settings", "Stroke / Fill swatch"):
        assert not tutorial._is_key_label(label), label

    # Frame-by-frame guide: detectors follow the real Draw Mode settings.
    scene = bpy.context.scene
    data = bpy.data.grease_pencils.new("FBP Tutorial Drawing")
    obj = bpy.data.objects.new("FBP Tutorial Drawing", data)
    material = bpy.data.materials.new("FBP Tutorial Ink")
    bpy.data.materials.create_gpencil_data(material)
    data.materials.append(material)
    layer = data.layers.new("Layer", set_active=True)
    layer.frames.new(1).drawing.add_strokes([3])

    state = tutorial.TutorialState()
    state.enter_route(bpy.context, "DRAW")
    assert state.active_task.key == "draw_add"
    assert not tutorial._detect_draw_add(bpy.context, state)
    scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    assert tutorial._detect_draw_add(bpy.context, state)

    bpy.ops.object.mode_set(mode="PAINT_GREASE_PENCIL")
    assert tutorial._detect_draw_mode(bpy.context, state)
    paint = scene.tool_settings.gpencil_paint
    settings = paint.brush.gpencil_settings
    settings.pin_draw_mode = False
    paint.color_mode = "MATERIAL"
    settings.stroke_type = "STROKE"
    assert not tutorial._detect_draw_vertex_color(bpy.context, state)
    assert tutorial._run_draw_task_action(bpy.context, "draw_vertex_color")
    assert tutorial._detect_draw_vertex_color(bpy.context, state)
    assert not tutorial._detect_draw_both(bpy.context, state)
    assert tutorial._run_draw_task_action(bpy.context, "draw_both")
    assert tutorial._detect_draw_both(bpy.context, state)

    color_state = obj.fbp_gp_vertex_color_state
    assert not tutorial._detect_draw_colors(bpy.context, state)
    color_state.fill_color = (0.2, 0.6, 0.9, 1.0)
    assert tutorial._detect_draw_colors(bpy.context, state)

    scene.tool_settings.use_keyframe_insert_auto = False
    assert not tutorial._detect_draw_autokey(bpy.context, state)
    assert tutorial._run_draw_task_action(bpy.context, "draw_autokey")
    assert tutorial._detect_draw_autokey(bpy.context, state)
    assert not tutorial._detect_draw_new_key(bpy.context, state)
    layer.frames.new(5).drawing.add_strokes([2])
    assert tutorial._detect_draw_new_key(bpy.context, state)

    # The whole route can be walked: detectors complete the steps in order.
    state = tutorial.TutorialState()
    state.enter_route(bpy.context, "DRAW")
    for _tick in range(12):
        tutorial._update_progress(bpy.context, state)
    assert state.page_index >= 1, (state.page_index, state.completed)
    print("FBPTEST live_tutorial: PASS")
except Exception:
    traceback.print_exc()
    raise
finally:
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    if not INSTALLED_PACKAGE:
        try:
            addon.unregister()
        except Exception:
            traceback.print_exc()
