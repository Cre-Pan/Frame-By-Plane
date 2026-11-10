"""Plane Material: the Layer Settings blocks duplicated at the top of Properties > Material."""

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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_layout_stub import StubLayout  # noqa: E402

addon = importlib.import_module(PACKAGE_NAME)
ui = importlib.import_module(f"{PACKAGE_NAME}.ui")


def _texts(layout):
    """Every text= keyword the stub layout recorded."""
    return [str(kwargs.get("text")) for _name, _args, kwargs in layout.calls if kwargs.get("text")]


def _activate(obj):
    for other in bpy.context.scene.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


try:
    if not INSTALLED_PACKAGE:
        addon.register()

    panels = ui.plane_material_panels
    assert {cls.bl_parent_id for cls in panels} == {
        "EEVEE_MATERIAL_PT_context_material",
        "CYCLES_PT_context_material",
    }
    for cls in panels:
        assert cls.bl_space_type == "PROPERTIES"
        assert cls.bl_context == "material"
        assert cls.bl_label == "Plane Material"
        assert cls not in ui.ui_classes
        parent = getattr(bpy.types, cls.bl_parent_id, None)
        assert parent is not None, cls.bl_parent_id
        bpy.utils.register_class(cls)
        bpy.utils.unregister_class(cls)
    assert set(ui._fbp_available_plane_material_panels()) == set(panels)

    scene = bpy.context.scene
    bpy.ops.object.camera_add()
    scene.camera = bpy.context.object

    procedural = importlib.import_module(f"{PACKAGE_NAME}.operator_procedural")
    rig = procedural.fbp_create_color_plane(bpy.context, "GRADIENT")
    plane = rig.fbp_plane_target
    assert plane is not None and plane.type == "MESH"

    # Only the mesh shows a Material tab; the rig (an Empty) resolves too.
    _activate(plane)
    assert panels[0].poll(bpy.context)
    stub = StubLayout()
    ui._fbp_draw_plane_material(stub, bpy.context, rig)
    texts = _texts(stub)
    assert "Opacity" in texts, texts
    assert "Gradient" in texts and "Position" in texts, texts
    assert "Rig Shape" not in texts and "Transform" not in texts, texts

    camera = scene.camera
    _activate(camera)
    assert not panels[0].poll(bpy.context)

    # Switching to Color redraws the swatch instead of the ramp.
    _activate(plane)
    rig.fbp_color_plane_mode = "SOLID"
    stub = StubLayout()
    ui._fbp_draw_plane_material(stub, bpy.context, rig)
    assert "Color" in _texts(stub)

    print("FBPTEST plane_material_panel: PASS")
except Exception:
    traceback.print_exc()
    raise
finally:
    for cls in getattr(ui, "plane_material_panels", ()):
        try:
            if getattr(bpy.types, cls.bl_idname, None) is not None:
                bpy.utils.unregister_class(cls)
        except Exception:
            traceback.print_exc()
    if not INSTALLED_PACKAGE:
        try:
            addon.unregister()
        except Exception:
            traceback.print_exc()
