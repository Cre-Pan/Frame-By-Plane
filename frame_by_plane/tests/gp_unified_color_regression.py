"""Stroke/Fill colors reach the colors Blender paints with under Unified Color.

Blender 5.3 keeps the Unified Color switch on the brush and paints with the
paint mode's unified settings while it is on (the Vertex Paint brush has it on
by default). Frame By Plane must write the Stroke/Fill pair there, not into
the brush's own colors, or the header shows one pair while strokes get another.
"""

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


RED = (1.0, 0.0, 0.0, 1.0)
BLUE = (0.0, 0.2, 1.0, 1.0)


def check_mode(module, obj, mode, paint_name, use_unified):
    bpy.ops.object.mode_set(mode=mode)
    paint = getattr(bpy.context.scene.tool_settings, paint_name)
    brush = paint.brush
    assert brush is not None, f"{mode}: no brush"
    if not hasattr(brush, "use_unified_color"):
        # Blender 5.2 keeps the switch on the unified settings only.
        paint.unified_paint_settings.use_unified_color = use_unified
    else:
        brush.use_unified_color = use_unified
    module.fbp_gp_brush_color_timer()
    state = obj.fbp_gp_vertex_color_state
    state.stroke_color = RED
    state.fill_color = BLUE
    module.fbp_gp_brush_color_timer()
    unified = paint.unified_paint_settings
    painted = unified if use_unified else brush
    _kind, _paint, _brush, owner, _settings, target = module._semantic_brush_context(bpy.context)
    assert owner == painted, (mode, use_unified, owner)
    primary, secondary = (BLUE, RED) if target == "FILL" else (RED, BLUE)
    assert close_color(painted.color, primary[:3]), (mode, use_unified, tuple(painted.color))
    assert close_color(painted.secondary_color, secondary[:3]), (
        mode, use_unified, tuple(painted.secondary_color)
    )
    # Native X swaps the colors Blender paints with; Stroke/Fill follow.
    painted.color, painted.secondary_color = tuple(painted.secondary_color), tuple(painted.color)
    module.fbp_gp_brush_color_timer()
    assert close_color(state.stroke_color, BLUE), (mode, use_unified, tuple(state.stroke_color))
    assert close_color(state.fill_color, RED), (mode, use_unified, tuple(state.fill_color))
    bpy.ops.object.mode_set(mode="OBJECT")


if not INSTALLED_PACKAGE:
    addon.register()
try:
    module = addon.gp_vertex_colors
    bpy.ops.object.grease_pencil_add(type="STROKE")
    obj = bpy.context.object
    for use_unified in (True, False):
        check_mode(module, obj, "PAINT_GREASE_PENCIL", "gpencil_paint", use_unified)
        check_mode(module, obj, "VERTEX_GREASE_PENCIL", "gpencil_vertex_paint", use_unified)
    print("FBPTEST gp_unified_color: PASS")
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
