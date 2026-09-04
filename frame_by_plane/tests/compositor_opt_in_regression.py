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


def report(label, value):
    print(f"FBPTEST {label}: {value!r}")


addon = importlib.import_module(PACKAGE_NAME)
scene = bpy.context.scene
report("native_before_register", scene.render.use_compositing)
report("group_before_register", scene.compositing_node_group)
native_before = bool(scene.render.use_compositing)
film_before = bool(scene.render.film_transparent)
group_before = scene.compositing_node_group

try:
    if not INSTALLED_PACKAGE:
        addon.register()
    report("native_after_register", scene.render.use_compositing)
    report("preview_default", scene.fbp_experimental_compositor)
    report(
        "render_opt_in_default",
        getattr(scene, "fbp_compositor_render_enabled", "MISSING"),
    )
    assert scene.fbp_experimental_compositor is False
    assert scene.fbp_compositor_render_enabled is False
    assert bool(scene.render.use_compositing) is native_before

    scene.fbp_experimental_compositor = True
    item = scene.fbp_compositor_layers.add()
    item.name = "Test Layer"
    item.layer_name = "Test Layer"
    item.collection = scene.collection

    result = addon.compositor.fbp_sync_compositor(
        scene,
        context=bpy.context,
        native_group=False,
        activate_compositor=True,
    )
    report("sync_result", result)
    report("native_after_first_sync", scene.render.use_compositing)
    report("managed_after_first_sync", scene.fbp_compositor_enabled)
    report("film_after_first_sync", scene.render.film_transparent)
    assert scene.fbp_compositor_enabled is True
    assert scene.render.use_compositing is False
    assert bool(scene.render.film_transparent) is film_before

    scene.fbp_compositor_render_enabled = True
    report("native_after_opt_in", scene.render.use_compositing)
    report("film_after_opt_in", scene.render.film_transparent)
    assert scene.render.use_compositing is True
    assert scene.render.film_transparent is True

    scene.fbp_compositor_render_enabled = False
    report("native_after_opt_out", scene.render.use_compositing)
    report("film_after_opt_out", scene.render.film_transparent)
    assert scene.render.use_compositing is False
    assert bool(scene.render.film_transparent) is film_before

    managed_tree = scene.compositing_node_group
    artist_tree = bpy.data.node_groups.new("Artist Compositor Test", "CompositorNodeTree")
    scene.compositing_node_group = artist_tree
    scene.render.use_compositing = False
    scene.fbp_compositor_render_enabled = True
    report("native_with_artist_graph", scene.render.use_compositing)
    assert scene.render.use_compositing is False
    scene.fbp_compositor_render_enabled = False
    scene.compositing_node_group = managed_tree
    scene.render.use_compositing = False

    addon.compositor.fbp_restore_compositor(scene)
    report("native_after_restore", scene.render.use_compositing)
    report("group_after_restore", scene.compositing_node_group)
    assert bool(scene.render.use_compositing) is native_before
    assert bool(scene.render.film_transparent) is film_before
    assert scene.compositing_node_group is group_before
    assert scene.fbp_compositor_enabled is False
except Exception:
    traceback.print_exc()
    raise
finally:
    if not INSTALLED_PACKAGE:
        try:
            addon.unregister()
        except Exception:
            traceback.print_exc()
