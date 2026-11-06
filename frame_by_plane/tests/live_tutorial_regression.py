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

    # The card stays compact and inside the viewport on every page, collapses
    # to its title bar and keeps a drag handle that never covers its buttons.
    class _Region:
        def __init__(self, width, height):
            self.width, self.height = width, height

    def _inside_region(hud, region):
        assert hud["x"] >= 0 and hud["y"] >= 0, hud
        assert hud["x"] + hud["width"] <= region.width + 0.01, hud
        assert hud["y"] + hud["height"] <= region.height + 0.01, hud

    for region in (_Region(1600, 900), _Region(420, 260)):
        state = tutorial.TutorialState()
        hud = tutorial._compute_hud(bpy.context, region, state)
        _inside_region(hud, region)
        for route_key, route in tutorial.ROUTES.items():
            state = tutorial.TutorialState()
            state.enter_route(bpy.context, route_key)
            for index in range(len(route.pages)):
                state.page_index = index
                hud = tutorial._compute_hud(bpy.context, region, state)
                _inside_region(hud, region)
                if region.width >= 1000:
                    assert hud["width"] <= 360 * hud["scale"], hud["width"]
                    assert hud["height"] <= 220 * hud["scale"], (route_key, index, hud["height"])
                drag = hud["drag_rect"]
                assert drag[0] + drag[2] <= hud["controls"]["help"][0], drag
            state.collapsed = True
            collapsed = tutorial._compute_hud(bpy.context, region, state)
            assert collapsed["height"] == collapsed["header_h"], collapsed["height"]
            state.offset = (-5000.0, 5000.0)
            moved = tutorial._compute_hud(bpy.context, region, state)
            _inside_region(moved, region)
    assert "image_import" in tutorial._DIALOG_OPTION_NOTES
    assert "multi_generate" in tutorial._DIALOG_OPTION_NOTES

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
    started = tutorial._progress_signature(state)
    for _tick in range(12):
        tutorial._update_progress(bpy.context, state)
    assert state.page_index >= 1, (state.page_index, state.completed)
    # The timer redraws the card only when this signature moves.
    settled = tutorial._progress_signature(state)
    assert settled != started, (started, settled)
    tutorial._update_progress(bpy.context, state)
    assert tutorial._progress_signature(state) == settled

    # Motion: animations start only after a change, end on their own, and the
    # card's final layout never depends on where an animation currently is.
    motion_module = importlib.import_module(f"{PACKAGE_NAME}.tutorial_motion")
    clock = [10.0]
    motion = motion_module.Motion(clock=lambda: clock[0])
    assert motion.value("progress", 0.25, 0.5) == 0.25 and not motion.busy()
    assert motion.value("progress", 1.0, 0.5) == 0.25 and motion.busy()
    clock[0] += 0.25
    assert 0.25 < motion.value("progress", 1.0, 0.5) < 1.0
    clock[0] += 0.5
    assert motion.value("progress", 1.0, 0.5) == 1.0 and not motion.busy()
    motion.trigger("content", 0.3)
    assert motion.phase("content") == 0.0 and motion.busy()
    clock[0] += 0.31
    assert motion.phase("content") is None and not motion.busy()
    motion.wake(0.1)
    assert motion.busy()
    clock[0] += 0.2
    assert not motion.busy()
    for ease in (motion_module.ease_out_cubic, motion_module.ease_in_out_cubic, motion_module.ease_out_back):
        assert abs(ease(0.0)) < 1e-9 and abs(ease(1.0) - 1.0) < 1e-9

    state = tutorial.TutorialState()
    state.motion.clock = lambda: clock[0]
    region = _Region(1600, 900)
    tutorial._sync_motion(state)
    assert not state.motion.busy(), "the first frame must not animate"
    state.enter_route(bpy.context, "IMAGE")
    tutorial._sync_motion(state)
    assert state.motion.running("content") and state.motion.running("attention")
    final = tutorial._compute_hud(bpy.context, region, state)
    state.motion.snap("height", 0.0)
    gliding = tutorial._compute_hud(bpy.context, region, state, animated=True)
    assert gliding["height"] < final["height"], "height glides when animated"
    assert abs((gliding["y"] + gliding["height"]) - (final["y"] + final["height"])) < 0.01, "top edge stays put"
    assert tutorial._compute_hud(bpy.context, region, state)["height"] == final["height"]
    first = state.active_task
    state.manual_completed.add(first.key)
    tutorial._sync_motion(state)
    assert state.motion.running("done"), "a confirmed step flashes"
    clock[0] += 5.0
    assert not state.motion.busy(), "every animation ends by itself"
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
