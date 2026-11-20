"""Plane group controller, keyframed layer Opacity and Ungroup.

* Keyframed Opacity on an image layer plays back: the material follows the
  keys through a driver (it used to keep the last slider value), in Solid
  shading too, also when the keys are added without touching the slider.
* Add Group Controller parents the group's layers to an Empty without moving
  them; moving or keyframing the controller moves the whole group.
* Group Opacity multiplies every layer's Opacity and can be keyframed.
* A click on the group selects the controller; it stands for the whole group.
* Remove Group Controller and Ungroup leave every layer where it was.

Run with Blender 5.2 or 5.3:
    blender -b --factory-startup --python-exit-code 1 \
        --python frame_by_plane/tests/group_controller_regression.py
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


def rigs():
    return [obj for obj in bpy.context.scene.objects if bool(getattr(obj, "is_fbp_control", False))]


def evaluated_opacity(rig):
    """``[(Opacity multiply, Solid alpha)]`` of the layer's materials, as evaluated."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    values = []
    for mat in rig.fbp_plane_target.data.materials:
        if mat is None:
            continue
        evaluated = mat.evaluated_get(depsgraph)
        node = evaluated.node_tree.nodes.get("FBP_Opacity")
        values.append((
            None if node is None else round(float(node.inputs[1].default_value), 4),
            round(float(evaluated.diffuse_color[3]), 4),
        ))
    return values


def worlds(objects):
    return {obj.name: obj.matrix_world.copy() for obj in objects}


def same_place(before, objects, tolerance=1.0e-4):
    for obj in objects:
        a, b = before[obj.name], obj.matrix_world
        for row in range(4):
            for column in range(4):
                if abs(a[row][column] - b[row][column]) > tolerance:
                    return False
    return True


