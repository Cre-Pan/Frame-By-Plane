"""Scene, Object, Collection and add-on preference properties."""

import bpy
from bpy.props import (
    StringProperty, IntProperty, BoolProperty, FloatProperty, FloatVectorProperty,
    CollectionProperty, PointerProperty, EnumProperty
)
from bpy.types import PropertyGroup, AddonPreferences

from .constants import COLOR_ENUM_ITEMS, COLLECTION_COLOR_ENUM_ITEMS, fbp_icon
from .matrix_presets import ASCII_ATLAS_COLUMNS, ASCII_TEXT_GLYPH_LIMIT, ascii_enum_items

from .runtime import fbp_undo_guard_active, fbp_set_rna_property_silent, fbp_warn


CAMERA_RATIO_ITEMS = [
    ('CUSTOM',       "Custom",         "Use the custom render resolution"),
    ('4_3',          "4:3",            "1920x1440 classic animation and TV format"),
    ('3_4',          "3:4 Vertical",   "1440x1920 vertical classic format"),
    ('HD_16_9',      "HD 16:9",        "1920x1080 horizontal HD format"),
    ('UHD_4K',       "4K UHD",         "3840x2160 horizontal 4K format"),
    ('STORY_9_16',   "Story 9:16",     "1080x1920 vertical social/story format"),
    ('1_1',          "Square 1:1",     "2000x2000 square format"),
    ('5_4',          "5:4",            "2000x1600 classic monitor/print ratio"),
    ('16_10',        "16:10",          "1920x1200 widescreen workspace ratio"),
    ('PHOTO_3_2',    "Photo 3:2",      "3000x2000 photographic ratio"),
    ('PHOTO_2_3',    "Photo 2:3",      "2000x3000 vertical photographic ratio"),
    ('CINEMA_185',   "Cinema 1.85:1",  "1850x1000 cinema ratio"),
    ('CINEMA_239',   "Cinema 2.39:1",  "2390x1000 widescreen cinema ratio"),
    ('TWO_1',        "2:1",            "2000x1000 wide format"),
    ('ULTRAWIDE_21_9', "21:9",         "2520x1080 ultrawide format"),
    ('A4_LANDSCAPE', "A4 Landscape",  "2480x1754 paper ratio"),
    ('A4_PORTRAIT',  "A4 Portrait",   "1754x2480 paper ratio"),
]

CAMERA_PROJECTION_ITEMS = [
    ('PERSP', "Perspective", "Create a perspective camera and fit planes using their distance from the camera"),
    ('ORTHO', "Orthographic", "Create an orthographic camera and fit planes using the camera orthographic scale"),
]

PLAYBACK_ITEMS = [
    ('NONE', "One Shot", "Play once", fbp_icon("FORWARD"), 0),
    ('REPEAT', "Loop", "Repeat forever", fbp_icon("FILE_REFRESH"), 1),
    ('PINGPONG', "Ping-Pong", "Play forward and backward", fbp_icon("UV_SYNC_SELECT"), 2),
]

INTERPOLATION_ITEMS = [
    ('Closest', "Pixel", "Sharp edges and pixel-art filtering", fbp_icon("ALIASED"), 0),
    ('Linear', "Smooth", "Bilinear image filtering", fbp_icon("ANTIALIASED"), 1),
]

ORIENTATION_ITEMS = [
    ('HORIZ', "Horizontal", "Generate planes parallel to the ground", fbp_icon("AXIS_TOP"), 0),
    ('VERT', "Vertical", "Generate standing planes facing the camera", fbp_icon("AXIS_FRONT"), 1),
]

CREATION_MODE_ITEMS = [
    ('COLOR', "Color Plane", "Solid, gradient or holdout procedural plane", fbp_icon("IMAGE"), 0),
    ('SINGLE', "Single Plane", "Single independent image sequence plane", fbp_icon("IMAGE_DATA"), 1),
    ('MULTI', "Multiplane", "Layered/parallax image project setup", fbp_icon("RENDERLAYERS"), 2),
]

COLOR_PLANE_TYPE_ITEMS = [
    ('CUSTOM', "Color", "Create a custom solid color camera-ratio plane", fbp_icon("IMAGE"), 0),
    ('GRADIENT', "Gradient", "Create an editable ColorRamp gradient plane for vignettes, fades and in-camera masks", fbp_icon("NODE_TEXTURE"), 1),
    ('HOLDOUT', "Holdout", "Create a holdout mask plane for compositing", fbp_icon("GHOST_DISABLED"), 2),
]

COLOR_PLANE_PRESET_ITEMS = [
    ('CUSTOM', "Custom", "Use the manually chosen color", fbp_icon("MESH_PLANE"), 0),
    ('BLACK', "Black", "Pure black", fbp_icon("COLORSET_20_VEC"), 1),
    ('WHITE', "White", "Pure white", fbp_icon("SNAP_FACE"), 2),
    ('MIDDLE_GREY', "Middle Grey", "50% grey", fbp_icon("STRIP_COLOR_09"), 3),
    ('GREENSCREEN', "Greenscreen", "Chroma green", fbp_icon("STRIP_COLOR_04"), 4),
    ('BLUE', "Blue", "#6697FFFF", fbp_icon("STRIP_COLOR_05"), 5),
    ('PURPLE', "Purple", "#9450F3FF", fbp_icon("STRIP_COLOR_06"), 6),
    ('ROSE', "Rose", "Rose / pink", fbp_icon("STRIP_COLOR_07"), 7),
    ('YELLOW', "Yellow", "#FFB300FF", fbp_icon("STRIP_COLOR_02"), 8),
    ('ORANGE', "Orange", "#FF7900FF", fbp_icon("STRIP_COLOR_02"), 9),
    ('RED', "Red", "Basic red", fbp_icon("STRIP_COLOR_01"), 10),
]

GRADIENT_MODE_ITEMS = [
    ('LINEAR', "Linear", "Linear gradient from one side of the plane to the other", fbp_icon("ARROW_LEFTRIGHT"), 0),
    ('CENTER', "Radial", "Centered radial gradient useful for vignettes", fbp_icon("EMPTY_ARROWS"), 1),
]

GRADIENT_KIND_ITEMS = [
    ('COLOR', "Color to Color", "Blend from Color A to Color B with full opacity", fbp_icon("COLOR"), 0),
    ('ALPHA', "Transparent to Visible", "Fade from transparent to the selected visible color", fbp_icon("IMAGE_ALPHA"), 1),
]

_PREFERENCES_SCENE_MARKER = "fbp_preferences_initialized"


# SECTION 00B - Proxy callbacks to core.py #
def _fbp_core_func(name):
    from . import core
    return getattr(core, name)


def _call_core(name, *args, default=None):
    if fbp_undo_guard_active():
        return default
    try:
        return _fbp_core_func(name)(*args)
    except ReferenceError:
        return default
    except Exception as exc:
        fbp_warn(f"Properties callback failed: {name}", exc)
        return default


def _fbp_layers_func(name):
    from . import layers
    return getattr(layers, name)


def _call_layers(name, *args, default=None):
    if fbp_undo_guard_active():
        return default
    try:
        return _fbp_layers_func(name)(*args)
    except ReferenceError:
        return default
    except Exception as exc:
        fbp_warn(f"Layer property callback failed: {name}", exc)
        return default


def update_settings_section_cb(self, context):
    """Keep Settings tabs compact and visually stable when switching category."""
    try:
        self.fbp_settings_primary_open = False
        self.fbp_settings_secondary_open = False
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def update_effects_view_cb(self, context):
    """Select the first visible effect when switching between the 2D and 3D stacks."""
    try:
        from .layers import get_selected_rigs
        from .geometry_nodes import fbp_effect_definition, fbp_sync_effect_items

        rigs = get_selected_rigs(context)
        if not rigs:
            return
        rig = rigs[0]
        fbp_sync_effect_items(rig, rigs)
        visible_categories = {"3D"} if self.fbp_effects_view == "3D" else {"BASE", "2D"}
        for index, item in enumerate(getattr(rig, "fbp_effects", ())):
            definition = fbp_effect_definition(getattr(item, "effect_id", ""))
            if str(definition.get("category", "2D") or "2D") in visible_categories:
                rig.fbp_effects_index = index
                break
        else:
            rig.fbp_effects_index = -1
    except (AttributeError, ImportError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


# SECTION 00C - Add-on Preferences #
class FBP_AddonPreferences(AddonPreferences):
    bl_idname = __package__ if __package__ else "frame_by_plane"

    default_project_path: StringProperty(
        name="Default Project Folder",
        description="Folder automatically assigned to new Frame by Plane scenes",
        subtype='DIR_PATH',
        default="",
    )
    default_last_directory: StringProperty(
        name="Default File Browser Folder",
        description="Starting folder used by Frame by Plane import file browsers",
        subtype='DIR_PATH',
        default="",
    )
    default_creation_mode: EnumProperty(
        name="Default Creation Mode",
        items=CREATION_MODE_ITEMS,
        default='COLOR',
    )
    default_frame_duration: IntProperty(
        name="Default Frame Duration",
        description="Number of timeline frames assigned to each newly imported image",
        default=2, min=1, soft_max=24,
    )
    default_scene_fps: IntProperty(
        name="Default Scene FPS",
        description="Frames per second assigned to new Frame by Plane scenes",
        default=24, min=1, max=240,
    )
    default_playback: EnumProperty(name="Default Playback", items=PLAYBACK_ITEMS, default='NONE')
    default_interpolation: EnumProperty(name="Default Image Filter", items=INTERPOLATION_ITEMS, default='Closest')
    default_emission: BoolProperty(
        name="Emission Textures",
        description="Use lightweight shadeless materials for newly imported image layers",
        default=True,
    )
    default_orientation: EnumProperty(name="Default Plane Orientation", items=ORIENTATION_ITEMS, default='VERT')
    default_layer_offset: FloatProperty(
        name="Default Plane Distance",
        description="Distance between generated multiplane layers",
        default=0.2, min=0.001, soft_max=10.0, unit='LENGTH',
    )
    default_fit_to_camera: BoolProperty(
        name="Fit New Layers to Camera",
        description="Automatically fit generated planes inside the active or generated camera",
        default=True,
    )
    default_track_camera: BoolProperty(
        name="Track Camera on New Layers",
        description="Add camera tracking to newly created Frame by Plane layers",
        default=False,
    )
    default_generate_camera: BoolProperty(
        name="Generate Camera",
        description="Generate a camera by default for new Multiplane projects",
        default=True,
    )
    default_camera_projection: EnumProperty(
        name="Default Camera Projection",
        items=CAMERA_PROJECTION_ITEMS,
        default='PERSP',
    )
    default_camera_ratio: EnumProperty(name="Default Aspect Ratio", items=CAMERA_RATIO_ITEMS, default='4_3')
    default_resolution_x: IntProperty(name="Custom Resolution X", default=1920, min=1, max=65536)
    default_resolution_y: IntProperty(name="Custom Resolution Y", default=1440, min=1, max=65536)
    default_camera_lens: FloatProperty(
        name="Perspective Lens", description="Lens used by newly generated perspective cameras",
        default=50.0, min=1.0, max=500.0,
    )
    default_camera_ortho_scale: FloatProperty(
        name="Orthographic Scale", description="Scale used by newly generated orthographic cameras",
        default=10.0, min=0.001, soft_max=100.0,
    )
    default_camera_clip_start: FloatProperty(
        name="Camera Clip Start", description="Near clipping distance for newly generated cameras",
        default=0.1, min=0.001, soft_max=10.0, unit='LENGTH',
    )
    default_camera_clip_end: FloatProperty(
        name="Camera Clip End", description="Far clipping distance for newly generated cameras",
        default=1000.0, min=1.0, soft_max=10000.0, unit='LENGTH',
    )
    default_camera_pivot: BoolProperty(
        name="3D Cursor on Camera",
        description="Move the 3D cursor to a newly generated camera",
        default=True,
    )
    default_color_variants: BoolProperty(
        name="Collection Color Variants",
        description="Give generated layers subtle viewport color variations inside each collection",
        default=True,
    )
    default_auto_clean_orphans: BoolProperty(
        name="Auto-clean FBP Orphans",
        description="Remove orphaned Frame by Plane planes and unused owned datablocks after normal deletion",
        default=True,
    )
    default_show_previews: BoolProperty(
        name="Show Image Thumbnails",
        description="Show image thumbnails in Frame by Plane layer and frame lists",
        default=False,
    )
    default_show_color_previews: BoolProperty(
        name="Show Color Previews",
        description="Show procedural color and gradient previews in UI lists",
        default=True,
    )
    default_sort_layers_alpha: BoolProperty(
        name="Sort Layers Alphabetically",
        description="Use alphabetical layer ordering by default",
        default=False,
    )
    default_show_project_tools: BoolProperty(
        name="Expand Project Import",
        description="Show the advanced project import section expanded by default",
        default=True,
    )
    default_show_gradient_ramp: BoolProperty(
        name="Expand Gradient Color Ramp",
        description="Show advanced ColorRamp controls by default when creating procedural gradients",
        default=True,
    )
    default_show_gradient_transform: BoolProperty(
        name="Expand Gradient Position",
        description="Show gradient position, scale and rotation controls by default",
        default=True,
    )
    default_render_output_dir: StringProperty(
        name="Default Render Folder",
        description="Folder used for background-rendered frame sequences; empty creates FBP_Render_Frames beside the .blend file",
        subtype='DIR_PATH',
        default="",
    )
    default_render_prefix: StringProperty(
        name="Render Filename Prefix",
        description="Filename prefix used by the background frame renderer",
        default="frame_",
    )
    default_color_plane_type: EnumProperty(
        name="Default Procedural Plane", items=COLOR_PLANE_TYPE_ITEMS, default='CUSTOM',
    )
    default_color_plane_preset: EnumProperty(
        name="Default Color Preset", items=COLOR_PLANE_PRESET_ITEMS, default='CUSTOM',
    )
    default_color_plane_color: FloatVectorProperty(
        name="Default Custom Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
    )
    default_color_plane_emission: BoolProperty(
        name="Color Plane Emission",
        description="Use emission materials for newly created Color and Gradient planes",
        default=True,
    )
    default_gradient_mode: EnumProperty(name="Default Gradient Shape", items=GRADIENT_MODE_ITEMS, default='LINEAR')
    default_gradient_kind: EnumProperty(name="Default Gradient Type", items=GRADIENT_KIND_ITEMS, default='COLOR')
    default_gradient_color_a: FloatVectorProperty(
        name="Default Gradient From", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 0.3686274509803922, 0.596078431372549, 1.0),
    )
    default_gradient_color_b: FloatVectorProperty(
        name="Default Gradient To", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0),
    )
    default_gradient_reverse: BoolProperty(name="Reverse Gradient", default=True)
    default_gradient_offset_x: FloatProperty(name="Gradient X Offset", default=0.0, soft_min=-2.0, soft_max=2.0)
    default_gradient_offset_y: FloatProperty(name="Gradient Y Offset", default=0.0, soft_min=-2.0, soft_max=2.0)
    default_gradient_scale_x: FloatProperty(name="Gradient Scale X", default=1.0, min=0.001, soft_max=10.0)
    default_gradient_scale_y: FloatProperty(name="Gradient Scale Y", default=1.0, min=0.001, soft_max=10.0)
    default_gradient_rotation: FloatProperty(name="Gradient Rotation", default=0.0, soft_min=-180.0, soft_max=180.0)

    def draw(self, context):
        layout = self.layout

        project = layout.box()
        project.label(text="Project and File Browser Defaults", icon='OUTLINER')
        project.prop(self, "default_project_path")
        project.prop(self, "default_last_directory")
        project.prop(self, "default_creation_mode")

        sequence = layout.box()
        sequence.label(text="Import and Sequence Defaults", icon='IMAGE_DATA')
        row = sequence.row(align=True)
        row.prop(self, "default_frame_duration")
        row.prop(self, "default_scene_fps")
        sequence.prop(self, "default_playback")
        sequence.prop(self, "default_interpolation")
        row = sequence.row(align=True)
        row.prop(self, "default_emission", toggle=True)
        row.prop(self, "default_orientation")
        row = sequence.row(align=True)
        row.prop(self, "default_layer_offset")
        row.prop(self, "default_fit_to_camera", toggle=True)
        sequence.prop(self, "default_track_camera", toggle=True)

        camera = layout.box()
        camera.label(text="Camera Defaults", icon='VIEW_CAMERA_UNSELECTED')
        row = camera.row(align=True)
        row.prop(self, "default_generate_camera", toggle=True)
        row.prop(self, "default_camera_pivot", toggle=True)
        camera.prop(self, "default_camera_projection")
        if self.default_camera_projection == 'ORTHO':
            camera.prop(self, "default_camera_ortho_scale")
        else:
            camera.prop(self, "default_camera_lens")
        row = camera.row(align=True)
        row.prop(self, "default_camera_clip_start")
        row.prop(self, "default_camera_clip_end")
        camera.prop(self, "default_camera_ratio")
        if self.default_camera_ratio == 'CUSTOM':
            row = camera.row(align=True)
            row.prop(self, "default_resolution_x")
            row.prop(self, "default_resolution_y")

        display = layout.box()
        display.label(text="Interface and Maintenance Defaults", icon='PREFERENCES')
        row = display.row(align=True)
        row.prop(self, "default_show_previews", toggle=True)
        row.prop(self, "default_show_color_previews", toggle=True)
        row = display.row(align=True)
        row.prop(self, "default_sort_layers_alpha", toggle=True)
        row.prop(self, "default_show_project_tools", toggle=True)
        row = display.row(align=True)
        row.prop(self, "default_show_gradient_ramp", toggle=True)
        row.prop(self, "default_show_gradient_transform", toggle=True)
        row = display.row(align=True)
        row.prop(self, "default_color_variants", toggle=True)
        row.prop(self, "default_auto_clean_orphans", toggle=True)

        render = layout.box()
        render.label(text="Background Render Defaults", icon='RENDER_ANIMATION')
        render.prop(self, "default_render_output_dir")
        render.prop(self, "default_render_prefix")

        procedural = layout.box()
        procedural.label(text="Procedural Plane Defaults", icon='MATERIAL')
        procedural.prop(self, "default_color_plane_type")
        procedural.prop(self, "default_color_plane_preset")
        if self.default_color_plane_preset == 'CUSTOM':
            procedural.prop(self, "default_color_plane_color")
        procedural.prop(self, "default_color_plane_emission", toggle=True)
        row = procedural.row(align=True)
        row.prop(self, "default_gradient_mode")
        row.prop(self, "default_gradient_kind")
        row = procedural.row(align=True)
        row.prop(self, "default_gradient_color_a")
        row.prop(self, "default_gradient_color_b")
        procedural.prop(self, "default_gradient_reverse", toggle=True)
        transform = procedural.column(align=True)
        row = transform.row(align=True)
        row.prop(self, "default_gradient_offset_x")
        row.prop(self, "default_gradient_offset_y")
        row = transform.row(align=True)
        row.prop(self, "default_gradient_scale_x")
        row.prop(self, "default_gradient_scale_y")
        transform.prop(self, "default_gradient_rotation")

        layout.separator()
        row = layout.row()
        row.scale_y = 1.2
        row.operator("fbp.apply_preferences_to_scene", icon='CHECKMARK', text="Apply Defaults to Current Scene")
        layout.label(text="Defaults are applied automatically to newly created scenes.", icon='INFO')


