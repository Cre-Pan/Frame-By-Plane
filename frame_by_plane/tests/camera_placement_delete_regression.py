"""New layers are generated in front of the camera; X/Delete removes rig and plane together.

Run with Blender 5.2:
    blender -b --factory-startup --python-exit-code 1 \
        --python frame_by_plane/tests/camera_placement_delete_regression.py
"""

import importlib
import math
import os
import sys
import tempfile
import traceback
from pathlib import Path

import bpy
import mathutils
from bpy_extras.object_utils import world_to_camera_view


INSTALLED_PACKAGE = os.environ.get("FBP_TEST_INSTALLED") == "1"
PACKAGE_NAME = os.environ.get(
    "FBP_TEST_PACKAGE",
    "bl_ext.fbp_audit.frame_by_plane" if INSTALLED_PACKAGE else "frame_by_plane",
)
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(PACKAGE_NAME)


def rigs():
    return [obj for obj in bpy.context.scene.objects if bool(getattr(obj, "is_fbp_control", False))]


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.view_layer.update()


def make_camera(location, rotation_deg, *, shift=(0.0, 0.0), ortho=False):
    data = bpy.data.cameras.new("Test Camera")
    data.shift_x, data.shift_y = shift
    if ortho:
        data.type = 'ORTHO'
        data.ortho_scale = 6.0
    camera = bpy.data.objects.new("Test Camera", data)
    camera.location = location
    camera.rotation_euler = tuple(math.radians(value) for value in rotation_deg)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    bpy.context.view_layer.update()
    return camera


def assert_in_front(rig, camera, label):
    bpy.context.view_layer.update()
    plane = rig.fbp_plane_target
    center = plane.matrix_world.translation
    view = world_to_camera_view(bpy.context.scene, camera, center)
    assert abs(view.x - 0.5) < 1e-3 and abs(view.y - 0.5) < 1e-3 and view.z > 0.0, (label, tuple(view))
    cam_forward = camera.matrix_world.to_quaternion() @ mathutils.Vector((0.0, 0.0, -1.0))
    plane_normal = plane.matrix_world.to_quaternion() @ mathutils.Vector((0.0, 0.0, 1.0))
    # The image faces the camera: its normal points back at the lens.
    assert plane_normal.dot(-cam_forward) > 0.9999, (label, tuple(plane_normal), tuple(cam_forward))
    return view.z


def import_single(workdir, name):
    result = bpy.ops.fbp.import_sequence(
        'EXEC_DEFAULT',
        synchronous=True,
        filepath=str(workdir / name),
        directory=str(workdir),
        files=[{"name": name}],
        media_filter='IMAGES',
    )
    assert result == {'FINISHED'}, result
    return rigs()[-1]


if not INSTALLED_PACKAGE:
    addon.register()
