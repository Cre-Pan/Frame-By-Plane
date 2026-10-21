"""Diagnostic: draw the Modifiers-tab effect panels of the new 8.0 effects."""
import importlib.util
import os
import sys
import time
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
geometry = module.geometry_nodes
builder = module.builder


def log(*args):
    print("DIAG", *args, flush=True)


STATE = {}
WORK = Path(bpy.app.tempdir or "/tmp") / "fbp_diag_fx"
WORK.mkdir(parents=True, exist_ok=True)


def make_images():
    names = []
    for index, color in enumerate(((1, 0, 0), (0, 1, 0), (0, 0, 1)), 1):
        name = f"seq_{index:04d}.png"
        names.append(name)
        image = bpy.data.images.new(name, 32, 18, alpha=True)
        image.generated_color = (*color, 1.0)
        image.filepath_raw = str(WORK / name)
        image.file_format = "PNG"
        image.save()
        bpy.data.images.remove(image)
    return names


def setup():
    names = make_images()
    seq = builder.build_fbp_rig(bpy.context, "Seq", str(WORK), names, (0.0, 0.0, 0.0))
    still = builder.build_fbp_rig(bpy.context, "Still", str(WORK), [names[0]], (2.0, 0.0, 0.0))
    STATE["seq"], STATE["still"] = seq.name, still.name
    log("frame stack added", geometry.fbp_add_effect(seq, "FRAME_STACK", select_object_mask_helper=False, inherit_active_group=False))
    log("knit added", geometry.fbp_add_effect(still, "KNIT_CROCHET", select_object_mask_helper=False, inherit_active_group=False))
    window = bpy.context.window_manager.windows[0]
    properties = next((area for area in window.screen.areas if area.type == "PROPERTIES"), None)
    if properties is not None:
        properties.spaces.active.context = "MODIFIER"
    log("properties area", properties is not None)


def show(name):
    def run():
        obj = bpy.data.objects[STATE[name]]
        for other in bpy.context.view_layer.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for area in bpy.context.window_manager.windows[0].screen.areas:
            area.tag_redraw()
        log("active", obj.name)
    return run


def toggles():
    still = bpy.data.objects[STATE["still"]]
    still.fbp_yarn_stitch_type = "CROCHET"
    seq = bpy.data.objects[STATE["seq"]]
    seq.fbp_frame_stack_outline = True
    seq.fbp_frame_stack_glow = True
    for area in bpy.context.window_manager.windows[0].screen.areas:
        area.tag_redraw()
    log("toggled")


STEPS = [
    (lambda: log("ready"), 1.0),
    (setup, 2.0),
    (show("seq"), 1.5),
    (lambda: bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=3), 1.0),
    (show("still"), 1.5),
    (lambda: bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=3), 1.0),
    (toggles, 1.5),
    (lambda: bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=3), 1.0),
    (show("seq"), 1.5),
    (lambda: bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=3), 1.0),
    (lambda: (log("done"), bpy.ops.wm.quit_blender()), 0.5),
]
INDEX = {"i": 0}


def tick():
    if INDEX["i"] >= len(STEPS):
        return None
    fn, delay = STEPS[INDEX["i"]]
    INDEX["i"] += 1
    try:
        fn()
    except Exception as exc:
        import traceback
        log("step error", INDEX["i"] - 1, repr(exc))
        traceback.print_exc()
    return delay


bpy.app.timers.register(tick, first_interval=2.0)
