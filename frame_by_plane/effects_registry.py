"""Effect identifiers, registry metadata and UI helpers.

This module is intentionally independent from the Geometry Nodes and shader
runtime.  UI, diagnostics and property callbacks can inspect the effect library
without importing the large runtime implementation in :mod:`geometry_nodes`.
"""

import time

import bpy

from .runtime import FBP_DATA_ERRORS
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
FBP_EFFECT_CUTOUT_OUTLINE = "CUTOUT_OUTLINE"
FBP_EFFECT_CAMERA_SCALE_LOCK = "CAMERA_SCALE_LOCK"
FBP_EFFECT_CAMERA_BILLBOARD = "CAMERA_BILLBOARD"
FBP_EFFECT_MIRROR = "MIRROR"
FBP_EFFECT_THICKNESS = "THICKNESS"
FBP_EFFECT_INFINITE_ROTATION = "INFINITE_ROTATION"
FBP_EFFECT_FELT_FUZZ = "FELT_FUZZ"
FBP_EFFECT_LATTICE = "LATTICE"

FBP_EFFECT_UV_DISTORTION = "UV_DISTORTION"
FBP_EFFECT_PIXELATE = "PIXELATE"
FBP_EFFECT_SWIRL = "SWIRL"
FBP_EFFECT_BULGE_PINCH = "BULGE_PINCH"
FBP_EFFECT_LENS_WARP = "LENS_WARP"
FBP_EFFECT_WAVE_WARP = "WAVE_WARP"
FBP_EFFECT_RIPPLE_DISTORTION = "RIPPLE_DISTORTION"
FBP_EFFECT_KALEIDOSCOPE = "KALEIDOSCOPE"
FBP_EFFECT_HEX_PIXELATE = "HEX_PIXELATE"
FBP_EFFECT_MOSAIC_JITTER = "MOSAIC_JITTER"
FBP_EFFECT_DEPTH_BLUR = "DEPTH_BLUR"
FBP_EFFECT_GAUSSIAN_BLUR = "GAUSSIAN_BLUR"
FBP_EFFECT_DIRECTIONAL_BLUR = "DIRECTIONAL_BLUR"
FBP_EFFECT_TRIANGLE_BLUR = "TRIANGLE_BLUR"
FBP_EFFECT_TILT_SHIFT = "TILT_SHIFT"
FBP_EFFECT_UNSHARP_MASK = "UNSHARP_MASK"
FBP_EFFECT_EDGE_DETECT = "EDGE_DETECT"
FBP_EFFECT_SMOOTH_TOON = "SMOOTH_TOON"
FBP_EFFECT_ADAPTIVE_THRESHOLD = "ADAPTIVE_THRESHOLD"
FBP_EFFECT_FALSE_COLOR = "FALSE_COLOR"
FBP_EFFECT_CHROMATIC_ABERRATION = "CHROMATIC_ABERRATION"
FBP_EFFECT_INK = "INK"
FBP_EFFECT_EDGE_WORK = "EDGE_WORK"
FBP_EFFECT_PENCIL_SKETCH = "PENCIL_SKETCH"
FBP_EFFECT_POSTER_EDGES = "POSTER_EDGES"
FBP_EFFECT_CROSSHATCH = "CROSSHATCH"
FBP_EFFECT_EMBOSS = "EMBOSS"
FBP_EFFECT_ALPHA_MATTE = "ALPHA_MATTE"
FBP_EFFECT_LUMA_MATTE = "LUMA_MATTE"
FBP_EFFECT_SQUARE_MASK = "SQUARE_MASK"
FBP_EFFECT_CIRCLE_MASK = "CIRCLE_MASK"
FBP_EFFECT_TRIANGLE_MASK = "TRIANGLE_MASK"
FBP_EFFECT_CLIPPING_MASK = "CLIPPING_MASK"
FBP_EFFECT_IMPORTED_MASK = "IMPORTED_MASK"
FBP_EFFECT_LAYER_BLEND = "LAYER_BLEND"
FBP_EFFECT_COLOR_MASK = "COLOR_MASK"
FBP_EFFECT_LUMINANCE_MASK = "LUMINANCE_MASK"
FBP_EFFECT_CHANNEL_MASK = "CHANNEL_MASK"
FBP_EFFECT_GRADIENT_MASK = "GRADIENT_MASK"
FBP_EFFECT_NOISE_MASK = "NOISE_MASK"
FBP_EFFECT_SOLID_MASK = "SOLID_MASK"
FBP_EFFECT_HUE_SATURATION = "HUE_SATURATION"
FBP_EFFECT_WHITE_BALANCE = "WHITE_BALANCE"
FBP_EFFECT_CURVES = "CURVES"
FBP_EFFECT_BRIGHTNESS_CONTRAST = "BRIGHTNESS_CONTRAST"
FBP_EFFECT_INVERT = "INVERT"
FBP_EFFECT_THRESHOLD = "THRESHOLD"
FBP_EFFECT_COLOR_ISOLATE = "COLOR_ISOLATE"
FBP_EFFECT_DUOTONE = "DUOTONE"
FBP_EFFECT_RECOLOR = "RECOLOR"
FBP_EFFECT_GRAIN = "GRAIN"
FBP_EFFECT_PAPER_FIBERS = "PAPER_FIBERS"
FBP_EFFECT_GRADIENT_LIGHT = "GRADIENT_LIGHT"
FBP_EFFECT_RIM = "RIM"
FBP_EFFECT_SHADOW = "SHADOW"
FBP_EFFECT_GOBO_SHADOWS = "GOBO_SHADOWS"
FBP_EFFECT_CRT_SCANLINES = "CRT_SCANLINES"
FBP_EFFECT_VIGNETTE = "VIGNETTE"
FBP_EFFECT_POSTERIZE = "POSTERIZE"
FBP_EFFECT_SOLARIZE = "SOLARIZE"
FBP_EFFECT_TRITONE = "TRITONE"
FBP_EFFECT_FILM_FADE = "FILM_FADE"
FBP_EFFECT_CROP = "CROP"
FBP_EFFECT_EXTEND = "EXTEND"
FBP_EFFECT_DIGITAL_NOISE = "DIGITAL_NOISE"
FBP_EFFECT_CHROMA_KEY = "CHROMA_KEY"
FBP_EFFECT_HALFTONE = "HALFTONE"
FBP_EFFECT_DOT_MATRIX = "DOT_MATRIX"
FBP_EFFECT_ASCII_MATRIX = "ASCII_MATRIX"
FBP_EFFECT_ASCII = "ASCII"
FBP_EFFECT_TEXT_MATRIX = "TEXT_MATRIX"

_FBP_CUSTOM_EFFECT_MISS_CACHE_SECONDS = 2.0
_FBP_CUSTOM_EFFECT_MISS_CACHE = globals().get("_FBP_CUSTOM_EFFECT_MISS_CACHE", {})
if not isinstance(_FBP_CUSTOM_EFFECT_MISS_CACHE, dict):
    _FBP_CUSTOM_EFFECT_MISS_CACHE = {}

