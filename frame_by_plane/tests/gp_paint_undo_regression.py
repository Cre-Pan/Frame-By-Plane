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


def close_color(actual, expected, epsilon=1.0e-5):
    return all(abs(float(a) - float(b)) <= epsilon for a, b in zip(actual, expected))


if not INSTALLED_PACKAGE:
    addon.register()
bpy.context.preferences.edit.use_global_undo = True
try:
    module = addon.gp_vertex_colors
    data = bpy.data.grease_pencils.new("FBP Paint Undo")
    obj = bpy.data.objects.new("FBP Paint Undo", data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    layer = data.layers.new("Layer", set_active=True)
    drawing = layer.frames.new(1).drawing
    drawing.add_strokes([2])
    material = bpy.data.materials.new("FBP Paint Undo Ink")
    bpy.data.materials.create_gpencil_data(material)
    data.materials.append(material)

    bpy.ops.object.mode_set(mode="PAINT_GREASE_PENCIL")
    module._sync_draw_state(bpy.context)
    state = obj.fbp_gp_vertex_color_state
    _paint, _brush, owner, gp_settings = module._draw_brush_context(bpy.context)
    gp_settings.stroke_type = "STROKE"
    original_stroke = (0.1, 0.2, 0.3, 1.0)
    original_fill = (0.7, 0.8, 0.9, 1.0)
    state.stroke_color = original_stroke
    state.fill_color = original_fill
    module._canonical_brush_colors(state, owner, "STROKE")
    assert bpy.ops.ed.undo_push(message="FBP Paint Baseline") == {"FINISHED"}

    # Emulate native X, then let the semantic synchronizer create the dedicated
    # swap step after state and brush have both been updated.
    owner.color, owner.secondary_color = tuple(owner.secondary_color), tuple(owner.color)
    assert module._sync_draw_state(bpy.context)
    swapped_stroke = tuple(state.stroke_color)
    swapped_fill = tuple(state.fill_color)
    assert close_color(swapped_stroke, original_fill)
    assert close_color(swapped_fill, original_stroke)

    drawing.add_strokes([2])
    data.update_tag()
    assert len(drawing.strokes) == 2
    assert bpy.ops.ed.undo_push(message="FBP Test Stroke") == {"FINISHED"}

    # First Ctrl+Z removes only the stroke. Both visible semantic swatches and
    # native brush colors must remain swapped.
    assert bpy.ops.ed.undo() == {"FINISHED"}
    obj = bpy.data.objects["FBP Paint Undo"]
    drawing = obj.data.layers.active.current_frame().drawing
    state = obj.fbp_gp_vertex_color_state
    _paint, _brush, owner, gp_settings = module._draw_brush_context(bpy.context)
    assert len(drawing.strokes) == 1
    assert close_color(state.stroke_color, swapped_stroke)
    assert close_color(state.fill_color, swapped_fill)
    assert close_color(tuple(owner.color), swapped_stroke[:3])
    assert close_color(tuple(owner.secondary_color), swapped_fill[:3])
    if module._RUNTIME["draw_watch_initialized"]:
        assert module._RUNTIME["draw_curve_count"] == 1

    # In Draw Mode Stroke / Fill are tool settings, like Blender's brush
    # colors: X adds no undo step of its own, and the restored baseline (which
    # predates the swap) does not bring the old pair back.
    obj = bpy.data.objects["FBP Paint Undo"]
    state = obj.fbp_gp_vertex_color_state
    _paint, _brush, owner, gp_settings = module._draw_brush_context(bpy.context)
    assert close_color(state.stroke_color, swapped_stroke)
    assert close_color(state.fill_color, swapped_fill)
    assert close_color(tuple(owner.color), swapped_stroke[:3])
    assert close_color(tuple(owner.secondary_color), swapped_fill[:3])

    # A color picked in a panel (no undo step of its own), then a stroke:
    # Ctrl+Z removes the stroke and keeps the picked color.
    picked = (0.9, 0.3, 0.1, 1.0)
    state.stroke_color = picked
    obj = bpy.data.objects["FBP Paint Undo"]
    drawing = obj.data.layers.active.current_frame().drawing
    drawing.add_strokes([2])
    assert bpy.ops.ed.undo_push(message="FBP Picked Color Stroke") == {"FINISHED"}
    assert bpy.ops.ed.undo() == {"FINISHED"}
    obj = bpy.data.objects["FBP Paint Undo"]
    state = obj.fbp_gp_vertex_color_state
    _paint, _brush, owner, gp_settings = module._draw_brush_context(bpy.context)
    assert close_color(state.stroke_color, picked), tuple(state.stroke_color)
    assert close_color(tuple(owner.color), picked[:3]), tuple(owner.color)
    # Redo brings nothing back that would change the color either.
    bpy.ops.ed.redo()
    obj = bpy.data.objects["FBP Paint Undo"]
    state = obj.fbp_gp_vertex_color_state
    assert close_color(state.stroke_color, picked)
    state.stroke_color = original_stroke
    state.fill_color = original_fill

    # Close Gap has the same two-step contract: stroke first, setting second.
    # Blender 5.3 has its own Cyclic brush option instead (covered by the
    # dual color regression), so the add-on setting is only checked on 5.2.
    if not module.native_cyclic_stroke():
        assert state.close_strokes is False
        assert bpy.ops.fbp.toggle_gp_close_gap() == {"FINISHED"}
        assert state.close_strokes is True
        obj = bpy.data.objects["FBP Paint Undo"]
        drawing = obj.data.layers.active.current_frame().drawing
        drawing.add_strokes([2])
        assert bpy.ops.ed.undo_push(message="FBP Closed Stroke") == {"FINISHED"}
        assert bpy.ops.ed.undo() == {"FINISHED"}
        obj = bpy.data.objects["FBP Paint Undo"]
        state = obj.fbp_gp_vertex_color_state
        assert state.close_strokes is True
        assert bpy.ops.ed.undo() == {"FINISHED"}
        obj = bpy.data.objects["FBP Paint Undo"]
        state = obj.fbp_gp_vertex_color_state
        assert state.close_strokes is False

    # Fill target reverses the native primary/secondary mapping; Undo keeps
    # the swapped pair there too.
    _paint, _brush, owner, gp_settings = module._draw_brush_context(bpy.context)
    gp_settings.stroke_type = "FILL"
    module._sync_draw_state(bpy.context)
    assert close_color(tuple(owner.color), original_fill[:3])
    assert close_color(tuple(owner.secondary_color), original_stroke[:3])
    assert bpy.ops.ed.undo_push(message="FBP Fill Baseline") == {"FINISHED"}
    owner.color, owner.secondary_color = tuple(owner.secondary_color), tuple(owner.color)
    assert module._sync_draw_state(bpy.context)
    fill_swapped_stroke = tuple(state.stroke_color)
    fill_swapped_fill = tuple(state.fill_color)
    assert close_color(fill_swapped_stroke, original_fill)
    assert close_color(fill_swapped_fill, original_stroke)
    obj = bpy.data.objects["FBP Paint Undo"]
    drawing = obj.data.layers.active.current_frame().drawing
    drawing.add_strokes([2])
    assert bpy.ops.ed.undo_push(message="FBP Fill Stroke") == {"FINISHED"}
    assert bpy.ops.ed.undo() == {"FINISHED"}
    obj = bpy.data.objects["FBP Paint Undo"]
    state = obj.fbp_gp_vertex_color_state
    _paint, _brush, owner, gp_settings = module._draw_brush_context(bpy.context)
    assert close_color(state.stroke_color, fill_swapped_stroke)
    assert close_color(state.fill_color, fill_swapped_fill)
    assert close_color(tuple(owner.color), fill_swapped_fill[:3])
    assert close_color(tuple(owner.secondary_color), fill_swapped_stroke[:3])
    assert bpy.ops.ed.undo() == {"FINISHED"}
    obj = bpy.data.objects["FBP Paint Undo"]
    state = obj.fbp_gp_vertex_color_state
    _paint, _brush, owner, gp_settings = module._draw_brush_context(bpy.context)
    assert close_color(state.stroke_color, fill_swapped_stroke)
    assert close_color(state.fill_color, fill_swapped_fill)
    assert close_color(tuple(owner.color), fill_swapped_fill[:3])
    assert close_color(tuple(owner.secondary_color), fill_swapped_stroke[:3])
    print("FBPTEST gp_paint_swap_stroke_undo: PASS")
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
