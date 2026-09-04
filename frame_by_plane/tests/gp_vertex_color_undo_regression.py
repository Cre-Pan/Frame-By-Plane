import importlib
import os
import sys
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


def close_color(actual, expected, epsilon=1.0e-5):
    return all(abs(float(a) - float(b)) <= epsilon for a, b in zip(actual, expected))


if not INSTALLED_PACKAGE:
    addon.register()
bpy.context.preferences.edit.use_global_undo = True
try:
    data = bpy.data.grease_pencils.new("FBP Undo Color")
    obj = bpy.data.objects.new("FBP Undo Color", data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    layer = data.layers.new("Layer", set_active=True)
    drawing = layer.frames.new(1).drawing
    drawing.add_strokes([2])
    original = (0.9, 0.1, 0.2, 0.7)
    original_fill = (0.1, 0.8, 0.3, 0.6)
    for point in drawing.strokes[0].points:
        point.vertex_color = original
    drawing.strokes[0].fill_color = original_fill
    data.update_tag()
    obj.update_tag(refresh={"DATA"})
    bpy.context.view_layer.update()

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.context.scene.tool_settings.gpencil_selectmode_edit = "STROKE"
    drawing.strokes[0].select = True
    addon.gp_vertex_colors._sync_edit_state(bpy.context, force=True)
    obj.fbp_gp_vertex_color_state.stroke_color = (0.2, 0.4, 0.6, 0.8)
    assert all(close_color(point.vertex_color, (0.2, 0.4, 0.6, 0.8)) for point in drawing.strokes[0].points)
    addon.gp_vertex_colors._commit_edit_color_undo()
    assert bpy.ops.ed.undo() == {"FINISHED"}

    obj = bpy.data.objects["FBP Undo Color"]
    drawing = obj.data.layers.active.current_frame().drawing
    print("FBPTEST undo_state", tuple(obj.fbp_gp_vertex_color_state.stroke_color))
    print("FBPTEST undo_colors", [tuple(point.vertex_color) for point in drawing.strokes[0].points])
    assert all(close_color(point.vertex_color, original) for point in drawing.strokes[0].points)
    assert close_color(obj.fbp_gp_vertex_color_state.stroke_color, original)

    drawing.strokes[0].select = True
    addon.gp_vertex_colors._sync_edit_state(bpy.context, force=True)
    new_fill = (0.7, 0.2, 0.5, 0.9)
    obj.fbp_gp_vertex_color_state.fill_color = new_fill
    assert close_color(drawing.strokes[0].fill_color, new_fill)
    addon.gp_vertex_colors._commit_edit_color_undo()
    assert bpy.ops.ed.undo() == {"FINISHED"}
    obj = bpy.data.objects["FBP Undo Color"]
    drawing = obj.data.layers.active.current_frame().drawing
    assert close_color(drawing.strokes[0].fill_color, original_fill)

    drawing.strokes[0].select = True
    addon.gp_vertex_colors._sync_edit_state(bpy.context, force=True)
    obj.fbp_gp_vertex_color_state.close_strokes = True
    assert drawing.strokes[0].cyclic is True
    addon.gp_vertex_colors._commit_edit_color_undo()
    assert bpy.ops.ed.undo() == {"FINISHED"}
    obj = bpy.data.objects["FBP Undo Color"]
    drawing = obj.data.layers.active.current_frame().drawing
    assert drawing.strokes[0].cyclic is False

    drawing.strokes[0].select = True
    addon.gp_vertex_colors._sync_edit_state(bpy.context, force=True)
    assert bpy.ops.fbp.swap_gp_vertex_colors() == {"FINISHED"}
    assert all(close_color(point.vertex_color, original_fill) for point in drawing.strokes[0].points)
    assert close_color(drawing.strokes[0].fill_color, original)
    assert bpy.ops.ed.undo() == {"FINISHED"}
    obj = bpy.data.objects["FBP Undo Color"]
    drawing = obj.data.layers.active.current_frame().drawing
    assert all(close_color(point.vertex_color, original) for point in drawing.strokes[0].points)
    assert close_color(drawing.strokes[0].fill_color, original_fill)
    print("FBPTEST gp_vertex_color_undo_stroke_fill_swap: PASS")
finally:
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    if not INSTALLED_PACKAGE:
        addon.unregister()
