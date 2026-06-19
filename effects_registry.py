"""Effect identifiers, registry metadata and compatibility helpers.

This module is intentionally independent from the Geometry Nodes and shader
runtime.  UI, diagnostics and property callbacks can inspect the effect library
without importing the large runtime implementation in :mod:`geometry_nodes`.
"""

import time

from .custom_effects import (
    is_custom_effect_id,
    refresh_custom_effect_registry,
    set_custom_effect_registry_refresh_callback,
)
from .effect_schema import (
    FBP_EFFECT_SCHEMA_VERSION,
    finalize_effect_registry,
    validate_effect_registry,
)

FBP_EFFECT_MESH_WIGGLE = "MESH_WIGGLE"
FBP_EFFECT_STOP_MOTION_CRUMPLE = "STOP_MOTION_CRUMPLE"
FBP_EFFECT_WIND_BENDER = "WIND_BENDER"
FBP_EFFECT_MESH_RIPPLE = "MESH_RIPPLE"
FBP_EFFECT_PAPER_CURL = "PAPER_CURL"
FBP_EFFECT_CUTOUT_OUTLINE = "CUTOUT_OUTLINE"
FBP_EFFECT_EXTRUDED_CUTOUT = "EXTRUDED_CUTOUT"
FBP_EFFECT_CAMERA_SCALE_LOCK = "CAMERA_SCALE_LOCK"
FBP_EFFECT_CAMERA_BILLBOARD = "CAMERA_BILLBOARD"
FBP_EFFECT_THICKNESS = "THICKNESS"
FBP_EFFECT_INFINITE_ROTATION = "INFINITE_ROTATION"
FBP_EFFECT_FELT_FUZZ = "FELT_FUZZ"

FBP_EFFECT_UV_DISTORTION = "UV_DISTORTION"
FBP_EFFECT_PIXELATE = "PIXELATE"
FBP_EFFECT_SOLID_MASK = "SOLID_MASK"
FBP_EFFECT_HUE_SATURATION = "HUE_SATURATION"
FBP_EFFECT_BRIGHTNESS_CONTRAST = "BRIGHTNESS_CONTRAST"
FBP_EFFECT_INVERT = "INVERT"
FBP_EFFECT_THRESHOLD = "THRESHOLD"
FBP_EFFECT_COLOR_ISOLATE = "COLOR_ISOLATE"
FBP_EFFECT_DUOTONE = "DUOTONE"
FBP_EFFECT_GRAIN = "GRAIN"
FBP_EFFECT_PAPER_FIBERS = "PAPER_FIBERS"
FBP_EFFECT_GRADIENT_LIGHT = "GRADIENT_LIGHT"
FBP_EFFECT_GOBO_SHADOWS = "GOBO_SHADOWS"
FBP_EFFECT_CRT_SCANLINES = "CRT_SCANLINES"
FBP_EFFECT_VIGNETTE = "VIGNETTE"
FBP_EFFECT_POSTERIZE = "POSTERIZE"
FBP_EFFECT_CROP = "CROP"
FBP_EFFECT_EXTEND = "EXTEND"
FBP_EFFECT_DIGITAL_NOISE = "DIGITAL_NOISE"
FBP_EFFECT_CHROMA_KEY = "CHROMA_KEY"
FBP_EFFECT_HALFTONE = "HALFTONE"
FBP_EFFECT_DOT_MATRIX = "DOT_MATRIX"
FBP_EFFECT_ASCII_MATRIX = "ASCII_MATRIX"
FBP_EFFECT_TEXT_MATRIX = "TEXT_MATRIX"

_FBP_CUSTOM_EFFECT_MISS_CACHE_SECONDS = 2.0
_FBP_CUSTOM_EFFECT_MISS_CACHE = globals().get("_FBP_CUSTOM_EFFECT_MISS_CACHE", {})
if not isinstance(_FBP_CUSTOM_EFFECT_MISS_CACHE, dict):
    _FBP_CUSTOM_EFFECT_MISS_CACHE = {}

