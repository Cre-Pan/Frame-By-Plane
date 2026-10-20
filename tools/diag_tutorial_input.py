"""Diagnostic: do keyboard shortcuts reach Blender while the live tutorial runs?"""
import importlib.util
import os
import sys
from pathlib import Path

import bpy

sys.dont_write_bytecode = True
SOURCE = Path(os.environ["FBP_DIAG_SOURCE"]).resolve()
spec = importlib.util.spec_from_file_location(
    "frame_by_plane", SOURCE / "__init__.py", submodule_search_locations=[str(SOURCE)]
)
module = importlib.util.module_from_spec(spec)
sys.modules["frame_by_plane"] = module
spec.loader.exec_module(module)
module.register()

DRAWN = {"count": 0}


def _spy(self, context):
    DRAWN["count"] += 1


bpy.types.VIEW3D_MT_add.append(_spy)


def log(*args):
    print("DIAG", *args, flush=True)


def view3d():
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    region = next(r for r in area.regions if r.type == "WINDOW")
    return win, area, region


def press(win, key, x, y, **mods):
    win.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    win.event_simulate(type=key, value="PRESS", x=x, y=y, **mods)
    win.event_simulate(type=key, value="RELEASE", x=x, y=y, **mods)


STEPS = []
STATE = {"index": 0, "before": 0}


def step(delay=0.8):
    def wrap(fn):
        STEPS.append((fn, delay))
        return fn
    return wrap


def shift_a_probe(label, where="center"):
    def start():
        win, area, region = view3d()
        x = region.x + region.width // 2
        y = region.y + region.height // 3
        if where == "hud":
            op = module.live_tutorial._ACTIVE_OPERATOR
            hud = getattr(op, "_hud_layout", {}) if op else {}
            if hud:
                x = int(region.x + hud["x"] + hud["width"] * 0.3)
                y = int(region.y + hud["y"] + hud["height"] * 0.5)
        STATE["before"] = DRAWN["count"]
        log(label, "press Shift+A at", x, y, "modal_ops=", [o.bl_idname for o in win.modal_operators])
        press(win, "A", x, y, shift=True)

    def check():
        win, area, region = view3d()
        opened = DRAWN["count"] > STATE["before"]
        log(label, "Shift+A menu drawn:", opened, "draws=", DRAWN["count"] - STATE["before"])
        press(win, "ESC", region.x + 5, region.y + 5)

    STEPS.append((start, 0.6))
    STEPS.append((check, 0.6))


def tab_probe(label):
    def start():
        win, area, region = view3d()
        cube = bpy.data.objects.get("Cube")
        if cube is not None:
            bpy.context.view_layer.objects.active = cube
            cube.select_set(True)
        STATE["mode"] = bpy.context.object.mode if bpy.context.object else None
        press(win, "TAB", region.x + region.width // 2, region.y + region.height // 3)

    def check():
        obj = bpy.context.view_layer.objects.active
        log(label, "Tab toggled mode:", STATE["mode"], "->", obj.mode if obj else None)
        if obj is not None and obj.mode != "OBJECT":
            win, area, region = view3d()
            press(win, "TAB", region.x + region.width // 2, region.y + region.height // 3)

    STEPS.append((start, 0.6))
    STEPS.append((check, 0.6))


STEPS.append((lambda: log("ready"), 1.5))
shift_a_probe("control")
tab_probe("control")


def start_tutorial():
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
        log("start tutorial ->", bpy.ops.fbp.live_tutorial("INVOKE_DEFAULT"))


STEPS.append((start_tutorial, 1.2))
shift_a_probe("tutorial-chooser")
shift_a_probe("tutorial-chooser-over-hud", where="hud")
tab_probe("tutorial-chooser")


def enter_route():
    op = module.live_tutorial._ACTIVE_OPERATOR
    if op is not None:
        op._state.enter_route(bpy.context, "IMAGE")
    log("entered IMAGE route", op is not None)


STEPS.append((enter_route, 1.0))
shift_a_probe("tutorial-step")
tab_probe("tutorial-step")


def stop_timer():
    op = module.live_tutorial._ACTIVE_OPERATOR
    if op is not None and op._timer is not None:
        bpy.context.window_manager.event_timer_remove(op._timer)
        op._timer = None
    log("tutorial timer removed")


STEPS.append((stop_timer, 0.8))
shift_a_probe("tutorial-no-timer")


def finish():
    log("done")
    bpy.ops.wm.quit_blender()


STEPS.append((finish, 0.5))


def tick():
    index = STATE["index"]
    if index >= len(STEPS):
        return None
    fn, delay = STEPS[index]
    STATE["index"] = index + 1
    try:
        fn()
    except Exception as exc:  # report and continue
        import traceback
        log("step error", index, repr(exc))
        traceback.print_exc()
    return delay


bpy.app.timers.register(tick, first_interval=2.0)
