"""Link Timelines: every time editor keeps each frame at the same screen x.

Needs a window (the link works on editor regions), so it does not run in the
background feature gate. On Linux without a display:
    xvfb-run -a -s "-screen 0 1600x1000x24" blender --factory-startup \
        --python-exit-code 1 --python frame_by_plane/tests/timeline_link_regression.py

Checks, on the factory Layout screen split into a Timeline and a Graph Editor:

* the toggle is on by default and the native Sync Visible Range gets switched off;
* the two editors line up although their channel lists differ;
* hiding the Graph Editor channel list makes it lead and the Timeline follows;
* zooming/panning either editor makes it lead; opening a sidebar moves nothing;
* with the toggle off nothing follows; turning it back on realigns;
* unregister removes the property and the header buttons.
"""

import importlib
import os
import sys
import traceback
from pathlib import Path

import bpy


PACKAGE_NAME = os.environ.get("FBP_TEST_PACKAGE", "frame_by_plane")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(PACKAGE_NAME)
addon.register()
link = importlib.import_module(f"{PACKAGE_NAME}.timeline_link")

TOLERANCE_PX = 1.5
FAILURES = []


def _regions():
    window = bpy.context.window_manager.windows[0]
    found = []
    for area in window.screen.areas:
        if area.type in {"DOPESHEET_EDITOR", "GRAPH_EDITOR"}:
            region = next(region for region in area.regions if region.type == "WINDOW")
            found.append((area, region))
    return window, found


def _screen_x(region, frame):
    view = region.view2d
    left = view.region_to_view(0.0, 0.0)[0]
    right = view.region_to_view(float(region.width), 0.0)[0]
    return region.x + (frame - left) * region.width / (right - left)


def _aligned():
    _window, found = _regions()
    (_a, first), (_b, second) = found[:2]
    return all(abs(_screen_x(first, f) - _screen_x(second, f)) <= TOLERANCE_PX for f in (1, 50, 120))


def _check(name, condition):
    print(("[PASS] " if condition else "[FAIL] ") + name, flush=True)
    if not condition:
        FAILURES.append(name)


def _op(area_index, operator, **kwargs):
    window, found = _regions()
    area, region = found[area_index]
    with bpy.context.temp_override(window=window, area=area, region=region):
        operator(**kwargs)


def step_split():
    wm = bpy.context.window_manager
    _check("toggle on by default", bool(getattr(wm, link.LINK_PROPERTY, False)))
    window = wm.windows[0]
    area = next(area for area in window.screen.areas if area.type == "DOPESHEET_EDITOR")
    with bpy.context.temp_override(window=window, area=area):
        bpy.ops.screen.area_split(direction="HORIZONTAL", factor=0.5)
    _window, found = _regions()
    found[1][0].type = "GRAPH_EDITOR"
    found[0][0].spaces.active.show_locked_time = True


def step_initial():
    _window, found = _regions()
    _check("editors differ in channel width", found[0][1].x != found[1][1].x)
    _check("aligned after split", _aligned())
    _check("native sync off", not any(area.spaces.active.show_locked_time for area, _r in found))
    found[0][0].spaces.active.show_region_ui = True
    STATE["before_sidebar"] = [_screen_x(region, 50) for _a, region in found]


def step_sidebar():
    _window, found = _regions()
    after = [_screen_x(region, 50) for _a, region in found]
    _check("sidebar moves nothing", all(abs(a - b) <= TOLERANCE_PX for a, b in zip(after, STATE["before_sidebar"])))
    STATE["timeline_x"] = _screen_x(found[0][1], 50)
    found[1][0].spaces.active.show_region_channels = False


def step_channels():
    _window, found = _regions()
    _check("channel list resize leads", abs(_screen_x(found[0][1], 50) - STATE["timeline_x"]) > 5)
    _check("aligned after channel resize", _aligned())
    _op(1, bpy.ops.view2d.zoom, deltax=40, deltay=0)
    _op(1, bpy.ops.view2d.pan, deltax=120, deltay=0)


def step_graph_zoom():
    _check("aligned after Graph Editor zoom", _aligned())
    _op(0, bpy.ops.view2d.pan, deltax=-200, deltay=0)


def step_timeline_pan():
    _check("aligned after Timeline pan", _aligned())
    bpy.context.window_manager.fbp_link_timelines = False
    _op(0, bpy.ops.view2d.pan, deltax=-300, deltay=0)


def step_off():
    _check("toggle off leaves editors alone", not _aligned())
    bpy.context.window_manager.fbp_link_timelines = True


def step_on_again():
    _check("realigned when turned back on", _aligned())
    addon.unregister()
    wm = bpy.context.window_manager
    _check("property removed", not hasattr(bpy.types.WindowManager, link.LINK_PROPERTY))
    callbacks = getattr(bpy.types.DOPESHEET_HT_header.draw, "_draw_funcs", ()) or ()
    _check("header button removed", not any(getattr(cb, "__name__", "") == "draw_link_toggle" for cb in callbacks))
    del wm


STATE = {}
STEPS = [step_split, step_initial, step_sidebar, step_channels, step_graph_zoom, step_timeline_pan, step_off, step_on_again]


def _finish():
    if FAILURES:
        print("Timeline link regression failed: " + ", ".join(FAILURES), flush=True)
        sys.stdout.flush()
        os._exit(1)
    print("Timeline link regression passed", flush=True)
    bpy.ops.wm.quit_blender()


def _runner():
    try:
        STEPS.pop(0)()
    except Exception:
        traceback.print_exc()
        FAILURES.append("exception")
        STEPS.clear()
    if STEPS:
        return 0.6
    _finish()
    return None


bpy.app.timers.register(_runner, first_interval=1.0)
