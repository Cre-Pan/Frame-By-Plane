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


def pump(seconds=1.5):
    """Run the add-on's deferred tasks as Blender's timer would."""
    dispatch = importlib.import_module(f"{PACKAGE_NAME}.runtime_scheduler").scheduler_dispatcher_callback()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        dispatch()
        time.sleep(0.02)


def mask_canvases():
    return [obj for obj in bpy.data.objects if gpb.is_gp_mask_canvas(obj)]


if not INSTALLED_PACKAGE:
    addon.register()
bpy.context.preferences.edit.use_global_undo = True
temporary = []
try:
    operator_import = importlib.import_module(f"{PACKAGE_NAME}.operator_import")
    geo = importlib.import_module(f"{PACKAGE_NAME}.geometry_nodes")
    gpb = importlib.import_module(f"{PACKAGE_NAME}.grease_pencil_bridge")
    pie = importlib.import_module(f"{PACKAGE_NAME}.viewport_pie")
    # Pie buttons call other operators; only the outer operator can push the
    # undo step, so it must be undoable itself.
    for operator_class in (pie.FBP_OT_PieAddEffect, pie.FBP_OT_PieAddGreasePencilMask, pie.FBP_OT_PieToggleClippingMask):
        assert "UNDO" in operator_class.bl_options, operator_class.__name__
    if getattr(bpy.types, operator_import.FBP_OT_ImportSequence.__name__, None) is None:
        bpy.utils.register_class(operator_import.FBP_OT_ImportSequence)
        temporary.append(operator_import.FBP_OT_ImportSequence)

    workdir = Path(tempfile.mkdtemp(prefix="fbp_gp_mask_"))
    image = bpy.data.images.new("FBP GP Mask Fixture", width=8, height=8, alpha=True)
    image.filepath_raw = str(workdir / "mask_plate.png")
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)
    assert bpy.ops.fbp.import_sequence(
        'EXEC_DEFAULT', synchronous=True, filepath=str(workdir / "mask_plate.png"),
        directory=str(workdir), media_filter='IMAGES',
    ) == {'FINISHED'}
    rig = [obj for obj in bpy.context.scene.objects if obj.is_fbp_control][0]
    rig_name = rig.name
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_set(66)
    pump(0.3)
    assert bpy.ops.ed.undo_push(message="Before Mask") == {'FINISHED'}

    # Create the mask at frame 66: it covers the whole shot from frame 1.
    assert bpy.ops.fbp.add_grease_pencil_mask() == {'FINISHED'}
    assert bpy.ops.ed.undo_push(message="Grease Pencil Mask") == {'FINISHED'}
    (canvas,) = mask_canvases()
    layer = canvas.data.layers.active
    assert [frame.frame_number for frame in layer.frames] == [1], [f.frame_number for f in layer.frames]
    assert bpy.context.mode == 'PAINT_GREASE_PENCIL'
    effects = list(geo.fbp_effect_ids_for_rig(rig))
    assert effects

    # First stroke, then Ctrl+Z: only the stroke goes away.
    layer.current_frame().drawing.add_strokes([4])
    assert bpy.ops.ed.undo_push(message="Draw Stroke") == {'FINISHED'}
    pump(0.5)
    assert bpy.ops.ed.undo() == {'FINISHED'}
    pump(1.5)
    rig = bpy.data.objects[rig_name]
    scene = bpy.context.scene
    assert list(geo.fbp_effect_ids_for_rig(rig)) == effects, list(geo.fbp_effect_ids_for_rig(rig))
    (canvas,) = mask_canvases()
    layer = canvas.data.layers.active
    assert len(layer.current_frame().drawing.strokes) == 0
    layer.current_frame().drawing.add_strokes([4])

    # Finish editing: the mask hides and cannot be clicked in the viewport.
    assert bpy.ops.fbp.edit_grease_pencil_mask(rig_name=rig.name, canvas_name=canvas.name) == {'FINISHED'}
    assert bpy.context.mode == 'OBJECT'
    assert bpy.context.view_layer.objects.active == rig
    assert canvas.hide_get() and canvas.hide_select

    # The eye keeps the strokes visible as a guide, still not selectable.
    canvas.fbp_gp_mask_show_guide = True
    assert not canvas.hide_get() and canvas.hide_select
    canvas.fbp_gp_mask_show_guide = False
    assert canvas.hide_get()

    # Edit again later in the shot: it draws on the existing drawing instead
    # of starting an empty key that would hide the mask from here on.
    scene.frame_set(80)
    assert bpy.ops.fbp.edit_grease_pencil_mask(rig_name=rig.name, canvas_name=canvas.name) == {'FINISHED'}
    assert bpy.context.mode == 'PAINT_GREASE_PENCIL'
    assert bpy.context.view_layer.objects.active == canvas
    assert not canvas.hide_get()
    assert [frame.frame_number for frame in layer.frames] == [1]
    assert len(layer.current_frame().drawing.strokes) == 1
    assert gpb.gp_mask_is_being_edited(bpy.context, canvas)
    assert bpy.ops.fbp.edit_grease_pencil_mask(rig_name=rig.name, canvas_name=canvas.name) == {'FINISHED'}
    assert bpy.context.mode == 'OBJECT'
    print("FBPTEST gp_mask_edit_undo: PASS")
except Exception:
    traceback.print_exc()
    raise
finally:
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
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
