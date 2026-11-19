"""Set Layer Origin.

* Origin to Geometry puts the layer origin in the middle of the cropped
  plane; the drawing does not move, on the current frame or on another
  keyed frame.
* Origin to 3D Cursor moves the origin to the cursor, the drawing stays.
* Geometry to Origin slides the plane so its middle sits on the origin.
* The plane keeps an identity parent inverse (its offset is a location).

Run with Blender 5.2 or 5.3:
    blender -b --factory-startup --python-exit-code 1 \
        --python frame_by_plane/tests/layer_origin_regression.py
"""

import importlib
import math
import os
import sys
import tempfile
import traceback
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


INSTALLED_PACKAGE = os.environ.get("FBP_TEST_INSTALLED") == "1"
PACKAGE_NAME = os.environ.get(
    "FBP_TEST_PACKAGE",
    "bl_ext.fbp_audit.frame_by_plane" if INSTALLED_PACKAGE else "frame_by_plane",
)
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(PACKAGE_NAME)
if not INSTALLED_PACKAGE:
    addon.register()


def write_drawing(path, width, height):
    image = bpy.data.images.new(path.stem, width=width, height=height, alpha=True)
    try:
        image.pixels.foreach_set([0.9, 0.4, 0.2, 1.0] * (width * height))
        image.filepath_raw = str(path)
        image.file_format = 'PNG'
        image.save()
    finally:
        bpy.data.images.remove(image)


def plane_world(plane):
    bpy.context.view_layer.update()
    return [plane.matrix_world @ vertex.co for vertex in plane.data.vertices]


def same_points(before, after, label):
    assert len(before) == len(after), label
    for a, b in zip(before, after):
        assert (a - b).length < 1.0e-4, (label, tuple(a), tuple(b))


def run_origin(rig, kind):
    bpy.ops.object.select_all(action='DESELECT')
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    result = bpy.ops.fbp.layer_origin_set('EXEC_DEFAULT', type=kind)
    assert 'FINISHED' in result, result


try:
    layer_origin = importlib.import_module(f"{PACKAGE_NAME}.layer_origin")
    operator_import = importlib.import_module(f"{PACKAGE_NAME}.operator_import")
    for operator_class in (operator_import.FBP_OT_ImportSequence, operator_import.FBP_OT_GenerateMultiplane):
        if getattr(bpy.types, operator_class.__name__, None) is None:
            bpy.utils.register_class(operator_class)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    scene = bpy.context.scene
    workdir = Path(tempfile.mkdtemp(prefix="fbp_layer_origin_"))
    write_drawing(workdir / "layer.png", 80, 40)
    camera = bpy.data.objects.new("Origin Camera", bpy.data.cameras.new("Origin Camera"))
    camera.location = (0.0, -12.0, 0.0)
    camera.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.collection.objects.link(camera)
    scene.camera = camera
    rows = [("Layer", "", str(workdir), ["layer.png"], False)]
    assert operator_import._fbp_prepare_pending_rows(bpy.context, str(workdir), rows) == 1
    assert 'FINISHED' in bpy.ops.fbp.generate_multiplane('EXEC_DEFAULT', camera_mode='KEEP')
    rig = next(obj for obj in scene.objects if bool(getattr(obj, "is_fbp_control", False)))
    plane = rig.fbp_plane_target

    # A rotated, stretched layer cropped on the right and the top: its middle
    # is away from the rig origin.
    rig.rotation_euler = (math.radians(90.0), math.radians(20.0), 0.0)
    rig.scale = (2.0, 1.0, 1.0)
    rig.fbp_crop_right = 1.0
    rig.fbp_crop_top = 0.5
    bpy.context.view_layer.update()
    # Key the rig location on two frames.
    scene.frame_set(1)
    rig.location = (0.0, 0.0, 0.0)
    rig.keyframe_insert("location", frame=1)
    rig.location = (1.0, 0.0, 0.5)
    rig.keyframe_insert("location", frame=10)
    scene.frame_set(1)
    before_1 = plane_world(plane)
    scene.frame_set(10)
    before_10 = plane_world(plane)
    scene.frame_set(1)

    center = layer_origin.layer_geometry_center(rig)
    assert center is not None
    assert (center - rig.matrix_world.translation).length > 0.1, "crop did not move the middle"

    # 1. Origin to Geometry.
    run_origin(rig, 'GEOMETRY')
    bpy.context.view_layer.update()
    assert (rig.matrix_world.translation - center).length < 1.0e-4, (
        tuple(rig.matrix_world.translation), tuple(center))
    same_points(before_1, plane_world(plane), "frame 1 moved")
    scene.frame_set(10)
    same_points(before_10, plane_world(plane), "keyed frame 10 moved")
    scene.frame_set(1)
    assert plane.matrix_parent_inverse == Matrix.Identity(4)
    # Running it again changes nothing.
    run_origin(rig, 'GEOMETRY')
    same_points(before_1, plane_world(plane), "second run moved")

    # 2. Origin to 3D Cursor.
    scene.cursor.location = (0.3, -0.2, 0.7)
    run_origin(rig, 'CURSOR')
    bpy.context.view_layer.update()
    assert (rig.matrix_world.translation - Vector((0.3, -0.2, 0.7))).length < 1.0e-4
    same_points(before_1, plane_world(plane), "cursor origin moved the drawing")

    # 3. Geometry to Origin: the middle comes onto the origin.
    run_origin(rig, 'GEOMETRY_TO_ORIGIN')
    bpy.context.view_layer.update()
    local = rig.matrix_world.inverted_safe() @ layer_origin.layer_geometry_center(rig)
    assert abs(local.x) < 1.0e-4 and abs(local.y) < 1.0e-4, tuple(local)

    print("FBPTEST layer origin: PASS")
except Exception:
    traceback.print_exc()
    sys.exit(1)