def fbp_get_addon_preferences(context=None):
    context = context or getattr(bpy, "context", None)
    preferences = getattr(context, "preferences", None) if context else None
    addons = getattr(preferences, "addons", None) if preferences else None
    if addons is None:
        return None
    keys = [__package__ if __package__ else "frame_by_plane", "frame_by_plane"]
    for key in keys:
        try:
            addon = addons.get(key)
            if addon and getattr(addon, "preferences", None):
                return addon.preferences
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    try:
        for key, addon in addons.items():
            if str(key).endswith(".frame_by_plane") or str(key) == "frame_by_plane":
                prefs = getattr(addon, "preferences", None)
                if prefs:
                    return prefs
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return None


def fbp_apply_preferences_to_scene(scene, *, force=False, context=None):
    if not scene:
        return False
    try:
        if not force and bool(scene.get(_PREFERENCES_SCENE_MARKER, False)):
            return False
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
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
        "fbp_creation_mode": getattr(prefs, "default_creation_mode", 'COLOR'),
        "fbp_pre_duration": getattr(prefs, "default_frame_duration", 2),
        "fbp_pre_shadeless": getattr(prefs, "default_emission", True),
        "fbp_pre_loop_mode": getattr(prefs, "default_playback", 'NONE'),
        "fbp_pre_interpolation": getattr(prefs, "default_interpolation", 'Closest'),
        "fbp_pre_orientation": getattr(prefs, "default_orientation", 'VERT'),
        "fbp_layer_offset": getattr(prefs, "default_layer_offset", 0.2),
        "fbp_auto_scale": getattr(prefs, "default_fit_to_camera", True),
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
        "fbp_show_project_tools": getattr(prefs, "default_show_project_tools", True),
        "fbp_show_gradient_ramp": getattr(prefs, "default_show_gradient_ramp", True),
        "fbp_show_gradient_transform": getattr(prefs, "default_show_gradient_transform", True),
        "fbp_render_output_dir": getattr(prefs, "default_render_output_dir", ""),
        "fbp_render_prefix": getattr(prefs, "default_render_prefix", "frame_"),
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

    changed = False
    for attr, value in assignments.items():
        try:
            setattr(scene, attr, value)
            changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

    # Set the preset after the custom color. The color update callback switches
    # non-Custom presets back to Custom, while the preset callback intentionally
    # applies the selected preset color. This ordering preserves the preference.
    try:
        scene.fbp_color_plane_preset = getattr(prefs, "default_color_plane_preset", 'CUSTOM')
        changed = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    try:
        scene.render.fps = int(getattr(prefs, "default_scene_fps", 24))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    if getattr(prefs, "default_camera_ratio", '4_3') == 'CUSTOM':
        try:
            scene.render.resolution_x = int(getattr(prefs, "default_resolution_x", 1920))
            scene.render.resolution_y = int(getattr(prefs, "default_resolution_y", 1440))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    try:
        scene[_PREFERENCES_SCENE_MARKER] = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return changed


def fbp_mark_scenes_preferences_initialized(scenes=None):
    scenes = scenes if scenes is not None else getattr(bpy.data, "scenes", [])
    for scene in list(scenes):
        try:
            scene[_PREFERENCES_SCENE_MARKER] = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass

def update_color_plane_color_cb(self, context):
    return _call_core('update_color_plane_color_cb', self, context)

def update_color_plane_preset_cb(self, context):
    return _call_core('update_color_plane_preset_cb', self, context)

def update_color_tag_cb(self, context):
    return _call_core('update_color_tag_cb', self, context)

def update_emission_cb(self, context):
    return _call_core('update_emission_cb', self, context)

def update_global_duration_cb(self, context):
    return _call_core('update_global_duration_cb', self, context)

def update_image_duration_cb(self, context):
    return _call_core('update_image_duration_cb', self, context)

def update_gradient_mapping_cb(self, context):
    return _call_core('update_gradient_mapping_cb', self, context)

def update_image_index_cb(self, context):
    return _call_core('update_image_index_cb', self, context)

def update_frame_preview_color_cb(self, context):
    return _call_core('update_frame_preview_color_cb', self, context)

def update_layer_stack_index_cb(self, context):
    return _call_core('update_layer_stack_index_cb', self, context)


def update_pending_collection_color_cb(self, context):
    """Apply a preview collection color to every direct layer in that setup collection."""
    try:
        if getattr(self, 'row_type', '') != 'GROUP':
            return
        path = (getattr(self, 'collection_path', '') or '').strip()
        if not path:
            return
        from .ui_layout import fbp_apply_pending_collection_color
        fbp_apply_pending_collection_color(context.scene, path, getattr(self, 'collection_color_tag', 'NONE'))
    except ReferenceError:
        return
    except Exception as exc:
        fbp_warn("Could not update pending collection color", exc)

def update_loop_mode_cb(self, context):
    return _call_core('update_loop_mode_cb', self, context)

def update_mute_cb(self, context):
    return _call_core('update_mute_cb', self, context)

def _call_geometry_nodes(name, *args, default=None):
    if fbp_undo_guard_active():
        return default
    from . import geometry_nodes
    try:
        return getattr(geometry_nodes, name)(*args)
    except ReferenceError:
        return default
    except Exception as exc:
        fbp_warn(f"Geometry Nodes callback failed: {name}", exc)
        return default


def update_mesh_wiggle_enabled_cb(self, context):
    return _call_geometry_nodes('update_mesh_wiggle_enabled_cb', self, context)



def update_mesh_wiggle_shade_smooth_cb(self, context):
    return _call_geometry_nodes('update_mesh_wiggle_setting_cb', self, context, 'fbp_mesh_wiggle_shade_smooth')


def update_mesh_wiggle_strength_cb(self, context):
    return _call_geometry_nodes('update_mesh_wiggle_setting_cb', self, context, 'fbp_mesh_wiggle_strength')


def update_mesh_wiggle_speed_cb(self, context):
    return _call_geometry_nodes('update_mesh_wiggle_setting_cb', self, context, 'fbp_mesh_wiggle_speed')


def update_mesh_wiggle_hold_cb(self, context):
    return _call_geometry_nodes('update_mesh_wiggle_setting_cb', self, context, 'fbp_mesh_wiggle_hold')


def update_mesh_wiggle_w_cb(self, context):
    return _call_geometry_nodes('update_mesh_wiggle_setting_cb', self, context, 'fbp_mesh_wiggle_w')


def update_mesh_wiggle_seed_cb(self, context):
    return _call_geometry_nodes('update_mesh_wiggle_setting_cb', self, context, 'fbp_mesh_wiggle_seed')


def update_mesh_wiggle_unique_seed_cb(self, context):
    return _call_geometry_nodes('update_mesh_wiggle_setting_cb', self, context, 'fbp_mesh_wiggle_unique_seed')


def update_mesh_wiggle_noise_scale_cb(self, context):
    return _call_geometry_nodes('update_mesh_wiggle_setting_cb', self, context, 'fbp_mesh_wiggle_noise_scale')


def update_mesh_wiggle_detail_cb(self, context):
    return _call_geometry_nodes('update_mesh_wiggle_setting_cb', self, context, 'fbp_mesh_wiggle_detail')


def update_mesh_wiggle_subdivisions_cb(self, context):
    return _call_geometry_nodes('update_mesh_wiggle_setting_cb', self, context, 'fbp_mesh_wiggle_subdivisions')




def _make_effect_update_callback(effect_id, prop_name):
    """Create a small RNA update callback for a registered FBP effect property."""
    def _update(self, context):
        return _call_geometry_nodes(
            'update_effect_setting_cb', self, context, effect_id, prop_name
        )
    return _update