FBP_EFFECT_REGISTRY = {
    FBP_EFFECT_CROP: {
        "label": "Crop", "icon": "FULLSCREEN_EXIT", "kind": "BASE",
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
        "label": "Crumple", "icon": "IMAGE_PLANE", "kind": "GEOMETRY",
        "source_names": ("FBP_StopMotion_Crumple",), "canonical_name": "FBP_GN_StopMotion_Crumple_450",
        "modifier_name": "FBP • Stop Motion Crumple", "asset_id": "frame_by_plane.stop_motion_crumple.450",
        "enabled_key": "fbp_effect_stop_motion_crumple", "alpha_aware": False,
        "property_map": {"fbp_stop_motion_resolution": "Resolution", "fbp_stop_motion_strength": "Strength", "fbp_stop_motion_step_frames": "Step Frames"},
    },
    FBP_EFFECT_WIND_BENDER: {
        "label": "Wind", "icon": "FORCE_WIND", "kind": "GEOMETRY",
        "source_names": (), "canonical_name": "FBP_GN_Mesh_Motion_611",
        "modifier_name": "FBP • Mesh Motion", "asset_id": "frame_by_plane.mesh_motion.611",
        "enabled_key": "fbp_effect_wind_bender", "alpha_aware": False,
        "property_map": {
            "fbp_wind_subdivision": "Subdivision", "fbp_wind_bend_amount": "Bend Amount",
            "fbp_wind_speed": "Wind Speed", "fbp_wind_stepped": "Stepped",
            "fbp_wind_pin_edge": "Pin Mode", "fbp_wind_pin_strength": "Pin Strength",
            "fbp_wind_pin_vertex_group": "Pin Vertex Group", "fbp_wind_motion_mode": "Motion Mode",
            "fbp_wind_ripple_direction": "Ripple Direction",
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
    FBP_EFFECT_CUTOUT_OUTLINE: {
        "label": "Cutout Outline", "icon": "MOD_SKIN", "kind": "GEOMETRY",
        "source_names": (), "canonical_name": "FBP_GN_Cutout_Outline_6027",
        "modifier_name": "FBP • Cutout Outline", "asset_id": "frame_by_plane.cutout_outline.6027",
        "enabled_key": "fbp_effect_cutout_outline", "alpha_aware": True,
        "private_group": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE"),
        "requires_alpha_geometry_contract": True,
        "required_input_sockets": ("Outline Material", "Show Image", "Wiggle Amount", "Wiggle Scale", "Wiggle Phase"),
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
            "fbp_cutout_outline_show_image": "Show Image",
            "fbp_cutout_outline_wiggle_amount": "Wiggle Amount",
            "fbp_cutout_outline_wiggle_scale": "Wiggle Scale",
            "fbp_cutout_outline_wiggle_phase": "Wiggle Phase",
        },
        "extra_properties": (
            "fbp_cutout_outline_playback_resolution",
            "fbp_cutout_outline_render_resolution",
            "fbp_cutout_outline_color",
        ),
        "evolve_property": "fbp_cutout_outline_wiggle_phase",
        "evolve_amount": 0.35,
        "evolve_active_property": "fbp_cutout_outline_wiggle_amount", "supports_seed": True,
    },
    FBP_EFFECT_CAMERA_SCALE_LOCK: {
        "label": "Camera Scale Lock", "icon": "CON_CAMERASOLVER", "kind": "GEOMETRY",
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
        "label": "Track to Camera", "icon": "CON_TRACKTO", "kind": "BASE", "category": "3D",
        "enabled_key": "fbp_effect_camera_billboard", "builtin": True,
        "supports_future_instances": False,
        "property_map": {
            "fbp_camera_billboard_mode": "Tracking Mode",
            "fbp_camera_billboard_flip": "Face Away",
            "fbp_camera_billboard_influence": "Influence",
        },
    },
    FBP_EFFECT_MIRROR: {
        "label": "Mirror", "icon": "MOD_MIRROR", "kind": "GEOMETRY",
        "source_names": (), "canonical_name": "FBP_GN_Mirror_611",
        "modifier_name": "FBP • Mirror", "asset_id": "frame_by_plane.mirror.611",
        "enabled_key": "fbp_effect_mirror", "alpha_aware": False, "builtin": True,
        "property_map": {
            "fbp_mirror_x": "Mirror X",
            "fbp_mirror_y": "Mirror Y",
        },
    },
    FBP_EFFECT_THICKNESS: {
        "label": "Extrude", "icon": "AREA_DOCK", "kind": "GEOMETRY",
        "source_names": ("FBP_Thickness", "FBP_GN_Extrude_585"), "canonical_name": "FBP_GN_Extrude_611",
        "modifier_name": "FBP • Extrude", "asset_id": "frame_by_plane.extrude.611",
        "enabled_key": "fbp_effect_thickness", "alpha_aware": True,
        "private_group": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE"),
        "requires_alpha_geometry_contract": True,
        "required_input_sockets": ("Pixels X", "Pixels Y", "Use Alpha Mask", "Side Material"),
        "quality_profile": "ALPHA_PIXELS",
        "quality_contracts": (
            {
                "socket": "Pixels X",
                "viewport_property": "fbp_thickness_viewport_pixels_x",
                "playback_property": "fbp_thickness_playback_pixels_x",
                "render_property": "fbp_thickness_render_pixels_x",
                "minimum": 1, "playback_mode": "REPLACE",
            },
            {
                "socket": "Pixels Y",
                "viewport_property": "fbp_thickness_viewport_pixels_y",
                "playback_property": "fbp_thickness_playback_pixels_y",
                "render_property": "fbp_thickness_render_pixels_y",
                "minimum": 1, "playback_mode": "REPLACE",
            },
        ),
        "property_map": {
            "fbp_thickness_viewport_pixels_x": "Pixels X",
            "fbp_thickness_viewport_pixels_y": "Pixels Y",
            "fbp_thickness_alpha_threshold": "Alpha Threshold",
            "fbp_thickness_amount": "Thickness",
            "fbp_thickness_mode": "Mode",
            "fbp_thickness_array_count": "Array Count",
            "fbp_thickness_direction": "Direction",
        },
        "extra_properties": (
            "fbp_thickness_grid_mode",
            "fbp_thickness_follow_pixelate",
            "fbp_thickness_safe_grid",
            "fbp_thickness_playback_pixels_x",
            "fbp_thickness_playback_pixels_y",
            "fbp_thickness_render_pixels_x",
            "fbp_thickness_render_pixels_y",
            "fbp_thickness_side_material",
            "fbp_thickness_side_color",
            "fbp_thickness_use_plane_colors",
        ),
        "ui_labels": {
            "fbp_thickness_grid_mode": "Grid",
            "fbp_thickness_follow_pixelate": "Follow Pixelate",
            "fbp_thickness_safe_grid": "Safe Grid Limits",
            "fbp_thickness_playback_pixels_x": "Playback Pixels X",
            "fbp_thickness_playback_pixels_y": "Playback Pixels Y",
            "fbp_thickness_render_pixels_x": "Render Pixels X",
            "fbp_thickness_render_pixels_y": "Render Pixels Y",
            "fbp_thickness_side_material": "Material Override",
            "fbp_thickness_side_color": "Side Color",
            "fbp_thickness_use_plane_colors": "Use Plane Colors",
        },
    },
    FBP_EFFECT_INFINITE_ROTATION: {
        "label": "Infinite Rotation", "icon": "FILE_REFRESH", "kind": "GEOMETRY",
        "source_names": ("FBP_Infinite_Rotation",), "canonical_name": "FBP_GN_Infinite_Rotation_450",
        "modifier_name": "FBP • Infinite Rotation", "asset_id": "frame_by_plane.infinite_rotation.450",
        "enabled_key": "fbp_effect_infinite_rotation", "alpha_aware": False,
        "property_map": {
            "fbp_infinite_rotation_speed": "Speed", "fbp_infinite_rotation_direction": "Direction",
            "fbp_infinite_rotation_stepped": "Stepped", "fbp_infinite_rotation_offset": "Offset",
        },
    },
    FBP_EFFECT_FELT_FUZZ: {
        "label": "Felt Fuzz", "icon": "PARTICLEMODE", "kind": "GEOMETRY",
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
    FBP_EFFECT_LATTICE: {
        "label": "Lattice", "icon": "MOD_LATTICE", "kind": "BASE",
        "category": "3D", "enabled_key": "fbp_effect_lattice",
        # Lattice deforms the generated mesh and does not depend on whether the
        # visual source is an image, sequence, procedural plane or migrated
        # test layer. Validate the real linked mesh instead of media metadata.
        "requires_mesh_plane": True,
        "property_map": {
            "fbp_lattice_mode": "Mode",
            "fbp_lattice_flatten_influence": "Flatten Influence",
            "fbp_lattice_live_update": "Live Update",
            "fbp_lattice_show_cage": "Show Cage",
            "fbp_lattice_grid_preset": "Cage Grid",
            "fbp_lattice_custom_loops_u": "Horizontal Loops",
            "fbp_lattice_custom_loops_v": "Vertical Loops",
            "fbp_lattice_interpolation": "Interpolation",
            "fbp_lattice_mesh_detail_mode": "Mesh Detail",
            "fbp_lattice_mesh_density": "Density",
            "fbp_lattice_mesh_subdivisions": "Subdivision Levels",
        },
        # Points W is retained only to migrate older files. The planar cage is
        # planar and always evaluates with one depth layer.
        "extra_properties": (
            "fbp_lattice_object", "fbp_lattice_points_u", "fbp_lattice_points_v",
            "fbp_lattice_points_w", "fbp_lattice_link_loops",
        ),
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT", "HOLDOUT", "CUTOUT"),
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
        "source_names": (), "canonical_name": "FBP_SH_Pixelate_6014",
        "asset_id": "frame_by_plane.shader.pixelate.6014", "enabled_key": "fbp_effect_pixelate",
        "input_socket": "Vector", "output_socket": "Vector Out",
        "required_input_sockets": ("Pixels X", "Pixels Y", "Rotation", "Offset X", "Offset Y"),
        "property_map": {
            "fbp_pixelate_resolution": "Pixels X",
            "fbp_pixelate_height": "Pixels Y",
            "fbp_pixelate_rotation": "Rotation",
            "fbp_pixelate_offset_x": "Offset X",
            "fbp_pixelate_offset_y": "Offset Y",
        },
        "extra_properties": ("fbp_pixelate_grid_mode",),
        "builtin": True,
    },
    FBP_EFFECT_SWIRL: {
        "label": "Swirl", "icon": "FORCE_VORTEX", "kind": "SHADER", "stage": "UV",
        "canonical_name": "FBP_SH_Swirl_6014", "asset_id": "frame_by_plane.shader.swirl.6014",
        "enabled_key": "fbp_effect_swirl", "input_socket": "Vector", "output_socket": "Vector Out",
        "required_input_sockets": ("Center X", "Center Y", "Radius", "Angle", "Factor"),
        "property_map": {
            "fbp_swirl_center_x": "Center X", "fbp_swirl_center_y": "Center Y",
            "fbp_swirl_radius": "Radius", "fbp_swirl_angle": "Angle", "fbp_swirl_factor": "Factor",
        },
        "builtin": True,
    },
    FBP_EFFECT_BULGE_PINCH: {
        "label": "Inflate & Pinch", "icon": "MOD_WARP", "kind": "SHADER", "stage": "UV",
        "canonical_name": "FBP_SH_Bulge_Pinch_6014", "asset_id": "frame_by_plane.shader.bulge_pinch.6014",
        "enabled_key": "fbp_effect_bulge_pinch", "input_socket": "Vector", "output_socket": "Vector Out",
        "required_input_sockets": ("Center X", "Center Y", "Radius", "Strength", "Factor"),
        "property_map": {
            "fbp_bulge_pinch_center_x": "Center X", "fbp_bulge_pinch_center_y": "Center Y",
            "fbp_bulge_pinch_radius": "Radius", "fbp_bulge_pinch_strength": "Strength",
            "fbp_bulge_pinch_factor": "Factor",
        },
        "builtin": True,
    },
    FBP_EFFECT_LENS_WARP: {
        "label": "Lens Warp", "icon": "CAMERA_DATA", "kind": "SHADER", "stage": "UV",
        "canonical_name": "FBP_SH_Lens_Warp_6014", "asset_id": "frame_by_plane.shader.lens_warp.6014",
        "enabled_key": "fbp_effect_lens_warp", "input_socket": "Vector", "output_socket": "Vector Out",
        "required_input_sockets": ("Center X", "Center Y", "Distortion", "Zoom", "Factor"),
        "property_map": {
            "fbp_lens_warp_center_x": "Center X", "fbp_lens_warp_center_y": "Center Y",
            "fbp_lens_warp_distortion": "Distortion", "fbp_lens_warp_zoom": "Zoom",
            "fbp_lens_warp_factor": "Factor",
        },
        "builtin": True,
    },
    FBP_EFFECT_WAVE_WARP: {
        "label": "Wave", "icon": "MOD_OCEAN", "kind": "SHADER", "stage": "UV",
        "canonical_name": "FBP_SH_Wave_Warp_6019", "asset_id": "frame_by_plane.shader.wave_warp.6019",
        "enabled_key": "fbp_effect_wave_warp", "input_socket": "Vector", "output_socket": "Vector Out",
        "required_input_sockets": ("Amplitude", "Frequency", "Phase", "Speed", "Angle", "Factor"),
        "property_map": {
            "fbp_wave_warp_amplitude": "Amplitude", "fbp_wave_warp_frequency": "Frequency",
            "fbp_wave_warp_phase": "Phase", "fbp_wave_warp_speed": "Speed",
            "fbp_wave_warp_angle": "Angle", "fbp_wave_warp_factor": "Factor",
        },
        "evolve_property": "fbp_wave_warp_phase", "evolve_amount": 6.283185307,
        "evolve_active_property": "fbp_wave_warp_amplitude", "supports_seed": True,
        "builtin": True,
    },
    FBP_EFFECT_RIPPLE_DISTORTION: {
        "label": "Ripple Distortion", "icon": "FORCE_HARMONIC", "kind": "SHADER", "stage": "UV",
        "canonical_name": "FBP_SH_Ripple_Distortion_6019", "asset_id": "frame_by_plane.shader.ripple_distortion.6019",
        "enabled_key": "fbp_effect_ripple_distortion", "input_socket": "Vector", "output_socket": "Vector Out",
        "required_input_sockets": ("Center X", "Center Y", "Amplitude", "Frequency", "Phase", "Speed", "Radius", "Falloff", "Factor"),
        "property_map": {
            "fbp_ripple_distortion_center_x": "Center X", "fbp_ripple_distortion_center_y": "Center Y",
            "fbp_ripple_distortion_amplitude": "Amplitude", "fbp_ripple_distortion_frequency": "Frequency",
            "fbp_ripple_distortion_phase": "Phase", "fbp_ripple_distortion_speed": "Speed",
            "fbp_ripple_distortion_radius": "Radius",
            "fbp_ripple_distortion_falloff": "Falloff", "fbp_ripple_distortion_factor": "Factor",
        },
        "evolve_property": "fbp_ripple_distortion_phase", "evolve_amount": 6.283185307,
        "evolve_active_property": "fbp_ripple_distortion_amplitude", "supports_seed": True,
        "builtin": True,
    },
    FBP_EFFECT_KALEIDOSCOPE: {
        "label": "Kaleidoscope", "icon": "FREEZE", "kind": "SHADER", "stage": "UV",
        "canonical_name": "FBP_SH_Kaleidoscope_6014", "asset_id": "frame_by_plane.shader.kaleidoscope.6014",
        "enabled_key": "fbp_effect_kaleidoscope", "input_socket": "Vector", "output_socket": "Vector Out",
        "required_input_sockets": ("Center X", "Center Y", "Segments", "Rotation", "Factor"),
        "property_map": {
            "fbp_kaleidoscope_center_x": "Center X", "fbp_kaleidoscope_center_y": "Center Y",
            "fbp_kaleidoscope_segments": "Segments", "fbp_kaleidoscope_rotation": "Rotation",
            "fbp_kaleidoscope_factor": "Factor",
        },
        "builtin": True,
    },
    FBP_EFFECT_HEX_PIXELATE: {
        "label": "Hexagonal", "icon": "ALIASED", "kind": "SHADER", "stage": "UV",
        "canonical_name": "FBP_SH_Hex_Pixelate_6014", "asset_id": "frame_by_plane.shader.hex_pixelate.6014",
        "enabled_key": "fbp_effect_hex_pixelate", "input_socket": "Vector", "output_socket": "Vector Out",
        "required_input_sockets": ("Cells X", "Cells Y", "Rotation", "Factor"),
        "property_map": {
            "fbp_hex_pixelate_cells_x": "Cells X", "fbp_hex_pixelate_cells_y": "Cells Y",
            "fbp_hex_pixelate_rotation": "Rotation", "fbp_hex_pixelate_factor": "Factor",
        },
        "builtin": True,
    },
    FBP_EFFECT_MOSAIC_JITTER: {
        "label": "Mosaic Jitter", "icon": "ALIASED", "kind": "SHADER", "stage": "UV",
        "canonical_name": "FBP_SH_Mosaic_Jitter_6026", "asset_id": "frame_by_plane.shader.mosaic_jitter.6026",
        "enabled_key": "fbp_effect_mosaic_jitter", "input_socket": "Vector", "output_socket": "Vector Out",
        "required_input_sockets": ("Cells X", "Cells Y", "Rotation", "Jitter", "Offset X", "Offset Y", "Seed", "Factor"),
        "property_map": {
            "fbp_mosaic_jitter_cells_x": "Cells X", "fbp_mosaic_jitter_cells_y": "Cells Y",
            "fbp_mosaic_jitter_rotation": "Rotation",
            "fbp_mosaic_jitter_amount": "Jitter",
            "fbp_mosaic_jitter_offset_x": "Offset X", "fbp_mosaic_jitter_offset_y": "Offset Y",
            "fbp_mosaic_jitter_seed": "Seed",
            "fbp_mosaic_jitter_factor": "Factor",
        },
        "evolve_property": "fbp_mosaic_jitter_seed", "evolve_amount": 1.0,
        "evolve_active_property": "fbp_mosaic_jitter_amount",
        "evolve_mode": "SEED_STEP", "supports_seed": True, "builtin": True,
    },
    FBP_EFFECT_DEPTH_BLUR: {
        "label": "Depth Blur", "icon": "CON_CAMERASOLVER", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Depth_Blur_5319",
        "asset_id": "frame_by_plane.shader.depth_blur.5319", "enabled_key": "fbp_effect_depth_blur",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "property_map": {
            "fbp_depth_blur_manual_radius": "Manual Radius",
            "fbp_depth_blur_max_radius": "Maximum Radius",
            "fbp_depth_blur_focus_range": "Focus Range",
            "fbp_depth_blur_falloff": "Falloff",
            "fbp_depth_blur_near_strength": "Near Strength",
            "fbp_depth_blur_far_strength": "Far Strength",
        },
        "extra_properties": (
            "fbp_depth_blur_mode", "fbp_depth_blur_use_camera_focus",
            "fbp_depth_blur_focus_distance",
        ),
        "private_group": True, "image_aware": True, "camera_aware": True,
        "uses_source_texel": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE"),
    },
    FBP_EFFECT_GAUSSIAN_BLUR: {
        "label": "Gaussian Blur", "icon": "PROP_ON", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Gaussian_Blur_611",
        "asset_id": "frame_by_plane.shader.gaussian_blur.611", "enabled_key": "fbp_effect_gaussian_blur",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE"),
        "required_input_sockets": ("Use Image Sample", "Radius X", "Radius Y", "Samples", "Factor", "Texel X", "Texel Y"),
        "property_map": {
            "fbp_gaussian_blur_radius_x": "Radius X",
            "fbp_gaussian_blur_radius_y": "Radius Y",
            "fbp_gaussian_blur_samples": "Samples",
            "fbp_gaussian_blur_factor": "Factor",
        },
    },
    FBP_EFFECT_DIRECTIONAL_BLUR: {
        "label": "Directional Blur", "icon": "PROP_PROJECTED", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Directional_Blur_611",
        "asset_id": "frame_by_plane.shader.directional_blur.611", "enabled_key": "fbp_effect_directional_blur",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE"),
        "required_input_sockets": ("Use Image Sample", "Angle", "Distance", "Samples", "Factor", "Texel X", "Texel Y"),
        "property_map": {
            "fbp_directional_blur_angle": "Angle",
            "fbp_directional_blur_distance": "Distance",
            "fbp_directional_blur_samples": "Samples",
            "fbp_directional_blur_factor": "Factor",
        },
    },
    FBP_EFFECT_TRIANGLE_BLUR: {
        "label": "Triangle Blur", "icon": "MOD_TONEMAP", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Triangle_Blur_6012", "asset_id": "frame_by_plane.shader.triangle_blur.6012",
        "enabled_key": "fbp_effect_triangle_blur", "input_socket": "Color In", "output_socket": "Color Out",
        "uv_input_socket": "UV Vector", "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE"),
        "property_map": {"fbp_triangle_blur_radius": "Radius", "fbp_triangle_blur_samples": "Samples", "fbp_triangle_blur_factor": "Factor"},
    },
    FBP_EFFECT_TILT_SHIFT: {
        "label": "Tilt Shift", "icon": "PROP_PROJECTED", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Tilt_Shift_6037", "asset_id": "frame_by_plane.shader.tilt_shift.6037",
        "enabled_key": "fbp_effect_tilt_shift", "input_socket": "Color In", "output_socket": "Color Out",
        "uv_input_socket": "UV Vector", "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE"),
        "required_input_sockets": ("Use Image Sample", "Focus Position", "Focus Width", "Focus Angle", "Blur Radius", "Factor", "Texel X", "Texel Y"),
        "property_map": {"fbp_tilt_shift_position": "Focus Position", "fbp_tilt_shift_width": "Focus Width", "fbp_tilt_shift_angle": "Focus Angle", "fbp_tilt_shift_radius": "Blur Radius", "fbp_tilt_shift_factor": "Factor"},
    },
    FBP_EFFECT_UNSHARP_MASK: {
        "label": "Sharpness", "icon": "SHARPCURVE", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Unsharp_Mask_6012", "asset_id": "frame_by_plane.shader.unsharp_mask.6012",
        "enabled_key": "fbp_effect_unsharp_mask", "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "supports": ("IMAGE", "SEQUENCE"),
        "property_map": {"fbp_unsharp_radius": "Radius", "fbp_unsharp_amount": "Amount", "fbp_unsharp_factor": "Factor"},
    },
    FBP_EFFECT_EDGE_DETECT: {
        "label": "Detect", "icon": "MOD_DASH", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Edge_Detect_6013", "asset_id": "frame_by_plane.shader.edge_detect.6013",
        "enabled_key": "fbp_effect_edge_detect", "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "supports": ("IMAGE", "SEQUENCE"),
        "required_input_sockets": ("Width", "Strength", "Threshold", "Softness", "Edge Color", "Factor", "Texel X", "Texel Y"),
        "property_map": {
            "fbp_edge_detect_width": "Width", "fbp_edge_detect_strength": "Strength",
            "fbp_edge_detect_threshold": "Threshold", "fbp_edge_detect_softness": "Softness",
            "fbp_edge_detect_color": "Edge Color", "fbp_edge_detect_factor": "Factor",
        },
    },
    FBP_EFFECT_SMOOTH_TOON: {
        "label": "Smooth Toon", "icon": "SHADING_RENDERED", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Smooth_Toon_6013", "asset_id": "frame_by_plane.shader.smooth_toon.6013",
        "enabled_key": "fbp_effect_smooth_toon", "input_socket": "Color In", "output_socket": "Color Out", "builtin": True,
        "required_input_sockets": ("Levels", "Softness", "Factor"),
        "property_map": {"fbp_smooth_toon_levels": "Levels", "fbp_smooth_toon_softness": "Softness", "fbp_smooth_toon_factor": "Factor"},
    },
    FBP_EFFECT_ADAPTIVE_THRESHOLD: {
        "label": "Threshold", "icon": "MOD_DASH", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Adaptive_Threshold_6013", "asset_id": "frame_by_plane.shader.adaptive_threshold.6013",
        "enabled_key": "fbp_effect_adaptive_threshold", "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "supports": ("IMAGE", "SEQUENCE"),
        "required_input_sockets": ("Radius", "Offset", "Softness", "Invert", "Factor", "Texel X", "Texel Y"),
        "property_map": {
            "fbp_adaptive_threshold_radius": "Radius", "fbp_adaptive_threshold_offset": "Offset",
            "fbp_adaptive_threshold_softness": "Softness", "fbp_adaptive_threshold_invert": "Invert",
            "fbp_adaptive_threshold_factor": "Factor",
        },
    },
    FBP_EFFECT_INK: {
        "label": "Ink", "icon": "MESH_MONKEY", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Ink_6013", "asset_id": "frame_by_plane.shader.ink.6013",
        "enabled_key": "fbp_effect_ink", "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "supports": ("IMAGE", "SEQUENCE"),
        "required_input_sockets": ("Width", "Threshold", "Softness", "Strength", "Ink Color", "Paper Color", "Preserve Color", "Factor", "Texel X", "Texel Y"),
        "property_map": {
            "fbp_ink_width": "Width", "fbp_ink_threshold": "Threshold", "fbp_ink_softness": "Softness",
            "fbp_ink_strength": "Strength", "fbp_ink_color": "Ink Color", "fbp_ink_paper_color": "Paper Color",
            "fbp_ink_preserve_color": "Preserve Color", "fbp_ink_factor": "Factor",
        },
    },
    FBP_EFFECT_EDGE_WORK: {
        "label": "Work", "icon": "MOD_DASH", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Edge_Work_6013", "asset_id": "frame_by_plane.shader.edge_work.6013",
        "enabled_key": "fbp_effect_edge_work", "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "supports": ("IMAGE", "SEQUENCE"),
        "required_input_sockets": ("Radius", "Thickness", "Strength", "Threshold", "Softness", "Edge Color", "Factor", "Texel X", "Texel Y"),
        "property_map": {
            "fbp_edge_work_radius": "Radius", "fbp_edge_work_thickness": "Thickness", "fbp_edge_work_strength": "Strength",
            "fbp_edge_work_threshold": "Threshold", "fbp_edge_work_softness": "Softness",
            "fbp_edge_work_color": "Edge Color", "fbp_edge_work_factor": "Factor",
        },
    },
    FBP_EFFECT_PENCIL_SKETCH: {
        "label": "Sketch", "icon": "MESH_MONKEY", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Pencil_Sketch_6013", "asset_id": "frame_by_plane.shader.pencil_sketch.6013",
        "enabled_key": "fbp_effect_pencil_sketch", "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "supports": ("IMAGE", "SEQUENCE"),
        "required_input_sockets": ("Radius", "Contrast", "Graphite Color", "Paper Color", "Color Amount", "Factor", "Texel X", "Texel Y"),
        "property_map": {
            "fbp_pencil_sketch_radius": "Radius", "fbp_pencil_sketch_contrast": "Contrast",
            "fbp_pencil_sketch_graphite": "Graphite Color", "fbp_pencil_sketch_paper": "Paper Color",
            "fbp_pencil_sketch_color_amount": "Color Amount", "fbp_pencil_sketch_factor": "Factor",
        },
    },
    FBP_EFFECT_POSTER_EDGES: {
        "label": "Poster", "icon": "MOD_DASH", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Poster_Edges_6013", "asset_id": "frame_by_plane.shader.poster_edges.6013",
        "enabled_key": "fbp_effect_poster_edges", "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "supports": ("IMAGE", "SEQUENCE"),
        "required_input_sockets": ("Levels", "Band Softness", "Edge Width", "Edge Strength", "Edge Threshold", "Edge Color", "Factor", "Texel X", "Texel Y"),
        "property_map": {
            "fbp_poster_edges_levels": "Levels", "fbp_poster_edges_softness": "Band Softness",
            "fbp_poster_edges_width": "Edge Width", "fbp_poster_edges_strength": "Edge Strength",
            "fbp_poster_edges_threshold": "Edge Threshold", "fbp_poster_edges_color": "Edge Color",
            "fbp_poster_edges_factor": "Factor",
        },
    },
    FBP_EFFECT_CROSSHATCH: {
        "label": "Crosshatch", "icon": "MOD_LINEART", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Crosshatch_6013", "asset_id": "frame_by_plane.shader.crosshatch.6013",
        "enabled_key": "fbp_effect_crosshatch", "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "private_group": True, "uses_source_texel": True, "builtin": True, "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
        "required_input_sockets": ("Scale", "Rotation", "Line Width", "Levels", "Ink Color", "Paper Color", "Preserve Color", "Factor", "Texel X", "Texel Y"),
        "property_map": {
            "fbp_crosshatch_scale": "Scale", "fbp_crosshatch_rotation": "Rotation", "fbp_crosshatch_line_width": "Line Width",
            "fbp_crosshatch_levels": "Levels", "fbp_crosshatch_ink": "Ink Color", "fbp_crosshatch_paper": "Paper Color",
            "fbp_crosshatch_preserve_color": "Preserve Color", "fbp_crosshatch_factor": "Factor",
        },
    },
    FBP_EFFECT_EMBOSS: {
        "label": "Emboss", "icon": "MOD_OCEAN", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Emboss_6013", "asset_id": "frame_by_plane.shader.emboss.6013",
        "enabled_key": "fbp_effect_emboss", "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "supports": ("IMAGE", "SEQUENCE"),
        "required_input_sockets": ("Angle", "Distance", "Strength", "Bias", "Color Amount", "Factor", "Texel X", "Texel Y"),
        "property_map": {
            "fbp_emboss_angle": "Angle", "fbp_emboss_distance": "Distance", "fbp_emboss_strength": "Strength",
            "fbp_emboss_bias": "Bias", "fbp_emboss_color_amount": "Color Amount", "fbp_emboss_factor": "Factor",
        },
    },
    FBP_EFFECT_FALSE_COLOR: {
        "label": "False Color", "icon": "COLOR", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_False_Color_6012", "asset_id": "frame_by_plane.shader.false_color.6012",
        "enabled_key": "fbp_effect_false_color", "input_socket": "Color In", "output_socket": "Color Out", "builtin": True,
        "property_map": {"fbp_false_color_dark": "Dark Color", "fbp_false_color_light": "Light Color", "fbp_false_color_factor": "Factor"},
    },
    FBP_EFFECT_CHROMATIC_ABERRATION: {
        "label": "Chromatic Aberration", "icon": "SEQ_CHROMA_SCOPE", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Chromatic_Aberration_6012", "asset_id": "frame_by_plane.shader.chromatic_aberration.6012",
        "enabled_key": "fbp_effect_chromatic_aberration", "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "supports": ("IMAGE", "SEQUENCE"),
        "property_map": {"fbp_chromatic_aberration_distance": "Distance", "fbp_chromatic_aberration_angle": "Angle", "fbp_chromatic_aberration_factor": "Factor"},
    },
    FBP_EFFECT_ALPHA_MATTE: {
        "label": "Alpha Matte", "icon": "TEXTURE", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Alpha_Matte_552",
        "asset_id": "frame_by_plane.shader.alpha_matte.552", "enabled_key": "fbp_effect_alpha_matte",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out", "uv_input_socket": "UV Vector",
        "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte"), ("SOURCE", "Source")),
        "property_map": {
            "fbp_alpha_matte_factor": "Factor",
            "fbp_alpha_matte_invert": "Invert",
            "fbp_alpha_matte_use_source_transform": "Use Source Transform",
            "fbp_alpha_matte_uv_offset_x": "UV Offset X",
            "fbp_alpha_matte_uv_offset_y": "UV Offset Y",
            "fbp_alpha_matte_uv_scale_x": "UV Scale X",
            "fbp_alpha_matte_uv_scale_y": "UV Scale Y",
            "fbp_alpha_matte_uv_rotation": "UV Rotation",
        },
        "extra_properties": ("fbp_alpha_matte_source", "fbp_alpha_matte_source_display"),
        "mask_source_property": "fbp_alpha_matte_source",
        "mask_source_aware": True, "mask_source_visibility_aware": True,
        "mask_source_transform_aware": True, "private_group": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_LUMA_MATTE: {
        "label": "Luma Matte", "icon": "SEQ_SPLITVIEW", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Luma_Matte_552",
        "asset_id": "frame_by_plane.shader.luma_matte.552", "enabled_key": "fbp_effect_luma_matte",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out", "uv_input_socket": "UV Vector",
        "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte"), ("SOURCE", "Source")),
        "property_map": {
            "fbp_luma_matte_factor": "Factor",
            "fbp_luma_matte_invert": "Invert",
            "fbp_luma_matte_threshold": "Threshold",
            "fbp_luma_matte_softness": "Softness",
            "fbp_luma_matte_use_source_transform": "Use Source Transform",
            "fbp_luma_matte_uv_offset_x": "UV Offset X",
            "fbp_luma_matte_uv_offset_y": "UV Offset Y",
            "fbp_luma_matte_uv_scale_x": "UV Scale X",
            "fbp_luma_matte_uv_scale_y": "UV Scale Y",
            "fbp_luma_matte_uv_rotation": "UV Rotation",
        },
        "extra_properties": ("fbp_luma_matte_source", "fbp_luma_matte_source_display"),
        "mask_source_property": "fbp_luma_matte_source",
        "mask_source_aware": True, "mask_source_visibility_aware": True,
        "mask_source_transform_aware": True, "private_group": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_SQUARE_MASK: {
        "label": "Square Mask", "icon": "MOD_MESHDEFORM", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Square_Mask_553",
        "asset_id": "frame_by_plane.shader.square_mask.553", "enabled_key": "fbp_effect_square_mask",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out", "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte")),
        "property_map": {
            "fbp_square_mask_factor": "Factor",
            "fbp_square_mask_invert": "Invert",
            "fbp_square_mask_feather": "Feather",
        },
        "extra_properties": (
            "fbp_square_mask_object", "fbp_square_mask_follow_bounds",
            "fbp_square_mask_show_helper", "fbp_square_mask_lock_to_plane",
        ),
        "object_mask_aware": True, "object_mask_shape": "SQUARE",
        "object_mask_pointer_property": "fbp_square_mask_object",
        "private_group": True, "builtin": True,
        "description": "Mask the layer with an editable square mesh. Move the helper in Object Mode or reshape its vertices in Edit Mode.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_CIRCLE_MASK: {
        "label": "Circle Mask", "icon": "CURVE_NCIRCLE", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Circle_Mask_553",
        "asset_id": "frame_by_plane.shader.circle_mask.553", "enabled_key": "fbp_effect_circle_mask",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out", "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte")),
        "property_map": {
            "fbp_circle_mask_factor": "Factor",
            "fbp_circle_mask_invert": "Invert",
            "fbp_circle_mask_feather": "Feather",
        },
        "extra_properties": (
            "fbp_circle_mask_object", "fbp_circle_mask_follow_bounds",
            "fbp_circle_mask_show_helper", "fbp_circle_mask_lock_to_plane",
        ),
        "object_mask_aware": True, "object_mask_shape": "CIRCLE",
        "object_mask_pointer_property": "fbp_circle_mask_object",
        "private_group": True, "builtin": True,
        "description": "Mask the layer with an editable circular mesh. Move the helper in Object Mode or reshape its vertices in Edit Mode.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_TRIANGLE_MASK: {
        "label": "Triangle Mask", "icon": "MESH_DATA", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Triangle_Mask_553",
        "asset_id": "frame_by_plane.shader.triangle_mask.553", "enabled_key": "fbp_effect_triangle_mask",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out", "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte")),
        "property_map": {
            "fbp_triangle_mask_factor": "Factor",
            "fbp_triangle_mask_invert": "Invert",
            "fbp_triangle_mask_feather": "Feather",
        },
        "extra_properties": (
            "fbp_triangle_mask_object", "fbp_triangle_mask_follow_bounds",
            "fbp_triangle_mask_show_helper", "fbp_triangle_mask_lock_to_plane",
        ),
        "object_mask_aware": True, "object_mask_shape": "TRIANGLE",
        "object_mask_pointer_property": "fbp_triangle_mask_object",
        "private_group": True, "builtin": True,
        "description": "Mask the layer with an editable triangle mesh. Move the helper in Object Mode or reshape its vertices in Edit Mode.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_CLIPPING_MASK: {
        "label": "Clipping Mask", "icon": "AREA_JOIN_DOWN", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Clipping_Mask_6030",
        "asset_id": "frame_by_plane.shader.clipping_mask.6030", "enabled_key": "fbp_effect_clipping_mask",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out", "uv_input_socket": "UV Vector",
        "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte"), ("SOURCE", "Source")),
        "property_map": {
            "fbp_clipping_mask_factor": "Factor",
            "fbp_clipping_mask_invert": "Invert",
            "fbp_clipping_mask_use_source_transform": "Use Source Transform",
            "fbp_clipping_mask_use_camera_projection": "Use Camera Projection",
            "fbp_clipping_mask_uv_offset_x": "UV Offset X",
            "fbp_clipping_mask_uv_offset_y": "UV Offset Y",
            "fbp_clipping_mask_uv_scale_x": "UV Scale X",
            "fbp_clipping_mask_uv_scale_y": "UV Scale Y",
            "fbp_clipping_mask_uv_rotation": "UV Rotation",
        },
        "extra_properties": ("fbp_clipping_mask_source",),
        "mask_source_property": "fbp_clipping_mask_source",
        "mask_source_aware": True, "mask_source_transform_aware": True,
        "track_matte_contract_version": 8,
        "private_group": True, "builtin": True, "layer_feature": True,
        "description": "Clip this layer to the alpha of the image or animated layer directly below it in the same collection.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_IMPORTED_MASK: {
        "label": "Imported Layer Mask", "icon": "NEWFOLDER", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Imported_Mask_593",
        "asset_id": "frame_by_plane.shader.imported_mask.593", "enabled_key": "fbp_effect_imported_mask",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out", "uv_input_socket": "UV Vector",
        "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte"), ("SOURCE", "Source")),
        "property_map": {
            "fbp_imported_mask_factor": "Factor",
            "fbp_imported_mask_invert": "Invert",
        },
        "extra_properties": ("fbp_imported_mask_path",),
        "imported_mask_aware": True,
        "private_group": True, "builtin": True, "layer_feature": True,
        "description": "Use a raster layer mask imported from a PSD or another layered document while keeping factor and inversion editable.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_LAYER_BLEND: {
        "label": "Layer Blend", "icon": "XRAY", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Layer_Blend_593",
        "asset_id": "frame_by_plane.shader.layer_blend.593", "enabled_key": "fbp_effect_layer_blend",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {
            "fbp_layer_blend_factor": "Factor",
        },
        "extra_properties": ("fbp_layer_blend_source", "fbp_layer_blend_mode"),
        "mask_source_property": "fbp_layer_blend_source",
        "mask_source_aware": True,
        "mask_use_socket": "Use Source Sample",
        "private_group": True, "builtin": True, "layer_feature": True,
        "description": "Blend this layer with the image layer directly below it. Principal PSD and Procreate blend modes can be transferred automatically.",
        "category": "2D", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE"),
    },
    FBP_EFFECT_COLOR_MASK: {
        "label": "Color Mask", "icon": "RESTRICT_COLOR_OFF", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Color_Mask_5514",
        "asset_id": "frame_by_plane.shader.color_mask.5514", "enabled_key": "fbp_effect_color_mask",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out",
        "uv_input_socket": "UV Vector", "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte")),
        "property_map": {
            "fbp_color_mask_color": "Target Color",
            "fbp_color_mask_tolerance": "Tolerance",
            "fbp_color_mask_softness": "Softness",
            "fbp_color_mask_factor": "Factor",
            "fbp_color_mask_invert": "Invert",
        },
        "private_group": True, "image_aware": True, "builtin": True,
        "description": "Build a mask from pixels close to a selected source color.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE"),
    },
    FBP_EFFECT_LUMINANCE_MASK: {
        "label": "Luminance Mask", "icon": "LIGHT", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Luminance_Mask_601",
        "asset_id": "frame_by_plane.shader.luminance_mask.601", "enabled_key": "fbp_effect_luminance_mask",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out",
        "uv_input_socket": "UV Vector", "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte")),
        "property_map": {
            "fbp_luminance_mask_minimum": "Minimum",
            "fbp_luminance_mask_maximum": "Maximum",
            "fbp_luminance_mask_softness": "Softness",
            "fbp_luminance_mask_factor": "Factor",
            "fbp_luminance_mask_invert": "Invert",
        },
        "private_group": True, "image_aware": True, "builtin": True,
        "description": "Build a mask from a selectable luminance range in the current image or sequence.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE"),
    },
    FBP_EFFECT_CHANNEL_MASK: {
        "label": "Channel Mask", "icon": "MOD_ARRAY", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Channel_Mask_603",
        "asset_id": "frame_by_plane.shader.channel_mask.603", "enabled_key": "fbp_effect_channel_mask",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out",
        "uv_input_socket": "UV Vector", "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte")),
        "property_map": {
            "fbp_channel_mask_channel": "Channel",
            "fbp_channel_mask_minimum": "Minimum",
            "fbp_channel_mask_maximum": "Maximum",
            "fbp_channel_mask_softness": "Softness",
            "fbp_channel_mask_factor": "Factor",
            "fbp_channel_mask_invert": "Invert",
        },
        "private_group": True, "image_aware": True, "builtin": True,
        "description": "Build a mask from the red, green, blue, alpha or luminance channel of the current image or sequence.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE"),
    },
    FBP_EFFECT_GRADIENT_MASK: {
        "label": "Gradient Mask", "icon": "NODE_TEXTURE", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Gradient_Mask_5513",
        "asset_id": "frame_by_plane.shader.gradient_mask.5513", "enabled_key": "fbp_effect_gradient_mask",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out",
        "uv_input_socket": "UV Vector", "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte")),
        "property_map": {
            "fbp_gradient_mask_type": "Type",
            "fbp_gradient_mask_center_x": "Center X",
            "fbp_gradient_mask_center_y": "Center Y",
            "fbp_gradient_mask_scale": "Scale",
            "fbp_gradient_mask_angle": "Angle",
            "fbp_gradient_mask_position": "Position",
            "fbp_gradient_mask_feather": "Feather",
            "fbp_gradient_mask_factor": "Factor",
            "fbp_gradient_mask_invert": "Invert",
        },
        "builtin": True,
        "description": "Create a linear or radial procedural mask in the layer UV space.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_NOISE_MASK: {
        "label": "Noise Mask", "icon": "FORCE_TURBULENCE", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Noise_Mask_5513",
        "asset_id": "frame_by_plane.shader.noise_mask.5513", "enabled_key": "fbp_effect_noise_mask",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out",
        "uv_input_socket": "UV Vector", "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte")),
        "property_map": {
            "fbp_noise_mask_scale": "Scale",
            "fbp_noise_mask_detail": "Detail",
            "fbp_noise_mask_roughness": "Roughness",
            "fbp_noise_mask_threshold": "Threshold",
            "fbp_noise_mask_softness": "Softness",
            "fbp_noise_mask_seed": "Seed",
            "fbp_noise_mask_factor": "Factor",
            "fbp_noise_mask_invert": "Invert",
        },
        "evolve_property": "fbp_noise_mask_seed", "evolve_amount": 1.0, "supports_seed": True,
        "builtin": True,
        "description": "Create an animatable procedural noise mask in the layer UV space.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
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
        "label": "Hue & Saturation", "icon": "IMAGE_RGB", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Hue_Saturation",), "canonical_name": "FBP_SH_Hue_Saturation_450",
        "asset_id": "frame_by_plane.shader.hue_saturation.450", "enabled_key": "fbp_effect_hue_saturation",
        "input_socket": "Color In", "output_socket": "Color Out",
        "property_map": {"fbp_hue_saturation_hue": "Hue", "fbp_hue_saturation_saturation": "Saturation", "fbp_hue_saturation_value": "Value"},
        "evolve_property": "fbp_hue_saturation_hue", "evolve_amount": 0.5, "supports_seed": True,
    },
    FBP_EFFECT_WHITE_BALANCE: {
        "label": "White Balance", "icon": "MOD_WHITE_BALANCE", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_White_Balance_6019",
        "asset_id": "frame_by_plane.shader.white_balance.6019", "enabled_key": "fbp_effect_white_balance",
        "input_socket": "Color In", "output_socket": "Color Out",
        "required_input_sockets": ("Temperature", "Tint", "Factor"),
        "property_map": {
            "fbp_white_balance_temperature": "Temperature",
            "fbp_white_balance_tint": "Tint",
            "fbp_white_balance_factor": "Factor",
        },
        "builtin": True,
    },
    FBP_EFFECT_CURVES: {
        "label": "Curves", "icon": "FORCE_HARMONIC", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Curves_6019",
        "asset_id": "frame_by_plane.shader.curves.6019", "enabled_key": "fbp_effect_curves",
        "input_socket": "Color In", "output_socket": "Color Out",
        "required_input_sockets": ("Factor",),
        "property_map": {"fbp_curves_factor": "Factor"},
        "private_group": True, "rig_private_group": True, "curve_mapping_role": "COLOR_CURVES",
        "builtin": True,
    },
    FBP_EFFECT_BRIGHTNESS_CONTRAST: {
        "label": "Brightness & Contrast", "icon": "IMAGE_RGB_ALPHA", "kind": "SHADER", "stage": "COLOR",
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
        "label": "Threshold", "icon": "NODE_TEXTURE", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Threshold",), "canonical_name": "FBP_SH_Threshold_450",
        "asset_id": "frame_by_plane.shader.threshold.450", "enabled_key": "fbp_effect_threshold",
        "input_socket": "Color In", "output_socket": "Color Out",
        "property_map": {"fbp_threshold_value": "Threshold"},
    },
    FBP_EFFECT_COLOR_ISOLATE: {
        "label": "Color Isolate", "icon": "TRACKER", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Color_Isolate",), "canonical_name": "FBP_SH_Color_Isolate_6026",
        "asset_id": "frame_by_plane.shader.color_isolate.6026", "enabled_key": "fbp_effect_color_isolate",
        "input_socket": "Color In", "output_socket": "Color Out",
        "required_input_sockets": ("Target Color", "Tolerance", "Falloff", "Factor"),
        "property_map": {
            "fbp_color_isolate_target": "Target Color",
            "fbp_color_isolate_tolerance": "Tolerance",
            "fbp_color_isolate_falloff": "Falloff",
            "fbp_color_isolate_factor": "Factor",
        },
        "builtin": True,
    },
    FBP_EFFECT_DUOTONE: {
        "label": "Duotone", "icon": "MOD_TINT", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Duotone",), "canonical_name": "FBP_SH_Duotone_445",
        "asset_id": "frame_by_plane.shader.duotone.445", "enabled_key": "fbp_effect_duotone",
        "input_socket": "Color In", "output_socket": "Color Out",
        "property_map": {"fbp_duotone_shadows": "Shadows Tone", "fbp_duotone_highlights": "Highlights Tone"},
    },
    FBP_EFFECT_RECOLOR: {
        "label": "Recolor", "icon": "COLOR", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Recolor_570",
        "asset_id": "frame_by_plane.shader.recolor.570", "enabled_key": "fbp_effect_recolor",
        "input_socket": "Color In", "output_socket": "Color Out",
        "private_group": True, "rig_private_group": True, "builtin": True,
        "required_input_sockets": ("Factor",),
        "property_map": {"fbp_recolor_factor": "Factor"},
        "color_ramp_role": "RECOLOR",
    },
    FBP_EFFECT_GRAIN: {
        "label": "Grain", "icon": "RENDER_STILL", "kind": "SHADER", "stage": "COLOR",
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
        "label": "Gradient", "icon": "NODE_TEXTURE", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_2D_Gradient_Light", "FBP_SH_Gradient_Light_570"), "canonical_name": "FBP_SH_Gradient_Light_6025",
        "asset_id": "frame_by_plane.shader.gradient_light.6025", "enabled_key": "fbp_effect_gradient_light",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "private_group": True, "rig_private_group": True, "builtin": True,
        "required_input_sockets": ("Center X", "Center Y", "Light Angle", "Light Position", "Strength"),
        "property_map": {
            "fbp_gradient_light_center_x": "Center X",
            "fbp_gradient_light_center_y": "Center Y",
            "fbp_gradient_light_angle": "Light Angle",
            "fbp_gradient_shadow_position": "Light Position",
            "fbp_gradient_light_strength": "Strength",
        },
        "extra_properties": ("fbp_gradient_softness", "fbp_gradient_shadow_color"),
        "color_ramp_role": "GRADIENT_LIGHT",
    },
    FBP_EFFECT_RIM: {
        "label": "Rim", "icon": "MOD_OUTLINE", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_SH_Rim_611", "FBP_SH_Rim_617", "FBP_SH_Rim_6021"), "canonical_name": "FBP_SH_Rim_6022",
        "asset_id": "frame_by_plane.shader.rim.6022", "enabled_key": "fbp_effect_rim",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "image_aware": True, "private_group": True, "builtin": True,
        "performance": "HEAVY",
        "required_input_sockets": ("Use Image Sample", "Width", "Offset X", "Offset Y", "Rotation", "Blur", "Softness", "Intensity", "Rim Color"),
        "property_map": {
            "fbp_rim_width": "Width",
            "fbp_rim_offset_x": "Offset X",
            "fbp_rim_offset_y": "Offset Y",
            "fbp_rim_rotation": "Rotation",
            "fbp_rim_blur": "Blur",
            "fbp_rim_softness": "Softness",
            "fbp_rim_intensity": "Intensity",
            "fbp_rim_color": "Rim Color",
        },
    },
    FBP_EFFECT_SHADOW: {
        "label": "Shadow", "icon": "SHADING_RENDERED", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_SH_Shadow_6046",), "canonical_name": "FBP_SH_Shadow_6047",
        "asset_id": "frame_by_plane.shader.shadow.6047", "enabled_key": "fbp_effect_shadow",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "image_aware": True, "private_group": True, "builtin": True,
        "performance": "MEDIUM",
        "required_input_sockets": (
            "Use Image Sample", "Mode", "Blend Mode", "Offset X", "Offset Y", "Blur", "Opacity", "Shadow Color",
        ),
        "property_map": {
            "fbp_shadow_mode": "Mode",
            "fbp_shadow_blend_mode": "Blend Mode",
            "fbp_shadow_offset_x": "Offset X",
            "fbp_shadow_offset_y": "Offset Y",
            "fbp_shadow_blur": "Blur",
            "fbp_shadow_opacity": "Opacity",
            "fbp_shadow_color": "Shadow Color",
        },
    },
    FBP_EFFECT_GOBO_SHADOWS: {
        "label": "Gobo Shadows", "icon": "LIGHT_SPOT", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Gobo_Shadows",), "canonical_name": "FBP_SH_Gobo_Shadows_445",
        "asset_id": "frame_by_plane.shader.gobo_shadows.445", "enabled_key": "fbp_effect_gobo_shadows",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {"fbp_gobo_pattern_scale": "Pattern Scale", "fbp_gobo_rotation": "Rotation Angle", "fbp_gobo_sharpness": "Sharpness"},
    },
    FBP_EFFECT_CRT_SCANLINES: {
        "label": "Scan-lines", "icon": "ALIGN_JUSTIFY", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_CRT_Scanlines",), "canonical_name": "FBP_SH_CRT_Scanlines_445",
        "asset_id": "frame_by_plane.shader.crt_scanlines.445", "enabled_key": "fbp_effect_crt_scanlines",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {"fbp_crt_line_count": "Line Count", "fbp_crt_opacity": "Opacity"},
    },
    FBP_EFFECT_VIGNETTE: {
        "label": "Vignette", "icon": "CLIPUV_DEHLT", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Vignette",), "canonical_name": "FBP_SH_Vignette_450",
        "asset_id": "frame_by_plane.shader.vignette.450", "enabled_key": "fbp_effect_vignette",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {"fbp_vignette_radius": "Radius", "fbp_vignette_smoothness": "Smoothness", "fbp_vignette_strength": "Strength"},
    },
    FBP_EFFECT_POSTERIZE: {
        "label": "Posterize", "icon": "SHADING_RENDERED", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Posterize",), "canonical_name": "FBP_SH_Posterize_445",
        "asset_id": "frame_by_plane.shader.posterize.445", "enabled_key": "fbp_effect_posterize",
        "input_socket": "Color In", "output_socket": "Color Out", "property_map": {"fbp_posterize_steps": "Color Steps"},
        "evolve_property": "fbp_posterize_steps", "evolve_amount": 8.0, "supports_seed": True,
    },
    FBP_EFFECT_SOLARIZE: {
        "label": "Solarize", "icon": "LIGHT_SUN", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Solarize_611",
        "asset_id": "frame_by_plane.shader.solarize.611", "enabled_key": "fbp_effect_solarize",
        "input_socket": "Color In", "output_socket": "Color Out", "builtin": True,
        "property_map": {
            "fbp_solarize_threshold": "Threshold",
            "fbp_solarize_softness": "Softness",
            "fbp_solarize_factor": "Factor",
        },
    },
    FBP_EFFECT_TRITONE: {
        "label": "Tritone", "icon": "COLOR", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Tritone_611",
        "asset_id": "frame_by_plane.shader.tritone.611", "enabled_key": "fbp_effect_tritone",
        "input_socket": "Color In", "output_socket": "Color Out", "builtin": True,
        "property_map": {
            "fbp_tritone_shadows": "Shadows Tone",
            "fbp_tritone_midtones": "Midtones Tone",
            "fbp_tritone_highlights": "Highlights Tone",
            "fbp_tritone_midpoint": "Midpoint",
            "fbp_tritone_factor": "Factor",
        },
    },
    FBP_EFFECT_FILM_FADE: {
        "label": "Fade", "icon": "MOD_FLUIDSIM", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Film_Fade_604",
        "asset_id": "frame_by_plane.shader.film_fade.604", "enabled_key": "fbp_effect_film_fade",
        "input_socket": "Color In", "output_socket": "Color Out", "builtin": True,
        "property_map": {
            "fbp_film_fade_color": "Fade Color",
            "fbp_film_fade_amount": "Amount",
            "fbp_film_fade_desaturation": "Desaturation",
            "fbp_film_fade_contrast_loss": "Contrast Loss",
        },
    },
    FBP_EFFECT_DIGITAL_NOISE: {
        "label": "Noise", "icon": "RNDCURVE", "kind": "SHADER", "stage": "COLOR",
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
        "label": "Chroma Key", "icon": "FORCE_TEXTURE", "kind": "SHADER", "stage": "COLOR",
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
        "label": "Halftone", "icon": "OUTLINER_DATA_POINTCLOUD", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Halftone_611",
        "asset_id": "frame_by_plane.shader.halftone.611", "enabled_key": "fbp_effect_halftone",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "required_input_sockets": ("Aspect Ratio", "Shape"),
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
        "label": "Dot Matrix", "icon": "LIGHTPROBE_VOLUME", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Dot_Matrix_611",
        "asset_id": "frame_by_plane.shader.dot_matrix.611", "enabled_key": "fbp_effect_dot_matrix",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "required_input_sockets": ("Aspect Ratio", "Shape"),
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
        "label": "Textellation", "icon": "SYNTAX_OFF", "kind": "SHADER", "stage": "COLOR",
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
        "ui_labels": {
            "fbp_ascii_charset": "Character Set",
            "fbp_ascii_character_count": "Character Count",
        },
        "evolve_property": "fbp_ascii_random_seed", "evolve_amount": 1.0,
        "evolve_mode": "SEED_STEP", "supports_seed": True,
        "debug_modes": (("FINAL", "Final"), ("LUMINANCE", "Luminance"), ("GLYPH", "Glyph Index")),
        "debug_socket": "Debug Mode",
        "private_group": True, "image_aware": True, "builtin": True,
    },
    FBP_EFFECT_ASCII: {
        "label": "Ascii", "icon": "CONSOLE", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Ascii_5311",
        "asset_id": "frame_by_plane.shader.ascii.5311", "enabled_key": "fbp_effect_ascii",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "property_map": {
            "fbp_terminal_ascii_scale": "Cell Scale",
            "fbp_terminal_ascii_contrast": "Contrast",
            "fbp_terminal_ascii_invert": "Invert",
            "fbp_terminal_ascii_fill_strength": "Fill Strength",
            "fbp_terminal_ascii_fill_threshold": "Fill Threshold",
            "fbp_terminal_ascii_use_edges": "Use Edges",
            "fbp_terminal_ascii_edge_strength": "Edge Strength",
            "fbp_terminal_ascii_edge_threshold": "Edge Threshold",
            "fbp_terminal_ascii_edge_mix": "Edge Mix",
            "fbp_terminal_ascii_use_source_color": "Use Source Color",
            "fbp_terminal_ascii_foreground": "Foreground",
            "fbp_terminal_ascii_background": "Background",
            "fbp_terminal_ascii_transparent_background": "Transparent Background",
            "fbp_terminal_ascii_seed": "Seed",
        },
        "evolve_property": "fbp_terminal_ascii_seed", "evolve_amount": 1.0,
        "evolve_mode": "SEED_STEP", "supports_seed": True,
        "debug_modes": (("FINAL", "Final"), ("LUMINANCE", "Luminance"), ("EDGES", "Edge Mask")),
        "debug_socket": "Debug Mode",
        "private_group": True, "image_aware": True, "builtin": True,
    },
    FBP_EFFECT_TEXT_MATRIX: {
        "label": "Text Matrix", "icon": "SMALL_CAPS", "kind": "GEOMETRY",
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
        "ui_labels": {
            "fbp_text_matrix_charset": "Character Set",
            "fbp_text_matrix_custom_charset": "Characters",
            "fbp_text_matrix_font": "Font",
            "fbp_text_matrix_background_color": "Background Color",
            "fbp_text_matrix_render_columns": "Render Columns",
            "fbp_text_matrix_render_rows": "Render Rows",
            "fbp_text_matrix_quality": "Quality",
            "fbp_text_matrix_auto_playback_limit": "Playback Limit",
            "fbp_text_matrix_playback_columns": "Playback Columns",
            "fbp_text_matrix_playback_rows": "Playback Rows",
        },
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
    FBP_EFFECT_EXTEND: ("BASE", "LIGHT", "Extend the plane borders while preserving the central image. Edge Pixel clamps, Transparent creates empty canvas for shadows and glows, and Repeat Texture tiles the source."),
    FBP_EFFECT_SOLID_MASK: ("BASE", "LIGHT", "Apply a color tint to the final plane output. Useful for recoloring images, solid planes and gradients."),
    FBP_EFFECT_HUE_SATURATION: ("BASE", "LIGHT", "Adjust hue, saturation and value on the final color output."),
    FBP_EFFECT_WHITE_BALANCE: ("BASE", "LIGHT", "Correct color temperature from cold to warm and tint from green to magenta while preserving alpha."),
    FBP_EFFECT_CURVES: ("BASE", "LIGHT", "Remap RGB values with Blender's native editable Color Curves node."),
    FBP_EFFECT_BRIGHTNESS_CONTRAST: ("BASE", "LIGHT", "Adjust brightness and contrast without rebuilding the source material."),
    FBP_EFFECT_INVERT: ("BASE", "LIGHT", "Invert the final color output. Factor allows partial inversion."),
    FBP_EFFECT_THRESHOLD: ("BASE", "LIGHT", "Convert luminance into a hard black-and-white threshold."),
    FBP_EFFECT_COLOR_ISOLATE: ("BASE", "LIGHT", "Keep a selected color range and suppress the remaining colors."),
    FBP_EFFECT_DUOTONE: ("BASE", "LIGHT", "Map shadows and highlights to two editable colors."),
    FBP_EFFECT_RECOLOR: ("2D", "LIGHT", "Map source luminance through an editable Color Ramp while preserving the original alpha."),
    FBP_EFFECT_CHROMA_KEY: ("BASE", "MEDIUM", "Remove a selected color and generate transparency. Softness cleans edges; Despill reduces the key color around the subject."),
    FBP_EFFECT_UV_DISTORTION: ("2D", "MEDIUM", "Distort UV coordinates with procedural turbulence. Animated or high-frequency distortion can cost viewport performance."),
    FBP_EFFECT_PIXELATE: ("2D", "LIGHT", "Reduce detail into adjustable pixel blocks. Square Pixels compensates for the plane aspect ratio and is enabled by default."),
    FBP_EFFECT_SWIRL: ("2D", "LIGHT", "Twist UV coordinates around an editable center with radius, angle and blend controls."),
    FBP_EFFECT_BULGE_PINCH: ("2D", "LIGHT", "Create a local bulge or pinch around an editable center while preserving the surrounding image."),
    FBP_EFFECT_LENS_WARP: ("2D", "LIGHT", "Apply global barrel or pincushion lens distortion with center and zoom controls."),
    FBP_EFFECT_WAVE_WARP: ("2D", "LIGHT", "Displace UVs with an animatable directional sine wave."),
    FBP_EFFECT_RIPPLE_DISTORTION: ("2D", "LIGHT", "Create concentric animated UV ripples with editable radius and falloff."),
    FBP_EFFECT_KALEIDOSCOPE: ("2D", "MEDIUM", "Fold the source around a configurable number of mirrored radial segments."),
    FBP_EFFECT_HEX_PIXELATE: ("2D", "LIGHT", "Sample the source on a staggered hexagonal-style grid with editable resolution and rotation."),
    FBP_EFFECT_MOSAIC_JITTER: ("2D", "MEDIUM", "Break the source into cells and randomly offset each sample for an animatable mosaic or glitch treatment."),
    FBP_EFFECT_DEPTH_BLUR: ("2D", "HEAVY", "Blur the animated source image with alpha-safe sampling. Manual mode uses a fixed radius; Depth mode increases blur away from the configured camera focus distance."),
    FBP_EFFECT_TRIANGLE_BLUR: ("2D", "HEAVY", "Apply a fast alpha-safe triangular blur with adjustable radius and sample count."),
    FBP_EFFECT_TILT_SHIFT: ("2D", "HEAVY", "Keep an editable horizontal focus band sharp while progressively blurring the surrounding image."),
    FBP_EFFECT_UNSHARP_MASK: ("2D", "HEAVY", "Sharpen local image detail by subtracting a small source blur from the original image."),
    FBP_EFFECT_EDGE_DETECT: ("2D", "HEAVY", "Extract source-image edges with a Sobel 3×3 kernel, adjustable width, smooth threshold, strength and color."),
    FBP_EFFECT_SMOOTH_TOON: ("2D", "LIGHT", "Quantize image colors into editable tonal bands with true softened transitions around each band boundary."),
    FBP_EFFECT_ADAPTIVE_THRESHOLD: ("2D", "HEAVY", "Create an invertible locally adaptive black-and-white treatment using a weighted eight-neighbor luminance average."),
    FBP_EFFECT_FALSE_COLOR: ("2D", "LIGHT", "Map source luminance between editable dark and light colors."),
    FBP_EFFECT_CHROMATIC_ABERRATION: ("2D", "HEAVY", "Offset red and blue source channels in opposite directions for lens-style color fringing."),
    FBP_EFFECT_INK: ("2D", "HEAVY", "Create configurable ink lines over a paper or partially preserved-color base using Sobel edge extraction."),
    FBP_EFFECT_EDGE_WORK: ("2D", "HEAVY", "Generate broader illustrated edges from the difference between two local luminance scales."),
    FBP_EFFECT_PENCIL_SKETCH: ("2D", "HEAVY", "Build a pencil-style sketch from local luminance contrast with editable graphite, paper and color retention."),
    FBP_EFFECT_POSTER_EDGES: ("2D", "HEAVY", "Combine smooth tonal posterization with Sobel outlines for a graphic poster treatment."),
    FBP_EFFECT_CROSSHATCH: ("2D", "MEDIUM", "Shade darker image regions with up to four aspect-corrected procedural hatch directions."),
    FBP_EFFECT_EMBOSS: ("2D", "HEAVY", "Create directional raised or engraved relief by comparing opposite source-image samples."),
    FBP_EFFECT_GAUSSIAN_BLUR: ("2D", "HEAVY", "Apply an adjustable three-to-twenty-five-tap alpha-safe Gaussian blur with independent horizontal and vertical radii measured in source-image pixels."),
    FBP_EFFECT_DIRECTIONAL_BLUR: ("2D", "HEAVY", "Apply an alpha-safe motion-style blur along an editable angle and distance measured in source-image pixels."),
    FBP_EFFECT_SQUARE_MASK: ("MASK", "LIGHT", "Mask the layer with an editable rectangular helper. Transform it in Object Mode or reshape its vertices in Edit Mode."),
    FBP_EFFECT_CIRCLE_MASK: ("MASK", "LIGHT", "Mask the layer with an editable circular helper. Transform it in Object Mode or reshape its vertices in Edit Mode."),
    FBP_EFFECT_TRIANGLE_MASK: ("MASK", "LIGHT", "Mask the layer with an editable triangular helper. Transform it in Object Mode or reshape its vertices in Edit Mode."),
    FBP_EFFECT_CLIPPING_MASK: ("MASK", "LIGHT", "Clip this layer to the alpha of the layer directly below it in the Layer List."),
    FBP_EFFECT_IMPORTED_MASK: ("MASK", "LIGHT", "Apply an imported raster layer mask while keeping factor and inversion editable."),
    FBP_EFFECT_LAYER_BLEND: ("2D", "LIGHT", "Blend the current layer against the image layer directly below it using a principal PSD or Procreate blend mode."),
    FBP_EFFECT_COLOR_MASK: ("MASK", "LIGHT", "Select pixels close to a chosen color and use the result as a layer or per-effect mask."),
    FBP_EFFECT_LUMINANCE_MASK: ("MASK", "LIGHT", "Select a luminance interval from the current image or sequence and use it as a layer or per-effect mask."),
    FBP_EFFECT_CHANNEL_MASK: ("MASK", "LIGHT", "Select a value interval from the red, green, blue, alpha or luminance channel of the current image or sequence."),
    FBP_EFFECT_GRADIENT_MASK: ("MASK", "LIGHT", "Create a linear or radial procedural mask with editable center, angle, scale and feather."),
    FBP_EFFECT_NOISE_MASK: ("MASK", "LIGHT", "Create an animatable procedural noise mask with threshold and softness controls."),
    FBP_EFFECT_ALPHA_MATTE: ("MASK", "LIGHT", "Multiply the layer alpha by another Frame By Plane image or sequence alpha, using normalized UVs or the live source-plane transform."),
    FBP_EFFECT_LUMA_MATTE: ("MASK", "LIGHT", "Convert another Frame By Plane image or sequence to luminance and use it as a normalized or spatially transformed track matte."),
    FBP_EFFECT_GRAIN: ("2D", "LIGHT", "Add soft monochromatic film-like grain. Use Digital Noise for colored high-ISO sensor noise."),
    FBP_EFFECT_DIGITAL_NOISE: ("2D", "MEDIUM", "Simulate high-ISO digital sensor noise with separate luminance and chromatic components. Strong animated chroma noise may be expensive."),
    FBP_EFFECT_HALFTONE: ("2D", "MEDIUM", "Convert luminance into a printed-dot pattern. Small cells can increase shader cost and cause viewport aliasing."),
    FBP_EFFECT_DOT_MATRIX: ("2D", "MEDIUM", "Rebuild the source image as cell-centered dots whose radius and brightness follow image luminance. Brightness Response reshapes the luminance-to-size curve; optional randomness only modulates the image-driven result."),
    FBP_EFFECT_ASCII_MATRIX: ("2D", "HEAVY", "Replace the animated FBP image or sequence with density-sorted atlas glyphs. Partial alpha is read as lighter luminance, total transparency is removed, and source-pixel color is preserved by default."),
    FBP_EFFECT_ASCII: ("2D", "HEAVY", "Convert the source into terminal-style ASCII using separate fill and directional edge glyph atlases. Fill density and edge extraction can be tuned independently."),
    FBP_EFFECT_TEXT_MATRIX: ("3D", "VERY_HEAVY", "Generate real vector text from the animated source. Geometry Nodes maps alpha-aware luminance to density-sorted glyphs and can preserve one sampled source color per cell."),
    FBP_EFFECT_PAPER_FIBERS: ("2D", "MEDIUM", "Overlay procedural paper fibers on the final color."),
    FBP_EFFECT_GRADIENT_LIGHT: ("2D", "LIGHT", "Multiply the source with a directional editable Color Ramp."),
    FBP_EFFECT_RIM: ("2D", "MEDIUM", "Create a soft colored rim from the animated image alpha or, for procedural planes, from the plane border."),
    FBP_EFFECT_SHADOW: ("2D", "MEDIUM", "Create an alpha-safe offset inner or outer shadow with editable color blending."),
    FBP_EFFECT_GOBO_SHADOWS: ("2D", "MEDIUM", "Project a procedural gobo-like shadow pattern across the plane."),
    FBP_EFFECT_CRT_SCANLINES: ("2D", "LIGHT", "Add CRT-style horizontal scanlines."),
    FBP_EFFECT_VIGNETTE: ("2D", "LIGHT", "Darken the image edges with an adjustable vignette."),
    FBP_EFFECT_POSTERIZE: ("2D", "LIGHT", "Reduce the number of color levels for a graphic posterized look."),
    FBP_EFFECT_SOLARIZE: ("2D", "LIGHT", "Invert highlights above an adjustable luminance threshold, with a soft transition and blend factor."),
    FBP_EFFECT_TRITONE: ("2D", "LIGHT", "Map source luminance across editable shadow, midtone and highlight colors."),
    FBP_EFFECT_FILM_FADE: ("2D", "LIGHT", "Create a faded-film look with editable tint, desaturation and contrast loss."),
    FBP_EFFECT_MESH_WIGGLE: ("3D", "MEDIUM", "Deform the plane with animated procedural noise. High subdivision values may slow playback."),
    FBP_EFFECT_STOP_MOTION_CRUMPLE: ("3D", "HEAVY", "Create stepped, stop-motion-style surface crumpling. Resolution has a strong impact on viewport performance."),
    FBP_EFFECT_WIND_BENDER: ("3D", "MEDIUM", "Combine sway, flowing waves and ripple deformation with shared border or vertex-group pinning that follows the evaluated Crop and Extend mesh."),
    FBP_EFFECT_CUTOUT_OUTLINE: ("3D", "HEAVY", "Generate a material outline from the animated image alpha while preserving the original plane geometry. Alpha detail has separate viewport, playback and render quality."),
    FBP_EFFECT_CAMERA_SCALE_LOCK: ("3D", "LIGHT", "Keep the plane at a stable apparent size while camera-space depth, focal length or sensor width changes."),
    FBP_EFFECT_CAMERA_BILLBOARD: ("3D", "LIGHT", "Track the complete Frame By Plane rig toward the active scene camera while preserving the rig pivot and layer dimensions."),
    FBP_EFFECT_MIRROR: ("3D", "LIGHT", "Mirror the plane geometry horizontally, vertically or on both axes around the rig pivot."),
    FBP_EFFECT_THICKNESS: ("3D", "HEAVY", "Extrude the animated alpha silhouette into a closed volume. The outer cap keeps the plane texture, while side faces can use a solid material or the animated plane colors."),
    FBP_EFFECT_INFINITE_ROTATION: ("3D", "LIGHT", "Continuously rotate the plane with optional stepped motion."),
    FBP_EFFECT_FELT_FUZZ: ("3D", "VERY_HEAVY", "Generate alpha-aware felt fibers. Render density and subdivisions can be extremely expensive."),
    FBP_EFFECT_LATTICE: ("3D", "LIGHT", "Deform the linked plane through a planar control grid with one selectable point per intersection, or bake its 3D perspective into a camera-parallel surface while preserving the same camera appearance."),
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
        and not _definition.get("mask_source_aware")
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
    "UV": (FBP_EFFECT_UV_DISTORTION, FBP_EFFECT_PIXELATE, FBP_EFFECT_SWIRL, FBP_EFFECT_BULGE_PINCH, FBP_EFFECT_LENS_WARP, FBP_EFFECT_WAVE_WARP, FBP_EFFECT_RIPPLE_DISTORTION, FBP_EFFECT_KALEIDOSCOPE, FBP_EFFECT_HEX_PIXELATE, FBP_EFFECT_MOSAIC_JITTER),
    "MASK": (
        FBP_EFFECT_CLIPPING_MASK, FBP_EFFECT_IMPORTED_MASK, FBP_EFFECT_ALPHA_MATTE, FBP_EFFECT_LUMA_MATTE,
        FBP_EFFECT_COLOR_MASK, FBP_EFFECT_LUMINANCE_MASK, FBP_EFFECT_CHANNEL_MASK, FBP_EFFECT_GRADIENT_MASK, FBP_EFFECT_NOISE_MASK,
        FBP_EFFECT_SQUARE_MASK, FBP_EFFECT_CIRCLE_MASK, FBP_EFFECT_TRIANGLE_MASK,
    ),
    "COLOR": (
        FBP_EFFECT_LAYER_BLEND, FBP_EFFECT_DEPTH_BLUR, FBP_EFFECT_GAUSSIAN_BLUR, FBP_EFFECT_DIRECTIONAL_BLUR, FBP_EFFECT_TRIANGLE_BLUR, FBP_EFFECT_TILT_SHIFT, FBP_EFFECT_UNSHARP_MASK, FBP_EFFECT_EDGE_DETECT, FBP_EFFECT_INK, FBP_EFFECT_EDGE_WORK, FBP_EFFECT_PENCIL_SKETCH, FBP_EFFECT_POSTER_EDGES, FBP_EFFECT_CROSSHATCH, FBP_EFFECT_EMBOSS, FBP_EFFECT_ADAPTIVE_THRESHOLD, FBP_EFFECT_CHROMATIC_ABERRATION, FBP_EFFECT_CHROMA_KEY, FBP_EFFECT_SOLID_MASK, FBP_EFFECT_HUE_SATURATION,
        FBP_EFFECT_WHITE_BALANCE, FBP_EFFECT_CURVES, FBP_EFFECT_BRIGHTNESS_CONTRAST, FBP_EFFECT_INVERT, FBP_EFFECT_THRESHOLD,
        FBP_EFFECT_COLOR_ISOLATE, FBP_EFFECT_DUOTONE, FBP_EFFECT_RECOLOR, FBP_EFFECT_HALFTONE,
        FBP_EFFECT_DOT_MATRIX, FBP_EFFECT_ASCII_MATRIX, FBP_EFFECT_ASCII, FBP_EFFECT_GRAIN,
        FBP_EFFECT_DIGITAL_NOISE,
        FBP_EFFECT_PAPER_FIBERS, FBP_EFFECT_GRADIENT_LIGHT, FBP_EFFECT_RIM, FBP_EFFECT_SHADOW, FBP_EFFECT_GOBO_SHADOWS,
        FBP_EFFECT_CRT_SCANLINES, FBP_EFFECT_VIGNETTE, FBP_EFFECT_POSTERIZE,
        FBP_EFFECT_SOLARIZE, FBP_EFFECT_TRITONE, FBP_EFFECT_FILM_FADE, FBP_EFFECT_SMOOTH_TOON, FBP_EFFECT_FALSE_COLOR,
    ),
}

