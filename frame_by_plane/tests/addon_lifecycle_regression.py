import importlib
import os
import sys
from pathlib import Path

import bpy
import bl_ui.properties_paint_common as paint_common
import bl_ui.space_view3d as space_view3d


INSTALLED_PACKAGE = os.environ.get("FBP_TEST_INSTALLED") == "1"
PACKAGE_NAME = os.environ.get(
    "FBP_TEST_PACKAGE",
    "bl_ext.fbp_audit.frame_by_plane" if INSTALLED_PACKAGE else "frame_by_plane",
)
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(PACKAGE_NAME)
native_draw_selector = paint_common.brush_basic__draw_color_selector
native_paint_settings = paint_common.brush_basic_grease_pencil_paint_settings
native_vertex_settings = vars(space_view3d._draw_tool_settings_context_mode)["VERTEX_GREASE_PENCIL"]
assert "EDIT_GREASE_PENCIL" not in vars(space_view3d._draw_tool_settings_context_mode)


def addon_handler_count():
    total = 0
    for name in dir(bpy.app.handlers):
        handlers = getattr(bpy.app.handlers, name, None)
        if not isinstance(handlers, list):
            continue
        total += sum(
            str(getattr(callback, "__module__", "")).startswith("frame_by_plane")
            for callback in handlers
        )
    return total


for cycle in range(1, 4):
    addon.register()
    registered_handlers = addon_handler_count()
    assert hasattr(bpy.types.Scene, "fbp_compositor_render_enabled")
    assert addon.gp_vertex_colors._HEADER_REGISTERED is True
    assert bpy.app.timers.is_registered(addon.gp_vertex_colors.fbp_gp_brush_color_timer)
    assert len(addon.gp_vertex_colors._ADDON_KEYMAPS) == 3
    assert paint_common.brush_basic__draw_color_selector is addon.gp_vertex_colors._draw_native_draw_color_selector
    addon.unregister()
    remaining_handlers = addon_handler_count()
    assert not hasattr(bpy.types.Scene, "fbp_compositor_render_enabled")
    assert addon.gp_vertex_colors._HEADER_REGISTERED is False
    assert not bpy.app.timers.is_registered(addon.gp_vertex_colors.fbp_gp_brush_color_timer)
    assert addon.gp_vertex_colors._ADDON_KEYMAPS == []
    assert paint_common.brush_basic__draw_color_selector is native_draw_selector
    assert paint_common.brush_basic_grease_pencil_paint_settings is native_paint_settings
    assert vars(space_view3d._draw_tool_settings_context_mode)["VERTEX_GREASE_PENCIL"] is native_vertex_settings
    assert "EDIT_GREASE_PENCIL" not in vars(space_view3d._draw_tool_settings_context_mode)
    assert remaining_handlers == 0
    print(
        f"FBPTEST lifecycle_cycle_{cycle}: "
        f"registered_handlers={registered_handlers}, remaining_handlers={remaining_handlers}"
    )
