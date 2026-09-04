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

    # Second Ctrl+Z is the dedicated X step and restores both representations.
    assert bpy.ops.ed.undo() == {"FINISHED"}
    obj = bpy.data.objects["FBP Paint Undo"]
    state = obj.fbp_gp_vertex_color_state
    _paint, _brush, owner, gp_settings = module._draw_brush_context(bpy.context)
    assert close_color(state.stroke_color, original_stroke)
    assert close_color(state.fill_color, original_fill)
    assert close_color(tuple(owner.color), original_stroke[:3])
    assert close_color(tuple(owner.secondary_color), original_fill[:3])

    # Close Gap has the same two-step contract: stroke first, setting second.
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

    # Fill target reverses the native primary/secondary mapping. It must obey
    # the same stroke-first, swap-second Undo contract.
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
    assert close_color(state.stroke_color, original_stroke)
    assert close_color(state.fill_color, original_fill)
    assert close_color(tuple(owner.color), original_fill[:3])
    assert close_color(tuple(owner.secondary_color), original_stroke[:3])
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
