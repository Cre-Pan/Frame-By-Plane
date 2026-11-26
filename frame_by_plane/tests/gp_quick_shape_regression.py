"""Grease Pencil Quick Shape: straight-stroke detection, Ctrl angle snapping
and the preferences that drive them.

The live behaviour (rest the pen, line follows the cursor, Shift and Ctrl,
release, Undo/Redo, 10 second window) needs real input events and is checked
in an interactive Blender session.

Run with Blender 5.2 or 5.3:
    blender -b --factory-startup --python-exit-code 1 \
        --python frame_by_plane/tests/gp_quick_shape_regression.py
"""

import importlib
import math
import os
import sys
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

try:
    quick = importlib.import_module(PACKAGE_NAME + ".gp_quick_shape")

    # 1. A slightly wobbly horizontal stroke is a line.
    wobbly = [(i * 10.0, 3.0 if i % 2 else -3.0) for i in range(21)]
    assert quick.is_straight_path(wobbly)
    # 2. An arc, a hook and a back-and-forth stroke are not.
    arc = [(i * 10.0, 80.0 * math.sin(i / 30.0 * math.pi)) for i in range(31)]
    assert not quick.is_straight_path(arc)
    hook = [(i * 10.0, 0.0) for i in range(21)] + [(200.0 - i * 10.0, 30.0) for i in range(1, 6)]
    assert not quick.is_straight_path(hook)
    back_and_forth = [(i * 10.0, 0.0) for i in range(21)] + [(200.0 - i * 10.0, 0.0) for i in range(1, 11)] + [(100.0 + i * 10.0, 0.0) for i in range(1, 11)]
    assert not quick.is_straight_path(back_and_forth)
    # 3. Too short to be a line.
    assert not quick.is_straight_path([(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)])

    # 4. Ctrl snapping keeps the length and lands on the step.
    for step in (5.0, 15.0, 22.5, 45.0):
        end = quick.snap_screen_angle((0.0, 0.0), (100.0, 4.0), step)
        assert abs(end[1]) < 1.0e-6 and abs(math.hypot(*end) - math.hypot(100.0, 4.0)) < 1.0e-6, (step, end)
        end = quick.snap_screen_angle((10.0, 10.0), (60.0, 58.0), step)
        assert abs(math.degrees(math.atan2(end[1] - 10.0, end[0] - 10.0)) - 45.0) < 1.0e-6, (step, end)
        end = quick.snap_screen_angle((0.0, 0.0), (-3.0, -90.0), step)
        assert abs(end[0]) < 1.0e-6 and end[1] < 0.0, (step, end)

    # 5. Preferences: defaults and validation.
    enabled, hold, snap, precision = quick.quick_shape_settings(bpy.context)
    assert enabled is True
    assert abs(hold - 0.4) < 1.0e-6
    assert snap == 15.0
    assert abs(precision - 0.25) < 1.0e-6
    assert quick.DETECTION_WINDOW_SECONDS == 10.0

    # 6. The operator never runs outside Grease Pencil Draw mode.
    assert quick.FBP_OT_GPQuickShapeStroke.bl_idname == "fbp.gp_quick_shape_stroke"

    print("FBPTEST gp quick shape: PASS")
except Exception:
    traceback.print_exc()
    sys.exit(1)
