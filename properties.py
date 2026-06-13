"""Scene, Object, Collection and add-on preference properties."""

import bpy
from bpy.props import (
    StringProperty, IntProperty, BoolProperty, FloatProperty, FloatVectorProperty,
    CollectionProperty, PointerProperty, EnumProperty
)
from bpy.types import PropertyGroup, AddonPreferences

try:
    from .constants import COLOR_ENUM_ITEMS, COLLECTION_COLOR_ENUM_ITEMS, fbp_icon
except ImportError:
    from constants import COLOR_ENUM_ITEMS, COLLECTION_COLOR_ENUM_ITEMS, fbp_icon


# SECTION 00B - Proxy callbacks to core.py #
def _fbp_core_func(name):
    try:
        from . import core
    except ImportError:
        import core
    return getattr(core, name)


def _call_core(name, *args, default=None):
    try:
        return _fbp_core_func(name)(*args)
    except ReferenceError:
        return default
    except Exception as exc:
        try:
            print(f"[FBP Warning] Properties callback failed: {name}: {exc}")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        return default


# SECTION 00C - Add-on Preferences #
class FBP_AddonPreferences(AddonPreferences):
    bl_idname = __package__ if __package__ else "frame_by_plane"

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Image sequences", icon='IMAGE_DATA')
        box.label(text="Uses Blender native Image Sequence nodes.")
        box.label(text="One material per image layer; timing is handled through ImageUser.")

def update_cam_ratio_cb(self, context):
    return _call_core('update_cam_ratio_cb', self, context)

def update_color_plane_color_cb(self, context):
    return _call_core('update_color_plane_color_cb', self, context)

def update_color_plane_preset_cb(self, context):
    return _call_core('update_color_plane_preset_cb', self, context)

def update_color_tag_cb(self, context):
    return _call_core('update_color_tag_cb', self, context)

def update_emission_cb(self, context):
    return _call_core('update_emission_cb', self, context)

def update_extend_plane_cb(self, context):
    return _call_core('update_extend_plane_cb', self, context)

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
        try:
            print(f"[FBP Warning] Could not update pending collection color: {exc}")
        except Exception:
            pass

def update_loop_mode_cb(self, context):
    return _call_core('update_loop_mode_cb', self, context)

def update_mute_cb(self, context):
    return _call_core('update_mute_cb', self, context)

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
    return _call_core('get_collection_holdout', self, default=False)

def get_collection_locked(self):
    return _call_core('get_collection_locked', self, default=False)

def get_collection_selected(self):
    return _call_core('get_collection_selected', self, default=False)

def get_collection_solo(self):
    return _call_core('get_collection_solo', self, default=False)

def get_collection_visible(self):
    return _call_core('get_collection_visible', self, default=False)

def get_layer_holdout(self):
    return _call_core('get_layer_holdout', self, default=False)

def get_layer_plane_locked(self):
    return _call_core('get_layer_plane_locked', self, default=False)

def get_layer_rig_locked(self):
    return _call_core('get_layer_rig_locked', self, default=False)

def get_layer_selected(self):
    return _call_core('get_layer_selected', self, default=False)

def get_layer_solo_view(self):
    return _call_core('get_layer_solo_view', self, default=False)

def set_collection_holdout(self, value):
    return _call_core('set_collection_holdout', self, value)

def set_collection_locked(self, value):
    return _call_core('set_collection_locked', self, value)

def get_collection_plane_locked(self):
    return _call_core('get_collection_plane_locked', self, default=True)

def set_collection_plane_locked(self, value):
    return _call_core('set_collection_plane_locked', self, value)

def set_collection_selected(self, value):
    return _call_core('set_collection_selected', self, value)

def set_collection_solo(self, value):
    return _call_core('set_collection_solo', self, value)

def set_collection_visible(self, value):
    return _call_core('set_collection_visible', self, value)

def set_layer_holdout(self, value):
    return _call_core('set_layer_holdout', self, value)

def set_layer_plane_locked(self, value):
    return _call_core('set_layer_plane_locked', self, value)

def set_layer_rig_locked(self, value):
    return _call_core('set_layer_rig_locked', self, value)

def set_layer_selected(self, value):
    return _call_core('set_layer_selected', self, value)