update_uv_distortion_scale_cb = _make_effect_update_callback('UV_DISTORTION', 'fbp_uv_distortion_scale')
update_uv_distortion_amount_cb = _make_effect_update_callback('UV_DISTORTION', 'fbp_uv_distortion_amount')
update_pixelate_resolution_cb = _make_effect_update_callback('PIXELATE', 'fbp_pixelate_resolution')
update_pixelate_square_pixels_cb = _make_effect_update_callback('PIXELATE', 'fbp_pixelate_square_pixels')
update_grain_strength_cb = _make_effect_update_callback('GRAIN', 'fbp_grain_strength')
update_grain_scale_cb = _make_effect_update_callback('GRAIN', 'fbp_grain_scale')
update_grain_seed_cb = _make_effect_update_callback('GRAIN', 'fbp_grain_seed')
update_digital_noise_luma_cb = _make_effect_update_callback('DIGITAL_NOISE', 'fbp_digital_noise_luma')
update_digital_noise_chroma_cb = _make_effect_update_callback('DIGITAL_NOISE', 'fbp_digital_noise_chroma')
update_digital_noise_scale_cb = _make_effect_update_callback('DIGITAL_NOISE', 'fbp_digital_noise_scale')
update_digital_noise_shadow_bias_cb = _make_effect_update_callback('DIGITAL_NOISE', 'fbp_digital_noise_shadow_bias')
update_digital_noise_seed_cb = _make_effect_update_callback('DIGITAL_NOISE', 'fbp_digital_noise_seed')
update_chroma_key_color_cb = _make_effect_update_callback('CHROMA_KEY', 'fbp_chroma_key_color')
update_chroma_key_tolerance_cb = _make_effect_update_callback('CHROMA_KEY', 'fbp_chroma_key_tolerance')
update_chroma_key_softness_cb = _make_effect_update_callback('CHROMA_KEY', 'fbp_chroma_key_softness')
update_chroma_key_despill_cb = _make_effect_update_callback('CHROMA_KEY', 'fbp_chroma_key_despill')
update_chroma_key_invert_cb = _make_effect_update_callback('CHROMA_KEY', 'fbp_chroma_key_invert')
update_halftone_scale_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_scale')
update_halftone_dot_size_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_dot_size')
update_halftone_rotation_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_rotation')
update_halftone_contrast_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_contrast')
update_halftone_invert_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_invert')
update_halftone_shape_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_shape')
update_halftone_use_source_color_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_use_source_color')
update_halftone_foreground_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_foreground')
update_halftone_background_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_background')
update_halftone_transparent_background_cb = _make_effect_update_callback('HALFTONE', 'fbp_halftone_transparent_background')
update_dot_matrix_scale_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_scale')
update_dot_matrix_dot_size_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_dot_size')
update_dot_matrix_spacing_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_spacing')
update_dot_matrix_contrast_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_contrast')
update_dot_matrix_response_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_response')
update_dot_matrix_invert_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_invert')
update_dot_matrix_random_size_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_random_size')
update_dot_matrix_random_brightness_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_random_brightness')
update_dot_matrix_seed_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_seed')
update_dot_matrix_glow_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_glow')
update_dot_matrix_use_source_color_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_use_source_color')
update_dot_matrix_foreground_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_foreground')
update_dot_matrix_background_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_background')
update_dot_matrix_transparent_background_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_transparent_background')
update_dot_matrix_shape_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_shape')
update_dot_matrix_min_size_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_min_size')
update_dot_matrix_max_size_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_max_size')
update_dot_matrix_dead_pixels_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_dead_pixels')
update_dot_matrix_flicker_cb = _make_effect_update_callback('DOT_MATRIX', 'fbp_dot_matrix_flicker')
update_ascii_scale_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_scale')
update_ascii_contrast_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_contrast')
update_ascii_invert_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_invert')
update_ascii_colorize_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_colorize')
update_ascii_foreground_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_foreground')
update_ascii_background_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_background')
update_ascii_transparent_background_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_transparent_background')
update_ascii_variation_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_variation')
update_ascii_random_seed_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_random_seed')
update_ascii_charset_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_charset')
update_ascii_character_count_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_character_count')
update_ascii_edge_boost_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_edge_boost')
update_ascii_dither_cb = _make_effect_update_callback('ASCII_MATRIX', 'fbp_ascii_dither')
update_text_matrix_columns_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_columns')
update_text_matrix_character_count_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_character_count')
update_text_matrix_character_aspect_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_character_aspect')
update_text_matrix_glyph_scale_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_glyph_scale')
update_text_matrix_contrast_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_contrast')
update_text_matrix_invert_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_invert')
update_text_matrix_variation_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_variation')
update_text_matrix_seed_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_seed')
update_text_matrix_alpha_threshold_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_alpha_threshold')
update_text_matrix_transparent_background_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_transparent_background')
update_text_matrix_realize_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_realize')
update_text_matrix_charset_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_charset')
update_text_matrix_custom_charset_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_custom_charset')
update_text_matrix_font_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_font')
update_text_matrix_use_source_color_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_use_source_color')
update_text_matrix_text_color_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_text_color')
update_text_matrix_background_color_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_background_color')
update_text_matrix_viewport_columns_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_viewport_columns')
update_text_matrix_viewport_rows_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_viewport_rows')
update_text_matrix_render_columns_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_render_columns')
update_text_matrix_render_rows_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_render_rows')
update_text_matrix_playback_columns_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_playback_columns')
update_text_matrix_playback_rows_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_playback_rows')
update_text_matrix_auto_playback_limit_cb = _make_effect_update_callback('TEXT_MATRIX', 'fbp_text_matrix_auto_playback_limit')
update_hue_saturation_hue_cb = _make_effect_update_callback('HUE_SATURATION', 'fbp_hue_saturation_hue')
update_hue_saturation_saturation_cb = _make_effect_update_callback('HUE_SATURATION', 'fbp_hue_saturation_saturation')
update_hue_saturation_value_cb = _make_effect_update_callback('HUE_SATURATION', 'fbp_hue_saturation_value')
update_brightness_contrast_brightness_cb = _make_effect_update_callback('BRIGHTNESS_CONTRAST', 'fbp_brightness_contrast_brightness')
update_brightness_contrast_contrast_cb = _make_effect_update_callback('BRIGHTNESS_CONTRAST', 'fbp_brightness_contrast_contrast')
update_invert_factor_cb = _make_effect_update_callback('INVERT', 'fbp_invert_factor')
update_threshold_value_cb = _make_effect_update_callback('THRESHOLD', 'fbp_threshold_value')
update_posterize_steps_cb = _make_effect_update_callback('POSTERIZE', 'fbp_posterize_steps')
update_solid_mask_color_cb = _make_effect_update_callback('SOLID_MASK', 'fbp_solid_mask_color')
update_solid_mask_factor_cb = _make_effect_update_callback('SOLID_MASK', 'fbp_solid_mask_factor')
update_stop_motion_resolution_cb = _make_effect_update_callback('STOP_MOTION_CRUMPLE', 'fbp_stop_motion_resolution')
update_stop_motion_strength_cb = _make_effect_update_callback('STOP_MOTION_CRUMPLE', 'fbp_stop_motion_strength')
update_stop_motion_step_frames_cb = _make_effect_update_callback('STOP_MOTION_CRUMPLE', 'fbp_stop_motion_step_frames')
update_wind_bend_amount_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_bend_amount')
update_wind_speed_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_speed')
update_wind_subdivision_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_subdivision')
update_wind_stepped_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_stepped')
update_wind_pin_edge_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_pin_edge')
update_wind_motion_mode_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_motion_mode')
update_wind_wave_count_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_wave_count')
update_wind_wave_amplitude_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_wave_amplitude')
update_wind_wave_speed_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_wave_speed')
update_wind_phase_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_phase')
update_wind_turbulence_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_turbulence')
update_wind_reverse_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_reverse')
update_wind_falloff_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_falloff')
update_wind_noise_scale_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_noise_scale')
update_wind_gust_strength_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_gust_strength')
update_wind_direction_space_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_direction_space')
update_wind_direction_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_direction')
update_wind_preview_falloff_cb = _make_effect_update_callback('WIND_BENDER', 'fbp_wind_preview_falloff')
update_thickness_amount_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_amount')
update_thickness_alpha_threshold_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_alpha_threshold')
update_thickness_alpha_resolution_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_alpha_resolution')
update_thickness_side_material_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_side_material')
update_thickness_side_color_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_side_color')
update_infinite_rotation_speed_cb = _make_effect_update_callback('INFINITE_ROTATION', 'fbp_infinite_rotation_speed')
update_infinite_rotation_direction_cb = _make_effect_update_callback('INFINITE_ROTATION', 'fbp_infinite_rotation_direction')
update_infinite_rotation_stepped_cb = _make_effect_update_callback('INFINITE_ROTATION', 'fbp_infinite_rotation_stepped')
update_infinite_rotation_offset_cb = _make_effect_update_callback('INFINITE_ROTATION', 'fbp_infinite_rotation_offset')
update_felt_render_density_cb = _make_effect_update_callback('FELT_FUZZ', 'fbp_felt_render_density')
update_felt_viewport_percentage_cb = _make_effect_update_callback('FELT_FUZZ', 'fbp_felt_viewport_percentage')
update_felt_fuzz_length_cb = _make_effect_update_callback('FELT_FUZZ', 'fbp_felt_fuzz_length')
update_felt_subdivisions_cb = _make_effect_update_callback('FELT_FUZZ', 'fbp_felt_subdivisions')
update_felt_fuzz_radius_cb = _make_effect_update_callback('FELT_FUZZ', 'fbp_felt_fuzz_radius')
update_felt_seed_cb = _make_effect_update_callback('FELT_FUZZ', 'fbp_felt_seed')
update_felt_curl_amount_cb = _make_effect_update_callback('FELT_FUZZ', 'fbp_felt_curl_amount')
update_felt_alpha_threshold_cb = _make_effect_update_callback('FELT_FUZZ', 'fbp_felt_alpha_threshold')
update_felt_alpha_resolution_cb = _make_effect_update_callback('FELT_FUZZ', 'fbp_felt_alpha_resolution')
update_color_isolate_target_cb = _make_effect_update_callback('COLOR_ISOLATE', 'fbp_color_isolate_target')
update_color_isolate_tolerance_cb = _make_effect_update_callback('COLOR_ISOLATE', 'fbp_color_isolate_tolerance')
update_color_isolate_falloff_cb = _make_effect_update_callback('COLOR_ISOLATE', 'fbp_color_isolate_falloff')
update_duotone_shadows_cb = _make_effect_update_callback('DUOTONE', 'fbp_duotone_shadows')
update_duotone_highlights_cb = _make_effect_update_callback('DUOTONE', 'fbp_duotone_highlights')
update_paper_fiber_scale_cb = _make_effect_update_callback('PAPER_FIBERS', 'fbp_paper_fiber_scale')
update_paper_fiber_intensity_cb = _make_effect_update_callback('PAPER_FIBERS', 'fbp_paper_fiber_intensity')
update_paper_fiber_phase_cb = _make_effect_update_callback('PAPER_FIBERS', 'fbp_paper_fiber_phase')
update_gradient_light_angle_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_light_angle')
update_gradient_shadow_position_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_shadow_position')
update_gradient_softness_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_softness')
update_gradient_shadow_color_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_shadow_color')
update_gobo_pattern_scale_cb = _make_effect_update_callback('GOBO_SHADOWS', 'fbp_gobo_pattern_scale')
update_gobo_rotation_cb = _make_effect_update_callback('GOBO_SHADOWS', 'fbp_gobo_rotation')
update_gobo_sharpness_cb = _make_effect_update_callback('GOBO_SHADOWS', 'fbp_gobo_sharpness')
update_crt_line_count_cb = _make_effect_update_callback('CRT_SCANLINES', 'fbp_crt_line_count')
update_crt_opacity_cb = _make_effect_update_callback('CRT_SCANLINES', 'fbp_crt_opacity')
update_vignette_radius_cb = _make_effect_update_callback('VIGNETTE', 'fbp_vignette_radius')
update_vignette_smoothness_cb = _make_effect_update_callback('VIGNETTE', 'fbp_vignette_smoothness')
update_vignette_strength_cb = _make_effect_update_callback('VIGNETTE', 'fbp_vignette_strength')


_EFFECT_ANIMATION_IDS = (
    'UV_DISTORTION',
    'PIXELATE',
    'HUE_SATURATION',
    'GRAIN',
    'DIGITAL_NOISE',
    'DOT_MATRIX',
    'ASCII_MATRIX',
    'TEXT_MATRIX',
    'PAPER_FIBERS',
    'POSTERIZE',
    'SOLID_MASK',
    'FELT_FUZZ',
)


def _effect_animation_property_name(effect_id, suffix):
    return f"fbp_anim_{effect_id.lower()}_{suffix}"


def _make_effect_animation_update_callback(effect_id, suffix):
    def _update(self, context):
        return _call_geometry_nodes(
            'update_effect_animation_setting_cb', self, context, effect_id, suffix
        )
    return _update


def _register_effect_animation_properties():
    for effect_id in _EFFECT_ANIMATION_IDS:
        setattr(
            bpy.types.Object,
            _effect_animation_property_name(effect_id, 'evolve'),
            BoolProperty(
                name="Evolve", default=False,
                description="Animate the preferred procedural parameter with deterministic non-repeating noise",
                update=_make_effect_animation_update_callback(effect_id, 'evolve'),
            ),
        )
        setattr(
            bpy.types.Object,
            _effect_animation_property_name(effect_id, 'step'),
            IntProperty(
                name="Stepped", default=4, min=1, max=240,
                description="Number of frames held before a new procedural value is generated. Set to 1 for a new value every frame",
                update=_make_effect_animation_update_callback(effect_id, 'step'),
            ),
        )
        setattr(
            bpy.types.Object,
            _effect_animation_property_name(effect_id, 'seed'),
            IntProperty(
                name="Seed", default=0, min=0, max=999999,
                description="Select the deterministic infinite procedural-noise stream",
                update=_make_effect_animation_update_callback(effect_id, 'seed'),
            ),
        )
        setattr(
            bpy.types.Object,
            _effect_animation_property_name(effect_id, 'unique'),
            BoolProperty(
                name="Unique per Layer", default=False,
                description="Give every layer a persistent independent procedural-noise stream",
                update=_make_effect_animation_update_callback(effect_id, 'unique'),
            ),
        )
        setattr(
            bpy.types.Object,
            _effect_animation_property_name(effect_id, 'layer_seed'),
            IntProperty(
                name="Internal Layer Seed", default=0, min=0, max=2147483647,
                description="Persistent internal seed used by Unique per Layer",
                options={'HIDDEN'},
            ),
        )


def _unregister_effect_animation_properties():
    for effect_id in _EFFECT_ANIMATION_IDS:
        for suffix in ('evolve', 'step', 'seed', 'unique', 'layer_seed'):
            attr = _effect_animation_property_name(effect_id, suffix)
            if hasattr(bpy.types.Object, attr):
                try:
                    delattr(bpy.types.Object, attr)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass


def update_object_color_plane_cb(self, context):
    return _call_core('update_object_color_plane_cb', self, context)

def update_object_padding_cb(self, context):
    return _call_core('update_object_padding_cb', self, context)

def update_opacity_cb(self, context):
    return _call_core('update_opacity_cb', self, context)

def update_scene_gradient_preview_cb(self, context):
    return _call_core('update_scene_gradient_preview_cb', self, context)

def update_start_frame_cb(self, context):
    return _call_core('update_start_frame_cb', self, context)

def update_track_cb(self, context):
    return _call_core('update_track_cb', self, context)

def update_visibility_cb(self, context):
    return _call_core('update_visibility_cb', self, context)


def get_collection_holdout(self):
    return _call_layers('get_collection_holdout', self, default=False)

def get_collection_locked(self):
    return _call_layers('get_collection_locked', self, default=False)

def get_collection_selected(self):
    return _call_layers('get_collection_selected', self, default=False)

def get_collection_solo(self):
    return _call_layers('get_collection_solo', self, default=False)

def get_collection_visible(self):
    return _call_layers('get_collection_visible', self, default=True)

def get_layer_holdout(self):
    return _call_layers('get_layer_holdout', self, default=False)

def get_layer_plane_locked(self):
    return _call_layers('get_layer_plane_locked', self, default=False)

def get_layer_rig_locked(self):
    return _call_layers('get_layer_rig_locked', self, default=False)

def get_layer_selected(self):
    return _call_layers('get_layer_selected', self, default=False)

def get_layer_solo_view(self):
    return _call_layers('get_layer_solo_view', self, default=False)

def set_collection_holdout(self, value):
    return _call_layers('set_collection_holdout', self, value)

def set_collection_locked(self, value):
    return _call_layers('set_collection_locked', self, value)

def get_collection_plane_locked(self):
    return _call_layers('get_collection_plane_locked', self, default=True)

def set_collection_plane_locked(self, value):
    return _call_layers('set_collection_plane_locked', self, value)

def set_collection_selected(self, value):
    return _call_layers('set_collection_selected', self, value)

def set_collection_solo(self, value):
    return _call_layers('set_collection_solo', self, value)

def set_collection_visible(self, value):
    return _call_layers('set_collection_visible', self, value)

def set_layer_holdout(self, value):
    return _call_layers('set_layer_holdout', self, value)

def set_layer_plane_locked(self, value):
    return _call_layers('set_layer_plane_locked', self, value)

def set_layer_rig_locked(self, value):
    return _call_layers('set_layer_rig_locked', self, value)

def set_layer_selected(self, value):
    return _call_layers('set_layer_selected', self, value)

def set_layer_solo_view(self, value):
    return _call_layers('set_layer_solo_view', self, value)

# SECTION 01 - PropertyGroup: Layer / Image / Pending Setup #

class FBP_LayerItem(PropertyGroup):
    # Runtime layer row: store only the object name, never an Object PointerProperty.
    # Blender 5.1 can crash while freeing undo/depsgraph IDProperties if a
    # Scene CollectionProperty contains live Object pointers. A string lookup is
    # slightly less direct but far safer for Undo, scene switching and add-on reload.
    obj_name: StringProperty(name="Object Name", default="", options={'SKIP_SAVE'})

    @property
    def obj(self):
        name = getattr(self, "obj_name", "")
        return bpy.data.objects.get(name) if name else None

    @obj.setter
    def obj(self, value):
        try:
            self.obj_name = getattr(value, "name", "") if value else ""
        except Exception:
            self.obj_name = ""

    solo:   BoolProperty(default=False)
    mute:   BoolProperty(default=False, update=update_mute_cb)
    folded: BoolProperty(default=False)

    selected: BoolProperty(
        name="Selected",
        description="Select this layer in the viewport. Click-drag across rows to paint selection",
        get=get_layer_selected,
        set=set_layer_selected)
    rig_locked: BoolProperty(
        name="Lock Rig",
        description="Lock/unlock rig selection. Click-drag across rows to paint locks",
        get=get_layer_rig_locked,
        set=set_layer_rig_locked)
    plane_locked: BoolProperty(
        name="Lock Plane",
        description="Lock/unlock plane selection. Click-drag across rows to paint locks",
        get=get_layer_plane_locked,
        set=set_layer_plane_locked)
    solo_view: BoolProperty(
        name="Solo",
        description="Solo this layer. Click-drag across rows to paint solo visibility",
        get=get_layer_solo_view,
        set=set_layer_solo_view)
    holdout: BoolProperty(
        name="Holdout",
        description="Toggle alpha-aware holdout for this layer. Transparent pixels stay transparent; visible pixels become holdout",
        get=get_layer_holdout,
        set=set_layer_holdout)


def update_text_matrix_quality_cb(self, context):
    if fbp_undo_guard_active():
        return
    preset = str(getattr(self, "fbp_text_matrix_quality", "CUSTOM") or "CUSTOM")
    values = {
        "DRAFT": (24, 48),
        "PREVIEW": (48, 96),
        "FINAL": (72, 160),
    }.get(preset)
    if values:
        fbp_set_rna_property_silent(
            self, "fbp_text_matrix_viewport_columns", values[0]
        )
        fbp_set_rna_property_silent(
            self, "fbp_text_matrix_render_columns", values[1]
        )
        fbp_set_rna_property_silent(self, "fbp_text_matrix_viewport_rows", 0)
        fbp_set_rna_property_silent(self, "fbp_text_matrix_render_rows", 0)
    # Apply columns and the Auto-row reset in one Geometry Nodes evaluation.
    return _call_geometry_nodes('update_text_matrix_grid_settings_cb', self, context)


def get_effect_item_visible(self):
    rig = getattr(self, "id_data", None)
    return bool(_call_geometry_nodes(
        'fbp_effect_item_visible_get', rig, getattr(self, 'effect_id', ''),
        default=True,
    ))


def set_effect_item_visible(self, value):
    rig = getattr(self, "id_data", None)
    _call_geometry_nodes(
        'fbp_effect_item_visible_set', rig, getattr(self, 'effect_id', ''),
        bool(value), default=False,
    )


def get_effect_item_render_visible(self):
    rig = getattr(self, "id_data", None)
    return bool(_call_geometry_nodes(
        'fbp_effect_render_visible_state', rig, getattr(self, 'effect_id', ''),
        default=True,
    ))


