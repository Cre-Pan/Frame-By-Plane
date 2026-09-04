"""Interactive, isolated Blender 5.2 camera/GP history regression.

Run with --factory-startup --python tools/audit_camera_gp_history.py. Set
FBP_HISTORY_REPORT to the report destination; use isolated BLENDER_USER_* dirs.
FBP_AUDIT_PACKAGE optionally selects an already-enabled installed extension.
Native Undo needs a real window. Timed stages allow the add-on watchdog and
deferred work to run between edits, rather than testing only a blocked runtime.
"""
import importlib
import json
import math
import os
from pathlib import Path
import sys
import traceback

sys.dont_write_bytecode = True
import bpy

ROOT = Path(__file__).resolve().parents[1]
REPORT = Path(os.environ.get('FBP_HISTORY_REPORT', ROOT / 'work/camera-gp-history.json'))
RESULTS = []
PACKAGE = os.environ.get('FBP_AUDIT_PACKAGE', 'frame_by_plane')
NAME = 'FBP History GP'
sys.path.insert(0, str(ROOT))


def result(name, details):
    RESULTS.append(dict(name=name, status='PASS', detail=details))
    print('FBP_HISTORY_PASS', name, details, flush=True)


def override():
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return bpy.context.temp_override(window=window, area=area, region=region)


def canvas():
    return bpy.data.objects[NAME]


def style():
    return canvas().data.materials[0].grease_pencil


def snapshot():
    obj = canvas()
    drawing = obj.data.layers[0].frames[0].drawing
    return {
        'mode': obj.mode,
        'points': [[round(float(v), 5) for v in p.position] for p in drawing.strokes[0].points],
        'vertex': [[round(float(v), 5) for v in p.vertex_color] for p in drawing.strokes[0].points],
        'stroke': [round(float(v), 5) for v in style().color],
        'fill': [round(float(v), 5) for v in style().fill_color],
        'hsv': [round(float(getattr(style(), key)), 5) for key in
                ('random_hue_factor', 'random_saturation_factor', 'random_value_factor')],
        'materials': len(obj.data.materials),
    }


