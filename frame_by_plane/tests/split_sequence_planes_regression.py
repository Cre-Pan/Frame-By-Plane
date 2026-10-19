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


def rigs():
    return [obj for obj in bpy.context.scene.objects if bool(getattr(obj, "is_fbp_control", False))]


if not INSTALLED_PACKAGE:
    addon.register()
try:
    operator_import = importlib.import_module(f"{PACKAGE_NAME}.operator_import")
    geo = importlib.import_module(f"{PACKAGE_NAME}.geometry_nodes")
    workdir = Path(tempfile.mkdtemp(prefix="fbp_split_"))
    names = []
    for index in range(1, 4):
        image = bpy.data.images.new(f"FBP Split Fixture {index}", width=8, height=8, alpha=True)
        try:
            image.generated_color = (0.3 * index, 0.2, 0.5, 1.0)
            image.filepath_raw = str(workdir / f"split_{index:04d}.png")
            image.file_format = 'PNG'
            image.save()
        finally:
            bpy.data.images.remove(image)
        names.append(f"split_{index:04d}.png")

    operator_sequence = importlib.import_module(f"{PACKAGE_NAME}.operator_sequence")
    # Background Blender registers only a headless subset of the operators.
    temporary = []
    for operator_class in (
        operator_import.FBP_OT_ImportSequence,
        operator_sequence.FBP_OT_DuplicateSelectedLayers,
        operator_sequence.FBP_OT_SplitSequenceToPlanes,
    ):
        if getattr(bpy.types, operator_class.__name__, None) is None:
            bpy.utils.register_class(operator_class)
            temporary.append(operator_class)
    assert bpy.ops.fbp.import_sequence(
        'EXEC_DEFAULT',
        synchronous=True,
        filepath=str(workdir / names[0]),
        directory=str(workdir),
        files=[{"name": name} for name in names],
        media_filter='IMAGES',
    ) == {'FINISHED'}
    (rig,) = rigs()
    assert len(rig.fbp_images) == 3
    rig.location = (1.5, -2.0, 0.75)
    rig.rotation_euler = (0.0, 0.0, 0.4)
    bpy.context.view_layer.update()
    assert geo.fbp_add_effect(rig, "INVERT", select_object_mask_helper=False, inherit_active_group=False)
    source_world = rig.fbp_plane_target.matrix_world.copy()
    source_effects = list(geo.fbp_effect_ids_for_rig(rig))
    assert source_effects

    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    assert bpy.ops.fbp.split_sequence_to_planes(rig_name=rig.name) == {'FINISHED'}

    result = rigs()
    assert len(result) == 3, [obj.name for obj in result]
    paths = set()
    materials = set()
    for layer in result:
        assert len(layer.fbp_images) == 1, (layer.name, len(layer.fbp_images))
        paths.add(os.path.basename(layer.fbp_images[0].filepath or layer.fbp_images[0].name))
        plane = layer.fbp_plane_target
        assert plane is not None and plane.parent == layer
        diff = max(abs(a - b) for row_a, row_b in zip(plane.matrix_world, source_world) for a, b in zip(row_a, row_b))
        assert diff < 1.0e-5, (layer.name, diff)
        assert list(geo.fbp_effect_ids_for_rig(layer)) == source_effects, layer.name
        for slot in plane.material_slots:
            if slot.material is not None:
                materials.add(slot.material.as_pointer())
        assert layer.select_get()
    assert len(paths) == 3, paths
    assert len(materials) >= 3, materials
    assert {obj.name for obj in result} >= {rig.name, f"{rig.name}_split_0002", f"{rig.name}_split_0003"}, [obj.name for obj in result]
    assert bpy.context.view_layer.objects.active == rig
    assert len(bpy.context.scene.fbp_layers) >= 3

    # The viewport SOLO badge counts soloed layers.
    solo_overlay = importlib.import_module(f"{PACKAGE_NAME}.solo_overlay")
    assert solo_overlay.solo_layer_count(bpy.context.scene) == 0
    rows = list(bpy.context.scene.fbp_layers)
    rows[0].solo = True
    rows[1].solo = True
    assert solo_overlay.solo_layer_count(bpy.context.scene) == 2
    for row in rows:
        row.solo = False

    # A single-frame layer cannot be split.
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    assert not bpy.ops.fbp.split_sequence_to_planes.poll()
    print("FBPTEST split_sequence_planes: PASS")
except Exception:
    traceback.print_exc()
    raise
finally:
    for operator_class in reversed(globals().get("temporary", [])):
        try:
            bpy.utils.unregister_class(operator_class)
        except RuntimeError:
            pass
    if not INSTALLED_PACKAGE:
        try:
            addon.unregister()
        except Exception:
            traceback.print_exc()