FBP_BASE_EFFECT_MENU_ORDER = (
    FBP_EFFECT_CROP, FBP_EFFECT_EXTEND, FBP_EFFECT_HUE_SATURATION,
    FBP_EFFECT_WHITE_BALANCE, FBP_EFFECT_BRIGHTNESS_CONTRAST, FBP_EFFECT_CURVES,
    FBP_EFFECT_SOLID_MASK, FBP_EFFECT_DUOTONE, FBP_EFFECT_TRITONE, FBP_EFFECT_RECOLOR,
    FBP_EFFECT_VIGNETTE, FBP_EFFECT_GRADIENT_LIGHT, FBP_EFFECT_RIM, FBP_EFFECT_SHADOW,
    FBP_EFFECT_CHROMA_KEY, FBP_EFFECT_INVERT, FBP_EFFECT_UNSHARP_MASK,
    FBP_EFFECT_THRESHOLD, FBP_EFFECT_COLOR_ISOLATE,
)
FBP_3D_EFFECT_MENU_ORDER = (
    FBP_EFFECT_CAMERA_SCALE_LOCK, FBP_EFFECT_CAMERA_BILLBOARD, FBP_EFFECT_MIRROR,
    FBP_EFFECT_LATTICE, FBP_EFFECT_MESH_WIGGLE, FBP_EFFECT_STOP_MOTION_CRUMPLE,
    FBP_EFFECT_WIND_BENDER, FBP_EFFECT_INFINITE_ROTATION, FBP_EFFECT_CUTOUT_OUTLINE,
    FBP_EFFECT_THICKNESS, FBP_EFFECT_FELT_FUZZ, FBP_EFFECT_TEXT_MATRIX,
)

