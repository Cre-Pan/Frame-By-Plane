"""Apply add-on preference defaults to Blender scenes.

Keeping scene initialization outside ``properties.py`` prevents handlers and
operators from importing the complete RNA schema simply to apply defaults.
"""

from __future__ import annotations

import bpy

from .interface_preferences import fbp_get_addon_preferences
from .runtime import FBP_DATA_ERRORS


PREFERENCES_SCENE_MARKER = "fbp_preferences_initialized"


def fbp_apply_preferences_to_scene(scene, *, force=False, context=None):
    if not scene:
        return False
    try:
        if not force and bool(scene.get(PREFERENCES_SCENE_MARKER, False)):
            return False
    except FBP_DATA_ERRORS:
        return False

    prefs = fbp_get_addon_preferences(context)
    if prefs is None:
        # Preferences can be temporarily unavailable during registration or file
        # loading. Leave the Scene unmarked so a later scene-sync can retry.
        return False

    project_path = str(getattr(prefs, "default_project_path", "") or "")
    last_directory = str(getattr(prefs, "default_last_directory", "") or "") or project_path

    assignments = {
        "fbp_last_directory": last_directory,
        "fbp_creation_mode": getattr(prefs, "default_creation_mode", 'SINGLE'),
        "fbp_pre_duration": getattr(prefs, "default_frame_duration", 2),
        "fbp_pre_shadeless": getattr(prefs, "default_emission", True),
        "fbp_import_crop_alpha": getattr(prefs, "default_import_crop_alpha", False),
        "fbp_import_crop_alpha_padding": getattr(prefs, "default_import_crop_alpha_padding", 0),
        "fbp_pre_loop_mode": getattr(prefs, "default_playback", 'NONE'),
        "fbp_pre_interpolation": getattr(prefs, "default_interpolation", 'Closest'),
        "fbp_pre_orientation": getattr(prefs, "default_orientation", 'VERT'),
        "fbp_layer_offset": getattr(prefs, "default_layer_offset", 0.2),
        "fbp_auto_scale": getattr(prefs, "default_fit_to_camera", True),
        "fbp_camera_fit_source_aspect": getattr(prefs, "default_camera_fit_source_aspect", True),
        "fbp_pre_track_cam": getattr(prefs, "default_track_camera", False),
        "fbp_gen_camera": getattr(prefs, "default_generate_camera", True),
        "fbp_cam_pivot": getattr(prefs, "default_camera_pivot", True),
        "fbp_camera_projection": getattr(prefs, "default_camera_projection", 'PERSP'),
        "fbp_cam_ratio": getattr(prefs, "default_camera_ratio", '4_3'),
        "fbp_camera_lens": getattr(prefs, "default_camera_lens", 50.0),
        "fbp_camera_ortho_scale": getattr(prefs, "default_camera_ortho_scale", 10.0),
        "fbp_camera_clip_start": getattr(prefs, "default_camera_clip_start", 0.1),
        "fbp_camera_clip_end": getattr(prefs, "default_camera_clip_end", 1000.0),
        "fbp_auto_collection_color_variants": getattr(prefs, "default_color_variants", True),
        "fbp_auto_clean_orphans": getattr(prefs, "default_auto_clean_orphans", True),
        "fbp_show_previews": getattr(prefs, "default_show_previews", False),
        "fbp_show_color_previews": getattr(prefs, "default_show_color_previews", True),
        "fbp_sort_layers_alpha": getattr(prefs, "default_sort_layers_alpha", False),
        "fbp_show_project_tools": getattr(prefs, "default_show_project_tools", False),
        "fbp_experimental_compositor": getattr(prefs, "default_preview_compositor", False),
        "fbp_preview_procreate_import": getattr(prefs, "default_preview_procreate_import", False),
        "fbp_preview_generic_mesh_effects": getattr(prefs, "default_preview_generic_mesh_effects", False),
        "fbp_show_gradient_ramp": getattr(prefs, "default_show_gradient_ramp", True),
        "fbp_show_gradient_transform": getattr(prefs, "default_show_gradient_transform", True),
        "fbp_alpha_render_method": getattr(prefs, "default_alpha_render_method", 'AUTO'),
        "fbp_color_plane_type": getattr(prefs, "default_color_plane_type", 'CUSTOM'),
        "fbp_color_plane_color": getattr(prefs, "default_color_plane_color", (1.0, 1.0, 1.0, 1.0)),
        "fbp_color_plane_emission": getattr(prefs, "default_color_plane_emission", True),
        "fbp_gradient_mode": getattr(prefs, "default_gradient_mode", 'LINEAR'),
        "fbp_gradient_kind": getattr(prefs, "default_gradient_kind", 'COLOR'),
        "fbp_gradient_color_a": getattr(prefs, "default_gradient_color_a", (1.0, 0.3686274509803922, 0.596078431372549, 1.0)),
        "fbp_gradient_color_b": getattr(prefs, "default_gradient_color_b", (0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0)),
        "fbp_gradient_reverse": getattr(prefs, "default_gradient_reverse", True),
        "fbp_gradient_offset_x": getattr(prefs, "default_gradient_offset_x", 0.0),
        "fbp_gradient_offset_y": getattr(prefs, "default_gradient_offset_y", 0.0),
        "fbp_gradient_scale_x": getattr(prefs, "default_gradient_scale_x", 1.0),
        "fbp_gradient_scale_y": getattr(prefs, "default_gradient_scale_y", 1.0),
        "fbp_gradient_rotation": getattr(prefs, "default_gradient_rotation", 0.0),
    }
    if project_path:
        assignments["fbp_project_path"] = project_path

    # Existing .blend files already have an authoritative native Render File
    # Path. Automatic initialization must not overwrite it with add-on defaults.
    # The explicit "Apply Defaults" action uses force=True and may intentionally
    # replace it.
    try:
        native_render_path = str(getattr(scene.render, "filepath", "") or "").strip()
    except FBP_DATA_ERRORS:
        native_render_path = ""
    if force or not native_render_path:
        assignments.update({
            "fbp_render_output_dir": getattr(prefs, "default_render_output_dir", ""),
            "fbp_render_prefix": getattr(prefs, "default_render_prefix", ""),
            "fbp_render_filename_mode": 'COMPOSE',
            "fbp_render_name_source": 'CUSTOM',
            "fbp_render_custom_name": "",
            "fbp_render_separator": getattr(prefs, "default_render_separator", 'DASH'),
            "fbp_render_frame_digits": getattr(prefs, "default_render_frame_digits", 4),
            "fbp_render_folder_builder_mode": 'GENERATE',
            "fbp_render_folder_name": "",
            "fbp_render_folder_tag": 'TEST',
            "fbp_render_folder_mode": 'ROOT',
            "fbp_render_auto_increment_test": getattr(prefs, "default_render_auto_increment_test", True),
        })

    changed = False
    for attr, value in assignments.items():
        try:
            if getattr(scene, attr) != value:
                setattr(scene, attr, value)
                changed = True
        except FBP_DATA_ERRORS:
            pass

    try:
        if hasattr(scene, 'playback_loop_mode'):
            desired_loop = str(getattr(prefs, 'default_scene_playback_loop_mode', 'INFINITE') or 'INFINITE')
            if str(getattr(scene, 'playback_loop_mode', '') or '') != desired_loop:
                scene.playback_loop_mode = desired_loop
                changed = True
        if hasattr(scene, 'allow_preroll'):
            desired_preroll = bool(getattr(prefs, 'default_scene_allow_preroll', False))
            if bool(getattr(scene, 'allow_preroll', False)) != desired_preroll:
                scene.allow_preroll = desired_preroll
                changed = True
    except FBP_DATA_ERRORS:
        pass

    try:
        render = getattr(scene, 'render', None)
        if render is not None and hasattr(render, 'anisotropic_filter'):
            desired_filter = str(getattr(prefs, 'default_anisotropic_filter', 'FILTER_2') or 'FILTER_2')
            if str(getattr(render, 'anisotropic_filter', '') or '') != desired_filter:
                render.anisotropic_filter = desired_filter
                changed = True
        cache_enabled = bool(getattr(prefs, 'default_cycles_texture_cache', True))
        if render is not None and hasattr(render, 'use_texture_cache'):
            if bool(getattr(render, 'use_texture_cache', False)) != cache_enabled:
                render.use_texture_cache = cache_enabled
                changed = True
        if render is not None and hasattr(render, 'use_auto_generate_texture_cache'):
            desired_auto_cache = cache_enabled and bool(
                getattr(prefs, 'default_cycles_auto_texture_cache', False)
            )
            if bool(getattr(render, 'use_auto_generate_texture_cache', False)) != desired_auto_cache:
                render.use_auto_generate_texture_cache = desired_auto_cache
                changed = True
    except FBP_DATA_ERRORS:
        pass

    # Set the preset after the custom color. The color update callback switches
    # non-Custom presets back to Custom, while the preset callback intentionally
    # applies the selected preset color. This ordering preserves the preference.
    try:
        scene.fbp_color_plane_preset = getattr(prefs, "default_color_plane_preset", 'CUSTOM')
        changed = True
    except FBP_DATA_ERRORS:
        pass

    try:
        scene.render.fps = int(getattr(prefs, "default_scene_fps", 24))
    except FBP_DATA_ERRORS:
        pass
    if getattr(prefs, "default_camera_ratio", '4_3') == 'CUSTOM':
        try:
            scene.render.resolution_x = int(getattr(prefs, "default_resolution_x", 1920))
            scene.render.resolution_y = int(getattr(prefs, "default_resolution_y", 1440))
        except FBP_DATA_ERRORS:
            pass
    try:
        scene[PREFERENCES_SCENE_MARKER] = True
    except FBP_DATA_ERRORS:
        pass
    return changed


def fbp_mark_scenes_preferences_initialized(scenes=None):
    try:
        scenes = scenes if scenes is not None else getattr(bpy.data, "scenes")
        items = tuple(scenes)
    except FBP_DATA_ERRORS:
        return 0
    marked = 0
    for scene in items:
        try:
            scene[PREFERENCES_SCENE_MARKER] = True
            marked += 1
        except FBP_DATA_ERRORS:
            pass
    return marked



__all__ = (
    "PREFERENCES_SCENE_MARKER",
    "fbp_apply_preferences_to_scene",
    "fbp_mark_scenes_preferences_initialized",
)