FBP_EFFECT_REGISTRY = {
    FBP_EFFECT_CROP: {
        "label": "Crop", "icon": "MOD_BOOLEAN", "kind": "BASE",
        "enabled_key": "fbp_effect_crop",
        "property_map": {
            "fbp_crop_top": "Top", "fbp_crop_left": "Left",
            "fbp_crop_right": "Right", "fbp_crop_bottom": "Bottom",
        },
    },
    FBP_EFFECT_EXTEND: {
        "label": "Extend", "icon": "FULLSCREEN_ENTER", "kind": "BASE",
        "enabled_key": "fbp_effect_extend",
        "property_map": {
            "fbp_extend_mode": "Extend Mode", "fbp_extend_top": "Top",
            "fbp_extend_left": "Left", "fbp_extend_right": "Right",
            "fbp_extend_bottom": "Bottom",
        },
    },
    FBP_EFFECT_MESH_WIGGLE: {
        "label": "Wiggle", "icon": "MOD_NOISE", "kind": "GEOMETRY",
        "source_names": ("FBP_Wiggle",),
        "canonical_name": "FBP_GN_Wiggle_450", "modifier_name": "FBP • Wiggle",
        "asset_id": "frame_by_plane.wiggle.450", "enabled_key": "fbp_effect_mesh_wiggle",
        "alpha_aware": False,
        "property_map": {
            "fbp_mesh_wiggle_subdivisions": "Subdivision", "fbp_mesh_wiggle_shade_smooth": "Shade Smooth",
            "fbp_mesh_wiggle_hold": "Stepped", "fbp_mesh_wiggle_strength": "Strength",
            "fbp_mesh_wiggle_speed": "Speed", "fbp_mesh_wiggle_w": "W",
            "fbp_mesh_wiggle_noise_scale": "Noise Scale", "fbp_mesh_wiggle_detail": "Noise Detail",
        },
        "supports_seed": True,
    },
    FBP_EFFECT_STOP_MOTION_CRUMPLE: {
        "label": "Stop Motion Crumple", "icon": "MOD_DISPLACE", "kind": "GEOMETRY",
        "source_names": ("FBP_StopMotion_Crumple",), "canonical_name": "FBP_GN_StopMotion_Crumple_450",
        "modifier_name": "FBP • Stop Motion Crumple", "asset_id": "frame_by_plane.stop_motion_crumple.450",
        "enabled_key": "fbp_effect_stop_motion_crumple", "alpha_aware": False,
        "property_map": {"fbp_stop_motion_resolution": "Resolution", "fbp_stop_motion_strength": "Strength", "fbp_stop_motion_step_frames": "Step Frames"},
    },
    FBP_EFFECT_WIND_BENDER: {
        "label": "Wind Bender", "icon": "FORCE_WIND", "kind": "GEOMETRY",
        "source_names": (), "canonical_name": "FBP_GN_Wind_Bender_483",
        "modifier_name": "FBP • Wind Bender", "asset_id": "frame_by_plane.wind_bender.483",
        "enabled_key": "fbp_effect_wind_bender", "alpha_aware": False,
        "property_map": {
            "fbp_wind_subdivision": "Subdivision", "fbp_wind_bend_amount": "Bend Amount",
            "fbp_wind_speed": "Wind Speed", "fbp_wind_stepped": "Stepped",
            "fbp_wind_pin_edge": "Pin Edge", "fbp_wind_motion_mode": "Motion Mode",
            "fbp_wind_wave_count": "Wave Count", "fbp_wind_wave_amplitude": "Wave Amplitude",
            "fbp_wind_wave_speed": "Wave Speed", "fbp_wind_phase": "Phase",
            "fbp_wind_turbulence": "Turbulence", "fbp_wind_reverse": "Reverse Direction",
            "fbp_wind_falloff": "Falloff", "fbp_wind_noise_scale": "Noise Scale",
            "fbp_wind_gust_strength": "Gust Strength",
            "fbp_wind_direction_space": "Direction Space",
            "fbp_wind_direction": "Wind Direction",
            "fbp_wind_preview_falloff": "Preview Falloff",
        },
        "builtin": True,
    },
    FBP_EFFECT_MESH_RIPPLE: {
        "label": "Mesh Ripple", "icon": "MOD_WAVE", "kind": "GEOMETRY",
        "source_names": (), "canonical_name": "FBP_GN_Mesh_Ripple_491",
        "modifier_name": "FBP • Mesh Ripple", "asset_id": "frame_by_plane.mesh_ripple.491",
        "enabled_key": "fbp_effect_mesh_ripple", "alpha_aware": False, "builtin": True,
        "quality_profile": "SUBDIVISION",
        "quality_contracts": ({
            "socket": "Subdivision",
            "viewport_property": "fbp_mesh_ripple_viewport_subdivision",
            "playback_property": "fbp_mesh_ripple_playback_subdivision",
            "render_property": "fbp_mesh_ripple_render_subdivision",
            "minimum": 0, "playback_mode": "REPLACE",
        },),
        "property_map": {
            "fbp_mesh_ripple_viewport_subdivision": "Subdivision",
            "fbp_mesh_ripple_direction": "Direction",
            "fbp_mesh_ripple_amplitude": "Amplitude",
            "fbp_mesh_ripple_frequency": "Frequency",
            "fbp_mesh_ripple_speed": "Speed",
            "fbp_mesh_ripple_phase": "Phase",
            "fbp_mesh_ripple_stepped": "Stepped",
            "fbp_mesh_ripple_pin_borders": "Pin Borders",
            "fbp_mesh_ripple_border_falloff": "Border Falloff",
        },
        "extra_properties": ("fbp_mesh_ripple_playback_subdivision", "fbp_mesh_ripple_render_subdivision"),
    },
    FBP_EFFECT_PAPER_CURL: {
        "label": "Paper Curl", "icon": "MOD_SIMPLEDEFORM", "kind": "GEOMETRY",
        "source_names": (), "canonical_name": "FBP_GN_Paper_Curl_492",
        "modifier_name": "FBP • Paper Curl", "asset_id": "frame_by_plane.paper_curl.492",
        "enabled_key": "fbp_effect_paper_curl", "alpha_aware": False, "builtin": True,
        "quality_profile": "SUBDIVISION",
        "quality_contracts": ({
            "socket": "Subdivision",
            "viewport_property": "fbp_paper_curl_viewport_subdivision",
            "playback_property": "fbp_paper_curl_playback_subdivision",
            "render_property": "fbp_paper_curl_render_subdivision",
            "minimum": 0, "playback_mode": "REPLACE",
        },),
        "property_map": {
            "fbp_paper_curl_viewport_subdivision": "Subdivision",
            "fbp_paper_curl_edge": "Edge",
            "fbp_paper_curl_progress": "Progress",
            "fbp_paper_curl_angle": "Curl Angle",
            "fbp_paper_curl_radius": "Curl Radius",
            "fbp_paper_curl_width": "Curl Width",
            "fbp_paper_curl_lift": "Lift",
            "fbp_paper_curl_reverse": "Reverse",
        },
        "extra_properties": (
            "fbp_paper_curl_playback_subdivision",
            "fbp_paper_curl_render_subdivision",
        ),
    },
    FBP_EFFECT_CUTOUT_OUTLINE: {
        "label": "Cutout Outline", "icon": "MOD_SKIN", "kind": "GEOMETRY",
        "source_names": (), "canonical_name": "FBP_GN_Cutout_Outline_494",
        "modifier_name": "FBP • Cutout Outline", "asset_id": "frame_by_plane.cutout_outline.494",
        "enabled_key": "fbp_effect_cutout_outline", "alpha_aware": True,
        "private_group": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE"),
        "requires_alpha_geometry_contract": True,
        "required_input_sockets": ("Outline Material",),
        "quality_profile": "ALPHA_DETAIL",
        "quality_contracts": ({
            "socket": "Alpha Resolution",
            "viewport_property": "fbp_cutout_outline_viewport_resolution",
            "playback_property": "fbp_cutout_outline_playback_resolution",
            "render_property": "fbp_cutout_outline_render_resolution",
            "minimum": 0, "playback_mode": "REPLACE",
        },),
        "property_map": {
            "fbp_cutout_outline_viewport_resolution": "Alpha Resolution",
            "fbp_cutout_outline_alpha_threshold": "Alpha Threshold",
            "fbp_cutout_outline_width": "Outline Width",
            "fbp_cutout_outline_offset": "Offset",
        },
        "extra_properties": (
            "fbp_cutout_outline_playback_resolution",
            "fbp_cutout_outline_render_resolution",
            "fbp_cutout_outline_color",
        ),
    },
    FBP_EFFECT_EXTRUDED_CUTOUT: {
        "label": "Extruded Cutout", "icon": "MOD_SOLIDIFY", "kind": "GEOMETRY",
        "source_names": (), "canonical_name": "FBP_GN_Extruded_Cutout_495",
        "modifier_name": "FBP • Extruded Cutout", "asset_id": "frame_by_plane.extruded_cutout.495",
        "enabled_key": "fbp_effect_extruded_cutout", "alpha_aware": True,
        "private_group": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE"),
        "requires_alpha_geometry_contract": True,
        "required_input_sockets": ("Side Material",),
        "quality_profile": "ALPHA_DETAIL",
        "quality_contracts": ({
            "socket": "Alpha Resolution",
            "viewport_property": "fbp_extruded_cutout_viewport_resolution",
            "playback_property": "fbp_extruded_cutout_playback_resolution",
            "render_property": "fbp_extruded_cutout_render_resolution",
            "minimum": 0, "playback_mode": "REPLACE",
        },),
        "property_map": {
            "fbp_extruded_cutout_viewport_resolution": "Alpha Resolution",
            "fbp_extruded_cutout_alpha_threshold": "Alpha Threshold",
            "fbp_extruded_cutout_thickness": "Thickness",
            "fbp_extruded_cutout_direction": "Direction",
        },
        "extra_properties": (
            "fbp_extruded_cutout_playback_resolution",
            "fbp_extruded_cutout_render_resolution",
            "fbp_extruded_cutout_side_material",
            "fbp_extruded_cutout_side_color",
        ),
    },
    FBP_EFFECT_CAMERA_SCALE_LOCK: {
        "label": "Camera Scale Lock", "icon": "CAMERA_DATA", "kind": "GEOMETRY",
        "source_names": (), "canonical_name": "FBP_GN_Camera_Scale_Lock_493",
        "modifier_name": "FBP • Camera Scale Lock", "asset_id": "frame_by_plane.camera_scale_lock.493",
        "enabled_key": "fbp_effect_camera_scale_lock", "alpha_aware": False, "builtin": True,
        "camera_aware": True,
        "camera_contract": {
            "object_socket": "Camera",
            "lens_socket": "Camera Lens",
            "sensor_width_socket": "Camera Sensor Width",
            "ortho_scale_socket": "Camera Ortho Scale",
            "perspective_socket": "Perspective",
            "shift_x_socket": "Camera Shift X",
            "shift_y_socket": "Camera Shift Y",
        },
        "property_map": {
            "fbp_camera_scale_lock_reference_distance": "Reference Distance",
            "fbp_camera_scale_lock_reference_lens": "Reference Lens",
            "fbp_camera_scale_lock_reference_sensor_width": "Reference Sensor Width",
            "fbp_camera_scale_lock_influence": "Influence",
        },
    },
    FBP_EFFECT_CAMERA_BILLBOARD: {
        "label": "Camera Billboard", "icon": "CON_CAMERASOLVER", "kind": "GEOMETRY",
        "source_names": (), "canonical_name": "FBP_GN_Camera_Billboard_497",
        "modifier_name": "FBP • Camera Billboard", "asset_id": "frame_by_plane.camera_billboard.497",
        "enabled_key": "fbp_effect_camera_billboard", "alpha_aware": False, "builtin": True,
        "camera_aware": True,
        "camera_contract": {"object_socket": "Camera", "space_vectors": True},
        "property_map": {
            "fbp_camera_billboard_mode": "Facing Mode",
            "fbp_camera_billboard_flip": "Flip",
            "fbp_camera_billboard_offset": "Offset",
        },
    },
    FBP_EFFECT_THICKNESS: {
        "label": "Thickness", "icon": "MOD_SOLIDIFY", "kind": "GEOMETRY",
        "source_names": ("FBP_Thickness",), "canonical_name": "FBP_GN_Thickness_450",
        "modifier_name": "FBP • Thickness", "asset_id": "frame_by_plane.thickness.450",
        "enabled_key": "fbp_effect_thickness", "alpha_aware": True,
        "property_map": {
            "fbp_thickness_amount": "Thickness", "fbp_thickness_alpha_threshold": "Alpha Threshold",
            "fbp_thickness_alpha_resolution": "Alpha Resolution",
        },
        "extra_properties": ("fbp_thickness_side_material", "fbp_thickness_side_color"),
    },
    FBP_EFFECT_INFINITE_ROTATION: {
        "label": "Infinite Rotation", "icon": "DRIVER_ROTATIONAL_DIFFERENCE", "kind": "GEOMETRY",
        "source_names": ("FBP_Infinite_Rotation",), "canonical_name": "FBP_GN_Infinite_Rotation_450",
        "modifier_name": "FBP • Infinite Rotation", "asset_id": "frame_by_plane.infinite_rotation.450",
        "enabled_key": "fbp_effect_infinite_rotation", "alpha_aware": False,
        "property_map": {
            "fbp_infinite_rotation_speed": "Speed", "fbp_infinite_rotation_direction": "Direction",
            "fbp_infinite_rotation_stepped": "Stepped", "fbp_infinite_rotation_offset": "Offset",
        },
    },
    FBP_EFFECT_FELT_FUZZ: {
        "label": "Felt Fuzz", "icon": "MOD_NOISE", "kind": "GEOMETRY",
        "source_names": ("FBP_Felt_Fuzz",), "canonical_name": "FBP_GN_Felt_Fuzz_453",
        "modifier_name": "FBP • Felt Fuzz", "asset_id": "frame_by_plane.felt_fuzz.453",
        "enabled_key": "fbp_effect_felt_fuzz", "alpha_aware": True,
        "property_map": {
            "fbp_felt_render_density": "Render Density", "fbp_felt_viewport_percentage": "Viewport %",
            "fbp_felt_fuzz_length": "Fuzz Length", "fbp_felt_subdivisions": "Subdivisions",
            "fbp_felt_fuzz_radius": "Fuzz Radius", "fbp_felt_curl_amount": "Curl Amount",
            "fbp_felt_seed": "Seed", "fbp_felt_alpha_threshold": "Alpha Threshold",
            "fbp_felt_alpha_resolution": "Alpha Resolution",
        },
        "evolve_property": "fbp_felt_seed", "evolve_amount": 1.0,
        "evolve_mode": "SEED_STEP", "supports_seed": False,
    },
    FBP_EFFECT_UV_DISTORTION: {
        "label": "Turbulence", "icon": "FORCE_TURBULENCE", "kind": "SHADER", "stage": "UV",
        "source_names": ("FBP_Turbolence",), "canonical_name": "FBP_SH_Turbolence_445",
        "asset_id": "frame_by_plane.shader.turbolence.445", "enabled_key": "fbp_effect_uv_distortion",
        "input_socket": "Vector", "output_socket": "Vector Out",
        "property_map": {"fbp_uv_distortion_scale": "Noise Scale", "fbp_uv_distortion_amount": "Distortion Amount"},
        "evolve_property": "fbp_uv_distortion_amount", "evolve_amount": 0.05, "supports_seed": True,
    },
    FBP_EFFECT_PIXELATE: {
        "label": "Pixelate", "icon": "ALIASED", "kind": "SHADER", "stage": "UV",
        "source_names": (), "canonical_name": "FBP_SH_Pixelate_461",
        "asset_id": "frame_by_plane.shader.pixelate.461", "enabled_key": "fbp_effect_pixelate",
        "input_socket": "Vector", "output_socket": "Vector Out", "property_map": {"fbp_pixelate_resolution": "Resolution"},
        "extra_properties": ("fbp_pixelate_square_pixels",),
        "evolve_property": "fbp_pixelate_resolution", "evolve_amount": 32.0, "supports_seed": True,
        "builtin": True,
    },
    FBP_EFFECT_SOLID_MASK: {
        "label": "Tint", "icon": "IMAGE", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Tint",), "canonical_name": "FBP_SH_Tint_450",
        "asset_id": "frame_by_plane.shader.tint.450", "enabled_key": "fbp_effect_solid_mask",
        "input_socket": "Color In", "output_socket": "Color Out",
        "property_map": {"fbp_solid_mask_color": "Mask Color", "fbp_solid_mask_factor": "Mask Factor"},
        "evolve_property": "fbp_solid_mask_factor", "evolve_amount": 1.0, "supports_seed": True,
    },
    FBP_EFFECT_HUE_SATURATION: {
        "label": "Hue / Saturation", "icon": "COLOR", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Hue_Saturation",), "canonical_name": "FBP_SH_Hue_Saturation_450",
        "asset_id": "frame_by_plane.shader.hue_saturation.450", "enabled_key": "fbp_effect_hue_saturation",
        "input_socket": "Color In", "output_socket": "Color Out",
        "property_map": {"fbp_hue_saturation_hue": "Hue", "fbp_hue_saturation_saturation": "Saturation", "fbp_hue_saturation_value": "Value"},
        "evolve_property": "fbp_hue_saturation_hue", "evolve_amount": 0.5, "supports_seed": True,
    },
    FBP_EFFECT_BRIGHTNESS_CONTRAST: {
        "label": "Brightness / Contrast", "icon": "IMAGE_ZDEPTH", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Brightness_Contrast",), "canonical_name": "FBP_SH_Brightness_Contrast_450",
        "asset_id": "frame_by_plane.shader.brightness_contrast.450", "enabled_key": "fbp_effect_brightness_contrast",
        "input_socket": "Color In", "output_socket": "Color Out",
        "property_map": {"fbp_brightness_contrast_brightness": "Brightness", "fbp_brightness_contrast_contrast": "Contrast"},
    },
    FBP_EFFECT_INVERT: {
        "label": "Invert", "icon": "IMAGE_ALPHA", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Invert",), "canonical_name": "FBP_SH_Invert_450",
        "asset_id": "frame_by_plane.shader.invert.450", "enabled_key": "fbp_effect_invert",
        "input_socket": "Color In", "output_socket": "Color Out",
        "property_map": {"fbp_invert_factor": "Factor"},
    },
    FBP_EFFECT_THRESHOLD: {
        "label": "Threshold", "icon": "MOD_MASK", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Threshold",), "canonical_name": "FBP_SH_Threshold_450",
        "asset_id": "frame_by_plane.shader.threshold.450", "enabled_key": "fbp_effect_threshold",
        "input_socket": "Color In", "output_socket": "Color Out",
        "property_map": {"fbp_threshold_value": "Threshold"},
    },
    FBP_EFFECT_COLOR_ISOLATE: {
        "label": "Color Isolate", "icon": "EYEDROPPER", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Color_Isolate",), "canonical_name": "FBP_SH_Color_Isolate_445",
        "asset_id": "frame_by_plane.shader.color_isolate.445", "enabled_key": "fbp_effect_color_isolate",
        "input_socket": "Color In", "output_socket": "Color Out",
        "property_map": {"fbp_color_isolate_target": "Target Color", "fbp_color_isolate_tolerance": "Tolerance", "fbp_color_isolate_falloff": "Falloff"},
    },
    FBP_EFFECT_DUOTONE: {
        "label": "Duotone", "icon": "MOD_TINT", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Duotone",), "canonical_name": "FBP_SH_Duotone_445",
        "asset_id": "frame_by_plane.shader.duotone.445", "enabled_key": "fbp_effect_duotone",
        "input_socket": "Color In", "output_socket": "Color Out",
        "property_map": {"fbp_duotone_shadows": "Shadows Tone", "fbp_duotone_highlights": "Highlights Tone"},
    },
    FBP_EFFECT_GRAIN: {
        "label": "Film Grain", "icon": "RENDER_STILL", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Film_Grain",), "canonical_name": "FBP_SH_Film_Grain_450",
        "asset_id": "frame_by_plane.shader.film_grain.450", "enabled_key": "fbp_effect_grain",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {"fbp_grain_strength": "Intensity", "fbp_grain_scale": "Grain Scale", "fbp_grain_seed": "Animate (W)"},
        "evolve_property": "fbp_grain_seed", "evolve_amount": 1.0, "supports_seed": False,
    },
    FBP_EFFECT_PAPER_FIBERS: {
        "label": "Paper Fibers", "icon": "TEXTURE", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Paper_Fibers",), "canonical_name": "FBP_SH_Paper_Fibers_450",
        "asset_id": "frame_by_plane.shader.paper_fibers.450", "enabled_key": "fbp_effect_paper_fibers",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {"fbp_paper_fiber_scale": "Fiber Scale", "fbp_paper_fiber_intensity": "Intensity", "fbp_paper_fiber_phase": "Animate (W)"},
        "evolve_property": "fbp_paper_fiber_phase", "evolve_amount": 0.2, "supports_seed": True,
    },
    FBP_EFFECT_GRADIENT_LIGHT: {
        "label": "2D Gradient Light", "icon": "LIGHT", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_2D_Gradient_Light",), "canonical_name": "FBP_SH_2D_Gradient_Light_445",
        "asset_id": "frame_by_plane.shader.gradient_light.445", "enabled_key": "fbp_effect_gradient_light",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {"fbp_gradient_light_angle": "Light Angle", "fbp_gradient_shadow_position": "Shadow Position", "fbp_gradient_softness": "Softness", "fbp_gradient_shadow_color": "Shadow Color"},
    },
    FBP_EFFECT_GOBO_SHADOWS: {
        "label": "Gobo Shadows", "icon": "LIGHT_SPOT", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Gobo_Shadows",), "canonical_name": "FBP_SH_Gobo_Shadows_445",
        "asset_id": "frame_by_plane.shader.gobo_shadows.445", "enabled_key": "fbp_effect_gobo_shadows",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {"fbp_gobo_pattern_scale": "Pattern Scale", "fbp_gobo_rotation": "Rotation Angle", "fbp_gobo_sharpness": "Sharpness"},
    },
    FBP_EFFECT_CRT_SCANLINES: {
        "label": "CRT Scanlines", "icon": "NODE_TEXTURE", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_CRT_Scanlines",), "canonical_name": "FBP_SH_CRT_Scanlines_445",
        "asset_id": "frame_by_plane.shader.crt_scanlines.445", "enabled_key": "fbp_effect_crt_scanlines",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {"fbp_crt_line_count": "Line Count", "fbp_crt_opacity": "Opacity"},
    },
    FBP_EFFECT_VIGNETTE: {
        "label": "Vignette", "icon": "MESH_CIRCLE", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Vignette",), "canonical_name": "FBP_SH_Vignette_450",
        "asset_id": "frame_by_plane.shader.vignette.450", "enabled_key": "fbp_effect_vignette",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {"fbp_vignette_radius": "Radius", "fbp_vignette_smoothness": "Smoothness", "fbp_vignette_strength": "Strength"},
    },
    FBP_EFFECT_POSTERIZE: {
        "label": "Posterize", "icon": "MOD_TINT", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Posterize",), "canonical_name": "FBP_SH_Posterize_445",
        "asset_id": "frame_by_plane.shader.posterize.445", "enabled_key": "fbp_effect_posterize",
        "input_socket": "Color In", "output_socket": "Color Out", "property_map": {"fbp_posterize_steps": "Color Steps"},
        "evolve_property": "fbp_posterize_steps", "evolve_amount": 8.0, "supports_seed": True,
    },
    FBP_EFFECT_DIGITAL_NOISE: {
        "label": "Digital Noise", "icon": "RNDCURVE", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Digital_Noise_466",
        "asset_id": "frame_by_plane.shader.digital_noise.466", "enabled_key": "fbp_effect_digital_noise",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {
            "fbp_digital_noise_luma": "Luminance Noise",
            "fbp_digital_noise_chroma": "Chroma Noise",
            "fbp_digital_noise_scale": "Noise Scale",
            "fbp_digital_noise_shadow_bias": "Shadow Bias",
            "fbp_digital_noise_seed": "Animate (W)",
        },
        "evolve_property": "fbp_digital_noise_seed", "evolve_amount": 1.0, "supports_seed": True,
        "builtin": True,
    },
    FBP_EFFECT_CHROMA_KEY: {
        "label": "Chroma Key", "icon": "EYEDROPPER", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Chroma_Key_480",
        "asset_id": "frame_by_plane.shader.chroma_key.480", "enabled_key": "fbp_effect_chroma_key",
        "input_socket": "Color In", "output_socket": "Color Out",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "property_map": {
            "fbp_chroma_key_color": "Key Color",
            "fbp_chroma_key_tolerance": "Tolerance",
            "fbp_chroma_key_softness": "Softness",
            "fbp_chroma_key_despill": "Despill",
            "fbp_chroma_key_invert": "Invert",
        },
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte"), ("DISTANCE", "Distance")),
        "debug_socket": "Debug Mode",
        "builtin": True,
    },
    FBP_EFFECT_HALFTONE: {
        "label": "Halftone", "icon": "MESH_CIRCLE", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Halftone_480",
        "asset_id": "frame_by_plane.shader.halftone.480", "enabled_key": "fbp_effect_halftone",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {
            "fbp_halftone_scale": "Cell Scale", "fbp_halftone_dot_size": "Dot Size",
            "fbp_halftone_rotation": "Rotation", "fbp_halftone_contrast": "Contrast",
            "fbp_halftone_invert": "Invert",
            "fbp_halftone_shape": "Shape",
            "fbp_halftone_use_source_color": "Use Source Color",
            "fbp_halftone_foreground": "Foreground",
            "fbp_halftone_background": "Background",
            "fbp_halftone_transparent_background": "Transparent Background",
        },
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "debug_modes": (("FINAL", "Final"), ("LUMINANCE", "Luminance"), ("MASK", "Mask")),
        "debug_socket": "Debug Mode",
        "builtin": True,
    },
    FBP_EFFECT_DOT_MATRIX: {
        "label": "Dot Matrix", "icon": "SNAP_GRID", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Dot_Matrix_483",
        "asset_id": "frame_by_plane.shader.dot_matrix.483", "enabled_key": "fbp_effect_dot_matrix",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "property_map": {
            "fbp_dot_matrix_scale": "Cell Scale", "fbp_dot_matrix_dot_size": "Dot Size",
            "fbp_dot_matrix_spacing": "Spacing", "fbp_dot_matrix_contrast": "Contrast",
            "fbp_dot_matrix_response": "Brightness Response",
            "fbp_dot_matrix_invert": "Invert", "fbp_dot_matrix_random_size": "Random Size",
            "fbp_dot_matrix_random_brightness": "Random Brightness", "fbp_dot_matrix_seed": "Seed",
            "fbp_dot_matrix_glow": "Glow", "fbp_dot_matrix_use_source_color": "Use Source Color",
            "fbp_dot_matrix_foreground": "Foreground", "fbp_dot_matrix_background": "Background",
            "fbp_dot_matrix_transparent_background": "Transparent Background",
            "fbp_dot_matrix_shape": "Shape",
            "fbp_dot_matrix_min_size": "Minimum Size",
            "fbp_dot_matrix_max_size": "Maximum Size",
            "fbp_dot_matrix_dead_pixels": "Dead Pixels",
            "fbp_dot_matrix_flicker": "Flicker",
        },
        "evolve_property": "fbp_dot_matrix_seed", "evolve_amount": 1.0,
        "evolve_mode": "SEED_STEP", "supports_seed": True,
        "debug_modes": (("FINAL", "Final"), ("LUMINANCE", "Luminance"), ("MASK", "Mask")),
        "debug_socket": "Debug Mode",
        "private_group": True, "image_aware": True, "builtin": True,
    },
    FBP_EFFECT_ASCII_MATRIX: {
        "label": "Textellation", "icon": "FONT_DATA", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Textellation_485",
        "asset_id": "frame_by_plane.shader.textellation.485", "enabled_key": "fbp_effect_ascii_matrix",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "property_map": {
            "fbp_ascii_scale": "Cell Scale", "fbp_ascii_contrast": "Contrast",
            "fbp_ascii_invert": "Invert", "fbp_ascii_colorize": "Use Source Color",
            "fbp_ascii_foreground": "Foreground", "fbp_ascii_background": "Background",
            "fbp_ascii_transparent_background": "Transparent Background",
            "fbp_ascii_variation": "Variation", "fbp_ascii_random_seed": "Seed",
            "fbp_ascii_edge_boost": "Edge Boost",
            "fbp_ascii_dither": "Dither",
        },
        "extra_properties": ("fbp_ascii_charset", "fbp_ascii_character_count"),
        "evolve_property": "fbp_ascii_random_seed", "evolve_amount": 1.0,
        "evolve_mode": "SEED_STEP", "supports_seed": True,
        "debug_modes": (("FINAL", "Final"), ("LUMINANCE", "Luminance"), ("GLYPH", "Glyph Index")),
        "debug_socket": "Debug Mode",
        "private_group": True, "image_aware": True, "builtin": True,
    },
    FBP_EFFECT_TEXT_MATRIX: {
        "label": "Text Matrix", "icon": "OUTLINER_OB_FONT", "kind": "GEOMETRY",
        "canonical_name": "FBP_GN_Text_Matrix_487", "modifier_name": "FBP • Text Matrix",
        "asset_id": "frame_by_plane.text_matrix.487", "enabled_key": "fbp_effect_text_matrix",
        "property_map": {
            "fbp_text_matrix_viewport_columns": "Columns",
            "fbp_text_matrix_viewport_rows": "Rows",
            "fbp_text_matrix_character_count": "Character Count",
            "fbp_text_matrix_character_aspect": "Character Aspect",
            "fbp_text_matrix_glyph_scale": "Glyph Scale",
            "fbp_text_matrix_contrast": "Contrast",
            "fbp_text_matrix_invert": "Invert",
            "fbp_text_matrix_variation": "Variation",
            "fbp_text_matrix_seed": "Seed",
            "fbp_text_matrix_alpha_threshold": "Alpha Threshold",
            "fbp_text_matrix_use_source_color": "Use Source Color",
            "fbp_text_matrix_text_color": "Text Color",
            "fbp_text_matrix_transparent_background": "Transparent Background",
            "fbp_text_matrix_realize": "Realize Text",
        },
        "extra_properties": (
            "fbp_text_matrix_charset", "fbp_text_matrix_custom_charset",
            "fbp_text_matrix_font", "fbp_text_matrix_background_color",
            "fbp_text_matrix_render_columns", "fbp_text_matrix_render_rows", "fbp_text_matrix_quality",
            "fbp_text_matrix_auto_playback_limit", "fbp_text_matrix_playback_columns",
            "fbp_text_matrix_playback_rows",
        ),
        "quality_contracts": (
            {"socket": "Columns", "viewport_property": "fbp_text_matrix_viewport_columns",
             "playback_property": "fbp_text_matrix_playback_columns", "render_property": "fbp_text_matrix_render_columns",
             "minimum": 2, "playback_mode": "LIMIT"},
            {"socket": "Rows", "viewport_property": "fbp_text_matrix_viewport_rows",
             "playback_property": "fbp_text_matrix_playback_rows", "render_property": "fbp_text_matrix_render_rows",
             "minimum": 0, "zero_is_auto": True, "playback_mode": "LIMIT"},
        ),
        "evolve_property": "fbp_text_matrix_seed", "evolve_amount": 1.0,
        "evolve_mode": "SEED_STEP", "supports_seed": True,
        "private_group": True, "image_aware": True, "alpha_aware": False,
        "supports": ("IMAGE", "SEQUENCE"), "builtin": True,
    },
}