# Related effects keep their stable internal IDs but appear as one user-facing
# family with an icon-free variant dropdown in the active effect settings.
FBP_EFFECT_FAMILIES = {
    "COLORIZE": {
        "label": "Colorize", "icon": "BRUSH_DATA", "default": FBP_EFFECT_SOLID_MASK,
        "variants": (
            (FBP_EFFECT_SOLID_MASK, "One Color"),
            (FBP_EFFECT_DUOTONE, "Duotone"),
            (FBP_EFFECT_FALSE_COLOR, "False Color"),
            (FBP_EFFECT_TRITONE, "Tritone"),
            (FBP_EFFECT_RECOLOR, "Color Ramp"),
        ),
    },
    "DIRECTIONAL_BLUR": {
        "label": "Directional Blur", "icon": "PROP_PROJECTED", "default": FBP_EFFECT_DIRECTIONAL_BLUR,
        "variants": (
            (FBP_EFFECT_DIRECTIONAL_BLUR, "Default"),
            (FBP_EFFECT_TILT_SHIFT, "Tilt Shift"),
        ),
    },
    "PIXELATE_MOSAIC": {
        "label": "Pixelate & Mosaic", "icon": "ALIASED", "default": FBP_EFFECT_PIXELATE,
        "variants": (
            (FBP_EFFECT_PIXELATE, "Pixelate"),
            (FBP_EFFECT_HEX_PIXELATE, "Hexagonal"),
            (FBP_EFFECT_MOSAIC_JITTER, "Mosaic Jitter"),
        ),
    },
    "POSTERIZE": {
        "label": "Posterize", "icon": "SHADING_RENDERED", "default": FBP_EFFECT_POSTERIZE,
        "variants": (
            (FBP_EFFECT_POSTERIZE, "Posterize"),
            (FBP_EFFECT_SMOOTH_TOON, "Smooth Toon"),
        ),
    },
    "EDGE": {
        "label": "Edge", "icon": "MOD_DASH", "default": FBP_EFFECT_EDGE_DETECT,
        "variants": (
            (FBP_EFFECT_EDGE_DETECT, "Detect"),
            (FBP_EFFECT_EDGE_WORK, "Work"),
            (FBP_EFFECT_POSTER_EDGES, "Poster"),
            (FBP_EFFECT_ADAPTIVE_THRESHOLD, "Threshold"),
        ),
    },
    "STYLIZE": {
        "label": "Stylize", "icon": "MESH_MONKEY", "default": FBP_EFFECT_INK,
        "variants": (
            (FBP_EFFECT_INK, "Ink"),
            (FBP_EFFECT_PENCIL_SKETCH, "Sketch"),
        ),
    },
    "WAVE": {
        "label": "Wave", "icon": "MOD_OCEAN", "default": FBP_EFFECT_WAVE_WARP,
        "variants": (
            (FBP_EFFECT_WAVE_WARP, "Linear"),
            (FBP_EFFECT_RIPPLE_DISTORTION, "Circle"),
        ),
    },
}

