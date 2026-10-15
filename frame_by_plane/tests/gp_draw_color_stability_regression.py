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


BLACK = (0.0, 0.0, 0.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)
SELECTION_STROKE = (0.9, 0.1, 0.1, 1.0)
SELECTION_FILL = (0.1, 0.9, 0.1, 0.0)


if not INSTALLED_PACKAGE:
    addon.register()
bpy.context.preferences.edit.use_global_undo = True
try:
    module = addon.gp_vertex_colors
    scene = bpy.context.scene
    tool_settings = scene.tool_settings
    data = bpy.data.grease_pencils.new("FBP Draw Color Stability")
    obj = bpy.data.objects.new("FBP Draw Color Stability", data)
    scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    material = bpy.data.materials.new("FBP Draw Color Stability Ink")
    bpy.data.materials.create_gpencil_data(material)
    data.materials.append(material)
    layer = data.layers.new("Layer", set_active=True)
    first = layer.frames.new(1).drawing
    first.add_strokes([3])
    first.strokes[0].fill_color = (0.2, 0.3, 0.4, 1.0)

    scene.frame_set(5)
    bpy.ops.object.mode_set(mode="PAINT_GREASE_PENCIL")
    _paint, brush, owner, gp_settings = module._draw_brush_context(bpy.context)
    gp_settings.stroke_type = "BOTH"
    gp_settings.pin_draw_mode = True
    gp_settings.brush_draw_mode = "VERTEXCOLOR"
    tool_settings.use_gpencil_draw_onback = False
    tool_settings.use_gpencil_draw_additive = False
    state = obj.fbp_gp_vertex_color_state
    module._sync_draw_state(bpy.context)
    state.stroke_color = BLACK
    state.fill_color = WHITE
    state.close_strokes = False
    assert close_color(owner.color, BLACK[:3])
    assert close_color(owner.secondary_color, WHITE[:3])

    # Auto Keying: the first stroke on an empty frame creates a new keyframe.
    # Blender fills it with the brush color (Stroke); Both must give it Fill.
    module._reset_draw_both_tracking()
    assert module._sync_draw_both_fill(bpy.context) == 0
    keyed = layer.frames.new(5).drawing
    keyed.add_strokes([3])
    keyed.strokes[0].fill_color = BLACK
    assert module._sync_draw_both_fill(bpy.context) == 1
    assert close_color(keyed.strokes[0].fill_color, WHITE)
    assert close_color(first.strokes[0].fill_color, (0.2, 0.3, 0.4, 1.0))

    # Additive Drawing copies the previous keyframe first; only the stroke
    # being drawn is new.
    tool_settings.use_gpencil_draw_additive = True
    scene.frame_set(9)
    module._sync_draw_both_fill(bpy.context)
    keyed.strokes[0].fill_color = (0.5, 0.4, 0.3, 1.0)
    additive = layer.frames.new(9).drawing
    additive.add_strokes([3, 3])
    additive.strokes[0].fill_color = (0.5, 0.4, 0.3, 1.0)
    additive.strokes[1].fill_color = BLACK
    assert module._sync_draw_both_fill(bpy.context) == 1
    assert close_color(additive.strokes[0].fill_color, (0.5, 0.4, 0.3, 1.0))
    assert close_color(additive.strokes[1].fill_color, WHITE)
    tool_settings.use_gpencil_draw_additive = False

    # Moving to another keyframe is not a new stroke.
    first.strokes[0].fill_color = BLACK
    scene.frame_set(1)
    module._sync_draw_both_fill(bpy.context)
    assert close_color(first.strokes[0].fill_color, BLACK)
    first.strokes[0].fill_color = (0.2, 0.3, 0.4, 1.0)

    # Switching Draw tool (Fill, Erase, Tint...) activates another brush with
    # its own colors. The Stroke / Fill pair must stay, and the new brush
    # receives it.
    other = bpy.data.brushes.new("FBP Other Draw Brush", mode="PAINT_GREASE_PENCIL")
    other.color = (0.3, 0.6, 0.1)
    other.secondary_color = (0.9, 0.2, 0.5)
    module._sync_paint_state(bpy.context, "DRAW", other, other.gpencil_settings or gp_settings, "STROKE")
    assert close_color(state.stroke_color, BLACK)
    assert close_color(state.fill_color, WHITE)
    assert close_color(other.color, BLACK[:3])
    assert close_color(other.secondary_color, WHITE[:3])
    module._sync_draw_state(bpy.context)
    assert close_color(state.stroke_color, BLACK)
    assert close_color(owner.color, BLACK[:3])

    # Blender pushes the "Toggle Draw Mode" undo step before the add-on swaps
    # the Edit selection's colors back to the paint colors. Undoing the first
    # stroke lands on that step and must not turn the selection's colors into
    # the brush colors.
    assert close_color(state.paint_stroke_color, BLACK)
    assert close_color(state.paint_fill_color, WHITE)
    module._set_state_value(state, "stroke_color", SELECTION_STROKE)
    module._set_state_value(state, "fill_color", SELECTION_FILL)
    assert bpy.ops.ed.undo_push(message="Toggle Draw Mode") == {"FINISHED"}
    module._set_state_value(state, "stroke_color", BLACK)
    module._set_state_value(state, "fill_color", WHITE)
    obj.data.layers.active.current_frame().drawing.add_strokes([2])
    assert bpy.ops.ed.undo_push(message="Draw Stroke") == {"FINISHED"}
    assert bpy.ops.ed.undo() == {"FINISHED"}
    obj = bpy.data.objects["FBP Draw Color Stability"]
    state = obj.fbp_gp_vertex_color_state
    _paint, brush, owner, gp_settings = module._draw_brush_context(bpy.context)
    assert close_color(state.stroke_color, BLACK), tuple(state.stroke_color)
    assert close_color(state.fill_color, WHITE), tuple(state.fill_color)
    assert close_color(owner.color, BLACK[:3]), tuple(owner.color)
    assert close_color(owner.secondary_color, WHITE[:3]), tuple(owner.secondary_color)
    print("FBPTEST gp_draw_color_stability: PASS")
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