def set_layer_solo_view(self, value):
    return _call_core('set_layer_solo_view', self, value)

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
    rebuilt only for display, so the UIList can show folder/scene headers and
    collapsible children without changing the actual import model.
    """
    row_type: EnumProperty(
        name="Row Type",
        items=[
            ('GROUP', "Group", "Folder or Scene header row"),
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
    is_scene: BoolProperty(name="Scene Row", default=False)
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
    bpy.types.Scene.fbp_import_main_folders_as_scenes = BoolProperty(
        name="Main Folders as Scenes",
        description="Create one Blender Scene for each top-level project folder. Folders starting with _ are ignored",
        default=False)
    bpy.types.Scene.fbp_cam_ratio = EnumProperty(
        name="Camera Ratio",
        items=[
            ('CUSTOM',       "Custom",         "Use the render resolution set below"),
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
            ('ULTRAWIDE_21_9', "21:9",          "2520x1080 ultrawide format"),
            ('A4_LANDSCAPE', "A4 Landscape",   "2480x1754 paper ratio"),
            ('A4_PORTRAIT',  "A4 Portrait",    "1754x2480 paper ratio"),
        ],
        default='4_3', update=update_cam_ratio_cb)
    bpy.types.Scene.fbp_show_previews = BoolProperty(name="Show Thumbnails", description="Show image thumbnails for imported image/video layers", default=False)
    bpy.types.Scene.fbp_show_color_previews = BoolProperty(name="Show Color Preview", description="Show color/gradient chips in Layer and Frame lists instead of generic procedural icons", default=True)
    bpy.types.Scene.fbp_sort_layers_alpha = BoolProperty(
        name="A-Z",
        description="Sort layers and collections alphabetically instead of by camera distance",
        default=False)
    bpy.types.Scene.fbp_layer_list_rows = IntProperty(
        name="Layer Rows",
        description="Maximum number of direct layer rows shown inside each expanded collection",
        default=12, min=4, max=40)
    bpy.types.Scene.fbp_layer_filter_collection = StringProperty(default="")
    bpy.types.Scene.fbp_pending_filter_collection = StringProperty(default="")
    bpy.types.Scene.fbp_auto_clean_orphans = BoolProperty(
        name="Auto-clean orphan Frame by Plane objects",
        description="After normal deletion, remove FBP planes left without their rig and purge unused FBP datablocks. Image files on disk are never deleted",
        default=True)
    bpy.types.Scene.fbp_show_create_tools = BoolProperty(name="Show Create Tools", description="Show additional creation tools in the sidebar", default=False)
    bpy.types.Scene.fbp_emergency_render_start = IntProperty(name="Start", description="First frame for the emergency background render", default=0, min=0)
    bpy.types.Scene.fbp_emergency_render_end = IntProperty(name="End", description="Last frame for the emergency background render", default=0, min=0)
    bpy.types.Scene.fbp_emergency_render_prefix = StringProperty(name="Prefix", description="Filename prefix used for emergency rendered frames", default="frame_")
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
        items=[
            ('COLOR',  "Color Plane", "Solid, gradient or holdout procedural plane", fbp_icon("IMAGE"), 0),
            ('SINGLE', "Single Plane", "Single independent image sequence plane", fbp_icon("IMAGE_DATA"), 1),
            ('MULTI',  "Multiplane",   "Layered/parallax image project setup", fbp_icon("RENDERLAYERS"), 2),
        ],
        default='COLOR')
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
        items=[
            ('NONE',     "One Shot",  "Play once",      fbp_icon("FORWARD"),        0),
            ('REPEAT',   "Loop",      "Repeat forever", fbp_icon("FILE_REFRESH"),   1),
            ('PINGPONG', "Ping-Pong", "Back and forth", fbp_icon("UV_SYNC_SELECT"), 2),
        ],
        default='NONE')
    bpy.types.Scene.fbp_pre_interpolation = EnumProperty(
        name="",
        items=[
            ('Closest', "Pixel",  "Sharp edges (pixel art)", fbp_icon("ALIASED"),     0),
            ('Linear',  "Smooth", "Bilinear filter",         fbp_icon("ANTIALIASED"), 1),
        ],
        default='Closest')
    bpy.types.Scene.fbp_pre_orientation = EnumProperty(
        name="",
        items=[
            ('HORIZ', "Horizontal", "Planes on the floor", fbp_icon("AXIS_TOP"),   0),
            ('VERT',  "Vertical",   "Standing planes",     fbp_icon("AXIS_FRONT"), 1),
        ],
        default='VERT')
    bpy.types.Scene.fbp_gen_camera   = BoolProperty(name="Generate Camera", description="Create or update a camera suitable for the generated multiplane setup", default=True)
    bpy.types.Scene.fbp_cam_pivot    = BoolProperty(name="Pivot on Camera", description="Move the 3D cursor to the camera pivot when creating a camera setup", default=True)
    bpy.types.Scene.fbp_layer_offset = FloatProperty(name="Plane Distance (m)", description="Distance between generated layers; imported top-level collections use a larger gap", default=0.2, min=0.001)
    bpy.types.Scene.fbp_auto_scale   = BoolProperty(name="Auto-Scale (Fit to Cam)", description="Scale generated planes to the camera frame using the image aspect ratio", default=True)
    bpy.types.Scene.fbp_settings_section = EnumProperty(
        name="Settings Section",
        description="Choose which Frame by Plane settings group to display",
        items=[
            ('PROJECT', "Project", "Project and folder import settings"),
            ('MAINTENANCE', "Maintenance", "Repair, relink and diagnostics tools"),
            ('RENDER', "Render", "Background render controls"),
            ('DISPLAY', "Display", "Output ratio, thumbnails and display options"),
        ],
        default='PROJECT')
    bpy.types.Scene.fbp_show_project_tools = BoolProperty(name="Project Import", description="Show advanced project and folder import controls", default=True)
    bpy.types.Scene.fbp_color_plane_type = EnumProperty(
        name="Plane Type",
        description="Choose what kind of camera-ratio plane to create",
        items=[
            ('CUSTOM', "Color", "Create a custom solid color camera-ratio plane", fbp_icon("IMAGE"), 0),
            ('GRADIENT', "Gradient", "Create an editable ColorRamp gradient plane for vignettes, fades and in-camera masks", fbp_icon("NODE_TEXTURE"), 1),
            ('HOLDOUT', "Holdout", "Create a holdout mask plane for compositing", fbp_icon("GHOST_DISABLED"), 2),
        ],
        default='CUSTOM')
    bpy.types.Scene.fbp_color_plane_color = FloatVectorProperty(
        name="Color", description="Solid color used when creating a Color Plane", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0), update=update_color_plane_color_cb)
    bpy.types.Scene.fbp_color_plane_preset = EnumProperty(
        name="Preset",
        description="Quick color preset for solid Color Plane creation",
        items=[
            ('CUSTOM', "Custom", "Use the manually chosen color", fbp_icon("MESH_PLANE"), 0),
            ('BLACK', "Black", "Pure black", fbp_icon("COLORSET_20_VEC"), 1),
            ('WHITE', "White", "Pure white", fbp_icon("SNAP_FACE"), 2),
            ('MIDDLE_GREY', "Middle Grey", "50% grey", fbp_icon("STRIP_COLOR_09"), 3),
            ('GREENSCREEN', "Greenscreen", "Chroma green", fbp_icon("STRIP_COLOR_04"), 4),
            ('BLUE', "Blue", "#6697FFFF", fbp_icon("STRIP_COLOR_05"), 5),
            ('PURPLE', "Purple", "#9450F3FF", fbp_icon("STRIP_COLOR_06"), 6),
            ('ROSE', "Rose", "Rose / pink", fbp_icon("STRIP_COLOR_07"), 7),
            ('ORANGE', "Yellow", "#FFB300FF", fbp_icon("STRIP_COLOR_02"), 8),
            ('RED', "Red", "Basic red", fbp_icon("STRIP_COLOR_01"), 9),
        ],
        default='CUSTOM', update=update_color_plane_preset_cb)
    bpy.types.Scene.fbp_color_plane_emission = BoolProperty(name="Emission", description="Use a lightweight emission shader for the color plane", default=True, update=update_scene_gradient_preview_cb)
    bpy.types.Scene.fbp_gradient_mode = EnumProperty(
        name="Gradient Mode", description="Shape of the generated gradient color plane",
        items=[('LINEAR', "Linear", "Linear gradient from one side of the plane to the other", fbp_icon("ARROW_LEFTRIGHT"), 0), ('CENTER', "Radial", "Centered radial gradient useful for vignettes", fbp_icon("EMPTY_ARROWS"), 1)], default='LINEAR', update=update_scene_gradient_preview_cb)
    bpy.types.Scene.fbp_gradient_kind = EnumProperty(
        name="Gradient Type", description="Choose whether the gradient blends between two colors or changes alpha",
        items=[('COLOR', "Color to Color", "Blend from Color A to Color B with full opacity", fbp_icon("COLOR"), 0), ('ALPHA', "Transparent to Visible", "Fade from transparent to the selected visible color", fbp_icon("IMAGE_ALPHA"), 1)], default='COLOR', update=update_scene_gradient_preview_cb)
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
    bpy.types.Scene.fbp_extend_mode = EnumProperty(
        name="Extend Mode",
        items=[
            ('EDGE', "Edge Pixel", "Extend the side pixel/edge UV without deforming the center image"),
            ('REPEAT', "Repeat Texture", "Repeat the texture into the extension area"),
        ],
        default='EDGE', update=update_extend_plane_cb)
    bpy.types.Scene.fbp_extend_left = FloatProperty(name="Left", description="Extend the left edge without scaling or deforming the central image", default=0.0, min=0.0, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_extend_plane_cb)
    bpy.types.Scene.fbp_extend_right = FloatProperty(name="Right", description="Extend the right edge without scaling or deforming the central image", default=0.0, min=0.0, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_extend_plane_cb)
    bpy.types.Scene.fbp_extend_top = FloatProperty(name="Top", description="Extend the top edge without scaling or deforming the central image", default=0.0, min=0.0, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_extend_plane_cb)
    bpy.types.Scene.fbp_extend_bottom = FloatProperty(name="Bottom", description="Extend the bottom edge without scaling or deforming the central image", default=0.0, min=0.0, soft_min=0.0, soft_max=1.0, step=1, precision=3, update=update_extend_plane_cb)

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
    bpy.types.Object.fbp_base_scale     = FloatProperty(name="Base Scale", description="Original generated scale used by Fit to Camera", default=1.0)
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


# SECTION 03 - Unregister properties #
def unregister_properties():
    for attr in ['fbp_last_directory', 'fbp_project_path', 'fbp_parent_import_path', 'fbp_import_main_folders_as_scenes', 'fbp_cam_ratio', 'fbp_show_previews', 'fbp_show_color_previews', 'fbp_sort_layers_alpha', 'fbp_layer_list_rows', 'fbp_layer_filter_collection', 'fbp_pending_filter_collection', 'fbp_auto_clean_orphans', 'fbp_show_create_tools', 'fbp_emergency_render_start', 'fbp_emergency_render_end', 'fbp_emergency_render_prefix', 'fbp_background_render_running', 'fbp_background_render_status', 'fbp_background_render_progress', 'fbp_background_render_total', 'fbp_background_render_output_dir', 'fbp_generation_rename_items', 'fbp_generation_rename_index', 'fbp_auto_collection_color_variants', 'fbp_layers', 'fbp_layer_stack_index', 'fbp_layer_tree_rows', 'fbp_layer_tree_rows_idx', 'fbp_layer_tree_signature', 'fbp_pending_open_collections', 'fbp_gradient_preview_material_name', 'fbp_creation_mode', 'fbp_pending_planes', 'fbp_pending_planes_idx', 'fbp_pending_tree_rows', 'fbp_pending_tree_rows_idx', 'fbp_pending_collection_name', 'fbp_pre_duration', 'fbp_pre_shadeless', 'fbp_pre_loop_mode', 'fbp_pre_interpolation', 'fbp_pre_orientation', 'fbp_gen_camera', 'fbp_cam_pivot', 'fbp_layer_offset', 'fbp_auto_scale', 'fbp_settings_section', 'fbp_show_project_tools', 'fbp_color_plane_type', 'fbp_color_plane_color', 'fbp_color_plane_preset', 'fbp_color_plane_emission', 'fbp_gradient_mode', 'fbp_gradient_kind', 'fbp_gradient_color_a', 'fbp_gradient_color_b', 'fbp_gradient_reverse', 'fbp_gradient_offset_x', 'fbp_gradient_offset_y', 'fbp_gradient_scale_x', 'fbp_gradient_scale_y', 'fbp_gradient_rotation', 'fbp_show_gradient_ramp', 'fbp_show_gradient_transform', 'fbp_extend_mode', 'fbp_extend_left', 'fbp_extend_right', 'fbp_extend_top', 'fbp_extend_bottom']:
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
    for attr in ['is_fbp_control', 'is_fbp_plane', 'fbp_collection_name', 'fbp_follow_collection_color', 'fbp_color_variant_index', 'fbp_base_scale', 'fbp_base_scale_vec', 'fbp_preview_path', 'fbp_is_vertical', 'fbp_images', 'fbp_images_index', 'fbp_color_tag', 'fbp_depth_order', 'fbp_loop_mode', 'fbp_use_emission', 'fbp_interpolation', 'fbp_plane_target', 'fbp_global_duration', 'fbp_start_frame', 'fbp_opacity', 'fbp_track_cam', 'fbp_is_visible', 'fbp_is_color_plane', 'fbp_color_plane_mode', 'fbp_color_plane_color', 'fbp_color_plane_emission', 'fbp_gradient_mode', 'fbp_gradient_kind', 'fbp_gradient_color_a', 'fbp_gradient_color_b', 'fbp_gradient_reverse', 'fbp_gradient_offset_x', 'fbp_gradient_offset_y', 'fbp_gradient_scale_x', 'fbp_gradient_scale_y', 'fbp_gradient_rotation', 'fbp_show_gradient_ramp', 'fbp_show_gradient_transform', 'fbp_extend_mode', 'fbp_extend_left', 'fbp_extend_right', 'fbp_extend_top', 'fbp_extend_bottom', 'fbp_crop_left', 'fbp_crop_right', 'fbp_crop_top', 'fbp_crop_bottom']:
        if hasattr(bpy.types.Object, attr):
            try:
                delattr(bpy.types.Object, attr)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass


# SECTION 04 - Registerable classes #
property_classes = (
    FBP_AddonPreferences,
    FBP_LayerItem,
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


def unregister():
    unregister_properties()
    for cls in reversed(property_classes):
        try:
            bpy.utils.unregister_class(cls)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