FBP_EFFECT_FAMILY_BY_EFFECT = {
    effect_id: family_id
    for family_id, family in FBP_EFFECT_FAMILIES.items()
    for effect_id, _variant_label in family["variants"]
}
FBP_EFFECT_VARIANT_LABELS = {
    effect_id: variant_label
    for family in FBP_EFFECT_FAMILIES.values()
    for effect_id, variant_label in family["variants"]
}


def fbp_effect_family_id(effect_id):
    return FBP_EFFECT_FAMILY_BY_EFFECT.get(fbp_normalize_effect_id(effect_id), "")


def fbp_effect_family_definition(family_or_effect_id):
    key = str(family_or_effect_id or "").upper()
    family_id = key if key in FBP_EFFECT_FAMILIES else fbp_effect_family_id(key)
    return FBP_EFFECT_FAMILIES.get(family_id, {})


def fbp_effect_variant_label(effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    definition = FBP_EFFECT_REGISTRY.get(effect_id, {})
    return str(
        FBP_EFFECT_VARIANT_LABELS.get(effect_id)
        or definition.get("label", effect_id)
        or effect_id
    )


for _family_id, _family in FBP_EFFECT_FAMILIES.items():
    for _effect_id, _variant_label in _family["variants"]:
        _definition = FBP_EFFECT_REGISTRY.get(_effect_id)
        if _definition is None:
            continue
        _definition["family_id"] = _family_id
        _definition["family_label"] = _family["label"]
        _definition["variant_label"] = _variant_label

# Add-menu sections and explicit column grouping mirror the supplied effect list.
# Each inner tuple is one visual column; short sections may share a column.
FBP_IMAGE_EFFECT_MENU_SECTIONS = (
    ("UTILITY", "TOOL_SETTINGS", (
        FBP_EFFECT_CROP, FBP_EFFECT_EXTEND, FBP_EFFECT_HUE_SATURATION,
        FBP_EFFECT_WHITE_BALANCE, FBP_EFFECT_BRIGHTNESS_CONTRAST, FBP_EFFECT_CURVES,
        "FAMILY:COLORIZE", FBP_EFFECT_VIGNETTE,
    )),
    ("Light", "OUTLINER_OB_LIGHT", (FBP_EFFECT_GRADIENT_LIGHT, FBP_EFFECT_RIM, FBP_EFFECT_SHADOW)),
    ("Magic", "SHADERFX", (
        FBP_EFFECT_CHROMA_KEY, FBP_EFFECT_INVERT, FBP_EFFECT_UNSHARP_MASK,
        FBP_EFFECT_THRESHOLD, FBP_EFFECT_COLOR_ISOLATE,
    )),
    ("BLUR", "ONIONSKIN_ON", (
        FBP_EFFECT_GAUSSIAN_BLUR, "FAMILY:DIRECTIONAL_BLUR",
        FBP_EFFECT_DEPTH_BLUR, FBP_EFFECT_TRIANGLE_BLUR,
    )),
    ("Digital", "IMAGE_BACKGROUND", (
        "FAMILY:PIXELATE_MOSAIC", FBP_EFFECT_CHROMATIC_ABERRATION,
        FBP_EFFECT_DIGITAL_NOISE, FBP_EFFECT_CRT_SCANLINES,
    )),
    ("Grid", "MESH_GRID", (
        FBP_EFFECT_DOT_MATRIX, FBP_EFFECT_HALFTONE, FBP_EFFECT_ASCII_MATRIX, FBP_EFFECT_ASCII,
    )),
    ("Film", "RENDER_STILL", (
        FBP_EFFECT_SOLARIZE, FBP_EFFECT_FILM_FADE, FBP_EFFECT_GRAIN, FBP_EFFECT_PAPER_FIBERS,
    )),
    ("Creative", "BRUSHES_ALL", (
        FBP_EFFECT_KALEIDOSCOPE, "FAMILY:POSTERIZE", "FAMILY:EDGE",
        "FAMILY:STYLIZE", FBP_EFFECT_EMBOSS,
    )),
    ("Deform", "OUTLINER_OB_SURFACE", (
        FBP_EFFECT_UV_DISTORTION, FBP_EFFECT_SWIRL, FBP_EFFECT_BULGE_PINCH,
        FBP_EFFECT_LENS_WARP, "FAMILY:WAVE",
    )),
)
FBP_IMAGE_EFFECT_MENU_COLUMNS = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
)

