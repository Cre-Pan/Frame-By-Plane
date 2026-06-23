"""Scene, Object, Collection and add-on preference properties."""

import bpy
from types import SimpleNamespace
from bpy.props import (
    StringProperty, IntProperty, BoolProperty, FloatProperty, FloatVectorProperty,
    CollectionProperty, PointerProperty, EnumProperty
)
from bpy.types import PropertyGroup, AddonPreferences

from .constants import COLOR_ENUM_ITEMS, COLLECTION_COLOR_ENUM_ITEMS, fbp_icon
from .matrix_presets import ASCII_ATLAS_COLUMNS, ASCII_TEXT_GLYPH_LIMIT, ascii_enum_items

from .storage_keys import fbp_effect_storage_key
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_undo_guard_active,
    fbp_set_rna_property_silent,
    fbp_warn,
    fbp_obj_runtime_token,
    fbp_obj_matches_runtime_token,
)


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


ALPHA_RENDER_METHOD_ITEMS = [
    ('AUTO', "Auto — Blended", "Use smooth Blended transparency when alpha is needed and Opaque for fully opaque materials", fbp_icon("IMAGE_ALPHA"), 0),
    ('DITHERED', "Dithered", "Use Dithered alpha rendering for transparent Frame By Plane materials. Recommended for Eevee depth of field, motion blur and depth passes", fbp_icon("ANTIALIASED"), 1),
    ('BLENDED', "Blended", "Use smooth blended transparency. This can produce incomplete depth information in Eevee and may limit depth of field", fbp_icon("IMAGE_ALPHA"), 2),
    ('OPAQUE', "Opaque", "Ignore material alpha at the surface-render level. Fast and depth-safe, but transparent pixels render as opaque", fbp_icon("MATERIAL"), 3),
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
    # Keep the legacy SINGLE / MULTI / COLOR identifiers so existing .blend
    # files and saved add-on preferences remain valid after the UI redesign.
    ('SINGLE', "Image Plane", "Create one Frame By Plane rig from a still image, numbered image sequence or supported video. Animated media uses Blender native image timing and remains linked to disk.", fbp_icon("IMAGE_DATA"), 0),
    ('MULTI', "Multiplane", "Open Multiplane Setup to organize multiple stills, sequences, videos and folder collections before generating depth-spaced layers for parallax animation.", fbp_icon("RENDERLAYERS"), 1),
    ('CUTOUT', "Cutout Plane", "Create one lightweight Cutout Plane whose ordered drawing library can be switched or keyframed for mouths, poses, expressions and replacement animation.", fbp_icon("OUTLINER_OB_ARMATURE"), 2),
    ('COLOR', "Color Plane", "Create a camera-ratio procedural plane with an editable solid RGBA color, optional emission shading and no external image dependency.", fbp_icon("IMAGE"), 3),
    ('GRADIENT', "Gradient Plane", "Create a camera-ratio plane with an editable linear or radial ColorRamp, alpha mode and local mapping controls.", fbp_icon("NODE_TEXTURE"), 4),
    ('HOLDOUT', "Holdout Plane", "Create an alpha-aware Holdout Plane for masking and compositing while preserving Frame By Plane layer controls and camera fitting.", fbp_icon("GHOST_DISABLED"), 5),
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


def get_fbp_layer_name(self):
    """Expose the live Object name through a rename-safe UI property."""
    try:
        return str(getattr(self, "name", "") or "")
    except FBP_DATA_ERRORS:
        return ""


def set_fbp_layer_name(self, value):
    """Rename an FBP rig and retarget its runtime UI references immediately."""
    if fbp_undo_guard_active():
        return
    requested = str(value or "").strip()
    if not requested:
        return
    try:
        current_name = str(getattr(self, "name", "") or "")
    except FBP_DATA_ERRORS:
        return
    if requested == current_name:
        return
    try:
        if bool(getattr(self, "is_fbp_control", False)):
            from .scene_sync import fbp_rename_layer_rig
            fbp_rename_layer_rig(self, requested, getattr(bpy, "context", None))
        else:
            self.name = requested
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not rename Frame by Plane layer", exc)


def update_show_previews_cb(self, context):
    """Release optional list-thumbnail previews when no Scene still needs them."""
    if bool(getattr(self, "fbp_show_previews", False)):
        return
    try:
        for scene in getattr(bpy.data, "scenes", ()):
            if scene is not self and bool(getattr(scene, "fbp_show_previews", False)):
                return
        _fbp_layers_func("clear_previews")()
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Could not clear Frame by Plane thumbnail previews", exc)


def update_collection_color_variants_cb(self, context):
    """Apply the current variant mode immediately to this Scene's layers."""
    if self is None:
        return
    target_context = context
    try:
        if not target_context or getattr(target_context, "scene", None) is not self:
            target_context = SimpleNamespace(scene=self)
    except FBP_DATA_ERRORS:
        target_context = SimpleNamespace(scene=self)
    _call_layers("sync_collection_colors_to_rigs", target_context)



def update_effects_view_cb(self, context):
    """Select the first visible effect when switching between the Image, Mask and Mesh stacks."""
    try:
        from .layers import get_selected_rigs
        from .effects_registry import fbp_effect_definition
        from .geometry_nodes import fbp_sync_effect_items

        rigs = get_selected_rigs(context)
        if not rigs:
            return
        rig = rigs[0]
        # Switching the Image/Mask/Mesh view only changes the transient UI mirror. Asset
        # repair is reserved for effect operators and diagnostics, avoiding a
        # full modifier/material validation every time the tab is clicked.
        fbp_sync_effect_items(
            rig, rigs, repair_assets=False, normalize_instance_ids=False
        )
        view = str(self.fbp_effects_view or '2D')
        visible_categories = ({'3D'} if view == '3D' else ({'MASK'} if view == 'MASK' else {'BASE', '2D'}))
        for index, item in enumerate(getattr(rig, "fbp_effects", ())):
            definition = fbp_effect_definition(getattr(item, "effect_id", ""))
            if str(definition.get("category", "2D") or "2D") in visible_categories:
                rig.fbp_effects_index = index
                break
        else:
            # The SKIP_SAVE index property has min=0. Keep it valid when the
            # selected effect view has no compatible effects; the panel draws an
            # explicit empty state instead of relying on a negative index.
            rig.fbp_effects_index = 0
    except (AttributeError, ImportError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


# SECTION 00C - Add-on Preferences #

def update_alpha_render_method_cb(self, context):
    # Refresh owned FBP material render methods after the Scene setting changes.
    if fbp_undo_guard_active():
        return
    try:
        from .materials import fbp_refresh_material_render_methods
        scene = getattr(context, 'scene', None) if context else self
        fbp_refresh_material_render_methods(scene)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not refresh Frame By Plane alpha rendering", exc)


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
    default_creation_mode: EnumProperty(description="Creation mode selected by default in new scenes when Frame By Plane initializes its Create panel.",
        name="Default Creation Mode",
        items=CREATION_MODE_ITEMS,
        default='SINGLE',
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
    default_playback: EnumProperty(description="Playback behavior assigned by default to newly imported animated planes: One Shot, Loop or Ping-Pong.", name="Default Playback", items=PLAYBACK_ITEMS, default='NONE')
    default_interpolation: EnumProperty(description="Texture filtering assigned by default to new image layers. Pixel preserves hard edges; Smooth uses linear interpolation.", name="Default Image Filter", items=INTERPOLATION_ITEMS, default='Closest')
    default_emission: BoolProperty(
        name="Emission Textures",
        description="Use lightweight shadeless materials for newly imported image layers",
        default=True,
    )
    default_orientation: EnumProperty(description="Default orientation of newly generated planes: vertical artwork facing the camera or horizontal planes parallel to the ground.", name="Default Plane Orientation", items=ORIENTATION_ITEMS, default='VERT')
    default_layer_offset: FloatProperty(
        name="Default Plane Distance",
        description="Default world-space distance inserted between consecutive layers generated by Multiplane Setup. Larger values create stronger parallax and require more camera depth.",
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
    default_camera_projection: EnumProperty(description="Projection used by newly generated cameras: perspective with a lens value or orthographic with a view scale.",
        name="Default Camera Projection",
        items=CAMERA_PROJECTION_ITEMS,
        default='PERSP',
    )
    default_camera_ratio: EnumProperty(description="Output aspect-ratio preset applied to newly initialized scenes and generated camera setups.", name="Default Aspect Ratio", items=CAMERA_RATIO_ITEMS, default='4_3')
    default_resolution_x: IntProperty(description="Custom horizontal render resolution used when the default aspect-ratio preset is set to Custom.", name="Custom Resolution X", default=1920, min=1, max=65536)
    default_resolution_y: IntProperty(description="Custom vertical render resolution used when the default aspect-ratio preset is set to Custom.", name="Custom Resolution Y", default=1440, min=1, max=65536)
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
        name="Show List Thumbnails",
        description="Show thumbnails inside layer, frame and Cutout library lists; the large active Cutout preview always remains visible",
        default=False,
    )
    default_show_color_previews: BoolProperty(
        name="Show Color Previews",
        description="Show procedural color and gradient previews in UI lists",
        default=True,
    )
    default_sort_layers_alpha: BoolProperty(
        name="Sort Layers Alphabetically",
        description="Sort Layer Tree rows alphabetically in newly initialized scenes instead of following scene and collection order. This changes UI ordering only.",
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
    default_alpha_render_method: EnumProperty(
        name="Default Alpha Rendering",
        description="Surface transparency method assigned to Frame By Plane materials. Auto uses Blended when alpha is needed and Opaque otherwise",
        items=ALPHA_RENDER_METHOD_ITEMS,
        default='AUTO',
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
    default_color_plane_type: EnumProperty(description="Procedural plane type selected by default when creating a Color, Gradient or Holdout plane.",
        name="Default Procedural Plane", items=COLOR_PLANE_TYPE_ITEMS, default='CUSTOM',
    )
    default_color_plane_preset: EnumProperty(description="Color preset assigned to new solid Color Planes. Custom uses the editable default color below.",
        name="Default Color Preset", items=COLOR_PLANE_PRESET_ITEMS, default='CUSTOM',
    )
    default_color_plane_color: FloatVectorProperty(description="RGBA color used for new Color Planes when the default preset is Custom.",
        name="Default Custom Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
    )
    default_color_plane_emission: BoolProperty(
        name="Color Plane Emission",
        description="Use emission materials for newly created Color and Gradient planes",
        default=True,
    )
    default_gradient_mode: EnumProperty(description="Default gradient shape for newly created Gradient Planes: linear across the plane or radial from the center.", name="Default Gradient Shape", items=GRADIENT_MODE_ITEMS, default='LINEAR')
    default_gradient_kind: EnumProperty(description="Default gradient alpha behavior: fully opaque color-to-color or transparent-to-visible.", name="Default Gradient Type", items=GRADIENT_KIND_ITEMS, default='COLOR')
    default_gradient_color_a: FloatVectorProperty(description="First endpoint color used by newly created procedural Gradient Planes.",
        name="Default Gradient From", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 0.3686274509803922, 0.596078431372549, 1.0),
    )
    default_gradient_color_b: FloatVectorProperty(description="Second endpoint color used by newly created procedural Gradient Planes.",
        name="Default Gradient To", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0),
    )
    default_gradient_reverse: BoolProperty(description="Swap the first and second endpoints of newly created Gradient Planes.", name="Reverse Gradient", default=True)
    default_gradient_offset_x: FloatProperty(description="Default horizontal offset applied to the procedural gradient mapping on new Gradient Planes.", name="Gradient X Offset", default=0.0, soft_min=-2.0, soft_max=2.0)
    default_gradient_offset_y: FloatProperty(description="Default vertical offset applied to the procedural gradient mapping on new Gradient Planes.", name="Gradient Y Offset", default=0.0, soft_min=-2.0, soft_max=2.0)
    default_gradient_scale_x: FloatProperty(description="Default horizontal scale of the procedural gradient mapping on new Gradient Planes.", name="Gradient Scale X", default=1.0, min=0.001, soft_max=10.0)
    default_gradient_scale_y: FloatProperty(description="Default vertical scale of the procedural gradient mapping on new Gradient Planes.", name="Gradient Scale Y", default=1.0, min=0.001, soft_max=10.0)
    default_gradient_rotation: FloatProperty(description="Default rotation in degrees applied to the gradient mapping on new Gradient Planes.", name="Gradient Rotation", default=0.0, soft_min=-180.0, soft_max=180.0)

    pie_quick_effect_1: StringProperty(
        name="Pie Quick Effect 1",
        description="First effect shown in the Frame By Plane viewport Pie Menu quick-effects popup",
        default="",
        options={'HIDDEN'},
    )
    pie_quick_effect_2: StringProperty(
        name="Pie Quick Effect 2",
        description="Second effect shown in the Frame By Plane viewport Pie Menu quick-effects popup",
        default="",
        options={'HIDDEN'},
    )
    pie_quick_effect_3: StringProperty(
        name="Pie Quick Effect 3",
        description="Third effect shown in the Frame By Plane viewport Pie Menu quick-effects popup",
        default="",
        options={'HIDDEN'},
    )
    pie_quick_effect_4: StringProperty(
        name="Pie Quick Effect 4",
        description="Fourth effect shown in the Frame By Plane viewport Pie Menu quick-effects popup",
        default="",
        options={'HIDDEN'},
    )
    pie_quick_effect_5: StringProperty(
        name="Pie Quick Effect 5",
        description="Fifth effect shown in the Frame By Plane viewport Pie Menu quick-effects popup",
        default="",
        options={'HIDDEN'},
    )

    review_reminders_enabled: BoolProperty(
        name="Show Friendly Review Reminders",
        description="Allow Frame By Plane to show an occasional optional review reminder only after real use. No telemetry or project data is collected",
        default=True,
    )
    review_install_time: FloatProperty(name="Review Install Time", default=0.0, options={'HIDDEN'})
    review_successful_operations: IntProperty(name="Successful Operations", default=0, min=0, options={'HIDDEN'})
    review_multiplane_completed: BoolProperty(name="Completed Multiplane", default=False, options={'HIDDEN'})
    review_campaign_version: StringProperty(name="Review Campaign", default="", options={'HIDDEN'})
    review_completed_version: StringProperty(name="Completed Review Campaign", default="", options={'HIDDEN'})
    review_snooze_until: FloatProperty(name="Review Snooze Time", default=0.0, options={'HIDDEN'})
    review_snooze_operation_target: IntProperty(name="Review Snooze Operations", default=0, min=0, options={'HIDDEN'})
    review_prompt_count: IntProperty(name="Review Prompt Count", default=0, min=0, options={'HIDDEN'})
    review_last_prompt_time: FloatProperty(name="Last Review Prompt", default=0.0, options={'HIDDEN'})

    def draw(self, context):
        layout = self.layout

        release = layout.box()
        release.label(text="Frame By Plane 5.8.4", icon='CHECKMARK')
        release.label(text="Viewport Pie Menu layout, universal object controls and quick effects")

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
        row.prop(self, "default_emission")
        row.prop(self, "default_orientation")
        row = sequence.row(align=True)
        row.prop(self, "default_layer_offset")
        row.prop(self, "default_fit_to_camera")
        sequence.prop(self, "default_track_camera")

        camera = layout.box()
        camera.label(text="Camera Defaults", icon='VIEW_CAMERA_UNSELECTED')
        row = camera.row(align=True)
        row.prop(self, "default_generate_camera")
        row.prop(self, "default_camera_pivot")
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
        display.label(text="Interface Defaults for New Scenes", icon='PREFERENCES')
        row = display.row(align=True)
        row.prop(self, "default_show_previews")
        row.prop(self, "default_show_color_previews")
        row = display.row(align=True)
        row.prop(self, "default_sort_layers_alpha")
        row.prop(self, "default_show_project_tools")
        row = display.row(align=True)
        row.prop(self, "default_show_gradient_ramp")
        row.prop(self, "default_show_gradient_transform")
        display.prop(self, "default_color_variants")

        maintenance = layout.box()
        maintenance.label(text="Maintenance Default for New Scenes", icon='MODIFIER')
        maintenance.prop(self, "default_auto_clean_orphans")

        render = layout.box()
        render.label(text="Render and Alpha Defaults", icon='RENDER_ANIMATION')
        render.prop(self, "default_alpha_render_method")
        render.prop(self, "default_render_output_dir")
        render.prop(self, "default_render_prefix")

        procedural = layout.box()
        procedural.label(text="Procedural Plane Defaults", icon='MATERIAL')
        procedural.prop(self, "default_color_plane_type")
        procedural.prop(self, "default_color_plane_preset")
        if self.default_color_plane_preset == 'CUSTOM':
            procedural.prop(self, "default_color_plane_color")
        procedural.prop(self, "default_color_plane_emission")
        row = procedural.row(align=True)
        row.prop(self, "default_gradient_mode")
        row.prop(self, "default_gradient_kind")
        row = procedural.row(align=True)
        row.prop(self, "default_gradient_color_a")
        row.prop(self, "default_gradient_color_b")
        procedural.prop(self, "default_gradient_reverse")
        transform = procedural.column(align=True)
        row = transform.row(align=True)
        row.prop(self, "default_gradient_offset_x")
        row.prop(self, "default_gradient_offset_y")
        row = transform.row(align=True)
        row.prop(self, "default_gradient_scale_x")
        row.prop(self, "default_gradient_scale_y")
        transform.prop(self, "default_gradient_rotation")

        feedback = layout.box()
        feedback.label(text="Feedback and Reviews", icon='INFO')
        feedback.prop(self, "review_reminders_enabled")
        info = feedback.column(align=True)
        info.enabled = False
        info.label(text="Shown only after real use — never at Blender startup.")
        info.label(text="No telemetry, project data or automatic messages are sent.")
        row = feedback.row(align=True)
        row.operator("fbp.open_review_page", text="Review Page :)", icon='CHECKMARK')
        row.operator("fbp.open_support_page", text="Support", icon='URL')

        layout.separator()
        row = layout.row()
        row.scale_y = 1.2
        row.operator("fbp.apply_preferences_to_scene", icon='CHECKMARK', text="Apply Defaults to Current Scene")


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
        except FBP_DATA_ERRORS:
            pass
    try:
        for key, addon in addons.items():
            if str(key).endswith(".frame_by_plane") or str(key) == "frame_by_plane":
                prefs = getattr(addon, "preferences", None)
                if prefs:
                    return prefs
    except FBP_DATA_ERRORS:
        pass
    return None


def fbp_apply_preferences_to_scene(scene, *, force=False, context=None):
    if not scene:
        return False
    try:
        if not force and bool(scene.get(_PREFERENCES_SCENE_MARKER, False)):
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
        "fbp_alpha_render_method": getattr(prefs, "default_alpha_render_method", 'AUTO'),
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
        scene[_PREFERENCES_SCENE_MARKER] = True
    except FBP_DATA_ERRORS:
        pass
    return changed


def fbp_mark_scenes_preferences_initialized(scenes=None):
    scenes = scenes if scenes is not None else getattr(bpy.data, "scenes", [])
    for scene in list(scenes):
        try:
            scene[_PREFERENCES_SCENE_MARKER] = True
        except FBP_DATA_ERRORS:
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

def update_interpolation_cb(self, context):
    return _call_core('update_interpolation_cb', self, context)


def update_extend_mode_cb(self, context):
    return _call_core('update_extend_mode_cb', self, context)


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
update_pixelate_height_cb = _make_effect_update_callback('PIXELATE', 'fbp_pixelate_height')
update_pixelate_grid_mode_cb = _make_effect_update_callback('PIXELATE', 'fbp_pixelate_grid_mode')
update_depth_blur_mode_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_mode')
update_depth_blur_manual_radius_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_manual_radius')
update_depth_blur_max_radius_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_max_radius')
update_depth_blur_use_camera_focus_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_use_camera_focus')
update_depth_blur_focus_distance_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_focus_distance')
update_depth_blur_focus_range_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_focus_range')
update_depth_blur_falloff_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_falloff')
update_depth_blur_near_strength_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_near_strength')
update_depth_blur_far_strength_cb = _make_effect_update_callback('DEPTH_BLUR', 'fbp_depth_blur_far_strength')
update_alpha_matte_source_cb = _make_effect_update_callback('ALPHA_MATTE', 'fbp_alpha_matte_source')
update_alpha_matte_factor_cb = _make_effect_update_callback('ALPHA_MATTE', 'fbp_alpha_matte_factor')
update_alpha_matte_invert_cb = _make_effect_update_callback('ALPHA_MATTE', 'fbp_alpha_matte_invert')
update_alpha_matte_use_source_transform_cb = _make_effect_update_callback('ALPHA_MATTE', 'fbp_alpha_matte_use_source_transform')
update_alpha_matte_source_display_cb = _make_effect_update_callback('ALPHA_MATTE', 'fbp_alpha_matte_source_display')
update_alpha_matte_uv_offset_x_cb = _make_effect_update_callback('ALPHA_MATTE', 'fbp_alpha_matte_uv_offset_x')
update_alpha_matte_uv_offset_y_cb = _make_effect_update_callback('ALPHA_MATTE', 'fbp_alpha_matte_uv_offset_y')
update_alpha_matte_uv_scale_x_cb = _make_effect_update_callback('ALPHA_MATTE', 'fbp_alpha_matte_uv_scale_x')
update_alpha_matte_uv_scale_y_cb = _make_effect_update_callback('ALPHA_MATTE', 'fbp_alpha_matte_uv_scale_y')
update_alpha_matte_uv_rotation_cb = _make_effect_update_callback('ALPHA_MATTE', 'fbp_alpha_matte_uv_rotation')
update_luma_matte_source_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_source')
update_luma_matte_factor_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_factor')
update_luma_matte_invert_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_invert')
update_luma_matte_threshold_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_threshold')
update_luma_matte_softness_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_softness')
update_luma_matte_use_source_transform_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_use_source_transform')
update_luma_matte_source_display_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_source_display')
update_luma_matte_uv_offset_x_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_uv_offset_x')
update_luma_matte_uv_offset_y_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_uv_offset_y')
update_luma_matte_uv_scale_x_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_uv_scale_x')
update_luma_matte_uv_scale_y_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_uv_scale_y')
update_luma_matte_uv_rotation_cb = _make_effect_update_callback('LUMA_MATTE', 'fbp_luma_matte_uv_rotation')
update_clipping_mask_source_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_source')
update_clipping_mask_factor_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_factor')
update_clipping_mask_invert_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_invert')
update_clipping_mask_use_source_transform_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_use_source_transform')
update_clipping_mask_uv_offset_x_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_uv_offset_x')
update_clipping_mask_uv_offset_y_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_uv_offset_y')
update_clipping_mask_uv_scale_x_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_uv_scale_x')
update_clipping_mask_uv_scale_y_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_uv_scale_y')
update_clipping_mask_uv_rotation_cb = _make_effect_update_callback('CLIPPING_MASK', 'fbp_clipping_mask_uv_rotation')
update_square_mask_object_cb = _make_effect_update_callback('SQUARE_MASK', 'fbp_square_mask_object')
update_square_mask_factor_cb = _make_effect_update_callback('SQUARE_MASK', 'fbp_square_mask_factor')
update_square_mask_invert_cb = _make_effect_update_callback('SQUARE_MASK', 'fbp_square_mask_invert')
update_square_mask_feather_cb = _make_effect_update_callback('SQUARE_MASK', 'fbp_square_mask_feather')
update_circle_mask_object_cb = _make_effect_update_callback('CIRCLE_MASK', 'fbp_circle_mask_object')
update_circle_mask_factor_cb = _make_effect_update_callback('CIRCLE_MASK', 'fbp_circle_mask_factor')
update_circle_mask_invert_cb = _make_effect_update_callback('CIRCLE_MASK', 'fbp_circle_mask_invert')
update_circle_mask_feather_cb = _make_effect_update_callback('CIRCLE_MASK', 'fbp_circle_mask_feather')
update_triangle_mask_object_cb = _make_effect_update_callback('TRIANGLE_MASK', 'fbp_triangle_mask_object')
update_triangle_mask_factor_cb = _make_effect_update_callback('TRIANGLE_MASK', 'fbp_triangle_mask_factor')
update_triangle_mask_invert_cb = _make_effect_update_callback('TRIANGLE_MASK', 'fbp_triangle_mask_invert')
update_triangle_mask_feather_cb = _make_effect_update_callback('TRIANGLE_MASK', 'fbp_triangle_mask_feather')
update_color_mask_color_cb = _make_effect_update_callback('COLOR_MASK', 'fbp_color_mask_color')
update_color_mask_tolerance_cb = _make_effect_update_callback('COLOR_MASK', 'fbp_color_mask_tolerance')
update_color_mask_softness_cb = _make_effect_update_callback('COLOR_MASK', 'fbp_color_mask_softness')
update_color_mask_factor_cb = _make_effect_update_callback('COLOR_MASK', 'fbp_color_mask_factor')
update_color_mask_invert_cb = _make_effect_update_callback('COLOR_MASK', 'fbp_color_mask_invert')
update_gradient_mask_type_cb = _make_effect_update_callback('GRADIENT_MASK', 'fbp_gradient_mask_type')
update_gradient_mask_center_x_cb = _make_effect_update_callback('GRADIENT_MASK', 'fbp_gradient_mask_center_x')
update_gradient_mask_center_y_cb = _make_effect_update_callback('GRADIENT_MASK', 'fbp_gradient_mask_center_y')
update_gradient_mask_scale_cb = _make_effect_update_callback('GRADIENT_MASK', 'fbp_gradient_mask_scale')
update_gradient_mask_angle_cb = _make_effect_update_callback('GRADIENT_MASK', 'fbp_gradient_mask_angle')
update_gradient_mask_position_cb = _make_effect_update_callback('GRADIENT_MASK', 'fbp_gradient_mask_position')
update_gradient_mask_feather_cb = _make_effect_update_callback('GRADIENT_MASK', 'fbp_gradient_mask_feather')
update_gradient_mask_factor_cb = _make_effect_update_callback('GRADIENT_MASK', 'fbp_gradient_mask_factor')
update_gradient_mask_invert_cb = _make_effect_update_callback('GRADIENT_MASK', 'fbp_gradient_mask_invert')
update_noise_mask_scale_cb = _make_effect_update_callback('NOISE_MASK', 'fbp_noise_mask_scale')
update_noise_mask_detail_cb = _make_effect_update_callback('NOISE_MASK', 'fbp_noise_mask_detail')
update_noise_mask_roughness_cb = _make_effect_update_callback('NOISE_MASK', 'fbp_noise_mask_roughness')
update_noise_mask_threshold_cb = _make_effect_update_callback('NOISE_MASK', 'fbp_noise_mask_threshold')
update_noise_mask_softness_cb = _make_effect_update_callback('NOISE_MASK', 'fbp_noise_mask_softness')
update_noise_mask_seed_cb = _make_effect_update_callback('NOISE_MASK', 'fbp_noise_mask_seed')
update_noise_mask_factor_cb = _make_effect_update_callback('NOISE_MASK', 'fbp_noise_mask_factor')
update_noise_mask_invert_cb = _make_effect_update_callback('NOISE_MASK', 'fbp_noise_mask_invert')


def _make_object_mask_follow_update(shape, effect_id, prop_name):
    def _update(self, context):
        if fbp_undo_guard_active():
            return
        try:
            from .object_masks import sync_object_mask_helper_to_bounds
            sync_object_mask_helper_to_bounds(self, shape, force=True)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not update Shape Mask bounds", exc)
        return _call_geometry_nodes('update_effect_setting_cb', self, context, effect_id, prop_name)
    return _update


def _make_object_mask_runtime_update(shape):
    def _update(self, context):
        if fbp_undo_guard_active():
            return
        try:
            from .object_masks import (
                find_object_mask_helper,
                sync_object_mask_helper_visibility,
            )
            helper = find_object_mask_helper(self, shape)
            if helper is not None:
                sync_object_mask_helper_visibility(helper, owner=self)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not update Shape Mask helper state", exc)
        try:
            for area in getattr(getattr(context, 'screen', None), 'areas', ()):
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        except (AttributeError, ReferenceError, RuntimeError):
            pass
    return _update


update_square_mask_follow_bounds_cb = _make_object_mask_follow_update('SQUARE', 'SQUARE_MASK', 'fbp_square_mask_follow_bounds')
update_circle_mask_follow_bounds_cb = _make_object_mask_follow_update('CIRCLE', 'CIRCLE_MASK', 'fbp_circle_mask_follow_bounds')
update_triangle_mask_follow_bounds_cb = _make_object_mask_follow_update('TRIANGLE', 'TRIANGLE_MASK', 'fbp_triangle_mask_follow_bounds')
update_square_mask_runtime_cb = _make_object_mask_runtime_update('SQUARE')
update_circle_mask_runtime_cb = _make_object_mask_runtime_update('CIRCLE')
update_triangle_mask_runtime_cb = _make_object_mask_runtime_update('TRIANGLE')
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
update_terminal_ascii_scale_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_scale')
update_terminal_ascii_contrast_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_contrast')
update_terminal_ascii_invert_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_invert')
update_terminal_ascii_fill_strength_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_fill_strength')
update_terminal_ascii_fill_threshold_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_fill_threshold')
update_terminal_ascii_use_edges_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_use_edges')
update_terminal_ascii_edge_strength_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_edge_strength')
update_terminal_ascii_edge_threshold_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_edge_threshold')
update_terminal_ascii_edge_mix_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_edge_mix')
update_terminal_ascii_use_source_color_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_use_source_color')
update_terminal_ascii_foreground_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_foreground')
update_terminal_ascii_background_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_background')
update_terminal_ascii_transparent_background_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_transparent_background')
update_terminal_ascii_seed_cb = _make_effect_update_callback('ASCII', 'fbp_terminal_ascii_seed')
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
update_mesh_ripple_viewport_subdivision_cb = _make_effect_update_callback('MESH_RIPPLE', 'fbp_mesh_ripple_viewport_subdivision')
update_mesh_ripple_playback_subdivision_cb = _make_effect_update_callback('MESH_RIPPLE', 'fbp_mesh_ripple_playback_subdivision')
update_mesh_ripple_render_subdivision_cb = _make_effect_update_callback('MESH_RIPPLE', 'fbp_mesh_ripple_render_subdivision')
update_mesh_ripple_direction_cb = _make_effect_update_callback('MESH_RIPPLE', 'fbp_mesh_ripple_direction')
update_mesh_ripple_amplitude_cb = _make_effect_update_callback('MESH_RIPPLE', 'fbp_mesh_ripple_amplitude')
update_mesh_ripple_frequency_cb = _make_effect_update_callback('MESH_RIPPLE', 'fbp_mesh_ripple_frequency')
update_mesh_ripple_speed_cb = _make_effect_update_callback('MESH_RIPPLE', 'fbp_mesh_ripple_speed')
update_mesh_ripple_phase_cb = _make_effect_update_callback('MESH_RIPPLE', 'fbp_mesh_ripple_phase')
update_mesh_ripple_stepped_cb = _make_effect_update_callback('MESH_RIPPLE', 'fbp_mesh_ripple_stepped')
update_mesh_ripple_pin_borders_cb = _make_effect_update_callback('MESH_RIPPLE', 'fbp_mesh_ripple_pin_borders')
update_mesh_ripple_border_falloff_cb = _make_effect_update_callback('MESH_RIPPLE', 'fbp_mesh_ripple_border_falloff')
update_paper_curl_viewport_subdivision_cb = _make_effect_update_callback('PAPER_CURL', 'fbp_paper_curl_viewport_subdivision')
update_paper_curl_playback_subdivision_cb = _make_effect_update_callback('PAPER_CURL', 'fbp_paper_curl_playback_subdivision')
update_paper_curl_render_subdivision_cb = _make_effect_update_callback('PAPER_CURL', 'fbp_paper_curl_render_subdivision')
update_paper_curl_edge_cb = _make_effect_update_callback('PAPER_CURL', 'fbp_paper_curl_edge')
update_paper_curl_progress_cb = _make_effect_update_callback('PAPER_CURL', 'fbp_paper_curl_progress')
update_paper_curl_angle_cb = _make_effect_update_callback('PAPER_CURL', 'fbp_paper_curl_angle')
update_paper_curl_radius_cb = _make_effect_update_callback('PAPER_CURL', 'fbp_paper_curl_radius')
update_paper_curl_width_cb = _make_effect_update_callback('PAPER_CURL', 'fbp_paper_curl_width')
update_paper_curl_lift_cb = _make_effect_update_callback('PAPER_CURL', 'fbp_paper_curl_lift')
update_paper_curl_reverse_cb = _make_effect_update_callback('PAPER_CURL', 'fbp_paper_curl_reverse')
update_cutout_outline_viewport_resolution_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_viewport_resolution')
update_cutout_outline_playback_resolution_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_playback_resolution')
update_cutout_outline_render_resolution_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_render_resolution')
update_cutout_outline_alpha_threshold_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_alpha_threshold')
update_cutout_outline_width_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_width')
update_cutout_outline_offset_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_offset')
update_cutout_outline_color_cb = _make_effect_update_callback('CUTOUT_OUTLINE', 'fbp_cutout_outline_color')
update_camera_scale_lock_reference_distance_cb = _make_effect_update_callback('CAMERA_SCALE_LOCK', 'fbp_camera_scale_lock_reference_distance')
update_camera_scale_lock_reference_lens_cb = _make_effect_update_callback('CAMERA_SCALE_LOCK', 'fbp_camera_scale_lock_reference_lens')
update_camera_scale_lock_reference_sensor_width_cb = _make_effect_update_callback('CAMERA_SCALE_LOCK', 'fbp_camera_scale_lock_reference_sensor_width')
update_camera_scale_lock_influence_cb = _make_effect_update_callback('CAMERA_SCALE_LOCK', 'fbp_camera_scale_lock_influence')
update_camera_billboard_mode_cb = _make_effect_update_callback('CAMERA_BILLBOARD', 'fbp_camera_billboard_mode')
update_camera_billboard_flip_cb = _make_effect_update_callback('CAMERA_BILLBOARD', 'fbp_camera_billboard_flip')
update_camera_billboard_offset_cb = _make_effect_update_callback('CAMERA_BILLBOARD', 'fbp_camera_billboard_offset')
update_thickness_viewport_pixels_x_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_viewport_pixels_x')
update_thickness_viewport_pixels_y_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_viewport_pixels_y')
update_thickness_playback_pixels_x_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_playback_pixels_x')
update_thickness_playback_pixels_y_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_playback_pixels_y')
update_thickness_render_pixels_x_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_render_pixels_x')
update_thickness_render_pixels_y_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_render_pixels_y')
update_thickness_grid_mode_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_grid_mode')
update_thickness_follow_pixelate_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_follow_pixelate')
update_thickness_amount_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_amount')
update_thickness_alpha_threshold_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_alpha_threshold')
update_thickness_direction_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_direction')
update_thickness_side_material_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_side_material')
update_thickness_side_color_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_side_color')
update_thickness_use_plane_colors_cb = _make_effect_update_callback('THICKNESS', 'fbp_thickness_use_plane_colors')
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
update_recolor_factor_cb = _make_effect_update_callback('RECOLOR', 'fbp_recolor_factor')
update_paper_fiber_scale_cb = _make_effect_update_callback('PAPER_FIBERS', 'fbp_paper_fiber_scale')
update_paper_fiber_intensity_cb = _make_effect_update_callback('PAPER_FIBERS', 'fbp_paper_fiber_intensity')
update_paper_fiber_phase_cb = _make_effect_update_callback('PAPER_FIBERS', 'fbp_paper_fiber_phase')
update_gradient_light_angle_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_light_angle')
update_gradient_light_strength_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_light_strength')
update_gradient_shadow_position_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_shadow_position')
update_gradient_softness_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_softness')
update_gradient_shadow_color_cb = _make_effect_update_callback('GRADIENT_LIGHT', 'fbp_gradient_shadow_color')
update_rim_width_cb = _make_effect_update_callback('RIM', 'fbp_rim_width')
update_rim_softness_cb = _make_effect_update_callback('RIM', 'fbp_rim_softness')
update_rim_intensity_cb = _make_effect_update_callback('RIM', 'fbp_rim_intensity')
update_rim_color_cb = _make_effect_update_callback('RIM', 'fbp_rim_color')
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
    'ASCII',
    'TEXT_MATRIX',
    'PAPER_FIBERS',
    'POSTERIZE',
    'SOLID_MASK',
    'FELT_FUZZ',
)


def _effect_animation_property_name(effect_id, suffix):
    return fbp_effect_storage_key("fbp_anim_", effect_id, f"_{suffix}")


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
                except FBP_DATA_ERRORS:
                    pass


def _fbp_mask_source_poll(owner, candidate):
    """Expose only compatible FBP media rigs from the owner's Scene."""
    try:
        if (
            candidate is None
            or candidate == owner
            or not bool(getattr(candidate, "is_fbp_control", False))
            or bool(getattr(candidate, "fbp_is_color_plane", False))
            or getattr(candidate, "fbp_plane_target", None) is None
        ):
            return False
        owner_scenes = tuple(getattr(owner, "users_scene", ()) or ())
        candidate_scenes = tuple(getattr(candidate, "users_scene", ()) or ())
        if owner_scenes and candidate_scenes:
            owner_keys = {int(scene.as_pointer()) for scene in owner_scenes}
            if not any(int(scene.as_pointer()) in owner_keys for scene in candidate_scenes):
                return False
        return True
    except FBP_DATA_ERRORS:
        return False


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
    # Runtime layer row: never keep an Object PointerProperty inside the Scene
    # collection. Blender 5.1 can become unstable while Undo frees such nested
    # pointers. Store the readable name plus the current runtime pointer token.
    # The token keeps the row resolvable during the short interval between an
    # Outliner rename and the deferred scene-sync repair.
    obj_name: StringProperty(description="Stored object name used as a compatibility fallback when the direct Frame By Plane object reference is temporarily unavailable.", name="Object Name", default="", options={'SKIP_SAVE'})
    obj_runtime_key: StringProperty(description="Runtime identity token used to resolve renamed or duplicated Frame By Plane objects safely.", name="Runtime Object Key", default="", options={'SKIP_SAVE'})

    @property
    def obj(self):
        name = str(getattr(self, "obj_name", "") or "")
        runtime_key = str(getattr(self, "obj_runtime_key", "") or "")
        candidate = bpy.data.objects.get(name) if name else None
        if candidate:
            try:
                if (
                    bool(getattr(candidate, "is_fbp_control", False))
                    and (not runtime_key or fbp_obj_matches_runtime_token(candidate, runtime_key))
                ):
                    return candidate
            except FBP_DATA_ERRORS:
                candidate = None
        if not runtime_key:
            return None
        try:
            for obj in bpy.data.objects:
                if fbp_obj_matches_runtime_token(obj, runtime_key):
                    return obj if bool(getattr(obj, "is_fbp_control", False)) else None
        except FBP_DATA_ERRORS:
            return None
        return None

    @obj.setter
    def obj(self, value):
        try:
            self.obj_name = str(getattr(value, "name", "") or "") if value else ""
            self.obj_runtime_key = fbp_obj_runtime_token(value) if value else ""
        except FBP_DATA_ERRORS:
            self.obj_name = ""
            self.obj_runtime_key = ""

    solo:   BoolProperty(description="Temporary solo state for this layer. When any layer is soloed, non-solo Frame By Plane layers are hidden without changing normal visibility.", default=False)
    mute:   BoolProperty(description="Temporary layer mute state used by the Layers UI and visibility synchronization.", default=False, update=update_mute_cb)
    folded: BoolProperty(description="UI-only collapsed state used when displaying grouped layer information.", default=False)

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
    row_type: EnumProperty(
        name="Row Type",
        description="Internal UI row type used to display real folder rows separately from their member effects",
        items=(
            ('EFFECT', "Effect", "A concrete shader or Geometry Nodes effect"),
            ('GROUP', "Folder", "A persistent Effect Group folder row"),
        ),
        default='EFFECT',
        options={'SKIP_SAVE'},
    )
    effect_id: StringProperty(description="Internal stable identifier of the Frame By Plane effect targeted by this action.", name="Effect ID", default="", options={'SKIP_SAVE'})
    instance_id: StringProperty(
        name="Effect Instance ID",
        description="Persistent identity reserved for future duplicate effect instances",
        default="",
        options={'SKIP_SAVE'},
    )
    group_id: StringProperty(
        name="Effect Group ID",
        description="Persistent organizational group assigned to this effect",
        default="",
        options={'SKIP_SAVE'},
    )
    group_name: StringProperty(
        name="Effect Group",
        description="Display name of the organizational Effect Group",
        default="",
        options={'SKIP_SAVE'},
    )
    group_is_first: BoolProperty(
        name="First Group Member",
        description="Internal UI flag marking the first visible member of an Effect Group",
        default=False,
        options={'SKIP_SAVE'},
    )
    group_collapsed: BoolProperty(
        name="Group Collapsed",
        description="Transient read-only mirror of the Effect Group collapse state used while drawing the stack",
        default=False,
        options={'SKIP_SAVE'},
    )
    group_member_count: IntProperty(
        name="Group Member Count",
        description="Transient number of effects represented by this Effect Group row",
        default=0,
        min=0,
        options={'SKIP_SAVE'},
    )
    label: StringProperty(description="User-facing label displayed for this runtime effect-stack entry.", name="Effect", default="Effect", options={'SKIP_SAVE'})
    is_selected: BoolProperty(
        name="Select Effect",
        description="Include this effect in grouped stack actions. When no checkbox is selected, actions use the active row",
        default=False,
        options={'SKIP_SAVE'},
    )
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


class FBP_EffectGroupItem(PropertyGroup):
    """Persistent organizational metadata for one logical Effect Group."""

    group_id: StringProperty(
        name="Group ID",
        description="Persistent identity shared by the effects assigned to this group",
        default="",
    )
    group_name: StringProperty(
        name="Group Name",
        description="Display name reserved for the Effect Groups interface",
        default="Effect Group",
    )
    collapsed: BoolProperty(
        name="Collapsed",
        description="Store whether this group is collapsed in the Effects Stack",
        default=False,
    )
    color_tag: EnumProperty(
        name="Color Tag",
        description="Color used by the Effect Group folder icon",
        items=COLLECTION_COLOR_ENUM_ITEMS,
        default='NONE',
    )


class FBP_ImageItem(PropertyGroup):
    name:        StringProperty(description="User-facing name stored for this Frame By Plane list entry.", name="Name", default="Image")
    duration:    IntProperty(name="Duration", description="Number of timeline frames this image/frame stays visible", default=2, min=1, update=update_image_duration_cb)
    is_selected: BoolProperty(name="Select", description="Include this frame in frame-list actions such as duplicate, split, sort or delete", default=True)
    is_empty:    BoolProperty(name="Empty", description="Marks this row as a transparent placeholder frame", default=False)
    filepath:    StringProperty(name="File", description="External image or video path used by this logical frame. Frame By Plane links the source and never deletes the file from disk.", subtype='FILE_PATH', default="")
    image:        PointerProperty(name="Image", description="Persistent Blender Image used by Cutout Plane entries", type=bpy.types.Image)
    image_name:   StringProperty(name="Image Datablock", description="Fallback datablock name for Cutout Plane compatibility", default="")
    managed_image: BoolProperty(name="Managed Buffer", description="Allow Frame by Plane to release inactive CPU/GPU buffers for this external Cutout image", default=False)
    source_width: IntProperty(name="Source Width", description="Cached source width used without decoding the image again", default=0, min=0)
    source_height: IntProperty(name="Source Height", description="Cached source height used without decoding the image again", default=0, min=0)
    stable_id:    StringProperty(name="Stable ID", description="Persistent unique identifier for this Cutout Plane library entry, used to keep animation references stable when drawings are reordered or renamed.", default="")
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
    row_type: EnumProperty(description="Internal row category used to distinguish collection, layer and setup rows in Frame By Plane UI lists.",
        name="Row Type",
        items=[
            ('GROUP', "Group", "Collection header row"),
            ('LAYER', "Layer", "Frame by Plane layer row"),
        ],
        default='LAYER'
    )
    name: StringProperty(description="User-facing name stored for this Frame By Plane list entry.", name="Display Name", default="")
    collection_name: StringProperty(description="Name of the Blender or pending setup collection targeted by this action.", name="Collection Name", default="")
    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", name="Rig Name", default="")
    layer_index: IntProperty(description="Index of the corresponding Frame By Plane layer in the scene runtime layer list.", name="Layer Index", default=-1)
    depth: IntProperty(description="Cached hierarchy indentation depth used to draw this tree row.", name="Depth", default=0, min=0)
    layer_count: IntProperty(description="Cached number of Frame By Plane layers contained in this collection row.", name="Direct Layer Count", default=0, min=0)
    child_count: IntProperty(description="Cached number of direct or nested child rows represented by this collection.", name="Child Collection Count", default=0, min=0)


class FBP_PendingPlaneItem(PropertyGroup):
    name:          StringProperty(name="Name", description="Editable name assigned to the Frame By Plane control rig and generated layer when this pending Multiplane Setup entry is built.", default="New Layer")
    collection_name: StringProperty(name="Collection", description="Collection name that will receive this pending layer during Multiplane generation. Editing it reorganizes only the setup preview until generation.", default="")
    directory:     StringProperty(name="Source Folder", description="Folder containing the images for this pending layer")
    files_str:     StringProperty(name="Files", description="Internal list of image files that will become this layer sequence")
    is_selected: BoolProperty(
        name="Select Setup Layer",
        description="Include this pending layer in grouped Multiplane Setup actions such as Reverse Selected Order",
        default=False,
    )
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
    row_type: EnumProperty(description="Internal row category used to distinguish collection, layer and setup rows in Frame By Plane UI lists.",
        name="Row Type",
        items=[
            ('GROUP', "Group", "Folder header row"),
            ('LAYER', "Layer", "Importable image layer row"),
        ],
        default='LAYER'
    )
    name: StringProperty(description="User-facing name stored for this Frame By Plane list entry.", name="Display Name", default="")
    collection_path: StringProperty(description="Serialized setup collection path used to rebuild nested Multiplane hierarchy before generation.", name="Collection Path", default="")
    pending_index: IntProperty(description="Index of the source Multiplane Setup layer represented by this flattened preview row.", name="Pending Layer Index", default=-1)
    depth: IntProperty(description="Cached hierarchy indentation depth used to draw this tree row.", name="Depth", default=0, min=0)
    file_count: IntProperty(description="Cached number of media files represented by this setup row, used for responsive UI display.", name="Frame Count", default=0, min=0)
    layer_count: IntProperty(description="Cached number of Frame By Plane layers contained in this collection row.", name="Layer Count", default=0, min=0)
    child_count: IntProperty(description="Cached number of direct or nested child rows represented by this collection.", name="Child Count", default=0, min=0)
    can_move_up: BoolProperty(description="Whether this pending setup layer can move upward inside its current collection.", name="Can Move Up", default=False, options={'SKIP_SAVE'})
    can_move_down: BoolProperty(description="Whether this pending setup layer can move downward inside its current collection.", name="Can Move Down", default=False, options={'SKIP_SAVE'})
    can_toggle_structure: BoolProperty(description="Whether this setup row can be converted between an animated sequence and a collection of still planes.", name="Can Split or Merge", default=False, options={'SKIP_SAVE'})
    collection_color_editable: BoolProperty(description="Whether the collection color control can be edited from this Multiplane Setup row.", name="Editable Collection Color", default=True, options={'SKIP_SAVE'})
    collection_color_tag: EnumProperty(
        name="Collection Color",
        description="Color tag that will be assigned to this generated collection",
        items=COLLECTION_COLOR_ENUM_ITEMS,
        default='NONE',
        update=update_pending_collection_color_cb,
        options={'SKIP_SAVE'},
    )


class FBP_GenerationRenameItem(PropertyGroup):
    rig_name: StringProperty(description="Name of the Frame By Plane control rig targeted by this action. Stored only long enough to resolve the object safely.", name="Rig Name", default="", options={'SKIP_SAVE'})
    display_name: StringProperty(description="User-facing sequence name shown in the generation repair report.", name="Sequence", default="", options={'SKIP_SAVE'})
    message: StringProperty(description="Diagnostic message describing the sequence or generation problem.", name="Issue", default="", options={'SKIP_SAVE'})
    preview_files: StringProperty(description="Compact list of example filenames shown for this generation problem.", name="Files", default="", options={'SKIP_SAVE'})
    is_renamed: BoolProperty(description="Whether this reported sequence has already been repaired by the safe rename operation.", name="Renamed", default=False, options={'SKIP_SAVE'})



# SECTION 02 - Scene / Collection / Object property registration #

def register_properties():
    bpy.types.Scene.fbp_last_directory = StringProperty(name="Last Folder", description="Last folder used by Frame by Plane file browsers", subtype='DIR_PATH', default="")
    bpy.types.Scene.fbp_effect_mask_edit_target = StringProperty(
        name="Effect Mask Editor",
        description="Transient 2D effect whose local masks are expanded below the Effects Stack",
        default="", options={'SKIP_SAVE'},
    )
    bpy.types.Scene.fbp_project_path = StringProperty(
        name="Project Folder", description="Root folder used for project import, relinking and health checks", subtype='DIR_PATH', default="")
    bpy.types.Scene.fbp_parent_import_path = StringProperty(
        name="Project Folder", description="Root folder currently represented by Multiplane Setup. It is used for relative paths, rescanning and relinking without copying source media.", subtype='DIR_PATH')
    bpy.types.Scene.fbp_cam_ratio = EnumProperty(description="Select the output aspect-ratio preset used when Frame By Plane creates or configures a camera. The preset updates render width and height while Custom keeps the current resolution.",
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
    bpy.types.Scene.fbp_show_previews = BoolProperty(
        name="Show List Thumbnails",
        description="Show thumbnails inside layer, frame and Cutout library lists; the large active Cutout preview always remains visible",
        default=False,
        update=update_show_previews_cb,
    )
    bpy.types.Scene.fbp_thumbnail_background_enabled = BoolProperty(
        name="Thumbnail Background",
        description="Place all Frame by Plane image thumbnails over the selected background color",
        default=False,
    )
    bpy.types.Scene.fbp_thumbnail_background_color = FloatVectorProperty(
        name="Thumbnail Background Color",
        description="Color shown behind transparent pixels in all Frame by Plane image thumbnails",
        subtype='COLOR', size=3, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0),
    )
    bpy.types.Scene.fbp_show_color_previews = BoolProperty(name="Show Color Preview", description="Show color/gradient chips in Layer and Frame lists instead of generic procedural icons", default=True)
    bpy.types.Scene.fbp_sort_layers_alpha = BoolProperty(
        name="A-Z",
        description="Sort layers and collections alphabetically instead of by camera distance",
        default=False)
    bpy.types.Scene.fbp_auto_clean_orphans = BoolProperty(
        name="Auto-clean orphan Frame by Plane objects",
        description="After normal deletion, remove orphan FBP planes and safely purge unused FBP mesh/material datablocks. Image datablocks and files on disk are never deleted automatically",
        default=True)
    bpy.types.Scene.fbp_show_create_tools = BoolProperty(name="Show Create Tools", description="Show additional creation tools in the sidebar", default=False)
    bpy.types.Scene.fbp_alpha_render_method = EnumProperty(
        name="Alpha Rendering",
        description="Surface transparency method used by Frame By Plane materials. Auto selects Blended for alpha materials and Opaque for fully opaque materials",
        items=ALPHA_RENDER_METHOD_ITEMS,
        default='AUTO',
        update=update_alpha_render_method_cb,
    )
    bpy.types.Scene.fbp_render_output_dir = StringProperty(
        name="Render Folder",
        description="Folder where the background-rendered frame sequence is saved. Empty creates FBP_Render_Frames beside the .blend file",
        subtype='DIR_PATH',
        default="")
    bpy.types.Scene.fbp_render_prefix = StringProperty(
        name="Filename Prefix",
        description="Filename prefix used for background-rendered frames",
        default="frame_")
    bpy.types.Scene.fbp_background_render_running = BoolProperty(description="Runtime flag indicating that a Frame By Plane background-render process is currently active. This value is managed automatically and is not saved in the .blend file.", name="Background Render Running", default=False, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_background_render_status = StringProperty(description="Human-readable runtime status reported by the active Frame By Plane background renderer, including idle, rendering, completed, stopped or error states.", name="Background Render Status", default="Idle", options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_background_render_progress = IntProperty(description="Number of frames confirmed as completed by the current Frame By Plane background-render process.", name="Rendered Frames", default=0, min=0, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_background_render_total = IntProperty(description="Total number of frames scheduled for the current Frame By Plane background render.", name="Total Frames", default=0, min=0, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_background_render_output_dir = StringProperty(description="Resolved output directory used by the active background-render process. This runtime path is updated automatically and is not stored in the project.", name="Output Folder", default="", subtype='DIR_PATH', options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_generation_rename_items = CollectionProperty(description="Runtime list of problematic image sequences reported during generation and available for safe filename repair.", type=FBP_GenerationRenameItem, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_generation_rename_index = IntProperty(name="Rename Sequence Index", description="Active problematic sequence in the generation rename list", default=0, min=0, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_auto_collection_color_variants = BoolProperty(
        name="Collection Color Variants",
        description="Give layers small viewport color variations based on their collection color",
        default=True,
        update=update_collection_color_variants_cb,
    )
    bpy.types.Scene.fbp_layers = CollectionProperty(description="Runtime mirror of Frame By Plane rig layers in the active scene, used by the Layers tree and multi-layer controls.", type=FBP_LayerItem, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_layer_stack_index = IntProperty(
        name="Layer Index", description="Active layer row in the Frame by Plane layer list", default=0, update=update_layer_stack_index_cb)
    bpy.types.Scene.fbp_layer_tree_rows = CollectionProperty(description="Flattened runtime rows used to display collections and layers in the Frame By Plane Layers tree without rebuilding hierarchy data for every visible row.", type=FBP_LayerTreeRowItem, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_layer_tree_rows_idx = IntProperty(name="Layer Tree Row", description="Runtime index of the active visible Layer Tree row. Frame By Plane keeps it synchronized with the selected rig while collections are collapsed or reordered.", default=0, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_layer_tree_signature = StringProperty(description="Internal cache signature used to rebuild the Layers tree only when its structure actually changes.", name="Layer Tree Signature", default="", options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_pending_open_collections = StringProperty(description="Internal serialized set of Multiplane Setup collections currently expanded in the preview tree.", name="Open Setup Collections", default="", options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_gradient_preview_material_name = StringProperty(description="Internal name of the temporary material used to generate procedural gradient thumbnails in the user interface.", name="Gradient Preview Material", default="", options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_creation_mode = EnumProperty(description="Choose the type of Frame By Plane rig shown in the Create section: Image Plane, Multiplane, Cutout Plane, Color Plane, Gradient Plane or Holdout Plane.",
        name="Mode",
        items=CREATION_MODE_ITEMS,
        default='SINGLE')
    bpy.types.Scene.fbp_effects_view = EnumProperty(
        name="Effect Type",
        description="Choose whether the Effects panel shows image effects, masks or mesh effects",
        items=(
            ('2D', "Image Effects", "Show Base and image-processing shader effects", fbp_icon("NODE_TEXTURE"), 0),
            ('MASK', "Masks", "Show Alpha Matte, Luma Matte and future mask-stack effects", fbp_icon("IMAGE_ALPHA"), 1),
            ('3D', "Mesh Effects", "Show Geometry Nodes and mesh effects", fbp_icon("MODIFIER"), 2),
        ),
        default='2D',
        update=update_effects_view_cb,
    )
    bpy.types.Scene.fbp_pending_planes = CollectionProperty(description="Pending media layers and collections prepared in Multiplane Setup before scene objects are generated.", type=FBP_PendingPlaneItem)
    bpy.types.Scene.fbp_pending_planes_idx = IntProperty(name="Setup Layer Index", description="Index of the active pending Multiplane Setup entry, used by edit, move, replace and remove actions before scene generation.", default=0)
    bpy.types.Scene.fbp_pending_tree_rows = CollectionProperty(description="Flattened runtime rows used to display the collapsible Multiplane Setup hierarchy efficiently.", type=FBP_PendingTreeRowItem, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_pending_tree_rows_idx = IntProperty(name="Setup Tree Row", description="Active visual row in the Multiplane Setup tree UIList", default=0, options={'SKIP_SAVE'})
    bpy.types.Scene.fbp_pending_collection_name = StringProperty(name="Collection", description="Name used when creating a new Multiplane Setup collection", default="New Collection")
    bpy.types.Scene.fbp_pre_duration = IntProperty(
        name="Duration (Frames)", description="Default duration assigned to each imported image frame", default=2, min=1)
    bpy.types.Scene.fbp_pre_shadeless = BoolProperty(name="Shadeless", description="Use lightweight emission materials so image planes are not affected by scene lighting", default=True)
    bpy.types.Scene.fbp_pre_loop_mode = EnumProperty(description="Default playback behavior assigned to newly generated animated Image Planes: play once, loop continuously or alternate forward and backward.",
        name="Playback",
        items=PLAYBACK_ITEMS,
        default='NONE')
    bpy.types.Scene.fbp_pre_interpolation = EnumProperty(description="Default texture filtering for newly generated planes. Pixel keeps hard nearest-neighbor edges; Smooth uses linear filtering for scaled artwork.",
        name="",
        items=INTERPOLATION_ITEMS,
        default='Closest')
    bpy.types.Scene.fbp_pre_orientation = EnumProperty(description="Default spatial orientation for newly generated planes. Vertical faces the camera as artwork; Horizontal places the plane parallel to the ground.",
        name="",
        items=ORIENTATION_ITEMS,
        default='VERT')
    bpy.types.Scene.fbp_gen_camera   = BoolProperty(name="Generate Camera", description="Create or update a camera suitable for the generated multiplane setup", default=True)
    bpy.types.Scene.fbp_cam_pivot    = BoolProperty(name="Pivot on Camera", description="Move the 3D cursor to the camera pivot when creating a camera setup", default=True)
    bpy.types.Scene.fbp_layer_offset = FloatProperty(name="Plane Distance (m)", description="Distance between generated layers; imported top-level collections use a larger gap", default=0.2, min=0.001)
    bpy.types.Scene.fbp_auto_scale   = BoolProperty(name="Auto-Scale (Fit to Cam)", description="Scale generated planes to the camera frame using the image aspect ratio", default=True)
    bpy.types.Scene.fbp_pre_track_cam = BoolProperty(name="Track Camera on New Layers", description="Add camera tracking to newly generated Frame by Plane layers", default=False)
    bpy.types.Scene.fbp_settings_section = EnumProperty(
        name="Settings Section",
        description="Choose which Frame by Plane settings group to display",
        items=[
            ('PROJECT', "Project", "Project folder and file settings"),
            ('DISPLAY', "Display", "Layer-list thumbnails, sorting and scene workflow options"),
            ('CAMERA', "Camera", "Camera projection and frame ratio"),
            ('RENDER', "Render", "Background render controls"),
            ('MAINTENANCE', "Tools", "Repair, relink and diagnostics"),
        ],
        default='PROJECT',
    )
    bpy.types.Scene.fbp_show_project_tools = BoolProperty(name="Project Import", description="Show advanced project and folder import controls", default=True)
    bpy.types.Scene.fbp_color_plane_type = EnumProperty(
        name="Plane Type",
        description="Choose what kind of camera-ratio plane to create",
        items=COLOR_PLANE_TYPE_ITEMS,
        default='CUSTOM')
    bpy.types.Scene.fbp_color_plane_color = FloatVectorProperty(
        name="Color", description="RGBA color used for the next generated Color Plane when Custom is selected. Alpha controls transparency and the source color is not color-managed outside Blender.", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0), update=update_color_plane_color_cb)
    bpy.types.Scene.fbp_color_plane_preset = EnumProperty(
        name="Preset",
        description="Quick color preset for solid Color Plane creation",
        items=COLOR_PLANE_PRESET_ITEMS,
        default='CUSTOM', update=update_color_plane_preset_cb)
    bpy.types.Scene.fbp_color_plane_emission = BoolProperty(name="Emission", description="Use a lightweight emission shader for the color plane", default=True, update=update_scene_gradient_preview_cb)
    bpy.types.Scene.fbp_gradient_mode = EnumProperty(
        name="Gradient Mode", description="Choose a linear gradient across the plane or a centered radial gradient. The selection updates the procedural preview and newly generated Gradient Plane.",
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
    bpy.types.Scene.fbp_gradient_rotation = FloatProperty(name="Gradient Rotation", description="Rotate the procedural gradient mapping around the center of the plane in degrees without rotating the plane object itself.", default=0.0, soft_min=-180.0, soft_max=180.0)
    bpy.types.Scene.fbp_show_gradient_ramp = BoolProperty(name="Show Gradient Ramp", description="Expand or collapse the advanced ColorRamp editor used to adjust gradient stops, positions, interpolation and alpha values.", default=True)
    bpy.types.Scene.fbp_show_gradient_transform = BoolProperty(name="Show Gradient Position", description="Show gradient position, scale and rotation controls", default=True)
    bpy.types.Collection.is_fbp_collection = BoolProperty(description="Internal marker identifying a Blender collection as managed by Frame By Plane.", default=False)
    bpy.types.Collection.fbp_collapsed = BoolProperty(name="Collapsed", description="Collapse or expand this collection in the Frame by Plane Layers list", default=True)
    bpy.types.Collection.fbp_collection_selected = BoolProperty(name="Select Collection Layers", description="Select or deselect all Frame by Plane layers inside this collection. Click-drag across matching icons to paint selection", get=get_collection_selected, set=set_collection_selected)
    bpy.types.Collection.fbp_collection_solo = BoolProperty(name="Solo Collection Layers", description="Solo or unsolo all Frame by Plane layers inside this collection. Click-drag across matching icons to paint solo state", get=get_collection_solo, set=set_collection_solo)
    bpy.types.Collection.fbp_collection_locked = BoolProperty(name="Lock Collection Layers", description="Lock or unlock all Frame by Plane rigs in this collection. Click-drag across matching icons to paint locks", get=get_collection_locked, set=set_collection_locked)
    bpy.types.Collection.fbp_collection_plane_locked = BoolProperty(name="Lock Collection Planes", description="Lock or unlock linked image/color planes in this collection. Click-drag across matching icons to paint plane selectability", get=get_collection_plane_locked, set=set_collection_plane_locked)
    bpy.types.Collection.fbp_collection_visible = BoolProperty(name="Show Collection Layers", description="Show or hide this Frame by Plane collection in the viewport. Click-drag across matching icons to paint visibility", get=get_collection_visible, set=set_collection_visible)
    bpy.types.Collection.fbp_collection_holdout = BoolProperty(name="Holdout Collection Layers", description="Toggle alpha-aware holdout on all Frame by Plane layers inside this collection. Click-drag across matching icons to paint holdouts", get=get_collection_holdout, set=set_collection_holdout)

    bpy.types.Object.is_fbp_control     = BoolProperty(description="Internal marker identifying an object as a Frame By Plane control rig rather than an ordinary scene object.", default=False)
    bpy.types.Object.is_fbp_plane       = BoolProperty(description="Internal marker identifying an object as a plane owned by a Frame By Plane rig.", default=False)
    bpy.types.Object.fbp_is_drawing_plane = BoolProperty(
        name="Is Cutout Plane",
        description="Internal flag for manually selected Cutout Plane image libraries",
        default=False,
    )
    bpy.types.Object.fbp_drawing_auto_key = BoolProperty(
        name="Auto Key Drawing",
        description="Insert or update a Constant keyframe when the drawing slider changes",
        default=True,
    )
    # Legacy per-Cutout preview properties were replaced by Scene-wide thumbnail settings in 5.1.2.
    bpy.types.Object.fbp_layer_name = StringProperty(
        name="Layer Name",
        description="Rename this Frame by Plane layer and update all linked UI references immediately",
        get=get_fbp_layer_name,
        set=set_fbp_layer_name,
        options={'SKIP_SAVE'},
    )
    bpy.types.Object.fbp_collection_name = StringProperty(name="FBP Collection", description="Internal name of the collection this Frame by Plane layer belongs to", default="")
    bpy.types.Object.fbp_follow_collection_color = BoolProperty(name="Follow Collection Color", description="Use the parent collection color tag as the rig viewport color", default=True)
    bpy.types.Object.fbp_color_variant_index = IntProperty(name="Color Variant", description="Internal color variation index used to make layers readable", default=0)
    bpy.types.Object.fbp_base_scale_vec = FloatVectorProperty(name="Base Scale Vector", description="Original generated scale vector used by Fit to Camera", default=(1.0, 1.0, 1.0))
    bpy.types.Object.fbp_preview_path   = StringProperty(name="Preview Path", description="Image path used for the layer thumbnail preview", default="")
    bpy.types.Object.fbp_is_vertical    = BoolProperty(name="Vertical", description="Whether this layer is standing vertically instead of lying horizontally", default=False)
    bpy.types.Object.fbp_images         = CollectionProperty(description="Ordered logical frame list used by this Frame By Plane layer, including linked media, durations, transparent frames and Cutout entries.", type=FBP_ImageItem)
    bpy.types.Object.fbp_images_index   = IntProperty(name="Active Frame", description="Active frame row in the selected Frame by Plane sequence", update=update_image_index_cb)
    bpy.types.Object.fbp_sequence_reversed = BoolProperty(
        name="Reverse Sequence",
        description="Internal direction state controlled by the sequence-side reverse icon",
        default=False,
    )
    bpy.types.Object.fbp_color_tag      = EnumProperty(
        name="Color Tag", description="Viewport and collection color tag for this Frame by Plane layer",
        items=COLOR_ENUM_ITEMS, default='COLOR_01', update=update_color_tag_cb)
    bpy.types.Object.fbp_depth_order    = IntProperty(name="Depth Order", description="Internal depth order used for generated layers", default=0)
    bpy.types.Object.fbp_loop_mode = EnumProperty(description="Choose how this animated layer behaves outside its logical image range. One Shot holds the end frame, Loop repeats, and Ping-Pong alternates direction.",
        name="Playback",
        items=[
            ('NONE',     "One Shot",  "Play the sequence once and hold the last frame", fbp_icon("FORWARD"),        0),
            ('REPEAT',   "Loop",      "Repeat the image sequence indefinitely", fbp_icon("FILE_REFRESH"),   1),
            ('PINGPONG', "Ping-Pong", "Play forward and backward in a loop", fbp_icon("UV_SYNC_SELECT"), 2),
        ],
        default='NONE', update=update_loop_mode_cb)
    bpy.types.Object.fbp_use_emission   = BoolProperty(
        name="Shadeless", description="Use an emission-style material so the image is not affected by scene lighting", default=False, update=update_emission_cb)
    bpy.types.Object.fbp_interpolation  = EnumProperty(description="Choose how the image texture is sampled. Pixel preserves sharp pixel-art edges; Smooth blends neighboring pixels during scaling and camera movement.",
        name="Filter",
        items=[
            ('Closest', "Pixel",  "Use nearest-neighbor filtering for sharp pixel edges", fbp_icon("ALIASED"), 0),
            ('Linear',  "Smooth", "Use linear filtering for smoother image scaling", fbp_icon("ANTIALIASED"), 1),
        ],
        default='Closest', update=update_interpolation_cb)
    bpy.types.Object.fbp_plane_target    = PointerProperty(name="Linked Plane", description="Image plane controlled by this Frame by Plane rig", type=bpy.types.Object)
    bpy.types.Object.fbp_global_duration = IntProperty(
        name="Global Duration", description="Set the duration in frames for all frames in this sequence", default=2, min=1, update=update_global_duration_cb)
    bpy.types.Object.fbp_start_frame     = IntProperty(
        name="Start Frame", description="Timeline frame where this sequence starts playing", default=1, update=update_start_frame_cb)
    bpy.types.Object.fbp_opacity         = FloatProperty(
        name="Opacity", description="Overall opacity multiplier for this layer. At 100% Frame By Plane removes unnecessary multiply nodes where safe; lower values preserve source alpha.", default=1.0, min=0.0, max=1.0,
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
        name="Gradient Mode", description="Choose whether this existing Gradient Plane uses a linear mapping or a centered radial mapping. The material preview updates immediately.",
        items=[('LINEAR', "Linear", "Linear gradient from one side of the plane to the other", fbp_icon("ARROW_LEFTRIGHT"), 0), ('CENTER', "Radial", "Centered radial gradient useful for vignettes", fbp_icon("EMPTY_ARROWS"), 1)], default='LINEAR', update=update_object_color_plane_cb)
    bpy.types.Object.fbp_gradient_kind = EnumProperty(
        name="Gradient Type", description="Choose whether this gradient blends between two colors or changes alpha",
        items=[('COLOR', "Color to Color", "Blend between the From and To colors", fbp_icon("COLOR"), 0), ('ALPHA', "Transparent to Visible", "Fade from the From color at 0 alpha to the To color", fbp_icon("IMAGE_ALPHA"), 1)], default='COLOR', update=update_object_color_plane_cb)
    bpy.types.Object.fbp_gradient_color_a = FloatVectorProperty(name="From", subtype='COLOR', size=4, min=0.0, max=1.0, description="Start color of the gradient ramp. In alpha mode this side is forced transparent", default=(1.0, 0.3686274509803922, 0.596078431372549, 1.0), update=update_object_color_plane_cb)
    bpy.types.Object.fbp_gradient_color_b = FloatVectorProperty(name="To", subtype='COLOR', size=4, min=0.0, max=1.0, description="RGBA color at the To side of this Gradient Plane. Its alpha participates in the material transparency and updates the preview immediately.", default=(0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0), update=update_object_color_plane_cb)
    bpy.types.Object.fbp_gradient_reverse = BoolProperty(name="Reverse Gradient", description="Reverse the gradient direction by swapping its two endpoints without changing their stored colors or the plane transform.", default=True, update=update_object_color_plane_cb)
    bpy.types.Object.fbp_gradient_offset_x = FloatProperty(name="Gradient X Offset", description="Offset the procedural gradient horizontally in local plane coordinates without moving the object or changing its UV layout.", default=0.0, soft_min=-2.0, soft_max=2.0, update=update_gradient_mapping_cb)
    bpy.types.Object.fbp_gradient_offset_y = FloatProperty(name="Gradient Y Offset", description="Offset the procedural gradient vertically in local plane coordinates without moving the object or changing its UV layout.", default=0.0, soft_min=-2.0, soft_max=2.0, update=update_gradient_mapping_cb)
    bpy.types.Object.fbp_gradient_scale_x = FloatProperty(name="Gradient Scale X", description="Stretch or compress this gradient horizontally", default=1.0, min=0.001, soft_min=0.1, soft_max=10.0, update=update_gradient_mapping_cb)
    bpy.types.Object.fbp_gradient_scale_y = FloatProperty(name="Gradient Scale Y", description="Scale the procedural gradient vertically around its center. Values below one compress the transition; larger values stretch it.", default=1.0, min=0.001, soft_min=0.1, soft_max=10.0, update=update_gradient_mapping_cb)
    bpy.types.Object.fbp_gradient_rotation = FloatProperty(name="Gradient Rotation", description="Rotate this Gradient Plane's procedural mapping around the local center in degrees without rotating the object.", default=0.0, soft_min=-180.0, soft_max=180.0, update=update_gradient_mapping_cb)
    bpy.types.Object.fbp_show_gradient_ramp = BoolProperty(name="Show Gradient Ramp", description="Show the advanced ColorRamp controls for this plane", default=True)
    bpy.types.Object.fbp_show_gradient_transform = BoolProperty(name="Show Gradient Position", description="Show the gradient position, scale and rotation controls for this plane", default=True)
    bpy.types.Object.fbp_extend_mode = EnumProperty(name="Extend Mode", description="How the added border geometry samples the original image", items=[('EDGE', "Edge Pixel", "Clamp added geometry to the cropped image edge"), ('REPEAT', "Repeat Texture", "Repeat the texture into the added geometry")], default='EDGE', update=update_extend_mode_cb)
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
    bpy.types.Object.fbp_effects_signature = StringProperty(description="Internal cache signature of the current effect stack, used to avoid unnecessary UI synchronization and node-tree rebuilds.",
        name="Effect Stack Signature", default="", options={'SKIP_SAVE'})
    bpy.types.Object.fbp_effect_groups = CollectionProperty(
        type=FBP_EffectGroupItem,
        description="Persistent organizational groups used by the Frame By Plane Effects Stack")
    bpy.types.Object.fbp_effect_groups_index = IntProperty(
        name="Active Effect Group",
        description="Reserved index for the future Effect Groups interface",
        default=0, min=0)
    bpy.types.Object.fbp_mesh_wiggle_enabled = BoolProperty(
        name="Wiggle",
        description="Enable the bundled Wiggle Geometry Nodes effect on this Frame by Plane layer",
        default=False,
        update=update_mesh_wiggle_enabled_cb)
    bpy.types.Object.fbp_mesh_wiggle_shade_smooth = BoolProperty(
        name="Shade Smooth",
        description="Apply smooth face shading after Wiggle subdivision. Disable it to preserve a faceted paper or low-poly appearance.",
        default=True,
        update=update_mesh_wiggle_shade_smooth_cb)
    bpy.types.Object.fbp_mesh_wiggle_strength = FloatProperty(
        name="Strength",
        description="Strength of the Wiggle deformation. Set to zero to keep the noise fixed visually",
        default=1.0, min=0.0, soft_max=3.0, precision=3,
        update=update_mesh_wiggle_strength_cb)
    bpy.types.Object.fbp_mesh_wiggle_speed = FloatProperty(
        name="Speed",
        description="Multiplier applied to Scene Time when Wiggle animation evolves automatically. Higher values change the noise pattern more rapidly.",
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
        description="Spatial scale of the procedural noise deforming the mesh. Lower values create broad bends; higher values create smaller detailed movement.",
        default=5.0, min=0.001, soft_max=20.0, precision=3,
        update=update_mesh_wiggle_noise_scale_cb)
    bpy.types.Object.fbp_mesh_wiggle_detail = FloatProperty(
        name="Noise Detail",
        description="Number of additional fractal noise octaves used by Wiggle. Higher values add fine deformation detail but increase evaluation cost.",
        default=0.0, min=0.0, soft_max=15.0, precision=3,
        update=update_mesh_wiggle_detail_cb)
    bpy.types.Object.fbp_mesh_wiggle_subdivisions = IntProperty(
        name="Subdivisions",
        description="Subdivision level applied before the Wiggle deformation",
        default=4, min=0, max=6,
        update=update_mesh_wiggle_subdivisions_cb)

    # Additional geometry effects from the corrected bundled library
    bpy.types.Object.fbp_stop_motion_resolution = IntProperty(description="Subdivision level used before the Stop Motion Crumple deformation. Higher values preserve finer bends but increase viewport and render cost.", name="Resolution", default=5, min=0, max=6, update=update_stop_motion_resolution_cb)
    bpy.types.Object.fbp_stop_motion_strength = FloatProperty(description="Maximum displacement applied by Stop Motion Crumple. Increase for stronger paper-like deformation; zero keeps the plane flat.", name="Strength", default=0.05, min=0.0, soft_max=1.0, precision=3, update=update_stop_motion_strength_cb)
    bpy.types.Object.fbp_stop_motion_step_frames = IntProperty(description="Number of timeline frames each Stop Motion Crumple pose is held before a new deterministic deformation is evaluated.", name="Step Frames", default=3, min=1, soft_max=24, update=update_stop_motion_step_frames_cb)
    bpy.types.Object.fbp_wind_bend_amount = FloatProperty(description="Overall amount and direction of Wind Bender deformation. Positive and negative values bend the free side in opposite directions.", name="Bend Amount", default=0.5, soft_min=-2.0, soft_max=2.0, precision=3, update=update_wind_bend_amount_cb)
    bpy.types.Object.fbp_wind_speed = FloatProperty(description="Animation speed used by Wind Bender. Negative values reverse temporal direction; zero freezes the current wind phase.", name="Wind Speed", default=2.0, soft_min=-20.0, soft_max=20.0, precision=3, update=update_wind_speed_cb)
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
    bpy.types.Object.fbp_wind_wave_amplitude = FloatProperty(description="Strength of traveling waves layered over the main Wind Bender deformation.",
        name="Wave Amplitude", default=0.12, min=0.0, soft_max=1.0, max=10.0, update=update_wind_wave_amplitude_cb)
    bpy.types.Object.fbp_wind_wave_speed = FloatProperty(description="Speed and direction of traveling waves in Wind Bender. Negative values make waves move backward.",
        name="Wave Speed", default=2.0, soft_min=-20.0, soft_max=20.0, update=update_wind_wave_speed_cb)
    bpy.types.Object.fbp_wind_phase = FloatProperty(description="Manual phase offset for Wind Bender waves. Animate this value to control motion independently from automatic Scene Time.",
        name="Phase", default=0.0, soft_min=-6.283185, soft_max=6.283185, subtype='ANGLE', update=update_wind_phase_cb)
    bpy.types.Object.fbp_wind_turbulence = FloatProperty(
        name="Turbulence", description="Small irregular motion layered over the main deformation",
        default=0.03, min=0.0, soft_max=0.3, max=2.0, update=update_wind_turbulence_cb)
    bpy.types.Object.fbp_wind_reverse = BoolProperty(
        name="Reverse Direction", description="Reverse the wind displacement vector while preserving all other Wind Bender strength, turbulence and animation settings.",
        default=False, update=update_wind_reverse_cb)
    bpy.types.Object.fbp_wind_falloff = FloatProperty(
        name="Falloff", description="Shape how strongly the pinned edge stays fixed",
        default=1.5, min=0.1, max=8.0, update=update_wind_falloff_cb)
    bpy.types.Object.fbp_wind_noise_scale = FloatProperty(
        name="Noise Scale", description="Size of the turbulence pattern used by Wind Bender. Lower values produce broad gusts; higher values create smaller local variations.",
        default=3.0, min=0.01, soft_max=20.0, max=100.0, update=update_wind_noise_scale_cb)
    bpy.types.Object.fbp_wind_gust_strength = FloatProperty(
        name="Gust Strength", description="Amount of slow irregular gust variation layered over the main wind cycle to reduce visibly repetitive motion.",
        default=0.0, min=0.0, soft_max=1.0, max=4.0, update=update_wind_gust_strength_cb)
    bpy.types.Object.fbp_wind_direction_space = EnumProperty(
        name="Direction Space",
        description="Interpret Wind Direction in the plane local axes or in world axes",
        items=(("LOCAL", "Local", "Direction rotates with the plane"),
               ("WORLD", "World", "Direction stays aligned to the world")),
        default="LOCAL", update=update_wind_direction_space_cb)
    bpy.types.Object.fbp_wind_direction = FloatVectorProperty(
        name="Wind Direction", description="Normalized local-space direction used by Wind Bender to displace the plane. This changes deformation direction without rotating the object.",
        size=3, subtype='DIRECTION', default=(0.0, 0.0, 1.0),
        min=-1.0, max=1.0, update=update_wind_direction_cb)
    bpy.types.Object.fbp_wind_preview_falloff = BoolProperty(
        name="Preview Falloff",
        description="Temporarily replace animated wind with a static displacement that visualizes pinned-edge falloff",
        default=False, update=update_wind_preview_falloff_cb)
    bpy.types.Object.fbp_felt_render_density = IntProperty(
        name="Render Density",
        description="Approximate strand count generated by Felt Fuzz at render quality. Higher values increase density, memory use and render time substantially.",
        default=50000, min=1000, soft_max=3000000, max=3000000, step=100,
        options={'ANIMATABLE'}, update=update_felt_render_density_cb)
    bpy.types.Object.fbp_felt_viewport_percentage = FloatProperty(
        name="Viewport %", description="Fraction of the render strand count displayed in the viewport",
        default=0.0025, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_felt_viewport_percentage_cb)
    bpy.types.Object.fbp_felt_fuzz_length = FloatProperty(description="Length of generated Felt Fuzz strands measured in scene units. Longer strands create softer wool but cost more to evaluate and render.",
        name="Fuzz Length", default=0.04, min=0.0, soft_max=0.5, max=10.0,
        precision=4, subtype='DISTANCE', options={'ANIMATABLE'}, update=update_felt_fuzz_length_cb)
    bpy.types.Object.fbp_felt_subdivisions = IntProperty(
        name="Subdivisions", description="Number of points along every strand; increase for smooth, tightly curled wool",
        default=3, min=2, soft_max=24, max=64, options={'ANIMATABLE'}, update=update_felt_subdivisions_cb)
    bpy.types.Object.fbp_felt_curl_amount = FloatProperty(
        name="Curl Amount", description="Number and intensity of curls along each strand",
        default=1.0, min=0.0, soft_max=5.0, max=12.0, precision=3,
        options={'ANIMATABLE'}, update=update_felt_curl_amount_cb)
    bpy.types.Object.fbp_felt_fuzz_radius = FloatProperty(description="Radius of each generated Felt Fuzz strand. Very small values create fine fibers; larger values produce thick yarn-like strands.",
        name="Fuzz Radius", default=0.0005, min=0.00001, soft_min=0.0005,
        soft_max=0.05, max=1.0, precision=6, subtype='DISTANCE', options={'ANIMATABLE'},
        update=update_felt_fuzz_radius_cb)
    bpy.types.Object.fbp_felt_seed = IntProperty(description="Deterministic random seed controlling Felt Fuzz strand placement and variation. The same value reproduces the same result.",
        name="Seed", default=0, min=0, max=2147483647, options={'ANIMATABLE'}, update=update_felt_seed_cb)
    bpy.types.Object.fbp_felt_alpha_threshold = FloatProperty(description="Minimum source alpha required to generate Felt Fuzz. Increase this value to keep fibers away from soft or partially transparent edges.", name="Alpha Threshold", default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_felt_alpha_threshold_cb)
    bpy.types.Object.fbp_felt_alpha_resolution = IntProperty(name="Alpha Resolution", description="Subdivision detail used only to sample the image alpha for fiber placement", default=2, min=2, max=6, update=update_felt_alpha_resolution_cb)

    bpy.types.Object.fbp_wind_subdivision = IntProperty(description="Mesh subdivision level used by Wind Bender. Higher values bend more smoothly but increase viewport and render evaluation time.", name="Subdivision", default=4, min=0, max=6, update=update_wind_subdivision_cb)
    bpy.types.Object.fbp_wind_stepped = IntProperty(description="Number of frames each Wind Bender deformation state is held. Set to 1 for continuous per-frame motion.", name="Stepped", default=1, min=1, soft_max=24, update=update_wind_stepped_cb)

    # 4.9 Geometry effect quality contract reference implementation.
    bpy.types.Object.fbp_mesh_ripple_viewport_subdivision = IntProperty(
        name="Viewport Subdivision", description="Subdivision detail used for this effect in the interactive viewport. Lower values improve editing speed while render detail remains independent.",
        default=4, min=0, max=7, update=update_mesh_ripple_viewport_subdivision_cb)
    bpy.types.Object.fbp_mesh_ripple_playback_subdivision = IntProperty(
        name="Playback Subdivision", description="Temporary mesh detail used during timeline playback",
        default=2, min=0, max=7, update=update_mesh_ripple_playback_subdivision_cb)
    bpy.types.Object.fbp_mesh_ripple_render_subdivision = IntProperty(
        name="Render Subdivision", description="Mesh detail temporarily used for final rendering",
        default=5, min=0, max=7, update=update_mesh_ripple_render_subdivision_cb)
    bpy.types.Object.fbp_mesh_ripple_direction = EnumProperty(description="Direction in which Mesh Ripple waves travel across the plane: local horizontal, local vertical or radially from the center.",
        name="Direction", items=(('X', "Horizontal", "Waves travel along local X"),
                                  ('Y', "Vertical", "Waves travel along local Y"),
                                  ('RADIAL', "Radial", "Waves expand from the plane center")),
        default='X', update=update_mesh_ripple_direction_cb)
    bpy.types.Object.fbp_mesh_ripple_amplitude = FloatProperty(description="Maximum distance Mesh Ripple displaces the plane away from its original surface.",
        name="Amplitude", default=0.08, min=0.0, soft_max=1.0, max=10.0,
        subtype='DISTANCE', precision=4, options={'ANIMATABLE'}, update=update_mesh_ripple_amplitude_cb)
    bpy.types.Object.fbp_mesh_ripple_frequency = FloatProperty(description="Number and density of Mesh Ripple waves across the plane. Higher values create tighter, more frequent ripples.",
        name="Frequency", default=3.0, min=0.0, soft_max=20.0, max=100.0,
        precision=3, options={'ANIMATABLE'}, update=update_mesh_ripple_frequency_cb)
    bpy.types.Object.fbp_mesh_ripple_speed = FloatProperty(description="Temporal speed of Mesh Ripple animation. Negative values reverse wave movement; zero freezes the phase.",
        name="Speed", default=1.0, soft_min=-10.0, soft_max=10.0, precision=3,
        options={'ANIMATABLE'}, update=update_mesh_ripple_speed_cb)
    bpy.types.Object.fbp_mesh_ripple_phase = FloatProperty(description="Manual angular phase offset for Mesh Ripple. Animate this value for direct, keyframe-controlled wave motion.",
        name="Phase", default=0.0, soft_min=-6.283185, soft_max=6.283185,
        subtype='ANGLE', options={'ANIMATABLE'}, update=update_mesh_ripple_phase_cb)
    bpy.types.Object.fbp_mesh_ripple_stepped = IntProperty(
        name="Stepped", description="Hold each deformation pose for this many frames",
        default=1, min=1, soft_max=24, max=1000, options={'ANIMATABLE'}, update=update_mesh_ripple_stepped_cb)
    bpy.types.Object.fbp_mesh_ripple_pin_borders = FloatProperty(
        name="Pin Borders", description="Strength used to pin the original plane border while the effect deforms the interior, helping preserve the silhouette and neighboring alignment.",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'}, update=update_mesh_ripple_pin_borders_cb)
    bpy.types.Object.fbp_mesh_ripple_border_falloff = FloatProperty(
        name="Border Falloff", description="Width of the soft transition between pinned border vertices and fully deformed interior geometry.",
        default=0.15, min=0.001, soft_max=0.5, max=1.0, subtype='FACTOR',
        options={'ANIMATABLE'}, update=update_mesh_ripple_border_falloff_cb)

    # 4.9.2 Paper Curl uses the shared Geometry Nodes quality contract.
    bpy.types.Object.fbp_paper_curl_viewport_subdivision = IntProperty(
        name="Viewport Subdivision", description="Subdivision detail used for this effect in the interactive viewport. Lower values improve editing speed while render detail remains independent.",
        default=4, min=0, max=7, update=update_paper_curl_viewport_subdivision_cb)
    bpy.types.Object.fbp_paper_curl_playback_subdivision = IntProperty(
        name="Playback Subdivision", description="Temporary mesh detail used during timeline playback",
        default=2, min=0, max=7, update=update_paper_curl_playback_subdivision_cb)
    bpy.types.Object.fbp_paper_curl_render_subdivision = IntProperty(
        name="Render Subdivision", description="Mesh detail temporarily used for final rendering",
        default=5, min=0, max=7, update=update_paper_curl_render_subdivision_cb)
    bpy.types.Object.fbp_paper_curl_edge = EnumProperty(description="Choose the plane edge from which Paper Curl begins. Progress moves the curled region inward from this side.",
        name="Curl Edge", items=(('LEFT', "Left", "Curl inward from the left edge"),
                                  ('RIGHT', "Right", "Curl inward from the right edge"),
                                  ('BOTTOM', "Bottom", "Curl inward from the bottom edge"),
                                  ('TOP', "Top", "Curl inward from the top edge")),
        default='TOP', update=update_paper_curl_edge_cb)
    bpy.types.Object.fbp_paper_curl_progress = FloatProperty(
        name="Progress", description="How far the curled region travels across the plane",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_paper_curl_progress_cb)
    bpy.types.Object.fbp_paper_curl_angle = FloatProperty(description="Total rotation applied to the curled Paper edge. Larger values roll the sheet farther around the curl radius.",
        name="Curl Angle", default=2.35619449, min=0.0, max=6.28318531, subtype='ANGLE',
        options={'ANIMATABLE'}, update=update_paper_curl_angle_cb)
    bpy.types.Object.fbp_paper_curl_radius = FloatProperty(description="Radius of the Paper Curl bend. Small values create a tight fold; large values create a broad, gentle roll.",
        name="Curl Radius", default=0.15, min=0.0, soft_max=1.0, max=10.0,
        subtype='DISTANCE', precision=4, options={'ANIMATABLE'}, update=update_paper_curl_radius_cb)
    bpy.types.Object.fbp_paper_curl_width = FloatProperty(
        name="Curl Width", description="Width of the transition from flat paper to the curled edge",
        default=0.28, min=0.001, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_paper_curl_width_cb)
    bpy.types.Object.fbp_paper_curl_lift = FloatProperty(
        name="Lift", description="Extra displacement applied near the Paper Curl edge, increasing separation from the original plane without changing curl direction.",
        default=0.02, soft_min=-0.5, soft_max=0.5, max=10.0, min=-10.0,
        subtype='DISTANCE', precision=4, options={'ANIMATABLE'}, update=update_paper_curl_lift_cb)
    bpy.types.Object.fbp_paper_curl_reverse = BoolProperty(
        name="Reverse Curl", description="Curl behind the plane instead of toward its local front",
        default=False, options={'ANIMATABLE'}, update=update_paper_curl_reverse_cb)

    # Reusable alpha-to-geometry contract reference effect.
    bpy.types.Object.fbp_cutout_outline_viewport_resolution = IntProperty(
        name="Viewport Alpha Detail", description="Subdivision level used to trace the alpha silhouette while editing",
        default=4, min=0, max=8, update=update_cutout_outline_viewport_resolution_cb)
    bpy.types.Object.fbp_cutout_outline_playback_resolution = IntProperty(
        name="Playback Alpha Detail", description="Temporary alpha tracing detail used during timeline playback",
        default=2, min=0, max=8, update=update_cutout_outline_playback_resolution_cb)
    bpy.types.Object.fbp_cutout_outline_render_resolution = IntProperty(
        name="Render Alpha Detail", description="Temporary alpha tracing detail used for final rendering",
        default=6, min=0, max=8, update=update_cutout_outline_render_resolution_cb)
    bpy.types.Object.fbp_cutout_outline_alpha_threshold = FloatProperty(
        name="Alpha Threshold", description="Pixels below this alpha value are excluded from the cutout silhouette",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_cutout_outline_alpha_threshold_cb)
    bpy.types.Object.fbp_cutout_outline_width = FloatProperty(
        name="Outline Width", description="World-space radius of the generated Cutout Outline geometry. Larger values create a thicker visible border around the source alpha silhouette.",
        default=0.012, min=0.00001, soft_max=0.1, max=10.0, subtype='DISTANCE', precision=5,
        options={'ANIMATABLE'}, update=update_cutout_outline_width_cb)
    bpy.types.Object.fbp_cutout_outline_offset = FloatProperty(
        name="Offset", description="Move the outline along the plane local Z axis",
        default=0.001, min=-10.0, max=10.0, soft_min=-0.1, soft_max=0.1,
        subtype='DISTANCE', precision=5, options={'ANIMATABLE'}, update=update_cutout_outline_offset_cb)
    bpy.types.Object.fbp_cutout_outline_color = FloatVectorProperty(description="RGBA color assigned to the generated Cutout Outline geometry.",
        name="Outline Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.02, 0.02, 0.02, 1.0), update=update_cutout_outline_color_cb)


    # Camera-space foundation reference effect.
    bpy.types.Object.fbp_camera_scale_lock_reference_distance = FloatProperty(
        name="Reference Distance",
        description="Camera-space depth at which the plane keeps its current apparent size",
        default=10.0, min=0.0001, soft_max=1000.0, max=1000000.0,
        precision=4, subtype='DISTANCE', options={'ANIMATABLE'},
        update=update_camera_scale_lock_reference_distance_cb)
    bpy.types.Object.fbp_camera_scale_lock_reference_lens = FloatProperty(
        name="Reference Lens",
        description="Focal length captured with the reference camera depth",
        default=50.0, min=0.1, soft_max=300.0, max=10000.0,
        precision=2, options={'ANIMATABLE'},
        update=update_camera_scale_lock_reference_lens_cb)
    bpy.types.Object.fbp_camera_scale_lock_reference_sensor_width = FloatProperty(
        name="Reference Sensor Width",
        description="Camera sensor width captured with the reference camera depth",
        default=36.0, min=0.1, soft_max=70.0, max=1000.0,
        precision=2, options={'ANIMATABLE'},
        update=update_camera_scale_lock_reference_sensor_width_cb)
    bpy.types.Object.fbp_camera_scale_lock_influence = FloatProperty(
        name="Influence",
        description="Blend between the original size and full projection-aware compensation",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'},
        update=update_camera_scale_lock_influence_cb)

    # 4.9.7 stabilized camera-space vector contract reference effect.
    bpy.types.Object.fbp_camera_billboard_mode = EnumProperty(description="Choose how the plane automatically faces the camera: full facing, axis-constrained facing or disabled behavior depending on the selected mode.",
        name="Facing Mode",
        items=(('FULL', "Full", "Face the camera on both local axes"),
               ('HORIZONTAL', "Horizontal", "Rotate only across the local horizontal axis"),
               ('VERTICAL', "Vertical", "Rotate only across the local vertical axis")),
        default='FULL', update=update_camera_billboard_mode_cb)
    bpy.types.Object.fbp_camera_billboard_flip = BoolProperty(
        name="Flip", description="Flip the generated geometry orientation and normals when the effect faces away from the expected camera or lighting direction.",
        default=False, options={'ANIMATABLE'}, update=update_camera_billboard_flip_cb)
    bpy.types.Object.fbp_camera_billboard_offset = FloatProperty(
        name="Camera Offset", description="Move generated geometry toward or away from the camera",
        default=0.0, min=-10000.0, max=10000.0, soft_min=-1.0, soft_max=1.0,
        subtype='DISTANCE', precision=4, options={'ANIMATABLE'}, update=update_camera_billboard_offset_cb)

    bpy.types.Object.fbp_thickness_viewport_pixels_x = IntProperty(
        name="Viewport Alpha Pixels X", description="Exact horizontal alpha samples used by Extrude while editing",
        default=128, min=1, soft_max=1024, max=4096, update=update_thickness_viewport_pixels_x_cb)
    bpy.types.Object.fbp_thickness_viewport_pixels_y = IntProperty(
        name="Viewport Alpha Pixels Y", description="Exact vertical alpha samples used by Extrude while editing",
        default=128, min=1, soft_max=1024, max=4096, update=update_thickness_viewport_pixels_y_cb)
    bpy.types.Object.fbp_thickness_playback_pixels_x = IntProperty(
        name="Playback Alpha Pixels X", description="Exact horizontal alpha samples temporarily used by Extrude during playback",
        default=64, min=1, soft_max=1024, max=4096, update=update_thickness_playback_pixels_x_cb)
    bpy.types.Object.fbp_thickness_playback_pixels_y = IntProperty(
        name="Playback Alpha Pixels Y", description="Exact vertical alpha samples temporarily used by Extrude during playback",
        default=64, min=1, soft_max=1024, max=4096, update=update_thickness_playback_pixels_y_cb)
    bpy.types.Object.fbp_thickness_render_pixels_x = IntProperty(
        name="Render Alpha Pixels X", description="Exact horizontal alpha samples used by Extrude for final rendering",
        default=256, min=1, soft_max=2048, max=4096, update=update_thickness_render_pixels_x_cb)
    bpy.types.Object.fbp_thickness_render_pixels_y = IntProperty(
        name="Render Alpha Pixels Y", description="Exact vertical alpha samples used by Extrude for final rendering",
        default=256, min=1, soft_max=2048, max=4096, update=update_thickness_render_pixels_y_cb)
    bpy.types.Object.fbp_thickness_grid_mode = EnumProperty(
        name="Extrude Grid Mode",
        description="Derive Pixels Y from the plane aspect ratio or use an exact X by Y alpha grid",
        items=(
            ('AUTO', "Auto Height", "Set Pixels X and derive Pixels Y so Extrude cells remain square", 'FULLSCREEN_ENTER', 0),
            ('EXACT', "Exact Grid", "Enter independent Pixels X and Pixels Y values", 'MESH_GRID', 1),
        ),
        default='AUTO', update=update_thickness_grid_mode_cb)
    bpy.types.Object.fbp_thickness_follow_pixelate = BoolProperty(
        name="Follow Pixelate",
        description="When Pixelate is present, use its effective X by Y grid for the Extrude silhouette",
        default=True, update=update_thickness_follow_pixelate_cb)
    bpy.types.Object.fbp_thickness_amount = FloatProperty(description="Depth of the Extrude side walls. Zero removes the generated volume.", name="Thickness", default=0.02, min=0.0, soft_max=0.25, max=10.0, precision=4, subtype='DISTANCE', options={'ANIMATABLE'}, update=update_thickness_amount_cb)
    bpy.types.Object.fbp_thickness_direction = FloatProperty(name="Direction", description="-1 extrudes behind the plane; +1 extrudes toward local front", default=-1.0, min=-1.0, max=1.0, options={'ANIMATABLE'}, update=update_thickness_direction_cb)
    bpy.types.Object.fbp_thickness_side_material = PointerProperty(description="Optional material assigned to Extrude side faces. Leave empty to use the side color instead.", name="Side Material", type=bpy.types.Material, update=update_thickness_side_material_cb)
    bpy.types.Object.fbp_thickness_side_color = FloatVectorProperty(description="RGBA fallback color used on Extrude side faces when no custom material is assigned.", name="Side Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.18, 0.12, 0.08, 1.0), update=update_thickness_side_color_cb)
    bpy.types.Object.fbp_thickness_use_plane_colors = BoolProperty(
        name="Use Plane Colors",
        description="Use the animated plane material on Extrude side faces so their colors follow the current image or pixel-art frame",
        default=False,
        update=update_thickness_use_plane_colors_cb,
    )
    bpy.types.Object.fbp_thickness_alpha_threshold = FloatProperty(description="Minimum source alpha included in the Extrude silhouette. Increase to remove translucent edge fringes.", name="Alpha Threshold", default=0.05, min=0.0, max=1.0, subtype='FACTOR', options={'ANIMATABLE'}, update=update_thickness_alpha_threshold_cb)

    bpy.types.Object.fbp_infinite_rotation_speed = FloatProperty(name="Speed", description="Automatic rotation speed in degrees per timeline frame. Negative values reverse direction and zero produces no time-based rotation.", default=1.0, min=0.0, soft_max=30.0, precision=3, update=update_infinite_rotation_speed_cb)
    bpy.types.Object.fbp_infinite_rotation_direction = EnumProperty(description="Direction of automatic Infinite Rotation around the configured axis.", name="Direction", items=(('RIGHT', "Clockwise", "Rotate clockwise"), ('LEFT', "Counter-clockwise", "Rotate counter-clockwise")), default='RIGHT', update=update_infinite_rotation_direction_cb)
    bpy.types.Object.fbp_infinite_rotation_stepped = IntProperty(description="Number of frames each Infinite Rotation angle is held. Set to 1 for smooth motion or higher values for stepped animation.", name="Stepped", default=1, min=1, soft_max=24, update=update_infinite_rotation_stepped_cb)
    bpy.types.Object.fbp_infinite_rotation_offset = FloatProperty(description="Manual angular offset added to Infinite Rotation without changing its speed or direction.", name="Offset (°)", default=0.0, soft_min=-360.0, soft_max=360.0, precision=2, update=update_infinite_rotation_offset_cb)

    # Shader effects
    bpy.types.Object.fbp_uv_distortion_scale = FloatProperty(description="Spatial scale of the procedural noise used to distort image UV coordinates. Higher values create smaller distortion features.",
        name="Noise Scale", default=10.0, min=0.001, soft_max=100.0, precision=3, update=update_uv_distortion_scale_cb)
    bpy.types.Object.fbp_uv_distortion_amount = FloatProperty(description="Strength of UV displacement applied to the image texture. Zero preserves the original mapping.",
        name="Distortion Amount", default=0.05, soft_min=-1.0, soft_max=1.0, precision=3, update=update_uv_distortion_amount_cb)
    bpy.types.Object.fbp_pixelate_grid_mode = EnumProperty(
        name="Pixel Grid Mode",
        description="Choose whether Pixelate derives the vertical cell count from the plane aspect ratio or uses an exact width-by-height grid",
        items=(
            ('AUTO', "Auto Height", "Set the horizontal pixel count and derive the vertical count so cells remain square", 'FULLSCREEN_ENTER', 0),
            ('EXACT', "Exact Grid", "Enter an explicit pixel grid such as 16 by 10 or 1920 by 1080", 'MESH_GRID', 1),
        ),
        default='AUTO', update=update_pixelate_grid_mode_cb)
    bpy.types.Object.fbp_pixelate_resolution = IntProperty(
        name="Pixels X", description="Horizontal number of pixel cells. Use small values such as 16 for chunky pixel art or source-like values such as 1920 for a fine grid",
        default=64, min=1, soft_max=2048, max=8192, update=update_pixelate_resolution_cb)
    bpy.types.Object.fbp_pixelate_height = IntProperty(
        name="Pixels Y", description="Vertical number of pixel cells used in Exact Grid mode, for example 10 in a 16 by 10 grid or 1080 in a 1920 by 1080 grid",
        default=36, min=1, soft_max=2048, max=8192, update=update_pixelate_height_cb)
    bpy.types.Object.fbp_depth_blur_mode = EnumProperty(
        name="Blur Mode",
        description="Use a fixed manual radius or derive the radius from camera-space distance to the focus plane",
        items=(
            ('MANUAL', "Manual", "Use the same blur radius for the complete plane", 'MOD_SMOOTH', 0),
            ('DEPTH', "Depth", "Increase blur as the plane moves away from the focus distance", 'CAMERA_DATA', 1),
        ),
        default='MANUAL', update=update_depth_blur_mode_cb)
    bpy.types.Object.fbp_depth_blur_manual_radius = FloatProperty(
        name="Manual Radius", description="Blur radius in source-image pixels used in Manual mode",
        default=4.0, min=0.0, soft_max=32.0, max=256.0, precision=2,
        update=update_depth_blur_manual_radius_cb)
    bpy.types.Object.fbp_depth_blur_max_radius = FloatProperty(
        name="Maximum Radius", description="Maximum source-image blur radius reached in Depth mode",
        default=16.0, min=0.0, soft_max=64.0, max=256.0, precision=2,
        update=update_depth_blur_max_radius_cb)
    bpy.types.Object.fbp_depth_blur_use_camera_focus = BoolProperty(
        name="Use Camera Focus", description="Read Focus Distance or the Focus Object from the active scene camera",
        default=True, update=update_depth_blur_use_camera_focus_cb)
    bpy.types.Object.fbp_depth_blur_focus_distance = FloatProperty(
        name="Focus Distance", description="Camera-space distance that remains in focus when Camera Focus is disabled",
        default=10.0, min=0.0, soft_max=100.0, max=1000000.0, subtype='DISTANCE', precision=3,
        update=update_depth_blur_focus_distance_cb)
    bpy.types.Object.fbp_depth_blur_focus_range = FloatProperty(
        name="Focus Range", description="Distance around the focus plane that remains sharp",
        default=0.25, min=0.0, soft_max=10.0, max=1000000.0, subtype='DISTANCE', precision=3,
        update=update_depth_blur_focus_range_cb)
    bpy.types.Object.fbp_depth_blur_falloff = FloatProperty(
        name="Falloff", description="Distance required to reach the maximum blur outside the focus range",
        default=5.0, min=0.001, soft_max=50.0, max=1000000.0, subtype='DISTANCE', precision=3,
        update=update_depth_blur_falloff_cb)
    bpy.types.Object.fbp_depth_blur_near_strength = FloatProperty(
        name="Near Strength", description="Multiplier applied to layers closer than the focus plane",
        default=1.0, min=0.0, max=2.0, soft_max=1.0, subtype='FACTOR',
        update=update_depth_blur_near_strength_cb)
    bpy.types.Object.fbp_depth_blur_far_strength = FloatProperty(
        name="Far Strength", description="Multiplier applied to layers farther than the focus plane",
        default=1.0, min=0.0, max=2.0, soft_max=1.0, subtype='FACTOR',
        update=update_depth_blur_far_strength_cb)
    bpy.types.Object.fbp_alpha_matte_source = PointerProperty(
        name="Source Layer", description="Frame By Plane image or sequence whose alpha channel masks this layer. The source is sampled in normalized UV space",
        type=bpy.types.Object, poll=_fbp_mask_source_poll, update=update_alpha_matte_source_cb)
    bpy.types.Object.fbp_alpha_matte_factor = FloatProperty(
        name="Factor", description="Blend between the original layer alpha and the Alpha Matte result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_alpha_matte_factor_cb)
    bpy.types.Object.fbp_alpha_matte_invert = BoolProperty(
        name="Invert", description="Invert the source alpha before applying the matte",
        default=False, update=update_alpha_matte_invert_cb)
    bpy.types.Object.fbp_alpha_matte_use_source_transform = BoolProperty(
        name="Follow Source Transform",
        description="Project the matte through the source plane so its position, rotation and scale affect the target. Disable to sample both layers in normalized UV space",
        default=False, update=update_alpha_matte_use_source_transform_cb)
    bpy.types.Object.fbp_alpha_matte_source_display = EnumProperty(
        name="Source Display",
        description="Choose whether the source layer remains a normal rendered layer, works as a viewport-only guide, or stays hidden while still driving the matte",
        items=[
            ('NORMAL', "Normal", "Respect the source layer's normal viewport and render visibility"),
            ('GUIDE', "Guide", "Show the source in the viewport but hide it from final renders"),
            ('HIDDEN', "Hidden", "Hide the source in both viewport and render while keeping the matte active"),
        ],
        default='GUIDE', update=update_alpha_matte_source_display_cb)
    bpy.types.Object.fbp_alpha_matte_uv_offset_x = FloatProperty(
        name="Offset X", description="Move the sampled matte horizontally in UV space",
        default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_alpha_matte_uv_offset_x_cb)
    bpy.types.Object.fbp_alpha_matte_uv_offset_y = FloatProperty(
        name="Offset Y", description="Move the sampled matte vertically in UV space",
        default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_alpha_matte_uv_offset_y_cb)
    bpy.types.Object.fbp_alpha_matte_uv_scale_x = FloatProperty(
        name="Scale X", description="Scale the matte horizontally around its center; values above one make the matte larger",
        default=1.0, min=0.001, soft_max=4.0, max=1000.0, precision=3, update=update_alpha_matte_uv_scale_x_cb)
    bpy.types.Object.fbp_alpha_matte_uv_scale_y = FloatProperty(
        name="Scale Y", description="Scale the matte vertically around its center; values above one make the matte larger",
        default=1.0, min=0.001, soft_max=4.0, max=1000.0, precision=3, update=update_alpha_matte_uv_scale_y_cb)
    bpy.types.Object.fbp_alpha_matte_uv_rotation = FloatProperty(
        name="Rotation", description="Rotate the matte around the center of its sampled UV space",
        default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_alpha_matte_uv_rotation_cb)
    bpy.types.Object.fbp_luma_matte_source = PointerProperty(
        name="Source Layer", description="Frame By Plane image or sequence whose luminance masks this layer. The source is sampled in normalized UV space",
        type=bpy.types.Object, poll=_fbp_mask_source_poll, update=update_luma_matte_source_cb)
    bpy.types.Object.fbp_luma_matte_factor = FloatProperty(
        name="Factor", description="Blend between the original layer alpha and the Luma Matte result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_luma_matte_factor_cb)
    bpy.types.Object.fbp_luma_matte_invert = BoolProperty(
        name="Invert", description="Invert the luminance matte before applying it",
        default=False, update=update_luma_matte_invert_cb)
    bpy.types.Object.fbp_luma_matte_threshold = FloatProperty(
        name="Threshold", description="Luminance value used as the center of the matte transition",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_luma_matte_threshold_cb)
    bpy.types.Object.fbp_luma_matte_softness = FloatProperty(
        name="Softness", description="Width of the smooth luminance transition around Threshold",
        default=0.15, min=0.0, max=1.0, subtype='FACTOR', update=update_luma_matte_softness_cb)
    bpy.types.Object.fbp_luma_matte_use_source_transform = BoolProperty(
        name="Follow Source Transform",
        description="Project the matte through the source plane so its position, rotation and scale affect the target. Disable to sample both layers in normalized UV space",
        default=False, update=update_luma_matte_use_source_transform_cb)
    bpy.types.Object.fbp_luma_matte_source_display = EnumProperty(
        name="Source Display",
        description="Choose whether the source layer remains a normal rendered layer, works as a viewport-only guide, or stays hidden while still driving the matte",
        items=[
            ('NORMAL', "Normal", "Respect the source layer's normal viewport and render visibility"),
            ('GUIDE', "Guide", "Show the source in the viewport but hide it from final renders"),
            ('HIDDEN', "Hidden", "Hide the source in both viewport and render while keeping the matte active"),
        ],
        default='GUIDE', update=update_luma_matte_source_display_cb)
    bpy.types.Object.fbp_luma_matte_uv_offset_x = FloatProperty(
        name="Offset X", description="Move the sampled matte horizontally in UV space",
        default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_luma_matte_uv_offset_x_cb)
    bpy.types.Object.fbp_luma_matte_uv_offset_y = FloatProperty(
        name="Offset Y", description="Move the sampled matte vertically in UV space",
        default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_luma_matte_uv_offset_y_cb)
    bpy.types.Object.fbp_luma_matte_uv_scale_x = FloatProperty(
        name="Scale X", description="Scale the matte horizontally around its center; values above one make the matte larger",
        default=1.0, min=0.001, soft_max=4.0, max=1000.0, precision=3, update=update_luma_matte_uv_scale_x_cb)
    bpy.types.Object.fbp_luma_matte_uv_scale_y = FloatProperty(
        name="Scale Y", description="Scale the matte vertically around its center; values above one make the matte larger",
        default=1.0, min=0.001, soft_max=4.0, max=1000.0, precision=3, update=update_luma_matte_uv_scale_y_cb)
    bpy.types.Object.fbp_luma_matte_uv_rotation = FloatProperty(
        name="Rotation", description="Rotate the matte around the center of its sampled UV space",
        default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_luma_matte_uv_rotation_cb)
    bpy.types.Object.fbp_color_mask_color = FloatVectorProperty(
        name="Target Color", description="Source color selected by Color Mask",
        subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 1.0, 0.0, 1.0),
        update=update_color_mask_color_cb)
    bpy.types.Object.fbp_color_mask_tolerance = FloatProperty(
        name="Tolerance", description="Maximum RGB distance treated as a color match",
        default=0.12, min=0.0, max=1.732, soft_max=1.0, subtype='FACTOR',
        update=update_color_mask_tolerance_cb)
    bpy.types.Object.fbp_color_mask_softness = FloatProperty(
        name="Softness", description="Smooth transition outside the Color Mask tolerance",
        default=0.08, min=0.0, max=1.0, subtype='FACTOR',
        update=update_color_mask_softness_cb)
    bpy.types.Object.fbp_color_mask_factor = FloatProperty(
        name="Factor", description="Blend between the unmasked result and Color Mask",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_color_mask_factor_cb)
    bpy.types.Object.fbp_color_mask_invert = BoolProperty(
        name="Invert", description="Use colors outside the selected range",
        default=False, update=update_color_mask_invert_cb)
    bpy.types.Object.fbp_gradient_mask_type = EnumProperty(
        name="Type", description="Gradient shape used by the mask",
        items=[
            ('LINEAR', "Linear", "Directional linear gradient"),
            ('RADIAL', "Radial", "Circular gradient around the mask center"),
        ], default='LINEAR', update=update_gradient_mask_type_cb)
    bpy.types.Object.fbp_gradient_mask_center_x = FloatProperty(
        name="Center X", description="Horizontal center of the Gradient Mask in UV space",
        default=0.5, soft_min=-1.0, soft_max=2.0, precision=3,
        update=update_gradient_mask_center_x_cb)
    bpy.types.Object.fbp_gradient_mask_center_y = FloatProperty(
        name="Center Y", description="Vertical center of the Gradient Mask in UV space",
        default=0.5, soft_min=-1.0, soft_max=2.0, precision=3,
        update=update_gradient_mask_center_y_cb)
    bpy.types.Object.fbp_gradient_mask_scale = FloatProperty(
        name="Scale", description="Scale the Gradient Mask around its center",
        default=1.0, min=0.001, soft_max=10.0, max=1000.0, precision=3,
        update=update_gradient_mask_scale_cb)
    bpy.types.Object.fbp_gradient_mask_angle = FloatProperty(
        name="Angle", description="Rotate a Linear Gradient Mask around its center",
        default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE',
        update=update_gradient_mask_angle_cb)
    bpy.types.Object.fbp_gradient_mask_position = FloatProperty(
        name="Position", description="Position of the gradient transition",
        default=0.5, soft_min=-1.0, soft_max=2.0, precision=3,
        update=update_gradient_mask_position_cb)
    bpy.types.Object.fbp_gradient_mask_feather = FloatProperty(
        name="Feather", description="Width of the Gradient Mask transition",
        default=0.2, min=0.0, soft_max=1.0, max=2.0, subtype='FACTOR',
        update=update_gradient_mask_feather_cb)
    bpy.types.Object.fbp_gradient_mask_factor = FloatProperty(
        name="Factor", description="Blend between the unmasked result and Gradient Mask",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_gradient_mask_factor_cb)
    bpy.types.Object.fbp_gradient_mask_invert = BoolProperty(
        name="Invert", description="Invert the Gradient Mask",
        default=False, update=update_gradient_mask_invert_cb)
    bpy.types.Object.fbp_noise_mask_scale = FloatProperty(
        name="Scale", description="Spatial frequency of the Noise Mask",
        default=6.0, min=0.001, soft_max=100.0, max=1000.0, precision=3,
        update=update_noise_mask_scale_cb)
    bpy.types.Object.fbp_noise_mask_detail = FloatProperty(
        name="Detail", description="Fractal detail of the Noise Mask",
        default=3.0, min=0.0, max=15.0, precision=2,
        update=update_noise_mask_detail_cb)
    bpy.types.Object.fbp_noise_mask_roughness = FloatProperty(
        name="Roughness", description="Contribution of fine Noise Mask octaves",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        update=update_noise_mask_roughness_cb)
    bpy.types.Object.fbp_noise_mask_threshold = FloatProperty(
        name="Threshold", description="Noise value used as the mask cutoff",
        default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        update=update_noise_mask_threshold_cb)
    bpy.types.Object.fbp_noise_mask_softness = FloatProperty(
        name="Softness", description="Width of the smooth transition around the Noise Mask threshold",
        default=0.15, min=0.0, max=1.0, subtype='FACTOR',
        update=update_noise_mask_softness_cb)
    bpy.types.Object.fbp_noise_mask_seed = FloatProperty(
        name="Seed", description="Fourth-dimensional coordinate used to animate the Noise Mask",
        default=0.0, soft_min=-1000.0, soft_max=1000.0, precision=3,
        update=update_noise_mask_seed_cb)
    bpy.types.Object.fbp_noise_mask_factor = FloatProperty(
        name="Factor", description="Blend between the unmasked result and Noise Mask",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        update=update_noise_mask_factor_cb)
    bpy.types.Object.fbp_noise_mask_invert = BoolProperty(
        name="Invert", description="Invert the Noise Mask",
        default=False, update=update_noise_mask_invert_cb)
    bpy.types.Object.fbp_clipping_mask_source = PointerProperty(
        name="Source Layer", description="Layer directly below this one, used automatically as the clipping alpha source",
        type=bpy.types.Object, poll=_fbp_mask_source_poll, update=update_clipping_mask_source_cb)
    bpy.types.Object.fbp_clipping_mask_factor = FloatProperty(
        name="Factor", description="Blend between the original layer alpha and the clipping result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_clipping_mask_factor_cb)
    bpy.types.Object.fbp_clipping_mask_invert = BoolProperty(
        name="Invert", description="Invert the alpha of the layer below before clipping",
        default=False, update=update_clipping_mask_invert_cb)
    bpy.types.Object.fbp_clipping_mask_use_source_transform = BoolProperty(
        name="Use Source Transform",
        description="Project through the source plane so its position, rotation and scale affect the clipping result. Disable for Procreate-style normalized clipping",
        default=False, update=update_clipping_mask_use_source_transform_cb)
    bpy.types.Object.fbp_clipping_mask_uv_offset_x = FloatProperty(
        name="Offset X", description="Move the sampled clipping alpha horizontally in UV space",
        default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_clipping_mask_uv_offset_x_cb)
    bpy.types.Object.fbp_clipping_mask_uv_offset_y = FloatProperty(
        name="Offset Y", description="Move the sampled clipping alpha vertically in UV space",
        default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_clipping_mask_uv_offset_y_cb)
    bpy.types.Object.fbp_clipping_mask_uv_scale_x = FloatProperty(
        name="Scale X", description="Scale the clipping alpha horizontally around its center",
        default=1.0, min=0.001, soft_max=4.0, max=1000.0, precision=3, update=update_clipping_mask_uv_scale_x_cb)
    bpy.types.Object.fbp_clipping_mask_uv_scale_y = FloatProperty(
        name="Scale Y", description="Scale the clipping alpha vertically around its center",
        default=1.0, min=0.001, soft_max=4.0, max=1000.0, precision=3, update=update_clipping_mask_uv_scale_y_cb)
    bpy.types.Object.fbp_clipping_mask_uv_rotation = FloatProperty(
        name="Rotation", description="Rotate the clipping alpha around the center of its sampled UV space",
        default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_clipping_mask_uv_rotation_cb)

    bpy.types.Object.fbp_square_mask_object = PointerProperty(
        name="Mask Shape", description="Editable Square Shape Mask helper. Select it and enter Edit Mode to change the silhouette",
        type=bpy.types.Object, update=update_square_mask_object_cb)
    bpy.types.Object.fbp_square_mask_factor = FloatProperty(
        name="Factor", description="Blend between the original alpha and the Square Shape Mask result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_square_mask_factor_cb)
    bpy.types.Object.fbp_square_mask_invert = BoolProperty(
        name="Invert", description="Invert the Square Shape Mask", default=False, update=update_square_mask_invert_cb)
    bpy.types.Object.fbp_square_mask_feather = FloatProperty(
        name="Feather", description="Soften the editable Square Shape Mask edge",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_square_mask_feather_cb)
    bpy.types.Object.fbp_square_mask_follow_bounds = BoolProperty(
        name="Follow Layer Bounds", description="Preserve the helper's normalized position and size when Crop or Extend changes the layer bounds",
        default=True, update=update_square_mask_follow_bounds_cb)
    bpy.types.Object.fbp_square_mask_show_helper = BoolProperty(
        name="Show Mask Shape", description="Show the Square helper while this layer or its helper is selected",
        default=True, update=update_square_mask_runtime_cb)
    bpy.types.Object.fbp_square_mask_lock_to_plane = BoolProperty(
        name="Lock to Plane", description="Keep G movement on the layer plane by locking local depth and off-plane rotation",
        default=True, update=update_square_mask_runtime_cb)

    bpy.types.Object.fbp_circle_mask_object = PointerProperty(
        name="Mask Shape", description="Editable Circle Shape Mask helper. Select it and enter Edit Mode to change the silhouette",
        type=bpy.types.Object, update=update_circle_mask_object_cb)
    bpy.types.Object.fbp_circle_mask_factor = FloatProperty(
        name="Factor", description="Blend between the original alpha and the Circle Shape Mask result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_circle_mask_factor_cb)
    bpy.types.Object.fbp_circle_mask_invert = BoolProperty(
        name="Invert", description="Invert the Circle Shape Mask", default=False, update=update_circle_mask_invert_cb)
    bpy.types.Object.fbp_circle_mask_feather = FloatProperty(
        name="Feather", description="Soften the editable Circle Shape Mask edge",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_circle_mask_feather_cb)
    bpy.types.Object.fbp_circle_mask_follow_bounds = BoolProperty(
        name="Follow Layer Bounds", description="Preserve the helper's normalized position and size when Crop or Extend changes the layer bounds",
        default=True, update=update_circle_mask_follow_bounds_cb)
    bpy.types.Object.fbp_circle_mask_show_helper = BoolProperty(
        name="Show Mask Shape", description="Show the Circle helper while this layer or its helper is selected",
        default=True, update=update_circle_mask_runtime_cb)
    bpy.types.Object.fbp_circle_mask_lock_to_plane = BoolProperty(
        name="Lock to Plane", description="Keep G movement on the layer plane by locking local depth and off-plane rotation",
        default=True, update=update_circle_mask_runtime_cb)

    bpy.types.Object.fbp_triangle_mask_object = PointerProperty(
        name="Mask Shape", description="Editable Triangle Shape Mask helper. Select it and enter Edit Mode to change the silhouette",
        type=bpy.types.Object, update=update_triangle_mask_object_cb)
    bpy.types.Object.fbp_triangle_mask_factor = FloatProperty(
        name="Factor", description="Blend between the original alpha and the Triangle Shape Mask result",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_triangle_mask_factor_cb)
    bpy.types.Object.fbp_triangle_mask_invert = BoolProperty(
        name="Invert", description="Invert the Triangle Shape Mask", default=False, update=update_triangle_mask_invert_cb)
    bpy.types.Object.fbp_triangle_mask_feather = FloatProperty(
        name="Feather", description="Soften the editable Triangle Shape Mask edge",
        default=0.05, min=0.0, max=1.0, subtype='FACTOR', update=update_triangle_mask_feather_cb)
    bpy.types.Object.fbp_triangle_mask_follow_bounds = BoolProperty(
        name="Follow Layer Bounds", description="Preserve the helper's normalized position and size when Crop or Extend changes the layer bounds",
        default=True, update=update_triangle_mask_follow_bounds_cb)
    bpy.types.Object.fbp_triangle_mask_show_helper = BoolProperty(
        name="Show Mask Shape", description="Show the Triangle helper while this layer or its helper is selected",
        default=True, update=update_triangle_mask_runtime_cb)
    bpy.types.Object.fbp_triangle_mask_lock_to_plane = BoolProperty(
        name="Lock to Plane", description="Keep G movement on the layer plane by locking local depth and off-plane rotation",
        default=True, update=update_triangle_mask_runtime_cb)
    bpy.types.Object.fbp_grain_strength = FloatProperty(description="Opacity and intensity of Film Grain layered over the source image.",
        name="Intensity", default=0.2, min=0.0, max=1.0, subtype='FACTOR', update=update_grain_strength_cb)
    bpy.types.Object.fbp_grain_scale = FloatProperty(description="Spatial size of Film Grain. Higher values create finer grain; lower values create larger visible noise clusters.",
        name="Grain Scale", default=180.0, min=0.01, soft_max=2000.0, precision=2, update=update_grain_scale_cb)
    bpy.types.Object.fbp_grain_seed = FloatProperty(description="Deterministic phase or seed controlling the Film Grain pattern. Animate it to make the grain evolve over time.",
        name="Animate (W)", default=0.0, soft_min=-100.0, soft_max=100.0, precision=3, update=update_grain_seed_cb)
    bpy.types.Object.fbp_digital_noise_luma = FloatProperty(
        name="Luminance Noise", description="Strength of luminance-only digital sensor noise added to the image. This simulates monochromatic high-ISO grain without color speckles.",
        default=0.12, min=0.0, max=1.0, subtype='FACTOR', update=update_digital_noise_luma_cb)
    bpy.types.Object.fbp_digital_noise_chroma = FloatProperty(
        name="Chroma Noise", description="Strength of independent RGB sensor noise. Higher values create colored speckles and can be more visually aggressive than monochromatic noise.",
        default=0.08, min=0.0, max=1.0, subtype='FACTOR', update=update_digital_noise_chroma_cb)
    bpy.types.Object.fbp_digital_noise_scale = FloatProperty(
        name="Noise Scale", description="Spatial scale of the digital noise pattern. Lower values produce larger blotches; higher values produce finer sensor-like grain.",
        default=500.0, min=1.0, soft_max=3000.0, max=10000.0, precision=1, update=update_digital_noise_scale_cb)
    bpy.types.Object.fbp_digital_noise_shadow_bias = FloatProperty(
        name="Shadow Bias", description="Bias that increases digital noise in shadows relative to highlights, approximating reduced signal quality in underexposed areas.",
        default=0.65, min=0.0, max=2.0, update=update_digital_noise_shadow_bias_cb)
    bpy.types.Object.fbp_digital_noise_seed = FloatProperty(
        name="Animate (W)", description="Temporal noise phase; animate or enable Evolve for moving sensor noise",
        default=0.0, soft_min=-100.0, soft_max=100.0, precision=3, update=update_digital_noise_seed_cb)
    bpy.types.Object.fbp_chroma_key_color = FloatVectorProperty(
        name="Key Color", description="Target RGBA key color removed by Chroma Key. Choose the screen color as closely as possible before adjusting tolerance and despill.",
        subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 1.0, 0.0, 1.0), update=update_chroma_key_color_cb)
    bpy.types.Object.fbp_chroma_key_tolerance = FloatProperty(
        name="Tolerance", description="Distance from the key color that becomes transparent",
        default=0.20, min=0.0, soft_max=1.0, max=1.732, update=update_chroma_key_tolerance_cb)
    bpy.types.Object.fbp_chroma_key_softness = FloatProperty(
        name="Softness", description="Soft transition width around the keyed color boundary. Increase it to reduce hard edges, but excessive values can erode the subject.",
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
    bpy.types.Object.fbp_halftone_dot_size = FloatProperty(description="Relative size of Halftone dots inside each sampling cell. Larger values make dots expand and merge sooner.",
        name="Dot Size", default=0.9, min=0.0, soft_max=1.2, max=1.5, update=update_halftone_dot_size_cb)
    bpy.types.Object.fbp_halftone_rotation = FloatProperty(description="Rotate the Halftone sampling grid to change the screen angle and moir\u00e9 direction.",
        name="Rotation", subtype='ANGLE', default=0.0, soft_min=-3.141593, soft_max=3.141593, update=update_halftone_rotation_cb)
    bpy.types.Object.fbp_halftone_contrast = FloatProperty(description="Contrast applied before Halftone dot generation. Higher values produce harder separation between large and small dots.",
        name="Contrast", default=1.4, min=0.0, soft_max=4.0, max=8.0, update=update_halftone_contrast_cb)
    bpy.types.Object.fbp_halftone_invert = BoolProperty(description="Invert luminance before generating Halftone dots, swapping dense dark regions with dense bright regions.",
        name="Invert", default=False, update=update_halftone_invert_cb)
    bpy.types.Object.fbp_halftone_shape = EnumProperty(
        name="Shape", description="Geometric shape used for Halftone cells. Shape changes the printed texture while luminance still controls cell coverage.",
        items=(("CIRCLE", "Circle", "Circular dots"), ("SQUARE", "Square", "Square cells"),
               ("DIAMOND", "Diamond", "Diamond-shaped cells"), ("LINE", "Line", "Parallel print lines")),
        default="CIRCLE", update=update_halftone_shape_cb)
    bpy.types.Object.fbp_halftone_use_source_color = BoolProperty(
        name="Use Source Color", description="Color Halftone cells from the source image. Disable it to use the custom foreground ink color instead.",
        default=True, update=update_halftone_use_source_color_cb)
    bpy.types.Object.fbp_halftone_foreground = FloatVectorProperty(description="RGBA ink color used for Halftone dots when source-color mode is disabled.",
        name="Ink Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_halftone_foreground_cb)
    bpy.types.Object.fbp_halftone_background = FloatVectorProperty(description="RGBA paper color shown between Halftone dots when the background is not transparent.",
        name="Paper Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0), update=update_halftone_background_cb)
    bpy.types.Object.fbp_halftone_transparent_background = BoolProperty(
        name="Transparent Background", description="Make the spaces between Halftone cells transparent instead of filling them with the configured background color.",
        default=False, update=update_halftone_transparent_background_cb)
    bpy.types.Object.fbp_dot_matrix_scale = FloatProperty(
        name="Cell Scale", description="Approximate number of Dot Matrix cells across the local plane width. Higher values increase detail and shader sampling frequency.",
        default=64.0, min=1.0, soft_max=500.0, max=2000.0, update=update_dot_matrix_scale_cb)
    bpy.types.Object.fbp_dot_matrix_dot_size = FloatProperty(description="Base diameter of Dot Matrix cells before luminance response and random size variation are applied.",
        name="Dot Size", default=0.85, min=0.0, soft_max=1.2, max=1.5, update=update_dot_matrix_dot_size_cb)
    bpy.types.Object.fbp_dot_matrix_spacing = FloatProperty(
        name="Spacing", description="Fraction of each Dot Matrix cell reserved as empty spacing. Higher values separate elements and make the pattern less dense.",
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
        name="Random Size", description="Amount of deterministic per-cell size variation applied to Dot Matrix elements. Zero keeps every cell uniform.",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_dot_matrix_random_size_cb)
    bpy.types.Object.fbp_dot_matrix_random_brightness = FloatProperty(
        name="Random Brightness", description="Amount of deterministic per-cell brightness variation applied to Dot Matrix elements without changing their source positions.",
        default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=update_dot_matrix_random_brightness_cb)
    bpy.types.Object.fbp_dot_matrix_seed = FloatProperty(
        name="Pattern Seed", description="Deterministic dot variation; animate or enable Evolve",
        default=0.0, soft_min=-100000.0, soft_max=100000.0, precision=0, update=update_dot_matrix_seed_cb)
    bpy.types.Object.fbp_dot_matrix_glow = FloatProperty(
        name="Glow", description="Soft anti-aliased edge around each dot; set to zero for a hard edge",
        default=0.04, min=0.0, soft_max=0.2, max=0.5, update=update_dot_matrix_glow_cb)
    bpy.types.Object.fbp_dot_matrix_use_source_color = BoolProperty(
        name="Use Source Color", description="Sample the source image color for each Dot Matrix element. Disable it to use the custom foreground light color.",
        default=True, update=update_dot_matrix_use_source_color_cb)
    bpy.types.Object.fbp_dot_matrix_foreground = FloatVectorProperty(description="RGBA color used for Dot Matrix lights when source-color mode is disabled.",
        name="Dot Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 0.65, 0.15, 1.0), update=update_dot_matrix_foreground_cb)
    bpy.types.Object.fbp_dot_matrix_background = FloatVectorProperty(description="RGBA background color shown behind Dot Matrix lights when transparency is disabled.",
        name="Background Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_dot_matrix_background_cb)
    bpy.types.Object.fbp_dot_matrix_transparent_background = BoolProperty(
        name="Transparent Background", description="Show only the dots and preserve transparent gaps",
        default=True, update=update_dot_matrix_transparent_background_cb)
    bpy.types.Object.fbp_dot_matrix_shape = EnumProperty(
        name="Shape", description="Geometry used for each Dot Matrix element: circle, square, diamond or horizontal bar. Luminance continues to control visible size.",
        items=(("CIRCLE", "Circle", "Circular lights"), ("SQUARE", "Square", "Square lights"),
               ("DIAMOND", "Diamond", "Diamond lights"), ("LINE", "Line", "Horizontal light bars")),
        default="CIRCLE", update=update_dot_matrix_shape_cb)
    bpy.types.Object.fbp_dot_matrix_min_size = FloatProperty(
        name="Minimum Size", description="Smallest Dot Matrix element size allowed after luminance mapping. Raise it to keep faint elements visible in dark areas.",
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
    bpy.types.Object.fbp_ascii_contrast = FloatProperty(description="Contrast used to map source luminance to Textellation glyph density. Higher values use the lightest and densest characters more aggressively.",
        name="Contrast", default=1.3, min=0.0, soft_max=4.0, max=8.0, update=update_ascii_contrast_cb)
    bpy.types.Object.fbp_ascii_invert = BoolProperty(description="Reverse the Textellation luminance mapping so bright areas use dense glyphs and dark areas use light glyphs.", name="Invert", default=False, update=update_ascii_invert_cb)
    bpy.types.Object.fbp_ascii_colorize = BoolProperty(
        name="Use Source Color", description="Color each glyph with the source image instead of Text Color",
        default=True, update=update_ascii_colorize_cb)
    bpy.types.Object.fbp_ascii_foreground = FloatVectorProperty(description="RGBA glyph color used by Textellation when source-color mode is disabled.",
        name="Text Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.1, 1.0, 0.2, 1.0), update=update_ascii_foreground_cb)
    bpy.types.Object.fbp_ascii_background = FloatVectorProperty(description="RGBA background color used by Textellation when transparent background is disabled.",
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

    bpy.types.Object.fbp_text_matrix_quality = EnumProperty(
        name="Quality", description="Quick viewport/render column presets; rows return to Auto",
        items=(("DRAFT", "Draft", "24 viewport / 48 render columns"),
               ("PREVIEW", "Preview", "48 viewport / 96 render columns"),
               ("FINAL", "Final", "72 viewport / 160 render columns"),
               ("CUSTOM", "Custom", "Use the manual column values")),
        default="PREVIEW", update=update_text_matrix_quality_cb)
    bpy.types.Object.fbp_text_matrix_viewport_columns = IntProperty(
        name="Viewport Columns", description="Number of real Text Matrix columns generated at viewport quality. Lower values improve interaction speed and do not change render-quality columns.",
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

    # Terminal-style Ascii effect based on Blender-Image-To-ASCII assets.
    bpy.types.Object.fbp_terminal_ascii_scale = FloatProperty(
        name="Cell Scale", description="Approximate number of terminal character cells placed across the local plane width. Higher values preserve more image detail but increase texture sampling frequency.",
        default=64.0, min=1.0, soft_max=300.0, max=1000.0, update=update_terminal_ascii_scale_cb)
    bpy.types.Object.fbp_terminal_ascii_contrast = FloatProperty(
        name="Contrast", description="Contrast applied before Terminal Ascii maps source luminance to fill glyph density. Higher values separate dark and bright character choices more strongly.",
        default=1.25, min=0.0, soft_max=4.0, max=8.0, update=update_terminal_ascii_contrast_cb)
    bpy.types.Object.fbp_terminal_ascii_invert = BoolProperty(
        name="Invert", description="Reverse Terminal Ascii density mapping so bright regions use dense glyphs and dark regions use sparse glyphs.",
        default=False, update=update_terminal_ascii_invert_cb)
    bpy.types.Object.fbp_terminal_ascii_fill_strength = FloatProperty(
        name="Fill Strength", description="Multiply the source-luminance contribution used to choose fill glyphs. Higher values favor denser terminal characters before thresholding.",
        default=1.0, min=0.0, soft_max=2.0, max=4.0, update=update_terminal_ascii_fill_strength_cb)
    bpy.types.Object.fbp_terminal_ascii_fill_threshold = FloatProperty(
        name="Fill Threshold", description="Threshold below which Terminal Ascii fill glyphs are suppressed, leaving more background or edge characters visible.",
        default=0.0, min=0.0, max=0.95, subtype='FACTOR', update=update_terminal_ascii_fill_threshold_cb)
    bpy.types.Object.fbp_terminal_ascii_use_edges = BoolProperty(
        name="Use Edges", description="Enable directional slash, dash and bar glyphs where local luminance gradients detect an edge. Disable it to render only tonal fill characters.",
        default=True, update=update_terminal_ascii_use_edges_cb)
    bpy.types.Object.fbp_terminal_ascii_edge_strength = FloatProperty(
        name="Edge Strength", description="Multiply local luminance gradients before edge thresholding. Higher values reveal weaker contours but can introduce noisy edge glyphs.",
        default=4.0, min=0.0, soft_max=12.0, max=32.0, update=update_terminal_ascii_edge_strength_cb)
    bpy.types.Object.fbp_terminal_ascii_edge_threshold = FloatProperty(
        name="Edge Threshold", description="Minimum amplified local luminance difference required to replace a fill glyph with a directional edge glyph. Raise it to keep only strong contours.",
        default=0.08, min=0.0, max=1.0, subtype='FACTOR', update=update_terminal_ascii_edge_threshold_cb)
    bpy.types.Object.fbp_terminal_ascii_edge_mix = FloatProperty(
        name="Edge Mix", description="Blend directional edge glyphs over the tonal fill result. Zero keeps only fill characters; one gives detected edges full priority.",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_terminal_ascii_edge_mix_cb)
    bpy.types.Object.fbp_terminal_ascii_use_source_color = BoolProperty(
        name="Use Source Color", description="Sample the source image color for every generated fill and edge glyph. Disable it to use the uniform terminal Text Color.",
        default=False, update=update_terminal_ascii_use_source_color_cb)
    bpy.types.Object.fbp_terminal_ascii_foreground = FloatVectorProperty(description="RGBA terminal-glyph color used by the Ascii effect when source-color mode is disabled.",
        name="Text Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.42, 1.0, 0.42, 1.0), update=update_terminal_ascii_foreground_cb)
    bpy.types.Object.fbp_terminal_ascii_background = FloatVectorProperty(description="RGBA color placed behind Ascii fill and edge glyphs when transparent background is disabled.",
        name="Background Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_terminal_ascii_background_cb)
    bpy.types.Object.fbp_terminal_ascii_transparent_background = BoolProperty(
        name="Transparent Background", description="Keep only generated terminal glyphs and preserve transparent gaps between them. Disable it to fill those gaps with Background Color.",
        default=True, update=update_terminal_ascii_transparent_background_cb)
    bpy.types.Object.fbp_terminal_ascii_seed = FloatProperty(
        name="Evolution Seed",
        description="Deterministic terminal-glyph variation. Animate it directly or enable Evolution for stepped non-repeating changes",
        default=0.0, soft_min=-100000.0, soft_max=100000.0, precision=0,
        update=update_terminal_ascii_seed_cb)

    bpy.types.Object.fbp_text_matrix_character_count = IntProperty(
        name="Character Levels", description="Number of distinct glyph-density steps used by Text Matrix. More levels improve tonal detail but increase generated text complexity.",
        default=16, min=2, max=ASCII_TEXT_GLYPH_LIMIT, update=update_text_matrix_character_count_cb)
    bpy.types.Object.fbp_text_matrix_character_aspect = FloatProperty(
        name="Character Aspect", description="Width-to-height compensation applied to each Text Matrix cell for the selected vector font. Adjust it when glyphs appear stretched or compressed.",
        default=0.60, min=0.1, max=2.0, update=update_text_matrix_character_aspect_cb)
    bpy.types.Object.fbp_text_matrix_glyph_scale = FloatProperty(
        name="Glyph Scale", description="Scale each generated Text Matrix glyph inside its cell. Values below one increase spacing; values above one can overlap neighboring cells.",
        default=0.88, min=0.05, max=2.0, update=update_text_matrix_glyph_scale_cb)
    bpy.types.Object.fbp_text_matrix_contrast = FloatProperty(description="Contrast used to map source luminance to real Text Matrix glyph density. Higher values emphasize the lightest and densest characters.",
        name="Contrast", default=1.3, min=0.0, soft_max=4.0, max=8.0, update=update_text_matrix_contrast_cb)
    bpy.types.Object.fbp_text_matrix_invert = BoolProperty(description="Reverse Text Matrix luminance mapping so bright areas receive dense glyphs and dark areas receive light glyphs.",
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
        name="Font", description="Optional Blender Vector Font used to generate real Text Matrix geometry. Leave empty to use Blender's built-in font; changing it rebuilds glyph geometry.",
        type=bpy.types.VectorFont, update=update_text_matrix_font_cb)
    bpy.types.Object.fbp_text_matrix_use_source_color = BoolProperty(
        name="Use Source Color",
        description="Color each vector glyph with the sampled source pixel instead of Text Color",
        default=True, update=update_text_matrix_use_source_color_cb)
    bpy.types.Object.fbp_text_matrix_text_color = FloatVectorProperty(description="RGBA color assigned to generated Text Matrix glyph geometry when source-color sampling is disabled.",
        name="Text Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.1, 1.0, 0.2, 1.0), update=update_text_matrix_text_color_cb)
    bpy.types.Object.fbp_text_matrix_background_color = FloatVectorProperty(description="RGBA background color generated behind Text Matrix glyphs when transparent background is disabled.",
        name="Background Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_text_matrix_background_color_cb)
    bpy.types.Object.fbp_hue_saturation_hue = FloatProperty(description="Hue rotation centered at the neutral value 0.5. Move below or above 0.5 to rotate colors in opposite directions.", name="Hue", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_hue_saturation_hue_cb)
    bpy.types.Object.fbp_hue_saturation_saturation = FloatProperty(description="Multiply source saturation. Zero produces grayscale, one preserves the source, and values above one intensify color.", name="Saturation", default=1.0, min=0.0, soft_max=2.0, update=update_hue_saturation_saturation_cb)
    bpy.types.Object.fbp_hue_saturation_value = FloatProperty(description="Multiply source brightness/value. One preserves the source; lower values darken and higher values brighten.", name="Value", default=1.0, min=0.0, soft_max=2.0, update=update_hue_saturation_value_cb)
    bpy.types.Object.fbp_brightness_contrast_brightness = FloatProperty(description="Add or subtract brightness before the effect output. Zero leaves source brightness unchanged.", name="Brightness", default=0.0, soft_min=-1.0, soft_max=1.0, update=update_brightness_contrast_brightness_cb)
    bpy.types.Object.fbp_brightness_contrast_contrast = FloatProperty(description="Increase or decrease separation around middle gray. Zero leaves source contrast unchanged.", name="Contrast", default=0.0, soft_min=-1.0, soft_max=1.0, update=update_brightness_contrast_contrast_cb)
    bpy.types.Object.fbp_invert_factor = FloatProperty(description="Blend between the original image and its inverted colors. Zero is unchanged; one is fully inverted.", name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_invert_factor_cb)
    bpy.types.Object.fbp_threshold_value = FloatProperty(description="Luminance cutoff used to separate pixels into black and white regions. Values below the threshold become dark.", name="Threshold", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_threshold_value_cb)
    bpy.types.Object.fbp_posterize_steps = FloatProperty(description="Number of discrete color levels retained per channel by Posterize. Lower values create stronger graphic banding.",
        name="Color Steps", default=4.0, min=2.0, soft_max=64.0, precision=0, update=update_posterize_steps_cb)
    bpy.types.Object.fbp_solid_mask_color = FloatVectorProperty(description="RGBA color blended over the source by Solid Mask.",
        name="Mask Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.0, 1.0), update=update_solid_mask_color_cb)
    bpy.types.Object.fbp_solid_mask_factor = FloatProperty(description="Blend amount between the original source and Solid Mask color. Zero keeps the source; one outputs only the mask color.",
        name="Mask Factor", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_solid_mask_factor_cb)
    bpy.types.Object.fbp_color_isolate_target = FloatVectorProperty(description="Color that Color Isolate keeps or emphasizes while suppressing colors outside the tolerance range.", name="Target Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.0, 0.0, 1.0), update=update_color_isolate_target_cb)
    bpy.types.Object.fbp_color_isolate_tolerance = FloatProperty(description="Maximum color distance considered a match to the target color. Higher values include a broader range of hues.", name="Tolerance", default=0.15, min=0.0, max=1.0, subtype='FACTOR', update=update_color_isolate_tolerance_cb)
    bpy.types.Object.fbp_color_isolate_falloff = FloatProperty(description="Soft transition width around the Color Isolate tolerance boundary. Higher values create smoother masks.", name="Falloff", default=0.1, min=0.0, max=1.0, subtype='FACTOR', update=update_color_isolate_falloff_cb)
    bpy.types.Object.fbp_duotone_shadows = FloatVectorProperty(description="RGBA color mapped to dark source values by Duotone.", name="Shadows Tone", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.2, 1.0), update=update_duotone_shadows_cb)
    bpy.types.Object.fbp_duotone_highlights = FloatVectorProperty(description="RGBA color mapped to bright source values by Duotone.", name="Highlights Tone", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.8, 0.6, 1.0), update=update_duotone_highlights_cb)
    bpy.types.Object.fbp_recolor_factor = FloatProperty(
        description="Blend between the original source and the colors mapped through the editable Color Ramp.",
        name="Factor", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_recolor_factor_cb)
    bpy.types.Object.fbp_paper_fiber_scale = FloatProperty(description="Spatial frequency of Paper Fibers. Higher values produce finer, more numerous fibers.", name="Fiber Scale", default=140.0, min=0.01, soft_max=3000.0, precision=1, update=update_paper_fiber_scale_cb)
    bpy.types.Object.fbp_paper_fiber_intensity = FloatProperty(description="Strength of Paper Fibers mixed into the source image.", name="Intensity", default=0.40, min=0.0, max=1.0, subtype='FACTOR', update=update_paper_fiber_intensity_cb)
    bpy.types.Object.fbp_paper_fiber_phase = FloatProperty(description="Fourth-dimensional noise coordinate used to animate or select a different Paper Fibers pattern.", name="Animate (W)", default=0.0, soft_min=-100.0, soft_max=100.0, precision=3, update=update_paper_fiber_phase_cb)
    bpy.types.Object.fbp_gradient_light_angle = FloatProperty(description="Direction of Gradient Light across the plane, expressed as an angle.", name="Light Angle", default=0.0, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_gradient_light_angle_cb)
    bpy.types.Object.fbp_gradient_light_strength = FloatProperty(description="Blend between the original source and the directional Color Ramp lighting.", name="Strength", default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=update_gradient_light_strength_cb)
    bpy.types.Object.fbp_gradient_shadow_position = FloatProperty(description="Offset of the Gradient Light shadow boundary across the plane.", name="Shadow Position", default=0.0, soft_min=-2.0, soft_max=2.0, precision=3, update=update_gradient_shadow_position_cb)
    bpy.types.Object.fbp_gradient_softness = FloatProperty(description="Width of the Gradient Light transition between lit and shadowed regions.", name="Softness", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=update_gradient_softness_cb)
    bpy.types.Object.fbp_gradient_shadow_color = FloatVectorProperty(description="RGBA color mixed into the shadow side of Gradient Light.", name="Shadow Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.05, 1.0), update=update_gradient_shadow_color_cb)
    bpy.types.Object.fbp_rim_width = FloatProperty(description="UV sampling distance used to find the source alpha edge. Larger values create a wider rim.", name="Width", default=0.012, min=0.00001, soft_max=0.1, max=0.5, precision=5, update=update_rim_width_cb)
    bpy.types.Object.fbp_rim_softness = FloatProperty(description="Softness of the colored rim transition.", name="Softness", default=0.25, min=0.0, max=1.0, subtype='FACTOR', update=update_rim_softness_cb)
    bpy.types.Object.fbp_rim_intensity = FloatProperty(description="Opacity and strength of the colored rim.", name="Intensity", default=1.0, min=0.0, soft_max=2.0, max=2.0, update=update_rim_intensity_cb)
    bpy.types.Object.fbp_rim_color = FloatVectorProperty(description="RGBA color applied to the generated rim.", name="Rim Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 0.35, 0.05, 1.0), update=update_rim_color_cb)
    bpy.types.Object.fbp_gobo_pattern_scale = FloatProperty(description="Spatial scale of the procedural Gobo Shadows pattern. Higher values create smaller projected shapes.", name="Pattern Scale", default=10.0, min=0.001, soft_max=100.0, precision=3, update=update_gobo_pattern_scale_cb)
    bpy.types.Object.fbp_gobo_rotation = FloatProperty(description="Rotate the Gobo Shadows pattern around the plane center.", name="Rotation Angle", default=0.5, soft_min=-3.141593, soft_max=3.141593, subtype='ANGLE', update=update_gobo_rotation_cb)
    bpy.types.Object.fbp_gobo_sharpness = FloatProperty(description="Hardness of Gobo Shadows pattern edges. Lower values blur transitions; higher values create crisp shapes.", name="Sharpness", default=0.8, min=0.0, max=1.0, subtype='FACTOR', update=update_gobo_sharpness_cb)
    bpy.types.Object.fbp_crt_line_count = FloatProperty(description="Approximate number of horizontal CRT scanlines distributed across the image height.", name="Line Count", default=200.0, min=1.0, soft_max=2000.0, precision=0, update=update_crt_line_count_cb)
    bpy.types.Object.fbp_crt_opacity = FloatProperty(description="Strength of dark CRT scanlines blended over the source image.", name="Opacity", default=0.15, min=0.0, max=1.0, subtype='FACTOR', update=update_crt_opacity_cb)
    bpy.types.Object.fbp_vignette_radius = FloatProperty(description="Distance from the image center before Vignette darkening becomes prominent.", name="Radius", default=0.5, min=0.0, soft_max=2.0, precision=3, update=update_vignette_radius_cb)
    bpy.types.Object.fbp_vignette_smoothness = FloatProperty(description="Width and softness of the Vignette transition. Higher values create a broader gradual falloff.", name="Smoothness", default=0.2, min=0.0, max=1.0, subtype='FACTOR', update=update_vignette_smoothness_cb)
    bpy.types.Object.fbp_vignette_strength = FloatProperty(description="Maximum amount of Vignette darkening applied near the image edges.", name="Strength", default=0.8, min=0.0, max=1.0, subtype='FACTOR', update=update_vignette_strength_cb)

    _register_effect_animation_properties()


# SECTION 03 - Unregister properties #
def _unregister_fbp_type_properties(owner):
    """Remove every Frame by Plane RNA property registered on ``owner``."""
    for attr in tuple(dir(owner)):
        if not (attr.startswith("fbp_") or attr.startswith("is_fbp_")):
            continue
        try:
            delattr(owner, attr)
        except FBP_DATA_IO_ERRORS:
            pass


def unregister_properties():
    _unregister_effect_animation_properties()
    for owner in (bpy.types.Scene, bpy.types.Collection, bpy.types.Object):
        _unregister_fbp_type_properties(owner)


# SECTION 04 - Registerable classes #
property_classes = (
    FBP_AddonPreferences,
    FBP_LayerItem,
    FBP_EffectItem,
    FBP_EffectGroupItem,
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
                    except FBP_DATA_ERRORS:
                        pass
    except FBP_DATA_ERRORS:
        pass


def unregister():
    unregister_properties()
    for cls in reversed(property_classes):
        try:
            bpy.utils.unregister_class(cls)
        except FBP_DATA_IO_ERRORS:
            pass