def stages():
    addon = importlib.import_module(PACKAGE)
    if PACKAGE == 'frame_by_plane':
        addon.register()
    else:
        assert PACKAGE in bpy.context.preferences.addons
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.preferences.edit.undo_steps = 64
    yield 2.0
    output = importlib.import_module(PACKAGE + '.camera_output')
    core = importlib.import_module(PACKAGE + '.core')
    bridge = importlib.import_module(PACKAGE + '.grease_pencil_bridge')
    scene = bpy.context.scene
    scene.fbp_cam_ratio = 'HD_16_9'
    scene.fbp_camera_aspect = '16:9'
    sizes = {}
    for key, longest in output.RESOLUTION_PRESETS[1:]:
        scene.fbp_camera_resolution = key
        size = scene.render.resolution_x, scene.render.resolution_y
        assert size == output.resolution_for_aspect(output.parse_aspect_ratio('16:9'), longest), size
        assert scene.fbp_camera_resolution == key
        sizes[key] = size
    scene.fbp_camera_aspect = '9:16'
    assert (scene.render.resolution_x, scene.render.resolution_y) == (7680, 4320)
    output.swap_camera_dimensions(scene)
    assert (scene.render.resolution_x, scene.render.resolution_y) == (4320, 7680)
    scene.fbp_camera_aspect = '1:1'
    assert scene.render.resolution_x == scene.render.resolution_y == 7680
    scene.fbp_camera_resolution = 'HD'
    scene.fbp_camera_aspect = '2.39:1'
    assert scene.fbp_camera_aspect == '2.39:1'
    size = scene.render.resolution_x, scene.render.resolution_y
    for invalid in ('0:1', '1:0', '-16:9', 'nan:1', '16', '1e400:1', '999999999999999999999:1'):
        scene.fbp_camera_aspect = invalid
        assert (scene.render.resolution_x, scene.render.resolution_y) == size, invalid
    scene.fbp_camera_resolution = 'CUSTOM'
    scene.fbp_camera_fit_source_aspect = True
    scene.fbp_camera_dimensions_linked = False
    scene.fbp_camera_width = 1234
    scene.fbp_camera_height = 987
    core.apply_camera_ratio_settings(scene)
    assert (scene.render.resolution_x, scene.render.resolution_y) == (1234, 987)
    assert scene.fbp_camera_resolution == 'CUSTOM'
    assert scene.fbp_camera_aspect == '1234:987'
    scene.render.pixel_aspect_x = 2.0
    scene.fbp_camera_aspect = '16:9'
    scene.fbp_camera_resolution = 'HD'
    assert (scene.render.resolution_x, scene.render.resolution_y) == (1707, 1920)
    scene.render.pixel_aspect_x = 1.0
    scene.fbp_camera_aspect = '16:9'
    scene.fbp_camera_resolution = 'HD'
    result('camera_output', dict(presets=sizes, invalid_rejected=7, custom_source_unlocked=True, non_square_pixels=True))
    with override():
        bpy.ops.ed.undo_push(message='Camera HD baseline')
        bpy.context.scene.fbp_camera_resolution = '4K'
        bpy.ops.ed.undo_push(message='Camera 4K')
        bpy.ops.ed.undo()
    yield 2.8
    assert bpy.context.scene.fbp_camera_resolution == 'HD'
    assert bpy.context.scene.render.resolution_x == 1920
    with override():
        bpy.ops.ed.redo()
    yield 2.8
    assert bpy.context.scene.fbp_camera_resolution == '4K'
    assert bpy.context.scene.render.resolution_x == 3840
    result('camera_undo_redo', 'HD -> 4K -> Undo HD -> Redo 4K, after timers settle')
    with override():
        bpy.ops.fbp.set_camera_aspect(preset='FOUR_FIVE')
        bpy.ops.ed.undo_push(message='Camera 4:5 landscape')
    assert (bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y) == (3840, 3072)
    with override():
        bpy.ops.fbp.swap_camera_dimensions()
        bpy.ops.ed.undo_push(message='Camera 4:5 portrait')
    assert (bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y) == (3072, 3840)
    with override():
        bpy.ops.ed.undo()
    yield 2.8
    assert (bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y) == (3840, 3072)
    with override():
        bpy.ops.ed.redo()
    yield 2.8
    assert (bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y) == (3072, 3840)
    assert output.camera_aspect_menu_label(bpy.context.scene) == '4:5'
    bpy.context.scene.fbp_camera_resolution = 'HD'
    assert (bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y) == (1536, 1920)
    result('camera_aspect_swap_undo_redo', '4:5 landscape by default, swap/Undo/Redo and portrait HD preserved')

    def camera_state():
        current = bpy.context.scene
        return (current.render.resolution_x, current.render.resolution_y,
                current.fbp_camera_dimensions_linked,
                output.camera_aspect_menu_label(current))

    with override():
        bpy.context.scene.fbp_camera_dimensions_linked = True
        bpy.context.scene.fbp_camera_aspect = '1:1'
        bpy.context.scene.fbp_camera_height = 1000
        bpy.ops.ed.undo_push(message='Linked square baseline')
        bpy.context.scene.fbp_camera_width = 1200
        bpy.ops.ed.undo_push(message='Linked width edit')
        assert camera_state() == (1200, 1200, True, '1:1')
        bpy.ops.ed.undo()
    yield 2.8
    assert camera_state() == (1000, 1000, True, '1:1')
    with override():
        bpy.ops.ed.redo()
    yield 2.8
    assert camera_state() == (1200, 1200, True, '1:1')
    result('camera_linked_pixels_undo_redo', 'Linked width restores both dimensions and aspect through history')

    with override():
        bpy.context.scene.fbp_camera_dimensions_linked = False
        bpy.context.scene.fbp_camera_height = 900
        bpy.ops.ed.undo_push(message='Unlinked height edit')
        assert camera_state() == (1200, 900, False, 'Custom')
        bpy.ops.ed.undo()
    yield 2.8
    assert camera_state() == (1200, 1200, True, '1:1')
    with override():
        bpy.ops.ed.redo()
    yield 2.8
    assert camera_state() == (1200, 900, False, 'Custom')
    result('camera_unlinked_pixels_undo_redo', 'Unlinked height, Custom aspect and link toggle restore together')

    with override():
        bpy.ops.fbp.save_camera_format_preset(name='History Format')
        bpy.ops.ed.undo_push(message='Saved camera preset')
        bpy.ops.ed.undo()
    yield .5
    assert len(bpy.context.scene.fbp_camera_format_presets) == 0
    with override():
        bpy.ops.ed.redo()
    yield .5
    assert len(bpy.context.scene.fbp_camera_format_presets) == 1
    with override():
        bpy.ops.fbp.set_camera_aspect(preset='SQUARE')
        bpy.ops.ed.undo_push(message='Square before preset')
        bpy.ops.fbp.apply_camera_format_preset(index=0)
        bpy.ops.ed.undo_push(message='Applied camera preset')
        assert camera_state() == (1200, 900, False, 'Custom')
        bpy.ops.ed.undo()
    yield 2.8
    assert camera_state() == (1200, 1200, False, '1:1')
    with override():
        bpy.ops.ed.redo()
    yield 2.8
    assert camera_state() == (1200, 900, False, 'Custom')
    with override():
        bpy.ops.fbp.remove_camera_format_preset(index=0)
        bpy.ops.ed.undo_push(message='Removed camera preset')
        assert len(bpy.context.scene.fbp_camera_format_presets) == 0
        bpy.ops.ed.undo()
    yield .5
    assert len(bpy.context.scene.fbp_camera_format_presets) == 1
    with override():
        bpy.ops.ed.redo()
    yield .5
    assert len(bpy.context.scene.fbp_camera_format_presets) == 0
    result('camera_presets_undo_redo', 'Save/apply/remove and linked/custom state restore through history')
    with override():
        bpy.ops.fbp.add_grease_pencil_canvas('EXEC_DEFAULT', canvas_name=NAME,
                                            owner_name='__FREE__', enter_draw_mode=False)
        obj = bpy.context.object
        obj.name = NAME
        layer = obj.data.layers[0]
        frame = layer.frames[0] if len(layer.frames) else layer.frames.new(1)
        drawing = frame.drawing
        drawing.add_strokes([3])
        for i, point in enumerate(drawing.strokes[0].points):
            point.position = (i * 0.3, 0, i * 0.15)
            point.radius = .08
            point.opacity = 1
            point.vertex_color = (.2, .4, .6, 1)
        style().mode = 'DOTS'
        style().use_randomization = True
        style().color = (.1, .2, .3, 1)
        style().fill_color = (.3, .2, .1, 1)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.grease_pencil.select_all(action='SELECT')
        bpy.ops.ed.undo_push(message='GP Edit baseline')
    yield .8
    baseline = snapshot()
    assert baseline['mode'] == 'EDIT'
    with override():
        for point in canvas().data.layers[0].frames[0].drawing.strokes[0].points:
            point.vertex_color = (.7, .2, .1, 1)
        bpy.ops.ed.undo_push(message='GP Edit vertex colors')
    changed = snapshot()
    assert changed['vertex'] != baseline['vertex'], (baseline, changed)
    yield .8
    with override():
        bpy.ops.ed.undo()
    yield 2.8
    assert snapshot() == baseline, ('GP vertex Undo', baseline, snapshot())
    with override():
        bpy.ops.ed.redo()
    yield 2.8
    assert snapshot() == changed, ('GP vertex Redo', changed, snapshot())
    result('gp_edit_vertex_color_undo_redo', 'Point color edits restored while keeping Edit Mode')
    with override():
        for _ in range(20):
            bpy.ops.ed.undo()
            assert snapshot() == baseline
            bpy.ops.ed.redo()
            assert snapshot() == changed
    yield 3.0
    assert snapshot() == changed
    result('gp_edit_rapid_history', '20 Undo/Redo pairs on point colors; mode and geometry preserved')
    assert not bridge._gp_external_settings_undo_safe(canvas())
    with override():
        assert not bpy.ops.fbp.toggle_gp_native_effect.poll()
        assert not bpy.ops.fbp.reset_gp_native_effect.poll()
        assert not bpy.ops.fbp.move_gp_native_effect.poll()
    # The exact installed 5.2 build skips Material-ID UI undo in GP Edit Mode.
    # The production UI now requires an explicit Object Mode switch first.
    with override():
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.ed.undo_push(message='GP Object material baseline')
    yield .8
    assert bridge._gp_external_settings_undo_safe(canvas())
    result('gp_edit_material_guard', 'Material controls read-only in Edit Mode; explicit Object Mode action')
    baseline = snapshot()
    style().color = (.9, .1, .2, .7)
    style().fill_color = (.1, .8, .3, .6)
    style().random_hue_factor = .8
    style().random_saturation_factor = .4
    style().random_value_factor = .3
    with override():
        bpy.ops.ed.undo_push(message='GP Stroke Material colors')
    changed = snapshot()
    yield .8
    with override():
        bpy.ops.ed.undo()
    yield 2.8
    assert snapshot() == baseline, ('GP material Undo', baseline, snapshot())
    with override():
        bpy.ops.ed.redo()
    yield 2.8
    assert snapshot() == changed, ('GP material Redo', changed, snapshot())
    result('gp_object_material_color_undo_redo', 'Stroke/fill RGBA and random HSV restored in Object Mode')
    with override():
        for _ in range(20):
            bpy.ops.ed.undo()
            assert snapshot() == baseline
            bpy.ops.ed.redo()
            assert snapshot() == changed
    yield 3.0
    assert snapshot() == changed
    result('gp_rapid_history', '20 Undo/Redo pairs plus settled-state assertion')
    with override():
        bpy.ops.fbp.toggle_gp_native_effect('EXEC_DEFAULT', effect_id='HUE_SATURATION')
        bpy.ops.ed.undo_push(message='GP HSV effect baseline')
    native = bridge._gp_native_effect_instance(canvas(), 'HUE_SATURATION')
    before_hue = float(native.hue)
    native.hue = .8
    with override():
        bpy.ops.ed.undo_push(message='GP HSV effect changed')
        bpy.ops.ed.undo()
    yield 2.8
    assert math.isclose(bridge._gp_native_effect_instance(canvas(), 'HUE_SATURATION').hue, before_hue, abs_tol=1e-5)
    with override():
        bpy.ops.ed.redo()
    yield 2.8
    assert math.isclose(bridge._gp_native_effect_instance(canvas(), 'HUE_SATURATION').hue, .8, abs_tol=1e-5)
    result('gp_hsv_effect_undo_redo', 'Native color modifier restores settings in Object Mode')
    with override():
        bpy.ops.object.mode_set(mode='OBJECT')
    yield .5
    original = snapshot()
    obj = canvas()
    duplicate = bpy.data.materials.new('History alternate')
    bpy.data.materials.create_gpencil_data(duplicate)
    obj.data.materials.append(duplicate)
    obj.active_material_index = 1
    assert bridge._active_gp_material_style(obj)[0] == duplicate
    obj.data.materials.pop(index=1)
    assert bridge._active_gp_material_style(obj)[0] == obj.data.materials[0]
    result('gp_material_slot_removal', 'Read-only UI lookup survives removal of active slot')
    result('blender_version', bpy.app.version_string)


ITERATOR = stages()


def tick():
    try:
        return next(ITERATOR)
    except StopIteration:
        pass
    except Exception:
        detail = traceback.format_exc()
        RESULTS.append(dict(name='regression', status='FAIL', detail=detail))
        print(detail, flush=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(dict(passed=all(r['status'] == 'PASS' for r in RESULTS),
                                     results=RESULTS), indent=2), encoding='utf-8')
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=.5)