FBP_EFFECT_METADATA = {
    FBP_EFFECT_CROP: ("BASE", "LIGHT", "Crop the visible borders without changing the rig transform. The operation is non-destructive and can be animated."),
    FBP_EFFECT_EXTEND: ("BASE", "LIGHT", "Extend the plane borders while preserving the central image. Edge Pixel clamps the border; Repeat Texture continues the texture."),
    FBP_EFFECT_SOLID_MASK: ("BASE", "LIGHT", "Apply a color tint to the final plane output. Useful for recoloring images, solid planes and gradients."),
    FBP_EFFECT_HUE_SATURATION: ("BASE", "LIGHT", "Adjust hue, saturation and value on the final color output."),
    FBP_EFFECT_BRIGHTNESS_CONTRAST: ("BASE", "LIGHT", "Adjust brightness and contrast without rebuilding the source material."),
    FBP_EFFECT_INVERT: ("BASE", "LIGHT", "Invert the final color output. Factor allows partial inversion."),
    FBP_EFFECT_THRESHOLD: ("BASE", "LIGHT", "Convert luminance into a hard black-and-white threshold."),
    FBP_EFFECT_COLOR_ISOLATE: ("BASE", "LIGHT", "Keep a selected color range and suppress the remaining colors."),
    FBP_EFFECT_DUOTONE: ("BASE", "LIGHT", "Map shadows and highlights to two editable colors."),
    FBP_EFFECT_CHROMA_KEY: ("BASE", "MEDIUM", "Remove a selected color and generate transparency. Softness cleans edges; Despill reduces the key color around the subject."),
    FBP_EFFECT_UV_DISTORTION: ("2D", "MEDIUM", "Distort UV coordinates with procedural turbulence. Animated or high-frequency distortion can cost viewport performance."),
    FBP_EFFECT_PIXELATE: ("2D", "LIGHT", "Reduce detail into adjustable pixel blocks. Square Pixels compensates for the plane aspect ratio and is enabled by default."),
    FBP_EFFECT_GRAIN: ("2D", "LIGHT", "Add soft monochromatic film-like grain. Use Digital Noise for colored high-ISO sensor noise."),
    FBP_EFFECT_DIGITAL_NOISE: ("2D", "MEDIUM", "Simulate high-ISO digital sensor noise with separate luminance and chromatic components. Strong animated chroma noise may be expensive."),
    FBP_EFFECT_HALFTONE: ("2D", "MEDIUM", "Convert luminance into a printed-dot pattern. Small cells can increase shader cost and cause viewport aliasing."),
    FBP_EFFECT_DOT_MATRIX: ("2D", "MEDIUM", "Rebuild the source image as cell-centered dots whose radius and brightness follow image luminance. Brightness Response reshapes the luminance-to-size curve; optional randomness only modulates the image-driven result."),
    FBP_EFFECT_ASCII_MATRIX: ("2D", "HEAVY", "Replace the animated FBP image or sequence with density-sorted atlas glyphs. Partial alpha is read as lighter luminance, total transparency is removed, and source-pixel color is preserved by default."),
    FBP_EFFECT_TEXT_MATRIX: ("3D", "VERY_HEAVY", "Generate real vector text from the animated source. Geometry Nodes maps alpha-aware luminance to density-sorted glyphs and can preserve one sampled source color per cell."),
    FBP_EFFECT_PAPER_FIBERS: ("2D", "MEDIUM", "Overlay procedural paper fibers on the final color."),
    FBP_EFFECT_GRADIENT_LIGHT: ("2D", "LIGHT", "Add a directional 2D light and shadow gradient."),
    FBP_EFFECT_GOBO_SHADOWS: ("2D", "MEDIUM", "Project a procedural gobo-like shadow pattern across the plane."),
    FBP_EFFECT_CRT_SCANLINES: ("2D", "LIGHT", "Add CRT-style horizontal scanlines."),
    FBP_EFFECT_VIGNETTE: ("2D", "LIGHT", "Darken the image edges with an adjustable vignette."),
    FBP_EFFECT_POSTERIZE: ("2D", "LIGHT", "Reduce the number of color levels for a graphic posterized look."),
    FBP_EFFECT_MESH_WIGGLE: ("3D", "MEDIUM", "Deform the plane with animated procedural noise. High subdivision values may slow playback."),
    FBP_EFFECT_STOP_MOTION_CRUMPLE: ("3D", "HEAVY", "Create stepped, stop-motion-style surface crumpling. Resolution has a strong impact on viewport performance."),
    FBP_EFFECT_WIND_BENDER: ("3D", "MEDIUM", "Bend the plane as if affected by wind. Choose the pinned edge, Local or World direction, global sway or flowing sine waves, and preview the falloff before animating flags, paper and hanging signs."),
    FBP_EFFECT_MESH_RIPPLE: ("3D", "MEDIUM", "Create directional or radial waves with independent viewport, playback and render subdivision quality."),
    FBP_EFFECT_PAPER_CURL: ("3D", "MEDIUM", "Curl a selected plane edge with animatable progress, radius, angle and independent viewport, playback and render subdivision quality."),
    FBP_EFFECT_CUTOUT_OUTLINE: ("3D", "HEAVY", "Generate a material outline from the animated image alpha while preserving the original plane geometry. Alpha detail has separate viewport, playback and render quality."),
    FBP_EFFECT_EXTRUDED_CUTOUT: ("3D", "HEAVY", "Extrude the animated alpha silhouette into real side and back geometry while preserving the original front plane."),
    FBP_EFFECT_CAMERA_SCALE_LOCK: ("3D", "LIGHT", "Keep the plane at a stable apparent size while camera-space depth, focal length or sensor width changes."),
    FBP_EFFECT_CAMERA_BILLBOARD: ("3D", "LIGHT", "Rotate plane geometry toward the active camera without changing the rig transform or its keyframes."),
    FBP_EFFECT_THICKNESS: ("3D", "HEAVY", "Extrude the alpha silhouette into a thick object. High alpha resolution can be expensive."),
    FBP_EFFECT_INFINITE_ROTATION: ("3D", "LIGHT", "Continuously rotate the plane with optional stepped motion."),
    FBP_EFFECT_FELT_FUZZ: ("3D", "VERY_HEAVY", "Generate alpha-aware felt fibers. Render density and subdivisions can be extremely expensive."),
}