temporary = []
try:
    operator_import = importlib.import_module(f"{PACKAGE_NAME}.operator_import")
    operator_sequence = importlib.import_module(f"{PACKAGE_NAME}.operator_sequence")
    builder = importlib.import_module(f"{PACKAGE_NAME}.builder")
    for operator_class in (
        operator_import.FBP_OT_ImportSequence,
        operator_import.FBP_OT_GenerateMultiplane,
        operator_sequence.FBP_OT_DeleteOrDefault,
    ):
        if getattr(bpy.types, operator_class.__name__, None) is None:
            bpy.utils.register_class(operator_class)
            temporary.append(operator_class)

    workdir = Path(tempfile.mkdtemp(prefix="fbp_camera_place_"))
    names = []
    for index in range(1, 4):
        image = bpy.data.images.new(f"FBP Place {index}", width=16, height=9, alpha=True)
        try:
            image.generated_color = (0.2 * index, 0.4, 0.6, 1.0)
            image.filepath_raw = str(workdir / f"layer_{index}.png")
            image.file_format = 'PNG'
            image.save()
        finally:
            bpy.data.images.remove(image)
        names.append(f"layer_{index}.png")

    scene = bpy.context.scene
    scene.fbp_gen_camera = False
    scene.cursor.location = (0.0, 0.0, 0.0)

    # 1. Front camera raised 4 units: the plane rises with it.
    clear_scene()
    camera = make_camera((0.0, -10.0, 4.0), (90.0, 0.0, 0.0))
    rig = import_single(workdir, names[0])
    depth = assert_in_front(rig, camera, "raised camera")
    assert abs(depth - 10.0) < 1e-3, depth
    assert rig.fbp_is_vertical
    print("FBPTEST raised camera location", tuple(round(v, 4) for v in rig.location))

    # 2. Tilted, rolled camera with lens shift, parented to an empty.
    clear_scene()
    camera = make_camera((2.0, -8.0, 3.0), (65.0, 10.0, 25.0), shift=(0.2, -0.1))
    holder = bpy.data.objects.new("Camera Holder", None)
    scene.collection.objects.link(holder)
    holder.location = (0.0, 0.0, 2.5)
    camera.parent = holder
    bpy.context.view_layer.update()
    rig = import_single(workdir, names[1])
    assert_in_front(rig, camera, "tilted camera")

    # 3. Orthographic camera looking down from high above.
    clear_scene()
    camera = make_camera((1.0, 1.0, 25.0), (0.0, 0.0, 0.0), ortho=True)
    rig = import_single(workdir, names[2])
    depth = assert_in_front(rig, camera, "ortho top camera")
    assert abs(depth - 25.0) < 1e-3 and not rig.fbp_is_vertical, depth

    # 4. Multiplane: every layer is centred and stepped away along the view axis.
    clear_scene()
    camera = make_camera((0.0, -10.0, 6.0), (80.0, 0.0, 0.0))
    rows = [(f"L{index}", "", str(workdir), [name], False) for index, name in enumerate(names)]
    assert operator_import._fbp_prepare_pending_rows(bpy.context, str(workdir), rows) == 3
    result = bpy.ops.fbp.generate_multiplane('EXEC_DEFAULT', camera_mode='KEEP')
    assert 'FINISHED' in result, result
    layers = sorted(rigs(), key=lambda obj: obj.fbp_depth_order)
    assert len(layers) == 3, [obj.name for obj in layers]
    depths = [assert_in_front(layer, camera, f"multiplane {layer.name}") for layer in layers]
    assert depths == sorted(depths) and depths[-1] - depths[0] > 0.01, depths

    # 5. Without a camera the classic cursor layout is unchanged.
    clear_scene()
    scene.camera = None
    scene.fbp_pre_orientation = 'VERT'
    placement = builder.fbp_layer_placement(scene, None, mathutils.Vector((1.0, 2.0, 3.0)))
    assert not placement.uses_camera
    assert tuple(placement.location(0.5)) == (1.0, 2.5, 3.0)

    # 6. Delete removes rig and plane together, plus other selected objects.
    clear_scene()
    camera = make_camera((0.0, -10.0, 0.0), (90.0, 0.0, 0.0))
    rig = import_single(workdir, names[0])
    plane_name = rig.fbp_plane_target.name
    rig_name = rig.name
    cube_mesh = bpy.data.meshes.new("Cube Mesh")
    cube = bpy.data.objects.new("Plain Cube", cube_mesh)
    scene.collection.objects.link(cube)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    rig.select_set(True)
    cube.select_set(True)
    bpy.context.view_layer.objects.active = rig
    assert bpy.ops.fbp.delete_or_default('EXEC_DEFAULT', confirm=False) == {'FINISHED'}
    assert bpy.data.objects.get(rig_name) is None
    assert bpy.data.objects.get(plane_name) is None, "plane survived the delete"
    assert bpy.data.objects.get("Plain Cube") is None
    assert bpy.data.objects.get("Test Camera") is not None

    print("FBPTEST camera_placement_delete: PASS")
except Exception:
    traceback.print_exc()
    raise
finally:
    for operator_class in reversed(temporary):
        try:
            bpy.utils.unregister_class(operator_class)
        except RuntimeError:
            pass
    if not INSTALLED_PACKAGE:
        addon.unregister()