FBP_MASK_EFFECT_MENU_SECTIONS = (
    ("Shape", "SURFACE_NCURVE", (FBP_EFFECT_SQUARE_MASK, FBP_EFFECT_CIRCLE_MASK, FBP_EFFECT_TRIANGLE_MASK)),
    ("Nodes", "NODE_INSERT_ON", (
        FBP_EFFECT_COLOR_MASK, FBP_EFFECT_LUMINANCE_MASK, FBP_EFFECT_CHANNEL_MASK,
        FBP_EFFECT_GRADIENT_MASK, FBP_EFFECT_NOISE_MASK,
    )),
    ("Advanced", "SEQ_STRIP_MODIFIER", (
        FBP_EFFECT_IMPORTED_MASK, FBP_EFFECT_ALPHA_MATTE, FBP_EFFECT_LUMA_MATTE,
    )),
    ("LAYER INTERACTION", "MOD_MASK", (FBP_EFFECT_CLIPPING_MASK, "LAYER_BLEND_CONTROL")),
)
FBP_MASK_EFFECT_MENU_COLUMNS = ((0,), (1,), (2, 3))

FBP_MESH_EFFECT_MENU_SECTIONS = (
    ("CAMERA & LAYOUT", "CAMERA_DATA", (
        FBP_EFFECT_CAMERA_SCALE_LOCK, FBP_EFFECT_CAMERA_BILLBOARD, FBP_EFFECT_MIRROR,
    )),
    ("Stop Motion", "WORLD", (
        FBP_EFFECT_LATTICE, FBP_EFFECT_MESH_WIGGLE, FBP_EFFECT_STOP_MOTION_CRUMPLE,
        FBP_EFFECT_WIND_BENDER, FBP_EFFECT_INFINITE_ROTATION,
    )),
    ("Creative", "MONKEY", (
        FBP_EFFECT_CUTOUT_OUTLINE, FBP_EFFECT_THICKNESS, FBP_EFFECT_FELT_FUZZ, FBP_EFFECT_TEXT_MATRIX,
    )),
)
FBP_MESH_EFFECT_MENU_COLUMNS = ((0,), (1,), (2,))


