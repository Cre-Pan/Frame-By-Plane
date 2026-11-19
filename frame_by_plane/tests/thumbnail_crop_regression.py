"""Thumbnail alpha crop: subject framing, toggle, cache and frame-list menus."""

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
layers = importlib.import_module(f"{PACKAGE_NAME}.layers")


def _write_subject_png(path, size=200):
    """A transparent canvas with one opaque red square in the lower-left area."""
    image = bpy.data.images.new("fbp_crop_source", width=size, height=size, alpha=True)
    pixels = [0.0] * (size * size * 4)
    for y in range(20, 60):
        for x in range(30, 90):
            offset = (y * size + x) * 4
            pixels[offset:offset + 4] = (1.0, 0.0, 0.0, 1.0)
    image.pixels.foreach_set(pixels)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def _opaque_bounds(preview):
    import numpy as np

    width, height = preview.image_size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    preview.image_pixels_float.foreach_get(pixels)
    alpha = pixels.reshape(height, width, 4)[:, :, 3]
    return width, height, layers._alpha_bounds(alpha, 0.5)


try:
    import numpy as np

    # Pure helpers: bounds and square letterbox with padding.
    alpha = np.zeros((10, 20), dtype=np.float32)
    alpha[2:5, 4:9] = 1.0
    assert layers._alpha_bounds(alpha) == (4, 2, 9, 5)
    assert layers._alpha_bounds(np.zeros((4, 4), dtype=np.float32)) is None
    source = np.zeros((10, 20, 4), dtype=np.float32)
    source[2:5, 4:9] = (0.0, 1.0, 0.0, 1.0)
    side, output = layers._square_preview_pixels(
        20, 10, source.ravel(), background_enabled=False,
        background=(1.0, 1.0, 1.0, 1.0), crop_alpha=True,
    )
    assert side == 5, side
    side, output = layers._square_preview_pixels(
        20, 10, source.ravel(), background_enabled=False,
        background=(1.0, 1.0, 1.0, 1.0), crop_alpha=False,
    )
    assert side == 20, side
    # Opaque square with no background and no crop: nothing to composite.
    opaque = np.ones((8, 8, 4), dtype=np.float32)
    assert layers._square_preview_pixels(
        8, 8, opaque.ravel(), background_enabled=False,
        background=(1.0, 1.0, 1.0, 1.0), crop_alpha=True,
    ) is None
    # Background composite fills transparent pixels.
    side, output = layers._square_preview_pixels(
        20, 10, source.ravel(), background_enabled=True,
        background=(0.0, 0.0, 1.0, 1.0), crop_alpha=False,
    )
    grid = np.asarray(output).reshape(side, side, 4)
    assert tuple(grid[0, 0]) == (0.0, 0.0, 1.0, 1.0), tuple(grid[0, 0])
    print("FBPTEST thumbnail_crop_helpers: PASS")

    if not INSTALLED_PACKAGE:
        addon.register()
    scene = bpy.context.scene
    assert scene.fbp_thumbnail_crop_alpha is True, "alpha crop must be on by default"

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "subject.png"
        _write_subject_png(path)

        cropped = layers.load_preview(str(path), scene=scene)
        assert cropped is not None
        width, height, bounds = _opaque_bounds(cropped)
        assert width == height, (width, height)
        x0, y0, x1, y1 = bounds
        # The 60x40 subject must fill the width up to the small padding.
        assert (x1 - x0) / width > 0.8, (bounds, width)
        print("FBPTEST thumbnail_crop_default: PASS", width, bounds)

        # Cached: the same preview object is returned on redraw.
        assert tuple(layers.load_preview(str(path), scene=scene).image_size) == (width, height)

        scene.fbp_thumbnail_crop_alpha = False
        raw = layers.load_preview(str(path), scene=scene)
        raw_width, raw_height, raw_bounds = _opaque_bounds(raw)
        assert (raw_bounds[2] - raw_bounds[0]) / raw_width < 0.5, (raw_bounds, raw_width)
        assert tuple(raw.image_size) == (200, 200), tuple(raw.image_size)
        print("FBPTEST thumbnail_crop_toggle_off: PASS", raw_width, raw_bounds)

        scene.fbp_thumbnail_crop_alpha = True
        square = layers.load_preview(str(path), scene=scene, force_square=True)
        assert tuple(square.image_size) == (width, height)

        assert layers.invalidate_preview_path(str(path)) is True
        layers.clear_previews()
        print("FBPTEST thumbnail_crop_cache: PASS")

    # Both frame-list menus expose the toggles.
    ui = importlib.import_module(f"{PACKAGE_NAME}.ui")
    drawing = importlib.import_module(f"{PACKAGE_NAME}.drawing_plane")
    import inspect
    assert "_fbp_draw_thumbnail_toggles(layout, context)" in inspect.getsource(ui.FBP_MT_SequenceFrameActions.draw)
    assert "fbp_thumbnail_crop_alpha" in inspect.getsource(drawing.FBP_MT_DrawingListActions.draw)
    print("FBPTEST thumbnail_crop_menus: PASS")
    if not INSTALLED_PACKAGE:
        addon.unregister()
    print("FBPTEST thumbnail_crop_regression: PASS")
except Exception:
    traceback.print_exc()
    print("FBPTEST thumbnail_crop_regression: FAIL")
    sys.exit(1)
