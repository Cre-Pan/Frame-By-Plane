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
shift_a_probe("warmup")

DRAWS = {"drop": 0, "render": 0}


def _count(cls, key):
    original = cls.draw

    def draw(self, context):
        DRAWS[key] += 1
        return original(self, context)

    cls.draw = draw


_count(module.operator_import.FBP_OT_DropMedia, "drop")
_count(module.compositor.FBP_OT_RenderChecked, "render")


def op():
    return module.live_tutorial._ACTIVE_OPERATOR


def start_tutorial():
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
        log("start tutorial ->", bpy.ops.fbp.live_tutorial("INVOKE_DEFAULT"))


def hud_report(label):
    def run():
        o = op()
        hud = getattr(o, "_hud_layout", {}) if o else {}
        log(label, "hud", {k: round(hud[k]) for k in ("x", "y", "width", "height")} if hud else None,
            "scale", round(hud.get("scale", 0), 2) if hud else None,
            "offset", tuple(round(v, 1) for v in o._state.offset) if o else None,
            "collapsed", o._state.collapsed if o else None)
    STEPS.append((run, 0.5))


STEPS.append((start_tutorial, 1.2))
hud_report("initial")


def drag():
    win, area, region = view3d()
    o = op()
    rect = o._state.hitboxes.get("drag_header")
    if rect is None:
        log("drag header missing", sorted(o._state.hitboxes))
        return
    x = int(region.x + rect[0] + 30)
    y = int(region.y + rect[1] + rect[3] * 0.5)
    win.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    win.event_simulate(type="LEFTMOUSE", value="PRESS", x=x, y=y)
    for step_index in range(1, 11):
        win.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x - 20 * step_index, y=y - 15 * step_index)
    win.event_simulate(type="LEFTMOUSE", value="RELEASE", x=x - 200, y=y - 150)
    log("dragged by (-200, -150)")


STEPS.append((drag, 0.8))
hud_report("after-drag")
shift_a_probe("after-drag")



def click(key):
    def run():
        win, area, region = view3d()
        o = op()
        rect = o._state.hitboxes.get(key) if o else None
        if rect is None:
            log("click", key, "missing; hitboxes=", sorted(o._state.hitboxes) if o else None)
            return
        x = int(region.x + rect[0] + rect[2] * 0.5)
        y = int(region.y + rect[1] + rect[3] * 0.5)
        win.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
        win.event_simulate(type="LEFTMOUSE", value="PRESS", x=x, y=y)
        win.event_simulate(type="LEFTMOUSE", value="RELEASE", x=x, y=y)
        log("clicked", key)
    STEPS.append((run, 0.8))


click("control_collapse")
hud_report("collapsed")
shift_a_probe("collapsed")
click("control_collapse")
hud_report("expanded")
click("route_IMAGE")
hud_report("route")
click("control_skip")
hud_report("skipped")
click("control_collapse")
hud_report("route-collapsed")
click("control_close")


def drop_dialog():
    from pathlib import Path
    folder = Path(bpy.app.tempdir or "/tmp") / "fbp_diag_drop"
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("a_0001.png", "a_0002.png"):
        path = folder / name
        if not path.exists():
            image = bpy.data.images.new(name, 16, 8)
            image.filepath_raw = str(path)
            image.file_format = "PNG"
            image.save()
            bpy.data.images.remove(image)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
        result = bpy.ops.fbp.drop_media(
            "INVOKE_DEFAULT", directory=str(folder),
            files=[{"name": "a_0001.png"}, {"name": "a_0002.png"}],
        )
    log("drop invoke ->", result)


STEPS.append((drop_dialog, 1.0))
STEPS.append((lambda: log("drop dialog draws:", DRAWS["drop"]), 0.3))
STEPS.append((lambda: press(view3d()[0], "ESC", view3d()[2].x + 300, view3d()[2].y + 300), 0.8))


def stale_compositor():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_percentage = 5
    scene.fbp_compositor_enabled = True
    scene["fbp_compositor_needs_refresh"] = False
    scene.fbp_compositor_render_enabled = True
    scene["fbp_compositor_needs_refresh"] = True
    log("out of date:", module.compositor.fbp_compositor_render_out_of_date(scene))
    win, area, region = view3d()
    press(win, "F12", region.x + region.width // 2, region.y + region.height // 2)


STEPS.append((stale_compositor, 1.0))
STEPS.append((lambda: log("F12 popup draws:", DRAWS["render"], "modal_ops", [o.bl_idname for o in view3d()[0].modal_operators]), 0.3))
STEPS.append((lambda: press(view3d()[0], "ESC", 5, 5), 0.8))


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