def fbp_normalize_effect_id(effect_id):
    """Return the stable string identifier used by registry and stack storage."""
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
    except FBP_DATA_ERRORS:
        return "IMAGE"

def _fbp_rig_has_mesh_plane(rig):
    """Return whether ``rig`` owns one unambiguous mesh plane.

    Do not rely only on ``fbp_plane_target`` or direct parenting. During Undo,
    duplication, regression-scene generation and migration Blender can briefly
    preserve only the owner metadata. This read-only resolver mirrors the more
    complete repair path used by the Lattice implementation.
    """
    if not rig:
        return False
    owner_name = str(getattr(rig, "name", "") or "")
    try:
        plane = getattr(rig, "fbp_plane_target", None)
        if plane is not None and str(getattr(plane, "type", "") or "") == "MESH":
            return True
    except FBP_DATA_ERRORS:
        pass

    tagged = []
    fallback = []
    try:
        for obj in tuple(getattr(bpy.data, "objects", ()) or ()):
            if str(getattr(obj, "type", "") or "") != "MESH":
                continue
            is_parented = getattr(obj, "parent", None) is rig
            try:
                stored_owner = str(obj.get("fbp_parent_rig_name", "") or "")
            except FBP_DATA_ERRORS:
                stored_owner = ""
            if not is_parented and stored_owner != owner_name:
                continue
            fallback.append(obj)
            if bool(getattr(obj, "is_fbp_plane", False)) or stored_owner == owner_name:
                tagged.append(obj)
    except FBP_DATA_ERRORS:
        return False
    return len(tagged) == 1 or (not tagged and len(fallback) == 1)


