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
FBP_EFFECT_FIBER_TUFTS = "FIBER_TUFTS"
FBP_EFFECT_PAPER_SHARDS = "PAPER_SHARDS"
FBP_EFFECT_SPHERE_SCREEN = "SPHERE_SCREEN"
FBP_EFFECT_IMAGE_RELIEF = "IMAGE_RELIEF"
FBP_EFFECT_GLASS = "GLASS"
FBP_EFFECT_CRYSTAL = "CRYSTAL"
FBP_EFFECT_SURFACE_CONFORM = "SURFACE_CONFORM"
FBP_EFFECT_ACCORDION_FOLD = "ACCORDION_FOLD"
FBP_EFFECT_SCULPT_WAVES = "SCULPT_WAVES"
FBP_EFFECT_KINETIC_TILES = "KINETIC_TILES"
FBP_EFFECT_LAYERED_ECHO = "LAYERED_ECHO"
FBP_EFFECT_LATTICE = "LATTICE"
FBP_EFFECT_MOTION = "MOTION"

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
FBP_EFFECT_SLICE_SHIFT = "SLICE_SHIFT"
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
FBP_EFFECT_GP_MASK_SLOT_2 = "GP_MASK_SLOT_2"
FBP_EFFECT_GP_MASK_SLOT_3 = "GP_MASK_SLOT_3"
FBP_EFFECT_GP_MASK_SLOT_4 = "GP_MASK_SLOT_4"
GP_MASK_EFFECT_IDS = (FBP_EFFECT_IMPORTED_MASK, FBP_EFFECT_GP_MASK_SLOT_2, FBP_EFFECT_GP_MASK_SLOT_3, FBP_EFFECT_GP_MASK_SLOT_4)
FBP_EFFECT_LAYER_BLEND = "LAYER_BLEND"
FBP_EFFECT_COLOR_MASK = "COLOR_MASK"
FBP_EFFECT_LUMINANCE_MASK = "LUMINANCE_MASK"
FBP_EFFECT_CHANNEL_MASK = "CHANNEL_MASK"
FBP_EFFECT_GRADIENT_MASK = "GRADIENT_MASK"
FBP_EFFECT_NOISE_MASK = "NOISE_MASK"
FBP_EFFECT_VORONOI_MASK = "VORONOI_MASK"
FBP_EFFECT_WAVE_MASK = "WAVE_MASK"
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
FBP_EFFECT_GRADIENT_MAP = "GRADIENT_MAP"
FBP_EFFECT_CHANNEL_MIXER = "CHANNEL_MIXER"
FBP_EFFECT_DITHER = "DITHER"
FBP_EFFECT_BLOOM = "BLOOM"
FBP_EFFECT_FILTER_PRESETS = "FILTER_PRESETS"
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
FBP_EFFECT_EMISSION = "EMISSION"
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
    FBP_EFFECT_MOTION: {
        "label": "Motion", "icon": "TIME", "kind": "BASE",
        "enabled_key": "fbp_motion_effect_container",
        "category": "3D", "performance": "LIGHT",
        "description": "Container for repeatable procedural Motion layers, paths, spring follow, stagger and baking.",
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT", "COLOR", "GRADIENT", "HOLDOUT"),
        "targets": ("IMAGE_PLANE",),
        "custom_ui": True,
    },
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
    FBP_EFFECT_EMISSION: {
        "label": "Emission", "icon": "LIGHT_SUN", "kind": "BASE",
        "enabled_key": "fbp_effect_emission",
        "category": "2D", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT", "COLOR", "GRADIENT"),
        "property_map": {"fbp_emission_strength": "Strength"},
        "description": "Use a real Emission shader and expose its unrestricted Strength directly in the effect stack.",
    },
    FBP_EFFECT_MESH_WIGGLE: {
        "label": "Mesh Wiggle", "icon": "MOD_NOISE", "kind": "GEOMETRY",
        "source_names": ("FBP_Wiggle",),
        "canonical_name": "FBP_GN_Wiggle_450", "modifier_name": "FBP • Mesh Wiggle",
        "asset_id": "frame_by_plane.wiggle.450", "enabled_key": "fbp_effect_mesh_wiggle",
        "alpha_aware": False,
        "property_map": {
            # Socket names must stay aligned with the bundled GN group. User-facing
            # labels are overridden in ui_labels below.
            "fbp_mesh_wiggle_subdivisions": "Subdivision", "fbp_mesh_wiggle_shade_smooth": "Shade Smooth",
            "fbp_mesh_wiggle_hold": "Stepped", "fbp_mesh_wiggle_strength": "Strength",
            "fbp_mesh_wiggle_speed": "Speed", "fbp_mesh_wiggle_w": "W",
            "fbp_mesh_wiggle_noise_scale": "Noise Scale", "fbp_mesh_wiggle_detail": "Noise Detail",
        },
        "extra_properties": (
            "fbp_mesh_wiggle_playback_subdivisions",
            "fbp_mesh_wiggle_render_subdivisions",
            "fbp_mesh_wiggle_seed",
            "fbp_mesh_wiggle_unique_seed",
        ),
        "ui_labels": {
            "fbp_mesh_wiggle_subdivisions": "Viewport",
            "fbp_mesh_wiggle_playback_subdivisions": "Playback",
            "fbp_mesh_wiggle_render_subdivisions": "Render",
            "fbp_mesh_wiggle_hold": "Stepped",
            "fbp_mesh_wiggle_w": "Starting Phase",
            "fbp_mesh_wiggle_noise_scale": "Scale",
            "fbp_mesh_wiggle_detail": "Detail",
            "fbp_mesh_wiggle_seed": "Pattern Seed",
            "fbp_mesh_wiggle_unique_seed": "Unique per Layer",
        },
        "quality_contracts": ({
            "socket": "Subdivision",
            "viewport_property": "fbp_mesh_wiggle_subdivisions",
            "playback_property": "fbp_mesh_wiggle_playback_subdivisions",
            "render_property": "fbp_mesh_wiggle_render_subdivisions",
            "minimum": 0,
            "playback_mode": "LIMIT",
        },),
        "evolve_property": "fbp_mesh_wiggle_w", "evolve_amount": 1.0,
        "evolve_active_property": "fbp_mesh_wiggle_strength",
        "supports_seed": True,
        "procedural_frame_sync": True,
    },
    FBP_EFFECT_STOP_MOTION_CRUMPLE: {
        "label": "Crumple", "icon": "MOD_DISPLACE", "kind": "GEOMETRY",
        "source_names": ("FBP_StopMotion_Crumple",), "canonical_name": "FBP_GN_StopMotion_Crumple_450",
        "modifier_name": "FBP • Crumple", "asset_id": "frame_by_plane.stop_motion_crumple.450",
        "enabled_key": "fbp_effect_stop_motion_crumple", "alpha_aware": False,
        "property_map": {
            "fbp_stop_motion_resolution": "Resolution",
            "fbp_stop_motion_strength": "Strength",
            "fbp_stop_motion_step_frames": "Step Frames",
        },
        "extra_properties": (
            "fbp_stop_motion_playback_resolution",
            "fbp_stop_motion_render_resolution",
        ),
        "ui_labels": {
            "fbp_stop_motion_resolution": "Viewport",
            "fbp_stop_motion_playback_resolution": "Playback",
            "fbp_stop_motion_render_resolution": "Render",
            "fbp_stop_motion_step_frames": "Stepped",
        },
        "quality_contracts": ({
            "socket": "Resolution",
            "viewport_property": "fbp_stop_motion_resolution",
            "playback_property": "fbp_stop_motion_playback_resolution",
            "render_property": "fbp_stop_motion_render_resolution",
            "minimum": 0,
            "playback_mode": "LIMIT",
        },),
        "performance": "HEAVY",
    },
    FBP_EFFECT_WIND_BENDER: {
        "label": "Wind", "icon": "FORCE_WIND", "kind": "GEOMETRY",
        "source_names": (), "canonical_name": "FBP_GN_Mesh_Motion_611",
        "modifier_name": "FBP • Wind", "asset_id": "frame_by_plane.mesh_motion.611",
        "enabled_key": "fbp_effect_wind_bender", "alpha_aware": False,
        "property_map": {
            "fbp_wind_subdivision": "Subdivision", "fbp_wind_bend_amount": "Bend Amount",
            "fbp_wind_speed": "Wind Speed", "fbp_wind_shade_smooth": "Shade Smooth", "fbp_wind_stepped": "Stepped",
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
        "extra_properties": (
            "fbp_wind_playback_subdivision",
            "fbp_wind_render_subdivision",
        ),
        "ui_labels": {
            "fbp_wind_subdivision": "Viewport",
            "fbp_wind_playback_subdivision": "Playback",
            "fbp_wind_render_subdivision": "Render",
            "fbp_wind_bend_amount": "Strength",
            "fbp_wind_speed": "Speed",
            "fbp_wind_shade_smooth": "Shade Smooth",
            "fbp_wind_wave_amplitude": "Strength",
            "fbp_wind_wave_speed": "Speed",
            "fbp_wind_phase": "Starting Phase",
            "fbp_wind_direction": "Direction",
            "fbp_wind_direction_space": "Local / World",
        },
        "quality_contracts": ({
            "socket": "Subdivision",
            "viewport_property": "fbp_wind_subdivision",
            "playback_property": "fbp_wind_playback_subdivision",
            "render_property": "fbp_wind_render_subdivision",
            "minimum": 0,
            "playback_mode": "LIMIT",
        },),
        "performance": "HEAVY",
        "evolve_property": "fbp_wind_phase", "evolve_amount": 6.283185307,
        "evolve_active_property": "fbp_wind_bend_amount", "supports_seed": True,
        "builtin": True,
    },
    FBP_EFFECT_CUTOUT_OUTLINE: {
        "label": "Cutout Outline", "icon": "MOD_SKIN", "kind": "GEOMETRY",
        "source_names": ("FBP_GN_Cutout_Outline_6027",), "canonical_name": "FBP_GN_Cutout_Outline_6130",
        "modifier_name": "FBP • Cutout Outline", "asset_id": "frame_by_plane.cutout_outline.6130",
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
        "enabled_key": "fbp_effect_camera_billboard",
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
        "label": "Extrude", "icon": "MOD_SOLIDIFY", "kind": "GEOMETRY",
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
        "evolve_mode": "SEED_STEP", "supports_seed": True,
        "source_material_socket": "Fuzz Material",
    },
    FBP_EFFECT_FIBER_TUFTS: {
        "label": "Fiber Tufts", "icon": "CURVES_DATA", "kind": "GEOMETRY",
        "source_names": ("FBP_GN_Fiber_Tufts_660",), "canonical_name": "FBP_GN_Fiber_Tufts_6130",
        "modifier_name": "FBP • Fiber Tufts", "asset_id": "frame_by_plane.fiber_tufts.6130",
        "enabled_key": "fbp_effect_fiber_tufts", "alpha_aware": True, "builtin": True,
        "requires_alpha_geometry_contract": True,
        "attribute_material_socket": "Fiber Material",
        "attribute_material_name": "fbp_fiber_color",
        "attribute_material_uv_name": "fbp_fiber_uv",
        "attribute_material_uv_store": "Store Fiber Source UV",
        "attribute_material_role": "Fiber Tufts",
        "owned_material": True,
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT"),
        "required_input_sockets": (
            "Render Density", "Viewport %", "Length", "Luminance Length", "Radius", "Segments",
            "Bend", "Randomness", "Seed", "Alpha Threshold", "Alpha Resolution",
            "Fiber Material",
        ),
        "property_map": {
            "fbp_fiber_render_density": "Render Density",
            "fbp_fiber_viewport_percentage": "Viewport %",
            "fbp_fiber_length": "Length",
            "fbp_fiber_luminance_length": "Luminance Length",
            "fbp_fiber_radius": "Radius",
            "fbp_fiber_segments": "Segments",
            "fbp_fiber_bend": "Bend",
            "fbp_fiber_randomness": "Randomness",
            "fbp_fiber_seed": "Seed",
            "fbp_fiber_alpha_threshold": "Alpha Threshold",
            "fbp_fiber_alpha_resolution": "Alpha Resolution",
        },
        "evolve_property": "fbp_fiber_seed", "evolve_amount": 1.0,
        "evolve_mode": "SEED_STEP", "supports_seed": True,
        "description": "Alpha-aware instanced fiber clumps sampled on an aspect-balanced plane grid. Instances stay unrealized for responsive viewport and render evaluation.",
    },
    FBP_EFFECT_PAPER_SHARDS: {
        "label": "Paper Shards", "icon": "MOD_EXPLODE", "kind": "GEOMETRY",
        "source_names": ("FBP_GN_Paper_Shards_660",), "canonical_name": "FBP_GN_Paper_Shards_6130",
        "modifier_name": "FBP • Paper Shards", "asset_id": "frame_by_plane.paper_shards.6130",
        "enabled_key": "fbp_effect_paper_shards", "alpha_aware": True, "builtin": True,
        "requires_alpha_geometry_contract": True,
        "attribute_material_socket": "Shard Material",
        "attribute_material_name": "fbp_shard_color",
        "attribute_material_uv_name": "fbp_shard_uv",
        "attribute_material_uv_store": "Store Shard Source UV",
        "attribute_material_role": "Paper Shards",
        "owned_material": True,
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT"),
        "required_input_sockets": (
            "Render Density", "Viewport %", "Shard Size", "Aspect", "Thickness",
            "Lift", "Luminance Lift", "Tilt", "Scale Randomness", "Seed", "Alpha Threshold",
            "Alpha Resolution", "Shard Material",
        ),
        "property_map": {
            "fbp_shards_render_density": "Render Density",
            "fbp_shards_viewport_percentage": "Viewport %",
            "fbp_shards_size": "Shard Size",
            "fbp_shards_aspect": "Aspect",
            "fbp_shards_thickness": "Thickness",
            "fbp_shards_lift": "Lift",
            "fbp_shards_luminance_lift": "Luminance Lift",
            "fbp_shards_tilt": "Tilt",
            "fbp_shards_scale_randomness": "Scale Randomness",
            "fbp_shards_seed": "Seed",
            "fbp_shards_alpha_threshold": "Alpha Threshold",
            "fbp_shards_alpha_resolution": "Alpha Resolution",
        },
        "evolve_property": "fbp_shards_seed", "evolve_amount": 1.0,
        "evolve_mode": "SEED_STEP", "supports_seed": True,
        "description": "Scatter lightweight instanced paper chips across an aspect-balanced opaque silhouette with controllable lift, tilt, thickness and scale variation.",
    },
    FBP_EFFECT_SPHERE_SCREEN: {
        "label": "Image Solids", "icon": "MESH_ICOSPHERE", "kind": "GEOMETRY",
        "source_names": ("FBP_GN_Image_Solids_680",), "canonical_name": "FBP_GN_Image_Solids_6140",
        "modifier_name": "FBP • Image Solids", "asset_id": "frame_by_plane.image_solids.6140",
        "enabled_key": "fbp_effect_sphere_screen", "image_aware": True,
        "alpha_aware": False, "private_group": True, "builtin": True,
        "material_preview": True,
        "attribute_material_socket": "Solid Material",
        "attribute_material_name": "fbp_sphere_screen_color",
        "attribute_material_uv_name": "fbp_sphere_screen_uv",
        "attribute_material_uv_store": "Store Image Solids UV",
        "attribute_material_role": "Image Solids",
        "attribute_material_emission_property": "fbp_sphere_screen_emission",
        "owned_material": True,
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT"),
        "required_input_sockets": (
            "Viewport Columns", "Viewport Rows", "Render Columns", "Render Rows",
            "Shape", "Solid Scale", "Luminance Size", "Sphere Detail",
            "Depth", "Depth Mode", "Depth Image", "Flicker", "Phase",
            "Alpha Threshold", "Show Source", "Solid Material",
        ),
        "property_map": {
            "fbp_sphere_screen_viewport_columns": "Viewport Columns",
            "fbp_sphere_screen_viewport_rows": "Viewport Rows",
            "fbp_sphere_screen_render_columns": "Render Columns",
            "fbp_sphere_screen_render_rows": "Render Rows",
            "fbp_sphere_screen_shape": "Shape",
            "fbp_sphere_screen_scale": "Solid Scale",
            "fbp_sphere_screen_luminance_size": "Luminance Size",
            "fbp_sphere_screen_subdivisions": "Sphere Detail",
            "fbp_sphere_screen_depth": "Depth",
            "fbp_sphere_screen_depth_mode": "Depth Mode",
            "fbp_sphere_screen_depth_image": "Depth Image",
            "fbp_sphere_screen_flicker": "Flicker",
            "fbp_sphere_screen_phase": "Phase",
            "fbp_sphere_screen_alpha_threshold": "Alpha Threshold",
            "fbp_sphere_screen_show_source": "Show Source",
        },
        "extra_properties": ("fbp_sphere_screen_emission",),
        "evolve_property": "fbp_sphere_screen_phase", "evolve_amount": 0.5,
        "evolve_active_property": "fbp_sphere_screen_flicker", "supports_seed": True,
        "description": "Rebuild the image as luminous spheres, cubes, cylinders or cones. Color, size and selectable light/shadow/saturation/custom-map depth remain point-driven and unrealized.",
    },
    FBP_EFFECT_IMAGE_RELIEF: {
        "label": "Image Relief", "icon": "MOD_DISPLACE", "kind": "GEOMETRY",
        "source_names": ("FBP_GN_Image_Relief_680", "FBP_GN_Image_Relief_6130"), "canonical_name": "FBP_GN_Image_Relief_6140",
        "modifier_name": "FBP • Image Relief", "asset_id": "frame_by_plane.image_relief.6140",
        "enabled_key": "fbp_effect_image_relief", "image_aware": True,
        "alpha_aware": False, "private_group": True, "builtin": True,
        "material_preview": True,
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT"),
        "required_input_sockets": (
            "Geometry", "Subdivision", "Depth", "Midlevel", "Depth Mode",
            "Depth Image", "Smooth", "Smooth Iterations", "Alpha Threshold", "Shade Smooth",
        ),
        "property_map": {
            "fbp_image_relief_subdivision": "Subdivision",
            "fbp_image_relief_depth": "Depth",
            "fbp_image_relief_midlevel": "Midlevel",
            "fbp_image_relief_depth_mode": "Depth Mode",
            "fbp_image_relief_depth_image": "Depth Image",
            "fbp_image_relief_smooth": "Smooth",
            "fbp_image_relief_smooth_iterations": "Smooth Iterations",
            "fbp_image_relief_alpha_threshold": "Alpha Threshold",
            "fbp_image_relief_shade_smooth": "Shade Smooth",
        },
        "extra_properties": (
            "fbp_image_relief_playback_subdivision",
            "fbp_image_relief_render_subdivision",
        ),
        "quality_contracts": ({
            "socket": "Subdivision",
            "viewport_property": "fbp_image_relief_subdivision",
            "playback_property": "fbp_image_relief_playback_subdivision",
            "render_property": "fbp_image_relief_render_subdivision",
            "minimum": 0,
            "playback_mode": "LIMIT",
        },),
        "evolve_property": "fbp_image_relief_depth", "evolve_amount": 0.02,
        "supports_seed": True,
        "description": "Turn the textured plane into a UV-preserving, aspect-balanced triangular relief driven by highlights, shadows, saturation or a custom depth image.",
    },
    FBP_EFFECT_GLASS: {
        "label": "Broken Glass", "icon": "MOD_EXPLODE", "kind": "GEOMETRY",
        "source_names": ("FBP_GN_Glass_690", "FBP_GN_Broken_Glass_6110", "FBP_GN_Broken_Glass_6120", "FBP_GN_Broken_Glass_6130", "FBP_GN_Broken_Glass_6140", "FBP_GN_Broken_Glass_6160", "FBP_GN_Broken_Glass_7000"), "canonical_name": "FBP_GN_Broken_Glass_6170",
        "modifier_name": "FBP • Broken Glass", "asset_id": "frame_by_plane.broken_glass.6170",
        "enabled_key": "fbp_effect_glass", "image_aware": True,
        "alpha_aware": False, "private_group": True, "builtin": True,
        "material_preview": True,
        "owned_material": True,
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT"),
        "required_input_sockets": (
            "Geometry", "Subdivision", "Thickness", "Bevel", "Shard Lift", "Damage Source",
            "Damage Map", "Cell Scale", "Correct Aspect", "Texture Scale X", "Texture Scale Y",
            "Crack Width", "Damage", "Chaos", "Seed",
            "Alpha Threshold", "Shade Smooth", "Glass Material",
        ),
        "property_map": {
            "fbp_glass_subdivision": "Subdivision",
            "fbp_glass_thickness": "Thickness",
            "fbp_glass_bevel": "Bevel",
            "fbp_glass_relief": "Shard Lift",
            "fbp_glass_source": "Damage Source",
            "fbp_glass_normal_image": "Damage Map",
            "fbp_glass_noise_scale": "Cell Scale",
            "fbp_glass_correct_aspect": "Correct Aspect",
            "fbp_glass_texture_scale_x": "Texture Scale X",
            "fbp_glass_texture_scale_y": "Texture Scale Y",
            "fbp_glass_crack_width": "Crack Width",
            "fbp_glass_damage": "Damage",
            "fbp_glass_noise_detail": "Chaos",
            "fbp_glass_phase": "Seed",
            "fbp_glass_alpha_threshold": "Alpha Threshold",
            "fbp_glass_shade_smooth": "Shade Smooth",
        },
        "extra_properties": (
            "fbp_glass_playback_subdivision",
            "fbp_glass_render_subdivision",
            "fbp_glass_crack_width",
            "fbp_glass_damage",
            "fbp_glass_distortion",
            "fbp_glass_roughness",
            "fbp_glass_ior",
            "fbp_glass_tint",
            "fbp_glass_source_color",
            "fbp_glass_edge_tint",
            "fbp_glass_absorption",
        ),
        "quality_contracts": ({
            "socket": "Subdivision",
            "viewport_property": "fbp_glass_subdivision",
            "playback_property": "fbp_glass_playback_subdivision",
            "render_property": "fbp_glass_render_subdivision",
            "minimum": 0,
            "playback_mode": "LIMIT",
        },),
        "evolve_property": "fbp_glass_phase", "evolve_amount": 0.35,
        "evolve_active_property": "fbp_glass_damage", "supports_seed": True,
        "description": "Fracture an aspect-balanced alpha grid into separated Voronoi shards with automatic texture-aspect correction, independent X/Y scale, Blender 5.2 Mesh Bevel, damage-map control and a closed refractive volume.",
    },
    FBP_EFFECT_CRYSTAL: {
        "label": "Crystal", "icon": "LIGHTPROBE_SPHERE", "kind": "GEOMETRY",
        "source_names": ("FBP_GN_Crystal_6110", "FBP_GN_Crystal_6120", "FBP_GN_Crystal_6130", "FBP_GN_Crystal_6140", "FBP_GN_Crystal_6160", "FBP_GN_Crystal_6170", "FBP_GN_Crystal_6180", "FBP_GN_Crystal_6190", "FBP_GN_Crystal_7000"), "canonical_name": "FBP_GN_Crystal_6222",
        "modifier_name": "FBP • Crystal", "asset_id": "frame_by_plane.crystal.6222",
        "enabled_key": "fbp_effect_crystal", "image_aware": True,
        "alpha_aware": False, "private_group": True, "builtin": True,
        "material_preview": True,
        "owned_material": True,
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT"),
        "required_input_sockets": (
            "Geometry", "Subdivision", "Silhouette Detail", "Depth", "Thickness", "Roundness",
            "Edge Pinning", "Blur Iterations", "Use Influence Map", "Influence Map",
            "Invert Influence", "Influence Strength", "Texture Type", "Pattern Mode", "Pattern Scale", "Correct Aspect",
            "Texture Scale X", "Texture Scale Y", "Pattern Detail",
            "Pattern Strength", "Cell Randomness", "Cell Seed", "Phase",
            "Alpha Threshold", "Surface Subdivision",
            "Shade Smooth", "Crystal Material",
        ),
        "property_map": {
            "fbp_crystal_subdivision": "Subdivision",
            "fbp_crystal_silhouette_detail": "Silhouette Detail",
            "fbp_crystal_depth": "Depth",
            "fbp_crystal_thickness": "Thickness",
            "fbp_crystal_roundness": "Roundness",
            "fbp_crystal_edge_pinning": "Edge Pinning",
            "fbp_crystal_blur_iterations": "Blur Iterations",
            "fbp_crystal_use_influence_map": "Use Influence Map",
            "fbp_crystal_influence_image": "Influence Map",
            "fbp_crystal_invert_influence": "Invert Influence",
            "fbp_crystal_influence_strength": "Influence Strength",
            "fbp_crystal_texture_type": "Texture Type",
            "fbp_crystal_pattern_mode": "Pattern Mode",
            "fbp_crystal_pattern_scale": "Pattern Scale",
            "fbp_crystal_correct_aspect": "Correct Aspect",
            "fbp_crystal_texture_scale_x": "Texture Scale X",
            "fbp_crystal_texture_scale_y": "Texture Scale Y",
            "fbp_crystal_pattern_detail": "Pattern Detail",
            "fbp_crystal_pattern_strength": "Pattern Strength",
            "fbp_crystal_cell_randomness": "Cell Randomness",
            "fbp_crystal_cell_seed": "Cell Seed",
            "fbp_crystal_phase": "Phase",
            "fbp_crystal_alpha_threshold": "Alpha Threshold",
            "fbp_crystal_surface_subdivision": "Surface Subdivision",
            "fbp_crystal_shade_smooth": "Shade Smooth",
        },
        "ui_labels": {"fbp_crystal_alpha_threshold": "Alpha Cutoff", "fbp_crystal_blur_iterations": "Edge Width"},
        "extra_properties": (
            "fbp_crystal_playback_subdivision", "fbp_crystal_render_subdivision",
            "fbp_crystal_distortion", "fbp_crystal_roughness", "fbp_crystal_ior",
            "fbp_crystal_tint", "fbp_crystal_source_color", "fbp_crystal_absorption",
            "fbp_crystal_thin_wall",
        ),
        "quality_contracts": ({
            "socket": "Subdivision",
            "viewport_property": "fbp_crystal_subdivision",
            "playback_property": "fbp_crystal_playback_subdivision",
            "render_property": "fbp_crystal_render_subdivision",
            "minimum": 0,
            "playback_mode": "LIMIT",
        },),
        "evolve_property": "fbp_crystal_phase", "evolve_amount": 0.25,
        "evolve_active_property": "fbp_crystal_pattern_strength", "supports_seed": True,
        "description": "Turn the plane texture into an exact-cut refractive surface while preserving the plane UVs, Crop and Extend modes across both the Crystal source and its Influence Map.",
    },
    FBP_EFFECT_SURFACE_CONFORM: {
        "label": "Surface Conform", "icon": "MOD_SHRINKWRAP", "kind": "GEOMETRY",
        "source_names": ("FBP_GN_Surface_Conform_650",), "canonical_name": "FBP_GN_Surface_Conform_6130",
        "modifier_name": "FBP • Surface Conform", "asset_id": "frame_by_plane.surface_conform.6130",
        "enabled_key": "fbp_effect_surface_conform", "builtin": True,
        "required_input_sockets": (
            "Target", "Subdivision", "Factor", "Offset", "Max Distance", "Shade Smooth",
        ),
        "property_map": {
            "fbp_surface_conform_target": "Target",
            "fbp_surface_conform_subdivision": "Subdivision",
            "fbp_surface_conform_factor": "Factor",
            "fbp_surface_conform_offset": "Offset",
            "fbp_surface_conform_max_distance": "Max Distance",
            "fbp_surface_conform_shade_smooth": "Shade Smooth",
        },
        "extra_properties": (
            "fbp_surface_conform_playback_subdivision",
            "fbp_surface_conform_render_subdivision",
        ),
        "quality_contracts": ({
            "socket": "Subdivision",
            "viewport_property": "fbp_surface_conform_subdivision",
            "playback_property": "fbp_surface_conform_playback_subdivision",
            "render_property": "fbp_surface_conform_render_subdivision",
            "minimum": 0,
            "playback_mode": "LIMIT",
        },),
        "evolve_property": "fbp_surface_conform_offset", "evolve_amount": 0.02,
        "supports_seed": True,
        "description": "Triangulate and non-destructively conform an aspect-balanced plane to the closest target surface while preserving its UV texture.",
    },
    FBP_EFFECT_ACCORDION_FOLD: {
        "label": "Accordion Fold", "icon": "MOD_SIMPLEDEFORM", "kind": "GEOMETRY",
        "source_names": ("FBP_GN_Accordion_Fold_660",), "canonical_name": "FBP_GN_Accordion_Fold_6130",
        "modifier_name": "FBP • Accordion Fold", "asset_id": "frame_by_plane.accordion_fold.6130",
        "enabled_key": "fbp_effect_accordion_fold", "builtin": True,
        "required_input_sockets": (
            "Geometry", "Subdivision", "Folds", "Depth", "Phase", "Vertical", "Shade Smooth",
        ),
        "property_map": {
            "fbp_accordion_subdivision": "Subdivision",
            "fbp_accordion_folds": "Folds",
            "fbp_accordion_depth": "Depth",
            "fbp_accordion_phase": "Phase",
            "fbp_accordion_vertical": "Vertical",
            "fbp_accordion_shade_smooth": "Shade Smooth",
        },
        "extra_properties": (
            "fbp_accordion_playback_subdivision",
            "fbp_accordion_render_subdivision",
        ),
        "quality_contracts": ({
            "socket": "Subdivision",
            "viewport_property": "fbp_accordion_subdivision",
            "playback_property": "fbp_accordion_playback_subdivision",
            "render_property": "fbp_accordion_render_subdivision",
            "minimum": 0,
            "playback_mode": "LIMIT",
        },),
        "evolve_property": "fbp_accordion_phase", "evolve_amount": 0.25,
        "supports_seed": True,
        "description": "Fold an aspect-balanced triangular plane into an animatable accordion surface while preserving UVs and material.",
    },
    FBP_EFFECT_SCULPT_WAVES: {
        "label": "Sculpt Waves", "icon": "MOD_WAVE", "kind": "GEOMETRY",
        "source_names": ("FBP_GN_Sculpt_Waves_680", "FBP_GN_Sculpt_Waves_6130"), "canonical_name": "FBP_GN_Sculpt_Waves_6140",
        "modifier_name": "FBP • Sculpt Waves", "asset_id": "frame_by_plane.sculpt_waves.6140",
        "enabled_key": "fbp_effect_sculpt_waves", "private_group": True, "builtin": True,
        "required_input_sockets": (
            "Geometry", "Subdivision", "Style", "Amplitude", "Frequency",
            "Phase", "Edge Falloff", "Shade Smooth",
        ),
        "property_map": {
            "fbp_sculpt_waves_subdivision": "Subdivision",
            "fbp_sculpt_waves_style": "Style",
            "fbp_sculpt_waves_amplitude": "Amplitude",
            "fbp_sculpt_waves_frequency": "Frequency",
            "fbp_sculpt_waves_phase": "Phase",
            "fbp_sculpt_waves_edge_falloff": "Edge Falloff",
            "fbp_sculpt_waves_shade_smooth": "Shade Smooth",
        },
        "extra_properties": (
            "fbp_sculpt_waves_playback_subdivision",
            "fbp_sculpt_waves_render_subdivision",
        ),
        "quality_contracts": ({
            "socket": "Subdivision",
            "viewport_property": "fbp_sculpt_waves_subdivision",
            "playback_property": "fbp_sculpt_waves_playback_subdivision",
            "render_property": "fbp_sculpt_waves_render_subdivision",
            "minimum": 0,
            "playback_mode": "LIMIT",
        },),
        "evolve_property": "fbp_sculpt_waves_phase", "evolve_amount": 0.18,
        "evolve_active_property": "fbp_sculpt_waves_amplitude", "supports_seed": True,
        "description": "Sculpt an aspect-balanced triangular plane into animated radial, moiré or spiral waves while preserving UVs and material.",
    },
    FBP_EFFECT_KINETIC_TILES: {
        "label": "Kinetic Tiles", "icon": "MESH_GRID", "kind": "GEOMETRY",
        "source_names": ("FBP_GN_Kinetic_Tiles_680", "FBP_GN_Kinetic_Tiles_6130"), "canonical_name": "FBP_GN_Kinetic_Tiles_6140",
        "modifier_name": "FBP • Kinetic Tiles", "asset_id": "frame_by_plane.kinetic_tiles.6140",
        "enabled_key": "fbp_effect_kinetic_tiles", "private_group": True, "builtin": True,
        "required_input_sockets": (
            "Geometry", "Subdivision", "Pattern", "Gap", "Thickness",
            "Motion", "Frequency", "Phase", "Shade Smooth",
        ),
        "property_map": {
            "fbp_kinetic_tiles_subdivision": "Subdivision",
            "fbp_kinetic_tiles_pattern": "Pattern",
            "fbp_kinetic_tiles_gap": "Gap",
            "fbp_kinetic_tiles_thickness": "Thickness",
            "fbp_kinetic_tiles_motion": "Motion",
            "fbp_kinetic_tiles_frequency": "Frequency",
            "fbp_kinetic_tiles_phase": "Phase",
            "fbp_kinetic_tiles_shade_smooth": "Shade Smooth",
        },
        "extra_properties": (
            "fbp_kinetic_tiles_playback_subdivision",
            "fbp_kinetic_tiles_render_subdivision",
        ),
        "quality_contracts": ({
            "socket": "Subdivision",
            "viewport_property": "fbp_kinetic_tiles_subdivision",
            "playback_property": "fbp_kinetic_tiles_playback_subdivision",
            "render_property": "fbp_kinetic_tiles_render_subdivision",
            "minimum": 0,
            "playback_mode": "LIMIT",
        },),
        "evolve_property": "fbp_kinetic_tiles_phase", "evolve_amount": 0.22,
        "evolve_active_property": "fbp_kinetic_tiles_motion", "supports_seed": True,
        "description": "Break the textured plane into near-square extruded tiles with wave, checker or ripple motion while retaining source UVs and material.",
    },
    FBP_EFFECT_LAYERED_ECHO: {
        "label": "Array", "icon": "MOD_ARRAY", "kind": "GEOMETRY",
        "source_names": (), "canonical_name": "FBP_GN_Array_670",
        "modifier_name": "FBP • Array", "asset_id": "frame_by_plane.array.670",
        "enabled_key": "fbp_effect_layered_echo", "builtin": True,
        "required_input_sockets": (
            "Geometry", "Layers", "Offset X", "Offset Y", "Spacing", "Scale Step",
            "Rotation X", "Rotation Y", "Twist", "Wave", "Phase",
        ),
        "property_map": {
            "fbp_layered_echo_layers": "Layers",
            "fbp_layered_echo_offset_x": "Offset X",
            "fbp_layered_echo_offset_y": "Offset Y",
            "fbp_layered_echo_spacing": "Spacing",
            "fbp_layered_echo_scale_step": "Scale Step",
            "fbp_layered_echo_rotation_x": "Rotation X",
            "fbp_layered_echo_rotation_y": "Rotation Y",
            "fbp_layered_echo_twist": "Twist",
            "fbp_layered_echo_wave": "Wave",
            "fbp_layered_echo_phase": "Phase",
        },
        "extra_properties": (
            "fbp_layered_echo_playback_layers",
            "fbp_layered_echo_render_layers",
        ),
        "quality_contracts": ({
            "socket": "Layers",
            "viewport_property": "fbp_layered_echo_layers",
            "playback_property": "fbp_layered_echo_playback_layers",
            "render_property": "fbp_layered_echo_render_layers",
            "minimum": 1,
            "playback_mode": "LIMIT",
        },),
        "evolve_property": "fbp_layered_echo_phase", "evolve_amount": 0.2,
        "evolve_active_property": "fbp_layered_echo_wave", "supports_seed": True,
        "description": "Create a memory-efficient animated stack of textured plane instances with depth, scale, twist and wave controls.",
    },
    FBP_EFFECT_LATTICE: {
        "label": "Lattice", "icon": "MOD_LATTICE", "kind": "BASE",
        "category": "3D", "enabled_key": "fbp_effect_lattice",
        # Lattice deforms the generated mesh and does not depend on whether the
        # visual source is an image, sequence, procedural plane or test layer.
        # Validate the real linked mesh instead of media metadata.
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
        "extra_properties": (
            "fbp_lattice_object", "fbp_lattice_points_u", "fbp_lattice_points_v",
            "fbp_lattice_link_loops",
        ),
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT", "HOLDOUT", "CUTOUT"),
    },
    FBP_EFFECT_UV_DISTORTION: {
        "label": "Turbulence", "icon": "FORCE_TURBULENCE", "kind": "SHADER", "stage": "UV",
        "source_names": ("FBP_Turbolence",), "canonical_name": "FBP_SH_Turbulence_7029",
        "asset_id": "frame_by_plane.shader.turbulence.7029", "enabled_key": "fbp_effect_uv_distortion",
        "input_socket": "Vector", "output_socket": "Vector Out",
        "required_input_sockets": ("Noise Scale", "Distortion Amount", "Evolution"),
        "property_map": {
            "fbp_uv_distortion_scale": "Noise Scale",
            "fbp_uv_distortion_amount": "Distortion Amount",
            "fbp_uv_distortion_evolution": "Evolution",
        },
        "evolve_property": "fbp_uv_distortion_evolution", "evolve_amount": 0.2,
        "supports_seed": True, "builtin": True,
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
        "extra_properties": (
            "fbp_pixelate_grid_mode",
            "fbp_pixelate_size", "fbp_pixelate_stretch",
        ),
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
        "label": "Wave Warp", "icon": "MOD_WAVE", "kind": "SHADER", "stage": "UV",
        "canonical_name": "FBP_SH_Wave_Warp_6019", "asset_id": "frame_by_plane.shader.wave_warp.6019",
        "enabled_key": "fbp_effect_wave_warp", "input_socket": "Vector", "output_socket": "Vector Out",
        "required_input_sockets": ("Amplitude", "Frequency", "Phase", "Speed", "Angle", "Factor"),
        "property_map": {
            "fbp_wave_warp_amplitude": "Amplitude", "fbp_wave_warp_frequency": "Frequency",
            "fbp_wave_warp_phase": "Phase", "fbp_wave_warp_speed": "Speed",
            "fbp_wave_warp_angle": "Angle", "fbp_wave_warp_factor": "Factor",
        },
        "ui_labels": {
            "fbp_wave_warp_amplitude": "Strength",
            "fbp_wave_warp_frequency": "Frequency",
            "fbp_wave_warp_phase": "Starting Phase",
            "fbp_wave_warp_speed": "Speed",
            "fbp_wave_warp_angle": "Direction",
            "fbp_wave_warp_factor": "Influence",
        },
        "evolve_property": "fbp_wave_warp_phase", "evolve_amount": 6.283185307,
        "evolve_speed_property": "fbp_wave_warp_speed",
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
        "ui_labels": {"fbp_ripple_distortion_phase": "Base Phase"},
        "evolve_property": "fbp_ripple_distortion_phase", "evolve_amount": 6.283185307,
        "evolve_speed_property": "fbp_ripple_distortion_speed",
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
        "ui_labels": {"fbp_mosaic_jitter_seed": "Base Seed"},
        "evolve_property": "fbp_mosaic_jitter_seed", "evolve_amount": 1.0,
        "evolve_active_property": "fbp_mosaic_jitter_amount",
        "evolve_mode": "SEED_STEP", "supports_seed": True, "builtin": True,
    },
    FBP_EFFECT_SLICE_SHIFT: {
        "label": "Slice Shift", "icon": "MOD_DISPLACE", "kind": "SHADER", "stage": "UV",
        "canonical_name": "FBP_SH_Slice_Shift_627", "asset_id": "frame_by_plane.shader.slice_shift.627",
        "enabled_key": "fbp_effect_slice_shift", "input_socket": "Vector", "output_socket": "Vector Out",
        "required_input_sockets": ("Angle", "Bands", "Shift", "Random", "Seed", "Factor"),
        "property_map": {
            "fbp_slice_shift_angle": "Angle",
            "fbp_slice_shift_bands": "Bands",
            "fbp_slice_shift_shift": "Shift",
            "fbp_slice_shift_random": "Random",
            "fbp_slice_shift_seed": "Seed",
            "fbp_slice_shift_factor": "Factor",
        },
        "ui_labels": {"fbp_slice_shift_seed": "Base Seed"},
        "evolve_property": "fbp_slice_shift_seed", "evolve_amount": 1.0,
        "evolve_active_property": "fbp_slice_shift_shift",
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
        "label": "Gaussian Blur", "icon": "ANTIALIASED", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Gaussian_Blur_611",
        "asset_id": "frame_by_plane.shader.gaussian_blur.611", "enabled_key": "fbp_effect_gaussian_blur",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "prebundled": True,
        
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
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "prebundled": True,
        "supports": ("IMAGE", "SEQUENCE"),
        "required_input_sockets": ("Use Image Sample", "Angle", "Distance", "Samples", "Factor", "Texel X", "Texel Y"),
        "property_map": {
            "fbp_directional_blur_angle": "Angle",
            "fbp_directional_blur_distance": "Distance",
            "fbp_directional_blur_samples": "Samples",
            "fbp_directional_blur_factor": "Factor",
        },
        # Controller anchor values are intentionally UI/runtime-only: they
        # position the viewport direction helper but do not map to shader sockets.
        "extra_properties": (
            "fbp_directional_blur_control_x",
            "fbp_directional_blur_control_y",
        ),
    },
    FBP_EFFECT_TRIANGLE_BLUR: {
        "label": "Triangle Blur", "icon": "ANTIALIASED", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Triangle_Blur_6012", "asset_id": "frame_by_plane.shader.triangle_blur.6012",
        "enabled_key": "fbp_effect_triangle_blur", "input_socket": "Color In", "output_socket": "Color Out",
        "uv_input_socket": "UV Vector", "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "prebundled": True,
        "supports": ("IMAGE", "SEQUENCE"),
        "property_map": {"fbp_triangle_blur_radius": "Radius", "fbp_triangle_blur_samples": "Samples", "fbp_triangle_blur_factor": "Factor"},
    },
    FBP_EFFECT_TILT_SHIFT: {
        "label": "Tilt Shift", "icon": "PROP_PROJECTED", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Tilt_Shift_6037", "asset_id": "frame_by_plane.shader.tilt_shift.6037",
        "enabled_key": "fbp_effect_tilt_shift", "input_socket": "Color In", "output_socket": "Color Out",
        "uv_input_socket": "UV Vector", "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "private_group": True, "image_aware": True, "uses_source_texel": True, "builtin": True, "prebundled": True,
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
        "label": "Adaptive Threshold", "icon": "MOD_DASH", "kind": "SHADER", "stage": "COLOR",
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
        "label": "Ink", "icon": "GREASEPENCIL", "kind": "SHADER", "stage": "COLOR",
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
        "label": "Sketch", "icon": "GREASEPENCIL", "kind": "SHADER", "stage": "COLOR",
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
        "label": "Emboss", "icon": "MOD_DISPLACE", "kind": "SHADER", "stage": "COLOR",
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
        "label": "Alpha Matte", "icon": "IMAGE_ALPHA", "kind": "SHADER", "stage": "MASK",
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
        "mask_source_transform_aware": True, "track_matte_contract_version": 10,
        "private_group": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_LUMA_MATTE: {
        "label": "Luma Matte", "icon": "LIGHT", "kind": "SHADER", "stage": "MASK",
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
        "extra_properties": (
            "fbp_luma_matte_source_type", "fbp_luma_matte_source",
            "fbp_luma_matte_path", "fbp_luma_matte_image",
            "fbp_luma_matte_source_display",
        ),
        "mask_source_property": "fbp_luma_matte_source",
        "mask_source_aware": True, "mask_source_visibility_aware": True,
        "mask_source_transform_aware": True, "track_matte_contract_version": 10,
        "private_group": True, "builtin": True,
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_SQUARE_MASK: {
        "label": "Square Mask", "icon": "MESH_PLANE", "kind": "SHADER", "stage": "MASK",
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
            "fbp_square_mask_external_null",
        ),
        "object_mask_aware": True, "object_mask_shape": "SQUARE",
        "object_mask_pointer_property": "fbp_square_mask_object",
        "private_group": True, "builtin": True,
        "description": "Mask the layer with an editable square mesh. Move the helper in Object Mode or reshape its vertices in Edit Mode.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_CIRCLE_MASK: {
        "label": "Circle Mask", "icon": "MESH_CIRCLE", "kind": "SHADER", "stage": "MASK",
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
            "fbp_circle_mask_external_null",
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
            "fbp_triangle_mask_external_null",
        ),
        "object_mask_aware": True, "object_mask_shape": "TRIANGLE",
        "object_mask_pointer_property": "fbp_triangle_mask_object",
        "private_group": True, "builtin": True,
        "description": "Mask the layer with an editable triangle mesh. Move the helper in Object Mode or reshape its vertices in Edit Mode.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_CLIPPING_MASK: {
        "label": "Clipping Mask", "icon": "CLIPUV_HLT", "kind": "SHADER", "stage": "MASK",
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
        "mask_camera_projection_aware": True,
        "track_matte_contract_version": 10,
        "private_group": True, "builtin": True, "layer_feature": True,
        "description": "Clip this layer to the alpha of the image or animated layer directly below it in the same collection.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_IMPORTED_MASK: {
        "label": "Imported Layer Mask", "icon": "FILE_IMAGE", "kind": "SHADER", "stage": "MASK",
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
        "imported_mask_aware": True, "imported_mask_prefix": "fbp_imported_mask",
        "private_group": True, "builtin": True, "layer_feature": True,
        "local_mask_capable": True,
        "description": "Use a raster layer mask imported from a PSD or another layered document while keeping factor and inversion editable.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_GP_MASK_SLOT_2: {
        "label": "Grease Pencil Mask Slot 2", "icon": "OUTLINER_OB_GREASEPENCIL", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_GP_Mask_Slot_2_624",
        "asset_id": "frame_by_plane.shader.gp_mask_slot_2.624", "enabled_key": "fbp_effect_gp_mask_slot_2",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out", "uv_input_socket": "UV Vector",
        "debug_socket": "Debug Preview", "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte"), ("SOURCE", "Source")),
        "property_map": {"fbp_gp_mask_slot_2_factor": "Factor", "fbp_gp_mask_slot_2_invert": "Invert"},
        "extra_properties": ("fbp_gp_mask_slot_2_path",),
        "imported_mask_aware": True, "imported_mask_prefix": "fbp_gp_mask_slot_2",
        "private_group": True, "builtin": True, "layer_feature": True, "hidden": True,
        "local_mask_capable": True,
        "description": "Independent Grease Pencil raster mask slot for a local effect.",
        "category": "MASK", "performance": "LIGHT", "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_GP_MASK_SLOT_3: {
        "label": "Grease Pencil Mask Slot 3", "icon": "OUTLINER_OB_GREASEPENCIL", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_GP_Mask_Slot_3_624",
        "asset_id": "frame_by_plane.shader.gp_mask_slot_3.624", "enabled_key": "fbp_effect_gp_mask_slot_3",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out", "uv_input_socket": "UV Vector",
        "debug_socket": "Debug Preview", "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte"), ("SOURCE", "Source")),
        "property_map": {"fbp_gp_mask_slot_3_factor": "Factor", "fbp_gp_mask_slot_3_invert": "Invert"},
        "extra_properties": ("fbp_gp_mask_slot_3_path",),
        "imported_mask_aware": True, "imported_mask_prefix": "fbp_gp_mask_slot_3",
        "private_group": True, "builtin": True, "layer_feature": True, "hidden": True,
        "local_mask_capable": True,
        "description": "Independent Grease Pencil raster mask slot for a local effect.",
        "category": "MASK", "performance": "LIGHT", "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_GP_MASK_SLOT_4: {
        "label": "Grease Pencil Mask Slot 4", "icon": "OUTLINER_OB_GREASEPENCIL", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_GP_Mask_Slot_4_624",
        "asset_id": "frame_by_plane.shader.gp_mask_slot_4.624", "enabled_key": "fbp_effect_gp_mask_slot_4",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out", "uv_input_socket": "UV Vector",
        "debug_socket": "Debug Preview", "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte"), ("SOURCE", "Source")),
        "property_map": {"fbp_gp_mask_slot_4_factor": "Factor", "fbp_gp_mask_slot_4_invert": "Invert"},
        "extra_properties": ("fbp_gp_mask_slot_4_path",),
        "imported_mask_aware": True, "imported_mask_prefix": "fbp_gp_mask_slot_4",
        "private_group": True, "builtin": True, "layer_feature": True, "hidden": True,
        "local_mask_capable": True,
        "description": "Independent Grease Pencil raster mask slot for a local effect.",
        "category": "MASK", "performance": "LIGHT", "supports": ("IMAGE", "SEQUENCE", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_LAYER_BLEND: {
        "label": "Layer Blend", "icon": "NODE_MATERIAL", "kind": "SHADER", "stage": "COLOR",
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
        "layer_blend_contract_version": 2,
        "private_group": True, "builtin": True, "layer_feature": True,
        "description": "Blend this layer with the Image or flat Color Plane directly below it. Principal PSD and Procreate blend modes can be transferred automatically.",
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
        "source_names": (), "canonical_name": "FBP_SH_Luminance_Mask_640",
        "asset_id": "frame_by_plane.shader.luminance_mask.640", "enabled_key": "fbp_effect_luminance_mask",
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
        "label": "Channel Mask", "icon": "IMAGE_RGB", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Channel_Mask_640",
        "asset_id": "frame_by_plane.shader.channel_mask.640", "enabled_key": "fbp_effect_channel_mask",
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
        "source_names": (), "canonical_name": "FBP_SH_Gradient_Mask_640",
        "asset_id": "frame_by_plane.shader.gradient_mask.640", "enabled_key": "fbp_effect_gradient_mask",
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
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT", "COLOR", "GRADIENT"),
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
        "evolve_property": "fbp_noise_mask_seed", "evolve_amount": 1.0, "evolve_mode": "SEED_STEP", "supports_seed": True,
        "builtin": True,
        "description": "Create an animatable procedural noise mask in the layer UV space.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_VORONOI_MASK: {
        "label": "Voronoi Mask", "icon": "NODE_TEXTURE", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Voronoi_Mask_640",
        "asset_id": "frame_by_plane.shader.voronoi_mask.640", "enabled_key": "fbp_effect_voronoi_mask",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out",
        "uv_input_socket": "UV Vector", "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte")),
        "property_map": {
            "fbp_voronoi_mask_scale": "Scale",
            "fbp_voronoi_mask_angle": "Angle",
            "fbp_voronoi_mask_randomness": "Randomness",
            "fbp_voronoi_mask_threshold": "Threshold",
            "fbp_voronoi_mask_softness": "Softness",
            "fbp_voronoi_mask_seed": "Seed",
            "fbp_voronoi_mask_factor": "Factor",
            "fbp_voronoi_mask_invert": "Invert",
        },
        "evolve_property": "fbp_voronoi_mask_seed", "evolve_amount": 1.0, "evolve_mode": "SEED_STEP", "supports_seed": True,
        "builtin": True,
        "description": "Create a cellular procedural mask from a Voronoi texture in layer UV space.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_WAVE_MASK: {
        "label": "Wave Mask", "icon": "MOD_OCEAN", "kind": "SHADER", "stage": "MASK",
        "source_names": (), "canonical_name": "FBP_SH_Wave_Mask_640",
        "asset_id": "frame_by_plane.shader.wave_mask.640", "enabled_key": "fbp_effect_wave_mask",
        "input_socket": "Alpha In", "output_socket": "Alpha Out", "mask_output_socket": "Mask Out",
        "uv_input_socket": "UV Vector", "debug_socket": "Debug Preview",
        "debug_modes": (("FINAL", "Final"), ("MATTE", "Matte")),
        "property_map": {
            "fbp_wave_mask_scale": "Scale",
            "fbp_wave_mask_angle": "Angle",
            "fbp_wave_mask_distortion": "Distortion",
            "fbp_wave_mask_detail": "Detail",
            "fbp_wave_mask_detail_scale": "Detail Scale",
            "fbp_wave_mask_detail_roughness": "Detail Roughness",
            "fbp_wave_mask_phase": "Phase",
            "fbp_wave_mask_threshold": "Threshold",
            "fbp_wave_mask_softness": "Softness",
            "fbp_wave_mask_factor": "Factor",
            "fbp_wave_mask_invert": "Invert",
        },
        "evolve_property": "fbp_wave_mask_phase", "evolve_amount": 0.25,
        "supports_seed": True,
        "builtin": True,
        "description": "Create an animatable stripe or ripple mask from a Wave texture in layer UV space.",
        "category": "MASK", "performance": "LIGHT",
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT", "COLOR", "GRADIENT"),
    },
    FBP_EFFECT_SOLID_MASK: {
        "label": "Tint", "icon": "IMAGE", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Tint",), "canonical_name": "FBP_SH_Tint_450",
        "asset_id": "frame_by_plane.shader.tint.450", "enabled_key": "fbp_effect_solid_mask",
        "input_socket": "Color In", "output_socket": "Color Out",
        "property_map": {"fbp_solid_mask_color": "Mask Color", "fbp_solid_mask_factor": "Mask Factor"},
        "evolve_property": "fbp_solid_mask_factor", "evolve_amount": 0.25,
        "evolve_mode": "PING_PONG", "evolve_min": 0.0, "evolve_max": 1.0,
        "supports_seed": True,
    },
    FBP_EFFECT_HUE_SATURATION: {
        "label": "Hue & Saturation", "icon": "IMAGE_RGB", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Hue_Saturation",), "canonical_name": "FBP_SH_Hue_Saturation_450",
        "asset_id": "frame_by_plane.shader.hue_saturation.450", "enabled_key": "fbp_effect_hue_saturation",
        "input_socket": "Color In", "output_socket": "Color Out",
        "property_map": {"fbp_hue_saturation_hue": "Hue", "fbp_hue_saturation_saturation": "Saturation", "fbp_hue_saturation_value": "Value"},
        "evolve_property": "fbp_hue_saturation_hue", "evolve_amount": 0.125,
        "evolve_mode": "WRAP", "evolve_min": 0.0, "evolve_max": 1.0,
        "supports_seed": True,
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
        "label": "Invert", "icon": "SELECT_DIFFERENCE", "kind": "SHADER", "stage": "COLOR",
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
    FBP_EFFECT_GRADIENT_MAP: {
        "label": "Gradient Map", "icon": "COLOR", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Gradient_Map_625",
        "asset_id": "frame_by_plane.shader.gradient_map.625", "enabled_key": "fbp_effect_gradient_map",
        "input_socket": "Color In", "output_socket": "Color Out",
        "private_group": True, "rig_private_group": True, "builtin": True,
        "required_input_sockets": ("Factor",),
        "property_map": {"fbp_gradient_map_factor": "Factor"},
        "color_ramp_role": "GRADIENT_MAP",
        "description": "Figma-inspired Gradient Map that remaps source luminance through an editable Color Ramp while preserving alpha.",
    },
    FBP_EFFECT_CHANNEL_MIXER: {
        "label": "Channel Mixer", "icon": "SEQ_SPLITVIEW", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Channel_Mixer_625",
        "asset_id": "frame_by_plane.shader.channel_mixer.625", "enabled_key": "fbp_effect_channel_mixer",
        "input_socket": "Color In", "output_socket": "Color Out",
        "private_group": True, "rig_private_group": True, "builtin": True,
        "required_input_sockets": ("Red", "Green", "Blue", "Factor"),
        "property_map": {
            "fbp_channel_mixer_red": "Red",
            "fbp_channel_mixer_green": "Green",
            "fbp_channel_mixer_blue": "Blue",
            "fbp_channel_mixer_factor": "Factor",
        },
        "description": "Figma-inspired RGB channel gain mixer for false-color, grading and stylized image treatment.",
    },
    FBP_EFFECT_DITHER: {
        "label": "Dither", "icon": "ALIASED", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Dither_641",
        "asset_id": "frame_by_plane.shader.dither.641", "enabled_key": "fbp_effect_dither",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "private_group": True, "rig_private_group": True, "builtin": True,
        "uses_source_texel": True,
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT", "COLOR", "GRADIENT"),
        "required_input_sockets": ("UV Vector", "Style", "Size", "Texel X", "Texel Y", "Brightness", "Contrast", "Mono", "Mono Color", "Factor"),
        "property_map": {
            "fbp_dither_style": "Style",
            "fbp_dither_size": "Size",
            "fbp_dither_brightness": "Brightness",
            "fbp_dither_contrast": "Contrast",
            "fbp_dither_mono": "Mono",
            "fbp_dither_mono_color": "Mono Color",
            "fbp_dither_factor": "Factor",
        },
        "description": "True ordered dithering. Source luminance is compared against Bayer/noise threshold matrices to create square source-pixel dither cells.",
    },
    FBP_EFFECT_BLOOM: {
        "label": "Bloom", "icon": "LIGHT_SUN", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Bloom_626",
        "asset_id": "frame_by_plane.shader.bloom.626", "enabled_key": "fbp_effect_bloom",
        "input_socket": "Color In", "output_socket": "Color Out",
        "private_group": True, "rig_private_group": True, "builtin": True,
        "required_input_sockets": ("Threshold", "Softness", "Intensity", "Glow Color", "Factor"),
        "property_map": {
            "fbp_bloom_threshold": "Threshold",
            "fbp_bloom_softness": "Softness",
            "fbp_bloom_intensity": "Intensity",
            "fbp_bloom_color": "Glow Color",
            "fbp_bloom_factor": "Factor",
        },
        "description": "Figma-inspired bloom/glow pass for highlights, luminous cards and painterly light accents.",
    },
    FBP_EFFECT_FILTER_PRESETS: {
        "label": "Filter Presets", "icon": "PRESET", "kind": "SHADER", "stage": "COLOR",
        "source_names": (), "canonical_name": "FBP_SH_Filter_Presets_627",
        "asset_id": "frame_by_plane.shader.filter_presets.627", "enabled_key": "fbp_effect_filter_presets",
        "input_socket": "Color In", "output_socket": "Color Out",
        "private_group": True, "rig_private_group": True, "builtin": True,
        "required_input_sockets": ("Sepia", "Warm", "Cool", "Noir", "Factor"),
        "property_map": {
            "fbp_filter_preset_sepia": "Sepia",
            "fbp_filter_preset_warm": "Warm",
            "fbp_filter_preset_cool": "Cool",
            "fbp_filter_preset_noir": "Noir",
            "fbp_filter_preset_factor": "Factor",
        },
        "description": "Figma-inspired quick filter stack for sepia, warm, cool and noir looks with one final intensity control.",
    },
    FBP_EFFECT_GRAIN: {
        "label": "Grain", "icon": "RNDCURVE", "kind": "SHADER", "stage": "COLOR",
        "source_names": ("FBP_Film_Grain",), "canonical_name": "FBP_SH_Film_Grain_450",
        "asset_id": "frame_by_plane.shader.film_grain.450", "enabled_key": "fbp_effect_grain",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "property_map": {"fbp_grain_strength": "Intensity", "fbp_grain_scale": "Grain Scale", "fbp_grain_seed": "Animate (W)"},
        "evolve_property": "fbp_grain_seed", "evolve_amount": 1.0, "evolve_mode": "SEED_STEP", "supports_seed": True,
        
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
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        # Gradient Light consumes the already-evaluated Color/UV stream and
        # does not sample a private image texture. Keeping it image-aware made
        # the generated group fail its own contract and scheduled needless
        # source synchronization on every animated frame.
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
        "source_names": ("FBP_SH_Rim_611", "FBP_SH_Rim_617", "FBP_SH_Rim_6021", "FBP_SH_Rim_6022"), "canonical_name": "FBP_SH_Rim_6100",
        "asset_id": "frame_by_plane.shader.rim.6100", "enabled_key": "fbp_effect_rim",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "image_aware": True, "private_group": True, "builtin": True,
        "performance": "HEAVY",
        "required_input_sockets": ("Use Image Sample", "Mode", "Blend Mode", "Width", "Expand / Shrink", "Offset X", "Offset Y", "Rotation", "Blur", "Softness", "Intensity", "Rim Color"),
        "property_map": {
            "fbp_rim_mode": "Mode",
            "fbp_rim_blend_mode": "Blend Mode",
            "fbp_rim_width": "Width",
            "fbp_rim_expand": "Expand / Shrink",
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
        "label": "Vignette", "icon": "IMAGE_ALPHA", "kind": "SHADER", "stage": "COLOR",
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
        "evolve_property": "fbp_posterize_steps", "evolve_amount": 4.0,
        "evolve_mode": "PING_PONG", "evolve_min": 2.0, "evolve_max": 64.0,
        "supports_seed": True,
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
        "label": "Fade", "icon": "IMAGE_ALPHA", "kind": "SHADER", "stage": "COLOR",
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
        "ui_labels": {"fbp_digital_noise_seed": "Base W"},
        "evolve_property": "fbp_digital_noise_seed", "evolve_amount": 1.0, "evolve_mode": "SEED_STEP", "supports_seed": True,
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
        "canonical_name": "FBP_SH_Halftone_621",
        "asset_id": "frame_by_plane.shader.halftone.621", "enabled_key": "fbp_effect_halftone",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "required_input_sockets": ("Aspect Ratio", "Pattern", "Color Mode", "Shape", "Dot Scale", "Blend", "Softness", "Center X", "Center Y", "Clip to Alpha"),
        "property_map": {
            "fbp_halftone_pattern": "Pattern", "fbp_halftone_color_mode": "Color Mode",
            "fbp_halftone_scale": "Cell Scale", "fbp_halftone_dot_size": "Dot Size",
            "fbp_halftone_dot_scale": "Dot Scale", "fbp_halftone_blend": "Blend", "fbp_halftone_softness": "Softness",
            "fbp_halftone_rotation": "Rotation", "fbp_halftone_contrast": "Contrast",
            "fbp_halftone_invert": "Invert",
            "fbp_halftone_shape": "Shape",
            "fbp_halftone_use_source_color": "Use Source Color",
            "fbp_halftone_foreground": "Foreground",
            "fbp_halftone_background": "Background",
            "fbp_halftone_transparent_background": "Transparent Background",
            "fbp_halftone_center_x": "Center X", "fbp_halftone_center_y": "Center Y",
            "fbp_halftone_clip_alpha": "Clip to Alpha",
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
        "ui_labels": {"fbp_dot_matrix_seed": "Base Seed"},
        "evolve_property": "fbp_dot_matrix_seed", "evolve_amount": 1.0,
        "evolve_mode": "SEED_STEP", "supports_seed": True,
        "debug_modes": (("FINAL", "Final"), ("LUMINANCE", "Luminance"), ("MASK", "Mask")),
        "debug_socket": "Debug Mode",
        "private_group": True, "image_aware": True, "builtin": True,
    },
    FBP_EFFECT_ASCII_MATRIX: {
        "label": "Textellation", "icon": "SYNTAX_OFF", "kind": "SHADER", "stage": "COLOR",
        "canonical_name": "FBP_SH_Textellation_486",
        "asset_id": "frame_by_plane.shader.textellation.486", "enabled_key": "fbp_effect_ascii_matrix",
        "input_socket": "Color In", "output_socket": "Color Out", "uv_input_socket": "UV Vector",
        "alpha_input_socket": "Alpha In", "alpha_output_socket": "Alpha Out",
        "property_map": {
            "fbp_ascii_scale": "Cell Scale", "fbp_ascii_contrast": "Contrast",
            "fbp_ascii_invert": "Invert", "fbp_ascii_colorize": "Use Source Color",
            "fbp_ascii_foreground": "Foreground", "fbp_ascii_background": "Background",
            "fbp_ascii_transparent_background": "Transparent Background",
            "fbp_ascii_variation": "Variation", "fbp_ascii_random_seed": "Seed",
            "fbp_ascii_gamma": "Gamma",
            "fbp_ascii_glyph_scale": "Glyph Scale",
            "fbp_ascii_glyph_width": "Glyph Width",
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
        "ui_labels": {"fbp_terminal_ascii_seed": "Base Seed"},
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
        "supports": ("IMAGE", "SEQUENCE", "VIDEO", "CUTOUT"), "builtin": True, "prebundled": True,
    },
}


FBP_EFFECT_METADATA = {
    FBP_EFFECT_CROP: ("BASE", "LIGHT", "Crop the visible borders without changing the rig transform. The operation is non-destructive and can be animated."),
    FBP_EFFECT_EXTEND: ("BASE", "LIGHT", "Extend the plane borders while preserving the central image. Edge Pixel clamps, Transparent creates empty canvas, Repeat Texture tiles the source, and Repeat Flipped alternates mirrored tiles for seamless infinite borders."),
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
    FBP_EFFECT_GRADIENT_MAP: ("2D", "LIGHT", "Figma-inspired Gradient Map that remaps source luminance through an editable Color Ramp."),
    FBP_EFFECT_CHANNEL_MIXER: ("2D", "LIGHT", "Figma-inspired Channel Mixer for RGB channel gain, false color and compact grading workflows."),
    FBP_EFFECT_DITHER: ("2D", "LIGHT", "Figma-inspired ordered dither for retro print, risograph and low-color graphics."),
    FBP_EFFECT_BLOOM: ("2D", "MEDIUM", "Figma-inspired highlight bloom/glow. Softness and intensity can add extra color processing cost."),
    FBP_EFFECT_FILTER_PRESETS: ("2D", "LIGHT", "Figma-inspired quick color presets for sepia, warm, cool and noir treatments."),
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
    FBP_EFFECT_SLICE_SHIFT: ("2D", "LIGHT", "Figma-inspired slice shift that cuts UVs into angled bands and offsets them with optional per-band randomness."),
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
    FBP_EFFECT_EMISSION: ("2D", "LIGHT", "Switch the owned layer material to a real Emission shader with directly editable high-dynamic-range strength."),
    FBP_EFFECT_LAYER_BLEND: ("2D", "LIGHT", "Blend the current layer against the image layer directly below it using a principal PSD or Procreate blend mode."),
    FBP_EFFECT_COLOR_MASK: ("MASK", "LIGHT", "Select pixels close to a chosen color and use the result as a layer or per-effect mask."),
    FBP_EFFECT_LUMINANCE_MASK: ("MASK", "LIGHT", "Select a luminance interval from the current image or sequence and use it as a layer or per-effect mask."),
    FBP_EFFECT_CHANNEL_MASK: ("MASK", "LIGHT", "Select a value interval from the red, green, blue, alpha or luminance channel of the current image or sequence."),
    FBP_EFFECT_GRADIENT_MASK: ("MASK", "LIGHT", "Create a linear or radial procedural mask with editable center, angle, scale and feather."),
    FBP_EFFECT_NOISE_MASK: ("MASK", "LIGHT", "Create an animatable procedural noise mask with threshold and softness controls."),
    FBP_EFFECT_VORONOI_MASK: ("MASK", "LIGHT", "Create a cellular procedural mask with scale, randomness, threshold and softness controls."),
    FBP_EFFECT_WAVE_MASK: ("MASK", "LIGHT", "Create an animatable stripe or ripple mask with distortion, phase, threshold and softness controls."),
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
    FBP_EFFECT_RIM: ("2D", "MEDIUM", "Create a Grease-Pencil-like inner, outer or two-sided colored rim with grow/shrink, spatial blur and editable blend modes."),
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
    FBP_EFFECT_FIBER_TUFTS: ("3D", "MEDIUM", "Generate lightweight alpha-aware fiber clumps as shared instances over an aspect-balanced sampling grid. Density is reduced independently in the viewport."),
    FBP_EFFECT_PAPER_SHARDS: ("3D", "MEDIUM", "Scatter alpha-aware paper chips over an aspect-balanced sampling grid. Keeping instances unrealized reduces memory use at high density."),
    FBP_EFFECT_SPHERE_SCREEN: ("3D", "HEAVY", "Rebuild the source as a luminous matrix of selectable shared solids with sampled color and multiple depth algorithms."),
    FBP_EFFECT_IMAGE_RELIEF: ("3D", "HEAVY", "Displace an aspect-balanced triangular grid from luminance, shadows, saturation or a custom depth image. Point budget remains close to the former square grid."),
    FBP_EFFECT_GLASS: ("3D", "HEAVY", "Cut an aspect-balanced quad grid into procedural shards. Mesh Bevel is bypassed at zero; positive bevel values add real topology only along sharp edges."),
    FBP_EFFECT_CRYSTAL: ("3D", "HEAVY", "Build an exact-cut rounded alpha relief. Adaptive refinement spends the requested edge density on the painted alpha region instead of the transparent canvas; Roundness Passes remain iterative."),
    FBP_EFFECT_SURFACE_CONFORM: ("3D", "HEAVY", "Project an aspect-balanced triangular grid through one nearest-surface sample per point. Remesh level has the strongest performance impact."),
    FBP_EFFECT_ACCORDION_FOLD: ("3D", "MEDIUM", "Fold an aspect-balanced triangular grid with an animatable profile. Playback and render use independent remesh quality."),
    FBP_EFFECT_SCULPT_WAVES: ("3D", "MEDIUM", "Sculpt an aspect-balanced triangular grid with radial, moiré or spiral fields. Remesh level controls most of the cost."),
    FBP_EFFECT_KINETIC_TILES: ("3D", "MEDIUM", "Split an aspect-balanced grid into near-square individually extruded tiles. Remesh level controls tile count and evaluation cost."),
    FBP_EFFECT_LAYERED_ECHO: ("3D", "LIGHT", "Array the textured plane with per-axis offset, rotation, scale, twist and animated wave controls. Layer count is the main cost."),
    FBP_EFFECT_LATTICE: ("3D", "LIGHT", "Deform the linked plane through a planar control grid with one selectable point per intersection, or bake its 3D perspective into a camera-parallel surface while preserving the same camera appearance."),
}

# Built-in image-pipeline effects share the same plane contract unless they
# explicitly opt into a narrower list. Keep one canonical default so the hot
# lookup cache and the fallback path cannot disagree after reload/Undo.
FBP_DEFAULT_PLANE_MEDIA_SUPPORT = (
    "IMAGE", "SEQUENCE", "VIDEO", "CUTOUT", "COLOR", "GRADIENT",
)


for _effect_id, (_category, _performance, _description) in FBP_EFFECT_METADATA.items():
    _definition = FBP_EFFECT_REGISTRY.get(_effect_id)
    if _definition is None:
        continue
    _definition.setdefault("category", _category)
    _definition.setdefault("performance", _performance)
    _definition.setdefault("description", _description)
    _definition.setdefault("supports", FBP_DEFAULT_PLANE_MEDIA_SUPPORT)

# Effects in this controlled rollout use only scalar socket-backed properties,
# share immutable node groups and keep all mutable state on the concrete node or
# instance animation channels. Contextual, ramp, pointer and mask-stage effects
# remain SINGLE until their dedicated UI/runtime contracts become instance-safe.
FBP_MULTI_INSTANCE_SUPPORTED_EFFECTS = frozenset((
    FBP_EFFECT_GRAIN,
    FBP_EFFECT_GAUSSIAN_BLUR,
    FBP_EFFECT_WAVE_WARP,
    FBP_EFFECT_UV_DISTORTION,
    FBP_EFFECT_TRIANGLE_BLUR,
    FBP_EFFECT_UNSHARP_MASK,
    FBP_EFFECT_SMOOTH_TOON,
    FBP_EFFECT_ADAPTIVE_THRESHOLD,
    FBP_EFFECT_HUE_SATURATION,
    FBP_EFFECT_WHITE_BALANCE,
    FBP_EFFECT_BRIGHTNESS_CONTRAST,
    FBP_EFFECT_INVERT,
    FBP_EFFECT_THRESHOLD,
    FBP_EFFECT_PAPER_FIBERS,
    FBP_EFFECT_CRT_SCANLINES,
    FBP_EFFECT_VIGNETTE,
    FBP_EFFECT_POSTERIZE,
    FBP_EFFECT_SOLARIZE,
    FBP_EFFECT_DIGITAL_NOISE,
))

for _effect_id in FBP_MULTI_INSTANCE_SUPPORTED_EFFECTS:
    _definition = FBP_EFFECT_REGISTRY.get(_effect_id)
    if _definition is not None:
        _definition["instance_policy"] = "MULTI"
        _definition["instance_support"] = "SUPPORTED"

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

# Hot lookup caches used by UI drawing, compatibility checks and property
# callbacks.  They avoid rebuilding temporary ``set(...)`` objects for every
# effect button, stack row and RNA update.  Custom effects rebuild their own
# entries when the custom registry changes.
_FBP_EFFECT_ALLOWED_PROPS_CACHE = globals().get("_FBP_EFFECT_ALLOWED_PROPS_CACHE", {})
if not isinstance(_FBP_EFFECT_ALLOWED_PROPS_CACHE, dict):
    _FBP_EFFECT_ALLOWED_PROPS_CACHE = {}
_FBP_RIG_MESH_PLANE_CACHE = globals().get("_FBP_RIG_MESH_PLANE_CACHE", {})
if not isinstance(_FBP_RIG_MESH_PLANE_CACHE, dict):
    _FBP_RIG_MESH_PLANE_CACHE = {}
_FBP_RIG_MEDIA_TYPE_CACHE = globals().get("_FBP_RIG_MEDIA_TYPE_CACHE", {})
if not isinstance(_FBP_RIG_MEDIA_TYPE_CACHE, dict):
    _FBP_RIG_MEDIA_TYPE_CACHE = {}
_FBP_EFFECT_SUPPORT_FOR_RIG_CACHE = globals().get("_FBP_EFFECT_SUPPORT_FOR_RIG_CACHE", {})
if not isinstance(_FBP_EFFECT_SUPPORT_FOR_RIG_CACHE, dict):
    _FBP_EFFECT_SUPPORT_FOR_RIG_CACHE = {}
_FBP_EFFECT_TOOLTIP_CACHE = globals().get("_FBP_EFFECT_TOOLTIP_CACHE", {})
if not isinstance(_FBP_EFFECT_TOOLTIP_CACHE, dict):
    _FBP_EFFECT_TOOLTIP_CACHE = {}
_FBP_EFFECT_SUPPORTS_MEDIA_CACHE = globals().get("_FBP_EFFECT_SUPPORTS_MEDIA_CACHE", {})
if not isinstance(_FBP_EFFECT_SUPPORTS_MEDIA_CACHE, dict):
    _FBP_EFFECT_SUPPORTS_MEDIA_CACHE = {}
_FBP_EFFECT_RUNTIME_CONTRACT_CACHE = globals().get(
    "_FBP_EFFECT_RUNTIME_CONTRACT_CACHE", {}
)
if not isinstance(_FBP_EFFECT_RUNTIME_CONTRACT_CACHE, dict):
    _FBP_EFFECT_RUNTIME_CONTRACT_CACHE = {}
# The owner index stores only primitive names. Blender Object wrappers are
# resolved afresh at each use so Undo, Delete and file reload cannot leave stale
# RNA objects in this global cache.
_FBP_PLANE_OWNER_INDEX = {
    "object_count": -1,
    "by_owner": {},
    "checked_at": 0.0,
}


def _fbp_compile_effect_runtime_contract(effect_id, definition):
    """Compile immutable values used by hot UI and compatibility paths."""
    kind = str(definition.get("kind", "") or "").upper()
    return {
        "effect_id": str(effect_id or ""),
        "kind": kind,
        "category": str(definition.get("category", "2D") or "2D").upper(),
        "supports": frozenset(definition.get("supports", FBP_DEFAULT_PLANE_MEDIA_SUPPORT)),
        "targets": frozenset(definition.get("targets", ())),
        "requires_mesh_plane": bool(
            definition.get("requires_mesh_plane", False) or kind == "SHADER"
        ),
        "node_tree_type": str(definition.get("node_tree_type", "") or ""),
        "asset_id": str(definition.get("asset_id", "") or ""),
        "evolve_property": str(definition.get("evolve_property", "") or ""),
        "evolve_speed_property": str(
            definition.get("evolve_speed_property", "") or ""
        ),
    }


def fbp_effect_runtime_contract(effect_id):
    """Return the precompiled runtime contract for one registered effect."""
    effect_id = fbp_normalize_effect_id(effect_id)
    cached = _FBP_EFFECT_RUNTIME_CONTRACT_CACHE.get(effect_id)
    if cached is not None:
        return cached
    definition = fbp_effect_definition(effect_id)
    if not definition:
        return {}
    cached = _fbp_compile_effect_runtime_contract(effect_id, definition)
    _FBP_EFFECT_RUNTIME_CONTRACT_CACHE[effect_id] = cached
    return cached


def _fbp_rebuild_effect_lookup_caches(effect_ids=None):
    # Rig/object compatibility depends on live Blender pointers. Any registry
    # rebuild (including extension reload and custom-effect refresh) invalidates
    # those pointer-sensitive results; retaining an old False entry caused
    # otherwise valid planes to reject effects such as Wave Warp after Undo.
    _FBP_EFFECT_SUPPORT_FOR_RIG_CACHE.clear()
    _FBP_RIG_MESH_PLANE_CACHE.clear()
    ids = tuple(effect_ids or FBP_EFFECT_REGISTRY.keys())
    for effect_id in ids:
        definition = FBP_EFFECT_REGISTRY.get(effect_id) or {}
        _FBP_EFFECT_ALLOWED_PROPS_CACHE[effect_id] = frozenset(
            tuple((definition.get("property_map", {}) or {}).keys())
            + tuple(definition.get("extra_properties", ()) or ())
        )
        _FBP_EFFECT_RUNTIME_CONTRACT_CACHE[effect_id] = (
            _fbp_compile_effect_runtime_contract(effect_id, definition)
        )
    return True


def _fbp_drop_effect_lookup_cache(effect_id):
    _FBP_EFFECT_ALLOWED_PROPS_CACHE.pop(effect_id, None)
    _FBP_EFFECT_RUNTIME_CONTRACT_CACHE.pop(effect_id, None)
    _FBP_EFFECT_TOOLTIP_CACHE.pop(effect_id, None)
    for cache_key in tuple(_FBP_EFFECT_SUPPORTS_MEDIA_CACHE.keys()):
        try:
            if cache_key[0] == effect_id:
                _FBP_EFFECT_SUPPORTS_MEDIA_CACHE.pop(cache_key, None)
        except (TypeError, IndexError):
            _FBP_EFFECT_SUPPORTS_MEDIA_CACHE.pop(cache_key, None)
    for cache_key in tuple(_FBP_EFFECT_SUPPORT_FOR_RIG_CACHE.keys()):
        try:
            if cache_key[-1] == effect_id:
                _FBP_EFFECT_SUPPORT_FOR_RIG_CACHE.pop(cache_key, None)
        except (TypeError, IndexError):
            _FBP_EFFECT_SUPPORT_FOR_RIG_CACHE.pop(cache_key, None)


def fbp_effect_allowed_property_names(effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    cached = _FBP_EFFECT_ALLOWED_PROPS_CACHE.get(effect_id)
    if cached is not None:
        return cached
    definition = FBP_EFFECT_REGISTRY.get(effect_id) or {}
    cached = frozenset(
        tuple((definition.get("property_map", {}) or {}).keys())
        + tuple(definition.get("extra_properties", ()) or ())
    )
    _FBP_EFFECT_ALLOWED_PROPS_CACHE[effect_id] = cached
    return cached


_fbp_rebuild_effect_lookup_caches()


def _fbp_purge_custom_effect_definitions():
    """Remove runtime custom entries while preserving the built-in registry."""
    removed = False
    for effect_id, definition in tuple(FBP_EFFECT_REGISTRY.items()):
        if is_custom_effect_id(effect_id) or bool(
            isinstance(definition, dict) and definition.get("custom", False)
        ):
            FBP_EFFECT_REGISTRY.pop(effect_id, None)
            _fbp_drop_effect_lookup_cache(effect_id)
            removed = True
    _FBP_CUSTOM_EFFECT_MISS_CACHE.clear()
    _FBP_RIG_MESH_PLANE_CACHE.clear()
    _FBP_RIG_MEDIA_TYPE_CACHE.clear()
    _FBP_EFFECT_SUPPORT_FOR_RIG_CACHE.clear()
    _FBP_EFFECT_SUPPORTS_MEDIA_CACHE.clear()
    _FBP_EFFECT_RUNTIME_CONTRACT_CACHE.clear()
    _FBP_EFFECT_TOOLTIP_CACHE.clear()
    _FBP_PLANE_OWNER_INDEX["object_count"] = -1
    _FBP_PLANE_OWNER_INDEX["by_owner"] = {}
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
        _fbp_rebuild_effect_lookup_caches(custom_ids)
        for effect_id in custom_ids:
            _FBP_CUSTOM_EFFECT_MISS_CACHE.pop(effect_id, None)
    return custom_ids


FBP_SHADER_STAGE_ORDER = {
    "UV": (FBP_EFFECT_UV_DISTORTION, FBP_EFFECT_PIXELATE, FBP_EFFECT_SWIRL, FBP_EFFECT_BULGE_PINCH, FBP_EFFECT_LENS_WARP, FBP_EFFECT_WAVE_WARP, FBP_EFFECT_RIPPLE_DISTORTION, FBP_EFFECT_KALEIDOSCOPE, FBP_EFFECT_HEX_PIXELATE, FBP_EFFECT_MOSAIC_JITTER, FBP_EFFECT_SLICE_SHIFT),
    "MASK": (
        FBP_EFFECT_CLIPPING_MASK, FBP_EFFECT_IMPORTED_MASK, FBP_EFFECT_ALPHA_MATTE, FBP_EFFECT_LUMA_MATTE,
        FBP_EFFECT_COLOR_MASK, FBP_EFFECT_LUMINANCE_MASK, FBP_EFFECT_CHANNEL_MASK, FBP_EFFECT_GRADIENT_MASK, FBP_EFFECT_NOISE_MASK, FBP_EFFECT_VORONOI_MASK, FBP_EFFECT_WAVE_MASK,
        FBP_EFFECT_SQUARE_MASK, FBP_EFFECT_CIRCLE_MASK, FBP_EFFECT_TRIANGLE_MASK,
    ),
    "COLOR": (
        FBP_EFFECT_LAYER_BLEND, FBP_EFFECT_DEPTH_BLUR, FBP_EFFECT_GAUSSIAN_BLUR, FBP_EFFECT_DIRECTIONAL_BLUR, FBP_EFFECT_TRIANGLE_BLUR, FBP_EFFECT_TILT_SHIFT, FBP_EFFECT_UNSHARP_MASK, FBP_EFFECT_EDGE_DETECT, FBP_EFFECT_INK, FBP_EFFECT_EDGE_WORK, FBP_EFFECT_PENCIL_SKETCH, FBP_EFFECT_POSTER_EDGES, FBP_EFFECT_CROSSHATCH, FBP_EFFECT_EMBOSS, FBP_EFFECT_ADAPTIVE_THRESHOLD, FBP_EFFECT_CHROMATIC_ABERRATION, FBP_EFFECT_CHROMA_KEY, FBP_EFFECT_SOLID_MASK, FBP_EFFECT_HUE_SATURATION,
        FBP_EFFECT_WHITE_BALANCE, FBP_EFFECT_CURVES, FBP_EFFECT_BRIGHTNESS_CONTRAST, FBP_EFFECT_INVERT, FBP_EFFECT_THRESHOLD,
        FBP_EFFECT_COLOR_ISOLATE, FBP_EFFECT_DUOTONE, FBP_EFFECT_RECOLOR, FBP_EFFECT_GRADIENT_MAP, FBP_EFFECT_CHANNEL_MIXER, FBP_EFFECT_DITHER, FBP_EFFECT_BLOOM, FBP_EFFECT_FILTER_PRESETS, FBP_EFFECT_HALFTONE,
        FBP_EFFECT_DOT_MATRIX, FBP_EFFECT_ASCII_MATRIX, FBP_EFFECT_ASCII, FBP_EFFECT_GRAIN,
        FBP_EFFECT_DIGITAL_NOISE,
        FBP_EFFECT_PAPER_FIBERS, FBP_EFFECT_GRADIENT_LIGHT, FBP_EFFECT_RIM, FBP_EFFECT_SHADOW, FBP_EFFECT_GOBO_SHADOWS,
        FBP_EFFECT_CRT_SCANLINES, FBP_EFFECT_VIGNETTE, FBP_EFFECT_POSTERIZE,
        FBP_EFFECT_SOLARIZE, FBP_EFFECT_TRITONE, FBP_EFFECT_FILM_FADE, FBP_EFFECT_SMOOTH_TOON, FBP_EFFECT_FALSE_COLOR,
    ),
}

FBP_BASE_EFFECT_MENU_ORDER = (
    FBP_EFFECT_CROP, FBP_EFFECT_EXTEND, FBP_EFFECT_EMISSION, FBP_EFFECT_HUE_SATURATION,
    FBP_EFFECT_WHITE_BALANCE, FBP_EFFECT_BRIGHTNESS_CONTRAST, FBP_EFFECT_CURVES,
    FBP_EFFECT_SOLID_MASK, FBP_EFFECT_DUOTONE, FBP_EFFECT_TRITONE, FBP_EFFECT_RECOLOR,
    FBP_EFFECT_VIGNETTE, FBP_EFFECT_GRADIENT_LIGHT, FBP_EFFECT_RIM, FBP_EFFECT_SHADOW,
    FBP_EFFECT_CHROMA_KEY, FBP_EFFECT_INVERT, FBP_EFFECT_UNSHARP_MASK,
    FBP_EFFECT_THRESHOLD, FBP_EFFECT_COLOR_ISOLATE,
)
FBP_3D_EFFECT_MENU_ORDER = (
    FBP_EFFECT_CAMERA_SCALE_LOCK, FBP_EFFECT_CAMERA_BILLBOARD, FBP_EFFECT_MIRROR,
    FBP_EFFECT_MOTION,
    FBP_EFFECT_LATTICE, FBP_EFFECT_MESH_WIGGLE, FBP_EFFECT_STOP_MOTION_CRUMPLE,
    FBP_EFFECT_WIND_BENDER, FBP_EFFECT_INFINITE_ROTATION, FBP_EFFECT_CUTOUT_OUTLINE,
    FBP_EFFECT_THICKNESS, FBP_EFFECT_FELT_FUZZ, FBP_EFFECT_FIBER_TUFTS,
    FBP_EFFECT_PAPER_SHARDS, FBP_EFFECT_SPHERE_SCREEN, FBP_EFFECT_IMAGE_RELIEF, FBP_EFFECT_GLASS, FBP_EFFECT_CRYSTAL,
    FBP_EFFECT_SURFACE_CONFORM, FBP_EFFECT_ACCORDION_FOLD,
    FBP_EFFECT_SCULPT_WAVES, FBP_EFFECT_KINETIC_TILES,
    FBP_EFFECT_LAYERED_ECHO, FBP_EFFECT_TEXT_MATRIX,
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
            (FBP_EFFECT_GRADIENT_MAP, "Gradient Map"),
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
        "label": "Warp", "icon": "MOD_WARP", "default": FBP_EFFECT_WAVE_WARP,
        "variants": (
            (FBP_EFFECT_WAVE_WARP, "Sine wave"),
            (FBP_EFFECT_SWIRL, "Swirl"),
            (FBP_EFFECT_BULGE_PINCH, "Bulge / Pinch"),
            (FBP_EFFECT_RIPPLE_DISTORTION, "Ripple"),
            (FBP_EFFECT_LENS_WARP, "Lens"),
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
    ("Color", "COLOR", (
        FBP_EFFECT_CROP, FBP_EFFECT_EXTEND, FBP_EFFECT_HUE_SATURATION,
        FBP_EFFECT_WHITE_BALANCE, FBP_EFFECT_BRIGHTNESS_CONTRAST, FBP_EFFECT_CURVES,
        "FAMILY:COLORIZE", FBP_EFFECT_CHANNEL_MIXER, FBP_EFFECT_FILTER_PRESETS,
        FBP_EFFECT_VIGNETTE,
    )),
    ("Light", "OUTLINER_OB_LIGHT", (
        FBP_EFFECT_BLOOM, FBP_EFFECT_GRADIENT_LIGHT, FBP_EFFECT_RIM, FBP_EFFECT_SHADOW,
    )),
    ("Blur", "ONIONSKIN_ON", (
        FBP_EFFECT_GAUSSIAN_BLUR, "FAMILY:DIRECTIONAL_BLUR",
        FBP_EFFECT_DEPTH_BLUR, FBP_EFFECT_TRIANGLE_BLUR,
    )),
    ("Pixel / Print", "MESH_GRID", (
        "FAMILY:PIXELATE_MOSAIC", FBP_EFFECT_DITHER, FBP_EFFECT_HALFTONE,
        FBP_EFFECT_DOT_MATRIX, FBP_EFFECT_CROSSHATCH,
    )),
    ("Deform", "OUTLINER_OB_SURFACE", (
        FBP_EFFECT_UV_DISTORTION, FBP_EFFECT_WAVE_WARP, FBP_EFFECT_SWIRL,
        FBP_EFFECT_BULGE_PINCH, FBP_EFFECT_RIPPLE_DISTORTION, FBP_EFFECT_LENS_WARP,
        FBP_EFFECT_SLICE_SHIFT, FBP_EFFECT_KALEIDOSCOPE,
    )),
    ("Edges", "MOD_LINEART", (
        "FAMILY:EDGE", "FAMILY:STYLIZE", FBP_EFFECT_EMBOSS,
    )),
    ("Digital", "IMAGE_BACKGROUND", (
        FBP_EFFECT_CHROMATIC_ABERRATION, FBP_EFFECT_DIGITAL_NOISE,
        FBP_EFFECT_CRT_SCANLINES, FBP_EFFECT_ASCII_MATRIX, FBP_EFFECT_ASCII,
    )),
    ("Film", "RENDER_STILL", (
        FBP_EFFECT_SOLARIZE, FBP_EFFECT_FILM_FADE, FBP_EFFECT_GRAIN, FBP_EFFECT_PAPER_FIBERS,
    )),
    ("Magic", "SHADERFX", (
        FBP_EFFECT_CHROMA_KEY, FBP_EFFECT_INVERT, FBP_EFFECT_UNSHARP_MASK,
        FBP_EFFECT_THRESHOLD, FBP_EFFECT_COLOR_ISOLATE,
    )),
)
FBP_IMAGE_EFFECT_MENU_COLUMNS = (
    (0,),
    (1, 2),
    (3, 5),
    (4,),
    (6, 7),
    (8,),
)

FBP_MASK_EFFECT_MENU_SECTIONS = (
    ("Shape", "SURFACE_NCURVE", (FBP_EFFECT_SQUARE_MASK, FBP_EFFECT_CIRCLE_MASK, FBP_EFFECT_TRIANGLE_MASK)),
    ("Nodes", "NODE_INSERT_ON", (
        FBP_EFFECT_COLOR_MASK, FBP_EFFECT_LUMINANCE_MASK, FBP_EFFECT_CHANNEL_MASK,
        FBP_EFFECT_GRADIENT_MASK, FBP_EFFECT_NOISE_MASK, FBP_EFFECT_VORONOI_MASK, FBP_EFFECT_WAVE_MASK,
    )),
    ("Advanced", "SEQ_STRIP_MODIFIER", (
        "GREASE_PENCIL_MASK_CONTROL", FBP_EFFECT_IMPORTED_MASK, FBP_EFFECT_ALPHA_MATTE, FBP_EFFECT_LUMA_MATTE,
    )),
)
FBP_MASK_EFFECT_MENU_COLUMNS = ((0, 2), (1,))

FBP_MESH_EFFECT_MENU_SECTIONS = (
    ("CAMERA & LAYOUT", "CAMERA_DATA", (
        FBP_EFFECT_CAMERA_SCALE_LOCK, FBP_EFFECT_CAMERA_BILLBOARD, FBP_EFFECT_MIRROR,
        FBP_EFFECT_MOTION, FBP_EFFECT_INFINITE_ROTATION, FBP_EFFECT_LAYERED_ECHO,
    )),
    ("DEFORM", "MOD_SIMPLEDEFORM", (
        FBP_EFFECT_LATTICE, FBP_EFFECT_MESH_WIGGLE, FBP_EFFECT_STOP_MOTION_CRUMPLE,
        FBP_EFFECT_WIND_BENDER, FBP_EFFECT_ACCORDION_FOLD,
        FBP_EFFECT_SURFACE_CONFORM, FBP_EFFECT_IMAGE_RELIEF,
    )),
    ("SURFACE & VOLUME", "MOD_SOLIDIFY", (
        FBP_EFFECT_CUTOUT_OUTLINE, FBP_EFFECT_THICKNESS, FBP_EFFECT_FELT_FUZZ,
        FBP_EFFECT_FIBER_TUFTS, FBP_EFFECT_PAPER_SHARDS, FBP_EFFECT_GLASS, FBP_EFFECT_CRYSTAL,
    )),
    ("ARTISTIC", "SHADERFX", (
        FBP_EFFECT_SCULPT_WAVES, FBP_EFFECT_KINETIC_TILES,
    )),
    ("IMAGE GEOMETRY", "IMAGE_DATA", (
        FBP_EFFECT_SPHERE_SCREEN, FBP_EFFECT_TEXT_MATRIX,
    )),
)
FBP_MESH_EFFECT_MENU_COLUMNS = ((0,), (1,), (2,), (3, 4))


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


def fbp_effect_multi_instance_enabled(effect_id):
    """Return whether one built-in effect has the complete MULTI contract."""
    definition = fbp_effect_definition(effect_id)
    return (
        str(definition.get("instance_policy", "SINGLE") or "SINGLE").upper() == "MULTI"
        and str(definition.get("instance_support", "NONE") or "NONE").upper()
        in {"PILOT", "SUPPORTED"}
    )


def _fbp_rig_media_cache_key(rig):
    try:
        plane = getattr(rig, "fbp_plane_target", None)
        mesh = getattr(plane, "data", None) if plane else None
        materials = getattr(mesh, "materials", ()) if mesh else ()
        material_key = tuple(
            (
                str(getattr(material, "name", "") or ""),
                bool(material.get("fbp_drawing_material", False)),
                bool(material.get("fbp_native_sequence", False)),
                bool(material.get("fbp_native_video", False)),
                bool(material.get("fbp_native_static_image", False)),
            )
            for material in tuple(materials or ())
            if material is not None
        )
        return (
            int(rig.as_pointer()),
            str(getattr(rig, "name", "") or ""),
            bool(getattr(rig, "fbp_is_color_plane", False)),
            str(getattr(rig, "fbp_color_plane_mode", "SOLID") or "SOLID"),
            bool(getattr(rig, "fbp_is_drawing_plane", False)),
            str(rig.get("fbp_backend_type", "") or ""),
            len(getattr(rig, "fbp_images", ()) or ()),
            material_key,
        )
    except FBP_DATA_ERRORS:
        return None


def _cache_rig_media_type(cache_key, media_type):
    if cache_key is None:
        return media_type
    if len(_FBP_RIG_MEDIA_TYPE_CACHE) >= 2048 and cache_key not in _FBP_RIG_MEDIA_TYPE_CACHE:
        _FBP_RIG_MEDIA_TYPE_CACHE.clear()
    _FBP_RIG_MEDIA_TYPE_CACHE[cache_key] = media_type
    return media_type


def fbp_rig_media_type(rig):
    if not rig:
        return "UNKNOWN"
    cache_key = _fbp_rig_media_cache_key(rig)
    cached = _FBP_RIG_MEDIA_TYPE_CACHE.get(cache_key) if cache_key is not None else None
    if cached is not None:
        return cached
    if bool(getattr(rig, "fbp_is_color_plane", False)):
        mode = str(getattr(rig, "fbp_color_plane_mode", "SOLID") or "SOLID")
        if mode == "HOLDOUT":
            return _cache_rig_media_type(cache_key, "HOLDOUT")
        if mode == "GRADIENT":
            return _cache_rig_media_type(cache_key, "GRADIENT")
        return _cache_rig_media_type(cache_key, "COLOR")
    # Preserve distinct public asset contracts while sharing the same effect
    # pipeline underneath. This makes compatibility diagnostics meaningful for
    # Cutout and Movie layers instead of silently reporting them as stills.
    try:
        from .layers import fbp_layer_backend_type
        backend = str(fbp_layer_backend_type(rig) or "")
        if backend == "CUTOUT":
            return _cache_rig_media_type(cache_key, "CUTOUT")
        if backend == "NATIVE_MOVIE":
            return _cache_rig_media_type(cache_key, "VIDEO")
        if backend == "NATIVE_SEQUENCE":
            return _cache_rig_media_type(cache_key, "SEQUENCE")
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        result = "SEQUENCE" if len(getattr(rig, "fbp_images", ())) > 1 else "IMAGE"
    except FBP_DATA_ERRORS:
        result = "IMAGE"
    return _cache_rig_media_type(cache_key, result)

def _fbp_rebuild_plane_owner_index():
    """Build one bounded owner-name index for Undo plane recovery.

    Normal compatibility uses the direct ``fbp_plane_target`` pointer. The
    index is consulted only while Blender is repairing that pointer, avoiding a
    full ``bpy.data.objects`` scan for every effect button and selected layer.
    """
    try:
        objects = getattr(bpy.data, "objects", None)
        object_count = len(objects or ())
    except FBP_DATA_ERRORS:
        return {}
    by_owner = {}
    try:
        for candidate in objects or ():
            if candidate is None or str(getattr(candidate, "type", "") or "") != "MESH":
                continue
            mesh = getattr(candidate, "data", None)
            tagged_plane = bool(getattr(candidate, "is_fbp_plane", False))
            if not tagged_plane and mesh is not None:
                tagged_plane = bool(mesh.get("fbp_plane_mesh", False))
            owner_name = str(candidate.get("fbp_parent_rig_name", "") or "")
            parent = getattr(candidate, "parent", None)
            if not owner_name and parent is not None and bool(
                getattr(parent, "is_fbp_control", False)
            ):
                owner_name = str(getattr(parent, "name", "") or "")
            if tagged_plane and owner_name and owner_name not in by_owner:
                by_owner[owner_name] = str(getattr(candidate, "name", "") or "")
    except FBP_DATA_ERRORS:
        by_owner = {}
    _FBP_PLANE_OWNER_INDEX["object_count"] = object_count
    _FBP_PLANE_OWNER_INDEX["by_owner"] = by_owner
    _FBP_PLANE_OWNER_INDEX["checked_at"] = time.monotonic()
    return by_owner


def _fbp_indexed_plane_for_rig(rig):
    if rig is None:
        return None
    try:
        owner_name = str(getattr(rig, "name", "") or "")
        objects = getattr(bpy.data, "objects", None)
        object_count = len(objects or ())
    except FBP_DATA_ERRORS:
        return None
    now = time.monotonic()
    cached_count = int(_FBP_PLANE_OWNER_INDEX.get("object_count", -1) or -1)
    checked_at = float(_FBP_PLANE_OWNER_INDEX.get("checked_at", 0.0) or 0.0)
    by_owner = _FBP_PLANE_OWNER_INDEX.get("by_owner", {})
    if (
        cached_count != object_count
        or not isinstance(by_owner, dict)
        or (owner_name not in by_owner and now - checked_at > 0.50)
    ):
        by_owner = _fbp_rebuild_plane_owner_index()

    def resolve(candidate_name):
        if not candidate_name:
            return None
        try:
            candidate = objects.get(str(candidate_name))
            if candidate is None or str(getattr(candidate, "type", "") or "") != "MESH":
                return None
            mesh = getattr(candidate, "data", None)
            tagged_plane = bool(getattr(candidate, "is_fbp_plane", False))
            if not tagged_plane and mesh is not None:
                tagged_plane = bool(mesh.get("fbp_plane_mesh", False))
            if not tagged_plane:
                return None
            tagged_owner = str(candidate.get("fbp_parent_rig_name", "") or "")
            parent = getattr(candidate, "parent", None)
            return candidate if (tagged_owner == owner_name or parent is rig) else None
        except FBP_DATA_ERRORS:
            return None

    candidate_name = by_owner.get(owner_name) if isinstance(by_owner, dict) else ""
    candidate = resolve(candidate_name)
    if candidate is not None:
        return candidate
    if not candidate_name and now - checked_at <= 0.50:
        # Preserve the bounded negative cache for rigs that legitimately do not
        # own a plane. Repeated compatibility draws must not rescan bpy.data on
        # every call.
        return None

    # Same-count Undo and name reuse can leave a valid Mesh under the cached
    # name, but that Mesh may now belong to another rig. Rebuild on every stale
    # validation failure, not only when the object disappeared.
    rebuilt = _fbp_rebuild_plane_owner_index()
    candidate = resolve(rebuilt.get(owner_name, "") if isinstance(rebuilt, dict) else "")
    if candidate is None and isinstance(rebuilt, dict):
        rebuilt.pop(owner_name, None)
    return candidate


def _fbp_rig_has_mesh_plane(rig):
    """Return whether ``rig`` owns a usable Frame By Plane mesh plane.

    Compatibility checks must never cache a transient negative result. During
    import, Undo and pointer repair Blender can briefly expose the rig before
    ``fbp_plane_target`` is restored; the previous negative cache then made
    ordinary shader effects such as Wave Warp appear randomly incompatible.
    Positive results remain cached behind a relation signature.
    """
    if not rig:
        return False

    try:
        plane = getattr(rig, "fbp_plane_target", None)
        if plane is not None and str(getattr(plane, "type", "") or "") == "MESH":
            return True
    except FBP_DATA_ERRORS:
        plane = None

    try:
        owner_name = str(getattr(rig, "name", "") or "")
        children = tuple(getattr(rig, "children", ()) or ())
        children_sig = tuple(
            (
                int(child.as_pointer()),
                str(getattr(child, "name", "") or ""),
                str(getattr(child, "type", "") or ""),
                bool(getattr(child, "is_fbp_plane", False)),
                str(child.get("fbp_parent_rig_name", "") or ""),
            )
            for child in children
            if child is not None
        )
        object_count = len(getattr(bpy.data, "objects", ()) or ())
        cache_key = (int(rig.as_pointer()), owner_name, object_count, children_sig)
    except FBP_DATA_ERRORS:
        return False

    # Only a positive entry is authoritative. A False result can be a one-tick
    # import/Undo state and must be re-evaluated immediately on the next query.
    if _FBP_RIG_MESH_PLANE_CACHE.get(cache_key) is True:
        return True

    def is_owned_plane(candidate):
        if candidate is None:
            return False
        try:
            if str(getattr(candidate, "type", "") or "") != "MESH":
                return False
            if bool(getattr(candidate, "is_fbp_plane", False)):
                return True
            # A direct mesh child is the strongest ownership relationship.
            # During creation/Undo the custom plane tags can lag behind the
            # parent relation by one depsgraph tick, so do not reject it.
            if getattr(candidate, "parent", None) is rig:
                return True
            return str(candidate.get("fbp_parent_rig_name", "") or "") == owner_name
        except FBP_DATA_ERRORS:
            return False

    result = any(is_owned_plane(child) for child in children)
    if not result:
        # Undo fallback is indexed once instead of rescanning Main for
        # each compatibility query. This is especially important while the
        # Effects popover draws dozens of buttons across multiple layers.
        result = is_owned_plane(_fbp_indexed_plane_for_rig(rig))

    if result:
        if len(_FBP_RIG_MESH_PLANE_CACHE) >= 1024 and cache_key not in _FBP_RIG_MESH_PLANE_CACHE:
            _FBP_RIG_MESH_PLANE_CACHE.clear()
        _FBP_RIG_MESH_PLANE_CACHE[cache_key] = True
    return bool(result)


FBP_PUBLIC_MEDIA_TYPES = (
    "IMAGE", "SEQUENCE", "VIDEO", "CUTOUT", "COLOR", "GRADIENT", "HOLDOUT",
)


def fbp_effect_supports_media_type(effect_id, media_type):
    """Return compatibility for one public Frame By Plane asset contract.

    Movie and Cutout layers share the image-texture/alpha pipeline used by
    stills and image sequences. Holdout layers deliberately remain narrower:
    only explicitly compatible, BASE and GEOMETRY effects are accepted. Shader masks require an image/color pipeline and are rejected unless explicitly supported.
    """
    effect_id = fbp_normalize_effect_id(effect_id)
    media_type = str(media_type or "UNKNOWN").upper()
    cache_key = (effect_id, media_type)
    cached = _FBP_EFFECT_SUPPORTS_MEDIA_CACHE.get(cache_key)
    if cached is not None:
        return bool(cached)
    definition = fbp_effect_definition(effect_id)
    contract = fbp_effect_runtime_contract(effect_id)
    if not definition or not contract or bool(definition.get("custom_invalid", False)):
        result = False
    else:
        supports = contract["supports"]
        if media_type == "VIDEO":
            result = bool(("VIDEO" in supports) or ("SEQUENCE" in supports) or ("IMAGE" in supports))
        elif media_type == "CUTOUT":
            result = bool(("CUTOUT" in supports) or ("SEQUENCE" in supports) or ("IMAGE" in supports))
        elif media_type == "HOLDOUT":
            result = bool(
                "HOLDOUT" in supports
                or contract["kind"] in {"BASE", "GEOMETRY"}
            )
        else:
            result = media_type in supports
    if len(_FBP_EFFECT_SUPPORTS_MEDIA_CACHE) >= 1024 and cache_key not in _FBP_EFFECT_SUPPORTS_MEDIA_CACHE:
        _FBP_EFFECT_SUPPORTS_MEDIA_CACHE.clear()
    _FBP_EFFECT_SUPPORTS_MEDIA_CACHE[cache_key] = bool(result)
    return bool(result)


def fbp_effect_supported_for_rig(rig, effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    if not rig:
        return False
    try:
        plane = getattr(rig, "fbp_plane_target", None)
        rig_key = (
            int(rig.as_pointer()),
            str(getattr(rig, "name", "") or ""),
            fbp_rig_media_type(rig),
            int(plane.as_pointer()) if plane is not None else 0,
            str(getattr(plane, "name", "") or ""),
            effect_id,
        )
    except FBP_DATA_ERRORS:
        rig_key = None
    cached = _FBP_EFFECT_SUPPORT_FOR_RIG_CACHE.get(rig_key) if rig_key is not None else None
    # Only positive compatibility is safe to cache. During import, mode changes
    # and Undo, Blender can expose a rig for one event tick before its plane
    # pointer/ownership tags are restored. Caching that transient False made
    # compatibility failures appear random until another object was created.
    if cached is True:
        return True
    definition = fbp_effect_definition(effect_id)
    contract = fbp_effect_runtime_contract(effect_id)
    if not definition or not contract or bool(definition.get("custom_invalid", False)):
        result = False
    elif "IMAGE_PLANE" not in contract["targets"]:
        result = False
    elif contract["requires_mesh_plane"] and not _fbp_rig_has_mesh_plane(rig):
        # Shader effects and explicitly mesh-bound geometry effects require the
        # actual plane, not a selected GP canvas/helper that resolves to a rig.
        result = False
    else:
        media_type = rig_key[2] if rig_key is not None else fbp_rig_media_type(rig)
        result = fbp_effect_supports_media_type(effect_id, media_type)
    if rig_key is not None and result:
        if len(_FBP_EFFECT_SUPPORT_FOR_RIG_CACHE) >= 4096 and rig_key not in _FBP_EFFECT_SUPPORT_FOR_RIG_CACHE:
            _FBP_EFFECT_SUPPORT_FOR_RIG_CACHE.clear()
        _FBP_EFFECT_SUPPORT_FOR_RIG_CACHE[rig_key] = True
    return bool(result)


def fbp_effect_compatibility_matrix(effect_ids=None):
    """Return a deterministic public asset compatibility matrix for audits/UI."""
    ids = tuple(effect_ids or FBP_EFFECT_REGISTRY.keys())
    return {
        effect_id: {
            media_type: fbp_effect_supports_media_type(effect_id, media_type)
            for media_type in FBP_PUBLIC_MEDIA_TYPES
        }
        for effect_id in ids
        if fbp_effect_definition(effect_id)
    }


def fbp_effect_supports_target(effect_id, target):
    """Return whether an effect explicitly supports one 6.2 target contract."""
    contract = fbp_effect_runtime_contract(effect_id)
    target = str(target or "").strip().upper()
    return bool(contract and target and target in contract["targets"])

def fbp_effect_tooltip(effect_id):
    effect_id = fbp_normalize_effect_id(effect_id)
    cached = _FBP_EFFECT_TOOLTIP_CACHE.get(effect_id)
    if cached is not None:
        return cached
    definition = fbp_effect_definition(effect_id)
    if not definition:
        return "Frame By Plane effect\n\nUse when: selecting or adding a registered Frame By Plane effect."
    label = str(definition.get("label", effect_id) or effect_id)
    description = str(definition.get("description", "") or "").strip()
    category = str(definition.get("category", "2D") or "2D")
    performance = str(definition.get("performance", "LIGHT") or "LIGHT").replace("_", " ").title()
    supports = ", ".join(str(item).title() for item in definition.get("supports", ())) or "Selected compatible layers"
    target_labels = {
        "IMAGE_PLANE": "Single Plane",
        "GREASE_PENCIL_MASK": "Grease Pencil Mask",
        "GREASE_PENCIL_OBJECT": "Grease Pencil Object",
        "CAMERA": "Camera",
        "COMPOSITOR": "Compositor",
    }
    targets = ", ".join(
        target_labels.get(str(item), str(item).replace("_", " ").title())
        for item in definition.get("targets", ("IMAGE_PLANE",))
    ) or "Single Plane"
    animation = (
        "Evolution, Stepped and Seed available"
        if definition.get("evolve_property")
        else "Static/deterministic; no Evolution control is exposed"
    )
    local_masks = (
        "Can receive local effect masks"
        if bool(definition.get("can_receive_local_masks", False)) or str(definition.get("stage", "")).upper() in {"COLOR", "UV"}
        else "Use as a whole-layer effect or mask source"
    )
    warning = ""
    if str(definition.get("performance", "")).upper() in {"HEAVY", "VERY_HEAVY"}:
        warning = "\n\nWarning: heavy effect. Test viewport playback before stacking many copies."
    example_by_category = {
        "MASK": "Example: add this to the Mask stack, or attach it to one effect through the effect-mask button.",
        "3D": "Example: use this for multiplane depth, mesh deformation, outlines, thickness or camera-aware layer behavior.",
        "2D": "Example: place this after color/UV effects when you want a visible image-processing result on the layer.",
    }
    example = example_by_category.get(category, "Example: add it to selected compatible Frame By Plane layers from the Effects library.")
    tooltip = (
        f"{label}\n{description}\n\n"
        f"Use on: {supports}\nTargets: {targets}\nType: {category}\nPerformance: {performance}\n"
        f"Animation: {animation}\nMasking: {local_masks}\n\n{example}{warning}"
    )
    if len(_FBP_EFFECT_TOOLTIP_CACHE) >= 1024 and effect_id not in _FBP_EFFECT_TOOLTIP_CACHE:
        _FBP_EFFECT_TOOLTIP_CACHE.clear()
    _FBP_EFFECT_TOOLTIP_CACHE[effect_id] = tooltip
    return tooltip

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
    "FBP_EFFECT_FIBER_TUFTS",
    "FBP_EFFECT_PAPER_SHARDS",
    "FBP_EFFECT_SPHERE_SCREEN",
    "FBP_EFFECT_IMAGE_RELIEF",
    "FBP_EFFECT_GLASS",
    "FBP_EFFECT_CRYSTAL",
    "FBP_EFFECT_SURFACE_CONFORM",
    "FBP_EFFECT_ACCORDION_FOLD",
    "FBP_EFFECT_SCULPT_WAVES",
    "FBP_EFFECT_KINETIC_TILES",
    "FBP_EFFECT_LAYERED_ECHO",
    "FBP_EFFECT_LATTICE",
    "FBP_EFFECT_MOTION",
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
    "FBP_EFFECT_GP_MASK_SLOT_2", "FBP_EFFECT_GP_MASK_SLOT_3", "FBP_EFFECT_GP_MASK_SLOT_4", "GP_MASK_EFFECT_IDS",
    "FBP_EFFECT_LAYER_BLEND",
    "FBP_EFFECT_COLOR_MASK",
    "FBP_EFFECT_LUMINANCE_MASK",
    "FBP_EFFECT_CHANNEL_MASK",
    "FBP_EFFECT_GRADIENT_MASK",
    "FBP_EFFECT_NOISE_MASK",
    "FBP_EFFECT_VORONOI_MASK",
    "FBP_EFFECT_WAVE_MASK",
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
    "FBP_EFFECT_GRADIENT_MAP",
    "FBP_EFFECT_CHANNEL_MIXER",
    "FBP_EFFECT_DITHER",
    "FBP_EFFECT_BLOOM",
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
    "FBP_EFFECT_EMISSION",
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
    "FBP_MULTI_INSTANCE_SUPPORTED_EFFECTS",
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
    "fbp_effect_multi_instance_enabled",
    "fbp_effect_runtime_contract",
    "fbp_effect_supported_for_rig",
    "fbp_effect_supports_media_type",
    "fbp_effect_allowed_property_names",
    "fbp_effect_compatibility_matrix",
    "FBP_PUBLIC_MEDIA_TYPES",
    "fbp_effect_supports_target",
    "fbp_effect_tooltip",
    "fbp_normalize_effect_id",
    "fbp_rig_media_type",
)
