import importlib
import os
import sys
import tempfile
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


def assert_uv_contract(rig, bounds, label):
    """Every plane vertex must sit where its UV says on the mask raster."""
    min_x, max_x, min_y, max_y = bounds
    mesh = rig.fbp_plane_target.data
    uv_layer = mesh.uv_layers.active
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            co = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            u, v = uv_layer.data[loop_index].uv
            assert abs((co.x - min_x) / (max_x - min_x) - u) < 1.0e-5, (label, co.x, u, bounds)
            assert abs((co.y - min_y) / (max_y - min_y) - v) < 1.0e-5, (label, co.y, v, bounds)


if not INSTALLED_PACKAGE:
    addon.register()
temporary = []
try:
    operator_import = importlib.import_module(f"{PACKAGE_NAME}.operator_import")
    gpb = importlib.import_module(f"{PACKAGE_NAME}.grease_pencil_bridge")
    core = importlib.import_module(f"{PACKAGE_NAME}.gp_mask_core")
    if getattr(bpy.types, operator_import.FBP_OT_ImportSequence.__name__, None) is None:
        bpy.utils.register_class(operator_import.FBP_OT_ImportSequence)
        temporary.append(operator_import.FBP_OT_ImportSequence)

    workdir = Path(tempfile.mkdtemp(prefix="fbp_gp_mask_crop_"))
    image = bpy.data.images.new("FBP GP Mask Crop Fixture", width=16, height=8, alpha=True)
    image.filepath_raw = str(workdir / "crop_plate.png")
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)
    assert bpy.ops.fbp.import_sequence(
        'EXEC_DEFAULT', synchronous=True, filepath=str(workdir / "crop_plate.png"),
        directory=str(workdir), media_filter='IMAGES',
    ) == {'FINISHED'}
    rig = [obj for obj in bpy.context.scene.objects if obj.is_fbp_control][0]

    uncropped = gpb._plane_bounds(rig)
    assert_uv_contract(rig, uncropped, "uncropped")

    # The mask is sampled with the plane UVs, so Crop must not change the
    # raster rectangle: it only shows less of it.
    rig.fbp_crop_left = 0.5
    rig.fbp_crop_top = 0.25
    bpy.context.view_layer.update()
    for label, bounds in (("bridge", gpb._plane_bounds(rig)), ("core", core.plane_bounds(rig))):
        assert all(abs(a - b) < 1.0e-6 for a, b in zip(bounds, uncropped, strict=True)), (label, bounds, uncropped)
        assert_uv_contract(rig, bounds, label)
    mesh_xs = [vertex.co.x for vertex in rig.fbp_plane_target.data.vertices]
    assert min(mesh_xs) > uncropped[0] + 1.0e-4, "the fixture plane was not cropped"
    print("GP mask crop regression passed")
finally:
    for operator_class in reversed(temporary):
        try:
            bpy.utils.unregister_class(operator_class)
        except RuntimeError:
            pass
    if not INSTALLED_PACKAGE:
        try:
            addon.unregister()
        except Exception:
            traceback.print_exc()