for _effect_id, (_category, _performance, _description) in FBP_EFFECT_METADATA.items():
    _definition = FBP_EFFECT_REGISTRY.get(_effect_id)
    if _definition is None:
        continue
    _definition.setdefault("category", _category)
    _definition.setdefault("performance", _performance)
    _definition.setdefault("description", _description)
    _definition.setdefault("supports", ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"))

# Color-chain effects can choose whether they read the original material color
# or the result of earlier effects. Image-sampling Matrix effects intentionally
# stay on their dedicated source because a shader cannot sample an arbitrary
# upstream color chain at a different cell-center UV without baking.
for _definition in FBP_EFFECT_REGISTRY.values():
    if (
        _definition.get("kind") == "SHADER"
        and _definition.get("stage") == "COLOR"
        and not _definition.get("image_aware")
    ):
        _definition.setdefault("supports_input_source", True)

finalize_effect_registry(FBP_EFFECT_REGISTRY)
FBP_EFFECT_REGISTRY_ISSUES = validate_effect_registry(FBP_EFFECT_REGISTRY)


def _fbp_purge_custom_effect_definitions():
    """Remove runtime custom entries while preserving the built-in registry."""
    removed = False
    for effect_id, definition in tuple(FBP_EFFECT_REGISTRY.items()):
        if is_custom_effect_id(effect_id) or bool(
            isinstance(definition, dict) and definition.get("custom", False)
        ):
            FBP_EFFECT_REGISTRY.pop(effect_id, None)
            removed = True
    _FBP_CUSTOM_EFFECT_MISS_CACHE.clear()
    return removed


def fbp_refresh_custom_effect_registry(force=False):
    """Merge tagged user node groups into the live effect registry."""
    force = bool(force)
    if force:
        _FBP_CUSTOM_EFFECT_MISS_CACHE.clear()
    custom_ids = refresh_custom_effect_registry(
        FBP_EFFECT_REGISTRY,
        FBP_EFFECT_SCHEMA_VERSION,
        force=force,
    )
    if custom_ids:
        finalize_effect_registry({
            effect_id: FBP_EFFECT_REGISTRY[effect_id]
            for effect_id in custom_ids
            if effect_id in FBP_EFFECT_REGISTRY
        })
        for effect_id in custom_ids:
            _FBP_CUSTOM_EFFECT_MISS_CACHE.pop(effect_id, None)
    return custom_ids


fbp_refresh_custom_effect_registry(force=True)
set_custom_effect_registry_refresh_callback(fbp_refresh_custom_effect_registry)

FBP_SHADER_STAGE_ORDER = {
    "UV": (FBP_EFFECT_UV_DISTORTION, FBP_EFFECT_PIXELATE),
    "COLOR": (
        FBP_EFFECT_CHROMA_KEY, FBP_EFFECT_SOLID_MASK, FBP_EFFECT_HUE_SATURATION,
        FBP_EFFECT_BRIGHTNESS_CONTRAST, FBP_EFFECT_INVERT, FBP_EFFECT_THRESHOLD,
        FBP_EFFECT_COLOR_ISOLATE, FBP_EFFECT_DUOTONE, FBP_EFFECT_HALFTONE,
        FBP_EFFECT_DOT_MATRIX, FBP_EFFECT_ASCII_MATRIX, FBP_EFFECT_GRAIN,
        FBP_EFFECT_DIGITAL_NOISE,
        FBP_EFFECT_PAPER_FIBERS, FBP_EFFECT_GRADIENT_LIGHT, FBP_EFFECT_GOBO_SHADOWS,
        FBP_EFFECT_CRT_SCANLINES, FBP_EFFECT_VIGNETTE, FBP_EFFECT_POSTERIZE,
    ),
}

FBP_BASE_EFFECT_MENU_ORDER = (
    FBP_EFFECT_CROP, FBP_EFFECT_EXTEND, FBP_EFFECT_CHROMA_KEY,
    FBP_EFFECT_SOLID_MASK, FBP_EFFECT_HUE_SATURATION, FBP_EFFECT_BRIGHTNESS_CONTRAST,
    FBP_EFFECT_INVERT, FBP_EFFECT_THRESHOLD, FBP_EFFECT_COLOR_ISOLATE, FBP_EFFECT_DUOTONE,
)
FBP_2D_EFFECT_MENU_ORDER = (
    FBP_EFFECT_UV_DISTORTION, FBP_EFFECT_PIXELATE, FBP_EFFECT_GRAIN,
    FBP_EFFECT_DIGITAL_NOISE, FBP_EFFECT_HALFTONE, FBP_EFFECT_DOT_MATRIX,
    FBP_EFFECT_ASCII_MATRIX, FBP_EFFECT_PAPER_FIBERS,
    FBP_EFFECT_GRADIENT_LIGHT, FBP_EFFECT_GOBO_SHADOWS, FBP_EFFECT_CRT_SCANLINES,
    FBP_EFFECT_VIGNETTE, FBP_EFFECT_POSTERIZE,
)
FBP_3D_EFFECT_MENU_ORDER = (
    FBP_EFFECT_CAMERA_SCALE_LOCK, FBP_EFFECT_CAMERA_BILLBOARD, FBP_EFFECT_MESH_WIGGLE, FBP_EFFECT_STOP_MOTION_CRUMPLE, FBP_EFFECT_WIND_BENDER,
    FBP_EFFECT_MESH_RIPPLE, FBP_EFFECT_PAPER_CURL, FBP_EFFECT_CUTOUT_OUTLINE, FBP_EFFECT_EXTRUDED_CUTOUT, FBP_EFFECT_THICKNESS, FBP_EFFECT_INFINITE_ROTATION, FBP_EFFECT_FELT_FUZZ,
    FBP_EFFECT_TEXT_MATRIX,
)

# Horizontal add-menu sections. Base tools remain first, while image effects are
# split by intent so the menu stays readable as the library grows.
FBP_IMAGE_EFFECT_MENU_SECTIONS = (
    (
        "Base", "TOOL_SETTINGS",
        (
            FBP_EFFECT_CROP, FBP_EFFECT_EXTEND, FBP_EFFECT_CHROMA_KEY,
            FBP_EFFECT_SOLID_MASK, FBP_EFFECT_HUE_SATURATION,
            FBP_EFFECT_BRIGHTNESS_CONTRAST, FBP_EFFECT_INVERT,
            FBP_EFFECT_THRESHOLD, FBP_EFFECT_COLOR_ISOLATE, FBP_EFFECT_DUOTONE,
        ),
    ),
    (
        "Creative", "NODE_TEXTURE",
        (
            FBP_EFFECT_UV_DISTORTION, FBP_EFFECT_PIXELATE, FBP_EFFECT_HALFTONE,
            FBP_EFFECT_DOT_MATRIX, FBP_EFFECT_ASCII_MATRIX,
            FBP_EFFECT_GRADIENT_LIGHT, FBP_EFFECT_GOBO_SHADOWS,
            FBP_EFFECT_POSTERIZE,
        ),
    ),
    (
        "Film & Display", "RENDERLAYERS",
        (
            FBP_EFFECT_GRAIN, FBP_EFFECT_DIGITAL_NOISE, FBP_EFFECT_PAPER_FIBERS,
            FBP_EFFECT_CRT_SCANLINES, FBP_EFFECT_VIGNETTE,
        ),
    ),
)

FBP_MESH_EFFECT_MENU_SECTIONS = (
    (
        "Camera & Layout", "CAMERA_DATA",
        (FBP_EFFECT_CAMERA_SCALE_LOCK, FBP_EFFECT_CAMERA_BILLBOARD),
    ),
    (
        "Deform & Motion", "MOD_DISPLACE",
        (
            FBP_EFFECT_MESH_WIGGLE, FBP_EFFECT_STOP_MOTION_CRUMPLE,
            FBP_EFFECT_WIND_BENDER, FBP_EFFECT_MESH_RIPPLE, FBP_EFFECT_PAPER_CURL,
            FBP_EFFECT_INFINITE_ROTATION,
        ),
    ),
    (
        "Surface", "MATERIAL",
        (FBP_EFFECT_CUTOUT_OUTLINE, FBP_EFFECT_EXTRUDED_CUTOUT, FBP_EFFECT_THICKNESS, FBP_EFFECT_FELT_FUZZ, FBP_EFFECT_TEXT_MATRIX),
    ),
)


def fbp_normalize_effect_id(effect_id):
    return str(effect_id or "")

def fbp_effect_definition(effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = FBP_EFFECT_REGISTRY.get(effect_id)
    if definition is None and is_custom_effect_id(effect_id):
        now = time.monotonic()
        last_miss = float(_FBP_CUSTOM_EFFECT_MISS_CACHE.get(effect_id, 0.0) or 0.0)
        if now - last_miss >= _FBP_CUSTOM_EFFECT_MISS_CACHE_SECONDS:
            fbp_refresh_custom_effect_registry(force=False)
            definition = FBP_EFFECT_REGISTRY.get(effect_id)
            if definition is None:
                if (
                    len(_FBP_CUSTOM_EFFECT_MISS_CACHE) >= 256
                    and effect_id not in _FBP_CUSTOM_EFFECT_MISS_CACHE
                ):
                    for stale_id in tuple(_FBP_CUSTOM_EFFECT_MISS_CACHE)[:64]:
                        _FBP_CUSTOM_EFFECT_MISS_CACHE.pop(stale_id, None)
                _FBP_CUSTOM_EFFECT_MISS_CACHE[effect_id] = now
        else:
            definition = None
    return definition or {}

def fbp_rig_media_type(rig):
    if not rig:
        return "UNKNOWN"
    if bool(getattr(rig, "fbp_is_color_plane", False)):
        mode = str(getattr(rig, "fbp_color_plane_mode", "SOLID") or "SOLID")
        if mode == "HOLDOUT":
            return "HOLDOUT"
        if mode == "GRADIENT":
            return "GRADIENT"
        return "COLOR"
    try:
        return "SEQUENCE" if len(getattr(rig, "fbp_images", ())) > 1 else "IMAGE"
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return "IMAGE"

def fbp_effect_supported_for_rig(rig, effect_id):
    definition = fbp_effect_definition(effect_id)
    if not definition or not rig:
        return False
    if bool(definition.get("custom_invalid", False)):
        return False
    media_type = fbp_rig_media_type(rig)
    supports = tuple(definition.get("supports", ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT")))
    if media_type not in supports:
        return False
    return True

def fbp_effect_tooltip(effect_id):
    definition = fbp_effect_definition(effect_id)
    if not definition:
        return "Frame by Plane effect"
    description = str(definition.get("description", "") or "")
    category = str(definition.get("category", "2D") or "2D")
    performance = str(definition.get("performance", "LIGHT") or "LIGHT").replace("_", " ").title()
    supports = ", ".join(str(item).title() for item in definition.get("supports", ()))
    warning = ""
    if str(definition.get("performance", "")).upper() in {"HEAVY", "VERY_HEAVY"}:
        warning = "\n\nWarning: This effect may reduce viewport playback performance."
    return (
        f"{description}\n\nCategory: {category}\n"
        f"Compatibility: {supports}\nPerformance: {performance}{warning}"
    )

def register():
    # Remove stale definitions left by older addon generations before rebuilding
    # the live custom registry from the current Main.
    _fbp_purge_custom_effect_definitions()
    set_custom_effect_registry_refresh_callback(fbp_refresh_custom_effect_registry)
    fbp_refresh_custom_effect_registry(force=True)


def unregister():
    set_custom_effect_registry_refresh_callback(None)
    _fbp_purge_custom_effect_definitions()


__all__ = (
    "FBP_EFFECT_MESH_WIGGLE",
    "FBP_EFFECT_STOP_MOTION_CRUMPLE",
    "FBP_EFFECT_WIND_BENDER",
    "FBP_EFFECT_MESH_RIPPLE",
    "FBP_EFFECT_PAPER_CURL",
    "FBP_EFFECT_CUTOUT_OUTLINE",
    "FBP_EFFECT_EXTRUDED_CUTOUT",
    "FBP_EFFECT_CAMERA_SCALE_LOCK",
    "FBP_EFFECT_CAMERA_BILLBOARD",
    "FBP_EFFECT_THICKNESS",
    "FBP_EFFECT_INFINITE_ROTATION",
    "FBP_EFFECT_FELT_FUZZ",
    "FBP_EFFECT_UV_DISTORTION",
    "FBP_EFFECT_PIXELATE",
    "FBP_EFFECT_SOLID_MASK",
    "FBP_EFFECT_HUE_SATURATION",
    "FBP_EFFECT_BRIGHTNESS_CONTRAST",
    "FBP_EFFECT_INVERT",
    "FBP_EFFECT_THRESHOLD",
    "FBP_EFFECT_COLOR_ISOLATE",
    "FBP_EFFECT_DUOTONE",
    "FBP_EFFECT_GRAIN",
    "FBP_EFFECT_PAPER_FIBERS",
    "FBP_EFFECT_GRADIENT_LIGHT",
    "FBP_EFFECT_GOBO_SHADOWS",
    "FBP_EFFECT_CRT_SCANLINES",
    "FBP_EFFECT_VIGNETTE",
    "FBP_EFFECT_POSTERIZE",
    "FBP_EFFECT_CROP",
    "FBP_EFFECT_EXTEND",
    "FBP_EFFECT_DIGITAL_NOISE",
    "FBP_EFFECT_CHROMA_KEY",
    "FBP_EFFECT_HALFTONE",
    "FBP_EFFECT_DOT_MATRIX",
    "FBP_EFFECT_ASCII_MATRIX",
    "FBP_EFFECT_TEXT_MATRIX",
    "FBP_EFFECT_REGISTRY",
    "FBP_EFFECT_METADATA",
    "FBP_EFFECT_REGISTRY_ISSUES",
    "fbp_refresh_custom_effect_registry",
    "FBP_SHADER_STAGE_ORDER",
    "FBP_BASE_EFFECT_MENU_ORDER",
    "FBP_2D_EFFECT_MENU_ORDER",
    "FBP_3D_EFFECT_MENU_ORDER",
    "FBP_IMAGE_EFFECT_MENU_SECTIONS",
    "FBP_MESH_EFFECT_MENU_SECTIONS",
    "fbp_effect_definition",
    "fbp_effect_supported_for_rig",
    "fbp_effect_tooltip",
    "fbp_normalize_effect_id",
    "fbp_rig_media_type",
)