def fbp_effect_supported_for_rig(rig, effect_id):
    definition = fbp_effect_definition(effect_id)
    if not definition or not rig:
        return False
    if bool(definition.get("custom_invalid", False)):
        return False
    if bool(definition.get("requires_mesh_plane", False)):
        return _fbp_rig_has_mesh_plane(rig)
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
    "FBP_EFFECT_CUTOUT_OUTLINE",
    "FBP_EFFECT_CAMERA_SCALE_LOCK",
    "FBP_EFFECT_CAMERA_BILLBOARD",
    "FBP_EFFECT_MIRROR",
    "FBP_EFFECT_THICKNESS",
    "FBP_EFFECT_INFINITE_ROTATION",
    "FBP_EFFECT_FELT_FUZZ",
    "FBP_EFFECT_LATTICE",
    "FBP_EFFECT_UV_DISTORTION",
    "FBP_EFFECT_PIXELATE",
    "FBP_EFFECT_SWIRL",
    "FBP_EFFECT_BULGE_PINCH",
    "FBP_EFFECT_LENS_WARP",
    "FBP_EFFECT_WAVE_WARP",
    "FBP_EFFECT_RIPPLE_DISTORTION",
    "FBP_EFFECT_KALEIDOSCOPE",
    "FBP_EFFECT_HEX_PIXELATE",
    "FBP_EFFECT_MOSAIC_JITTER",
    "FBP_EFFECT_DEPTH_BLUR",
    "FBP_EFFECT_GAUSSIAN_BLUR",
    "FBP_EFFECT_DIRECTIONAL_BLUR",
    "FBP_EFFECT_TRIANGLE_BLUR",
    "FBP_EFFECT_TILT_SHIFT",
    "FBP_EFFECT_UNSHARP_MASK",
    "FBP_EFFECT_EDGE_DETECT",
    "FBP_EFFECT_SMOOTH_TOON",
    "FBP_EFFECT_ADAPTIVE_THRESHOLD",
    "FBP_EFFECT_FALSE_COLOR",
    "FBP_EFFECT_CHROMATIC_ABERRATION",
    "FBP_EFFECT_INK",
    "FBP_EFFECT_EDGE_WORK",
    "FBP_EFFECT_PENCIL_SKETCH",
    "FBP_EFFECT_POSTER_EDGES",
    "FBP_EFFECT_CROSSHATCH",
    "FBP_EFFECT_EMBOSS",
    "FBP_EFFECT_ALPHA_MATTE",
    "FBP_EFFECT_LUMA_MATTE",
    "FBP_EFFECT_SQUARE_MASK",
    "FBP_EFFECT_CIRCLE_MASK",
    "FBP_EFFECT_TRIANGLE_MASK",
    "FBP_EFFECT_CLIPPING_MASK",
    "FBP_EFFECT_IMPORTED_MASK",
    "FBP_EFFECT_LAYER_BLEND",
    "FBP_EFFECT_COLOR_MASK",
    "FBP_EFFECT_LUMINANCE_MASK",
    "FBP_EFFECT_CHANNEL_MASK",
    "FBP_EFFECT_GRADIENT_MASK",
    "FBP_EFFECT_NOISE_MASK",
    "FBP_EFFECT_SOLID_MASK",
    "FBP_EFFECT_HUE_SATURATION",
    "FBP_EFFECT_WHITE_BALANCE",
    "FBP_EFFECT_CURVES",
    "FBP_EFFECT_BRIGHTNESS_CONTRAST",
    "FBP_EFFECT_INVERT",
    "FBP_EFFECT_THRESHOLD",
    "FBP_EFFECT_COLOR_ISOLATE",
    "FBP_EFFECT_DUOTONE",
    "FBP_EFFECT_RECOLOR",
    "FBP_EFFECT_GRAIN",
    "FBP_EFFECT_PAPER_FIBERS",
    "FBP_EFFECT_GRADIENT_LIGHT",
    "FBP_EFFECT_RIM",
    "FBP_EFFECT_SHADOW",
    "FBP_EFFECT_GOBO_SHADOWS",
    "FBP_EFFECT_CRT_SCANLINES",
    "FBP_EFFECT_VIGNETTE",
    "FBP_EFFECT_POSTERIZE",
    "FBP_EFFECT_SOLARIZE",
    "FBP_EFFECT_TRITONE",
    "FBP_EFFECT_FILM_FADE",
    "FBP_EFFECT_CROP",
    "FBP_EFFECT_EXTEND",
    "FBP_EFFECT_DIGITAL_NOISE",
    "FBP_EFFECT_CHROMA_KEY",
    "FBP_EFFECT_HALFTONE",
    "FBP_EFFECT_DOT_MATRIX",
    "FBP_EFFECT_ASCII_MATRIX",
    "FBP_EFFECT_ASCII",
    "FBP_EFFECT_TEXT_MATRIX",
    "FBP_EFFECT_REGISTRY",
    "FBP_EFFECT_METADATA",
    "FBP_EFFECT_REGISTRY_ISSUES",
    "fbp_refresh_custom_effect_registry",
    "FBP_SHADER_STAGE_ORDER",
    "FBP_BASE_EFFECT_MENU_ORDER",
    "FBP_3D_EFFECT_MENU_ORDER",
    "FBP_EFFECT_FAMILIES",
    "FBP_EFFECT_FAMILY_BY_EFFECT",
    "fbp_effect_family_id",
    "fbp_effect_family_definition",
    "fbp_effect_variant_label",
    "FBP_IMAGE_EFFECT_MENU_SECTIONS",
    "FBP_IMAGE_EFFECT_MENU_COLUMNS",
    "FBP_MASK_EFFECT_MENU_SECTIONS",
    "FBP_MASK_EFFECT_MENU_COLUMNS",
    "FBP_MESH_EFFECT_MENU_SECTIONS",
    "FBP_MESH_EFFECT_MENU_COLUMNS",
    "fbp_effect_definition",
    "fbp_effect_supported_for_rig",
    "fbp_effect_tooltip",
    "fbp_normalize_effect_id",
    "fbp_rig_media_type",
)
