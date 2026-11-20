"""Blender 5.3 Edit Mode header: Stroke/Fill/Both, native Cyclic, Arrange.

On Blender 5.3 the add-on's own Close Gap gives way to Blender's Cyclic
option. Edit Mode gets the native Set Stroke Type, Close/Open and Arrange
operators as header buttons, and the Cyclic button shows whether every
selected stroke is closed.
"""

import importlib
import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy


INSTALLED_PACKAGE = os.environ.get("FBP_TEST_INSTALLED") == "1"
PACKAGE_NAME = os.environ.get(
    "FBP_TEST_PACKAGE",
    "bl_ext.fbp_audit.frame_by_plane" if INSTALLED_PACKAGE else "frame_by_plane",
)
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(PACKAGE_NAME)


class FakeLayout:
    def __init__(self, root=None):
        self.root = root or self
        if root is None:
            self.operators = []
        self.enabled = True

    def row(self, **_kwargs):
        return FakeLayout(self.root)

    def operator(self, operator_id, **kwargs):
        properties = SimpleNamespace()
        self.root.operators.append((operator_id, kwargs, properties))
        return properties


if not INSTALLED_PACKAGE:
    addon.register()
try:
    module = addon.gp_vertex_colors
    if not module.native_cyclic_stroke():
        print("FBPTEST gp_native_edit_tools: SKIP (Blender without native Cyclic)")
    else:
        bpy.ops.object.grease_pencil_add(type="STROKE")
        obj = bpy.context.object
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.grease_pencil.select_all(action="SELECT")
        drawing = obj.data.layers.active.current_frame().drawing
        for stroke in drawing.strokes:
            stroke.cyclic = False

        module._sync_edit_state(bpy.context, force=True)
        assert module._RUNTIME["edit_all_cyclic"] is False

        layout = FakeLayout()
        assert module._draw_header_close_stroke(layout, bpy.context)
        ids = [(op, getattr(props, "type", getattr(props, "direction", None)))
               for op, _kwargs, props in layout.operators]
        assert ids == [
            ("grease_pencil.set_stroke_type", "STROKE"),
            ("grease_pencil.set_stroke_type", "FILL"),
            ("grease_pencil.set_stroke_type", "BOTH"),
            ("grease_pencil.cyclical_set", "CLOSE"),
            ("grease_pencil.reorder", "TOP"),
            ("grease_pencil.reorder", "UP"),
            ("grease_pencil.reorder", "DOWN"),
            ("grease_pencil.reorder", "BOTTOM"),
        ], ids
        cyclic_kwargs = layout.operators[3][1]
        assert cyclic_kwargs["icon"] == "GP_CYCLIC_STROKE"
        assert cyclic_kwargs["depress"] is False

        # The Cyclic button runs Blender's own operator on the selection.
        assert bpy.ops.grease_pencil.cyclical_set(type="CLOSE") == {"FINISHED"}
        drawing = obj.data.layers.active.current_frame().drawing
        assert all(stroke.cyclic for stroke in drawing.strokes)
        module._sync_edit_state(bpy.context, force=True)
        assert module._RUNTIME["edit_all_cyclic"] is True
        layout = FakeLayout()
        module._draw_header_close_stroke(layout, bpy.context)
        assert layout.operators[3][1]["depress"] is True
        assert layout.operators[3][2].type == "OPEN"

        # The add-on's toggle (and so any shortcut to it) follows the same rule.
        assert bpy.ops.fbp.toggle_gp_close_gap() == {"FINISHED"}
        drawing = obj.data.layers.active.current_frame().drawing
        assert not any(stroke.cyclic for stroke in drawing.strokes)

        # Stroke type buttons work on the selection.
        assert bpy.ops.grease_pencil.set_stroke_type(type="FILL") == {"FINISHED"}
        hide = obj.data.layers.active.current_frame().drawing.attributes.get("hide_stroke")
        assert hide is not None and all(item.value for item in hide.data)
        assert bpy.ops.grease_pencil.reorder(direction="TOP") == {"FINISHED"}

        # Draw Mode: new strokes keep the cyclic flag Blender's brush gave them.
        bpy.ops.object.mode_set(mode="PAINT_GREASE_PENCIL")
        state = obj.fbp_gp_vertex_color_state
        state.close_strokes = True  # A file saved with the old Close Gap on.
        module._reset_draw_both_tracking()
        module._sync_draw_both_fill(bpy.context)
        drawing = obj.data.layers.active.current_frame().drawing
        drawing.add_strokes([3])
        drawing.strokes[-1].cyclic = False
        module._sync_draw_both_fill(bpy.context)
        assert drawing.strokes[-1].cyclic is False
        print("FBPTEST gp_native_edit_tools: PASS")
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
