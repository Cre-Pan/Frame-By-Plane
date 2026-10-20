"""Diagnostic: do image planes draw pink (missing texture) after Undo?"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import bpy

sys.dont_write_bytecode = True
SOURCE = Path(os.environ["FBP_DIAG_SOURCE"]).resolve()
FIX = os.environ.get("FBP_DIAG_FIX", "1") == "1"
spec = importlib.util.spec_from_file_location(
    "frame_by_plane", SOURCE / "__init__.py", submodule_search_locations=[str(SOURCE)]
)
module = importlib.util.module_from_spec(spec)
sys.modules["frame_by_plane"] = module
spec.loader.exec_module(module)
module.register()
if not FIX:
    module.handlers._fbp_refresh_animated_image_frames = lambda scene: None

WORK = Path(tempfile.mkdtemp(prefix="fbp_pink_"))
SHOTS = WORK / "shots"
SHOTS.mkdir()


def log(*args):
    print("DIAG", "fix" if FIX else "nofix", *args, flush=True)


def write_png(path, color):
    image = bpy.data.images.new(path.stem, 64, 64, alpha=True)
    image.generated_color = color
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def build_fixture():
    root = WORK / "project"
    (root / "02_Seq").mkdir(parents=True)
    write_png(root / "01_BG.png", (0.1, 0.8, 0.2, 1.0))
    for index in range(1, 5):
        write_png(root / "02_Seq" / f"seq_{index:04d}.png", (0.1, 0.2, 0.3 + 0.15 * index, 1.0))
    return root


def view3d():
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    region = next(r for r in area.regions if r.type == "WINDOW")
    return win, area, region


def press(key, **mods):
    win, area, region = view3d()
    x = region.x + region.width // 2
    y = region.y + region.height // 2
    win.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    win.event_simulate(type=key, value="PRESS", x=x, y=y, **mods)
    win.event_simulate(type=key, value="RELEASE", x=x, y=y, **mods)


def magenta(label):
    win, area, region = view3d()
    path = SHOTS / f"{label}.png"
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.screen.screenshot_area(filepath=str(path))
    image = bpy.data.images.load(str(path))
    pixels = list(image.pixels)
    count = green = blue = 0
    total = len(pixels) // 4
    for index in range(0, len(pixels), 4):
        r, g, b = pixels[index], pixels[index + 1], pixels[index + 2]
        if r > 0.8 and b > 0.8 and g < 0.25:
            count += 1
        elif g > 0.6 and r < 0.3 and b < 0.4:
            green += 1
        elif b > 0.5 and r < 0.3 and g < 0.4:
            blue += 1
    bpy.data.images.remove(image)
    return count, f"{total} green {green} blue {blue}"


def evaluated_frames():
    depsgraph = bpy.context.evaluated_depsgraph_get()
    rows = []
    for material in bpy.data.materials:
        if not material.users or not material.node_tree:
            continue
        evaluated = material.evaluated_get(depsgraph)
        for node in evaluated.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                rows.append((material.name, node.image.source, node.image_user.frame_current, node.image.has_data))
    return rows


def report(label):
    count, total = magenta(label)
    obj = bpy.context.object
    log(label, "mode", obj.mode if obj else None, "objects", len(bpy.context.scene.objects), "frame", bpy.context.scene.frame_current, "magenta_px", count, "of", total, "images", evaluated_frames())


STEPS = []


def step(delay):
    def wrap(fn):
        STEPS.append((fn, delay))
        return fn
    return wrap


@step(1.0)
def setup():
    win, area, region = view3d()
    area.spaces.active.shading.type = "MATERIAL"
    root = build_fixture()
    bpy.context.scene.frame_set(3)
    with bpy.context.temp_override(window=win, area=area, region=region):
        result = bpy.ops.fbp.popup_multiplane("EXEC_DEFAULT", folder=str(root), animation=True)
    log("multiplane", result)


@step(6.0)
def frame_view():
    win, area, region = view3d()
    for obj in bpy.context.scene.objects:
        obj.select_set(obj.type == "MESH" and obj.name != "Cube")
    cube = bpy.data.objects.get("Cube")
    if cube:
        cube.hide_set(True)
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.view3d.view_selected()
    bpy.ops.ed.undo_push(message="Diag multiplane")


@step(8.0)
def before():
    report("1_after_multiplane")
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        result = bpy.ops.fbp.add_grease_pencil_canvas("EXEC_DEFAULT", enter_draw_mode=os.environ.get("FBP_DIAG_DRAW", "1") == "1")
    log("gp", result)
    bpy.ops.ed.undo_push(message="Diag GP plane")


@step(4.0)
def undo():
    report("2_after_gp")
    press("Z", ctrl=True)


@step(1.0)
def soon():
    report("3_undo_after_1s")


@step(6.0)
def later():
    report("4_undo_after_7s")
    press("Z", ctrl=True)


@step(6.0)
def second_undo():
    report("4b_second_undo_after_6s")
    bpy.context.scene.frame_set(bpy.context.scene.frame_current + 1)


@step(4.0)
def moved():
    report("5_after_frame_change")


@step(0.5)
def done():
    log("done")
    bpy.ops.wm.quit_blender()


def run(index=0):
    if index >= len(STEPS):
        return None
    fn, delay = STEPS[index]
    try:
        fn()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        log("step failed", fn.__name__, repr(exc))
    bpy.app.timers.register(lambda: run(index + 1), first_interval=delay)
    return None


bpy.app.timers.register(lambda: run(0), first_interval=2.0)
