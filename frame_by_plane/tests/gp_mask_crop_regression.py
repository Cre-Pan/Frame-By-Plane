import importlib
import os
import sys
import tempfile
import time
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

    # Linear + CLIP sampling faded the border texels into a thin unmasked
    # line wherever a stroke ran past the image edge.
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    assert bpy.ops.fbp.add_grease_pencil_mask() == {'FINISHED'}
    canvas = next(obj for obj in bpy.data.objects if gpb.is_gp_mask_canvas(obj))
    layer = canvas.data.layers.active
    layer.current_frame().drawing.add_strokes([4])
    bpy.ops.object.mode_set(mode="OBJECT")
    dispatch = importlib.import_module(f"{PACKAGE_NAME}.runtime_scheduler").scheduler_dispatcher_callback()
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        dispatch()
        time.sleep(0.02)
    gpb.refresh_gp_mask(canvas, force=True, scene=bpy.context.scene)
    mask_image = canvas.fbp_gp_mask_image
    assert mask_image is not None
    nodes = [
        node for group in bpy.data.node_groups for node in group.nodes
        if node.get("fbp_imported_mask_image_node", False) and node.image == mask_image
    ]
    assert nodes, "the GP mask image is not bound to the effect"
    assert all(node.extension == "EXTEND" for node in nodes), [node.extension for node in nodes]

    # Blur and Expand apply only while their checkbox is on.
    raster = importlib.import_module(f"{PACKAGE_NAME}.gp_mask_raster")
    assert not canvas.fbp_gp_mask_use_blur and not canvas.fbp_gp_mask_use_expand
    assert abs(canvas.fbp_gp_mask_feather - 0.125) < 1.0e-6 and canvas.fbp_gp_mask_expand == 0.0
    assert raster.mask_blur(canvas) == 0.0 and raster.mask_expand(canvas) == 0.0
    canvas.fbp_gp_mask_use_blur = True
    assert abs(raster.mask_blur(canvas) - 0.125) < 1.0e-6

    class Layout:
        """Accept any layout call so the panel draw code runs headless."""
        def __getattr__(self, _name):
            return lambda *args, **kwargs: Layout()
        def __setattr__(self, _name, _value):
            pass
        def __iter__(self):
            return iter((Layout(), Layout()))

    canvas.fbp_gp_mask_ui_show_settings = True
    assert gpb.draw_gp_mask_settings_ui(Layout(), bpy.context, canvas, embedded=True, header_actions=False)
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
