"""Advanced Render: off by default and leaves Blender's Output path alone;
on, it builds Prefix / Name / Suffix with per-section switches and tokens.
Project Doctor no longer reports layer timing outside the Scene range.

Run with Blender 5.2 or 5.3:
    blender -b --factory-startup --python-exit-code 1 \
        --python frame_by_plane/tests/advanced_render_regression.py
"""

import importlib
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


def check(condition, message):
    if not condition:
        raise AssertionError(message)


try:
    render_output = importlib.import_module(f"{PACKAGE_NAME}.render_output")
    scene = bpy.context.scene

    # Off by default: Frame By Plane never writes Blender's Output path.
    check(not scene.fbp_render_advanced, "Advanced Render must be off by default")
    scene.render.filepath = "//native_output/frame_"
    scene.fbp_render_prefix = "Shot"
    check(scene.render.filepath == "//native_output/frame_", "Output path changed while Advanced Render is off")
    check(not render_output.fbp_sync_render_output_from_native(scene, force=True), "Native path was imported while off")
    check(scene.fbp_render_prefix == "Shot", "Builder was overwritten while off")

    # Stacked sections, tokens and separators.
    scene.fbp_render_custom_name = "Test"
    scene.fbp_render_suffix = "v"
    scene.fbp_render_separator = 'DASH'
    scene.fbp_render_frame_digits = 4
    scene.fbp_render_letter = "A"
    scene.fbp_render_number = 1
    scene.fbp_render_number_digits = 1
    pattern = render_output.fbp_render_filename_pattern
    check(pattern(scene) == "Shot - Test - v - ####", pattern(scene))
    scene.fbp_render_prefix_token = 'NUMBER'
    check(pattern(scene) == "Shot 1 - Test - v - ####", pattern(scene))
    scene.fbp_render_prefix_token = 'LETTER'
    check(pattern(scene) == "Shot A - Test - v - ####", pattern(scene))
    scene.fbp_render_prefix_token = 'LETTER_NUMBER'
    scene.fbp_render_suffix_token = 'NUMBER'
    check(pattern(scene) == "Shot A1 - Test - v 1 - ####", pattern(scene))
    scene.fbp_render_use_suffix = False
    check(pattern(scene) == "Shot A1 - Test - ####", pattern(scene))
    scene.fbp_render_use_name = False
    scene.fbp_render_separator = 'UNDERSCORE'
    check(pattern(scene) == "Shot A1_####", pattern(scene))
    scene.fbp_render_use_prefix = False
    check(pattern(scene) == "frame_####", pattern(scene))
    for value, expected in (('NONE', "Test####"), ('SPACE', "Test ####"), ('HYPHEN', "Test-####")):
        scene.fbp_render_use_name = True
        scene.fbp_render_separator = value
        check(pattern(scene) == expected, f"{value}: {pattern(scene)}")
    check(
        [item.identifier for item in scene.bl_rna.properties["fbp_render_separator"].enum_items][0] == 'NONE',
        "None must be the first Separator choice",
    )

    # Legacy single token (before Prefix) is read as the Prefix token.
    scene.fbp_render_use_prefix = True
    scene.fbp_render_separator = 'DASH'
    scene.fbp_render_prefix_token = 'NONE'
    scene.fbp_render_suffix_token = 'NONE'
    scene.fbp_render_token_mode = 'NUMBER'
    scene.fbp_render_token_position = 'BEFORE'
    check(render_output.fbp_render_section_token(scene, 'PREFIX') == 'NUMBER', "Legacy token lost")
    check(render_output.fbp_render_section_token(scene, 'SUFFIX') == 'NONE', "Legacy token leaked to Suffix")
    scene.fbp_render_token_mode = 'NONE'

    # On: the builder path is written into Blender's Output path.
    scene.fbp_render_advanced = True
    check("Shot - Test" in scene.render.filepath, f"Output path not synchronized: {scene.render.filepath}")

    # Export date in the generated folder name, ordered by Blender's language.
    import datetime
    day = datetime.date(2026, 11, 24)
    text = render_output.fbp_render_date_text
    check(text('NUMERIC', day, "it_IT") == "24.11.2026", text('NUMERIC', day, "it_IT"))
    check(text('TEXT', day, "it_IT") == "24 Nov 2026", text('TEXT', day, "it_IT"))
    check(text('COMPACT', day, "it_IT") == "24-11-26", text('COMPACT', day, "it_IT"))
    check(text('NUMERIC', day, "en_US") == "11.24.2026", text('NUMERIC', day, "en_US"))
    check(text('TEXT', day, "ja_JP") == "2026 Nov 24", text('TEXT', day, "ja_JP"))
    check(text('TEXT', day, "de_DE") == "24 Nov 2026", text('TEXT', day, "de_DE"))
    scene.fbp_render_folder_builder_mode = 'GENERATE'
    scene.fbp_render_folder_name = "Spot"
    scene.fbp_render_folder_tag = 'TEST'
    scene.fbp_render_folder_use_date = True
    scene.fbp_render_folder_date_style = 'COMPACT'
    folder = render_output.fbp_render_folder_name(scene, when=day)
    check(folder.startswith("Spot TEST (") and folder.endswith(")"), folder)
    check(render_output.fbp_render_folder_name(scene).replace("Spot TEST ", "") in scene.render.filepath, scene.render.filepath)
    scene.fbp_render_folder_use_date = False
    check(render_output.fbp_render_folder_name(scene) == "Spot TEST", render_output.fbp_render_folder_name(scene))

    # Section switches: off folds the section and drops its part of the path.
    scene.fbp_render_use_file_naming = False
    check(not scene.fbp_render_show_file_naming, "File Naming did not fold when switched off")
    check(pattern(scene) == "####", pattern(scene))
    scene.fbp_render_use_file_naming = True
    check(scene.fbp_render_show_file_naming, "File Naming did not open when switched on")
    scene.fbp_render_folder_use_date = False
    scene.fbp_render_use_folder = False
    check(not scene.fbp_render_show_folder, "Folder did not fold when switched off")
    check(render_output.fbp_render_folder_name(scene) == "", "Folder off still adds a subfolder")
    scene.fbp_render_use_folder = True

    # Project Doctor: the layer frame-range check is gone.
    project_health = importlib.import_module(f"{PACKAGE_NAME}.project_health")
    check(not hasattr(project_health, "_sequence_end"), "Frame-range helper should be removed")
    result = project_health.scan_project_health(scene, repair=False)
    codes = {str(issue.get("code", "")) for issue in (result.get("issues", ()) or ())} if isinstance(result, dict) else set()
    check("FRAME_RANGE" not in codes and "EMPTY_COLLECTION" not in codes, f"Removed checks still reported: {codes}")
    print("ADVANCED_RENDER_REGRESSION_PASSED")
except Exception:
    traceback.print_exc()
    sys.exit(1)
