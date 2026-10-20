"""Diagnostic: Generate Layers and Add Effect in the FBP compositor (GUI)."""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import bpy

sys.dont_write_bytecode = True
SOURCE = Path(os.environ["FBP_DIAG_SOURCE"]).resolve()
FIX = os.environ.get("FBP_DIAG_FIX", "1") == "1"
EDITOR = os.environ.get("FBP_DIAG_EDITOR", "0") == "1"
spec = importlib.util.spec_from_file_location(
    "frame_by_plane", SOURCE / "__init__.py", submodule_search_locations=[str(SOURCE)]
)
module = importlib.util.module_from_spec(spec)
sys.modules["frame_by_plane"] = module
spec.loader.exec_module(module)
module.register()
comp = module.compositor
if not FIX:
    def _old_show_root_tree(context, override, space, tree):
        with context.temp_override(**override):
            for _step in range(32):
                if getattr(space, "edit_tree", None) is tree:
                    break
                result = bpy.ops.node.group_edit(exit=True)
                if 'FINISHED' not in result:
                    break
        return getattr(space, "edit_tree", None) is tree
    comp._show_root_tree = _old_show_root_tree
else:
    _real_show_root_tree = comp._show_root_tree

    def _traced_show_root_tree(context, override, space, tree):
        def name(value):
            return getattr(value, "name", None) if value is not None else None
        log("before", "tree", name(tree), "edit", name(getattr(space, "edit_tree", None)),
            "node_tree", name(getattr(space, "node_tree", None)), "pin", getattr(space, "pin", None),
            "path", [name(item.node_tree) for item in getattr(space, "path", ())],
            "scene group", name(getattr(bpy.context.scene, "compositing_node_group", None)),
            "area", getattr(override.get("area"), "type", None), "ui", getattr(override.get("area"), "ui_type", None))
        try:
            space.path.start(tree)
            log("path.start ok", "edit", name(getattr(space, "edit_tree", None)), "node_tree", name(getattr(space, "node_tree", None)))
        except Exception as exc:
            log("path.start EXC", repr(exc))
        result = _real_show_root_tree(context, override, space, tree)
        log("after", result, "edit", name(getattr(space, "edit_tree", None)))
        return result
    comp._show_root_tree = _traced_show_root_tree

WORK = Path(tempfile.mkdtemp(prefix="fbp_comp_"))


def log(*args):
    print("DIAG", "fix" if FIX else "nofix", "editor" if EDITOR else "noeditor", *args, flush=True)


def write_png(path, color):
    image = bpy.data.images.new(path.stem, 64, 64, alpha=True)
    image.generated_color = color
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def view3d():
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    region = next(r for r in area.regions if r.type == "WINDOW")
    return win, area, region


def call(label, op, **kwargs):
    win, area, region = view3d()
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            result = op("EXEC_DEFAULT", **kwargs)
        log(label, result)
    except Exception as exc:
        log(label, "EXC", repr(exc))


STEPS = []


def step(delay):
    def wrap(fn):
        STEPS.append((fn, delay))
        return fn
    return wrap


@step(1.0)
def setup():
    root = WORK / "project"
    root.mkdir(parents=True)
    write_png(root / "01_BG.png", (0.1, 0.8, 0.2, 1.0))
    write_png(root / "02_FG.png", (0.8, 0.2, 0.1, 1.0))
    call("multiplane", bpy.ops.fbp.popup_multiplane, folder=str(root), animation=False)
    if EDITOR:
        win = bpy.context.window_manager.windows[0]
        area = min((a for a in win.screen.areas if a.type != "VIEW_3D"), key=lambda a: a.width * a.height)
        area.type = "NODE_EDITOR"
        area.spaces.active.tree_type = "CompositorNodeTree"
        log("opened editor", area.ui_type)


@step(4.0)
def enable():
    call("compositor_toggle", bpy.ops.fbp.compositor_toggle)


@step(3.0)
def generate():
    call("auto_layers", bpy.ops.fbp.compositor_auto_layers)


@step(3.0)
def add_effect():
    scene = bpy.context.scene
    log("rows", len(scene.fbp_compositor_layers), "index", scene.fbp_compositor_layer_index)
    if scene.fbp_compositor_layers:
        scene.fbp_compositor_layer_index = 0
    call("add_glow", bpy.ops.fbp.compositor_effect_action, action="ADD", effect_type="GLOW")


@step(3.0)
def inspect():
    scene = bpy.context.scene
    effects = [len(item.effects) for item in scene.fbp_compositor_layers]
    log("effects per row", effects)
    tree = getattr(scene, "compositing_node_group", None) or getattr(scene, "node_tree", None)
    if tree is not None:
        log("root nodes", sorted(node.bl_idname for node in tree.nodes))
    win = bpy.context.window_manager.windows[0]
    log("areas", [a.type for a in win.screen.areas])


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
