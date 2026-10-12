"""Verify the installed Frame By Plane release and bundled dependencies."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import attrs
import bpy
import PIL
import psd_tools
import typing_extensions


BASE = "bl_ext.fbp_audit.frame_by_plane"
REPORT = Path(os.environ["FBP_INSTALLED_CONTRACT_REPORT"]).resolve()


def _group_socket_names(group, in_out):
    return {
        str(getattr(item, "name", "") or "")
        for item in tuple(getattr(getattr(group, "interface", None), "items_tree", ()) or ())
        if getattr(item, "item_type", "") == "SOCKET"
        and getattr(item, "in_out", "") == in_out
    }


def main():
    constants = importlib.import_module(f"{BASE}.constants")
    scrub = importlib.import_module(f"{BASE}.grease_pencil_scrub")
    geometry = importlib.import_module(f"{BASE}.geometry_nodes")
    builtin = importlib.import_module(f"{BASE}.builtin_effects")
    registry = importlib.import_module(f"{BASE}.effects_registry")
    bridge = importlib.import_module(f"{BASE}.grease_pencil_bridge")
    gp_colors = importlib.import_module(f"{BASE}.gp_vertex_colors")
    ui = importlib.import_module(f"{BASE}.ui")
    operator_import = importlib.import_module(f"{BASE}.operator_import")
    importlib.import_module(f"{BASE}.timeline_backport")

    assert constants.FBP_VERSION_STRING == "7.5.5"
    assert hasattr(bpy.ops.fbp, "import_folder_multiplane")
    assert hasattr(bpy.ops.fbp, "create_color_plane_from_hex")

    items = {
        identifier: {
            "label": label,
            "description": description,
            "icon": icon,
            "index": index,
        }
        for identifier, label, description, icon, index in scrub._BOOKMARK_COLOR_ITEMS
    }
    assert items["NONE"]["label"] == "None"
    assert items["NONE"]["icon"] == "SNAP_FACE"
    assert items["GREY"]["icon"] == "STRIP_COLOR_09"
    assert "WHITE" not in items
    assert "BLUE" not in items
    assert items["CYAN"]["label"] == "Cyan"
    assert scrub._bookmark_color_tag("WHITE") == "NONE"
    assert scrub._bookmark_color_tag("BLUE") == "CYAN"
    assert scrub._bookmark_color_tag("CYAN") == "CYAN"

    scene = bpy.context.scene
    gp_dual_color_contract = bool(
        hasattr(bpy.types.Object, "fbp_gp_vertex_color_state")
        and hasattr(bpy.types, gp_colors.FBP_PT_GPVertexColors.bl_idname)
        and hasattr(bpy.ops.fbp, "swap_gp_vertex_colors")
        and hasattr(bpy.ops.fbp, "sample_gp_stroke_color")
        and hasattr(bpy.ops.fbp, "toggle_gp_close_gap")
        and gp_colors._HEADER_REGISTERED
        and len(gp_colors._ADDON_KEYMAPS) == 3
    )
    assert gp_dual_color_contract
    compositor_opt_in_contract = bool(
        hasattr(bpy.types.Scene, "fbp_compositor_render_enabled")
        and scene.fbp_compositor_render_enabled is False
    )
    assert compositor_opt_in_contract
    image_properties_contract = bool(
        ui.FBP_PT_ImagePlaneData in ui.ui_classes
        and ui.FBP_PT_ImagePlaneData.bl_context == "data"
        and not getattr(ui.FBP_PT_ImagePlaneData, "bl_parent_id", "")
    )
    assert image_properties_contract
    marker = scene.timeline_markers.new("\u2726 - Legacy Blue", frame=24)
    marker.select = True
    scene["_fbp_scrub_bookmarks_v1"] = json.dumps([
        {
            "uid": "legacy-blue-installed-contract",
            "label": "Legacy Blue",
            "color_tag": "BLUE",
            "marker_name": marker.name,
            "frame": marker.frame,
        }
    ])
    record = scrub.scrub_bookmark_records(scene)[0]
    assert record["color_tag"] == "CYAN", record

    felt_definition = registry.FBP_EFFECT_REGISTRY["FELT_FUZZ"]
    felt_group = geometry._fbp_load_effect_group("FELT_FUZZ")
    felt_inputs = _group_socket_names(felt_group, "INPUT")
    felt_contract = bool(
        felt_group is not None
        and builtin._builtin_group_is_complete(felt_group, felt_definition)
        and {"Seed", "Use Alpha Mask", "Alpha Threshold", "Alpha Resolution"} <= felt_inputs
    )
    assert felt_contract, sorted(felt_inputs)

    # The Frame By Plane GP effect stack, Ink Over Image and Limited Loop
    # tools were removed in favor of Blender's native panels.
    gp_removed_tools_contract = bool(
        not hasattr(bpy.types, "FBP_UL_GPNativeEffectStack")
        and not hasattr(bpy.types, "FBP_MT_gp_native_effects")
        and not hasattr(bpy.types, "FBP_PT_grease_pencil_limited_loop")
        and not hasattr(bridge, "GP_NATIVE_EFFECTS")
        and not hasattr(bpy.types.Object, "fbp_gp_loop_blocks")
    )
    assert gp_removed_tools_contract

    blender_icons = {
        item.identifier
        for item in bpy.types.UILayout.bl_rna.functions["operator"]
        .parameters["icon"].enum_items
    }

    reports = []

    class ReportingOperator:
        def report(self, level, message):
            reports.append((set(level), str(message)))

    class StaleImportScene:
        def __getattribute__(self, name):
            if str(name).startswith("fbp_"):
                raise ReferenceError("StructRNA of type Scene has been removed")
            return super().__getattribute__(name)

    stale_import_scene_contract = not operator_import._fbp_require_import_scene_properties(
        ReportingOperator(),
        StaleImportScene(),
    )
    assert stale_import_scene_contract
    assert reports and reports[-1][0] == {"ERROR"}, reports

    camera_output = importlib.import_module(f"{BASE}.camera_output")
    scene = bpy.context.scene
    scene.fbp_camera_aspect = '16:9'
    scene.fbp_camera_resolution = '4K'
    camera_output_contract = (scene.render.resolution_x, scene.render.resolution_y) == (3840, 2160)
    scene.fbp_camera_resolution = 'CUSTOM'
    scene.fbp_camera_fit_source_aspect = True
    scene.fbp_camera_dimensions_linked = False
    scene.fbp_camera_width, scene.fbp_camera_height = 1234, 987
    camera_output_contract &= scene.fbp_camera_aspect == '1234:987' and scene.fbp_cam_ratio == 'CUSTOM'
    assert camera_output_contract

    assert len(camera_output.ASPECT_PRESETS) == 10
    assert {'IMAGE_BACKGROUND', 'RENDER_SWAP_DIMENSIONS'} <= blender_icons
    scene.fbp_camera_resolution = 'HD'
    assert bpy.ops.fbp.set_camera_aspect(preset='FOUR_FIVE') == {'FINISHED'}
    assert (scene.render.resolution_x, scene.render.resolution_y) == (1920, 1536)
    assert camera_output.camera_aspect_menu_label(scene) == '4:5'

    scene.fbp_camera_aspect = '1:1'
    scene.fbp_camera_dimensions_linked = True
    scene.fbp_camera_height = 1000
    assert (scene.render.resolution_x, scene.render.resolution_y) == (1000, 1000)
    scene.fbp_camera_dimensions_linked = False
    scene.fbp_camera_width = 1200
    assert (scene.render.resolution_x, scene.render.resolution_y) == (1200, 1000)
    assert camera_output.camera_aspect_menu_label(scene) == 'Custom'
    assert bpy.ops.fbp.save_camera_format_preset(name='Installed Custom') == {'FINISHED'}
    scene.fbp_camera_aspect = '16:9'
    assert bpy.ops.fbp.apply_camera_format_preset(index=0) == {'FINISHED'}
    assert (scene.render.resolution_x, scene.render.resolution_y) == (1200, 1000)
    assert camera_output.camera_aspect_menu_label(scene) == 'Custom'
    assert bpy.ops.fbp.remove_camera_format_preset(index=0) == {'FINISHED'}
    scene.fbp_camera_aspect = '4:5'
    scene.fbp_camera_resolution = 'HD'
    assert bpy.ops.fbp.swap_camera_dimensions() == {'FINISHED'}
    assert (scene.render.resolution_x, scene.render.resolution_y) == (1536, 1920)
    scene.fbp_camera_resolution = '4K'
    assert (scene.render.resolution_x, scene.render.resolution_y) == (3072, 3840)
    assert camera_output.camera_aspect_menu_label(scene) == '4:5'

    class EditingCanvas:
        mode = 'EDIT'

    gp_edit_undo_guard = not bridge._gp_external_settings_undo_safe(EditingCanvas())
    assert gp_edit_undo_guard

    workspace = bpy.context.workspace
    timeline_contract = bool(
        all(
            hasattr(workspace, name)
            for name in (
                "show_jump_to_endpoints",
                "show_jump_to_keyframes",
                "show_jump_by_delta",
                "use_scene_time_sync_follow_scene",
                "fbp_use_scene_time_sync",
            )
        )
        and all(
            hasattr(bpy.types, name)
            for name in (
                "FBP_PT_time_jump",
                "FBP_PT_dopesheet_time_sync",
                "FBP_PT_graph_time_sync",
                "FBP_PT_nla_time_sync",
                "FBP_PT_sequencer_time_sync",
            )
        )
    )
    assert timeline_contract

    payload = {
        "blender": bpy.app.version_string,
        "addon_version": constants.FBP_VERSION_STRING,
        "bookmark_palette_migrated": bool(
            record["color_tag"] == "CYAN"
            and scrub._bookmark_color_tag("WHITE") == "NONE"
        ),
        "palette": items,
        "folder_clipboard_operator": hasattr(bpy.ops.fbp, "import_folder_multiplane"),
        "hex_color_operator": hasattr(bpy.ops.fbp, "create_color_plane_from_hex"),
        "felt_fuzz_contract": felt_contract,
        "felt_fuzz_inputs": sorted(felt_inputs),
        "gp_removed_tools_contract": gp_removed_tools_contract,
        "gp_dual_color_contract": gp_dual_color_contract,
        "compositor_opt_in_contract": compositor_opt_in_contract,
        "image_properties_contract": image_properties_contract,
        "stale_import_scene_contract": stale_import_scene_contract,
        "camera_output_contract": camera_output_contract,
        "camera_aspect_dropdown_contract": True,
        "camera_linked_pixels_presets_contract": True,
        "gp_edit_undo_guard": gp_edit_undo_guard,
        "timeline_backport_contract": timeline_contract,
        "wheels": {
            "pillow": PIL.__version__,
            "psd_tools": psd_tools.__version__,
            "attrs": attrs.__version__,
            "typing_extensions": getattr(typing_extensions, "__version__", "imported"),
        },
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
