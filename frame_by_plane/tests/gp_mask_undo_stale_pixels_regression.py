"""Ctrl+Z after the first Grease Pencil Mask stroke clears the mask again.

Undo restores the canvas and its saved raster signature, but not the pixels
of generated images. When the stroke had been rasterized into a recycled
buffer (the image the undo step points at), the mask kept showing the undone
stroke: the signature matched the empty drawing, so the post-Undo refresh
skipped the raster.

Run with Blender 5.2 or 5.3:
    blender -b --factory-startup --python-exit-code 1 \
        --python frame_by_plane/tests/gp_mask_undo_stale_pixels_regression.py
"""

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
    dispatch = importlib.import_module(
        f"{PACKAGE_NAME}.runtime_scheduler"
    ).scheduler_dispatcher_callback()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        dispatch()
        time.sleep(0.02)


def mask_canvas(gpb):
    (canvas,) = [obj for obj in bpy.data.objects if gpb.is_gp_mask_canvas(obj)]
    return canvas


def coverage(image):
    pixels = image.pixels[:]
    return max(pixels[0::4]) if pixels else 0.0


def draw_line(canvas):
    drawing = canvas.data.layers.active.current_frame().drawing
    drawing.add_strokes([8])
    stroke = drawing.strokes[-1]
    for index, point in enumerate(stroke.points):
        point.position = (-0.6 + 1.2 * index / 7.0, 0.0, 0.0)
        point.radius = 0.08
        point.opacity = 1.0


if not INSTALLED_PACKAGE:
    addon.register()
bpy.context.preferences.edit.use_global_undo = True
temporary = []
gpb = None
reuse_delay = None
try:
    operator_import = importlib.import_module(f"{PACKAGE_NAME}.operator_import")
    gpb = importlib.import_module(f"{PACKAGE_NAME}.grease_pencil_bridge")
    if getattr(bpy.types, operator_import.FBP_OT_ImportSequence.__name__, None) is None:
        bpy.utils.register_class(operator_import.FBP_OT_ImportSequence)
        temporary.append(operator_import.FBP_OT_ImportSequence)

    workdir = Path(tempfile.mkdtemp(prefix="fbp_gp_mask_undo_pixels_"))
    image = bpy.data.images.new("FBP GP Undo Fixture", width=8, height=8, alpha=True)
    image.filepath_raw = str(workdir / "plate.png")
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    assert bpy.ops.fbp.import_sequence(
        "EXEC_DEFAULT", synchronous=True, filepath=str(workdir / "plate.png"),
        directory=str(workdir), media_filter="IMAGES",
    ) == {"FINISHED"}
    rig = [obj for obj in bpy.context.scene.objects if obj.is_fbp_control][0]
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    pump(0.3)

    assert bpy.ops.fbp.add_grease_pencil_mask() == {"FINISHED"}
    pump(0.5)
    canvas = mask_canvas(gpb)
    gpb.refresh_gp_mask(canvas, force=True)
    undo_image = canvas.fbp_gp_mask_image
    assert undo_image is not None and coverage(undo_image) == 0.0
    undo_image_name = undo_image.name
    assert bpy.ops.ed.undo_push(message="Grease Pencil Mask") == {"FINISHED"}

    # Recycle buffers at once, as an artist who waits a few seconds before
    # the first stroke does: the stroke lands in the image of the undo step.
    reuse_delay = gpb._GP_MASK_IMAGE_REUSE_DELAY
    gpb._GP_MASK_IMAGE_REUSE_DELAY = 0.0
    gpb.refresh_gp_mask(canvas, force=True)
    assert canvas.fbp_gp_mask_image.name != undo_image_name
    draw_line(canvas)
    gpb.refresh_gp_mask(canvas, force=True)
    stroke_image = canvas.fbp_gp_mask_image
    assert stroke_image.name == undo_image_name, (stroke_image.name, undo_image_name)
    assert coverage(stroke_image) > 0.5, coverage(stroke_image)
    assert bpy.ops.ed.undo_push(message="Draw Stroke") == {"FINISHED"}

    assert bpy.ops.ed.undo() == {"FINISHED"}
    pump(1.0)
    # The idle watchdog that starts the post-Undo repair is an app timer,
    # which background mode does not run: start the GP part of it here.
    gpb._deferred_gp_history_reindex()
    pump(3.0)
    canvas = mask_canvas(gpb)
    assert len(canvas.data.layers.active.current_frame().drawing.strokes) == 0
    shown = canvas.fbp_gp_mask_image
    assert shown is not None
    assert coverage(shown) == 0.0, (
        "the undone stroke is still in the mask", shown.name, coverage(shown)
    )

    # Drawing again still updates the mask.
    draw_line(canvas)
    gpb.mark_gp_mask_dirty(canvas, schedule=True, geometry=True, immediate=True)
    pump(2.0)
    assert coverage(canvas.fbp_gp_mask_image) > 0.5
    print("FBPTEST gp_mask_undo_stale_pixels: PASS")
except Exception:
    traceback.print_exc()
    raise
finally:
    if gpb is not None and reuse_delay is not None:
        gpb._GP_MASK_IMAGE_REUSE_DELAY = reuse_delay
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