def set_effect_item_render_visible(self, value):
    rig = getattr(self, "id_data", None)
    effect_id = getattr(self, 'effect_id', '')
    rigs = _call_geometry_nodes('_fbp_selected_rigs', bpy.context, default=[]) or [rig]
    for target in rigs:
        _call_geometry_nodes(
            'fbp_set_effect_render_visible', target, effect_id, bool(value), default=False,
        )


class FBP_EffectItem(PropertyGroup):
    """Runtime mirror of a supported geometry or shader effect.

    Modifiers and tagged shader group nodes remain the source of truth. These
    lightweight rows are rebuilt for the UIList after material or effect-stack
    changes so stale interface data is never retained.
    """
    effect_id: StringProperty(name="Effect ID", default="", options={'SKIP_SAVE'})
    label: StringProperty(name="Effect", default="Effect", options={'SKIP_SAVE'})
    visible: BoolProperty(
        name="Viewport",
        description="Show or hide this effect only in the viewport. Click-drag across eye icons to paint visibility",
        get=get_effect_item_visible,
        set=set_effect_item_visible,
        options={'SKIP_SAVE'},
    )
    render_visible: BoolProperty(
        name="Render",
        description="Include or exclude this effect from final rendering",
        get=get_effect_item_render_visible,
        set=set_effect_item_render_visible,
        options={'SKIP_SAVE'},
    )


class FBP_ImageItem(PropertyGroup):
    name:        StringProperty(name="Name", default="Image")
    duration:    IntProperty(name="Duration", description="Number of timeline frames this image/frame stays visible", default=2, min=1, update=update_image_duration_cb)
    is_selected: BoolProperty(name="Select", description="Include this frame in frame-list actions such as duplicate, split, sort or delete", default=True)
    is_empty:    BoolProperty(name="Empty", description="Marks this row as a transparent placeholder frame", default=False)
    filepath:    StringProperty(name="File", description="Image or video file used by this frame", subtype='FILE_PATH', default="")
    procedural_kind: EnumProperty(
        name="Frame Type",
        description="Internal type for procedural color/gradient frame rows",
        items=[
            ('AUTO', "Auto", "Infer the procedural frame type from its material"),
            ('SOLID', "Color", "Solid color procedural frame"),
            ('GRADIENT', "Gradient", "Gradient procedural frame"),
            ('HOLDOUT', "Holdout", "Holdout procedural frame"),
        ],
        default='AUTO')
    preview_color_a: FloatVectorProperty(
        name="Color A",
        description="Editable procedural frame color used by the Frames UIList",
        subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
        update=update_frame_preview_color_cb)
    preview_color_b: FloatVectorProperty(
        name="Color B",
        description="Editable second procedural frame color for gradient frames",
        subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
        update=update_frame_preview_color_cb)


class FBP_LayerTreeRowItem(PropertyGroup):
    """Virtual row used by the Layers UIList tree.

    The real layer data remains in Scene.fbp_layers and Collection/Object
    properties. These rows exist only so the Layer Stack can be drawn as a
    real Blender UIList with collapsible collection headers.
    """
    row_type: EnumProperty(
        name="Row Type",
        items=[
            ('GROUP', "Group", "Collection header row"),
            ('LAYER', "Layer", "Frame by Plane layer row"),
        ],
        default='LAYER'
    )
    name: StringProperty(name="Display Name", default="")
    collection_name: StringProperty(name="Collection Name", default="")
    rig_name: StringProperty(name="Rig Name", default="")
    layer_index: IntProperty(name="Layer Index", default=-1)
    depth: IntProperty(name="Depth", default=0, min=0)
    layer_count: IntProperty(name="Direct Layer Count", default=0, min=0)
    child_count: IntProperty(name="Child Collection Count", default=0, min=0)


class FBP_PendingPlaneItem(PropertyGroup):
    name:          StringProperty(name="Name", description="Name of the layer that will be created", default="New Layer")
    collection_name: StringProperty(name="Collection", description="Target collection for this pending layer", default="")
    directory:     StringProperty(name="Source Folder", description="Folder containing the images for this pending layer")
    files_str:     StringProperty(name="Files", description="Internal list of image files that will become this layer sequence")
    follow_collection_color: BoolProperty(
        name="Follow Collection Color",
        description="Internal import rule: inherit the target collection color instead of keeping an independent layer color",
        default=True,
    )
    fbp_color_tag: EnumProperty(name="Color Tag", description="Color tag to assign to the generated rig and collection", items=COLOR_ENUM_ITEMS, default='COLOR_01')


class FBP_PendingTreeRowItem(PropertyGroup):
    """Virtual row used by the Multiplane Setup UIList tree.

    The real import data remains in Scene.fbp_pending_planes. These rows are
    rebuilt only for display, so the UIList can show folder headers and
    collapsible children without changing the actual import model.
    """
    row_type: EnumProperty(
        name="Row Type",
        items=[
            ('GROUP', "Group", "Folder header row"),
            ('LAYER', "Layer", "Importable image layer row"),
        ],
        default='LAYER'
    )
    name: StringProperty(name="Display Name", default="")
    collection_path: StringProperty(name="Collection Path", default="")
    pending_index: IntProperty(name="Pending Layer Index", default=-1)
    depth: IntProperty(name="Depth", default=0, min=0)
    file_count: IntProperty(name="Frame Count", default=0, min=0)
    layer_count: IntProperty(name="Layer Count", default=0, min=0)
    child_count: IntProperty(name="Child Count", default=0, min=0)
    collection_color_editable: BoolProperty(name="Editable Collection Color", default=True, options={'SKIP_SAVE'})
    collection_color_tag: EnumProperty(
        name="Collection Color",
        description="Color tag that will be assigned to this generated collection",
        items=COLLECTION_COLOR_ENUM_ITEMS,
        default='NONE',
        update=update_pending_collection_color_cb,
        options={'SKIP_SAVE'},
    )


class FBP_GenerationRenameItem(PropertyGroup):
    rig_name: StringProperty(name="Rig Name", default="", options={'SKIP_SAVE'})
    display_name: StringProperty(name="Sequence", default="", options={'SKIP_SAVE'})
    message: StringProperty(name="Issue", default="", options={'SKIP_SAVE'})
    preview_files: StringProperty(name="Files", default="", options={'SKIP_SAVE'})
    is_renamed: BoolProperty(name="Renamed", default=False, options={'SKIP_SAVE'})



# SECTION 02 - Scene / Collection / Object property registration #

