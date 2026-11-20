"""Transform box of the rig styles.

* A Legacy layer shows its wire only: no transform box, even when selected.
* A Digital Alpha Outline layer gets its handles on the box around the
  visible pixels, not on the whole plane (a small drawing on a large canvas
  gets a small box).
* Points that are not finite never reach the GPU.

Run with Blender 5.2 or 5.3:
    blender -b --factory-startup --python-exit-code 1 \
        --python frame_by_plane/tests/rig_box_regression.py
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


def use_bundled_pillow():
    """From the source tree Pillow is not installed (the extension installs it
    from ``wheels/``): unpack this platform's wheel so the Alpha Outline can
    read the drawing's pixels."""
    try:
        import PIL  # noqa: F401
        return
    except ImportError:
        pass
    import platform
    import zipfile
    tags = {
        ("Linux", "x86_64"): "manylinux", ("Darwin", "arm64"): "macosx_11_0_arm64",
        ("Darwin", "x86_64"): "macosx_10_13_x86_64", ("Windows", "AMD64"): "win_amd64",
        ("Windows", "ARM64"): "win_arm64",
    }
    tag = tags.get((platform.system(), platform.machine()))
    wheels = Path(__file__).resolve().parents[1] / "wheels"
    for wheel in sorted(wheels.glob("pillow-*.whl")):
        if tag and tag in wheel.name:
            target = Path(tempfile.mkdtemp(prefix="fbp_pillow_"))
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(target)
            sys.path.insert(0, str(target))
            return


if not INSTALLED_PACKAGE:
    use_bundled_pillow()
addon = importlib.import_module(PACKAGE_NAME)
if not INSTALLED_PACKAGE:
    addon.register()


def rigs():
    return [obj for obj in bpy.context.scene.objects if bool(getattr(obj, "is_fbp_control", False))]


def write_drawing(path, width, height, box):
    """A PNG with one opaque rectangle ``box = (x0, y0, x1, y1)`` (pixels,
    origin bottom-left) on a transparent canvas."""
    image = bpy.data.images.new(path.stem, width=width, height=height, alpha=True)
    try:
        pixels = [0.0] * (width * height * 4)
        x0, y0, x1, y1 = box
        for y in range(y0, y1):
            for x in range(x0, x1):
                index = (y * width + x) * 4
                pixels[index:index + 4] = (0.9, 0.4, 0.2, 1.0)
        image.pixels.foreach_set(pixels)
        image.filepath_raw = str(path)
        image.file_format = 'PNG'
        image.save()
    finally:
        bpy.data.images.remove(image)


try:
    layer_cage = importlib.import_module(f"{PACKAGE_NAME}.layer_cage")
    operator_import = importlib.import_module(f"{PACKAGE_NAME}.operator_import")
    for operator_class in (operator_import.FBP_OT_ImportSequence, operator_import.FBP_OT_GenerateMultiplane):
        if getattr(bpy.types, operator_class.__name__, None) is None:
            bpy.utils.register_class(operator_class)

    workdir = Path(tempfile.mkdtemp(prefix="fbp_rig_box_"))
    # 80 x 40 canvas, drawing in the left half: x 8..32, y 10..30.
    write_drawing(workdir / "corner.png", 80, 40, (8, 10, 32, 30))
    write_drawing(workdir / "legacy.png", 80, 40, (8, 10, 32, 30))

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    scene = bpy.context.scene
    camera = bpy.data.objects.new("Box Camera", bpy.data.cameras.new("Box Camera"))
    camera.location = (0.0, -12.0, 0.0)
    camera.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.collection.objects.link(camera)
    scene.camera = camera
    bpy.context.view_layer.update()

    rows = [
        ("Corner", "", str(workdir), ["corner.png"], False),
        ("Legacy", "", str(workdir), ["legacy.png"], False),
    ]
    assert operator_import._fbp_prepare_pending_rows(bpy.context, str(workdir), rows) == 2
    assert 'FINISHED' in bpy.ops.fbp.generate_multiplane('EXEC_DEFAULT', camera_mode='KEEP')
    layers = {rig.name: rig for rig in rigs()}
    digital, legacy = layers["Corner"], layers["Legacy"]
    assert digital.fbp_rig_shape == 'ALPHA' and digital.fbp_rig_style == 'DIGITAL'
    legacy.fbp_rig_style = 'LEGACY'

    # 1. Selected Legacy layers show no transform box; Digital ones do.
    bpy.ops.object.select_all(action='DESELECT')
    digital.select_set(True)
    legacy.select_set(True)
    bpy.context.view_layer.objects.active = digital
    shown = {rig.name for rig in layer_cage._cage_layers(bpy.context)}
    assert shown == {"Corner"}, shown
    legacy.fbp_rig_style = 'DIGITAL'
    shown = {rig.name for rig in layer_cage._cage_layers(bpy.context)}
    assert shown == {"Corner", "Legacy"}, shown

    # 2. The Alpha Outline box hugs the drawing, not the whole canvas.
    digital.fbp_rig_shape_expand = 0.0
    center, size = layer_cage.layer_cage_rect(digital)
    box_center, box_size, outline, alpha = layer_cage.box_shape(digital, center, size)
    assert alpha, "no Alpha Outline segments"
    assert not outline
    # The drawing is 24 x 20 px of an 80 x 40 canvas, in its left half.
    width_ratio = box_size.x / size.x
    height_ratio = box_size.y / size.y
    assert 0.2 < width_ratio < 0.45, ("box wider than the drawing", width_ratio)
    assert 0.35 < height_ratio < 0.65, ("box taller than the drawing", height_ratio)
    assert box_center.x < center.x - size.x * 0.15, ("box not on the drawing", box_center.x, center.x)
    xs = [point[0] for point in alpha]
    ys = [point[1] for point in alpha]
    assert abs(min(xs) - (box_center.x - box_size.x * 0.5)) < 1.0e-5
    assert abs(max(ys) - (box_center.y + box_size.y * 0.5)) < 1.0e-5
    corners, _edges = layer_cage.local_handles(box_center, box_size, outline)
    assert all(min(xs) - 1.0e-5 <= corner.x <= max(xs) + 1.0e-5 for corner in corners), corners

    # 3. Other shapes keep the plane box.
    digital.fbp_rig_shape = 'DEFAULT'
    box_center, box_size, outline, alpha = layer_cage.box_shape(digital, center, size)
    assert not alpha and abs(box_size.x - size.x) < 1.0e-5, (box_size, size)

    # 4. Points that are not finite are dropped before drawing.
    positions, colors = layer_cage._colored([
        ([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], (1.0, 1.0, 1.0), 1.0),
        ([(float("nan"), 0.0, 0.0), (1.0, 1.0, 0.0)], (1.0, 1.0, 1.0), 1.0),
    ])
    assert len(positions) == 2 and len(colors) == 2, positions

    print("FBPTEST rig box: PASS")
except Exception:
    traceback.print_exc()
    sys.exit(1)