try:
    groups = importlib.import_module(f"{PACKAGE_NAME}.plane_groups")
    controller_module = importlib.import_module(f"{PACKAGE_NAME}.group_controller")
    materials = importlib.import_module(f"{PACKAGE_NAME}.materials")
    runtime = importlib.import_module(f"{PACKAGE_NAME}.runtime")
    operator_import = importlib.import_module(f"{PACKAGE_NAME}.operator_import")
    operator_layers = importlib.import_module(f"{PACKAGE_NAME}.operator_layers")
    for operator_class in (
        operator_import.FBP_OT_ImportSequence,
        operator_import.FBP_OT_GenerateMultiplane,
        operator_layers.FBP_OT_CreateLayerCollection,
        *controller_module._CLASSES,
    ):
        if getattr(bpy.types, operator_class.__name__, None) is None:
            bpy.utils.register_class(operator_class)

    workdir = Path(tempfile.mkdtemp(prefix="fbp_group_controller_"))
    names = []
    for index in range(1, 5):
        image = bpy.data.images.new(f"FBP Controller {index}", width=12, height=8, alpha=True)
        try:
            image.generated_color = (0.2 * index, 0.5, 0.7, 1.0)
            image.filepath_raw = str(workdir / f"layer_{index}.png")
            image.file_format = 'PNG'
            image.save()
        finally:
            bpy.data.images.remove(image)
        names.append(f"layer_{index}.png")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    scene = bpy.context.scene
    camera = bpy.data.objects.new("Controller Camera", bpy.data.cameras.new("Controller Camera"))
    camera.location = (0.0, -12.0, 0.0)
    camera.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.collection.objects.link(camera)
    scene.camera = camera
    bpy.context.view_layer.update()
    rows = [(f"L{index}", "", str(workdir), [name], False) for index, name in enumerate(names)]
    assert operator_import._fbp_prepare_pending_rows(bpy.context, str(workdir), rows) == 4
    assert 'FINISHED' in bpy.ops.fbp.generate_multiplane('EXEC_DEFAULT', camera_mode='KEEP')
    layers = sorted(rigs(), key=lambda obj: obj.fbp_depth_order)
    assert len(layers) == 4

    # --- 1. Keyframed Opacity on an image layer plays back -------------------
    keyed = layers[3]
    keyed.fbp_opacity = 1.0
    keyed.keyframe_insert("fbp_opacity", frame=1)
    keyed.keyframe_insert("fbp_opacity", frame=11)
    # Keys added without the slider: the depsgraph observer notices them.
    fcurve = runtime.fbp_find_action_fcurve(keyed, "fbp_opacity")
    assert fcurve is not None
    fcurve.keyframe_points[1].co.y = 0.2
    fcurve.update()
    assert materials._fbp_color_plane_opacity_binding_stale(keyed), "keys added: drivers must be bound"
    materials.fbp_bind_animated_color_plane_opacity(scene)
    assert not materials._fbp_color_plane_opacity_binding_stale(keyed)
    scene.frame_set(1)
    assert evaluated_opacity(keyed)[0][0] == 1.0, evaluated_opacity(keyed)
    scene.frame_set(11)
    assert evaluated_opacity(keyed)[0] == (0.2, 0.2), evaluated_opacity(keyed)
    scene.frame_set(6)
    assert abs(evaluated_opacity(keyed)[0][0] - 0.6) < 0.05, evaluated_opacity(keyed)
    scene.frame_set(1)

    # --- 2. A plane group with a controller ----------------------------------
    bpy.ops.object.select_all(action='DESELECT')
    for rig in layers[:3]:
        rig.select_set(True)
    bpy.context.view_layer.objects.active = layers[0]
    assert bpy.ops.fbp.create_layer_collection('EXEC_DEFAULT', mode='PLANES') == {'FINISHED'}
    group = groups.group_chain(layers[0], scene)[-1]
    members = groups.group_rigs(group, scene)
    assert set(members) == set(layers[:3])
    before = worlds(members)
    planes_before = worlds([rig.fbp_plane_target for rig in members])
    assert bpy.ops.fbp.add_group_controller('EXEC_DEFAULT', group_name=group.name) == {'FINISHED'}
    controller = controller_module.group_controller(group)
    assert controller is not None and controller.type == 'EMPTY'
    assert controller.name in group.objects
    bpy.context.view_layer.update()
    assert all(rig.parent == controller for rig in members), [rig.parent for rig in members]
    assert layers[3].parent != controller
    assert same_place(before, members), "adding the controller moved the layers"
    assert same_place(planes_before, [rig.fbp_plane_target for rig in members])
    assert bpy.context.view_layer.objects.active == controller

    # --- 3. Moving and keyframing the controller moves the group --------------
    controller.location.x += 2.0
    bpy.context.view_layer.update()
    for rig in members:
        delta = rig.matrix_world.translation - before[rig.name].translation
        assert abs(delta.x - 2.0) < 1.0e-4 and abs(delta.y) < 1.0e-4, (rig.name, delta)
    controller.keyframe_insert("location", frame=1)
    controller.location.z += 1.0
    controller.keyframe_insert("location", frame=11)
    scene.frame_set(11)
    z11 = members[0].matrix_world.translation.z
    scene.frame_set(1)
    z1 = members[0].matrix_world.translation.z
    assert abs((z11 - z1) - 1.0) < 1.0e-4, (z1, z11)

    # --- 4. Group Opacity, keyframed -----------------------------------------
    members[0].fbp_opacity = 0.5
    controller.fbp_group_opacity = 1.0
    controller.keyframe_insert("fbp_group_opacity", frame=1)
    controller.fbp_group_opacity = 0.4
    controller.keyframe_insert("fbp_group_opacity", frame=11)
    scene.frame_set(1)
    assert evaluated_opacity(members[0])[0][0] == 0.5, evaluated_opacity(members[0])
    assert evaluated_opacity(members[1])[0][0] == 1.0, evaluated_opacity(members[1])
    scene.frame_set(11)
    assert evaluated_opacity(members[0])[0] == (0.2, 0.2), evaluated_opacity(members[0])
    assert evaluated_opacity(members[1])[0] == (0.4, 0.4), evaluated_opacity(members[1])
    assert evaluated_opacity(layers[3])[0][0] == 0.2, "a layer outside the group must not follow it"
    scene.frame_set(1)

    # --- 5. A click selects the controller, which stands for the group --------
    bpy.ops.object.select_all(action='DESELECT')
    assert groups.select_group(bpy.context, group, members[1])
    assert controller.select_get() and not any(rig.select_get() for rig in members)
    assert groups.whole_group_selected_rigs(bpy.context) == {rig.name for rig in members}
    assert controller_module.whole_group_selected(bpy.context) == group
    assert groups.group_selected(group, scene)

    # --- 6. Remove the controller: layers stay -------------------------------
    controller.animation_data_clear()
    bpy.context.view_layer.update()
    placed = worlds(members)
    assert bpy.ops.fbp.remove_group_controller('EXEC_DEFAULT', group_name=group.name) == {'FINISHED'}
    bpy.context.view_layer.update()
    assert controller_module.group_controller(group) is None
    assert not any(obj.name.endswith(controller_module.CONTROLLER_SUFFIX) for obj in bpy.data.objects)
    assert all(rig.parent is None for rig in members), [rig.parent for rig in members]
    assert same_place(placed, members), "removing the controller moved the layers"
    assert evaluated_opacity(members[0])[0][0] == 0.5, evaluated_opacity(members[0])
    assert evaluated_opacity(members[1]) == [(None, 1.0)], evaluated_opacity(members[1])
    assert not materials._fbp_color_plane_opacity_binding_stale(members[1])

    # --- 7. Ungroup -------------------------------------------------------------
    assert bpy.ops.fbp.add_group_controller('EXEC_DEFAULT', group_name=group.name) == {'FINISHED'}
    group_name = group.name
    placed = worlds(members)
    assert bpy.ops.fbp.dissolve_plane_group('EXEC_DEFAULT', group_name=group_name) == {'FINISHED'}
    bpy.context.view_layer.update()
    assert bpy.data.collections.get(group_name) is None, "the empty group must be deleted"
    assert all(groups.group_chain(rig, scene) == [] for rig in members)
    assert same_place(placed, members), "Ungroup moved the layers"
    assert all(rig.parent is None for rig in members)

    assert not runtime.fbp_callback_failures(), runtime.fbp_callback_failures()
    print("FBPTEST group controller: PASS")
except Exception:
    traceback.print_exc()
    sys.exit(1)