def register_properties():
    bpy.types.Scene.fbp_last_directory = StringProperty(name="Last Folder", description="Last folder used by Frame by Plane file browsers", subtype='DIR_PATH', default="")
    bpy.types.Scene.fbp_project_path = StringProperty(
        name="Project Folder", description="Root folder used for project import, relinking and health checks", subtype='DIR_PATH', default="")
    bpy.types.Scene.fbp_parent_import_path = StringProperty(
        name="Project Folder", description="Folder used by the current Multiplane Setup", subtype='DIR_PATH')
    bpy.types.Scene.fbp_cam_ratio = EnumProperty(
        name="Camera Ratio",
        items=CAMERA_RATIO_ITEMS,
        default='4_3')
    bpy.types.Scene.fbp_camera_projection = EnumProperty(
        name="Camera Projection",
        description="Projection used by newly generated Frame by Plane cameras",
        items=CAMERA_PROJECTION_ITEMS,
        default='PERSP')
    bpy.types.Scene.fbp_camera_lens = FloatProperty(
        name="Perspective Lens",
        description="Lens in millimeters used by newly generated perspective cameras",
        default=50.0, min=1.0, max=500.0)
    bpy.types.Scene.fbp_camera_ortho_scale = FloatProperty(
        name="Orthographic Scale",
        description="View scale used by newly generated orthographic cameras",
        default=10.0, min=0.001, soft_max=100.0)
    bpy.types.Scene.fbp_camera_clip_start = FloatProperty(
        name="Clip Start", description="Near clipping distance for newly generated cameras",
        default=0.1, min=0.001, soft_max=10.0, unit='LENGTH')
    bpy.types.Scene.fbp_camera_clip_end = FloatProperty(
        name="Clip End", description="Far clipping distance for newly generated cameras",
        default=1000.0, min=1.0, soft_max=10000.0, unit='LENGTH')
    bpy.types.Scene.fbp_show_previews = BoolProperty(name="Show Thumbnails", description="Show image thumbnails for imported image/video layers", default=False)
    bpy.types.Scene.fbp_show_color_previews = BoolProperty(name="Show Color Preview", description="Show color/gradient chips in Layer and Frame lists instead of generic procedural icons", default=True)
    bpy.types.Scene.fbp_sort_layers_alpha = BoolProperty(
        name="A-Z",
        description="Sort layers and collections alphabetically instead of by camera distance",
        default=False)
    bpy.types.Scene.fbp_auto_clean_orphans = BoolProperty(
        name="Auto-clean orphan Frame by Plane objects",
        description="After normal deletion, remove FBP planes left without their rig and purge unused FBP datablocks. Image files on disk are never deleted",
        default=True)
    bpy.types.Scene.fbp_show_create_tools = BoolProperty(name="Show Create Tools", description="Show additional creation tools in the sidebar", default=False)
    bpy.types.Scene.fbp_render_output_dir = StringProperty(
        name="Render Folder",
        description="Folder where the background-rendered frame sequence is saved. Empty creates FBP_Render_Frames beside the .blend file",
        subtype='DIR_PATH',
        default="")
    bpy.types.Scene.fbp_render_prefix = StringProperty(
        name="Filename Prefix",
        description="Filename prefix used for background-rendered frames",
        default="frame_")
    bpy.types.Scene.fbp_background_render_running = BoolProperty(name="Background Render Running", default=False, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_background_render_status = StringProperty(name="Background Render Status", default="Idle", options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_background_render_progress = IntProperty(name="Rendered Frames", default=0, min=0, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_background_render_total = IntProperty(name="Total Frames", default=0, min=0, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_background_render_output_dir = StringProperty(name="Output Folder", default="", subtype='DIR_PATH', options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_generation_rename_items = CollectionProperty(type=FBP_GenerationRenameItem, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_generation_rename_index = IntProperty(name="Rename Sequence Index", description="Active problematic sequence in the generation rename list", default=0, min=0, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_auto_collection_color_variants = BoolProperty(name="Collection Color Variants", description="Give layers small viewport color variations based on their collection color", default=True)
    bpy.types.Scene.fbp_layers = CollectionProperty(type=FBP_LayerItem, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_layer_stack_index = IntProperty(
        name="Layer Index", description="Active layer row in the Frame by Plane layer list", default=0, update=update_layer_stack_index_cb)
    bpy.types.Scene.fbp_layer_tree_rows = CollectionProperty(type=FBP_LayerTreeRowItem, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_layer_tree_rows_idx = IntProperty(name="Layer Tree Row", description="Active visual row in the Layers tree UIList", default=0, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_layer_tree_signature = StringProperty(name="Layer Tree Signature", default="", options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_pending_open_collections = StringProperty(name="Open Setup Collections", default="", options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_gradient_preview_material_name = StringProperty(name="Gradient Preview Material", default="", options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_creation_mode = EnumProperty(
        name="Mode",
        items=CREATION_MODE_ITEMS,
        default='COLOR')
    bpy.types.Scene.fbp_effects_view = EnumProperty(
        name="Effect Type",
        description="Choose whether the Effects panel shows image-processing or mesh effects",
        items=(
            ('2D', "Image Effects", "Show Base and image-processing shader effects", fbp_icon("NODE_TEXTURE"), 0),
            ('3D', "Mesh Effects", "Show Geometry Nodes and mesh effects", fbp_icon("MODIFIER"), 1),
        ),
        default='2D',
        update=update_effects_view_cb,
    )
    bpy.types.Scene.fbp_pending_planes = CollectionProperty(type=FBP_PendingPlaneItem)
    bpy.types.Scene.fbp_pending_planes_idx = IntProperty(name="Setup Layer Index", description="Active pending layer in the Multiplane Setup", default=0)
    bpy.types.Scene.fbp_pending_tree_rows = CollectionProperty(type=FBP_PendingTreeRowItem, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_pending_tree_rows_idx = IntProperty(name="Setup Tree Row", description="Active visual row in the Multiplane Setup tree UIList", default=0, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_pending_collection_name = StringProperty(name="Collection", description="Name used when creating a new Multiplane Setup collection", default="New Collection")
    bpy.types.Scene.fbp_pre_duration = IntProperty(
        name="Duration (Frames)", description="Default duration assigned to each imported image frame", default=2, min=1)
    bpy.types.Scene.fbp_pre_shadeless = BoolProperty(name="Shadeless", description="Use lightweight emission materials so image planes are not affected by scene lighting", default=True)
    bpy.types.Scene.fbp_pre_loop_mode = EnumProperty(
        name="Playback",
        items=PLAYBACK_ITEMS,
        default='NONE')
    bpy.types.Scene.fbp_pre_interpolation = EnumProperty(
        name="",
        items=INTERPOLATION_ITEMS,
        default='Closest')
    bpy.types.Scene.fbp_pre_orientation = EnumProperty(
        name="",
        items=ORIENTATION_ITEMS,
        default='VERT')
    bpy.types.Scene.fbp_gen_camera   = BoolProperty(name="Generate Camera", description="Create or update a camera suitable for the generated multiplane setup", default=True)
    bpy.types.Scene.fbp_cam_pivot    = BoolProperty(name="Pivot on Camera", description="Move the 3D cursor to the camera pivot when creating a camera setup", default=True)
    bpy.types.Scene.fbp_layer_offset = FloatProperty(name="Plane Distance (m)", description="Distance between generated layers; imported top-level collections use a larger gap", default=0.2, min=0.001)
    bpy.types.Scene.fbp_auto_scale   = BoolProperty(name="Auto-Scale (Fit to Cam)", description="Scale generated planes to the camera frame using the image aspect ratio", default=True)
    bpy.types.Scene.fbp_pre_track_cam = BoolProperty(name="Track Camera on New Layers", description="Add camera tracking to newly generated Frame by Plane layers", default=False)
    bpy.types.Scene.fbp_settings_primary_open = BoolProperty(
        name="Primary Settings Section",
        description="Expand the first group in the active Settings category",
        default=False,
        options={'SKIP_SAVE'},
    )
    bpy.types.Scene.fbp_settings_secondary_open = BoolProperty(
        name="Secondary Settings Section",
        description="Expand the second group in the active Settings category",
        default=False,
        options={'SKIP_SAVE'},
    )
    bpy.types.Scene.fbp_settings_section = EnumProperty(
        name="Settings Section",
        description="Choose which Frame by Plane settings group to display",
        items=[
            ('PROJECT', "Project", "Project folder and file settings"),
            ('CAMERA', "Camera", "Camera projection and frame ratio"),
            ('RENDER', "Render", "Background render controls"),
            ('MAINTENANCE', "Maintenance", "Repair, relink, diagnostics and project statistics"),
        ],
        default='PROJECT',
        update=update_settings_section_cb,
    )
    bpy.types.Scene.fbp_show_project_tools = BoolProperty(name="Project Import", description="Show advanced project and folder import controls", default=True)
    bpy.types.Scene.fbp_color_plane_type = EnumProperty(
        name="Plane Type",
        description="Choose what kind of camera-ratio plane to create",
        items=COLOR_PLANE_TYPE_ITEMS,
        default='CUSTOM')
    bpy.types.Scene.fbp_color_plane_color = FloatVectorProperty(
        name="Color", description="Solid color used when creating a Color Plane", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0), update=update_color_plane_color_cb)
    bpy.types.Scene.fbp_color_plane_preset = EnumProperty(
        name="Preset",
        description="Quick color preset for solid Color Plane creation",
        items=COLOR_PLANE_PRESET_ITEMS,
        default='CUSTOM', update=update_color_plane_preset_cb)
    bpy.types.Scene.fbp_color_plane_emission = BoolProperty(name="Emission", description="Use a lightweight emission shader for the color plane", default=True, update=update_scene_gradient_preview_cb)
    bpy.types.Scene.fbp_gradient_mode = EnumProperty(
        name="Gradient Mode", description="Shape of the generated gradient color plane",
        items=GRADIENT_MODE_ITEMS, default='LINEAR', update=update_scene_gradient_preview_cb)
    bpy.types.Scene.fbp_gradient_kind = EnumProperty(
        name="Gradient Type", description="Choose whether the gradient blends between two colors or changes alpha",
        items=GRADIENT_KIND_ITEMS, default='COLOR', update=update_scene_gradient_preview_cb)
    bpy.types.Scene.fbp_gradient_color_a = FloatVectorProperty(name="From", subtype='COLOR', size=4, min=0.0, max=1.0, description="Start color of the gradient ramp. In alpha mode this side is forced transparent", default=(1.0, 0.3686274509803922, 0.596078431372549, 1.0), update=update_scene_gradient_preview_cb)
    bpy.types.Scene.fbp_gradient_color_b = FloatVectorProperty(name="To", subtype='COLOR', size=4, min=0.0, max=1.0, description="End color of the gradient ramp or visible color in alpha mode", default=(0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0), update=update_scene_gradient_preview_cb)
    bpy.types.Scene.fbp_gradient_reverse = BoolProperty(name="Reverse Gradient", description="Swap the start and end of the generated gradient", default=True, update=update_scene_gradient_preview_cb)
    bpy.types.Scene.fbp_gradient_offset_x = FloatProperty(name="Gradient X Offset", description="Move the generated gradient horizontally before creating the plane", default=0.0, soft_min=-2.0, soft_max=2.0)
    bpy.types.Scene.fbp_gradient_offset_y = FloatProperty(name="Gradient Y Offset", description="Move the generated gradient vertically before creating the plane", default=0.0, soft_min=-2.0, soft_max=2.0)
    bpy.types.Scene.fbp_gradient_scale_x = FloatProperty(name="Gradient Scale X", description="Stretch or compress the generated gradient horizontally", default=1.0, min=0.001, soft_min=0.1, soft_max=10.0)
    bpy.types.Scene.fbp_gradient_scale_y = FloatProperty(name="Gradient Scale Y", description="Stretch or compress the generated gradient vertically", default=1.0, min=0.001, soft_min=0.1, soft_max=10.0)
    bpy.types.Scene.fbp_gradient_rotation = FloatProperty(name="Gradient Rotation", description="Rotate the generated gradient in degrees", default=0.0, soft_min=-180.0, soft_max=180.0)
    bpy.types.Scene.fbp_show_gradient_ramp = BoolProperty(name="Show Gradient Ramp", description="Show the advanced ColorRamp controls", default=True)
    bpy.types.Scene.fbp_show_gradient_transform = BoolProperty(name="Show Gradient Position", description="Show gradient position, scale and rotation controls", default=True)
    bpy.types.Collection.is_fbp_collection = BoolProperty(default=False)
    bpy.types.Collection.fbp_collapsed = BoolProperty(name="Collapsed", description="Collapse or expand this collection in the Frame by Plane Layers list", default=True)
    bpy.types.Collection.fbp_collection_selected = BoolProperty(name="Select Collection Layers", description="Select or deselect all Frame by Plane layers inside this collection. Click-drag across matching icons to paint selection", get=get_collection_selected, set=set_collection_selected)
    bpy.types.Collection.fbp_collection_solo = BoolProperty(name="Solo Collection Layers", description="Solo or unsolo all Frame by Plane layers inside this collection. Click-drag across matching icons to paint solo state", get=get_collection_solo, set=set_collection_solo)
    bpy.types.Collection.fbp_collection_locked = BoolProperty(name="Lock Collection Layers", description="Lock or unlock all Frame by Plane rigs in this collection. Click-drag across matching icons to paint locks", get=get_collection_locked, set=set_collection_locked)
    bpy.types.Collection.fbp_collection_plane_locked = BoolProperty(name="Lock Collection Planes", description="Lock or unlock linked image/color planes in this collection. Click-drag across matching icons to paint plane selectability", get=get_collection_plane_locked, set=set_collection_plane_locked)
    bpy.types.Collection.fbp_collection_visible = BoolProperty(name="Show Collection Layers", description="Show or hide this Frame by Plane collection in the viewport. Click-drag across matching icons to paint visibility", get=get_collection_visible, set=set_collection_visible)
    bpy.types.Collection.fbp_collection_holdout = BoolProperty(name="Holdout Collection Layers", description="Toggle alpha-aware holdout on all Frame by Plane layers inside this collection. Click-drag across matching icons to paint holdouts", get=get_collection_holdout, set=set_collection_holdout)

    bpy.types.Object.is_fbp_control     = BoolProperty(default=False)
    bpy.types.Object.is_fbp_plane       = BoolProperty(default=False)
    bpy.types.Object.fbp_collection_name = StringProperty(name="FBP Collection", description="Internal name of the collection this Frame by Plane layer belongs to", default="")
    bpy.types.Object.fbp_follow_collection_color = BoolProperty(name="Follow Collection Color", description="Use the parent collection color tag as the rig viewport color", default=True)
    bpy.types.Object.fbp_color_variant_index = IntProperty(name="Color Variant", description="Internal color variation index used to make layers readable", default=0)
    bpy.types.Object.fbp_base_scale_vec = FloatVectorProperty(name="Base Scale Vector", description="Original generated scale vector used by Fit to Camera", default=(1.0, 1.0, 1.0))
    bpy.types.Object.fbp_preview_path   = StringProperty(name="Preview Path", description="Image path used for the layer thumbnail preview", default="")
    bpy.types.Object.fbp_is_vertical    = BoolProperty(name="Vertical", description="Whether this layer is standing vertically instead of lying horizontally", default=False)
    bpy.types.Object.fbp_images         = CollectionProperty(type=FBP_ImageItem)
    bpy.types.Object.fbp_images_index   = IntProperty(name="Active Frame", description="Active frame row in the selected Frame by Plane sequence", update=update_image_index_cb)
    bpy.types.Object.fbp_color_tag      = EnumProperty(
        name="Color Tag", description="Viewport and collection color tag for this Frame by Plane layer",
        items=COLOR_ENUM_ITEMS, default='COLOR_01', update=update_color_tag_cb)
    bpy.types.Object.fbp_depth_order    = IntProperty(name="Depth Order", description="Internal depth order used for generated layers", default=0)
    bpy.types.Object.fbp_loop_mode = EnumProperty(
        name="Playback",
        items=[
            ('NONE',     "One Shot",  "Play the sequence once and hold the last frame", fbp_icon("FORWARD"),        0),
            ('REPEAT',   "Loop",      "Repeat the image sequence indefinitely", fbp_icon("FILE_REFRESH"),   1),
            ('PINGPONG', "Ping-Pong", "Play forward and backward in a loop", fbp_icon("UV_SYNC_SELECT"), 2),
        ],
        default='NONE', update=update_loop_mode_cb)
    bpy.types.Object.fbp_use_emission   = BoolProperty(
        name="Shadeless", description="Use an emission-style material so the image is not affected by scene lighting", default=False, update=update_emission_cb)
    bpy.types.Object.fbp_interpolation  = EnumProperty(
        name="Filter",
        items=[
            ('Closest', "Pixel",  "Use nearest-neighbor filtering for sharp pixel edges", fbp_icon("SNAP_GRID"), 0),
            ('Linear',  "Smooth", "Use linear filtering for smoother image scaling", fbp_icon("IMAGE_RGB"), 1),
        ],
        default='Closest')
    bpy.types.Object.fbp_plane_target    = PointerProperty(name="Linked Plane", description="Image plane controlled by this Frame by Plane rig", type=bpy.types.Object)
    bpy.types.Object.fbp_global_duration = IntProperty(
        name="Global Duration", description="Set the duration in frames for all frames in this sequence", default=2, min=1, update=update_global_duration_cb)
    bpy.types.Object.fbp_start_frame     = IntProperty(
        name="Start Frame", description="Timeline frame where this sequence starts playing", default=1, update=update_start_frame_cb)
    bpy.types.Object.fbp_opacity         = FloatProperty(
        name="Opacity", description="Opacity of the selected layer material", default=1.0, min=0.0, max=1.0,
        subtype='FACTOR', update=update_opacity_cb)
    bpy.types.Object.fbp_track_cam       = BoolProperty(
        name="Track Camera", description="Constrain this layer to face the active camera", default=False, update=update_track_cb)
    bpy.types.Object.fbp_is_visible      = BoolProperty(
        name="Visible", description="Show or hide this Frame by Plane layer in the viewport and render", default=True, update=update_visibility_cb)
    bpy.types.Object.fbp_is_color_plane = BoolProperty(name="Is Color Plane", description="Internal flag for rigged Frame by Plane color, holdout and gradient planes", default=False)
    bpy.types.Object.fbp_color_plane_mode = EnumProperty(
        name="Plane Type", description="Change the selected color plane between solid color, gradient and holdout material",
        items=[('SOLID', "Solid", "Use one editable solid color"), ('GRADIENT', "Gradient", "Use an editable color-ramp gradient"), ('HOLDOUT', "Holdout", "Use a compositor holdout material")],
        default='SOLID', update=update_object_color_plane_cb)
    bpy.types.Object.fbp_color_plane_color = FloatVectorProperty(name="Color", subtype='COLOR', size=4, min=0.0, max=1.0, description="Solid color used by this Frame by Plane color plane", default=(1.0, 1.0, 1.0, 1.0), update=update_object_color_plane_cb)
    bpy.types.Object.fbp_color_plane_emission = BoolProperty(name="Emission", description="Use a lightweight emission shader for this color or gradient plane", default=True, update=update_object_color_plane_cb)
    bpy.types.Object.fbp_gradient_mode = EnumProperty(
        name="Gradient Mode", description="Shape of this plane gradient",
        items=[('LINEAR', "Linear", "Linear gradient from one side of the plane to the other", fbp_icon("ARROW_LEFTRIGHT"), 0), ('CENTER', "Radial", "Centered radial gradient useful for vignettes", fbp_icon("EMPTY_ARROWS"), 1)], default='LINEAR', update=update_object_color_plane_cb)
    bpy.types.Object.fbp_gradient_kind = EnumProperty(
        name="Gradient Type", description="Choose whether this gradient blends between two colors or changes alpha",
        items=[('COLOR', "Color to Color", "Blend between the From and To colors", fbp_icon("COLOR"), 0), ('ALPHA', "Transparent to Visible", "Fade from the From color at 0 alpha to the To color", fbp_icon("IMAGE_ALPHA"), 1)], default='COLOR', update=update_object_color_plane_cb)
    bpy.types.Object.fbp_gradient_color_a = FloatVectorProperty(name="From", subtype='COLOR', size=4, min=0.0, max=1.0, description="Start color of the gradient ramp. In alpha mode this side is forced transparent", default=(1.0, 0.3686274509803922, 0.596078431372549, 1.0), update=update_object_color_plane_cb)
    bpy.types.Object.fbp_gradient_color_b = FloatVectorProperty(name="To", subtype='COLOR', size=4, min=0.0, max=1.0, description="End color of the gradient ramp", default=(0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0), update=update_object_color_plane_cb)
    bpy.types.Object.fbp_gradient_reverse = BoolProperty(name="Reverse Gradient", description="Swap the From and To sides of this gradient", default=True, update=update_object_color_plane_cb)
    bpy.types.Object.fbp_gradient_offset_x = FloatProperty(name="Gradient X Offset", description="Move this gradient horizontally on the plane", default=0.0, soft_min=-2.0, soft_max=2.0, update=update_gradient_mapping_cb)
    bpy.types.Object.fbp_gradient_offset_y = FloatProperty(name="Gradient Y Offset", description="Move this gradient vertically on the plane", default=0.0, soft_min=-2.0, soft_max=2.0, update=update_gradient_mapping_cb)
    bpy.types.Object.fbp_gradient_scale_x = FloatProperty(name="Gradient Scale X", description="Stretch or compress this gradient horizontally", default=1.0, min=0.001, soft_min=0.1, soft_max=10.0, update=update_gradient_mapping_cb)
    bpy.types.Object.fbp_gradient_scale_y = FloatProperty(name="Gradient Scale Y", description="Stretch or compress this gradient vertically", default=1.0, min=0.001, soft_min=0.1, soft_max=10.0, update=update_gradient_mapping_cb)
    bpy.types.Object.fbp_gradient_rotation = FloatProperty(name="Gradient Rotation", description="Rotate this gradient in degrees", default=0.0, soft_min=-180.0, soft_max=180.0, update=update_gradient_mapping_cb)
    bpy.types.Object.fbp_show_gradient_ramp = BoolProperty(name="Show Gradient Ramp", description="Show the advanced ColorRamp controls for this plane", default=True)
    bpy.types.Object.fbp_show_gradient_transform = BoolProperty(name="Show Gradient Position", description="Show the gradient position, scale and rotation controls for this plane", default=True)
    bpy.types.Object.fbp_extend_mode = EnumProperty(name="Extend Mode", description="How the added border geometry samples the original image", items=[('EDGE', "Edge Pixel", "Clamp added geometry to the cropped image edge"), ('REPEAT', "Repeat Texture", "Repeat the texture into the added geometry")], default='EDGE', update=update_object_padding_cb)
    bpy.types.Object.fbp_extend_left = FloatProperty(name="Left", description="Extend the left edge after crop without scaling the image center", default=0.0, min=0.0, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_object_padding_cb)
    bpy.types.Object.fbp_extend_right = FloatProperty(name="Right", description="Extend the right edge after crop without scaling the image center", default=0.0, min=0.0, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_object_padding_cb)
    bpy.types.Object.fbp_extend_top = FloatProperty(name="Top", description="Extend the top edge after crop without scaling the image center", default=0.0, min=0.0, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_object_padding_cb)
    bpy.types.Object.fbp_extend_bottom = FloatProperty(name="Bottom", description="Extend the bottom edge after crop without scaling the image center", default=0.0, min=0.0, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_object_padding_cb)
    bpy.types.Object.fbp_crop_left = FloatProperty(name="Left", description="Crop the left edge before extension is applied", default=0.0, min=0.0, max=1.95, update=update_object_padding_cb)
    bpy.types.Object.fbp_crop_right = FloatProperty(name="Right", description="Crop the right edge before extension is applied", default=0.0, min=0.0, max=1.95, update=update_object_padding_cb)
    bpy.types.Object.fbp_crop_top = FloatProperty(name="Top", description="Crop the top edge before extension is applied", default=0.0, min=0.0, max=1.95, update=update_object_padding_cb)
    bpy.types.Object.fbp_crop_bottom = FloatProperty(name="Bottom", description="Crop the bottom edge before extension is applied", default=0.0, min=0.0, max=1.95, update=update_object_padding_cb)
    bpy.types.Object.fbp_effects = CollectionProperty(
        type=FBP_EffectItem,
        description="Runtime list of geometry and shader effects shared by the selected Frame by Plane layers",
        options={'SKIP_SAVE'})
    bpy.types.Object.fbp_effects_index = IntProperty(
        name="Active Effect",
        description="Selected effect in the Frame by Plane effect stack",
        default=0, min=0, options={'SKIP_SAVE'})
    bpy.types.Object.fbp_effects_signature = StringProperty(
        name="Effect Stack Signature", default="", options={'SKIP_SAVE'})
    bpy.types.Object.fbp_mesh_wiggle_enabled = BoolProperty(
        name="Wiggle",
        description="Enable the bundled Wiggle Geometry Nodes effect on this Frame by Plane layer",
        default=False,
        update=update_mesh_wiggle_enabled_cb)
    bpy.types.Object.fbp_mesh_wiggle_shade_smooth = BoolProperty(
        name="Shade Smooth",
        description="Smooth the subdivided Wiggle geometry",
        default=True,
        update=update_mesh_wiggle_shade_smooth_cb)
    bpy.types.Object.fbp_mesh_wiggle_strength = FloatProperty(
        name="Strength",
        description="Strength of the Wiggle deformation. Set to zero to keep the noise fixed visually",
        default=1.0, min=0.0, soft_max=3.0, precision=3,
        update=update_mesh_wiggle_strength_cb)
    bpy.types.Object.fbp_mesh_wiggle_speed = FloatProperty(
        name="Speed",
        description="Automatic Scene Time evolution speed",
        default=10.0, soft_min=-20.0, soft_max=20.0, precision=3,
        update=update_mesh_wiggle_speed_cb)
    bpy.types.Object.fbp_mesh_wiggle_hold = IntProperty(
        name="Stepped",
        description="Number of frames held before the Wiggle noise updates",
        default=4, min=1, soft_max=24,
        update=update_mesh_wiggle_hold_cb)
    bpy.types.Object.fbp_mesh_wiggle_w = FloatProperty(
        name="Noise Phase (W)",
        description="Fourth coordinate of the 4D Noise Texture. It shifts the noise pattern without moving the plane",
        default=0.0, soft_min=-20.0, soft_max=20.0, precision=3,
        update=update_mesh_wiggle_w_cb)
    bpy.types.Object.fbp_mesh_wiggle_seed = IntProperty(
        name="Seed",
        description="Integer offset used to choose a repeatable Wiggle noise pattern",
        default=0, min=0, max=999999,
        update=update_mesh_wiggle_seed_cb)
    bpy.types.Object.fbp_mesh_wiggle_unique_seed = BoolProperty(
        name="Unique per Layer",
        description="Add a persistent per-layer seed so selected planes can share settings without sharing the same noise pattern",
        default=False,
        update=update_mesh_wiggle_unique_seed_cb)
    bpy.types.Object.fbp_mesh_wiggle_layer_seed = IntProperty(
        name="Internal Layer Seed",
        description="Persistent internal seed used by Unique per Layer",
        default=0, min=0, max=2147483647, options={'HIDDEN'})
    bpy.types.Object.fbp_mesh_wiggle_noise_scale = FloatProperty(
        name="Noise Scale",
        description="Scale of the noise used by Mesh Wiggle",
        default=5.0, min=0.001, soft_max=20.0, precision=3,
        update=update_mesh_wiggle_noise_scale_cb)
    bpy.types.Object.fbp_mesh_wiggle_detail = FloatProperty(
        name="Noise Detail",
        description="Fractal detail of the Wiggle noise",
        default=0.0, min=0.0, soft_max=15.0, precision=3,
        update=update_mesh_wiggle_detail_cb)
    bpy.types.Object.fbp_mesh_wiggle_subdivisions = IntProperty(
        name="Subdivisions",
        description="Subdivision level applied before the Wiggle deformation",
        default=4, min=0, max=6,
        update=update_mesh_wiggle_subdivisions_cb)

    # Additional geometry effects from the corrected bundled library
    bpy.types.Object.fbp_stop_motion_resolution = IntProperty(name="Resolution", default=5, min=0, max=6, update=update_stop_motion_resolution_cb)
    bpy.types.Object.fbp_stop_motion_strength = FloatProperty(name="Strength", default=0.05, min=0.0, soft_max=1.0, precision=3, update=update_stop_motion_strength_cb)
    bpy.types.Object.fbp_stop_motion_step_frames = IntProperty(name="Step Frames", default=3, min=1, soft_max=24, update=update_stop_motion_step_frames_cb)
    bpy.types.Object.fbp_wind_bend_amount = FloatProperty(name="Bend Amount", default=0.5, soft_min=-2.0, soft_max=2.0, precision=3, update=update_wind_bend_amount_cb)
    bpy.types.Object.fbp_wind_speed = FloatProperty(name="Wind Speed", default=2.0, soft_min=-20.0, soft_max=20.0, precision=3, update=update_wind_speed_cb)
    bpy.types.Object.fbp_wind_pin_edge = EnumProperty(
        name="Pin Edge", description="Side that remains attached while the remaining plane moves",
        items=(
            ('LEFT', "Left", "Attach the left edge"),
            ('RIGHT', "Right", "Attach the right edge"),
            ('BOTTOM', "Bottom", "Attach the bottom edge"),
            ('TOP', "Top", "Attach the top edge"),
        ), default='LEFT', update=update_wind_pin_edge_cb)
    bpy.types.Object.fbp_wind_motion_mode = EnumProperty(
        name="Motion Mode", description="Choose a global sway or waves that travel across the plane",
        items=(
            ('SWAY', "Sway", "Oscillate the plane back and forth from the pinned edge"),
            ('FLOW', "Flowing Waves", "Move sine waves from the pinned edge toward the free edge"),
        ), default='SWAY', update=update_wind_motion_mode_cb)
    bpy.types.Object.fbp_wind_wave_count = FloatProperty(
        name="Wave Count", description="Number of waves distributed between pinned and free edge",
        default=2.0, min=0.0, soft_max=10.0, max=40.0, update=update_wind_wave_count_cb)
    bpy.types.Object.fbp_wind_wave_amplitude = FloatProperty(
        name="Wave Amplitude", default=0.12, min=0.0, soft_max=1.0, max=10.0, update=update_wind_wave_amplitude_cb)
    bpy.types.Object.fbp_wind_wave_speed = FloatProperty(
        name="Wave Speed", default=2.0, soft_min=-20.0, soft_max=20.0, update=update_wind_wave_speed_cb)
    bpy.types.Object.fbp_wind_phase = FloatProperty(
        name="Phase", default=0.0, soft_min=-6.283185, soft_max=6.283185, subtype='ANGLE', update=update_wind_phase_cb)
    bpy.types.Object.fbp_wind_turbulence = FloatProperty(
        name="Turbulence", description="Small irregular motion layered over the main deformation",
        default=0.03, min=0.0, soft_max=0.3, max=2.0, update=update_wind_turbulence_cb)
    bpy.types.Object.fbp_wind_reverse = BoolProperty(
        name="Reverse Direction", description="Flip the wind deformation direction",
        default=False, update=update_wind_reverse_cb)
    bpy.types.Object.fbp_wind_falloff = FloatProperty(
        name="Falloff", description="Shape how strongly the pinned edge stays fixed",
        default=1.5, min=0.1, max=8.0, update=update_wind_falloff_cb)
    bpy.types.Object.fbp_wind_noise_scale = FloatProperty(
        name="Noise Scale", description="Spatial scale of wind turbulence",
        default=3.0, min=0.01, soft_max=20.0, max=100.0, update=update_wind_noise_scale_cb)
    bpy.types.Object.fbp_wind_gust_strength = FloatProperty(
        name="Gust Strength", description="Add slower non-periodic gust variation",
        default=0.0, min=0.0, soft_max=1.0, max=4.0, update=update_wind_gust_strength_cb)
    bpy.types.Object.fbp_wind_direction_space = EnumProperty(
        name="Direction Space",
        description="Interpret Wind Direction in the plane local axes or in world axes",
        items=(("LOCAL", "Local", "Direction rotates with the plane"),
               ("WORLD", "World", "Direction stays aligned to the world")),
        default="LOCAL", update=update_wind_direction_space_cb)
    bpy.types.Object.fbp_wind_direction = FloatVectorProperty(
        name="Wind Direction", description="Direction used for the wind displacement",
        size=3, subtype='DIRECTION', default=(0.0, 0.0, 1.0),
        min=-1.0, max=1.0, update=update_wind_direction_cb)
    bpy.types.Object.fbp_wind_preview_falloff = BoolProperty(
        name="Preview Falloff",
        description="Temporarily replace animated wind with a static displacement that visualizes pinned-edge falloff",
        default=False, update=update_wind_preview_falloff_cb)
    bpy.types.Object.fbp_felt_render_density = IntProperty(
        name="Render Density",
        description="Approximate total number of rendered strands",
        default=50000, min=1000, soft_max=3000000, max=3000000, step=100,
        options={'ANIMATABLE'}, update=update_felt_render_density_cb)
    bpy.types.Object.fbp_felt_viewport_percentage = FloatProperty(
        name="Viewport %", description="Fraction of the render strand count displayed in the viewport",
        default=0.0025, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_felt_viewport_percentage_cb)
    bpy.types.Object.fbp_felt_fuzz_length = FloatProperty(
        name="Fuzz Length", default=0.04, min=0.0, soft_max=0.5, max=10.0,
        precision=4, subtype='DISTANCE', options={'ANIMATABLE'}, update=update_felt_fuzz_length_cb)
    bpy.types.Object.fbp_felt_subdivisions = IntProperty(
        name="Subdivisions", description="Number of points along every strand; increase for smooth, tightly curled wool",
        default=3, min=2, soft_max=24, max=64, options={'ANIMATABLE'}, update=update_felt_subdivisions_cb)
    bpy.types.Object.fbp_felt_curl_amount = FloatProperty(
        name="Curl Amount", description="Number and intensity of curls along each strand",
        default=1.0, min=0.0, soft_max=5.0, max=12.0, precision=3,
        options={'ANIMATABLE'}, update=update_felt_curl_amount_cb)
    bpy.types.Object.fbp_felt_fuzz_radius = FloatProperty(
        name="Fuzz Radius", default=0.0005, min=0.00001, soft_min=0.0005,
        soft_max=0.05, max=1.0, precision=6, subtype='DISTANCE', options={'ANIMATABLE'},
        update=update_felt_fuzz_radius_cb)
    bpy.types.Object.fbp_felt_seed = IntProperty(
        name="Seed", default=0, min=0, max=2147483647, options={'ANIMATABLE'}, update=update_felt_seed_cb)
    bpy.types.Object.fbp_felt_alpha_threshold = FloatProperty(name="Alpha Threshold", default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_felt_alpha_threshold_cb)
    bpy.types.Object.fbp_felt_alpha_resolution = IntProperty(name="Alpha Resolution", description="Subdivision detail used only to sample the image alpha for fiber placement", default=2, min=2, max=6, update=update_felt_alpha_resolution_cb)

    bpy.types.Object.fbp_wind_subdivision = IntProperty(name="Subdivision", default=4, min=0, max=6, update=update_wind_subdivision_cb)
    bpy.types.Object.fbp_wind_stepped = IntProperty(name="Stepped", default=1, min=1, soft_max=24, update=update_wind_stepped_cb)

    bpy.types.Object.fbp_thickness_amount = FloatProperty(name="Thickness", default=0.02, min=0.0, soft_max=0.25, precision=4, subtype='DISTANCE', update=update_thickness_amount_cb)
    bpy.types.Object.fbp_thickness_side_material = PointerProperty(name="Side / Back Material", type=bpy.types.Material, update=update_thickness_side_material_cb)
    bpy.types.Object.fbp_thickness_side_color = FloatVectorProperty(name="Side / Back Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.18, 0.12, 0.08, 1.0), update=update_thickness_side_color_cb)
    bpy.types.Object.fbp_thickness_alpha_threshold = FloatProperty(name="Alpha Threshold", default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_thickness_alpha_threshold_cb)
    bpy.types.Object.fbp_thickness_alpha_resolution = IntProperty(name="Alpha Resolution", default=5, min=0, max=6, update=update_thickness_alpha_resolution_cb)

    bpy.types.Object.fbp_infinite_rotation_speed = FloatProperty(name="Speed", description="Degrees rotated per frame", default=1.0, min=0.0, soft_max=30.0, precision=3, update=update_infinite_rotation_speed_cb)
    bpy.types.Object.fbp_infinite_rotation_direction = EnumProperty(name="Direction", items=(('RIGHT', "Clockwise", "Rotate clockwise"), ('LEFT', "Counter-clockwise", "Rotate counter-clockwise")), default='RIGHT', update=update_infinite_rotation_direction_cb)
    bpy.types.Object.fbp_infinite_rotation_stepped = IntProperty(name="Stepped", default=1, min=1, soft_max=24, update=update_infinite_rotation_stepped_cb)
    bpy.types.Object.fbp_infinite_rotation_offset = FloatProperty(name="Offset (°)", default=0.0, soft_min=-360.0, soft_max=360.0, precision=2, update=update_infinite_rotation_offset_cb)

    # Shader effects
    bpy.types.Object.fbp_uv_distortion_scale = FloatProperty(
        name="Noise Scale", default=10.0, min=0.001, soft_max=100.0, precision=3, update=update_uv_distortion_scale_cb)
    bpy.types.Object.fbp_uv_distortion_amount = FloatProperty(
        name="Distortion Amount", default=0.05, soft_min=-1.0, soft_max=1.0, precision=3, update=update_uv_distortion_amount_cb)
    bpy.types.Object.fbp_pixelate_resolution = FloatProperty(
        name="Pixel Density", description="Number of pixel cells across the plane width; lower values create larger blocks",
        default=64.0, min=1.0, soft_max=2048.0, precision=1, update=update_pixelate_resolution_cb)
    bpy.types.Object.fbp_pixelate_square_pixels = BoolProperty(
        name="Square Pixels", description="Compensate for the plane aspect ratio so pixel blocks appear square",
        default=True, update=update_pixelate_square_pixels_cb)
    bpy.types.Object.fbp_grain_strength = FloatProperty(
        name="Intensity", default=0.2, min=0.0, max=1.0, subtype='FACTOR', update=update_grain_strength_cb)
    bpy.types.Object.fbp_grain_scale = FloatProperty(
        name="Grain Scale", default=180.0, min=0.01, soft_max=2000.0, precision=2, update=update_grain_scale_cb)
    bpy.types.Object.fbp_grain_seed = FloatProperty(
        name="Animate (W)", default=0.0, soft_min=-100.0, soft_max=100.0, precision=3, update=update_grain_seed_cb)
    bpy.types.Object.fbp_digital_noise_luma = FloatProperty(
        name="Luminance Noise", description="Monochromatic high-ISO noise amount",
        default=0.12, min=0.0, max=1.0, subtype='FACTOR', update=update_digital_noise_luma_cb)
    bpy.types.Object.fbp_digital_noise_chroma = FloatProperty(
        name="Chroma Noise", description="Colored sensor noise amount",
        default=0.08, min=0.0, max=1.0, subtype='FACTOR', update=update_digital_noise_chroma_cb)
    bpy.types.Object.fbp_digital_noise_scale = FloatProperty(
        name="Noise Scale", description="Size and frequency of the sensor noise",
        default=500.0, min=1.0, soft_max=3000.0, max=10000.0, precision=1, update=update_digital_noise_scale_cb)
    bpy.types.Object.fbp_digital_noise_shadow_bias = FloatProperty(
        name="Shadow Bias", description="Increase noise in darker image regions",
        default=0.65, min=0.0, max=2.0, update=update_digital_noise_shadow_bias_cb)
    bpy.types.Object.fbp_digital_noise_seed = FloatProperty(
        name="Animate (W)", description="Temporal noise phase; animate or enable Evolve for moving sensor noise",
        default=0.0, soft_min=-100.0, soft_max=100.0, precision=3, update=update_digital_noise_seed_cb)
    bpy.types.Object.fbp_chroma_key_color = FloatVectorProperty(
        name="Key Color", description="Color removed from the plane",
        subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 1.0, 0.0, 1.0), update=update_chroma_key_color_cb)
    bpy.types.Object.fbp_chroma_key_tolerance = FloatProperty(
        name="Tolerance", description="Distance from the key color that becomes transparent",
        default=0.20, min=0.0, soft_max=1.0, max=1.732, update=update_chroma_key_tolerance_cb)
    bpy.types.Object.fbp_chroma_key_softness = FloatProperty(
        name="Softness", description="Feather the key edge",
        default=0.08, min=0.0, max=1.0, subtype='FACTOR', update=update_chroma_key_softness_cb)
    bpy.types.Object.fbp_chroma_key_despill = FloatProperty(
        name="Despill", description="Desaturate key-color contamination near transparent edges",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_chroma_key_despill_cb)
    bpy.types.Object.fbp_chroma_key_invert = BoolProperty(
        name="Invert", description="Keep the selected key color and remove the rest",
        default=False, update=update_chroma_key_invert_cb)
    bpy.types.Object.fbp_halftone_scale = FloatProperty(
        name="Cell Scale", description="Number of halftone cells across the plane width",
        default=80.0, min=1.0, soft_max=500.0, max=2000.0, update=update_halftone_scale_cb)
    bpy.types.Object.fbp_halftone_dot_size = FloatProperty(
        name="Dot Size", default=0.9, min=0.0, soft_max=1.2, max=1.5, update=update_halftone_dot_size_cb)
    bpy.types.Object.fbp_halftone_rotation = FloatProperty(
        name="Rotation", subtype='ANGLE', default=0.0, soft_min=-3.141593, soft_max=3.141593, update=update_halftone_rotation_cb)
    bpy.types.Object.fbp_halftone_contrast = FloatProperty(
        name="Contrast", default=1.4, min=0.0, soft_max=4.0, max=8.0, update=update_halftone_contrast_cb)
    bpy.types.Object.fbp_halftone_invert = BoolProperty(
        name="Invert", default=False, update=update_halftone_invert_cb)
    bpy.types.Object.fbp_halftone_shape = EnumProperty(
        name="Shape", description="Shape used for the printed cells",
        items=(("CIRCLE", "Circle", "Circular dots"), ("SQUARE", "Square", "Square cells"),
               ("DIAMOND", "Diamond", "Diamond-shaped cells"), ("LINE", "Line", "Parallel print lines")),
        default="CIRCLE", update=update_halftone_shape_cb)
    bpy.types.Object.fbp_halftone_use_source_color = BoolProperty(
        name="Use Source Color", description="Use the source image as ink color",
        default=True, update=update_halftone_use_source_color_cb)
    bpy.types.Object.fbp_halftone_foreground = FloatVectorProperty(
        name="Ink Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_halftone_foreground_cb)
    bpy.types.Object.fbp_halftone_background = FloatVectorProperty(
        name="Paper Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0), update=update_halftone_background_cb)
    bpy.types.Object.fbp_halftone_transparent_background = BoolProperty(
        name="Transparent Background", description="Keep only the printed cells",
        default=False, update=update_halftone_transparent_background_cb)
    bpy.types.Object.fbp_dot_matrix_scale = FloatProperty(
        name="Cell Scale", description="Number of dot cells across the plane width",
        default=64.0, min=1.0, soft_max=500.0, max=2000.0, update=update_dot_matrix_scale_cb)
    bpy.types.Object.fbp_dot_matrix_dot_size = FloatProperty(
        name="Dot Size", default=0.85, min=0.0, soft_max=1.2, max=1.5, update=update_dot_matrix_dot_size_cb)
    bpy.types.Object.fbp_dot_matrix_spacing = FloatProperty(
        name="Spacing", description="Empty space between neighboring dots",
        default=0.10, min=0.0, max=0.95, subtype='FACTOR', update=update_dot_matrix_spacing_cb)
    bpy.types.Object.fbp_dot_matrix_contrast = FloatProperty(
        name="Contrast", description="Contrast used to derive dot radius and brightness from the source image",
        default=1.0, min=0.0, soft_max=4.0, max=8.0, update=update_dot_matrix_contrast_cb)
    bpy.types.Object.fbp_dot_matrix_response = FloatProperty(
        name="Brightness Response",
        description="Shape the luminance-to-size response: below 1 lifts dark regions, above 1 concentrates dots in highlights",
        default=1.0, min=0.1, soft_max=4.0, max=8.0, update=update_dot_matrix_response_cb)
    bpy.types.Object.fbp_dot_matrix_invert = BoolProperty(
        name="Invert", description="Invert source luminance before generating dot size and brightness",
        default=False, update=update_dot_matrix_invert_cb)
    bpy.types.Object.fbp_dot_matrix_random_size = FloatProperty(
        name="Random Size", description="Randomize dot radius per cell",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_dot_matrix_random_size_cb)
    bpy.types.Object.fbp_dot_matrix_random_brightness = FloatProperty(
        name="Random Brightness", description="Randomize the brightness of each dot",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_dot_matrix_random_brightness_cb)
    bpy.types.Object.fbp_dot_matrix_seed = FloatProperty(
        name="Pattern Seed", description="Deterministic dot variation; animate or enable Evolve",
        default=0.0, soft_min=-100000.0, soft_max=100000.0, precision=0, update=update_dot_matrix_seed_cb)
    bpy.types.Object.fbp_dot_matrix_glow = FloatProperty(
        name="Glow", description="Soft anti-aliased edge around each dot; set to zero for a hard edge",
        default=0.04, min=0.0, soft_max=0.2, max=0.5, update=update_dot_matrix_glow_cb)
    bpy.types.Object.fbp_dot_matrix_use_source_color = BoolProperty(
        name="Use Source Color", description="Color each dot using the source image",
        default=True, update=update_dot_matrix_use_source_color_cb)
    bpy.types.Object.fbp_dot_matrix_foreground = FloatVectorProperty(
        name="Dot Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 0.65, 0.15, 1.0), update=update_dot_matrix_foreground_cb)
    bpy.types.Object.fbp_dot_matrix_background = FloatVectorProperty(
        name="Background Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_dot_matrix_background_cb)
    bpy.types.Object.fbp_dot_matrix_transparent_background = BoolProperty(
        name="Transparent Background", description="Show only the dots and preserve transparent gaps",
        default=True, update=update_dot_matrix_transparent_background_cb)
    bpy.types.Object.fbp_dot_matrix_shape = EnumProperty(
        name="Shape", description="Shape of every matrix element",
        items=(("CIRCLE", "Circle", "Circular lights"), ("SQUARE", "Square", "Square lights"),
               ("DIAMOND", "Diamond", "Diamond lights"), ("LINE", "Line", "Horizontal light bars")),
        default="CIRCLE", update=update_dot_matrix_shape_cb)
    bpy.types.Object.fbp_dot_matrix_min_size = FloatProperty(
        name="Minimum Size", description="Minimum visible element size in dark regions",
        default=0.0, min=0.0, max=1.5, update=update_dot_matrix_min_size_cb)
    bpy.types.Object.fbp_dot_matrix_max_size = FloatProperty(
        name="Maximum Size", description="Maximum visible element size in bright regions",
        default=1.0, min=0.0, max=1.5, update=update_dot_matrix_max_size_cb)
    bpy.types.Object.fbp_dot_matrix_dead_pixels = FloatProperty(
        name="Dead Pixels", description="Random fraction of permanently disabled elements",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_dot_matrix_dead_pixels_cb)
    bpy.types.Object.fbp_dot_matrix_flicker = FloatProperty(
        name="Flicker", description="Random brightness variation driven by Seed and Evolve",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_dot_matrix_flicker_cb)

    bpy.types.Object.fbp_ascii_scale = FloatProperty(
        name="Cell Scale", description="Number of character cells across the plane width",
        default=48.0, min=1.0, soft_max=300.0, max=1000.0, update=update_ascii_scale_cb)
    bpy.types.Object.fbp_ascii_contrast = FloatProperty(
        name="Contrast", default=1.3, min=0.0, soft_max=4.0, max=8.0, update=update_ascii_contrast_cb)
    bpy.types.Object.fbp_ascii_invert = BoolProperty(name="Invert", default=False, update=update_ascii_invert_cb)
    bpy.types.Object.fbp_ascii_colorize = BoolProperty(
        name="Use Source Color", description="Color each glyph with the source image instead of Text Color",
        default=True, update=update_ascii_colorize_cb)
    bpy.types.Object.fbp_ascii_foreground = FloatVectorProperty(
        name="Text Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.1, 1.0, 0.2, 1.0), update=update_ascii_foreground_cb)
    bpy.types.Object.fbp_ascii_background = FloatVectorProperty(
        name="Background Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_ascii_background_cb)
    bpy.types.Object.fbp_ascii_transparent_background = BoolProperty(
        name="Transparent Background", description="Replace the source image with glyphs on transparent gaps",
        default=True, update=update_ascii_transparent_background_cb)
    bpy.types.Object.fbp_ascii_variation = FloatProperty(
        name="Character Variation", description="Vary neighboring glyph choices while preserving luminance",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_ascii_variation_cb)
    bpy.types.Object.fbp_ascii_random_seed = FloatProperty(
        name="Character Seed", description="Deterministic glyph variation; animate or enable Evolve",
        default=0.0, soft_min=-100000.0, soft_max=100000.0, precision=0, update=update_ascii_random_seed_cb)
    bpy.types.Object.fbp_ascii_charset = EnumProperty(
        name="Character Set", description="Character gradient used to map image luminance",
        items=ascii_enum_items(), default='CLASSIC', update=update_ascii_charset_cb)
    bpy.types.Object.fbp_ascii_character_count = IntProperty(
        name="Character Count", description="Number of luminance levels used from the selected character set",
        default=16, min=2, max=ASCII_ATLAS_COLUMNS, update=update_ascii_character_count_cb)
    bpy.types.Object.fbp_ascii_edge_boost = FloatProperty(
        name="Edge Boost", description="Emphasize image edges before choosing glyph density",
        default=0.0, min=0.0, max=2.0, update=update_ascii_edge_boost_cb)
    bpy.types.Object.fbp_ascii_dither = FloatProperty(
        name="Dither", description="Add ordered cell variation to preserve gradients",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_ascii_dither_cb)

    bpy.types.Object.fbp_text_matrix_columns = IntProperty(
        name="Columns (Legacy)", description="Legacy Text Matrix column value",
        default=24, min=2, soft_max=96, max=256, update=update_text_matrix_columns_cb)
    bpy.types.Object.fbp_text_matrix_quality = EnumProperty(
        name="Quality", description="Quick viewport/render column presets; rows return to Auto",
        items=(("DRAFT", "Draft", "24 viewport / 48 render columns"),
               ("PREVIEW", "Preview", "48 viewport / 96 render columns"),
               ("FINAL", "Final", "72 viewport / 160 render columns"),
               ("CUSTOM", "Custom", "Use the manual column values")),
        default="PREVIEW", update=update_text_matrix_quality_cb)
    bpy.types.Object.fbp_text_matrix_viewport_columns = IntProperty(
        name="Viewport Columns", description="Text columns used during viewport work",
        default=48, min=2, soft_max=96, max=256, update=update_text_matrix_viewport_columns_cb)
    bpy.types.Object.fbp_text_matrix_viewport_rows = IntProperty(
        name="Viewport Rows",
        description="Text rows used in the viewport; 0 derives rows automatically from plane and font aspect",
        default=0, min=0, soft_max=128, max=512, update=update_text_matrix_viewport_rows_cb)
    bpy.types.Object.fbp_text_matrix_render_columns = IntProperty(
        name="Render Columns", description="Text columns temporarily used for final rendering",
        default=96, min=2, soft_max=192, max=512, update=update_text_matrix_render_columns_cb)
    bpy.types.Object.fbp_text_matrix_render_rows = IntProperty(
        name="Render Rows",
        description="Text rows used for final rendering; 0 derives rows automatically from plane and font aspect",
        default=0, min=0, soft_max=256, max=512, update=update_text_matrix_render_rows_cb)
    bpy.types.Object.fbp_text_matrix_auto_playback_limit = BoolProperty(
        name="Limit During Playback",
        description="Temporarily lower Text Matrix grid density while timeline playback is running",
        default=True, update=update_text_matrix_auto_playback_limit_cb)
    bpy.types.Object.fbp_text_matrix_playback_columns = IntProperty(
        name="Playback Columns",
        description="Maximum Text Matrix columns used during timeline playback",
        default=24, min=2, soft_max=64, max=128, update=update_text_matrix_playback_columns_cb)
    bpy.types.Object.fbp_text_matrix_playback_rows = IntProperty(
        name="Playback Rows",
        description="Maximum explicit Text Matrix rows during playback; 0 keeps automatic rows",
        default=0, min=0, soft_max=64, max=128, update=update_text_matrix_playback_rows_cb)
    bpy.types.Object.fbp_text_matrix_character_count = IntProperty(
        name="Character Levels", description="Number of different glyph density levels",
        default=16, min=2, max=ASCII_TEXT_GLYPH_LIMIT, update=update_text_matrix_character_count_cb)
    bpy.types.Object.fbp_text_matrix_character_aspect = FloatProperty(
        name="Character Aspect", description="Width-to-height compensation for the selected font",
        default=0.60, min=0.1, max=2.0, update=update_text_matrix_character_aspect_cb)
    bpy.types.Object.fbp_text_matrix_glyph_scale = FloatProperty(
        name="Glyph Scale", description="Scale glyphs inside each text cell",
        default=0.88, min=0.05, max=2.0, update=update_text_matrix_glyph_scale_cb)
    bpy.types.Object.fbp_text_matrix_contrast = FloatProperty(
        name="Contrast", default=1.3, min=0.0, soft_max=4.0, max=8.0, update=update_text_matrix_contrast_cb)
    bpy.types.Object.fbp_text_matrix_invert = BoolProperty(
        name="Invert", default=False, update=update_text_matrix_invert_cb)
    bpy.types.Object.fbp_text_matrix_variation = FloatProperty(
        name="Character Variation", description="Randomly choose nearby glyphs while preserving luminance",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_text_matrix_variation_cb)
    bpy.types.Object.fbp_text_matrix_seed = FloatProperty(
        name="Character Seed", description="Deterministic glyph variation; animate or enable Evolve",
        default=0.0, soft_min=-100000.0, soft_max=100000.0, precision=0, update=update_text_matrix_seed_cb)
    bpy.types.Object.fbp_text_matrix_alpha_threshold = FloatProperty(
        name="Alpha Threshold", description="Discard cells at or below this alpha value; zero keeps every non-transparent cell and reads partial alpha as lighter luminance",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_text_matrix_alpha_threshold_cb)
    bpy.types.Object.fbp_text_matrix_transparent_background = BoolProperty(
        name="Transparent Background", description="Generate only text geometry without a background plane",
        default=True, update=update_text_matrix_transparent_background_cb)
    bpy.types.Object.fbp_text_matrix_realize = BoolProperty(
        name="Realize Text Geometry", description="Convert glyph instances to mesh only when a later modifier needs real geometry",
        default=False, update=update_text_matrix_realize_cb)
    bpy.types.Object.fbp_text_matrix_charset = EnumProperty(
        name="Character Set", description="Character gradient used to generate real text geometry",
        items=ascii_enum_items(include_custom=True), default='CLASSIC', update=update_text_matrix_charset_cb)
    bpy.types.Object.fbp_text_matrix_custom_charset = StringProperty(
        name="Characters", description="Custom glyphs ordered from lightest to darkest",
        default=" .:-=+*#%@", maxlen=256, update=update_text_matrix_custom_charset_cb)
    bpy.types.Object.fbp_text_matrix_font = PointerProperty(
        name="Font", description="Blender vector font used by Text Matrix",
        type=bpy.types.VectorFont, update=update_text_matrix_font_cb)
    bpy.types.Object.fbp_text_matrix_use_source_color = BoolProperty(
        name="Use Source Color",
        description="Color each vector glyph with the sampled source pixel instead of Text Color",
        default=True, update=update_text_matrix_use_source_color_cb)
    bpy.types.Object.fbp_text_matrix_text_color = FloatVectorProperty(
        name="Text Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.1, 1.0, 0.2, 1.0), update=update_text_matrix_text_color_cb)
    bpy.types.Object.fbp_text_matrix_background_color = FloatVectorProperty(
        name="Background Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_text_matrix_background_color_cb)
    bpy.types.Object.fbp_hue_saturation_hue = FloatProperty(name="Hue", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_hue_saturation_hue_cb)
    bpy.types.Object.fbp_hue_saturation_saturation = FloatProperty(name="Saturation", default=1.0, min=0.0, soft_max=2.0, update=update_hue_saturation_saturation_cb)
    bpy.types.Object.fbp_hue_saturation_value = FloatProperty(name="Value", default=1.0, min=0.0, soft_max=2.0, update=update_hue_saturation_value_cb)
    bpy.types.Object.fbp_brightness_contrast_brightness = FloatProperty(name="Brightness", default=0.0, soft_min=-1.0, soft_max=1.0, update=update_brightness_contrast_brightness_cb)
    bpy.types.Object.fbp_brightness_contrast_contrast = FloatProperty(name="Contrast", default=0.0, soft_min=-1.0, soft_max=1.0, update=update_brightness_contrast_contrast_cb)
    bpy.types.Object.fbp_invert_factor = FloatProperty(name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_invert_factor_cb)
    bpy.types.Object.fbp_threshold_value = FloatProperty(name="Threshold", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_threshold_value_cb)
    bpy.types.Object.fbp_posterize_steps = FloatProperty(
        name="Color Steps", default=4.0, min=2.0, soft_max=64.0, precision=0, update=update_posterize_steps_cb)
    bpy.types.Object.fbp_solid_mask_color = FloatVectorProperty(
        name="Mask Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.0, 1.0), update=update_solid_mask_color_cb)
    bpy.types.Object.fbp_solid_mask_factor = FloatProperty(
        name="Mask Factor", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_solid_mask_factor_cb)
    bpy.types.Object.fbp_color_isolate_target = FloatVectorProperty(name="Target Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.0, 0.0, 1.0), update=update_color_isolate_target_cb)
    bpy.types.Object.fbp_color_isolate_tolerance = FloatProperty(name="Tolerance", default=0.15, min=0.0, max=1.0, subtype='FACTOR', update=update_color_isolate_tolerance_cb)
    bpy.types.Object.fbp_color_isolate_falloff = FloatProperty(name="Falloff", default=0.1, min=0.0, max=1.0, subtype='FACTOR', update=update_color_isolate_falloff_cb)
    bpy.types.Object.fbp_duotone_shadows = FloatVectorProperty(name="Shadows Tone", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.2, 1.0), update=update_duotone_shadows_cb)
    bpy.types.Object.fbp_duotone_highlights = FloatVectorProperty(name="Highlights Tone", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.8, 0.6, 1.0), update=update_duotone_highlights_cb)
    bpy.types.Object.fbp_paper_fiber_scale = FloatProperty(name="Fiber Scale", default=140.0, min=0.01, soft_max=3000.0, precision=1, update=update_paper_fiber_scale_cb)
    bpy.types.Object.fbp_paper_fiber_intensity = FloatProperty(name="Intensity", default=0.40, min=0.0, max=1.0, subtype='FACTOR', update=update_paper_fiber_intensity_cb)
    bpy.types.Object.fbp_paper_fiber_phase = FloatProperty(name="Animate (W)", default=0.0, soft_min=-100.0, soft_max=100.0, precision=3, update=update_paper_fiber_phase_cb)
    bpy.types.Object.fbp_gradient_light_angle = FloatProperty(name="Light Angle", default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_gradient_light_angle_cb)
    bpy.types.Object.fbp_gradient_shadow_position = FloatProperty(name="Shadow Position", default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_gradient_shadow_position_cb)
    bpy.types.Object.fbp_gradient_softness = FloatProperty(name="Softness", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_gradient_softness_cb)
    bpy.types.Object.fbp_gradient_shadow_color = FloatVectorProperty(name="Shadow Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.05, 1.0), update=update_gradient_shadow_color_cb)
    bpy.types.Object.fbp_gobo_pattern_scale = FloatProperty(name="Pattern Scale", default=10.0, min=0.001, soft_max=100.0, precision=3, update=update_gobo_pattern_scale_cb)
    bpy.types.Object.fbp_gobo_rotation = FloatProperty(name="Rotation Angle", default=0.5, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_gobo_rotation_cb)
    bpy.types.Object.fbp_gobo_sharpness = FloatProperty(name="Sharpness", default=0.8, min=0.0, max=1.0, subtype='FACTOR', update=update_gobo_sharpness_cb)
    bpy.types.Object.fbp_crt_line_count = FloatProperty(name="Line Count", default=200.0, min=1.0, soft_max=2000.0, precision=0, update=update_crt_line_count_cb)
    bpy.types.Object.fbp_crt_opacity = FloatProperty(name="Opacity", default=0.15, min=0.0, max=1.0, subtype='FACTOR', update=update_crt_opacity_cb)
    bpy.types.Object.fbp_vignette_radius = FloatProperty(name="Radius", default=0.5, min=0.0, soft_max=2.0, precision=3, update=update_vignette_radius_cb)
    bpy.types.Object.fbp_vignette_smoothness = FloatProperty(name="Smoothness", default=0.2, min=0.0, max=1.0, subtype='FACTOR', update=update_vignette_smoothness_cb)
    bpy.types.Object.fbp_vignette_strength = FloatProperty(name="Strength", default=0.8, min=0.0, max=1.0, subtype='FACTOR', update=update_vignette_strength_cb)

    _register_effect_animation_properties()


# SECTION 03 - Unregister properties #
def unregister_properties():
    _unregister_effect_animation_properties()
    for attr in ['fbp_last_directory', 'fbp_project_path', 'fbp_parent_import_path', 'fbp_cam_ratio', 'fbp_camera_projection', 'fbp_camera_lens', 'fbp_camera_ortho_scale', 'fbp_camera_clip_start', 'fbp_camera_clip_end', 'fbp_show_previews', 'fbp_show_color_previews', 'fbp_sort_layers_alpha', 'fbp_auto_clean_orphans', 'fbp_show_create_tools', 'fbp_render_output_dir', 'fbp_render_prefix', 'fbp_background_render_running', 'fbp_background_render_status', 'fbp_background_render_progress', 'fbp_background_render_total', 'fbp_background_render_output_dir', 'fbp_generation_rename_items', 'fbp_generation_rename_index', 'fbp_auto_collection_color_variants', 'fbp_layers', 'fbp_layer_stack_index', 'fbp_layer_tree_rows', 'fbp_layer_tree_rows_idx', 'fbp_layer_tree_signature', 'fbp_pending_open_collections', 'fbp_gradient_preview_material_name', 'fbp_creation_mode', 'fbp_effects_view', 'fbp_pending_planes', 'fbp_pending_planes_idx', 'fbp_pending_tree_rows', 'fbp_pending_tree_rows_idx', 'fbp_pending_collection_name', 'fbp_pre_duration', 'fbp_pre_shadeless', 'fbp_pre_loop_mode', 'fbp_pre_interpolation', 'fbp_pre_orientation', 'fbp_gen_camera', 'fbp_cam_pivot', 'fbp_layer_offset', 'fbp_auto_scale', 'fbp_pre_track_cam', 'fbp_settings_primary_open', 'fbp_settings_secondary_open', 'fbp_settings_section', 'fbp_show_project_tools', 'fbp_color_plane_type', 'fbp_color_plane_color', 'fbp_color_plane_preset', 'fbp_color_plane_emission', 'fbp_gradient_mode', 'fbp_gradient_kind', 'fbp_gradient_color_a', 'fbp_gradient_color_b', 'fbp_gradient_reverse', 'fbp_gradient_offset_x', 'fbp_gradient_offset_y', 'fbp_gradient_scale_x', 'fbp_gradient_scale_y', 'fbp_gradient_rotation', 'fbp_show_gradient_ramp', 'fbp_show_gradient_transform']:
        if hasattr(bpy.types.Scene, attr):
            try:
                delattr(bpy.types.Scene, attr)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
    for attr in ['is_fbp_collection', 'fbp_collapsed', 'fbp_collection_selected', 'fbp_collection_solo', 'fbp_collection_locked', 'fbp_collection_plane_locked', 'fbp_collection_visible', 'fbp_collection_holdout']:
        if hasattr(bpy.types.Collection, attr):
            try:
                delattr(bpy.types.Collection, attr)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
    for attr in ['is_fbp_control', 'is_fbp_plane', 'fbp_collection_name', 'fbp_follow_collection_color', 'fbp_color_variant_index', 'fbp_base_scale_vec', 'fbp_preview_path', 'fbp_is_vertical', 'fbp_images', 'fbp_images_index', 'fbp_color_tag', 'fbp_depth_order', 'fbp_loop_mode', 'fbp_use_emission', 'fbp_interpolation', 'fbp_plane_target', 'fbp_global_duration', 'fbp_start_frame', 'fbp_opacity', 'fbp_track_cam', 'fbp_is_visible', 'fbp_is_color_plane', 'fbp_color_plane_mode', 'fbp_color_plane_color', 'fbp_color_plane_emission', 'fbp_gradient_mode', 'fbp_gradient_kind', 'fbp_gradient_color_a', 'fbp_gradient_color_b', 'fbp_gradient_reverse', 'fbp_gradient_offset_x', 'fbp_gradient_offset_y', 'fbp_gradient_scale_x', 'fbp_gradient_scale_y', 'fbp_gradient_rotation', 'fbp_show_gradient_ramp', 'fbp_show_gradient_transform', 'fbp_extend_mode', 'fbp_extend_left', 'fbp_extend_right', 'fbp_extend_top', 'fbp_extend_bottom', 'fbp_crop_left', 'fbp_crop_right', 'fbp_crop_top', 'fbp_crop_bottom', 'fbp_effects', 'fbp_effects_index', 'fbp_effects_signature', 'fbp_mesh_wiggle_enabled', 'fbp_mesh_wiggle_shade_smooth', 'fbp_mesh_wiggle_strength', 'fbp_mesh_wiggle_speed', 'fbp_mesh_wiggle_hold', 'fbp_mesh_wiggle_w', 'fbp_mesh_wiggle_seed', 'fbp_mesh_wiggle_unique_seed', 'fbp_mesh_wiggle_layer_seed', 'fbp_mesh_wiggle_noise_scale', 'fbp_mesh_wiggle_detail', 'fbp_mesh_wiggle_subdivisions', 'fbp_uv_distortion_scale', 'fbp_uv_distortion_amount', 'fbp_pixelate_resolution', 'fbp_pixelate_square_pixels', 'fbp_grain_strength', 'fbp_grain_scale', 'fbp_grain_seed', 'fbp_digital_noise_luma', 'fbp_digital_noise_chroma', 'fbp_digital_noise_scale', 'fbp_digital_noise_shadow_bias', 'fbp_digital_noise_seed', 'fbp_chroma_key_color', 'fbp_chroma_key_tolerance', 'fbp_chroma_key_softness', 'fbp_chroma_key_despill', 'fbp_chroma_key_invert', 'fbp_halftone_scale', 'fbp_halftone_dot_size', 'fbp_halftone_rotation', 'fbp_halftone_contrast', 'fbp_halftone_invert', 'fbp_dot_matrix_scale', 'fbp_dot_matrix_dot_size', 'fbp_dot_matrix_spacing', 'fbp_dot_matrix_contrast', 'fbp_dot_matrix_response', 'fbp_dot_matrix_invert', 'fbp_dot_matrix_random_size', 'fbp_dot_matrix_random_brightness', 'fbp_dot_matrix_seed', 'fbp_dot_matrix_glow', 'fbp_dot_matrix_use_source_color', 'fbp_dot_matrix_foreground', 'fbp_dot_matrix_background', 'fbp_dot_matrix_transparent_background', 'fbp_ascii_scale', 'fbp_ascii_contrast', 'fbp_ascii_invert', 'fbp_ascii_colorize', 'fbp_ascii_foreground', 'fbp_ascii_background', 'fbp_ascii_transparent_background', 'fbp_ascii_variation', 'fbp_ascii_random_seed', 'fbp_ascii_seed', 'fbp_ascii_charset', 'fbp_ascii_character_count', 'fbp_text_matrix_columns', 'fbp_text_matrix_character_count', 'fbp_text_matrix_character_aspect', 'fbp_text_matrix_glyph_scale', 'fbp_text_matrix_contrast', 'fbp_text_matrix_invert', 'fbp_text_matrix_variation', 'fbp_text_matrix_seed', 'fbp_text_matrix_alpha_threshold', 'fbp_text_matrix_transparent_background', 'fbp_text_matrix_realize', 'fbp_text_matrix_charset', 'fbp_text_matrix_custom_charset', 'fbp_text_matrix_font', 'fbp_text_matrix_use_source_color', 'fbp_text_matrix_text_color', 'fbp_text_matrix_background_color', 'fbp_text_matrix_quality', 'fbp_text_matrix_viewport_columns', 'fbp_text_matrix_viewport_rows', 'fbp_text_matrix_render_columns', 'fbp_text_matrix_render_rows', 'fbp_text_matrix_auto_playback_limit', 'fbp_text_matrix_playback_columns', 'fbp_text_matrix_playback_rows', 'fbp_ascii_edge_boost', 'fbp_ascii_dither', 'fbp_dot_matrix_shape', 'fbp_dot_matrix_min_size', 'fbp_dot_matrix_max_size', 'fbp_dot_matrix_dead_pixels', 'fbp_dot_matrix_flicker', 'fbp_halftone_shape', 'fbp_halftone_use_source_color', 'fbp_halftone_foreground', 'fbp_halftone_background', 'fbp_halftone_transparent_background', 'fbp_wind_falloff', 'fbp_wind_noise_scale', 'fbp_wind_gust_strength', 'fbp_wind_direction_space', 'fbp_wind_direction', 'fbp_wind_preview_falloff', 'fbp_posterize_steps', 'fbp_solid_mask_color', 'fbp_solid_mask_factor', 'fbp_stop_motion_resolution', 'fbp_stop_motion_strength', 'fbp_stop_motion_step_frames', 'fbp_wind_bend_amount', 'fbp_wind_speed', 'fbp_wind_pin_edge', 'fbp_wind_motion_mode', 'fbp_wind_wave_count', 'fbp_wind_wave_amplitude', 'fbp_wind_wave_speed', 'fbp_wind_phase', 'fbp_wind_turbulence', 'fbp_wind_reverse', 'fbp_felt_render_density', 'fbp_felt_viewport_percentage', 'fbp_felt_fuzz_length', 'fbp_felt_subdivisions', 'fbp_felt_curl_amount', 'fbp_felt_alpha_threshold', 'fbp_felt_alpha_resolution', 'fbp_color_isolate_target', 'fbp_color_isolate_tolerance', 'fbp_color_isolate_falloff', 'fbp_duotone_shadows', 'fbp_duotone_highlights', 'fbp_paper_fiber_scale', 'fbp_paper_fiber_intensity', 'fbp_gradient_light_angle', 'fbp_gradient_shadow_position', 'fbp_gradient_softness', 'fbp_gradient_shadow_color', 'fbp_gobo_pattern_scale', 'fbp_gobo_rotation', 'fbp_gobo_sharpness', 'fbp_crt_line_count', 'fbp_crt_opacity', 'fbp_vignette_radius', 'fbp_vignette_smoothness', 'fbp_vignette_strength', 'fbp_wind_subdivision', 'fbp_wind_stepped', 'fbp_thickness_amount', 'fbp_thickness_side_material', 'fbp_thickness_side_color', 'fbp_thickness_alpha_threshold', 'fbp_thickness_alpha_resolution', 'fbp_infinite_rotation_speed', 'fbp_infinite_rotation_direction', 'fbp_infinite_rotation_stepped', 'fbp_infinite_rotation_offset', 'fbp_felt_fuzz_radius', 'fbp_felt_seed', 'fbp_hue_saturation_hue', 'fbp_hue_saturation_saturation', 'fbp_hue_saturation_value', 'fbp_brightness_contrast_brightness', 'fbp_brightness_contrast_contrast', 'fbp_invert_factor', 'fbp_threshold_value', 'fbp_paper_fiber_phase']:
        if hasattr(bpy.types.Object, attr):
            try:
                delattr(bpy.types.Object, attr)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass


# SECTION 04 - Registerable classes #
property_classes = (
    FBP_AddonPreferences,
    FBP_LayerItem,
    FBP_EffectItem,
    FBP_LayerTreeRowItem,
    FBP_ImageItem,
    FBP_PendingPlaneItem,
    FBP_PendingTreeRowItem,
    FBP_GenerationRenameItem,
)


def register():
    for cls in property_classes:
        bpy.utils.register_class(cls)
    register_properties()
    # Preserve settings stored in existing .blend files. Only an unsaved startup
    # scene receives the user defaults immediately; newly created scenes are
    # initialized later by the scene-switch handler.
    try:
        if bpy.data.is_saved:
            fbp_mark_scenes_preferences_initialized()
        else:
            active_scene = getattr(bpy.context, "scene", None)
            if active_scene:
                fbp_apply_preferences_to_scene(active_scene, force=False, context=bpy.context)
            for scene in bpy.data.scenes:
                if scene != active_scene:
                    try:
                        scene[_PREFERENCES_SCENE_MARKER] = True
                    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                        pass
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def unregister():
    unregister_properties()
    for cls in reversed(property_classes):
        try:
            bpy.utils.unregister_class(cls)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
