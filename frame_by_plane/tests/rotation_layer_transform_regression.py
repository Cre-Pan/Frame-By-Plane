"""Infinite Rotation and layer transform.

* Motion > Infinite Rotation follows every frame: the frame handler writes
  the rotation right away, it no longer waits for an idle timer (which made
  playback look stepped).
* The Infinite Rotation effect keeps the plane rigid when the layer is
  scaled on one axis only: edges and diagonals keep their length at any
  angle. The patch is idempotent.
* The layer transform panel finds the rig of an active image plane, and
  flags transform keys put on the plane itself.

Run with Blender 5.2 or 5.3:
    blender -b --factory-startup --python-exit-code 1 \
        --python frame_by_plane/tests/rotation_layer_transform_regression.py
"""

import importlib
import math
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
if not INSTALLED_PACKAGE:
    addon.register()


def world_quad(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def write_drawing(path, width, height):
    image = bpy.data.images.new(path.stem, width=width, height=height, alpha=True)
    try:
        image.pixels.foreach_set([0.9, 0.4, 0.2, 1.0] * (width * height))
        image.filepath_raw = str(path)
        image.file_format = 'PNG'
        image.save()
    finally:
        bpy.data.images.remove(image)


try:
    geometry_nodes = importlib.import_module(f"{PACKAGE_NAME}.geometry_nodes")
    motion = importlib.import_module(f"{PACKAGE_NAME}.motion_runtime")
    panel = importlib.import_module(f"{PACKAGE_NAME}.layer_transform_panel")
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # 1. Infinite Rotation effect: rigid under a one-axis scale.
    group = geometry_nodes._fbp_load_effect_group("INFINITE_ROTATION")
    assert group is not None, "Infinite Rotation group did not load"
    node_count = len(group.nodes)
    geometry_nodes._fbp_patch_infinite_rotation_scale(group)
    assert len(group.nodes) == node_count, "patch is not idempotent"
    assert group.nodes.get("FBP Rigid Scale In") is not None

    mesh = bpy.data.meshes.new("Rotation Quad")
    mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    parent = bpy.data.objects.new("Stretched Rig", None)
    parent.scale = (3.0, 1.0, 1.0)
    parent.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    plane = bpy.data.objects.new("Rotation Plane", mesh)
    plane.parent = parent
    scene.collection.objects.link(parent)
    scene.collection.objects.link(plane)
    modifier = plane.modifiers.new("Infinite Rotation", "NODES")
    modifier.node_group = group
    geometry_nodes._fbp_set_modifier_input(modifier, group, "Speed", 45.0)
    scene.frame_set(1)
    rest = world_quad(plane)
    scene.frame_set(2)  # 45 degrees: the worst shear before the fix.
    turned = world_quad(plane)
    for index in range(4):
        before = (rest[index] - rest[(index + 1) % 4]).length
        after = (turned[index] - turned[(index + 1) % 4]).length
        assert abs(before - after) < 1.0e-4, ("edge changed length", index, before, after)
    for a, b in ((0, 2), (1, 3)):
        assert abs((rest[a] - rest[b]).length - (turned[a] - turned[b]).length) < 1.0e-4
    assert (rest[0] - turned[0]).length > 0.5, "the plane did not rotate"

    # 2. Motion > Infinite Rotation: one new angle on every frame.
    target = bpy.data.objects.new("Motion Target", None)
    scene.collection.objects.link(target)
    assert motion._capture_motion_base(target)
    item = target.fbp_motions.add()
    motion.apply_motion_preset_defaults(item, "INFINITE_ROTATION")
    assert item.step_frames == 1
    motion._clear_motion_target_cache(scene)
    angles = []
    for frame in range(1, 7):
        scene.frame_current = frame
        motion._fbp_motion_frame_change(scene)
        angles.append(target.delta_rotation_euler.z)
    steps = [b - a for a, b in zip(angles, angles[1:])]
    assert all(step > 1.0e-4 for step in steps), ("Motion held a frame", angles)
    assert max(steps) - min(steps) < 1.0e-5, ("uneven Motion steps", steps)

    # 3. Layer transform panel: rig of an active plane, keys on the plane.
    operator_import = importlib.import_module(f"{PACKAGE_NAME}.operator_import")
    for operator_class in (operator_import.FBP_OT_ImportSequence, operator_import.FBP_OT_GenerateMultiplane):
        if getattr(bpy.types, operator_class.__name__, None) is None:
            bpy.utils.register_class(operator_class)
    workdir = Path(tempfile.mkdtemp(prefix="fbp_layer_transform_"))
    write_drawing(workdir / "layer.png", 40, 20)
    camera = bpy.data.objects.new("Transform Camera", bpy.data.cameras.new("Transform Camera"))
    camera.location = (0.0, -12.0, 0.0)
    camera.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.collection.objects.link(camera)
    scene.camera = camera
    rows = [("Layer", "", str(workdir), ["layer.png"], False)]
    assert operator_import._fbp_prepare_pending_rows(bpy.context, str(workdir), rows) == 1
    assert 'FINISHED' in bpy.ops.fbp.generate_multiplane('EXEC_DEFAULT', camera_mode='KEEP')
    rig = next(obj for obj in scene.objects if bool(getattr(obj, "is_fbp_control", False)))
    layer_plane = rig.fbp_plane_target
    assert panel.layer_rig_for_plane(layer_plane) == rig
    assert panel.layer_rig_for_plane(rig) is None
    assert panel.layer_rig_for_plane(camera) is None
    assert not panel.plane_has_transform_keys(layer_plane)
    layer_plane.keyframe_insert("location", frame=1)
    assert panel.plane_has_transform_keys(layer_plane)

    print("FBPTEST rotation and layer transform: PASS")
except Exception:
    traceback.print_exc()
    sys.exit(1)
