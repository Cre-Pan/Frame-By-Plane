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
ui = importlib.import_module(f"{PACKAGE_NAME}.ui")


try:
    if not INSTALLED_PACKAGE:
        addon.register()
    panel = ui.FBP_PT_ImagePlaneData
    assert panel.bl_space_type == "PROPERTIES"
    assert panel.bl_region_type == "WINDOW"
    assert panel.bl_context == "data"
    assert panel in ui.ui_classes
    assert panel in ui._all_properties_order_classes()

    rig = bpy.data.objects.new("FBP Image Properties Rig", None)
    mesh = bpy.data.meshes.new("FBP Image Properties Mesh")
    plane = bpy.data.objects.new("FBP Image Properties Plane", mesh)
    unrelated_mesh = bpy.data.meshes.new("FBP Unrelated Mesh")
    unrelated = bpy.data.objects.new("FBP Unrelated", unrelated_mesh)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.scene.collection.objects.link(plane)
    bpy.context.scene.collection.objects.link(unrelated)
    rig.is_fbp_control = True
    rig.fbp_plane_target = plane
    plane.is_fbp_plane = True
    plane.parent = rig

    bpy.context.view_layer.objects.active = plane
    plane.select_set(True)
    assert ui._fbp_image_properties_rig(bpy.context) == rig
    assert panel.poll(bpy.context) is True

    bpy.context.view_layer.objects.active = rig
    assert ui._fbp_image_properties_rig(bpy.context) == rig
    assert panel.poll(bpy.context) is True

    bpy.context.view_layer.objects.active = unrelated
    assert ui._fbp_image_properties_rig(bpy.context) is None
    assert panel.poll(bpy.context) is False

    bpy.utils.register_class(panel)
    bpy.utils.unregister_class(panel)
    print("FBPTEST image_properties_panel: PASS")
except Exception:
    traceback.print_exc()
    raise
finally:
    try:
        if getattr(bpy.types, "FBP_PT_ImagePlaneData", None) is not None:
            bpy.utils.unregister_class(ui.FBP_PT_ImagePlaneData)
    except Exception:
        traceback.print_exc()
    if not INSTALLED_PACKAGE:
        try:
            addon.unregister()
        except Exception:
            traceback.print_exc()
